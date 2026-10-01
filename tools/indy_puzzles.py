#!/usr/bin/env python3
"""File the Independent's puzzles the feed never served, from fifteensquared.

    python3 tools/indy_puzzles.py                  # parse, rebuild, file what is new
    python3 tools/indy_puzzles.py --limit 50       # the newest 50 not yet tried
    python3 tools/indy_puzzles.py --dry-run        # count, write no puzzle

tools/fetch_independent.py reads the paper's own feed, which starts at No
8,978 (2015-07-25). fifteensquared blogged every Independent and Independent
on Sunday puzzle long before that, and from 2011 a growing share of those
posts write out every clue with its number and answer -- the whole input to
the grid search tools/ft_puzzles.py runs for the FT. So this is that pipeline
pointed at the blog's Independent category: the same post reader, the same
search, the same filer checks. Only a number not already on disk is parsed,
so the feed's puzzles are never rebuilt or overwritten.

One category carries both papers. The title says which -- "Independent on
Sunday 1218/Kairos", "IoS 1,246" -- and the numbers agree: the Sunday
sequence never reached 3,000, the daily passed 7,000 before the blog began.
A title and a number that disagree are left alone.
"""
import argparse
import collections
import datetime
import functools
import html
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import fetch_fifteensquared as fsq
import file_blog_puzzles
import file_times_puzzles as ftp
import ft_puzzles as ft
import puzzle_integrity
import times_grids as tg
from fetch_puzzle import puzzle_files, puzzle_path, read_puzzle_file, write_puzzle_file

CATEGORY = "Independent"
CACHE = fsq.CACHE / "independent"
GENERATOR = "tools/indy_puzzles.py"
DAILY, SUNDAY = "independent", "indysunday"
SUNDAY_TITLE = re.compile(r"\b(?:on\s+sunday|ios|sunday)\b", re.IGNORECASE)
#: Not the cryptic: the magazine's Inquisitor, the Saturday Magazine puzzles.
OTHER_PUZZLE = re.compile(r"\b(?:inquisitor|magazine|jumbo|quick|genius)\b", re.IGNORECASE)
#: Below this a number is the Sunday sequence's, at or above it the daily's.
SUNDAY_BELOW = 3000


#: A print date or prize label in a title, which the setter pattern would
#: otherwise read as a name: "Sat 23-May-2015", "Saturday Prize Puzzle 2 July
#: 2011", "(Saturday Prize Crossword 7/04/12)".
DATED = re.compile(r"\([^)]*\)|\b(?:sat(?:urday)?|sun(?:day)?)\b(?:\s+prize\s+(?:puzzle|crossword))?"
                   r"(?:[\s\-/]*(?:\d{1,4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b))*",
                   re.IGNORECASE)


#: "by Glowworm", "by Hypnos/Nitsy": the byline, wherever the title puts it.
BYLINE = re.compile(r"\bby\s+([A-Z][\w'’\-]*(?:/[A-Z][\w'’\-]*)?)")
SETTER_FIELD = re.compile(r'"setter":\s*"([^"]+)"')
#: "Independent 6634 (Glow-Worm)", "Independent 7321, Sat 3 April – Merlin",
#: "Independent 6540\\Virgilius": a lone name in brackets or after the last mark.
LONE_NAME = re.compile(r"\(([A-Z][\w'’\-]+)\)|[\-–—/\\]\s*([A-Z][\w'’\-]+)\s*$")
MONTH = re.compile(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.IGNORECASE)


@functools.lru_cache(maxsize=1)
def known_setters():
    """{lowercased name: name} for every setter filed under either paper."""
    out = {}
    for series in (DAILY, SUNDAY):
        for f in (TOOLS.parent / "puzzles" / series).glob("*/*.json"):
            with f.open(encoding="utf-8") as fh:
                m = SETTER_FIELD.search(fh.read(600))
            if m and not re.search(r"\d", m.group(1)):
                out.setdefault(m.group(1).lower(), m.group(1))
    return out


