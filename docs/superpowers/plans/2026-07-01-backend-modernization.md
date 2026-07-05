# Backend Modernization — Implementation Plan

**Status:** ACTIVE (unblocked 2026-07-04) — the feature brainstorm
concluded in the [related-content design](../specs/2026-07-01-related-content-discovery-design.md)
+ [plan](2026-07-03-related-content-discovery.md), which supersedes
increment 7. **Sequencing: that plan executes first, on the current
monolith** (it is line-number-anchored to it and needs nothing from this
program); increments 1–6 then proceed as written, absorbing the shipped
feature. See the spec's *Amendment (2026-07-04)* for the full
reconciliation.
**Date:** 2026-07-01 (amended 2026-07-04)
**Spec:** [2026-07-01-backend-modernization-design.md](../specs/2026-07-01-backend-modernization-design.md)

## Ground rules (every increment)

- One PR per increment; implementation commits only (spec/plan docs land
  on main separately per repo convention).
- `pytest` + `pylint` + `web/ npm test` green at every PR boundary; CI
  builds the web bundle first as today.
- The re-export shim table in the spec ("Test-contract names are API") is
  a review checklist item on every PR touching `audio_dl_ui`.
- Every PR's description states its **abandon state**: what the codebase
  permanently gains if the program stops after that PR.
- SSE v1 vocabulary and all legacy route shapes are byte-frozen; changes
  are additive fields/events/routes only.
- New code carries no new `[ui]` dependencies. Anything stdlib-only.
- `audio-dl.spec` hiddenimports and `--selfcheck` are re-verified on any
  PR that adds a module or a lazy import (increments 1, 4, 6, 7
  especially) — build the `.app` locally and run
  `scripts/smoke-test-bundle.sh` before merge.

## Increment ladder

### 1. Package re-home (pure mechanical split)

Split `audio_dl_ui/__init__.py` into the spec's layout (`app.py`,
`main.py`, `csrf.py`, `models.py`, `thumbnails.py`, `jobs/runner.py`,
`jobs/manager.py`, `events/{bus,snapshot,sse}.py`,
`routers/{legacy,system,spa}.py`, `native/{desktop,preflight}.py`) with
`__init__.py` re-exporting every pinned name. **Zero behavior change;
zero test edits** — that's the acceptance test. Swap `audio-dl.spec` to
`collect_submodules("audio_dl_ui")`. The shim table additionally covers
the related-content feature's names, which land first (`related.py`
symbols, `_RELATED_EXECUTOR`, `_run_discovery`,
`_fetch_related_thumb_bytes`, `_GUARANTEED_EVENT_TYPES`,
`_RELATED_LINGER_CAP_SECONDS`).

- Verify: full test suite untouched and green; `.app` build + smoke test.
- Abandon state: a readable, navigable package. Worth having alone.
- Risk: import cycles (runner ↔ bus). Break them by having `runner`
  receive an `emit` callable rather than importing the bus.
- Risk: patch-target locations. Tests patch `audio_dl_ui.httpx.stream`,
  `audio_dl_ui.uvicorn`, `audio_dl_ui.webbrowser`, and setattr
  `download_media`/`sanitize_url`/`_check_dependencies` on the root
  module. Moved code must resolve these through the root namespace at
  call time (`import audio_dl_ui as root; root.httpx.stream(...)`) or
  the patches silently stop intercepting — see the spec's
  "Patch-target locations" note.

### 2. Settings + paths + durable logging + egress hardening

`config.py` (frozen dataclass; CLI > `AUDIO_DL_*` env > TOML via
`tomllib` > defaults; `validate()` keeps the loopback/`--allow-remote`
gate byte-identical; `lastfm_api_key` never serialized into any
response), `paths.py` (per-OS data/config/log dirs — includes the
**Windows `%LOCALAPPDATA%` fix**; `_thumb_cache_dir` migrates onto it),
`logging_setup.py` (stdlib `RotatingFileHandler`; job transitions +
errors logged), and `egress.py` — the guarded outbound-HTTP helper
(scheme allow-list, bounded timeouts, redirect cap, private-IP guard)
**retrofitted onto `_fetch_thumbnail` now** — the shipped related-content
feature deliberately left it unhardened — and absorbing that feature's
own helpers (`_fetch_related_thumb_bytes`, `is_allowed_thumb_url`) so
one module owns outbound HTTP policy. `main()` builds `Settings` and
stores it on `app.state.settings`; old `app.state.default_output_dir` /
`max_parallel` / `csrf_token` / `related_enabled` reads become shims
over it (`related_enabled` is a Settings field, default true, set false
by `--no-related`).

