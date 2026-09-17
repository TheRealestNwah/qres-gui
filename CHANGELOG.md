# Changelog

All notable changes to QRes GUI. Versions before 1.0 were marked as
pre-releases on GitHub, as is any later version that ships for testing before
it has been proven on real hardware.

## Unreleased

### Added
- **Install update**, right from the update banner. It downloads the release
  zip from this project's GitHub releases, checks it against the SHA-256
  checksum GitHub lists for it and that it holds the version it says, then
  closes QRes GUI, runs the zip's `install.ps1` — the same as installing by
  hand — and opens QRes GUI again, which says it's been updated. Profiles,
  settings and hooks stay as they are. Only the installed copy offers it, and
  not while a game is running through QRes. If installing fails, QRes GUI
  opens at the version you had and says why (the installer's output is in
  `%APPDATA%\QResGUI\update.log`). Nothing is downloaded until you click it.

### Fixed
- **Games that only ship a Unity-made launcher are no longer called Unity
  games.** The METAL GEAR SOLID Master Collection's MGS2, MGS3 and Metal Gear
  & Metal Gear 2 run on their own engine, but their `launcher.exe` is built
  with Unity, so they were offered Unity's engine options, which mean nothing
  to the games. A folder now counts as a Unity game only when every program in
  it (apart from Unity's crash handler) is a Unity player with its own
  `_Data` folder. Engine choices saved for a game whose folder no longer shows
  that engine are left off its command line.

## 1.7.0 — 2026-09-16

Commands around the switch, and engine games told their resolution. Both are
covered by tests — the commands run for real through cmd.exe in them — but
haven't been tried on real hardware yet. A game with no commands and no engine
options launches exactly as in 1.6.0.

### Added
- **Commands before and after the switch**, for every game (Settings ›
  Switching) and per game (the game's new Commands box). "Before" runs just
  before QRes switches the display, "after" once it's switched back — however
  that happens: the game exiting, Steam's Stop, Playnite's stop script or
  Restore desktop resolution. Every-game commands wrap around a game's own.
  QRes waits up to 15 seconds for each, then carries on, and anything a command
  starts keeps running; a failing command never stops a game from starting.
  Commands get `QRES_EVENT`, `QRES_GAME` and `QRES_GAME_ID`. Backups carry
  them, and an import that would add commands lists each one word for word
  before anything is applied.
- **Engine games can start at their profile's resolution.** Unity and Unreal
  games get a *Start at this game's resolution* choice among their engine
  options, which passes the size the profile switches to
  (`-screen-width`/`-screen-height`, `-ResX`/`-ResY`) so a borderless game fills
  the switched desktop instead of an older remembered size. It follows the
  profile: change the resolution and the flags change with it.

## 1.6.0 — 2026-09-15

The six issues found while testing 1.3–1.5. Everything below is covered by
tests and the new screens were checked with the real theme; the launcher
changes — extra arguments and engine options reaching Steam games — haven't
been tried on real hardware yet. A game with no extra arguments or engine
options starts exactly as before.

### Added
- **Engine options as choices** ([#14](https://github.com/TheRealestNwah/qres-gui/issues/14)).
  For games made with Unity or Unreal Engine, the Extra arguments box offers
  the options the engine documents for every game made with it: window mode,
  graphics API and, for Unity, which monitor — no need to know the flags.
  The engine is told from files in the game's folder and nothing is looked up
  online; the box shows exactly what the choices add, and anything you type
  goes after them. Backups carry the choices.
- **Hide games from the list** ([#10](https://github.com/TheRealestNwah/qres-gui/issues/10)):
  right-click a game › **Hide from list**. Only the list changes — a hidden game
  keeps its profile and still switches when started. While anything is hidden,
  the line under the list says how many, with a **Show** link; hidden games then
  appear greyed with *(hidden)*, and right-click › **Show in list** brings one
  back. Nothing is added to the window when nothing is hidden. Backups carry
  the hidden list.

### Changed
- **Settings is organised into tabs** ([#11](https://github.com/TheRealestNwah/qres-gui/issues/11)):
  General, Switching, Tray & hotkeys, Integrations, Updates, and Help & About,
  instead of one long form of sixteen rows. The dialog is less than half as
  tall, the hints are shorter, and **Remove all hooks…** sits apart at the
  bottom of Integrations rather than between everyday settings. Buttons in a
  row no longer touch.
- **Extra arguments work for Steam games, including ones started from
  Playnite** ([#13](https://github.com/TheRealestNwah/qres-gui/issues/13)).
  Steam games had no field at all. Now the launcher adds a game's extra
  arguments after Steam's own command whenever Steam starts it through QRes,
  so they apply whether you start it from Steam or from Playnite, your own
  Steam launch options stay as they are, and changing them doesn't need Steam
  closed.
- Extra arguments have their own box in the game panel, which says in the
  open where they apply for that game — and, for games Playnite starts
  directly, where to set them instead (Playnite's Edit › Actions) rather than
  offering a field that would be ignored. It used to be a tooltip.

### Fixed
- **Dropdowns and number fields look like what they are**
  ([#9](https://github.com/TheRealestNwah/qres-gui/issues/9)). Their outline all
  but vanished against the window, a dropdown's arrow sat in a box of its own,
  and the **Wait** fields in Settings had no visible up/down buttons at all.
  Fields now have a border you can see, dropdowns a chevron, number fields
  proper arrows, and disabled ones grey out. The store filter above the game
  list is a single pill, so it reads as a dropdown at a glance.
- **Running a copy of QRes GUI that isn't the installed one no longer takes
  over your games' hooks** ([#12](https://github.com/TheRealestNwah/qres-gui/issues/12)).
  An unzipped download or a test build used to call every Steam launch option
  and Playnite script "outdated" and offer to point them at itself — and once
  that folder was deleted, those games stopped launching from Steam. Steam,
  Playnite and shortcuts now always use the installed copy when there is one,
  whichever copy is open; only with nothing installed do they point at the copy
  you're running, and **Settings › Launcher** says so.
- Launch options that run a QRes launcher which has since been deleted are
  called **broken** rather than just "need updating", since Steam can't start
  those games at all.
- **Diagnostics** said "installed build" for any packaged copy, including one
  in Downloads. It now tells an installed copy from an unzipped one, and shows
  which launcher games actually go through.

## 1.5.0 — 2026-09-14

Checked on a real PC: exporting, restoring a backup over changes made since
(including a game set up after it), and importing a damaged file.

### Added
- **Back up and restore profiles** (Settings › Profiles › **Back up and
  restore…**). Export your game profiles, presets and settings to a file, and
  import them on another PC or after a reinstall.

  Importing works one of two ways. **Restore**, the default, makes everything
  match the file: profiles and presets set up since it was made are removed, and
  so is a setting within a profile the backup didn't have. **Merge** adds and
  updates what the file names and removes nothing, for bringing profiles to
  another PC. The summary before you apply lists everything that will be
  removed, including games you added by hand, which come off the list.

  An export carries only what means the same thing anywhere. It leaves out
  where QRes.exe is, your desktop resolution and the update-check state, and
  for each game the `launch` block and install folder the stores report — a
  rescan fills those in again, so copying them would point a profile at a path
  that isn't there. Games added by hand keep their path, since they have no
  store to be found from.

  Games are matched by their store ID, and a store game's own `launch` block
  is never overwritten. A display a profile names is kept only when a monitor
  of the same name *and* number is connected here, and otherwise falls back to
  the primary display — `\\.\DISPLAY2` is a different monitor on a different
  PC, and switching the wrong screen is worse than switching none. A preset
  whose shortcut is already in use here comes in without one. Nothing is
  applied until you've seen a summary of exactly what will change.

### Fixed
- **Settings** scrolls instead of growing past the bottom of the screen. On a
  1080p display, or with Windows scaling, OK and Cancel ended up out of reach;
  they now stay put below the settings.

## 1.4.0 — 2026-09-14

Checked on a real PC with an HDR display: the panel reports the QRes.exe in
use, the display and its mode, and HDR as available and on.

### Added
- **Diagnostics panel** (Settings › Help › **Diagnostics…**). One screen showing
  what QRes GUI can actually see: its version and where it keeps its settings
  and log, the Windows build, which QRes.exe it found, every connected display
  with the mode it's running, whether HDR is available on each — and the reason
  in Windows' own words when it isn't — any switch being tracked right now and
  what it will restore, the Playnite and notification state, and the last update
  check. Rows that went wrong are highlighted, and **Copy for a bug report** puts
  the lot on the clipboard as plain text.

  Most of [Troubleshooting](docs/TROUBLESHOOTING.md) opens by asking you to find
  one of these out. Nothing is sent anywhere, and opening the panel never starts
  an update check — it reads the last result from your settings instead.

## 1.3.0 — 2026-09-14

HDR switching has been tested on a real HDR display: turned off for a game
and put back on a normal quit, Steam's **Stop**, the game being killed in Task
Manager, and **Restore desktop resolution** mid-game. Switching a second
monitor hasn't been tried with more than one screen connected yet; reports
welcome. Existing profiles are unaffected: HDR and display selection are off
unless a profile asks for them, and a profile that names no display still
means the primary one.

### Added
- **Per-game HDR.** A game's profile can turn HDR on or off while it runs and
  put it back when it exits — on for a game that wants it, off so an SDR game
  doesn't look washed out. QRes can't switch HDR, so this goes through the
  Windows display API (`DisplayConfig`, Windows 10 1709 and later). Where HDR
  isn't available the control is greyed out and says why, and a failed switch
  never stops a game from starting.
- **Per-game display selection.** A game's profile can switch any connected
  display, not just the primary one. The **Display** row at the top of the
  Display box lists every monitor Windows reports, and the resolution and
  refresh-rate choices come from the screen you pick. The default, *Primary
  display*, follows whichever screen Windows calls primary, so it survives
  re-plugging. HDR follows the same screen, so the two can't land on different
  monitors.

  The chosen display and the desktop's HDR state are both recorded alongside
  the resolution, so the guard, **Restore desktop resolution**,
  `QResLauncher.exe restore` and Playnite's stop script all put back the screen
  that was actually changed, in the state it was in. A profile naming a monitor
  that isn't plugged in switches nothing and says so, rather than switching a
  different screen.
- **Presets name a display too.** The preset editor has a Display row, and a
  preset's global hotkey switches the screen the preset names — a hotkey fires
  with no window in front of you, so the screen has to come from the preset
  itself. Chips, the tray menu and the presets list all match against the
  preset's own screen, and a preset whose display isn't connected switches
  nothing and says so.
- **Custom launch arguments** for store games QRes GUI starts itself (GOG, EA,
  Amazon, standalone): an **Extra arguments** field, added after the store's own
  arguments and kept when a rescan refreshes them. They apply to shortcuts QRes
  made and to **Play**; Steam games keep using Steam's own launch options.

### Changed
- A game's **Resolution** box is now **Display**, covering the screen,
  resolution, refresh rate and HDR together.
- `display` and `hdr` both take a display throughout, defaulting to the primary
  one, so existing profiles behave exactly as before.
- QRes.exe drives the primary display only — it has no monitor argument — so a
  named secondary screen goes through the Windows display API instead. Primary
  profiles still try QRes first.

### Fixed
- **Restore desktop resolution** now puts back HDR, and the display the session
  record names rather than always the primary one. It only ever switched the
  primary's resolution, which mattered because that button is where the
  launcher's own failure notifications send you; every automatic path was
  already correct.
- The guard no longer gives up when the display a profile named has been
  unplugged mid-game; it falls through to the restore attempt instead.
- A leftover session record is now judged against the display it names. It was
  compared with the primary, so a chance match would clear the record and
  strand the other screen with nothing left to restore from.
- A leftover record for a *different* screen is no longer inherited as this
  screen's desktop mode, which could put one display's resolution on another.
- The Quick switch tooltip and `modes_for`'s docstring still said presets were
  primary-only after presets learned to name a screen.
- The HDR control said "Your primary display doesn't report HDR support" no
  matter which display it was reporting on, and the Getting started guide still
  said other monitors are left alone.
- **Getting started** now covers per-game displays and HDR, tailored to the PC
  it's running on rather than promising a second screen or an HDR toggle that
  isn't there.

### Removed
- `display.monitor_count`, which only fed the "QRes only switches the primary
  one" warning that the display picker replaces.

## 1.2.0 — 2026-09-13

### Added
- **System-tray icon** with the current resolution, your presets, restore, and
  show/quit. Optionally **keep running in the tray** when the window is closed.
- **Global hotkeys**: give any preset, or *Restore desktop resolution*, a
  system-wide shortcut (needs a modifier, e.g. Ctrl+Alt+1) that works from
  anywhere, including inside a game.

## 1.1.0 — 2026-09-13

### Added
- **Quick resolution switching.** A Quick switch strip under the top bar
  changes the primary display's resolution on the spot, with saveable
  one-click presets (Manage presets…). Applying one asks whether to keep it
  and reverts after 15 seconds if you don't, so a bad mode can't strand you.
  Presets for a resolution Windows doesn't currently offer are flagged, with a
  note to create it as a custom resolution in your graphics control panel
  first.

## 1.0.0 — 2026-09-13

First stable release. Everything from the 0.x pre-releases: per-game
resolution profiles switched through QRes; Steam launch options, shortcuts,
and Playnite integration for every other store; safety nets for Steam's Stop
button and launchers or Playnite going away mid-game; notifications; the
installer, update check and Getting started guide.

Tested with MGS4 (Steam, and via Playnite) and Stardew Valley (GOG via
Playnite). Detection for Epic / Ubisoft / Heroic / Amazon / EA / Battle.net /
Xbox is built to those tools' file formats but not yet tried on a real
install. Releases are unsigned.

## 0.10.0 — 2026-09-13

### Added
- An **AI disclosure**: QRes GUI was written by Claude (Anthropic's AI
  assistant), directed and tested by the maintainer. Noted in the README and
  in **Settings › About**.

### Changed
- QA pass: a switch that fails now never stops the game from starting
  (any error while switching is caught, reported, and the game launches at the
  current resolution). Process tracking ignores a game's parent id once
  Windows has reused it for an unrelated process. Linting (ruff) added and
  clean.

### Prepared for 1.0
- From 1.0, releases are published as normal GitHub releases instead of
  pre-releases, and the update check offers people on a finished version only
  finished versions.

## 0.9.0 — 2026-09-12

### Added
- **Getting started guide** for new installs: what QRes GUI does, finding
  QRes.exe, your desktop resolution and what games switch to, how you start
  games (Steam, Playnite with a one-click **Add QRes to Playnite**, shortcuts
  for everything else), and picking a first game. Existing setups skip it;
  **Settings › Getting started…** reopens it any time.
- **Settings › Help** with the guide and the troubleshooting page.

## 0.8.0 — 2026-09-12

### Added
- **Update check.** At most once a day QRes GUI asks GitHub for this
  project's release list and, if there's a newer version, shows a banner with
  **What's new** and **Later** (hidden until the next version). Nothing about
  your PC is sent and nothing is downloaded for you. **Settings › Updates**
  turns it off or checks right away; `QResLauncher.exe check-update` logs the
  result for troubleshooting.

## 0.7.0 — 2026-09-12

### Added
- [Troubleshooting guide](docs/TROUBLESHOOTING.md): stuck resolutions,
  what the notifications mean, games that switch back too early or late,
  Steam, Playnite, notifications, SmartScreen / antivirus.
- Screenshots in the README.
- Automated builds: GitHub Actions runs the tests and builds the zip on every
  push, and publishes releases from version tags. Dependencies are pinned
  (`requirements.txt`, `requirements-dev.txt`).

### Fixed
- Settings: the hints under "Desktop resolution", "Notifications",
  "Playnite" and "Hooks" were cut off.

## 0.6.0 — 2026-09-12

### Added
- Third-party license notices (`THIRD_PARTY_NOTICES.md`) and license texts
  shipped in the download's `licenses` folder; **Settings › About › Licenses…**
  opens it.
- The app says plainly that QRes switches the **primary display only**, and
  warns in the game panel when more than one display is connected.
- This changelog.

### Changed
- The download no longer carries Qt parts QRes GUI never used (QML/Quick,
  PDF, network, SVG, OpenGL, Virtual Keyboard). It's smaller, and its Qt
  licensing is LGPL Core/GUI/Widgets only.

## 0.5.0 — 2026-09-12

### Added
- Games started from Playnite that QRes has no profile for are listed
  automatically, with **Play in Playnite** and **Remove from list**.
- Detection of EA app, Battle.net and Xbox app / PC Game Pass games.
- Tests for the GUI itself.

## 0.4.0 — 2026-09-12

### Added
- Playnite integration through Playnite's global game scripts (added for
  you, or copied by hand); matches games by store ID, install folder or name.
- Detection of Legendary and Nile (standalone or through Playnite plugins)
  and GOG OSS installs.

### Fixed
- Steam's **Stop** button left the game running and could leave the
  resolution switched. The game now closes with the launcher, and the
  backup process is started outside Steam's reach so it always switches back.
- If Playnite (or the launcher) goes away mid-game, the resolution stays
  until the game really exits.

## 0.3.0 — 2026-09-12

### Added
- Detection of Heroic (Epic, Amazon, GOG) and Amazon Games app installs.

## 0.2.0 — 2026-09-12

### Added
- Launcher problems appear as Windows notifications instead of message
  boxes, plus a banner in QRes GUI for the latest one.
- **Settings › Send test notification**.

### Changed
- Version numbers are plain (0.1.0, 0.2.0, …) and marked as pre-releases.

## 0.1.0 — 2026-09-10

First public pre-release: per-game resolution profiles, Steam launch
options, shortcuts for GOG / Epic / Ubisoft / manual games, the launcher
with process tracking and safety nets, installer and uninstaller, quick
switch-back, and **Remove all hooks**.
