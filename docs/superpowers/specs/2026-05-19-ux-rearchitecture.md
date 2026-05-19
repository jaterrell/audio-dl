# Spec — v1.8 UX rearchitecture (three-zone UI, persistent history)

**Status:** Design approved 2026-05-19
**Target file:** `audio_dl_ui.py` (web UI), with small backing changes in `audio_dl_ui.py`'s `main()` and one CLI flag surface
**Predecessors:**
[web UI](2026-05-10-web-ui-design.md) (v1.2),
[themes](2026-05-14-console-ui-themes.md) (v1.5),
[rich cards](2026-05-16-rich-job-cards-design.md) (v1.6),
[per-theme card variations](2026-05-16-per-theme-card-variations-design.md) (v1.7)

## Problem

v1.5 through v1.7 layered heavy visual polish onto the web UI — ten themes,
rich live-feedback cards, per-theme structural card variations — without
ever revisiting the underlying flow the UI was built around. That flow is
now actively wrong for how the tool gets used.

Concrete pain reported by the maintainer:

- **No proper state management.** Completed URL cards never leave the
  active view. They pile up under the same list as in-flight downloads.
- **The textarea is never cleared on submit.** URLs accumulate as you
  re-paste throughout the day, and resubmitting requires manually
  selecting and deleting the previous batch.
- **Cards only disappear when a new submission runs
  `rows.innerHTML = ''`**, which nukes everything — including any
  completed cards a user might still want to act on (Reveal, look up
  what was saved, copy a path).
- **The layout assumes "type URLs once, walk away."** The real usage
  pattern is queueing throughout the day: drop a URL in, do something
  else, come back, drop another URL in, repeat.

The interaction model the UI was sketched against in v1.2 has been
silently obsolete since the .app shipped. v1.8 fixes it.

## Goals

- One screen, three zones that map to the three moments of use: typing,
  watching, looking-back.
- A global parallelism cap that survives across submissions — adding ten
  URLs while four are running should queue, not overwhelm.
- Completed work moves out of the way automatically, but stays reachable.
- History survives browser refresh and server restart, without
  introducing server-side persistence.

## Non-goals

- **Per-URL config.** "Different format per URL inside one submission" is
  a real ask but it's a separate spec; planned for v1.9.
- **Server-side history sync across browsers.** The CLI is the multi-host
  story. The UI is single-machine by design. Likely never built.
- **Auto-retry on failure.** Tempting but its own design surface (backoff,
  failure classes, manual override). v1.9 candidate.
- **`JOBS` dict GC / TTL.** The in-memory `JOBS` dict grows unbounded
  across the life of the process. Pre-existing memory leak, deferred to
  v1.9 — irrelevant for typical session lengths.
- **Live concurrency-cap adjustment in the UI.** The cap is set at
  launch via `--max-parallel` and stays fixed. A UI slider is a v1.9+
  consideration if it turns out to matter.

## Mental model

Discovery happened by walking three moments narratively (rather than from
a feature list):

1. **Fresh launch.** User opens the app. They see a split view: an
   empty **In Flight** zone with a "nothing running" empty state, and a
   populated **History** zone (loaded from localStorage) showing what
   they downloaded yesterday. The input form sits above both, ready.
2. **Mid-flight add.** User has four downloads running. They paste a new
   URL into the input and submit. The input is always available; the
   new URL appears in **In Flight** and either starts immediately (if
   below the global cap) or sits in the queued state. The textarea
   clears so they can paste the next one.
3. **After many downloads.** Over the course of an hour the user has
   queued 30 URLs. Completed ones have moved to **History** as each one
   finished, so **In Flight** only shows the four currently running
   plus whatever is queued. Looking back at a track from earlier means
   scrolling **History**, not hunting through a mixed list.

## Locked decisions

These are settled and not up for debate during implementation. Listed so
the implementing agent doesn't have to re-derive them.

