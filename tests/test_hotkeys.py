"""Global-hotkey string parsing (no real hotkeys registered)."""

import pytest

from qres_gui.gui import hotkeys

CTRL, ALT, SHIFT, WIN = hotkeys.MOD_CONTROL, hotkeys.MOD_ALT, hotkeys.MOD_SHIFT, hotkeys.MOD_WIN


@pytest.mark.parametrize("sequence, expected", [
    ("Ctrl+Alt+1", (CTRL | ALT, 0x31)),
    ("Ctrl+Shift+A", (CTRL | SHIFT, 0x41)),
    ("Alt+F4", (ALT, 0x73)),
    ("Ctrl+Alt+Home", (CTRL | ALT, 0x24)),
    ("Meta+Up", (WIN, 0x26)),
    ("Ctrl+Alt+F12", (CTRL | ALT, 0x7B)),
])
def test_parse_valid(sequence, expected):
    assert hotkeys.parse(sequence) == expected


@pytest.mark.parametrize("sequence", [
    "", "A",            # no modifier -> would hijack the key globally
    "Ctrl",             # modifier only
    "Ctrl+Alt+A+B",     # two non-modifier keys
    "Ctrl+F25",         # out of range
    "Ctrl+ñ",           # unknown key
])
def test_parse_rejected(sequence):
    assert hotkeys.parse(sequence) is None
