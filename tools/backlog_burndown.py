#!/usr/bin/env python3
"""Annotation backlog over time, reconstructed from git history.

    python3 tools/backlog_burndown.py            # weekly buckets, ASCII
    python3 tools/backlog_burndown.py --days 60  # daily buckets over a window
    python3 tools/backlog_burndown.py --svg out.svg

puzzles/index.json carries an `annotated` flag per puzzle, but it is only
rewritten by the republish step at the END of a backfill run, so a run that is
still going — or one that was killed — leaves it reading high by however many
puzzles have been annotated since. History does not have that problem: a puzzle
arrives when its file is added and leaves the backlog on the first "Annotate"
commit that touches it, and both of those are facts in the log.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

BAR = "█"


def events(live, flagged):
    """(arrived, annotated) epoch seconds per puzzle id, from the git log.

    `live` is the set of ids that exist today. History is walked oldest-first
    with rename detection on, because the puzzles were renumbered once
    (`puzzles/30066.js` -> `puzzles/cryptic-30066.js`); without following the
    rename each of those counts as one puzzle that arrived and one that
    vanished, which invents a backlog that was never there.
    """
    out = subprocess.run(
        ["git", "log", "--reverse", "--date-order", "--name-status", "-M",
         "--pretty=format:\x01%at\x02%s", "--", "puzzles/"],
        capture_output=True, text=True, check=True).stdout
    arrived, done, touched = {}, {}, {}
    when = subject = None

    def pid_of(path):
        name = path[len("puzzles/"):] if path.startswith("puzzles/") else ""
        return name[:-3] if name.endswith(".js") else None

    for line in out.splitlines():
        if line.startswith("\x01"):
            when, subject = line[1:].split("\x02", 1)
            when = int(when)
            continue
        if not line or when is None:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            old, new = pid_of(parts[1]), pid_of(parts[2])
            if old and new and old != new:
                for book in (arrived, done):
                    if old in book:
                        book.setdefault(new, book.pop(old))
            pid = new
        else:
            pid = pid_of(parts[-1])
        if pid is None:
            continue
        touched[pid] = when
        if status.startswith("A"):
            arrived.setdefault(pid, when)
        # A puzzle leaves the backlog on the first commit that annotates it.
        # Keyed on the touched PATH, not on ids parsed out of the subject:
        # "Annotate 30066 (Tramp) and 30067 (Imogen)" names two puzzles one way
        # and "Annotate everyman-4150" names one another way.
        if subject.startswith("Annotate") and pid not in done:
            done[pid] = when
            arrived.setdefault(pid, when)

    # Not every annotation arrived in a commit called "Annotate" — some puzzles
    # were fetched with their annotations already on them. index.json's flag is
    # the authority on WHETHER a puzzle is annotated; the log only supplies WHEN,
    # so for those, date it to the last commit that touched the file.
    for pid in flagged - set(done):
        if pid in touched:
            done[pid] = touched[pid]

    # Files that were deleted, and scratch that never shipped, are not backlog.
    arrived = {k: v for k, v in arrived.items() if k in live}
    done = {k: v for k, v in done.items() if k in live}
    return arrived, done


def series_of(pid):
    return pid.rsplit("-", 1)[0] if "-" in pid else "cryptic"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, help="daily buckets over the last N days")
    ap.add_argument("--weeks", type=int, default=26)
    ap.add_argument("--width", type=int, default=52)
    ap.add_argument("--svg", metavar="PATH")
    args = ap.parse_args()

    idx = json.load(open("puzzles/index.json"))["puzzles"]
    live = {p["id"] for p in idx if p.get("hasSolutions")}
    flagged = {p["id"] for p in idx if p["annotated"]}
    arrived, done = events(live, flagged)
    if not arrived:
        sys.exit("no puzzle history found — is this a cryptic-teacher checkout?")

    now = datetime.now(timezone.utc)
    if args.days:
        step, count, fmt = timedelta(days=1), args.days, "%m-%d"
    else:
        step, count, fmt = timedelta(days=7), args.weeks, "%m-%d"
    marks = [now - step * i for i in range(count - 1, -1, -1)]

    rows = []
    for t in marks:
        cut = t.timestamp()
        have = sum(1 for v in arrived.values() if v <= cut)
        gone = sum(1 for v in done.values() if v <= cut)
        rows.append((t, have - gone, have, gone))

    peak = max(r[1] for r in rows) or 1
    print(f"annotation backlog — {'daily' if args.days else 'weekly'}, "
          f"{len(arrived)} puzzles ever, {len(done)} annotated")
    for t, back, have, gone in rows:
        bar = BAR * round(back / peak * args.width)
        print(f"  {t.strftime(fmt)}  {back:4d} {bar}")

    # The rate that matters is the recent one: the backfill runs in bursts
    # against a weekly reset, so a lifetime average describes nothing.
    # Both windows, because they disagree and the disagreement IS the story: a
    # month that took on a whole archive at once still reads as losing ground
    # while the last week of it is clearing that archive fast.
    print()
    for days in (28, 7):
        recent = [r for r in rows if (now - r[0]).days <= days]
        if len(recent) < 2:
            continue
        closed = recent[-1][3] - recent[0][3]
        added = recent[-1][2] - recent[0][2]
        span = max((recent[-1][0] - recent[0][0]).days, 1)
        net = recent[0][1] - recent[-1][1]
        line = f"last {span}d: {closed} annotated, {added} arrived, backlog {-net:+d}"
        if net > 0:
            line += (f" — at that pace the remaining {rows[-1][1]} clear in "
                     f"{rows[-1][1] * span / net:.0f} days")
        print(line)

    left = {}
    for pid, t in arrived.items():
        if pid not in done:
            left[series_of(pid)] = left.get(series_of(pid), 0) + 1
    if left:
        print("  outstanding: " + ", ".join(
            f"{k} {v}" for k, v in sorted(left.items(), key=lambda kv: -kv[1])))

    # index.json's `annotated` flags are only rewritten by the republish step at
    # the end of a run, so they lag whenever a run is mid-flight or was killed.
    # Say by how much rather than quietly disagreeing with the site.
    stale = set(done) - flagged
    if stale:
        print(f"  note: puzzles/index.json still calls {len(stale)} of these "
              f"un-annotated — it is rewritten only by a completed run")

    if args.svg:
        w, h, pad = 720, 240, 34
        pts = []
        for i, (_, back, _, _) in enumerate(rows):
            x = pad + i * (w - 2 * pad) / max(len(rows) - 1, 1)
            y = h - pad - back / peak * (h - 2 * pad)
            pts.append(f"{x:.1f},{y:.1f}")
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<rect width="{w}" height="{h}" fill="#fbfbf9"/>
<polyline fill="none" stroke="#1b6ca8" stroke-width="2" points="{' '.join(pts)}"/>
<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="#999"/>
<text x="{pad}" y="{pad - 12}" font-family="system-ui" font-size="13" fill="#333">annotation backlog ({peak} peak, {rows[-1][1]} now)</text>
<text x="{pad}" y="{h - 10}" font-family="system-ui" font-size="11" fill="#666">{rows[0][0].strftime('%Y-%m-%d')}</text>
<text x="{w - pad}" y="{h - 10}" text-anchor="end" font-family="system-ui" font-size="11" fill="#666">{rows[-1][0].strftime('%Y-%m-%d')}</text>
</svg>
"""
        with open(args.svg, "w") as f:
            f.write(svg)
        print(f"\nwrote {args.svg}")


if __name__ == "__main__":
    main()
