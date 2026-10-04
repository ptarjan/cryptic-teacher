#!/usr/bin/env bash
# A clue the setter printed wrong is annotated as printed: the anagram mismatch
# tools/data/setter_error.json names for that light passes, with a walkthrough
# saying so, and every other mismatch still fails.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

v.SETTER_ERROR = {("p-1", "13-down"): ("skis Elf oil", "KISSOFLIFE", "the page prints it"),
                  ("p-1", "2-down"): ("abcdef", "ghijkl", "too far out")}
WALK = {"walkthrough": "The printed clue has ELF OIL where KISS OF LIFE needs one more F, one less L."}

def errors(pid, eid, fodder, gives, walk=WALK):
    ann = {"assembly": {"anagrams": [{"fodder": fodder, "gives": gives}]}, "explanation": walk}
    out = []
    v.check_anagram_letters(pid, eid, "X", ann, out)
    return out

check("the declared slip passes", [], errors("p-1", "13-down", "SKIS ELF OIL", "KISS OF LIFE"))
check("a sound anagram passes with no row", [], errors("p-1", "1-across", "LISTEN", "SILENT"))
check("a mismatch with no row fails", 1, len(errors("p-1", "1-across", "LISTEN", "SILENTS")))
check("the row is for its puzzle only", 1, len(errors("p-2", "13-down", "SKISELFOIL", "KISSOFLIFE")))
check("the row is for its light only", 1, len(errors("p-1", "14-down", "SKISELFOIL", "KISSOFLIFE")))
check("another mismatch on the row's light fails, and the row is unused", 2,
      len(errors("p-1", "13-down", "SKISELFOL", "KISSOFLIFE")))
check("the slip must be told in the walkthrough", 1,
      len(errors("p-1", "13-down", "SKISELFOIL", "KISSOFLIFE", walk={})))
check("a row more than one letter out is a wrong parse", 1,
      len(errors("p-1", "2-down", "ABCDEF", "GHIJKL")))

# The committed rows: each one's fodder is in its clue, and it is at most one letter out.
from fetch_puzzle import clue_words, read_puzzle_file
from groups import entry_id
from puzzle_paths import find
for (pid, eid), (fodder, gives, why) in v.load_source_table("setter_error").items():
    e = {entry_id(x): x for x in read_puzzle_file(find(pid))["entries"]}[eid]
    words = {v.letters(w) for w in e["clue"]["text"].split()}
    check(f"{pid}/{eid}: fodder is words printed in the clue", True,
          all(v.letters(w) in words for w in fodder.split()))
    check(f"{pid}/{eid}: gives is the answer", True, v.letters(gives) == e["solution"])
    check(f"{pid}/{eid}: has evidence", True, bool(why.strip()))
raise SystemExit(fails)
PY
