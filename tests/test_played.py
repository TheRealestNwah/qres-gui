"""Last played: what the launcher notes, what Steam knows, and how the list says it."""

import sys
import time

import pytest

from qres_gui import config, launcher, notify, played, vdf
from qres_gui.stores.steam import SteamClient


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setattr(launcher, "EXIT_GRACE", 0.5)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: pytest.fail(f"unexpected notification: {a}"))


def test_record_and_load():
    assert played.load() == {}
    played.record("steam:1", when=1000)
    played.record("gog:2", when=2000)
    played.record("steam:1", when=3000)
    assert played.load() == {"steam:1": 3000.0, "gog:2": 2000.0}
    played.record("")                               # nothing to note
    assert len(played.load()) == 2


def test_a_damaged_file_reads_as_nothing_played_and_is_rewritten():
    played.path().parent.mkdir(parents=True, exist_ok=True)
    played.path().write_text("{not json", encoding="utf-8")
    assert played.load() == {}
    played.record("steam:1", when=5)
    assert played.load() == {"steam:1": 5.0}


def test_record_never_raises(monkeypatch):
    monkeypatch.setattr(played, "path", lambda: played.paths.app_dir() / "missing-folder" / "played.json")
    played.record("steam:1")                        # the folder doesn't exist: logged, not raised


def local(year, month, day, hour=12):
    return time.mktime((year, month, day, hour, 0, 0, 0, 0, -1))


@pytest.mark.parametrize("when, expected", [
    (0, "—"),
    (local(2026, 9, 16, 1), "Today"),
    (local(2026, 9, 15, 23), "Yesterday"),
    (local(2026, 9, 13), "3 days ago"),
    (local(2026, 9, 10), "6 days ago"),
    (local(2026, 9, 9), "9 Sep 2026"),
    (local(2025, 12, 31), "31 Dec 2025"),
])
def test_describe(when, expected):
    assert played.describe(when, now=local(2026, 9, 16, 22)) == expected


def test_the_launcher_notes_every_start_switching_or_not():
    cfg = config.load()
    cfg["games"]["steam:1"] = {"enabled": False, "watch": []}
    config.save(cfg)
    before = time.time()
    assert launcher.run("steam:1", [sys.executable, "-c", "pass"]) == 0
    assert played.load()["steam:1"] >= before - 1


def test_steam_last_played_comes_from_localconfig(tmp_path):
    root = tmp_path / "Steam"
    (root / "config").mkdir(parents=True)
    (root / "config" / "loginusers.vdf").write_text(
        '"users"\n{\n\t"76561197960265738"\n\t{\n\t\t"MostRecent"\t\t"1"\n\t}\n}\n', encoding="utf-8")
    config_dir = root / "userdata" / "10" / "config"
    config_dir.mkdir(parents=True)
    apps = {"10": {"LastPlayed": "1757000000", "LaunchOptions": "-novid"},
            "20": {"LastPlayed": "0"},              # installed, never played
            "30": {"LaunchOptions": "x"}}
    body = "".join(f'\t\t\t\t\t"{a}"\n\t\t\t\t\t{{\n' +
                   "".join(f'\t\t\t\t\t\t"{k}"\t\t"{vdf._escape(v)}"\n' for k, v in values.items()) +
                   "\t\t\t\t\t}\n" for a, values in apps.items())
    (config_dir / "localconfig.vdf").write_text(
        '"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
        f'\t\t\t\t"apps"\n\t\t\t\t{{\n{body}\t\t\t\t}}\n\t\t\t}}\n\t\t}}\n\t}}\n}}\n', encoding="utf-8")
    client = SteamClient(root)
    assert client.last_played() == {"10": 1757000000.0}
    assert client.launch_options() == {"10": "-novid", "20": "", "30": "x"}
