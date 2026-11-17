import copy
import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no real windows during tests

import pytest

from handctl import config  # noqa: E402  (imported before PySide6 on purpose; see handctl/__init__.py)
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fake_app(qapp, monkeypatch):
    """Stands in for handctl.__main__.App: no camera, no tray, and config.save never touches the real settings file."""
    import handctl.__main__ as main
    monkeypatch.setattr(main, "list_cameras", lambda: [0])
    saved, applied = [], []
    monkeypatch.setattr(config, "save", lambda cfg, *a: saved.append(copy.deepcopy(cfg)))
    return types.SimpleNamespace(
        cfg=copy.deepcopy(config.DEFAULTS), saved=saved, applied=applied, calibrating=False, force_face=False,
        tracker=types.SimpleNamespace(preview=False, enabled=True), sample_hook=None, frame_hook=None, look_hook=None,
        toggle_action=types.SimpleNamespace(setChecked=lambda v: None),
        apply=lambda cfg: applied.append(cfg), stop=lambda: None)
