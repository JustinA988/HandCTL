import copy
import json
import random

import pytest

from handctl import config
from handctl.gestures import Engine, OneEuro, classify


def cfg(**overrides):
    c = copy.deepcopy(config.DEFAULTS)
    c.update(overrides)
    return c


def run(engine, frames):
    """frames: list of (t, gesture, anchor). Returns all events."""
    out = []
    for t, g, a in frames:
        out += engine.update(t, g, a)
    return out


def hold(gesture, start, end, anchor=(0.5, 0.5), step=0.033):
    n = int((end - start) / step)
    return [(start + i * step, gesture, anchor) for i in range(n)]


def kinds(events):
    return [e[0] for e in events]


def hand(up=(), thumb="out"):
    """Synthetic right hand: wrist at the bottom, hand size 0.3. up: fingers extended ('i', 'm', 'r', 'p')."""
    lm = [(0.5, 0.5)] * 21
    lm[0] = (0.5, 0.9)
    for name, x, (mcp, pip, dip, tip) in (("i", 0.45, (5, 6, 7, 8)), ("m", 0.5, (9, 10, 11, 12)),
                                          ("r", 0.55, (13, 14, 15, 16)), ("p", 0.6, (17, 18, 19, 20))):
        lm[mcp], lm[pip] = (x, 0.6), (x, 0.5)
        lm[dip], lm[tip] = ((x, 0.4), (x, 0.3)) if name in up else ((x, 0.55), (x, 0.62))
    lm[4] = {"out": (0.25, 0.65), "tap": (0.44, 0.55), "pinch": lm[8]}[thumb]
    return lm


def test_classify_poses():
    c = cfg()
    assert classify("None", hand("i"), c) == "Point"
    assert classify("None", hand("i", "tap"), c) == "Point_Tap"
    assert classify("None", hand("im"), c) == "Two_Finger"
    assert classify("None", hand("im", "tap"), c) == "Two_Finger_Tap"
    assert classify("None", hand("imr"), c) == "Three_Finger"
    assert classify("None", hand("imr", "tap"), c) == "Three_Finger_Tap"
    assert classify("None", hand(""), c) == "Closed_Fist"
    assert classify("None", hand("mrp", "pinch"), c) == "Pinch"
    assert classify("Closed_Fist", hand("", "pinch"), c) == "Closed_Fist"  # fist wins over pinch
    for trusted in ("Thumb_Up", "ILoveYou"):
        assert classify(trusted, hand(""), c) == trusted
    # a finger pointing at the camera looks curled in 2D; MediaPipe's label rescues it
    assert classify("Pointing_Up", hand(""), c) == "Point"
    # flat open palm (wrist-straining, so not a gesture) and odd shapes do nothing
    assert classify("Open_Palm", hand("imrp"), c) == "None"
    assert classify("None", hand("ip"), c) == "None"


def test_gesture_must_hold_before_firing():
    e = Engine(cfg())
    assert run(e, hold("Three_Finger_Tap", 0, 0.1)) == []
    events = run(e, hold("Three_Finger_Tap", 0.1, 0.3))
    assert kinds(events) == ["run"] and events[0][1]["value"] == "<media_play_pause>"


def test_thumb_tap_clicks_without_moving_then_drags():
    e = Engine(cfg())
    events = run(e, hold("Point_Tap", 0, 0.25, (0.3, 0.5)))
    assert kinds(events) == ["press"]  # cursor frozen during the click window
    events = run(e, hold("Point_Tap", 0.25, 0.6, (0.4, 0.6)))
    assert "move" in kinds(events)
    events = run(e, hold("Point", 0.6, 0.9))
    assert "release" in kinds(events)


def test_two_finger_scroll_and_tap_right_click():
    e = Engine(cfg())
    frames = [(i * 0.033, "Two_Finger", (0.5, 0.8 - i * 0.02)) for i in range(20)]
    assert sum(ev[1] for ev in run(e, frames) if ev[0] == "scroll") > 0  # hand up = scroll up
    events = run(e, hold("Two_Finger_Tap", 0.7, 1.0))
    assert [ev[1]["value"] for ev in events if ev[0] == "run"] == ["right"]


