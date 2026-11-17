"""Settings: defaults, validation, and load/save of %APPDATA%/handctl/config.json."""
import copy
import json
import logging
import os
from pathlib import Path

from pynput.keyboard import HotKey

PATH = Path(os.environ.get("APPDATA", Path.home())) / "handctl" / "config.json"

POSE_NAMES = ["Hand", "Pinch", "Pinch_Middle", "Pinch_Ring", "Pinch_Pinky", "Closed_Fist", "Thumb_Up", "Thumb_Down", "Victory", "ILoveYou"]
MODE_POSES = ["Closed_Fist", "Thumb_Up", "Thumb_Down", "Victory", "ILoveYou"]  # poses the other hand can hold to pick a mode
MODES = ["Edit", "Media", "Windows", "Browser", "System"]
SLOTS = [p for p in POSE_NAMES if p != "Hand"]  # what the main hand can do inside a mode
# every mapping name: a plain pose is a "core" action that works whenever no mode overrides it; "Mode/Pose" is a mode's version
GESTURES = POSE_NAMES + [f"{mode}/{pose}" for mode in MODES for pose in SLOTS]
ACTION_TYPES = ["none", "mouse", "keys", "shell"]
MOUSE_VALUES = ["move", "left", "right", "middle", "scroll", "hscroll", "zoom"]


def _keys(combo, cooldown=400, **extra):
    return {"type": "keys", "value": combo, "cooldown_ms": cooldown, **extra}


def _mouse(value, **extra):
    return {"type": "mouse", "value": value, **extra}


MAPPINGS = {
    # core: works with one hand, or with the main hand whenever the other hand isn't holding a mode.
    # The reliable signals (measured on one user's camera) are the index pinch, fist, thumbs and peace sign; the middle, ring
    # and pinky pinches are bonus slots: they were mistaken for the index pinch there, so nothing important depends on them.
    "Hand": _mouse("move"),  # any open or relaxed hand
    "Pinch": _mouse("left"),  # thumb + index: click; keep pinching and move to drag
    "Victory": _mouse("right", cooldown_ms=500),  # peace sign: right click, like a two-finger tap on a trackpad
    "Closed_Fist": _mouse("scroll"),  # grab and move up/down
    "Thumb_Up": _keys("<media_volume_up>", 150, repeat=True),
    "Thumb_Down": _keys("<media_volume_down>", 150, repeat=True),
    "ILoveYou": _keys("<cmd>+<tab>", 1500),
    "Pinch_Middle": _mouse("right", cooldown_ms=500),
    "Pinch_Ring": _mouse("middle", cooldown_ms=500),
    "Pinch_Pinky": {"type": "none", "value": ""},
    # Edit: the other hand makes a fist
    "Edit/Pinch": _keys("<ctrl>+c"), "Edit/Closed_Fist": _keys("<ctrl>+v"), "Edit/Thumb_Up": _keys("<ctrl>+y"),
    "Edit/Thumb_Down": _keys("<ctrl>+z"), "Edit/Victory": _keys("<ctrl>+s", 1000), "Edit/ILoveYou": _keys("<ctrl>+a", 1000),
    "Edit/Pinch_Middle": _keys("<ctrl>+x"), "Edit/Pinch_Ring": _keys("<ctrl>+f", 1000),
    # Media: the other hand gives a thumbs up. Thumbs up/down keep their core job (volume, repeating)
    "Media/Pinch": _keys("<media_play_pause>"), "Media/Closed_Fist": _keys("<media_volume_mute>"),
    "Media/Victory": _keys("<media_next>", 600), "Media/ILoveYou": _keys("<media_previous>", 600),
    "Media/Pinch_Middle": _keys("<media_next>", 600), "Media/Pinch_Ring": _keys("<media_previous>", 600),
    "Media/Pinch_Pinky": _keys("<media_volume_mute>"),
    # Windows: the other hand makes a peace sign
    "Windows/Pinch": _keys("<alt>+<tab>", 500), "Windows/Closed_Fist": _keys("<cmd>+d", 1000),
    "Windows/Thumb_Up": _keys("<cmd>+<up>", 600), "Windows/Thumb_Down": _keys("<cmd>+<down>", 600),
    "Windows/Victory": _keys("<cmd>+<ctrl>+<left>", 800), "Windows/ILoveYou": _keys("<cmd>+<ctrl>+<right>", 800),
    "Windows/Pinch_Middle": _keys("<cmd>+<tab>", 1000), "Windows/Pinch_Ring": _keys("<cmd>+<left>", 800),
    "Windows/Pinch_Pinky": _keys("<alt>+<f4>", 1500),
    # Browser: the other hand makes the "I love you" sign. The fist zooms instead of scrolling
    "Browser/Pinch": _keys("<alt>+<left>", 600), "Browser/Closed_Fist": _mouse("zoom"),
    "Browser/Thumb_Up": _keys("<ctrl>+<tab>", 500), "Browser/Thumb_Down": _keys("<ctrl>+<shift>+<tab>", 500),
    "Browser/Victory": _keys("<ctrl>+w", 800), "Browser/ILoveYou": _keys("<ctrl>+<shift>+t", 1000),
    "Browser/Pinch_Middle": _keys("<alt>+<right>", 600), "Browser/Pinch_Ring": _keys("<f5>", 1000),
    "Browser/Pinch_Pinky": _keys("<ctrl>+t", 800),
    # System: the other hand gives a thumbs down
    "System/Pinch": _keys("<cmd>+<shift>+s", 1500), "System/Closed_Fist": _keys("<cmd>+h", 1500),
    "System/Thumb_Up": _keys("<cmd>+s", 1500), "System/Thumb_Down": _keys("<cmd>+n", 1500),
    "System/Victory": _keys("<cmd>+i", 1500), "System/ILoveYou": _keys("<cmd>+.", 1500),
    "System/Pinch_Middle": _keys("<cmd>+l", 2500), "System/Pinch_Pinky": _keys("<ctrl>+<shift>+<esc>", 1500),
}

