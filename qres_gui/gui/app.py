from __future__ import annotations

import ctypes
import sys

from PySide6.QtWidgets import QApplication

from . import theme
from .main_window import MainWindow


def main() -> int:
    # Own taskbar identity, so Windows shows our icon rather than Python's.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("QResGUI")
    app = QApplication(sys.argv)
    app.setApplicationName("QRes GUI")
    app.setWindowIcon(theme.app_icon())
    # We manage quitting ourselves, so hiding the window to the tray doesn't exit.
    app.setQuitOnLastWindowClosed(False)
    theme.apply(app)
    window = MainWindow()
    # Started with Windows: straight to the tray, if there is one to open it from.
    if "--tray" in sys.argv[1:] and window.tray is not None:
        window.started_in_tray = True
    else:
        window.show()
    return app.exec()
