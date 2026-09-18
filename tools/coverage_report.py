#!/usr/bin/env python3
"""What we hold of every series, and which ones are not finished.

Run it:

    python3 tools/coverage_report.py            # the table
    python3 tools/coverage_report.py --quiet    # only the series with a problem

Every series is meant to be walked back to its source's floor and then kept
current nightly. Two different things stop that happening and neither one
announces itself: a fetcher that can only ever get "today" leaves its series one
puzzle deep forever, and a feed that quietly stops answering leaves its series
frozen at whatever day it broke on. Both look healthy from inside the nightly
run -- it fetched, nothing failed, there was simply nothing new -- so the only
way either is noticed is a person looking at the site and counting. This is that
count, run every night.

The flags, in the order they matter:

  STALE    the newest puzzle is older than three times the series' cadence, so
           the feed has stopped answering and nobody has been told.
  SHALLOW  the whole series spans less than SHALLOW_DAYS, which means it has
           never been backfilled -- the state tools/fetch_metro.py was in on
           2026-09-17, holding exactly one puzzle.
  HOLES    more than HOLES_PCT of the numbers between the oldest and newest we
           hold are missing, so a walk stopped part-way.
  STRAY    a puzzle whose number is nowhere near the rest of its series, which
           means it was filed under the wrong one.
  WEEKDAY  a puzzle dated on a day of the week its paper does not publish on,
           which means its date is wrong -- the puzzle is real, the date is
           not, and every date-ordered view of the site puts it in the wrong
           place.
  DATELESS a puzzle with no date at all. The site sorts by date, so these sink.

Exits 1 if any series carries a flag, so the nightly can alert on it.
"""

import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import series as series_meta  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "puzzles" / "index.json"

# A series younger than this has never been walked backwards. Three months is
# comfortably longer than any gap a live feed leaves and far shorter than any
# archive worth having, so nothing that is merely new trips it for long.
SHALLOW_DAYS = 90
HOLES_PCT = 5
# How many interquartile spreads outside the bulk of a series a number may
# sit before it stops looking like that series and starts looking like a
# misfile. Applied to the interquartile range rather than the median value,
# so it measures how tightly the numbers cluster, not how far a number sits
# from the middle -- a series backfilled all the way to its floor is one
# dense run from top to bottom, never "far" from its own median.
STRAY_FACTOR = 3
# A weekday carrying less than this share of a series' dates is not one of that
# paper's publication days, so a puzzle landing there has a wrong date rather
# than an unusual one. Expressed as a share and not a count because the question
# is whether the day is part of the pattern, and a paper that changed its
# publication day mid-life leaves a real minority weekday -- the Observer's 51
# Saturday Everymen (4%) and the Quiptic's 128 Sundays (9%) are both eras, not
# errors, and must stay silent. One puzzle in three hundred is not an era.
ODD_WEEKDAY_PCT = 1

# Puzzles that really were published on a day their series otherwise never
# uses. An entry belongs here only once the neighbouring numbers have been read
# and they corroborate the odd date rather than contradicting it -- a date that
# cannot be reconciled with its neighbours stays flagged, because the report is
# the to-do list for exactly that.
WEEKDAY_AS_PUBLISHED = {
    # The Quiptic launched on Tuesday 1999-11-23 and only settled onto Mondays
    # afterwards: No 2 is Monday 1999-11-29, the Monday after, not the Monday
    # before. There is no wrong date here, just a first edition.
    ("quiptic", 1): "the series' launch day, before it moved to Mondays",
}

