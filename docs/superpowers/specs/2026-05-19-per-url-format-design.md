# Spec — v1.9 per-URL format (single-screen row builder)

**Status:** Design approved 2026-05-19
**Target files:** `audio_dl_ui.py` (web UI), `test_audio_dl_ui.py`
**Predecessors:**
[web UI](2026-05-10-web-ui-design.md) (v1.2),
[themes](2026-05-14-console-ui-themes.md) (v1.5),
[rich cards](2026-05-16-rich-job-cards-design.md) (v1.6),
[per-theme card variations](2026-05-16-per-theme-card-variations-design.md) (v1.7),
[UX rearchitecture](2026-05-19-ux-rearchitecture.md) (v1.8)

## Problem

v1.8 introduced the three-zone UI and persistent History but kept the v1.2
assumption that *one submission has one format*. The form has a single
`format` dropdown that applies to every URL in the textarea.

The maintainer's real workflow is a mixed list — some URLs are music
(want `m4a` or `flac`), others are video (want `mp4`) — pasted in one go.
Today that forces either (a) sorting the list by format and submitting
in batches, or (b) submitting in one batch and accepting that the videos
will get stripped to audio. Neither matches the queueing-throughout-the-day
flow v1.8 just optimized for.

v1.9 makes format a per-URL decision, surfaced directly in the form.

## Goals

- Each queued URL carries its own target format, set in the form before submit.
- Pasting a multi-line list still works in one paste — each line becomes its
  own row with its own picker.
- A "default" format setting still exists, so a list of like-formatted URLs
  doesn't require N clicks.
- Format is visible at every stage: the form row, the In Flight card, and
  the History row (the last is already in v1.8).
- Wire format and server state cleanly carry per-URL format. No string-
  munging hacks.

## Non-goals

- **CLI per-URL syntax.** The CLI stays on a single `-f` flag for v1.9.
  Multiple-format CLI runs are still achievable via shell loops.
- **Smart per-platform format inference.** ("YouTube → mp4 automatically")
  considered and rejected during brainstorming — hidden behavior with high
  maintenance cost.
- **Per-URL choice of fragments, playlist, output_dir, or force.** Those
  remain job-level. Not a real user need.
- **Drag-to-reorder queued rows.** YAGNI; submission order rarely matters.
- **Persisting unsubmitted queue across browser refresh.** The form is
  ephemeral; History is the durable surface.
- **Re-download from History with a different format.** Already possible
  via re-download → change default → submit. No new affordance needed.

## Mental model

One screen. The form's "URLs" zone *is* a queue list. Rows materialize as
the user types or pastes; the last row is always an empty input ready for
the next entry. Each row owns its own format picker. A small "default"
strip below the list controls the format that's applied to *new* rows
(plus offers bulk-apply and clear-all actions).

This collapses the v1.8 textarea+dropdown into a single, direct surface:
what you see in the queue is what gets submitted.

## Locked decisions

| # | Decision |
|---|---|
| 1 | Single-screen form. No two-step "compose preview". |
| 2 | URLs zone is a list of rows. Each row: gutter marker · URL · format dropdown · remove (`×`). |
| 3 | The last row is always an empty input row (gutter `+`, italic placeholder). Pressing `↵` commits it as a row and a new empty input row materializes below. |
| 4 | Pasting multi-line text into the empty input row splits into N committed rows (one per non-blank line). |
| 5 | Pasting a line whose **last whitespace-separated token** matches a known format (`mp3`, `m4a`, `flac`, `alac`, `opus`, `wav`, `mp4`) strips that token from the URL and pre-fills the new row's dropdown. Case-insensitive match. |
| 6 | Per-row picker is a `<select>` (not radios, not chips). One dropdown per row with the seven `ALL_FORMATS` options. |
| 7 | A "default" strip sits **below** the list: `default format for new URLs: [m4a ▾]` · `set all rows → default` · `clear all`. The default does not retroactively change existing rows unless `set all rows → default` is clicked. |
| 8 | Client-side URL validation is **light**: row is valid iff URL starts with `http://` or `https://`. Empty input row never counts as invalid (it's the input affordance). |
| 9 | Submit button label: `[ SUBMIT N ]` where N is the count of committed rows. Disabled when N = 0 or any committed row is invalid. |
| 10 | In Flight cards gain a small format chip next to the title, matching the History row chip style already shipped in v1.8. |
| 11 | Wire format: `POST /jobs` body becomes `{urls: [{url, format}, ...], output_dir, playlist, force, fragments}`. The top-level `format` field is **removed** entirely. |
| 12 | `UrlState` gains `media_format: str`. `JobState.media_format` is **kept** as a legacy field representing the submission's default (used only for the job_snapshot's `default_format` and for any future telemetry); downloads always read `url_state.media_format`. |
| 13 | Re-download from History still uses `entry.format` (v1.8 behavior, no change). The re-download path constructs a single-row submission with the entry's format. |

