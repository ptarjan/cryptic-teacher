#!/usr/bin/env python3
"""How wide the pre-reset backfill runs, and in what order it takes the queue.

Every wave runs CAP annotations at once: the job's goal is every five-hour
window spent to 100%, and nothing is gained by pacing — quota left on a window
when it turns over is gone.

The queue order is the round-robin tools/prereset_backfill.sh builds, with the
puzzles a lockout cut off first, then Cracking the Cryptic's puzzles, then the
indicator cover (tools/indicator_cover.py).

    tools/prereset_plan.py --width                        # runs to keep in flight
    ids | tools/prereset_plan.py --cover-first "PINNED"   # the queue, cover first
    tools/prereset_plan.py --self-test
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# These runs sit waiting on the API almost the whole time, so a spare one costs a
# process, not a core. The cap bounds the fan-out; it has to be wide enough to
# empty a five-hour window well before it turns over.
CAP = int(os.environ.get("PARALLEL_MAX", 14))


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
    bad = cover_self_test(covers)
    n = len(covers)
    print(f"prereset plan self-test FAILED: {bad} of {n}" if bad
          else f"prereset plan self-test: {n} cases pass")
    return 1 if bad else 0


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
        print(CAP)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
