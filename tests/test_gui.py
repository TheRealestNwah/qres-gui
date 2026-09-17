"""The GUI, driven offscreen with fake stores, a fake Steam and a fixed set of display modes."""

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from qres_gui import (__version__, config, display, hdr, notify, paths, playnite, session, shortcuts,
                      transfer, updates)
from qres_gui.gui import main_window, theme
from qres_gui.gui.dialogs import (AddGameDialog, DiagnosticsDialog, PlayniteDialog, SettingsDialog,
                                  TransferDialog)
from qres_gui.stores import Game, steam

MODES = [display.Mode(3440, 1440, 165), display.Mode(3440, 1440, 60), display.Mode(2560, 1440, 165),
         display.Mode(2560, 1440, 60), display.Mode(1920, 1080, 165)]
DESKTOP = MODES[0]

PRIMARY = display.Display(r"\\.\DISPLAY1", "Main Monitor", True)
SECOND = display.Display(r"\\.\DISPLAY2", "Side Monitor", False)
# The second screen deliberately offers a different, smaller set.
SECOND_MODES = [display.Mode(1920, 1080, 60), display.Mode(1280, 720, 60)]
SECOND_DESKTOP = SECOND_MODES[0]


def _modes_for(device=None):
    return list(SECOND_MODES if device == SECOND.device else MODES)


def _mode_of(device=None):
    return SECOND_DESKTOP if device == SECOND.device else DESKTOP


class FakeSteam:
    available = True

    def __init__(self):
        self.options = {"10": "-novid"}
        self.running = False
        self.writes = []

    def is_running(self):
        return self.running

    def launch_options(self):
        return dict(self.options)

    def set_launch_options(self, updates):
        if self.running:
            raise steam.SteamRunningError("Steam is running")
        self.writes.append(dict(updates))
        self.options.update(updates)
        return Path("localconfig.vdf.bak")

    def shutdown(self):
        self.running = False


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    return app


@pytest.fixture
def env(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setattr(display, "list_modes", _modes_for)
    monkeypatch.setattr(display, "current_mode", _mode_of)
    monkeypatch.setattr(display, "find_qres", lambda *a: r"C:\Tools\QRes.exe")
    # Two displays, so the picker has something to pick.
    monkeypatch.setattr(display, "list_displays", lambda: [PRIMARY, SECOND])
    monkeypatch.setattr(display, "primary_device", lambda: PRIMARY.device)
    monkeypatch.setattr(display, "find_display",
                        lambda d: next((x for x in (PRIMARY, SECOND) if x.device == d), None) if d else PRIMARY)
    monkeypatch.setattr(display, "set_mode", lambda *a, **k: "stub")  # never change the real resolution
    # A CI runner's virtual display can't do HDR; pretend one that can.
    monkeypatch.setattr(hdr, "status", lambda device=None: hdr.Status(supported=True, enabled=False))
    monkeypatch.setattr(updates, "check", lambda current=None: None)  # never reach GitHub from tests
    desktop, menu = tmp_path / "Desktop", tmp_path / "Programs" / "QRes GUI"
    desktop.mkdir()
    monkeypatch.setattr(shortcuts, "desktop_dir", lambda: desktop)
    monkeypatch.setattr(shortcuts, "start_menu_dir", lambda: menu)
    monkeypatch.setattr(shortcuts, "create", lambda path, *a, **k: (path.parent.mkdir(parents=True, exist_ok=True),
                                                                     path.write_bytes(b"lnk")))
    monkeypatch.setattr(playnite, "config_path", lambda: None)
    monkeypatch.setattr(playnite, "is_running", lambda: False)
    monkeypatch.setattr(notify, "toast", lambda *a: True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail(f"unexpected warning: {a[2:]}"))

    exe = tmp_path / "Games" / "Stardew" / "Stardew Valley.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    games = [
        Game(id="steam:10", name="Counter Test", store="steam", install_dir=str(tmp_path / "steamgame"),
             launch={"type": "uri", "uri": "steam://rungameid/10"}),
        Game(id="gog:1453375253", name="Stardew Valley", store="gog", install_dir=str(exe.parent), exe=str(exe),
             launch={"type": "exe", "path": str(exe), "args": "", "cwd": str(exe.parent)}),
        Game(id="legendary:Quail", name="Hogwarts Legacy", store="legendary", install_dir=str(tmp_path / "hl")),
        Game(id="playnite:abc", name="PUBG", store="playnite", install_dir=str(tmp_path / "pubg")),
    ]
    monkeypatch.setattr(main_window, "detect_all", lambda client: (list(games), []))
    fake_steam = FakeSteam()
    monkeypatch.setattr(main_window, "SteamClient", lambda: fake_steam)
    cfg = config.load()
    cfg["first_run_done"] = True  # the guide has its own tests; keep it out of the others
    config.save(cfg)
    return {"steam": fake_steam, "desktop": desktop, "tmp": tmp_path}


@pytest.fixture
def win(env):
    window = main_window.MainWindow()
    window.show()
    QApplication.processEvents()
    yield window
    window.close()


def select(win, game_id):
    win.tree.setCurrentItem(win.items[game_id])
    QApplication.processEvents()


def row(win, game_id):
    item = win.items[game_id]
    return [item.text(c) for c in range(4)]


# --- the list ---------------------------------------------------------------------

def test_lists_detected_games(win):
    assert set(win.items) == {"steam:10", "gog:1453375253", "legendary:Quail", "playnite:abc"}
    assert row(win, "gog:1453375253")[:3] == ["Stardew Valley", "GOG", "—"]
    assert row(win, "playnite:abc")[1] == "Playnite"
    assert win.summary.text() == "4 of 4 games shown · 0 switch resolution"
    assert win.windowTitle().startswith("QRes GUI ")


def test_filters(win):
    win.search.setText("stardew")
    assert [g for g, item in win.items.items() if not item.isHidden()] == ["gog:1453375253"]
    win.search.clear()
    win.store_filter.setCurrentIndex(win.store_filter.findData("steam"))
    assert [g for g, item in win.items.items() if not item.isHidden()] == ["steam:10"]
    win.store_filter.setCurrentIndex(0)
    win.only_configured.setChecked(True)
    assert all(item.isHidden() for item in win.items.values())


def test_dropdown_and_spin_box_arrows_are_drawn(qapp):
    """#9: the stylesheet points at chevrons the theme painted, and they exist."""
    import re
    arrows = re.findall(r'url\("([^"]+)"\)', qapp.styleSheet())
    assert any("chevron-down" in a for a in arrows) and any("chevron-up" in a for a in arrows)
    assert all(Path(a).is_file() and Path(a.replace(".png", "@2x.png")).is_file() for a in arrows)


def test_the_store_filter_is_a_pill_lined_up_with_the_search_box(win):
    assert win.store_filter.objectName() == "pill"
    assert win.store_filter.height() == win.search.height() == theme.PILL_HEIGHT


def shown(win):
    return {g for g, item in win.items.items() if not item.isHidden()}


