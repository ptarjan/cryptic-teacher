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

# telegraph-31356 24D with its selector put back in the block, and as fixed but
# edited, so both count as changed against HEAD. A frozen legacy copy
# (tools/fixtures): legacy blocks and normalize() are the subject, and the
# corpus file may be format v2.
path = v.ROOT / "tools/fixtures/telegraph-31356-legacy.json"
puzzle = json.loads(path.read_text())
e = next(e for e in puzzle["entries"] if v.entry_id(e) == "24-down")
fixed = copy.deepcopy(puzzle)
next(f for f in fixed["entries"] if v.entry_id(f) == "24-down")["annotation"]["explanation"]["surface"] += " "
b = next(b for b in e["annotation"]["blocks"] if b["gives"] == "B")
b["clueFragment"] = "capital of Bahrain"
errors = []
v.check_selectors_are_indicators(puzzle, path, errors)
check("changed entry is checked", 1, len(errors))
check("message names the indicator and the block", True,
      "'capital of'" in errors[0] and "'Bahrain'" in errors[0])
errors = []
v.check_selectors_are_indicators(fixed, path, errors)
check("fixed entry passes", [], errors)

# A format v2 file stores a tree: its blocks are view()'s, and a leaf holding
# the selector ("capital of Bahrain" giving B) is refused the same way.
import convert_v2
v2, _ = convert_v2.migrate_puzzle(fixed)
for f in v2["entries"]:  # HEAD's copy is legacy, so every v2 annotation is "changed": keep 24D's only
    if v.entry_id(f) != "24-down":
        f.pop("annotation", None)
def unfirst(node):
    for i, part in enumerate(node.get("parts") or []):
        if part.get("op") == "first" and part["parts"][0].get("words") == "Bahrain":
            node["parts"][i] = {"words": "capital of Bahrain", "gives": "B"}
        else:
            unfirst(part)
errors = []
v.check_selectors_are_indicators(v2, path, errors)
check("a v2 file's fixed entry passes", [], errors)
unfirst(next(f for f in v2["entries"] if v.entry_id(f) == "24-down")["annotation"]["wordplay"])
errors = []
v.check_selectors_are_indicators(v2, path, errors)
check("a v2 leaf with its selector inside is checked", 1, len(errors))

# apply_annotations.normalize writes that fix itself: the run's block with its
# selector inside goes to disk as the block and the indicator.
import apply_annotations as A
split = A.normalize(e["annotation"], e, puzzle["entries"])
sb = next(b for b in split["blocks"] if b["gives"] == "B")
check("normalize splits the block", ("Bahrain", "first"), (sb["clueFragment"], sb.get("select")))
check("and adds the selector as an indicator", 1,
      sum(i.get("text") == "capital of" and i.get("for") == "letter_selection"
          for i in split["indicators"]))
check("and letter_selection to type", True, "letter_selection" in split["type"])
fixed2 = copy.deepcopy(puzzle)
next(f for f in fixed2["entries"] if v.entry_id(f) == "24-down")["annotation"] = split
errors = []
v.check_selectors_are_indicators(fixed2, path, errors)
check("the split passes the check", [], errors)
again = A.normalize(split, e, puzzle["entries"])
check("a second normalize changes nothing", split["indicators"], again["indicators"])
def one(fragment, gives, inds=()):
    return A.split_selectors({"type": ["charade"], "blocks": [{"clueFragment": fragment, "gives": gives}],
                              "indicators": list(inds)})
check("last letter", ({"clueFragment": "dinner", "gives": "R", "select": "last"}, "end of"),
      (one("end of dinner", "R")["blocks"][0], one("end of dinner", "R")["indicators"][0]["text"]))
check("a possessive keeps its word", "Party", one("Party's conclusion", "Y")["blocks"][0]["clueFragment"])
check("an indicator already listed is not doubled", 1,
      len(one("Irish leader", "I", [{"text": "leader", "for": "letter_selection", "note": "n"}])["indicators"]))
check("several source words are left to the run", "last bit of money",
      one("last bit of money", "Y")["blocks"][0]["clueFragment"])
check("several letters are left to the run", "a lender's first",
      one("a lender's first", "AL")["blocks"][0]["clueFragment"])
check("a note that teaches", True,
      len(one("Irish leader", "I")["indicators"][0]["note"]) >= 25)
raise SystemExit(fails)
PY
