"""A unit's soft deadline: work that would run past it stops cleanly instead.

    import budget
    if budget.spent():
        budget.stop("tools/x.py: 300 of 900 rows made; the rest next run")

tools/unit_queue.py kills a unit at its limit. Paul, 2026-10-15: "Zero jobs
should ever be killed by timeouts. Don't make timeouts longer fix the jobs to
scale as our repo scales." So unit_queue.run sets CT_UNIT_DEADLINE (epoch
seconds) to a share of the limit (SHARE, below); a unit whose passes stop
cleanly exports it as CT_DEADLINE (daily_update.sh's with_deadline), and a long pass that keeps its
progress (tools/row_cache.py stores each batch as it is made; letter_facts'
lexicon chunks and clue results likewise) checks spent() between slices.
Out of time, stop() says how far it got, marks the unit as having backlog
left (unit_more.backlog_left: due again at the next tick, not after its
`every`) and exits STOP_RC, 0 unless the caller set it: a later run resumes off
the stored slices, so a cold cache costs a few bounded runs, not a kill.

Outside a unit (CT_DEADLINE unset) there is no deadline: a run by hand
finishes. CT_DEADLINE=0 stops at the first check, which the tests use.
"""
import os
import sys
import time

#: The share of a unit's limit before its deadline. The rest is left for the
#: commit and push (a rebase may rebuild generated files) and a slice in
#: flight when the deadline passes.
SHARE = 0.7
#: The exit status of stop(). blog_facts sets 75 (daily_update.sh: nothing
#: committed), as its files are half-written when it stops.
STOP_RC = 0


def deadline():
    """The epoch second work should stop by, or None (no deadline)."""
    v = os.environ.get("CT_DEADLINE", "")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def left():
    """Seconds to the deadline (negative past it), or None without one."""
    d = deadline()
    return None if d is None else d - time.time()


def spent(reserve=0):
    """Whether the deadline is under `reserve` seconds away (or past)."""
    s = left()
    return s is not None and s <= reserve


class Stopped(SystemExit):
    """stop()'s exit: a SystemExit, so a tool needs no handler of its own."""


def stop(why):
    """Say `why` (how far the run got) and exit STOP_RC with backlog left."""
    from unit_more import backlog_left
    # stderr: the ratings steps send stdout to /dev/null.
    print(f"out of time (CT_DEADLINE): {why}", file=sys.stderr, flush=True)
    backlog_left()
    raise Stopped(STOP_RC)
