"""The diagnostics report: what it says, and that a broken getter can't take it down.

None of the Windows APIs are exercised here - `display` and `hdr` both talk to
Windows - so they're stood in for by fakes, the same way test_hdr.py does it.
The behaviour that matters most is the last test: the report is read when
something has already gone wrong, so a section that raises must cost its own row
and nothing else.
"""

import pytest

from qres_gui import diagnostics, display, hdr, notify, playnite, session

PRIMARY = display.Display(r"\\.\DISPLAY1", "Main Monitor", True)
SECOND = display.Display(r"\\.\DISPLAY2", "Side Monitor", False)
MODE = display.Mode(3440, 1440, 165)
SECOND_MODE = display.Mode(1920, 1080, 60)

CFG = {"qres_path": r"C:\Tools\QRes.exe", "games": {"a": {}, "b": {}}}


@pytest.fixture
def two_screens(monkeypatch):
    """Two displays, both readable, HDR available on neither unless a test says so."""
    monkeypatch.setattr(display, "list_displays", lambda: [PRIMARY, SECOND])
    monkeypatch.setattr(display, "current_mode",
                        lambda device=None: SECOND_MODE if device == SECOND.device else MODE)
    monkeypatch.setattr(display, "find_qres", lambda configured=None: configured)
    monkeypatch.setattr(hdr, "status", lambda device=None: hdr.Status(supported=True, enabled=False))
    monkeypatch.setattr(session, "read", lambda: None)
    monkeypatch.setattr(notify, "read_events", list)
    monkeypatch.setattr(playnite, "state", lambda cmd: "not installed")


def _section(sections, title):
    return next(s for s in sections if s.title == title)


def _values(sections, title):
    return [row.value for row in _section(sections, title).rows]


def test_every_display_is_reported_with_its_own_mode(two_screens):
    rows = _section(diagnostics.report(CFG), "Displays").rows
    assert [row.label for row in rows] == [PRIMARY.label, SECOND.label]
    assert str(MODE) in rows[0].value and str(SECOND_MODE) in rows[1].value
    assert "(primary)" in rows[0].label and "(primary)" not in rows[1].label


def test_hdr_reason_reaches_the_report_verbatim(two_screens, monkeypatch):
    """The whole point of the HDR row: say why, in Windows' own words."""
    monkeypatch.setattr(hdr, "status",
                        lambda device=None: hdr.Status(supported=False, reason=hdr.NO_API))
    rows = _section(diagnostics.report(CFG), "HDR").rows
    assert all(hdr.NO_API in row.value for row in rows)
    assert all(not row.ok for row in rows)


def test_hdr_reports_on_and_off(two_screens, monkeypatch):
    monkeypatch.setattr(hdr, "status",
                        lambda device=None: hdr.Status(supported=True,
                                                       enabled=device == SECOND.device))
    rows = _section(diagnostics.report(CFG), "HDR").rows
    assert rows[0].value.endswith("off") and rows[1].value.endswith("on")
    assert all(row.ok for row in rows)


def test_a_live_session_is_reported_with_its_display_and_hdr(two_screens, monkeypatch):
    monkeypatch.setattr(session, "read", lambda: {
        "pid": 4321, "game_id": "steam:10", "device": SECOND.device, "original_hdr": True,
        "original": {"width": 1920, "height": 1080, "refresh": 60}})
    monkeypatch.setattr(session, "owner_alive", lambda data: True)
    values = " ".join(_values(diagnostics.report(CFG), "Current switch"))
    assert "steam:10" in values and SECOND.device in values
    assert "1920x1080 @ 60Hz" in values and "running" in values
    assert "Restores HDR to" in [row.label for row in _section(diagnostics.report(CFG), "Current switch").rows]


def test_a_dead_owner_is_flagged_not_just_listed(two_screens, monkeypatch):
    monkeypatch.setattr(session, "read", lambda: {
        "pid": 4321, "game_id": "steam:10", "original": {"width": 1920, "height": 1080, "refresh": 60}})
    monkeypatch.setattr(session, "owner_alive", lambda data: False)
    owner = next(r for r in _section(diagnostics.report(CFG), "Current switch").rows if r.label == "Owner")
    assert not owner.ok and "gone" in owner.value


def test_no_session_says_so_rather_than_failing(two_screens):
    rows = _section(diagnostics.report(CFG), "Current switch").rows
    assert len(rows) == 1 and rows[0].ok and "none" in rows[0].value


def test_missing_qres_is_marked_not_found(two_screens, monkeypatch):
    monkeypatch.setattr(display, "find_qres", lambda configured=None: None)
    in_use = _section(diagnostics.report(CFG), "QRes.exe").rows[0]
    assert not in_use.ok and "not found" in in_use.value


def test_found_qres_is_not_marked(two_screens):
    assert _section(diagnostics.report(CFG), "QRes.exe").rows[0].ok


def test_a_raising_getter_costs_one_section_and_no_more(two_screens, monkeypatch):
    """A display driver that throws must not cost the HDR reason or the log path."""
    def boom(*a, **k):
        raise OSError("the display driver gave up")

    monkeypatch.setattr(display, "list_displays", boom)
    sections = diagnostics.report(CFG)

    broken = _section(sections, "Displays").rows
    assert len(broken) == 1 and not broken[0].ok
    assert "the display driver gave up" in broken[0].value

    # everything that doesn't depend on the displays is still there
    assert _section(sections, "QRes.exe").rows[0].ok
    assert all(row.ok for row in _section(sections, "QRes GUI").rows)
    # and the HDR section degrades the same way rather than escaping
    assert not _section(sections, "HDR").rows[0].ok


def test_report_survives_every_section_failing(monkeypatch):
    """Nothing readable at all still produces a report, which is when one is needed most."""
    def boom(*a, **k):
        raise RuntimeError("nope")

    for module, name in ((display, "list_displays"), (display, "find_qres"), (hdr, "status"),
                         (session, "read"), (notify, "read_events"), (playnite, "state")):
        monkeypatch.setattr(module, name, boom)
    sections = diagnostics.report(CFG)
    assert len(sections) == 8
    assert diagnostics.as_text(sections)


def test_as_text_carries_the_version_and_every_heading(two_screens):
    from qres_gui import __version__
    sections = diagnostics.report(CFG)
    text = diagnostics.as_text(sections)
    assert __version__ in text
    for section in sections:
        assert f"## {section.title}" in text
    assert text.endswith("\n")
