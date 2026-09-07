#!/usr/bin/env python3
"""How many annotation runs a puzzle has already been given, and lost.

The nightly queue in tools/daily_update.sh is "un-annotated, newest first", and
nothing in it remembers effort. A puzzle whose annotate call dies — the output
ceiling reached on the first try AND on the in-run retry, a crash, a CLI that
falls over mid-run — ends the night exactly as it began it: un-annotated,
still the newest, and therefore first in tomorrow's queue, to be annotated FROM
SCRATCH at a full puzzle's price. indysunday-1906 is the worked example: its
2026-09-06 run was killed by the 64000-token output ceiling in force at the
time, left the puzzle at 0/30, and it was still standing at the head of a later
night's queue. It escaped being bought a second time only because a person
annotated it by hand that morning.

A rejected annotation costs the same. daily_update.sh reverts tonight's own
puzzle files on VALIDATION FAILED, so the work is bought, thrown away, and
queued again — and a puzzle that trips the validator systematically would do
that every night, indefinitely, at full price each time.

So the attempts are counted, and a puzzle that has had ANNOTATE_MAX_ATTEMPTS of
them leaves the queue until a person looks at it. This is the argument
tools/fetch_puzzle.py's puzzle_is_annotated already makes for clues the paper
printed blank — "buys a full annotation run on it every night, for ever" — made
for the failure case rather than the impossible one.

Two attempts by default, because a night already contains one in-run retry: two
nights is up to four tries, which is enough to tell a hard puzzle from a broken
one. Only the PUZZLE's own failures may be counted — a run stopped by a usage
lockout or an expired login learned nothing about the puzzle, and charging it
one would blacklist a perfectly good grid for a fault that had nothing to do
with it. That judgement belongs to the caller; this file counts what it is
given.

The state is tracked, not gitignored like .solve_attempts.json, for one reason:
the nightly job runs in a throwaway worktree (tools/nightly_worktree.sh) and
commits what it changed, so a tracked file survives the rebuild and reaches
every checkout, while an untracked one in the worktree would be thrown away on
exactly the night the count needed to hold.

    python3 tools/annotate_attempts.py record <id> --reason "..." [--session <uuid>]
    python3 tools/annotate_attempts.py clear <id>
    python3 tools/annotate_attempts.py blocked [--if-changed]
    python3 tools/annotate_attempts.py session <id>
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# An override so the test can drive the real thing against a scratch file
# instead of the corpus's own ledger. The default is the tracked copy.
LEDGER = Path(os.environ.get("ANNOTATE_ATTEMPTS_FILE")
              or ROOT / "tools" / "data" / "annotate_attempts.json")


def max_attempts():
    """The limit, from the environment, or 2.

    A typo'd limit is refused rather than quietly replaced by the default: a
    scheduler that means ANNOTATE_MAX_ATTEMPTS=3 and writes "3 " must not spend
    a month believing it set something. The wording matches the allowlist
    tools/alert.sh greps the run log for, so it reaches Discord rather than
    only the log.
    """
    raw = os.environ.get("ANNOTATE_MAX_ATTEMPTS", "").strip()
    if not raw:
        return 2
    try:
        return max(1, int(raw))
    except ValueError:
        raise SystemExit("annotate_attempts.py: error: ANNOTATE_MAX_ATTEMPTS="
                         f"{raw!r} is not a number")


def load():
    """The ledger, always in its full shape.

    A missing file is a repo that has never lost an annotation; a corrupt one
    says so on stderr rather than dying, because the worst thing this file can
    do is stop a night's annotation over its own bookkeeping.
    """
    data = {}
    try:
        data = json.loads(LEDGER.read_text())
    except FileNotFoundError:
        pass
    except ValueError as err:
        print(f"annotate_attempts.py: error: {LEDGER} is not readable JSON "
              f"({err}) — starting a fresh ledger", file=sys.stderr)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("puzzles", {})
    data.setdefault("alerted", [])
    return data


def save(data):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def prune(data):
    """Forget puzzles that are annotated now, however that happened.

    A block is only ever a way of keeping a puzzle out of the queue, so once it
    IS annotated the entry means nothing — and left behind it is a trap: the
    blind-solve grading drops the annotation of every clue the model got wrong
    (see tools/fetch_puzzle.py --refresh-unsolved), which puts an already-blocked
    puzzle back in the queue where the block would silently hold it out of reach
    for ever. indysunday-1906 is also the case for the other half of this: it
    was annotated by hand, and a hand fix must clear the count without anyone
    having to remember a second command.

    Only ids the index positively reports as annotated are dropped. An id the
    index has never heard of is left alone: a ledger driven from a scratch file
    (the test) or a checkout mid-rewrite must not have its history deleted by a
    file it isn't about.
    """
    try:
        idx = json.loads((ROOT / "puzzles" / "index.json").read_text())
    except (FileNotFoundError, ValueError):
        return False
    done = {p["id"] for p in idx.get("puzzles", []) if p.get("annotated")}
    stale = [i for i in data["puzzles"] if i in done]
    for i in stale:
        del data["puzzles"][i]
    return bool(stale)


def blocked_ids(data):
    limit = max_attempts()
    return sorted(i for i, rec in data["puzzles"].items()
                  if rec.get("attempts", 0) >= limit)


def cmd_record(args):
    data = load()
    rec = data["puzzles"].setdefault(args.id, {})
    rec["attempts"] = rec.get("attempts", 0) + 1
    rec["date"] = date.today().isoformat()
    rec["reason"] = (args.reason or "")[:300]
    # The session of the LAST attempt and no other, because that is the only
    # one --resume can carry on from. An attempt whose session id we were not
    # told about therefore erases the one before it: resuming a conversation
    # two nights older than the work would replay a transcript that no longer
    # describes the file on disk.
    if args.session:
        rec["session"] = args.session
    else:
        rec.pop("session", None)
    save(data)
    print(rec["attempts"])


def cmd_clear(args):
    data = load()
    if data["puzzles"].pop(args.id, None) is not None:
        save(data)


def cmd_blocked(args):
    data = load()
    changed = prune(data)
    ids = blocked_ids(data)
    if args.if_changed:
        # Told once, not nightly. tools/alert.sh's header is explicit about
        # this: the pre-reset job repeated one paragraph four times on
        # 2026-08-07 and a channel that cries wolf on the hour teaches its one
        # reader to scroll past it. The set that has already been reported is
        # remembered IN the ledger, so it survives the worktree rebuild the
        # same way the counts do.
        if ids == sorted(data["alerted"]):
            if changed:
                save(data)
            return
        data["alerted"] = ids
        save(data)
    elif changed:
        save(data)
    for i in ids:
        print(i)


def cmd_session(args):
    """The session id of the last attempt, if we hold one.

    Prints nothing when there is none, so a caller can test the output for
    emptiness and never has to parse an excuse.
    """
    sid = load()["puzzles"].get(args.id, {}).get("session")
    if sid:
        print(sid)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("record", help="count one failed attempt against a puzzle")
    p.add_argument("id")
    p.add_argument("--reason", default="", help="why it failed, in the words of whatever said so")
    p.add_argument("--session", default="", help="the claude session id that attempt used")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("clear", help="forget a puzzle: it annotated cleanly")
    p.add_argument("id")
    p.set_defaults(func=cmd_clear)

    p = sub.add_parser("blocked", help="ids at or over the attempt limit, one per line")
    p.add_argument("--if-changed", action="store_true",
                   help="print them only when the set differs from the last time this asked")
    p.set_defaults(func=cmd_blocked)

    p = sub.add_parser("session", help="the session id of a puzzle's last attempt")
    p.add_argument("id")
    p.set_defaults(func=cmd_session)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
