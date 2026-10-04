#!/usr/bin/env python3
"""Drop the source_clue_wrong.json rows of one puzzle that its file does not show.

    python3 tools/discard_clue_rows.py ID

A run that corrects an OCR'd clue writes two things: the printed text into the
puzzle file and a row into tools/data/source_clue_wrong.json. When the pre-reset
backfill discards that run (tools/prereset_backfill.sh discard_puzzle) the file
goes back, so the row must go too: otherwise it names a clue the file does not
hold, and the next sibling puzzle's commit carries it to master, where
tools/test_source_answer_wrong.sh fails on it.

A row stays when the file on disk holds its printed clue (compared as
clue_words, as that test does), so rows committed with an earlier annotation
are untouched. Every other row for ID is removed, leaving the rest of the file as it was. The retry files the
correction again if it is real.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_puzzle as fetcher
from groups import entry_id
from json_merge import dump_lines

DATA = Path(fetcher.__file__).resolve().parent / "data" / "source_clue_wrong.json"


def shown_clues(pid):
    """{entry id: clue words} as the puzzle file on disk holds them; {} when
    there is no file."""
    path = fetcher.puzzle_paths.find(pid)
    if path is None:
        return {}
    return {entry_id(e): fetcher.clue_words(e["clue"].get("text"))
            for e in fetcher.read_puzzle_file(path)["entries"]}


def drop_unshown(pid, data_path=DATA):
    """Remove pid's rows whose printed clue its file does not hold. Returns the
    entry ids removed."""
    rows = json.loads(data_path.read_text(encoding="utf-8"))
    shown = shown_clues(pid)
    gone = []
    for key, (_served, printed, _why) in list(rows.items()):
        row_pid, eid = key.split("/", 1)
        if row_pid == pid and shown.get(eid) != fetcher.clue_words(printed):
            gone.append(eid)
            del rows[key]
    if gone:
        data_path.write_text(dump_lines(rows), encoding="utf-8")
    return gone


def main(argv):
    if len(argv) != 1:
        raise SystemExit(__doc__)
    for eid in drop_unshown(argv[0]):
        print(f"  [{argv[0]}] dropped its source_clue_wrong.json row for {eid}: the reverted file "
              "does not show that clue")


if __name__ == "__main__":
    main(sys.argv[1:])
