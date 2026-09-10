"""Ubisoft Connect: install folders are registered per game id.

The registry doesn't record the executable, so we guess one; the user can
correct it in the "Game process" section.
"""

from __future__ import annotations

import os
import winreg

from .base import Game, guess_main_exe, reg_subkeys

INSTALLS_KEY = r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"
UNINSTALL_KEY = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"


def installed_games() -> list[Game]:
    installs = reg_subkeys(winreg.HKEY_LOCAL_MACHINE, INSTALLS_KEY)
    if not installs:
        return []
    names = {
        key[len("Uplay Install "):]: str(values.get("displayname") or "")
        for key, values in reg_subkeys(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY)
        if key.startswith("Uplay Install ")
    }
    games = []
    for game_id, values in installs:
        folder = os.path.normpath(str(values.get("installdir") or ""))
        if not os.path.isdir(folder):
            continue
        games.append(Game(
            id=f"ubisoft:{game_id}",
            name=names.get(game_id) or os.path.basename(folder),
            store="ubisoft",
            install_dir=folder,
            exe=guess_main_exe(folder),
            launch={"type": "uri", "uri": f"uplay://launch/{game_id}/0"},
            needs_watch=True,
        ))
    return games
