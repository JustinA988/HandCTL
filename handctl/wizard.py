"""Setup flows: the first-run wizard (camera, cursor area, pinch calibration, gesture check) and the monitor calibration."""
import copy
import ctypes
import math
import statistics
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QPushButton, QVBoxLayout, QWizard, QWizardPage

from . import actions, config
from .gaze import MIN_APART, MIN_SAMPLES, calibrate

CHECK = [  # (gesture, what to do)
    ("Hand", "Hold up an open, relaxed hand (this moves the cursor)"),
    ("Pinch", "Touch your thumb and index fingertips together (left click)"),
    ("Pinch_Middle", "Thumb and middle fingertips together (bonus: right click; may read as an index pinch on your camera)"),
    ("Pinch_Ring", "Thumb and ring fingertips together (bonus: middle click; may read as an index pinch)"),
    ("Pinch_Pinky", "Thumb and pinky fingertips together (bonus: a mode action; partly reliable)"),
    ("Closed_Fist", "Make a fist (scroll; with the other hand, Edit mode)"),
    ("Thumb_Up", "Thumbs up (volume up; with the other hand, Media mode)"),
    ("Thumb_Down", "Thumbs down (volume down; with the other hand, System mode)"),
    ("Victory", "Peace sign (right click; with the other hand, Windows mode)"),
    ("ILoveYou", "Thumb, index and pinky out (task view; with the other hand, Browser mode)"),
]


