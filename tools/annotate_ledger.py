#!/usr/bin/env python3
"""Every burn checkpoint measures its own annotate cost; the room is woken when it drifts.

    python3 tools/annotate_ledger.py record            # audit since the last row, append one
    python3 tools/annotate_ledger.py record --since 2026-10-20T10:00:00+00:00 --dry-run
    python3 tools/annotate_ledger.py decide [--dry-run]  # the wake rule over the ledger
    python3 tools/annotate_ledger.py --no-lever "<cause key or label>"  # investigated, no lever

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

11-19: the room was woken hourly about a cause it had settled as a genuine model error
(investigated 5 times). Now: a no-lever record (tools/data/annotate_no_lever.json, tracked)
holds until the cause's $/clue passes NO_LEVER_RISE x the recorded or NO_LEVER_DAYS pass,
whatever code commits land; each re-mark counts an investigation, which adds $6 to that
cause's assumed fix cost; the payback horizon is the clues the burn does in PAYBACK_DAYS; and
only a wake (real, not -q) is sent when should_wake fires. Every other line stays in the log.

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
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import annotate_audit as audit
import gitlog_cache

REPO = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(os.environ.get("ANNOTATE_CACHE", pathlib.Path.home() / ".cache"))
LEDGER = pathlib.Path(os.environ.get("ANNOTATE_LEDGER", CACHE / "annotate_cost_ledger.jsonl"))
STATE = pathlib.Path(os.environ.get("ANNOTATE_WAKE_STATE", CACHE / "annotate_cost_wake.json"))
# The no-lever book is tracked repo data (11-19): the room's settled causes survive a cache wipe.
NO_LEVER = pathlib.Path(os.environ.get("ANNOTATE_NO_LEVER", REPO / "tools" / "data" / "annotate_no_lever.json"))
OLD_NO_LEVER = CACHE / "annotate_no_lever.json"   # where the book lived until 11-19: migrated once
NO_LEVER_RISE = 1.5   # a no-lever cause wakes again when its $/clue passes this x the recorded
NO_LEVER_DAYS = 14    # ...or when this many days have passed since the record's date
FIX_COST_PER_INVESTIGATION = 6.0   # each earlier look at a cause adds this to its assumed fix cost
PAYBACK_DAYS = 30     # the saving counts the clues the burn does in this many days, no more
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
MIN_CAUSE_SESSIONS = 3  # the top cause must show in this many sessions over RATE_ROWS rows
                        # before its payback wakes the room: 11-20 one session's $0.21 was
                        # projected over 1.1M clues into a "$127 saving" wake
RATE_ROWS = 6         # recent rows averaged for the cause's $/h (never fewer than 3)
# What "annotate code" means for the best-level baseline.
CODE_PATHS = ["tools/annotate*", "tools/validate_annotations.py", "tools/validate_*.py", ":(exclude)tools/validate_scope.py", "tools/puzzle_worker.sh",
              "tools/clue_bag.py", "tools/annotate_prompt.md", "tools/annotate_bag_prompt.md",
              # the modules an annotate run's checks and apply step import: a fix there is
              # an annotate fix (wordplay.py holds the "does not give the answer" refusal)
              "tools/wordplay.py", "tools/apply_annotations.py", "tools/annotation.py",
              "tools/clue_types.py", "tools/corroborate.py", "tools/definitions.py",
              "tools/groups.py", "tools/find_answer_leaks.py", "tools/find_renarration.py",
              "tools/hidden_mechanical.py", "tools/tree_normalize.py", "tools/code_checks.py"]
# The ledger and its test match tools/annotate* but do not change what an annotate run costs:
# a commit to them must not reset the best level or lift a no-lever record.
LEDGER_FILES = [":(exclude)tools/annotate_ledger.py", ":(exclude)tests/test_annotate_ledger.py",
                ":(exclude)tools/annotate_audit.py"]


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def parse(t):
    return datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))


HINT = "hint"   # the row field `kind` of a hint-backfill row; annotation rows carry none (or "annotate")


def row_kind(r):
    return r.get("kind") or "annotate"


def read_ledger(path=None, kind="annotate"):
    """The ledger's rows of one kind (default: annotation, which every wake rule judges, so a
    hint-backfill row never lifts or dilutes the annotation $/clue); kind=None reads all."""
    return [r for r in read_all(path) if kind is None or row_kind(r) == kind]


def read_all(path=None):
    if path is None:
        return audit.read_jsonl_incremental(LEDGER)
    rows = []
    try:
        for line in path.read_text().splitlines():
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


def code_commit(repo=REPO, skip=()):
    """(sha, ISO committer time, subject) of the last commit touching annotate code,
    less the paths in `skip` (shape_queue.REARM_SKIP)."""
    # cached per HEAD: this walk re-read the tools history on every burn loop
    try:
        out = gitlog_cache.log(["-1", "--format=%h%x09%cI%x09%s", "--"] + CODE_PATHS + LEDGER_FILES
                               + [f":(exclude){x}" for x in skip], cwd=repo).strip()
    except (subprocess.CalledProcessError, OSError):
        out = ""
    parts = out.split("\t")
    return tuple(parts) if len(parts) == 3 else (None, None, None)


def master_sha(repo=REPO):
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True,
                          text=True, check=False).stdout.strip()


def make_row(res, sha, kind="annotate"):
    row = {"start": res["since"], "end": res["until"], "sha": sha, "sessions": res["sessions"],
            "puzzles": res["puzzles"], "clues": res["clues"], "cost": res["cost"],
            "cost_per_clue": res["cost_per_clue"], "turns_per_clue": res["turns_per_clue"],
            "first_fail": res["first_fail"],
            "top_causes": [{k: c[k] for k in ("key", "label", "sessions", "cost_after_check")}
                           for c in res["causes"][:3]]}
    if kind != "annotate":
        row["kind"] = kind    # annotation rows stay as they were: no field
        row["top_causes"] = []
    return row


def report(rows=None):
    """$ per clue by kind over `rows` (default the whole ledger): what the daily burn-log review
    reads. {kind: {rows, sessions, puzzles, clues, cost, cost_per_clue}}; hint is never in annotate's."""
    out = {}
    for r in rows if rows is not None else read_all():
        d = out.setdefault(row_kind(r), {"rows": 0, "sessions": 0, "puzzles": 0, "clues": 0, "cost": 0.0})
        d["rows"] += 1
        for k in ("sessions", "puzzles", "clues"):
            d[k] += r.get(k) or 0
        d["cost"] += r.get("cost") or 0
    for d in out.values():
        d["cost"] = round(d["cost"], 4)
        d["cost_per_clue"] = d["cost"] / d["clues"] if d["clues"] else None
    return out


