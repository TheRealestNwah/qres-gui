"""The update check: picking the newest release, and the launcher's diagnostic command."""

import io
import json

import pytest

from qres_gui import launcher, updates

RELEASES = [
    {"tag_name": "v0.9.0", "draft": True, "html_url": "draft"},          # not published
    {"tag_name": "v0.8.1", "html_url": "https://example/v0.8.1", "name": "QRes GUI 0.8.1"},
    {"tag_name": "v0.10.0", "html_url": "https://example/v0.10.0", "name": "QRes GUI 0.10.0"},
    {"tag_name": "nightly", "html_url": "x"},                            # not a version
    {"tag_name": "v0.7.0", "html_url": "https://example/v0.7.0"},
]


@pytest.mark.parametrize("current, expected", [
    ("0.8.0", "0.10.0"),   # numeric, not alphabetical: 0.10 > 0.9 > 0.8
    ("0.10.0", None),
    ("0.11.0", None),
    ("garbage", "0.10.0"),
])
def test_newest(current, expected):
    found = updates.newest(RELEASES, current)
    assert (found["version"] if found else None) == expected
    if found:
        assert found["url"] == "https://example/v0.10.0"


def test_from_1_0_only_finished_releases_are_offered():
    releases = [
        {"tag_name": "v1.1.0", "prerelease": True, "html_url": "pre"},
        {"tag_name": "v1.0.1", "prerelease": False, "html_url": "stable"},
    ]
    assert updates.newest(releases, "1.0.0")["version"] == "1.0.1"
    assert updates.newest(releases, "1.0.1") is None
    assert updates.newest(releases, "0.9.0")["version"] == "1.1.0"  # pre-1.0: every release counts


def test_is_newer():
    assert updates.is_newer("0.10.0", "0.9.9") and not updates.is_newer("0.8.0", "0.8.0")
    assert not updates.is_newer("", "0.8.0") and not updates.is_newer("0.9.0", "dev")


def test_fetch_sends_only_a_plain_request(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"], seen["headers"], seen["timeout"] = request.full_url, dict(request.header_items()), timeout
        return io.BytesIO(json.dumps(RELEASES).encode())

    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)
    assert updates.check("0.8.0")["version"] == "0.10.0"
    assert seen["url"] == updates.RELEASES_API and seen["timeout"] == 10
    assert set(seen["headers"]) == {"Accept", "User-agent"}


def test_launcher_check_update_command(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(updates, "check", lambda current=None: {"version": "9.9.9", "url": "u", "name": ""})
    assert launcher.main(["check-update"]) == 1
    monkeypatch.setattr(updates, "check", lambda current=None: None)
    assert launcher.main(["check-update"]) == 0
