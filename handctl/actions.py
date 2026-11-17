"""Executes Engine events on the real mouse and keyboard, and knows the monitor layout."""
import ctypes
import logging
import subprocess
from ctypes import wintypes

from pynput.keyboard import Controller as Keyboard, HotKey
from pynput.mouse import Button, Controller as Mouse

mouse = Mouse()
keyboard = Keyboard()
active = None  # rectangle of the monitor the hand controls; None = the whole desktop (monitor switching off)


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


def screen_rect():
    # shortcut: Windows-only virtual desktop (all monitors) query; replace when porting to macOS/Linux
    metric = ctypes.windll.user32.GetSystemMetrics
    return metric(76), metric(77), metric(78), metric(79)


def monitors():
    """{device name: (left, top, width, height)} for every monitor, in the same pixel units the mouse uses."""
    # shortcut: Windows-only (EnumDisplayMonitors); replace when porting to macOS/Linux
    user32 = ctypes.windll.user32
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]  # 64-bit handles must not be truncated
    found = {}

    def visit(handle, _dc, _rect, _data):
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            r = info.rcMonitor
            found[info.szDevice] = (r.left, r.top, r.right - r.left, r.bottom - r.top)
        return 1  # keep enumerating

    callback = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    user32.EnumDisplayMonitors(None, None, callback(visit), 0)
    return found


def monitor_at(x, y, rects):
    """Name of the monitor containing the point, or None."""
    return next((name for name, (l, t, w, h) in rects.items() if l <= x < l + w and t <= y < t + h), None)


def look_at(name):
    """Make `name` the monitor the hand controls and carry the cursor to the same relative spot on it.
    name None turns monitor switching off: the hand maps to the whole desktop again."""
    global active
    rects = monitors()
    if name not in rects:
        active = None
        return
    x, y = mouse.position
    old = active if active in rects.values() else rects.get(monitor_at(x, y, rects))
    active = rects[name]
    if old and old != active:
        fx = min(max((x - old[0]) / max(old[2] - 1, 1), 0.0), 1.0)
        fy = min(max((y - old[1]) / max(old[3] - 1, 1), 0.0), 1.0)
        mouse.position = (active[0] + round(fx * (active[2] - 1)), active[1] + round(fy * (active[3] - 1)))


def press_combo(combo):
    keys = HotKey.parse(combo)
    for k in keys:
        keyboard.press(k)
    for k in reversed(keys):
        keyboard.release(k)


def execute(event, cfg):
    kind = event[0]
    if kind == "move":
        left, top, width, height = active or screen_rect()
        mouse.position = (left + round(event[1] * (width - 1)), top + round(event[2] * (height - 1)))
    elif kind == "press":
        mouse.press(Button.left)
    elif kind == "release":
        mouse.release(Button.left)
    elif kind == "scroll":
        mouse.scroll(0, event[1])
    elif kind == "run":
        act = event[1]
        if act["type"] == "mouse" and act["value"] == "right":
            mouse.click(Button.right)
        elif act["type"] == "keys":
            press_combo(act["value"])
        elif act["type"] == "shell":
            if not cfg["shell_enabled"]:
                logging.warning("Shell command skipped (shell commands are disabled): %s", act["value"])
                return
            # detached, no console window, not waited on: launched apps must outlive this call
            subprocess.Popen(act["value"], shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
