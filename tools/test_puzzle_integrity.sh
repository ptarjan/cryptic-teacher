#!/bin/bash
# Does puzzle_integrity catch every kind of defect it claims to, and do its two
# exception tables forgive exactly the findings they name, and nothing else?
#
#     bash tools/test_puzzle_integrity.sh
#
# This tests the CHECKER, on fixtures: real puzzles copied into memory or into
# a scratch puzzles/ directory and mutated there, so it runs in seconds and
# never writes under the repo's puzzles/. Whether the corpus itself is clean is
# a different question, answered by running the checker over all of it:
#
#     python3 tools/puzzle_integrity.py --quiet
#
# CI runs that once, as its own step, not here.
#
# Every flag in puzzle_integrity.FLAGS, plus DUPLICATE, has a fixture below
# that raises it and only it (a DUPLICATE shares every clue, so NEARDUP comes
# with it); the test fails if FLAGS grows a kind that has no fixture here.
#
# PUBLISHED_WRONG and UNLINKED_IN_SOURCE are keyed by (puzzle id, whole finding
# string), so that forgiving one sentence forgives nothing else about that
# clue. The property under test: lengthening every key's finding string by one
# trailing space must reproduce every finding the tables forgive, since a
# prefix or substring match would still swallow some of them. Both tables are
# checked separately, with their sizes read off len(), so a key that no longer
# matches a live finding fails the run. Every key names its puzzle, so only the
# puzzles the tables name are read for this.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
fails=0
check() { if grep -qF -- "$2" <<<"$1"; then echo "  ok: $3"; else
  echo "  FAIL: $3"$'\n'"    wanted to find: $2"$'\n'"    in: $1"; fails=$((fails + 1)); fi; }
absent() { if grep -qF -- "$2" <<<"$1"; then
  echo "  FAIL: $3"$'\n'"    did not want to find: $2"$'\n'"    in: $1"; fails=$((fails + 1));
  else echo "  ok: $3"; fi; }
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }
field() { awk -v k="$1" '$1==k {print $2}' <<<"$2"; }
# A heredoc that died prints no fields, and empty fields say nothing of why.
died() { if grep -q '^Traceback' <<<"$1"; then echo "  FAIL: $2 crashed:"
  sed 's/^/    /' <<<"$1"; fails=$((fails + 1)); fi; }

