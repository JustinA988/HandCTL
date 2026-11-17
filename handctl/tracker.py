"""Camera thread: frames -> MediaPipe -> Classifier -> Engine(s) -> actions, plus preview frames for the UI.
When monitor switching is on, it also reads the face a few times a second to see which monitor the user looks at."""
import logging
import time
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker, FaceLandmarkerOptions, GestureRecognizer, GestureRecognizerOptions, RunningMode,
)
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from . import actions
from .gaze import Selector, gaze
from .gestures import Classifier, Engine, anchor, assign

MODEL = Path(__file__).parent / "models" / "gesture_recognizer.task"
FACE_MODEL = MODEL.with_name("face_landmarker.task")
ANY = "Hand"  # single-hand mode tracks whichever hand shows up
LOOK_EVERY = 0.15  # seconds between face readings: plenty for choosing a monitor, and it keeps hand tracking fast


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
    look = Signal(object)  # each face reading: (yaw, pitch) of the gaze, or None when no face is visible
    error = Signal(str)
    toggled = Signal(bool)

    def __init__(self, cfg, enabled=True, face=False):
        """face=True reads the face even when monitor switching is off (the monitor calibration needs it)."""
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
        self.switching = cfg["monitor_switch"] and len(cfg["monitor_gaze"]) >= 2
        self.face = face or self.switching
        self.selector = self.target = None  # which monitor the user looks at, once monitor switching has started

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
        face, last_ms, next_look = None, 0, 0.0
        try:
            face = self._open_face()
            self._start_monitors()
            with GestureRecognizer.create_from_options(options) as recognizer:
                while not self.isInterruptionRequested():
                    ok, frame = cap.read()
                    if not ok:
                        self.error.emit("Camera stopped sending frames.")
                        break
                    t = time.monotonic()
                    if face and t >= next_look:
                        next_look = t + LOOK_EVERY
                        self._look(t, face, frame)  # the unmirrored frame, so the mirror setting can't flip left and right
                    if self.cfg["mirror"]:
                        frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    last_ms = max(last_ms + 1, int(t * 1000))  # MediaPipe requires strictly increasing timestamps
                    result = recognizer.recognize_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), last_ms)
                    hands = self._read(result, t)
                    self._step(t, hands)
                    self.sample.emit(hands)
                    if self.preview:
                        self._emit(rgb, hands)
        finally:
            cap.release()
            if face:
                face.close()
            self._release()  # never leave the mouse button stuck down
            actions.look_at(None)  # the hand maps to the whole desktop again once tracking stops

    def _open_face(self):
        if not self.face:
            return None
        if not FACE_MODEL.exists():
            self.error.emit(f"Face model missing: {FACE_MODEL}. Monitor switching is off; see README for the download step.")
            return None
        return FaceLandmarker.create_from_options(
            FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(FACE_MODEL)), num_faces=1))

    def _start_monitors(self):
        """Monitor switching starts on the monitor the cursor is on, so nothing jumps at launch."""
        actions.look_at(None)
        if not self.switching:
            return
        rects = actions.monitors()
        points = {name: tuple(p) for name, p in self.cfg["monitor_gaze"].items() if name in rects}
        if len(points) < 2:
            self.error.emit("Monitor switching is off: fewer than two calibrated monitors are connected. "
                            "Run Settings > Monitors > Calibrate monitors again.")
            return
        self.target = actions.monitor_at(*actions.mouse.position, rects)
        self.selector = Selector(points, self.target if self.target in points else None)
        actions.look_at(self.target)

    def _look(self, t, face, frame):
        result = face.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        height, width = frame.shape[:2]
        seen = gaze([(p.x, p.y, p.z) for p in result.face_landmarks[0]], width, height) if result.face_landmarks else None
        self.look.emit(seen)
        if not (self.selector and self.enabled):
            return
        target = self.selector.update(t, seen)
        if target and target != self.target:
            self.target = target
            try:
                actions.look_at(target)
            except Exception as e:  # a failed cursor move must not kill tracking
                logging.exception("Monitor switch failed")
                self.error.emit(f"Monitor switch failed: {e}")

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
        if self.selector:
            seen += f" | looking at: {(self.target or 'unknown').lstrip(chr(92) + '.')}"
        self.frame.emit(QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy(), f"Tracking {state} | {seen}")
