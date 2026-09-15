"""Which launcher hooks point at: the installed copy's, whichever copy is asking (#12)."""

import sys

import pytest

from qres_gui import paths


@pytest.fixture
def installed():
    """A QRes GUI install where install.ps1 puts one (LOCALAPPDATA is a temp folder, see conftest)."""
    folder = paths.installed_folder()
    folder.mkdir(parents=True)
    (folder / "QResLauncher.exe").write_bytes(b"MZ")
    (folder / "QResGUI.exe").write_bytes(b"MZ")
    return folder


def _running_from(monkeypatch, exe):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))


def test_hooks_use_the_installed_launcher_when_there_is_one(installed):
    assert paths.hook_command() == [str(installed / "QResLauncher.exe")]


def test_an_unzipped_copy_still_hooks_the_installed_launcher(installed, monkeypatch, tmp_path):
    """The bug: a test copy offered to repoint every hook at itself, then got deleted."""
    copy = tmp_path / "Desktop" / "QResGUI-1.5.0-win64"
    _running_from(monkeypatch, copy / "QResGUI.exe")
    assert paths.launcher_command() == [str(copy / "QResLauncher.exe")]      # its own, for Play
    assert paths.hook_command() == [str(installed / "QResLauncher.exe")]     # but hooks stay put
    assert not paths.is_installed_copy() and paths.runs_installed_hooks()


def test_the_installed_copy_knows_it_is(installed, monkeypatch):
    _running_from(monkeypatch, installed / "QResGUI.exe")
    assert paths.is_installed_copy() and not paths.runs_installed_hooks()
    assert paths.hook_command() == paths.launcher_command()


def test_with_nothing_installed_hooks_point_at_the_running_copy(monkeypatch, tmp_path):
    """Portable use: there's nowhere else to point them."""
    copy = tmp_path / "Portable"
    _running_from(monkeypatch, copy / "QResGUI.exe")
    assert paths.installed_launcher() is None
    assert paths.hook_command() == [str(copy / "QResLauncher.exe")]
    assert not paths.runs_installed_hooks()


def test_running_from_source_is_never_the_installed_copy(installed):
    assert not getattr(sys, "frozen", False)
    assert not paths.is_installed_copy() and paths.runs_installed_hooks()
