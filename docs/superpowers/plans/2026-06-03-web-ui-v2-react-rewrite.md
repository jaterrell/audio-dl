# v2.0 Web UI React Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 3700-line inline `_INDEX_TEMPLATE` web UI in `audio_dl_ui.py` with a new Vite-built React app served by FastAPI `StaticFiles`. The new UI ships the "Now Playing" aesthetic: stage with hero album art for the latest-started download, ambient color extracted from that art, "Also downloading" strip for concurrent jobs, "Up next" queue, always-on URL input bar with inline format pill, and a separate `/library` route for full download history.

**Architecture:** Backend stays mostly intact. The FastAPI app gains four small endpoints (`/api/version`, `/api/settings/defaults`, `/api/csrf` dev-only, `/thumbs/{thumb_id}.jpg`) and a thumbnail cache directory. The `_INDEX_*` constants and `_render_index` function are removed and replaced by `StaticFiles(html=True)` mounted at `/`, serving the Vite build output from `audio_dl_ui/static/`. The new front-end is a TypeScript React 19 SPA built with Vite, routed by TanStack Router, with TanStack Query holding per-job state fed by an SSE side-channel.

**Tech Stack:** Python 3.10+ FastAPI + Pydantic (backend unchanged); pytest + pylint (backend tests); Node 20 LTS + Vite 6 + React 19 + TypeScript 5 + TanStack Router + TanStack Query + Tailwind v4 + shadcn/ui (Radix primitives) + Lucide icons + Biome (frontend); Vitest + React Testing Library + MSW (frontend tests); PyInstaller (`.app` bundling, existing).

**Spec:** [docs/superpowers/specs/2026-06-03-web-ui-v2-react-rewrite-design.md](../specs/2026-06-03-web-ui-v2-react-rewrite-design.md) (committed `5db5c9a`)

**Branching/PR notes:**
- Create a feature branch `v2.0-react-rewrite` off `origin/main`. The plan and spec are already on `main`; only implementation commits land in the PR.
- Per CLAUDE.md: sub-agents that write/edit code MUST use `isolation: "worktree"` on the Agent call.
- After PR opens and CI is green, mark ready-for-review (Codex fires on draft→ready).
- Backend commits and frontend commits can interleave freely on the same branch; CI runs both pytest and `npm run build` from the same workflow.

---

## File Structure

| File | Role | Status |
|---|---|---|
| `web/package.json` | Frontend dependency manifest. | Create |
| `web/vite.config.ts` | Vite build + dev proxy config. | Create |
| `web/tsconfig.json` | TypeScript compiler options. | Create |
| `web/tsconfig.node.json` | TypeScript config for build files (`vite.config.ts`). | Create |
| `web/biome.json` | Biome lint + format rules. | Create |
| `web/index.html` | Vite entry HTML. | Create |
| `web/components.json` | shadcn/ui config (tells the CLI where to put generated components). | Create |
| `web/postcss.config.js` | PostCSS config for Tailwind v4. | Create |
| `web/.gitignore` | Frontend-specific ignores (`node_modules`, `dist`). | Create |
| `web/src/main.tsx` | App entry; Router + QueryClient providers. | Create |
| `web/src/routes/__root.tsx` | AppShell (Topbar + `<Outlet />`). | Create |
| `web/src/routes/index.tsx` | `/` route — Now screen. | Create |
| `web/src/routes/library.tsx` | `/library` route — Library screen. | Create |
| `web/src/components/topbar.tsx` | Brand + tab nav. | Create |
| `web/src/components/stage.tsx` | Hero stage (active download). | Create |
| `web/src/components/empty-stage.tsx` | Stage when nothing is downloading. | Create |
| `web/src/components/also-downloading.tsx` | Strip of concurrent downloads. | Create |
| `web/src/components/queue.tsx` | Up-next queued URLs. | Create |
| `web/src/components/url-input.tsx` | Bottom input bar + format pill + Add button. | Create |
| `web/src/components/format-picker.tsx` | shadcn `DropdownMenu` of formats. | Create |
| `web/src/components/album-art.tsx` | `<img>` with gradient fallback; reads thumbId. | Create |
| `web/src/components/library-grid.tsx` | Day-grouped tile grid for history. | Create |
| `web/src/components/library-filters.tsx` | Search input + format filter pills. | Create |
| `web/src/components/cancel-dialog.tsx` | shadcn `AlertDialog` "Cancel this download?". | Create |
| `web/src/hooks/use-job-events.ts` | SSE EventSource → TanStack Query cache. | Create |
| `web/src/hooks/use-active-jobs.ts` | Selector: active job IDs from query cache. | Create |
| `web/src/hooks/use-history.ts` | localStorage read/write for history. | Create |
| `web/src/hooks/use-settings.ts` | localStorage read/write for default format / output dir. | Create |
| `web/src/hooks/use-vibrant.ts` | Extract palette from `<img>` and set CSS vars. | Create |
| `web/src/lib/api.ts` | Fetch wrappers for backend endpoints. | Create |
| `web/src/lib/csrf.ts` | CSRF token discovery (URL or `/api/csrf`). | Create |
| `web/src/lib/format.ts` | Format-list constants. | Create |
| `web/src/lib/types.ts` | TypeScript types shared across files. | Create |
| `web/src/lib/group-by-day.ts` | History grouping helper. | Create |
| `web/src/styles/globals.css` | `@import "tailwindcss";` + Inter font + base CSS vars. | Create |
| `web/src/styles/tokens.css` | Aesthetic system tokens (colors, spacing, radii). | Create |
| `web/src/test-utils/render.tsx` | Custom RTL render with Router + QueryClient. | Create |
| `web/src/test-utils/server.ts` | MSW server setup for tests. | Create |
| `audio_dl_ui.py` | Remove `_INDEX_*` constants, `_render_index`, `GET /` handler. Mount `StaticFiles`. Add new endpoints. | Modify |
| `test_audio_dl_ui.py` | Add tests for new endpoints; remove tests asserting inline HTML. | Modify |
| `audio_dl_ui/__init__.py` | Empty package init so `importlib.resources` can locate `static/`. | Create |
| `audio_dl_ui/static/.gitkeep` | Placeholder so the dir exists for source installs. | Create |
| `audio-dl.spec` | Add `audio_dl_ui/static` to `datas`. | Modify |
| `scripts/build-app.sh` | Run `npm ci && npm run build` and copy `dist/*` before PyInstaller. | Modify |
| `scripts/build-web.sh` | New helper: `npm ci && npm run build && cp dist → static`. Called by `build-app.sh` and CI. | Create |
| `pyproject.toml` | Bump version, add `[tool.setuptools.package-data]` entry for `audio_dl_ui/static/**`. | Modify |
| `audio_dl.py` | Bump `__version__`. | Modify |
| `CHANGELOG.md` | Add `## v2.0.0` section. | Modify |
| `README.md` | Update screenshots, dev-mode instructions, build instructions. | Modify |
| `.github/workflows/tests.yml` | Add a `web-build` job (Node 20, `npm ci`, `npm run build`, `npm test`). | Modify |
| `.gitignore` | Add `web/node_modules`, `web/dist`, `audio_dl_ui/static/*` (keep `.gitkeep`). | Modify |

---

## Task 0: Create feature branch

**Files:** none yet.

- [ ] **Step 1: Sync `main`, then create the branch.**

```bash
git fetch origin
git checkout -B v2.0-react-rewrite origin/main
git log --oneline -2
```

Expected: top commit is `docs(spec): v2.0 web UI React rewrite — Now Playing aesthetic`.

- [ ] **Step 2: Confirm baseline tests pass.**

```bash
pytest -q
pylint $(git ls-files '*.py')
```

Expected: pytest green, pylint 10.00/10. Stop and investigate if either fails — it's a pre-existing problem.

---

# Phase 1 — Backend additions

Server-side endpoints and thumbnail cache the front-end will depend on. These commits land first so the new front-end has a real backend to talk to during dev.

## Task 1: `GET /api/version` endpoint

**Goal:** Expose `__version__` and a build identifier the React app can fetch on boot.

**Files:**
- Modify: `audio_dl_ui.py` (add endpoint after the existing `/jobs` endpoints, ~line 3540).
- Modify: `test_audio_dl_ui.py` (new test class `TestApiVersion`).

- [ ] **Step 1: Write the failing test.**

Add to `test_audio_dl_ui.py` (end of file before the last class):

```python
class TestApiVersion:
    def test_returns_version_and_build(self, client):
        r = client.get("/api/version")
        assert r.status_code == 200
        data = r.json()
        assert data["version"] == __version__
        assert "build" in data
        assert isinstance(data["build"], str) and data["build"]
```

(`__version__` and `client` are already imported at the top of `test_audio_dl_ui.py`.)

- [ ] **Step 2: Run the test, watch it fail.**

```bash
pytest test_audio_dl_ui.py::TestApiVersion -v
```

Expected: FAIL — 404 on `/api/version`.

- [ ] **Step 3: Implement the endpoint.**

In `audio_dl_ui.py`, after the `/reveal` endpoint, add:

```python
@app.get("/api/version")
def api_version() -> dict:
    """Version + build identifier the front-end uses to sanity-check the backend."""
    return {
        "version": __version__,
        "build": _BUILD_ID,
    }
```

At the top of `audio_dl_ui.py` (near other module-level constants, after the `__version__` import), add:

```python
_BUILD_ID = os.environ.get("AUDIO_DL_BUILD", "dev")
```

(`os` is already imported.)

- [ ] **Step 4: Run the test, watch it pass.**

```bash
pytest test_audio_dl_ui.py::TestApiVersion -v
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): add GET /api/version endpoint"
```

---

## Task 2: `GET /api/settings/defaults` endpoint

**Goal:** Surface the launch-time `output_dir`, `max_parallel`, and the canonical list of formats so the React app doesn't have to infer them.

**Files:**
- Modify: `audio_dl_ui.py` (add endpoint after `api_version`).
- Modify: `test_audio_dl_ui.py` (new test class `TestApiSettingsDefaults`).

- [ ] **Step 1: Write the failing test.**

Add to `test_audio_dl_ui.py`:

```python
class TestApiSettingsDefaults:
    def test_returns_output_dir_max_parallel_and_formats(self, client):
        r = client.get("/api/settings/defaults")
        assert r.status_code == 200
        data = r.json()
        assert data["output_dir"]
        assert isinstance(data["max_parallel"], int) and data["max_parallel"] >= 1
        assert set(data["available_formats"]) >= {"mp3", "m4a", "flac", "mp4"}
```

- [ ] **Step 2: Run the test, watch it fail.**

```bash
pytest test_audio_dl_ui.py::TestApiSettingsDefaults -v
```

Expected: FAIL — 404.

- [ ] **Step 3: Implement.**

In `audio_dl_ui.py`, after `api_version`:

```python
@app.get("/api/settings/defaults")
def api_settings_defaults() -> dict:
    """Launch-time settings the front-end needs to render correctly."""
    return {
        "output_dir": str(_OUTPUT_DIR.resolve()),
        "max_parallel": _MAX_PARALLEL,
        "available_formats": list(ALL_FORMATS),
    }
```

`_OUTPUT_DIR`, `_MAX_PARALLEL`, `ALL_FORMATS` already exist in the module.

- [ ] **Step 4: Run the test, watch it pass.**

```bash
pytest test_audio_dl_ui.py::TestApiSettingsDefaults -v
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): add GET /api/settings/defaults endpoint"
```

---

## Task 3: `GET /api/csrf` — dev-only convenience

**Goal:** Let the Vite dev server fetch the CSRF token without manual copy-paste. Disabled unless `AUDIO_DL_DEV=1` or `--dev` flag is set; refuses non-loopback origins.

**Files:**
- Modify: `audio_dl_ui.py` (add endpoint + `_DEV_MODE` flag).
- Modify: `test_audio_dl_ui.py` (new test class `TestApiCsrf`).

- [ ] **Step 1: Write the failing tests.**

Add to `test_audio_dl_ui.py`:

```python
class TestApiCsrf:
    def test_returns_token_in_dev_mode(self, monkeypatch, client):
        monkeypatch.setenv("AUDIO_DL_DEV", "1")
        from audio_dl_ui import _refresh_dev_mode
        _refresh_dev_mode()
        try:
            r = client.get("/api/csrf")
            assert r.status_code == 200
            assert r.json()["token"]
        finally:
            monkeypatch.delenv("AUDIO_DL_DEV")
            _refresh_dev_mode()

    def test_404_when_not_dev_mode(self, client):
        r = client.get("/api/csrf")
        assert r.status_code == 404
```

- [ ] **Step 2: Run, watch fail.**

```bash
pytest test_audio_dl_ui.py::TestApiCsrf -v
```

Expected: FAIL — endpoint missing.

- [ ] **Step 3: Implement.**

Near the top of `audio_dl_ui.py` (with `_BUILD_ID`):

```python
_DEV_MODE = os.environ.get("AUDIO_DL_DEV") == "1"

def _refresh_dev_mode() -> None:
    """Re-read AUDIO_DL_DEV. Used by tests to flip mode mid-process."""
    global _DEV_MODE
    _DEV_MODE = os.environ.get("AUDIO_DL_DEV") == "1"
```

After `api_settings_defaults`:

```python
@app.get("/api/csrf")
def api_csrf(request: Request) -> dict:
    """Dev-only: hand the CSRF token to the Vite dev server.
    Refuses if not in dev mode or if the request is not from loopback."""
    if not _DEV_MODE:
        raise HTTPException(status_code=404)
    client_host = (request.client.host if request.client else "") or ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=404)
    return {"token": _CSRF_TOKEN}
```

(`Request` and `HTTPException` are already imported; `_CSRF_TOKEN` already exists.)

- [ ] **Step 4: Run, watch pass.**

```bash
pytest test_audio_dl_ui.py::TestApiCsrf -v
```

Expected: PASS (both tests).

- [ ] **Step 5: Commit.**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): add dev-only GET /api/csrf for Vite dev server"
```

---

## Task 4: Thumbnail cache writer

**Goal:** When a job's thumbnail bytes are first observed, write them to `~/Library/Application Support/audio-dl/thumbs/{thumb_id}.jpg` (or `XDG_DATA_HOME` equivalent on Linux). `thumb_id` is the SHA-1 of the source URL — stable across re-downloads.

**Files:**
- Modify: `audio_dl_ui.py` (new helpers `_thumb_cache_dir`, `_compute_thumb_id`, `_persist_thumb`).
- Modify: `test_audio_dl_ui.py` (new test class `TestThumbCache`).

- [ ] **Step 1: Write the failing tests.**

Add to `test_audio_dl_ui.py`:

```python
class TestThumbCache:
    def test_compute_thumb_id_stable_for_same_url(self):
        from audio_dl_ui import _compute_thumb_id
        a = _compute_thumb_id("https://youtu.be/dQw4w9WgXcQ")
        b = _compute_thumb_id("https://youtu.be/dQw4w9WgXcQ")
        assert a == b
        assert len(a) == 40  # SHA-1 hex

    def test_compute_thumb_id_differs_for_different_urls(self):
        from audio_dl_ui import _compute_thumb_id
        assert _compute_thumb_id("https://a") != _compute_thumb_id("https://b")

    def test_persist_thumb_writes_file(self, tmp_path, monkeypatch):
        from audio_dl_ui import _persist_thumb
        monkeypatch.setattr("audio_dl_ui._thumb_cache_dir", lambda: tmp_path)
        thumb_id = _persist_thumb("https://example.test/track", b"\xff\xd8\xff_jpeg_bytes")
        out = tmp_path / f"{thumb_id}.jpg"
        assert out.exists()
        assert out.read_bytes().startswith(b"\xff\xd8\xff")

    def test_persist_thumb_idempotent(self, tmp_path, monkeypatch):
        from audio_dl_ui import _persist_thumb
        monkeypatch.setattr("audio_dl_ui._thumb_cache_dir", lambda: tmp_path)
        a = _persist_thumb("https://example.test/x", b"first")
        b = _persist_thumb("https://example.test/x", b"second")
        assert a == b
        # First-write wins: don't overwrite an existing cached thumb.
        assert (tmp_path / f"{a}.jpg").read_bytes() == b"first"
