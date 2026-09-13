"""Render README screenshots offscreen from a made-up demo library.

    .venv\\Scripts\\python tools\\screenshots.py      ->  docs\\screenshots\\*.png

Nothing here reads the real machine: stores, Steam, Playnite and display
modes are all stand-ins, and the game names are fictional (no store artwork).
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="qres-shots-")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qres_gui import display, paths, playnite, shortcuts, updates  # noqa: E402
from qres_gui.gui import main_window, theme  # noqa: E402
from qres_gui.gui.dialogs import PlayniteDialog, SettingsDialog  # noqa: E402
from qres_gui.stores import Game, steam  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
LAUNCHER = [r"C:\Users\You\AppData\Local\Programs\QResGUI\QResLauncher.exe"]
MODES = [display.Mode(w, h, r) for w, h in ((3440, 1440), (2560, 1440), (2560, 1080), (1920, 1080))
         for r in (165, 144, 60)]
work = Path(os.environ["APPDATA"])

display.list_modes = lambda: list(MODES)
display.current_mode = lambda: MODES[0]
display.find_qres = lambda *a: r"C:\Tools\QRes\QRes.exe"
display.monitor_count = lambda: 1
display.set_mode = lambda *a, **k: "stub"  # screenshots must never change the real resolution
updates.check = lambda current=None: None
paths.launcher_command = lambda: list(LAUNCHER)
shortcuts.desktop_dir = lambda: work / "Desktop"
shortcuts.start_menu_dir = lambda: work / "Programs" / "QRes GUI"
(work / "Desktop").mkdir()
(work / "Desktop" / "Ashen Vale (QRes).lnk").write_bytes(b"lnk")

playnite_cfg = work / "Playnite" / "config.json"
playnite_cfg.parent.mkdir()
playnite_cfg.write_text(json.dumps({"PreScript": None, "PostScript": None}), encoding="utf-8")
playnite.config_path = lambda: playnite_cfg
playnite.is_running = lambda: False
playnite.install(LAUNCHER)

demo = [
    ("steam:101", "Starfall Tactics", "steam"), ("steam:102", "Neon Harbor", "steam"),
    ("steam:103", "Copper Skies", "steam"), ("gog:201", "Ashen Vale", "gog"),
    ("legendary:Rift", "Riftbound Legends", "legendary"), ("xbox:Lumen", "Lumen Drift", "xbox"),
    ("ea:301", "Velocity Circuit", "ea"), ("playnite:9f2", "Hollow Crown", "playnite"),
]
games = [Game(id=gid, name=name, store=store, install_dir=rf"D:\Games\{name}",
              launch={"type": "exe", "path": rf"D:\Games\{name}\game.exe", "args": "", "cwd": ""}
              if store == "gog" else None)
         for gid, name, store in demo]


class DemoSteam:
    available = True
    options = {"101": steam.apply_ours("-novid", steam.launch_prefix(LAUNCHER, "steam:101")),
               "103": steam.apply_ours("", steam.launch_prefix(LAUNCHER, "steam:103"))}

    def is_running(self):
        return False

    def launch_options(self):
        return dict(self.options)


main_window.detect_all = lambda client: (list(games), [])
main_window.SteamClient = DemoSteam

app = QApplication([])
app.setFont(QFont("Segoe UI", 9))
theme.apply(app)
OUT.mkdir(parents=True, exist_ok=True)

win = main_window.MainWindow()
win.cfg["presets"] = [{"name": "1440p", "width": 2560, "height": 1440, "refresh": 0},
                      {"name": "Cinema", "width": 2560, "height": 1080, "refresh": 0},
                      {"name": "", "width": 1920, "height": 1080, "refresh": 120}]
win._refresh_presets()
for gid, width, height in (("steam:101", 2560, 1440), ("steam:103", 2560, 1080), ("gog:201", 2560, 1440),
                           ("legendary:Rift", 1920, 1080)):
    entry = win.entry_for(win.games[gid], create=True)
    entry.update(enabled=True, width=width, height=height)
win.playnite_state = playnite.state(LAUNCHER)
win.refresh_rows()
win.resize(1360, 820)
win.show()
win.tree.setCurrentItem(win.items["steam:101"])
app.processEvents()
win.grab().save(str(OUT / "main.png"))

for name, dialog in (("playnite", PlayniteDialog(win)), ("settings", SettingsDialog(win, win.cfg, win.modes,
                                                                                   on_remove_hooks=lambda: None,
                                                                                   on_playnite=lambda: None,
                                                                                   on_check_updates=lambda: (None, "")))):
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(OUT / f"{name}.png"))
    dialog.close()

from qres_gui.gui.presets import PresetsDialog  # noqa: E402
pd = PresetsDialog(win)
pd.show()
app.processEvents()
pd.grab().save(str(OUT / "presets.png"))
pd.close()

from qres_gui.gui.guide import GettingStarted  # noqa: E402
guide = GettingStarted(win)
guide.show()
for page in range(guide.pages.count()):
    guide._go(page - guide.pages.currentIndex())
    app.processEvents()
    guide.grab().save(str(OUT / f"guide-{page + 1}.png"))
guide.close()
print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.png"))))


