# Spec — Related-content discovery ("More like this")

**Status:** Approved — merged via #42 (2026-07-02); amendments + verified late-results fix via #52
**Target:** `audio_dl_ui/` package + `web/` React app. **Zero changes to `audio_dl.py` (CLI).**
**Predecessors:** [rich job cards](2026-05-16-rich-job-cards-design.md),
[colorful dual-mode foundation](2026-06-28-web-ui-colorful-dual-mode-foundation-design.md),
[polish & motion](2026-06-28-web-ui-polish-and-motion-design.md)

## Goal

While a download/conversion job runs in the web UI, discover music related to
each submitted track across streaming platforms (YouTube + SoundCloud in v1)
and render it as a horizontal strip of thumbnail tiles — album art / video
still, title, artist, platform label — under the hero stage. Each tile links
to the track's platform page, and a one-click button queues it as a new
download job. When the job finishes, its related items persist onto the
history record so the idle screen ("latest download") keeps showing the strip.

Discovery rides entirely on `yt-dlp` (already the core dependency): no API
keys, no new runtime dependencies, no new HTTP endpoints.

## Decisions & assumptions (resolved autonomously)

This design was produced in a backgrounded session, so clarifying questions
were resolved as explicit, veto-able decisions:

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | Which platforms? | YouTube + SoundCloud in v1, behind a provider seam | The two named in the request; both natively searchable/related-capable through yt-dlp with zero credentials. Spotify/Apple need API keys and can't be downloaded anyway — deferred |
| 2 | Web UI, CLI, or both? | Web UI only | The request specifies thumbnails; the CLI can't render them. `audio_dl.py` is untouched |
| 3 | What counts as "related"? | Platform-native related (YouTube Mix, SoundCloud recommended) first, then same-artist search results on the *other* platform | Native endpoints capture "people also listen to"; cross-platform artist search delivers the "across multiple platforms" ask |
| 4 | Links only, or actionable? | Links + a small "queue this" button per tile | In a downloader, "download this too" is the natural verb; it reuses the existing `postJobs → trackJob` idiom (~10 LOC). Trim if unwanted |
| 5 | Show only during the job? | During download **and** after completion via the latest-history strip on the idle stage; late-arriving results upsert into the already-written history record | The Now screen tears a job down ~1.5 s after completion — a during-only strip would flash and vanish on short tracks. On those same short tracks discovery often finishes *after* completion, so persistence-at-completion alone would miss exactly the case it exists for; the stream lingers briefly and the frontend upserts (see "Late results") |
| 6 | Opt-out? | `--no-related` server flag, default on | Zero-egress escape hatch; no UI setting in v1 |
| 7 | How many items? | Cap 8 per URL — native results get priority, cross-platform fills the remainder | One strip row; no pagination |
| 8 | Discovery egress default, given anonymous-throttling risk? | Default **on**, retained deliberately | Per URL: 2 flat-extract calls + ≤8 small image fetches — the same order as the thumbnail egress the app already generates, bounded by the 2-worker executor. Flip the default only if anonymous throttling is observed harming real downloads (see Privacy & security) |

## Alternatives considered

- **Official platform APIs (rejected).** YouTube Data API removed
  `relatedToVideoId` in 2023; SoundCloud stopped issuing API keys years ago;
  Spotify deprecated its related-artists endpoint for new apps in Nov 2024.
  All would add key management, quotas, and ToS surface for *less* capability
  than yt-dlp already ships.
- **Metadata-service enrichment — MusicBrainz / ListenBrainz / Last.fm
  (deferred).** Richer *similar-artist* semantics, but adds an external
  service dependency, 1 req/s rate limits, extra latency, and patchy artwork.
  The provider seam below (`related.py`) is exactly where this could layer in
  later, resolving similar artists first and then finding their tracks via
  `ytsearch`/`scsearch`.
- **yt-dlp-native discovery (chosen).** Verified against the installed
  yt-dlp 2026.03.17 — see "Verified payload shapes" below.

## Non-goals

- Providers beyond YouTube + SoundCloud (Bandcamp, Spotify link-out, etc.).
- Similarity beyond platform-native related + same-artist search (no
  MusicBrainz graph, no personalization).
