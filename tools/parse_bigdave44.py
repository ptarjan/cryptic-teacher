#!/usr/bin/env python3
"""Turn cached bigdave44.com posts into one clue-and-answer record per puzzle.

The Telegraph keeps its archive behind a paywall, but bigdave44.com has
hinted every back-page cryptic and Toughie since 2009, and each post prints
the clue NUMBER, the clue with its enumeration, and the answer. That is the
same light list tools/parse_timesforthetimes.py reads off the Times blog, in a
tidier house style, so the reading is that module's read_entries(); this one
only adds what is the Telegraph's:

  * which of the four series a post is, and its number, off the title;
  * the print date: the review's "This puzzle was published on ..." line, or
    else the day the hints went up, which is the day the paper printed it;
  * the setter, from the "Toughie No 3762 by Dada" heading or the setter's
    category, and never from "Hints and tips by", which is the blogger.

A prize puzzle is blogged twice, hints on the day and a full review after
entries close, so posts are grouped by (series, number) and the fullest list
of each group is the record. Reads the cache tools/fetch_wp_blog.py writes;
never the network.
"""
import argparse
import bisect
import collections
import datetime
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_wp_blog
import file_blog_puzzles
import parse_timesforthetimes as tftt

BLOG = fetch_wp_blog.BLOGS["bigdave44"]
POSTS = BLOG.posts
OUT = BLOG.cache / "parsed.jsonl"

#: The paper each title prefix names, and the series key it files under.
PAPERS = (
    (re.compile(r"^\s*sunday\s+toughie\b", re.I), "sundaytough"),
    (re.compile(r"^\s*toughie\b", re.I), "toughie"),
    (re.compile(r"^\s*(?:ST|sunday\s+telegraph)\b", re.I), "sundaytel"),
    (re.compile(r"^\s*(?:DT|daily\s*telegraph)\b", re.I), "telegraph"),
)
#: The puzzle number after the paper: "DT 31354", "Toughie No 2717",
#: "DT31349 (Hints)", "Sunday Toughie 242 (full review)".
NUMBER = re.compile(r"^\D*?(\d[\d,]{1,6})\b")

#: The body's heading names the setter where the paper prints one: "Toughie
#: No 2717 by Robyn", "Sunday Toughie No 180 by Beam". Only a line that opens
#: with the paper and its number counts, so "Hints and tips by Mr K" -- the
#: blogger -- is never read as the setter.
BYLINE = re.compile(
    r"^(?:DT\s+)?(?:daily\s*telegraph|sunday\s+telegraph|sunday\s+toughie|toughie)"
    r"\b[^\d]{0,30}\d[\d,]*\s+by\s+([A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*){0,2})", re.I)
#: A Toughie heading that is the paper and its number alone, "Toughie No
#: 2257", puts the byline on the puzzle's title on the line after it:
#: "Double, double toil and trouble by Firefly". Only the Toughies print a
#: setter, so under any other heading that line is the blogger's ("A full
#: analysis by Big Dave"), and so is any line naming the blogging.
BARE_HEADING = re.compile(r"^(?:sunday\s+)?toughie\b[^\d]{0,30}\d[\d,]*\s*$", re.IGNORECASE)
TITLE_BYLINE = re.compile(r"\bby\s+([A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*){0,2})\s*$")
BLOGGER = re.compile(r"\b(?:hints|tips|review\w*|analysis|blog\w*|comments?)\b", re.IGNORECASE)
#: Setter categories sit under the Toughie's and the Sunday Toughie's.
SETTER_PARENTS = {11, 7625}
#: A setter category that names no setter.
NOT_A_SETTER = re.compile(r"[^\w\s'’.-]|\d")

PUBLISHED = re.compile(
    r"published\s+on\s+(?:\w+day,?\s+)?(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(?:of\s+)?([A-Za-z]+)\.?,?\s+(\d{4})", re.I)
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
REVIEW = re.compile(r"\breview\b", re.I)

#: The days each series is printed on; a date on another day is no print date.
PRINT_DAYS = {"telegraph": set(range(6)), "toughie": set(range(6)),
              "sundaytel": {6}, "sundaytough": {6}}

#: How many lights a Telegraph 15x15 has, give or take a linked answer. A
#: prize puzzle's hints post covers only some of them and is kept out by this.
PLAUSIBLE = (20, 40)

#: "1a", "12d." -- the clue's number with its direction glued on, as every era
#: of the blog writes it. The shared reader takes the direction off an
#: Across/Down heading, and the blog's headings vary ("Across Clues", none at
#: all), so the suffix becomes the heading; a linked head "1a/5d" keeps it.
SUFFIX = re.compile(r"^(\d{1,2})\s*([ad])\b\.?(?!\s*(?:/|,|&|and)\s*\d)\s*", re.I)
WAY = {"a": "Across", "d": "Down"}
#: Until about 2015 the answer is printed white on white inside braces,
#: "{ SAPLINGS } An anagram ...", and the shared reader drops braced text.
HIDDEN = re.compile(r"\{\s*((?:<[^>]+>\s*)*[^<{}]*?(?:\s*</[^>]+>)*)\s*\}")

