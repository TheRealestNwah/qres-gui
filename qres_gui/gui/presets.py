"""Quick resolution switching: apply a mode with a keep/revert safety prompt,
and manage saved presets. Presets are {"name", "width", "height", "refresh"}
(refresh 0 = same as desktop)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout,
)

from .. import display
from . import theme

REVERT_SECONDS = 15


def preset_label(preset: dict) -> str:
    refresh = int(preset.get("refresh") or 0)
    rate = "" if refresh == 0 else f" @ {refresh} Hz"
    return f"{preset['width']} × {preset['height']}{rate}"


def preset_name(preset: dict) -> str:
    return str(preset.get("name") or "").strip() or preset_label(preset)


class ApplyResolutionDialog(QDialog):
    """Switch the primary display to `target`, then ask whether to keep it.

    If the user doesn't confirm within REVERT_SECONDS, or the mode can't be
    set, the display goes back to what it was - so a black or unusable screen
    fixes itself.
    """

    def __init__(self, parent, target: display.Mode, qres: str | None, temporary: bool,
                 seconds: int = REVERT_SECONDS):
        super().__init__(parent)
        self.setWindowTitle("Switch resolution")
        self.setMinimumWidth(440)
        self.target, self.qres, self.temporary = target, qres, temporary
        self.original = display.current_mode()
        self.remaining = seconds
        self.switched = False
        self.kept = False

        self.message = QLabel(f"Switching to {target}…", wordWrap=True)
        self.message.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.countdown = QLabel(objectName="muted", wordWrap=True)
        self.keep_btn = QPushButton("Keep", objectName="primary", clicked=self._keep)
        self.revert_btn = QPushButton("Revert now", clicked=self.reject)
        self.close_btn = QPushButton("Close", clicked=self.reject)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.revert_btn)
        row.addWidget(self.keep_btn)
        row.addWidget(self.close_btn)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(self.message)
        layout.addWidget(self.countdown)
        layout.addLayout(row)
        self._show_buttons(applying=True)

        self.timer = QTimer(self, interval=1000, timeout=self._tick)
        QTimer.singleShot(150, self._switch)

    def _show_buttons(self, applying: bool, failed: bool = False) -> None:
        self.keep_btn.setVisible(not applying and not failed)
        self.revert_btn.setVisible(not applying and not failed)
        self.close_btn.setVisible(failed)

    def _switch(self) -> None:
        if self.target == self.original:
            self.message.setText(f"The display is already at {self.target}.")
            self.countdown.setText("")
            self._show_buttons(applying=False, failed=True)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            how = display.set_mode(self.target, self.qres, self.temporary)
        except display.DisplayError as exc:
            self._failed(exc)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.switched = True
        self.message.setText(f"Now at {self.target}  (via {how}).  Keep it?")
        self._show_buttons(applying=False)
        self._update_countdown()
        self.timer.start()

    def _failed(self, exc: Exception) -> None:
        text = str(exc)
        if not display.is_size_available(self.target.width, self.target.height):
            text += ("\n\n" + f"Windows isn't offering {self.target.width} × {self.target.height}. "
                     "Create it as a custom resolution in your graphics control panel "
                     "(NVIDIA, AMD or Intel) first, then try again.")
        self.message.setText("Couldn't switch.")
        theme.set_state(self.countdown, "warn", text)
        self._show_buttons(applying=False, failed=True)

    def _keep(self) -> None:
        self.kept = True
        self.accept()

    def _tick(self) -> None:
        self.remaining -= 1
        if self.remaining <= 0:
            self.reject()
        else:
            self._update_countdown()

    def _update_countdown(self) -> None:
        self.countdown.setText(f"Reverts to {self.original} in {self.remaining} s if you don't keep it.")

    def done(self, result: int) -> None:
        self.timer.stop()
        if self.switched and not self.kept:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                display.set_mode(self.original, self.qres, self.temporary)
            except display.DisplayError:
                pass  # the main window's Restore button covers this
            finally:
                QApplication.restoreOverrideCursor()
        super().done(result)


class PresetEditor(QDialog):
    """Add or edit a single preset."""

    def __init__(self, parent, modes: list[display.Mode], preset: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit preset" if preset else "Add preset")
        self.setMinimumWidth(440)
        self.modes = modes
        current = display.current_mode()

        self.name = QLineEdit(placeholderText="Optional (defaults to the resolution)")
        self.width = QSpinBox(minimum=320, maximum=15360, singleStep=10)
        self.height = QSpinBox(minimum=240, maximum=8640, singleStep=10)
        self.width.setValue(int((preset or {}).get("width") or current.width))
        self.height.setValue(int((preset or {}).get("height") or current.height))
        self.refresh = QComboBox()
        self.name.setText(str((preset or {}).get("name") or ""))

        size_row = QHBoxLayout()
        size_row.addWidget(self.width)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.height)
        size_row.addStretch()

        self.status = QLabel(wordWrap=True)
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Resolution", size_row)
        form.addRow("Refresh rate", self.refresh)
        form.addRow("", self.status)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

        self.width.valueChanged.connect(self._refresh_rates)
        self.height.valueChanged.connect(self._refresh_rates)
        self._refresh_rates(select=int((preset or {}).get("refresh") or 0))

    def _refresh_rates(self, *_args, select: int | None = None) -> None:
        want = select if select is not None else int(self.refresh.currentData() or 0)
        rates = display.refresh_rates(self.width.value(), self.height.value(), self.modes)
        self.refresh.blockSignals(True)
        self.refresh.clear()
        self.refresh.addItem("Same as desktop", 0)
        for rate in rates:
            self.refresh.addItem(f"{rate} Hz", rate)
        self.refresh.setCurrentIndex(max(self.refresh.findData(want), 0))
        self.refresh.blockSignals(False)

        if display.is_size_available(self.width.value(), self.height.value(), self.modes):
            theme.set_state(self.status, "ok", "✓  Windows offers this resolution.")
        else:
            theme.set_state(self.status, "warn",
                            "Windows isn't offering this resolution. Create it as a custom resolution in your "
                            "graphics control panel (NVIDIA, AMD or Intel) first, or the preset won't switch.")

    def preset(self) -> dict:
        return {"name": self.name.text().strip(), "width": self.width.value(), "height": self.height.value(),
                "refresh": int(self.refresh.currentData() or 0)}


class PresetsDialog(QDialog):
    """Manage the quick-switch presets and apply any of them."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Resolution presets")
        self.setMinimumSize(520, 400)
        self.presets: list[dict] = [dict(p) for p in win.cfg.get("presets", [])]

        intro = QLabel("Presets switch your primary display instantly. Applying one asks you to keep it, "
                       "and reverts on its own if you don't — so a bad mode can't strand you.", wordWrap=True)
        intro.setObjectName("muted")
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._sync_buttons)
        self.list.itemDoubleClicked.connect(lambda _i: self._apply())

        self.apply_btn = QPushButton("Apply", objectName="primary", clicked=self._apply)
        add = QPushButton("Add…", clicked=self._add)
        from_current = QPushButton("Add current", clicked=self._add_current)
        self.edit_btn = QPushButton("Edit…", clicked=self._edit)
        self.remove_btn = QPushButton("Remove", clicked=self._remove)
        self.up_btn = QPushButton("↑", clicked=lambda: self._move(-1))
        self.down_btn = QPushButton("↓", clicked=lambda: self._move(1))
        buttons = QVBoxLayout()
        for b in (self.apply_btn, add, from_current, self.edit_btn, self.remove_btn, self.up_btn, self.down_btn):
            buttons.addWidget(b)
        buttons.addStretch()

        body = QHBoxLayout()
        body.addWidget(self.list, 1)
        body.addLayout(buttons)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(body, 1)
        layout.addWidget(close)
        self._reload()

    def _reload(self, select: int | None = None) -> None:
        self.list.clear()
        for preset in self.presets:
            available = display.is_size_available(preset["width"], preset["height"], self.win.modes)
            text = f"{preset_name(preset)}    ·    {preset_label(preset)}"
            if not available:
                text += "    ·    needs a custom resolution"
            item = QListWidgetItem(text)
            if not available:
                item.setForeground(theme.QColor(theme.WARN))
            self.list.addItem(item)
        if self.presets:
            self.list.setCurrentRow(min(select if select is not None else 0, len(self.presets) - 1))
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        row = self.list.currentRow()
        has = row >= 0
        for b in (self.apply_btn, self.edit_btn, self.remove_btn):
            b.setEnabled(has)
        self.up_btn.setEnabled(has and row > 0)
        self.down_btn.setEnabled(has and row < len(self.presets) - 1)

    def _save(self) -> None:
        self.win.cfg["presets"] = [dict(p) for p in self.presets]
        self.win.save_presets()

    def _add(self) -> None:
        editor = PresetEditor(self, self.win.modes)
        if editor.exec():
            self.presets.append(editor.preset())
            self._save()
            self._reload(len(self.presets) - 1)

    def _add_current(self) -> None:
        mode = display.current_mode()
        self.presets.append({"name": "", "width": mode.width, "height": mode.height, "refresh": 0})
        self._save()
        self._reload(len(self.presets) - 1)

    def _edit(self) -> None:
        row = self.list.currentRow()
        editor = PresetEditor(self, self.win.modes, self.presets[row])
        if editor.exec():
            self.presets[row] = editor.preset()
            self._save()
            self._reload(row)

    def _remove(self) -> None:
        row = self.list.currentRow()
        del self.presets[row]
        self._save()
        self._reload(row)

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        new = row + delta
        self.presets[row], self.presets[new] = self.presets[new], self.presets[row]
        self._save()
        self._reload(new)

    def _apply(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.win.apply_preset(self.presets[row])
