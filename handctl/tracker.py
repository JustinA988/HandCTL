"""Camera thread: frames -> MediaPipe -> Classifier -> Engine(s) -> actions, plus preview frames for the UI."""
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
from .gestures import Classifier, Engine, anchor, assign

MODEL = Path(__file__).parent / "models" / "gesture_recognizer.task"
ANY = "Hand"  # single-hand mode tracks whichever hand shows up


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
    sample = Signal(object)  # every frame: {side: {"gesture", "pos", "lm", "feat"}}, for the setup wizard
    error = Signal(str)
    toggled = Signal(bool)

    def __init__(self, cfg, enabled=True):
        super().__init__()
        self.cfg = cfg
        self.enabled = enabled
        self.preview = False
        if cfg["hand_mode"] == "two":  # the pointer hand moves the cursor, the other hand does everything else
            other = "Left" if cfg["hand"] == "Right" else "Right"
            self.engines = {cfg["hand"]: Engine(cfg, "pointer"), other: Engine(cfg, "action")}
        else:
            self.engines = {ANY: Engine(cfg)}
        self.classifiers = {side: Classifier(cfg) for side in self.engines}
        self.last = {}  # side -> (time, position) it was last seen at

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
        # shortcut: 0.3 instead of MediaPipe's 0.5 so a tilted or edge-on hand is dropped less often; untested guess,
        # raise it if the tracker starts seeing hands that aren't there
        options = GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL)), running_mode=RunningMode.VIDEO, num_hands=len(self.engines),
            min_hand_detection_confidence=0.3, min_hand_presence_confidence=0.3, min_tracking_confidence=0.3)
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
                    hands = self._read(result, t)
                    self._step(t, hands)
                    self.sample.emit(hands)
                    if self.preview:
                        self._emit(rgb, hands)
        finally:
            cap.release()
            self._release()  # never leave the mouse button stuck down

    def _step(self, t, hands):
        if not self.enabled:
            self._release()
            for engine in self.engines.values():
                engine.reset()
            return
        for side, engine in self.engines.items():
            hand = hands.get(side)
            for event in engine.update(t, hand and hand["gesture"], hand and hand["pos"]):
                self._execute(event)

    def _release(self):
        if any(e.down for e in self.engines.values()):
            self._execute(("release",))

    def _read(self, result, t):
        """{side: hand} for the hands in view. side is ANY in single-hand mode, else "Left" / "Right"."""
        found = []
        for i, points in enumerate(result.hand_landmarks):
            label = result.handedness[i][0].category_name
            if not self.cfg["mirror"]:
                label = {"Left": "Right", "Right": "Left"}[label]  # MediaPipe labels assume a mirrored image
            top = result.gestures[i][0] if i < len(result.gestures) and result.gestures[i] else None
            lm = [(p.x, p.y) for p in points]
            found.append({"label": label, "lm": lm, "pos": anchor(lm), "canned": top.category_name if top else "None",
                          "score": top.score if top else 0.0, "world": [(p.x, p.y, p.z) for p in result.hand_world_landmarks[i]]})
        if ANY in self.engines:
            sides = {ANY: 0} if found else {}
        else:
            sides = assign([(h["label"], h["pos"]) for h in found], self.last, t, self.cfg["mirror"])
        hands = {}
        for side, i in sides.items():
            hand = found[i]
            hand["gesture"], hand["feat"] = self.classifiers[side](hand["canned"], hand["score"], hand["world"])
            self.last[side] = (t, hand["pos"])
            hands[side] = hand
        return hands

    def _execute(self, event):
        try:
            actions.execute(event, self.cfg)
        except Exception as e:  # a bad mapping must not kill tracking
            logging.exception("Action failed: %s", event)
            self.error.emit(f"Action failed: {e}")

    def _emit(self, rgb, hands):
        h, w, _ = rgb.shape
        x0, y0, x1, y1 = self.cfg["box"]
        cv2.rectangle(rgb, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), (0, 200, 255), 2)
        for hand in hands.values():
            for x, y in hand["lm"]:
                cv2.circle(rgb, (int(x * w), int(y * h)), 3, (0, 255, 0), -1)
            cv2.circle(rgb, (int(hand["pos"][0] * w), int(hand["pos"][1] * h)), 9, (255, 80, 80), 2)  # what the cursor follows
        state = "ON" if self.enabled else "OFF (hotkey to enable)"
        # the pinch number is shown so the pinch threshold slider can be tuned by eye
        seen = " | ".join(f"{side}: {hands[side]['gesture']} (pinch {hands[side]['feat']['pinch']:.2f})" if side in hands
                          else f"{side}: not in view" for side in self.engines)
        self.frame.emit(QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy(), f"Tracking {state} | {seen}")
