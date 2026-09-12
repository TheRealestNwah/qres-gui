"""Dark Fusion palette, stylesheet and the painted app icon."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QLabel

ACCENT = "#5b8def"
OK = "#5fd38d"
WARN = "#f0b54a"
ERROR = "#ef6b6b"
MUTED = "#8b919b"

STORE_COLORS = {
    "steam": "#4c9be8",
    "gog": "#b066db",
    "epic": "#c9cdd3",
    "ubisoft": "#35c0ae",
    "heroic": "#e0736a",
    "amazon": "#d9a14a",
    "legendary": "#c9cdd3",
    "nile": "#d9a14a",
    "manual": "#8b93a1",
}

STYLESHEET = f"""
QWidget {{ font-size: 13px; }}
QFrame#topBar {{ background: #16181b; border-bottom: 1px solid #2a2d33; }}
QFrame#eventBar {{ background: #2a2518; border-bottom: 1px solid #4a3f22; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#caption {{ color: {MUTED}; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }}
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
    background: #16181b; border: 1px solid #33373e; border-radius: 6px; padding: 5px 8px;
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit[readOnly="true"] {{ color: #b9bec6; background: #1a1c20; }}
QTreeWidget {{ border: 1px solid #2e3238; border-radius: 8px; padding: 2px; }}
QTreeWidget::item {{ padding: 3px 2px; }}
QHeaderView::section {{
    background: #1d1f23; color: #aeb4bd; border: none; border-bottom: 1px solid #2e3238; padding: 6px;
}}
QScrollArea {{ border: none; }}
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
    app.setStyleSheet(STYLESHEET)


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