def read_no_lever():
    """{cause key: {label, date, per_clue, commit, commit_time, count}} the room marked
    investigated. The first run without the repo file copies the old cache file's contents in."""
    if not NO_LEVER.exists() and OLD_NO_LEVER != NO_LEVER and OLD_NO_LEVER.exists():
        try:
            book = json.loads(OLD_NO_LEVER.read_text())
            NO_LEVER.parent.mkdir(parents=True, exist_ok=True)
            NO_LEVER.write_text(json.dumps(book, indent=1) + "\n")
        except (OSError, ValueError):
            pass
    try:
        return json.loads(NO_LEVER.read_text())
    except (OSError, ValueError):
        return {}


def muted(rec, per_clue, now=None):
    """True while a no-lever record holds: the cause's $/clue is under NO_LEVER_RISE x the
    recorded one and the record is under NO_LEVER_DAYS old. An annotate-code commit no longer
    lifts it (11-19: the same genuine model error was re-investigated five times)."""
    if not rec:
        return False
    if per_clue >= rec.get("per_clue", 0) * NO_LEVER_RISE:
        return False
    if rec.get("date"):
        now = now or now_utc()
        age = now.date() - datetime.date.fromisoformat(rec["date"])
        if age > datetime.timedelta(days=NO_LEVER_DAYS):
            return False
    return True


