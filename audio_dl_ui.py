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
import collections
import html
import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from dataclasses import dataclass, field
from typing import Callable, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
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
    # v1.6 — rich card fields
    title: str | None = None
    uploader: str | None = None
    duration: int | None = None
    thumbnail_ready: bool = False
    phase: str | None = None
    log: "collections.deque[dict]" = field(
        default_factory=lambda: collections.deque(maxlen=50)
    )
    # Tracks whether url_metadata has already been emitted (so we don't
    # re-emit on every hook tick — only on first info-dict and on
    # thumb-fetched).
    metadata_emitted: bool = False


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


_LOG_KEEP_PREFIXES = (
    "[hls] downloading fragment",
    "[ffmpeg]",
    "[ExtractAudio]",
    "[EmbedThumbnail]",
    "[Metadata]",
)


def _should_keep_log(level: str, text: str) -> bool:
    """Filter yt-dlp log lines down to ones worth showing the user."""
    if level in ("warning", "error"):
        return True
    if level == "debug":
        return False
    # level == "info" (or anything else): keep only known phase markers
    return any(text.startswith(p) for p in _LOG_KEEP_PREFIXES)


def _pick_thumbnail_url(info: dict) -> str | None:
    """Pick a reasonable thumbnail URL from a yt-dlp info dict.

    Prefers the largest thumbnail with width <= 480 (good for our 120px
    card thumbs without retina-blur). Falls back to the smallest width
    if none are <= 480, then the singular ``thumbnail`` field, then None.
    """
    thumbs = info.get("thumbnails") or []
    sized = [t for t in thumbs if isinstance(t.get("width"), int)]
    if sized:
        small = [t for t in sized if t["width"] <= 480]
        if small:
            chosen = max(small, key=lambda t: t["width"])
        else:
            chosen = min(sized, key=lambda t: t["width"])
        return chosen.get("url")
    if thumbs:
        return thumbs[0].get("url")
    return info.get("thumbnail") or None


_THUMB_ROOT = os.path.join(tempfile.gettempdir(), "audio-dl-thumbs")


def _thumb_dir(job_id: str) -> str:
    return os.path.join(_THUMB_ROOT, job_id)


def _cleanup_thumb_dir(job: "JobState") -> None:
    """Remove the job's thumb dir AND clear thumbnail_ready flags so any
    post-cleanup snapshot accurately reports the thumbs are gone.

    Idempotent and never raises.
    """
    path = _thumb_dir(job.id)
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:  # pylint: disable=broad-except
        pass
    # Clear flags so a late-connecting subscriber sees thumbnail_ready=False
    for st in job.url_states.values():
        st.thumbnail_ready = False


def _url_idx(job: "JobState", raw_url: str) -> int:
    """0-based position of the URL within the job's submission order."""
    for i, u in enumerate(job.url_states.keys()):
        if u == raw_url:
            return i
    return -1


_THUMB_MAX_BYTES = 5 * 1024 * 1024  # 5MB cap; real thumbs are <100KB


def _fetch_thumbnail(job_id: str, url_idx: int, src_url: str) -> bool:
    """Stream a thumbnail to {THUMB_ROOT}/{job_id}/{url_idx}.jpg.

    Returns True on success, False on any failure (timeout, non-200,
    write error, exceeds size cap). No retries. Never raises.
    """
    try:
        target_dir = _thumb_dir(job_id)
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, f"{url_idx}.jpg")
        tmp_fd, tmp_path = tempfile.mkstemp(dir=target_dir, prefix=".thumb-", suffix=".tmp")
        try:
            with httpx.stream(
                "GET", src_url, timeout=5.0, follow_redirects=True
            ) as resp:
                if resp.status_code != 200:
                    raise IOError("non-200")
                total = 0
                with os.fdopen(tmp_fd, "wb") as f:
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > _THUMB_MAX_BYTES:
                            raise IOError("exceeded size cap")
                        f.write(chunk)
            os.replace(tmp_path, target)
            return True
        except Exception:  # pylint: disable=broad-except
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False
    except Exception:  # pylint: disable=broad-except
        return False


class _YDLLogger:
    """yt-dlp-compatible logger that routes filtered lines into a URL's
    state deque and broadcasts each kept line as a ``url_log`` SSE event.

    yt-dlp invokes ``.debug``, ``.info``, ``.warning``, ``.error`` with
    a single string (sometimes an exception). We coerce, filter, append,
    emit. Never raises — a logger that crashes would break the download.
    """
    # pylint: disable=missing-function-docstring

    def __init__(self, job: "JobState", url_state: "UrlState") -> None:
        self._job = job
        self._url_state = url_state

    def _route(self, level: str, msg) -> None:
        try:
            text = str(msg)
        except Exception:  # pylint: disable=broad-except
            text = repr(msg)
        if not _should_keep_log(level, text):
            return
        entry = {"ts": time.time(), "level": level, "text": text}
        self._url_state.log.append(entry)
        _emit(self._job, {
            "type": "url_log",
            "job_id": self._job.id,
            "url": self._url_state.url,
            "level": level,
            "text": text,
            "ts": entry["ts"],
        })

    def debug(self, msg) -> None:
        self._route("debug", msg)

    def info(self, msg) -> None:
        self._route("info", msg)

    def warning(self, msg) -> None:
        self._route("warning", msg)

    def error(self, msg) -> None:
        self._route("error", msg)


