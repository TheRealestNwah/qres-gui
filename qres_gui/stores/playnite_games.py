"""Games Playnite has started that no store detection covers.

The launcher remembers every game Playnite starts without a QRes profile
(see playnite.remember). Listed here unless another store already lists
the same game, by store ID or install folder.
"""

from __future__ import annotations

import os

from .. import playnite
from .base import Game


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)).rstrip("\\/") if path else ""


def games(known: list[Game]) -> list[Game]:
    known_ids = {g.id for g in known}
    known_dirs = {_norm(g.install_dir) for g in known if g.install_dir}
    out = []
    for game_id, info in playnite.seen().items():
        folder = str(info.get("installDir") or "")
        prefix = playnite.PLUGIN_PREFIXES.get(str(info.get("pluginId") or ""))
        if prefix and f"{prefix}:{info.get('gameId')}" in known_ids:
            continue
        if folder and (_norm(folder) in known_dirs or not os.path.isdir(folder)):
            continue  # listed elsewhere, or uninstalled since
        out.append(Game(id=f"playnite:{game_id}", name=str(info.get("name") or game_id),
                        store="playnite", install_dir=folder))
    return out
