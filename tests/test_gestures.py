import copy
import json
import math
import random

import pytest

from handctl import config
from handctl.gestures import FINGERS, Classifier, Engine, OneEuro, anchor, assign, features


def cfg(**overrides):
    c = copy.deepcopy(config.DEFAULTS)
    c.update(overrides)
    return c


def world(curl="", thumb="out"):
    """Synthetic 3D hand, size 10. curl: fully curled fingers ('i', 'm', 'r', 'p').
    thumb: 'out', 'index' / 'middle' (touching that fingertip) or 'near' (0.4 hand sizes from the index tip)."""
    pts = [(0.0, 0.0, 0.0)] * 21
    pts[0] = (0.0, -10.0, 0.0)
    for name, x, (m, p, d, t) in zip("imrp", (-2.5, 0.0, 2.5, 5.0), FINGERS):
        pts[m], pts[p] = (x, 0.0, 0.0), (x, 4.0, 0.0)
        pts[d], pts[t] = ((x, 4.0, -2.5), (x, 2.0, -2.5)) if name in curl else ((x, 6.5, 0.0), (x, 8.5, 0.0))
    ix, iy, iz = pts[8]
    mx, my, mz = pts[12]
    pts[4] = {"out": (-9.0, -2.0, 0.0), "index": (ix - 1, iy, iz - 1), "middle": (mx + 1, my, mz - 1), "near": (ix - 4, iy, iz)}[thumb]
    return pts


def turned(pts, yaw=0.9, pitch=0.6):
    """The same hand turned well away from the camera."""
    out = []
    for x, y, z in pts:
        x, z = x * math.cos(yaw) + z * math.sin(yaw), -x * math.sin(yaw) + z * math.cos(yaw)
        y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
        out.append((x, y, z))
    return out


def pose(c, canned="None", score=0.9, **hand):
    return c(canned, score, world(**hand))[0]


def run(engine, frames):
    """frames: list of (t, gesture, pos). Returns all events."""
    out = []
    for t, g, p in frames:
        out += engine.update(t, g, p)
    return out


def hold(gesture, start, end, pos=(0.5, 0.5), step=0.033):
    n = int(round((end - start) / step))
    return [(start + i * step, gesture, pos if gesture else None) for i in range(n)]


def kinds(events):
    return [e[0] for e in events]


# --- shape features and pose naming --------------------------------------------------------------------------------

def test_features_do_not_change_when_the_hand_is_turned():
    for hand in (world(), world(thumb="index"), world("imrp"), world("mrp", "index")):
        flat, rotated = features(hand), features(turned(hand))
        assert rotated["pinch"] == pytest.approx(flat["pinch"]) and rotated["ext"] == pytest.approx(flat["ext"])


def test_anchor_is_the_palm_centre_and_ignores_fingers():
    lm = [(0.5, 0.5)] * 21
    moved = list(lm)
    for tip in (4, 8, 12, 16, 20):
        moved[tip] = (0.9, 0.1)  # fingers pinching or curling don't move the cursor anchor
    assert anchor(lm) == anchor(moved) == pytest.approx((0.5, 0.5))


def test_poses():
    c = lambda: Classifier(cfg())
    for neutral in ("None", "Open_Palm", "Pointing_Up"):
        assert pose(c(), neutral) == "Hand"  # any unremarkable hand moves the cursor
    assert pose(c(), thumb="index") == "Pinch"
    assert pose(c(), thumb="middle") == "Pinch_Middle"
    assert pose(c(), curl="imrp") == "Closed_Fist"
    assert pose(c(), curl="mrp", thumb="index") == "Pinch"  # pinch with the other fingers curled is still a pinch...
    assert pose(c(), "Closed_Fist", curl="mrp", thumb="index") == "Pinch"  # ...even if MediaPipe calls it a fist
    assert pose(c(), curl="imrp", thumb="index") == "Closed_Fist"  # thumb resting on a curled index is a fist, not a click
    for trained in ("Thumb_Up", "Thumb_Down", "Victory", "ILoveYou"):
        assert pose(c(), trained, 0.9) == trained
    assert pose(c(), "Victory", 0.4) == "Hand"  # a half-formed pose doesn't fire
    assert pose(c(), "Thumb_Up", 0.4, curl="imrp") == "Closed_Fist"


