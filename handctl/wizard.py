"""First-run setup wizard: camera, cursor area, thumb-tap calibration, then a live check of each gesture."""
import copy
import statistics
import time

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QVBoxLayout, QWizard, QWizardPage

from . import config
from .gestures import tap_ratio

CHECK = [  # (gesture, what to do)
    ("Point", "Point with your index finger"), ("Point_Tap", "Point, then tap your thumb on the side of your index finger"),
    ("Two_Finger", "Hold up index and middle fingers"), ("Two_Finger_Tap", "Two fingers, then tap your thumb"),
    ("Three_Finger_Tap", "Three fingers (index, middle, ring), then tap your thumb"),
    ("Closed_Fist", "Make a fist"), ("Thumb_Up", "Thumbs up"),
]
NO_TAP = {"type": "none", "value": ""}


def percentile(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def tap_threshold(out, pressed):
    """Midway between the pressed and thumb-out readings; None when they overlap (a tap can't be told apart)."""
    hi, lo = percentile(pressed, 0.9), percentile(out, 0.1)
    return round(max(0.05, (hi + lo) / 2), 2) if hi + 0.03 < lo else None


def box_from(top_left, bottom_right, min_span=0.15):
    """Cursor area from two captured hand positions, or None when they are too close (or the wrong way round)."""
    (x0, y0), (x1, y1) = top_left, bottom_right
    if x1 - x0 < min_span or y1 - y0 < min_span:
        return None
    return [round(min(max(v, 0.0), 1.0), 2) for v in (x0, y0, x1, y1)]


def use_pinch_instead(mappings):
    """Fallback when thumb tap can't be detected on this camera: pinch clicks, the tap gestures are switched off."""
    mappings = copy.deepcopy(mappings)
    mappings["Pinch"] = {"type": "mouse", "value": "left"}
    for name in ("Point_Tap", "Two_Finger_Tap", "Three_Finger_Tap"):
        mappings[name] = dict(NO_TAP)
    return mappings


class Collector:
    """Records values for `seconds` after start()."""

    def __init__(self, seconds=3.0):
        self.seconds, self.values, self.end = seconds, [], None

    def start(self):
        self.values, self.end = [], time.monotonic() + self.seconds

    def running(self):
        return self.end is not None and time.monotonic() < self.end

    def finished(self):
        """True once, right after the window ends."""
        done = self.end is not None and time.monotonic() >= self.end
        if done:
            self.end = None
        return done

    def add(self, value):
        if self.running():
            self.values.append(value)


class Page(QWizardPage):
    def __init__(self, title, text):
        super().__init__()
        self.setTitle(title)
        self.layout_ = QVBoxLayout(self)
        intro = QLabel(text)
        intro.setWordWrap(True)
        self.layout_.addWidget(intro)
        self.note = QLabel()
        self.note.setWordWrap(True)

    def on_sample(self, wizard, hands):
        pass

    def button(self, label, action):
        b = QPushButton(label)
        b.clicked.connect(action)
        self.layout_.addWidget(b)
        return b


class CameraPage(Page):
    def __init__(self, wizard):
        super().__init__("Camera", "Pick the camera that faces you. The picture on the left should show your hand and the desk "
                         "area above your keyboard. Rest your elbow on the desk and keep your hand low: it tires your arm far less.")
        self.combo = QComboBox()
        for i in range(wizard.settings.camera.count()):
            self.combo.addItem(wizard.settings.camera.itemText(i), wizard.settings.camera.itemData(i))
        self.combo.setCurrentIndex(wizard.settings.camera.currentIndex())
        self.combo.activated.connect(lambda i: (wizard.settings.camera.setCurrentIndex(i), wizard.settings.switch_camera()))
        self.layout_.addWidget(self.combo)


class AreaPage(Page):
    def __init__(self, wizard):
        super().__init__("Cursor area", "Point at where the top-left corner of your screen should be, press the button, and hold "
                         "still for 3 seconds. Then do the same for the bottom-right corner. Small, comfortable movements work best.")
        self.wizard, self.points, self.collector, self.target = wizard, {}, Collector(), None
        self.button("Capture top-left", lambda: self.capture("tl"))
        self.button("Capture bottom-right", lambda: self.capture("br"))
        self.layout_.addWidget(self.note)

    def capture(self, which):
        self.target = which
        self.note.setText("Hold still...")
        self.collector.start()

    def on_sample(self, wizard, hands):
        hand = hands.get(wizard.app.cfg["hand"])
        if hand:
            self.collector.add(hand[1][5])
        if not self.collector.finished():
            return
        if len(self.collector.values) < 10:
            self.note.setText("I couldn't see your hand. Try again.")
            return
        self.points[self.target] = tuple(statistics.median(v[i] for v in self.collector.values) for i in (0, 1))
        if len(self.points) < 2:
            self.note.setText("Got it. Now the other corner.")
            return
        box = box_from(self.points["tl"], self.points["br"])
        if box is None:
            self.points.clear()
            self.note.setText("Those points are too close together, or top-left was not up and to the left. Capture both again.")
        else:
            wizard.cfg["box"] = box
            self.note.setText(f"Cursor area set to {box}.")


class ThumbPage(Page):
    def __init__(self, wizard):
        super().__init__("Thumb tap", "Clicking uses a thumb tap on the side of your index finger. Point with your index finger. "
                         "First capture with your thumb held away from your finger, then with your thumb pressed against it.")
        self.wizard, self.collectors, self.readings, self.which = wizard, {"out": Collector(), "pressed": Collector()}, {}, None
        self.button("Capture: thumb away (3 s)", lambda: self.capture("out"))
        self.button("Capture: thumb pressed on finger (3 s)", lambda: self.capture("pressed"))
        self.layout_.addWidget(self.note)

    def capture(self, which):
        self.which = which
        self.note.setText("Hold still...")
        self.collectors[which].start()

    def on_sample(self, wizard, hands):
        app_cfg = wizard.app.cfg
        label = app_cfg["hand"] if app_cfg["hand_mode"] == "single" else ("Left" if app_cfg["hand"] == "Right" else "Right")
        if label in hands:
            for c in self.collectors.values():
                c.add(tap_ratio(hands[label][1]))
        c = self.collectors.get(self.which)
        if not c or not c.finished():
            return
        if len(c.values) < 10:
            self.note.setText("I couldn't see your hand. Try again.")
            return
        self.readings[self.which] = c.values
        if len(self.readings) < 2:
            self.note.setText("Got it. Now the other one.")
            return
        threshold = tap_threshold(self.readings["out"], self.readings["pressed"])
        if threshold is None:
            wizard.cfg["mappings"] = use_pinch_instead(wizard.cfg["mappings"])
            self.note.setText("Thumb taps can't be told apart on this camera view, so pinch (thumb to index fingertip) will click "
                              "instead, and the tap gestures are switched off. You can change this in Settings.")
        else:
            wizard.cfg["tap_threshold"] = threshold
            self.note.setText(f"Thumb tap calibrated (threshold {threshold}).")


class GesturePage(Page):
    def __init__(self, wizard):
        super().__init__("Try your gestures", "Make each gesture below. It gets a check mark when it is recognized. "
                         "You can finish at any time; anything missed can be tuned in Settings.")
        self.labels = {g: QLabel(f"○ {text}") for g, text in CHECK}
        self.text, self.run, self.last = dict(CHECK), {}, {}
        for label in self.labels.values():
            self.layout_.addWidget(label)

    def on_sample(self, wizard, hands):
        for hand, (gesture, _) in hands.items():
            self.run[hand] = self.run.get(hand, 0) + 1 if gesture == self.last.get(hand) else 1
            self.last[hand] = gesture
            if self.run[hand] >= 6 and gesture in self.labels:  # held for a few frames, not a one-frame glitch
                self.labels[gesture].setText(f"✓ {self.text[gesture]}")


class Wizard(QWizard):
    def __init__(self, settings):
        super().__init__(settings)
        self.settings, self.app = settings, settings.app
        self.cfg = copy.deepcopy(self.app.cfg)
        self.setWindowTitle("handctl setup")
        self.preview = QLabel()
        self.preview.setFixedSize(320, 240)
        self.setSideWidget(self.preview)
        self.app.calibrating = True  # tracking stays off so the cursor can't move while you set up
        self.app.tracker.enabled = False
        self.app.toggle_action.setChecked(False)
        self.app.sample_hook, self.app.frame_hook = self.on_sample, self.on_frame
        for page in (CameraPage, AreaPage, ThumbPage, GesturePage):
            self.addPage(page(self))

    def on_frame(self, image, text):
        self.preview.setPixmap(QPixmap.fromImage(image).scaledToWidth(320))

    def on_sample(self, hands):
        self.currentPage().on_sample(self, hands)

    def done(self, result):
        # Finish saves the results; Cancel keeps current settings. Either way the wizard doesn't open again by itself.
        cfg = self.cfg if result else {**self.app.cfg, "wizard_done": True}
        cfg["wizard_done"] = True
        self.app.sample_hook = self.app.frame_hook = None
        self.app.calibrating = False
        config.save(cfg)
        self.app.apply(cfg)
        self.settings.load(cfg)
        super().done(result)
