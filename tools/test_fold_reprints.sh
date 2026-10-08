#!/bin/bash
# Does fold_reprints.rekeyer rename a folded id both as a whole JSON string and
# as the lead of one ("globeandmail-3334 2-down MOSS", a "canberra-750213/11-across"
# key of tools/data/source_clue_wrong.json), and leave a longer
# number, a mid-string mention and other series alone?
#
#     bash tools/test_fold_reprints.sh
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import fold_reprints as F

sub = F.rekeyer({"globeandmail-3334": "timesquick-3334"})
cases = (
    ("whole string", '["globeandmail-3334"]', '["timesquick-3334"]'),
    ("object key", '{"globeandmail-3334": 1}', '{"timesquick-3334": 1}'),
    ("leads a string", '"globeandmail-3334 2-down MOSS"', '"timesquick-3334 2-down MOSS"'),
    ("leads a light key", '"globeandmail-3334/2-down"', '"timesquick-3334/2-down"'),
    ("longer number then slash", '"globeandmail-33345/2-down"', '"globeandmail-33345/2-down"'),
    ("longer number", '"globeandmail-33345"', '"globeandmail-33345"'),
    ("longer number then space", '"globeandmail-33345 1-down X"', '"globeandmail-33345 1-down X"'),
    ("mid-string", '"see globeandmail-3334 2-down"', '"see globeandmail-3334 2-down"'),
    ("other id", '"globeandmail-3335 2-down MOSS"', '"globeandmail-3335 2-down MOSS"'),
)
fails = 0
for what, text, want in cases:
    got = sub(text)
    ok = got == want
    fails += not ok
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else f": expected {want!r}, got {got!r}"))
raise SystemExit(1 if fails else 0)
PY

# Does reprints.merged keep the original's clue where neither copy annotates
# it, take the reprint's annotated clue whole where only the reprint does,
# fill a missing answer, and lose none of the reprint's lights (reprints.lost)?
python3 - <<'PY'
import reprints as R

def entry(n, text, solution=None, annotation=None):
    e = {"number": n, "direction": "across", "position": {"x": 0, "y": n}, "length": 4,
         "clue": {"text": text, "enumeration": "4"}}
    return {**e, **({"solution": solution} if solution else {}),
            **({"annotation": annotation} if annotation else {})}

times = {"id": "times-1", "series": "times", "number": 1, "dimensions": {"cols": 4, "rows": 4},
         "source": {"url": "t"}, "solutions": {"origin": "unsolved"},
         "entries": [entry(1, "Times words"), entry(2, "Times slip"), entry(3, "Both", "ABCD", {"by": "t"})]}
canberra = {"id": "canberra-2", "series": "canberra", "number": 2, "date": "1975-01-01",
            "dimensions": {"cols": 4, "rows": 4}, "source": {"reprintOf": "times-1"},
            "solutions": {"origin": "model"}, "annotatedBy": ["m"],
            "entries": [entry(1, "Canberra words", "WXYZ"), entry(2, "Canberra fix", "EFGH", {"by": "c"}),
                        entry(3, "Both", "ABCD", {"by": "c"})]}
out = R.merged(times, canberra)
got = {e["number"]: (e["clue"]["text"], e.get("solution"), (e.get("annotation") or {}).get("by"))
       for e in out["entries"]}
cases = (
    ("unannotated light keeps the original's words, takes the answer", got[1], ("Times words", "WXYZ", None)),
    ("annotated reprint light moves whole", got[2], ("Canberra fix", "EFGH", "c")),
    ("original's annotation stays", got[3], ("Both", "ABCD", "t")),
    ("reprint's print recorded", out["source"]["reprintedIn"], [{"series": "canberra", "number": 2, "date": "1975-01-01"}]),
    ("solutions block of the copy answering more", out["solutions"], {"origin": "model"}),
    ("nothing of the reprint lost", R.lost(canberra, out), []),
    ("a dropped answer is caught", R.lost(canberra, times)[:1], ["1-across answer WXYZ now None"]),
    ("a different answer is a mismatch", R.mismatch({**times, "entries": [entry(1, "x", "QQQQ")]},
                                                    {**canberra, "entries": [entry(1, "x", "WXYZ")]}),
     "1-across answered WXYZ against QQQQ"),
)
fails = 0
for what, have, want in cases:
    ok = have == want
    fails += not ok
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else f": expected {want!r}, got {have!r}"))
raise SystemExit(1 if fails else 0)
PY