def test_pinch_does_not_flicker_near_the_threshold():
    c = Classifier(cfg())
    assert pose(c, thumb="near") == "Hand"  # 0.4 hand sizes apart: not close enough to start a pinch
    assert pose(c, thumb="index") == "Pinch"
    assert pose(c, thumb="near") == "Pinch"  # ...but not far enough to end one
    assert pose(c, "Thumb_Up", 0.9, thumb="near") == "Pinch"  # a held pinch (a drag) isn't interrupted by a misread pose
    assert pose(c, thumb="out") == "Hand"


# --- engine ---------------------------------------------------------------------------------------------------------

def test_any_hand_moves_the_cursor_inside_the_box():
    e = Engine(cfg())
    assert "move" in kinds(run(e, hold("Hand", 0, 0.3)))
    run(e, hold("Hand", 0.3, 1.3, (0.2, 0.2)))
    assert e.pos == pytest.approx((0.0, 0.0), abs=1e-3)
    run(e, hold("Hand", 1.3, 2.3, (0.95, 0.95)))
    assert e.pos == pytest.approx((1.0, 1.0), abs=1e-3)  # clamped outside the box


def test_pinch_clicks_fast_and_the_cursor_holds_still():
    e = Engine(cfg())
    run(e, hold("Hand", 0, 0.5))
    events = run(e, hold("Pinch", 0.5, 0.7))
    assert kinds(events) == ["move", "press"]  # one aiming move, then the press, within 200 ms; no drift while pinched
    assert kinds(run(e, hold("Hand", 0.7, 0.9)))[0] == "release"


def test_click_lands_where_the_cursor_was_before_the_fingers_closed():
    e = Engine(cfg())
    drift = [(i * 0.033, "Hand", (0.4 + i * 0.004, 0.5)) for i in range(20)]  # hand creeping right as the fingers close
    run(e, drift)
    events = run(e, hold("Pinch", 0.66, 0.8, (0.48, 0.5)))
    aim = next(ev for ev in events if ev[0] == "move")
    assert aim[1] < e.pos[0]  # aimed back at the earlier position, not where the hand ended up


def test_held_pinch_drags_and_survives_a_tracking_dropout():
    e = Engine(cfg())
    run(e, hold("Hand", 0, 0.3))
    assert "press" in kinds(run(e, hold("Pinch", 0.3, 0.5)))
    assert "move" in kinds(run(e, hold("Pinch", 0.5, 1.0, (0.6, 0.6))))  # past drag_ms the cursor follows again
    assert run(e, hold(None, 1.0, 1.2)) == []  # hand lost for 200 ms: the drag is not dropped
    assert "release" not in kinds(run(e, hold("Pinch", 1.2, 1.4, (0.6, 0.6))))
    assert kinds(run(e, hold(None, 1.4, 2.0))) == ["release"]  # really gone: let go of the button


def test_pose_must_be_held_before_it_fires_and_respects_cooldown():
    e = Engine(cfg())
    assert run(e, hold("Victory", 0, 0.2)) == []
    events = run(e, hold("Victory", 0.2, 0.5))
    assert [ev[1]["value"] for ev in events] == ["<media_play_pause>"]
    again = run(e, hold("Hand", 0.5, 0.7) + hold("Victory", 0.7, 1.3))
    assert "run" not in kinds(again)  # held long enough, but still inside the 1500 ms cooldown
    later = run(e, hold("Hand", 1.3, 2.2) + hold("Victory", 2.2, 2.7))
    assert kinds(later).count("run") == 1  # fires again once the cooldown has passed


def test_fist_scrolls_and_does_not_move_the_cursor():
    e = Engine(cfg())
    run(e, hold("Hand", 0, 0.3))
    events = run(e, [(0.3 + i * 0.033, "Closed_Fist", (0.5, 0.8 - i * 0.01)) for i in range(40)])
    assert sum(ev[1] for ev in events if ev[0] == "scroll") > 0 and "move" not in kinds(events)  # hand up = scroll up


def test_thumbs_repeat_volume_while_held():
    e = Engine(cfg())
    events = run(e, hold("Thumb_Up", 0, 1.3))
    assert {ev[1]["value"] for ev in events} == {"<media_volume_up>"} and 4 <= len(events) <= 8


