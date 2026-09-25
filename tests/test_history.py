"""Launch history: what each launch notes, how its end is filled in, and how the history reads."""

import base64
import json
import os
import subprocess
import sys
import time

import pytest

from helpers import no_guard
from qres_gui import config, display, hdr, history, launcher, notify, played, playnite, session

STEAM_PLUGIN = "cb91dfc9-b977-43bf-8e70-55f46e410fab"
DESKTOP = display.Mode(3440, 1440, 165)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.delenv(history.SOURCE_ENV, raising=False)
    monkeypatch.setattr(launcher, "EXIT_GRACE", 0.5)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: None)


# --- the file -----------------------------------------------------------------------

def test_a_launch_is_noted_when_it_starts_and_again_when_it_ends():
    launch = history.start("steam:1", history.STEAM, "Portal", when=1000)
    assert launch
    [entry] = history.load()
    assert entry["game_id"] == "steam:1" and entry["name"] == "Portal" and entry["source"] == history.STEAM
    assert entry["start"] == 1000 and entry.get("end") is None and entry.get("restore") is None
    assert played.load() == {"steam:1": 1000.0}      # Last played still comes from played.json

    history.finish(launch, history.PARTIAL, ["HDR"], end=1600)
    [entry] = history.load()
    assert entry["end"] == 1600 and entry["restore"] == history.PARTIAL and entry["problems"] == ["HDR"]


def test_whatever_sees_the_end_first_counts():
    launch = history.start("steam:1", history.STEAM)
    history.finish(launch, history.RECOVERED)                    # the safety net, before the game's end
    history.finish(launch, history.CLEAN, end=time.time() + 60)  # the launcher, later
    [entry] = history.load()
    assert entry["restore"] == history.RECOVERED and entry["end"] is not None


def test_nothing_is_noted_without_a_game_or_a_launch():
    assert history.start("", history.STEAM) == ""
    history.finish("", history.CLEAN)
    history.finish("not-a-launch", history.CLEAN)
    assert history.load() == []


def test_only_the_last_launches_are_kept(monkeypatch):
    monkeypatch.setattr(history, "LIMIT", 3)
    for n in range(5):
        history.start(f"steam:{n}", history.STEAM, when=1000 + n)
    assert [e["game_id"] for e in history.load()] == ["steam:2", "steam:3", "steam:4"]
    assert len(played.load()) == 5                   # trimming the history doesn't forget Last played


def test_a_damaged_file_reads_as_empty_and_is_rewritten():
    history.path().write_text("[{not json", encoding="utf-8")
    assert history.load() == []
    history.start("steam:1", history.STEAM)
    assert len(history.load()) == 1


def test_entries_that_arent_launches_are_skipped():
    history.path().write_text(json.dumps([{"id": "a", "game_id": "steam:1", "start": 5}, {"id": "b"}, "x"]),
                              encoding="utf-8")
    assert [e["id"] for e in history.load()] == ["a"]


def test_start_never_raises(monkeypatch):
    monkeypatch.setattr(history, "path", lambda: history.paths.app_dir() / "missing" / "history.json")
    assert history.start("steam:1", history.STEAM) == ""
    history.finish("abc", history.CLEAN)             # logged, not raised


def test_clear():
    history.start("steam:1", history.STEAM)
    history.clear()
    assert history.load() == []
    history.clear()                                  # nothing to clear is fine


def test_latest_open():
    old = history.start("playnite:p1", history.PLAYNITE, when=1)
    new = history.start("playnite:p1", history.PLAYNITE, when=2)
    history.start("steam:1", history.STEAM, when=3)
    assert history.latest_open("playnite:p1", history.PLAYNITE) == new
    history.finish(new, end=5)
    assert history.latest_open("playnite:p1", history.PLAYNITE) == old
    assert history.latest_open("playnite:p1", history.STEAM) == ""


def test_only_the_newest_open_launch_of_a_live_owner_is_running():
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        missed = history.start("playnite:a", history.PLAYNITE, owner=sleeper.pid, when=1)
        current = history.start("playnite:b", history.PLAYNITE, owner=sleeper.pid, when=2)
        done = history.start("steam:1", history.STEAM, when=3)
        history.finish(done, history.CLEAN, end=4)
        assert history.running_ids(history.load()) == {current}
    finally:
        sleeper.kill()
        sleeper.wait()
    assert history.running_ids(history.load()) == set()   # its owner has gone
    assert missed not in history.running_ids(history.load())


