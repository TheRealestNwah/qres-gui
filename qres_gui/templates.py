"""Profile templates: one game's display settings, kept under a name and put onto other games.

A template carries what a profile says about how a game is shown and heard -
the display, resolution, refresh rate, HDR, scaling, playback device, whether
to switch back the moment it closes, and its before/after commands - and
nothing that says which game it is or how it starts. So applying one leaves a
game's name, store, `launch` and `install_dir` alone, and its process names,
extra arguments and engine options too, which only ever fit the one game. It
doesn't write Steam launch options or make shortcuts either: a game's launch
hook stays whatever it was, and the list says if one still needs setting up.

Saved in the config as "templates": [{"name", "display", "width", "height",
"refresh", "hdr", "scaling", "audio_device", "quick_restore", "commands"}].
Every field is written out, "leave it alone" included, so a game a template
is applied to ends up matching it rather than keeping bits of what it had.
"""

from __future__ import annotations

from copy import deepcopy

from . import audio, display, scaling

FIELDS = ("display", "width", "height", "refresh", "hdr", "scaling", "audio_device", "quick_restore",
          "commands")

# What a profile without the field means; the same as what the game panel shows for it.
_UNSET = {"display": "", "refresh": 0, "hdr": None, "scaling": None, "audio_device": None,
          "quick_restore": False}
_WHEN = ("before", "after")


def _commands(value) -> dict:
    """A profile's commands as saved: only the ones that are set."""
    value = value if isinstance(value, dict) else {}
    return {when: value[when].strip() for when in _WHEN
            if isinstance(value.get(when), str) and value[when].strip()}


def settings_of(entry: dict) -> dict:
    """The template half of a game's profile."""
    settings = {key: deepcopy(entry.get(key, default)) for key, default in _UNSET.items()}
    settings["width"], settings["height"] = int(entry["width"]), int(entry["height"])
    settings["commands"] = _commands(entry.get("commands"))
    return {key: settings[key] for key in FIELDS}


def make(name: str, entry: dict) -> dict:
    return {"name": name.strip(), **settings_of(entry)}


def clean(saved) -> dict | None:
    """A template from the config, checked; None if it can't be used.

    The config is a file people can edit, so a template that has lost its name
    or size is dropped rather than applied half-way.
    """
    if not isinstance(saved, dict) or not isinstance(saved.get("name"), str) or not saved["name"].strip():
        return None
    try:
        width, height = int(saved["width"]), int(saved["height"])
        refresh = int(saved.get("refresh") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0 or refresh < 0:
        return None
    hdr = saved.get("hdr")
    return {
        "name": saved["name"].strip(),
        "display": saved["display"] if isinstance(saved.get("display"), str) else "",
        "width": width, "height": height, "refresh": refresh,
        "hdr": hdr if isinstance(hdr, bool) else None,
        "scaling": saved["scaling"] if saved.get("scaling") in scaling.CHOICES else None,
        "audio_device": saved["audio_device"] if isinstance(saved.get("audio_device"), str)
        and saved["audio_device"] else None,
        "quick_restore": bool(saved.get("quick_restore")),
        "commands": _commands(saved.get("commands")),
    }


def load(cfg: dict) -> list[dict]:
    return [t for t in map(clean, cfg.get("templates") or []) if t]


def find(templates: list[dict], name: str) -> int:
    """Where a template of that name is (names match whatever their case); -1 if none."""
    key = name.strip().casefold()
    return next((i for i, t in enumerate(templates) if t["name"].casefold() == key), -1)


def apply(entry: dict, template: dict) -> None:
    """Make a game's profile match the template, leaving what isn't in one alone."""
    for key in FIELDS:
        if key == "commands":
            if template.get("commands"):
                entry["commands"] = dict(template["commands"])
            else:
                entry.pop("commands", None)   # how the game panel saves "no commands"
        else:
            entry[key] = deepcopy(template.get(key, _UNSET.get(key)))


def summary(template: dict) -> list[str]:
    """What a template sets, one short line each, for the dialogs that apply one."""
    size = f"{template['width']} × {template['height']}"
    refresh = int(template.get("refresh") or 0)
    lines = [size + (f" @ {refresh} Hz" if refresh else ", same refresh rate as the desktop")]
    device = template.get("display") or ""
    lines.append(f"Display {display.device_number(device)}" if device else "Primary display")
    if template.get("hdr") is not None:
        lines.append("HDR " + ("on" if template["hdr"] else "off"))
    if template.get("scaling") in scaling.CHOICES:
        lines.append("Scaling: " + dict((key, label) for label, key in scaling.LABELS)[template["scaling"]])
    if template.get("audio_device"):
        lines.append(f"Playback device: {audio.name(template['audio_device'])}")
    if template.get("quick_restore"):
        lines.append("Switches back the moment the game closes")
    # Word for word: these run on this PC whenever any of the games switches.
    for when, label in (("before", "Before switching"), ("after", "After switching back")):
        command = (template.get("commands") or {}).get(when)
        if command:
            lines.append(f"{label}: {command}")
    return lines
