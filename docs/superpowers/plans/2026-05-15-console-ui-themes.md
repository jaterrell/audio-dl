# v1.5 Console UI + Theme System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current macOS-system-light web UI with a TUI-in-browser direction (Console aesthetic) and add a runtime theme system with 10 themes (Phosphor Green default), accessible via a popover picker in the TUI frame header.

**Architecture:** Refactor `_INDEX_HTML` (currently one ~280-line Python string in `audio_dl_ui.py`) into five split constants — `_INDEX_TEMPLATE`, `_INDEX_CSS_BASE`, `_INDEX_CSS_THEMES`, `_INDEX_HTML_BODY`, `_INDEX_JS` — assembled by a new `_render_index()` helper. Themes implemented as `:root[data-theme="<slug>"]` CSS-vars blocks. A synchronous boot script in `<head>` reads `localStorage["audio-dl-theme"]` (or `prefers-color-scheme`, or `'phosphor'` fallback) and sets `documentElement.dataset.theme` before paint, avoiding FOUC. Picker popover lives in the TUI frame header; keyboard handlers (`⌘↵`, `esc`, `⌘T`, `⌘K`) bound on `DOMContentLoaded`.

**Tech Stack:** Python 3.10+, FastAPI, vanilla JS/CSS (no framework, no build step), `pytest` for the rendering tests, pylint at 10.00/10.

**Spec:** [docs/superpowers/specs/2026-05-14-console-ui-themes.md](../specs/2026-05-14-console-ui-themes.md) (commit `128afc3`)

---

## Task 1: Transparent refactor — split `_INDEX_HTML` into 5 constants + `_render_index()` helper

**Why first:** every later task touches one of the new constants. Doing this as a no-behavior-change refactor first means the rest of the plan can edit specific constants in isolation without re-litigating the index() route. This task ends with byte-equivalent rendering and all 147 existing tests passing.

**Files:**
- Modify: `audio_dl_ui.py:338-663` (replaces `_INDEX_HTML` definition + `index()` route body)
- Modify: `test_audio_dl_ui.py:864-874` (`TestBtoaUnicodeSafe` — retarget import from `_INDEX_HTML` to `_INDEX_JS`)

- [ ] **Step 1: Read the current `_INDEX_HTML` to identify split boundaries**

Run: `awk 'NR>=339 && NR<=623' audio_dl_ui.py | head -100`

Identify these regions inside the existing string (line numbers below are within the current file):
- `<!doctype html>` through `<title>audio-dl</title>` and `<style>` open → goes in `_INDEX_TEMPLATE`
- Everything between `<style>` and `</style>` (lines 346–378) → goes in `_INDEX_CSS_BASE`
- The closing `</style></head><body>` → goes in `_INDEX_TEMPLATE`
- Everything between `<body>` open and `<script>` open (lines 382–426) → goes in `_INDEX_HTML_BODY`
- The opening `<script>` tag → goes in `_INDEX_TEMPLATE`
- Everything inside `<script>...</script>` (lines 428–618) → goes in `_INDEX_JS`
- The closing `</script></body></html>` → goes in `_INDEX_TEMPLATE`

`_INDEX_CSS_THEMES` is **empty for this task** — added in Task 2.

- [ ] **Step 2: Replace the `_INDEX_HTML` block with the five split constants + template + helper**

Open `audio_dl_ui.py`. Find the line `# pylint: disable=line-too-long` immediately before `_INDEX_HTML = """<!doctype html>` (around line 338). Replace from that line through the closing `"""` of `_INDEX_HTML` (around line 622) with this exact code, **preserving the existing HTML/CSS/JS content verbatim** in the appropriate constant:

```python
# pylint: disable=line-too-long
_INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="csrf-token" content="__CSRF_TOKEN__">
<title>audio-dl</title>
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

_INDEX_CSS_BASE = """  :root { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif; }
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
"""

_INDEX_CSS_THEMES = ""

_INDEX_HTML_BODY = """<h1>audio-dl</h1>
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
"""

_INDEX_JS = """(() => {
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
    if (ev.type === 'job_snapshot') {
      ev.urls.forEach(u => {
        const row = rowFor(u.url);
        setBar(row, u.percent);
        if (u.status === 'downloading') {
          const bits = [u.percent.toFixed(1) + '%'];
          if (u.speed) bits.push(fmtSpeed(u.speed));
          if (u.eta != null) bits.push(fmtEta(u.eta));
          setStatus(row, bits.join(' · '));
        } else if (u.status === 'completed') {
          setBar(row, 100);
          setStatus(row, 'completed', 'completed');
          if (u.paths && u.paths.length) addRevealButton(row, u.paths);
        } else if (u.status === 'failed') {
          setStatus(row, u.error || 'failed', 'failed');
        } else if (u.status === 'cancelled') {
          setStatus(row, 'cancelled', 'cancelled');
        }
      });
      if (ev.complete) {
        $('submit').disabled = false;
        $('cancel').disabled = true;
      }
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
    es.onerror = () => { /* EventSource auto-reconnects */ };
  });

  $('cancel').addEventListener('click', () => {
    if (currentJobId) {
      fetch('/jobs/' + currentJobId + '/cancel', {method: 'POST', headers: {'X-Audio-DL-Token': CSRF_TOKEN}});
    }
  });
})();
"""
# pylint: enable=line-too-long


def _render_index(token: str, options: str, default_dir: str) -> str:
    """Assemble the full HTML page from the split constants.

    Substitutions:
      - {css_base}, {css_themes}, {html_body}, {js} into _INDEX_TEMPLATE
      - __CSRF_TOKEN__, __FORMAT_OPTIONS__, __DEFAULT_OUTPUT_DIR__ into the body/JS
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
    )
```

