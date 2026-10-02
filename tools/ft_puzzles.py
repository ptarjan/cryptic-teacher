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
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import fetch_fifteensquared as fsq
import file_blog_puzzles
import file_times_puzzles as ftp
import parse_timesforthetimes as tftt
import puzzle_integrity
import series as series_meta
import times_grids as tg
from fetch_puzzle import correct_source_answers, puzzle_files, puzzle_path, read_puzzle_file, write_puzzle_file

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
#: A hyphen between letters is part of the name ("Glow-worm"); any other
#: closes it ("Mudd - Ups and downs", "Sat 27-June-2015"), as does a double space.
SETTER = re.compile(r"\d[\s\-–—:/]*(?:by|from|/|[\-–—:])?\s*"
                    r"([A-Za-z](?:[\w'’. ]|(?<=[A-Za-z])-(?=[A-Za-z]))*?)\s*"
                    r"(?:(?<![A-Za-z])-|-(?![A-Za-z])|[–—:(]|\s{2}|$)")


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


def tidy(ln):
    """tftt.tidy for a fifteensquared FT post: its bloggers' brackets add
    their own words to an elliptical clue ("Having paid, he [he] recovers"),
    so a bracket's words stay as they are, never merged into the clue."""
    return tftt.tidy(ln, link_words=False)


def heading(ln):
    m = tftt.HEADING.match(ln)
    return m.group(1).lower() if m else None


#: Wordplay, not a clue: a capitalised word of three letters or more, or the
#: blog's working marks. A post that prints its clues without their counts
#: is read by telling the clue from the wordplay row beside it.
WORKING = re.compile(r"\b[A-Z]{3,}\b|[=+*<>\[\]{}]")
MARKS = re.compile(r"[=+*<>\[\]{}]")
#: The blogger's verdict on a clue, never the clue: "Double definition".
VERDICT = re.compile(r"^\W*(?:double|triple|dd\b|cd\b|cryptic|charade|anagram|hidden|"
                     r"reversal|homophone|&\s*lit|see\b|a (?:double|cryptic)|vote\W*$)", re.IGNORECASE)
#: A line that is all answer: capitals, spaces, hyphens, apostrophes.
WHOLE_ANSWER = re.compile(r"[A-Z][A-Z'’\-–\s]*[A-Z]!?")
#: An answer the wordplay ends on: "... + tub (clumsy one) = STUB".
EQUALS_ANSWER = re.compile(r"=\s*([A-Z][A-Z'’\-\s]*[A-Z])(?![a-z])")


def enum_of(printed):
    """The enumeration a printed answer spells: "SEA PERCH" is 3,5."""
    out = ""
    for tok in re.findall(r"[^\s\-–]+|[\-–]+|\s+", printed.strip()):
        if tok[0] in "-–":
            out += "-"
        elif tok.isspace():
            out += ","
        else:
            n = len(re.sub(r"[^A-Za-z]", "", tok))
            out += str(n) if n else ""
    return re.sub(r"^[,\-]+|[,\-]+$", "", re.sub(r"([,\-])[,\-]+", r"\1", out)) or None


def clue_like(ln, strict):
    """Could this line be a clue printed without its count? `strict` also
    turns away a capitalised word, for a line that could be the wordplay."""
    return (bool(re.search(r"[a-z]", ln)) and not VERDICT.match(ln)
            and not (WORKING if strict else MARKS).search(ln))


def head_of(ln, direction, last, bare=False):
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
        glued = None if suffix else tftt.GLUED_SUFFIX.match(ln)
        if suffix:
            rest, way = "", tftt.DIRECTION_OF[suffix.group(1).lower()]
        elif glued:
            rest, way = ln[glued.end():].strip(), tftt.DIRECTION_OF[glued.group(1).lower()]
        lights = [(int(m.group(1)), way)]
    if not lights or lights[0][0] <= last or lights[0][0] > 40:
        return None
    if rest and not (tftt.ENUM.search(rest) or tftt.CONTINUATION.match(rest)
                     or tftt.answer_line(rest) or (bare and clue_like(rest, False))):
        return None
    return lights, rest


def answer_by_count(lines, enum, clue):
    """The answer a line spells to the count, when nothing marks it as the
    answer: a whole line "Facial" under (6), or "... = STUB" under (4)."""
    counts = [int(n) for n in re.findall(r"\d+", enum)]
    for ln in lines:
        if ln is clue:
            continue
        if re.fullmatch(r"[A-Za-z'’\-–\s]+[.!?]?", ln.strip()):
            words = re.findall(r"[A-Za-z'’]+", ln)
            if (len(words) <= len(counts)
                    and sum(len(re.sub(r"[^A-Za-z]", "", w)) for w in words) == sum(counts)):
                return " ".join(w.upper() for w in words)
        for m in reversed(list(EQUALS_ANSWER.finditer(ln))):
            if tftt.enum_fits(m.group(1), enum):
                return " ".join(m.group(1).split())
    return None


def read_bare(lines):
    """(clue, enumeration, printed answer) for a light whose clue has no count:
    the answer is a line of capitals alone, the clue the line before it, or
    else the line after it when the wordplay follows that. The count is the
    one the answer spells, written onto the clue as the blog would have."""
    for i, ln in enumerate(lines):
        if WHOLE_ANSWER.fullmatch(ln.strip()):
            printed = " ".join(ln.split())
            break
    else:
        return None, None, None
    enum = enum_of(printed)
    clue = None
    if i > 0 and clue_like(lines[i - 1], False):
        clue = lines[i - 1]
    elif i + 2 < len(lines) and clue_like(lines[i + 1], True):
        clue = lines[i + 1]
    if clue and enum:
        clue = f"{clue.strip()} ({enum})"
    return clue, enum, printed


