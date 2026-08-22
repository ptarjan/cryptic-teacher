#!/usr/bin/env python3
"""Do visitors actually solve anything?

Cloudflare's RUM sees the arrival and nothing after it, because solving happens
entirely in localStorage — so a visitor who read one clue and left and one who
filled the whole grid look identical from outside. app.js reports a handful of
milestones instead (sync/events.js), and this counts them.

The counting is a key listing. sync/worker.js stores each event as a KEY NAME
with an empty value — `e:<date>:<event>:<random>` — so a count is a prefix list
and no value is ever read. That is also the whole of what is stored: there is no
address, no cookie, no id and no clock finer than the day anywhere in it, so
this report can say how many people took a hint and can never say which ones.

    python3 tools/usage_report.py              # everything KV still holds
    python3 tools/usage_report.py --days 14
    python3 tools/usage_report.py --file keys.json

Reads only. Nothing here writes to the site or to KV.
"""
import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMESPACE = "85f9de552ea64b229c113df624fb6ca0"
KEY = re.compile(r"^e:(\d{4}-\d{2}-\d{2}):([a-z0-9]+):")


def events():
    """The event names, read out of the file both other ends share. A second
    list here would drift, and a name this tool has never heard of is a column
    that silently goes missing rather than an error."""
    src = (ROOT / "sync" / "events.js").read_text(encoding="utf-8")
    body = src[src.index("Object.freeze(["):]
    return re.findall(r'"([^"]+)"', body[:body.index("])")])


def list_keys():
    """Key names from KV. wrangler prints a banner before the JSON, so the
    output is sliced from the first bracket rather than parsed whole."""
    out = subprocess.run(
        ["npx", "wrangler", "kv", "key", "list", "--namespace-id", NAMESPACE, "--remote"],
        cwd=ROOT / "sync", capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr.strip() or "wrangler failed", file=sys.stderr)
        raise SystemExit(1)
    at = out.stdout.find("[")
    if at < 0:
        print(f"no JSON in wrangler's output: {out.stdout.strip()[:200]}", file=sys.stderr)
        raise SystemExit(1)
    return json.loads(out.stdout[at:])


def bar(n, top, width=24):
    return "#" * (round(width * n / top) if top else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, help="only the last N days")
    ap.add_argument("--file", help="a saved key listing instead of calling wrangler")
    args = ap.parse_args()

    keys = json.load(open(args.file)) if args.file else list_keys()
    names = events()

    by_day = defaultdict(Counter)
    for k in keys:
        m = KEY.match(k["name"] if isinstance(k, dict) else str(k))
        if m:
            by_day[m.group(1)][m.group(2)] += 1
    days = sorted(by_day)
    if args.days:
        days = days[-args.days:]
    if not days:
        # An empty report and a report of emptiness look identical, and only one
        # of them means the beacons are working.
        print("no e: keys in KV yet — either nobody has opened a puzzle since the "
              "Worker was deployed, or the beacons are not arriving", file=sys.stderr)
        return 1

    shown = [n for n in names if any(by_day[d][n] for d in days)]
    print("events per day")
    print("  " + "day".ljust(12) + "".join(n.rjust(8) for n in shown))
    for d in days:
        print("  " + d.ljust(12) + "".join(str(by_day[d][n] or "").rjust(8) for n in shown))

    total = Counter()
    for d in days:
        total.update(by_day[d])
    top = max(total.values())
    print("\ntotals")
    for n in names:
        if total[n]:
            print(f"  {n:<10} {total[n]:>6}  {bar(total[n], top)}")

    # The actual question, and the reason the events are the ones they are: of
    # the people who opened a puzzle, how many got any distance into it. Shares
    # of OPENS throughout rather than of the previous step, because the steps are
    # not a strict sequence — plenty of solvers take a hint without ever pressing
    # check — and a chain of conditional rates would read as one when it is not.
    opens = total["open"]
    # hint1 is the first rung of any clue's ladder and goes once a session, so it
    # is exactly "took a hint at all". The deeper rungs are how far they went.
    hints = total["hint1"]
    print(f"\nof {opens} puzzle openings")
    if not opens:
        print("  (nothing opened in this window)")
        return 0
    for label, n in [("typed a letter", total["letter"]),
                     ("took a hint", hints),
                     ("used a check", total["check"]),
                     ("solved an entry", total["entry"]),
                     ("filled half the grid", total["half"]),
                     ("finished the puzzle", total["done"])]:
        print(f"  {label:<22} {100 * n / opens:>5.1f}%   {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
