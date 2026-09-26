#!/bin/bash
# Does every puzzle write refuse what the corpus sweep would report?
#
#     bash tools/test_puzzle_invariants.sh
#
# fetch_puzzle.write_puzzle_file runs puzzle_integrity.check_puzzle on every
# write, so a fetcher cannot put on disk a defect an earlier fetcher shipped.
# Each case below takes a healthy puzzle from the corpus, gives it one defect
# a fetcher once wrote, and expects the write to be refused naming it; the
# deliberate shapes (cryptic-30098's blank 12-across, cryptic-23053's corrected
# answer, a Times prize the filer cannot date yet) must still write. The
# cross-puzzle DATE check is asked of synthetic rows and then of the corpus.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }

out=$(PYTHONPATH=tools python3 - <<'PY'
import copy
import datetime
import json
import tempfile
from pathlib import Path

import corroborate
import fetch_puzzle as fetcher
import puzzle_integrity as pi

tmp = Path(tempfile.mkdtemp())
# Offline: no second source fills what a case leaves out, and no ledger is kept.
corroborate.SOURCES = ()
corroborate.LEDGER = tmp / "ledger.json"


def real(pid):
    return fetcher.read_puzzle_file(fetcher.PUZZLE_DIR / f"{pid}.json")


def write(name, puzzle, over=None):
    """REFUSED <name> <first flag> or WROTE <name>, writing into a scratch dir."""
    path = tmp / f"{puzzle['id']}.json"
    if over is not None:
        path.write_text(json.dumps(over), encoding="utf-8")
    elif path.exists():
        path.unlink()
    try:
        fetcher.write_puzzle_file(path, puzzle)
    except ValueError as err:
        flag = str(err).split(": ", 1)[1].split(" ", 1)[0]
        print(f"REFUSED {name} {flag}")
        return None
    print(f"WROTE {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def entry(p, eid):
    return next(e for e in p["entries"] if e["id"] == eid)


indy = real("independent-12000")
write("healthy", indy)

p = copy.deepcopy(indy)
p["setter"] = "Unknown"
write("placeholder-setter", p)

p = copy.deepcopy(indy)
p["setter"] = "Juji / ©News Licensing/Times Media Limited"
write("licensed-setter", p)

p = copy.deepcopy(indy)
p["setter"] = "Picaroon "
write("padded-setter", p)

p = copy.deepcopy(indy)
p["setter"] = None
write("bylined-null-setter", p)

p = copy.deepcopy(indy)
p["date"] = None
write("feed-undated", p)

p = copy.deepcopy(indy)
p["entries"][0]["clue"] = "dishe{s a la Mi}lanese " + p["entries"][0]["clue"]
write("braced-clue", p)

p = copy.deepcopy(indy)
p["entries"][0]["clue"] = "<i>Black Narcissus</i> " + p["entries"][0]["clue"]
write("markup-clue", p)

p = copy.deepcopy(indy)
p["entries"][0]["clue"] = "Cyclops \u0096 " + p["entries"][0]["clue"]
write("c1-clue", p)

p = copy.deepcopy(indy)
a = next(e for e in p["entries"] if e["direction"] == "across" and e.get("solution"))
a["solution"] = a["solution"][:-1] + ("Z" if a["solution"][-1] != "Z" else "Q")
write("crossing-conflict", p)

p = copy.deepcopy(indy)
blank = copy.deepcopy(indy)
first = entry(blank, p["entries"][0]["id"])
first["clue"] = " " + fetcher.ENUMERATION.search(first["clue"]).group(0).strip()
first["clueMissing"] = True
write("refetch-blanks-a-clue", blank, over=p)

p = copy.deepcopy(indy)
p["provenance"]["acquiredOn"] = "2020-01-01"
fresh = copy.deepcopy(indy)
del fresh["provenance"]
got = write("refetch-keeps-acquiredOn", fresh, over=p)
print("ACQUIRED", got and got["provenance"]["acquiredOn"])

quick = real("timesquick-2000")
p = copy.deepcopy(quick)
lead = next(e for e in p["entries"] if not fetcher.is_continuation(e["clue"]))
lead["clue"] = fetcher.ENUMERATION.sub("", lead["clue"]).rstrip()
write("blog-clue-no-enumeration", p)

p = copy.deepcopy(real("sundaytimes-5000"))
p["date"] = None
write("prize-not-yet-dated", p)

write("30098-blank-12a", real("cryptic-30098"))
write("23053-corrected", real("cryptic-23053"))


def day(y, m, d):
    return int(datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc).timestamp() * 1000)


def dates(name, rows):
    flags = []
    pi.check_dates(rows, flags)
    print(f"DATES {name} {len(flags)}")


dates("rising", [("timesquick", 181, day(2014, 11, 17), "timesquick-181"),
                 ("timesquick", 182, day(2014, 11, 18), "timesquick-182")])
dates("same-day", [("timesquick", 181, day(2014, 11, 17), "timesquick-181"),
                   ("timesquick", 182, day(2014, 11, 17), "timesquick-182")])
dates("backwards", [("cryptic", 24744, day(2009, 7, 14), "cryptic-24744"),
                    ("cryptic", 24745, day(2009, 7, 7), "cryptic-24745")])
dates("pinned-gap", [("sundaytimes", 5020, day(2022, 9, 4), "sundaytimes-5020"),
                     ("sundaytimes", 5021, None, "sundaytimes-5021"),
                     ("sundaytimes", 5022, day(2022, 9, 18), "sundaytimes-5022")])
# The Jubilee week: two bank holidays for one Jumbo, so nothing proves 1559.
dates("jumbo-1559", [("timesjumbo", 1316, day(2018, 4, 2), "timesjumbo-1316"),
                     ("timesjumbo", 1540, day(2021, 12, 30), "timesjumbo-1540"),
                     ("timesjumbo", 1558, day(2022, 5, 28), "timesjumbo-1558"),
                     ("timesjumbo", 1559, None, "timesjumbo-1559"),
                     ("timesjumbo", 1560, day(2022, 6, 4), "timesjumbo-1560")])
dates("book-years", [("book", 1001, "1995", "book-1001"),
                     ("book", 1002, "1990", "book-1002")])

held, flags = [], []
for path in fetcher.puzzle_files():
    z = fetcher.read_puzzle_file(path)
    held.append((z.get("series", "cryptic"), z["number"], z.get("date"), z["id"]))
    pi.check_setter(z, flags)
pi.check_dates(held, flags)
print("CORPUS " + ("; ".join(f"{f} {pid} {w}" for f, pid, w in flags[:5]) or "clean"))
PY
)
echo "every puzzle write runs the corpus sweep's per-puzzle checks"
same "a healthy puzzle writes" "$(grep '^WROTE healthy$' <<<"$out")" "WROTE healthy"
same "a placeholder setter is refused" "$(grep ' placeholder-setter' <<<"$out")" "REFUSED placeholder-setter SETTER"
same "a syndication suffix on a setter is refused" "$(grep ' licensed-setter' <<<"$out")" "REFUSED licensed-setter SETTER"
same "a setter with stray whitespace is refused" "$(grep ' padded-setter' <<<"$out")" "REFUSED padded-setter SETTER"
same "a bylined series with no setter is refused" "$(grep ' bylined-null-setter' <<<"$out")" "REFUSED bylined-null-setter SETTER"
same "a feed puzzle with no date is refused" "$(grep ' feed-undated' <<<"$out")" "REFUSED feed-undated SHAPE"
same "a blog's braces in a clue are refused" "$(grep ' braced-clue' <<<"$out")" "REFUSED braced-clue SHAPE"
same "HTML in a clue is refused" "$(grep ' markup-clue' <<<"$out")" "REFUSED markup-clue SHAPE"
same "a C1 control character is refused" "$(grep ' c1-clue' <<<"$out")" "REFUSED c1-clue SHAPE"
same "a crossing conflict is refused" "$(grep ' crossing-conflict' <<<"$out")" "REFUSED crossing-conflict CROSS"
same "a re-fetch may not blank a clue the file has" "$(grep ' refetch-blanks-a-clue' <<<"$out")" "REFUSED refetch-blanks-a-clue SHAPE"
same "a re-fetch keeps the file's acquiredOn" "$(grep '^ACQUIRED ' <<<"$out")" "ACQUIRED 2020-01-01"
same "a blog clue without its count is refused" "$(grep ' blog-clue-no-enumeration' <<<"$out")" "REFUSED blog-clue-no-enumeration SHAPE"
same "a prize the filer cannot date yet still writes" "$(grep ' prize-not-yet-dated' <<<"$out")" "WROTE prize-not-yet-dated"
same "30098's deliberately blank 12-across writes" "$(grep ' 30098-blank-12a' <<<"$out")" "WROTE 30098-blank-12a"
same "23053's corrected answer writes" "$(grep ' 23053-corrected' <<<"$out")" "WROTE 23053-corrected"
same "rising dates pass" "$(grep '^DATES rising ' <<<"$out")" "DATES rising 0"
same "two numbers on one day are flagged" "$(grep '^DATES same-day ' <<<"$out")" "DATES same-day 1"
same "a later number dated earlier is flagged" "$(grep '^DATES backwards ' <<<"$out")" "DATES backwards 1"
same "an undated puzzle its neighbours pin is flagged" "$(grep '^DATES pinned-gap ' <<<"$out")" "DATES pinned-gap 1"
same "an undated Jumbo two holidays could hold is not" "$(grep '^DATES jumbo-1559 ' <<<"$out")" "DATES jumbo-1559 0"
same "book years are not a sequence" "$(grep '^DATES book-years ' <<<"$out")" "DATES book-years 0"
same "the corpus's setters and dates are clean" "$(grep '^CORPUS ' <<<"$out")" "CORPUS clean"

if [ "$fails" -gt 0 ]; then echo "$out" | grep -v '^\(WROTE\|REFUSED\|DATES\|ACQUIRED\|CORPUS\) ' | head -20; echo "puzzle_invariants: $fails check(s) failed"; exit 1; fi
echo "puzzle_invariants: all checks passed"
