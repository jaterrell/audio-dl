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

# Ship the third-party notices + full license texts alongside the bundle.
# Required for the LGPL (ffmpeg) and GPL (mutagen) components embedded in the
# .app — the license text has to travel with the binary, not just live in the
# repo. Both files are required; fail loudly if either is missing.
for lic in NOTICE.md LICENSES; do
    if [[ ! -e "$lic" ]]; then
        echo "ERROR: ${lic} missing — required for bundled GPL/LGPL license compliance." >&2
        exit 1
    fi
done
cp NOTICE.md "$STAGE/NOTICE.md"
cp -R LICENSES "$STAGE/LICENSES"

cd dist/release
zip -qr "${STAGE_NAME}.zip" "$STAGE_NAME"
shasum -a 256 "${STAGE_NAME}.zip" > SHA256SUMS

echo "Packaged: dist/release/${STAGE_NAME}.zip"
echo "Checksum: dist/release/SHA256SUMS"