def investigated(rec):
    """'investigated N times, last <date>' for a cause the room has settled, else ''."""
    if not rec:
        return ""
    n = rec.get("count") or 1
    return f"investigated {n} time{'s' if n != 1 else ''}, last {rec.get('date') or '?'}"


def mark_no_lever(cause, rows, commit, now=None):
    """Record a cause as investigated with no lever; returns the stored record (None if the
    cause is in no row). cause matches a top cause's key or label."""
    now = now or now_utc()
    if commit[1]:
        rows = [r for r in rows if parse(r["end"]) >= parse(commit[1])]
    for r in reversed(rows):
        for c in r.get("top_causes") or []:
            if cause in (c.get("key"), c.get("label")):
                key = c["key"]
                per_clue, _ = cause_per_clue(rows, key)
                rec = {"label": c.get("label"), "date": now.date().isoformat(),
                       "per_clue": round(per_clue, 6), "commit": commit[0], "commit_time": commit[1]}
                book = read_no_lever()
                rec["count"] = (book.get(key, {}).get("count") or (1 if key in book else 0)) + 1
                book[key] = rec
                NO_LEVER.parent.mkdir(parents=True, exist_ok=True)
                NO_LEVER.write_text(json.dumps(book, indent=1) + "\n")
                return dict(rec, key=key)
    return None


def should_wake(rows, since_commit, state, now, no_lever=None):
    """(reason, facts) when the room should be woken, else (None, why not).

    rows: ledger rows, oldest first; since_commit: ISO time of the last annotate-code
    commit (None = all rows count); state: {woken, top} of the previous wake;
    no_lever: {cause key: record} of causes investigated with no lever (see muted)."""
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
    key = top_cause.get("key")
    rec = (no_lever or {}).get(key)
    left = min(clues_left(mean_clues), burn_clues_per_day(rows) * PAYBACK_DAYS)
    fix_cost = FIX_COST + FIX_COST_PER_INVESTIGATION * ((rec or {}).get("count") or (1 if rec else 0))
    saving = per_clue * left * SUCCESS_RATE
    rate = cause_rate(rows, top_cause.get("key"))
    facts = {"cur": cur, "best": best, "rate": rate, "saving": saving, "left": left,
             "per_clue": per_clue, "key": key, "fix_cost": fix_cost,
             "investigated": investigated(rec)}
    woken = state.get("woken")
    if woken and (now - parse(woken)).total_seconds() < COOLDOWN_H * 3600:
        return None, f"woken {woken}, inside the {COOLDOWN_H}h cooldown"
    pay = (f"top cause `{top_cause.get('key')}` (${per_clue:.4f}/clue after check, ${rate:.2f}/h): "
           f"est. saving ${saving:.0f} over the next ~{left:,.0f} clues vs ~${fix_cost:.0f} fix cost")
    seen = cause_sessions(rows, key)
    if saving > fix_cost and seen < MIN_CAUSE_SESSIONS:
        pay += f" - seen in only {seen} session(s), under {MIN_CAUSE_SESSIONS}: too thin to project"
    elif saving > fix_cost:
        if muted(rec, per_clue, now):
            return None, f"{pay} - marked no-lever ({investigated(rec)}), under {NO_LEVER_RISE}x and {NO_LEVER_DAYS} days"
        return pay, facts
    if best and cur > best * (1 + REGRESS):
        return (f"latest ${cur:.3f}/clue is {cur / best - 1:+.0%} over the best level "
                f"${best:.3f} since the last annotate-code commit; {pay}"), facts
    return None, f"${cur:.3f}/clue within 10% of best ${best:.3f}; {pay} - not worth a fix"


