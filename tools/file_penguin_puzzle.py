#!/usr/bin/env python3
"""File one scanned-book puzzle into puzzles/ from a solve record.

    python3 tools/file_penguin_puzzle.py /tmp/solve.json --book newpenguinbkguar0000perk
    python3 tools/file_penguin_puzzle.py /tmp/solve.json --book heraldcrosswordb0000unse --unsolved

Named for the Penguin volumes it was written for, and it files any book that
comes down the same route — "The New Penguin Book of The Guardian Crosswords"
and "The Herald Crossword Book" alike. Which book it is, is one row in
tools/data/books.json: its index, its cover volume, its shelf label, its title
and the scan it was read out of. --book names that row BY THE ARCHIVE.ORG
IDENTIFIER, which is also the item whose text was read, so the number, the
title and the sourceUrl cannot come from three different books.

These puzzles come from "The New Penguin Book of The Guardian Crosswords",
scanned and OCR'd (tools/fetch_ia_book.py), parsed into clue lists
(tools/parse_penguin_book.py), given a grid reconstructed from the clue list
alone (tools/reconstruct_grid.py), and then solved from scratch by a model.
Nothing about them arrives from a feed, so this is the one place that turns a
solve record into a puzzle file, and everything the route has to get right is
spelled once, here.

THE NUMBER IS THE BOOK'S, NOT THE GUARDIAN'S. No volume prints a Guardian
puzzle number or a publication date — checked across all six books. So the key
is book-local: the series is `book` for the whole shelf and the number carries
the book and the puzzle's place in it, book_index * 1000 + position, giving
"book-3003" for the book registered as index 3, No 3. The book is in the
number and not in the key because every book restarts at 1 — one flat sequence
would put thirty different puzzles at No 3 and walk prev/next from the Herald
into the Daily Mail — while thirty keys meant thirty badges, thirty colours and
thirty tooltips for one shelf.

THERE IS NO DATE, so `date` is null. That is an established state in this
corpus rather than a new one: nine Cyclops puzzles carry it, puzzle_integrity's
check_shape passes a null date through untouched, and reindex sorts it to the
back of the archive instead of the front. An invented date would be a fact
nobody could ever correct.

NO JOB CAN FETCH THE ANSWER KEY. The book does print one — solved answer grids
at the back — but as page IMAGES: their OCR text is noise, and archive.org
serves a loan's page images encrypted for its in-browser reader only. With no
Guardian number or date there is no other key to look up. So solutionSource
carries `officialKey: "never"` on top of the usual `kind: "model"`. `kind`
keeps every existing model-fill rule working — blind_annotate.py refuses to
grade the fill against itself, index.json's solutionsUnofficial goes true, the
crawlable page qualifies the answers it prints — and `officialKey` says no
scheduled job should wait for a key. The printed grids stay readable by a
person holding the loan; answers read from them replace the model's and drop
`kind: "model"`.

CONFIDENCE IS PER ENTRY AND IT SURVIVES. A model solve is not uniformly sure of
itself: most entries parse completely, and a few are a definition plus enough
crossings to force the letters, with wordplay that does NOT fully account for
the answer. Those carry `solutionConfidence: "LIKELY"` on the entry. It is
written only where it is not CONFIDENT, the way `clues` coverage is written only
where a clue is missing — absence is the default and saying so 28 times per
puzzle states nothing. The annotator reads the puzzle file, and
tools/annotate_prompt.md tells it what the field means: a LIKELY entry's
letters are forced rather than derived, so it may not be written up as though
the wordplay were known. Told "CONFIDENT", an annotator invents authoritative
wordplay for exactly those clues, which is the worst thing this route could
produce — a teaching site confidently teaching a parse nobody verified.

A LINKED ANSWER'S COUNT LIVES ON ITS LEADER, and the continuation prints none
— puzzles/book-3003.json's 15-down "(9,5,4)" over NEWCASTLE and 17-down "See 15"
over UNDERLYME. The solve scripts emit the other shape, a per-light count on
each half, so this converts it on the way in rather than refusing it: see
tools/normalise_linked_enumerations.py, which derives the count from the
answer's own words and refuses loudly when the group cannot be resolved.

ANSWERS ARE OPTIONAL, AND --unsolved IS HOW YOU SAY SO. A book puzzle is worth
filing the moment its grid and clues are readable: filed with `solution: null`
on every entry it is a puzzle the site can show, and puzzles/index.json records
hasSolutions false, which is what puts it in the cold-solve queue in
tools/daily_update.sh (section 3a) for the nightly backfill to finish. That is
the cheap way to solve a book — one puzzle a night off an existing job, rather
than a person driving a solver.

The flag is explicit because the alternative is dangerous. Inferring "unsolved"
from a record that happens to be missing answers would turn a truncated solve
into a silently half-filed puzzle; without the flag a missing answer is still
the hard error it always was. And --unsolved files NO answers rather than the
ones it has: a partial fill in a puzzle file is worse than none, because
tools/apply_solution.py refuses to write over a puzzle that already holds
answers and no solutionSource, so a half-filled file would turn away the very
job that is meant to finish it. Keep a partial fill beside the record instead —
tools/data/penguin_partial_fills/ is where the ones we have are kept.

An unsolved file carries no solutionSource either, for the same reason it
carries no answers: there is no solve to describe yet, and the field is what
index.json reads to say the answers on this page are ours rather than the
paper's. apply_solution.py writes it when the backfill lands, and stamps
`officialKey` from tools/series.py, so the one permanent fact about these books
survives the route that fills them in.

The input record is what the solve wrote: `puzzle` (grid geometry and clue text
from the reconstructor), `fill` (id -> answer), `entries` (id -> answer,
confidence, parse) and `setter`. This writes the file and checks nothing; run
tools/apply_solution.py --check-only and tools/puzzle_integrity.py over the
result, which is what the recipe in docs/ does.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from fetch_puzzle import puzzle_path, write_puzzle_file  # noqa: E402
# One rule for linked answers, spelled once. That module owns both halves of it:
# which lights a "See N" ties together, and what the group's enumeration is.
from normalise_linked_enumerations import (enumeration_parts,  # noqa: E402
                                           normalise_record, resolve_groups)
from series import (BOOK_SERIES, book_number, default_setter,  # noqa: E402
                    official_key, puzzle_id, puzzle_name, scan_url)
import provenance  # noqa: E402

def source_url(series, number):
    """The archive.org item these clues were read out of.

    Read BACK out of the number, never carried through from --book: the number
    was built from the identifier, so reading it back is what proves the two
    agree. sourceUrl and provenance.book.identifier both come from that one
    registry row, so they cannot name different books — a free identifier
    beside a free --volume is precisely how they came to.
    """
    url = scan_url(series, number)
    if not url:
        raise SystemExit(
            f"{series}-{number} has no archive.org identifier in "
            f"tools/data/books.json — look its scan up and add it there. "
            f"Filing it without one makes the puzzle cite another book.")
    return url


def normalise(answer):
    return re.sub(r"[^A-Z]", "", str(answer).upper())


def separators(group_ids, by_id, enumeration, fill=None):
    """Word breaks for one linked group, placed on the light each one falls in.

    The enumeration counts the whole answer; the grid holds it in lights. A
    break at cumulative position P belongs to the light that ENDS at or after P
    — so a break exactly on a light boundary is written at the end of the
    earlier light, which is how cryptic-30004 stores "(2,3,3,4)" over TOTIE and
    THEKNOT: {",": [2, 5]} then {",": [3]}.

    The breaks come from the enumeration and the light lengths, so a puzzle
    filed with no answers gets the same ones a solved one would: the app draws
    them, and the count they come from is printed in the clue either way. `fill`
    is the cross-check that the answers agree with the count, and is skipped
    when there are none to check — no answer is not a disagreement.
    """
    lights = [(gid, by_id[gid]["length"]) for gid in group_ids]
    total = sum(n for _, n in lights)
    parts = enumeration_parts(enumeration)
    if sum(n for n, _ in parts) != total:
        raise SystemExit(
            f"{group_ids}: enumeration ({enumeration}) counts "
            f"{sum(n for n, _ in parts)} letters, the grid holds {total}")
    if fill:
        answer = "".join(normalise(fill[gid]) for gid in group_ids)
        if len(answer) != total:
            raise SystemExit(f"{group_ids}: answers hold {len(answer)} letters, grid wants {total}")

    out = {gid: {} for gid, _ in lights}
    at = 0
    for count, sep in parts:
        at += count
        if not sep:
            continue
        start = 0
        for gid, length in lights:
            if start < at <= start + length:
                out[gid].setdefault(sep, []).append(at - start)
                break
            start += length
        else:
            raise SystemExit(f"{group_ids}: word break at {at} falls outside the grid")
    return out


def coarse_continuations(record):
    """Lights whose enumeration was guessed rather than read, filed unsolved.

    A continuation the book printed no count over counts as ONE word of its own
    length (see tools/normalise_linked_enumerations.py). That is the weakest true
    statement available with no answer to read, and it can be coarser than the
    answer turns out to deserve: book 27's "(5,9)" over UNTER DEN LINDEN, which a
    solve would enumerate (5,3,6). Nothing catches that later — the clue text is
    written once, here, and puzzle_integrity's check_length only compares totals
    — so the lights it happened to are named on the way out. A worklist beats a
    corpus scan if these are ever re-derived from the answers.
    """
    entries = [dict(e) for e in record["puzzle"]["entries"]]
    by_id = {e["id"]: e for e in entries}
    coarse = []
    for leader, group_ids in sorted(resolve_groups(entries).items()):
        if leader != group_ids[0]:
            continue
        total = sum(by_id[gid]["length"] for gid in group_ids)
        printed = by_id[leader].get("enumeration")
        if printed and sum(n for n, _ in enumeration_parts(printed)) == total:
            continue  # already leader form: the book counted the whole answer
        coarse += [gid for gid in group_ids if not by_id[gid].get("enumeration")]
    return coarse


def build(record, identifier, model, unsolved=False):
    src = record["puzzle"]
    # The record carries the number the BOOK prints. The stored number carries
    # the book as well (tools/series.py: book_index * 1000 + position), because
    # one series covers the whole shelf and No 18 alone would name thirty
    # different puzzles.
    position = record["book_number"]
    series = BOOK_SERIES
    number = book_number(identifier, position)
    pid = puzzle_id(series, number)
    # --unsolved files no answers at all, not the ones the record happens to
    # hold: see the module docstring — a half-filled puzzle file turns away the
    # backfill that is meant to finish it.
    fill = {} if unsolved else record["fill"]
    solved = {} if unsolved else record["entries"]

    entries = [dict(e) for e in src["entries"]]
    by_id = {e["id"]: e for e in entries}
    if not unsolved:
        missing = [e["id"] for e in entries if e["id"] not in fill]
        if missing:
            raise SystemExit(f"{pid}: no answer for {', '.join(missing)}")
    # A LINKED ANSWER IS STORED ON ITS LEADER. The solve scripts emit a count on
    # each half, because a light is what they measured; this writes the whole
    # answer's count on the leader and none on the continuation. Converting here
    # rather than refusing here is what makes the split shape unfilable instead
    # of merely rejected — see tools/normalise_linked_enumerations.py for how
    # the count is read out of the answer. On the copies, so the record on disk
    # is left exactly as the solve wrote it.
    normalise_record({"puzzle": {"entries": entries}, "fill": fill})
    groups = resolve_groups(entries)

    seps = {}
    for e in entries:
        if not e.get("enumeration"):
            continue
        group_ids = groups.get(e["id"], [e["id"]])
        if group_ids[0] != e["id"]:
            raise SystemExit(f"{e['id']} carries an enumeration but is a continuation")
        seps.update(separators(group_ids, by_id, e["enumeration"], fill))

    out = []
    for e in entries:
        enumeration = e.pop("enumeration", None)
        # The clue as the book printed it: the enumeration belongs in the clue
        # text, which is where check_length and the app both read it from. A
        # continuation ("See 11") is printed without one and stays that way.
        if enumeration:
            e["clue"] = f"{e['clue']} ({enumeration})"
        if seps.get(e["id"]):
            e["separatorLocations"] = seps[e["id"]]
        if e["id"] in groups:
            e["group"] = list(groups[e["id"]])
        # null, not absent, on an unsolved puzzle: that is how every unsolved
        # puzzle in this corpus spells an unanswered light.
        e["solution"] = normalise(fill[e["id"]]) if e["id"] in fill else None
        confidence = (solved.get(e["id"]) or {}).get("confidence", "CONFIDENT")
        if confidence != "CONFIDENT":
            # Read by the annotator, via tools/annotate_prompt.md. Written only
            # when it is not the default, so its presence is the whole signal.
            e["solutionConfidence"] = confidence
        out.append(e)

    verification = record.get("verification") or {}
    crossings, conflicts = verification.get("crossing_cells"), verification.get("conflicts")
    if isinstance(crossings, int) and isinstance(conflicts, int):
        check = f"{len(out)} entries, {crossings} crossings, {conflicts} conflicts"
    else:
        check = (f"{len(out)} entries; the solve record carried no machine check — "
                 f"run tools/apply_solution.py --check-only and record what it says")
    puzzle = {
        "id": pid,
        "number": number,
        "series": series,
        "name": puzzle_name(series, number),
        # Some books print no byline over a puzzle. "Unknown" is what the rest
        # of the corpus shows for one, and it is the series table's answer — an
        # empty setter would read as a parsing failure instead of as the blank
        # the page actually has.
        "setter": record.get("setter") or default_setter(series, number),
        # No volume prints a date. null is the corpus's existing spelling for
        # "nobody knows", not a gap to be filled in later.
        "date": None,
        "dimensions": src["dimensions"],
        "sourceUrl": source_url(series, number),
        "entries": out,
    }
    # No solve, no solutionSource. The field says whose answers these are, and
    # puzzles/index.json turns it into solutionsUnofficial — claiming a model
    # fill over a grid with no answers in it would mark the puzzle as ours to a
    # reader and, worse, satisfy apply_solution.py's overwrite guard on behalf
    # of a solve that never happened. The backfill writes it when it lands.
    if not unsolved:
        puzzle["solutionSource"] = {
            "kind": "model",
            "model": model,
            "date": datetime.date.today().isoformat(),
            # Counts, or an admission. A solve that was stopped before it ran
            # check_geometry/check_fill leaves prose in these fields — one
            # record said conflicts were "unchecked (all crossings were
            # verified by hand while solving)" — and prose spliced into a
            # counts field reads afterwards as a count. Either both numbers
            # are numbers or this says plainly that nothing machine-checked
            # the fill, which is the thing a later reader needs to know.
            "check": check,
            # The one fact that separates these from a prize puzzle solved early:
            # nothing is coming later to grade this against. Penguin prints its
            # solutions as answer-grid images that OCR to noise, and the book
            # names no Guardian number or date to look one up by. Stated once in
            # tools/series.py, because tools/apply_solution.py has to stamp the
            # same fact when the nightly solve fills one of these in.
            "officialKey": official_key(series),
        }
    return puzzle


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("record", help="the solve record, e.g. /tmp/penguin_solve_book3.json")
    ap.add_argument("--book", required=True,
                    help="the archive.org identifier of the book this was read "
                         "out of, as registered in tools/data/books.json. The "
                         "id is book-<book_index*1000+position>")
    ap.add_argument("--model", default="opus", help="the model that solved it")
    ap.add_argument("--unsolved", action="store_true",
                    help="file the grid and clues with no answers at all, for the "
                         "nightly cold solve to finish (daily_update.sh, step 3a)")
    args = ap.parse_args(argv)

    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    puzzle = build(record, args.book, args.model, unsolved=args.unsolved)
    path = puzzle_path(puzzle["series"], puzzle["number"])
    if path.exists():
        raise SystemExit(f"{path} already exists — refusing to overwrite a filed puzzle")
    write_puzzle_file(path, puzzle, generator="tools/file_penguin_puzzle.py")
    if args.unsolved:
        print(f"wrote {path} — {len(puzzle['entries'])} entries, no date, NO ANSWERS: "
              f"it is now the cold-solve queue's problem (daily_update.sh, step 3a)")
        coarse = coarse_continuations(record)
        if coarse:
            print(f"  {len(coarse)} light(s) the book printed no count over, enumerated "
                  f"as one word of their own length: {', '.join(coarse)}")
        return 0
    likely = [e["id"] for e in puzzle["entries"] if e.get("solutionConfidence")]
    print(f"wrote {path} — {len(puzzle['entries'])} entries, no date, model fill, "
          f"no official key will ever exist")
    print(f"  {len(likely)} entr{'y' if len(likely) == 1 else 'ies'} below CONFIDENT: "
          + (", ".join(likely) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
