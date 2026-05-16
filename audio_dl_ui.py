#!/usr/bin/env python3
# pylint: disable=too-many-lines
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
    """Holds the entire state of a batch download job, including all URL states.

    Broadcast architecture (v1.3): every SSE subscriber registers its own
    ``queue.Queue`` and ``_emit`` fans events out to all of them, so a
    reconnect-during-job no longer races and splits events between connections.

    New subscribers receive a single ``job_snapshot`` event (cumulative
    state) on connect — they don't replay historical events. The UI is
    state-driven, not event-replay-driven; the snapshot captures everything
    a fresh subscriber needs to render the current state without ambiguity
    about which past events to apply.

    ``lock`` protects ``subscribers``; ``_emit`` snapshots the subscriber
    list under the lock before fanning out, so registration and broadcast
    can't race.
    """

    id: str
    media_format: str
    output_dir: str
    playlist: bool
    force: bool
    fragments: int
    jobs: int
    url_states: dict[str, UrlState]
    subscribers: list["queue.Queue[dict]"] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    cancelled: bool = False
    completed: bool = False
    executor: ThreadPoolExecutor | None = None


JOBS: dict[str, JobState] = {}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

# Terminal events must always be delivered even if the queue is full;
# progress events can be dropped (they're throttled to ~5/sec/URL upstream
# and a missed sample is harmless). ``job_snapshot`` is delivered out-of-band
# (yielded directly by _events_iter before draining the queue) so it doesn't
# appear here.
_TERMINAL_EVENT_TYPES = frozenset({
    "url_started", "url_completed", "url_failed", "job_completed",
})


def _put_with_overflow(q: "queue.Queue[dict]", event: dict) -> None:
    """Push one event onto one subscriber's queue with overflow handling.

    Terminal events take a small block-with-timeout so a momentarily-full
    queue still gets the lifecycle signal. If the timeout expires, drop the
    oldest event to make room — silently losing a terminal event would hang
    the client UI. Progress events use put_nowait and drop on Full.
    """
    if event.get("type") in _TERMINAL_EVENT_TYPES:
        try:
            q.put(event, timeout=1.0)
            return
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # truly stuck; worst-case outcome
    else:
        try:
            q.put_nowait(event)
        except queue.Full:
            pass  # drop excess progress


def _emit(job: JobState, event: dict) -> None:
    """Broadcast an SSE event to every subscriber currently connected.

    Snapshots the subscriber list under the lock so register/unregister can't
    mutate it mid-iteration. The actual ``put`` happens without the lock so
    a slow consumer doesn't block emitters.
    """
    if event.get("type") == "job_completed":
        job.completed = True
    with job.lock:
        subs = list(job.subscribers)
    for q in subs:
        _put_with_overflow(q, event)


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
    """Spin up the executor and supervisor. Called from POST /jobs.

    v1.3: there is no ``job_started`` event anymore. The initial state of all
    URLs is conveyed via the ``job_snapshot`` event that every SSE subscriber
    receives on connect. This sidesteps the race where a subscriber connects
    after ``_start_job`` and would otherwise miss the original ``job_started``
    in a pure-broadcast model.
    """
    job.executor = ThreadPoolExecutor(max_workers=job.jobs)
    futures = [
        job.executor.submit(_run_one, job, url)
        for url in job.url_states
    ]
    supervisor = threading.Thread(target=_supervise, args=(job, futures), daemon=True)
    supervisor.start()


