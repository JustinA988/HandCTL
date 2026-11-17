import time
import types

import pytest

from handctl import config, wizard
from handctl.tracker import Tracker

from test_gestures import cfg, hand


# --- tracker: reading one or two hands ---------------------------------------------------------------------------

def fake_result(*hands):
    """hands: (label, canned gesture, landmarks)."""
    pts = lambda lm: [types.SimpleNamespace(x=x, y=y) for x, y in lm]
    return types.SimpleNamespace(
        hand_landmarks=[pts(lm) for _, _, lm in hands],
        handedness=[[types.SimpleNamespace(category_name=label)] for label, _, _ in hands],
        gestures=[[types.SimpleNamespace(category_name=g)] for _, g, _ in hands])


def test_single_hand_mode_reads_only_the_chosen_hand(qapp):
    t = Tracker(cfg(hand="Right"))
    got = t._read(fake_result(("Left", "None", hand("im")), ("Right", "None", hand("i"))))
    assert list(got) == ["Right"] and got["Right"][0] == "Point"


def test_two_hand_mode_reads_both_hands_with_roles(qapp):
    t = Tracker(cfg(hand="Right", hand_mode="two"))
    assert {k: e.role for k, e in t.engines.items()} == {"Right": "pointer", "Left": "action"}
    got = t._read(fake_result(("Left", "None", hand("i", "tap")), ("Right", "None", hand("i"))))
    assert {k: v[0] for k, v in got.items()} == {"Left": "Point_Tap", "Right": "Point"}
    swapped = Tracker(cfg(hand="Left", hand_mode="two"))
    assert {k: e.role for k, e in swapped.engines.items()} == {"Left": "pointer", "Right": "action"}


def test_unmirrored_camera_swaps_hand_labels(qapp):
    t = Tracker(cfg(hand="Right", mirror=False))
    assert list(t._read(fake_result(("Left", "None", hand("i"))))) == ["Right"]


# --- wizard: calibration math ------------------------------------------------------------------------------------

def test_tap_threshold_sits_between_pressed_and_out_readings():
    assert wizard.tap_threshold([0.6, 0.7, 0.65] * 10, [0.05, 0.08, 0.06] * 10) == pytest.approx(0.35, abs=0.05)
    assert wizard.tap_threshold([0.2, 0.25, 0.3] * 10, [0.18, 0.2, 0.22] * 10) is None  # overlap: can't tell taps apart


def test_box_from_two_corners():
    assert wizard.box_from((0.3, 0.35), (0.7, 0.8)) == [0.3, 0.35, 0.7, 0.8]
    assert wizard.box_from((0.3, 0.35), (0.35, 0.8)) is None  # too narrow
    assert wizard.box_from((0.7, 0.35), (0.3, 0.8)) is None  # bottom-right was left of top-left


def test_pinch_fallback_replaces_the_tap_clicks():
    m = wizard.use_pinch_instead(config.DEFAULTS["mappings"])
    assert m["Pinch"] == {"type": "mouse", "value": "left"}
    assert all(m[n]["type"] == "none" for n in ("Point_Tap", "Two_Finger_Tap", "Three_Finger_Tap"))
    assert config.DEFAULTS["mappings"]["Point_Tap"]["type"] == "mouse"  # the defaults themselves are untouched
    assert config.validate({**cfg(), "mappings": m}) == []


# --- wizard flow, driven with fake samples -----------------------------------------------------------------------

@pytest.fixture
def quick_wizard(fake_app, monkeypatch):
    import handctl.__main__ as main
    original = wizard.Collector
    monkeypatch.setattr(wizard, "Collector", lambda: original(0.05))  # 3-second captures would make the test slow
    w = wizard.Wizard(main.Settings(fake_app))
    return w, fake_app


def capture(page, wizard_, hands_list):
    """Feed samples during a capture window, then one more after it ends."""
    for hands in hands_list:
        page.on_sample(wizard_, hands)
    time.sleep(0.08)
    page.on_sample(wizard_, hands_list[-1])


def test_wizard_tracking_is_off_while_it_runs(quick_wizard):
    w, app = quick_wizard
    assert app.calibrating and app.tracker.enabled is False


def test_wizard_sets_cursor_area_and_calibrates_thumb_tap(quick_wizard):
    w, app = quick_wizard
    area, thumb = w.page(1), w.page(2)
    corner = lambda x, y: {"Right": ("Point", [(x, y)] * 21)}
    area.capture("tl")
    capture(area, w, [corner(0.3, 0.35)] * 12)
    area.capture("br")
    capture(area, w, [corner(0.7, 0.8)] * 12)
    assert w.cfg["box"] == [0.3, 0.35, 0.7, 0.8]

    thumb.capture("out")
    capture(thumb, w, [{"Right": ("Point", hand("i", "out"))}] * 12)
    thumb.capture("pressed")
    capture(thumb, w, [{"Right": ("Point_Tap", hand("i", "tap"))}] * 12)
    assert 0.05 < w.cfg["tap_threshold"] < 0.67 and w.cfg["mappings"]["Point_Tap"]["type"] == "mouse"


def test_wizard_falls_back_to_pinch_when_taps_cannot_be_told_apart(quick_wizard):
    w, _ = quick_wizard
    thumb = w.page(2)
    thumb.capture("out")
    capture(thumb, w, [{"Right": ("Point", hand("i", "tap"))}] * 12)  # "out" reading looks pressed too
    thumb.capture("pressed")
    capture(thumb, w, [{"Right": ("Point_Tap", hand("i", "tap"))}] * 12)
    assert w.cfg["mappings"]["Pinch"]["value"] == "left" and w.cfg["mappings"]["Point_Tap"]["type"] == "none"


def test_wizard_gesture_check_needs_a_held_pose(quick_wizard):
    w, _ = quick_wizard
    page = w.page(3)
    page.on_sample(w, {"Right": ("Point", hand("i"))})
    assert page.labels["Point"].text().startswith("○")  # one frame is not enough
    for _ in range(6):
        page.on_sample(w, {"Right": ("Point", hand("i"))})
    assert page.labels["Point"].text().startswith("✓")


def test_wizard_finish_saves_and_cancel_keeps_settings(quick_wizard):
    w, app = quick_wizard
    w.cfg["box"] = [0.25, 0.3, 0.75, 0.85]
    w.done(1)
    assert app.saved[-1]["box"] == [0.25, 0.3, 0.75, 0.85] and app.saved[-1]["wizard_done"] is True
    assert app.applied[-1]["wizard_done"] is True and app.calibrating is False and app.sample_hook is None