def test_fist_and_unmapped_poses_do_nothing():
    e = Engine(cfg())
    assert run(e, hold("Closed_Fist", 0, 0.5) + hold("None", 0.5, 1.0) + hold("Three_Finger", 1.0, 1.5)) == []


def test_cooldown():
    e = Engine(cfg())
    events = run(e, hold("Three_Finger_Tap", 0, 0.3) + hold("Three_Finger", 0.3, 0.6) + hold("Three_Finger_Tap", 0.6, 0.9))
    assert kinds(events).count("run") == 1  # second play/pause is inside the 1000 ms cooldown


def test_thumbs_up_slider_sets_volume_by_height():
    e = Engine(cfg())
    up = run(e, [(i * 0.033, "Thumb_Up", (0.5, 0.8 - i * 0.02)) for i in range(20)])
    assert {ev[1]["value"] for ev in up if ev[0] == "run"} == {"<media_volume_up>"}
    down = run(e, [(0.7 + i * 0.033, "Thumb_Up", (0.5, 0.42 + i * 0.02)) for i in range(20)])
    assert {ev[1]["value"] for ev in down if ev[0] == "run"} == {"<media_volume_down>"}


def test_three_finger_swipe_switches_desktops():
    e = Engine(cfg())
    frames = [(i * 0.033, "Three_Finger", (0.3 + i * 0.03, 0.5)) for i in range(8)]
    assert [ev[1]["value"] for ev in run(e, frames) if ev[0] == "run"] == ["<cmd>+<ctrl>+<right>"]
    e = Engine(cfg())
    frames = [(i * 0.033, "Three_Finger", (0.7 - i * 0.03, 0.5)) for i in range(8)]
    assert [ev[1]["value"] for ev in run(e, frames) if ev[0] == "run"] == ["<cmd>+<ctrl>+<left>"]
    e = Engine(cfg())  # the same motion with another pose is not a swipe
    assert run(e, [(i * 0.033, "Two_Finger", (0.3 + i * 0.03, 0.5)) for i in range(8)]) == []


def test_absolute_cursor_maps_box_to_screen():
    e = Engine(cfg())
    run(e, hold("Point", 0, 1.0, (0.2, 0.3)))
    assert e.pos == pytest.approx((0.0, 0.0), abs=1e-3)
    e.reset()
    run(e, hold("Point", 0, 1.0, (0.95, 0.95)))
    assert e.pos == pytest.approx((1.0, 1.0), abs=1e-3)  # clamped outside the box


def test_relative_cursor_and_fist_clutch():
    e = Engine(cfg(cursor_mode="relative"))
    moved = lambda evs: sum(ev[1] for ev in evs if ev[0] == "move_by")
    run(e, hold("Point", 0, 0.3, (0.3, 0.5)))
    right = run(e, [(0.3 + i * 0.033, "Point", (0.3 + i * 0.01, 0.5)) for i in range(20)])
    assert moved(right) > 0 and "move" not in kinds(right)
    back = run(e, [(1.0 + i * 0.033, "Closed_Fist", (0.5 - i * 0.01, 0.5)) for i in range(20)])
    assert "move_by" not in kinds(back)  # fist = lift the mouse
    again = run(e, hold("Point", 1.7, 2.2, (0.3, 0.5)))
    assert abs(moved(again)) < 0.01  # resuming from a new hand position doesn't jump the cursor


