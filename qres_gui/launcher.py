"""The program that Steam launch options and shortcuts point at.

    QResLauncher run <game-id> [game command...]
    QResLauncher restore
    QResLauncher playnite-start <base64 json>  (Playnite's before-start script)
    QResLauncher playnite-stop <base64 json>   (Playnite's after-exit script)
    QResLauncher remove-hooks [report.json]    (used by the uninstaller)
    QResLauncher guard <pid> [token]           (internal)

`run` switches to the game's configured resolution, starts the game (the
command Steam substitutes for %command%, or the launch target saved for the
game), waits for the game's processes to exit and switches back.

`playnite-start` / `playnite-stop` only switch: Playnite starts the game,
tracks it, and runs the stop script when it exits.
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from logging.handlers import RotatingFileHandler

import psutil

from . import config, display, notify, paths, playnite, session

log = logging.getLogger("qres.launcher")

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_NO_WINDOW = 0x08000000
ERROR_ELEVATION_REQUIRED = 740
SEE_MASK_NOCLOSEPROCESS = 0x00000040

APPEAR_TIMEOUT = 180.0  # how long to wait for a watched process to show up
EXIT_GRACE = 3.0        # a game gone for this long is closed (covers self-restarts)
EXIT_STEAM_RUNNING = 3     # remove-hooks: Steam must be closed first
EXIT_PLAYNITE_RUNNING = 4  # remove-hooks: Playnite must be closed first
GUARD_POLL = 2.0           # seconds between guard checks


class LaunchError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["guard"] and len(argv) == 4 and argv[3]:
        # Started through WMI, the guard gets a fresh environment; use the launcher's settings folder.
        os.environ["APPDATA"] = argv[3]
    _setup_logging()
    log.info("started with %r", argv)
    try:
        if len(argv) >= 2 and argv[0] == "run":
            return run(argv[1], argv[2:])
        if argv == ["restore"]:
            return restore()
        if len(argv) == 2 and argv[0] == "playnite-start":
            return playnite_start(argv[1])
        if len(argv) == 2 and argv[0] == "playnite-stop":
            return playnite_stop(argv[1])
        if argv[:1] == ["remove-hooks"] and len(argv) <= 2:
            return remove_hooks(argv[1] if len(argv) == 2 else None)
        if argv[:1] == ["guard"] and 2 <= len(argv) <= 4:
            return guard(int(argv[1]), argv[2] if len(argv) >= 3 else None)
    except Exception as exc:
        log.exception("launcher failed")
        if argv[:1] == ["run"]:
            notify.notify(f"Couldn't start {_game_name(argv[1])}", str(exc), game_id=argv[1])
        else:
            notify.notify("QRes Launcher failed", str(exc))
        return 1
    # Someone ran the exe by hand, so a plain message box is the right answer.
    notify._message_box("QRes Launcher",
                        "Usage:\n  QResLauncher run <game-id> [command...]\n  QResLauncher restore", "info")
    return 2


def _game_name(game_id: str) -> str:
    try:
        return config.load().get("games", {}).get(game_id, {}).get("name") or game_id
    except Exception:
        return game_id


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
    quick = bool(entry.get("quick_restore"))
    started_from = command[0] if command else (entry.get("launch") or {}).get("path", "")
    install_dir = entry.get("install_dir") or (os.path.dirname(started_from) if started_from else "")
    switch = _Switch(cfg, entry, game_id, install_dir=install_dir) if entry.get("enabled") else None
    if switch is None:
        log.info("resolution switching is off for %s; launching as-is", game_id)
    else:
        switch.apply()  # before joining the job below, so the guard it starts stays out of it
    with _CloseGameWithUs():
        try:
            started = start()
            return _wait(started, watch, grace=0.0 if quick else None)
        finally:
            if switch is not None:
                switch.restore()


class _Switch:
    """One resolution switch. The owner (this launcher, or Playnite) keeps it alive."""

    def __init__(self, cfg: dict, entry: dict, game_id: str, owner: int | None = None,
                 install_dir: str = "", **extra):
        self.cfg = cfg
        self.entry = entry
        self.game_id = game_id
        self.owner = owner or os.getpid()
        # Stored in the session record. The folder and watch names let the guard
        # recognise the game if the owner goes away while it's still running.
        self.extra = {"install_dir": install_dir, "watch": list(entry.get("watch") or []), **extra}
        self.name = entry.get("name") or game_id
        self.qres = display.find_qres(cfg.get("qres_path"))
        self.temporary = bool(cfg.get("temporary", True))
        self.original: display.Mode | None = None
        self.token: str | None = None

    def apply(self) -> None:
        active = session.read()
        if active and session.owner_alive(active):
            # Playnite runs its stop script per game; if one never came, the next
            # game from the same Playnite takes the switch over.
            takeover = (active.get("source") == "playnite" and self.extra.get("source") == "playnite"
                        and active.get("pid") == self.owner)
            if not takeover:
                log.info("another launch (pid %s) already switched the display; leaving it alone", active["pid"])
                return
            log.info("taking over Playnite's earlier switch for %s", active.get("game_id"))
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
                if display.current_mode() != original:  # a taken-over switch still needs undoing
                    display.set_mode(original, self.qres, self.temporary)
                session.clear()
            return

        self.token = session.write(original.to_dict(), self.game_id, owner=self.owner, **self.extra)
        self.original = original
        guard_starting = _spawn_guard(self.owner, self.token)  # in the background, while we switch
        try:
            how = display.set_mode(target, self.qres, self.temporary)
            log.info("switched %s -> %s (%s)", original, target, how)
            time.sleep(float(self.cfg.get("switch_delay", 1.0)))
        except display.DisplayError as exc:
            notify.notify(f"Couldn't switch to {target}",
                          f"{self.name} is starting at your current resolution. ({exc})", game_id=self.game_id)
        finally:
            guard_starting.join(30)

    def restore(self) -> None:
        if self.original is None:
            return
        if not self.entry.get("quick_restore"):
            time.sleep(float(self.cfg.get("restore_delay", 1.0)))
        try:
            how = display.set_mode(self.original, self.qres, self.temporary)
            log.info("restored %s (%s)", self.original, how)
        except display.DisplayError as exc:
            notify.notify(f"Couldn't switch back to {self.original}",
                          f"Open QRes GUI and click Restore desktop resolution. ({exc})", game_id=self.game_id)
            return  # keep the session record so the GUI can offer to restore
        session.clear(token=self.token)


# --- tying the game to the launcher ----------------------------------------

JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _CloseGameWithUs:
    """Put the launcher, and so everything it starts, in a job Windows closes if the launcher is killed.

    Steam's Stop button ends the process Steam started - this launcher, not
    the game - so without this the game would keep running on its own. On
    any normal way out of the block, including errors, the kill flag is
    cleared first: only an outside kill closes the game.
    """

    def __enter__(self):
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        self.k32 = k32
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            log.warning("couldn't create a job object; Steam's Stop won't close the game")
            return self
        if not (self._set(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK)
                and k32.AssignProcessToJobObject(self.handle, k32.GetCurrentProcess())):
            log.warning("couldn't join a job object (%s); Steam's Stop won't close the game",
                        ctypes.WinError(ctypes.get_last_error()))
            k32.CloseHandle(self.handle)
            self.handle = None
        return self

    def _set(self, flags: int) -> bool:
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = flags
        return bool(self.k32.SetInformationJobObject(
            self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)))

    def __exit__(self, *exc) -> None:
        if self.handle:
            self._set(JOB_OBJECT_LIMIT_BREAKAWAY_OK)  # leave anything still running alone
            self.k32.CloseHandle(self.handle)
            self.handle = None


# --- starting the game -----------------------------------------------------

def _start_command(command: list[str]) -> subprocess.Popen | int:
    try:
        return subprocess.Popen(command)
    except FileNotFoundError:
        raise LaunchError(f"{command[0]} doesn't exist. Check the game's launch options.") from None
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
        if not os.path.isfile(path):
            raise LaunchError(f"{path} doesn't exist. The game may have moved or been uninstalled; "
                              "rescan or fix it in QRes GUI.")
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


def _wait(started: subprocess.Popen | int | None, watch: set[str], grace: float | None = None) -> int:
    """Block until the game is gone (for `grace` seconds; default EXIT_GRACE).

    Without `watch`, that's when the started process and everything it spawned
    have exited. With `watch` (process names), it's when the watched processes
    have appeared and exited again - needed for store-URL launches, and for
    launchers that stay open after the game closes.

    Windows keeps a process's parent pid after the parent exits, so a game
    started by a launcher that quit straight away is still recognised as ours.
    """
    grace = EXIT_GRACE if grace is None else grace
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
        elif now - gone_since >= grace:
            break
        # Poll fast while launchers are likely to be handing off, then back off.
        elapsed = now - t0
        time.sleep(0.05 if elapsed < 15 else 0.25 if elapsed < 60 else 0.5)

    log.info("game exited after %.0f s", time.monotonic() - t0)
    if isinstance(started, subprocess.Popen):
        return started.poll() or 0
    return 0


# --- safety net ------------------------------------------------------------

def _spawn_guard(owner: int, token: str) -> threading.Thread:
    """Start the guard, which restores the resolution if the owner goes away first.

    It has to outlive whatever ends the owner, and Steam's Stop button ends
    the whole process tree it launched - following parent links, so any child
    of ours goes with it, job or no job. The guard is therefore created
    through WMI (Win32_Process.Create): its parent is the WMI host, outside
    our tree and any job, in the same session with the same desktop. Only if
    that fails is it started as our own (detached, breakaway) child.
    Runs on a thread because the WMI route takes a second or so.
    """
    cmd = paths.launcher_command() + ["guard", str(owner), token, os.environ.get("APPDATA", "")]
    quiet = {"close_fds": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
             "stderr": subprocess.DEVNULL}
    base = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    def start() -> None:
        if _start_outside_jobs(cmd):
            log.info("guard started through WMI")
            return
        for flags in (base | CREATE_BREAKAWAY_FROM_JOB, base):
            try:
                subprocess.Popen(cmd, creationflags=flags, **quiet)
                log.warning("guard started as our own child; ending our process tree would end it too")
                return
            except OSError as exc:
                error = exc
        log.warning("couldn't start the guard process: %s", error)

    thread = threading.Thread(target=start, name="guard-start", daemon=True)
    thread.start()
    return thread


def _start_outside_jobs(cmd: list[str]) -> bool:
    """Create a process through WMI (Win32_Process.Create): outside our process tree and jobs."""
    line = subprocess.list2cmdline(cmd).replace("'", "''")
    script = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
              f"-Arguments @{{ CommandLine = '{line}' }}; exit [int]($r.ReturnValue -ne 0)")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("WMI process creation failed: %s", exc)
        return False
    if result.returncode != 0:
        log.warning("WMI process creation failed: %s", (result.stderr or result.stdout).strip()[:300])
        return False
    return True


def _still_ours(pid: int, token: str | None) -> dict | None:
    data = session.read()
    if not data or data.get("pid") != pid or (token and data.get("token") != token):
        return None
    return data


class _GameWatch:
    """Recognises a game's processes by its install folder and watched exe names."""

    MAX_DEPTH = 6

    def __init__(self, data: dict):
        folder = str(data.get("install_dir") or "")
        self.folder = os.path.normcase(os.path.normpath(folder)) if folder and os.path.isdir(folder) else ""
        self.watch = {str(w).lower() for w in data.get("watch") or [] if w}
        self.folder_exes: set[str] = set()
        if self.folder:
            for dirpath, dirnames, filenames in os.walk(folder):
                if os.path.relpath(dirpath, folder).count(os.sep) + 1 >= self.MAX_DEPTH:
                    dirnames[:] = []
                self.folder_exes.update(f.lower() for f in filenames if f.lower().endswith(".exe"))

    def running(self) -> bool:
        for pid, _, name in _snapshot():
            if name in self.watch:
                return True
            if name in self.folder_exes:
                try:
                    exe = os.path.normcase(psutil.Process(pid).exe())
                except psutil.Error:
                    continue
                if exe.startswith(self.folder + os.sep):
                    return True
        return False