- Verify: existing settings/CSRF tests green via shims; new unit tests
  for precedence order, TOML parsing, `paths.py` per-platform branches
  (monkeypatched `sys.platform`), log file rotation, and egress guards
  (scheme rejection, private-IP rejection, redirect cap) with `httpx`
  mocked.
- Abandon state: typed config, correct Windows paths, SSRF-guarded
  egress, and the `.app` finally writes a crash-forensics log.

### 3. JobStore protocol + MemoryStore + eviction

`jobs/store.py`: the `JobStore` protocol from the spec; `MemoryStore`
wrapping the `JOBS` dict (which becomes the store's backing dict —
`audio_dl_ui.JOBS` alias still points at the same object so test
mutation keeps working). Add the **eviction sweep** (terminal jobs
pruned by age/count; startup + hourly) — this fixes the unbounded-memory
leak. `JobManager` (`jobs/manager.py`) becomes the single owner of
store + `_GLOBAL_EXECUTOR` (module alias preserved).

- Verify: a `JobStore` **contract test suite** (parametrized fixture,
  currently one impl) covering save/get/list/update_url/prune; existing
  lifecycle tests untouched; a new eviction test.
- Abandon state: memory leak fixed; persistence-shaped seam in place.

### 4. SqliteStore (opt-in) + graceful shutdown + migrations

`SqliteStore` behind `--persist` (default off): WAL mode, dedicated
single-writer thread draining a write queue (workers never touch the
DB), transition-debounced writes, full-fidelity schema (includes
`output_dir`/`playlist`/`force`/`fragments` — **not** the
`_build_snapshot` projection), `migrations.py` with
`PRAGMA user_version`. Startup rehydration marks prior non-terminal jobs
`interrupted`. Graceful shutdown: lifespan hook + SIGTERM → drain flag,
flip in-flight jobs to `interrupted` in-store, flush writer queue with
deadline; **cancel deletes `.part` partials, shutdown/crash keeps them**.
`--selfcheck` gains the DB-writable probe.

- Verify: contract suite now parametrized over both stores; rehydration
  test (create → kill writer → reopen → `interrupted`); migration test
  (v0 DB upgrades cleanly); shutdown test (SIGTERM in a subprocess run);
  `/reveal` allow-list works from a rehydrated job's `output_dir`.
- Abandon state: durable job history + honest restart semantics, still
  default-off — a complete standalone feature.

### 5. /api/v2 surface + global event channel (+ codegen)

`routers/v2.py`: `GET /api/v2/jobs[?active=1]`, `GET /api/v2/jobs/{id}`,
`GET /api/v2/health`, and `GET /api/v2/events` — the persistent
multiplexed SSE channel fed by `events/bus.py` (per-job stream behavior
and thumb-dir cleanup untouched). CI step generates
`web/src/lib/generated/v2.ts` from the OpenAPI schema (v2 routes only)
and fails on drift. Frontend follow-up (small, may ride along or land
separately): on load, `GET /api/v2/jobs?active=1` → re-open per-job SSE
→ re-register in `tracked-jobs.ts` — the refresh-orphan fix.

- Verify: v2 endpoint tests (CSRF on streams, list correctness against
  both stores); global-channel test (event pushed after `job_completed`
  is received); codegen determinism check in CI; frontend reconnect test
  with `MockEventSource`.
- Abandon state: server-authoritative job list + a post-terminal push
  channel any future feature can use.

### 6. Metadata enrichment + hot-path cleanup

