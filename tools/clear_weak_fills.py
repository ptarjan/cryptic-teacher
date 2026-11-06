#!/usr/bin/env python3
"""Clear the Times lights our clue solve filled past a crossing nobody printed (WEAK_FILLS).

    python3 tools/clear_weak_fills.py            # count only
    python3 tools/clear_weak_fills.py --apply    # write

A light of a file whose solutions.model is file_archive_org_puzzles.CLUE_SOLVER and that is outside solutions.printed
and solutions.hand is ours. Where a cell of it is crossed by a light that is blank or ours too, no printed letter
holds that cell, and the fill stood on a guess: 11-06 Paul read 10 Times solution grids by eye, three of the model
fills in two of them were wrong (SWORDER, LABOR for LAMPS, PREENS for GREENS), each on a
crossing the print had not given. clue_solved_reads now fills such a light only by an anagram of the clue, the answer
another puzzle gave the same clue, or as the puzzle's only blank light; this clears the lights that rule would not
have filled: every other route with a crossing not printed. An annotation of a cleared light goes with its answer.
A file left with no light of ours loses its model detail (provenance.stamp makes it the paper's partial file); one
left a light short is no longer fully answered.
"""
import argparse
import copy
import sys

import provenance
import puzzle_paths
import trove_solution_ocr as tso
from fetch_puzzle import read_puzzle_file, write_puzzle_file
from groups import entry_id


def cells(e):
    x, y, across = e["position"]["x"], e["position"]["y"], e["direction"] == "across"
    return [(x + i * across, y + i * (not across)) for i in range(e["length"])]


def weak_lights(puzzle, standing=None):
    """{light: why} of the lights of model-solved `puzzle` to clear: ours, a cell crossed by a light that is not the
    print's (blank, or ours), and no anagram of the clue (`standing(clue text, enumeration, pattern, answer, puzzle
    id)` -> bool, the default: trove_solution_ocr.clue_repeat gives it, or wordplay_fit spells it by an anagram
    that WordNet links to its clue)."""
    import file_archive_org_puzzles as archive
    ours = archive.our_lights(puzzle)
    if not ours:
        return {}
    es = {entry_id(e): e for e in puzzle["entries"]}
    by_cell = {}
    for lid, e in es.items():
        for rc in cells(e):
            by_cell.setdefault(rc, []).append(lid)
    letters = {}
    for lid, e in es.items():
        if e.get("solution") and len(e["solution"]) == e["length"]:
            for i, rc in enumerate(cells(e)):
                letters.setdefault(rc, {})[lid] = e["solution"][i]
    standing = standing or standing_route
    out = {}
    for lid in sorted(ours):
        e = es[lid]
        weak = [rc for rc in cells(e) if len(by_cell[rc]) > 1 and all(o in ours or not es[o].get("solution")
                                                                       for o in by_cell[rc] if o != lid)]
        if not weak:
            continue
        pattern = "".join(next((ch for o, ch in letters.get(rc, {}).items() if o != lid), "?") for rc in cells(e))
        clue = e.get("clue") or {}
        if not standing(clue.get("text"), clue.get("enumeration"), pattern, e["solution"], puzzle.get("id")):
            out[lid] = f"{e['solution']}: {len(weak)} crossing cell(s) not printed"
    return out


def standing_route(text, enum, pattern, answer, puzzle_id):
    """Whether a route that needs no printed crossing gives `answer`: the same clue elsewhere, or an anagram."""
    import file_archive_org_puzzles as archive
    if not text:
        return False
    if tso.clue_repeat(text, enum, pattern, puzzle_id) == answer:
        return True
    word = archive.wordplay_fit(text, pattern, enum)
    return word == answer and tso.clue_wordplay(text, len(pattern)).get(word) == "anagram" \
        and bool(tso.definition_linked(word, text))


def clear(puzzle, lights):
    """`puzzle` with `lights` blank (their annotations gone), its model detail dropped where none of ours is left;
    the ids that had an annotation."""
    import file_archive_org_puzzles as archive
    new = copy.deepcopy(puzzle)
    annotated = []
    for e in new["entries"]:
        if entry_id(e) in lights:
            if e.pop("annotation", None):
                annotated.append(entry_id(e))
            e["solution"] = None
    if not archive.our_lights(new):
        new = provenance.with_solution_detail(new, {k: v for k, v in provenance.solution_detail(new).items()
                                                    if k not in ("model", "date", "check", "printed")})
    return new, annotated


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the files (default: count only)")
    args = ap.parse_args(argv)
    seen = cleared = whole_lost = 0
    annotated = []
    for path in puzzle_paths.puzzle_files("times"):
        try:
            puzzle = read_puzzle_file(path)
        except (OSError, ValueError):
            continue
        lights = weak_lights(puzzle)
        if not lights:
            continue
        seen += 1
        cleared += len(lights)
        whole = all(e.get("solution") for e in puzzle["entries"])
        new, ann = clear(puzzle, lights)
        annotated += [(puzzle["id"], a) for a in ann]
        whole_lost += whole
        if args.apply:
            write_puzzle_file(path, new)
    print(f"clear_weak_fills: {cleared} lights of {seen} puzzles ({whole_lost} fully answered) "
          f"{'cleared' if args.apply else 'to clear'}; {len(annotated)} annotated lights")
    for pid, lid in annotated:
        print(f"  annotated: {pid} {lid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
