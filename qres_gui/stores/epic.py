"""Epic Games Launcher: one JSON manifest (*.item) per installed app.

Epic games generally need the launcher for authentication, so we start them
through its URL scheme and track the game by its executable name.
"""

from __future__ import annotations

import json
import os
import winreg
from pathlib import Path

from .base import Game


def _manifest_dir() -> Path:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Epic Games\EpicGamesLauncher") as key:
            data_dir, _ = winreg.QueryValueEx(key, "AppDataPath")
            return Path(data_dir) / "Manifests"
    except OSError:
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(program_data) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"


def installed_games() -> list[Game]:
    folder = _manifest_dir()
    if not folder.is_dir():
        return []
    games = []
    for item in folder.glob("*.item"):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        app = data.get("AppName", "")
        if not app or data.get("bIsIncompleteInstall"):
            continue
        if data.get("MainGameAppName", app) != app:  # DLC
            continue
        if "games" not in data.get("AppCategories", ["games"]):
            continue
        install = data.get("InstallLocation", "")
        exe = os.path.join(install, data.get("LaunchExecutable", "")) if data.get("LaunchExecutable") else ""
        ns, item_id = data.get("CatalogNamespace", ""), data.get("CatalogItemId", "")
        games.append(Game(
            id=f"epic:{app}",
            name=data.get("DisplayName") or app,
            store="epic",
            install_dir=install,
            exe=exe,
            launch={"type": "uri", "uri": f"com.epicgames.launcher://apps/{ns}%3A{item_id}%3A{app}?action=launch&silent=true"},
            needs_watch=True,
        ))
    return games
