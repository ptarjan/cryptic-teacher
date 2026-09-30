"""One map over the corpus, spread across the machine's cores.

The build reads every puzzle file several times over (tens of thousands of
them), and each read is independent of the others, so the deploy's runner
does that work on all its cores instead of one.

Forked, not spawned: a worker starts with everything the parent had already
built in memory (the lexicon, a lookup table, a cache), so what a worker needs
is whatever was loaded before pmap() was called, and nothing is pickled but
the items and the results. Results come back in the order of the items, so a
caller gets exactly what the serial loop would have produced.

A SystemExit in a worker (the tools' way of refusing) is raised again in the
parent with its message. Left alone it would kill the worker, and Pool.map
waits forever for a task whose process is gone.

  pmap(fn, items)   # [fn(x) for x in items]; fn must be a module-level function
"""
import multiprocessing
import os

_FN = None


class _Exit:
    def __init__(self, code):
        self.code = code


def _call(x):
    try:
        return _FN(x)
    except SystemExit as err:
        return _Exit(err.code)


def workers():
    """Cores to use. CT_JOBS overrides, and CT_JOBS=1 runs serially, in-process."""
    return int(os.environ.get("CT_JOBS") or os.cpu_count() or 1)


def pmap(fn, items, chunksize=64):
    global _FN
    items = list(items)
    n = min(workers(), max(1, len(items) // chunksize))
    if n <= 1 or multiprocessing.current_process().daemon:
        return [fn(x) for x in items]
    _FN = fn
    try:
        with multiprocessing.get_context("fork").Pool(n) as pool:
            out = pool.map(_call, items, chunksize)
    finally:
        _FN = None
    for r in out:
        if isinstance(r, _Exit):
            raise SystemExit(r.code)
    return out
