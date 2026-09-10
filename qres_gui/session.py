"""Record of an in-progress resolution switch.

Written before the launcher changes the resolution and removed once it has
switched back. If it outlives its owner (the launcher was killed), it holds
the desktop mode to go back to.
"""

from __future__ import annotations

import json
import os

import psutil

from . import paths


def read() -> dict | None:
    try:
        return json.loads(paths.session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write(original: dict, game_id: str) -> None:
    pid = os.getpid()
    data = {
        "pid": pid,
        "create_time": psutil.Process(pid).create_time(),
        "original": original,
        "game_id": game_id,
    }
    tmp = paths.session_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, paths.session_path())


def owner_alive(data: dict) -> bool:
    try:
        proc = psutil.Process(int(data["pid"]))
        return abs(proc.create_time() - float(data.get("create_time", 0))) < 1.0
    except (psutil.Error, KeyError, ValueError, TypeError):
        return False


def clear(pid: int | None = None) -> None:
    """Delete the record; with `pid`, only if that process owns it."""
    if pid is not None:
        data = read()
        if not data or data.get("pid") != pid:
            return
    paths.session_path().unlink(missing_ok=True)
