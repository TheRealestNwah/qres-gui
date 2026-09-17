"""Launch arguments a game's engine documents, offered as choices instead of free text (#14).

Everything here comes from the engines' own documentation and nothing is looked
up online: the engine is told from files in the install folder, and each option
maps to flags the engine's manual lists. Sources:

- Unity: "Windows standalone player command-line arguments",
  https://docs.unity3d.com/Manual/PlayerCommandLineArguments.html
- Unreal Engine: "Unreal Engine Command-Line Arguments Reference",
  https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-command-line-arguments-reference

A game is free to ignore these - Unreal games in particular can be built to -
so the GUI presents them as "documented by the engine", never as a promise.

Pure Python with no Qt, so the launcher can turn a profile's choices into flags.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

UNITY = "unity"
UNREAL = "unreal"
NAMES = {UNITY: "Unity", UNREAL: "Unreal Engine"}


@dataclass(frozen=True)
class Option:
    key: str                                   # stored in the profile's "engine_args"
    label: str
    choices: tuple[tuple[str, str, tuple[str, ...]], ...]   # (value, label, flags)
    per_display: bool = False                  # choices are made from the connected displays
    per_profile: bool = False                  # the one choice takes its values from the game's profile


# The single choice of a per_profile option: the game's own resolution, whatever
# the profile says it is at launch, so changing the profile needs nothing else.
PROFILE_RESOLUTION = "profile"


OPTIONS: dict[str, tuple[Option, ...]] = {
    UNITY: (
        Option("window", "Window mode", (
            ("borderless", "Borderless fullscreen", ("-screen-fullscreen", "1", "-window-mode", "borderless")),
            ("exclusive", "Exclusive fullscreen", ("-screen-fullscreen", "1", "-window-mode", "exclusive")),
            ("windowed", "Windowed", ("-screen-fullscreen", "0")),
        )),
        Option("api", "Graphics API", (
            ("d3d11", "Direct3D 11", ("-force-d3d11",)),
            ("d3d12", "Direct3D 12", ("-force-d3d12",)),
            ("vulkan", "Vulkan", ("-force-vulkan",)),
        )),
        # Unity numbers monitors itself (1-based); values are filled in from the
        # displays connected, see monitor_choices().
        Option("monitor", "Monitor", (), per_display=True),
        # Tells the game the size to render at, so a borderless game fills the
        # switched desktop instead of remembering an older size.
        Option("resolution", "Resolution", (), per_profile=True),
    ),
    UNREAL: (
        Option("window", "Window mode", (
            ("fullscreen", "Fullscreen", ("-fullscreen",)),
            ("windowed", "Windowed", ("-windowed",)),
        )),
        Option("api", "Graphics API", (
            ("d3d11", "Direct3D 11", ("-dx11",)),
            ("d3d12", "Direct3D 12", ("-dx12",)),
            ("vulkan", "Vulkan", ("-vulkan",)),
        )),
        Option("resolution", "Resolution", (), per_profile=True),
    ),
}

# How each engine spells "render at this size".
_RESOLUTION_FLAGS = {
    UNITY: lambda w, h: ["-screen-width", str(w), "-screen-height", str(h)],
    UNREAL: lambda w, h: [f"-ResX={w}", f"-ResY={h}"],
}


@lru_cache(maxsize=512)
def detect(install_dir: str) -> str | None:
    """The engine a game's install folder shows, or None if it's neither Unity nor Unreal.

    Only looks at the folder and one level below it, so it's cheap enough to run
    whenever a game is shown. Cached per folder for the life of the process.
    """
    if not install_dir:
        return None
    root = Path(install_dir)
    try:
        if not root.is_dir():
            return None
        if _is_unity(root):
            return UNITY
        # A packaged Unreal game has an Engine folder next to its project folder,
        # whose Binaries\Win64 holds "<Project>-Win64-Shipping.exe".
        if (root / "Engine" / "Binaries").is_dir() or any(root.glob("*/Binaries/Win64/*-Win64-Shipping.exe")):
            return UNREAL
    except OSError:
        return None
    return None


# Executables a Unity game ships beside its own that aren't the game.
_UNITY_HELPERS = {"unitycrashhandler32.exe", "unitycrashhandler64.exe"}
# What a Unity player's "<Game>_Data" folder holds: globalgamemanagers from
# Unity 5 on, mainData or data.unity3d before that.
_UNITY_DATA = ("globalgamemanagers", "mainData", "data.unity3d")


def _is_unity(root: Path) -> bool:
    """Whether the game in `root` is a Unity player, not just something beside it.

    A Unity player "<Game>.exe" keeps its data in "<Game>_Data". Every exe in
    the folder has to be one, or Unity's crash handler: a game on its own engine
    can ship a Unity-made launcher alongside - the METAL GEAR SOLID Master
    Collection has launcher.exe and launcher_Data beside METAL GEAR SOLID2.exe -
    and Unity's flags mean nothing to the game itself.
    """
    exes = [p for p in root.glob("*.exe") if p.is_file() and p.name.casefold() not in _UNITY_HELPERS]
    if not exes:
        return False
    for exe in exes:
        data = root / f"{exe.stem}_Data"
        if not any((data / name).exists() for name in _UNITY_DATA):
            return False
    return True


def monitor_choices(count: int) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    return tuple((str(n), f"Monitor {n}", ("-monitor", str(n))) for n in range(1, max(count, 1) + 1))


def profile_size(entry: dict | None) -> tuple[int, int] | None:
    """The width and height a game's profile switches to, if it names them."""
    try:
        width, height = int((entry or {}).get("width") or 0), int((entry or {}).get("height") or 0)
    except (TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def flags(choices: dict | None, entry: dict | None = None) -> list[str]:
    """The flags a profile's "engine_args" stands for; unknown engines, keys and values add nothing.

    `entry` is the game's profile, which "start at this game's resolution" reads its size from.
    """
    if not isinstance(choices, dict):
        return []
    engine = choices.get("engine")
    out: list[str] = []
    for option in OPTIONS.get(engine, ()):
        value = choices.get(option.key)
        if not value or not isinstance(value, str):
            continue
        if option.per_display:
            if value.isdigit() and int(value) >= 1:
                out += ["-monitor", value]
            continue
        if option.per_profile:
            size = profile_size(entry)
            if value == PROFILE_RESOLUTION and size:
                out += _RESOLUTION_FLAGS[engine](*size)
            continue
        for choice_value, _label, choice_flags in option.choices:
            if choice_value == value:
                out += list(choice_flags)
    return out


def command_line(choices: dict | None, entry: dict | None = None) -> str:
    """`flags` as command-line text, ready to go in front of the user's own extra arguments."""
    return subprocess.list2cmdline(flags(choices, entry))
