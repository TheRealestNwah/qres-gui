"""Per-game scaling mode: what the launcher sets, what puts it back, and the pieces around it.

Windows' DisplayConfig API needs a real display, so qres_gui.scaling's two
calls are stood in for by a fake that remembers what it was asked; one test
reads the real current mode, which changes nothing.
"""

import base64
import json
import subprocess
import sys

import pytest

from helpers import no_guard
from qres_gui import config, display, launcher, notify, scaling, session, transfer

DESKTOP = display.Mode(3440, 1440, 165)


class FakeScaling:
    def __init__(self, mode=scaling.IDENTITY, breaks=False):
        self.mode, self.breaks, self.calls = mode, breaks, []

    def current(self, device=None):
        return self.mode

    def set_mode(self, value, device=None):
        self.calls.append((value, device))
        if self.breaks:
            raise scaling.ScalingError("the driver said no")
        changed, self.mode = self.mode != value, value
        return changed


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(launcher, "EXIT_GRACE", 0.5)
    monkeypatch.setattr(display, "current_mode", lambda device=None: DESKTOP)
    monkeypatch.setattr(display, "resolve", lambda w, h, r, d, device=None: display.Mode(w, h, d.refresh))
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: "stub")
    monkeypatch.setattr(launcher, "_spawn_guard", no_guard)
    monkeypatch.setattr(launcher.hdr, "status", lambda device=None: launcher.hdr.Status())
    monkeypatch.setattr(notify, "notify", lambda *a, **k: pytest.fail(f"unexpected notification: {a}"))


@pytest.fixture
def fake(monkeypatch):
    def install(**kwargs):
        stand_in = FakeScaling(**kwargs)
        monkeypatch.setattr(scaling, "current", stand_in.current)
        monkeypatch.setattr(scaling, "set_mode", stand_in.set_mode)
        return stand_in
    return install


def _profile(**overrides):
    cfg = config.load()
    cfg.update(switch_delay=0, restore_delay=0)
    cfg["games"]["steam:1"] = {"enabled": True, "name": "Test Game", "width": 2560, "height": 1440,
                               "refresh": 0, "watch": [], "quick_restore": True, **overrides}
    config.save(cfg)


def _sleep_cmd(seconds):
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


@pytest.mark.parametrize("choice, value", [("aspect", scaling.ASPECT), ("centered", scaling.CENTERED),
                                           ("stretch", scaling.STRETCHED)])
def test_the_scaling_mode_is_set_for_the_game_and_put_back(fake, choice, value):
    stand_in = fake(mode=scaling.IDENTITY)
    _profile(scaling=choice)
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0
    assert stand_in.calls == [(value, None), (scaling.IDENTITY, None)]
    assert session.read() is None


def test_scaling_is_left_alone_unless_the_profile_asks(fake):
    stand_in = fake()
    _profile()
    launcher.run("steam:1", _sleep_cmd(0.2))
    assert stand_in.calls == []


def test_scaling_is_left_alone_at_the_displays_own_resolution(fake):
    """Nothing to scale when the game runs at the desktop size."""
    stand_in = fake()
    _profile(scaling="aspect", width=3440, height=1440)
    launcher.run("steam:1", _sleep_cmd(0.2))
    assert stand_in.calls == []


def test_the_record_holds_the_desktop_scaling_for_the_guard(fake, monkeypatch):
    fake(mode=scaling.PREFERRED)
    _profile(scaling="stretch", display=r"\\.\DISPLAY2")
    monkeypatch.setattr(display, "find_display", lambda d: object())
    seen = {}
    monkeypatch.setattr(launcher, "_start_command",
                        lambda cmd, extra="": seen.update(session.read() or {}) or subprocess.Popen(cmd))
    launcher.run("steam:1", _sleep_cmd(0.2))
    assert seen["original_scaling"] == scaling.PREFERRED and seen["device"] == r"\\.\DISPLAY2"


def test_restore_puts_scaling_back(fake):
    stand_in = fake(mode=scaling.STRETCHED)
    session.write(DESKTOP.to_dict(), "steam:1", original_scaling=scaling.ASPECT)
    assert launcher.restore() == 0
    assert stand_in.calls == [(scaling.ASPECT, None)]


def test_a_driver_that_refuses_still_starts_the_game(fake, monkeypatch):
    fake(breaks=True)
    told = []
    monkeypatch.setattr(notify, "notify", lambda *a, **k: told.append(a))
    _profile(scaling="aspect")
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0
    assert told and "scaling" in told[0][0] and session.read() is None


def test_a_display_that_wont_say_its_scaling_is_left_alone(monkeypatch):
    calls = []
    monkeypatch.setattr(scaling, "current", lambda device=None: None)
    monkeypatch.setattr(scaling, "set_mode", lambda *a, **k: calls.append(a))
    _profile(scaling="aspect")
    launcher.run("steam:1", _sleep_cmd(0.2))
    assert calls == []


def test_backups_carry_the_scaling_choice():
    assert "scaling" in transfer.PORTABLE_GAME


def test_reading_the_real_scaling_mode_never_raises():
    value = scaling.current()
    assert value is None or isinstance(value, int)
    assert isinstance(scaling.describe(value), str)


def test_playnites_stop_script_puts_scaling_back(fake):
    stand_in = fake(mode=scaling.CENTERED)
    session.write(DESKTOP.to_dict(), "steam:1", source="playnite", playnite_id="p1", original_scaling=scaling.IDENTITY)
    payload = base64.b64encode(json.dumps({"id": "p1"}).encode()).decode()
    assert launcher.playnite_stop(payload) == 0
    assert stand_in.calls == [(scaling.IDENTITY, None)] and session.read() is None