def test_right_click_hides_a_game_and_says_how_to_get_it_back(win):
    """#10. The menu is built and its action triggered, rather than shown (which would block)."""
    [hide] = win.game_menu("legendary:Quail").actions()
    assert hide.text() == "Hide from list"
    hide.trigger()
    assert "legendary:Quail" not in shown(win)
    assert config.load()["hidden_games"] == ["legendary:Quail"]
    assert "1 hidden" in win.summary.text() and "Show" in win.summary.text()
    assert "still switches" in win.statusBar().currentMessage()


def test_hidden_games_come_back_through_the_link_under_the_list(win):
    win.set_hidden("legendary:Quail", True)
    win.summary.linkActivated.emit("hidden")               # "Show"
    assert "legendary:Quail" in shown(win)
    assert row(win, "legendary:Quail")[0].endswith("(hidden)")
    assert "Hide them again" in win.summary.text()
    [show] = win.game_menu("legendary:Quail").actions()    # right-click › Show in list
    assert show.text() == "Show in list"
    show.trigger()
    assert row(win, "legendary:Quail")[0] == "Hogwarts Legacy"
    assert win.summary.text() == "4 of 4 games shown · 0 switch resolution"   # the link goes with the last one


def test_the_hidden_link_only_appears_when_something_is_hidden(win):
    assert "hidden" not in win.summary.text()


def test_hiding_a_game_leaves_its_profile_alone(win):
    """A list filter, not a disable: a hidden game still switches when it's started."""
    win.cfg["games"]["steam:10"] = {"name": "Counter Test", "store": "steam", "enabled": True,
                                    "width": 2560, "height": 1440, "refresh": 0}
    before = dict(win.cfg["games"]["steam:10"])
    win.set_hidden("steam:10", True)
    assert config.load()["games"]["steam:10"] == before


def test_hidden_games_stay_hidden_under_the_other_filters(win):
    win.set_hidden("steam:10", True)
    win.store_filter.setCurrentIndex(win.store_filter.findData("steam"))
    assert shown(win) == set()


# --- the detail panel ---------------------------------------------------------------

def test_enabling_switching_creates_a_profile(win):
    select(win, "steam:10")
    assert config.load()["games"] == {}  # just looking changes nothing
    win.detail.enabled.setChecked(True)
    win._save_now()
    entry = config.load()["games"]["steam:10"]
    assert entry["enabled"] and (entry["width"], entry["height"], entry["refresh"]) == (2560, 1440, 0)
    assert row(win, "steam:10")[2:] == ["2560 × 1440", "Launch options not set"]


def test_resolution_and_refresh_choices(win):
    select(win, "steam:10")
    combo = win.detail.res_combo
    assert [combo.itemData(i) for i in range(combo.count())] == ["3440x1440", "2560x1440", "1920x1080"]
    combo.setCurrentIndex(combo.findData("1920x1080"))
    rates = win.detail.rate_combo
    assert rates.itemText(0) == "Same as desktop (165 Hz)" and rates.itemData(1) == 165
    win.detail.rate_combo.setCurrentIndex(1)
    win.detail.quick.setChecked(True)
    win._save_now()
    entry = config.load()["games"]["steam:10"]
    assert (entry["width"], entry["height"], entry["refresh"], entry["quick_restore"]) == (1920, 1080, 165, True)


def test_hdr_choice_is_saved_and_shown_in_the_list(win):
    select(win, "gog:1453375253")
    combo = win.detail.hdr_combo
    assert combo.isEnabled() and combo.currentData() == ""  # "leave as it is" by default
    win.detail.enabled.setChecked(True)
    combo.setCurrentIndex(combo.findData("on"))
    win._save_now()
    assert config.load()["games"]["gog:1453375253"]["hdr"] is True
    assert row(win, "gog:1453375253")[2] == "2560 × 1440  ·  HDR on"

    combo.setCurrentIndex(combo.findData(""))
    win._save_now()
    assert config.load()["games"]["gog:1453375253"]["hdr"] is None
    assert row(win, "gog:1453375253")[2] == "2560 × 1440"


def test_hdr_is_greyed_out_when_the_display_cant_do_it(win, monkeypatch):
    monkeypatch.setattr(hdr, "status", lambda device=None: hdr.Status(reason=hdr.NO_SUPPORT))
    select(win, "gog:1453375253")
    assert not win.detail.hdr_combo.isEnabled()
    assert win.detail.hdr_hint.text() == hdr.NO_SUPPORT


def test_extra_arguments_for_a_store_game(win):
    select(win, "gog:1453375253")
    assert not win.detail.extra_args.isHidden()
    win.detail.extra_args.setText("  -windowed  ")
    win.detail.extra_args.editingFinished.emit()
    win._save_now()
    assert config.load()["games"]["gog:1453375253"]["extra_args"] == "-windowed"
    assert win.detail.target_label.text().endswith("-windowed")
    # Said in the open, not only in a tooltip: Playnite starting it uses Playnite's own.
    assert "Playnite's own arguments" in win.detail.args_hint.text()


def test_extra_arguments_are_offered_for_steam_games_too(win):
    """#13: Steam games had no field at all."""
    select(win, "steam:10")
    assert not win.detail.args_box.isHidden() and not win.detail.extra_args.isHidden()
    assert "from Playnite through Steam" in win.detail.args_hint.text()
    assert "once QRes's launch options are applied" in win.detail.args_hint.text()   # not hooked yet
    win.detail.steam_apply.click()
    assert "once QRes's launch options" not in win.detail.args_hint.text()


def _make_unity(env):
    folder = env["tmp"] / "steamgame"          # steam:10's install folder in the fake store
    folder.mkdir(exist_ok=True)
    (folder / "UnityPlayer.dll").write_bytes(b"MZ")
    (folder / "Counter Test.exe").write_bytes(b"MZ")
    (folder / "Counter Test_Data").mkdir(exist_ok=True)
    (folder / "Counter Test_Data" / "globalgamemanagers").write_bytes(b"")


def test_a_unity_game_offers_its_engines_options(win, env):
    """#14: toggles from Unity's documented flags, for a game whose folder shows it's Unity."""
    _make_unity(env)
    select(win, "steam:10")
    assert win.detail.engine_note.text() == "Unity options" and not win.detail.engine_note.isHidden()
    assert set(win.detail.engine_combos) == {"window", "api", "monitor", "resolution"}
    monitors = win.detail.engine_combos["monitor"]
    assert [monitors.itemText(i) for i in range(monitors.count())] == ["Game's choice", "Monitor 1", "Monitor 2"]

    window = win.detail.engine_combos["window"]
    window.setCurrentIndex(window.findData("borderless"))
    win._save_now()
    assert config.load()["games"]["steam:10"]["engine_args"] == {"engine": "unity", "window": "borderless"}
    assert "Adds: -screen-fullscreen 1 -window-mode borderless" in win.detail.engine_adds.text()

    window.setCurrentIndex(0)                      # back to "Game's choice"
    win._save_now()
    assert "engine_args" not in config.load()["games"]["steam:10"]


