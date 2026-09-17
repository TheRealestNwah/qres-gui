"""Checking GitHub for a newer QRes GUI release, and installing it when asked.

Only GitHub's public release list for this project is requested; nothing about
the PC or its games is sent. QRes GUI checks at most once a day (Settings can
turn it off).

Nothing is downloaded until someone clicks Install update, and only the
installed copy offers it. The release zip then comes from this project's own
GitHub releases, must match the SHA-256 digest GitHub publishes for it, and
must hold the version it claims. A small PowerShell script waits for QRes GUI
to close, runs the zip's install.ps1 - exactly what installing by hand does -
writes how that went for the next start to report, and opens QRes GUI again.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from . import __version__, paths

REPO = "TheRealestNwah/qres-gui"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"
CHECK_INTERVAL = 24 * 3600  # seconds between automatic checks
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


class UpdateError(Exception):
    """Downloading or unpacking an update failed; the message says why, for people."""


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(text).strip())
    return tuple(int(part) for part in match.groups()) if match else None


def is_newer(version: str, than: str) -> bool:
    new, old = parse_version(version), parse_version(than)
    return bool(new and old and new > old)


def newest(releases: list[dict], current: str) -> dict | None:
    """The highest published release above `current`, or None.

    Returns {"version", "url", "name", "download"}; "download" is the zip to
    install from (see _download), or None when there isn't one to trust.

    Before 1.0 every release is a GitHub pre-release, so all count. From 1.0 on,
    pre-releases are left out: someone on a finished version is only offered
    finished versions.
    """
    best, best_version = None, parse_version(current) or (0, 0, 0)
    stable_only = best_version >= (1, 0, 0)
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        if stable_only and release.get("prerelease"):
            continue
        version = parse_version(release.get("tag_name", ""))
        if version and version > best_version:
            best, best_version = release, version
    if best is None:
        return None
    version = ".".join(map(str, best_version))
    return {"version": version, "url": best.get("html_url") or RELEASES_PAGE,
            "name": best.get("name") or "", "download": _download(best, version)}


def asset_name(version: str) -> str:
    return f"QResGUI-{version}-win64.zip"


def _download(release: dict, version: str) -> dict | None:
    """The release zip: {"url", "size", "sha256"}, or None if it can't be checked.

    Only this project's own release download, and only with the digest GitHub
    computed for it - without one there's nothing to check the file against.
    """
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict) or asset.get("name") != asset_name(version):
            continue
        url, digest = str(asset.get("browser_download_url") or ""), str(asset.get("digest") or "")
        if url.startswith(DOWNLOADS) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            return {"url": url, "size": int(asset.get("size") or 0), "sha256": digest[7:]}
    return None


def fetch_releases(timeout: float = 10) -> list[dict]:
    request = urllib.request.Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"QResGUI/{__version__}",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    return data if isinstance(data, list) else []


def check(current: str = __version__) -> dict | None:
    """Newest release above `current`, or None. Raises OSError / ValueError if GitHub can't be reached."""
    return newest(fetch_releases(), current)


# --- installing ---------------------------------------------------------------

def work_root() -> Path:
    return Path(os.environ.get("TEMP") or paths.app_dir()) / "QResGUI-update"


def result_path() -> Path:
    return paths.app_dir() / "update-result.json"


def log_path() -> Path:
    return paths.app_dir() / "update.log"


