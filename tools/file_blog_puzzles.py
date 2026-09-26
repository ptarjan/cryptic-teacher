#!/usr/bin/env python3
"""File grids rebuilt from a crossword blog into puzzles/: the half of filing
every blog shares. tools/file_times_puzzles.py and
tools/file_telegraph_puzzles.py each hand run() a source saying what is
their paper's: which series a row files under, its setter, its print dates.

A row is filed only when all of these hold, and every refusal is counted by
its reason:

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
    is inside. One whose title is a single typing slip from exactly one
    unclaimed number that fits is filed under that number. A number two
    posts claim files neither;
  - no other series reprints it: a number a reprinting series (`reprints`
    in tools/series.py) holds, or has not reached yet, is left to it.

The blog's answers are a solver's write-up, not the paper's key, so
solutionSource.kind names the blog (series.py's `blog`) and provenance says so.

A file already on disk is never rewritten but for its date, which facts
arriving later can prove, and a placeholder setter the post names: by then it
may carry annotations. One whose clues or answers no longer match what this
would write is named, so a correction made upstream is seen rather than lost.
"""
import bisect
import collections
import datetime
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import fetch_puzzle
import reconstruct_grid as rg
import series as series_meta
import times_grids as tg
from fetch_puzzle import (
    clue_words,
    has_words,
    puzzle_path,
    read_puzzle_file,
    write_puzzle_file,
)
from file_penguin_puzzle import separators
from normalise_linked_enumerations import enumeration_parts, resolve_groups


@dataclass(frozen=True)
class Source:
    """What one blog's filer knows about its paper.

    `tool` is the filer, recorded as the puzzle's acquirer. `target(row)` is (series
    key, dated?), where a dated series falls back to the post date when
    `print_dates(recs, renumbered)` -- ({(series, number): date}, [notes]) --
    proves none. `setter(rec, series)` is the byline or None."""
    tool: str
    target: Callable
    print_dates: Callable
    setter: Callable


def epoch_ms(day):
    return int(datetime.datetime(day.year, day.month, day.day,
                                 tzinfo=datetime.timezone.utc).timestamp() * 1000)


#: C1 controls: bytes the blog lost in decoding, never text.
C1 = re.compile(r"[\x80-\x9f]")


def clean(clue):
    """The clue as text: the blog's markup, lost bytes and doubled spaces removed."""
    return " ".join(C1.sub("", fetch_puzzle.plain_text(clue)).split()) if clue else clue


#: How far from a post the sequence around it is read.
NEAR = datetime.timedelta(days=28)


def in_sequence(rows):
    """The post_ids whose numbers fit the sequence around their post date."""
    fits = sequence_window(rows)
    return {r["post_id"] for r in rows if fits(r["date"], r["number"])}


def sequence_window(rows):
    """fits(date, number): does a number sit in the sequence near that date?

    Inside the range the longest run of rows whose numbers rise with the post
    date spans within NEAR of it.
    """
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

    def fits(date, number):
        day = datetime.date.fromisoformat(date)
        lo, hi = bisect.bisect_left(days, day - NEAR), bisect.bisect_right(days, day + NEAR)
        # The spine rises, so its first and last numbers in the window bound it.
        return lo < hi and spine[lo]["number"] <= number <= spine[hi - 1]["number"]
    return fits


def slips(number):
    """Every number one typing slip from this one: a digit changed, or two
    adjacent digits swapped."""
    s, out = str(number), set()
    for i in range(len(s)):
        out |= {s[:i] + d + s[i + 1:] for d in "0123456789"}
    out |= {s[:i] + s[i + 1] + s[i] + s[i + 2:] for i in range(len(s) - 1)}
    return {int(t) for t in out if t[0] != "0"} - {number}


def retyped(row, fits, taken):
    """The number an out-of-sequence row was meant to carry, or None.

    Bloggers mistype titles -- "Sunday Times 5445" for 5,045, "Jumbo 1754"
    for 1,764 -- and the sequence is where the number is checked. A row is
    renumbered only when exactly one slip of its number fits the sequence at
    its date and no other row claims it.
    """
    fit = [n for n in slips(row["number"]) if n not in taken and fits(row["date"], n)]
    return fit[0] if len(fit) == 1 else None


