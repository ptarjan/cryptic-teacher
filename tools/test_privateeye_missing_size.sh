#!/bin/bash
# Does tools/clue_repair.fill_missing_sizes give a plain light whose
# count the OCR lost the length of the answer the next issue printed, and leave
# a linked light's length to its group? (Cyclops No 164's 17ac.)
#
#     bash tools/test_privateeye_missing_size.sh
#
# Offline.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {
  if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: want [$2] got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import clue_repair as pw

across = [[1, 5, "plain"], [17, None, "plain"], [11, None, "linked"], [20, None, "plain"]]
down = [[17, None, "plain"], [2, 4, "plain"]]
given = {("17", "across"): "TUTSI", ("11", "across"): "SUMMER", ("2", "down"): "ABCDEFG"}
pw.fill_missing_sizes(across, down, given)
print("ACROSS", [x[1] for x in across])
print("DOWN", [x[1] for x in down])
PY
)
check "a plain light's lost count takes the answer's length; linked, unanswered and counted lights keep theirs" \
  "ACROSS [5, 5, None, None]
DOWN [None, 4]" "$out"
[ "$fails" = 0 ] && echo "all ok" || exit 1
