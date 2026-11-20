#!/usr/bin/env python3
# The mend for a one-leaf wordplay of notes/keys over an A-G answer (singleLeaf): [keys]CADGE becomes
# one piece per letter.
#
#     python3 tests/test_mend_note_letters.py
import _path  # puts tools/ on sys.path
import mend_note_letters as M
import validate_annotations as V
import wordplay

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


CLUE = "Beg for keys"
a = {"wp": "[keys]CADGE", "notes": {"keys": "keys are notes"}}
check("the shape is a singleLeaf finding to begin with", V.single_leaf(wordplay.parse(a["wp"], CLUE)))
check("the mend reports a change", M.mend(a, CLUE, "CADGE"))
fixed = wordplay.parse(a["wp"], CLUE)
check("no singleLeaf finding is left", not V.single_leaf(fixed))
check("it still gives the answer", wordplay.evaluate(fixed, "CADGE") is not None)
check("a second mend changes nothing", not M.mend(a, CLUE, "CADGE"))
b = {"wp": "[Beg]CADGE"}
check("a leaf that names no notes is left alone", not M.mend(b, CLUE, "CADGE"))
c = {"wp": "[keys]CLOSE"}
check("an answer with letters outside A-G is left alone", not M.mend(c, "Keys", "CLOSE"))
check("no clue or answer, no change", not M.mend({"wp": "[keys]CADGE"}, "", ""))

print("FAILED" if fails else "all ok")
raise SystemExit(1 if fails else 0)
