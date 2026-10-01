#!/bin/bash
# Is a puzzle with clues and no grid a whole puzzle, written, checked and solved?
#
#     bash tools/test_gridless.sh
#
# Only the clues are mandatory: a puzzle whose grid nobody has found is filed
# without `dimensions` and without any entry's `position`, and a later write
# may add the grid. Each rule is checked against its mirror: the gridless
# puzzle is accepted, and every half state between it and a gridded one is
# refused. The blog record is bigdave44's post on Sunday Telegraph 2,630,
# whose answers no grid holds (the blog gives FARMHANDS under "(4,4)").
set -uo pipefail
cd "$(dirname "$0")/.."
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

out=$(SCRATCH="$scratch" PYTHONPATH=tools python3 - <<'PY'
import copy, datetime, json, os
from pathlib import Path
import fetch_puzzle as fetcher
import puzzle_integrity, puzzle_schema, provenance, difficulty, solve_packet
import file_blog_puzzles as fbp
from apply_solution import check_fill, check_geometry, check_sources
from groups import entry_id

real = fetcher.read_puzzle_file(fetcher.resolve_puzzle("cryptic-30066"))


def gridless(p):
    p = copy.deepcopy(p)
    p.pop("dimensions"); p.pop("bars", None)
    p["source"].pop("gridOrigin")
    for e in p["entries"]:
        e.pop("position")
    return p


def verdict(p, old=None):
    try:
        puzzle_integrity.refuse_bad_write(puzzle_schema.order(p), old)
        return "accepted"
    except ValueError as err:
        return " | ".join(f"{k} {w}" for k, _, w in err.flags)


bare = gridless(real)
print("BARE", verdict(bare))
print("GRIDDED", verdict(real))
half = copy.deepcopy(bare); half["dimensions"] = real["dimensions"]
print("DIMSONLY", verdict(half))
half = copy.deepcopy(bare); half["entries"][0]["position"] = {"x": 0, "y": 0}
print("POSONLY", verdict(half))
half = copy.deepcopy(bare); half["source"]["gridOrigin"] = "published"
print("ORIGIN", verdict(half))
half = copy.deepcopy(bare); half["bars"] = ["." * 15] * 15
print("BARS", verdict(half))
half = copy.deepcopy(real); half["source"].pop("gridOrigin")
print("NOORIGIN", verdict(half))
print("DROPGRID", verdict(bare, real))
print("ADDGRID", verdict(real, bare))
print("HASGRID", puzzle_schema.has_grid(real), puzzle_schema.has_grid(bare),
      puzzle_schema.has_grid({**bare, "dimensions": None}))

# The write path: gridless lands with no gridOrigin, a grid added later lands
# with one, and taking the grid away again is refused.
path = Path(os.environ["SCRATCH"]) / f"{real['id']}.json"
fetcher.write_puzzle_file(path, bare)
held = json.loads(path.read_text())
print("WROTE", "dimensions" in held, "gridOrigin" in held["source"],
      any("position" in e for e in held["entries"]))
fetcher.write_puzzle_file(path, real)
held = json.loads(path.read_text())
print("REGRID", "dimensions" in held, held["source"].get("gridOrigin"))
try:
    fetcher.write_puzzle_file(path, bare)
    print("UNGRID accepted")
except ValueError as err:
    print("UNGRID", err)

# The blog filer's builder with no grid row.
rec = json.loads(Path("tools/fixtures/bigdave44/27605.json").read_text())
day = datetime.date.fromisoformat(rec["printed"])
p, why = fbp.build(rec, None, rec["series"], day, None)
print("BUILT", why, "dimensions" in fetcher.puzzle_schema.prune(p),
      p["solutions"]["origin"], sum(bool(e.get("solution")) for e in p["entries"]),
      next(e["length"] for e in p["entries"] if entry_id(e) == "8-across"))
fixed = copy.deepcopy(rec)
for e in fixed["entries"]:
    if e["number"] == 8 and e["direction"] == "across":
        e["answer"], e["answer_spaced"] = "FARMHAND", "FARM HAND"
p2, why = fbp.build(fixed, None, rec["series"], day, None)
print("BUILTFIT", why, p2["solutions"].get("blog"),
      sum(bool(e.get("solution")) for e in p2["entries"]), len(p2["entries"]))
print("BUILTOK", verdict(provenance.stamp(puzzle_schema.prune(p2), "tools/file_telegraph_puzzles.py")))

# Solving: no geometry to fail, no crossing to place, a packet that says so,
# and no checking component for difficulty.
fill = {entry_id(e): e["solution"] for e in bare["entries"]}
cells, crossings, problems = check_fill(bare, fill)
print("SOLVE", check_geometry(bare), problems, crossings)
print("SOURCES", check_sources(bare, fill, sources=[lambda p: []]))
print("PACKET", "no grid" in solve_packet.packet(bare))
print("CHECKING", difficulty.checking(bare), difficulty.checking(real) is not None)
PY
)
fails=0
line() { grep "^$1 " <<<"$out"; }
same() { if [ "$(line "$1")" = "$1 $2" ]; then echo "  ok: $3"; else
  echo "  FAIL: $3"$'\n'"    want $1 $2"$'\n'"    got  $(line "$1")"; fails=$((fails + 1)); fi; }
has() { if line "$1" | grep -qF -- "$2"; then echo "  ok: $3"; else
  echo "  FAIL: $3"$'\n'"    want $2 in"$'\n'"    $(line "$1")"; fails=$((fails + 1)); fi; }
grep -q '^CHECKING ' <<<"$out" || { echo "$out"; exit 1; }

same BARE accepted "a gridless puzzle is written"
same GRIDDED accepted "mirror: the same puzzle with its grid is written"
has DIMSONLY "has dimensions but an entry has no position" "dimensions without positions are refused"
has POSONLY "entries have positions but the puzzle has no dimensions" "a position without dimensions is refused"
has ORIGIN "source.gridOrigin is 'published' but the puzzle has no grid" "a gridless puzzle naming a gridOrigin is refused"
has BARS "must not match" "a gridless puzzle with bars is refused"
has NOORIGIN "source is missing gridOrigin" "mirror: a gridded puzzle without a gridOrigin is refused"
has DROPGRID "would drop the held grid" "a write that takes the held grid away is refused"
same ADDGRID accepted "a write that adds a grid to a gridless puzzle is accepted"
same HASGRID "True False False" "has_grid reads dimensions, and an empty one as absent"
same WROTE "False False False" "written gridless: no dimensions, no gridOrigin, no position"
same REGRID "True published" "a later write adds the grid and its gridOrigin"
has UNGRID "would drop the held grid" "writing gridless over the held grid is refused"
same BUILT "None False unsolved 0 8" "a blog record with no grid files gridless, unsolved where an answer breaks its printed count"
same BUILTFIT "None bigdave44 27 27" "mirror: every answer fitting its count files with the blog's answers"
same BUILTOK accepted "the gridless blog puzzle passes the write gate"
same SOLVE "[] [] 0" "a gridless fill has no geometry to fail and nothing to cross"
same SOURCES "[]" "the fill is weighed against other sources with no grid to place it in"
same PACKET True "the solve packet says there is no grid"
same CHECKING "None True" "difficulty has no checking component for a gridless puzzle"

[ "$fails" -eq 0 ] && echo "gridless: all checks passed" || { echo "gridless: $fails failure(s)"; exit 1; }