def setter_of(title):
    """The setter a title names, or None: "Independent 8925 Sat 23-May-2015
    Monk" is Monk, "IoS 1,102 / Poins. Heart to heart" is Poins,
    "Independent on Sunday 1106, by Glowworm" is Glowworm. A title with no
    byline is searched for a setter either paper has already filed."""
    m = ft.NUMBER.search(title)
    if not m:
        return None
    known = known_setters()
    by = BYLINE.search(title)
    if by and not MONTH.fullmatch(by.group(1)[:3]):
        return known.get(by.group(1).lower(), by.group(1))
    rest = DATED.sub(" ", title[m.end():])
    name = ft.post_setter(title[:m.end()] + " " + rest.strip())
    name = name and re.split(r"\.\s|\s{2,}", name)[0].strip()
    if name and not re.search(r"\d", name) and not name.lower().startswith(
            ("prize", "independent", "on sunday", "saturday")):
        return known.get(name.lower(), name)
    hits = [(w.start(), known[w.group(0).lower()])
            for w in re.finditer(r"[A-Za-z][\w'’\-]*", title) if w.group(0).lower() in known]
    if hits:
        return min(hits)[1]
    lone = LONE_NAME.search(title)
    name = lone and (lone.group(1) or lone.group(2))
    return known.get(name.lower(), name) if name and not MONTH.match(name) else None


def series_of(title, number):
    """DAILY, SUNDAY, or None when the post is another puzzle or its title
    and number disagree about which paper it was."""
    if number is None or OTHER_PUZZLE.search(title):
        return None
    sunday = bool(SUNDAY_TITLE.search(title))
    if sunday != (number < SUNDAY_BELOW):
        return None
    return SUNDAY if sunday else DAILY


def heading(post):
    """(title, number, series) from a cached post."""
    title = html.unescape(post.get("title", {}).get("rendered", ""))
    number = ft.post_number(title)
    return title, number, series_of(title, number)


def parse_post(post, category_id):
    """One cached post to its record, or None if it is not an Independent
    cryptic or that number is already on disk."""
    if category_id not in post.get("categories", []):
        return None
    title, number, series = heading(post)
    if series is None or puzzle_path(series, number).exists():
        return None
    entries, unsplit = ft.parse_entries(post["content"]["rendered"])
    rec = {
        "post_id": f"fifteensquared-{post['id']}",
        "date": post["date"][:10], "slug": post.get("slug", ""),
        "link": post.get("link"), "series": series,
        "number": number, "title": title,
        "setter": setter_of(title), "entries": entries,
    }
    if unsplit:
        rec["unsplit"] = unsplit
    return rec


def posts():
    cat = fsq.cached_categories()[CATEGORY]
    for f in sorted(fsq.POSTS.glob("*.json")):
        post = json.loads(f.read_text(encoding="utf-8"))
        if cat in post.get("categories", []):
            yield post, cat


def parse(write=True):
    """Every Independent post whose number is not on disk to parsed.jsonl.
    Returns (records, implausible, posted): posted is (series, number, date)
    for every post with a number, the input the print dates are fitted to."""
    recs, odd, posted = [], [], []
    for post, cat in posts():
        _, number, series = heading(post)
        if series:
            posted.append({"series": series, "number": number,
                           "date": post["date"][:10], "post_id": str(post["id"])})
        rec = parse_post(post, cat)
        if rec is None:
            continue
        lo, hi = ft.PLAUSIBLE
        (recs if lo <= len(rec["entries"]) <= hi else odd).append(rec)
    if write:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = CACHE / "parsed.tmp"
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                       encoding="utf-8")
        tmp.replace(CACHE / "parsed.jsonl")
    return recs, odd, posted


def grids(limit=None, max_nodes=tg.DEFAULT_MAX_NODES):
    return tg.run(limit, None, max_nodes=max_nodes, where=CACHE)


def sunday_dates(rows):
    """{number: Sunday}: the Sunday on or before the post, kept only where
    the dates rise strictly with the numbers."""
    guess = {}
    for r in rows:
        day = datetime.date.fromisoformat(r["date"])
        day -= datetime.timedelta(days=(day.weekday() - ftp.SUNDAY) % 7)
        guess[r["number"]] = min(day, guess.get(r["number"], day))
    out, last = {}, None
    for n in sorted(guess):
        ok = last is None or guess[n] > last
        out[n] = guess[n] if ok else None
        last = guess[n] if ok else last
    return out


