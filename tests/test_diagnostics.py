"""The diagnostics report: what it says, and that a broken getter can't take it down.

None of the Windows APIs are exercised here - `display` and `hdr` both talk to
Windows - so they're stood in for by fakes, the same way test_hdr.py does it.
The behaviour that matters most is the last test: the report is read when
something has already gone wrong, so a section that raises must cost its own row
and nothing else.
"""

import pytest

from qres_gui import audio, diagnostics, display, hdr, notify, paths, playnite, scaling, session

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


# --- one game's readiness ---------------------------------------------------------

PRIMARY_MODES = [MODE, display.Mode(3440, 1440, 60), display.Mode(2560, 1440, 165), display.Mode(2560, 1440, 60)]
SECOND_MODES = [SECOND_MODE, display.Mode(1280, 720, 60)]


@pytest.fixture
def ready(two_screens, monkeypatch, tmp_path):
    """A PC where everything a profile can ask for is there: modes, QRes, HDR, scaling, audio, the launcher."""
    monkeypatch.setattr(display, "list_modes",
                        lambda device=None: list(SECOND_MODES if device == SECOND.device else PRIMARY_MODES))
    monkeypatch.setattr(display, "find_qres", lambda configured=None: r"C:\Tools\QRes.exe")
    monkeypatch.setattr(scaling, "current", lambda device=None: scaling.IDENTITY)
    monkeypatch.setattr(audio, "outputs", lambda: [audio.Device("speakers", "Desktop speakers"),
                                                   audio.Device("headset", "Headset")])
    launcher = tmp_path / "QResLauncher.exe"
    launcher.write_bytes(b"MZ")
    monkeypatch.setattr(paths, "hook_command", lambda: [str(launcher)])
    exe = tmp_path / "Game.exe"
    exe.write_bytes(b"MZ")
    return {"exe": str(exe)}


def _profile(**changes):
    entry = {"name": "Stardew Valley", "enabled": True, "width": 2560, "height": 1440, "refresh": 0,
             "display": "", "hdr": None, "scaling": None, "audio_device": None, "watch": [], "launch": None}
    entry.update(changes)
    return entry


def _rows(section):
    return {row.label: row for row in section.rows}


def test_a_profile_that_will_work_has_nothing_to_look_at(ready):
    section = diagnostics.readiness(CFG, "gog:1", _profile(hdr=True, scaling="aspect", audio_device="headset"),
                                    hook=("Shortcut: Desktop", "ok"))
    assert diagnostics.problems(section) == []
    rows = _rows(section)
    assert section.title == "Stardew Valley"
    assert rows["Resolution"].value.startswith("2560 × 1440 @ 165 Hz")     # the desktop's rate, as the launcher picks
    assert "QRes" in rows["Switched by"].value
    assert rows["HDR"].value.startswith("turned on")
    assert rows["Scaling"].value.startswith("keep aspect ratio")
    assert rows["Audio"].value == "Headset"
    assert rows["Starts through"].value == "Shortcut: Desktop"


def test_switching_off_is_the_first_thing_said(ready):
    [first, *_] = diagnostics.readiness(CFG, "gog:1", _profile(enabled=False)).rows
    assert first.label == "Switching" and not first.ok


def test_an_unplugged_display_stops_the_display_checks_there(ready):
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile(display=r"\\.\DISPLAY7")))
    assert not rows["Display"].ok and "isn't connected" in rows["Display"].value
    assert "Resolution" not in rows and "HDR" not in rows      # nothing to check them against
    assert "Audio" in rows                                     # audio doesn't depend on the display


def test_a_resolution_the_display_doesnt_offer_is_flagged(ready):
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile(display=SECOND.device, width=2560, height=1440)))
    assert not rows["Resolution"].ok and "custom resolution" in rows["Resolution"].value


def test_a_refresh_rate_it_doesnt_offer_says_what_it_will_use(ready):
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile(refresh=144)))
    assert not rows["Resolution"].ok
    assert "144 Hz isn't offered" in rows["Resolution"].value and "use 165 Hz" in rows["Resolution"].value


