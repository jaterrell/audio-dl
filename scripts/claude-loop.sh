#!/usr/bin/env bash
#
# claude-loop.sh — a loop that prompts Claude, so you don't have to.
#
# The Boris pattern: this script is the control layer; `claude -p` (the
# Agent SDK) is the engine. The loop feeds verification results back to
# the agent until the verify command exits 0, or a safety rail trips.
#
# Usage:
#   claude-loop.sh -g "goal prompt" -v "verify command" [options]
#
# Example:
#   claude-loop.sh \
#     -g "Make all tests pass. Do not modify the tests themselves." \
#     -v "npm test" \
#     -t "Bash(npm test *),Read,Edit" \
#     -n 8 -c 3.00
#
# Options:
#   -g  Goal prompt (required)
#   -v  Verify command; loop stops when it exits 0 (required)
#   -t  --allowedTools value (default: "Read,Edit,Bash")
#   -n  Max iterations (default: 10)
#   -c  Cost cap in USD, cumulative across iterations (default: 5.00)
#   -m  Model (optional; omit to use your default)
#   -b  Pass --bare (skip hooks/skills/CLAUDE.md; reproducible CI runs)
#
# Requirements: claude (Claude Code CLI), jq
set -euo pipefail

GOAL="" VERIFY="" TOOLS="Read,Edit,Bash" MAX_ITERS=10 COST_CAP="5.00"
MODEL="" BARE=""

while getopts "g:v:t:n:c:m:b" opt; do
  case "$opt" in
    g) GOAL="$OPTARG" ;;
    v) VERIFY="$OPTARG" ;;
    t) TOOLS="$OPTARG" ;;
    n) MAX_ITERS="$OPTARG" ;;
    c) COST_CAP="$OPTARG" ;;
    m) MODEL="$OPTARG" ;;
    b) BARE="--bare" ;;
    *) exit 2 ;;
  esac
done

[[ -z "$GOAL" || -z "$VERIFY" ]] && {
  echo "error: -g <goal> and -v <verify command> are required" >&2; exit 2; }
command -v claude >/dev/null || { echo "error: claude not on PATH" >&2; exit 2; }
command -v jq >/dev/null || { echo "error: jq not on PATH" >&2; exit 2; }

LOG_DIR=".claude-loop"
mkdir -p "$LOG_DIR"
RUN_LOG="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S).log"

SESSION_ID=""
TOTAL_COST="0"

log() { printf '%s\n' "$*" | tee -a "$RUN_LOG"; }

run_verify() {
  # Capture verify output (truncated) to feed back to the agent.
  set +e
  VERIFY_OUT="$("$SHELL" -c "$VERIFY" 2>&1 | tail -c 4000)"
  VERIFY_RC=$?
  set -e
}

# Iteration 0: check whether the goal is already met.
run_verify
if [[ $VERIFY_RC -eq 0 ]]; then
  log "verify already passes; nothing to do."
  exit 0
fi

for (( i=1; i<=MAX_ITERS; i++ )); do
  log "=== iteration $i/$MAX_ITERS (cost so far: \$$TOTAL_COST) ==="

  if [[ -z "$SESSION_ID" ]]; then
    PROMPT="Goal: $GOAL

Definition of done: the command \`$VERIFY\` exits 0. Latest output:
$VERIFY_OUT

Work toward the goal. I will run the verify command after your turn."
    SESSION_ARGS=()
  else
    PROMPT="Verify command \`$VERIFY\` still failing (exit $VERIFY_RC). Output:
$VERIFY_OUT

Continue working toward the goal."
    SESSION_ARGS=(--resume "$SESSION_ID")
  fi

  MODEL_ARGS=()
  [[ -n "$MODEL" ]] && MODEL_ARGS=(--model "$MODEL")

  set +e
  RESP="$(claude -p "$PROMPT" $BARE \
    --allowedTools "$TOOLS" \
    --max-turns 25 \
    --output-format json \
    ${SESSION_ARGS[@]+"${SESSION_ARGS[@]}"} \
    ${MODEL_ARGS[@]+"${MODEL_ARGS[@]}"} 2>>"$RUN_LOG")"
  CLAUDE_RC=$?
  set -e

  if [[ $CLAUDE_RC -ne 0 || -z "$RESP" ]]; then
    log "claude exited non-zero ($CLAUDE_RC); see $RUN_LOG. Aborting."
    exit 1
  fi

  SESSION_ID="$(jq -r '.session_id // empty' <<<"$RESP")"
  ITER_COST="$(jq -r '.total_cost_usd // 0' <<<"$RESP")"
  TOTAL_COST="$(awk -v a="$TOTAL_COST" -v b="$ITER_COST" 'BEGIN{printf "%.4f", a+b}')"
  jq -r '.result // empty' <<<"$RESP" | tee -a "$RUN_LOG"

  # The honest stop condition: the verifier, not the model. Check before
  # the cost rail so a goal reached on the final dollar still counts.
  run_verify
  if [[ $VERIFY_RC -eq 0 ]]; then
    log "=== DONE: verify passed after $i iteration(s). Total cost: \$$TOTAL_COST ==="
    log "Session: $SESSION_ID (resume with: claude --resume $SESSION_ID)"
    exit 0
  fi

  # Safety rail: cumulative cost ceiling.
  if awk -v t="$TOTAL_COST" -v cap="$COST_CAP" 'BEGIN{exit !(t>cap)}'; then
    log "cost cap exceeded (\$$TOTAL_COST > \$$COST_CAP). Aborting."
    exit 1
  fi
done

log "=== FAILED: hit iteration cap ($MAX_ITERS) without passing verify. Cost: \$$TOTAL_COST ==="
log "Session: $SESSION_ID (inspect with: claude --resume $SESSION_ID)"
exit 1