# pylint: disable=line-too-long
_INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="csrf-token" content="__CSRF_TOKEN__">
<title>audio-dl</title>
<script>
// Synchronous boot: set data-theme before paint to avoid FOUC.
// Slug list duplicated here (rather than referencing window.THEMES) because
// the THEMES const lives in the deferred end-of-body <script>.
(function() {{
  const SLUGS = ['phosphor','rose','moon','dawn','amber','solarized','gruvbox','tokyo','atom','claude'];
  let chosen = null;
  try {{
    const stored = localStorage.getItem('audio-dl-theme');
    if (stored && SLUGS.indexOf(stored) >= 0) chosen = stored;
  }} catch (e) {{ /* localStorage unavailable; fall through */ }}
  if (!chosen) {{
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {{
      chosen = 'dawn';
    }} else {{
      chosen = 'phosphor';
    }}
  }}
  document.documentElement.dataset.theme = chosen;
}})();
</script>
<style>
{css_base}
{css_themes}
</style>
</head>
<body>
{html_body}
<script>
{js}
</script>
</body>
</html>
"""

_INDEX_CSS_BASE = """  :root {
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, 'Cascadia Code', monospace;
    font-size: 13px;
    line-height: 1.5;
  }
  body {
    max-width: 760px; margin: 2rem auto; padding: 1.5rem;
    background: var(--bg); color: var(--fg);
    -webkit-font-smoothing: antialiased;
  }
  .frame { white-space: pre; color: var(--frame); line-height: 1.25; }
  .frame .title { color: var(--accent); font-weight: 400; }
  .frame .theme-btn {
    color: var(--accent); background: rgba(255,255,255,0.04);
    padding: 0 6px; cursor: pointer; user-select: none;
  }
  .frame .theme-btn:hover { background: rgba(255,255,255,0.08); }
  .body-section { padding-left: 2px; margin: 4px 0; }
  .body-section .field-line { display: flex; align-items: baseline; gap: 4px; }
  .label { color: var(--label); display: inline-block; min-width: 9ch; }
  .marker { color: var(--accent); }
  .accent { color: var(--accent); }
  .ok { color: var(--ok); }
  .err { color: var(--err); }
  .warn { color: var(--warn); }
  .live { color: var(--live); }
  .dim { color: var(--dim); }
  .bar-graph { color: var(--bar); }
  input.field, textarea.field, select.field {
    background: transparent; color: var(--fg); border: 0; padding: 0;
    font: inherit; outline: 0; flex: 1;
  }
  textarea.field { resize: vertical; min-height: 3.5rem; width: 100%; }
  select.field { cursor: pointer; }
  input[type=range].slider {
    appearance: none; -webkit-appearance: none;
    height: 6px; background: var(--frame); border-radius: 3px; outline: 0;
    flex: 1; max-width: 200px;
  }
  input[type=range].slider::-webkit-slider-thumb {
    appearance: none; -webkit-appearance: none;
    width: 12px; height: 12px; border-radius: 50%;
    background: var(--accent); cursor: pointer;
  }
  input[type=range].slider::-moz-range-thumb {
    width: 12px; height: 12px; border-radius: 50%;
    background: var(--accent); cursor: pointer; border: 0;
  }
  button.tui-btn {
    color: var(--btn-fg); background: var(--accent);
    border: 0; padding: 2px 12px; font: inherit; font-weight: 600;
    cursor: pointer;
  }
  button.tui-btn:hover { filter: brightness(1.1); }
  button.tui-btn:disabled { opacity: 0.4; cursor: default; }
  button.cancel-btn {
    background: transparent; color: var(--err);
    border: 1px solid var(--frame); padding: 1px 8px;
    font: inherit; font-size: 11px; cursor: pointer;
  }
  .summary { color: var(--dim); }
  .live-pulse { animation: pulse 1.4s ease-in-out infinite; }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  @media (prefers-reduced-motion: reduce) {
    .live-pulse { animation: none; }
  }
  .url-row { padding: 4px 0; }
  .url-row .url { color: var(--fg); word-break: break-all; }
  .url-row .reveal-btn {
    background: transparent; color: var(--accent);
    border: 1px solid var(--frame); padding: 0 6px;
    font: inherit; font-size: 11px; cursor: pointer; margin-left: 8px;
  }
  /* Popover (added in Task 6 — styles defined here for cohesion) */
  #theme-popover[hidden] { display: none; }
  #theme-popover {
    position: fixed; top: 60px; right: 24px; width: 360px;
    background: var(--bg); color: var(--fg);
    border: 1px solid var(--frame); border-radius: 6px;
    padding: 14px; z-index: 100;
    box-shadow: 0 8px 32px rgba(0,0,0,0.6);
    font-size: 11px;
  }
  #theme-popover .pop-header {
    color: var(--accent); font-weight: 600; margin-bottom: 4px;
    display: flex; justify-content: space-between; align-items: center;
  }
  #theme-popover .pop-sub { color: var(--dim); font-size: 10px; margin-bottom: 12px; }
  #theme-popover input.pop-search {
    background: var(--bg); border: 1px solid var(--frame); border-radius: 4px;
    padding: 5px 8px; color: var(--fg); font: inherit;
    width: 100%; box-sizing: border-box; margin-bottom: 12px; outline: 0;
  }
  #theme-popover input.pop-search:focus { border-color: var(--accent); }
  #theme-popover .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  #theme-popover .thumb {
    border-radius: 4px; overflow: hidden; cursor: pointer;
    border: 2px solid transparent; padding: 0; background: transparent;
    font: inherit; text-align: left;
  }
  #theme-popover .thumb:hover { border-color: var(--frame); }
  #theme-popover .thumb.active { border-color: var(--accent); }
  #theme-popover .thumb:focus { outline: 0; border-color: var(--accent); }
  #theme-popover .thumb .preview {
    padding: 6px 8px; font-size: 8px; line-height: 1.3; min-height: 48px;
  }
  #theme-popover .thumb .name {
    background: rgba(0,0,0,0.4); padding: 4px 8px; font-size: 9px;
    color: var(--fg); display: flex; justify-content: space-between;
  }
  @media (max-width: 480px) {
    #theme-popover { left: 10px; right: 10px; width: auto; }
  }
