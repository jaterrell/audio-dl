# audio-dl Web UI — design spec

**Status:** approved
**Date:** 2026-05-10
**Owner:** Joe Terrell
**Target release:** v1.2.0 (web UI shipped; .app packaging is a separate Phase-3 spec)

## Purpose

Give `audio-dl` a one-page browser UI so it can ship as a double-clickable
macOS `.app` (Phase 3). No terminal, no flags — paste URLs, pick a format,
click Download, watch progress, click to reveal the saved file. Power users
keep the CLI; the UI is the consumer face.

## Goals

- Local-only single-user web UI that exercises the existing `audio_dl`
  Python API (no subprocess, no duplication).
- Real-time progress per URL via Server-Sent Events.
- Whole-job Cancel that stops in-flight and queued URLs.
- Reveal-in-Finder for saved files.
- Zero new deps in the CLI install path (`fastapi`/`uvicorn` go behind
  `[project.optional-dependencies] ui = [...]`).

## Non-goals

- Multi-user / shared deployment. Server binds `127.0.0.1` only.
- Authentication.
- Credentials surface in the UI (`--cookies-from-browser`, `--sc-auth`,
  `--cookies`). Power users use the CLI for gated content.
- Persistent job history across server restarts.
- Cross-platform Reveal — macOS-first (`open -R <path>`). Linux/Windows
  later if needed.

---

## Architecture

**Process model:** single FastAPI app served by uvicorn. One server, one
user, in-memory state. Dies on Ctrl+C.

**Module boundary:**

| File | Role |
|---|---|
| `audio_dl.py` | CLI + Python API (unchanged behavior, one new optional param) |
| `audio_dl_ui.py` | FastAPI app, in-memory `JOBS` dict, SSE serializer, embedded HTML/CSS/JS |
| `pyproject.toml` | `py-modules` grows to `["audio_dl", "audio_dl_ui"]`; new `[project.optional-dependencies] ui = ["fastapi", "uvicorn[standard]"]`; new `[project.scripts]` entry `audio-dl-ui = "audio_dl_ui:main"` |

**Concurrency:** `ThreadPoolExecutor(max_workers=jobs)` per job. yt-dlp
progress hooks bound to `(job, url)` push events into a per-job
`queue.Queue`. SSE endpoint drains that queue via
`await asyncio.to_thread(q.get, timeout=1.0)`.

**No new deps in core path.** `audio_dl.py` does not import FastAPI.

---

## Public seam change in `audio_dl.py`

Add a single optional parameter to `download_media` and thread it through
`_build_ydl_opts`:

```python
def download_media(
    url: str,
    media_format: str = "mp3",
    ...,
    concurrent_fragments: int = 4,
    progress_hooks: list[Callable] | None = None,  # NEW
) -> list[str]:
```

```python
def _build_ydl_opts(
    *,
    media_format: str,
    ...,
    cookies_from_browser: str | None = None,
    progress_hooks: list[Callable] | None = None,  # NEW
) -> dict:
    ...
    if progress_hooks:
        opts["progress_hooks"] = progress_hooks
    return opts
```

CLI behavior unchanged (parameter defaults to `None`). Existing tests stay
green; one new unit test covers the new opt path.

---

## `audio_dl_ui.py` internals

### State

```python
@dataclass
class UrlState:
    url: str
    sanitized_url: str
    status: Literal["pending", "downloading", "completed", "failed", "cancelled"]
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None
    filename: str | None = None
    paths: list[str] = field(default_factory=list)
    error: str | None = None
    last_progress_emit: float = 0.0  # for throttle

@dataclass
class JobState:
    id: str
    media_format: str
    output_dir: str
    playlist: bool
    force: bool
    fragments: int
    jobs: int
    url_states: dict[str, UrlState]
    queue: queue.Queue  # SSE events
    cancelled: bool = False
    executor: ThreadPoolExecutor | None = None  # for shutdown on cancel

JOBS: dict[str, JobState] = {}
```

### HTTP endpoints

| Method | Path | Body / Response |
|---|---|---|
| `GET` | `/` | `HTMLResponse(_INDEX_HTML)` |
| `POST` | `/jobs` | Body: `{urls: str, format, output_dir, playlist, force, fragments, jobs}`. Returns `{job_id}`. 400 on validation failure. |
| `GET` | `/jobs/{id}/events` | SSE stream from `JobState.queue`. Emits `: keepalive\n\n` every 30s when idle. |
| `POST` | `/jobs/{id}/cancel` | Sets `job.cancelled = True`; calls `job.executor.shutdown(wait=False, cancel_futures=True)`. Returns `{ok: true}`. 404 if unknown. |
| `POST` | `/reveal` | Body: `{path}`. Validates path is in some `JOBS[*].url_states[*].paths`. Then `subprocess.run(["open", "-R", path], check=False)`. 400 if path not found in any current job. |