def burn_clues_per_day(rows):
    """Clues the burn does a day, from the recent rows' clues over their hours (0 with none)."""
    clues = hours = 0.0
    for r in rows[-RATE_ROWS:]:
        clues += r.get("clues") or 0
        hours += (parse(r["end"]) - parse(r["start"])).total_seconds() / 3600
    return clues / hours * 24 if hours > 0 else 0.0


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


def cause_sessions(rows, key):
    """Sessions that failed the first check on the cause, over the last RATE_ROWS rows."""
    return sum(c.get("sessions") or 0 for r in rows[-RATE_ROWS:]
               for c in r.get("top_causes") or [] if c.get("key") == key)


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
    horizon = min(horizon, MAX_HORIZON_DAYS)
    back = max(filed - hinted, 0)
    if horizon > 0:  # filing cannot outrun the corpus: backlog + inflow <= known less hinted
        inflow = min(inflow, max(known - hinted - back, 0) / horizon)
    return back, inflow, horizon


def clues_left(mean_clues, days=None):
    """Clues still to annotate: (filed less hinted + filing inflow over the horizon) x mean
    clues/puzzle."""
    back, inflow, horizon = backlog_counts(days)
    return (back + inflow * horizon) * mean_clues


def work_order(reason, facts, rows, commit):
    """The wake text: facts a human reads at a glance first (cost and trend, top cause with
    its payback, the next action), the agent's instructions in a separate trailing block."""
    last = rows[-ROLL:]
    cur, best = facts["cur"], facts["best"]
    first = last[0].get("cost_per_clue") if last else None
    trend = ""
    if first and len(last) > 1:
        trend = f", {cur / first - 1:+.0%} over the last {len(last)} runs"
    lines = [f"Annotate cost: ${cur:.3f}/clue now (best since the last code change ${best:.3f}{trend})."]
    top = (last[-1].get("top_causes") or [None])[0]
    saving = facts.get("saving")
    if top:
        pc = facts.get("per_clue")
        spend = f"${pc:.4f}/clue" if pc is not None else f"${top['cost_after_check']:.2f} total"
        lines.append(f"Top cause: {top['label']} - {top['sessions']} sessions, {spend} spent after the check"
                     + (f", ${facts['rate']:.2f}/h." if facts.get("rate") is not None else "."))
    if saving is not None:
        fix_cost = facts.get("fix_cost", FIX_COST)
        worth = saving > fix_cost
        lines.append(f"Payback: saves ~${saving:,.0f} over the next ~{facts['left']:,.0f} clues "
                     f"vs ~${fix_cost:.0f} to fix - {'worth fixing' if worth else 'not worth a fix'}.")
        if facts.get("investigated"):
            lines.append(f"This cause: {facts['investigated']}.")
    else:
        lines.append(f"Why: {reason}.")
    worth = saving is None or saving > facts.get("fix_cost", FIX_COST)
    lines.append("Next: find a fix already landed for this cause; if none, have one Sonnet worker fix it."
                 if worth else "Next: nothing to fix for this cause; check what changed in the last code commit.")
    lines.append("Recent runs (end, sessions, clues, $/clue, turns/clue):")
    for r in last:
        pc, tc = r.get("cost_per_clue"), r.get("turns_per_clue")
        lines.append(f"  {r['end'][:16]}  {r['sessions']} sess, {r.get('clues', 0)} clues, "
                     f"${pc or 0:.3f}, {tc or 0:.2f} turns")
    lines.append("Last code change: %s %s" % (commit[0] or "?", commit[2] or ""))
    lines.append("--- Instructions for the agent ---")
    tail = ("Ledger: ~/.cache/annotate_cost_ledger.jsonl; `python3 tools/annotate_audit.py --since "
            "<ISO> --json` re-audits a window.")
    if worth:
        tail += (" Check git log for a fix already landed for this "
                 "cause; if none, spawn ONE Sonnet worker in a sparse worktree to fix it, code-side if "
                 "possible, and have it also judge whether tools/annotate_prompt.md could steer the "
                 "model better on this cause (Paul 10-30); goal is the payback above, not a fixed $/clue.")
    lines.append(tail)
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
    reason, facts = should_wake(rows, commit[1], state, now, read_no_lever())
    if not reason:
        print(f"annotate ledger: no wake - {facts}")
        return 0
    since = [r for r in rows if not commit[1] or parse(r["end"]) >= parse(commit[1])]
    text = work_order(reason, facts, since, commit)
    if dry_run:
        print("annotate ledger: WOULD WAKE (dry run)\n" + text)
        return 0
    # A real wake, not -q: should_wake only fires on a regression or an unmuted cause worth
    # fixing, and a quiet wake rode onto the next message (11-19). Every other hourly line
    # stays in the burn log (stdout above, .prereset.debug.log) and never wakes the room.
    rc = subprocess.run([WAKE_SH, "-c", WAKE_ROOM, text], check=False).returncode
    if rc:
        print(f"annotate ledger: wake.sh exited {rc}; nothing recorded")
        return rc
    top = (since[-1].get("top_causes") or [{}])[0].get("key")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"woken": now.isoformat(timespec="seconds"), "top": top,
                                 "reason": reason, "commit": commit[1]}, indent=1) + "\n")
    print(f"annotate ledger: woke the room ({reason})")
    return 0


