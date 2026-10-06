#!/bin/bash
# Does tools/build_authored_puzzle.py still write A001 (id authored-1), and does what it writes
# pass everything a fetched puzzle must?
#
#     bash tools/test_build_authored_puzzle.sh
#
# The authored puzzle is never committed — its clues JSON is the source — so no
# corpus sweep ever sees it, and a change to the schema, the provenance rules
# or the annotation rules can leave it unbuildable without failing anything.
# This builds it through the real write path into a scratch puzzles/ tree and
# holds the result to the schema, puzzle_integrity and validate_annotations.
set -uo pipefail
cd "$(dirname "$0")/.."

PYTHONPATH=tools python3 - <<'PY'
import datetime
import json
import sys
import tempfile
from pathlib import Path

import build_authored_puzzle as builder
import provenance
import puzzle_integrity
import puzzle_paths
import series
import validate_annotations
from fetch_puzzle import write_puzzle_file

fails = []
with tempfile.TemporaryDirectory() as scratch:
    puzzle_paths.PUZZLE_DIR = Path(scratch)
    puzzle = builder.build("tools/data/sample_fill_11.json",
                           "tools/data/authored_A001_clues.json", 1,
                           "Cryptic Teacher No 1", "Cryptic Teacher",
                           datetime.date(2026, 7, 29))
    # finish() is the builder's own pre-write step, refusal included.
    puzzle, errors = builder.finish(puzzle, "human")
    if errors:
        sys.exit("  FAIL: the builder refuses its own puzzle:\n    " + "\n    ".join(errors))
    try:
        out = write_puzzle_file(puzzle_paths.file_for(puzzle), puzzle,
                                generator="tools/build_authored_puzzle.py")
    except ValueError as err:
        sys.exit(f"  FAIL: the builder's write was refused: {err}")
    written = json.loads(Path(out).read_text())

    want = ("authored-1", 1, "authored")
    got = (written["id"], written["number"], written["series"])
    if got != want:
        fails.append(f"id/number/series is {got}, want {want}")
    if Path(out).relative_to(scratch).as_posix() != "authored/2026/authored-1.json":
        fails.append(f"filed at {out}")
    src = written["source"]
    if (src.get("publisher"), src.get("acquiredBy"), src.get("retrievedFrom"),
            "url" in src) != ("Cryptic Teacher", "tools/build_authored_puzzle.py",
                              "authored", False):
        fails.append(f"source is {src}")
    # The site publishes it at ?p=authored-1 only because the series is unlisted.
    if not series.unlisted(written["series"]):
        fails.append(f"series {written['series']!r} is listed: the site would index it")
    if written["solutions"] != {"origin": "authored"}:
        fails.append(f"solutions is {written['solutions']}")

    try:
        puzzle_integrity.refuse_bad_write(written)
    except ValueError as err:
        fails.append(f"integrity: {err}")
    _, errors, _ = validate_annotations.validate_puzzle(written)
    fails += [f"validate_annotations: {e}" for e in errors]

    # The same clues under a second id, by the same process: the index the
    # first write entered refuses it, whichever filer asks.
    copy = {**puzzle, "id": "authored-2", "number": 2}
    try:
        write_puzzle_file(puzzle_paths.file_for(copy), copy,
                          generator="tools/build_authored_puzzle.py")
        fails.append("a second id carrying authored-1's clues was filed")
    except puzzle_integrity.RefusedWrite as err:
        if [f[0] for f in err.flags] != ["NEARDUP"]:
            fails.append(f"the copy was refused for {err.flags}, want NEARDUP")

    # A book page holding a newspaper's puzzle is the reprint, whichever was
    # filed first: written after it, the newspaper's own id is filed, and
    # the book file becomes a reading of it beside acquire_book's reprints.
    # A book page reprinting a held newspaper puzzle is refused.
    import book_queue
    with tempfile.TemporaryDirectory() as other:
        puzzle_paths.PUZZLE_DIR = Path(other) / "puzzles"
        book_queue.REPRINT_DIR = Path(other) / "book-reprints"
        book = {**{k: v for k, v in puzzle.items() if k != "date"},
                "id": "book-13007", "number": 13007, "series": "book", "year": 1998,
                "source": {**puzzle["source"],
                           "url": "https://archive.org/details/isbn_9781902254067",
                           "book": {"identifier": "isbn_9781902254067", "numberInBook": 7}}}
        held = puzzle_paths.file_for(book)
        held.parent.mkdir(parents=True)
        held.write_text(json.dumps(book))
        try:
            write_puzzle_file(puzzle_paths.file_for(puzzle), puzzle,
                              generator="tools/build_authored_puzzle.py")
        except puzzle_integrity.RefusedWrite as err:
            fails.append(f"the original was refused over a held book copy: {err}")
        if not puzzle_paths.find("authored-1"):
            fails.append("the original was not filed over a held book copy")
        if puzzle_paths.find("book-13007"):
            fails.append("the book copy of a newspaper puzzle is still filed")
        reading = book_queue.REPRINT_DIR / "authored-1" / "isbn_9781902254067-7.txt"
        clue = puzzle["entries"][0]["clue"]["text"]
        if not reading.is_file() or clue not in reading.read_text():
            fails.append(f"the book copy's clues are not kept at {reading}")
        try:
            write_puzzle_file(puzzle_paths.file_for(book), book)
            fails.append("a book page reprinting a held puzzle was filed")
        except puzzle_integrity.RefusedWrite as err:
            if [f[0] for f in err.flags] != ["NEARDUP"]:
                fails.append(f"the book reprint was refused for {err.flags}, want NEARDUP")

for f in fails:
    print("  FAIL:", f)
if fails:
    sys.exit(1)
print("  ok: authored-1 builds, files, and passes schema, integrity and annotations")
PY
