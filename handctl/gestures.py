"""Turns per-frame hand observations into actions. Pure logic: no camera or OS calls."""
import math
from collections import deque

PALM = (0, 5, 9, 13, 17)  # wrist + the four knuckles: barely moves when fingers pinch or curl
FINGERS = ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))  # index, middle, ring, pinky joints
PINCHES = {"Pinch": "pinch", "Pinch_Middle": "pinch_middle", "Pinch_Ring": "pinch_ring", "Pinch_Pinky": "pinch_pinky"}  # pose -> feature
PINCH_FINGER = {"Pinch": 0, "Pinch_Middle": 1, "Pinch_Ring": 2, "Pinch_Pinky": 3}  # the finger touching the thumb in each pinch
SCROLLS = ("scroll", "hscroll", "zoom")  # mouse actions driven by moving the hand
POSES = ("Thumb_Up", "Thumb_Down", "Victory", "ILoveYou")  # MediaPipe's trained poses, used as they come
POSE_SCORE = 0.6  # below this confidence a trained pose is ignored, so half-formed poses don't fire actions
CURLED = 0.72  # a finger straighter than this can pinch. Measured on one user: pinching fingers 0.85-0.97, fist fingers 0.43-0.65
FIST = 0.72  # average straightness of the four fingers below this is a fist (measured: fists 0.42-0.68, open hands 0.85+)
QUICK = ("Hand", "Pinch", "Pinch_Middle")  # these switch after QUICK_HOLD so clicks feel instant; the rest wait hold_ms
SLOW = {"Pinch_Ring": 0.2, "Pinch_Pinky": 0.25}  # seconds. Ring and pinky pinches are harder to tell from the index finger
QUICK_HOLD = 0.06  # seconds, about two frames
GRACE = 0.3  # seconds a hand may vanish (tracking dropout) before it counts as gone
LOOKBACK = 0.1  # seconds: a click lands where the cursor was before the closing fingers nudged the hand


def cut_off(lm, limit=3):
    """True when the picture's edge cuts the hand off (a hand resting at the bottom edge, say): its pose can't be read, and
    guessing made stray clicks. Measured on one user: hands being used had 0-1 landmarks outside the picture, never 3 or more
    except while entering it; hands cut off by the edge had up to 13."""
    return sum(1 for x, y in lm if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0)) >= limit


def anchor(lm):
    """Cursor anchor: the palm centre, in image coordinates."""
    return sum(lm[i][0] for i in PALM) / 5, sum(lm[i][1] for i in PALM) / 5


def features(world):
    """Shape measures from MediaPipe's 3D world landmarks, so they hold when the hand is tilted or turned.
    pinch, pinch_middle, pinch_ring, pinch_pinky: thumb tip to that fingertip, in hand sizes (small = touching).
    ext: per finger, straight-line knuckle-to-tip distance over the finger's length."""
    size = math.dist(world[0], world[9])
    ext = [math.dist(world[m], world[t]) / (math.dist(world[m], world[p]) + math.dist(world[p], world[d]) + math.dist(world[d], world[t]))
           for m, p, d, t in FINGERS]
    return {"pinch": math.dist(world[4], world[8]) / size, "pinch_middle": math.dist(world[4], world[12]) / size,
            "pinch_ring": math.dist(world[4], world[16]) / size, "pinch_pinky": math.dist(world[4], world[20]) / size, "ext": ext}


class Classifier:
    """Names the pose of one hand: Hand (anything unremarkable), a Pinch (thumb to index, middle, ring or pinky fingertip),
    Closed_Fist, or one of POSES.
    Keeps state so a pinch or fist doesn't flicker when its measure sits near the threshold."""

    def __init__(self, cfg):
        self.cfg, self.held = cfg, None

    def __call__(self, canned, score, world):
        """canned, score: MediaPipe's gesture name and confidence. Returns (pose name, features)."""
        f = features(world)
        enter = self.cfg["pinch_threshold"]
        mean = sum(f["ext"]) / 4
        # a finger curled into a fist can't be pinching, however close it sits to the thumb; holding a pinch is a bit more lenient
        near = {name: f[PINCHES[name]] for name, finger in PINCH_FINGER.items() if f["ext"][finger] >= CURLED - 0.1}
        if self.held in PINCHES:
            d = near.get(self.held)
            closer = min(near, key=near.get) if near else None
            # fingers must clearly part before a pinch ends, and it moves to another finger once that one is clearly closer
            if d is not None and d < enter * 1.5 and not (closer != self.held and near[closer] < enter and near[closer] < 0.8 * d):
                return self.held, f
        elif self.held == "Closed_Fist" and mean < FIST + 0.1 and not (canned in POSES and score >= POSE_SCORE):
            return self.held, f  # (a thumbs-up or peace sign also has curled fingers, so a clear pose ends the fist)
        self.held = None
        starts = {name: d for name, d in near.items() if d < enter and f["ext"][PINCH_FINGER[name]] >= CURLED}
        if starts:
            self.held = min(starts, key=starts.get)
        elif canned in POSES and score >= POSE_SCORE:
            return canned, f
        elif mean < FIST or (canned == "Closed_Fist" and mean < FIST + 0.1):
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


