#!/usr/bin/env python3
"""File Times and Telegraph puzzles we lack from the Cryptonite clue dataset.

    python3 tools/file_cryptonite.py DATA_DIR --dry-run          # count, write nothing
    python3 tools/file_cryptonite.py DATA_DIR --pilot 20         # a few of each gap
    python3 tools/file_cryptonite.py DATA_DIR                    # file every one that passes
    python3 tools/file_cryptonite.py DATA_DIR --validate         # check the rules on held puzzles

DATA_DIR holds cryptonite-{train,val,test}.jsonl, unzipped from
github.com/aviaefrat/cryptonite data/cryptonite-official-split.zip (see
docs/missing-puzzle-sources.md, "1. Cryptonite dataset"). It is downloaded data:
read it, never run anything from it.

One dataset row is one clue: paper, print date, number, direction, clue and
answer, both lowercased. No grid, no puzzle number. A puzzle files only when
all of this holds, else it is skipped and counted under the reason:

  * Bucketed by paper and date. The Telegraph rows carry no sub-publisher, so
    a Sunday is the Sunday Telegraph and any other day the daily. A Times row
    labelled "" counts only where no labelled row shares its date (the blank
    label is mostly the Saturday Jumbo beside the daily). Quick-flagged rows are
    dropped; a date whose remaining rows repeat a (number, direction) holds two
    cryptics (the Saturday Jumbo, or the Toughie beside the back-page puzzle),
    which numbering alone cannot share out, so it is skipped.
  * No puzzle held for that date, and none for the number it maps to.
  * The number is forced (number_for): between the nearest held puzzles either
    side, the printing days are at least the dataset's own dates and at most
    every day the paper could print (Monday to Saturday bar Christmas Day for a
    daily, every Sunday for a Sunday paper). The number counts only when every
    calendar between those bounds that fits the held numbers gives the same
    one. No interpolation past the last held puzzle, no guess.
  * One grid (place): the answers written into a 15x15 half-turn-symmetric
    grid whose numbering prints exactly these lights, every crossing agreeing,
    and the search finishing with exactly one such grid.
  * file_blog_puzzles.build accepts it (lights, enumerations, word breaks), and
    write_puzzle_file's checks pass.

Clue case is restored by rule (recase): the first letter of each sentence, "I"
standing alone, and a word our own Times/Telegraph clues capitalise mid-clue at
least CAPITAL_SHARE of the time over CAPITAL_MIN uses. Anything else stays
lowercase. Provenance says where it came from: source.url is the dataset,
acquiredBy this tool (provenance.ACQUIRED_BY says the text was lowercased),
retrievedFrom "dataset", gridOrigin "reconstructed". The answers are the
paper's own (the authors scraped its solutions), so their origin is published.

Filed puzzles carry every answer and no hints, so the burn's backlog
(tools/prereset_plan.py) takes them as it takes any un-annotated puzzle.
"""
import argparse
import collections
import concurrent.futures
import datetime
import json
import os
import re
import sys
from pathlib import Path

import clue_text
import file_blog_puzzles
import reconstruct_grid as rg
import series as series_meta
from fetch_puzzle import puzzle_path, write_puzzle_file

TOOL = "tools/file_cryptonite.py"
URL = "https://github.com/aviaefrat/cryptonite"
ROOT = Path(__file__).resolve().parent.parent
SERIES = ("telegraph", "sundaytel", "times", "sundaytimes")
SUNDAY = {"sundaytel", "sundaytimes"}
SIZE = 15
MAX_NODES = 3_000_000
CAPITAL_SHARE = 0.9
CAPITAL_MIN = 3
#: The share of held dates in a paper-year whose answers the dataset must match.
AGREE = 0.9
DAY = datetime.timedelta(days=1)


# ------------------------------------------------------------- the dataset

def day_of(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).date()


FIELDS = ("publisher", "sub_publisher", "date", "number", "orientation", "clue",
          "answer", "enumeration", "quick")