echo "each per-file check flags its own defect, and nothing else"
out1=$(PYTHONPATH="$REPO/tools" python3 - 2>&1 <<'PY'
import copy
from datetime import date
import puzzle_integrity as pi
from groups import entry_id

TODAY = date(2026, 10, 5)
# cryptic-24104 holds two findings UNLINKED_IN_SOURCE forgives, so every
# mutation below also proves forgiving them does not blank out the rest of it.
# cryptic-24447 holds the corpus's three-plus-light group ALL AND SUN DRY.
# times-29329 is annotated, so its clue can be edited out from under its annotation.
base = {pid: pi.read_puzzle_file(pi.puzzle_paths.find(pid))
        for pid in ("cryptic-24104", "cryptic-24447", "times-29329")}


def kinds(pid, mutate=None):
    p = copy.deepcopy(base[pid])
    if mutate:
        mutate(p, {entry_id(e): e for e in p["entries"]})
    flags = []
    pi.check_puzzle(p, TODAY, flags)
    return ",".join(sorted({f[0] for f in flags})) or "none"


def reorder(p, by):
    g = by["13-across"]["group"]
    by["13-across"]["group"] = [g[0]] + g[1:][::-1]


def alter(p, by):
    p["preamble"] = "Some answers are altered."
    by["2-down"]["alteration"] = {"from": "YANKS", "steps": [{"op": "anagram"}]}


def off_board(p, by):
    # Unanswered, so the shifted light breaks no crossing: GRID alone.
    by["1-across"]["position"]["x"] = 1
    del by["1-across"]["solution"]


MUTATIONS = {
    "LENGTH": ("cryptic-24104", lambda p, by: by["1-across"]["clue"].update(enumeration="3,4,2,1,6")),
    "ORDER": ("cryptic-24447", reorder),
    "APOSTROPHE": ("cryptic-24104", lambda p, by: by["1-across"]["clue"].update(enumeration="3,4,2,1'5")),
    "CROSS": ("cryptic-24104", lambda p, by: by["1-across"].update(solution="Z" + by["1-across"]["solution"][1:])),
    "CELLS": ("cryptic-24104", lambda p, by: p.update(printed=[{"x": 0, "y": 0, "letter": "Z"}])),
    "ALTERED": ("cryptic-24104", alter),
    "GRID": ("cryptic-24104", off_board),
    "NUMBER": ("cryptic-24104", lambda p, by: by["30-across"].update(number=31)),
    "SETTER": ("cryptic-24104", lambda p, by: p.update(setter="Unknown")),
    "SHAPE": ("cryptic-24104", lambda p, by: by["2-down"]["clue"].update(text="")),
    "PROV": ("cryptic-24104", lambda p, by: p["solutions"].update(origin="bogus")),
    # The clue cleaned in place and its annotation left quoting the old words.
    # A known copy of another puzzle, filed under its own id.
    "REPRINT": ("cryptic-24104", lambda p, by: p["source"].update(reprintOf="times-1")),
    "CURLY": ("cryptic-24104", lambda p, by: by["2-down"]["clue"].update(
        text=by["2-down"]["clue"]["text"] + " \u2018it\u2019s\u2019")),
    "QUOTE": ("times-29329", lambda p, by: by["20-down"]["clue"].update(
        text=by["20-down"]["clue"]["text"].replace("Dip ", "Plunge "))),
}
for pid in base:
    print("PRISTINE", pid, kinds(pid))
for flag, (pid, mutate) in MUTATIONS.items():
    print("FLAG", flag, kinds(pid, mutate))
# DATE, FILED and NEARDUP are cross-file; the CLI section below raises them.
print("UNCOVERED", ",".join(sorted(set(pi.FLAGS) - set(MUTATIONS) - {"DATE", "FILED", "NEARDUP"})) or "none")
PY
)
died "$out1" "the per-file fixtures"
for pid in cryptic-24104 cryptic-24447; do
  same "$pid as published is clean" "$(awk -v p="$pid" '$1=="PRISTINE" && $2==p {print $3}' <<<"$out1")" "none"
done
while read -r _ flag raised; do
  same "a $flag defect is flagged $flag alone" "$raised" "$flag"
done < <(grep '^FLAG ' <<<"$out1")
same "every flag in FLAGS has a fixture" "$(field UNCOVERED "$out1")" "none"

echo "a clue that says 'See preamble' with no preamble is written, and never sent for annotation"
out_pre=$(PYTHONPATH="$REPO/tools" python3 - 2>&1 <<'PY'
import copy
from datetime import date
import puzzle_integrity as pi

real = pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-24104"))
for name, pre in (("BARE", None), ("WITH", "1 Across is unclued.")):
    p = copy.deepcopy(real)
    p["entries"][0]["clue"]["text"] = "See preamble"
    if pre:
        p["preamble"] = pre
    flags = []
    pi.check_puzzle(p, date(2026, 10, 5), flags)
    print(name, pi.awaits_preamble(p), any("preamble" in f[2] for f in flags))
try:
    p = copy.deepcopy(real)
    p["entries"][0]["clue"]["text"] = "Unclued (see the preamble)"
    pi.refuse_bad_write(p)
    print("WRITE allowed")
    print("INDEXED", pi.awaits_preamble(p))
except pi.RefusedWrite as e:
    print("WRITE", f"refused: {e}")
for name, slug in (("SPECIAL", "playfair"), ("PLAIN", "plain-christmas"), ("COMP", "plain-competition-puzzle"),
                   ("BARENUM", "")):
    p = copy.deepcopy(real)
    p["series"] = "azed"
    p["source"]["url"] = f"https://fifteensquared.net/2021/08/22/azed-no-2566{'-' + slug if slug else ''}/"
    print(name, pi.awaits_preamble(p))
PY
)
died "$out_pre" "the see-preamble fixture"
same "an Azed special from its blog awaits its preamble" "$(field SPECIAL "$out_pre")" "True"
same "a plain Christmas Azed does not" "$(field PLAIN "$out_pre")" "False"
same "a plain competition Azed does not" "$(field COMP "$out_pre")" "False"
same "an Azed post named by number alone does not" "$(field BARENUM "$out_pre")" "False"
same "'See preamble' with no preamble awaits its preamble" "$(field BARE "$out_pre")" "True"
same "'See preamble' with a preamble does not" "$(field WITH "$out_pre")" "False"
same "the write path accepts it" "$(field WRITE "$out_pre")" "allowed"
same "'(see the preamble)' awaits too" "$(field INDEXED "$out_pre")" "True"