DEFAULTS = {
    "version": 4,  # bump when mapping names change; load() then adds the new defaults (and resets very old settings)
    "camera": 0,
    "hand": "Right",  # with both hands in view, this one moves the cursor and the other one picks the mode
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
    "modes": {"Edit": "Closed_Fist", "Media": "Thumb_Up", "Windows": "Victory", "Browser": "ILoveYou", "System": "Thumb_Down"},
    "mappings": MAPPINGS,
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
    version = data.get("version")
    if not isinstance(version, int) or version < 3:
        logging.warning("Settings from an older version: gesture mappings reset to the new defaults")
        data.pop("mappings", None)  # version 2 and earlier used other gesture names
        data.pop("wizard_done", None)  # what the wizard calibrates changed, so offer it once more
    # version 3 -> 4 only added mappings and modes: the user's own mappings stay, and the new ones are filled in below
    data["version"] = DEFAULTS["version"]
    if data.get("hand_mode") in ("single", "two"):
        # older values. "single" was the default, not a choice, and only ever tracked one hand; "auto" now tracks both
        data["hand_mode"] = "auto"
    for key, value in data.items():
        default = DEFAULTS.get(key)
        if type(value) is type(default) or (type(default) is float and type(value) is int):
            cfg[key] = value
    saved = {
        name: m for name, m in cfg["mappings"].items()
        if isinstance(m, dict) and m.get("type") in ACTION_TYPES and isinstance(m.get("value"), str)
        and isinstance(m.get("cooldown_ms", 0), (int, float))
    }
    cfg["mappings"] = {**copy.deepcopy(DEFAULTS["mappings"]), **saved}
    cfg["modes"] = {**DEFAULTS["modes"], **cfg["modes"]}
    if _mode_errors(cfg["modes"]):  # a damaged modes table must not cost the user the rest of their settings
        cfg["modes"] = copy.deepcopy(DEFAULTS["modes"])
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


def _mode_errors(modes):
    errors = []
    for mode, pose in modes.items():
        if mode not in MODES:
            errors.append(f"'{mode}' is not a mode.")
        elif pose not in MODE_POSES:
            errors.append(f"{mode} mode: the other hand's pose must be one of {', '.join(MODE_POSES)}.")
    poses = list(modes.values())
    if len(set(poses)) != len(poses):
        errors.append("Two modes use the same pose. Give each mode its own.")
    return errors


def validate(cfg):
    """Returns a list of human-readable problems; empty means OK."""
    errors = []
    x0, y0, x1, y1 = cfg["box"]
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        errors.append("Cursor area: left/top must be smaller than right/bottom, all between 0 and 1.")
    if cfg["hand_mode"] not in ("auto", "one") or cfg["hand"] not in ("Right", "Left"):
        errors.append("Hand mode must be auto or one, and the pointer hand Right or Left.")
    errors += _mode_errors(cfg["modes"])
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
