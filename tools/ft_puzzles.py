#!/usr/bin/env python3
"""File the Financial Times cryptic from fifteensquared's write-ups.

    python3 tools/ft_puzzles.py                  # parse, rebuild, file what is new
    python3 tools/ft_puzzles.py --limit 50       # the newest 50 not yet tried
    python3 tools/ft_puzzles.py --dry-run        # count, write no puzzle

The FT's own site answers a script with a Cloudflare challenge, so the grid is
rebuilt from the clue numbers, the way the Times' is: fifteensquared prints
every FT puzzle's clues, numbers and answers (tools/fetch_fifteensquared.py
caches them), numbering is a function of the black squares, and
tools/times_grids.py's search runs it backwards. What files is held to
tools/file_times_puzzles.py's checks, by its own build().

Three steps, each reading the one before off disk, so a run killed anywhere
resumes: parse the cached posts into parsed.jsonl, rebuild grids into
grids.jsonl (newest first; every attempt logged, so a failure is not ground
again), file each grid into puzzles/.

Every era of the blog's markup is one reader. The post is flattened to lines,
and a light is the run of lines from its number to the next number: its clue
is the line that ends in an enumeration, and its answer the line whose capitals
that enumeration counts, in whichever order the blogger printed them.
"""
import argparse
import collections
import datetime
import html
import itertools
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import fetch_fifteensquared as fsq
import file_times_puzzles as ftp
import parse_timesforthetimes as tftt
import times_grids as tg
from fetch_puzzle import puzzle_path, read_puzzle_file, write_puzzle_file

SERIES = "ftcryptic"
#: The blog's category, and the label its records carry into times_grids.
CATEGORY = "FT"
CACHE = fsq.CACHE / "ft"
GENERATOR = "tools/ft_puzzles.py"

#: The FT's weekday cryptic runs 15x15 with 26 to 32 lights; a post parsed
#: outside this range lost or invented a light.
PLAUSIBLE = (22, 34)

#: Title shapes: "Financial Times 18,489 by XELA", "FT 16,342 / Mudd",
#: "Financial Times 18480 Mudd". The FT Weekend's Sunday and Jumbo puzzles are
#: their own numbering and sit in their own categories.
NUMBER = re.compile(r"\b(\d{1,2},\d{3}|\d{4,5})\b")
OTHER_PUZZLE = re.compile(r"\b(?:sunday|jumbo|weekend|polymath|genius)\b", re.IGNORECASE)
SETTER = re.compile(r"\d[\s\-–—:/]*(?:by|from|/|[\-–—:])?\s*([A-Za-z][\w'’. ]*?)\s*"
                    r"(?:[\-–—:(]|$)")


def post_number(title):
    m = NUMBER.search(title)
    return int(m.group(1).replace(",", "")) if m else None


def post_setter(title):
    """The setter the title names, in the case the FT prints it: the blog
    capitalises some names (XELA) and not others (Julius)."""
    m = NUMBER.search(title)
    if not m:
        return None
    s = SETTER.match(title, m.end() - 1)
    name = s and s.group(1).strip(" .")
    if not name or name.lower() in ("by", "prize"):
        return None
    return name.title() if name.isupper() else name


def heading(ln):
    m = tftt.HEADING.match(ln)
    return m.group(1).lower() if m else None


def head_of(ln, direction, last):
    """(lights, rest) when this line opens a new light, else None.

    A light opens on its number, alone or followed by its clue or answer, and
    numbers rise within a direction: a number at or below the last one is the
    blogger's prose ("1 SEN = 1/100th of a yen"), not a light.
    """
    ln = re.sub(r"^\s*\*+", "", ln)
    m = tftt.LINK_HEAD.match(ln)
    if m:
        lights = tftt.link_lights(m, direction)
        rest = tftt.LINK_TAIL.sub("", ln[m.end():]).strip()
    else:
        m = tftt.NUMBERED.match(ln)
        if not m:
            return None
        rest = m.group(2).strip()
        way = direction
        suffix = tftt.BARE_SUFFIX.match(rest)
        if suffix:
            rest, way = "", tftt.DIRECTION_OF[suffix.group(1).lower()]
        lights = [(int(m.group(1)), way)]
    if not lights or lights[0][0] <= last or lights[0][0] > 40:
        return None
    if rest and not (tftt.ENUM.search(rest) or tftt.CONTINUATION.match(rest)
                     or tftt.answer_line(rest)):
        return None
    return lights, rest


