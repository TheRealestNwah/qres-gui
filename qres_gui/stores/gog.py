"""GOG games (Galaxy, Heroic or offline installers all register them here).

GOG games are DRM-free, so the launcher starts the executable directly.
"""

from __future__ import annotations

import os
import winreg

from .base import Game, reg_subkeys

GAMES_KEY = r"SOFTWARE\WOW6432Node\GOG.com\Games"


def installed_games() -> list[Game]:
    games = []
    for key_name, values in reg_subkeys(winreg.HKEY_LOCAL_MACHINE, GAMES_KEY):
        if values.get("dependson"):  # DLC
            continue
        exe = str(values.get("exe") or "")
        path = str(values.get("path") or "")
        if not path or not os.path.isdir(path):
            continue
        games.append(Game(
            id=f"gog:{values.get('gameid') or key_name}",
            name=str(values.get("gamename") or key_name),
            store="gog",
            install_dir=path,
            exe=exe,
            launch={
                "type": "exe",
                "path": exe,
                "args": str(values.get("launchparam") or ""),
                "cwd": str(values.get("workingdir") or path),
            },
        ))
    return games
