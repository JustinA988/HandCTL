"""Settings: defaults, validation, and load/save of %APPDATA%/handctl/config.json."""
import copy
import json
import logging
import os
from pathlib import Path

from pynput.keyboard import HotKey

PATH = Path(os.environ.get("APPDATA", Path.home())) / "handctl" / "config.json"

POSE_NAMES = ["Hand", "Pinch", "Pinch_Middle", "Pinch_Ring", "Pinch_Pinky", "Closed_Fist", "Thumb_Up", "Thumb_Down", "Victory", "ILoveYou",
              "Point"]
MODE_POSES = ["Closed_Fist", "Thumb_Up", "Thumb_Down", "Victory", "ILoveYou"]  # poses the other hand can hold to pick a mode
MODES = ["Edit", "Media", "Windows"]
SLOTS = [p for p in POSE_NAMES if p != "Hand"]  # what the main hand can do inside a mode
# every mapping name: a plain pose is a "core" action that works whenever no mode overrides it; "Mode/Pose" is a mode's version
ACTION_PREFIX = "A:"  # action-only mode keeps its own mappings under this prefix, so switching modes never loses either set
GESTURES = POSE_NAMES + [f"{mode}/{pose}" for mode in MODES for pose in SLOTS]
# action mode only: pinch and move the hand one way. A pinch let go without moving is the plain "Pinch" action
MOTIONS = ["Swipe_Left", "Swipe_Right", "Swipe_Up", "Swipe_Down"]
ACTION_GESTURES = [ACTION_PREFIX + name for name in
                   POSE_NAMES + MOTIONS + [f"{mode}/{pose}" for mode in MODES for pose in SLOTS + MOTIONS]]
ACTION_TYPES = ["none", "mouse", "keys", "shell"]
MOUSE_VALUES = ["move", "left", "right", "middle", "scroll", "hscroll", "zoom"]


def _keys(combo, cooldown=400, **extra):
    return {"type": "keys", "value": combo, "cooldown_ms": cooldown, **extra}


def _mouse(value, **extra):
    return {"type": "mouse", "value": value, **extra}


_NONE = {"type": "none", "value": ""}

# The default set uses seven signs only: open hand (rest), pinch, point, fist, thumbs up, thumbs down and peace sign. They
# lean on the thumb and index finger, the most independent fingers (Hager-Ross & Schieber 2000), and they were the ones
# read reliably on the camera they were tested with. The middle, ring and pinky pinches and "I love you" have slots but no
# default action: the first three were mistaken for the index pinch there, and the fewer signs to learn, the better.
MAPPINGS = {
    # cursor mode, core: works with one hand, or with the main hand whenever the other hand isn't holding a mode
    "Hand": _mouse("move"),  # any open or relaxed hand
    "Point": _mouse("move"),  # index finger up, the rest curled: also moves the cursor
    "Pinch": _mouse("left"),  # thumb + index: click; keep pinching and move to drag
    "Victory": _mouse("right", cooldown_ms=500),  # peace sign: right click, like a two-finger tap on a trackpad
    "Closed_Fist": _mouse("scroll"),  # grab and move up/down
    "Thumb_Up": _keys("<media_volume_up>", 150, repeat=True),
    "Thumb_Down": _keys("<media_volume_down>", 150, repeat=True),
    "ILoveYou": _NONE, "Pinch_Middle": _NONE, "Pinch_Ring": _NONE, "Pinch_Pinky": _NONE,
    # modes, picked by the other hand. Each uses the same five signs, and anything a mode leaves out does its core job
    # Edit: the other hand makes a fist
    "Edit/Pinch": _keys("<ctrl>+c"), "Edit/Closed_Fist": _keys("<ctrl>+v"), "Edit/Victory": _keys("<ctrl>+s", 1000),
    "Edit/Thumb_Up": _keys("<ctrl>+y"), "Edit/Thumb_Down": _keys("<ctrl>+z"),
    # Media: the other hand gives a thumbs up. Thumbs keep their core job (volume)
    "Media/Pinch": _keys("<media_play_pause>"), "Media/Closed_Fist": _keys("<media_volume_mute>"),
    "Media/Victory": _keys("<media_next>", 600),
    # Windows: the other hand makes a peace sign
    "Windows/Pinch": _keys("<alt>+<tab>", 500), "Windows/Closed_Fist": _keys("<cmd>+d", 1000),
    "Windows/Victory": _keys("<cmd>+<tab>", 1000), "Windows/Thumb_Up": _keys("<cmd>+<up>", 600),
    "Windows/Thumb_Down": _keys("<cmd>+<down>", 600),
}

