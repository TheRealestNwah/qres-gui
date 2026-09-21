"""Taking profiles to another PC, or getting them back after a reinstall.

The config is not portable as it stands. Most of it describes *this* machine:
where QRes.exe lives, what the desktop resolution is, when updates were last
checked - and, per game, the `launch` block the stores report and an
`install_dir`, both of which `MainWindow.rescan` rewrites from the store on
every scan. Copying those to another PC would at best be pointless and at worst
point a profile at a path that isn't there.

So an export carries only what means the same thing anywhere: which games
switch, to what resolution and refresh rate, whether they touch HDR, the extra
arguments, the presets and the handful of settings that aren't about this PC.

Displays are the awkward one. `\\\\.\\DISPLAY2` is a different monitor on a
different machine, and silently switching the wrong screen is the failure this
whole app is careful about. So the export records the monitor's *name* beside
its number, and an import restores the choice only when a display of that name
and number is actually present. Anything else falls back to the primary display
and is counted in the summary, so nothing is aimed at a screen by guesswork.

The file is JSON and comes from outside, so everything here validates rather
than trusts: a truncated, hand-edited or unrelated file raises `TransferError`
with something a person can act on, and never half-applies.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, display

FORMAT = 1
KIND = "qres-gui-profiles"

# Settings that mean the same thing on any PC. Everything else in config.DEFAULTS
# is about this machine (qres_path, desktop_mode) or is local state (the update
# check, first_run_done), and is deliberately left out.
PORTABLE_SETTINGS = (
    "temporary", "switch_delay", "restore_delay", "default_target",
    "check_updates", "tray_icon", "background", "restore_hotkey",
    "hidden_games",   # store ids, so they mean the same games on any PC
    "commands",       # listed verbatim in the import preview; see Summary.commands
)

# A game profile's portable half. "launch" rides along for manual games only,
# which own it - a store game's copy is rewritten by the next rescan.
PORTABLE_GAME = ("name", "store", "enabled", "width", "height", "refresh", "hdr", "scaling", "audio_device",
                 "watch", "extra_args", "quick_restore", "engine_args", "commands")
PORTABLE_PRESET = ("name", "width", "height", "refresh", "hotkey")

# The fields the first exports carried, before they said which ones they carry.
# A restore only clears a field the file could have held: an older backup that
# says nothing about a newer setting isn't saying "turn it off".
_FIRST_GAME_FIELDS = ("name", "store", "enabled", "width", "height", "refresh", "hdr",
                      "watch", "extra_args")


class TransferError(RuntimeError):
    """A file that can't be read as an export, with a reason worth showing."""


@dataclass
class Summary:
    """What an import did, or would do."""
    games_added: int = 0
    games_updated: int = 0
    presets_added: int = 0
    presets_updated: int = 0
    settings_applied: int = 0
    displays_kept: int = 0
    displays_dropped: list[str] = field(default_factory=list)   # profile names
    manual_games: list[str] = field(default_factory=list)       # names whose paths need checking
    hotkeys_dropped: list[str] = field(default_factory=list)    # presets whose shortcut was taken
    # Commands the file would add or change, as "Game (before): command". A
    # profile file can come from anyone, and these run on this PC when a game
    # switches, so the preview shows every one of them, word for word.
    commands: list[str] = field(default_factory=list)
    # Only a restore removes anything.
    games_removed: list[str] = field(default_factory=list)      # profiles set up since the backup
    manual_removed: list[str] = field(default_factory=list)     # hand-added games since the backup
    presets_removed: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.games_added or self.games_updated or self.presets_added
                    or self.presets_updated or self.settings_applied or self.games_removed
                    or self.manual_removed or self.presets_removed)

    @property
    def games_listed_changed(self) -> bool:
        """Whether hand-added games came or went, which only a rescan shows."""
        return bool(self.manual_games or self.manual_removed)

    def lines(self) -> list[str]:
        """Plain sentences for a dialog, in the order that matters."""
        if not self.changed:
            # The notes below only mean something beside an actual change: a
            # re-import resolves displays again without altering a thing, and
            # leading with that would read as work to approve.
            return ["Nothing to change — this file matches what's already here."]
        out = []
        if self.commands:
            out.append(f"This file sets {len(self.commands)} command(s) that will run on this PC when games "
                       "switch. Only apply it if you trust where it came from:\n    "
                       + "\n    ".join(self.commands))
        if self.games_added or self.games_updated:
            out.append(f"{self.games_added} game profile(s) added, {self.games_updated} updated.")
        if self.games_removed:
            out.append(f"{len(self.games_removed)} game profile(s) set up since this backup removed, so "
                       f"those games go back to not switching: {', '.join(sorted(self.games_removed))}.")
        if self.manual_removed:
            out.append(f"{len(self.manual_removed)} game(s) added by hand since this backup taken off the "
                       f"list (shortcuts made for them will stop working): "
                       f"{', '.join(sorted(self.manual_removed))}.")
        if self.presets_added or self.presets_updated:
            out.append(f"{self.presets_added} preset(s) added, {self.presets_updated} updated.")
        if self.presets_removed:
            out.append(f"{len(self.presets_removed)} preset(s) removed: "
                       f"{', '.join(sorted(self.presets_removed))}.")
        if self.settings_applied:
            out.append(f"{self.settings_applied} setting(s) applied.")
        if self.displays_kept:
            out.append(f"{self.displays_kept} display choice(s) matched a monitor here and were kept.")
        if self.displays_dropped:
            out.append(f"{len(self.displays_dropped)} profile(s) named a display this PC doesn't have, "
                       f"so they use the primary one: {', '.join(sorted(self.displays_dropped))}.")
        if self.hotkeys_dropped:
            out.append(f"{len(self.hotkeys_dropped)} imported preset(s) wanted a shortcut already in use "
                       f"here, so they came in without one: {', '.join(sorted(self.hotkeys_dropped))}.")
        if self.manual_games:
            out.append(f"{len(self.manual_games)} added game(s) carry a path from the other PC — "
                       f"check them if they don't start: {', '.join(sorted(self.manual_games))}.")
        return out


