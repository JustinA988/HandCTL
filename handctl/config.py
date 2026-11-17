"""Settings: defaults, validation, and load/save of %APPDATA%/handctl/config.json."""
import copy
import json
import logging
import os
from pathlib import Path

from pynput.keyboard import HotKey

PATH = Path(os.environ.get("APPDATA", Path.home())) / "handctl" / "config.json"

GESTURES = [
    "Pointing_Up", "Pinch", "Pinch_Middle", "Victory", "Closed_Fist",
    "Thumb_Up", "Thumb_Down", "ILoveYou", "Swipe_Left", "Swipe_Right",
]
ACTION_TYPES = ["none", "mouse", "keys", "shell"]
MOUSE_VALUES = ["move", "left", "right", "scroll"]

DEFAULTS = {
    "camera": 0,
    "hand": "Right",
    "mirror": True,
    "toggle_hotkey": "<ctrl>+<alt>+g",
    "shell_enabled": False,
    "autostart": False,
    "box": [0.2, 0.15, 0.8, 0.75],  # cursor area in the camera frame: left, top, right, bottom (0-1)
    "min_cutoff": 5.0,  # steadiness: lower = less jitter when the hand is still
    "beta": 20.0,  # responsiveness: higher = less lag on fast moves
    "pinch_threshold": 0.3,
    "hold_ms": 150,
    "drag_ms": 300,
    "scroll_speed": 30,
    "mappings": {
        "Pointing_Up": {"type": "mouse", "value": "move"},
        "Pinch": {"type": "mouse", "value": "left"},
        "Pinch_Middle": {"type": "mouse", "value": "right", "cooldown_ms": 500},
        "Victory": {"type": "mouse", "value": "scroll"},
        "Closed_Fist": {"type": "keys", "value": "<media_play_pause>", "cooldown_ms": 1000},
        "Thumb_Up": {"type": "keys", "value": "<media_volume_up>", "cooldown_ms": 150, "repeat": True},
        "Thumb_Down": {"type": "keys", "value": "<media_volume_down>", "cooldown_ms": 150, "repeat": True},
        "ILoveYou": {"type": "keys", "value": "<cmd>+<tab>", "cooldown_ms": 1500},
        "Swipe_Left": {"type": "keys", "value": "<cmd>+<ctrl>+<left>", "cooldown_ms": 800},
        "Swipe_Right": {"type": "keys", "value": "<cmd>+<ctrl>+<right>", "cooldown_ms": 800},
    },
}


def load(path=PATH):
    cfg = copy.deepcopy(DEFAULTS)
    if not path.exists():
        return cfg
    try:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level is not an object")
    except (OSError, ValueError) as e:
        backup = path.with_suffix(".json.bak")
        logging.warning("Unreadable config (%s); moved it to %s and using defaults", e, backup)
        path.replace(backup)
        return cfg
    for key, value in data.items():
        default = DEFAULTS.get(key)
        if type(value) is type(default) or (type(default) is float and type(value) is int):
            cfg[key] = value
    cfg["mappings"] = {
        name: m for name, m in cfg["mappings"].items()
        if isinstance(m, dict) and m.get("type") in ACTION_TYPES and isinstance(m.get("value"), str)
        and isinstance(m.get("cooldown_ms", 0), (int, float))
    }
    try:
        errors = validate(cfg)
    except (ValueError, TypeError) as e:  # e.g. a box that isn't 4 numbers
        errors = [str(e)]
    if errors:
        logging.warning("Invalid settings in %s (%s); using defaults", path, "; ".join(errors))
        return copy.deepcopy(DEFAULTS)
    return cfg


def save(cfg, path=PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), "utf-8")
    tmp.replace(path)  # atomic, so a crash mid-write can't leave a half-written config


def validate(cfg):
    """Returns a list of human-readable problems; empty means OK."""
    errors = []
    x0, y0, x1, y1 = cfg["box"]
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        errors.append("Cursor area: left/top must be smaller than right/bottom, all between 0 and 1.")
    combos = [("Toggle hotkey", cfg["toggle_hotkey"])]
    for name, m in cfg["mappings"].items():
        if m["type"] == "keys":
            combos.append((name, m["value"]))
        elif m["type"] == "mouse" and m["value"] not in MOUSE_VALUES:
            errors.append(f"{name}: mouse action must be one of {', '.join(MOUSE_VALUES)}.")
        elif m["type"] == "shell" and not m["value"].strip():
            errors.append(f"{name}: shell command is empty.")
    for label, combo in combos:
        try:
            HotKey.parse(combo)
        except ValueError:
            errors.append(f"{label}: '{combo}' is not a valid key combo (example: <ctrl>+<alt>+g).")
    return errors
