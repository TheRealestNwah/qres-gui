"""What happens when the launcher or its owner goes away before the game does."""

import os
import shutil
import subprocess
import sys
import textwrap
import time

import psutil
import pytest

from qres_gui import config, display, launcher, notify, session

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))


def _wait_for_file(path, timeout=20.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


def _gone(pid: int, timeout: float) -> bool:
    try:
        psutil.Process(pid).wait(timeout)
        return True
    except psutil.NoSuchProcess:
        return True
    except psutil.TimeoutExpired:
        return False


def _child(tmp_path, body: str) -> tuple[subprocess.Popen, int, int]:
    """Run `body` in a separate Python; returns (proc, its real pid, the 'game' pid it started)."""
    me, game = tmp_path / "me.pid", tmp_path / "game.pid"
    script = tmp_path / "child.py"
    script.write_text(textwrap.dedent(f"""
        import os, subprocess, sys
        sys.path.insert(0, {ROOT!r})
        from qres_gui import launcher
        open({str(me)!r}, "w").write(str(os.getpid()))
        GAME = [sys.executable, "-c", "import os, time; open('{game.as_posix()}', 'w').write(str(os.getpid())); time.sleep(60)"]
    """) + textwrap.dedent(body))
    # The base interpreter, not the venv's python.exe: that one is a small launcher
    # that puts its child in its own kill-on-close job, which would muddy the test.
    # (The built QResLauncher.exe runs in-process, like this.)
    path = os.pathsep.join(p for p in sys.path if p and os.path.isdir(p))
    proc = subprocess.Popen([sys._base_executable, str(script)], env={**os.environ, "PYTHONPATH": path})
    return proc, int(_wait_for_file(me)), int(_wait_for_file(game))


def test_killing_the_launcher_closes_the_game(tmp_path):
    """Steam's Stop ends the launcher; the game must go with it."""
    proc, launcher_pid, game_pid = _child(tmp_path, """
        sys.exit(launcher.run("steam:1", GAME))
    """)
    try:
        assert psutil.pid_exists(game_pid)
        psutil.Process(launcher_pid).kill()  # what Steam's Stop does
        assert _gone(game_pid, 5), "the game survived the launcher being killed"
    finally:
        proc.kill()
        for pid in (game_pid,):
            if psutil.pid_exists(pid):
                psutil.Process(pid).kill()


def test_normal_exit_leaves_the_rest_running(tmp_path):
    proc, _, game_pid = _child(tmp_path, """
        with launcher._CloseGameWithUs():
            subprocess.Popen(GAME)
    """)
    try:
        proc.wait(20)
        time.sleep(0.5)
        assert psutil.pid_exists(game_pid), "a normal exit shouldn't close anything"
    finally:
        if psutil.pid_exists(game_pid):
            psutil.Process(game_pid).kill()


def test_guard_survives_a_steam_style_job_being_ended(tmp_path):
    """Steam's Stop ends a job that doesn't allow breaking away; the guard must not be in it."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    ntdll = ctypes.WinDLL("ntdll")

    guard_pid_file = tmp_path / "guard.pid"
    stand_in_guard = tmp_path / "guard_stand_in.py"  # plays the launcher's "guard" command
    stand_in_guard.write_text(
        f"import os, time; open('{guard_pid_file.as_posix()}', 'w').write(str(os.getpid())); time.sleep(60)")
    starter = tmp_path / "starter.py"
    starter.write_text(textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {ROOT!r})
        from qres_gui import launcher, paths
        paths.launcher_command = lambda: [sys.executable, {str(stand_in_guard)!r}]
        launcher._spawn_guard(os.getpid(), "token").join(60)
        time.sleep(60)
    """))
    job = k32.CreateJobObjectW(None, None)  # default limits: no breaking away
    path = os.pathsep.join(p for p in sys.path if p and os.path.isdir(p))
    proc = subprocess.Popen([sys._base_executable, str(starter)], env={**os.environ, "PYTHONPATH": path},
                            creationflags=0x4)  # suspended until it's in the job
    handle = k32.OpenProcess(0x1F0FFF, False, proc.pid)
    assert k32.AssignProcessToJobObject(job, handle)
    ntdll.NtResumeProcess(wintypes.HANDLE(handle))
    guard_pid = int(_wait_for_file(guard_pid_file, timeout=60))
    try:
        k32.TerminateJobObject(job, 1)  # Steam's Stop
        assert _gone(proc.pid, 5)
        time.sleep(0.5)
        assert psutil.pid_exists(guard_pid), "the guard was ended along with the job"
    finally:
        if psutil.pid_exists(guard_pid):
            psutil.Process(guard_pid).kill()


