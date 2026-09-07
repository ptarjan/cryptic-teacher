#!/bin/bash
# Does a failed annotation resume, or does it start over and pay twice?
#
# The retry in daily_update.sh only ever runs when a nightly job is already
# going wrong, which is the worst place to find out it was wired up wrong. So
# this drives it with a fake `claude`: the block under test is READ OUT OF
# daily_update.sh by its own first and last lines rather than copied here, so a
# copy cannot drift away from the thing that runs at 06:15.
#
#     bash tools/test_annotate_retry.sh
#
# Four cases, and the last two are the ones that matter: a run cut off for
# overrunning the output ceiling must come back with --resume and the SAME
# session id, because everything it had read and worked out is in that
# conversation and nowhere else — and a puzzle whose conversation survived the
# night it died in must resume THAT, rather than opening a fresh one and paying
# for the grid, the wordplay and half the annotation a second time.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

block=$(awk '/^      ann_sid=\$\(session_id\)/,/^      done$/' tools/daily_update.sh)
[ -n "$block" ] || { echo "FAIL: the retry block is no longer where this test reads it from"; exit 1; }

stub=$(mktemp -d)
trap 'rm -rf "$stub"' EXIT
# A claude that records how it was called and fails the way $MODE says.
cat > "$stub/claude" <<'STUB'
#!/bin/bash
n=$(cat "$CALLS/n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$CALLS/n"
printf '%s\n' "$*" >> "$CALLS/argv"
if [ "$n" = 1 ] && [ -n "${MODE:-}" ]; then
  [ "$MODE" = overrun ] && echo "API Error: Claude's response exceeded the 128000 output token maximum."
  [ "$MODE" = limit ] && echo "Claude AI usage limit reached"
  exit 1
fi
echo "done"
STUB
chmod +x "$stub/claude"
PATH="$stub:$PATH"

run() {  # $1 = MODE ("" for a clean first run), $2 = a session the ledger holds
  CALLS=$(mktemp -d); export CALLS MODE="$1"
  # A scratch ledger, always — never the corpus's own, and never absent: the
  # block asks it for last night's session on every puzzle it annotates.
  export ANNOTATE_ATTEMPTS_FILE="$stub/ledger.json"
  printf '{"puzzles": {%s}}\n' \
    "${2:+\"test-1\": {\"attempts\": 1, \"session\": \"$2\"}}" > "$ANNOTATE_ATTEMPTS_FILE"
  . tools/claude_session.sh
  local ANNOTATE_MODEL=opus ann_tools=Read ann_turns=80 num=test-1 run_log
  local CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000 ANNOTATE_RETRY_CEILING=200000
  local ann_sids="" ann_prior
  local ann_task="Annotate." ann_sid ann_sess ann_ceiling ann_prompt ann_ok ann_retried
  run_log=$(mktemp)
  # session_exists must say yes, since the fake CLI writes no transcript.
  session_exists() { [ -n "${1:-}" ]; }
  eval "$block" >/dev/null 2>&1
  calls=$(cat "$CALLS/n"); argv=$(cat "$CALLS/argv"); ok="$ann_ok"
  rm -rf "$CALLS" "$run_log"
}

echo "a clean run is one call and no resume"
run "" ""
check "calls" "$calls" "1"
check "succeeded" "${ok:-no}" "1"
check "no --resume" "$(grep -c -- --resume <<<"$argv")" "0"

echo "a usage lockout is not retried — it wants the next window, not another try"
run limit
check "calls" "$calls" "1"
check "failed" "${ok:-no}" "no"

echo "an output overrun resumes the same conversation instead of starting over"
run overrun
check "calls" "$calls" "2"
check "succeeded on the retry" "${ok:-no}" "1"
sid=$(sed -n '1s/.*--session-id \([^ ]*\).*/\1/p' <<<"$argv")
check "second call resumed the first's session" \
  "$(sed -n '2s/.*--resume \([^ ]*\).*/\1/p' <<<"$argv")" "$sid"
check "and it did not start a new one" "$(sed -n 2p <<<"$argv" | grep -c -- --session-id)" "0"

echo "a puzzle that died last night resumes that night's session, not a fresh one"
run "" last-nights-session
check "calls" "$calls" "1"
check "resumed it" "$(sed -n '1s/.*--resume \([^ ]*\).*/\1/p' <<<"$argv")" "last-nights-session"
check "and opened no new conversation" "$(grep -c -- --session-id <<<"$argv")" "0"

[ "$fails" = 0 ] && echo "annotate retry: all checks passed" || echo "annotate retry: $fails FAILED"
exit $((fails > 0))
