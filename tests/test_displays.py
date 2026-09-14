"""Per-game display selection: which screen the launcher switches, and puts back.

The Windows enumeration isn't exercised here - it needs real monitors - so
`display.list_displays` and friends are faked with a two-screen setup.
"""

import json
import subprocess
import sys

import pytest

from helpers import no_guard
from qres_gui import config, display, hdr, launcher, notify, paths, session

PRIMARY = display.Display(r"\\.\DISPLAY1", "Main Monitor", True)
SECOND = display.Display(r"\\.\DISPLAY2", "Side Monitor", False)
GONE = r"\\.\DISPLAY9"

MODE_OF = {None: display.Mode(3440, 1440, 165),
           PRIMARY.device: display.Mode(3440, 1440, 165),
           SECOND.device: display.Mode(1920, 1080, 60)}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(launcher, "EXIT_GRACE", 0.5)
    monkeypatch.setattr(launcher, "_spawn_guard", no_guard)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: pytest.fail(f"unexpected notification: {a}"))
    monkeypatch.setattr(display, "list_displays", lambda: [PRIMARY, SECOND])
    monkeypatch.setattr(display, "primary_device", lambda: PRIMARY.device)
    monkeypatch.setattr(display, "find_display",
                        lambda d: next((x for x in (PRIMARY, SECOND) if x.device == d), None) if d else PRIMARY)
    monkeypatch.setattr(display, "current_mode", lambda device=None: MODE_OF[device])
    monkeypatch.setattr(display, "resolve",
                        lambda w, h, r, d, device=None: display.Mode(w, h, r or d.refresh))
    monkeypatch.setattr(hdr, "status", lambda device=None: hdr.Status())


@pytest.fixture
def switches(monkeypatch) -> list:
    """Every (mode, device) the launcher asked for, in order."""
    seen = []
    monkeypatch.setattr(display, "set_mode",
                        lambda mode, qres, temporary=True, device=None: seen.append((mode, device)) or "stub")
    return seen


@pytest.fixture
def notifications(monkeypatch) -> list:
    seen = []
    monkeypatch.setattr(notify, "notify", lambda *a, **k: seen.append(a))
    return seen


def _profile(**overrides) -> None:
    cfg = config.load()
    cfg.update(switch_delay=0, restore_delay=0)
    cfg["games"]["steam:1"] = {"enabled": True, "name": "Test Game", "width": 1280, "height": 720,
                               "refresh": 0, "watch": [], "quick_restore": True, **overrides}
    config.save(cfg)


def _sleep_cmd(seconds: float) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


# --- naming a display -------------------------------------------------------

def test_a_profile_without_a_display_still_means_the_primary(switches):
    """The default path has to be untouched by all of this."""
    _profile()
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0
    assert switches == [(display.Mode(1280, 720, 165), None), (display.Mode(3440, 1440, 165), None)]


def test_a_game_switches_the_display_it_names(switches):
    _profile(display=SECOND.device)
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0
    # Switched to the game's mode on that screen, then back to *that* screen's desktop mode.
    assert switches == [(display.Mode(1280, 720, 60), SECOND.device),
                        (display.Mode(1920, 1080, 60), SECOND.device)]


def test_the_session_record_names_the_display(switches, monkeypatch):
    """So the guard puts back the screen that was changed, not whichever is primary."""
    _profile(display=SECOND.device)
    while_running = {}
    monkeypatch.setattr(launcher, "_start_command",
                        lambda cmd: while_running.update(session.read() or {}) or subprocess.Popen(cmd))
    launcher.run("steam:1", _sleep_cmd(0.2))
    assert while_running["device"] == SECOND.device
    assert while_running["original"] == MODE_OF[SECOND.device].to_dict()


def test_a_primary_profile_leaves_the_device_out_of_the_record(switches, monkeypatch):
    _profile()
    while_running = {}
    monkeypatch.setattr(launcher, "_start_command",
                        lambda cmd: while_running.update(session.read() or {}) or subprocess.Popen(cmd))
    launcher.run("steam:1", _sleep_cmd(0.2))
    assert "device" not in while_running


# --- a display that isn't there ---------------------------------------------

