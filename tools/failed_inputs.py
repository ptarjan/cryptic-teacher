#!/usr/bin/env python3
"""Nightly work that failed, and the puzzle it failed on.

The nightly queues in tools/daily_update.sh pick work by date. When something
fails deterministically it is still the newest candidate the next night, so it
gets bought again at full price. So each failure is recorded along with a hash of
the puzzle it failed on: its clues, answers and grid. The item is skipped while
that hash still matches, and becomes eligible again by itself when the puzzle
changes: a corrected answer, a re-fetched clue. The code is not part of the
hash: whoever changes a prompt, a validator or an applier and wants old failures
retried clears them once with `clear`, by id or by the words of their reason.
There is no timer.

A transient failure is never recorded, because it says nothing about the item.
That covers a usage lockout, an expired login, a network error, or an overloaded
API. `record` refuses those itself (TRANSIENT below), so no caller can charge an
item for them. The check reads the CLI's last words, so it is skipped for
--judged failures: a validator's or applier's verdict on the output is about the
item by definition, and it quotes clue text that could contain any word.

    python3 tools/failed_inputs.py record <kind> <id> --reason "..." [--judged]
    python3 tools/failed_inputs.py clear <kind> <id> [<id> ...]   # it succeeded, or retry it
    python3 tools/failed_inputs.py clear <kind> --reason "pieces"  # retry those whose reason says this
    python3 tools/failed_inputs.py clear <kind> --all              # retry every one
    python3 tools/failed_inputs.py skipped <kind>     # ids to leave out tonight
    python3 tools/failed_inputs.py summary            # one line for the log

The ledger is written to the main checkout, untracked. The nightly job runs in
a throwaway worktree (tools/nightly_worktree.sh) that is reset to origin/master
every night, and a run that exits before its commit (it does, when every
annotation fails validation) would lose a tracked record with the rest.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = Path(os.environ.get("FAILED_INPUTS_FILE")
              or Path(os.environ.get("CT_MAIN_CHECKOUT") or ROOT) / ".failed_inputs.json")
sys.path.insert(0, str(ROOT / "tools"))
import enumeration  # noqa: E402
import puzzle_paths  # noqa: E402
from groups import entry_id  # noqa: E402

if os.environ.get("FAILED_INPUTS_PUZZLES"):
    puzzle_paths.PUZZLE_DIR = Path(os.environ["FAILED_INPUTS_PUZZLES"])
BLIND_STASH = ROOT / ".blind"

KINDS = ("annotate", "solve")

# Failures that are about us or the network, not the item.
TRANSIENT = re.compile(
    r"usage limit|spend limit|limit reached|rate limit|five-hour window|Not logged in|"
    r"authenticate|OAuth|credit balance|overloaded|API Error: (?:5\d\d|429)|"
    r"Connection error|ECONNRESET|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|fetch failed|"
    r"Request timed out|network|safeguards flagged", re.IGNORECASE)


# Entry fields that are the puzzle and not our work on it, after the entry's id.
# Annotations are left out because a failed run can leave half of one on disk.
ENTRY_INPUTS = ("clue", "solution", "length", "position", "direction")


def puzzle_inputs(pid):
    """The clues, answers and grid of puzzle <pid>'s file, or None if missing.

    During a blind run the answers sit in .blind/<pid>.json and the file holds
    blanks. The stash is read in their place, so a failure recorded mid-run
    hashes the same key the next night will.
    """
    path = puzzle_paths.find(pid)
    if path is None:
        return None
    try:
        puzzle = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    key = {}
    stash = BLIND_STASH / f"{pid}.json"
    if stash.exists():
        key = json.loads(stash.read_text(encoding="utf-8"))
    entries = []
    for e in puzzle.get("entries", []):
        row = {"id": entry_id(e), **{k: e.get(k) for k in ENTRY_INPUTS}}
        # The clue's printed line, the one part of it a run reads.
        row["clue"] = enumeration.printed(e["clue"])
        if entry_id(e) in key:
            row["solution"] = key[entry_id(e)]
        entries.append(row)
    return {"dimensions": puzzle.get("dimensions"), "entries": entries}


def input_hash(pid):
    return hashlib.sha256(json.dumps(puzzle_inputs(pid), sort_keys=True).encode()).hexdigest()[:16]


def load():
    try:
        data = json.loads(LEDGER.read_text())
    except FileNotFoundError:
        data = {}
    except ValueError as err:
        print(f"failed_inputs.py: error: {LEDGER} is not readable JSON ({err}) "
              "— starting a fresh ledger", file=sys.stderr)
        data = {}
    if not isinstance(data, dict):
        data = {}
    # A record with no "puzzle" hash is held against the puzzle as it is now,
    # so no failure on record comes back without its puzzle changing.
    adopted = False
    for kind in KINDS:
        for pid, rec in data.setdefault(kind, {}).items():
            if "puzzle" not in rec:
                rec.pop("inputs", None)
                rec["puzzle"] = input_hash(pid)
                adopted = True
    if adopted:
        save(data)
    return data


def save(data):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def skipped(data, kind):
    """Ids whose recorded failure is on the puzzle as it is now."""
    return sorted(i for i, rec in data[kind].items() if rec["puzzle"] == input_hash(i))


def cmd_record(args):
    if not args.judged and TRANSIENT.search(args.reason or ""):
        print(f"not recording {args.id}: that failure was ours or the "
              "network's, not the item's — it retries next run")
        sys.exit(3)   # a caller that alerts on a real failure tests for this
    data = load()
    data[args.kind][args.id] = {
        "puzzle": input_hash(args.id),
        "date": datetime.now(timezone.utc).date().isoformat(),
        "reason": (args.reason or "")[:300],
    }
    save(data)
    print(f"{args.id} failed on this puzzle and is skipped until it changes")


def cmd_clear(args):
    if not (args.ids or args.reason or args.all):
        sys.exit("failed_inputs.py clear: name the ids, a --reason, or --all")
    data = load()
    gone = [i for i, rec in data[args.kind].items()
            if (not args.ids or i in args.ids)
            and (not args.reason or args.reason.lower() in rec.get("reason", "").lower())]
    for i in gone:
        del data[args.kind][i]
    if gone:
        save(data)
    if not args.ids:
        print(f"cleared {len(gone)} {args.kind} failures; they are tried again next run")


def cmd_skipped(args):
    for i in skipped(load(), args.kind):
        print(i)


def cmd_summary(args):
    """One log line: how many items are held out, and which.

    Records whose puzzle has changed are dropped here. They are eligible again
    anyway, and keeping them would make the ledger look like a list of blocks.
    """
    data = load()
    parts, stale = [], False
    for kind in KINDS:
        held = skipped(data, kind)
        for i in list(data[kind]):
            if i not in held:
                del data[kind][i]
                stale = True
        if held:
            parts.append(f"{kind} {len(held)} ({' '.join(held)})")
    if stale:
        save(data)
    total = sum(len(data[k]) for k in KINDS)
    print(f"skipped as failed on unchanged inputs: {total}"
          + (" — " + "; ".join(parts) if parts else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("record", help="record a failure against an item's current inputs")
    p.add_argument("kind", choices=KINDS)
    p.add_argument("id")
    p.add_argument("--reason", default="")
    p.add_argument("--judged", action="store_true",
                   help="a checker rejected the output: never treated as transient")
    p.set_defaults(func=cmd_record)
    p = sub.add_parser("clear", help="forget failures: an item succeeded, or the code that failed them changed")
    p.add_argument("kind", choices=KINDS)
    p.add_argument("ids", nargs="*", metavar="id")
    p.add_argument("--reason", help="only failures whose reason contains this (any case)")
    p.add_argument("--all", action="store_true", help="every failure of this kind")
    p.set_defaults(func=cmd_clear)
    p = sub.add_parser("skipped", help="ids to leave out tonight, one per line")
    p.add_argument("kind", choices=KINDS)
    p.set_defaults(func=cmd_skipped)
    p = sub.add_parser("summary", help="count of skipped items, for the log")
    p.set_defaults(func=cmd_summary)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
