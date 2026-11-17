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
    s.fields["hand_mode"].setCurrentText("two")
    s.fields["hand"].setCurrentText("Left")
    cfg = s.read()
    assert (cfg["hand_mode"], cfg["hand"]) == ("two", "Left") and config.validate(cfg) == []


def test_save_applies_and_persists(fake_app, monkeypatch):
    import handctl.__main__ as main
    monkeypatch.setattr(main, "set_autostart", lambda on: None)  # never touch the real registry in tests
    s = main.Settings(fake_app)
    s.fields["beta"].setValue(3.5)
    s.save()
    assert fake_app.saved[-1]["beta"] == 3.5 and fake_app.applied[-1]["beta"] == 3.5
