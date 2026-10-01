#!/usr/bin/env python3
"""How wide the pre-reset backfill runs, and in what order it takes the queue.

Every wave runs at least CAP annotations at once: the job's goal is every
five-hour window spent to 100%, and nothing is gained by pacing — quota left on
a window when it turns over is gone. When CAP runs would not reach 100% by the
window's reset, the wave fans out to the width that would, up to BURST.

The queue order is the round-robin tools/prereset_backfill.sh builds, with the
puzzles a lockout cut off first, then Cracking the Cryptic's puzzles, then the
indicator cover (tools/indicator_cover.py).

    tools/prereset_plan.py --width                        # runs to keep in flight
    ids | tools/prereset_plan.py --cover-first "PINNED"   # the queue, cover first
    tools/prereset_plan.py --self-test
"""
import json
import math
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# These runs sit waiting on the API almost the whole time, so a spare one costs a
# process, not a core. CAP is the width every wave runs at least; BURST bounds the
# fan-out when the five-hour window is behind. Each run holds ~210 MB, so BURST
# 28 is ~6 GB of the box's ~12 GB free.
CAP = _env_int("PARALLEL_MAX", 14)
BURST = _env_int("PARALLEL_BURST", 28)

# Five-hour points one run in flight spends per hour. Measured off the burn's own
# per-wave lines in .prereset.log (see per_run_rate); this is the fallback when
# too few are readable: 27 points an hour at width 14 over 60 waves.
PER_RUN_RATE = 1.95
WAVE_LINE = re.compile(r"five-hour (\d+)% -> (\d+)% in ([\d.]+)h at width (\d+)")
RATE_WAVES = 60
RATE_MIN_WAVES = 10


def per_run_rate(lines):
    """Five-hour points per run-hour over the last RATE_WAVES waves logged.
    A wave whose meter fell crossed a reset and says nothing, so it is skipped."""
    points = run_hours = 0.0
    waves = [m for m in map(WAVE_LINE.search, lines) if m][-RATE_WAVES:]
    used = 0
    for m in waves:
        before, after, hours, width = int(m[1]), int(m[2]), float(m[3]), int(m[4])
        if after < before or hours <= 0 or width <= 0:
            continue
        points += after - before
        run_hours += hours * width
        used += 1
    if used < RATE_MIN_WAVES or points <= 0:
        return PER_RUN_RATE
    return points / run_hours


def width_for(pct, hours_left, rate):
    """Runs that would spend the five-hour window's remainder by its reset:
    ceil((100 - pct) / (hours_left * rate)), clamped to [CAP, BURST]. Any input
    missing or unusable means CAP."""
    try:
        need = math.ceil((100 - pct) / (hours_left * rate))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return CAP
    if hours_left <= 0 or rate <= 0:
        return CAP
    return max(CAP, min(BURST, need))


def width():
    """The width for the next wave, from the live five-hour meter and reset."""
    try:
        import weekly_usage
        pct = weekly_usage.usage_pct("session")
        hours_left, _ = weekly_usage.resets_in_hours("session")
        log = Path(os.environ.get("CT_MAIN_CHECKOUT") or REPO) / ".prereset.log"
        lines = log.read_text(errors="replace").splitlines() if log.exists() else []
        return width_for(pct, hours_left, per_run_rate(lines))
    except Exception as exc:  # noqa: BLE001 — any failed reading means CAP
        print(f"width: {exc}; running {CAP}", file=sys.stderr)
        return CAP


def self_test():
    """The backlog order: a puzzle whose blog names an indicator none of our
    annotations links yet jumps the queue, weighted by that indicator's clues."""
    # queue, {puzzle: pairs its blog gives}, {unlinked pair: clues}, pinned -> order
    A, B = ("anagram", "UPSIDEDOWN"), ("reversal", "UP")
    covers = [
        # a puzzle covering an unlinked indicator jumps the queue
        (["new", "mid", "old"], {"old": {A}}, {A: 5}, (), ["old", "new", "mid"]),
        # once annotated the pair is linked, so it no longer counts: nothing jumps
        (["new", "mid", "old2"], {"old2": {A}}, {}, (), ["new", "mid", "old2"]),
        # one common indicator beats two rare ones
        (["a", "b", "c"], {"b": {A}, "c": {B, ("hidden_word", "IN")}},
         {A: 10, B: 1, ("hidden_word", "IN"): 1}, (), ["b", "c", "a"]),
        # a pair counts once: the second puzzle giving only it stays in place
        (["a", "b", "c"], {"b": {A}, "c": {A}}, {A: 5}, (), ["b", "a", "c"]),
        # ties keep queue order (newest first)
        (["a", "b", "c"], {"b": {A}, "c": {B}}, {A: 3, B: 3}, (), ["b", "c", "a"]),
        # puzzles a lockout cut off still resume first
        (["r", "a", "b"], {"b": {A}}, {A: 5}, ("r", "gone"), ["r", "b", "a"]),
    ]
    bad = cover_self_test(covers) + width_self_test()
    n = len(covers) + len(WIDTH_CASES) + 3
    print(f"prereset plan self-test FAILED: {bad} of {n}" if bad
          else f"prereset plan self-test: {n} cases pass")
    return 1 if bad else 0


