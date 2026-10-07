#!/bin/bash
# Is a model's solve graded when a solver's blog (or any other copy) arrives
# with answers, through the same grader as the paper's key?
#
#     bash tools/test_blog_grade.sh
#
# Offline: tools/cross_validate.py's grade_model() on a 3x3 model-solved grid
# against stub copies; blind_misses.json is written under a temp root.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
python3 - <<'PY'
import contextlib
import copy
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "tools")
import cross_validate as cv
import fetch_puzzle
import provenance

fails = 0


def same(what, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else f": got {got!r}, want {want!r}"))


root = Path(tempfile.mkdtemp())
fetch_puzzle.ROOT = root
MISSES = root / "tools" / "data" / "blind_misses.json"


def misses():
    return json.loads(MISSES.read_text()) if MISSES.exists() else {}


def entry(n, d, x, y, sol):
    return {"number": n, "direction": d, "position": {"x": x, "y": y}, "length": len(sol),
            "clue": {"text": f"clue {n}{d[0]}", "enumeration": str(len(sol))}, "solution": sol}


# 3-across's middle cell is checked by no down light; its ends cross CAB and TOE.
def grid(three="BEE", **solutions):
    return {"id": "toughie-1", "dimensions": {"cols": 3, "rows": 3},
            "source": {"retrievedFrom": "blog"},
            "solutions": {"origin": "model", "model": "opus", "date": "2026-10-07",
                          "check": "4 entries", **solutions},
            "entries": [entry(1, "across", 0, 0, "CAT"), entry(1, "down", 0, 0, "CAB"),
                        entry(2, "down", 2, 0, "TOE"), entry(3, "across", 0, 2, three)]}


class Blog(cv.Adapter):
    def __init__(self, name="bigdave44", authority=cv.BLOG):
        self.name, self.origin, self.authority = name, name, authority
        self.votes = ("ANSWER",)


def grade(ours, *held):
    held = list(held)
    verdicts, found = cv.majority(ours, held)
    return cv.grade_model(ours, held, found, verdicts)


def copy_of(three="BEE", drop=()):
    theirs = grid(three)
    for e in theirs["entries"]:
        if f"{e['number']}-{e['direction']}" in drop:
            e["solution"] = None
    return theirs


# A blog's answer outranks a model's guess: it takes the light over, and the
# guess is a miss in blind_misses.json, its annotation dropped.
ours = grid("BYE")
ours["entries"][3]["annotation"] = {"answer": "BYE"}
new, wrong, marked, origins = grade(ours, (Blog(), copy_of()))
same("a blog's answer replaces the model's guess", new["entries"][3]["solution"], "BEE")
same("and the guess is graded a miss", wrong, [("3-across", "BYE", "BEE")])
same("in blind_misses.json, for the nightly diagnosis", misses(), {"toughie-1": {"3-across": "BYE"}})
same("its annotation written off the wrong answer is dropped", "annotation" in new["entries"][3], False)
same("every light the blog answers is marked graded, by the blog",
     new["solutions"]["graded"], {e: "bigdave44" for e in
                                  ("1-across", "1-down", "2-down", "3-across")})
same("the file still says a model solved it", provenance.solution_detail(new)["model"], "opus")
out = io.StringIO()
with contextlib.redirect_stdout(out):
    fetch_puzzle.print_grade(new, wrong, marked, " and ".join(origins) + "'s answers")
same("the grade prints in the line daily_update.sh alerts on", out.getvalue().splitlines()[0],
     "BLIND SOLVE GRADED toughie-1: 3/4 correct against bigdave44's answers")

# Each guess is graded once: the graded file offers nothing to mark again.
same("a graded light is no longer a guess to mark", provenance.model_answers(new), {})
same("so the next night's pass grades nothing", grade(new, (Blog(), copy_of())), None)

# A blog that answers only some lights grades those; the rest wait. A later
# copy grades the rest without clearing the first grade's misses.
MISSES.unlink()
new, wrong, marked, _ = grade(grid("BYE"), (Blog(), copy_of(drop=("3-across", "1-down"))))
same("a partial write-up grades only what it answers", sorted(marked), ["1-across", "2-down"])
same("with nothing wrong in it", wrong, [])
fetch_puzzle.record_misses("toughie-1", [("1-down", "CAD", "CAB")], {"1-down": "CAD"})
new2, wrong2, marked2, _ = grade(new, (Blog("fifteensquared"), copy_of()))
same("a later copy grades only the lights still ungraded", sorted(marked2), ["1-down", "3-across"])
same("an earlier grade's miss on a light not re-marked stands",
     misses(), {"toughie-1": {"3-across": "BYE"}})

# Crossings refute a blog's answer: the guess stands, graded, and is no miss.
MISSES.unlink()
new, wrong, marked, _ = grade(grid(), (Blog(), copy_of("TEE")))
same("a blog answer its crossings refute does not take over", new["entries"][3]["solution"], "BEE")
same("and the guess it disputed is graded, not a miss", ("3-across" in marked, wrong), (True, []))
same("so blind_misses.json has nothing for it", misses(), {})

# A blog's typo the model got right is SOURCE_ANSWER_WRONG's: the copy is put
# right before it votes (witness()), so the model is not marked down for it.
fetch_puzzle.SOURCE_ANSWER_WRONG[("toughie-1", "3-across")] = ("BYE", "BEE", "blog typo")
held = [(Blog(), cv.witness(copy_of("BYE")))]
new, wrong, _, _ = grade(grid(), *held)
same("a blog typo in the answer table is no miss", (wrong, new["entries"][3]["solution"]), ([], "BEE"))
del fetch_puzzle.SOURCE_ANSWER_WRONG[("toughie-1", "3-across")]

# Two copies that dispute a light leave it ungraded, a lead for the next copy.
graded = grade(grid("BYE"), (Blog("bigdave44"), copy_of()), (Blog("georgeho"), copy_of("BOE")))
same("a light the copies dispute is not graded", "3-across" in graded[2], False)

# An answer the paper printed under the model's fill is the paper's, not a guess.
ours = grid("BYE", printed={"3-across": "BYE"})
new, wrong, marked, _ = grade(ours, (Blog(), copy_of()))
same("a printed answer is not marked, nor outranked by a blog",
     ("3-across" in marked, new["entries"][3]["solution"]), (False, "BYE"))

# A prize page's placeholder ("M1D1L") is no answer.
same("an answer with digits in it is no ballot",
     cv.ballot({"length": 5, "solution": "M1D1L"}, "ANSWER"), None)

# A grid the copy does not share grades nothing.
other = copy_of()
other["entries"][3]["position"] = {"x": 0, "y": 1}
same("a copy of another grid grades nothing", grade(grid("BYE"), (Blog(), other)), None)

# A puzzle not solved by a model is never graded.
published = grid("BYE")
published["solutions"] = {"origin": "published"}
same("a published key is not a guess", grade(published, (Blog(), copy_of())), None)

# A write-up's answers are its source's: a gap-fill solve keeps them.
writeup = grid()
writeup["solutions"] = {"origin": "writeup", "blog": "bigdave44", "url": "u", "date": "d",
                        "check": "c"}
writeup["entries"][3]["solution"] = None
same("a write-up's answers are the ones a solve must keep",
     sorted(provenance.printed_answers(writeup)), ["1-across", "1-down", "2-down"])

print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
PY
