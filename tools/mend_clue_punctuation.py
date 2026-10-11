"""One-shot migration (2026-10-11): make punctuation's certain mends
("by.clever" to "by clever", "''" to '"', ",," to ",") in the book
channel's held clue text, and list the faults left.

A book's held puzzles are never re-filed by a re-read (acquire_book skips a
held leaf), so this is the only way their clues reach the write path's
mends (fetch_puzzle.write_puzzle_file, punctuation.mend_puzzle). Archive.org
newspaper files are left to their re-reads: edition_commit.strayed makes
those editions due, and file_archive_org_puzzles mends them in place there.
Publisher feeds are the setter's text and stay as served.

Only the clue's text changes, with its italics and its annotation's offsets
moved (punctuation.mend_entry, enumeration.edit_entry); the file is written
back in the corpus's own format (collapse_clue_spaces.migrate).

    python3 tools/mend_clue_punctuation.py [--dry-run]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collapse_clue_spaces
import punctuation
from groups import entry_id

CHANNELS = ("book",)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", default=str(collapse_clue_spaces.ROOT / "puzzles"))
    args = ap.parse_args(argv)
    left = []

    def change(puzzle):
        n = len(punctuation.mend_puzzle(puzzle))
        left.extend((puzzle.get("id"), entry_id(e), e["clue"]["text"], punctuation.faults(e["clue"]["text"]))
                    for e in puzzle.get("entries") or ()
                    if isinstance(e.get("clue"), dict) and punctuation.faults(e["clue"].get("text")))
        return n
    clues, files = collapse_clue_spaces.migrate(args.root, set(CHANNELS), change, args.dry_run)
    print(f"{'would mend' if args.dry_run else 'mended'} {clues} clues in {files} files")
    print(f"{len(left)} clues keep a fault:")
    for pid, eid, text, found in sorted(left):
        print(f"  {pid} {eid}: {text!r}: {'; '.join(why for why, _ in found)}")


if __name__ == "__main__":
    main()
