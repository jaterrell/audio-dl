#!/usr/bin/env python3
"""
audio_dl_ui.py — One-page web UI for audio_dl.

Sibling file to audio_dl.py. Reuses download_media, sanitize_url, and
ALL_FORMATS. fastapi/uvicorn live behind the [ui] optional-dependency
extra so the CLI install stays minimal.

Usage:
    audio-dl-ui                          # bind 127.0.0.1:8000, open browser
    audio-dl-ui --port 9000              # custom port
    audio-dl-ui --output-dir ~/Music     # change default output dir
    audio-dl-ui --no-browser             # don't auto-open the browser
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from dataclasses import dataclass, field
from typing import Callable, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from audio_dl import (
    ALL_FORMATS,
    _check_dependencies,
    download_media,
    sanitize_url,
    __version__,
)

# uvicorn is an optional dep (UI extra). Imported lazily in main() to avoid
# ImportError when the package is installed without [ui]. Exposed as a
# module-level name so tests can monkeypatch it before calling main().
uvicorn = None  # type: ignore[assignment]  # pylint: disable=invalid-name


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class _Cancelled(Exception):
    """Raised inside a yt-dlp progress hook to abort an in-flight download."""


@dataclass
class UrlState:  # pylint: disable=too-many-instance-attributes
    """Per-URL download state within a job, updated by progress hooks."""

    url: str
    sanitized_url: str = ""
    status: Literal["pending", "downloading", "completed", "failed", "cancelled"] = "pending"
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None
    filename: str | None = None
    paths: list[str] = field(default_factory=list)
    error: str | None = None
    last_progress_emit: float = 0.0


@dataclass
class JobState:  # pylint: disable=too-many-instance-attributes
    """Holds the entire state of a batch download job, including all URL states."""

    id: str
    media_format: str
    output_dir: str
    playlist: bool
    force: bool
    fragments: int
    jobs: int
    url_states: dict[str, UrlState]
    queue: "queue.Queue[dict]"
    cancelled: bool = False
    executor: ThreadPoolExecutor | None = None


JOBS: dict[str, JobState] = {}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

# Terminal events must always be delivered even if the queue is full;
# progress events can be dropped (they're throttled to ~5/sec/URL upstream
# and a missed sample is harmless).
_TERMINAL_EVENT_TYPES = frozenset({
    "job_started", "url_started", "url_completed", "url_failed", "job_completed",
})


def _emit(job: JobState, event: dict) -> None:
    """Push an SSE event onto the job's queue.

    Terminal events (job/url lifecycle) use a bounded put with a short
    timeout — if the queue is somehow full of progress events, give them a
    chance to be drained before silently dropping the terminal.
    Progress events use put_nowait and drop on Full.
    """
    if event.get("type") in _TERMINAL_EVENT_TYPES:
        try:
            job.queue.put(event, timeout=1.0)
        except queue.Full:
            # Last-resort: force-drop the oldest queued event to make room.
            # The alternative is silently losing this terminal event, which
            # is worse (UI hangs). Note: if the queue is somehow full of
            # other terminals (only possible with many URLs + a disconnected
            # client), this drops one of them — accepted tradeoff until the
            # v1.3 per-subscriber broadcast rewrite.
            try:
                job.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                job.queue.put_nowait(event)
            except queue.Full:
                pass  # truly stuck; the worst-case outcome
    else:
        try:
            job.queue.put_nowait(event)
        except queue.Full:
            pass  # drop excess progress


def _require_csrf(request: Request) -> str:
    """Verify CSRF token from X-Audio-DL-Token header OR ?token= query param."""
    expected = getattr(request.app.state, "csrf_token", None)
    if not expected:
        # Token not initialized (TestClient + no main() call). Block by default.
        raise HTTPException(403, "CSRF token not configured.")
    provided = request.headers.get("X-Audio-DL-Token") or request.query_params.get("token")
    if not provided:
        raise HTTPException(403, "Missing CSRF token.")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(403, "Invalid CSRF token.")
    return provided


def _make_progress_hook(job: JobState, url_state: UrlState) -> Callable[[dict], None]:
    """
    Build a yt-dlp progress hook bound to one URL.

    - Raises `_Cancelled` when `job.cancelled` is set (yt-dlp will surface
      this as a DownloadError, which `_run_one` catches).
    - Throttles to at most ~5 events/sec/URL.
    """
    def hook(d: dict) -> None:
        if job.cancelled:
            raise _Cancelled()

        if d.get("status") != "downloading":
            return

        now = time.monotonic()
        if now - url_state.last_progress_emit < 0.2:
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


def _run_one(job: JobState, raw_url: str) -> None:
    """One unit of work for the executor: sanitize, download, emit events."""
    url_state = job.url_states[raw_url]

    # Cancel-before-start: handles the race where a future is scheduled
    # but hadn't started running when cancel was hit.
    if job.cancelled:
        url_state.status = "cancelled"
        url_state.error = "Cancelled"
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": "Cancelled"})
        return

    hook = _make_progress_hook(job, url_state)
    try:
        clean = sanitize_url(raw_url)
        url_state.sanitized_url = clean
        url_state.status = "downloading"
        _emit(job, {"type": "url_started", "job_id": job.id,
                    "url": raw_url, "sanitized_url": clean})

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
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": "Cancelled"})
        return
    except Exception as e:  # pylint: disable=broad-except
        # yt-dlp may wrap _Cancelled in DownloadError — detect by chained cause.
        if isinstance(e.__cause__, _Cancelled) or "Cancelled" in str(e):
            url_state.status = "cancelled"
            _emit(job, {"type": "url_failed", "job_id": job.id,
                        "url": raw_url, "error": "Cancelled"})
            return
        url_state.status = "failed"
        url_state.error = str(e)
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": str(e)})
        return

    if not paths:
        url_state.status = "failed"
        url_state.error = "Download failed"
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": "Download failed"})
        return

    url_state.status = "completed"
    url_state.paths = paths
    _emit(job, {"type": "url_completed", "job_id": job.id,
                "url": raw_url, "paths": paths})


def _supervise(job: JobState, futures: list) -> None:
    """Wait for all futures, then emit job_completed and clean up."""
    wait(futures, return_when=ALL_COMPLETED)
    # Futures cancelled by the executor (cancel_futures=True path) never
    # ran _run_one, so their url_states are still 'pending'. Reclassify
    # them as 'cancelled' and emit the matching url_failed event so the
    # UI shows the right state.
    if job.cancelled:
        for st in job.url_states.values():
            if st.status in ("pending", "downloading"):
                st.status = "cancelled"
                st.error = "Cancelled"
                _emit(job, {"type": "url_failed", "job_id": job.id,
                            "url": st.url, "error": "Cancelled"})
    summary = {"completed": 0, "failed": 0, "cancelled": 0}
    for st in job.url_states.values():
        if st.status == "completed":
            summary["completed"] += 1
        elif st.status == "cancelled":
            summary["cancelled"] += 1
        else:
            summary["failed"] += 1
    _emit(job, {"type": "job_completed", "job_id": job.id, "summary": summary})
    if job.executor is not None:
        job.executor.shutdown(wait=False)


def _start_job(job: JobState) -> None:
    """Spin up the executor and supervisor. Called from POST /jobs."""
    job.executor = ThreadPoolExecutor(max_workers=job.jobs)
    # Emit job_started BEFORE submitting futures to guarantee it is first in
    # the queue, regardless of how quickly the worker threads start running.
    _emit(job, {
        "type": "job_started",
        "job_id": job.id,
        "urls": [{"url": s.url} for s in job.url_states.values()],
    })
    futures = [
        job.executor.submit(_run_one, job, url)
        for url in job.url_states
    ]
    supervisor = threading.Thread(target=_supervise, args=(job, futures), daemon=True)
    supervisor.start()


# pylint: disable=line-too-long
_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="csrf-token" content="__CSRF_TOKEN__">
<title>audio-dl</title>
<style>
  :root { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif; }
  body { max-width: 760px; margin: 2rem auto; padding: 0 1rem; color: #1c1c1e; background: #f7f7f8; }
  h1 { margin: 0 0 0.25rem; font-size: 1.4rem; }
  .sub { color: #6e6e73; font-size: 0.85rem; margin-bottom: 1.5rem; }
  form { background: #fff; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e5ea; }
  label { display: block; font-weight: 600; font-size: 0.85rem; margin: 0.75rem 0 0.3rem; }
  textarea, input[type=text], select { width: 100%; box-sizing: border-box; padding: 0.5rem 0.6rem; border-radius: 8px; border: 1px solid #d1d1d6; font: inherit; }
  textarea { resize: vertical; min-height: 5.5rem; font-family: ui-monospace, SFMono-Regular, monospace; font-size: 0.85rem; }
  .row { display: flex; gap: 0.75rem; }
  .row > div { flex: 1; }
  .checkboxes { display: flex; gap: 1rem; margin-top: 0.5rem; font-size: 0.9rem; }
  .sliders { display: flex; gap: 1rem; margin-top: 0.5rem; }
  .sliders > div { flex: 1; }
  .sliders label { display: flex; justify-content: space-between; align-items: baseline; }
  .sliders span { font-weight: 400; color: #6e6e73; font-variant-numeric: tabular-nums; }
  button { background: #007aff; color: white; border: 0; padding: 0.6rem 1.2rem; border-radius: 8px; font: inherit; font-weight: 600; cursor: pointer; margin-top: 1rem; }
  button:disabled { background: #c7c7cc; cursor: default; }
  button.cancel { background: #ff3b30; }
  #jobpanel { background: #fff; margin-top: 1rem; padding: 1rem 1.25rem; border-radius: 12px; border: 1px solid #e5e5ea; display: none; }
  #jobpanel.active { display: block; }
  #jobpanel header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; }
  #jobpanel h2 { font-size: 1rem; margin: 0; }
  .urlrow { padding: 0.6rem 0; border-top: 1px solid #f2f2f4; }
  .urlrow:first-child { border-top: 0; }
  .urlrow .top { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; }
  .urlrow .url { font-family: ui-monospace, SFMono-Regular, monospace; font-size: 0.8rem; color: #3a3a3c; word-break: break-all; flex: 1; }
  .urlrow .status { font-size: 0.8rem; color: #6e6e73; white-space: nowrap; }
  .urlrow .status.completed { color: #34c759; }
  .urlrow .status.failed, .urlrow .status.cancelled { color: #ff3b30; }
  .bar { height: 6px; background: #e5e5ea; border-radius: 3px; margin-top: 0.4rem; overflow: hidden; }
  .bar > div { height: 100%; background: #007aff; width: 0; transition: width 0.15s linear; }
  .reveal { font-size: 0.8rem; padding: 0.25rem 0.6rem; margin-top: 0.4rem; background: #e5e5ea; color: #1c1c1e; border-radius: 6px; cursor: pointer; border: 0; }
  .reveal:hover { background: #d1d1d6; }
</style>
</head>
<body>
<h1>audio-dl</h1>
<div class="sub">Paste URLs. Pick a format. Click Download.</div>

<form id="dl">
  <label for="urls">URLs (one per line)</label>
  <textarea id="urls" name="urls" placeholder="https://youtu.be/...&#10;https://soundcloud.com/..." required></textarea>

  <div class="row">
    <div>
      <label for="format">Format</label>
      <select id="format" name="format">__FORMAT_OPTIONS__</select>
    </div>
    <div>
      <label for="output_dir">Output folder</label>
      <input id="output_dir" name="output_dir" type="text" value="__DEFAULT_OUTPUT_DIR__" required>
    </div>
  </div>

  <div class="checkboxes">
    <label><input type="checkbox" id="playlist" name="playlist"> Full playlist</label>
    <label><input type="checkbox" id="force" name="force"> Overwrite existing</label>
  </div>

  <div class="sliders">
    <div>
      <label for="jobs">Parallel jobs <span id="jobs_val">1</span></label>
      <input id="jobs" name="jobs" type="range" min="1" max="8" value="1">
    </div>
    <div>
      <label for="fragments">Fragments / track <span id="fragments_val">4</span></label>
      <input id="fragments" name="fragments" type="range" min="1" max="16" value="4">
    </div>
  </div>

  <button type="submit" id="submit">Download</button>
</form>

<section id="jobpanel">
  <header>
    <h2>Current job</h2>
    <button type="button" class="cancel" id="cancel">Cancel</button>
  </header>
  <div id="rows"></div>
</section>

<script>
(() => {
  const CSRF_TOKEN = "__CSRF_TOKEN__";
  const $ = (id) => document.getElementById(id);
  const sliderBind = (id) => {
    const el = $(id), out = $(id + '_val');
    el.addEventListener('input', () => { out.textContent = el.value; });
  };
  sliderBind('jobs');
  sliderBind('fragments');

  let currentJobId = null;
  let es = null;
  const rows = $('rows');

  function rowFor(url) {
    let row = document.getElementById('row-' + btoa(unescape(encodeURIComponent(url))).replace(/=/g, ''));
    if (row) return row;
    row = document.createElement('div');
    row.className = 'urlrow';
    row.id = 'row-' + btoa(unescape(encodeURIComponent(url))).replace(/=/g, '');
    const top = document.createElement('div'); top.className = 'top';
    const urlDiv = document.createElement('div'); urlDiv.className = 'url';
    urlDiv.textContent = url;
    const statusDiv = document.createElement('div'); statusDiv.className = 'status';
    statusDiv.textContent = 'pending';
    top.appendChild(urlDiv); top.appendChild(statusDiv);
    const bar = document.createElement('div'); bar.className = 'bar';
    bar.appendChild(document.createElement('div'));
    const files = document.createElement('div'); files.className = 'files';
    row.appendChild(top); row.appendChild(bar); row.appendChild(files);
    rows.appendChild(row);
    return row;
  }

  function setStatus(row, text, cls) {
    const s = row.querySelector('.status');
    s.textContent = text;
    s.className = 'status ' + (cls || '');
  }

  function setBar(row, pct) {
    row.querySelector('.bar > div').style.width = pct + '%';
  }

  function fmtBytes(b) {
    if (!b) return '';
    const u = ['B','KB','MB','GB']; let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return b.toFixed(1) + u[i];
  }

  function fmtSpeed(b) { return b ? fmtBytes(b) + '/s' : ''; }

  function fmtEta(s) {
    if (s == null) return '';
    const m = Math.floor(s / 60), r = s % 60;
    return `ETA ${m}:${String(r).padStart(2,'0')}`;
  }

  function addRevealButton(row, paths) {
    const filesDiv = row.querySelector('.files');
    filesDiv.innerHTML = '';
    if (paths.length === 1) {
      const name = paths[0].split('/').pop();
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'reveal';
      btn.textContent = `Reveal: ${name}`;
      btn.onclick = () => fetch('/reveal', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Audio-DL-Token': CSRF_TOKEN},
        body: JSON.stringify({path: paths[0]})
      });
      filesDiv.appendChild(btn);
    } else {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'reveal';
      btn.textContent = `Reveal in Finder (${paths.length} files)`;
      btn.onclick = () => fetch('/reveal', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Audio-DL-Token': CSRF_TOKEN},
        body: JSON.stringify({path: paths[0]})
      });
      filesDiv.appendChild(btn);
    }
  }

  function handleEvent(ev) {
    if (ev.type === 'job_started') {
      ev.urls.forEach(u => rowFor(u.url));
    } else if (ev.type === 'url_started') {
      const row = rowFor(ev.url);
      setStatus(row, 'downloading…');
    } else if (ev.type === 'progress') {
      const row = rowFor(ev.url);
      setBar(row, ev.percent);
      const bits = [`${ev.percent.toFixed(1)}%`];
      if (ev.speed) bits.push(fmtSpeed(ev.speed));
      if (ev.eta != null) bits.push(fmtEta(ev.eta));
      setStatus(row, bits.join(' · '));
    } else if (ev.type === 'url_completed') {
      const row = rowFor(ev.url);
      setBar(row, 100);
      setStatus(row, 'completed', 'completed');
      addRevealButton(row, ev.paths);
    } else if (ev.type === 'url_failed') {
      const row = rowFor(ev.url);
      setStatus(row, ev.error || 'failed',
                ev.error === 'Cancelled' ? 'cancelled' : 'failed');
    } else if (ev.type === 'job_completed') {
      $('submit').disabled = false;
      $('cancel').disabled = true;
      es && es.close();
      es = null;
      currentJobId = null;
    }
  }

  $('dl').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('submit').disabled = true;
    $('cancel').disabled = false;
    rows.innerHTML = '';
    $('jobpanel').classList.add('active');

    const body = {
      urls: $('urls').value,
      format: $('format').value,
      output_dir: $('output_dir').value,
      playlist: $('playlist').checked,
      force: $('force').checked,
      jobs: parseInt($('jobs').value, 10),
      fragments: parseInt($('fragments').value, 10),
    };
    let resp;
    try {
      resp = await fetch('/jobs', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Audio-DL-Token': CSRF_TOKEN},
        body: JSON.stringify(body),
      });
    } catch (err) {
      alert('Failed to start: ' + err);
      $('submit').disabled = false;
      return;
    }
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({detail: resp.statusText}));
      alert('Error: ' + (detail.detail || resp.statusText));
      $('submit').disabled = false;
      return;
    }
    const {job_id} = await resp.json();
    currentJobId = job_id;
    es = new EventSource('/jobs/' + job_id + '/events?token=' + encodeURIComponent(CSRF_TOKEN));
    es.onmessage = (m) => {
      if (!m.data) return;
      try { handleEvent(JSON.parse(m.data)); } catch (e) { console.error(e, m.data); }
    };
    es.onerror = () => { /* EventSource auto-reconnects; nothing to do */ };
  });

  $('cancel').addEventListener('click', () => {
    if (currentJobId) {
      fetch('/jobs/' + currentJobId + '/cancel', {method: 'POST', headers: {'X-Audio-DL-Token': CSRF_TOKEN}});
    }
  });
})();
</script>
</body>
</html>
"""
# pylint: enable=line-too-long


