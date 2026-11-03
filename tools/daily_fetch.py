"""The loop every numbered daily fetcher runs, written once.

fetch_puzzle.py (the Guardian's series), fetch_observer.py (Everyman) and
fetch_privateeye.py (Cyclops) all file a paper whose puzzles carry a running
number, and all three do the same four things with it: walk a run of numbers,
fetching each one not already held; find the run OLDER than what is held, for
--extend; read the numbers held off the file names; and, each night, re-ask
the source for the answers of puzzles that are still waiting for them. Each
fetcher keeps only what differs: how one puzzle is fetched, where it is held,
what its source's floor is, and what "answers arrived" means for one puzzle.

The fetchers hand their own functions in, rather than this module importing
them, so the names a test patches on a fetcher (fetch_number, puzzle_files,
reindex) are still the ones this loop calls.

What is NOT here, and why. --latest: every paper has its own idea of "newest"
(the Guardian fills gaps across five series, the Globe asks a date picker,
Metro has one URL) and the shared part is only the exit-3 contract. The Globe
and Metro walks: one walks dates it never holds on disk, the other walks
Wayback captures, so neither has a "number already held" to skip. The Times
feed's walk is a search along a chain of ids, not a run of numbers. Each
convert() reads a different source format.
"""

import time
import urllib.error

import provenance


def numbers_in(files, series):
    """Every number of `series` among `files`, read off the file names
    ("cyclops-412.json" is 412), sorted."""
    prefix = f"{series}-"
    return sorted(int(p.stem[len(prefix):]) for p in files
                  if p.stem.startswith(prefix) and p.stem[len(prefix):].isdigit())


def older(oldest, count, floor=1):
    """The `count` numbers below `oldest`, newest first, never below `floor`."""
    return range(oldest - 1, max(oldest - 1 - count, floor - 1), -1)


def walk(numbers, held, fetch, what="backfill", finish=None, stop_statuses=()):
    """Fetch each number in turn, skipping what `held` says is on disk and
    reporting what fails without stopping. Returns how many arrived.

    A paper's numbers are sequential but not gapless, so a 404 is normal. An
    HTTP status in `stop_statuses` is not: the fetch has already backed off
    through its own retries, so recording a gap would bake a lie into the
    archive, and the walk stops instead. `finish` runs once at the end (the
    Guardian and the Observer rebuild the index there), stopped or not. One
    polite second per number actually requested.
    """
    fetched = skipped = missing = 0
    for num in numbers:
        if held(num):
            skipped += 1
            continue
        try:
            fetch(num)
            fetched += 1
        except urllib.error.HTTPError as err:
            if err.code in stop_statuses:
                print(f"STOPPING at {num}: HTTP {err.code} after every retry — "
                      f"{fetched} fetched before it started refusing")
                if finish:
                    finish()
                raise
            print(f"skip {num}: HTTP {err.code}")
            missing += 1
        except Exception as err:  # one bad puzzle is reported, not the walk's end
            print(f"skip {num}: {type(err).__name__}: {err}")
            missing += 1
        time.sleep(1)
    if finish:
        finish()
    print(f"{what + ' ' if what else ''}done: {fetched} fetched, {skipped} already present, "
          f"{missing} unavailable")
    return fetched


def needs_answers(puzzle):
    """Is this puzzle still waiting for its paper's answers? Yes if an entry has
    none, and yes if the answers are only our own fill (any solution detail
    means a model or a blog filled them, not the paper's own feed). A model
    fill puts a letter in every square, so the first test alone would walk
    straight past the one puzzle whose answers are a guess."""
    return not all(e.get("solution") for e in puzzle["entries"]) or bool(
        provenance.solution_detail(puzzle))


def refresh(pending, one, label=lambda item: item):
    """Re-ask the source for each pending puzzle's answers, one polite second
    apart. `one(item)` returns True when the answers arrived (and were
    written). One puzzle's failure is reported and the next is asked.
    Returns (filled, failed): the caller decides from these whether the index
    needs rebuilding."""
    filled = failed = 0
    for item in pending:
        try:
            if one(item):
                filled += 1
        except Exception as err:  # one bad puzzle is reported, then the next is checked
            print(f"refresh {label(item)} failed: {type(err).__name__}: {err}")
            failed += 1
        time.sleep(1)
    print(f"refresh-unsolved: {filled}/{len(pending)} puzzle(s) gained solutions")
    return filled, failed