class ModeSelector:
    """Which mode the other hand is holding. A mode is a pose held like a Shift key: it starts after HOLD_IN seconds of the
    pose and ends HOLD_OUT seconds after it is dropped or the hand leaves, so a flicker doesn't flip modes."""
    HOLD_IN, HOLD_OUT = 0.15, 0.25

    def __init__(self, cfg):
        self.poses = {pose: mode for mode, pose in cfg["modes"].items()}
        self.reset()

    def reset(self):
        self.mode = None
        self.pending = None  # (the mode being moved to, since when); a tuple, because "no mode" is a target too

    def update(self, t, pose):
        """pose: what the mode hand is doing, or None when it isn't in view. Returns the current mode name, or None."""
        want = self.poses.get(pose)
        if want == self.mode:
            self.pending = None
        elif self.pending is None or self.pending[0] != want:
            self.pending = (want, t)
        elif t - self.pending[1] >= (self.HOLD_IN if want else self.HOLD_OUT):
            self.mode, self.pending = want, None
        return self.mode


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
    ("press",), ("release",), ("scroll", steps), ("hscroll", steps), ("zoom", steps), ("run", mapping).
    `mode` is set from outside (the other hand's pose, see ModeSelector): a pose then first looks for a "Mode/Pose" mapping
    and falls back to the plain "Pose" one, so the common actions keep working in every mode."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.mode = None
        self.last_fire = {}
        self.reset()

    def reset(self):
        self.raw = self.current = None
        self.since = self.entered = self.seen = 0.0
        self.pos = None
        self.filters = [OneEuro(self.cfg["min_cutoff"], self.cfg["beta"]) for _ in range(2)]
        self.trail = deque()
        self.down = False
        self.action = None  # (mapping name, mapping) chosen when the current pose started, so a mode change can't switch it mid-pose
        self.last_v = None
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
        out = []
        if gesture != self.raw:
            self.raw, self.since = gesture, t
        hold = SLOW.get(gesture) or (QUICK_HOLD if gesture in QUICK else self.cfg["hold_ms"] / 1000)
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
        if not self.action or self.raw != self.current:
            return out  # while the hand is changing shape (fingers closing to pinch), everything holds still
        name, act = self.action
        if act["type"] == "mouse":
            value = act["value"]
            if value == "move" or (value == "left" and t - self.entered >= self.cfg["drag_ms"] / 1000):
                out.append(("move", *self.pos))
            elif value in SCROLLS:
                horizontal = value == "hscroll"  # moving the hand sideways scrolls sideways; up or down does the rest
                steps = self._steps(smooth[0 if horizontal else 1], 1 if horizontal else -1)
                if steps:
                    out.append((value, steps))
        elif act.get("repeat"):
            out += self._fire(name, act, t)
        return out

    def _pick(self, pose):
        """(name, mapping) for a pose: the current mode's version if it has one, else the plain one."""
        mappings = self.cfg["mappings"]
        names = [f"{self.mode}/{pose}", pose] if self.mode else [pose]
        for name in names:
            act = mappings.get(name)
            if act and act["type"] != "none":
                return name, act
        return None

    def _enter(self, t):
        self.action = self._pick(self.current)
        if not self.action:
            return []
        name, act = self.action
        if act["type"] != "mouse":
            return self._fire(name, act, t)
        if act["value"] in SCROLLS:
            self.last_v, self.step_acc = None, 0.0
        if act["value"] == "left":
            self.down = True
            return self._aim() + [("press",)]
        if act["value"] in ("right", "middle"):
            fired = self._fire(name, act, t)
            return self._aim() + fired if fired else []
        return []

    def _aim(self):
        """Put the cursor back where it was just before the fingers started closing, so the click lands on target."""
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

    def _steps(self, v, sign):
        """Whole scroll steps of hand motion along one axis since the last frame (sign +1: increasing v is positive)."""
        steps = 0
        if self.last_v is not None:
            self.step_acc += (v - self.last_v) * sign * self.cfg["scroll_speed"]
            steps = int(self.step_acc)
            self.step_acc -= steps
        self.last_v = v
        return steps
