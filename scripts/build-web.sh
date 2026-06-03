#!/usr/bin/env bash
# Build the React frontend and copy the bundle into the Python package's static/.
set -euo pipefail
cd "$(dirname "$0")/.."

pushd web > /dev/null
npm ci
npm run build
popd > /dev/null

rm -rf audio_dl_ui/static
mkdir -p audio_dl_ui/static
cp -R web/dist/* audio_dl_ui/static/
# Restore the tracked placeholder so 'git status' stays clean.
touch audio_dl_ui/static/.gitkeep
echo "web bundle → audio_dl_ui/static/"
