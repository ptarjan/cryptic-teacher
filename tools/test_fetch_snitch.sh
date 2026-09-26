#!/bin/bash
# Does tools/fetch_snitch.py read the SNITCH's week table into the right puzzle
# ids, and drop the cells that are not a rating of that puzzle?
#
#     bash tools/test_fetch_snitch.sh
#
# A rating filed under the wrong id is a wrong point in the difficulty
# calibration and a wrong range on a Times badge. The fixture is rows cut from
# the live archive page, typos included, so nothing here touches the network.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

out=$(PYTHONPATH="$REPO/tools" python3 - "$REPO/tools/fixtures/snitch_archive.html" "$tmp/snitch.json" <<'PY'
import json, sys
from pathlib import Path
import fetch_snitch as F

got = F.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
show = lambda k: (f"{got[k]['nitch']}@{got[k]['date']}#{got[k]['snitch']}" if k in got else "absent")
print("COUNT", len(got))
print("MONDAY", show("times-29647"))
print("SATURDAY", show("times-29652"))
print("SUNDAY", show("sundaytimes-5233"))
print("ZERO", show("times-0"), show("times-28482"))
print("TYPO", show("times-230365"), show("times-27016"))
print("SPECIAL", show("sundaytimes-2024"), show("sundaytimes-1975"))
F.OUT = Path(sys.argv[2])
F.save(got)
back = json.loads(F.OUT.read_text(encoding="utf-8"))
print("ROUNDTRIP", back == got)
lines = F.OUT.read_text(encoding="utf-8").splitlines()
print("ORDER", lines[1].split(":")[0], lines[-2].split(":")[0])
PY
)
field() { printf '%s\n' "$out" | sed -n "s/^$1 //p"; }
check "every rated puzzle in the fixture read" "52" "$(field COUNT)"
check "a weekday cell is the Times daily, dated from its column" "87@2026-09-14#4196" "$(field MONDAY)"
check "Saturday is the Times daily too" "74@2026-09-19#4208" "$(field SATURDAY)"
check "Sunday is the Sunday Times" "107@2026-09-13#4202" "$(field SUNDAY)"
check "a NITCH of 0 is no rating" "absent absent" "$(field ZERO)"
check "a number out of sequence is a typo, and its neighbours stand" "absent 90@2018-04-19#715" "$(field TYPO)"
check "a Sunday special numbered by its year is not a Sunday Times" "absent absent" "$(field SPECIAL)"
check "the saved file reads back as parsed" "True" "$(field ROUNDTRIP)"
check "the saved file is sorted by series then number" '"sundaytimes-5232" "times-29652"' "$(field ORDER)"

if [ $fails -ne 0 ]; then echo "$fails check(s) failed"; exit 1; fi
echo "all fetch_snitch checks passed"
