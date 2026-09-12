"""Xbox app / PC Game Pass installs.

Each drive the Xbox app installs to has a .GamingRoot file naming its game
folders ("RGBX", a count, then UTF-16 folder names). Every game has a
MicrosoftGame.config with its package name, exe and display name. These are
packaged apps, started through shell:AppsFolder\\<package family>!<app id>,
and tracked by exe name.
"""

from __future__ import annotations

import ctypes
import os
import string
import winreg
import xml.etree.ElementTree as ET
from pathlib import Path

from .base import Game

PACKAGES_KEY = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
DRIVE_FIXED = 3


def gaming_roots() -> list[Path]:
    """Xbox game folders from every fixed drive's .GamingRoot."""
    roots = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i) or ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\") != DRIVE_FIXED:
            continue
        roots.extend(parse_gaming_root(Path(f"{letter}:\\.GamingRoot")))
    return roots


def parse_gaming_root(path: Path) -> list[Path]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if data[:4] != b"RGBX":
        return []
    names = data[8:].decode("utf-16-le", errors="ignore").split("\x00")
    return [Path(path.anchor) / name for name in names if name.strip()]


def _package_families() -> dict[str, str]:
    """Package name -> package family name, from the installed-packages registry."""
    families = {}
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, PACKAGES_KEY)
    except OSError:
        return families
    with key:
        i = 0
        while True:
            try:
                full_name = winreg.EnumKey(key, i)  # Name_Version_Arch_ResourceId_PublisherId
            except OSError:
                break
            parts = full_name.split("_")
            if len(parts) >= 5:
                families.setdefault(parts[0], f"{parts[0]}_{parts[-1]}")
            i += 1
    return families


def read_game_config(path: Path) -> dict:
    """{"identity", "exe", "app_id", "name"} from a MicrosoftGame.config."""
    root = ET.parse(path).getroot()
    for element in root.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]
    executables = root.findall(".//ExecutableList/Executable")
    pc = [e for e in executables if (e.get("TargetDeviceFamily") or "PC").lower() == "pc"]
    exe = (pc or executables or [None])[0]
    visuals = root.find(".//ShellVisuals")
    name = (visuals.get("DefaultDisplayName") if visuals is not None else "") or ""
    identity = root.find(".//Identity")
    return {
        "identity": identity.get("Name", "") if identity is not None else "",
        "exe": exe.get("Name", "") if exe is not None else "",
        "app_id": exe.get("Id", "") if exe is not None else "",
        "name": "" if name.startswith("ms-resource:") else name,
    }


def installed_games() -> list[Game]:
    families = None
    games: dict[str, Game] = {}
    for root in gaming_roots():
        if not root.is_dir():
            continue
        for folder in root.iterdir():
            config = next((c for c in (folder / "Content" / "MicrosoftGame.config", folder / "MicrosoftGame.config")
                           if c.is_file()), None)
            if config is None:
                continue
            try:
                info = read_game_config(config)
            except (ET.ParseError, OSError):
                continue
            if not info["identity"]:
                continue
            if families is None:
                families = _package_families()
            family = families.get(info["identity"])
            content = config.parent
            launch = ({"type": "uri", "uri": f"shell:AppsFolder\\{family}!{info['app_id']}"}
                      if family and info["app_id"] else None)
            games.setdefault(info["identity"], Game(
                id=f"xbox:{info['identity']}",
                name=info["name"] or folder.name,
                store="xbox",
                install_dir=str(content),
                exe=os.path.join(content, info["exe"]) if info["exe"] else "",
                launch=launch,
                needs_watch=launch is not None,
            ))
    return list(games.values())
