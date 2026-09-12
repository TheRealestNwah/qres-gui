"""Playnite integration through its global game scripts.

Playnite runs `PreScript` before starting any game (synchronously; if the
script throws, the game doesn't start) and `PostScript` after it stops. We
add a small block to each that hands the game's details to QResLauncher,
which switches the resolution for games set up in QRes GUI and back again.
Playnite, not the launcher, owns the switch while the game runs, so a guard
restores it if Playnite goes away without running the exit script.

Blocks are fenced by markers so they can be updated or removed without
touching the user's own script lines.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import winreg
from pathlib import Path

import psutil

BEGIN = "# >>> QRes GUI"
END = "# <<< QRes GUI"
_BLOCK = re.compile(rf"\r?\n?{re.escape(BEGIN)}.*?{re.escape(END)}[^\r\n]*", re.S)
SCRIPT_KEYS = ("PreScript", "PostScript")
BACKUPS_KEPT = 5
PROCESS_NAMES = {"playnite.desktopapp.exe", "playnite.fullscreenapp.exe"}

# Library plugin id -> the QRes game-id prefix its Playnite GameId maps to.
PLUGIN_PREFIXES = {
    "cb91dfc9-b977-43bf-8e70-55f46e410fab": "steam",      # Steam
    "00000002-dbd1-46c6-b5d0-b1ba559d10e4": "epic",       # Epic Games (official)
    "aebe8b7c-6dc3-4a66-af31-e7375c6b5e9e": "gog",        # GOG (official)
    "03689811-3f33-4dfb-a121-2ee168fb9a5c": "gog",        # GOG OSS (hawkeye116477)
    "ead65c3b-2f8f-4e37-b4e6-b3de6be540c6": "legendary",  # Legendary (hawkeye116477)
    "5901b4b4-774d-411a-9cce-807c5ca49d88": "nile",       # Nile (hawkeye116477)
    "402674cd-4af6-4886-b6ec-0e695bfa0688": "amazon",     # Amazon Games (official)
    "c2f038e5-8b92-4877-91f1-da9094155fc5": "ubisoft",    # Ubisoft Connect (official)
}


class PlayniteRunningError(RuntimeError):
    pass


# --- where Playnite lives ----------------------------------------------------

def _handler_exe() -> Path | None:
    """Playnite.DesktopApp.exe from the playnite:// URL handler, if registered."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\playnite\shell\open\command") as key:
            command, _ = winreg.QueryValueEx(key, "")
    except OSError:
        return None
    match = re.match(r'\s*"([^"]+)"', command) or re.match(r"\s*(\S+)", command)
    return Path(match.group(1)) if match else None


def data_dir() -> Path | None:
    """Playnite's settings folder: next to the exe when portable, else %APPDATA%\\Playnite."""
    exe = _handler_exe()
    if exe and (exe.parent / "config.json").is_file():
        return exe.parent
    roaming = Path(os.environ.get("APPDATA", "")) / "Playnite"
    return roaming if (roaming / "config.json").is_file() else None


def config_path() -> Path | None:
    folder = data_dir()
    return folder / "config.json" if folder else None


def is_running() -> bool:
    return any((p.info["name"] or "").lower() in PROCESS_NAMES for p in psutil.process_iter(["name"]))


def owner_pid(pid: int) -> int | None:
    """The Playnite process to tie a switch to: `pid` if it's Playnite, else any running Playnite."""
    try:
        if psutil.Process(pid).name().lower() in PROCESS_NAMES:
            return pid
    except (psutil.Error, ValueError):
        pass
    for proc in psutil.process_iter(["name"]):
        if (proc.info["name"] or "").lower() in PROCESS_NAMES:
            return proc.pid
    return None


# --- matching a Playnite game to a QRes profile --------------------------------

def _norm_dir(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)).rstrip("\\/") if path else ""


