# audio-dl Release Pipeline — design spec (Phase 3c + Phase 4)

**Status:** Design approved 2026-05-13. Implementation pending.
**Date:** 2026-05-13
**Owner:** Joe Terrell
**Target release:** v1.4.0
**Supersedes:** the Phase 3c / Phase 4 sections of `2026-05-13-app-bundle.md`.

## Purpose

Ship an automated release pipeline that turns a tag push into a downloadable, smoke-tested macOS arm64 `.app` on the public repo's Releases page, plus the distribution-UX polish needed for non-technical testers to get past Gatekeeper on first launch.

Combines two roadmap phases that the Phase 3a/3b spec deferred:

- **Phase 3c (slimmed):** Originally Developer-ID signing + notarization. Collapsed to a cleanup-and-docs slice because the project is staying unsigned. Drops dead Developer-ID `# TODO` blocks from `scripts/build-app.sh`, ships `INSTALL.md` and a bundled `README-FIRST.txt`, points the README at them.
- **Phase 4:** GitHub Actions release builder. Tag push to the public repo → macos-14 runner → build → smoke test → zip + SHA256SUMS → GH Release with CHANGELOG-extracted notes.

## Audience

Same as Phase 3a/3b — **trusted testers** on Apple Silicon Macs. The widening here is distribution surface (anyone with the public Releases URL can grab a build) rather than consumer polish. Gatekeeper friction remains; `README-FIRST.txt` and `INSTALL.md` are how we soften it.

## Goals (this slice)

- A `git push --tags` to the internal repo, followed by `scripts/publish.sh`, results in a fully populated v1.4.0 release on the public repo's Releases page with notes, the macOS .app zip, and a SHA256SUMS file — no manual `gh release create` step.
- The released bundle is verified to actually serve `GET /` before publish; a build that ad-hoc-signs but fails to bind cannot reach users.
- A first-time tester who downloads the zip can get the .app open without consulting the repo (instructions are bundled).
- All existing tests still pass. New tests cover the CHANGELOG extractor and the packaging script.
- Pylint ≥ 10.00/10 (current bar).

## Non-goals (deferred or rejected)

- **Apple Developer Program enrollment, Developer-ID signing, notarization, stapling.** Explicit "stay unsigned" decision. Removes ~$99/yr cost and credential management overhead.
- **Intel x86_64 builds, Universal2 fat binaries.** arm64-only for v1.4. Apple Silicon is the dev arch and dominates the trusted-tester audience. Intel users still get the CLI via source install.
- **DMG packaging.** Gives no UX win over zip for unsigned distribution; Gatekeeper friction is unchanged.
- **GPG-signed checksums.** SHA256SUMS for integrity is enough; provenance signing is more credential overhead than the audience needs.
- **Homebrew cask, Windows/Linux bundles, self-update, automated yt-dlp version pinning.** Each is its own slice if demand surfaces.
- **Automated rollback** on partial release failure. Manual `gh release delete` is one command; not worth the YAML complexity.

---

## Decisions (pinned)

| Decision | Choice | Reasoning |
|---|---|---|
| **Signing** | Ad-hoc only (`codesign --sign -`) | Already in `build-app.sh`. Suppresses runtime-integrity gripes without requiring a Developer ID. |
| **Architecture** | arm64 only | Single GH Actions job on `macos-14`. Matches dev arch and audience. |
| **Trigger** | `push: tags: ['v*']` + `workflow_dispatch` | Tag push is the default flow; dispatch is the re-run / hotfix safety net. |
| **Repo gating** | `if: github.repository == 'jaterrell/audio-dl'` | Workflow file lives in both repos (carried by the mirror). Only public runs it. Prevents private-repo waste and accidental uploads. |
| **Release notes source** | Auto-extracted from `CHANGELOG.md` | One canonical voice. Missing section = workflow fails loudly. |
| **Asset shape** | Zipped directory: `audio-dl-vX.Y.Z-macos-arm64/{audio-dl.app, README-FIRST.txt}` + `SHA256SUMS` | Bundled README-FIRST means first-launch instructions live next to the binary, not buried in the repo. |
| **Smoke test** | curl loop, 30s budget, fails the workflow on timeout | Highest-leverage gate; catches "builds clean, won't bind 8000" silent failures. |
| **CI artifact upload** | Before `gh release create` | If publish fails, the built zip is still downloadable from the Actions Artifacts panel — fallback distribution channel. |