#: "&npsp;" is the blog's typo for "&nbsp;", which no HTML decoder knows;
#: the editor escaped its ampersand, so the post holds "&amp;npsp;".
TYPOED_NBSP = re.compile(r"&(?:amp;)?npsp;")


def categories():
    path = BLOG.cache / "categories.json"
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {int(k): v for k, v in raw.items()}


def title_of(post):
    return html.unescape(post.get("title", {}).get("rendered", ""))


def series_and_number(post, heading):
    """(series key, number) off the title, or the body's first line when the
    title names no paper; (None, None) for a post that is no puzzle of ours."""
    for text in (title_of(post), heading):
        for pattern, key in PAPERS:
            if pattern.search(text):
                m = NUMBER.match(text[pattern.search(text).end():])
                if m:
                    return key, int(m.group(1).replace(",", ""))
    return None, None


def setter_of(post, rendered, cats):
    """The setter the post names, or None."""
    for i, ln in enumerate(rendered[:6]):
        m = BYLINE.match(ln)
        if m:
            return m.group(1).strip(" .")
        if BARE_HEADING.match(ln) and i + 1 < len(rendered):
            m = TITLE_BYLINE.search(rendered[i + 1])
            if m and not BLOGGER.search(rendered[i + 1]):
                return m.group(1).strip(" .")
    named = {re.sub(r"\s*\(Sunday\)$", "", cats[c]["name"]) for c in post.get("categories", ())
             if c in cats and cats[c]["parent"] in SETTER_PARENTS}
    named = {n for n in named if not NOT_A_SETTER.search(n)}
    return named.pop() if len(named) == 1 else None


def published_on(rendered):
    for ln in rendered:
        m = PUBLISHED.search(ln)
        if m:
            month = MONTHS.get(m.group(2)[:3].lower())
            try:
                return datetime.date(int(m.group(3)), month, int(m.group(1))) if month else None
            except ValueError:
                return None
    return None


def headed(rendered):
    """The lines with each clue's direction suffix turned into the heading
    the shared reader expects: "9a Fragrance ... (5)" under "Across"."""
    out, way = [], None
    for ln in rendered:
        m = SUFFIX.match(ln)
        if m:
            if WAY[m.group(2).lower()] != way:
                way = WAY[m.group(2).lower()]
                out.append(way)
            ln = f"{m.group(1)} {ln[m.end():]}"
        out.append(ln)
    return out


def read_post(post, cats):
    """One post's facts, or None for a post that is no puzzle of ours."""
    body = TYPOED_NBSP.sub(" ", post["content"]["rendered"])
    rendered = [ln for ln in tftt.lines(HIDDEN.sub(r"\1 – ", body)) if ln]
    series, number = series_and_number(post, rendered[0] if rendered else "")
    if series is None:
        return None
    entries, unsplit = tftt.read_entries(headed(rendered))
    review = bool(REVIEW.search(title_of(post))) or any(
        REVIEW.search(ln) for ln in rendered[:3])
    return {
        "post_id": post["id"], "date": post["date"][:10], "slug": post["slug"],
        "link": post.get("link"), "series": series, "number": number,
        "title": title_of(post), "entries": entries, "unsplit": unsplit,
        "setter": setter_of(post, rendered, cats),
        "published": published_on(rendered), "review": review,
    }


def print_date(series, posts):
    """(date or None, note or None) for one puzzle from all its posts.

    A review says when the puzzle was published. Failing that the hints went
    up on the print day, so the earliest post dates it -- unless that post is
    itself a review, which is written after entries close."""
    stated = {p["published"] for p in posts if p["published"]}
    if len(stated) > 1:
        return None, f"reviews state {len(stated)} dates"
    if stated:
        day = stated.pop()
    else:
        first = min(posts, key=lambda p: p["date"])
        if first["review"]:
            return None, None
        day = datetime.date.fromisoformat(first["date"])
    if day.weekday() not in PRINT_DAYS[series]:
        return None, f"{day:%A %d %B %Y} is no day the paper prints it"
    return day, None


def by_cadence(series, dates):
    """Date the numbers between two dated ones when the paper's print days
    between them are exactly as many as the numbers: the Saturday prize
    between Friday's and Monday's, or a run of Sundays no hints post dated.
    Anything else stays undated -- a Christmas with no paper is one day
    short, and a guess would date a whole run wrongly."""
    known = sorted((n, d) for n, d in dates.items() if d)
    filled = {}
    for (a, da), (b, db) in zip(known, known[1:]):
        if b - a < 2:
            continue
        days = [da + datetime.timedelta(days=k) for k in range(1, (db - da).days)]
        days = [d for d in days if d.weekday() in PRINT_DAYS[series]]
        if len(days) == b - a - 1:
            filled.update({n: days[n - a - 1] for n in range(a + 1, b) if not dates.get(n)})
    return filled