def guard(pid: int, token: str | None = None) -> int:
    """Wait while the owner lives and the switch is still its; then clean up.

    Polls rather than waiting on the process, because a Playnite owner outlives
    many switches and the guard must leave once its own switch is undone. If
    the owner dies while the game is still running (Playnite restarting, the
    launcher killed), the guard takes the switch over and waits for the game.
    """
    while (data := _still_ours(pid, token)) and session.owner_alive(data):
        time.sleep(GUARD_POLL)
    if not data:
        return 0  # switched back normally, or a newer switch took over
    game_id = data.get("game_id") or ""
    name = _game_name(game_id)
    cause = (f"Playnite closed while {name} was running" if data.get("source") == "playnite"
             else f"The launcher for {name} closed unexpectedly")

    game = _GameWatch(data)
    waited = game.running()
    if waited:
        log.info("owner %d is gone but %s is still running; switching back when it exits", pid, game_id)
        data = session.adopt(data)
        while (current := _still_ours(os.getpid(), data["token"])) and game.running():
            time.sleep(GUARD_POLL)
        if not current:
            return 0  # something newer took over
        data = current

    mode = display.Mode.from_dict(data["original"])
    if display.current_mode() == mode:
        log.info("owner %d is gone; the display is already back at %s", pid, mode)
        session.clear(token=data.get("token"))
        return 0
    log.warning("owner %d ended without switching back; restoring", pid)
    try:
        code = restore()
    except display.DisplayError as exc:
        notify.notify(f"Couldn't switch back to {mode}",
                      f"{cause}. Open QRes GUI and click Restore desktop resolution. ({exc})", game_id=game_id)
        return 1
    if code == 0:
        after = f", so QRes switched back to {mode} once the game exited" if waited else \
            f", so QRes switched back to {mode}"
        notify.notify("Resolution restored", f"{cause}{after}.", level="info", game_id=game_id)
    return code