| # | Decision |
|---|---|
| 1 | Three zones in one page: **Input**, **In Flight**, **History** |
| 2 | Global concurrency cap, cross-submission, set via new `--max-parallel N` CLI flag on `audio-dl-ui` (default `4`) |
| 3 | Each URL is its own card in **In Flight** — no job-grouping in the UI (the underlying `JobState` still groups them server-side) |
| 4 | History persists in `localStorage` under key `audio_dl_history`, JSON shape `{v: 1, items: [...]}` (envelope is versioned for future migration) |
| 5 | History capped at **100 entries**, FIFO drop on overflow |
| 6 | History row actions: **re-download**, **reveal in Finder**, **dismiss** |
| 7 | Textarea clears on successful submit (after server returns 200 from `POST /jobs`) |
| 8 | Server stays stateless / in-memory. No SQLite, no on-disk job log. History is purely a client-side concept. |
| 9 | `/reveal` validation relaxed: instead of requiring the path be present in some `JOBS[*].url_states[*].paths`, allow any path that (a) exists on disk and (b) sits inside an allow-listed root (the configured `output_dir`, or any output dir surfaced in the session). Traversal protection (no `..`, resolved-realpath check) stays. |

## Server-side notes

(Implementation lives in another agent; this section is the contract.)

### Global executor

Today, `POST /jobs` constructs a fresh `ThreadPoolExecutor(max_workers=job.jobs)`
per job (at `audio_dl_ui.py:578`). Two URLs across two jobs can run with
up to `2 × jobs` workers — there's no cross-job bound.

v1.8: a **process-wide singleton** `ThreadPoolExecutor`, initialized in
`main()` from `--max-parallel`. All `_run_one` submissions across all
jobs route to the same pool. Cancellation semantics stay per-job (set
`job.cancelled = True`, hook raises `_Cancelled` on next tick), but the
pool itself is not shut down on cancel — other jobs keep running.

Concretely:

```python
# module scope
_executor: ThreadPoolExecutor | None = None

def main():
    parser.add_argument("--max-parallel", type=int, default=4)
    args = parser.parse_args()
    global _executor
    _executor = ThreadPoolExecutor(
        max_workers=args.max_parallel,
        thread_name_prefix="audio-dl-worker",
    )
    ...
```

`POST /jobs` no longer creates an executor. The supervisor thread that
emits `job_completed` still uses `concurrent.futures.wait(futures, ...)`;
that semantics is unchanged because `wait()` is per-future, not per-pool.

### `-j` field becomes vestigial

The form's `-j` (parallel-URLs) field has no server-side meaning anymore.
The UI removes it from the form. If the field arrives in a `POST /jobs`
body (e.g. an old client), it's ignored. No 400.

### `--fragments` is unchanged

`--fragments` controls **intra-track** fragment parallelism inside
yt-dlp/ffmpeg — orthogonal to the cross-URL cap. It stays in the form.

### Per-job tempdir cleanup is unchanged

The thumbnail/temp cleanup logic around `audio_dl_ui.py:565` is
unaffected. It runs when the last subscriber leaves and the job is
terminal, which still happens.

### `/reveal` allow-list

Today's `/reveal`:

1. Validates that the requested path appears in some
   `JOBS[*].url_states[*].paths`.
2. Calls `subprocess.run(["open", "-R", path])`.

