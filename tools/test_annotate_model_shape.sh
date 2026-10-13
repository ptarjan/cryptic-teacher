#!/usr/bin/env bash
# Does an annotate run's output in the model's shape (`def`, `wp`, `notes`:
# tools/annotate_prompt.md's Schema) translate to the stored annotation, with a
# precise message when it does not check, and land in a file of either shape?
#
#     bash tools/test_annotate_model_shape.sh
#
# Corpus annotations are rendered in the model's shape (annotation.to_model of
# convert_v2's tree) and translated back (annotation.from_model); the view of
# both must agree. apply_annotations.normalize writes a model clue into a
# legacy file as its view and into a v2 file as the tree, and an old-prompt
# clue (type, blocks) the old way, or through convert_v2 into a v2 file.
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
import convert_v2
import fetch_puzzle as fp
import puzzle_schema as S
import wordplay as W

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else detail)

# A frozen legacy copy (tools/fixtures): the legacy annotations are the subject,
# and the corpus file is format v2 from step 8 on.
p = fp.read_puzzle_file(Path("fixtures/quiptic-619-legacy.json"))
by = {f"{e['number']}-{e['direction']}": e for e in p["entries"]}
model, same, tried = {}, 0, 0
for eid, e in by.items():
    st, _, new = convert_v2.check(e["annotation"], e, p)
    if st == "failed" or any(n.get("unchecked") for n, _ in annotation._walk(new.get("wordplay") or {"parts": []})):
        continue
    m = annotation.to_model(new)
    model[eid] = m
    tried += 1
    back = annotation.from_model(json.loads(json.dumps(m)), e, p)
    same += annotation.view(back, e, p) == annotation.view(new, e, p)
check("model shape round-trips through from_model", tried > 20 and same == tried, f"{same}/{tried}")
check("the model shape has no derived key",
      not any(set(m) & set(annotation.LEGACY_KEYS) for m in model.values()))

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
check("a legacy key says what to write instead",
      "write `def`, `wp` and `notes`" in err("11-across", lambda m: m.update(linkWords=["by"])))
check("a note naming no span is refused",
      "name no span" in err("11-across", lambda m: m["notes"].update(nowhere="x")))
check("a definition's note lands on the definition",
      annotation.from_model(dict(model["11-across"], notes={**model["11-across"]["notes"], "libellous": "adjective"}),
                            by["11-across"], p)["definitions"][0].get("note") == "adjective")
check("a double definition's notes are its meanings",
      [d.get("meaning") for d in annotation.from_model(model["10-across"], by["10-across"], p)["definitions"]]
      == [model["10-across"]["notes"]["Excellent"], model["10-across"]["notes"]["penalty"]])

# Into a legacy file: the view, which the legacy schema takes.
e = by["11-across"]
legacy = A.normalize(model["11-across"], e, p["entries"], v2=False, puzzle=p)
check("into a legacy file it is legacy-shaped", "blocks" in legacy and "type" in legacy and "wordplay" not in legacy)
check("with the anagram the app's ring deals", legacy.get("assembly", {}).get("anagrams"))
q = copy.deepcopy(p)
for x in q["entries"]:
    k = f"{x['number']}-{x['direction']}"
    if k in model:
        x["annotation"] = A.normalize(model[k], x, q["entries"], v2=False, puzzle=q)
check("a legacy file stays wholly legacy", not S.is_v2(q) and not S.format_problems(q), S.format_problems(q))

# Into a v2 file: the tree; an old-prompt clue goes through convert_v2.
conv, _ = convert_v2.convert_puzzle(p)
old = {k: {f: v for f, v in x["annotation"].items() if f != "assembly"} for k, x in by.items()}
for label, src in (("model", model), ("old-prompt", old)):
    q = copy.deepcopy(conv)
    for x in q["entries"]:
        k = f"{x['number']}-{x['direction']}"
        if k in src:
            x["annotation"] = A.normalize(src[k], x, q["entries"], v2=True, puzzle=q)
    probs = []
    annotation.view_puzzle(q, probs)
    check(f"{label} clues into a v2 file keep it wholly v2, every tree checking",
          S.is_v2(q) and not S.format_problems(q) and not probs, (S.format_problems(q), probs))

check("an old-prompt clue is not taken for the model's", not annotation.is_model(old["11-across"]))
check("a model clue with a stray legacy key is still the model's",
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
