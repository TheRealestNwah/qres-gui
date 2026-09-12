"""Playnite integration: matching, the scripts themselves, Playnite's settings, and the launcher side."""

import base64
import json
import subprocess
import sys

import psutil
import pytest

from helpers import no_guard
from qres_gui import config, display, hooks, launcher, notify, playnite, session
from qres_gui.stores import standalone
from qres_gui.stores.steam import SteamClient

STEAM_PLUGIN = "cb91dfc9-b977-43bf-8e70-55f46e410fab"
LEGENDARY_PLUGIN = "ead65c3b-2f8f-4e37-b4e6-b3de6be540c6"
CMD = [r"C:\Apps\QRes GUI\QResLauncher.exe"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setattr(notify, "notify", lambda *a, **k: pytest.fail(f"unexpected notification: {a}"))


def _payload(**info) -> str:
    return base64.b64encode(json.dumps(info).encode()).decode()


# --- matching -------------------------------------------------------------------

GAMES = {
    "steam:2492670": {"name": "METAL GEAR SOLID 4: Guns of the Patriots", "install_dir": r"D:\SteamLibrary\common\MGS4"},
    "legendary:Quail": {"name": "Hogwarts Legacy", "install_dir": r"D:\Heroic\HogwartsLegacy"},
    "manual:pubg": {"name": "PUBG", "install_dir": r"D:\Heroic\PUBGbhX8R\TslGame\Binaries\Win64"},
    "gog:1453375253": {"name": "Stardew Valley™", "install_dir": r"D:\Heroic\Stardew Valley"},
}


@pytest.mark.parametrize("info, expected", [
    ({"pluginId": STEAM_PLUGIN.upper(), "gameId": "2492670", "installDir": r"C:\elsewhere"}, "steam:2492670"),
    ({"pluginId": LEGENDARY_PLUGIN, "gameId": "Quail"}, "legendary:Quail"),
    ({"pluginId": "unknown", "gameId": "x", "installDir": "d:/heroic/hogwartslegacy/"}, "legendary:Quail"),
    ({"installDir": r"D:\Heroic\PUBGbhX8R"}, "manual:pubg"),            # profile points inside the game folder
    ({"name": "stardew valley", "installDir": r"C:\other"}, "gog:1453375253"),
    ({"name": "Something Else", "installDir": r"D:\Games\Other"}, None),
])
def test_match(info, expected):
    game_id, entry = playnite.match({"games": GAMES}, info)
    assert game_id == expected
    assert (entry is GAMES.get(expected)) if expected else entry is None


# --- scripts and Playnite's settings ---------------------------------------------

@pytest.fixture
def fake_playnite(tmp_path, monkeypatch):
    path = tmp_path / "Playnite" / "config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"PreScript": "Write-Host 'mine'", "PostScript": None, "Theme": "Default",
                                "Nested": {"a": [1, 2.5, None]}}), encoding="utf-8-sig")
    monkeypatch.setattr(playnite, "config_path", lambda: path)
    monkeypatch.setattr(playnite, "is_running", lambda: False)
    return path


def test_install_keeps_user_lines_and_other_settings(fake_playnite):
    assert playnite.state(CMD) == "none"
    backup = playnite.install(CMD)
    assert backup.exists()
    data = json.loads(fake_playnite.read_text(encoding="utf-8"))
    assert data["PreScript"].startswith("Write-Host 'mine'")
    assert playnite.BEGIN in data["PreScript"] and "playnite-start" in data["PreScript"]
    assert "playnite-stop" in data["PostScript"]
    assert data["Theme"] == "Default" and data["Nested"] == {"a": [1, 2.5, None]}
    assert playnite.state(CMD) == "installed"

    playnite.install(CMD)  # idempotent: one block per script
    data = json.loads(fake_playnite.read_text(encoding="utf-8"))
    assert data["PreScript"].count(playnite.BEGIN) == 1

    assert playnite.state([r"D:\Moved\QResLauncher.exe"]) == "outdated"
    playnite.uninstall()
    data = json.loads(fake_playnite.read_text(encoding="utf-8"))
    assert data["PreScript"] == "Write-Host 'mine'" and data["PostScript"] is None
    assert playnite.state(CMD) == "none"


def test_state_survives_crlf_rewrites(fake_playnite):
    playnite.install(CMD)
    data = json.loads(fake_playnite.read_text(encoding="utf-8"))
    data["PreScript"] = data["PreScript"].replace("\r\n", "\n").replace("\n", "\r\n")
    fake_playnite.write_text(json.dumps(data), encoding="utf-8")
    assert playnite.state(CMD) == "installed"