**Important:** the `_INDEX_TEMPLATE` uses `{css_base}` / `{css_themes}` / `{html_body}` / `{js}` as `str.format()` placeholders. The CSS in `_INDEX_CSS_BASE` contains literal `{` and `}` characters from CSS rules. Inside a string passed to `.format()`, those would be interpreted as format-placeholders and crash. **Solution:** since `_INDEX_CSS_BASE` and the other large constants are interpolated *into* the template (not formatted themselves), they don't need escaping — but the template itself must not contain stray `{` or `}` outside the named placeholders. The template above is clean (only the four named braces). Verify by reading the template back: there are no other `{` or `}` characters in `_INDEX_TEMPLATE`.

- [ ] **Step 3: Update the `index()` route to call the helper**

Find the `index()` async function (line 645). Replace its body with:

```python
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
```

- [ ] **Step 4: Retarget the `_INDEX_HTML`-importing test to `_INDEX_JS`**

Open `test_audio_dl_ui.py`. Find `class TestBtoaUnicodeSafe` (line 864). Replace the test method body:

```python
class TestBtoaUnicodeSafe:
    """The rowFor() JS uses btoa for row ids. Raw btoa throws on non-ASCII;
    wrapping with unescape(encodeURIComponent(...)) makes it UTF-8 safe."""

    def test_js_uses_utf8_safe_btoa(self):
        # Structural assertion on the embedded JS (post-refactor: was _INDEX_HTML).
        from audio_dl_ui import _INDEX_JS
        assert "btoa(unescape(encodeURIComponent(url)))" in _INDEX_JS
        # No remaining raw btoa(url) without the wrap.
        assert "btoa(url)" not in _INDEX_JS
```

- [ ] **Step 5: Run the full test suite — expect all 147 to pass**

Run: `pytest -q`

Expected: `147 passed`. Same count as before (no new tests). If anything fails, the refactor lost or shifted something — revert and try again.

- [ ] **Step 6: Lint**

Run: `pylint $(git ls-files '*.py')`

Expected: 10.00/10. The new constants share the existing `# pylint: disable=line-too-long` block.

- [ ] **Step 7: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "$(cat <<'EOF'
refactor(ui): split _INDEX_HTML into 5 constants + _render_index helper

Replaces the single ~280-line _INDEX_HTML string with _INDEX_TEMPLATE,
_INDEX_CSS_BASE, _INDEX_CSS_THEMES (empty for now), _INDEX_HTML_BODY,
and _INDEX_JS, assembled by a new _render_index() helper. No behavior
change — same rendered HTML, same 147 tests passing.

Sets up the v1.5 Console UI work where each constant gets edited in
isolation: themes go in _INDEX_CSS_THEMES, picker logic in _INDEX_JS,
TUI body in _INDEX_HTML_BODY.

Retargets test_audio_dl_ui.py:870 (TestBtoaUnicodeSafe) to import
_INDEX_JS instead of _INDEX_HTML, since the latter no longer exists.

Spec: docs/superpowers/specs/2026-05-14-console-ui-themes.md
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add the 10 theme CSS-vars blocks to `_INDEX_CSS_THEMES`

**Why second:** themes are pure CSS data with no dependencies on body markup or JS. Adding them now lets every later task assume their existence. The blocks are inert until the body markup uses `var(--bg)` etc. — that swap happens in Task 5.

**Files:**
- Modify: `audio_dl_ui.py` (`_INDEX_CSS_THEMES` constant)
- Modify: `test_audio_dl_ui.py` (add `TestThemeRendering` class with first test)

- [ ] **Step 1: Write the failing test for all 10 theme blocks**

At the bottom of `test_audio_dl_ui.py`, after the last existing class, add:

```python
# ---------------------------------------------------------------------------
# v1.5 theme system — CSS cascade + JS registry tests
# ---------------------------------------------------------------------------

import re  # noqa: E402  (intentional position; tests below use it)


class TestThemeRendering:
    """Theme cascade is 10 :root[data-theme="<slug>"] blocks. The JS THEMES
    registry must enumerate the same 10 slugs in the same order. Drift between
    the two would silently break the picker."""

    EXPECTED_SLUGS = [
        "phosphor", "rose", "moon", "dawn", "amber",
        "solarized", "gruvbox", "tokyo", "atom", "claude",
    ]

    def test_all_ten_theme_blocks_present(self):
        """_INDEX_CSS_THEMES contains exactly 10 :root[data-theme="<slug>"] selectors."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        found = re.findall(r':root\[data-theme="([^"]+)"\]', _INDEX_CSS_THEMES)
        assert sorted(found) == sorted(self.EXPECTED_SLUGS), (
            f"Expected {self.EXPECTED_SLUGS}, found {found}"
        )
```

- [ ] **Step 2: Run the test — expect FAIL**

Run: `pytest test_audio_dl_ui.py::TestThemeRendering::test_all_ten_theme_blocks_present -v`

Expected: FAIL — `_INDEX_CSS_THEMES` is currently `""`.

- [ ] **Step 3: Add the 10 theme blocks to `_INDEX_CSS_THEMES`**

Open `audio_dl_ui.py`. Find `_INDEX_CSS_THEMES = ""` and replace with this exact content:

```python
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
```

- [ ] **Step 4: Run the test — expect PASS**

Run: `pytest test_audio_dl_ui.py::TestThemeRendering -v`

Expected: PASS.

- [ ] **Step 5: Run the full suite + lint**

Run: `pytest -q`
Expected: 148 passed (147 + 1 new).

Run: `pylint $(git ls-files '*.py')`
Expected: 10.00/10.