## Form layout

The form lives in `_INDEX_HTML_BODY` and is themed via existing CSS vars.
No new theme vars introduced. Layout, top-to-bottom inside the existing
[ NEW JOB ] frame:

```
┌─ [ NEW JOB ] ────────────────────────────────────
  urls   N in queue ··············· ↵ to add · paste many lines to split

  ▸  https://youtu.be/abc123                         [M4A ▾]   ×
  ▸  https://soundcloud.com/artist/track             [FLAC ▾]  ×
  ▸  https://youtu.be/xyz789                         [MP4 ▾]   ×
  ▸  https://bandcamp.com/track/foo                  [M4A ▾]   ×
  +  paste or type a URL...                          [M4A ▾]

  default format for new URLs: [m4a ▾]  |  set all rows → default  |  clear all

  output ▸  ~/Downloads/audio-dl
  parallel ▸ fragments: 4
  [ ] playlist  [ ] force redownload

  [ SUBMIT 4 ]
```

Row anatomy (CSS grid, 4 cols):

| Col | Width | Content (committed row) | Content (empty input row) |
|---|---|---|---|
| 1 | 16px | `▸` gutter (var(--accent)) | `+` gutter (dim var(--accent)) |
| 2 | 1fr | URL text, domain in var(--accent), path in var(--dim) | `<input>` with placeholder "paste or type a URL…" |
| 3 | 12ch | `<select>` with current format | `<select>` with default format (disabled-ish styling, no `×`) |
| 4 | 22px | `×` button | hidden |

The empty input row remains visible at the bottom even when N = 0; the
N-in-queue counter shows "0 in queue" and the submit button is disabled
with label `[ SUBMIT 0 ]`.

## Client-side state

```js
// Queue is the source of truth; render derives from it.
const queue = [
  { id: 'r_1', url: 'https://youtu.be/abc123', format: 'm4a', error: null },
  { id: 'r_2', url: 'https://soundcloud.com/artist/track', format: 'flac', error: null },
  // ...
];

let defaultFormat = 'm4a';   // separate from per-row format
```

`id` is a monotonic counter (`r_${n++}`), used as the React-style key.
`error` is `null` for valid rows; otherwise a short string ("not a URL").

### Input-row commit

The empty input row's `<input>` has these handlers:

- **`Enter` keydown:** if the input value passes light validation
  (`/^https?:\/\//i`), commit a new queue row with `{url: value, format: defaultFormat}`, clear the input, focus stays in the input.
  If invalid, mark the input with an error border and tooltip; don't commit.
- **`paste` event:** read `clipboardData.getData('text')`, split on `\n`,
  filter blank lines, run each line through the per-line format-detection
  parser (below), commit each as its own row with the resolved format.
  Clear the input. If a line fails validation, commit it anyway with
  `error` set; the user sees the bad row and can edit or delete.
- **`blur` with content:** treat like `Enter` (commit if valid).

### Per-line format detection (paste path only)

```js
function parseLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(/\s+/);
  if (parts.length >= 2) {
    const last = parts[parts.length - 1].toLowerCase();
    if (ALL_FORMATS.has(last)) {
      return { url: parts.slice(0, -1).join(' '), format: last };
    }
  }
  return { url: trimmed, format: defaultFormat };
}
```

Note that `parts.slice(0, -1).join(' ')` only matters when the user pasted
a URL with internal whitespace — pathologically rare; URLs shouldn't have
spaces. The .join(' ') is defensive.

Format detection only runs on paste, not on `Enter` commit — a user typing
manually who hits space + `mp4` clearly meant to keep typing, and we
shouldn't surprise them by mutating the dropdown mid-typing.

### Bulk actions

- **`set all rows → default`:** iterates `queue`, sets each row's `format`
  to `defaultFormat`. No confirmation prompt.
- **`clear all`:** empties `queue`, leaves the empty input row in place.
  Single click; no undo. Sufficient because the user typed/pasted what they
  wanted moments ago.

### Submit

```js
async function submit() {
  const valid = queue.filter(r => !r.error);
  if (!valid.length) return;
  const body = {
    urls: valid.map(r => ({ url: r.url, format: r.format })),
    output_dir: $('output').value,
    playlist: $('playlist').checked,
    force: $('force').checked,
    fragments: parseInt($('fragments').value, 10),
  };
  const resp = await fetch('/jobs', { method: 'POST', headers: {...csrfHeaders, 'Content-Type': 'application/json'}, body: JSON.stringify(body) });
  if (resp.ok) {
    queue.length = 0;        // clear committed rows
    $('add-input').value = '';
    render();
    const { job_id } = await resp.json();
    openStream(job_id);
  }
}
```