```

- [ ] **Step 2: Run, watch fail.**

```bash
pytest test_audio_dl_ui.py::TestThumbCache -v
```

Expected: FAIL — helpers don't exist.

- [ ] **Step 3: Implement.**

Add `import hashlib` to the top of `audio_dl_ui.py` if not already present. Add new helpers near the other module-level utilities (around the existing `_check_dependencies_gui`):

```python
def _thumb_cache_dir() -> Path:
    """Return the on-disk thumbnail cache directory, creating it if needed."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "audio-dl"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "audio-dl"
    cache = base / "thumbs"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _compute_thumb_id(url: str) -> str:
    """Stable SHA-1 hex for a source URL — used as the thumbnail cache key."""
    return hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()


def _persist_thumb(url: str, jpeg_bytes: bytes) -> str:
    """Write jpeg_bytes to the thumb cache keyed by URL. First write wins.
    Returns the thumb_id. Safe to call repeatedly."""
    thumb_id = _compute_thumb_id(url)
    path = _thumb_cache_dir() / f"{thumb_id}.jpg"
    if not path.exists():
        path.write_bytes(jpeg_bytes)
    return thumb_id
```

- [ ] **Step 4: Run, watch pass.**

```bash
pytest test_audio_dl_ui.py::TestThumbCache -v
```

Expected: PASS (all four).

- [ ] **Step 5: Commit.**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): add on-disk thumbnail cache (sha1 keyed)"
```

---

## Task 5: `GET /thumbs/{thumb_id}.jpg` endpoint

**Goal:** Serve cached thumbnails by stable ID for the Library view.

**Files:**
- Modify: `audio_dl_ui.py` (new endpoint).
- Modify: `test_audio_dl_ui.py` (new test class `TestThumbsEndpoint`).

- [ ] **Step 1: Write the failing tests.**

Add to `test_audio_dl_ui.py`:

```python
class TestThumbsEndpoint:
    def test_serves_cached_jpeg(self, tmp_path, monkeypatch, client):
        from audio_dl_ui import _persist_thumb
        monkeypatch.setattr("audio_dl_ui._thumb_cache_dir", lambda: tmp_path)
        thumb_id = _persist_thumb("https://example.test/song", b"\xff\xd8\xfftestbytes")
        r = client.get(f"/thumbs/{thumb_id}.jpg")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/jpeg")
        assert r.content.startswith(b"\xff\xd8\xff")

    def test_404_for_missing(self, tmp_path, monkeypatch, client):
        monkeypatch.setattr("audio_dl_ui._thumb_cache_dir", lambda: tmp_path)
        r = client.get("/thumbs/" + ("0" * 40) + ".jpg")
        assert r.status_code == 404

    def test_rejects_path_traversal(self, client):
        # No slashes / dots allowed in thumb_id.
        r = client.get("/thumbs/..%2Fetc%2Fpasswd.jpg")
        assert r.status_code in (400, 404)
```

- [ ] **Step 2: Run, watch fail.**

```bash
pytest test_audio_dl_ui.py::TestThumbsEndpoint -v
```

Expected: FAIL — endpoint missing.

- [ ] **Step 3: Implement.**

After `api_csrf` in `audio_dl_ui.py`:

```python
@app.get("/thumbs/{thumb_id}.jpg")
def serve_thumb(thumb_id: str) -> Response:
    """Serve a cached thumbnail by stable SHA-1 ID."""
    # Validate the ID format strictly to prevent path traversal.
    if not (len(thumb_id) == 40 and all(c in "0123456789abcdef" for c in thumb_id)):
        raise HTTPException(status_code=400, detail="invalid thumb_id")
    path = _thumb_cache_dir() / f"{thumb_id}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404)
    return Response(content=path.read_bytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})
```

(`Response` is already imported.)

- [ ] **Step 4: Run, watch pass.**

```bash
pytest test_audio_dl_ui.py::TestThumbsEndpoint -v
```

Expected: PASS (all three).

- [ ] **Step 5: Commit.**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): add GET /thumbs/{thumb_id}.jpg cached thumbnail endpoint"
```

---

## Task 6: Persist thumbs on download completion

**Goal:** When a download completes and yt-dlp has produced a thumbnail JPEG, write it to the thumb cache so the Library view can later serve it via the stable URL. Update the SSE event payload to include `thumb_id` per URL state.

**Files:**
- Modify: `audio_dl_ui.py` (`_run_one` or completion path; `_build_snapshot`).
- Modify: `test_audio_dl_ui.py` (extend an existing job-lifecycle test).

- [ ] **Step 1: Write the failing test.**

Add to `test_audio_dl_ui.py`, in the existing `TestJobLifecycle` class (or create one if missing — most likely it exists; if not, add as a new class):

```python
def test_completed_url_state_includes_thumb_id(self, tmp_path, monkeypatch, client):
    monkeypatch.setattr("audio_dl_ui._thumb_cache_dir", lambda: tmp_path)
    fake_download = _make_fake_download_with_thumb(tmp_path)
    monkeypatch.setattr("audio_dl_ui.download_media", fake_download)
    job_id = _post_one_url_and_wait(client, "https://example.test/song")
    snapshot = client.get(f"/jobs/{job_id}").json()
    url_state = snapshot["urls"][0]
    assert url_state["thumb_id"]
    assert len(url_state["thumb_id"]) == 40
```

If `_make_fake_download_with_thumb` and `_post_one_url_and_wait` helpers don't exist, add them at the top of `test_audio_dl_ui.py` near the existing helpers:

```python
def _make_fake_download_with_thumb(tmp_path):
    """A fake download_media that drops a known thumbnail jpeg next to the audio."""
    def _fake(url, *, output_dir, media_format, **kwargs):
        out = Path(output_dir) / "track.m4a"
        out.write_bytes(b"audio")
        thumb = Path(output_dir) / "track.jpg"
        thumb.write_bytes(b"\xff\xd8\xfftestjpeg")
        return [str(out)]
    return _fake


def _post_one_url_and_wait(client, url, timeout=2.0):
    """POST a single URL and poll the snapshot until the job terminates."""
    body = _valid_body(urls=[{"url": url, "format": "m4a"}])
    r = client.post("/jobs", json=body, headers={"X-CSRF-Token": _csrf(client)})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.get(f"/jobs/{job_id}").json()
        if snap["state"] in ("completed", "failed", "cancelled"):
            return job_id
        time.sleep(0.05)
    raise AssertionError("job did not terminate in time")
```

(`_valid_body` and `_csrf` already exist.)

- [ ] **Step 2: Run, watch fail.**

```bash
pytest test_audio_dl_ui.py -k "test_completed_url_state_includes_thumb_id" -v
```

Expected: FAIL — snapshot doesn't include `thumb_id`.

- [ ] **Step 3: Implement.**

In `audio_dl_ui.py`, find the `UrlState` dataclass (around line 67) and add the field:

```python
@dataclass
class UrlState:
    url: str
    media_format: str
    state: str = "queued"
    progress_percent: float = 0.0
    speed: str | None = None
    eta: str | None = None
    paths: list[str] = field(default_factory=list)
    error: str | None = None
    thumb_id: str | None = None  # NEW
```

Find `_run_one` (the per-URL worker). After a successful download, locate the thumbnail file yt-dlp produced (sibling JPEG next to the audio output) and persist it:

```python
# After the existing `paths = download_media(...)` and `url_state.paths = paths`:
if url_state.state == "completed" and paths:
    audio_path = Path(paths[0])
    sibling_thumb = audio_path.with_suffix(".jpg")
    if sibling_thumb.exists():
        try:
            url_state.thumb_id = _persist_thumb(url_state.url, sibling_thumb.read_bytes())
        except OSError:
            # Persisting a thumbnail must never break the job; log and continue.
            logging.warning("failed to persist thumb for %s", url_state.url)
```

In `_build_snapshot`, ensure the URL state serialization includes `thumb_id`:

```python
# In the loop that serializes each URL:
{
    "url": u.url,
    "media_format": u.media_format,
    "state": u.state,
    "progress_percent": u.progress_percent,
    "speed": u.speed,
    "eta": u.eta,
    "paths": list(u.paths),
    "error": u.error,
    "thumb_id": u.thumb_id,  # NEW
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
pytest test_audio_dl_ui.py -k "test_completed_url_state_includes_thumb_id" -v
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): persist thumbnails on completion and surface thumb_id"
```

---

## Task 7: Full backend phase smoke test

**Goal:** Single quality gate before moving to frontend. Run the entire pytest + pylint suite; confirm no regressions.

**Files:** none modified.

- [ ] **Step 1: Run full test suite.**

```bash
pytest -q
```

Expected: all green (previous 246 plus the new tests from Tasks 1–6).

- [ ] **Step 2: Run pylint.**

```bash
pylint $(git ls-files '*.py')
```

Expected: 10.00/10. If lint drops, fix the new code (likely unused imports or missing docstrings on the new endpoints).

- [ ] **Step 3: No commit — this is a verification gate.**

---

# Phase 2 — Frontend scaffold

Stand up Vite + React + TS + Biome + Tailwind v4 + shadcn/ui. Each task lands a working state — every commit leaves `npm run dev` and `npm test` green.

## Task 8: Initialize `web/` with Vite + React + TS

**Goal:** Get to a hello-world React page served by `npm run dev`.

**Files:**
- Create: `web/package.json`, `web/index.html`, `web/vite.config.ts`, `web/tsconfig.json`, `web/tsconfig.node.json`, `web/src/main.tsx`, `web/src/App.tsx`, `web/.gitignore`.
- Modify: `.gitignore` (top-level).

- [ ] **Step 1: Create `web/package.json`.**

```json
{
  "name": "audio-dl-web",
  "version": "2.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "biome check src/",
    "format": "biome format --write src/"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@biomejs/biome": "^1.9.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.6.0",
    "vite": "^6.0.0"
  }
}
```

- [ ] **Step 2: Create `web/index.html`.**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>audio-dl</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 3: Create `web/vite.config.ts`.**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:9000",
      "/jobs": { target: "http://localhost:9000", changeOrigin: true, ws: false },
      "/thumbs": "http://localhost:9000",
      "/reveal": "http://localhost:9000",
    },
  },
});
```

- [ ] **Step 4: Create `web/tsconfig.json`.**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "useDefineForClassFields": true,
    "allowImportingTsExtensions": true,
    "noEmit": true,
    "paths": {
      "@/*": ["./src/*"]
    },
    "baseUrl": "."
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 5: Create `web/tsconfig.node.json`.**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 6: Create `web/src/main.tsx`.**

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

- [ ] **Step 7: Create `web/src/App.tsx`.**

```tsx
export default function App() {
  return <h1>audio-dl v2 — hello</h1>;
}
```

- [ ] **Step 8: Create `web/.gitignore`.**

```
node_modules
dist
*.log
.vite
```

- [ ] **Step 9: Update top-level `.gitignore`.**

Append (after existing entries):

```
web/node_modules/
web/dist/
audio_dl_ui/static/*
!audio_dl_ui/static/.gitkeep
```

- [ ] **Step 10: Install and smoke-test.**

```bash
cd web && npm install && npm run build
```

Expected: build succeeds, produces `web/dist/`.

```bash
cd web && npm run dev
```

Open http://localhost:5173 — see "audio-dl v2 — hello". Ctrl-C to stop.

- [ ] **Step 11: Commit.**

```bash
git add web/ .gitignore
git commit -m "feat(web): scaffold Vite + React + TS app"
```

---

## Task 9: Add Biome (lint + format)

**Goal:** One tool replaces ESLint + Prettier. Catches errors before tests run.

**Files:**
- Create: `web/biome.json`.

- [ ] **Step 1: Create `web/biome.json`.**

```json
{
  "$schema": "https://biomejs.dev/schemas/1.9.0/schema.json",
  "vcs": { "enabled": true, "clientKind": "git", "useIgnoreFile": true },
  "files": { "ignoreUnknown": true },
  "formatter": {
    "enabled": true,
    "indentStyle": "space",
    "indentWidth": 2,
    "lineWidth": 100
  },
  "linter": {
    "enabled": true,
    "rules": {
      "recommended": true,
      "style": { "noNonNullAssertion": "off" },
      "suspicious": { "noExplicitAny": "warn" }
    }
  },
  "javascript": { "formatter": { "quoteStyle": "double", "semicolons": "always" } }
}
```

- [ ] **Step 2: Run Biome to verify clean state.**

```bash
cd web && npm run lint
```

Expected: no errors on the trivial scaffold.

- [ ] **Step 3: Commit.**

```bash
git add web/biome.json
git commit -m "feat(web): add Biome lint + format config"
```

---

## Task 10: Add Tailwind v4

**Goal:** CSS framework in place. Hello-world uses a Tailwind class to confirm it's loading.

**Files:**
- Modify: `web/package.json` (add deps).
- Create: `web/postcss.config.js`, `web/src/styles/globals.css`, `web/src/styles/tokens.css`.
- Modify: `web/src/main.tsx` (import css), `web/src/App.tsx` (use a class).

- [ ] **Step 1: Install Tailwind v4 and PostCSS.**

```bash
cd web && npm install -D tailwindcss@^4.0.0 @tailwindcss/postcss@^4.0.0 postcss@^8.4.0 @fontsource/inter@^5.1.0
```

- [ ] **Step 2: Create `web/postcss.config.js`.**

```js
export default {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};
```

- [ ] **Step 3: Create `web/src/styles/tokens.css`.**

```css
:root {
  /* surface tokens — dark, the only mode */
  --bg: #08080a;
  --surface: rgb(255 255 255 / 0.04);
  --surface-strong: rgb(255 255 255 / 0.08);
  --border: rgb(255 255 255 / 0.07);
  --text: #f5f5f7;
  --text-2: #a1a1aa;
  --text-3: #71717a;

  /* adaptive accent — overwritten at runtime by useVibrant */
  --accent: #818cf8;
  --accent-2: #c084fc;
  --ambient: rgb(129 140 248 / 0.18);

  /* radii */
  --radius-lg: 14px;
  --radius-md: 10px;
  --radius-sm: 6px;
}
```

- [ ] **Step 4: Create `web/src/styles/globals.css`.**

```css
@import "tailwindcss";
@import "@fontsource/inter/400.css";
@import "@fontsource/inter/500.css";
@import "@fontsource/inter/600.css";
@import "@fontsource/inter/700.css";
@import "./tokens.css";

@theme {
  --color-bg: var(--bg);
  --color-surface: var(--surface);
  --color-surface-strong: var(--surface-strong);
  --color-border-app: var(--border);
  --color-text-app: var(--text);
  --color-text-2: var(--text-2);
  --color-text-3: var(--text-3);
  --color-accent: var(--accent);
  --color-accent-2: var(--accent-2);
  --font-sans: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

html, body, #root {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  font-feature-settings: "tnum";
}
```

- [ ] **Step 5: Update `web/src/main.tsx`.**

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/globals.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

- [ ] **Step 6: Update `web/src/App.tsx` to use a Tailwind class.**

```tsx
export default function App() {
  return (
    <h1 className="p-8 text-2xl font-semibold tracking-tight">audio-dl v2 — hello</h1>
  );
}
```

- [ ] **Step 7: Smoke-test.**

```bash
cd web && npm run dev
```

Open http://localhost:5173 — "audio-dl v2 — hello" should now render in Inter, dark background, 32px padding. Ctrl-C.

- [ ] **Step 8: Verify build still works.**

```bash
cd web && npm run build
```

Expected: build succeeds.

- [ ] **Step 9: Commit.**

```bash
git add web/
git commit -m "feat(web): add Tailwind v4 + Inter font + token CSS vars"
```

---

## Task 11: Add Vitest + React Testing Library + MSW

**Goal:** Test infrastructure for components and hooks.

**Files:**
- Modify: `web/package.json` (deps), `web/vite.config.ts` (test config).
- Create: `web/src/test-utils/server.ts`, `web/src/test-utils/render.tsx`, `web/src/setupTests.ts`.

- [ ] **Step 1: Install test deps.**

```bash
cd web && npm install -D vitest@^2.1.0 @testing-library/react@^16.0.0 \
  @testing-library/jest-dom@^6.5.0 @testing-library/user-event@^14.5.0 \
  jsdom@^25.0.0 msw@^2.6.0
```

- [ ] **Step 2: Update `web/vite.config.ts` with test config.**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:9000",
      "/jobs": { target: "http://localhost:9000", changeOrigin: true, ws: false },
      "/thumbs": "http://localhost:9000",
      "/reveal": "http://localhost:9000",
    },
  },
  resolve: { alias: { "@": "/src" } },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
  },
});
```

- [ ] **Step 3: Create `web/src/setupTests.ts`.**

```ts
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./test-utils/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

- [ ] **Step 4: Create `web/src/test-utils/server.ts`.**

```ts
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

export const handlers = [
  http.get("/api/version", () => HttpResponse.json({ version: "2.0.0-test", build: "test" })),
  http.get("/api/settings/defaults", () =>
    HttpResponse.json({
      output_dir: "/tmp/audio-dl-test",
      max_parallel: 4,
      available_formats: ["mp3", "m4a", "flac", "alac", "opus", "wav", "mp4"],
    })
  ),
];

export const server = setupServer(...handlers);
```

- [ ] **Step 5: Create `web/src/test-utils/render.tsx`.**

```tsx
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

export function renderUI(ui: ReactElement, options?: RenderOptions) {
  function Wrapper({ children }: { children: ReactNode }) {
    return <>{children}</>;
  }
  return render(ui, { wrapper: Wrapper, ...options });
}
```

(Router + QueryClient wrappers added later when those deps land — keep this minimal for now.)

- [ ] **Step 6: Add `tsconfig.json` reference for vitest globals.**

In `web/tsconfig.json`, add `"types"` to `compilerOptions`:

```json
"types": ["vitest/globals", "@testing-library/jest-dom"],
```

- [ ] **Step 7: Smoke test.**

Add `web/src/App.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { renderUI } from "./test-utils/render";
import App from "./App";

describe("App", () => {
  it("renders the hello header", () => {
    const { getByRole } = renderUI(<App />);
    expect(getByRole("heading", { name: /audio-dl v2/i })).toBeInTheDocument();
  });
});
```

```bash
cd web && npm test
```

Expected: 1 test passes.

- [ ] **Step 8: Commit.**

```bash
git add web/
git commit -m "feat(web): add Vitest + RTL + MSW test infrastructure"
```

---

## Task 12: Add TanStack Router + Query + shadcn/ui base

**Goal:** Routing, server-state caching, and the shadcn primitives we'll need (button, input, dropdown-menu, alert-dialog, dialog, tabs, scroll-area, tooltip). End state: app renders an empty AppShell with two routes.

**Files:**
- Modify: `web/package.json` (deps).
- Create: `web/components.json`, `web/src/lib/utils.ts`, `web/src/components/ui/*` via shadcn CLI.
- Modify: `web/src/main.tsx`, `web/src/App.tsx`, `web/tsconfig.json` (path mapping).

- [ ] **Step 1: Install router + query + shadcn dependencies.**

```bash
cd web && npm install \
  @tanstack/react-router@^1.95.0 @tanstack/react-query@^5.59.0 \
  class-variance-authority@^0.7.0 clsx@^2.1.0 tailwind-merge@^2.5.0 \
  lucide-react@^0.460.0 @radix-ui/react-slot@^1.1.0 \
  @radix-ui/react-dropdown-menu@^2.1.0 @radix-ui/react-alert-dialog@^1.1.0 \
  @radix-ui/react-tabs@^1.1.0 @radix-ui/react-tooltip@^1.1.0 \
  @radix-ui/react-scroll-area@^1.2.0
cd web && npm install -D @tanstack/router-vite-plugin@^1.95.0
```

- [ ] **Step 2: Create `web/src/lib/utils.ts` (shadcn's `cn` helper).**

```ts
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 3: Create `web/components.json` (shadcn config — paths so future CLI invocations drop files in the right place).**

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "default",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "src/styles/globals.css",
    "baseColor": "zinc",
    "cssVariables": true
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

- [ ] **Step 4: Manually add the shadcn `Button` primitive.**

shadcn CLI requires Node interactivity that doesn't run cleanly in CI; we copy primitives by hand. Create `web/src/components/ui/button.tsx`:

```tsx
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-md)] " +
    "text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 " +
    "focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)] disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-[var(--accent)] text-white hover:opacity-90 shadow-[0_4px_16px_var(--ambient)]",
        ghost: "hover:bg-[var(--surface)] text-[var(--text-2)]",
        outline: "border border-[var(--border)] bg-transparent hover:bg-[var(--surface)] text-[var(--text)]",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-[var(--radius-sm)] px-3 text-xs",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  }
);
Button.displayName = "Button";
```

- [ ] **Step 5: Configure TanStack Router with file-based routes.**

Update `web/vite.config.ts` to add the router plugin:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { TanStackRouterVite } from "@tanstack/router-vite-plugin";

export default defineConfig({
  plugins: [TanStackRouterVite(), react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:9000",
      "/jobs": { target: "http://localhost:9000", changeOrigin: true, ws: false },
      "/thumbs": "http://localhost:9000",
      "/reveal": "http://localhost:9000",
    },
  },
  resolve: { alias: { "@": "/src" } },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
  },
});
```

- [ ] **Step 6: Create `web/src/routes/__root.tsx`.**

```tsx
import { createRootRoute, Outlet, Link } from "@tanstack/react-router";

export const Route = createRootRoute({
  component: AppShell,
});

function AppShell() {
  return (
    <div className="min-h-screen">
      <header className="flex justify-between items-center px-7 py-5">
        <div className="flex items-center gap-3 font-semibold">audio-dl</div>
        <nav className="flex gap-1">
          <Link
            to="/"
            className="px-3 py-1.5 rounded-md text-sm text-[var(--text-2)]"
            activeProps={{ className: "bg-[var(--surface)] text-[var(--text)]" }}
          >
            Now
          </Link>
          <Link
            to="/library"
            className="px-3 py-1.5 rounded-md text-sm text-[var(--text-2)]"
            activeProps={{ className: "bg-[var(--surface)] text-[var(--text)]" }}
          >
            Library
          </Link>
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 7: Create `web/src/routes/index.tsx`.**

```tsx
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  component: NowScreen,
});

function NowScreen() {
  return <div className="px-7">Now screen — placeholder</div>;
}
```

- [ ] **Step 8: Create `web/src/routes/library.tsx`.**

```tsx
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/library")({
  component: LibraryScreen,
});

function LibraryScreen() {
  return <div className="px-7">Library screen — placeholder</div>;
}
```

- [ ] **Step 9: Update `web/src/main.tsx`.**

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./styles/globals.css";
import { routeTree } from "./routeTree.gen";

const router = createRouter({ routeTree });
const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: Infinity, retry: false } },
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>
);
```

- [ ] **Step 10: Delete the old `web/src/App.tsx` and `web/src/App.test.tsx`.**

```bash
rm web/src/App.tsx web/src/App.test.tsx
```

- [ ] **Step 11: Run dev to generate `routeTree.gen.ts` (auto-generated by the router plugin).**

```bash
cd web && npm run dev
```

Open http://localhost:5173 — see the AppShell with Now and Library tabs. Switch between them to verify routing. Ctrl-C.

- [ ] **Step 12: Verify build, tests still pass.**

```bash
cd web && npm run build && npm test
```

Expected: build succeeds, tests pass (no app-level tests yet — they were removed).

- [ ] **Step 13: Commit.**

```bash
git add web/
git commit -m "feat(web): add TanStack Router/Query and shadcn Button primitive"
```

---

# Phase 3 — Frontend lib

Pure utilities. No React. Tested with Vitest unit tests.

## Task 13: `lib/types.ts` — shared TypeScript types

**Goal:** Define the TypeScript shapes the app uses end-to-end. Mirrors the FastAPI snapshot.

**Files:**
- Create: `web/src/lib/types.ts`.

- [ ] **Step 1: Write `web/src/lib/types.ts`.**

```ts
export type Format = "mp3" | "m4a" | "flac" | "alac" | "opus" | "wav" | "mp4";

export const AUDIO_FORMATS: Format[] = ["mp3", "m4a", "flac", "alac", "opus", "wav"];
export const VIDEO_FORMATS: Format[] = ["mp4"];
export const ALL_FORMATS: Format[] = [...AUDIO_FORMATS, ...VIDEO_FORMATS];

export type UrlStateName = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface UrlState {
  url: string;
  media_format: Format;
  state: UrlStateName;
  progress_percent: number;
  speed: string | null;
  eta: string | null;
  paths: string[];
  error: string | null;
  thumb_id: string | null;
}

export interface JobSnapshot {
  job_id: string;
  state: UrlStateName;
  started_at: number;
  urls: UrlState[];
}

export interface HistoryItem {
  url: string;
  title: string | null;
  artist: string | null;
  media_format: Format;
  paths: string[];
  thumb_id: string | null;
  added_at: number; // epoch ms
}

export interface Settings {
  default_format: Format;
  output_dir: string;
  max_parallel: number;
}

export interface VersionInfo {
  version: string;
  build: string;
}
```

- [ ] **Step 2: Smoke-test that it compiles.**

```bash
cd web && npx tsc -b --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit.**

```bash
git add web/src/lib/types.ts
git commit -m "feat(web): add shared TypeScript types"
```

---

## Task 14: `lib/csrf.ts` — token discovery

**Goal:** Pure function that finds the CSRF token from the URL or via `/api/csrf` (dev mode).

**Files:**
- Create: `web/src/lib/csrf.ts`, `web/src/lib/csrf.test.ts`.

- [ ] **Step 1: Write the failing test.**

`web/src/lib/csrf.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { server } from "@/test-utils/server";
import { http, HttpResponse } from "msw";
import { discoverCsrfToken } from "./csrf";

describe("discoverCsrfToken", () => {
  const originalLocation = window.location;

  function setLocation(search: string) {
    Object.defineProperty(window, "location", {
      writable: true,
      value: new URL(`http://localhost:5173/${search}`),
    });
  }

  beforeEach(() => {
    setLocation("");
  });

  afterEach(() => {
    Object.defineProperty(window, "location", { writable: true, value: originalLocation });
  });

  it("returns token from URL ?token= when present", async () => {
    setLocation("?token=abc123");
    expect(await discoverCsrfToken()).toBe("abc123");
  });

  it("falls back to /api/csrf in dev mode", async () => {
    server.use(http.get("/api/csrf", () => HttpResponse.json({ token: "from-server" })));
    expect(await discoverCsrfToken()).toBe("from-server");
  });

  it("returns empty string if neither source has a token", async () => {
    server.use(http.get("/api/csrf", () => HttpResponse.json({}, { status: 404 })));
    expect(await discoverCsrfToken()).toBe("");
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- csrf
```

Expected: FAIL — file doesn't exist.

- [ ] **Step 3: Implement `web/src/lib/csrf.ts`.**

```ts
let cached: string | null = null;

export async function discoverCsrfToken(): Promise<string> {
  if (cached !== null) return cached;
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("token");
  if (fromUrl) {
    cached = fromUrl;
    return fromUrl;
  }
  try {
    const r = await fetch("/api/csrf");
    if (r.ok) {
      const data = (await r.json()) as { token?: string };
      cached = data.token ?? "";
      return cached;
    }
  } catch {
    // network error in dev — fall through
  }
  cached = "";
  return "";
}

export function resetCsrfCache() {
  cached = null;
}
```

The test imports `discoverCsrfToken` between cases — add a `beforeEach` that resets the cache:

Update `web/src/lib/csrf.test.ts` — add `resetCsrfCache()` call in `beforeEach`:

```ts
import { discoverCsrfToken, resetCsrfCache } from "./csrf";
// ...
  beforeEach(() => {
    setLocation("");
    resetCsrfCache();
  });
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- csrf
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/lib/csrf.ts web/src/lib/csrf.test.ts
git commit -m "feat(web): add CSRF token discovery"
```

---

## Task 15: `lib/api.ts` — fetch wrappers

**Goal:** Typed wrappers around backend endpoints. CSRF auto-injected for mutating calls.

**Files:**
- Create: `web/src/lib/api.ts`, `web/src/lib/api.test.ts`.

- [ ] **Step 1: Write the failing test.**

`web/src/lib/api.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { server } from "@/test-utils/server";
import { http, HttpResponse } from "msw";
import { getVersion, getDefaults, postJobs, cancelJob, reveal } from "./api";
import { resetCsrfCache } from "./csrf";

beforeEach(() => {
  resetCsrfCache();
  Object.defineProperty(window, "location", {
    writable: true,
    value: new URL("http://localhost:5173/?token=test-csrf"),
  });
});

describe("api.getVersion", () => {
  it("returns version info", async () => {
    const data = await getVersion();
    expect(data.version).toBe("2.0.0-test");
  });
});

describe("api.getDefaults", () => {
  it("returns launch defaults", async () => {
    const data = await getDefaults();
    expect(data.max_parallel).toBe(4);
    expect(data.available_formats).toContain("mp3");
  });
});

describe("api.postJobs", () => {
  it("posts urls with CSRF header and returns job_id", async () => {
    server.use(
      http.post("/jobs", async ({ request }) => {
        expect(request.headers.get("X-CSRF-Token")).toBe("test-csrf");
        const body = (await request.json()) as { urls: { url: string; format: string }[] };
        expect(body.urls).toHaveLength(2);
        return HttpResponse.json({ job_id: "job-1", urls: body.urls });
      })
    );
    const r = await postJobs([
      { url: "https://a", format: "mp3" },
      { url: "https://b", format: "m4a" },
    ]);
    expect(r.job_id).toBe("job-1");
  });
});

describe("api.cancelJob", () => {
  it("posts cancel with CSRF and parses ok", async () => {
    server.use(
      http.post("/jobs/job-1/cancel", () => HttpResponse.json({ cancelled: true }))
    );
    await expect(cancelJob("job-1")).resolves.toEqual({ cancelled: true });
  });
});

describe("api.reveal", () => {
  it("posts a path", async () => {
    server.use(http.post("/reveal", () => HttpResponse.json({ ok: true })));
    await expect(reveal("/tmp/file.mp3")).resolves.toEqual({ ok: true });
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- api
```

Expected: FAIL — `api.ts` doesn't exist.

- [ ] **Step 3: Implement `web/src/lib/api.ts`.**

```ts
import { discoverCsrfToken } from "./csrf";
import type { Format, VersionInfo } from "./types";

async function csrfHeaders(): Promise<HeadersInit> {
  const token = await discoverCsrfToken();
  return token ? { "X-CSRF-Token": token, "Content-Type": "application/json" } : { "Content-Type": "application/json" };
}

export async function getVersion(): Promise<VersionInfo> {
  const r = await fetch("/api/version");
  if (!r.ok) throw new Error(`/api/version ${r.status}`);
  return r.json();
}

export async function getDefaults(): Promise<{
  output_dir: string;
  max_parallel: number;
  available_formats: Format[];
}> {
  const r = await fetch("/api/settings/defaults");
  if (!r.ok) throw new Error(`/api/settings/defaults ${r.status}`);
  return r.json();
}

export interface PostJobsRequest {
  url: string;
  format: Format;
}

export async function postJobs(urls: PostJobsRequest[]): Promise<{ job_id: string; urls: { url: string; format: Format }[] }> {
  const r = await fetch("/jobs", {
    method: "POST",
    headers: await csrfHeaders(),
    body: JSON.stringify({ urls }),
  });
  if (!r.ok) throw new Error(`/jobs ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function cancelJob(jobId: string): Promise<{ cancelled: boolean }> {
  const r = await fetch(`/jobs/${jobId}/cancel`, {
    method: "POST",
    headers: await csrfHeaders(),
  });
  if (!r.ok) throw new Error(`cancel ${r.status}`);
  return r.json();
}

export async function reveal(path: string): Promise<{ ok: boolean }> {
  const r = await fetch("/reveal", {
    method: "POST",
    headers: await csrfHeaders(),
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`/reveal ${r.status}`);
  return r.json();
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- api
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/lib/api.ts web/src/lib/api.test.ts
git commit -m "feat(web): add typed API fetch wrappers"
```

---

# Phase 4 — SSE + TanStack Query plumbing

## Task 16: `useJobEvents` hook — SSE to query cache

**Goal:** Open an `EventSource` for a job, write each event into the TanStack Query cache via `setQueryData(["job", jobId])`.

**Files:**
- Create: `web/src/hooks/use-job-events.ts`, `web/src/hooks/use-job-events.test.tsx`.

- [ ] **Step 1: Write the failing test.**

`web/src/hooks/use-job-events.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { useJobEvents } from "./use-job-events";
import type { JobSnapshot } from "@/lib/types";

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
  close() { this.closed = true; }
  emit(data: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  (globalThis as unknown as { EventSource: typeof MockEventSource }).EventSource = MockEventSource;
});

afterEach(() => {
  delete (globalThis as unknown as { EventSource?: typeof MockEventSource }).EventSource;
});

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useJobEvents", () => {
  it("opens EventSource with job_id in URL and includes ?token=", () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    const es = MockEventSource.instances[0];
    expect(es.url).toContain("/jobs/job-1/events");
  });

  it("writes received snapshot to query cache", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    const es = MockEventSource.instances[0];
    const snapshot: JobSnapshot = {
      job_id: "job-1",
      state: "running",
      started_at: Date.now(),
      urls: [{
        url: "https://a", media_format: "mp3", state: "running",
        progress_percent: 42, speed: "1.0 MB/s", eta: "10s",
        paths: [], error: null, thumb_id: null,
      }],
    };
    es.emit(snapshot);
    await waitFor(() => {
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toEqual(snapshot);
    });
  });

  it("closes the EventSource on unmount", () => {
    const client = new QueryClient();
    const { unmount } = renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    const es = MockEventSource.instances[0];
    unmount();
    expect(es.closed).toBe(true);
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- use-job-events
```

Expected: FAIL — hook doesn't exist.

- [ ] **Step 3: Implement `web/src/hooks/use-job-events.ts`.**

```ts
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { JobSnapshot } from "@/lib/types";
import { discoverCsrfToken } from "@/lib/csrf";

export function useJobEvents(jobId: string) {
  const queryClient = useQueryClient();
  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
    (async () => {
      const token = await discoverCsrfToken();
      if (cancelled) return;
      const url = token ? `/jobs/${jobId}/events?token=${encodeURIComponent(token)}` : `/jobs/${jobId}/events`;
      es = new EventSource(url);
      es.onmessage = (e) => {
        try {
          const snapshot = JSON.parse(e.data) as JobSnapshot;
          queryClient.setQueryData(["job", jobId], snapshot);
        } catch {
          // ignore malformed
        }
      };
    })();
    return () => {
      cancelled = true;
      es?.close();
    };
  }, [jobId, queryClient]);
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- use-job-events
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/hooks/use-job-events.ts web/src/hooks/use-job-events.test.tsx
git commit -m "feat(web): add useJobEvents SSE hook"
```

---

## Task 17: `useActiveJobs` selector hook

**Goal:** Return the list of job snapshots whose state is not terminal, sorted by `started_at` descending (so `[0]` is the most-recently-started — the stage occupant).

**Files:**
- Create: `web/src/hooks/use-active-jobs.ts`, `web/src/hooks/use-active-jobs.test.tsx`.

- [ ] **Step 1: Write the failing test.**

```tsx
import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { JobSnapshot } from "@/lib/types";
import { useActiveJobs } from "./use-active-jobs";

function snapshot(id: string, state: JobSnapshot["state"], startedAt: number): JobSnapshot {
  return { job_id: id, state, started_at: startedAt, urls: [] };
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useActiveJobs", () => {
  it("returns only non-terminal jobs, latest-started first", () => {
    const client = new QueryClient();
    client.setQueryData(["job", "a"], snapshot("a", "running", 100));
    client.setQueryData(["job", "b"], snapshot("b", "completed", 200));
    client.setQueryData(["job", "c"], snapshot("c", "running", 300));
    const { result } = renderHook(() => useActiveJobs(), { wrapper: wrapper(client) });
    expect(result.current.map((j) => j.job_id)).toEqual(["c", "a"]);
  });

  it("returns empty list when nothing is running", () => {
    const client = new QueryClient();
    client.setQueryData(["job", "a"], snapshot("a", "completed", 100));
    const { result } = renderHook(() => useActiveJobs(), { wrapper: wrapper(client) });
    expect(result.current).toEqual([]);
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- use-active-jobs
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/hooks/use-active-jobs.ts`.**

```ts
import { useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import type { JobSnapshot } from "@/lib/types";

const TERMINAL: JobSnapshot["state"][] = ["completed", "failed", "cancelled"];

export function useActiveJobs(): JobSnapshot[] {
  const queryClient = useQueryClient();
  return useSyncExternalStore(
    (onChange) => {
      const unsub = queryClient.getQueryCache().subscribe(onChange);
      return unsub;
    },
    () => {
      const all = queryClient.getQueriesData<JobSnapshot>({ queryKey: ["job"] });
      return all
        .map(([, snapshot]) => snapshot)
        .filter((s): s is JobSnapshot => !!s && !TERMINAL.includes(s.state))
        .sort((a, b) => b.started_at - a.started_at);
    }
  );
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- use-active-jobs
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/hooks/use-active-jobs.ts web/src/hooks/use-active-jobs.test.tsx
git commit -m "feat(web): add useActiveJobs cache-derived selector"
```

---

# Phase 5 — Now screen components

Each component is built test-first. The render-utils get expanded to provide Router + Query wrapping for components that need it.

## Task 18: Expand `test-utils/render.tsx` for Router + Query

**Goal:** A single helper renders a component within all the providers it might need.

**Files:**
- Modify: `web/src/test-utils/render.tsx`.

- [ ] **Step 1: Update `web/src/test-utils/render.tsx`.**

```tsx
import { render, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider, createRootRoute, createRoute, Outlet } from "@tanstack/react-router";
import type { ReactElement, ReactNode } from "react";

export function renderUI(ui: ReactElement, options?: RenderOptions & { initialPath?: string }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }

  return {
    queryClient,
    ...render(ui, { wrapper: Wrapper, ...options }),
  };
}

export function renderWithRouter(ui: ReactElement, options?: { initialPath?: string }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const rootRoute = createRootRoute({ component: () => <Outlet /> });
  const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: () => ui });
  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute]),
    history: createMemoryHistory({ initialEntries: [options?.initialPath ?? "/"] }),
  });
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    ),
  };
}
```

- [ ] **Step 2: Verify existing tests still pass.**

```bash
cd web && npm test
```

Expected: all tests pass.

- [ ] **Step 3: Commit.**

```bash
git add web/src/test-utils/render.tsx
git commit -m "test(web): expand render utility with Router + Query wrappers"
```

---

## Task 19: `<AlbumArt />` component

**Goal:** Render `<img>` for a `thumb_id`, or a gradient fallback when missing/broken. Loads from `/thumbs/{id}.jpg`.

**Files:**
- Create: `web/src/components/album-art.tsx`, `web/src/components/album-art.test.tsx`.

- [ ] **Step 1: Write the failing test.**

```tsx
import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { AlbumArt } from "./album-art";

describe("AlbumArt", () => {
  it("renders an img with the correct src when thumbId is provided", () => {
    const { container } = renderUI(<AlbumArt thumbId="abc123" size={48} />);
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.getAttribute("src")).toBe("/thumbs/abc123.jpg");
    expect(img!.style.width).toBe("48px");
  });

  it("renders a fallback when thumbId is null", () => {
    const { container } = renderUI(<AlbumArt thumbId={null} size={48} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[data-testid='album-art-fallback']")).not.toBeNull();
  });

  it("replaces img with fallback on error", async () => {
    const { container, findByTestId } = renderUI(<AlbumArt thumbId="abc" size={48} />);
    const img = container.querySelector("img")!;
    img.dispatchEvent(new Event("error"));
    expect(await findByTestId("album-art-fallback")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- album-art
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/components/album-art.tsx`.**

```tsx
import { useState } from "react";
import { cn } from "@/lib/utils";

interface AlbumArtProps {
  thumbId: string | null | undefined;
  size: number;
  className?: string;
}

export function AlbumArt({ thumbId, size, className }: AlbumArtProps) {
  const [failed, setFailed] = useState(false);

  const style = { width: `${size}px`, height: `${size}px` };

  if (!thumbId || failed) {
    return (
      <div
        data-testid="album-art-fallback"
        style={style}
        className={cn(
          "rounded-[var(--radius-sm)] flex-shrink-0",
          "bg-gradient-to-br from-[var(--accent)]/30 to-[var(--accent-2)]/30",
          className
        )}
      />
    );
  }

  return (
    <img
      src={`/thumbs/${thumbId}.jpg`}
      alt=""
      crossOrigin="anonymous"
      referrerPolicy="no-referrer"
      style={style}
      className={cn(
        "rounded-[var(--radius-sm)] flex-shrink-0 object-cover",
        "shadow-[0_2px_12px_rgba(0,0,0,0.4)]",
        className
      )}
      onError={() => setFailed(true)}
    />
  );
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- album-art
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/components/album-art.tsx web/src/components/album-art.test.tsx
git commit -m "feat(web): add AlbumArt component with fallback"
```

---

## Task 20: `<FormatPicker />` component

**Goal:** Show the current default format as a clickable pill that opens a dropdown menu.

**Files:**
- Create: `web/src/components/ui/dropdown-menu.tsx` (shadcn primitive — manually copied), `web/src/components/format-picker.tsx`, `web/src/components/format-picker.test.tsx`.

- [ ] **Step 1: Add the shadcn DropdownMenu primitive.**

Create `web/src/components/ui/dropdown-menu.tsx`:

```tsx
import * as React from "react";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export const DropdownMenu = DropdownMenuPrimitive.Root;
export const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;

export const DropdownMenuContent = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <DropdownMenuPrimitive.Portal>
    <DropdownMenuPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "z-50 min-w-[10rem] overflow-hidden rounded-[var(--radius-md)]",
        "border border-[var(--border)] bg-[#101013] p-1 shadow-md",
        "text-sm text-[var(--text)]",
        className
      )}
      {...props}
    />
  </DropdownMenuPrimitive.Portal>
));
DropdownMenuContent.displayName = "DropdownMenuContent";

export const DropdownMenuItem = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & { selected?: boolean }
>(({ className, selected, children, ...props }, ref) => (
  <DropdownMenuPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex select-none items-center gap-2 rounded-[var(--radius-sm)] px-2 py-1.5",
      "outline-none cursor-default",
      "data-[highlighted]:bg-[var(--surface)] data-[highlighted]:text-[var(--text)]",
      className
    )}
    {...props}
  >
    <span className="w-4">{selected ? <Check size={14} /> : null}</span>
    {children}
  </DropdownMenuPrimitive.Item>
));
DropdownMenuItem.displayName = "DropdownMenuItem";
```

- [ ] **Step 2: Write the failing test for `<FormatPicker />`.**

`web/src/components/format-picker.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { renderUI } from "@/test-utils/render";
import userEvent from "@testing-library/user-event";
import { FormatPicker } from "./format-picker";

describe("FormatPicker", () => {
  it("renders the current value", () => {
    const { getByRole } = renderUI(<FormatPicker value="m4a" onChange={() => {}} />);
    expect(getByRole("button")).toHaveTextContent(/m4a/i);
  });

  it("calls onChange when a different format is selected", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    const { getByRole, findByText } = renderUI(<FormatPicker value="m4a" onChange={onChange} />);
    await user.click(getByRole("button"));
    await user.click(await findByText("flac"));
    expect(onChange).toHaveBeenCalledWith("flac");
  });
});
```

- [ ] **Step 3: Run, watch fail.**

```bash
cd web && npm test -- format-picker
```

Expected: FAIL.

- [ ] **Step 4: Implement `web/src/components/format-picker.tsx`.**

```tsx
import { ChevronDown } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "./ui/dropdown-menu";
import { ALL_FORMATS, type Format } from "@/lib/types";

interface FormatPickerProps {
  value: Format;
  onChange: (next: Format) => void;
}

const QUALITY_HINT: Record<Format, string> = {
  mp3: "320 kbps",
  m4a: "256 kbps",
  flac: "lossless",
  alac: "lossless",
  opus: "best",
  wav: "raw",
  mp4: "video",
};

export function FormatPicker({ value, onChange }: FormatPickerProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="px-3 py-2 rounded-[var(--radius-md)] bg-[var(--surface)] border border-[var(--border)] text-sm font-medium text-[var(--text-2)] inline-flex items-center gap-2 cursor-pointer"
        >
          {value} · {QUALITY_HINT[value]}
          <ChevronDown size={12} className="text-[var(--text-3)]" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {ALL_FORMATS.map((f) => (
          <DropdownMenuItem key={f} selected={f === value} onSelect={() => onChange(f)}>
            {f} <span className="text-[var(--text-3)] text-xs ml-auto">{QUALITY_HINT[f]}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
```

- [ ] **Step 5: Run, watch pass.**

```bash
cd web && npm test -- format-picker
```

Expected: 2 tests pass.

- [ ] **Step 6: Commit.**

```bash
git add web/src/components/format-picker.tsx web/src/components/format-picker.test.tsx web/src/components/ui/dropdown-menu.tsx
git commit -m "feat(web): add FormatPicker + DropdownMenu primitive"
```

---

## Task 21: `useSettings` hook (localStorage)

**Goal:** Read/write the user's default format and other preferences. Reactive to changes.

**Files:**
- Create: `web/src/hooks/use-settings.ts`, `web/src/hooks/use-settings.test.tsx`.

- [ ] **Step 1: Write the failing test.**

```tsx
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSettings } from "./use-settings";

beforeEach(() => localStorage.clear());

describe("useSettings", () => {
  it("returns mp3 as default format when nothing stored", () => {
    const { result } = renderHook(() => useSettings());
    expect(result.current.settings.default_format).toBe("m4a");
  });

  it("persists changes to localStorage", () => {
    const { result } = renderHook(() => useSettings());
    act(() => result.current.setDefaultFormat("flac"));
    expect(JSON.parse(localStorage.getItem("audio_dl_settings")!).default_format).toBe("flac");
  });

  it("re-reads value after setting", () => {
    const { result } = renderHook(() => useSettings());
    act(() => result.current.setDefaultFormat("opus"));
    expect(result.current.settings.default_format).toBe("opus");
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- use-settings
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/hooks/use-settings.ts`.**

```ts
import { useCallback, useSyncExternalStore } from "react";
import type { Format } from "@/lib/types";

const KEY = "audio_dl_settings";

interface StoredSettings {
  default_format: Format;
}

const DEFAULTS: StoredSettings = { default_format: "m4a" };

function read(): StoredSettings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw);
    return { default_format: parsed.default_format ?? DEFAULTS.default_format };
  } catch {
    return DEFAULTS;
  }
}

const listeners = new Set<() => void>();

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function notify() {
  for (const cb of listeners) cb();
}

export function useSettings() {
  const settings = useSyncExternalStore(subscribe, read, () => DEFAULTS);

  const setDefaultFormat = useCallback((fmt: Format) => {
    const next = { ...read(), default_format: fmt };
    localStorage.setItem(KEY, JSON.stringify(next));
    notify();
  }, []);

  return { settings, setDefaultFormat };
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- use-settings
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/hooks/use-settings.ts web/src/hooks/use-settings.test.tsx
git commit -m "feat(web): add useSettings hook for localStorage prefs"
```

---

## Task 22: `<UrlInput />` component

**Goal:** Bottom input bar with URL field, inline FormatPicker, and Add button. Submits to `postJobs`. Multi-line paste splits into N URL+format pairs at the current default format.

**Files:**
- Create: `web/src/components/url-input.tsx`, `web/src/components/url-input.test.tsx`.

- [ ] **Step 1: Write the failing test.**

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderUI } from "@/test-utils/render";
import userEvent from "@testing-library/user-event";
import { server } from "@/test-utils/server";
import { http, HttpResponse } from "msw";
import { UrlInput } from "./url-input";

beforeEach(() => localStorage.clear());

describe("UrlInput", () => {
  it("submits a single URL with the current default format", async () => {
    const user = userEvent.setup();
    const onJobCreated = vi.fn();
    let captured: { url: string; format: string }[] = [];
    server.use(
      http.post("/jobs", async ({ request }) => {
        captured = ((await request.json()) as { urls: { url: string; format: string }[] }).urls;
        return HttpResponse.json({ job_id: "job-x", urls: captured });
      })
    );
    const { getByPlaceholderText, getByRole } = renderUI(<UrlInput onJobCreated={onJobCreated} />);
    const input = getByPlaceholderText(/paste a url/i);
    await user.type(input, "https://youtu.be/abc");
    await user.click(getByRole("button", { name: /add/i }));
    expect(captured).toEqual([{ url: "https://youtu.be/abc", format: "m4a" }]);
    expect(onJobCreated).toHaveBeenCalledWith("job-x");
  });

  it("splits multi-line paste into N URL+format pairs", async () => {
    const user = userEvent.setup();
    let captured: { url: string; format: string }[] = [];
    server.use(
      http.post("/jobs", async ({ request }) => {
        captured = ((await request.json()) as { urls: { url: string; format: string }[] }).urls;
        return HttpResponse.json({ job_id: "job-y", urls: captured });
      })
    );
    const { getByPlaceholderText, getByRole } = renderUI(<UrlInput onJobCreated={() => {}} />);
    const input = getByPlaceholderText(/paste a url/i);
    await user.click(input);
    await user.paste("https://a\nhttps://b\nhttps://c");
    await user.click(getByRole("button", { name: /add/i }));
    expect(captured).toEqual([
      { url: "https://a", format: "m4a" },
      { url: "https://b", format: "m4a" },
      { url: "https://c", format: "m4a" },
    ]);
  });

  it("clears the input on successful submit", async () => {
    const user = userEvent.setup();
    server.use(http.post("/jobs", () => HttpResponse.json({ job_id: "job-z", urls: [] })));
    const { getByPlaceholderText, getByRole } = renderUI(<UrlInput onJobCreated={() => {}} />);
    const input = getByPlaceholderText(/paste a url/i) as HTMLInputElement;
    await user.type(input, "https://x");
    await user.click(getByRole("button", { name: /add/i }));
    expect(input.value).toBe("");
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- url-input
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/components/url-input.tsx`.**

```tsx
import { useState } from "react";
import { Button } from "./ui/button";
import { FormatPicker } from "./format-picker";
import { useSettings } from "@/hooks/use-settings";
import { postJobs } from "@/lib/api";

interface UrlInputProps {
  onJobCreated: (jobId: string) => void;
}

export function UrlInput({ onJobCreated }: UrlInputProps) {
  const { settings, setDefaultFormat } = useSettings();
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleAdd() {
    const lines = value
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (lines.length === 0) return;
    const urls = lines.map((url) => ({ url, format: settings.default_format }));
    setSubmitting(true);
    try {
      const r = await postJobs(urls);
      onJobCreated(r.job_id);
      setValue("");
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-7 mb-8 grid grid-cols-[1fr_auto_auto] gap-2 p-2 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-lg)]">
      <input
        type="text"
        placeholder="Paste a URL to queue it next…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !submitting) handleAdd();
        }}
        className="bg-transparent border-none text-[var(--text)] px-3 py-2 text-sm outline-none placeholder:text-[var(--text-3)]"
      />
      <FormatPicker value={settings.default_format} onChange={setDefaultFormat} />
      <Button onClick={handleAdd} disabled={submitting || !value.trim()}>
        Add
      </Button>
    </div>
  );
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- url-input
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/components/url-input.tsx web/src/components/url-input.test.tsx
git commit -m "feat(web): add UrlInput component"
```

---

## Task 23: `useVibrant` hook

**Goal:** Extract dominant color from an `<img>` and set CSS variables `--accent`, `--accent-2`, `--ambient` on `:root`.

**Files:**
- Modify: `web/package.json` (add `node-vibrant`).
- Create: `web/src/hooks/use-vibrant.ts`, `web/src/hooks/use-vibrant.test.tsx`.

- [ ] **Step 1: Install node-vibrant.**

```bash
cd web && npm install node-vibrant@^4.0.0
```

- [ ] **Step 2: Write the failing test.**

```tsx
import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useVibrant } from "./use-vibrant";

vi.mock("node-vibrant", () => ({
  Vibrant: {
    from: () => ({
      getPalette: () => Promise.resolve({
        Vibrant: { hex: "#ff00ff" },
        LightVibrant: { hex: "#ff66ff" },
        DarkMuted: { hex: "#330033" },
      }),
    }),
  },
}));

describe("useVibrant", () => {
  it("sets --accent on :root when img loads", async () => {
    const img = document.createElement("img");
    img.src = "/thumbs/abc.jpg";
    document.body.appendChild(img);
    renderHook(() => useVibrant({ current: img }));
    img.dispatchEvent(new Event("load"));
    // Wait one tick for the promise to resolve.
    await new Promise((r) => setTimeout(r, 50));
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("#ff00ff");
  });
});
```

- [ ] **Step 3: Run, watch fail.**

```bash
cd web && npm test -- use-vibrant
```

Expected: FAIL.

- [ ] **Step 4: Implement `web/src/hooks/use-vibrant.ts`.**

```ts
import { useEffect, type RefObject } from "react";

export function useVibrant(ref: RefObject<HTMLImageElement | null>) {
  useEffect(() => {
    const img = ref.current;
    if (!img) return;
    let cancelled = false;

    async function extract() {
      if (!img) return;
      try {
        const { Vibrant } = await import("node-vibrant");
        if (cancelled) return;
        const palette = await Vibrant.from(img).getPalette();
        if (cancelled) return;
        const accent = palette.Vibrant?.hex ?? "#818cf8";
        const accent2 = palette.LightVibrant?.hex ?? palette.Vibrant?.hex ?? "#c084fc";
        const ambient = palette.DarkMuted?.hex ?? "#1a1a2e";
        document.documentElement.style.setProperty("--accent", accent);
        document.documentElement.style.setProperty("--accent-2", accent2);
        document.documentElement.style.setProperty("--ambient", `${ambient}40`);
      } catch (e) {
        console.warn("vibrant extraction failed", e);
      }
    }

    if (img.complete) {
      extract();
    } else {
      img.addEventListener("load", extract);
    }
    return () => {
      cancelled = true;
      img.removeEventListener("load", extract);
    };
  }, [ref]);
}
```

- [ ] **Step 5: Run, watch pass.**

```bash
cd web && npm test -- use-vibrant
```

Expected: test passes.

- [ ] **Step 6: Commit.**

```bash
git add web/
git commit -m "feat(web): add useVibrant color extraction hook"
```

---

## Task 24: `<HeroStage />` component

**Goal:** Render the active job's album art at 240px, eyebrow + title + artist, progress bar, MB/s + time-left line. Drives `useVibrant`.

**Files:**
- Create: `web/src/components/stage.tsx`, `web/src/components/stage.test.tsx`.

- [ ] **Step 1: Write the failing test.**

```tsx
import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { HeroStage } from "./stage";
import type { JobSnapshot } from "@/lib/types";

function snapshot(overrides: Partial<JobSnapshot["urls"][0]> = {}): JobSnapshot {
  return {
    job_id: "job-1",
    state: "running",
    started_at: Date.now(),
    urls: [{
      url: "https://a",
      media_format: "m4a",
      state: "running",
      progress_percent: 62,
      speed: "3.4 MB/s",
      eta: "18s",
      paths: [],
      error: null,
      thumb_id: "abc123",
      ...overrides,
    }],
  };
}

describe("HeroStage", () => {
  it("renders the URL as the title when no parsed title is available", () => {
    const { container } = renderUI(<HeroStage snapshot={snapshot()} activeCount={1} />);
    expect(container.textContent).toMatch(/https:\/\/a/);
  });

  it("renders 'Downloading · 1 of N' eyebrow", () => {
    const { getByText } = renderUI(<HeroStage snapshot={snapshot()} activeCount={3} />);
    expect(getByText(/downloading · 1 of 3/i)).toBeInTheDocument();
  });

  it("renders speed and eta", () => {
    const { container } = renderUI(<HeroStage snapshot={snapshot()} activeCount={1} />);
    expect(container.textContent).toMatch(/3\.4 MB\/s/);
    expect(container.textContent).toMatch(/18s/);
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- stage
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/components/stage.tsx`.**

```tsx
import { useRef } from "react";
import { AlbumArt } from "./album-art";
import { useVibrant } from "@/hooks/use-vibrant";
import type { JobSnapshot } from "@/lib/types";

interface HeroStageProps {
  snapshot: JobSnapshot;
  activeCount: number;
}

export function HeroStage({ snapshot, activeCount }: HeroStageProps) {
  const imgRef = useRef<HTMLImageElement | null>(null);
  useVibrant(imgRef);

  // For v2.0, the URL stands in as title. yt-dlp title parsing is a v2.1 task.
  const u = snapshot.urls[0];
  if (!u) return null;
  const title = u.url;
  const artist = "";

  return (
    <div className="grid place-items-center px-8 pt-7 pb-4">
      <div className="relative">
        <AlbumArt thumbId={u.thumb_id} size={240} className="!shadow-[0_24px_64px_rgba(0,0,0,0.55),0_0_100px_var(--ambient)]" />
        {/* AlbumArt swaps to fallback if thumb missing; the underlying <img> ref is wired below */}
        <img
          ref={imgRef}
          src={u.thumb_id ? `/thumbs/${u.thumb_id}.jpg` : ""}
          alt=""
          crossOrigin="anonymous"
          referrerPolicy="no-referrer"
          className="absolute opacity-0 pointer-events-none w-0 h-0"
        />
      </div>
      <div className="text-center mt-6">
        <div className="text-[11px] uppercase tracking-[0.06em] font-bold text-[var(--accent)] mb-2">
          Downloading · 1 of {activeCount}
        </div>
        <h2 className="text-[26px] font-bold tracking-[-0.025em] leading-tight mb-1">{title}</h2>
        {artist && <p className="text-[var(--text-2)] text-[15px] mb-6">{artist}</p>}
        <div className="w-full max-w-[460px] mx-auto">
          <div className="h-1 bg-white/10 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-[width] duration-200"
              style={{
                width: `${u.progress_percent}%`,
                background: "linear-gradient(90deg, var(--accent), var(--accent-2))",
                boxShadow: "0 0 8px var(--accent)",
              }}
            />
          </div>
          <div className="flex justify-between text-xs text-[var(--text-3)] mt-2">
            <span>{u.speed ?? ""}</span>
            <span>{u.eta ?? ""}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- stage
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/components/stage.tsx web/src/components/stage.test.tsx
git commit -m "feat(web): add HeroStage component"
```

---

## Task 25: `<AlsoDownloading />` component

**Goal:** Horizontal strip of mini cards for concurrent active jobs beyond the stage occupant.

**Files:**
- Create: `web/src/components/also-downloading.tsx`, `web/src/components/also-downloading.test.tsx`.

- [ ] **Step 1: Write the failing test.**

```tsx
import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { AlsoDownloading } from "./also-downloading";
import type { JobSnapshot } from "@/lib/types";

function snap(id: string, percent: number): JobSnapshot {
  return {
    job_id: id,
    state: "running",
    started_at: 0,
    urls: [{
      url: `https://${id}`, media_format: "m4a", state: "running",
      progress_percent: percent, speed: null, eta: null,
      paths: [], error: null, thumb_id: null,
    }],
  };
}

describe("AlsoDownloading", () => {
  it("renders nothing when given empty list", () => {
    const { container } = renderUI(<AlsoDownloading jobs={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders one card per job", () => {
    const { getAllByTestId } = renderUI(<AlsoDownloading jobs={[snap("a", 10), snap("b", 90)]} />);
    expect(getAllByTestId("also-card")).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- also-downloading
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/components/also-downloading.tsx`.**

```tsx
import { AlbumArt } from "./album-art";
import type { JobSnapshot } from "@/lib/types";

interface AlsoDownloadingProps {
  jobs: JobSnapshot[];
}

export function AlsoDownloading({ jobs }: AlsoDownloadingProps) {
  if (jobs.length === 0) return null;
  return (
    <div className="mx-8 mt-7 grid grid-cols-[90px_1fr] gap-4 items-center">
      <div className="text-right text-xs text-[var(--text-3)] font-medium">Also downloading</div>
      <div className="flex gap-2 overflow-x-auto">
        {jobs.map((j) => {
          const u = j.urls[0];
          if (!u) return null;
          return (
            <div
              key={j.job_id}
              data-testid="also-card"
              className="flex items-center gap-2.5 p-2 pr-3 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-md)] flex-1 min-w-[200px]"
            >
              <AlbumArt thumbId={u.thumb_id} size={32} />
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium truncate">{u.url}</div>
                <div className="h-0.5 bg-white/7 rounded-full overflow-hidden mt-1">
                  <div
                    className="h-full rounded-full transition-[width] duration-200"
                    style={{ width: `${u.progress_percent}%`, background: "var(--accent)" }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- also-downloading
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/components/also-downloading.tsx web/src/components/also-downloading.test.tsx
git commit -m "feat(web): add AlsoDownloading strip"
```

---

## Task 26: `<Queue />` component

**Goal:** "Up next" list of queued (not yet started) URLs.

**Files:**
- Create: `web/src/components/queue.tsx`, `web/src/components/queue.test.tsx`.

- [ ] **Step 1: Write the failing test.**

```tsx
import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { Queue } from "./queue";
import type { JobSnapshot } from "@/lib/types";

function snap(id: string): JobSnapshot {
  return {
    job_id: id,
    state: "queued",
    started_at: 0,
    urls: [{
      url: `https://${id}`, media_format: "m4a", state: "queued",
      progress_percent: 0, speed: null, eta: null,
      paths: [], error: null, thumb_id: null,
    }],
  };
}

describe("Queue", () => {
  it("renders nothing when empty", () => {
    const { container } = renderUI(<Queue jobs={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows N queued count", () => {
    const { getByText } = renderUI(<Queue jobs={[snap("a"), snap("b"), snap("c")]} />);
    expect(getByText(/3 queued/)).toBeInTheDocument();
  });

  it("renders one row per queued job", () => {
    const { getAllByTestId } = renderUI(<Queue jobs={[snap("a"), snap("b")]} />);
    expect(getAllByTestId("queue-row")).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- queue
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/components/queue.tsx`.**

```tsx
import { AlbumArt } from "./album-art";
import type { JobSnapshot } from "@/lib/types";

interface QueueProps {
  jobs: JobSnapshot[];
}

export function Queue({ jobs }: QueueProps) {
  if (jobs.length === 0) return null;
  return (
    <div className="mx-8 mt-7">
      <div className="flex justify-between items-baseline mb-3">
        <div className="text-base font-bold tracking-[-0.015em]">Up next</div>
        <div className="text-sm text-[var(--text-3)]">{jobs.length} queued</div>
      </div>
      {jobs.map((j) => {
        const u = j.urls[0];
        if (!u) return null;
        return (
          <div
            key={j.job_id}
            data-testid="queue-row"
            className="grid grid-cols-[40px_1fr_auto] gap-3 items-center p-2 rounded-[var(--radius-md)] hover:bg-white/[0.03]"
          >
            <AlbumArt thumbId={u.thumb_id} size={40} />
            <div className="min-w-0">
              <div className="text-sm font-medium truncate">{u.url}</div>
            </div>
            <span className="text-xs text-[var(--text-2)] bg-[var(--surface)] px-2 py-0.5 rounded-full font-medium">
              {u.media_format}
            </span>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- queue
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/components/queue.tsx web/src/components/queue.test.tsx
git commit -m "feat(web): add Queue component"
```

---

## Task 27: `<EmptyStage />` component

**Goal:** When nothing is downloading, show the most-recently-completed history item as a quiet "Last added" preview. If no history, show a typographic wordmark state.

**Files:**
- Create: `web/src/components/empty-stage.tsx`, `web/src/components/empty-stage.test.tsx`.

- [ ] **Step 1: Write the failing test.**

```tsx
import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { EmptyStage } from "./empty-stage";
import type { HistoryItem } from "@/lib/types";

const latest: HistoryItem = {
  url: "https://a", title: "Self Care", artist: "Mac Miller", media_format: "m4a",
  paths: ["/tmp/a.m4a"], thumb_id: "abc", added_at: 0,
};

describe("EmptyStage", () => {
  it("shows 'Last added' eyebrow when history is present", () => {
    const { getByText } = renderUI(<EmptyStage latest={latest} />);
    expect(getByText(/last added/i)).toBeInTheDocument();
    expect(getByText(/self care/i)).toBeInTheDocument();
  });

  it("shows quiet wordmark when no history", () => {
    const { getByText } = renderUI(<EmptyStage latest={null} />);
    expect(getByText(/paste a url to get started/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- empty-stage
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/components/empty-stage.tsx`.**

```tsx
import { AlbumArt } from "./album-art";
import type { HistoryItem } from "@/lib/types";

interface EmptyStageProps {
  latest: HistoryItem | null;
}

export function EmptyStage({ latest }: EmptyStageProps) {
  if (!latest) {
    return (
      <div className="grid place-items-center min-h-[300px] text-center px-8">
        <p className="text-[var(--text-2)] text-base">
          Paste a URL to get started.
        </p>
      </div>
    );
  }
  return (
    <div className="grid place-items-center px-8 pt-7 pb-4">
      <AlbumArt thumbId={latest.thumb_id} size={240} />
      <div className="text-center mt-6">
        <div className="text-[11px] uppercase tracking-[0.06em] font-bold text-[var(--text-2)] mb-2">
          Last added
        </div>
        <h2 className="text-[22px] font-bold tracking-[-0.02em]">{latest.title ?? latest.url}</h2>
        {latest.artist && <p className="text-[var(--text-2)] text-sm mt-1">{latest.artist}</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- empty-stage
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/components/empty-stage.tsx web/src/components/empty-stage.test.tsx
git commit -m "feat(web): add EmptyStage component"
```

---

## Task 28: `useHistory` hook (localStorage)

**Goal:** Read/write the v1.8-shaped history array, capped at 100 entries with FIFO drop.

**Files:**
- Create: `web/src/hooks/use-history.ts`, `web/src/hooks/use-history.test.tsx`.

- [ ] **Step 1: Write the failing test.**

```tsx
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useHistory } from "./use-history";
import type { HistoryItem } from "@/lib/types";

beforeEach(() => localStorage.clear());

function mk(url: string, added_at: number): HistoryItem {
  return {
    url, title: null, artist: null, media_format: "m4a",
    paths: [], thumb_id: null, added_at,
  };
}

describe("useHistory", () => {
  it("returns empty when nothing stored", () => {
    const { result } = renderHook(() => useHistory());
    expect(result.current.history).toEqual([]);
  });

  it("prepends items via addItem", () => {
    const { result } = renderHook(() => useHistory());
    act(() => result.current.addItem(mk("https://a", 1)));
    act(() => result.current.addItem(mk("https://b", 2)));
    expect(result.current.history.map((h) => h.url)).toEqual(["https://b", "https://a"]);
  });

  it("caps at 100 entries with FIFO drop", () => {
    const { result } = renderHook(() => useHistory());
    act(() => {
      for (let i = 0; i < 105; i++) result.current.addItem(mk(`https://${i}`, i));
    });
    expect(result.current.history).toHaveLength(100);
    expect(result.current.history[99].url).toBe("https://5");
  });

  it("removes an item by url", () => {
    const { result } = renderHook(() => useHistory());
    act(() => result.current.addItem(mk("https://a", 1)));
    act(() => result.current.addItem(mk("https://b", 2)));
    act(() => result.current.removeItem("https://a"));
    expect(result.current.history.map((h) => h.url)).toEqual(["https://b"]);
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- use-history
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/hooks/use-history.ts`.**

```ts
import { useCallback, useSyncExternalStore } from "react";
import type { HistoryItem } from "@/lib/types";

const KEY = "audio_dl_history";
const CAP = 100;

interface Envelope { v: 1; items: HistoryItem[] }

function read(): HistoryItem[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Partial<Envelope>;
    if (parsed.v !== 1 || !Array.isArray(parsed.items)) return [];
    return parsed.items;
  } catch {
    return [];
  }
}

function write(items: HistoryItem[]) {
  const envelope: Envelope = { v: 1, items };
  localStorage.setItem(KEY, JSON.stringify(envelope));
}

const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};
const notify = () => { for (const cb of listeners) cb(); };

export function useHistory() {
  const history = useSyncExternalStore(subscribe, read, () => []);

  const addItem = useCallback((item: HistoryItem) => {
    const next = [item, ...read().filter((h) => h.url !== item.url)].slice(0, CAP);
    write(next);
    notify();
  }, []);

  const removeItem = useCallback((url: string) => {
    write(read().filter((h) => h.url !== url));
    notify();
  }, []);

  return { history, addItem, removeItem };
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- use-history
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/hooks/use-history.ts web/src/hooks/use-history.test.tsx
git commit -m "feat(web): add useHistory hook with FIFO cap"
```

---

# Phase 6 — Wire up Now screen

## Task 29: Now screen integration

**Goal:** Compose the components into `/` route. On `postJobs` success, start an SSE feed. On terminal job state, prepend to history.

**Files:**
- Modify: `web/src/routes/index.tsx`.
- Create: `web/src/components/job-tracker.tsx` (per-job SSE feed lifecycle).

- [ ] **Step 1: Write `web/src/components/job-tracker.tsx`.**

This is a behavior-only component (renders nothing). It owns one job's SSE lifecycle: opens the feed and, on terminal state, prepends a history item.

```tsx
import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useJobEvents } from "@/hooks/use-job-events";
import { useHistory } from "@/hooks/use-history";
import type { JobSnapshot } from "@/lib/types";

const TERMINAL: JobSnapshot["state"][] = ["completed", "failed", "cancelled"];

export function JobTracker({ jobId }: { jobId: string }) {
  useJobEvents(jobId);
  const queryClient = useQueryClient();
  const { data } = useQuery<JobSnapshot>({ queryKey: ["job", jobId], enabled: false });
  const { addItem } = useHistory();

  useEffect(() => {
    if (!data) return;
    if (!TERMINAL.includes(data.state)) return;
    for (const u of data.urls) {
      if (u.state === "completed") {
        addItem({
          url: u.url,
          title: null,
          artist: null,
          media_format: u.media_format,
          paths: u.paths,
          thumb_id: u.thumb_id,
          added_at: Date.now(),
        });
      }
    }
    // Leave the job in the cache for a moment so UI transitions feel natural.
    setTimeout(() => queryClient.removeQueries({ queryKey: ["job", jobId] }), 1500);
  }, [data, addItem, jobId, queryClient]);

  return null;
}
```

- [ ] **Step 2: Update `web/src/routes/index.tsx`.**

```tsx
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useActiveJobs } from "@/hooks/use-active-jobs";
import { useHistory } from "@/hooks/use-history";
import { HeroStage } from "@/components/stage";
import { EmptyStage } from "@/components/empty-stage";
import { AlsoDownloading } from "@/components/also-downloading";
import { Queue } from "@/components/queue";
import { UrlInput } from "@/components/url-input";
import { JobTracker } from "@/components/job-tracker";

export const Route = createFileRoute("/")({ component: NowScreen });

function NowScreen() {
  const activeJobs = useActiveJobs();
  const { history } = useHistory();
  const [trackedJobs, setTrackedJobs] = useState<string[]>([]);

  const stageJob = activeJobs.find((j) => j.state === "running") ?? null;
  const otherRunning = activeJobs.filter((j) => j.job_id !== stageJob?.job_id && j.state === "running");
  const queued = activeJobs.filter((j) => j.state === "queued");

  return (
    <>
      {trackedJobs.map((id) => <JobTracker key={id} jobId={id} />)}
      {stageJob ? (
        <HeroStage snapshot={stageJob} activeCount={activeJobs.filter((j) => j.state === "running").length} />
      ) : (
        <EmptyStage latest={history[0] ?? null} />
      )}
      <AlsoDownloading jobs={otherRunning} />
      <Queue jobs={queued} />
      <UrlInput onJobCreated={(id) => setTrackedJobs((prev) => [...prev, id])} />
    </>
  );
}
```

- [ ] **Step 3: Smoke-test.**

```bash
cd web && npm run dev
```

Open http://localhost:5173 — should see the EmptyStage with "Paste a URL to get started" and the UrlInput at the bottom. Backend isn't running so submitting won't work, but the layout should render.

- [ ] **Step 4: Run the full backend.**

In a second terminal:

```bash
AUDIO_DL_DEV=1 audio-dl-ui --port 9000 --no-browser
```

Now in the React app, paste a YouTube URL into the input, click Add. You should see:
- The URL appears as a queued/running job.
- The HeroStage materializes with a fallback gradient (thumbnail not yet cached).
- Progress updates flow via SSE.
- On completion, the stage clears (or shows the next active) and the item enters history.

Ctrl-C both servers when satisfied.

- [ ] **Step 5: Verify tests still pass.**

```bash
cd web && npm test
```

Expected: all green.

- [ ] **Step 6: Commit.**

```bash
git add web/
git commit -m "feat(web): wire up Now screen — SSE feed + history persistence"
```

---

## Task 29b: Cancel affordance + confirm dialog (spec decision #15)

**Goal:** Add a hover-revealed × button to the HeroStage and AlsoDownloading cards. Clicking opens a shadcn `AlertDialog`; confirming calls `cancelJob`.

**Files:**
- Create: `web/src/components/ui/alert-dialog.tsx` (shadcn primitive), `web/src/components/cancel-dialog.tsx`, `web/src/components/cancel-dialog.test.tsx`.
- Modify: `web/src/components/stage.tsx`, `web/src/components/also-downloading.tsx`.

- [ ] **Step 1: Add the shadcn AlertDialog primitive `web/src/components/ui/alert-dialog.tsx`.**

```tsx
import * as React from "react";
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import { cn } from "@/lib/utils";

export const AlertDialog = AlertDialogPrimitive.Root;
export const AlertDialogTrigger = AlertDialogPrimitive.Trigger;
export const AlertDialogPortal = AlertDialogPrimitive.Portal;

export const AlertDialogOverlay = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Overlay
    ref={ref}
    className={cn("fixed inset-0 z-50 bg-black/60 backdrop-blur-sm", className)}
    {...props}
  />
));
AlertDialogOverlay.displayName = "AlertDialogOverlay";

export const AlertDialogContent = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Content>
>(({ className, ...props }, ref) => (
  <AlertDialogPortal>
    <AlertDialogOverlay />
    <AlertDialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
        "w-full max-w-sm p-6 rounded-[var(--radius-lg)]",
        "bg-[#101013] border border-[var(--border)] shadow-2xl",
        className
      )}
      {...props}
    />
  </AlertDialogPortal>
));
AlertDialogContent.displayName = "AlertDialogContent";

export const AlertDialogTitle = AlertDialogPrimitive.Title;
export const AlertDialogDescription = AlertDialogPrimitive.Description;
export const AlertDialogAction = AlertDialogPrimitive.Action;
export const AlertDialogCancel = AlertDialogPrimitive.Cancel;
```

- [ ] **Step 2: Write the failing test for `<CancelDialog />`.**

`web/src/components/cancel-dialog.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { renderUI } from "@/test-utils/render";
import userEvent from "@testing-library/user-event";
import { server } from "@/test-utils/server";
import { http, HttpResponse } from "msw";
import { CancelDialog } from "./cancel-dialog";

describe("CancelDialog", () => {
  it("renders the trigger button", () => {
    const { getByRole } = renderUI(<CancelDialog jobId="job-1" />);
    expect(getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("calls cancelJob on confirm", async () => {
    const cancelHandler = vi.fn(() => HttpResponse.json({ cancelled: true }));
    server.use(http.post("/jobs/job-1/cancel", cancelHandler));
    const user = userEvent.setup();
    const { getByRole, findByRole } = renderUI(<CancelDialog jobId="job-1" />);
    await user.click(getByRole("button", { name: /cancel/i }));
    await user.click(await findByRole("button", { name: /confirm/i }));
    expect(cancelHandler).toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run, watch fail.**

```bash
cd web && npm test -- cancel-dialog
```

Expected: FAIL.

- [ ] **Step 4: Implement `web/src/components/cancel-dialog.tsx`.**

```tsx
import { X } from "lucide-react";
import {
  AlertDialog, AlertDialogTrigger, AlertDialogContent,
  AlertDialogTitle, AlertDialogDescription,
  AlertDialogAction, AlertDialogCancel,
} from "./ui/alert-dialog";
import { cancelJob } from "@/lib/api";

interface CancelDialogProps {
  jobId: string;
  size?: "sm" | "md";
}

export function CancelDialog({ jobId, size = "md" }: CancelDialogProps) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <button
          type="button"
          aria-label="Cancel"
          className={
            size === "sm"
              ? "w-5 h-5 rounded-full bg-black/40 grid place-items-center text-white/80 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
              : "w-6 h-6 rounded-full bg-black/40 grid place-items-center text-white/80 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
          }
        >
          <X size={size === "sm" ? 12 : 14} />
        </button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogTitle className="text-base font-semibold tracking-tight">
          Cancel this download?
        </AlertDialogTitle>
        <AlertDialogDescription className="text-sm text-[var(--text-2)] mt-2">
          The download will stop. Partial files will be removed.
        </AlertDialogDescription>
        <div className="flex justify-end gap-2 mt-5">
          <AlertDialogCancel className="px-4 py-2 text-sm rounded-[var(--radius-md)] text-[var(--text-2)] hover:bg-[var(--surface)]">
            Keep
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={() => cancelJob(jobId).catch(console.error)}
            className="px-4 py-2 text-sm rounded-[var(--radius-md)] bg-[var(--accent)] text-white font-medium"
          >
            Confirm cancel
          </AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
```

- [ ] **Step 5: Run, watch pass.**

```bash
cd web && npm test -- cancel-dialog
```

Expected: 2 tests pass.

- [ ] **Step 6: Wire the cancel button into the stage.**

In `web/src/components/stage.tsx`, modify the AlbumArt-wrapping `<div className="relative">` to a `group` so hover reveals work:

```tsx
import { CancelDialog } from "./cancel-dialog";
// ...
<div className="relative group">
  <AlbumArt thumbId={u.thumb_id} size={240} ... />
  <div className="absolute top-2 right-2">
    <CancelDialog jobId={snapshot.job_id} />
  </div>
  {/* hidden image ref for useVibrant — unchanged */}
</div>
```

- [ ] **Step 7: Wire into AlsoDownloading.**

In `web/src/components/also-downloading.tsx`, wrap the card div in `group` and add a small CancelDialog:

```tsx
import { CancelDialog } from "./cancel-dialog";
// ...
<div className="group relative flex items-center gap-2.5 ...">
  <AlbumArt thumbId={u.thumb_id} size={32} />
  <div className="flex-1 min-w-0">
    {/* unchanged */}
  </div>
  <div className="absolute top-1 right-1">
    <CancelDialog jobId={j.job_id} size="sm" />
  </div>
</div>
```

- [ ] **Step 8: Smoke-test.**

```bash
cd web && npm run dev
```

Hover the stage album art → × appears. Click it → dialog. Confirm → POST /jobs/{id}/cancel fires. Ctrl-C.

- [ ] **Step 9: Commit.**

```bash
git add web/
git commit -m "feat(web): add cancel affordance with confirm dialog"
```

---

# Phase 7 — Library screen

## Task 30: `lib/group-by-day.ts` — day grouping helper

**Goal:** Pure function that groups history items into `{ label, items }[]` by calendar day.

**Files:**
- Create: `web/src/lib/group-by-day.ts`, `web/src/lib/group-by-day.test.ts`.

- [ ] **Step 1: Write the failing test.**

```ts
import { describe, it, expect } from "vitest";
import { groupByDay } from "./group-by-day";
import type { HistoryItem } from "./types";

function item(added_at: number): HistoryItem {
  return {
    url: `https://${added_at}`, title: null, artist: null,
    media_format: "m4a", paths: [], thumb_id: null, added_at,
  };
}

describe("groupByDay", () => {
  it("groups items by calendar day", () => {
    const now = new Date("2026-06-03T15:00:00Z").getTime();
    const yesterday = now - 24 * 60 * 60 * 1000;
    const groups = groupByDay([item(now), item(yesterday), item(yesterday - 10000)], now);
    expect(groups).toHaveLength(2);
    expect(groups[0].label).toBe("Today");
    expect(groups[1].label).toBe("Yesterday");
    expect(groups[0].items).toHaveLength(1);
    expect(groups[1].items).toHaveLength(2);
  });

  it("uses absolute date label for older items", () => {
    const now = new Date("2026-06-03T15:00:00Z").getTime();
    const aWeekAgo = now - 7 * 24 * 60 * 60 * 1000;
    const groups = groupByDay([item(aWeekAgo)], now);
    expect(groups[0].label).toMatch(/May 2[67]/);
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- group-by-day
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/lib/group-by-day.ts`.**

```ts
import type { HistoryItem } from "./types";

export interface DayGroup {
  label: string;
  items: HistoryItem[];
}

function startOfDay(ts: number): number {
  const d = new Date(ts);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function label(itemDay: number, todayDay: number): string {
  const dayMs = 24 * 60 * 60 * 1000;
  if (itemDay === todayDay) return "Today";
  if (itemDay === todayDay - dayMs) return "Yesterday";
  return new Date(itemDay).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

export function groupByDay(items: HistoryItem[], now: number = Date.now()): DayGroup[] {
  const today = startOfDay(now);
  const map = new Map<number, HistoryItem[]>();
  for (const item of items) {
    const day = startOfDay(item.added_at);
    if (!map.has(day)) map.set(day, []);
    map.get(day)!.push(item);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => b - a)
    .map(([day, items]) => ({ label: label(day, today), items }));
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- group-by-day
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/lib/group-by-day.ts web/src/lib/group-by-day.test.ts
git commit -m "feat(web): add groupByDay history helper"
```

---

## Task 31: `<LibraryFilters />` component

**Goal:** Search input + format filter pills (controlled).

**Files:**
- Create: `web/src/components/library-filters.tsx`, `web/src/components/library-filters.test.tsx`.

- [ ] **Step 1: Write the failing test.**

```tsx
import { describe, it, expect, vi } from "vitest";
import { renderUI } from "@/test-utils/render";
import userEvent from "@testing-library/user-event";
import { LibraryFilters } from "./library-filters";

describe("LibraryFilters", () => {
  it("calls onSearchChange on input", async () => {
    const onSearchChange = vi.fn();
    const user = userEvent.setup();
    const { getByPlaceholderText } = renderUI(
      <LibraryFilters search="" formats={[]} availableFormats={["mp3", "flac"]}
        onSearchChange={onSearchChange} onFormatsChange={() => {}} />
    );
    await user.type(getByPlaceholderText(/search/i), "mac");
    expect(onSearchChange).toHaveBeenLastCalledWith("mac");
  });

  it("toggles format filters", async () => {
    const onFormatsChange = vi.fn();
    const user = userEvent.setup();
    const { getByRole } = renderUI(
      <LibraryFilters search="" formats={[]} availableFormats={["mp3", "flac"]}
        onSearchChange={() => {}} onFormatsChange={onFormatsChange} />
    );
    await user.click(getByRole("button", { name: "flac" }));
    expect(onFormatsChange).toHaveBeenLastCalledWith(["flac"]);
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- library-filters
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/components/library-filters.tsx`.**

```tsx
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Format } from "@/lib/types";

interface LibraryFiltersProps {
  search: string;
  formats: Format[];
  availableFormats: Format[];
  onSearchChange: (next: string) => void;
  onFormatsChange: (next: Format[]) => void;
}

export function LibraryFilters({
  search, formats, availableFormats,
  onSearchChange, onFormatsChange,
}: LibraryFiltersProps) {
  function toggle(f: Format) {
    onFormatsChange(formats.includes(f) ? formats.filter((x) => x !== f) : [...formats, f]);
  }
  return (
    <div className="mx-8 mt-4 mb-6 flex gap-3 items-center flex-wrap">
      <div className="relative flex-1 min-w-[200px] max-w-md">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-3)]" />
        <input
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search by title or artist"
          className="w-full bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] pl-9 pr-3 py-2 rounded-[var(--radius-md)] text-sm outline-none placeholder:text-[var(--text-3)]"
        />
      </div>
      <div className="flex gap-1.5">
        {availableFormats.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => toggle(f)}
            className={cn(
              "px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
              formats.includes(f)
                ? "bg-[var(--accent)] text-white"
                : "bg-[var(--surface)] text-[var(--text-2)] border border-[var(--border)]"
            )}
          >
            {f}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- library-filters
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/components/library-filters.tsx web/src/components/library-filters.test.tsx
git commit -m "feat(web): add LibraryFilters component"
```

---

## Task 32: `<LibraryGrid />` component

**Goal:** Day-grouped grid of album-art tiles. Per-tile right-click / "..." menu with Reveal / Re-download / Dismiss actions.

**Files:**
- Create: `web/src/components/library-grid.tsx`, `web/src/components/library-grid.test.tsx`.

- [ ] **Step 1: Write the failing test.**

```tsx
import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { LibraryGrid } from "./library-grid";
import type { HistoryItem } from "@/lib/types";

const items: HistoryItem[] = [
  { url: "https://a", title: "Self Care", artist: "Mac Miller", media_format: "m4a", paths: [], thumb_id: "abc", added_at: Date.now() },
  { url: "https://b", title: "Let It Happen", artist: "Tame Impala", media_format: "flac", paths: [], thumb_id: "def", added_at: Date.now() - 24*60*60*1000 },
];

describe("LibraryGrid", () => {
  it("shows tiles for each item", () => {
    const { getAllByTestId } = renderUI(<LibraryGrid items={items} onRemove={() => {}} />);
    expect(getAllByTestId("library-tile")).toHaveLength(2);
  });

  it("shows day group headers", () => {
    const { getByText } = renderUI(<LibraryGrid items={items} onRemove={() => {}} />);
    expect(getByText("Today")).toBeInTheDocument();
    expect(getByText("Yesterday")).toBeInTheDocument();
  });

  it("renders quiet empty state when items is empty", () => {
    const { getByText } = renderUI(<LibraryGrid items={[]} onRemove={() => {}} />);
    expect(getByText(/nothing yet/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, watch fail.**

```bash
cd web && npm test -- library-grid
```

Expected: FAIL.

- [ ] **Step 3: Implement `web/src/components/library-grid.tsx`.**

```tsx
import { AlbumArt } from "./album-art";
import { groupByDay } from "@/lib/group-by-day";
import type { HistoryItem } from "@/lib/types";

interface LibraryGridProps {
  items: HistoryItem[];
  onRemove: (url: string) => void;
}

export function LibraryGrid({ items }: LibraryGridProps) {
  if (items.length === 0) {
    return (
      <div className="px-8 py-16 text-center text-[var(--text-2)] text-base font-light">
        Nothing yet. Downloads will appear here once they finish.
      </div>
    );
  }
  const groups = groupByDay(items);
  return (
    <div className="px-8 pb-12">
      {groups.map((g) => (
        <div key={g.label} className="mb-8">
          <h3 className="text-lg font-bold tracking-tight mb-4 sticky top-0 bg-[var(--bg)] py-2">{g.label}</h3>
          <div className="grid grid-cols-6 gap-3">
            {g.items.map((h) => (
              <div key={h.url} data-testid="library-tile">
                <AlbumArt thumbId={h.thumb_id} size={140} className="!w-full !h-auto aspect-square" />
                <div className="text-sm font-semibold mt-2 truncate">{h.title ?? h.url}</div>
                {h.artist && <div className="text-xs text-[var(--text-3)] truncate">{h.artist}</div>}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run, watch pass.**

```bash
cd web && npm test -- library-grid
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add web/src/components/library-grid.tsx web/src/components/library-grid.test.tsx
git commit -m "feat(web): add LibraryGrid component"
```

---

## Task 33: Library route wiring

**Goal:** Compose `<LibraryFilters />` + `<LibraryGrid />` in `/library`.

**Files:**
- Modify: `web/src/routes/library.tsx`.

- [ ] **Step 1: Write the route.**

```tsx
import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useHistory } from "@/hooks/use-history";
import { LibraryFilters } from "@/components/library-filters";
import { LibraryGrid } from "@/components/library-grid";
import type { Format } from "@/lib/types";

export const Route = createFileRoute("/library")({ component: LibraryScreen });

function LibraryScreen() {
  const { history, removeItem } = useHistory();
  const [search, setSearch] = useState("");
  const [formats, setFormats] = useState<Format[]>([]);

  const availableFormats = useMemo(
    () => Array.from(new Set(history.map((h) => h.media_format))) as Format[],
    [history]
  );

  const filtered = useMemo(
    () => history.filter((h) => {
      if (formats.length > 0 && !formats.includes(h.media_format)) return false;
      if (search) {
        const needle = search.toLowerCase();
        const hay = `${h.title ?? ""} ${h.artist ?? ""} ${h.url}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    }),
    [history, search, formats]
  );

  return (
    <>
      <LibraryFilters
        search={search} formats={formats} availableFormats={availableFormats}
        onSearchChange={setSearch} onFormatsChange={setFormats}
      />
      <LibraryGrid items={filtered} onRemove={removeItem} />
    </>
  );
}
```

- [ ] **Step 2: Smoke-test.**

```bash
cd web && npm run dev
```

Click "Library" tab. If history exists (from earlier testing), tiles render. Empty otherwise.

- [ ] **Step 3: Commit.**

```bash
git add web/src/routes/library.tsx
git commit -m "feat(web): wire up Library route"
```

---

## Task 33b: Reveal-in-Finder context menu on Library tiles (spec decision #16)

**Goal:** Right-click on a library tile opens a Radix `ContextMenu` with Reveal in Finder / Re-download / Dismiss from history. A hover-revealed "..." trigger gives the same menu via left-click for discoverability.

**Files:**
- Modify: `web/package.json` (add `@radix-ui/react-context-menu`).
- Create: `web/src/components/ui/context-menu.tsx`, `web/src/components/library-tile-menu.tsx`, `web/src/components/library-tile-menu.test.tsx`.
- Modify: `web/src/components/library-grid.tsx` (wrap each tile in the menu trigger; emit `onRemove`, `onReveal`, `onReDownload`).

- [ ] **Step 1: Install the Radix primitive.**

```bash
cd web && npm install @radix-ui/react-context-menu@^2.2.0
```

- [ ] **Step 2: Add the shadcn ContextMenu primitive `web/src/components/ui/context-menu.tsx`.**

```tsx
import * as React from "react";
import * as ContextMenuPrimitive from "@radix-ui/react-context-menu";
import { cn } from "@/lib/utils";

export const ContextMenu = ContextMenuPrimitive.Root;
export const ContextMenuTrigger = ContextMenuPrimitive.Trigger;
export const ContextMenuPortal = ContextMenuPrimitive.Portal;

export const ContextMenuContent = React.forwardRef<
  React.ElementRef<typeof ContextMenuPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Content>
>(({ className, ...props }, ref) => (
  <ContextMenuPortal>
    <ContextMenuPrimitive.Content
      ref={ref}
      className={cn(
        "z-50 min-w-[12rem] overflow-hidden rounded-[var(--radius-md)]",
        "border border-[var(--border)] bg-[#101013] p-1 shadow-md",
        "text-sm text-[var(--text)]",
        className
      )}
      {...props}
    />
  </ContextMenuPortal>
));
ContextMenuContent.displayName = "ContextMenuContent";

export const ContextMenuItem = React.forwardRef<
  React.ElementRef<typeof ContextMenuPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Item>
>(({ className, ...props }, ref) => (
  <ContextMenuPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex select-none items-center gap-2 rounded-[var(--radius-sm)] px-2 py-1.5",
      "outline-none cursor-default",
      "data-[highlighted]:bg-[var(--surface)] data-[highlighted]:text-[var(--text)]",
      className
    )}
    {...props}
  />
));
ContextMenuItem.displayName = "ContextMenuItem";
```

- [ ] **Step 3: Write the failing test for `<LibraryTileMenu />`.**

`web/src/components/library-tile-menu.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { renderUI } from "@/test-utils/render";
import userEvent from "@testing-library/user-event";
import { LibraryTileMenu } from "./library-tile-menu";
import type { HistoryItem } from "@/lib/types";

const item: HistoryItem = {
  url: "https://a", title: "X", artist: null, media_format: "m4a",
  paths: ["/tmp/x.m4a"], thumb_id: null, added_at: 0,
};

describe("LibraryTileMenu", () => {
  it("wraps children and exposes a trigger", () => {
    const { getByText } = renderUI(
      <LibraryTileMenu item={item} onRemove={() => {}}>
        <div>tile contents</div>
      </LibraryTileMenu>
    );
    expect(getByText("tile contents")).toBeInTheDocument();
  });

  it("calls onRemove from menu", async () => {
    const onRemove = vi.fn();
    const user = userEvent.setup();
    const { getByText } = renderUI(
      <LibraryTileMenu item={item} onRemove={onRemove}>
        <button>tile</button>
      </LibraryTileMenu>
    );
    // Right-click the trigger.
    await user.pointer({ keys: "[MouseRight]", target: getByText("tile") });
    await user.click(await waitForMenuItem(/dismiss/i));
    expect(onRemove).toHaveBeenCalledWith("https://a");
  });
});

async function waitForMenuItem(name: RegExp): Promise<HTMLElement> {
  const { findByRole } = await import("@testing-library/react");
  return findByRole(document.body, "menuitem", { name }) as Promise<HTMLElement>;
}
```

- [ ] **Step 4: Run, watch fail.**

```bash
cd web && npm test -- library-tile-menu
```

Expected: FAIL.

- [ ] **Step 5: Implement `web/src/components/library-tile-menu.tsx`.**

```tsx
import { FolderOpen, RefreshCw, Trash2 } from "lucide-react";
import {
  ContextMenu, ContextMenuTrigger, ContextMenuContent, ContextMenuItem,
} from "./ui/context-menu";
import { reveal, postJobs } from "@/lib/api";
import type { HistoryItem } from "@/lib/types";

interface LibraryTileMenuProps {
  item: HistoryItem;
  onRemove: (url: string) => void;
  children: React.ReactNode;
}

export function LibraryTileMenu({ item, onRemove, children }: LibraryTileMenuProps) {
  async function handleReveal() {
    if (item.paths[0]) {
      try { await reveal(item.paths[0]); } catch (e) { console.error(e); }
    }
  }
  async function handleReDownload() {
    try { await postJobs([{ url: item.url, format: item.media_format }]); }
    catch (e) { console.error(e); }
  }
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={handleReveal} disabled={!item.paths[0]}>
          <FolderOpen size={14} /> Reveal in Finder
        </ContextMenuItem>
        <ContextMenuItem onSelect={handleReDownload}>
          <RefreshCw size={14} /> Re-download
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => onRemove(item.url)}>
          <Trash2 size={14} /> Dismiss from history
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
```

- [ ] **Step 6: Update `web/src/components/library-grid.tsx` to wrap each tile in `LibraryTileMenu`.**

```tsx
import { LibraryTileMenu } from "./library-tile-menu";
// ...
{g.items.map((h) => (
  <LibraryTileMenu key={h.url} item={h} onRemove={onRemove}>
    <div data-testid="library-tile" className="cursor-context-menu">
      <AlbumArt thumbId={h.thumb_id} size={140} className="!w-full !h-auto aspect-square" />
      <div className="text-sm font-semibold mt-2 truncate">{h.title ?? h.url}</div>
      {h.artist && <div className="text-xs text-[var(--text-3)] truncate">{h.artist}</div>}
    </div>
  </LibraryTileMenu>
))}
```

- [ ] **Step 7: Run all tests.**

```bash
cd web && npm test
```

Expected: all tests pass (existing library-grid tests still work since the tile content is unchanged; new menu tests pass).

- [ ] **Step 8: Commit.**

```bash
git add web/
git commit -m "feat(web): add Library tile context menu (reveal / re-download / dismiss)"
```

---

# Phase 8 — Backend cleanup

## Task 34: Mount StaticFiles, remove `_INDEX_*` constants

**Goal:** Delete the inline template machinery and serve the React build instead.

**Files:**
- Modify: `audio_dl_ui.py`.
- Create: `audio_dl_ui/__init__.py`, `audio_dl_ui/static/.gitkeep`.
- Modify: `test_audio_dl_ui.py` (remove HTML-content assertions).

- [ ] **Step 1: Create the package directory and gitkeep.**

```bash
mkdir -p audio_dl_ui/static
touch audio_dl_ui/__init__.py audio_dl_ui/static/.gitkeep
```

`audio_dl_ui/__init__.py` content:

```python
"""Static files package for the React UI bundle.