# The lowest number the source will still serve. A floor belongs here only once
# a walk has ended in 404s at it -- guessing one hides exactly the backfill this
# report exists to find. Without it, a series that has been walked to its floor
# reads as 96% missing forever, because the hole count is measured from the
# oldest number held and most of the numbers below the floor were never
# digitised. Papers do also serve the odd puzzle from far below their floor;
# those are counted separately rather than treated as the start of the run.
ARCHIVE_FLOOR = {
    # 1999-06-23, a site-wide date wall on theguardian.com — corroborated by
    # the Guardian quick crossword walling at No. 9,093 the same day. Same
    # number as tools/fetch_puzzle.py's CRYPTIC_FLOOR.
    "cryptic": 21620,
    # 2003-07-27, confirmed by tools/fetch_puzzle.py's --extend walk 404ing at
    # 2,964 and below. Same number as that file's EVERYMAN_FLOOR.
    "everyman": 2965,
    # 2025-11-16 ("No 3106"), confirmed 2026-09-18: cdn-us.amuselabs.com
    # "puzzle not found"s every day from 2025-11-02 to 2025-11-14 and every
    # Saturday walked back to 2025-01-04. Three earlier dates (2025-11-01,
    # -08, -15) do carry real puzzle data but no publisher number in any
    # field, so they were never filed here either. Same number as
    # tools/fetch_globeandmail.py's GLOBEANDMAIL_FLOOR_DATE.
    "globeandmail": 3106,
}

# Days between issues at the source. Used only to decide whether a series has
# gone quiet, so a paper printing six days a week and one printing seven are
# both 1 -- the question is how long a silence is too long, not how many
# puzzles a week to expect.
CADENCE_DAYS = {
    "cryptic": 1,
    "quiptic": 7,
    "everyman": 7,
    "independent": 1,
    "indysunday": 7,
    "metro": 1,
    "cyclops": 14,
    "globeandmail": 1,
}