echo "a run that left answers to a missing preamble marks the puzzle to await one"
out_await=$(PYTHONPATH="$REPO/tools" SCRATCH="$scratch/await" python3 - 2>&1 <<'PY'
import copy, json, os
from datetime import date
from pathlib import Path
import await_preamble
import fetch_puzzle
import puzzle_integrity as pi
import puzzle_paths

path = puzzle_paths.find("cryptic-24319")
real = pi.read_puzzle_file(path)
bare = copy.deepcopy(real)
del bare["preamble"]
print("WHICH", "-".join(await_preamble.which(path, bare)) or "none")
print("HELD", "-".join(await_preamble.which(path, real)) or "none")
other = copy.deepcopy(bare)
next(e for e in other["entries"] if e.get("annotation")
     and not e["annotation"].get("definedByPreamble"))["annotation"].pop("answer")
print("OTHER", "-".join(await_preamble.which(path, other)) or "none")
flagged = dict(bare, awaitsPreamble=True)
print("FLAGGED", pi.awaits_preamble(flagged))
print("ARRIVED", pi.awaits_preamble(dict(flagged, preamble="Unclued answers are birds.")))
flags = []
pi.check_puzzle(dict(flagged, preamble="Unclued answers are birds."), date(2026, 10, 10), flags)
print("BESIDE", any("awaitsPreamble beside" in f[2] for f in flags))
out = Path(os.environ["SCRATCH"]) / f"{real['id']}.json"
out.parent.mkdir(parents=True)
fetch_puzzle.write_puzzle_file(out, copy.deepcopy(flagged))
fetch_puzzle.write_puzzle_file(out, copy.deepcopy(bare))
print("KEPT", json.loads(out.read_text()).get("awaitsPreamble"))
fetch_puzzle.write_puzzle_file(out, dict(copy.deepcopy(flagged), preamble="Unclued answers are birds."))
print("DROPPED", "awaitsPreamble" not in json.loads(out.read_text()))
PY
)
died "$out_await" "the await-preamble fixture"
same "the run's sole failure is the missing preamble: its entries are listed" "$(field WHICH "$out_await" | grep -c '[0-9][AD]')" "1"
same "a puzzle holding its preamble awaits none" "$(field HELD "$out_await")" "none"
same "a run that failed on anything else too is parked instead" "$(field OTHER "$out_await")" "none"
same "awaitsPreamble keeps it from the annotators" "$(field FLAGGED "$out_await")" "True"
same "until a preamble is filed" "$(field ARRIVED "$out_await")" "False"
same "the flag beside a preamble is flagged" "$(field BESIDE "$out_await")" "True"
same "a rewrite with no preamble keeps the flag" "$(field KEPT "$out_await")" "True"
same "filing a preamble drops it" "$(field DROPPED "$out_await")" "True"

echo "the CLI on a scratch corpus: clean exits 0; DUPLICATE, NEARDUP and DATE across files exit 1"
out2=$(PYTHONPATH="$REPO/tools" SCRATCH="$scratch/cli" python3 - 2>&1 <<'PY'
import contextlib, copy, io, json, os, re
from datetime import date, timedelta
from pathlib import Path
import puzzle_integrity as pi
import puzzle_paths

real = pi.read_puzzle_file(puzzle_paths.find("cryptic-24447"))
root = Path(os.environ["SCRATCH"])
puzzle_paths.PUZZLE_DIR = root / "puzzles"
pi.CACHE = root / "integrity-rows.pickle"
puzzle_paths.PUZZLE_DIR.mkdir(parents=True)


def put(p):
    path = puzzle_paths.file_for(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p))
    return path


