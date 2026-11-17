"""Turns per-frame hand observations into actions. Pure logic: no camera or OS calls."""
import math
from collections import deque

PALM = (0, 5, 9, 13, 17)  # wrist + the four knuckles: barely moves when fingers pinch or curl
FINGERS = ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))  # index, middle, ring, pinky joints
PINCHES = {"Pinch": "pinch", "Pinch_Middle": "pinch_middle"}  # gesture name -> feature it is measured by
POSES = ("Thumb_Up", "Thumb_Down", "Victory", "ILoveYou")  # MediaPipe's trained poses, used as they come
POSE_SCORE = 0.6  # below this confidence a trained pose is ignored, so half-formed poses don't fire actions
CURLED = 0.6  # finger extension below this = curled (a straight finger is 1.0, a fist about 0.4)
QUICK = ("Hand", "Pinch", "Pinch_Middle")  # these switch after QUICK_HOLD so clicks feel instant; the rest wait hold_ms
QUICK_HOLD = 0.06  # seconds, about two frames
GRACE = 0.3  # seconds a hand may vanish (tracking dropout) before it counts as gone
LOOKBACK = 0.1  # seconds: a click lands where the cursor was before the closing fingers nudged the hand


def anchor(lm):
    """Cursor anchor: the palm centre, in image coordinates."""
    return sum(lm[i][0] for i in PALM) / 5, sum(lm[i][1] for i in PALM) / 5


def features(world):
    """Shape measures from MediaPipe's 3D world landmarks, so they hold when the hand is tilted or turned.
    pinch / pinch_middle: thumb tip to index / middle fingertip, in hand sizes (small = touching).
    ext: per finger, straight-line knuckle-to-tip distance over the finger's length."""
    size = math.dist(world[0], world[9])
    ext = [math.dist(world[m], world[t]) / (math.dist(world[m], world[p]) + math.dist(world[p], world[d]) + math.dist(world[d], world[t]))
           for m, p, d, t in FINGERS]
    return {"pinch": math.dist(world[4], world[8]) / size, "pinch_middle": math.dist(world[4], world[12]) / size, "ext": ext}


class Classifier:
    """Names the pose of one hand: Hand (anything unremarkable), Pinch, Pinch_Middle, Closed_Fist or one of POSES.
    Keeps state so a pinch or fist doesn't flicker when its measure sits near the threshold."""

    def __init__(self, cfg):
        self.cfg, self.held = cfg, None

    def __call__(self, canned, score, world):
        """canned, score: MediaPipe's gesture name and confidence. Returns (pose name, features)."""
        f = features(world)
        enter = self.cfg["pinch_threshold"]
        if self.held in PINCHES:
            still = f[PINCHES[self.held]] < enter * 1.5  # fingers must clearly part before a pinch ends
        else:
            still = self.held == "Closed_Fist" and max(f["ext"]) < CURLED + 0.1
        if still:
            return self.held, f
        self.held = None
        # the pinching finger must not be curled up, which is what tells a pinch from a fist
        pinches = [name for name, finger in (("Pinch", 0), ("Pinch_Middle", 1)) if f[PINCHES[name]] < enter and f["ext"][finger] >= CURLED]
        if pinches:
            self.held = min(pinches, key=lambda name: f[PINCHES[name]])
        elif canned in POSES and score >= POSE_SCORE:
            return canned, f
        elif f["ext"][0] < CURLED and (canned == "Closed_Fist" or max(f["ext"]) < CURLED):
            self.held = "Closed_Fist"
        return self.held or "Hand", f


def assign(found, last, t, mirror=True):
    """Two-hand mode: which detection is the user's Left / Right hand. Returns {side: index into found}.
    found: [(MediaPipe's label, (x, y))]; last: {side: (time, (x, y))}, where each hand was last seen.
    MediaPipe's label flips when a hand turns edge-on, so position decides whenever it can."""
    if not found:
        return {}
    if len(found) >= 2:
        a, b = sorted(range(2), key=lambda i: found[i][1][0])  # left to right in the image
        return {"Left": a, "Right": b} if mirror else {"Left": b, "Right": a}
    label, pos = found[0]
    recent = {side: p for side, (seen, p) in last.items() if t - seen < 0.5}
    if recent:
        side = min(recent, key=lambda s: math.dist(recent[s], pos))
        if len(recent) == 2 or math.dist(recent[side], pos) < 0.25:  # it's the hand that was just there
            return {side: 0}
    return {label: 0}


def _alpha(cutoff, dt):
    r = 2 * math.pi * cutoff * dt
    return r / (r + 1)


