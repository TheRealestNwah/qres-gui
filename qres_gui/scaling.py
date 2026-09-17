"""How a resolution smaller than the display is shown: black bars, centred, or stretched.

Windows keeps a scaling mode for each display output in the DisplayConfig
API (the one `hdr` uses): keep the aspect ratio, centre the picture without
scaling, or stretch it to fill. At the display's own resolution there's
nothing to scale, so it only matters while a game runs at another size - on
an ultrawide at 2560 × 1440, it's whether the game gets bars at the sides or
is stretched wide.

Changes are made without saving them to Windows' display database, so like
QRes's /D a restart forgets them. Graphics drivers decide whether to honour
the setting: NVIDIA only does when its control panel scales on the GPU. Like
`hdr`, nothing here may stop a game from starting - callers catch
ScalingError and carry on.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from . import display, hdr

log = logging.getLogger(__name__)

# DISPLAYCONFIG_SCALING
IDENTITY, CENTERED, STRETCHED, ASPECT, CUSTOM, PREFERRED = 1, 2, 3, 4, 5, 128

# What a profile stores ("scaling"), and what each means to Windows. None leaves it alone.
CHOICES = {"aspect": ASPECT, "centered": CENTERED, "stretch": STRETCHED}
LABELS = (
    ("Leave as it is", ""),
    ("Keep aspect ratio", "aspect"),
    ("Centered, no scaling", "centered"),
    ("Stretch to fill", "stretch"),
)

SDC_USE_SUPPLIED_DISPLAY_CONFIG = 0x00000020
SDC_APPLY = 0x00000080
SDC_ALLOW_CHANGES = 0x00000400

try:
    hdr._user32.SetDisplayConfig.argtypes = [
        wintypes.UINT, ctypes.POINTER(hdr.DISPLAYCONFIG_PATH_INFO),
        wintypes.UINT, ctypes.POINTER(hdr.DISPLAYCONFIG_MODE_INFO), wintypes.UINT,
    ]
    hdr._user32.SetDisplayConfig.restype = wintypes.LONG
    _HAVE_API = hdr._HAVE_API
except AttributeError:
    _HAVE_API = False


class ScalingError(RuntimeError):
    pass


def _query():
    """(paths, path count, modes, mode count) for the active configuration, or None."""
    for _ in range(2):
        paths_n, modes_n = wintypes.UINT(), wintypes.UINT()
        if hdr._user32.GetDisplayConfigBufferSizes(hdr.QDC_ONLY_ACTIVE_PATHS,
                                                   ctypes.byref(paths_n), ctypes.byref(modes_n)):
            return None
        paths = (hdr.DISPLAYCONFIG_PATH_INFO * paths_n.value)()
        modes = (hdr.DISPLAYCONFIG_MODE_INFO * modes_n.value)()
        code = hdr._user32.QueryDisplayConfig(hdr.QDC_ONLY_ACTIVE_PATHS, ctypes.byref(paths_n), paths,
                                              ctypes.byref(modes_n), modes, None)
        if code == 0:
            return paths, paths_n.value, modes, modes_n.value
        if code != hdr.ERROR_INSUFFICIENT_BUFFER:
            log.info("QueryDisplayConfig failed (%d)", code)
            return None
    return None


def _index(paths, count: int, device: str | None) -> int | None:
    """Which path drives `device`, or the primary display. Never guesses at a named one."""
    wanted = device or display.primary_device() or ""
    for i in range(count):
        if not wanted or hdr._source_name(paths[i]) == wanted:
            return i
    if device:
        return None
    return 0 if count else None


def current(device: str | None = None) -> int | None:
    """The scaling mode `device` (or the primary display) uses now, or None if Windows won't say."""
    if not _HAVE_API:
        return None
    try:
        found = _query()
        if not found:
            return None
        paths, count, _modes, _ = found
        i = _index(paths, count, device)
        return None if i is None else int(paths[i].targetInfo.scaling)
    except Exception:  # an unexpected API failure must not take the caller with it
        log.exception("couldn't read the scaling mode")
        return None


def set_mode(value: int, device: str | None = None) -> bool:
    """Set the scaling mode of `device`, or the primary display; returns whether anything changed.

    Raises ScalingError if Windows wouldn't do it.
    """
    if not _HAVE_API:
        raise ScalingError("This version of Windows doesn't have the display scaling setting.")
    found = _query()
    if not found:
        raise ScalingError("Windows didn't report the display configuration.")
    paths, count, modes, mode_count = found
    i = _index(paths, count, device)
    if i is None:
        raise ScalingError("That display isn't connected right now.")
    if paths[i].targetInfo.scaling == value:
        return False
    paths[i].targetInfo.scaling = value
    code = hdr._user32.SetDisplayConfig(count, paths, mode_count, modes,
                                        SDC_APPLY | SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_ALLOW_CHANGES)
    if code:
        raise ScalingError(f"Windows wouldn't change the scaling mode (error {code}).")
    log.info("set scaling to %s on %s", describe(value), device or "the primary display")
    return True


def describe(value: int | None) -> str:
    return {IDENTITY: "none (native)", CENTERED: "centered", STRETCHED: "stretched", ASPECT: "keep aspect ratio",
            CUSTOM: "custom", PREFERRED: "the display's preference"}.get(value, f"mode {value}")