def test_a_unity_game_can_start_at_its_profiles_resolution(win, env):
    """Tells the game its size, and follows the profile when that changes."""
    _make_unity(env)
    select(win, "steam:10")
    win.detail.enabled.setChecked(True)                 # a profile at the default 2560 × 1440
    resolution = win.detail.engine_combos["resolution"]
    assert resolution.itemText(1) == "Start at this game's resolution (2560 × 1440)"
    resolution.setCurrentIndex(1)
    assert "Adds: -screen-width 2560 -screen-height 1440" in win.detail.engine_adds.text()

    win.detail.res_combo.setCurrentIndex(win.detail.res_combo.findData("1920x1080"))
    assert win.detail.engine_combos["resolution"].itemText(1).endswith("(1920 × 1080)")
    assert "-screen-width 1920 -screen-height 1080" in win.detail.engine_adds.text()


def test_no_engine_options_for_a_game_whose_engine_isnt_known(win):
    select(win, "steam:10")                        # its folder doesn't exist in the fake store
    assert win.detail.engine_note.isHidden() and not win.detail.engine_combos


def test_a_games_commands_are_saved_and_cleared(win):
    select(win, "steam:10")
    win.detail.before_cmd.setText("  taskkill /im Discord.exe  ")
    win.detail.before_cmd.editingFinished.emit()
    win._save_now()
    assert config.load()["games"]["steam:10"]["commands"] == {"before": "taskkill /im Discord.exe"}
    win.detail.before_cmd.setText("")
    win.detail.before_cmd.editingFinished.emit()
    win._save_now()
    assert "commands" not in config.load()["games"]["steam:10"]


def test_commands_for_every_game_live_on_the_switching_tab(win):
    dialog = SettingsDialog(win, win.cfg, win.modes)
    assert _tab_of(dialog, dialog.before_cmd) == "Switching"
    dialog.after_cmd.setText(" echo done ")
    dialog.apply_to(win.cfg)
    assert win.cfg["commands"] == {"before": "", "after": "echo done"}


def test_extra_arguments_say_where_to_set_them_when_qres_cant(win):
    select(win, "playnite:abc")  # Playnite starts it, so QRes never builds the command line
    assert win.detail.extra_args.isHidden() and not win.detail.args_box.isHidden()
    assert "set its arguments in Playnite" in win.detail.args_hint.text()


def test_apply_to_steam_keeps_the_users_options(win, env):
    select(win, "steam:10")
    win.detail.steam_apply.click()
    [update] = env["steam"].writes
    options = update["10"]
    assert options.startswith(steam.launch_prefix(paths.launcher_command(), "steam:10"))
    assert options.endswith("%command% -novid")
    assert config.load()["games"]["steam:10"]["enabled"]  # applying turns switching on
    assert row(win, "steam:10")[3] == "Steam launch options"
    assert not win.detail.steam_apply.isEnabled()

    win.detail.steam_remove.click()
    assert env["steam"].options["10"] == "-novid"


def test_steam_running_blocks_writing(env, qapp):
    env["steam"].running = True
    window = main_window.MainWindow()
    window.show()
    try:
        select(window, "steam:10")
        window.detail.enabled.setChecked(True)
        assert not window.detail.steam_apply.isEnabled()
        assert not window.detail.steam_close.isHidden()
        assert not window.sync_btn.isEnabled() and "(1)" in window.sync_btn.text()
    finally:
        window.close()


def test_desktop_shortcut_for_a_gog_game(win, env):
    select(win, "gog:1453375253")
    assert not win.detail.desktop_btn.isHidden()
    win.detail.desktop_btn.click()
    assert (env["desktop"] / "Stardew Valley (QRes).lnk").exists()
    assert row(win, "gog:1453375253")[2:] == ["2560 × 1440", "Shortcut: Desktop"]
    win.detail.remove_shortcuts_btn.click()
    assert not (env["desktop"] / "Stardew Valley (QRes).lnk").exists()


def test_legendary_game_can_only_start_from_playnite(win):
    select(win, "legendary:Quail")
    win.detail.enabled.setChecked(True)
    assert win.detail.desktop_btn.isHidden() and win.detail.play_btn.isHidden()
    assert "Playnite integration" in win.detail.shortcut_status.text()
    assert row(win, "legendary:Quail")[3] == "Needs Playnite setup"


def test_playnite_game_plays_through_playnite(win, monkeypatch):
    opened = []
    monkeypatch.setattr(os, "startfile", lambda target: opened.append(target))
    select(win, "playnite:abc")
    assert not win.detail.play_btn.isHidden() and win.detail.play_btn.text() == "Play in Playnite"
    assert not win.detail.remove_btn.isHidden()
    win.detail.play_btn.click()
    assert opened == ["playnite://playnite/start/abc"]


def test_removing_a_playnite_game_forgets_it(win, monkeypatch):
    forgotten = []
    monkeypatch.setattr(playnite, "forget", lambda game_id: forgotten.append(game_id))
    select(win, "playnite:abc")
    win.detail.enabled.setChecked(True)
    win.remove_manual_game(win.games["playnite:abc"])
    assert forgotten == ["abc"] and "playnite:abc" not in config.load()["games"]


def test_display_defaults_to_primary_and_lists_the_others(win):
    select(win, "steam:10")
    combo = win.detail.display_combo
    assert combo.currentData() == ""  # "" means whichever display is primary
    assert [combo.itemData(i) for i in range(combo.count())] == ["", PRIMARY.device, SECOND.device]
    assert combo.itemText(1) == "Display 1: Main Monitor  (primary)"
    assert win.detail.primary_hint.text() == "QRes switches the primary display."


def test_choosing_a_second_display_saves_it_and_relists_its_modes(win):
    select(win, "gog:1453375253")
    win.detail.enabled.setChecked(True)
    combo = win.detail.display_combo
    combo.setCurrentIndex(combo.findData(SECOND.device))
    win._save_now()
    entry = config.load()["games"]["gog:1453375253"]
    assert entry["display"] == SECOND.device
    # 2560 × 1440 isn't on that screen, so the profile snaps to what it runs at.
    assert (entry["width"], entry["height"]) == (1920, 1080)
    res = win.detail.res_combo
    assert [res.itemData(i) for i in range(res.count())] == ["1920x1080", "1280x720"]
    assert "Windows API" in win.detail.primary_hint.text()
    assert row(win, "gog:1453375253")[2] == "1920 × 1080  ·  Display 2"


def test_a_display_that_is_unplugged_is_still_shown_and_flagged(win, monkeypatch):
    cfg = config.load()
    cfg["games"]["gog:1453375253"] = {**win.default_entry(win.games["gog:1453375253"]),
                                      "enabled": True, "display": r"\\.\DISPLAY9"}
    config.save(cfg)
    win.cfg = config.load()
    select(win, "gog:1453375253")
    combo = win.detail.display_combo
    assert combo.currentData() == r"\\.\DISPLAY9"
    assert combo.currentText().endswith("(not connected)")
    assert "isn't connected" in win.detail.primary_hint.text()