RECORD_EVERY_S = 600   # the burn calls `record` at every checkpoint; each call loads the 80 MB audit cache
RECORD_STAMP = audit._CACHE_DIR / "ledger-record.stamp"


def record(since=None, until=None, dry_run=False):
    """One audit lock hold for both windows: the session cache is read once, not twice."""
    now = until or now_utc()
    if since is None and until is None and not dry_run:
        try:
            if time.time() - RECORD_STAMP.stat().st_mtime < RECORD_EVERY_S:
                return None  # the window since the last row only grows: a later call covers it
        except OSError:
            pass
        try:
            RECORD_STAMP.parent.mkdir(parents=True, exist_ok=True)
            RECORD_STAMP.touch()
        except OSError:
            pass
    with audit._exclusive():
        return _record(now, since, until, dry_run)


def _record(now, since, until, dry_run):
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
    # The same window's hint-backfill sessions: one row of their own, so the review reports
    # their $/clue apart from annotation's (none when no backfill ran).
    hint = audit.window_audit(since, now, HINT)
    hint["until"] = now.isoformat()
    hint_row = make_row(hint, row["sha"], HINT) if hint["sessions"] else None
    if hint_row:
        print("annotate ledger hint row: " + json.dumps(hint_row))
    if not dry_run:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a") as fh:
            for r in (row, hint_row):
                if r:
                    fh.write(json.dumps(r) + "\n")
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", nargs="?", choices=["record", "decide", "report"])
    ap.add_argument("--no-lever", metavar="CAUSE",
                    help="mark a top cause (its key or label) investigated with no lever: the alert "
                    "stays quiet until its $/clue passes 1.5x the recorded or 14 days pass")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--dry-run", action="store_true",
                    help="record: print the row, append nothing; decide: print the wake, send nothing")
    args = ap.parse_args(argv)
    try:
        if args.no_lever:
            rec = mark_no_lever(args.no_lever, read_ledger(), code_commit())
            print(f"annotate ledger: no-lever recorded {rec}" if rec else
                  f"annotate ledger: no top cause matches {args.no_lever!r} since the last code commit")
            return 0 if rec else 1
        if not args.cmd:
            ap.error("a command (record, decide) or --no-lever is required")
        if args.cmd == "report":
            for kind, d in report().items():
                pc = d["cost_per_clue"]
                print(f"{kind}: {d['rows']} rows, {d['clues']} clues, ${d['cost']:.2f}, "
                      + (f"${pc:.4f}/clue" if pc is not None else "no clues"))
            return 0
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
