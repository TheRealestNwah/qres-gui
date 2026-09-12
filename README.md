# QRes GUI

Switch Windows to a different desktop resolution while a particular game runs,
and back again when it closes. Made for games that only render correctly when
the *desktop* is at, say, 2560 × 1440 on a 3440 × 1440 ultrawide, because they
don't let you pick an exact resolution themselves.

Resolution changes go through **QRes** (`QRes.exe` v1.1 by Anders Kjersem), a
small command-line tool that isn't included here. Get it separately and point
QRes GUI at it, or drop it into the install folder. Without it, QRes GUI uses
the Windows display API directly.

> **Status: early pre-release (0.3.0).** Versions go 0.1.0, 0.2.0, … and
> are marked as pre-releases on GitHub until the first stable release.
> Verified on real hardware:
> launching a Steam game through its launch options (MGS4, including its
> launcher handing off to the game), switching back when it closes, the Steam
> overlay, launch options surviving a Steam restart, and the installer. Not
> yet tested: Steam's *Stop* button, anti-cheat games, and Epic / Ubisoft /
> Heroic / Amazon detection. Expect rough edges, and please report what you find.
>
> Windows 10/11 only. The executables aren't code-signed, so SmartScreen may
> warn the first time you run them.

## How it works

`QResLauncher.exe` sits between the store and the game:

1. It switches to the game's resolution, keeping the desktop's refresh rate
   unless you pick another.
2. It starts the game and follows every process the game starts, including
   ones whose launcher has already exited.
3. When they've all closed, it switches back.

How the launcher gets in the loop depends on the store:

| Store | Hook | Detected from |
|---|---|---|
| Steam | Launch options become `"…\QResLauncher.exe" run steam:<appid> %command%` (your existing options are kept) | `libraryfolders.vdf`, `appmanifest_*.acf`, `localconfig.vdf` |
| GOG (Galaxy, Heroic, offline installers) | Desktop / Start menu shortcut that runs the game's exe through the launcher | `HKLM\SOFTWARE\WOW6432Node\GOG.com\Games` |
| Epic Games | Shortcut that opens the game through Epic's URL, then waits for the game's exe | Launcher manifests (`*.item`) |
| Ubisoft Connect | Shortcut that opens the game through `uplay://`, then waits for the game's exe (guessed; check it) | `HKLM\…\Ubisoft\Launcher\Installs` |
| Heroic (Epic, Amazon) | Shortcut that opens the game through `heroic://launch`, then waits for the game's exe | `%APPDATA%\heroic\legendaryConfig\…\installed.json`, `nile_config\…\installed.json` |
| Heroic (GOG) | Shortcut that runs the game's exe through the launcher (listed once if Windows also knows it as a GOG game) | `%APPDATA%\heroic\gog_store\installed.json` + `goggame-<id>.info` |
| Amazon Games app | Shortcut that opens the game through `amazon-games://`, then waits for the exe named in its `fuel.json` | `%LOCALAPPDATA%\Amazon Games\…\GameInstallInfo.sqlite` |
| Anything else | **Add game…** and point at the exe | — |

For non-Steam games, start the game from the `… (QRes)` shortcut (or **Play**),
not from the store's own button. The store can't be told to go through the launcher.

### Safety nets

- By default the switch is **temporary** (QRes `/D`). It's never written to
  the registry, so a reboot always comes back at your normal resolution.
