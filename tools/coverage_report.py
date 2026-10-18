#!/usr/bin/env python3
"""What we hold of every series, and which ones are not finished.

Run it:

    python3 tools/coverage_report.py            # the table
    python3 tools/coverage_report.py --quiet    # only the series with a problem
    python3 tools/coverage_report.py --stale-only   # only STALE, as the nightly alerts on

Every series is meant to be walked back to its source's floor and then kept
current nightly. Two different things stop that happening and neither one
announces itself: a fetcher that can only ever get "today" leaves its series one
puzzle deep forever, and a feed that quietly stops answering leaves its series
frozen at whatever day it broke on. Both look healthy from inside the nightly
run -- it fetched, nothing failed, there was simply nothing new -- so the only
way either is noticed is a person looking at the site and counting. This is that
count, run every night.

The flags, in the order they matter:

  STALE    the newest puzzle is older than the series' STALE_AFTER_DAYS (its
           cadence plus its source's posting lag), so the feed has stopped
           answering and nobody has been told.
  SHALLOW  the whole series spans less than SHALLOW_DAYS, which means it has
           never been backfilled.
  HOLES    more than HOLES_PCT of the numbers between the oldest and newest we
           hold are missing, so a walk stopped part-way.
  REACH    the oldest number held is above the series' ARCHIVE_FLOOR, so the
           walk back has not reached what the source still serves.
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
from datetime import date, datetime, timedelta, timezone

import puzzle_paths
import series as series_meta

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
}

# Days of silence after which a live series is STALE: every series the daily
# run hooks, so none can stop arriving unnoticed. 2026-10-12: Quiptic, Sunday
# Times, Times Jumbo and Azed had all stopped weeks earlier while the old rule
# (three cadences, seven series) stayed quiet. The base is the cadence: daily 3,
# weekly 10, fortnightly 17, monthly 40. Added on top is the source's own lag:
# a series rebuilt from a blog only arrives once the post does, and a prize
# puzzle's post waits for its competition to close, a week after it ran (two
# weeks for the Jumbo). The newest held date is the puzzle's own, so that lag
# is silence the feed always shows. A series not listed here never goes STALE.
# Dead series (the Nation, Listener, TLS archives) and the books are left out.
STALE_AFTER_DAYS = {
    # Fetched from the paper the day it runs.
    "cryptic": 3,
    "independent": 3,
    "metro": 3,          # Mon-Fri: Friday to Monday is 3
    "quiptic": 10,
    "everyman": 10,
    "indysunday": 10,
    "cyclops": 17,       # Private Eye, fortnightly
    # Rebuilt from blogs posted the same day or the next.
    "times": 3,
    "timesquick": 3,
    "telegraph": 4,      # a day's blog lag after Sunday's gap
    "toughie": 5,        # Tue-Fri: Friday to Tuesday is 4, plus the blog's day
    "ftcryptic": 4,      # Mon-Sat, fifteensquared the same day or the next
    # Prize puzzles, blogged once their competition closes.
    "sundaytimes": 10 + 7,
    "mephisto": 10 + 7,
    "sundaytel": 10 + 7,
    "sundaytough": 10 + 7,
    "timesjumbo": 10 + 14,
    "azed": 40 + 7,      # monthly from 2026, first Sunday; blogged a week on
    "timesclub": 40,     # the Times Crossword Club's monthly
    "tls": 17,           # fortnightly since 2025 (tools/tls_puzzles.py)
    # No "listener": archive-only by Paul's choice (2026-10-12), no paid Times
    # Puzzle Club, so it has no live source and a threshold would alert every
    # night. Not "nation" either: its weekly cryptic ended 2020-04-13.
    "genius": 40,        # monthly; filed unsolved before its answers post
}


def is_date_keyed(held):
    """True when a series' "number" is really its own date spelled YYYYMMDD
    (metro until 2026-10-11: number 20260918 on 2026-09-18), not a running
    puzzle count.

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
        if parsed != series_meta.puzzle_day(p):
            return False
        checked = True
    return checked


