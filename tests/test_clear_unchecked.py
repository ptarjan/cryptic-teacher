#!/usr/bin/env python3
# tools/clear_unchecked.py: the flag goes only from a tree that evaluates to the answer
# without it; a tree with the wrong part count is failing, not crashed.
import os
import sys
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import clear_unchecked as C

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

first = {"op": "first", "unchecked": True, "gives": "M", "indicators": [{"text": "first of", "note": "first of means its opening letter"}],
         "parts": [{"words": "members", "at": 9}]}
check("an unchecked step is seen", True, C.flagged({"op": "charade", "parts": [first, {"words": "x"}]}))
check("a checked tree is not", False, C.flagged({"op": "charade", "parts": [{"words": "x", "gives": "X"}]}))
s = C.stripped({"op": "charade", "unchecked": True, "parts": [first]})
check("stripping removes every flag", False, C.flagged(s))
check("and leaves the original alone", True, C.flagged(first))
check("a tree that gives the answer is cleared", "cleared", C.verdict(first, "M"))
check("a tree that does not is failing", "failing", C.verdict(first, "N"))
check("a wrong part count is failing, not crashed", "failing",
      C.verdict({"op": "container", "unchecked": True, "parts": [{"words": "a", "gives": "A"}]}, "AB"))
check("no parts at all is failing too", "failing", C.verdict({"op": "reversal", "unchecked": True}, "AB"))

entry = {"number": 1, "direction": "across", "solution": "M",
         "clue": {"text": "first of members", "enumeration": "1"},
         "annotation": {"definitions": [], "wordplay": first}}
puzzle = {"id": "test-1", "entries": [entry]}
real = C._problems
C._problems = lambda p: (C.collections.Counter(), C.collections.Counter(), int(C.flagged(p["entries"][0]["annotation"]["wordplay"])))  # the validator is not under test
done = C.clear_puzzle(puzzle)
check("an unchecked op's stated letters go with its flag", False, "gives" in C.stripped(first))
check("a leaf keeps its letters", "X", C.stripped({"words": "x", "gives": "X"})["gives"])
check("a clearable clue is reported", [("1a", "M")], [d[:2] for d in done[1]])
check("its flag is gone from the new puzzle", False,
      C.flagged(done[0]["entries"][0]["annotation"]["wordplay"]))
check("and kept in the old one", True, C.flagged(entry["annotation"]["wordplay"]))
check("the counts say cleared", 1, done[2]["cleared"])
check("a clue that fails is left", [], C.clear_puzzle({"id": "test-2", "entries": [{**entry, "solution": "N"}]})[1])
C._problems = lambda p: (C.collections.Counter(new=1), C.collections.Counter(), 0) if not C.flagged(p["entries"][0]["annotation"]["wordplay"]) else (C.collections.Counter(), C.collections.Counter(), 1)
check("a clear that adds an error is held back", [], C.clear_puzzle(puzzle)[1])
C._problems = real
check("a leaf pre-scrambled from its words is not cleared", "failing",
      C.verdict({"op": "container", "unchecked": True, "parts": [{"words": "lice", "gives": "CILE"}, {"words": "about", "gives": "CA"}]}, "CICALE"))
check("a failing clue is bucketed by reason", "eval: wrong string", C.bucket(first, "N")[1])
check("a clearing clue has the cleared bucket", "cleared", C.bucket(first, "M")[1])
# A tree that evaluates but that the validator's shape rules flag is not cleared
# (FOURTHESTATE: the "framed by" indicator sits on the inner first, not the container).
fourth = {"op": "container", "indicators": [{"text": "Leader of", "note": "the leader of a word is its first letter"}],
          "parts": [{"words": "pro-government", "gives": "FORTHESTATE", "note": "for the state"},
                    {"op": "first", "unchecked": True, "gives": "U",
                     "indicators": [{"text": "framed by", "note": "the letter sits inside the phrase like a picture in a frame"}],
                     "parts": [{"unchecked": True, "words": "Leader of union", "gives": "U", "select": "first",
                                "note": "first letter of UNION"}]}]}
ann = {"wordplay": fourth, "definitions": [{"text": "pro-government", "at": 0}]}
check("it evaluates without the flag", "surplus leaf words", C.bucket(fourth, "FOURTHESTATE")[1])
check("but its shape warnings keep it flagged", "failing",
      C.bucket(fourth, "FOURTHESTATE", ann, "Pro-government framed by leader of union")[0])
check("and say which", True, C.bucket(fourth, "FOURTHESTATE", ann, "x")[1].startswith(("shape: ", "surplus ")))
# A selection over a leaf holding words the pick does not need ('spilling guts' beside GASTRONOME) is not cleared.
surplus = {"op": "outer", "indicators": [{"text": "after", "note": "n"}], "unchecked": True,
           "parts": [{"words": "gastronome spilling guts", "gives": "GE", "unchecked": True, "select": "outer"}]}
check("surplus leaf words keep a selection flagged", "surplus leaf words", C.bucket(surplus, "GE")[1])
# A leaf giving a selection's result reads its words, a note's synonym stands for the longer word,
# a one-leaf spoonerism is two leaves, and first + last over one word is outer.
tidy = {"op": "middle", "unchecked": True, "gives": "OFFER", "indicators": [{"text": "Unlimited", "note": "n"}],
        "parts": [{"unchecked": True, "words": "funds", "gives": "OFFER", "select": "middle", "note": "the inside of coffers"}]}
check("a synonym named in the note is checked (COFFERS)", "cleared", C.bucket(tidy, "OFFER")[0])
check("and the leaf now gives the longer word", "COFFERS", C.cleaned(tidy, "OFFER")["parts"][0]["gives"])
check("and carries no select key", False, "select" in C.cleaned(tidy, "OFFER")["parts"][0])
spoon = {"op": "spoonerism", "unchecked": True, "gives": "RATTLEBAG", "indicators": [{"text": "Spooner", "note": "n"}],
         "parts": [{"unchecked": True, "words": "the military newspaper", "gives": "RATTLEBAG", "soundsLike": "BATTLE RAG"}]}
check("a one-leaf spoonerism is two checked leaves", "cleared", C.bucket(spoon, "RATTLEBAG")[0])
check("whose letters are the sound words", ["BATTLE", "RAG"], [p["gives"] for p in C.cleaned(spoon, "RATTLEBAG")["parts"]])
badspoon = {**spoon, "parts": [{**spoon["parts"][0], "soundsLike": "BATTLE RAG"}]}
check("a spoonerism whose letters do not swap stays failing", "failing", C.bucket(badspoon, "RATTLEBUG")[0])
raise SystemExit(fails)
