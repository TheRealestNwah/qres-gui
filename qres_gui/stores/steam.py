"""Steam: installed games, and per-game launch options in localconfig.vdf.

Steam keeps launch options in userdata/<account>/config/localconfig.vdf under
UserLocalConfigStore/Software/Valve/Steam/apps/<appid>/LaunchOptions. It
rewrites that file when it exits, so edits are only safe while it's closed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import winreg
from pathlib import Path

import psutil

from .. import vdf
from .base import Game

STEAMID64_BASE = 76561197960265728
APPS_PATH = ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps")
IGNORED_APPIDS = {"228980", "250820", "1070560", "1391110", "1628350", "1493710", "2180100", "1826330"}
IGNORED_NAMES = re.compile(r"redistributable|steam linux runtime|^proton|steamvr|soundtrack$", re.I)
BACKUPS_KEPT = 5

# Matches the part of a launch-options string that we added, in either the
# frozen form ("...\QResLauncher.exe" run steam:1) or the from-source form
# ("...\pythonw.exe" "...\QResLauncher.pyw" run steam:1).
_OURS = re.compile(r'^\s*(?:"[^"]*"\s+)?"[^"]*QResLauncher\.(?:exe|pyw)"\s+run\s+\S+\s*', re.I)
COMMAND = "%command%"


class SteamRunningError(RuntimeError):
    pass


def _read_vdf(path: Path) -> vdf.KV:
    return vdf.loads(path.read_text(encoding="utf-8", errors="replace"))


def find_steam() -> Path | None:
    for hive, sub, name in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    ):
        try:
            with winreg.OpenKey(hive, sub) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        path = Path(value)
        if (path / "steam.exe").is_file():
            return path
    return None


# --- launch option strings -------------------------------------------------

def launch_prefix(launcher_cmd: list[str], game_id: str) -> str:
    return " ".join(f'"{part}"' for part in launcher_cmd) + f" run {game_id}"


def strip_ours(options: str) -> tuple[str, bool]:
    """Remove our launcher prefix; returns (remaining options, whether it was there)."""
    match = _OURS.match(options)
    if not match:
        return options, False
    rest = options[match.end():].strip()
    # We add %command% when the user's options didn't have one; take it back out.
    if rest.startswith(COMMAND) and rest.count(COMMAND) == 1:
        rest = rest[len(COMMAND):].strip()
    return rest, True


def apply_ours(options: str, prefix: str) -> str:
    """Wrap the game command with our launcher, keeping the user's own options."""
    base, _ = strip_ours(options)
    base = base.strip()
    if not base:
        return f"{prefix} {COMMAND}"
    if COMMAND in base:
        # e.g. '"nvse_loader.exe" %command%': we launch their wrapper, which launches the game.
        return f"{prefix} {base}"
    return f"{prefix} {COMMAND} {base}"


def option_state(options: str, prefix: str) -> str:
    """"applied", "outdated" (ours, but a different launcher path) or "none"."""
    base, found = strip_ours(options)
    if not found:
        return "none"
    return "applied" if options.strip() == apply_ours(base, prefix) else "outdated"


# --- client ----------------------------------------------------------------

