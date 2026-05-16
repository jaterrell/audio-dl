# Spec — Rich job cards (live feedback per URL)

**Status:** Design approved 2026-05-16
**Target file:** `audio_dl_ui.py` (web UI, no CLI changes)
**Predecessor:** v1.5 console UI ([2026-05-14-console-ui-themes.md](2026-05-14-console-ui-themes.md))
**Follow-ups deferred:** v1.8 per-theme card structural variations.

## Goal

Replace the running-job row list with a **vertical stack of full-width cards**, one per URL, each surfacing live download feedback in four dimensions:

1. **Speed / ETA / bytes** — bytes/sec, ETA countdown, downloaded/total.
2. **Track metadata** — title, uploader, duration (replaces bare URL once known).
3. **Thumbnail preview** — proxied through the FastAPI app, not loaded cross-origin.
4. **Filtered log tail** — last 3 of the last 50 yt-dlp log lines per URL, filtered to useful phases.

A user with multiple URLs running sees a column of self-contained cards, each one explaining its own state — what's downloading, how fast, what's about to happen — without needing a detail-pane click.

## Non-goals

- Per-theme card structural variations (deferred to v1.8).
- Expanding the log tail beyond 3 visible lines / "show more" UI.
- Persisting cards across browser refreshes beyond what the SSE snapshot already replays.
- Mobile / narrow-viewport responsive treatment.
- Aggregate-across-cards stats (total speed, queue ETA).

## User-visible behavior

Cards have six lifecycle states. Visual treatment is theme-driven (cards inherit theme color/typography vars), so the description below is structural.

| State | Thumb | Title row | Progress row | Log tail | Notes |
|---|---|---|---|---|---|
| `queued` | placeholder | raw URL | hidden | hidden | "queued" badge |
| `resolving` | placeholder | raw URL | hidden | hidden | animated "resolving…" badge |
| `downloading` | real (or placeholder if fetch failed) | title · uploader · duration | progress bar + `speed · ETA · bytes` | last 3 of last 50 | live ticks |
| `postprocessing` | real | title · uploader · duration | "extracting audio" / "embedding thumbnail" line | last 3 | speed/ETA hidden |
| `complete` | real | title · uploader · duration | "saved · {size}" + reveal-in-Finder click | last 3 | `[OK]` badge; card stays open |
| `failed` | real if obtained, placeholder otherwise | title or URL | "failed" | last 3, error lines highlighted | `[xx]` badge; card stays open |

Cards stack vertically full-width; viewport scrolls when many. No grid layout — readability over density at typical 1–5 URL counts.

## Backend data shape

### `UrlState` (extended)

Existing fields (preserved): `url`, `status`, `percent`, `paths`.

New fields, all default to `None` until known:

```python
# metadata — set once on first info-dict tick
title: str | None
uploader: str | None
duration: int | None         # seconds
thumbnail_ready: bool        # True once /jobs/{id}/thumb/{idx} will serve

# live progress — updated every progress-hook tick
phase: str | None            # "resolving" | "downloading" | "postprocessing" | "complete" | "failed"
speed: float | None          # bytes/sec
eta: int | None              # seconds
downloaded_bytes: int | None
total_bytes: int | None      # falls back to total_bytes_estimate

# log ring — bounded server-side
log: collections.deque[dict] # maxlen=50; entries {ts: float, level: str, text: str}
```

`thumbnail_ready` is a boolean. The file lives at a known on-disk path served by the proxy endpoint; the URL never travels in the SSE payload.

## SSE protocol additions

Three events. One is brand new (`url_log`), one is sticky-one-shot (`url_metadata`), one is an additive extension of an existing event (`url_progress`).

### Extended `url_progress`

```jsonc
{ "type": "url_progress",
  "url_idx": 1,
  "percent": 30.0,            // existing
  "phase": "downloading",     // new
  "speed": 3250000,           // new — bytes/sec
  "eta": 8,                   // new — seconds
  "downloaded_bytes": 14700000,  // new
  "total_bytes": 47000000 }   // new — uses total_bytes_estimate fallback
```

Backwards-compatible: existing consumers ignore unknown fields.

### New `url_metadata` — one-shot per URL

Fired when yt-dlp's info dict is first available for a URL, and again with `thumbnail_ready: true` once the proxy has the thumb on disk (or once with `thumbnail_ready: false` if fetch fails).

```jsonc
{ "type": "url_metadata",
  "url_idx": 1,
  "title": "Wandered into the Day",
  "uploader": "Geotic",
  "duration": 251,
  "thumbnail_ready": true }
```

May fire **up to twice** per URL: once on metadata-known with `thumbnail_ready: false`, once on thumb-fetched with `thumbnail_ready: true`. UI is idempotent — last value wins.

### New `url_log`

```jsonc
{ "type": "url_log",
  "url_idx": 1,
  "level": "info",            // "info" | "warning" | "error"
  "text": "[hls] downloading fragment 12/45",
  "ts": 1715855412.3 }
```

