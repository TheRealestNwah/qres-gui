"""Settings and per-game profiles, shared by the GUI and the launcher.

Stored as JSON in %APPDATA%\\QResGUI\\config.json. Each game profile is keyed
by a store-qualified id such as "steam:620" or "gog:1453375253":

    {"name": ..., "store": ..., "enabled": true,
     "width": 2560, "height": 1440, "refresh": 0,      # 0 = match desktop
     "watch": ["Game.exe"],                            # optional process names
     "launch": {"type": "exe", "path": ..., "args": ..., "cwd": ...}
               | {"type": "uri", "uri": ...} | null}
"""

from __future__ import annotations

import json
import os
from copy import deepcopy

from . import paths

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
    "presets": [],            # quick-switch resolutions: [{"name", "width", "height", "refresh"}]
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


def save(cfg: dict) -> None:
    path = paths.config_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, path)
