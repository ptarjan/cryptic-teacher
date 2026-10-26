#!/usr/bin/env python3
# Where a puzzle came from is `source`, whose answers it holds is `solutions`,
# and who wrote its hints is `annotatedBy` — one key each, nothing said twice.
#
#     python3 tests/test_puzzle_source.py
#
# Tests both halves: every write lands the three blocks in that shape (and
# nothing else says the same thing), and provenance.check refuses a `solutions`
# whose detail does not back its `origin`.
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO / "tools"))

import fetch_puzzle as fetcher
import provenance
import puzzle_integrity
import puzzle_schema
# Two lights are not a whole puzzle; the write gate has its own test,
# tests/test_puzzle_invariants.py.
puzzle_integrity.refuse_bad_write = lambda puzzle, old=None: None

fails = 0


def same(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name}\n    want {want}\n    got  {got}")
        fails += 1


def entry(eid, num, solution="ANSWERED"):
    return {"id": eid, "number": num, "direction": "across",
            "position": {"x": 0, "y": num - 1}, "length": 8,
            "clue": "A clue with words in it (8)", "solution": solution,
            "group": [eid]}


def refused(solutions, want):
    p = {"id": "cryptic-30066", "number": 30066, "series": "cryptic",
         "source": {"publisher": "Guardian", "url": "https://x/",
                    "retrievedFrom": "publisher",
                    "acquiredBy": "tools/fetch_puzzle.py",
                    "acquiredOn": "2026-09-01", "gridOrigin": "published"},
         "solutions": solutions, "entries": [entry("1-across", 1)]}
    return any(want in f for f in provenance.check(p))


def gather():
    data = {"id": "crosswords/prize/30066", "number": 30066,
            "name": "Prize crossword No 30,066", "creator": {"name": "Tramp"},
            "date": 1784764800000, "dimensions": {"rows": 15, "cols": 15},
            "entries": [entry("1-across", 1, ""), entry("2-across", 2, "")]}

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "cryptic-30066.json"
        fetcher.write_puzzle_file(path, fetcher.convert(data))
        p = fetcher.read_puzzle_file(path)
        print("KEYS", ",".join(k for k in p if k != "entries"))
        print("SOURCE", ",".join(p["source"]), p["source"]["url"])
        print("UNSOLVED", json.dumps(p["solutions"]))

        # A model solve names its model; the origin follows from the detail.
        for e in p["entries"]:
            e["solution"] = "GUESSEDX"
        p = provenance.with_solution_detail(
            p, {"model": "claude-opus-5-5", "date": "2026-09-28",
                "check": "2 entries, 0 crossings, 0 conflicts"})
        p["source"]["acquiredOn"] = "2026-09-01"
        fetcher.write_puzzle_file(path, p)
        p = fetcher.read_puzzle_file(path)
        print("MODEL", p["solutions"]["origin"], ",".join(p["solutions"]))

        # A write-up's answers arrive on a fresh fetch, which states only the
        # detail; the model fill they replace is remembered.
        data["entries"] = [entry("1-across", 1), entry("2-across", 2)]
        fresh = provenance.with_solution_detail(fetcher.convert(data), {
            "blog": "fifteensquared", "url": "https://fifteensquared.net/x/",
            "date": "2026-09-28", "check": "2 entries verified"})
        fetcher.write_puzzle_file(path, fresh)
        p = fetcher.read_puzzle_file(path)
        print("WRITEUP", p["solutions"]["origin"], p["solutions"].get("previousOrigin"))

        # The paper prints its key: a fresh fetch carries no detail, so the answers
        # are the publisher's, the guess is remembered, the arrival date is kept.
        data["entries"] = [entry("1-across", 1), entry("2-across", 2)]
        fetcher.write_puzzle_file(path, fetcher.convert(data))
        p = fetcher.read_puzzle_file(path)
        print("PUBLISHED", json.dumps(p["solutions"]), p["source"]["acquiredOn"])
        print("SCHEMA", puzzle_schema.validate(p))
        print("FIXPOINT", provenance.stamp(p, p["source"]["acquiredBy"]) == p)
        # sourceUrl and provenance are not part of the shape.
        old = {**p, "sourceUrl": p["source"]["url"], "provenance": {}}
        print("OLDKEYS", len([x for x in puzzle_schema.validate(old)
                              if "sourceUrl" in x or "provenance" in x]))

    WRITEUP = {"origin": "writeup", "blog": "fifteensquared", "url": "https://f/",
               "date": "2026-09-01", "check": "1 entry"}
    print("OK_WRITEUP", provenance.check({
        "id": "cryptic-30066", "number": 30066, "series": "cryptic",
        "source": {"publisher": "Guardian", "url": "https://x/",
                   "retrievedFrom": "publisher", "acquiredBy": "tools/fetch_puzzle.py",
                   "acquiredOn": "2026-09-01", "gridOrigin": "published"},
        "solutions": WRITEUP, "entries": [entry("1-across", 1)]}))
    print("R_DETAIL", refused({"origin": "published", "date": "2026-09-01"}, "only back"))
    print("R_NOBLOG", refused({k: v for k, v in WRITEUP.items() if k != "blog"},
                              "has no blog"))
    print("R_BOTH", refused({**WRITEUP, "model": "m"}, "both a blog and a model"))
    print("R_REPEAT", refused({"origin": "published", "previousOrigin": "published"},
                              "repeats origin"))
    print("R_BADBLOG", refused({**WRITEUP, "blog": "somewhere"}, "solutions.blog"))


buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    gather()
out = {}
for ln in buf.getvalue().splitlines():
    out.setdefault(ln.split(" ", 1)[0], ln)


def line(key):
    return out.get(key, "")


print("a fetched puzzle writes source, solutions and nothing that repeats them")
same("top-level keys, in order", line("KEYS"),
     "KEYS id,number,prize,setter,date,dimensions,source,solutions")
same("source holds the url and how it was read", line("SOURCE"),
     "SOURCE publisher,url,retrievedFrom,acquiredBy,acquiredOn,gridOrigin https://www.theguardian.com/crosswords/prize/30066")
same("no answers: origin unsolved, no detail", line("UNSOLVED"),
     'UNSOLVED {"origin": "unsolved"}')
print("the detail keys decide the origin")
same("a model solve", line("MODEL"), "MODEL model origin,model,date,check")
same("a write-up replaces it and the guess is remembered", line("WRITEUP"), "WRITEUP writeup model")
same("the paper's key replaces it and the guess is remembered", line("PUBLISHED"),
     'PUBLISHED {"origin": "published", "previousOrigin": "model"} 2026-09-01')
same("the written file meets the schema", line("SCHEMA"), "SCHEMA []")
same("a second stamp changes nothing", line("FIXPOINT"), "FIXPOINT True")
same("the schema refuses sourceUrl and provenance", line("OLDKEYS"), "OLDKEYS 2")
print("provenance.check refuses solutions its detail does not back")
same("a full writeup passes", line("OK_WRITEUP"), "OK_WRITEUP []")
for r in ["R_DETAIL", "R_NOBLOG", "R_BOTH", "R_REPEAT", "R_BADBLOG"]:
    same(r, line(r), f"{r} True")

if fails:
    print(f"{fails} failure(s)")
    sys.exit(1)
print("PASS")
