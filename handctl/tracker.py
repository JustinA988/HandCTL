"""Camera thread: frames -> MediaPipe -> Engine -> actions, plus preview frames for the UI."""
import logging
import time
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import GestureRecognizer, GestureRecognizerOptions, RunningMode
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from . import actions
from .gestures import Engine, classify

MODEL = Path(__file__).parent / "models" / "gesture_recognizer.task"


def list_cameras(limit=5):
    """Indices of cameras that open. A camera already in use reads as missing, so call this with tracking stopped."""
    found = []
    for i in range(limit):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found


class Tracker(QThread):
    frame = Signal(QImage, str)
    error = Signal(str)
    toggled = Signal(bool)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.enabled = True
        self.preview = False
        self.engine = Engine(cfg)

    def toggle(self):
        self.enabled = not self.enabled
        self.toggled.emit(self.enabled)

    def run(self):
        if not MODEL.exists():
            self.error.emit(f"Model file missing: {MODEL}. See README for the download step.")
            return
        cap = cv2.VideoCapture(self.cfg["camera"], cv2.CAP_DSHOW)
        if not cap.isOpened():
            self.error.emit(f"Could not open camera {self.cfg['camera']}.")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)  # shortcut: higher resolutions drop to ~4 FPS on this CPU with a hand in view
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        options = GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL)), running_mode=RunningMode.VIDEO, num_hands=1)
        last_ms = 0
        try:
            with GestureRecognizer.create_from_options(options) as recognizer:
                while not self.isInterruptionRequested():
                    ok, frame = cap.read()
                    if not ok:
                        self.error.emit("Camera stopped sending frames.")
                        break
                    if self.cfg["mirror"]:
                        frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    t = time.monotonic()
                    last_ms = max(last_ms + 1, int(t * 1000))  # MediaPipe requires strictly increasing timestamps
                    result = recognizer.recognize_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), last_ms)
                    gesture, lm = self._read(result)
                    if self.enabled:
                        for event in self.engine.update(t, gesture, lm[5] if lm else None):  # index knuckle: steady while pinching
                            self._execute(event)
                    else:
                        if self.engine.down:
                            self._execute(("release",))
                        self.engine.reset()
                    if self.preview:
                        self._emit(rgb, lm, gesture)
        finally:
            cap.release()
            if self.engine.down:
                self._execute(("release",))  # never leave the mouse button stuck down

    def _read(self, result):
        if not result.hand_landmarks:
            return None, None
        side = result.handedness[0][0].category_name
        if not self.cfg["mirror"]:
            side = {"Left": "Right", "Right": "Left"}[side]  # MediaPipe labels assume a mirrored image
        if side != self.cfg["hand"]:
            # shortcut: num_hands=1 can lock onto the other hand when both are visible; raise to 2 if that bites
            return None, None
        lm = [(p.x, p.y) for p in result.hand_landmarks[0]]
        canned = result.gestures[0][0].category_name if result.gestures and result.gestures[0] else "None"
        return classify(canned, lm, self.cfg["pinch_threshold"]), lm

    def _execute(self, event):
        try:
            actions.execute(event, self.cfg)
        except Exception as e:  # a bad mapping must not kill tracking
            logging.exception("Action failed: %s", event)
            self.error.emit(f"Action failed: {e}")

    def _emit(self, rgb, lm, gesture):
        h, w, _ = rgb.shape
        x0, y0, x1, y1 = self.cfg["box"]
        cv2.rectangle(rgb, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), (0, 200, 255), 2)
        for x, y in lm or []:
            cv2.circle(rgb, (int(x * w), int(y * h)), 4, (0, 255, 0), -1)
        state = "ON" if self.enabled else "OFF (hotkey to enable)"
        self.frame.emit(QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy(), f"Tracking {state} | gesture: {gesture or 'no hand'}")
