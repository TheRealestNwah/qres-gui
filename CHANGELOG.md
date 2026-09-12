# Changelog

All notable changes to QRes GUI. Versions are marked as pre-releases on
GitHub until 1.0.

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
