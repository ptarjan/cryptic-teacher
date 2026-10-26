#!/usr/bin/env python3
"""Nightly work that failed, and the puzzle it failed on.

The nightly queues in tools/daily_update.sh pick work by date. When something
fails deterministically it is still the newest candidate the next night, so it
gets bought again at full price. So each failure is recorded along with a hash of
the puzzle it failed on: its clues, answers and grid. The item is skipped while
that hash still matches, and becomes eligible again by itself when the puzzle
changes: a corrected answer, a re-fetched clue (a row of
tools/data/setter_error.json, a clue the setter printed wrong, is an input of
its puzzle). Each record also keeps the version of what refused it
(code_version: the modules its reason names, else the kind's checkers, and
any other puzzle the reason leans on, such as the neighbour a DATE refusal
compares against), so a fix to that code or data makes the row due by itself,
in whichever tree reads the ledger once it holds the fix. `clear` is left for
an item that succeeded, or a retry wanted for any other reason. There is no
timer.

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
import yield_cpu  # noqa: F401  (a nice-19 burn's session yields too)
import argparse
import ast
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import clues_only
import enumeration
import puzzle_paths
from groups import entry_id

ROOT = Path(__file__).resolve().parent.parent
LEDGER = Path(os.environ.get("FAILED_INPUTS_FILE")
              or Path(os.environ.get("CT_MAIN_CHECKOUT") or ROOT) / ".failed_inputs.json")

if os.environ.get("FAILED_INPUTS_PUZZLES"):
    puzzle_paths.PUZZLE_DIR = Path(os.environ["FAILED_INPUTS_PUZZLES"])
BLIND_STASH = ROOT / ".blind"
SETTER_ERROR = ROOT / "tools" / "data" / "setter_error.json"

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


def _git(cwd, *args):
    """git's stdout in `cwd`, or None when it fails or there is no git."""
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def committed(pid):
    """Puzzle <pid> as HEAD holds it: ("puzzle", dict) for its file,
    ("clues", dict) for a clues-only file, or None when it is not in a git
    tree (the tree's copy is then the only one) or HEAD has no copy.

    A run's failure can be recorded while its edits are still on disk: a cold
    solve's answers written into the file, a clues-only file it promoted. Those
    edits are thrown away, so a hash of them never matched the puzzle again and
    the record blocked nothing (10-09..12: book-26052 and canberra-861019 were
    solved again after a recorded failure; repeats of unshipped solves were
    ~3-4% of the burn's spend). So a record hashes what is committed.
    """
    path = puzzle_paths.find(pid)
    top = _git(path.parent if path else ROOT, "rev-parse", "--show-toplevel")
    if top is None:
        return None
    top = Path(top.strip())
    names = _git(top, "ls-files", "--", f"puzzles/*/*/{pid}.json", f"clues_only/*/{pid}.json")
    for name in (names or "").split():
        text = _git(top, "show", f"HEAD:{name}")
        if text is None:
            continue   # staged, never committed
        try:
            data = json.loads(text)
        except ValueError:
            return None
        return ("clues" if name.startswith("clues_only/") else "puzzle", data)
    return None


def puzzle_inputs(pid, held=None):
    """The clues, answers and grid of puzzle <pid>'s file, or None if missing.
    `held` is committed(pid)'s answer, read in place of the tree's copy.

    During a blind run the answers sit in .blind/<pid>.json and the file holds
    blanks. The stash is read in their place, so a failure recorded mid-run
    hashes the same key the next night will.
    """
    if held is not None and held[0] == "clues":
        return held[1]
    if held is not None:
        puzzle = held[1]
    else:
        path = puzzle_paths.find(pid)
        if path is None:
            # Held as its clues alone: those are its inputs (tools/clues_only.py).
            return clues_only.read(pid) if "-" in str(pid) else None
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
    inputs = {"dimensions": puzzle.get("dimensions"), "entries": entries}
    # A run read the preamble too: one filed since the failure (genius-15's
    # border instructions) is what lets its blocks validate. Absent, the hash
    # is what it always was.
    if puzzle.get("preamble"):
        inputs["preamble"] = puzzle["preamble"]
    # Likewise a themeClue filed since (nation-3337's 30-across states the
    # fish its Across wordplay omits): it lets clue-word-less blocks stand.
    if puzzle.get("themeClue"):
        inputs["themeClue"] = puzzle["themeClue"]
    # A setter's slip filed since the failure is what lets its clue validate,
    # so the row is an input; absent, the hash is what it always was.
    slips = {k: v for k, v in json.loads(SETTER_ERROR.read_text(encoding="utf-8")).items()
             if k.split("/", 1)[0] == pid}
    if slips:
        inputs["setterErrors"] = slips
    return inputs


def input_hash(pid, held=None):
    return hashlib.sha256(json.dumps(puzzle_inputs(pid, held), sort_keys=True).encode()).hexdigest()[:16]


