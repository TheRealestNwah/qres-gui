from __future__ import annotations

import html
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import QFileInfo, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFileIconProvider, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressDialog, QPushButton, QSplitter, QStatusBar, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import (__version__, autostart, commands, config, display, hdr, hooks, notify, paths, played, playnite,
                session, shortcuts, updates, watcher)
from ..stores import STORE_LABELS, Game, SteamClient, detect_all, steam
from . import theme
from .detail_panel import DetailPanel
from .dialogs import (AddGameDialog, DiagnosticsDialog, PlayniteDialog, SettingsDialog,
                      TransferDialog)
from .guide import GettingStarted
from .hotkeys import HotkeyManager
from .presets import ApplyResolutionDialog, PresetsDialog, preset_device, preset_label, preset_name
from .tray import Tray

ICON_SIZE = QSize(92, 43)
ROLE_ID = Qt.ItemDataRole.UserRole
ROLE_SORT = Qt.ItemDataRole.UserRole + 1     # what a column sorts by, when not its text
COLUMNS = ["Game", "Store", "Resolution", "Launch hook", "Last played"]
COL_HOOK, COL_PLAYED = 3, 4
HOOK_WIDTH = 170     # the widest the Launch hook column opens at, so long states don't squeeze names


class GameItem(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree else 0
        if column == COL_PLAYED:
            mine, theirs = float(self.data(column, ROLE_SORT) or 0), float(other.data(column, ROLE_SORT) or 0)
            if mine != theirs:
                return mine < theirs
            # Played the same moment, or never: A to Z, whichever way the column is sorted.
            descending = bool(tree) and tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
            before = self.text(0).casefold() < other.text(0).casefold()
            return not before if descending else before
        return self.text(column).casefold() < other.text(column).casefold()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"QRes GUI {__version__}")
        self.resize(1360, 840)
        self.cfg = config.load()
        self.steam = SteamClient()
        self.steam_running = self.steam.available and self.steam.is_running()
        self.modes = display.list_modes()          # the primary's, which presets use
        self.displays = display.list_displays()
        self._modes_by_device: dict[str, list[display.Mode]] = {}
        self.games: dict[str, Game] = {}
        self.items: dict[str, GameItem] = {}
        self.launch_opts: dict[str, str] = {}
        self.steam_played: dict[str, float] = {}    # Steam's own last-played times, by appid
        self.played: dict[str, float] = {}          # launches through QRes (played.json)
        self._played_seen = (-1.0, "")              # (played.json's mtime, the day) the column shows
        self.playnite_state = "missing"
        self._icons: dict[str, QPixmap] = {}
        self._save_timer = QTimer(self, singleShot=True, interval=400, timeout=self._save_now)
        self.tray = None            # set up after the first poll/rescan, at the end of __init__
        self.hotkeys = None
        self._quitting = False
        self._told_tray = False
        self._last_mode_str = ""
        self._show_hidden = False     # the "N hidden · Show" link under the list
        self.started_in_tray = False  # started with Windows, so closing the window keeps it running
        self.watcher: watcher.Watcher | None = None
        self._watch_targets: list[watcher.Target] = []
        self._watch_spec: list | None = None      # what the targets were built from
        self._watch_building = False
        self._watch_cooldown: dict[str, float] = {}

        self._init_defaults()
        self._build_ui()
        self._refresh_presets()
        self.rescan()
        self._poll_state()
        self._poll = QTimer(self, interval=2500, timeout=self._poll_state)
        self._poll.start()
        QTimer.singleShot(300, self._check_leftover_session)
        if self._needs_guide():
            QTimer.singleShot(300, self.open_guide)  # the guide covers finding QRes
        else:
            QTimer.singleShot(500, self._ensure_qres)
        self._update_found.connect(self._on_update_result)
        self._show_update_bar()                  # from an earlier check
        QTimer.singleShot(800, self._report_update_result)
        QTimer.singleShot(1500, self._auto_check_updates)
        self._setup_tray_and_hotkeys()
        self._targets_built.connect(self._on_targets_built)
        self._watch_timer = QTimer(self, interval=1000, timeout=self._watch_tick)
        self.apply_watch_setting()

    # --- setup -------------------------------------------------------------

    def _init_defaults(self) -> None:
        if not self.cfg.get("qres_path") or not os.path.isfile(self.cfg["qres_path"]):
            self.cfg["qres_path"] = display.find_qres() or self.cfg.get("qres_path", "")
        if not self.cfg.get("desktop_mode"):
            active = session.read()
            mode = active["original"] if active else display.current_mode().to_dict()
            self.cfg["desktop_mode"] = mode
        target = self.cfg["default_target"]
        sizes = {(m.width, m.height) for m in self.modes}
        if (target["width"], target["height"]) not in sizes and self.modes:
            desktop = display.current_mode()
            same_height = [m for m in self.modes if m.height == desktop.height and m.width < desktop.width]
            fallback = same_height[0] if same_height else self.modes[0]
            self.cfg["default_target"] = {"width": fallback.width, "height": fallback.height, "refresh": 0}
        config.save(self.cfg)

    def _build_ui(self) -> None:
        # Top bar: current mode and global actions.
        top = QFrame(objectName="topBar")
        bar = QHBoxLayout(top)
        bar.setContentsMargins(18, 12, 18, 12)
        logo = QLabel()
        logo.setPixmap(theme.icon_pixmap(40))
        bar.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(QLabel("Primary display", objectName="caption"))
        self.desktop_label = QLabel(objectName="desktopMode")
        col.addWidget(self.desktop_label)
        bar.addLayout(col)
        bar.addSpacing(16)
        self.session_label = QLabel()
        bar.addWidget(self.session_label)
        bar.addStretch()
        self.restore_btn = QPushButton("Restore desktop resolution", clicked=self.restore_desktop)
        self.sync_btn = QPushButton("Update Steam launch options", clicked=self.sync_steam)
        add_btn = QPushButton("Add game…", clicked=self.add_game)
        rescan_btn = QPushButton("Rescan", clicked=self.rescan)
        settings_btn = QPushButton("Settings", clicked=self.open_settings)
        for button in (self.restore_btn, self.sync_btn, add_btn, rescan_btn, settings_btn):
            bar.addWidget(button)

        # Left: filters and the game list.
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search games…", clearButtonEnabled=True)
        self.search.textChanged.connect(self._apply_filter)
        # One pill with a chevron, so it reads as a dropdown at a glance (#9). The
        # search box shares its height so the row lines up.
        self.store_filter = QComboBox(objectName="pill")
        self.store_filter.setFixedHeight(theme.PILL_HEIGHT)
        self.search.setFixedHeight(theme.PILL_HEIGHT)
        self.store_filter.currentIndexChanged.connect(self._apply_filter)
        self.only_configured = QCheckBox("Configured only")
        self.only_configured.toggled.connect(self._apply_filter)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.store_filter)
        filters.addWidget(self.only_configured)
        lv.addLayout(filters)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(COLUMNS)
        self.tree.headerItem().setToolTip(COL_PLAYED, "When the game was last started through QRes, "
                                                      "or by Steam for Steam games")
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(ICON_SIZE)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        # Sized to its contents up to a limit instead (_fit_columns), and draggable: its longest
        # states would otherwise leave game names as "METAL GEAR ..." in a normal-sized window.
        header.setSectionResizeMode(COL_HOOK, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)   # the spare room goes to Game, not Last played
        sort = self.cfg.get("list_sort") or {}
        column = sort.get("column") if sort.get("column") in range(len(COLUMNS)) else 0
        self._sort_column = column
        self.tree.sortByColumn(column, Qt.SortOrder.DescendingOrder if sort.get("descending")
                               else Qt.SortOrder.AscendingOrder)
        header.sortIndicatorChanged.connect(self._on_sort_changed)
        self.tree.currentItemChanged.connect(self._on_select)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._game_menu)
        lv.addWidget(self.tree, 1)
        self.summary = QLabel(objectName="muted")
        # Holds the "N hidden · Show" link, which only appears while a game is hidden.
        self.summary.linkActivated.connect(lambda _: self.set_show_hidden(not self._show_hidden))
        lv.addWidget(self.summary)

        self.detail = DetailPanel(self)
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([840, 520])

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(14, 12, 14, 8)
        bl.addWidget(splitter)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(top)
        cl.addWidget(self._build_quickswitch_bar())
        cl.addWidget(self._build_update_bar())
        cl.addWidget(self._build_event_bar())
        cl.addWidget(body, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

    # --- tray icon and global hotkeys ----------------------------------------

    HK_RESTORE = 1
    HK_PRESET_BASE = 100

    def _setup_tray_and_hotkeys(self) -> None:
        if self.cfg.get("tray_icon", True) and Tray.available():
            self.tray = Tray(self)
            self.tray.show()
        # RegisterHotKey needs a window handle; winId() creates it even while hidden.
        self.hotkeys = HotkeyManager(int(self.winId()), self._on_hotkey)
        QApplication.instance().installNativeEventFilter(self.hotkeys)
        self.apply_hotkeys()

    def apply_hotkeys(self) -> dict:
        """(Re)register global hotkeys from the config; returns {id: sequence} that failed."""
        bindings = {}
        if self.cfg.get("restore_hotkey"):
            bindings[self.HK_RESTORE] = self.cfg["restore_hotkey"]
        for i, preset in enumerate(self.cfg.get("presets", [])):
            if preset.get("hotkey"):
                bindings[self.HK_PRESET_BASE + i] = preset["hotkey"]
        self._hotkey_failed = self.hotkeys.apply(bindings)
        return self._hotkey_failed

    def _on_hotkey(self, hotkey_id: int) -> None:
        if hotkey_id == self.HK_RESTORE:
            self.restore_desktop()
        else:
            presets = self.cfg.get("presets", [])
            index = hotkey_id - self.HK_PRESET_BASE
            if 0 <= index < len(presets):
                self.apply_preset(presets[index])

    def refresh_tray(self, force: bool = False) -> None:
        if not self.tray:
            return
        try:
            mode = str(display.current_mode())
        except display.DisplayError:
            mode = ""
        if force or mode != self._last_mode_str:
            self._last_mode_str = mode
            self.tray.rebuild()

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()

    # --- quick resolution switching ------------------------------------------

    def _build_quickswitch_bar(self) -> QFrame:
        bar = QFrame(objectName="quickBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 6, 18, 6)
        row.setSpacing(6)
        quick = QLabel("Quick switch", objectName="caption")
        quick.setToolTip("Presets and their hotkeys switch the display the preset names, or "
                         "the primary one when it names none.")
        row.addWidget(quick)
        self._preset_row = QHBoxLayout()
        self._preset_row.setSpacing(6)
        row.addLayout(self._preset_row)
        self._no_presets = QLabel("no presets yet", objectName="muted")
        row.addWidget(self._no_presets)
        row.addStretch()
        row.addWidget(QPushButton("Manage presets…", clicked=self.open_presets))
        return bar

    def _refresh_presets(self) -> None:
        while self._preset_row.count():
            self._preset_row.takeAt(0).widget().deleteLater()
        self._preset_chips = []
        presets = self.cfg.get("presets", [])
        self._no_presets.setVisible(not presets)
        for preset in presets:
            chip = QPushButton(preset_name(preset))
            screen = preset_device(preset)
            tip = f"Switch to {preset_label(preset)}"   # the label names the screen when it isn't the primary
            if not display.is_size_available(preset["width"], preset["height"], self.modes_for(screen)):
                tip += " — needs a custom resolution first"
            chip.setToolTip(tip)
            chip.clicked.connect(lambda _c=False, p=preset: self.apply_preset(p))
            self._preset_row.addWidget(chip)
            self._preset_chips.append((chip, preset))
        self._update_preset_highlight()
        if getattr(self, "hotkeys", None):  # presets carry hotkeys; tray lists presets
            self.apply_hotkeys()
            self.refresh_tray(force=True)

    def _update_preset_highlight(self) -> None:
        """Mark the chips whose resolution matches their own screen now, without rebuilding."""
        seen: dict[str | None, display.Mode | None] = {}
        for chip, preset in getattr(self, "_preset_chips", []):
            screen = preset_device(preset)
            if screen not in seen:
                try:
                    seen[screen] = display.current_mode(screen)
                except display.DisplayError:
                    seen[screen] = None
            current = seen[screen]
            active = current is not None and (current.width, current.height) == (preset["width"], preset["height"])
            name = "presetActive" if active else "preset"
            if chip.objectName() != name:
                chip.setObjectName(name)
                chip.style().unpolish(chip)
                chip.style().polish(chip)

    def apply_preset(self, preset: dict) -> None:
        """Apply a preset to the screen it names - including when a hotkey fires it."""
        screen = preset_device(preset)
        if screen and display.find_display(screen) is None:
            self.statusBar().showMessage(
                f"Display {display.device_number(screen)} isn't connected, so "
                f"{preset_name(preset)} was left alone.", 8000)
            return
        try:
            desktop = display.current_mode(screen)
        except display.DisplayError:
            return
        target = display.resolve(int(preset["width"]), int(preset["height"]),
                                 int(preset.get("refresh") or 0), desktop, screen)
        self.apply_resolution(target, screen)

    def apply_resolution(self, target: display.Mode, device: str | None = None) -> None:
        ApplyResolutionDialog(self, target, display.find_qres(self.cfg.get("qres_path")),
                              bool(self.cfg.get("temporary", True)), device=device).exec()
        self._refresh_presets()
        self._poll_state()

    def open_presets(self) -> None:
        PresetsDialog(self).exec()
        self._refresh_presets()

    def save_presets(self) -> None:
        self._save_now()
        self._refresh_presets()

    # --- updates -------------------------------------------------------------

    _update_found = Signal(object, str)  # (newer release or None, error text); from the checking thread

    def _build_update_bar(self) -> QFrame:
        self.update_bar = QFrame(objectName="updateBar")
        row = QHBoxLayout(self.update_bar)
        row.setContentsMargins(18, 8, 18, 8)
        self.update_label = QLabel()
        row.addWidget(self.update_label, 1)
        self.install_update_btn = QPushButton("Install update", objectName="primary", clicked=self.install_update)
        self.whats_new_btn = QPushButton("What's new", clicked=self._open_update_page)
        row.addWidget(self.install_update_btn)
        row.addWidget(self.whats_new_btn)
        row.addWidget(QPushButton("Later", clicked=self._dismiss_update))
        self.update_bar.hide()
        return self.update_bar

    def _auto_check_updates(self) -> None:
        if not self.cfg.get("check_updates", True):
            return
        if time.time() - float(self.cfg.get("update_last_check") or 0) < updates.CHECK_INTERVAL:
            return
        self.check_for_updates()

    def check_for_updates(self, wait: bool = False) -> tuple[dict | None, str]:
        """Ask GitHub in the background (or, with `wait`, right away) and show what it says."""
        def work() -> tuple[dict | None, str]:
            try:
                return updates.check(), ""
            except (OSError, ValueError) as exc:
                return None, str(exc)

        if wait:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                result = work()
            finally:
                QApplication.restoreOverrideCursor()
            self._on_update_result(*result)
            return result
        threading.Thread(target=lambda: self._update_found.emit(*work()), name="update-check", daemon=True).start()
        return None, ""

    def _on_update_result(self, release: dict | None, error: str) -> None:
        if error:
            return  # offline or GitHub unreachable: try again another day
        self.cfg["update_last_check"] = time.time()
        self.cfg["update_available"] = {"version": release["version"], "url": release["url"],
                                        "download": release.get("download")} if release else None
        self._save_now()
        self._show_update_bar()

    def _show_update_bar(self) -> None:
        available = self.cfg.get("update_available") or {}
        version = available.get("version", "")
        show = updates.is_newer(version, __version__) and version != self.cfg.get("update_dismissed")
        if show:
            self.update_label.setText(f"<b>QRes GUI {html.escape(version)} is available</b>"
                                      f"&nbsp;&nbsp;<span style='color:{theme.MUTED}'>You have {__version__}.</span>")
            # Only the installed copy updates itself: installing always goes to the
            # install folder, which isn't where an unzipped or source copy runs from.
            can_install = self.can_install_update()
            self.install_update_btn.setVisible(can_install)
            self.whats_new_btn.setObjectName("" if can_install else "primary")
            self.whats_new_btn.style().unpolish(self.whats_new_btn)
            self.whats_new_btn.style().polish(self.whats_new_btn)
        self.update_bar.setVisible(show)

    def can_install_update(self) -> bool:
        available = self.cfg.get("update_available") or {}
        return bool(available.get("download")) and paths.is_installed_copy()

    _update_progress = Signal(int, int)       # (bytes so far, total); from the download thread
    _update_fetched = Signal(object, str)     # (unpacked folder or None, error text)

    def install_update(self, wait: bool = False) -> bool:
        """Download the new release, then close so its installer can run. True once handed over."""
        available = self.cfg.get("update_available") or {}
        version, download = available.get("version", ""), available.get("download")
        if not (download and updates.is_newer(version, __version__)):
            return False
        active = session.read()
        if active and session.owner_alive(active):
            QMessageBox.information(self, "Install update",
                                    "A game is running through QRes. Install the update once you've quit it — "
                                    "installing replaces the launcher that's switching the display back.")
            return False
        size = int(download.get("size") or 0)
        answer = QMessageBox.question(
            self, "Install update",
            f"Download QRes GUI {version}{f' ({size / 1048576:.0f} MB)' if size else ''} from GitHub and "
            "install it?\n\nQRes GUI closes, installs the update and opens again. Your profiles, settings, "
            "Steam launch options and Playnite scripts stay as they are.")
        if answer != QMessageBox.StandardButton.Yes:
            return False

        folder = updates.work_root() / version
        cancelled = threading.Event()

        def work(progress) -> tuple[Path | None, str]:
            try:
                zip_path = updates.fetch(download, folder.with_suffix(".zip"),
                                         lambda done, total: progress(done, total) and not cancelled.is_set())
                return updates.unpack(zip_path, folder, version), ""
            except updates.UpdateError as exc:
                return None, str(exc)

        if wait:
            return self._on_update_fetched(*work(lambda *_: True), version=version)

        dialog = QProgressDialog(f"Downloading QRes GUI {version}…", "Cancel", 0, max(size, 1), self)
        dialog.setWindowTitle("Install update")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.canceled.connect(cancelled.set)
        self._update_dialog = dialog

        def progress(done: int, total: int) -> bool:
            self._update_progress.emit(done, total)
            return True

        def on_progress(done: int, total: int) -> None:
            if total:
                dialog.setMaximum(total)
            dialog.setValue(min(done, dialog.maximum()))

        def on_fetched(source, error: str) -> None:
            self._update_progress.disconnect(on_progress)
            self._update_fetched.disconnect(on_fetched)
            was_cancelled = cancelled.is_set()
            dialog.canceled.disconnect(cancelled.set)   # closing it counts as Cancel
            dialog.close()
            if not was_cancelled:
                self._on_update_fetched(source, error, version=version)

        self._update_progress.connect(on_progress)
        self._update_fetched.connect(on_fetched)
        threading.Thread(target=lambda: self._update_fetched.emit(*work(progress)),
                         name="update-download", daemon=True).start()
        return True

    def _on_update_fetched(self, source: Path | None, error: str, version: str) -> bool:
        if source is None:
            QMessageBox.warning(self, "Install update",
                                f"{error}\n\nYou can also download it from the releases page and run install.cmd.")
            return False
        try:
            updates.start_install(source, version)
        except updates.UpdateError as exc:
            QMessageBox.warning(self, "Install update", str(exc))
            return False
        self.quit_app()
        return True

    def _report_update_result(self) -> None:
        """Say how an in-app update went, on the first start after it."""
        result = updates.take_result()
        if not result:
            return
        if result["ok"] and result["version"] == __version__:
            self.statusBar().showMessage(f"Updated to QRes GUI {__version__}.", 15000)
        else:
            detail = result["error"] or "The installer didn't finish."
            QMessageBox.warning(self, "Update not installed",
                                f"QRes GUI {result['version'] or 'the new version'} couldn't be installed, so you "
                                f"still have {__version__}.\n\n{detail}\n\nThe installer's log is "
                                f"{updates.log_path()}.")

    def _open_update_page(self) -> None:
        url = (self.cfg.get("update_available") or {}).get("url") or updates.RELEASES_PAGE
        QDesktopServices.openUrl(QUrl(url))

    def _dismiss_update(self) -> None:
        self.cfg["update_dismissed"] = (self.cfg.get("update_available") or {}).get("version", "")
        self._save_now()
        self.update_bar.hide()

    def _build_event_bar(self) -> QFrame:
        """Banner for the latest launcher problem the user hasn't dismissed yet."""
        self.event_bar = QFrame(objectName="eventBar")
        row = QHBoxLayout(self.event_bar)
        row.setContentsMargins(18, 8, 18, 8)
        self.event_label = QLabel(wordWrap=True)
        self.event_label.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.event_label, 1)
        row.addWidget(QPushButton("Open log", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.log_path())))))
        row.addWidget(QPushButton("Dismiss", clicked=self._dismiss_events))
        self.event_bar.hide()
        self._events_mtime = None
        return self.event_bar

    def _refresh_events(self) -> None:
        try:
            mtime = notify.events_path().stat().st_mtime
        except OSError:
            mtime = None
        if mtime == self._events_mtime:
            return
        self._events_mtime = mtime
        seen = float(self.cfg.get("events_seen", 0))
        unseen = [e for e in notify.read_events() if float(e.get("time", 0)) > seen]
        if not unseen:
            self.event_bar.hide()
            return
        latest = unseen[-1]
        when = time.strftime("%a %H:%M", time.localtime(float(latest["time"])))
        more = f"  ·  {len(unseen) - 1} earlier" if len(unseen) > 1 else ""
        color = theme.ACCENT if latest.get("level") == "info" else theme.WARN
        self.event_label.setText(
            f"<span style='color:{color}; font-weight:600'>{html.escape(latest.get('title', ''))}</span>"
            f"&nbsp;&nbsp;{html.escape(latest.get('message', ''))}"
            f"<span style='color:{theme.MUTED}'>&nbsp;&nbsp;·&nbsp;&nbsp;{when}{more}</span>")
        self.event_bar.show()

    def _pick_up_playnite_games(self) -> None:
        """Rescan when Playnite has started a game QRes didn't know, so it appears while the GUI is open."""
        try:
            mtime = playnite.seen_path().stat().st_mtime
        except OSError:
            mtime = None
        previous = getattr(self, "_seen_mtime", "unset")
        self._seen_mtime = mtime
        if previous != "unset" and mtime != previous:
            self.rescan()

    def _dismiss_events(self) -> None:
        times = [float(e.get("time", 0)) for e in notify.read_events()]
        self.cfg["events_seen"] = max(times, default=time.time())
        self._save_now()
        self.event_bar.hide()

    # --- data --------------------------------------------------------------

    def rescan(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            detected, errors = detect_all(self.steam)
            self._reload_launch_options()
        finally:
            QApplication.restoreOverrideCursor()
        manual = [
            Game(id=gid, name=e.get("name", gid), store="manual",
                 install_dir=os.path.dirname((e.get("launch") or {}).get("path", "")),
                 exe=(e.get("launch") or {}).get("path", ""), launch=e.get("launch"))
            for gid, e in self.cfg["games"].items() if e.get("store") == "manual"
        ]
        self.games = {g.id: g for g in detected + manual}
        # Keep saved profiles in step with what the stores report now; the
        # launcher and Playnite matching work from these copies.
        for gid, entry in self.cfg["games"].items():
            game = self.games.get(gid)
            if game and game.store != "manual":
                entry["launch"], entry["name"] = game.launch, game.name
            if game:
                entry["install_dir"] = game.install_dir
        self.playnite_state = playnite.state(paths.hook_command())
        # A rescan is also the moment to notice a display being plugged in or out.
        self.displays = display.list_displays()
        self._modes_by_device.clear()
        self.save()

        stores_present = sorted({g.store for g in self.games.values()}, key=list(STORE_LABELS).index)
        current = self.store_filter.currentData()
        self.store_filter.blockSignals(True)
        self.store_filter.clear()
        self.store_filter.addItem("All stores", None)
        for store in stores_present:
            self.store_filter.addItem(STORE_LABELS[store], store)
        self.store_filter.setCurrentIndex(max(self.store_filter.findData(current), 0))
        self.store_filter.blockSignals(False)
        self._populate()

        counts = ", ".join(
            f"{STORE_LABELS[s]} {sum(g.store == s for g in self.games.values())}" for s in stores_present
        )
        message = f"Found {len(self.games)} games ({counts})."
        if errors:
            message += "  Problems: " + "; ".join(errors)
        self.statusBar().showMessage(message, 10000)

    def _reload_launch_options(self) -> None:
        if not self.steam.available:
            self.launch_opts = {}
            return
        try:
            self.launch_opts = self.steam.launch_options()
            self.steam_played = self.steam.last_played()
        except (OSError, ValueError) as exc:
            self.launch_opts = {}
            self.statusBar().showMessage(f"Couldn't read Steam launch options: {exc}", 10000)

    def modes_for(self, device: str | None) -> list[display.Mode]:
        """The modes one display offers, read once and kept.

        `self.modes` stays the primary's, which is what a caller with no
        display in hand - and a preset that names none - asks for.
        """
        if not device:
            return self.modes
        if device not in self._modes_by_device:
            try:
                self._modes_by_device[device] = display.list_modes(device)
            except display.DisplayError:
                self._modes_by_device[device] = []
        return self._modes_by_device[device] or self.modes

    def entry_for(self, game: Game, create: bool = False) -> dict | None:
        entry = self.cfg["games"].get(game.id)
        if entry is None and create:
            entry = self.default_entry(game)
            self.cfg["games"][game.id] = entry
        return entry

    def default_entry(self, game: Game) -> dict:
        target = self.cfg["default_target"]
        return {
            "name": game.name, "store": game.store, "enabled": False,
            "width": target["width"], "height": target["height"], "refresh": target.get("refresh", 0),
            "watch": [Path(game.exe).name] if game.needs_watch and game.exe else [],
            "launch": game.launch,
            "install_dir": game.install_dir,
        }

    def save(self) -> None:
        self._save_timer.start()

    def _save_now(self) -> None:
        config.save(self.cfg)

    def closeEvent(self, event) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_now()
        # Keep running in the tray if asked, unless we're really quitting.
        if not self._quitting and self.tray and (self.cfg.get("background") or self.started_in_tray):
            event.ignore()
            self.hide()
            if not self._told_tray:
                self._told_tray = True
                self.tray.showMessage("QRes GUI", "Still running in the tray — right-click for presets, "
                                      "or Quit to exit.", self.tray.icon(), 5000)
            return
        if self.tray:
            self.tray.hide()
        if getattr(self, "hotkeys", None):
            self.hotkeys.clear()
        super().closeEvent(event)
        QApplication.instance().quit()

    # --- Steam helpers used by the detail panel ------------------------------

    def steam_prefix(self, game_id: str) -> str:
        return steam.launch_prefix(paths.hook_command(), game_id)

    def steam_state(self, game: Game) -> str:
        appid = game.id.split(":", 1)[1]
        return steam.option_state(self.launch_opts.get(appid, ""), self.steam_prefix(game.id))

    def steam_hook_missing(self, game: Game) -> bool:
        """Whether the game's launch options run a QRes launcher that's been deleted or moved."""
        launcher = steam.hooked_launcher(self.launch_opts.get(game.id.split(":", 1)[1], ""))
        return bool(launcher) and not os.path.isfile(launcher)

    def write_steam_options(self, updates: dict[str, str]) -> bool:
        try:
            backup = self.steam.set_launch_options(updates)
        except Exception as exc:
            QMessageBox.warning(self, "Steam launch options", str(exc))
            return False
        self._reload_launch_options()
        self.statusBar().showMessage(f"Updated Steam launch options (backup: {backup.name}).", 10000)
        self.refresh_rows()
        return True

    def pending_steam_updates(self) -> dict[str, str]:
        updates = {}
        for game in self.games.values():
            if game.store != "steam":
                continue
            appid = game.id.split(":", 1)[1]
            current = self.launch_opts.get(appid, "")
            entry = self.cfg["games"].get(game.id)
            if entry and entry.get("enabled"):
                wanted = steam.apply_ours(current, self.steam_prefix(game.id))
            else:
                wanted, _ = steam.strip_ours(current)
            if wanted != current:
                updates[appid] = wanted
        return updates

    def sync_steam(self) -> None:
        updates = self.pending_steam_updates()
        if not updates:
            return
        names = [g.name for g in self.games.values() if g.id.startswith("steam:") and g.id[6:] in updates]
        answer = QMessageBox.question(
            self, "Update Steam launch options",
            "Update launch options for:\n\n  " + "\n  ".join(sorted(names, key=str.casefold)) +
            "\n\nGames with resolution switching on get the launcher added; games with it off have it removed. "
            "Your other launch options are kept.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.write_steam_options(updates)

    # --- list --------------------------------------------------------------

    def _populate(self) -> None:
        self.played = played.load()
        self._played_seen = (played.mtime(), time.strftime("%Y-%m-%d"))
        selected = self.detail.game.id if self.detail.game else None
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        self.items = {}
        for game in self.games.values():
            item = GameItem()
            item.setData(0, ROLE_ID, game.id)
            item.setIcon(0, self._list_icon(game))
            self.tree.addTopLevelItem(item)
            self.items[game.id] = item
            self._fill_row(game)
        self.tree.setSortingEnabled(True)
        self._fit_columns()
        self._apply_filter()
        self._update_sync_button()
        if selected in self.items:
            self.tree.setCurrentItem(self.items[selected])
        elif selected:
            self.detail.show_game(None)

    def _fill_row(self, game: Game) -> None:
        item = self.items[game.id]
        entry = self.cfg["games"].get(game.id)
        enabled = bool(entry and entry.get("enabled"))
        # Only ever on screen while "Show" is on, so it's worth saying which ones they are.
        hidden = game.id in self.hidden_ids()
        item.setText(0, f"{game.name}  (hidden)" if hidden else game.name)
        item.setToolTip(0, game.name)   # long names are cut short in the column
        item.setData(0, Qt.ItemDataRole.ForegroundRole, QBrush(QColor(theme.MUTED)) if hidden else None)
        item.setText(1, game.store_label)
        item.setForeground(1, QBrush(QColor(theme.STORE_COLORS.get(game.store, theme.MUTED))))
        target = f"{entry['width']} × {entry['height']}" if enabled else "—"
        if enabled and entry.get("display"):
            target += f"  ·  Display {display.device_number(entry['display'])}"
        if enabled and entry.get("hdr") is not None:
            target += "  ·  HDR " + ("on" if entry["hdr"] else "off")
        item.setText(2, target)
        item.setForeground(2, QBrush(QColor("#e4e6ea" if enabled else theme.MUTED)))
        text, kind = self.hook_status(game, entry)
        item.setText(3, text)
        item.setToolTip(COL_HOOK, text)
        color = {"ok": theme.OK, "warn": theme.WARN}.get(kind, theme.MUTED)
        item.setForeground(3, QBrush(QColor(color)))
        self._fill_played(game)

    def _fit_columns(self) -> None:
        self.tree.setColumnWidth(COL_HOOK, min(self.tree.sizeHintForColumn(COL_HOOK) + 12, HOOK_WIDTH))

    # --- switching for games started without QRes -----------------------------

    _targets_built = Signal(object, object)   # (spec, targets); from the thread that walks game folders
    ADOPT_COOLDOWN = 30.0                      # seconds before the same game can be adopted again

    def apply_watch_setting(self) -> None:
        if self.cfg.get("watch_games"):
            if self.watcher is None:
                self.watcher = watcher.Watcher()
                self._watch_spec = None
                self._watch_timer.start()
        else:
            self._watch_timer.stop()
            self.watcher = None
            self._watch_targets = []

    def watch_spec(self) -> list[tuple[str, str, list[str]]]:
        """(game id, install folder, watched names) for every game with switching on."""
        spec = []
        for game_id, entry in sorted(self.cfg["games"].items()):
            if not entry.get("enabled"):
                continue
            game = self.games.get(game_id)
            folder = (game.install_dir if game else "") or entry.get("install_dir") or \
                os.path.dirname((entry.get("launch") or {}).get("path") or "")
            spec.append((game_id, folder, sorted(entry.get("watch") or [])))
        return spec

    def _watch_tick(self) -> None:
        if self.watcher is None:
            return
        spec = self.watch_spec()
        if spec != self._watch_spec and not self._watch_building:
            self._watch_building = True
            threading.Thread(target=lambda: self._targets_built.emit(spec, watcher.build_targets(spec)),
                             name="watch-targets", daemon=True).start()
        for game_id, pid in self.watcher.poll(self._watch_targets):
            self.adopt_game(game_id, pid)

    def _on_targets_built(self, spec, targets) -> None:
        self._watch_building = False
        self._watch_spec, self._watch_targets = spec, targets

    def adopt_game(self, game_id: str, pid: int) -> bool:
        """Hand a game that started without QRes to the launcher; True if it was."""
        now = time.monotonic()
        if self._watch_cooldown.get(game_id, 0) > now:
            return False   # its other processes, or a restart, while the launcher already has it
        active = session.read()
        if active and session.owner_alive(active):
            return False   # a hook, Playnite or another game already switched
        self._watch_cooldown[game_id] = now + self.ADOPT_COOLDOWN
        name = (self.cfg["games"].get(game_id) or {}).get("name", game_id)
        try:
            subprocess.Popen(paths.hook_command() + ["adopt", game_id, str(pid)],
                             creationflags=0x00000008 | 0x00000200, close_fds=True)   # detached, own group
        except OSError as exc:
            self.statusBar().showMessage(f"Couldn't switch for {name}: {exc}", 10000)
            return False
        self.statusBar().showMessage(f"{name} started outside QRes; switching while it runs.", 8000)
        return True

    # --- last played ------------------------------------------------------------

    def last_played(self, game: Game) -> float:
        """When the game was last started: through QRes, or by Steam for a Steam game. 0 if never."""
        steam_time = self.steam_played.get(game.id[6:], 0.0) if game.store == "steam" else 0.0
        return max(self.played.get(game.id, 0.0), steam_time)

    def _fill_played(self, game: Game) -> None:
        item = self.items[game.id]
        when = self.last_played(game)
        item.setText(COL_PLAYED, played.describe(when))
        item.setData(COL_PLAYED, ROLE_SORT, when)
        item.setToolTip(COL_PLAYED, time.strftime("%d %B %Y, %H:%M", time.localtime(when)) if when else "")
        item.setForeground(COL_PLAYED, QBrush(QColor("#e4e6ea" if when else theme.MUTED)))

    def _refresh_played(self) -> None:
        """Pick up a launch the launcher noted, or a new day turning "Today" into "Yesterday"."""
        seen = (played.mtime(), time.strftime("%Y-%m-%d"))
        if seen == self._played_seen:
            return
        self._played_seen = seen
        self.played = played.load()
        sorting = self.tree.isSortingEnabled()
        self.tree.setSortingEnabled(False)          # re-sort once, not once per row
        for game_id in self.items:
            self._fill_played(self.games[game_id])
        self.tree.setSortingEnabled(sorting)

    def _on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        if column == COL_PLAYED and self._sort_column != COL_PLAYED and order == Qt.SortOrder.AscendingOrder:
            # Most recent first is what anyone sorting by Last played wants to see. Once
            # this signal is done: the tree's own sort also answers it, and may come after us.
            self._sort_column = column
            QTimer.singleShot(0, lambda: self.tree.sortByColumn(column, Qt.SortOrder.DescendingOrder))
            return
        self._sort_column = column
        self.cfg["list_sort"] = {"column": column, "descending": order == Qt.SortOrder.DescendingOrder}
        self.save()

    @property
    def playnite_hooked(self) -> bool:
        return self.playnite_state == "installed"

    def hook_status(self, game: Game, entry: dict | None) -> tuple[str, str]:
        enabled = bool(entry and entry.get("enabled"))
        if game.store == "steam":
            state = self.steam_state(game)
            if state == "applied":
                return ("Steam launch options", "ok") if enabled else ("Launch options (switching off)", "off")
            if state == "outdated" and self.steam_hook_missing(game):
                return "Launch options broken — update them", "warn"
            if state == "outdated":
                return "Launch options need updating", "warn"
            if enabled and self.playnite_hooked:
                return "Playnite only", "ok"
            if enabled and self.cfg.get("watch_games"):
                return "When it starts", "ok"
            return ("Launch options not set", "warn") if enabled else ("—", "off")
        found = shortcuts.existing(game.name)
        if found:
            where = " + ".join("Desktop" if p.parent == shortcuts.desktop_dir() else "Start menu" for p in found)
            if self.playnite_hooked:
                where += " + Playnite"
            return f"Shortcut: {where}", "ok" if enabled else "off"
        if self.playnite_hooked:
            return ("Playnite", "ok") if enabled else ("—", "off")
        if enabled and self.cfg.get("watch_games"):
            return "When it starts", "ok"
        if not game.launch:  # only startable from Playnite
            return ("Needs Playnite setup", "warn") if enabled else ("—", "off")
        return ("No shortcut yet", "warn") if enabled else ("—", "off")

    def refresh_rows(self, game_id: str | None = None) -> None:
        targets = [game_id] if game_id else list(self.items)
        for gid in targets:
            if gid in self.games and gid in self.items:
                self._fill_row(self.games[gid])
        self._apply_filter()
        self._update_sync_button()
        self.detail.refresh_integration()

    def _update_sync_button(self) -> None:
        pending = len(self.pending_steam_updates())
        self.sync_btn.setVisible(self.steam.available)
        self.sync_btn.setText(f"Update Steam launch options ({pending})" if pending else "Steam launch options up to date")
        self.sync_btn.setObjectName("primary" if pending and not self.steam_running else "")
        self.sync_btn.style().unpolish(self.sync_btn)
        self.sync_btn.style().polish(self.sync_btn)
        self.sync_btn.setEnabled(bool(pending) and not self.steam_running)
        self.sync_btn.setToolTip(
            "Close Steam first - it overwrites its config file when it exits." if self.steam_running and pending
            else "Write QRes launch options for every Steam game with switching turned on."
        )

    def _apply_filter(self) -> None:
        needle = self.search.text().strip().casefold()
        store = self.store_filter.currentData()
        only = self.only_configured.isChecked()
        hidden = self.hidden_ids()
        shown = 0
        for gid, item in self.items.items():
            game = self.games[gid]
            entry = self.cfg["games"].get(gid)
            visible = (
                (not needle or needle in game.name.casefold())
                and (store is None or game.store == store)
                and (not only or bool(entry and entry.get("enabled")))
                and (self._show_hidden or gid not in hidden)
            )
            item.setHidden(not visible)
            shown += visible
        enabled = sum(1 for g in self.games if (self.cfg["games"].get(g) or {}).get("enabled"))
        text = f"{shown} of {len(self.items)} games shown · {enabled} switch resolution"
        count = sum(1 for gid in self.items if gid in hidden)
        if count:
            link = "Hide them again" if self._show_hidden else "Show"
            text = html.escape(text) + f" · {count} hidden — <a href='hidden'>{link}</a>"
        elif self._show_hidden:
            self._show_hidden = False   # nothing left to show
        self.summary.setText(text)

    # --- hiding games from the list ------------------------------------------

    def hidden_ids(self) -> set[str]:
        return set(self.cfg.get("hidden_games") or [])

    def set_hidden(self, game_id: str, hide: bool) -> None:
        """Hide a game from the list, or bring it back. Its profile and switching are untouched."""
        ids = [gid for gid in (self.cfg.get("hidden_games") or []) if gid != game_id]
        if hide:
            ids.append(game_id)
        self.cfg["hidden_games"] = ids
        self._save_now()
        if game_id in self.games:
            self._fill_row(self.games[game_id])
        self._apply_filter()
        name = self.games[game_id].name if game_id in self.games else game_id
        self.statusBar().showMessage(
            f"Hid {name}. It still switches when you start it; “Show” under the list brings it back."
            if hide else f"{name} is back in the list.", 8000)

    def set_show_hidden(self, show: bool) -> None:
        self._show_hidden = show
        self._apply_filter()

    def _game_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is not None:
            self.game_menu(item.data(0, ROLE_ID)).exec(self.tree.viewport().mapToGlobal(pos))

    def game_menu(self, game_id: str) -> QMenu:
        """The right-click menu for a game in the list."""
        hidden = game_id in self.hidden_ids()
        menu = QMenu(self)
        action = menu.addAction("Show in list" if hidden else "Hide from list")
        action.triggered.connect(lambda: self.set_hidden(game_id, not hidden))
        return menu

    def _on_select(self, current: QTreeWidgetItem | None, _previous) -> None:
        game = self.games.get(current.data(0, ROLE_ID)) if current else None
        self.detail.show_game(game)

    def _list_icon(self, game: Game) -> QPixmap:
        key = game.image or game.exe or game.store
        if key in self._icons:
            return self._icons[key]
        w, h = ICON_SIZE.width(), ICON_SIZE.height()
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        image = QPixmap(game.image) if game.image else QPixmap()
        if not image.isNull():
            scaled = image.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(0, 0, scaled, (scaled.width() - w) // 2, (scaled.height() - h) // 2, w, h)
        else:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            base = QColor(theme.STORE_COLORS.get(game.store, theme.MUTED))
            base.setAlpha(46)
            painter.setBrush(base)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRect(0, 0, w, h), 4, 4)
            if game.exe and os.path.isfile(game.exe):
                icon = QFileIconProvider().icon(QFileInfo(game.exe)).pixmap(32, 32)
                painter.drawPixmap((w - 32) // 2, (h - 32) // 2, icon)
            else:
                initials = "".join(word[0] for word in re.findall(r"\w+", game.name)[:2]).upper()
                painter.setPen(QColor(theme.STORE_COLORS.get(game.store, theme.MUTED)))
                font = painter.font()
                font.setBold(True)
                font.setPixelSize(16)
                painter.setFont(font)
                painter.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, initials)
        painter.end()
        self._icons[key] = pm
        return pm

    # --- actions -----------------------------------------------------------

    def add_game(self) -> None:
        dialog = AddGameDialog(self)
        if not dialog.exec():
            return
        name, exe, args = dialog.values()
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "game"
        game_id, n = f"manual:{slug}", 2
        while game_id in self.cfg["games"] or game_id in self.games:
            game_id, n = f"manual:{slug}-{n}", n + 1
        target = self.cfg["default_target"]
        self.cfg["games"][game_id] = {
            "name": name, "store": "manual", "enabled": True,
            "width": target["width"], "height": target["height"], "refresh": target.get("refresh", 0),
            "watch": [], "launch": {"type": "exe", "path": exe, "args": args, "cwd": os.path.dirname(exe)},
            "install_dir": os.path.dirname(exe),
        }
        self._save_now()
        self.rescan()
        if game_id in self.items:
            self.tree.setCurrentItem(self.items[game_id])

    def remove_manual_game(self, game: Game) -> None:
        """Remove a hand-added game, or one only known because Playnite started it."""
        self.cfg["games"].pop(game.id, None)
        if game.store == "playnite":
            playnite.forget(game.id.split(":", 1)[1])
        self._save_now()
        self.detail.show_game(None)
        self.rescan()

    def remove_all_hooks(self) -> None:
        found = hooks.find(self.steam)
        if not found:
            QMessageBox.information(self, "Remove all hooks", "Nothing is hooked up right now.")
            return
        if found.steam and self.steam.is_running():
            answer = QMessageBox.question(
                self, "Remove all hooks",
                "Steam is running. It has to be closed before its launch options can be changed.\n\nClose Steam now?")
            if answer != QMessageBox.StandardButton.Yes or not self._close_steam_and_wait():
                return
        if found.playnite and playnite.is_running():
            QMessageBox.information(self, "Remove all hooks",
                                    "Playnite is running. Close it first - it saves its settings when it exits.")
            return
        parts = [f"remove QRes from {len(found.steam)} Steam game(s)' launch options",
                 f"delete {len(found.shortcut_files)} game shortcut(s)"]
        if found.playnite:
            parts.append("take QRes's lines out of Playnite's scripts")
        answer = QMessageBox.question(
            self, "Remove all hooks",
            f"This will {', '.join(parts[:-1])} and {parts[-1]}.\n\n"
            "Switching gets turned off for every game; your resolution choices are kept.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            hooks.remove(self.steam, found)
        except Exception as exc:
            QMessageBox.warning(self, "Remove all hooks", str(exc))
            return
        for entry in self.cfg["games"].values():
            entry["enabled"] = False
        self._save_now()
        self._reload_launch_options()
        self.playnite_state = playnite.state(paths.hook_command())
        self.refresh_rows()
        self.statusBar().showMessage("Removed all hooks and turned switching off.", 10000)

    def _close_steam_and_wait(self, timeout: float = 45.0) -> bool:
        self.steam.shutdown()
        self.statusBar().showMessage("Waiting for Steam to exit…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            deadline = time.monotonic() + timeout
            while self.steam.is_running() and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.25)
        finally:
            QApplication.restoreOverrideCursor()
        if self.steam.is_running():
            QMessageBox.warning(self, "Steam", "Steam didn't exit. Close it yourself and try again.")
            return False
        self.steam_running = False
        return True

    def open_settings(self) -> None:
        dialog = SettingsDialog(self, self.cfg, self.modes, on_remove_hooks=self.remove_all_hooks,
                                on_playnite=self.open_playnite,
                                on_check_updates=lambda: self.check_for_updates(wait=True),
                                on_guide=self.open_guide,
                                on_diagnostics=self.open_diagnostics,
                                on_transfer=self.open_transfer)
        if dialog.exec():
            dialog.apply_to(self.cfg)
            self._save_now()
            self._sync_tray()
            if dialog.start_with_windows.isEnabled() and dialog.start_with_windows.isChecked() != autostart.enabled():
                if not autostart.set_enabled(dialog.start_with_windows.isChecked()):
                    QMessageBox.warning(self, "Start with Windows", "Windows wouldn't change the startup entry.")
            self.apply_watch_setting()
            self.refresh_rows()
            failed = self.apply_hotkeys()
            if failed:
                QMessageBox.warning(self, "Hotkeys",
                                    "These shortcuts couldn't be registered (another program may already use "
                                    "them):\n\n  " + "\n  ".join(sorted(failed.values())))
            self._poll_state()

    def _sync_tray(self) -> None:
        """Create or remove the tray icon to match the setting."""
        want = self.cfg.get("tray_icon", True) and Tray.available()
        if want and not self.tray:
            self.tray = Tray(self)
            self.tray.show()
        elif not want and self.tray:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None

    def _needs_guide(self) -> bool:
        """A new install gets the guide once; anyone with games already set up is past it."""
        if self.cfg.get("first_run_done"):
            return False
        if any(entry.get("enabled") for entry in self.cfg["games"].values()):
            self.cfg["first_run_done"] = True
            self._save_now()
            return False
        return True

    def open_guide(self) -> None:
        guide = GettingStarted(self)
        accepted = guide.exec()
        self.cfg["first_run_done"] = True
        if accepted:
            game_id = guide.apply()
            if game_id in self.games:
                entry = self.entry_for(self.games[game_id], create=True)
                target = self.cfg["default_target"]
                entry.update(enabled=True, width=target["width"], height=target["height"],
                             refresh=target.get("refresh", 0))
            self.playnite_state = playnite.state(paths.hook_command())
            self._save_now()
            self.refresh_rows()
            if game_id in self.items:
                self.tree.setCurrentItem(self.items[game_id])
            self._poll_state()
        else:
            self._save_now()

    def open_transfer(self) -> None:
        dialog = TransferDialog(self, self.cfg)
        dialog.exec()
        if dialog.imported:
            # An import can touch every profile, every preset and the hotkeys,
            # so everything that reads them is rebuilt rather than patched.
            self._save_now()
            if dialog.summary and dialog.summary.games_listed_changed:
                # Hand-added games live only in their profiles, so one coming or
                # going changes the list itself; a rescan rebuilds it and
                # reloads whichever game is selected.
                self.rescan()
            else:
                self.refresh_rows()
                # The panel reads a profile when its game is selected, so without
                # this it keeps showing what the import just replaced.
                self.detail.show_game(self.detail.game)
            self._sync_tray()
            self._refresh_presets()
            failed = self.apply_hotkeys()
            if failed:
                QMessageBox.warning(self, "Hotkeys",
                                    "These shortcuts couldn't be registered (another program may "
                                    "already use them):\n\n  " + "\n  ".join(sorted(failed.values())))
            self.statusBar().showMessage("Profiles imported.", 8000)

    def open_diagnostics(self) -> None:
        DiagnosticsDialog(self, self.cfg).exec()

    def open_playnite(self) -> None:
        PlayniteDialog(self).exec()
        self.playnite_state = playnite.state(paths.hook_command())
        self.refresh_rows()

    def restore_desktop(self) -> None:
        active = session.read()
        if active and session.owner_alive(active):
            name = (self.cfg["games"].get(active.get("game_id")) or {}).get("name", "A game")
            answer = QMessageBox.question(
                self, "Game still running",
                f"{name} was started through QRes and is still running. Switch back to the desktop resolution anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        source = (active or {}).get("original") or self.cfg.get("desktop_mode")
        mode = display.Mode.from_dict(source)
        # Put back the screen the record names, and the HDR state with it - this
        # is the button the launcher's own failure notifications point people at,
        # so it has to undo everything a switch did, not just the resolution.
        device = (active or {}).get("device") or None
        want_hdr = (active or {}).get("original_hdr")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            how = display.set_mode(mode, display.find_qres(self.cfg.get("qres_path")),
                                   self.cfg.get("temporary", True), device)
        except display.DisplayError as exc:
            QMessageBox.warning(self, "Restore desktop resolution", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        hdr_note = ""
        if want_hdr is not None:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                if hdr.set_enabled(bool(want_hdr), device):
                    hdr_note = f"  HDR turned back {'on' if want_hdr else 'off'}."
            except Exception as exc:  # the resolution is already back; don't undo that over HDR
                hdr_note = f"  HDR couldn't be put back: {exc}"
            finally:
                QApplication.restoreOverrideCursor()
        if active and not session.owner_alive(active):
            session.clear()
            self._run_after_commands(active)
        self.statusBar().showMessage(f"Switched to {mode} ({how}).{hdr_note}", 8000)
        self._poll_state()

    def _run_after_commands(self, record: dict) -> None:
        """Run a finished switch's "after" commands without holding up the window."""
        after = record.get("after") or []
        if after:
            game_id = record.get("game_id") or ""
            name = (self.cfg["games"].get(game_id) or {}).get("name") or game_id
            threading.Thread(target=commands.run_all, args=(after, commands.AFTER, game_id, name),
                             daemon=True).start()

    def _ensure_qres(self) -> None:
        if display.find_qres(self.cfg.get("qres_path")):
            return
        answer = QMessageBox.question(
            self, "QRes not found",
            "QRes.exe isn't on your PATH or next to QRes GUI, and no location is set.\n\n"
            "Without it, resolutions are changed through Windows directly instead. Locate QRes.exe now?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Locate QRes.exe", "", "QRes (QRes.exe);;Programs (*.exe)")
        if path:
            self.cfg["qres_path"] = os.path.normpath(path)
            self._save_now()
            self.statusBar().showMessage(f"Using {self.cfg['qres_path']}", 8000)

    def _check_leftover_session(self) -> None:
        active = session.read()
        if not active or session.owner_alive(active):
            return
        original = display.Mode.from_dict(active["original"])
        # Against the screen the record names. Reading the primary instead would
        # compare two different displays, and on a chance match would clear the
        # record - stranding the other screen with nothing left to restore from.
        device = active.get("device") or None
        try:
            current = display.current_mode(device)
        except display.DisplayError:
            current = None  # unplugged since; offer the restore rather than drop the record
        if current == original:
            session.clear()
            self._run_after_commands(active)   # the display came back; what was due after it still is
            return
        where = f" on Display {display.device_number(device)}" if device else ""
        answer = QMessageBox.question(
            self, "Resolution wasn't restored",
            f"A game launched through QRes didn't switch the display back{where}.\n\n"
            f"Current: {current if current else 'not connected'}\nDesktop: {original}\n\n"
            f"Switch back now?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.restore_desktop()
        else:
            session.clear()

    def _poll_state(self) -> None:
        self._refresh_events()
        self._refresh_played()
        self._pick_up_playnite_games()
        try:
            current = display.current_mode()
        except display.DisplayError:
            return
        self.desktop_label.setText(str(current))
        self._update_preset_highlight()
        self.refresh_tray()
        desktop = self.cfg.get("desktop_mode")
        self.restore_btn.setEnabled(bool(desktop) and display.Mode.from_dict(desktop) != current)

        active = session.read()
        if active and session.owner_alive(active):
            name = (self.cfg["games"].get(active.get("game_id")) or {}).get("name", "a game")
            theme.set_state(self.session_label, "ok", f"●  Running {name} through QRes")
        else:
            self.session_label.setText("")

        if self.steam.available:
            running = self.steam.is_running()
            if running != self.steam_running:
                self.steam_running = running
                if not running:
                    # Steam rewrites localconfig.vdf on exit; pick up what it saved.
                    self._reload_launch_options()
                    self.refresh_rows()                # its last-played times come with it
                self._update_sync_button()
                self.detail.refresh_integration()
