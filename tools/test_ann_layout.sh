#!/usr/bin/env bash
# annotate_check's fix-ups rewrite only the values they change in
# tools/_ann_<ID>.json, so the run's next Edit of text it wrote still matches.
#
#     bash tools/test_ann_layout.sh
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import json, pathlib, tempfile
import annotate_check as C

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

# The layout the runs write: one entry's fields packed a few to a line.
WRITTEN = '''{
  "1-across": {"answer": "LABOUR SAVING", "type": ["charade"],
    "definitions": [{"text": "reducing effort"}],
    "blocks": [
      {"clueFragment": "party", "gives": "LABOUR", "at": 3},
      {"clueFragment": "Spending less", "gives": "SAVING"}
    ],
    "explanation": {"walkthrough": "w", "definitionFit": "f"}},
  "2-down": null,
  "3-down": {"answer": "X", "linkWords": ["the"]}
}
'''
pending = pathlib.Path(tempfile.mkdtemp()) / "_ann_t-1.json"

def rewrite(change):
    pending.write_text(WRITTEN, encoding="utf-8")
    ann = json.loads(WRITTEN)
    change(ann)
    C.write_pending(pending, ann)
    out = pending.read_text(encoding="utf-8")
    return ann, out

def fixups(ann):  # what normalize, recut and fill_missing do to a run's file
    ann["1-across"]["blocks"][0].pop("at")
    ann["1-across"]["assembly"] = {"pieces": ["LABOUR", "SAVING"]}
    del ann["3-down"]["linkWords"]
    ann["4-across"] = None

ann, out = rewrite(fixups)
check("the rewrite holds the new values", json.loads(out) == ann)
for line in ('{"clueFragment": "Spending less", "gives": "SAVING"}',
             '"explanation": {"walkthrough": "w", "definitionFit": "f"}',
             '"definitions": [{"text": "reducing effort"}],'):
    check(f"untouched text kept for the next Edit: {line[:40]}", line in out)
check("a changed value is rewritten in place",
      '{"clueFragment": "party", "gives": "LABOUR"},' in out)
check("an added key goes on the end", out.rstrip().endswith('"4-across": null\n}'))

_, out = rewrite(lambda a: None)
check("nothing changed, nothing rewritten", out == WRITTEN)

def drop_first(a):
    del a["1-across"]
ann, out = rewrite(drop_first)
check("dropping the first entry still parses", json.loads(out) == ann)
check("1 and true are not the same value",
      json.loads(rewrite(lambda a: a.update({"2-down": True}))[1])["2-down"] is True)

pending.write_text("{not json", encoding="utf-8")
C.write_pending(pending, {"a": 1})
check("a file that does not parse is written whole", json.loads(pending.read_text()) == {"a": 1})
raise SystemExit(fails)
PY
echo "all _ann layout checks passed"