def test_a_second_display_is_switched_without_qres(ready):
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile(display=SECOND.device, width=1280, height=720)))
    assert rows["Switched by"].ok and "Windows API" in rows["Switched by"].value


def test_missing_qres_is_flagged_for_the_primary_display(ready, monkeypatch):
    monkeypatch.setattr(display, "find_qres", lambda configured=None: None)
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile()))
    assert not rows["Switched by"].ok and "QRes.exe wasn't found" in rows["Switched by"].value


def test_hdr_that_windows_cant_do_gives_its_reason(ready, monkeypatch):
    monkeypatch.setattr(hdr, "status", lambda device=None: hdr.Status(supported=False, reason=hdr.NO_API))
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile(hdr=True)))
    assert not rows["HDR"].ok and hdr.NO_API in rows["HDR"].value
    # a profile that leaves HDR alone has nothing to worry about
    assert _rows(diagnostics.readiness(CFG, "gog:1", _profile()))["HDR"].ok


def test_scaling_is_only_checked_when_the_game_runs_at_another_size(ready, monkeypatch):
    monkeypatch.setattr(scaling, "current", lambda device=None: None)
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile(scaling="stretch")))
    assert not rows["Scaling"].ok and "doesn't report" in rows["Scaling"].value
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile(scaling="stretch", width=3440, height=1440)))
    assert rows["Scaling"].ok and rows["Scaling"].value.startswith("not used")


def test_an_audio_device_thats_gone_is_flagged(ready, monkeypatch):
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile(audio_device="unplugged")))
    assert not rows["Audio"].ok and "isn't active" in rows["Audio"].value

    def unavailable():
        raise audio.AudioError("Windows audio controls aren't available")
    monkeypatch.setattr(audio, "outputs", unavailable)
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile(audio_device="headset")))
    assert not rows["Audio"].ok and "aren't available" in rows["Audio"].value


def test_launch_problems_are_flagged(ready):
    hooked = diagnostics.readiness(CFG, "gog:1", _profile(launch={"type": "exe", "path": ready["exe"]}),
                                   hook=("No shortcut yet", "warn"))
    rows = _rows(hooked)
    assert not rows["Starts through"].ok and rows["Game exe"].ok and rows["Launcher"].ok

    gone = r"C:\Games\Removed\Game.exe"
    rows = _rows(diagnostics.readiness(CFG, "xbox:1", _profile(launch={"type": "exe", "path": gone}),
                                       needs_watch=True))
    assert not rows["Game exe"].ok and "isn't there any more" in rows["Game exe"].value
    assert not rows["Game process"].ok
    # the store's own target counts when the profile hasn't saved one yet
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile(), launch={"type": "exe", "path": ready["exe"]}))
    assert rows["Game exe"].ok


def test_another_games_live_switch_is_flagged_but_not_this_ones(ready, monkeypatch):
    monkeypatch.setattr(session, "read", lambda: {"pid": 4321, "game_id": "steam:10"})
    monkeypatch.setattr(session, "owner_alive", lambda data: True)
    assert not _rows(diagnostics.readiness(CFG, "gog:1", _profile()))["Other switches"].ok
    assert _rows(diagnostics.readiness(CFG, "steam:10", _profile()))["Other switches"].ok


def test_a_raising_check_costs_only_its_own_row(ready, monkeypatch):
    def boom(*a, **k):
        raise OSError("the display driver gave up")
    monkeypatch.setattr(hdr, "status", boom)
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile(hdr=True)))
    assert not rows["HDR"].ok and "gave up" in rows["HDR"].value
    assert rows["Resolution"].ok and rows["Audio"].ok

    monkeypatch.setattr(display, "list_displays", boom)
    rows = _rows(diagnostics.readiness(CFG, "gog:1", _profile()))
    assert not rows["Display"].ok and "gave up" in rows["Display"].value
    assert rows["Audio"].ok and "Other switches" in rows


def test_readiness_reads_as_text(ready):
    text = diagnostics.as_text([diagnostics.readiness(CFG, "gog:1", _profile())])
    assert "## Stardew Valley" in text and "Resolution" in text
