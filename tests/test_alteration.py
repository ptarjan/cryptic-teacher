#!/usr/bin/env python3
# Does the write gate hold an entry's `alteration` to the letters it claims?
#
#     python3 tests/test_alteration.py
#
# A Listener whose preamble or clue alters answers before entry files the
# grid's letters as `solution` and the clue's own word as `alteration.from`;
# each step's op has to turn the word before it into the word after. Every op
# is held to one mapping it must accept and one it must refuse, then a real
# puzzle carrying an alteration is written through refuse_bad_write and broken
# one way at a time (an enumeration may count either word, never a third), an
# annotation is held to building `from`, not the entry, and every light in
# listener_puzzles.ARCHIVE_ALTERED is held to being filed that way.
import copy
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
os.chdir(REPO)
import fetch_puzzle as fetcher
import listener_puzzles as lp
import puzzle_integrity
import puzzle_schema
import quotes
import validate_annotations as va

fails = 0
lines = []


def emit(*parts):
    lines.append(" ".join(str(p) for p in parts))


def grep(prefix):
    return "\n".join(l for l in lines if l.startswith(prefix))


def same(what, got, want):
    global fails
    if got == want:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what}\n    want {want}\n    got  {got}")
        fails += 1


OPS = puzzle_integrity.ALTERATION_OPS
CASES = {  # op: (accepted, refused)
    "reversal": (("FOETOR", "ROTEOF"), ("FOETOR", "FOETOR")),
    "anagram": (("CANOPY", "PYCANO"), ("CANOPY", "CANOPE")),
    "move": (("TRITE", "RITTE"), ("TRITE", "ETIRT")),
    "deletion": (("BASIN", "BAI"), ("BASIN", "BIA")),
    "insertion": (("BAI", "BAIT"), ("BAI", "TIAB")),
    "substitution": (("SALON", "TALON"), ("SALON", "TALONS")),
}
for op, (good, bad) in CASES.items():
    emit(f"OP {op}", OPS[op](*good), OPS[op](*bad))

real = fetcher.read_puzzle_file(fetcher.resolve_puzzle("listener-1"))
e = next(e for e in real["entries"] if len(e["solution"]) >= 4)
good = copy.deepcopy(real)
good["preamble"] = "Answers are entered reversed."
g = next(x for x in good["entries"] if x["number"] == e["number"] and x["direction"] == e["direction"])
g["alteration"] = {"from": e["solution"][::-1], "steps": [{"op": "reversal"}]}


def verdict(p):
    try:
        puzzle_integrity.refuse_bad_write(puzzle_schema.order(quotes.straighten(p)))
        return "accepted"
    except ValueError as err:
        return " | ".join(f"{k}" for k, _, w in err.flags)


def broken(name, change):
    p = copy.deepcopy(good)
    change(p)
    emit(name, verdict(p))


def alt(p):
    return next(x for x in p["entries"] if "alteration" in x)["alteration"]


emit("GOOD", verdict(good))
broken("WRONGOP", lambda p: alt(p)["steps"].__setitem__(0, {"op": "deletion"}))
broken("CLUESAYSIT", lambda p: p.pop("preamble"))


def unprinted(p):
    p.pop("preamble")
    t = next(x for x in p["entries"] if "alteration" in x)
    t["clue"] = {"missing": True}
    t.pop("annotation", None)


broken("NOPREAMBLE", unprinted)


def counted(n):
    def change(p):
        t = next(x for x in p["entries"] if "alteration" in x)
        t["alteration"] = {"from": t["solution"][::-1] + "S", "steps": [
            {"op": "deletion", "gives": t["solution"][::-1]}, {"op": "reversal"}]}
        t["clue"] = {**t["clue"], "enumeration": str(len(t["solution"]) + n)}
    return change


broken("COUNTSENTRY", counted(0))
broken("COUNTSFROM", counted(1))
broken("COUNTSNEITHER", counted(2))

# Every archive entry ARCHIVE_ALTERED names is filed with that alteration.
for n, lights in lp.ARCHIVE_ALTERED.items():
    held = fetcher.read_puzzle_file(fetcher.resolve_puzzle(f"listener-{n}"))
    by = {(x["number"], x["direction"]): x for x in held["entries"]}
    for k, (word, op) in lights.items():
        x = by.get(k, {})
        ok = (x.get("alteration") == {"from": word, "steps": [{"op": op}]}
              and OPS[op](word, x.get("solution", "")))
        if not ok:
            emit("ARCHIVE", n, k, x.get("solution"), x.get("alteration"))
emit("ARCHIVE done")
broken("LASTGIVES", lambda p: alt(p)["steps"][0].__setitem__("gives", e["solution"]))
broken("CHAINOK", lambda p: alt(p).__setitem__("steps", [
    {"op": "insertion", "gives": e["solution"][::-1] + "S"},
    {"op": "deletion", "gives": e["solution"][::-1]}, {"op": "reversal"}]))
broken("CHAINNOGIVES", lambda p: alt(p).__setitem__("steps", [{"op": "insertion"}, {"op": "deletion"}]))
broken("BADOPNAME", lambda p: alt(p)["steps"].__setitem__(0, {"op": "jumble"}))

# The annotation's wordplay builds the clue's word, not the entry.
w = g["alteration"]["from"]
for pieces, name in (([w[:2], w[2:]], "FROM"), ([e["solution"][:2], e["solution"][2:]], "ENTRY")):
    p = copy.deepcopy(good)
    t = next(x for x in p["entries"] if "alteration" in x)
    words = t["clue"]["text"].split()
    t["annotation"] = {"definitions": t["annotation"]["definitions"],
                       "wordplay": {"op": "charade", "parts": [{"words": words[0], "gives": pieces[0]},
                                                                {"words": words[-1], "gives": pieces[1]}]}}
    errors = va.validate_puzzle(p)[1]
    emit("PIECES", name, any("wordplay does not give" in x for x in errors))

for op in "reversal anagram move deletion insertion substitution".split():
    same(f"{op} accepts its mapping and refuses a wrong one", grep(f"OP {op} "), f"OP {op} True False")
same("a correct alteration is written", grep("GOOD"), "GOOD accepted")
same("an op that does not map the word is refused", grep("WRONGOP"), "WRONGOP ALTERED")
same("a clue printed without a preamble may say how", grep("CLUESAYSIT"), "CLUESAYSIT accepted")
same("neither preamble nor clue printed, no alteration", grep("NOPREAMBLE"), "NOPREAMBLE ALTERED")
same("an enumeration may count the entry", grep("COUNTSENTRY"), "COUNTSENTRY accepted")
same("an enumeration may count the clue's word", grep("COUNTSFROM"), "COUNTSFROM accepted")
same("an enumeration counting neither is refused", grep("COUNTSNEITHER"), "COUNTSNEITHER LENGTH")
same("every ARCHIVE_ALTERED light is filed altered", grep("ARCHIVE"), "ARCHIVE done")
same("the last step's result is the solution, not a gives", grep("LASTGIVES"), "LASTGIVES ALTERED")
same("a chain of steps through gives is accepted", grep("CHAINOK"), "CHAINOK accepted")
same("a middle step without gives is refused", grep("CHAINNOGIVES"), "CHAINNOGIVES ALTERED")
same("an op outside the enum is refused", grep("BADOPNAME"), "BADOPNAME ALTERED | SCHEMA")
same("pieces building the clue's word pass", grep("PIECES FROM"), "PIECES FROM False")
same("pieces building the entry fail", grep("PIECES ENTRY"), "PIECES ENTRY True")

if fails:
    print(f"{fails} failed")
    sys.exit(1)
print("all passed")