# action mode: the hand never aims the cursor. Simple actions are a single sign; the ones with a direction or an amount are
# a sign plus a movement. Swipes follow the Windows touchpad: down shows the desktop, sideways moves between things.
_ACTION_CORE = {
    "Hand": _NONE,  # relaxed hand: nothing happens
    "Pinch": _keys("<cmd>+<shift>+s", 1500),  # screenshot: pinch and let go without moving
    "Swipe_Left": _keys("<ctrl>+<shift>+<tab>", 150),  # pinch and move left: previous tab
    "Swipe_Right": _keys("<ctrl>+<tab>", 150),  # next tab
    "Swipe_Up": _keys("<alt>+<tab>", 800),  # back to the last app (task view, the touchpad's swipe up, needs a cursor)
    "Swipe_Down": _keys("<cmd>+d", 1000),  # show desktop
    "Point": _mouse("scroll"),  # index finger up, then move the hand up or down
    "Closed_Fist": _keys("<cmd>+h", 1500),  # voice typing: a fist like holding a microphone
    "Thumb_Up": _keys("<media_volume_up>", 150, repeat=True),
    "Thumb_Down": _keys("<media_volume_down>", 150, repeat=True),
    "Victory": _keys("<media_play_pause>", 800),
}
for _pose in POSE_NAMES + MOTIONS:
    MAPPINGS[ACTION_PREFIX + _pose] = _ACTION_CORE.get(_pose, _NONE)
for _name, _m in list(MAPPINGS.items()):
    if "/" in _name and not _name.startswith(ACTION_PREFIX):
        MAPPINGS[ACTION_PREFIX + _name] = dict(_m)
MAPPINGS.update({  # in action mode, swipes inside a mode move through that mode's things
    "A:Media/Swipe_Left": _keys("<media_previous>", 600), "A:Media/Swipe_Right": _keys("<media_next>", 600),
    "A:Windows/Swipe_Left": _keys("<cmd>+<ctrl>+<left>", 800),  # previous / next virtual desktop, like a four-finger swipe
    "A:Windows/Swipe_Right": _keys("<cmd>+<ctrl>+<right>", 800),
})
KNOWN = set(GESTURES + ACTION_GESTURES)
# earlier defaults that have since changed, by their old value. load() drops a saved mapping still holding its old default,
# so untouched settings get today's set while mappings the user changed stay
_OLD = {
    "ILoveYou": "<cmd>+<tab>", "Pinch_Middle": "right", "Pinch_Ring": "middle",
    "A:ILoveYou": "<alt>+<tab>", "A:Swipe_Up": "<cmd>+<tab>", "A:Thumb_Up": "<ctrl>+<tab>", "A:Thumb_Down": "<ctrl>+<shift>+<tab>",
    # empty before ("none"; the settings window saves every row), so they get their new default
    "A:Media/Swipe_Left": "", "A:Media/Swipe_Right": "", "A:Windows/Swipe_Left": "", "A:Windows/Swipe_Right": "",
    **{prefix + name: value for prefix in ("", ACTION_PREFIX) for name, value in {
        "Edit/ILoveYou": "<ctrl>+a", "Edit/Pinch_Middle": "<ctrl>+x", "Edit/Pinch_Ring": "<ctrl>+f",
        "Media/ILoveYou": "<media_previous>", "Media/Pinch_Middle": "<media_next>", "Media/Pinch_Ring": "<media_previous>",
        "Media/Pinch_Pinky": "<media_volume_mute>", "Windows/Victory": "<cmd>+<ctrl>+<left>",
        "Windows/ILoveYou": "<cmd>+<ctrl>+<right>", "Windows/Pinch_Middle": "<cmd>+<tab>", "Windows/Pinch_Ring": "<cmd>+<left>",
        "Windows/Pinch_Pinky": "<alt>+<f4>",
    }.items()},
}