---

## Release lifecycle

### Developer flow (manual, internal repo)

1. Bump `__version__` in `audio_dl.py` and `version` in `pyproject.toml`. (`/release-helper` enforces this dual-source.)
2. Add a `## v1.4 — <title> (YYYY-MM-DD)` section to `CHANGELOG.md`. This section's body becomes the GH Release notes verbatim.
3. Run tests + pylint locally as usual.
4. Commit, tag `v1.4.0` (or `v1.4` per CHANGELOG convention — the extractor handles either), push branch + tag to `origin` (internal).
5. Run `scripts/publish.sh` — filter-mirrors to public, including the new tag.

### CI flow (automated, public repo)

The tag push lands on `jaterrell/audio-dl`. The mirrored `.github/workflows/release.yml` fires:

1. **Guard:** `if: github.repository == 'jaterrell/audio-dl'` — internal mirror's same workflow file no-ops.
2. **Setup:** `actions/checkout@v4`, `actions/setup-python@v5` with `python-version: '3.12'`, install `-e '.[ui,app]'` + `pyinstaller`.
3. **Build:** `scripts/build-app.sh` produces `dist/audio-dl.app`.
4. **Smoke test:** `scripts/smoke-test-bundle.sh` boots the bundle binary with `--no-browser`, polls `http://127.0.0.1:8000/` for HTTP 200 with a 30s budget, kills the subprocess. Failure = workflow fails.
5. **Package:** `scripts/package-release.sh "$TAG"` stages `dist/release/audio-dl-${TAG}-macos-arm64/` with the `.app` and `README-FIRST.txt`, zips it, generates `SHA256SUMS`.
6. **Notes:** `scripts/extract-changelog.py "$TAG" > RELEASE_NOTES.md`. Missing section = exit 1 = workflow fails before publish.
7. **Upload artifacts:** `actions/upload-artifact@v4` attaches the zip + SHA256SUMS to the workflow run. **This runs before publish** so failed-publish runs still leave a downloadable artifact.
8. **Publish:** `gh release create "$TAG" --notes-file RELEASE_NOTES.md --title "$TAG" dist/release/*.zip dist/release/SHA256SUMS`, using the auto-provided `GITHUB_TOKEN`.

### Two-repo model interactions

- The workflow file is created in the internal repo and propagates to public via `scripts/publish.sh` like everything else. The gating `if:` ensures it only runs on public.
- Tags already propagate via `--mirror`. Release notes/assets don't — that's exactly what this workflow fixes.
- Internal repo continues to have no GH Releases. If internal-side artifacts are ever wanted, that's a separate decision.
- `scripts/publish.sh` itself is unchanged.

---

## Architecture

### File changes

| File | Action | Notes |
|---|---|---|
| `.github/workflows/release.yml` | Create | Single job, macos-14, tag-push + workflow_dispatch triggers, public-repo guard. |
| `scripts/smoke-test-bundle.sh` | Create | Shell-only. Launch → curl loop → kill. ~30 lines. |
| `scripts/package-release.sh` | Create | Shell-only. Stage dir → copy app + README-FIRST → zip → SHA256SUMS. ~25 lines. |
| `scripts/extract-changelog.py` | Create | stdlib-only Python. Tag-to-section parser. ~30 lines. |
| `scripts/release-templates/README-FIRST.txt` | Create | Static template bundled inside every release zip. ~60 words. |
| `scripts/build-app.sh` | Modify | Drop dead Developer-ID `# TODO` block (~9 lines). Replace with a one-line comment explaining the unsigned-by-design decision. |
| `_app_entry.py` | Modify | Switch from `sys.argv = sys.argv[:1]` (clears all) to selective `-psn_*` stripping. Required so the smoke test can pass `--no-browser`. ~5 line change. |
| `INSTALL.md` | Create | Full first-launch walkthrough. ~80 lines. |
| `README.md` | Modify | Add "Installing the .app" subsection inside the existing macOS section. Points to Releases page + INSTALL.md. ~15 line addition. |
| `CLAUDE.md` | Modify | Note: release pipeline section, updated `_app_entry.py` description (drop "clears all argv" if any wording implies that, confirm "selective strip of -psn_*"). ~10 lines. |
| `CHANGELOG.md` | Modify | New `## v1.4 — Automated macOS release pipeline (YYYY-MM-DD)` section. ~25 lines. |
| `pyproject.toml` | Modify | Bump version to 1.4.0. |
| `audio_dl.py` `__version__` | Modify | Bump to 1.4.0. |
| `test_audio_dl.py` | Modify | Add `TestExtractChangelog` (~6 tests) and `TestPackageRelease` (~1 test). |

