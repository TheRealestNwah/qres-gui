# Troubleshooting

Start with **Settings › Help & About › Diagnostics…**: it shows what QRes GUI can actually see
— which QRes.exe it found, every display and the mode it's running, whether HDR
is available on each and why not when it isn't, and any switch being tracked
right now. **Copy for a bug report** puts the lot on the clipboard.

Then the log: **Settings › Integrations › Open log folder**, then open `launcher.log`
(`%APPDATA%\QResGUI\launcher.log`). Every launch writes what it switched,
which processes it followed and when it switched back. When reporting a
problem, include the diagnostics and the lines from that launch.

## The screen is stuck at the game's resolution

- Click **Restore desktop resolution** in QRes GUI's top bar.
- Or run `QResLauncher.exe restore` from the install folder
  (`%LOCALAPPDATA%\Programs\QResGUI`).
- Or reboot: by default switches are temporary (QRes `/D`, never saved to the
  registry), so Windows always starts at your normal resolution.

QRes GUI also notices a switch that was never undone the next time it starts,
and offers to restore it.

## A notification said "Resolution restored"

Something ended while a game was running at a switched resolution, and QRes
cleaned up:

- **"The launcher … was closed (for example with Steam's Stop button)"**: the
  program Steam (or a shortcut) started was ended. The game is closed with it,
  and the resolution is switched back.
- **"Playnite closed while … was running"**: QRes kept the game's resolution
  until the game itself exited, then switched back.

Nothing needs fixing; it's the safety net working.

## The game still starts at the old resolution, or looks wrong

- **Use Test for 10 seconds** in the game's panel to check the resolution and
  refresh rate work on your display at all.
- **Raise "Wait after switching"** (Settings). Some games read the desktop size
  the moment they start, before the display has settled.
- **Check the game's own display mode.** Borderless / windowed-fullscreen games
  take the desktop resolution, which is what QRes changes. A game in exclusive
  fullscreen picks its own mode and may ignore the desktop.
- **Is the game on your primary display?** QRes only switches the primary
  display. Games on other monitors keep that monitor's resolution.
- **Is it hooked up?** The **Launch hook** column should say how: Steam launch
  options, a shortcut, or Playnite. Starting a non-Steam game from its store's
  own button bypasses QRes unless Playnite's scripts are in place.

## It switches back too early

The game handed over to another process that QRes didn't follow, or a launcher
closed and QRes thought the game was done.

- Put the real game exe (e.g. `Game-Win64-Shipping.exe`) in the game's
  **Game process** box. QRes then waits for that process instead.
- Started from Playnite: switching back happens when Playnite reports the game
  stopped. If a Playnite library plugin reports that too early, adding QRes's
  Steam launch options or a shortcut can be more precise.

## It switches back too late, or never

- A launcher that stays open after you quit keeps QRes waiting. Name the real
  game exe under **Game process**.
- Tick **Switch back the moment the game closes** to skip the usual few seconds'
  wait after the game exits.

## Steam launch options

- **"Apply to Steam" is greyed out:** Steam is running, and it overwrites its
  settings file when it exits. Use **Close Steam**, or **Copy** the options and
  paste them into Steam › right-click the game › Properties › General ›
  Launch options.
- **"Launch options need updating":** the launch options run a different copy
  of QRes GUI than the installed one — an unzipped download, say. Close Steam
  and click **Update Steam launch options** in the installed QRes GUI.
- **"Launch options broken":** they run a QRes launcher that has since been
  deleted or moved, so Steam can't start the game at all. Same fix: close
  Steam, then **Update Steam launch options**.
- **Trying out a different version:** unzip it anywhere and run it — Steam,
  Playnite and shortcuts keep using your *installed* copy, so nothing breaks
  when you delete the test folder. The flip side is that games launch the way
  the installed version works; to try a new version's switching, install it
  (`install.cmd`). **Settings › Integrations › Launcher** and **Diagnostics** say which copy
  games launch through. With nothing installed, hooks point at the copy you're
  running, so don't move or delete its folder while games are set up.
- A backup of Steam's `localconfig.vdf` is kept next to it (the last five),
  named `localconfig.vdf.qresgui-<date>.bak`.

## Playnite

- **Nothing switches:** check **Settings › Integrations › Playnite integration…** says the
  scripts are added (Playnite must be closed while QRes changes them). Then
  make sure the game has a profile with switching turned on.
- **A game isn't in QRes GUI:** start it from Playnite once. QRes lists games
  Playnite starts that it doesn't know yet.
- The log says `no QRes profile for Playnite game …` when a started game wasn't
  matched.

## Notifications don't appear

Windows holds notifications back while a fullscreen game has focus (and when
Do Not Disturb is on); they wait in the notification centre, and QRes GUI
shows the latest one in a banner. **Settings › Integrations › Send test notification** checks
they work at all.

## The update check

**Settings › Updates › Check now** says whether GitHub has a newer release. If
it can't reach GitHub (offline, a firewall, a proxy), it says so and the daily
check simply tries again another day. `QResLauncher.exe check-update` writes
the same result to the log. Updating means downloading the new zip from the
release page and running `install.cmd`; your settings and hooks are kept.

## A preset or quick switch doesn't work

