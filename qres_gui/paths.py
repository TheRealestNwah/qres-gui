"""Where settings live and how to invoke the launcher."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "QResGUI"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return app_dir() / "config.json"


def session_path() -> Path:
    return app_dir() / "session.json"


def log_path() -> Path:
    return app_dir() / "launcher.log"


def app_folder() -> Path:
    """The install folder when built, the project root when run from source."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else PROJECT_ROOT


def launcher_command() -> list[str]:
    """Command prefix that starts *this copy's* launcher.

    In a PyInstaller build QResLauncher.exe sits next to QResGUI.exe; from
    source it is pythonw.exe running QResLauncher.pyw from the project root.
    For what Steam, Playnite and shortcuts should run, use `hook_command`.
    """
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("QResLauncher.exe"))]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return [str(interpreter), str(PROJECT_ROOT / "QResLauncher.pyw")]


def installed_folder() -> Path:
    """Where install.ps1 puts QRes GUI. It never moves, which is what hooks rely on."""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "Programs" / APP_NAME


def installed_launcher() -> Path | None:
    """The installed copy's launcher, if QRes GUI is installed."""
    exe = installed_folder() / "QResLauncher.exe"
    return exe if exe.is_file() else None


def is_installed_copy() -> bool:
    """Whether this is the installed QRes GUI rather than an unzipped or test copy, or source."""
    if not getattr(sys, "frozen", False):
        return False
    try:
        return Path(sys.executable).resolve().parent == installed_folder().resolve()
    except OSError:
        return False


def hook_command() -> list[str]:
    """The launcher that Steam's launch options, Playnite's scripts and shortcuts should run.

    The installed copy's whenever there is one, whichever copy is asking. A
    hook outlives the copy that wrote it: one pointing at an unzipped download
    or a test build stops the game launching once that folder is deleted, and
    the installed folder is the one place that stays put across updates. So
    another copy leaves the hooks on the installed launcher instead of
    offering to "update" them to itself. Only with nothing installed does a
    copy point hooks at its own folder.
    """
    installed = installed_launcher()
    return [str(installed)] if installed else launcher_command()


def runs_installed_hooks() -> bool:
    """True when this copy isn't the installed one but the hooks run the installed one."""
    return installed_launcher() is not None and not is_installed_copy()
