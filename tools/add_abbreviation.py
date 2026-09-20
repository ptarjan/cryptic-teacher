#!/usr/bin/env python3
"""Add one sense to one row of tools/data/abbreviations.json without racing.

tools/prereset_backfill.sh runs annotator sessions four at a time, and more
than one of them can decide the same clue-writing pass needs a new
abbreviation. Two sessions that each read the whole JSON, add their own row in
memory and write the whole file back is a lost-update race: whichever write
lands second wins, and the first session's row is gone with nothing for git to
flag — both writes are valid JSON, so the diff just looks like one commit
that happened to include an edit the other session made. This script is the
only writer any annotator should use, so the read-modify-write is atomic
instead of three separate steps a second process can land in the middle of.

Usage: python3 tools/add_abbreviation.py LETTERS SENSE [SENSE ...]

Idempotent: a SENSE the row already lists is a no-op, and the file is not
touched at all if every SENSE given is already there. LETTERS is folded to
uppercase and each SENSE to lowercase to match the table's own documented
convention (see abbreviations.json's "_comment").
"""
import fcntl
import json
import os
import re
import sys
import tempfile
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "abbreviations.json"
# Never renamed out from under a waiter: PATH itself gets replaced by every
# write, so flock-ing it directly would let a second process that opened it
# just before the replace lock the old, now-unlinked inode and read stale
# content once its turn comes. This file is created once and only ever
# flock-ed, never moved, so every waiter locks the same inode as the writer
# ahead of it.
LOCK = DATA.with_name(DATA.name + ".lock")


def add_row(letters, senses):
    """Add SENSES to LETTERS's row. Returns True if the file changed."""
    letters = letters.upper()
    senses = [s.lower() for s in senses]
    LOCK.touch(exist_ok=True)
    with open(LOCK, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(DATA.read_text(encoding="utf-8"))
            table = data["abbreviations"]
            row = table.get(letters, [])
            missing = [s for s in senses if s not in row]
            if not missing:
                return False
            table[letters] = sorted(row + missing)
            # Keys stay alphabetical: that is the shape every row already has,
            # and a new letter belongs where a reader would look for it, not
            # tacked on at the end.
            data["abbreviations"] = dict(sorted(table.items()))
            text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            fd, tmp_path = tempfile.mkstemp(
                dir=DATA.parent, prefix=".abbreviations.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                    tmp.write(text)
                os.chmod(tmp_path, DATA.stat().st_mode)
                # Atomic on the same filesystem: a reader (or a process killed
                # mid-write) only ever sees the old file in full or the new
                # file in full, never a half-written truncation.
                os.replace(tmp_path, DATA)
            except BaseException:
                os.unlink(tmp_path)
                raise
            return True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def main(argv):
    if len(argv) < 2:
        print("usage: add_abbreviation.py LETTERS SENSE [SENSE ...]", file=sys.stderr)
        return 2
    letters, senses = argv[0], argv[1:]
    if not re.fullmatch(r"[A-Za-z]{1,3}", letters):
        print(f"'{letters}' is not a 1-3 letter abbreviation", file=sys.stderr)
        return 2
    label, lowered = letters.upper(), ", ".join(s.lower() for s in senses)
    if add_row(letters, senses):
        print(f"{label}: added {lowered}")
    else:
        print(f"{label}: already has {lowered}, no change")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
