"""EA app, Battle.net, Xbox and Playnite-seen detection against fake installs."""

import base64
import json
from pathlib import Path

import pytest

from qres_gui import config, launcher, notify, playnite
from qres_gui.stores import Game, battlenet, ea, playnite_games, xbox

NEW_MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<DiPManifest version="4.0">
  <gameTitles><gameTitle locale="de_DE">Spiel</gameTitle><gameTitle locale="en_US">Test Game</gameTitle></gameTitles>
  <contentIDs><contentID>1026023</contentID><contentID>1026024</contentID></contentIDs>
  <runtime>
    <launcher><filePath>[HKEY_LOCAL_MACHINE\\SOFTWARE\\EA Games\\Test Game\\Install Dir]TestTrial.exe</filePath>
      <trial>true</trial></launcher>
    <launcher><filePath>[HKEY_LOCAL_MACHINE\\SOFTWARE\\EA Games\\Test Game\\Install Dir]bin\\Test.exe</filePath>
      <parameters>-dx12</parameters><trial>false</trial></launcher>
  </runtime>
</DiPManifest>"""

OLD_MANIFEST = """<game manifestVersion="1.0">
  <metadata><localeInfo locale="en_US"><title>Old Game</title></localeInfo></metadata>
  <contentIDs><contentID>70001</contentID></contentIDs>
  <runtime><launcher><filePath>[HKEY_LOCAL_MACHINE\\SOFTWARE\\Origin Games\\70001\\Install Dir]old.exe</filePath></launcher></runtime>
</game>"""


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))


def test_ea_installerdata_both_formats(tmp_path):
    new, old = tmp_path / "new.xml", tmp_path / "old.xml"
    new.write_text(NEW_MANIFEST, encoding="utf-8")
    old.write_text(OLD_MANIFEST, encoding="utf-8")
    assert ea.read_installerdata(new) == {"title": "Test Game", "exe": "bin\\Test.exe", "args": "-dx12",
                                          "content_id": "1026023"}
    assert ea.read_installerdata(old) == {"title": "Old Game", "exe": "old.exe", "args": "", "content_id": "70001"}


def test_ea_games_from_uninstall_entries(tmp_path, monkeypatch):
    folder = tmp_path / "EA Games" / "Test Game"
    (folder / "__Installer").mkdir(parents=True)
    (folder / "__Installer" / "installerdata.xml").write_text(NEW_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(ea, "uninstall_entries", lambda: [
        ("{GUID-1}", {"displayname": "Test Game", "installlocation": f'"{folder}\\"'}),  # quoted, trailing slash
        ("Other", {"displayname": "Not EA", "installlocation": str(tmp_path)}),
    ])
    [game] = ea.installed_games()
    assert game.id == "ea:1026023" and game.name == "Test Game" and game.store == "ea"
    assert game.launch == {"type": "exe", "path": str(folder / "bin" / "Test.exe"), "args": "-dx12", "cwd": str(folder)}
    assert game.needs_watch


def test_battlenet_games_from_uninstall_entries(tmp_path, monkeypatch):
    folder = tmp_path / "Overwatch"
    folder.mkdir()
    (folder / "Overwatch.exe").write_bytes(b"MZ" * 100)
    monkeypatch.setattr(battlenet, "uninstall_entries", lambda: [
        ("Overwatch", {"displayname": "Overwatch", "installlocation": str(folder),
                       "uninstallstring": '"C:\\ProgramData\\Battle.net\\Agent\\Blizzard Uninstaller.exe" --lang=enUS --uid=prometheus --displayname="Overwatch"'}),
        ("Battle.net", {"displayname": "Battle.net", "installlocation": str(tmp_path),
                        "uninstallstring": '"C:\\Program Files (x86)\\Battle.net\\Battle.net Uninstaller.exe"'}),
    ])
    [game] = battlenet.installed_games()
    assert game.id == "battlenet:prometheus" and game.name == "Overwatch"
    assert game.launch is None and game.exe.endswith("Overwatch.exe")


def test_xbox_gaming_root_and_config(tmp_path, monkeypatch):
    root_file = tmp_path / ".GamingRoot"
    root_file.write_bytes(b"RGBX\x01\x00\x00\x00" + "Xbox Games\x00".encode("utf-16-le"))
    assert xbox.parse_gaming_root(root_file) == [Path(tmp_path.anchor) / "Xbox Games"]

    games_root = tmp_path / "Xbox Games"
    content = games_root / "Forza Horizon 5" / "Content"
    content.mkdir(parents=True)
    (content / "MicrosoftGame.config").write_text("""<?xml version="1.0"?>
