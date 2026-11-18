"""Entry point: tray icon, settings window, global hotkey toggle. Run with `python -m handctl`."""
import copy
import ctypes
import logging
import sys
import winreg
from pathlib import Path

from pynput import keyboard
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSlider, QSpinBox, QStyle, QSystemTrayIcon, QTableWidget, QTabWidget,
    QVBoxLayout, QWidget,
)

from . import actions, config
from .tracker import Tracker, list_cameras
from .wizard import MonitorCalibration, Wizard

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
CONTROL_HELP = (
    "Cursor: your hand moves the cursor and clicks. Actions: it never does; gestures only trigger actions (screenshot, "
    "voice typing, change tab, ...), with the common ones on one hand and the rest on two. You can also switch from the "
    "tray menu. The Gestures tab has a separate set of gestures for each, so editing one never changes the other."
)
HANDS_HELP = (
    "Auto: both hands are tracked. With one hand in view, it does everything (the core gestures). With both in view, "
    "the main hand keeps moving the cursor and doing the core gestures, and the other hand picks a mode by holding a "
    "pose, like holding Shift: while it does, the main hand's pinches, thumbs and signs do that mode's actions "
    "(Edit, Media, Windows, Browser, System). Let go and everything returns to normal.\n"
    "One: only one hand is ever tracked, so a second hand in view (say, typing) is ignored.\n"
    "Choose each mode's pose below; each mode needs its own."
)
GESTURES_HELP = (
    "Core: what each gesture does on its own. The other tabs: what the main hand's gestures do while the other hand "
    "holds that mode's pose (set on Settings > Hands). A mode gesture left at 'none' does its core action instead. "
    "Action values - mouse: move, left, right, middle, scroll, hscroll, zoom | keys: <ctrl>+<alt>+t, <cmd>+d, <media_next> | "
    "shell: any command (only runs if enabled under Settings > General)."
)
MONITORS_HELP = (
    "With two or more monitors, your hand controls the monitor you are looking at, and the cursor jumps to it when "
    "you look across. Both head turns and eye movement count.\n"
    "Calibration shows a window on each monitor in turn: look at each one for a few seconds. Your face has to stay "
    "visible to the camera, so a monitor you can only see by turning away from the camera is left out. "
    "Calibrate again if you move the camera or your monitors."
)


def set_autostart(on):
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}" --tray'
    else:
        cmd = f'"{Path(sys.executable).with_name("pythonw.exe")}" -m handctl --tray'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, "handctl", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "handctl")
            except FileNotFoundError:
                pass


def spin(lo, hi, step=None):
    w = QDoubleSpinBox() if step else QSpinBox()
    w.setRange(lo, hi)
    if step:
        w.setSingleStep(step)
    return w


class Slider(QWidget):
    """Labelled slider with a real-valued range; value()/setValue() work like a spin box."""

    def __init__(self, lo, hi, step, decimals=2):
        super().__init__()
        self.decimals, self.scale = decimals, 10 ** decimals  # QSlider only does integers
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(round(lo * self.scale), round(hi * self.scale))
        self.slider.setSingleStep(max(1, round(step * self.scale)))
        self.slider.setPageStep(max(1, round(step * self.scale)) * 5)
        self.text = QLabel()
        self.text.setMinimumWidth(48)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.slider, 1)
        row.addWidget(self.text)
        self.slider.valueChanged.connect(self._show)

    def _show(self, raw):
        self.text.setText(f"{raw / self.scale:.{self.decimals}f}")

    def value(self):
        v = round(self.slider.value() / self.scale, self.decimals)
        return int(v) if self.decimals == 0 else v

    def setValue(self, v):
        self.slider.setValue(round(v * self.scale))
        self._show(self.slider.value())


def combo(items):
    w = QComboBox()
    w.addItems(items)
    return w


def get(w):
    if isinstance(w, QCheckBox):
        return w.isChecked()
    if isinstance(w, QComboBox):
        return w.currentText()
    if isinstance(w, QLineEdit):
        return w.text().strip()
    return w.value()