def _make_url_logger(job: "JobState", url_state: "UrlState") -> _YDLLogger:
    """Factory — kept as a function for test seam parity with hooks."""
    return _YDLLogger(job, url_state)


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
    - On the first tick carrying an info_dict, emits url_metadata with
      thumbnail_ready=False and stores title/uploader/duration on UrlState.
    """
    def hook(d: dict) -> None:
        if job.cancelled:
            raise _Cancelled()

        info = d.get("info_dict") or {}
        if info and not url_state.metadata_emitted:
            url_state.title = info.get("title")
            url_state.uploader = info.get("uploader")
            url_state.duration = info.get("duration")
            url_state.metadata_emitted = True
            _emit(job, {
                "type": "url_metadata",
                "job_id": job.id,
                "url": url_state.url,
                "title": url_state.title,
                "uploader": url_state.uploader,
                "duration": url_state.duration,
                "thumbnail_ready": False,
            })
            thumb_src = _pick_thumbnail_url(info)
            if thumb_src:
                idx = _url_idx(job, url_state.url)

                def _do_fetch() -> None:
                    if _fetch_thumbnail(job.id, idx, thumb_src):
                        url_state.thumbnail_ready = True
                        _emit(job, {
                            "type": "url_metadata",
                            "job_id": job.id,
                            "url": url_state.url,
                            "title": url_state.title,
                            "uploader": url_state.uploader,
                            "duration": url_state.duration,
                            "thumbnail_ready": True,
                        })

                threading.Thread(target=_do_fetch, daemon=True).start()

        status = d.get("status")
        if status == "finished":
            # yt-dlp signals download-complete; postprocessing begins now.
            url_state.phase = "postprocessing"
            _emit(job, {
                "type": "progress",
                "job_id": job.id,
                "url": url_state.url,
                "percent": 100.0,
                "downloaded_bytes": d.get("downloaded_bytes") or url_state.downloaded_bytes,
                "total_bytes": d.get("total_bytes") or url_state.total_bytes,
                "speed": None,
                "eta": None,
                "filename": d.get("filename") or url_state.filename,
                "phase": "postprocessing",
            })
            return

        if status != "downloading":
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
        url_state.phase = "downloading"

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
            "phase": "downloading",
        })

    return hook


def _run_one(job: JobState, raw_url: str) -> None:
    """One unit of work for the executor: sanitize, download, emit events."""
    url_state = job.url_states[raw_url]

    # Cancel-before-start: handles the race where a future is scheduled
    # but hadn't started running when cancel was hit.
    if job.cancelled:
        url_state.status = "cancelled"
        url_state.phase = "failed"
        url_state.error = "Cancelled"
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": "Cancelled"})
        return

    hook = _make_progress_hook(job, url_state)
    try:
        url_state.phase = "resolving"
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
            logger=_make_url_logger(job, url_state),
        )
    except _Cancelled:
        url_state.status = "cancelled"
        url_state.phase = "failed"
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": "Cancelled"})
        return
    except Exception as e:  # pylint: disable=broad-except
        # yt-dlp may wrap _Cancelled in DownloadError — detect by chained cause.
        if isinstance(e.__cause__, _Cancelled) or "Cancelled" in str(e):
            url_state.status = "cancelled"
            url_state.phase = "failed"
            _emit(job, {"type": "url_failed", "job_id": job.id,
                        "url": raw_url, "error": "Cancelled"})
            return
        url_state.status = "failed"
        url_state.phase = "failed"
        url_state.error = str(e)
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": str(e)})
        return

    if not paths:
        url_state.status = "failed"
        url_state.phase = "failed"
        url_state.error = "Download failed"
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": "Download failed"})
        return

    url_state.status = "completed"
    url_state.phase = "complete"
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
    # Best-effort cleanup of thumbnail tempdir. Only remove if no
    # subscribers are still streaming — otherwise reconnects in the next
    # second would 404 on thumbs that should still render.
    with job.lock:
        subs_remaining = len(job.subscribers)
    if subs_remaining == 0:
        _cleanup_thumb_dir(job)


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
    font-size: var(--fs-base);
    /* ── Proportional typography (clamp: min, vh-preferred, max) ── */
    --fs-base: clamp(16px, 1.7vh, 24px);
    --fs-sm:   clamp(13px, 1.4vh, 19px);
    --fs-lg:   clamp(20px, 2.4vh, 32px);
    --fs-xl:   clamp(26px, 3.5vh, 48px);
    /* ── Structural override surface (theme blocks can override these) ── */
    /* Frame characters — declared contract; corner glyphs live in HTML spans,
       not CSS content:, so these are forward-looking for themes that rewire
       via pseudo-elements. Wired vars below affect rendered borders. */
    --frame-corner-tl: '┌';
    --frame-corner-tr: '┐';
    --frame-corner-bl: '└';
    --frame-corner-br: '┘';
    --frame-h: '─';
    --frame-v: '│';
    --frame-junction-l: '├';
    --frame-junction-r: '┤';
    /* Frame rule (wired into .frame .frame-fill) */
    --frame-rule-color: var(--frame);
    --frame-rule-width: 1px;
    --frame-rule-style: solid;
    /* Spacing */
    --pane-padding: 0.6em 0.9em;
    --pane-gap: 0.7em;
    --line-height: 1.5;
    /* Title typography */
    --title-weight: 400;
    --title-letterspacing: 0.01em;
    --title-transform: none;
    /* Decoration — declared contract; used by JS-rendered content indirectly */
    --section-divider: ' · ';
    --idle-cursor-char: '▌';
  }
  *, *::before, *::after { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0; height: 100%;
    background: var(--bg); color: var(--fg);
    -webkit-font-smoothing: antialiased;
  }
  body {
    display: grid;
    min-height: 100vh;
    grid-template-areas: "status" "main" "keys";
    grid-template-rows: auto 1fr auto;
    grid-template-columns: 1fr;
    line-height: var(--line-height);
  }
  /* ── Status bar (top) ── */
  #status-bar {
    grid-area: status;
    display: flex; align-items: center; gap: 0;
    background: var(--bg); color: var(--dim);
    border-bottom: 1px solid var(--frame);
    padding: 0 1ch; height: 1.6em;
    white-space: nowrap; overflow: hidden; font-size: var(--fs-sm);
  }
  #status-bar .sb-app { color: var(--accent); font-weight: 600; margin-right: 1.5ch; }
  #status-bar .sb-sep { color: var(--frame); margin: 0 1ch; }
  #status-bar .sb-fill { flex: 1; }
  #status-bar .sb-ver { color: var(--dim); }
  #status-indicator { color: var(--dim); }
  #status-indicator.active { color: var(--live); }
  #status-indicator.done { color: var(--ok); }
  #status-indicator.failed { color: var(--err); }
  /* Idle breathing pulse — CSS-only, no JS state changes needed */
  #status-indicator:not(.active):not(.done):not(.failed) {
    animation: idle-breathe 2.4s ease-in-out infinite;
  }
  /* Blinking cursor: sibling of #status-indicator, visible only when idle */
  #idle-cursor {
    color: var(--dim); margin-left: 0.4ch;
    animation: cursor-blink 1.2s steps(1, end) infinite;
  }
  #status-indicator.active ~ #idle-cursor,
  #status-indicator.done ~ #idle-cursor,
  #status-indicator.failed ~ #idle-cursor { display: none; }
  @keyframes idle-breathe {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.55; }
  }
  @keyframes cursor-blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
  }
  @media (max-width: 600px) {
    #status-bar .sb-meta { display: none; }
    #sb-clock { display: none; }
  }
  /* ── Live clock ── */
  #sb-clock {
    color: var(--dim); margin-left: 1.5ch; white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  /* ── Glow for dark themes (dawn sets --glow: none) ── */
  .frame .title { text-shadow: var(--glow); }
  .accent { color: var(--accent); text-shadow: var(--glow); }
  .marker { color: var(--accent); text-shadow: var(--glow); }
  #status-indicator { text-shadow: var(--glow); }
  button.tui-btn { text-shadow: var(--glow); }
  /* ── Footer keybar (bottom) ── */
  #keybar {
    grid-area: keys;
    display: flex; align-items: center; gap: 0;
    background: var(--bg); color: var(--dim);
    border-top: 1px solid var(--frame);
    padding: 0 1ch; height: 1.6em;
    white-space: nowrap; overflow: hidden; font-size: var(--fs-sm);
  }
  #keybar .kb-item { display: flex; align-items: center; margin-right: 1.5ch; }
  #keybar .kb-key { color: var(--dim); }
  #keybar .kb-key .kb-bracket { color: var(--frame); }
  #keybar .kb-key .kb-chord { color: var(--label); }
  #keybar .kb-action { color: var(--fg); margin-left: 0.5ch; }
  @media (max-width: 600px) {
    #keybar .kb-item:nth-child(n+4) { display: none; }
  }
  /* ── Main content area between status bar and keybar ── */
  #main-content {
    grid-area: main;
    display: grid;
    place-items: stretch;
    min-height: 0; overflow: auto;
  }
  /* ── Frame rows: flex-based so the ─ fills span full viewport width ── */
  .frame {
    color: var(--frame); line-height: 1.4;
    display: flex; align-items: center; flex-shrink: 0;
    white-space: nowrap; overflow: hidden;
  }
  .frame .frame-corner { color: var(--frame); }
  .frame .frame-fill {
    flex: 1; overflow: hidden;
    border-bottom: var(--frame-rule-width) var(--frame-rule-style) var(--frame-rule-color);
    margin-bottom: 0.35em;
    min-width: 1ch;
  }
  .frame .panel-title {
    color: var(--label); font-size: var(--fs-sm); letter-spacing: var(--title-letterspacing);
    font-weight: var(--title-weight); text-transform: var(--title-transform);
    flex-shrink: 0;
  }
  .frame .panel-title .pt-bracket { color: var(--frame); }
  .frame .panel-title .pt-label { color: var(--accent); }
  .frame .title { color: var(--accent); font-weight: var(--title-weight); }
  .frame .theme-btn {
    color: var(--accent); background: rgba(255,255,255,0.04);
    padding: 0 6px; cursor: pointer; user-select: none;
    flex-shrink: 0; font-size: var(--fs-sm);
  }
  .frame .theme-btn:hover { background: rgba(255,255,255,0.08); }
  .frame .frame-seg { flex-shrink: 0; color: var(--frame); }
  /* ── Two-pane layout: form left, jobs right on wide viewports ── */
  .panes {
    display: grid;
    grid-template-areas: "input" "output";
    grid-template-columns: 1fr;
    min-height: 0;
    gap: var(--pane-gap, 0.7em);
    padding: var(--pane-padding, 0.5rem 1rem);
  }
  .panes .panel:nth-child(1) { grid-area: input; }
  .panes .panel:nth-child(2) { grid-area: output; }
  @media (min-width: 1200px) {
    .panes {
      grid-template-areas: "input output";
      grid-template-columns: minmax(44ch, 1fr) minmax(0, 1.4fr);
      align-items: start;
    }
  }
  /* ── Panel containers (each with their own border box) ── */
  .panel { display: flex; flex-direction: column; }
  /* ── Form panel ── */
  .body-section { padding-left: 1ch; margin: 1px 0; }
  .body-section .field-line { display: flex; align-items: baseline; gap: 4px; padding: 1px 0; }
  .label { color: var(--label); display: inline-block; min-width: 10ch; }
  .marker { color: var(--accent); }
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
  textarea.field { resize: none; height: 7.5rem; width: 100%; }
  select.field { cursor: pointer; }
  input[type=range].slider {
    appearance: none; -webkit-appearance: none;
    height: 6px; background: var(--frame); border-radius: 3px; outline: 0;
    flex: 1; max-width: 22ch;
  }
  input[type=range].slider::-webkit-slider-thumb {
    appearance: none; -webkit-appearance: none;
    width: 15px; height: 15px; border-radius: 50%;
    background: var(--accent); cursor: pointer;
  }
  input[type=range].slider::-moz-range-thumb {
    width: 15px; height: 15px; border-radius: 50%;
    background: var(--accent); cursor: pointer; border: 0;
  }
  button.tui-btn {
    color: var(--btn-fg); background: var(--accent);
    border: 0; padding: 1px 12px; font: inherit; font-weight: 600;
    cursor: pointer; font-size: var(--fs-sm);
  }
  button.tui-btn:hover { filter: brightness(1.1); }
  button.tui-btn:disabled { opacity: 0.4; cursor: default; }
  button.cancel-btn {
    background: transparent; color: var(--err);
    border: 1px solid var(--frame); padding: 0 7px;
    font: inherit; font-size: var(--fs-sm); cursor: pointer;
  }
  /* ── Job panel ── */
  #jobpanel { min-height: 0; }
  #jobpanel[hidden] { display: none; }
  .summary { color: var(--dim); font-size: var(--fs-sm); }
  .jobpanel-empty { color: var(--dim); padding-left: 1ch; font-style: italic; font-size: var(--fs-sm); }
  /* live-pulse: opacity fade + live-color text-shadow pulse */
  .live-pulse { animation: pulse 1.4s ease-in-out infinite; }
  @keyframes pulse {
    0%, 100% { opacity: 1; text-shadow: 0 0 4px var(--live); }
    50% { opacity: 0.4; text-shadow: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    .live-pulse { animation: none; }
    #status-indicator:not(.active):not(.done):not(.failed) { animation: none; }
    #idle-cursor { animation: none; }
  }
  /* ── Stats subpanel inside OUTPUT panel ── */
  #stats-panel {
    font-size: var(--fs-sm);
    margin-bottom: 2px;
  }
  #stats-panel .stats-frame { margin-bottom: 0; }
  .stats-body {
    padding: 1px 0 2px 1ch;
    display: flex; flex-direction: column; gap: 0;
  }
  .stats-row { display: flex; gap: 1ch; padding: 0; }
  .stats-label { color: var(--label); min-width: 9ch; }
  .stats-val { color: var(--dim); min-width: 3ch; text-align: right; }
  .stats-val.active { color: var(--live); }
  .stats-val.done { color: var(--ok); }
  .stats-val.failed { color: var(--err); }
  /* ── Right-pane frame separator on wide screens ── */
  @media (min-width: 1200px) {
    #jobpanel[hidden] { display: block; }
    .jobpanel-empty { display: block; }
    #jobpanel .jobpanel-empty { display: block; }
  }
  /* ── Popover ── */
  #theme-popover[hidden] { display: none; }
  #theme-popover {
    position: fixed; top: 2.2rem; right: 1rem; width: 440px;
    background: var(--bg); color: var(--fg);
    border: 1px solid var(--frame);
    padding: 12px; z-index: 100;
    box-shadow: 0 8px 32px rgba(0,0,0,0.6);
    font-size: var(--fs-sm);
  }
  #theme-popover .pop-header {
    color: var(--accent); font-weight: 600; margin-bottom: 4px;
    display: flex; justify-content: space-between; align-items: center;
  }
  #theme-popover .pop-sub { color: var(--dim); font-size: var(--fs-sm); margin-bottom: 10px; }
  #theme-popover input.pop-search {
    background: var(--bg); border: 1px solid var(--frame);
    padding: 4px 8px; color: var(--fg); font: inherit;
    width: 100%; box-sizing: border-box; margin-bottom: 10px; outline: 0;
  }
  #theme-popover input.pop-search:focus { border-color: var(--accent); }
  #theme-popover .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  #theme-popover .thumb {
    overflow: hidden; cursor: pointer;
    border: 2px solid transparent; padding: 0; background: transparent;
    font: inherit; text-align: left;
  }
  #theme-popover .thumb:hover { border-color: var(--frame); }
  #theme-popover .thumb.active { border-color: var(--accent); }
  #theme-popover .thumb:focus { outline: 0; border-color: var(--accent); }
  #theme-popover .thumb .preview {
    padding: 5px 7px; font-size: var(--fs-sm); line-height: 1.3; min-height: 44px;
  }
  #theme-popover .thumb .name {
    background: rgba(0,0,0,0.4); padding: 3px 7px; font-size: var(--fs-sm);
    color: var(--fg); display: flex; justify-content: space-between;
  }
  @media (max-width: 480px) {
    #theme-popover { left: 0.5rem; right: 0.5rem; width: auto; }
  }

  /* ── rich job cards ─────────────────────────────────────────────── */
  .card {
    display: grid;
    grid-template-columns: 128px 1fr;
    gap: 14px;
    padding: 12px 14px;
    border: 1px solid var(--frame);
    margin: 8px 0;
    background: var(--bg);
  }
  .card-thumb {
    width: 120px;
    height: 68px;
    background: var(--dim);
    border: 1px solid var(--frame);
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .card-thumb img { display: block; width: 100%; height: 100%; object-fit: cover; }
  .card-thumb--placeholder::before {
    content: "▢";
    color: var(--frame);
    font-size: 24px;
  }
  .card-body { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .card-head { display: flex; align-items: baseline; gap: 8px; }
  .card-title {
    color: var(--accent);
    font-weight: bold;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .card-meta { color: var(--dim); font-size: 0.9em; }
  .card-badge { color: var(--accent); font-family: inherit; margin-left: auto; }
  .card[data-state="complete"] .card-badge { color: var(--ok); }
  .card[data-state="failed"] .card-badge { color: var(--err); }
  .card[data-state="resolving"] .card-badge::after {
    content: "";
    display: inline-block;
    animation: card-blink 1s infinite;
  }
  @keyframes card-blink {
    50% { opacity: 0.3; }
  }
  .card-progress { display: flex; align-items: center; gap: 10px; }
  .card-bar {
    flex: 1;
    height: 6px;
    background: var(--dim);
    border: 1px solid var(--frame);
    position: relative;
  }
  .card-bar > span {
    position: absolute;
    top: 0; left: 0; bottom: 0;
    background: var(--bar, var(--accent));
    transition: width 0.15s linear;
  }
  .card-stats { color: var(--dim); font-size: 0.9em; min-width: 24ch; text-align: right; }
  .card-reveal {
    background: transparent;
    border: 1px solid var(--frame);
    color: var(--accent);
    font-family: inherit;
    font-size: 0.9em;
    padding: 2px 8px;
    cursor: pointer;
  }
  .card-reveal:hover { background: var(--dim); }
  .card-log {
    list-style: none;
    margin: 0; padding: 0;
    color: var(--dim);
    font-size: 0.9em;
  }
  .card-log-line { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .card-log-line[data-level="warning"] { color: var(--warn); }
  .card-log-line[data-level="error"] { color: var(--err); }
  /* State-driven show/hide */
  .card[data-state="queued"] .card-progress,
  .card[data-state="resolving"] .card-progress,
  .card[data-state="queued"] .card-log,
  .card[data-state="resolving"] .card-log { display: none; }
  @media (prefers-reduced-motion: reduce) {
    .card[data-state="resolving"] .card-badge::after { animation: none; }
  }
"""

