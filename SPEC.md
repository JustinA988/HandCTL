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
- **Hand modes:** "auto" (default, since 3.0.1) always asks MediaPipe for two hands. One hand in view does everything; with both in view the pointer hand only moves the cursor and the other hand does everything else (clicks included). Roles are re-decided every frame (`Tracker._roles`), with a 0.3 s grace so a tracking hiccup doesn't flip them, and never change while a hand holds the mouse button. A setting swaps which hand is the pointer. "one" tracks a single hand only. Hands are told apart by position in the frame (`assign` in `gestures.py`), falling back to MediaPipe's left/right label only when there is nothing else to go on. Before 3.0.1 the default "single" mode asked MediaPipe for one hand, so a second hand was never seen; saved "single"/"two" settings now load as "auto".
- **Speed (3.0.2):** asking MediaPipe for two hands costs about 12 ms more per frame than one, because it hunts for a second hand every frame (measured: one hand in view 10.5 ms vs 22.6 ms). In "auto" mode `HandCount` keeps a one-hand recognizer for tracking and uses a two-hand recognizer only while a second hand is present, plus a check every 0.25 s to notice one arriving (noticed within about 180-230 ms in testing); it drops back after the second hand has been missing for 1 s. Measured through the real tracker thread on hand photos: one hand 20.5 ms -> 11.7 ms per frame, two hands 18.7 -> 16.6 ms. The preview is drawn 15 times a second instead of every frame.
- **Smoothing trade-off (One Euro, 30 fps, slow hand movement):** min_cutoff / beta 5 / 20 trails the hand by ~17 ms with 1.5x less jitter; 1 / 10 by ~38 ms with 2.3x; 0.5 / 2 by ~96 ms with 3.4x. Defaults are 1.0 / 10 (guarded by a test); the user's own settings file may hold other values.
- **Settings file:** read as UTF-8 with or without a byte-order mark (Notepad and PowerShell 5 write one); before 3.0.2 such a file was treated as corrupt and moved aside.
- **Known limit:** MediaPipe's trained-pose scores depend on image orientation (one sample peace sign scores 0.68-0.77 unmirrored, 0.51-0.53 mirrored), so poses near the 0.6 cutoff may not always fire. Lower `POSE_SCORE` only with real-hand data, since that also raises accidental triggers.
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

### v3 (built on branch `v3/installer-monitors`)

#### Monitor switching
- **Gaze** (`gaze.py`): MediaPipe's face landmarker (478 points including irises) gives a line of sight in degrees. Yaw = head turn (depth difference between the outer eye corners) + eye rotation (iris offset across the eye opening, scaled by eye width over eyeball radius). Pitch = head tilt only, because eyelids make vertical iris position unreliable; stacked monitors may need eye pitch later. Landmark indices and sign conventions were checked against a real face photo.
- **Calibration**: a window appears on each monitor in turn (placed through Windows in real pixels); the median gaze while looking at each one becomes its target. Monitors with too few readings (face not visible) or targets closer than 8 degrees are left out, and the user is told which and why. Needs two usable monitors.
- **Choosing**: the nearest target wins, but a switch needs the new monitor to be clearly nearer (distance under 0.75x the current one) for 0.4 s, so glances and noise don't flip it. No face visible = stay put. Switching starts on the monitor the cursor is on, so nothing jumps at launch.
- **Effect**: the hand's cursor area maps onto the looked-at monitor only, and on a switch the cursor moves to the same relative spot there. Switching off = the hand maps to the whole desktop, as before.
- **Cost**: the face is read every 150 ms, only while switching is on or calibrating; hand tracking keeps its own frame rate.

#### Installer
- PyInstaller freezes the app (`installer/entry.py`), Inno Setup packages it (`installer/handctl.iss`); `installer/build.ps1` does both and refuses to package a frozen copy that fails `handctl --check`.
- Per-user install without admin rights (an all-users install is offered), Start Menu entry, optional desktop shortcut and autostart. Setup and uninstall ask to close a running copy (it holds the `handctl-single-instance` mutex). Uninstall removes the autostart entry however it was set, and keeps `%APPDATA%\handctl`.
- Python 3.15 note: PySide6 replaces `builtins.__import__`, after which 3.15's lazy imports never resolve across modules. A frozen build loads Qt first, so `handctl/__init__.py` turns lazy imports off and repairs `concurrent.futures` regardless of import order.

#### Two-hand controls: core plus modes (3.1)

