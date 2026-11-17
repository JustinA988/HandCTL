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

## Default gestures

| Gesture | Action |
|---|---|
| Point index finger up | Move cursor |
| Pinch thumb + index | Left click; hold 300 ms then move = drag |
| Pinch thumb + middle | Right click |
| Two fingers (victory) + move up/down | Scroll |
| Open palm, swipe left/right | Previous/next virtual desktop |
| Fist | Play/pause |
| Thumbs up / down (hold) | Volume up / down |
| "I love you" sign | Task view |

A pose must be held for 150 ms before it fires, and every action has a cooldown. Remap anything under **Settings → Gestures**: an action is a mouse action (`move`, `left`, `right`, `scroll`), a key combo (`<ctrl>+<alt>+t`, `<cmd>+d`, `<media_next>`, in [pynput's HotKey format](https://pynput.readthedocs.io/en/latest/keyboard.html#global-hotkeys)), or a shell command.

**Shell commands are disabled by default.** Enable them under Settings → General only if you trust every command in your mappings.

## Switching cameras

Pick a camera from the **Camera** dropdown at the top of the Preview tab; it switches immediately and the choice is saved. Cameras are listed as "Camera 0", "Camera 1" and so on, so the live preview tells you which is which. Plugged one in after launch? Press **Refresh**.

## Calibration

Under **Preview & calibration**, the orange box on the camera preview is the area that maps to your whole screen (all monitors). Shrink it so you can reach every corner without stretching. If the cursor jitters when you hold still, lower **Steadiness**. If it lags behind fast moves, raise **Responsiveness**. Adjust the pinch threshold if clicks fire too easily or not at all.

Settings are stored in `%APPDATA%\handctl\config.json`. If that file is unreadable it is moved to `config.json.bak` and defaults are used.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

## Roadmap

v1 is an early release: the gestures and defaults are not final.

**v2:** single-hand or two-hand mode (one hand moves the cursor, the other triggers actions, with a setting to swap them), new ergonomic gestures replacing the current set, a Settings tab with sub-tabs and sliders, and a first-run calibration wizard.

**v3:** a Windows installer, and monitor switching by head and eye direction.

**v4:** recording custom poses, an optional second camera, voice commands, gesture profile import/export, macOS then Linux.

Full details are in [SPEC.md](SPEC.md).

## License

MIT. The MediaPipe model is Apache-2.0 (Google).
