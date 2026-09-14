"""Per-game HDR: what the launcher switches, and what puts it back.

The Windows API itself isn't exercised here - qres_gui.hdr talks to
DisplayConfig, which needs a real display - so it's stood in for by a fake that
records what was asked of it.
"""

import dataclasses
import json
import subprocess
import sys

import pytest

from helpers import no_guard
from qres_gui import config, display, hdr, launcher, notify, paths, session

DESKTOP = display.Mode(3440, 1440, 165)


class FakeHdr:
    """qres_gui.hdr, minus Windows. Remembers every switch it was asked for."""

    def __init__(self, supported: bool = True, enabled: bool = False, breaks: bool = False):
        self.state = hdr.Status(supported=supported, enabled=enabled,
                                reason="" if supported else hdr.NO_SUPPORT)
        self.breaks = breaks
        self.calls: list[bool] = []

    def status(self) -> hdr.Status:
        return self.state

    def set_enabled(self, on: bool) -> bool:
        self.calls.append(on)
        if self.state.enabled == on:
            return False  # like the real one, which checks this before it can fail
        if self.breaks:
            raise hdr.HdrError("the display said no")
        self.state = dataclasses.replace(self.state, enabled=on)
        return True


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(launcher, "EXIT_GRACE", 0.5)
    monkeypatch.setattr(display, "current_mode", lambda: DESKTOP)
    monkeypatch.setattr(display, "resolve", lambda w, h, r, d: display.Mode(w, h, d.refresh))
    monkeypatch.setattr(launcher, "_spawn_guard", no_guard)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: pytest.fail(f"unexpected notification: {a}"))


@pytest.fixture
def fake_hdr(monkeypatch):
    def install(**kwargs) -> FakeHdr:
        fake = FakeHdr(**kwargs)
        monkeypatch.setattr(hdr, "status", fake.status)
        monkeypatch.setattr(hdr, "set_enabled", fake.set_enabled)
        return fake
    return install


@pytest.fixture
def notifications(monkeypatch) -> list:
    seen = []
    monkeypatch.setattr(notify, "notify", lambda *a, **k: seen.append(a))
    return seen


def _profile(**overrides) -> dict:
    cfg = config.load()
    cfg.update(switch_delay=0, restore_delay=0)
    cfg["games"]["steam:1"] = {"enabled": True, "name": "Test Game", "width": 2560, "height": 1440,
                               "refresh": 0, "watch": [], "quick_restore": True, **overrides}
    config.save(cfg)
    return cfg


def _sleep_cmd(seconds: float) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


# --- switching --------------------------------------------------------------

@pytest.mark.parametrize("want, before, expected", [
    (True, False, [True, False]),   # HDR on for the game, off again afterwards
    (False, True, [False, True]),   # and the other way round, for washed-out SDR games
])
def test_hdr_is_switched_for_the_game_and_put_back(monkeypatch, fake_hdr, want, before, expected):
    fake = fake_hdr(enabled=before)
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: "stub")
    _profile(hdr=want)
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0
    assert fake.calls == expected
    assert fake.state.enabled is before
    assert session.read() is None


def test_hdr_is_left_alone_unless_the_profile_asks(fake_hdr, monkeypatch):
    fake = fake_hdr(enabled=True)
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: "stub")
    _profile()  # no "hdr" key at all
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0
    assert fake.calls == []


def test_hdr_switches_on_its_own_without_a_resolution_change(monkeypatch, fake_hdr):
    """A profile can be HDR-only: same resolution as the desktop, HDR on."""
    fake = fake_hdr(enabled=False)
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: pytest.fail("set_mode called"))
    _profile(width=DESKTOP.width, height=DESKTOP.height, refresh=DESKTOP.refresh, hdr=True)
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0
    assert fake.calls == [True, False]
    assert session.read() is None


def test_nothing_happens_when_hdr_is_already_where_the_game_wants_it(monkeypatch, fake_hdr):
    fake = fake_hdr(enabled=True)
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: "stub")
    _profile(hdr=True)
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0
    assert fake.calls == []
    assert session.read() is None


