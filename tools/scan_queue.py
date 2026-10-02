"""The read queue the scan filers share (tools/file_archive_org_puzzles.py,
tools/file_trove_puzzles.py).

  - order(): what was never read comes first, in the caller's order; then
    what new input or an explicit --reread made stale, the longest since
    read first (a row's "readAt"), so a run never starts over: the unread
    still lead and the stale queue by age. A change of code alone makes
    nothing stale; when()/read_before() pick the rows --reread BEFORE
    reads again, so the slices of one re-read resume rather than restart.
  - parallel(): `workers` sources in flight at once, in a process pool, so
    one source's wait on the desktop VLM (one request at a time) overlaps
    another's OCR. No source starts once `deadline` (time.monotonic()) has
    passed.
  - lock(): one run per ledger, so a long full pass and the nightly never
    write the same ledger at once.
"""
import contextlib
import datetime
import fcntl
import multiprocessing
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def when(text):
    """The datetime an ISO `text` names ("now": this moment), None for None:
    a --reread BEFORE."""
    if text is None:
        return None
    if text == "now":
        return datetime.datetime.now(datetime.timezone.utc)
    t = datetime.datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def read_before(row, t):
    """Whether ledger `row` was last read before datetime `t` (no "readAt":
    it was)."""
    at = row.get("readAt")
    return not at or when(at) < t


def order(keys, rows, unread):
    """`keys` (in the caller's order) with the never-read first, then the
    rest by their row's "readAt", oldest first (none: first of all)."""
    fresh = [k for k in keys if unread(rows.get(k))]
    stale = [k for k in keys if not unread(rows.get(k))]
    stale.sort(key=lambda k: rows[k].get("readAt") or "")
    return fresh + stale


@contextlib.contextmanager
def lock(ledger, wait_for_it=False):
    """Yields whether this run holds `ledger`'s lock (<ledger>.lock); with
    `wait_for_it`, waits for it instead of yielding False."""
    path = ledger.with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if wait_for_it else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True


def parallel(items, fn, workers=1, deadline=None, init=None, initargs=()):
    """Yields (item, fn(*item)) as each finishes, at most `workers` at once
    (1: in this process, in order). `init(*initargs)` runs first in each
    process. No item starts once `deadline` has passed."""
    def due():
        return deadline is not None and time.monotonic() >= deadline
    items = iter(items)
    if workers <= 1:
        if init:
            init(*initargs)
        for item in items:
            if due():
                return
            yield item, fn(*item)
        return
    # Forked, so a worker starts with the parent's lexicon and modules loaded
    # (the parent loads no OCR model, so no thread is forked mid-call).
    method = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
    with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context(method),
                             initializer=init, initargs=initargs) as pool:
        running = {}

        def top_up():
            while len(running) < workers and not due():
                item = next(items, None)
                if item is None:
                    return
                running[pool.submit(fn, *item)] = item
        top_up()
        while running:
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in done:
                yield running.pop(fut), fut.result()
            top_up()
