#!/bin/bash
# Does the alert a dead annotation sends actually carry the evidence?
#
#     bash tools/test_annotate_postmortem.sh
#
# Two halves, and they fail for different reasons. The first drives
# annotate_postmortem.py over a transcript built here, so the shape it reports
# is checked against a run whose facts this file knows. The second reads
# annotate_alert OUT of daily_update.sh and calls it, because a post-mortem
# nothing invokes is the same as no post-mortem — which is what the nightly
# had until 2026-09-12: it recorded "ran past 90m" and told nobody.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
check() { if grep -qF -- "$2" <<<"$1"; then echo "  ok: $3"; else
  echo "  FAIL: $3"$'\n'"    wanted to find: $2"$'\n'"    in: $1"; fails=$((fails + 1)); fi; }

work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
sid=00000000-dead-0000-0000-000000000000
mkdir -p "$work/projects/test"
# A run the shape of independent-12459: one turn that read a file, then a turn
# that spent the whole output ceiling on thinking and called nothing.
{
  printf '{"type":"assistant","timestamp":"2026-09-12T12:00:00Z","message":{"id":"m1","stop_reason":"tool_use","usage":{"output_tokens":900,"output_tokens_details":{"thinking_tokens":400}},"content":[{"type":"tool_use","name":"Read","input":{"file_path":"puzzles/independent-12459.js"}}]}}\n'
  printf '{"type":"assistant","timestamp":"2026-09-12T13:21:00Z","message":{"id":"m2","stop_reason":"max_tokens","usage":{"output_tokens":128000,"output_tokens_details":{"thinking_tokens":127997}},"content":[{"type":"thinking","thinking":"","signature":"xx"}]}}\n'
} > "$work/projects/test/$sid.jsonl"

echo "the post-mortem names the ceiling turns, the clock and the transcript"
out=$(CLAUDE_CONFIG_DIR="$work" python3 tools/annotate_postmortem.py "$sid" --puzzle independent-12459)
check "$out" "independent-12459 — 2 turn(s) over 1h21m" "turns and wall clock"
check "$out" "1 turn(s) hit the 128,000-token output ceiling" "the turn that bought nothing"
check "$out" "128,000 tokens bought nothing" "what it cost"
check "$out" "peak thinking in one turn: 127,997 tokens" "thinking read from usage, not from the block"
check "$out" "last tool call: Read puzzles/independent-12459.js" "what it was doing"
check "$out" "$sid.jsonl" "where to go next"

echo "a session that was never written does not turn one failure into two"
out=$(CLAUDE_CONFIG_DIR="$work" python3 tools/annotate_postmortem.py no-such-session 2>&1); rc=$?
check "$out" "no transcript for session no-such-session" "says so plainly"
[ "$rc" = 0 ] && echo "  ok: exits 0" || { echo "  FAIL: exited $rc, so it would take the nightly down with it"; fails=$((fails + 1)); }

echo "daily_update.sh's annotate_alert sends that post-mortem, not a pointer to it"
block=$(awk '/^annotate_alert\(\) \{/,/^\}$/' tools/daily_update.sh)
[ -n "$block" ] || { echo "  FAIL: annotate_alert is no longer where this test reads it from"; exit 1; }
sent=""; stop_alerted=""
alert() { sent="$*"; }
eval "$block"
CLAUDE_CONFIG_DIR="$work" annotate_alert independent-12459 "independent-12459 ran past 90m" "$sid"
check "$sent" "independent-12459 ran past 90m" "the headline"
check "$sent" "1 turn(s) hit the 128,000-token output ceiling" "and the evidence under it"
check "$sent" '```' "fenced, so the channel renders it"
[ -n "$stop_alerted" ] && echo "  ok: marks the failure as already reported" || {
  echo "  FAIL: stop_alerted unset, so the run summary will report it a second time"; fails=$((fails + 1)); }

[ "$fails" = 0 ] && echo "annotate post-mortem: all checks passed" || echo "annotate post-mortem: $fails FAILED"
exit $((fails > 0))
