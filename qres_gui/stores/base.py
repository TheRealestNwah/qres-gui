from __future__ import annotations

import json
import os
import re
import subprocess
import winreg
from dataclasses import dataclass
from pathlib import Path

STORE_LABELS = {
    "steam": "Steam",
    "gog": "GOG",
    "epic": "Epic Games",
    "ubisoft": "Ubisoft Connect",
    "heroic": "Heroic",
    "amazon": "Amazon Games",
    "legendary": "Epic (Legendary)",
    "nile": "Amazon (nile)",
    "ea": "EA app",
    "battlenet": "Battle.net",
    "xbox": "Xbox",
    "playnite": "Playnite",
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


def read_json_lenient(path) -> object | None:
    """Parse a JSON file, tolerating a BOM, comments and trailing commas (fuel.json is JSON5)."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        return json.loads(_strip_json5(text))
    except ValueError:
        return None


def _strip_json5(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == '"':  # copy strings verbatim, escapes included
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(text[i])
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def read_fuel(install_dir: str) -> dict | None:
    """Launch details from an Amazon game's fuel.json: {"path", "args", "cwd"}."""
    data = read_json_lenient(Path(install_dir) / "fuel.json")
    main = data.get("Main") if isinstance(data, dict) else None
    if not isinstance(main, dict) or not main.get("Command"):
        return None
    subdir = main.get("WorkingSubdirOverride")
    args = main.get("Args") or []
    return {
        "path": os.path.normpath(os.path.join(install_dir, main["Command"])),
        "args": subprocess.list2cmdline(args) if isinstance(args, list) else str(args),
        "cwd": os.path.normpath(os.path.join(install_dir, subdir)) if subdir else install_dir,
    }


def read_goggame_info(install_dir: str, game_id: str) -> dict | None:
    """Name and primary play task from a GOG game's goggame-<id>.info: {"name", "path", "args", "cwd"}."""
    data = read_json_lenient(Path(install_dir) / f"goggame-{game_id}.info")
    if not isinstance(data, dict):
        return None
    tasks = [t for t in data.get("playTasks", [])
             if isinstance(t, dict) and t.get("type") == "FileTask" and t.get("category", "game") == "game"]
    task = next((t for t in tasks if t.get("isPrimary")), tasks[0] if tasks else None)
    info = {"name": str(data.get("name") or ""), "path": "", "args": "", "cwd": install_dir}
    if task and task.get("path"):
        info["path"] = os.path.normpath(os.path.join(install_dir, task["path"]))
        info["args"] = str(task.get("arguments") or "")
        if task.get("workingDir"):
            info["cwd"] = os.path.normpath(os.path.join(install_dir, task["workingDir"]))
    return info


def legendary_installs(installed_json) -> list[dict]:
    """Windows base games from a legendary installed.json: [{"app", "title", "install", "exe"}]."""
    data = read_json_lenient(installed_json)
    out = []
    for app, info in (data.items() if isinstance(data, dict) else []):
        if not isinstance(info, dict) or info.get("is_dlc"):
            continue
        if str(info.get("platform") or "windows").lower() not in ("windows", "win32"):
            continue
        install = str(info.get("install_path") or "")
        if not os.path.isdir(install):
            continue
        exe = os.path.normpath(os.path.join(install, info["executable"])) if info.get("executable") else ""
        out.append({"app": app, "title": str(info.get("title") or app), "install": install, "exe": exe})
    return out


def nile_installs(config_dir) -> list[dict]:
    """Games from a nile config folder (installed.json + library.json titles):
    [{"app", "title", "install", "exe"}]."""
    config_dir = Path(config_dir)
    installed = read_json_lenient(config_dir / "installed.json")
    if not isinstance(installed, list):
        return []
    titles = {}
    library = read_json_lenient(config_dir / "library.json")
    for item in (library if isinstance(library, list) else []):
        product = item.get("product") if isinstance(item, dict) else None
        if isinstance(product, dict) and product.get("id"):
            titles[product["id"]] = str(product.get("title") or "")
    out = []
    for entry in installed:
        if not isinstance(entry, dict):
            continue
        app, install = entry.get("id"), str(entry.get("path") or "")
        if not app or not os.path.isdir(install):
            continue
        fuel = read_fuel(install)
        out.append({"app": app, "title": titles.get(app) or os.path.basename(install), "install": install,
                    "exe": fuel["path"] if fuel else guess_main_exe(install)})
    return out


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


UNINSTALL_KEYS = (
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
)


def uninstall_entries() -> list[tuple[str, dict]]:
    """(key name, lower-cased values) for every "Apps & features" entry, both registry views and HKCU."""
    out = []
    for hive, path in UNINSTALL_KEYS:
        out.extend(reg_subkeys(hive, path))
    return out


def clean_path(value) -> str:
    """Registry paths are sometimes quoted or padded."""
    return os.path.normpath(str(value).strip().strip('"').strip()) if value and str(value).strip() else ""


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
