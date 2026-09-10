import glob
import os

import pytest

from qres_gui import vdf

STEAM = r"C:\Program Files (x86)\Steam"


def test_parse_nested_and_escapes():
    text = '"root"\n{\n\t"a"\t\t"1"\n\t"Opts"\t\t"\\"C:\\\\x y.exe\\" %command%"\n\t"sub"\n\t{\n\t}\n}\n'
    root = vdf.loads(text)
    block = root.block("ROOT")
    assert block.get("a") == "1"
    assert block.get("opts") == '"C:\\x y.exe" %command%'
    assert isinstance(block.get("sub"), vdf.KV)
    assert vdf.dumps(root) == text


def test_raw_tabs_in_values_round_trip():
    text = '"k"\n{\n\t"key"\t\t"Shift\tKEY_TAB"\n}\n'
    assert vdf.dumps(vdf.loads(text)) == text


def test_duplicate_keys_preserved():
    text = '"k"\n{\n\t"x"\t\t"1"\n\t"x"\t\t"2"\n}\n'
    assert vdf.dumps(vdf.loads(text)) == text


def test_block_create():
    root = vdf.KV()
    root.block("a", "b", create=True)["c"] = "d"
    assert vdf.loads(vdf.dumps(root)).block("a", "b").get("c") == "d"


def test_malformed_raises():
    with pytest.raises(ValueError):
        vdf.loads('"a"\n{\n"b" "c"\n')


real_files = (
    glob.glob(os.path.join(STEAM, "userdata", "*", "config", "localconfig.vdf"))
    + glob.glob(os.path.join(STEAM, "config", "loginusers.vdf"))
    + glob.glob(os.path.join(STEAM, "config", "config.vdf"))
    + glob.glob(os.path.join(STEAM, "steamapps", "*.acf"))
    + glob.glob(os.path.join(STEAM, "steamapps", "libraryfolders.vdf"))
)


@pytest.mark.skipif(not real_files, reason="no local Steam install")
@pytest.mark.parametrize("path", real_files)
def test_real_steam_files_round_trip_exactly(path):
    with open(path, encoding="utf-8", newline="") as fh:
        raw = fh.read()
    assert vdf.dumps(vdf.loads(raw)) == raw
