"""Turns per-frame hand observations into actions. Pure logic: no camera or OS calls."""
import math
from collections import deque

SWIPE_WINDOW = 0.3  # seconds
SWIPE_DIST = 0.2  # fraction of frame width


def classify(canned, lm, threshold):
    """Adds pinch poses on top of MediaPipe's gesture name. lm: 21 (x, y) landmarks."""
    if canned == "Closed_Fist":
        return canned  # the thumb rests near the curled fingers in a fist
    size = math.dist(lm[0], lm[9])  # wrist to middle knuckle, so thresholds ignore distance to camera
    if math.dist(lm[4], lm[8]) < threshold * size:
        return "Pinch"
    # middle finger must not be curled, or a tucked thumb in Pointing_Up reads as a pinch
    if math.dist(lm[4], lm[12]) < threshold * size and math.dist(lm[0], lm[12]) > size:
        return "Pinch_Middle"
    return canned


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
    """update() returns events: ("move", x, y) with x, y in 0-1 of the screen,
    ("press",), ("release",), ("scroll", steps), ("run", mapping)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.raw = self.current = None
        self.since = self.entered = 0.0
        self.pos = None
        self.filters = [OneEuro(self.cfg["min_cutoff"], self.cfg["beta"]) for _ in range(2)]
        self.down = False
        self.last_y = None
        self.scroll_acc = 0.0
        self.last_fire = {}
        self.palm = deque()

    def update(self, t, gesture, anchor):
        """t: seconds; gesture: name, or None when no hand; anchor: (x, y) in 0-1 of the camera frame."""
        out = []
        if gesture != self.raw:
            self.raw, self.since = gesture, t
        if gesture != self.current and t - self.since >= self.cfg["hold_ms"] / 1000:
            out += self._exit()
            self.current, self.entered = gesture, t
            out += self._enter(t)
        if anchor is None:
            return out
        out += self._swipe(t, gesture, anchor[0])
        self._track(t, anchor)
        act = self._action(self.current)
        if not act:
            return out
        if act["type"] == "mouse":
            value = act["value"]
            if value == "move" or (value == "left" and t - self.entered >= self.cfg["drag_ms"] / 1000):
                out.append(("move", *self.pos))
            elif value == "scroll":
                out += self._scroll(anchor[1])
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
        if act["type"] != "mouse" or act["value"] == "right":
            return self._fire(self.current, act, t)
        if act["value"] == "left":
            self.down = True
            return [("press",)]
        if act["value"] == "scroll":
            self.last_y, self.scroll_acc = None, 0.0
        return []

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

    def _track(self, t, anchor):
        x0, y0, x1, y1 = self.cfg["box"]
        target = [min(max((a - lo) / max(hi - lo, 1e-3), 0.0), 1.0) for a, lo, hi in ((anchor[0], x0, x1), (anchor[1], y0, y1))]
        self.pos = tuple(f(v, t) for f, v in zip(self.filters, target))

    def _scroll(self, y):
        out = []
        if self.last_y is not None:
            self.scroll_acc += (self.last_y - y) * self.cfg["scroll_speed"]
            steps = int(self.scroll_acc)
            self.scroll_acc -= steps
            if steps:
                out.append(("scroll", steps))
        self.last_y = y
        return out

    def _swipe(self, t, gesture, x):
        if gesture != "Open_Palm":
            self.palm.clear()
            return []
        self.palm.append((t, x))
        while t - self.palm[0][0] > SWIPE_WINDOW:
            self.palm.popleft()
        dx = x - self.palm[0][1]
        if abs(dx) < SWIPE_DIST:
            return []
        self.palm.clear()
        name = "Swipe_Right" if dx > 0 else "Swipe_Left"
        act = self._action(name)
        return self._fire(name, act, t) if act else []