# --- banner, dialogs, hooks -----------------------------------------------------------

def test_problem_banner_shows_and_dismisses(win):
    assert win.event_bar.isHidden()
    notify.record("Couldn't switch to 2560 × 1440", "Counter Test is starting at your current resolution.")
    win._refresh_events()
    assert not win.event_bar.isHidden() and "switch to 2560 × 1440" in win.event_label.text()
    win._dismiss_events()
    assert win.event_bar.isHidden() and config.load()["events_seen"] > 0


def test_update_banner(win, monkeypatch):
    assert win.update_bar.isHidden()
    monkeypatch.setattr(updates, "check", lambda current=None: {"version": "99.0.0", "url": "https://x/v99", "name": ""})
    release, error = win.check_for_updates(wait=True)
    assert release["version"] == "99.0.0" and not error
    assert not win.update_bar.isHidden() and "99.0.0 is available" in win.update_label.text()
    assert config.load()["update_available"] == {"version": "99.0.0", "url": "https://x/v99"}

    win._dismiss_update()  # "Later"
    assert win.update_bar.isHidden()
    win._show_update_bar()
    assert win.update_bar.isHidden()  # stays hidden for that version...

    win._on_update_result({"version": "99.1.0", "url": "u"}, "")
    assert not win.update_bar.isHidden()  # ...but not for the next one


def test_update_check_failures_stay_quiet(win, monkeypatch):
    def offline(current=None):
        raise OSError("no network")
    monkeypatch.setattr(updates, "check", offline)
    before = config.load().get("update_last_check", 0)
    assert win.check_for_updates(wait=True) == (None, "no network")
    assert win.update_bar.isHidden() and config.load().get("update_last_check", 0) == before  # retried later


def test_update_banner_clears_once_updated(win):
    win.cfg["update_available"] = {"version": __version__, "url": "u"}
    win._show_update_bar()
    assert win.update_bar.isHidden()


def test_automatic_check_respects_the_setting_and_the_daily_limit(win, monkeypatch):
    calls = []
    monkeypatch.setattr(win, "check_for_updates", lambda wait=False: calls.append(wait) or (None, ""))
    win.cfg["check_updates"] = False
    win._auto_check_updates()
    win.cfg.update(check_updates=True, update_last_check=__import__("time").time())
    win._auto_check_updates()
    assert calls == []
    win.cfg["update_last_check"] = 0
    win._auto_check_updates()
    assert calls == [False]


# --- Getting started guide -------------------------------------------------------------

def test_guide_is_for_new_installs_only(win):
    win.cfg["first_run_done"] = False
    assert win._needs_guide()
    win.cfg["games"]["steam:10"] = {"enabled": True, "width": 2560, "height": 1440}
    assert not win._needs_guide() and config.load()["first_run_done"] is True  # already set up


def test_guide_pages(win, env):
    from qres_gui.gui.guide import GettingStarted
    guide = GettingStarted(win)
    assert guide.step.text().startswith("Step 1 of 5") and not guide.back_btn.isEnabled()
    guide.next_btn.click()
    assert "QRes" in guide.step.text()
    assert "Found QRes" not in guide.qres_status.text()  # the fake path doesn't exist
    real = env["tmp"] / "QRes.exe"
    real.write_bytes(b"MZ")
    guide.qres_path.setText(str(real))
    assert "Found QRes" in guide.qres_status.text()
    for _ in range(3):
        guide.next_btn.click()
    assert guide.next_btn.text() == "Finish" and guide.step.text().startswith("Step 5 of 5")
    guide.search.setText("stardew")
    visible = [guide.game_list.item(i).text() for i in range(guide.game_list.count())
               if not guide.game_list.item(i).isHidden()]
    assert visible == ["Stardew Valley    ·    GOG"]


def test_guide_covers_displays_and_hdr_for_this_pc(win):
    """The guide walks new users past both, so it has to mention them - and it
    shouldn't promise a second screen or an HDR toggle that isn't there."""
    from qres_gui.gui.guide import GettingStarted
    guide = GettingStarted(win)
    text = guide._extras()
    assert "2 displays" in text                      # env fakes a primary + a second screen
    assert "HDR on or off" in text                   # env fakes HDR as available
    assert "Display box" in text


def test_guide_says_why_hdr_is_unavailable_rather_than_promising_it(win, monkeypatch):
    from qres_gui.gui.guide import GettingStarted
    monkeypatch.setattr(hdr, "status", lambda device=None: hdr.Status(reason=hdr.NO_SUPPORT))
    text = GettingStarted(win)._extras()
    assert "isn't available on this PC" in text and "doesn't report HDR support" in text
    assert "HDR on or off" not in text


def test_guide_copes_with_an_hdr_status_that_gives_no_reason(win, monkeypatch):
    """Status() defaults to an empty reason; formatting it must not blow up."""
    from qres_gui.gui.guide import GettingStarted
    monkeypatch.setattr(hdr, "status", lambda device=None: hdr.Status())
    assert "isn't available on this PC" in GettingStarted(win)._extras()


def test_finishing_the_guide_sets_up_the_chosen_game(win, env, monkeypatch):
    from qres_gui.gui.guide import GettingStarted

    def run(guide):
        guide.target.setCurrentIndex(guide.target.findData("1920x1080"))
        for i in range(guide.game_list.count()):
            if "Stardew" in guide.game_list.item(i).text():
                guide.game_list.setCurrentRow(i)
        return 1

    monkeypatch.setattr(GettingStarted, "exec", run)
    win.cfg["first_run_done"] = False
    win.open_guide()
    saved = config.load()
    assert saved["first_run_done"] and saved["default_target"] == {"width": 1920, "height": 1080, "refresh": 0}
    entry = saved["games"]["gog:1453375253"]
    assert entry["enabled"] and (entry["width"], entry["height"]) == (1920, 1080)
    assert win.detail.game.id == "gog:1453375253"  # opened, ready for the shortcut step


def test_skipping_the_guide_changes_nothing_but_the_flag(win, monkeypatch):
    from qres_gui.gui.guide import GettingStarted
    monkeypatch.setattr(GettingStarted, "exec", lambda self: 0)
    before = config.load()
    win.cfg["first_run_done"] = False
    win.open_guide()
    after = config.load()
    assert after["first_run_done"] and after["default_target"] == before["default_target"]
    assert not any(e.get("enabled") for e in after["games"].values())


def test_guide_adds_qres_to_playnite(win, env, monkeypatch):
    from qres_gui.gui.guide import GettingStarted
    cfg_path = env["tmp"] / "Playnite" / "config.json"
    cfg_path.parent.mkdir()
    cfg_path.write_text(json.dumps({"PreScript": "", "PostScript": ""}), encoding="utf-8")
    monkeypatch.setattr(playnite, "config_path", lambda: cfg_path)
    guide = GettingStarted(win)
    guide._go(3)
    assert not guide.playnite_btn.isHidden()
    guide.playnite_btn.click()
    assert playnite.state(paths.launcher_command()) == "installed"
    assert guide.playnite_btn.isHidden() and "already in Playnite" in guide.playnite_status.text()