# --- how it reads -------------------------------------------------------------------

@pytest.mark.parametrize("seconds, expected", [
    (20, "Under a minute"), (60 * 12 + 30, "12 min"), (3600 + 60 * 5, "1 h 05 min"), (3600 * 3, "3 h 00 min"),
])
def test_describe_duration(seconds, expected):
    assert history.describe_duration({"start": 1000.0, "end": 1000.0 + seconds}) == expected


def test_describe_an_unfinished_launch():
    entry = {"start": 1000.0, "source": "playnite"}
    assert history.describe_duration(entry, running=True) == "Running"
    assert history.describe_duration(entry) == "—"
    assert history.describe_restore(entry, running=True)[0] == "—"
    assert history.describe_restore(entry)[0] == "Unknown"
    assert history.describe_source(entry) == "Playnite"
    assert history.describe_source({}) == "—"


@pytest.mark.parametrize("restore, problems, shown, bad", [
    (history.CLEAN, [], "Restored", False),
    (history.PARTIAL, ["HDR", "scaling"], "Restored except HDR, scaling", True),
    (history.FAILED, ["resolution"], "Not restored", True),
    (history.RECOVERED, [], "Restored late", False),
    (history.UNCHANGED, [], "Not switched", False),
])
def test_describe_restore(restore, problems, shown, bad):
    text, why, wrong = history.describe_restore({"restore": restore, "problems": problems})
    assert (text, wrong) == (shown, bad) and why


def test_describe_start():
    now = time.mktime((2026, 9, 16, 22, 0, 0, 0, 0, -1))
    assert history.describe_start(time.mktime((2026, 9, 16, 21, 4, 0, 0, 0, -1)), now) == "Today 21:04"
    assert history.describe_start(time.mktime((2026, 9, 1, 8, 30, 0, 0, 0, -1)), now) == "1 Sep 2026 08:30"


# --- what the launcher notes ------------------------------------------------------------

@pytest.fixture
def screen(monkeypatch):
    """A stubbed display that switches and switches back; `fail_restore` makes switching back fail."""
    state = {"mode": DESKTOP, "fail_restore": False}

    def set_mode(mode, qres, temporary, device=None):
        if mode == DESKTOP and state["fail_restore"]:
            raise display.DisplayError("the driver said no")
        state["mode"] = mode
        return "stub"

    monkeypatch.setattr(display, "current_mode", lambda device=None: state["mode"])
    monkeypatch.setattr(display, "resolve", lambda w, h, r, d, device=None: display.Mode(w, h, d.refresh))
    monkeypatch.setattr(display, "set_mode", set_mode)
    monkeypatch.setattr(launcher, "_spawn_guard", no_guard)
    return state


def _profile(**entry):
    cfg = config.load()
    cfg.update(switch_delay=0, restore_delay=0, desktop_mode=DESKTOP.to_dict())
    cfg["games"]["steam:1"] = {"name": "Test Game", "enabled": True, "width": 2560, "height": 1440, "refresh": 0,
                               "watch": [], "quick_restore": True, **entry}
    config.save(cfg)


def _sleep_cmd(seconds: float) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


def test_a_steam_launch_that_switches_back(screen):
    _profile()
    before = time.time()
    assert launcher.run("steam:1", _sleep_cmd(1.2)) == 0
    [entry] = history.load()
    assert entry["source"] == history.STEAM and entry["name"] == "Test Game"
    assert entry["restore"] == history.CLEAN and "problems" not in entry
    assert entry["start"] >= before - 1 and entry["end"] - entry["start"] >= 1.0
    assert session.read() is None


def test_a_launch_from_the_play_button(screen, monkeypatch):
    _profile(launch={"type": "exe", "path": sys.executable, "args": '-c "pass"'})
    monkeypatch.setenv(history.SOURCE_ENV, history.GUI)
    assert launcher.run("steam:1", []) == 0
    assert history.load()[0]["source"] == history.GUI
    assert history.SOURCE_ENV not in os.environ     # not passed on to the game


def test_a_launch_from_a_shortcut(screen):
    _profile(launch={"type": "exe", "path": sys.executable, "args": '-c "pass"'})
    assert launcher.run("steam:1", []) == 0
    assert history.load()[0]["source"] == history.SHORTCUT