Extend the first-info-dict branch in `jobs/runner.py` to capture
`track, artist, album, channel_id, webpage_url, tags, extractor` into
`UrlState.source_meta` (additive dataclass field, additive DB column +
migration, additive snapshot field). **This branch already hosts the
shipped related-content glue** (seed assembly via `resolve_artist`,
discovery trigger, `related_status` on the `url_metadata` emitters) —
capture must coexist with it, and `source_meta` should become the seed's
source of truth so metadata is extracted once. **Remove the 1.5 s
thumbnail poll** from `_run_one`: the fetch thread persists to the cache
itself and emits a follow-up `url_metadata` event carrying `thumb_id`;
`url_completed` carries `thumb_id` when already available, `null`
otherwise. Both emitters keep the feature's additive `related_status`
field intact.

- Verify: hook test asserts new fields captured; timing test asserts
  `_run_one` completion no longer sleeps; frontend reducer handles the
  additive `thumb_id` on `url_metadata` (one new case + test).
- Abandon state: richer cards/history data + faster completions, useful
  regardless of what the brainstorm decides.

### 7. Re-home the shipped related-content feature (superseded build → move)

The feature itself ships **before** this program via the
[2026-07-03 plan](2026-07-03-related-content-discovery.md) (yt-dlp-native
providers, default ON with `--no-related`, `url_related` on the legacy
per-job stream with a ≤10 s linger, results in localStorage). This
increment only relocates it into the layered package: `related.py` →
`features/related/`, hook/executor/SSE glue → `jobs/runner.py` /
`jobs/manager.py` / `events/`, `app.state.related_enabled` → the
`Settings.related_enabled` field (shimmed since increment 2). Optional
follow-up (frontend-paced, not required): migrate `url_related` onto the
v2 global channel and delete the linger.

- Verify: the feature's own test suite green unmoved (re-export shims
  cover its pinned names); no SSE vocabulary or wire-shape change.
- Abandon state: feature keeps working exactly as shipped; only the
  code location differs.

### 8. Personal-cloud Docker target (optional, last)

`Dockerfile` (python-slim + system ffmpeg, `[ui]` only) +
`docker-compose.yml`, entrypoint honoring `AUDIO_DL_UPDATE_YTDLP=1`,
healthcheck on `/api/v2/health`, docs page stating the deployment
posture (behind operator auth only; BYO cookies read-only; never
public). Parallel non-blocking CI job builds the image and runs a
mocked-download smoke test. Optional: cookie-based CSRF double-submit
for `--allow-remote` mode.

- Verify: compose smoke in CI; `release.yml`/`mirror-public.yml`
  untouched; smoke-test-bundle contract unaffected.
- Abandon state: the cloud story exists without ever having touched the
  desktop pipeline.

## Sequencing notes

- **Increment 0, in effect: the related-content plan
  (2026-07-03) executes first on the monolith.** Running the two
  programs concurrently is the one forbidden arrangement — they collide
  in `_make_progress_hook`, `_events_iter`, `UrlState`,
  `_build_snapshot`, the guaranteed-event set, and `main()`.
- 1→2→3→4 are strictly ordered. 5 needs 3 (list endpoint reads the
  store) but not 4. 6's metadata capture + snapshot fields need only 1,
  but its DB column/migration piece needs 4 — if 6 ever jumps ahead of
  4, ship the capture and defer the column into 4's migration chain.
  7 (re-homing) needs only 1+2; its optional v2-channel migration needs
  5. 8 needs 4 (persistence makes a cloud instance sane) and
  5 (its container healthcheck targets `/api/v2/health`); egress
  hardening arrives with 2, well before any remote exposure.
- The brainstorm outcome clause resolved on 2026-07-04: the chosen
  feature IS related content, but per its own design — increments 1–6
  proceed unchanged and increment 7 became the re-homing step above.
- Estimated sizes: 1 is large-but-mechanical; 2–6 are each small/medium
  reviewable PRs; 7 is now small; 8 is small.

## Documentation debt paid along the way

- CLAUDE.md still describes `audio_dl_ui.py` as a single file and the UI
  as vanilla-JS templates — increment 1's PR updates the Layout section
  to the package layout (and fixes the stale React description).
- `README`/`INSTALL` gain the `--persist` flag (inc. 4) and the Docker
  posture doc (inc. 8).