The same dedupe guard from PR #23 follow-up still applies: skip URLs
already in `cardState` (i.e., currently In Flight) and show the inline
"N already in flight, skipped" notice.

## Server-side notes

### `JobRequest` body shape

```python
class UrlSpec(BaseModel):
    url: str
    format: str   # must be in ALL_FORMATS

class JobRequest(BaseModel):
    urls: list[UrlSpec]
    output_dir: str
    playlist: bool = False
    force: bool = False
    fragments: int = 4
    # NO top-level `format` field — gone in v1.9.
    # NO top-level `jobs` field — also removed (vestigial since v1.8).
```

The `jobs` field has already been documented as vestigial in v1.8 (the
global executor ignored it). v1.9 finalizes its removal so old payloads
that include it 400 (Pydantic strict-mode default). Acceptable break;
the only client is the v1.9 UI.

Validation in `POST /jobs`:

```python
if not req.urls:
    raise HTTPException(400, "At least one URL is required.")
for spec in req.urls:
    if spec.format not in ALL_FORMATS:
        raise HTTPException(400, f"Unknown format: {spec.format!r} for {spec.url!r}.")
```

The existing path-validation, `output_dir` writable check, and `fragments`
range check are unchanged.

### `UrlState` gains `media_format`

```python
@dataclass
class UrlState:
    url: str
    media_format: str        # NEW — per-URL target format
    # ...existing fields unchanged
```

