# Git Strategy

How this project's repos, branches, versions, and releases are organized. Optimized for solo development with public distribution.

## The model in one sentence

One **private** dev repo (full history, Claude tooling, specs, plans) → filter out `.claude/` → force-mirror to one **public** repo. Single `main` branch on both. Atomic commits straight to main, no feature branches.

## The two repos

| | Private | Public |
|---|---|---|
| URL | `jaterrell/audio-dl-internal` | `jaterrell/audio-dl` |
| Role | Source of truth. Where you push. | Distribution mirror. Where users `pip install` from. |
| Contains | Everything in the working tree, including `.claude/`. | Everything except `.claude/`, with that path scrubbed from history. |
| Force-push | Normal `git push origin main` (no force needed). | Force-pushed via `--mirror` by `scripts/publish.sh`. Never push directly. |
| GitHub releases | Created manually with `gh release create`. | Created manually with `gh release create`. Releases do **not** transfer via `--mirror` — they're API objects, not git refs. |
| CI runs | Yes — `tests.yml` + `pylint.yml`. | Yes — same workflows (transferred via filter). README badges point here. |

The public repo is downstream. Anything you can do on public, you can re-derive from private. Anything you do on public that isn't on private gets blown away by the next `publish.sh` run.

## Branching

**One branch: `main`.** No feature branches, no PRs, no merge commits in normal flow.

This works because:
- One developer. No coordination cost.
- TDD discipline keeps each commit green — bisect stays useful.
- Spec → plan → implementation cycle produces a clean linear history naturally.
- Release is just a tag on a commit that's already on main.

When you would change this:
- Multi-developer collaboration — switch to feature branches + PRs.
- Long-running experimental work that shouldn't block routine fixes — branch it.
- Production deployments needing pre-release validation — branch for staging.

For now: stay on main, keep commits small and atomic, never push broken code.

## Versioning

**Semver: MAJOR.MINOR.PATCH.** Dual-sourced — both must match:

- `audio_dl.py` line ~31 — `__version__ = "X.Y.Z"`
- `pyproject.toml` line ~7 — `version = "X.Y.Z"`

Why dual: the runtime CLI needs `__version__` for `--version` output and any future "what version am I?" introspection; pip/pipx needs `pyproject.toml` for `pip install` resolution. Keeping them in sync is the entire reason `/release-helper` exists.

When to bump (during normal development on main):
- `MAJOR`: API-breaking change in `download_media` / `sanitize_url` / CLI flags. Rare.
- `MINOR`: user-visible feature (new format, web UI, new flag). Most releases.
- `PATCH`: bug fix only, no API change.

The bump can happen any time on main — it doesn't have to be the final commit before the tag. `release-helper` is built around the idea that you bump first, verify, then tag.

## Release flow (the manual recipe)

This is the canonical order. The `release-helper` skill handles steps 1-3; the rest is by hand.

```bash
# 1. Bump version + draft CHANGELOG (release-helper skill)
/release-helper 1.2.0
# → edits audio_dl.py + pyproject.toml + CHANGELOG.md
# → runs pytest + pylint to verify
# → stops here for you to review the diff

# 2. Commit the bump (skipped if version + CHANGELOG were already bumped during the work)
git add audio_dl.py pyproject.toml CHANGELOG.md
git commit -m "release: v1.2.0"

# 3. Tag (lightweight — precedent set by v1.0.0/v1.1.0)
git tag v1.2.0

# 4. Push commits + tag to PRIVATE
git push origin main --tags

# 5. Mirror PRIVATE → PUBLIC (filters .claude/, force-pushes --mirror)
./scripts/publish.sh

# 6. Re-create GitHub releases (NOT auto-transferred via --mirror)
# Extract this version's CHANGELOG section (header is "## vX.Y.Z" or "## [X.Y.Z]"):
awk '/^## v1.2.0/{p=1; next} p && /^## /{exit} p' CHANGELOG.md > /tmp/notes.md

gh release create v1.2.0 --repo jaterrell/audio-dl-internal \
  --title "v1.2.0 — <one-liner>" --notes-file /tmp/notes.md
gh release create v1.2.0 --repo jaterrell/audio-dl \
  --title "v1.2.0 — <one-liner>" --notes-file /tmp/notes.md
```

### If you tagged a broken commit

CI failing on a tagged commit is fixable but annoying. Pattern:

```bash
# Fix the issue, commit on main
git commit -am "ci: <whatever>"
git push origin main

# Delete the broken tag + releases
gh release delete v1.2.0 --repo jaterrell/audio-dl-internal --yes
gh release delete v1.2.0 --repo jaterrell/audio-dl --yes
git tag -d v1.2.0
git push origin :refs/tags/v1.2.0

# Re-tag on the fixed commit and push everything
git tag v1.2.0
git push origin --tags
./scripts/publish.sh
# Recreate releases as in step 6 above
```

