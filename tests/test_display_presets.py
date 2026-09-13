"""display helpers used by presets (no real resolution changes)."""

from qres_gui import display
from qres_gui.gui import presets

MODES = [display.Mode(3440, 1440, 165), display.Mode(2560, 1440, 165), display.Mode(2560, 1440, 60),
         display.Mode(1920, 1080, 120)]


def test_available_sizes_and_membership():
    assert display.available_sizes(MODES) == [(3440, 1440), (2560, 1440), (1920, 1080)]
    assert display.is_size_available(2560, 1440, MODES)
    assert not display.is_size_available(5120, 2160, MODES)


def test_preset_labels():
    assert presets.preset_label({"width": 2560, "height": 1440, "refresh": 0}) == "2560 × 1440"
    assert presets.preset_label({"width": 1920, "height": 1080, "refresh": 120}) == "1920 × 1080 @ 120 Hz"
    assert presets.preset_name({"name": " ", "width": 2560, "height": 1440, "refresh": 0}) == "2560 × 1440"
    assert presets.preset_name({"name": "Cinema", "width": 2560, "height": 1080, "refresh": 0}) == "Cinema"
