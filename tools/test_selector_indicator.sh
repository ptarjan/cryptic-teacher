#!/usr/bin/env bash
# A letter selector is an indicator: a block holds only the words it selects
# from ("capital of Bahrain" giving B is the indicator "capital of" and the
# block "Bahrain"), checked on new or changed annotations only.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy, json
import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def found(fragment, gives):
    return v.selector_in_block({"clueFragment": fragment, "gives": gives})

check("leading 'X of'", ("capital of", "Bahrain"), found("capital of Bahrain", "B"))
check("trailing adverb", ("initially", "Bahrain"), found("Bahrain, initially", "B"))
check("possessive noun", ("capital", "Bahrain"), found("Bahrain’s capital", "B"))
check("last letter", ("end of", "film"), found("end of film", "M"))
check("middle letters", ("at the centre", "time"), found("time at the centre", "IM"))
check("one letter from each word", ("originally", "Some incentive"),
      found("Some incentive originally", "SI"))
check("letters are not the selection", None, found("head of state", "PM"))
check("the source word alone", None, found("Bahrain", "B"))
check("a selector phrase alone", None, found("at last", "T"))

# telegraph-31356 24D, a frozen copy (tools/fixtures) so the corpus can move on
# under it. The file stores a tree: its blocks are view()'s, and a leaf holding
# the selector ("capital of Bahrain" giving B) is refused. 24D is edited so it
# counts as changed against HEAD; every other annotation is dropped, so only
# 24D is judged whatever HEAD holds at that path.
path = v.ROOT / "tools/fixtures/telegraph-31356.json"
puzzle = json.loads(path.read_text())
for f in puzzle["entries"]:
    if v.entry_id(f) != "24-down":
        f.pop("annotation", None)
fixed = copy.deepcopy(puzzle)
next(f for f in fixed["entries"] if v.entry_id(f) == "24-down")["annotation"]["explanation"]["surface"] += " "
def unfirst(node):
    for i, part in enumerate(node.get("parts") or []):
        if part.get("op") == "first" and part["parts"][0].get("words") == "Bahrain":
            node["parts"][i] = {"words": "capital of Bahrain", "gives": "B"}
        else:
            unfirst(part)
errors = []
v.check_selectors_are_indicators(fixed, path, errors)
check("fixed entry passes", [], errors)
inside = copy.deepcopy(fixed)
unfirst(next(f for f in inside["entries"] if v.entry_id(f) == "24-down")["annotation"]["wordplay"])
errors = []
v.check_selectors_are_indicators(inside, path, errors)
check("a leaf with its selector inside is checked", 1, len(errors))
check("message names the indicator and the block", True,
      bool(errors) and "'capital of'" in errors[0] and "'Bahrain'" in errors[0])

# A run's model clue lands through apply_annotations.normalize as the tree: a
# leaf with its selector inside is refused by the check, the selector written
# as the op's indicator passes.
import apply_annotations as A
e = {"number": 1, "direction": "across", "clue": {"text": "Capital of Bahrain on oar is wild pig", "enumeration": "4"},
     "solution": "BOAR"}
def landed(wp):
    pz = {"id": "t-1", "entries": [dict(e, annotation=A.normalize({"def": "wild pig", "wp": wp}, e, [e]))]}
    errors = []
    v.check_selectors_are_indicators(pz, v.ROOT / "tools/fixtures/no-such-puzzle.json", errors)
    return errors
check("a model leaf with its selector inside is refused", 1,
      len(landed("[Capital of Bahrain]B + [oar]OAR")))
check("the selector as the op's indicator passes", [],
      landed("first<Capital of>([Bahrain]) + [oar]OAR"))
raise SystemExit(fails)
PY
