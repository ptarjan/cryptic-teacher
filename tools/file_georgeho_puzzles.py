#!/usr/bin/env python3
"""File the puzzles only georgeho's ODbL clue database holds into puzzles/.

    python3 tools/file_georgeho_puzzles.py --rebuild   # backsolve the grids (bounded)
    python3 tools/file_georgeho_puzzles.py --dry-run   # count what it would file
    python3 tools/file_georgeho_puzzles.py             # file them

cryptics.georgeho.org scraped fifteensquared, times-xwd-times and bigdave44
up to 2023-07-15 (tools/corroborate.py indexes our ids out of it). Some of
those posts are gone or never parsed here, so the scrape is the only copy of
their clues and answers we have, and it has no grid. The grid is backsolved
from the clue numbers and answers by tools/times_grids.py, as for every blog,
and a puzzle is filed only when exactly one grid fits.

A puzzle is filed only when:

  - our corpus holds the numbers either side of it in its series, at most
    MAX_GAP away (a misread title, "Toughie 100001", has no neighbours);
  - its print date is the title's, or the one printing day its neighbours
    leave for it; otherwise it is not filed;
  - no reprinting series holds it, and the Telegraph's own bucket does not
    serve it (the blog filers' checks);
  - file_blog_puzzles.build accepts it: clues, counts, crossings.

A title that names no setter ("Toughie 1031") takes the one bigdave44's
cached posts on the same puzzle name ("Toughie No 1031 by Beam", its hints
post included), or the cached fifteensquared post at the same url's title.

georgeho is frozen, so this is a one-off run with no nightly step.
"""
import argparse
import collections
import datetime
import json
import re
import sqlite3
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import corroborate
import fetch_telegraph
import file_blog_puzzles as fbp
import parse_bigdave44
import puzzle_paths
import series as series_meta
import times_grids as tg
from fetch_puzzle import puzzle_path, read_puzzle_file, write_puzzle_file

TOOL = "tools/file_georgeho_puzzles.py"
CACHE = corroborate.GEORGEHO.parent / "blog"
#: The furthest a filed neighbour may sit from the number, either side.
MAX_GAP = 60
URL_DATE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")
ENUM = re.compile(r"\s*\(([\d,\-\s]+)\)\s*$")
VIA = "cryptics.georgeho.org (ODbL)"


def letters(answer):
    return re.sub(r"[^A-Z]", "", (answer or "").upper())


def count_of(answer):
    """The count a blogger's answer spells: "ROMAN WALL" (5,4), "NON-FATAL" (3-5)."""
    out, word = [], ""
    for ch in answer.upper().strip():
        if ch.isalpha():
            word += ch
        elif ch in " -" and word:
            out.append(f"{len(word)}{',' if ch == ' ' else '-'}")
            word = ""
    return "".join(out) + (str(len(word)) if word else "")


def lights_of(number, heading):
    """[(number, direction)] for "13a", "13/15a", "26,10" -> None for a cell
    that names no light. A number with no suffix takes `heading`, the
    direction the rows above it are in."""
    text = number.strip().lower()
    parts = re.findall(r"(\d+)\s*(a|ac|across|d|dn|down)?", text)
    if not parts or not re.fullmatch(r"[\d\s/,&adcrosnw]+", text):
        return None
    last = next((d for _, d in reversed(parts) if d), None) or heading
    out = []
    for n, d in parts:
        d = d or last
        out.append((int(n), "across" if d.startswith("a") else "down"))
    return out


def blog_answers(parsed=tg.PARSED):
    """{pid: {(number, direction): printed answer}} from our own parse of the
    timesforthetimes posts, the blog georgeho scraped the Times's from."""
    import file_times_puzzles as ftp
    out = {}
    if not parsed.exists():
        return out
    for line in parsed.open(encoding="utf-8"):
        r = json.loads(line)
        if not isinstance(r.get("number"), int):
            continue
        try:
            pid = f"{ftp.target(r)[0]}-{r['number']}"
        except ValueError:
            continue
        out[pid] = {(e["number"], e["direction"]): e.get("answer_spaced") or e["answer"]
                    for e in r["entries"] if e.get("answer")}
    return out


