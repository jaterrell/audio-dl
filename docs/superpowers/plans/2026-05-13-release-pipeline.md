# v1.4 Release Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an automated macOS .app release pipeline (Phase 3c + Phase 4) — tag push to the public repo triggers a smoke-tested arm64 build that lands on GitHub Releases with auto-extracted CHANGELOG notes, plus distribution-UX polish (INSTALL.md, bundled README-FIRST, README pointer) so non-technical testers get past Gatekeeper on first launch.

**Architecture:** New `.github/workflows/release.yml` on macos-14, gated to the public repo, calling four new support scripts (`extract_changelog.py`, `package-release.sh`, `smoke-test-bundle.sh`, plus the existing `build-app.sh` with dead Developer-ID TODOs removed). The smoke test boots the bundle and polls `127.0.0.1:8000` before publish — requires `_app_entry.py` to be refactored to pass through `--no-browser`. Build artifacts are uploaded to the workflow run *before* `gh release create` so failures still leave a downloadable build.

**Tech Stack:** GitHub Actions (macos-14 runner), Python 3.12, PyInstaller, `gh` CLI, `imageio-ffmpeg`, pytest + monkeypatch, pylint 10/10 bar.

**Spec:** [docs/superpowers/specs/2026-05-13-release-pipeline.md](../specs/2026-05-13-release-pipeline.md)

---

## Task 1: `_app_entry.py` — selective `-psn_*` argv stripping

**Why first:** every other task that touches the workflow depends on the smoke test being able to launch the bundle with `--no-browser`. The current `_app_entry._main()` clears all argv (`sys.argv = sys.argv[:1]`), so the flag would be eaten. This is also the smallest TDD-able change in the plan.

**Files:**
- Modify: `_app_entry.py:49-60` (`_main` function body)
- Modify: `test_audio_dl.py:659-672` (rename + retarget `test_strips_argv_before_delegating`)
- Modify: `test_audio_dl.py:673` (add a new test after the renamed one, before `TestAppEntryHomebrewPathBootstrap`)

- [ ] **Step 1: Rewrite the existing test to assert the new behavior**

Open `test_audio_dl.py` and replace the entire `test_strips_argv_before_delegating` method (lines 659-672) with:

```python
    def test_strips_psn_argv_preserves_other_flags(self, monkeypatch):
        """_main() drops Finder-injected -psn_* argv but preserves real flags
        like --no-browser so the CI smoke test can boot the bundle headless."""
        import sys
        import importlib
        mod = importlib.import_module("_app_entry")
        captured: dict[str, list[str]] = {}

        def fake_main():
            captured["argv"] = list(sys.argv)

        monkeypatch.setattr("audio_dl_ui.main", fake_main)
        monkeypatch.setattr(
            sys, "argv", ["audio-dl", "-psn_0_12345", "--no-browser"]
        )
        mod._main()
        assert captured["argv"] == ["audio-dl", "--no-browser"]
```

- [ ] **Step 2: Add a new test for the pure-Finder-launch case**

Add this method immediately after `test_strips_psn_argv_preserves_other_flags`, still inside `class TestAppEntry`:

```python
    def test_strips_psn_argv_when_no_other_flags(self, monkeypatch):
        """A Finder launch with only -psn_* args leaves just argv[0]."""
        import sys
        import importlib
        mod = importlib.import_module("_app_entry")
        captured: dict[str, list[str]] = {}

        def fake_main():
            captured["argv"] = list(sys.argv)

        monkeypatch.setattr("audio_dl_ui.main", fake_main)
        monkeypatch.setattr(sys, "argv", ["audio-dl", "-psn_0_98765"])
        mod._main()
        assert captured["argv"] == ["audio-dl"]
```

- [ ] **Step 3: Run the tests — expect FAIL on the rewritten one**

Run: `pytest test_audio_dl.py::TestAppEntry -v`

Expected:
- `test_imports_without_side_effects` PASS (untouched)
- `test_strips_psn_argv_preserves_other_flags` **FAIL** — current `_main()` clears all argv, so `captured["argv"]` will be `["audio-dl"]` instead of `["audio-dl", "--no-browser"]`
- `test_strips_psn_argv_when_no_other_flags` PASS (current behavior matches by coincidence — clearing all is a superset of dropping `-psn_*`)

- [ ] **Step 4: Update `_app_entry._main()` to selective stripping**

Open `_app_entry.py` and replace the body of `_main()` (currently `sys.argv = sys.argv[:1]` on line 51) with:

```python
def _main() -> None:
    """Strip Finder-injected -psn_* argv, bootstrap PATH, delegate to audio_dl_ui.main.

    LaunchServices injects -psn_NNN_MMM (Finder process-serial-number) when
    a .app is launched via double-click. argparse in audio_dl_ui.main would
    reject those. We drop just those args, preserving real flags like
    --no-browser so the bundle can be driven headless (e.g., CI smoke test).
    """
    sys.argv = [arg for arg in sys.argv if not arg.startswith("-psn_")]
    # The PATH bootstrap is only meaningful when launched from a GUI context
    # (PyInstaller frozen bundle, Finder double-click). Running this shim
    # directly from a terminal also calls _bootstrap_homebrew_path, but it's
    # idempotent and any user with these prefixes already on PATH is a no-op.
    _bootstrap_homebrew_path()
    # Import inside the function so ``import _app_entry`` from tests does not
    # pull in fastapi/uvicorn at module-load time.
    from audio_dl_ui import main  # pylint: disable=import-outside-toplevel
    main()
```

Also update the module-level docstring (lines 7-9) to match the new behavior. Replace:

```
1. LaunchServices on older macOS can inject ``-psn_NNN_MMM`` or similar
   Finder process-serial-number flags into argv when an app is launched
   from the GUI. ``audio_dl_ui:main`` uses ``argparse`` and would reject
   them. This shim strips argv before delegating.
```

with:

```
1. LaunchServices on older macOS can inject ``-psn_NNN_MMM`` or similar
   Finder process-serial-number flags into argv when an app is launched
   from the GUI. ``audio_dl_ui:main`` uses ``argparse`` and would reject
   them. This shim strips just those flags, preserving real CLI args
   (e.g., ``--no-browser``) so the bundled binary can be driven headless.
```

- [ ] **Step 5: Run the tests — expect PASS**

Run: `pytest test_audio_dl.py::TestAppEntry -v`

Expected: all three tests PASS.

