"""Settings and per-game profiles, shared by the GUI and the launcher.

Stored as JSON in %APPDATA%\\QResGUI\\config.json. Each game profile is keyed
by a store-qualified id such as "steam:620" or "gog:1453375253":

    {"name": ..., "store": ..., "enabled": true,
     "width": 2560, "height": 1440, "refresh": 0,      # 0 = match desktop
     "display": "\\\\.\\DISPLAY2" | "",                    # "" = whichever is primary
     "hdr": true | false | null,                       # null = leave HDR alone
     "watch": ["Game.exe"],                            # optional process names
     "extra_args": "-windowed",                        # added to the store's own arguments
     "launch": {"type": "exe", "path": ..., "args": ..., "cwd": ...}
               | {"type": "uri", "uri": ...} | null}

"launch" is a copy of what the store reports and is refreshed on every rescan,
so anything the user types goes in "extra_args" instead - except for manual
games, which have no store to copy from and own "launch" outright.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy

from . import engines, paths

DEFAULTS: dict = {
    "qres_path": "",
    "temporary": True,        # pass /D so the change is never written to the registry
    "switch_delay": 1.0,      # seconds to let the new mode settle before starting the game
    "restore_delay": 1.0,     # seconds to wait after the game exits before switching back
    "default_target": {"width": 2560, "height": 1440, "refresh": 0},
    "desktop_mode": None,     # fallback for "Restore desktop resolution"
    "check_updates": True,    # ask GitHub for a newer release at most once a day
    "update_last_check": 0,
    "update_available": None, # {"version", "url"} from the last check, until installed or dismissed
    "update_dismissed": "",   # version the user said "Later" to
    "first_run_done": False,  # the Getting started guide has been shown
    # quick-switch resolutions: [{"name", "width", "height", "refresh", "hotkey",
    #                            "display"}] - display "" = whichever is primary
    "presets": [],
    "tray_icon": True,        # show a system-tray icon
    "background": False,      # keep running in the tray when the window is closed
    "restore_hotkey": "",     # global hotkey for "Restore desktop resolution"
    # games hidden from the list (ids). Only a list filter: a hidden game keeps
    # its profile and still switches when launched.
    "hidden_games": [],
    # command lines run just before every game's switch and after it's undone
    # (see commands.py); games can add their own in their profile's "commands"
    "commands": {"before": "", "after": ""},
    "games": {},
}


def load() -> dict:
    cfg = deepcopy(DEFAULTS)
    path = paths.config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return cfg
    except (OSError, ValueError):
        # Keep the unreadable file around rather than silently overwriting it.
        os.replace(path, path.with_suffix(".corrupt.json"))
        return cfg
    cfg.update(data)
    return cfg


def extra_args(entry: dict) -> str:
    """What QRes adds to a game's command line: the engine options picked, then the user's own text.

    The user's text comes last so it can override an engine option if they want.
    """
    parts = (engines.command_line(entry.get("engine_args"), entry), entry.get("extra_args") or "")
    return " ".join(part.strip() for part in parts if part.strip())


def full_args(entry: dict) -> str:
    """A game's command line: the store's own arguments, then what QRes adds (extra_args)."""
    parts = ((entry.get("launch") or {}).get("args") or "", extra_args(entry))
    return " ".join(part.strip() for part in parts if part.strip())


def save(cfg: dict) -> None:
    path = paths.config_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, path)
