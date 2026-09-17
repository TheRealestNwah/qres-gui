"""When each game was last started through QRes, for the list's Last played column.

Kept in %APPDATA%\\QResGUI\\played.json as {game id: unix time}, apart from
config.json: the launcher writes it as a game starts, while QRes GUI may be open
holding its own copy of the config, which it would save back over a launcher's
change. Only this PC's history, so backups leave it out.

Steam keeps its own "last played" for every Steam game, however it was started;
the GUI shows whichever of the two is later.
"""

from __future__ import annotations

import json
import logging
import os
import time

from . import paths

log = logging.getLogger(__name__)


def path():
    return paths.app_dir() / "played.json"


def load() -> dict[str, float]:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float)) and v > 0}


def record(game_id: str, when: float | None = None) -> None:
    """Note that `game_id` is starting now. Never raises: this is only for the list."""
    if not game_id:
        return
    try:
        data = load()
        data[game_id] = float(when if when is not None else time.time())
        target = path()
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        log.warning("couldn't note when %s was played: %s", game_id, exc)


def mtime() -> float:
    try:
        return path().stat().st_mtime
    except OSError:
        return 0.0


def describe(when: float, now: float | None = None) -> str:
    """"Today", "Yesterday", "3 days ago", or a date for anything older than a week; "—" for never."""
    if not when:
        return "—"
    now = time.time() if now is None else now
    today = time.localtime(now)
    then = time.localtime(when)
    days = (time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1)) -
            time.mktime((then.tm_year, then.tm_mon, then.tm_mday, 0, 0, 0, 0, 0, -1)))
    days = round(days / 86400)
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    return f"{then.tm_mday} {time.strftime('%b', then)} {then.tm_year}"
