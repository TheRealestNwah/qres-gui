r"""Reading and changing a display's resolution.

Every function here takes an optional `device` - the \\.\DISPLAYn name from
`list_displays()` - and defaults to the primary display when it's None, which
is what the whole app did before it could target a second screen.

Mode changes go through QRes.exe. The Windows API is used directly as a
fallback, so that switching back can't fail just because QRes went missing,
and for any display that isn't the primary one: QRes has no monitor switch, so
it can only ever drive the primary.
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

from . import paths

log = logging.getLogger(__name__)

ENUM_CURRENT_SETTINGS = 0xFFFFFFFF
DM_BITSPERPEL = 0x00040000
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000
CDS_UPDATEREGISTRY = 0x00000001
DISP_CHANGE_SUCCESSFUL = 0
CREATE_NO_WINDOW = 0x08000000

DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
DISPLAY_DEVICE_MIRRORING_DRIVER = 0x00000008


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


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128),
    ]


assert ctypes.sizeof(DEVMODEW) == 220
assert ctypes.sizeof(DISPLAY_DEVICEW) == 840

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
_user32.EnumDisplaySettingsW.restype = wintypes.BOOL
_user32.ChangeDisplaySettingsExW.argtypes = [
    wintypes.LPCWSTR, ctypes.POINTER(DEVMODEW), wintypes.HWND, wintypes.DWORD, ctypes.c_void_p,
]
_user32.ChangeDisplaySettingsExW.restype = ctypes.c_long
_user32.EnumDisplayDevicesW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DISPLAY_DEVICEW), wintypes.DWORD,
]
_user32.EnumDisplayDevicesW.restype = wintypes.BOOL


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


def device_number(device: str) -> str:
    r"""The n from \\.\DISPLAYn, for short labels."""
    return (device or "").rsplit("DISPLAY", 1)[-1] or "?"


@dataclass(frozen=True)
class Display:
    device: str    # \\.\DISPLAYn, the name every function here takes
    name: str      # the monitor's own name, for people
    primary: bool

    def __str__(self) -> str:
        return self.label

    @property
    def number(self) -> str:
        return device_number(self.device)

    @property
    def label(self) -> str:
        """Includes the number, because two identical monitors report the same name."""
        return f"Display {self.number}: {self.name}" + ("  (primary)" if self.primary else "")


def _devmode(index: int, device: str | None = None) -> DEVMODEW | None:
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    if not _user32.EnumDisplaySettingsW(device, index, ctypes.byref(dm)):
        return None
    return dm


def _display_device(device: str | None, index: int) -> DISPLAY_DEVICEW | None:
    entry = DISPLAY_DEVICEW()
    entry.cb = ctypes.sizeof(DISPLAY_DEVICEW)  # wanted on every call, not just the first
    if not _user32.EnumDisplayDevicesW(device, index, ctypes.byref(entry), 0):
        return None
    return entry


def list_displays() -> list[Display]:
    r"""Every display making up the desktop, the primary one first.

    The adapter entry carries the \\.\DISPLAYn name the rest of this module
    works in; the monitor attached to it carries a name worth showing someone.
    """
    displays: list[Display] = []
    index = 0
    while (adapter := _display_device(None, index)) is not None:
        index += 1
        # Detached outputs and the mirroring pseudo-drivers some capture tools
        # install aren't displays anyone means.
        if not adapter.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            continue
        if adapter.StateFlags & DISPLAY_DEVICE_MIRRORING_DRIVER:
            continue
        monitor = _display_device(adapter.DeviceName, 0)
        name = (monitor.DeviceString if monitor else "") or adapter.DeviceString or adapter.DeviceName
        displays.append(Display(adapter.DeviceName, name,
                                bool(adapter.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE)))
    return sorted(displays, key=lambda d: not d.primary)


def primary_device() -> str | None:
    r"""The \\.\DISPLAYn of the primary display, or None if Windows doesn't say."""
    return next((d.device for d in list_displays() if d.primary), None)