# --- restoring the desktop ------------------------------------------------------------

def test_leftover_session_is_judged_against_the_display_it_names(win, monkeypatch):
    """Comparing the primary instead would clear the record on a chance match and
    strand the other screen with nothing left to restore from."""
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No)
    # The record is for the second screen, sitting at the primary's mode by
    # coincidence - the exact case that used to silently drop it.
    session.write(DESKTOP.to_dict(), "gog:1453375253", device=SECOND.device)
    stale = {**session.read(), "create_time": 0.0}
    paths.session_path().write_text(json.dumps(stale), encoding="utf-8")

    win._check_leftover_session()
    assert asked and "Display 2" in asked[0]     # it noticed, and named the right screen
    assert session.read() is None                # cleared only because we answered No


def test_restore_desktop_puts_back_the_recorded_display_and_hdr(win, monkeypatch):
    """The button the launcher's failure notifications point people at has to undo
    everything a switch did - the screen it names, and HDR - not just the resolution."""
    switched, hdr_calls = [], []
    monkeypatch.setattr(display, "set_mode",
                        lambda mode, qres, temporary=True, device=None:
                            switched.append((mode, device)) or "stub")
    monkeypatch.setattr(hdr, "set_enabled",
                        lambda on, device=None: hdr_calls.append((on, device)) or True)
    desktop = display.Mode(1920, 1080, 60)
    session.write(desktop.to_dict(), "gog:1453375253", device=SECOND.device, original_hdr=False)
    stale = {**session.read(), "create_time": 0.0}  # the launcher that made it is gone
    paths.session_path().write_text(json.dumps(stale), encoding="utf-8")

    win.restore_desktop()
    assert switched == [(desktop, SECOND.device)]   # that screen, not the primary
    assert hdr_calls == [(False, SECOND.device)]    # and HDR back, on the same screen
    assert session.read() is None


def test_restore_desktop_leaves_hdr_alone_when_the_record_says_nothing(win, monkeypatch):
    switched, hdr_calls = [], []
    monkeypatch.setattr(display, "set_mode",
                        lambda mode, qres, temporary=True, device=None:
                            switched.append((mode, device)) or "stub")
    monkeypatch.setattr(hdr, "set_enabled",
                        lambda on, device=None: hdr_calls.append((on, device)) or True)
    session.write(DESKTOP.to_dict(), "steam:10")
    stale = {**session.read(), "create_time": 0.0}
    paths.session_path().write_text(json.dumps(stale), encoding="utf-8")

    win.restore_desktop()
    assert switched == [(DESKTOP, None)]
    assert hdr_calls == []


def test_restore_desktop_still_restores_the_resolution_if_hdr_fails(win, monkeypatch):
    switched = []
    monkeypatch.setattr(display, "set_mode",
                        lambda mode, qres, temporary=True, device=None:
                            switched.append(mode) or "stub")
    def broken(on, device=None):
        raise hdr.HdrError("the display said no")
    monkeypatch.setattr(hdr, "set_enabled", broken)
    session.write(DESKTOP.to_dict(), "steam:10", original_hdr=True)
    stale = {**session.read(), "create_time": 0.0}
    paths.session_path().write_text(json.dumps(stale), encoding="utf-8")

    win.restore_desktop()
    assert switched == [DESKTOP]                     # the resolution came back regardless
    assert "HDR couldn't be put back" in win.statusBar().currentMessage()


# --- quick switch / presets -----------------------------------------------------------

def test_preset_chips_appear_and_apply(win, monkeypatch):
    assert not win._no_presets.isHidden() and len(win._preset_chips) == 0
    win.cfg["presets"] = [{"name": "1440p", "width": 2560, "height": 1440, "refresh": 0},
                          {"name": "", "width": 1920, "height": 1080, "refresh": 120}]
    win._refresh_presets()
    assert win._no_presets.isHidden()
    labels = [chip.text() for chip, _ in win._preset_chips]
    assert labels == ["1440p", "1920 × 1080 @ 120 Hz"]

    applied = []
    monkeypatch.setattr(main_window, "ApplyResolutionDialog",
                        lambda *a, **k: type("D", (), {"exec": lambda self: applied.append(a[1]) or 0})())
    win._preset_chips[0][0].click()
    assert applied == [display.Mode(2560, 1440, 165)]  # refresh 0 resolved to the desktop's 165


def test_a_preset_can_name_a_display_and_applies_to_it(win, monkeypatch):
    """A hotkey fires with no UI context, so the screen has to come from the preset."""
    win.cfg["presets"] = [{"name": "Side 720p", "width": 1280, "height": 720, "refresh": 0,
                           "display": SECOND.device}]
    win._refresh_presets()
    [(chip, preset)] = win._preset_chips
    assert "Display 2" in chip.toolTip()

    applied = []
    monkeypatch.setattr(main_window, "ApplyResolutionDialog",
                        lambda *a, **k: type("D", (), {"exec": lambda self: applied.append((a[1], k.get("device"))) or 0})())
    chip.click()
    # resolved against that screen's 60 Hz, and aimed at it
    assert applied == [(display.Mode(1280, 720, 60), SECOND.device)]


def test_a_preset_on_an_unplugged_display_switches_nothing(win, monkeypatch):
    win.cfg["presets"] = [{"name": "Gone", "width": 1280, "height": 720, "refresh": 0,
                           "display": r"\\.\DISPLAY9"}]
    win._refresh_presets()
    monkeypatch.setattr(main_window, "ApplyResolutionDialog",
                        lambda *a, **k: pytest.fail("applied to a display that isn't there"))
    win._preset_chips[0][0].click()
    assert "isn't connected" in win.statusBar().currentMessage()


def test_preset_chips_highlight_against_their_own_screen(win):
    """The side preset matches that screen's mode; the primary one doesn't match it."""
    win.cfg["presets"] = [{"name": "Side", "width": SECOND_DESKTOP.width, "height": SECOND_DESKTOP.height,
                           "refresh": 0, "display": SECOND.device},
                          {"name": "Same size, primary", "width": SECOND_DESKTOP.width,
                           "height": SECOND_DESKTOP.height, "refresh": 0, "display": ""}]
    win._refresh_presets()
    names = [chip.objectName() for chip, _ in win._preset_chips]
    assert names == ["presetActive", "preset"]


def test_preset_editor_offers_the_displays_and_saves_the_choice(win):
    from qres_gui.gui.presets import PresetEditor
    editor = PresetEditor(win, win.modes, displays=win.displays)
    combo = editor.screen
    assert [combo.itemData(i) for i in range(combo.count())] == ["", PRIMARY.device, SECOND.device]
    combo.setCurrentIndex(combo.findData(SECOND.device))
    # 3440 × 1440 isn't on that screen, so it snaps to what that screen runs
    assert (editor.width.value(), editor.height.value()) == (SECOND_DESKTOP.width, SECOND_DESKTOP.height)
    assert editor.preset()["display"] == SECOND.device


