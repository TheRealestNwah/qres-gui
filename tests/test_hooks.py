"""Hook discovery/removal against a fake Steam install and temporary shortcut folders."""

import json

import pytest

from qres_gui import hooks, launcher, notify, playnite, shortcuts, vdf
from qres_gui.stores import steam
from qres_gui.stores.steam import SteamClient, SteamRunningError

OURS = steam.launch_prefix([r"C:\Apps\QResGUI\QResLauncher.exe"], "steam:10")


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    root = tmp_path / "Steam"
    (root / "config").mkdir(parents=True)
    (root / "config" / "loginusers.vdf").write_text(
        '"users"\n{\n\t"76561197960265738"\n\t{\n\t\t"MostRecent"\t\t"1"\n\t}\n}\n', encoding="utf-8")
    config_dir = root / "userdata" / "10" / "config"
    config_dir.mkdir(parents=True)
    apps = {
        "10": f"{OURS} %command% -novid",       # ours, with the user's own option
        "20": '"D:\\x\\loader.exe" %command%',  # someone else's wrapper: untouched
        "30": f"{OURS} %command%",               # ours only
    }
    body = "".join(f'\t\t\t\t\t"{a}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"LaunchOptions"\t\t"{vdf._escape(o)}"\n\t\t\t\t\t}}\n'
                   for a, o in apps.items())
    (config_dir / "localconfig.vdf").write_text(
        '"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
        f'\t\t\t\t"apps"\n\t\t\t\t{{\n{body}\t\t\t\t}}\n\t\t\t}}\n\t\t}}\n\t}}\n}}\n', encoding="utf-8")

    desktop, menu = tmp_path / "Desktop", tmp_path / "Programs" / "QRes GUI"
    desktop.mkdir()
    menu.mkdir(parents=True)
    for path in (desktop / "Stardew Valley (QRes).lnk", menu / "Saints Row 2 (QRes).lnk",
                 desktop / "Stardew Valley.lnk", menu / "QRes GUI.lnk"):
        path.write_bytes(b"lnk")
    monkeypatch.setattr(shortcuts, "desktop_dir", lambda: desktop)
    monkeypatch.setattr(shortcuts, "start_menu_dir", lambda: menu)
    monkeypatch.setattr(SteamClient, "is_running", staticmethod(lambda: False))
    monkeypatch.setattr(playnite, "config_path", lambda: None)  # keep the real Playnite out of it
    return SteamClient(root), desktop, menu


def test_find_only_our_hooks(fake_env):
    client, desktop, menu = fake_env
    found = hooks.find(client)
    assert found.steam == {"10": "-novid", "30": ""}
    assert sorted(p.name for p in found.shortcut_files) == ["Saints Row 2 (QRes).lnk", "Stardew Valley (QRes).lnk"]


def test_remove_restores_user_options_and_keeps_other_files(fake_env):
    client, desktop, menu = fake_env
    backup = hooks.remove(client, hooks.find(client))
    assert backup.exists()
    assert client.launch_options() == {"10": "-novid", "20": '"D:\\x\\loader.exe" %command%', "30": ""}
    assert sorted(p.name for p in desktop.iterdir()) == ["Stardew Valley.lnk"]
    assert sorted(p.name for p in menu.iterdir()) == ["QRes GUI.lnk"]
    assert not hooks.find(client)


def test_steam_running_touches_nothing(fake_env, monkeypatch):
    client, desktop, _ = fake_env
    monkeypatch.setattr(SteamClient, "is_running", staticmethod(lambda: True))
    with pytest.raises(SteamRunningError):
        hooks.remove(client, hooks.find(client))
    assert (desktop / "Stardew Valley (QRes).lnk").exists()
    assert client.launch_options()["30"] == f"{OURS} %command%"


def test_remove_hooks_command_reports_and_signals_steam_running(fake_env, monkeypatch, tmp_path):
    client, _, _ = fake_env
    monkeypatch.setattr(notify, "notify", lambda *a, **k: pytest.fail(f"unexpected notification: {a}"))
    monkeypatch.setattr(steam, "find_steam", lambda: client.root)
    report = tmp_path / "report.json"

    monkeypatch.setattr(SteamClient, "is_running", staticmethod(lambda: True))
    assert launcher.remove_hooks(str(report)) == launcher.EXIT_STEAM_RUNNING
    assert json.loads(report.read_text())["status"] == "steam-running"

    monkeypatch.setattr(SteamClient, "is_running", staticmethod(lambda: False))
    assert launcher.remove_hooks(str(report)) == 0
    data = json.loads(report.read_text())
    assert data["status"] == "ok" and data["steam"] == ["10", "30"] and len(data["shortcuts"]) == 2
