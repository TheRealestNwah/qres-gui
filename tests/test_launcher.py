"""Launcher behaviour that doesn't change the real display resolution."""

import json
import shutil
import subprocess
import sys
import time

import pytest

from helpers import no_guard
from qres_gui import config, display, launcher, notify, session


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(launcher, "EXIT_GRACE", 0.5)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: pytest.fail(f"unexpected notification: {a}"))


def _sleep_cmd(seconds: float) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


def _spawn_child_then_exit_cmd(seconds: float) -> list[str]:
    # Parent starts a detached-ish child and exits immediately, like a game launcher.
    code = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep({seconds})']); "
        "sys.exit(0)"
    )
    return [sys.executable, "-c", code]


def test_waits_for_direct_process():
    t0 = time.monotonic()
    assert launcher.run("steam:1", _sleep_cmd(1.5)) == 0
    assert time.monotonic() - t0 >= 1.5


def test_waits_for_grandchild_after_parent_exits():
    t0 = time.monotonic()
    launcher.run("steam:1", _spawn_child_then_exit_cmd(2.5))
    assert time.monotonic() - t0 >= 2.5


def test_returns_game_exit_code():
    assert launcher.run("steam:1", [sys.executable, "-c", "raise SystemExit(3)"]) == 3


def test_no_switch_when_target_is_desktop_mode(monkeypatch):
    current = display.current_mode()
    cfg = config.load()
    cfg["games"]["steam:1"] = {"enabled": True, "width": current.width, "height": current.height,
                               "refresh": current.refresh, "watch": []}
    config.save(cfg)
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: pytest.fail("set_mode called"))
    assert launcher.run("steam:1", _sleep_cmd(0.3)) == 0
    assert session.read() is None


def test_switch_and_restore_are_paired(monkeypatch):
    """With the display calls stubbed out, check the switch/restore sequence and session record."""
    calls = []
    desktop = display.Mode(3440, 1440, 165)
    monkeypatch.setattr(display, "current_mode", lambda: desktop)
    monkeypatch.setattr(display, "resolve", lambda w, h, r, d: display.Mode(w, h, d.refresh))
    monkeypatch.setattr(display, "set_mode", lambda mode, qres, temporary: calls.append(mode) or "stub")
    monkeypatch.setattr(launcher, "_spawn_guard", no_guard)
    cfg = config.load()
    cfg.update(switch_delay=0, restore_delay=0)
    cfg["games"]["steam:1"] = {"enabled": True, "width": 2560, "height": 1440, "refresh": 0, "watch": []}
    config.save(cfg)

    seen_session = {}

    def fake_start(command):
        seen_session.update(session.read() or {})
        return subprocess.Popen(command)

    monkeypatch.setattr(launcher, "_start_command", fake_start)
    launcher.run("steam:1", _sleep_cmd(0.2))
    assert calls == [display.Mode(2560, 1440, 165), desktop]
    assert seen_session["original"] == desktop.to_dict()
    assert session.read() is None


@pytest.mark.parametrize("quick, minimum, maximum", [(False, 2.5, 6), (True, 0, 1.0)])
def test_quick_restore_skips_the_waits(monkeypatch, tmp_path, quick, minimum, maximum):
    """Time from the game exiting to the display being switched back.

    Normally that's EXIT_GRACE + restore_delay (1.5 + 1.0 here); quick_restore skips both.
    """
    monkeypatch.setattr(launcher, "EXIT_GRACE", 1.5)
    desktop = display.Mode(3440, 1440, 165)
    restored_at = []
    monkeypatch.setattr(display, "current_mode", lambda: desktop)
    monkeypatch.setattr(display, "resolve", lambda w, h, r, d: display.Mode(w, h, d.refresh))
    monkeypatch.setattr(display, "set_mode",
                        lambda mode, qres, temporary: mode == desktop and restored_at.append(time.monotonic()))
    monkeypatch.setattr(launcher, "_spawn_guard", no_guard)
    cfg = config.load()
    cfg.update(switch_delay=0, restore_delay=1.0)
    cfg["games"]["steam:1"] = {"enabled": True, "width": 2560, "height": 1440, "refresh": 0,
                               "watch": [], "quick_restore": quick}
    config.save(cfg)

    # The "game" records when it quits; monotonic() is system-wide on Windows.
    stamp = tmp_path / "exit.txt"
    game = [sys.executable, "-c", f"import time; open({str(stamp)!r}, 'w').write(repr(time.monotonic()))"]
    launcher.run("steam:1", game)
    assert minimum <= restored_at[0] - float(stamp.read_text()) <= maximum


def test_disabled_game_launches_without_switching(monkeypatch):
    cfg = config.load()
    cfg["games"]["steam:1"] = {"enabled": False, "width": 800, "height": 600, "refresh": 0}
    config.save(cfg)
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: pytest.fail("set_mode called"))
    assert launcher.run("steam:1", _sleep_cmd(0.2)) == 0


def test_watch_names_track_a_process_started_elsewhere(monkeypatch, tmp_path):
    """Store-URL launches: nothing is started by us; the game is found by name."""
    monkeypatch.setattr(launcher, "APPEAR_TIMEOUT", 10)
    # A uniquely named exe, so no unrelated process matches the watch list.
    sleeper = tmp_path / "qres_test_game.exe"
    shutil.copy(r"C:\Windows\System32\PING.EXE", sleeper)
    proc = subprocess.Popen([str(sleeper), "-n", "3", "127.0.0.1"], stdout=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    t0 = time.monotonic()
    launcher._wait(None, {sleeper.name})
    assert time.monotonic() - t0 >= 1.0
    assert proc.poll() is not None


def test_config_file_is_json(tmp_path):
    cfg = config.load()
    config.save(cfg)
    assert json.loads((tmp_path / "QResGUI" / "config.json").read_text())["temporary"] is True