def sibling(day, same_clues=0):
    """cryptic-24448 on `day`; its first `same_clues` clues are 24447's, the
    rest made its own."""
    p = copy.deepcopy(real)
    p.update(id="cryptic-24448", number=24448, date=day)
    p["source"]["url"] = p["source"]["url"].replace("24447", "24448")
    for i, e in enumerate(p["entries"]):
        if i >= same_clues and e["clue"].get("text"):
            e["clue"]["text"] = f"Other {i} " + e["clue"]["text"]
    return p


def cli(name):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = pi.main([])
    text = out.getvalue()
    tallies = {m[0]: int(m[1]) for m in re.findall(r"^  (\w+) +(\d+)", text, re.M)}
    raised = ",".join(sorted(k for k, n in tallies.items() if n)) or "none"
    print(name, rc, raised)


put(real)
day = date.fromisoformat(real["date"])
later, earlier = str(day + timedelta(days=7)), str(day - timedelta(days=7))
for name, p in [("CLEAN", sibling(later)),
                ("DATE", sibling(earlier)),
                ("NEARDUP", sibling(later, same_clues=len(real["entries"]) - 1)),
                ("DUPLICATE", sibling(later, same_clues=len(real["entries"])))]:
    path = put(p)
    cli(name)
    path.unlink()
# The same copy, listed in clue_index.REPRINTS: one puzzle the paper printed twice.
import clue_index
clue_index.REPRINTS[frozenset(("cryptic-24447", "cryptic-24448"))] = "fixture"
path = put(sibling(later, same_clues=len(real["entries"])))
cli("REPRINT")
path.unlink()
PY
)
died "$out2" "the scratch-corpus CLI"
same "two clean puzzles: exit 0, every tally 0" "$(grep '^CLEAN ' <<<"$out2" | cut -d' ' -f2-)" "0 none"
same "a later number dated earlier: exit 1, DATE alone" "$(grep '^DATE ' <<<"$out2" | cut -d' ' -f2-)" "1 DATE"
same "all but one clue shared: exit 1, NEARDUP alone" "$(grep '^NEARDUP ' <<<"$out2" | cut -d' ' -f2-)" "1 NEARDUP"
# A copy shares every clue too, so NEARDUP rides along with DUPLICATE.
same "the same puzzle under another id: exit 1, DUPLICATE" "$(grep '^DUPLICATE ' <<<"$out2" | cut -d' ' -f2-)" "1 DUPLICATE,NEARDUP"
same "the same puzzle as a listed reprint: exit 0, every tally 0" "$(grep '^REPRINT ' <<<"$out2" | cut -d' ' -f2-)" "0 none"

echo "exactness: a lengthened key must not still match, and dropping one table must not touch the other"
combo=$(PYTHONPATH="$REPO/tools" python3 - 2>&1 <<'PY'
from datetime import datetime, timezone
import puzzle_integrity as pi

today = datetime.now(timezone.utc).date()

# Every key names its puzzle, so the puzzles the tables name are the only
# ones whose findings the tables can change. check_shape reads neither table,
# so it runs once per puzzle; every variant below reruns the rest in memory.
named = sorted({pid for pid, _ in [*pi.PUBLISHED_WRONG, *pi.UNLINKED_IN_SOURCE]})
cache = []
for pid in named:
    puzzle = pi.read_puzzle_file(pi.puzzle_paths.find(pid))
    cache.append((puzzle, pi.check_shape(puzzle, today, [])))

def length_count():
    # Every check that consults the tables, so a dropped key shows up in this
    # total whichever check would have produced its finding. The counts below
    # are read off len(table), so a check left out here reads as keys that
    # forgive nothing and fails the run.
    flags = []
    for puzzle, checkable in cache:
        pi.check_length(puzzle, checkable, flags)
        pi.check_grid(puzzle, flags)
        pi.check_numbering(puzzle, flags)
        pi.check_cross(puzzle, checkable, flags)
    return len(flags)

orig_pw = dict(pi.PUBLISHED_WRONG)
orig_uis = dict(pi.UNLINKED_IN_SOURCE)
print("TABLE_SIZES", len(orig_pw), len(orig_uis))
print("BASELINE", length_count())

def lengthen(table):
    # One trailing space on every finding string. A prefix or substring match
    # would still find the original text inside this and stay silent; an exact
    # match cannot, and the finding must reappear.
    return {(pid, finding + " "): note for (pid, finding), note in table.items()}

pi.PUBLISHED_WRONG = lengthen(orig_pw)
pi.UNLINKED_IN_SOURCE = lengthen(orig_uis)
print("LENGTHENED_BOTH", length_count())
pi.PUBLISHED_WRONG, pi.UNLINKED_IN_SOURCE = orig_pw, orig_uis

pi.PUBLISHED_WRONG = {}
print("DROP_PUBLISHED_WRONG", length_count())
pi.PUBLISHED_WRONG = orig_pw

pi.UNLINKED_IN_SOURCE = {}
print("DROP_UNLINKED_IN_SOURCE", length_count())
pi.UNLINKED_IN_SOURCE = orig_uis

print("RESTORED", length_count())
PY
)
died "$combo" "the exactness check"
n_pw=$(awk '$1=="TABLE_SIZES" {print $2}' <<<"$combo")
n_uis=$(awk '$1=="TABLE_SIZES" {print $3}' <<<"$combo")
same "the puzzles the tables name report nothing with both tables in place" \
  "$(field BASELINE "$combo")" "0"
