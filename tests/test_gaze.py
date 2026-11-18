import math
import time
import types

import numpy as np
import pytest

from handctl import actions, config, wizard
from handctl.gaze import Selector, calibrate, gaze
from handctl.tracker import Tracker

from test_gestures import cfg

A, B, C = (0, 0, 1000, 500), (1000, -200, 500, 1000), (1500, 0, 1000, 500)  # fake monitors: left, top, width, height


def face(head_yaw=0.0, head_pitch=0.0, eye_yaw=0.0, width=640, height=480):
    """MediaPipe-style landmarks of a simple 3D face (mm) whose head and eyes are turned by known angles (degrees).
    Convention as MediaPipe reports it: x right, y down, z away from the camera, x/y normalized, z in x's scale."""
    yaw, pitch = math.radians(head_yaw), math.radians(head_pitch)
    shift = 12.5 * math.sin(math.radians(eye_yaw))  # iris travel on a 12.5 mm eyeball; eye opening is 30 mm wide
    points = {33: (-45, 0, 0), 133: (-15, 0, 0), 362: (15, 0, 0), 263: (45, 0, 0), 10: (0, -70, 0), 152: (0, 70, 0),
              468: (-30 + shift, 0, 0), 473: (30 + shift, 0, 0)}
    lm = [(0.5, 0.5, 0.0)] * 478
    for i, (x, y, z) in points.items():
        x, z = x * math.cos(yaw) - z * math.sin(yaw), x * math.sin(yaw) + z * math.cos(yaw)  # turn toward image right
        y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)  # tilt down
        lm[i] = ((320 + 2 * x) / width, (240 + 2 * y) / height, 2 * z / width)
    return lm


# --- gaze from landmarks --------------------------------------------------------------------------------------------

def test_gaze_reads_head_turns_and_eye_movement_in_degrees():
    assert gaze(face(), 640, 480) == pytest.approx((0, 0), abs=0.01)
    assert gaze(face(head_yaw=20), 640, 480) == pytest.approx((20, 0), abs=0.1)
    assert gaze(face(head_yaw=-35), 640, 480) == pytest.approx((-35, 0), abs=0.1)
    assert gaze(face(eye_yaw=15), 640, 480) == pytest.approx((15, 0), abs=0.1)
    assert gaze(face(head_pitch=12), 640, 480) == pytest.approx((0, 12), abs=0.1)
    assert gaze(face(head_yaw=20), 1280, 720) == pytest.approx((20, 0), abs=0.1)  # frame size doesn't change the angle


def test_a_glance_and_a_head_turn_toward_the_same_spot_read_the_same():
    turn, glance, mixed = gaze(face(head_yaw=25), 640, 480), gaze(face(eye_yaw=25), 640, 480), gaze(face(10, 0, 15), 640, 480)
    assert turn[0] == pytest.approx(25, abs=0.2) and glance[0] == pytest.approx(25, abs=0.2) and mixed[0] == pytest.approx(25, abs=0.2)
    assert gaze(face(head_yaw=20, eye_yaw=-20), 640, 480)[0] == pytest.approx(0, abs=0.2)  # head turned, eyes back on target


# --- calibration and monitor choice ---------------------------------------------------------------------------------

def test_calibrate_takes_the_middle_reading_and_leaves_out_unusable_monitors():
    looks = lambda yaw: [(yaw + d, 2.0) for d in (-1, 0, 1, 0, -1, 1, 0, 0, 40)]  # one wild outlier each
    points, problems = calibrate({"a": looks(-20), "b": looks(20)})
    assert points == {"a": (-20, 2.0), "b": (20, 2.0)} and problems == []
    points, problems = calibrate({"a": looks(-20), "b": looks(20), "c": [(50, 0)] * 3}, {"c": "Monitor 3"}.get)
    assert set(points) == {"a", "b"} and "Monitor 3 was left out" in problems[0] and "wasn't visible" in problems[0]
    points, problems = calibrate({"a": looks(-20), "b": looks(-17), "c": looks(30)})
    assert set(points) == {"c"} and "looked the same" in problems[0]  # a and b can't be told apart, so neither is used


