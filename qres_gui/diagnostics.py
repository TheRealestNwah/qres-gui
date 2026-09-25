"""What QRes GUI can see about this PC, gathered in one place.

Most of `docs/TROUBLESHOOTING.md` opens by asking the reader to find something
out - where QRes.exe is, which screen is primary, why the HDR control is greyed
out, whether a stale session record is sitting around. The running app already
knows all of it; this module collects it so a panel can show it and a bug report
can carry it.

Nothing here reads anything the app doesn't already read elsewhere, and nothing
here goes near the network: opening a diagnostics panel must not start an update
check. Every value is gathered through `_row`, so one broken getter costs its own
row and leaves the rest of the report standing - the report is read when
something is already wrong, which is the worst time to raise.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field

from . import __prerelease__, __version__, audio, display, hdr, notify, paths, playnite, scaling, session

UNKNOWN = "couldn't read"


@dataclass(frozen=True)
class Row:
    label: str
    value: str
    ok: bool = True          # False when the value is a failure, so a panel can mark it


@dataclass(frozen=True)
class Section:
    title: str
    rows: list[Row] = field(default_factory=list)


def _row(label: str, get, *, ok=None) -> Row:
    """One row, whose getter is allowed to fail.

    `get` returns the value; `ok` optionally judges it. A raising getter becomes
    a failed row naming the exception rather than taking the report down.
    """
    try:
        value = get()
    except Exception as exc:                                  # noqa: BLE001 - the whole point
        return Row(label, f"{UNKNOWN} ({exc.__class__.__name__}: {exc})", False)
    text = str(value)
    return Row(label, text, True if ok is None else bool(ok(value)))


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def _build() -> str:
    if paths.is_installed_copy():
        return "installed"
    if getattr(sys, "frozen", False):
        return "not installed (an unzipped or test copy)"
    return "run from source"


def _hooks_run() -> str:
    """What Steam, Playnite and shortcuts start games through, and whose it is."""
    cmd = subprocess.list2cmdline(paths.hook_command())
    if paths.runs_installed_hooks():
        return f"{cmd}  (the installed copy, not this one)"
    return cmd


def _app_section() -> Section:
    return Section("QRes GUI", [
        _row("Version", lambda: f"{__version__}{'  (pre-release)' if __prerelease__ else ''}"),
        _row("Build", _build),
        _row("Program folder", paths.app_folder),
        # The launcher is the command's last part: the .exe, or the .pyw from source.
        _row("Games launch through", _hooks_run, ok=lambda _: os.path.isfile(paths.hook_command()[-1])),
        _row("Settings", paths.config_path),
        _row("Log", paths.log_path),
    ])


def _windows_section() -> Section:
    return Section("Windows", [
        _row("Version", lambda: f"{platform.system()} {platform.release()} (build {platform.version()})"),
        _row("Python", lambda: sys.version.split()[0]),
    ])


def _qres_section(cfg: dict | None) -> Section:
    configured = (cfg or {}).get("qres_path") or ""

    def found() -> str:
        path = display.find_qres(configured or None)
        return path or "not found - set it in Settings, or put QRes.exe beside QResGUI.exe"

    return Section("QRes.exe", [
        _row("In use", found, ok=lambda v: not v.startswith("not found")),
        _row("Configured", lambda: configured or "(none - searching PATH and the program folder)"),
    ])


def _display_rows() -> list[Row]:
    screens = display.list_displays()
    if not screens:
        return [Row("Displays", f"{UNKNOWN} (Windows reported none)", False)]
    rows = []
    for screen in screens:
        rows.append(_row(screen.label, lambda s=screen: display.current_mode(s.device)))
    return rows


def _displays_section() -> Section:
    try:
        rows = _display_rows()
    except Exception as exc:                                  # noqa: BLE001
        rows = [Row("Displays", f"{UNKNOWN} ({exc.__class__.__name__}: {exc})", False)]
    return Section("Displays", rows)


def _hdr_rows() -> list[Row]:
    rows = []
    for screen in display.list_displays():
        state = hdr.status(screen.device)
        if not state.supported:
            rows.append(Row(screen.label, f"not available - {state.reason or 'Windows gave no reason'}", False))
        else:
            rows.append(Row(screen.label, f"available, currently {'on' if state.enabled else 'off'}"))
    return rows


def _hdr_section() -> Section:
    try:
        rows = _hdr_rows() or [Row("HDR", f"{UNKNOWN} (no displays)", False)]
    except Exception as exc:                                  # noqa: BLE001
        rows = [Row("HDR", f"{UNKNOWN} ({exc.__class__.__name__}: {exc})", False)]
    return Section("HDR", rows)


def _session_rows() -> list[Row]:
    active = session.read()
    if not active:
        return [Row("Record", "none - no switch is being tracked")]
    alive = session.owner_alive(active)
    original = active.get("original") or {}
    rows = [
        Row("Game", str(active.get("game_id") or "(unknown)")),
        Row("Owner", f"pid {active.get('pid')} - {'running' if alive else 'gone, the guard should have restored'}",
            alive),
        Row("Restores to", f"{original.get('width')}x{original.get('height')}"
                           f" @ {original.get('refresh')}Hz" if original else f"{UNKNOWN} (no mode recorded)"),
        Row("On display", str(active.get("device") or "the primary one")),
    ]
    if active.get("original_hdr") is not None:
        rows.append(Row("Restores HDR to", _yes(bool(active["original_hdr"]))))
    if active.get("original_scaling") is not None:
        rows.append(Row("Restores scaling to", scaling.describe(int(active["original_scaling"]))))
    if active.get("original_audio"):
        rows.append(Row("Restores audio to", active["original_audio"]))
    return rows


def _session_section() -> Section:
    try:
        rows = _session_rows()
    except Exception as exc:                                  # noqa: BLE001
        rows = [Row("Record", f"{UNKNOWN} ({exc.__class__.__name__}: {exc})", False)]
    return Section("Current switch", rows)


def _integrations_section(cfg: dict | None) -> Section:
    games = (cfg or {}).get("games") or {}

    def events() -> str:
        recent = notify.read_events()
        if not recent:
            return "none recorded"
        newest = recent[-1]
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(newest.get("time", 0)))
        return f"{len(recent)} kept, newest {when}: {newest.get('title', '(no title)')}"

    return Section("Integrations", [
        _row("Playnite", lambda: playnite.state(paths.hook_command())),
        _row("Games configured", lambda: len(games)),
        _row("Notification history", events),
    ])


def _updates_section(cfg: dict | None) -> Section:
    cfg = cfg or {}

    def when() -> str:
        stamp = cfg.get("update_last_check")
        if not stamp:
            return "never"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(stamp)))

    def found() -> str:
        available = cfg.get("update_available") or {}
        version = available.get("version")
        return f"{version} is available" if version else f"nothing newer than {__version__}"

    return Section("Updates", [_row("Last checked", when), _row("Result", found)])


def report(cfg: dict | None = None) -> list[Section]:
    """Everything worth knowing, in the order a reader wants it.

    `cfg` is the live config, which is also where the last update check's result
    already sits - read from there rather than re-checking, so that opening the
    panel never touches the network.
    """
    return [
        _app_section(),
        _windows_section(),
        _qres_section(cfg),
        _displays_section(),
        _hdr_section(),
        _session_section(),
        _integrations_section(cfg),
        _updates_section(cfg),
    ]


# --- one game's readiness -------------------------------------------------------
#
# The report above is about the PC; this one is about a single profile, checked
# against the PC as it is right now: would launching this game switch what it's
# set up to switch? Same rules - read only what the launcher itself would read,
# never change anything, and let one failing check cost only its own row.


def _checked(label: str, check) -> Row:
    """A readiness row from `check`, which returns (value, ok); raising costs only this row."""
    try:
        value, ok = check()
    except Exception as exc:                                  # noqa: BLE001
        return Row(label, f"{UNKNOWN} ({exc.__class__.__name__}: {exc})", False)
    return Row(label, value, ok)


def _profile_display_rows(cfg: dict, entry: dict) -> list[Row]:
    device = entry.get("display") or None
    screen = display.find_display(device)
    if screen is None:
        where = device or "The primary display"
        return [Row("Display", f"{where} isn't connected - the game will start without switching", False)]
    rows = [Row("Display", f"{screen.label}, connected")]

    width, height = int(entry.get("width") or 0), int(entry.get("height") or 0)
    refresh = int(entry.get("refresh") or 0)
    desktop = display.current_mode(device)
    modes = display.list_modes(device)
    target = display.resolve(width, height, refresh, desktop, device)

    def resolution():
        if not display.is_size_available(width, height, modes):
            return (f"{width} × {height} isn't a resolution Windows offers on this display - pick another, "
                    "or create it as a custom resolution in your graphics driver", False)
        if refresh and refresh != target.refresh:
            return f"{target} - {refresh} Hz isn't offered at this size, so it'll use {target.refresh} Hz", False
        if target == desktop:
            return f"{target}, the display's current mode - only the settings below change", True
        return f"{target}, from {desktop}", True

    def switched_by():
        if not display.drives_primary(device):
            return "the Windows API (QRes can only switch the primary display)", True
        qres = display.find_qres(cfg.get("qres_path"))
        if qres:
            return f"QRes ({qres})", True
        return "the Windows API - QRes.exe wasn't found; set it in Settings", False

    def hdr_row():
        want = entry.get("hdr")
        if want is None:
            return "left as it is", True
        state = hdr.status(device)
        if not state.supported:
            return f"won't change - {state.reason or 'Windows gave no reason'}", False
        now = "on" if state.enabled else "off"
        return f"turned {'on' if want else 'off'} while the game runs (it's {now} now)", True

    def scaling_row():
        choice = entry.get("scaling") or ""
        if choice not in scaling.CHOICES:
            return "left as it is", True
        if target == desktop:
            return "not used - the game runs at the display's own resolution", True
        if scaling.current(device) is None:
            return "won't change - Windows doesn't report this display's scaling mode", False
        label = next(text for text, key in scaling.LABELS if key == choice)
        return f"{label.lower()}; the graphics driver decides whether to follow it", True

    rows += [_checked("Resolution", resolution), _checked("Switched by", switched_by),
             _checked("HDR", hdr_row), _checked("Scaling", scaling_row)]
    return rows


def _audio_row(entry: dict) -> Row:
    def check():
        wanted = entry.get("audio_device")
        if not wanted:
            return "left as it is", True
        try:
            found = next((d for d in audio.outputs() if d.id == wanted), None)
        except audio.AudioError as exc:
            return f"won't change - {exc}", False
        if found is None:
            return ("the chosen device isn't active (unplugged or disabled) - the game will use "
                    "Windows' current one", False)
        return found.name, True
    return _checked("Audio", check)


def _launch_rows(game_id: str, entry: dict, hook: tuple[str, str] | None,
                 launch: dict | None, needs_watch: bool) -> list[Row]:
    rows = []
    if hook is not None:
        text, state = hook
        rows.append(Row("Starts through", text, state != "warn"))
    rows.append(_row("Launcher", lambda: paths.hook_command()[-1],
                     ok=lambda _: os.path.isfile(paths.hook_command()[-1])))
    target = entry.get("launch") or launch or {}
    if target.get("type") == "exe" and target.get("path"):
        path = target["path"]
        rows.append(Row("Game exe", path if os.path.isfile(path) else f"{path} isn't there any more",
                        os.path.isfile(path)))
    if needs_watch and not [w for w in entry.get("watch") or [] if w.strip()]:
        rows.append(Row("Game process", "not set - QRes can't tell when the game closes, so it switches "
                                        "back straight away; set it under Game process", False))

    def other_switch():
        active = session.read()
        if not active or not session.owner_alive(active) or active.get("game_id") == game_id:
            return "none", True
        return (f"{active.get('game_id') or 'another game'} is switched right now - this game won't "
                "switch until that one has been put back", False)
    rows.append(_checked("Other switches", other_switch))
    return rows


def readiness(cfg: dict, game_id: str, entry: dict | None, *, hook: tuple[str, str] | None = None,
              launch: dict | None = None, needs_watch: bool = False) -> Section:
    """Whether launching `game_id` now would do what its profile asks, one row per part.

    `hook` is how the game list describes the game's launch hook (its text and
    "ok" / "warn" / "off"), `launch` the store's launch target when the profile
    has none saved yet, and `needs_watch` whether the store starts the game
    itself so QRes needs its process name. Nothing is changed or started.
    """
    entry = entry or {}
    name = entry.get("name") or game_id
    if entry.get("enabled"):
        rows = [Row("Switching", "on")]
    else:
        rows = [Row("Switching", "off - the game starts as it is and nothing below is changed", False)]
    try:
        rows += _profile_display_rows(cfg or {}, entry)
    except Exception as exc:                                  # noqa: BLE001
        rows.append(Row("Display", f"{UNKNOWN} ({exc.__class__.__name__}: {exc})", False))
    rows.append(_audio_row(entry))
    rows += _launch_rows(game_id, entry, hook, launch, needs_watch)
    return Section(name, rows)


def problems(section: Section) -> list[Row]:
    """The rows of a readiness check that need looking at."""
    return [row for row in section.rows if not row.ok]


def as_text(sections: list[Section] | None = None, cfg: dict | None = None) -> str:
    """The report as plain text, for pasting into a bug report."""
    sections = report(cfg) if sections is None else sections
    lines = [f"QRes GUI diagnostics - {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for section in sections:
        lines.append(f"## {section.title}")
        width = max((len(row.label) for row in section.rows), default=0)
        for row in section.rows:
            lines.append(f"  {row.label.ljust(width)}  {row.value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
