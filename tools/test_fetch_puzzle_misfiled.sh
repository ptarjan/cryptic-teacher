#!/bin/bash
# Does fetch_puzzle.convert() refuse a mis-filed Guardian page and accept a
# re-published one?
#
#     bash tools/test_fetch_puzzle_misfiled.sh
#
# Both arrive with a `date` far from `webPublicationDate`. /crosswords/cryptic/1183
# serves Quiptic 1,183 under 1934 and must be refused; cryptic 26,752 was
# re-published on 2016-01-25 with its own date intact between its neighbours
# and must be filed.
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import json, pathlib, sys, tempfile
sys.path.insert(0, "tools")
import fetch_puzzle as fp

DAY = 86_400_000
tmp = pathlib.Path(tempfile.mkdtemp())
fp.PUZZLE_DIR = tmp
for n, d in ((26751, 1449705600000), (26753, 1449878400000)):   # 2015-12-10, 12-12
    (tmp / f"cryptic-{n}.json").write_text(json.dumps({"id": f"cryptic-{n}", "date": d}))

def page(number, date, published):
    return {"id": f"crosswords/cryptic/{number}", "number": number, "name": "x",
            "date": date, "webPublicationDate": published,
            "creator": {"name": "Setter"}, "dimensions": {"cols": 3, "rows": 1},
            "entries": [{"id": "1-across", "number": 1, "direction": "across",
                         "position": {"x": 0, "y": 0}, "length": 3,
                         "clue": "Feline (3)", "solution": "CAT", "group": ["1-across"],
                         "separatorLocations": {}}]}

fails = 0
def check(why, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + why)
    fails += not ok

def refused(data):
    try:
        fp.convert(data)
    except ValueError:
        return True
    return False

check("a re-published page whose date fits its neighbours is filed",
      not refused(page(26752, 1449792000000, 1453680000000)))
check("a page far from any neighbour is refused",
      refused(page(1183, -1134086400000, 1657756800000)))
check("a page between neighbours but dated a year away is refused",
      refused(page(26752, 1449792000000 - 365 * DAY, 1453680000000)))
print("FAILED: %d" % fails if fails else "all ok")
sys.exit(1 if fails else 0)
PY