Then run the full test suite to confirm nothing else broke:

Run: `pytest -q`

Expected: all tests PASS (was 138 before this plan starts; should still be 138 since we replaced one test and added one — net +1 = 139).

- [ ] **Step 6: Lint**

Run: `pylint $(git ls-files '*.py')`

Expected: 10.00/10.

- [ ] **Step 7: Commit**

```bash
git add _app_entry.py test_audio_dl.py
git commit -m "$(cat <<'EOF'
refactor(_app_entry): strip only -psn_* argv, preserve real flags

The smoke test in the upcoming release workflow needs to launch the
bundle with --no-browser; the previous implementation cleared all argv
after argv[0]. Narrow the strip to LaunchServices' -psn_* pattern so
real flags pass through to audio_dl_ui.main's argparse.

Test renamed and retargeted; one new test covers the Finder-only argv
case to keep coverage symmetric.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `scripts/extract_changelog.py` — CHANGELOG section extractor

**Why second:** standalone Python script with no dependencies on other tasks. TDD-friendly. The release workflow needs it.

**Files:**
- Create: `scripts/extract_changelog.py`
- Modify: `test_audio_dl.py` (add `TestExtractChangelog` class at end of file)

**Design note:** The filename uses an underscore (`extract_changelog.py`) not a hyphen, contrary to the spec's "extract-changelog.py" wording, because Python module names with hyphens break direct imports — but we test the script as a subprocess CLI, not by importing it, so the rename is mostly cosmetic. The workflow YAML will invoke it as `python scripts/extract_changelog.py`.

- [ ] **Step 1: Write the failing tests**

At the bottom of `test_audio_dl.py`, after the last existing class, add:

```python
# ---------------------------------------------------------------------------
# scripts/extract_changelog.py — CHANGELOG section extractor for release notes
# ---------------------------------------------------------------------------

import pathlib  # noqa: E402  (intentional position; tests below use it)
import subprocess  # noqa: E402

_REPO_ROOT = pathlib.Path(__file__).parent
_EXTRACT_SCRIPT = _REPO_ROOT / "scripts" / "extract_changelog.py"