def test_guard_survives_its_starters_process_tree_being_killed(tmp_path):
    """Steam's Stop ends the launched process and all its descendants, like "End process tree"."""
    guard_pid_file = tmp_path / "guard.pid"
    stand_in_guard = tmp_path / "guard_stand_in.py"
    stand_in_guard.write_text(
        f"import os, time; open('{guard_pid_file.as_posix()}', 'w').write(str(os.getpid())); time.sleep(60)")
    starter = tmp_path / "starter.py"
    starter.write_text(textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {ROOT!r})
        from qres_gui import launcher, paths
        paths.launcher_command = lambda: [sys.executable, {str(stand_in_guard)!r}]
        launcher._spawn_guard(os.getpid(), "token").join(60)
        time.sleep(60)
    """))
    path = os.pathsep.join(p for p in sys.path if p and os.path.isdir(p))
    proc = subprocess.Popen([sys._base_executable, str(starter)], env={**os.environ, "PYTHONPATH": path})
    guard_pid = int(_wait_for_file(guard_pid_file, timeout=60))
    try:
        root = psutil.Process(proc.pid)
        for p in root.children(recursive=True) + [root]:  # "End process tree"
            p.kill()
        time.sleep(0.5)
        assert psutil.pid_exists(guard_pid), "the guard was in the starter's process tree"
    finally:
        if psutil.pid_exists(guard_pid):
            psutil.Process(guard_pid).kill()


def test_guard_waits_for_a_game_that_outlives_its_owner(tmp_path, monkeypatch):
    """Playnite restarting mid-game: switch back when the game exits, not straight away."""
    monkeypatch.setattr(launcher, "GUARD_POLL", 0.1)
    desktop = display.Mode(3440, 1440, 165)
    state = {"mode": display.Mode(2560, 1440, 165), "restored_at": None}

    def set_mode(mode, qres, temporary):
        state["mode"], state["restored_at"] = mode, time.monotonic()
        return "stub"

    monkeypatch.setattr(display, "current_mode", lambda: state["mode"])
    monkeypatch.setattr(display, "set_mode", set_mode)
    shown = []
    monkeypatch.setattr(notify, "notify", lambda title, message, **k: shown.append((title, message)))
    cfg = config.load()
    cfg["games"]["steam:9"] = {"name": "MGS4"}
    config.save(cfg)

    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    exe = game_dir / "qres_test_game.exe"
    shutil.copy(r"C:\Windows\System32\PING.EXE", exe)
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])  # stands in for Playnite
    token = session.write(desktop.to_dict(), "steam:9", owner=owner.pid, install_dir=str(game_dir),
                          watch=[], source="playnite")
    game = subprocess.Popen([str(exe), "-n", "4", "127.0.0.1"], stdout=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)

    assert launcher.guard(owner.pid, token) == 0
    game_ended = time.monotonic()
    assert game.poll() is not None  # the guard only returned once the game was gone
    assert state["mode"] == desktop and state["restored_at"] <= game_ended
    assert shown and "once the game exited" in shown[-1][1]
    assert session.read() is None


def test_guard_stays_quiet_when_the_display_is_already_back(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "GUARD_POLL", 0.05)
    desktop = display.Mode(3440, 1440, 165)
    monkeypatch.setattr(display, "current_mode", lambda: desktop)
    monkeypatch.setattr(display, "set_mode", lambda *a: pytest.fail("nothing to switch"))
    monkeypatch.setattr(notify, "notify", lambda *a, **k: pytest.fail("nothing to report"))
    owner = subprocess.Popen([sys.executable, "-c", "pass"])
    owner.wait()
    owner_pid = os.getpid()  # a live pid for the write; then point the record at the dead one
    token = session.write(desktop.to_dict(), "x", owner=owner_pid)
    data = session.read()
    data["pid"] = owner.pid
    session._store(data)
    assert launcher.guard(owner.pid, token) == 0
    assert session.read() is None
