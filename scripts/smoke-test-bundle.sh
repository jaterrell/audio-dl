#!/usr/bin/env bash
# Smoke-test the built .app by launching it headless and verifying the
# embedded uvicorn binds on 127.0.0.1:8000 within a budget. Catches the
# silent failure mode "bundle launches and ad-hoc-signs cleanly but won't
# serve HTTP" before the release workflow uploads it.
#
# Invoked by .github/workflows/release.yml between build-app.sh and
# package-release.sh.
#
# Prerequisite: _app_entry.py preserves --no-browser argv (Phase 4 refactor).

set -euo pipefail

BIN="dist/audio-dl.app/Contents/MacOS/audio-dl"
if [[ ! -x "$BIN" ]]; then
    echo "ERROR: ${BIN} not found or not executable." >&2
    exit 1
fi

LOG="$(mktemp -t audio-dl-smoke.XXXXXX)"
trap 'rm -f "$LOG"' EXIT

echo "Launching bundle headless: $BIN --no-browser"
"$BIN" --no-browser >"$LOG" 2>&1 &
PID=$!

# Ensure we kill the bundle no matter how we exit.
cleanup() {
    if kill -0 "$PID" 2>/dev/null; then
        kill -TERM "$PID" 2>/dev/null || true
        # Give it 5s to shut down cleanly, then escalate.
        for _ in 1 2 3 4 5; do
            if ! kill -0 "$PID" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        kill -KILL "$PID" 2>/dev/null || true
    fi
    rm -f "$LOG"
}
trap cleanup EXIT

# Poll for HTTP 200 on the UI root for up to 30s.
for i in $(seq 1 30); do
    if curl -fsS -o /dev/null http://127.0.0.1:8000/; then
        echo "Smoke test PASSED (uvicorn bound on :8000 within ${i}s)."
        exit 0
    fi
    sleep 1
done

echo "Smoke test FAILED: bundle did not respond on :8000 within 30s." >&2
echo "--- last 50 lines of bundle stderr ---" >&2
tail -n 50 "$LOG" >&2 || true
exit 1
