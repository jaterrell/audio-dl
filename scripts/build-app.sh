#!/usr/bin/env bash
# Build the macOS .app bundle for audio-dl (Phase 3a slice).
#
# Audience: developers + trusted testers. The bundle this builds is:
#   - Unsigned (ad-hoc signed only to suppress macOS runtime warnings).
#   - Without embedded ffmpeg — the .app surfaces a native dialog telling
#     the user to ``brew install ffmpeg`` if it's missing on PATH.
#
# Signing/notarization for distribution to strangers is Phase 3b — hooks
# are left as ``# TODO`` blocks below for when Joe's Developer ID is wired.
#
# Prereqs (do once per dev machine):
#   python -m pip install -e '.[ui]'
#   python -m pip install pyinstaller
#   brew install ffmpeg     # runtime dep, not build dep
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

rm -rf build dist

python -m PyInstaller audio-dl.spec --noconfirm --clean

# Ad-hoc sign so macOS doesn't refuse to launch with a runtime-integrity gripe.
# This does NOT make the bundle distributable — Gatekeeper still blocks it on
# first launch via "right-click → Open" or ``xattr -d com.apple.quarantine``.
codesign --force --deep --sign - dist/audio-dl.app

# TODO (Phase 3b): real signing + notarization when Joe's Developer ID is set up:
#   codesign --force --deep --options runtime \
#            --sign "Developer ID Application: <Joe Terrell>" \
#            --entitlements scripts/entitlements.plist \
#            dist/audio-dl.app
#   ditto -c -k --keepParent dist/audio-dl.app dist/audio-dl.zip
#   xcrun notarytool submit dist/audio-dl.zip \
#       --keychain-profile audio-dl-notary --wait
#   xcrun stapler staple dist/audio-dl.app

cat <<MSG

Built: dist/audio-dl.app

Try it:
  open dist/audio-dl.app

If macOS Gatekeeper refuses, either right-click the bundle in Finder and
choose Open, or strip the quarantine attribute:
  xattr -d com.apple.quarantine dist/audio-dl.app

Reminder: the .app expects ffmpeg on PATH. If it's missing, a dialog will
appear telling the user to run ``brew install ffmpeg`` — but this is Phase
3a and we don't embed ffmpeg yet. Power-user UX, not consumer UX.

MSG
