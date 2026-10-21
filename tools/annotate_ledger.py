#!/usr/bin/env python3
"""Every burn checkpoint measures its own annotate cost; the room is woken when it drifts.

    python3 tools/annotate_ledger.py record            # audit since the last row, append one
    python3 tools/annotate_ledger.py record --since 2026-10-20T10:00:00+00:00 --dry-run
    python3 tools/annotate_ledger.py decide [--dry-run]  # the wake rule over the ledger

Paul 10-20: "check each run and hill climb on the cost" (target $0.022/clue, the
pre-bag level). tools/prereset_backfill.sh calls `record` (niced, time-boxed,
never failing the burn) about hourly and at the end of the burn. `record` runs
tools/annotate_audit.py's window audit over [end of the last ledger row, now),
appends one JSON line to ~/.cache/annotate_cost_ledger.jsonl, then applies the
wake rule. No model call anywhere: it is arithmetic over the CLI's transcripts.

A window with fewer than MIN_SESSIONS sessions writes no row, and the next one
reaches back to the same start (at most MAX_WINDOW_H), so thin runs accumulate.

The wake rule (should_wake), in code, queued quietly (wake.sh -q) to the room:
  (a) the last 3 rows' pooled $/clue is more than 10% above the best 3-row level
      since the last commit touching annotate code; or
  (b) the #1 cause is not the #1 cause of the previous wake;
at most once per COOLDOWN_H hours, and never while at or under the target.
"""
import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import annotate_audit as audit

REPO = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(os.environ.get("ANNOTATE_CACHE", pathlib.Path.home() / ".cache"))
LEDGER = pathlib.Path(os.environ.get("ANNOTATE_LEDGER", CACHE / "annotate_cost_ledger.jsonl"))
STATE = pathlib.Path(os.environ.get("ANNOTATE_WAKE_STATE", CACHE / "annotate_cost_wake.json"))
WAKE_SH = os.environ.get("WAKE_SH") or __import__("local_config").path("household_dir") + "/tools/wake.sh"
WAKE_ROOM = os.environ.get("ANNOTATE_WAKE_ROOM", "-1003929432016:61")
MIN_SESSIONS = 5
MAX_WINDOW_H = 12
FIRST_WINDOW_H = 2
ROLL = 3
REGRESS = 0.10
COOLDOWN_H = 4
TARGET = 0.022
# What "annotate code" means for the best-level baseline.
CODE_PATHS = ["tools/annotate*", "tools/validate_annotations.py", "tools/puzzle_worker.sh",
              "tools/clue_bag.py", "tools/annotate_prompt.md", "tools/annotate_bag_prompt.md"]


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def parse(t):
    return datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))


def read_ledger(path=None):
    rows = []
    try:
        for line in (path or LEDGER).read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return rows


def pooled(rows):
    """$/clue over rows: total cost over total clues, so a thin row weighs by its work."""
    clues = sum(r.get("clues") or 0 for r in rows)
    return sum(r.get("cost") or 0 for r in rows) / clues if clues else None


def code_commit(repo=REPO):
    """(sha, ISO committer time, subject) of the last commit touching annotate code."""
    out = subprocess.run(["git", "log", "-1", "--format=%h%x09%cI%x09%s", "--"] + CODE_PATHS,
                         cwd=repo, capture_output=True, text=True, check=False).stdout.strip()
    parts = out.split("\t")
    return tuple(parts) if len(parts) == 3 else (None, None, None)


def master_sha(repo=REPO):
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True,
                          text=True, check=False).stdout.strip()


def make_row(res, sha):
    return {"start": res["since"], "end": res["until"], "sha": sha, "sessions": res["sessions"],
            "puzzles": res["puzzles"], "clues": res["clues"], "cost": res["cost"],
            "cost_per_clue": res["cost_per_clue"], "turns_per_clue": res["turns_per_clue"],
            "first_fail": res["first_fail"],
            "top_causes": [{k: c[k] for k in ("key", "label", "sessions", "cost_after_check")}
                           for c in res["causes"][:3]]}


