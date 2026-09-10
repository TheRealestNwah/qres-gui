"""Reading and changing the primary display's resolution.

Mode changes go through QRes.exe. The Windows API is used directly only as a
fallback, so that switching back can't fail just because QRes went missing.
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)

ENUM_CURRENT_SETTINGS = 0xFFFFFFFF
DM_BITSPERPEL = 0x00040000
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000
CDS_UPDATEREGISTRY = 0x00000001
DISP_CHANGE_SUCCESSFUL = 0
CREATE_NO_WINDOW = 0x08000000


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


assert ctypes.sizeof(DEVMODEW) == 220

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
_user32.EnumDisplaySettingsW.restype = wintypes.BOOL
_user32.ChangeDisplaySettingsExW.argtypes = [
    wintypes.LPCWSTR, ctypes.POINTER(DEVMODEW), wintypes.HWND, wintypes.DWORD, ctypes.c_void_p,
]
_user32.ChangeDisplaySettingsExW.restype = ctypes.c_long


class DisplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    refresh: int

    def __str__(self) -> str:
        return f"{self.width} × {self.height} @ {self.refresh} Hz"

    @property
    def size_text(self) -> str:
        return f"{self.width} × {self.height}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Mode":
        return cls(int(data["width"]), int(data["height"]), int(data.get("refresh") or 0))


def _devmode(index: int) -> DEVMODEW | None:
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    if not _user32.EnumDisplaySettingsW(None, index, ctypes.byref(dm)):
        return None
    return dm


def current_mode() -> Mode:
    dm = _devmode(ENUM_CURRENT_SETTINGS)
    if dm is None:
        raise DisplayError("Couldn't read the current display mode.")
    return Mode(dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency)


def list_modes() -> list[Mode]:
    """All 32-bit modes of the primary display, largest resolution first."""
    modes: set[Mode] = set()
    index = 0
    while (dm := _devmode(index)) is not None:
        if dm.dmBitsPerPel == 32:
            modes.add(Mode(dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency))
        index += 1
    return sorted(modes, key=lambda m: (m.width * m.height, m.width, m.refresh), reverse=True)


def refresh_rates(width: int, height: int, modes: list[Mode] | None = None) -> list[int]:
    modes = list_modes() if modes is None else modes
    return sorted({m.refresh for m in modes if (m.width, m.height) == (width, height)}, reverse=True)


def resolve(width: int, height: int, refresh: int, desktop: Mode) -> Mode:
    """Pick the concrete mode for a profile. refresh=0 means "same as desktop"."""
    rates = refresh_rates(width, height)
    if refresh and (refresh in rates or not rates):
        return Mode(width, height, refresh)
    if desktop.refresh in rates or not rates:
        return Mode(width, height, desktop.refresh)
    return Mode(width, height, rates[0])


def find_qres(configured: str | None = None) -> str | None:
    for candidate in (configured, shutil.which("QRes.exe"), shutil.which("qres")):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _wait_for(mode: Mode, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if current_mode() == mode:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def _set_with_qres(mode: Mode, qres: str, temporary: bool) -> str:
    args = [qres, f"/X:{mode.width}", f"/Y:{mode.height}", f"/R:{mode.refresh}", "/V"]
    if temporary:
        args.append("/D")
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=20, creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"couldn't run QRes: {exc}"
    return " ".join((result.stdout + result.stderr).split())


def _set_with_api(mode: Mode, temporary: bool) -> int:
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency = mode.width, mode.height, mode.refresh
    dm.dmBitsPerPel = 32
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY | DM_BITSPERPEL
    flags = 0 if temporary else CDS_UPDATEREGISTRY
    return _user32.ChangeDisplaySettingsExW(None, ctypes.byref(dm), None, flags, None)


def set_mode(mode: Mode, qres: str | None, temporary: bool = True) -> str:
    """Switch the primary display to `mode`; returns which method worked."""
    if current_mode() == mode:
        return "already set"
    if qres:
        output = _set_with_qres(mode, qres, temporary)
        if _wait_for(mode):
            return "QRes"
        log.warning("QRes didn't switch to %s (%s); falling back to the Windows API", mode, output)
    code = _set_with_api(mode, temporary)
    if code == DISP_CHANGE_SUCCESSFUL and _wait_for(mode):
        return "Windows API"
    raise DisplayError(f"Couldn't switch the display to {mode} (ChangeDisplaySettings returned {code}).")
