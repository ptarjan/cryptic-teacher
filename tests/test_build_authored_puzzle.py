#!/usr/bin/env python3
# Does tools/build_authored_puzzle.py still write A001 (id authored-1), and does what it writes
# pass everything a fetched puzzle must?
#
#     python3 tests/test_build_authored_puzzle.py
#
# The authored puzzle is never committed — its clues JSON is the source — so no
# corpus sweep ever sees it, and a change to the schema, the provenance rules
# or the annotation rules can leave it unbuildable without failing anything.
# This builds it through the real write path into a scratch puzzles/ tree and
# holds the result to the schema, puzzle_integrity and validate_annotations.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONPATH"] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")

import datetime
import json
import sys
import tempfile
from pathlib import Path

import annotation
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
                           "Cryptic Teacher",
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
    got = (written["id"], written["number"], series.parse_id(written["id"])[0])
    if got != want:
        fails.append(f"id/number/series is {got}, want {want}")
    # The format stores no series and no name: the id gives both.
    if "series" in written or "name" in written:
        fails.append(f"stores {sorted({'series', 'name'} & set(written))}: the id gives them")
    if series.display_name(written) != "Cryptic Teacher No 1":
        fails.append(f"displays as {series.display_name(written)!r}")
    # Each annotation is the stored wordplay tree, not the clues file's model shape.
    for e in written["entries"]:
        ann = e["annotation"]
        if annotation.is_model(ann) or "type" in ann or "blocks" in ann:
            fails.append(f"{e['number']}-{e['direction']} annotation is not the stored tree: {sorted(ann)}")
    if Path(out).relative_to(scratch).as_posix() != "authored/2026/authored-1.json":
        fails.append(f"filed at {out}")
    src = written["source"]
    if (src.get("publisher"), src.get("acquiredBy"), src.get("retrievedFrom"),
            "url" in src) != ("Cryptic Teacher", "tools/build_authored_puzzle.py",
                              "authored", False):
        fails.append(f"source is {src}")
    # The site publishes it at ?p=authored-1 only because the series is unlisted.
    if not series.unlisted(series.parse_id(written["id"])[0]):
        fails.append("series authored is listed: the site would index it")
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
    copy = {**puzzle, "id": "authored-2", "number": 2,
            "date": (datetime.date.fromisoformat(puzzle["date"]) + datetime.timedelta(1)).isoformat()}
    try:
        write_puzzle_file(puzzle_paths.file_for(copy), copy,
                          generator="tools/build_authored_puzzle.py")
        fails.append("a second id carrying authored-1's clues was filed")
    except puzzle_integrity.RefusedWrite as err:
        if [f[0] for f in err.flags] != ["NEARDUP"]:
            fails.append(f"the copy was refused for {err.flags}, want NEARDUP")

    # A held book file (solved or annotated: unsolved_book_yields below) is never replaced by another copy of its puzzle,
    # whichever was filed first: a newspaper id carrying a held book file's
    # clues (telegraph-26398 over the solved, annotated book-25035) is
    # refused, the book file stands untouched, and the pair is recorded for
    # the cross-check (tools/book_twins.py). A book page reprinting a held
    # newspaper puzzle is refused too.
    import book_queue
    import book_twins
    import corroborate
    with tempfile.TemporaryDirectory() as other:
        puzzle_paths.PUZZLE_DIR = Path(other) / "puzzles"
        book_queue.REPRINT_DIR = Path(other) / "book-reprints"
        book = {**{k: v for k, v in puzzle.items() if k != "date"},
                "id": "book-13007", "number": 13007, "year": 1998,
                "source": {**puzzle["source"],
                           "url": "https://archive.org/details/isbn_9781902254067",
                           "book": {"identifier": "isbn_9781902254067", "numberInBook": 7}}}
        held = puzzle_paths.file_for(book)
        held.parent.mkdir(parents=True)
        held.write_text(json.dumps(book))
        before = held.read_bytes()
        try:
            write_puzzle_file(puzzle_paths.file_for(puzzle), puzzle,
                              generator="tools/build_authored_puzzle.py")
            fails.append("a newspaper id was filed over a held book copy of its puzzle")
        except puzzle_integrity.RefusedWrite as err:
            if [f[0] for f in err.flags] != ["NEARDUP"]:
                fails.append(f"the newspaper copy was refused for {err.flags}, want NEARDUP")
        if puzzle_paths.find("authored-1"):
            fails.append("the newspaper copy of a held book puzzle was filed")
        if not held.is_file() or held.read_bytes() != before:
            fails.append("the held book file was removed or changed by a copy's write")
        if (book_queue.REPRINT_DIR / "authored-1").exists():
            fails.append("the held book file was turned into a reading")
        twins = book_twins.read(Path(other))
        if twins != {"book-13007": "authored-1"}:
            fails.append(f"book_twins holds {twins}, want the refused pair")
        seen = []
        corroborate._georgeho[:] = [type("DB", (), {"execute": lambda self, q, a: seen.append(a) or []})()]
        book_twins.ROOT = Path(other)
        corroborate.georgeho.every({"id": "book-13007"})
        if seen != [("authored-1",)]:
            fails.append(f"georgeho reads the book under {seen}, want its twin authored-1")
    with tempfile.TemporaryDirectory() as other:
        puzzle_paths.PUZZLE_DIR = Path(other) / "puzzles"
        original = puzzle_paths.file_for(puzzle)
        original.parent.mkdir(parents=True)
        original.write_text(json.dumps(puzzle))
        try:
            write_puzzle_file(puzzle_paths.file_for(book), book)
            fails.append("a book page reprinting a held puzzle was filed")
        except puzzle_integrity.RefusedWrite as err:
            if [f[0] for f in err.flags] != ["NEARDUP"]:
                fails.append(f"the book reprint was refused for {err.flags}, want NEARDUP")
    import fetch_puzzle
    for gone in ("supersede_book", "supersede_held_books"):
        if hasattr(fetch_puzzle, gone):
            fails.append(f"fetch_puzzle.{gone} can still remove a held book file")

    # The one exception (fetch_puzzle.unsolved_book_yields, failure shapes r29): a book file with no answer
    # and no annotation in any entry gives way to a newspaper copy holding every answer. The copy is filed,
    # the book's file, shim and rows go, and renamed_ids.json sends the book's id to the copy. A book with
    # a single answer or a single annotation, or a copy one answer short, is refused as before.
    import renamed_ids

    def bare(entry, **keep):
        return {**{k: v for k, v in entry.items() if k not in ("solution", "annotation")}, **keep}

    def held_book(entries):
        return {**{k: v for k, v in puzzle.items() if k != "date"}, "entries": entries,
                "id": "book-13008", "number": 13008, "year": 1998,
                "source": {**puzzle["source"], "url": "https://archive.org/details/isbn_9781902254067",
                           "book": {"identifier": "isbn_9781902254067", "numberInBook": 8}}}

    first = puzzle["entries"][0]
    cases = [("unsolved", [bare(e) for e in puzzle["entries"]], puzzle, True),
             ("one answer", [bare(first, solution=first.get("solution") or "X")] + [bare(e) for e in puzzle["entries"][1:]],
              puzzle, False),
             ("one annotation", [bare(first, annotation=first.get("annotation") or {"note": "held"})]
              + [bare(e) for e in puzzle["entries"][1:]], puzzle, False),
             ("copy short", [bare(e) for e in puzzle["entries"]],
              {**puzzle, "entries": [bare(first)] + puzzle["entries"][1:]}, False)]
    for name, entries, copy, yields in cases:
        with tempfile.TemporaryDirectory() as other:
            puzzle_paths.PUZZLE_DIR = Path(other) / "puzzles"
            book = held_book(entries)
            held = puzzle_paths.file_for(book)
            held.parent.mkdir(parents=True)
            held.write_text(json.dumps(book))
            before = held.read_bytes()
            try:
                write_puzzle_file(puzzle_paths.file_for(copy), copy, generator="tools/build_authored_puzzle.py")
                filed = True
            except ValueError:
                filed = False
            mapped = renamed_ids.read(Path(other) / "tools" / "data" / "renamed_ids.json") \
                if (Path(other) / "tools" / "data" / "renamed_ids.json").exists() else {}
            twins = book_twins.read(Path(other))
            if yields:
                if not filed or not puzzle_paths.find("authored-1"):
                    fails.append(f"{name}: the newspaper copy was not filed over an unsolved, unannotated book")
                if held.exists() or puzzle_paths.shim_path(held).exists():
                    fails.append(f"{name}: the yielded book file or its shim is still held")
                if mapped != {"book-13008": "authored-1"}:
                    fails.append(f"{name}: renamed_ids holds {mapped}, want book-13008 -> authored-1")
                if "book-13008" in twins:
                    fails.append(f"{name}: book_twins still pairs the retired book: {twins}")
            else:
                if filed or puzzle_paths.find("authored-1"):
                    fails.append(f"{name}: the newspaper copy was filed over the book")
                if not held.is_file() or held.read_bytes() != before:
                    fails.append(f"{name}: the held book file was removed or changed")
                if mapped:
                    fails.append(f"{name}: renamed_ids holds {mapped} for a book that stands")

for f in fails:
    print("  FAIL:", f)
if fails:
    sys.exit(1)
print("  ok: authored-1 builds, files, and passes schema, integrity and annotations")
