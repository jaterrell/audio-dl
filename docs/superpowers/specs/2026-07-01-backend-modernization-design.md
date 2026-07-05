# audio-dl Backend Modernization — Evolve-in-Place, SaaS-Shaped (design spec)

**Status:** draft — planning only; implementation is HELD until the
related-content feature brainstorm concludes (see [Roadmap
robustness](#roadmap-robustness))
**Date:** 2026-07-01
**Owner:** Joe Terrell
**Target release:** v2.3.x program (multiple PRs)

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
related-content feature was designed and planned independently
([design](2026-07-01-related-content-discovery-design.md),
[plan](../plans/2026-07-03-related-content-discovery.md), merged via
PRs #42/#52/#55) — and it chose a **different design** than this spec's
increment 7 / worked example. Reconciliation:

- **Sequencing: related-content ships first, on the current monolith.**
  Its plan is anchored to the monolith's line numbers, needs nothing from
  this program, and is approved and verified. Increments 1–6 then proceed
  as written, absorbing the shipped `audio_dl_ui/related.py` into the
  package split.
- **Increment 7 is superseded.** The shipped feature is yt-dlp-native
  only (YouTube Mix / SoundCloud recommended → cross-platform
  same-artist search), **default ON** with a `--no-related` opt-out, no
  discovery cache, no new endpoints, results in localStorage — not the
  MusicBrainz→ListenBrainz→Odesli chain, not default-OFF, not the v2
  channel. Increment 7 re-scopes to: *re-home the shipped feature into
  the layered package* (see the plan doc's amended increment 7).
- **The per-job SSE linger contradiction is resolved pragmatically.**
  This spec rejected a "per-job SSE keepalive grace window" in favor of
  the v2 global channel; the shipped feature uses exactly that grace
  window (a ≤10 s linger in `_events_iter`). Verdict: the linger ships
  in v1 — it exists, it's tested, and the v2 channel doesn't yet.
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

## Current state (verified 2026-07-01, v2.2.0)

- `audio_dl_ui/__init__.py` — one module holding: 10 routes, `JOBS`
  (module-level dict, in-memory, **never evicted**), `_GLOBAL_EXECUTOR`
  (process-wide `ThreadPoolExecutor`, the only concurrency knob), SSE fan-out
  (`_emit` → per-subscriber bounded `queue.Queue(128)`), CSRF, two thumbnail
  subsystems, macOS dialogs/Finder-reveal, dependency pre-flight, argparse
  entry, and the SPA catch-all.
- Job history lives **client-side** in `localStorage` (`use-history.ts`);
  the server forgets everything on restart, and a page refresh orphans
  in-flight jobs (`tracked-jobs.ts` is in-memory only — the job keeps
  running server-side but the browser loses the `job_id`).
- Metadata captured from yt-dlp is minimal (title/uploader/duration/
  thumbnail); `track`, `artist`, `channel_id`, `tags`, `webpage_url` are
  discarded — a related-content feature has **no data pipeline today**.
- `_run_one` blocks up to **1.5 s per completed download** polling for the
  thumbnail fetch thread (`audio_dl_ui/__init__.py:567-570`).
- No API versioning (bare `/jobs` + inconsistent `/api/*`), no service
  layer, no durable logs (the `.app`'s stderr is invisible), no signal
  handling anywhere, and the SSE event shapes are hand-synced across three
  places (Python dict builders, TS interfaces, the `use-job-events.ts`
  reducer).

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

**Test-contract names are API.** The suite (2,442 lines, 44 classes)
imports or monkeypatches these module-level names; every one stays
importable from `audio_dl_ui` via re-export shims for the whole program —
no renames (specifically **not** `_require_csrf` → anything else; tests
don't patch it, but every route's `Depends()` wiring references it):

`JOBS`, `JobState`, `UrlState`, `_Cancelled`, `_GLOBAL_EXECUTOR`,
`download_media`, `sanitize_url`, `_check_dependencies`, `_run_one`,
`_make_progress_hook`, `_make_url_logger`, `_emit`, `_events_iter`,
`_supervise`, `_build_snapshot`, `_require_csrf`, `_should_keep_log`,
`_pick_thumbnail_url`, `_fetch_thumbnail`, `_persist_thumb`,
`_compute_thumb_id`, `_thumb_dir`, `_cleanup_thumb_dir`,
`_thumb_cache_dir`, `_THUMB_ROOT`, `_THUMB_MAX_BYTES`, `_LOOPBACK_HOSTS`,
`_check_dependencies_gui`, `_show_macos_dialog`, `_selfcheck_problems`,
`_refresh_dev_mode`, `app`, `main`.

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

**Migrations:** `PRAGMA user_version` + ordered migration functions in
`migrations.py` (no Alembic — zero-ops end users). Later increments that
add columns (e.g. related-content metadata) ship a migration; a
fresh-install and an upgraded DB are both tested.

**Restart semantics (honest, not magical):** on startup, jobs that were
non-terminal are marked `interrupted` — a half-downloaded yt-dlp fragment
stream can't resume across a process death. The UI can offer one-click
re-queue; yt-dlp's own `.part` handling resumes what it can.

**Graceful shutdown (new — today there is zero signal handling):** a
uvicorn lifespan shutdown hook plus SIGTERM handler: set a global
draining flag, flip in-flight jobs to `interrupted` in the store *at
shutdown* (not just at next startup), flush the writer queue with a
deadline, and leave `.part` files in place (they enable resume-on-requeue).
Explicit policy: **cancel deletes partials** (user intent: discard);
**crash/shutdown keeps them** (enables resume). Covers both Cmd-Q on the
`.app` and `docker stop` on the personal cloud.

### API surface

- **Legacy surface (frozen forever):** `POST /jobs` (returns exactly
  `{job_id}`), `GET /jobs/{id}/events`, `POST /jobs/{id}/cancel`,
  `GET /jobs/{id}/thumb/{idx}.jpg`, `POST /reveal`, `GET /thumbs/{id}.jpg`,
  `GET /api/version`, `GET /api/settings/defaults`, `GET /api/csrf`, SPA
  catch-all. These are the de-facto v1 the shipped React bundle speaks;
  `routers/legacy.py` keeps them as thin adapters over the service layer.
- **`/api/v2/` (canonical, additive):**
  - `GET /api/v2/jobs?active=1&limit=N` — server-authoritative job list
    (the thing localStorage never gave us).
  - `GET /api/v2/jobs/{id}` — snapshot without opening a stream.
  - `GET /api/v2/events` — **persistent multiplexed SSE channel** (below).
  - `GET /api/v2/jobs/{id}/urls/{idx}/related` — related-content payload.
  - `GET /api/v2/health` — selfcheck-derived readiness (also used by the
    Docker target's healthcheck).
  - All mutations/streams reuse `Depends(_require_csrf)` unchanged.
- **OpenAPI → TS codegen, v2 only:** CI generates
  `web/src/lib/generated/v2.ts` from FastAPI's schema; a backend field
  rename becomes a TS compile error instead of a silent runtime break.
  v1's hand-maintained shapes stay frozen-by-test and are deliberately
  left out of codegen.

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
IPs** (checked post-DNS-resolution). Provider calls are further
restricted to a **host allow-list** (`musicbrainz.org`,
`labs.api.listenbrainz.org`, `api.song.link`) — they never fetch
arbitrary URLs. Thumbnail URLs from yt-dlp info dicts are semi-trusted
and get the full private-IP guard.

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
(python-slim + system ffmpeg, `pip install '.[ui]'`, **no** `[app]` extra)
running the same app with `--persist --host 0.0.0.0 --allow-remote`,
documented as: **must sit behind the operator's own auth**
(Tailscale/reverse-proxy) — never raw-public; BYO cookies mounted
read-only at launch (CLI-side, honoring the credential rule); serverless
explicitly rejected (ffmpeg transcodes exceed Lambda limits). yt-dlp
staleness in a container is handled by an opt-in entrypoint flag
(`AUDIO_DL_UPDATE_YTDLP=1` → `pip install -U yt-dlp` at start), the
standard MeTube-style pattern, so extractor fixes don't require image
rebuilds. For the primary distributions the yt-dlp policy stays what it
is today: unpinned floor for pip installs (users `pip install -U`), and
the `.app` bundles whatever is current at build time — extractor
breakage between releases is fixed by cutting a patch release. A
parallel, non-blocking CI job builds the image; `release.yml` (macOS
`.app`) is untouched.

If off-box durability for the SQLite store is ever wanted on the
personal-cloud target, **Litestream** (continuous WAL streaming to
S3-compatible storage) is the documented option — a sidecar, no code
change, and a better fit than LiteFS for a single-server deploy.

**Remote-deploy CSRF hardening (v2, optional):** the `?token=` query
transport leaks into proxy logs/history/Referer on a remote deploy. When
the app is launched with `--allow-remote`, `GET /` additionally sets the
token as an `HttpOnly; SameSite=Strict` cookie, and CSRF checks accept
cookie+header double-submit — `EventSource` and `<img>` send cookies
automatically, so query-param tokens become unnecessary on the remote
path. Loopback behavior is unchanged.

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

## Out of scope (separate decisions, not part of this program)

- **Tooling migration (uv, ruff).** Stack research recommends `uv` for
  env/lockfile management and `ruff format`/`ruff check` layered alongside
  (not replacing) the pylint CI gate. Both compose fine with PyInstaller.
  Worthwhile, but orthogonal to backend architecture — propose separately
  so this program's PRs stay reviewable.
- **Frontend v1→v2 client migration.** The React app keeps speaking v1
  indefinitely; adopting v2 endpoints (job list, generated types, global
  channel) happens feature-by-feature on the frontend's own schedule.
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