def rising(dates):
    """The numbers whose dates lie on the longest run of dates rising with
    the numbers. A date off it -- a review's "published on" typed a year out
    -- is the one that is wrong, since its neighbours agree with each other."""
    known = sorted((n, d) for n, d in dates.items() if d)
    tails, tail_at, back = [], [], [None] * len(known)
    for i, (_, d) in enumerate(known):
        k = bisect.bisect_left(tails, d)
        back[i] = tail_at[k - 1] if k else None
        if k == len(tails):
            tails.append(d)
            tail_at.append(i)
        else:
            tails[k], tail_at[k] = d, i
    keep, i = set(), tail_at[-1] if tail_at else None
    while i is not None:
        keep.add(known[i][0])
        i = back[i]
    return keep


def records(posts):
    """One record per (series, number): the fullest post's entries, its
    setter or another post's, and the print date its posts prove, or the
    paper's cadence proves between two that are.

    A post whose number is out of sequence with its post date carries a
    mistyped number, so it is kept out of that number's group and dates
    nothing; its record goes to the filer, which renumbers or refuses it."""
    groups = collections.defaultdict(list)
    for series in {p["series"] for p in posts}:
        mine = [p for p in posts if p["series"] == series]
        fits = file_blog_puzzles.sequence_window(mine)
        for p in mine:
            key = ((series, p["number"]) if fits(p["date"], p["number"])
                   else (series, p["number"], p["post_id"]))
            groups[key].append(p)
    notes, dates = [], collections.defaultdict(dict)
    for key, group in groups.items():
        if len(key) == 2:
            dates[key[0]][key[1]], note = print_date(key[0], group)
            if note:
                notes.append(f"{key[0]}-{key[1]}: {note}")
    for series, known in dates.items():
        keep = rising(known)
        for n, d in known.items():
            if d and n not in keep:
                notes.append(f"{series}-{n}: {d} is out of order with its neighbours' dates")
                known[n] = None
        known.update(by_cadence(series, known))
    for key, group in sorted(groups.items()):
        series, number = key[:2]
        best = max(group, key=lambda p: (len(p["entries"]), p["date"], p["post_id"]))
        setters = {p["setter"] for p in group if p["setter"]}
        rec = {k: best[k] for k in ("post_id", "date", "slug", "link", "series",
                                    "number", "title", "entries")}
        if best["unsplit"]:
            rec["unsplit"] = best["unsplit"]
        rec["setter"] = best["setter"] or (setters.pop() if len(setters) == 1 else None)
        day = dates[series].get(number) if len(key) == 2 else None
        rec["printed"] = day and day.isoformat()
        yield rec
    for note in sorted(notes):
        print(f"  date: {note}")


def plausible(rec):
    return PLAUSIBLE[0] <= len(rec["entries"]) <= PLAUSIBLE[1]


def run(write=True):
    cats = categories()
    posts = []
    for f in sorted(POSTS.glob("*.json")):
        p = read_post(json.loads(f.read_text(encoding="utf-8")), cats)
        if p:
            posts.append(p)
    by_series = collections.defaultdict(collections.Counter)
    checked = agreed = 0
    out = OUT.open("w", encoding="utf-8") if write else None
    for rec in records(posts):
        c = by_series[rec["series"]]
        c["puzzles"] += 1
        if not plausible(rec):
            continue
        c["plausible"] += 1
        c["dated"] += bool(rec["printed"])
        c["setter"] += bool(rec["setter"])
        leaders = tftt.leader_numbers(rec["entries"])
        for e in rec["entries"]:
            a = tftt.enum_agrees(e, leaders)
            if a is not None:
                checked += 1
                agreed += a
        if out:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if out:
        out.close()
    print(f"{len(posts)} post(s) read")
    print("BY SERIES  (puzzles / full clue list / dated / setter named)")
    for s, c in sorted(by_series.items()):
        print(f"  {s:<12} {c['puzzles']:>5} / {c['plausible']:>5} / "
              f"{c['dated']:>5} / {c['setter']:>5}")
    if checked:
        print(f"{agreed}/{checked} entries ({100.0 * agreed / checked:.1f}%) have the "
              f"answer length their own enumeration claims")
    if write:
        print(f"wrote {OUT}")
    return by_series


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true", help="report without writing")
    ap.add_argument("--show", type=int, help="parse one cached post id and print it")
    a = ap.parse_args()
    if a.show:
        post = json.loads((POSTS / f"{a.show}.json").read_text(encoding="utf-8"))
        print(json.dumps(read_post(post, categories()), ensure_ascii=False, indent=2,
                         default=str))
        return 0
    run(write=not a.status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
