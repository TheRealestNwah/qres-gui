from __future__ import annotations

import os
import subprocess
from copy import deepcopy

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __version__, diagnostics, display, notify, paths, playnite, transfer
from . import theme


def _browse_row(edit: QLineEdit, button: QPushButton) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(edit, 1)
    layout.addWidget(button)
    return row


TROUBLESHOOTING = "https://github.com/TheRealestNwah/qres-gui/blob/main/docs/TROUBLESHOOTING.md"


def _left(widget: QWidget) -> QHBoxLayout:
    """A form cell holding `widget` at its natural size, on the left."""
    row = QHBoxLayout()
    row.addWidget(widget)
    row.addStretch()
    return row


def _copy_to_clipboard(text: str) -> None:
    QApplication.clipboard().setText(text)


def licenses_folder():
    """This program's and its third-party components' license texts."""
    return paths.app_folder() / "licenses"


def _hint(text: str) -> QLabel:
    label = QLabel(text, objectName="muted", wordWrap=True)
    # The form sizes wrapped labels for their minimum width; without a realistic
    # one it reserves room for extra lines and leaves gaps around the text.
    label.setMinimumWidth(460)
    return label


def _button_row(*widgets: QWidget) -> QHBoxLayout:
    """A row of buttons (and maybe a label) with room between them; they used to touch."""
    row = QHBoxLayout()
    row.setSpacing(8)
    for widget in widgets:
        row.addWidget(widget)
    return row


def _separator() -> QFrame:
    line = QFrame(frameShape=QFrame.Shape.HLine)
    line.setStyleSheet("color: #2e3238;")
    return line


def launcher_hint() -> str:
    """What starts games from Steam, Playnite and shortcuts, and why it's that one."""
    if paths.is_installed_copy():
        return "Steam, Playnite and shortcuts start games through this launcher."
    if paths.runs_installed_hooks():
        return ("This copy isn't the installed QRes GUI. Steam, Playnite and shortcuts keep using the "
                "installed one, so games switch the way that version does; install this version to "
                "try its launcher.")
    return ("QRes GUI isn't installed, so Steam, Playnite and shortcuts start games from this folder. "
            "Don't move or delete it while games are set up, or install QRes GUI so they point "
            "somewhere that stays put.")


