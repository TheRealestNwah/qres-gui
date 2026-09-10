import pytest

from qres_gui.stores import steam

FROZEN = steam.launch_prefix([r"D:\Tools\QRes GUI\QResLauncher.exe"], "steam:620")
SOURCE = steam.launch_prefix([r"D:\p\.venv\Scripts\pythonw.exe", r"D:\p\QResLauncher.pyw"], "steam:620")


@pytest.mark.parametrize("prefix", [FROZEN, SOURCE])
@pytest.mark.parametrize("existing, expected_tail", [
    ("", "%command%"),
    ("-hz=165", "%command% -hz=165"),
    ("%command% -dx11", "%command% -dx11"),
    ('"D:\\Games\\FNV\\nvse_loader.exe" %command%', '"D:\\Games\\FNV\\nvse_loader.exe" %command%'),
])
def test_apply_keeps_user_options(prefix, existing, expected_tail):
    applied = steam.apply_ours(existing, prefix)
    assert applied == f"{prefix} {expected_tail}"
    assert steam.option_state(applied, prefix) == "applied"


@pytest.mark.parametrize("existing", ["", "-hz=165", '"D:\\x\\loader.exe" %command%', "-a -b"])
def test_strip_restores_original(existing):
    stripped, found = steam.strip_ours(steam.apply_ours(existing, FROZEN))
    assert found
    assert stripped == existing


def test_apply_is_idempotent_and_replaces_old_path():
    once = steam.apply_ours("-novid", FROZEN)
    assert steam.apply_ours(once, FROZEN) == once
    moved = steam.apply_ours(once, SOURCE)
    assert moved == f"{SOURCE} %command% -novid"
    assert steam.option_state(once, SOURCE) == "outdated"


def test_foreign_options_untouched():
    for options in ["-hz=165", '"D:\\OpenMW\\openmw.exe" %command%', "/resolution 2560 1440"]:
        assert steam.strip_ours(options) == (options, False)
        assert steam.option_state(options, FROZEN) == "none"