# --- displays, the part that must never guess --------------------------------

def _describe_display(device: str | None) -> dict | None:
    """A display choice as something another PC can be asked about."""
    if not device:
        return None
    try:
        found = display.find_display(device)
    except Exception:                                   # noqa: BLE001 - never block an export
        found = None
    return {"device": device, "name": found.name if found else "", "number": display.device_number(device)}


def _resolve_display(described, summary: Summary, label: str) -> str:
    """The local device matching `described`, or "" (the primary) if none does.

    Matched on the monitor's name *and* number: the name alone repeats across
    identical monitors, and the number alone means nothing on another PC.
    """
    if not isinstance(described, dict):
        return ""
    name, number = described.get("name") or "", str(described.get("number") or "")
    if not name:
        summary.displays_dropped.append(label)
        return ""
    try:
        screens = display.list_displays()
    except Exception:                                   # noqa: BLE001 - primary is the safe answer
        screens = []
    for screen in screens:
        if screen.name == name and screen.number == number:
            summary.displays_kept += 1
            return screen.device
    summary.displays_dropped.append(label)
    return ""


# --- export ------------------------------------------------------------------

def export_data(cfg: dict) -> dict:
    """The portable half of `cfg`, ready to be written out."""
    games = {}
    for game_id, entry in (cfg.get("games") or {}).items():
        if not isinstance(entry, dict):
            continue
        saved = {key: entry[key] for key in PORTABLE_GAME if key in entry}
        saved["display"] = _describe_display(entry.get("display"))
        if entry.get("store") == "manual" and entry.get("launch"):
            # A manual game is rebuilt from its launch block, so it doesn't
            # survive without one - even though the path is this PC's.
            saved["launch"] = entry["launch"]
        games[game_id] = saved

    presets = []
    for preset in (cfg.get("presets") or []):
        if not isinstance(preset, dict):
            continue
        saved = {key: preset[key] for key in PORTABLE_PRESET if key in preset}
        saved["display"] = _describe_display(preset.get("display"))
        presets.append(saved)

    return {
        "kind": KIND,
        "format": FORMAT,
        "app_version": __version__,
        "exported": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # Which profile fields this file speaks for, so a restore from it
        # clears only those (see _FIRST_GAME_FIELDS).
        "game_fields": list(PORTABLE_GAME),
        "settings": {key: cfg[key] for key in PORTABLE_SETTINGS if key in cfg},
        "games": games,
        "presets": presets,
    }


def write_export(cfg: dict, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(export_data(cfg), indent=2), encoding="utf-8")
    return path


# --- import ------------------------------------------------------------------