Design (Guiard's asymmetric model: the non-dominant hand sets the context, the dominant hand does the fine work): the main hand always moves the cursor and does the core gestures; the other hand holds a pose like a modifier key to pick a mode (`ModeSelector`, 0.15 s in, 0.25 s out); in a mode the main hand's gestures look up `Mode/Pose` first and fall back to the plain `Pose`. The other hand never moves the cursor or clicks, so a fist or thumbs-up held there can't act. An action is chosen when its pose starts and kept until the pose ends. Five modes (Edit, Media, Windows, Browser, System), nine slots each; one hand in view = core only.

Measured on one user's camera (guided recording of 1,839 frames, replayed through the real tracker logic), which changed the design:
- **Only the index pinch is reliable.** With 3D distances the index fingertip was the nearest to the thumb 94-100% of the time whichever finger was pinching; with 2D or palm-plane distances the intended fingertip was nearest only 17-49% of the time. So middle/ring/pinky pinches are bonus slots and every important action sits on reliable signals: index pinch, fist, thumbs up/down, peace sign, "I love you".
- **Right click moved to the peace sign** (recognised in 143 of 148 frames); the thumb + middle pinch it used to be was never recognised.
- **Fist vs pinch:** a fist's fingers measured 0.42-0.68 straight, a pinching finger 0.85-0.97 (1.0 = straight). Fingers must be straighter than `CURLED` (0.72) to pinch, and an average below `FIST` (0.72) is a fist. A held pinch used to ignore straightness and stay "held" through a fist; a held fist used to stay held through a thumbs-up or peace sign. Both fixed; fist recognition went from 43 to 119 of 147 frames, fist scrolling from 1 to 51 scroll events.
- **A held pinch moves to another finger** once that finger is clearly nearer (0.8x the distance).
- **Phantom hands** (MediaPipe reporting a small hand on the cheek or hairline when none is in view) did not depend on the confidence setting (0.3, 0.5 and 0.7 gave the same count). Measured as 0.27-0.42x the face's width, versus 0.51-0.65x for the user's fists and about 1.2x for open hands. `face_part` drops a detection smaller than 0.45x the face width and centred within one face-width/height of it; the face is read about every 0.3 s. On the recording it dropped 13 of the 14 detections narrower than 0.6x the face in the index-pinch phase and 19 of the 39 in the pinky-pinch phase; what the remainder were (real hands, or phantoms outside the limits) was not determined.
- **Hands cut off by the picture edge** (3 or more landmarks outside it; up to 13 for a hand resting at the bottom edge) are ignored: they caused stray clicks. Hands being used had 0-1.
- Not verified on other people or cameras. Thresholds (`CURLED`, `FIST`, the 0.45 face ratio, `POSE_SCORE`) come from this one recording. The wizard's pinch step measures the pinch threshold per user.

#### Action-only mode (3.2)

`control_mode: "actions"` (Settings > Hands, or the tray menu). The hand never aims: `Engine._pick` looks only at `A:`-prefixed mappings (`A:Pinch`, `A:Edit/Pinch`, ...), which are kept next to the cursor mappings in the same dictionary, so settings files from earlier versions simply gain them and switching modes loses nothing. No fallback to a cursor mapping. Every pose waits `action_hold_ms` (250) instead of the quick 60 ms pinch and 100 ms pose holds, because with nothing being aimed there is no reason to hurry and a stray pinch would fire a screenshot. One hand, on the poses that tested reliable: pinch = screenshot, fist = voice typing, thumbs up/down = next/previous tab, peace sign = play/pause, "I love you" = switch app. The two-hand modes are copied over (`A:Edit/...` etc.) with Media's thumbs set to volume. Verified by replaying the recorded session in this mode: no actions in the no-hands, open-hand, both-hands-open and near-face phases; one screenshot from the repeated pinches (cooldown 1.5 s), one voice-typing from the held fist, two copies in Edit mode. Not verified live.

#### 3.3: action-only fixes

- Picking a control mode in Settings applied nothing until Save & apply, and closing the window quits without saving, so the switch looked broken (the tester's saved file still said `cursor`). The Control mode dropdown now applies and saves at once, like the tray item, without saving or discarding other edits in the window. Closing the window with unsaved edits asks Save / Discard / Cancel.
- `action_hold_ms` 250 -> 150. Replaying the recorded session in action-only mode: 150 fires nothing in the no-hands, open-hand, both-open and near-face phases, and the index pinch fires sooner; 100 fired voice typing from a relaxed open hand.
- Action-only thumbs repeat while held (cooldown 800 ms), so a held thumb walks through tabs.
- Settings version 5: version-4 files that still hold the old untouched values (hold 250, thumbs 500 ms without repeat) get the new ones; changed values stay.

#### 3.4: action mode by default, motion gestures, steadier monitor switching

- `control_mode` defaults to `"actions"`; cursor mode is optional. Saved settings keep the user's choice.
- New pose `Point`: index finger straight (ext >= CURLED + 0.1), the other three curled (< CURLED). Checked before the fist, whose mean-ext test it would otherwise pass; a pointing finger also ends a held fist. Cursor mode maps it to `move` (pointing used to read as a fist and scroll); action mode to `scroll`.
- Action-mode pinch is a tap or a swipe: on entering a pinch nothing fires; while it is held, every `SWIPE` (0.12 of the cursor area) travelled fires `Swipe_Left/Right/Up/Down` (tabs, task view, show desktop), the first step locking the axis; letting go fires the plain `Pinch` mapping (screenshot) only if no swipe fired. Thumbs are volume (repeat) again; tabs moved to swipes.
- Monitor switching: `gaze_source` `eyes` | `head` (head yaw only); one calibration run stores both (`monitor_gaze`, `monitor_head`), the look signal carrying (yaw, pitch, head yaw). The selector takes the per-axis median of the last three readings, with user-set `monitor_dwell_ms` and `monitor_margin`. A switch is deferred while any engine is `busy()` (a pose other than a resting or cursor-moving hand) or a mode is held, then happens at the next reading. `monitor_focus` (default on): `look_at` brings the frontmost ordinary window centred on that monitor to the front (EnumWindows z-order, skipping tool, click-through, no-activate and cloaked windows; AttachThreadInput to get past the foreground lock) and centres the cursor on it, clipped to the monitor.
- Settings version 6: untouched 3.2/3.3 action thumb mappings are replaced by the new defaults.
- Verified: unit tests (93), a replay of the recorded session in action mode (no actions with no hands, open hand, both open or near the face; no swipes from repeated in-place pinches; Point seen in 2 frames of the fist phase, too short to act), and bringing a window on another monitor to the front from a background process on the dev machine. Not verified live with hands or eyes.

#### 3.5: gesture fixes, places to ignore, faster switching

- Reported: pinch/swipes and peace / "I love you" / modes did nothing or the wrong thing; looking down at the keyboard switched monitors (and, with focus on, sent gestures to the wrong window).
- Swipes are measured from when the raw pinch started (from the position trail), not from when the pinch was confirmed 0.15 s later: a quick flick was mostly over by then, fell short, and the release took a screenshot. One action per swipe (largest axis), `SWIPE` 0.15; stepping fired several tabs on one long swipe. The pinch's own action and a swipe use any mode held during the pinch, picked at release, so a mode hand that is a moment late still counts.
- Peace sign and "I love you" also come from finger shape (index + middle straight, ring + pinky bent; index + pinky straight, middle + ring bent), alongside MediaPipe's label at >= 0.6, which drops on a turned hand. The replayed session shows no such shapes with open hands or near the face.
- Places to ignore: calibration ends with a keyboard step (beep when done, since the user is looking away); "Add a place to ignore" records one more; stored per gaze source (`ignore_gaze`, `ignore_head`). The selector stays put whenever an ignore spot is nearer than the nearest monitor. A spot within `MIN_APART` of a monitor is left out with a message.
- Faster: face read every 0.1 s (was 0.15), `monitor_dwell_ms` 250 (was 400; settings version 7 moves an untouched 400).
- Not verified live.

#### 3.6: a simpler default set

- Seven signs (open hand, pinch, point, fist, thumbs up/down, peace sign), the ones read reliably on the test camera and leaning on the thumb and index finger, the most independent digits (Hager-Ross & Schieber 2000). The middle/ring/pinky pinches and "I love you" keep their slots with no default action.
- Modes cut from five to three (Edit = fist, Media = thumbs up, Windows = peace sign: the steadiest signs to hold with the other hand, after Guiard's kinematic chain), each using the same five main-hand signs. Browser and System are gone (tabs live in the core swipes).
- Action mode: swipe up = Alt+Tab (task view needs a cursor), "I love you" no longer switches app; inside Media mode swipes change track, inside Windows mode they switch virtual desktop (the touchpad's four-finger swipe).
- Settings version 8: `_OLD` lists every default that changed, by its old value; a saved mapping still holding it is dropped so the new default applies, and one the user changed stays. Saved mappings for names that no longer exist (Browser/..., System/...) and modes that no longer exist are dropped.
- Verified: 102 tests; the replayed session gives the same actions as before (nothing with no hands, open hands or near the face). The tester's own peace-sign change (play/pause in cursor mode) survives the upgrade. Not verified live.

### v4
- Recording custom poses in settings, optional second camera, voice commands, gesture profile import/export, wake-gesture / hold-to-act activation, macOS then Linux.
