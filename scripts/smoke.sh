#!/usr/bin/env bash
#
# End-to-end pipeline smoke test for construction-analyzer.
#
# Verifies in order:
#   1. backend /health   (process up)
#   2. backend /ready    (Ollama + Postgres + KB + checkpointer wired)
#   3. backend /api/reports bootstrap/inspection/gate cancellation
#   4. backend /api/chat/sync with a fresh thread_id (returns assistant reply)
#   5. backend /api/chat/sync again on the SAME thread_id (history grows)
#   6. backend /api/threads/{id}/history shows both turns persisted
#   7. frontend / (HTML responds 200 if frontend container is running)
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

assert_report_launch_response() {
  python3 - <<'PY'
import json
import os


def require(condition, message):
    if not condition:
        raise SystemExit(f"report launch assertion failed: {message}")


body = json.loads(os.environ["REPORT_JSON"])
expected_session_id = os.environ["REPORT_SESSION_ID"]
require(body.get("session_id") == expected_session_id, "unexpected session_id")
require(body.get("status") == "blocked", "expected status=blocked")
require(body.get("current_stage") == "bootstrap", "expected current_stage=bootstrap")
require(body.get("resumed") is False, "expected a new report session")
print(
    "session_id={session_id} status={status} stage={stage}".format(
        session_id=body["session_id"],
        status=body["status"],
        stage=body["current_stage"],
    )
)
PY
}

assert_report_bootstrap_inspection() {
  python3 - <<'PY'
import json
import os


def require(condition, message):
    if not condition:
        raise SystemExit(f"report inspection assertion failed: {message}")


body = json.loads(os.environ["REPORT_JSON"])
expected_session_id = os.environ["REPORT_SESSION_ID"]
session = body.get("session") or {}
require(session.get("session_id") == expected_session_id, "unexpected session_id")
require(session.get("status") == "blocked", "expected session.status=blocked")
require(body.get("current_stage") == "bootstrap", "expected current_stage=bootstrap")

collections = {
    "stages": body.get("stages"),
    "gates": body.get("gates"),
    "artifacts": body.get("artifacts"),
    "validation_findings": body.get("validation_findings"),
    "exports": body.get("exports"),
    "recent_logs": body.get("recent_logs"),
}
for name, value in collections.items():
    require(isinstance(value, list), f"{name} is not a JSON array")

stages = collections["stages"]
gates = collections["gates"]
recent_logs = collections["recent_logs"]
require(any(stage.get("name") == "bootstrap" for stage in stages), "missing bootstrap stage")
require(
    any(
        gate.get("gate_id") == "report_template_confirmation" and gate.get("status") == "open"
        for gate in gates
    ),
    "missing open report_template_confirmation gate",
)
require(len(recent_logs) >= 1, "missing recent log entry")
print(
    "session_id={session_id} status={status} stages={stages} gates={gates} "
    "logs={logs} artifacts={artifacts} findings={findings} exports={exports}".format(
        session_id=expected_session_id,
        status=session["status"],
        stages=len(stages),
        gates=len(gates),
        logs=len(recent_logs),
        artifacts=len(collections["artifacts"]),
        findings=len(collections["validation_findings"]),
        exports=len(collections["exports"]),
    )
)
PY
}