def retext_held(write=True):
    """Tidy the clues of every file this tool wrote as the parser now reads
    them (ft.tidy, file_blog_puzzles.retext). A held number's post is never
    parsed again, so this walks the files, not the rows. Returns how many."""
    tidied = 0
    for path in puzzle_files():
        if path.parent.parent.name not in (DAILY, SUNDAY):
            continue
        held = read_puzzle_file(path)
        if (held.get("source") or {}).get("acquiredBy") != GENERATOR:
            continue
        new, n = file_blog_puzzles.retext(held, ft.tidy)
        if n:
            tidied += 1
            if write:
                write_puzzle_file(path, new)
    return tidied


def file(posted, write=True, limit=None):
    """File every grid row not yet in puzzles/, newest first; (filed, skipped)."""
    skipped = collections.Counter()
    skipped["already filed, clues tidied"] = retext_held(write)
    recs = {r["post_id"]: r for r in map(json.loads, (CACHE / "parsed.jsonl").open(encoding="utf-8"))}
    rows = [json.loads(line) for line in (CACHE / "grids.jsonl").open(encoding="utf-8")]
    rows.sort(key=lambda r: (r["date"], r["post_id"]), reverse=True)
    by_series = collections.defaultdict(list)
    for p in posted:
        by_series[p["series"]].append(p)
    fits = {s: file_blog_puzzles.sequence_window(ps) for s, ps in by_series.items()}
    dates = {DAILY: ft.print_dates([p for p in by_series[DAILY]
                                    if fits[DAILY](p["date"], p["number"])]),
             SUNDAY: sunday_dates([p for p in by_series[SUNDAY]
                                   if fits[SUNDAY](p["date"], p["number"])])}
    claims = collections.Counter((p["series"], p["number"]) for p in posted)
    filed = []
    on_disk = {}
    for row in rows:
        rec = recs.get(row["post_id"])
        series, number = row["series"], row.get("number")
        if rec is None:
            skipped["no longer parsed (filed since)"] += 1
        elif not fits[series](row["date"], number):
            skipped["number out of sequence"] += 1
        elif claims[(series, number)] > 1:
            skipped["number claimed twice"] += 1
        elif puzzle_path(series, number).exists():
            skipped["already filed"] += 1
        elif limit is not None and len(filed) >= limit:
            skipped["past --limit"] += 1
        else:
            puzzle, why = ftp.build(rec, row, series,
                                    dates[series].get(number))
            if why:
                skipped[why] += 1
                continue
            if series not in on_disk:
                on_disk[series] = ft.held_by_content(series)
            key = puzzle_integrity.content_hash(puzzle)
            if key in on_disk[series]:
                skipped[f"reprint of {on_disk[series][key]}"] += 1
                continue
            if write:
                try:
                    write_puzzle_file(puzzle_path(series, number), puzzle, generator=GENERATOR)
                except ValueError as e:     # puzzle_integrity's write check
                    skipped[f"refused on write: {str(e).split(': ', 1)[-1][:120]}"] += 1
                    continue
            on_disk[series][key] = puzzle["id"]
            filed.append(puzzle["id"])
    return filed, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, help="rebuild and file at most N puzzles")
    ap.add_argument("--dry-run", action="store_true", help="file nothing")
    ap.add_argument("--max-nodes", type=int, default=tg.DEFAULT_MAX_NODES)
    a = ap.parse_args(argv)
    recs, odd, posted = parse()
    print(f"parsed {len(recs)} Independent post(s) not on disk; "
          f"{len(odd)} more with an implausible light count")
    r = grids(a.limit, a.max_nodes)
    if r:
        tg.report(r)
    filed, skipped = file(posted, write=not a.dry_run, limit=a.limit)
    print(f"{'would file' if a.dry_run else 'filed'} {len(filed)}: {' '.join(filed[:20])}"
          + (" ..." if len(filed) > 20 else ""))
    for why, n in skipped.most_common():
        print(f"  skipped {n}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
