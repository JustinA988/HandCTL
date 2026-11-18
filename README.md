# handctl

Control your Windows PC with your hands in front of a webcam: screenshots, voice typing, tabs, scrolling and media with simple hand signs, or, optionally, move and click the mouse. With several monitors, the one you look at gets the keyboard. Everything runs locally on the CPU. No network calls, no accounts.

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

Seven signs do everything: **open hand** (rest), **pinch**, **point**, **fist**, **thumbs up**, **thumbs down** and **peace sign**. Rest your elbow on the desk or chair arm and keep your hand low and relaxed; holding the arm up tires it within minutes. Your hand doesn't have to face the camera squarely: poses are read from the hand's 3D shape.

### Action mode (default)

Gestures trigger actions; the hand never moves the cursor. Simple actions are one sign. Ones with a direction are a pinch plus a move, like a touchpad swipe. Hold a sign for 0.15 s; a relaxed hand does nothing.

| Gesture | Action |
|---|---|
| Pinch thumb + index, then let go | Screenshot |
| Pinch and move left / right | Previous / next tab |
| Pinch and move up | Back to the last app |
| Pinch and move down | Show desktop |
| Point (index finger up) and move up / down | Scroll |
| Fist | Voice typing |
| Thumbs up / down (hold) | Volume up / down |
| Peace sign | Play/pause |

A pinch that moves is a swipe, not a screenshot. Each swipe does one thing; pinch again for another.

### Two hands: modes

Your **other hand** holds a sign like a Shift key; while it does, your **main hand** (right by default) does that mode's version of each sign. Let go and everything is back to normal. Anything a mode leaves out keeps its usual job.

| Main hand | Edit (other hand: fist) | Media (other hand: thumbs up) | Windows (other hand: peace sign) |
|---|---|---|---|
| Pinch | Copy | Play/pause | Switch app |
| Fist | Paste | Mute | Show desktop |
| Peace sign | Save | Next track | Task view |
| Thumbs up | Redo | (volume up) | Maximize |
| Thumbs down | Undo | (volume down) | Minimize |
| Pinch and move left / right | (tabs) | Previous / next track | Previous / next desktop |

### Cursor mode (optional)

Turn it on under **Settings → Hands → Control mode** or from the tray menu (it applies at once). The hand moves the cursor:

| Gesture | Action |
|---|---|
| Open hand, or pointing | Move cursor (it follows the centre of your palm) |
| Pinch | Left click; keep pinching and move = drag |
| Peace sign | Right click |
| Fist, move up/down | Scroll |
| Thumbs up / down (hold) | Volume up / down |

The same three modes work here, with a pinch acting straight away instead of when you let go.

### Why these signs

