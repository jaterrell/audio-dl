#!/usr/bin/env bash
#
# publish.sh — Mirror filtered history from the private repo to the public one.
#
# Workflow: clone the private repo --bare into a temp dir, run git-filter-repo
# to drop EXCLUDE_PATHS, then force-push main + v* tags to the public repo.
# Idempotent. Manual fallback for .github/workflows/mirror-public.yml.
#
# Pushes ONLY refs/heads/main and refs/tags/v* — not --mirror — so internal
# feature branches never leak to public and non-release tags stay private.
# Tag deletions are not propagated (releases are permanent). To clean up a
# stale ref on public, delete it explicitly with `gh api`.
#
# Run from anywhere. Requires: git-filter-repo, gh (for release sync, optional).
# Usage:
#   ./scripts/publish.sh [--dry-run]
#
set -euo pipefail

PRIVATE="https://github.com/jaterrell/audio-dl-internal.git"
PUBLIC="https://github.com/jaterrell/audio-dl.git"
EXCLUDE_PATHS=(.claude CLAUDE.md)

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
git log --oneline -10
echo "→ Tags after filter:"
git tag --list | sort -V
echo

if [[ $DRY_RUN -eq 1 ]]; then
  echo "✓ Dry run complete. Nothing pushed."
  exit 0
fi

echo "→ Pushing main + v* tags to $PUBLIC (force on both)"
git push "$PUBLIC" \
  +refs/heads/main:refs/heads/main \
  '+refs/tags/v*:refs/tags/v*'
echo "✓ Public mirror updated"
echo
echo "Notes:"
echo "  - Internal feature branches and non-v* tags are NOT pushed."
echo "  - GitHub releases (notes, attached assets) are not git objects."
echo "    They're created by public's release.yml on tag push, not here."
echo "  - To delete a stale ref on public, do it explicitly:"
echo "      gh api -X DELETE repos/jaterrell/audio-dl/git/refs/heads/<branch>"
