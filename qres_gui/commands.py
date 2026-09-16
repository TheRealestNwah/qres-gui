"""Commands the user asks to run just before a game's switch, and after it's undone.

Set for every game (Settings › Switching) and per game (the game panel). Before a
switch the global one runs first and the game's second; afterwards the game's
runs first and the global one last, so each undoes in the reverse order it set
up. "Before" runs where the switch is made - the launcher, or Playnite's start
script - and "after" commands are saved in the session record, so whatever puts
the display back (a normal exit, the guard after Steam's Stop, Playnite's stop
script, Restore desktop resolution) runs them, once.

A command is typed as it would be in a Command Prompt and runs through cmd.exe,
with no console window, outside the launcher's kill-on-close job so a program
it starts outlives the game. QRes waits up to WAIT seconds for each to finish -
long enough for "close this app first" - then carries on; a command that keeps
running (say, a frame limiter) is left to run. A failing command never stops a
game from starting or the display from coming back.
"""

from __future__ import annotations

import logging
import os
import subprocess

from . import notify

log = logging.getLogger(__name__)

BEFORE, AFTER = "before", "after"
WAIT = 15.0
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def planned(cfg: dict, entry: dict, when: str) -> list[str]:
    """The commands to run `when` ("before" or "after") for a game, in order."""
    everywhere = ((cfg.get("commands") or {}).get(when) or "").strip()
    this_game = ((entry.get("commands") or {}).get(when) or "").strip()
    ordered = (everywhere, this_game) if when == BEFORE else (this_game, everywhere)
    return [command for command in ordered if command]


def run_all(commands: list[str] | None, when: str, game_id: str = "", name: str = "") -> None:
    for command in commands or []:
        if isinstance(command, str) and command.strip():
            run(command.strip(), when, game_id, name)


def run(command: str, when: str, game_id: str = "", name: str = "") -> None:
    """Run one command; never raises."""
    env = {**os.environ, "QRES_EVENT": when, "QRES_GAME_ID": game_id, "QRES_GAME": name or game_id}
    log.info("running the %s command for %s: %s", when, game_id or "every game", command)
    proc = error = None
    # Out of the launcher's job where the job allows it (ours does), else as a
    # plain child: a job that forbids breaking away refuses the first attempt.
    for flags in (CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB, CREATE_NO_WINDOW):
        try:
            proc = subprocess.Popen(command, shell=True, env=env, creationflags=flags, close_fds=True,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            break
        except OSError as exc:
            error = exc
    if proc is None:
        log.warning("couldn't run the %s command %r: %s", when, command, error)
        notify.notify(f"Couldn't run the command {'before' if when == BEFORE else 'after'} "
                      f"{name or 'a game'}", f"{command} ({error})", game_id=game_id or None)
        return
    try:
        code = proc.wait(WAIT)
    except subprocess.TimeoutExpired:
        log.info("the %s command is still running after %.0f s; carrying on", when, WAIT)
        return
    # A non-zero exit is often nothing (taskkill for an app that isn't open), so it's logged, not shown.
    log.info("the %s command finished (exit code %s)", when, code)
