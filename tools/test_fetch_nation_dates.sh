#!/bin/bash
# Does fetch_nation date a page printing no issue on the issue clock, so it
# sorts between its neighbours instead of before the number below it?
#
#     bash tools/test_fetch_nation_dates.sh
#
# A page printing "This article appears in the June 25, 2012 issue" is dated
# by that issue, about three weeks after it went online; one printing none was
# dated the day it went online, so nation-3244 (posted 2012-06-13) sorted
# before 3243 (issue 2012-06-25) and puzzle_integrity refused fifteen backfill
# solves on DATE (2026-10-13). issue_date() lends the nearest number's lag.
# Synthetic lags only: no held page is read.
set -uo pipefail
cd "$(dirname "$0")/.."
out=$(PYTHONPATH="$PWD/tools" python3 - <<'PY'
import datetime as dt
import fetch_nation as F
D = dt.date.fromisoformat
lags = {3243: (D("2012-06-05"), D("2012-06-25")),   # the real 3243
        3261: (D("2012-11-14"), D("2012-12-03"))}
print("A3244", F.issue_date(3244, "2012-06-13", lags))
print("A3245", F.issue_date(3245, "2012-06-25", lags))
print("FAR", F.issue_date(3243 + F.ISSUE_REACH + 1 + 40, "2013-01-01", {3243: lags[3243]}))
print("NOPOST", F.issue_date(3244, None, lags))
page = ('<meta property="og:title" content="Puzzle No. 3244">'
        '<meta property="article:published_time" content="2012-06-13T10:00:00">')
m = F.meta(page)
print("META", m["date"], m["issued"], m["posted"])
PY
)
fails=0
expect() { grep -qxF "$1" <<<"$out" && echo "  ok: $2" || { echo "  FAIL: $2 (want '$1')"; echo "$out"; fails=$((fails+1)); }; }
expect "A3244 2012-07-02" "a page posted a week after 3243 takes 3243's lag, on its Monday cover date"
expect "A3245 2012-07-16" "the next page lands after it, so the series rises"
expect "FAR None" "no number printing both within ISSUE_REACH lends a lag"
expect "NOPOST None" "a page with no posted day gets no derived issue"
expect "META 2012-06-13 False 2012-06-13" "meta keeps the posted day and says no issue was printed"
[ "$fails" = 0 ] && echo "fetch_nation dates: all checks passed" || echo "fetch_nation dates: $fails FAILED"
exit $((fails > 0))