same "lengthening every key by one trailing space reproduces all $((n_pw + n_uis)) findings" \
  "$(field LENGTHENED_BOTH "$combo")" "$((n_pw + n_uis))"
same "dropping PUBLISHED_WRONG alone reproduces its own $n_pw finding(s), not UNLINKED_IN_SOURCE's" \
  "$(field DROP_PUBLISHED_WRONG "$combo")" "$n_pw"
same "dropping UNLINKED_IN_SOURCE alone reproduces its own $n_uis finding(s), not PUBLISHED_WRONG's" \
  "$(field DROP_UNLINKED_IN_SOURCE "$combo")" "$n_uis"
same "both tables restored, clean again" "$(field RESTORED "$combo")" "0"

echo "non-blanket suppression: baselining a finding must not blank out the rest of its puzzle"
out3=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import copy
from datetime import datetime, timezone
import puzzle_integrity as pi
from groups import entry_id

today = datetime.now(timezone.utc).date()
path = pi.puzzle_paths.find("cryptic-24104")
puzzle = copy.deepcopy(pi.read_puzzle_file(path))
by_id = {entry_id(e): e for e in puzzle["entries"]}
target = by_id["1-across"]
assert target.get("solution"), "fixture assumption broken: 1-across has no solution"
# A grid-length mismatch is checked and flagged before either exception table
# is even consulted (see check_length), so no baseline could ever suppress it
# -- exactly the kind of unrelated defect that must still surface next to the
# two findings cryptic-24104 already has baselined (13-across and 16-down).
target["length"] = target["length"] + 1

flags = []
checkable = pi.check_shape(puzzle, today, flags)
pi.check_length(puzzle, checkable, flags)
findings = [f[2] for f in flags if f[0] == "LENGTH"]
print("TOTAL", len(findings))
print("NEW_DEFECT", any(f.startswith("1-across:") for f in findings))
print("PAIR_SILENT", not any(f.startswith("13-across:") or f.startswith("16-down:")
                              for f in findings))
PY
)
same "exactly one LENGTH finding survives in the mutated cryptic-24104" \
  "$(field TOTAL "$out3")" "1"
same "it is the injected 1-across defect" "$(field NEW_DEFECT "$out3")" "True"
same "the baselined 13-across/16-down pair stays silent" \
  "$(field PAIR_SILENT "$out3")" "True"

echo "a grid with no puzzle in it: every clue blank is one finding, one blank clue is none"
out4=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import copy
from datetime import datetime, timezone
import puzzle_integrity as pi

