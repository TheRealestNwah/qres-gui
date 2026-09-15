"""Engine options (#14): telling the engine from the install folder, and turning choices into flags."""

import pytest

from qres_gui import config, engines


@pytest.fixture(autouse=True)
def fresh_detection():
    engines.detect.cache_clear()
    yield
    engines.detect.cache_clear()


def test_a_unity_game_is_told_by_its_player_dll(tmp_path):
    (tmp_path / "UnityPlayer.dll").write_bytes(b"MZ")
    assert engines.detect(str(tmp_path)) == engines.UNITY


def test_an_older_unity_game_is_told_by_its_data_folder(tmp_path):
    (tmp_path / "Game_Data").mkdir()
    (tmp_path / "Game_Data" / "globalgamemanagers").write_bytes(b"")
    assert engines.detect(str(tmp_path)) == engines.UNITY


def test_an_unreal_game_is_told_by_its_shipping_exe(tmp_path):
    exe = tmp_path / "Quarry" / "Binaries" / "Win64" / "Quarry-Win64-Shipping.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    assert engines.detect(str(tmp_path)) == engines.UNREAL


def test_an_unreal_game_is_told_by_its_engine_folder(tmp_path):
    (tmp_path / "Engine" / "Binaries").mkdir(parents=True)
    assert engines.detect(str(tmp_path)) == engines.UNREAL


@pytest.mark.parametrize("folder", ["", "does-not-exist"])
def test_no_folder_means_no_engine(tmp_path, folder):
    assert engines.detect(str(tmp_path / folder) if folder else "") is None


def test_anything_else_is_no_engine(tmp_path):
    (tmp_path / "game.exe").write_bytes(b"MZ")
    (tmp_path / "data.pak").write_bytes(b"")
    assert engines.detect(str(tmp_path)) is None


@pytest.mark.parametrize("choices, expected", [
    ({"engine": "unity", "window": "borderless"}, ["-screen-fullscreen", "1", "-window-mode", "borderless"]),
    ({"engine": "unity", "window": "windowed", "api": "d3d12"}, ["-screen-fullscreen", "0", "-force-d3d12"]),
    ({"engine": "unity", "monitor": "2"}, ["-monitor", "2"]),
    ({"engine": "unreal", "window": "windowed", "api": "vulkan"}, ["-windowed", "-vulkan"]),
])
def test_choices_become_the_engines_documented_flags(choices, expected):
    assert engines.flags(choices) == expected


@pytest.mark.parametrize("choices", [
    None, "not a dict", {}, {"engine": "godot", "window": "windowed"},      # unknown engine
    {"engine": "unity", "window": "sideways"},                               # unknown value
    {"engine": "unity", "monitor": "0"}, {"engine": "unity", "monitor": "x"},  # no such monitor
    {"engine": "unreal", "monitor": "2"},                                    # Unreal has no monitor option
])
def test_anything_unknown_adds_nothing(choices):
    assert engines.flags(choices) == []


def test_engine_options_go_before_the_users_own_arguments():
    """So typed arguments can override an engine option."""
    entry = {"engine_args": {"engine": "unreal", "api": "d3d12"}, "extra_args": "-dx11",
             "launch": {"type": "exe", "path": "game.exe", "args": "-store"}}
    assert config.extra_args(entry) == "-dx12 -dx11"
    assert config.full_args(entry) == "-store -dx12 -dx11"
