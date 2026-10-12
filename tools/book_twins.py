"""{book id: newspaper id}: each held book file a filer found to be the same
puzzle as a newspaper id it tried to file.

A held book or reprint file is never replaced or removed by another copy of
its puzzle: fetch_puzzle.check_not_copy refuses the copy, whichever filer
asks, and records the pair here. The copy then serves only as a cross-check
source: corroborate.georgeho reads a book file's blog rows under its twin's
id, so a blog post of the newspaper puzzle still votes on the book's clues
and answers (tools/cross_validate.py georgeho).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "book_twins"


def path(root=None):
    return Path(root or ROOT) / "tools" / "data" / f"{NAME}.json"


def read(root=None):
    p = path(root)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def add(book_id, original_id, root=None):
    """Record that held `book_id` is `original_id`'s puzzle."""
    from json_merge import dump_lines
    rows = read(root)
    if rows.get(book_id) == original_id:
        return
    rows[book_id] = original_id
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump_lines(rows), encoding="utf-8")


def twin_of(pid, root=None):
    """The newspaper id held book `pid` was found to be, else `pid`."""
    return read(root).get(pid, pid)
