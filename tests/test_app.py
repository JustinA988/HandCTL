import subprocess
import sys
import time
import types

import pytest

from handctl import config, wizard
from handctl.tracker import ANY, Tracker

from test_gestures import cfg, world


def test_executors_work_even_when_qt_and_concurrent_futures_load_before_handctl():
    # the order a frozen build produces; on Python 3.15 PySide6 otherwise leaves these names unusable (see handctl/__init__.py)
    code = ("import PySide6.QtCore, concurrent.futures, handctl\n"
            "from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor\n"
            "assert concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(lambda: 42).result() == 42\n"
            "assert isinstance(ThreadPoolExecutor, type) and isinstance(ProcessPoolExecutor, type)\n")
    subprocess.run([sys.executable, "-c", code], check=True)


# --- tracker: reading one or two hands ---------------------------------------------------------------------------

def fake_result(*hands):
    """hands: (MediaPipe label, canned gesture, x position, 3D landmarks)."""
    ns = types.SimpleNamespace
    return ns(
        hand_landmarks=[[ns(x=x, y=0.5)] * 21 for _, _, x, _ in hands],
        hand_world_landmarks=[[ns(x=p[0], y=p[1], z=p[2]) for p in w] for _, _, _, w in hands],
        handedness=[[ns(category_name=label)] for label, _, _, _ in hands],
        gestures=[[ns(category_name=g, score=0.9)] for _, g, _, _ in hands])


def test_single_hand_mode_follows_whichever_hand_shows_up(qapp):
    for label in ("Left", "Right"):  # MediaPipe's left/right label doesn't matter, so a flipped label can't lose the hand
        t = Tracker(cfg())
        got = t._read(fake_result((label, "None", 0.4, world(thumb="index"))), 0.0)
        assert list(got) == [ANY] and got[ANY]["gesture"] == "Pinch" and got[ANY]["pos"] == pytest.approx((0.4, 0.5))


def test_two_hand_mode_assigns_roles_by_position(qapp):
    t = Tracker(cfg(hand="Right", hand_mode="two"))
    assert {k: e.role for k, e in t.engines.items()} == {"Right": "pointer", "Left": "action"}
    # both mislabelled "Right": the one on the left of the mirrored image is still the left hand
    got = t._read(fake_result(("Right", "None", 0.7, world()), ("Right", "None", 0.3, world(thumb="index"))), 0.0)
    assert {k: v["gesture"] for k, v in got.items()} == {"Left": "Pinch", "Right": "Hand"}
    swapped = Tracker(cfg(hand="Left", hand_mode="two"))
    assert {k: e.role for k, e in swapped.engines.items()} == {"Left": "pointer", "Right": "action"}


def test_no_hand_in_view(qapp):
    assert Tracker(cfg())._read(fake_result(), 0.0) == {}


# --- wizard: calibration math ------------------------------------------------------------------------------------

def test_pinch_threshold_sits_between_pinched_and_open_readings():
    threshold = wizard.pinch_threshold([0.6, 0.7, 0.65] * 10, [0.12, 0.18, 0.15] * 10)
    assert 0.18 < threshold and threshold * 1.5 <= 0.6  # above a real pinch; an open hand clearly ends it
    assert wizard.pinch_threshold([0.3, 0.32, 0.35] * 10, [0.25, 0.28, 0.3] * 10) is None  # overlap: can't tell apart


def test_box_from_two_corners():
    assert wizard.box_from((0.3, 0.35), (0.7, 0.8)) == [0.3, 0.35, 0.7, 0.8]
    assert wizard.box_from((0.3, 0.35), (0.35, 0.8)) is None  # too narrow
    assert wizard.box_from((0.7, 0.35), (0.3, 0.8)) is None  # bottom-right was left of top-left


