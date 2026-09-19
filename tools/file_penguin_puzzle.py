#!/usr/bin/env python3
"""File one Penguin-book Guardian reprint into puzzles/ from a solve record.

    python3 tools/file_penguin_puzzle.py /tmp/penguin_solve_book3.json --volume 5

These puzzles come from "The New Penguin Book of The Guardian Crosswords",
scanned and OCR'd (tools/fetch_ia_book.py), parsed into clue lists
(tools/parse_penguin_book.py), given a grid reconstructed from the clue list
alone (tools/reconstruct_grid.py), and then solved from scratch by a model.
Nothing about them arrives from a feed, so this is the one place that turns a
solve record into a puzzle file, and everything the route has to get right is
spelled once, here.

THE NUMBER IS THE BOOK'S, NOT THE GUARDIAN'S. No volume prints a Guardian
puzzle number or a publication date — checked across all six books. So the key
is book-local: the series is the volume ("penguin5") and the number is the
book's own position in it (3), giving "penguin5-3". A volume per series because
every volume restarts at 1, and sharing one series would put two different
puzzles at No 3 in one sequence and walk prev/next between them — the same
reasoning tools/series.py gives for splitting indysunday off independent.

THERE IS NO DATE, so `date` is null. That is an established state in this
corpus rather than a new one: nine Cyclops puzzles carry it, puzzle_integrity's
check_shape passes a null date through untouched, and reindex sorts it to the
back of the archive instead of the front. An invented date would be a fact
nobody could ever correct.

THERE WILL NEVER BE AN ANSWER KEY. Penguin prints its solutions as answer-grid
IMAGES, which OCR to noise, and with no Guardian number or date there is nothing
to look one up by either. So solutionSource carries `officialKey: "never"` on
top of the usual `kind: "model"`. `kind` keeps every existing model-fill rule
working — blind_annotate.py refuses to grade the fill against itself,
index.json's solutionsUnofficial goes true, the crawlable page qualifies the
answers it prints — and `officialKey` says the one thing that is different
about these: no later job should wait for, or grade against, a key that is not
coming.

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
— puzzles/penguin5-3.js's 15-down "(9,5,4)" over NEWCASTLE and 17-down "See 15"
over UNDERLYME. The solve scripts emit the other shape, a per-light count on
each half, so this converts it on the way in rather than refusing it: see
tools/normalise_linked_enumerations.py, which derives the count from the
answer's own words and refuses loudly when the group cannot be resolved.

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
from fetch_puzzle import PUZZLE_DIR, write_puzzle_file  # noqa: E402
# One rule for linked answers, spelled once. That module owns both halves of it:
# which lights a "See N" ties together, and what the group's enumeration is.
from normalise_linked_enumerations import (enumeration_parts,  # noqa: E402
                                           normalise_record, resolve_groups)
from series import puzzle_id  # noqa: E402

# The scan these were read out of. A real, resolvable source for a book that has
# no URL of its own; the volume is in the series key, not here.
SOURCE_URL = "https://archive.org/details/newpenguinbkguar0000perk"


def normalise(answer):
    return re.sub(r"[^A-Z]", "", str(answer).upper())


def separators(group_ids, by_id, enumeration, fill):
    """Word breaks for one linked group, placed on the light each one falls in.

    The enumeration counts the whole answer; the grid holds it in lights. A
    break at cumulative position P belongs to the light that ENDS at or after P
    — so a break exactly on a light boundary is written at the end of the
    earlier light, which is how cryptic-30004 stores "(2,3,3,4)" over TOTIE and
    THEKNOT: {",": [2, 5]} then {",": [3]}.
    """
    lights = [(gid, by_id[gid]["length"]) for gid in group_ids]
    total = sum(n for _, n in lights)
    parts = enumeration_parts(enumeration)
    if sum(n for n, _ in parts) != total:
        raise SystemExit(
            f"{group_ids}: enumeration ({enumeration}) counts "
            f"{sum(n for n, _ in parts)} letters, the grid holds {total}")
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


def build(record, volume, model):
    src = record["puzzle"]
    number = record["book_number"]
    pid = puzzle_id(f"penguin{volume}", number)
    fill = record["fill"]
    solved = record["entries"]

    entries = [dict(e) for e in src["entries"]]
    by_id = {e["id"]: e for e in entries}
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
        e["separatorLocations"] = seps.get(e["id"], {})
        if e["id"] in groups:
            e["group"] = list(groups[e["id"]])
        e["solution"] = normalise(fill[e["id"]])
        confidence = (solved.get(e["id"]) or {}).get("confidence", "CONFIDENT")
        if confidence != "CONFIDENT":
            # Read by the annotator, via tools/annotate_prompt.md. Written only
            # when it is not the default, so its presence is the whole signal.
            e["solutionConfidence"] = confidence
        e["annotation"] = None
        out.append(e)

    verification = record.get("verification") or {}
    puzzle = {
        "id": pid,
        "number": number,
        "series": f"penguin{volume}",
        "name": f"Guardian cryptic crossword, Penguin book {volume} No {number}",
        "setter": record["setter"],
        # No volume prints a date. null is the corpus's existing spelling for
        # "nobody knows", not a gap to be filled in later.
        "date": None,
        "dimensions": src["dimensions"],
        "sourceUrl": SOURCE_URL,
        "entries": out,
        "solutionSource": {
            "kind": "model",
            "model": model,
            "date": datetime.date.today().isoformat(),
            "check": (f"{len(out)} entries, "
                      f"{verification.get('crossing_cells', '?')} crossings, "
                      f"{verification.get('conflicts', '?')} conflicts"),
            # The one fact that separates these from a prize puzzle solved early:
            # nothing is coming later to grade this against. Penguin prints its
            # solutions as answer-grid images that OCR to noise, and the book
            # names no Guardian number or date to look one up by.
            "officialKey": "never",
        },
    }
    return puzzle


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("record", help="the solve record, e.g. /tmp/penguin_solve_book3.json")
    ap.add_argument("--volume", type=int, required=True,
                    help="which Penguin volume this book is (the series key is penguin<N>)")
    ap.add_argument("--model", default="opus", help="the model that solved it")
    args = ap.parse_args(argv)

    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    puzzle = build(record, args.volume, args.model)
    path = PUZZLE_DIR / f"{puzzle['id']}.js"
    if path.exists():
        raise SystemExit(f"{path} already exists — refusing to overwrite a filed puzzle")
    write_puzzle_file(path, puzzle, generator="tools/file_penguin_puzzle.py")
    likely = [e["id"] for e in puzzle["entries"] if e.get("solutionConfidence")]
    print(f"wrote {path} — {len(puzzle['entries'])} entries, no date, model fill, "
          f"no official key will ever exist")
    print(f"  {len(likely)} entr{'y' if len(likely) == 1 else 'ies'} below CONFIDENT: "
          + (", ".join(likely) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