def should_wake(rows, since_commit, state, now):
    """(reason, facts) when the room should be woken, else (None, why not).

    rows: ledger rows, oldest first; since_commit: ISO time of the last annotate-code
    commit (None = all rows count); state: {woken, top} of the previous wake."""
    if since_commit:
        rows = [r for r in rows if parse(r["end"]) >= parse(since_commit)]
    if len(rows) < ROLL:
        return None, f"only {len(rows)} rows since the last annotate-code commit"
    cur = pooled(rows[-ROLL:])
    rolls = [pooled(rows[i:i + ROLL]) for i in range(len(rows) - ROLL + 1)]
    best = min(x for x in rolls if x is not None) if any(x is not None for x in rolls) else None
    if cur is None:
        return None, "no clues in the last rows"
    if cur <= TARGET:
        return None, f"${cur:.3f}/clue is at the ${TARGET} target"
    woken = state.get("woken")
    if woken and (now - parse(woken)).total_seconds() < COOLDOWN_H * 3600:
        return None, f"woken {woken}, inside the {COOLDOWN_H}h cooldown"
    top = (rows[-1].get("top_causes") or [{}])[0].get("key")
    if best and cur > best * (1 + REGRESS):
        return (f"rolling ${cur:.3f}/clue is {cur / best - 1:+.0%} over the best 3-row level "
                f"${best:.3f} since the last annotate-code commit"), {"cur": cur, "best": best}
    if top and top != state.get("top"):
        return (f"cause #1 is now `{top}`, was `{state.get('top')}` at the previous wake"), \
            {"cur": cur, "best": best}
    if since_commit and state.get("commit") != since_commit:
        # Hill climb: each annotate-code change gets measured, and while the cost is
        # still over target the next cause is worked on, even with no regression.
        return (f"${cur:.3f}/clue is still over the ${TARGET} target {ROLL} runs after the "
                f"last annotate-code commit"), {"cur": cur, "best": best}
    return None, f"${cur:.3f}/clue within 10% of best ${best:.3f}; #1 cause unchanged"


def work_order(reason, facts, rows, commit):
    last = rows[-ROLL:]
    lines = [f"Annotate cost hill-climb: {reason}. Target $0.022/clue (pre-bag level); now "
             f"${facts['cur']:.3f}. Latest ledger rows (end, sessions, $/clue, turns/clue):"]
    for r in last:
        pc, tc = r.get("cost_per_clue"), r.get("turns_per_clue")
        lines.append(f"  {r['end'][:16]}  {r['sessions']} sessions, {r.get('clues', 0)} clues, "
                     f"${pc or 0:.3f}/clue, {tc or 0:.2f} turns/clue")
    top = (last[-1].get("top_causes") or [None])[0]
    if top:
        lines.append(f"Top cause: {top['label']} - {top['sessions']} sessions, "
                     f"${top['cost_after_check']:.2f} spent after the check in them.")
    lines.append("Last annotate-code commit: %s %s" % (commit[0] or "?", commit[2] or ""))
    lines.append("Ledger: ~/.cache/annotate_cost_ledger.jsonl; `python3 tools/annotate_audit.py --since "
                 "<ISO> --json` re-audits a window. Check git log for a fix already landed for this "
                 "cause; if none, spawn ONE Sonnet worker (isolation=worktree) to fix it, code-side if "
                 "possible; target $0.022/clue.")
    return "\n".join(lines)[:1900]


def decide(dry_run=False, now=None):
    now = now or now_utc()
    rows = read_ledger()
    commit = code_commit()
    state = {}
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        pass
    reason, facts = should_wake(rows, commit[1], state, now)
    if not reason:
        print(f"annotate ledger: no wake - {facts}")
        return 0
    since = [r for r in rows if not commit[1] or parse(r["end"]) >= parse(commit[1])]
    text = work_order(reason, facts, since, commit)
    if dry_run:
        print("annotate ledger: WOULD WAKE (dry run)\n" + text)
        return 0
    rc = subprocess.run([WAKE_SH, "-q", "-c", WAKE_ROOM, text], check=False).returncode
    if rc:
        print(f"annotate ledger: wake.sh exited {rc}; nothing recorded")
        return rc
    top = (since[-1].get("top_causes") or [{}])[0].get("key")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"woken": now.isoformat(timespec="seconds"), "top": top,
                                 "reason": reason, "commit": commit[1]}, indent=1) + "\n")
    print(f"annotate ledger: woke the room ({reason})")
    return 0


def record(since=None, until=None, dry_run=False):
    now = until or now_utc()
    rows = read_ledger()
    if since is None:
        floor = now - datetime.timedelta(hours=MAX_WINDOW_H)
        since = max(parse(rows[-1]["end"]), floor) if rows else now - datetime.timedelta(hours=FIRST_WINDOW_H)
    res = audit.window_audit(since, now)
    res["until"] = now.isoformat()
    if res["sessions"] < MIN_SESSIONS:
        print(f"annotate ledger: {res['sessions']} sessions since {since.isoformat()}, under "
              f"{MIN_SESSIONS} - no row")
        return None
    row = make_row(res, master_sha())
    print("annotate ledger row: " + json.dumps(row))
    if not dry_run:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["record", "decide"])
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--dry-run", action="store_true",
                    help="record: print the row, append nothing; decide: print the wake, send nothing")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "decide":
            return decide(args.dry_run)
        row = record(audit.parse_time(args.since) if args.since else None,
                     audit.parse_time(args.until) if args.until else None, args.dry_run)
        return decide(args.dry_run) if row else 0
    except Exception as e:  # never fail the burn
        print(f"annotate ledger: skipped, {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
