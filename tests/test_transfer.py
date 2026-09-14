"""Backing up and restoring profiles: what travels, what deliberately doesn't.

The whole point of this module is that a config is *not* portable, so most of
these tests are about what an export refuses to carry - machine-local paths, and
a display that means a different monitor on the other PC. `display` is stood in
for by a fake, as everywhere else in this suite.
"""

import json

import pytest

from qres_gui import display, transfer

PRIMARY = display.Display(r"\\.\DISPLAY1", "Main Monitor", True)
SECOND = display.Display(r"\\.\DISPLAY2", "Side Monitor", False)


@pytest.fixture
def two_screens(monkeypatch):
    monkeypatch.setattr(display, "list_displays", lambda: [PRIMARY, SECOND])
    monkeypatch.setattr(display, "find_display",
                        lambda device: {PRIMARY.device: PRIMARY, SECOND.device: SECOND}.get(device))


@pytest.fixture
def cfg():
    return {
        "qres_path": r"C:\Tools\QRes.exe",                 # this PC's
        "desktop_mode": {"width": 3440, "height": 1440, "refresh": 165},   # this PC's
        "update_last_check": 1_700_000_000,                # local state
        "first_run_done": True,                            # local state
        "temporary": True, "switch_delay": 1.5, "tray_icon": False,
        "restore_hotkey": "Ctrl+Alt+R",
        "presets": [{"name": "Tall", "width": 2560, "height": 1080, "refresh": 60,
                     "hotkey": "Ctrl+Alt+1", "display": SECOND.device}],
        "games": {
            "steam:620": {"name": "Portal 2", "store": "steam", "enabled": True,
                          "width": 2560, "height": 1440, "refresh": 0, "hdr": True,
                          "extra_args": "-windowed", "watch": ["portal2.exe"],
                          "display": SECOND.device,
                          "launch": {"type": "uri", "uri": "steam://run/620"},
                          "install_dir": r"C:\Steam\Portal 2"},
            "manual:1": {"name": "Some Game", "store": "manual", "enabled": True,
                         "width": 1920, "height": 1080, "refresh": 60,
                         "launch": {"type": "exe", "path": r"D:\Games\game.exe"}},
        },
    }


# --- export: what must not travel -------------------------------------------

def test_export_leaves_out_everything_about_this_pc(two_screens, cfg):
    data = transfer.export_data(cfg)
    assert set(data["settings"]) <= set(transfer.PORTABLE_SETTINGS)
    for local in ("qres_path", "desktop_mode", "update_last_check", "first_run_done"):
        assert local not in data["settings"]


def test_export_drops_a_store_games_launch_and_install_dir(two_screens, cfg):
    """A rescan rewrites both from the store, so carrying them is wrong and pointless."""
    saved = transfer.export_data(cfg)["games"]["steam:620"]
    assert "launch" not in saved and "install_dir" not in saved
    assert saved["extra_args"] == "-windowed" and saved["hdr"] is True


def test_export_keeps_a_manual_games_launch(two_screens, cfg):
    """A manual game is rebuilt from its launch block, so it doesn't survive without one."""
    saved = transfer.export_data(cfg)["games"]["manual:1"]
    assert saved["launch"]["path"] == r"D:\Games\game.exe"


def test_export_records_the_monitors_name_not_just_its_device(two_screens, cfg):
    saved = transfer.export_data(cfg)["games"]["steam:620"]["display"]
    assert saved["name"] == "Side Monitor" and saved["number"] == "2"


def test_export_survives_a_display_lookup_that_raises(cfg, monkeypatch):
    def boom(*a, **k):
        raise OSError("no display driver")

    monkeypatch.setattr(display, "find_display", boom)
    monkeypatch.setattr(display, "list_displays", boom)
    data = transfer.export_data(cfg)          # must not raise
    assert data["games"]["steam:620"]["display"]["name"] == ""


# --- import: reading the file ------------------------------------------------

def _write(tmp_path, data):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_round_trip(two_screens, cfg, tmp_path):
    path = transfer.write_export(cfg, tmp_path / "out.json")
    data = transfer.read_export(path)
    assert data["kind"] == transfer.KIND and data["format"] == transfer.FORMAT
    assert set(data["games"]) == {"steam:620", "manual:1"}


@pytest.mark.parametrize("content, says", [
    ("not json at all", "isn't valid JSON"),
    (json.dumps({"hello": "world"}), "isn't a QRes GUI profile export"),
    (json.dumps({"kind": transfer.KIND}), "doesn't say which format"),
    (json.dumps({"kind": transfer.KIND, "format": 99}), "newer QRes GUI"),
    (json.dumps({"kind": transfer.KIND, "format": 1, "games": []}), "\"games\" section is damaged"),
])
def test_a_bad_file_says_why_and_never_half_applies(tmp_path, content, says):
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(transfer.TransferError) as exc:
        transfer.read_export(path)
    assert says in str(exc.value)


def test_a_missing_file_is_a_transfer_error_not_an_oserror(tmp_path):
    with pytest.raises(transfer.TransferError):
        transfer.read_export(tmp_path / "nope.json")


# --- import: merging ---------------------------------------------------------

def test_import_adds_and_updates_but_leaves_other_games_alone(two_screens, cfg, tmp_path):
    data = transfer.read_export(transfer.write_export(cfg, tmp_path / "out.json"))
    target = {"games": {"steam:620": {"name": "Portal 2", "store": "steam", "enabled": False,
                                      "width": 1920, "height": 1080, "refresh": 60,
                                      "launch": {"type": "uri", "uri": "steam://run/620"}},
                        "gog:99": {"name": "Untouched", "store": "gog", "enabled": True}},
              "presets": []}
    summary = transfer.merge(target, data)
    assert summary.games_added == 1 and summary.games_updated == 1
    assert target["games"]["gog:99"] == {"name": "Untouched", "store": "gog", "enabled": True}
    assert target["games"]["steam:620"]["width"] == 2560 and target["games"]["steam:620"]["enabled"]


