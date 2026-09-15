"""Settings shared by the whole suite."""

import pytest


@pytest.fixture(autouse=True, scope="session")
def no_real_appdata(tmp_path_factory):
    """A throwaway %APPDATA% for anything that runs before a test sets its own.

    The Qt app is made once per session and its theme writes the dropdown
    chevrons under %APPDATA%\\QResGUI\\ui - which, without this, is the real one.
    """
    patch = pytest.MonkeyPatch()
    patch.setenv("APPDATA", str(tmp_path_factory.mktemp("AppData")))
    yield
    patch.undo()


@pytest.fixture(autouse=True)
def no_real_install(tmp_path_factory, monkeypatch):
    """Keep every test away from a real QRes GUI install.

    Hooks follow the installed copy (`paths.hook_command`), which is found under
    %LOCALAPPDATA%. On a developer's PC that is a real install, so without this
    the same test would pass on CI and behave differently at home.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path_factory.mktemp("LocalAppData")))
