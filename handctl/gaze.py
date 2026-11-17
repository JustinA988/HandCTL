"""Where the user is looking, from MediaPipe face landmarks, and which monitor that means. Pure logic: no camera or OS calls."""
import math
import statistics

# MediaPipe face-mesh landmark indices. "Left" and "right" here mean left and right in the image.
EYES = ((33, 133, 468), (362, 263, 473))  # each eye: image-left corner, image-right corner, iris centre
OUTER = (33, 263)  # outer eye corners: the face's left-right axis
TOP, CHIN = 10, 152  # the face's up-down axis
EYE_GAIN = 2.4  # eye opening width over eyeball radius (~29 mm / ~12 mm): turns iris offset into sin(eye angle)
MIN_SAMPLES = 8  # gaze readings needed per monitor for a calibration to count
MIN_APART = 8.0  # degrees: calibrated monitors closer than this can't be told apart reliably


def gaze(lm, width, height):
    """(yaw, pitch) in degrees of the line of sight relative to the camera: positive yaw = toward image right,
    positive pitch = downward. lm: MediaPipe face landmarks as normalized (x, y, z); z has x's scale, smaller = closer.
    Yaw adds eye rotation to head rotation, so a glance and a head turn toward the same monitor read the same.
    shortcut: pitch is head-only (eyelids make vertical iris position unreliable); add eye pitch if stacked monitors need it."""
    p = [(x * width, y * height, z * width) for x, y, z in lm]
    a, b = p[OUTER[0]], p[OUTER[1]]
    head_yaw = math.atan2(b[2] - a[2], b[0] - a[0])  # the image-right eye corner sits farther away when turned right
    head_pitch = math.atan2(p[CHIN][2] - p[TOP][2], p[CHIN][1] - p[TOP][1])  # the chin sits farther away when looking down
    offsets = []
    for left, right, iris in EYES:
        ax, ay = p[right][0] - p[left][0], p[right][1] - p[left][1]
        along = ((p[iris][0] - p[left][0]) * ax + (p[iris][1] - p[left][1]) * ay) / (ax * ax + ay * ay)
        offsets.append(along - 0.5)  # how far the iris sits from the middle of the eye, toward image right
    eye_yaw = math.asin(max(-1.0, min(1.0, EYE_GAIN * statistics.mean(offsets))))
    return math.degrees(head_yaw + eye_yaw), math.degrees(head_pitch)


def face_box(lm):
    """Box (x0, y0, x1, y1) around one face's landmarks, as normalized (x, y)."""
    xs, ys = [p[0] for p in lm], [p[1] for p in lm]
    return min(xs), min(ys), max(xs), max(ys)


def face_part(hand, faces, small=0.45, reach=1.0):
    """True when a detected "hand" is really a phantom on or around a face. MediaPipe sometimes reports a tiny hand-shaped
    thing on the cheek or hairline. Measured on one user: phantoms were 0.27-0.42x the face's width, real open hands about
    1.2x and real fists 0.5-0.65x. So a detection is dropped only if it is smaller than `small` x the face width AND centred
    within `reach` face-widths/heights of the face.
    hand: 21 (x, y) landmarks; faces: boxes from face_box(), in the same coordinates."""
    xs, ys = [p[0] for p in hand], [p[1] for p in hand]
    width = max(xs) - min(xs)
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    for x0, y0, x1, y1 in faces:
        fw, fh = x1 - x0, y1 - y0
        if width < small * fw and x0 - reach * fw <= cx <= x1 + reach * fw and y0 - reach * fh <= cy <= y1 + reach * fh:
            return True
    return False


def calibrate(samples, label=str):
    """samples: {monitor: [(yaw, pitch), ...]} recorded while the user looked at each monitor.
    Returns ({monitor: (yaw, pitch)}, problems): the monitors that can be used, and a plain-language line for each one
    that was left out. label turns a monitor key into the name shown to the user."""
    points, problems = {}, []
    for name, looks in samples.items():
        if len(looks) < MIN_SAMPLES:
            problems.append(f"{label(name)} was left out: your face wasn't visible to the camera while you looked at it.")
        else:
            points[name] = (statistics.median(l[0] for l in looks), statistics.median(l[1] for l in looks))
    names = list(points)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a in points and b in points and math.dist(points[a], points[b]) < MIN_APART:
                problems.append(f"{label(a)} and {label(b)} were left out: they looked the same to the camera.")
                del points[a], points[b]
    return points, problems


class Selector:
    """Picks the monitor being looked at: the calibrated point nearest the current gaze. Two guards stop it flapping
    on glances and noise: the new monitor must be clearly nearer (MARGIN) and stay so for DWELL seconds."""
    MARGIN = 0.75
    DWELL = 0.4

    def __init__(self, points, current=None):
        """points: {monitor: (yaw, pitch)} from calibrate(); current: the monitor in use now, if known."""
        self.points, self.current = points, current
        self.candidate, self.since = None, 0.0

    def update(self, t, look):
        """look: (yaw, pitch), or None when no face is visible. Returns the monitor to use (None if never determined)."""
        if look is None or len(self.points) < 2:
            self.candidate = None
            return self.current
        dist = {name: math.dist(look, point) for name, point in self.points.items()}
        best = min(dist, key=dist.get)
        if self.current not in dist:
            self.current = best  # nothing to switch away from yet
        if best == self.current or dist[best] > self.MARGIN * dist[self.current]:
            self.candidate = None
        elif best != self.candidate:
            self.candidate, self.since = best, t
        elif t - self.since >= self.DWELL:
            self.current, self.candidate = best, None
        return self.current
