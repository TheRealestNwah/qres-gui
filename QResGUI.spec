# PyInstaller spec: builds QResGUI.exe and QResLauncher.exe into one folder.
# The launcher leaves Qt out, so it starts quickly when Steam runs it.
from pathlib import Path

root = Path(SPECPATH)
icon = str(root / "build" / "icon.ico")

gui = Analysis([str(root / "QResGUI.pyw")], pathex=[str(root)], excludes=["tkinter"])
launcher = Analysis([str(root / "QResLauncher.pyw")], pathex=[str(root)], excludes=["tkinter", "PySide6", "shiboken6"])

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="QResGUI",
              console=False, icon=icon, upx=False)
launcher_exe = EXE(PYZ(launcher.pure), launcher.scripts, [], exclude_binaries=True, name="QResLauncher",
                   console=False, icon=icon, upx=False)

COLLECT(gui_exe, gui.binaries, gui.datas,
        launcher_exe, launcher.binaries, launcher.datas,
        name="QResGUI", upx=False)
