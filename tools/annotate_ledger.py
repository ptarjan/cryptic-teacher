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

Paul 10-22: "Also analyze more often to fix cost per annotate". So the rule judges
the newest row alone, so one bad hour (10-22 00:51: $0.157/clue, 2.0 turns/clue)
is not averaged away. A row under MIN_CLUES clues is merged with the rows before
it (up to ROLL) and, if still thin, is noise and never wakes.

The wake rule (should_wake), in code, queued quietly (wake.sh -q) to the room:
  (a) payback: the #1 first-check-failure cause's $/clue after the check (its cost over the
      clues of the recent rows listing it) x clues still to annotate ((filed - hinted) +
      filing inflow until the /progress/ hinted ETA, capped at 12 months; x mean
      clues/puzzle) x SUCCESS_RATE (0.5) exceeds FIX_COST (~$6, one Sonnet worker),
      whatever the $/clue; or
  (b) regression: the latest window's pooled $/clue is more than 10% above the best such
      level since the last commit touching annotate code;
at most once per COOLDOWN_H (1) hours. The wake text carries the payback numbers.

Paul 10-23: "why aren't you doing cost fixing more often?" - at $0.015-0.021/clue the
old fixed $0.022 target never woke, even with one retry cause burning dollars an hour.
Then: "Lower the goal. I want to spend inference fixing the per clue as long as it pays
off in saved other inference." Hence the payback gate instead of a target.

Paul 10-23: "I think the savings is over many months. How far does progress say before we
are done annotating". backlog_burndown.py said 18,976 puzzles left (~26 days), but Paul
corrected it: /progress/ says hinted finishes in ~8 months, with 40,088 filed puzzles still
to annotate, filing adding ~800-1,350 puzzles a day and hinting ~620-715. So the saving is
counted per clue over the clues still to annotate, not per hour over a fixed 7 days, and
the counts are the page's own recorded nights (tools/progress.py), not a scrape.
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
ROLL = 3              # max rows merged to reach MIN_CLUES (was: always the last 3)
MIN_CLUES = 50        # a window thinner than this is noise: never wakes
AFTER_COMMIT_ROWS = 2  # re-judge this many rows after an annotate-code commit (was 3)
REGRESS = 0.10
COOLDOWN_H = 1        # was 4
# Payback gate: wake when fixing the top cause is expected to save more than the fix costs.
# Paul 10-23: "I think the savings is over many months" - so the horizon is the clues still
# to annotate (filed less hinted, plus the filing inflow until the page's hinted ETA, x mean
# clues/puzzle), not a fixed 7 days. The counts are /progress/'s own recorded nights.
MAX_HORIZON_DAYS = 365  # the horizon is the page's hinted ETA, capped at 12 months
PACE_DAYS = 7           # the page's 7-day pace
DEFAULT_CLUES_PER_PUZZLE = 28
SUCCESS_RATE = 0.5    # a fix is assumed to work half the time
FIX_COST = 6.0        # one Sonnet cost-fix worker, in dollars (estimate, not measured)
RATE_ROWS = 6         # recent rows averaged for the cause's $/h (never fewer than 3)
# What "annotate code" means for the best-level baseline.
CODE_PATHS = ["tools/annotate*", "tools/validate_annotations.py", "tools/puzzle_worker.sh",
              "tools/clue_bag.py", "tools/annotate_prompt.md", "tools/annotate_bag_prompt.md",
              # the modules an annotate run's checks and apply step import: a fix there is
              # an annotate fix (wordplay.py holds the "does not give the answer" refusal)
              "tools/wordplay.py", "tools/apply_annotations.py", "tools/annotation.py",
              "tools/clue_types.py", "tools/corroborate.py", "tools/definitions.py",
              "tools/groups.py", "tools/find_answer_leaks.py", "tools/find_renarration.py",
              "tools/hidden_mechanical.py", "tools/tree_normalize.py", "tools/code_checks.py"]


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


