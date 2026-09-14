"""Turning HDR on and off on a display.

QRes can't do this: HDR lives behind a different Windows API (the
DisplayConfig one, Windows 10 1709 and later), so it gets its own module.
Like `display`, every entry point takes an optional `device` and falls back to
the primary one, so HDR and the resolution always land on the same screen.

Everything here is best-effort and never guesses. `status()` reports whether
that display can do HDR at all and what it's doing right now, with a
plain-English `reason` when it can't, so the GUI can grey the control out and
say why. Nothing in here may stop a game from starting: callers are expected
to catch `HdrError` and carry on.
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass

from . import display

log = logging.getLogger(__name__)

QDC_ONLY_ACTIVE_PATHS = 0x00000002
ERROR_INSUFFICIENT_BUFFER = 122
CCHDEVICENAME = 32

GET_SOURCE_NAME = 1
GET_ADVANCED_COLOR_INFO = 9
SET_ADVANCED_COLOR_STATE = 10

# Bits of DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO's value union.
COLOR_SUPPORTED = 0x1
COLOR_ENABLED = 0x2
COLOR_FORCE_DISABLED = 0x8

# A display re-syncs when HDR is switched, which blanks it for a moment. Wait
# that out so whatever happens next (a resolution change, the game starting)
# doesn't land mid-handshake.
SETTLE = 2.0

NO_API = "This version of Windows doesn't have the HDR display setting (Windows 10 1709 or newer)."
NO_CONFIG = "Windows didn't report the display configuration."
NO_DISPLAY = "That display isn't connected right now."
NO_SUPPORT = "Your primary display doesn't report HDR support."
FORCED_OFF = "Windows has HDR switched off for this display; turn it on in Settings › System › Display › HDR."


class HdrError(RuntimeError):
    pass


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD), ("size", wintypes.DWORD), ("adapterId", LUID), ("id", wintypes.DWORD),
    ]


class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wintypes.DWORD), ("Denominator", wintypes.DWORD)]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID), ("id", wintypes.DWORD),
        ("modeInfoIdx", wintypes.DWORD), ("statusFlags", wintypes.DWORD),
    ]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID), ("id", wintypes.DWORD), ("modeInfoIdx", wintypes.DWORD),
        ("outputTechnology", wintypes.DWORD), ("rotation", wintypes.DWORD), ("scaling", wintypes.DWORD),
        ("refreshRate", DISPLAYCONFIG_RATIONAL), ("scanLineOrdering", wintypes.DWORD),
        ("targetAvailable", wintypes.BOOL), ("statusFlags", wintypes.DWORD),
    ]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", wintypes.DWORD),
    ]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    """QueryDisplayConfig insists on the modes array; HDR never reads it, so the
    union of source / target / desktop-image modes is carried as opaque bytes."""

    _fields_ = [
        ("infoType", wintypes.DWORD), ("id", wintypes.DWORD), ("adapterId", LUID),
        ("mode", ctypes.c_uint64 * 6),
    ]


class DISPLAYCONFIG_SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("viewGdiDeviceName", wintypes.WCHAR * CCHDEVICENAME),
    ]


class DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value", wintypes.DWORD),  # the COLOR_* bits above
        ("colorEncoding", wintypes.DWORD), ("bitsPerColorChannel", wintypes.DWORD),
    ]


class DISPLAYCONFIG_SET_ADVANCED_COLOR_STATE(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value", wintypes.DWORD),  # bit 0: turn advanced colour (HDR) on
    ]


assert ctypes.sizeof(DISPLAYCONFIG_PATH_INFO) == 72
assert ctypes.sizeof(DISPLAYCONFIG_MODE_INFO) == 64
assert ctypes.sizeof(DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO) == 32

try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetDisplayConfigBufferSizes.argtypes = [
        wintypes.DWORD, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT),
    ]
    _user32.GetDisplayConfigBufferSizes.restype = wintypes.LONG
    _user32.QueryDisplayConfig.argtypes = [
        wintypes.DWORD, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(DISPLAYCONFIG_PATH_INFO),
        ctypes.POINTER(wintypes.UINT), ctypes.POINTER(DISPLAYCONFIG_MODE_INFO), ctypes.c_void_p,
    ]
    _user32.QueryDisplayConfig.restype = wintypes.LONG
    _user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
    _user32.DisplayConfigGetDeviceInfo.restype = wintypes.LONG
    _user32.DisplayConfigSetDeviceInfo.argtypes = [ctypes.c_void_p]
    _user32.DisplayConfigSetDeviceInfo.restype = wintypes.LONG
    _HAVE_API = True
except (AttributeError, OSError):  # a Windows too old to have DisplayConfig at all
    _HAVE_API = False


@dataclass(frozen=True)
class Status:
    """What HDR is doing on the primary display."""

    supported: bool = False  # QRes GUI can switch HDR here
    enabled: bool = False    # HDR is on right now
    reason: str = ""         # empty when supported; otherwise why not, for the GUI


# --- talking to Windows ----------------------------------------------------

def _active_paths() -> list[DISPLAYCONFIG_PATH_INFO]:
    """Every active source-to-display path. Empty if Windows wouldn't say."""
    for _ in range(2):  # the config can change between sizing and querying; one retry is enough
        paths_n, modes_n = wintypes.UINT(), wintypes.UINT()
        code = _user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS,
                                                   ctypes.byref(paths_n), ctypes.byref(modes_n))
        if code:
            log.info("GetDisplayConfigBufferSizes failed (%d)", code)
            return []
        paths = (DISPLAYCONFIG_PATH_INFO * paths_n.value)()
        modes = (DISPLAYCONFIG_MODE_INFO * modes_n.value)()
        code = _user32.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(paths_n), paths,
                                          ctypes.byref(modes_n), modes, None)
        if code == 0:
            return list(paths[:paths_n.value])
        if code != ERROR_INSUFFICIENT_BUFFER:
            log.info("QueryDisplayConfig failed (%d)", code)
            return []
    return []


