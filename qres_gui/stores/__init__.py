"""Detecting installed games across stores."""

from __future__ import annotations

from . import amazon, epic, gog, heroic, standalone, ubisoft
from .base import STORE_LABELS, Game, guess_main_exe
from .steam import SteamClient

__all__ = ["Game", "STORE_LABELS", "SteamClient", "detect_all", "guess_main_exe"]


def detect_all(steam: SteamClient) -> tuple[list[Game], list[str]]:
    """Games from every supported store, plus one error message per store that failed."""
    sources = [
        ("Steam", steam.installed_games if steam.available else list),
        ("GOG", gog.installed_games),
        ("Epic Games", epic.installed_games),
        ("Ubisoft Connect", ubisoft.installed_games),
        ("Heroic", heroic.installed_games),
        ("Amazon Games", amazon.installed_games),
        ("Legendary / nile / GOG OSS", standalone.installed_games),
    ]
    games: list[Game] = []
    errors: list[str] = []
    for label, detect in sources:
        try:
            games.extend(detect())
        except Exception as exc:  # one broken store shouldn't hide the others
            errors.append(f"{label}: {exc}")
    # GOG installs made by Heroic or GOG OSS usually register with Windows too;
    # list each game once, preferring the earlier (registry) entry.
    registered = {g.id.split(":", 1)[1] for g in games if g.store == "gog"}
    games = [g for g in games if not (g.id.startswith("heroic:gog:") and g.id.split(":", 2)[2] in registered)]
    unique: dict[str, Game] = {}
    for game in games:
        unique.setdefault(game.id, game)
    return list(unique.values()), errors
