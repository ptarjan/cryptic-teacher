#!/usr/bin/env python3
# annotate_check --show / --try look at a clue as filed and test a wp, so a run needs no `python3 -c`.
#
#     python3 tests/test_clue_peek.py
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path
import clue_peek

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

puzzle = {"entries": [{"number": 6, "direction": "down", "solution": "CHOSES",
                       "clue": {"text": "Elected socialist leader", "enumeration": "6"},
                       "annotation": {"definitions": []}}]}
out = clue_peek.show(puzzle, ["6-down", "9-across"])
check("show prints the clue, answer and annotation", "CHOSES" in out and "Elected socialist leader" in out and '"definitions"' in out)
check("show names the ids that exist for an unknown one", "9-across: no such entry" in out and "6-down" in out)
ok = clue_peek.try_wp(puzzle, "6-down", "[Elected]CHOSE + first<leader>([socialist])")
check("try says ok for a wp that gives the answer", "ok, the letters come out" in ok)
bad = clue_peek.try_wp(puzzle, "6-down", "[Elected]CHOSE + [socialist]X")
check("try gives the checker's own refusal", "does not give CHOSES" in bad)
linked = {"entries": [
    {"number": 22, "direction": "across", "solution": "GENTLE", "group": ["22-across", "5-down"],
     "clue": {"text": "Kind pachyderm, say", "enumeration": "6,5"}},
    {"number": 5, "direction": "down", "solution": "GIANT", "group": ["22-across", "5-down"],
     "clue": {"text": "See 22", "enumeration": "5"}}]}
lk = clue_peek.try_wp(linked, "22-across", "[Kind]GENTLE + GIANT")
check("try judges a linked answer whole, not its first light", "11 letters against 6" not in lk and "GENTLE GIANT" in lk)
sys.exit(1 if fails else 0)
