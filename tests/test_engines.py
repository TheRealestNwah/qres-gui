"""Engine options (#14): telling the engine from the install folder, and turning choices into flags."""

import pytest

from qres_gui import config, engines


@pytest.fixture(autouse=True)
def fresh_detection():
    engines.detect.cache_clear()
    yield
    engines.detect.cache_clear()


def unity_game(folder, exe="Dinkum.exe", marker="globalgamemanagers"):
    (folder / exe).write_bytes(b"MZ")
    data = folder / (exe[:-4] + "_Data")
    data.mkdir()
    (data / marker).write_bytes(b"")


def test_a_unity_game_is_told_by_its_exe_and_data_folder(tmp_path):
    unity_game(tmp_path)
    (tmp_path / "UnityPlayer.dll").write_bytes(b"MZ")
    (tmp_path / "UnityCrashHandler64.exe").write_bytes(b"MZ")   # Unity's own helper doesn't count
    assert engines.detect(str(tmp_path)) == engines.UNITY


@pytest.mark.parametrize("marker", ["mainData", "data.unity3d"])
def test_an_older_unity_game_is_told_by_its_data_folder(tmp_path, marker):
    unity_game(tmp_path, "Game.exe", marker)
    assert engines.detect(str(tmp_path)) == engines.UNITY


def test_a_unity_launcher_beside_another_engine_is_not_the_game(tmp_path):
    """The METAL GEAR SOLID Master Collection: a Unity launcher.exe next to the game's own exe."""
    unity_game(tmp_path, "launcher.exe")
    (tmp_path / "UnityPlayer.dll").write_bytes(b"MZ")
    (tmp_path / "Engine.dll").write_bytes(b"MZ")
    (tmp_path / "METAL GEAR SOLID2.exe").write_bytes(b"MZ")
    assert engines.detect(str(tmp_path)) is None


def test_unity_files_without_a_player_exe_are_not_a_unity_game(tmp_path):
    (tmp_path / "UnityPlayer.dll").write_bytes(b"MZ")
    (tmp_path / "Game_Data").mkdir()
    assert engines.detect(str(tmp_path)) is None


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


@pytest.mark.parametrize("engine, expected", [
    ("unity", ["-screen-width", "2560", "-screen-height", "1440"]),
    ("unreal", ["-ResX=2560", "-ResY=1440"]),
])
def test_start_at_the_games_resolution_reads_the_profile(engine, expected):
    entry = {"width": 2560, "height": 1440}
    assert engines.flags({"engine": engine, "resolution": "profile"}, entry) == expected


@pytest.mark.parametrize("entry", [None, {}, {"width": 0, "height": 1440}, {"width": "wide", "height": 1440}])
def test_no_size_in_the_profile_adds_no_resolution(entry):
    assert engines.flags({"engine": "unity", "resolution": "profile"}, entry) == []


def test_the_resolution_travels_with_the_rest_of_the_arguments():
    entry = {"width": 1920, "height": 1080, "extra_args": "-typed",
             "engine_args": {"engine": "unity", "window": "borderless", "resolution": "profile"}}
    assert config.extra_args(entry) == ("-screen-fullscreen 1 -window-mode borderless "
                                        "-screen-width 1920 -screen-height 1080 -typed")


def test_choices_for_an_engine_the_folder_no_longer_shows_add_nothing(tmp_path):
    """A profile saved while a Unity launcher made the game look like Unity keeps no stray flags."""
    entry = {"engine_args": {"engine": "unity", "window": "windowed"}, "extra_args": "-mine",
             "install_dir": str(tmp_path)}
    (tmp_path / "launcher.exe").write_bytes(b"MZ")
    (tmp_path / "launcher_Data").mkdir()
    (tmp_path / "launcher_Data" / "globalgamemanagers").write_bytes(b"")
    (tmp_path / "METAL GEAR SOLID2.exe").write_bytes(b"MZ")
    assert config.extra_args(entry) == "-mine"
    (tmp_path / "METAL GEAR SOLID2.exe").unlink()        # now launcher.exe is the only exe: a Unity game
    engines.detect.cache_clear()
    assert config.extra_args(entry) == "-screen-fullscreen 0 -mine"
    assert config.extra_args({**entry, "install_dir": ""}) == "-screen-fullscreen 0 -mine"   # folder unknown