DEFAULTS = {
    "version": 8,  # bump when mapping names change; load() then adds the new defaults (and resets very old settings)
    "camera": 0,
    "hand": "Right",  # with both hands in view, this one moves the cursor and the other one picks the mode
    "control_mode": "actions",  # "actions": gestures only trigger actions; "cursor" (optional): the hand moves the cursor
    "action_hold_ms": 150,  # action-only mode: how long any pose must be held (replayed: 100 let a relaxed hand fire)
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
    "gaze_source": "eyes",  # "eyes": head turn plus eye direction; "head": head turn only (steadier, no eye tracking)
    "monitor_head": {},  # like monitor_gaze, calibrated with gaze_source "head"
    "monitor_focus": True,  # on a switch, bring that monitor's window to the front and put the cursor in its middle
    "monitor_dwell_ms": 250,  # how long a look must last before the monitor switches
    "ignore_gaze": [],  # [yaw, pitch] of places looked at that aren't monitors (the keyboard...): looking there never switches
    "ignore_head": [],  # the same for gaze_source "head"
    "monitor_margin": 0.75,  # how much nearer the new monitor must look than the current one (lower = steadier)
    "modes": {"Edit": "Closed_Fist", "Media": "Thumb_Up", "Windows": "Victory"},
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
    if version == 6 and data.get("monitor_dwell_ms") == 400:  # 3.4's switch delay, left as it came: take the quicker one
        data.pop("monitor_dwell_ms")
    if version == 4 and data.get("action_hold_ms") == 250:
        data.pop("action_hold_ms")
    if isinstance(version, int) and 4 <= version < 8 and isinstance(data.get("mappings"), dict):
        data["mappings"] = {name: m for name, m in data["mappings"].items()
                            if not (isinstance(m, dict) and name in _OLD and m.get("value") == _OLD[name])}
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
        if name in KNOWN and isinstance(m, dict) and m.get("type") in ACTION_TYPES and isinstance(m.get("value"), str)
        and isinstance(m.get("cooldown_ms", 0), (int, float))
    }
    cfg["mappings"] = {**copy.deepcopy(DEFAULTS["mappings"]), **saved}
    cfg["modes"] = {**DEFAULTS["modes"], **{mode: pose for mode, pose in cfg["modes"].items() if mode in MODES}}
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


def gaze_key(cfg, ignore=False):
    """Where the monitor calibration (or, with ignore=True, the places to ignore) for the chosen gaze source is kept."""
    head = cfg["gaze_source"] == "head"
    return ("ignore_head" if head else "ignore_gaze") if ignore else ("monitor_head" if head else "monitor_gaze")


def validate(cfg):
    """Returns a list of human-readable problems; empty means OK."""
    errors = []
    x0, y0, x1, y1 = cfg["box"]
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        errors.append("Cursor area: left/top must be smaller than right/bottom, all between 0 and 1.")
    if cfg["control_mode"] not in ("cursor", "actions"):
        errors.append("Control mode must be cursor or actions.")
    if cfg["hand_mode"] not in ("auto", "one") or cfg["hand"] not in ("Right", "Left"):
        errors.append("Hand mode must be auto or one, and the pointer hand Right or Left.")
    errors += _mode_errors(cfg["modes"])
    if not all(isinstance(p, list) and len(p) == 2 and all(type(v) in (int, float) for v in p)
               for key in ("monitor_gaze", "monitor_head") for p in cfg[key].values()) or not all(
            isinstance(p, list) and len(p) == 2 and all(type(v) in (int, float) for v in p)
            for key in ("ignore_gaze", "ignore_head") for p in cfg[key]):
        errors.append("Monitor calibration data is damaged. Run the monitor calibration again.")
    if cfg["gaze_source"] not in ("eyes", "head"):
        errors.append("Monitor switching must follow eyes or head.")
    elif cfg["monitor_switch"] and len(cfg[gaze_key(cfg)]) < 2:
        errors.append("Monitor switching needs a calibration first (one for each of eyes and head turn): "
                      "Settings > Monitors > Calibrate monitors.")
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