<Game configVersion="1">
  <Identity Name="Microsoft.624F8B84B80" Publisher="CN=Microsoft" Version="1.0.0.0"/>
  <ExecutableList>
    <Executable Name="ForzaHorizon5_Xbox.exe" Id="GameXbox" TargetDeviceFamily="Scarlett"/>
    <Executable Name="ForzaHorizon5.exe" Id="Game" TargetDeviceFamily="PC"/>
  </ExecutableList>
  <ShellVisuals DefaultDisplayName="Forza Horizon 5" PublisherDisplayName="Xbox Game Studios"/>
</Game>""", encoding="utf-8")
    (games_root / "GameSave").mkdir()  # the Xbox app keeps this folder around; not a game
    monkeypatch.setattr(xbox, "gaming_roots", lambda: [games_root])
    monkeypatch.setattr(xbox, "_package_families", lambda: {"Microsoft.624F8B84B80": "Microsoft.624F8B84B80_8wekyb3d8bbwe"})
    [game] = xbox.installed_games()
    assert game.id == "xbox:Microsoft.624F8B84B80" and game.name == "Forza Horizon 5"
    assert game.exe == str(content / "ForzaHorizon5.exe") and game.install_dir == str(content)
    assert game.launch == {"type": "uri", "uri": "shell:AppsFolder\\Microsoft.624F8B84B80_8wekyb3d8bbwe!Game"}
    assert game.needs_watch


def test_real_gaming_roots_parse():
    for root in xbox.gaming_roots():  # whatever this PC has; must not raise
        assert root.anchor


# --- Playnite-seen games ----------------------------------------------------------

def test_unknown_playnite_game_is_remembered_and_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "notify", lambda *a, **k: pytest.fail(f"unexpected notification: {a}"))
    folder = tmp_path / "Hogwarts"
    folder.mkdir()
    payload = {"id": "aaaa-1", "gameId": "fa42", "pluginId": "EAD65C3B-2F8F-4E37-B4E6-B3DE6BE540C6",
               "name": "Hogwarts Legacy", "installDir": str(folder), "owner": 0}
    assert launcher.playnite_start(base64.b64encode(json.dumps(payload).encode()).decode()) == 0
    assert playnite.seen()["aaaa-1"]["name"] == "Hogwarts Legacy"

    [game] = playnite_games.games([])
    assert game.id == "playnite:aaaa-1" and game.store == "playnite" and game.launch is None

    # Once it has a profile, Playnite's next start matches it directly.
    game_id, _ = playnite.match({"games": {"playnite:aaaa-1": {"name": "x"}}}, payload)
    assert game_id == "playnite:aaaa-1"

    playnite.forget("aaaa-1")
    assert playnite_games.games([]) == []


def test_playnite_seen_games_already_listed_elsewhere_are_skipped(tmp_path):
    folder = tmp_path / "MGS4"
    folder.mkdir()
    playnite.remember({"id": "p-steam", "gameId": "2492670", "pluginId": "cb91dfc9-b977-43bf-8e70-55f46e410fab",
                       "name": "MGS4", "installDir": r"C:\elsewhere"})
    playnite.remember({"id": "p-dir", "name": "Same Folder", "installDir": str(folder)})
    playnite.remember({"id": "p-gone", "name": "Uninstalled", "installDir": str(tmp_path / "gone")})
    known = [Game(id="steam:2492670", name="MGS4", store="steam", install_dir=r"D:\x"),
             Game(id="gog:1", name="Other", store="gog", install_dir=str(folder))]
    assert playnite_games.games(known) == []