def test_an_unplugged_display_is_never_swapped_for_another(switches, notifications):
    """Switching some other screen would be worse than not switching at all."""
    _profile(display=GONE)
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0  # the game still starts
    assert switches == []
    assert [n[0] for n in notifications] == ["Couldn't switch the display for Test Game"]
    assert session.read() is None


# --- putting it back --------------------------------------------------------

def test_restore_puts_back_the_display_it_changed(switches):
    session.write(MODE_OF[SECOND.device].to_dict(), "steam:1", device=SECOND.device)
    assert launcher.restore() == 0
    assert switches == [(MODE_OF[SECOND.device], SECOND.device)]
    assert session.read() is None


def test_the_guard_puts_back_the_display_from_the_record(switches, monkeypatch, tmp_path):
    """An owner that died leaves a record; the guard must follow its device."""
    monkeypatch.setattr(launcher, "GUARD_POLL", 0.05)
    session.write(MODE_OF[SECOND.device].to_dict(), "steam:1", device=SECOND.device)
    stale = {**session.read(), "create_time": 0.0}  # as if that launcher were long gone
    paths.session_path().write_text(json.dumps(stale), encoding="utf-8")
    # The second screen is currently on the game's mode, not its desktop one.
    monkeypatch.setattr(display, "current_mode",
                        lambda device=None: display.Mode(1280, 720, 60) if device == SECOND.device
                        else MODE_OF[device])
    monkeypatch.setattr(notify, "notify", lambda *a, **k: None)
    assert launcher.guard(stale["pid"], stale["token"]) == 0
    assert switches == [(MODE_OF[SECOND.device], SECOND.device)]


def test_the_guard_survives_a_display_that_vanished(switches, monkeypatch):
    """Reading a named display can now raise, and the guard is the safety net for a
    killed launcher - it must not die there and leave the resolution stranded."""
    monkeypatch.setattr(launcher, "GUARD_POLL", 0.05)
    session.write(MODE_OF[SECOND.device].to_dict(), "steam:1", device=SECOND.device)
    stale = {**session.read(), "create_time": 0.0}  # as if that launcher were long gone
    paths.session_path().write_text(json.dumps(stale), encoding="utf-8")

    def unplugged(device=None):
        if device == SECOND.device:
            raise display.DisplayError("that display isn't there")
        return MODE_OF[device]

    monkeypatch.setattr(display, "current_mode", unplugged)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: None)
    assert launcher.guard(stale["pid"], stale["token"]) == 0
    assert switches == [(MODE_OF[SECOND.device], SECOND.device)]  # it still tried the restore
    assert session.read() is None


# --- HDR follows the same screen -------------------------------------------

def test_hdr_is_asked_about_the_games_display(switches, monkeypatch):
    asked = []
    monkeypatch.setattr(hdr, "status", lambda device=None: asked.append(device) or hdr.Status())
    _profile(display=SECOND.device)
    launcher.run("steam:1", _sleep_cmd(0.2))
    assert asked == [SECOND.device]


def test_hdr_is_switched_on_the_games_display(switches, monkeypatch):
    switched = []
    monkeypatch.setattr(hdr, "status", lambda device=None: hdr.Status(supported=True, enabled=False))
    monkeypatch.setattr(hdr, "set_enabled",
                        lambda on, device=None: switched.append((on, device)) or True)
    _profile(display=SECOND.device, hdr=True)
    launcher.run("steam:1", _sleep_cmd(0.2))
    assert switched == [(True, SECOND.device), (False, SECOND.device)]


# --- the pure helpers -------------------------------------------------------

@pytest.mark.parametrize("device, expected", [
    (r"\\.\DISPLAY1", "1"), (r"\\.\DISPLAY12", "12"), ("", "?"), (None, "?"),
])
def test_device_number(device, expected):
    assert display.device_number(device) == expected


def test_display_labels_say_which_screen_and_which_is_primary():
    assert PRIMARY.label == "Display 1: Main Monitor  (primary)"
    assert SECOND.label == "Display 2: Side Monitor"


def test_only_the_primary_goes_through_qres():
    """QRes v1.1 takes no monitor argument, so anything else must use the API."""
    assert display.drives_primary(None)
    assert display.drives_primary(PRIMARY.device)
    assert not display.drives_primary(SECOND.device)
