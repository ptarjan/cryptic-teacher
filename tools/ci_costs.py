#!/usr/bin/env python3
"""Per-script seconds from a tests.yml run's log, in the shape of ci_shards.js's COST.

    gh run view <run-id> --repo <owner>/<repo> --log > /tmp/run.log
    python3 tools/ci_costs.py /tmp/run.log            # the COST entries, slowest first
    python3 tools/ci_costs.py /tmp/run.log --top 10   # a table of the slowest, for a report

A serial script's seconds are the span of its log group in "Run this shard of
the test scripts": the workflow opens a `::group::<interpreter> <item>` before
each script and closes it right after, so the span is the script alone (the
dirty-tree check that follows is ITEM_OVERHEAD in the splitter). The PARALLEL
items (smoke slices) run in the background and their logs are printed after
the serial scripts, so a group's span there is only the wait for it; they are
reported by what the shard took as a whole instead (see --shards).

A run that has red shards still gives true spans for the scripts that ran to
the end; a script that failed early is shorter than its green self, so measure
from a green run when there is one.
"""
import argparse
import re
import sys
from datetime import datetime

STEP = "Run this shard of the test scripts"
LINE = re.compile(r"﻿?(\d{4}-\d\d-\d\dT[\d:.]+)Z (.*)")
GROUP = re.compile(r"##\[group\](python3|bash|node) (.*)")
MIN_SECONDS = 5  # shorter ones are DEFAULT_COST's business


def stamp(text):
    return datetime.fromisoformat(text[:26])


def read(path):
    """({item: seconds} of the serial scripts, {job: seconds of its run step})."""
    open_group, scripts, steps = {}, {}, {}
    with open(path, errors="replace") as f:
        for raw in f:
            parts = raw.rstrip("\n").split("\t", 2)
            if len(parts) < 3 or not parts[0].startswith("tests ") or parts[1] != STEP:
                continue
            m = LINE.match(parts[2])
            if not m:
                continue
            job, (at, text) = parts[0], (stamp(m.group(1)), m.group(2))
            first, _ = steps.get(job, (at, at))
            steps[job] = (first, at)
            g = GROUP.match(text)
            if g:
                open_group[job] = (g.group(2), at)
            elif text.startswith("##[endgroup]") and job in open_group:
                item, began = open_group.pop(job)
                if "smoke_test" not in item:
                    scripts[item] = (at - began).total_seconds()
    return scripts, {job: (b - a).total_seconds() for job, (a, b) in steps.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("log")
    ap.add_argument("--top", type=int, help="print a table of the N slowest scripts instead")
    ap.add_argument("--shards", action="store_true", help="print each shard's run step seconds")
    args = ap.parse_args()
    scripts, steps = read(args.log)
    if not scripts:
        sys.exit(f"ci_costs: no script groups in {args.log}: pass `gh run view <id> --log` output")
    ranked = sorted(scripts.items(), key=lambda kv: (-kv[1], kv[0]))
    if args.shards:
        for job, secs in sorted(steps.items()):
            print(f"{job}: {secs:.0f}s")
    elif args.top:
        for item, secs in ranked[: args.top]:
            print(f"{secs:7.1f}s  {item}")
    else:
        for item, secs in ranked:
            if secs >= MIN_SECONDS:
                print(f'  "{item}": {round(secs)},')


if __name__ == "__main__":
    main()