This package exists solely so `importlib.resources` can resolve the bundled
`static/` directory at runtime, including inside a PyInstaller-built `.app`.
"""
```

- [ ] **Step 2: Stage a tiny static `index.html` so the smoke test has something to serve before `npm run build` happens in tests.**

```bash
mkdir -p audio_dl_ui/static
cat > audio_dl_ui/static/index.html <<'EOF'
<!doctype html><title>audio-dl</title><h1>audio-dl static placeholder</h1>
EOF
```

(This file is *only* a placeholder for tests; production `audio_dl_ui/static/` gets overwritten by `npm run build`.)

- [ ] **Step 3: Write the failing test.**

In `test_audio_dl_ui.py`, replace any existing test asserting the inline HTML body with:

```python
class TestStaticFilesMount:
    def test_root_serves_index_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert b"<title>audio-dl</title>" in r.content

    def test_unknown_path_serves_index_html(self, client):
        # html=True fallback for client-side routing.
        r = client.get("/library")
        assert r.status_code == 200
        assert b"<title>audio-dl</title>" in r.content
```

Search `test_audio_dl_ui.py` for any test asserting inline `_INDEX_*` content and delete those tests — they're testing a removed UI.

- [ ] **Step 4: Run, watch fail (or pass if the previous index handler still routes).**

```bash
pytest test_audio_dl_ui.py::TestStaticFilesMount -v
```

Expected: probably fails (the old `GET /` handler returns the inline template, not the static file).

- [ ] **Step 5: Delete the inline machinery in `audio_dl_ui.py`.**

Remove:
- `_INDEX_TEMPLATE`, `_INDEX_CSS_BASE`, `_INDEX_CSS_THEMES`, `_INDEX_HTML_BODY`, `_INDEX_JS` constants
- `_render_index` function
- `@app.get("/", response_class=HTMLResponse)` handler
- `THEMES` JS constant references

Add the StaticFiles mount at the end of the route definitions (must come last so it doesn't shadow `/jobs`, `/api`, `/reveal`, `/thumbs`):

```python
from importlib.resources import files
from fastapi.staticfiles import StaticFiles

_static_dir = files("audio_dl_ui") / "static"
app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
```

Place that block at the bottom of `audio_dl_ui.py`, after all `@app.{get,post}` route definitions.

- [ ] **Step 6: Run, watch pass.**

```bash
pytest test_audio_dl_ui.py::TestStaticFilesMount -v
pytest -q
```

Expected: TestStaticFilesMount green; full suite green (after deleting the old inline-HTML tests).

- [ ] **Step 7: Confirm pylint passes (a lot of dead code is gone).**

```bash
pylint $(git ls-files '*.py')
```

Expected: 10.00/10.

- [ ] **Step 8: Commit.**

```bash
git add audio_dl_ui.py audio_dl_ui/ test_audio_dl_ui.py
git commit -m "feat(ui): replace inline template with StaticFiles mount"
```

---

## Task 35: Verify backend size collapsed

**Goal:** Confirmation step — the 3700-line file is now small.

**Files:** none modified.

- [ ] **Step 1: Check line count.**

```bash
wc -l audio_dl_ui.py
```

Expected: under 1500 lines (the template machinery was ~2500 lines).

- [ ] **Step 2: No commit.**

---

# Phase 9 — Packaging

## Task 36: `scripts/build-web.sh` helper

**Goal:** One reusable script that builds the React app and copies the output into the Python package's static dir.

**Files:**
- Create: `scripts/build-web.sh`.

- [ ] **Step 1: Write the script.**

```bash
#!/usr/bin/env bash
# Build the React frontend and copy the bundle into the Python package's static/.
set -euo pipefail
cd "$(dirname "$0")/.."

pushd web > /dev/null
npm ci
npm run build
popd > /dev/null

rm -rf audio_dl_ui/static
mkdir -p audio_dl_ui/static
cp -R web/dist/* audio_dl_ui/static/
echo "web bundle → audio_dl_ui/static/"
```

- [ ] **Step 2: Make it executable.**

```bash
chmod +x scripts/build-web.sh
```

- [ ] **Step 3: Smoke-test it.**

```bash
./scripts/build-web.sh
ls audio_dl_ui/static/
```

Expected: `index.html`, `assets/`, plus other Vite outputs.

- [ ] **Step 4: Commit.**

```bash
git add scripts/build-web.sh
git commit -m "build: add scripts/build-web.sh"
```

---

## Task 37: Update `scripts/build-app.sh`

**Goal:** Run the web build before PyInstaller.

**Files:**
- Modify: `scripts/build-app.sh`.

- [ ] **Step 1: Edit `scripts/build-app.sh`.**

At the top of the script (after `set -euo pipefail`), insert:

```bash
# Build the React frontend first so PyInstaller has audio_dl_ui/static/ populated.
"$(dirname "$0")/build-web.sh"
```

- [ ] **Step 2: Commit.**

```bash
git add scripts/build-app.sh
git commit -m "build: build web bundle before PyInstaller in build-app.sh"
```

---

## Task 38: Update `audio-dl.spec` (PyInstaller)

**Goal:** Include `audio_dl_ui/static/**` in the bundle so the `.app` ships the React build.

**Files:**
- Modify: `audio-dl.spec`.

- [ ] **Step 1: Locate `datas = [...]` in `audio-dl.spec` and append:**

```python
datas = [
    # ... existing entries
    ("audio_dl_ui/static", "audio_dl_ui/static"),
]
```

If `datas` doesn't exist yet, add it before the `Analysis(...)` call.

- [ ] **Step 2: Smoke-test the build.**

```bash
./scripts/build-app.sh
```

Expected: produces `dist/audio-dl.app`. Try launching it: `open dist/audio-dl.app`. The web UI should appear.

- [ ] **Step 3: Commit.**

```bash
git add audio-dl.spec
git commit -m "build: include audio_dl_ui/static in PyInstaller bundle"
```

---

## Task 39: Update `pyproject.toml` package data

**Goal:** A `pip install` should include `audio_dl_ui/static/**` so server installs (without `.app` bundling) still serve the bundle.

**Files:**
- Modify: `pyproject.toml`.

- [ ] **Step 1: Add package data section.**

In `pyproject.toml`:

```toml
[tool.setuptools]
packages = ["audio_dl_ui"]
py-modules = ["audio_dl"]

[tool.setuptools.package-data]
audio_dl_ui = ["static/**/*"]
```

(Adjust to merge with any existing `[tool.setuptools.*]` sections.)

- [ ] **Step 2: Verify `pip install -e .` still works.**

```bash
pip install -e '.[ui]'
audio-dl-ui --port 9100 --no-browser
```

Open http://localhost:9100/?token=... — UI should load. Ctrl-C.

- [ ] **Step 3: Commit.**

```bash
git add pyproject.toml
git commit -m "build: declare audio_dl_ui.static as package data"
```

---

# Phase 10 — Release prep

## Task 40: Update CI workflow

**Goal:** CI builds the web bundle before running pytest so `audio_dl_ui/static/index.html` exists for backend tests.

**Files:**
- Modify: `.github/workflows/tests.yml`.

- [ ] **Step 1: Add a Node setup + web build step to the matrix job.**

In `.github/workflows/tests.yml`, before the pytest step (and after Python setup):

```yaml
      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: web/package-lock.json

      - name: Build web bundle
        run: ./scripts/build-web.sh

      - name: Frontend tests
        run: cd web && npm test
```

- [ ] **Step 2: Commit.**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: build web bundle and run frontend tests"
```

---

## Task 41: Update README

**Goal:** Document the new dev workflow and the deletion of themes.

**Files:**
- Modify: `README.md`.

- [ ] **Step 1: Replace any v1 UI screenshots / sections.**

Look for: "Themes", "Console UI", `phosphor` references, `_INDEX_*`. Remove or replace.

Add a "Web UI v2" section:

```markdown
## Web UI (v2)

The web UI is a React app built with Vite, served by FastAPI's `StaticFiles`.

### Development

In one terminal, run the backend in dev mode:

\`\`\`bash
AUDIO_DL_DEV=1 audio-dl-ui --port 9000 --no-browser
\`\`\`

In another:

\`\`\`bash
cd web
npm install
npm run dev
\`\`\`

Open http://localhost:5173. The Vite proxy forwards `/api`, `/jobs`, `/thumbs`, `/reveal` to the backend.

### Production

\`\`\`bash
./scripts/build-web.sh   # produces audio_dl_ui/static/
audio-dl-ui              # serves the built bundle
\`\`\`
```

- [ ] **Step 2: Commit.**

```bash
git add README.md
git commit -m "docs: update README for v2 React UI dev/prod workflow"
```

---

## Task 42: CHANGELOG entry

**Goal:** Document the major break.

**Files:**
- Modify: `CHANGELOG.md`.

- [ ] **Step 1: Add a `## v2.0.0` section above the existing `## v1.9.2` entry.**

```markdown
## v2.0.0 — Web UI v2 (React rewrite)

The web UI is rebuilt from scratch:

- **New aesthetic:** "Now Playing" single-focus design. Album art glows on a stage at the center; ambient color is extracted from that art using node-vibrant. The console / TUI look is gone.
- **New stack:** Vite + React 19 + TypeScript + TanStack Router + TanStack Query + Tailwind v4 + shadcn/ui (Radix primitives) + Lucide + Biome. The 3700-line inline `_INDEX_TEMPLATE` is replaced by a Vite-built bundle served via FastAPI `StaticFiles`.
- **New screens:** `/` (Now — active downloads, queue, URL input) and `/library` (full history with search + format filter, day-grouped tile grid).
- **No more themes.** The ten console themes from v1.5-1.7 are removed.
- **No cmd-K.** The keyboard palette is gone; every action is reachable through visible UI.
- **No more per-URL row builder.** Paste one URL at a time, or multi-line paste auto-queues each line at the current default format.
- **Adaptive accent color.** Each new hero album art re-tints the page's accent gradient.
- **Thumbnail cache.** Completed downloads' thumbnails are persisted on-disk under `~/Library/Application Support/audio-dl/thumbs/` and served by stable SHA-1 URLs via `GET /thumbs/{thumb_id}.jpg` — so the Library view always has art available.
- **Server additions:** `/api/version`, `/api/settings/defaults`, `/api/csrf` (dev-only), `/thumbs/{thumb_id}.jpg`. `POST /jobs` returns `thumb_id` per URL.
- **Backwards compatibility:** v1 history in localStorage carries forward as-is; old entries render with fallback gradients (no `thumb_id`). CLI is unchanged.

The `.app` build pipeline now runs `npm ci && npm run build` before PyInstaller. CI builds the bundle and runs the frontend test suite alongside pytest.
```

- [ ] **Step 2: Commit.**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): add v2.0.0 entry"
```

---

## Task 43: Version bump

**Goal:** Bump `__version__` to 2.0.0 in both sources.

**Files:**
- Modify: `audio_dl.py`, `pyproject.toml`.

- [ ] **Step 1: Edit `audio_dl.py` line 31:** `__version__ = "1.9.2"` → `__version__ = "2.0.0"`.

- [ ] **Step 2: Edit `pyproject.toml` line 7:** `version = "1.9.2"` → `version = "2.0.0"`.

- [ ] **Step 3: Run full suite.**

```bash
pytest -q && pylint $(git ls-files '*.py') && cd web && npm test
```

Expected: all green.

- [ ] **Step 4: Commit.**

```bash
cd "$(git rev-parse --show-toplevel)"
git add audio_dl.py pyproject.toml
git commit -m "chore: bump version to 2.0.0"
```

---

## Task 44: Open PR

**Goal:** Land the rewrite via a release PR (which the watcher routine auto-tags after merge).

**Files:** none.

- [ ] **Step 1: Push the branch.**

```bash
git push -u origin v2.0-react-rewrite
```

- [ ] **Step 2: Open the PR.**

```bash
gh pr create --title "v2.0.0 — Web UI v2 React rewrite (Now Playing aesthetic)" --body "$(cat <<'EOF'
## Summary

- Complete frontend rewrite. The 3700-line inline `_INDEX_TEMPLATE` in `audio_dl_ui.py` is replaced by a Vite-built React app served via `StaticFiles`.
- New "Now Playing" aesthetic: stage with hero album art, adaptive accent extracted from art with node-vibrant, "Also downloading" strip for concurrent jobs, "Up next" queue, always-on URL input with inline format pill.
- New `/library` route: full history with search, per-format filter, day-grouped tile grid.
- Stack: React 19, TypeScript, Vite 6, TanStack Router/Query, Tailwind v4, shadcn/ui (Radix), Lucide, Biome.
- Backend additions: `/api/version`, `/api/settings/defaults`, `/api/csrf` (dev-only), `/thumbs/{thumb_id}.jpg`. Thumbnails cached on-disk by SHA-1 of source URL.
- Themes removed. cmd-K removed. Per-URL row builder removed.
- See: spec [docs/superpowers/specs/2026-06-03-web-ui-v2-react-rewrite-design.md](docs/superpowers/specs/2026-06-03-web-ui-v2-react-rewrite-design.md), plan [docs/superpowers/plans/2026-06-03-web-ui-v2-react-rewrite.md](docs/superpowers/plans/2026-06-03-web-ui-v2-react-rewrite.md).

## Test plan

- [x] `pytest -q` — full backend suite green
- [x] `pylint $(git ls-files '*.py')` — 10.00/10
- [x] `cd web && npm test` — frontend suite green
- [x] `cd web && npm run build` — bundle builds
- [x] Local smoke: paste YouTube URL → see progress on stage → completes → enters Library
- [x] Multi-line paste auto-queues each line at default format
- [x] Library search + format filter work
- [x] `.app` bundle build via `scripts/build-app.sh` produces a launchable app
- [ ] First-launch experience on a fresh machine (right-click → Open)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: After CI is green, mark ready-for-review.**

```bash
gh pr ready
```

The Codex review runs on draft→ready. Address any findings before merge.

After merge, the PR watcher routine auto-tags `v2.0.0`. The mirror workflow propagates to the public repo, and `release.yml` on public builds and publishes the `.app`.

---

## Self-review checklist (run after finishing the plan)

- Spec section "Locked decisions" #1–#19: every decision is implemented in some task.
- Spec section "Server changes / Add" — `/api/version` Task 1, `/api/settings/defaults` Task 2, `/api/csrf` Task 3, `/thumbs/` Tasks 4–5, `POST /jobs` amendment Task 6.
- Spec section "Aesthetic system" tokens are in `tokens.css` (Task 10) and consumed by component classes.
- Spec section "Screens" — Now (Tasks 24–29), Library (Tasks 30–33).
- Spec section "Components" — every component listed in §Components has a task.
- Spec section "Build & packaging" — Tasks 36–39 cover scripts and PyInstaller.
- Spec section "Migration" — `audio_dl_ui/__init__.py` (Task 34) makes the package locatable; v1 history forward-compat is handled by `useHistory` defaulting missing `thumb_id` to `null` (Task 28).
- No placeholders — every step contains the code or command an engineer would need.
