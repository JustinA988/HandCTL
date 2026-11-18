"""Camera thread: frames -> MediaPipe -> Classifier -> Engine(s) -> actions, plus preview frames for the UI.
It also reads the face a few times a second: to drop phantom hands detected on the face, and (when monitor switching is
on) to see which monitor the user looks at."""
import contextlib
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

from . import actions, config
from .gaze import Selector, face_box, face_part, gaze
from .gestures import GRACE, Classifier, Engine, ModeSelector, anchor, assign, cut_off

MODEL = Path(__file__).parent / "models" / "gesture_recognizer.task"
FACE_MODEL = MODEL.with_name("face_landmarker.task")
ANY = "Hand"  # one-hand mode tracks whichever hand shows up
LOOK_EVERY = 0.1  # seconds between face readings when choosing a monitor: quick switches, still leaves hand tracking fast
FACE_EVERY = 0.3  # seconds between face readings when it is only there to drop phantom hands (a face moves slowly)
FACE_KEEP = 1.0  # seconds a face box stays valid after the face was last seen
PREVIEW_EVERY = 1 / 15  # the settings window needs 15 pictures a second, not every frame


def list_cameras(limit=5):
    """Indices of cameras that open. A camera already in use reads as missing, so call this with tracking stopped."""
    found = []
    for i in range(limit):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found


class HandCount:
    """Which MediaPipe recognizer the next frame should use. Asking it for two hands costs about 12 ms more per frame
    than one (it hunts for a second hand every frame), so the one-hand recognizer does the tracking and the two-hand
    one only runs while a second hand is there, plus a quick check a few times a second to notice when one arrives."""
    PROBE_EVERY = 0.25  # seconds between checks for a second hand: the most it can take to notice one
    KEEP = 1.0  # seconds a second hand may be missing before dropping back to the cheaper recognizer

    def __init__(self):
        self.two, self.next_probe, self.last_pair = False, 0.0, 0.0

    def wants_two(self, t):
        return self.two or t >= self.next_probe

    def saw(self, t, used_two, found):
        """Report what the recognizer used for this frame found."""
        if not used_two:
            return
        if found >= 2:
            self.two, self.last_pair = True, t
        elif self.two and t - self.last_pair > self.KEEP:
            self.two = False
        if not self.two:
            self.next_probe = t + self.PROBE_EVERY