def test_role_hand_picks_the_right_hand_for_each_job():
    hands = {"Left": "L", "Right": "R"}
    two = cfg(hand_mode="two", hand="Right")
    assert wizard.role_hand(hands, two, "pointer") == "R" and wizard.role_hand(hands, two, "action") == "L"
    assert wizard.role_hand({ANY: "H"}, cfg(), "pointer") == wizard.role_hand({ANY: "H"}, cfg(), "action") == "H"
    assert wizard.role_hand({}, cfg(), "pointer") is None


# --- wizard flow, driven with fake samples -----------------------------------------------------------------------

def sample(gesture="Hand", pos=(0.5, 0.5), pinch=0.8):
    return {ANY: {"gesture": gesture, "pos": pos, "feat": {"pinch": pinch}}}


@pytest.fixture
def quick_wizard(fake_app, monkeypatch):
    import handctl.__main__ as main
    original = wizard.Collector
    monkeypatch.setattr(wizard, "Collector", lambda: original(0.05))  # 3-second captures would make the test slow
    return wizard.Wizard(main.Settings(fake_app)), fake_app


def capture(page, wizard_, hands, n=12):
    """Feed samples during a capture window, then one more after it ends."""
    for _ in range(n):
        page.on_sample(wizard_, hands)
    time.sleep(0.08)
    page.on_sample(wizard_, hands)


def test_wizard_tracking_is_off_while_it_runs(quick_wizard):
    w, app = quick_wizard
    assert app.calibrating and app.tracker.enabled is False


def test_wizard_sets_cursor_area_and_calibrates_pinch(quick_wizard):
    w, app = quick_wizard
    area, pinch = w.page(1), w.page(2)
    area.capture("tl")
    capture(area, w, sample(pos=(0.3, 0.35)))
    area.capture("br")
    capture(area, w, sample(pos=(0.7, 0.8)))
    assert w.cfg["box"] == [0.3, 0.35, 0.7, 0.8]

    pinch.capture("open")
    capture(pinch, w, sample(pinch=0.7))
    pinch.capture("pinched")
    capture(pinch, w, sample("Pinch", pinch=0.15))
    assert 0.17 < w.cfg["pinch_threshold"] < 0.47


def test_wizard_keeps_the_default_when_pinch_readings_overlap(quick_wizard):
    w, _ = quick_wizard
    page = w.page(2)
    page.capture("open")
    capture(page, w, sample(pinch=0.3))
    page.capture("pinched")
    capture(page, w, sample(pinch=0.28))
    assert w.cfg["pinch_threshold"] == config.DEFAULTS["pinch_threshold"] and "too close" in page.note.text()


def test_wizard_says_so_when_no_hand_was_seen(quick_wizard):
    w, _ = quick_wizard
    page = w.page(1)
    page.capture("tl")
    capture(page, w, {})
    assert "couldn't see" in page.note.text() and w.cfg["box"] == config.DEFAULTS["box"]


def test_wizard_gesture_check_needs_a_held_pose(quick_wizard):
    w, _ = quick_wizard
    page = w.page(3)
    page.on_sample(w, sample("Pinch"))
    assert page.labels["Pinch"].text().startswith("○")  # one frame is not enough
    for _ in range(6):
        page.on_sample(w, sample("Pinch"))
    assert page.labels["Pinch"].text().startswith("✓")


def test_wizard_finish_saves_and_turns_tracking_back_on(quick_wizard):
    w, app = quick_wizard
    w.cfg["box"] = [0.25, 0.3, 0.75, 0.85]
    w.done(1)
    assert app.saved[-1]["box"] == [0.25, 0.3, 0.75, 0.85] and app.saved[-1]["wizard_done"] is True
    assert app.applied[-1]["wizard_done"] is True and app.calibrating is False and app.sample_hook is None


def test_wizard_cancel_keeps_settings(quick_wizard):
    w, app = quick_wizard
    w.cfg["box"] = [0.25, 0.3, 0.75, 0.85]
    w.done(0)
    assert app.saved[-1]["box"] == config.DEFAULTS["box"] and app.saved[-1]["wizard_done"] is True
