#!/usr/bin/env python3
"""Where the hint ladder loses people.

Every save already carries `hintsShown`: per clue, the rungs that were opened,
in the order they were asked for. That is a record of exactly where a solver
gave up and took the answer, and it has been synced to the Worker all along —
nobody has ever looked at it.

The question it answers is not "how hard is this clue" (tools/difficulty.py
already measures that from the clue itself). It is "which of OUR rungs failed":
a clue where solvers climb all five and still take the answer is a clue whose
walkthrough does not land, and that is a hint-writing bug we would otherwise
never hear about.

    python3 tools/rung_report.py <sync-code>
    python3 tools/rung_report.py --file saves.json

Reads only. Nothing here writes to the site, and the report is aggregate — a
sync code is a crossword, not an identity (see sync/worker.js).
"""
import argparse
import json
import sys
import urllib.request
from collections import Counter

SYNC = "https://cryptic-teacher-sync.curly-unit-b9e0.workers.dev"
ANSWER = "answer"
# The ladder in the order app.js recommends, so "how far did they climb" is a
# position in this list and not the arbitrary order the rungs were asked for.
LADDER = ["type", "definition", "indicators", "blocks", "walkthrough"]


def fetch(code):
    with urllib.request.urlopen(f"{SYNC}/s/{code}", timeout=20) as r:
        return json.load(r)


def saves_of(envelope):
    """The per-puzzle saves, whatever wrapper the Worker put them in."""
    for key in ("saves", "data", "value"):
        if isinstance(envelope, dict) and isinstance(envelope.get(key), dict):
            envelope = envelope[key]
    return {k: v for k, v in envelope.items() if isinstance(v, dict) and "hintsShown" in v}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("code", nargs="?", help="sync code to read")
    ap.add_argument("--file", help="a saves JSON on disk instead of the Worker")
    args = ap.parse_args()
    if not args.code and not args.file:
        ap.error("give a sync code or --file")

    envelope = json.load(open(args.file)) if args.file else fetch(args.code)
    saves = saves_of(envelope)
    if not saves:
        # An empty report and a report of emptiness look identical, and only one
        # of them means "the ladder is working".
        print("no saves with hintsShown in that envelope — nothing to report", file=sys.stderr)
        return 1

    depth = Counter()      # how far up the ladder before the answer was taken
    bailed = Counter()     # clue id -> took the answer
    climbed = Counter()    # clue id -> opened at least one rung
    rung_use = Counter()
    clues = 0

    for pkey, save in saves.items():
        for entry, rungs in (save.get("hintsShown") or {}).items():
            if not isinstance(rungs, list) or not rungs:
                continue
            clues += 1
            climbed[pkey] += 1
            for r in rungs:
                rung_use[r] += 1
            if ANSWER in rungs:
                bailed[pkey] += 1
                # Height, not count: taking the walkthrough alone is climbing
                # further than taking type and definition, and counting rungs
                # would say the opposite.
                reached = [LADDER.index(r) for r in rungs if r in LADDER]
                depth[max(reached) + 1 if reached else 0] += 1

    print(f"clues with any rung open: {clues}   answers taken: {sum(bailed.values())}"
          f" ({100 * sum(bailed.values()) / clues:.0f}%)\n")

    print("how far they got before taking the answer")
    for i in range(len(LADDER) + 1):
        label = "nothing first" if i == 0 else f"up to {LADDER[i - 1]}"
        n = depth[i]
        print(f"  {label:<22} {n:>4}  {'#' * min(n, 40)}")

    print("\nrungs opened, all clues")
    for rung, n in rung_use.most_common():
        print(f"  {rung:<22} {n:>4}")

    # Ranked, because a list of every puzzle is a list nobody reads. A puzzle
    # only appears once it has enough clues opened for a rate to mean anything.
    print("\npuzzles by how often the ladder ended in the answer (min 5 clues)")
    rates = [(bailed[p] / climbed[p], p, bailed[p], climbed[p])
             for p in climbed if climbed[p] >= 5]
    for rate, p, b, c in sorted(rates, reverse=True)[:10]:
        print(f"  {p:<28} {100 * rate:>3.0f}%   {b}/{c}")
    if not rates:
        print("  (no puzzle has 5 clues with rungs open yet)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