- **Thumb and index first.** The thumb and index finger move most independently of the others, while the middle and ring fingers drag their neighbours along ([Häger-Ross & Schieber 2000](https://www.jneurosci.org/content/jneuro/20/22/8542.full.pdf)). So the set leans on pinch and point, and leaves out the ring and middle pinches (which were also mistaken for the index pinch on the camera this was tested with) and the "I love you" sign.
- **Few signs, low and relaxed.** Mid-air input tires the arm fast ("gorilla arm"; [Hincapié-Ramos et al., CHI 2014](https://hci.cs.umanitoba.ca/publications/details/consumed-endurance-a-metric-to-quantify-arm-fatigue-of-mid-air-interactions)), so every gesture is a short sign or a small move made from a resting position, and a relaxed hand does nothing.
- **Pinch as the main input, pinch and move to swipe**, as on headsets that track hands ([Apple, WWDC24](https://developer.apple.com/videos/play/wwdc2024/10094/)).
- **Swipes follow the Windows touchpad:** down shows the desktop, sideways moves between things, and inside Windows mode sideways switches desktops as a four-finger swipe does ([Microsoft](https://support.microsoft.com/help/17206)). Swipe up goes back to the last app instead of opening task view, because task view needs a cursor.
- **Modes on the other hand.** In two-handed work the non-dominant hand sets the frame and the dominant hand does the detailed work ([Guiard 1987](https://web-archive.southampton.ac.uk/cogprints.org/625/)), so the other hand picks a mode with the three steadiest signs to hold (fist, thumbs up, peace sign) and the main hand reuses the same five signs in every mode.
- **Easy to remember:** thumbs mean up/down, a fist is a microphone grip (voice typing), swipes move between things.

### Changing them

Every gesture can be changed under the **Gestures** tab (one table for the core gestures and one per mode, for each control mode), and each mode's sign under Settings → Hands. **Reset gestures to defaults** brings back this set. Actions can be mouse actions (`move`, `left`, `right`, `middle`, `scroll`, `hscroll`, `zoom`), key combos (`<ctrl>+<alt>+t`, `<cmd>+d`, `<media_next>`, in [pynput's HotKey format](https://pynput.readthedocs.io/en/latest/keyboard.html#global-hotkeys)), or shell commands. The middle, ring and pinky pinches and "I love you" have empty slots to fill if they work well for you.

Settings from an earlier version get this set, except for any gesture you had changed yourself, which keeps your choice. The Browser and System modes are gone.

**Shell commands are disabled by default.** Enable them under Settings → General only if you trust every command in your mappings.

### How it avoids misfires

- A relaxed hand does nothing in action mode, and the cursor needs no special pose in cursor mode.
- A click lands where the cursor was just before your fingers closed, and the cursor holds still while you pinch.
- A pinch only ends when the fingers clearly part, and a straight finger is required to pinch, so a fist with the thumb against it isn't read as a pinch.
- A hand that vanishes for under 0.3 s (a tracking hiccup) changes nothing. Signs must be held briefly, and each action has a cooldown.
- A mode starts after its sign is held for 0.15 s and ends 0.25 s after you drop it.
- Phantom hands are ignored: small hand-shaped detections on your face or hairline, and hands cut off by the edge of the picture.
- If a second hand gets in the way (say, typing), set **Settings → Hands → Hand mode** to **one**: only one hand is tracked, and modes are off.

## Settings window

Three tabs: **Preview** (camera picker and live image), **Gestures** (what each gesture does: Core, then one table per mode, for action mode or cursor mode) and **Settings**, with sub-tabs **Hands** (control mode, hand mode, main hand, each mode's pose), **Cursor**, **Gesture tuning** (sliders for the pinch threshold, hold times and scroll speed), **Monitors** and **General**. The Preview status line names the pose each hand is making, a live pinch number, and the mode that is active.

## If it doesn't pick up your hand

- Open the **Preview** tab: green dots should sit on your hand, and the status line names the pose it sees and a live pinch number. If a hand is doing nothing, check it isn't cut off by the picture's edge.
- Dots missing or flickering: add light (dim rooms blur a moving hand), keep the whole hand in frame, and move a little closer.
- Pinches not clicking, or clicking by accident: re-run the wizard's pinch step, or set **Pinch threshold** between the pinch numbers you see with fingers touching and with your hand open.

## Switching cameras

Pick a camera from the **Camera** dropdown at the top of the Preview tab; it switches immediately and the choice is saved. Cameras are listed as "Camera 0", "Camera 1" and so on, so the live preview tells you which is which. Plugged one in after launch? Press **Refresh**.

## Calibration

The wizard sets these for you; to adjust them by hand, use **Settings → Cursor**. The orange box on the **Preview** tab is the area that maps to your whole screen (all monitors); shrink it so you can reach every corner without stretching. If the cursor jitters when you hold still, lower **Steadiness**. If it lags behind fast moves, raise **Responsiveness**. The red circle on the preview is the point the cursor follows.

## Monitor switching

With two or more monitors, open **Settings → Monitors → Calibrate monitors**. A small window appears on each monitor in turn; look at it until it moves on. Afterwards, keeping your eyes on a monitor for a moment makes it the one you control:

- **Bring its window to the front** (on by default): the front window on that monitor gets the keyboard, so you can just start typing (Windows puts you back in the text box you last used in that window), and the cursor moves to that window's middle. On a monitor with no open window the cursor goes to the monitor's middle. With it off, the cursor keeps the same relative spot.
- A switch waits until a gesture you are in the middle of is finished (a pinch, a swipe, a scroll, a held mode), so looking around while you gesture never pulls the cursor or keyboard away mid-gesture. Then it happens straight away.
- **Follow: eyes** (head turns and eye movement) or **head** (head turns only). Head is steadier if eye tracking keeps losing you, but you have to turn your head toward each monitor. One calibration records both; a calibration from before version 3.4 only has eyes, so calibrate once more to use head.
- **Your keyboard and other places to ignore.** Calibration ends by asking you to look at your keyboard; looking there never switches monitors (or pulls the keyboard focus away). **Add a place to ignore** records another one (a phone, notes, a second keyboard); **Clear places to ignore** removes them. Calibrations from before 3.5 have none, so calibrate once more.
- **Switch delay** (default 250 ms): how long a look must last. **Switch threshold** (default 0.75): lower needs a clearer look before it switches. Each reading is also the middle of the last three (the face is read ten times a second), so a blink or one bad reading is ignored.

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
