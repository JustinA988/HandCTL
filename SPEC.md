# Hand Gesture Control — v1 Spec

Package name: `handctl`.
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
2. **Calibration** — cursor box edges as number fields (drawn on the preview), mirror toggle, smoothing, pinch threshold, scroll speed.
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

### v2
- **Hand modes:** single-hand mode (as in v1) or two-hand mode with separate roles: one hand moves the cursor, the other triggers clicks and actions. A setting swaps which hand does which.
- **New gestures:** replace the gesture set with ergonomic signs chosen from a short research pass (comfort, low arm fatigue, reliable detection). Pinch click and drag is the first to replace. New signs get approved before they are built.
- **Settings:** a dedicated Settings tab with sub-tabs, using sliders for tuning values.
- **First-run calibration wizard:** camera choice, cursor area, and a quick test of each gesture.

### v3
- **Windows installer** (.msi / Inno Setup) with a Start Menu entry.
- **Monitor switching** by head and eye direction, with a camera position setting (above/below monitor).

### v4
- Recording custom poses in settings, optional second camera, voice commands, gesture profile import/export, wake-gesture / hold-to-act activation, macOS then Linux.
