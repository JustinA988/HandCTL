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


def frame(t, now, *hands):
    """One camera frame through the tracker: read the hands, then step the engines (mouse output is stubbed)."""
    t._step(now, t._read(fake_result(*hands), now))


def right(**shape):  # the right hand, on the right of the (mirrored) picture
    return "Right", "None", 0.7, world(**shape)


def left(**shape):
    return "Left", "None", 0.3, world(**shape)


def frames(t, start, seconds, *hands, step=0.033):
    """Feed the same hands for a while; returns the time it ended at."""
    for i in range(round(seconds / step)):
        frame(t, start + i * step, *hands)
    return start + seconds


@pytest.fixture
def quiet(monkeypatch):
    from handctl import actions
    events = []
    monkeypatch.setattr(actions, "execute", lambda event, cfg: events.append(event))
    return events


def combos(events):
    return [e[1]["value"] for e in events if e[0] == "run"]


def test_the_other_hand_picks_a_mode_and_the_main_hand_acts_in_it(qapp, quiet):
    t = Tracker(cfg(hand="Right"))
    now = frames(t, 0.0, 0.4, right(), left())  # both hands open: no mode
    assert t.mode is None
    now = frames(t, now, 0.4, right(), left(curl="imrp"))  # the other hand makes a fist: Edit mode
    assert t.mode == "Edit"
    quiet.clear()
    now = frames(t, now, 0.4, right(thumb="index"), left(curl="imrp"))  # a pinch now copies instead of clicking
    assert combos(quiet) == ["<ctrl>+c"] and "press" not in [e[0] for e in quiet]
    quiet.clear()
    now = frames(t, now, 0.4, right(thumb="ring"), left(curl="imrp"))  # ring finger pinch: find (a bonus slot)
    assert combos(quiet) == ["<ctrl>+f"]
    quiet.clear()
    now = frames(t, now, 0.4, right(curl="imrp"), left(curl="imrp"))  # fist with the main hand too: paste, not scroll
    assert combos(quiet) == ["<ctrl>+v"] and "scroll" not in [e[0] for e in quiet]
    now = frames(t, now, 0.5, right(), left())  # the other hand lets go: back to normal
    assert t.mode is None
    quiet.clear()
    frames(t, now, 0.4, right(thumb="index"), left())
    assert "press" in [e[0] for e in quiet] and combos(quiet) == []  # a plain click again


def test_each_mode_pose_selects_its_mode(qapp, quiet):
    t = Tracker(cfg(hand="Right"))
    # poses that MediaPipe names (thumbs, peace sign, I-love-you) arrive as its own gesture label
    named = {"Media": "Thumb_Up", "Windows": "Victory", "Browser": "ILoveYou", "System": "Thumb_Down"}
    now = 0.0
    for mode, canned in named.items():
        for i in range(12):
            t._step(now, t._read(fake_result(right(), ("Left", canned, 0.3, world())), now))
            now += 0.033
        assert t.mode == mode, (mode, t.mode)
        now = frames(t, now, 0.5, right(), left())  # let go between modes
        assert t.mode is None  # (Edit's fist pose is exercised in the test above)


def test_a_single_hand_in_view_only_has_the_core_gestures(qapp, quiet):
    t = Tracker(cfg(hand="Right"))
    now = frames(t, 0.0, 0.3, right())
    frames(t, now, 0.4, right(thumb="index"))
    assert t.mode is None and "press" in [e[0] for e in quiet]  # click, as always
    t2 = Tracker(cfg(hand="Right"))
    frames(t2, 0.0, 0.6, left(curl="imrp"))  # the left hand alone making a fist is just a fist (scroll), not a mode
    assert t2.mode is None


def test_a_drag_is_not_cut_off_when_the_second_hand_appears(qapp, quiet):
    t = Tracker(cfg(hand="Right"))
    now = frames(t, 0.0, 0.4, right(thumb="index"))
    assert t.engines["Right"].down and "press" in [e[0] for e in quiet]
    now = frames(t, now, 0.4, right(thumb="index"), left())  # the other hand joins: the drag goes on
    assert t.engines["Right"].down and "release" not in [e[0] for e in quiet]
    now = frames(t, now, 0.4, right(thumb="index"), left(curl="imrp"))  # even a mode starting doesn't change the drag
    assert t.mode == "Edit" and combos(quiet) == [] and t.engines["Right"].down
    frames(t, now, 0.4, right(), left(curl="imrp"))  # fingers part: the click ends
    assert "release" in [e[0] for e in quiet]