def read_export(path: str | Path) -> dict:
    """Load and check an export file. Raises `TransferError` with a readable reason."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise TransferError(f"Couldn't open that file: {exc.strerror or exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise TransferError("That file isn't valid JSON, so it isn't a QRes GUI export.") from exc
    if not isinstance(data, dict) or data.get("kind") != KIND:
        raise TransferError("That file isn't a QRes GUI profile export.")
    version = data.get("format")
    if not isinstance(version, int):
        raise TransferError("That export doesn't say which format it is.")
    if version > FORMAT:
        raise TransferError(f"That export was written by a newer QRes GUI (format {version}; "
                            f"this one reads {FORMAT}). Update QRes GUI and try again.")
    for key, kind in (("games", dict), ("presets", list), ("settings", dict)):
        if key in data and not isinstance(data[key], kind):
            raise TransferError(f"That export's \"{key}\" section is damaged.")
    return data


def _clean_game(saved: dict) -> dict | None:
    """A profile's fields, keeping only what's the right shape."""
    if not isinstance(saved, dict):
        return None
    entry = {key: saved[key] for key in PORTABLE_GAME if key in saved}
    if not isinstance(entry.get("watch", []), list):
        entry.pop("watch")
    if not isinstance(entry.get("engine_args", {}), dict):
        entry.pop("engine_args")
    commands = entry.get("commands", {})
    if not isinstance(commands, dict) or not all(isinstance(v, str) for v in commands.values()):
        entry.pop("commands")
    if saved.get("store") == "manual" and isinstance(saved.get("launch"), dict):
        entry["launch"] = saved["launch"]
    return entry


def merge(cfg: dict, data: dict, *, games: bool = True, presets: bool = True,
          settings: bool = True) -> Summary:
    """Apply `data` to `cfg` in place, and say what happened.

    Games are matched by their store-qualified id, which means the same game on
    any PC, so importing updates the profiles a file mentions and leaves every
    other game alone. A store game's `launch` block is never overwritten: it
    belongs to this machine and the next rescan rewrites it anyway.
    """
    summary = Summary()

    if settings:
        _apply_settings(cfg, data, summary)

    if games:
        cfg.setdefault("games", {})
        for game_id, saved in (data.get("games") or {}).items():
            entry = _clean_game(saved)
            if entry is None:
                continue
            label = entry.get("name") or game_id
            entry["display"] = _resolve_display(saved.get("display"), summary, label)
            existing = cfg["games"].get(game_id)
            _note_commands(summary, label, (existing or {}).get("commands"), entry.get("commands"))
            if existing:
                keep = {key: existing[key] for key in ("launch", "install_dir") if key in existing}
                if existing.get("store") == "manual" and "launch" in entry:
                    keep.pop("launch", None)   # a manual game's own launch may be updated
                before = dict(existing)
                existing.update(entry)
                existing.update(keep)
                # Only count a profile that actually moved: re-importing the same
                # file must preview as "nothing to change", not as work to approve.
                if not _same_profile(existing, before):
                    summary.games_updated += 1
            else:
                cfg["games"][game_id] = entry
                if entry.get("store") == "manual":
                    summary.manual_games.append(label)
                summary.games_added += 1

    if presets:
        cfg.setdefault("presets", [])
        have = {(p.get("name"), p.get("width"), p.get("height"), p.get("refresh"))
                for p in cfg["presets"] if isinstance(p, dict)}
        # Two presets on one shortcut means one of them silently never fires, so
        # an imported hotkey gives way to a binding this PC already has.
        taken = {p.get("hotkey") for p in cfg["presets"] if isinstance(p, dict) and p.get("hotkey")}
        taken.add(cfg.get("restore_hotkey") or None)
        for saved in (data.get("presets") or []):
            if not isinstance(saved, dict):
                continue
            preset = {key: saved[key] for key in PORTABLE_PRESET if key in saved}
            if (preset.get("name"), preset.get("width"), preset.get("height"),
                    preset.get("refresh")) in have:
                continue    # same preset already here; don't make a second one
            if preset.get("hotkey") and preset["hotkey"] in taken:
                summary.hotkeys_dropped.append(preset.get("name") or "a preset")
                preset["hotkey"] = ""
            elif preset.get("hotkey"):
                taken.add(preset["hotkey"])
            preset["display"] = _resolve_display(saved.get("display"), summary,
                                                 preset.get("name") or "a preset")
            cfg["presets"].append(preset)
            summary.presets_added += 1

    return summary


def restore(cfg: dict, data: dict, *, games: bool = True, presets: bool = True,
            settings: bool = True) -> Summary:
    """Make `cfg` match `data` again, and say what that changed.

    What a backup is for: undoing what's happened since. Unlike `merge`, a
    profile set up after the backup is removed - the game goes back to never
    having been set up - and so is a setting within a profile the backup
    didn't have, such as an HDR choice made since. Presets are replaced
    outright. As in `merge`, a store game keeps this machine's `launch` and
    `install_dir`: the backup never had them.
    """
    summary = Summary()

    if settings:
        _apply_settings(cfg, data, summary)

    # A file without a section doesn't speak for it; restoring "nothing" over
    # every profile would be a strange reading of a hand-trimmed file.
    if games and "games" in data:
        _restore_games(cfg, data, summary)

    if presets and "presets" in data:
        _restore_presets(cfg, data, summary)

    return summary


# What a profile means when it doesn't mention these: an older profile has no
# key where a restored one has the empty value, and that's the same choice.
_PROFILE_DEFAULTS = {"display": "", "hdr": None, "scaling": None, "audio_device": None, "extra_args": "", "quick_restore": False, "watch": [],
                     "engine_args": {}, "commands": {}}


def _same_profile(a: dict, b: dict) -> bool:
    return {**_PROFILE_DEFAULTS, **a} == {**_PROFILE_DEFAULTS, **b}


def _note_commands(summary: Summary, label: str, old, new) -> None:
    """Add any command `new` sets that `old` didn't have, word for word, to the preview."""
    old = old if isinstance(old, dict) else {}
    new = new if isinstance(new, dict) else {}
    for when in ("before", "after"):
        command = new.get(when)
        command = command.strip() if isinstance(command, str) else ""
        if command and command != (old.get(when) or "").strip():
            summary.commands.append(f"{label} ({when}): {command}")


