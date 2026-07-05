# Backend Modernization — Implementation Plan

**Status:** ACTIVE (unblocked 2026-07-04) — the feature brainstorm
concluded in the [related-content design](../specs/2026-07-01-related-content-discovery-design.md)
+ [plan](2026-07-03-related-content-discovery.md), which supersedes
increment 7. **Sequencing: that plan executes first, on the current
monolith** (it is line-number-anchored to it and needs nothing from this
program); increments 1–6 then proceed as written, absorbing the shipped
feature. See the spec's *Amendment (2026-07-04)* for the full
reconciliation.
**Date:** 2026-07-01 (amended 2026-07-04; re-verified against v2.4.0
2026-07-05)
**Spec:** [2026-07-01-backend-modernization-design.md](../specs/2026-07-01-backend-modernization-design.md)

> **⛔ GATE — increment 1 must not open until BOTH are true:**
> 1. the [related-content plan](2026-07-03-related-content-discovery.md)
>    is **implemented and merged** (as of 2026-07-05 it is **docs-only**;
>    `audio_dl_ui/` on `origin/main` is still just `__init__.py` +
>    `static/` — no `related.py`, no `_RELATED_*`, no `url_related`, no
>    linger), and
> 2. the increment-1 shim table has been **re-verified against the real
>    merged code** (both the related-content names *and* the v2.4
>    auto-shutdown names — see increment 1).
>
> This is a hard precondition, not prose guidance: the 8-hourly
> autonomous PR watcher merges PRs and dispatches fix agents, so a
> sequencing sentence alone is not an enforcement mechanism. A PR that
> opens increment 1 before the gate clears is out of order and should be
> closed.

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

**Gate first:** do not open this increment until the status-block gate
above clears (related-content merged + shim table re-verified).

Split `audio_dl_ui/__init__.py` into the spec's layout (`app.py`,
`main.py`, `csrf.py`, `models.py`, `thumbnails.py`, `jobs/runner.py`,
`jobs/manager.py`, `events/{bus,snapshot,sse}.py`,
`events/presence.py` (the v2.4 auto-shutdown state),
`routers/{legacy,system,spa}.py`, `native/{desktop,preflight}.py`) with
`__init__.py` re-exporting every pinned name. **Zero behavior change;
zero test edits** — that's the acceptance test. `create_app` configures
and returns the **module-level `app` singleton** (tests mutate
`app.state` on the import-time object; the factory must not build a fresh
instance). Swap `audio-dl.spec` to `collect_submodules("audio_dl_ui")`.

The shim table covers three name sets:
- **v2.4 auto-shutdown (already on `origin/main`, must carry now):**
  `_Presence`, `_PRESENCE`, `_presence_reset`, `_presence_connect`,
  `_presence_disconnect`, `_presence_iter`, `_should_auto_shutdown`,
  `_shutdown_watchdog`, `_auto_shutdown_enabled`,
  `_SHUTDOWN_GRACE_SECONDS`, and the `GET /presence` route
  (→ `routers/legacy.py`). Tests mutate `ui._PRESENCE.last_disconnect`
  directly, so a re-export alone is insufficient — the state singleton
  must be the same object.
- **related-content (lands first; re-verify at the gate):** `related.py`
  symbols, `_RELATED_EXECUTOR`, `_run_discovery`,
  `_fetch_related_thumb_bytes`, `_GUARANTEED_EVENT_TYPES`,
  `_RELATED_LINGER_CAP_SECONDS`.
- the base set already enumerated in the spec's "Test-contract names".

- Verify: full test suite untouched and green; `.app` build + smoke test;
  **an automated patch-interception guard** — a test asserting
  `patch("audio_dl_ui.httpx.stream")` (and `uvicorn`/`webbrowser`) still
  intercepts at each moved call site, or an import-linter contract
  forbidding bare `import httpx`/`uvicorn`/`webbrowser` in moved modules.
  Eyeball review across ~25 modules is not the guard.