"""

_INDEX_CSS_THEMES = """  :root[data-theme="phosphor"] {
    --bg: #000;        --fg: #d0d0d0;     --frame: #1a4a1a;  --label: #707070;
    --accent: #00ff88; --ok: #00ff88;     --err: #ff5555;    --warn: #ffaa33;
    --live: #00d9ff;   --dim: #555;       --bar: #00d9ff;    --btn-fg: #000;
  }
  :root[data-theme="rose"] {
    --bg: #191724;     --fg: #e0def4;     --frame: #403d52;  --label: #908caa;
    --accent: #ebbcba; --ok: #9ccfd8;     --err: #eb6f92;    --warn: #f6c177;
    --live: #c4a7e7;   --dim: #6e6a86;    --bar: #c4a7e7;    --btn-fg: #191724;
  }
  :root[data-theme="moon"] {
    --bg: #232136;     --fg: #e0def4;     --frame: #44415a;  --label: #908caa;
    --accent: #ea9a97; --ok: #9ccfd8;     --err: #eb6f92;    --warn: #f6c177;
    --live: #c4a7e7;   --dim: #6e6a86;    --bar: #c4a7e7;    --btn-fg: #232136;
  }
  :root[data-theme="dawn"] {
    --bg: #faf4ed;     --fg: #575279;     --frame: #cecacd;  --label: #797593;
    --accent: #d7827e; --ok: #56949f;     --err: #b4637a;    --warn: #ea9d34;
    --live: #907aa9;   --dim: #9893a5;    --bar: #907aa9;    --btn-fg: #faf4ed;
  }
  :root[data-theme="amber"] {
    --bg: #0a0600;     --fg: #ffb000;     --frame: #4a3000;  --label: #8a5a00;
    --accent: #ffb000; --ok: #ffb000;     --err: #ff4500;    --warn: #ff8800;
    --live: #ff8800;   --dim: #4a3000;    --bar: #ff8800;    --btn-fg: #0a0600;
  }
  :root[data-theme="solarized"] {
    --bg: #002b36;     --fg: #93a1a1;     --frame: #073642;  --label: #586e75;
    --accent: #b58900; --ok: #859900;     --err: #dc322f;    --warn: #cb4b16;
    --live: #2aa198;   --dim: #586e75;    --bar: #268bd2;    --btn-fg: #002b36;
  }
  :root[data-theme="gruvbox"] {
    --bg: #282828;     --fg: #ebdbb2;     --frame: #504945;  --label: #928374;
    --accent: #fabd2f; --ok: #b8bb26;     --err: #fb4934;    --warn: #fe8019;
    --live: #8ec07c;   --dim: #665c54;    --bar: #83a598;    --btn-fg: #282828;
  }
  :root[data-theme="tokyo"] {
    --bg: #1a1b26;     --fg: #c0caf5;     --frame: #565f89;  --label: #565f89;
    --accent: #bb9af7; --ok: #9ece6a;     --err: #f7768e;    --warn: #e0af68;
    --live: #7dcfff;   --dim: #414868;    --bar: #7dcfff;    --btn-fg: #1a1b26;
  }
  :root[data-theme="atom"] {
    --bg: #282c34;     --fg: #abb2bf;     --frame: #3e4451;  --label: #5c6370;
    --accent: #c678dd; --ok: #98c379;     --err: #e06c75;    --warn: #d19a66;
    --live: #61afef;   --dim: #4b5263;    --bar: #61afef;    --btn-fg: #282c34;
  }
  :root[data-theme="claude"] {
    --bg: #181513;     --fg: #efe9d9;     --frame: #4d4641;  --label: #8a7a6a;
    --accent: #d97757; --ok: #88a86c;     --err: #d5524d;    --warn: #d99155;
    --live: #e8a866;   --dim: #4d4641;    --bar: #e8a866;    --btn-fg: #181513;
  }
