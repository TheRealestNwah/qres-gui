from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from .. import display, paths


def _browse_row(edit: QLineEdit, button: QPushButton) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(edit, 1)
    layout.addWidget(button)
    return row


def _hint(text: str) -> QLabel:
    label = QLabel(text, objectName="muted", wordWrap=True)
    return label


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg: dict, modes: list[display.Mode], on_remove_hooks=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(620)
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

        launcher = QLineEdit(subprocess.list2cmdline(paths.launcher_command()), readOnly=True)
        logs = QPushButton("Open log folder", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.app_dir()))))

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow("QRes.exe", _browse_row(self.qres, browse))
        form.addRow("Desktop resolution", self.desktop)
        form.addRow("", _hint("What \"Restore desktop resolution\" switches back to if nothing else is recorded."))
        form.addRow("New games default to", self.default_size)
        form.addRow("", self.temporary)
        form.addRow("", _hint("Keeps a crash or power cut from leaving Windows at the game's resolution after a reboot."))
        form.addRow("Wait after switching", self.switch_delay)
        form.addRow("Wait before switching back", self.restore_delay)
        form.addRow("Launcher", _browse_row(launcher, logs))
        if on_remove_hooks:
            unhook = QPushButton("Remove all hooks…", clicked=on_remove_hooks)
            row = QHBoxLayout()
            row.addWidget(unhook)
            row.addWidget(_hint("Takes QRes out of every Steam game's launch options, deletes the "
                                "game shortcuts and turns switching off. Resolution choices are kept."), 1)
            form.addRow("Hooks", row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

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

    def __init__(self, parent, target: display.Mode, qres: str | None, temporary: bool, seconds: int = 10):
        super().__init__(parent)
        self.setWindowTitle("Testing resolution")
        self.setMinimumWidth(420)
        self.target, self.qres, self.temporary = target, qres, temporary
        self.original = display.current_mode()
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
            how = display.set_mode(self.target, self.qres, self.temporary)
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
                display.set_mode(self.original, self.qres, self.temporary)
            except display.DisplayError:
                pass  # the main window's restore button covers this
            finally:
                QApplication.restoreOverrideCursor()
            self.switched = False
        super().done(result)
