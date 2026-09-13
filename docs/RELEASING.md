# Releasing

CI (`.github/workflows/ci.yml`) builds and publishes releases; nothing is
uploaded from a local machine.

## Any release

1. Add a `## <version> — <date>` section to `CHANGELOG.md` (CI turns it into
   the release notes; relative links are made absolute).
2. Bump the version in `qres_gui/__init__.py` and `pyproject.toml`.
3. Commit and push `main`; wait for CI to pass.
4. `git tag v<version>` and `git push origin v<version>`. CI checks the tag
   matches the version, builds the zip, and publishes the release: a
   pre-release for 0.x, a normal ("latest") release from 1.0 on.
5. Optionally add a "Superseded by …" line to the previous release's notes.

## 1.0 checklist

Before tagging:

- [ ] Real-world checks done: a GOG OSS game started from Playnite, one
      exclusive-fullscreen and one borderless game.
- [x] Windows Defender scan of the installed app and the release zip is clean
      (done for 0.9.0 with signatures 1.459.180.0: clean).
- [x] Code signing: not for 1.0. Releases stay unsigned; the troubleshooting
      guide covers SmartScreen (Unblock, or More info › Run anyway).
      `docs/CODE_SIGNING.md` has the options if that changes.

Then:

- [ ] Rename `## Unreleased` in `CHANGELOG.md` to `## 1.0.0 — <date>` and
      describe the release.
- [ ] README: replace the "early pre-release" status box with a short
      "Tested with" note, keeping the known limitations section.
- [ ] Bump to `1.0.0`, push, tag `v1.0.0`. CI publishes it as the latest
      (non-pre-release) release; people on 1.0+ are then only offered finished
      releases by the update check.