# (five-hour pct, hours to its reset, per-run rate) -> width, at CAP 14, BURST 28
WIDTH_CASES = [
    ((50, 2.0, 1.95), 14),    # on track: 14 runs spend 54.6 points in 2h
    ((60, 1.0, 1.95), 21),    # behind: 40 points in 1h needs 21 runs
    ((10, 0.5, 1.95), 28),    # way behind: 93 runs wanted, BURST caps it
    ((100, 1.0, 1.95), 14),   # window spent
    ((None, 1.0, 1.95), 14),  # meter unread
    ((50, 0.0, 1.95), 14),    # reset unread or passed
    ((50, -1.0, 1.95), 14),
]


def width_self_test():
    """WIDTH_CASES, the rate read off the log, and a failed read falling to CAP."""
    global CAP, BURST
    saved, (CAP, BURST) = (CAP, BURST), (14, 28)
    bad = 0
    try:
        for args, want in WIDTH_CASES:
            if width_for(*args) != want:
                print(f"FAIL width_for{args} = {width_for(*args)} (want {want})", file=sys.stderr)
                bad += 1
        line = "  weekly 1% -> 1%, five-hour {}% -> {}% in 0.1h at width 14"
        logged = [line.format(i, i + 3) for i in range(12)] + [line.format(90, 2)]
        for lines, want in [(logged, 3 / 1.4), (logged[:3], PER_RUN_RATE)]:
            if abs(per_run_rate(lines) - want) > 1e-9:
                print(f"FAIL per_run_rate of {len(lines)} lines = {per_run_rate(lines)} "
                      f"(want {want})", file=sys.stderr)
                bad += 1
        import weekly_usage
        real = weekly_usage.usage_pct
        def unreadable(_group):
            raise RuntimeError("no reading")
        weekly_usage.usage_pct = unreadable
        try:
            if width() != 14:
                print(f"FAIL width() with the meter unread = {width()} (want 14)",
                      file=sys.stderr)
                bad += 1
        finally:
            weekly_usage.usage_pct = real
    finally:
        CAP, BURST = saved
    return bad


def cover_self_test(covers):
    """covers' cases, and the key both sides of the match are spelled in."""
    import indicator_cover
    from indicator_keys import indicator_key
    bad = 0
    for queue, pairs_of, weight, pinned, want in covers:
        got, _ = indicator_cover.order(queue, pairs_of, weight, pinned)
        if got != want:
            print(f"FAIL cover {queue} with {pairs_of}: {got} (want {want})", file=sys.stderr)
            bad += 1
    # indicators.json keys "upside-down" as one word; so must the lookup
    for phrase, want in [("upside-down", "UPSIDEDOWN"), ("So-called", "SOCALLED"),
                         ("it’s off", "ITS OFF")]:
        if indicator_key(phrase) != want:
            print(f"FAIL indicator_key({phrase!r}) = {indicator_key(phrase)!r} (want {want!r})",
                  file=sys.stderr)
            bad += 1
    return bad


def ctc_puzzles():
    """Puzzles Cracking the Cryptic solved on video (tools/ctc_transcripts.py).
    Their praise is our only human signal of what makes a clue good, and a
    praised clue teaches the setting prompt nothing until it is annotated."""
    path = REPO / "tools/data/ctc_moments.json"
    if not path.exists():
        return set()
    return {v["puzzle"] for v in json.loads(path.read_text())["videos"] if v["puzzle"]}


def cover_first(pinned):
    """The ids on stdin, reordered: pinned first, then Cracking the Cryptic's
    puzzles, then the indicator cover, then the rest as they came. The summary
    goes to stderr, which is the burn's log."""
    import indicator_cover
    queue = sys.stdin.read().split()
    ctc = ctc_puzzles()
    pinned = pinned + [pid for pid in queue if pid in ctc and pid not in pinned]
    ordered, picks, weight = indicator_cover.plan(queue, pinned)
    reached = set().union(*(m for _, m in picks))
    head = ", ".join(f"{pid} ({len(m)})" for pid, m in picks[:4])
    print(f"indicator cover: {len(picks)} puzzles reach {len(reached)} of {len(weight)} "
          f"unlinked indicators" + (f"; next {head}" if picks else ""), file=sys.stderr)
    print("\n".join(ordered))
    return 0


def main():
    if "--cover-first" in sys.argv:
        at = sys.argv.index("--cover-first")
        return cover_first(" ".join(sys.argv[at + 1:]).split())
    if "--self-test" in sys.argv:
        return self_test()
    if "--width" in sys.argv:
        print(width())
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
