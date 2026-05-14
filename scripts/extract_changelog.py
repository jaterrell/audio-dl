#!/usr/bin/env python3
"""Extract a CHANGELOG.md section for use as GitHub Release notes.

Usage:
    python scripts/extract_changelog.py v1.4.0 > RELEASE_NOTES.md

Reads CHANGELOG.md from cwd. Looks for a header matching "## <tag> ..." at
line start. If the tag is "vX.Y.Z" and no exact match is found, retries
with the trailing ".0" stripped ("vX.Y") to handle the precedent of
tagging minor releases with just two version components.

The section terminates at the next ## header (any version format), so this
works correctly with both modern "## vX.Y" and older Keep-A-Changelog
"## [X.Y.Z]" headers.

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
    if tag.endswith(".0"):
        candidates.append(tag[:-2])

    for needle in candidates:
        pattern = re.compile(
            rf"^##\s+{re.escape(needle)}(?:\s|$).*?(?=^##\s|\Z)",
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
    """Entry point for the script.

    Args:
        argv: Command-line arguments (argv[0] is program name, argv[1] is tag).

    Raises:
        SystemExit: If CHANGELOG.md is not found or tag is not matched.
    """
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
