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

Raise your hand in view of the camera with your elbow resting on the desk or chair arm; holding your whole arm out tires it quickly. Your hand doesn't have to face the camera squarely: poses are read from the hand's 3D shape, and the camera can sit above, below or beside the screen.

| Gesture | Action |
|---|---|
| Any open or relaxed hand | Move cursor (it follows the centre of your palm) |
| Pinch thumb + index fingertip | Left click; keep pinching and move = drag |
| Pinch thumb + middle fingertip | Right click |
| Fist, move up/down | Scroll |
| Thumbs up / thumbs down (hold) | Volume up / down |
| Peace sign | Play/pause |
| "I love you" sign | Task view (pick a window or desktop from there) |

How it avoids misfires and missed input:
- The cursor needs no special pose, so it can't be "lost" by a finger out of place.
- A click lands where the cursor was just before your fingers closed, and the cursor holds still while you pinch.
- A pinch only ends when the fingers clearly part, so drags don't drop. A hand that vanishes for under 0.3 s (a tracking hiccup) changes nothing.
- Fist, thumbs and the signs must be held for a quarter second before they act, and each action has a cooldown.

### Using both hands

Both hands are tracked automatically. With one hand in view, it does everything. With both in view, the *pointer hand* (right by default; change it under **Settings → Hands**) only moves the cursor, whatever shape it makes, and the *other hand* does everything else. That way the pointer never moves when you click, and pinching with one hand while moving the other drags. A hand that drops out of view for a moment doesn't change who does what, and a drag in progress is never cut off by the other hand appearing. Hands are told apart by where they are in the picture, not by MediaPipe's left/right guess, which flips when a hand turns sideways.

If a second hand gets in the way (for example while typing), set **Settings → Hands → Hand mode** to **one**: only one hand is ever tracked.

Remap anything under the **Gestures** tab: an action is a mouse action (`move`, `left`, `right`, `scroll`), a key combo (`<ctrl>+<alt>+t`, `<cmd>+d`, `<media_next>`, in [pynput's HotKey format](https://pynput.readthedocs.io/en/latest/keyboard.html#global-hotkeys)), or a shell command.

Settings saved by an earlier version keep your camera and calibration, but their gesture mappings are reset to the current defaults because the gesture names changed.

**Shell commands are disabled by default.** Enable them under Settings → General only if you trust every command in your mappings.

## Settings window

Three tabs: **Preview** (camera picker and live image), **Gestures** (what each gesture does) and **Settings**, with sub-tabs **Hands**, **Cursor**, **Gesture tuning** (sliders for the pinch threshold, hold times and scroll speed) and **General**.

## If it doesn't pick up your hand

- Open the **Preview** tab: green dots should sit on your hand, and the status line names the pose it sees and a live pinch number.
- Dots missing or flickering: add light (dim rooms blur a moving hand), keep the whole hand in frame, and move a little closer.
- Pinches not clicking, or clicking by accident: re-run the wizard's pinch step, or set **Pinch threshold** between the pinch numbers you see with fingers touching and with your hand open.

## Switching cameras

Pick a camera from the **Camera** dropdown at the top of the Preview tab; it switches immediately and the choice is saved. Cameras are listed as "Camera 0", "Camera 1" and so on, so the live preview tells you which is which. Plugged one in after launch? Press **Refresh**.

## Calibration

The wizard sets these for you; to adjust them by hand, use **Settings → Cursor**. The orange box on the **Preview** tab is the area that maps to your whole screen (all monitors); shrink it so you can reach every corner without stretching. If the cursor jitters when you hold still, lower **Steadiness**. If it lags behind fast moves, raise **Responsiveness**. The red circle on the preview is the point the cursor follows.

## Monitor switching

With two or more monitors, open **Settings → Monitors → Calibrate monitors**. A small window appears on each monitor in turn; look at it until it moves on. Afterwards your hand controls the monitor you are looking at, and the cursor jumps to the same spot on a monitor when you look across to it. Head turns and eye movement both count, and a quick glance doesn't trigger a switch: you have to keep looking for about half a second.

The camera has to see your face while you look at each monitor. A monitor you can only see by turning away from the camera is left out, and the calibration tells you so. Calibrate again after moving the camera or your monitors. Turn switching off with the checkbox on the same tab.

Settings are stored in `%APPDATA%\handctl\config.json`. If that file is unreadable it is moved to `config.json.bak` and defaults are used.

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
