"""Settings shared by the whole suite."""

import pytest


@pytest.fixture(autouse=True)
def no_real_install(tmp_path_factory, monkeypatch):
    """Keep every test away from a real QRes GUI install.

    Hooks follow the installed copy (`paths.hook_command`), which is found under
    %LOCALAPPDATA%. On a developer's PC that is a real install, so without this
    the same test would pass on CI and behave differently at home.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path_factory.mktemp("LocalAppData")))