def test_import_never_overwrites_a_store_games_local_launch(two_screens, cfg, tmp_path):
    """The local launch block belongs to this machine; the next rescan owns it."""
    data = transfer.read_export(transfer.write_export(cfg, tmp_path / "out.json"))
    mine = {"type": "uri", "uri": "steam://run/620?thisPC"}
    target = {"games": {"steam:620": {"store": "steam", "launch": mine,
                                      "install_dir": r"E:\Elsewhere"}}}
    transfer.merge(target, data)
    assert target["games"]["steam:620"]["launch"] == mine
    assert target["games"]["steam:620"]["install_dir"] == r"E:\Elsewhere"


def test_a_display_that_matches_by_name_and_number_is_kept(two_screens, cfg, tmp_path):
    data = transfer.read_export(transfer.write_export(cfg, tmp_path / "out.json"))
    target = {}
    summary = transfer.merge(target, data)
    assert target["games"]["steam:620"]["display"] == SECOND.device
    assert summary.displays_kept >= 1 and not summary.displays_dropped


def test_a_display_this_pc_doesnt_have_falls_back_to_primary_and_is_reported(cfg, tmp_path, monkeypatch):
    """The failure this app is careful about: never aim at a screen by guesswork."""
    monkeypatch.setattr(display, "list_displays", lambda: [PRIMARY, SECOND])
    monkeypatch.setattr(display, "find_display",
                        lambda device: {PRIMARY.device: PRIMARY, SECOND.device: SECOND}.get(device))
    data = transfer.read_export(transfer.write_export(cfg, tmp_path / "out.json"))

    monkeypatch.setattr(display, "list_displays", lambda: [PRIMARY])   # the other PC has one screen
    target = {}
    summary = transfer.merge(target, data)
    assert target["games"]["steam:620"]["display"] == ""
    assert "Portal 2" in summary.displays_dropped


def test_a_same_named_monitor_at_a_different_number_is_not_assumed(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(display, "list_displays", lambda: [PRIMARY, SECOND])
    monkeypatch.setattr(display, "find_display",
                        lambda device: {PRIMARY.device: PRIMARY, SECOND.device: SECOND}.get(device))
    data = transfer.read_export(transfer.write_export(cfg, tmp_path / "out.json"))

    moved = display.Display(r"\\.\DISPLAY3", "Side Monitor", False)     # same name, re-plugged
    monkeypatch.setattr(display, "list_displays", lambda: [PRIMARY, moved])
    target = {}
    transfer.merge(target, data)
    assert target["games"]["steam:620"]["display"] == ""


def test_presets_are_not_duplicated_on_a_second_import(two_screens, cfg, tmp_path):
    data = transfer.read_export(transfer.write_export(cfg, tmp_path / "out.json"))
    target = {}
    assert transfer.merge(target, data).presets_added == 1
    assert transfer.merge(target, data).presets_added == 0
    assert len(target["presets"]) == 1


def test_an_imported_preset_gives_way_on_a_shortcut_already_in_use(two_screens, cfg, tmp_path):
    """Two presets on one shortcut means one silently never fires."""
    data = transfer.read_export(transfer.write_export(cfg, tmp_path / "out.json"))
    target = {"presets": [{"name": "Mine", "width": 1920, "height": 1080, "refresh": 60,
                           "hotkey": "Ctrl+Alt+1"}]}
    summary = transfer.merge(target, data)
    assert target["presets"][1]["hotkey"] == ""
    assert "Tall" in summary.hotkeys_dropped


def test_the_restore_hotkey_also_counts_as_taken(two_screens, cfg, tmp_path):
    cfg["presets"][0]["hotkey"] = "Ctrl+Alt+R"
    data = transfer.read_export(transfer.write_export(cfg, tmp_path / "out.json"))
    target = {"restore_hotkey": "Ctrl+Alt+R", "presets": []}
    transfer.merge(target, data)
    assert target["presets"][0]["hotkey"] == ""


def test_sections_can_be_left_out(two_screens, cfg, tmp_path):
    data = transfer.read_export(transfer.write_export(cfg, tmp_path / "out.json"))
    target = {}
    summary = transfer.merge(target, data, presets=False, settings=False)
    assert summary.games_added == 2 and summary.presets_added == 0
    assert not target.get("presets") and "switch_delay" not in target


def test_a_manual_game_is_flagged_because_its_path_came_from_elsewhere(two_screens, cfg, tmp_path):
    data = transfer.read_export(transfer.write_export(cfg, tmp_path / "out.json"))
    summary = transfer.merge({}, data)
    assert summary.manual_games == ["Some Game"]


def test_merge_ignores_entries_of_the_wrong_shape(two_screens):
    data = {"kind": transfer.KIND, "format": 1,
            "games": {"a": "not a dict", "b": {"name": "Fine", "store": "steam", "watch": "not a list"}},
            "presets": ["not a dict"], "settings": {"tray_icon": False, "qres_path": "hostile"}}
    target = {}
    summary = transfer.merge(target, data)
    assert summary.games_added == 1 and "watch" not in target["games"]["b"]
    assert summary.presets_added == 0
    assert "qres_path" not in target and target["tray_icon"] is False


def test_nothing_to_change_says_so(two_screens, cfg, tmp_path):
    data = transfer.read_export(transfer.write_export(cfg, tmp_path / "out.json"))
    target = {}
    transfer.merge(target, data)
    again = transfer.merge(target, data)
    assert not again.changed and "Nothing to change" in again.lines()[0]