assert_report_complete_inspection() {
  python3 - <<'PY'
import json
import os


def require(condition, message):
    if not condition:
        raise SystemExit(f"report completion assertion failed: {message}")


body = json.loads(os.environ["REPORT_JSON"])
expected_session_id = os.environ["REPORT_SESSION_ID"]
session = body.get("session") or {}
stages = body.get("stages")
gates = body.get("gates")
recent_logs = body.get("recent_logs")
require(session.get("session_id") == expected_session_id, "unexpected session_id")
require(session.get("status") == "complete", "expected session.status=complete")
require(body.get("current_stage") in (None, ""), "expected no current stage after cancel")
require(isinstance(stages, list), "stages is not a JSON array")
require(isinstance(gates, list), "gates is not a JSON array")
require(isinstance(recent_logs, list), "recent_logs is not a JSON array")
require(any(stage.get("name") == "bootstrap" for stage in stages), "missing bootstrap stage")
require(
    any(
        gate.get("gate_id") == "report_template_confirmation" and gate.get("status") == "closed"
        for gate in gates
    ),
    "missing closed report_template_confirmation gate",
)
require(not any(gate.get("status") == "open" for gate in gates), "report smoke left an open gate")
print(
    "session_id={session_id} status={status} stages={stages} gates={gates} logs={logs}".format(
        session_id=expected_session_id,
        status=session["status"],
        stages=len(stages),
        gates=len(gates),
        logs=len(recent_logs),
    )
)
PY
}

probe_report_exports_dir() {
  python3 - <<'PY'
import os
from pathlib import Path

root = os.environ.get("REPORT_EXPORTS_DIR", "")
try:
    directory = Path(root)
    if not directory.is_dir():
        raise RuntimeError("not an existing directory")
    probe = directory / f".smoke-export-probe-{os.getpid()}"
    probe.write_text("smoke export probe\n", encoding="utf-8")
    if not probe.is_file():
        raise RuntimeError("probe file was not created")
    probe.unlink()
except Exception as exc:  # noqa: BLE001 - this is a bounded smoke diagnostic
    raise SystemExit(f"REPORT_EXPORTS_DIR write/delete probe failed: {type(exc).__name__}") from exc
PY
}

require curl
require python3

bold "[1/7] Backend liveness"
wait_for "$BACKEND_URL/health" "/health"

bold "[2/7] Backend readiness"
READY="$(curl -fsS --max-time "$TIMEOUT" "$BACKEND_URL/ready")"
echo "  $READY" | head -c 400; echo
STATUS="$(printf "%s" "$READY" | python3 -c 'import sys, json; print(json.load(sys.stdin)["status"])')"
case "$STATUS" in
  ready)    ok "ready" ;;
  degraded) info "degraded (continuing; smoke can still pass with FakeKB)" ;;
  *)        fail "unexpected /ready status: $STATUS" ;;
esac

bold "[3/7] Report session bootstrap and gate cancellation"
REPORT_SESSION_ID="smoke-report-$(date +%s)-$$"
REPORT_LAUNCH="$(curl -fsS --max-time "$TIMEOUT" -X POST "$BACKEND_URL/api/reports" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$REPORT_SESSION_ID\",\"metadata\":{\"source\":\"scripts/smoke.sh\",\"purpose\":\"report-bootstrap-smoke\"}}")" \
  || fail "report session launch failed"
REPORT_LAUNCH_SUMMARY="$(REPORT_JSON="$REPORT_LAUNCH" REPORT_SESSION_ID="$REPORT_SESSION_ID" assert_report_launch_response)" \
  || fail "report launch response did not match expected bootstrap shape"
ok "$REPORT_LAUNCH_SUMMARY"

REPORT_INSPECTION="$(curl -fsS --max-time "$TIMEOUT" "$BACKEND_URL/api/reports/$REPORT_SESSION_ID")" \
  || fail "report session inspection failed before gate cancellation"
REPORT_INSPECTION_SUMMARY="$(REPORT_JSON="$REPORT_INSPECTION" REPORT_SESSION_ID="$REPORT_SESSION_ID" assert_report_bootstrap_inspection)" \
  || fail "report bootstrap inspection did not match expected shape"
ok "$REPORT_INSPECTION_SUMMARY"

curl -fsS --max-time "$TIMEOUT" -o /dev/null -X POST \
  "$BACKEND_URL/api/reports/$REPORT_SESSION_ID/gates/report_template_confirmation/answer" \
  -H "Content-Type: application/json" \
  -d '{"answer":{"choice":"cancel"}}' \
  || fail "report gate cancellation failed"

