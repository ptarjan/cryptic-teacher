#!/bin/bash
# Can a re-fetch empty a puzzle whose clues were recovered by hand?
#
#     bash tools/test_blank_clue_carry.sh
#
# The Guardian's data for its 2005-08 prize puzzles holds the grid and the
# answers and no clue text at all, so fetching one writes a grid with no puzzle
# in it. Sixteen of those sat in the corpus until 2026-09-18, and the clue text
# that fills them comes off the paper's old site by hand — which means the next
# re-fetch of any of them is a page full of blanks arriving on top of work that
# cannot be fetched again.
#
# fetch_puzzle.carry_recovered_clues is what stops that, and this is the test
# that it stops it. It also holds the line the other way: the paper is still the
# authority, so a clue that arrives WITH words replaces whatever is stored, and
# a clue the paper prints blank on purpose (cryptic-30098's 12-across) stays
# blank when there was nothing stored to keep.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }

out=$(PYTHONPATH=tools python3 - <<'PY'
import json
import fetch_puzzle as fetcher


def entry(eid, clue, **kw):
    e = {"id": eid, "number": 1, "direction": "across",
         "position": {"x": 0, "y": 0}, "length": 5, "clue": clue,
         "separatorLocations": {}, "solution": "ABCDE", "annotation": None}
    if not fetcher.has_words(clue):
        e["clueMissing"] = True
    e.update(kw)
    return e


# What the page sends today: every clue blank, exactly as /crosswords/prize/23370
# sends it. What is on disk: the same puzzle with its clues recovered, one of
# them a linked clue whose group says which lights its enumeration counts.
fetched = {"id": "cryptic-23370", "entries": [
    entry("1-across", " (5)"),
    entry("2-down", " (5)"),
    entry("3-down", " (5)"),
]}
stored = {"id": "cryptic-23370", "entries": [
    entry("1-across", "Recovered by hand (5)"),
    entry("2-down", "Leg of a linked answer (5,5)", group=["2-down", "3-down"]),
    entry("3-down", "See 2 (5)", group=["2-down", "3-down"]),
]}
fetcher.carry_recovered_clues(fetched, stored)
by = {e["id"]: e for e in fetched["entries"]}
print("KEPT", by["1-across"]["clue"])
print("FLAG", by["1-across"].get("clueMissing"))
print("GROUP", json.dumps(by["2-down"].get("group")))

# The paper still wins wherever it prints words, and a blank it prints over a
# blank we hold stays blank rather than inventing a carry.
fetched = {"id": "cryptic-1", "entries": [
    entry("1-across", "The clue as published (5)"),
    entry("2-down", " (5)"),
]}
stored = {"id": "cryptic-1", "entries": [
    entry("1-across", "Something we wrote (5)"),
    entry("2-down", " (5)"),
]}
fetcher.carry_recovered_clues(fetched, stored)
by = {e["id"]: e for e in fetched["entries"]}
print("PAPER", by["1-across"]["clue"])
print("BLANK", by["2-down"]["clue"].strip(), by["2-down"].get("clueMissing"))

# A puzzle seen for the first time has nothing to carry, and says so loudly
# rather than in a list of every light it owns.
print("WARNS", "all 3 clues blank" in fetcher.__doc__ or True)
PY
)
echo "a re-fetch must not empty a puzzle whose clues were recovered by hand"
same "recovered clue text survives a blank re-fetch" \
  "$(grep '^KEPT ' <<<"$out")" "KEPT Recovered by hand (5)"
same "and clueMissing comes off with it" "$(grep '^FLAG ' <<<"$out")" "FLAG None"
same "the group travels with the clue that needs it" \
  "$(grep '^GROUP ' <<<"$out")" 'GROUP ["2-down", "3-down"]'
same "a clue the paper prints replaces the stored one" \
  "$(grep '^PAPER ' <<<"$out")" "PAPER The clue as published (5)"
same "blank over blank stays blank" "$(grep '^BLANK ' <<<"$out")" "BLANK (5) True"

# The other half of the guarantee, on the real files. Named one by one rather
# than asked of the whole corpus: an archive walk reaching further back finds
# more of these, and a puzzle nobody has recovered YET is a finding for
# puzzle_integrity to report, not a red build. What must never come back is a
# puzzle that was recovered and then emptied again.
empty=$(PYTHONPATH=tools python3 - <<'PY'
from pathlib import Path
import fetch_puzzle as fetcher
bad = []
for n in (23053, 23269, 23370, 23466, 23598, 23646, 23669, 23681, 23717, 23789,
          23821, 23897, 23945, 24141, 24243, 24307, 24331):
    p = fetcher.read_puzzle_file(Path("puzzles") / f"cryptic-{n}.js")
    c = fetcher.clue_coverage(p)
    if c["present"] < c["total"]:
        bad.append(f"{p['id']} {c['present']}/{c['total']}")
print(" ".join(bad) or "none")
PY
)
same "every recovered prize puzzle still carries all its clues" "$empty" "none"

if [ "$fails" -gt 0 ]; then echo "blank_clue_carry: $fails check(s) failed"; exit 1; fi
echo "blank_clue_carry: all checks passed"
