#!/usr/bin/env bash
# Does an annotate run's output in the model's shape (`def`, `wp`, `notes`:
# tools/annotate_prompt.md's Schema) translate to the stored annotation, with a
# precise message when it does not check, and land in the file as the tree?
#
#     bash tools/test_annotate_model_shape.sh
#
# A puzzle's stored trees are rendered in the model's shape (annotation.to_model)
# and translated back (annotation.from_model); the view of both must agree.
# apply_annotations.normalize writes a model clue into the file as the tree,
# keeps a stored tree as it is, and refuses an old-prompt clue (type, blocks:
# the view's keys) with a message naming `def`, `wp` and `notes`.
# Everything is in memory except --patch, which works on a temp file.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import json
import tempfile
from pathlib import Path

import annotate_check as AC
import annotation
import apply_annotations as A
import fetch_puzzle as fp
import puzzle_schema as S
import wordplay as W

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else detail)

# A frozen copy (tools/fixtures), so the corpus can move on under it.
p = fp.read_puzzle_file(Path("fixtures/quiptic-619.json"))
by = {f"{e['number']}-{e['direction']}": e for e in p["entries"]}
model, same, tried = {}, 0, 0
for eid, e in by.items():
    new = e.get("annotation")
    if not new or any(n.get("unchecked") for n, _ in annotation._walk(new.get("wordplay") or {"parts": []})):
        continue
    # A note that only restates the abbreviation table has no model form:
    # to_model leaves it out and view() glosses from the table instead.
    new = copy.deepcopy(new)
    if new.get("wordplay"):
        annotation.strip_abbreviation_notes(new["wordplay"])
    m = annotation.to_model(new)
    model[eid] = m
    tried += 1
    back = annotation.from_model(json.loads(json.dumps(m)), e, p)
    same += annotation.view(back, e, p) == annotation.view(new, e, p)
check("model shape round-trips through from_model", tried > 20 and same == tried, f"{same}/{tried}")
check("the model shape has no derived key",
      not any(set(m) & set(annotation.DERIVED_KEYS) for m in model.values()))

def err(eid, change):
    m = copy.deepcopy(model[eid]); change(m)
    try:
        annotation.from_model(m, by[eid], p)
    except W.WordplayError as e:
        return str(e)
    return ""
check("a leaf with the wrong letters names it and the letters wanted",
      "[conservative]TORE gives TORE; the answer needs TORY here" in
      err("11-across", lambda m: m.update(wp=m["wp"].replace("TORY", "TORE"))))
check("a word not in the clue is named",
      "'turned' is not in the clue" in err("22-down", lambda m: m.update(wp="rev<turned>([Harry]YRRAH)")))
check("an old-prompt key says what to write instead",
      "write `def`, `wp` and `notes`" in err("11-across", lambda m: m.update(linkWords=["by"])))
check("a note naming no span is refused",
      "name no span" in err("11-across", lambda m: m["notes"].update(nowhere="x")))
check("a definition's note lands on the definition",
      annotation.from_model(dict(model["11-across"], notes={**model["11-across"]["notes"], "libellous": "adjective"}),
                            by["11-across"], p)["definitions"][0].get("note") == "adjective")
check("a double definition's notes are its meanings",
      [d.get("meaning") for d in annotation.from_model(model["10-across"], by["10-across"], p)["definitions"]]
      == [model["10-across"]["notes"]["Excellent"], model["10-across"]["notes"]["penalty"]])

# Into the file: the tree, every one checking and the file clean.
e = by["11-across"]
stored = A.normalize(model["11-across"], e, p["entries"], puzzle=p)
check("a model clue is stored as the tree",
      "wordplay" in stored and not set(stored) & (set(annotation.DERIVED_KEYS) - {"definitions"}), stored)
check("with the anagram the app's ring deals",
      annotation.view(stored, e, p).get("assembly", {}).get("anagrams"))
q = copy.deepcopy(p)
for x in q["entries"]:
    k = f"{x['number']}-{x['direction']}"
    if k in model:
        x["annotation"] = A.normalize(model[k], x, q["entries"], puzzle=q)
probs = []
annotation.view_puzzle(q, probs)
check("model clues keep the file clean, every tree checking",
      not S.format_problems(q) and not probs, (S.format_problems(q), probs))
check("a stored tree re-applied is kept as it is",
      all(A.normalize(x["annotation"], x, p["entries"], puzzle=p) == x["annotation"]
          for x in p["entries"] if x.get("annotation")))

# An old-prompt clue (the view's type, blocks, indicators, assembly) is refused,
# naming what to write instead.
old = {k: annotation.view(by[k]["annotation"], by[k], p) for k in model}
refused = 0
for k, o in old.items():
    try:
        A.normalize(o, by[k], p["entries"], puzzle=p)
    except W.WordplayError as x:
        refused += "write `def`, `wp` and `notes`" in str(x)
check("every old-prompt clue is refused, naming def, wp and notes", refused == len(old), f"{refused}/{len(old)}")

check("an old-prompt clue is not taken for the model's", not annotation.is_model(old["11-across"]))
check("a model clue with a stray derived key is still the model's",
      annotation.is_model({"def": "x", "wp": "[a]A", "type": ["charade"]}))

# --patch: fields replaced, notes merged note by note.
d = Path(tempfile.mkdtemp())
pending, fix = d / "_ann_x.json", d / "fix.json"
pending.write_text(json.dumps({"11-across": model["11-across"]}))
fix.write_text(json.dumps({"11-across": {"notes": {"Fake": "a new note on the anagram signal word", "made": None}}}))
check("--patch merges", AC.patch(pending, fix) is None)
n = json.loads(pending.read_text())["11-across"]["notes"]
check("one note replaced, one removed, the rest kept",
      n["Fake"].startswith("a new note") and "made" not in n and n["conservative"] == model["11-across"]["notes"]["conservative"])

print("model shape:", "all checks passed" if not fails else f"FAILED {fails}")
raise SystemExit(1 if fails else 0)
PY
