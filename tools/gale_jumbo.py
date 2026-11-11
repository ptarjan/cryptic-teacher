"""The Times Jumbo cryptics we lack, and the dates of the Times issues that print them.

The Jumbo is printed on the Saturday and, for a Bank Holiday weekend, on the
weekday holiday itself. puzzles/timesjumbo holds the ones the blogs solved
(839, 1197 onward); the rest are on Gale's Times Digital Archive (TTDA, to
2014: its 2015-2019 pages are not there), as "Jumbo Crossword 129" (1997) or
"Jumbo crossword no 838" (2009), in the Saturday's contents beside the
daily cryptic. tools/gale_fetch.py queues one row of kind JUMBO_KIND
(gale_docs.JUMBO_KIND) for each date missing_dates() returns.

Number to date: the Jumbo's number counts the Saturdays and the weekday
holidays holidays() names. Gale's titles and the blog posts' dates date 83
numbers (ANCHORS keeps the 29 the count does not predict from the one
before, and the one before each); date_of() counts forward or back from the
nearest. Against 360 neighbouring pairs of dated numbers (1997-2024, under
75 days apart) the count is right for 349; the misses are a few Christmas
and Easter weeks of 1998-2000, 2009-10 and 2021-23, where a Jumbo was
printed on another day or not on a holiday. Between two anchors whose count
disagrees date_of() says sure=False: the date may be a holiday out. So
wanted() queues every day a Jumbo may have run on, not a date per number.
"""
import bisect
import datetime


