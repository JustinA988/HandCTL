import contextlib

from pynput.keyboard import Key
from pynput.mouse import Button

from handctl import actions, gaze


def test_zoom_sideways_scroll_and_middle_click_reach_the_mouse(monkeypatch):
    log = []

    class Mouse:
        def scroll(self, dx, dy):
            log.append(("scroll", dx, dy))

        def click(self, button):
            log.append(("click", button))

    class Keyboard:
        @contextlib.contextmanager
        def pressed(self, key):
            log.append(("down", key))
            yield
            log.append(("up", key))

    monkeypatch.setattr(actions, "mouse", Mouse())
    monkeypatch.setattr(actions, "keyboard", Keyboard())
    actions.execute(("zoom", 2), {})
    assert log == [("down", Key.ctrl), ("scroll", 0, 2), ("up", Key.ctrl)]  # Ctrl held around the wheel, then released
    log.clear()
    actions.execute(("hscroll", 3), {})
    assert log == [("scroll", 3, 0)]
    log.clear()
    actions.execute(("run", {"type": "mouse", "value": "middle"}), {})
    actions.execute(("run", {"type": "mouse", "value": "right"}), {})
    assert log == [("click", Button.middle), ("click", Button.right)]


def blob(cx, cy, width, height=None):
    """21 landmarks spread over a box centred on (cx, cy)."""
    height = height or width
    return [(cx - width / 2 + width * (i % 4) / 3, cy - height / 2 + height * (i // 4) / 5) for i in range(21)]


def test_face_part_rule_on_sizes_measured_from_a_real_camera():
    """Measured on one user, as a share of the face's width: phantom hands 0.27-0.42, their fists 0.51-0.65, open hands 1.1-1.3.
    Phantoms sat on the cheek and on the hairline above it."""
    face = (0.30, 0.20, 0.50, 0.55)  # 0.2 of the frame wide, about as measured
    assert gaze.face_part(blob(0.42, 0.37, 0.07), [face])  # a phantom on the cheek (0.35x the face)
    assert gaze.face_part(blob(0.46, 0.15, 0.07), [face])  # a phantom up on the hairline, outside the face box
    assert not gaze.face_part(blob(0.42, 0.37, 0.11), [face])  # a fist held in front of the face (0.55x) stays
    assert not gaze.face_part(blob(0.40, 0.45, 0.24, 0.30), [face])  # an open hand in front of the face stays
    assert not gaze.face_part(blob(0.95, 0.37, 0.07), [face])  # the same small blob far from the face stays
    assert not gaze.face_part(blob(0.42, 0.37, 0.07), [])  # no face seen: nothing to compare with
    assert gaze.face_part(blob(0.42, 0.37, 0.07), [(0.0, 0.0, 0.1, 0.1), face])  # any of several faces counts