def window(rows):
    """The newest row, merged back with earlier rows (at most ROLL) until it holds
    MIN_CLUES clues; [] when even that is too thin to judge (so noise never wakes)."""
    out, clues = [], 0
    for r in reversed(rows[-ROLL:]):
        out.insert(0, r)
        clues += r.get("clues") or 0
        if clues >= MIN_CLUES:
            return out
    return []


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
    need = AFTER_COMMIT_ROWS if since_commit else 1
    if len(rows) < need:
        return None, f"only {len(rows)} rows since the last annotate-code commit"
    last = window(rows)
    cur = pooled(last)
    if cur is None:
        return None, f"under {MIN_CLUES} clues in the last {ROLL} rows - too thin to judge"
    rolls = [pooled(window(rows[:i + 1])) for i in range(len(rows))]
    best = min((x for x in rolls if x is not None), default=None)
    top_cause = (rows[-1].get("top_causes") or [{}])[0]
    per_clue, mean_clues = cause_per_clue(rows, top_cause.get("key"))
    left = clues_left(mean_clues)
    saving = per_clue * left * SUCCESS_RATE
    rate = cause_rate(rows, top_cause.get("key"))
    facts = {"cur": cur, "best": best, "rate": rate, "saving": saving, "left": left}
    woken = state.get("woken")
    if woken and (now - parse(woken)).total_seconds() < COOLDOWN_H * 3600:
        return None, f"woken {woken}, inside the {COOLDOWN_H}h cooldown"
    pay = (f"top cause `{top_cause.get('key')}` (${per_clue:.4f}/clue after check, ${rate:.2f}/h): "
           f"est. saving ${saving:.0f} over the remaining ~{left:,.0f} clues vs ~${FIX_COST:.0f} fix cost")
    if saving > FIX_COST:
        return pay, facts
    if best and cur > best * (1 + REGRESS):
        return (f"latest ${cur:.3f}/clue is {cur / best - 1:+.0%} over the best level "
                f"${best:.3f} since the last annotate-code commit; {pay}"), facts
    return None, f"${cur:.3f}/clue within 10% of best ${best:.3f}; {pay} - not worth a fix"


def cause_rate(rows, key):
    """$/hour the cause spends after the check: its cost over the hours of the recent rows
    (the last RATE_ROWS, so at least 3) that list it; 0 when none does."""
    cost = hours = 0.0
    for r in rows[-RATE_ROWS:]:
        for c in r.get("top_causes") or []:
            if c.get("key") == key:
                cost += c.get("cost_after_check") or 0
                hours += (parse(r["end"]) - parse(r["start"])).total_seconds() / 3600
    return cost / hours if hours > 0 else 0.0


def cause_per_clue(rows, key):
    """(the cause's $/clue after the check, mean clues per puzzle), over the last RATE_ROWS
    rows: cost over the clues of the rows that list the cause; 0 when none does."""
    cost = clues = 0.0
    for r in rows[-RATE_ROWS:]:
        for c in r.get("top_causes") or []:
            if c.get("key") == key:
                cost += c.get("cost_after_check") or 0
                clues += r.get("clues") or 0
    recent = rows[-RATE_ROWS:]
    puzzles = sum(r.get("puzzles") or 0 for r in recent)
    mean = sum(r.get("clues") or 0 for r in recent) / puzzles if puzzles else DEFAULT_CLUES_PER_PUZZLE
    return (cost / clues if clues else 0.0), mean


def backlog_counts(days=None):
    """(puzzles to annotate, filing inflow a day, horizon in days) from the nightly counts
    /progress/ draws (tools/data/progress.json via tools/progress.py): to annotate = filed
    less hinted; inflow = filed's 7-day pace; horizon = the page's hinted ETA, (known less
    hinted) over hinted's 7-day pace, capped at MAX_HORIZON_DAYS. (0, 0, 0) with no history."""
    import progress
    days = progress.load() if days is None else days
    if not days:
        return 0, 0.0, 0
    known, _, filed, _, hinted = progress.nested_totals(days[max(days)])
    per_hint = progress.rate(progress.funnel_series(days, 4), PACE_DAYS) or 0
    inflow = max(progress.rate(progress.funnel_series(days, 2), PACE_DAYS) or 0, 0.0)
    horizon = (known - hinted) / per_hint if per_hint > 0 else MAX_HORIZON_DAYS
    return max(filed - hinted, 0), inflow, min(horizon, MAX_HORIZON_DAYS)


def clues_left(mean_clues, days=None):
    """Clues still to annotate: (filed less hinted + filing inflow over the horizon) x mean
    clues/puzzle."""
    back, inflow, horizon = backlog_counts(days)
    return (back + inflow * horizon) * mean_clues


def work_order(reason, facts, rows, commit):
    last = rows[-ROLL:]
    lines = [f"Annotate cost hill-climb: {reason}. Now ${facts['cur']:.3f}/clue "
             f"(best since the last code commit ${facts['best']:.3f}). Latest ledger rows (end, sessions, $/clue, turns/clue):"]
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
                 "possible; goal is the payback above, not a fixed $/clue.")
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