def test_selector_switches_only_on_a_sustained_clear_look():
    s = Selector({"A": (-20, 0), "B": (20, 0)}, "A")
    assert s.update(0.0, (-18, 1)) == "A"
    assert s.update(0.15, (19, 0)) == "A" and s.update(0.30, (-19, 0)) == "A"  # a glance at B and back: no switch
    assert [s.update(t, (19, 0)) for t in (1.0, 1.15, 1.3)] == ["A", "A", "A"]  # looking at B, but not for long enough yet
    assert s.update(1.45, (19, 0)) == "B"
    assert s.update(2.0, (-2, 0)) == "B" and s.update(3.0, (-2, 0)) == "B"  # near the middle: not clearly nearer to A
    assert s.update(4.0, None) == "B"  # face not visible: stay put
    assert [s.update(t, (-19, 0)) for t in (5.0, 5.2, 5.45)] == ["B", "B", "A"]


def test_looking_at_a_place_to_ignore_never_switches():
    s = Selector({"A": (-20, 0), "B": (20, 0)}, "A", ignore=[(15, 30)])  # the keyboard sits below, nearer B than A
    assert [s.update(t, (15, 28)) for t in (0.0, 0.2, 0.4, 0.6, 0.8)] == ["A"] * 5  # looking down at it: stays on A
    assert [s.update(t, (19, 0)) for t in (1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6)][-1] == "B"  # looking at B still switches


def test_selector_starts_on_the_first_monitor_seen_and_needs_two_to_choose():
    s = Selector({"A": (-20, 0), "B": (20, 0)})
    assert s.update(0.0, None) is None and s.update(0.1, (15, 0)) == "B"  # nothing to switch away from: no wait
    assert Selector({"A": (0, 0)}, "A").update(0.0, (50, 0)) == "A"


# --- monitor layout and cursor carry-over ---------------------------------------------------------------------------

@pytest.fixture
def desk(monkeypatch):
    """Two fake monitors and a fake mouse; nothing real is touched."""
    mouse = types.SimpleNamespace(position=(250, 125))
    monkeypatch.setattr(actions, "mouse", mouse)
    monkeypatch.setattr(actions, "monitors", lambda: {"A": A, "B": B})
    monkeypatch.setattr(actions, "screen_rect", lambda: (0, -200, 1500, 1000))
    monkeypatch.setattr(actions, "active", None)
    monkeypatch.setattr(actions, "top_window", lambda rect: None)  # never look at or focus the real windows
    monkeypatch.setattr(actions, "bring_to_front", lambda hwnd: None)
    return mouse


def test_look_at_carries_the_cursor_to_the_same_spot_on_the_other_monitor(desk):
    assert actions.monitor_at(250, 125, {"A": A, "B": B}) == "A" and actions.monitor_at(5000, 0, {"A": A, "B": B}) is None
    actions.look_at("B")
    assert actions.active == B and desk.position == (1125, 50)  # a quarter across and a quarter down, as it was on A
    actions.look_at("B")
    assert desk.position == (1125, 50)  # already there: nothing moves
    actions.execute(("move", 1.0, 1.0), {})
    assert desk.position == (1499, 799)  # the hand now maps onto monitor B only
    actions.look_at(None)
    actions.execute(("move", 0.0, 0.0), {})
    assert actions.active is None and desk.position == (0, -200)  # switching off: the hand maps to the whole desktop
    actions.look_at("unplugged")
    assert actions.active is None


def test_real_monitor_layout_adds_up_to_the_desktop():
    rects = actions.monitors()  # read-only query of the real machine
    assert rects and all(w > 0 and h > 0 for _, _, w, h in rects.values())
    left, top = min(r[0] for r in rects.values()), min(r[1] for r in rects.values())
    right, bottom = max(r[0] + r[2] for r in rects.values()), max(r[1] + r[3] for r in rects.values())
    assert (left, top, right - left, bottom - top) == actions.screen_rect()


def test_monitor_settings_are_validated():
    assert config.validate(cfg(monitor_switch=True, monitor_gaze={"A": [-20.0, 0.0], "B": [20, 1]})) == []
    assert "calibration first" in config.validate(cfg(monitor_switch=True))[0]
    assert "damaged" in config.validate(cfg(monitor_gaze={"A": [1.0], "B": "x"}))[0]


# --- tracker: reading the face and switching ------------------------------------------------------------------------

