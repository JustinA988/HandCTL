"""Executes Engine events on the real mouse and keyboard, and knows the monitor layout."""
import ctypes
import logging
import subprocess
from ctypes import wintypes

from pynput.keyboard import Controller as Keyboard, HotKey, Key
from pynput.mouse import Button, Controller as Mouse

mouse = Mouse()
keyboard = Keyboard()
CLICKS = {"right": Button.right, "middle": Button.middle}
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


_user32 = ctypes.WinDLL("user32")  # own copy, so the argtypes set below can't affect pynput's calls
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
for _f in ("SetForegroundWindow", "BringWindowToTop", "IsWindowVisible", "IsIconic", "GetWindowTextLengthW"):
    getattr(_user32, _f).argtypes = [wintypes.HWND]
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_SKIP_STYLES = 0x80 | 0x20 | 0x08000000  # tool windows, click-through overlays, windows that never take focus


def top_window(rect):
    """(handle, (left, top, right, bottom)) of the frontmost ordinary window centred on the monitor `rect`, or None."""
    # shortcut: Windows-only (EnumWindows lists top-level windows front to back); replace when porting to macOS/Linux
    found = []

    def visit(hwnd, _data):
        if (not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd) or not _user32.GetWindowTextLengthW(hwnd)
                or _user32.GetWindowLongW(hwnd, -20) & _SKIP_STYLES):  # -20: extended styles
            return 1
        cloaked = wintypes.DWORD()  # hidden store apps and windows on other virtual desktops report visible but cloaked
        ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(cloaked), 4)
        r = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(r))
        if not cloaked.value and monitor_at((r.left + r.right) // 2, (r.top + r.bottom) // 2, {"m": rect}):
            found.append((hwnd, (r.left, r.top, r.right, r.bottom)))
            return 0  # the frontmost one is enough
        return 1

    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows(callback(visit), 0)
    return found[0] if found else None


def bring_to_front(hwnd):
    """Give `hwnd` the keyboard: Windows then puts the typing cursor back in the box last used in that window.
    Windows only lets the app the user is using take focus, so this briefly joins that app's input queue."""
    front = _user32.GetForegroundWindow()
    if front == hwnd:
        return
    me = ctypes.windll.kernel32.GetCurrentThreadId()
    other = _user32.GetWindowThreadProcessId(front, None) if front else 0
    joined = other and other != me and _user32.AttachThreadInput(me, other, True)
    try:
        _user32.SetForegroundWindow(hwnd)
        _user32.BringWindowToTop(hwnd)
    finally:
        if joined:
            _user32.AttachThreadInput(me, other, False)


def look_at(name, focus=False):
    """Make `name` the monitor the hand controls and carry the cursor to the same relative spot on it.
    focus=True instead brings that monitor's front window to the front and puts the cursor in its middle, so typing and
    gestures go straight to what the user looks at.
    name None turns monitor switching off: the hand maps to the whole desktop again."""
    global active
    rects = monitors()
    if name not in rects:
        active = None
        return
    x, y = mouse.position
    old = active if active in rects.values() else rects.get(monitor_at(x, y, rects))
    active = rects[name]
    if focus:
        left, top, width, height = active
        window = top_window(active)
        if window:
            bring_to_front(window[0])
            wl, wt, wr, wb = window[1]  # its middle, kept on this monitor if the window spills over
            left, top, width, height = max(wl, left), max(wt, top), min(wr, left + width) - max(wl, left), min(wb, top + height) - max(wt, top)
        mouse.position = (left + width // 2, top + height // 2)
    elif old and old != active:
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
    elif kind == "hscroll":
        mouse.scroll(event[1], 0)
    elif kind == "zoom":  # Ctrl + wheel zooms in browsers, editors and most apps
        with keyboard.pressed(Key.ctrl):
            mouse.scroll(0, event[1])
    elif kind == "run":
        act = event[1]
        if act["type"] == "mouse" and act["value"] in CLICKS:
            mouse.click(CLICKS[act["value"]])
        elif act["type"] == "keys":
            press_combo(act["value"])
        elif act["type"] == "shell":
            if not cfg["shell_enabled"]:
                logging.warning("Shell command skipped (shell commands are disabled): %s", act["value"])
                return
            # detached, no console window, not waited on: launched apps must outlive this call
            subprocess.Popen(act["value"], shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