"""

_INDEX_HTML_BODY = """<div class="frame">┌─ <span class="title">audio-dl</span> <span class="dim">─────────────── v__VERSION__ ──── </span><span class="theme-btn" id="theme-btn">theme: <span id="theme-current">phosphor</span> ▾</span> <span class="dim">─┐</span></div>
<form id="dl">
  <div class="body-section">
    <div class="field-line"><span class="label">urls</span><span class="marker">▸</span> <textarea class="field" id="urls" name="urls" placeholder="https://youtu.be/...&#10;https://soundcloud.com/..." required></textarea></div>
    <div class="field-line"><span class="label">format</span><span class="marker">▸</span> <select class="field" id="format" name="format" style="max-width:180px;">__FORMAT_OPTIONS__</select></div>
    <div class="field-line"><span class="label">output</span><span class="marker">▸</span> <input class="field" id="output_dir" name="output_dir" type="text" value="__DEFAULT_OUTPUT_DIR__" required></div>
    <div class="field-line"><span class="label">jobs</span><span class="marker">▸</span> <input class="slider" id="jobs" name="jobs" type="range" min="1" max="8" value="1"> <span id="jobs_val" class="dim">1</span></div>
    <div class="field-line"><span class="label">fragments</span><span class="marker">▸</span> <input class="slider" id="fragments" name="fragments" type="range" min="1" max="16" value="4"> <span id="fragments_val" class="dim">4</span></div>
    <div class="field-line"><span class="label">flags</span><span class="marker">▸</span> <label style="margin-right:12px;"><input type="checkbox" id="playlist" name="playlist"> playlist</label> <label><input type="checkbox" id="force" name="force"> overwrite</label></div>
    <div class="field-line" style="margin-top:8px;"><span class="label"></span><button type="submit" class="tui-btn" id="submit">[ download ]</button> <span class="dim">⌘↵</span></div>
  </div>
</form>

<section id="jobpanel" hidden>
  <div class="frame">├─ <span class="accent">job</span> <span class="dim">─ </span><span class="summary" id="job-summary">0 done · 0 active · 0 fail</span> <span class="dim">─</span> <button type="button" class="cancel-btn" id="cancel">esc</button> <span class="dim">┤</span></div>
  <div class="body-section" id="rows"></div>
</section>

<div class="frame">└<span class="dim">────────────────────────────────────────┘</span></div>

<div id="theme-popover" hidden role="dialog" aria-label="Switch theme">
  <div class="pop-header"><span>switch theme</span><span class="dim">⌘T to cycle</span></div>
  <div class="pop-sub">click to apply · saved to localStorage</div>
  <input class="pop-search" id="pop-search" placeholder="search…" autocomplete="off">
  <div class="grid" id="pop-grid"></div>
</div>
"""

_INDEX_JS = """const THEMES = [
  { slug: 'phosphor',  name: 'Phosphor Green',  default: true },
  { slug: 'rose',      name: 'Rose Pine'                       },
  { slug: 'moon',      name: 'Rose Pine Moon'                  },
  { slug: 'dawn',      name: 'Rose Pine Dawn',  light: true    },
  { slug: 'amber',     name: 'Amber CRT'                       },
  { slug: 'solarized', name: 'Solarized Dark'                  },
  { slug: 'gruvbox',   name: 'Gruvbox Dark'                    },
  { slug: 'tokyo',     name: 'Tokyo Night'                     },
  { slug: 'atom',      name: 'Atom Dark Pro'                   },
  { slug: 'claude',    name: 'Claude'                          },
];

