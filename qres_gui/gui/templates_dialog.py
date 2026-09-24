"""Profile templates in the window (#38): picking games to put settings on, and managing saved templates.

What a template carries, and what it leaves alone, is `qres_gui.templates`."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from .. import templates

ROLE_ID = Qt.ItemDataRole.UserRole


def _games(n: int) -> str:
    return f"{n} game" if n == 1 else f"{n} games"


class ApplyToGamesDialog(QDialog):
    """Tick the games a set of settings goes onto: a saved template, or another game's."""

    def __init__(self, win, template: dict, title: str, checked=(), exclude: str | None = None):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(title)
        self.setMinimumSize(520, 560)

        intro = QLabel("Every game you tick gets these settings in place of its own. Each keeps its store, "
                       "launch options and shortcuts, and its process names and extra arguments.",
                       wordWrap=True, objectName="muted")
        sets = QGroupBox("Sets")
        sets_layout = QVBoxLayout(sets)
        self.summary = QLabel("\n".join(templates.summary(template)), wordWrap=True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sets_layout.addWidget(self.summary)

        self.search = QLineEdit(placeholderText="Search games…", clearButtonEnabled=True)
        self.search.textChanged.connect(self._filter)
        self.list = QListWidget()
        hidden = win.hidden_ids()
        games = sorted(win.games.values(), key=lambda g: g.name.casefold())
        for game in games:
            if game.id == exclude or (game.id in hidden and game.id not in checked):
                continue
            item = QListWidgetItem(f"{game.name}    ·    {game.store_label}")
            item.setData(ROLE_ID, game.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if game.id in checked else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.itemChanged.connect(self._count)
        self.list.itemActivated.connect(self._toggle)

        tick_shown = QPushButton("Tick all shown", clicked=lambda: self._tick_shown(True))
        untick = QPushButton("Untick all", clicked=self._untick_all)
        row = QHBoxLayout()
        row.addWidget(self.search, 1)
        row.addWidget(tick_shown)
        row.addWidget(untick)

        self.enable = QCheckBox("Turn switching on for them", checked=True)
        self.enable.setToolTip("Steam games also need their launch options updated, as usual; the Launch hook "
                               "column says which games still need hooking up.")

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(sets)
        layout.addLayout(row)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.enable)
        layout.addWidget(self.buttons)
        self._count()

    def _items(self) -> list[QListWidgetItem]:
        return [self.list.item(i) for i in range(self.list.count())]

    def _filter(self) -> None:
        needle = self.search.text().strip().casefold()
        for item in self._items():
            item.setHidden(bool(needle) and needle not in item.text().casefold())

    def _toggle(self, item: QListWidgetItem) -> None:
        checked = item.checkState() == Qt.CheckState.Checked
        item.setCheckState(Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked)

    def _tick_shown(self, on: bool) -> None:
        for item in self._items():
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _untick_all(self) -> None:
        for item in self._items():
            item.setCheckState(Qt.CheckState.Unchecked)

    def _count(self, *_args) -> None:
        n = len(self.chosen())
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(f"Apply to {_games(n)}" if n else "Apply")
        ok.setEnabled(bool(n))

    def chosen(self) -> list[str]:
        return [item.data(ROLE_ID) for item in self._items() if item.checkState() == Qt.CheckState.Checked]


class TemplatesDialog(QDialog):
    """The saved templates: apply one to games, rename or remove it."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Profile templates")
        self.setMinimumSize(520, 380)

        intro = QLabel("A template is a game's display, audio and command settings, saved to put onto other "
                       "games. To make one, right-click a game set up the way you want and choose "
                       "Save settings as template…", wordWrap=True, objectName="muted")
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._sync_buttons)
        self.list.itemDoubleClicked.connect(lambda _i: self._apply())
        self.empty = QLabel("No templates yet.", objectName="muted", alignment=Qt.AlignmentFlag.AlignCenter)

        self.apply_btn = QPushButton("Apply to games…", objectName="primary", clicked=self._apply)
        self.rename_btn = QPushButton("Rename…", clicked=self._rename)
        self.remove_btn = QPushButton("Remove", clicked=self._remove)
        buttons = QVBoxLayout()
        for button in (self.apply_btn, self.rename_btn, self.remove_btn):
            buttons.addWidget(button)
        buttons.addStretch()
        body = QHBoxLayout()
        column = QVBoxLayout()
        column.addWidget(self.list, 1)
        column.addWidget(self.empty)
        body.addLayout(column, 1)
        body.addLayout(buttons)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(body, 1)
        layout.addWidget(close)
        self._reload()

    def _reload(self, select: int = 0) -> None:
        saved = self.win.templates()
        self.list.clear()
        for template in saved:
            lines = templates.summary(template)
            item = QListWidgetItem(f"{template['name']}    ·    {lines[0]}")
            item.setToolTip("\n".join(lines))
            self.list.addItem(item)
        self.list.setVisible(bool(saved))
        self.empty.setVisible(not saved)
        if saved:
            self.list.setCurrentRow(min(select, len(saved) - 1))
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has = self.list.currentRow() >= 0
        for button in (self.apply_btn, self.rename_btn, self.remove_btn):
            button.setEnabled(has)

    def _current(self) -> dict | None:
        row = self.list.currentRow()
        saved = self.win.templates()
        return saved[row] if 0 <= row < len(saved) else None

    def _apply(self) -> None:
        template = self._current()
        if template:
            self.win.apply_template_to_picked(template)

    def _rename(self) -> None:
        row = self.list.currentRow()
        template = self._current()
        if template is None:
            return
        name, ok = QInputDialog.getText(self, "Rename template", "Name", text=template["name"])
        name = name.strip()
        if not ok or not name or name == template["name"]:
            return
        saved = self.win.templates()
        clash = templates.find(saved, name)
        if clash not in (-1, row):
            QMessageBox.information(self, "Rename template", f"There's already a template called “{name}”.")
            return
        saved[row]["name"] = name
        self.win.set_templates(saved)
        self._reload(row)

    def _remove(self) -> None:
        row = self.list.currentRow()
        saved = self.win.templates()
        if 0 <= row < len(saved):
            # Games it was applied to keep their settings; a template is only ever copied onto them.
            del saved[row]
            self.win.set_templates(saved)
            self._reload(row)