class Tracker(QThread):
    frame = Signal(QImage, str)
    sample = Signal(object)  # every frame: {side: {"gesture", "pos", "lm", "feat"}}, for the setup wizard
    look = Signal(object)  # each face reading: (yaw, pitch, head-only yaw) of the gaze, or None when no face is visible
    error = Signal(str)
    toggled = Signal(bool)

    def __init__(self, cfg, enabled=True, face=False):
        """face=True reads the face even when monitor switching is off (the monitor calibration needs it)."""
        super().__init__()
        self.cfg = cfg
        self.enabled = enabled
        self.preview = False
        if cfg["hand_mode"] == "one":
            self.engines = {ANY: Engine(cfg)}
        else:  # "auto": up to two hands; _mode_side decides each frame whether one of them only picks a mode
            self.engines = {"Left": Engine(cfg), "Right": Engine(cfg)}
        self.classifiers = {side: Classifier(cfg) for side in self.engines}
        self.modes = ModeSelector(cfg)
        self.mode = None  # the mode the other hand is holding right now
        self._mode_hand = None  # which side was the mode hand last frame
        self.last = {}  # side -> (time, position) it was last seen at
        self.faces = (0.0, [])  # when the faces were last seen, and their boxes in the same coordinates as the hands
        self.found = 0  # hands in the last frame, after dropping phantoms
        self.switching = cfg["monitor_switch"] and len(cfg[config.gaze_key(cfg)]) >= 2
        self.face = face or self.switching  # whether the gaze is needed; the face is read either way
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
        face, last_ms, next_look, next_preview = None, 0, 0.0, 0.0
        counter = HandCount()
        try:
            face = self._open_face()
            self._start_monitors()
            with contextlib.ExitStack() as models:
                one = models.enter_context(GestureRecognizer.create_from_options(self._options(1)))
                two = models.enter_context(GestureRecognizer.create_from_options(self._options(2))) if len(self.engines) == 2 else None
                while not self.isInterruptionRequested():
                    ok, frame = cap.read()
                    if not ok:
                        self.error.emit("Camera stopped sending frames.")
                        break
                    t = time.monotonic()
                    if face and t >= next_look:
                        next_look = t + (LOOK_EVERY if self.face else FACE_EVERY)
                        self._look(t, face, frame)  # the unmirrored frame, so the mirror setting can't flip left and right
                    if self.cfg["mirror"]:
                        frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    last_ms = max(last_ms + 1, int(t * 1000))  # MediaPipe requires strictly increasing timestamps
                    use_two = two is not None and counter.wants_two(t)
                    result = (two if use_two else one).recognize_for_video(
                        mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), last_ms)
                    hands = self._read(result, t)
                    if two is not None:
                        counter.saw(t, use_two, self.found)  # phantoms don't count, or they'd keep the slow recognizer on
                    self._step(t, hands)
                    self.sample.emit(hands)
                    if self.preview and t >= next_preview:
                        next_preview = t + PREVIEW_EVERY
                        self._emit(rgb, hands)  # drawing and handing frames to the window takes time from tracking
        finally:
            cap.release()
            if face:
                face.close()
            self._release()  # never leave the mouse button stuck down
            actions.look_at(None)  # the hand maps to the whole desktop again once tracking stops

    @staticmethod
    def _options(hands):
        # shortcut: 0.3 instead of MediaPipe's 0.5 so a tilted or edge-on hand is dropped less often; untested guess,
        # raise it if the tracker starts seeing hands that aren't there
        return GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL)), running_mode=RunningMode.VIDEO, num_hands=hands,
            min_hand_detection_confidence=0.3, min_hand_presence_confidence=0.3, min_tracking_confidence=0.3)

    def _open_face(self):
        if not FACE_MODEL.exists():
            self.error.emit(f"Face model missing: {FACE_MODEL}. Phantom-hand filtering and monitor switching are off; "
                            "see README for the download step.")
            self.switching = False
            return None
        return FaceLandmarker.create_from_options(
            FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(FACE_MODEL)), num_faces=2))

    def _start_monitors(self):
        """Monitor switching starts on the monitor the cursor is on, so nothing jumps at launch."""
        actions.look_at(None)
        if not self.switching:
            return
        rects = actions.monitors()
        points = {name: tuple(p) for name, p in self.cfg[config.gaze_key(self.cfg)].items() if name in rects}
        if len(points) < 2:
            self.error.emit("Monitor switching is off: fewer than two calibrated monitors are connected. "
                            "Run Settings > Monitors > Calibrate monitors again.")
            return
        self.target = actions.monitor_at(*actions.mouse.position, rects)
        self.selector = Selector(points, self.target if self.target in points else None,
                                 self.cfg["monitor_dwell_ms"] / 1000, self.cfg["monitor_margin"],
                                 [tuple(p) for p in self.cfg[config.gaze_key(self.cfg, ignore=True)]])
        actions.look_at(self.target)

    def _look(self, t, face, frame):
        result = face.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        height, width = frame.shape[:2]
        boxes = [face_box([(p.x, p.y) for p in landmarks]) for landmarks in result.face_landmarks]
        if self.cfg["mirror"]:  # this frame isn't mirrored, but the hands are
            boxes = [(1 - x1, y0, 1 - x0, y1) for x0, y0, x1, y1 in boxes]
        if boxes:
            self.faces = (t, boxes)
        seen = None
        if result.face_landmarks:
            lm = [(p.x, p.y, p.z) for p in result.face_landmarks[0]]
            seen = (*gaze(lm, width, height), gaze(lm, width, height, eyes=False)[0])
        self.look.emit(seen)
        if not (self.selector and self.enabled):
            return
        head = self.cfg["gaze_source"] == "head"
        target = self.selector.update(t, seen and ((seen[2], seen[1]) if head else seen[:2]))
        # the selector keeps following the eyes, but the switch waits until any gesture under way is finished, so the
        # cursor and the window never change under a pinch, a scroll or a held mode
        busy = self.mode or any(engine.busy() for engine in self.engines.values())
        if target and target != self.target and not busy:
            self.target = target
            try:
                actions.look_at(target, focus=self.cfg["monitor_focus"])
            except Exception as e:  # a failed cursor move must not kill tracking
                logging.exception("Monitor switch failed")
                self.error.emit(f"Monitor switch failed: {e}")

    def _step(self, t, hands):
        if not self.enabled:
            self._release()
            for engine in self.engines.values():
                engine.reset()
            self.mode, self._mode_hand = None, None
            self.modes.reset()
            return
        mode_side = self._mode_side(t)
        self.mode = self.modes.update(t, hands[mode_side]["gesture"] if mode_side in hands else None) if mode_side else None
        for side, engine in self.engines.items():
            if side == mode_side:
                continue  # this hand only chooses the mode
            engine.mode = self.mode
            hand = hands.get(side)
            for event in engine.update(t, hand and hand["gesture"], hand and hand["pos"]):
                self._execute(event)

    def _mode_side(self, t):
        """With both hands in view, the side whose pose picks the mode (the hand that isn't the main one); None when only
        one hand is in view, so that hand does everything. A hand missing for under GRACE still counts, so a tracking
        hiccup doesn't flip roles."""
        if ANY in self.engines or len(self.last) < 2 or any(t - seen >= GRACE for seen, _ in self.last.values()):
            self._free_mode_hand(None)
            return None
        side = "Left" if self.cfg["hand"] == "Right" else "Right"
        self._free_mode_hand(side)
        return side

    def _free_mode_hand(self, side):
        """A hand that becomes the mode hand lets go of anything it was holding (a drag) and forgets its pose."""
        if side is not None and side != self._mode_hand:
            engine = self.engines[side]
            if engine.down:
                self._execute(("release",))
            engine.reset()
        if side is None:
            self.modes.reset()
        self._mode_hand = side

    def _release(self):
        if any(e.down for e in self.engines.values()):
            self._execute(("release",))

    def _read(self, result, t):
        """{side: hand} for the hands in view. side is ANY in one-hand mode, else "Left" / "Right"."""
        found = []
        faces = self.faces[1] if t - self.faces[0] < FACE_KEEP else []
        for i, points in enumerate(result.hand_landmarks):
            outline = [(p.x, p.y) for p in points]
            if face_part(outline, faces) or cut_off(outline):
                continue  # a phantom hand on the face, or a hand the picture's edge cuts off
            label = result.handedness[i][0].category_name
            if not self.cfg["mirror"]:
                label = {"Left": "Right", "Right": "Left"}[label]  # MediaPipe labels assume a mirrored image
            top = result.gestures[i][0] if i < len(result.gestures) and result.gestures[i] else None
            lm = [(p.x, p.y) for p in points]
            found.append({"label": label, "lm": lm, "pos": anchor(lm), "canned": top.category_name if top else "None",
                          "score": top.score if top else 0.0, "world": [(p.x, p.y, p.z) for p in result.hand_world_landmarks[i]]})
        self.found = len(found)
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
        if self.cfg["control_mode"] == "actions":
            seen += " | ACTION-ONLY (cursor off)"
        if self.mode:
            seen += f" | MODE: {self.mode}"
        if self.selector:
            seen += f" | looking at: {(self.target or 'unknown').lstrip(chr(92) + '.')}"
        self.frame.emit(QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy(), f"Tracking {state} | {seen}")