today = datetime.now(timezone.utc).date()
# A real puzzle, so the fixture cannot drift out of the shape the checker reads.
# clue.missing on every entry is the state the 2005-2008 Saturday prize puzzles are
# in: answers scraped, clue text never fetched. Per-entry forgiveness finds nothing
# wrong with any single one of them, which is the whole reason the puzzle is asked.
puzzle = copy.deepcopy(pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-24104")))


def blank(p, entries):
    for e in entries:
        e["clue"] = {"enumeration": str(e["length"]), "missing": True}
    flags = []
    pi.check_shape(p, today, flags)
    return [f[2] for f in flags if "blank" in f[2]]


one = copy.deepcopy(puzzle)
print("ONE_BLANK", len(blank(one, one["entries"][:1])))
whole = copy.deepcopy(puzzle)
found = blank(whole, whole["entries"])
print("ALL_BLANK", len(found))
print("BLANK_SAYS", found == [f"all {len(whole['entries'])} clues are blank"])
PY
)
same "one clue the setter left blank is not a defect" "$(field ONE_BLANK "$out4")" "0"
same "a puzzle with no clue text at all is exactly one finding" \
  "$(field ALL_BLANK "$out4")" "1"
same "and it counts the clues it actually read" "$(field BLANK_SAYS "$out4")" "True"

echo "grid geometry: a light off the board and two acrosses on one cell are findings"
out5=$(PYTHONPATH="$REPO/tools" python3 - <<'XPY'
import copy
import puzzle_integrity as pi
from apply_solution import check_geometry
from groups import entry_id

# A real 15x15, so the fixture cannot drift out of the shape the checker reads.
puzzle = pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-24104"))
print("PRISTINE", len(check_geometry(puzzle)))

# 1-across is 15 cells of a 15-wide grid. Shifted one column right it is the
# same light, still crossing everything, and no longer on the board.
off = copy.deepcopy(puzzle)
by_id = {entry_id(e): e for e in off["entries"]}
assert by_id["1-across"]["length"] == off["dimensions"]["cols"], "fixture assumption broken"
by_id["1-across"]["position"]["x"] = 1
found = check_geometry(off)
print("OFFBOARD", len(found))
print("OFFBOARD_SAYS", found == ["1-across: 15 cells across from (1,0) runs off a 15x15 grid"])

# No exception table forgives it, and the write path refuses it: a light off
# the board is a cell no reader can draw, whatever a note says about why.
pi.PUBLISHED_WRONG[(off["id"], found[0])] = "a note cannot put a cell on the board"
flags = []
pi.check_grid(off, flags)
print("FORGIVEN_STILL_FLAGS", [w for _, _, w in flags] == found)
try:
    pi.refuse_bad_write(off)
    print("WRITE_REFUSED", False)
except pi.RefusedWrite as err:
    print("WRITE_REFUSED", "runs off a 15x15 grid" in str(err))
del pi.PUBLISHED_WRONG[(off["id"], found[0])]

# A second across laid over the first four cells of 1-across: the shape a
# mis-templated grid takes when a light is split or a block lands in the wrong
# square. Numbered like 1-across so that only the overlap rule can speak.
over = copy.deepcopy(puzzle)
twin = copy.deepcopy({entry_id(e): e for e in over["entries"]}["1-across"])
twin["length"] = 4
over["entries"].append(twin)
found = check_geometry(over)
print("OVERLAP", len(found))
print("OVERLAP_SAYS", all(f == f"cell ({x}, 0): 2 across lights share it — "
                          "1-across, 1-across" for x, f in enumerate(found)))
XPY
)
same "the puzzle as published is a coherent grid" "$(field PRISTINE "$out5")" "0"
same "a light off the board is exactly one finding" "$(field OFFBOARD "$out5")" "1"
same "and it names the light, the run and the board" "$(field OFFBOARD_SAYS "$out5")" "True"
same "PUBLISHED_WRONG naming an off-board light does not forgive it" \
  "$(field FORGIVEN_STILL_FLAGS "$out5")" "True"
same "and the writer refuses to put it on disk" "$(field WRITE_REFUSED "$out5")" "True"
same "two acrosses over four cells is four findings" "$(field OVERLAP "$out5")" "4"
same "each names the cell and both lights" "$(field OVERLAP_SAYS "$out5")" "True"

echo "a book puzzle holds its book's year and no date; only a book holds a year"
# Synthetic puzzles, so the check is exercised whatever the corpus holds.
out6=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
from datetime import date
import puzzle_integrity as pi
import series

