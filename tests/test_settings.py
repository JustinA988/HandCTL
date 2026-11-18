from handctl import config


def test_slider_values_round_trip(qapp):
    from handctl.__main__ import Slider
    s = Slider(0.1, 5, 0.1, 1)
    s.setValue(0.5)
    assert s.value() == 0.5 and s.text.text() == "0.5"
    s = Slider(0, 1000, 10, 0)
    s.setValue(150)
    assert s.value() == 150 and isinstance(s.value(), int)  # whole-number settings stay ints, as config.load expects


def test_settings_window_round_trips_defaults_and_two_hand_mode(fake_app):
    from handctl.__main__ import Settings
    s = Settings(fake_app)
    cfg = s.read()
    assert config.validate(cfg) == []
    for key, value in config.DEFAULTS.items():
        if key != "mappings":
            assert cfg[key] == value, key
    for name, m in config.DEFAULTS["mappings"].items():
        got = cfg["mappings"][name]
        assert (got["type"], got["value"]) == (m["type"], m["value"]), name
    s.fields["hand_mode"].setCurrentText("one")
    s.fields["hand"].setCurrentText("Left")
    cfg = s.read()
    assert (cfg["hand_mode"], cfg["hand"]) == ("one", "Left") and config.validate(cfg) == []


def test_every_gesture_has_a_row_and_mode_poses_can_be_changed(fake_app):
    from handctl.__main__ import Settings
    s = Settings(fake_app)
    assert [row[0] for row in s.rows] == config.GESTURES + config.ACTION_GESTURES  # a table set for each control mode
    s.mode_poses["Edit"].setCurrentText("ILoveYou")
    s.mode_poses["Browser"].setCurrentText("Closed_Fist")
    cfg = s.read()
    assert cfg["modes"]["Edit"] == "ILoveYou" and cfg["modes"]["Browser"] == "Closed_Fist" and config.validate(cfg) == []
    s.mode_poses["Media"].setCurrentText("ILoveYou")  # now two modes want the same pose
    assert any("same pose" in e for e in config.validate(s.read()))
    row = next(r for r in s.rows if r[0] == "Edit/Pinch")  # the table shows what the mode does, and edits flow back
    assert row[1].currentText() == "keys" and row[2].text() == "<ctrl>+c"
    row[2].setText("<ctrl>+<shift>+c")
    assert s.read()["mappings"]["Edit/Pinch"]["value"] == "<ctrl>+<shift>+c"


def test_control_mode_switch_and_the_two_gesture_sets(fake_app):
    from handctl.__main__ import Settings
    s = Settings(fake_app)
    assert s.set_picker.currentIndex() == 0 and not s.sets[0].isHidden() and s.sets[1].isHidden()  # cursor gestures shown
    s.set_picker.setCurrentIndex(1)
    assert s.sets[0].isHidden() and not s.sets[1].isHidden()
    s.fields["control_mode"].setCurrentText("actions")
    row = next(r for r in s.rows if r[0] == "A:Pinch")  # the action-only set is editable and independent of the cursor set
    assert row[1].currentText() == "keys" and row[2].text() == "<cmd>+<shift>+s"
    row[2].setText("<ctrl>+<shift>+s")
    cfg = s.read()
    assert cfg["control_mode"] == "actions" and cfg["mappings"]["A:Pinch"]["value"] == "<ctrl>+<shift>+s"
    assert cfg["mappings"]["Pinch"]["value"] == "left" and config.validate(cfg) == []
    s.load({**fake_app.cfg, "control_mode": "actions"})  # loading settings that use action-only mode shows that set
    assert s.set_picker.currentIndex() == 1


def test_picking_a_control_mode_applies_at_once(fake_app):
    from handctl.__main__ import Settings
    picked = []
    fake_app.set_control_mode = picked.append
    s = Settings(fake_app)
    assert picked == []  # filling the window doesn't count as picking
    s.fields["control_mode"].activated.emit(1)  # what a user's pick in the dropdown sends
    s.fields["control_mode"].setCurrentText("actions")
    s.fields["control_mode"].activated.emit(1)
    assert picked[-1] == "actions"


def test_closing_with_unsaved_changes_asks_first(fake_app, monkeypatch):
    import handctl.__main__ as main
    from PySide6.QtGui import QCloseEvent
    s = main.Settings(fake_app)
    assert s.edits() == s.unchanged
    s.fields["control_mode"].setCurrentText("actions")
    assert s.edits() == s.unchanged  # control mode applies at once, so it isn't an unsaved change
    s.fields["beta"].setValue(3.5)
    monkeypatch.setattr(main.QMessageBox, "question", lambda *a: main.QMessageBox.StandardButton.Cancel)
    event = QCloseEvent()
    s.closeEvent(event)
    assert not event.isAccepted() and fake_app.saved == []  # Cancel: stays open, nothing saved
    monkeypatch.setattr(main, "set_autostart", lambda on: None)
    monkeypatch.setattr(main.QMessageBox, "question", lambda *a: main.QMessageBox.StandardButton.Save)
    monkeypatch.setattr(main.QApplication, "instance", lambda: type("Q", (), {"quit": lambda self: None})())
    event = QCloseEvent()
    s.closeEvent(event)
    assert event.isAccepted() and fake_app.saved[-1]["beta"] == 3.5 and s.edits() == s.unchanged


def test_save_applies_and_persists(fake_app, monkeypatch):
    import handctl.__main__ as main
    monkeypatch.setattr(main, "set_autostart", lambda on: None)  # never touch the real registry in tests
    s = main.Settings(fake_app)
    s.fields["beta"].setValue(3.5)
    s.save()
    assert fake_app.saved[-1]["beta"] == 3.5 and fake_app.applied[-1]["beta"] == 3.5