def put(w, v):
    if isinstance(w, QCheckBox):
        w.setChecked(v)
    elif isinstance(w, QComboBox):
        w.setCurrentText(v)
    elif isinstance(w, QLineEdit):
        w.setText(v)
    else:
        w.setValue(v)


def form(*rows):
    """A tab page: rows are (label, widget), a lone widget, or a lone string (a wrapped note)."""
    page = QWidget()
    f = QFormLayout(page)
    for row in rows:
        if isinstance(row, str):
            note = QLabel(row)
            note.setWordWrap(True)
            f.addRow(note)
        elif isinstance(row, tuple):
            f.addRow(*row)
        else:
            f.addRow(row)
    return page


class Settings(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("handctl settings")

        self.fields = {
            "control_mode": combo(["cursor", "actions"]), "action_hold_ms": Slider(100, 1000, 10, 0),
            "hand_mode": combo(["auto", "one"]), "hand": combo(["Right", "Left"]),
            "mirror": QCheckBox("Mirror camera image"),
            "min_cutoff": Slider(0.1, 5, 0.1, 1), "beta": Slider(0, 20, 0.5, 1),
            "pinch_threshold": Slider(0.05, 1, 0.01, 2),
            "hold_ms": Slider(0, 1000, 10, 0), "drag_ms": Slider(0, 1500, 10, 0), "scroll_speed": Slider(1, 200, 1, 0),
            "toggle_hotkey": QLineEdit(),
            "shell_enabled": QCheckBox("Allow gestures to run shell commands"),
            "autostart": QCheckBox("Start with Windows"),
            "monitor_switch": QCheckBox("Move the cursor to the monitor I look at"),
        }
        self.box = [spin(0, 1, 0.05) for _ in range(4)]
        f = self.fields
        # a mode switch, like the tray item: applies at once, no Save needed (activated: user picks only, not load())
        f["control_mode"].activated.connect(lambda: self.app.set_control_mode(get(f["control_mode"])))

        # Preview tab: camera picker, live image, status
        self.preview = QLabel("Starting camera...")
        self.preview.setMinimumSize(640, 480)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status = QLabel()
        self.camera = QComboBox()
        self.camera.activated.connect(self.switch_camera)  # user picks only; filling the list must not restart tracking
        rescan = QPushButton("Refresh")
        rescan.clicked.connect(self.refresh_cameras)
        pick = QHBoxLayout()
        pick.addWidget(QLabel("Camera"))
        pick.addWidget(self.camera, 1)
        pick.addWidget(rescan)
        self.fill_cameras(app.cfg["camera"])  # runs before tracking starts, so every camera is free to probe
        preview_tab = QWidget()
        pv = QVBoxLayout(preview_tab)
        pv.addLayout(pick)
        pv.addWidget(self.preview)
        pv.addWidget(self.status)

        # Gestures tab: what each gesture does, one table for the core gestures and one per mode
        self.rows = []
        self.sets = [self.groups_for(""), self.groups_for(config.ACTION_PREFIX)]  # cursor-mode gestures, action-only gestures
        self.set_picker = combo(["Cursor mode gestures", "Action-only mode gestures"])
        self.set_picker.currentIndexChanged.connect(self.show_set)
        reset = QPushButton("Reset gestures to defaults")
        reset.clicked.connect(lambda: self.put_mappings(config.DEFAULTS["mappings"]))
        gestures_tab = QWidget()
        g = QVBoxLayout(gestures_tab)
        help_label = QLabel(GESTURES_HELP)
        help_label.setWordWrap(True)
        g.addWidget(help_label)
        g.addWidget(self.set_picker)
        for groups in self.sets:
            g.addWidget(groups)
        g.addWidget(reset)
        self.show_set(0)

        # Settings tab with sub-tabs
        wizard = QPushButton("Run setup wizard")
        wizard.clicked.connect(lambda: self.app.run_wizard())
        sub = QTabWidget()
        self.mode_poses = {mode: combo(config.MODE_POSES) for mode in config.MODES}
        sub.addTab(form(
            ("Control mode", f["control_mode"]), CONTROL_HELP,
            ("Hand mode", f["hand_mode"]), ("Main hand", f["hand"]), f["mirror"], HANDS_HELP,
            *[(f"{mode} mode: other hand makes", box) for mode, box in self.mode_poses.items()],
        ), "Hands")
        sub.addTab(form(
            ("Steadiness (lower = steadier)", f["min_cutoff"]), ("Responsiveness (higher = less lag)", f["beta"]),
            ("Cursor area left", self.box[0]), ("top", self.box[1]), ("right", self.box[2]), ("bottom", self.box[3]),
        ), "Cursor")
        sub.addTab(form(
            ("Pinch threshold", f["pinch_threshold"]), ("Pose hold before acting (ms)", f["hold_ms"]),
            ("Hold in action-only mode (ms)", f["action_hold_ms"]),
            ("Pinch hold before drag (ms)", f["drag_ms"]), ("Scroll speed", f["scroll_speed"]),
            "The Preview tab shows a live pinch number: it is small when thumb and finger touch. Set the pinch threshold "
            "between your touching and open values: raise it if pinches don't click, lower it if clicks fire by accident.",
        ), "Gesture tuning")
        self.monitor_note = QLabel()
        calibrate = QPushButton("Calibrate monitors")
        calibrate.clicked.connect(lambda: self.app.calibrate_monitors())
        sub.addTab(form(f["monitor_switch"], self.monitor_note, calibrate, MONITORS_HELP), "Monitors")
        sub.addTab(form(("Toggle hotkey", f["toggle_hotkey"]), f["shell_enabled"], f["autostart"], wizard), "General")

        tabs = QTabWidget()
        tabs.addTab(preview_tab, "Preview")
        tabs.addTab(gestures_tab, "Gestures")
        tabs.addTab(sub, "Settings")
        save = QPushButton("Save && apply")
        save.clicked.connect(self.save)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(save)
        self.load(app.cfg)

    def groups_for(self, prefix):
        """Tabs of tables: the core gestures, then one per mode. prefix picks the cursor-mode or action-only set."""
        groups = QTabWidget()
        groups.addTab(self.table_for([prefix + pose for pose in config.POSE_NAMES]), "Core")
        for mode in config.MODES:
            groups.addTab(self.table_for([f"{prefix}{mode}/{pose}" for pose in config.SLOTS]), mode)
        return groups

    def show_set(self, index):
        for i, groups in enumerate(self.sets):
            groups.setVisible(i == index)

    def table_for(self, names):
        """A table with one row per mapping name; its widgets are collected in self.rows."""
        table = QTableWidget(len(names), 5)
        table.setHorizontalHeaderLabels(["Gesture", "Action", "Value", "Cooldown ms", "Repeat while held"])
        for i, name in enumerate(names):
            cells = [combo(config.ACTION_TYPES), QLineEdit(), spin(0, 10000), QCheckBox()]
            table.setCellWidget(i, 0, QLabel(name.removeprefix(config.ACTION_PREFIX).split("/")[-1].replace("_", " ")))
            for col, w in enumerate(cells, 1):
                table.setCellWidget(i, col, w)
            self.rows.append((name, *cells))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def fill_cameras(self, current):
        found = list_cameras()
        self.camera.clear()
        for i in sorted({*found, current}):  # keep the saved camera listed even when unplugged
            self.camera.addItem(f"Camera {i}" + ("" if i in found else " (not found)"), i)
        self.camera.setCurrentIndex(self.camera.findData(current))

    def switch_camera(self):
        cfg = {**self.app.cfg, "camera": self.camera.currentData()}
        config.save(cfg)
        self.app.apply(cfg)

    def refresh_cameras(self):
        self.app.stop()  # the active camera can't be probed while tracking holds it
        self.fill_cameras(self.app.cfg["camera"])
        self.app.apply(self.app.cfg)

    def load(self, cfg):
        for key, w in self.fields.items():
            put(w, cfg[key])
        for w, v in zip(self.box, cfg["box"]):
            w.setValue(v)
        for mode, box in self.mode_poses.items():
            box.setCurrentText(cfg["modes"][mode])
        self.set_picker.setCurrentIndex(1 if cfg["control_mode"] == "actions" else 0)  # show the set that is in use
        calibrated = len(cfg["monitor_gaze"])
        self.monitor_note.setText(f"Calibrated for {calibrated} monitors." if calibrated >= 2 else "Not calibrated yet.")
        self.put_mappings(cfg["mappings"])
        self.unchanged = self.edits()

    def edits(self):
        """What the widgets hold, to spot unsaved changes. Control mode applies at once, so it never counts."""
        cfg = self.read()
        return [cfg[key] for key in [*self.fields, "box", "modes", "mappings"] if key != "control_mode"]

    def put_mappings(self, mappings):
        for name, kind, value, cooldown, repeat in self.rows:
            m = mappings.get(name, {"type": "none", "value": ""})
            kind.setCurrentText(m["type"])
            value.setText(m["value"])
            cooldown.setValue(m.get("cooldown_ms", 0))
            repeat.setChecked(m.get("repeat", False))

    def read(self):
        cfg = copy.deepcopy(self.app.cfg)
        cfg.update({key: get(w) for key, w in self.fields.items()})
        cfg["box"] = [w.value() for w in self.box]
        cfg["modes"] = {mode: box.currentText() for mode, box in self.mode_poses.items()}
        cfg["mappings"] = {
            name: {"type": kind.currentText(), "value": value.text().strip(), "cooldown_ms": cooldown.value(), "repeat": repeat.isChecked()}
            for name, kind, value, cooldown, repeat in self.rows
        }
        return cfg

    def save(self):
        cfg = self.read()
        errors = config.validate(cfg)
        if errors:
            QMessageBox.warning(self, "Fix these settings", "\n".join(errors))
            return False
        config.save(cfg)
        set_autostart(cfg["autostart"])
        self.app.apply(cfg)
        self.unchanged = self.edits()
        return True

    def show_frame(self, image, text):
        self.preview.setPixmap(QPixmap.fromImage(image))
        self.status.setText(text)

    def showEvent(self, event):
        self.app.tracker.preview = True

    def hideEvent(self, event):
        self.app.tracker.preview = False

    def closeEvent(self, event):
        if self.edits() != self.unchanged:  # closing quits, so unsaved changes would be lost silently
            buttons = QMessageBox.StandardButton
            answer = QMessageBox.question(self, "handctl", "Save your changes before quitting?",
                                          buttons.Save | buttons.Discard | buttons.Cancel)
            if answer == buttons.Cancel or (answer == buttons.Save and not self.save()):
                event.ignore()
                return
        event.accept()
        QApplication.instance().quit()  # closing the settings window quits the app; minimizing doesn't


class App:
    def __init__(self, qapp):
        self.cfg = config.load()
        self.tracker = self.hotkey = None
        self.calibrating = False  # the wizard and the monitor calibration keep tracking off while they measure
        self.force_face = False  # the monitor calibration needs the face read even while monitor switching is off
        self.sample_hook = self.frame_hook = self.look_hook = None  # the wizard and the monitor calibration listen here
        self.tray = QSystemTrayIcon(qapp.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray.setToolTip("handctl")
        menu = QMenu()
        self.toggle_action = menu.addAction("Tracking enabled")
        self.toggle_action.setCheckable(True)
        self.toggle_action.triggered.connect(lambda: self.tracker.toggle())
        self.action_only = menu.addAction("Action-only mode (cursor off)")
        self.action_only.setCheckable(True)
        self.action_only.triggered.connect(lambda checked: self.set_control_mode("actions" if checked else "cursor"))
        menu.addAction("Settings", self.show_settings)
        menu.addAction("Quit", qapp.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and self.show_settings())
        self.tray.show()
        self.settings = Settings(self)
        qapp.aboutToQuit.connect(self.stop)
        self.apply(self.cfg)

    def show_settings(self):
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def set_control_mode(self, mode):
        cfg = {**self.cfg, "control_mode": mode}
        config.save(cfg)
        self.apply(cfg)
        # only these two widgets: a full load() would throw away edits not saved yet
        self.settings.fields["control_mode"].setCurrentText(mode)
        self.settings.set_picker.setCurrentIndex(1 if mode == "actions" else 0)

    def run_wizard(self):
        self.show_settings()
        Wizard(self.settings).exec()

    def calibrate_monitors(self):
        if len(actions.monitors()) < 2:
            QMessageBox.information(self.settings, "handctl", "Only one monitor is connected, so there is nothing to switch between.")
            return
        self.show_settings()
        MonitorCalibration(self.settings).exec()

    def stop(self):
        if self.hotkey:
            self.hotkey.stop()
        if self.tracker:
            self.tracker.requestInterruption()
            self.tracker.wait()

    def apply(self, cfg):
        self.stop()
        self.cfg = cfg
        self.tracker = Tracker(cfg, enabled=not self.calibrating, face=self.force_face)
        self.tracker.preview = self.settings.isVisible()

        def frame(image, text):
            self.settings.show_frame(image, text)
            if self.frame_hook:
                self.frame_hook(image, text)

        self.tracker.frame.connect(frame)
        self.tracker.sample.connect(lambda hands: self.sample_hook and self.sample_hook(hands))
        self.tracker.look.connect(lambda seen: self.look_hook and self.look_hook(seen))
        self.tracker.error.connect(lambda msg: self.tray.showMessage("handctl", msg, QSystemTrayIcon.MessageIcon.Warning))
        self.tracker.toggled.connect(self.toggle_action.setChecked)
        self.toggle_action.setChecked(not self.calibrating)
        self.action_only.setChecked(cfg["control_mode"] == "actions")
        self.tracker.start()
        self.hotkey = keyboard.GlobalHotKeys({cfg["toggle_hotkey"]: self.tracker.toggle})
        self.hotkey.start()


_mutex = None  # module-level so the handle lives as long as the process


def already_running():
    # shortcut: Windows named mutex; the OS frees it when the process exits, so a crash can't leave a stale lock
    global _mutex
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex = kernel32.CreateMutexW(None, False, "handctl-single-instance")
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def self_check():
    """`handctl --check`: proves this copy is complete (both models load and run, monitors can be read) without
    touching the camera, mouse or keyboard. Returns the exit code: 0 = OK. Details go to handctl-check.log in the temp folder."""
    import tempfile
    import traceback

    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions, GestureRecognizer, GestureRecognizerOptions

    from .tracker import FACE_MODEL, MODEL

    log = Path(tempfile.gettempdir()) / "handctl-check.log"
    try:
        problems = config.validate(config.DEFAULTS)
        assert not problems, problems
        blank = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((240, 320, 3), np.uint8))
        with GestureRecognizer.create_from_options(GestureRecognizerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)))) as hands:
            hands.recognize(blank)
        with FaceLandmarker.create_from_options(FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(FACE_MODEL)))) as faces:
            faces.detect(blank)
        assert actions.monitors(), "no monitors found"
        log.write_text("ok\n", "utf-8")
        return 0
    except Exception:
        log.write_text(traceback.format_exc(), "utf-8")
        return 1


def main():
    logging.basicConfig(level=logging.INFO)
    qapp = QApplication(sys.argv)
    if "--check" in sys.argv:
        sys.exit(self_check())
    if already_running():
        if "--tray" not in sys.argv:  # silent at login (autostart), visible when the user double-clicks
            QMessageBox.information(None, "handctl", "handctl is already running. Look for its tray icon.")
        return
    # Closing the settings window quits the app (Settings.closeEvent); minimizing doesn't. Tray Quit also works.
    app = App(qapp)
    if "--tray" not in sys.argv:
        app.show_settings()
        if not app.cfg["wizard_done"]:
            QTimer.singleShot(0, app.run_wizard)  # first launch: walk through setup once the window is up
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
