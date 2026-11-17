"""Turns per-frame hand observations into actions. Pure logic: no camera or OS calls."""
import math
from collections import deque

FLICK_WINDOW = 0.25  # seconds
FLICK_DIST = 0.12  # fraction of frame width: a short wrist flick (with three fingers out), not a full arm swipe
TRUSTED = ("Thumb_Up", "ILoveYou")  # MediaPipe's built-in poses that need no landmark checks
POINTER_GESTURES = ("Point", "Closed_Fist")  # in two-hand mode the pointer hand only does these; the other hand does the rest


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy or 1e-9)))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def tap_ratio(lm):
    """Thumb tip to the side of the index finger, in hand sizes: small = thumb pressed against it."""
    return min(_seg_dist(lm[4], lm[5], lm[6]), _seg_dist(lm[4], lm[6], lm[7])) / math.dist(lm[0], lm[9])


def fingers(lm):
    """Extended state of index, middle, ring, pinky: tip clearly farther from the wrist than its middle joint."""
    return tuple(math.dist(lm[0], lm[tip]) > 1.1 * math.dist(lm[0], lm[pip]) for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)))


def classify(canned, lm, cfg):
    """Maps MediaPipe's gesture name plus 21 (x, y) landmarks to one of config.GESTURES (or "None")."""
    if canned in TRUSTED:
        return canned
    size = math.dist(lm[0], lm[9])  # wrist to middle knuckle, so thresholds ignore distance to camera
    ext = list(fingers(lm))
    # a finger pointing at the camera looks short in 2D; trust MediaPipe's own label for which fingers are out
    if canned == "Pointing_Up":
        ext[0] = True
    elif canned == "Victory":
        ext[0] = ext[1] = True
    ext = tuple(ext)
    if canned == "Closed_Fist":
        return canned  # the thumb rests near the curled fingers in a fist, so this must win over pinch
    if math.dist(lm[4], lm[8]) < cfg["pinch_threshold"] * size:
        return "Pinch"
    if not any(ext):
        return "Closed_Fist"
    tap = tap_ratio(lm) < cfg["tap_threshold"]  # thumb tip pressed onto the side of the index finger
    for name, shape in (("Point", (True, False, False, False)), ("Two_Finger", (True, True, False, False)),
                        ("Three_Finger", (True, True, True, False))):
        if ext == shape:
            return name + "_Tap" if tap else name
    return "None"


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
    """update() returns events: ("move", x, y) with x, y in 0-1 of the screen (absolute mode),
    ("move_by", dx, dy) in screen fractions (relative mode), ("press",), ("release",), ("scroll", steps),
    ("run", mapping)."""

    def __init__(self, cfg, role="single"):
        """role: "single" does everything; in two-hand mode "pointer" only moves the cursor (Point, fist clutch)
        and "action" never moves it, so a thumb tap there clicks without disturbing the pointer hand."""
        self.cfg, self.role = cfg, role
        self.reset()

    def reset(self):
        self.raw = self.current = None
        self.since = self.entered = 0.0
        self.pos = self.ref = None
        self.filters = [OneEuro(self.cfg["min_cutoff"], self.cfg["beta"]) for _ in range(2)]
        self.down = False
        self.last_y = None
        self.step_acc = 0.0
        self.last_fire = {}
        self.palm = deque()

    def update(self, t, gesture, anchor):
        """t: seconds; gesture: name, or None when no hand; anchor: (x, y) in 0-1 of the camera frame."""
        out = []
        if self.role == "pointer" and gesture not in POINTER_GESTURES:
            gesture = None
        if gesture != self.raw:
            self.raw, self.since = gesture, t
        if gesture != self.current and t - self.since >= self.cfg["hold_ms"] / 1000:
            out += self._exit()
            self.current, self.entered = gesture, t
            out += self._enter(t)
        if anchor is None:
            self.ref = None
            return out
        out += self._flick(t, gesture, anchor[0])
        smooth = [f(v, t) for f, v in zip(self.filters, anchor)]
        x0, y0, x1, y1 = self.cfg["box"]
        spans = ((x0, max(x1 - x0, 1e-3)), (y0, max(y1 - y0, 1e-3)))
        self.pos = tuple(min(max((v - lo) / span, 0.0), 1.0) for v, (lo, span) in zip(smooth, spans))
        act = self._action(self.current)
        # raw == current: freeze as soon as the pose starts changing (into a fist or a thumb tap), not 150 ms later
        moving = bool(act) and self.role != "action" and act["type"] == "mouse" and self.raw == self.current and (
            act["value"] == "move" or (act["value"] == "left" and t - self.entered >= self.cfg["drag_ms"] / 1000))
        if not moving:
            self.ref = None  # any non-moving pose is a clutch: relative mode resumes from the new hand position
        elif self.cfg["cursor_mode"] == "relative":
            if self.ref is not None:
                speed = self.cfg["relative_speed"]
                out.append(("move_by", *((v - r) / span * speed for v, r, (_, span) in zip(smooth, self.ref, spans))))
            self.ref = smooth
        else:
            out.append(("move", *self.pos))
        if not act:
            return out
        if act["type"] == "mouse" and act["value"] == "scroll":
            steps = self._steps(anchor[1])
            if steps:
                out.append(("scroll", steps))
        elif act["type"] == "slider":
            steps = self._steps(anchor[1])
            up, down = (c.strip() for c in act["value"].split(","))
            out += [("run", {"type": "keys", "value": up if steps > 0 else down})] * abs(steps)
        elif act["type"] in ("keys", "shell") and act.get("repeat"):
            out += self._fire(self.current, act, t)
        return out

    def _action(self, name):
        act = self.cfg["mappings"].get(name) if name else None
        return act if act and act["type"] != "none" else None

    def _enter(self, t):
        act = self._action(self.current)
        if not act:
            return []
        if act["type"] == "slider" or (act["type"] == "mouse" and act["value"] == "scroll"):
            self.last_y, self.step_acc = None, 0.0
            return []
        if act["type"] == "mouse" and act["value"] == "left":
            self.down = True
            return [("press",)]
        if act["type"] == "mouse" and act["value"] == "move":
            return []
        return self._fire(self.current, act, t)

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
        """Whole steps of vertical hand motion since the last frame; up is positive."""
        steps = 0
        if self.last_y is not None:
            self.step_acc += (self.last_y - y) * self.cfg["scroll_speed"]
            steps = int(self.step_acc)
            self.step_acc -= steps
        self.last_y = y
        return steps

    def _flick(self, t, gesture, x):
        if gesture != "Three_Finger":
            self.palm.clear()
            return []
        self.palm.append((t, x))
        while t - self.palm[0][0] > FLICK_WINDOW:
            self.palm.popleft()
        dx = x - self.palm[0][1]
        if abs(dx) < FLICK_DIST:
            return []
        self.palm.clear()
        name = "Flick_Right" if dx > 0 else "Flick_Left"
        act = self._action(name)
        return self._fire(name, act, t) if act else []
