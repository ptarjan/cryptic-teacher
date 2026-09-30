#!/usr/bin/env python3
"""The blind solves' graded misses, and which of them have been learned from.

tools/data/blind_misses.json says which entries a model got wrong once the
paper's key arrived (fetch_puzzle.record_misses). This file keeps the other
half: tools/data/diagnosed_misses.json, one record per miss that a diagnosis
run (tools/solve_miss_prompt.md) has looked at, so each miss is paid for once.
It is a sibling rather than a field in blind_misses.json because that file's
readers treat every key under a puzzle as an entry id, and record_misses
rewrites a puzzle's block whole.

    python3 tools/solve_misses.py pending                 # "<puzzle> <entry>" per undiagnosed miss
    python3 tools/solve_misses.py packet <puzzle> <entry> # what the diagnosis run reads
    python3 tools/solve_misses.py record <puzzle> <entry> --verdict fixed|nothing-generalises|unfinished --note "..."
    python3 tools/solve_misses.py verdict <puzzle> <entry> # the recorded verdict and note, or nothing
    python3 tools/solve_misses.py keep-log <puzzle> <log> # save a cold solve's output for its later diagnosis

A cold solve's output is kept in the main checkout's .solve_logs/, untracked,
because the key that grades it arrives up to a fortnight after the nightly
worktree that ran it has been reset. Logs older than LOG_DAYS are pruned on
every keep-log.
"""
import argparse
import datetime
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from fetch_puzzle import read_puzzle_file, resolve_puzzle  # noqa: E402
from groups import entry_id  # noqa: E402
from solve_packet import crossing_map, label  # noqa: E402

MISSES = ROOT / "tools" / "data" / "blind_misses.json"
DIAGNOSED = ROOT / "tools" / "data" / "diagnosed_misses.json"
LOGS = Path(os.environ.get("CT_MAIN_CHECKOUT") or ROOT) / ".solve_logs"
VERDICTS = ("fixed", "nothing-generalises", "unfinished")
LOG_DAYS = 45


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pending():
    done = load(DIAGNOSED)
    return [(pid, eid) for pid, entries in sorted(load(MISSES).items())
            for eid in sorted(entries) if eid not in done.get(pid, {})]


def packet(pid, eid):
    puzzle = read_puzzle_file(resolve_puzzle(pid))
    ours = load(MISSES).get(pid, {})
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    if eid not in by_id:
        raise SystemExit(f"{pid} has no entry {eid}")
    e = by_id[eid]
    answer = e.get("solution") or ""
    lines = [
        (f"puzzle {pid} ({puzzle.get('name', '')}, setter {puzzle.get('setter') or 'unknown'}), "
         f"file {resolve_puzzle(pid).relative_to(ROOT)}"),
        f"entry {eid}, clue {label(e)} ({e['length']}): {e['clue'].get('text', '')}",
        f"we answered {ours.get(eid)}; the published answer is {answer}",
        "",
        "crossings, each with the answer we gave it:",
    ]
    cross = crossing_map(puzzle["entries"])
    crossed = {i for i, _, _ in cross.get(eid, [])}
    for i, other, j in sorted(cross.get(eid, [])):
        o = by_id[other]
        theirs = o.get("solution") or ""
        mine = ours.get(other, theirs)
        flag = "  <- also missed" if other in ours else ""
        lines.append(f"  pos{i} = {label(o)} pos{j}: {label(o)} ({o['length']}) "
                     f"{o['clue'].get('text', '')} = {mine}{flag}")
    unchecked = [i + 1 for i in range(e["length"]) if i + 1 not in crossed]
    lines.append(f"unchecked positions in {label(e)}: "
                 f"{', '.join(map(str, unchecked)) or 'none'}")
    differ = [i + 1 for i, (a, b) in enumerate(zip(ours.get(eid) or "", answer)) if a != b]
    lines.append(f"positions where ours and the answer differ: {', '.join(map(str, differ))}")
    log = LOGS / f"{pid}.log"
    lines.append("")
    lines.append(f"the cold solve's own output is kept at {log}" if log.exists()
                 else "the cold solve's output was not kept, so its reasoning is not available")
    return "\n".join(lines)


def record(pid, eid, verdict, note):
    data = load(DIAGNOSED)
    data.setdefault(pid, {})[eid] = {
        "ours": load(MISSES).get(pid, {}).get(eid),
        "verdict": verdict,
        "note": note,
        "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
    }
    DIAGNOSED.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                         encoding="utf-8")


def keep_log(pid, src):
    LOGS.mkdir(exist_ok=True)
    shutil.copyfile(src, LOGS / f"{pid}.log")
    cutoff = time.time() - LOG_DAYS * 86400
    for old in LOGS.glob("*.log"):
        if old.stat().st_mtime < cutoff:
            old.unlink()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pending")
    p = sub.add_parser("packet")
    p.add_argument("puzzle")
    p.add_argument("entry")
    r = sub.add_parser("record")
    r.add_argument("puzzle")
    r.add_argument("entry")
    r.add_argument("--verdict", required=True, choices=VERDICTS)
    r.add_argument("--note", required=True)
    v = sub.add_parser("verdict")
    v.add_argument("puzzle")
    v.add_argument("entry")
    k = sub.add_parser("keep-log")
    k.add_argument("puzzle")
    k.add_argument("log")
    args = ap.parse_args()
    if args.cmd == "pending":
        for pid, eid in pending():
            print(pid, eid)
    elif args.cmd == "packet":
        print(packet(args.puzzle, args.entry))
    elif args.cmd == "record":
        if (args.puzzle, args.entry) not in pending() and args.entry not in load(DIAGNOSED).get(args.puzzle, {}):
            raise SystemExit(f"{args.puzzle} {args.entry} is not a graded miss in {MISSES.name}")
        record(args.puzzle, args.entry, args.verdict, args.note)
    elif args.cmd == "verdict":
        rec = load(DIAGNOSED).get(args.puzzle, {}).get(args.entry)
        if rec:
            print(f"{rec['verdict']}: {rec['note']}")
    elif args.cmd == "keep-log":
        keep_log(args.puzzle, args.log)


if __name__ == "__main__":
    main()