- Abandon state: a readable, navigable package. Worth having alone.
- Risk: import cycles (runner ↔ bus) — **illusory; the dependency is
  one-way.** Still, `runner` receives an `emit` callable rather than
  importing the bus; the callable is a **module-level default**, never a
  new required parameter on a pinned-signature function (arity is fixed by
  tests).
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
gate byte-identical — **and preserves `SystemExit(code==1)`** where tests
assert exit code 1 vs 2; the input-only-secret rule stands for any future
secret-shaped field, though the superseded `lastfm_api_key` no longer
exists), `paths.py` (per-OS data/config/log dirs — includes the
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

The egress guard must **close the DNS-rebinding/TOCTOU hole**, not just
check the resolved IP: resolve once, validate the literal, connect to the
**vetted literal IP** (custom transport / resolver pin, or Host+SNI
override), and set `follow_redirects=False` with manual per-hop
re-validation up to the cap. `_fetch_thumbnail` today follows redirects
with no guard on semi-trusted info-dict URLs — this increment actually
fixes that, per the spec's Outbound HTTP posture.

- Verify: existing settings/CSRF tests green via shims; new unit tests
  for precedence order, TOML parsing, **malformed-TOML and bad-env
  coercion failure paths**, `validate()` exit-code parity (1 vs 2),
  `paths.py` per-platform branches (monkeypatched `sys.platform`), log
  file rotation, and egress guards (scheme rejection, private-IP
  rejection, redirect cap, **and a rebinding test: check-time public IP,
  connect-time private IP is refused**) with `httpx` mocked.
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
  lifecycle tests untouched; a new eviction test; **a test asserting the
  GC/eviction sweep is armed only by `create_app`/`main`, never at import
  time** (import must not spawn a background thread); and an
  **evict-vs-live-subscriber race test** (a job with an open per-job
  stream is not evicted out from under it).
- Abandon state: memory leak fixed; persistence-shaped seam in place.

### 4. SqliteStore (opt-in) + graceful shutdown + migrations

`SqliteStore` behind `--persist` (default off): WAL mode, dedicated
single-writer thread draining a write queue (workers never touch the
DB), transition-debounced writes, full-fidelity schema (includes
`output_dir`/`playlist`/`force`/`fragments` — **not** the
`_build_snapshot` projection), `migrations.py` with
`PRAGMA user_version`. Startup rehydration marks prior non-terminal jobs
`interrupted`. `--selfcheck` gains the DB-writable probe.

**Graceful shutdown composes with the v2.4 watchdog** (this is not
greenfield): the lifespan hook defines one `_drain_and_exit` path — set
drain flag, flip in-flight jobs to `interrupted` in-store, flush writer
queue with a deadline — and **all three exits funnel through it**:
SIGTERM, SIGINT, *and the v2.4 auto-shutdown watchdog* (the common
desktop case, last tab closed, which today exits via `SIGINT`). Miss the
watchdog path and the most frequent shutdown skips persistence.

**`thumb_id` (and increment 6's `source_meta`) persist off the transition
path.** They arrive on a post-`url_completed` `url_metadata` event, which
is *not* a state transition, so the writer's persist triggers must
include it explicitly or `job_urls.thumb_id` stays null and the Library
shows no art after restart.

**Partial deletion is surgical.** `cancel` deleting `.part` files is new
behavior (today `cancel_job` only sets flags). Delete **only** the exact
per-URL temp path captured from the progress hook (`d["tmpfilename"]`),
never a directory sweep — jobs share `output_dir` on one executor, so a
sweep can delete a sibling job's in-flight fragments. If precision proves
fragile, keep flags-only. `shutdown/crash keeps partials`.

**Writer-thread death is handled, not silent.** Per-op exceptions are
caught and logged; a fatal writer-loop exit sets a `store_degraded` flag
surfaced through `/api/v2/health` (which otherwise probes a *reader*
connection and stays falsely green); over-deadline flushes are accounted
for so a completed job whose final write was dropped is not resurrected
as `interrupted`.

- Verify: contract suite now parametrized over both stores; rehydration
  test (create → kill writer → reopen → `interrupted`); migration tests —
  v0 DB upgrades cleanly, **mid-migration failure leaves `user_version`
  un-advanced and is re-runnable**, **corrupt-DB-at-open hits a defined
  fallback**; shutdown test (SIGTERM in a subprocess run) **plus a
  shutdown-via-watchdog test proving the drain runs on the SIGINT/last-tab
  path**; `/reveal` allow-list works from a rehydrated job's `output_dir`;
  a **concurrent-job cancel test** (sibling job's partials survive); a
  **writer-death test** (queue keeps draining or health flips degraded, no
  silent loss); a **reopen-and-assert `thumb_id` test**.
- Abandon state: durable job history + honest restart semantics, still
  default-off — a complete standalone feature.

### 5. /api/v2 surface + global event channel (+ codegen)

`routers/v2.py`: `GET /api/v2/jobs[?active=1]`, `GET /api/v2/jobs/{id}`,
`GET /api/v2/health`, and `GET /api/v2/events` — the persistent
multiplexed SSE channel fed by `events/bus.py` (per-job stream behavior
and thumb-dir cleanup untouched). **The global channel carries the same
bounded-`128` per-subscriber queue + drop-oldest-progress overflow as the
per-job streams, plus keepalive-driven idle reaping** — the global stream
survives job completion and a crashed/refreshed tab never cleanly
disconnects, so without a bound + reap it re-introduces exactly the
subscriber leak increment 3's eviction fixes. CI **regenerates and
diff-checks the committed `web/src/lib/generated/v2.ts`** (v2 routes only;
`git diff --exit-code` after the named regen script — the file is
committed, not built during `build-web.sh`, so the public repo needs no
Python at web-build). Frontend follow-up (small, may ride along or land
separately): on load, `GET /api/v2/jobs?active=1` → re-open per-job SSE
→ re-register in `tracked-jobs.ts` — the refresh-orphan fix.

- Verify: v2 endpoint tests (CSRF on streams, list correctness against
  both stores); global-channel test (event pushed after `job_completed`
  is received); **a dead-subscriber test (queue unregistered after the
  peer vanishes) and a global-queue overflow test**; codegen determinism
  check (`git diff --exit-code`); frontend reconnect test with
  `MockEventSource`.
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
  additive `thumb_id` on `url_metadata` (one new case + test);
  **reopen-and-assert that the post-`url_completed` `thumb_id`/`source_meta`
  actually persist** (they arrive off the transition path — see inc 4);
  **a coexistence test that the related-content glue's `related_status`
  field survives** the capture edit in the same call sites.
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

`Dockerfile` (python-slim + system ffmpeg, `[ui]` only, **runs
non-root** with `PUID`/`PGID` MeTube-style) + `docker-compose.yml` as the
**posture source of truth** (all volumes enumerated: `output_dir`, data
dir = DB + thumb cache, logs; a **commented-out Tailscale/WireGuard
egress exit-node block**; `AUTH_MODE=none` + a startup no-auth warning).
Entrypoint honors `AUDIO_DL_UPDATE_YTDLP=1` (must not hard-fail boot on
network error; writable pip target; `--no-cache-dir`; note the `--read-only`
FS and SBOM caveats). **Logging flips to stdout in-container** (new
log-sink `Settings` field). Healthcheck is a **`python -c` urllib probe**
(no curl in slim) against `/api/v2/health` (CSRF-exempt, minimal body).
SSE responses set `X-Accel-Buffering: no` + `Cache-Control: no-cache`;
the posture doc carries the nginx snippet (buffering off, long read
timeout). **Cookies:** `--cookies cookies.txt` mounted **writable**
(read-only breaks yt-dlp writeback), CLI-side, with the "cookies degrade
fast from datacenter IPs" caveat. Base image pinning is a stated call
(digest+cadence or floating-by-policy). Docs page states the posture
plainly: **inbound auth ≠ egress routing**; YouTube from datacenter IPs
is degraded 60-80% (SoundCloud unaffected); the real mitigations are a
residential exit node or a PO-token sidecar. **Required for this
increment (not optional): the remote CSRF model** (server-only cookie +
`SameSite=Strict` + remote meta-tag injection + stable env token) from
the spec. Without it a `--allow-remote` container behind the intended
proxy serves a **token-less page** — the SPA discovers a token only via
loopback-only meta injection or the dev/loopback `/api/csrf`, and no
local browser is auto-opened with `?token=` — so the healthcheck stays
green while every real remote `POST /jobs` 403s. A cloud target that
can't queue a download is not shippable; the remote-token path gates
increment 8.

**Publish job (mirrors `release.yml`'s two-tier, repo-guarded pattern):**
every push in both repos builds + mocked-download smoke (no registry
push); **only** the public repo, tag-triggered
(`if: github.repository == 'jaterrell/audio-dl'`), publishes
`ghcr.io/jaterrell/audio-dl:vX.Y.Z` + `:latest` via `docker/login-action`
with the default `GITHUB_TOKEN` (`packages: write`, no new secret), built
**multi-arch `linux/amd64,linux/arm64`** on the publish job only.

- Verify: compose smoke in CI (**with volumes, and a restart-survival
  check**); **remote CSRF end-to-end — a remote client (no `?token=`, no
  loopback meta injection) can actually POST /jobs and it survives a
  restart** (required gate, not conditional); `release.yml`/
  `mirror-public.yml` untouched; smoke-test-bundle contract unaffected.
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
