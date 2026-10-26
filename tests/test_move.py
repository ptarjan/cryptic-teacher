#!/usr/bin/env python3
# A letter move is one wordplay step (Paul 10-19): "England dropping ball and lacking colour"
# is ALBION with its O dropped, ALBINO, written move<dropping>([England]ALBION, [ball]O),
# never ALBION + O with the first O deleted.
import os
import sys
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
sys.path.insert(0, ".")

import annotation
import wordplay as W

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def refused(text, answer, clue=None):
    try:
        W.evaluate(W.parse(text, clue), answer)
    except W.WordplayError:
        return True
    return False

CLUE = "England dropping ball and lacking colour"
EXPR = "move<dropping>([England]ALBION, [ball]O)"
tree = W.parse(EXPR, CLUE)
check("move parses to its own op over the fodder and the moved letter", ("move", ["ALBION", "O"]),
      (tree["op"], [p["gives"] for p in tree["parts"]]))
check("ALBION with its O moved gives ALBINO", "ALBINO", W.evaluate(tree, "ALBINO")[id(tree)])
check("the expression renders back as written", EXPR, W.render(tree))
check("the moved letter must be in the fodder", True, refused("move<dropping>([England]ALBION, [ball]E)", "ALBINE"))
check("a move that leaves the word as it was gives nothing", True, refused("move<dropping>([England]ALBION, [ball]O)", "ALBION"))
check("move takes the fodder and the moved letters", True, refused("move<dropping>([England]ALBION)", "ALBINO"))
check("a run of letters moves together, in its order", {"BCAD", "ADBC"}, W._moves("ABCD", "BC"))
voila = W.parse("move<brought down>([Instrument]VIOLA, [I])", "Instrument I brought down — there it is!")
check("VIOLA with its I brought down is VOILA (times-28672 2d)", "VOILA", W.evaluate(voila, "VOILA")[id(voila)])

entry = {"number": 6, "direction": "down", "solution": "ALBINO", "length": 6,
         "clue": {"text": CLUE, "enumeration": "6"}}
ann = {"definitions": [{"text": "lacking colour"}], "wordplay": W.parse(EXPR)}
v = annotation.view(ann, entry)
check("its clue type is move", ["move"], v["type"])
check("its indicator signals the move", [{"text": "dropping", "for": "move"}],
      [{k: i[k] for k in ("text", "for")} for i in v["indicators"]])
check("its blocks are the fodder and the moved letter", [("England", "ALBION"), ("ball", "O")],
      [(b.get("clueFragment"), b.get("gives")) for b in v["blocks"]])
raise SystemExit(fails)