def read_light(lines):
    """(clue, enumeration, printed answer) out of one light's lines."""
    clue = enum = None
    for ln in lines:
        e = tftt.ENUM.search(ln)
        if e or tftt.CONTINUATION.match(ln):
            clue, enum = ln, e and e.group(1).strip()
            break
    answer = None
    for ln in lines:
        if ln is clue:
            continue
        printed = (tftt.answer_by_enum(ln, enum) if enum else None) or tftt.answer_line(ln)
        if printed and (enum is None or tftt.enum_fits(printed, enum)):
            answer = printed
            break
    return clue, enum, answer


def complete(lines):
    """Has this light its clue and its answer? A "See N" has no answer."""
    clue, _, answer = read_light(lines)
    return bool(clue) and (answer is not None or bool(tftt.CONTINUATION.match(clue)))


def parse_entries(rendered):
    """(entries, unsplit) in the times_grids record shape."""
    direction, last, lights = None, 0, None
    segments = []
    for ln in tftt.lines(rendered):
        if not ln:
            continue
        way = heading(ln)
        if way:
            direction, last = way, 0
            continue
        if direction is None:
            continue
        head = head_of(ln, direction, last)
        # A clue can open with a number, "16 9 church in Leicester", so a
        # number with text after it only opens a light once the one before it
        # has its clue and its answer. A bare number cell always does.
        if head and head[1] and segments and not complete(segments[-1][1]):
            head = None
        if head:
            lights, rest = head
            last = lights[0][0]
            segments.append((lights, [rest] if rest else []))
        elif segments:
            segments[-1][1].append(ln)
    entries, unsplit = [], []
    for lights, lines in segments:
        clue, enum, printed = read_light(lines)
        if printed is None:
            continue
        pieces = ([(lights[0], re.sub(r"[^A-Z]", "", printed))] if len(lights) == 1
                  else tftt.link_pieces(lights, printed, enum))
        if pieces is None:
            unsplit.append({"lights": [list(x) for x in lights],
                            "answer_printed": printed, "clue": clue,
                            "enumeration": enum})
            continue
        leader = pieces[0][0][0]
        for i, ((n, d), letters) in enumerate(pieces):
            entries.append({
                "number": n, "direction": d, "answer": letters,
                "clue": clue if i == 0 else f"See {leader}",
                "enumeration": enum if i == 0 else None,
            })
    tftt.one_entry_per_light(entries)
    tftt.trim_continuations(entries)
    return entries, unsplit


def parse_post(post, category_id):
    """One cached post to its record, or None if it is not a weekday FT."""
    if category_id not in post.get("categories", []):
        return None
    title = html.unescape(post.get("title", {}).get("rendered", ""))
    if OTHER_PUZZLE.search(title):
        return None
    entries, unsplit = parse_entries(post["content"]["rendered"])
    rec = {
        # Qualified, so nothing the Times keys by its blog's post ids (its
        # settled answers, its misspellings) can land on an FT post.
        "post_id": f"fifteensquared-{post['id']}",
        "date": post["date"][:10], "slug": post.get("slug", ""),
        "link": post.get("link"), "series": CATEGORY,
        "number": post_number(title), "title": title,
        "setter": post_setter(title), "entries": entries,
    }
    if unsplit:
        rec["unsplit"] = unsplit
    return rec


# ------------------------------------------------------------------ parse

def parse(write=True):
    """Every cached FT post to parsed.jsonl. Returns (records, implausible)."""
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


# ------------------------------------------------------------------ grids

#: The most splits of a record's linked answers solve() tries.
MAX_SPLITS = 16


def splits(group):
    """Every way to share a linked answer's words out among its lights, in
    order and at word breaks: [[(light, letters), ...], ...]."""
    words = tftt.answer_words(group["answer_printed"])
    lights = [tuple(x) for x in group["lights"]]
    out = []
    for cuts in itertools.combinations(range(1, len(words)), len(lights) - 1):
        bounds = (0, *cuts, len(words))
        out.append([(light, "".join(words[a:b]))
                    for light, a, b in zip(lights, bounds, bounds[1:])])
    return out


