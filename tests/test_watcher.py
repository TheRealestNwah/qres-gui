"""Switching for games started without QRes: recognising them, and the launcher's adopt command."""

import shutil
import subprocess
import time

import pytest

from helpers import no_guard
from qres_gui import autostart, config, display, launcher, notify, played, session, watcher

DESKTOP = display.Mode(3440, 1440, 165)


def game_folder(tmp_path, name="Quarry", exe="Quarry.exe"):
    folder = tmp_path / "Games" / name
    (folder / "Binaries").mkdir(parents=True)
    (folder / "Binaries" / exe).write_bytes(b"MZ")
    (folder / "_CommonRedist").mkdir()
    (folder / "_CommonRedist" / "vc_redist.x64.exe").write_bytes(b"MZ")
    (folder / "UnityCrashHandler64.exe").write_bytes(b"MZ")
    return folder


# --- recognising a game ----------------------------------------------------------

@pytest.mark.parametrize("name, path, helper", [
    ("Quarry.exe", r"D:\Games\Quarry\Quarry.exe", False),
    ("vc_redist.x64.exe", r"D:\Games\Quarry\vc_redist.x64.exe", True),
    ("Quarry.exe", r"D:\Games\Quarry\_CommonRedist\Quarry.exe", True),
    ("UnityCrashHandler64.exe", r"D:\Games\Quarry\UnityCrashHandler64.exe", True),
    ("unins000.exe", r"D:\Games\Quarry\unins000.exe", True),
    ("launcher.exe", r"D:\Games\MGS2\launcher.exe", False),     # part of starting the game
])
def test_helpers_are_not_the_game(name, path, helper):
    assert watcher.is_helper(name, path) is helper


def test_only_a_specific_folder_identifies_a_game(tmp_path):
    folder = game_folder(tmp_path)
    assert watcher.usable_folder(str(folder))
    assert not watcher.usable_folder(str(tmp_path.anchor))                   # a drive
    assert not watcher.usable_folder(str(tmp_path / "Games" / "missing"))    # not there
    common = tmp_path / "steamapps" / "common"
    common.mkdir(parents=True)
    assert not watcher.usable_folder(str(common))                            # a whole library


def test_targets_list_the_games_exes_but_not_its_helpers(tmp_path):
    folder = game_folder(tmp_path)
    [target] = watcher.build_targets([("steam:1", str(folder), ["Game-Win64-Shipping.exe"])])
    assert target.exes == {"quarry.exe"}
    assert target.watch == {"game-win64-shipping.exe"}
    assert watcher.build_targets([("steam:2", "", [])]) == []                # nothing to recognise it by


def test_the_watcher_reports_only_new_processes_of_a_game(tmp_path, monkeypatch):
    folder = game_folder(tmp_path)
    targets = watcher.build_targets([("steam:1", str(folder), [])])
    table = [(1, 0, "explorer.exe")]
    w = watcher.Watcher(snapshot=lambda: list(table))
    exe_of = {7: str(folder / "Binaries" / "Quarry.exe"), 8: r"C:\Elsewhere\Quarry.exe"}

    class Proc:
        def __init__(self, pid):
            self.pid = pid

        def exe(self):
            return exe_of[self.pid]
    monkeypatch.setattr(watcher.psutil, "Process", Proc)

    assert w.poll(targets) == []                          # the first look only learns what's running
    table.append((8, 1, "quarry.exe"))                    # same name, another folder
    assert w.poll(targets) == []
    table.append((7, 1, "quarry.exe"))
    table.append((9, 7, "vc_redist.x64.exe"))
    assert w.poll(targets) == [("steam:1", 7)]
    assert w.poll(targets) == []                          # already seen


def test_a_game_already_running_when_watching_starts_isnt_switched(tmp_path):
    folder = game_folder(tmp_path)
    targets = watcher.build_targets([("steam:1", "", ["quarry.exe"])])
    w = watcher.Watcher(snapshot=lambda: [(7, 1, "quarry.exe")])
    assert w.poll(targets) == [] and w.poll(targets) == []
    assert folder.exists()


# --- the launcher's adopt command ------------------------------------------------

@pytest.fixture
def switching(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setattr(launcher, "EXIT_GRACE", 0.5)
    monkeypatch.setattr(launcher, "ADOPT_POLL", 0.2)
    monkeypatch.setattr(launcher, "_spawn_guard", no_guard)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: pytest.fail(f"unexpected notification: {a}"))
    state = {"mode": DESKTOP, "calls": []}
    monkeypatch.setattr(display, "current_mode", lambda device=None: state["mode"])
    monkeypatch.setattr(display, "resolve", lambda w, h, r, d, device=None: display.Mode(w, h, d.refresh))

    def set_mode(mode, *a, **k):
        state["calls"].append(mode)
        state["mode"] = mode
        return "stub"
    monkeypatch.setattr(display, "set_mode", set_mode)
    monkeypatch.setattr(launcher.hdr, "status", lambda device=None: launcher.hdr.Status())
    return state