REPORT_AFTER_CANCEL="$(curl -fsS --max-time "$TIMEOUT" "$BACKEND_URL/api/reports/$REPORT_SESSION_ID")" \
  || fail "report session inspection failed after gate cancellation"
REPORT_AFTER_CANCEL_SUMMARY="$(REPORT_JSON="$REPORT_AFTER_CANCEL" REPORT_SESSION_ID="$REPORT_SESSION_ID" assert_report_complete_inspection)" \
  || fail "report completion inspection did not match expected shape"
ok "$REPORT_AFTER_CANCEL_SUMMARY"

if [ -n "${REPORT_EXPORTS_DIR:-}" ]; then
  probe_report_exports_dir || fail "REPORT_EXPORTS_DIR write/delete probe failed"
  ok "REPORT_EXPORTS_DIR write/delete probe passed"
else
  info "REPORT_EXPORTS_DIR not set; skipping local export directory write/delete probe"
fi

THREAD_ID="smoke-$(date +%s)-$$"
if [ "$SKIP_CHAT" = "1" ]; then
  bold "[4-6/7] Chat round-trip (SKIPPED via SKIP_CHAT=1)"
  info "set SKIP_CHAT=0 (default) and ensure your LLM provider is reachable to exercise this leg"
else
  bold "[4/7] First chat turn (thread_id=$THREAD_ID, timeout ${CHAT_TIMEOUT}s)"
  info "first call may take a while if the LLM is loading (especially Ollama on CPU)"
  R1="$(curl -fsS --max-time "$CHAT_TIMEOUT" -X POST "$BACKEND_URL/api/chat/sync" \
    -H "Content-Type: application/json" \
    -d "{\"message\":\"smoke ping (turn 1)\",\"thread_id\":\"$THREAD_ID\"}")" \
    || fail "first chat turn failed (try OPENAI_API_KEY or run 'make pull-models', or set SKIP_CHAT=1)"
  CONTENT1="$(printf "%s" "$R1" | python3 -c 'import sys, json; print(json.load(sys.stdin)["message"]["content"])')"
  [ -n "$CONTENT1" ] || fail "empty assistant reply on first turn"
  ok "assistant replied: ${CONTENT1:0:60}..."

  bold "[5/7] Second chat turn on same thread"
  R2="$(curl -fsS --max-time "$CHAT_TIMEOUT" -X POST "$BACKEND_URL/api/chat/sync" \
    -H "Content-Type: application/json" \
    -d "{\"message\":\"smoke ping (turn 2)\",\"thread_id\":\"$THREAD_ID\"}")" \
    || fail "second chat turn failed"
  CONTENT2="$(printf "%s" "$R2" | python3 -c 'import sys, json; print(json.load(sys.stdin)["message"]["content"])')"
  [ -n "$CONTENT2" ] || fail "empty assistant reply on second turn"
  ok "assistant replied: ${CONTENT2:0:60}..."

  bold "[6/7] Thread history is persisted"
  HIST="$(curl -fsS --max-time "$TIMEOUT" "$BACKEND_URL/api/threads/$THREAD_ID/history")"
  COUNT="$(printf "%s" "$HIST" | python3 -c 'import sys, json; print(len(json.load(sys.stdin)["messages"]))')"
  [ "$COUNT" -ge 4 ] || fail "expected >=4 messages, got $COUNT"
  ok "$COUNT messages persisted in checkpointer for $THREAD_ID"
fi

bold "[7/7] Frontend reachable"
if curl -fsS -o /dev/null --max-time 5 "$FRONTEND_URL/api/health"; then
  ok "frontend /api/health responds"
elif curl -fsS -o /dev/null --max-time 5 "$FRONTEND_URL"; then
  ok "frontend / responds"
else
  info "frontend not reachable at $FRONTEND_URL (skipping; backend smoke still passed)"
fi

bold "ALL SMOKE CHECKS PASSED"
