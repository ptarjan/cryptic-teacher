#!/bin/bash
# Does puzzle_integrity refuse a blog clue that opens with what is left of the
# blog's clue number, and pass the clues that only look like one?
#
#     bash tools/test_clue_number_residue.sh
#
# Every blog writes the number and its direction before the clue, "1a" or
# "1ac." or "1 a.", and a parser that takes the number but not the suffix files
# "a Bizarre eponym ...". The opposite slip ate the clue's own "A" off "1 A
# moral purge ...", which is why the message asks for that to be checked too.
# Real clues open lowercase as well ("e.g.", "iPads are epic!", "see 24dn.",
# "eBay"), and those must pass.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }

out=$(PYTHONPATH=tools python3 - <<'PY'
import puzzle_integrity as P

def flagged(text, retrieved="blog"):
    flags = []
    puzzle = {"id": "telegraph-1", "source": {"retrievedFrom": retrieved},
              "entries": [{"number": 1, "direction": "across", "position": {"x": 0, "y": 0},
                           "length": 4, "clue": {"text": text, "enumeration": "4"},
                           "solution": "ABCD"}]}
    P.check_shape(puzzle, "2026-10-01", flags)
    return "Y" if any("clue number" in f[2] for f in flags) else "n"

bad = ["a Bizarre eponym worked for lad on warship", "d Not complete in showing bias",
       "ac. Seaman, getting posted", "dn Fares", "dFares going up on flights?",
       "aWorthless gemstone", "s Sailor carries drugs back", "aa Reject sugar"]
good = ["A moral purge modified indoor pastime", "e.g. registered undertakings",
        "eg registered undertakings", "iPads are epic!", "eBay seller", "see 24dn.",
        "e + r ÷ (51 + 11) = magic formula", "i newspaper printed in New York",
        "makes new plans about navy pennants"]
print("BAD", "".join(flagged(t) for t in bad))
print("GOOD", "".join(flagged(t) for t in good))
print("PAPER", flagged("a Bizarre eponym", retrieved="publisher"))
PY
)
got() { echo "$out" | grep "^$1 " | cut -d' ' -f2-; }
same "every number residue is refused" "$(got BAD)" "YYYYYYYY"
same "lowercase-opening clues that are clues pass" "$(got GOOD)" "nnnnnnnnn"
same "only a blog transcription is held to it" "$(got PAPER)" "n"

[ $fails -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
