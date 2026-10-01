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
import puzzle_paths

DAY = 86_400_000
puzzle_paths.PUZZLE_DIR = pathlib.Path(tempfile.mkdtemp())
for n, d in ((26751, "2015-12-10"), (26753, "2015-12-12")):
    held = {"id": f"cryptic-{n}", "date": d}
    puzzle_paths.file_for(held).parent.mkdir(parents=True, exist_ok=True)
    puzzle_paths.file_for(held).write_text(json.dumps(held))

def page(number, date, published):
    return {"id": f"crosswords/cryptic/{number}", "number": number, "name": "x",
            "date": date, "webPublicationDate": published,
            "creator": {"name": "Setter"}, "dimensions": {"cols": 3, "rows": 1},
            "entries": [{"number": 1, "direction": "across",
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
# The archive's islands far below the run (cryptic 591, 1932) carry a date
# their own webPublicationDate agrees with, so no neighbour is needed.
island = page(591, -1187485200000, -1187485200000)
check("an archive page whose two dates agree is filed with no neighbours",
      not refused(island))
island["creator"] = {"name": "a"}
check("a one-letter creator is an anonymous placeholder, not a setter",
      fp.convert(island)["setter"] is None)
print("FAILED: %d" % fails if fails else "all ok")
sys.exit(1 if fails else 0)
PY
