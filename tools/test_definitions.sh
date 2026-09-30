#!/usr/bin/env bash
# A definition's `at` is computed from its text by the rules in
# tools/definitions.py, refused where they leave it ambiguous, and checked by
# validate_annotations against the clue.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import definitions as D
import puzzle_schema
import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def at(clue, *texts):
    return [d["at"] for d in D.place([{"text": t} for t in texts], clue)]

check("once", [4], at("Big cat", "cat"))
check("whole words: not inside Part", [23], at("Part of medicine man’s art", "art"))
check("the enumeration is not in the text", [0], at("4, whichever way you look at it!", "4"))
check("at an end: last of two", [41], at("Speak about Irish city, but not northern city", "city"))
check("at an end: first of two", [0], at("Down, as in Watership Down?", "Down, as"))
check("no overlap with the other definition, in clue order", [0, 6],
      at("Down, as in Watership Down?", "Down", "as in Watership Down?"))
check("a given `at` that points at its text is kept", [22],
      [d["at"] for d in D.place([{"text": "Down", "at": 22}], "Down, as in Watership Down?")])
check("a wrong `at` is recomputed", [4],
      [d["at"] for d in D.place([{"text": "cat", "at": 1}], "Big cat")])
check("straight quotes typed for curly ones take the clue's spelling", ["Don\u2019t panic"],
      [d["text"] for d in D.place([{"text": "Don't panic"}], "Don\u2019t panic \u2014 and don\u2019t shave!")])
check("note is kept", "why", D.place([{"text": "cat", "note": "why"}], "Big cat")[0]["note"])

def refused(clue, *texts):
    try:
        D.place([{"text": t} for t in texts], clue)
    except ValueError as err:
        return str(err)
    return None
check("both ends is ambiguous", True, "occurs 3 times" in (refused("up and up and up", "up") or ""))
check("not in the clue", True, "not in the clue" in (refused("Big cat", "dog") or ""))

def errors(defs):
    puzzle = {"id": "t-1", "entries": [{"number": 1, "direction": "across",
              "clue": {"text": "Changes colour", "enumeration": "9"}, "solution": "TURNSTONE",
              "annotation": {"type": ["charade"], "answer": "TURNSTONE", "explanation": {"walkthrough": "w"},
                             "definitions": defs, "assembly": {"pieces": ["TURNS", "TONE"]},
                             "blocks": [{"clueFragment": "Changes", "gives": "TURNS"},
                                        {"clueFragment": "colour", "gives": "TONE"}]}}]}
    return [e for e in v.validate_puzzle(puzzle_schema.order(puzzle))[1] if "definition" in e]
check("validator: `at` on its text", [], errors([{"text": "Changes", "at": 0}]))
check("validator: `at` off its text", True,
      any("is not at 3" in e for e in errors([{"text": "Changes", "at": 3}])))
raise SystemExit(fails)
PY
echo "all definition placement checks passed"