def load(data_dir):
    """The deduplicated rows. Parsing the 1 GB of jsonl is the costly part, so
    it is done once into DATA_DIR/rows-<zip mtime>.pickle, and every later run
    reads that (a pickle of our own writing, beside the data it was made from)."""
    import pickle
    data_dir = Path(data_dir)
    zipped = data_dir / "cryptonite.zip"
    stamp = int(zipped.stat().st_mtime) if zipped.exists() else 0
    cache = data_dir / f"rows-{stamp}.pickle"
    if cache.exists():
        with open(cache, "rb") as fh:
            return [dict(zip(FIELDS, t)) for t in pickle.load(fh)]
    rows = _parse(data_dir)
    tmp = cache.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump([tuple(r[k] for k in FIELDS) for r in rows], fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(cache)
    return rows


def _parse(data_dir):
    rows, seen = [], set()
    for part in ("train", "val", "test"):
        with open(Path(data_dir) / f"cryptonite-{part}.jsonl", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                key = (r["publisher"], r["sub_publisher"], r["date"], r["number"],
                       r["orientation"], r["answer"], r["quick"])
                if key not in seen:
                    seen.add(key)
                    rows.append(r)
    return rows


def buckets(rows, skipped):
    """{(series, day): [rows]} of the non-quick rows, and every Cryptonite day
    each series printed something on (dated)."""
    raw = collections.defaultdict(list)
    for r in rows:
        raw[(r["publisher"], r["sub_publisher"] or "", day_of(r["date"]))].append(r)
    labelled = {(p, d) for (p, sp, d) in raw if sp}
    out, dated = collections.defaultdict(list), collections.defaultdict(set)
    for (pub, sp, day), rs in raw.items():
        sunday = day.weekday() == 6
        if pub == "Telegraph":
            series = "sundaytel" if sunday else "telegraph"
        elif sp == "The Times":
            series = None if sunday else "times"
        elif sp == "The Sunday Times":
            series = "sundaytimes" if sunday else None
        else:
            series = None if (pub, day) in labelled else ("sundaytimes" if sunday else "times")
        if series is None:
            skipped[("?", day.year, "label disagrees with the weekday, or blank label beside a labelled one")] += 1
            continue
        cryptic = [r for r in rs if not r["quick"]]
        if len(cryptic) < len(rs):
            skipped[(series, day.year, "quick puzzle on the date (not filed)")] += 1
        if cryptic:
            out[(series, day)] += cryptic
            dated[series].add(day)
    return out, dated


def two_puzzles(rs):
    keys = collections.Counter((r["number"], r["orientation"]) for r in rs)
    return any(n > 1 for n in keys.values())


# ------------------------------------------------------------ held puzzles

def corpus(root=ROOT):
    """One read of every held puzzle in SERIES: ({series: {number: date}},
    {series: {date: set of answers}}, casing's {word: form})."""
    have = {s: {} for s in SERIES}
    answers = {s: {} for s in SERIES}
    forms = collections.defaultdict(collections.Counter)
    for s in SERIES:
        for p in (root / "puzzles" / s).glob("*/*.json"):
            j = json.loads(p.read_text(encoding="utf-8"))
            if j.get("number") and j.get("date"):
                day = datetime.date.fromisoformat(j["date"][:10])
                have[s][j["number"]] = day
                answers[s][day] = {e.get("solution") for e in j.get("entries", ()) if e.get("solution")}
            for e in j.get("entries", ()):
                clue = e.get("clue")
                count_forms(clue.get("text") if isinstance(clue, dict) else clue, forms)
    return have, answers, casing(forms)


def held(root=ROOT):
    return corpus(root)[0]


def disagreeing_years(groups, answers):
    """{(series, year)} where the dataset's answers match our held puzzle on
    fewer than AGREE of the shared dates: there its date or label means some
    other puzzle (the Sunday Times 2001-mid 2006), so none of it is filed."""
    tally = collections.defaultdict(collections.Counter)
    for (series, day), rs in groups.items():
        ours = answers[series].get(day)
        if ours is None or two_puzzles(rs):
            continue
        theirs = {letters(r["answer"]) for r in rs}
        tally[(series, day.year)][len(ours & theirs) >= 0.8 * len(theirs)] += 1
    return {k for k, c in tally.items() if c[True] < AGREE * (c[True] + c[False])}


def could_print(series, day):
    """The widest calendar: a day the paper could have printed this series."""
    if series in SUNDAY:
        return day.weekday() == 6
    return day.weekday() != 6 and (day.month, day.day) != (12, 25)


def number_for(series, day, anchors, printed):
    """(number, None) or (None, why). `anchors` is sorted [(date, number)] of
    held puzzles, `printed` the days the series surely printed (the dataset's).
    Between the anchors (d1, n1) and (d2, n2) round `day`, the true printing
    days T hold `printed`, sit inside could_print, and number n2 - n1 - 1. The
    number is n1 + |T in (d1, day]|; it stands only when every such T agrees."""
    import bisect
    dates = [d for d, _ in anchors]
    i = bisect.bisect_left(dates, day)
    if i < len(dates) and dates[i] == day:
        return None, "date already held"
    if i == 0:
        return None, "no held puzzle before it"
    if i == len(dates):
        return None, "no held puzzle after it"
    (d1, n1), (d2, n2) = anchors[i - 1], anchors[i]
    need = n2 - n1 - 1
    if need < 1:
        return None, "held neighbours leave no number free"

    def span(a, b):              # days in (a, b]
        days = [a + DAY * k for k in range(1, (b - a).days + 1)]
        wide = sum(could_print(series, x) for x in days)
        sure = sum(x in printed and could_print(series, x) for x in days)
        return sure, wide
    sure_l, wide_l = span(d1, day)
    sure_r, wide_r = span(day, d2 - DAY)
    if not (sure_l + sure_r <= need <= wide_l + wide_r):
        return None, "held neighbours disagree with the calendar"
    lo = max(sure_l, need - wide_r)
    hi = min(wide_l, need - sure_r)
    if lo != hi:
        return None, "number ambiguous between held neighbours"
    return n1 + lo, None


# ------------------------------------------------------------------ grids

def letters(answer):
    return re.sub(r"[^A-Z]", "", answer.upper())


def entries_of(rs):
    order = {"across": 0, "down": 1}
    return sorted(({"number": int(r["number"]), "direction": r["orientation"],
                    "answer": letters(r["answer"]), "clue": r["clue"],
                    "enumeration": r["enumeration"].strip("() ")} for r in rs),
                  key=lambda e: (e["number"], order[e["direction"]]))


def place(entries, size=SIZE, max_nodes=MAX_NODES):
    """(grid, None) when exactly one half-turn-symmetric grid numbers these
    lights and takes every answer, the search finishing; else (None, why)."""
    spec = [(e["number"], e["direction"], len(e["answer"])) for e in entries]
    words = [e["answer"] for e in entries]
    try:
        sols, info = rg.reconstruct(spec, cols=size, rows=size, limit=2, words=words,
                                    max_nodes=max_nodes)
    except ValueError:
        return None, "no grid: a light longer than the grid"
    if info.get("gaps"):
        return None, "no grid: clue numbers skip"
    if info.get("truncated"):
        return None, "grid search ran out of budget"
    if not sols:
        return None, "no grid takes the answers"
    if len(sols) > 1:
        return None, "more than one grid takes the answers"
    return sols[0], None


def _place_job(entries):
    return place(entries)


# ------------------------------------------------------------------- case

#: A run of letters: "london's" is "london" and "s", "i'm" is "i" and "m".
WORD = re.compile(r"[A-Za-z]+")


def count_forms(text, forms):
    """Tally each word's written form, except where a sentence starts."""
    for m in WORD.finditer(text or ""):
        before = text[:m.start()].rstrip(" \"'\u2018\u201c(")
        if before and before[-1] not in ".?!:;":
            forms[m.group().lower()][m.group()] += 1


def casing(forms):
    """{lowercase word: its form} for words our Times and Telegraph clues
    write capitalised mid-sentence at least CAPITAL_SHARE of the time."""
    out = {}
    for low, c in forms.items():
        total = sum(c.values())
        form, n = c.most_common(1)[0]
        if total >= CAPITAL_MIN and form != low and form[0].isupper() and n / total >= CAPITAL_SHARE:
            out[low] = form
    return out


def recase(text, caps):
    def word(m):
        w = m.group()
        if w == "i" and not re.match(r"\.[a-z]", text[m.end():m.end() + 2]):   # not "i.e."
            return "I"
        return caps.get(w, w)
    text = WORD.sub(word, text)
    # The first letter of the clue and of every sentence in it.
    return re.sub(r"(^|[.?!]\s+)([\"'\u2018\u201c(]*)([a-z])",
                  lambda m: m.group(1) + m.group(2) + m.group(3).upper(), text)


# ----------------------------------------------------------------- filing

def mend_clue(text):
    """The clue with the characters the dataset lost put back, or unchanged.

    Cryptonite's Telegraph and Sunday Telegraph clues of 2005-2009 were read
    as UTF-8 from Windows-1252 text, so each curly quote, apostrophe and dash
    arrived as U+FFFD. The bytes are gone but the character is not in doubt:
    a gap between letters is an apostrophe ("it?s"), a lone one between spaces
    is a dash, a gap opening a word opens a quote and one closing it closes
    it (written straight; the writer curls nothing), and an s with nothing open before it is a plural possessive
    ("workers? holiday"). Any gap left that these do not settle stays, so the
    writer's own U+FFFD check still refuses the clue (an accented letter, as
    in "flamb?", is not guessed). A brace closing a parenthesis ("(crack}") is
    a typo for the bracket."""
    if "\ufffd" in text:
        text = re.sub(r"(?<=\S) \ufffd (?=\S)|^\ufffd | \ufffd$", lambda m: m.group().replace("\ufffd", "\u2014"), text)
        text = re.sub(r"(?<=[A-Za-z])\ufffd(?=[a-z])", "'", text)
        out, opened = [], False
        for i, ch in enumerate(text):
            if ch != "\ufffd":
                out.append(ch)
                continue
            before = text[i - 1] if i else " "
            after = text[i + 1] if i + 1 < len(text) else " "
            if not before.isalnum() and after.isalnum():
                out.append('"')
                opened = True
            elif before.isalnum() or before in "?!.,;":
                if opened:
                    out.append('"')
                    opened = False
                elif before == "s":
                    out.append("'")
                else:
                    out.append(ch)
            else:
                out.append(ch)
        text = "".join(out)
    if "}" in text and text.count("(") > text.count(")"):
        text = text.replace("}", ")", 1)
    return text


def puzzle_of(series, number, day, rs, grid, caps):
    entries = entries_of(rs)
    for e in entries:
        e["clue"] = recase(mend_clue(e["clue"]), caps)
    rec = {"post_id": f"cryptonite-{series}-{day}", "series": series, "link": URL,
           "date": day.isoformat(), "entries": entries}
    row = {"grid": list(grid), "number": number, "how": "unique"}
    puzzle, why = file_blog_puzzles.build(rec, row, series, day,
                                          series_meta.default_setter(series))
    if why:
        return None, why
    puzzle["source"] = {"url": URL}
    puzzle["solutions"] = {"origin": "published"}
    return puzzle, None


GAPS = (("telegraph", 2001, 2008), ("sundaytel", 2001, 2008),
        ("sundaytimes", 2007, 2014), ("times", 2015, 2016))


def pilot_pick(cands, n):
    """About n candidates spread over the gap types, then any strays."""
    per = max(1, n // (len(GAPS) + 1))
    out = []
    for s, a, b in GAPS:
        inside = [c for c in cands if c[0] == s and a <= c[1].year <= b]
        step = max(1, len(inside) // per)
        out += inside[::step][:per]
    rest = [c for c in cands if c not in out]
    return out + rest[:: max(1, len(rest) // per)][:per]


def run(data_dir, write=True, pilot=None, workers=None, report=None):
    skipped = collections.Counter()
    filed = collections.Counter()
    rows = load(data_dir)
    groups, dated = buckets(rows, skipped)
    have, answers, caps = corpus()
    unlike = disagreeing_years(groups, answers)
    anchors = {s: sorted((d, n) for n, d in have[s].items()) for s in SERIES}
    held_days = {s: set(have[s].values()) for s in SERIES}
    cands = []
    for (series, day), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        why = None
        if day in held_days[series]:
            why = "date already held"
        elif (series, day.year) in unlike:
            why = "dataset disagrees with our held puzzles that year"
        elif two_puzzles(rs):
            why = "two cryptics on the date, not separable by numbering"
        elif not 20 <= len(rs) <= 40:
            why = "clue count unlike a 15x15 cryptic"
        elif any(not letters(r["answer"]) for r in rs):
            why = "a clue without an answer"
        elif any(clue_text.count_total(r["enumeration"].strip("() ")) not in (None, len(letters(r["answer"])))
                 for r in rs):
            why = "an answer's length disagrees with its enumeration"
        if why:
            skipped[(series, day.year, why)] += 1
            continue
        number, why = number_for(series, day, anchors[series], dated[series])
        if why is None and number in have[series]:
            why = "its number is already held under another date"
        if why:
            skipped[(series, day.year, why)] += 1
            continue
        cands.append((series, day, number, rs))
    if pilot:
        cands = pilot_pick(cands, pilot)
    # Spawned, not forked: a forked child would share (and, as refcounts touch
    # them, copy) the parent's whole dataset. Each child gets only its entries.
    del rows, groups
    import multiprocessing
    workers = workers or min(2, os.cpu_count() or 1)
    with concurrent.futures.ProcessPoolExecutor(
            workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        placed = pool.map(_place_job, [entries_of(rs) for *_, rs in cands], chunksize=4)
        for (series, day, number, rs), (grid, why) in zip(cands, placed):
            if why is None:
                puzzle, why = puzzle_of(series, number, day, rs, grid, caps)
            if why is None:
                try:
                    write_puzzle_file(puzzle_path(series, number), puzzle, generator=TOOL,
                                      dry_run=not write)
                except ValueError as e:
                    why = "write refused: " + str(e)
                    print(f"refused {series}-{number} {day}: {e}", flush=True)
            if why:
                skipped[(series, day.year, why)] += 1
                continue
            filed[(series, day.year)] += 1
            print(f"{'filed' if write else 'would file'} {series}-{number} {day}", flush=True)
    table = {"filed": {f"{s} {y}": n for (s, y), n in sorted(filed.items())},
             "skipped": {f"{s} {y} | {w}": n for (s, y, w), n in sorted(skipped.items(), key=str)}}
    if report:
        Path(report).write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8")
    print(f"{'filed' if write else 'would file'} {sum(filed.values())}, "
          f"skipped {sum(skipped.values())}")
    return table


def validate(data_dir):
    """How the rules fare on what we hold: answer agreement on held dates, and
    number_for leave-one-out on held puzzles 2001-2020."""
    skipped = collections.Counter()
    groups, dated = buckets(load(data_dir), skipped)
    have, answers, _ = corpus()
    print("paper-years not filed (disagree):", sorted(disagreeing_years(groups, answers)))
    for s in SERIES:
        agree = collections.Counter()
        for (series, day), rs in groups.items():
            if series != s or day not in answers[s] or two_puzzles(rs):
                continue
            ours = answers[s][day]
            theirs = {letters(r["answer"]) for r in rs}
            agree["same" if len(ours & theirs) >= 0.8 * len(theirs) else "differ"] += 1
        anchors = sorted((d, n) for n, d in have[s].items())
        loo = collections.Counter()
        for k, (d, n) in enumerate(anchors):
            if not 2001 <= d.year <= 2020 or k % 7:
                continue
            got, why = number_for(s, d, anchors[:k] + anchors[k + 1:], dated[s] | {d})
            loo["right" if got == n else ("wrong" if got else why)] += 1
        print(s, "answers on held dates:", dict(agree), "| leave-one-out:", dict(loo))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data_dir")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pilot", type=int)
    ap.add_argument("--workers", type=int)
    ap.add_argument("--report", default="/tmp/cryptonite_report.json")
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args(argv)
    if args.validate:
        validate(args.data_dir)
        return 0
    run(args.data_dir, write=not args.dry_run, pilot=args.pilot, workers=args.workers,
        report=args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
