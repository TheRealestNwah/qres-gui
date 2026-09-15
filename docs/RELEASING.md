# Releasing

CI (`.github/workflows/ci.yml`) builds and publishes releases; nothing is
uploaded from a local machine.

## Branches

`main` holds the latest released version, so it matches what people can
download. Work in progress lands on a branch named for its feature and
reaches `main` through a pull request; a release is cut by tagging `main`
once the release's work has merged. CI runs on every push to `main` and on
every pull request, so a feature branch is tested the whole way in.

One feature per branch is the default. When a feature depends on work that
hasn't merged yet, branch off *that* branch rather than `main` and point its
pull request at it too, so what's under review is only the new feature; GitHub
moves it to `main` when the parent merges. Merge them in order, parent first,
and merge the parent with a merge commit rather than a squash — a squash
rewrites the parent's history into a commit the child doesn't share, which is
what turns the follow-on merge into a conflict.

What keeps a branch short-lived is being able to finish it, and some of this
app can only be finished on hardware CI doesn't have: an HDR display, a second
monitor, a particular store's launcher. A feature like that will sit unmerged
and collect dependents, so it's worth knowing which kind you're starting before
you start it.

## Any release

1. Rename `CHANGELOG.md`'s `## Unreleased` section — where each merged pull
   request adds its entry — to `## <version> — <date>` (CI turns it into the
   release notes; relative links are made absolute).
2. Bump the version in `qres_gui/__init__.py` and `pyproject.toml`.
3. Set `__prerelease__` in `qres_gui/__init__.py`: `True` to publish for
   testing, `False` for a finished release. Keep `__version__` a plain
   `x.y.z` — `updates.parse_version` only understands that shape, so an
   `-rc` suffix would make the update check read the running version as
   `0.0.0` and offer the *previous* release as an upgrade.
4. Merge the release's pull requests into `main`; wait for CI to pass there.
5. `git tag v<version> main` and `git push origin v<version>`. CI checks the tag
   matches the version, builds the zip, and publishes the release: a
   pre-release if `__prerelease__` is `True` or the version is 0.x, a normal
   ("latest") release otherwise.
6. Optionally add a "Superseded by …" line to the previous release's notes.

## Releasing without a local git

Actions › CI › **Run workflow** does steps 4-5 from a browser (the GitHub
mobile app included). Give it the tag to create and what to release - a branch
or a commit SHA - and it tests, builds, creates the tag and publishes, all from
the one run. The version check still applies, so the tag has to match
`__version__` at that commit.

It has to publish in the same run because a tag created by Actions' own
`GITHUB_TOKEN` cannot start another workflow run, so the `push: tags` trigger
never fires for it.

A pre-release is never offered by the in-app update check to anyone on 1.0 or
later (`updates.newest`), so it reaches only people who go to the releases
page. To promote one once it's proven, set `__prerelease__ = False`, bump the
patch version and tag that — a published tag can't be re-pointed.

## 1.0 — done 2026-09-13

Kept for reference. 1.0.0 shipped after: a GOG game started from Playnite
verified (Stardew Valley); a clean Windows Defender scan (0.9.0, signatures
1.459.180.0); releases left unsigned by choice. The changelog got a `## 1.0.0`
section, the README status box became a "Tested with" note, and `v1.0.0` was
tagged so CI published it as the latest (non-pre-release) release.
