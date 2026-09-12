"""Record of an in-progress resolution switch.

Written before the resolution is changed and removed once it's back. It names
the process that owns the switch (the launcher, or Playnite for games started
there); if the record outlives its owner, it holds the desktop mode to go back
to. The token tells one switch from the next when the owner stays the same.
"""

from __future__ import annotations

import json
import os
import uuid

import psutil

from . import paths


def read() -> dict | None:
    try:
        return json.loads(paths.session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write(original: dict, game_id: str, owner: int | None = None, **extra) -> str:
    """Record a switch owned by `owner` (default: this process); returns its token."""
    pid = owner or os.getpid()
    token = uuid.uuid4().hex
    _store({
        "pid": pid,
        "create_time": psutil.Process(pid).create_time(),
        "original": original,
        "game_id": game_id,
        "token": token,
        **extra,
    })
    return token


def adopt(data: dict) -> dict:
    """Make this process the owner of a record whose owner has gone (same token)."""
    pid = os.getpid()
    data = {**data, "pid": pid, "create_time": psutil.Process(pid).create_time()}
    _store(data)
    return data


def _store(data: dict) -> None:
    tmp = paths.session_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, paths.session_path())


def owner_alive(data: dict) -> bool:
    try:
        proc = psutil.Process(int(data["pid"]))
        return abs(proc.create_time() - float(data.get("create_time", 0))) < 1.0
    except (psutil.Error, KeyError, ValueError, TypeError):
        return False


def clear(pid: int | None = None, token: str | None = None) -> None:
    """Delete the record; with `pid` or `token`, only if it still matches."""
    if pid is not None or token is not None:
        data = read()
        if not data or (pid is not None and data.get("pid") != pid) or \
                (token is not None and data.get("token") != token):
            return
    paths.session_path().unlink(missing_ok=True)
