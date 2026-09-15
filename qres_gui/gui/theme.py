"""Dark Fusion palette, stylesheet and the painted app icon."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel

from .. import paths

ACCENT = "#5b8def"
OK = "#5fd38d"
WARN = "#f0b54a"
ERROR = "#ef6b6b"
MUTED = "#8b919b"
# Borders for fields. Bright enough to read against the window: at #33373e a
# dropdown's outline all but vanished (#9).
FIELD_BORDER = "#4a4f58"
FIELD_HOVER = "#5d636e"
ARROW = "#b9bec6"
ARROW_DISABLED = "#5a5f68"
PILL_HEIGHT = 30   # the store filter's pill: its radius in the stylesheet is half this

STORE_COLORS = {
    "steam": "#4c9be8",
    "gog": "#b066db",
    "epic": "#c9cdd3",
    "ubisoft": "#35c0ae",
    "heroic": "#e0736a",
    "amazon": "#d9a14a",
    "legendary": "#c9cdd3",
    "nile": "#d9a14a",
    "ea": "#ff6b5a",
    "battlenet": "#3fa8ff",
    "xbox": "#62c462",
    "playnite": "#b98cff",
    "manual": "#8b93a1",
}

STYLESHEET = f"""
QWidget {{ font-size: 13px; }}
QFrame#topBar {{ background: #16181b; border-bottom: 1px solid #2a2d33; }}
QFrame#eventBar {{ background: #2a2518; border-bottom: 1px solid #4a3f22; }}
QFrame#updateBar {{ background: #1b2638; border-bottom: 1px solid #2c3f60; }}
QFrame#quickBar {{ background: #191b1f; border-bottom: 1px solid #2a2d33; }}
QPushButton#preset {{ padding: 3px 12px; border-radius: 12px; }}
QPushButton#presetActive {{
    padding: 3px 12px; border-radius: 12px; background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600;
}}
QPushButton#presetActive:hover {{ background: #6f9cf2; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#caption {{ color: {MUTED}; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }}
QLabel#warning {{ color: {WARN}; }}
QLabel#desktopMode {{ font-size: 17px; font-weight: 600; }}
QLabel#title {{ font-size: 21px; font-weight: 700; }}
QGroupBox {{
    border: 1px solid #2e3238; border-radius: 8px; margin-top: 16px;
    padding: 14px 12px 12px 12px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #aeb4bd; }}
QPushButton {{
    background: #2a2d33; border: 1px solid #3a3e46; border-radius: 6px; padding: 6px 12px;
}}
QPushButton:hover {{ background: #33373e; }}
QPushButton:pressed {{ background: #24272c; }}
QPushButton:disabled {{ color: #666b74; border-color: #2e3238; background: #24262b; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: #6f9cf2; }}
QPushButton#primary:disabled {{ background: #2c3850; border-color: #2c3850; color: #8791a3; }}
QLineEdit, QComboBox, QDoubleSpinBox {{
    background: #16181b; border: 1px solid {FIELD_BORDER}; border-radius: 6px; padding: 5px 8px;
}}
QComboBox, QDoubleSpinBox {{ background: #1b1d21; }}
QLineEdit:hover, QComboBox:hover, QDoubleSpinBox:hover {{ border-color: {FIELD_HOVER}; }}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled {{ border-color: #2e3238; color: #666b74; }}
QComboBox QAbstractItemView {{
    background: #1b1d21; border: 1px solid {FIELD_BORDER}; selection-background-color: #2f4a7a; outline: 0;
}}
QComboBox#pill {{ border-radius: {PILL_HEIGHT // 2}px; padding-left: 14px; }}
QLineEdit[readOnly="true"] {{ color: #b9bec6; background: #1a1c20; }}
QTreeWidget {{ border: 1px solid #2e3238; border-radius: 8px; padding: 2px; }}
QTreeWidget::item {{ padding: 3px 2px; }}
QListWidget {{ border: 1px solid #2e3238; border-radius: 8px; padding: 4px; }}
QListWidget::item {{ padding: 5px 6px; border-radius: 4px; }}
QHeaderView::section {{
    background: #1d1f23; color: #aeb4bd; border: none; border-bottom: 1px solid #2e3238; padding: 6px;
}}
QScrollArea {{ border: none; }}
QTabWidget::pane {{ border: 1px solid #2e3238; border-radius: 8px; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: #aeb4bd; padding: 7px 14px; border: none;
    border-bottom: 2px solid transparent; margin-right: 2px;
}}
QTabBar::tab:hover {{ color: #e4e6ea; }}
QTabBar::tab:selected {{ color: #e4e6ea; border-bottom-color: {ACCENT}; font-weight: 600; }}
QSplitter::handle {{ background: transparent; width: 8px; }}
QStatusBar {{ color: #aeb4bd; }}
QToolTip {{ background: #2a2d33; color: #e4e6ea; border: 1px solid #3a3e46; padding: 4px; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    role = QPalette.ColorRole
    palette = QPalette()
    for r, color in {
        role.Window: "#1d1f23", role.WindowText: "#e4e6ea", role.Base: "#16181b",
        role.AlternateBase: "#1a1c20", role.ToolTipBase: "#2a2d33", role.ToolTipText: "#e4e6ea",
        role.Text: "#e4e6ea", role.Button: "#2a2d33", role.ButtonText: "#e4e6ea",
        role.BrightText: "#ffffff", role.Highlight: "#2f4a7a", role.HighlightedText: "#ffffff",
        role.Link: ACCENT, role.PlaceholderText: "#6f757f", role.Mid: "#33373e",
        role.Dark: "#121316", role.Light: "#3a3e46",
    }.items():
        palette.setColor(r, QColor(color))
    for r in (role.Text, role.ButtonText, role.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, r, QColor("#666b74"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET + _arrows_css())


# --- the arrows on dropdowns and spin boxes -----------------------------------
#
# Once a combo box or spin box has a stylesheet border, Fusion stops drawing its
# arrow areas properly: the dropdown's arrow sat in a box of its own and the
# spin boxes' buttons shrank to a sliver (#9). Styling those parts means giving
# them images, and QtSvg isn't in the build, so the chevrons are painted here
# and written out as PNGs (with @2x copies for scaled displays) that the
# stylesheet points at.

def _chevron(up: bool, color: str, scale: int) -> QPixmap:
    w, h = 10 * scale, 6 * scale
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(color), 1.6 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    top, bottom = 1.2 * scale, h - 1.2 * scale
    y_ends, y_tip = (bottom, top) if up else (top, bottom)
    p.drawPolyline([QPointF(1.2 * scale, y_ends), QPointF(w / 2, y_tip), QPointF(w - 1.2 * scale, y_ends)])
    p.end()
    return pm


def _arrow_file(up: bool, color: str) -> str:
    """Path to a chevron PNG, written once per colour (a new colour gets a new name)."""
    folder = paths.app_dir() / "ui"
    folder.mkdir(exist_ok=True)
    stem = f"chevron-{'up' if up else 'down'}-{color.lstrip('#')}"
    target = folder / f"{stem}.png"
    for scale, name in ((1, f"{stem}.png"), (2, f"{stem}@2x.png")):
        if not (folder / name).exists():
            _chevron(up, color, scale).save(str(folder / name))
    return target.as_posix()


def _arrows_css() -> str:
    try:
        down, up = _arrow_file(False, ARROW), _arrow_file(True, ARROW)
        down_off, up_off = _arrow_file(False, ARROW_DISABLED), _arrow_file(True, ARROW_DISABLED)
    except OSError:
        return ""   # Fusion's own arrows are a worse look, not a broken one
    return f"""
QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none; background: transparent;
}}
QComboBox::down-arrow {{ image: url("{down}"); width: 10px; height: 6px; }}
QComboBox::down-arrow:disabled {{ image: url("{down_off}"); }}
QDoubleSpinBox {{ padding-right: 26px; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; width: 22px; border: none; border-left: 1px solid {FIELD_BORDER};
    background: transparent;
}}
QDoubleSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right; border-bottom-right-radius: 6px; border-top: 1px solid {FIELD_BORDER};
}}
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: #2a2d33; }}
QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 10px; height: 6px; }}
QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 10px; height: 6px; }}
QDoubleSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:off {{ image: url("{up_off}"); }}
QDoubleSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:off {{ image: url("{down_off}"); }}
"""


def set_state(label: QLabel, kind: str, text: str) -> None:
    """Colour a status label: kind is "ok", "warn", "error" or "off"."""
    color = {"ok": OK, "warn": WARN, "error": ERROR}.get(kind, MUTED)
    label.setText(text)
    label.setStyleSheet(f"color: {color}; font-weight: 600;")


def app_icon() -> QIcon:
    """An ultrawide monitor with a 16:9 picture inside it."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(icon_pixmap(size))
    return icon


def icon_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    s = size / 64
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(ACCENT))
    p.drawRoundedRect(QRectF(2 * s, 12 * s, 60 * s, 34 * s), 5 * s, 5 * s)
    p.setBrush(QColor("#16181b"))
    p.drawRoundedRect(QRectF(6 * s, 16 * s, 52 * s, 26 * s), 2 * s, 2 * s)
    p.setBrush(QColor("#a9c3f7"))
    p.drawRect(QRectF(20 * s, 16 * s, 24 * s, 26 * s))
    p.setBrush(QColor("#9aa3b2"))
    p.drawRect(QRectF(28 * s, 46 * s, 8 * s, 6 * s))
    p.drawRoundedRect(QRectF(18 * s, 51 * s, 28 * s, 5 * s), 2 * s, 2 * s)
    p.end()
    return pm
