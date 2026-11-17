"""Executes Engine events on the real mouse and keyboard."""
import ctypes
import logging
import subprocess

from pynput.keyboard import Controller as Keyboard, HotKey
from pynput.mouse import Button, Controller as Mouse

mouse = Mouse()
keyboard = Keyboard()


def screen_rect():
    # shortcut: Windows-only virtual desktop (all monitors) query; replace when porting to macOS/Linux
    metric = ctypes.windll.user32.GetSystemMetrics
    return metric(76), metric(77), metric(78), metric(79)


def press_combo(combo):
    keys = HotKey.parse(combo)
    for k in keys:
        keyboard.press(k)
    for k in reversed(keys):
        keyboard.release(k)


def execute(event, cfg):
    kind = event[0]
    if kind == "move":
        left, top, width, height = screen_rect()
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
