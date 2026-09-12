"""EA app (and old Origin) installs.

Each game leaves an "Apps & features" entry whose folder holds
__Installer\\installerdata.xml, with the title and the exe to run. EA games
started from their exe hand over to the EA app to sign in, so QRes tracks
them by exe name rather than by the process it started.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .base import Game, clean_path, uninstall_entries


def _strip_namespaces(root: ET.Element) -> ET.Element:
    for element in root.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]
    return root


def read_installerdata(path: Path) -> dict:
    """{"title", "exe" (relative to the game folder), "args", "content_id"} from installerdata.xml."""
    root = _strip_namespaces(ET.parse(path).getroot())
    # Newer manifests: <gameTitles><gameTitle locale="en_US">; older: <localeInfo locale="en_US"><title>.
    localised = [(e.get("locale"), e.text) for e in root.findall(".//gameTitles/gameTitle")]
    localised += [(e.get("locale"), e.findtext("title")) for e in root.findall(".//localeInfo")]
    localised = [(str(locale or "").lower(), text.strip()) for locale, text in localised if text and text.strip()]
    title = next((text for locale, text in localised if locale == "en_us"), localised[0][1] if localised else "")

    exe = args = ""
    for launcher in root.findall(".//runtime/launcher"):
        if (launcher.findtext("trial") or "").strip().lower() == "true":
            continue
        file_path = (launcher.findtext("filePath") or "").strip()
        if file_path:
            # "[HKEY_LOCAL_MACHINE\SOFTWARE\EA Games\Game\Install Dir]bin\Game.exe" -> "bin\Game.exe"
            exe = re.sub(r"^\[[^\]]*\]", "", file_path).lstrip("\\/")
            args = (launcher.findtext("parameters") or "").strip()
            break
    content_id = (root.findtext(".//contentIDs/contentID") or "").strip()
    return {"title": title, "exe": exe, "args": args, "content_id": content_id}


def installed_games() -> list[Game]:
    games: dict[str, Game] = {}
    for key, values in uninstall_entries():
        folder = clean_path(values.get("installlocation"))
        manifest = Path(folder) / "__Installer" / "installerdata.xml" if folder else None
        if not manifest or not manifest.is_file():
            continue
        try:
            info = read_installerdata(manifest)
        except (ET.ParseError, OSError):
            continue
        exe = os.path.join(folder, info["exe"]) if info["exe"] else ""
        game_id = f"ea:{info['content_id'] or key}"
        games.setdefault(game_id, Game(
            id=game_id,
            name=info["title"] or str(values.get("displayname") or os.path.basename(folder)),
            store="ea",
            install_dir=folder,
            exe=exe,
            launch={"type": "exe", "path": exe, "args": info["args"], "cwd": folder} if exe else None,
            needs_watch=bool(exe),
        ))
    return list(games.values())
