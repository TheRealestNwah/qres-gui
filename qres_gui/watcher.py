"""Noticing a set-up game that starts without QRes, so it can still switch.

Steam launch options, Playnite's scripts and QRes shortcuts put the launcher in
front of a game. Everything else - the Xbox app, EA app, Ubisoft Connect,
Battle.net, a store's own Play button - starts the game directly. While QRes
GUI runs with "Switch games however they're started" on, this watches for new
processes and recognises a game by where its exe lives: inside the install
folder of a profile with switching on (or by a watched process name). The GUI
then starts `QResLauncher adopt`, which switches while the game runs and back
once it has gone.

The switch lands a moment after the game starts rather than before it, so a
game that reads the desktop size in its first second may not see it; hooks
remain the better way wherever a store has them.

Pure Python with no Qt, so it can be tested without a window.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

import psutil

log = logging.getLogger(__name__)

MAX_DEPTH = 6   # folders below the install folder searched for exes, like the guard's

# Programs that live in game folders but aren't the game: installers for runtimes,
# crash reporters, uninstallers, anti-cheat setup. Starting one mustn't switch.
_NOT_THE_GAME = re.compile(
    r"^(unitycrashhandler(32|64)?|crashreportclient|crashpad_handler|crashreporter|bugsplat.*|"
    r"vc_?redist.*|vcredist.*|dxsetup|dotnetfx.*|ndp\d+.*|physx.*|oalinst|uninst.*|unins\d+|"
    r"easyanticheat_(eos_)?setup|battleye_?installer|setup|install(er)?|update(r)?|"
    r"ue4prereqsetup.*|ueprereqsetup.*)\.exe$")
_NOT_GAME_FOLDERS = {"_commonredist", "commonredist", "redist", "redistributables", "__installer",
                     "directx", "dotnet", "vcredist", "support", "installers", "prereqs"}


def is_helper(name: str, path: str = "") -> bool:
    """Whether a process is a game folder's helper rather than the game."""
    if _NOT_THE_GAME.match(name.lower()):
        return True
    parts = {part.lower() for part in re.split(r"[\\/]", path)[:-1]}
    return bool(parts & _NOT_GAME_FOLDERS)


def usable_folder(folder: str) -> bool:
    """A folder specific enough to say "this is the game": not a drive, a library, or Program Files."""
    if not folder or not os.path.isdir(folder):
        return False
    norm = os.path.normcase(os.path.normpath(folder)).rstrip("\\/")
    drive, rest = os.path.splitdrive(norm)
    depth = len([p for p in re.split(r"[\\/]", rest) if p])
    if depth < 2:
        return False
    tail = norm.rsplit(os.sep, 2)
    broad = {"common", "games", "program files", "program files (x86)", "windowsapps", "xboxgames", "steamlibrary",
             "epic games", "gog galaxy", "ubisoft game launcher", "ea games", "origin games", "users"}
    return tail[-1] not in broad


@dataclass
class Target:
    game_id: str
    folder: str                                   # normcase'd install folder, or "" for watch names only
    watch: set[str] = field(default_factory=set)  # lower-case process names
    exes: set[str] = field(default_factory=set)   # lower-case exe names found under the folder


def build_targets(games: list[tuple[str, str, list[str]]]) -> list[Target]:
    """(game id, install folder, watched names) for each game with switching on -> what to look for.

    Walks each folder once, which can take a moment for big games; the GUI does
    it off the UI thread.
    """
    targets = []
    for game_id, folder, watch in games:
        names = {str(w).strip().lower() for w in watch or [] if str(w).strip()}
        target = Target(game_id, "", names)
        if usable_folder(folder):
            target.folder = os.path.normcase(os.path.normpath(folder))
            for dirpath, dirnames, filenames in os.walk(folder):
                if os.path.relpath(dirpath, folder).count(os.sep) + 1 >= MAX_DEPTH:
                    dirnames[:] = []
                dirnames[:] = [d for d in dirnames if d.lower() not in _NOT_GAME_FOLDERS]
                target.exes.update(f.lower() for f in filenames if f.lower().endswith(".exe") and not is_helper(f))
        if target.folder or target.watch:
            targets.append(target)
    return targets


class Watcher:
    """Reports games whose processes appeared since the last poll."""

    def __init__(self, snapshot=None):
        if snapshot is None:
            from .launcher import _snapshot as snapshot
        self._snapshot = snapshot
        self._seen: set[int] | None = None    # None until the first poll: what was running before isn't news

    def poll(self, targets: list[Target]) -> list[tuple[str, int]]:
        """[(game id, pid)] for each game one of whose processes started since the last poll."""
        table = self._snapshot()
        pids = {pid for pid, _, _ in table}
        first, seen = self._seen is None, self._seen or set()
        self._seen = pids
        if first or not targets:
            return []
        hits: dict[str, int] = {}
        for pid, _ppid, name in table:
            if pid in seen or is_helper(name):
                continue
            for target in targets:
                if target.game_id in hits:
                    continue
                if name in target.watch:
                    hits[target.game_id] = pid
                elif target.folder and name in target.exes:
                    try:
                        exe = psutil.Process(pid).exe()
                    except psutil.Error:
                        continue
                    if os.path.normcase(exe).startswith(target.folder + os.sep) and not is_helper(name, exe):
                        hits[target.game_id] = pid
        for game_id, pid in hits.items():
            log.info("%s started outside QRes (pid %d)", game_id, pid)
        return list(hits.items())
