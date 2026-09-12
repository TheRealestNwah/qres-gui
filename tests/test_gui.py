"""The GUI, driven offscreen with fake stores, a fake Steam and a fixed set of display modes."""

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from qres_gui import config, display, notify, paths, playnite, shortcuts
from qres_gui.gui import main_window, theme
from qres_gui.gui.dialogs import AddGameDialog, PlayniteDialog, SettingsDialog
from qres_gui.stores import Game, steam

MODES = [display.Mode(3440, 1440, 165), display.Mode(3440, 1440, 60), display.Mode(2560, 1440, 165),
         display.Mode(2560, 1440, 60), display.Mode(1920, 1080, 165)]
DESKTOP = MODES[0]


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
    monkeypatch.setattr(display, "list_modes", lambda: list(MODES))
    monkeypatch.setattr(display, "current_mode", lambda: DESKTOP)
    monkeypatch.setattr(display, "find_qres", lambda *a: r"C:\Tools\QRes.exe")
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


# --- banner, dialogs, hooks -----------------------------------------------------------

def test_problem_banner_shows_and_dismisses(win):
    assert win.event_bar.isHidden()
    notify.record("Couldn't switch to 2560 × 1440", "Counter Test is starting at your current resolution.")
    win._refresh_events()
    assert not win.event_bar.isHidden() and "switch to 2560 × 1440" in win.event_label.text()
    win._dismiss_events()
    assert win.event_bar.isHidden() and config.load()["events_seen"] > 0


def test_settings_dialog_applies(win):
    dialog = SettingsDialog(win, win.cfg, win.modes)
    dialog.qres.setText(r"D:\Tools\QRes.exe")
    dialog.default_size.setCurrentIndex(dialog.default_size.findData("1920x1080"))
    dialog.temporary.setChecked(False)
    dialog.switch_delay.setValue(2.5)
    dialog.apply_to(win.cfg)
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
