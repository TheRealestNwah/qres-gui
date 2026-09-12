"""Battle.net installs.

Blizzard games register an "Apps & features" entry whose uninstall command
runs Battle.net's uninstaller with --uid=<product>. They need Battle.net to
start, so QRes lists them for their resolution profile and they're started
from Battle.net or Playnite.
"""

from __future__ import annotations

import os
import re

from .base import Game, clean_path, guess_main_exe, uninstall_entries

_UID = re.compile(r"--uid=([\w.-]+)", re.I)


def installed_games() -> list[Game]:
    games: dict[str, Game] = {}
    for _key, values in uninstall_entries():
        uninstall = str(values.get("uninstallstring") or "")
        match = _UID.search(uninstall)
        if not match or "battle.net" not in uninstall.lower():
            continue
        folder = clean_path(values.get("installlocation"))
        if not folder or not os.path.isdir(folder):
            continue
        uid = match.group(1).lower()
        games.setdefault(uid, Game(
            id=f"battlenet:{uid}",
            name=str(values.get("displayname") or os.path.basename(folder)),
            store="battlenet",
            install_dir=folder,
            exe=guess_main_exe(folder),
        ))
    return list(games.values())