def test_presets_dialog_add_edit_remove_persist(win, monkeypatch):
    from qres_gui.gui.presets import PresetEditor, PresetsDialog
    dialog = PresetsDialog(win)
    monkeypatch.setattr(PresetEditor, "exec", lambda self: 1)
    monkeypatch.setattr(PresetEditor, "preset",
                        lambda self: {"name": "Tall", "width": 2560, "height": 1080, "refresh": 60})
    dialog._add()
    assert config.load()["presets"] == [{"name": "Tall", "width": 2560, "height": 1080, "refresh": 60}]
    assert dialog.list.count() == 1

    dialog._add_current()  # adds 3440x1440 (the fake desktop)
    assert dialog.list.count() == 2 and config.load()["presets"][1]["width"] == 3440
    dialog.list.setCurrentRow(1)
    dialog._move(-1)
    assert [p["width"] for p in config.load()["presets"]] == [3440, 2560]
    dialog._remove()
    assert [p["width"] for p in config.load()["presets"]] == [2560]


def test_preset_editor_warns_about_custom_resolutions(win):
    from qres_gui.gui.presets import PresetEditor
    editor = PresetEditor(win, win.modes)
    editor.width.setValue(2560)
    editor.height.setValue(1440)
    assert "offers this resolution" in editor.status.text()
    editor.width.setValue(5120)  # not in the fake mode list
    editor.height.setValue(2160)
    assert "custom resolution" in editor.status.text()


def test_apply_resolution_dialog_reverts_when_not_kept(win, monkeypatch):
    from qres_gui.gui import presets
    calls = []
    monkeypatch.setattr(display, "set_mode", lambda mode, *a, **k: calls.append(mode) or "stub")
    monkeypatch.setattr(display, "current_mode", lambda device=None: display.Mode(3440, 1440, 165))
    dialog = presets.ApplyResolutionDialog(win, display.Mode(2560, 1440, 165), None, True)
    dialog._switch()
    assert calls == [display.Mode(2560, 1440, 165)] and dialog.switched
    dialog.done(0)  # closed without keeping
    assert calls[-1] == display.Mode(3440, 1440, 165)  # reverted

    calls.clear()
    dialog2 = presets.ApplyResolutionDialog(win, display.Mode(2560, 1440, 165), None, True)
    dialog2._switch()
    dialog2._keep()  # accept + keep
    dialog2.done(dialog2.result())
    assert calls == [display.Mode(2560, 1440, 165)]  # switched, not reverted


def test_hotkeys_dispatch_to_presets_and_restore(win, monkeypatch):
    win.cfg["presets"] = [{"name": "A", "width": 2560, "height": 1440, "refresh": 0}]
    applied, restored = [], []
    monkeypatch.setattr(win, "apply_preset", lambda p: applied.append(p))
    monkeypatch.setattr(win, "restore_desktop", lambda: restored.append(True))
    win._on_hotkey(win.HK_PRESET_BASE + 0)
    win._on_hotkey(win.HK_RESTORE)
    win._on_hotkey(win.HK_PRESET_BASE + 5)  # out of range: ignored
    assert applied == [{"name": "A", "width": 2560, "height": 1440, "refresh": 0}] and restored == [True]


def test_apply_hotkeys_reads_config(win, monkeypatch):
    registered = {}
    monkeypatch.setattr(win.hotkeys, "apply", lambda bindings: registered.update(bindings) or {})
    win.cfg["restore_hotkey"] = "Ctrl+Alt+Home"
    win.cfg["presets"] = [{"name": "A", "width": 2560, "height": 1440, "refresh": 0, "hotkey": "Ctrl+Alt+1"},
                          {"name": "B", "width": 1920, "height": 1080, "refresh": 0, "hotkey": ""}]
    win.apply_hotkeys()
    assert registered == {win.HK_RESTORE: "Ctrl+Alt+Home", win.HK_PRESET_BASE: "Ctrl+Alt+1"}


