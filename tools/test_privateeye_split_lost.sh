#!/bin/bash
# Does tools/privateeye_wayback.split_lost split a clue the OCR ran into the
# one before it, only at a number the lists skip? (Cyclops Nos 71, 96, 98, 111, 113.)
#
#     bash tools/test_privateeye_split_lost.sh
#
# Offline.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {
  if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: want [$2] got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import privateeye_wayback as pw


def r(n, clue, enum):
    return {"number": n, "clue": clue, "enumeration": enum}


def show(a, d):
    return [(x["number"], x["clue"], x["enumeration"]) for x in a + d]


# A lost count: 15's "(6)" is 17's, the numbers skip 17.
a = [r("1", "One", "4"), r("15", "Action at one time 17 Go down sportingly", "6"), r("18", "Eighteen", "5")]
d = [r("2", "Two", "3"), r("16", "Sixteen", "4")]
a2, d2 = pw.split_lost([x.copy() for x in a], [x.copy() for x in d])
print("LOST", show(a2, d2)[1:3])

# A cross-reference with no count, run into the next clue.
a = [r("1", "One", "4"), r("5", "Five", "5")]
d = [r("2", "(sce 4) 3 Supported while bestowing", "4"), r("6", "Six", "5")]
a2, d2 = pw.split_lost([x.copy() for x in a], [x.copy() for x in d])
print("SEE", show(a2, d2))

# A count inside the text: the row's own is the later clue's.
a = [r("%d" % n, "Clue", "4") for n in (1, 3, 5, 7, 9)] + [r("10", "Quite able (7) 1] Those who have been honoured", "5")]
d = [r("%d" % n, "Clue", "4") for n in (2, 4, 6, 8, 12)]
a2, d2 = pw.split_lost([x.copy() for x in a], [x.copy() for x in d])
print("INSIDE", show(a2, d2)[5:7])

# No number skipped: nothing is touched.
a = [r("1", "Whole 2 Clue here", "5")]
d = [r("2", "Two", "3")]
a2, d2 = pw.split_lost([x.copy() for x in a], [x.copy() for x in d])
print("WHOLE", show(a2, d2)[0])
PY
)
get() { echo "$out" | sed -n "s/^$1 //p"; }

check "a lost count: the clue splits at the skipped number" \
  "[('15', 'Action at one time', None), ('17', 'Go down sportingly', '6')]" "$(get LOST)"
check "a bare cross-reference splits off as See N" \
  "[('1', 'One', '4'), ('5', 'Five', '5'), ('2', 'See 4', None), ('3', 'Supported while bestowing', '4'), ('6', 'Six', '5')]" "$(get SEE)"
check "a count inside the text is the earlier clue's" \
  "[('10', 'Quite able', '7'), ('11', 'Those who have been honoured', '5')]" "$(get INSIDE)"
check "a list with no skipped number is left alone" "('1', 'Whole 2 Clue here', '5')" "$(get WHOLE)"

[ "$fails" = 0 ] && echo "all ok" || { echo "$fails failed"; exit 1; }
