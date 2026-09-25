"""Each launch through QRes: when, for how long, what started it, and whether the desktop came back.

Kept in %APPDATA%\\QResGUI\\history.json as a list, oldest first, trimmed to the
last LIMIT launches. Like played.json it lives apart from config.json because
the launcher writes it while QRes GUI may be holding its own copy of the config,
and like played.json it's only this PC's, so backups leave it out. Nothing in it
leaves the PC: a game id and the name it had, times, where the launch came from
and how the restore went - no paths, arguments or commands.

`start` also notes the launch in played.json, which stays what the list's Last
played column reads: it is one small lookup per game, and it keeps a game's
last start after its launches have been trimmed from here.

A launch is written twice: when it starts, and when it ends (`finish`). One the
end of which QRes never saw - the PC turned off, the launcher was killed and
nothing took over - keeps no end, and reads as not known rather than guessed.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid

import psutil

from . import paths, played

log = logging.getLogger(__name__)

LIMIT = 500

# What started the game.
STEAM = "steam"          # Steam's launch options (its Play button, or anything that asks Steam)
GUI = "gui"              # QRes GUI's Play button
SHORTCUT = "shortcut"    # a shortcut QRes GUI made
PLAYNITE = "playnite"    # Playnite's scripts
WATCHER = "watcher"      # QRes GUI noticed it starting some other way
SOURCES = {STEAM: "Steam", GUI: "QRes GUI", SHORTCUT: "Shortcut", PLAYNITE: "Playnite",
           WATCHER: "Noticed starting"}

# How the desktop came back afterwards.
CLEAN = "clean"            # everything QRes changed was put back when the game ended
PARTIAL = "partial"        # the resolution came back, but not all of HDR, scaling and audio did
FAILED = "failed"          # the resolution didn't come back
RECOVERED = "recovered"    # put back, but by the safety net: whatever owned the switch ended first
UNCHANGED = "unchanged"    # nothing was switched, so nothing needed putting back

# Set in the launcher's environment by QRes GUI's Play button: `run` without a
# game command is otherwise a shortcut, and the two start the same way.
SOURCE_ENV = "QRES_LAUNCH_SOURCE"


def path():
    return paths.app_dir() / "history.json"


def load() -> list[dict]:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict) and entry.get("id") and entry.get("game_id")
            and isinstance(entry.get("start"), (int, float))]


def mtime() -> float:
    try:
        return path().stat().st_mtime
    except OSError:
        return 0.0


def _save(entries: list[dict]) -> None:
    target = path()
    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(entries[-LIMIT:], indent=1), encoding="utf-8")
    # Replacing a file another process is reading fails on Windows; that read is over in a moment.
    for attempt in range(5):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == 4:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.1)


def start(game_id: str, source: str, name: str = "", owner: int | None = None,
          when: float | None = None) -> str:
    """Note that `game_id` is starting now; returns the launch's id for `finish` ("" if it couldn't be noted).

    `owner` is the process whose life the launch follows (default: this one),
    so the history can tell a launch still running from one whose end it missed.
    Never raises: a launch mustn't fail over its history.
    """
    if not game_id:
        return ""
    when = float(when if when is not None else time.time())
    played.record(game_id, when)
    pid = owner or os.getpid()
    launch = uuid.uuid4().hex[:12]
    try:
        created = psutil.Process(pid).create_time()
    except psutil.Error:
        created = 0.0
    try:
        entries = load()
        entries.append({"id": launch, "game_id": game_id, "name": name or game_id, "source": source,
                        "start": when, "pid": pid, "create_time": created})
        _save(entries)
    except OSError as exc:
        log.warning("couldn't add %s to the launch history: %s", game_id, exc)
        return ""
    return launch


def finish(launch: str | None, restore: str | None = None, problems: list[str] | None = None,
           end: float | None = None) -> None:
    """Note how launch `launch` ended. Never raises.

    Fills in only what isn't known yet, so whichever part of QRes sees an end
    first - the launcher, the safety net, QRes GUI's Restore button - is the one
    that counts. `end` is when the game exited; leave it out when that isn't
    known. `problems` names what didn't come back, for PARTIAL and FAILED.
    """
    if not launch:
        return
    try:
        entries = load()
        entry = next((e for e in entries if e.get("id") == launch), None)
        if entry is None:
            return   # trimmed, or the history was cleared while the game ran
        changed = False
        if end is not None and entry.get("end") is None:
            entry["end"] = float(max(end, entry["start"]))
            changed = True
        if restore is not None and entry.get("restore") is None:
            entry["restore"] = restore
            if problems:
                entry["problems"] = list(problems)
            changed = True
        if changed:
            _save(entries)
    except OSError as exc:
        log.warning("couldn't finish launch %s in the history: %s", launch, exc)


def just_started(game_id: str, source: str, within: float = 300.0) -> str:
    """A launch of `game_id` from `source` noted in the last `within` seconds that hasn't ended and
    whose owner still runs ("" if none). A Steam game Playnite starts also runs Steam's launch
    options, and so the launcher: that's the same launch, already noted by Playnite's script."""
    now = time.time()
    for entry in reversed(load()):
        if (entry["game_id"] == game_id and entry.get("source") == source and entry.get("end") is None
                and now - entry["start"] <= within and _alive(entry)):
            return entry["id"]
    return ""


def latest_open(game_id: str, source: str) -> str:
    """The newest launch of `game_id` from `source` with no end yet ("" if none), for an end
    reported by something that never had the launch's id - Playnite's stop script for a game
    it started without a switch."""
    for entry in reversed(load()):
        if entry["game_id"] == game_id and entry.get("source") == source and entry.get("end") is None:
            return entry["id"]
    return ""


def clear() -> None:
    path().unlink(missing_ok=True)


# --- reading it back --------------------------------------------------------------

def running_ids(entries: list[dict]) -> set[str]:
    """Launches with no end yet whose owner is still running - the newest such per owner.

    An owner that outlives its launches (Playnite) may never have said one of
    them ended; only its latest can still be going.
    """
    newest: dict[tuple, dict] = {}
    for entry in entries:
        if entry.get("end") is None:
            key = (entry.get("pid"), entry.get("create_time"))
            if key not in newest or entry["start"] >= newest[key]["start"]:
                newest[key] = entry
    return {entry["id"] for entry in newest.values() if _alive(entry)}


def _alive(entry: dict) -> bool:
    """Whether the process a launch follows is still running (the same process, not a reused pid)."""
    try:
        proc = psutil.Process(int(entry.get("pid") or 0))
        return abs(proc.create_time() - float(entry.get("create_time") or 0)) < 1.0
    except (psutil.Error, ValueError, TypeError):
        return False


def describe_start(when: float, now: float | None = None) -> str:
    """"Today 21:04", "Yesterday 18:30", "3 days ago 12:00", "9 Sep 2026 20:15"."""
    return f"{played.describe(when, now)} {time.strftime('%H:%M', time.localtime(when))}"


def describe_duration(entry: dict, running: bool = False) -> str:
    if entry.get("end") is None:
        return "Running" if running else "—"
    minutes = int((float(entry["end"]) - float(entry["start"])) // 60)
    if minutes < 1:
        return "Under a minute"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def describe_source(entry: dict) -> str:
    return SOURCES.get(entry.get("source") or "", "—")


def describe_restore(entry: dict, running: bool = False) -> tuple[str, str, bool]:
    """(what the history shows, a longer explanation, whether it went wrong)."""
    outcome = entry.get("restore")
    problems = ", ".join(entry.get("problems") or [])
    if outcome == CLEAN:
        return "Restored", "Everything QRes changed was put back when the game ended.", False
    if outcome == PARTIAL:
        return (f"Restored except {problems}" if problems else "Partly restored",
                f"The resolution came back, but QRes couldn't put back: {problems or 'everything else'}.", True)
    if outcome == FAILED:
        return ("Not restored", "The desktop resolution wasn't put back. QRes GUI's Restore desktop "
                "resolution button does that.", True)
    if outcome == RECOVERED:
        return ("Restored late", "What started the game ended without switching back, so QRes put the "
                "desktop back afterwards - its safety net, or QRes GUI.", False)
    if outcome == UNCHANGED:
        return "Not switched", "Nothing was switched for this launch, so nothing needed putting back.", False
    if running:
        return "—", "The game is still running.", False
    return ("Unknown", "QRes didn't see this launch end - the PC may have been turned off or the launcher "
            "stopped while the game ran.", False)
