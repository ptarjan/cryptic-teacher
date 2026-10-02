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
from groups import entry_id

tmp = Path(tempfile.mkdtemp())
# Offline: no second source fills what a case leaves out, and no ledger is kept.
corroborate.SOURCES = ()
corroborate.LEDGER = tmp / "ledger.json"


def real(pid):
    return fetcher.read_puzzle_file(fetcher.resolve_puzzle(pid))


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
    return next(e for e in p["entries"] if entry_id(e) == eid)


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

# A complete puzzle read off a newspaper scan writes with no byline (the 1970s
# FT printed none) and no answers (an unreadable solution grid).
ft = real("ftcryptic-13232")
p = {k: v for k, v in copy.deepcopy(ft).items()
     if k not in ("setter", "source", "solutions", "annotatedBy")}
p["source"] = {"url": "https://archive.org/details/FinancialTimes1975UKEnglish/page/n20"}
for e in p["entries"]:
    e.pop("solution", None)
    e.pop("annotation", None)
try:
    fetcher.write_puzzle_file(tmp / f"{p['id']}.json", p, generator="tools/file_archive_org_puzzles.py")
    print("WROTE scan-no-byline-no-answers")
except ValueError as err:
    print(f"REFUSED scan-no-byline-no-answers {err}")


p = copy.deepcopy(indy)
p["entries"][0]["clue"]["text"] = "dishe{s a la Mi}lanese " + p["entries"][0]["clue"]["text"]
write("braced-clue", p)

p = copy.deepcopy(indy)
p["entries"][0]["clue"]["text"] = "<i>Black Narcissus</i> " + p["entries"][0]["clue"]["text"]
write("markup-clue", p)

p = copy.deepcopy(indy)
p["entries"][0]["clue"]["text"] = "Cyclops \u0096 " + p["entries"][0]["clue"]["text"]
write("c1-clue", p)

p = copy.deepcopy(indy)
a = next(e for e in p["entries"] if e["direction"] == "across" and e.get("solution"))
a["solution"] = a["solution"][:-1] + ("Z" if a["solution"][-1] != "Z" else "Q")
write("crossing-conflict", p)

p = copy.deepcopy(indy)
blank = copy.deepcopy(indy)
first = entry(blank, entry_id(p["entries"][0]))
first["clue"] = {"enumeration": first["clue"]["enumeration"], "missing": True}
write("refetch-blanks-a-clue", blank, over=p)

p = copy.deepcopy(indy)
p["source"]["acquiredOn"] = "2020-01-01"
fresh = copy.deepcopy(indy)
del fresh["source"]
got = write("refetch-keeps-acquiredOn", fresh, over=p)
print("ACQUIRED", got and got["source"]["acquiredOn"])

p = copy.deepcopy(indy)
lead, cont = p["entries"][0], p["entries"][1]
lead["clue"]["enumeration"] = f"{lead['length']},{cont['length']}"
cont["clue"] = {"text": f"See {lead['number']}"}
lead["group"] = cont["group"] = [entry_id(lead), entry_id(cont)]
cont.pop("annotation", None)
write("continuation-holds-group", p)
del cont["group"]
write("leader-holds-group", p)

quick = real("timesquick-2000")
p = copy.deepcopy(quick)
lead = next(e for e in p["entries"] if not fetcher.is_continuation(e["clue"]["text"]))
del lead["clue"]["enumeration"]
write("blog-clue-no-enumeration", p)

p = copy.deepcopy(real("sundaytimes-5000"))
p["date"] = None
write("prize-not-yet-dated", p)

write("30098-blank-12a", real("cryptic-30098"))
write("23053-corrected", real("cryptic-23053"))


def day(y, m, d):
    return datetime.date(y, m, d)


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
# A book puzzle holds a `year` and no `date`, so the sweep hands it over undated.
dates("book-years", [("book", 1001, None, "book-1001"),
                     ("book", 1002, None, "book-1002")])

