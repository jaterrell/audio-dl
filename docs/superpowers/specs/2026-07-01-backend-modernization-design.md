# audio-dl Backend Modernization — Evolve-in-Place, SaaS-Shaped (design spec)

**Status:** ACTIVE (unblocked 2026-07-04) — the related-content feature
brainstorm concluded (see [Amendment (2026-07-04)](#amendment-2026-07-04-brainstorm-concluded--program-unblocked)).
Implementation is gated on the related-content plan landing first; see
that amendment for the sequencing gate.
**Date:** 2026-07-01 (amended 2026-07-04)
**Owner:** Joe Terrell
**Target release:** v2.6.x program (multiple PRs; v2.4.0 already shipped
the auto-shutdown work (#56) and v2.5.0 is claimed by the related-content
feature that lands first, so this program's first increment lands no
earlier than v2.6.0)

## Purpose

Restructure the web backend (`audio_dl_ui/__init__.py`, 1,249 lines) into a
layered, persistent, extensible service so that UX-driven features — the
planned "related music/content links per queued URL" feature is the worked
example throughout — plug in end-to-end without touching unrelated code, and
so that a cloud deployment is a configuration, not a rewrite.

This spec was produced by a multi-agent design program: five codebase
mappers, three external researchers (modern Python stacks, SaaS/legal
feasibility, related-content APIs), three independent architecture proposals
(evolve-in-place / queue-ready / SaaS-first), three judges, and an
adversarial completeness critic. The decisions below are the judges'
synthesis with every critic finding addressed.

## The headline decisions

1. **Evolve in place. No new infrastructure.** The target is a modular
   monolith inside the `audio_dl_ui` package: app factory, routers, service
   layer, job store, event bus. No Redis, no broker, no worker processes, no
   S3, no new `[ui]` dependencies. Persistence is stdlib `sqlite3`.
   Cloud-readiness comes from seams, not distributed pieces.
2. **Public multi-tenant SaaS is rejected — deliberately and permanently.**
   Not as a deferral: the research is unambiguous (see [SaaS
   verdict](#saas-verdict-and-the-personal-cloud-target)). What ships instead
   is an optional **single-tenant "personal cloud"** Docker target, gated
   behind the operator's own auth proxy.
3. **The shipped API contract is frozen; everything new is additive under
   `/api/v2/`.** The bundled React app's wire contract (bare routes + exact
   SSE vocabulary) is treated as an immutable v1. New endpoints, the
   persistent event channel, and OpenAPI→TS type generation live under v2.
4. **Jobs become durable.** A `JobStore` protocol with the in-memory store
   as default and an opt-in (later default) SQLite store: job history
   survives restarts, the memory leak is fixed by eviction, and the server
   finally has an authoritative job list.
5. *(superseded — see Amendment)* **Related-content ships as a keyless,
   default-OFF, fully-isolated feature** — a provider chain (MusicBrainz →
   ListenBrainz → yt-dlp-native → Odesli) on its own executor and its own
   cache, riding the v2 event channel. It is the litmus test for the
   layering, and it is **privacy-gated**: enabling it is an explicit user
   decision because it sends track metadata to third-party APIs.
   *The concluded brainstorm chose a yt-dlp-native, default-ON design
   instead ([related-content design](2026-07-01-related-content-discovery-design.md));
   it ships first, and increment 7 re-scopes to re-homing it.*

## Amendment (2026-07-04): brainstorm concluded — program unblocked

The feature brainstorm this program was holding for has concluded: the
related-content feature was **designed and planned** independently
([design](2026-07-01-related-content-discovery-design.md),
[plan](../plans/2026-07-03-related-content-discovery.md), merged via
PRs #42/#52/#55) — and it chose a **different design** than this spec's
increment 7 / worked example. Note the merged PRs landed **docs only**:
as of `origin/main` (v2.4.0) `audio_dl_ui/` still contains just
`__init__.py` + `static/` — no `related.py`, no `_RELATED_*` symbols, no
`url_related` event, no linger. The reconciliation below is written for
the state *after* that plan is implemented; everything it calls "shipped"
is shipped only once that implementation merges. Reconciliation:

- **Sequencing: related-content is implemented first, on the current
  monolith.** Its plan is anchored to the monolith's line numbers, needs
  nothing from this program, and is approved. Once it merges, increments
  1–6 proceed as written, absorbing `audio_dl_ui/related.py` into the
  package split.
- **Hard gate (enforcement, not prose):** **increment 1 must not open
  until the related-content implementation is merged and the shim-table
  names below are re-verified against the real code.** This is a
  checklist precondition in the plan's status block, not a suggestion —
  the 8-hourly autonomous PR watcher merges PRs and dispatches fix
  agents, so a prose sequencing rule alone is not an enforcement
  mechanism. If the related-content plan slips or changes shape, the shim
  table (increment 1) and the hook-glue dedupe (increment 6) re-derive
  from whatever actually landed.
- **Increment 7 is superseded.** The shipped feature is yt-dlp-native
  only (YouTube Mix / SoundCloud recommended → cross-platform
  same-artist search), **default ON** with a `--no-related` opt-out, no
  discovery cache, no new endpoints, results in localStorage — not the
  MusicBrainz→ListenBrainz→Odesli chain, not default-OFF, not the v2
  channel. Increment 7 re-scopes to: *re-home the shipped feature into
  the layered package* (see the plan doc's amended increment 7).
- **The per-job SSE linger contradiction is resolved pragmatically.**
  This spec rejected a "per-job SSE keepalive grace window" in favor of
  the v2 global channel; the related-content design uses exactly that
  grace window (a ≤10 s linger in `_events_iter`). Verdict: the linger
  ships **with the related-content plan, in v1** — it lands before this
  program does, and the v2 channel doesn't exist until increment 5.
  Migrating `url_related` onto the v2 global channel and deleting the
  linger becomes optional later polish under the existing
  "Frontend v1→v2 client migration" out-of-scope item.
- **Settings drops `features_related` and `lastfm_api_key`.** The feature
  is default-ON with a `--no-related` flag (becomes a `Settings` field in
  increment 2), and no provider needs a key.
- **Increment 2's `egress.py` absorbs the feature's outbound-HTTP
  helpers** (`_fetch_related_thumb_bytes`, `is_allowed_thumb_url`) and
  still retrofits the *original* `_fetch_thumbnail`, which the feature
  deliberately left unhardened.
- **Increment 1's re-export shim table** gains the shipped feature's
  pinned names (`related.py` symbols, `_RELATED_EXECUTOR`,
  `_run_discovery`, `_fetch_related_thumb_bytes`,
  `_GUARANTEED_EVENT_TYPES`, `_RELATED_LINGER_CAP_SECONDS`).
- **Increment 6 dedupes against the shipped hook glue:** the feature
  already assembles a discovery seed at the first-info-dict tick and adds
  `related_status` to the `url_metadata` emitters; increment 6's
  `source_meta` capture and `thumb_id` follow-up land in the same call
  sites and must preserve those additive fields.

Sections below marked *(superseded — see Amendment)* are kept as the
historical record of the pre-brainstorm design.

## Current state (re-verified 2026-07-05 against `origin/main`, v2.4.0)

*(Originally written against v2.2.0 on 2026-07-01; re-stamped after PR #56
landed the auto-shutdown subsystem in v2.4.0. The module is now **1,550
lines**, and the suite is **47 classes / 2,632+ lines**.)*

- `audio_dl_ui/__init__.py` — one module holding: 11 routes (10 + the
  new `GET /presence`), `JOBS` (module-level dict, in-memory, **never
  evicted**), `_GLOBAL_EXECUTOR` (process-wide `ThreadPoolExecutor`, the
  only concurrency knob), SSE fan-out (`_emit` → per-subscriber bounded
  `queue.Queue(128)`), CSRF, two thumbnail subsystems, macOS
  dialogs/Finder-reveal, dependency pre-flight, argparse entry, the SPA
  catch-all, **and the v2.4 auto-shutdown subsystem** (`_Presence` /
  module-level `_PRESENCE`, `_presence_reset/_connect/_disconnect/_iter`,
  `_should_auto_shutdown`, `_shutdown_watchdog`, `_auto_shutdown_enabled`,
  `_SHUTDOWN_GRACE_SECONDS`, plus the CSRF-guarded `GET /presence` SSE
  route). This subsystem is the **first signal-adjacent machinery in the
  module** — the watchdog thread exits the server via `SIGINT`, riding
  uvicorn's own handler — so the "no signal handling anywhere" note below
  is now only half true.
- Job history lives **client-side** in `localStorage` (`use-history.ts`);
  the server forgets everything on restart, and a page refresh orphans
  in-flight jobs (`tracked-jobs.ts` is in-memory only — the job keeps
  running server-side but the browser loses the `job_id`).
- Metadata captured from yt-dlp is minimal (title/uploader/duration/
  thumbnail); `track`, `artist`, `channel_id`, `tags`, `webpage_url` are
  discarded — a related-content feature has **no data pipeline today**.
- `_run_one` blocks up to **1.5 s per completed download** polling for the
  thumbnail fetch thread (the poll loop at the tail of `_run_one`; anchor
  to the symbol, not a line number — line anchors here are already stale
  and the related-content plan landing first shifts them again).
- No API *versioning* (bare `/jobs` + inconsistent `/api/*`), no service
  layer, no durable logs (the `.app`'s stderr is invisible), and the SSE
  event shapes are hand-synced across three places (Python dict builders,
  TS interfaces, the `use-job-events.ts` reducer). Signal handling is no
  longer entirely absent: the v2.4 watchdog exits via `SIGINT` through
  uvicorn's handler, but there is still no drain-on-`SIGTERM` path (the
  gap increment 4 fills — see the watchdog-integration note there).

## Hard constraints (all preserved)

| Constraint | Where enforced today |
|---|---|
| Single process; `.app` = one uvicorn, Cmd-Q quits it | `audio-dl.spec` `LSUIElement=False` |
| Loopback bind by default; `--allow-remote` to opt out | `main()` refusal gate |
| CSRF on every mutation + SSE/img (`X-Audio-DL-Token` or `?token=`) | `_require_csrf` |
| Credentials (`--cookies*`, `--sc-auth`) never cross the web layer | CLAUDE.md convention |
| `[ui]` extra stays `fastapi, uvicorn[standard], httpx` | pyproject dep boundary |
| `audio_dl.py` stays a single-file CLI | CLAUDE.md convention |
| SPA catch-all registered last, traversal guards intact | `spa_or_static` |
| Version dual-sourced: `__version__` in `audio_dl.py` + pyproject | `tag-release.yml` greps it |
| `--selfcheck` + headless `127.0.0.1:8000` smoke contract | `smoke-test-bundle.sh` |
| PyInstaller static analysis: new/lazy imports must reach `hiddenimports` | the mutagen incident |

**Test-contract names are API.** The suite (2,632+ lines, 47 classes as
of v2.4.0) imports or monkeypatches these module-level names; every one
stays importable from `audio_dl_ui` via re-export shims for the whole
program — no renames (specifically **not** `_require_csrf` → anything
else; tests don't patch it, but every route's `Depends()` wiring
references it):

`JOBS`, `JobState`, `UrlState`, `_Cancelled`, `_GLOBAL_EXECUTOR`,
`download_media`, `sanitize_url`, `_check_dependencies`, `_run_one`,
`_make_progress_hook`, `_make_url_logger`, `_emit`, `_events_iter`,
`_supervise`, `_build_snapshot`, `_require_csrf`, `_should_keep_log`,
`_pick_thumbnail_url`, `_fetch_thumbnail`, `_persist_thumb`,
`_compute_thumb_id`, `_thumb_dir`, `_cleanup_thumb_dir`,
`_thumb_cache_dir`, `_THUMB_ROOT`, `_THUMB_MAX_BYTES`, `_LOOPBACK_HOSTS`,
`_check_dependencies_gui`, `_show_macos_dialog`, `_selfcheck_problems`,
`_refresh_dev_mode`, `app`, `main`.

**Plus the v2.4 auto-shutdown subsystem** (PR #56), which the split must
carry and which tests pin on the root module exactly like `JOBS` — e.g.
`ui._PRESENCE.last_disconnect` is mutated directly, the same
shared-singleton pattern — so increment 1's "zero test edits" fails
without them shimmed: `_Presence`, `_PRESENCE`, `_presence_reset`,
`_presence_connect`, `_presence_disconnect`, `_presence_iter`,
`_should_auto_shutdown`, `_shutdown_watchdog`, `_auto_shutdown_enabled`,
`_SHUTDOWN_GRACE_SECONDS`. In the target layout the presence state lives
next to the bus (`events/presence.py`, or alongside `events/sse.py`) and
the `GET /presence` route lands in `routers/legacy.py` with the other
frozen routes.

**And — conditionally — the related-content feature's names**, once its
plan lands (it lands first; see the Amendment): `related.py` symbols,
`_RELATED_EXECUTOR`, `_run_discovery`, `_fetch_related_thumb_bytes`,
`_GUARANTEED_EVENT_TYPES`, `_RELATED_LINGER_CAP_SECONDS`. These are
re-verified against the real merged code at increment 1's gate, not taken
on faith from the plan.

**Patch-target locations are contract too, not just names.** Tests patch
`audio_dl_ui.httpx.stream` (7 sites), `audio_dl_ui.uvicorn`,
`audio_dl_ui.webbrowser`, and setattr `_check_dependencies`/
`download_media`/`sanitize_url` on the root module — a re-export alone
doesn't make the *moved call sites* see those patches. Moved code must
dereference these dependencies through the root namespace at call time
(`import audio_dl_ui as root; root.httpx.stream(...)` /
`root.download_media(...)`), so `patch("audio_dl_ui.X")` keeps
intercepting. This is the increment-1 acceptance mechanism for
"zero test edits."

Likewise the SSE wire vocabulary is frozen: `job_snapshot`, `url_started`,
`progress`, `url_log`, `url_completed`, `url_failed`, `url_metadata`,
`job_completed` with their exact current field names. (`url_log` is
backend-emitted and test-asserted; the current frontend ignores it —
freeze it anyway, it feeds the snapshot's `log` field.) New event types
and fields are additive only.

## Target architecture

### Package layout

```
audio_dl.py                 # UNCHANGED single-file CLI
audio_dl_ui/
  __init__.py               # slim: re-export shims (test contract), __version__ passthrough
  app.py                    # create_app(settings) factory; router wiring; SPA last
  main.py                   # argparse entry → Settings → uvicorn.run
  config.py                 # Settings frozen dataclass; CLI > env > TOML file > defaults
  paths.py                  # per-OS data/config/log dirs (fixes the Windows bug)
  logging_setup.py          # RotatingFileHandler into the data dir (stdlib logging)
  csrf.py                   # _require_csrf (moved verbatim) + token helpers
  models.py                 # JobState / UrlState / _Cancelled (lifted verbatim)
  thumbnails.py             # _pick_thumbnail_url, _fetch_thumbnail, _thumb_dir,
                            #   _cleanup_thumb_dir, _persist_thumb, _compute_thumb_id,
                            #   _thumb_cache_dir, _THUMB_ROOT, _THUMB_MAX_BYTES
  egress.py                 # guarded outbound-HTTP helper (see Outbound HTTP posture)
  jobs/
    manager.py              # JobManager: create/get/cancel/list; owns the executor
    runner.py               # _run_one, _make_progress_hook, _supervise,
                            #   _YDLLogger + its _make_url_logger factory, _should_keep_log
    store.py                # JobStore protocol; MemoryStore; SqliteStore (+ writer thread)
    migrations.py           # PRAGMA user_version schema migrations
  events/
    bus.py                  # EventBus: today's fan-out + the global v2 channel
    snapshot.py             # _build_snapshot (wire serialization seam)
    sse.py                  # _events_iter + /api/v2/events generators
  features/
    related/                # default-OFF; see worked example
      chain.py providers.py cache.py
  routers/
    legacy.py               # the frozen bare routes (thin adapters)
    v2.py                   # /api/v2/*: jobs list, related, events, health
    system.py               # /api/version, /api/settings/defaults, /api/csrf
    spa.py                  # spa_or_static catch-all (guards preserved, registered last)
  native/                   # NOT "platform/" — avoids shadowing the stdlib module
    desktop.py              # open -R, osascript dialogs (_show_macos_dialog; darwin-gated)
    preflight.py            # _check_dependencies_gui, _selfcheck_problems
  static/                   # built React app (unchanged)
```

`audio-dl.spec` switches to `collect_submodules("audio_dl_ui")` in
`hiddenimports` so the deeper package can never silently drop a module from
the `.app` (the mutagen lesson, closed structurally).

**`create_app(settings)` configures and returns the module-level `app`
singleton — it does not build a fresh instance.** Tests do
`TestClient(app)` and mutate `app.state` on the import-time singleton; if
the factory returned a new instance for `main()`, the store / manager /
GC / settings would attach to an app the tests never see. So `app` is
created module-level (as today), `create_app` wires routers and returns
*that* object, and `main()` mutates its `app.state`. This is the
increment-1/5 contract; the factory is a configuration seam, not an
instance factory.

**Increment 1's "zero test edits" needs an automated guard, not
eyeball.** The root-namespace-dereference rule
(`import audio_dl_ui as root; root.httpx.stream(...)`) is what keeps
`patch("audio_dl_ui.httpx.stream")` intercepting after code moves across
a ~25-module split; a single bare `import httpx` in a moved file passes
the suite today and silently rots the patch later. Add a test that
asserts patch interception still fires at each moved call site (or an
import-linter contract forbidding direct `import httpx`/`uvicorn`/
`webbrowser` in the moved modules). Also: the "import cycles (runner ↔
bus)" risk is illusory — the dependency is one-way — and the `emit`
callable that breaks it must be a **module-level default**, never a new
required parameter on a pinned-signature function
(`_make_progress_hook(job, url_state)` etc. are called with fixed arity
by tests).

### Configuration

`config.py` defines a **frozen plain dataclass** (deliberately not
pydantic-settings — zero new deps, zero PyInstaller risk), resolved with
precedence **CLI flag > `AUDIO_DL_*` env > config file > defaults**. The
config file is TOML read with stdlib `tomllib` from the per-OS config dir.
Fields: `host, port, output_dir, max_parallel, allow_remote, dev_mode,
persist (job store), db_path, log_path, related_enabled` (default true;
set false by `--no-related` — replaces the superseded `features_related`
and `lastfm_api_key` fields, see Amendment). The loopback-refusal gate moves into
`Settings.validate()` unchanged. Gated-content credentials are structurally
absent — not fields at all.

`paths.py` centralizes data/config/log locations and **fixes the latent
Windows bug** that `_thumb_cache_dir` has today (`~/.local/share` on
Windows): darwin → `~/Library/Application Support/audio-dl`; Windows →
`%LOCALAPPDATA%\audio-dl`; else → `$XDG_DATA_HOME`/`~/.local/share`.
One resolver owns every location — data, config, caches, and logs each
land in their platform's *native* spot (logs go to `~/Library/Logs/
audio-dl/` on darwin, the data dir elsewhere) — and `_thumb_cache_dir`
is migrated onto it. No more ad-hoc path logic anywhere else.

*(superseded — see Amendment; no Last.fm key exists in the shipped
design)* `Settings.lastfm_api_key` was a user-supplied secret, **never
serialized into any API response or request schema**. The rule it
encoded stands for any future secret-shaped Settings field: input-only
via CLI/env/TOML.

### Job persistence (`JobStore`)

```python
class JobStore(Protocol):
    def save(self, job: JobState) -> None: ...
    def update_url(self, job_id: str, url: str, **fields) -> None: ...
    def get(self, job_id: str) -> JobState | None: ...
    def list(self, limit: int = 50, active_only: bool = False) -> list[JobSummary]: ...
    def prune(self, max_age: timedelta, max_jobs: int) -> int: ...
```

- **`MemoryStore`** (default initially): wraps today's `JOBS` dict —
  behavior-identical, plus the **eviction cap the current code lacks**
  (terminal jobs pruned by age/count; fixes the unbounded-growth leak).
- **`SqliteStore`** (opt-in via `--persist`, flipped to default once the
  contract tests and a release cycle prove it): stdlib `sqlite3`, WAL mode,
  DB in the `paths.py` data dir.

**The persistence schema serializes real `JobState` fields, not the
`_build_snapshot` wire projection.** The snapshot omits `output_dir`,
`playlist`, `force`, `fragments` — and `/reveal`'s allow-list depends on
`output_dir` — so the schema is explicit:
`jobs(id, created_at, status, output_dir, playlist, force, fragments,
default_format, summary_json)` and
`job_urls(job_id, url, position, format, status, percent, paths_json,
title, uploader, duration, thumb_id, error, meta_json)`.
Locks/queues/deques are never persisted; they're reconstructed empty.

**Write concurrency (explicit, because worker threads write):** a single
dedicated writer thread owns the only write connection and drains a
`queue.Queue` of write ops; worker threads enqueue and never touch the DB.
Reads use per-request connections in WAL mode. This sidesteps
`check_same_thread` and "database is locked" entirely. Progress ticks
(~5/sec/URL) update memory only; DB writes fire on **state transitions**
(`url_started/completed/failed`, `job_completed`) so the hot path never
does I/O.

**One non-transition write is mandatory:** `thumb_id`. Increment 6 moves
thumbnail delivery to a follow-up `url_metadata` event that fires *after*
`url_completed` — which is **not** a state transition, so on the
transition-only trigger set it never persists, `job_urls.thumb_id` stays
null, and the Library view shows no art after a restart. The writer's
persist triggers therefore include a `thumb_ready`/`url_metadata`
carrying `thumb_id` (and, in increment 6, `source_meta`), verified by a
reopen-and-assert test. The same applies to any later additive field
delivered off the transition path.

**Migrations:** `PRAGMA user_version` + ordered migration functions in
`migrations.py` (no Alembic — zero-ops end users). Later increments that
add columns (e.g. related-content metadata) ship a migration; a
fresh-install and an upgraded DB are both tested.

**Restart semantics (honest, not magical):** on startup, jobs that were
non-terminal are marked `interrupted` — a half-downloaded yt-dlp fragment
stream can't resume across a process death. The UI can offer one-click
re-queue; yt-dlp's own `.part` handling resumes what it can.

**Graceful shutdown (new — but no longer greenfield; v2.4 added a
watchdog):** a uvicorn lifespan shutdown hook plus SIGTERM handler: set a
global draining flag, flip in-flight jobs to `interrupted` in the store
*at shutdown* (not just at next startup), flush the writer queue with a
deadline, and leave `.part` files in place (they enable
resume-on-requeue). Covers Cmd-Q on the `.app`, `docker stop` on the
personal cloud — **and the most common desktop shutdown, the v2.4
watchdog exiting when the last tab closes.** That watchdog already exits
via `SIGINT`; increment 4's drain path must run on *that* exit too, not
just SIGTERM, or the common case skips the new persistence guarantees.
Concretely: the watchdog and both signal paths funnel through one
`_drain_and_exit()` helper (flip jobs → flush writer queue → exit); the
lifespan shutdown hook is the single place the drain is defined.

**Partial-file policy (`.part`):** **crash/shutdown keeps partials**
(enables resume); **cancel deletes them** (user intent: discard). This is
*new behavior* — today `cancel_job` only sets flags and nothing deletes a
`.part`. The deletion mechanism must be surgical: jobs share one
`output_dir` on one executor, so a directory sweep can delete a
concurrent job's in-flight fragments. Capture the exact temp path per URL
from the progress hook (`d["tmpfilename"]`) and delete **only that path**,
with a concurrent-job test proving a sibling job's partials survive. If
that precision proves fragile, drop the delete-on-cancel policy and keep
today's flags-only behavior rather than risk cross-job data loss.

**Writer-thread failure is a first-class lost-write path, not an
afterthought:** if the single writer thread dies (disk full, DB
corruption) the write queue grows unbounded and *every* state transition
silently fails to persist — and `/api/v2/health`'s DB probe checks a
*reader* connection, so it stays green. Define the handling: the writer
catches per-op exceptions and continues; a fatal loop exit sets a
`store_degraded` flag surfaced through `/api/v2/health` (degraded, not
OK) and logged at ERROR; the drain deadline is accounted for explicitly
(a completed job whose final write was dropped past the deadline must not
be silently resurrected as `interrupted` on next start — reconcile
memory-terminal against store-non-terminal at shutdown).

### API surface

- **Legacy surface (frozen forever):** `POST /jobs` (returns exactly
  `{job_id}`), `GET /jobs/{id}/events`, `POST /jobs/{id}/cancel`,
  `GET /jobs/{id}/thumb/{idx}.jpg`, `POST /reveal`, `GET /thumbs/{id}.jpg`,
  `GET /presence` (v2.4 auto-shutdown SSE stream; CSRF-guarded like the
  other streams), `GET /api/version`, `GET /api/settings/defaults`,
  `GET /api/csrf`, SPA catch-all. These are the de-facto v1 the shipped
  React bundle speaks; `routers/legacy.py` keeps them as thin adapters
  over the service layer.
- **`/api/v2/` (canonical, additive):**
  - `GET /api/v2/jobs?active=1&limit=N` — server-authoritative job list
    (the thing localStorage never gave us).
  - `GET /api/v2/jobs/{id}` — snapshot without opening a stream.
  - `GET /api/v2/events` — **persistent multiplexed SSE channel** (below).
  - ~~`GET /api/v2/jobs/{id}/urls/{idx}/related` — related-content
    payload.~~ *(superseded — see Amendment.* The shipped related-content
    feature stores results in **localStorage** and adds **no server
    endpoint**; do **not** build this route in increment 5/7. It survives
    only as an **explicit optional migration** if the feature is ever
    re-homed onto server-side persistence — not a canonical v2 route and
    **not a codegen target** until then.)*
  - `GET /api/v2/health` — selfcheck-derived readiness (also used by the
    Docker target's healthcheck).
  - All mutations/streams reuse `Depends(_require_csrf)` unchanged.
- **OpenAPI → TS codegen, v2 only:** CI generates
  `web/src/lib/generated/v2.ts` from FastAPI's schema; a backend field
  rename becomes a TS compile error instead of a silent runtime break.
  v1's hand-maintained shapes stay frozen-by-test and are deliberately
  left out of codegen. **The generated file is committed, not built at
  web-build time.** `scripts/build-web.sh` runs *before*
  `pip install -e '.[ui]'` in `tests.yml`, so a build-time generator
  would need Python present at web-build and would reorder the pipeline;
  committing the file avoids that, crosses the mirror to the public repo
  for free (the public repo never needs Python at web-build time), and
  turns drift-detection into a plain `git diff --exit-code` after
  re-running the named regen script. (See the open decision below on
  whether to build codegen at all before the frontend v2 migration has a
  consumer.)

### Realtime events

SSE stays; native `EventSource` stays (a WebSocket move would rewrite ~15
frontend tests for zero user benefit). Two tiers:

1. **Per-job stream (`/jobs/{id}/events`)** — unchanged wire behavior:
   snapshot-on-connect, live tail, server closes on terminal. Internally it
   reads from `events/bus.py`, but the bounded-128 / drop-progress /
   force-deliver-terminal policy is preserved exactly (`TestQueueBound`).
2. **Global channel (`GET /api/v2/events`)** — one long-lived stream per
   client, surviving job completion. This is the home for **post-terminal
   pushes** (related-content results that arrive after `job_completed`) and
   future cross-job notifications. It exists precisely so we do *not* need
   the rejected alternative (holding per-job streams open on a grace
   timer), and therefore **the thumb-dir cleanup coupling is untouched**:
   per-job stream lifecycle — and the `_cleanup_thumb_dir`-when-
   subscribers-reach-zero logic — behaves exactly as today. Anything
   pushed on the global channel references only durable artifacts (the
   persistent `thumb_id` cache, the jobs DB), never the ephemeral per-job
   temp dir.

   **The global channel must not re-introduce the very leak the store
   eviction (increment 3) fixes.** Per-job streams self-terminate on
   `job_completed`; the global stream lives until the client cleanly
   disconnects, which a crashed/refreshed tab never does. So the global
   channel carries the *same* bounded-`128` per-subscriber queue with the
   drop-oldest-progress overflow policy as the per-job streams, **plus**
   keepalive-driven idle reaping: a periodic keepalive write detects a
   dead peer (write error / no consumer draining a full queue past a
   grace window) and evicts the subscriber. A dead-subscriber test
   asserts the queue is unregistered after the peer vanishes. Without
   this, N browser refreshes leak N subscriber queues forever — exactly
   what `JOBS` eviction was added to prevent.

**Frontend reconnect flow (the refresh-orphan fix, paired client work):**
on app load, query `GET /api/v2/jobs?active=1`; for each in-flight job,
re-open its per-job SSE stream (snapshot-on-connect makes this free) and
re-register it in `tracked-jobs.ts`. Discovery + re-subscribe together
restore live progress after a refresh; today both halves are impossible.

### Outbound HTTP posture (SSRF / egress)

New rule, applied to the existing thumbnail fetcher and all provider
calls: outbound requests go through one helper (`egress.py`) that
enforces **http/https schemes only, bounded connect/read timeouts, a
redirect cap, and rejection of loopback/private/link-local destination
IPs**. Provider calls are further restricted to a **host allow-list**
(`musicbrainz.org`, `labs.api.listenbrainz.org`, `api.song.link`) — they
never fetch arbitrary URLs. Thumbnail URLs from yt-dlp info dicts are
semi-trusted and get the full private-IP guard.

**The private-IP check must survive DNS rebinding — a post-resolution
check alone does not.** If `egress.py` validates the resolved IP and then
hands the *hostname* back to httpx, httpx re-resolves at connect time: a
TTL-0 record that returns a public IP on the check and `169.254.169.254`
(cloud IMDS) on the connect defeats the guard. `follow_redirects=True`
has the same hole — a `302` to an internal address is followed without
re-entering the guard, and today's `_fetch_thumbnail` does exactly this
on semi-trusted info-dict URLs. The mechanism, specified so increment 2
actually closes the hole it names: **resolve the host once, validate the
returned literal IP(s), then connect to the vetted literal** (custom
`httpx` transport / resolver pin, or Host-header + SNI override), and set
**`follow_redirects=False`** with manual per-hop re-validation through the
same helper up to the redirect cap. "Checked post-DNS-resolution" is
necessary but not sufficient; the connect must use the checked IP, not a
second resolution.

**Sequencing is deliberate:** the helper and its retrofit onto
`_fetch_thumbnail` (which today streams arbitrary info-dict URLs with
`follow_redirects=True` and no guard) ship in **increment 2** — early,
feature-independent, and strictly before any remote-deploy work — not
inside the optional related-content increment. The related feature later
reuses the same helper, adding only its host allow-list. This matters
little on loopback and a lot under `--allow-remote`.

### Observability

- `logging_setup.py`: stdlib `RotatingFileHandler` writing to the
  `paths.py` log dir (`~/Library/Logs/audio-dl/` on darwin).
  Job lifecycle transitions and errors at INFO/ERROR, so a crashed job
  finally leaves a forensic trail — critical for the `.app`, where stderr
  is invisible. The 50-entry in-memory SSE log deque is unchanged (UI
  concern); the file is the durable copy.
- `--selfcheck` grows a "DB writable" probe; `/api/v2/health` exposes the
  same probe over HTTP.

### Disk retention (unified)

One GC policy owned by `JobManager`, run at startup + hourly: jobs DB
pruned by `max_age`/`max_jobs`; the persistent thumbnail cache —
**already unbounded today** — gets an mtime-LRU sweep with a size cap
(default 500 MB); per-job temp thumb dirs keep today's exact cleanup.
Caps are `Settings` fields.

## SaaS verdict and the personal-cloud target

**Public multi-tenant SaaS: no.** Two independent walls:

- *Legal:* Cordova v. Huneault (N.D. Cal., Feb 2026) holds YouTube's
  rolling cipher is a DMCA §1201 access control, making circumvention an
  independent claim; the FLVTO/2conv $82.9M judgment and IFPI's Oct 2025
  Y2Mate takedown (12 sites) show active enforcement against exactly this
  business model; SoundCloud's ToU bans stream-ripping outright. A
  monetized public instance is a lawsuit magnet in a way a personal tool
  is not.
- *Operational:* datacenter IPs get BotGuard/PO-token-blocked (~20-40%
  success vs 85-95% residential); mitigation is residential proxies at
  $4-11/GB — more per user than a downloader SaaS could charge. The whole
  self-hosted ecosystem (MeTube, Pinchflat, Tube Archivist, yt-dlp-web-ui)
  converged on "single operator, private network" for these reasons.

**Personal cloud: yes, as the last optional increment.** A `Dockerfile`
(python-slim + system ffmpeg, `pip install '.[ui]'`, **no** `[app]`
extra) running the same app with `--persist --host 0.0.0.0
--allow-remote`. The `docker-compose.yml` is the source of truth for the
deployment posture; see the posture doc below.

**The datacenter-IP wall applies to the personal cloud too — say so
plainly.** The same fact that kills SaaS (datacenter IPs get
BotGuard/PO-token-blocked, ~20-40% success vs 85-95% residential) hits a
VPS deploy: a Hetzner/Lightsail instance sees **YouTube extraction
degraded 60-80%** while **SoundCloud is unaffected** (it doesn't gate on
ASN the same way). This is an *egress-routing* problem and is **distinct
from inbound auth** — the two must not be conflated:

- **Inbound auth** (who may reach the UI) — front the app with the
  operator's own auth (Tailscale / reverse-proxy); never raw-public. This
  does nothing for extraction success.
- **Egress routing** (where yt-dlp's requests originate) — the actual
  mitigation for the datacenter wall. Two real options, documented
  distinctly: **(a)** route yt-dlp egress through a **residential IP** via
  a Tailscale exit node or WireGuard tunnel back to a home network (most
  durable — restores near-residential success); **(b)** a
  `bgutil-ytdlp-pot-provider` **PO-token sidecar** (helps, but is
  insufficient on an IP already flagged). Ship the exit-node pattern as a
  **commented-out block in `docker-compose.yml`** so an operator can
  uncomment it.

**Cookies on the container, corrected.** The earlier "BYO cookies mounted
read-only" guidance was wrong on three counts and is replaced: (1)
`--cookies-from-browser` is impossible in a headless container — only a
`--cookies cookies.txt` file works; (2) a **read-only** mount breaks
yt-dlp's cookie-refresh writeback, so the cookies file mounts
**writable**; (3) YouTube binds session cookies to the originating
IP/fingerprint and burns them fast from datacenter ASNs — using an
account's cookies from a flagged datacenter IP risks the Google account,
so cookies **degrade fast from datacenter IPs** and are not a substitute
for residential egress. Credentials still stay CLI-side (the file is
passed to the CLI layer, never through the web UI).

Serverless stays **explicitly rejected** (ffmpeg transcodes exceed Lambda
limits); the analogous honesty for VM deploys is the datacenter-egress
caveat above, not silence.

yt-dlp staleness in a container is handled by an opt-in entrypoint flag
(`AUDIO_DL_UPDATE_YTDLP=1` → `pip install -U yt-dlp` at start), the
standard MeTube-style pattern, so extractor fixes don't require image
rebuilds. Caveats made explicit: it must **not hard-fail boot on a
network error** (log and continue on the pinned image version); it targets
a **writable location** (breaks under `--read-only` root filesystems —
document a writable pip target or the incompatibility); use
`pip install -U --no-cache-dir`; and note the SBOM/scan caveat (the
running image no longer matches its published digest). For the primary
distributions the yt-dlp policy stays what it is today: unpinned floor
for pip installs (users `pip install -U`), and the `.app` bundles
whatever is current at build time — extractor breakage between releases
is fixed by cutting a patch release.

### Container deployment posture (increment 8 details)

- **Volumes are enumerated in `docker-compose.yml`, which is the source
  of truth.** Named/bind volumes for `output_dir` (the downloads — the
  actual crown jewels), the data dir (SQLite DB + thumb cache), and logs.
  Without them `docker compose down` destroys the downloads and
  increment 4's "shutdown keeps `.part` for resume" is a no-op on the one
  target where restarts are routine.
- **Logging flips to stdout in the container.** `RotatingFileHandler`
  into the data dir is right for the `.app` (stderr is invisible there)
  and backwards in a container (stdout is the only observability surface;
  an in-container log file dies with the container). Add a log-sink
  `Settings` field; the Docker entrypoint selects stdout.
- **SSE through a reverse proxy.** The remote path mandates a proxy;
  nginx's default `proxy_buffering on` withholds `job_snapshot` and clumps
  progress, and default read timeouts cut idle streams. SSE responses
  emit `X-Accel-Buffering: no` + `Cache-Control: no-cache`, and the
  posture doc carries the proxy snippet (buffering off, long read
  timeout).
- **No-auth guardrail.** Desktop refuses non-loopback without
  `--allow-remote`; the container defaults to `AUTH_MODE=none` and binds
  `0.0.0.0`. Log a prominent startup warning ("no app-level auth — front
  this with your own auth proxy") as cheap defense-in-depth.
- **Non-root + PUID/PGID.** `python:slim` runs as root, and root-owned
  files in a bind-mounted `output_dir` is the classic self-hosted
  complaint. Carry MeTube's `PUID`/`PGID` convention (already cited as
  prior art) and run as a non-root user.
- **Healthcheck without curl.** python-slim ships no curl; the
  healthcheck is a `python -c` urllib probe against `/api/v2/health`,
  which is **CSRF-exempt** and keeps a minimal body.
- **Base image pinning** is a deliberate call, not left silent: either
  pin to a digest with a bump cadence, or state the floating tag as an
  intentional tradeoff consistent with the yt-dlp unpinned-floor policy.
- **`_auto_shutdown_enabled` already returns `False` under
  `--allow-remote`** (v2.4), so the container will **not** kill itself
  when browser tabs close — the auto-shutdown watchdog is correctly inert
  on this target. Say so; no extra work needed.

### Publishing the image (increment 8, two-tier like `release.yml`)

The image is not just built — it is **published**, mirroring the existing
`.app`/site two-tier, repo-guarded pattern:

- **Every push, both repos:** build the image + run a mocked-download
  smoke test. Unauthenticated, **no registry push** — a fast breakage
  gate only.
- **Publish only on the public repo, tag-triggered:** guarded exactly like
  `release.yml` (`if: github.repository == 'jaterrell/audio-dl'`), pushing
  `ghcr.io/jaterrell/audio-dl:vX.Y.Z` + `:latest` via `docker/login-action`
  with the default `GITHUB_TOKEN` (`packages: write`) — **no new secret**
  joins the rotation list. Build **multi-arch (`linux/amd64,linux/arm64`)
  on the publish job only**; ARM home servers and VPSes are a primary
  audience for this target. `release.yml` (macOS `.app`) and
  `mirror-public.yml` are untouched.

If off-box durability for the SQLite store is ever wanted on the
personal-cloud target, **Litestream** (continuous WAL streaming to
S3-compatible storage) is the documented option — a sidecar, no code
change, and a better fit than LiteFS for a single-server deploy. Scope it
honestly: Litestream backs up the **job metadata DB only**, not
`output_dir` (the actual crown jewels — the downloaded files). Point the
operator at ordinary volume backup for the files.

**Remote-deploy CSRF hardening — required whenever `--allow-remote` is
actually used (the Docker target always does); moot on loopback. One
coherent model, and a threat model first.** With `AUTH_MODE=none` there is no authenticated
session to protect, so the CSRF token is functionally a **bearer secret**
with no rotation, expiry, or user binding — this is the honest threat
model, and the remote-deploy answer is "front it with your own auth
proxy" (above); the token is defense-in-depth against cross-site POSTs,
not an auth system.

The earlier draft of this paragraph was **internally contradictory**: it
set the token as an `HttpOnly; SameSite=Strict` cookie *and* asked CSRF
checks to accept cookie+header double-submit. Double-submit requires JS
to read the cookie and echo it into `X-Audio-DL-Token`; `HttpOnly` makes
that impossible, and the `<meta name="csrf-token">` injection that would
otherwise supply the header is gated on a loopback client + loopback
Host, so a **remote browser gets neither the meta tag nor a readable
cookie nor a `?token=`** — it can never form the credential to POST
`/jobs`. Pick one model:

- **Chosen: server-only cookie + `SameSite=Strict`, plus meta-tag
  injection on the remote path.** Keep the token cookie `HttpOnly`
  (server-only), rely on `SameSite=Strict` so cookie-carrying requests
  (`EventSource`, `<img>`, top-level POSTs) are same-site by construction,
  **and extend the `<meta name="csrf-token">` injection to the
  `--allow-remote` path** so header-bearing `fetch()` (the `POST /jobs`
  call) has a token to send. State per request which mechanism protects
  it: streams/images ride the `SameSite` cookie; JSON `fetch` mutations
  carry the meta-sourced header. (The rejected alternative — drop
  `HttpOnly` and do true JS-readable double-submit — also works but
  exposes the token to any XSS; the `.app`'s bundled SPA is trusted, so
  the server-only cookie is preferred.)
- **Restart churn is fixed with a stable operator token.**
  `app.state.csrf_token` regenerates every process start, so a container
  with `restart: unless-stopped` (or `AUDIO_DL_UPDATE_YTDLP=1` restarts)
  invalidates every session, and the v2.3.0 stale-token recovery
  (refetch `/`) fails remotely because the re-served page is token-less.
  On the remote path, accept an **operator-supplied token via env**
  (stable across restarts) and make the stale-token recovery actually
  serve a fresh meta tag remotely. Loopback behavior is unchanged.

The acceptance test for this increment is end-to-end and **gating, not
optional**: **a remote client (no `?token=`, no loopback meta injection)
can actually `POST /jobs`** and it survives a container restart. Without
it the healthcheck passes while every real remote mutation 403s on a
token-less page — a cloud UI that can't queue a download does not ship.

**Auth seam, shipped disabled:** the service layer passes an opaque
`principal` (constant `"local"`) through job creation/listing. It is a
documented extension point (`AUTH_MODE=none` is the only shipped value) —
deliberately not built further. `_require_csrf` keeps its name and
signature.

## Worked example: related music/content links *(superseded — see Amendment)*

The concluded brainstorm replaced this design with
[2026-07-01-related-content-discovery-design.md](2026-07-01-related-content-discovery-design.md);
this section is kept as the historical record, and its final paragraph's
escape hatch is exactly what happened.

The end-to-end proof that the layering works. **Default OFF**
(`features_related = false`) — this is a *privacy* decision, not a mere
feature flag: enabling it sends title/artist metadata of what you download
to third-party APIs, which would silently erode the app's local-only
posture if it were on by default. (Thumbnail fetching is the one
pre-existing default outbound call; related-content must not silently
add more.) The setting copy must say so.

1. **Metadata pipeline (increment 6):** the first-info-dict branch in
   `runner.py` (where title/uploader/duration are already captured)
   additionally pulls `track, artist, album, channel_id, webpage_url,
   tags, extractor` into `UrlState.source_meta` (additive field + DB
   column + migration). The same increment **removes the 1.5 s
   completion-path thumbnail poll** (`_run_one` lines 567-570): the
   fetch thread persists the thumbnail itself and emits a follow-up
   `url_metadata` event carrying `thumb_id`; `url_completed` carries it
   only when already available. Valuable alone: richer cards, better
   history, faster completions.
2. **Provider chain (`features/related/`):** `RelatedProvider` protocol;
   chain per research: **MusicBrainz** (MBID resolution; keyless; 1 req/s;
   real User-Agent) → **ListenBrainz Labs** `similar-artists` (keyless) →
   **yt-dlp-native fallback** when no MBID resolves (YouTube Mix
   `&list=RD<id>`; SoundCloud `/tracks/{id}/related` via the client_id
   yt-dlp already scrapes) → **Odesli/song.link** for cross-platform
   outbound links (keyless; 10 req/min). **Last.fm** only if the user
   supplies their own key. **Spotify and Deezer are excluded** — both
   closed to new apps (Nov 2024 / Nov 2025). **ytmusicapi excluded** —
   requires user cookies, colliding with the credentials-stay-CLI rule.
3. **Cache:** a standalone content-addressed SQLite cache
   (`features/related/cache.py`, keyed `sha1(provider + seed)`), in the
   data dir, **independent of the opt-in job store** — rate-limit
   protection must hold on a default MemoryStore install too. Long TTL;
   catalog relations are near-static.
4. **Execution:** on `url_completed`, `JobManager` submits
   `resolve_related(job_id, url)` to a **dedicated
   `ThreadPoolExecutor(max_workers=2)`** — discovery never competes with
   downloads for the `--max-parallel` pool. Failures degrade to an empty
   result; they can never fail a job.
5. **Delivery:** results persist to the store, then push as a new
   `url_related` event on the **global v2 channel** (works after
   `job_completed`; no per-job stream lifecycle change), and are readable
   at `GET /api/v2/jobs/{id}/urls/{idx}/related` for the Library view.
   Frontend: one new case in `use-job-events.ts`'s `applyEvent` (or its v2
   sibling) writing onto the `['job', jobId]` cache; a panel renders it.
6. **Credentials:** the whole default chain is keyless. Nothing
   credential-shaped crosses the web layer.

If the in-progress brainstorm redefines this feature, increments 1-6 are
unaffected (see next section) and only this worked example is re-planned.
*(It did, and it was — see Amendment.)*

## Roadmap robustness

A separate feature brainstorm was running that could reshape priorities
(it has since concluded — see Amendment; the properties below held). The
plan was built for that:

- Increments 1-6 (package split, config/logging/egress hardening, store +
  eviction, SQLite persistence + shutdown, v2 surface + event bus,
  metadata pipeline) are **feature-agnostic infrastructure** — whatever
  feature wins the brainstorm needs them.
- Every increment is independently shippable, keeps `pytest` + `npm test`
  green, and leaves the tree strictly better if the program stops there.
- Increment 7 (related-content) is the only feature-shaped piece and is
  explicitly re-plannable against the brainstorm outcome.

The full increment ladder, per-PR scope, and test plan live in the
companion plan doc:
[2026-07-01-backend-modernization.md](../plans/2026-07-01-backend-modernization.md).

## Other approaches considered and rejected

- **Queue/worker split with broker (arq/Redis or Postgres), dual
  embedded/distributed modes, S3 artifact store** — rejected by all three
  judges: it forces the runner's closures (over `JobState` containing
  `Lock`/`Queue`) to become picklable IPC, a deep rewrite of the exact hot
  path the tests pin, and it builds horizontal scale for a destination
  (multi-tenant) that the legal/operational research rules out. Kept from
  it: the contract-test pattern (one suite run against every store/bus
  impl) and the dependency rule (if distributed deps ever arrive, they go
  in a new `[server]` extra, never `[ui]`). Stack research confirms no
  job-queue library (arq, SAQ, Dramatiq, Celery, RQ, procrastinate,
  pgqueuer) runs brokerless in a zero-config single process; if a
  Postgres-backed cloud variant ever materializes, **procrastinate** is
  the named upgrade path — future-only, not built now.
- **pydantic-settings / platformdirs** — real new `[ui]` deps +
  PyInstaller hiddenimports risk for what a frozen dataclass + `tomllib`
  + a ~15-line three-branch `paths.py` do fine. (These are the idiomatic
  choices for greenfield apps; the zero-new-deps rule wins here.)
- **sse-starlette** — the hand-rolled SSE generator already implements
  keepalives and snapshot-on-connect, and the frozen v1 wire format is
  test-pinned; adopting a library adds a dep without removing code we're
  allowed to delete. FastAPI ≥0.135's native `Last-Event-ID` header
  support is noted for a future v2 replay design, but snapshot-on-connect
  makes replay unnecessary today.
- **WebSocket transport** — rewrites ~15 frontend tests, gains nothing
  for one-way progress.
- **Per-job SSE keepalive grace window for post-terminal pushes** —
  fragile timer hack; interacts badly with thumb-dir cleanup; the global
  v2 channel is the structural answer. *(Overtaken by events: the shipped
  related-content design uses exactly this linger, bounded at ≤10 s. It
  stays in v1; migrating `url_related` to the v2 channel and deleting the
  linger is optional later polish — see Amendment.)*
- **True mid-download resume across restarts** — yt-dlp fragment state
  isn't checkpointable from the outside; `interrupted` + re-queue is
  honest.
- **Alembic migrations** — operational overkill for end users;
  `PRAGMA user_version` suffices.
- **Serialized single-connection WAL writes instead of a dedicated writer
  thread + queue** (increment 4). An independent reviewer argued the
  writer-thread machinery is bespoke concurrency for what is effectively a
  read-only archive, and that a single serialized WAL connection guarded
  by a lock would be simpler and eliminate the writer-death lost-write
  class outright. Kept as the recorded alternative: the writer-thread
  design stays (it keeps the download hot path off any write lock and is
  the substrate increment 8 depends on), but the serialized variant is the
  fallback if the failure-mode handling above proves fussy. **Recorded
  decision: keep increment 4, minimal** — its two real bugs (memory leak,
  refresh orphans) are fixed by increments 3+5, but 4 is the substrate for
  server-authoritative history, `/reveal` after restart, and the personal
  cloud (8 depends on it).

## Out of scope (separate decisions, not part of this program)

- **Tooling migration (uv, ruff).** Stack research recommends `uv` for
  env/lockfile management and `ruff format`/`ruff check` layered alongside
  (not replacing) the pylint CI gate. Both compose fine with PyInstaller.
  Worthwhile, but orthogonal to backend architecture — propose separately
  so this program's PRs stay reviewable.
- **Frontend v1→v2 client migration.** The React app keeps speaking v1
  indefinitely; adopting v2 endpoints (job list, generated types, global
  channel) happens feature-by-feature on the frontend's own schedule.
  *Recorded open decision (codegen timing):* `v2.ts` has **zero
  importers** until this migration, so the generator + drift gate protect
  nothing on day one. Either defer codegen to the first consumer, or build
  it now to lock the contract early — both defensible. **If built now, the
  committed-file design above is the only variant that doesn't perturb the
  `tests.yml` build order.**
- **Multi-user auth.** The `principal` seam ships disabled; building it
  is explicitly deferred until a real (legal) need exists.

## Trade-offs accepted

- Re-export shims in `__init__.py` are carried indefinitely to protect the
  test contract — mild cruft, decisive migration-risk win.
- Debounced persistence loses sub-transition progress on a hard crash
  (memory-only between state transitions) — acceptable for a local tool.
- Cooperative cancellation stays: a hung pre-progress `extract_info()`
  still pins a worker thread until yt-dlp times out. A hard-kill path
  needs process isolation this design rejects.
- Single process, no `--workers > 1` — by design; the seams (store, bus)
  are where a future cloud variant would diverge, and not before.
- Dual v1/v2 surface is permanent maintenance — the price of never
  breaking a shipped `.app`'s bundled frontend.
- Related-content coverage is bounded by keyless providers (no Spotify /
  Deezer / YT Music) — correctness of posture over completeness of
  catalog.
