# Troubleshooting

Start with the log: **Settings › Open log folder**, then open `launcher.log`
(`%APPDATA%\QResGUI\launcher.log`). Every launch writes what it switched,
which processes it followed and when it switched back. When reporting a
problem, include the lines from that launch.

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
- **"Launch options need updating":** QRes GUI was moved or reinstalled
  somewhere else. Close Steam and click **Update Steam launch options**.
- A backup of Steam's `localconfig.vdf` is kept next to it (the last five),
  named `localconfig.vdf.qresgui-<date>.bak`.

## Playnite

- **Nothing switches:** check **Settings › Playnite integration…** says the
  scripts are added (Playnite must be closed while QRes changes them). Then
  make sure the game has a profile with switching turned on.
- **A game isn't in QRes GUI:** start it from Playnite once. QRes lists games
  Playnite starts that it doesn't know yet.
- The log says `no QRes profile for Playnite game …` when a started game wasn't
  matched.

## Notifications don't appear

Windows holds notifications back while a fullscreen game has focus (and when
Do Not Disturb is on); they wait in the notification centre, and QRes GUI
shows the latest one in a banner. **Settings › Send test notification** checks
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

## QRes.exe isn't found

Point **Settings › QRes.exe** at it, or copy `QRes.exe` into the install
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

## Removing QRes GUI

**Settings › Remove all hooks…** takes QRes out of Steam's launch options and
Playnite's scripts and deletes the game shortcuts. Uninstalling from
*Settings › Apps* does the same first, then removes the program.
