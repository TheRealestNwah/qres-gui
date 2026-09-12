"""Stores run through legendary, nile and gogdl outside Heroic, such as
hawkeye116477's Playnite plugins (Legendary, Nile, GOG OSS).

Epic and Amazon games need those tools' sign-in, so QRes can't start them on
its own: they're meant to be started from Playnite, where its scripts do the
switching. GOG games are DRM-free and start directly.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import playnite
from .base import Game, guess_main_exe, legendary_installs, nile_installs, read_goggame_info, read_json_lenient

GOG_OSS_PLUGIN = "03689811-3f33-4dfb-a121-2ee168fb9a5c"


def legendary_dir() -> Path:
    if os.environ.get("LEGENDARY_CONFIG_PATH"):
        return Path(os.environ["LEGENDARY_CONFIG_PATH"])
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "legendary"


def nile_dir() -> Path:
    if os.environ.get("NILE_CONFIG_PATH"):
        return Path(os.environ["NILE_CONFIG_PATH"]) / "nile"
    return Path(os.environ.get("XDG_CONFIG_HOME") or os.environ.get("APPDATA", "")) / "nile"


def gog_oss_installed() -> Path | None:
    folder = playnite.data_dir()
    return folder / "ExtensionsData" / GOG_OSS_PLUGIN / "installed.json" if folder else None


def installed_games() -> list[Game]:
    games = [Game(id=f"legendary:{g['app']}", name=g["title"], store="legendary", install_dir=g["install"], exe=g["exe"])
             for g in legendary_installs(legendary_dir() / "installed.json")]
    games += [Game(id=f"nile:{g['app']}", name=g["title"], store="nile", install_dir=g["install"], exe=g["exe"])
              for g in nile_installs(nile_dir())]
    games += _gog_oss()
    return games


def _gog_oss() -> list[Game]:
    path = gog_oss_installed()
    data = read_json_lenient(path) if path else None
    games = []
    for game_id, info in (data.items() if isinstance(data, dict) else []):
        if not isinstance(info, dict) or str(info.get("platform") or "windows").lower() != "windows":
            continue
        install = os.path.normpath(str(info.get("install_path") or ""))
        if not os.path.isdir(install):
            continue
        details = read_goggame_info(install, game_id) or {}
        exe = details.get("path") or (os.path.join(install, info["executable"]) if info.get("executable")
                                      else guess_main_exe(install))
        games.append(Game(
            id=f"gog:{game_id}", name=str(info.get("title") or details.get("name") or os.path.basename(install)),
            store="gog", install_dir=install, exe=exe,
            launch={"type": "exe", "path": exe, "args": details.get("args", ""), "cwd": details.get("cwd") or install},
        ))
    return games
