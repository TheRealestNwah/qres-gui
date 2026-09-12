"""Heroic and Amazon detection against fake installs built from each tool's file formats."""

import json
import os
import sqlite3
from contextlib import closing

import pytest

from qres_gui import stores
from qres_gui.stores import amazon, base, gog, heroic

REAL_STARDEW = r"D:\Heroic\Stardew Valley"


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def _game_dir(tmp_path, name, exe="Game.exe"):
    folder = tmp_path / "Games" / name
    folder.mkdir(parents=True)
    (folder / exe).write_bytes(b"MZ")
    return folder


# --- helpers -----------------------------------------------------------------

def test_lenient_json_handles_json5_bits(tmp_path):
    path = tmp_path / "fuel.json"
    path.write_bytes(
        b'\xef\xbb\xbf{ // BOM, comments and trailing commas\n'
        b'  "Main": { "Command": "bin/Game.exe", /* inline */ "Args": ["-a", "b c",], },\n'
        b'  "Url": "http://example.com/x//y",\n}\n')
    data = base.read_json_lenient(path)
    assert data["Main"]["Args"] == ["-a", "b c"] and data["Url"] == "http://example.com/x//y"


def test_read_fuel(tmp_path):
    folder = _game_dir(tmp_path, "Amz")
    _write(folder / "fuel.json", {"SchemaVersion": "2", "Main": {
        "Command": "bin\\Game.exe", "Args": ["-x", "two words"], "WorkingSubdirOverride": "bin"}})
    fuel = base.read_fuel(str(folder))
    assert fuel == {"path": str(folder / "bin" / "Game.exe"), "args": '-x "two words"', "cwd": str(folder / "bin")}


@pytest.mark.skipif(not os.path.isfile(os.path.join(REAL_STARDEW, "goggame-1453375253.info")),
                    reason="no local GOG Stardew Valley install")
def test_read_goggame_info_real_file():
    info = base.read_goggame_info(REAL_STARDEW, "1453375253")
    assert info["name"] == "Stardew Valley"
    assert info["path"] == os.path.join(REAL_STARDEW, "Stardew Valley.exe")


# --- Heroic --------------------------------------------------------------------

@pytest.fixture
def fake_heroic(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    root = tmp_path / "AppData" / "heroic"
    hogwarts = _game_dir(tmp_path, "HogwartsLegacy", "HogwartsLegacy.exe")
    _write(root / "legendaryConfig" / "legendary" / "installed.json", {
        "fa4240e57a3c46b39f169041b7811293": {
            "app_name": "fa4240e57a3c46b39f169041b7811293", "title": "Hogwarts Legacy",
            "install_path": str(hogwarts), "executable": "HogwartsLegacy.exe", "is_dlc": False,
            "platform": "Windows", "version": "1"},
        "dlc1": {"app_name": "dlc1", "title": "Some DLC", "install_path": str(hogwarts), "is_dlc": True},
        "gone": {"app_name": "gone", "title": "Uninstalled", "install_path": str(tmp_path / "nope")},
    })
    amz = _game_dir(tmp_path, "AmazonGame")
    _write(amz / "fuel.json", '{"Main": {"Command": "Game.exe",},}')
    _write(root / "nile_config" / "nile" / "installed.json",
           [{"id": "amzn1.adg.product.abc", "version": "v1", "path": str(amz), "size": 1}])
    _write(root / "nile_config" / "nile" / "library.json",
           [{"id": "ent", "product": {"id": "amzn1.adg.product.abc", "title": "Amazon Test Game"}}])
    gog_dir = _game_dir(tmp_path, "GogGame", "Play.exe")
    _write(gog_dir / "goggame-111.info", {"name": "GOG Test Game", "playTasks": [
        {"type": "URLTask", "link": "http://x"},
        {"type": "FileTask", "isPrimary": True, "path": "Play.exe", "arguments": "-fast", "category": "game"}]})
    _write(root / "gog_store" / "installed.json", {"installed": [
        {"appName": "111", "install_path": str(gog_dir), "platform": "windows", "is_dlc": False},
        {"appName": "222", "install_path": str(gog_dir), "platform": "linux"}]})
    return tmp_path


def test_heroic_detects_all_three_runners(fake_heroic):
    games = {g.id: g for g in heroic.installed_games()}
    assert set(games) == {"heroic:legendary:fa4240e57a3c46b39f169041b7811293",
                          "heroic:nile:amzn1.adg.product.abc", "heroic:gog:111"}

    epic = games["heroic:legendary:fa4240e57a3c46b39f169041b7811293"]
    assert epic.name == "Hogwarts Legacy" and epic.needs_watch
    assert epic.launch["uri"] == "heroic://launch?appName=fa4240e57a3c46b39f169041b7811293&runner=legendary"
    assert epic.exe.endswith("HogwartsLegacy.exe")

    amz = games["heroic:nile:amzn1.adg.product.abc"]
    assert amz.name == "Amazon Test Game" and amz.exe.endswith("Game.exe")
    assert amz.launch["uri"] == "heroic://launch?appName=amzn1.adg.product.abc&runner=nile"

    gog_game = games["heroic:gog:111"]
    assert gog_game.name == "GOG Test Game" and not gog_game.needs_watch
    assert gog_game.launch == {"type": "exe", "path": gog_game.exe, "args": "-fast",
                               "cwd": gog_game.install_dir}


def test_heroic_gog_game_also_in_registry_is_listed_once(fake_heroic, monkeypatch):
    monkeypatch.setattr(gog, "installed_games", lambda: [base.Game(id="gog:111", name="GOG Test Game", store="gog")])
    monkeypatch.setattr(amazon, "installed_games", list)
    monkeypatch.setattr(stores.epic, "installed_games", list)
    monkeypatch.setattr(stores.ubisoft, "installed_games", list)
    client = stores.SteamClient(root=fake_heroic / "no-steam")
    monkeypatch.setattr(type(client), "available", property(lambda self: False))
    games, errors = stores.detect_all(client)
    ids = sorted(g.id for g in games)
    assert errors == [] and "gog:111" in ids and "heroic:gog:111" not in ids
    assert "heroic:nile:amzn1.adg.product.abc" in ids


def test_no_heroic_install_means_no_games(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert heroic.installed_games() == []


# --- Amazon Games app ------------------------------------------------------------

def test_amazon_app_database(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    game = _game_dir(tmp_path, "Amazon Title", "Title.exe")
    _write(game / "fuel.json", {"Main": {"Command": "Title.exe"}})
    db = amazon.database_path()
    db.parent.mkdir(parents=True)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE DbSet (Id TEXT, InstallDirectory TEXT, ProductTitle TEXT, Installed INTEGER)")
        conn.executemany("INSERT INTO DbSet VALUES (?, ?, ?, ?)", [
            ("amzn1.adg.product.1", str(game), "Amazon Title™", 1),
            ("amzn1.adg.product.2", str(game), "Not Installed", 0),
            ("amzn1.adg.product.3", str(tmp_path / "missing"), "Deleted Folder", 1),
        ])
        conn.commit()
    [found] = amazon.installed_games()
    assert found.id == "amazon:amzn1.adg.product.1" and found.name == "Amazon Title"
    assert found.launch == {"type": "uri", "uri": "amazon-games://play/amzn1.adg.product.1"}
    assert found.exe == str(game / "Title.exe") and found.needs_watch


def test_no_amazon_app_means_no_games(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert amazon.installed_games() == []
