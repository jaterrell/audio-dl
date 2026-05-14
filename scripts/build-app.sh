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

set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "ERROR: build-app.sh targets macOS only (this is Phase 3a)." >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! python -c "import PyInstaller" 2>/dev/null; then
    echo "ERROR: pyinstaller is not installed in the active Python environment." >&2
    echo "  python -m pip install pyinstaller" >&2
    exit 1
fi

if ! python -c "import audio_dl_ui" 2>/dev/null; then
    echo "ERROR: audio_dl_ui not importable — install the [ui] extra first." >&2
    echo "  python -m pip install -e '.[ui]'" >&2
    exit 1
fi

if ! python -c "import imageio_ffmpeg" 2>/dev/null; then
    echo "ERROR: imageio_ffmpeg not installed — required for the embedded ffmpeg binary." >&2
    echo "  python -m pip install imageio-ffmpeg" >&2
    exit 1
fi

rm -rf build dist

python -m PyInstaller audio-dl.spec --noconfirm --clean

# Ad-hoc sign so macOS doesn't refuse to launch with a runtime-integrity gripe.
# This does NOT make the bundle distributable — Gatekeeper still blocks it on
# first launch via "right-click → Open" or ``xattr -d com.apple.quarantine``.
codesign --force --deep --sign - dist/audio-dl.app

# Distribution is unsigned by design (trusted-tester scope) — Gatekeeper
# on first launch is handled by INSTALL.md / README-FIRST.txt, not by
# signing. See docs/superpowers/specs/2026-05-13-release-pipeline.md.

cat <<MSG

Built: dist/audio-dl.app

Try it:
  open dist/audio-dl.app

If macOS Gatekeeper refuses, either right-click the bundle in Finder and
choose Open, or strip the quarantine attribute:
  xattr -d com.apple.quarantine dist/audio-dl.app

ffmpeg is now embedded via imageio-ffmpeg (Phase 3b) — no Homebrew install
required for the .app to function. License attribution: see LICENSES/
inside the bundle.

MSG