def with_split(rec, choice):
    """rec with one split of each linked answer the blog left unsplit."""
    entries = list(rec["entries"])
    for group, pieces in zip(rec["unsplit"], choice):
        leader = pieces[0][0][0]
        for i, ((n, d), letters) in enumerate(pieces):
            entries.append({"number": n, "direction": d, "answer": letters,
                            "clue": group["clue"] if i == 0 else f"See {leader}",
                            "enumeration": group["enumeration"] if i == 0 else None})
    return dict(rec, entries=entries)


def solve(rec, max_nodes=tg.DEFAULT_MAX_NODES):
    """times_grids.solve, after sharing out any linked answer the post prints
    whole: every split at a word break is rebuilt, and one split landing on
    exactly one grid is the split. The chosen split is written into rec's
    entries, which is what the grid row and the filer read."""
    if not rec.get("unsplit"):
        return tg.solve(rec, max_nodes=max_nodes)
    choices = list(itertools.islice(
        itertools.product(*(splits(g) for g in rec["unsplit"])), MAX_SPLITS + 1))
    if len(choices) > MAX_SPLITS:
        return [], "rejected: too many ways to split its linked answers"
    found = []
    for choice in choices:
        grids, why = tg.solve(with_split(rec, choice), max_nodes=max_nodes)
        if grids:
            found.append((choice, grids, why))
    if len(found) != 1 or len(found[0][1]) != 1:
        return [], ("no grid fits any split of its linked answers" if not found
                    else f"shortlist: {len(found)} splits of its linked answers fit")
    choice, grids, why = found[0]
    rec["entries"] = with_split(rec, choice)["entries"]
    return grids, why + ", linked answer split by the grid"


def grids(limit=None, max_nodes=tg.DEFAULT_MAX_NODES):
    return tg.run(limit, CATEGORY, max_nodes=max_nodes, where=CACHE, solver=solve)


# ------------------------------------------------------------------ file

def printing_day(day):
    """Does the FT print a crossword on `day`? Monday to Saturday, not
    Christmas Day."""
    return day.weekday() != ftp.SUNDAY and (day.month, day.day) != (12, 25)


def last_printing_day(day):
    while not printing_day(day):
        day -= ftp.DAY
    return day


def print_dates(recs):
    """{number: date or None}.

    A puzzle is blogged on the day it is printed or later, never earlier, so
    one blogged no earlier than the number after it was blogged late -- the
    Saturday prize, after entries close -- and was printed the printing day
    before that number's post. Every other puzzle's date is its post's.

    The numbering is not one number per printing day for good (a week can
    carry an extra one), so nothing is counted across more than one step.
    A date that does not rise strictly between its neighbours' is dropped
    and refitted: each run of dropped numbers takes the printing days between
    its dated neighbours nearest its own posts, rising with the numbers, and
    a run with fewer days than numbers takes in a neighbour each side until
    it fits, none after its own post. So every number is dated, some a few
    days out."""
    posted = {}
    for r in recs:
        if r.get("number"):
            day = last_printing_day(datetime.date.fromisoformat(r["date"]))
            posted[r["number"]] = min(day, posted.get(r["number"], day))
    guess = {}
    for n, day in posted.items():
        after = posted.get(n + 1)
        guess[n] = (last_printing_day(after - ftp.DAY)
                    if after is not None and day >= after else day)
    order = sorted(guess)
    dates, last = {}, None
    for i, n in enumerate(order):
        nxt = guess[order[i + 1]] if i + 1 < len(order) else None
        day = guess[n]
        ok = (last is None or day > last) and (nxt is None or day < nxt)
        dates[n] = day if ok else None
        last = day if ok else last
    i = 0
    while i < len(order):
        if dates[order[i]]:
            i += 1
            continue
        lo = hi = i
        while hi + 1 < len(order) and not dates[order[hi + 1]]:
            hi += 1
        while True:
            run = order[lo:hi + 1]
            fit = nearest(between(dates[order[lo - 1]] if lo else None,
                                  dates[order[hi + 1]] if hi + 1 < len(order) else None,
                                  [guess[n] for n in run]),
                          [guess[n] for n in run], [posted[n] for n in run])
            if fit:
                break
            lo, hi = max(lo - 1, 0), min(hi + 1, len(order) - 1)
        dates.update(zip(run, fit))
        i = hi + 1
    return dates