# --- when HDR can't be had --------------------------------------------------

def test_an_unsupported_display_is_never_switched(monkeypatch, fake_hdr, notifications):
    fake = fake_hdr(supported=False)
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: "stub")
    _profile(hdr=True)
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0
    assert fake.calls == [] and notifications == []


def test_a_failed_hdr_switch_still_starts_the_game(monkeypatch, fake_hdr, notifications):
    fake = fake_hdr(breaks=True)
    switched = []
    monkeypatch.setattr(display, "set_mode", lambda mode, *a, **k: switched.append(mode) or "stub")
    _profile(hdr=True)
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0
    assert switched == [display.Mode(2560, 1440, 165), DESKTOP]  # the resolution still switched, and back
    assert [n[0] for n in notifications] == ["Couldn't turn HDR on"]


# --- the safety net ---------------------------------------------------------

def test_the_session_record_holds_the_desktop_hdr_state(monkeypatch, fake_hdr):
    """So the guard can put HDR back if this launcher is killed mid-game."""
    fake_hdr(enabled=False)
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: "stub")
    _profile(hdr=True)
    while_running = {}
    monkeypatch.setattr(launcher, "_start_command",
                        lambda cmd: while_running.update(session.read() or {}) or subprocess.Popen(cmd))
    launcher.run("steam:1", _sleep_cmd(0.2))
    assert while_running["original_hdr"] is False
    assert while_running["original"] == DESKTOP.to_dict()


def test_restore_puts_hdr_back_too(monkeypatch, fake_hdr):
    """`QResLauncher restore`, which is also what the guard and the GUI fall back on."""
    fake = fake_hdr(enabled=True)  # a game turned it on and never turned it off
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: "stub")
    session.write(DESKTOP.to_dict(), "steam:1", original_hdr=False)
    assert launcher.restore() == 0
    assert fake.calls == [False]
    assert session.read() is None


def test_a_stale_record_keeps_the_real_desktop_hdr_state(monkeypatch, fake_hdr):
    """A second game starting after a crashed first one must still restore to the desktop state."""
    fake = fake_hdr(enabled=True)  # left on by the launch that never switched back
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: "stub")
    session.write(DESKTOP.to_dict(), "steam:0", original_hdr=False)
    stale = {**session.read(), "create_time": 0.0}  # as if that launcher were long gone
    paths.session_path().write_text(json.dumps(stale), encoding="utf-8")
    _profile(hdr=True)  # this game wants HDR too, so nothing to switch on the way in
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0
    assert fake.calls == [False]  # only the restore, back to the desktop's HDR-off
    assert session.read() is None


# --- custom launch arguments ------------------------------------------------

@pytest.mark.parametrize("launch_args, extra, expected", [
    ("-dx11", "-windowed", "-dx11 -windowed"),
    ("", "-windowed", "-windowed"),
    ("-dx11", "", "-dx11"),
    ("", "", ""),
    ("  -dx11  ", "  -windowed  ", "-dx11 -windowed"),
])
def test_full_args_puts_the_users_arguments_after_the_stores(launch_args, extra, expected):
    entry = {"launch": {"type": "exe", "path": "Game.exe", "args": launch_args}, "extra_args": extra}
    assert config.full_args(entry) == expected


def test_full_args_copes_with_a_profile_that_has_neither():
    assert config.full_args({}) == ""


def test_extra_arguments_reach_the_command_line(monkeypatch, tmp_path):
    exe = tmp_path / "Game.exe"
    exe.write_bytes(b"MZ")
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmdline, cwd=None: started.append((cmdline, cwd)))
    entry = {"launch": {"type": "exe", "path": str(exe), "args": "-dx11", "cwd": str(tmp_path)},
             "extra_args": "-windowed -skipintro"}
    launcher._start_target(entry["launch"], config.full_args(entry))
    assert started == [(subprocess.list2cmdline([str(exe)]) + " -dx11 -windowed -skipintro", str(tmp_path))]