Problem: history rows hold paths that are no longer in `JOBS` (either
the job got GC'd or the server restarted). They can't be revealed,
which defeats the point of persistent history.

v1.8 relaxation:

```python
def _is_revealable(path: str, allow_roots: list[str]) -> bool:
    real = os.path.realpath(path)
    if not os.path.exists(real):
        return False
    for root in allow_roots:
        real_root = os.path.realpath(root)
        # robust prefix check — guards against /foo/barx matching /foo/bar
        if real == real_root or real.startswith(real_root + os.sep):
            return True
    return False
```

`allow_roots` = the union of every `output_dir` seen this session
(launch default plus anything submitted via the form), plus the launch
`--output-dir`. Traversal protection (`os.path.realpath`,
`startswith(root + os.sep)`) is preserved verbatim.

400 if the path fails either check. The current JSON shape of the
endpoint (`{path: str}`) doesn't change.

## Client-side notes

### Markup

Wrap existing `#rows` (the rich-cards container from v1.6) as
`<section id="inflight">` with a count header. Add a sibling
`<section id="history">` with its own count header and an empty-state
line ("No downloads yet").

```html
<section id="inflight">
  <header>
    <h2>In Flight</h2><span class="count">0</span>
  </header>
  <div id="rows"><!-- existing card markup --></div>
  <p class="empty">Nothing running.</p>
</section>

<section id="history">
  <header>
    <h2>History</h2><span class="count">0</span>
  </header>
  <ul id="history-rows"></ul>
  <p class="empty">No downloads yet.</p>
</section>
```

Both sections live inside the main column; styles inherit existing theme
vars (no new CSS vars).

### State machine

Per URL, client tracks:

```
queued → resolving → downloading → postprocessing → complete  →  History
                                                  ↘ failed    →  History
                                                  ↘ cancelled →  (dropped, no history entry)
```

On `url_completed` or `url_failed`, the client:

1. Combines the prior `url_metadata` payload (`title`, `uploader`,
   `duration`) with the terminal event's `paths` (or `error`).
2. Fetches the thumbnail blob via the existing
   `/jobs/{job_id}/thumb/{url_idx}` endpoint.
3. If the blob is **≤50KB**, encodes to a base64 data URL and stores it
   on the history entry. Larger → store `null` and render a placeholder.
   (Keeps localStorage well below the 5MB browser cap with 100 entries.)
4. Pushes the entry into `audio_dl_history.items`, FIFO-drops oldest if
   length > 100, writes back to `localStorage`.
5. Removes the in-flight card.
6. Re-renders the History section.

Cancelled URLs are not written to History — they're treated as the user
saying "never mind."

### History entry shape

```jsonc
{
  "id": "h_2026-05-19T18:42:11Z_0",  // monotonically unique
  "url": "https://...",
  "sanitized_url": "https://...",
  "title": "Wandered into the Day",
  "uploader": "Geotic",
  "duration": 251,
  "format": "m4a",
  "status": "complete",      // "complete" | "failed"
  "paths": ["/Users/.../Wandered into the Day.m4a"],
  "error": null,
  "thumb_data_url": "data:image/jpeg;base64,...",  // or null
  "completed_at": 1715855531
}
```

### History row markup

Compact one-line row, ~40px tall:

```
[thumb 32px] Title — Uploader  [m4a]  5m ago   [↻] [⊙] [×]
```

- `↻` re-download — POSTs a fresh `/jobs` with this URL + format.
- `⊙` reveal — POSTs `/reveal` with the first path. Hidden for `failed`.
- `×` dismiss — removes from history, writes back, re-renders.

Re-downloaded URLs follow the normal flow: appear in In Flight, eventually
land in History as a *new* entry. The original history entry stays.

### LocalStorage envelope

```jsonc
{ "v": 1, "items": [ ... ] }
```

Version envelope so a v2 schema can migrate (or wipe on mismatch). On
load, if `parse` throws or `v !== 1`, reset to empty silently.

### Empty states

Both sections show their empty-state line when their list is empty. The
empty states are CSS-driven (`:empty` selector on the list parent) so JS
doesn't have to track them.

## File touch summary

| File | Change |
|---|---|
| `audio_dl_ui.py` | Global singleton executor; `--max-parallel` CLI flag; `/reveal` relaxation + allow-list; three-zone HTML in `_INDEX_HTML_BODY`; History CSS in `_INDEX_CSS_BASE`; JS state machine + localStorage handling in `_INDEX_JS`; remove `-j` from form |
| `test_audio_dl_ui.py` | Tests for concurrency cap (one pool, N URLs across 2 jobs runs ≤cap concurrently); tests for relaxed `/reveal` (in-root path with no JOBS entry → 200, traversal still 400, non-existent file → 400) |
| `audio_dl.py` | Bump `__version__` to `1.8.0` |
| `pyproject.toml` | Bump `version` to `1.8.0` |
| `CHANGELOG.md` | New `## v1.8.0` section: UX rearchitecture, three zones, persistent history, `--max-parallel` |

## Done criteria

- `audio-dl-ui --max-parallel 2`, submit 5 URLs across 2 jobs — never
  more than 2 yt-dlp downloads concurrent.
- Submitting clears the textarea (verified via Selenium-equivalent or
  manual smoke).
- Completed cards move to History within ~1s of the `url_completed`
  event.
- Refreshing the browser keeps History populated.
- History row "reveal" works for a path whose `JobState` has since been
  forgotten (e.g. after server restart, simulated via clearing `JOBS`).
- `/reveal` with `../etc/passwd` and friends still returns 400.
- `pytest` green, `pylint` clean.
- CHANGELOG has a v1.8.0 section, both version sources match.

## Open follow-ups (out of scope, restating)

- Per-URL config (v1.9 spec)
- Auto-retry (v1.9 candidate)
- `JOBS` dict GC/TTL (v1.9)
- Live concurrency-cap adjustment in UI (v1.9+, if needed)
- Server-side history sync (never; CLI is that story)
