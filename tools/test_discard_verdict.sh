#!/bin/bash
# Does a discarded annotation run wake someone only when they can act on it?
# (tools/discard_alert.py; wired into _worker_finish in tools/puzzle_worker.sh.)
#
#     bash tools/test_discard_alert.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
j() { python3 -I -c '
import sys, json; sys.path.insert(0, "tools")
import discard_alert as a
print(a.judge(sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3]), sys.argv[4]))' "$@"; }

PRE='["1A: definedByPreamble, but the puzzle has no preamble to define it."]'
FRAG='["2D: a block with no clueFragment is for letters the preamble supplies, and needs `gives`"]'
REAL='["3A: block fragment '"'x'"' not found in clue"]'
OTHER='["4A: the anagram letters do not match"]'

echo "a puzzle that cannot be mended is parked silently"
check "definedByPreamble, no preamble" "$(j g-1 "$PRE" '{}' "$d")" silent
check "no-clueFragment, no preamble" "$(j g-1 "$FRAG" '{}' "$d")" silent
check "awaitsPreamble, whatever the errors" "$(j g-1 "$REAL" '{"awaitsPreamble":true}' "$d")" silent
check "silent runs are not counted" "$([ -e "$d/counts.json" ] && echo yes || echo no)" no
check "a preamble-less error beside a real one is not silent" \
  "$(j g-2 '["1A: definedByPreamble, but the puzzle has no preamble","3A: wrong"]' '{}' "$d")" retry

echo "the first discard retries, the second alerts only for a new class"
check "first discard of g-3: retry" "$(j g-3 "$REAL" '{}' "$d")" retry
check "second discard of g-3: new class alerts" "$(j g-3 "$REAL" '{}' "$d")" alert
check "first discard of g-4 (same class): retry" "$(j g-4 "$REAL" '{}' "$d")" retry
check "second discard of g-4 (class seen): ledger only" "$(j g-4 "$REAL" '{}' "$d")" ledger
check "another class on a second discard alerts" "$(j g-5 "$OTHER" '{}' "$d")$(j g-5 "$OTHER" '{}' "$d")" "retryalert"
check "the ledger holds a line per discard" "$(wc -l <"$d/discards.log" | tr -d ' ')" 7

echo "success clears the count"
python3 -I tools/discard_alert.py clear g-3 --dir "$d"
check "g-3 retries again after it annotated" "$(j g-3 "$REAL" '{}' "$d")" retry

echo "wired in: only the alert verdict wakes"
check "alert is gated on the verdict" "$(grep -c '"\$verdict" = alert \] && alert "\$what \$id was discarded' tools/puzzle_worker.sh)" 1

[ "$fails" = 0 ] && echo "discard alert: all checks passed" || echo "discard alert: $fails FAILED"
exit $((fails > 0))
