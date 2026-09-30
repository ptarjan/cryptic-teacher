"""One map over the corpus, spread across the machine's cores.

The build reads every puzzle file several times over (tens of thousands of
them), and each read is independent of the others, so the deploy's runner
does that work on all its cores instead of one.

Forked, not spawned: a worker starts with everything the parent had already
built in memory (the lexicon, a lookup table, a cache), so what a worker needs
is whatever was loaded before pmap() was called, and nothing is pickled but
the items and the results. Results come back in the order of the items, so a
caller gets exactly what the serial loop would have produced.

  pmap(fn, items)   # [fn(x) for x in items]; fn must be a module-level function
"""
import multiprocessing
import os


def workers():
    """Cores to use. CT_JOBS overrides, and CT_JOBS=1 runs serially, in-process."""
    return int(os.environ.get("CT_JOBS") or os.cpu_count() or 1)


def pmap(fn, items, chunksize=64):
    items = list(items)
    n = min(workers(), max(1, len(items) // chunksize))
    if n <= 1 or multiprocessing.current_process().daemon:
        return [fn(x) for x in items]
    with multiprocessing.get_context("fork").Pool(n) as pool:
        return pool.map(fn, items, chunksize)
