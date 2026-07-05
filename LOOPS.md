# Project loops

Saved, reusable agent loops for this project. Each entry records the loop
name, what it does, the exact prompt to run it, and when it was saved.

## Release preflight

Checks that a candidate release commit's version is internally consistent —
the real pre-tag gate that `tag-release.yml` enforces — iterating one fix at a
time until it agrees, and stopping to ask rather than guessing a version or
performing the tag itself.

Prompt:
> Before tagging a release, verify the version is internally consistent:
> confirm `__version__` (audio_dl.py), `version` (pyproject.toml), and the top
> `## vX.Y` section in CHANGELOG.md all match the intended release version. Fix
> one discrepancy at a time — bump a lagging version or add the missing
> CHANGELOG section — re-checking after each. Stop when all three agree and
> report ready to tag. Ask before choosing a version number, or tagging,
> pushing, or dispatching any release workflow. (Packaging health — mutagen,
> the web bundle, ffmpeg — is gated downstream by the bundle smoke test in
> release.yml, not this loop; running `audio-dl-ui --selfcheck` against a bare
> source checkout gives false failures because `static/` isn't built.)

Saved: 2026-07-05 (unpublished design; Loop Library catalog was unavailable at
save time, so overlap with a published loop was not verified. Revised same day
per PR #59 Codex review: dropped the source-checkout `--selfcheck` step, which
false-fails on a clean checkout, and scoped the loop to version consistency.)
