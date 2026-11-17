import copy
import json

import pytest

from handctl import config
from handctl.gestures import Engine, OneEuro, classify


def cfg():
    return copy.deepcopy(config.DEFAULTS)


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


def hand(thumb_tip, index_tip, middle_tip=(0.5, 0.1)):
    lm = [(0.5, 0.5)] * 21
    lm[0], lm[9] = (0.5, 0.9), (0.5, 0.5)  # hand size 0.4
    lm[4], lm[8], lm[12] = thumb_tip, index_tip, middle_tip
    return lm


def test_classify_pinches():
    assert classify("None", hand((0.3, 0.3), (0.32, 0.3)), 0.3) == "Pinch"
    assert classify("None", hand((0.3, 0.3), (0.6, 0.1), middle_tip=(0.31, 0.3)), 0.3) == "Pinch_Middle"
    assert classify("Pointing_Up", hand((0.3, 0.3), (0.5, 0.0)), 0.3) == "Pointing_Up"
    assert classify("Closed_Fist", hand((0.3, 0.3), (0.32, 0.3)), 0.3) == "Closed_Fist"
    # curled middle finger near the thumb is not a right-click pinch
    assert classify("Pointing_Up", hand((0.5, 0.7), (0.5, 0.0), middle_tip=(0.52, 0.7)), 0.3) == "Pointing_Up"


def test_gesture_must_hold_before_firing():
    e = Engine(cfg())
    assert run(e, hold("Closed_Fist", 0, 0.1)) == []
    events = run(e, hold("Closed_Fist", 0.1, 0.3))
    assert kinds(events) == ["run"] and events[0][1]["value"] == "<media_play_pause>"


def test_pinch_clicks_without_moving_then_drags():
    e = Engine(cfg())
    events = run(e, hold("Pinch", 0, 0.25, (0.3, 0.3)))
    assert kinds(events) == ["press"]  # cursor frozen during the click window
    events = run(e, hold("Pinch", 0.25, 0.6, (0.4, 0.4)))
    assert "move" in kinds(events)
    events = run(e, hold(None, 0.6, 0.9, None))
    assert kinds(events) == ["release"]


def test_cooldown_and_repeat():
    c = cfg()
    e = Engine(c)
    events = run(e, hold("Thumb_Up", 0, 1.0))
    assert 4 <= kinds(events).count("run") <= 6  # repeats every 150 ms after the 150 ms hold
    e = Engine(c)
    events = run(e, hold("Closed_Fist", 0, 0.3) + hold("Open_Palm", 0.3, 0.6) + hold("Closed_Fist", 0.6, 0.9))
    assert kinds(events).count("run") == 1  # second fist is inside the 1000 ms cooldown


def test_scroll_follows_vertical_motion():
    e = Engine(cfg())
    frames = [(i * 0.033, "Victory", (0.5, 0.8 - i * 0.02)) for i in range(20)]
    steps = sum(ev[1] for ev in run(e, frames) if ev[0] == "scroll")
    assert steps > 0  # hand moving up scrolls up


def test_swipe():
    e = Engine(cfg())
    frames = [(i * 0.033, "Open_Palm", (0.3 + i * 0.03, 0.5)) for i in range(10)]
    events = run(e, frames)
    assert [ev[1]["value"] for ev in events if ev[0] == "run"] == ["<cmd>+<ctrl>+<right>"]


def test_cursor_maps_box_to_screen():
    e = Engine(cfg())
    run(e, hold("Pointing_Up", 0, 1.0, (0.2, 0.15)))
    assert e.pos == pytest.approx((0.0, 0.0), abs=1e-3)
    e.reset()
    run(e, hold("Pointing_Up", 0, 1.0, (0.95, 0.95)))
    assert e.pos == pytest.approx((1.0, 1.0), abs=1e-3)  # clamped outside the box


def test_one_euro_steadies_still_hand_and_keeps_up_with_fast_moves():
    import random
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


def test_defaults_are_valid_and_bad_values_rejected():
    assert config.validate(cfg()) == []
    c = cfg()
    c["box"] = [0.5, 0, 0.5, 1]
    c["mappings"]["Thumb_Up"]["value"] = "<notakey>"
    c["mappings"]["Pinch"]["value"] = "triple"
    assert len(config.validate(c)) == 3


def test_load_backs_up_broken_file_and_ignores_wrong_types(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{broken")
    assert config.load(p) == config.DEFAULTS
    assert (tmp_path / "config.json.bak").read_text() == "{broken"
    p.write_text(json.dumps({"camera": "zero", "beta": 2, "unknown": 5}))
    loaded = config.load(p)
    assert loaded["camera"] == 0 and loaded["beta"] == 2 and "unknown" not in loaded
    p.write_text(json.dumps({"box": [1, 2], "mappings": {"Pinch": {"type": "keys"}, "Thumb_Up": "x"}}))
    assert config.load(p) == config.DEFAULTS  # malformed values fall back instead of crashing tracking