book = series.book_number("newpenguinbkguar0000perk", 1)
DAY = "2014-12-31"
def shape(series_key, number, **when):
    flags = []
    pi.check_shape({"id": f"{series_key}-{number}", "series": series_key,
                    "number": number, **when,
                    "entries": [{"number": 1, "direction": "across", "clue": {"text": "x", "enumeration": "1"}}]},
                   date(2026, 9, 25), flags)
    return sum(1 for kind, _pid, msg in flags
               if kind == "SHAPE" and ("date" in msg or "year" in msg))
print("BOOK_RIGHT", shape("book", book, year=series.published("book", book)))
print("BOOK_UNDATED", shape("book", book))
print("BOOK_WRONG_YEAR", shape("book", book, year=1996))
print("BOOK_DAY", shape("book", book, year=series.published("book", book), date=DAY))
print("PAPER_RIGHT", shape("cryptic", 30000, date=DAY))
print("PAPER_YEAR", shape("cryptic", 30000, year=1995))
print("PAPER_JUNK", shape("cryptic", 30000, date="1995"))
print("PAPER_MS", shape("cryptic", 30000, date=1419984000000))
print("PAPER_NO_DAY", shape("cryptic", 30000, date="2014-02-30"))
print("PAPER_COMPACT", shape("cryptic", 30000, date="20141231"))
PY
)
same "the registry's year passes" "$(field BOOK_RIGHT "$out6")" "0"
same "a book puzzle with no year is flagged" "$(field BOOK_UNDATED "$out6")" "1"
same "a book puzzle under another year is flagged" "$(field BOOK_WRONG_YEAR "$out6")" "1"
same "a book puzzle with a day is flagged" "$(field BOOK_DAY "$out6")" "1"
same "a paper's day passes" "$(field PAPER_RIGHT "$out6")" "0"
same "a paper's puzzle holding a year, and no date, is flagged twice" "$(field PAPER_YEAR "$out6")" "2"
same "a date that is only a year is flagged" "$(field PAPER_JUNK "$out6")" "1"
same "a date in epoch milliseconds is flagged" "$(field PAPER_MS "$out6")" "1"
same "a date that is not a calendar day is flagged" "$(field PAPER_NO_DAY "$out6")" "1"
same "a date not written YYYY-MM-DD is flagged" "$(field PAPER_COMPACT "$out6")" "1"

echo "a file not at file_for is FILED: wrong year, flat stray, wrong name"
out7=$(PYTHONPATH="$REPO/tools" SCRATCH="$scratch" python3 - <<'PY'
import json, os, shutil
from datetime import date
from pathlib import Path
import puzzle_integrity as pi
import puzzle_paths

real = puzzle_paths.find("cryptic-24104")
puzzle = pi.read_puzzle_file(real)
puzzle_paths.PUZZLE_DIR = Path(os.environ["SCRATCH"]) / "puzzles"
pi.CACHE = Path(os.environ["SCRATCH"]) / "integrity-rows.pickle"
right = puzzle_paths.file_for(puzzle)
right.parent.mkdir(parents=True)
shutil.copy(real, right)
(puzzle_paths.PUZZLE_DIR / "index.json").write_text("{}")

def filed():
    files = pi.listing()
    flags, _ = pi.audit(files, pi.published(files), date(2026, 9, 25))
    return sorted(what for kind, _pid, what in flags if kind == "FILED")

print("CLEAN", len(filed()))
wrong = puzzle_paths.PUZZLE_DIR / "cryptic" / "1999" / right.name
wrong.parent.mkdir()
right.rename(wrong)
print("WRONG_YEAR", filed() == [f"puzzles/cryptic/1999/cryptic-24104.json belongs at {right.relative_to(puzzle_paths.PUZZLE_DIR.parent)}"])
wrong.rename(right)
flat = puzzle_paths.PUZZLE_DIR / right.name
shutil.copy(right, flat)
print("FLAT", filed() == [f"puzzles/cryptic-24104.json belongs at {right.relative_to(puzzle_paths.PUZZLE_DIR.parent)}"])
flat.unlink()
misnamed = right.with_name("cryptic-24105.json")
right.rename(misnamed)
print("MISNAMED", len(filed()))
PY
)
same "a puzzle at file_for is not flagged (nor is the generated index)" "$(field CLEAN "$out7")" "0"
same "a puzzle in the wrong year folder names where it belongs" "$(field WRONG_YEAR "$out7")" "True"
same "a stray flat puzzles/<id>.json names where it belongs" "$(field FLAT "$out7")" "True"
same "a file named for another id is flagged" "$(field MISNAMED "$out7")" "1"

