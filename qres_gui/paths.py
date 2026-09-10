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
    """Command prefix that starts the launcher.

    In a PyInstaller build QResLauncher.exe sits next to QResGUI.exe; from
    source it is pythonw.exe running QResLauncher.pyw from the project root.
    """
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("QResLauncher.exe"))]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return [str(interpreter), str(PROJECT_ROOT / "QResLauncher.pyw")]