`media_format` is set at construction time from the `UrlSpec`. It is
**not** mutable after the job starts (no UI affordance to change a queued
URL's format once submitted; cancel-and-resubmit is the path).

### `JobState.media_format`

Kept as-is for back-compat (`job_snapshot` carries it as `default_format`)
but no longer read by `_run_one`. The value stored is the `format` of the
first `UrlSpec` in the submission (an arbitrary choice — could equally be
`null`; first-element keeps existing snapshot shape stable).

### `_run_one` change

At [audio_dl_ui.py:500](../../../audio_dl_ui.py):

```python
# Before:
media_format=job.media_format,
# After:
media_format=url_state.media_format,
```

This is the only line of `_run_one` that needs to change.

### Snapshot shape

`job_snapshot` already carries a `url_states` dict keyed by URL with each
state's fields. v1.9 adds `media_format` to each per-URL entry. Late-
connect subscribers therefore render the right chip on each card.

```jsonc
{
  "type": "job_snapshot",
  "job_id": "...",
  "default_format": "m4a",
  "url_states": {
    "https://youtu.be/abc123": {
      "media_format": "m4a",
      "status": "downloading",
      "title": "...",
      // ...rest unchanged
    }
  },
  // ...
}
```

## In Flight card chip

The v1.8 In Flight card has a `<header>` with title, uploader, duration.
v1.9 adds a sibling chip in that header:

```html
<header class="card-head">
  <span class="card-title">…</span>
  <span class="card-meta">…</span>
  <span class="card-format-chip">M4A</span>   <!-- NEW -->
</header>
```

Styling reuses the History row chip block — same color rules (lossy /
lossless / video tint), same border + padding. No new theme vars.

The chip is populated from `url_states[url].media_format` (from snapshot
or `url_started` event payload). It does not change after first render.

## Error handling

| Condition | Behavior |
|---|---|
| Row URL doesn't start with `http(s)://` | Red border on URL cell, tooltip "must start with http:// or https://". Submit disabled until all rows pass or are removed. |
| `POST /jobs` rejects an unknown format (server-side guard against tampering) | Inline notice next to submit: "Server rejected: unknown format X for Y". Queue untouched so user can fix and retry. |
| Paste contains a line that's pure whitespace | Skipped (no row committed). |
| Paste contains a line that's only a format token (`mp3` with no URL) | Committed as an invalid row with the format token as the URL; light validation fails; user sees the row and removes it. |
| `set all rows → default` clicked with empty queue | No-op. |
| `clear all` clicked with empty queue | No-op. |
| Submit clicked with all rows invalid | No-op; button is already disabled. |

## Testing

Additions to [test_audio_dl_ui.py](../../../test_audio_dl_ui.py):

1. **`JobRequest` schema** — POSTing the old shape (`urls: str, format: str`) returns 422 (Pydantic rejects). POSTing the new shape with one URL succeeds.
2. **Per-URL format propagates to download** — POST with two URLs at different formats; assert `_run_one` is called with `url_state.media_format` matching each spec, not `job.media_format`.
3. **Unknown format in `UrlSpec`** — POST with `[{url: "https://...", format: "mp3x"}]` returns 400 with a message naming the bad format and URL.
4. **Empty `urls` list** — POST with `urls: []` returns 400.
5. **Snapshot includes per-URL `media_format`** — start a job with mixed formats, connect a late SSE subscriber, assert each `url_states[*]` in the snapshot has the right `media_format`.
6. **History entry has the per-URL format** — covered by existing v1.8 tests; no change needed since the client already writes `entry.format` per URL.

JS-side helpers added (testable as pure functions, parametrized table tests):

7. **Paste-time parsing — integration test only.** Drive it indirectly: POST a body whose URLs came from a known paste fixture and assert the server received the right `{url, format}` pairs. The pure-JS `parseLine` function stays client-only; we don't introduce a JS test runner just for this.

Rules covered by manual smoke during PR review (six lines of pasted text, six expected outcomes — fast to verify visually):

| Pasted line | Expected row |
|---|---|
| `https://yt.com/abc` | url = `https://yt.com/abc`, format = default |
| `https://yt.com/abc mp3` | url = `https://yt.com/abc`, format = `mp3` |
| `https://yt.com/abc MP3` | url = `https://yt.com/abc`, format = `mp3` |
| `https://yt.com/abc unrelated` | url = `https://yt.com/abc unrelated`, format = default (light validation will then flag the URL as invalid because of the space) |
| (blank line) | skipped, no row |
| `mp3` (only the token) | url = `mp3`, format = default (light validation flags as invalid; user removes) |

## File touch summary

| File | Change |
|---|---|
| `audio_dl_ui.py` | `UrlSpec` model · `JobRequest.urls` changes from `str` to `list[UrlSpec]` · top-level `format` and `jobs` removed · `UrlState.media_format` added · `_run_one` reads `url_state.media_format` · `_build_snapshot` adds per-URL `media_format` · form HTML in `_INDEX_HTML_BODY` rewritten to row builder · CSS in `_INDEX_CSS_BASE` for row layout + chip · JS in `_INDEX_JS` for queue state, paste handler, bulk actions, submit · In Flight card template gains `card-format-chip` |
| `test_audio_dl_ui.py` | Tests 1–7 above. Existing tests updated to send the new POST shape. |
| `audio_dl.py` | Bump `__version__` to `1.9.0` |
| `pyproject.toml` | Bump `version` to `1.9.0` |
| `CHANGELOG.md` | New `## v1.9.0` section: per-URL format, single-screen row builder, removed `jobs` field, breaking POST shape |

Existing tests that assert the old POST shape (e.g., happy-path SSE,
cancel) need to be migrated. Roughly 8-10 tests touch the request body.

## Done criteria

- `audio-dl-ui` launches; form shows the row-builder layout matching the V3 mockup.
- Pasting `https://yt.com/abc\nhttps://yt.com/xyz mp4` into the input row commits two rows; the second has `mp4` pre-selected.
- Typing `https://yt.com/qrs` + `↵` commits a row with the default format.
- Each row's dropdown changes only that row's format (not the default).
- `set all rows → default` overrides every row to the current default.
- Submitting a mixed-format batch produces N downloads each in the right format (verified by output file extensions).
- In Flight cards show the correct format chip per URL.
- Refreshing the browser mid-submission rebuilds cards with the right format chip (snapshot path).
- History entries retain their per-URL format (re-download produces the same format).
- `POST /jobs` with old `{urls: "...", format: "..."}` returns 422.
- `POST /jobs` with `[{url, format: "mp3x"}]` returns 400 naming the bad format.
- `pytest` green, `pylint` clean.
- CHANGELOG has a v1.9.0 section, both version sources match.

## Open follow-ups (out of scope, restating)

- CLI per-URL syntax (later, if anyone asks)
- Smart per-platform format inference (rejected; revisit only on user demand)
- Per-URL fragments / playlist / output_dir (no real need)
- Drag-to-reorder queued rows
- **Edit-on-click for committed rows.** Today, fixing a typo means `×` + re-add. If this turns out to be friction in practice, swap the `<span>` URL cell for an inline-editable input on click. Trivial follow-up.
- Persist unsubmitted queue across browser refresh
- Persist last-used default format in `localStorage` (currently resets to `ALL_FORMATS[0]` on every page load)
- Live re-download with different format from History
- `JOBS` dict GC/TTL (still deferred from v1.8)
- Auto-retry on failure (still deferred from v1.8)
