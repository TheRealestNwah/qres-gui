"""Windows playback-device helpers used by per-game audio profiles.

Windows' public Core Audio API can enumerate output endpoints, while changing
the default endpoint goes through its policy interface.  ``pycaw`` provides a
small, MIT-licensed wrapper for both.  Keep the import lazy: audio is optional
and a missing or unavailable audio service must never prevent a game launch.
"""

from __future__ import annotations

from dataclasses import dataclass


class AudioError(RuntimeError):
    """Core Audio could not be read or changed."""


@dataclass(frozen=True)
class Device:
    """One active Windows playback endpoint."""

    id: str
    name: str


def _api():
    try:
        from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
        from pycaw.pycaw import AudioUtilities
    except (ImportError, OSError) as exc:
        raise AudioError("Windows audio controls aren't available") from exc
    return AudioUtilities, EDataFlow, DEVICE_STATE, ERole


def outputs() -> list[Device]:
    """The active playback devices, with stable Windows endpoint ids."""
    try:
        utilities, flow, state, _roles = _api()
        devices = utilities.GetAllDevices(flow.eRender.value, state.ACTIVE.value)
        found = [Device(str(device.id), str(device.FriendlyName or device.id)) for device in devices]
    except AudioError:
        raise
    except Exception as exc:  # COM service/device errors differ by driver
        raise AudioError(str(exc) or "Windows couldn't list playback devices") from exc
    return sorted(found, key=lambda device: device.name.casefold())


def default_id() -> str:
    """The current default playback endpoint (the normal Windows output)."""
    try:
        utilities, _flow, _state, _roles = _api()
        device = utilities.GetSpeakers()
        if device is None or not device.id:
            raise AudioError("Windows has no default playback device")
        return str(device.id)
    except AudioError:
        raise
    except Exception as exc:
        raise AudioError(str(exc) or "Windows couldn't read the default playback device") from exc


def set_default(device_id: str) -> None:
    """Make an active endpoint the default for console, media and calls."""
    if not device_id:
        raise AudioError("No playback device was selected")
    try:
        utilities, _flow, _state, roles = _api()
        utilities.SetDefaultDevice(str(device_id), [roles.eConsole, roles.eMultimedia, roles.eCommunications])
    except AudioError:
        raise
    except Exception as exc:
        raise AudioError(str(exc) or "Windows couldn't change the playback device") from exc


def name(device_id: str) -> str:
    """A friendly name for diagnostics; endpoint ids remain the saved value."""
    try:
        return next((device.name for device in outputs() if device.id == device_id), device_id)
    except AudioError:
        return device_id
