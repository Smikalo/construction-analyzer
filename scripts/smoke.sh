#!/usr/bin/env bash
#
# End-to-end pipeline smoke test for construction-analyzer.
#
# Verifies in order:
#   1. backend /health   (process up)
#   2. backend /ready    (Ollama + Postgres + KB + checkpointer wired)
#   3. backend /api/chat/sync with a fresh thread_id (returns assistant reply)
#   4. backend /api/chat/sync again on the SAME thread_id (history grows)
#   5. backend /api/threads/{id}/history shows both turns persisted
#   6. frontend / (HTML responds 200 if frontend container is running)
#
# Usage:
#   ./scripts/smoke.sh                 # talks to localhost:8000 and :3000
#   BACKEND_URL=... FRONTEND_URL=... ./scripts/smoke.sh
#
# Compatible with bash 3.2 (default macOS) and bash 4+ (Linux).

set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"
TIMEOUT="${TIMEOUT:-90}"
CHAT_TIMEOUT="${CHAT_TIMEOUT:-180}"
SKIP_CHAT="${SKIP_CHAT:-0}"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m\xE2\x9C\x93\033[0m %s\n" "$*"; }
fail() { printf "  \033[31m\xE2\x9C\x97\033[0m %s\n" "$*" >&2; exit 1; }
info() { printf "  \033[2m%s\033[0m\n" "$*"; }

require() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

wait_for() {
  local url="$1" label="$2" deadline=$(( $(date +%s) + TIMEOUT ))
  while :; do
    if curl -fsS -o /dev/null --max-time 3 "$url"; then
      ok "$label reachable at $url"
      return
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      fail "$label not reachable at $url after ${TIMEOUT}s"
    fi
    sleep 2
  done
}

require curl
require python3

bold "[1/6] Backend liveness"
wait_for "$BACKEND_URL/health" "/health"

bold "[2/6] Backend readiness"
READY="$(curl -fsS "$BACKEND_URL/ready")"
echo "  $READY" | head -c 400; echo
STATUS="$(printf "%s" "$READY" | python3 -c 'import sys, json; print(json.load(sys.stdin)["status"])')"
case "$STATUS" in
  ready)    ok "ready" ;;
  degraded) info "degraded (continuing; smoke can still pass with FakeKB)" ;;
  *)        fail "unexpected /ready status: $STATUS" ;;
esac

THREAD_ID="smoke-$(date +%s)-$$"
if [ "$SKIP_CHAT" = "1" ]; then
  bold "[3-5/6] Chat round-trip (SKIPPED via SKIP_CHAT=1)"
  info "set SKIP_CHAT=0 (default) and ensure your LLM provider is reachable to exercise this leg"
else
  bold "[3/6] First chat turn (thread_id=$THREAD_ID, timeout ${CHAT_TIMEOUT}s)"
  info "first call may take a while if the LLM is loading (especially Ollama on CPU)"
  R1="$(curl -fsS --max-time "$CHAT_TIMEOUT" -X POST "$BACKEND_URL/api/chat/sync" \
    -H "Content-Type: application/json" \
    -d "{\"message\":\"smoke ping (turn 1)\",\"thread_id\":\"$THREAD_ID\"}")" \
    || fail "first chat turn failed (try OPENAI_API_KEY or run 'make pull-models', or set SKIP_CHAT=1)"
  CONTENT1="$(printf "%s" "$R1" | python3 -c 'import sys, json; print(json.load(sys.stdin)["message"]["content"])')"
  [ -n "$CONTENT1" ] || fail "empty assistant reply on first turn"
  ok "assistant replied: ${CONTENT1:0:60}..."

  bold "[4/6] Second chat turn on same thread"
  R2="$(curl -fsS --max-time "$CHAT_TIMEOUT" -X POST "$BACKEND_URL/api/chat/sync" \
    -H "Content-Type: application/json" \
    -d "{\"message\":\"smoke ping (turn 2)\",\"thread_id\":\"$THREAD_ID\"}")" \
    || fail "second chat turn failed"
  CONTENT2="$(printf "%s" "$R2" | python3 -c 'import sys, json; print(json.load(sys.stdin)["message"]["content"])')"
  [ -n "$CONTENT2" ] || fail "empty assistant reply on second turn"
  ok "assistant replied: ${CONTENT2:0:60}..."

  bold "[5/6] Thread history is persisted"
  HIST="$(curl -fsS "$BACKEND_URL/api/threads/$THREAD_ID/history")"
  COUNT="$(printf "%s" "$HIST" | python3 -c 'import sys, json; print(len(json.load(sys.stdin)["messages"]))')"
  [ "$COUNT" -ge 4 ] || fail "expected >=4 messages, got $COUNT"
  ok "$COUNT messages persisted in checkpointer for $THREAD_ID"
fi

bold "[6/6] Frontend reachable"
if curl -fsS -o /dev/null --max-time 5 "$FRONTEND_URL/api/health"; then
  ok "frontend /api/health responds"
elif curl -fsS -o /dev/null --max-time 5 "$FRONTEND_URL"; then
  ok "frontend / responds"
else
  info "frontend not reachable at $FRONTEND_URL (skipping; backend smoke still passed)"
fi

bold "ALL SMOKE CHECKS PASSED"
