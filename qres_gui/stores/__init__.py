"""Detecting installed games across stores."""

from __future__ import annotations

from . import epic, gog, ubisoft
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
    ]
    games: list[Game] = []
    errors: list[str] = []
    for label, detect in sources:
        try:
            games.extend(detect())
        except Exception as exc:  # one broken store shouldn't hide the others
            errors.append(f"{label}: {exc}")
    return games, errors
