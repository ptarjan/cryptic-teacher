#!/usr/bin/env python3
"""File the Observer's Azed from fifteensquared's write-ups.

    python3 tools/azed_puzzles.py                # parse, rebuild, file what is new
    python3 tools/azed_puzzles.py --limit 50     # the newest 50 not yet tried
    python3 tools/azed_puzzles.py --dry-run      # count, write no puzzle

The Azed is a 12x12 barred grid. The Observer's own pages serve it only as a
picture, but fifteensquared prints every clue beside its numbered answer
(tools/fetch_fifteensquared.py caches the posts), and in a barred grid where
every cell holds a letter the numbered answers pin the bars down
(tools/barred_grid.py), as they do for the Mephisto. A special whose answers
go into the grid altered fits no layout and is not filed.

The steps are tools/ft_puzzles.py's, each reading the one before off disk:
parse the cached posts into parsed.jsonl, rebuild bars into grids.jsonl, file
each grid into puzzles/.
"""
import argparse
import collections
import datetime
import html
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import fetch_fifteensquared as fsq
import file_blog_puzzles
import ft_puzzles
import parse_timesforthetimes as tftt
import times_grids as tg
from fetch_puzzle import correct_source_answers, puzzle_path, write_puzzle_file

SERIES = "azed"
#: The blog's category, and the label its records carry into times_grids.
CATEGORY = "Azed"
CACHE = fsq.CACHE / "azed"
GENERATOR = "tools/azed_puzzles.py"
#: Every Azed is set by Jonathan Crowther under this name.
SETTER = "Azed"

#: A 12x12 Azed has 30 to 44 lights; a post parsed outside this range lost or
#: invented a light.
PLAUSIBLE = (26, 48)

#: "Azed No. 2,751 Plain", "Azed 2,500 (Special)".
NUMBER = re.compile(r"\bazed\b\D{0,12}?(\d{1,2},\d{3}|\d{3,4})\b", re.IGNORECASE)
WEEK = datetime.timedelta(days=7)
#: Azed counts a multi-word answer in figures, "(10, 2 words)", which the FT's
#: reader does not take for an enumeration. The post is read with the bare
#: total and the clue given back its words in the form enumeration.WORDED
#: stores, "(10, two words)".
FIGURE_WORDS = re.compile(r"\(\s*(\d{1,2})\s*,\s*(\d)\s+words\s*\)")
SPELT = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


def clue_key(text):
    return re.sub(r"[^a-z]", "", (text or "").lower())


def post_number(title):
    m = NUMBER.search(title)
    return int(m.group(1).replace(",", "")) if m else None


def print_date(posted):
    """The Sunday an Azed was printed: the blog writes it up once its
    competition closes, on or after the next Sunday, so the print day is the
    last Sunday at least a week before the post."""
    day = datetime.date.fromisoformat(posted[:10]) - WEEK
    return day - datetime.timedelta(days=(day.weekday() + 1) % 7)


def print_dates(recs):
    """{number: print date}. Each post dates its own number (print_date), but
    a post written late or early misdates it, so each number takes the date
    most of its neighbours' posts put it at, counting a week a number."""
    own = {}
    for r in recs:
        own.setdefault(r["number"], print_date(r["date"]))
    out = {}
    for n in own:
        votes = collections.Counter(own[n + k] - k * WEEK for k in range(-3, 4) if n + k in own)
        best = max(votes.values())
        out[n] = own[n] if votes[own[n]] == best else votes.most_common(1)[0][0]
    return out


