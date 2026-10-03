#!/usr/bin/env python3
"""Drop the SOURCE_CLUE_WRONG rows of one puzzle that its file does not show.

    python3 tools/discard_clue_rows.py ID

A run that corrects an OCR'd clue writes two things: the printed text into the
puzzle file and a row into fetch_puzzle.SOURCE_CLUE_WRONG. When the pre-reset
backfill discards that run (tools/prereset_backfill.sh discard_puzzle) the file
goes back, so the row must go too: otherwise it names a clue the file does not
hold, and the next sibling puzzle's commit carries it to master, where
tools/test_source_answer_wrong.sh fails on it.

A row stays when the file on disk holds its printed clue (compared as
clue_words, as that test does), so rows committed with an earlier annotation
are untouched. Every other row for ID is removed from the source text, its
whole lines, leaving the rest of the file byte for byte. The retry files the
correction again if it is real.
"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_puzzle as fetcher
from groups import entry_id
from own_rows import tables

TABLE = "SOURCE_CLUE_WRONG"


def row_spans(source):
    """[(pid, eid, printed, first line, last line)], 1-based and inclusive, for
    every row of TABLE in `source`, its lead comments included."""
    if TABLE not in (found := tables(source)):
        raise SystemExit(f"discard_clue_rows: no {TABLE} in fetch_puzzle.py")
    return [(pid, ast.literal_eval(k)[1], ast.literal_eval(v)[1], first, last)
            for pid, k, v, first, last in found[TABLE][1]]


def shown_clues(pid):
    """{entry id: clue words} as the puzzle file on disk holds them; {} when
    there is no file."""
    path = fetcher.puzzle_paths.find(pid)
    if path is None:
        return {}
    return {entry_id(e): fetcher.clue_words(e["clue"].get("text"))
            for e in fetcher.read_puzzle_file(path)["entries"]}


def drop_unshown(pid, source_path=Path(fetcher.__file__)):
    """Remove pid's rows whose printed clue its file does not hold. Returns the
    entry ids removed."""
    source = source_path.read_text()
    lines = source.splitlines(keepends=True)
    shown = shown_clues(pid)
    gone, cut = [], set()
    for row_pid, eid, printed, first, last in row_spans(source):
        if row_pid == pid and shown.get(eid) != fetcher.clue_words(printed):
            gone.append(eid)
            cut.update(range(first, last + 1))
    if cut:
        kept = "".join(line for n, line in enumerate(lines, 1) if n not in cut)
        ast.parse(kept)  # never leave the fetcher unimportable
        source_path.write_text(kept)
    return gone


def main(argv):
    if len(argv) != 1:
        raise SystemExit(__doc__)
    for eid in drop_unshown(argv[0]):
        print(f"  [{argv[0]}] dropped its {TABLE} row for {eid}: the reverted file "
              "does not show that clue")


if __name__ == "__main__":
    main(sys.argv[1:])
