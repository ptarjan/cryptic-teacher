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
def raises(fn, *args):
    try:
        fn(*args)
    except ValueError as err:
        return str(err)
    return None

served = page(591, -1187485200000, -1187485200000)
check("a page that is the one requested passes", raises(fp.check_served, 591, served) is None)
msg = raises(fp.check_served, 592, served)
check("a page whose id is another number is refused, saying both",
      msg is not None and "requested cryptic/prize 592" in msg and "crosswords/cryptic/591" in msg)
served["id"] = "crosswords/quiptic/591"
check("a page whose id is another series is refused",
      raises(fp.check_served, 591, served) is not None)
def clues(prefix, n=10):
    return [{"clue": {"text": f"{prefix} clue number {i} (5)"}} for i in range(n)]

def held_puzzle(pid, date, entries):
    held = {"id": pid, "date": date, "entries": entries}
    puzzle_paths.file_for(held).parent.mkdir(parents=True, exist_ok=True)
    puzzle_paths.file_for(held).write_text(json.dumps(held))

def served(number, entries):
    return {"id": f"cryptic-{number}", "number": number, "entries": entries}

held_puzzle("quiptic-591", "2011-03-14", clues("alpha"))
held_puzzle("cryptic-25545", "2011-03-15", clues("beta"))
fp._CLUE_INDEX = None  # rebuilt from the scratch tree

msg = raises(fp.check_not_copy, served(591, clues("alpha")))
check("cryptic 591 carrying quiptic 591's clues is refused, naming both",
      msg is not None and "requested cryptic-591" in msg and "quiptic-591" in msg
      and "10 of 10" in msg)
msg = raises(fp.check_not_copy, served(2545, clues("beta")))
check("cryptic 2545 carrying cryptic 25545's clues (another number) is refused",
      msg is not None and "requested cryptic-2545" in msg and "cryptic-25545" in msg)
nearly = clues("beta")
nearly[0] = {"clue": {"text": "Reworded entirely (4)"}}
msg = raises(fp.check_not_copy, served(2545, nearly))
check("a copy with one of ten clues changed is still refused, saying 9 of 10",
      msg is not None and "9 of 10" in msg)
half = clues("beta")[:5] + clues("gamma")[5:]
check("a puzzle sharing half its clues is filed",
      raises(fp.check_not_copy, served(2545, half)) is None)
check("a genuine new puzzle is filed", raises(fp.check_not_copy, served(2546, clues("delta"))) is None)
check("a puzzle is not a copy of itself on refresh",
      raises(fp.check_not_copy, served(25545, clues("beta"))) is None)
print("FAILED: %d" % fails if fails else "all ok")
sys.exit(1 if fails else 0)
PY