# The code that refuses each kind of item when the reason names none.
TOOLS = ROOT / "tools"
CHECKERS = {
    "solve": ("apply_solution", "clues_only", "jigsaw_fit", "enumeration", "puzzle_integrity"),
    "annotate": ("validate_annotations", "annotate_check", "apply_annotations", "enumeration"),
}
# "puzzle_integrity.RefusedWrite: ...", "validate_annotations.py: ..."
NAMED_MODULE = re.compile(r"\b([a-z_][a-z0-9_]*)\.(?:py\b|[A-Z]\w*(?:Error|Write)\b)")
# Another puzzle a refusal leans on: "not before nation-3264's 2012-12-04".
NAMED_PUZZLE = re.compile(r"\b[a-z]+-\d+\b")


@functools.lru_cache(maxsize=None)
def _module_version(name):
    """A hash of tools/<name>.py and the tools modules it imports directly."""
    path = TOOLS / f"{name}.py"
    try:
        text = path.read_bytes()
    except OSError:
        return "-"
    deps = set()
    try:
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                deps |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                deps.add(node.module.split(".")[0])
    except SyntaxError:
        pass
    h = hashlib.sha256(text)
    for dep in sorted(deps - {name}):
        dep_path = TOOLS / f"{dep}.py"
        if dep_path.exists():
            h.update(dep.encode() + b"\0" + dep_path.read_bytes())
    return h.hexdigest()


def code_version(kind, pid, reason):
    """The version of what refused <pid>: the modules its reason names (else
    the kind's CHECKERS) with their direct imports, and the date and inputs of
    every other puzzle the reason names (a DATE refusal holds until the
    neighbour is re-dated). A record keeps this beside its puzzle hash, so a
    fix to the check, or to the data it judged by, makes the row due by itself,
    in whichever tree reads the ledger once it holds the fix: nobody clears
    rows by hand or waits for a deploy (Paul 10-13)."""
    reason = reason or ""
    mods = sorted({m for m in NAMED_MODULE.findall(reason) if (TOOLS / f"{m}.py").exists()}
                  or CHECKERS[kind])
    h = hashlib.sha256()
    for m in mods:
        h.update(f"{m}:{_module_version(m)}\n".encode())
    for other in sorted(set(NAMED_PUZZLE.findall(reason)) - {pid}):
        held = committed(other)
        if held:
            date = held[1].get("date")
        else:   # not in a git tree: the file on disk is the only copy
            path = puzzle_paths.find(other)
            try:
                date = json.loads(path.read_text(encoding="utf-8")).get("date") if path else None
            except (OSError, ValueError):
                date = None
        h.update(f"{other}:{date}:{input_hash(other, held)}\n".encode())
    return h.hexdigest()[:16]


def due(kind, pid, rec):
    """Whether a recorded failure no longer holds: its puzzle changed, or the
    code or data that refused it did. A record from before code versions
    (no "code") that names the module refusing it is due, since nobody knows
    which version that was (10-13: genius-38 and Nation DATE rows waited by
    hand for a fix and a re-date); one naming none (the model's own failure,
    the bulk) holds on its puzzle alone."""
    if rec["puzzle"] != input_hash(pid):
        return True
    if "code" not in rec:
        return any((TOOLS / f"{m}.py").exists()
                   for m in NAMED_MODULE.findall(rec.get("reason") or ""))
    if rec["code"] == code_version(kind, pid, rec.get("reason")):
        return False
    # The code moved, the puzzle did not. A named module such as
    # puzzle_integrity is edited many times a day, and each edit made every
    # row naming it due: tls-1133 and nation-3490 were bought 3-4 times in
    # three days for the same refusal (10-16 audit). So a code-only release
    # waits out a cooldown that doubles each time the run was bought and
    # failed again with the puzzle unchanged (1, 2, 4... days, at most 16).
    return code_age_days(rec) >= code_cooldown_days(rec)


def code_cooldown_days(rec):
    return min(2 ** rec.get("retries", 0), 16)


def code_age_days(rec, today=None):
    try:
        then = datetime.fromisoformat(rec["date"]).date()
    except (KeyError, ValueError):
        return 10 ** 6   # undated: nothing to wait out
    return ((today or datetime.now(timezone.utc).date()) - then).days


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
    return sorted(i for i, rec in data[kind].items() if not due(kind, i, rec))


def cmd_record(args):
    if not args.judged and TRANSIENT.search(args.reason or ""):
        print(f"not recording {args.id}: that failure was ours or the "
              "network's, not the item's — it retries next run")
        sys.exit(3)   # a caller that alerts on a real failure tests for this
    data = load()
    reason = (args.reason or "")[:300]
    puzzle = input_hash(args.id, committed(args.id))
    old = data[args.kind].get(args.id)
    # Bought again on the same puzzle (released by a code change alone):
    # back off the next code-only release.
    retries = old.get("retries", 0) + 1 if old and old.get("puzzle") == puzzle else 0
    data[args.kind][args.id] = {
        "retries": retries,
        "puzzle": puzzle,
        "code": code_version(args.kind, args.id, reason),
        "date": datetime.now(timezone.utc).date().isoformat(),
        "reason": reason,
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