def test_cursor_freezes_while_the_hand_changes_shape():
    e = Engine(cfg())
    run(e, hold("Hand", 0, 0.5))
    assert run(e, [(0.5, "Closed_Fist", (0.7, 0.7))]) == []  # closing into a fist doesn't drag the cursor along


def test_two_hand_roles():
    pointer, action = Engine(cfg(), "pointer"), Engine(cfg(), "action")
    events = run(pointer, hold("Pinch", 0, 0.5) + hold("Thumb_Up", 0.5, 1.2) + hold("Closed_Fist", 1.2, 1.8))
    assert set(kinds(events)) == {"move"}  # the pointer hand only ever moves the cursor
    assert kinds(run(action, hold("Hand", 0, 0.3) + hold("Pinch", 0.3, 1.0))) == ["press"]  # clicks, never moves
    assert kinds(run(action, hold("Hand", 1.0, 1.2))) == ["release"]
    events = run(action, [(1.2 + i * 0.033, "Closed_Fist", (0.5, 0.8 - i * 0.01)) for i in range(40)])
    assert "scroll" in kinds(events) and "move" not in kinds(events)


def test_assign_hands_by_position():
    left, right = ("Left", (0.3, 0.5)), ("Right", (0.7, 0.5))
    assert assign([right, left], {}, 0) == {"Left": 1, "Right": 0}
    assert assign([("Right", (0.3, 0.5)), ("Right", (0.7, 0.5))], {}, 0) == {"Left": 0, "Right": 1}  # wrong labels ignored
    assert assign([left, right], {}, 0, mirror=False) == {"Left": 1, "Right": 0}  # unmirrored image: sides swap
    assert assign([left], {}, 0) == {"Left": 0}  # nothing to go on but the label
    seen = {"Right": (1.0, (0.7, 0.5))}
    assert assign([("Left", (0.68, 0.52))], seen, 1.1) == {"Right": 0}  # label flipped, but it's the hand that was just there
    assert assign([("Left", (0.2, 0.5))], seen, 1.1) == {"Left": 0}  # far from the right hand: the other hand
    assert assign([("Left", (0.68, 0.52))], seen, 5.0) == {"Left": 0}  # stale history is ignored
    assert assign([], seen, 1.1) == {}


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


# --- settings file --------------------------------------------------------------------------------------------------

def test_defaults_are_valid_and_bad_values_rejected():
    assert config.validate(cfg()) == []
    assert set(config.DEFAULTS["mappings"]) == set(config.GESTURES)
    c = cfg(hand_mode="three")
    c["box"] = [0.5, 0, 0.5, 1]
    c["mappings"]["Victory"]["value"] = "<notakey>"
    c["mappings"]["Hand"]["value"] = "triple"
    assert len(config.validate(c)) == 4


def test_load_backs_up_broken_file_and_ignores_wrong_types(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{broken")
    assert config.load(p) == config.DEFAULTS
    assert (tmp_path / "config.json.bak").read_text() == "{broken"
    p.write_text(json.dumps({"version": 3, "camera": "zero", "beta": 2, "unknown": 5}))
    loaded = config.load(p)
    assert loaded["camera"] == 0 and loaded["beta"] == 2 and "unknown" not in loaded
    p.write_text(json.dumps({"version": 3, "box": [1, 2], "mappings": {"Pinch": {"type": "keys"}, "Thumb_Up": "x"}}))
    assert config.load(p) == config.DEFAULTS  # malformed values fall back instead of crashing tracking


def test_older_settings_keep_camera_but_get_new_gesture_mappings(tmp_path):
    p = tmp_path / "config.json"
    old = {"version": 2, "camera": 1, "min_cutoff": 0.5, "cursor_mode": "relative", "wizard_done": True,
           "mappings": {"Point_Tap": {"type": "mouse", "value": "left"}}}
    p.write_text(json.dumps(old))
    loaded = config.load(p)
    assert loaded["camera"] == 1 and loaded["min_cutoff"] == 0.5 and "cursor_mode" not in loaded
    assert loaded["mappings"] == config.DEFAULTS["mappings"] and loaded["version"] == 3
    assert loaded["wizard_done"] is False  # the wizard is offered again, because it now calibrates pinch
