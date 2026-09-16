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

from .. import config, display, engines, hdr, paths, playnite, shortcuts
from ..stores import Game, steam
from . import theme
from .dialogs import TestResolutionDialog

DETACHED_PROCESS = 0x00000008
BANNER_WIDTH = 460

# "" means leave HDR alone; the launcher stores that as null.
HDR_CHOICES = (("Leave as it is", ""), ("Turn on for this game", "on"), ("Turn off for this game", "off"))
HDR_HINT = "Switched when the game starts and put back when it exits."


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


def _hdr_choice(value) -> str:
    """A saved "hdr" setting (True / False / None) as its combo-box key."""
    return "" if value is None else ("on" if value else "off")


def _hdr_value(choice: str) -> bool | None:
    return None if not choice else choice == "on"


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
        self.placeholder = QLabel("Select a game to set up its display.", objectName="muted",
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

        # Display profile
        box = QGroupBox("Display")
        layout = QVBoxLayout(box)
        self.enabled = QCheckBox("Change the display when this game launches")
        self.enabled.setStyleSheet("font-weight: 600;")
        self.enabled.toggled.connect(self._on_enabled)
        layout.addWidget(self.enabled)
        form = QFormLayout()
        self.display_combo = QComboBox()
        self.display_combo.setToolTip("Which screen this game switches. \"Primary display\" follows whichever\n"
                                      "one Windows currently calls primary, so it survives re-plugging.")
        self.display_combo.currentIndexChanged.connect(self._on_display)
        form.addRow("Display", self.display_combo)
        self.res_combo = QComboBox()
        self.res_combo.currentIndexChanged.connect(self._on_resolution)
        self.rate_combo = QComboBox()
        self.rate_combo.currentIndexChanged.connect(self._on_rate)
        self.hdr_combo = QComboBox()
        for label, key in HDR_CHOICES:
            self.hdr_combo.addItem(label, key)
        self.hdr_combo.currentIndexChanged.connect(self._on_hdr)
        form.addRow("Resolution", self.res_combo)
        form.addRow("Refresh rate", self.rate_combo)
        form.addRow("HDR", self.hdr_combo)
        layout.addLayout(form)
        self.hdr_hint = _muted(HDR_HINT)
        layout.addWidget(self.hdr_hint)
        self.quick = QCheckBox("Switch back the moment the game closes")
        self.quick.setToolTip("Skips the few seconds QRes normally waits after the game exits, which\n"
                              "catch games that restart themselves (e.g. after changing graphics settings).")
        self.quick.toggled.connect(self._on_quick)
        layout.addWidget(self.quick)
        self.test_btn = QPushButton("Test for 10 seconds", clicked=self._test)
        layout.addLayout(_row(self.test_btn, _muted("Switches, then comes back on its own.")))
        self.primary_hint = _muted()
        layout.addWidget(self.primary_hint)
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

        # Extra arguments: their own box, because where they can apply - and
        # where they can't - depends on how the game is started, and that has
        # to be said in the open rather than in a tooltip.
        self.args_box = QGroupBox("Extra arguments")
        layout = QVBoxLayout(self.args_box)
        # Options the game's engine documents (#14), when the install folder
        # shows a known engine. Rebuilt per engine; see _show_engine.
        self.engine_note = QLabel(objectName="caption")
        layout.addWidget(self.engine_note)
        self.engine_form = QFormLayout()
        self.engine_form.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.engine_form)
        self.engine_adds = _muted()
        layout.addWidget(self.engine_adds)
        self.engine_combos: dict[str, QComboBox] = {}
        self._engine_shown: str | None = None
        self.extra_args = QLineEdit(placeholderText="Optional, e.g. -windowed -skipintro")
        self.extra_args.editingFinished.connect(self._on_extra_args)
        layout.addWidget(self.extra_args)
        self.args_hint = _muted()
        layout.addWidget(self.args_hint)
        v.addWidget(self.args_box)

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

        # Commands around the switch (commands.py)
        box = QGroupBox("Commands")
        form = QFormLayout(box)
        self.before_cmd = QLineEdit(placeholderText="Optional, e.g. taskkill /im Discord.exe")
        self.after_cmd = QLineEdit(placeholderText=r'Optional, e.g. start "" "C:\Tools\Overlay.exe"')
        for field, when in ((self.before_cmd, "before"), (self.after_cmd, "after")):
            field.editingFinished.connect(lambda when=when: self._on_command(when))
        form.addRow("Before switching", self.before_cmd)
        form.addRow("After switching back", self.after_cmd)
        form.addRow(_muted(
            "Run as in a Command Prompt, just before QRes switches the display for this game and after it "
            "switches back — including when the game is closed from Steam or Playnite. QRes waits up to "
            "15 seconds for each, and anything it starts keeps running. Commands for every game are in "
            "Settings › Switching: those run first before, and last after."))
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
        self.quick.setChecked(bool(entry.get("quick_restore")))
        self._fill_displays(entry.get("display") or "")
        self._fill_resolutions(entry["width"], entry["height"])
        self._fill_rates(entry["width"], entry["height"], entry.get("refresh", 0))
        self._update_display_hint()
        self._fill_hdr(entry.get("hdr"))
        self.watch.setText(", ".join(entry.get("watch", [])))
        self.extra_args.setText(entry.get("extra_args", ""))
        saved = entry.get("commands") or {}
        self.before_cmd.setText(saved.get("before", ""))
        self.after_cmd.setText(saved.get("after", ""))

        is_steam, is_manual = game.store == "steam", game.store == "manual"
        self.steam_box.setVisible(is_steam)
        self.shortcut_box.setVisible(not is_steam)
        self.manual_form.setVisible(is_manual)
        self.remove_btn.setVisible(is_manual or game.store == "playnite")
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

    def _device(self) -> str | None:
        """The display this game switches; None means whichever is primary."""
        return (self._entry(create=False).get("display") or "") or None

    def _modes(self) -> list[display.Mode]:
        return self.win.modes_for(self._device())

    def _live_mode(self, device: str | None) -> display.Mode:
        """What this display is running right now."""
        try:
            return display.current_mode(device)
        except display.DisplayError:
            return display.current_mode()  # unplugged mid-edit; the primary is the safe answer

    def _desktop_mode(self, device: str | None) -> display.Mode:
        """What this display sits at normally - the saved desktop mode, for the primary."""
        if device is None and self.win.cfg.get("desktop_mode"):
            return display.Mode.from_dict(self.win.cfg["desktop_mode"])
        return self._live_mode(device)

    def _update_display_hint(self) -> None:
        """Say how this screen gets switched - the answer differs off the primary."""
        device = self._device()
        if device and display.find_display(device) is None:
            theme.set_state(self.primary_hint, "warn",
                            "That display isn't connected. QRes won't switch anything for this game "
                            "until it's back, rather than switch a different screen.")
        elif device and not display.drives_primary(device):
            self.primary_hint.setStyleSheet("")
            self.primary_hint.setText("QRes.exe only drives the primary display, so this one is "
                                      "switched through the Windows API instead.")
        else:
            self.primary_hint.setStyleSheet("")
            self.primary_hint.setText("QRes switches the primary display.")

    def _fill_displays(self, device: str) -> None:
        """Every attached display, plus the saved one if it has been unplugged."""
        self.display_combo.blockSignals(True)
        self.display_combo.clear()
        self.display_combo.addItem("Primary display", "")
        for entry in self.win.displays:
            self.display_combo.addItem(entry.label, entry.device)
        if device and self.display_combo.findData(device) < 0:
            self.display_combo.addItem(f"{device}  (not connected)", device)
        self.display_combo.setCurrentIndex(max(self.display_combo.findData(device or ""), 0))
        self.display_combo.blockSignals(False)

    def _fill_resolutions(self, width: int, height: int) -> None:
        self.res_combo.blockSignals(True)
        self.res_combo.clear()
        sizes = list(dict.fromkeys((m.width, m.height) for m in self._modes()))
        if (width, height) not in sizes:
            sizes.append((width, height))
        here = self._live_mode(self._device())
        for w, h in sizes:
            label = f"{w} × {h}"
            if (w, h) == (here.width, here.height):
                label += "   (current)"
            self.res_combo.addItem(label, f"{w}x{h}")
        self.res_combo.setCurrentIndex(max(self.res_combo.findData(f"{width}x{height}"), 0))
        self.res_combo.blockSignals(False)

    def _fill_rates(self, width: int, height: int, selected: int) -> None:
        self.rate_combo.blockSignals(True)
        self.rate_combo.clear()
        rates = display.refresh_rates(width, height, self._modes())
        desktop_rate = self._desktop_mode(self._device()).refresh
        if desktop_rate in rates or not rates:
            self.rate_combo.addItem(f"Same as desktop ({desktop_rate} Hz)", 0)
        else:
            self.rate_combo.addItem(f"Highest available ({rates[0]} Hz)", 0)
        for rate in rates:
            self.rate_combo.addItem(f"{rate} Hz", rate)
        self.rate_combo.setCurrentIndex(max(self.rate_combo.findData(selected), 0))
        self.rate_combo.blockSignals(False)

    def _fill_hdr(self, value) -> None:
        """Show the saved choice, and say so if this display can't do HDR anyway."""
        self.hdr_combo.blockSignals(True)
        self.hdr_combo.setCurrentIndex(max(self.hdr_combo.findData(_hdr_choice(value)), 0))
        self.hdr_combo.blockSignals(False)
        state = hdr.status(self._device())
        self.hdr_combo.setEnabled(state.supported)
        if state.supported:
            self.hdr_hint.setStyleSheet("")
            self.hdr_hint.setText(HDR_HINT)
        else:
            # Only a warning if the profile is actually asking for HDR.
            theme.set_state(self.hdr_hint, "warn" if value is not None else "off", state.reason)

    # --- profile edits -----------------------------------------------------

    def _changed(self) -> None:
        self.win.save()
        self.win.refresh_rows(self.game.id)

    def _on_enabled(self, checked: bool) -> None:
        if self._loading or not self.game:
            return
        self._entry()["enabled"] = checked
        self._changed()

    def _on_quick(self, checked: bool) -> None:
        if self._loading or not self.game:
            return
        self._entry()["quick_restore"] = checked
        self._changed()

    def _on_resolution(self) -> None:
        if self._loading or not self.game:
            return
        w, h = (int(x) for x in self.res_combo.currentData().split("x"))
        entry = self._entry()
        entry["width"], entry["height"] = w, h
        if entry.get("refresh") and entry["refresh"] not in display.refresh_rates(w, h, self._modes()):
            entry["refresh"] = 0
        self._fill_rates(w, h, entry.get("refresh", 0))
        self._changed()

    def _on_rate(self) -> None:
        if self._loading or not self.game:
            return
        self._entry()["refresh"] = int(self.rate_combo.currentData() or 0)
        self._changed()

    def _on_display(self) -> None:
        if self._loading or not self.game:
            return
        entry = self._entry()
        entry["display"] = self.display_combo.currentData() or ""
        device = entry["display"] or None
        modes = self.win.modes_for(device)
        # The saved resolution may be one this screen doesn't offer; snapping to
        # what it is actually running beats saving a mode that can't be set.
        if modes and not display.is_size_available(entry["width"], entry["height"], modes):
            here = self._desktop_mode(device)
            entry["width"], entry["height"], entry["refresh"] = here.width, here.height, 0
        self._loading = True
        self._fill_resolutions(entry["width"], entry["height"])
        self._fill_rates(entry["width"], entry["height"], entry.get("refresh", 0))
        self._fill_hdr(entry.get("hdr"))
        self._loading = False
        self._update_display_hint()
        self._changed()
        self.refresh_integration()

    def _on_hdr(self) -> None:
        if self._loading or not self.game:
            return
        self._entry()["hdr"] = _hdr_value(self.hdr_combo.currentData())
        self._changed()

    def _on_extra_args(self) -> None:
        if self._loading or not self.game:
            return
        entry = self._entry()
        args = self.extra_args.text().strip()
        if args != entry.get("extra_args", ""):
            entry["extra_args"] = args
            self.extra_args.setText(args)
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

    def _on_command(self, when: str) -> None:
        if self._loading or not self.game:
            return
        field = self.before_cmd if when == "before" else self.after_cmd
        text = field.text().strip()
        entry = self._entry()
        saved = dict(entry.get("commands") or {})
        if text == saved.get(when, ""):
            return
        if text:
            saved[when] = text
        else:
            saved.pop(when, None)
        if saved:
            entry["commands"] = saved
        else:
            entry.pop("commands", None)
        field.setText(text)
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
        device = self._device()
        if device and display.find_display(device) is None:
            QMessageBox.information(self, "Test resolution",
                                    "The display this game is set up for isn't connected.")
            return
        desktop = self._desktop_mode(device)
        target = display.resolve(entry["width"], entry["height"], entry.get("refresh", 0), desktop, device)
        if target == display.current_mode(device):
            QMessageBox.information(self, "Test resolution", f"That display is already at {target}.")
            return
        TestResolutionDialog(self, target, display.find_qres(self.win.cfg.get("qres_path")),
                             bool(self.win.cfg.get("temporary", True)), device=device).exec()
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
        self._refresh_args(entry)

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

    def _refresh_args(self, entry: dict) -> None:
        """Say where extra arguments apply for this game - and where to set them when they can't."""
        # A game added by hand has its own Arguments field; there's no store's to add to.
        self.args_box.setVisible(self.game.store != "manual")
        launch = entry.get("launch") or self.game.launch or {}
        playnite_edit = "right-click the game › Edit › Actions"
        if self.game.store == "steam":
            hooked = self.win.steam_state(self.game) == "applied"
            text = ("Added after the game's own command whenever Steam starts it through QRes — from Steam, "
                    "or from Playnite through Steam. Your own Steam launch options stay as they are.")
            if not hooked:
                text += " They start working once QRes's launch options are applied to Steam."
            self._set_args(True, text)
        elif launch.get("type") == "exe":
            self._set_args(True, "Added after the store's own arguments when QRes GUI starts the game: its "
                                 "shortcuts and Play. When Playnite starts it, Playnite's own arguments "
                                 f"apply instead — {playnite_edit}.")
        elif self.game.store == "playnite" or not launch:
            self._set_args(False, f"Playnite starts this game, so set its arguments in Playnite: {playnite_edit}.")
        else:
            self._set_args(False, f"{self.game.store_label} starts this game itself, so QRes can't add "
                                  "arguments to it. Set them in the store's own launcher, or in Playnite "
                                  f"({playnite_edit}) if you start it from there.")

    def _set_args(self, usable: bool, hint: str) -> None:
        self.extra_args.setVisible(usable)
        self.args_hint.setText(hint)
        # Engine options travel the same way as the typed arguments, so they're
        # offered exactly where those can apply.
        entry = self._entry(create=False)
        self._show_engine(engines.detect(self.game.install_dir or "") if usable else None, entry)

    def _show_engine(self, engine: str | None, entry: dict) -> None:
        if engine != self._engine_shown:
            while self.engine_form.rowCount():
                self.engine_form.removeRow(0)
            self.engine_combos = {}
            for option in engines.OPTIONS.get(engine, ()):
                combo = QComboBox()
                combo.addItem("Game's choice", "")
                if option.per_display:
                    choices = engines.monitor_choices(len(self.win.displays))
                elif option.per_profile:
                    choices = ((engines.PROFILE_RESOLUTION, "Start at this game's resolution", ()),)
                else:
                    choices = option.choices
                for value, label, _flags in choices:
                    combo.addItem(label, value)
                combo.currentIndexChanged.connect(lambda _i, key=option.key: self._on_engine_option(key))
                self.engine_form.addRow(option.label, combo)
                self.engine_combos[option.key] = combo
            self._engine_shown = engine
        for widget in (self.engine_note, self.engine_adds):
            widget.setVisible(engine is not None)
        if engine is None:
            return
        name = engines.NAMES[engine]
        self.engine_note.setText(f"{name} options")
        saved = entry.get("engine_args") or {}
        saved = saved if saved.get("engine") == engine else {}
        for key, combo in self.engine_combos.items():
            combo.blockSignals(True)
            combo.setCurrentIndex(max(combo.findData(saved.get(key, "")), 0))
            combo.blockSignals(False)
        # Say which size "this game's resolution" means right now; it follows the profile.
        resolution = self.engine_combos.get("resolution")
        size = engines.profile_size(entry)
        if resolution is not None:
            resolution.setItemText(1, "Start at this game's resolution" +
                                   (f" ({size[0]} × {size[1]})" if size else ""))
        adds = engines.command_line(saved, entry)
        self.engine_adds.setText(
            (f"Adds: {adds}. " if adds else "") +
            f"Documented by {name} for every game made with it, though a game can choose to ignore them. "
            "Anything typed below goes after these.")

    def _on_engine_option(self, key: str) -> None:
        if self._loading or not self.game or not self._engine_shown:
            return
        entry = self._entry()
        choices = dict(entry.get("engine_args") or {})
        if choices.get("engine") != self._engine_shown:
            choices = {}          # choices made for another engine mean nothing here
        choices["engine"] = self._engine_shown
        value = self.engine_combos[key].currentData()
        if value:
            choices[key] = value
        else:
            choices.pop(key, None)
        if set(choices) == {"engine"}:
            entry.pop("engine_args", None)
        else:
            entry["engine_args"] = choices
        self._changed()   # refreshes the panel too, and with it the "Adds:" line

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
        elif state == "outdated" and self.win.steam_hook_missing(self.game):
            theme.set_state(self.steam_status, "warn",
                            "The launch options run a QRes launcher that isn't there any more, so Steam "
                            "can't start this game. Update them.")
        elif state == "outdated":
            target = "your installed QRes GUI" if paths.installed_launcher() else "this copy"
            theme.set_state(self.steam_status, "warn",
                            f"The launch options run a different copy of QRes GUI "
                            f"({steam.hooked_launcher(current)}). Update them to use {target}.")
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
        if self.win.playnite_hooked:
            self.steam_hint.setText(self.steam_hint.text() + " Started from Playnite, it switches through "
                                    "Playnite's scripts either way; the launch options cover starting it from Steam.")

    def _refresh_shortcuts(self, entry: dict, enabled: bool, watch_needed: bool) -> None:
        launch = entry.get("launch") or self.game.launch or {}
        if launch.get("type") == "exe":
            self.target_label.setText(f"Starts  {launch.get('path', '')}  {config.full_args(entry)}".rstrip())
        elif launch.get("type") == "uri":
            self.target_label.setText(f"Starts through {self.game.store_label}  ({launch['uri']})")
        else:
            if self.game.store == "playnite":
                self.target_label.setText("Found because Playnite started it. Start it from Playnite; "
                                          "Play below asks Playnite to start it.")
            else:
                self.target_label.setText(f"QRes can't start {self.game.store_label} games itself; they need "
                                          "the tool that installed them. Start it from Playnite instead.")
        self.target_label.setVisible(self.game.store != "manual")

        found = shortcuts.existing(self.game.name)
        playnite_only = not launch
        if playnite_only:
            if self.win.playnite_hooked:
                theme.set_state(self.shortcut_status, "ok" if enabled else "off",
                                "✓  Switches when started from Playnite." if enabled else
                                "Turn on switching above; it then switches when started from Playnite.")
            else:
                theme.set_state(self.shortcut_status, "warn",
                                "Add QRes to Playnite first: Settings › Integrations › Playnite integration.")
        elif watch_needed:
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
        for button in (self.desktop_btn, self.startmenu_btn, self.play_btn):
            button.setVisible(not playnite_only)
        if self.game.store == "playnite":  # Playnite can start it; its scripts do the switching
            self.play_btn.setVisible(True)
            self.play_btn.setEnabled(True)
        self.play_btn.setText("Play in Playnite" if self.game.store == "playnite" else "Play")
        if playnite_only:
            hint = ""
        elif self.game.store != "manual":
            hint = (f"Start the game from this shortcut (or Play) instead of from {self.game.store_label} "
                    "directly - that's what switches the resolution.")
        else:
            hint = "Start the game from this shortcut (or Play) so the resolution switches."
        if self.win.playnite_hooked and not playnite_only:
            hint += " Starting it from Playnite switches too."
        self.shortcut_hint.setText(hint)
        self.shortcut_hint.setVisible(bool(hint))

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
        cmd = paths.hook_command()
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
        if self.game.store == "playnite":
            os.startfile(playnite.start_uri(self.game.id.split(":", 1)[1]))
            self.win.statusBar().showMessage(f"Asked Playnite to start {self.game.name}…", 6000)
            return
        subprocess.Popen(paths.launcher_command() + ["run", self.game.id], creationflags=DETACHED_PROCESS,
                         close_fds=True)
        self.win.statusBar().showMessage(f"Starting {self.game.name}…", 6000)