def restore() -> int:
    cfg = config.load()
    data = session.read()
    source = (data or {}).get("original") or cfg.get("desktop_mode")
    if not source:
        notify.notify("No desktop resolution saved", "Open QRes GUI once so it can record your desktop resolution.")
        return 1
    mode = display.Mode.from_dict(source)
    how = display.set_mode(mode, display.find_qres(cfg.get("qres_path")), bool(cfg.get("temporary", True)))
    log.info("restored %s (%s)", mode, how)
    session.clear()
    return 0


def _decode(payload: str) -> dict:
    data = json.loads(base64.b64decode(payload).decode("utf-8"))
    if not isinstance(data, dict):
        raise LaunchError("Playnite passed an unexpected payload.")
    return data


def playnite_start(payload: str) -> int:
    """Before-start script: switch for the Playnite game's QRes profile, if it has one."""
    info = _decode(payload)
    cfg = config.load()
    game_id, entry = playnite.match(cfg, info)
    if not game_id:
        log.info("no QRes profile for Playnite game %r (%s)", info.get("name"), info.get("installDir"))
        return 0
    if not entry.get("enabled"):
        log.info("switching is off for %s", game_id)
        return 0
    owner = playnite.owner_pid(int(info.get("owner") or 0))
    if owner is None:
        log.warning("no running Playnite to tie the switch to; not switching")
        return 0
    log.info("Playnite is starting %s (%s)", info.get("name"), game_id)
    _Switch(cfg, entry, game_id, owner=owner, install_dir=entry.get("install_dir") or str(info.get("installDir") or ""),
            source="playnite", playnite_id=str(info.get("id"))).apply()
    return 0