class OneEuro:
    """Smooths one value. Still hand -> heavy smoothing (no jitter); fast move -> light smoothing (no lag)."""

    def __init__(self, min_cutoff, beta):
        self.min_cutoff, self.beta = min_cutoff, beta
        self.x = self.dx = self.t = None

    def __call__(self, x, t):
        if self.x is None:
            self.x, self.dx, self.t = x, 0.0, t
            return x
        dt = max(t - self.t, 1e-3)
        self.t = t
        a = _alpha(1.0, dt)  # speed estimate is smoothed at a fixed 1 Hz
        self.dx = a * (x - self.x) / dt + (1 - a) * self.dx
        a = _alpha(self.min_cutoff + self.beta * abs(self.dx), dt)
        self.x = a * x + (1 - a) * self.x
        return self.x


class Engine:
    """One hand's state machine. update() returns events: ("move", x, y) with x, y in 0-1 of the screen,
    ("press",), ("release",), ("scroll", steps), ("run", mapping).
    role: "single" does everything; in two-hand mode "pointer" only moves the cursor and "action" never moves it."""

    def __init__(self, cfg, role="single"):
        self.cfg, self.role = cfg, role
        self.last_fire = {}
        self.reset()

    def reset(self):
        self.raw = self.current = None
        self.since = self.entered = self.seen = 0.0
        self.pos = None
        self.filters = [OneEuro(self.cfg["min_cutoff"], self.cfg["beta"]) for _ in range(2)]
        self.trail = deque()
        self.down = False
        self.last_y = None
        self.step_acc = 0.0

    def update(self, t, gesture, pos):
        """t: seconds; gesture: pose name, or None when this hand isn't visible; pos: palm centre in 0-1 of the frame."""
        if gesture is None:
            if self.current is None or t - self.seen < GRACE:
                return []  # nothing held, or a brief tracking dropout: keep the pose (and any drag) alive
            out = self._exit()
            self.reset()
            return out
        self.seen = t
        if self.role == "pointer":
            gesture = "Hand"  # the pointer hand only ever moves the cursor, whatever shape it makes
        out = []
        if gesture != self.raw:
            self.raw, self.since = gesture, t
        hold = QUICK_HOLD if gesture in QUICK else self.cfg["hold_ms"] / 1000
        if gesture != self.current and t - self.since >= hold:
            out += self._exit()
            self.current, self.entered = gesture, t
            out += self._enter(t)
        smooth = [f(v, t) for f, v in zip(self.filters, pos)]
        x0, y0, x1, y1 = self.cfg["box"]
        self.pos = tuple(min(max((v - lo) / max(hi - lo, 1e-3), 0.0), 1.0) for v, lo, hi in ((smooth[0], x0, x1), (smooth[1], y0, y1)))
        self.trail.append((t, self.pos))
        while t - self.trail[0][0] > 1.0:
            self.trail.popleft()
        act = self._action(self.current)
        if not act or self.raw != self.current:
            return out  # while the hand is changing shape (fingers closing to pinch), everything holds still
        if act["type"] == "mouse":
            value = act["value"]
            if self.role != "action" and (value == "move" or (value == "left" and t - self.entered >= self.cfg["drag_ms"] / 1000)):
                out.append(("move", *self.pos))
            elif value == "scroll":
                steps = self._steps(smooth[1])
                if steps:
                    out.append(("scroll", steps))
        elif act.get("repeat"):
            out += self._fire(self.current, act, t)
        return out

    def _action(self, name):
        act = self.cfg["mappings"].get(name) if name else None
        return act if act and act["type"] != "none" else None

    def _enter(self, t):
        act = self._action(self.current)
        if not act:
            return []
        if act["type"] != "mouse":
            return self._fire(self.current, act, t)
        if act["value"] == "scroll":
            self.last_y, self.step_acc = None, 0.0
        if act["value"] == "left":
            self.down = True
            return self._aim() + [("press",)]
        if act["value"] == "right":
            fired = self._fire(self.current, act, t)
            return self._aim() + fired if fired else []
        return []

    def _aim(self):
        """Put the cursor back where it was just before the fingers started closing, so the click lands on target."""
        if self.role == "action":
            return []
        past = [p for seen, p in self.trail if seen <= self.since - LOOKBACK]
        return [("move", *past[-1])] if past else []

    def _exit(self):
        if self.down:
            self.down = False
            return [("release",)]
        return []

    def _fire(self, name, act, t):
        if t - self.last_fire.get(name, -math.inf) < act.get("cooldown_ms", 0) / 1000:
            return []
        self.last_fire[name] = t
        return [("run", act)]

    def _steps(self, y):
        """Whole scroll steps of vertical hand motion since the last frame; up is positive."""
        steps = 0
        if self.last_y is not None:
            self.step_acc += (self.last_y - y) * self.cfg["scroll_speed"]
            steps = int(self.step_acc)
            self.step_acc -= steps
        self.last_y = y
        return steps