echo "a rewrite may not replace the held puzzle with another one"
out8=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import copy
import puzzle_integrity as pi

held = pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-24104"))
other = copy.deepcopy(held)
for e in other["entries"]:
    e["solution"] = "Q" * e["length"]
fixed = copy.deepcopy(held)
fixed["entries"][0]["solution"] = "Q" * fixed["entries"][0]["length"]
withdrawn = copy.deepcopy(held)
for e in withdrawn["entries"][4:]:
    e.pop("solution", None)


def filed(new):
    flags = []
    pi.check_rewrite(held, new, flags)
    return sum(f[0] == "FILED" for f in flags)


print("ANOTHER", filed(other))
print("ONE_FIXED", filed(fixed))
print("WITHDRAWN", filed(withdrawn))
PY
)
same "another puzzle's answers over a held file are refused" "$(field ANOTHER "$out8")" "1"
same "one corrected answer is not another puzzle" "$(field ONE_FIXED "$out8")" "0"
same "most answers withdrawn to blank is not another puzzle" "$(field WITHDRAWN "$out8")" "0"

echo "an OCR reading may not file one clue on two lights"
out9=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import copy
import fetch_puzzle
import puzzle_integrity as pi

# cryptic-23115 prints "Big hitting" on 16 and 17 down (THUMPING, WHOPPING):
# the Guardian's own feed serves each light's clue, so that is the setter's.
held = pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-23115"))
ocr = copy.deepcopy(held)
ocr["source"]["retrievedFrom"] = "newspaper"


def dups(p):
    flags = []
    pi.check_duplicated_clues(p, flags)
    return len(flags)


print("FEED", dups(held))
print("OCR", dups(ocr))
fetch_puzzle.SOURCE_CLUE_WRONG[("cryptic-23115", "17-down")] = ("Big hitting", "Printed clue", "evidence")
print("FIXED", dups(ocr))
del fetch_puzzle.SOURCE_CLUE_WRONG[("cryptic-23115", "17-down")]
# Listener No 3 prints "An exclamation." for 32 across and 2 down: one clue
# in both lists is printed twice, no misread.
lists = copy.deepcopy(ocr)
across = next(e for e in lists["entries"] if e["direction"] == "across")
for e in lists["entries"]:
    if (e["number"], e["direction"]) == (17, "down"):
        e["clue"] = {"text": "Another clue"}
across["clue"] = {"text": "Big hitting"}
print("LISTS", dups(lists))
blanked = copy.deepcopy(ocr)
for e in blanked["entries"]:
    if (e["number"], e["direction"]) in ((16, "down"), (1, "down")):
        e["clue"] = {"text": "", "missing": True}


def blanks(old):
    flags = []
    pi.check_rewrite(old, blanked, flags)
    return ",".join(sorted(f[2].split(":")[0] for f in flags if f[0] == "SHAPE"))


print("REWRITE_OCR", blanks(ocr))
print("REWRITE_FEED", blanks(held))
PY
)
same "a feed's clue on two lights is the setter's" "$(field FEED "$out9")" "0"
same "an OCR reading's clue on two lights is refused" "$(field OCR "$out9")" "1"
same "unless SOURCE_CLUE_WRONG prints one of them" "$(field FIXED "$out9")" "0"
same "one clue in the ACROSS and DOWN lists is printed in each" "$(field LISTS "$out9")" "0"
same "blanking an OCR reading's clue on two lights loses nothing, any other clue is kept" \
  "$(field REWRITE_OCR "$out9")" "1-down"
same "a feed's clue on two lights is a clue a rewrite keeps" "$(field REWRITE_FEED "$out9")" "1-down,16-down"

[ "$fails" = 0 ] && echo "puzzle_integrity: all checks passed" || echo "puzzle_integrity: $fails FAILED"
exit $((fails > 0))
