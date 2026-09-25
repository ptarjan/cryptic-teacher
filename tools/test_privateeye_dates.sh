#!/bin/bash
# Does tools/fetch_privateeye.py read the issue off every title shape the
# archive ships, and take the Eye's Christmas cover date as it prints it?
#
#     bash tools/test_privateeye_dates.sh
#
# Offline: the cover page is stubbed.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {
  if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: want [$2] got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import datetime
import fetch_privateeye as pe

print("PAIRS", pe.issue_number(400, "Eye 1245/400"), pe.issue_number(821, "Eye 821/1666"),
      pe.issue_number(538, "Eye 538/ 1383"))
print("ALONE", pe.issue_number(434, "Eye 1279"), pe.issue_number(436, "Eye 1280   (2 Feb '11)"),
      pe.issue_number(434, "Eye 434"))

covers = {1: datetime.date(2011, 1, 7), 2: datetime.date(2016, 12, 20),
          3: datetime.date(2007, 1, 20)}
pe.fetch_cover_date = covers.get
day = lambda issue: (ms := pe.cover_date(99, f"Eye 99/{issue}")) and str(
    datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).date())
print("COVERS", day(1), day(2), day(3))
PY
)
got() { echo "$out" | sed -n "s/^$1 //p"; }
check "an issue/number pair is read in either order" "1245 1666 1383" "$(got PAIRS)"
check "a title naming one number names the issue" "1279 1280 None" "$(got ALONE)"
check "a Friday and a Christmas cover date are kept, another weekday is not" \
  "2011-01-07 2016-12-20 None" "$(got COVERS)"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