def _apply_settings(cfg: dict, data: dict, summary: Summary) -> None:
    for key, value in (data.get("settings") or {}).items():
        if key == "commands" and not (isinstance(value, dict)
                                      and all(isinstance(v, str) for v in value.values())):
            continue
        if key == "commands":
            _note_commands(summary, "Every game", cfg.get(key), value)
        if key in PORTABLE_SETTINGS and cfg.get(key) != value:
            cfg[key] = value
            summary.settings_applied += 1


def _game_fields(data: dict) -> set[str]:
    """The profile fields a file speaks for; older files didn't say."""
    declared = data.get("game_fields")
    if not isinstance(declared, list) or not all(isinstance(f, str) for f in declared):
        declared = _FIRST_GAME_FIELDS
    return set(declared) & set(PORTABLE_GAME)


def _restore_games(cfg: dict, data: dict, summary: Summary) -> None:
    games = cfg.setdefault("games", {})
    wanted = {gid: entry for gid, saved in (data.get("games") or {}).items()
              if (entry := _clean_game(saved)) is not None}
    # Clearable: what the file speaks for, less what names the game.
    clearable = _game_fields(data) - {"name", "store"}

    for game_id in [gid for gid in games if gid not in wanted]:
        entry = games.pop(game_id)
        name = (entry.get("name") if isinstance(entry, dict) else None) or game_id
        manual = isinstance(entry, dict) and entry.get("store") == "manual"
        (summary.manual_removed if manual else summary.games_removed).append(name)

    for game_id, entry in wanted.items():
        label = entry.get("name") or game_id
        entry["display"] = _resolve_display((data["games"][game_id] or {}).get("display"), summary, label)
        existing = games.get(game_id)
        _note_commands(summary, label, existing.get("commands") if isinstance(existing, dict) else None,
                       entry.get("commands"))
        if not isinstance(existing, dict):
            games[game_id] = entry
            if entry.get("store") == "manual":
                summary.manual_games.append(label)
            summary.games_added += 1
            continue
        before = dict(existing)
        for key in clearable:
            if key not in entry:
                existing.pop(key, None)
        existing.update(entry)
        if not _same_profile(existing, before):
            summary.games_updated += 1


def _restore_presets(cfg: dict, data: dict, summary: Summary) -> None:
    # The presets being replaced don't hold their shortcuts any more, so only
    # the restore hotkey (as it stands after the settings) and presets taken
    # from the file already can be in the way.
    taken = {cfg.get("restore_hotkey") or None}
    restored = []
    for saved in (data.get("presets") or []):
        if not isinstance(saved, dict):
            continue
        preset = {key: saved[key] for key in PORTABLE_PRESET if key in saved}
        if preset.get("hotkey") and preset["hotkey"] in taken:
            summary.hotkeys_dropped.append(preset.get("name") or "a preset")
            preset["hotkey"] = ""
        elif preset.get("hotkey"):
            taken.add(preset["hotkey"])
        preset["display"] = _resolve_display(saved.get("display"), summary, preset.get("name") or "a preset")
        restored.append(preset)

    current = [p for p in (cfg.get("presets") or []) if isinstance(p, dict)]
    by_name = {p.get("name"): p for p in current}
    restored_names = {p.get("name") for p in restored}
    for preset in restored:
        old = by_name.get(preset.get("name"))
        if old is None:
            summary.presets_added += 1
        elif {"display": "", "hotkey": "", **old} != {"hotkey": "", **preset}:
            summary.presets_updated += 1
    summary.presets_removed.extend(p.get("name") or "a preset" for p in current
                                   if p.get("name") not in restored_names)
    cfg["presets"] = restored
