#!/usr/bin/env python3
"""How much fifteensquared's readers talked about each puzzle, as a committed file.

  python3 tools/build_buzz.py          # rebuild tools/data/fifteensquared_buzz.json

A blog thread's size is the only public measure of whether a puzzle was worth
talking about, and it is the one thing in that data that survived testing: a
composite "quality" score built from the clues themselves correlated with the
favourite-clue votes at rho -0.116, and with thread size held constant at -0.007
— thread size itself was +0.833. So the site offers the signal that is real,
under its own name ("popular"), instead of a quality number that is not.

WHAT IT IS NOT. It measures ONE blog's audience, not ours and not the world's:
Guardian cryptics run a median of 64 comments against 10 for the Independent, on
puzzles of the same standing. Any use of this number has to be relative to the
series or it just sorts the papers — puzzles/index.json stores a within-series
percentile for exactly that reason, and the raw count is kept here only so the
percentile can be recomputed without the cache.

WHY IT IS COMMITTED. The comment cache lives in ~/cryptic-setter-data, outside
the repo, and the site is built in CI on a clean checkout — where reindexing
would find no cache and silently drop the field from every puzzle. A generated
file that CI cannot regenerate has to be in the repo.

Re-run it after tools/fetch_fifteensquared.py tops the cache up. Puzzles the
blog never covered, or covered outside the cached window, are simply absent, and
the site tags nothing it has no number for.
"""
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from favourites_survey import CACHE, puzzle_id, text_of

OUT = Path(__file__).resolve().parent / "data" / "fifteensquared_buzz.json"


def comment_counts():
    """puzzle id -> number of comments on its fifteensquared post."""
    counts = {}
    for path in sorted(glob.glob(os.path.join(CACHE, "posts", "*.json"))):
        post = json.load(open(path, encoding="utf-8"))
        title = post["title"]
        pid = puzzle_id(text_of(title["rendered"] if isinstance(title, dict) else title))
        if not pid:
            continue
        comments = os.path.join(CACHE, "comments", os.path.basename(path))
        if not os.path.exists(comments):
            continue
        # A puzzle can be blogged twice (a repost, a correction). The fuller
        # thread is the one that describes the reception.
        counts[pid] = max(counts.get(pid, 0), len(json.load(open(comments, encoding="utf-8"))))
    return counts


def main():
    if not os.path.isdir(os.path.join(CACHE, "posts")):
        raise SystemExit(f"no fifteensquared cache at {CACHE} — run tools/fetch_fifteensquared.py")
    counts = comment_counts()
    if not counts:
        raise SystemExit("the cache holds no post that names a puzzle we know")
    OUT.write_text(json.dumps(counts, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(counts)} puzzle(s) -> {OUT.relative_to(Path.cwd()) if str(OUT).startswith(str(Path.cwd())) else OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
