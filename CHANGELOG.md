# Changelog

All notable changes to QRes GUI. Versions before 1.0 are marked as
pre-releases on GitHub.

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
