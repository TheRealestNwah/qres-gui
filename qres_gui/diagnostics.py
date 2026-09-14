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

import platform
import sys
import time
from dataclasses import dataclass, field

from . import __prerelease__, __version__, display, hdr, notify, paths, playnite, session

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


def _app_section() -> Section:
    build = "installed build" if getattr(sys, "frozen", False) else "run from source"
    return Section("QRes GUI", [
        _row("Version", lambda: f"{__version__}{'  (pre-release)' if __prerelease__ else ''}"),
        _row("Build", lambda: build),
        _row("Program folder", paths.app_folder),
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
        _row("Playnite", lambda: playnite.state(paths.launcher_command())),
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