# ---------------------------------------------------------------------------
# FastAPI app (endpoints filled in by later tasks)
# ---------------------------------------------------------------------------

app = FastAPI(title="audio-dl-ui", version=__version__)


class JobRequest(BaseModel):
    """Request body for POST /jobs."""

    urls: str
    format: str
    output_dir: str
    playlist: bool = False
    force: bool = False
    fragments: int = 4
    jobs: int = 1


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Render the single-page UI with format options + default output dir templated in."""
    options = "".join(
        f'<option value="{f}">{f}</option>' for f in ALL_FORMATS
    )
    default_dir = getattr(app.state, "default_output_dir",
                          os.path.expanduser("~/Downloads/audio-dl"))
    token = getattr(app.state, "csrf_token", "")
    html_doc = (
        _INDEX_HTML
        .replace("__FORMAT_OPTIONS__", options)
        # Escape default_dir before injecting into an HTML attribute value.
        # Without this, a launcher arg like --output-dir '"><script>...' breaks
        # markup and creates a self-XSS sink.
        .replace("__DEFAULT_OUTPUT_DIR__", html.escape(default_dir, quote=True))
        .replace("__CSRF_TOKEN__", token)
    )
    return HTMLResponse(html_doc)


@app.post("/jobs")
async def post_jobs(req: JobRequest, _csrf: str = Depends(_require_csrf)) -> dict:  # pylint: disable=unused-argument
    """Validate the request, register a JobState, return the job_id."""
    # Parse URLs (whitespace-separated, drop blanks).
    urls = [u.strip() for u in req.urls.split() if u.strip()]
    if not urls:
        raise HTTPException(400, "At least one URL is required.")

    if req.format not in ALL_FORMATS:
        raise HTTPException(400, f"Unknown format: {req.format!r}. Must be one of {ALL_FORMATS}.")

    if not 1 <= req.jobs <= 8:
        raise HTTPException(400, "jobs must be in 1..8.")

    if not 1 <= req.fragments <= 16:
        raise HTTPException(400, "fragments must be in 1..16.")

    output_dir = os.path.expanduser(req.output_dir)
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        raise HTTPException(400, f"output_dir not writable: {e}") from e

    job_id = uuid.uuid4().hex
    job = JobState(
        id=job_id,
        media_format=req.format,
        output_dir=output_dir,
        playlist=req.playlist,
        force=req.force,
        fragments=req.fragments,
        jobs=req.jobs,
        url_states={u: UrlState(url=u) for u in urls},
        queue=queue.Queue(maxsize=128),
    )
    JOBS[job_id] = job
    _start_job(job)
    return {"job_id": job_id}


async def _events_iter(job_id: str):
    """SSE generator: drain a job's queue and yield framed events."""
    job = JOBS.get(job_id)
    if job is None:
        # Should not happen because get_events checks first, but be defensive.
        return
    last_keepalive = time.monotonic()
    while True:
        try:
            event = await asyncio.to_thread(job.queue.get, True, 1.0)
        except queue.Empty:
            now = time.monotonic()
            if now - last_keepalive >= 30:
                yield ": keepalive\n\n"
                last_keepalive = now
            continue
        yield f"data: {json.dumps(event)}\n\n"
        last_keepalive = time.monotonic()
        if event.get("type") == "job_completed":
            return