def between(after, before, guesses):
    """The printing days strictly between two dates; an open end reaches a
    month past the farthest guess."""
    day = (after or min(guesses) - 31 * ftp.DAY) + ftp.DAY
    end = before or max(guesses) + 31 * ftp.DAY
    out = []
    while day < end:
        if printing_day(day):
            out.append(day)
        day += ftp.DAY
    return out


def nearest(slots, guesses, latest):
    """One slot per guess, rising with the guesses, none after its latest, the
    total days off the guesses least; None when no such choice exists."""
    inf = float("inf")
    # cost[i][j]: the first i guesses placed in the first j slots.
    cost = [[0] * (len(slots) + 1)] + [[inf] * (len(slots) + 1) for _ in guesses]
    for i, g in enumerate(guesses, 1):
        for j in range(i, len(slots) + 1):
            cost[i][j] = min(cost[i][j - 1],
                             cost[i - 1][j - 1] + abs((slots[j - 1] - g).days)
                             if slots[j - 1] <= latest[i - 1] else inf)
    if cost[-1][-1] == inf:
        return None
    out, j = [], len(slots)
    for i in range(len(guesses), 0, -1):
        while cost[i][j] == cost[i][j - 1]:
            j -= 1
        out.append(slots[j - 1])
        j -= 1
    return out[::-1]


def split_by(rec, grid):
    """rec with its linked answers shared out as the grid's lights have them."""
    if not rec.get("unsplit"):
        return rec
    for choice in itertools.product(*(splits(g) for g in rec["unsplit"])):
        whole = with_split(rec, choice)
        if tg.answers_fit(grid, whole):
            return whole
    return rec


def file(write=True, limit=None):
    """File every grid row not yet in puzzles/, newest first; (filed, skipped)."""
    recs = {r["post_id"]: r for r in map(json.loads, (CACHE / "parsed.jsonl").open(encoding="utf-8"))}
    rows = [json.loads(line) for line in (CACHE / "grids.jsonl").open(encoding="utf-8")]
    rows.sort(key=lambda r: (r["date"], r["post_id"]), reverse=True)
    fits = ftp.sequence_window([r for r in recs.values() if r.get("number")])
    dates = print_dates([r for r in recs.values()
                         if r.get("number") and fits(r["date"], r["number"])])
    claims = collections.Counter(r["number"] for r in recs.values() if r.get("number"))
    skipped, filed = collections.Counter(), []
    for row in rows:
        if limit is not None and len(filed) >= limit:
            break
        number = row.get("number")
        if not number:
            skipped["no puzzle number"] += 1
        elif not fits(row["date"], number):
            skipped["number out of sequence"] += 1
        elif claims[number] > 1:
            skipped["number claimed twice"] += 1
        elif puzzle_path(SERIES, number).exists():
            skipped["already filed"] += 1
            # Only the date is rewritten: it is fitted to every post, and a
            # post arriving later can move it.
            held = read_puzzle_file(puzzle_path(SERIES, number))
            day = dates.get(number)
            ms = day and ftp.file_blog_puzzles.epoch_ms(day)
            if ms and held.get("date") != ms:
                skipped["already filed, redated"] += 1
                if write:
                    write_puzzle_file(puzzle_path(SERIES, number), {**held, "date": ms})
        else:
            rec = split_by(recs[row["post_id"]], row["grid"])
            puzzle, why = ftp.build(rec, row, SERIES, dates.get(number))
            if why:
                skipped[why] += 1
                continue
            if write:
                try:
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
    ap.add_argument("--max-nodes", type=int, default=tg.DEFAULT_MAX_NODES)
    a = ap.parse_args(argv)
    recs, odd = parse()
    print(f"parsed {len(recs)} FT post(s); {len(odd)} more with an implausible light count")
    r = grids(a.limit, a.max_nodes)
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