def fetch(download: dict, dest: Path, progress=None, timeout: float = 30) -> Path:
    """Download the release zip to `dest` and check it against its digest.

    `progress(done, total)` is called as it goes; returning False cancels.
    """
    url = str(download.get("url") or "")
    if not url.startswith(DOWNLOADS):
        raise UpdateError(f"Not downloading from {url or 'an unknown address'}: it isn't a QRes GUI release.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    total, done, digest = int(download.get("size") or 0), 0, hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": f"QResGUI/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, open(dest, "wb") as out:
            while chunk := response.read(256 * 1024):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress and progress(done, total) is False:
                    raise UpdateError("The download was cancelled.")
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise UpdateError(f"Couldn't download the update: {getattr(exc, 'reason', None) or exc}") from exc
    except UpdateError:
        dest.unlink(missing_ok=True)
        raise
    if digest.hexdigest() != str(download.get("sha256") or "").lower():
        dest.unlink(missing_ok=True)
        raise UpdateError("The download doesn't match the checksum GitHub lists for it, so it wasn't "
                          "installed. Try again later, or install it by hand from the releases page.")
    return dest


REQUIRED = ("install.ps1", "QResGUI.exe", "QResLauncher.exe", "VERSION")


def unpack(zip_path: Path, folder: Path, version: str) -> Path:
    """Extract the release zip into `folder`; returns the folder holding install.ps1."""
    shutil.rmtree(folder, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(folder)   # extractall drops absolute paths and ".." parts
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"Couldn't unpack the update: {exc}") from exc
    # Release zips hold one QResGUI-<version>-win64 folder; allow the files at the top too.
    for root in (folder, *sorted(p for p in folder.iterdir() if p.is_dir())):
        if all((root / name).is_file() for name in REQUIRED):
            found = (root / "VERSION").read_text(encoding="utf-8-sig", errors="replace").strip()
            if found != version:
                raise UpdateError(f"The download holds version {found or 'unknown'}, not {version}.")
            return root
    raise UpdateError("The download isn't a QRes GUI release: install.ps1 is missing.")


def _ps(text: str | Path) -> str:
    """A PowerShell single-quoted string."""
    return "'" + str(text).replace("'", "''") + "'"


def install_script(source: Path, version: str, gui_pid: int) -> str:
    """PowerShell that installs from `source` once process `gui_pid` has exited, then reopens QRes GUI."""
    lines = [
        "$ErrorActionPreference = 'Continue'",
        f"# Written by QRes GUI to install {version}; safe to delete.",
        "$dest = Join-Path $env:LOCALAPPDATA 'Programs\\QResGUI'",
        f"$log = {_ps(log_path())}",
        f"try {{ Wait-Process -Id {int(gui_pid)} -Timeout 60 -ErrorAction SilentlyContinue }} catch {{ }}",
        "$ok = $false",
        "$message = ''",
        "try {",
        f"    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File {_ps(source / 'install.ps1')} *>&1 |",
        "        Out-File -FilePath $log -Encoding utf8",
        "    if ($LASTEXITCODE -eq 0) { $ok = $true }",
        "    else {",
        # The error's own line, without PowerShell's "powershell.exe : " prefix and position lines.
        "        $message = Get-Content $log -ErrorAction SilentlyContinue |",
        r"            Where-Object { $_.Trim() -and $_ -notmatch '^\s*(\+|At |~)' } | Select-Object -First 1",
        r"""        $message = "$message" -replace '^(powershell\.exe|.*?\.ps1) : ', ''""",
        "        if (-not $message) { $message = \"install.ps1 exited with code $LASTEXITCODE\" }",
        "    }",
        "} catch { $message = $_.Exception.Message }",
        f"[ordered]@{{ version = {_ps(version)}; ok = $ok; error = $message }} | ConvertTo-Json |",
        f"    Set-Content -Path {_ps(result_path())} -Encoding UTF8",
        # Reopen whichever QRes GUI is there now: the new one, or the old one if installing failed.
        f"if (-not (Get-Process -Id {int(gui_pid)} -ErrorAction SilentlyContinue)) {{",
        "    Start-Process -FilePath (Join-Path $dest 'QResGUI.exe') -WorkingDirectory $dest",
        "}",
    ]
    return "\r\n".join(lines) + "\r\n"


def start_install(source: Path, version: str, gui_pid: int | None = None) -> None:
    """Start the install script, which waits for QRes GUI to exit; raises UpdateError."""
    script = source.parent / "install-update.ps1"
    try:
        script.write_text(install_script(source, version, gui_pid or os.getpid()), encoding="utf-8-sig")
    except OSError as exc:
        raise UpdateError(f"Couldn't write the installer script: {exc}") from exc
    result_path().unlink(missing_ok=True)
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
               "-File", str(script)]
    error = None
    # Out of any job QRes GUI is in where allowed, so closing QRes GUI can't end it.
    for flags in (CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB,
                  CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP):
        try:
            subprocess.Popen(command, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError as exc:
            error = exc
    raise UpdateError(f"Couldn't start the installer: {error}")


def take_result() -> dict | None:
    """How the last in-app update went, once: {"version", "ok", "error"}. Also clears its download."""
    path = result_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    path.unlink(missing_ok=True)
    shutil.rmtree(work_root(), ignore_errors=True)
    if not isinstance(data, dict):
        return None
    return {"version": str(data.get("version") or ""), "ok": bool(data.get("ok")),
            "error": str(data.get("error") or "")}