- Related strips on the small `AlsoDownloading` pill-cards or `Queue` rows —
  only the hero stage (staged job's first URL) and the idle stage get strips.
- Library-grid integration beyond what history persistence gives for free
  (no "more like this" per library tile in v1).
- CLI flag or terminal output for related content.
- A UI settings toggle (server flag only in v1).
- Retrofitting SSRF hardening onto the *existing* job-thumbnail fetch path
  (observation recorded below; separate concern). New fetches introduced by
  this feature are hardened from day one.
- Thumb-cache eviction policy (pre-existing property of the persistent cache;
  follow-up).

## User-visible behavior

The strip appears under the hero stage once discovery for the staged URL
completes with ≥1 item, entering with the existing `enter-fade` treatment.
There is no loading skeleton — absence is the loading, empty, error, and
unsupported state. It never blocks or delays the download itself.

| Job moment | Strip behavior |
|---|---|
| Queued / resolving | Absent (discovery hasn't started) |
| Downloading (early) | Absent → appears when `url_related` lands (discovery typically finishes in 2–6 s, well inside most downloads) |
| Postprocessing / converting | Visible — this is the "presented during conversion" moment |
| Completed | Job card leaves the Now screen (~1.5 s, existing behavior); items are copied onto the `HistoryItem`, so the idle stage's "latest download" now renders the same strip. If discovery is still in flight at completion (common on short tracks), the late `url_related` upserts into that history record — see "Late results" |
| Failed / cancelled | Strip vanishes with the card; nothing persisted |
| Discovery yields 0 items / errors / unsupported platform (Bunny, unknown) | Strip never appears; no user-facing error |

Tile anatomy (fixed ~132 px wide, horizontal `overflow-x-auto` strip like
`AlsoDownloading`): `AlbumArt` (120 px, served from the persistent
`/thumbs/{id}.jpg` cache, gradient fallback when missing) → title (one line,
truncated) → `Artist · YouTube` line in `--text-3`. The art + text are wrapped in an
`<a href={webpage_url} target="_blank" rel="noopener noreferrer">`; a small
icon button (shared `Button`, `size="icon"`, `variant="ghost"`,
`aria-label="Download {title}"`, `focus-ring`) sits as a **sibling** of the
anchor within the tile container (overlaid on the art corner, never nested
inside the link — nested interactives are invalid), revealed on
hover/focus-visible, and queues the item as a new job in the user's default
format. Section heading:
"More like this".

Multi-URL jobs: the strip shows the staged URL's (`urls[0]`) items, matching
`HeroStage` which only renders `urls[0]`. Discovery still runs for every URL
in the job — each URL's items ride its own `url_related` event and persist to
its own history record.

## Discovery pipeline (backend)

### Trigger and seed

Discovery starts at the same seam that captures title/uploader today: the
first `info_dict`-bearing progress-hook tick in `_make_progress_hook`
(`audio_dl_ui/__init__.py`, the `metadata_emitted` gate). At that moment the
hook assembles a **seed**:

```python
seed = {
    "platform":    detect_platform(info.get("webpage_url") or url_state.sanitized_url or url),
    "id":          info.get("id"),
    "title":       info.get("title"),
    "artist":      first of info["artist"] / info["artists"][0] / info["uploader"] / info["channel"],
    "webpage_url": info.get("webpage_url"),
}
```

Artist strings drop a trailing `" - Topic"` (YouTube auto-generated channels).
If `app.state.related_enabled` is false or `platform` is not
`youtube`/`soundcloud`, the URL's `related_status` is set to `"unsupported"`
silently (no event, strip never shows). Otherwise a discovery task is
submitted to a dedicated executor (below) — never to `_GLOBAL_EXECUTOR`,
which is sized for downloads.

The entire trigger seam — seed assembly, the status flip to `"pending"`,
and `executor.submit` — runs **inside the progress hook, in the hot
download path**, where an uncaught exception would be swallowed by
`_run_one`'s broad handler and fail the *download*. It is therefore wrapped
in its own `try/except`: a trigger failure logs, sets
`related_status = "error"`, and the download proceeds untouched.

For playlist jobs the hook's existing `metadata_emitted` gate means the seed
is the first entry that ticks — same first-entry semantics as today's
title/thumbnail capture.

### Providers

Pure functions in a new `audio_dl_ui/related.py`, each returning normalized
item dicts, all through one mockable seam `_flat_extract(query: str) -> dict`
(a `yt_dlp.YoutubeDL({"extract_flat": True, "skip_download": True,
"playlist_items": "1-10", "socket_timeout": 8, "quiet": True}).extract_info`
call). No credentials are ever attached (the UI has none by design).

| Seed platform | Native related (priority) | Cross-platform (fills remainder) |
|---|---|---|
| youtube | YouTube Mix: `https://www.youtube.com/watch?v={id}&list=RD{id}` — platform-curated radio for the seed; **first entry is the seed itself, excluded** | `scsearch8:{artist}` |
| soundcloud | `{webpage_url}/recommended` (SoundcloudRelatedIE) | `ytsearch8:{artist}` |
| bunnystream / unknown | — (status `"unsupported"`) | — |

Selection rules, in order: normalize each entry → drop the seed (same
platform + id) → drop entries with no usable title → dedupe by
`(platform, id)` → allocate 8 slots: native results first, capped at 5 while
cross-platform results exist to fill the rest; when one side is short, empty,
or skipped, the other may fill all 8. If `artist` is unresolvable, the
cross-platform search is skipped entirely. The two provider calls run
sequentially inside one task per URL; each carries an 8 s socket timeout.
Note `socket_timeout` caps individual socket operations, not total
extraction wall time — yt-dlp may retry internally, so a single provider
call can exceed 8 s. The task then fetches up to 8 thumbnails sequentially
(5 s timeout each — see "Thumbnails"); a 15 s budget on the thumbnail phase
(stop fetching once exceeded; remaining items keep `thumb_id: null`) is the
one hard, enforced bound. Together these make ~30 s the *typical* worst
case, not a guarantee. A task-level watchdog is deliberately omitted: an
overrun is contained to the 2-worker discovery executor and can never
affect downloads or the 10 s SSE linger cap, which is enforced
independently. One provider failing or timing out just means the other's
results stand alone.

### Verified payload shapes

Live-probed against yt-dlp 2026.03.17 (2026-07-01):

- **YouTube Mix flat entries:** `id`, `title`, `uploader`/`channel`,
  `duration` (float secs), `url` (watch URL), `thumbnails[]`
  (`i.ytimg.com/vi/{id}/hqdefault.jpg`, 480 px ≤ largest). Seed appears as
  entry 1. Mix playlists occasionally don't exist for obscure videos → empty
  entries, handled as "fewer/zero native items".
- **`ytsearch` flat entries:** same shape + `view_count`.
- **`scsearch` flat entries:** `id`, `title`, `uploader`, `artists[]`,
  `duration`, `webpage_url` (human permalink — the `url` field is an API URL,
  do not use it for linking), `thumbnails[]` (10 `sndcdn.com` size variants).
- **SoundCloud `/recommended`:** extractor verified present
  (`SoundcloudRelatedIE`, pattern `…/(albums|sets|recommended)`); entry shape
  expected to match `scsearch` entries (same extractor family). ☐ **Gating
  pre-requisite:** the probe of this URL form was not completed — the
  implementation must live-probe `/recommended` and capture the fixture
  *before* enabling the SoundCloud native path. If the shape doesn't pan
  out, SoundCloud seeds ship cross-platform-only (`ytsearch8:{artist}` may
  fill all 8 slots — the selection rules already allow it) and the native
  path moves to the follow-ups list.

Normalized item (wire + state shape):

```jsonc
{ "title":       "One More Time",
  "artist":      "Daft Punk",          // artists[0] → uploader → channel fallback chain
  "platform":    "youtube",            // "youtube" | "soundcloud"
  "webpage_url": "https://www.youtube.com/watch?v=FGBhQbmPwH8",
  "duration":    322,                  // int seconds | null
  "thumb_id":    "3f2a…40-hex" }       // persistent thumb cache key | null
```

### Thumbnails

Related-item art reuses the **persistent content-addressed thumb cache**
(`_thumb_cache_dir()`, `GET /thumbs/{40-hex}.jpg`, 1-year immutable cache) —
the same store the Library uses — so `AlbumArt` renders items unchanged and
art survives job teardown. No new endpoint, no Vite proxy change.

Inside the discovery task, after selection: pick each item's source URL with
the existing `_pick_thumbnail_url` semantics (largest ≤480 px), then fetch
with a **hardened** variant of the existing atomic tmp-file+rename fetch:

- `https` scheme only;
- host allowlist per provider: `i.ytimg.com`, `*.sndcdn.com`
  (subdomain-safe suffix matching, same spirit as `_host_matches`);
- `follow_redirects=False` — a redirect counts as a failed fetch. The
  pre-existing fetch follows redirects, which would let an allowlisted host
  302 straight past the allowlist; CDN thumb URLs are direct, so refusing
  redirects costs nothing;
- existing 5 MB size cap and 5 s per-fetch timeout; no retries; the
  thumbnail phase as a whole carries the 15 s budget noted above.

Failures leave `thumb_id: null` → gradient fallback tile. Only after thumbs
resolve does the single `url_related` event fire, so tiles never pop in art
later. (Observation, out of scope: the *pre-existing* job-thumbnail fetch has
no scheme/host validation; worth a separate hardening pass.)

Cache growth: up to 8 extra small images (~10–50 KB each) per downloaded URL.
The cache is already unbounded today; eviction stays a follow-up.

### Concurrency, cancellation, failure isolation

- Module-global `_RELATED_EXECUTOR = ThreadPoolExecutor(max_workers=2,
  thread_name_prefix="related")`, lazily created like `_GLOBAL_EXECUTOR`'s
  pytest fallback. Two workers bound total discovery egress regardless of
  batch size and keep download workers unaffected.
- The task checks `job.cancelled` before starting and again before
  emitting, and also checks its seed URL's download status before emitting:
  if the job was cancelled or that URL's download failed or was cancelled,
  the result is dropped silently and `related_status` set to `"none"` — no
  strip for failed downloads, no linger stall, and no exit path that leaves
  a URL stuck at `"pending"`.
- Everything is wrapped so no exception can propagate into job state: any
  unexpected failure → `related_status = "error"`, no strip, log line only.
- If the job completes before discovery, the SSE stream lingers briefly so
  the result still reaches connected clients and the frontend upserts it
  into history — see "Late results" below and the error table. Past the
  linger cap, the emit is a no-op to a drained subscriber list; state still
  records the result.

## Backend data shape

### `UrlState` (extended)

```python
related_status: str | None = None
# None       — never started: disabled, or the URL never reached its first
#              metadata tick (failed while resolving)
# "pending"  — discovery task submitted, result not yet resolved
# "ready" | "none" | "error" | "unsupported" — resolved outcomes
related_items: list[dict] = field(default_factory=list)
# normalized items, shape above, only when status == "ready"
```

The hook sets `"pending"` at the moment it submits the discovery task, so
"in-flight" is always distinguishable from "never started" — the SSE linger
(completed URLs only) and the client's connection-lifetime logic both key
on `"pending"`, never on `None`. Every task exit path (success, empty,
error, download-failure suppression, cancellation) moves the status off
`"pending"`.

`JobState` is untouched. Items are per-URL because relatedness is seeded per
track and every existing SSE event is keyed by the raw `url` string.

### SSE protocol additions

One new event, fired **at most once per URL** for supported platforms:

```jsonc
{ "type": "url_related",
  "job_id": "…",
  "url": "https://…",            // raw URL string key, like every other event
  "status": "ready",             // "ready" | "none" | "error"
  "items": [ { …normalized item… } ] }   // [] unless "ready"
```

One existing event is extended: `url_metadata` (both of its up-to-two
emissions) gains a `related_status` field carrying the URL's status *at
emission time* — typically `null`, `"pending"`, or `"unsupported"`; the
second emission may rarely carry an already-resolved value if discovery
beat the thumbnail fetch. Additive and backwards-compatible — the same
precedent as `progress` gaining `phase` in the rich-cards release. This is
what lets a live client observe discovery entering flight ("Late results"
below).

- `_build_snapshot` per-URL entries gain `related_status` + `related_items`
  so late subscribers reconstruct the strip (snapshot-on-connect protocol,
  no replay log).
- `url_related` joins the guaranteed-delivery set — it is a one-shot state
  transition that must not be silently dropped on a full queue. Targeted
  improvement while there: rename `_TERMINAL_EVENT_TYPES` →
  `_GUARANTEED_EVENT_TYPES` (one definition, one use) since "terminal" no
  longer describes its contents.
- `"unsupported"`/disabled produce **no event**; the field still appears in
  snapshots for state completeness.

### Late results — completion beats discovery

On short tracks the download+ffmpeg pipeline can finish before the 2–6 s
discovery task does — which, uncorrected, would lose exactly the case
history persistence exists for: `_events_iter` closes the stream right
after `job_completed`, a later `url_related` would fan out to a drained
subscriber list, and the `HistoryItem` would be written without `related`.
Two small accommodations close the gap:

- **Backend linger:** after emitting `job_completed`, `_events_iter` keeps
  the connection open while any URL whose download **completed** has
  `related_status == "pending"` (explicitly not `None` — a URL that failed
  before its first metadata tick never started discovery and must not stall
  the close; and a failed/cancelled download's still-in-flight discovery
  must not stall it either — its result is suppressed, see the concurrency
  bullets), capped at 10 s and ended early if the job is cancelled,
  forwarding the late `url_related` event(s) before closing. Jobs with
  nothing pending close immediately, as today.
- **`"pending"` is made observable client-side:** the existing
  `url_metadata` event gains a `related_status` field (see SSE section) —
  it already fires on the same hook tick where the discovery task is
  submitted, so a live client sees each URL enter `"pending"` (or
  `"unsupported"`/`null`) as it happens. Without this the client could
  never distinguish "discovery in flight" from "nothing to wait for":
  `url_related` only carries resolved statuses, and a client connected from
  job start never receives another snapshot.
- **Client-side connection ownership (relocated close):** today
  `useJobEvents.onmessage` closes the EventSource permanently the moment
  the *derived* job state turns terminal — which happens on the final
  `url_completed`, before `job_completed` even arrives — and `onerror`
  does the same. An explicit `close()` never auto-reconnects, so without
  change the linger would stream into a socket the client already hung up.
  That close **moves**: the hook maintains a `pendingRelated` set in a ref
  (URLs added on `related_status: "pending"`, removed on any resolved
  status; failed/cancelled URLs dropped at terminal-derive time). On
  terminal: if the set is empty, close immediately — the common long-track
  case behaves exactly as today. Otherwise keep the socket open, drain the
  set as `url_related` events arrive, and close (client-initiated, silent)
  when it empties or at the hook's own 10 s cap. A `sawTerminal` ref —
  deliberately independent of the react-query record, which the 1.5 s
  teardown deletes — makes any `onerror` after terminal a silent,
  permanent close: no "Lost connection" toast, no reconnect attempt. That
  covers the race where the server finishes its linger and closes first.
- **Frontend upsert:** the `url_related` branch in `applyEvent` runs
  **before** the missing-snapshot early-return (`if (!prev) return`) — by
  the time a late event arrives, the job's query record has usually already
  been removed by the 1.5 s teardown. Routing — both actions, not
  either/or: **(1)** if the query record still exists (terminal or not),
  patch it, so a history write that hasn't happened yet picks the items up
  from the snapshot; **(2)** if the record is terminal or missing,
  *additionally* upsert the items onto the matching `HistoryItem` via
  `updateItem` (see the frontend section). Both actions are idempotent
  (same content), and together they close the ordering race where SSE
  messages arrive back-to-back — `url_completed` (state turns terminal)
  then `url_related` — before React has flushed `JobTracker`'s
  terminal-state effect that writes the history row: the cache patch feeds
  the pending history write, while `updateItem` covers rows already
  written. `updateItem` alone would no-op in that window and drop the
  items. The 1.5 s visual teardown is unchanged.

Past the cap (pathological provider stall) the result is dropped for that
run — the accepted race shrinks from "any short track" to "discovery slower
than completion + 10 s".

*Rejected simpler alternative:* keep the terminal close as-is and have the
client open a one-shot "probe" EventSource ~10 s after completion to read
the snapshot (which carries resolved related state) and upsert from it.
Zero backend change, but it needs the same pending-observability and
toast-suppression work, always delivers a fixed 10 s late instead of
as-ready, and adds a second connection lifecycle to reason about — not
actually simpler where it counts.

### Module layout

New submodule `audio_dl_ui/related.py` (~150 LOC): `normalize_entry`,
`build_native_query`, `build_search_query`, `resolve_artist`,
`select_items` (dedupe/exclude-seed/cap), `discover(seed) -> (status, items)`
orchestration, `_flat_extract` seam, thumb-host allowlist. Pure logic only —
no FastAPI, no `JobState`, no emitting — so it's directly unit-testable and
safely importable.

Integration glue (~100 LOC) stays in `audio_dl_ui/__init__.py`: hook trigger,
executor, thumb fetch/persist (reuses `_compute_thumb_id`, `_persist_thumb`
machinery), `_emit`, snapshot fields, `--no-related` argparse →
`app.state.related_enabled`.

On the "no third module without a clear case" convention: `audio_dl_ui` is
already a package (the convention's "sibling file" description predates the
v2.0 React rewrite); `related.py` is a submodule inside it, mirroring how
`web/` splits components, and keeps 1249-line `__init__.py` from absorbing
another ~250 lines of separable pure logic.

## Frontend

### Types & event handling

- `web/src/lib/types.ts`: add `RelatedItem` (mirror of the normalized item);
  `UrlState` gains `related_status?: string | null` and
  `related?: RelatedItem[]`; `HistoryItem` gains `related?: RelatedItem[]`.
- `web/src/hooks/use-job-events.ts`: add `UrlRelatedEvent` to the `AnyEvent`
  union; new `applyEvent` branch patches the matching URL (same
  `u.url === e.url` idiom); the `url_metadata` handler additionally patches
  the new `related_status` field; `job_snapshot` mapping carries the new
  fields. The `url_related` branch is evaluated ahead of the
  missing-snapshot early-return; it patches the query record whenever it
  still exists and *additionally* routes to the history upsert when the
  record is terminal or missing — both, not either/or, per the ordering
  race in "Late results" above. This hook also owns
  the entire connection-lifetime change: the terminal `es.close()` in
  `onmessage` is replaced by the `pendingRelated`-set logic (close
  immediately when empty, else drain-or-10 s-cap), and `onerror` consults
  the `sawTerminal` ref instead of the query record so post-terminal
  errors close silently with no toast. Unknown-event fallthrough keeps
  older backends harmless.
- `web/src/hooks/use-history.ts`: `useHistory` gains
  `updateItem(url, patch)` — patches the newest record matching `url`,
  no-op when none matches, and notifies subscribers so an already-mounted
  `EmptyStage` strip appears in place when the upsert lands.
- `web/src/components/job-tracker.tsx`: when a job goes `completed`, copy
  each URL's `related` onto the `HistoryItem` it writes (≤8 items ≈ ≤1.5 KB
  per record; 100-record cap ⇒ ≤ ~150 KB worst case in localStorage). The
  1.5 s teardown still removes the job query on schedule (the card leaves
  the Now screen unchanged), but when the just-read terminal snapshot shows
  any URL still `"pending"`, the tracker schedules `untrackJob` — which
  unmounts the hook — at a flat 10 s instead of 1.5 s. No early-exit
  drain: the tracker has no channel to observe event arrivals (the hook
  owns the socket and late events route to history, not the query cache),
  and a headless component lingering a few extra seconds costs nothing.
  The hook has typically already closed its own socket by then.

### `RelatedStrip` component

`web/src/components/related-strip.tsx` (~90 LOC):
`RelatedStrip({ items }: { items: RelatedItem[] })` → `null` when empty,
else `<section aria-label="Related music">` with "More like this" heading and
the `AlsoDownloading`-style `flex gap-2 overflow-x-auto` row. Tiles keyed
`${platform}-${id-or-url}`. Theme-correctness rules followed exactly: only
`var(--surface/--border/--text*/--accent/--on-accent/--radius-*)` tokens,
shared `Button` for the queue action, `focus-ring` on all interactives,
`enter-fade` for entrance (already covered by the reduced-motion guard block
— no new keyframes). `AlbumArt` used as-is with `thumbId` + `size={120}`.

Queue action: `postJobs([{ url: item.webpage_url, format:
settings.default_format }])` then `trackJob(job_id)` — the exact
`LibraryTileMenu.handleReDownload` idiom; the new job appears in the Queue
strip as organic feedback, errors surface via the existing toast store.
Server-side, the submitted URL flows through the normal `sanitize_url` path
like any user-pasted URL — the server never fetches client-supplied URLs for
this feature.

### Mount points

- `web/src/routes/index.tsx`: below `HeroStage`, inside the existing
  stage-keyed `enter-fade` wrapper:
  `<RelatedStrip items={stageJob.urls[0].related ?? []} />`.
- `web/src/components/empty-stage.tsx`: below the latest-item display:
  `<RelatedStrip items={latest?.related ?? []} />`. Old history records
  simply lack the field → no strip, no migration needed.

## Error handling

| Condition | Behavior |
|---|---|
| Artist unresolvable | Skip cross-platform search; native results only |
| Native related empty/unavailable (no Mix for video) | Cross-platform results only |
| One provider times out / errors | Other provider's results stand; status still `"ready"` if ≥1 item |
| Both providers fail | `status: "error"`, no event items, strip absent, log line only |
| Zero items after filtering | `status: "none"`, strip absent |
| Unsupported platform / `--no-related` | `related_status: "unsupported"` / stays `None`; no event, no strip |
| Thumb fetch fails / disallowed host | `thumb_id: null` → gradient fallback tile |
| Job cancelled mid-discovery | Results dropped before emit; nothing persisted |
| Download fails/cancels after discovery was seeded | Result suppressed (no emit), `related_status: "none"`; the failed URL neither stalls the linger nor surfaces a strip |
| Job completes before discovery finishes | Stream lingers (≤10 s, completed-URLs-only predicate) and the client keeps its socket open on the same condition, so the late `url_related` is delivered and upserted onto the already-written history record — the idle-stage strip still appears. Past the cap: dropped for that run; history record has no `related` |
| Server closes the lingered stream before the client's cap | `onerror` sees `sawTerminal` → silent permanent close; no "Lost connection" toast, no reconnect |
| SSE queue full | `url_related` uses the guaranteed-delivery path (blocking put w/ timeout) |
| yt-dlp extractor drift (Mix/`recommended` shape changes) | Caught by the catch-all → `"error"`; downloads unaffected |
| Discovery exception of any kind | Never propagates to the download worker or job status |

## Privacy & security

- Discovery sends artist/track search queries to YouTube/SoundCloud
  anonymously — same trust class as the existing thumbnail fetches; no
  cookies or auth ever attached (UI has none by design). `--no-related`
  disables all discovery egress.
- **Rate-limiting trade-off (named deliberately):** the extra anonymous
  Mix/`ytsearch`/`scsearch` egress rides the same IP the downloads use, and
  YouTube throttles unauthenticated metadata traffic aggressively — in the
  worst case discovery could accelerate IP-level 429s/CAPTCHAs that hurt
  the *real* downloads. Volume is small and bounded (decision #8: 2
  flat-extract calls + ≤8 thumbnail fetches per URL, 2 workers total), so
  the default stays **on**; `--no-related` is the kill switch, and the
  default flips to off if throttling harm is observed in practice.
- New outbound image fetches are https-only against a per-provider host
  allowlist with the existing 5 MB cap; IDs served to the browser are opaque
  40-hex SHA-1 keys via the existing validated `/thumbs/` route. No
  client-supplied URL is ever fetched server-side by this feature.
- No new endpoints, no CSRF surface change.

## Testing

Backend — new `test_audio_dl_related.py` (pure, no network):
parametrized tests for `resolve_artist` (artist/artists/uploader/channel
chain, `" - Topic"` strip), `build_native_query` per platform,
`select_items` (seed exclusion incl. Mix-echoes-seed, dedupe, cap, native/
cross interleave), `normalize_entry` against **fixtures captured from the
live probes** (Mix, ytsearch, scsearch shapes; the `/recommended` fixture
is the gating pre-requisite from "Verified payload shapes"), thumb-host allowlist
(`i.ytimg.com` ✓, `evil-i.ytimg.com.evil.test` ✗, http ✗), and
`discover()` with `_flat_extract` monkeypatched (one-provider-fails,
both-fail, empty, budget).

Backend — additions to `test_audio_dl_ui.py` (existing patterns:
`TestClient`, monkeypatched `download_media` driving real hooks, mocked
httpx): first info-dict tick submits exactly one discovery task per URL
(gate respected); `url_related` SSE event shape on the stream; snapshot
carries `related_status`/`related_items` for late subscribers; `--no-related`
/ unsupported platform → no task, no event; cancelled job → no emit; a URL
whose download failed after discovery was seeded → no emit, status
`"none"`, no linger stall; discovery exception (including one thrown from
the in-hook trigger seam) → job still completes normally; `url_metadata`
carries `related_status`; `url_related` is not dropped when a subscriber
queue is full (guaranteed-delivery path, mirroring the existing
terminal-event overflow coverage); stream lingers after `job_completed`
while any **completed** URL's `related_status` is `"pending"` — with the
negative assertions that a URL left at `None` and a failed URL left
in-flight do **not** stall the close — forwards the late `url_related`,
closes at the 10 s cap, and closes immediately when nothing is pending.

Frontend — `use-job-events.test.tsx` MockEventSource template: `url_related`
merges into the right URL; `url_metadata` patches `related_status`;
snapshot round-trip. Connection-lifetime cases: terminal with empty
`pendingRelated` → socket closed immediately (today's behavior preserved);
terminal with a pending URL → socket stays open, the late `url_related`
drains the set and closes it silently; the hook's 10 s cap closes it when
nothing arrives; a server-initiated close after `sawTerminal` produces no
"Lost connection" toast; a late `url_related` upserts via `updateItem`
even when the query record was already removed (must not hit the
missing-snapshot early-return); and the back-to-back race — apply
`url_completed` (terminal) then `url_related` synchronously, *then* run
the tracker's terminal effect — still yields a history row carrying the
items (the cache patch fed the pending write). New `related-strip.test.tsx` (renderUI +
local fixtures): renders N tiles, empty → null, queue button calls mocked
`postJobs`+`trackJob` (`vi.mock("@/lib/api")` — MSW floor errors on
unhandled requests), links use `target="_blank" rel="noopener noreferrer"`.
`job-tracker` test: completed job copies `related` into history record;
with a URL still `"pending"` at terminal, `untrackJob` fires at 10 s
instead of 1.5 s (and `removeQueries` still at 1.5 s). `use-history` test:
`updateItem` patches the newest matching record, no-ops when none match,
notifies subscribers.

## Size impact

Backend ~250 LOC (`related.py` ~150 + glue ~100), frontend ~200 LOC,
tests ~400 LOC. `__init__.py` stays ~1350 lines; no new dependencies; no new
endpoints.

## Versioning & docs

Implementation PR bumps `__version__` + `pyproject.toml` to **v2.5.0**, adds
`## v2.5` to `CHANGELOG.md` (amended 2026-07-05: originally v2.3.0, then
briefly v2.4.0 — but v2.3.0 shipped 2026-07-03 as the landing-page/CSRF
release and v2.4.0 shipped as the auto-shutdown release (#56), so this
feature is the next open slot, v2.5.0), updates
CLAUDE.md's layout section (mention
`audio_dl_ui/related.py`, add this spec to the deep-dive links — noting the
section's description of the UI internals predates the React rewrite and
deserves its own refresh separately), and follows the standard flow: spec/plan
docs to `origin/main`, implementation-only PR, squash-merge, `reset --hard`.

## Open follow-ups (out of scope)

- More providers behind the same seam: Bandcamp search, Spotify/Apple
  link-out tiles (display-only), MusicBrainz/ListenBrainz similar-artist
  layer feeding the existing search providers.
- Library-grid "more like this" (data already persisted on `HistoryItem`).
- Thumb-cache eviction (pre-existing growth property, now mildly accelerated).
- UI settings toggle mirroring `--no-related`.
- Strips for non-staged URLs in multi-URL batches.
- SSRF hardening for the pre-existing job-thumbnail fetch path.