_INDEX_CSS_THEMES = """  :root[data-theme="phosphor"] {
    /* colors */
    --bg: #000;        --fg: #d0d0d0;     --frame: #1a4a1a;  --label: #707070;
    --accent: #00ff88; --ok: #00ff88;     --err: #ff5555;    --warn: #ffaa33;
    --live: #00d9ff;   --dim: #555;       --bar: #00d9ff;    --btn-fg: #000;
    --glow: 0 0 6px var(--accent);
    /* structural — classic dense VT100 identity */
    --line-height: 1.35;
    --pane-padding: 0.4em 0.7em;
    --pane-gap: 0.5em;
    --title-weight: 400;
    --title-letterspacing: 0.05em;
    --title-transform: lowercase;
    --frame-rule-color: var(--frame);
    --frame-rule-width: 1px;
    --frame-rule-style: solid;
  }
  /* Phosphor: baseline — status top, 2 horizontal panes, keybar bottom */
  html[data-theme="phosphor"] body {
    grid-template-areas: "status" "main" "keys";
    grid-template-rows: auto 1fr auto;
  }
  @media (min-width: 1200px) {
    html[data-theme="phosphor"] .panes {
      grid-template-areas: "input output";
      grid-template-columns: 1fr 1fr;
    }
  }
  :root[data-theme="rose"] {
    --bg: #191724;     --fg: #e0def4;     --frame: #403d52;  --label: #908caa;
    --accent: #ebbcba; --ok: #9ccfd8;     --err: #eb6f92;    --warn: #f6c177;
    --live: #c4a7e7;   --dim: #6e6a86;    --bar: #c4a7e7;    --btn-fg: #191724;
    --glow: 0 0 6px var(--accent);
    /* structural: editorial / magazine identity */
    --line-height: 1.75;
    --pane-padding: 0.9em 1.4em;
    --title-letterspacing: 0.04em;
    --title-weight: 400;
    --section-divider: ' \2014 ';
  }
  html[data-theme="rose"] .panel {
    border-radius: 4px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.25);
  }
  html[data-theme="rose"] .frame .panel-title {
    font-style: italic;
    font-weight: 400;
  }
  /* Rose Pine: editorial single-column centered, stacked panes, magazine feel */
  html[data-theme="rose"] body {
    grid-template-areas: "status" "main" "keys";
    grid-template-rows: auto 1fr auto;
  }
  html[data-theme="rose"] .panes {
    grid-template-areas: "input" "output";
    grid-template-columns: 1fr;
    max-width: 760px;
    margin: 2rem auto;
    gap: 2rem;
    padding: 0;
  }
  @media (min-width: 1200px) {
    html[data-theme="rose"] .panes {
      grid-template-areas: "input" "output";
      grid-template-columns: 1fr;
    }
  }
  :root[data-theme="moon"] {
    --bg: #232136;     --fg: #e0def4;     --frame: #44415a;  --label: #908caa;
    --accent: #ea9a97; --ok: #9ccfd8;     --err: #eb6f92;    --warn: #f6c177;
    --live: #c4a7e7;   --dim: #6e6a86;    --bar: #c4a7e7;    --btn-fg: #232136;
    --glow: 0 0 10px var(--accent);
    /* structural: dramatic / performance identity */
    --line-height: 1.7;
    --pane-padding: 0.9em 1.4em;
    --title-letterspacing: 0.02em;
    --title-weight: 400;
    --section-divider: ' / ';
  }
  html[data-theme="moon"] .panel {
    border-left: 4px solid var(--accent);
    padding-left: 1em;
  }
  /* Rose Pine Moon: vertical status bar on right side, stacked panes, keybar bottom */
  html[data-theme="moon"] body {
    grid-template-areas: "main status" "keys keys";
    grid-template-columns: 1fr auto;
    grid-template-rows: 1fr auto;
  }
  html[data-theme="moon"] #status-bar {
    writing-mode: vertical-rl;
    border-bottom: none;
    border-left: 2px solid var(--frame);
    height: auto;
    width: 1.8em;
    padding: 1rem 0;
    align-items: flex-start;
    overflow: hidden;
  }
  html[data-theme="moon"] .panes {
    grid-template-areas: "input" "output";
    grid-template-columns: 1fr;
    max-width: 760px;
    margin: 2rem auto;
    padding: 0;
  }
  @media (min-width: 1200px) {
    html[data-theme="moon"] .panes {
      grid-template-areas: "input" "output";
      grid-template-columns: 1fr;
    }
  }
  @media (max-width: 800px) {
    html[data-theme="moon"] body {
      grid-template-areas: "status" "main" "keys";
      grid-template-columns: 1fr;
      grid-template-rows: auto 1fr auto;
    }
    html[data-theme="moon"] #status-bar {
      writing-mode: horizontal-tb;
      border-left: none;
      border-bottom: 1px solid var(--frame);
      width: auto;
      height: 1.6em;
      padding: 0 1ch;
    }
  }
  :root[data-theme="dawn"] {
    --bg: #faf4ed;     --fg: #575279;     --frame: #cecacd;  --label: #797593;
    --accent: #d7827e; --ok: #56949f;     --err: #b4637a;    --warn: #ea9d34;
    --live: #907aa9;   --dim: #9893a5;    --bar: #907aa9;    --btn-fg: #faf4ed;
    --glow: none;
    /* structural: paper / print identity */
    --line-height: 1.85;
    --frame-rule-width: 1px;
    --frame-rule-color: var(--label);
    --section-divider: ' \203B ';
  }
  html[data-theme="dawn"] #status-bar .sb-app {
    font-family: Georgia, 'Times New Roman', serif;
    font-style: italic;
    font-weight: 400;
  }
  html[data-theme="dawn"] button.tui-btn:hover {
    filter: none;
    text-decoration: underline;
  }
  /* Rose Pine Dawn: paper/page — faux page margins, stacked panes centered */
  html[data-theme="dawn"] body {
    grid-template-areas: "status" "main" "keys";
    grid-template-rows: auto 1fr auto;
    padding: 2rem 0;
    background: #d8d2c4;
  }
  html[data-theme="dawn"] #main-content {
    max-width: 760px;
    margin: 0 auto;
    background: var(--bg);
    padding: 2.5rem 3rem;
    box-shadow: 0 6px 24px rgba(0,0,0,0.12);
    border-radius: 2px;
  }
  html[data-theme="dawn"] .panes {
    grid-template-areas: "input" "output";
    grid-template-columns: 1fr;
    padding: 0;
    gap: 1.5rem;
  }
  @media (min-width: 1200px) {
    html[data-theme="dawn"] .panes {
      grid-template-areas: "input" "output";
      grid-template-columns: 1fr;
    }
  }
  :root[data-theme="amber"] {
    --bg: #0a0600;     --fg: #ffb000;     --frame: #4a3000;  --label: #8a5a00;
    --accent: #ffb000; --ok: #ffb000;     --err: #ff4500;    --warn: #ff8800;
    --live: #ff8800;   --dim: #4a3000;    --bar: #ff8800;    --btn-fg: #0a0600;
    --glow: none;
    /* Structural: Amber CRT — vintage Tektronix phosphor */
    --line-height: 1.65;
    --title-weight: 600;
    --title-letterspacing: 0.15em;
    --title-transform: uppercase;
    --frame-rule-style: dotted;
    --pane-padding: 0.7em 1em;
    --section-divider: ' · · ';
  }
  /* Amber CRT: wider letter-spacing, dotted borders, uppercase titles, warm fuzz */
  [data-theme="amber"] body { letter-spacing: 0.05em; }
  [data-theme="amber"] .frame .frame-fill {
    border-bottom-style: dotted;
    border-bottom-color: var(--frame);
  }
  [data-theme="amber"] #status-bar { border-bottom-style: dotted; }
  [data-theme="amber"] #keybar { border-top-style: dotted; }
  [data-theme="amber"] .frame .panel-title {
    text-transform: uppercase;
    letter-spacing: 0.15em;
    font-weight: 600;
  }
  [data-theme="amber"] .frame .title {
    text-transform: uppercase;
    letter-spacing: 0.15em;
    font-weight: 600;
    text-shadow: 0 0 1px #ffb000;
  }
  [data-theme="amber"] #status-bar .sb-app {
    letter-spacing: 0.08em;
    text-shadow: 0 0 1px #ffb000;
  }
  [data-theme="amber"] .label { letter-spacing: 0.05em; }
  [data-theme="amber"] .body-section { line-height: 1.65; }
  /* Amber CRT: vintage single-column, panes stacked, status/keybar centered */
  html[data-theme="amber"] body {
    grid-template-areas: "status" "main" "keys";
    grid-template-rows: auto 1fr auto;
  }
  html[data-theme="amber"] #status-bar { justify-content: center; text-align: center; }
  html[data-theme="amber"] #keybar { justify-content: center; }
  html[data-theme="amber"] .panes {
    grid-template-areas: "input" "output";
    grid-template-columns: 1fr;
    max-width: 70ch;
    margin: 0 auto;
    padding: 0.7em 1em;
  }
  @media (min-width: 1200px) {
    html[data-theme="amber"] .panes {
      grid-template-areas: "input" "output";
      grid-template-columns: 1fr;
    }
  }
  :root[data-theme="solarized"] {
    --bg: #002b36;     --fg: #93a1a1;     --frame: #073642;  --label: #586e75;
    --accent: #b58900; --ok: #859900;     --err: #dc322f;    --warn: #cb4b16;
    --live: #2aa198;   --dim: #586e75;    --bar: #268bd2;    --btn-fg: #002b36;
    --glow: none;
    /* Structural: Solarized Dark — scholarly, compact, tabular */
    --line-height: 1.4;
    --title-weight: 400;
    --title-letterspacing: 0.01em;
    --title-transform: capitalize;
    --frame-rule-color: var(--bar);
    --pane-padding: 0.45em 0.8em;
    --pane-gap: 0.5em;
    --section-divider: ' / ';
  }
  /* Solarized: compact/tabular, pine-blue frame rules, capitalized titles */
  [data-theme="solarized"] body {
    font-feature-settings: "tnum" 1;
    font-variant-numeric: tabular-nums;
  }
  [data-theme="solarized"] .frame .frame-fill {
    border-bottom-color: #268bd2;
  }
  [data-theme="solarized"] #status-bar {
    border-bottom-color: #268bd2;
  }
  [data-theme="solarized"] #keybar {
    border-top-color: #268bd2;
  }
  [data-theme="solarized"] .frame .panel-title {
    text-transform: capitalize;
    letter-spacing: 0.01em;
    font-weight: 400;
  }
  [data-theme="solarized"] .frame .title {
    text-transform: capitalize;
    font-weight: 400;
  }
  [data-theme="solarized"] .body-section {
    line-height: 1.4;
    padding-left: 0.8ch;
  }
  [data-theme="solarized"] .stats-val,
  [data-theme="solarized"] #sb-clock {
    font-feature-settings: "tnum" 1;
    font-variant-numeric: tabular-nums;
  }
  /* Solarized Dark: scholarly — asymmetric panes (input narrower), fixed keybar top-right */
  html[data-theme="solarized"] body {
    grid-template-areas: "status" "main";
    grid-template-rows: auto 1fr;
  }
  html[data-theme="solarized"] #keybar {
    position: fixed; top: 0; right: 1rem;
    height: 1.6em; border: none; border-left: 1px solid var(--frame);
    background: var(--bg); padding: 0 1ch;
    z-index: 50;
  }
  @media (min-width: 1200px) {
    html[data-theme="solarized"] .panes {
      grid-template-areas: "input output";
      grid-template-columns: 1fr 1.2fr;
    }
  }
  @media (max-width: 800px) {
    html[data-theme="solarized"] body {
      grid-template-areas: "status" "main" "keys";
      grid-template-rows: auto 1fr auto;
    }
    html[data-theme="solarized"] #keybar {
      position: static; border: none;
      border-top: 1px solid var(--frame);
    }
  }
  :root[data-theme="gruvbox"] {
    --bg: #282828;     --fg: #ebdbb2;     --frame: #504945;  --label: #928374;
    --accent: #fabd2f; --ok: #b8bb26;     --err: #fb4934;    --warn: #fe8019;
    --live: #8ec07c;   --dim: #665c54;    --bar: #83a598;    --btn-fg: #282828;
    --glow: none;
    /* Structural: Gruvbox Dark — brutalist warm retro */
    --line-height: 1.45;
    --title-weight: 700;
    --title-letterspacing: 0.08em;
    --title-transform: uppercase;
    --frame-rule-width: 2px;
    --frame-rule-color: var(--accent);
    --pane-padding: 0.5em 1.1em;
    --section-divider: ' :: ';
  }
  /* Gruvbox: thick borders, bold uppercase titles, condensed, matte painted */
  [data-theme="gruvbox"] .frame .frame-fill {
    border-bottom-width: 2px;
    border-bottom-color: var(--accent);
  }
  [data-theme="gruvbox"] #status-bar {
    border-bottom-width: 2px;
    border-bottom-color: var(--accent);
  }
  [data-theme="gruvbox"] #keybar {
    border-top-width: 2px;
    border-top-color: var(--accent);
  }
  [data-theme="gruvbox"] .frame .panel-title {
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 700;
  }
  [data-theme="gruvbox"] .frame .title {
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 700;
  }
  [data-theme="gruvbox"] #status-bar .sb-app {
    font-weight: 700;
    letter-spacing: 0.08em;
  }
  [data-theme="gruvbox"] .body-section { line-height: 1.45; }
  /* Gruvbox Dark: brutalist menubar — keybar at TOP, stacked panes below */
  html[data-theme="gruvbox"] body {
    grid-template-areas: "keys" "status" "main";
    grid-template-rows: auto auto 1fr;
  }
  html[data-theme="gruvbox"] #keybar {
    border-top: none;
    border-bottom: 2px solid var(--accent);
    justify-content: flex-start;
  }
  html[data-theme="gruvbox"] #status-bar {
    border-bottom-width: 2px;
    border-bottom-color: var(--accent);
  }
  html[data-theme="gruvbox"] .panes {
    grid-template-areas: "input" "output";
    grid-template-columns: 1fr;
    padding: 0.5em 1.1em;
  }
  @media (min-width: 1200px) {
    html[data-theme="gruvbox"] .panes {
      grid-template-areas: "input" "output";
      grid-template-columns: 1fr;
    }
  }
  :root[data-theme="tokyo"] {
    --bg: #1a1b26;     --fg: #c0caf5;     --frame: #565f89;  --label: #565f89;
    --accent: #bb9af7; --ok: #9ece6a;     --err: #f7768e;    --warn: #e0af68;
    --live: #7dcfff;   --dim: #414868;    --bar: #7dcfff;    --btn-fg: #1a1b26;
    --glow: 0 0 10px var(--accent), 0 0 22px var(--accent);
    /* Structural identity: cyberpunk neon — double borders, glow, dense typography */
    --frame-rule-style: double;
    --frame-rule-width: 3px;
    --frame-rule-color: var(--frame);
    --line-height: 1.35;
    --title-transform: uppercase;
    --title-letterspacing: 0.15em;
    --title-weight: 700;
    --section-divider: ' \25b8 ';
    --idle-cursor-char: '\258c';
  }
  /* Tokyo Night — double-line frame fills */
  :root[data-theme="tokyo"] .frame .frame-fill {
    border-bottom: 3px double var(--frame);
  }
  /* Tokyo Night — chromatic aberration on the app title in the status bar */
  :root[data-theme="tokyo"] #status-bar .sb-app {
    text-shadow: -1px 0 #ff00ea, 1px 0 #00ffff, 0 0 12px var(--accent);
    text-transform: uppercase;
    letter-spacing: 0.15em;
    font-weight: 700;
  }
  /* Tokyo Night — intense neon glow on panel title accent labels */
  :root[data-theme="tokyo"] .frame .pt-label {
    text-shadow: -1px 0 #ff00ea, 1px 0 #00ffff, 0 0 12px var(--accent);
    text-transform: uppercase;
    letter-spacing: 0.15em;
  }
  /* Tokyo Night — uppercase panel title labels */
  :root[data-theme="tokyo"] .frame .panel-title {
    letter-spacing: 0.15em;
    text-transform: uppercase;
  }
  /* Tokyo Night: cyberpunk — main content top, keybar middle, status at bottom */
  html[data-theme="tokyo"] body {
    grid-template-areas: "main" "keys" "status";
    grid-template-rows: 1fr auto auto;
  }
  html[data-theme="tokyo"] #status-bar {
    border-top: 3px double var(--frame);
    border-bottom: none;
  }
  html[data-theme="tokyo"] #keybar {
    border-top: none;
    border-bottom: 3px double var(--frame);
  }
  @media (min-width: 1200px) {
    html[data-theme="tokyo"] .panes {
      grid-template-areas: "input output";
      grid-template-columns: 1fr 1.4fr;
    }
  }
  :root[data-theme="atom"] {
    --bg: #282c34;     --fg: #abb2bf;     --frame: #3e4451;  --label: #5c6370;
    --accent: #c678dd; --ok: #98c379;     --err: #e06c75;    --warn: #d19a66;
    --live: #61afef;   --dim: #4b5263;    --bar: #61afef;    --btn-fg: #282c34;
    --glow: 0 0 6px var(--accent);
    /* Structural identity: code editor — gutter, tab-style panel titles, tight spacing */
    --line-height: 1.4;
    --pane-padding: 0.5em 0.8em;
    --section-divider: ' :: ';
    --idle-cursor-char: '|';
  }
  /* Atom — line-number gutter on the form field lines */
  :root[data-theme="atom"] .body-section {
    counter-reset: lineno;
  }
  :root[data-theme="atom"] .body-section .field-line {
    counter-increment: lineno;
    position: relative;
    padding-left: 3.5em;
  }
  :root[data-theme="atom"] .body-section .field-line::before {
    content: counter(lineno);
    position: absolute;
    left: 0;
    width: 2.5em;
    text-align: right;
    color: var(--dim);
    border-right: 1px solid var(--frame);
    padding-right: 0.5em;
    font-style: normal;
    pointer-events: none;
  }
  /* Atom — editor-tab style for panel titles: bottom-border accent underline */
  :root[data-theme="atom"] .frame .panel-title {
    background: rgba(198,120,221,0.08);
    padding: 0 0.6em;
    border-bottom: 2px solid var(--accent);
    font-size: 13px;
    letter-spacing: 0.04em;
  }
  /* Atom — monospace italic on accent-colored spans (syntax-highlight feel) */
  :root[data-theme="atom"] .accent {
    font-style: italic;
  }
  /* Atom Dark Pro: IDE layout — fixed-width sidebar (input), flex main area (output) */
  html[data-theme="atom"] body {
    grid-template-areas: "status" "main" "keys";
    grid-template-rows: auto 1fr auto;
  }
  @media (min-width: 1200px) {
    html[data-theme="atom"] .panes {
      grid-template-areas: "input output";
      grid-template-columns: 360px 1fr;
    }
    html[data-theme="atom"] .panes .panel:nth-child(1) {
      border-right: 1px solid var(--frame);
    }
  }
  :root[data-theme="claude"] {
    --bg: #181513;     --fg: #efe9d9;     --frame: #4d4641;  --label: #8a7a6a;
    --accent: #d97757; --ok: #88a86c;     --err: #d5524d;    --warn: #d99155;
    --live: #e8a866;   --dim: #4d4641;    --bar: #e8a866;    --btn-fg: #181513;
    --glow: 0 0 12px rgba(217,119,87,0.45);
    /* Structural identity: warm, considered — no terminal chrome, generous spacing */
    --line-height: 1.7;
    --pane-padding: 1.2em 1.6em;
    --section-divider: '  \00b7  ';
  }
  /* Claude — remove terminal frame chrome: hide corner glyphs, drop frame-fill border */
  :root[data-theme="claude"] .frame .frame-corner {
    display: none;
  }
  :root[data-theme="claude"] .frame .frame-fill {
    border-bottom: none;
    margin-bottom: 0;
  }
  /* Claude — replace hard border on .frame with a soft dotted underline */
  :root[data-theme="claude"] .frame {
    border: none;
    padding-bottom: 0.3em;
    border-bottom: 1px dotted var(--label);
  }
  /* Claude — panels: no border, warm tint, rounded card feel */
  :root[data-theme="claude"] .panel {
    border: none;
    padding: 1.2em 1.6em;
    background: rgba(217,119,87,0.03);
    border-radius: 8px;
  }
  /* Claude — large, light app title in the status bar */
  :root[data-theme="claude"] #status-bar .sb-app {
    font-size: 1.05em;
    font-weight: 300;
    letter-spacing: 0.05em;
  }
  /* Claude — hide the blinking idle cursor (calm, not nervous) */
  :root[data-theme="claude"] #idle-cursor {
    display: none;
  }
  /* Claude — pill-shaped download button (warm, rounded) */
  :root[data-theme="claude"] button.tui-btn {
    border-radius: 999px;
    padding: 0.4em 1.2em;
  }
  /* Claude — softer panel-title label (no harsh brackets feel) */
  :root[data-theme="claude"] .frame .panel-title {
    letter-spacing: 0.06em;
    font-size: 13px;
  }
  /* Claude: signature — floating status overlay, no terminal chrome, asymmetric panes */
  html[data-theme="claude"] body {
    grid-template-areas: "main" "keys";
    grid-template-rows: 1fr auto;
    padding: 1.5rem 2rem;
    gap: 1rem;
  }
  html[data-theme="claude"] #status-bar {
    position: fixed; top: 1.5rem; right: 2rem;
    border: none; background: rgba(217,119,87,0.08);
    padding: 0.4em 1em; border-radius: 999px; width: auto;
    height: auto; white-space: nowrap;
    z-index: 40;
  }
  html[data-theme="claude"] #keybar {
    background: rgba(217,119,87,0.04); border-radius: 999px;
    border: 1px solid var(--frame); justify-content: center;
  }
  @media (min-width: 1200px) {
    html[data-theme="claude"] .panes {
      grid-template-areas: "input output";
      grid-template-columns: 1fr 1.4fr;
      gap: 1.5rem;
    }
  }
  @media (max-width: 800px) {
    html[data-theme="claude"] body {
      padding: 1rem;
    }
    html[data-theme="claude"] #status-bar {
      position: static;
      border-radius: 0; background: transparent;
      padding: 0 1ch; height: 1.6em; width: auto;
    }
  }
"""