(() => {
  const CSRF_TOKEN = "__CSRF_TOKEN__";
  const $ = (id) => document.getElementById(id);

  // Slider value bindings (sync the displayed number).
  const sliderBind = (id) => {
    const el = $(id), out = $(id + '_val');
    el.addEventListener('input', () => { out.textContent = el.value; });
  };
  sliderBind('jobs');
  sliderBind('fragments');

  let currentJobId = null;
  let es = null;
  const rows = $('rows');
  const summary = $('job-summary');
  let counts = { done: 0, active: 0, fail: 0 };

  function refreshSummary() {
    summary.textContent = `${counts.done} done · ${counts.active} active · ${counts.fail} fail`;
  }

  function rowFor(url) {
    const id = 'row-' + btoa(unescape(encodeURIComponent(url))).replace(/=/g, '');
    let row = document.getElementById(id);
    if (row) return row;
    row = document.createElement('div');
    row.className = 'url-row';
    row.id = id;
    // Format: [GLYPH] <url>  <progress>  <reveal-btn>
    row.innerHTML = `<span class="glyph dim">[--]</span> <span class="url">${escapeHtml(url)}</span> <span class="progress dim"></span><span class="files"></span>`;
    rows.appendChild(row);
    return row;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
    ));
  }

  function setGlyph(row, glyph, cls, pulse) {
    const g = row.querySelector('.glyph');
    g.textContent = glyph;
    g.className = 'glyph ' + cls + (pulse ? ' live-pulse' : '');
    // Track the row's last-known status class so handlers can avoid
    // double-counting transitions (e.g., url_failed for a row that
    // was never `active` because cancel hit before url_started).
    row.dataset.status = cls;
  }

  function setProgress(row, pct, extras) {
    const p = row.querySelector('.progress');
    if (pct == null) {
      p.textContent = extras || '';
      p.className = 'progress dim';
      return;
    }
    // Clamp filled to [0, 18] — yt-dlp can report pct > 100 for
    // fragmented downloads with estimated totals, which would make
    // (18 - filled) negative and crash String.repeat() with RangeError.
    const filled = Math.max(0, Math.min(18, Math.round(pct / 100 * 18)));
    const bar = '▓'.repeat(filled) + '░'.repeat(18 - filled);
    // bar uses only ▓/░ (HTML-safe). Escape `extras` since it can come
    // from progressExtras() today but might carry user-controlled text
    // (filenames, error strings) in future callers.
    const extrasHtml = extras ? ` <span class="dim">${escapeHtml(extras)}</span>` : '';
    p.innerHTML = `<span class="bar-graph">${bar}</span> <span class="live">${pct.toFixed(1)}%</span>${extrasHtml}`;
    p.className = 'progress';
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
    return `${m}:${String(r).padStart(2,'0')} left`;
  }
  function progressExtras(speed, eta) {
    const bits = [];
    if (speed) bits.push(fmtSpeed(speed));
    if (eta != null) bits.push(fmtEta(eta));
    return bits.join(' · ');
  }

  function addRevealButton(row, paths) {
    const filesDiv = row.querySelector('.files');
    filesDiv.innerHTML = '';
    const name = paths[0].split('/').pop();
    const label = paths.length === 1 ? `↗ ${name}` : `↗ ${paths.length} files`;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'reveal-btn';
    btn.textContent = label;
    btn.onclick = () => fetch('/reveal', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Audio-DL-Token': CSRF_TOKEN},
      body: JSON.stringify({path: paths[0]})
    });
    filesDiv.appendChild(btn);
  }

  function applyUrlState(row, u) {
    if (u.status === 'pending') {
      setGlyph(row, '[--]', 'dim');
      setProgress(row, null, 'queued');
    } else if (u.status === 'downloading') {
      setGlyph(row, '[..]', 'live', true);
      setProgress(row, u.percent, progressExtras(u.speed, u.eta));
    } else if (u.status === 'completed') {
      setGlyph(row, '[OK]', 'ok');
      setProgress(row, 100, '');
      if (u.paths && u.paths.length) addRevealButton(row, u.paths);
    } else if (u.status === 'failed') {
      setGlyph(row, '[!!]', 'err');
      setProgress(row, null, u.error || 'failed');
    } else if (u.status === 'cancelled') {
      setGlyph(row, '[xx]', 'err');
      setProgress(row, null, 'cancelled');
    }
  }

  // Derive counts from current row states (the DOM, via dataset.status set
  // by setGlyph). Idempotent — called after every state transition rather
  // than incrementing on each event. Avoids drift when a job_snapshot's
  // states overlap with queued live events from the same connection window
  // (the SSE broadcast can deliver both for the same URL).
  function recountFromDOM() {
    const next = { done: 0, active: 0, fail: 0 };
    rows.querySelectorAll('.url-row').forEach(row => {
      const s = row.dataset.status;
      if (s === 'ok') next.done++;
      else if (s === 'live') next.active++;
      else if (s === 'err') next.fail++;
    });
    counts = next;
    refreshSummary();
  }

  function handleEvent(ev) {
    if (ev.type === 'job_snapshot') {
      ev.urls.forEach(u => {
        const row = rowFor(u.url);
        applyUrlState(row, u);
      });
      recountFromDOM();
      if (ev.complete) {
        $('submit').disabled = false;
        $('cancel').disabled = true;
      }
    } else if (ev.type === 'url_started') {
      const row = rowFor(ev.url);
      setGlyph(row, '[..]', 'live', true);
      setProgress(row, 0, '');
      recountFromDOM();
    } else if (ev.type === 'progress') {
      const row = rowFor(ev.url);
      setGlyph(row, '[..]', 'live', true);
      setProgress(row, ev.percent, progressExtras(ev.speed, ev.eta));
    } else if (ev.type === 'url_completed') {
      const row = rowFor(ev.url);
      setGlyph(row, '[OK]', 'ok');
      setProgress(row, 100, '');
      addRevealButton(row, ev.paths);
      recountFromDOM();
    } else if (ev.type === 'url_failed') {
      const row = rowFor(ev.url);
      const cancelled = ev.error === 'Cancelled';
      setGlyph(row, cancelled ? '[xx]' : '[!!]', 'err');
      setProgress(row, null, ev.error || 'failed');
      recountFromDOM();
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
    counts = { done: 0, active: 0, fail: 0 };
    refreshSummary();
    $('jobpanel').hidden = false;

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
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Audio-DL-Token': CSRF_TOKEN},
        body: JSON.stringify(body),
      });
    } catch (err) {
      alert('Failed to start: ' + err);
      $('submit').disabled = false;
      $('cancel').disabled = true;
      return;
    }
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({detail: resp.statusText}));
      alert('Error: ' + (detail.detail || resp.statusText));
      $('submit').disabled = false;
      $('cancel').disabled = true;
      return;
    }
    const {job_id} = await resp.json();
    currentJobId = job_id;
    es = new EventSource('/jobs/' + job_id + '/events?token=' + encodeURIComponent(CSRF_TOKEN));
    es.onmessage = (m) => {
      if (!m.data) return;
      try { handleEvent(JSON.parse(m.data)); } catch (e) { console.error(e, m.data); }
    };
    es.onerror = () => { /* EventSource auto-reconnects */ };
  });

  $('cancel').addEventListener('click', () => {
    if (currentJobId) {
      fetch('/jobs/' + currentJobId + '/cancel', {
        method: 'POST',
        headers: {'X-Audio-DL-Token': CSRF_TOKEN}
      });
    }
  });

  // Reflect the active theme in the header button.
  function refreshThemeLabel() {
    const cur = document.documentElement.dataset.theme || 'phosphor';
    $('theme-current').textContent = cur;
  }
  refreshThemeLabel();
  window.refreshThemeLabel = refreshThemeLabel;  // Picker (Task 6) calls this on change.

  // ── Theme picker popover ────────────────────────────────────────────
  const popover = $('theme-popover');
  const popGrid = $('pop-grid');
  const popSearch = $('pop-search');
  const themeBtn = $('theme-btn');

  function applyTheme(slug) {
    document.documentElement.dataset.theme = slug;
    try { localStorage.setItem('audio-dl-theme', slug); }
    catch (e) { /* localStorage unavailable; theme is session-only */ }
    refreshThemeLabel();
    renderThumbs(popSearch.value);
  }

  function renderThumbs(filter) {
    const f = (filter || '').toLowerCase().trim();
    const cur = document.documentElement.dataset.theme || 'phosphor';
    popGrid.innerHTML = '';
    THEMES.filter(t => !f || t.name.toLowerCase().includes(f) || t.slug.toLowerCase().includes(f))
      .forEach(t => {
        const el = document.createElement('button');
        el.type = 'button';
        el.className = 'thumb' + (t.slug === cur ? ' active' : '');
        el.dataset.slug = t.slug;
        // Render thumbnail using inline CSS from the theme's :root vars.
        const styles = getComputedStyleForTheme(t.slug);
        el.innerHTML = `
          <div class="preview" style="background:${styles.bg};color:${styles.fg};">
            <div style="color:${styles.accent}">┌─ ${t.slug} ─┐</div>
            <div><span style="color:${styles.label}">▸</span> <span style="color:${styles.accent}">downloading</span></div>
            <div><span style="color:${styles.live}">[..]</span> <span style="color:${styles.live}">73%</span></div>
            <div><span style="color:${styles.ok}">[OK]</span> done</div>
          </div>
          <div class="name" style="background:rgba(0,0,0,0.4);color:${styles.fg};">
            <span>${t.name}${t.default ? ' <span style="color:'+styles.accent+'">·default</span>' : ''}</span>
            ${t.slug === cur ? '<span style="color:'+styles.accent+'">✓</span>' : ''}
          </div>`;
        el.addEventListener('click', () => { applyTheme(t.slug); closePopover(); });
        popGrid.appendChild(el);
      });
  }

  // Read each theme's computed CSS-vars by temporarily swapping data-theme
  // on documentElement and reading getComputedStyle. Restores the previous
  // value before returning. Costs N forced layouts when the popover opens
  // (10 themes), which is fine — popover open is a rare interaction and
  // modern browsers handle this in single-digit ms.
  function getComputedStyleForTheme(slug) {
    const prev = document.documentElement.dataset.theme;
    document.documentElement.dataset.theme = slug;
    const cs = getComputedStyle(document.documentElement);
    const styles = {
      bg: cs.getPropertyValue('--bg').trim(), fg: cs.getPropertyValue('--fg').trim(),
      accent: cs.getPropertyValue('--accent').trim(), ok: cs.getPropertyValue('--ok').trim(),
      live: cs.getPropertyValue('--live').trim(), label: cs.getPropertyValue('--label').trim(),
    };
    document.documentElement.dataset.theme = prev;
    return styles;
  }

  function openPopover() {
    popover.hidden = false;
    themeBtn.setAttribute('aria-expanded', 'true');
    renderThumbs('');
    popSearch.value = '';
    setTimeout(() => popSearch.focus(), 0);
  }

  function closePopover() {
    popover.hidden = true;
    themeBtn.setAttribute('aria-expanded', 'false');
  }

  themeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (popover.hidden) openPopover(); else closePopover();
  });

  popSearch.addEventListener('input', () => renderThumbs(popSearch.value));

  // Click-outside closes the popover (mousedown for snappy close).
  document.addEventListener('mousedown', (e) => {
    if (popover.hidden) return;
    if (popover.contains(e.target) || themeBtn.contains(e.target)) return;
    closePopover();
  });

  // ── Keyboard shortcuts ──────────────────────────────────────────────
  const IS_MAC = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
  const cmdKey = (e) => IS_MAC ? e.metaKey : e.ctrlKey;

  function cycleTheme() {
    const cur = document.documentElement.dataset.theme || 'phosphor';
    const idx = THEMES.findIndex(t => t.slug === cur);
    const next = THEMES[(idx + 1) % THEMES.length];
    applyTheme(next.slug);
  }

  document.addEventListener('keydown', (e) => {
    // esc: close popover (priority) OR cancel job
    if (e.key === 'Escape') {
      if (!popover.hidden) {
        closePopover();
        e.preventDefault();
        return;
      }
      if (currentJobId && !$('cancel').disabled) {
        $('cancel').click();
        e.preventDefault();
      }
      return;
    }
    // ⌘↵ / Ctrl+↵: submit form (works inside textarea too)
    // requestSubmit() — not dispatchEvent(new Event('submit')) — so HTML
    // constraint validation (required, etc.) runs, matching the behavior
    // of a button click. A synthetic submit event bypasses validation.
    if (cmdKey(e) && e.key === 'Enter') {
      if (!$('submit').disabled) {
        $('dl').requestSubmit();
        e.preventDefault();
      }
      return;
    }
    // ⌘T: cycle theme inline (don't open popover)
    // Note: macOS Safari intercepts ⌘T for "new tab" — preventDefault
    // wins here only when the page has focus.
    if (cmdKey(e) && e.key.toLowerCase() === 't') {
      cycleTheme();
      e.preventDefault();
      return;
    }
    // ⌘K: open picker with search focused
    if (cmdKey(e) && e.key.toLowerCase() === 'k') {
      if (popover.hidden) openPopover();
      else closePopover();
      e.preventDefault();
      return;
    }
  });

  // Picker grid keyboard nav: arrow up/down moves focus; enter selects.
  popover.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const thumbs = Array.from(popGrid.querySelectorAll('.thumb'));
      if (!thumbs.length) return;
      const focused = document.activeElement;
      let idx = thumbs.indexOf(focused);
      if (idx < 0) idx = 0;
      else idx = (idx + (e.key === 'ArrowDown' ? 1 : -1) + thumbs.length) % thumbs.length;
      thumbs[idx].focus();
      e.preventDefault();
    } else if (e.key === 'Enter' && document.activeElement.classList.contains('thumb')) {
      const slug = document.activeElement.dataset.slug;
      applyTheme(slug);
      closePopover();
      e.preventDefault();
    }
  });
})();
"""
# pylint: enable=line-too-long


def _render_index(token: str, options: str, default_dir: str) -> str:
    """Assemble the full HTML page from the split constants.

    Substitutions:
      - {css_base}, {css_themes}, {html_body}, {js} into _INDEX_TEMPLATE
      - __CSRF_TOKEN__, __FORMAT_OPTIONS__, __DEFAULT_OUTPUT_DIR__,
        __VERSION__ into the body/JS
    The escape on default_dir guards against attribute-XSS via launcher arg.
    """
    page = _INDEX_TEMPLATE.format(
        css_base=_INDEX_CSS_BASE,
        css_themes=_INDEX_CSS_THEMES,
        html_body=_INDEX_HTML_BODY,
        js=_INDEX_JS,
    )
    return (
        page
        .replace("__FORMAT_OPTIONS__", options)
        .replace("__DEFAULT_OUTPUT_DIR__", html.escape(default_dir, quote=True))
        .replace("__CSRF_TOKEN__", token)
        .replace("__VERSION__", __version__)
    )


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
    return HTMLResponse(_render_index(token, options, default_dir))


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
    )
    JOBS[job_id] = job
    _start_job(job)
    return {"job_id": job_id}


def _build_snapshot(job: JobState) -> dict:
    """Build a ``job_snapshot`` event describing the job's current state.

    Sent as the first event to every new SSE subscriber so a reconnecting or
    late-joining browser can rebuild its UI without having received the
    original ``job_started``/``progress``/``url_completed`` sequence. Includes
    a ``complete`` flag so a subscriber that connects after ``job_completed``
    can still flip its UI to the terminal state.
    """
    summary: dict | None = None
    if job.completed:
        summary = {
            "completed": sum(1 for s in job.url_states.values() if s.status == "completed"),
            "failed": sum(
                1 for s in job.url_states.values()
                if s.status in ("failed", "cancelled")
            ),
        }
    return {
        "type": "job_snapshot",
        "job_id": job.id,
        "complete": job.completed,
        "summary": summary,
        "urls": [
            {
                "url": s.url,
                "status": s.status,
                "percent": s.percent,
                "downloaded_bytes": s.downloaded_bytes,
                "total_bytes": s.total_bytes,
                "speed": s.speed,
                "eta": s.eta,
                "filename": s.filename,
                "paths": list(s.paths),
                "error": s.error,
            }
            for s in job.url_states.values()
        ],
    }


async def _events_iter(job_id: str):
    """SSE generator: register as a subscriber, yield snapshot, live-stream.

    Sequence:

    1. Register a per-connection ``queue.Queue`` in ``job.subscribers``
       under ``job.lock``.
    2. Yield a single ``job_snapshot`` event capturing cumulative state
       (URL list, per-URL status/percent, completion flag, summary). The
       UI is state-driven; the snapshot is everything a fresh subscriber
       needs to render correctly without trying to apply a historical
       event sequence (and without the duplicate-event semantics that a
       snapshot+replay design would create).
    3. If the job was already complete when the subscriber connected, the
       snapshot conveys that (``complete=True``, ``summary`` populated)
       and the generator returns immediately — no point keeping the
       connection open.
    4. Otherwise, live-stream events from the per-connection queue until
       ``job_completed`` or the client disconnects.

    The ``finally`` block removes this subscriber on generator close so
    dead subscribers don't leak (uvicorn cancels the task on client
    disconnect).
    """
    job = JOBS.get(job_id)
    if job is None:
        # get_events checks first, but be defensive.
        return
    sub_queue: "queue.Queue[dict]" = queue.Queue(maxsize=128)
    with job.lock:
        job.subscribers.append(sub_queue)
    try:
        yield f"data: {json.dumps(_build_snapshot(job))}\n\n"
        if job.completed:
            return
        last_keepalive = time.monotonic()
        while True:
            try:
                event = await asyncio.to_thread(sub_queue.get, True, 1.0)
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
    finally:
        with job.lock:
            try:
                job.subscribers.remove(sub_queue)
            except ValueError:
                pass  # already removed; no-op


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
