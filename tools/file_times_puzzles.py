#!/usr/bin/env python3
"""File the Times grids rebuilt from the times-for-the-times blog into puzzles/.

    python3 tools/file_times_puzzles.py             # file every row not yet filed
    python3 tools/file_times_puzzles.py --dry-run   # count what it would do

Reads tools/times_grids.py's grids.jsonl and the parsed.jsonl records beside
it. A row is filed only when all of these hold, and every refusal is counted
by its reason:

  - every light in the grid has an entry with a clue;
  - every clue carries an enumeration agreeing with its light, or with its
    whole group when it leads a linked answer; a "See N" continuation may
    carry none;
  - the answers, read through times_grids.answers() so the corrections apply,
    write into the grid with every crossing agreeing;
  - the number sits in its sequence: inside the range the longest run of
    rows whose numbers rise with the post date spans within four weeks of
    this post. A row outside it carries a number the parser misread (a year,
    a stray digit, another series' number); one merely posted out of order
    is inside. A number two posts claim files neither;
  - no other series reprints it: from the first number a reprinting series
    (`reprints` in tools/series.py) holds on, that series files it.

The blog's answers are a solver's write-up, not the paper's key, so
solutionSource is `timesforthetimes` and provenance says so. The date is the
print date, from print_dates below: the Quick's is its post date; the prize
puzzles (Saturday's Times, the Jumbo, the Sunday Times) are blogged after
entries close, so theirs comes from the Times's own listing
(tools/fetch_times_listing.py), the post's slug, and the paper's cadence
between them, and stays null where those prove nothing.

The setter of a Quick or Sunday Times puzzle is the one the post's title
names; the Times Cryptic and the Jumbo stay anonymous.

A file already on disk is never rewritten but for its date, which facts
arriving later (the next week's posts, the listing) can prove, and a
placeholder setter the title names: by then it may carry annotations. One
whose clues or answers no longer match what this would write is named, so a
correction made upstream is seen rather than lost.
"""
import argparse
import bisect
import collections
import datetime
import itertools
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import fetch_puzzle
import parse_timesforthetimes as tftt
import reconstruct_grid as rg
import series as series_meta
import times_grids as tg
from fetch_puzzle import has_words, puzzle_path, read_puzzle_file, write_puzzle_file
from file_penguin_puzzle import separators
from normalise_linked_enumerations import enumeration_parts, resolve_groups

#: C1 controls: bytes the blog lost in decoding, never text.
C1 = re.compile(r"[\x80-\x9f]")


def clean(clue):
    """The clue as text: the blog's markup and lost bytes removed."""
    return C1.sub("", fetch_puzzle.plain_text(clue)) if clue else clue


#: Below this a Weekend Cryptic number is the Sunday Times' (~5,200 in 2026,
#: one a week); above it, Saturday's Times (~29,600, six a week).
SUNDAY_TIMES_BELOW = 10_000

#: The series whose blog titles name the setter. The Times Cryptic and the
#: Jumbo are anonymous: a "by" in their titles is the blogger's prose.
BYLINED = {"timesquick", "sundaytimes"}


def setter(rec, series):
    """The setter the post's title names, where the series prints one."""
    named = series in BYLINED and tftt.setter_from_title(rec.get("title"))
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


#: How far from a post the sequence around it is read.
NEAR = datetime.timedelta(days=28)


