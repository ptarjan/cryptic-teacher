#!/usr/bin/env python3
"""Prune the puzzle cards no puzzle gets, then print the ones to draw.

  python3 tools/og_list.py LIMIT   # make_og_card.py --prune, then --stale --limit LIMIT

One process for what make_og.sh used to ask of make_og_card.py in two, so the
corpus-wide eligible() list is worked out once instead of twice. It depends
only on the puzzle files and the index, neither of which pruning touches.
What prune() reports goes to stderr: stdout is the list make_og.sh loops over.

A separate file rather than a flag on make_og_card.py because that script
hashes its own bytes into every card's key, and any edit to it redraws them all.
"""
import contextlib
import functools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_og_card  # noqa: E402


def main(argv):
    limit = int(argv[0])
    make_og_card.eligible = functools.cache(make_og_card.eligible)
    with contextlib.redirect_stdout(sys.stderr):
        make_og_card.prune()
    for i, pid in enumerate(make_og_card.stale()):
        if i >= limit:
            break
        print(pid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