def easter(y):
    """Easter Sunday of year `y` (the Gregorian computus)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(y, month, day + 1)


def monday(y, month, last=False):
    """The first (or last) Monday of `month`."""
    if last:
        d = datetime.date(y + (month == 12), month % 12 + 1, 1) - datetime.timedelta(1)
    else:
        d = datetime.date(y, month, 1)
    while d.weekday():
        d += datetime.timedelta(-1 if last else 1)
    return d


def holidays(y):
    """The weekday dates of year `y` the Times printed a Jumbo on besides
    its Saturdays: New Year's Day, Easter Monday, the early May, spring
    (last Monday of May) and summer (last of August) holidays, and Boxing
    Day, each moved on as the holiday is. Not Good Friday nor Christmas Day."""
    ny = datetime.date(y, 1, 1)
    out = {ny if ny.weekday() < 5 else ny + datetime.timedelta(7 - ny.weekday()),
           easter(y) + datetime.timedelta(1), monday(y, 5), monday(y, 5, last=True), monday(y, 8, last=True)}
    boxing = datetime.date(y, 12, 26)
    out.add(boxing if boxing.weekday() < 5 else boxing + datetime.timedelta(2 if boxing.weekday() == 5 else 1))
    return out


def days(first, last):
    """The dates in [first, last] a Jumbo is counted on, earliest first."""
    hol = set()
    for y in range(first.year, last.year + 1):
        hol |= holidays(y)
    d, out = first, []
    while d <= last:
        if d.weekday() == 5 or d in hol:
            out.append(d)
        d += datetime.timedelta(1)
    return out


#: {number: ISO date} of dated Jumbos (see the module doc): Gale's own titles
#: ("Jumbo Crossword 129" on 1997-09-27), then the blog posts' dates.
ANCHORS = {
    129: "1997-09-27",
    167: "1998-05-23",
    170: "1998-06-06",
    196: "1998-11-28",
    208: "1999-01-30",
    209: "1999-02-06",
    225: "1999-05-08",
    257: "1999-12-04",
    263: "2000-01-01",
    279: "2000-04-15",
    285: "2000-05-06",
    319: "2000-12-16",
    329: "2001-02-10",
    478: "2003-08-09",
    500: "2003-12-27",
    527: "2004-06-05",
    569: "2005-03-05",
    587: "2005-06-18",
    613: "2005-12-10",
    640: "2006-05-13",
    821: "2009-06-20",
    839: "2009-10-17",
    850: "2009-12-26",
    879: "2010-07-10",
    1081: "2014-03-08",
    1086: "2014-04-12",
    1100: "2014-07-12",
    1101: "2014-07-19",
    1197: "2016-03-19",
}

#: The Times Digital Archive's last year (gale_inbox.YEARS ends with 2014) and
#: the first year queued (the Jumbo was not weekly before 1997).
FIRST, LAST = datetime.date(1997, 1, 1), datetime.date(2014, 12, 31)


def date_of(number):
    """(date, sure) of Jumbo `number`: counted from the nearest anchor, forward
    from the one before or back from the one after. sure is False when the
    anchors either side disagree with the count between them (a Christmas or
    Easter week the count mispredicts): the date may be one holiday out."""
    nums = sorted(ANCHORS)
    i = bisect.bisect_right(nums, number)
    lo = nums[i - 1] if i else None
    hi = nums[i] if i < len(nums) else None
    sure = True
    if lo is not None and hi is not None:
        span = days(datetime.date.fromisoformat(ANCHORS[lo]), datetime.date.fromisoformat(ANCHORS[hi]))
        sure = len(span) - 1 == hi - lo
    if lo is not None and (hi is None or number - lo <= hi - number):
        start = datetime.date.fromisoformat(ANCHORS[lo])
        return days(start, start + datetime.timedelta(7 * (number - lo) + 60))[number - lo], sure
    end = datetime.date.fromisoformat(ANCHORS[hi])
    back = days(end - datetime.timedelta(7 * (hi - number) + 60), end)
    return back[len(back) - 1 - (hi - number)], sure


def held(files=None):
    """The Jumbo numbers puzzles/timesjumbo holds."""
    import puzzle_paths
    return {int(p.stem.rsplit("-", 1)[1]) for p in (files if files is not None else puzzle_paths.puzzle_files("timesjumbo"))}


def missing(have=None):
    """[(number, date, sure)] of each Jumbo from FIRST to LAST that
    puzzles/timesjumbo lacks, by number."""
    have = held() if have is None else have
    out, n = [], min(ANCHORS)
    while date_of(n)[0] >= FIRST:
        n -= 1
    n += 1
    while (d := date_of(n))[0] <= LAST:
        if n not in have:
            out.append((n, *d))
        n += 1
    return out


def wanted(have=None):
    """[date] of each Jumbo day from FIRST to LAST but those of Jumbos
    puzzles/timesjumbo holds, newest first. By date, not number: where the
    count between two anchors is unsure the date of a number may be a
    holiday out, so every Saturday and holiday goes, and a day with no Jumbo
    costs one lookup (a cached miss)."""
    have = held() if have is None else have
    done = {date_of(n)[0] for n in have if FIRST <= date_of(n)[0] <= LAST}
    return [d for d in reversed(days(FIRST, LAST)) if d not in done]


#: Dates whose solution windows go first: the Jumbos 149, 230 and 256, which
#: puzzles/timesjumbo lacks, and the five Saturdays after each.
PRIORITY_DAYS = [datetime.date(1998, 1, 31), datetime.date(1999, 6, 5), datetime.date(1999, 11, 27)]


def number_on(day):
    """The number of the Jumbo printed on `day`, or None (date_of inverted)."""
    for n in range(1, 1300):
        if date_of(n)[0] == day:
            return n
    return None


def solution_days():
    """[date] of every day a Jumbo may have run on, FIRST to LAST: the issues
    that may print a Jumbo's solution (gale_docs.JUMBO_SOLUTION_KIND), a week
    or two (1997-2003: up to five) after the puzzle. All of them, not only those
    lacking from puzzles/timesjumbo. Order: PRIORITY_DAYS and the five
    Saturdays after each, then 1997-2003 earliest first, then the rest newest first."""
    week = datetime.timedelta(weeks=1)
    first = [d + k * week for d in PRIORITY_DAYS for k in range(6)]
    every = days(FIRST, LAST)
    early = [d for d in every if d.year < 2004]
    late = [d for d in reversed(every) if d.year >= 2004]
    return list(dict.fromkeys(first + early + late))
