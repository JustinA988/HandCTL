"""Entry point: tray icon, settings window, global hotkey toggle. Run with `python -m handctl`."""
import copy
import ctypes
import logging
import sys
import winreg
from pathlib import Path

from pynput import keyboard
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSpinBox, QStyle, QSystemTrayIcon, QTableWidget, QTabWidget,
    QVBoxLayout, QWidget,
)

from . import config
from .tracker import Tracker, list_cameras

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


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


class Settings(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("handctl settings")

        self.fields = {
            "hand": combo(["Right", "Left"]), "toggle_hotkey": QLineEdit(),
            "hold_ms": spin(0, 2000), "drag_ms": spin(0, 2000),
            "shell_enabled": QCheckBox("Allow gestures to run shell commands"),
            "autostart": QCheckBox("Start with Windows"),
            "mirror": QCheckBox("Mirror camera image"), "min_cutoff": spin(0.1, 5, 0.1), "beta": spin(0, 20, 0.5),
            "pinch_threshold": spin(0.05, 1, 0.05), "scroll_speed": spin(1, 200),
        }
        self.box = [spin(0, 1, 0.05) for _ in range(4)]

        self.preview = QLabel("Starting camera...")
        self.preview.setMinimumSize(640, 480)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status = QLabel()
        calibration = QFormLayout()
        for label, w in zip(["Cursor area left", "top", "right", "bottom"], self.box):
            calibration.addRow(label, w)
        calibration.addRow(self.fields["mirror"])
        calibration.addRow("Steadiness (lower = steadier)", self.fields["min_cutoff"])
        calibration.addRow("Responsiveness (higher = less lag)", self.fields["beta"])
        calibration.addRow("Pinch threshold", self.fields["pinch_threshold"])
        calibration.addRow("Scroll speed", self.fields["scroll_speed"])
        preview_tab = QWidget()
        row = QHBoxLayout(preview_tab)
        self.camera = QComboBox()
        self.camera.activated.connect(self.switch_camera)  # user picks only; filling the list must not restart tracking
        rescan = QPushButton("Refresh")
        rescan.clicked.connect(self.refresh_cameras)
        pick = QHBoxLayout()
        pick.addWidget(QLabel("Camera"))
        pick.addWidget(self.camera, 1)
        pick.addWidget(rescan)
        self.fill_cameras(app.cfg["camera"])  # runs before tracking starts, so every camera is free to probe
        left = QVBoxLayout()
        left.addLayout(pick)
        left.addWidget(self.preview)
        left.addWidget(self.status)
        row.addLayout(left)
        row.addLayout(calibration)

        self.table = QTableWidget(len(config.GESTURES), 5)
        self.table.setHorizontalHeaderLabels(["Gesture", "Action", "Value", "Cooldown ms", "Repeat while held"])
        self.rows = []
        for i, name in enumerate(config.GESTURES):
            label = QLabel(name)
            cells = [combo(config.ACTION_TYPES), QLineEdit(), spin(0, 10000), QCheckBox()]
            self.table.setCellWidget(i, 0, label)
            for col, w in enumerate(cells, 1):
                self.table.setCellWidget(i, col, w)
            self.rows.append((name, *cells))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        reset = QPushButton("Reset gestures to defaults")
        reset.clicked.connect(lambda: self.put_mappings(config.DEFAULTS["mappings"]))
        gestures_tab = QWidget()
        g = QVBoxLayout(gestures_tab)
        g.addWidget(self.table)
        g.addWidget(QLabel(
            "Action values - mouse: move, left, right, scroll | keys: <ctrl>+<alt>+t, <cmd>+d, <media_next> | "
            "shell: any command (only runs if enabled under General)."))
        g.addWidget(reset)

        general_tab = QWidget()
        f = QFormLayout(general_tab)
        f.addRow("Tracked hand", self.fields["hand"])
        f.addRow("Toggle hotkey", self.fields["toggle_hotkey"])
        f.addRow("Hold before firing (ms)", self.fields["hold_ms"])
        f.addRow("Pinch hold before drag (ms)", self.fields["drag_ms"])
        f.addRow(self.fields["shell_enabled"])
        f.addRow(self.fields["autostart"])

        tabs = QTabWidget()
        tabs.addTab(preview_tab, "Preview && calibration")
        tabs.addTab(gestures_tab, "Gestures")
        tabs.addTab(general_tab, "General")
        save = QPushButton("Save && apply")
        save.clicked.connect(self.save)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(save)
        self.load(app.cfg)

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
        self.put_mappings(cfg["mappings"])

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
            return
        config.save(cfg)
        set_autostart(cfg["autostart"])
        self.app.apply(cfg)

    def show_frame(self, image, text):
        self.preview.setPixmap(QPixmap.fromImage(image))
        self.status.setText(text)

    def showEvent(self, event):
        self.app.tracker.preview = True

    def hideEvent(self, event):
        self.app.tracker.preview = False

    def closeEvent(self, event):
        event.accept()
        QApplication.instance().quit()  # closing the settings window quits the app; minimizing doesn't


class App:
    def __init__(self, qapp):
        self.cfg = config.load()
        self.tracker = self.hotkey = None
        self.tray = QSystemTrayIcon(qapp.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray.setToolTip("handctl")
        menu = QMenu()
        self.toggle_action = menu.addAction("Tracking enabled")
        self.toggle_action.setCheckable(True)
        self.toggle_action.triggered.connect(lambda: self.tracker.toggle())
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

    def stop(self):
        if self.hotkey:
            self.hotkey.stop()
        if self.tracker:
            self.tracker.requestInterruption()
            self.tracker.wait()

    def apply(self, cfg):
        self.stop()
        self.cfg = cfg
        self.tracker = Tracker(cfg)
        self.tracker.preview = self.settings.isVisible()
        self.tracker.frame.connect(self.settings.show_frame)
        self.tracker.error.connect(lambda msg: self.tray.showMessage("handctl", msg, QSystemTrayIcon.MessageIcon.Warning))
        self.tracker.toggled.connect(self.toggle_action.setChecked)
        self.toggle_action.setChecked(True)
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


def main():
    logging.basicConfig(level=logging.INFO)
    qapp = QApplication(sys.argv)
    if already_running():
        if "--tray" not in sys.argv:  # silent at login (autostart), visible when the user double-clicks
            QMessageBox.information(None, "handctl", "handctl is already running. Look for its tray icon.")
        return
    # Closing the settings window quits the app (Settings.closeEvent); minimizing doesn't. Tray Quit also works.
    app = App(qapp)
    if "--tray" not in sys.argv:
        app.show_settings()
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