class SteamClient:
    def __init__(self, root: Path | None = None):
        self.root = root or find_steam()

    @property
    def available(self) -> bool:
        return self.root is not None

    def library_folders(self) -> list[Path]:
        folders = [self.root]
        try:
            libs = _read_vdf(self.root / "steamapps" / "libraryfolders.vdf").block("libraryfolders")
        except (OSError, ValueError):
            libs = None
        for _, lib in (libs.items() if libs else []):
            if isinstance(lib, vdf.KV) and lib.get("path"):
                path = Path(lib.get("path"))
                if path.is_dir() and all(path.resolve() != f.resolve() for f in folders):
                    folders.append(path)
        return folders

    def installed_games(self) -> list[Game]:
        games: dict[str, Game] = {}
        for lib in self.library_folders():
            for manifest in (lib / "steamapps").glob("appmanifest_*.acf"):
                try:
                    state = _read_vdf(manifest).block("AppState")
                except (OSError, ValueError):
                    continue
                if state is None:
                    continue
                appid, name = state.get("appid", ""), state.get("name", "")
                if not appid or appid in IGNORED_APPIDS or IGNORED_NAMES.search(name):
                    continue
                install_dir = lib / "steamapps" / "common" / state.get("installdir", "")
                games[appid] = Game(
                    id=f"steam:{appid}",
                    name=name or f"App {appid}",
                    store="steam",
                    install_dir=str(install_dir),
                    launch={"type": "uri", "uri": f"steam://rungameid/{appid}"},
                    image=self.header_image(appid),
                )
        return list(games.values())

    def header_image(self, appid: str) -> str:
        cache = self.root / "appcache" / "librarycache"
        folder = cache / appid
        if folder.is_dir():
            # Older clients use header.jpg, newer ones library_header.jpg, either
            # directly in the folder or in a hash-named subfolder.
            for pattern in ("header.jpg", "library_header.jpg", "*/header.jpg", "*/library_header.jpg"):
                for candidate in folder.glob(pattern):
                    return str(candidate)
        legacy = cache / f"{appid}_header.jpg"
        return str(legacy) if legacy.is_file() else ""

    # -- launch options --

    def account_id(self) -> str | None:
        try:
            users = _read_vdf(self.root / "config" / "loginusers.vdf").block("users")
        except (OSError, ValueError):
            users = None
        candidates = []
        for steamid, info in (users.items() if users else []):
            if isinstance(info, vdf.KV) and steamid.isdigit():
                recent = info.get("MostRecent") == "1"
                candidates.append((recent, int(info.get("Timestamp", "0") or 0), str(int(steamid) - STEAMID64_BASE)))
        for _, _, account in sorted(candidates, reverse=True):
            if (self.root / "userdata" / account / "config" / "localconfig.vdf").is_file():
                return account
        # Fall back to whichever profile was used last.
        configs = [p for p in (self.root / "userdata").glob("*/config/localconfig.vdf") if p.parts[-3] != "0"]
        if configs:
            return max(configs, key=lambda p: p.stat().st_mtime).parts[-3]
        return None

    def localconfig_path(self) -> Path | None:
        account = self.account_id()
        return self.root / "userdata" / account / "config" / "localconfig.vdf" if account else None

    def launch_options(self) -> dict[str, str]:
        path = self.localconfig_path()
        if not path:
            return {}
        apps = _read_vdf(path).block(*APPS_PATH)
        if apps is None:
            return {}
        return {
            appid: block.get("LaunchOptions", "")
            for appid, block in apps.items()
            if isinstance(block, vdf.KV)
        }

    def set_launch_options(self, updates: dict[str, str]) -> Path:
        """Write launch options for several apps at once; returns the backup file."""
        if self.is_running():
            raise SteamRunningError("Steam is running. Close it first - it overwrites localconfig.vdf on exit.")
        path = self.localconfig_path()
        if not path:
            raise FileNotFoundError("Couldn't find this Steam account's localconfig.vdf.")
        raw = path.read_text(encoding="utf-8")
        root = vdf.loads(raw)
        apps = root.block(*APPS_PATH, create=True)
        for appid, options in updates.items():
            apps.block(appid, create=True)["LaunchOptions"] = options
        text = vdf.dumps(root)
        vdf.loads(text)  # sanity check before touching the real file

        backup = path.with_name(f"{path.name}.qresgui-{time.strftime('%Y%m%d-%H%M%S')}.bak")
        shutil.copy2(path, backup)
        for old in sorted(path.parent.glob(f"{path.name}.qresgui-*.bak"))[:-BACKUPS_KEPT]:
            old.unlink(missing_ok=True)
        tmp = path.with_name(path.name + ".qresgui-tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
        return backup

    # -- process --

    @staticmethod
    def is_running() -> bool:
        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower() == "steam.exe":
                return True
        return False

    def shutdown(self) -> None:
        subprocess.Popen([str(self.root / "steam.exe"), "-shutdown"])