held, flags = [], []
for path in fetcher.puzzle_files():
    z = fetcher.read_puzzle_file(path)
    held.append((z.get("series", "cryptic"), z["number"], pi.date_of(z), z["id"]))
    pi.check_setter(z, flags)
pi.check_dates(held, flags)
print("CORPUS " + ("; ".join(f"{f} {pid} {w}" for f, pid, w in flags[:5]) or "clean"))
PY
)
echo "every puzzle write runs the corpus sweep's per-puzzle checks"
same "a healthy puzzle writes" "$(grep '^WROTE healthy$' <<<"$out")" "WROTE healthy"
same "a group held by its leader alone writes" "$(grep ' leader-holds-group' <<<"$out")" "WROTE leader-holds-group"
same "a continuation holding the group is refused" "$(grep ' continuation-holds-group' <<<"$out")" "REFUSED continuation-holds-group SHAPE"
same "a placeholder setter is refused" "$(grep ' placeholder-setter' <<<"$out")" "REFUSED placeholder-setter SETTER"
same "a syndication suffix on a setter is refused" "$(grep ' licensed-setter' <<<"$out")" "REFUSED licensed-setter SETTER"
same "a setter with stray whitespace is refused" "$(grep ' padded-setter' <<<"$out")" "REFUSED padded-setter SETTER"
same "a bylined series with no setter is refused" "$(grep ' bylined-null-setter' <<<"$out")" "REFUSED bylined-null-setter SETTER"
same "a complete scanned puzzle with no byline and no answers writes" "$(grep ' scan-no-byline-no-answers' <<<"$out")" "WROTE scan-no-byline-no-answers"
same "a feed puzzle with no date is refused" "$(grep ' feed-undated' <<<"$out")" "REFUSED feed-undated SHAPE"
same "a blog's braces in a clue are refused" "$(grep ' braced-clue' <<<"$out")" "REFUSED braced-clue SHAPE"
same "HTML in a clue is refused" "$(grep ' markup-clue' <<<"$out")" "REFUSED markup-clue SHAPE"
same "a C1 control character is refused" "$(grep ' c1-clue' <<<"$out")" "REFUSED c1-clue SHAPE"
same "a crossing conflict is refused" "$(grep ' crossing-conflict' <<<"$out")" "REFUSED crossing-conflict CROSS"
same "a re-fetch may not blank a clue the file has" "$(grep ' refetch-blanks-a-clue' <<<"$out")" "REFUSED refetch-blanks-a-clue SHAPE"
same "a re-fetch keeps the file's acquiredOn" "$(grep '^ACQUIRED ' <<<"$out")" "ACQUIRED 2020-01-01"
same "a blog clue without its count is refused" "$(grep ' blog-clue-no-enumeration' <<<"$out")" "REFUSED blog-clue-no-enumeration SHAPE"
same "a prize with no date is refused: the filer always fits one" "$(grep ' prize-not-yet-dated' <<<"$out")" "REFUSED prize-not-yet-dated SHAPE"
same "30098's deliberately blank 12-across writes" "$(grep ' 30098-blank-12a' <<<"$out")" "WROTE 30098-blank-12a"
same "23053's corrected answer writes" "$(grep ' 23053-corrected' <<<"$out")" "WROTE 23053-corrected"
same "rising dates pass" "$(grep '^DATES rising ' <<<"$out")" "DATES rising 0"
same "two numbers on one day are flagged" "$(grep '^DATES same-day ' <<<"$out")" "DATES same-day 1"
same "a later number dated earlier is flagged" "$(grep '^DATES backwards ' <<<"$out")" "DATES backwards 1"
same "book years are not a sequence" "$(grep '^DATES book-years ' <<<"$out")" "DATES book-years 0"
same "the corpus's setters and dates are clean" "$(grep '^CORPUS ' <<<"$out")" "CORPUS clean"

if [ "$fails" -gt 0 ]; then echo "$out" | grep -v '^\(WROTE\|REFUSED\|DATES\|ACQUIRED\|CORPUS\) ' | head -20; echo "puzzle_invariants: $fails check(s) failed"; exit 1; fi
echo "puzzle_invariants: all checks passed"