def test_refuses_while_playnite_runs(fake_playnite, monkeypatch):
    monkeypatch.setattr(playnite, "is_running", lambda: True)
    with pytest.raises(playnite.PlayniteRunningError):
        playnite.install(CMD)


def test_remove_all_hooks_takes_out_playnite_lines(fake_playnite, monkeypatch, tmp_path):
    playnite.install(CMD)
    monkeypatch.setattr(hooks.shortcuts, "all_game_shortcuts", list)
    client = SteamClient(root=tmp_path / "no-steam")
    monkeypatch.setattr(type(client), "available", property(lambda self: False))
    found = hooks.find(client)
    assert found.playnite and not found.steam
    hooks.remove(client, found)
    assert playnite.state(CMD) == "none"


def test_pre_script_really_runs_in_windows_powershell(tmp_path):
    """Run the generated before-start block in PowerShell 5.1 (what Playnite uses) with a fake
    $Game, pointing at a stand-in launcher that records the payload it receives."""
    record = tmp_path / "received.json"
    stand_in = tmp_path / "stand_in.py"
    stand_in.write_text(
        "import base64, sys\n"
        f"open({str(record)!r}, 'w', encoding='utf-8').write("
        "sys.argv[1] + ' ' + base64.b64decode(sys.argv[2]).decode('utf-8'))\n", encoding="utf-8")
    pre, _ = playnite.scripts([sys.executable, str(stand_in)])
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        "$Game = [pscustomobject]@{ Id = [guid]'11111111-2222-3333-4444-555555555555'; GameId = '2492670';\n"
        "  PluginId = [guid]'" + STEAM_PLUGIN + "'; Name = 'Assassin''s Creed™ \"Test\" Édition';\n"
        "  InstallDirectory = '{PlayniteDir}\\Games\\My Game\\' }\n"
        "$PlayniteApi = [pscustomobject]@{}\n"
        "$PlayniteApi | Add-Member -MemberType ScriptMethod -Name ExpandGameVariables "
        "-Value { param($g, $s) $s.Replace('{PlayniteDir}', 'C:\\Playnite') }\n"
        + pre + "\n", encoding="utf-8-sig")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    command, received = record.read_text(encoding="utf-8").split(" ", 1)
    info = json.loads(received)
    assert command == "playnite-start"
    assert info["id"] == "11111111-2222-3333-4444-555555555555" and info["gameId"] == "2492670"
    assert info["pluginId"] == STEAM_PLUGIN
    assert info["name"] == 'Assassin\'s Creed™ "Test" Édition'
    assert info["installDir"] == "C:\\Playnite\\Games\\My Game\\"
    assert isinstance(info["owner"], int)


# --- the launcher side ------------------------------------------------------------

@pytest.fixture
def switching(monkeypatch):
    """Stub the display, and use a live stand-in process as "Playnite"."""
    desktop = display.Mode(3440, 1440, 165)
    state = {"mode": desktop, "calls": []}

    def set_mode(mode, qres, temporary):
        state["calls"].append(mode)
        state["mode"] = mode
        return "stub"

    monkeypatch.setattr(display, "current_mode", lambda: state["mode"])
    monkeypatch.setattr(display, "resolve", lambda w, h, r, d: display.Mode(w, h, d.refresh))
    monkeypatch.setattr(display, "set_mode", set_mode)
    monkeypatch.setattr(launcher, "_spawn_guard", no_guard)
    fake = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    monkeypatch.setattr(playnite, "owner_pid", lambda pid: fake.pid)
    cfg = config.load()
    cfg.update(switch_delay=0, restore_delay=0)
    cfg["games"] = {
        "steam:1": {"name": "Steam Game", "enabled": True, "width": 2560, "height": 1440, "install_dir": r"D:\S"},
        "legendary:Quail": {"name": "Hogwarts Legacy", "enabled": True, "width": 1920, "height": 1080},
        "gog:9": {"name": "Off", "enabled": False, "width": 800, "height": 600},
    }
    config.save(cfg)
    yield state, desktop, fake.pid
    fake.kill()


def test_playnite_start_and_stop(switching):
    state, desktop, owner = switching
    assert launcher.playnite_start(_payload(id="p1", pluginId=STEAM_PLUGIN, gameId="1", owner=0)) == 0
    assert state["mode"] == display.Mode(2560, 1440, 165)
    data = session.read()
    assert data["source"] == "playnite" and data["playnite_id"] == "p1" and data["pid"] == owner

    assert launcher.playnite_stop(_payload(id="someone-else")) == 0  # not ours: leave it
    assert session.read() is not None

    assert launcher.playnite_stop(_payload(id="p1")) == 0
    assert state["mode"] == desktop and session.read() is None