- [ ] **Step 6: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "$(cat <<'EOF'
feat(ui): add 10 theme CSS-vars blocks to _INDEX_CSS_THEMES

Phosphor Green (default), Rose Pine, Rose Pine Moon, Rose Pine Dawn
(light), Amber CRT, Solarized Dark, Gruvbox Dark, Tokyo Night,
Atom Dark Pro, Claude. Each block defines 12 CSS custom properties
(--bg, --fg, --frame, --label, --accent, --ok, --err, --warn, --live,
--dim, --bar, --btn-fg). Inert until the body markup uses var(--xxx)
references (Task 5).

New TestThemeRendering test enumerates the expected 10 slugs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add `THEMES` JS registry to `_INDEX_JS`

**Why now:** the registry is the single source of truth for the picker UI (rendered later, in Task 6). Adding it now with a matching test catches drift between CSS-block slugs and the JS array.

**Files:**
- Modify: `audio_dl_ui.py` (prepend `THEMES` to `_INDEX_JS`)
- Modify: `test_audio_dl_ui.py` (extend `TestThemeRendering`)

- [ ] **Step 1: Write the failing tests for the JS registry**

Add to the existing `TestThemeRendering` class in `test_audio_dl_ui.py`:

```python
    def test_js_themes_registry_matches_css_slugs(self):
        """JS THEMES array's slugs match the CSS :root[data-theme] slugs."""
        from audio_dl_ui import _INDEX_JS
        slugs = re.findall(r"slug:\s*'([^']+)'", _INDEX_JS)
        assert sorted(slugs) == sorted(self.EXPECTED_SLUGS), (
            f"JS slugs {slugs} drift from CSS slugs {self.EXPECTED_SLUGS}"
        )

    def test_js_default_theme_is_phosphor(self):
        """Exactly one theme entry has default: true, and it's phosphor."""
        from audio_dl_ui import _INDEX_JS
        # Match a registry entry where default: true follows the slug.
        # Allow any chars except 'slug:' between slug and default within the entry.
        defaults = re.findall(
            r"slug:\s*'([^']+)'[^}]*default:\s*true",
            _INDEX_JS,
        )
        assert defaults == ['phosphor'], (
            f"Expected exactly ['phosphor'] as default, got {defaults}"
        )
```

- [ ] **Step 2: Run — expect FAIL on both**

Run: `pytest test_audio_dl_ui.py::TestThemeRendering -v`

Expected: 1 PASS (the previous test), 2 FAIL (no `THEMES` array exists yet).

- [ ] **Step 3: Prepend the `THEMES` registry to `_INDEX_JS`**

Open `audio_dl_ui.py`. Find the line `_INDEX_JS = """(() => {`. Replace just that opening line + the line after with:

```python
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
```

