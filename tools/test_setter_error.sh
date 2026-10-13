#!/usr/bin/env bash
# A clue the setter printed wrong is annotated as printed: the anagram mismatch
# tools/data/setter_error.json names for that light passes, with a walkthrough
# saying so, and every other mismatch still fails. A row is a whole-answer or a
# partial anagram of what the clue prints, or it is refused.
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

# The blocks hand over the fodder as printed: with a slip they add up to the
# answer with the slip's letters swapped back (a v2 file's blocks are the
# printed words); a legacy file that respelt a block to hide it still passes.
E = {"number": 13, "direction": "down", "solution": "KISSOFLIFE", "clue": {"text": "x"}}
def slip_ann(*gives):
    return {"type": ["anagram"], "answer": "KISS OF LIFE",
            "blocks": [{"clueFragment": "w", "gives": g} for g in gives],
            "assembly": {"anagrams": [{"fodder": "SKISELFOIL", "gives": "KISSOFLIFE"}]}}
check("blocks of the printed fodder add up with the slip", False, v.blocks_miss_letters(slip_ann("SKIS", "ELFOIL"), E))
check("blocks respelt to hide the slip still add up", False, v.blocks_miss_letters(slip_ann("SKIS", "ELFOIF"), E))
check("blocks that are neither do not", True, v.blocks_miss_letters(slip_ann("SKIS", "ELFOIX"), E))

# A separator at the light's own end runs the answer on into another light
# (cryptic-21625 6D, A DANCE TO THE MUSIC OF TIME): no gap in this answer can be it.
def seps(answer, ats):
    out = []
    v.check_answer_matches_separators("6D", {"answer": answer}, {"clue": {"separators": [
        {"at": a, "mark": ","} for a in ats]}}, out)
    return len(out)
check("a separator at the light's end is not a gap in it", 0, seps("DANCE TO THE MUSIC", [5, 7, 10, 15]))
check("a missing gap inside the light still fails", 1, seps("DANCE TO THEMUSIC", [5, 7, 10, 15]))

# The row's two shapes, and a row fitting neither (setter_error_problems, which
# annotate_check refuses to file by and the validator fails on).
PUZ = {"id": "p-1", "entries": [
    {"number": 13, "direction": "down", "solution": "KISSOFLIFE",
     "clue": {"text": "First aid required after skis become involved in Elf oil spill"}},
    {"number": 3, "direction": "across", "solution": "UNGALLANT",
     "clue": {"text": "Discourteous bitterness in crude taunt"}},
    {"number": 5, "direction": "across", "solution": "BLUECOLLAR",
     "clue": {"text": "Unskilled group circulating changed locale"}},
    {"number": 6, "direction": "down", "solution": "REAPPEAR",
     "clue": {"text": "Notepaper ordered has become available again"}},
    {"number": 1, "direction": "across", "solution": "WHO", "group": ["1-across", "9-across"],
     "clue": {"text": "Ow, ho, I am! Television show"}},
    {"number": 9, "direction": "across", "solution": "AMI", "clue": {"text": "See 1"}}]}
GALL = {"blocks": [{"clueFragment": "bitterness", "gives": "GALL"}]}
CLUB = {"blocks": [{"clueFragment": "group", "gives": "CLUB"}]}
P = lambda eid, row, ann={}: len(v.setter_error_problems(PUZ, eid, row, ann))
check("whole answer from printed words is filed", 0, P("13-down", ["skis Elf oil", "KISSOFLIFE", "e"]))
check("a partial anagram's own letters are filed", 0, P("3-across", ["taunt", "UNANT", "e"], GALL))
check("fodder may be a block's gives", 0, P("5-across", ["club locale", "BLUECOLLAR", "e"], CLUB))
check("fodder may be a block's fragment of one printed word", 0,
      P("6-down", ["paper", "APPEAR", "e"], {"blocks": [{"clueFragment": "Note", "gives": "RE"},
                                                     {"clueFragment": "paper", "gives": "PAPERA"}]}))
check("part of a printed word with no block reading it off is refused", 1,
      P("6-down", ["paper", "APPEAR", "e"]))
check("a linked answer is every light's letters", 0, P("1-across", ["ow ho I am", "WHOAMI", "e"]))
check("fodder neither printed nor a block's gives is refused", 1,
      P("5-across", ["club locale", "BLUECOLLAR", "e"]))
check("gives with letters the answer lacks is refused", 1, P("3-across", ["taunt", "TAUNT", "e"], GALL))
check("a row too far out is refused", 1, P("13-down", ["skis", "KISSOFLIFE", "e"]))
check("a row with no evidence is refused", 1, P("13-down", ["skis Elf oil", "KISSOFLIFE", " "]))

# The committed rows all fit.
from fetch_puzzle import read_puzzle_file
from puzzle_paths import find
for (pid, eid), row in v.load_source_table("setter_error").items():
    check(f"{pid}/{eid} fits a setter_error shape", [],
          v.setter_error_problems(read_puzzle_file(find(pid)), eid, row))
raise SystemExit(fails)
PY