def test_a_launch_with_switching_off(screen):
    _profile(enabled=False)
    assert launcher.run("steam:1", [sys.executable, "-c", "pass"]) == 0
    [entry] = history.load()
    assert entry["restore"] == history.UNCHANGED and entry["end"] is not None


def test_a_resolution_that_wouldnt_go_back(screen):
    _profile()
    screen["fail_restore"] = True
    assert launcher.run("steam:1", [sys.executable, "-c", "pass"]) == 0
    [entry] = history.load()
    assert entry["restore"] == history.FAILED and entry["problems"] == ["resolution"]
    assert session.read()["launch"] == entry["id"]   # the GUI's Restore button can still finish it


def test_hdr_that_wouldnt_go_back(screen, monkeypatch):
    _profile(hdr=True)
    state = {"on": False}

    def set_enabled(on, device=None):
        if not on:
            raise hdr.HdrError("the display went away")
        state["on"] = on
        return True

    monkeypatch.setattr(hdr, "status", lambda device=None: hdr.Status(supported=True, enabled=state["on"]))
    monkeypatch.setattr(hdr, "set_enabled", set_enabled)
    assert launcher.run("steam:1", [sys.executable, "-c", "pass"]) == 0
    [entry] = history.load()
    assert entry["restore"] == history.PARTIAL and entry["problems"] == ["HDR"]


def test_the_safety_net_notes_a_late_restore(screen, monkeypatch):
    """Steam's Stop ends the launcher mid-game; the guard's restore is what finishes the launch."""
    _profile()

    def killed_mid_game(command, extra=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(launcher, "_start_command", killed_mid_game)
    monkeypatch.setattr(launcher._Switch, "restore", lambda self: (None, []))  # it never got there
    with pytest.raises(KeyboardInterrupt):
        launcher.run("steam:1", [sys.executable, "-c", "pass"])
    assert history.load()[0].get("restore") is None
    assert launcher.restore() == 0                   # what the guard falls back on, as the record's owner
    assert history.load()[0]["restore"] == history.RECOVERED
    assert history.load()[0].get("end") is None      # when the game really ended isn't known here


def _payload(**info) -> str:
    return base64.b64encode(json.dumps(info).encode()).decode()


def test_playnite_launches_are_noted_start_to_stop(screen, monkeypatch):
    owner = subprocess.Popen(_sleep_cmd(60))
    try:
        monkeypatch.setattr(playnite, "owner_pid", lambda pid: owner.pid)
        _profile()
        assert launcher.playnite_start(_payload(id="p1", pluginId=STEAM_PLUGIN, gameId="1", owner=0)) == 0
        [entry] = history.load()
        assert entry["source"] == history.PLAYNITE and entry["pid"] == owner.pid
        assert history.running_ids(history.load()) == {entry["id"]}
        assert launcher.playnite_stop(_payload(id="p1")) == 0
    finally:
        owner.kill()
    [entry] = history.load()
    assert entry["restore"] == history.CLEAN and entry["end"] is not None


def test_a_steam_game_started_from_playnite_is_one_launch(screen, monkeypatch):
    """Playnite starts a Steam game through Steam, whose launch options run the launcher too."""
    owner = subprocess.Popen(_sleep_cmd(60))
    try:
        monkeypatch.setattr(playnite, "owner_pid", lambda pid: owner.pid)
        _profile()
        info = {"id": "p1", "pluginId": STEAM_PLUGIN, "gameId": "1", "owner": 0}
        assert launcher.playnite_start(_payload(**info)) == 0
        assert launcher.run("steam:1", [sys.executable, "-c", "pass"]) == 0
        assert launcher.playnite_stop(_payload(**info)) == 0
    finally:
        owner.kill()
    [entry] = history.load()
    assert entry["source"] == history.PLAYNITE and entry["restore"] == history.CLEAN


def test_a_playnite_game_with_switching_off_still_gets_its_end(screen, monkeypatch):
    owner = subprocess.Popen(_sleep_cmd(60))
    try:
        monkeypatch.setattr(playnite, "owner_pid", lambda pid: owner.pid)
        _profile(enabled=False)
        info = {"id": "p1", "pluginId": STEAM_PLUGIN, "gameId": "1", "owner": 0}
        assert launcher.playnite_start(_payload(**info)) == 0
        assert launcher.playnite_stop(_payload(**info)) == 0
    finally:
        owner.kill()
    [entry] = history.load()
    assert entry["restore"] == history.UNCHANGED and entry["end"] is not None
