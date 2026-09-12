"""Everything QRes GUI hooks into outside its own folder: Steam launch options,
Playnite's global scripts and game shortcuts. Used by "Remove all hooks" and by
the uninstaller."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import playnite, shortcuts
from .stores.steam import SteamClient, SteamRunningError, strip_ours


@dataclass
class Hooks:
    steam: dict[str, str] = field(default_factory=dict)  # appid -> launch options with our part removed
    shortcut_files: list[Path] = field(default_factory=list)
    playnite: bool = False

    def __bool__(self) -> bool:
        return bool(self.steam or self.shortcut_files or self.playnite)


def find(client: SteamClient) -> Hooks:
    """Every hook present, including ones for games that are no longer installed."""
    found = Hooks(shortcut_files=shortcuts.all_game_shortcuts(),
                  playnite=playnite.state(["?"]) in ("installed", "outdated"))
    if client.available:
        for appid, options in client.launch_options().items():
            rest, ours = strip_ours(options)
            if ours:
                found.steam[appid] = rest
    return found


def remove(client: SteamClient, found: Hooks) -> Path | None:
    """Remove the hooks; returns the localconfig.vdf backup if Steam was changed.

    Checks up front that neither Steam nor Playnite needs to be closed first
    (SteamRunningError / PlayniteRunningError), so a refusal touches nothing.
    """
    if found.steam and client.is_running():
        raise SteamRunningError("Steam is running. Close it first - it overwrites localconfig.vdf on exit.")
    if found.playnite and playnite.is_running():
        raise playnite.PlayniteRunningError("Playnite is running. Close it first - it saves its settings on exit.")
    backup = client.set_launch_options(found.steam) if found.steam else None
    if found.playnite:
        playnite.uninstall()
    for path in found.shortcut_files:
        path.unlink(missing_ok=True)
    return backup
