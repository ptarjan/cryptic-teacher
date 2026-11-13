#!/usr/bin/env python3
"""Whether the stores pages.yml's build restored still fit this checkout's code.

    python3 tools/cache_warmth.py PAGE_FINGERPRINT
    -> "warm"            the row store holds this code's rows for (nearly)
                         every puzzle file, and the page store was saved under
                         this checkout's page fingerprint
    -> "cold <reason>"   one of them does not

PAGE_FINGERPRINT is the fingerprint (tools/page_cache.py) the restored page
store was saved under: Save the puzzle pages puts it in the cache key, and the
build reads it back from the key it matched ('' when that key carries none).

The build asks this when tools/ci_scope.py answers "code": nothing but puzzle
data and tools/*.py modules moved since the live commit. The puzzle fast path
skips only warm-up (the row-cache slices and the page shards), never a
decision, so it is right whatever the code did; it is slow only when the code
the stores are keyed on moved, because then the reindex re-makes every row in
one step (~175s cold) and the render re-renders every page in one step. That
is exactly what this checks, from the stores themselves, rather than guessing
from file names that a tools/ edit might have moved them.
"""
import sys

import row_cache

#: Rows a warm store may lack: the files the push itself added or changed
#: (made by the reindex in seconds), up to ci_scope's cap on the fast path.
MAX_MISSING = 1500


def row_maps():
    """(module, function, roots, salt) of every cached_map the warm-up slices
    fill (fetch_puzzle.warm_rows): the same arguments, so the same code keys."""
    import difficulty
    return [
        ("fetch_puzzle", "index_row", {"index_row_deps"}, ""),
        ("difficulty", "clue_row", {"_load_clue_inputs"},
         difficulty._files_hash(difficulty.LEXICON, difficulty.WORDNET)),
        ("difficulty", "history_row", set(), ""),
    ]


def stored_rows(conn, code):
    """How many rows the store holds under `code` (a code's rows sort together)."""
    lo = row_cache._prefix(code) + ":"
    return conn.execute("SELECT COUNT(*) FROM rows WHERE key >= ? AND key < ?",
                        (lo, lo[:-1] + ";")).fetchone()[0]


def check(page_fp):
    import page_cache
    import puzzle_paths
    files = len(puzzle_paths.puzzle_files())
    conn = row_cache._open()
    try:
        for name, fn, roots, salt in row_maps():
            have = stored_rows(conn, row_cache.code_for(name, fn, roots, salt))
            if have < files - MAX_MISSING:
                return f"cold {name}.{fn}: {have} stored row(s) for {files} puzzle file(s)"
    finally:
        conn.close()
    fp = page_cache.fingerprint()
    if not fp or fp != page_fp:
        return f"cold the page store was saved under {page_fp[:12] or 'no fingerprint'}, this code's is {(fp or 'none')[:12]}"
    return "warm"


def main(argv):
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        print(check(argv[0].strip()))
    except Exception as err:  # noqa: BLE001 - anything unreadable is a cold store: the full path is never wrong
        print(f"cold {type(err).__name__}: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