def reprinted_from():
    """{series: (the series reprinting it, the numbers that series holds)}."""
    held = {}
    for key, meta in series_meta.SERIES.items():
        if meta.get("reprints"):
            numbers = {series_meta.parse_id(p.stem)[1]
                       for p in fetch_puzzle.PUZZLE_DIR.glob(f"{key}-[0-9]*.json")}
            if numbers:
                held[meta["reprints"]] = (key, numbers)
    return held


def reprinted_by(reprints, series, number):
    """The series that files `number` instead of `series`, or None.

    It holds the number, or has not reached it yet (the Globe prints the Quick
    ~7 weeks late). A number inside its run that it never printed — Globe
    3,263 fell on Victoria Day — is still ours to file.
    """
    if series not in reprints:
        return None
    key, numbers = reprints[series]
    return key if number in numbers or number > max(numbers) else None


def build(rec, row, series, date, setter):
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
    if row.get("titled"):
        check += (f"; the blog titled it No {row['titled']}, which the sequence "
                  f"puts at {number}")
    if fixed:
        check += (f"; the grid proves the blog's answer wrong at "
                  f"{', '.join(fixed)}, corrected here")
    kind = series_meta.kind(series)
    return {
        "id": series_meta.puzzle_id(series, number),
        "number": number,
        "series": series,
        "name": f"{series_meta.publisher(series)} {kind.lower()} crossword No {number:,}",
        "setter": setter,
        "date": date and epoch_ms(date),
        "dimensions": {"cols": len(row["grid"][0]), "rows": len(row["grid"])},
        "sourceUrl": rec["link"],
        # The blog's own name: "timesforthetimes", "bigdave44".
        "solutionSource": {"kind": series_meta.meta(series)["blog"].split(".")[0],
                           "url": rec["link"],
                           "date": rec["date"], "check": check},
        "entries": out,
    }, None


def content(puzzle):
    """What a later run compares: the grid, the clues' words and the answers.
    A clue retyped with other quotes or dashes is the same clue."""
    return [(e["id"], e["position"], e["length"], clue_words(e["clue"]), e["solution"])
            for e in puzzle["entries"]]


def run(source, grids, parsed, write=True, newest=None):
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
        sources[(row["series"], *source.target(row))].append(row)
    claims = collections.defaultdict(list)
    strays = []
    for (_, series, dated), group in sources.items():
        fits = sequence_window(group)
        for row in group:
            if fits(row["date"], row["number"]):
                claims[(series, row["number"])].append((row, dated))
            else:
                strays.append((series, dated, fits, row))
    taken = collections.defaultdict(set)
    for (_, series, _), group in sources.items():
        taken[series] |= {r["number"] for r in group}
    for series, dated, fits, row in strays:
        number = retyped(row, fits, taken[series])
        if number is None:
            skipped["number out of sequence"] += 1
            continue
        claims[(series, number)].append((dict(row, number=number, titled=row["number"]), dated))
        taken[series].add(number)

    renumbered = {row["post_id"]: row["number"]
                  for claim in claims.values() for row, _ in claim if row.get("titled")}
    dates, notes = source.print_dates(recs.values(), renumbered)
    reprints = reprinted_from()
    filed, kept, drifted = collections.Counter(), 0, []
    redated, renamed = collections.Counter(), collections.Counter()
    refused = []
    order = sorted(claims.items(), key=lambda kv: (kv[0][0], -kv[0][1] if newest else kv[0][1]))
    for (series, number), claim in order:
        if newest and filed[series] >= newest:
            continue
        if len(claim) > 1:
            skipped["number claimed twice"] += len(claim)
            continue
        by = reprinted_by(reprints, series, number)
        if by:
            skipped[f"{by} reprints it"] += 1
            continue
        row, dated = claim[0]
        rec = recs[row["post_id"]]
        date = dates.get((series, number)) or (
            datetime.date.fromisoformat(rec["date"]) if dated else None)
        puzzle, why = build(rec, row, series, date, source.setter(rec, series))
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
                try:
                    write_puzzle_file(path, {**held, **fix})
                except ValueError as e:
                    refused.append(str(e))
            continue
        # The write path refuses what the corpus sweep would report, so a dry
        # run cannot count those refusals.
        try:
            if write:
                write_puzzle_file(path, puzzle, generator=source.tool)
        except ValueError as e:
            refused.append(str(e))
            skipped["refused by the write path"] += 1
            continue
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
    for why in refused[:20]:
        print(f"  {why}")
    if drifted:
        print(f"  {len(drifted)} filed puzzle(s) differ from the blog now, left as they are: "
              + " ".join(drifted))
    return filed, skipped, drifted
