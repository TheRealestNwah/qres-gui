"""Checking GitHub for a newer QRes GUI release.

Only GitHub's public release list for this project is requested; nothing about
the PC or its games is sent. QRes GUI checks at most once a day (Settings can
turn it off), and never downloads or installs anything itself.
"""

from __future__ import annotations

import json
import re
import urllib.request

from . import __version__

REPO = "TheRealestNwah/qres-gui"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
CHECK_INTERVAL = 24 * 3600  # seconds between automatic checks


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(text).strip())
    return tuple(int(part) for part in match.groups()) if match else None


def is_newer(version: str, than: str) -> bool:
    new, old = parse_version(version), parse_version(than)
    return bool(new and old and new > old)


def newest(releases: list[dict], current: str) -> dict | None:
    """The highest published release above `current`: {"version", "url", "name"}, or None.

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
    return {"version": ".".join(map(str, best_version)), "url": best.get("html_url") or RELEASES_PAGE,
            "name": best.get("name") or ""}


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
