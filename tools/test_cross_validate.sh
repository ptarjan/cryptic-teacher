#!/bin/bash
# Does tools/cross_validate.py name each way two copies of a puzzle differ?
#
#     bash tools/test_cross_validate.sh
#
# Offline: one healthy puzzle in our shape, and one mutation of it per class.
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import copy
import sys

sys.path.insert(0, "tools")
import cross_validate as cv

fails = 0


def same(what, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else f": got {got!r}, want {want!r}"))


def entry(n, d, x, y, sol, text, enum=None):
    clue = {"text": text, "enumeration": enum or str(len(sol))}
    return {"number": n, "direction": d, "position": {"x": x, "y": y},
            "length": len(sol), "clue": clue, "solution": sol}


base = {"id": "telegraph-1", "dimensions": {"cols": 3, "rows": 3}, "entries": [
    entry(1, "across", 0, 0, "CAT", "Tom’s pet"), entry(1, "down", 0, 0, "CAB", "Taxi"),
    entry(2, "down", 2, 0, "TOE", "Digit"), entry(3, "across", 0, 2, "BEE", "Buzzer")]}


def classes(mutate):
    ours = copy.deepcopy(base)
    mutate(ours)
    return sorted(m["class"] for m in cv.diff(ours, base))


same("a copy is clean", classes(lambda p: None), [])
same("quotes, dashes, case and spacing are not a clue difference",
     classes(lambda p: p["entries"][0]["clue"].update(text="TOM'S  pet!")), [])
same("other words are", classes(lambda p: p["entries"][0]["clue"].update(text="Kitty")), ["CLUE"])
same("a count", classes(lambda p: p["entries"][1]["clue"].update(enumeration="1,2")),
     ["ENUMERATION"])
same("an answer", classes(lambda p: p["entries"][3].update(solution="BYE")), ["ANSWER"])
same("a number", classes(lambda p: p["entries"][2].update(number=4)), ["NUMBERING"])
same("another grid", classes(lambda p: p["entries"][3]["position"].update(y=1)), ["GRID"])
row = next(m for m in cv.diff(
    {**base, "entries": [*base["entries"][:3], entry(3, "across", 0, 2, "BEA", "Buzzer")]}, base))
same("an answer says which crossings agree with each side",
     (row["oursCross"], row["theirsCross"]), ((2, 1), (2, 2)))

page = {"id": "crosswords/prize/30074", "number": 30074, "dimensions": {"cols": 3, "rows": 3},
        "entries": [{"number": 1, "direction": "across", "position": {"x": 0, "y": 0}, "length": 3,
                     "clue": "<i>Tom</i>&rsquo;s\u200b  pet (3)", "solution": "cat"},
                    {"number": 2, "direction": "down", "position": {"x": 2, "y": 0}, "length": 3,
                     "clue": "See 1", "solution": "TOE"}]}
got = cv.guardian_shape(page, "https://www.theguardian.com/crosswords/prize/30074")
same("a Guardian page is read without the converter: tags, entities and the count",
     (got["id"], got["entries"][0]["clue"], got["entries"][0]["solution"]),
     ("cryptic-30074", {"text": "Tom’s pet", "enumeration": "3"}, "CAT"))
same("a Guardian pointer has no count", got["entries"][1]["clue"]["enumeration"], None)
same("a source clue with no words is no witness",
     sorted(m["class"] for m in cv.diff(base, {**base, "entries": [
         {**base["entries"][0], "clue": {"text": "", "enumeration": "1,2"}}, *base["entries"][1:]]})),
     [])

import fetch_puzzle as fp
data = {"id": "crosswords/quiptic/1090", "number": 1090, "name": "Quiptic No 1,090",
        "creator": {"name": "Pan"}, "date": 1600000000000, "dimensions": {"cols": 3, "rows": 3},
        "entries": [{"id": "1-across", "number": 1, "direction": "across",
                     "position": {"x": 0, "y": 0}, "length": 3, "group": ["1-across"],
                     "clue": " Tom’s pet (3)", "solution": "CAT"}]}
same("a clue the page prints with a space in front converts without it",
     fp.convert(data)["entries"][0]["clue"]["text"], "Tom’s pet")
print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
PY