def looking(head_yaw):
    """A stand-in for MediaPipe's face landmarker that always sees a face turned by head_yaw (None = no face)."""
    ns = types.SimpleNamespace
    faces = [] if head_yaw is None else [[ns(x=x, y=y, z=z) for x, y, z in face(head_yaw=head_yaw)]]
    return ns(detect=lambda image: ns(face_landmarks=faces))


FRAME = np.zeros((480, 640, 3), np.uint8)
CALIBRATED = dict(monitor_switch=True, monitor_focus=False, monitor_dwell_ms=400, monitor_gaze={"A": [-20.0, 0.0], "B": [20.0, 0.0]})


def test_tracker_switches_monitor_when_the_user_looks_across(qapp, desk):
    t = Tracker(cfg(**CALIBRATED))
    seen = []
    t.look.connect(seen.append)
    t._start_monitors()
    assert t.face and t.target == "A" and actions.active == A  # starts on the monitor the cursor is on: nothing jumps
    for now in (0.0, 0.15, 0.3):
        t._look(now, looking(20), FRAME)
    assert t.target == "A" and seen[-1] == pytest.approx((20, 0, 20), abs=0.2)  # with eyes, pitch, head only
    t._look(0.45, looking(20), FRAME)
    assert t.target == "B" and actions.active == B and desk.position == (1125, 50)
    t._look(1.0, looking(None), FRAME)
    assert t.target == "B" and seen[-1] is None  # face lost: stays on B


def test_look_at_with_focus_brings_the_front_window_forward_and_centres_the_cursor(desk, monkeypatch):
    fronted = []
    monkeypatch.setattr(actions, "bring_to_front", fronted.append)
    monkeypatch.setattr(actions, "top_window", lambda rect: ("win", (900, 0, 1300, 400)) if rect == B else None)
    actions.look_at("B", focus=True)
    assert fronted == ["win"] and desk.position == (1150, 200)  # the middle of the part of the window on B
    actions.look_at("A", focus=True)
    assert fronted == ["win"] and desk.position == (500, 250)  # no window there: the middle of the monitor


def test_head_only_follows_the_head_turn_and_a_switch_waits_for_the_gesture(qapp, desk):
    t = Tracker(cfg(**{**CALIBRATED, "gaze_source": "head", "monitor_head": {"A": [-20.0, 0.0], "B": [20.0, 0.0]},
                       "monitor_gaze": {}}))
    t._start_monitors()
    for now in (0.0, 0.15, 0.3, 0.45, 0.6):
        t._look(now, looking(20), FRAME)
    assert t.target == "B"  # switched on the head turn alone
    busy = t.engines["Right"]
    busy.current, busy.action = "Closed_Fist", ("Closed_Fist", {"type": "mouse", "value": "scroll"})  # mid-scroll
    for now in (1.0, 1.15, 1.3, 1.45, 1.6):
        t._look(now, looking(-20), FRAME)
    assert t.target == "B"  # looked back at A, but the scroll isn't finished
    busy.current, busy.action = "Hand", None
    t._look(1.75, looking(-20), FRAME)
    assert t.target == "A"  # done: the switch happens straight away


def test_tracker_does_not_switch_while_tracking_is_paused(qapp, desk):
    t = Tracker(cfg(**CALIBRATED), enabled=False)
    t._start_monitors()
    for now in (0.0, 0.2, 0.5, 0.8):
        t._look(now, looking(20), FRAME)
    assert t.target == "A" and desk.position == (250, 125)


def test_monitor_switching_stays_off_without_two_connected_calibrated_monitors(qapp, desk):
    plain = Tracker(cfg())
    plain._start_monitors()
    assert not plain.face and plain.selector is None and actions.active is None
    errors = []
    gone = Tracker(cfg(monitor_switch=True, monitor_gaze={"A": [-20.0, 0.0], "Unplugged": [20.0, 0.0]}))
    gone.error.connect(errors.append)
    gone._start_monitors()
    assert gone.selector is None and actions.active is None and "fewer than two" in errors[0]
    assert Tracker(cfg(), face=True).face  # the calibration can ask for face reading on its own


# --- calibration dialog ---------------------------------------------------------------------------------------------