def test_steam_launch_options_dont_switch_twice(switching):
    """A Steam game with QRes launch options, started from Playnite with the scripts in place."""
    state, desktop, _ = switching
    launcher.playnite_start(_payload(id="p1", pluginId=STEAM_PLUGIN, gameId="1", owner=0))
    calls_before = list(state["calls"])
    assert launcher.run("steam:1", [sys.executable, "-c", "pass"]) == 0
    assert state["calls"] == calls_before  # the Steam-side launcher neither switched nor restored
    launcher.playnite_stop(_payload(id="p1"))
    assert state["mode"] == desktop


def test_next_playnite_game_takes_over_a_switch_left_behind(switching):
    state, desktop, _ = switching
    launcher.playnite_start(_payload(id="p1", pluginId=STEAM_PLUGIN, gameId="1", owner=0))
    launcher.playnite_start(_payload(id="p2", pluginId=LEGENDARY_PLUGIN, gameId="Quail", owner=0))
    assert state["mode"] == display.Mode(1920, 1080, 165)
    assert session.read()["original"] == desktop.to_dict()  # still the real desktop mode
    launcher.playnite_stop(_payload(id="p2"))
    assert state["mode"] == desktop


def test_unmatched_or_disabled_games_are_left_alone(switching):
    state, desktop, _ = switching
    launcher.playnite_start(_payload(id="p1", name="Unknown Game", installDir=r"C:\x", owner=0))
    launcher.playnite_start(_payload(id="p2", pluginId="aebe8b7c-6dc3-4a66-af31-e7375c6b5e9e", gameId="9", owner=0))
    assert state["calls"] == [] and session.read() is None


def test_guard_leaves_once_its_switch_is_undone(monkeypatch):
    monkeypatch.setattr(launcher, "GUARD_POLL", 0.05)
    monkeypatch.setattr(display, "set_mode", lambda *a: pytest.fail("guard restored"))
    fake = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        token = session.write({"width": 1, "height": 1, "refresh": 1}, "x", owner=fake.pid)
        session.clear(token=token)
        assert launcher.guard(fake.pid, token) == 0  # returns straight away, Playnite still running
        assert psutil.pid_exists(fake.pid)
    finally:
        fake.kill()


# --- plugin install lists ---------------------------------------------------------

def test_standalone_plugins_are_detected(tmp_path, monkeypatch):
    game = tmp_path / "Games" / "Hogwarts"
    game.mkdir(parents=True)
    (game / "HogwartsLegacy.exe").write_bytes(b"MZ")
    legendary = tmp_path / "legendary"
    legendary.mkdir()
    (legendary / "installed.json").write_text(json.dumps({"Quail": {
        "app_name": "Quail", "title": "Hogwarts Legacy", "install_path": str(game),
        "executable": "HogwartsLegacy.exe", "is_dlc": False, "platform": "Windows"}}))
    monkeypatch.setenv("LEGENDARY_CONFIG_PATH", str(legendary))

    nile_root = tmp_path / "nilecfg"
    (nile_root / "nile").mkdir(parents=True)
    (nile_root / "nile" / "installed.json").write_text(json.dumps([{"id": "amzn1.x", "path": str(game)}]))
    monkeypatch.setenv("NILE_CONFIG_PATH", str(nile_root))

    gog_game = tmp_path / "Games" / "Stardew"
    gog_game.mkdir(parents=True)
    (gog_game / "Stardew Valley.exe").write_bytes(b"MZ")
    (gog_game / "goggame-1453375253.info").write_text(json.dumps({"name": "Stardew Valley", "playTasks": [
        {"type": "FileTask", "isPrimary": True, "path": "Stardew Valley.exe", "category": "game"}]}))
    pn = tmp_path / "Playnite"
    (pn / "ExtensionsData" / standalone.GOG_OSS_PLUGIN).mkdir(parents=True)
    (pn / "ExtensionsData" / standalone.GOG_OSS_PLUGIN / "installed.json").write_text(json.dumps({
        "1453375253": {"title": "Stardew Valley", "platform": "windows", "executable": "",
                       "install_path": str(gog_game) + "\\"}}))
    monkeypatch.setattr(playnite, "data_dir", lambda: pn)

    games = {g.id: g for g in standalone.installed_games()}
    assert set(games) == {"legendary:Quail", "nile:amzn1.x", "gog:1453375253"}
    assert games["legendary:Quail"].launch is None and games["legendary:Quail"].store == "legendary"
    assert games["nile:amzn1.x"].store == "nile"
    stardew = games["gog:1453375253"]
    assert stardew.launch["path"] == str(gog_game / "Stardew Valley.exe")
