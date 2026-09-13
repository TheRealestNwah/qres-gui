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

## 1.0 — done 2026-09-13

Kept for reference. 1.0.0 shipped after: a GOG game started from Playnite
verified (Stardew Valley); a clean Windows Defender scan (0.9.0, signatures
1.459.180.0); releases left unsigned by choice. The changelog got a `## 1.0.0`
section, the README status box became a "Tested with" note, and `v1.0.0` was
tagged so CI published it as the latest (non-pre-release) release.
