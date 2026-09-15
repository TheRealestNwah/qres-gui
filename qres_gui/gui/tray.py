"""System-tray icon: current resolution, presets, restore, show/quit.

Rebuilt from the config whenever presets change.
"""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import display
from . import theme
from .presets import preset_device, preset_label, preset_name


class Tray(QSystemTrayIcon):
    def __init__(self, win):
        super().__init__(theme.app_icon(), win)
        self.win = win
        self.setToolTip("QRes GUI")
        self.menu = QMenu()
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)
        self.rebuild()

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def rebuild(self) -> None:
        self.menu.clear()
        try:
            current = display.current_mode()
            header = self.menu.addAction(f"Now: {current}")
        except display.DisplayError:
            current = None
            header = self.menu.addAction("QRes GUI")
        header.setEnabled(False)
        self.menu.addSeparator()

        presets = self.win.cfg.get("presets", [])
        if presets:
            for preset in presets:
                action = QAction(f"{preset_name(preset)}  ·  {preset_label(preset)}", self.menu)
                # A preset naming another screen is matched against that screen,
                # not against the primary the header shows.
                screen = preset_device(preset)
                if screen:
                    try:
                        here = display.current_mode(screen)
                    except display.DisplayError:
                        here = None
                else:
                    here = current
                if here and (here.width, here.height) == (preset["width"], preset["height"]):
                    action.setText("● " + action.text())
                action.triggered.connect(lambda _c=False, p=preset: self.win.apply_preset(p))
                self.menu.addAction(action)
            self.menu.addSeparator()

        self.menu.addAction("Restore desktop resolution", self.win.restore_desktop)
        self.menu.addSeparator()
        self.menu.addAction("Open QRes GUI", self.win.show_from_tray)
        self.menu.addAction("Quit", self.win.quit_app)
        self.setToolTip(f"QRes GUI — {current}" if current else "QRes GUI")

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.win.show_from_tray()