### `.github/workflows/release.yml` shape

```yaml
name: Release

on:
  push:
    tags: ['v*']
  workflow_dispatch:
    inputs:
      tag:
        description: 'Tag to release (e.g., v1.4.0)'
        required: true

jobs:
  release:
    if: github.repository == 'jaterrell/audio-dl'
    runs-on: macos-14
    permissions:
      contents: write
    env:
      TAG: ${{ github.event_name == 'workflow_dispatch' && inputs.tag || github.ref_name }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install build deps
        run: |
          python -m pip install --upgrade pip
          pip install -e '.[ui,app]'
          pip install pyinstaller
      - name: Build .app
        run: scripts/build-app.sh
      - name: Smoke test bundle
        run: scripts/smoke-test-bundle.sh
      - name: Package release
        run: scripts/package-release.sh "$TAG"
      - name: Extract changelog section
        run: scripts/extract-changelog.py "$TAG" > RELEASE_NOTES.md
      - name: Upload workflow artifact
        uses: actions/upload-artifact@v4
        with:
          name: macos-arm64-bundle
          path: |
            dist/release/*.zip
            dist/release/SHA256SUMS
      - name: Publish GitHub Release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh release create "$TAG" \
            --title "$TAG" \
            --notes-file RELEASE_NOTES.md \
            dist/release/*.zip dist/release/SHA256SUMS
```

### `scripts/smoke-test-bundle.sh` shape

```bash
#!/usr/bin/env bash
set -euo pipefail

BIN="dist/audio-dl.app/Contents/MacOS/audio-dl"
LOG="$(mktemp)"
"$BIN" --no-browser >"$LOG" 2>&1 &
PID=$!
trap 'kill "$PID" 2>/dev/null || true' EXIT

for _ in {1..30}; do
    if curl -fsS http://127.0.0.1:8000/ > /dev/null 2>&1; then
        echo "Smoke test passed (uvicorn bound on :8000)."
        exit 0
    fi
    sleep 1
done

echo "Smoke test FAILED: bundle did not respond on :8000 within 30s." >&2
echo "--- bundle stderr ---" >&2
tail -n 50 "$LOG" >&2 || true
exit 1
```

### `scripts/package-release.sh` shape

```bash
#!/usr/bin/env bash
set -euo pipefail

TAG="$1"
STAGE_NAME="audio-dl-${TAG}-macos-arm64"
STAGE="dist/release/${STAGE_NAME}"

rm -rf dist/release
mkdir -p "$STAGE"
cp -R dist/audio-dl.app "$STAGE/"
cp scripts/release-templates/README-FIRST.txt "$STAGE/"

cd dist/release
zip -r "${STAGE_NAME}.zip" "$STAGE_NAME/"
shasum -a 256 "${STAGE_NAME}.zip" > SHA256SUMS
```

### `scripts/extract-changelog.py` shape

stdlib-only. Pseudocode:

