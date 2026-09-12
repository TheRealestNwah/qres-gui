"""Notifications: the event record, toast XML, fallbacks, and which launcher paths notify."""

import subprocess
import sys
import xml.dom.minidom

import psutil
import pytest

from qres_gui import config, display, launcher, notify, session


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    shown, boxes = [], []
    monkeypatch.setattr(notify, "toast", lambda title, message: shown.append((title, message)) or True)
    monkeypatch.setattr(notify, "_message_box", lambda *a: boxes.append(a))
    return shown, boxes


def test_notify_records_and_toasts(isolated):
    shown, boxes = isolated
    notify.notify("Couldn't switch", "details", game_id="steam:1")
    assert shown == [("Couldn't switch", "details")] and boxes == []
    [event] = notify.read_events()
    assert event["title"] == "Couldn't switch" and event["game_id"] == "steam:1" and event["level"] == "warning"


def test_message_box_only_when_toast_fails(isolated, monkeypatch):
    _, boxes = isolated
    monkeypatch.setattr(notify, "toast", lambda title, message: False)
    notify.notify("t", "m", level="info")
    assert boxes == [("t", "m", "info")]


def test_event_record_is_capped():
    for i in range(notify.EVENTS_KEPT + 5):
        notify.record(f"t{i}", "m")
    events = notify.read_events()
    assert len(events) == notify.EVENTS_KEPT and events[-1]["title"] == f"t{notify.EVENTS_KEPT + 4}"


def test_toast_xml_escapes_everything():
    text = notify.toast_xml("It's <b>&", 'say "hi" \'@')
    doc = xml.dom.minidom.parseString(text)
    assert [n.firstChild.data for n in doc.getElementsByTagName("text")] == ["It's <b>&", 'say "hi" \'@']
    assert "'" not in text  # it's embedded in a single-quoted PowerShell string


def test_switch_failure_notifies_and_still_launches(isolated, monkeypatch):
    shown, _ = isolated
    monkeypatch.setattr(display, "current_mode", lambda: display.Mode(3440, 1440, 165))
    monkeypatch.setattr(display, "resolve", lambda w, h, r, d: display.Mode(w, h, 165))

    def failing_set_mode(mode, qres, temporary):
        if mode.width == 2560:
            raise display.DisplayError("nope")
        return "stub"

    monkeypatch.setattr(display, "set_mode", failing_set_mode)
    monkeypatch.setattr(launcher, "_spawn_guard", lambda: None)
    cfg = config.load()
    cfg.update(switch_delay=0, restore_delay=0)
    cfg["games"]["steam:1"] = {"name": "Test Game", "enabled": True, "width": 2560, "height": 1440}
    config.save(cfg)
    assert launcher.run("steam:1", [sys.executable, "-c", "raise SystemExit(7)"]) == 7
    assert shown[0][0].startswith("Couldn't switch to 2560")
    assert "Test Game" in shown[0][1]


def test_start_failure_notifies_with_game_name(isolated):
    shown, _ = isolated
    cfg = config.load()
    cfg["games"]["gog:1"] = {"name": "Stardew Valley", "enabled": False,
                             "launch": {"type": "exe", "path": r"C:\nope\missing.exe"}}
    config.save(cfg)
    assert launcher.main(["run", "gog:1"]) == 1
    assert shown[0][0] == "Couldn't start Stardew Valley"
    assert shown[0][1].startswith(r"C:\nope\missing.exe doesn't exist")


def test_guard_restores_and_says_so(isolated, monkeypatch):
    shown, _ = isolated
    desktop = display.Mode(3440, 1440, 165)
    calls = []
    monkeypatch.setattr(display, "set_mode", lambda mode, qres, temporary: calls.append(mode) or "stub")
    cfg = config.load()
    cfg["games"]["steam:9"] = {"name": "MGS4"}
    config.save(cfg)
    # A short-lived process stands in for a launcher that got killed.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
    session.write(desktop.to_dict(), "steam:9")
    data = session.read()
    data["pid"], data["create_time"] = proc.pid, psutil.Process(proc.pid).create_time()
    session.paths.session_path().write_text(__import__("json").dumps(data))

    assert launcher.guard(proc.pid) == 0
    assert calls == [desktop]
    assert shown[0][0] == "Resolution restored" and "MGS4" in shown[0][1]
    assert notify.read_events()[-1]["level"] == "info"
    assert session.read() is None
