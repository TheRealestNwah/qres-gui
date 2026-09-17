"""Starting QRes GUI with Windows, in the tray.

A value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run - the
same place Settings › Apps › Startup lists and switches off. It always names
the installed copy when there is one, like the hooks do, so an unzipped copy
can't leave a startup entry pointing at a folder that later disappears.
"""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

from . import paths

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "QRes GUI"
TRAY_FLAG = "--tray"


def target() -> Path | None:
    """The QRes GUI exe a startup entry should run, or None when there's no built copy (a source checkout)."""
    installed = paths.installed_folder() / "QResGUI.exe"
    if installed.is_file():
        return installed
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return None


def command() -> str | None:
    exe = target()
    return f'"{exe}" {TRAY_FLAG}' if exe else None


def current() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE)
            return str(value)
    except OSError:
        return None


def enabled() -> bool:
    return current() is not None


def set_enabled(on: bool) -> bool:
    """Add or remove the startup entry; returns whether it's now as asked. Never raises."""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if on:
                cmd = command()
                if not cmd:
                    return False
                winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
