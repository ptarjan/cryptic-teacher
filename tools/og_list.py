#!/usr/bin/env python3
"""Prune the puzzle cards no puzzle gets, then print the ones to draw.

  python3 tools/og_list.py LIMIT   # make_og_card.py --prune, then --stale --limit LIMIT

One process for both steps, so the corpus-wide eligible() list is worked out
once instead of twice. It depends
only on the puzzle files and the index, neither of which pruning touches.
What prune() reports goes to stderr: stdout is the list make_og.sh loops over.

Both lists are what make_og_card.eligible() and card_key() say, but each
puzzle's share of them (has it an annotation, does pick() find a clue to draw,
its card key: the hash of the HTML its card is drawn from) comes off
tools/row_cache.py, made again only for a puzzle
whose file, blog facts or drawing code moved. Worked out afresh, they read and
score every one of the ~50k puzzle files, which was most of the deploy's card
step even when no card needed drawing. A row is keyed, beyond row_cache's
code reach and the tools/data files that code names (clue_types.json,
books.json: row_cache.data_files), on make_og_card._salt(): the template and
the app.js tables it draws from.

Not on all of tools/data, as it was: annotate and blog-facts commits touch a
sidecar there (blog_disagree.json, setter_error.json, the lexicons) many times
a day, none of which a card reads, and each one worked all ~17k rows out again
(~45s of the deploy). tools/test_og_card_key.sh holds that line.

An edit to the drawing code works every row out again (a minute or so, no
drawing), but a card is redrawn only if its HTML came out different.
"""
import contextlib
import functools
import sys

import fetch_puzzle
import make_og_card
import puzzle_paths
import row_cache


@functools.cache
def _blog_hashes():
    return fetch_puzzle.blog_fact_hashes()


def blog_deps(path, row):
    return _blog_hashes().get(path.stem)


def annotated_row(path):
    """Whether the puzzle has any annotation: what puts it among ours."""
    return any(e.get("annotation") for e in fetch_puzzle.read_puzzle_file(path)["entries"])


def card_row(path):
    """(whether pick() finds a clue to draw, the card key or None)."""
    ok = bool(make_og_card.pick(path.stem)[0])
    return ok, make_og_card.card_key(path.stem) if ok else None


def main(argv):
    limit = int(argv[0])
    salt = make_og_card._salt().hexdigest()
    files = puzzle_paths.puzzle_files()
    by_id = {f.stem: f for f in files}
    marks = row_cache.cached_map("og_list", annotated_row, files)
    ours = sorted(f.stem for f, has in zip(files, marks) if has)
    taken = set(ours)
    wanted = ours + [b for b in make_og_card.blog_card_ids() if b not in taken and b in by_id]
    rows = row_cache.cached_map("og_list", card_row, [by_id[p] for p in wanted],
                                salt=salt, deps=blog_deps)
    keys = {p: key for p, (ok, key) in zip(wanted, rows) if ok}
    eligible = [p for p in wanted if p in keys]
    make_og_card.eligible = lambda: eligible
    make_og_card.card_key = lambda pid: keys[pid]
    with contextlib.redirect_stdout(sys.stderr):
        make_og_card.prune()
        adopted = make_og_card.adopt_legacy()
        if adopted:
            print(f"og_list: took {adopted} card(s) drawn under the old key as current")
    for i, pid in enumerate(make_og_card.stale()):
        if i >= limit:
            break
        print(pid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