Only filter-passing lines reach this event (see "Logger capture + filtering" below).

### `job_snapshot` extension

Late-connect subscribers must catch up. Per-URL snapshot entries gain all the sticky fields above plus `log` (full 50-line ring). Existing snapshot fields preserved.

## Thumbnail proxy

### Fetcher

On first `url_metadata` emission, server dispatches a fetch task to a small thread pool (reuse the existing job executor — these are cheap I/O):

1. Pick from `info_dict["thumbnails"]` (list of `{url, width, height, ...}`), preferring `width ≤ 480`. Fall back to `info_dict["thumbnail"]` (single URL) if list absent. If neither, skip.
2. `httpx.get(url, timeout=5)`. On non-200, exception, or timeout: skip. No retries.
3. Write to `{TMPDIR}/audio-dl-thumbs/{job_id}/{url_idx}.jpg`. Atomic write (tmp + rename).
4. Emit `url_metadata` with `thumbnail_ready: true`.

On failure path: emit `url_metadata` with `thumbnail_ready: false`. UI shows placeholder; no user-facing error.

### Endpoint

`GET /jobs/{job_id}/thumb/{url_idx}` — CSRF-guarded via the existing `_require_csrf` (`?token=...` query param since `<img>` can't send custom headers).

Behavior:
- File exists → return it (`Content-Type: image/jpeg`).
- Job unknown, url_idx out of range, or file missing → `404`.
- Bad / missing token → `403` via `_require_csrf`.

### Cleanup

Per-job thumb dir removed when:
1. Job state is fully complete (all URLs done/failed/cancelled), AND
2. Last SSE subscriber has disconnected.

Worst case (process crash) leaves orphans in `$TMPDIR` — OS handles eventual cleanup. Disk footprint is trivial (10–50KB per URL).

## Logger capture + filtering

### Logger seam

`download_media` already accepts `progress_hooks`. Extend `_build_ydl_opts` to also wire a `logger=` arg from a new pure factory:

```python
def _make_url_logger(job: JobState, url_state: UrlState) -> _YDLLogger:
    """Returns a yt-dlp-compatible logger that routes filtered lines into the URL's log deque + emits url_log SSE events."""
```

`_YDLLogger` implements `.debug(msg)`, `.info(msg)`, `.warning(msg)`, `.error(msg)` — the four methods yt-dlp invokes. Each:

1. Calls `_should_keep_log(level, text)`.
2. If kept: append `{ts, level, text}` to `url_state.log` (bounded by deque maxlen), call `_emit(job, {type:"url_log", ...})`.
3. Never raises (coerces non-string args via `str(...)`).

### Filter

```python
def _should_keep_log(level: str, text: str) -> bool: ...
```

Pure function. Rules:

- **Always keep** `warning` and `error`.
- **For `info`** — keep lines containing any of:
  - `[hls] downloading fragment`
  - `[ffmpeg]` (merging, metadata, adding thumbnail, etc.)
  - `[ExtractAudio]`
  - `[EmbedThumbnail]`
  - `[Metadata]`
- **Drop everything else** at `info` level, and drop all `debug` lines unconditionally.

This filter is the test surface that matters most — covered by a parametrized table test.

### Routing

The logger has captured references to `job` and `url_state`, so each log line is correctly attributed to its URL without yt-dlp needing to know about it. A fresh logger is constructed inside `_run_one` before yt-dlp invocation.

## Phase transitions

`phase` is set server-side at these explicit points (not derived client-side):

| Transition | Trigger |
|---|---|
| `None → "resolving"` | First line of `_run_one` for a URL, before any yt-dlp call |
| `"resolving" → "downloading"` | First `progress_hooks` tick with `status: "downloading"` |
| `"downloading" → "postprocessing"` | `progress_hooks` tick with `status: "finished"` (yt-dlp's "download done, postproc next" signal) |
| `"postprocessing" → "complete"` | `_run_one` returns successfully; final paths recorded |
| any `→ "failed"` | `_run_one` raises or yt-dlp signals an error |

Each transition emits a `url_progress` event so the UI updates promptly.

## UI rendering

### HTML structure (replaces row template)

```html
<article class="card" data-state="downloading">
  <div class="card-thumb">
    <img src="/jobs/{job_id}/thumb/{idx}?token=..." alt="" />
    <!-- placeholder div when thumbnail_ready is false -->
  </div>
  <div class="card-body">
    <header class="card-head">
      <span class="card-title">Wandered into the Day</span>
      <span class="card-meta">Geotic · 4:11</span>
      <span class="card-badge">[..]</span>
    </header>
    <div class="card-progress">
      <div class="card-bar"><span style="width:30%"></span></div>
      <div class="card-stats">3.1MB/s · ETA 0:08 · 14/47MB</div>
    </div>
    <ul class="card-log">
      <li class="card-log-line">[hls] downloading fragment 12/45</li>
      <li class="card-log-line">[ffmpeg] embedding thumbnail</li>
      <li class="card-log-line">…</li>
    </ul>
  </div>
</article>
```

`data-state` drives CSS show/hide of progress + log + thumb-placeholder.

### CSS impact

- `_INDEX_CSS_BASE` gains a `.card` block (~80 lines): grid layout, badge styling, thumb sizing (120×68 16:9), log line styling, state-driven `display`.
- All colors go through existing CSS vars (`--bg`, `--fg`, `--frame`, `--accent`, `--ok`, `--err`, `--warn`, `--dim`). No new vars.
- `_INDEX_CSS_THEMES` is **not modified** in this release — cards inherit theme color/typography automatically.

### JS impact

- `_INDEX_JS` gains:
  - Event handlers for `url_metadata` and `url_log` (currently only `url_progress` exists in the new shape).
  - `url_progress` handler extended to read the new fields and re-render speed/ETA/bytes.
  - Card-rendering helper that materializes the markup given URL state (used by snapshot replay + every event).
  - Thumbnail token construction (`?token=${TOKEN}` appended to thumb URLs).

### Theme override touch-point (now)

None. Cards use only existing vars. Per-theme structural card overrides are the obvious v1.8 motion.

## Error handling

| Condition | Behavior |
|---|---|
| Thumbnail fetch HTTP non-200 / timeout | `thumbnail_ready: false`, placeholder rendered, no user message |
| Logger receives non-string | `str(...)` coerce, never raises |
| Info dict missing `title` | Fall back to URL in card title |
| Info dict missing `uploader` / `duration` | Render as `—` |
| Speed/ETA missing on a tick | Keep last known value (don't flicker to `—`) |
| Job cancelled mid-thumb-fetch | Fetcher checks `job.cancelled`, drops bytes, doesn't write file |
| Thumb endpoint hit with bad token | 403 via `_require_csrf` |
| Thumb endpoint hit before ready | 404 |

## Testing

Additions to [test_audio_dl_ui.py](../../../test_audio_dl_ui.py):

1. **`_should_keep_log`** — parametrized table of `(level, text, expected_keep)` covering each rule branch.
2. **`_pick_thumbnail_url`** — given various `thumbnails` list shapes (including missing widths, single-URL fallback, empty), picks correctly.
3. **`_make_url_logger`** — each of `.debug/.info/.warning/.error` routes to the right level, applies the filter, and emits `url_log` with the right `url_idx`.
4. **Progress hook integration** — feed a fake hook tick with all the new fields (`speed`, `eta`, `downloaded_bytes`, `total_bytes`); assert SSE emits `url_progress` with them.
5. **Metadata event** — feed an info-dict-bearing hook tick; assert one `url_metadata` event with title/uploader/duration and `thumbnail_ready: false`; mock httpx success; assert second `url_metadata` event with `thumbnail_ready: true`.
6. **Snapshot replay** — connect a late subscriber mid-job; assert snapshot includes the URL's title, log deque contents, sticky progress fields, and `thumbnail_ready`.
7. **Thumbnail endpoint** — 404 before ready, 200 + correct bytes after, 403 with bad token, 403 with missing token.
8. **Existing tests still pass** — additive change; old `url_progress` consumers in tests should not need updating.

Mocking strategy: thumbnail HTTP fetched via `httpx.get` — patch at the module-import site, same pattern as existing `download_media` mocks.

## File-size impact

Current `audio_dl_ui.py`: ~2230 lines.

Estimated additions:
- Backend (UrlState fields, SSE event types, logger, thumbnail fetcher, endpoint): ~300 LOC
- HTML body / JS rendering: ~150 LOC
- CSS `.card` block in `_INDEX_CSS_BASE`: ~80 LOC

Total ~530 LOC → ~2760 lines. Within the "single sibling file" convention. No third module proposed.

## Versioning

This is a UI-only addition. Per [CLAUDE.md](../../../CLAUDE.md) release flow: bump `__version__` in `audio_dl.py` + `version` in `pyproject.toml` + add `## v1.X — Rich job cards` section to `CHANGELOG.md` on the implementation PR. Recommended version: **v1.6** (folds in this work + the unreleased v1.6/v1.7 commit-labeled UI work as one shipped release), or **v1.8** if we want commit-label and version-label to match. Decide at implementation time.

## Open follow-ups (out of scope)

- **v1.8 per-theme card layouts** — each theme gets its own card structure (amber dithers thumbs, rose hides them, claude reorders metadata, etc.).
- **Expandable log** — click a card to see all 50 lines, not just the last 3.
- **Aggregate stats panel** — total speed, queue ETA, total bytes, in the panel summary.
- **Reveal-in-Finder per card** — clicking `complete` cards already reveals; tighten the affordance.