def in_sequence(rows):
    """The post_ids whose numbers fit the sequence around their post date."""
    rows = sorted(rows, key=lambda r: (r["date"], r["post_id"]))
    tails, tail_at, back = [], [], [None] * len(rows)
    for i, r in enumerate(rows):
        k = bisect.bisect_left(tails, r["number"])
        back[i] = tail_at[k - 1] if k else None
        if k == len(tails):
            tails.append(r["number"])
            tail_at.append(i)
        else:
            tails[k], tail_at[k] = r["number"], i
    spine, i = [], tail_at[-1] if tail_at else None
    while i is not None:
        spine.append(rows[i])
        i = back[i]
    spine.reverse()
    days = [datetime.date.fromisoformat(r["date"]) for r in spine]
    keep = set()
    for r in rows:
        day = datetime.date.fromisoformat(r["date"])
        lo, hi = bisect.bisect_left(days, day - NEAR), bisect.bisect_right(days, day + NEAR)
        # The spine rises, so its first and last numbers in the window bound it.
        if lo < hi and spine[lo]["number"] <= r["number"] <= spine[hi - 1]["number"]:
            keep.add(r["post_id"])
    return keep


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


def named_dates(slug, posted):
    """The dates a post's slug names: "12-september-2026", "26th-april",
    "march-19-2016". One naming no year is read in the year that puts it
    before the post and within BLOGGED_WITHIN of it."""
    tokens = slug.lower().split("-")
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
        month = month_of(tok, False)
        if month and nxt and DAY_TOKEN.fullmatch(nxt[0]):
            found.append((int(DAY_TOKEN.fullmatch(nxt[0]).group(1)), month, year(1)))
    out = set()
    for day, month, year in found:
        for y in ([year] if year else [posted.year, posted.year - 1]):
            try:
                date = datetime.date(y, month, day)
            except ValueError:
                continue
            if datetime.timedelta(0) <= posted - date <= (
                    datetime.timedelta(days=400) if year else BLOGGED_WITHIN):
                out.add(date)
    return out


