#!/usr/bin/env bash
# Does the corpus decide which abbreviations are standard?
#
#     bash tools/test_corpus_abbreviations.sh
#
# tools/build_corpus_abbreviations.py counts every leaf whose note calls it an
# abbreviation and keeps a pair attested in MIN_PUZZLES puzzles from
# MIN_SERIES series and MIN_SETTERS setters. On synthetic puzzle files in a
# temp dir (never puzzles/): a widely used pair is in, one setter's habit and
# a thin pair are out, spans the table never holds are not counted, a
# stripped leaf still counts. Then the committed file: Paul's D for deserted
# is in the table, so its note now restates it.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import json
import tempfile
from pathlib import Path

import annotation as A
import build_corpus_abbreviations as C

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else detail)

root = Path(tempfile.mkdtemp())
files = []
def puzzle(n, series, setter, *leaves):
    path = root / series / "2026" / f"{series}-{n}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [{"number": i + 1, "direction": "across", "clue": {"text": "x", "enumeration": "1"},
                "solution": "X", "annotation": {"wordplay": {"op": "charade", "parts": [dict(l)]}}}
               for i, l in enumerate(leaves)]
    path.write_text(json.dumps({"id": f"{series}-{n}", "number": n, "setter": setter, "entries": entries}))
    files.append(path)

note = lambda g, w: {"words": w, "gives": g, "note": f"{g} is a recorded abbreviation for {w}"}
n = 0
for i in range(12):  # widely used: 12 puzzles, 4 series, 6 setters
    n += 1
    puzzle(n, f"s{i % 4}", f"setter{i % 6}", note("D", "deserted"), note("Y", "a year"),
           note("F", "fellow's"), {"words": "deserted", "gives": "D", "note": "D for deserted, on old maps"})
for i in range(20):  # one setter's habit, however often
    n += 1
    puzzle(n, "s0", "solo", note("S", "sex"))
for i in range(9):   # spread enough, one puzzle short
    n += 1
    puzzle(n, f"s{i % 5}", f"setter{i}", note("D", "god"))
for i in range(12):  # no note says abbreviation, and the table does not hold it
    n += 1
    puzzle(n, f"s{i % 4}", f"setter{i % 6}", {"words": "sailor", "gives": "TAR", "note": "a tar is a sailor"})
for i in range(12):  # stripped leaves on a pair the table already holds
    n += 1
    puzzle(n, f"s{i % 4}", f"setter{i % 6}", {"words": "name", "gives": "N"})

stats = C.count(files, frozenset({("NAME", "N")}))
out = C.build(stats)
pairs = {(g, w) for g, ws in out.items() for w in ws}
check("a widely used pair is standard", ("D", "deserted") in pairs, out)
row = out.get("D", {}).get("deserted", {})
check("its counts are kept as provenance",
      (row.get("puzzles"), row.get("series"), row.get("setters"), row.get("leaves")) == (12, 4, 6, 24), row)
check("one setter's habit is not", ("S", "sex") not in pairs)
check("nine puzzles is not enough", ("D", "god") not in pairs)
check("a leaf whose note never says abbreviation is no attestation", ("TAR", "sailor") not in pairs)
check("a span led by an article is not counted", not any(w == "a year" for _, w in stats))
check("a possessive span is not counted", not any(w == "fellow's" for _, w in stats))
check("a stripped leaf on a table pair still counts", ("N", "name") in pairs, out)
check("the build is a function of the counts", C.render(out) == C.render(C.build(C.count(files, frozenset({("NAME", "N")})))))

# The committed file, through the table every reader uses.
committed = json.loads(C.OUT.read_text(encoding="utf-8"))
check("Paul's D for deserted is in the committed file", "deserted" in committed.get("D", {}))
check("so the table holds it", A.is_abbreviation({"words": "deserted", "gives": "D"}))
check("and its note restates the table",
      A.restates_abbreviation({"words": "deserted", "gives": "D", "note": "D is a recorded abbreviation for deserted"}))
check("US for american, which no dictionary lists, is in", A.is_abbreviation({"words": "american", "gives": "US"}))
check("S for sex (one setter) is not", not A.is_abbreviation({"words": "sex", "gives": "S"}))
check("every committed pair clears the thresholds", all(
    r["puzzles"] >= C.MIN_PUZZLES and r["series"] >= C.MIN_SERIES and r["setters"] >= C.MIN_SETTERS
    for ws in committed.values() for r in ws.values()))

print("corpus abbreviations:", "all checks passed" if not fails else f"FAILED {fails}")
raise SystemExit(1 if fails else 0)
PY