def find_display(device: str | None) -> Display | None:
    """The named display, or None if it isn't attached right now.

    Deliberately not falling back to the primary: switching a screen the user
    didn't name is worse than not switching at all.
    """
    if not device:
        return next((d for d in list_displays() if d.primary), None)
    return next((d for d in list_displays() if d.device == device), None)


def current_mode(device: str | None = None) -> Mode:
    dm = _devmode(ENUM_CURRENT_SETTINGS, device)
    if dm is None:
        raise DisplayError(f"Couldn't read the current mode of {device or 'the primary display'}.")
    return Mode(dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency)


def list_modes(device: str | None = None) -> list[Mode]:
    """All 32-bit modes of a display, largest resolution first."""
    modes: set[Mode] = set()
    index = 0
    while (dm := _devmode(index, device)) is not None:
        if dm.dmBitsPerPel == 32:
            modes.add(Mode(dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency))
        index += 1
    return sorted(modes, key=lambda m: (m.width * m.height, m.width, m.refresh), reverse=True)


def refresh_rates(width: int, height: int, modes: list[Mode] | None = None,
                  device: str | None = None) -> list[int]:
    modes = list_modes(device) if modes is None else modes
    return sorted({m.refresh for m in modes if (m.width, m.height) == (width, height)}, reverse=True)


def available_sizes(modes: list[Mode] | None = None, device: str | None = None) -> list[tuple[int, int]]:
    """(width, height) pairs Windows currently offers for a display, largest first."""
    modes = list_modes(device) if modes is None else modes
    return list(dict.fromkeys((m.width, m.height) for m in modes))


def is_size_available(width: int, height: int, modes: list[Mode] | None = None,
                      device: str | None = None) -> bool:
    """Whether Windows offers this resolution. A custom resolution not yet created won't switch."""
    return (width, height) in available_sizes(modes, device)


def resolve(width: int, height: int, refresh: int, desktop: Mode, device: str | None = None) -> Mode:
    """Pick the concrete mode for a profile. refresh=0 means "same as desktop"."""
    rates = refresh_rates(width, height, device=device)
    if refresh and (refresh in rates or not rates):
        return Mode(width, height, refresh)
    if desktop.refresh in rates or not rates:
        return Mode(width, height, desktop.refresh)
    return Mode(width, height, rates[0])


def find_qres(configured: str | None = None) -> str | None:
    """The configured QRes.exe, else one on PATH, else one dropped next to the app."""
    bundled = os.path.join(paths.app_folder(), "QRes.exe")
    for candidate in (configured, shutil.which("QRes.exe"), bundled):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _wait_for(mode: Mode, device: str | None = None, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if current_mode(device) == mode:
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


def _set_with_api(mode: Mode, temporary: bool, device: str | None = None) -> int:
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency = mode.width, mode.height, mode.refresh
    dm.dmBitsPerPel = 32
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY | DM_BITSPERPEL
    flags = 0 if temporary else CDS_UPDATEREGISTRY
    return _user32.ChangeDisplaySettingsExW(device, ctypes.byref(dm), None, flags, None)


def drives_primary(device: str | None) -> bool:
    """Whether `device` means the primary display - which is the only one QRes can switch."""
    return device is None or device == primary_device()


def set_mode(mode: Mode, qres: str | None, temporary: bool = True, device: str | None = None) -> str:
    """Switch `device` (default: the primary display) to `mode`; returns which method worked.

    QRes v1.1 takes no monitor argument, so it can only ever drive the primary
    display. For any other one the Windows API - which is per-device - is the
    only route, and the QRes step is skipped rather than aimed at the wrong
    screen.
    """
    if current_mode(device) == mode:
        return "already set"
    if qres and drives_primary(device):
        output = _set_with_qres(mode, qres, temporary)
        if _wait_for(mode, device):
            return "QRes"
        log.warning("QRes didn't switch to %s (%s); falling back to the Windows API", mode, output)
    code = _set_with_api(mode, temporary, device)
    if code == DISP_CHANGE_SUCCESSFUL and _wait_for(mode, device):
        return "Windows API"
    where = "" if drives_primary(device) else f" on {device}"
    raise DisplayError(
        f"Couldn't switch the display to {mode}{where} (ChangeDisplaySettings returned {code}).")
