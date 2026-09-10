"""Right-hand panel: one game's resolution profile and how it gets launched."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import display, paths, shortcuts
from ..stores import Game, steam
from . import theme
from .dialogs import TestResolutionDialog

DETACHED_PROCESS = 0x00000008
BANNER_WIDTH = 460


def _row(*widgets, stretch_after: int | None = None) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    for i, widget in enumerate(widgets):
        layout.addWidget(widget)
        if stretch_after is not None and i == stretch_after:
            layout.addStretch()
    if stretch_after is None:
        layout.addStretch()
    return layout


def _muted(text: str = "") -> QLabel:
    label = QLabel(text, objectName="muted", wordWrap=True)
    return label


class DetailPanel(QScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.game: Game | None = None
        self._loading = False
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(460)

        container = QWidget()
        self.setWidget(container)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(12, 0, 6, 0)
        self.placeholder = QLabel("Select a game to set up its resolution.", objectName="muted",
                                  alignment=Qt.AlignmentFlag.AlignCenter)
        self.content = QWidget()
        outer.addWidget(self.placeholder, 1)
        outer.addWidget(self.content)
        outer.addStretch()
        self._build()
        self.content.hide()

    # --- layout ------------------------------------------------------------

    def _build(self) -> None:
        v = QVBoxLayout(self.content)
        v.setContentsMargins(0, 0, 0, 12)
        v.setSpacing(6)

        self.banner = QLabel()
        v.addWidget(self.banner)
        self.title = QLabel(objectName="title", wordWrap=True)
        v.addWidget(self.title)
        self.meta = _muted()
        self.meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_folder = QPushButton("Open folder", clicked=self._open_folder)
        meta_row = QHBoxLayout()
        meta_row.addWidget(self.meta, 1)
        meta_row.addWidget(self.open_folder, alignment=Qt.AlignmentFlag.AlignTop)
        v.addLayout(meta_row)

        # Resolution profile
        box = QGroupBox("Resolution")
        layout = QVBoxLayout(box)
        self.enabled = QCheckBox("Switch resolution when this game launches")
        self.enabled.setStyleSheet("font-weight: 600;")
        self.enabled.toggled.connect(self._on_enabled)
        layout.addWidget(self.enabled)
        form = QFormLayout()
        self.res_combo = QComboBox()
        self.res_combo.currentIndexChanged.connect(self._on_resolution)
        self.rate_combo = QComboBox()
        self.rate_combo.currentIndexChanged.connect(self._on_rate)
        form.addRow("Resolution", self.res_combo)
        form.addRow("Refresh rate", self.rate_combo)
        layout.addLayout(form)
        self.test_btn = QPushButton("Test for 10 seconds", clicked=self._test)
        layout.addLayout(_row(self.test_btn, _muted("Switches, then comes back on its own.")))
        v.addWidget(box)

        # Steam
        self.steam_box = QGroupBox("Steam launch options")
        layout = QVBoxLayout(self.steam_box)
        self.steam_status = QLabel(wordWrap=True)
        layout.addWidget(self.steam_status)
        form = QFormLayout()
        self.steam_current = QLineEdit(readOnly=True, placeholderText="(none)")
        self.steam_new = QLineEdit(readOnly=True)
        form.addRow("Now", self.steam_current)
        form.addRow("With QRes", self.steam_new)
        layout.addLayout(form)
        self.steam_apply = QPushButton("Apply to Steam", objectName="primary", clicked=self._steam_apply)
        self.steam_copy = QPushButton("Copy", clicked=self._steam_copy)
        self.steam_remove = QPushButton("Remove", clicked=self._steam_remove)
        self.steam_close = QPushButton("Close Steam", clicked=self._steam_close)
        self.steam_play = QPushButton("Play", clicked=self._steam_play)
        layout.addLayout(_row(self.steam_apply, self.steam_copy, self.steam_remove, self.steam_close,
                              self.steam_play, stretch_after=3))
        self.steam_hint = _muted()
        layout.addWidget(self.steam_hint)
        v.addWidget(self.steam_box)

        # Shortcuts, for every other store
        self.shortcut_box = QGroupBox("Launching")
        layout = QVBoxLayout(self.shortcut_box)
        self.target_label = _muted()
        self.target_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.target_label)
        self.manual_form = QWidget()
        mform = QFormLayout(self.manual_form)
        mform.setContentsMargins(0, 0, 0, 0)
        self.manual_exe = QLineEdit()
        self.manual_exe.editingFinished.connect(self._on_manual_target)
        self.manual_args = QLineEdit(placeholderText="Optional")
        self.manual_args.editingFinished.connect(self._on_manual_target)
        exe_row = QHBoxLayout()
        exe_row.addWidget(self.manual_exe, 1)
        exe_row.addWidget(QPushButton("Browse…", clicked=self._browse_manual_exe))
        mform.addRow("Executable", exe_row)
        mform.addRow("Arguments", self.manual_args)
        layout.addWidget(self.manual_form)
        self.shortcut_status = QLabel(wordWrap=True)
        layout.addWidget(self.shortcut_status)
        self.desktop_btn = QPushButton("Create desktop shortcut", objectName="primary",
                                       clicked=lambda: self._create_shortcut(shortcuts.desktop_dir()))
        self.startmenu_btn = QPushButton("Add to Start menu",
                                         clicked=lambda: self._create_shortcut(shortcuts.start_menu_dir()))
        self.remove_shortcuts_btn = QPushButton("Remove shortcuts", clicked=self._remove_shortcuts)
        self.play_btn = QPushButton("Play", clicked=self._play)
        layout.addLayout(_row(self.desktop_btn, self.startmenu_btn, self.remove_shortcuts_btn, self.play_btn,
                              stretch_after=2))
        self.shortcut_hint = _muted()
        layout.addWidget(self.shortcut_hint)
        v.addWidget(self.shortcut_box)

        # Process tracking
        box = QGroupBox("Game process")
        layout = QVBoxLayout(box)
        self.watch = QLineEdit(placeholderText="e.g. Game-Win64-Shipping.exe")
        self.watch.editingFinished.connect(self._on_watch)
        pick = QPushButton("Choose exe…", clicked=self._pick_watch_exe)
        row = QHBoxLayout()
        row.addWidget(self.watch, 1)
        row.addWidget(pick)
        layout.addLayout(row)
        self.watch_hint = _muted()
        layout.addWidget(self.watch_hint)
        v.addWidget(box)

        self.remove_btn = QPushButton("Remove from list", clicked=lambda: self.win.remove_manual_game(self.game))
        v.addLayout(_row(self.remove_btn))

    # --- showing a game ----------------------------------------------------

    def show_game(self, game: Game | None) -> None:
        self.game = game
        if game is None:
            self.content.hide()
            self.placeholder.show()
            return
        self._loading = True
        entry = self._entry(create=False)

        image = QPixmap(game.image) if game.image else QPixmap()
        if image.isNull():
            self.banner.hide()
        else:
            self.banner.setPixmap(image.scaledToWidth(BANNER_WIDTH, Qt.TransformationMode.SmoothTransformation))
            self.banner.show()
        self.title.setText(game.name)
        ident = game.id.split(":", 1)[1]
        meta = [game.store_label] + ([f"ID {ident}"] if game.store != "manual" else [])
        if game.install_dir:
            meta.append(game.install_dir)
        self.meta.setText("  ·  ".join(meta))
        self.open_folder.setEnabled(bool(game.install_dir) and os.path.isdir(game.install_dir))

        self.enabled.setChecked(bool(entry.get("enabled")))
        self._fill_resolutions(entry["width"], entry["height"])
        self._fill_rates(entry["width"], entry["height"], entry.get("refresh", 0))
        self.watch.setText(", ".join(entry.get("watch", [])))

        is_steam, is_manual = game.store == "steam", game.store == "manual"
        self.steam_box.setVisible(is_steam)
        self.shortcut_box.setVisible(not is_steam)
        self.manual_form.setVisible(is_manual)
        self.remove_btn.setVisible(is_manual)
        if is_manual:
            launch = entry.get("launch") or {}
            self.manual_exe.setText(launch.get("path", ""))
            self.manual_args.setText(launch.get("args", ""))
        self._loading = False

        self.placeholder.hide()
        self.content.show()
        self.refresh_integration()
        self.verticalScrollBar().setValue(0)

    def _entry(self, create: bool = True) -> dict:
        entry = self.win.entry_for(self.game, create=create)
        return entry if entry is not None else self.win.default_entry(self.game)

    def _fill_resolutions(self, width: int, height: int) -> None:
        self.res_combo.blockSignals(True)
        self.res_combo.clear()
        sizes = list(dict.fromkeys((m.width, m.height) for m in self.win.modes))
        if (width, height) not in sizes:
            sizes.append((width, height))
        desktop = display.current_mode()
        for w, h in sizes:
            label = f"{w} × {h}"
            if (w, h) == (desktop.width, desktop.height):
                label += "   (current)"
            self.res_combo.addItem(label, f"{w}x{h}")
        self.res_combo.setCurrentIndex(max(self.res_combo.findData(f"{width}x{height}"), 0))
        self.res_combo.blockSignals(False)

    def _fill_rates(self, width: int, height: int, selected: int) -> None:
        self.rate_combo.blockSignals(True)
        self.rate_combo.clear()
        rates = display.refresh_rates(width, height, self.win.modes)
        desktop = self.win.cfg.get("desktop_mode") or display.current_mode().to_dict()
        desktop_rate = int(desktop.get("refresh", 0))
        if desktop_rate in rates or not rates:
            self.rate_combo.addItem(f"Same as desktop ({desktop_rate} Hz)", 0)
        else:
            self.rate_combo.addItem(f"Highest available ({rates[0]} Hz)", 0)
        for rate in rates:
            self.rate_combo.addItem(f"{rate} Hz", rate)
        self.rate_combo.setCurrentIndex(max(self.rate_combo.findData(selected), 0))
        self.rate_combo.blockSignals(False)

    # --- profile edits -----------------------------------------------------

    def _changed(self) -> None:
        self.win.save()
        self.win.refresh_rows(self.game.id)

    def _on_enabled(self, checked: bool) -> None:
        if self._loading or not self.game:
            return
        self._entry()["enabled"] = checked
        self._changed()

    def _on_resolution(self) -> None:
        if self._loading or not self.game:
            return
        w, h = (int(x) for x in self.res_combo.currentData().split("x"))
        entry = self._entry()
        entry["width"], entry["height"] = w, h
        if entry.get("refresh") and entry["refresh"] not in display.refresh_rates(w, h, self.win.modes):
            entry["refresh"] = 0
        self._fill_rates(w, h, entry.get("refresh", 0))
        self._changed()

    def _on_rate(self) -> None:
        if self._loading or not self.game:
            return
        self._entry()["refresh"] = int(self.rate_combo.currentData() or 0)
        self._changed()

    def _on_watch(self) -> None:
        if self._loading or not self.game:
            return
        names = [n.strip() for n in self.watch.text().replace(";", ",").split(",") if n.strip()]
        names = [n if n.lower().endswith(".exe") else n + ".exe" for n in names]
        entry = self._entry()
        if names != entry.get("watch", []):
            entry["watch"] = names
            self.watch.setText(", ".join(names))
            self._changed()

    def _pick_watch_exe(self) -> None:
        start = self.game.install_dir or ""
        path, _ = QFileDialog.getOpenFileName(self, "Choose the game's executable", start, "Programs (*.exe)")
        if not path:
            return
        entry = self._entry()
        name = Path(path).name
        if name.lower() not in (n.lower() for n in entry.get("watch", [])):
            entry["watch"] = entry.get("watch", []) + [name]
        self.watch.setText(", ".join(entry["watch"]))
        self._changed()

    def _on_manual_target(self) -> None:
        if self._loading or not self.game:
            return
        exe = self.manual_exe.text().strip()
        entry = self._entry()
        entry["launch"] = {"type": "exe", "path": exe, "args": self.manual_args.text().strip(),
                           "cwd": os.path.dirname(exe)}
        self.game.launch, self.game.exe = entry["launch"], exe
        self._changed()

    def _browse_manual_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose the game's executable",
                                              os.path.dirname(self.manual_exe.text()), "Programs (*.exe)")
        if path:
            self.manual_exe.setText(os.path.normpath(path))
            self._on_manual_target()

    def _ensure_enabled(self) -> dict:
        """Hooking a game up implies switching should be on."""
        entry = self._entry()
        if not entry.get("enabled"):
            entry["enabled"] = True
            self._loading = True
            self.enabled.setChecked(True)
            self._loading = False
        if not entry.get("launch"):
            entry["launch"] = self.game.launch
        self.win._save_now()
        return entry

    def _test(self) -> None:
        entry = self._entry(create=False)
        desktop = display.Mode.from_dict(self.win.cfg.get("desktop_mode") or display.current_mode().to_dict())
        target = display.resolve(entry["width"], entry["height"], entry.get("refresh", 0), desktop)
        if target == display.current_mode():
            QMessageBox.information(self, "Test resolution", f"The display is already at {target}.")
            return
        TestResolutionDialog(self, target, display.find_qres(self.win.cfg.get("qres_path")),
                             bool(self.win.cfg.get("temporary", True))).exec()
        self.win._poll_state()

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.game.install_dir))

    # --- integration state -------------------------------------------------

    def refresh_integration(self) -> None:
        if not self.game:
            return
        entry = self._entry(create=False)
        enabled = bool(entry.get("enabled"))
        watch_needed = self.game.needs_watch and not entry.get("watch")
        if self.game.store == "steam":
            self._refresh_steam(enabled)
        else:
            self._refresh_shortcuts(entry, enabled, watch_needed)

        if self.game.needs_watch:
            text = (f"Required: {self.game.store_label} starts the game itself, so QRes needs the game's "
                    "process name to know when it has closed.")
            if self.game.exe and entry.get("watch"):
                text += f" Detected: {Path(self.game.exe).name}."
            self.watch_hint.setText(text)
            self.watch_hint.setStyleSheet(f"color: {theme.WARN};" if watch_needed else "")
        else:
            self.watch_hint.setText(
                "Optional. QRes normally waits until the game and everything it started have exited. "
                "If a launcher stays open after you quit, or the game hands off to another exe, "
                "name the real game exe here and QRes will wait for that instead.")
            self.watch_hint.setStyleSheet("")

    def _refresh_steam(self, enabled: bool) -> None:
        appid = self.game.id.split(":", 1)[1]
        current = self.win.launch_opts.get(appid, "")
        prefix = self.win.steam_prefix(self.game.id)
        state = steam.option_state(current, prefix)
        running = self.win.steam_running
        for field, text in ((self.steam_current, current), (self.steam_new, steam.apply_ours(current, prefix))):
            field.setText(text)
            field.setToolTip(text)
            field.setCursorPosition(0)

        if state == "applied":
            theme.set_state(self.steam_status, "ok" if enabled else "off",
                            "✓  Steam starts this game through QRes." if enabled else
                            "Steam starts this game through QRes, but switching is off, so nothing changes.")
        elif state == "outdated":
            theme.set_state(self.steam_status, "warn",
                            "The launch options point at an older QRes launcher location. Update them.")
        elif enabled:
            theme.set_state(self.steam_status, "warn",
                            "Not hooked up yet: Steam will start the game without switching.")
        else:
            theme.set_state(self.steam_status, "off", "Turn on switching above, then apply to Steam.")

        self.steam_apply.setText("Update in Steam" if state == "outdated" else "Apply to Steam")
        self.steam_apply.setEnabled(not running and state != "applied")
        self.steam_remove.setEnabled(not running and state != "none")
        self.steam_close.setVisible(running)
        if running:
            self.steam_hint.setText(
                "Steam is running, and it overwrites its settings file when it exits, so close it before "
                "applying. Or use Copy and paste the options into Steam › right-click the game › "
                "Properties › General › Launch options.")
        else:
            self.steam_hint.setText("Steam is closed, so the change can be written directly. "
                                    "Your existing launch options are kept.")

    def _refresh_shortcuts(self, entry: dict, enabled: bool, watch_needed: bool) -> None:
        launch = entry.get("launch") or self.game.launch or {}
        if launch.get("type") == "exe":
            self.target_label.setText(f"Starts  {launch.get('path', '')}  {launch.get('args', '')}".rstrip())
        elif launch.get("type") == "uri":
            self.target_label.setText(f"Starts through {self.game.store_label}  ({launch['uri']})")
        else:
            self.target_label.setText("No launch target.")
        self.target_label.setVisible(self.game.store != "manual")

        found = shortcuts.existing(self.game.name)
        if watch_needed:
            theme.set_state(self.shortcut_status, "warn", "Set the game process below before creating a shortcut.")
        elif found:
            where = " and ".join("on the Desktop" if p.parent == shortcuts.desktop_dir() else "in the Start menu"
                                 for p in found)
            theme.set_state(self.shortcut_status, "ok" if enabled else "off", f"✓  Shortcut {where}.")
        elif enabled:
            theme.set_state(self.shortcut_status, "warn", "No shortcut yet.")
        else:
            theme.set_state(self.shortcut_status, "off", "Turn on switching above, then create a shortcut.")

        has_target = bool(launch) and (launch.get("type") != "exe" or os.path.isfile(launch.get("path", "")))
        for button in (self.desktop_btn, self.startmenu_btn, self.play_btn):
            button.setEnabled(has_target and not watch_needed)
        self.remove_shortcuts_btn.setVisible(bool(found))
        self.shortcut_hint.setText(
            f"Start the game from this shortcut (or Play) instead of from {self.game.store_label} directly - "
            "that's what switches the resolution." if self.game.store != "manual" else
            "Start the game from this shortcut (or Play) so the resolution switches.")

    # --- actions -----------------------------------------------------------

    def _steam_apply(self) -> None:
        self._ensure_enabled()
        appid = self.game.id.split(":", 1)[1]
        current = self.win.launch_opts.get(appid, "")
        self.win.write_steam_options({appid: steam.apply_ours(current, self.win.steam_prefix(self.game.id))})

    def _steam_remove(self) -> None:
        appid = self.game.id.split(":", 1)[1]
        remaining, _ = steam.strip_ours(self.win.launch_opts.get(appid, ""))
        self.win.write_steam_options({appid: remaining})

    def _steam_copy(self) -> None:
        self._ensure_enabled()
        self.win.refresh_rows(self.game.id)
        QGuiApplication.clipboard().setText(self.steam_new.text())
        self.win.statusBar().showMessage(
            "Copied. In Steam: right-click the game › Properties › General › Launch options, and paste.", 10000)

    def _steam_close(self) -> None:
        self.win.steam.shutdown()
        self.win.statusBar().showMessage("Asking Steam to exit…", 8000)

    def _steam_play(self) -> None:
        os.startfile(f"steam://rungameid/{self.game.id.split(':', 1)[1]}")

    def _create_shortcut(self, folder: Path) -> None:
        entry = self._ensure_enabled()
        cmd = paths.launcher_command()
        exe = self.game.exe if self.game.exe and os.path.isfile(self.game.exe) else ""
        path = shortcuts.shortcut_path(folder, self.game.name)
        try:
            shortcuts.create(
                path, cmd[0], subprocess.list2cmdline(cmd[1:] + ["run", self.game.id]),
                working_dir=self.game.install_dir or (os.path.dirname(exe) if exe else ""),
                icon=exe or (cmd[0] if len(cmd) == 1 else ""),
                description=f"{self.game.name} at {entry['width']}×{entry['height']} (QRes GUI)",
            )
        except OSError as exc:
            QMessageBox.warning(self, "Create shortcut", str(exc))
            return
        self.win.statusBar().showMessage(f"Created {path}", 8000)
        self.win.refresh_rows(self.game.id)

    def _remove_shortcuts(self) -> None:
        for path in shortcuts.existing(self.game.name):
            path.unlink(missing_ok=True)
        self.win.refresh_rows(self.game.id)

    def _play(self) -> None:
        self._ensure_enabled()
        self.win.refresh_rows(self.game.id)
        subprocess.Popen(paths.launcher_command() + ["run", self.game.id], creationflags=DETACHED_PROCESS,
                         close_fds=True)
        self.win.statusBar().showMessage(f"Starting {self.game.name}…", 6000)
