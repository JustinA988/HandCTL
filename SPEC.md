# Hand Gesture Control — v1 Spec

Working name: `handctl` (placeholder, rename before publishing).
License: MIT. Runs fully local and free: no network calls, no paid APIs.

## Goal

Control a Windows PC with one hand in front of a webcam: move and click the mouse, and fire key combos (media, desktop, custom) from a fixed set of poses.

## v1 scope

| Area | v1 behavior |
|---|---|
| OS | Windows 10/11 only. Use cross-platform libs (pynput, Qt) so macOS/Linux ports need no rewrite. |
| Hands | One hand. Left/right chosen in settings (default: right). |
| Activation | On whenever the app runs. Global hotkey toggles tracking (default `Ctrl+Alt+G`). |
| Cursor | Absolute mapping: a calibrated box in the camera frame maps to the full virtual desktop (all monitors). Smoothed. |
| Actions | Every action is one of: mouse action, key combo, or shell command. Media and desktop control are just key combos with good defaults. |
| Gestures | Fixed built-in set (below). User can remap any gesture to any action. |
| Shell commands | Disabled until the user enables them in settings. |
| Safety | Gesture must hold steady ~150 ms before it fires. Per-action cooldown (default 500 ms). Hotkey always works, even if tracking misbehaves. |
| UI | Tray icon + settings window (PySide6). |
| Performance | CPU only, target ~30 FPS at 640x480. |
| Autostart | Settings checkbox, off by default (per-user `HKCU\...\Run` registry entry). |
| Release | PyInstaller zip on GitHub Releases. |

## Built-in gestures and default mappings

Poses come from MediaPipe's free on-device Gesture Recognizer (it returns hand landmarks too). Pinch, scroll and swipe are computed from landmarks.

| Gesture | Default action |
|---|---|
| Pointing up (index finger) | Move cursor (index fingertip) |
| Pinch thumb + index | Left click; hold > 300 ms = drag |
| Pinch thumb + middle | Right click |
| Victory (two fingers) + move up/down | Scroll |
| Open palm, swipe left / right | Switch virtual desktop (`Win+Ctrl+Left` / `Win+Ctrl+Right`) |
| Closed fist | Play/pause (media key) |
| Thumbs up | Volume up |
| Thumbs down | Volume down |
| I-love-you sign | Task view (`Win+Tab`) |

## Settings window

1. **Preview** — live camera feed with landmarks and the detected gesture name.
2. **Calibration** — (v1 layout; v2 moves these to the Settings tab, see Roadmap) cursor box edges as number fields (drawn on the preview), mirror toggle, steadiness, responsiveness, pinch threshold, scroll speed.
3. **Gestures** — table: gesture → action type → value (key combo or command) → cooldown. "Reset to defaults" button.
4. **General** — camera index, hand (L/R), toggle hotkey, enable shell commands, start with Windows.

Settings save to `%APPDATA%\handctl\config.json`. A missing or broken file falls back to defaults, and the broken file is kept as `config.json.bak` instead of being overwritten.

## Code layout

```
handctl/
  __main__.py   Qt app, tray icon, settings window
  tracker.py    camera thread: OpenCV capture → MediaPipe → gesture events
  gestures.py   pinch / scroll / swipe detection from landmarks, debounce
  actions.py    executes actions via pynput (mouse, keys) and subprocess (shell)
  config.py     defaults, load/save JSON
tests/
  test_gestures.py   detection logic on recorded/synthetic landmarks
```

Dependencies: `mediapipe`, `opencv-python`, `PySide6`, `pynput`. Nothing else.

## Known technical points

- MediaPipe models (`gesture_recognizer.task`) ship inside the release; nothing is downloaded at runtime.
- Qt 6 makes the process per-monitor DPI aware, so cursor coordinates match physical pixels on mixed-DPI monitors.
- Camera runs in its own thread; actions run off the UI thread so a slow shell command can't freeze tracking.
- Shell commands run detached without a console window and are not waited on (a timeout would kill launched apps); launch failures show a tray notification.
- MediaPipe 1.x no longer bundles models or the legacy `mp.solutions` API; the app uses the Tasks `GestureRecognizer`.

