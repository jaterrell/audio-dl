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
# pylint: disable=unused-import
# The following imports are unused in this bootstrap scaffold but will be used
# in future tasks (3-11) to implement the full UI, progress hooks, job state,
# and SSE endpoints. Suppressing to allow clean bootstrap status.
import asyncio
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from dataclasses import dataclass, field
from typing import Callable, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from audio_dl import (
    ALL_FORMATS,
    check_dependencies,
    download_media,
    sanitize_url,
    __version__,
)
# pylint: enable=unused-import


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

def _emit(job: JobState, event: dict) -> None:
    """Push an SSE event onto the job's queue."""
    job.queue.put(event)


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

    clean = sanitize_url(raw_url)
    url_state.sanitized_url = clean
    url_state.status = "downloading"
    _emit(job, {"type": "url_started", "job_id": job.id,
                "url": raw_url, "sanitized_url": clean})

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
    let row = document.getElementById('row-' + btoa(url).replace(/=/g, ''));
    if (row) return row;
    row = document.createElement('div');
    row.className = 'urlrow';
    row.id = 'row-' + btoa(url).replace(/=/g, '');
    row.innerHTML = `
      <div class="top">
        <div class="url">${url}</div>
        <div class="status">pending</div>
      </div>
      <div class="bar"><div></div></div>
      <div class="files"></div>
    `;
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
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: paths[0]})
      });
      filesDiv.appendChild(btn);
    } else {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'reveal';
      btn.textContent = `Reveal folder (${paths.length} files)`;
      btn.onclick = () => fetch('/reveal', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
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
        method: 'POST', headers: {'Content-Type': 'application/json'},
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
    es = new EventSource('/jobs/' + job_id + '/events');
    es.onmessage = (m) => {
      if (!m.data) return;
      try { handleEvent(JSON.parse(m.data)); } catch (e) { console.error(e, m.data); }
    };
    es.onerror = () => { /* EventSource auto-reconnects; nothing to do */ };
  });

  $('cancel').addEventListener('click', () => {
    if (currentJobId) {
      fetch('/jobs/' + currentJobId + '/cancel', {method: 'POST'});
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
    html = (
        _INDEX_HTML
        .replace("__FORMAT_OPTIONS__", options)
        .replace("__DEFAULT_OUTPUT_DIR__", default_dir)
    )
    return HTMLResponse(html)


@app.post("/jobs")
async def post_jobs(req: JobRequest) -> dict:
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
        queue=queue.Queue(),
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
async def get_events(job_id: str) -> StreamingResponse:
    """Stream SSE events for a job."""
    if job_id not in JOBS:
        raise HTTPException(404, f"unknown job_id: {job_id}")
    return StreamingResponse(
        _events_iter(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
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
async def reveal(req: RevealRequest) -> dict:
    """Open the file in Finder. Path must match a saved file in some current job."""
    # Path-traversal guard: only allow paths that match a saved file in
    # some current JobState. Prevents arbitrary `open -R` calls from the
    # browser.
    known = {
        p
        for job in JOBS.values()
        for st in job.url_states.values()
        for p in st.paths
    }
    if req.path not in known:
        raise HTTPException(400, "Path not found in any current job.")
    subprocess.run(["open", "-R", req.path], check=False)
    return {"ok": True}


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
    args = parser.parse_args()

    check_dependencies()

    # Stash the default output dir for the index page to read.
    app.state.default_output_dir = args.output_dir

    if not args.no_browser:
        threading.Timer(
            0.8, lambda: webbrowser.open(f"http://{args.host}:{args.port}")
        ).start()

    import uvicorn  # pylint: disable=import-outside-toplevel
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    except OSError as e:
        print(f"ERROR: cannot bind {args.host}:{args.port} — {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