def whole(answer, count, fuller):
    """`answer`, or `fuller` where georgeho cut the answer off at a break
    (TAM for TAM-O'-SHANTER (3-1-7)) and our parse of the same post has it
    whole: starting with the cut letters and as long as the count."""
    total = sum(int(n) for n in re.findall(r"\d+", count or ""))
    if fuller and len(letters(answer)) < total == len(letters(fuller)) \
            and letters(fuller).startswith(letters(answer)):
        return fuller
    return answer


def record(pid, rows, posted=None, fuller=None):
    """A parsed record in the blog parsers' shape, or (None, why). The post's
    date is its url's, else georgeho's `posted` for the url. `fuller` is
    blog_answers()' for the post: answers georgeho cut off are taken whole
    from it."""
    by_url = collections.defaultdict(list)
    for row in rows:
        by_url[row[1]].append(row)
    url, rows = max(by_url.items(), key=lambda kv: len(kv[1]))
    m = URL_DATE.search(url)
    day = "-".join(m.groups()) if m else (posted or {}).get(url)
    if not day:
        return None, "no post date"
    series, number = series_meta.parse_id(pid)
    entries, unsplit, heading, last = [], [], "a", 0
    for _, _, name, cell, clue, answer in rows:
        if answer == corroborate.GEORGEHO_MISSING:
            continue                        # "See 4": its leader carries it
        first = re.match(r"\s*(\d+)", cell)
        if first and int(first.group(1)) < last and heading == "a":
            heading = "d"                   # the numbers start again: the downs
        lights = lights_of(cell, heading)
        if lights is None:
            return None, "a clue number it cannot read"
        heading, last = lights[0][1][0], lights[0][0]
        clue = re.sub(r"\s+", " ", clue or "").strip()
        enum = ENUM.search(clue)
        count = re.sub(r"\s", "", enum.group(1)) if enum else count_of(answer)
        if not enum:
            clue = f"{clue} ({count})"
        if len(lights) > 1:
            unsplit.append({"lights": [list(k) for k in lights], "answer": letters(answer),
                            "enumeration": count, "answer_printed": answer.upper(),
                            "clue": clue})
            continue
        (n, d), = lights
        answer = whole(answer, count, (fuller or {}).get((n, d)))
        entries.append({"number": n, "direction": d, "answer": letters(answer),
                        "answer_spaced": answer.upper(), "clue": clue,
                        "enumeration": count, "counted": not enum})
    rec = {"post_id": pid, "date": day, "slug": pid, "link": url,
           "series": series, "number": number, "title": rows[0][2],
           "setter": corroborate.blog_setter(rows[0][2]),
           "printed": (d.isoformat() if (d := corroborate.title_date(rows[0][2])) else None),
           "entries": entries}
    if unsplit:
        rec["unsplit"] = unsplit
    return rec, None


def held_numbers():
    """{series: sorted numbers our corpus holds}."""
    out = collections.defaultdict(list)
    for p in puzzle_paths.PUZZLE_DIR.glob("*/*/*.json"):
        try:
            s, n = series_meta.parse_id(p.stem)
        except (ValueError, TypeError):
            continue
        if isinstance(n, int):
            out[s].append(n)
    return {s: sorted(ns) for s, ns in out.items()}


def only_here():
    """{pid: rows} for every puzzle georgeho holds and our corpus does not."""
    db = corroborate._georgeho_index()
    if db is None:
        raise SystemExit(f"no {corroborate.GEORGEHO}: corroborate.py --download")
    out = collections.defaultdict(list)
    for row in db.execute("select pid, url, name, clue_number, clue, answer from clue "
                          "order by rowid"):
        out[row[0]].append(row)
    return {pid: rows for pid, rows in out.items()
            if not puzzle_path(*series_meta.parse_id(pid)).exists()}


def write_records():
    """Write CACHE/parsed.jsonl; return {why: count} for what it left out."""
    CACHE.mkdir(parents=True, exist_ok=True)
    left = collections.Counter()
    recs, here = [], only_here()
    src = sqlite3.connect(f"file:{corroborate.GEORGEHO}?mode=ro", uri=True)
    urls = {row[1] for rows in here.values() for row in rows}
    posted = {u: d for u, d in src.execute("select distinct source_url, puzzle_date from clues "
                                           "where source = 'times_xwd_times'") if u in urls}
    blog = blog_answers()
    for pid, rows in sorted(here.items()):
        if series_meta.parse_id(pid)[0] not in tg.SIZE:
            left["a series the grid rebuild has no size for"] += 1
            continue
        rec, why = record(pid, rows, posted, blog.get(pid))
        if why:
            left[why] += 1
        else:
            recs.append(rec)
    tmp = CACHE / "parsed.tmp"
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                   encoding="utf-8")
    tmp.replace(CACHE / "parsed.jsonl")
    print(f"{len(recs)} record(s) written to {CACHE / 'parsed.jsonl'}")
    for why, n in left.most_common():
        print(f"  left out {n}: {why}")
    return left


