#!/usr/bin/env python3
"""Give a filed puzzle the setter its cached blog post names, where the filer missed it.

    python3 tools/backfill_setters.py --report             # per series: missing, recoverable
    python3 tools/backfill_setters.py --apply              # write the setters found
    python3 tools/backfill_setters.py --apply mephisto     # one series

The filers name a setter only from the post they read at filing time, and the
rules that read a post improve after the puzzle is filed (a Mephisto setter
named in the blogger's intro rather than the title). Re-filing is refused by
design (a filed puzzle is left alone, its annotations kept), so this edits the
one key. IDEMPOTENT: a puzzle that has a setter is never touched, and a second
run finds nothing. Reads only the caches the fetchers wrote; never the network.

A source is a function (series, {number: puzzle id}) -> {puzzle id: setter}.
Add one per blog; each must say, in its own docstring, how it was checked
against the puzzles that already carry a setter.
"""
import argparse
import json
import sys

import fetch_puzzle
import fetch_times_feed
import file_times_puzzles
import parse_bigdave44 as bigdave
import parse_timesforthetimes as tftt
import puzzle_paths
import puzzle_schema


def missing(series):
    """{number: id} of every filed puzzle of `series` without a setter."""
    out = {}
    for path in sorted((puzzle_paths.PUZZLE_DIR / series).glob("*/*.json")):
        puzzle = fetch_puzzle.read_puzzle_file(path)
        if not puzzle.get("setter"):
            out[puzzle["number"]] = puzzle["id"]
    return out


def times_blog_records(series):
    """{number: parsed.jsonl record} of the posts the Times filer files as `series`."""
    out = {}
    with open(tftt.OUT, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("series") not in file_times_puzzles.LABELS or not rec.get("number"):
                continue
            rec = {**rec, "number": int(rec["number"])}
            if file_times_puzzles.target(rec)[0] == series:
                out[rec["number"]] = rec
    return out


def mephisto(numbers):
    """The Mephisto setter the post names in its title or the blogger's intro:
    file_times_puzzles.mephisto_setter. Checked on the 250 Mephisto puzzles
    that already had a setter: all 250 agree with it."""
    records = times_blog_records("mephisto")
    found = {}
    for number, pid in numbers.items():
        name = file_times_puzzles.mephisto_setter(records[number]) if number in records else None
        if name:
            found[pid] = name
    return found


def times_feed_quick(numbers):
    """The Quick Cryptic setter the Times's own puzzle feed prints (`setter`, else
    `byline`): the publisher itself, so it outranks the blog."""
    found = {}
    for _, _, data in fetch_times_feed.cached(fetch_times_feed.QUICK):
        number = fetch_times_feed.number_of(data)
        copy = data["copy"]
        name = (copy.get("setter") or copy.get("byline") or "").strip()
        if name and number in numbers:
            found[numbers[number]] = name
    return found


def times_title(series):
    """A source for a Times series whose blog titles carry a byline, through
    file_times_puzzles.setter: the Quick Cryptic, the Sunday Times and the TLS."""
    def source(numbers):
        records = times_blog_records(series)
        found = {}
        for number, pid in numbers.items():
            name = file_times_puzzles.setter(records[number], series) if number in records else None
            if name:
                found[pid] = name
        return found
    source.__doc__ = f"The {series} setter the Times for the Times post title names."
    return source


def timesquick(numbers):
    """The feed's setter, else the blog title's."""
    found = times_title("timesquick")(numbers)
    found.update(times_feed_quick(numbers))
    return found


def telegraph(series):
    """A source for the Daily or Sunday Telegraph: the setter the blogger names in
    his opening of the puzzle's post (or of the posts its facts were filled from),
    parse_bigdave44.setter_of. The paper prints none. The weekday rota is the
    check: on the 1,100 posts that name one, Wednesdays are Jay's (183 of 200),
    Thursdays Ray T's, Fridays Giovanni's and Cephas's, Sundays Dada's and
    Virgilius's."""
    def source(numbers):
        cats = bigdave.categories()
        found = {}
        with open(bigdave.OUT, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("series") != series or not rec.get("number"):
                    continue
                pid = numbers.get(int(rec["number"]))
                if pid is None:
                    continue
                names = set()
                for post_id in [rec["post_id"], *(rec.get("filled_from") or ())]:
                    try:
                        post = json.loads((bigdave.POSTS / f"{post_id}.json").read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    names.add(bigdave.setter_of(post, bigdave.rendered_lines(post), cats))
                names.discard(None)
                if len(names) == 1:
                    found[pid] = names.pop()
        return found
    source.__doc__ = f"The {series} setter the blogger names in his opening."
    return source


SOURCES = {"telegraph": telegraph("telegraph"), "sundaytel": telegraph("sundaytel"),
           "mephisto": mephisto,
           **{s: times_title(s) for s in file_times_puzzles.BYLINED}, "timesquick": timesquick}


def apply_setter(pid, setter):
    path = puzzle_paths.find(pid)
    puzzle = fetch_puzzle.read_puzzle_file(path)
    if puzzle.get("setter"):
        return False
    puzzle["setter"] = setter
    puzzle = puzzle_schema.order(puzzle)
    fetch_puzzle.write_whole(path, json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("series", nargs="*", help="series to read (default: every source)")
    ap.add_argument("--apply", action="store_true", help="write the setters found")
    ap.add_argument("--report", action="store_true", help="count only (the default)")
    args = ap.parse_args(argv)
    chosen = args.series or sorted(SOURCES)
    unknown = [s for s in chosen if s not in SOURCES]
    if unknown:
        sys.exit(f"no source for {unknown}; known: {sorted(SOURCES)}")
    for series in chosen:
        gaps = missing(series)
        found = SOURCES[series](gaps)
        wrote = sum(apply_setter(pid, name) for pid, name in found.items()) if args.apply else 0
        print(f"{series}: {len(gaps)} without a setter, {len(found)} named by the blog"
              + (f", {wrote} written" if args.apply else ""))


if __name__ == "__main__":
    main()
