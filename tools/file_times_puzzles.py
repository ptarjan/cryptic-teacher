#!/usr/bin/env python3
"""File the Times grids rebuilt from the times-for-the-times blog into puzzles/.

    python3 tools/file_times_puzzles.py             # file every row not yet filed
    python3 tools/file_times_puzzles.py --dry-run   # count what it would do

Reads tools/times_grids.py's grids.jsonl and the parsed.jsonl records beside
it, and files them through tools/file_blog_puzzles.py, which says what a row
must pass. What is the Times's is here: which series a row is, its setter,
its print date.

The date is the print date, from print_dates below: the Quick's is its post
date; the prize puzzles (Saturday's Times, the Jumbo, the Sunday Times) are
blogged after entries close, so theirs comes from the Times's own listing
(tools/fetch_times_listing.py), the post's slug, and the paper's cadence
between them, and stays null where those prove nothing.

The setter of a Quick or Sunday Times puzzle is the one the post's title
names, or failing that SETTERS_FROM_COMMENTS; the Times Cryptic and the Jumbo
stay anonymous.
"""
import argparse
import bisect
import collections
import datetime
import itertools
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import file_blog_puzzles
import parse_timesforthetimes as tftt
import series as series_meta
import times_grids as tg
from file_blog_puzzles import (  # noqa: F401 -- the filer's checks, as tools/ft_puzzles.py reads them
    in_sequence,
    reprinted_by,
    reprinted_from,
    retyped,
    sequence_window,
)

#: Below this a Weekend Cryptic number is the Sunday Times' (~5,200 in 2026,
#: one a week); above it, Saturday's Times (~29,600, six a week).
SUNDAY_TIMES_BELOW = 10_000

#: The series whose blog titles name the setter. The Times Cryptic and the
#: Jumbo are anonymous: a "by" in their titles is the blogger's prose.
BYLINED = {"timesquick", "sundaytimes"}


#: Setters of bylined puzzles whose post title names nobody, keyed by post_id.
#: Each is the name the post's comments agree on, read off
#: timesforthetimes.co.uk/wp-json/wp/v2/comments?post=<post_id>, or its own
#: body backed by a comment; a lone commenter's guess is not enough.
SETTERS_FROM_COMMENTS = {
    25945: "Dean Mayer",    # ST 5079: "setter Dean", "Mr Mayer", "Typical economy from Dean"
    29816: "Robert Price",  # ST 5107: "Thanks Robert", "Robert Price's elegant clues"
    7589: "Flamande",       # QC 570: the post body ("Flamande's puzzles") and a commenter
    21545: "Orpheus",       # QC 2326: "thank you Orpheus ... thank you Merlin" (the blogger)
    22309: "Orpheus",       # QC 2356: "Thanks Merlin and Orpheus", from six commenters
}


def setter(rec, series):
    """The setter the post's title names, where the series prints one: a
    parser that read it already has it in the record."""
    named = rec.get("setter") or series in BYLINED and (
        tftt.setter_from_title(rec.get("title"))
        or SETTERS_FROM_COMMENTS.get(rec.get("post_id")))
    return named or series_meta.default_setter(series)


def target(row):
    """(series key, dated?) for one grid row."""
    label = row["series"]
    if label == "Quick Cryptic":
        return "timesquick", True
    if label == "Daily Cryptic":
        return "times", True
    if label == "Jumbo Cryptic":
        return "timesjumbo", False
    if label == "Weekend Cryptic":
        return ("sundaytimes" if row["number"] < SUNDAY_TIMES_BELOW else "times"), False
    raise ValueError(f"post {row['post_id']}: no series for {label!r}")


# ------------------------------------------------------------- print dates
#
# The Quick and the Daily are blogged the day they are printed, or the evening
# before, so a daily's post date is its print date or the day before it. The
# prize puzzles are blogged after entries close, a week or more late, so their
# post date is no print date at all. Every date below is a fact or follows from
# facts by the paper's cadence; a number nothing proves stays undated.

SATURDAY, SUNDAY = 5, 6
DAY = datetime.timedelta(days=1)
WEEK = datetime.timedelta(days=7)

#: The day each prize series is printed on. The Jumbo also runs on bank
#: holidays, which only the Times's own listing dates.
#: Print dates the blog and the listing cannot prove, each from a page that
#: names the day. Read as the listing is: an anchor, never overruled.
PRINT_DATES = {
    # lucianpoll.com/2022/06/02/times-jumbo-cryptic-crossword-1559/: "A medium
    # strength puzzle for Bank Holiday Thursday", posted that day.
    ("timesjumbo", 1559): datetime.date(2022, 6, 2),
}

