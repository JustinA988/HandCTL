import subprocess
import sys
import time
import types

import pytest

from handctl import config, wizard
from handctl.tracker import ANY, HandCount, Tracker

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


def test_one_hand_mode_follows_whichever_hand_shows_up(qapp):
    for label in ("Left", "Right"):  # MediaPipe's left/right label doesn't matter, so a flipped label can't lose the hand
        t = Tracker(cfg(hand_mode="one"))
        got = t._read(fake_result((label, "None", 0.4, world(thumb="index"))), 0.0)
        assert list(got) == [ANY] and got[ANY]["gesture"] == "Pinch" and got[ANY]["pos"] == pytest.approx((0.4, 0.5))


def test_auto_mode_tracks_both_hands_by_default(qapp):
    t = Tracker(cfg())
    assert config.DEFAULTS["hand_mode"] == "auto" and set(t.engines) == {"Left", "Right"}  # MediaPipe asked for 2 hands
    # both mislabelled "Right": the one on the left of the mirrored image is still the left hand
    got = t._read(fake_result(("Right", "None", 0.7, world()), ("Right", "None", 0.3, world(thumb="index"))), 0.0)
    assert {k: v["gesture"] for k, v in got.items()} == {"Left": "Pinch", "Right": "Hand"}


def roles(t):
    return {side: e.role for side, e in t.engines.items()}


def frame(t, now, *hands):
    """One camera frame through the tracker: read the hands, then step the engines (mouse output is stubbed)."""
    t._step(now, t._read(fake_result(*hands), now))


@pytest.fixture
def quiet(monkeypatch):
    from handctl import actions
    events = []
    monkeypatch.setattr(actions, "execute", lambda event, cfg: events.append(event))
    return events


def test_one_hand_in_view_does_everything_two_hands_split_the_work(qapp, quiet):
    t = Tracker(cfg(hand="Right"))
    right, left = ("Right", "None", 0.7, world()), ("Left", "None", 0.3, world())
    frame(t, 0.0, right)
    assert roles(t)["Right"] == "single"
    frame(t, 0.1, right, left)
    assert roles(t) == {"Right": "pointer", "Left": "action"}
    frame(t, 0.2, right)  # left hand drops out for one frame: a tracking hiccup, roles hold
    assert roles(t) == {"Right": "pointer", "Left": "action"}
    for now in (0.6, 0.7):
        frame(t, now, right)  # left hand really gone: the right hand does everything again
    assert roles(t)["Right"] == "single"
    for now in (1.0, 1.1):
        frame(t, now, left)  # only the left hand: it does everything, clicks included
    assert roles(t)["Left"] == "single"
    swapped = Tracker(cfg(hand="Left"))
    frame(swapped, 0.0, right, left)
    assert roles(swapped) == {"Left": "pointer", "Right": "action"}


def test_a_drag_is_not_cut_off_when_the_second_hand_appears(qapp, quiet):
    t = Tracker(cfg(hand="Right"))
    pinching, open_left = ("Right", "None", 0.7, world(thumb="index")), ("Left", "None", 0.3, world())
    for i in range(10):
        frame(t, i * 0.033, pinching)
    assert t.engines["Right"].down and "press" in [e[0] for e in quiet]
    for i in range(10, 20):
        frame(t, i * 0.033, pinching, open_left)
    assert t.engines["Right"].down and t.engines["Right"].role == "single"  # still dragging; role waits
    assert "release" not in [e[0] for e in quiet]
    for i in range(20, 30):
        frame(t, i * 0.033, ("Right", "None", 0.7, world()), open_left)  # fingers part: drag ends, then roles split
    assert "release" in [e[0] for e in quiet] and roles(t) == {"Right": "pointer", "Left": "action"}


def test_hand_count_uses_the_cheap_recognizer_and_probes_for_a_second_hand():
    c = HandCount()
    assert c.wants_two(0.0)  # the first frame checks for a second hand
    c.saw(0.0, True, 1)
    used = [c.wants_two(0.033 * i) for i in range(1, 8)]
    assert not any(used)  # frames in the next 0.23 s use the one-hand recognizer
    assert c.wants_two(0.26)  # then another check
    c.saw(0.26, True, 1)
    assert not c.two and not c.wants_two(0.30)
    c.saw(0.51, True, 2)  # a second hand arrived: stay on the two-hand recognizer
    assert c.two and c.wants_two(0.54) and c.wants_two(0.9)
    c.saw(0.57, True, 1)  # one frame without the second hand (a tracking hiccup) changes nothing
    assert c.two
    c.saw(1.7, True, 1)  # missing for over a second: back to the cheap recognizer
    assert not c.two and not c.wants_two(1.75) and c.wants_two(1.96)


def test_no_hand_in_view(qapp):
    assert Tracker(cfg())._read(fake_result(), 0.0) == {}
    assert Tracker(cfg(hand_mode="one"))._read(fake_result(), 0.0) == {}


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
    assert wizard.role_hand(hands, cfg(hand="Right"), "pointer") == "R" and wizard.role_hand(hands, cfg(hand="Right"), "action") == "L"
    assert wizard.role_hand({"Left": "L"}, cfg(hand="Right"), "action") == wizard.role_hand({"Left": "L"}, cfg(), "pointer") == "L"
    one = cfg(hand_mode="one")
    assert wizard.role_hand({ANY: "H"}, one, "pointer") == wizard.role_hand({ANY: "H"}, one, "action") == "H"
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
