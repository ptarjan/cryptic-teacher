#!/usr/bin/env python3
"""Keep puzzles on the site but off the inference queues.

Publishing a puzzle and paying to annotate it are separate decisions. They used
to be the same one: anything imported was, by virtue of being newer than the
backlog, first in line for the nightly annotator — so a bulk import was an
unasked-for bill the next morning (Paul, Everyman backfill, 2026-08-16).

A held puzzle is fully on the site: it opens, it is searchable, it shows its
answers if it has them. It is simply skipped by both spending steps of
tools/daily_update.sh — the annotator AND the cold solver. Nothing else reads
the flag, so holding can never break a page.

The flag is written into the PUZZLE FILE, not into puzzles/index.json. The index
is regenerated from the files by every fetcher run, so a hold recorded only in
the index would survive until the next nightly fetch and no longer — which is
the worst possible lifetime for a safety catch, since it looks like it worked.

    python3 tools/hold.py --list
    python3 tools/hold.py --set   --series everyman     # hold every unannotated one
    python3 tools/hold.py --clear --series everyman     # let the queue have them
    python3 tools/hold.py --clear 4097 4098

Import held and lift it deliberately; that way forgetting costs nothing, which
is the right direction for a mistake to fall.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_puzzle import (PUZZLE_DIR, puzzle_is_annotated, read_puzzle_file,  # noqa: E402
                          reindex, write_puzzle_file)


def load_all():
    out = []
    for path in sorted(PUZZLE_DIR.glob("*.js")):
        if path.name == "index.js":
            continue
        try:
            out.append((path, read_puzzle_file(path)))
        except Exception as exc:                      # noqa: BLE001
            print(f"skipping {path.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--set", action="store_true", help="hold: keep off the queues")
    g.add_argument("--clear", action="store_true", help="release to the queues")
    g.add_argument("--list", action="store_true", help="show what is held")
    ap.add_argument("--series", help="every unannotated puzzle of this series")
    ap.add_argument("numbers", nargs="*", type=int)
    args = ap.parse_args()

    puzzles = load_all()

    if args.list:
        held = [(pa, p) for pa, p in puzzles if p.get("annotateHold")]
        for _, p in sorted(held, key=lambda t: t[1].get("date") or 0):
            print(f"{p['number']:>6}  {p.get('series', 'cryptic'):<12}"
                  f"  {'annotated' if puzzle_is_annotated(p) else 'no hints'}")
        print(f"{len(held)} held" if held else "nothing held")
        return 0

    if not args.series and not args.numbers:
        print("say which: --series NAME, or a list of puzzle numbers", file=sys.stderr)
        return 2

    want = set(args.numbers)
    hit = []
    for path, p in puzzles:
        # --series takes only the UNANNOTATED ones. Holding a puzzle that is
        # already annotated changes nothing — the queue skips it regardless —
        # and would only clutter --list with puzzles that are not waiting.
        by_series = (args.series and p.get("series", "cryptic") == args.series
                     and not puzzle_is_annotated(p))
        if p["number"] not in want and not by_series:
            continue
        want.discard(p["number"])
        if args.set:
            if p.get("annotateHold"):
                continue                      # already held; leave the file alone
            p["annotateHold"] = True
        elif p.pop("annotateHold", None) is None:
            continue                          # not held; nothing to release
        write_puzzle_file(path, p)
        hit.append(p["number"])

    if want:
        print(f"not in the index: {sorted(want)}", file=sys.stderr)
        return 1
    if hit:
        reindex()
    verb = "held" if args.set else "released"
    print(f"{verb} {len(hit)} puzzle(s)" + (f": {sorted(hit)}" if 0 < len(hit) <= 12 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
