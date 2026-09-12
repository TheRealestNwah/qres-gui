"""Amazon Games app: installed games are rows in its GameInstallInfo database.

Amazon games need the app for sign-in, so they start through its
amazon-games:// link and are tracked by the exe named in their fuel.json.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .base import Game, guess_main_exe, read_fuel


def database_path() -> Path:
    return (Path(os.environ.get("LOCALAPPDATA", "")) / "Amazon Games" / "Data" / "Games" / "Sql"
            / "GameInstallInfo.sqlite")


def installed_games() -> list[Game]:
    db = database_path()
    if not db.is_file():
        return []
    # Read-only, so we never contend with the Amazon app for its own database.
    with closing(sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)) as conn:
        rows = conn.execute("SELECT Id, InstallDirectory, ProductTitle FROM DbSet WHERE Installed = 1").fetchall()
    games = []
    for game_id, folder, title in rows:
        folder = os.path.normpath(str(folder or ""))
        if not game_id or not os.path.isdir(folder):
            continue
        fuel = read_fuel(folder)
        games.append(Game(
            id=f"amazon:{game_id}",
            name=str(title or os.path.basename(folder)).replace("™", "").replace("®", "").strip(),
            store="amazon",
            install_dir=folder,
            exe=fuel["path"] if fuel else guess_main_exe(folder),
            launch={"type": "uri", "uri": f"amazon-games://play/{game_id}"},
            needs_watch=True,
        ))
    return games