FIFTEENSQUARED = corroborate.GEORGEHO.parent.parent / "fifteensquared" / "posts"


def url_key(url):
    """A post's url without its scheme and host's www, for matching copies."""
    return re.sub(r"^https?://(?:www\.)?", "", url or "").rstrip("/")


def other_setters(wanted, bigdave=parse_bigdave44.POSTS, fifteensquared=FIFTEENSQUARED):
    """{(series, number): setter} for the records in `wanted` whose title
    names none, from the posts we cache: bigdave44's on the same puzzle, else
    the fifteensquared post at the record's url. Posts naming two setters
    name none."""
    keys = {(r["series"], r["number"]) for r in wanted}
    named = collections.defaultdict(set)
    if bigdave.is_dir():
        cats, numbers = parse_bigdave44.categories(), {str(n) for _, n in keys}
        for path in bigdave.glob("*.json"):
            post = json.loads(path.read_text(encoding="utf-8"))
            if not numbers & set(re.findall(r"\d+", post.get("slug", ""))):
                continue
            got = parse_bigdave44.named_setter(post, cats)
            if got and got[:2] in keys and got[2]:
                named[got[:2]].add(got[2])
    urls = {url_key(r["link"]): (r["series"], r["number"]) for r in wanted
            if (r["series"], r["number"]) not in named}
    if urls and fifteensquared.is_dir():
        for path in fifteensquared.glob("*.json"):
            post = json.loads(path.read_text(encoding="utf-8"))
            key = urls.get(url_key(post.get("link")))
            setter = key and corroborate.blog_setter(post.get("title", {}).get("rendered"))
            if setter:
                named[key].add(setter)
    return {k: v.pop() for k, v in named.items() if len(v) == 1}


def neighbours(held, series, number):
    """(lower, upper) numbers our corpus holds either side, each within MAX_GAP."""
    import bisect
    ns = held.get(series, [])
    i = bisect.bisect_left(ns, number)
    lo = ns[i - 1] if i and number - ns[i - 1] <= MAX_GAP else None
    hi = ns[i] if i < len(ns) and ns[i] - number <= MAX_GAP else None
    return lo, hi


def print_date(rec, lo, hi):
    """The title's date, else the one printing day the neighbours leave."""
    if rec.get("printed"):
        return datetime.date.fromisoformat(rec["printed"])
    days = {}
    for n in (lo, hi):
        d = read_puzzle_file(puzzle_path(rec["series"], n)).get("date")
        days[n] = d and datetime.date.fromisoformat(d)
    if not (days[lo] and days[hi]):
        return None
    seen = collections.Counter([days[lo].weekday(), days[hi].weekday()])
    if hi - lo <= 7:
        # The series' weekdays, from the neighbours' own neighbours.
        seen = collections.Counter()
        for n in range(max(1, lo - 7), hi + 8):
            p = puzzle_paths.find(series_meta.puzzle_id(rec["series"], n))
            if p and (d := read_puzzle_file(p).get("date")):
                seen[datetime.date.fromisoformat(d).weekday()] += 1
    # A weekday seen once, or under a quarter as often as the series' commonest,
    # is a holiday special (the Times's Boxing Day Jumbo on a Thursday, two
    # bank-holiday Monday Jumbos among sixteen Saturday ones), not a day the
    # series prints on.
    top = max(seen.values())
    weekdays = {w for w, k in seen.items() if k > 1 and 4 * k > top} or set(seen)
    slots, day = [], days[lo] + fbp.DAY
    while day < days[hi]:
        if day.weekday() in weekdays and (day.month, day.day) != (12, 25):
            slots.append(day)
        day += fbp.DAY
    return slots[rec["number"] - lo - 1] if len(slots) == hi - lo - 1 else None