def as_date(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date()


def is_date_keyed(held):
    """True when a series' "number" is really its own date spelled YYYYMMDD
    (metro: number 20260918 on 2026-09-18), not a running puzzle count.

    Checked structurally -- every puzzle that carries a date must parse as
    YYYYMMDD and equal that same puzzle's date -- rather than by series name,
    because the failure mode this guards against is `numbers[-1] -
    numbers[0]` being fed a pair of dates and returning a difference that
    looks like a puzzle count but isn't. Naming metro here would fix today's
    series and leave the next date-keyed feed to trip the same bug.
    """
    checked = False
    for p in held:
        if not p.get("date"):
            continue
        try:
            parsed = datetime.strptime(str(p["number"]), "%Y%m%d").date()
        except ValueError:
            return False
        if parsed != as_date(p["date"]):
            return False
        checked = True
    return checked


def audit(puzzles, today):
    """One row per series, each with a (possibly empty) list of flags."""
    by_series = defaultdict(list)
    for p in puzzles:
        by_series[p["series"]].append(p)

    rows = []
    for name in sorted(by_series):
        held = by_series[name]
        all_numbers = sorted(p["number"] for p in held)
        dates = sorted(as_date(p["date"]) for p in held if p.get("date"))
        dateless = len(held) - len(dates)
        floor = ARCHIVE_FLOOR.get(name)
        cadence = CADENCE_DAYS.get(name)
        below = [n for n in all_numbers if floor and n < floor]
        numbers = [n for n in all_numbers if n not in set(below)]
        span = numbers[-1] - numbers[0] + 1
        missing = span - len(set(numbers))
        flags = []

        # A series with no dates at all can still be stale or full of holes; it
        # just cannot be measured on the time axis, so those two checks are
        # skipped rather than guessed at.
        if dates:
            newest, oldest = dates[-1], dates[0]
            quiet = (today - newest).days
            depth = (newest - oldest).days
            if cadence and quiet > cadence * 3:
                flags.append(f"STALE nothing since {newest} ({quiet}d)")
            if depth < SHALLOW_DAYS:
                flags.append(f"SHALLOW spans {depth}d, never backfilled")
        else:
            newest = oldest = None

        if dates and cadence and is_date_keyed(held):
            # numbers[0] and numbers[-1] are dates in disguise here, so their
            # difference (metro: 20260918 - 20250403 = 10,464) isn't a puzzle
            # count -- measure the axis this series actually has: publication
            # days, at its own cadence, between the oldest and newest held.
            expected = depth // cadence + 1
            missing = expected - len(dates)
            if expected > 1 and missing * 100 / expected > HOLES_PCT:
                flags.append(f"HOLES {missing} of {expected} publication days missing")
        elif span > 1 and missing * 100 / span > HOLES_PCT:
            flags.append(f"HOLES {missing} of {span} numbers missing")

        # The gap between what the source still serves and the oldest we have
        # walked back to. Nothing else here can see it: within what we hold the
        # series looks complete, and the only sign it is not finished is a floor
        # we have not reached yet.
        if floor and numbers[0] > floor:
            flags.append(f"REACH {numbers[0] - floor} below {numbers[0]} still unfetched "
                         f"(source floor {floor})")

        # Fenced off the interquartile range rather than the median value, so
        # this catches a number with nothing between it and the rest of the
        # series, without also catching the low end of a series that has been
        # backfilled all the way down to its floor -- those numbers are far
        # from the middle by value, but not sparse; they sit shoulder to
        # shoulder with their neighbours, which the spread of the bulk (not
        # its centre) is what tells apart. Skipped under four numbers, where
        # a quartile split cannot mean anything.
        if len(numbers) >= 4:
            q1, _, q3 = statistics.quantiles(numbers, n=4, method="inclusive")
            iqr = q3 - q1
            lo, hi = q1 - STRAY_FACTOR * iqr, q3 + STRAY_FACTOR * iqr
            strays = [n for n in numbers if n < lo or n > hi]
            if strays:
                flags.append(f"STRAY {len(strays)} numbered far off ({strays[0]}..{strays[-1]})")

        # Which days a paper publishes on is the most stable fact about a
        # series, so a date on a day the rest of the series never uses is a
        # broken date rather than a rare edition. Nothing else here can see it:
        # such a puzzle has a plausible number, sits in a dense run, and is
        # neither stale nor missing -- it is simply filed on the wrong day.
        # Derived from the series' own dates rather than a table of publication
        # schedules, so a paper that moves its crossword day needs no edit here.
        odd = defaultdict(list)
        for p in held:
            if p.get("date"):
                odd[as_date(p["date"]).strftime("%a")].append(p["number"])
        for day, nums in sorted(odd.items()):
            if len(nums) * 100 / len(dates) >= ODD_WEEKDAY_PCT:
                continue
            nums = [n for n in nums if (name, n) not in WEEKDAY_AS_PUBLISHED]
            if not nums:
                continue
            shown = ", ".join(str(n) for n in sorted(nums)[:6])
            more = "" if len(nums) <= 6 else f", +{len(nums) - 6} more"
            flags.append(f"WEEKDAY {len(nums)} dated {day}, which {name} "
                         f"does not publish on ({shown}{more})")

        if dateless:
            flags.append(f"DATELESS {dateless} with no date")

        rows.append({
            "series": name,
            "held": len(held),
            "below": below,
            "numbers": (numbers[0], numbers[-1]),
            "oldest": oldest,
            "newest": newest,
            "flags": flags,
        })
    return rows


def main(argv):
    quiet = "--quiet" in argv
    # Two audiences, one report. A dead feed is tonight's problem and worth
    # waking someone for; an unfinished backfill is a standing to-do that would
    # fire the same alert every night until the walk finishes, which is how an
    # alert stops being read. --stale-only is the half that is allowed to shout.
    stale_only = "--stale-only" in argv
    index = json.loads(INDEX.read_text())
    rows = audit(index["puzzles"], datetime.now(timezone.utc).date())
    if stale_only:
        for r in rows:
            r["flags"] = [f for f in r["flags"] if f.startswith("STALE")]

    shown = [r for r in rows if r["flags"]] if quiet or stale_only else rows
    for r in shown:
        # The publisher is what makes a row actionable: "metro" is a key, "Metro"
        # is where to go looking for an archive.
        pub = series_meta.SERIES.get(r["series"], {}).get("publisher", "?")
        print(f"{r['series']:<13} {r['held']:>5} held  "
              f"{r['numbers'][0]}-{r['numbers'][1]}  "
              f"{r['oldest'] or '?'} to {r['newest'] or '?'}  ({pub})")
        for f in r["flags"]:
            print(f"    {f}")
        if r["below"]:
            print(f"    note {len(r['below'])} below the known floor "
                  f"({r['below'][0]}..{r['below'][-1]}) — one-offs, not a gap")

    flagged = [r for r in rows if r["flags"]]
    if flagged:
        what = "have gone quiet" if stale_only else "need work"
        print(f"\n{len(flagged)} of {len(rows)} series {what}: "
              + ", ".join(r["series"] for r in flagged))
        return 1
    print(f"\nall {len(rows)} series "
          + ("are still being fed" if stale_only else "current and backfilled"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