## Roadmap

### v2 (built on branch `v2/gestures`)
- **Hand modes:** single-hand mode (as in v1) or two-hand mode with separate roles. The pointer hand only moves the cursor (point; fist = lift); the other hand does everything else, clicks included, so the pointer never moves to click and a thumb tap held on one hand while pointing with the other is a drag. A setting swaps which hand is the pointer. Roles are fixed per gesture (`POINTER_GESTURES` in `gestures.py`); per-gesture role editing is not built.
- **Gestures:** an ergonomic set chosen from research (below).
- **Settings:** a Settings tab with sub-tabs (Hands, Cursor, Gesture tuning, General), using sliders for tuning values.
- **First-run setup wizard** (`wizard.py`): camera, cursor area (point at two screen corners), thumb-tap calibration, and a live check of each gesture. Tracking is off while it runs. If thumb taps can't be told apart on the camera, the wizard switches clicking to pinch.

#### v2 gesture set and why

Research findings behind it:
- Arm held out at shoulder height is the most tiring mid-air posture ([Consumed Endurance, CHI 2014](https://hci.cs.umanitoba.ca/publications/details/consumed-endurance-a-metric-to-quantify-arm-fatigue-of-mid-air-interactions)), so the hand stays low with the elbow on the desk.
- Thumb-to-index-finger microgestures are low-effort, and the finger side facing the thumb is the least demanding ([Saarland thesis on single-handed gesture input](https://hci.cs.uni-saarland.de/wp-content/uploads/Theses/Bachelors/Bachelor-thesis-lena-hegemann.pdf)); clicking with the thumb also keeps the pointing finger still.
- An open palm facing forward causes wrist dorsiflexion, a common ergonomic issue in mid-air studies ([Exploring Mid-Air Hand Interaction in Data Visualization](https://arxiv.org/pdf/2311.15372)), so no gesture uses a flat palm and an open hand is simply "nothing".
- Guiard's asymmetric bimanual model: the dominant hand does fine pointing, the other hand coarse actions ([overview](https://a11y-paradise.onrender.com/glossary/69e17e182d4c4de6f084c00f)). Evidence on the non-dominant hand clicking is mixed, hence swappable roles.
- Webcam air pointing reaches under 75% of mouse throughput, partly from poor click detection ([SFU](https://vvise.iat.sfu.ca/user/data/papers/inairpointing.pdf)), hence the wizard's calibration and the pinch fallback.

| Pose | Default action |
|---|---|
| Point (index finger out) | Move cursor |
| Point + thumb tap on the side of the index finger | Left click; hold = drag |
| Two fingers out (index + middle), move up/down | Scroll |
| Two fingers + thumb tap | Right click |
| Three fingers out (index, middle, ring), short wrist swipe left/right | Previous/next desktop |
| Three fingers + thumb tap | Play/pause |
| Thumbs up, raise/lower the hand | Volume up/down |
| Fist | Nothing: freezes the cursor ("lift the mouse"), the clutch for relative mode |
| Pinch, I-love-you | Unmapped; pinch is the fallback click |

Rule of the set (the trackpad model): 1 finger moves and taps to click, 2 fingers scroll and tap to right-click, 3 fingers swipe to switch desktops and tap to play/pause.

Also new: a relative ("trackpad") cursor mode as an option; absolute stays the default. Thumb tap's default threshold is untested on real cameras, so the wizard measures it per user and it's a slider in settings.

### v3
- **Windows installer** (.msi / Inno Setup) with a Start Menu entry.
- **Monitor switching** by head and eye direction, with a camera position setting (above/below monitor).

### v4
- Recording custom poses in settings, optional second camera, voice commands, gesture profile import/export, wake-gesture / hold-to-act activation, macOS then Linux.
