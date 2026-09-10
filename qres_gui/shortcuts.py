"""Windows .lnk shortcuts that start a game through the launcher."""

from __future__ import annotations

import ctypes
import re
import subprocess
import uuid
from functools import cache
from pathlib import Path

FOLDERID_DESKTOP = "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"
FOLDERID_PROGRAMS = "A77F5D77-2E2B-44C3-A6A2-ABA601054A51"
CREATE_NO_WINDOW = 0x08000000
START_MENU_FOLDER = "QRes GUI"


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


@cache
def _known_folder(folder_id: str) -> Path:
    guid = _GUID.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
    out = ctypes.c_wchar_p()
    hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out))
    if hr != 0:
        raise OSError(f"SHGetKnownFolderPath failed ({hr:#x})")
    try:
        return Path(out.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def desktop_dir() -> Path:
    return _known_folder(FOLDERID_DESKTOP)


def start_menu_dir() -> Path:
    return _known_folder(FOLDERID_PROGRAMS) / START_MENU_FOLDER


def shortcut_path(folder: Path, game_name: str) -> Path:
    # The suffix keeps us from overwriting the store's own shortcut.
    safe = re.sub(r'[<>:"/\\|?*]', "", game_name).strip() or "Game"
    return folder / f"{safe} (QRes).lnk"


def existing(game_name: str) -> list[Path]:
    paths = [shortcut_path(desktop_dir(), game_name), shortcut_path(start_menu_dir(), game_name)]
    return [p for p in paths if p.exists()]


def create(path: Path, target: str, arguments: str = "", working_dir: str = "",
           icon: str = "", description: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def q(value) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    lines = [
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({q(path)})",
        f"$s.TargetPath = {q(target)}",
        f"$s.Arguments = {q(arguments)}",
        f"$s.WorkingDirectory = {q(working_dir)}",
        f"$s.Description = {q(description)}",
    ]
    if icon:
        lines.append(f"$s.IconLocation = {q(icon + ',0')}")
    lines.append("$s.Save()")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "; ".join(lines)],
        capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode != 0 or not path.exists():
        raise OSError(f"Couldn't create {path}: {result.stderr.strip() or result.stdout.strip()}")