class TestExtractChangelog:
    CHANGELOG_FIXTURE = """# Changelog

## v1.4 — Automated macOS release pipeline (2026-05-14)

Pipeline section body.

Multiple lines of notes.

## v1.3 — SSE per-subscriber broadcast (2026-05-13)

Old SSE section body.

## v1.2.1 — codex review-driven patch (2026-05-12)

Older patch notes.
"""

    def _run(self, tag: str, changelog_content: str, tmp_path):
        (tmp_path / "CHANGELOG.md").write_text(changelog_content)
        return subprocess.run(
            ["python", str(_EXTRACT_SCRIPT), tag],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_exact_match_returns_section_body(self, tmp_path):
        r = self._run("v1.4", self.CHANGELOG_FIXTURE, tmp_path)
        assert r.returncode == 0, r.stderr
        assert "Pipeline section body." in r.stdout
        assert "Multiple lines of notes." in r.stdout
        assert "Old SSE section body." not in r.stdout

    def test_header_line_itself_is_stripped(self, tmp_path):
        r = self._run("v1.4", self.CHANGELOG_FIXTURE, tmp_path)
        assert r.returncode == 0
        assert "## v1.4" not in r.stdout

    def test_v_x_y_zero_falls_back_to_v_x_y(self, tmp_path):
        r = self._run("v1.4.0", self.CHANGELOG_FIXTURE, tmp_path)
        assert r.returncode == 0, r.stderr
        assert "Pipeline section body." in r.stdout

    def test_patch_version_exact_match(self, tmp_path):
        r = self._run("v1.2.1", self.CHANGELOG_FIXTURE, tmp_path)
        assert r.returncode == 0, r.stderr
        assert "Older patch notes." in r.stdout
        assert "Pipeline section body." not in r.stdout
        assert "Old SSE section body." not in r.stdout

    def test_no_match_exits_nonzero(self, tmp_path):
        r = self._run("v9.9.9", self.CHANGELOG_FIXTURE, tmp_path)
        assert r.returncode != 0
        assert "v9.9.9" in r.stderr

    def test_empty_changelog_exits_nonzero(self, tmp_path):
        r = self._run("v1.0", "", tmp_path)
        assert r.returncode != 0
```

- [ ] **Step 2: Run the tests — expect FAIL**

Run: `pytest test_audio_dl.py::TestExtractChangelog -v`

Expected: all 6 tests **FAIL** because `scripts/extract_changelog.py` does not exist yet (subprocess returncode is non-zero with "No such file or directory" or python module error).

- [ ] **Step 3: Create `scripts/extract_changelog.py`**

Write the file with this exact content:

```python
#!/usr/bin/env python3
"""Extract a CHANGELOG.md section for use as GitHub Release notes.

Usage:
    python scripts/extract_changelog.py v1.4.0 > RELEASE_NOTES.md

Reads CHANGELOG.md from cwd. Looks for a header matching "## <tag> ..." at
line start. If the tag is "vX.Y.Z" and no exact match is found, retries
with the trailing ".0" stripped ("vX.Y") to handle the precedent of
tagging minor releases with just two version components.

Prints the section body (header line excluded) to stdout. Exits non-zero
with a stderr message if no matching section is found — failed extraction
must fail the release workflow loudly, never ship empty notes.
"""
from __future__ import annotations

import pathlib
import re
import sys


def extract(tag: str, changelog: str) -> str:
    """Return the body of the ## <tag> section, header line excluded.

    Tries the literal tag first; if tag ends in ".0", also tries the
    trimmed form (v1.4.0 -> v1.4). Raises SystemExit on no match.
    """
    candidates = [tag]
    trimmed = tag[:-2] if tag.endswith(".0") else None
    if trimmed and trimmed != tag:
        candidates.append(trimmed)

    for needle in candidates:
        pattern = re.compile(
            rf"^##\s+{re.escape(needle)}(?:\s|$).*?(?=^##\s+v|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(changelog)
        if not match:
            continue
        # Drop the header line itself; keep the body.
        body = match.group(0).split("\n", 1)
        body_text = body[1] if len(body) == 2 else ""
        return body_text.strip() + "\n"

    raise SystemExit(
        f"extract_changelog.py: no ## {tag} section found in CHANGELOG.md "
        f"(tried: {', '.join(candidates)})"
    )


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit(
            "Usage: python scripts/extract_changelog.py <tag>\n"
            "Example: python scripts/extract_changelog.py v1.4.0"
        )
    tag = argv[1]
    changelog_path = pathlib.Path("CHANGELOG.md")
    if not changelog_path.exists():
        raise SystemExit("extract_changelog.py: CHANGELOG.md not found in cwd")
    body = extract(tag, changelog_path.read_text(encoding="utf-8"))
    sys.stdout.write(body)


if __name__ == "__main__":
    main(sys.argv)
```

Make it executable:

```bash
chmod +x scripts/extract_changelog.py
```

- [ ] **Step 4: Run the tests — expect PASS**

Run: `pytest test_audio_dl.py::TestExtractChangelog -v`

Expected: all 6 tests PASS.

- [ ] **Step 5: Lint**

Run: `pylint $(git ls-files '*.py') scripts/extract_changelog.py`

(The script isn't in `git ls-files` yet on first run — pass it explicitly. After commit it'll be picked up by the glob automatically.)

Expected: 10.00/10.

- [ ] **Step 6: Commit**

```bash
git add scripts/extract_changelog.py test_audio_dl.py
git commit -m "$(cat <<'EOF'
feat(release): CHANGELOG section extractor for release notes

scripts/extract_changelog.py reads CHANGELOG.md from cwd, prints the
section body matching a given tag (with vX.Y.0 -> vX.Y fallback for the
minor-release convention), exits non-zero on no match so the release
workflow fails loudly rather than shipping empty notes.

stdlib-only, ~50 lines. Tested via subprocess invocation against a
fixture CHANGELOG.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `README-FIRST.txt` template + `package-release.sh`

**Files:**
- Create: `scripts/release-templates/README-FIRST.txt`
- Create: `scripts/package-release.sh`
- Modify: `test_audio_dl.py` (add `TestPackageRelease` class at end)

- [ ] **Step 1: Create the README-FIRST template**

Create `scripts/release-templates/README-FIRST.txt` with this exact content:

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

- [ ] **Step 2: Write the failing test for package-release.sh**

Add to the bottom of `test_audio_dl.py`:

```python
# ---------------------------------------------------------------------------
# scripts/package-release.sh — stage + zip + checksum the .app for release
# ---------------------------------------------------------------------------

import os  # noqa: E402
import shutil  # noqa: E402

_PACKAGE_SCRIPT = _REPO_ROOT / "scripts" / "package-release.sh"


class TestPackageRelease:
    def test_packages_app_with_readme_first_and_checksum(self, tmp_path):
        """End-to-end: given a fake dist/audio-dl.app and the README-FIRST
        template, the script stages, zips, and SHA256-sums the release."""
        # Fake .app directory tree (just enough to be cp'd as a real .app).
        app_dir = tmp_path / "dist" / "audio-dl.app"
        (app_dir / "Contents").mkdir(parents=True)
        (app_dir / "Contents" / "marker").write_text("fake app contents")

        # Copy the actual README-FIRST template into the tmp tree.
        templates_dir = tmp_path / "scripts" / "release-templates"
        templates_dir.mkdir(parents=True)
        shutil.copy(
            _REPO_ROOT / "scripts" / "release-templates" / "README-FIRST.txt",
            templates_dir / "README-FIRST.txt",
        )

        # Copy the actual package-release.sh script.
        scripts_dir = tmp_path / "scripts"
        target_script = scripts_dir / "package-release.sh"
        shutil.copy(_PACKAGE_SCRIPT, target_script)
        os.chmod(target_script, 0o755)

        r = subprocess.run(
            ["bash", str(target_script), "v1.4.0"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"

        # Staged directory contains the app + README-FIRST.
        stage = tmp_path / "dist" / "release" / "audio-dl-v1.4.0-macos-arm64"
        assert (stage / "audio-dl.app" / "Contents" / "marker").exists()
        assert (stage / "README-FIRST.txt").exists()

        # Zip and checksum files exist with the expected names.
        zip_path = tmp_path / "dist" / "release" / "audio-dl-v1.4.0-macos-arm64.zip"
        assert zip_path.exists()
        sha_path = tmp_path / "dist" / "release" / "SHA256SUMS"
        assert sha_path.exists()
        # SHA256SUMS references the zip by name.
        assert "audio-dl-v1.4.0-macos-arm64.zip" in sha_path.read_text()
```

- [ ] **Step 3: Run the test — expect FAIL**

Run: `pytest test_audio_dl.py::TestPackageRelease -v`

Expected: FAIL — `scripts/package-release.sh` does not exist (the copy in the test will raise FileNotFoundError, which becomes a test error).

- [ ] **Step 4: Create `scripts/package-release.sh`**

Write the file with this exact content:

```bash
#!/usr/bin/env bash
# Stage the built .app, bundle a first-launch README, zip, and checksum.
# Invoked by .github/workflows/release.yml after build-app.sh + smoke test.
#
# Usage:
#   scripts/package-release.sh v1.4.0
#
# Inputs:
#   dist/audio-dl.app                         # produced by build-app.sh
#   scripts/release-templates/README-FIRST.txt
#
# Outputs (under dist/release/):
#   audio-dl-vX.Y.Z-macos-arm64/               # staging dir
#     audio-dl.app/
#     README-FIRST.txt
#   audio-dl-vX.Y.Z-macos-arm64.zip
#   SHA256SUMS                                 # checksum of the zip only
#
# Idempotent: wipes dist/release/ on entry so re-runs don't accumulate cruft.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <tag> (e.g., v1.4.0)" >&2
    exit 2
fi

TAG="$1"
STAGE_NAME="audio-dl-${TAG}-macos-arm64"
STAGE="dist/release/${STAGE_NAME}"

if [[ ! -d "dist/audio-dl.app" ]]; then
    echo "ERROR: dist/audio-dl.app not found — run scripts/build-app.sh first." >&2
    exit 1
fi

TEMPLATE="scripts/release-templates/README-FIRST.txt"
if [[ ! -f "$TEMPLATE" ]]; then
    echo "ERROR: ${TEMPLATE} missing." >&2
    exit 1
fi

rm -rf dist/release
mkdir -p "$STAGE"
cp -R dist/audio-dl.app "$STAGE/"
cp "$TEMPLATE" "$STAGE/README-FIRST.txt"

cd dist/release
zip -qr "${STAGE_NAME}.zip" "$STAGE_NAME"
shasum -a 256 "${STAGE_NAME}.zip" > SHA256SUMS

echo "Packaged: dist/release/${STAGE_NAME}.zip"
echo "Checksum: dist/release/SHA256SUMS"
```

Make executable:

```bash
chmod +x scripts/package-release.sh
```

- [ ] **Step 5: Run the test — expect PASS**

Run: `pytest test_audio_dl.py::TestPackageRelease -v`

Expected: PASS.

- [ ] **Step 6: Run full suite + lint**

Run: `pytest -q`
Expected: all PASS (test count now ~141 = 139 + 6 extract_changelog + 1 package-release - some double-counting). The exact number isn't critical; just no failures.

Run: `pylint $(git ls-files '*.py') scripts/extract_changelog.py`
Expected: 10.00/10.

- [ ] **Step 7: Commit**

```bash
git add scripts/release-templates/README-FIRST.txt scripts/package-release.sh test_audio_dl.py
git commit -m "$(cat <<'EOF'
feat(release): package-release.sh + bundled README-FIRST.txt template

Stages dist/audio-dl.app into a versioned directory alongside a static
README-FIRST.txt that explains the right-click→Open Gatekeeper workaround
to first-time testers, zips the directory, and emits a SHA256SUMS file.

The README-FIRST lives in scripts/release-templates/ so it's source-
controlled but easy to find; package-release.sh copies it into every
staged release. End-to-end tested with a fake .app fixture.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `scripts/smoke-test-bundle.sh`

**Why now:** depends on Task 1 (argv pass-through). Plain shell, no unit tests — exercised by the CI workflow on every release.

**Files:**
- Create: `scripts/smoke-test-bundle.sh`

- [ ] **Step 1: Create the smoke test script**

Write `scripts/smoke-test-bundle.sh` with this exact content:

```bash
#!/usr/bin/env bash
# Smoke-test the built .app by launching it headless and verifying the
# embedded uvicorn binds on 127.0.0.1:8000 within a budget. Catches the
# silent failure mode "bundle launches and ad-hoc-signs cleanly but won't
# serve HTTP" before the release workflow uploads it.
#
# Invoked by .github/workflows/release.yml between build-app.sh and
# package-release.sh.
#
# Prerequisite: _app_entry.py preserves --no-browser argv (Phase 4 refactor).

set -euo pipefail

BIN="dist/audio-dl.app/Contents/MacOS/audio-dl"
if [[ ! -x "$BIN" ]]; then
    echo "ERROR: ${BIN} not found or not executable." >&2
    exit 1
fi

LOG="$(mktemp -t audio-dl-smoke.XXXXXX)"
trap 'rm -f "$LOG"' EXIT

echo "Launching bundle headless: $BIN --no-browser"
"$BIN" --no-browser >"$LOG" 2>&1 &
PID=$!

# Ensure we kill the bundle no matter how we exit.
cleanup() {
    if kill -0 "$PID" 2>/dev/null; then
        kill -TERM "$PID" 2>/dev/null || true
        # Give it 5s to shut down cleanly, then escalate.
        for _ in 1 2 3 4 5; do
            if ! kill -0 "$PID" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        kill -KILL "$PID" 2>/dev/null || true
    fi
    rm -f "$LOG"
}
trap cleanup EXIT

# Poll for HTTP 200 on the UI root for up to 30s.
for i in $(seq 1 30); do
    if curl -fsS -o /dev/null http://127.0.0.1:8000/; then
        echo "Smoke test PASSED (uvicorn bound on :8000 within ${i}s)."
        exit 0
    fi
    sleep 1
done

echo "Smoke test FAILED: bundle did not respond on :8000 within 30s." >&2
echo "--- last 50 lines of bundle stderr ---" >&2
tail -n 50 "$LOG" >&2 || true
exit 1
```

Make executable:

```bash
chmod +x scripts/smoke-test-bundle.sh
```

- [ ] **Step 2: Local smoke check (optional but recommended)**

If you have time and a built bundle from a previous `scripts/build-app.sh` run, sanity-check the script:

```bash
scripts/build-app.sh   # only if dist/audio-dl.app doesn't exist
scripts/smoke-test-bundle.sh
```

Expected: "Smoke test PASSED (uvicorn bound on :8000 within Ns)." If port 8000 is already in use on your dev machine, kill the offender first or skip this step — CI runners always start clean.

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke-test-bundle.sh
git commit -m "$(cat <<'EOF'
feat(release): smoke-test-bundle.sh — verify embedded uvicorn binds

Launches dist/audio-dl.app/Contents/MacOS/audio-dl with --no-browser,
polls 127.0.0.1:8000 for HTTP 200 with a 30s budget, kills the
subprocess cleanly. Failure exits non-zero with the last 50 lines of
the bundle's stderr, failing the release workflow before upload.

Catches "bundle launches, ad-hoc-signs cleanly, but uvicorn doesn't
actually bind" — the silent failure that would land in users' hands
otherwise.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `scripts/build-app.sh` — drop dead Developer-ID TODO block

**Files:**
- Modify: `scripts/build-app.sh:56-64` (delete the TODO block, replace with one-line comment)
- Modify: `scripts/build-app.sh:1-18` (clean up top-of-file framing — Phase 3b is shipped, not TODO)

- [ ] **Step 1: Delete the Developer-ID TODO block**

Open `scripts/build-app.sh` and find the block starting at line 56:

```bash
# TODO (Phase 3b): real signing + notarization when Joe's Developer ID is set up:
#   codesign --force --deep --options runtime \
#            --sign "Developer ID Application: <Joe Terrell>" \
#            --entitlements scripts/entitlements.plist \
#            dist/audio-dl.app
#   ditto -c -k --keepParent dist/audio-dl.app dist/audio-dl.zip
#   xcrun notarytool submit dist/audio-dl.zip \
#       --keychain-profile audio-dl-notary --wait
#   xcrun stapler staple dist/audio-dl.app
```

Replace the entire block (lines ~56-64) with:

```bash
# Distribution is unsigned by design (trusted-tester scope) — Gatekeeper
# on first launch is handled by INSTALL.md / README-FIRST.txt, not by
# signing. See docs/superpowers/specs/2026-05-13-release-pipeline.md.
```

- [ ] **Step 2: Update the top-of-file framing**

The current header (lines 1-18) describes Phase 3b as in-progress and references "Distribution-grade Developer-ID signing + notarization remains a TODO block below." Update that paragraph to reflect that signing has been explicitly deferred (out of scope, not pending).

Replace lines 1-18 with:

```bash
#!/usr/bin/env bash
# Build the macOS .app bundle for audio-dl.
#
# Ships ffmpeg embedded via imageio-ffmpeg (Phase 3b, v1.3) so the .app
# doesn't require `brew install ffmpeg`. Bundle size is ~95 MB.
#
# Distribution is unsigned by design — see
# docs/superpowers/specs/2026-05-13-release-pipeline.md. First-launch
# Gatekeeper friction is handled by INSTALL.md and the bundled
# README-FIRST.txt that ships inside every release zip.
#
# Prereqs (do once per dev machine):
#   python -m pip install -e '.[ui,app]'
#   python -m pip install pyinstaller
#
# Usage:
#   scripts/build-app.sh
```

- [ ] **Step 3: Verify the script still parses**

Run: `bash -n scripts/build-app.sh`

Expected: no output (means syntax-OK).

- [ ] **Step 4: Commit**

```bash
git add scripts/build-app.sh
git commit -m "$(cat <<'EOF'
chore(build): drop dead Developer-ID TODO block from build-app.sh

The v1.4 release pipeline spec made "stay unsigned" an explicit
non-goal. The Developer-ID/notarization TODO block in the build
script was load-bearing only as a reminder that signing was deferred,
not declined. Replace with a one-line pointer to the spec, and clean
up the top-of-file framing to match.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `INSTALL.md` + `README.md` "Installing the .app" subsection

**Files:**
- Create: `INSTALL.md`
- Modify: `README.md` (add "Installing the .app" subsection inside the existing macOS `.app` section)

- [ ] **Step 1: Create `INSTALL.md` at repo root**

Write the file with this exact content:

```markdown
# Installing the audio-dl macOS .app

audio-dl ships as a macOS `.app` bundle for Apple Silicon Macs. It's
**unsigned** — distributed for trusted testers, not through the App Store
or the Apple notarization pipeline. macOS Gatekeeper will block the first
launch by default; the steps below get past it once, after which the app
opens normally.

If you're on an Intel Mac or want to compile from source, see the
"macOS `.app` bundle" section of the README for the build-from-source
path.

## Download

1. Go to <https://github.com/jaterrell/audio-dl/releases>.
2. From the latest release, grab:
   - `audio-dl-vX.Y.Z-macos-arm64.zip` — the bundle.
   - `SHA256SUMS` — (optional) the integrity checksum.

## Verify the download (optional)

In Terminal, in the directory you downloaded both files into:

```
shasum -a 256 -c SHA256SUMS
```

You should see `audio-dl-vX.Y.Z-macos-arm64.zip: OK`. If you see `FAILED`,
the file was corrupted in transit — delete and re-download.

## Install

1. Double-click the zip to unpack it. You'll get a folder containing
   `audio-dl.app` and `README-FIRST.txt`.
2. (Optional) drag `audio-dl.app` to your `/Applications` folder. The app
   also runs fine from `~/Downloads` or anywhere else.

## First launch — getting past Gatekeeper

macOS will block the first launch with a dialog like:

> *"audio-dl" can't be opened because Apple cannot check it for malicious
> software.*

This is expected — the app is unsigned. Two ways to bypass it:

**Right-click → Open (recommended).** In Finder, right-click (or
two-finger click) `audio-dl.app` and choose **Open**. macOS shows a
slightly different dialog with an **Open** button. Click it. macOS only
asks once per app — after that, double-clicking works normally.

**Power-user shortcut.** In Terminal:

```
xattr -d com.apple.quarantine /path/to/audio-dl.app
```

Replace `/path/to/audio-dl.app` with wherever you put the app. This
removes the "downloaded from the internet" marker that triggers
Gatekeeper.

## Using audio-dl

Once running:

- Your browser opens to <http://127.0.0.1:8000/>.
- Paste one or more URLs (YouTube, SoundCloud, etc.) into the textarea.
- Pick a format (mp3, m4a, flac, etc.) and click **Download**.
- Click **Reveal** next to a finished download to open it in Finder.

Quitting the app from the Dock (right-click → Quit, or ⌘Q while it's
focused) stops the embedded web server.

## Updating

When a new release comes out:

1. Quit the running app.
2. Download the new zip from the Releases page.
3. Replace your existing `audio-dl.app` with the new one. Existing
   downloads in your output directory are untouched.

## Troubleshooting

**"Port 8000 already in use."** Something else on your Mac is bound to
8000. Quit it, or relaunch audio-dl with a different port: in Terminal,
run `/path/to/audio-dl.app/Contents/MacOS/audio-dl --port 9000`.

**Browser doesn't open automatically.** Open one yourself and navigate
to <http://127.0.0.1:8000/>.

**"ffmpeg not found" dialog.** This shouldn't happen — ffmpeg is bundled
inside the `.app` as of v1.3. If you see it, file an issue at
<https://github.com/jaterrell/audio-dl/issues> with the macOS version
and the output of `dist/audio-dl.app/Contents/MacOS/audio-dl --no-browser`
from Terminal.
```

- [ ] **Step 2: Add "Installing the .app" subsection to README.md**

Open `README.md`. Find the section that documents the macOS `.app` bundle
(it'll be the section titled "macOS `.app` bundle" or similar, matching
the CLAUDE.md layout). Inside that section, after any existing intro
paragraph and the build-from-source instructions, add a new subsection:

```markdown
### Installing a release build

If you don't want to build the bundle yourself, download a prebuilt
release from the [Releases page](https://github.com/jaterrell/audio-dl/releases).
Each release ships an Apple Silicon (`arm64`) zip with the `.app` and a
first-launch instructions file inside.

Full step-by-step including the Gatekeeper workaround is in
[INSTALL.md](INSTALL.md).

Intel Mac users: build from source via the instructions above. There is
no x86_64 prebuilt bundle yet.
```

Place this subsection *after* the existing `scripts/build-app.sh` block so the build-from-source path remains the primary documentation for developers, and the new subsection is positioned as the user-facing alternative.

- [ ] **Step 3: Verify links**

Run: `grep -l "INSTALL.md\|/releases" README.md INSTALL.md`

Expected: both files appear in the output (`INSTALL.md` references `/releases`; `README.md` references `INSTALL.md`).

- [ ] **Step 4: Commit**

```bash
git add INSTALL.md README.md
git commit -m "$(cat <<'EOF'
docs: INSTALL.md + README "Installing a release build" subsection

INSTALL.md is the full first-launch walkthrough for non-technical
testers: download, verify SHA256SUMS, unzip, right-click→Open, use the
UI, update, troubleshoot. Written for someone who's never opened an
unsigned .app before.

README gets a short pointer subsection inside the existing macOS .app
section — build-from-source remains the primary developer doc, the
new subsection is the user-facing "I just want to download it" path.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `CLAUDE.md` — fix `_app_entry.py` description + add release pipeline notes

**Files:**
- Modify: `CLAUDE.md` (the `_app_entry.py` Layout section; the macOS `.app` section; possibly the Conventions section)

Note: the `_app_entry.py` description in CLAUDE.md already says "Strips Finder-injected argv (`-psn_NNN_MMM`)" — which actually matches the *new* behavior we just shipped in Task 1. Before Task 1, the code cleared all argv; the CLAUDE.md description was aspirational. After Task 1 it's accurate. **Don't change that line.** What needs updating:

1. The release pipeline now exists and the macOS section should reference it.
2. A new Convention line about the release flow.
3. The Layout section gets a new entry for `.github/workflows/release.yml` if Layout currently lists workflow files (check first).

- [ ] **Step 1: Read CLAUDE.md to find the macOS `.app` bundle section**

Run: `grep -n "macOS\|build-app\|release" CLAUDE.md`

Note the line numbers for:
- The "macOS `.app` bundle" subsection inside `## Run`.
- The Conventions section (probably near the bottom).

- [ ] **Step 2: Add a "Releases" sub-section in the macOS `.app` section**

After the existing block that documents `scripts/build-app.sh` and ends with the reference to `2026-05-13-app-bundle.md`, add this paragraph:

```markdown
**Released bundles** ship on the public repo's [Releases page](https://github.com/jaterrell/audio-dl/releases),
built by `.github/workflows/release.yml` on every `v*` tag push to public
(gated to `jaterrell/audio-dl` so the internal mirror doesn't double-run).
Each release contains an `audio-dl-vX.Y.Z-macos-arm64.zip` (with the .app
and a bundled `README-FIRST.txt`) plus `SHA256SUMS`. Release notes are
auto-extracted from the matching `## v1.X` section of `CHANGELOG.md` by
`scripts/extract_changelog.py`. See
[docs/superpowers/specs/2026-05-13-release-pipeline.md](docs/superpowers/specs/2026-05-13-release-pipeline.md).
```

- [ ] **Step 3: Add a Convention about the release flow**

Append a new bullet to the Conventions section, near the existing "Two-repo model" bullet (since the release flow rides on top of the two-repo mirror):

```markdown
- Release flow: bump `__version__` (audio_dl.py) + `version`
  (pyproject.toml) + add `## v1.X — …` section to CHANGELOG.md, commit,
  tag `v1.X`, push to internal, run `scripts/publish.sh`. The tag mirrors
  to public; the public repo's `release.yml` workflow builds the arm64
  .app, smoke-tests it on the runner, uploads the zip + SHA256SUMS to a
  new GitHub Release, and pulls the release body from the matching
  CHANGELOG section. If the workflow fails before the release-create
  step, the built zip is still downloadable from the workflow's Artifacts
  panel — manual recovery is `gh release delete vX.Y.Z` then
  `workflow_dispatch` to re-run.
```

- [ ] **Step 4: Add `release.yml` to the file inventory (if Layout lists workflows)**

Check whether the Layout section's file inventory currently lists `.github/workflows/*.yml`. Run:

```bash
grep -n "\.github\|workflows" CLAUDE.md
```

If the workflows ARE listed in Layout, add a line for `release.yml`. If they aren't (current state — Layout focuses on `.py` files), skip this step. (The CHANGELOG mentions tests.yml and pylint.yml in the Test/Lint section but not as Layout entries — this is consistent. Skip.)

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(CLAUDE.md): document v1.4 release pipeline

Adds the "Released bundles" paragraph to the macOS .app section pointing
at .github/workflows/release.yml and the new spec, and a Convention
bullet describing the bump-tag-publish flow plus the failure-recovery
path via Artifacts panel + workflow_dispatch.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `.github/workflows/release.yml`

**Why now:** depends on all support scripts existing (Tasks 1-5) and all docs being in place (Tasks 6-7).

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create the workflow YAML**

Write `.github/workflows/release.yml` with this exact content:

```yaml
name: Release

on:
  push:
    tags: ['v*']
  workflow_dispatch:
    inputs:
      tag:
        description: 'Tag to release (e.g., v1.4.0). Must already exist.'
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
      - name: Checkout (tag)
        uses: actions/checkout@v4
        with:
          ref: ${{ env.TAG }}

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install build dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e '.[ui,app]'
          python -m pip install pyinstaller

      - name: Build .app bundle
        run: scripts/build-app.sh

      - name: Smoke-test the bundle
        run: scripts/smoke-test-bundle.sh

      - name: Package release artifacts
        run: scripts/package-release.sh "$TAG"

      - name: Extract release notes from CHANGELOG
        run: python scripts/extract_changelog.py "$TAG" > RELEASE_NOTES.md

      - name: Upload workflow artifact (pre-publish safety net)
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

- [ ] **Step 2: Validate the YAML locally**

If you have `yamllint` installed, run:

```bash
yamllint .github/workflows/release.yml
```

Otherwise, do a quick visual scan: indentation is consistent (2 spaces), every `:` has either a value or a newline, the `${{ ... }}` expressions use `||` not `or`.

If the GitHub CLI is installed and authenticated:

```bash
gh workflow view --repo jaterrell/audio-dl release.yml || true
```

(This will fail until the workflow is pushed to public — that's expected. We're just checking the YAML parses; failure here doesn't block.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "$(cat <<'EOF'
ci(release): macos-14 release workflow gated to public repo

Tag push to jaterrell/audio-dl (public) triggers: build .app on
macos-14, smoke-test 127.0.0.1:8000 within 30s, package into
audio-dl-vX.Y.Z-macos-arm64.zip with bundled README-FIRST + SHA256SUMS,
extract release notes from the matching CHANGELOG section, upload the
zip as a workflow artifact, then gh release create.

if: github.repository == 'jaterrell/audio-dl' so the same file mirrored
to internal stays inert. workflow_dispatch added for re-running a
failed release on an existing tag.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Version bumps + `CHANGELOG.md` v1.4 section

**Why last (before manual verification):** every other commit on this branch will be incorporated into v1.4. The CHANGELOG section is what the workflow will extract, so it has to land before the tag.

**Files:**
- Modify: `audio_dl.py` (line containing `__version__ = "..."`)
- Modify: `pyproject.toml` (line containing `version = "..."`)
- Modify: `CHANGELOG.md` (prepend a new `## v1.4 — ...` section above the existing `## v1.3`)

- [ ] **Step 1: Bump `audio_dl.py.__version__`**

Find the line in `audio_dl.py` matching `__version__ = "1.3"` (or whatever the current value is). Run:

```bash
grep -n "^__version__" audio_dl.py
```

Edit that line to:

```python
__version__ = "1.4"
```

(Bump the minor version — the precedent from v1.3 is two-component tags for minor releases.)

- [ ] **Step 2: Bump `pyproject.toml` version**

Find the `version = "..."` line in `pyproject.toml`. Run:

```bash
grep -n "^version" pyproject.toml
```

Edit that line to:

```toml
version = "1.4"
```

- [ ] **Step 3: Verify the versions match**

Run:

```bash
python -c "import re, pathlib; \
  py = re.search(r'__version__\s*=\s*[\"\\']([^\"\\']+)', pathlib.Path('audio_dl.py').read_text()).group(1); \
  toml = re.search(r'^version\s*=\s*[\"\\']([^\"\\']+)', pathlib.Path('pyproject.toml').read_text(), re.M).group(1); \
  assert py == toml == '1.4', f'mismatch: audio_dl.py={py} pyproject.toml={toml}'; \
  print(f'OK: both are {py}')"
```

Expected: `OK: both are 1.4`.

- [ ] **Step 4: Add the CHANGELOG section**

Open `CHANGELOG.md`. Find the existing `## v1.3 — ...` header. Insert this new section **above** it (immediately below the file's title/preamble, above the v1.3 section):

```markdown
## v1.4 — Automated macOS release pipeline (YYYY-MM-DD)

Phase 3c + Phase 4 of the macOS .app roadmap, shipped as one slice:

### Added
- `.github/workflows/release.yml` — tag push to the public repo (gated
  with `if: github.repository == 'jaterrell/audio-dl'`) builds the arm64
  `.app` on a `macos-14` runner, smoke-tests the embedded uvicorn,
  packages a versioned zip alongside `SHA256SUMS`, extracts notes from
  this CHANGELOG, and publishes a GitHub Release. `workflow_dispatch`
  available for re-running a failed release on an existing tag.
- `scripts/extract_changelog.py` — stdlib-only release-notes extractor.
  Looks up the `## <tag>` section, falls back from `vX.Y.0` to `vX.Y`
  when the literal tag doesn't match, exits non-zero on no match so a
  missing CHANGELOG entry fails the workflow loudly.
- `scripts/package-release.sh` — stages the built `.app` with a bundled
  `README-FIRST.txt` (first-launch instructions for Gatekeeper), zips
  the directory, generates SHA256SUMS.
- `scripts/smoke-test-bundle.sh` — boots the bundle headless with
  `--no-browser`, polls `127.0.0.1:8000` for HTTP 200 with a 30s budget,
  fails the workflow if uvicorn can't bind.
- `scripts/release-templates/README-FIRST.txt` — bundled in every
  release zip; explains the right-click → Open Gatekeeper workaround
  next to the binary, not buried in the repo.
- `INSTALL.md` — full first-launch walkthrough for non-technical
  testers. README gets a short pointer subsection.

### Changed
- `_app_entry.py` strips only `-psn_*` argv (Finder process-serial-number
  flags) rather than clearing all argv. Real CLI flags like
  `--no-browser` now pass through to `audio_dl_ui.main`, which is what
  makes the CI smoke test possible.
- `scripts/build-app.sh` — dropped the dead Developer-ID
  signing/notarization `# TODO` block. The project is staying unsigned;
  the workaround (right-click → Open, documented in `INSTALL.md` /
  `README-FIRST.txt`) is the answer, not deferred signing work.

### Decisions pinned (see [spec](docs/superpowers/specs/2026-05-13-release-pipeline.md))
- Unsigned distribution (no Apple Developer Program enrollment).
- arm64 only (Apple Silicon). Intel users build from source.
- Tag-push trigger on the public repo only; internal mirror's same
  workflow file no-ops via the repo guard.
- Release notes auto-extracted from this CHANGELOG; missing section
  fails the workflow before publish.
- Smoke test is the gate: a built-but-unbindable bundle never reaches
  users.
- Build artifacts uploaded to the workflow run *before* `gh release
  create`, so a failed publish still leaves a downloadable zip.

### Test count
- 138 → ~145 (added: 1 for the `_app_entry.py` argv refactor, 6 for
  `TestExtractChangelog`, 1 for `TestPackageRelease`; existing
  `test_strips_argv_before_delegating` renamed and retargeted).
```

Replace `YYYY-MM-DD` in the header with the actual release date when you commit (or leave as `YYYY-MM-DD` and update at tag time — the extractor matches on `## v1.4 ` so the trailing date doesn't affect matching).

- [ ] **Step 5: Smoke-test the CHANGELOG extractor against the real file**

Run:

```bash
python scripts/extract_changelog.py v1.4
```

Expected: prints the body of the new v1.4 section (Phase 3c + Phase 4 description, etc.). Should NOT include the `## v1.4` header line itself, and should stop before `## v1.3`.

Also try the fallback path:

```bash
python scripts/extract_changelog.py v1.4.0
```

Expected: same output (matches via the `.0`-strip fallback).

And the failure path:

```bash
python scripts/extract_changelog.py v9.9.9 && echo "BUG: should have exited nonzero"
```

Expected: prints "extract_changelog.py: no ## v9.9.9 section found in CHANGELOG.md (tried: v9.9.9, v9.9)" to stderr and exits 1. You should NOT see "BUG: ...".

- [ ] **Step 6: Run full tests + lint**

Run: `pytest -q`
Expected: ~145 tests pass. No failures.

Run: `pylint $(git ls-files '*.py')`
Expected: 10.00/10.

- [ ] **Step 7: Commit (version bump + CHANGELOG together — this is the release-prep commit)**

```bash
git add audio_dl.py pyproject.toml CHANGELOG.md
git commit -m "$(cat <<'EOF'
release: v1.4 — automated macOS release pipeline

Bumps __version__ + pyproject.toml to 1.4. CHANGELOG section will be
extracted verbatim by the release workflow on tag push to public.

See docs/superpowers/specs/2026-05-13-release-pipeline.md for the
design and docs/superpowers/plans/2026-05-13-release-pipeline.md for
the implementation breakdown.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Local end-to-end verification (manual)

**Why:** the workflow's first real run is the v1.4 release itself. Before tagging, exercise as much of it as possible locally to catch problems while iteration is cheap.

**No commits in this task** — diagnostic only.

- [ ] **Step 1: Local build**

```bash
rm -rf build dist
scripts/build-app.sh
```

Expected: ends with the "Built: dist/audio-dl.app" message. `ls dist/` shows `audio-dl.app`.

- [ ] **Step 2: Local smoke test**

```bash
scripts/smoke-test-bundle.sh
```

Expected: "Smoke test PASSED (uvicorn bound on :8000 within Ns)." If port 8000 is in use locally, `lsof -ti :8000 | xargs kill` first.

- [ ] **Step 3: Local package**

```bash
scripts/package-release.sh v1.4
```

Expected: ends with "Packaged: dist/release/audio-dl-v1.4-macos-arm64.zip" and "Checksum: dist/release/SHA256SUMS". Verify:

```bash
ls dist/release/
unzip -l dist/release/audio-dl-v1.4-macos-arm64.zip | head -20
shasum -a 256 -c dist/release/SHA256SUMS
```

Expected: the zip contains `audio-dl-v1.4-macos-arm64/audio-dl.app/...` + `audio-dl-v1.4-macos-arm64/README-FIRST.txt`, and `shasum -c` says `audio-dl-v1.4-macos-arm64.zip: OK`.

- [ ] **Step 4: Sanity-check the unzipped bundle**

```bash
mkdir -p /tmp/audio-dl-release-test
cd /tmp/audio-dl-release-test
unzip -q "$OLDPWD/dist/release/audio-dl-v1.4-macos-arm64.zip"
cat audio-dl-v1.4-macos-arm64/README-FIRST.txt
open audio-dl-v1.4-macos-arm64/audio-dl.app
cd "$OLDPWD"
```

Expected: README-FIRST text prints, the .app opens and the browser tab pops to http://127.0.0.1:8000/. Verify a small download (e.g., a short YouTube video) works end-to-end through the UI. Quit the app from the Dock when done.

- [ ] **Step 5: Local CHANGELOG extraction**

```bash
python scripts/extract_changelog.py v1.4 | head -40
```

Expected: prints the v1.4 section body (header line excluded, terminates before v1.3).

- [ ] **Step 6: If anything failed**

Do NOT proceed to tagging. Fix the underlying issue, commit the fix, and re-run from Step 1. The point of the local exercise is to keep CI iteration cycles for genuine CI-specific issues (e.g., GH-Actions environment quirks), not script bugs.

- [ ] **Step 7: When everything passes — tag and push**

```bash
# In the internal repo:
git tag v1.4
git push origin main --tags

# Mirror to public:
scripts/publish.sh
```

The public repo's `release.yml` will fire on the mirrored tag. Watch it in the Actions tab. When it goes green, verify the release page at `https://github.com/jaterrell/audio-dl/releases`.

- [ ] **Step 8: If the GH Actions run fails**

Don't panic. The Artifacts panel of the failed run contains the built zip + SHA256SUMS — you can manually `gh release create` from those if you need to ship today. Then fix the workflow issue, push to a fresh patch tag (v1.4.1) and re-run.

If the failure is in the publish step (e.g., `gh release create` errored), delete the partial release (`gh release delete v1.4 --yes --repo jaterrell/audio-dl`) and trigger `workflow_dispatch` against the existing tag from the public repo's Actions UI.

---

## Self-review

**Spec coverage check:**

| Spec section | Implementation task |
|---|---|
| `_app_entry.py` selective `-psn_*` strip | Task 1 |
| `scripts/extract_changelog.py` + 6 tests | Task 2 |
| `scripts/release-templates/README-FIRST.txt` | Task 3 |
| `scripts/package-release.sh` + 1 test | Task 3 |
| `scripts/smoke-test-bundle.sh` | Task 4 |
| `scripts/build-app.sh` cleanup | Task 5 |
| `INSTALL.md` | Task 6 |
| `README.md` "Installing a release build" subsection | Task 6 |
| `CLAUDE.md` release-pipeline doc | Task 7 |
| `.github/workflows/release.yml` | Task 8 |
| `pyproject.toml` + `audio_dl.py` version bumps | Task 9 |
| `CHANGELOG.md` v1.4 section | Task 9 |
| Failure-mode recovery (artifact upload before publish) | Tasks 8 (impl) + 10 step 8 (verification) |
| Pylint 10.00/10 acceptance criterion | Tasks 1, 2, 3 (each task lints before commit) |
| Smoke test gate before publish | Tasks 4 (impl) + 10 step 2 (local verify) |

All spec sections covered.

**Placeholder scan:** the CHANGELOG `## v1.4 — ... (YYYY-MM-DD)` literal date placeholder is intentional (engineer fills in at commit time, or leaves as-is since the extractor matches on the tag prefix). No other TBDs.

**Type/name consistency check:**
- `extract(tag, changelog)` signature consistent between Task 2 step 3 (impl) and step 1 (tests via subprocess — tests don't import the function, so no API mismatch risk).
- Script filename `extract_changelog.py` (underscore) used consistently in Tasks 2, 8 (workflow), 9, 10. Old hyphenated spelling from the spec text is corrected throughout the plan.
- Release zip naming `audio-dl-${TAG}-macos-arm64.zip` consistent across Tasks 3 (script), 6 (INSTALL.md), 8 (workflow), 9 (CHANGELOG), 10 (local verify).
- Workflow env var `$TAG` consistent in Task 8.
- The `--no-browser` flag is consistent between Tasks 1 (test asserts it survives), 4 (smoke test uses it), 6 (INSTALL.md troubleshooting suggests `--port` as a sibling flag), and audio_dl_ui's existing CLI surface.

**Task count:** 10 tasks. The skill's "bite-sized" guidance with ~5 steps each = ~50 discrete actions. Most are 2-5 minute steps; a few (full local end-to-end verify in Task 10) are longer. Manageable in one focused session or split across two.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-13-release-pipeline.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