def test_a_hand_that_becomes_the_mode_hand_lets_go_of_a_drag(qapp, quiet):
    t = Tracker(cfg(hand="Right"))
    now = frames(t, 0.0, 0.5, left(thumb="index"))  # only the left hand is in view, and it is dragging
    assert t.engines["Left"].down
    quiet.clear()
    frames(t, now, 0.2, right(), left(thumb="index"))  # the right hand arrives: the left hand now only picks modes
    assert ("release",) in quiet and not t.engines["Left"].down


def test_action_only_mode_through_the_tracker(qapp, quiet):
    t = Tracker(cfg(control_mode="actions", hand="Right"))
    now = frames(t, 0.0, 0.3, right())  # an open hand, moving or not, does nothing
    assert quiet == []
    now = frames(t, now, 0.5, right(thumb="index"))  # a pinch held long enough, then let go: a screenshot, not a click
    now = frames(t, now, 0.4, right())
    assert combos(quiet) == ["<cmd>+<shift>+s"] and not {"press", "move", "scroll"} & {e[0] for e in quiet}
    quiet.clear()
    now = frames(t, now, 0.4, right(), left())
    now = frames(t, now, 0.5, right(thumb="index"), left(curl="imrp"))  # the other hand's fist: Edit mode, so a pinch copies
    now = frames(t, now, 0.4, right(), left(curl="imrp"))
    assert t.mode == "Edit" and combos(quiet) == ["<ctrl>+c"] and not {"press", "move"} & {e[0] for e in quiet}


def test_modes_reset_when_tracking_is_paused(qapp, quiet):
    t = Tracker(cfg(hand="Right"))
    frames(t, 0.0, 0.5, right(), left(curl="imrp"))
    assert t.mode == "Edit"
    t.enabled = False
    frame(t, 1.0, right(), left(curl="imrp"))
    assert t.mode is None


# --- phantom hands on the face --------------------------------------------------------------------------------------

def wide_hand(x0, x1, y=0.5):
    """A MediaPipe-style hand result whose landmarks spread from x0 to x1."""
    ns = types.SimpleNamespace
    xs = [x0 + (x1 - x0) * i / 20 for i in range(21)]
    w = world()
    return ns(hand_landmarks=[[ns(x=x, y=y) for x in xs]], hand_world_landmarks=[[ns(x=p[0], y=p[1], z=p[2]) for p in w]],
              handedness=[[ns(category_name="Right")]], gestures=[[ns(category_name="None", score=0.9)]])


def test_phantom_hands_on_the_face_are_dropped_but_real_hands_are_kept(qapp):
    t = Tracker(cfg(hand_mode="one"))
    t.faces = (0.0, [(0.3, 0.3, 0.5, 0.7)])  # a face, as seen a moment ago
    assert t._read(fake_result(right()[:2] + (0.4, world())), 0.5) == {} and t.found == 0  # a tiny "hand" on the face
    assert list(t._read(fake_result(right()[:2] + (0.9, world())), 0.5)) == [ANY] and t.found == 1  # the same hand elsewhere
    assert list(t._read(wide_hand(0.2, 0.55), 0.5)) == [ANY]  # a real hand held in front of the face is as wide as it
    assert t._read(wide_hand(0.4, 0.45), 0.5) == {} and t.found == 0  # a tiny one is not
    assert list(t._read(wide_hand(0.4, 0.45), 2.0)) == [ANY]  # unless the face wasn't seen for over a second


def test_a_hand_cut_off_by_the_picture_edge_is_ignored(qapp):
    t = Tracker(cfg(hand_mode="one"))
    ns = types.SimpleNamespace
    points = [ns(x=0.5 + 0.01 * i, y=1.0 + 0.01 * i) for i in range(21)]  # most of it below the bottom edge
    cut = ns(hand_landmarks=[points], hand_world_landmarks=[[ns(x=p[0], y=p[1], z=p[2]) for p in world()]],
             handedness=[[ns(category_name="Right")]], gestures=[[ns(category_name="None", score=0.9)]])
    assert t._read(cut, 0.0) == {} and t.found == 0
    assert list(t._read(fake_result(right()), 0.0)) == [ANY]
    assert list(t._read(fake_result(right()[:2] + (0.4, world())), 2.0)) == [ANY]  # the face wasn't seen for over a second


def test_phantoms_do_not_keep_the_slow_two_hand_recognizer_on(qapp):
    t = Tracker(cfg())
    t.faces = (0.0, [(0.3, 0.3, 0.5, 0.7)])
    t._read(fake_result(("Right", "None", 0.4, world()), ("Left", "None", 0.8, world())), 0.5)  # one phantom, one real hand
    assert t.found == 1  # HandCount sees one hand, so tracking stays on the cheap recognizer


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