def test_close_to_tray_hides_when_background_on(win, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    win.tray = type("T", (), {"showMessage": lambda *a, **k: None, "icon": lambda self: None,
                              "hide": lambda self: None})()
    win.cfg["background"] = True
    win._told_tray = True
    event = QCloseEvent()
    win.closeEvent(event)
    assert not event.isAccepted()  # ignored -> window hidden, app keeps running


def test_settings_saves_tray_and_hotkey(win):
    dialog = SettingsDialog(win, win.cfg, win.modes)
    dialog.background.setChecked(True)
    dialog.tray_icon.setChecked(False)
    from PySide6.QtGui import QKeySequence
    dialog.restore_hotkey.setKeySequence(QKeySequence("Ctrl+Alt+Home"))
    dialog.apply_to(win.cfg)
    assert win.cfg["background"] is True and win.cfg["tray_icon"] is False
    assert win.cfg["restore_hotkey"] == "Ctrl+Alt+Home"


def test_settings_opens_the_guide(win):
    opened = []
    dialog = SettingsDialog(win, win.cfg, win.modes, on_guide=lambda: opened.append(True))
    [button] = [b for b in dialog.findChildren(main_window.QPushButton) if b.text() == "Getting started…"]
    button.click()
    assert opened == [True] and dialog.result() == 0  # Settings closed without applying


def test_settings_opens_diagnostics(win):
    opened = []
    dialog = SettingsDialog(win, win.cfg, win.modes, on_diagnostics=lambda: opened.append(True))
    [button] = [b for b in dialog.findChildren(main_window.QPushButton) if b.text() == "Diagnostics…"]
    button.click()
    assert opened == [True]


def test_diagnostics_dialog_shows_both_screens_and_copies(win):
    from PySide6.QtWidgets import QApplication
    dialog = DiagnosticsDialog(win, win.cfg)
    titles = [s.title for s in dialog.sections]
    assert "Displays" in titles and "HDR" in titles

    screens = [row.label for s in dialog.sections if s.title == "Displays" for row in s.rows]
    assert screens == [PRIMARY.label, SECOND.label]

    [copy] = [b for b in dialog.findChildren(main_window.QPushButton)
              if b.text() == "Copy for a bug report"]
    copy.click()
    assert QApplication.clipboard().text() == dialog.text
    assert __version__ in dialog.text and copy.text() == "Copied"


def test_diagnostics_never_checks_for_updates(win, monkeypatch):
    """Opening the panel must not touch the network; the last result comes from the config."""
    monkeypatch.setattr(updates, "fetch_releases",
                        lambda *a, **k: pytest.fail("diagnostics went to the network"))
    win.cfg["update_last_check"] = 1_700_000_000
    win.cfg["update_available"] = {"version": "9.9.9", "url": "https://example.invalid"}
    dialog = DiagnosticsDialog(win, win.cfg)
    [section] = [s for s in dialog.sections if s.title == "Updates"]
    assert "9.9.9" in " ".join(row.value for row in section.rows)


def test_settings_opens_the_transfer_dialog(win):
    opened = []
    dialog = SettingsDialog(win, win.cfg, win.modes, on_transfer=lambda: opened.append(True))
    [button] = [b for b in dialog.findChildren(main_window.QPushButton)
                if b.text() == "Back up and restore…"]
    button.click()
    assert opened == [True] and dialog.result() == 0  # Settings closed without applying


def test_transfer_round_trip_through_the_dialog(win, monkeypatch, tmp_path):
    """Export then import into a config that has lost its profiles."""
    win.cfg["games"]["steam:10"] = {"name": "Portal 2", "store": "steam", "enabled": True,
                                    "width": 2560, "height": 1440, "refresh": 0}
    out = tmp_path / "profiles.json"

    dialog = TransferDialog(win, win.cfg)
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr("qres_gui.gui.dialogs.QFileDialog.getSaveFileName",
                        lambda *a, **k: (str(out), ""))
    dialog._export()
    assert out.exists() and not dialog.imported

    win.cfg["games"].pop("steam:10")
    monkeypatch.setattr("qres_gui.gui.dialogs.QFileDialog.getOpenFileName",
                        lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(main_window.QMessageBox, "question",
                        lambda *a, **k: main_window.QMessageBox.StandardButton.Yes)
    dialog._import()
    assert dialog.imported and win.cfg["games"]["steam:10"]["width"] == 2560


def test_transfer_import_declined_changes_nothing(win, monkeypatch, tmp_path):
    win.cfg["games"]["steam:10"] = {"name": "Portal 2", "store": "steam", "enabled": True,
                                    "width": 2560, "height": 1440, "refresh": 0}
    out = tmp_path / "profiles.json"
    transfer.write_export(win.cfg, out)
    win.cfg["games"]["steam:10"]["width"] = 1920

    dialog = TransferDialog(win, win.cfg)
    monkeypatch.setattr("qres_gui.gui.dialogs.QFileDialog.getOpenFileName",
                        lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(main_window.QMessageBox, "question",
                        lambda *a, **k: main_window.QMessageBox.StandardButton.No)
    dialog._import()
    assert not dialog.imported and win.cfg["games"]["steam:10"]["width"] == 1920


def test_transfer_reports_a_bad_file_without_touching_the_config(win, monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    before = dict(win.cfg["games"])
    said = []
    dialog = TransferDialog(win, win.cfg)
    monkeypatch.setattr("qres_gui.gui.dialogs.QFileDialog.getOpenFileName",
                        lambda *a, **k: (str(bad), ""))
    monkeypatch.setattr(main_window.QMessageBox, "warning",
                        lambda parent, title, text, *a, **k: said.append(text))
    dialog._import()
    assert not dialog.imported and win.cfg["games"] == before
    assert said and "isn't a QRes GUI profile export" in said[0]


@pytest.fixture
def installed(env):
    """An installed QRes GUI (in the test's own LOCALAPPDATA), while the GUI runs from somewhere else."""
    folder = paths.installed_folder()
    folder.mkdir(parents=True)
    launcher = folder / "QResLauncher.exe"
    launcher.write_bytes(b"MZ")
    return launcher


def test_another_copy_sees_hooks_to_the_installed_copy_as_fine(installed, env):
    """#12: an unzipped or test copy used to call these "outdated" and offer to repoint them at itself."""
    env["steam"].options["10"] = steam.apply_ours("-novid", steam.launch_prefix([str(installed)], "steam:10"))
    cfg = config.load()
    cfg["games"]["steam:10"] = {"name": "Counter Test", "store": "steam", "enabled": True,
                                "width": 2560, "height": 1440, "refresh": 0}
    config.save(cfg)
    window = main_window.MainWindow()
    try:
        assert row(window, "steam:10")[3] == "Steam launch options"
        assert window.pending_steam_updates() == {}
        assert window.steam_prefix("steam:10").startswith(f'"{installed}"')
    finally:
        window.close()


def test_a_hook_to_a_deleted_copy_is_called_broken_and_fixed_to_the_installed_one(installed, env, tmp_path):
    gone = tmp_path / "Desktop" / "qRes UI" / "1.4.0" / "QResLauncher.exe"      # deleted after testing
    env["steam"].options["10"] = steam.apply_ours("", steam.launch_prefix([str(gone)], "steam:10"))
    cfg = config.load()
    cfg["games"]["steam:10"] = {"name": "Counter Test", "store": "steam", "enabled": True,
                                "width": 2560, "height": 1440, "refresh": 0}
    config.save(cfg)
    window = main_window.MainWindow()
    try:
        assert row(window, "steam:10")[3] == "Launch options broken — update them"
        select(window, "steam:10")
        assert "isn't there any more" in window.detail.steam_status.text()
        assert steam.hooked_launcher(window.pending_steam_updates()["10"]) == str(installed)
    finally:
        window.close()


def test_settings_says_when_this_copy_isnt_the_one_games_launch_through(installed, win):
    dialog = SettingsDialog(win, win.cfg, win.modes)
    hints = [label.text() for label in dialog.findChildren(main_window.QLabel)]
    assert any("isn't the installed QRes GUI" in text for text in hints)


def test_settings_warns_a_portable_copy_not_to_move_its_folder(win):
    dialog = SettingsDialog(win, win.cfg, win.modes)
    hints = [label.text() for label in dialog.findChildren(main_window.QLabel)]
    assert any("Don't move or delete it" in text for text in hints)


def _import_through_dialog(win, monkeypatch, path, merge=False):
    dialog = TransferDialog(win, win.cfg)
    monkeypatch.setattr("qres_gui.gui.dialogs.QFileDialog.getOpenFileName", lambda *a, **k: (str(path), ""))
    if merge:
        dialog.merge_mode.setChecked(True)
    dialog._import()
    return dialog


def test_transfer_restores_by_default_and_removes_what_came_since(win, monkeypatch, tmp_path):
    win.cfg["games"]["steam:10"] = {"name": "Counter Test", "store": "steam", "enabled": True,
                                    "width": 2560, "height": 1440, "refresh": 0}
    out = transfer.write_export(win.cfg, tmp_path / "profiles.json")
    win.cfg["games"]["gog:1453375253"] = {"name": "Stardew Valley", "store": "gog", "enabled": True,
                                          "width": 1920, "height": 1080, "refresh": 0}
    dialog = _import_through_dialog(win, monkeypatch, out)
    assert dialog.restore_mode.isChecked() and dialog.imported
    assert "gog:1453375253" not in win.cfg["games"] and "steam:10" in win.cfg["games"]
    assert dialog.summary.games_removed == ["Stardew Valley"]


def test_transfer_merge_keeps_what_came_since(win, monkeypatch, tmp_path):
    win.cfg["games"]["steam:10"] = {"name": "Counter Test", "store": "steam", "enabled": True,
                                    "width": 2560, "height": 1440, "refresh": 0}
    out = transfer.write_export(win.cfg, tmp_path / "profiles.json")
    win.cfg["games"]["steam:10"]["width"] = 1920
    win.cfg["games"]["gog:1453375253"] = {"name": "Stardew Valley", "store": "gog", "enabled": True,
                                          "width": 1920, "height": 1080, "refresh": 0}
    _import_through_dialog(win, monkeypatch, out, merge=True)
    assert win.cfg["games"]["steam:10"]["width"] == 2560 and "gog:1453375253" in win.cfg["games"]


def test_the_game_panel_shows_what_an_import_restored(win, monkeypatch, tmp_path):
    """QA found the panel kept showing the old refresh rate until another game was clicked."""
    win.cfg["games"]["steam:10"] = {"name": "Counter Test", "store": "steam", "enabled": True,
                                    "width": 2560, "height": 1440, "refresh": 0}
    out = transfer.write_export(win.cfg, tmp_path / "profiles.json")
    select(win, "steam:10")
    win.detail.rate_combo.setCurrentIndex(win.detail.rate_combo.findData(60))
    assert win.cfg["games"]["steam:10"]["refresh"] == 60

    monkeypatch.setattr("qres_gui.gui.dialogs.QFileDialog.getOpenFileName", lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(TransferDialog, "exec", lambda self: self._import())
    win.open_transfer()
    assert win.cfg["games"]["steam:10"]["refresh"] == 0
    assert int(win.detail.rate_combo.currentData() or 0) == 0


def test_settings_scroll_and_never_open_taller_than_the_screen(win):
    """On 1080p the form is taller than the screen; OK and Cancel must stay reachable."""
    dialog = SettingsDialog(win, win.cfg, win.modes, on_playnite=lambda: None, on_remove_hooks=lambda: None,
                            on_check_updates=lambda: (None, None), on_guide=lambda: None,
                            on_diagnostics=lambda: None, on_transfer=lambda: None)
    first = dialog.tabs.widget(0)
    assert first.widget().isAncestorOf(dialog.qres)                  # each tab scrolls on its own
    ok = next(b for b in dialog.findChildren(main_window.QPushButton) if b.text() == "OK")
    assert not dialog.tabs.isAncestorOf(ok)                           # OK and Cancel stay put below
    assert dialog.height() <= dialog.screen().availableGeometry().height()


def _tab_of(dialog, widget):
    return next(dialog.tabs.tabText(i).replace("&&", "&") for i in range(dialog.tabs.count())
                if dialog.tabs.widget(i).widget().isAncestorOf(widget))


def test_settings_are_grouped_into_tabs(win):
    """#11: one flat form of sixteen rows became six short tabs."""
    dialog = SettingsDialog(win, win.cfg, win.modes, on_playnite=lambda: None, on_remove_hooks=lambda: None,
                            on_check_updates=lambda: (None, None), on_guide=lambda: None,
                            on_diagnostics=lambda: None, on_transfer=lambda: None)
    assert [dialog.tabs.tabText(i).replace("&&", "&") for i in range(dialog.tabs.count())] == [
        "General", "Switching", "Tray & hotkeys", "Integrations", "Updates", "Help & About"]
    assert _tab_of(dialog, dialog.qres) == "General"
    assert _tab_of(dialog, dialog.switch_delay) == "Switching"
    assert _tab_of(dialog, dialog.restore_hotkey) == "Tray & hotkeys"
    assert _tab_of(dialog, dialog.check_updates) == "Updates"
    button = {b.text(): b for b in dialog.findChildren(main_window.QPushButton)}
    assert _tab_of(dialog, button["Remove all hooks…"]) == "Integrations"   # away from everyday settings
    assert _tab_of(dialog, button["Diagnostics…"]) == "Help & About"
    assert _tab_of(dialog, button["Back up and restore…"]) == "Help & About"


def test_settings_still_saves_from_every_tab(win):
    dialog = SettingsDialog(win, win.cfg, win.modes)
    dialog.switch_delay.setValue(3.0)
    dialog.background.setChecked(True)
    dialog.check_updates.setChecked(False)
    dialog.apply_to(win.cfg)
    assert (win.cfg["switch_delay"], win.cfg["background"], win.cfg["check_updates"]) == (3.0, True, False)


def test_settings_dialog_applies(win):
    dialog = SettingsDialog(win, win.cfg, win.modes)
    dialog.qres.setText(r"D:\Tools\QRes.exe")
    dialog.default_size.setCurrentIndex(dialog.default_size.findData("1920x1080"))
    dialog.temporary.setChecked(False)
    dialog.switch_delay.setValue(2.5)
    dialog.check_updates.setChecked(False)
    dialog.apply_to(win.cfg)
    assert win.cfg["check_updates"] is False
    from qres_gui.gui.dialogs import licenses_folder
    assert (licenses_folder() / "LGPL-3.0.txt").is_file()
    assert win.cfg["qres_path"] == r"D:\Tools\QRes.exe"
    assert win.cfg["default_target"] == {"width": 1920, "height": 1080, "refresh": 0}
    assert win.cfg["temporary"] is False and win.cfg["switch_delay"] == 2.5


def test_add_game_dialog_needs_a_real_exe_and_a_name(win, env):
    from PySide6.QtWidgets import QDialogButtonBox
    dialog = AddGameDialog(win)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    dialog.exe.setText(str(env["tmp"] / "Games" / "Stardew" / "Stardew Valley.exe"))
    assert not ok.isEnabled()
    dialog.name.setText("Stardew (manual)")
    assert ok.isEnabled()


def test_playnite_dialog_adds_scripts_and_hooks_show_it(win, env, monkeypatch):
    cfg_path = env["tmp"] / "Playnite" / "config.json"
    cfg_path.parent.mkdir()
    cfg_path.write_text(json.dumps({"PreScript": None, "PostScript": None}), encoding="utf-8")
    monkeypatch.setattr(playnite, "config_path", lambda: cfg_path)
    dialog = PlayniteDialog(win)
    assert dialog.install_btn.isEnabled() and not dialog.remove_btn.isEnabled()
    dialog.install_btn.click()
    assert playnite.state(paths.launcher_command()) == "installed"
    assert not dialog.install_btn.isEnabled() and dialog.remove_btn.isEnabled()

    win.playnite_state = playnite.state(paths.launcher_command())
    select(win, "legendary:Quail")
    win.detail.enabled.setChecked(True)
    assert row(win, "legendary:Quail")[3] == "Playnite"

    monkeypatch.setattr(playnite, "is_running", lambda: True)
    dialog._refresh()
    assert not dialog.remove_btn.isEnabled() and "Playnite is running" in dialog.status.text()


def test_remove_all_hooks(win, env):
    select(win, "steam:10")
    win.detail.steam_apply.click()
    select(win, "gog:1453375253")
    win.detail.desktop_btn.click()
    win.remove_all_hooks()
    assert env["steam"].options["10"] == "-novid"
    assert not (env["desktop"] / "Stardew Valley (QRes).lnk").exists()
    assert not any(e.get("enabled") for e in config.load()["games"].values())
