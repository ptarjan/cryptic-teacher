#!/usr/bin/env python3
"""Prune the puzzle cards no puzzle gets, then print the ones to draw.

  python3 tools/og_list.py LIMIT   # make_og_card.py --prune, then --stale --limit LIMIT

One process for both steps, so the corpus-wide eligible() list is worked out
once instead of twice. It depends
only on the puzzle files and the index, neither of which pruning touches.
What prune() reports goes to stderr: stdout is the list make_og.sh loops over.

Both lists are what make_og_card.eligible() and card_key() say, but each
puzzle's share of them (has it an annotation, does pick() find a clue to draw,
its card key) comes off tools/row_cache.py, made again only for a puzzle
whose file, blog facts or drawing code moved. Worked out afresh, they read and
score every one of the ~50k puzzle files, which was most of the deploy's card
step even when no card needed drawing. A row is keyed, beyond row_cache's
code reach, on make_og_card's own salt and a hash of tools/data (whatever
table the drawing code reads), so a change to either works them all out again.

A separate file rather than a flag on make_og_card.py because that script
hashes its own bytes into every card's key, and any edit to it redraws them all.
"""
import contextlib
import functools
import hashlib
import sys

import fetch_puzzle
import make_og_card
import puzzle_paths
import row_cache

DATA = puzzle_paths.ROOT / "tools" / "data"
SALT = None  # make_og_card._salt(), set before the rows are made


def data_hash():
    """Every file under tools/data but the blog facts, which each row names
    for its own puzzle instead (blog_deps)."""
    h = hashlib.sha1()
    for f in sorted(DATA.rglob("*")):
        if f.is_file() and "blog_facts" not in f.relative_to(DATA).parts:
            h.update(f.relative_to(DATA).as_posix().encode() + b"\0" + f.read_bytes())
    return h.hexdigest()


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
    return ok, make_og_card.card_key(path.stem, SALT) if ok else None


def main(argv):
    global SALT
    limit = int(argv[0])
    SALT = make_og_card._salt()
    salt = f"{SALT.hexdigest()}:{data_hash()}"
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
    make_og_card.card_key = lambda pid, _salt: keys[pid]
    with contextlib.redirect_stdout(sys.stderr):
        make_og_card.prune()
    for i, pid in enumerate(make_og_card.stale()):
        if i >= limit:
            break
        print(pid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
