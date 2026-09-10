from __future__ import annotations

import os
import re
import winreg
from dataclasses import dataclass
from pathlib import Path

STORE_LABELS = {
    "steam": "Steam",
    "gog": "GOG",
    "epic": "Epic Games",
    "ubisoft": "Ubisoft Connect",
    "manual": "Manual",
}


@dataclass
class Game:
    id: str                    # store-qualified, e.g. "steam:620"
    name: str
    store: str                 # key of STORE_LABELS
    install_dir: str = ""
    exe: str = ""              # main executable, if known
    launch: dict | None = None # how the launcher starts it without the store's help
    image: str = ""            # banner image, if the store keeps one locally
    needs_watch: bool = False  # started via a store URL, so we must know its process name

    @property
    def store_label(self) -> str:
        return STORE_LABELS.get(self.store, self.store)


def reg_values(key) -> dict[str, object]:
    """All values of an open registry key, with lower-cased names."""
    values = {}
    i = 0
    while True:
        try:
            name, value, _ = winreg.EnumValue(key, i)
        except OSError:
            return values
        values[name.lower()] = value
        i += 1


def reg_subkeys(hive, path: str) -> list[tuple[str, dict]]:
    """(subkey name, values) for every subkey of hive\\path; [] if it doesn't exist."""
    try:
        key = winreg.OpenKey(hive, path)
    except OSError:
        return []
    out = []
    with key:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(key, i)
            except OSError:
                break
            try:
                with winreg.OpenKey(key, name) as sub:
                    out.append((name, reg_values(sub)))
            except OSError:
                pass
            i += 1
    return out


_JUNK_EXE = re.compile(
    r"crash|report|setup|unins|redist|dxsetup|prereq|install|helper|update|easyanticheat|eac_|"
    r"battleye|be_service|dotnet|cefprocess|webhelper|uploader|diagnostic|touchup|cleanup|"
    r"activation|register|vc_?redist|dxwebsetup|oalinst|physx",
    re.I,
)
_JUNK_DIR = re.compile(r"redist|directx|vcredist|__installer|installer|prereq|support|easyanticheat|battleye", re.I)


def guess_main_exe(folder: str, max_depth: int = 4) -> str:
    """Best guess at a game's main executable: the largest plausible .exe.

    Unreal Engine games keep the real binary several levels down
    (<Project>/Binaries/Win64/<Project>-Win64-Shipping.exe), so those win.
    """
    root = Path(folder)
    if not root.is_dir():
        return ""
    best, best_score = "", -1
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        dirnames[:] = [] if depth >= max_depth else [d for d in dirnames if not _JUNK_DIR.search(d)]
        for name in filenames:
            if not name.lower().endswith(".exe") or _JUNK_EXE.search(name):
                continue
            path = os.path.join(dirpath, name)
            try:
                score = os.path.getsize(path)
            except OSError:
                continue
            if "shipping" in name.lower():
                score *= 4
            if score > best_score:
                best, best_score = path, score
    return best
