"""Heroic Games Launcher: its Epic (legendary), Amazon (nile) and GOG installs.

Everything lives under %APPDATA%\\heroic. Epic and Amazon games need their
store's sign-in, so they start through Heroic's heroic:// link and are tracked
by exe name. GOG games are DRM-free and start directly, like other GOG installs.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from .base import Game, guess_main_exe, legendary_installs, nile_installs, read_goggame_info, read_json_lenient

RUNNER_STORES = {"legendary": "Epic", "nile": "Amazon", "gog": "GOG"}


def heroic_dir() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "heroic"


def launch_uri(runner: str, app_name: str) -> str:
    return f"heroic://launch?appName={quote(app_name, safe='')}&runner={runner}"


def installed_games() -> list[Game]:
    root = heroic_dir()
    if not root.is_dir():
        return []
    return _legendary(root) + _nile(root) + _gog(root)


def _via_heroic(runner: str, app_name: str, name: str, install_dir: str, exe: str) -> Game:
    return Game(
        id=f"heroic:{runner}:{app_name}",
        name=name,
        store="heroic",
        install_dir=install_dir,
        exe=exe,
        launch={"type": "uri", "uri": launch_uri(runner, app_name)},
        needs_watch=True,
    )


def _windows(platform) -> bool:
    return str(platform or "windows").lower() in ("windows", "win32")


def _legendary(root: Path) -> list[Game]:
    return [_via_heroic("legendary", g["app"], g["title"], g["install"], g["exe"])
            for g in legendary_installs(root / "legendaryConfig" / "legendary" / "installed.json")]


def _nile(root: Path) -> list[Game]:
    return [_via_heroic("nile", g["app"], g["title"], g["install"], g["exe"])
            for g in nile_installs(root / "nile_config" / "nile")]


def _gog(root: Path) -> list[Game]:
    data = read_json_lenient(root / "gog_store" / "installed.json")
    entries = data.get("installed") if isinstance(data, dict) else None
    games = []
    for entry in (entries if isinstance(entries, list) else []):
        if not isinstance(entry, dict) or entry.get("is_dlc") or not _windows(entry.get("platform")):
            continue
        app, install = str(entry.get("appName") or ""), str(entry.get("install_path") or "")
        if not app or not os.path.isdir(install):
            continue
        info = read_goggame_info(install, app) or {}
        name = info.get("name") or os.path.basename(install)
        if info.get("path"):
            games.append(Game(
                id=f"heroic:gog:{app}", name=name, store="heroic", install_dir=install, exe=info["path"],
                launch={"type": "exe", "path": info["path"], "args": info["args"], "cwd": info["cwd"]},
            ))
        else:
            games.append(_via_heroic("gog", app, name, install, guess_main_exe(install)))
    return games
