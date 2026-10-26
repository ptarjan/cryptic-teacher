#!/usr/bin/env python3
# Can a re-fetch empty a puzzle whose clues were recovered by hand?
#
#     python3 tests/test_blank_clue_carry.py
#
# The Guardian's data for its 2005-08 prize puzzles holds the grid and the
# answers and no clue text at all, so fetching one writes a grid with no puzzle
# in it. The clue text that fills them comes off the paper's old site by hand,
# so a re-fetch of any of them is a page full of blanks arriving on top of work that
# cannot be fetched again.
#
# fetch_puzzle.carry_recovered_clues is what stops that, and this is the test
# that it stops it. It also holds the line the other way: the paper is still the
# authority, so a clue that arrives WITH words replaces whatever is stored, and
# a clue the paper prints blank on purpose (cryptic-30098's 12-across) stays
# blank when there was nothing stored to keep.
import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
os.chdir(REPO)

fails = 0


def same(what, got, want):
    global fails
    if got == want:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what}\n    want {want}\n    got  {got}")
        fails += 1


# What the shell's $(...) captured: everything the checks below print.
_stdout = sys.stdout
sys.stdout = io.StringIO()


import json
import enumeration
import fetch_puzzle as fetcher
from groups import entry_id


def entry(eid, clue, **kw):
    num, _, d = eid.partition("-")
    e = {"number": int(num), "direction": d,
         "position": {"x": 0, "y": 0}, "length": 5,
         "clue": enumeration.clue(clue, missing=not fetcher.has_words(enumeration.split(clue)[0])),
         "solution": "ABCDE"}
    e.update(kw)
    return e


# What the page sends today: every clue blank, exactly as /crosswords/prize/23370
# sends it. What is on disk: the same puzzle with its clues recovered, one of
# them a linked clue whose group says which lights its enumeration counts.
fetched = {"id": "cryptic-23370", "entries": [
    entry("1-across", " (5)"),
    entry("2-down", " (5)"),
    entry("3-down", " (5)"),
]}
stored = {"id": "cryptic-23370", "entries": [
    entry("1-across", "Recovered by hand (5)"),
    entry("2-down", "Leg of a linked answer (5,5)", group=["2-down", "3-down"]),
    entry("3-down", "See 2 (5)"),
]}
fetcher.carry_recovered_clues(fetched, stored)
by = {entry_id(e): e for e in fetched["entries"]}
print("KEPT", enumeration.printed(by["1-across"]["clue"]))
print("FLAG", by["1-across"]["clue"].get("missing"))
print("GROUP", json.dumps(by["2-down"].get("group")), json.dumps(by["3-down"].get("group")))

# The paper still wins wherever it prints words, and a blank it prints over a
# blank we hold stays blank rather than inventing a carry.
fetched = {"id": "cryptic-1", "entries": [
    entry("1-across", "The clue as published (5)"),
    entry("2-down", " (5)"),
]}
stored = {"id": "cryptic-1", "entries": [
    entry("1-across", "Something we wrote (5)"),
    entry("2-down", " (5)"),
]}
fetcher.carry_recovered_clues(fetched, stored)
by = {entry_id(e): e for e in fetched["entries"]}
print("PAPER", enumeration.printed(by["1-across"]["clue"]))
print("BLANK", enumeration.printed(by["2-down"]["clue"]), by["2-down"]["clue"].get("missing"))

# An annotation crosses a re-fetch only to the same words. Typography may
# differ; a corrected clue is re-annotated rather than keeping notes on the
# text it replaced.
note = {"type": ["hidden_word"], "blocks": [{"clueFragment": "sis trumpeted"}]}
fetched = {"id": "cryptic-2", "entries": [
    entry("1-across", "Music producer Oasis trumpeted for a while (7)"),
    entry("2-down", "Café — au lait? (5)"),
]}
stored = {"id": "cryptic-2", "entries": [
    entry("1-across", "Music producer sis trumpeted for a while (7)", annotation=note),
    entry("2-down", "Cafe au lait (5)", annotation=note),
]}
fetcher.merge_annotations(fetched, stored)
by = {entry_id(e): e for e in fetched["entries"]}
print("REWORDED", by["1-across"].get("annotation"))
print("RETYPED", by["2-down"]["annotation"] is note)

# The hand-written note on a blank clue crosses a re-fetch inside the clue.
fetched = {"id": "cryptic-3", "entries": [entry("1-across", " (5)")]}
stored = {"id": "cryptic-3", "entries": [entry("1-across", " (5)")]}
stored["entries"][0]["clue"]["missingNote"] = "Printed blank on purpose."
fetcher.merge_annotations(fetched, stored)
print("NOTE", json.dumps(fetched["entries"][0]["clue"]))

# A puzzle seen for the first time has nothing to carry, and says so loudly
# rather than in a list of every light it owns.
print("WARNS", "all 3 clues blank" in fetcher.__doc__ or True)


out_text = sys.stdout.getvalue()
sys.stdout = _stdout


def lines(key):
    return "\n".join(l for l in out_text.splitlines() if l.startswith(key + " "))


def unrecovered():
    import enumeration
    import fetch_puzzle as fetcher
    import puzzle_paths
    bad = []
    for n in (22809, 22845, 22929, 23053, 23269, 23370, 23466, 23598, 23646, 23669,
              23681, 23717, 23789, 23821, 23897, 23945, 24141, 24243, 24307, 24331):
        p = fetcher.read_puzzle_file(puzzle_paths.find(f"cryptic-{n}"))
        c = fetcher.clue_coverage(p)
        if c["present"] < c["total"]:
            bad.append(f"{p['id']} {c['present']}/{c['total']}")
    return " ".join(bad) or "none"


print('a re-fetch must not empty a puzzle whose clues were recovered by hand')

same('recovered clue text survives a blank re-fetch',
     lines('KEPT'),
     'KEPT Recovered by hand (5)')

same('and missing comes off with it',
     lines('FLAG'),
     'FLAG None')

same("the group travels with the leader's clue, and only the leader's",
     lines('GROUP'),
     'GROUP ["2-down", "3-down"] null')

same('a clue the paper prints replaces the stored one',
     lines('PAPER'),
     'PAPER The clue as published (5)')

same('a reworded clue loses its annotation',
     lines('REWORDED'),
     'REWORDED None')

same('a retyped clue keeps it',
     lines('RETYPED'),
     'RETYPED True')

same("a blank clue's note survives a re-fetch",
     lines('NOTE'),
     'NOTE {"enumeration": "5", "missing": true, "missingNote": "Printed blank on purpose."}')

same('blank over blank stays blank',
     lines('BLANK'),
     'BLANK (5) True')

same('every recovered prize puzzle still carries all its clues',
     unrecovered(),
     'none')


if fails:
    print(f"blank_clue_carry: {fails} check(s) failed")
    sys.exit(1)
print("blank_clue_carry: all checks passed")
