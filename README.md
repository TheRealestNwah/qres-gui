# QRes GUI

Switch Windows to a different desktop resolution while a particular game runs,
and back again when it closes. Made for games that only render correctly when
the *desktop* is at, say, 2560 × 1440 on a 3440 × 1440 ultrawide, because they
don't let you pick an exact resolution themselves.

Resolution changes go through [QRes](https://sourceforge.net/projects/qres/)
(the Windows API is only a fallback for switching back).

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

## Using it

1. Run `.\install.ps1`. It builds and installs to `%LOCALAPPDATA%\Programs\QResGUI`,
   adds **QRes GUI** to the Start menu and to *Settings › Apps*. Re-run it to
   update; the folder never moves, so existing hooks keep working.
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
4. **Game process** (optional for Steam and GOG, required for Epic and Ubisoft):
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
```

Run from source, the GUI writes launch options that call
`.venv\Scripts\pythonw.exe QResLauncher.pyw`. That works, but the built exe
is the stable target.

Layout:

- `qres_gui/display.py`: read modes (EnumDisplaySettings), switch via QRes / API
- `qres_gui/launcher.py`: the `run` / `restore` / `guard` entry points
- `qres_gui/vdf.py`: Valve KeyValues reader/writer (round-trips Steam's files byte for byte)
- `qres_gui/stores/`: per-store detection; `steam.py` also edits launch options
- `qres_gui/gui/`: PySide6 UI
- Logs: `%APPDATA%\QResGUI\launcher.log`

## Known limitations

- Only the primary display is switched (QRes's own behaviour).
- EA app, Battle.net, Xbox / Game Pass and Amazon aren't auto-detected. Use
  **Add game…** for games with a plain exe; Game Pass apps generally can't be
  started that way.
- Some anti-cheat launchers dislike being started by another process. If a game
  refuses, remove the hook and use **Test** / manual switching instead.
- After the game exits, switching back waits about 4 s (3 s to allow for games
  that restart themselves, plus the configurable restore delay) unless the game
  has **Switch back the moment the game closes** ticked.