def read_light(lines, bare=False):
    """(clue, enumeration, printed answer) out of one light's lines, the clue
    tidied of the blogger's slashes, asides and stray spaces (tidy)."""
    clue, enum, answer = (read_bare if bare else read_counted)(lines)
    return (tidy(clue) if clue else clue), enum, answer


def read_counted(lines):
    """read_light() for a light whose clue prints its count."""
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
    if answer is None and enum:
        answer = answer_by_count(lines, enum, clue)
    return clue, enum, answer


def complete(lines, bare=False):
    """Has this light its clue and its answer? A "See N" has no answer."""
    clue, _, answer = read_light(lines, bare)
    return bool(clue) and (answer is not None or bool(tftt.CONTINUATION.match(clue)))


def clued(entries):
    return sum(bool(e.get("clue")) for e in entries)


#: A table post that shows each clue only as its answer's hover text,
#: '<span title="Shrink's terms of employment (8)"><strong>CONTRACT', beside
#: a "vote" link: the title is the clue, and becomes a line of its own after
#: what the span wraps (the light's number).
TITLED_CLUE = re.compile(r'<span\s+title="([^"<>]*\(\s*\d[^"<>]*\))"\s*>(.*?)</span>',
                         re.IGNORECASE | re.DOTALL)


def parse_entries(rendered):
    """(entries, unsplit) in the times_grids record shape. A post that prints
    its clues without their counts is read again for that layout, and that
    reading kept when it finds more clues."""
    rendered = TITLED_CLUE.sub(lambda m: f"{m.group(2)}<br />{m.group(1)}<br />", rendered)
    got = read_entries(rendered)
    if clued(got[0]) < 0.9 * len(got[0]) or not got[0]:
        bare = read_entries(rendered, bare=True)
        if clued(bare[0]) > clued(got[0]):
            return bare
    return got


def read_entries(rendered, bare=False):
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
        head = head_of(ln, direction, last, bare)
        # A clue can open with a number, "16 9 church in Leicester", so a
        # number with text after it only opens a light once the one before it
        # has its clue and its answer. A bare number cell always does.
        if head and head[1] and segments and not complete(segments[-1][1], bare):
            head = None
        if head:
            lights, rest = head
            last = lights[0][0]
            segments.append((lights, [rest] if rest else []))
        elif segments:
            segments[-1][1].append(ln)
    entries, unsplit = [], []
    for lights, lines in segments:
        clue, enum, printed = read_light(lines, bare)
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

def grids(limit=None, max_nodes=tg.DEFAULT_MAX_NODES):
    return tg.run(limit, CATEGORY, max_nodes=max_nodes, where=CACHE)


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
    return file_blog_puzzles.fit_undated(dates, guess, posted, printing_day)


def held_by_content(series=SERIES):
    """content_hash -> id of every puzzle of `series` on disk. The FT reprints
    an old puzzle under a new number, and the blog writes the reprint up as if
    it were new; puzzle_integrity calls the second copy a DUPLICATE."""
    prefix = puzzle_path(series, 0).name.rsplit("-", 1)[0] + "-"
    held = {}
    for path in puzzle_files():
        if path.name.startswith(prefix):
            p = read_puzzle_file(path)
            held.setdefault(puzzle_integrity.content_hash(p), p["id"])
    return held


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
    on_disk = None  # read only once a puzzle is built, which most nights none is
    for row in rows:
        number = row.get("number")
        if not number:
            skipped["no puzzle number"] += 1
        elif not fits(row["date"], number):
            skipped["number out of sequence"] += 1
        elif claims[number] > 1:
            skipped["number claimed twice"] += 1
        elif puzzle_path(SERIES, number).exists():
            skipped["already filed"] += 1
            # Only a file this tool wrote is rewritten, and only its date and
            # its tidied clues: the date is fitted to every post, and a post
            # arriving later can move it. A file from the FT's PDF is dated
            # by the FT's own crossword page, which no post fit overrides.
            held = read_puzzle_file(puzzle_path(SERIES, number))
            if (held.get("source") or {}).get("acquiredBy") != GENERATOR:
                continue
            fix = {}
            day = dates.get(number)
            if day and series_meta.puzzle_day(held) != day:
                skipped["already filed, redated"] += 1
                fix["date"] = day.isoformat()
            # What a parser fix tidies out of the clues reaches the files
            # written before it (file_blog_puzzles.retext).
            tidied, n = file_blog_puzzles.retext(held, tidy)
            if n:
                skipped["already filed, clues tidied"] += 1
                fix["entries"] = tidied["entries"]
            if fix and write:
                write_puzzle_file(puzzle_path(SERIES, number), {**held, **fix})
        elif limit is not None and len(filed) >= limit:
            skipped["past --limit"] += 1
        else:
            puzzle, why = ftp.build(recs[row["post_id"]], row, SERIES, dates.get(number))
            if why:
                skipped[why] += 1
                continue
            if on_disk is None:
                on_disk = held_by_content()
            key = puzzle_integrity.content_hash(puzzle)
            if key in on_disk:
                skipped[f"reprint of {on_disk[key]}"] += 1
                continue
            if write:
                try:
                    correct_source_answers(puzzle["id"], puzzle["entries"])
                    write_puzzle_file(puzzle_path(SERIES, number), puzzle, generator=GENERATOR)
                except ValueError as e:     # puzzle_integrity's write check
                    skipped[f"refused on write: {str(e).split(': ', 1)[-1][:120]}"] += 1
                    continue
            on_disk[key] = puzzle["id"]
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
