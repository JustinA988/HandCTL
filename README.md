# handctl

Control your Windows PC with one hand in front of a webcam: move and click the mouse, scroll, control media and switch desktops. Everything runs locally on the CPU. No network calls, no accounts.

## Install (from source)

Requires Windows 10/11, Python 3.12+ and a webcam. Commands are for Windows PowerShell and run from the project folder (the one containing `pyproject.toml`).

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Download MediaPipe's gesture model (Apache-2.0, ~8 MB) into `handctl/models/`:

```powershell
New-Item -ItemType Directory -Force handctl\models; Invoke-WebRequest https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task -OutFile handctl\models\gesture_recognizer.task
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

The first launch opens a setup wizard: pick your camera, mark the cursor area by pointing at two screen corners, calibrate the thumb tap, and try each gesture. Tracking stays off while it runs, so the cursor can't move. Re-run it any time from **Settings → General → Run setup wizard**.

## Default gestures

Rest your elbow on the desk and keep your hand low; holding your arm out at shoulder height tires it quickly. The set follows one rule, like a laptop trackpad: **1 finger** moves and taps to click, **2 fingers** scroll and tap to right-click, **3 fingers** swipe to switch desktops and tap to play/pause. Clicks are thumb taps, so the pointing finger doesn't move when you click. There's deliberately no flat open-palm pose: holding a palm toward the camera bends the wrist back and tires it.

| Gesture | Action |
|---|---|
| Point (index finger out) | Move cursor |
| Point + tap your thumb on the side of your index finger | Left click; keep the thumb down and move = drag |
| Two fingers out (index + middle), move up/down | Scroll |
| Two fingers + thumb tap | Right click |
| Three fingers out (index, middle, ring), short wrist swipe left/right | Previous/next virtual desktop |
| Three fingers + thumb tap | Play/pause |
| Thumbs up, raise/lower your hand | Volume up/down |
| Fist | Freeze the cursor ("lift the mouse") |

Anything else (a relaxed hand, an open hand) does nothing. Pinch and the "I love you" sign are unmapped but available. If thumb taps are unreliable on your camera, the wizard switches clicking to **Pinch** for you; you can also map it yourself.

### Two-hand mode

**Settings → Hands → Hand mode: two.** The *pointer hand* (right by default, swappable) only moves the cursor: point to move, fist to lift it. The *other hand* does everything else, including clicks, so the pointer hand never moves when you click, and holding a thumb tap with one hand while pointing with the other drags. Two hands run at about 20 FPS on a typical laptop CPU, against about 26 for one.

A pose must be held for 150 ms before it fires, and every action has a cooldown. Remap anything under **Settings → Gestures**: an action is a mouse action (`move`, `left`, `right`, `scroll`), a key combo (`<ctrl>+<alt>+t`, `<cmd>+d`, `<media_next>`, in [pynput's HotKey format](https://pynput.readthedocs.io/en/latest/keyboard.html#global-hotkeys)), a slider (two key combos `up,down`, fired as you raise or lower your hand), or a shell command.

Settings saved by v1 keep your camera and calibration, but their gesture mappings are reset to the v2 defaults because the gesture names changed.

**Shell commands are disabled by default.** Enable them under Settings → General only if you trust every command in your mappings.

## Settings window

Three tabs: **Preview** (camera picker and live image), **Gestures** (what each gesture does) and **Settings**, with sub-tabs **Hands**, **Cursor**, **Gesture tuning** (sliders for the thumb tap and pinch thresholds, hold times and scroll speed) and **General**.

## Switching cameras

Pick a camera from the **Camera** dropdown at the top of the Preview tab; it switches immediately and the choice is saved. Cameras are listed as "Camera 0", "Camera 1" and so on, so the live preview tells you which is which. Plugged one in after launch? Press **Refresh**.

## Calibration

The wizard sets these for you; to adjust them by hand, use **Settings → Cursor**. The orange box on the **Preview** tab is the area that maps to your whole screen (all monitors); shrink it so you can reach every corner without stretching. If the cursor jitters when you hold still, lower **Steadiness**. If it lags behind fast moves, raise **Responsiveness**. Under **Gesture tuning**, raise the **thumb tap threshold** if taps don't register, or lower it if clicks fire by accident.

**Cursor mode:** *absolute* (default) maps the box to the screen. *Relative* works like a trackpad: pointing moves the cursor from where it is, **Relative speed** sets how far, and a fist lets you move your hand back without moving the cursor.

Settings are stored in `%APPDATA%\handctl\config.json`. If that file is unreadable it is moved to `config.json.bak` and defaults are used.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

## Roadmap

v1 is an early release: the gestures and defaults are not final.

**v2 (this branch):** single-hand or two-hand mode, an ergonomic gesture set, a Settings tab with sub-tabs and sliders, a relative cursor mode, and a first-run setup wizard.

**v3:** a Windows installer, and monitor switching by head and eye direction.

**v4:** recording custom poses, an optional second camera, voice commands, gesture profile import/export, macOS then Linux.

Full details are in [SPEC.md](SPEC.md).

## License

MIT. The MediaPipe model is Apache-2.0 (Google).