_INDEX_HTML_BODY = """<div id="status-bar">
  <span class="sb-app">audio-dl</span>
  <span id="status-indicator">◌ idle</span><span id="idle-cursor">▌</span>
  <span class="sb-sep sb-meta">·</span>
  <span class="sb-meta" id="sb-meta-text"></span>
  <span class="sb-fill"></span>
  <span id="sb-clock" class="dim"></span>
  <span class="sb-sep dim" style="margin-left:1ch;">──</span>
  <span class="sb-ver dim">v__VERSION__</span>
</div>

<div id="main-content">
<div class="panes">

<div class="panel">
  <div class="frame"><span class="frame-corner">┌─</span><span class="panel-title"><span class="pt-bracket">[ </span><span class="pt-label">INPUT</span><span class="pt-bracket"> ]</span></span><span class="frame-fill"></span><span class="theme-btn" id="theme-btn"><span class="pt-bracket">[ </span>theme: <span id="theme-current">phosphor</span> ▾<span class="pt-bracket"> ]</span></span><span class="frame-fill"></span><span class="frame-corner">─┐</span></div>
  <form id="dl">
    <div class="body-section">
      <div class="field-line"><span class="label">urls</span><span class="marker">▸</span> <textarea class="field" id="urls" name="urls" placeholder="https://youtu.be/...&#10;https://soundcloud.com/..." required></textarea></div>
      <div class="field-line"><span class="label">format</span><span class="marker">▸</span> <select class="field" id="format" name="format" style="max-width:18ch;">__FORMAT_OPTIONS__</select></div>
      <div class="field-line"><span class="label">output</span><span class="marker">▸</span> <input class="field" id="output_dir" name="output_dir" type="text" value="__DEFAULT_OUTPUT_DIR__" required></div>
      <div class="field-line"><span class="label">jobs</span><span class="marker">▸</span> <input class="slider" id="jobs" name="jobs" type="range" min="1" max="8" value="1"> <span id="jobs_val" class="dim">1</span></div>
      <div class="field-line"><span class="label">fragments</span><span class="marker">▸</span> <input class="slider" id="fragments" name="fragments" type="range" min="1" max="16" value="4"> <span id="fragments_val" class="dim">4</span></div>
      <div class="field-line"><span class="label">flags</span><span class="marker">▸</span> <label style="margin-right:12px;"><input type="checkbox" id="playlist" name="playlist"> playlist</label> <label><input type="checkbox" id="force" name="force"> overwrite</label></div>
      <div class="field-line" style="margin-top:6px;"><span class="label"></span><button type="submit" class="tui-btn" id="submit">[ download ]</button> <span class="dim">⌘↵</span></div>
    </div>
  </form>
  <div class="frame"><span class="frame-corner">└</span><span class="frame-fill"></span><span class="frame-corner">┘</span></div>
</div>

<div class="panel">
  <div class="frame"><span class="frame-corner">┌─</span><span class="panel-title"><span class="pt-bracket">[ </span><span class="pt-label">OUTPUT</span><span class="pt-bracket"> ]</span></span><span class="frame-fill"></span><button type="button" class="cancel-btn" id="cancel" disabled>[ esc ] cancel</button><span class="frame-fill" style="max-width:1ch;"></span><span class="frame-corner">─┐</span></div>
  <div id="stats-panel">
    <div class="frame stats-frame"><span class="frame-corner">├─</span><span class="panel-title"><span class="pt-bracket">[ </span><span class="pt-label">STATS</span><span class="pt-bracket"> ]</span></span><span class="frame-fill"></span><span class="frame-corner">┤</span></div>
    <div class="stats-body">
      <div class="stats-row"><span class="stats-label">queued</span><span class="stats-val" id="stat-queued">0</span></div>
      <div class="stats-row"><span class="stats-label">active</span><span class="stats-val active" id="stat-active">0</span></div>
      <div class="stats-row"><span class="stats-label">done</span><span class="stats-val done" id="stat-done">0</span></div>
      <div class="stats-row"><span class="stats-label">failed</span><span class="stats-val failed" id="stat-failed">0</span></div>
    </div>
  </div>
  <section id="jobpanel" hidden>
    <div class="frame"><span class="frame-corner">├─</span><span class="panel-title"><span class="pt-bracket">[ </span><span class="pt-label">JOBS</span><span class="pt-bracket"> ]</span></span><span class="dim" style="margin-left:1ch;">─</span> <span class="summary" id="job-summary">0 done · 0 active · 0 fail</span><span class="frame-fill"></span><span class="frame-corner">┤</span></div>
    <div class="body-section" id="rows"></div>
  </section>
  <div class="frame"><span class="frame-corner">└</span><span class="frame-fill"></span><span class="frame-corner">┘</span></div>
</div>

</div>
</div>

<div id="keybar">
  <span class="kb-item"><span class="kb-key"><span class="kb-bracket">[</span> <span class="kb-chord">⌘↵</span> <span class="kb-bracket">]</span></span><span class="kb-action">download</span></span>
  <span class="kb-item"><span class="kb-key"><span class="kb-bracket">[</span> <span class="kb-chord">esc</span> <span class="kb-bracket">]</span></span><span class="kb-action">cancel</span></span>
  <span class="kb-item"><span class="kb-key"><span class="kb-bracket">[</span> <span class="kb-chord">⌘T</span> <span class="kb-bracket">]</span></span><span class="kb-action">theme</span></span>
  <span class="kb-item"><span class="kb-key"><span class="kb-bracket">[</span> <span class="kb-chord">⌘K</span> <span class="kb-bracket">]</span></span><span class="kb-action">picker</span></span>
  <span class="kb-item"><span class="kb-key"><span class="kb-bracket">[</span> <span class="kb-chord">⌘/</span> <span class="kb-bracket">]</span></span><span class="kb-action">help</span></span>
</div>

<div id="theme-popover" hidden role="dialog" aria-label="Switch theme">
  <div class="pop-header"><span>switch theme</span><span class="dim">⌘T to cycle</span></div>
  <div class="pop-sub">click to apply · saved to localStorage</div>
  <input class="pop-search" id="pop-search" placeholder="search…" autocomplete="off">
  <div class="grid" id="pop-grid"></div>
</div>

<template id="card-template">
  <article class="card" data-state="queued">
    <div class="card-thumb card-thumb--placeholder"></div>
    <div class="card-body">
      <header class="card-head">
        <span class="card-title"></span>
        <span class="card-meta"></span>
        <span class="card-badge">[--]</span>
      </header>
      <div class="card-progress">
        <div class="card-bar"><span style="width:0%"></span></div>
        <div class="card-stats"></div>
        <button type="button" class="card-reveal" hidden>↗</button>
      </div>
      <ul class="card-log"></ul>
    </div>
  </article>
</template>
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
  let counts = { done: 0, active: 0, fail: 0, queued: 0 };

  // ── Status indicator (top bar) ───────────────────────────────────────
  const statusIndicator = $('status-indicator');
  const sbMetaText = $('sb-meta-text');
  const SPIN_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
  let spinInterval = null;
  let spinFrame = 0;

  const reducedMotion = window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false;

  // ── Live clock ────────────────────────────────────────────────────────
  // Clock is information, not decoration — keeps ticking under reduced-motion.
  function tickClock() {
    const clockEl = $('sb-clock');
    if (!clockEl) return;
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const ss = String(now.getSeconds()).padStart(2, '0');
    clockEl.textContent = `${hh}:${mm}:${ss}`;
  }
  tickClock();
  setInterval(tickClock, 1000);

  function startSpinner() {
    if (spinInterval) return;
    spinFrame = 0;
    if (reducedMotion) {
      // No animation — show a static active indicator.
      const label = counts.active > 0
        ? ` downloading ${counts.active} / ${counts.done + counts.active}`
        : '';
      statusIndicator.textContent = '⠿' + label;
      return;
    }
    spinInterval = setInterval(() => {
      spinFrame = (spinFrame + 1) % SPIN_FRAMES.length;
      const label = counts.active > 0
        ? ` downloading ${counts.active} / ${counts.done + counts.active}`
        : '';
      statusIndicator.textContent = SPIN_FRAMES[spinFrame] + label;
    }, 100);
  }

  function stopSpinner() {
    if (spinInterval) { clearInterval(spinInterval); spinInterval = null; }
  }

  function updateStatusIndicator() {
    const { done, active, fail, queued } = counts;
    const total = done + active + fail + queued;
    stopSpinner();
    if (active > 0) {
      statusIndicator.className = 'active';
      startSpinner();
    } else if (total > 0 && active === 0 && queued === 0) {
      if (fail > 0 && done === 0) {
        statusIndicator.className = 'failed';
        statusIndicator.textContent = `! ${fail} failed`;
      } else if (fail > 0) {
        statusIndicator.className = 'failed';
        statusIndicator.textContent = `! ${done} done · ${fail} failed`;
      } else {
        statusIndicator.className = 'done';
        statusIndicator.textContent = `✓ ${done} done`;
      }
    } else {
      statusIndicator.className = '';
      statusIndicator.textContent = '◌ idle';
    }
  }

  function updateStatsMeta() {
    const { done, active, fail } = counts;
    const theme = document.documentElement.dataset.theme || 'phosphor';
    const jobs = $('jobs') ? parseInt($('jobs').value, 10) : 1;
    const frags = $('fragments') ? $('fragments').value : '4';
    const jobLabel = jobs === 1 ? '1 job' : `${jobs} jobs`;
    sbMetaText.textContent = `${jobLabel} · ${frags} frags · ${theme}`;
    $('stat-queued').textContent = String(counts.queued);
    $('stat-active').textContent = String(active);
    $('stat-done').textContent = String(done);
    $('stat-failed').textContent = String(fail);
  }

  function refreshSummary() {
    summary.textContent = `${counts.done} done · ${counts.active} active · ${counts.fail} fail`;
    updateStatusIndicator();
    updateStatsMeta();
  }

  // ── Card rendering — rich job cards ────────────────────────────────────
  const cardEls = {};   // url -> HTMLElement
  const cardState = {}; // url -> { phase, title, uploader, duration, thumbnail_ready, log[], etc. }

  function upsertCard(url) {
    if (cardEls[url]) return cardEls[url];
    const tpl = $('card-template');
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.url = url;
    rows.appendChild(node);
    cardEls[url] = node;
    if (!cardState[url]) cardState[url] = { phase: 'queued', log: [] };
    node.querySelector('.card-title').textContent = url;
    return node;
  }

  function phaseBadge(phase) {
    switch (phase) {
      case 'downloading':    return '[..]';
      case 'postprocessing': return '[~~]';
      case 'complete':       return '[OK]';
      case 'failed':         return '[xx]';
      case 'resolving':      return '[??]';
      default:               return '[--]';
    }
  }

  function formatDuration(seconds) {
    if (seconds == null) return '';
    const m = Math.floor(seconds / 60);
    const s = String(seconds % 60).padStart(2, '0');
    return m + ':' + s;
  }

  function formatBytes(n) {
    if (!n) return '0B';
    const units = ['B','KB','MB','GB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return n.toFixed(n >= 100 || i === 0 ? 0 : 1) + units[i];
  }

  function progressStats(st) {
    if (st.phase === 'postprocessing') return 'extracting audio…';
    if (st.phase === 'complete') {
      return st.total_bytes ? ('saved · ' + formatBytes(st.total_bytes)) : 'done';
    }
    if (st.phase === 'failed') return 'failed';
    if (st.phase === 'downloading') {
      const parts = [];
      if (st.speed) parts.push(formatBytes(st.speed) + '/s');
      if (st.eta != null) parts.push('ETA ' + formatDuration(st.eta));
      if (st.downloaded_bytes && st.total_bytes) {
        parts.push(formatBytes(st.downloaded_bytes) + '/' + formatBytes(st.total_bytes));
      }
      return parts.join(' · ');
    }
    return '';
  }

  function renderCard(url) {
    const el = upsertCard(url);
    const st = cardState[url] || {};
    el.dataset.state = st.phase || 'queued';

    // Title row
    if (st.title) {
      el.querySelector('.card-title').textContent = st.title;
      const metaParts = [];
      if (st.uploader) metaParts.push(st.uploader);
      if (st.duration) metaParts.push(formatDuration(st.duration));
      el.querySelector('.card-meta').textContent = metaParts.join(' · ');
    } else {
      el.querySelector('.card-title').textContent = url;
      el.querySelector('.card-meta').textContent = '';
    }

    // Badge
    el.querySelector('.card-badge').textContent = phaseBadge(st.phase);

    // Thumbnail
    const thumb = el.querySelector('.card-thumb');
    if (st.thumbnail_ready && currentJobId) {
      thumb.classList.remove('card-thumb--placeholder');
      const idx = st.url_idx != null ? st.url_idx : 0;
      thumb.innerHTML = `<img src="/jobs/${currentJobId}/thumb/${idx}.jpg?token=${encodeURIComponent(CSRF_TOKEN)}" alt="">`;
    } else {
      thumb.classList.add('card-thumb--placeholder');
      thumb.innerHTML = '';
    }

    // Progress
    el.querySelector('.card-bar span').style.width = (st.percent || 0) + '%';
    el.querySelector('.card-stats').textContent = progressStats(st);

    // Reveal-in-Finder button
    const revealBtn = el.querySelector('.card-reveal');
    if (st.phase === 'complete' && st.paths && st.paths.length > 0) {
      revealBtn.hidden = false;
      revealBtn.onclick = () => {
        fetch('/reveal', {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-Audio-DL-Token': CSRF_TOKEN},
          body: JSON.stringify({path: st.paths[0]}),
        });
      };
    } else {
      revealBtn.hidden = true;
      revealBtn.onclick = null;
    }

    // Log tail — last 3
    const ul = el.querySelector('.card-log');
    ul.innerHTML = '';
    const tail = (st.log || []).slice(-3);
    for (const line of tail) {
      const li = document.createElement('li');
      li.className = 'card-log-line';
      li.dataset.level = line.level;
      li.textContent = line.text;
      ul.appendChild(li);
    }
  }

  // Derive counts from current card states. Idempotent — called after every
  // state transition rather than incrementing on each event. Avoids drift when
  // a job_snapshot's states overlap with queued live events from the same
  // connection window (the SSE broadcast can deliver both for the same URL).
  function recountFromCards() {
    const next = { done: 0, active: 0, fail: 0, queued: 0 };
    rows.querySelectorAll('.card').forEach(card => {
      const s = card.dataset.state;
      if (s === 'complete') next.done++;
      else if (s === 'downloading' || s === 'postprocessing' || s === 'resolving') next.active++;
      else if (s === 'failed') next.fail++;
      else next.queued++;
    });
    counts = next;
    refreshSummary();
  }

  function handleEvent(ev) {
    if (ev.type === 'job_snapshot') {
      for (let i = 0; i < ev.urls.length; i++) {
        const u = ev.urls[i];
        // Map legacy status to phase when phase is absent
        let phase = u.phase;
        if (!phase) {
          if (u.status === 'completed') phase = 'complete';
          else if (u.status === 'failed') phase = 'failed';
          else if (u.status === 'cancelled') phase = 'failed';
          else if (u.status === 'downloading') phase = 'downloading';
          else phase = 'queued';
        }
        cardState[u.url] = {
          url_idx: i,
          phase,
          title: u.title, uploader: u.uploader, duration: u.duration,
          thumbnail_ready: u.thumbnail_ready, log: u.log || [],
          percent: u.percent, speed: u.speed, eta: u.eta,
          downloaded_bytes: u.downloaded_bytes, total_bytes: u.total_bytes,
          paths: u.paths,
        };
        renderCard(u.url);
      }
      recountFromCards();
      if (ev.complete) {
        $('submit').disabled = false;
        $('cancel').disabled = true;
        stopSpinner();
        // recountFromCards already called above; updateStatusIndicator() runs
        // via refreshSummary() inside it, reflecting the completed state.
      }
    } else if (ev.type === 'url_started') {
      if (!cardState[ev.url]) cardState[ev.url] = { log: [] };
      cardState[ev.url].phase = 'resolving';
      if (cardState[ev.url].url_idx === undefined) {
        cardState[ev.url].url_idx = Object.keys(cardState).indexOf(ev.url);
      }
      renderCard(ev.url);
      recountFromCards();
    } else if (ev.type === 'url_metadata') {
      if (!cardState[ev.url]) cardState[ev.url] = { log: [] };
      Object.assign(cardState[ev.url], {
        title: ev.title, uploader: ev.uploader, duration: ev.duration,
        thumbnail_ready: ev.thumbnail_ready,
      });
      if (cardState[ev.url].url_idx === undefined) {
        cardState[ev.url].url_idx = Object.keys(cardState).indexOf(ev.url);
      }
      renderCard(ev.url);
    } else if (ev.type === 'progress') {
      if (!cardState[ev.url]) cardState[ev.url] = { log: [] };
      Object.assign(cardState[ev.url], {
        phase: ev.phase || cardState[ev.url].phase,
        percent: ev.percent,
        speed: ev.speed, eta: ev.eta,
        downloaded_bytes: ev.downloaded_bytes, total_bytes: ev.total_bytes,
      });
      renderCard(ev.url);
    } else if (ev.type === 'url_log') {
      if (!cardState[ev.url]) cardState[ev.url] = { log: [] };
      cardState[ev.url].log = cardState[ev.url].log || [];
      cardState[ev.url].log.push({ level: ev.level, text: ev.text, ts: ev.ts });
      if (cardState[ev.url].log.length > 50) cardState[ev.url].log.shift();
      renderCard(ev.url);
    } else if (ev.type === 'url_completed') {
      if (!cardState[ev.url]) cardState[ev.url] = { log: [] };
      cardState[ev.url].phase = 'complete';
      cardState[ev.url].paths = ev.paths;
      renderCard(ev.url);
      recountFromCards();
    } else if (ev.type === 'url_failed') {
      if (!cardState[ev.url]) cardState[ev.url] = { log: [] };
      cardState[ev.url].phase = 'failed';
      cardState[ev.url].error = ev.error;
      renderCard(ev.url);
      recountFromCards();
    } else if (ev.type === 'job_completed') {
      $('submit').disabled = false;
      $('cancel').disabled = true;
      es && es.close();
      es = null;
      currentJobId = null;
      stopSpinner();
      // Re-derive counts from cards so the indicator reflects final state.
      recountFromCards();
    }
  }

  // Update status bar meta text when sliders change.
  ['jobs', 'fragments'].forEach(id => {
    $(id).addEventListener('input', updateStatsMeta);
  });
  // Initial meta text render.
  updateStatsMeta();

  $('dl').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('submit').disabled = true;
    $('cancel').disabled = false;
    rows.innerHTML = '';
    // Reset card state so re-submissions don't reuse detached DOM nodes.
    for (const k in cardEls) delete cardEls[k];
    for (const k in cardState) delete cardState[k];
    stopSpinner();
    counts = { done: 0, active: 0, fail: 0, queued: 0 };
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

  // Reflect the active theme in the header button and status bar meta.
  function refreshThemeLabel() {
    const cur = document.documentElement.dataset.theme || 'phosphor';
    $('theme-current').textContent = cur;
    updateStatsMeta();
  }
  refreshThemeLabel();
  window.refreshThemeLabel = refreshThemeLabel;  // Picker calls this on change.

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
                # v1.6 — rich card fields
                "title": s.title,
                "uploader": s.uploader,
                "duration": s.duration,
                "thumbnail_ready": s.thumbnail_ready,
                "phase": s.phase,
                "log": list(s.log),
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
                pass
            remaining = len(job.subscribers)
        if job.completed and remaining == 0:
            _cleanup_thumb_dir(job)


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


@app.get("/jobs/{job_id}/thumb/{url_idx}.jpg")
async def get_thumbnail(
    job_id: str,
    url_idx: int,
    _csrf: str = Depends(_require_csrf),  # pylint: disable=unused-argument
) -> FileResponse:
    """Serve a per-URL thumbnail from the job-scoped temp dir.

    CSRF-guarded via ?token=... query param (image tags can't send custom
    headers). Returns 404 if job unknown, url_idx out of range, or thumb
    not yet on disk.
    """
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"unknown job_id: {job_id}")
    if url_idx < 0 or url_idx >= len(job.url_states):
        raise HTTPException(404, "url_idx out of range")
    path = os.path.join(_thumb_dir(job_id), f"{url_idx}.jpg")
    if not os.path.exists(path):
        raise HTTPException(404, "thumbnail not ready")
    return FileResponse(path, media_type="image/jpeg")


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