### Worker

For each URL in `JobState.urls`, the executor runs:

```python
def _run_one(job: JobState, raw_url: str) -> None:
    url_state = job.url_states[raw_url]

    # Advisor fix #1: cancel-before-start check
    if job.cancelled:
        url_state.status = "cancelled"
        url_state.error = "Cancelled"
        _emit(job, {"type": "url_failed", "job_id": job.id, "url": raw_url, "error": "Cancelled"})
        return

    clean = sanitize_url(raw_url)
    url_state.sanitized_url = clean
    url_state.status = "downloading"
    _emit(job, {"type": "url_started", "job_id": job.id, "url": raw_url, "sanitized_url": clean})

    hook = _make_progress_hook(job, url_state)
    try:
        paths = download_media(
            clean,
            media_format=job.media_format,
            output_dir=job.output_dir,
            playlist=job.playlist,
            force=job.force,
            concurrent_fragments=job.fragments,
            progress_hooks=[hook],
        )
    except _Cancelled:
        url_state.status = "cancelled"
        _emit(job, {"type": "url_failed", "job_id": job.id, "url": raw_url, "error": "Cancelled"})
        return
    except Exception as e:  # pylint: disable=broad-except
        url_state.status = "failed"
        url_state.error = str(e)
        _emit(job, {"type": "url_failed", "job_id": job.id, "url": raw_url, "error": str(e)})
        return

    if not paths:
        url_state.status = "failed"
        url_state.error = "Download failed"
        _emit(job, {"type": "url_failed", "job_id": job.id, "url": raw_url, "error": "Download failed"})
        return

    url_state.status = "completed"
    url_state.paths = paths
    _emit(job, {"type": "url_completed", "job_id": job.id, "url": raw_url, "paths": paths})
```

A small `_emit(job, event)` helper is just `job.queue.put(event)` — a
one-liner; SSE drain consumes from the other end.

A **supervisor thread** (spawned alongside the executor at `POST /jobs`
time) calls `concurrent.futures.wait(futures, return_when=ALL_COMPLETED)`,
then tallies counts from `job.url_states` and emits the final
`job_completed` event. (`wait()` is used instead of `executor.shutdown()`
because cancel may have already called `shutdown(wait=False, ...)`, and
double-shutdown semantics are subtle.) The supervisor runs in its own
thread (not the executor pool) so it doesn't consume a worker slot.

### Progress hook (with throttle)

```python
class _Cancelled(Exception):
    """Raised inside a yt-dlp progress hook to abort a download."""

def _make_progress_hook(job: JobState, url_state: UrlState) -> Callable:
    def hook(d: dict) -> None:
        if job.cancelled:
            raise _Cancelled()

        if d.get("status") != "downloading":
            return

        now = time.monotonic()
        if now - url_state.last_progress_emit < 0.2:  # max 5/sec/URL
            return
        url_state.last_progress_emit = now

        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes") or 0
        percent = (downloaded / total * 100) if total else 0.0

        url_state.percent = percent
        url_state.downloaded_bytes = downloaded
        url_state.total_bytes = total
        url_state.speed = d.get("speed")
        url_state.eta = d.get("eta")
        url_state.filename = d.get("filename")

        _emit(job, {
            "type": "progress",
            "job_id": job.id,
            "url": url_state.url,
            "percent": percent,
            "downloaded_bytes": downloaded,
            "total_bytes": total,
            "speed": d.get("speed"),
            "eta": d.get("eta"),
            "filename": d.get("filename"),
        })

    return hook
```

### SSE serializer

```python
async def _events(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)

    last_keepalive = time.monotonic()
    while True:
        try:
            event = await asyncio.to_thread(job.queue.get, timeout=1.0)
        except queue.Empty:
            now = time.monotonic()
            if now - last_keepalive >= 30:
                yield ": keepalive\n\n"
                last_keepalive = now
            continue

        yield f"data: {json.dumps(event)}\n\n"
        if event.get("type") == "job_completed":
            return
```

### Entry point

```python
def main():
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--output-dir", default=os.path.expanduser("~/Downloads/audio-dl"))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    check_dependencies()  # reuse from audio_dl

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    except OSError as e:
        print(f"ERROR: cannot bind {args.host}:{args.port} — {e}")
        sys.exit(1)
```

