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
solutionSource is `timesforthetimes` and provenance says so. The Quick and the
Daily are blogged the day they are printed, so the post date is the puzzle's;
the prize puzzles are blogged after entries close, so theirs is null.

A file already on disk is never rewritten: by then it may carry annotations.
One whose clues or answers no longer match what this would write is named, so
a correction made upstream is seen rather than lost.
"""
import argparse
import bisect
import collections
import datetime
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import fetch_puzzle
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


def build(rec, row, series, dated):
    """(puzzle, None) or (None, reason it is not filed)."""
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
    date = None
    if dated:
        day = datetime.date.fromisoformat(rec["date"])
        date = int(datetime.datetime(day.year, day.month, day.day,
                                     tzinfo=datetime.timezone.utc).timestamp() * 1000)
    kind = series_meta.kind(series)
    return {
        "id": series_meta.puzzle_id(series, number),
        "number": number,
        "series": series,
        "name": f"{series_meta.publisher(series)} {kind.lower()} crossword No {number:,}",
        "setter": series_meta.default_setter(series),
        "date": date,
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


def run(grids=tg.OUT, parsed=tg.PARSED, write=True):
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

    reprints = reprinted_from()
    filed, kept, drifted = collections.Counter(), 0, []
    for (series, number), claim in sorted(claims.items()):
        if len(claim) > 1:
            skipped["number claimed twice"] += len(claim)
            continue
        if series in reprints and number >= reprints[series][1]:
            skipped[f"{reprints[series][0]} reprints it"] += 1
            continue
        row, dated = claim[0]
        puzzle, why = build(recs[row["post_id"]], row, series, dated)
        if why:
            skipped[why] += 1
            continue
        path = puzzle_path(series, number)
        if path.exists():
            kept += 1
            if content(read_puzzle_file(path)) != content(puzzle):
                drifted.append(puzzle["id"])
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