- Before switching, the launcher records the desktop mode in
  `%APPDATA%\QResGUI\session.json` and starts a small detached guard process.
  If the launcher is killed (e.g. Steam's *Stop* button), the guard switches back.
- If both are killed anyway, the GUI notices on its next start and offers to
  restore. **Restore desktop resolution** in the top bar also works any time,
  as does `QResLauncher.exe restore`.

### Notifications

The launcher never stops to show a dialog. If it can't switch or switch back,
or the guard had to step in, you get a Windows notification. The game still
starts at your current resolution if switching failed. While a fullscreen
game has focus, Windows holds notifications in the notification centre
instead of popping them up, so QRes GUI also shows the latest one in a banner
until you dismiss it. **Settings › Send test notification** checks they work.

## Using it

1. Install:
   - **From a release:** download `QResGUI-<version>-win64.zip` from
     [Releases](https://github.com/TheRealestNwah/qres-gui/releases), extract it
     and double-click `install.cmd`.
   - **From source:** run `.\install.ps1` (see Development).

   Either way it installs to `%LOCALAPPDATA%\Programs\QResGUI` and adds
   **QRes GUI** to the Start menu and to *Settings › Apps*. Installing a newer
   version the same way updates it in place. The folder never moves, so
   existing hooks keep working.
2. Open **QRes GUI**. If QRes.exe isn't on your PATH or in the install folder,
   it asks you where it is. Select a game, tick **Switch resolution when this game
   launches** and pick the resolution. **Test for 10 seconds** tries the mode
   and switches back on its own. **Switch back the moment the game closes**
   skips the few seconds normally allowed for games that restart themselves.
3. Hook it up:
   - **Steam:** close Steam (the **Close Steam** button asks it to exit), then
     **Apply to Steam**, or **Update Steam launch options** in the top bar to do
     every enabled game at once. Steam overwrites `localconfig.vdf` when it
     exits, so writing is blocked while it runs. **Copy** gives you the string
     to paste into *Properties › General › Launch options* by hand instead. A
     timestamped backup of `localconfig.vdf` is kept next to it (last 5).
   - **Other stores:** **Create desktop shortcut** / **Add to Start menu**.
4. **Game process** (optional for Steam and GOG, required for games started
   through a store link: Epic, Ubisoft, Heroic's Epic/Amazon, Amazon Games):
   the exe name(s) to wait for. Use it when a game hands off to a different exe,
   or leaves a launcher running after you quit.

### Removing it

- **Settings › Remove all hooks…** takes QRes out of every Steam game's launch
  options (keeping your own options), deletes the game shortcuts and turns
  switching off.
- **Uninstall** from *Settings › Apps* (or run `uninstall.ps1` in the install
  folder) does the same first, so no game is left pointing at a missing
  launcher. It then removes the program. It offers to close Steam if needed and
  asks before deleting your settings.

## Development

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install PySide6 psutil pyinstaller pytest pytest-timeout
.venv\Scripts\pythonw QResGUI.pyw         # run from source
.venv\Scripts\python -m pytest            # tests (don't change the real resolution)
.\build.ps1                               # -> dist\QResGUI\
.\install.ps1                             # build + install for the current user
.\package.ps1                             # build + release\QResGUI-<version>-win64.zip
```

The version lives in `qres_gui/__init__.py` (mirrored in `pyproject.toml`).

Run from source, the GUI writes launch options that call
`.venv\Scripts\pythonw.exe QResLauncher.pyw`. That works, but the built exe
is the stable target.

Layout:

- `qres_gui/display.py`: read modes (EnumDisplaySettings), switch via QRes / API
- `qres_gui/launcher.py`: the `run` / `restore` / `remove-hooks` / `guard` entry points
- `qres_gui/hooks.py`: finds and removes Steam launch options and game shortcuts
- `qres_gui/notify.py`: toast notifications and the event record behind the GUI banner
- `qres_gui/vdf.py`: Valve KeyValues reader/writer (round-trips Steam's files byte for byte)
- `qres_gui/stores/`: per-store detection; `steam.py` also edits launch options
- `qres_gui/gui/`: PySide6 UI
- Logs: `%APPDATA%\QResGUI\launcher.log`

## Known limitations

- Only the primary display is switched (QRes's own behaviour).
- EA app, Battle.net and Xbox / Game Pass aren't auto-detected, nor are
  standalone legendary / nile installs (only Heroic's). Use **Add game…** for
  games with a plain exe; Game Pass apps generally can't be started that way.
- Heroic and Amazon Games detection follows those apps' file formats but
  hasn't been tried against a real install yet.
- Some anti-cheat launchers dislike being started by another process. If a game
  refuses, remove the hook and use **Test** / manual switching instead.
- After the game exits, switching back waits about 4 s (3 s to allow for games
  that restart themselves, plus the configurable restore delay) unless the game
  has **Switch back the moment the game closes** ticked.

## License

MIT; see [LICENSE](LICENSE). QRes itself is a separate program with its own terms.
