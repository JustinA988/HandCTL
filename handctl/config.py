"""Settings: defaults, validation, and load/save of %APPDATA%/handctl/config.json."""
import copy
import json
import logging
import os
from pathlib import Path

from pynput.keyboard import HotKey

PATH = Path(os.environ.get("APPDATA", Path.home())) / "handctl" / "config.json"

GESTURES = [
    "Point", "Point_Tap", "Two_Finger", "Two_Finger_Tap", "Three_Finger_Tap", "Closed_Fist",
    "Flick_Left", "Flick_Right", "Thumb_Up", "Pinch", "ILoveYou",
]
ACTION_TYPES = ["none", "mouse", "keys", "slider", "shell"]
MOUSE_VALUES = ["move", "left", "right", "scroll"]

DEFAULTS = {
    "version": 2,  # bump when gesture names change, so old mappings get reset instead of silently doing nothing
    "camera": 0,
    "hand": "Right",  # the tracked hand; in two-hand mode the pointer hand (the other hand does the actions)
    "hand_mode": "single",  # or "two"
    "wizard_done": False,  # the first-run setup wizard opens until this is true
    "mirror": True,
    "toggle_hotkey": "<ctrl>+<alt>+g",
    "shell_enabled": False,
    "autostart": False,
    "cursor_mode": "absolute",  # or "relative": hand movement nudges the cursor like a trackpad
    "relative_speed": 1.5,  # relative mode: screens moved per cursor-area width of hand travel
    "box": [0.2, 0.3, 0.8, 0.9],  # cursor area in the camera frame (left, top, right, bottom); low, so the hand can rest low
    "min_cutoff": 5.0,  # steadiness: lower = less jitter when the hand is still
    "beta": 20.0,  # responsiveness: higher = less lag on fast moves
    "pinch_threshold": 0.3,
    "tap_threshold": 0.2,  # shortcut: untested guess for thumb-on-index distance; tune it once tested on a real camera
    "hold_ms": 150,
    "drag_ms": 300,
    "scroll_speed": 30,
    "mappings": {
        "Point": {"type": "mouse", "value": "move"},
        "Point_Tap": {"type": "mouse", "value": "left"},
        "Two_Finger": {"type": "mouse", "value": "scroll"},
        "Two_Finger_Tap": {"type": "mouse", "value": "right", "cooldown_ms": 500},
        "Three_Finger_Tap": {"type": "keys", "value": "<media_play_pause>", "cooldown_ms": 1000},
        "Closed_Fist": {"type": "none", "value": ""},  # clutch: freezes the cursor
        "Flick_Left": {"type": "keys", "value": "<cmd>+<ctrl>+<left>", "cooldown_ms": 800},  # three-finger swipe
        "Flick_Right": {"type": "keys", "value": "<cmd>+<ctrl>+<right>", "cooldown_ms": 800},
        "Thumb_Up": {"type": "slider", "value": "<media_volume_up>,<media_volume_down>"},
        "Pinch": {"type": "none", "value": ""},  # fallback click if thumb tap proves unreliable
        "ILoveYou": {"type": "none", "value": ""},
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
    if data.get("version") != DEFAULTS["version"]:
        logging.warning("Settings from an older version: gesture mappings reset to the new defaults")
        data.pop("mappings", None)  # old gesture names no longer exist; other settings carry over
        data["version"] = DEFAULTS["version"]
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
    if cfg["cursor_mode"] not in ("absolute", "relative"):
        errors.append("Cursor mode must be absolute or relative.")
    if cfg["hand_mode"] not in ("single", "two") or cfg["hand"] not in ("Right", "Left"):
        errors.append("Hand mode must be single or two, and the hand Right or Left.")
    combos = [("Toggle hotkey", cfg["toggle_hotkey"])]
    for name, m in cfg["mappings"].items():
        if m["type"] == "keys":
            combos.append((name, m["value"]))
        elif m["type"] == "slider":
            parts = m["value"].split(",")
            if len(parts) != 2:
                errors.append(f"{name}: slider needs two key combos separated by a comma (up,down).")
            else:
                combos += [(name, p.strip()) for p in parts]
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
