"""The update check and in-app install: picking the newest release, checking and unpacking its zip, and the hand-over."""

import hashlib
import io
import json
import subprocess
import sys
import zipfile

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


# --- installing an update -----------------------------------------------------------

ZIP_URL = updates.DOWNLOADS + "v9.9.9/QResGUI-9.9.9-win64.zip"
DIGEST = "sha256:" + "ab" * 32


def release_with(asset):
    return [{"tag_name": "v9.9.9", "html_url": "page", "assets": [asset]}]


def test_newest_offers_only_a_checkable_zip_from_this_project():
    asset = {"name": "QResGUI-9.9.9-win64.zip", "browser_download_url": ZIP_URL, "size": 123, "digest": DIGEST}
    assert updates.newest(release_with(asset), "1.0.0")["download"] == {"url": ZIP_URL, "size": 123,
                                                                          "sha256": "ab" * 32}
    for bad in ({"digest": ""},                                                  # nothing to check it against
                {"digest": "md5:abc"},
                {"browser_download_url": "https://example.com/QResGUI-9.9.9-win64.zip"},   # someone else's
                {"name": "QResGUI-9.9.8-win64.zip"}):                           # not this version's zip
        found = updates.newest(release_with({**asset, **bad}), "1.0.0")
        assert found["version"] == "9.9.9" and found["download"] is None
    assert updates.newest([{"tag_name": "v9.9.9"}], "1.0.0")["download"] is None


def serve(monkeypatch, payload: bytes):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        return io.BytesIO(payload)
    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_fetch_checks_the_digest(monkeypatch, tmp_path):
    payload = b"zip bytes" * 1000
    good = {"url": ZIP_URL, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    seen, progress = serve(monkeypatch, payload), []
    dest = updates.fetch(good, tmp_path / "u.zip", lambda done, total: progress.append((done, total)))
    assert dest.read_bytes() == payload and seen["url"] == ZIP_URL
    assert progress[-1] == (len(payload), len(payload))

    with pytest.raises(updates.UpdateError, match="checksum"):
        updates.fetch({**good, "sha256": "00" * 32}, tmp_path / "bad.zip")
    assert not (tmp_path / "bad.zip").exists()           # a file that failed the check isn't left behind


def test_fetch_refuses_other_addresses_and_can_be_cancelled(monkeypatch, tmp_path):
    serve(monkeypatch, b"x" * 600_000)
    with pytest.raises(updates.UpdateError, match="isn't a QRes GUI release"):
        updates.fetch({"url": "https://example.com/evil.zip", "sha256": ""}, tmp_path / "e.zip")
    with pytest.raises(updates.UpdateError, match="cancelled"):
        updates.fetch({"url": ZIP_URL, "sha256": ""}, tmp_path / "c.zip", lambda done, total: False)
    assert not (tmp_path / "c.zip").exists()

    def offline(request, timeout):
        raise OSError("no network")
    monkeypatch.setattr(updates.urllib.request, "urlopen", offline)
    with pytest.raises(updates.UpdateError, match="no network"):
        updates.fetch({"url": ZIP_URL, "sha256": ""}, tmp_path / "o.zip")


def make_zip(path, version="9.9.9", files=updates.REQUIRED, extra=()):
    with zipfile.ZipFile(path, "w") as archive:
        for name in files:
            archive.writestr(f"QResGUI-{version}-win64/{name}", version if name == "VERSION" else "x")
        for name, data in extra:
            archive.writestr(name, data)
    return path


def test_unpack_finds_the_release_folder(tmp_path):
    source = updates.unpack(make_zip(tmp_path / "u.zip", extra=[("../escape.txt", "x")]), tmp_path / "out", "9.9.9")
    assert source == tmp_path / "out" / "QResGUI-9.9.9-win64" and (source / "install.ps1").is_file()
    assert not (tmp_path / "escape.txt").exists()        # nothing lands outside the folder

    with pytest.raises(updates.UpdateError, match="holds version 9.9.8"):
        updates.unpack(make_zip(tmp_path / "old.zip", version="9.9.8"), tmp_path / "out2", "9.9.9")
    with pytest.raises(updates.UpdateError, match="install.ps1 is missing"):
        updates.unpack(make_zip(tmp_path / "part.zip", files=("QResGUI.exe", "VERSION")), tmp_path / "out3", "9.9.9")
    (tmp_path / "junk.zip").write_bytes(b"not a zip")
    with pytest.raises(updates.UpdateError, match="unpack"):
        updates.unpack(tmp_path / "junk.zip", tmp_path / "out4", "9.9.9")


def run_install_script(tmp_path, install_body: str) -> dict:
    source = tmp_path / "it's here" / "QResGUI-9.9.9-win64"        # an apostrophe, to test the quoting
    source.mkdir(parents=True)
    (source / "install.ps1").write_text(install_body, encoding="utf-8")
    ended = subprocess.Popen([sys.executable, "-c", "pass"])
    ended.wait()                                                   # QRes GUI has already closed
    script = tmp_path / "install-update.ps1"
    script.write_text(updates.install_script(source, "9.9.9", ended.pid), encoding="utf-8-sig")
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                   capture_output=True, timeout=120, check=False)
    return updates.take_result()


def test_install_script_records_success(tmp_path):
    result = run_install_script(tmp_path, "Write-Host 'Installed QRes GUI 9.9.9'\nexit 0\n")
    assert result == {"version": "9.9.9", "ok": True, "error": ""}
    assert "Installed QRes GUI 9.9.9" in updates.log_path().read_text(encoding="utf-8-sig")
    assert updates.take_result() is None                           # reported once


def test_install_script_records_why_it_failed(tmp_path):
    result = run_install_script(tmp_path, '$ErrorActionPreference = "Stop"\n'
                                          'throw "QRes GUI, or a game started through it, is running."\n')
    assert result == {"version": "9.9.9", "ok": False,
                      "error": "QRes GUI, or a game started through it, is running."}


def test_take_result_tidies_the_download(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))
    (updates.work_root() / "9.9.9").mkdir(parents=True)
    updates.result_path().parent.mkdir(parents=True, exist_ok=True)
    updates.result_path().write_text('{"version": "9.9.9", "ok": true}', encoding="utf-8-sig")
    assert updates.take_result() == {"version": "9.9.9", "ok": True, "error": ""}
    assert not updates.work_root().exists()
