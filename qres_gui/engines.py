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
    ),
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
        # Unity ships UnityPlayer.dll beside the exe (Unity 2017.2 on) and keeps
        # its data in "<Game>_Data".
        if (root / "UnityPlayer.dll").is_file() or any(
                p.is_dir() and (p / "globalgamemanagers").exists() for p in root.glob("*_Data")):
            return UNITY
        # A packaged Unreal game has an Engine folder next to its project folder,
        # whose Binaries\Win64 holds "<Project>-Win64-Shipping.exe".
        if (root / "Engine" / "Binaries").is_dir() or any(root.glob("*/Binaries/Win64/*-Win64-Shipping.exe")):
            return UNREAL
    except OSError:
        return None
    return None


def monitor_choices(count: int) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    return tuple((str(n), f"Monitor {n}", ("-monitor", str(n))) for n in range(1, max(count, 1) + 1))


def flags(choices: dict | None) -> list[str]:
    """The flags a profile's "engine_args" stands for; unknown engines, keys and values add nothing."""
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
        for choice_value, _label, choice_flags in option.choices:
            if choice_value == value:
                out += list(choice_flags)
    return out


def command_line(choices: dict | None) -> str:
    """`flags` as command-line text, ready to go in front of the user's own extra arguments."""
    return subprocess.list2cmdline(flags(choices))