def _source_name(path: DISPLAYCONFIG_PATH_INFO) -> str:
    request = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
    request.header.type = GET_SOURCE_NAME
    request.header.size = ctypes.sizeof(request)
    request.header.adapterId = path.sourceInfo.adapterId
    request.header.id = path.sourceInfo.id
    if _user32.DisplayConfigGetDeviceInfo(ctypes.byref(request)):
        return ""
    return request.viewGdiDeviceName


def _target_for(device: str | None) -> tuple[LUID, int] | None:
    """(adapter, target id) of the output driving `device`, or the primary display."""
    paths = _active_paths()
    if not paths:
        return None
    wanted = device or display.primary_device() or ""
    for path in paths:
        if not wanted or _source_name(path) == wanted:
            return path.targetInfo.adapterId, path.targetInfo.id
    if device:
        # An explicitly named display we can't find is never worth guessing at:
        # switching HDR on the wrong screen is the thing this is meant to stop.
        log.info("no display-config path matches %s", device)
        return None
    # Windows named a primary we couldn't match; the first active path is the
    # best remaining guess, and on a single-display PC it is the right one.
    log.info("no display-config path matches the primary display %s; using the first active one", wanted)
    return paths[0].targetInfo.adapterId, paths[0].targetInfo.id


def _probe(device: str | None = None) -> tuple[Status, tuple[LUID, int] | None]:
    if not _HAVE_API:
        return Status(reason=NO_API), None
    target = _target_for(device)
    if target is None:
        return Status(reason=NO_DISPLAY if device else NO_CONFIG), None
    info = DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO()
    info.header.type = GET_ADVANCED_COLOR_INFO
    info.header.size = ctypes.sizeof(info)
    info.header.adapterId, info.header.id = target
    code = _user32.DisplayConfigGetDeviceInfo(ctypes.byref(info))
    if code:
        # Pre-1709 Windows rejects the request type outright.
        log.info("couldn't read the advanced-colour state (%d)", code)
        return Status(reason=NO_API), target
    enabled = bool(info.value & COLOR_ENABLED)
    if not info.value & COLOR_SUPPORTED:
        return Status(enabled=enabled, reason=NO_SUPPORT), target
    if info.value & COLOR_FORCE_DISABLED:
        return Status(enabled=enabled, reason=FORCED_OFF), target
    return Status(supported=True, enabled=enabled), target


# --- what the rest of QRes GUI uses ----------------------------------------

def status(device: str | None = None) -> Status:
    """What HDR is doing on `device`, or the primary display. Never raises."""
    try:
        return _probe(device)[0]
    except Exception:  # an unexpected API failure must not take the caller with it
        log.exception("couldn't read the HDR state")
        return Status(reason=NO_CONFIG)


def set_enabled(on: bool, device: str | None = None) -> bool:
    """Switch HDR on `device`, or the primary display; returns whether anything changed.

    Waits out the display's re-sync afterwards, so callers can act on the new
    state straight away. Raises HdrError if Windows wouldn't do it.
    """
    state, target = _probe(device)
    if state.enabled == on:
        return False  # nothing to do, so it doesn't matter whether we could
    if not state.supported or target is None:
        raise HdrError(state.reason or NO_SUPPORT)
    request = DISPLAYCONFIG_SET_ADVANCED_COLOR_STATE()
    request.header.type = SET_ADVANCED_COLOR_STATE
    request.header.size = ctypes.sizeof(request)
    request.header.adapterId, request.header.id = target
    request.value = 1 if on else 0
    code = _user32.DisplayConfigSetDeviceInfo(ctypes.byref(request))
    if code:
        raise HdrError(f"Windows wouldn't turn HDR {'on' if on else 'off'} (error {code}).")
    log.info("turned HDR %s on %s", "on" if on else "off", device or "the primary display")
    time.sleep(SETTLE)
    if _probe(device)[0].enabled != on:
        # Worth knowing about, but not worth telling the user off for: some
        # drivers report the new state late, and the display did change.
        log.warning("Windows accepted the HDR change but still reports it as %s", "off" if on else "on")
    return True
