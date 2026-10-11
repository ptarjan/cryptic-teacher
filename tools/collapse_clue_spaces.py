"""One-shot migration (2026-10-11): cut each run of spaces in held clue text
to one, for the channels whose filers now do it themselves.

The publisher filers (fetch_puzzle, fetch_independent, fetch_privateeye)
build clues through enumeration.clue / collapse_spaces now, so a re-fetch
would collapse them anyway; a book's held puzzles are never re-filed by a
re-read (acquire_book skips a held leaf). Archive.org newspaper files are
left to their re-reads: edition_commit.spaced makes those editions due, and
file_archive_org_puzzles collapses them in place there.

Pure whitespace: only the clue's text changes, with its italics and its
annotation's offsets moved (enumeration.collapse_entry_spaces); the file is
written back in the corpus's own format, so nothing else moves.

    python3 tools/collapse_clue_spaces.py [--dry-run] [--channel publisher --channel book]
"""
import argparse
import json
import os
import pathlib

import enumeration

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANNELS = ("publisher", "book")


def collapse(puzzle):
    """The number of clues of `puzzle` changed, in place."""
    return sum(enumeration.collapse_entry_spaces(e) for e in puzzle.get("entries") or ())


def migrate(root, channels, change, dry_run=False, needle=None):
    """Run `change(puzzle)` (the number of clues it changed, in place) over
    each puzzle file under `root` whose source.retrievedFrom is in
    `channels` (and whose raw text holds `needle`, when given), writing
    back each one it changed in the corpus's own format: (clues, files)."""
    files = clues = 0
    for dirpath, _, names in os.walk(root):
        for name in sorted(names):
            if not name.endswith(".json"):
                continue
            path = pathlib.Path(dirpath) / name
            raw = path.read_text(encoding="utf-8")
            if needle is not None and needle not in raw:
                continue
            puzzle = json.loads(raw)
            if not isinstance(puzzle, dict) or (puzzle.get("source") or {}).get("retrievedFrom") not in channels:
                continue
            n = change(puzzle)
            if not n:
                continue
            files, clues = files + 1, clues + n
            if not dry_run:
                part = path.with_name(f".{path.name}.part")
                part.write_text(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                os.replace(part, path)
    return clues, files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--channel", action="append", help=f"source.retrievedFrom to touch (default {CHANNELS})")
    ap.add_argument("--root", default=str(ROOT / "puzzles"))
    args = ap.parse_args(argv)
    clues, files = migrate(args.root, set(args.channel or CHANNELS), collapse, args.dry_run, needle="  ")
    print(f"{'would collapse' if args.dry_run else 'collapsed'} {clues} clues in {files} files")


if __name__ == "__main__":
    main()