```python
import re, sys, pathlib

def extract(tag: str, changelog: str) -> str:
    candidates = [tag, tag.removesuffix(".0")]  # v1.4.0 → also try v1.4
    for needle in candidates:
        pattern = rf"^##\s+{re.escape(needle)}(\s|$)"
        ...find section, capture until next "^## " or EOF, strip header line...
        if found:
            return body.strip() + "\n"
    raise SystemExit(f"extract-changelog.py: no ## {tag} section in CHANGELOG.md")

if __name__ == "__main__":
    print(extract(sys.argv[1], pathlib.Path("CHANGELOG.md").read_text()), end="")
```

### `_app_entry.py` change

Current:
```python
def _main() -> None:
    sys.argv = sys.argv[:1]   # ← clears everything
    _bootstrap_homebrew_path()
    from audio_dl_ui import main
    main()
```

New:
```python
def _main() -> None:
    # Strip only Finder-injected process-serial-number argv; preserve real flags
    # so a launch like `dist/audio-dl.app/Contents/MacOS/audio-dl --no-browser`
    # works (CI smoke test relies on this).
    sys.argv = [arg for arg in sys.argv if not arg.startswith("-psn_")]
    _bootstrap_homebrew_path()
    from audio_dl_ui import main
    main()
```

Test impact: the existing `_app_entry` shim test should be extended with two cases — a `-psn_*` arg is dropped, a `--no-browser` arg is preserved.

### `README-FIRST.txt` template (bundled in zip)

```
audio-dl — macOS

First time?  macOS will say "audio-dl can't be opened because Apple cannot
check it for malicious software." That's expected — this is an unsigned
app for trusted testers.

To open: right-click audio-dl.app, choose Open, then click Open in the
dialog. macOS only asks once.

After that: your browser opens to http://127.0.0.1:8000/. Paste a YouTube
or SoundCloud URL and click Download.

Full instructions: https://github.com/jaterrell/audio-dl/blob/main/INSTALL.md
```

### `INSTALL.md` structure

- **What this is** — one paragraph, unsigned/trusted-tester framing.
- **Download** — link to Releases page, file naming (`audio-dl-vX.Y.Z-macos-arm64.zip` + `SHA256SUMS`), note that Intel users build from source.
- **Verify (optional)** — `shasum -a 256 -c SHA256SUMS` two-line block.
- **Install** — unzip, drag `audio-dl.app` to `/Applications` (optional).
- **First launch** — right-click → Open → Open (primary); `xattr -d com.apple.quarantine` (power-user). One-sentence "why macOS gripes."
- **Using it** — browser opens to 127.0.0.1:8000, paste URL, click Download, click Reveal.
- **Updating** — download new release, replace the app.
- **Troubleshooting** — port 8000 in use; browser doesn't open; missing-ffmpeg dialog (shouldn't happen post-3b but listed for completeness).

### `scripts/build-app.sh` cleanup

Replace the `# TODO (Phase 3b): real signing + notarization` block (~9 lines) with:

```bash
# Distribution is unsigned by design (trusted-tester scope) — Gatekeeper
# on first launch is handled by INSTALL.md / README-FIRST.txt, not by
# signing. See docs/superpowers/specs/2026-05-13-release-pipeline.md.
```

Top-of-file comment is updated to drop the "Phase 3b" framing (this is post-Phase-3b reality, not a TODO).

---

## Testing

| Component | Test approach |
|---|---|
| `scripts/extract-changelog.py` | `TestExtractChangelog` in `test_audio_dl.py`. Parametrized: exact match, `vX.Y.0` → `vX.Y` fallback, missing section fails with stderr, multi-section returns only the requested span, malformed CHANGELOG fails. ~6 tests. |
| `scripts/package-release.sh` | `TestPackageRelease` in `test_audio_dl.py`. Shell-out against a fake `dist/audio-dl.app` directory (marker file inside). Verify staged folder structure, README-FIRST copy, zip + SHA256SUMS output. ~1 test. |
| `_app_entry.py` argv handling | Extend existing `_app_entry` shim test. Verify `-psn_*` dropped, `--no-browser` preserved. |
| `scripts/smoke-test-bundle.sh` | No direct unit tests — too thin a layer of shell over `curl`/`kill`. The script is exercised by every CI release run. |
| The workflow YAML itself | No direct tests. `workflow_dispatch` exists for re-running during development without re-tagging. |