def playnite_stop(payload: str) -> int:
    """After-exit script: switch back if Playnite's switch for this game is still in place."""
    info = _decode(payload)
    data = session.read()
    if not data or data.get("source") != "playnite" or data.get("playnite_id") != str(info.get("id")):
        log.info("nothing of Playnite's to switch back for %s", info.get("id"))
        return 0
    cfg = config.load()
    entry = cfg.get("games", {}).get(data.get("game_id"), {})
    if not entry.get("quick_restore"):
        time.sleep(float(cfg.get("restore_delay", 1.0)))
    mode = display.Mode.from_dict(data["original"])
    try:
        how = display.set_mode(mode, display.find_qres(cfg.get("qres_path")), bool(cfg.get("temporary", True)))
    except display.DisplayError as exc:
        notify.notify(f"Couldn't switch back to {mode}",
                      f"Open QRes GUI and click Restore desktop resolution. ({exc})", game_id=data.get("game_id"))
        return 1
    log.info("restored %s after Playnite stopped %s (%s)", mode, data.get("game_id"), how)
    session.clear(token=data.get("token"))
    return 0


def remove_hooks(report: str | None) -> int:
    """Strip our Steam launch options and Playnite scripts, and delete game shortcuts
    (for the uninstaller). Touches nothing, and exits with EXIT_STEAM_RUNNING or
    EXIT_PLAYNITE_RUNNING, if Steam or Playnite needs changing but is open.
    """
    from . import hooks
    from .stores.steam import SteamClient, SteamRunningError

    client = SteamClient()
    found = hooks.find(client)
    summary = {"steam": sorted(found.steam), "shortcuts": [str(p) for p in found.shortcut_files],
               "playnite": found.playnite, "status": "ok"}
    code = 0
    try:
        hooks.remove(client, found)
        log.info("removed hooks: %s", summary)
    except SteamRunningError:
        summary["status"], code = "steam-running", EXIT_STEAM_RUNNING
        log.info("can't remove Steam hooks while Steam is running")
    except playnite.PlayniteRunningError:
        summary["status"], code = "playnite-running", EXIT_PLAYNITE_RUNNING
        log.info("can't remove Playnite scripts while Playnite is running")
    if report:
        with open(report, "w", encoding="utf-8") as fh:
            json.dump(summary, fh)
    return code


# --- plumbing --------------------------------------------------------------

def _setup_logging() -> None:
    handler = RotatingFileHandler(paths.log_path(), maxBytes=512_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(process)d] %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
