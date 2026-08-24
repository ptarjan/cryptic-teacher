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
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kv  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KEY = re.compile(r"^e:(\d{4}-\d{2}-\d{2}):([a-z0-9-]+):")


def events():
    """The event names, read out of the file both other ends share. A second
    list here would drift, and a name this tool has never heard of is a column
    that silently goes missing rather than an error."""
    src = (ROOT / "sync" / "events.js").read_text(encoding="utf-8")
    body = src[src.index("Object.freeze(["):]
    return re.findall(r'"([^"]+)"', body[:body.index("])")])


def bar(n, top, width=24):
    return "#" * (round(width * n / top) if top else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, help="only the last N days")
    ap.add_argument("--file", help="a saved key listing instead of calling wrangler")
    args = ap.parse_args()

    keys = json.load(open(args.file)) if args.file else kv.list_keys()
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

    # Names in the order sync/events.js writes them, then anything KV holds that
    # the list has never heard of. Keys live 90 days, so a name retired today is
    # real traffic for a quarter after it stops being sent, and dropping its
    # column would report that stretch as nobody having done it.
    shown = [n for n in names if any(by_day[d][n] for d in days)]
    shown += sorted({n for d in days for n in by_day[d]} - set(names))
    width = {n: max(8, len(n) + 2) for n in shown}
    print("events per day")
    print("  " + "day".ljust(12) + "".join(n.rjust(width[n]) for n in shown))
    for d in days:
        print("  " + d.ljust(12)
              + "".join(str(by_day[d][n] or "").rjust(width[n]) for n in shown))

    total = Counter()
    for d in days:
        total.update(by_day[d])
    top = max(total.values())
    pad = max(10, max(len(n) for n in shown))
    print("\ntotals")
    for n in shown:
        print(f"  {n:<{pad}} {total[n]:>6}  {bar(total[n], top)}")

    # Openings count sessions, not solvers, so on their own they cannot tell one
    # regular from a crowd. These do, as far as anything without an identifier
    # can: one a day from each browser, bucketed by how many days it has come.
    # A browser is not a person — a second device reads as another new arrival —
    # so this is a floor on returning and a ceiling on new.
    visit = {n: total[n] for n in names if n.startswith("visit-")}
    seen = sum(visit.values())
    if seen:
        # A bucket nobody could have reached yet is not a measurement. Two days
        # after the beacons went up, "5th day or more: 0.0%" is arithmetic about
        # the calendar, not about the audience, and it reads as "nobody comes
        # back" — so a bucket that needs more history than the window holds says
        # so instead of printing a zero.
        span = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days + 1
        print(f"\nof {seen} browser-days, over {span} day{'s' if span != 1 else ''} of data")
        for label, n, needs in [("first day here", visit.get("visit-new", 0), 1),
                                ("2nd to 4th day", visit.get("visit-return", 0), 2),
                                ("5th day or more", visit.get("visit-regular", 0), 5)]:
            if span < needs and not n:
                print(f"  {label:<22}     -   needs {needs} days of data")
            else:
                print(f"  {label:<22} {100 * n / seen:>5.1f}%   {n}")

    # The actual question, and the reason the events are the ones they are: of
    # the people who opened a puzzle, how many got any distance into it. Shares
    # of OPENS throughout rather than of the previous step, because the steps are
    # not a strict sequence — plenty of solvers take a hint without ever pressing
    # check — and a chain of conditional rates would read as one when it is not.
    opens = total["open"]
    # Each hint name goes at most once a session, so a session that took the
    # definition and then the walkthrough is counted in two of them and the sum
    # is not a number of people. The largest single rung is the floor on "took a
    # hint at all", and the floor is what belongs in a funnel of openings; the
    # totals above are where WHICH rung they reached for is read.
    hints = max((total[n] for n in names if n.startswith("hint-")), default=0)
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
