"""System-wide hotkeys on Windows (RegisterHotKey + WM_HOTKEY).

Hotkeys are stored as the strings QKeySequenceEdit produces, e.g. "Ctrl+Alt+1".
A manager registers them against the main window and calls a handler when one
is pressed, so they work even when the window is hidden.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

log = logging.getLogger(__name__)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
WM_HOTKEY = 0x0312

_MODIFIERS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
    "meta": MOD_WIN, "win": MOD_WIN, "super": MOD_WIN, "cmd": MOD_WIN,
}
_NAMED_KEYS = {
    "space": 0x20, "home": 0x24, "end": 0x23, "insert": 0x2D, "ins": 0x2D, "delete": 0x2E, "del": 0x2E,
    "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdown": 0x22, "pgdn": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "tab": 0x09, "return": 0x0D, "enter": 0x0D,
    "backspace": 0x08, "esc": 0x1B, "escape": 0x1B,
}


def parse(sequence: str) -> tuple[int, int] | None:
    """"Ctrl+Alt+1" -> (modifier flags, virtual-key code). None if unusable.

    A plain key with no modifier is rejected: registering it system-wide would
    swallow that key everywhere.
    """
    tokens = [t.strip() for t in str(sequence).split("+") if t.strip()]
    if not tokens:
        return None
    mods, vk = 0, None
    for token in tokens:
        low = token.lower()
        if low in _MODIFIERS:
            mods |= _MODIFIERS[low]
        elif vk is not None:
            return None  # more than one non-modifier key
        elif len(token) == 1 and token.isascii() and token.isalnum():
            vk = ord(token.upper())  # VK codes for A-Z / 0-9 equal their ASCII values
        elif low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
            vk = 0x70 + int(low[1:]) - 1
        elif low in _NAMED_KEYS:
            vk = _NAMED_KEYS[low]
        else:
            return None
    if vk is None or mods == 0:
        return None
    return mods, vk


class HotkeyManager(QAbstractNativeEventFilter):
    """Registers hotkeys against a window and runs a callback when one fires."""

    def __init__(self, hwnd: int, on_pressed):
        super().__init__()
        self.hwnd = wintypes.HWND(hwnd)
        self.on_pressed = on_pressed
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._registered: list[int] = []

    def apply(self, bindings: dict[int, str]) -> dict[int, str]:
        """Register {id: sequence}; returns {id: sequence} for the ones that failed."""
        self.clear()
        failed = {}
        for hotkey_id, sequence in bindings.items():
            parsed = parse(sequence)
            if parsed is None:
                failed[hotkey_id] = sequence
                continue
            mods, vk = parsed
            if self.user32.RegisterHotKey(self.hwnd, hotkey_id, mods | MOD_NOREPEAT, vk):
                self._registered.append(hotkey_id)
            else:
                failed[hotkey_id] = sequence
                log.warning("couldn't register hotkey %s (id %d): %s", sequence, hotkey_id,
                            ctypes.WinError(ctypes.get_last_error()))
        return failed

    def clear(self) -> None:
        for hotkey_id in self._registered:
            self.user32.UnregisterHotKey(self.hwnd, hotkey_id)
        self._registered = []

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_HOTKEY:
                self.on_pressed(int(msg.wParam))
        return False, 0