`--output-dir` is the **default** populated into the form; the user can edit
it in the textbox before submitting.

---

## Data flow (happy path)

1. Browser loads `GET /` → empty form, output dir prepopulated.
2. User submits form → `POST /jobs` validates, creates `JobState`, returns `{job_id}`.
3. Worker thread starts `ThreadPoolExecutor(max_workers=jobs)`; submits one `_run_one(job, url)` per URL.
4. JS opens `EventSource('/jobs/{job_id}/events')` and renders rows.
5. Each running task:
   - Sanitizes URL → emits `url_started`.
   - Calls `download_media(..., progress_hooks=[hook])`.
   - Hook pushes throttled `progress` events.
   - On finish: emits `url_completed` with paths.
6. Supervisor emits `job_completed` once all futures resolved. SSE drain loop sees it and closes the stream.
7. UI renders completed rows with size + Reveal button. For playlist URLs (N paths), the row shows one **Reveal folder** button instead of per-file buttons (advisor fix #2).

---

## Cancel semantics (advisor fix #1)

`POST /jobs/{id}/cancel` does **both**:

1. Sets `job.cancelled = True` — running tasks see it on the next progress
   hook tick and raise `_Cancelled`.
2. Calls `job.executor.shutdown(wait=False, cancel_futures=True)` —
   futures that haven't started running yet are cancelled outright.

The worker entry-point also checks `job.cancelled` before starting any
work, so the race where a future starts running between `shutdown(...)`
returning and the actual task body executing is still handled.

After cancel: any URL that hadn't started reports `url_failed` with
`error: "Cancelled"`. URLs in-flight raise `_Cancelled` from their hook
and likewise report `url_failed` with `error: "Cancelled"`. The supervisor
still emits `job_completed` with counts.

---

## Error handling

| Failure mode | Behavior |
|---|---|
| `download_media` returns `[]` | `url_failed` with "Download failed" |
| Exception in worker | catch broad, `url_failed` with `str(e)` |
| `_Cancelled` from hook | `url_failed` with "Cancelled" |
| Validation: empty URLs | 400 from `POST /jobs` |
| Validation: bad format | 400 |
| Validation: `jobs` not in 1..8 | 400 |
| Validation: `fragments` not in 1..16 | 400 |
| Validation: `output_dir` not writable | 400 (call `os.makedirs(output_dir, exist_ok=True)`; catch OSError) |
| Port already in use | uvicorn raises OSError, main() catches, prints clear message, exit 1 |
| `/reveal` with path not in any `JOBS[*].url_states[*].paths` | 400 |

---

## HTML/CSS/JS (embedded as one string)

Single string constant `_INDEX_HTML` containing:

- `<style>` block (compact, no framework, ~50 lines)
- Header: "audio-dl" + version
- Form section: URLs textarea, format `<select>` (populated from `ALL_FORMATS`), output-dir text input, `--playlist` and `--force` checkboxes, fragments range slider (1–16), jobs range slider (1–8), Download button.
- Active-job panel (hidden until first submit): URL rows with per-row progress bar, sanitized URL, percent + speed + ETA, and a job-level Cancel button.
- Completed list: rows with filename, size, Reveal button (or "Reveal folder" for N>1 paths).
- Vanilla JS:
  - `form.onsubmit` → `fetch('/jobs', POST)` → on success, hide form (or disable Download), open `EventSource('/jobs/{id}/events')`.
  - Event handler switch: render or update rows.
  - Cancel: `fetch('/jobs/{id}/cancel', POST)`.
  - Reveal: `fetch('/reveal', POST, body: {path})`.
  - On `job_completed`: re-enable Download button, close `EventSource`.

No build step. No external scripts.

---

## Testing

**New file:** `test_audio_dl_ui.py` (~15 tests)

| Test | What it covers |
|---|---|
| `test_build_ydl_opts_with_progress_hooks` | `_build_ydl_opts(progress_hooks=[h])` → `opts["progress_hooks"] == [h]` |
| `test_build_ydl_opts_no_hooks` | `progress_hooks=None` → key absent |
| `test_post_jobs_empty_urls_400` | Empty URL string → 400 |
| `test_post_jobs_bad_format_400` | Format not in ALL_FORMATS → 400 |
| `test_post_jobs_jobs_out_of_range_400` | jobs=0, jobs=9 → 400 |
| `test_post_jobs_fragments_out_of_range_400` | fragments=0, fragments=17 → 400 |
| `test_post_jobs_unwritable_output_dir_400` | output_dir under `/dev/null/...` → 400 |
| `test_post_jobs_happy_path` | Valid body → 200, returns `{job_id}`, `JOBS[id]` populated |
| `test_reveal_unknown_path_400` | path not in JOBS → 400, `subprocess.run` not called |
| `test_reveal_known_path_calls_open` | path in JOBS → `subprocess.run(["open","-R",path])` called (mocked) |
| `test_cancel_unknown_job_404` | Unknown job_id → 404 |
| `test_cancel_sets_flag_and_shutdown` | `POST /cancel` → flag set, `executor.shutdown(wait=False, cancel_futures=True)` called |
| `test_progress_hook_throttle` | 1000 hook calls in simulated 1s (monkeypatch `time.monotonic`) → ~5 progress events in queue |
| `test_cancel_during_hook_raises` | After setting cancelled, calling hook raises `_Cancelled` |
| `test_sse_end_to_end_happy_path` | Monkeypatch `download_media` to push 3 progress events + return `["/fake/song.mp3"]`. POST /jobs, open SSE stream, assert event order: `url_started → progress×3 → url_completed → job_completed`. |

**Throttle test determinism note** (per advisor): the throttle test uses
`monkeypatch.setattr(audio_dl_ui.time, "monotonic", fake_clock)` where
`fake_clock` returns a manually-advanced timestamp. Avoids `time.sleep`.

**Test infra:** `fastapi.testclient.TestClient` handles sync + streaming.
No `pytest-asyncio` needed. `subprocess.run`, `webbrowser.open`, and
`download_media` are all mocked. No network in any test.

**CI updates:**

- `.github/workflows/tests.yml`: add `pip install -e '.[ui]'` step so
  fastapi/uvicorn are present before `pytest`.
- `.github/workflows/pylint.yml`: add `pip install -e '.[ui]'` step so
  pylint can resolve fastapi/uvicorn imports. The existing
  `pylint $(git ls-files '*.py')` line already picks up `audio_dl_ui.py`
  and `test_audio_dl_ui.py` once they're committed — no command change
  needed.

---

## Out of scope / future

- Phase 3 — PyInstaller `.app` bundle (separate spec).
- Phase 4 — GitHub Actions release builder on public repo (separate spec).
- Cross-platform Reveal (Linux: `xdg-open`, Windows: `explorer /select,`).
  Add when there's demand.
- Credentials in UI. Punt to v1.3 if user demand emerges.
- Persistent job history (SQLite).
- WebSocket instead of SSE (no benefit at this size).

---

## Files touched (delta summary)

| File | Change |
|---|---|
| `audio_dl.py` | Add `progress_hooks: list[Callable] \| None = None` to `download_media` and `_build_ydl_opts`. Pass through. ~6 line delta. |
| `audio_dl_ui.py` | **New.** ~250 lines including embedded HTML/CSS/JS. |
| `test_audio_dl_ui.py` | **New.** ~150 lines, 15 tests. |
| `test_audio_dl.py` | Add 2 tests for new `progress_hooks` parameter on `_build_ydl_opts`. |
| `pyproject.toml` | `py-modules = ["audio_dl", "audio_dl_ui"]`; new `[project.optional-dependencies] ui = ["fastapi", "uvicorn[standard]"]`; new script `audio-dl-ui = "audio_dl_ui:main"`. Bump version to `1.2.0`. |
| `requirements.txt` | Unchanged (UI deps live in pyproject extra). |
| `CHANGELOG.md` | New v1.2.0 section. |
| `README.md` | Add "Web UI" section: `pipx install 'audio-dl[ui]'` then `audio-dl-ui`. |
| `.github/workflows/tests.yml` | `pip install -e '.[ui]'` step. |
| `.github/workflows/pylint.yml` | Add `audio_dl_ui.py` and `test_audio_dl_ui.py`. |

---

## Done criteria

- `pip install -e '.[ui]'` succeeds in a fresh venv.
- `audio-dl-ui` launches a server on `127.0.0.1:8000` and opens the default browser.
- Pasting a real YouTube URL, picking mp3, clicking Download produces a file in `~/Downloads/audio-dl/` and the row shows a working Reveal button.
- Cancel mid-download stops the active URL and prevents queued URLs from starting.
- `pytest` passes (all old tests + ~17 new ones).
- `pylint audio_dl.py audio_dl_ui.py test_audio_dl_ui.py` passes with no new warnings.
- CHANGELOG.md has a v1.2.0 section.