def running_game(tmp_path, seconds):
    """A real process whose exe lives in the game's folder: a copy of cmd.exe that pings for a while."""
    folder = tmp_path / "Games" / "Quarry"
    folder.mkdir(parents=True)
    exe = folder / "Quarry.exe"
    shutil.copy(shutil.which("cmd.exe"), exe)
    proc = subprocess.Popen([str(exe), "/c", f"ping -n {seconds + 1} 127.0.0.1 >nul"])
    time.sleep(0.3)
    return folder, proc


def profile(folder, **overrides):
    cfg = config.load()
    cfg.update(switch_delay=0, restore_delay=0)
    cfg["games"]["xbox:quarry"] = {"enabled": True, "name": "Quarry", "width": 2560, "height": 1440, "refresh": 0,
                                   "watch": [], "install_dir": str(folder), **overrides}
    config.save(cfg)


def test_adopt_switches_while_the_game_runs_and_back_after(switching, tmp_path):
    folder, proc = running_game(tmp_path, 2)
    try:
        profile(folder)
        assert launcher.adopt("xbox:quarry", proc.pid) == 0
        assert switching["calls"] == [display.Mode(2560, 1440, 165), DESKTOP]
        assert proc.poll() is not None                     # it waited for the game to end
        assert session.read() is None
        assert "xbox:quarry" in played.load()
    finally:
        proc.kill()


def test_adopt_leaves_an_existing_switch_alone(switching, tmp_path, monkeypatch):
    folder, proc = running_game(tmp_path, 1)
    try:
        profile(folder)
        session.write(DESKTOP.to_dict(), "steam:9")        # a hook already switched for this launch
        assert launcher.adopt("xbox:quarry", proc.pid) == 0
        assert switching["calls"] == []
    finally:
        proc.kill()


def test_adopt_does_nothing_for_a_game_with_switching_off_or_already_gone(switching, tmp_path):
    folder, proc = running_game(tmp_path, 1)
    proc.wait()
    profile(folder)
    assert launcher.adopt("xbox:quarry", proc.pid) == 0          # gone before the launcher got going
    profile(folder, enabled=False)
    assert launcher.adopt("xbox:quarry", 4) == 0
    assert launcher.adopt("xbox:unknown", 4) == 0
    assert switching["calls"] == []


def test_adopt_is_a_launcher_command(switching, monkeypatch):
    seen = []
    monkeypatch.setattr(launcher, "adopt", lambda game_id, pid: seen.append((game_id, pid)) or 0)
    assert launcher.main(["adopt", "xbox:quarry", "1234"]) == 0
    assert seen == [("xbox:quarry", 1234)]


# --- starting with Windows ----------------------------------------------------------

@pytest.fixture
def run_key(monkeypatch):
    values = {}

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(autostart.winreg, "CreateKey", lambda *a: Key())
    monkeypatch.setattr(autostart.winreg, "OpenKey", lambda *a: Key())
    monkeypatch.setattr(autostart.winreg, "SetValueEx", lambda key, name, _r, _t, value: values.__setitem__(name, value))

    def query(key, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], 1

    def delete(key, name):
        if name not in values:
            raise FileNotFoundError(name)
        del values[name]
    monkeypatch.setattr(autostart.winreg, "QueryValueEx", query)
    monkeypatch.setattr(autostart.winreg, "DeleteValue", delete)
    return values


def test_start_with_windows_names_the_installed_copy_in_the_tray(run_key, tmp_path, monkeypatch):
    installed = tmp_path / "Programs" / "QResGUI"
    installed.mkdir(parents=True)
    (installed / "QResGUI.exe").write_bytes(b"MZ")
    monkeypatch.setattr(autostart.paths, "installed_folder", lambda: installed)
    assert autostart.set_enabled(True) and autostart.enabled()
    assert run_key[autostart.VALUE] == f'"{installed / "QResGUI.exe"}" --tray'
    assert autostart.set_enabled(False) and not autostart.enabled()
    assert autostart.set_enabled(False)                    # already off is fine


def test_a_source_checkout_cant_start_with_windows(run_key, tmp_path, monkeypatch):
    monkeypatch.setattr(autostart.paths, "installed_folder", lambda: tmp_path / "nothing")
    monkeypatch.setattr(autostart.sys, "frozen", False, raising=False)
    assert autostart.command() is None
    assert not autostart.set_enabled(True) and not autostart.enabled()



def test_the_watcher_sees_a_real_game_process_start(tmp_path):
    """Windows' real process list and exe paths, with a stand-in game in a temporary folder."""
    folder = tmp_path / "Games" / "Quarry"
    folder.mkdir(parents=True)
    exe = folder / "Quarry.exe"
    shutil.copy(shutil.which("cmd.exe"), exe)
    targets = watcher.build_targets([("xbox:quarry", str(folder), [])])
    w = watcher.Watcher()
    assert w.poll(targets) == []
    proc = subprocess.Popen([str(exe), "/c", "ping -n 3 127.0.0.1 >nul"])
    try:
        time.sleep(0.3)
        assert w.poll(targets) == [("xbox:quarry", proc.pid)]
    finally:
        proc.kill()
