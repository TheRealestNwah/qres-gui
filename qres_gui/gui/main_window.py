from __future__ import annotations

import html
import os
import re
import time
from pathlib import Path

from PySide6.QtCore import QFileInfo, QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFileIconProvider, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QSplitter, QStatusBar, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import __version__, config, display, hooks, notify, paths, session, shortcuts
from ..stores import STORE_LABELS, Game, SteamClient, detect_all, steam
from . import theme
from .detail_panel import DetailPanel
from .dialogs import AddGameDialog, SettingsDialog

ICON_SIZE = QSize(92, 43)
ROLE_ID = Qt.ItemDataRole.UserRole


class GameItem(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        return self.text(column).casefold() < other.text(column).casefold()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"QRes GUI {__version__}")
        self.resize(1360, 840)
        self.cfg = config.load()
        self.steam = SteamClient()
        self.steam_running = self.steam.available and self.steam.is_running()
        self.modes = display.list_modes()
        self.games: dict[str, Game] = {}
        self.items: dict[str, GameItem] = {}
        self.launch_opts: dict[str, str] = {}
        self._icons: dict[str, QPixmap] = {}
        self._save_timer = QTimer(self, singleShot=True, interval=400, timeout=self._save_now)

        self._init_defaults()
        self._build_ui()
        self.rescan()
        self._poll_state()
        self._poll = QTimer(self, interval=2500, timeout=self._poll_state)
        self._poll.start()
        QTimer.singleShot(300, self._check_leftover_session)
        QTimer.singleShot(500, self._ensure_qres)

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
        col.addWidget(QLabel("Desktop resolution", objectName="caption"))
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
        self.store_filter = QComboBox()
        self.store_filter.currentIndexChanged.connect(self._apply_filter)
        self.only_configured = QCheckBox("Configured only")
        self.only_configured.toggled.connect(self._apply_filter)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.store_filter)
        filters.addWidget(self.only_configured)
        lv.addLayout(filters)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Game", "Store", "Resolution", "Launch hook"])
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(ICON_SIZE)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(self._on_select)
        lv.addWidget(self.tree, 1)
        self.summary = QLabel(objectName="muted")
        lv.addWidget(self.summary)

        self.detail = DetailPanel(self)
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([780, 560])

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(14, 12, 14, 8)
        bl.addWidget(splitter)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(top)
        cl.addWidget(self._build_event_bar())
        cl.addWidget(body, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

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
        # Keep saved launch targets in step with what the stores report now.
        for gid, entry in self.cfg["games"].items():
            game = self.games.get(gid)
            if game and game.store != "manual":
                entry["launch"], entry["name"] = game.launch, game.name
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
        except (OSError, ValueError) as exc:
            self.launch_opts = {}
            self.statusBar().showMessage(f"Couldn't read Steam launch options: {exc}", 10000)

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
        }

    def save(self) -> None:
        self._save_timer.start()

    def _save_now(self) -> None:
        config.save(self.cfg)

    def closeEvent(self, event) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_now()
        super().closeEvent(event)

    # --- Steam helpers used by the detail panel ------------------------------

    def steam_prefix(self, game_id: str) -> str:
        return steam.launch_prefix(paths.launcher_command(), game_id)

    def steam_state(self, game: Game) -> str:
        appid = game.id.split(":", 1)[1]
        return steam.option_state(self.launch_opts.get(appid, ""), self.steam_prefix(game.id))

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
        item.setText(0, game.name)
        item.setText(1, game.store_label)
        item.setForeground(1, QBrush(QColor(theme.STORE_COLORS.get(game.store, theme.MUTED))))
        item.setText(2, f"{entry['width']} × {entry['height']}" if enabled else "—")
        item.setForeground(2, QBrush(QColor("#e4e6ea" if enabled else theme.MUTED)))
        text, kind = self.hook_status(game, entry)
        item.setText(3, text)
        color = {"ok": theme.OK, "warn": theme.WARN}.get(kind, theme.MUTED)
        item.setForeground(3, QBrush(QColor(color)))

    def hook_status(self, game: Game, entry: dict | None) -> tuple[str, str]:
        enabled = bool(entry and entry.get("enabled"))
        if game.store == "steam":
            state = self.steam_state(game)
            if state == "applied":
                return ("Steam launch options", "ok") if enabled else ("Launch options (switching off)", "off")
            if state == "outdated":
                return "Launch options need updating", "warn"
            return ("Launch options not set", "warn") if enabled else ("—", "off")
        found = shortcuts.existing(game.name)
        if found:
            where = " + ".join("Desktop" if p.parent == shortcuts.desktop_dir() else "Start menu" for p in found)
            return f"Shortcut: {where}", "ok" if enabled else "off"
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
        shown = 0
        for gid, item in self.items.items():
            game = self.games[gid]
            entry = self.cfg["games"].get(gid)
            visible = (
                (not needle or needle in game.name.casefold())
                and (store is None or game.store == store)
                and (not only or bool(entry and entry.get("enabled")))
            )
            item.setHidden(not visible)
            shown += visible
        enabled = sum(1 for g in self.games if (self.cfg["games"].get(g) or {}).get("enabled"))
        self.summary.setText(f"{shown} of {len(self.items)} games shown · {enabled} switch resolution")

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
        }
        self._save_now()
        self.rescan()
        if game_id in self.items:
            self.tree.setCurrentItem(self.items[game_id])

    def remove_manual_game(self, game: Game) -> None:
        self.cfg["games"].pop(game.id, None)
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
        answer = QMessageBox.question(
            self, "Remove all hooks",
            f"Remove QRes from {len(found.steam)} Steam game(s)' launch options and delete "
            f"{len(found.shortcut_files)} game shortcut(s)?\n\n"
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
        dialog = SettingsDialog(self, self.cfg, self.modes, on_remove_hooks=self.remove_all_hooks)
        if dialog.exec():
            dialog.apply_to(self.cfg)
            self._save_now()
            self._poll_state()

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
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            how = display.set_mode(mode, display.find_qres(self.cfg.get("qres_path")), self.cfg.get("temporary", True))
        except display.DisplayError as exc:
            QMessageBox.warning(self, "Restore desktop resolution", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        if active and not session.owner_alive(active):
            session.clear()
        self.statusBar().showMessage(f"Switched to {mode} ({how}).", 6000)
        self._poll_state()

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
        if display.current_mode() == original:
            session.clear()
            return
        answer = QMessageBox.question(
            self, "Resolution wasn't restored",
            f"A game launched through QRes didn't switch the display back.\n\n"
            f"Current: {display.current_mode()}\nDesktop: {original}\n\nSwitch back now?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.restore_desktop()
        else:
            session.clear()

    def _poll_state(self) -> None:
        self._refresh_events()
        try:
            current = display.current_mode()
        except display.DisplayError:
            return
        self.desktop_label.setText(str(current))
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
                    self.refresh_rows()
                self._update_sync_button()
                self.detail.refresh_integration()
