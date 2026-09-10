"""The program that Steam launch options and shortcuts point at.

    QResLauncher run <game-id> [game command...]
    QResLauncher restore
    QResLauncher guard <pid>          (internal)

`run` switches to the game's configured resolution, starts the game (the
command Steam substitutes for %command%, or the launch target saved for the
game), waits for the game's processes to exit and switches back.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import time
from ctypes import wintypes
from logging.handlers import RotatingFileHandler

import psutil

from . import config, display, paths, session

log = logging.getLogger("qres.launcher")

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
ERROR_ELEVATION_REQUIRED = 740
SEE_MASK_NOCLOSEPROCESS = 0x00000040

APPEAR_TIMEOUT = 180.0  # how long to wait for a watched process to show up
EXIT_GRACE = 3.0        # a game gone for this long is closed (covers self-restarts)


class LaunchError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _setup_logging()
    log.info("started with %r", argv)
    try:
        if len(argv) >= 2 and argv[0] == "run":
            return run(argv[1], argv[2:])
        if argv == ["restore"]:
            return restore()
        if len(argv) == 2 and argv[0] == "guard":
            return guard(int(argv[1]))
    except Exception as exc:
        log.exception("launcher failed")
        _message(f"{exc}\n\nDetails are in {paths.log_path()}")
        return 1
    _message("Usage:\n  QResLauncher run <game-id> [command...]\n  QResLauncher restore")
    return 2


# --- run -------------------------------------------------------------------

def run(game_id: str, command: list[str]) -> int:
    cfg = config.load()
    entry = cfg.get("games", {}).get(game_id) or {}
    if command:
        start = lambda: _start_command(command)
    elif entry.get("launch"):
        start = lambda: _start_target(entry["launch"])
    else:
        raise LaunchError(f"There's no launch target saved for {game_id}. Set the game up in QRes GUI first.")

    watch = {w.strip().lower() for w in entry.get("watch", []) if w.strip()}
    switch = _Switch(cfg, entry, game_id) if entry.get("enabled") else None
    if switch is None:
        log.info("resolution switching is off for %s; launching as-is", game_id)
    else:
        switch.apply()
    try:
        started = start()
        return _wait(started, watch)
    finally:
        if switch is not None:
            switch.restore()


class _Switch:
    def __init__(self, cfg: dict, entry: dict, game_id: str):
        self.cfg = cfg
        self.entry = entry
        self.game_id = game_id
        self.qres = display.find_qres(cfg.get("qres_path"))
        self.temporary = bool(cfg.get("temporary", True))
        self.original: display.Mode | None = None

    def apply(self) -> None:
        active = session.read()
        if active and session.owner_alive(active):
            log.info("another launch (pid %s) already switched the display; leaving it alone", active["pid"])
            return
        # A stale record means an earlier launch never switched back, so its
        # "original" is the real desktop mode, not whatever is set right now.
        original = display.Mode.from_dict(active["original"]) if active else display.current_mode()
        target = display.resolve(
            int(self.entry.get("width") or 0), int(self.entry.get("height") or 0),
            int(self.entry.get("refresh") or 0), original,
        )
        if target == original:
            log.info("target %s is the desktop mode; nothing to do", target)
            if active:
                session.clear()
            return

        session.write(original.to_dict(), self.game_id)
        self.original = original
        _spawn_guard()
        try:
            how = display.set_mode(target, self.qres, self.temporary)
            log.info("switched %s -> %s (%s)", original, target, how)
        except display.DisplayError as exc:
            log.error("%s", exc)
            _message(f"{exc}\n\nThe game will start at the current resolution.")
            return
        time.sleep(float(self.cfg.get("switch_delay", 1.0)))

    def restore(self) -> None:
        if self.original is None:
            return
        time.sleep(float(self.cfg.get("restore_delay", 1.0)))
        try:
            how = display.set_mode(self.original, self.qres, self.temporary)
            log.info("restored %s (%s)", self.original, how)
        except display.DisplayError as exc:
            log.error("restore failed: %s", exc)
            _message(f"Couldn't switch back to {self.original}.\n\n{exc}\n\n"
                     "Use \"Restore desktop resolution\" in QRes GUI.")
            return  # keep the session record so the GUI can offer to restore
        session.clear(os.getpid())


# --- starting the game -----------------------------------------------------

def _start_command(command: list[str]) -> subprocess.Popen | int:
    try:
        return subprocess.Popen(command)
    except OSError as exc:
        if getattr(exc, "winerror", None) != ERROR_ELEVATION_REQUIRED:
            raise
    log.info("%s needs administrator rights; starting it through ShellExecute", command[0])
    return _shell_execute(command[0], subprocess.list2cmdline(command[1:]), os.getcwd())


def _start_target(launch: dict) -> subprocess.Popen | int | None:
    kind = launch.get("type")
    if kind == "uri":
        log.info("opening %s", launch["uri"])
        os.startfile(launch["uri"])
        return None
    if kind == "exe":
        path, args = launch["path"], launch.get("args") or ""
        cwd = launch.get("cwd") or os.path.dirname(path)
        cmdline = subprocess.list2cmdline([path]) + (f" {args}" if args else "")
        log.info("starting %s in %s", cmdline, cwd)
        try:
            return subprocess.Popen(cmdline, cwd=cwd)
        except OSError as exc:
            if getattr(exc, "winerror", None) != ERROR_ELEVATION_REQUIRED:
                raise
        return _shell_execute(path, args, cwd)
    raise LaunchError(f"Unknown launch type {kind!r}")


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
    ]


def _shell_execute(file: str, params: str, cwd: str) -> int:
    """Start a program that needs elevation (Windows shows the UAC prompt); returns its pid."""
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpFile, info.lpParameters, info.lpDirectory, info.nShow = file, params, cwd, 1
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel32.GetProcessId.argtypes = [wintypes.HANDLE]
    pid = kernel32.GetProcessId(info.hProcess)
    kernel32.CloseHandle(info.hProcess)
    return pid


# --- waiting for the game to exit ------------------------------------------

TH32CS_SNAPPROCESS = 0x00000002


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_INVALID_HANDLE = ctypes.c_void_p(-1).value


def _snapshot() -> list[tuple[int, int, str]]:
    """(pid, parent pid, lower-case exe name) for every process, in one cheap call."""
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == _INVALID_HANDLE:
        return []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        out = []
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile.lower()))
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
        return out
    finally:
        _k32.CloseHandle(snap)


def _create_time(pid: int) -> float | None:
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


def _wait(started: subprocess.Popen | int | None, watch: set[str]) -> int:
    """Block until the game is gone.

    Without `watch`, that's when the started process and everything it spawned
    have exited. With `watch` (process names), it's when the watched processes
    have appeared and exited again - needed for store-URL launches, and for
    launchers that stay open after the game closes.

    Windows keeps a process's parent pid after the parent exits, so a game
    started by a launcher that quit straight away is still recognised as ours.
    """
    tracked: dict[int, psutil.Process] = {}  # live game processes
    names: dict[int, str] = {}
    born: dict[int, float] = {}               # every pid ever tracked -> creation time

    def track(pid: int, name: str) -> None:
        created = _create_time(pid)
        if created is None:
            return
        tracked[pid], names[pid], born[pid] = psutil.Process(pid), name, created
        log.info("tracking %s (%d)", name, pid)

    root = started.pid if isinstance(started, subprocess.Popen) else started
    if root:
        try:
            track(root, psutil.Process(root).name().lower())
        except psutil.Error:
            pass
        born.setdefault(root, 0.0)  # even if it already quit, adopt whatever it started
    t0 = time.monotonic()
    seen_watched = False
    gone_since: float | None = None
    while True:
        now = time.monotonic()
        table = _snapshot()
        # Repeat so a child and grandchild that both appeared since the last poll are caught together.
        added = True
        while added:
            added = False
            for pid, ppid, name in table:
                if pid in tracked:
                    continue
                parent_born = born.get(ppid)
                ours = parent_born is not None and (_create_time(pid) or 0) >= parent_born - 1
                if ours or name in watch:
                    track(pid, name)
                    added = added or pid in tracked
        present = {pid for pid, _, _ in table}
        for pid in [p for p, proc in tracked.items() if p not in present or not proc.is_running()]:
            del tracked[pid]

        watched_alive = any(names[p] in watch for p in tracked)
        seen_watched = seen_watched or watched_alive
        if watch and seen_watched:
            running = watched_alive
        else:
            running = bool(tracked) or (bool(watch) and now - t0 < APPEAR_TIMEOUT)

        if running:
            gone_since = None
        elif gone_since is None:
            gone_since = now
        elif now - gone_since >= EXIT_GRACE:
            break
        # Poll fast while launchers are likely to be handing off, then back off.
        elapsed = now - t0
        time.sleep(0.05 if elapsed < 15 else 0.25 if elapsed < 60 else 1.0)

    log.info("game exited after %.0f s", time.monotonic() - t0)
    if isinstance(started, subprocess.Popen):
        return started.poll() or 0
    return 0


# --- safety net ------------------------------------------------------------

def _spawn_guard() -> None:
    """Start a detached process that restores the resolution if we get killed."""
    cmd = paths.launcher_command() + ["guard", str(os.getpid())]
    base = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for flags in (base | CREATE_BREAKAWAY_FROM_JOB, base):
        try:
            subprocess.Popen(cmd, creationflags=flags, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError as exc:
            error = exc
    log.warning("couldn't start the guard process: %s", error)


def guard(pid: int) -> int:
    try:
        psutil.Process(pid).wait()
    except psutil.NoSuchProcess:
        pass
    data = session.read()
    if not data or data.get("pid") != pid:
        return 0
    log.warning("launcher %d ended without switching back; restoring", pid)
    return restore()


def restore() -> int:
    cfg = config.load()
    data = session.read()
    source = (data or {}).get("original") or cfg.get("desktop_mode")
    if not source:
        _message("No desktop resolution is saved yet. Open QRes GUI once to record it.")
        return 1
    mode = display.Mode.from_dict(source)
    how = display.set_mode(mode, display.find_qres(cfg.get("qres_path")), bool(cfg.get("temporary", True)))
    log.info("restored %s (%s)", mode, how)
    session.clear()
    return 0


# --- plumbing --------------------------------------------------------------

def _setup_logging() -> None:
    handler = RotatingFileHandler(paths.log_path(), maxBytes=512_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(process)d] %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _message(text: str) -> None:
    MB_ICONWARNING, MB_SETFOREGROUND, MB_TOPMOST = 0x30, 0x10000, 0x40000
    ctypes.windll.user32.MessageBoxW(None, text, "QRes Launcher", MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST)
