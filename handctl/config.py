"""Settings: defaults, validation, and load/save of %APPDATA%/handctl/config.json."""
import copy
import json
import logging
import os
from pathlib import Path

from pynput.keyboard import HotKey

PATH = Path(os.environ.get("APPDATA", Path.home())) / "handctl" / "config.json"

GESTURES = ["Hand", "Pinch", "Pinch_Middle", "Closed_Fist", "Thumb_Up", "Thumb_Down", "Victory", "ILoveYou"]
ACTION_TYPES = ["none", "mouse", "keys", "shell"]
MOUSE_VALUES = ["move", "left", "right", "scroll"]

DEFAULTS = {
    "version": 3,  # bump when gesture names change, so old mappings get reset instead of silently doing nothing
    "camera": 0,
    "hand": "Right",  # with both hands in view, this one moves the cursor and the other does the actions
    "hand_mode": "auto",  # "auto": one hand in view does everything, two split the work; "one": only ever one hand
    "wizard_done": False,  # the first-run setup wizard opens until this is true
    "mirror": True,
    "toggle_hotkey": "<ctrl>+<alt>+g",
    "shell_enabled": False,
    "autostart": False,
    "box": [0.2, 0.2, 0.8, 0.8],  # cursor area in the camera frame: left, top, right, bottom (0-1)
    "min_cutoff": 1.0,  # steadiness: lower = less jitter when the hand is still (1.0: jitter cut ~2.3x in simulation)
    "beta": 10.0,  # responsiveness: higher = less lag (10: cursor trails the hand ~38 ms on slow moves, ~8 ms on fast ones)
    "pinch_threshold": 0.4,  # thumb-to-fingertip distance in hand sizes; looser than before so a relaxed pinch clicks
    "hold_ms": 100,  # how long a pose (fist, thumbs, peace, I-love-you) must be held before it acts; pinches are faster
    "drag_ms": 300,
    "scroll_speed": 30,
    "monitor_switch": False,  # move the cursor to the monitor the user looks at
    "monitor_gaze": {},  # monitor device name -> [yaw, pitch] of the gaze when looking at it, from the calibration
    "mappings": {
        "Hand": {"type": "mouse", "value": "move"},  # any open or relaxed hand
        "Pinch": {"type": "mouse", "value": "left"},
        "Pinch_Middle": {"type": "mouse", "value": "right", "cooldown_ms": 500},
        "Closed_Fist": {"type": "mouse", "value": "scroll"},  # grab and move up/down
        "Thumb_Up": {"type": "keys", "value": "<media_volume_up>", "cooldown_ms": 150, "repeat": True},
        "Thumb_Down": {"type": "keys", "value": "<media_volume_down>", "cooldown_ms": 150, "repeat": True},
        "Victory": {"type": "keys", "value": "<media_play_pause>", "cooldown_ms": 1500},
        "ILoveYou": {"type": "keys", "value": "<cmd>+<tab>", "cooldown_ms": 1500},
    },
}


def load(path=PATH):
    cfg = copy.deepcopy(DEFAULTS)
    if not path.exists():
        return cfg
    try:
        data = json.loads(path.read_text("utf-8-sig"))  # -sig: Notepad and PowerShell add a byte-order mark; that's not corruption
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
        data.pop("wizard_done", None)  # what the wizard calibrates may have changed, so offer it once more
        data["version"] = DEFAULTS["version"]
    if data.get("hand_mode") in ("single", "two"):
        # older values. "single" was the default, not a choice, and only ever tracked one hand; "auto" now tracks both
        data["hand_mode"] = "auto"
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
    if cfg["hand_mode"] not in ("auto", "one") or cfg["hand"] not in ("Right", "Left"):
        errors.append("Hand mode must be auto or one, and the pointer hand Right or Left.")
    if not all(isinstance(p, list) and len(p) == 2 and all(type(v) in (int, float) for v in p) for p in cfg["monitor_gaze"].values()):
        errors.append("Monitor calibration data is damaged. Run the monitor calibration again.")
    if cfg["monitor_switch"] and len(cfg["monitor_gaze"]) < 2:
        errors.append("Monitor switching needs a calibration first: Settings > Monitors > Calibrate monitors.")
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
