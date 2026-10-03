# QRes GUI

A Windows desktop app (Python 3.13, PySide6) that switches display resolution, refresh rate, HDR, scaling and audio per game, and restores them when the game exits. The GitHub repo is `qres-gui`. The version lives in `qres_gui/__init__.py` (mirrored in `pyproject.toml`).

## Build, test, lint

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\pythonw QResGUI.pyw     # run from source
.venv\Scripts\python -m pytest -q     # tests (what CI runs)
.\build.ps1                           # -> dist\QResGUI\
.\package.ps1 -Installer              # -> release\ zip and Inno Setup installer
.\install.ps1                         # build and install for the current user
```

CI (`windows-latest`, job `test-and-build`) runs pytest, builds the zip and installer, installs it silently and checks the Settings > Apps entry, launches the installed app, then reinstalls over it. A `v<version>` tag push or the manual workflow dispatch publishes the release. Steps are in `docs/RELEASING.md`; signing options in `docs/CODE_SIGNING.md`. There is no separate lint step.

## Layout

- `qres_gui/` — `display.py` (mode enumeration and switching), `launcher.py` (`run` / `restore` / `remove-hooks` / `guard`), `hooks.py` (Steam launch options and shortcuts), `playnite.py`, `notify.py`, `vdf.py` (round-trips Steam files byte for byte), `stores/` (per-store detection), `gui/` (PySide6 UI).
- `tests/` — pytest suite. `tools/` — icon, screenshot, release-notes and winget-manifest scripts. `winget/` — manifests. `installer/` — Inno Setup files.
- Logs: `%APPDATA%\QResGUI\launcher.log`.

## Gotchas

- Tests must not change the real display resolution; use the helpers in `tests/helpers.py` and `conftest.py`.
- Running from source writes Steam launch options that call `.venv\Scripts\pythonw.exe QResLauncher.pyw`; the built exe is the stable target.
- Update `THIRD_PARTY_NOTICES.md` and `licenses/` when dependencies change.
- Update `CHANGELOG.md` for user-visible changes, and bump the version in both places.
