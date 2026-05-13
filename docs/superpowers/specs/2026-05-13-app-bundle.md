# audio-dl `.app` Bundle — design spec (Phase 3a + 3b)

**Status:** Phase 3a shipped (PR #11 → `a227c2f`). Phase 3b in flight on
`feat/phase-3b-embed-ffmpeg`. Codesigning + notarization (Phase 3c) still
pending Joe's Developer ID.
**Date:** 2026-05-13
**Owner:** Joe Terrell
**Target release:** v1.3.0

## Purpose

Ship a buildable macOS `.app` bundle that launches the existing web UI
(`audio_dl_ui`) with no terminal visible. Establishes the build pipeline
and entry-point UX so Phase 3b (codesigning, ffmpeg embedding, distribution)
and Phase 4 (GitHub Actions release builder) have a known-good target.

## Audience for this slice

**A trusted tester with Homebrew and `brew install ffmpeg` on PATH.**

Not:
- A stranger who downloads a zip and expects double-click-to-run (no signing → Gatekeeper blocks; no embedded ffmpeg → first download fails)
- A consumer who's never used a terminal (no embedded ffmpeg → "ffmpeg not found" dialog with install instructions is the best we offer)

The README and CHANGELOG framing must reflect this honestly. **Do not market this as "Phase 3 shipped."** It's Phase 3a — the bundle exists; the consumer story does not.

## Goals (this slice)

- `scripts/build-app.sh` produces `dist/audio-dl.app` on a developer's Mac.
- Double-clicking the `.app` launches the web UI, opens the browser, no terminal window.
- If ffmpeg is missing, a native macOS dialog explains how to install it (no silent fail).
- All existing tests still pass. New tests cover the ffmpeg-missing GUI path and the bundle entry-point's importability.
- Pylint ≥ 9.5.

## Non-goals (deferred to 3c / later)

- **Codesigning + notarization (3c).** Hooks left in `build-app.sh` for Joe's Developer ID + notarytool. Without these, distribution requires `xattr -d com.apple.quarantine audio-dl.app` post-download — documented but not fixed.
- **~~Embedded ffmpeg.~~** **Done in Phase 3b** via `imageio-ffmpeg` (LGPLv2.1+ static binary, BSD-2 wrapper). Bundle grew ~47 MB → ~95 MB. Path resolution lives in `_find_ffmpeg()` and feeds both the dep check and `download_media`. Attribution in `NOTICE.md`; full LGPL text in `LICENSES/ffmpeg-LGPL-2.1.txt`. **Caveat:** imageio-ffmpeg ships only `ffmpeg`, not `ffprobe`. Common audio/video flows work (verified end-to-end with mp3 + mp4 on a stripped `PATH`); advanced yt-dlp extractor paths that invoke ffprobe will fall through to whatever `ffprobe` is on `PATH` and fail if none. Users hitting that should `brew install ffmpeg`. A future phase could add a bundled ffprobe (e.g. via a different packaging) if the demand materializes.
- **Cross-platform bundle.** PyInstaller can target Windows/Linux, but the build script is mac-only and Info.plist is mac-specific. Windows/Linux follow when there's demand.
- **First-run download of yt-dlp updates.** The bundle ships with a pinned yt-dlp; users update by rebuilding. Self-update is its own scope.
- **Universal2 (arm64 + x86_64).** Build script targets the host arch; cross-arch is a Phase 3c/4 concern.

---

## Decisions (pinned)

| Decision | Choice | Reasoning |
|---|---|---|
| **Tool** | **PyInstaller** | Named in the v1.2 spec. Cross-platform path matters for Phase 4. |
| **ffmpeg** | **External (Homebrew)** | Embedding is a real engineering project (license, size, path resolution) — its own slice. Tester audience can run `brew install ffmpeg`. |
| **ffmpeg-missing UX** | **`osascript` dialog** + clean exit | No silent fail when there's no terminal. Dialog text mirrors the existing CLI message. |
| **Gatekeeper** | **Unsigned**, ad-hoc `codesign --sign -` to suppress runtime warnings, leave a `# TODO: Developer ID` block in the build script | Joe's cert isn't here. Build script ready when it is. |
| **Browser launch** | **Reuse `audio_dl_ui:main`** as the entry-point | Already auto-opens the browser, has --no-browser, --port. Don't fork behavior. |
| **Bundle name** | **`audio-dl.app`** (Finder display: `audio-dl`) | Matches CLI, repo, PyPI-planned name, existing brand. |
| **Bundle identifier** | `com.jaterrell.audio-dl` | Reverse-DNS, owner-namespaced. |
| **`LSUIElement`** | **`false`** (regular app, shows in Dock) | Web UI lives in a browser window; killing the `.app` from Dock should stop the server. LSUIElement-true (menubar/agent) is a UX choice for Phase 3b. |
| **Auto-open browser** | **Yes** (existing `audio_dl_ui` default) | Whole point of the bundle is "double-click → page opens". |

---

## Architecture

**Process model.** PyInstaller produces an `.app` bundle whose main executable
is a tiny launcher that boots Python and calls `audio_dl_ui:main`. Standard
PyInstaller console=False mode — no Terminal window.

**Module layout.**

| File | Role |
|---|---|
| `audio_dl.py` | Refactor `check_dependencies` → return a list of error lines, not `sys.exit` directly. CLI keeps its current print+exit behavior via a thin wrapper. |
| `audio_dl_ui.py` | Replace `check_dependencies()` call in `main()` with a GUI-aware path: on missing deps, show macOS dialog (osascript) then exit. |
| `audio-dl.spec` | PyInstaller spec — single-binary launch of `audio_dl_ui:main` via a tiny `_app_entry.py` shim. |
| `_app_entry.py` | 5-line shim: `from audio_dl_ui import main; main()` — gives PyInstaller a clean entrypoint without arg-parsing surprises (calls `main()` with `sys.argv[1:] = []` so the bundle ignores junk argv from `LaunchServices`). |
| `scripts/build-app.sh` | Cleans `build/`, `dist/`, runs PyInstaller, ad-hoc-signs, prints next steps. |

**Why a shim `_app_entry.py`** instead of pointing PyInstaller at `audio_dl_ui:main`? PyInstaller bundles a module's `if __name__ == "__main__"` block by including the module as the script. `audio_dl_ui.py` already has `argparse`. Launching from Finder passes weird argv (e.g. `-psn_0_12345` on older macOS) that argparse would reject. The shim clears `sys.argv` to `[sys.argv[0]]` before calling `main()`.

**Refactor of `check_dependencies`** is the only behavior change in `audio_dl.py`. It returns `list[str]` of human-readable problem lines (empty = all good). Two thin callers:
- `audio_dl.py` CLI path: existing `check_dependencies()` becomes `_check_dependencies_or_exit()` — prints lines and `sys.exit(1)`. CLI behavior unchanged.
- `audio_dl_ui.py` GUI path: new `_check_dependencies_gui()` — calls the pure function, on failure shows osascript dialog and exits.

---

## File changes

| File | Action | Lines |
|---|---|---|
| `audio_dl.py` | Modify (refactor `check_dependencies` to pure-fn + thin exit wrapper) | ~15 net add |
| `audio_dl_ui.py` | Modify (`main()` calls GUI-aware dep check; add `_show_macos_dialog`, `_check_dependencies_gui`) | ~30 net add |
| `_app_entry.py` | Create | ~10 |
| `audio-dl.spec` | Create | ~45 |
| `scripts/build-app.sh` | Create | ~40 |
| `test_audio_dl.py` | Modify (3 tests for new `check_dependencies` pure-fn return shape) | ~25 |
| `test_audio_dl_ui.py` | Modify (2 tests for `_check_dependencies_gui` path) | ~30 |
| `README.md` | Modify (new "macOS .app build" section) | ~25 |
| `CLAUDE.md` | Modify (note bundle artifacts + Phase 3a framing) | ~15 |
| `CHANGELOG.md` | Modify (new `## v1.3.0` section) | ~25 |
| `pyproject.toml` | Modify (bump version, no new runtime deps) | 1 |
| `audio_dl.py` `__version__` | Modify | 1 |

PyInstaller stays out of `pyproject.toml` — it's a build-time tool, like pytest. Document `pip install pyinstaller` in the build script comment + README.

---

## Build flow (`scripts/build-app.sh`)

```
1. Verify dev deps: python ≥ 3.10, pyinstaller installed
2. Clean build/ and dist/
3. Run: pyinstaller audio-dl.spec --noconfirm
4. Ad-hoc sign: codesign --force --deep --sign - dist/audio-dl.app
5. (TODO: when Joe has Developer ID)
   codesign --force --deep --sign "Developer ID Application: …" \
            --options runtime --entitlements entitlements.plist dist/audio-dl.app
   xcrun notarytool submit dist/audio-dl.app.zip --keychain-profile … --wait
   xcrun stapler staple dist/audio-dl.app
6. Print: "Built dist/audio-dl.app — double-click to launch.
          ffmpeg must be on PATH (brew install ffmpeg)."
```

## Testing

Three categories of tests, none of which require running PyInstaller in CI (would balloon CI time and we don't have a clean way to verify "double-click launches"):

1. **`check_dependencies` pure-fn behavior** — empty list when present, populated list when missing (mocked `shutil.which` and `importlib.util.find_spec`).
2. **`_check_dependencies_gui` flow** — when deps OK, returns without calling dialog; when deps missing, calls dialog with expected text and exits non-zero.
3. **`_app_entry.py` importability** — `import _app_entry` succeeds without side effects (i.e., doesn't call `main()` at import time).

PyInstaller spec file parse-ability is verified by running `python audio-dl.spec` doesn't import properly — instead, the build script's CI-equivalent is `python -c "import PyInstaller.utils.misc; PyInstaller.utils.misc.load_py_data_struct('audio-dl.spec')"` (or just compile-check via `python -m py_compile audio-dl.spec`). For this slice, we'll just `py_compile` the spec in a test.

---

## Risks / open questions

- **`audio_dl_ui:main`'s argparse choking on Finder argv.** Mitigated by the shim. Verified by smoke test of `_app_entry`.
- **Browser auto-open misfires** in a bundled context (different working dir, different env). Mitigated by reusing the existing `webbrowser.open` call which is already known good.
- **PyInstaller missing FastAPI hidden imports.** Spec uses
  `collect_submodules("fastapi" / "uvicorn" / "starlette" / "pydantic" /
  "pydantic_core")` plus `collect_data_files("fastapi" / "uvicorn")` so we
  don't have to chase new submodule names across upstream releases.
  Verified by an end-to-end build during this session (bundle launches,
  embedded uvicorn serves the UI on `http://127.0.0.1:8000/`).
- **macOS dialog escaping.** `osascript -e 'display dialog "..."'` is shell-quoted; we use a fixed template, no user input flows in.

---

## Out of scope (explicit non-goals, restated)

- Codesigning / notarization
- Embedded ffmpeg
- Cross-platform builds
- GitHub Actions release builder (= Phase 4)
- Universal2 binaries
- Self-update / yt-dlp version refresh
- Removing the requirement that the tester have Xcode CLT installed (PyInstaller needs `lipo`)

---

## Acceptance criteria

- [ ] `bash scripts/build-app.sh` exits 0 on a clean dev Mac with ffmpeg + pyinstaller installed.
- [ ] `open dist/audio-dl.app` opens a browser tab to the web UI; closing the browser tab does not stop the server, but quitting the app (cmd-Q / Dock right-click) does.
- [ ] With ffmpeg uninstalled, launching the `.app` shows a native dialog naming `brew install ffmpeg`, not silent failure.
- [ ] `pytest` passes (existing + new).
- [ ] `pylint` ≥ 9.5 on all `*.py` files.
- [ ] README + CHANGELOG + CLAUDE.md updated, framing is honest about the slice.