def parse_post(post, category_id):
    """One cached post to its record, or None if it is not an Azed."""
    if category_id not in post.get("categories", []):
        return None
    title = html.unescape(post.get("title", {}).get("rendered", ""))
    number = post_number(title)
    if number is None:
        return None
    rendered = post["content"]["rendered"]
    worded = {}
    for ln in tftt.lines(rendered):
        m = FIGURE_WORDS.search(ln or "")
        if m and int(m.group(2)) in SPELT:
            worded[clue_key(ln[:m.start()])] = (m.group(1), SPELT[int(m.group(2))])
    entries, unsplit = ft_puzzles.parse_entries(FIGURE_WORDS.sub(r"(\1)", rendered))
    for e in entries:
        m = tftt.ENUM.search(e.get("clue") or "")
        spelt = m and worded.get(clue_key(e["clue"][:m.start()]))
        if spelt and spelt[0] == m.group(1).strip():
            e["clue"] = f"{e['clue'][:m.start()].rstrip()} ({spelt[0]}, {spelt[1]} words)"
            e["enumeration"] = spelt[0]
    rec = {
        "post_id": f"fifteensquared-{post['id']}",
        "date": post["date"][:10], "slug": post.get("slug", ""),
        "link": post.get("link"), "series": CATEGORY,
        "number": number, "title": title, "setter": SETTER, "entries": entries,
    }
    if unsplit:
        rec["unsplit"] = unsplit
    return rec


def parse(write=True):
    """Every cached Azed post to parsed.jsonl. Returns (records, implausible)."""
    cat = fsq.cached_categories()[CATEGORY]
    recs, odd = [], []
    for f in sorted(fsq.POSTS.glob("*.json")):
        rec = parse_post(json.loads(f.read_text(encoding="utf-8")), cat)
        if rec is None:
            continue
        lo, hi = PLAUSIBLE
        (recs if lo <= len(rec["entries"]) <= hi else odd).append(rec)
    if write:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = CACHE / "parsed.tmp"
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                       encoding="utf-8")
        tmp.replace(CACHE / "parsed.jsonl")
    return recs, odd


def file(write=True, limit=None):
    """File every grid row not yet in puzzles/, newest first; (filed, skipped)."""
    recs = {r["post_id"]: r for r in map(json.loads, (CACHE / "parsed.jsonl").open(encoding="utf-8"))}
    rows = [json.loads(line) for line in (CACHE / "grids.jsonl").open(encoding="utf-8")]
    rows.sort(key=lambda r: (r["date"], r["post_id"]), reverse=True)
    claims = collections.Counter(r["number"] for r in recs.values())
    dates = print_dates(list(recs.values()))
    skipped, filed = collections.Counter(), []
    for row in rows:
        number = row.get("number")
        rec = recs.get(row["post_id"])
        if rec is None:
            skipped["no longer parsed"] += 1
        elif claims[number] > 1:
            skipped["number claimed twice"] += 1
        elif puzzle_path(SERIES, number).exists():
            skipped["already filed"] += 1
        elif limit is not None and len(filed) >= limit:
            skipped["past --limit"] += 1
        else:
            puzzle, why = file_blog_puzzles.build(rec, row, SERIES, dates[number], SETTER)
            if why:
                skipped[why] += 1
                continue
            if write:
                try:
                    correct_source_answers(puzzle["id"], puzzle["entries"])
                    write_puzzle_file(puzzle_path(SERIES, number), puzzle, generator=GENERATOR)
                except ValueError as e:     # puzzle_integrity's write check
                    skipped[f"refused on write: {str(e).split(': ', 1)[-1][:120]}"] += 1
                    continue
            filed.append(puzzle["id"])
    return filed, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, help="rebuild and file at most N puzzles")
    ap.add_argument("--dry-run", action="store_true", help="file nothing")
    a = ap.parse_args(argv)
    recs, odd = parse()
    print(f"parsed {len(recs)} Azed post(s); {len(odd)} more with an implausible light count")
    r = tg.run(a.limit, CATEGORY, where=CACHE)
    if r:
        tg.report(r)
    filed, skipped = file(write=not a.dry_run, limit=a.limit)
    print(f"{'would file' if a.dry_run else 'filed'} {len(filed)}: {' '.join(filed[:20])}"
          + (" ..." if len(filed) > 20 else ""))
    for why, n in skipped.most_common():
        print(f"  skipped {n}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