@pytest.fixture
def calibration(fake_app, monkeypatch):
    import handctl.__main__ as main
    monkeypatch.setattr(actions, "monitors", lambda: {"B": B, "A": A, "C": C})
    monkeypatch.setattr(wizard.MonitorCalibration, "READY", 0.03)
    monkeypatch.setattr(wizard.MonitorCalibration, "HOLD", 0.03)
    settings = main.Settings(fake_app)
    dialog = wizard.MonitorCalibration(settings)
    assert fake_app.calibrating and fake_app.force_face and list(dialog.rects) == ["A", "B", "C"]  # left to right

    def run(yaws, spot_only=False):
        """Walk through the steps: each monitor, then the keyboard. yaws[i] is where the user looks for step i: a yaw (the
        head turns about half as far), a full (yaw, pitch, head yaw) reading, or None (face not visible)."""
        nonlocal dialog
        if spot_only:
            dialog = wizard.MonitorCalibration(settings, spot_only=True)
        dialog.next_monitor()
        for yaw in yaws:
            dialog.on_look((99.0, 0.0, 99.0))  # readings before recording starts must be ignored
            time.sleep(0.04)
            dialog.tick()  # get-ready time is over: recording
            for _ in range(10):
                dialog.on_look(yaw if yaw is None or isinstance(yaw, tuple) else (yaw, 1.0, yaw / 2))
            time.sleep(0.04)
            dialog.tick()  # recording is over: next step, or finish
        return dialog

    return run, fake_app


def test_monitor_calibration_saves_and_turns_switching_on(calibration):
    run, app = calibration
    dialog = run([-30.0, 0.0, 30.0, (0.0, 30.0, 0.0)])  # the keyboard: looking down
    saved = app.saved[-1]
    assert saved["monitor_gaze"] == {"A": [-30.0, 1.0], "B": [0.0, 1.0], "C": [30.0, 1.0]} and saved["monitor_switch"] is True
    assert saved["monitor_head"] == {"A": [-15.0, 1.0], "B": [0.0, 1.0], "C": [15.0, 1.0]}  # head-only, from the same run
    assert saved["ignore_gaze"] == [[0.0, 30.0]] and saved["ignore_head"] == [[0.0, 30.0]]
    assert config.validate(saved) == [] and "Monitor 1, Monitor 2, Monitor 3" in dialog.text.text()
    dialog.done(1)
    assert app.applied[-1] == saved and not app.calibrating and not app.force_face and app.look_hook is None


def test_monitor_calibration_keeps_the_monitors_it_could_see(calibration):
    run, app = calibration
    dialog = run([-30.0, 0.0, None, (0.0, 30.0, 0.0)])  # face not visible while looking at the third monitor
    assert set(app.saved[-1]["monitor_gaze"]) == {"A", "B"} and "Monitor 3 was left out" in dialog.text.text()


def test_a_keyboard_that_looks_like_a_monitor_is_left_out(calibration):
    run, app = calibration
    dialog = run([-30.0, 0.0, 30.0, (2.0, 1.0, 1.0)])  # the keyboard reads almost like monitor 2
    assert app.saved[-1]["ignore_gaze"] == [] and "looked the same as Monitor 2" in dialog.text.text()
    assert len(app.saved[-1]["monitor_gaze"]) == 3  # the monitors are kept


def test_adding_a_place_to_ignore_keeps_everything_else(calibration):
    run, app = calibration
    app.cfg.update(monitor_switch=True, monitor_gaze={"A": [-30.0, 1.0], "B": [30.0, 1.0]},
                   monitor_head={"A": [-15.0, 1.0], "B": [15.0, 1.0]}, ignore_gaze=[[0.0, 30.0]], ignore_head=[[0.0, 30.0]])
    dialog = run([(-5.0, -25.0, -2.0)], spot_only=True)  # a phone held up to the left
    saved = app.saved[-1]
    assert saved["ignore_gaze"] == [[0.0, 30.0], [-5.0, -25.0]] and saved["ignore_head"] == [[0.0, 30.0], [-2.0, -25.0]]
    assert saved["monitor_gaze"] == app.cfg["monitor_gaze"] and "won't switch" in dialog.text.text()


def test_failed_monitor_calibration_changes_nothing(calibration):
    run, app = calibration
    dialog = run([-30.0, None, None, None])
    assert app.saved == [] and "didn't work" in dialog.text.text()
    dialog.done(0)
    assert app.applied[-1] == app.cfg and app.applied[-1]["monitor_switch"] is False and not app.calibrating
