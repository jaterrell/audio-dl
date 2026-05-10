#!/usr/bin/env bash
#
# publish.sh — Mirror filtered history from the private repo to the public one.
#
# Workflow: clone the private repo --bare into a temp dir, run git-filter-repo
# to drop EXCLUDE_PATHS, then force-push --mirror to the public repo. Idempotent.
#
# Run from anywhere. Requires: git-filter-repo, gh (for release sync, optional).
# Usage:
#   ./scripts/publish.sh [--dry-run]
#
set -euo pipefail

PRIVATE="https://github.com/jaterrell/audio-dl-internal.git"
PUBLIC="https://github.com/jaterrell/audio-dl.git"
EXCLUDE_PATHS=(.claude)

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "→ Cloning $PRIVATE (bare)"
git clone --bare --quiet "$PRIVATE" "$WORK/repo.git"
cd "$WORK/repo.git"

echo "→ Filtering: removing ${EXCLUDE_PATHS[*]} from history"
filter_args=()
for p in "${EXCLUDE_PATHS[@]}"; do
  filter_args+=(--path "$p")
done
git filter-repo --invert-paths "${filter_args[@]}" --force --quiet

echo
echo "→ Filtered history (head):"
git log --oneline | head -10
echo "→ Tags after filter:"
git tag --list | sort -V
echo

if [[ $DRY_RUN -eq 1 ]]; then
  echo "✓ Dry run complete. Nothing pushed."
  exit 0
fi

echo "→ Pushing --mirror to $PUBLIC (force-overwrites public branches/tags)"
git push --mirror "$PUBLIC"
echo "✓ Public mirror updated"
echo
echo "Note: GitHub releases (notes, attached assets) are not git objects and"
echo "do not transfer with --mirror. Re-create them on the public repo with"
echo "  gh release create <tag> --repo jaterrell/audio-dl --notes-file <file>"
echo "or via the GitHub UI. Tag refs themselves are already in place."