def _indented_hint(text: str) -> QLabel:
    """A hint that belongs to the radio button above it."""
    label = _hint(text)
    label.setContentsMargins(24, 0, 0, 4)
    return label


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg: dict, modes: list[display.Mode], on_remove_hooks=None, on_playnite=None,
                 on_check_updates=None, on_guide=None, on_diagnostics=None, on_transfer=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(700)
        self.modes = modes

        self.qres = QLineEdit(cfg.get("qres_path", ""), placeholderText="Path to QRes.exe")
        browse = QPushButton("Browse…", clicked=self._browse_qres)

        self.desktop = QComboBox()
        desktop = cfg.get("desktop_mode")
        current = display.Mode.from_dict(desktop) if desktop else display.current_mode()
        for mode in modes:
            self.desktop.addItem(str(mode), mode)
        index = self.desktop.findText(str(current))
        self.desktop.setCurrentIndex(max(index, 0))

        self.default_size = QComboBox()
        sizes = list(dict.fromkeys((m.width, m.height) for m in modes))
        for w, h in sizes:
            self.default_size.addItem(f"{w} × {h}", f"{w}x{h}")
        target = cfg.get("default_target", {})
        index = self.default_size.findData(f"{target.get('width')}x{target.get('height')}")
        self.default_size.setCurrentIndex(max(index, 0))

        self.temporary = QCheckBox("Don't save switched resolutions to the registry (QRes /D)")
        self.temporary.setChecked(bool(cfg.get("temporary", True)))

        self.switch_delay = QDoubleSpinBox(suffix=" s", decimals=1, minimum=0, maximum=15, singleStep=0.5)
        self.switch_delay.setValue(float(cfg.get("switch_delay", 1.0)))
        self.restore_delay = QDoubleSpinBox(suffix=" s", decimals=1, minimum=0, maximum=15, singleStep=0.5)
        self.restore_delay.setValue(float(cfg.get("restore_delay", 1.0)))

        saved = cfg.get("commands") or {}
        self.before_cmd = QLineEdit(saved.get("before", ""), placeholderText="Optional")
        self.after_cmd = QLineEdit(saved.get("after", ""), placeholderText="Optional")

        launcher = QLineEdit(subprocess.list2cmdline(paths.hook_command()), readOnly=True)
        logs = QPushButton("Open log folder", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.app_dir()))))

        self.tray_icon = QCheckBox("Show a system-tray icon")
        self.tray_icon.setChecked(bool(cfg.get("tray_icon", True)))
        self.background = QCheckBox("Keep running in the tray when the window is closed")
        self.background.setChecked(bool(cfg.get("background", False)))
        self.restore_hotkey = QKeySequenceEdit()
        self.restore_hotkey.setMaximumSequenceLength(1)
        if cfg.get("restore_hotkey"):
            self.restore_hotkey.setKeySequence(QKeySequence(cfg["restore_hotkey"]))
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self.restore_hotkey, 1)
        hotkey_row.addWidget(QPushButton("Clear", clicked=self.restore_hotkey.clear))
        self.check_updates = QCheckBox("Check for updates when QRes GUI starts (at most once a day)")
        self.check_updates.setChecked(bool(cfg.get("check_updates", True)))
        self.on_check_updates = on_check_updates

        # Six short tabs instead of one long form (#11): everyday settings first,
        # rare and risky actions away from them.
        self.tabs = QTabWidget(objectName="settingsTabs")

        form = self._page("General")
        form.addRow("QRes.exe", _browse_row(self.qres, browse))
        form.addRow("Desktop resolution", self.desktop)
        form.addRow("", _hint("What \"Restore desktop resolution\" goes back to when nothing else is "
                              "recorded. QRes only ever changes the primary display."))
        form.addRow("New games default to", self.default_size)

        form = self._page("Switching")
        form.addRow("", self.temporary)
        form.addRow("", _hint("So a crash or power cut can't leave Windows at a game's resolution after a "
                              "reboot."))
        form.addRow("Wait after switching", self.switch_delay)
        form.addRow("Wait before switching back", self.restore_delay)
        form.addRow("", _hint("Raise the first if a game starts before the display has settled, the second "
                              "if a game restarts itself right after you quit."))
        form.addRow("Before every switch", self.before_cmd)
        form.addRow("After every switch", self.after_cmd)
        form.addRow("", _hint("Commands run as in a Command Prompt for every game, before its own commands "
                              "and after them. QRES_GAME and QRES_GAME_ID say which game it is."))

        form = self._page("Tray && hotkeys")
        form.addRow("Tray icon", _left(self.tray_icon))
        form.addRow("", _left(self.background))
        form.addRow("Restore hotkey", hotkey_row)
        form.addRow("", _hint("Switches back to your desktop resolution from anywhere, even in a game, while "
                              "QRes GUI is running. Needs a modifier, e.g. Ctrl+Alt+Home. Presets get their "
                              "own hotkeys in Manage presets."))

        form = self._page("Integrations")
        # Hints go on their own rows under their buttons: beside a button, a
        # wrapped label doesn't get the height it needs and ends up cut off.
        if on_playnite:
            form.addRow("Playnite", _left(QPushButton("Playnite integration…", clicked=on_playnite)))
            form.addRow("", _hint("Switch resolution for games started from Playnite, whatever the store."))
        form.addRow("Launcher", _browse_row(launcher, logs))
        form.addRow("", _hint(launcher_hint()))
        form.addRow("Notifications", _left(QPushButton("Send test notification", clicked=self._test_notification)))
        form.addRow("", _hint("Launcher problems show up as Windows notifications; during a fullscreen game "
                              "Windows keeps them in the notification centre."))
        if on_remove_hooks:
            # The one thing in Settings that undoes work, kept apart at the bottom.
            form.addRow(_separator())
            form.addRow(QLabel("Undo everything", objectName="caption"))
            form.addRow("Hooks", _left(QPushButton("Remove all hooks…", clicked=on_remove_hooks)))
            form.addRow("", _hint("Takes QRes out of every Steam game's launch options and Playnite's scripts, "
                                  "deletes its game shortcuts and turns switching off. Resolution choices "
                                  "are kept."))

        form = self._page("Updates")
        row = _button_row(self.check_updates)
        if on_check_updates:
            row.addWidget(QPushButton("Check now", clicked=self._check_now))
        row.addStretch()
        form.addRow("Check", row)
        form.addRow("", _hint("Asks GitHub for this project's release list; nothing about your PC or games is "
                              "sent. Nothing is downloaded until you click Install update."))

        form = self._page("Help && About")
        row = _button_row()
        if on_guide:
            # Close Settings first, so its (now stale) fields can't overwrite the guide's choices.
            row.addWidget(QPushButton("Getting started…", clicked=lambda: (self.reject(), on_guide())))
        row.addWidget(QPushButton("Troubleshooting", clicked=lambda: QDesktopServices.openUrl(QUrl(TROUBLESHOOTING))))
        if on_diagnostics:
            row.addWidget(QPushButton("Diagnostics…", clicked=on_diagnostics))
        row.addStretch()
        form.addRow("Help", row)
        if on_transfer:
            # Closes Settings first: an import rewrites the very settings this
            # dialog would write back over on OK.
            form.addRow("Profiles", _left(QPushButton("Back up and restore…",
                                                     clicked=lambda: (self.reject(), on_transfer()))))
        row = _button_row(QLabel(f"QRes GUI {__version__} · MIT license"))
        row.addSpacing(6)
        row.addWidget(QPushButton("Licenses…", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(licenses_folder())))))
        row.addStretch()
        form.addRow("About", row)
        form.addRow("", _hint("Written by Claude (Anthropic's AI assistant), directed and tested by the "
                              "maintainer. Open source: github.com/TheRealestNwah/qres-gui"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(buttons)

        # Open as tall as the tallest tab needs at this width, so no tab opens
        # scrolled - but never taller than the screen; then the tab scrolls and
        # OK / Cancel stay put below it.
        width = self.minimumWidth()
        margins = layout.contentsMargins()
        inner = width - margins.left() - margins.right() - 40   # the tab frame and page margins
        content = max(self._page_height(self.tabs.widget(i), inner) for i in range(self.tabs.count()))
        chrome = (margins.top() + margins.bottom() + layout.spacing() + buttons.sizeHint().height()
                  + self.tabs.tabBar().sizeHint().height() + 12)
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        room = int(screen.availableGeometry().height() * 0.9) - 40 if screen else content + chrome
        self.resize(width, min(content + chrome, room))

    def _page(self, title: str) -> QFormLayout:
        """A tab holding a form, which scrolls if the screen is too short for it."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 14, 14, 8)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        outer.addLayout(form)
        outer.addStretch()
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)
        return form

    @staticmethod
    def _page_height(scroll: QScrollArea, width: int) -> int:
        layout = scroll.widget().layout()
        return layout.totalHeightForWidth(width) if layout.hasHeightForWidth() else scroll.widget().sizeHint().height()

    def _check_now(self) -> None:
        release, error = self.on_check_updates()
        if error:
            QMessageBox.warning(self, "Updates", f"Couldn't reach GitHub: {error}")
        elif release:
            answer = QMessageBox.question(self, "Updates",
                                          f"QRes GUI {release['version']} is available (you have {__version__}).\n\n"
                                          "Open its release page?")
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(release["url"]))
        else:
            QMessageBox.information(self, "Updates", f"You're up to date (QRes GUI {__version__}).")

    def _test_notification(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok = notify.toast("QRes GUI test notification", "Launcher problems will show up like this.")
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            QMessageBox.warning(self, "Notifications",
                                "Windows refused the notification; problems will appear as message boxes. "
                                f"Details are in {paths.log_path()}.")

    def _browse_qres(self) -> None:
        start = os.path.dirname(self.qres.text()) if self.qres.text() else ""
        path, _ = QFileDialog.getOpenFileName(self, "Locate QRes.exe", start, "QRes (QRes.exe);;Programs (*.exe)")
        if path:
            self.qres.setText(os.path.normpath(path))

    def apply_to(self, cfg: dict) -> None:
        cfg["qres_path"] = self.qres.text().strip()
        mode: display.Mode = self.desktop.currentData()
        cfg["desktop_mode"] = mode.to_dict()
        w, h = (int(x) for x in self.default_size.currentData().split("x"))
        cfg["default_target"] = {"width": w, "height": h, "refresh": 0}
        cfg["temporary"] = self.temporary.isChecked()
        cfg["switch_delay"] = self.switch_delay.value()
        cfg["restore_delay"] = self.restore_delay.value()
        cfg["check_updates"] = self.check_updates.isChecked()
        cfg["tray_icon"] = self.tray_icon.isChecked()
        cfg["background"] = self.background.isChecked()
        cfg["restore_hotkey"] = self.restore_hotkey.keySequence().toString()
        cfg["commands"] = {"before": self.before_cmd.text().strip(), "after": self.after_cmd.text().strip()}


class PlayniteDialog(QDialog):
    """Add QRes's lines to Playnite's global game scripts, or show them for pasting in by hand."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Playnite integration")
        self.setMinimumWidth(720)
        self.cmd = paths.hook_command()
        pre, post = playnite.scripts(self.cmd)

        intro = QLabel(
            "Playnite can run a script before every game starts and after it exits. With QRes's lines "
            "added there, any game you start from Playnite switches resolution if it's set up in QRes GUI "
            "with switching on. It's matched by store ID, install folder or name, whichever plugin "
            "Playnite uses to start it. Steam games that also have QRes launch options switch only once.",
            wordWrap=True)
        self.status = QLabel(wordWrap=True)
        self.install_btn = QPushButton("Add to Playnite", objectName="primary", clicked=self._install)
        self.remove_btn = QPushButton("Remove from Playnite", clicked=self._remove)
        buttons = QHBoxLayout()
        buttons.addWidget(self.install_btn)
        buttons.addWidget(self.remove_btn)
        buttons.addStretch()

        manual = QLabel("To add them by hand instead: Playnite › Main menu › Settings › Scripts. "
                        "Add the first block to \"Execute before starting a game\" and the second to "
                        "\"Execute after exiting a game\", after any lines already there.",
                        objectName="muted", wordWrap=True)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(intro)
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        layout.addSpacing(6)
        layout.addWidget(manual)
        for title, text in (("Before starting a game", pre), ("After exiting a game", post)):
            box = QPlainTextEdit(text, readOnly=True)
            box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            lines = text.count("\n") + 1
            box.setMinimumHeight(box.fontMetrics().lineSpacing() * lines + 2 * box.frameWidth()
                                 + 2 * int(box.document().documentMargin())
                                 + box.horizontalScrollBar().sizeHint().height() + 6)
            box.setMaximumHeight(box.minimumHeight())
            copy = QPushButton(f"Copy \"{title}\"", clicked=lambda _=False, t=text: self._copy(t))
            layout.addWidget(box)
            layout.addWidget(copy, alignment=Qt.AlignmentFlag.AlignLeft)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self._refresh()
        self.resize(max(self.sizeHint().width(), 860), self.sizeHint().height())

    def _refresh(self) -> None:
        state = playnite.state(self.cmd)
        running = playnite.is_running()
        texts = {
            "missing": ("error", "Playnite wasn't found on this PC."),
            "none": ("off", "Not added to Playnite yet."),
            "installed": ("ok", "✓  Added to Playnite's scripts."),
            "outdated": ("warn", "Playnite's scripts point at an older QRes launcher location. Add them again to update."),
        }
        kind, text = texts[state]
        if running and state != "missing":
            text += "  Playnite is running; close it to change its scripts (it saves its settings on exit)."
        theme.set_state(self.status, kind, text)
        self.install_btn.setText("Update in Playnite" if state == "outdated" else "Add to Playnite")
        self.install_btn.setEnabled(state in ("none", "outdated") and not running)
        self.remove_btn.setEnabled(state in ("installed", "outdated") and not running)

    def _install(self) -> None:
        self._change(lambda: playnite.install(self.cmd), "Added. Start Playnite again and play.")

    def _remove(self) -> None:
        self._change(playnite.uninstall, "Removed QRes's lines from Playnite's scripts.")

    def _change(self, action, done: str) -> None:
        try:
            backup = action()
        except Exception as exc:
            QMessageBox.warning(self, "Playnite integration", str(exc))
        else:
            QMessageBox.information(self, "Playnite integration", f"{done}\n\nBackup of the old settings: {backup.name}")
        self._refresh()

    def _copy(self, text: str) -> None:
        _copy_to_clipboard(text)



class DiagnosticsDialog(QDialog):
    """Everything QRes GUI can see about this PC, for reading or for pasting into a bug report."""

    def __init__(self, parent, cfg: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Diagnostics")
        self.setMinimumWidth(720)
        self.sections = diagnostics.report(cfg)
        self.text = diagnostics.as_text(self.sections)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(_hint("What QRes GUI can see right now. Nothing here is sent anywhere - "
                               "Copy puts it on the clipboard so you can paste it into a bug report."))
        for section in self.sections:
            layout.addWidget(QLabel(section.title, objectName="caption"))
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            for row in section.rows:
                value = QLabel(row.value, wordWrap=True)
                if not row.ok:
                    # The rows worth reading first are the ones that went wrong.
                    value.setObjectName("warning")
                form.addRow(f"{row.label}:", value)
            layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = QPushButton("Copy for a bug report", objectName="primary",
                           clicked=lambda: self._copy_report(copy))
        buttons.addButton(copy, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy_report(self, button: QPushButton) -> None:
        _copy_to_clipboard(self.text)
        button.setText("Copied")
        QTimer.singleShot(1500, lambda: button.setText("Copy for a bug report"))



FILTER = "QRes GUI profiles (*.qresprofiles.json);;JSON (*.json)"
SUFFIX = ".qresprofiles.json"


class TransferDialog(QDialog):
    """Take profiles to another PC, or bring them back after a reinstall."""

    def __init__(self, parent, cfg: dict):
        super().__init__(parent)
        self.setWindowTitle("Back up and restore profiles")
        self.setMinimumWidth(640)
        self.cfg = cfg
        self.imported = False        # the caller reloads its views only if this is True
        self.summary: transfer.Summary | None = None   # what the import did, once it has

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(_hint(
            "An export carries your game profiles, presets and the settings that mean the same "
            "thing anywhere. It leaves out what only applies to this PC — where QRes.exe is, your "
            "desktop resolution, and the paths the stores report, which a rescan fills in again."))

        counts = QLabel(f"{len(cfg.get('games') or {})} game profile(s) and "
                        f"{len(cfg.get('presets') or [])} preset(s) here now.")
        layout.addWidget(counts)

        row = QHBoxLayout()
        row.addWidget(QPushButton("Export…", objectName="primary", clicked=self._export))
        row.addWidget(QPushButton("Import…", clicked=self._import))
        row.addStretch()
        layout.addLayout(row)

        layout.addWidget(QLabel("Importing:", objectName="caption"))
        self.restore_mode = QRadioButton("Restore — make everything match the file", checked=True)
        self.merge_mode = QRadioButton("Merge — add and update from the file, keep everything else")
        layout.addWidget(self.restore_mode)
        layout.addWidget(_indented_hint(
            "For undoing changes. Profiles and presets set up since the file was made are removed."))
        layout.addWidget(self.merge_mode)
        layout.addWidget(_indented_hint(
            "For bringing profiles to another PC. Nothing already here is removed."))

        self.what = QVBoxLayout()
        self.games = QCheckBox("Game profiles", checked=True)
        self.presets = QCheckBox("Presets", checked=True)
        self.settings = QCheckBox("Settings", checked=True)
        for box in (self.games, self.presets, self.settings):
            self.what.addWidget(box)
        layout.addWidget(QLabel("Include:", objectName="caption"))
        layout.addLayout(self.what)
        layout.addWidget(_hint(
            "Games are matched by their store ID. A display a profile names is kept only if a "
            "monitor of the same name and number is connected here — otherwise that profile uses "
            "the primary display rather than guessing at the wrong screen. You'll see exactly "
            "what will change before anything does."))

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def _export(self) -> None:
        start = os.path.join(os.path.expanduser("~"), "QRes GUI profiles" + SUFFIX)
        path, _ = QFileDialog.getSaveFileName(self, "Export profiles", start, FILTER)
        if not path:
            return
        try:
            written = transfer.write_export(self.cfg, path)
        except OSError as exc:
            QMessageBox.warning(self, "Export", f"Couldn't write that file: {exc.strerror or exc}")
            return
        data = transfer.export_data(self.cfg)
        QMessageBox.information(self, "Export",
                                f"Exported {len(data['games'])} game profile(s) and "
                                f"{len(data['presets'])} preset(s) to:\n\n{written}")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import profiles", "", FILTER)
        if not path:
            return
        try:
            data = transfer.read_export(path)
        except transfer.TransferError as exc:
            QMessageBox.warning(self, "Import", str(exc))
            return

        # Say what it would do before doing it: an import rewrites profiles the
        # user may have spent a while on, and a restore can remove some.
        apply = transfer.restore if self.restore_mode.isChecked() else transfer.merge
        title = "Restore" if self.restore_mode.isChecked() else "Merge"
        sections = dict(games=self.games.isChecked(), presets=self.presets.isChecked(),
                        settings=self.settings.isChecked())
        preview = apply(deepcopy(self.cfg), data, **sections)
        when = data.get("exported", "an unknown date")
        body = f"From a QRes GUI {data.get('app_version', '?')} export made {when}.\n\n" + \
               "\n".join(f"• {line}" for line in preview.lines())
        if not preview.changed:
            QMessageBox.information(self, title, body)
            return
        if QMessageBox.question(self, title, body + "\n\nApply this?") != QMessageBox.StandardButton.Yes:
            return

        self.summary = apply(self.cfg, data, **sections)
        self.imported = True
        self.accept()


class AddGameDialog(QDialog):
    """Add a game no store detection covers, by pointing at its executable."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add game")
        self.setMinimumWidth(560)
        self.exe = QLineEdit(placeholderText="Game executable")
        self.name = QLineEdit(placeholderText="Name shown in the list")
        self.args = QLineEdit(placeholderText="Optional command-line arguments")
        self.exe.textChanged.connect(self._validate)
        self.name.textChanged.connect(self._validate)

        form = QFormLayout()
        form.addRow("Executable", _browse_row(self.exe, QPushButton("Browse…", clicked=self._browse)))
        form.addRow("Name", self.name)
        form.addRow("Arguments", self.args)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self._validate()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose the game's executable", "", "Programs (*.exe)")
        if not path:
            return
        path = os.path.normpath(path)
        self.exe.setText(path)
        if not self.name.text().strip():
            folder = os.path.basename(os.path.dirname(path))
            self.name.setText(folder or os.path.splitext(os.path.basename(path))[0])

    def _validate(self) -> None:
        ok = os.path.isfile(self.exe.text().strip()) and bool(self.name.text().strip())
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def values(self) -> tuple[str, str, str]:
        return self.name.text().strip(), self.exe.text().strip(), self.args.text().strip()


class TestResolutionDialog(QDialog):
    """Switch to a mode for a few seconds, then back, so it can be checked safely."""

    def __init__(self, parent, target: display.Mode, qres: str | None, temporary: bool,
                 seconds: int = 10, device: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Testing resolution")
        self.setMinimumWidth(420)
        self.target, self.qres, self.temporary = target, qres, temporary
        self.device = device
        self.original = display.current_mode(device)
        self.remaining = seconds
        self.switched = False

        self.message = QLabel(f"Switching to {target}…", wordWrap=True)
        self.message.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.countdown = QLabel(objectName="muted")
        back = QPushButton("Switch back now", objectName="primary", clicked=self.accept)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(self.message)
        layout.addWidget(self.countdown)
        layout.addWidget(back, alignment=Qt.AlignmentFlag.AlignRight)

        self.timer = QTimer(self, interval=1000, timeout=self._tick)
        QTimer.singleShot(150, self._switch)

    def _switch(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            how = display.set_mode(self.target, self.qres, self.temporary, self.device)
        except display.DisplayError as exc:
            self.message.setText(str(exc))
            self.countdown.setText("")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.switched = True
        self.message.setText(f"Now running at {self.target}  (via {how})")
        self._update_countdown()
        self.timer.start()

    def _tick(self) -> None:
        self.remaining -= 1
        if self.remaining <= 0:
            self.accept()
        else:
            self._update_countdown()

    def _update_countdown(self) -> None:
        self.countdown.setText(f"Switching back to {self.original} in {self.remaining} s.")

    def done(self, result: int) -> None:
        self.timer.stop()
        if self.switched:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                display.set_mode(self.original, self.qres, self.temporary, self.device)
            except display.DisplayError:
                pass  # the main window's restore button covers this
            finally:
                QApplication.restoreOverrideCursor()
            self.switched = False
        super().done(result)
