"""Commands before and after a game's switch: when they run, in what order, and that they run once.

Commands really run - through cmd.exe, as a user's would - but only a small
recorder script, which appends what it was told and the environment QRes gave
it to a log. The display is stubbed as in the other launcher tests.
"""

import base64
import json
import subprocess
import sys
import time

import pytest

from helpers import no_guard
from qres_gui import commands, config, display, launcher, notify, playnite, session

DESKTOP = display.Mode(3440, 1440, 165)
STEAM_PLUGIN = "cb91dfc9-b977-43bf-8e70-55f46e410fab"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setattr(launcher, "EXIT_GRACE", 0.5)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: pytest.fail(f"unexpected notification: {a}"))


@pytest.fixture
def events(tmp_path):
    """A log that commands and the stubbed display both write to, in order."""
    return tmp_path / "events.log"


@pytest.fixture
def record(tmp_path, events):
    """Command text that appends `word` (and QRes's environment) to the events log."""
    script = tmp_path / "record.py"
    script.write_text(
        "import json, os, sys\n"
        f"with open({str(events)!r}, 'a', encoding='utf-8') as log:\n"
        "    log.write(json.dumps([sys.argv[1], os.environ.get('QRES_EVENT'), os.environ.get('QRES_GAME')]) + '\\n')\n",
        encoding="utf-8")
    return lambda word: f'"{sys.executable}" "{script}" {word}'


def logged(events):
    if not events.exists():
        return []
    return [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def display_log(monkeypatch, events):
    state = {"mode": DESKTOP}

    def set_mode(mode, qres, temporary, device=None):
        with open(events, "a", encoding="utf-8") as log:
            log.write(json.dumps(["restore" if mode == DESKTOP else "switch", None, None]) + "\n")
        state["mode"] = mode
        return "stub"

    monkeypatch.setattr(display, "current_mode", lambda device=None: state["mode"])
    monkeypatch.setattr(display, "resolve", lambda w, h, r, d, device=None: display.Mode(w, h, d.refresh))
    monkeypatch.setattr(display, "set_mode", set_mode)
    monkeypatch.setattr(launcher, "_spawn_guard", no_guard)
    return state


def _profile(record, width=2560, game=None, everywhere=None):
    cfg = config.load()
    cfg.update(switch_delay=0, restore_delay=0, desktop_mode=DESKTOP.to_dict())
    if everywhere is not None:
        cfg["commands"] = everywhere
    cfg["games"]["steam:1"] = {"name": "Test Game", "enabled": True, "width": width, "height": 1440, "refresh": 0,
                               "watch": [], "quick_restore": True, **({"commands": game} if game else {})}
    config.save(cfg)


# --- which commands, in which order ------------------------------------------

def test_every_games_commands_wrap_around_this_games():
    cfg = {"commands": {"before": "global-before", "after": "global-after"}}
    entry = {"commands": {"before": "game-before", "after": "game-after"}}
    assert commands.planned(cfg, entry, commands.BEFORE) == ["global-before", "game-before"]
    assert commands.planned(cfg, entry, commands.AFTER) == ["game-after", "global-after"]
    assert commands.planned({}, {}, commands.BEFORE) == []


def test_a_command_gets_the_game_in_its_environment(record, events):
    commands.run(record("hello"), commands.BEFORE, "steam:1", "Test Game")
    assert logged(events) == [["hello", "before", "Test Game"]]


def test_a_long_running_command_doesnt_hold_things_up(monkeypatch):
    """A frame limiter or overlay keeps running; QRes carries on after WAIT."""
    monkeypatch.setattr(commands, "WAIT", 0.5)
    started = time.monotonic()
    commands.run(f'"{sys.executable}" -c "import time; time.sleep(5)"', commands.BEFORE)
    assert time.monotonic() - started < 3


def test_a_command_that_cant_start_is_reported_not_raised(monkeypatch):
    said = []
    monkeypatch.setattr(notify, "notify", lambda title, message, **k: said.append(title))

    def refuse(*a, **k):
        raise OSError("nope")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    commands.run("anything", commands.AFTER, "steam:1", "Test Game")   # must not raise
    assert said == ["Couldn't run the command after Test Game"]


# --- around a real launch ------------------------------------------------------

def test_before_runs_before_the_switch_and_after_once_it_is_undone(display_log, record, events):
    _profile(record, game={"before": record("game-before"), "after": record("game-after")},
             everywhere={"before": record("global-before"), "after": record("global-after")})
    assert launcher.run("steam:1", [sys.executable, "-c", "pass"]) == 0
    assert [e[0] for e in logged(events)] == [
        "global-before", "game-before", "switch", "restore", "game-after", "global-after"]
    assert session.read() is None


def test_no_switch_means_no_commands(display_log, record, events):
    """Commands belong to the switch: a game already at the desktop's mode runs none."""
    _profile(record, width=3440, game={"before": record("before"), "after": record("after")})
    assert launcher.run("steam:1", [sys.executable, "-c", "pass"]) == 0
    assert logged(events) == []


def test_after_commands_are_saved_so_a_restore_from_elsewhere_runs_them(display_log, record, events,
                                                                       monkeypatch):
    """Steam's Stop kills the launcher; the guard or the Restore button then finishes the switch."""
    _profile(record, game={"after": record("game-after")})
    seen = {}

    def killed_mid_game(command, extra=""):
        seen.update(session.read() or {})
        raise KeyboardInterrupt   # the launcher never gets to its own restore

    monkeypatch.setattr(launcher, "_start_command", killed_mid_game)
    monkeypatch.setattr(launcher._Switch, "restore", lambda self: None)
    with pytest.raises(KeyboardInterrupt):
        launcher.run("steam:1", [sys.executable, "-c", "pass"])
    assert seen["after"] == [record("game-after")]
    assert launcher.restore() == 0                     # what the guard falls back on
    assert [e[0] for e in logged(events)] == ["switch", "restore", "game-after"]
    assert launcher.restore() == 0                     # a second restore has nothing left to run
    assert [e[0] for e in logged(events)].count("game-after") == 1


# --- Playnite -----------------------------------------------------------------------

def _payload(**info) -> str:
    return base64.b64encode(json.dumps(info).encode()).decode()


def test_playnite_runs_them_once_even_when_steam_starts_the_game_too(display_log, record, events,
                                                                    monkeypatch):
    """Playnite's scripts own the switch; the Steam-side launcher must not run the commands again."""
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        monkeypatch.setattr(playnite, "owner_pid", lambda pid: owner.pid)
        _profile(record, game={"before": record("before"), "after": record("after")})
        assert launcher.playnite_start(_payload(id="p1", pluginId=STEAM_PLUGIN, gameId="1", owner=0)) == 0
        assert launcher.run("steam:1", [sys.executable, "-c", "pass"]) == 0
        assert launcher.playnite_stop(_payload(id="p1")) == 0
    finally:
        owner.kill()
    assert [e[0] for e in logged(events)] == ["before", "switch", "restore", "after"]
