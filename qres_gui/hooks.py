"""Everything QRes GUI hooks into outside its own folder: Steam launch options
and game shortcuts. Used by "Remove all hooks" and by the uninstaller."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import shortcuts
from .stores.steam import SteamClient, strip_ours


@dataclass
class Hooks:
    steam: dict[str, str] = field(default_factory=dict)  # appid -> launch options with our part removed
    shortcut_files: list[Path] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.steam or self.shortcut_files)


def find(client: SteamClient) -> Hooks:
    """Every hook present, including ones for games that are no longer installed."""
    found = Hooks(shortcut_files=shortcuts.all_game_shortcuts())
    if client.available:
        for appid, options in client.launch_options().items():
            rest, ours = strip_ours(options)
            if ours:
                found.steam[appid] = rest
    return found


def remove(client: SteamClient, found: Hooks) -> Path | None:
    """Remove the hooks; returns the localconfig.vdf backup if Steam was changed.

    Steam goes first, so if it's running (SteamRunningError) nothing is touched.
    """
    backup = client.set_launch_options(found.steam) if found.steam else None
    for path in found.shortcut_files:
        path.unlink(missing_ok=True)
    return backup