def _norm_name(name: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", name.casefold().replace("™", "").replace("®", "")).split())


def match(cfg: dict, info: dict) -> tuple[str | None, dict | None]:
    """Find the QRes profile for a Playnite game: store id, then install folder, then name."""
    games = cfg.get("games", {})
    prefix = PLUGIN_PREFIXES.get(str(info.get("pluginId", "")).lower())
    game_id = str(info.get("gameId") or "")
    if prefix and game_id:
        for candidate in (f"{prefix}:{game_id}", f"heroic:{prefix}:{game_id}"):
            if candidate in games:
                return candidate, games[candidate]

    folder = _norm_dir(str(info.get("installDir") or ""))
    if folder:
        best = None
        for gid, entry in games.items():
            theirs = _norm_dir(entry.get("install_dir", ""))
            if not theirs:
                continue
            if theirs == folder:
                return gid, entry
            # One folder inside the other, e.g. a manual profile pointing at <game>\bin.
            if theirs.startswith(folder + os.sep) or folder.startswith(theirs + os.sep):
                if best is None or len(theirs) > len(_norm_dir(games[best].get("install_dir", ""))):
                    best = gid
        if best:
            return best, games[best]

    name = _norm_name(str(info.get("name") or ""))
    if name:
        for gid, entry in games.items():
            if _norm_name(entry.get("name", "")) == name:
                return gid, entry
    return None, None


# --- the scripts ----------------------------------------------------------------

def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def scripts(launcher_cmd: list[str]) -> tuple[str, str]:
    """(before-start block, after-exit block) for Playnite's global scripts."""
    exe = _ps_quote(launcher_cmd[0])
    prefix = subprocess.list2cmdline(launcher_cmd[1:])
    lead = (prefix + " ") if prefix else ""
    pre = f"""{BEGIN} (switches resolution for games set up in QRes GUI)
try {{
    $qresInfo = @{{
        id = "$($Game.Id)"; gameId = "$($Game.GameId)"; pluginId = "$($Game.PluginId)"; name = "$($Game.Name)"
        installDir = $PlayniteApi.ExpandGameVariables($Game, "$($Game.InstallDirectory)")
        owner = [System.Diagnostics.Process]::GetCurrentProcess().Id
    }} | ConvertTo-Json -Compress
    $qresArg = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($qresInfo))
    $qresProc = Start-Process -FilePath {exe} -ArgumentList ({_ps_quote(lead + "playnite-start ")} + $qresArg) -PassThru
    [void]$qresProc.WaitForExit(30000)
}} catch {{ }}
{END}"""
    post = f"""{BEGIN} (switches the resolution back)
try {{
    $qresArg = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((@{{ id = "$($Game.Id)" }} | ConvertTo-Json -Compress)))
    Start-Process -FilePath {exe} -ArgumentList ({_ps_quote(lead + "playnite-stop ")} + $qresArg) | Out-Null
}} catch {{ }}
{END}"""
    return pre, post


def strip_block(script: str | None) -> str:
    return _BLOCK.sub("", script or "").strip("\r\n")


# --- reading and writing Playnite's settings -------------------------------------

def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def state(launcher_cmd: list[str]) -> str:
    """"missing" (no Playnite), "none", "installed" or "outdated" (older launcher path)."""
    path = config_path()
    if not path:
        return "missing"
    try:
        data = _load(path)
    except (OSError, ValueError):
        return "missing"
    blocks = [str(data.get(key) or "") for key in SCRIPT_KEYS]
    if not any(BEGIN in b for b in blocks):
        return "none"
    def flat(text: str) -> str:  # Playnite's editor may turn \n into \r\n
        return text.replace("\r\n", "\n")
    wanted = scripts(launcher_cmd)
    return "installed" if all(flat(w) in flat(b) for w, b in zip(wanted, blocks)) else "outdated"


def _write(update) -> Path:
    if is_running():
        raise PlayniteRunningError("Playnite is running. Close it first - it saves its settings when it exits.")
    path = config_path()
    if not path:
        raise FileNotFoundError("Couldn't find Playnite's config.json.")
    data = _load(path)
    update(data)
    backup = path.with_name(f"{path.name}.qresgui-{time.strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(path, backup)
    for old in sorted(path.parent.glob(f"{path.name}.qresgui-*.bak"))[:-BACKUPS_KEPT]:
        old.unlink(missing_ok=True)
    tmp = path.with_name(path.name + ".qresgui-tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return backup


def install(launcher_cmd: list[str]) -> Path:
    """Add (or refresh) our blocks after the user's own global scripts; returns the backup."""
    def update(data: dict) -> None:
        for key, block in zip(SCRIPT_KEYS, scripts(launcher_cmd)):
            own = strip_block(data.get(key))
            data[key] = f"{own}\r\n\r\n{block}" if own.strip() else block
    return _write(update)


def uninstall() -> Path:
    def update(data: dict) -> None:
        for key in SCRIPT_KEYS:
            own = strip_block(data.get(key))
            data[key] = own if own.strip() else None
    return _write(update)