def file_all(write=True):
    recs = {json.loads(line)["post_id"]: json.loads(line)
            for line in (CACHE / "parsed.jsonl").open(encoding="utf-8")}
    rows = [json.loads(line) for line in (CACHE / "grids.jsonl").open(encoding="utf-8")]
    held = held_numbers()
    reprints = fbp.reprinted_from()
    typed = fbp.typed_counts(recs.values())
    filed, skipped, compared = collections.Counter(), collections.Counter(), collections.Counter()
    unnamed = [recs[r["post_id"]] for r in rows
               if r["post_id"] in recs and not recs[r["post_id"]].get("setter")
               and not puzzle_path(recs[r["post_id"]]["series"], recs[r["post_id"]]["number"]).exists()]
    named = other_setters(unnamed)
    for row in rows:
        rec = recs.get(row["post_id"])
        if rec is None:
            skipped["no record"] += 1
            continue
        series, number = rec["series"], rec["number"]
        path = puzzle_path(series, number)
        if path.exists():
            # Filed meanwhile from another source: georgeho corroborates it.
            skipped["already filed"] += 1
            agree, differ = compare(read_puzzle_file(path), rec)
            compared["answers agree"] += agree
            if differ:
                compared["answers differ"] += len(differ)
                print(f"  {rec['post_id']}: georgeho differs at " + ", ".join(differ))
            continue
        by = fbp.reprinted_by(reprints, series, number)
        if by:
            skipped[f"{by} reprints it"] += 1
            continue
        if fetch_telegraph.served(series, number):
            skipped["the paper's own feed files it"] += 1
            continue
        lo, hi = neighbours(held, series, number)
        if lo is None or hi is None:
            skipped["no filed neighbour within reach: a misread number"] += 1
            continue
        date = print_date(rec, lo, hi)
        if date is None:
            skipped["no print date: neither the title nor its neighbours fix one"] += 1
            continue
        setter = (rec.get("setter") or named.get((series, number))
                  or series_meta.default_setter(series))
        puzzle, why = fbp.build(rec, row, series, date, setter, typed)
        if why:
            skipped[why] += 1
            continue
        counted = [f"{e['number']} {e['direction']}" for e in rec["entries"] if e.get("counted")]
        puzzle["solutions"]["check"] += (
            f"; clues and answers read from {VIA}'s copy of the post"
            + (", which drops the counts, so each count is read off the blogger's "
               "answer" if counted else ""))
        if write:
            try:
                write_puzzle_file(path, puzzle, generator=TOOL)
            except ValueError as e:
                skipped["refused by the write path: " + str(e).split(": ", 1)[-1].split()[0]] += 1
                continue
        filed[series] += 1
    print(f"{'filed' if write else 'would file'} {sum(filed.values())}: "
          + ", ".join(f"{s} {n}" for s, n in sorted(filed.items())))
    for why, n in skipped.most_common():
        print(f"  skipped {n}: {why}")
    if compared:
        print("  against the files already held: " + ", ".join(
            f"{n} {k}" for k, n in compared.items()))
    return filed, skipped


def compare(held, rec):
    """(answers agreeing, ["13 across HELD/GEORGEHO", ...]) between a held
    puzzle and georgeho's record of it, light by light. tools/cross_validate.py
    georgeho is the full comparison, clue words and counts included."""
    ours = {(e["number"], e["direction"]): e.get("solution") for e in held["entries"]}
    agree, differ = 0, []
    for e in rec["entries"]:
        mine = ours.get((e["number"], e["direction"]))
        if not mine or not e["answer"]:
            continue
        if mine == e["answer"]:
            agree += 1
        else:
            differ.append(f"{e['number']} {e['direction']} {mine}/{e['answer']}")
    return agree, differ


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rebuild", action="store_true",
                    help="write the records and backsolve their grids")
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    a = ap.parse_args(argv)
    if a.rebuild:
        write_records()
        # Smallest grids first: a 23x23 can spend its whole budget, minutes,
        # and a run cut short should have spent them on the many.
        held = {json.loads(line)["series"] for line in (CACHE / "parsed.jsonl").open()}
        for series in sorted(held, key=lambda s: (tg.SIZE[s], s)):
            print(f"\n{series}")
            r = tg.run(where=CACHE, series=series)
            if r:
                tg.report(r)
        return 0
    file_all(write=not a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