@app.get("/jobs/{job_id}/events")
async def get_events(job_id: str, _csrf: str = Depends(_require_csrf)) -> StreamingResponse:  # pylint: disable=unused-argument
    """Stream SSE events for a job."""
    if job_id not in JOBS:
        raise HTTPException(404, f"unknown job_id: {job_id}")
    return StreamingResponse(
        _events_iter(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, _csrf: str = Depends(_require_csrf)) -> dict:  # pylint: disable=unused-argument
    """Cancel a job: set flag and shut down the executor."""
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"unknown job_id: {job_id}")
    job.cancelled = True
    if job.executor is not None:
        job.executor.shutdown(wait=False, cancel_futures=True)
    return {"ok": True}


class RevealRequest(BaseModel):
    """Request body for POST /reveal."""
    path: str


@app.post("/reveal")
async def reveal(req: RevealRequest, _csrf: str = Depends(_require_csrf)) -> dict:  # pylint: disable=unused-argument
    """Open the file in Finder. Path must match a saved file in some current job."""
    # Path-traversal guard: only allow paths that match a saved file in
    # some current JobState. Prevents arbitrary `open -R` calls from the
    # browser. Snapshot JOBS first — concurrent POST /jobs can mutate it
    # mid-iteration and raise RuntimeError otherwise.
    known = {
        p
        for job in list(JOBS.values())
        for st in list(job.url_states.values())
        for p in st.paths
    }
    if req.path not in known:
        raise HTTPException(400, "Path not found in any current job.")
    subprocess.run(["open", "-R", req.path], check=False)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Dependency pre-flight (GUI-aware)
