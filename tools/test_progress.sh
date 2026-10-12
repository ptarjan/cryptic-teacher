#!/bin/bash
# Does /progress/ count each phase right? The backfill must date each puzzle's
# phases where tools/progress.py says, the build must replace today's file
# phases with its own index while carrying the ledger's counts forward, the
# paces must divide by days and not by points, and the page must draw every
# chart with today's totals in it.
#
#     bash tools/test_progress.sh
#
# A synthetic history and index, so nothing here reads the corpus or writes to
# the tree.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
out=$(TMP="$tmp" PYTHONPATH="$REPO/tools" python3 - <<'PY' 2>&1
import os
from datetime import date
from pathlib import Path
import progress as P
import progress_record as R
import build_seo_pages as B

rows = [("times-1", "times", "2026-10-01", "2026-10-01", True),
        ("times-2", "times", "2026-10-01", "2026-10-03", True),
        ("times-3", "times", "2026-10-02", None, False),
        ("azed-9", "azed", "2026-10-03", "2026-10-03", True)]
ledgers = {"2026-10-03": {"series": {"times": {"exist": 10, "filed": 3}}}}
days = R.backfill_days(rows, {"times-2": "2026-10-04"}, ledgers, "2026-10-04")
assert list(days) == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"], list(days)
assert days["2026-10-01"] == {"times": [None, None, 2, 1, 1, None, None]}, days["2026-10-01"]
assert days["2026-10-03"] == {"azed": [None, None, 1, 1, 1, None, None], "times": [10, 3, 3, 2, 1, None, None]}, days["2026-10-03"]
# times-2's hints date from its Annotate commit, not its filing.
assert days["2026-10-04"]["times"] == [None, None, 3, 2, 2, None, None], days["2026-10-04"]

path = Path(os.environ["TMP"]) / "progress.json"
P.save(days, path)
assert P.load(path) == days and len(path.read_text().splitlines()) == len(days) + 2
# A row saved before the queue phases existed stays five long on disk.
assert '"times":[10,3,3,2,1]' in path.read_text(), path.read_text()

# The read queue: downloaded and queued, recorded on two nights.
days["2026-10-05"] = P.day_row({"times": [3, 2, 2], "azed": [1, 1, 1]}, None, {"times": [100, 40]})
days["2026-10-07"] = P.day_row({"times": [3, 2, 2], "azed": [1, 1, 1]}, None, {"times": [110, 30]})
assert days["2026-10-07"]["times"] == [None, None, 3, 2, 2, 110, 30]
P.save(days, path)
assert P.load(path) == days

live = P.with_today(days, {"times": [5, 4, 3], "azed": [1, 1, 1]}, "2026-10-08")
assert live["2026-10-08"] == {"azed": [None, None, 1, 1, 1, None, None], "times": [10, 3, 5, 4, 3, 110, 30]}, live["2026-10-08"]
assert P.totals(live["2026-10-08"]) == [10, 3, 6, 5, 4, 110, 30]
# 10 downloaded and 20 read over the two days between the queue's nights.
assert B.queue_flow(days, 7) == (5, 10), B.queue_flow(days, 7)

pts = P.series_of(live, P.HINTED)
assert P.daily(pts)[-1] == ("2026-10-08", 1), P.daily(pts)
# Three puzzles hinted in the seven days since 10-01 (times-2, azed-9, the
# live one): a mean over days, not over the five points.
assert abs(P.rate(pts, 7) - 3 / 7) < 1e-9, P.rate(pts, 7)
assert P.rate(P.series_of(live, P.KNOWN), 7) == 0

# Every stage nests in the one above, per series and in total: downloaded is
# filed plus the unread, capped at known-but-unfiled; hinted needs solved.
assert P.file_counts([("a", True, True), ("a", False, True), ("a", True, False)]) == {"a": [3, 2, 1]}
cases = [[100, 90, 40, 30, 20, 500, 400],   # unread capped at known - filed = 60
         [100, 90, 40, 30, 20, 50, 10],
         [None, None, 76, 76, 76, None, None],   # no ledger: known follows downloaded
         [10, 10, 12, 12, 12, 3, 3],            # more filed than known
         [50, 5, 30, 40, 45, None, None]]       # stale solved/hinted above filed
for c in cases:
    n = P.nested(c)
    assert all(a >= b for a, b in zip(n, n[1:])), (c, n)
assert P.nested(cases[0]) == [100, 100, 40, 30, 20] and P.nested(cases[1]) == [100, 50, 40, 30, 20]
assert P.nested(cases[2]) == [76, 76, 76, 76, 76]
tot = P.nested_totals(dict(enumerate(cases)))
assert all(a >= b for a, b in zip(tot, tot[1:])), tot
assert tot == [sum(P.nested(c)[i] for c in cases) for i in range(5)]

assert B.at_pace(0, 5) == "done" and B.at_pace(10, 0) == "not moving"
assert B.at_pace(100, 10) == "10 days" and B.at_pace(3650, 1) == "10 years"

P.HISTORY = path
idx = {"puzzles": [{"series": "times", "hasSolutions": True, "annotated": True}] * 4
                  + [{"series": "times", "hasSolutions": False, "annotated": False}]}
html = B.progress_page(idx, today=date(2026, 10, 8))
assert html.count("<svg") == 5, html.count("<svg")
assert "5 not read yet" in html and "+5 in, &minus;10 read" in html and "read in 6 days" in html, html
assert "solved</td>" not in html, "solved has no pace of its own"
assert "<polyline" in html and "10 are known to exist" in html, html[:2000]
assert "{" not in html.split("<main", 1)[1].split("</main>")[0], "an unfilled placeholder"
print("ok")
PY
)
rc=$?
echo "$out"
[ "$rc" -eq 0 ] && [ "${out##*$'\n'}" = "ok" ] || { echo "FAIL: tools/test_progress.sh"; exit 1; }
