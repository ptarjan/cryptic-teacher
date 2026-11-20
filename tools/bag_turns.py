#!/usr/bin/env python3
"""The turn limit of a bag session, from its clue count: python3 tools/bag_turns.py CLUES

One rule for every bag kind (Annotate, shape backfills, blog re-check): the session reads
its one view, writes its annotations in one Write, checks, patches what failed, checks
again, about 10-15 turns for 30 clues (tools/annotate_bag_prompt.md). The limit is that
plus room for the clues that need a second look: 20 turns and one per clue, never under
40. It used to be a flat 80 for everything, and 13 blog bags hit it (11-03) because that
kind edited each puzzle's own file, a read, a check and an edit per puzzle.
tools/prereset_backfill.sh writes the number beside the bag's sid file; a bag that still
hits it ships what it finished and hands the rest back (puzzle_worker.sh worker_finish_bag).
"""
import sys

BASE = 20
FLOOR = 40


def turns(clues):
    return max(FLOOR, BASE + int(clues))


if __name__ == "__main__":
    try:
        print(turns(sys.argv[1] if len(sys.argv) > 1 else 0))
    except ValueError:
        print(FLOOR)