def percentile(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def pinch_threshold(open_hand, pinched):
    """Threshold between this user's pinched and open readings, or None when they are too close to tell apart.
    A pinch ends at 1.5x the threshold, so the threshold is kept low enough that an open hand is clearly past that."""
    hi, lo = percentile(pinched, 0.9), percentile(open_hand, 0.1)
    threshold = round(min((hi + lo) / 2, lo / 1.6), 2)
    return threshold if threshold > hi + 0.02 else None


def box_from(top_left, bottom_right, min_span=0.15):
    """Cursor area from two captured hand positions, or None when they are too close (or the wrong way round)."""
    (x0, y0), (x1, y1) = top_left, bottom_right
    if x1 - x0 < min_span or y1 - y0 < min_span:
        return None
    return [round(min(max(v, 0.0), 1.0), 2) for v in (x0, y0, x1, y1)]


def role_hand(hands, cfg, role):
    """The hand that moves the cursor ("pointer") or clicks ("action") when both are in view; with one hand in view
    (or in one-hand mode) that hand does both jobs."""
    if cfg["hand_mode"] == "one" or len(hands) < 2:
        return next(iter(hands.values()), None)
    other = "Left" if cfg["hand"] == "Right" else "Right"
    return hands.get(cfg["hand"] if role == "pointer" else other)


class Collector:
    """Records values for `seconds` after start()."""

    def __init__(self, seconds=3.0):
        self.seconds, self.values, self.end = seconds, [], None

    def start(self):
        self.values, self.end = [], time.monotonic() + self.seconds

    def finished(self):
        """True once, right after the window ends."""
        done = self.end is not None and time.monotonic() >= self.end
        if done:
            self.end = None
        return done

    def add(self, value):
        if self.end is not None and time.monotonic() < self.end:
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
        super().__init__("Camera", "Pick the camera that faces you. The picture on the left should show your raised hand. "
                         "Rest your elbow on the desk or chair arm with your forearm upright: it tires your arm far less "
                         "than holding it out. Your hand doesn't need to face the camera squarely.")
        self.combo = QComboBox()
        for i in range(wizard.settings.camera.count()):
            self.combo.addItem(wizard.settings.camera.itemText(i), wizard.settings.camera.itemData(i))
        self.combo.setCurrentIndex(wizard.settings.camera.currentIndex())
        self.combo.activated.connect(lambda i: (wizard.settings.camera.setCurrentIndex(i), wizard.settings.switch_camera()))
        self.layout_.addWidget(self.combo)


class AreaPage(Page):
    def __init__(self, wizard):
        super().__init__("Cursor area", "Hold your open hand where the top-left corner of your screen should be, press the "
                         "button, and hold still for 3 seconds. Then do the same for the bottom-right corner. "
                         "Small, comfortable movements work best.")
        self.points, self.collector, self.target = {}, Collector(), None
        self.button("Capture top-left", lambda: self.capture("tl"))
        self.button("Capture bottom-right", lambda: self.capture("br"))
        self.layout_.addWidget(self.note)

    def capture(self, which):
        self.target = which
        self.note.setText("Hold still...")
        self.collector.start()

    def on_sample(self, wizard, hands):
        hand = role_hand(hands, wizard.app.cfg, "pointer")
        if hand:
            self.collector.add(hand["pos"])
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


class PinchPage(Page):
    def __init__(self, wizard):
        super().__init__("Pinch", "Clicking is a pinch: thumb and index fingertips touching. First capture with your hand "
                         "open and relaxed, then with thumb and index fingertip held together.")
        self.collectors, self.readings, self.which = {"open": Collector(), "pinched": Collector()}, {}, None
        self.button("Capture: hand open (3 s)", lambda: self.capture("open"))
        self.button("Capture: pinching (3 s)", lambda: self.capture("pinched"))
        self.layout_.addWidget(self.note)

    def capture(self, which):
        self.which = which
        self.note.setText("Hold still...")
        self.collectors[which].start()

    def on_sample(self, wizard, hands):
        hand = role_hand(hands, wizard.app.cfg, "pointer")  # the main hand is the one that pinches
        if hand:
            for c in self.collectors.values():
                c.add(hand["feat"]["pinch"])
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
        threshold = pinch_threshold(self.readings["open"], self.readings["pinched"])
        if threshold is None:
            self.note.setText("Your open and pinching readings were too close to tell apart, so the standard setting is kept. "
                              "Try again with your hand closer to the camera, or adjust it under Settings > Gesture tuning.")
        else:
            wizard.cfg["pinch_threshold"] = threshold
            self.note.setText(f"Pinch calibrated (threshold {threshold}).")


class GesturePage(Page):
    def __init__(self, wizard):
        super().__init__("Try your gestures", "Make each gesture below. It gets a check mark when it is recognized. "
                         "You can finish at any time; anything missed can be tuned in Settings.")
        self.labels = {g: QLabel(f"○ {text}") for g, text in CHECK}
        self.text, self.run, self.last = dict(CHECK), {}, {}
        for label in self.labels.values():
            self.layout_.addWidget(label)

    def on_sample(self, wizard, hands):
        for side, hand in hands.items():
            gesture = hand["gesture"]
            self.run[side] = self.run.get(side, 0) + 1 if gesture == self.last.get(side) else 1
            self.last[side] = gesture
            if self.run[side] >= 6 and gesture in self.labels:  # held for a few frames, not a one-frame glitch
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
        for page in (CameraPage, AreaPage, PinchPage, GesturePage):
            self.addPage(page(self))

    def on_frame(self, image, text):
        self.preview.setPixmap(QPixmap.fromImage(image).scaledToWidth(320))

    def on_sample(self, hands):
        self.currentPage().on_sample(self, hands)

    def done(self, result):
        # Finish saves the results; Cancel keeps current settings. Either way the wizard doesn't open again by itself.
        cfg = self.cfg if result else copy.deepcopy(self.app.cfg)
        cfg["wizard_done"] = True
        self.app.sample_hook = self.app.frame_hook = None
        self.app.calibrating = False
        config.save(cfg)
        self.app.apply(cfg)
        self.settings.load(cfg)
        super().done(result)


SPOT = "spot"  # a place the user looks at that isn't a monitor (the keyboard...): looking there must never switch


class MonitorCalibration(QDialog):
    """Shows a window on each monitor in turn and records where the user's gaze points while they look at it, then
    records the keyboard as a place to ignore. spot_only=True records one more place to ignore and changes nothing else."""
    READY, HOLD = 2.5, 2.5  # seconds to turn and look, then seconds recorded, per monitor

    def __init__(self, settings, spot_only=False):
        super().__init__(settings)
        self.settings, self.app = settings, settings.app
        self.setWindowTitle("handctl monitor calibration")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.resize(560, 280)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.text.font()
        font.setPointSize(14)
        self.text.setFont(font)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        self.close_button.hide()
        layout = QVBoxLayout(self)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.close_button)
        self.rects = dict(sorted(actions.monitors().items(), key=lambda item: (item[1][0], item[1][1])))
        self.labels = {name: f"Monitor {i + 1}" for i, name in enumerate(self.rects)}  # numbered left to right
        self.spot_only = spot_only
        self.steps = [SPOT] if spot_only else [*self.rects, SPOT]
        self.samples = {name: [] for name in self.steps}
        self.index, self.recording, self.phase_end, self.saved = -1, False, 0.0, None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.app.calibrating = self.app.force_face = True  # cursor control off, face reading on
        self.app.look_hook = self.on_look
        self.app.apply(self.app.cfg)

    def showEvent(self, event):
        if self.index < 0:
            self.next_monitor()
            self.timer.start(100)

    def next_monitor(self):
        self.index += 1
        if self.index >= len(self.steps):
            self.finish()
            return
        self.recording, self.phase_end = False, time.monotonic() + self.READY
        if self.steps[self.index] != SPOT and QGuiApplication.platformName() == "windows":
            # placed through Windows in real pixels: Qt's own coordinates differ from them on scaled displays
            left, top, width, height = list(self.rects.values())[self.index]
            ctypes.windll.user32.SetWindowPos(int(self.winId()), 0, left + width // 2 - 280, top + height // 2 - 140, 0, 0, 0x0015)
        self.tick()

    def tick(self):
        if not 0 <= self.index < len(self.steps):
            return
        left = self.phase_end - time.monotonic()
        spot = self.steps[self.index] == SPOT
        if left <= 0 and self.recording:
            if spot:
                QApplication.beep()  # the user is looking away from the screen, so a sound says it's done
            self.next_monitor()
            return
        if left <= 0:
            self.recording, self.phase_end, left = True, time.monotonic() + self.HOLD, self.HOLD
        what = "the place to ignore (your phone, notes, a second keyboard...)" if self.spot_only else "your keyboard"
        if spot:
            self.text.setText(f"Keep looking at {what} until you hear a beep." if self.recording else
                              f"{'Last step: l' if not self.spot_only else 'L'}ook at {what} and keep looking until you "
                              f"hear a beep. Looking there will never switch monitors.\nRecording starts in {math.ceil(left)}")
        elif self.recording:
            self.text.setText(f"Keep looking at this window...\n{math.ceil(left)}")
        else:
            label = list(self.labels.values())[self.index]
            self.text.setText(f"{label} of {len(self.rects)}: look at this window.\nRecording starts in {math.ceil(left)}")

    def on_look(self, seen):
        if self.recording and seen and 0 <= self.index < len(self.steps):
            self.samples[self.steps[self.index]].append(seen)

    def finish(self):
        self.timer.stop()
        self.recording = False
        # each reading holds both gaze sources, (yaw, pitch, head-only yaw), so both calibrations come from one run
        sources = {"eyes": lambda s: s[:2], "head": lambda s: (s[2], s[1])}
        monitors = {n: looks for n, looks in self.samples.items() if n != SPOT}
        spot_looks = self.samples[SPOT]
        source = self.app.cfg["gaze_source"]
        cfg = copy.deepcopy(self.app.cfg)
        results = {}
        for name, read in sources.items():
            key_cfg = {**cfg, "gaze_source": name}
            if self.spot_only:
                points = {n: tuple(p) for n, p in cfg[config.gaze_key(key_cfg)].items()}
                problems = []
            else:
                points, problems = calibrate({n: [read(s) for s in looks] for n, looks in monitors.items()}, self.labels.get)
            spot = None
            if len(spot_looks) >= MIN_SAMPLES:
                spot = tuple(statistics.median(read(s)[i] for s in spot_looks) for i in (0, 1))
                near = [n for n, p in points.items() if math.dist(p, spot) < MIN_APART]
                if near:  # it would swallow looks at that monitor, so it is left out
                    problems.append(f"The place to ignore looked the same as {self.labels.get(near[0], near[0])} to the camera, "
                                    "so it was left out.")
                    spot = None
            elif not problems or self.spot_only:
                problems.append("The place to ignore was left out: your face wasn't visible to the camera while you looked at it.")
            results[name] = (points, spot, problems)
        points, spot, problems = results[source]
        if self.spot_only:
            if spot:
                self.saved = cfg
                for name, (_, found, _) in results.items():
                    if found:
                        self.saved[config.gaze_key({**cfg, "gaze_source": name}, ignore=True)].append([round(v, 1) for v in found])
                config.save(self.saved)
                head = "Done. Looking at that place won't switch monitors."
            else:
                head = "That didn't work, so nothing was changed."
        elif len(points) >= 2:
            self.saved = cfg
            for name, (found, found_spot, _) in results.items():
                key_cfg = {**cfg, "gaze_source": name}
                self.saved[config.gaze_key(key_cfg)] = {n: [round(v, 1) for v in p] for n, p in found.items()}
                self.saved[config.gaze_key(key_cfg, ignore=True)] = [[round(v, 1) for v in found_spot]] if found_spot else []
            self.saved["monitor_switch"] = True
            config.save(self.saved)
            head = f"Done. You now control the monitor you look at: {', '.join(self.labels[name] for name in points)}."
        else:
            head = "Calibration didn't work, so monitor switching was left as it was."
        self.text.setText("\n".join([head] + problems))
        self.close_button.show()

    def done(self, result):
        self.timer.stop()
        self.app.look_hook = None
        self.app.calibrating = self.app.force_face = False
        cfg = self.saved or self.app.cfg
        self.app.apply(cfg)  # restarts tracking with the new calibration, or the old settings if it failed
        self.settings.load(cfg)
        super().done(result)