def audit(puzzles, today, waiting=None):
    """One row per series, each with a (possibly empty) list of flags.
    `waiting` is {series: newest date} of puzzles fetched but held back in
    clues_only/ for their answers (waiting_dates): the feed did answer, so
    they count against STALE, though not as filed puzzles."""
    by_series = defaultdict(list)
    for p in puzzles:
        by_series[p["series"]].append(p)

    rows = []
    for name in sorted(by_series):
        held = by_series[name]
        all_numbers = sorted(p["number"] for p in held)
        dates = sorted(d for d in map(series_meta.puzzle_day, held) if d)
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
            quiet = (today - max(newest, (waiting or {}).get(name, newest))).days
            depth = (newest - oldest).days
            stale_after = STALE_AFTER_DAYS.get(name)
            if stale_after and quiet > stale_after:
                flags.append(f"STALE nothing since {today - timedelta(days=quiet)} ({quiet}d)")
            if depth < SHALLOW_DAYS:
                flags.append(f"SHALLOW spans {depth}d, never backfilled")
        else:
            newest = oldest = None

        if dates and cadence and is_date_keyed(held):
            # numbers[0] and numbers[-1] are dates in disguise here, so their
            # difference (old metro: 20260918 - 20250403 = 10,464) isn't a puzzle
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
            # A `year` has no weekday; its 1 January is not a publishing day.
            if p.get("date"):
                odd[series_meta.puzzle_day(p).strftime("%a")].append(p["number"])
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
            # A shelf dated by years says so in years, not as 1 January.
            **({"oldest": oldest.year, "newest": newest.year}
               if dates and not any(p.get("date") for p in held)
               else {"oldest": oldest, "newest": newest}),
            "flags": flags,
        })
    return rows


def held_puzzles():
    """The rows of puzzles/index.json this report reads (id, series, number,
    date, year), straight from the puzzle files that index is built from.
    The daily `checks` unit then needs no generated files at start
    (daily_units.py GENERATED): waiting its turn for a whole-corpus rebuild
    took 35 of its 45 minutes and got it killed (2026-10-15). It is never
    staler than the files either. Unlisted series are left out, as the
    index's "puzzles" leaves them out."""
    rows = []
    for path in puzzle_paths.puzzle_files():
        p = json.loads(path.read_text(encoding="utf-8"))
        # A file never stores its series; its id names it (annotation.view_puzzle).
        series = series_meta.parse_id(p["id"])[0]
        if not series_meta.unlisted(series):
            rows.append({"series": series, **{k: p[k] for k in ("id", "number", "date", "year") if k in p}})
    return rows


def waiting_dates():
    """{series: newest date} of the clues-only holds (clues_only/), puzzles
    the feed delivered that wait on answers before they file: genius-280
    sat there from 2026-10-05 while the report called the series STALE."""
    import clues_only
    out = {}
    for path in clues_only.files():
        p = json.loads(path.read_text(encoding="utf-8"))
        try:
            day = date.fromisoformat(str(p.get("date"))[:10])
        except ValueError:
            continue
        series = series_meta.parse_id(p["id"])[0]
        out[series] = max(day, out.get(series, day))
    return out


def main(argv):
    quiet = "--quiet" in argv
    # Two audiences, one report. A dead feed is tonight's problem and worth
    # waking someone for; an unfinished backfill is a standing to-do that would
    # fire the same alert every night until the walk finishes, which is how an
    # alert stops being read. --stale-only is the half that is allowed to shout.
    stale_only = "--stale-only" in argv
    rows = audit(held_puzzles(), datetime.now(timezone.utc).date(), waiting_dates())
    if stale_only:
        for r in rows:
            r["flags"] = [f for f in r["flags"] if f.startswith("STALE")]

    shown = [r for r in rows if r["flags"]] if quiet or stale_only else rows
    for r in shown:
        # The publisher is what makes a row actionable: "metro" is a key, "Metro"
        # is where to go looking for an archive.
        # "the shelf" for a book series: it is one key over a dozen papers,
        # and the row it labels is one line of a coverage report.
        pub = series_meta.publisher(r["series"]) or "the shelf"
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
