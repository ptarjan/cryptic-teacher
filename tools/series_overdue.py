#!/usr/bin/env python3
"""Overdue-series alarm: wake the room when a paper silently stops arriving.

    python3 tools/series_overdue.py              # check, update the state, wake on a new gap
    python3 tools/series_overdue.py --dry-run    # print what it would do, touch nothing
    python3 tools/series_overdue.py --index FILE # read a local index.json instead of the live one

Pure code, no model call. For each series in the puzzle index:

  * Only series with a puzzle in the last 90 days are judged (long-dead ones are ignored), and
    any series named in tools/series_overdue_ignore.txt (one per line, # comments).
  * The expected weekdays are learned from the past year: a weekday counts when it holds at
    least 60% of the busiest weekday's puzzles AND occurred in at least WEEKLY_MIN of the weeks.
    Series too sparse for that (monthly, fortnightly) are judged by their usual interval
    instead: overdue once the days since the last puzzle exceed 1.5x the median gap + 3.
  * An expected day in the last WINDOW days with no puzzle is a gap once it is older than the
    series' grace. The grace is the 90th percentile of the arrival lags this script itself has
    observed (days between a puzzle's date and the first run that saw it; prize puzzles that
    arrive only with their solutions show up as a long lag), never below DEFAULT_GRACE.
  * A series whose whole window is missing is one gap, keyed "series@last-seen-date"; a series
    with scattered holes gets one key per missing date ("series:date").

The room is woken (wake.sh -q) only when a key appears that the state file has not
announced. Keys that clear are dropped, so a series that recovers and stops again wakes
again. A quiet day writes the state and says nothing.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta

ROOM = "cryptic-crosswords"
INDEX_URL = "https://cryptic.paultarjan.com/puzzles/index.json"
STATE = os.path.expanduser("~/.cache/cryptic-series-overdue.json")
IGNORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "series_overdue_ignore.txt")
WINDOW = 14
YEAR = 365
DEAD_AFTER = 90
SHARE = 0.6
WEEKLY_MIN = 20  # a weekday must occur in this many of the year's ~52 weeks
DEFAULT_GRACE = 2
MAX_GRACE = 14
LAG_KEEP = 60  # observed lags kept per series


def load_index(src):
    if src:
        with open(src) as f:
            return json.load(f)["puzzles"]
    req = urllib.request.Request(INDEX_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["puzzles"]


def load_ignore(path=IGNORE):
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return set()
    return {ln.split("#")[0].strip() for ln in lines if ln.split("#")[0].strip()}


def by_series(puzzles):
    out = {}
    for p in puzzles:
        try:
            d = date.fromisoformat(p["date"])
        except (KeyError, ValueError, TypeError):
            continue
        out.setdefault(p["series"], set()).add(d)
    return out


def expected_weekdays(dates, today):
    """Weekdays (0=Mon) a series reliably publishes on, from the past year; empty if too sparse."""
    year = [d for d in dates if today - timedelta(YEAR) <= d <= today]
    counts = Counter(d.weekday() for d in year)
    if not counts:
        return set()
    top = max(counts.values())
    return {w for w, c in counts.items() if c >= SHARE * top and c >= WEEKLY_MIN}


def grace_for(lags):
    if not lags:
        return DEFAULT_GRACE
    s = sorted(lags)
    p90 = s[min(len(s) - 1, int(0.9 * len(s)))]
    return max(DEFAULT_GRACE, min(MAX_GRACE, p90))


def find_gaps(dates, today, grace):
    """Gap keys for one series, each mapped to a human description. Empty when all is well."""
    last = max(d for d in dates if d <= today) if any(d <= today for d in dates) else None
    if last is None or (today - last).days > DEAD_AFTER:
        return {}
    weekdays = expected_weekdays(dates, today)
    gaps = {}
    if weekdays:
        missing = []
        for back in range(grace, WINDOW + 1):
            d = today - timedelta(back)
            if d.weekday() in weekdays and d not in dates:
                missing.append(d)
        missing.sort()
        window_start = today - timedelta(WINDOW)
        if missing and last < window_start + timedelta(1):
            shown = _fmt(missing[:3]) + (f" and {len(missing) - 3} more" if len(missing) > 3 else "")
            return {f"@{last}": f"nothing since {last}; missing {shown}"}
        for d in missing:
            gaps[f":{d}"] = f"missing {d} ({d.strftime('%a')})"
    else:
        past = sorted(d for d in dates if today - timedelta(YEAR) <= d <= last)
        steps = [(b - a).days for a, b in zip(past, past[1:])]
        if len(steps) >= 4:
            usual = statistics.median(steps)
            idle = (today - last).days
            if idle > 1.5 * usual + 3:
                gaps[f"@{last}"] = f"nothing since {last} ({idle}d; usually every {usual:g}d)"
    return gaps


def _fmt(days):
    return ", ".join(f"{d} {d.strftime('%a')}" for d in days)


def observe(state, series_dates, today):
    """Record arrival lags: dates first seen by this run. The first run only seeds."""
    seen = state.setdefault("seen", {})
    lags = state.setdefault("lags", {})
    for s, dates in series_dates.items():
        recent = {d.isoformat() for d in dates if today - timedelta(30) <= d <= today}
        if s in seen:
            for iso in recent - set(seen[s]):
                lags.setdefault(s, []).append((today - date.fromisoformat(iso)).days)
            lags[s] = lags.get(s, [])[-LAG_KEEP:]
        seen[s] = sorted(recent)


def check(series_dates, state, today, ignore):
    observe(state, series_dates, today)
    found = {}
    for s, dates in sorted(series_dates.items()):
        if s in ignore:
            continue
        for k, text in find_gaps(dates, today, grace_for(state["lags"].get(s))).items():
            found[s + k] = f"{s}: {text}"
    return found


def wake(text):
    wake_sh = os.environ.get("WAKE_SH") or __import__("local_config").path("household_dir") + "/tools/wake.sh"
    return subprocess.run([wake_sh, "-q", "-c", ROOM, text], check=False, timeout=120).returncode


def digest(new, found):
    lines = [f"Overdue puzzle series ({len(new)} new gap{'s' * (len(new) != 1)}); a paper may have silently stopped. "
             "Find out why (fetcher broke, site moved, series ended) and fix or add it to "
             "tools/series_overdue_ignore.txt if it is gone for good:"]
    lines += [f"- {found[k]}" for k in sorted(new)]
    rest = sorted(set(found) - set(new))
    if rest:
        lines.append(f"Already announced and still open: {', '.join(k.split(':')[0].split('@')[0] for k in rest)}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--index")
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--today")
    args = ap.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else datetime.now().date()
    try:
        state = json.load(open(args.state))
    except (OSError, ValueError):
        state = {}
    series_dates = by_series(load_index(args.index))
    found = check(series_dates, state, today, load_ignore())
    new = [k for k in found if k not in state.get("announced", [])]
    for k in sorted(found):
        print(("NEW  " if k in new else "open ") + found[k])
    print(f"series overdue: {len(found)} open, {len(new)} new")
    if args.dry_run:
        return 0
    rc = wake(digest(new, found)) if new else 0
    if rc:  # a failed wake leaves the new keys unannounced, so the next run tries again
        print(f"series overdue: wake.sh exited {rc}", file=sys.stderr)
    state["announced"] = sorted(k for k in found if not rc or k not in new)
    os.makedirs(os.path.dirname(args.state), exist_ok=True)
    with open(args.state + ".tmp", "w") as f:
        json.dump(state, f)
    os.replace(args.state + ".tmp", args.state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
