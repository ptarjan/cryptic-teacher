#!/bin/bash
# Does /puzzles/ describe each series without counting it?
# A series blurb with a count or puzzle number must be refused, the hub must
# not print a series' puzzle total, and each series with enough rated puzzles
# gets a difficulty strip whose median sits where its middle puzzle is.
#
#     bash tools/test_series_hub.sh
#
# A synthetic index, so nothing here reads the corpus or writes to the tree.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY' 2>&1
import app_tables as A
import build_seo_pages as B

def refused(text):
    try:
        A.series_blurbs(f'  const SERIES_BADGE = {{\n    x: ["x", `{text}`],\n  }};')
    except SystemExit:
        return True
    return False

print("COUNT", refused("now near 5,200") and refused("past 12400"))
print("GRID", not refused("a 13x13 grid, Penguin book 5 No 18"))
print("APP", bool(A.series_blurbs()))

ps = [{"series": "times", "number": i, "id": f"times-{i}", "date": "2025-01-01",
       "hasSolutions": True,
       "difficulty": {"percentile": 10 * (i % 10), "band": "Tough" if i % 10 >= 5 else "Gentle"}}
      for i in range(30)]
page = B.hub_page({"puzzles": ps})
section = page.split('<section class="s-series"', 1)[1].split("</section>", 1)[0]
print("NOTOTAL", "30 puzzle" not in section)
print("STRIP", page.count('class="chart strip"') == 1 and "harder than 50%" in page
      and "diff-tough" in page and 'class="median"' in page)
print("FEW", B.difficulty_strip("x", ps[:B.STRIP_MIN - 1]) == "")
PY
)
echo "$out"
for k in COUNT GRID APP NOTOTAL STRIP FEW; do
  echo "$out" | grep -qx "$k True" || { echo "FAIL: $k"; exit 1; }
done
echo "PASS"