QRes can only switch to a resolution Windows already offers. If a preset is
flagged "needs a custom resolution", or a switch fails saying Windows isn't
offering that size, create it first as a **custom resolution** in your graphics
control panel (NVIDIA Control Panel, AMD Software, or Intel Graphics Command
Center), then try again. Applying a resolution always asks *Keep this
resolution?* and reverts after 15 seconds on its own, so a bad choice can't
leave you stuck.

## The wrong screen switched, or nothing switched

**Settings › Help & About › Diagnostics…** lists every display Windows reports, which one is
primary, and the mode each is running — start there if you aren't sure which
screen is which.

Check the **Display** row at the top of the game's Display box. *Primary
display* — the default — follows whichever monitor Windows currently calls
primary, so moving cables around can move which screen a game switches. Name
the monitor explicitly if you mean that one.

If the profile names a display that isn't connected, QRes GUI switches nothing
at all and notifies you, rather than switch a different screen. Plug it back in,
or set the game to a screen you have.

Quick switching, presets and their hotkeys always act on the primary display,
whatever a game's profile says.

## The HDR control is greyed out

QRes GUI only offers HDR where Windows says it's available on the display the
profile names — the primary one unless you picked another. The greyed-out
control says which of these it is:

**Settings › Help & About › Diagnostics…** lists every display with its HDR state and the same
reason, which is quicker than checking one profile at a time.

- *This version of Windows doesn't have the HDR display setting* — it needs
  Windows 10 1709 or newer.
- *This display doesn't report HDR support* — the monitor, the cable or
  the driver isn't offering it. Check *Settings › System › Display › HDR* in
  Windows: if **Use HDR** isn't there for this display either, QRes GUI can't
  add it.
- *Windows has HDR switched off for this display* — Windows is currently
  refusing it (a display mode that can't carry HDR, or the setting blocked).
  Turn it on once in Windows and the control comes back.

On more than one display, remember QRes GUI only ever touches the primary one,
so check Windows' HDR setting for *that* display.

## HDR didn't switch, or didn't switch back

The game starts either way — HDR is never allowed to hold it up — and a
notification says what failed. HDR is recorded in `session.json` next to the
resolution, so **Restore desktop resolution** in the top bar (or
`QResLauncher.exe restore`) puts both back. `%APPDATA%\QResGUI\launcher.log`
has the detail.

A second or two of black screen each way is normal: the display re-syncs when
HDR changes.

## Extra arguments aren't being used

The game's **Extra arguments** box says where they apply for that game. In short:

- **Steam games** get them whenever Steam starts the game through QRes, so the
  QRes launch options have to be applied (the box says if they aren't yet).
  `launcher.log` shows `adding the profile's extra arguments` for each launch.
- **Other store games** get them only when QRes GUI starts the game — a
  shortcut it created, or **Play**. Starting it from the store's own client or
  from Playnite skips them, because those build the command line themselves.
  Put the arguments in that tool instead (Playnite: right-click the game › Edit
  › Actions).
- Some games ignore arguments they don't know. Check the game's own
  documentation or PCGamingWiki for what it accepts.

## QRes.exe isn't found

Point **Settings › General › QRes.exe** at it, or copy `QRes.exe` into the install
folder. Without QRes, switching falls back to Windows' own display API.

## Windows or antivirus warns about the download

The programs aren't code-signed yet, so SmartScreen may say "Windows protected
your PC": choose **More info › Run anyway**.

To avoid the warnings altogether, unblock the download before extracting it:
right-click the zip › **Properties** › tick **Unblock** › **OK**. Windows then
stops treating the extracted files as "from the internet". (In PowerShell:
`Unblock-File .\QResGUI-<version>-win64.zip`.) The launcher starts its
safety-net process through Windows' WMI service, which some antivirus tools
look at closely. The source is at <https://github.com/TheRealestNwah/qres-gui>
if you'd like to check or build it yourself.

## Importing profiles didn't bring everything across

By design. An export leaves out what only describes the PC it came from: where
QRes.exe is, the desktop resolution, and each game's `launch` block and install
folder, which the stores report and a rescan fills in again. Run a rescan on the
new PC and the store games find themselves.

Games you added by hand keep their path, because there's no store to find them
from — if one doesn't start, point it at the executable again in its profile.

A display a profile named is kept only when a monitor of the same name *and*
number is connected here. Otherwise that profile falls back to the primary
display and the import summary says which ones — `\\.\DISPLAY2` is a different
monitor on a different PC, so the alternative is switching the wrong screen.

Presets whose shortcut is already in use here come in without one; set a new
shortcut in **Manage presets**.

## Restoring a backup didn't undo a change

Check which way the import ran. **Merge** only adds and updates what the file
names, so a game you set up *after* making the backup keeps its new profile.
**Restore** (the default) is the one that undoes: it removes profiles and presets
the file doesn't have. The summary before you apply lists everything it will
remove.

A setting a backup doesn't know about is left as it is: a backup made before
**Switch back the moment the game closes** was saved in backups can't say
whether it was on, so restoring it doesn't turn it off.

## Removing QRes GUI

**Settings › Integrations › Remove all hooks…** takes QRes out of Steam's launch options and
Playnite's scripts and deletes the game shortcuts. Uninstalling from
*Settings › Apps* does the same first, then removes the program.