**Pylint:** 10.00/10 stays the bar.

**New test count target:** ~145 (138 after v1.3 + ~7 here).

---

## Failure modes and recovery

| Failure | Workflow outcome | Recovery |
|---|---|---|
| `build-app.sh` exits nonzero (PyInstaller error, missing dep) | Fails before smoke test. No release. Artifacts step doesn't run. | Fix code, push commit, re-tag. `workflow_dispatch` available to re-run on the existing tag. |
| Smoke test times out or returns non-200 | Fails. No release. Artifacts step doesn't run (after smoke). | Same as above. Smoke test stderr is in the workflow log. |
| `extract-changelog.py` finds no matching section | Fails before publish. No release. | Add the CHANGELOG section, push, re-tag (or `workflow_dispatch`). |
| `gh release create` fails (network, conflict) | Release missing or partial. Build artifacts still uploaded to the workflow run. | If partially created, `gh release delete vX.Y.Z --yes`. Re-run via `workflow_dispatch`. |
| Tag pushed without a CHANGELOG section | Same as the extract-changelog case. | Same as above. |

**Idempotency:** `gh release create` is *not* idempotent (rejects duplicate releases for an existing tag). `workflow_dispatch` re-runs on a tag that already has a release require the old release be deleted first. Documented; auto-cleanup not built.

---

## Open questions / risks

- **GitHub Actions macos-14 runner availability and queue time.** macos-14 (arm64) runners are GA but can have longer queue times than Linux. If queue depth becomes a release-day pain point, fallback is to use `macos-13` (x86_64) and accept Rosetta penalties for the build — but that contradicts the arm64-only decision. Mitigation: not a code change; live with it.
- **CI-built bundle vs Joe-built bundle drift.** The CI runner is a fresh-every-time environment; Joe's local Mac has whatever pip resolved last. yt-dlp is fast-moving. A CI build on the same SHA may include a newer yt-dlp than Joe's local build. Mitigation: this is by design (releases ride pip resolution). If it ever burns us, add a `requirements-release.txt` lock file.
- **`workflow_dispatch` input mismatch with the workflow's `$TAG` env var.** The env expression `${{ github.event_name == 'workflow_dispatch' && inputs.tag || github.ref_name }}` is fine for both triggers, but copy-paste hazards apply if anyone edits it. Mitigation: small enough to eyeball; the YAML linter in `gh actions-runner` catches structural errors.
- **CHANGELOG section detection sensitivity.** The regex requires `## vX.Y` at line start with whitespace or EOL after. A typo like `##v1.4` (no space) silently misses. Mitigation: extract-changelog's failure mode is loud (workflow fails, no release), so a typo is caught the first time it's used in anger. We don't add fuzzy matching — strict is correct.

---

## Acceptance criteria

- [ ] Tag `v1.4.0` pushed to internal + mirrored to public produces a fully populated v1.4.0 release on `https://github.com/jaterrell/audio-dl/releases` containing `audio-dl-v1.4.0-macos-arm64.zip` (with `audio-dl.app` + `README-FIRST.txt` inside), `SHA256SUMS`, and notes matching the `## v1.4` section of `CHANGELOG.md`.
- [ ] Downloading the zip on a fresh trusted-tester Mac, following `README-FIRST.txt`, results in the .app launching the web UI on first try (right-click → Open path).
- [ ] CI smoke test catches a deliberately broken bundle (e.g., uvicorn binding disabled) — workflow fails, no release.
- [ ] A tag pushed without a matching CHANGELOG section fails the workflow loudly.
- [ ] `workflow_dispatch` can re-run a release on an existing tag (after manual `gh release delete`) without retagging.
- [ ] `_app_entry.py` preserves `--no-browser` argv (smoke test passes); still strips `-psn_*` (existing behavior).
- [ ] `pytest` passes (existing + ~7 new). Pylint 10.00/10.
- [ ] `INSTALL.md`, README "Installing the .app" subsection, and `README-FIRST.txt` template all consistent on the right-click → Open instructions.
- [ ] Dead Developer-ID TODO block removed from `scripts/build-app.sh`.