Acceptable in the first ~hour after tagging when no one's consumed the release yet. If `v1.2.0` has been in the wild for any non-trivial time, fix-forward as `v1.2.1` instead.

## CHANGELOG format (be consistent)

Currently inconsistent — `v1.0.0` and `v1.1.0` use `## [X.Y.Z] - YYYY-MM-DD`, `v1.2.0` uses `## vX.Y.Z — YYYY-MM-DD`. Pick one and stick to it next time you touch the file. The `awk` extraction in step 6 above assumes the `## vX.Y.Z` form — if you switch styles, update the extraction.

## CI

Both repos run identical workflows:

- `.github/workflows/tests.yml` — pytest on Python 3.10–3.13.
- `.github/workflows/pylint.yml` — `pylint $(git ls-files '*.py')` on the same matrix.

Workflows live in the private repo's `.github/workflows/`. They transfer to public via `publish.sh` (they're not in `.claude/`).

README badges resolve to the **public** repo's CI runs. That's intentional — public is the user-facing home.

If you add a new dev-only dep (something tests or pylint need but the runtime doesn't), update **both** workflow files' `pip install` lines. Don't add it to `[project.dependencies]` or even `[project.optional-dependencies] ui` — those are runtime concerns. Workflow-only deps go in the workflow files directly. Common ones already there: `pytest`, `pylint`, `httpx`.

## Auth setup (one-time, per developer)

The system `git-credential-manager` was segfaulting (signal 11) on `gh`-managed credentials. Workaround wired system-wide:

```bash
git config --global \
  credential.https://github.com.helper \
  '!/opt/homebrew/bin/gh auth git-credential'
```

Future github.com git ops bypass the broken credential manager and go through `gh auth`. Survives session restarts.

If you move to a new machine: `brew install gh && gh auth login`, then run the credential helper line above.

## Recovery

**If something goes wrong on public:** re-run `./scripts/publish.sh`. It's idempotent. Private is authoritative; public is reconstructible.

**If `scripts/publish.sh` itself fails:** it has a SIGPIPE bug under `pipefail` when history is long enough — `git log --oneline | head -10` triggers SIGPIPE in newer git. The manual equivalent works:

```bash
WORK=$(mktemp -d)
git clone --bare --quiet https://github.com/jaterrell/audio-dl-internal.git "$WORK/repo.git"
cd "$WORK/repo.git"
git filter-repo --invert-paths --path .claude --force --quiet
git push --mirror https://github.com/jaterrell/audio-dl.git
rm -rf "$WORK"
```

Or fix `publish.sh:37` to use `git log -n 10 --oneline` (no pipe).

**If something goes wrong on private:** you're in trouble. Private is the source of truth. Recover from any local clone (`/Users/joe/src/audio-dl/.git`) — `git push --force origin main` from a known-good local. If everywhere is corrupted, the public repo's history can be re-imported (you'd lose `.claude/` permanently from history, which is fine in practice).

## Don'ts

- **Don't commit secrets.** Public repo has full filtered history. Anything you ever committed (other than `.claude/`) is on the public internet forever.
- **Don't push directly to public.** Always go through `scripts/publish.sh`. The public remote is `--mirror`-overwritten; any direct commits will be erased on the next mirror.
- **Don't rely on `--mirror` to copy GitHub releases.** They're API objects, not git refs. Manually `gh release create` on both repos every time.
- **Don't bump only one of the two version sources.** That's the entire reason `release-helper` exists — to prevent that exact trap.
- **Don't use annotated tags without checking precedent.** `v1.0.0`, `v1.1.0`, `v1.2.0` are all lightweight. If you switch to annotated, update `release-helper`.
- **Don't put dev-only deps in `[project.dependencies]` or `[ui]`.** Those are runtime concerns. CI deps go in `.github/workflows/*.yml`.
- **Don't include `.claude/` paths in commit messages expecting them to filter out.** `filter-repo --invert-paths` removes the files, not the references. If a commit message says "wired up `.claude/skills/release-helper`", that text persists in public history.

## When to revisit this strategy

This setup is right-sized for **one developer, two repos, small codebase, infrequent releases**. Triggers to redesign:

- Adding a second developer → feature branches + PRs.
- Adding CI/CD that auto-deploys → may want a `release/*` branch pattern.
- Public repo grows independent contributors → the force-mirror pattern starts erasing their work. Switch to public-as-source-of-truth with a private overlay for `.claude/` only.
- Phase 3 (PyInstaller `.app`) ships → release artifacts get bigger; consider GitHub Actions auto-building on tag push (the planned Phase 4).