(The existing IIFE body that follows `(() => {` stays exactly as-is. The `THEMES` const is declared at module scope before the IIFE so it's visible to both the boot script in Task 4 and the picker code in Task 6.)

- [ ] **Step 4: Run the tests — expect PASS**

Run: `pytest test_audio_dl_ui.py::TestThemeRendering -v`

Expected: 3 PASS.

- [ ] **Step 5: Run the full suite + lint**

Run: `pytest -q`
Expected: 150 passed (148 + 2 new).

Run: `pylint $(git ls-files '*.py')`
Expected: 10.00/10.

- [ ] **Step 6: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "$(cat <<'EOF'
feat(ui): add THEMES registry to _INDEX_JS

10-entry array — { slug, name, default?, light? } — declared at module
scope before the existing IIFE so the boot script and picker (Tasks 4
and 6) can both see it. Phosphor flagged default: true; Dawn flagged
light: true for the prefers-color-scheme handler.

Two new tests assert (a) JS slugs match CSS slugs (catches drift) and
(b) exactly one entry has default: true, and it's phosphor.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add the synchronous boot script in `<head>` to set `data-theme`

**Why now:** the boot script needs `THEMES` (Task 3) to validate slugs from localStorage, and is independent of the body markup (Task 5). Adding it here means by Task 5 we already have a known-good mechanism for applying themes.

**Files:**
- Modify: `audio_dl_ui.py` (`_INDEX_TEMPLATE` — inject a `<script>` before `<title>`; the boot script needs `THEMES` so it has to come *after* the THEMES const is defined — easiest is to inline the slug list directly in the boot script for self-containment)

- [ ] **Step 1: Update `_INDEX_TEMPLATE` to include the boot script in `<head>`**

Open `audio_dl_ui.py`. Find `_INDEX_TEMPLATE = """<!doctype html>` and replace through the `<title>audio-dl</title>` line with:

```python
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
(function() {
  const SLUGS = ['phosphor','rose','moon','dawn','amber','solarized','gruvbox','tokyo','atom','claude'];
  let chosen = null;
  try {
    const stored = localStorage.getItem('audio-dl-theme');
    if (stored && SLUGS.indexOf(stored) >= 0) chosen = stored;
  } catch (e) { /* localStorage unavailable; fall through */ }
  if (!chosen) {
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
      chosen = 'dawn';
    } else {
      chosen = 'phosphor';
    }
  }
  document.documentElement.dataset.theme = chosen;
})();
</script>
```

The rest of `_INDEX_TEMPLATE` (the `<style>...</style>` block + body) stays exactly as it was after Task 1.

- [ ] **Step 2: Verify the test for `_render_index()` substitution still passes**

The existing `index()` route still produces a valid page. Run:

```bash
pytest test_audio_dl_ui.py -v -k "Csrf or Index or btoa or Theme"
```

Expected: all relevant tests pass.

- [ ] **Step 3: Manual verification (browser, optional but recommended)**

If you have a dev environment running, start the UI and inspect:

```bash
audio-dl-ui --no-browser &
curl -s http://127.0.0.1:8000/ | grep -A2 'data-theme\|SLUGS'
kill %1
```

Expected: the boot script appears in the source, with the SLUGS array. Open in browser DevTools console and run `document.documentElement.dataset.theme` — should return `phosphor` (or `dawn` if your system prefers light + you have no stored value).

To verify localStorage path:

```js
localStorage.setItem('audio-dl-theme', 'rose');
location.reload();
// In console after reload:
document.documentElement.dataset.theme  // → "rose"
```

To clear and test default again:

```js
localStorage.removeItem('audio-dl-theme');
location.reload();
document.documentElement.dataset.theme  // → "phosphor" (or "dawn" if light-mode)
```

These are manual checks. No automated assertion — `data-theme` is set by client-side JS at runtime, not visible in server-rendered HTML beyond the script's source itself.

- [ ] **Step 4: Run the full suite + lint**

Run: `pytest -q`
Expected: 150 passed (no new tests, no regressions).

Run: `pylint $(git ls-files '*.py')`
Expected: 10.00/10.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py
git commit -m "$(cat <<'EOF'
feat(ui): synchronous boot script sets data-theme before paint

Inline <script> in <head> reads localStorage["audio-dl-theme"] (or
prefers-color-scheme=light → dawn; else phosphor) and sets
document.documentElement.dataset.theme before any body paint, avoiding
FOUC when the page swaps to TUI markup in Task 5.

Slug list is duplicated in the boot script rather than referencing
window.THEMES because THEMES lives in the deferred end-of-body script
and isn't yet defined when the boot script runs. Drift is unlikely
(both edited under the same task in practice) but acceptable risk for
zero-FOUC simplicity.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Replace HTML body + CSS base + JS event handlers with TUI structure

**Why now:** all infrastructure is in place — themes cascade, boot script applies one. This task flips the visual switch in one cohesive commit. After this, the page looks like the TUI mockup; before this, it still looks like macOS-light. There is no clean half-state.

**This is the largest task.** Three constants change: `_INDEX_CSS_BASE`, `_INDEX_HTML_BODY`, `_INDEX_JS` (just the SSE/event handlers; `THEMES` const stays as added in Task 3).

**Files:**
- Modify: `audio_dl_ui.py` (`_INDEX_CSS_BASE`, `_INDEX_HTML_BODY`, `_INDEX_JS`)

- [ ] **Step 1: Replace `_INDEX_CSS_BASE` with the TUI base CSS**

Find `_INDEX_CSS_BASE = """  :root { font-family:` (start of the constant from Task 1). Replace the entire constant with:

```python
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
```

- [ ] **Step 2: Replace `_INDEX_HTML_BODY` with the TUI markup**

Find `_INDEX_HTML_BODY = """<h1>audio-dl</h1>` (start of the constant from Task 1). Replace the entire constant with:

```python
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
```

The `__VERSION__` placeholder will be substituted by `_render_index()` — update that helper next.

- [ ] **Step 3: Add `__VERSION__` substitution to `_render_index()`**

Find the `_render_index()` function. Update it to inject the version:

```python
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
```

(`__version__` is already imported at the top of `audio_dl_ui.py` from the existing `from audio_dl import (..., __version__)` line.)

- [ ] **Step 4: Replace the SSE/event handler section of `_INDEX_JS` with TUI-aware versions**

The `THEMES` const at the top of `_INDEX_JS` (added in Task 3) stays. The IIFE that follows changes substantially. Find the line `(() => {` (the IIFE opener) inside `_INDEX_JS` and replace from there through the closing `})();` of `_INDEX_JS` with:

```python
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
  let counts = { done: 0, active: 0, fail: 0, total: 0 };

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
  }

  function setProgress(row, pct, extras) {
    const p = row.querySelector('.progress');
    if (pct == null) {
      p.textContent = extras || '';
      p.className = 'progress dim';
      return;
    }
    const filled = Math.round(pct / 100 * 18);
    const bar = '▓'.repeat(filled) + '░'.repeat(18 - filled);
    p.innerHTML = `<span class="bar-graph">${bar}</span> <span class="live">${pct.toFixed(1)}%</span>` + (extras ? ` <span class="dim">${extras}</span>` : '');
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
    if (u.status === 'pending' || u.status === 'queued') {
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

  function recountFromSnapshot(urls) {
    counts = { done: 0, active: 0, fail: 0, total: urls.length };
    urls.forEach(u => {
      if (u.status === 'completed') counts.done++;
      else if (u.status === 'downloading') counts.active++;
      else if (u.status === 'failed' || u.status === 'cancelled') counts.fail++;
    });
    refreshSummary();
  }

  function handleEvent(ev) {
    if (ev.type === 'job_snapshot') {
      ev.urls.forEach(u => {
        const row = rowFor(u.url);
        applyUrlState(row, u);
      });
      recountFromSnapshot(ev.urls);
      if (ev.complete) {
        $('submit').disabled = false;
        $('cancel').disabled = true;
      }
    } else if (ev.type === 'url_started') {
      const row = rowFor(ev.url);
      setGlyph(row, '[..]', 'live', true);
      setProgress(row, 0, '');
      counts.active++;
      refreshSummary();
    } else if (ev.type === 'progress') {
      const row = rowFor(ev.url);
      setGlyph(row, '[..]', 'live', true);
      setProgress(row, ev.percent, progressExtras(ev.speed, ev.eta));
    } else if (ev.type === 'url_completed') {
      const row = rowFor(ev.url);
      setGlyph(row, '[OK]', 'ok');
      setProgress(row, 100, '');
      addRevealButton(row, ev.paths);
      counts.active--; counts.done++;
      refreshSummary();
    } else if (ev.type === 'url_failed') {
      const row = rowFor(ev.url);
      const cancelled = ev.error === 'Cancelled';
      setGlyph(row, cancelled ? '[xx]' : '[!!]', 'err');
      setProgress(row, null, ev.error || 'failed');
      counts.active--; counts.fail++;
      refreshSummary();
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
    counts = { done: 0, active: 0, fail: 0, total: 0 };
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
})();
```

- [ ] **Step 5: Run the existing test suite — expect all 150 to pass**

Run: `pytest -q`

Expected: 150 passed. The endpoint contract didn't change — `index()` returns HTML, `/jobs` accepts the same JSON, SSE emits the same events, `/reveal` works the same. All existing tests pass without modification.

If the `TestBtoaUnicodeSafe` test fails, the `btoa(unescape(encodeURIComponent(url)))` pattern was lost in the rewrite — it must be present in the new `rowFor()`.

- [ ] **Step 6: Lint**

Run: `pylint $(git ls-files '*.py')`

Expected: 10.00/10.

- [ ] **Step 7: Manual verification (browser)**

```bash
audio-dl-ui --no-browser &
open http://127.0.0.1:8000/
```

Verify visually:
- Page renders with TUI box-drawing frame: `┌─ audio-dl ─── v1.4 ──── theme: phosphor ▾ ─┐`
- Phosphor green color scheme active (`#00ff88` accent on black bg)
- Form fields are inline with the frame, no rounded boxes, no white background
- Sliders have a green thumb
- "[ download ]" button looks like a TUI button
- DevTools: `document.documentElement.dataset.theme` returns `"phosphor"`

Submit a test job (e.g., `https://youtu.be/dQw4w9WgXcQ`):
- The job panel appears below the form
- The URL row shows `[--]` then `[..]` (pulsing) with an ASCII progress bar `▓▓▓▓░░░░░ 73.2% 2.4MB/s 0:12 left`
- On completion: `[OK]` and a `↗ Never Gonna...mp3` reveal button
- Summary updates: "1 done · 0 active · 0 fail"

If anything looks broken, fix in this commit (don't ship a broken UI). When done:

```bash
kill %1
```

- [ ] **Step 8: Commit**

```bash
git add audio_dl_ui.py
git commit -m "$(cat <<'EOF'
feat(ui): replace UI surface with TUI structure (Console direction)

Three constants rewritten:
- _INDEX_CSS_BASE: var(--bg/fg/accent/...) throughout, JetBrains Mono
  font stack with fallbacks, frame styling, slider/button/popover styles,
  prefers-reduced-motion opt-out for the live-pulse animation.
- _INDEX_HTML_BODY: TUI markup with real Unicode box-drawing chars
  (┌─ ┐ │ ├─ ┤ └─ ┘), inline labels (urls ▸, format ▸, etc.),
  job panel header with summary placeholder, theme: phosphor ▾ button
  in the frame header, hidden popover stub for Task 6.
- _INDEX_JS (IIFE body): SSE handlers render status glyphs
  ([OK] [..] [--] [!!] [xx]) + ASCII progress bars (▓▓▓░░░░ 73%) +
  panel summary counts (X done · Y active · Z fail). Pulse animation on
  active rows. New escapeHtml() helper for safe URL rendering.

Adds __VERSION__ substitution to _render_index() so the frame header
shows the current version.

Endpoint contract unchanged. All 150 existing tests pass without
modification — DOM structure changed, but the API surface (POST /jobs,
SSE event shapes, /reveal) is identical.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Wire the picker popover (open/close/search/select)

**Why now:** the popover DOM stub already exists (added in Task 5) and `THEMES` is in scope. This task adds the JS to populate the thumbnail grid and handle interactions.

**Files:**
- Modify: `audio_dl_ui.py` (`_INDEX_JS` — append picker code inside the IIFE)

- [ ] **Step 1: Append the picker code to the IIFE**

Open `audio_dl_ui.py`. Find the line `window.refreshThemeLabel = refreshThemeLabel;  // Picker (Task 6) calls this on change.` inside `_INDEX_JS`. Insert the picker block just after it (still inside the IIFE, before the closing `})();`):

```python
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
        // We grab them from a hidden temp <html data-theme=...> doesn't work,
        // so duplicate-source the colors here for preview fidelity.
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
    const get = v => cs.getPropertyValue(v).trim();
    const styles = {
      bg: get('--bg'), fg: get('--fg'), accent: get('--accent'),
      ok: get('--ok'), live: get('--live'), label: get('--label'),
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
```

- [ ] **Step 2: Run the test suite — expect all 150 to pass**

Run: `pytest -q`

Expected: 150 passed. (No new tests — picker has no JS test infra; verified manually.)

- [ ] **Step 3: Lint**

Run: `pylint $(git ls-files '*.py')`

Expected: 10.00/10.

- [ ] **Step 4: Manual verification (browser)**

```bash
audio-dl-ui --no-browser &
open http://127.0.0.1:8000/
```

Verify:
- Click `theme: phosphor ▾` button in the header → popover opens at top-right
- Search input is focused; type `rose` → only Rose Pine entries visible
- Clear search → all 10 thumbs visible, Phosphor highlighted with checkmark + accent border + `·default` tag
- Click `Rose Pine` → page recolors immediately to Rose Pine; popover closes; header shows `theme: rose ▾`
- Reload the page → still Rose Pine (localStorage)
- Reopen popover → Rose Pine has the active border now; Phosphor still has `·default`
- Click `Phosphor Green` → page returns to phosphor
- Open popover → press Escape → not yet bound (Task 7); click outside → popover closes ✓
- DevTools: `localStorage.getItem('audio-dl-theme')` reflects the active slug

When done:

```bash
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py
git commit -m "$(cat <<'EOF'
feat(ui): wire theme picker popover (open/close/search/select)

Click theme button → popover opens with thumbnail grid + search.
Each thumbnail is a tiny live preview using that theme's actual CSS
custom-property values (read via getComputedStyle on a temporary
data-theme swap, so off-active themes preview accurately). Click a
thumb → applyTheme() sets data-theme + writes localStorage + refreshes
the header label + redraws the grid (active marker shifts).

Click-outside (mousedown not in popover or trigger) closes. Esc-to-
close + ⌘T cycle + ⌘K open are wired in Task 7.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Add keyboard shortcuts (`⌘↵`, `esc`, `⌘T`, `⌘K`)

**Why now:** all the targets exist — submit form (Task 5), cancel button (Task 5), picker open/close (Task 6), theme cycling (uses `THEMES` from Task 3 + `applyTheme` from Task 6). This task wires the global key listener that dispatches to them.

**Files:**
- Modify: `audio_dl_ui.py` (`_INDEX_JS` — append global key handler inside the IIFE)

- [ ] **Step 1: Append the keyboard handler to the IIFE**

Find the line `closePopover();` in the click-outside handler (end of Task 6's additions). Append the keyboard block immediately after it, still inside the IIFE before `})();`:

```python
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
    if (cmdKey(e) && e.key === 'Enter') {
      if (!$('submit').disabled) {
        $('dl').dispatchEvent(new Event('submit', {cancelable: true}));
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
```

- [ ] **Step 2: Run the test suite — expect all 150 to pass**

Run: `pytest -q`

Expected: 150 passed.

- [ ] **Step 3: Lint**

Run: `pylint $(git ls-files '*.py')`

Expected: 10.00/10.

- [ ] **Step 4: Manual verification (browser)**

```bash
audio-dl-ui --no-browser &
open http://127.0.0.1:8000/
```

Test each shortcut:
- Paste a URL into the URLs textarea, press `⌘↵` (Mac) or `Ctrl+↵` (other) → form submits
- During an active download, press `esc` → cancel fires (job ends, button disables)
- Press `⌘T` repeatedly → theme cycles through all 10 (phosphor → rose → moon → dawn → amber → solarized → gruvbox → tokyo → atom → claude → phosphor)
- Press `⌘K` → popover opens with search input focused
- Inside popover, press arrow down/up → focus moves between thumbnails
- Press `enter` on a focused thumb → applies + closes
- Reopen popover, press `esc` → closes (job-cancel is suppressed because popover-close took priority)

Browser caveats to be aware of:
- macOS Safari may intercept `⌘T` for "new tab" before the page gets focus. If so, click on the page once and try again.
- Some browsers won't let `preventDefault` override `⌘K` (which is "address bar focus" in Chrome/Firefox). Acceptable degradation: user can still click the picker button.

When done:

```bash
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py
git commit -m "$(cat <<'EOF'
feat(ui): keyboard shortcuts (⌘↵ submit, esc cancel/close,
                                ⌘T cycle theme, ⌘K toggle picker)

Global keydown listener dispatches to existing handlers. esc has
priority routing: closes popover if open, otherwise clicks the
cancel button if an active job exists. ⌘T cycles themes inline
(no popover); ⌘K toggles the picker (open with search focused or
close if open). OS detection via navigator.platform decides
metaKey vs. ctrlKey.

Picker popover gains arrow-up/down keyboard navigation between
thumbnails and enter-to-select on the focused thumb.

Browser caveats documented in plan: Safari may intercept ⌘T,
Chrome/Firefox may intercept ⌘K — acceptable graceful degradation
since the picker button remains clickable.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Update `CLAUDE.md` to document the new structure

**Files:**
- Modify: `CLAUDE.md` — update `audio_dl_ui.py` Layout entry + add Convention bullets

- [ ] **Step 1: Update the `audio_dl_ui.py` Layout entry**

Open `CLAUDE.md`. Find the line starting `- [audio_dl_ui.py](audio_dl_ui.py) — optional FastAPI/uvicorn web UI sibling.` (around line 39). The whole entry currently runs ~25 lines. Append a new paragraph at the end of that entry (just before the line beginning `- [_app_entry.py]`):

```markdown
  v1.5 Console UI: the inline UI string is split into 5 constants —
  `_INDEX_TEMPLATE` (the shell), `_INDEX_CSS_BASE` (layout/components),
  `_INDEX_CSS_THEMES` (10 `:root[data-theme="<slug>"]` blocks), 
  `_INDEX_HTML_BODY` (TUI markup with real Unicode box-drawing chars),
  `_INDEX_JS` (THEMES registry at top + IIFE with handlers). Assembled
  by `_render_index(token, options, default_dir)`. The synchronous
  `<head>` boot script reads `localStorage["audio-dl-theme"]` (or
  `prefers-color-scheme: light` → `dawn`; else `phosphor`) and sets
  `documentElement.dataset.theme` before paint to avoid FOUC. Picker
  popover lives in the frame header. Keyboard: `⌘↵` submit, `esc`
  cancel/close-popover, `⌘T` cycle, `⌘K` toggle picker.
```

- [ ] **Step 2: Add a Convention bullet about the theme system**

Find the `## Conventions` section (near the bottom of `CLAUDE.md`). Append a new bullet:

```markdown
- Theme system (v1.5): adding a theme requires (a) a `:root[data-theme="<slug>"]` 
  block in `_INDEX_CSS_THEMES` defining all 12 CSS custom properties (`--bg`, 
  `--fg`, `--frame`, `--label`, `--accent`, `--ok`, `--err`, `--warn`, `--live`, 
  `--dim`, `--bar`, `--btn-fg`) and (b) a matching entry in the JS `THEMES` 
  array (top of `_INDEX_JS`) with the same `slug`. The slug also has to be in 
  the boot-script's `SLUGS` array in `_INDEX_TEMPLATE` (duplicated there because 
  the boot script runs in `<head>` before `_INDEX_JS`). Drift between the three
  places is caught by `TestThemeRendering` for the CSS↔JS axis; the boot-script
  duplicate is small enough to verify visually. See
  [docs/superpowers/specs/2026-05-14-console-ui-themes.md](docs/superpowers/specs/2026-05-14-console-ui-themes.md).
```

- [ ] **Step 3: Verify the changes**

Run: `grep -A1 "Console UI\|Theme system (v1.5)" CLAUDE.md`

Expected: both new blocks appear.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(CLAUDE.md): document v1.5 Console UI + theme system

Updates the audio_dl_ui.py Layout entry to describe the 5-constant
split (_INDEX_TEMPLATE / _CSS_BASE / _CSS_THEMES / _HTML_BODY /
_JS), the _render_index helper, the FOUC-avoiding boot script,
and the keyboard shortcuts.

Adds a Conventions bullet pinning the three-way contract for adding
a theme: CSS block + JS THEMES entry + boot-script SLUGS array.
Drift between CSS and JS is caught by tests; the boot-script
duplicate is small and visually verifiable.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Version bump (1.4 → 1.5) + CHANGELOG section

**Why last:** every other commit on this branch will be incorporated into v1.5. The CHANGELOG section is what the release workflow extracts on tag push, so it has to land before tagging.

**Files:**
- Modify: `audio_dl.py` — `__version__`
- Modify: `pyproject.toml` — `version`
- Modify: `CHANGELOG.md` — prepend new section

- [ ] **Step 1: Bump `audio_dl.py.__version__`**

Open `audio_dl.py`. Find line 31:

```python
__version__ = "1.4"
```

Change to:

```python
__version__ = "1.5"
```

- [ ] **Step 2: Bump `pyproject.toml` version**

Open `pyproject.toml`. Find line 7:

```toml
version = "1.4"
```

Change to:

```toml
version = "1.5"
```

- [ ] **Step 3: Verify versions match**

Run:

```bash
python -c "import re, pathlib; \
  py = re.search(r'__version__\s*=\s*[\"\\']([^\"\\']+)', pathlib.Path('audio_dl.py').read_text()).group(1); \
  toml = re.search(r'^version\s*=\s*[\"\\']([^\"\\']+)', pathlib.Path('pyproject.toml').read_text(), re.M).group(1); \
  assert py == toml == '1.5', f'mismatch: audio_dl.py={py} pyproject.toml={toml}'; \
  print(f'OK: both are {py}')"
```

Expected: `OK: both are 1.5`.

- [ ] **Step 4: Add the CHANGELOG section**

Open `CHANGELOG.md`. Find the existing `## v1.4 — Automated macOS release pipeline` header. Insert this new section **above** it (immediately below the file's `# Changelog` title, above the v1.4 section):

```markdown
## v1.5 — Console UI + theme system (2026-05-15)

Web UI redesign — replaces the macOS-system-light look with a
TUI-in-browser direction (Console aesthetic) plus a runtime theme
system with 10 themes selectable via a popover picker.

### Added
- **Console UI direction.** Real Unicode box-drawing frame
  (`┌─ ┐ │ ├─ ┤ └─ ┘`), JetBrains Mono font stack, status glyphs
  (`[OK]`, `[..]`, `[--]`, `[!!]`, `[xx]`), ASCII progress bars
  (`▓▓▓▓░░░░ 73%`), panel summary header (`X done · Y active · Z fail`).
  All component CSS goes through `var(--bg)`, `var(--fg)`, etc.
- **10 themes.** Phosphor Green (default), Rose Pine, Rose Pine Moon,
  Rose Pine Dawn (light), Amber CRT, Solarized Dark, Gruvbox Dark,
  Tokyo Night, Atom Dark Pro, Claude. Implemented as
  `:root[data-theme="<slug>"]` CSS-vars blocks + a JS `THEMES`
  registry. Theme persists to `localStorage["audio-dl-theme"]`.
- **Picker popover.** Anchored to the `theme: <slug> ▾` button in
  the TUI frame header. Search input + thumbnail grid; each
  thumbnail is a tiny live preview using that theme's actual colors.
- **Synchronous boot script.** Runs in `<head>` before paint;
  reads `localStorage` (or `prefers-color-scheme: light` → `dawn`;
  else `phosphor`) and sets `documentElement.dataset.theme` to
  avoid FOUC.
- **Keyboard shortcuts.** `⌘↵` submit, `esc` cancel job (or close
  popover if open), `⌘T` cycle themes inline, `⌘K` toggle picker
  with search focused. Picker grid supports arrow-up/down + enter.
- **Reduced-motion respect.** `[..]` pulse animation disabled
  under `prefers-reduced-motion: reduce`.

### Changed
- `audio_dl_ui.py` UI structure refactored from one ~280-line
  `_INDEX_HTML` string into five split constants
  (`_INDEX_TEMPLATE`, `_INDEX_CSS_BASE`, `_INDEX_CSS_THEMES`,
  `_INDEX_HTML_BODY`, `_INDEX_JS`) + `_render_index()` helper.
- `test_audio_dl_ui.py:870` (the UTF-8-safe `btoa` test) retargeted
  from `_INDEX_HTML` to `_INDEX_JS`.

### Decisions pinned (see [spec](docs/superpowers/specs/2026-05-14-console-ui-themes.md))
- TUI-in-browser, not "Linear with a nice icon."
- JetBrains Mono with `ui-monospace` fallback (no webfont CDN).
- Real Unicode box-drawing chars, not CSS-styled-to-look-TUI.
- Stays inline in `audio_dl_ui.py` — no static-files extraction
  (honors the CLAUDE.md sibling-file convention; no PyInstaller
  spec change).
- Drag-drop / clipboard paste / history / format presets / per-URL
  options bundled together as the deferred "new features" bucket
  for v1.6+ — out of scope for this slice.

### Test count
- 150 (was 147) — `TestThemeRendering` adds 3 tests; the
  refactor + status-glyph rewrite preserve every other test.
```

- [ ] **Step 5: Smoke-test the CHANGELOG extractor**

```bash
python scripts/extract_changelog.py v1.5
```

Expected: prints the body of the new v1.5 section (Added/Changed/Decisions/Test count). Should NOT include the `## v1.5` header line itself, and should stop before `## v1.4`.

Also try the `v1.5.0` fallback path:

```bash
python scripts/extract_changelog.py v1.5.0
```

Expected: same output (matches via the `.0`-strip fallback in `extract_changelog.py`).

- [ ] **Step 6: Run full tests + lint**

Run: `pytest -q`
Expected: 150 passed.

Run: `pylint $(git ls-files '*.py')`
Expected: 10.00/10.

- [ ] **Step 7: Commit**

```bash
git add audio_dl.py pyproject.toml CHANGELOG.md
git commit -m "$(cat <<'EOF'
release: v1.5 — Console UI + theme system

Bumps __version__ + pyproject.toml to 1.5. Adds the v1.5 CHANGELOG
section that the release workflow will extract verbatim on tag push
to public.

See docs/superpowers/specs/2026-05-14-console-ui-themes.md for the
design and docs/superpowers/plans/2026-05-15-console-ui-themes.md
for the implementation breakdown.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

**Spec coverage check:**

| Spec section | Implementation task |
|---|---|
| Visual: TUI structure, JetBrains Mono, box-drawing chars | Task 5 |
| Status glyphs ([OK], [..], [--], [!!], [xx]) | Task 5 |
| ASCII progress bars (`▓▓▓░░░`) | Task 5 |
| Panel summary header (X done · Y active · Z fail) | Task 5 |
| 10 theme CSS-vars blocks | Task 2 |
| THEMES JS registry (single source of truth) | Task 3 |
| Synchronous boot script in `<head>` | Task 4 |
| Picker popover (open/close/search/select) | Task 6 |
| Keyboard shortcuts (⌘↵, esc, ⌘T, ⌘K, arrows) | Task 7 |
| Reduced-motion opt-out for live pulse | Task 5 (CSS media query) |
| `localStorage["audio-dl-theme"]` persistence | Task 4 (boot reads) + Task 6 (applyTheme writes) |
| First-visit `prefers-color-scheme: light` → Dawn | Task 4 (boot logic) |
| Code organization: 5-constant split + `_render_index()` | Task 1 |
| `TestThemeRendering` (3 tests: blocks, registry, default) | Tasks 2 + 3 |
| Existing `_INDEX_HTML`-importing test retargeted | Task 1 |
| Pylint 10.00/10 | Every task lints before commit |
| `audio_dl.py` + `pyproject.toml` version bumps | Task 9 |
| CHANGELOG v1.5 section | Task 9 |
| `CLAUDE.md` updated for theme system + constant split | Task 8 |
| CLI behavior unchanged | Acceptance criterion — verified by all CLI tests still passing across all tasks |

All spec sections covered.

**Placeholder scan:** No "TBD" / "TODO" / "fill in" / "similar to Task N." Every code block in every step is complete.

**Type/name consistency check:**
- Constant names (`_INDEX_TEMPLATE`, `_INDEX_CSS_BASE`, `_INDEX_CSS_THEMES`, `_INDEX_HTML_BODY`, `_INDEX_JS`) used identically across Tasks 1–7.
- Helper name `_render_index(token, options, default_dir)` consistent in Tasks 1, 5.
- Theme slugs `{phosphor, rose, moon, dawn, amber, solarized, gruvbox, tokyo, atom, claude}` consistent across Tasks 2, 3, 4 (boot script SLUGS).
- CSS custom properties `--bg --fg --frame --label --accent --ok --err --warn --live --dim --bar --btn-fg` consistent between Task 2 (definitions) and Task 5 (consumers).
- DOM IDs `theme-btn`, `theme-current`, `theme-popover`, `pop-grid`, `pop-search`, `dl`, `submit`, `cancel`, `jobpanel`, `rows`, `urls`, `format`, `output_dir`, `playlist`, `force`, `jobs`, `fragments`, `jobs_val`, `fragments_val`, `job-summary` all consistent between Task 5 (markup) and Tasks 5/6/7 (handlers).
- Status glyph table from spec matches Task 5 implementation: `[OK]` (ok), `[..]` (live, pulses), `[--]` (dim), `[!!]` (err), `[xx]` (err).
- `applyTheme(slug)`, `closePopover()`, `openPopover()`, `renderThumbs(filter)` defined in Task 6, used in Task 7.
- `currentJobId`, `popover` (from Task 5/6) referenced in Task 7's keydown handler — both in scope inside the IIFE.

**Task count:** 9 tasks. ~50 discrete steps. Tasks 1–4 + 8–9 are 2–5 minute steps each; Tasks 5–7 have larger code drops (5 is the biggest, ~30 minutes including manual browser verification). Doable in one focused session or split across two.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-15-console-ui-themes.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
