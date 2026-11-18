# handctl

Control your Windows PC with your hands in front of a webcam: move and click the mouse, scroll and control media. With several monitors, the cursor follows you to the monitor you look at. Everything runs locally on the CPU. No network calls, no accounts.

## Install

Run `handctl-setup-<version>.exe`, from the [Releases page](https://github.com/JustinA988/HandCTL/releases) once a release is published, or built yourself (see [Building the installer](#building-the-installer)). It installs for your user account only, with no admin rights needed, and adds a Start Menu entry. A desktop shortcut and starting with Windows are optional during setup. Uninstall from **Settings → Apps**; your settings in `%APPDATA%\handctl` are kept, so a reinstall remembers your calibration.

## Install from source

Requires Windows 10/11, Python 3.12+ and a webcam. Commands are for Windows PowerShell and run from the project folder (the one containing `pyproject.toml`).

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Download MediaPipe's hand and face models (Apache-2.0, ~8 MB and ~4 MB) into `handctl/models/`:

```powershell
Invoke-WebRequest https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task -OutFile handctl\models\gesture_recognizer.task
```

```powershell
Invoke-WebRequest https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task -OutFile handctl\models\face_landmarker.task
```

Check that everything loads (no camera, mouse or keyboard involved; exit code 0 means OK):

```powershell
.venv\Scripts\python -m handctl --check; $LASTEXITCODE
```

## Run

```powershell
.venv\Scripts\python -m handctl
```

To start hidden in the tray instead (no settings window):

```powershell
.venv\Scripts\python -m handctl --tray
```

The app sits in the system tray. The settings window opens on launch unless you pass `--tray`.

**Closing the settings window quits the app.** Minimizing it doesn't. To quit while the window is closed, right-click the tray icon and choose **Quit**. Only one copy can run at a time; a second launch shows a message and exits.
**`Ctrl+Alt+G` turns tracking on and off**, and so does the tray menu. Tracking is on as soon as the app starts.

## First run

The first launch opens a setup wizard: pick your camera, mark the cursor area by holding your hand at two screen corners, calibrate your pinch, and try each gesture. Tracking stays off while it runs, so the cursor can't move. Re-run it any time from **Settings → General → Run setup wizard**.

## Default gestures

Raise a hand in view of the camera with your elbow resting on the desk or chair arm; holding your whole arm out tires it quickly. Your hand doesn't have to face the camera squarely: poses are read from the hand's 3D shape, and the camera can sit above, below or beside the screen.

### One hand

| Gesture | Action |
|---|---|
| Any open or relaxed hand | Move cursor (it follows the centre of your palm) |
| Pinch thumb + index fingertip | Left click; keep pinching and move = drag |
| Peace sign | Right click |
| Fist, move up/down | Scroll |
| Thumbs up / thumbs down (hold) | Volume up / down (repeats) |
| "I love you" sign | Task view |

### Two hands: modes

With both hands in view, your **main hand** (right by default; change it under Settings → Hands) keeps doing everything above. Your **other hand** holds a pose like a Shift key to pick a *mode*; while it does, the main hand's gestures do that mode's actions. Let go and everything returns to normal.

| Other hand holds | Mode |
|---|---|
| Fist | Edit |
| Thumbs up | Media |
| Peace sign | Windows |
| "I love you" sign | Browser |
| Thumbs down | System |

What the main hand's gestures do in each mode:

| Main hand | Edit | Media | Windows | Browser | System |
|---|---|---|---|---|---|
| Pinch (thumb + index) | Copy | Play/pause | Switch app | Back | Screenshot |
| Fist | Paste | Mute | Show desktop | Zoom (move up/down) | Voice typing |
| Thumbs up | Redo | Volume up | Maximize | Next tab | Search |
| Thumbs down | Undo | Volume down | Minimize | Previous tab | Notifications |
| Peace sign | Save | Next track | Previous desktop | Close tab | Settings |
| "I love you" | Select all | Previous track | Next desktop | Reopen closed tab | Emoji panel |

Anything a mode doesn't use does its normal job (thumbs up is still volume in Media mode). Every mapping can be changed under the **Gestures** tab, which has a table for the normal gestures and one per mode, and each mode's pose can be changed under Settings → Hands. Actions can be mouse actions (`move`, `left`, `right`, `middle`, `scroll`, `hscroll`, `zoom`), key combos (`<ctrl>+<alt>+t`, `<cmd>+d`, `<media_next>`, in [pynput's HotKey format](https://pynput.readthedocs.io/en/latest/keyboard.html#global-hotkeys)), or shell commands.

**Bonus pinches.** Thumb + middle (right click), thumb + ring (middle click) and thumb + pinky also have slots, with extra actions in the modes (cut, find, forward, refresh, new tab, close window, lock screen, task manager and more). On the camera these were tested on, the middle and ring pinches were mistaken for the index pinch and the pinky pinch worked about a third of the time, so nothing important depends on them. They may work better on your hands.

How it avoids misfires and missed input:
- The cursor needs no special pose, so it can't be "lost" by a finger out of place.
- A click lands where the cursor was just before your fingers closed, and the cursor holds still while you pinch.
- A pinch only ends when the fingers clearly part, and a straight finger is required to pinch, so a fist with the thumb against it isn't read as a pinch.
- A hand that vanishes for under 0.3 s (a tracking hiccup) changes nothing. Poses other than the index pinch must be held about a tenth of a second, ring and pinky pinches a fifth, and each action has a cooldown.
- A mode starts after its pose is held for 0.15 s and ends 0.25 s after you drop it, so a flicker doesn't flip modes. An action stays what it was when its gesture started, even if the mode changes underneath it.
- Phantom hands are ignored: small hand-shaped detections on your face or hairline, and hands cut off by the edge of the picture (a hand resting at the bottom edge used to cause stray clicks).
- Closing the mode hand's pose never moves the cursor or clicks: that hand only picks the mode.

If a second hand gets in the way (for example while typing), set **Settings → Hands → Hand mode** to **one**: only one hand is ever tracked, and modes are off.

To keep this fast, the app tracks with the cheaper one-hand mode and checks for a second hand four times a second, so a second hand is noticed within about a quarter of a second of appearing. (Always looking for two hands made every frame about 9 ms slower, even with one hand in view.)

Settings saved by an earlier version keep your camera, calibration and your own mappings; the new modes are added alongside them. Settings from version 2 or earlier have their mappings reset because the gesture names changed.

**Shell commands are disabled by default.** Enable them under Settings → General only if you trust every command in your mappings.

### Action-only mode

For when you don't want the hand moving the cursor at all. Switch it in **Settings → Hands → Control mode: actions**, or from the tray icon's menu (**Action-only mode**). Either one takes effect straight away, with no Save needed. The hand never moves the cursor, clicks or scrolls; gestures only trigger actions. Every pose has to be held for 0.15 s (a slider under Gesture tuning), so a stray fist or pinch can't fire an action, and nothing happens at all while you just wave a relaxed hand about. Hold a thumb up or down to keep moving through tabs, one every 0.8 s.

One hand does the common ones:

| Gesture | Action |
|---|---|
| Pinch thumb + index | Screenshot |
| Fist | Voice typing |
| Thumbs up | Next tab (hold to keep going) |
| Thumbs down | Previous tab (hold to keep going) |
| Peace sign | Play/pause |
| "I love you" sign | Switch app |

The less common actions are on two hands, with the same five modes as cursor mode (the other hand holds a fist, thumbs up, peace sign, "I love you" or thumbs down) and the same main-hand gestures: copy, paste, undo, close tab, show desktop, lock screen and the rest. The one difference is thumbs inside Media mode, which are volume up and down, because thumbs are tab changes on their own here. The Gestures tab keeps a separate set of gestures for each control mode (pick which to edit at the top), so changing one never changes the other, and action-only mode never falls back to a cursor gesture.

## Settings window

Three tabs: **Preview** (camera picker and live image), **Gestures** (what each gesture does: Core, then one table per mode, for cursor mode or action-only mode) and **Settings**, with sub-tabs **Hands** (control mode, hand mode, main hand, each mode's pose), **Cursor**, **Gesture tuning** (sliders for the pinch threshold, hold times and scroll speed), **Monitors** and **General**. The Preview status line names the pose each hand is making, a live pinch number, and the mode that is active.

## If it doesn't pick up your hand

- Open the **Preview** tab: green dots should sit on your hand, and the status line names the pose it sees and a live pinch number. If a hand is doing nothing, check it isn't cut off by the picture's edge.
- Dots missing or flickering: add light (dim rooms blur a moving hand), keep the whole hand in frame, and move a little closer.
- Pinches not clicking, or clicking by accident: re-run the wizard's pinch step, or set **Pinch threshold** between the pinch numbers you see with fingers touching and with your hand open.

## Switching cameras

Pick a camera from the **Camera** dropdown at the top of the Preview tab; it switches immediately and the choice is saved. Cameras are listed as "Camera 0", "Camera 1" and so on, so the live preview tells you which is which. Plugged one in after launch? Press **Refresh**.

## Calibration

The wizard sets these for you; to adjust them by hand, use **Settings → Cursor**. The orange box on the **Preview** tab is the area that maps to your whole screen (all monitors); shrink it so you can reach every corner without stretching. If the cursor jitters when you hold still, lower **Steadiness**. If it lags behind fast moves, raise **Responsiveness**. The red circle on the preview is the point the cursor follows.

## Monitor switching

With two or more monitors, open **Settings → Monitors → Calibrate monitors**. A small window appears on each monitor in turn; look at it until it moves on. Afterwards your hand controls the monitor you are looking at, and the cursor jumps to the same spot on a monitor when you look across to it. Head turns and eye movement both count, and a quick glance doesn't trigger a switch: you have to keep looking for about half a second.

The camera has to see your face while you look at each monitor. A monitor you can only see by turning away from the camera is left out, and the calibration tells you so. Calibrate again after moving the camera or your monitors. Turn switching off with the checkbox on the same tab.

Settings are stored in `%APPDATA%\handctl\config.json`. You can edit it by hand (Notepad is fine). If it can't be parsed it is moved to `config.json.bak` and defaults are used, so a typo never crashes the app.

## If the cursor lags

- The delay between your hand and the cursor is the camera frame plus about 12 to 35 ms of hand tracking, plus the smoothing. Smoothing is the part you control: under **Settings → Cursor**, raise **Responsiveness** (and **Steadiness**) for less lag, lower them for less jitter. Simulated lag at 30 FPS for a slow hand movement: Steadiness 5 / Responsiveness 20 trails about 17 ms, 1 / 10 about 38 ms, 0.5 / 2 about 96 ms.
- **Hand mode: one** is the fastest setting (about 9 ms a frame faster than auto while two hands are in view).
- Keep the room lit: in dim light cameras drop their frame rate, which adds delay however fast the app is.
- Leaving the settings window open costs a little speed (it draws the preview 15 times a second).

## Tests

```powershell
.venv\Scripts\python -m pytest
```

## Building the installer

Needs PyInstaller in the venv and Inno Setup 6:

```powershell
.venv\Scripts\python -m pip install pyinstaller
```

```powershell
winget install JRSoftware.InnoSetup
```

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

It freezes the app, runs the frozen copy's self-check, and writes `build\installer\handctl-setup-<version>.exe`. The version comes from `pyproject.toml`.

## Roadmap

v1 is an early release: the gestures and defaults are not final.

**v2:** one or both hands, detection that works with a turned hand and any camera position, a Settings tab with sub-tabs and sliders, and a first-run setup wizard.

**v3 (this branch):** a Windows installer, and monitor switching by head and eye direction.

**v4:** recording custom poses, an optional second camera, voice commands, gesture profile import/export, macOS then Linux.

Full details are in [SPEC.md](SPEC.md).

## License

MIT. The MediaPipe models are Apache-2.0 (Google).