def test_two_hand_roles_pointer_moves_action_clicks():
    pointer, action = Engine(cfg(), "pointer"), Engine(cfg(), "action")
    # the pointer hand ignores everything except Point and fist: a stray thumb tap or thumbs-up does nothing
    assert run(pointer, hold("Point_Tap", 0, 0.5) + hold("Thumb_Up", 0.5, 1.0)) == []
    assert "move" in kinds(run(pointer, hold("Point", 1.0, 1.4)))
    # the action hand clicks and drags but never moves the cursor
    events = run(action, hold("Point_Tap", 0, 0.8, (0.3, 0.5)))
    assert kinds(events) == ["press"]
    assert run(action, hold("Point", 0.8, 1.2)) == [("release",)]
    assert run(action, hold("Closed_Fist", 1.2, 1.5)) == []


def test_one_euro_steadies_still_hand_and_keeps_up_with_fast_moves():
    random.seed(1)
    # 0.5/2.0 is the filter's tuned setting; the shipped defaults are 5/20 by user choice and steady less
    f = OneEuro(min_cutoff=0.5, beta=2.0)
    raw = [0.5 + random.gauss(0, 0.01) for _ in range(300)]  # hand held still with sensor noise
    smooth = [f(v, i / 30) for i, v in enumerate(raw)]
    spread = lambda xs: max(xs[100:]) - min(xs[100:])
    assert spread(smooth) < spread(raw) / 3  # jitter cut by at least 3x
    f = OneEuro(min_cutoff=0.5, beta=2.0)
    f(0.0, 0.0)
    out = [f(1.0, 0.03 * i) for i in range(1, 6)]  # fast move to 1.0 over 5 frames
    assert out[-1] > 0.8  # reaches the target within ~150 ms, not seconds later


def test_relative_moves_keep_sub_pixel_motion(monkeypatch):
    from handctl import actions
    moves = []
    monkeypatch.setattr(actions, "mouse", type("FakeMouse", (), {"move": lambda self, dx, dy: moves.append((dx, dy))})())
    monkeypatch.setattr(actions, "screen_rect", lambda: (0, 0, 1000, 1000))
    monkeypatch.setattr(actions, "_remainder", [0.0, 0.0])
    for _ in range(10):
        actions.execute(("move_by", 0.00035, -0.00035), {})  # 0.35 px per frame: rounds to 0 on its own
    assert sum(m[0] for m in moves) == 3 and sum(m[1] for m in moves) == -3  # 3.5 px total, 0.5 px carried over


def test_defaults_are_valid_and_bad_values_rejected():
    assert config.validate(cfg()) == []
    c = cfg(cursor_mode="sideways", hand_mode="three")
    c["box"] = [0.5, 0, 0.5, 1]
    c["mappings"]["Three_Finger_Tap"]["value"] = "<notakey>"
    c["mappings"]["Point"]["value"] = "triple"
    c["mappings"]["Thumb_Up"]["value"] = "<media_volume_up>"  # slider needs two combos
    assert len(config.validate(c)) == 6


def test_load_backs_up_broken_file_and_ignores_wrong_types(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{broken")
    assert config.load(p) == config.DEFAULTS
    assert (tmp_path / "config.json.bak").read_text() == "{broken"
    p.write_text(json.dumps({"version": 2, "camera": "zero", "beta": 2, "unknown": 5}))
    loaded = config.load(p)
    assert loaded["camera"] == 0 and loaded["beta"] == 2 and "unknown" not in loaded
    p.write_text(json.dumps({"version": 2, "box": [1, 2], "mappings": {"Point_Tap": {"type": "keys"}, "Thumb_Up": "x"}}))
    assert config.load(p) == config.DEFAULTS  # malformed values fall back instead of crashing tracking


def test_v1_settings_keep_camera_but_get_new_gesture_mappings(tmp_path):
    p = tmp_path / "config.json"
    v1 = {"camera": 1, "min_cutoff": 0.5, "mappings": {"Pointing_Up": {"type": "mouse", "value": "move"}}}
    p.write_text(json.dumps(v1))
    loaded = config.load(p)
    assert loaded["camera"] == 1 and loaded["min_cutoff"] == 0.5
    assert loaded["mappings"] == config.DEFAULTS["mappings"] and loaded["version"] == 2
    assert loaded["wizard_done"] is False  # v1 users get the setup wizard on first launch
