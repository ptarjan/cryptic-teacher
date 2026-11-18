#!/usr/bin/env python3
"""Readout of the rush A/B: finished runs grouped by arm (model/effort).

    python3 tools/ab_report.py [--since 2026-11-17T00:00:00-07:00] [--json]

Arms come from $RUNS/<id>.model and .effort (tools/prereset_backfill.sh run_claude;
a run with no .effort file is the paced baseline, opus/medium). Each run is joined
to its CLI transcript (tools/annotate_audit.py) by start time: the transcript that
starts first within JOIN_S after the .model file was written, each used once. From
the transcript: cost, wall time, turns, clues written, first-check pass rate.

Missing, by design (the logs do not hold them per run): withheld clues per puzzle,
no-change rate, hints per clue, grading against a reference. The report says so.
"""
import argparse
import collections
import datetime
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

JOIN_S = 300
MISSING = ["withheld clues per puzzle", "no-change rate", "hints per clue", "reference grading"]


def arm_of(model, effort):
    """No effort on record: opus is the paced baseline (medium); anything else is unknown."""
    return f"{model or '?'}/{effort or ('medium' if model == 'opus' else '?')}"


def read_runs(runs_dir, since=None, high_since=None):
    """[(id, arm, written_at)] from the run records. A fable run with no .effort file, written
    after high_since (master 8f706e507e4, which made rush runs high), is counted high."""
    out = []
    for m in pathlib.Path(runs_dir).glob("*.model"):
        t = datetime.datetime.fromtimestamp(m.stat().st_mtime, datetime.UTC)
        if since and t < since:
            continue
        e = m.with_suffix(".effort")
        effort = e.read_text().strip() if e.exists() else ""
        if not effort and high_since and t >= high_since and m.read_text().strip() == "fable":
            effort = "high"
        out.append((m.stem, arm_of(m.read_text().strip(), effort), t))
    return sorted(out, key=lambda r: r[2])


def join(runs, sessions, join_s=JOIN_S):
    """[(arm, session)]: each run takes the earliest unused session starting 0..join_s after it."""
    used, out = set(), []
    sess = sorted(sessions, key=lambda s: s["start"])
    for _, arm, t in runs:
        for i, s in enumerate(sess):
            d = (s["start"] - t).total_seconds()
            if i not in used and -5 <= d <= join_s:
                used.add(i)
                out.append((arm, s))
                break
    return out


def summarise(pairs, n_runs):
    """arm -> stats; n_runs is how many runs each arm had on record, joined or not."""
    by = collections.defaultdict(list)
    for arm, s in pairs:
        by[arm].append(s)
    rows = {}
    for arm in sorted(set(by) | set(n_runs)):
        ss = by.get(arm, [])
        costs = [s["cost"] for s in ss if s["cost"] is not None]
        checked = [s for s in ss if s["first_units"]]
        units = sum(s["first_units"] for s in checked)
        failed = sum(s["first_failed"] for s in checked)
        clues = sum(s["clues"] or 0 for s in ss)
        rows[arm] = {
            "runs": n_runs.get(arm, 0), "with_transcript": len(ss),
            "cost_per_puzzle": sum(costs) / len(costs) if costs else None,
            "cost_per_clue": sum(costs) / clues if costs and clues else None,
            "turns_per_run": sum(s["turns"] for s in ss) / len(ss) if ss else None,
            "wall_min": sum(s["wall_min"] for s in ss) / len(ss) if ss else None,
            "first_check_pass": (units - failed) / units if units else None,
            "first_units": units, "clues": clues,
        }
    return rows


def fmt(x, spec):
    return "-" if x is None else format(x, spec)


def table(rows):
    head = ["arm", "runs", "tx", "$/puzzle", "$/clue", "turns", "wall min", "1st-check pass", "units"]
    lines = [head]
    for arm, r in rows.items():
        lines.append([arm, str(r["runs"]), str(r["with_transcript"]), fmt(r["cost_per_puzzle"], ".2f"),
                      fmt(r["cost_per_clue"], ".3f"), fmt(r["turns_per_run"], ".0f"),
                      fmt(r["wall_min"], ".1f"),
                      fmt(None if r["first_check_pass"] is None else 100 * r["first_check_pass"], ".0f") + ("%" if r["first_check_pass"] is not None else ""),
                      str(r["first_units"])])
    w = [max(len(row[i]) for row in lines) for i in range(len(head))]
    text = "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(row)) for row in lines)
    return text + "\nmissing (not logged per run): " + ", ".join(MISSING)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", help="ISO time; default: all records")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--high-since", help="ISO time: effortless fable runs after it count as high")
    args = ap.parse_args(argv)
    high_since = datetime.datetime.fromisoformat(args.high_since) if args.high_since else None
    since = datetime.datetime.fromisoformat(args.since) if args.since else None
    if since and since.tzinfo is None:
        since = since.replace(tzinfo=datetime.UTC)
    import annotate_audit as audit
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    runs = read_runs(pathlib.Path(common).parent / ".ct-runs" / "prereset_backfill", since, high_since)
    with audit._exclusive():
        templates = audit.load_templates(audit.validator_source())
        floor = (since or datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=3))
        sessions = list(audit.sessions(floor, templates))
        audit.save_session_cache()
    n_runs = collections.Counter(arm for _, arm, _ in runs)
    rows = summarise(join(runs, sessions), n_runs)
    print(json.dumps(rows, indent=1) if args.json else table(rows))


if __name__ == "__main__":
    main()
