#!/usr/bin/env python3
# tools/unchecked_repairs.py: each mechanical repair of an unchecked tree is kept
# only when the evaluator then finds the answer; the cases are clues from the corpus.
#
#     python3 tools/test_unchecked_repairs.py
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import clear_unchecked as C
import unchecked_repairs as R
import wordplay

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")


def leaf(words, gives=None, **kw):
    return {"words": words, **({"gives": gives} if gives is not None else {}), **kw}


def op(name, *parts, **kw):
    return {"op": name, "parts": list(parts), **kw}


def clears(tree, answer):
    return C.bucket(tree, answer)[0] == "cleared"


# A leaf under an anagram that holds the answer-order slice reads its clue words.
check("ana fodder leaves unscrambled (DEALT)", True, clears(
    op("anagram", leaf("diamonds", "D"), leaf("late", "EALT"), unchecked=True), "DEALT"))
check("an ana leaf outside the fodder is left alone", False, clears(
    op("container", leaf("lice", "CILE"), leaf("about", "CA"), unchecked=True), "CICALE"))
orig = op("anagram", leaf("late", "EALT"))
check("unscramble drops the scrambled gives", False, "gives" in R.unscramble(orig)["parts"][0])
check("and leaves the original alone", "EALT", orig["parts"][0]["gives"])

# A letterless unchecked leaf in a charade was a word carried along; its flag must not make it letters.
check("a filler leaf is dropped (PEEK)", True, clears(
    op("charade", leaf("top", "PEEK", unchecked=True), leaf("dog", unchecked=True), leaf("annoyance", unchecked=True)), "PEEK"))
check("a letterless leaf with letters elsewhere stays out of the sum", ["top"],
      [p["words"] for p in R.drop_wordless(op("charade", leaf("top", "PEEK"), leaf("dog", unchecked=True)))["parts"]])
check("pal() with its leaf dropped checks the answer", True, clears(
    op("palindrome", leaf("looking back and forth?", unchecked=True)), "OTTO"))

# Parts filed in the order the indicator reads.
check("sub filed new-then-old (PROP)", True, clears(
    op("substitution", leaf("leave out", "DROP"), leaf("power", "P"), leaf("day", "D"), unchecked=True), "PROP"))
check("del filed removed-then-from (TRAIT)", True, clears(
    op("deletion", leaf("an s", "S"), leaf("tr", "STRAIT"), unchecked=True), "TRAIT"))
check("a swap that does not give the answer is not made", False, clears(
    op("substitution", leaf("leave out", "DROP"), leaf("power", "P"), leaf("day", "D"), unchecked=True), "PLOP"))

# The letters a del/sub names, read off the answer.
dropped = R.repaired(op("deletion", leaf("sumptuous", "RICH")), "RIC")
check("a one-part del names the last letter (briefly)", ["RICH", "H"], [p["gives"] for p in dropped["parts"]])
check("a one-part del clears when the answer is x less a run", True, clears(
    op("deletion", leaf("sumptuous", "RICH"), unchecked=True), "RIC"))
check("a one-part del whose answer is not a cut of x does not", False, clears(
    op("deletion", leaf("sumptuous", "RICH"), unchecked=True), "XYZ"))
check("a one-part sub names old and new (INNIT)", True, clears(
    op("substitution", leaf("Indigenous Americans", "INUIT"), unchecked=True), "INNIT"))
check("the cut is the end before the start", [(3, "H")], R._removals("RICH", "RIC")[:1])
check("a headless cut is found", [(0, "S")], R._removals("STRAIT", "TRAIT")[:1])

# ins filed as one charade.
check("ins as one charade is split (ODDBALL)", True, clears(
    op("container", op("charade", leaf("old", "O"), leaf("Double Diamonds", "DD"), leaf("bishop", "B"), leaf("every one", "ALL")),
       unchecked=True), "ODDBALL"))

# rev over leaves that hold the letters as the answer has them.
check("a rev of two post-reversal leaves is reversed back (DAHLIA)", True, clears(
    op("reversal", op("charade", leaf("kept", "DAH"), leaf("trouble", "LIA")), unchecked=True), "DAHLIA"))
check("and reads the clue order, each leaf before the reversal", ["AIL", "HAD"],
      [p["gives"] for p in R.repaired(C.stripped(op("reversal", op("charade", leaf("kept", "DAH"), leaf("trouble", "LIA")))), "DAHLIA")["parts"][0]["parts"]])
swept = R.repaired(C.stripped(op("reversal", op("charade", leaf("American", "AM"), leaf("energy", "E"), leaf("oil", "LIO"), leaf("price", "RATE")))), "AMELIORATE")
check("only the reversed piece sits under rev (AMELIORATE)", ["charade", ["AM", "E", "reversal", "RATE"]],
      [swept["op"], [p.get("gives") or p["op"] for p in swept["parts"]]])
check("a rev filed with two parts is read the same way", True, clears(
    op("reversal", leaf("kept", "DAH"), leaf("trouble", "LIA"), unchecked=True), "DAHLIA"))
check("a rev that fits no run stays failing", False, clears(
    op("reversal", op("charade", leaf("kept", "DAH"), leaf("trouble", "LIA")), unchecked=True), "DAHLIB"))

# spoonerism filed as the two results.
check("a one-part spoon is a part count, not a crash", "eval: spoon part count",
      C.bucket(op("spoonerism", leaf("lead", "BLUE"), unchecked=True), "BLUECOATS")[1])
spoon = op("spoonerism", op("charade", leaf("in good form", "PIT"), leaf("become tired", "FALL")), unchecked=True)
check("a spoon of the two results has the inputs unswapped (PITFALL)", True, clears(spoon, "PITFALL"))
check("and gives the leaves their pre-swap letters", ["FIT", "PALL"],
      [p["gives"] for p in R.repaired(C.stripped(spoon), "PITFALL")["parts"]])

raise SystemExit(fails)
