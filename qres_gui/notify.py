"""Telling the user about launcher problems without holding up the game.

Each problem is recorded in %APPDATA%\\QResGUI\\events.json (QRes GUI shows the
latest unseen one in a banner) and shown as a Windows toast notification.
Windows holds toasts back while a fullscreen game has focus and lists them in
the notification centre instead; the banner covers the case where they're
switched off. A message box is used only if a toast can't be shown at all.
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import subprocess
import time
import winreg
from xml.sax.saxutils import escape

from . import paths

log = logging.getLogger(__name__)

AUMID = "QResGUI"  # also set by the GUI process, so toasts and taskbar agree
AUMID_KEY = rf"Software\Classes\AppUserModelId\{AUMID}"
EVENTS_KEPT = 20
CREATE_NO_WINDOW = 0x08000000

# Windows PowerShell (5.1) can reach the WinRT toast API without extra packages.
_TOAST_SCRIPT = """
$ErrorActionPreference = 'Stop'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('{xml}')
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{aumid}').Show($toast)
"""


def notify(title: str, message: str, level: str = "warning", game_id: str | None = None) -> None:
    """Record a problem and show it as a toast (level: "warning" or "info")."""
    log.log(logging.INFO if level == "info" else logging.WARNING, "%s: %s", title, message)
    record(title, message, level, game_id)
    if not toast(title, message):
        _message_box(title, message, level)


# --- event record ----------------------------------------------------------

def events_path():
    return paths.app_dir() / "events.json"


def read_events() -> list[dict]:
    try:
        data = json.loads(events_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def record(title: str, message: str, level: str = "warning", game_id: str | None = None) -> None:
    events = read_events()[-(EVENTS_KEPT - 1):]
    events.append({"time": time.time(), "level": level, "title": title, "message": message, "game_id": game_id})
    path = events_path()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(events, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("couldn't record event: %s", exc)


# --- toast -----------------------------------------------------------------

def _icon_file() -> str:
    for candidate in (paths.app_folder() / "icon.png", paths.app_folder() / "build" / "icon.png"):
        if candidate.is_file():
            return str(candidate)
    return ""


def register_app() -> None:
    """Name and icon for our toasts; this key is how Windows identifies unpackaged apps."""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUMID_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "QRes GUI")
        icon = _icon_file()
        if icon:
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, icon)


def toast_xml(title: str, message: str) -> str:
    # &apos; keeps the XML safe inside the script's single-quoted string.
    def esc(text: str) -> str:
        return escape(text, {'"': "&quot;", "'": "&apos;"})
    return ('<toast><visual><binding template="ToastGeneric">'
            f"<text>{esc(title)}</text><text>{esc(message)}</text>"
            "</binding></visual></toast>")


def toast(title: str, message: str) -> bool:
    """Show a toast; False if Windows couldn't be asked to show it."""
    try:
        register_app()
        script = _TOAST_SCRIPT.format(xml=toast_xml(title, message), aumid=AUMID)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=20, creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("couldn't show a notification: %s", exc)
        return False
    if result.returncode != 0:
        log.warning("couldn't show a notification: %s", (result.stderr or result.stdout).strip()[:500])
        return False
    return True


def _message_box(title: str, message: str, level: str) -> None:
    MB_ICONINFORMATION, MB_ICONWARNING, MB_SETFOREGROUND, MB_TOPMOST = 0x40, 0x30, 0x10000, 0x40000
    icon = MB_ICONINFORMATION if level == "info" else MB_ICONWARNING
    ctypes.windll.user32.MessageBoxW(None, message, title, icon | MB_SETFOREGROUND | MB_TOPMOST)