def blog_date(rec, series):
    """The one print date the post's slug names, or None: a date on the
    series' day, or for the Jumbo a bank holiday's, which is a Monday or in
    the week from Christmas Eve to 2 January (bloggers mistype the day, and
    a Wednesday "bank holiday" is one of those)."""
    posted = datetime.date.fromisoformat(rec["date"])
    day = PRIZE_DAY[series]
    on_day = {d for d in named_dates(rec.get("slug") or "", posted)
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
    bank holidays, so a gap holding one no anchor names has a number too many
    and proves nothing."""
    day = PRIZE_DAY[series]
    d = da + DAY * ((day - da.weekday() - 1) % 7 + 1)
    days = []
    while d < db:
        days.append(d)
        d += WEEK
    return days if b > a and len(days) == b - a - 1 else None


def date_weekly(series, numbers, listing, blog, notes):
    """{number: date} for one weekly prize series.

    Anchors are the listing's dates and the blog's (a blog date only once an
    adjacent anchor agrees with it by the cadence, since a blogger can mistype
    a day). Between two anchors the cadence proves, every number follows."""
    anchors = dict(blog)
    for n, d in listing.items():
        if blog.get(n, d) != d:
            notes.append(f"{series}-{n}: the blog says {blog[n]}, the Times's listing {d}; the listing's kept")
        anchors[n] = d
    order = sorted(anchors)

    def agree(a, b):
        return between(series, a, anchors[a], b, anchors[b]) is not None

    confirmed = {}
    for i, n in enumerate(order):
        if (n in listing or (i > 0 and agree(order[i - 1], n))
                or (i + 1 < len(order) and agree(n, order[i + 1]))):
            confirmed[n] = anchors[n]
        else:
            notes.append(f"{series}-{n}: the blog's {anchors[n]} agrees with no anchor beside it; unused")
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


def print_dates(recs, listing=None):
    """({(series, number): date}, [notes]) for every Times row the blog has.

    `recs` are parsed.jsonl records; only those whose number fits the
    sequence around their post (in_sequence) are read, so a misread number is
    no anchor."""
    listing = times_listing() if listing is None else listing
    groups = collections.defaultdict(list)
    for rec in recs:
        if rec.get("number") and rec.get("series") in (
                "Quick Cryptic", "Daily Cryptic", "Jumbo Cryptic", "Weekend Cryptic"):
            groups[target(rec)].append(rec)
    posts = collections.defaultdict(dict)  # (series, dated) -> {number: rec}
    for key, group in groups.items():
        keep = in_sequence(group)
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
        mine = {n: d for (s, n), d in listing.items() if s == series}
        if series == "times":
            daily = {n: datetime.date.fromisoformat(r["date"])
                     for n, r in posts[(series, True)].items() if n not in prize}
            got = date_times(set(prize), daily, mine, blog, notes)
        else:
            got = date_weekly(series, sorted(prize), mine, blog, notes)
        dates.update({(series, n): d for n, d in got.items()})
    return dates, notes


def epoch_ms(day):
    return int(datetime.datetime(day.year, day.month, day.day,
                                 tzinfo=datetime.timezone.utc).timestamp() * 1000)


def reprinted_from():
    """{series: the first number a series reprinting it holds}."""
    first = {}
    for key, meta in series_meta.SERIES.items():
        if meta.get("reprints"):
            numbers = [series_meta.parse_id(p.stem)[1]
                       for p in fetch_puzzle.PUZZLE_DIR.glob(f"{key}-[0-9]*.json")]
            if numbers:
                first[meta["reprints"]] = (key, min(numbers))
    return first


def build(rec, row, series, date):
    """(puzzle, None) or (None, reason it is not filed). `date` is the print
    date, or None where nothing proves one."""
    entries = [dict(e, clue=clean(e.get("clue"))) for e in tg.answers(rec, row)]
    if not tg.answers_fit(row["grid"], {"entries": entries}):
        return None, "answers disagree with the grid"
    lights = rg.light_cells(row["grid"])
    by_key = {(e["number"], e["direction"]): e for e in entries}
    if set(by_key) != set(lights) or len(by_key) != len(entries):
        return None, "entries do not match the grid's lights"
    if not all(has_words(e.get("clue") or "") for e in entries):
        return None, "a light has no clue"

    out = []
    for e in tg.printed({"entries": entries}):
        cells = lights[(e["number"], e["direction"])]
        out.append({
            "id": f"{e['number']}-{e['direction']}",
            "number": e["number"],
            "direction": e["direction"],
            "position": {"x": cells[0][1], "y": cells[0][0]},
            "length": len(cells),
            "clue": e["clue"],
            "enumeration": e.get("enumeration"),
            "solution": e["answer"],
        })
    by_id = {e["id"]: e for e in out}
    try:
        groups = resolve_groups(out)
    except SystemExit:
        return None, "a linked clue names no single light"
    for e in out:
        enumeration = e.pop("enumeration")
        group = groups.get(e["id"], [e["id"]])
        if not enumeration:
            if group[0] == e["id"]:
                return None, "a clue has no enumeration"
            continue
        count = sum(n for n, _ in enumeration_parts(enumeration))
        if count == e["length"]:
            group = [e["id"]]
        elif group[0] != e["id"] or count != sum(by_id[g]["length"] for g in group):
            return None, "an enumeration disagrees with its light"
        for gid, seps in separators(group, by_id, enumeration).items():
            if seps:
                by_id[gid]["separatorLocations"] = seps
    for e in out:
        if e["id"] in groups:
            e["group"] = list(groups[e["id"]])
        e["solution"] = e.pop("solution")  # last, as every other series writes it

    number = row["number"]
    fixed = [f"{c['number']} {c['direction']}" for c in row.get("corrections", ())]
    check = (f"grid rebuilt from the blog's light list ({row['how']}); every "
             f"answer written into it with each crossing agreeing")
    if fixed:
        check += (f"; the grid proves the blog's answer wrong at "
                  f"{', '.join(fixed)}, corrected here")
    kind = series_meta.kind(series)
    return {
        "id": series_meta.puzzle_id(series, number),
        "number": number,
        "series": series,
        "name": f"{series_meta.publisher(series)} {kind.lower()} crossword No {number:,}",
        "setter": setter(rec, series),
        "date": date and epoch_ms(date),
        "dimensions": {"cols": len(row["grid"][0]), "rows": len(row["grid"])},
        "sourceUrl": rec["link"],
        "solutionSource": {"kind": "timesforthetimes", "url": rec["link"],
                           "date": rec["date"], "check": check},
        "entries": out,
    }, None


def content(puzzle):
    """What a later run compares: the grid, the clues and the answers."""
    return [(e["id"], e["position"], e["length"], e["clue"], e["solution"])
            for e in puzzle["entries"]]


def run(grids=tg.OUT, parsed=tg.PARSED, write=True, listing=None):
    recs = {}
    for line in parsed.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        recs[rec["post_id"]] = rec
    rows = [json.loads(line) for line in grids.read_text(encoding="utf-8").splitlines()]

    skipped = collections.Counter()
    sources = collections.defaultdict(list)
    for row in rows:
        if not row.get("number"):
            skipped["no puzzle number"] += 1
            continue
        sources[(row["series"], *target(row))].append(row)
    claims = collections.defaultdict(list)
    for (_, series, dated), group in sources.items():
        keep = in_sequence(group)
        for row in group:
            if row["post_id"] in keep:
                claims[(series, row["number"])].append((row, dated))
            else:
                skipped["number out of sequence"] += 1

    dates, notes = print_dates(recs.values(), listing)
    reprints = reprinted_from()
    filed, kept, drifted = collections.Counter(), 0, []
    redated, renamed = collections.Counter(), collections.Counter()
    for (series, number), claim in sorted(claims.items()):
        if len(claim) > 1:
            skipped["number claimed twice"] += len(claim)
            continue
        if series in reprints and number >= reprints[series][1]:
            skipped[f"{reprints[series][0]} reprints it"] += 1
            continue
        row, dated = claim[0]
        rec = recs[row["post_id"]]
        date = dates.get((series, number)) or (
            datetime.date.fromisoformat(rec["date"]) if dated else None)
        puzzle, why = build(rec, row, series, date)
        if why:
            skipped[why] += 1
            continue
        path = puzzle_path(series, number)
        if path.exists():
            kept += 1
            held = read_puzzle_file(path)
            if content(held) != content(puzzle):
                drifted.append(puzzle["id"])
            # Only the date and a placeholder setter are ever rewritten: the
            # date is derived from facts that arrive after the file (the next
            # Saturday's title, the listing), and a name never replaces a name.
            fix = {}
            if puzzle["date"] and held.get("date") != puzzle["date"]:
                fix["date"] = puzzle["date"]
                redated[series] += 1
            if (held.get("setter") == series_meta.default_setter(series)
                    and puzzle["setter"] != held["setter"]):
                fix["setter"] = puzzle["setter"]
                renamed[series] += 1
            if fix and write:
                write_puzzle_file(path, {**held, **fix})
            continue
        if write:
            write_puzzle_file(path, puzzle, generator="tools/file_times_puzzles.py")
        filed[series] += 1

    verb = "would file" if not write else "filed"
    print(f"{verb} {sum(filed.values())}: "
          + (", ".join(f"{s} {n}" for s, n in sorted(filed.items())) or "nothing new"))
    print(f"already filed {kept}")
    for why, n in skipped.most_common():
        print(f"  skipped {n}: {why}")
    if redated:
        print(f"{'would redate' if not write else 'redated'} {sum(redated.values())}: "
              + ", ".join(f"{s} {n}" for s, n in sorted(redated.items())))
    if renamed:
        print(f"{'would name the setter of' if not write else 'named the setter of'} "
              f"{sum(renamed.values())}: "
              + ", ".join(f"{s} {n}" for s, n in sorted(renamed.items())))
    for note in notes:
        print(f"  date: {note}")
    if drifted:
        print(f"  {len(drifted)} filed puzzle(s) differ from the blog now, left as they are: "
              + " ".join(drifted))
    return filed, skipped, drifted


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