# ---------------------------------------------------------------------------

def _show_macos_dialog(title: str, message: str) -> bool:
    """Display a native macOS dialog via ``osascript``.

    Used by the ``.app`` bundle path where stderr is invisible — without this
    the user double-clicks the app and sees nothing on missing dependencies.
    Returns True if the dialog was displayed; False on any failure (we're
    about to ``sys.exit`` anyway so the caller has nothing useful to do with
    the error).
    """
    if sys.platform != "darwin":
        return False

    def _esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script = (
        f'display dialog "{_esc(message)}" with title "{_esc(title)}" '
        f'buttons {{"OK"}} default button "OK" with icon stop'
    )
    try:
        result = subprocess.run(["osascript", "-e", script], check=False, timeout=60)
        # osascript returns nonzero when AppleScript rejects the source (syntax
        # error, unknown keyword on an old macOS, etc.). Treat nonzero as a
        # failed display so the caller falls through to the stderr path.
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _check_dependencies_gui() -> None:
    """Pre-flight dep check that surfaces failures sensibly for both shells and the ``.app``.

    Terminal users get CLI-parity stderr output. The bundled ``.app`` (no TTY)
    gets a native macOS dialog so a missing ffmpeg doesn't manifest as silent
    failure. If the dialog itself can't be shown (osascript missing on a
    Frankenstein system, syntax-rejected on a future macOS) we fall through
    to the stderr path — at least system-log capture will record the cause.
    Always exits non-zero on missing deps.
    """
    problems = _check_dependencies()
    if not problems:
        return

    no_tty = not (sys.stderr and sys.stderr.isatty())
    if no_tty and sys.platform == "darwin":
        message = "audio-dl can't start:\n\n" + "\n".join(problems)
        if _show_macos_dialog("audio-dl — missing dependency", message):
            sys.exit(1)
        # Dialog refused — fall through to stderr so the failure is at least
        # captured somewhere a developer can find it.

    for line in problems:
        print(line if line.startswith(" ") else f"ERROR: {line}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Parse args and run the uvicorn server."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--output-dir",
        default=os.path.expanduser("~/Downloads/audio-dl"),
        help="Default output directory shown in the form (default: ~/Downloads/audio-dl).",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser.")
    parser.add_argument(
        "--allow-remote", action="store_true",
        help="Allow binding to non-loopback hosts (LAN/public). Default refuses for safety.",
    )
    args = parser.parse_args()

    # Refuse non-loopback bind without explicit opt-in.
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        print(
            f"ERROR: --host {args.host!r} is not loopback. Add --allow-remote to bind to "
            "non-loopback addresses (LAN/public). Loopback: 127.0.0.1, localhost, ::1.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Generate per-launch CSRF token.
    app.state.csrf_token = secrets.token_urlsafe(32)

    _check_dependencies_gui()

    # Stash the default output dir for the index page to read.
    app.state.default_output_dir = args.output_dir

    if not args.no_browser:
        # 0.0.0.0 / :: are bind-all addresses, not routable from a browser.
        # Open the browser to the loopback address instead.
        browser_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
        threading.Timer(
            0.8, lambda: webbrowser.open(f"http://{browser_host}:{args.port}")
        ).start()

    global uvicorn  # pylint: disable=global-statement
    if uvicorn is None:
        import uvicorn as _uvicorn  # pylint: disable=import-outside-toplevel
        uvicorn = _uvicorn
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    except OSError as e:
        print(f"ERROR: cannot bind {args.host}:{args.port} — {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