PRIZE_DAY = {"times": SATURDAY, "timesjumbo": SATURDAY, "sundaytimes": SUNDAY}

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
ROMAN = {r: i for i, r in enumerate(
    ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"], 1)}
YEAR = re.compile(r"(19|20)\d\d")
DAY_TOKEN = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?")

#: How long after its print date a prize puzzle can be blogged, for reading
#: a date that names no year.
BLOGGED_WITHIN = datetime.timedelta(days=120)


def month_of(token, year_follows):
    token = token.rstrip(".")
    if token in ROMAN and year_follows:
        return ROMAN[token]  # "23-ii-2020": a Roman month only beside a year
    if len(token) >= 3 and token[:3] in MONTHS and (
            len(token) == 3 or token == "sept" or
            datetime.date(2000, MONTHS[token[:3]], 1).strftime("%B").lower() == token):
        return MONTHS[token[:3]]
    return None


#: Holidays a Jumbo title names instead of a date: the words, then the date
#: in a given year.
def easter(y):
    """Easter Sunday of year `y` (the Gregorian computus)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(y, month, day + 1)


def last_monday(y, month):
    d = datetime.date(y, month + 1, 1) - DAY
    return d - DAY * d.weekday()


def first_monday(y, month):
    d = datetime.date(y, month, 1)
    return d + DAY * (-d.weekday() % 7)


def weekday_from(d):
    """`d`, or the Monday after it when it falls on a weekend."""
    return d + DAY * (-d.weekday() % 7 if d.weekday() >= SATURDAY else 0)


#: England's bank holidays moved by proclamation, and those added.
MOVED = {datetime.date(1995, 5, 1): datetime.date(1995, 5, 8),
         datetime.date(2002, 5, 27): datetime.date(2002, 6, 4),
         datetime.date(2012, 5, 28): datetime.date(2012, 6, 4),
         datetime.date(2020, 5, 4): datetime.date(2020, 5, 8),
         datetime.date(2022, 5, 30): datetime.date(2022, 6, 2)}
ADDED = {datetime.date(1999, 12, 31), datetime.date(2002, 6, 3), datetime.date(2011, 4, 29),
         datetime.date(2012, 6, 5), datetime.date(2022, 6, 3), datetime.date(2022, 9, 19),
         datetime.date(2023, 5, 8)}


def jumbo_holidays(y):
    """The bank holidays of year `y` a Jumbo can be printed on: England's,
    but for Good Friday and Christmas Day, and with one after Christmas, the
    first weekday from 26 December. The dated Jumbos from 2016 on show just
    these."""
    days = {weekday_from(datetime.date(y, 1, 1)), easter(y) + DAY, first_monday(y, 5),
            last_monday(y, 5), last_monday(y, 8), weekday_from(datetime.date(y, 12, 26))}
    return {MOVED.get(d, d) for d in days} | {d for d in ADDED if d.year == y}


HOLIDAYS = {
    ("christmas", "day"): lambda y: datetime.date(y, 12, 25),
    ("boxing", "day"): lambda y: datetime.date(y, 12, 26),
    ("new", "year", "s", "day"): lambda y: datetime.date(y, 1, 1),
    ("new", "years", "day"): lambda y: datetime.date(y, 1, 1),
    ("easter", "monday"): lambda y: easter(y) + DAY,
    ("summer", "bank", "holiday"): lambda y: last_monday(y, 8),
}

#: A slug or title as words: "April1, 2017" and "april1-2017" both read
#: april, 1, 2017; "18/11/17" reads 18, 11, 17.
WORD = re.compile(r"\d+(?:st|nd|rd|th)?|[a-z]+")


def named_dates(text, posted):
    """The dates a post's slug or title names: "12-september-2026",
    "26th-april", "march-19-2016", "18/11/17", "Boxing Day, 2016". One naming
    no year is read in the year that puts it before the post and within
    BLOGGED_WITHIN of it."""
    tokens = WORD.findall(text.lower())
    found = []
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1:i + 4]

        def year(k, nxt=nxt):
            return int(nxt[k]) if len(nxt) > k and YEAR.fullmatch(nxt[k]) else None

        day = DAY_TOKEN.fullmatch(tok)
        if day and nxt:
            k = 1 if nxt[0] == "of" and len(nxt) > 1 else 0
            month = month_of(nxt[k], year(k + 1) is not None)
            if month:
                found.append((int(day.group(1)), month, year(k + 1)))
        if tok.isdigit() and len(nxt) >= 2 and nxt[0].isdigit() and len(nxt[1]) in (2, 4) \
                and nxt[1].isdigit() and 1 <= int(nxt[0]) <= 12:
            y = int(nxt[1])
            found.append((int(tok), int(nxt[0]), y if y > 999 else 2000 + y))  # d/m/yy
        month = month_of(tok, False)
        if month and nxt and DAY_TOKEN.fullmatch(nxt[0]):
            found.append((int(DAY_TOKEN.fullmatch(nxt[0]).group(1)), month, year(1)))
    out = set()
    for day, month, year in found:
        for y in ([year] if year else [posted.year, posted.year - 1]):
            try:
                out.add((datetime.date(y, month, day), bool(year)))
            except ValueError:
                continue
    for words, on in HOLIDAYS.items():
        for i in range(len(tokens) - len(words) + 1):
            if tuple(tokens[i:i + len(words)]) == words:
                y = tokens[i + len(words):i + len(words) + 1]
                if y and YEAR.fullmatch(y[0]):
                    out.add((on(int(y[0])), True))
                else:
                    out.update((on(y), False) for y in (posted.year, posted.year - 1))
    return {d for d, dated in out
            if datetime.timedelta(0) <= posted - d <= (
                datetime.timedelta(days=400) if dated else BLOGGED_WITHIN)}


def blog_date(rec, series):
    """The one print date the post's slug and title name, or None: a date on
    the series' day, or for the Jumbo a bank holiday's, which is a Monday or
    in the week from Christmas Eve to 2 January (bloggers mistype the day, and
    a Wednesday "bank holiday" is one of those)."""
    posted = datetime.date.fromisoformat(rec["date"])
    day = PRIZE_DAY[series]
    named = set()
    for text in (rec.get("slug"), rec.get("title")):
        named |= named_dates(text or "", posted)
    on_day = {d for d in named
              if d.weekday() == day or (series == "timesjumbo" and holiday(d))}
    return on_day.pop() if len(on_day) == 1 else None


def holiday(d):
    """Could the Times run a bank-holiday Jumbo on `d`?"""
    return d.weekday() == 0 or (d.weekday() < SATURDAY and (
        (d.month, d.day) >= (12, 24) or (d.month, d.day) <= (1, 2)))


def times_listing():
    """{(series, number): date} off the cached Times listing, or {} without it."""
    import fetch_times_listing
    return fetch_times_listing.paper_dates()


def between(series, a, da, b, db):
    """The dates of the numbers strictly between anchors a and b, or None
    where the cadence does not prove them.

    No week goes without its puzzle, so the numbers between two anchors are
    the prize days between them, in order, exactly when there are as many of
    each. The Sunday Times has only its Sunday puzzle. The Jumbo adds one on
    bank holidays (jumbo_holidays), so a gap with a number too many for its
    Saturdays is its Saturdays and bank holidays, when there are as many of
    those. An older gap with a holiday but no number for it is its Saturdays."""
    day = PRIZE_DAY[series]
    d = da + DAY * ((day - da.weekday() - 1) % 7 + 1)
    days = []
    while d < db:
        days.append(d)
        d += WEEK
    if series == "timesjumbo" and len(days) != b - a - 1:
        days = sorted(set(days) | {h for y in range(da.year, db.year + 1)
                                   for h in jumbo_holidays(y) if da < h < db})
    return days if b > a and len(days) == b - a - 1 else None


def fits_between(series, a, da, b, db):
    """Can numbers a and b be printed on da and db? Every prize day between
    them has its number, so there are at least as many numbers between as
    prize days, and the Jumbo's bank holidays allow at most one more for each
    Monday and Christmas-week weekday between."""
    if b <= a or db <= da:
        return False
    days = [da + DAY * k for k in range(1, (db - da).days)]
    due = sum(d.weekday() == PRIZE_DAY[series] for d in days)
    could = due + (series == "timesjumbo") * sum(
        holiday(d) and d.weekday() != PRIZE_DAY[series] for d in days)
    return due <= b - a - 1 <= could


def date_weekly(series, numbers, listing, blog, notes):
    """{number: date} for one weekly prize series.

    Anchors are the listing's dates and the blog's (a blog date only once an
    adjacent anchor agrees with it by the cadence, or the numbers between it
    and the anchors either side fit the days between them, since a blogger
    can mistype a day). Between two anchors the
    cadence proves, every number follows."""
    anchors = dict(blog)
    for n, d in listing.items():
        if blog.get(n, d) != d:
            notes.append(f"{series}-{n}: the blog says {blog[n]}, the Times's listing {d}; the listing's kept")
        anchors[n] = d
    order = sorted(anchors)

    def agree(a, b):
        return between(series, a, anchors[a], b, anchors[b]) is not None

    def fits(a, b):
        return fits_between(series, a, anchors[a], b, anchors[b])

    confirmed = {}
    for i, n in enumerate(order):
        pairs = [p for p in ((order[i - 1], n) if i > 0 else None,
                             (n, order[i + 1]) if i + 1 < len(order) else None) if p]
        if n in listing or any(agree(*p) for p in pairs) or (
                pairs and all(fits(*p) for p in pairs)):
            confirmed[n] = anchors[n]
        else:
            notes.append(f"{series}-{n}: the blog's {anchors[n]} leaves too many or too few "
                         f"numbers for the days to an anchor beside it; unused")
    order = sorted(confirmed)
    out, breaks = {}, set()
    for n in numbers:
        if n in confirmed:
            out[n] = confirmed[n]
            continue
        i = bisect.bisect(order, n)
        if 0 < i < len(order):
            a, b = order[i - 1], order[i]
            days = between(series, a, confirmed[a], b, confirmed[b])
            if days is not None:
                out[n] = days[n - a - 1]
                continue
            breaks.add((a, b))
    for a, b in sorted(breaks):
        left = sum(1 for n in numbers if a < n < b)
        notes.append(f"{series}: {left} undated between {a} ({confirmed[a]}) and {b} "
                     f"({confirmed[b]}): {b - a} numbers in {(confirmed[b] - confirmed[a]).days} days")
    ends = [n for n in numbers if not order or n < order[0] or n > order[-1]]
    if ends:
        notes.append(f"{series}: {len(ends)} undated outside the anchors "
                     f"({min(ends)}..{max(ends)})")
    return out


def date_times(prize, daily, listing, blog, notes):
    """{number: date} for Saturday's Times and the dailies around it.

    A Saturday puzzle is printed after the number before it and before the
    number after it, so it is the one Saturday between its neighbours: a
    neighbour's date is the listing's, a Saturday blog title's, or for a daily
    its post date and the day after (the evening-before posts). A title naming
    another Saturday than that is named, and the number left undated.

    Then the dailies between two Saturday puzzles seven days apart are that
    week's printing days in order, when there are as many of them as numbers:
    Monday to Friday. A daily outside such a week is the
    one of its post date and the day after that falls between its
    neighbours; failing that it keeps its post date."""
    bounds = {n: (p, p + DAY) for n, p in daily.items()}
    bounds.update({n: (d, d) for n, d in blog.items()})
    bounds.update({n: (d, d) for n, d in listing.items()})
    order = sorted(bounds)
    sat = {}
    for n in prize:
        if n in listing:
            if listing[n].weekday() == SATURDAY:
                sat[n] = listing[n]
            else:
                notes.append(f"times-{n}: the listing prints it on {listing[n]:%A %d %B %Y}, not a Saturday")
            continue
        i, j = bisect.bisect_left(order, n), bisect.bisect_right(order, n)
        lo = bounds[order[i - 1]][0] if i > 0 else None
        hi = bounds[order[j]][1] if j < len(order) else None
        titled = blog.get(n)
        between = []
        if lo and hi:
            d = lo + DAY * ((SATURDAY - lo.weekday() - 1) % 7 + 1)
            while d < hi:
                if printed(d):
                    between.append(d)
                d += WEEK
        if len(between) == 1 and titled not in (None, between[0]):
            notes.append(f"times-{n}: titled {titled}, but the one Saturday between its "
                         f"neighbours is {between[0]}; left undated")
        elif len(between) == 1:
            sat[n] = between[0]
        elif titled and (lo is None or titled > lo) and (hi is None or titled < hi):
            sat[n] = titled
        else:
            notes.append(f"times-{n}: {len(between)} Saturdays between its neighbours "
                         f"({lo} to {hi}) and no title to choose; left undated")
    fixed = {n: d for n, d in listing.items() if n not in prize}
    fixed.update(sat)
    for a, b in itertools.pairwise(sorted(sat)):
        week = [sat[a] + DAY * k for k in range(2, 7) if printed(sat[a] + DAY * k)]
        if sat[b] - sat[a] == WEEK and len(week) == b - a - 1:
            fixed.update(zip(range(a + 1, b), week))
    return date_dailies(daily, fixed)


def date_dailies(daily, fixed):
    """{number: date} for a daily series from its post dates.

    `fixed` are dates already proven. Any other number is the one of its post
    date and the day after (a daily is often blogged the evening before, or
    two in one catch-up post) that is a printing day between its neighbours;
    failing that it keeps its post date."""
    known = {n: (p, p + DAY) for n, p in daily.items()}
    known.update({n: (d, d) for n, d in fixed.items()})
    order = sorted(known)
    days = dict(fixed)
    for i, n in enumerate(order):
        if n in fixed:
            continue
        lo = known[order[i - 1]][0] if i > 0 else None
        hi = known[order[i + 1]][1] if i + 1 < len(order) else None
        fits = [d for d in known[n] if printed(d) and d.weekday() != SUNDAY
                and (lo is None or d > lo) and (hi is None or d < hi)]
        days[n] = fits[0] if len(fits) == 1 else daily[n]
    return days


def printed(day):
    """Is `day` one the Times dates a puzzle? Monday to Saturday: Christmas Day
    has its puzzles too (26917, 2017; the Jumbo 1532, 2021), though no paper."""
    return day.weekday() != SUNDAY


def print_dates(recs, listing=None, renumbered=None):
    """({(series, number): date}, [notes]) for every Times row the blog has.

    `recs` are parsed.jsonl records; only those whose number fits the
    sequence around their post (in_sequence) are read, so a misread number is
    no anchor. `renumbered` is {post_id: number} for the posts run() files
    under a number their title mistypes (retyped); each is read as that
    number, so what is filed under it is dated as its neighbours are."""
    listing = times_listing() if listing is None else listing
    renumbered = renumbered or {}
    groups = collections.defaultdict(list)
    for rec in recs:
        if rec.get("post_id") in renumbered:
            rec = dict(rec, number=renumbered[rec["post_id"]])
        if rec.get("number") and rec.get("series") in (
                "Quick Cryptic", "Daily Cryptic", "Jumbo Cryptic", "Weekend Cryptic"):
            groups[target(rec)].append(rec)
    posts = collections.defaultdict(dict)  # (series, dated) -> {number: rec}
    for key, group in groups.items():
        keep = in_sequence(group) | renumbered.keys()
        for rec in sorted(group, key=lambda r: r["date"]):
            if rec["post_id"] in keep:
                posts[key].setdefault(rec["number"], rec)
    notes, dates = [], {}
    for series in PRIZE_DAY:
        prize = dict(posts[(series, False)])
        if series == "times":
            # A few Saturday posts sit in the blog's Daily category; the
            # Saturday their slug names says which.
            prize.update({n: r for n, r in posts[(series, True)].items()
                          if blog_date(r, series)})
        blog = {n: d for n, rec in prize.items() if (d := blog_date(rec, series))}
        mine = {n: d for (s, n), d in (listing | PRINT_DATES).items() if s == series}
        if series == "times":
            daily = {n: datetime.date.fromisoformat(r["date"])
                     for n, r in posts[(series, True)].items() if n not in prize}
            got = date_times(set(prize), daily, mine, blog, notes)
        else:
            got = date_weekly(series, sorted(prize), mine, blog, notes)
        dates.update({(series, n): d for n, d in got.items()})
    quick = {n: datetime.date.fromisoformat(r["date"])
             for n, r in posts[("timesquick", True)].items()}
    anchors = {n: d for (s, n), d in (listing | PRINT_DATES).items() if s == "timesquick"}
    dates.update({("timesquick", n): d
                  for n, d in date_dailies(quick, anchors).items()})
    return dates, notes


def build(rec, row, series, date):
    """file_blog_puzzles.build, with the setter the Times's post names."""
    return file_blog_puzzles.build(rec, row, series, date, setter(rec, series))


def run(grids=tg.OUT, parsed=tg.PARSED, write=True, listing=None, newest=None):
    source = file_blog_puzzles.Source(
        tool="tools/file_times_puzzles.py", target=target,
        print_dates=lambda recs, renumbered: print_dates(recs, listing, renumbered),
        setter=setter)
    return file_blog_puzzles.run(source, grids, parsed, write=write, newest=newest)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    ap.add_argument("--grids", type=Path, default=tg.OUT)
    ap.add_argument("--parsed", type=Path, default=tg.PARSED)
    args = ap.parse_args(argv)
    run(args.grids, args.parsed, write=not args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
