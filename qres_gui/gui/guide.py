"""Getting started: a short guide for a new install, reachable later from Settings."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import display, paths, playnite
from . import theme

PAGES = ("Welcome", "QRes", "Resolutions", "Your launchers", "Pick a game")


def _text(text: str, muted: bool = False) -> QLabel:
    label = QLabel(text, wordWrap=True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setOpenExternalLinks(True)
    if muted:
        label.setObjectName("muted")
    return label


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-size: 18px; font-weight: 700;")
    return label


class GettingStarted(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Getting started")
        self.setMinimumSize(640, 460)

        self.step = QLabel(objectName="caption")
        self.pages = QStackedWidget()
        for build in (self._welcome, self._qres, self._resolutions, self._launchers, self._pick):
            self.pages.addWidget(build())

        self.back_btn = QPushButton("Back", clicked=lambda: self._go(-1))
        self.next_btn = QPushButton("Next", objectName="primary", clicked=self._next)
        self.skip_btn = QPushButton("Skip the guide", clicked=self.reject)
        nav = QHBoxLayout()
        nav.addWidget(self.skip_btn)
        nav.addStretch()
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(self.step)
        layout.addWidget(self.pages, 1)
        layout.addLayout(nav)
        self._go(0)

    # --- pages --------------------------------------------------------------

    def _page(self, title: str, *widgets) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(_heading(title))
        for widget in widgets:
            if isinstance(widget, QWidget):
                layout.addWidget(widget)
            else:
                layout.addLayout(widget)
        layout.addStretch()
        return page

    def _welcome(self) -> QWidget:
        return self._page(
            "Welcome to QRes GUI",
            _text("Some games only look right when the <i>desktop</i> is at a particular resolution, "
                  "say 2560 × 1440 on a 3440 × 1440 ultrawide, and don't let you choose it themselves."),
            _text("QRes GUI switches Windows to that resolution while such a game runs, and back again "
                  "when it closes:"),
            _text("•&nbsp; You pick the games and their resolution.<br>"
                  "•&nbsp; It uses QRes to switch your <b>primary display</b> (other monitors are left alone).<br>"
                  "•&nbsp; Switches aren't saved to Windows, so even a crash or reboot comes back at "
                  "your normal resolution."),
            _text("This takes about a minute. You can reopen it from <b>Settings › Getting started</b>.",
                  muted=True),
        )

    def _qres(self) -> QWidget:
        self.qres_path = QLineEdit(self.win.cfg.get("qres_path") or display.find_qres() or "",
                                   placeholderText="Path to QRes.exe")
        self.qres_path.textChanged.connect(self._refresh_qres)
        browse = QPushButton("Browse…", clicked=self._browse_qres)
        row = QHBoxLayout()
        row.addWidget(self.qres_path, 1)
        row.addWidget(browse)
        self.qres_status = QLabel(wordWrap=True)
        self._refresh_qres()
        return self._page(
            "Where's QRes?",
            _text("QRes (<code>QRes.exe</code> v1.1 by Anders Kjersem) does the actual switching. It isn't "
                  "included with QRes GUI; download it separately and point QRes GUI at it, or copy it "
                  "into QRes GUI's install folder."),
            row,
            self.qres_status,
        )

    def _resolutions(self) -> QWidget:
        current = display.current_mode()
        self.desktop = QComboBox()
        for mode in self.win.modes:
            self.desktop.addItem(str(mode), mode)
        saved = self.win.cfg.get("desktop_mode")
        wanted = display.Mode.from_dict(saved) if saved else current
        self.desktop.setCurrentIndex(max(self.desktop.findText(str(wanted)), 0))

        self.target = QComboBox()
        for w, h in dict.fromkeys((m.width, m.height) for m in self.win.modes):
            self.target.addItem(f"{w} × {h}", f"{w}x{h}")
        target = self.win.cfg.get("default_target", {})
        self.target.setCurrentIndex(max(self.target.findData(f"{target.get('width')}x{target.get('height')}"), 0))

        form = QFormLayout()
        form.addRow("Your desktop", self.desktop)
        form.addRow("Games switch to", self.target)
        return self._page(
            "Resolutions",
            _text("Your primary display's normal resolution is what QRes GUI always switches back to. "
                  "Games you set up switch to the resolution below; you can change it for each game."),
            form,
            _text("Refresh rate stays the same as your desktop unless you choose otherwise for a game.",
                  muted=True),
        )

    def _launchers(self) -> QWidget:
        steam_found = bool(getattr(self.win.steam, "available", False))
        steam = _text(("<b>Steam</b> ✓ found. When you set up a Steam game, QRes GUI adds itself to "
                       "that game's launch options (Steam needs to be closed while it does).")
                      if steam_found else "<b>Steam</b> wasn't found.")
        self.playnite_status = QLabel(wordWrap=True)
        self.playnite_btn = QPushButton("Add QRes to Playnite", objectName="primary", clicked=self._add_playnite)
        playnite_row = QHBoxLayout()
        playnite_row.addWidget(self.playnite_btn)
        playnite_row.addStretch()
        self._refresh_playnite()
        return self._page(
            "How do you start your games?",
            steam,
            _text("<b>Playnite</b>: with QRes added to Playnite's game scripts, any game you start from "
                  "Playnite switches, whatever store it's from."),
            self.playnite_status,
            playnite_row,
            _text("<b>Everything else</b> (GOG, Epic, EA, Xbox, …): QRes GUI makes a desktop or Start "
                  "menu shortcut that switches, then starts the game. Use it instead of the store's "
                  "Play button."),
        )

    def _pick(self) -> QWidget:
        self.search = QLineEdit(placeholderText="Search your games…", clearButtonEnabled=True)
        self.search.textChanged.connect(self._filter_games)
        self.game_list = QListWidget()
        for game in sorted(self.win.games.values(), key=lambda g: g.name.casefold()):
            item = QListWidgetItem(f"{game.name}    ·    {game.store_label}")
            item.setData(Qt.ItemDataRole.UserRole, game.id)
            self.game_list.addItem(item)
        return self._page(
            "Pick a game to start with",
            _text("Choose a game that needs a different desktop resolution. It'll switch to the "
                  "resolution you picked, and QRes GUI opens it so you can finish hooking it up. "
                  "Or just click Finish and pick games later."),
            self.search,
            self.game_list,
        )

    # --- behaviour -------------------------------------------------------------

    def _refresh_qres(self) -> None:
        path = self.qres_path.text().strip()
        if path and os.path.isfile(path):
            theme.set_state(self.qres_status, "ok", "✓  Found QRes.")
        elif path:
            theme.set_state(self.qres_status, "warn", "There's no file at that path.")
        else:
            theme.set_state(self.qres_status, "warn",
                            "QRes wasn't found. You can carry on: until it's set, QRes GUI switches "
                            "through Windows directly.")

    def _browse_qres(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Locate QRes.exe", "", "QRes (QRes.exe);;Programs (*.exe)")
        if path:
            self.qres_path.setText(os.path.normpath(path))

    def _refresh_playnite(self) -> None:
        state = playnite.state(paths.launcher_command())
        running = playnite.is_running()
        self.playnite_btn.setVisible(state in ("none", "outdated"))
        self.playnite_btn.setEnabled(not running)
        if state == "missing":
            theme.set_state(self.playnite_status, "off", "Playnite wasn't found on this PC.")
        elif state == "installed":
            theme.set_state(self.playnite_status, "ok", "✓  QRes is already in Playnite's scripts.")
        elif running:
            theme.set_state(self.playnite_status, "warn",
                            "Playnite is running. Close it to add QRes (it saves its settings on exit).")
        else:
            theme.set_state(self.playnite_status, "off", "Playnite found.")

    def _add_playnite(self) -> None:
        try:
            playnite.install(paths.launcher_command())
        except Exception as exc:
            QMessageBox.warning(self, "Playnite", str(exc))
        self._refresh_playnite()

    def _filter_games(self) -> None:
        needle = self.search.text().strip().casefold()
        for i in range(self.game_list.count()):
            item = self.game_list.item(i)
            item.setHidden(bool(needle) and needle not in item.text().casefold())

    def _go(self, delta: int) -> None:
        index = max(0, min(self.pages.count() - 1, self.pages.currentIndex() + delta))
        self.pages.setCurrentIndex(index)
        self.step.setText(f"Step {index + 1} of {self.pages.count()}  ·  {PAGES[index]}")
        self.back_btn.setEnabled(index > 0)
        last = index == self.pages.count() - 1
        self.next_btn.setText("Finish" if last else "Next")
        if PAGES[index] == "Your launchers":
            self._refresh_playnite()

    def _next(self) -> None:
        if self.pages.currentIndex() == self.pages.count() - 1:
            self.accept()
        else:
            self._go(1)

    def chosen_game(self) -> str | None:
        item = self.game_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item and not item.isHidden() else None

    def apply(self) -> str | None:
        """Save the choices; returns the game picked on the last page, if any."""
        cfg = self.win.cfg
        cfg["qres_path"] = self.qres_path.text().strip()
        cfg["desktop_mode"] = self.desktop.currentData().to_dict()
        w, h = (int(x) for x in self.target.currentData().split("x"))
        cfg["default_target"] = {"width": w, "height": h, "refresh": 0}
        return self.chosen_game()
