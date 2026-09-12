# PyInstaller spec: builds QResGUI.exe and QResLauncher.exe into one folder.
# The launcher leaves Qt out, so it starts quickly when Steam runs it.
from pathlib import Path

root = Path(SPECPATH)
icon = str(root / "build" / "icon.ico")

gui = Analysis([str(root / "QResGUI.pyw")], pathex=[str(root)], excludes=["tkinter"])
launcher = Analysis([str(root / "QResLauncher.pyw")], pathex=[str(root)], excludes=["tkinter", "PySide6", "shiboken6"])

# PySide6's hooks pull in Qt modules the GUI never uses (QML/Quick, PDF,
# network, SVG, OpenGL, and the GPL-only Virtual Keyboard) through plugins.
# Leaving them out keeps the download smaller and its licensing to LGPL Qt
# Core/GUI/Widgets. See THIRD_PARTY_NOTICES.md.
UNUSED_QT = (
    "qt6qml", "qt6quick", "qt6pdf", "qt6virtualkeyboard", "qt6network", "qt6opengl", "qt6svg", "\\qtnetwork.",
    "opengl32sw.dll", "\\qml\\", "\\platforminputcontexts\\", "\\tls\\", "\\networkinformation\\",
    "\\iconengines\\", "\\generic\\", "\\imageformats\\qsvg", "\\imageformats\\qpdf",
)


def used(entries):
    return [e for e in entries if not any(part in e[0].lower() for part in UNUSED_QT)]


gui.binaries = used(gui.binaries)
gui.datas = used(gui.datas)

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="QResGUI",
              console=False, icon=icon, upx=False)
launcher_exe = EXE(PYZ(launcher.pure), launcher.scripts, [], exclude_binaries=True, name="QResLauncher",
                   console=False, icon=icon, upx=False)

COLLECT(gui_exe, gui.binaries, gui.datas,
        launcher_exe, launcher.binaries, launcher.datas,
        name="QResGUI", upx=False)
