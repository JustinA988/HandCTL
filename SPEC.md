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
- **Hand modes:** single-hand mode follows whichever hand is in view. Two-hand mode splits roles: the pointer hand only moves the cursor, the other hand does everything else (clicks included). A setting swaps which hand is the pointer. Hands are told apart by position in the frame (`assign` in `gestures.py`), falling back to MediaPipe's left/right label only when there is nothing else to go on.
- **Settings:** a Settings tab with sub-tabs (Hands, Cursor, Gesture tuning, General), using sliders for tuning values.
- **First-run setup wizard** (`wizard.py`): camera, cursor area (hold the hand at two screen corners), pinch calibration, and a live check of each gesture. Tracking is off while it runs.

#### v2 detection design

The first v2 attempt (finger counting plus a thumb tap on the side of the index finger, read from 2D landmarks) failed in real use: the cursor stalled, clicks were missed, actions misfired and the hand was often dropped. It assumed a hand squarely facing the camera, and its click signal (thumb resting on the index finger or not) was too small a difference to read reliably. The rework follows these rules:

- **Shape from 3D.** Pinch distance and finger curl come from MediaPipe's 3D world landmarks, normalized by hand size, so they hold when the hand is tilted or turned and for any camera position (`features`).
- **Only strong signals.** Clicks are pinches (fingertips touching vs. apart is a large, unambiguous difference). Everything else is one of MediaPipe's own trained poses, accepted only above 0.6 confidence. No hand-rolled finger counting.
- **The cursor needs no pose.** Any hand that isn't pinching, in a fist or making a trained pose moves the cursor, anchored to the palm centre, which barely moves when fingers pinch.
- **Hysteresis.** A pinch starts under the threshold and ends only past 1.5x it; a fist has a similar margin. The pinching finger must not be curled, which separates a pinch from a fist.
- **Timing.** Pinches switch after ~60 ms so clicks feel instant; other poses must be held for `hold_ms` (250 ms). While the hand is changing shape the cursor holds still, and a click is aimed at where the cursor was 100 ms before the fingers began to close.
- **Dropout tolerance.** A hand missing for under 0.3 s changes nothing, so a tracking hiccup doesn't drop a drag. MediaPipe's detection, presence and tracking confidences are lowered from 0.5 to 0.3 so a turned hand is dropped less often.

| Pose | Default action |
|---|---|
| Hand (anything else) | Move cursor |
| Pinch (thumb + index) | Left click; hold = drag |
| Pinch_Middle (thumb + middle) | Right click |
| Closed_Fist, move up/down | Scroll |
| Thumb_Up / Thumb_Down (held) | Volume up / down, repeating |
| Victory | Play/pause |
| ILoveYou | Task view |

Removed from the first v2 attempt: thumb-tap and finger-count gestures, wrist-flick desktop switching (fast cursor moves set it off), the volume "slider" action, and relative cursor mode (it needed the fist as a clutch, which now scrolls).

Not yet verified on real hands: the 0.6 curl and pose-confidence limits, the 0.3 MediaPipe confidences, and the default pinch threshold are reasoned values. The wizard measures the pinch threshold per user; the Preview tab shows the live pinch number for manual tuning.

Ergonomics notes that still apply: an arm held out at shoulder height is the most tiring mid-air posture ([Consumed Endurance, CHI 2014](https://hci.cs.umanitoba.ca/publications/details/consumed-endurance-a-metric-to-quantify-arm-fatigue-of-mid-air-interactions)), so rest the elbow ([elbow-anchored input](https://hci.cs.umanitoba.ca/publications/details/elbow-anchored-interaction-designing-restful-mid-air-input)); webcam air pointing reaches under 75% of mouse throughput, partly from click detection ([SFU](https://vvise.iat.sfu.ca/user/data/papers/inairpointing.pdf)).

### v3
- **Windows installer** (.msi / Inno Setup) with a Start Menu entry.
- **Monitor switching** by head and eye direction, with a camera position setting (above/below monitor).

### v4
- Recording custom poses in settings, optional second camera, voice commands, gesture profile import/export, wake-gesture / hold-to-act activation, macOS then Linux.
