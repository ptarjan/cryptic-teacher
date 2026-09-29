#!/usr/bin/env python3
"""Assemble an original puzzle file from a grid fill plus authored clues.

The grid fill (tools/grid_fill.py) already knows the geometry: where every
entry starts, how long it is, and which word fills it. What it cannot know is
the clue. This script marries the two halves so the geometry is never retyped
by hand — retyping is how a solution and a position drift apart.

Output goes to puzzles/authored/<year>/authored-<number>.json, written by
tools/fetch_puzzle.write_puzzle_file exactly as it writes Guardian puzzles, so
the same schema, validator, app and smoke test apply to our own puzzles with no
special cases: the id is <series>-<number> like every other puzzle's, and the
source names us as publisher with no url, since nothing was fetched.

  python3 tools/build_authored_puzzle.py \
      --fill tools/data/sample_fill_11.json \
      --clues tools/data/authored_A001_clues.json \
      --number 1 --name "Cryptic Teacher No 1" --setter "Cryptic Teacher" \
      --date 2026-07-29 --annotated-by human

--annotated-by says who wrote the clues' annotations — `human`, or the exact
model id that drafted them — and lands in the top-level `annotatedBy`.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import provenance  # noqa: E402
import puzzle_paths  # noqa: E402
import series  # noqa: E402
from fetch_puzzle import write_puzzle_file  # noqa: E402


def build(fill_path, clues_path, number, name, setter, day):
    fill = json.loads(Path(fill_path).read_text())
    clues = json.loads(Path(clues_path).read_text())

    entries = []
    missing = []
    for e in fill["entries"]:
        eid = e["id"]
        spec = clues.get(eid)
        if not spec:
            missing.append(eid)
            continue
        ann = spec["annotation"]
        # The annotation's answer must be the letters the grid actually holds.
        # A silent mismatch here would put a clue for one word under another.
        letters = "".join(c for c in ann["answer"].upper() if c.isalpha())
        if letters != e["solution"]:
            sys.exit(
                f"{eid}: annotation answer {ann['answer']!r} gives {letters}, "
                f"but the grid holds {e['solution']}"
            )
        entries.append({
            "id": eid,
            "number": e["number"],
            "direction": e["direction"],
            "position": e["position"],
            "length": e["length"],
            "clue": spec["clue"],
            "solution": e["solution"],
            "annotation": ann,
        })

    if missing:
        sys.exit("no clue written for: " + ", ".join(missing))

    extra = set(k for k in clues if not k.startswith("_")) - {e["id"] for e in entries}
    if extra:
        sys.exit("clues written for entries not in the fill: " + ", ".join(sorted(extra)))

    entries.sort(key=lambda e: (e["number"], e["direction"]))
    size = fill["size"]
    return {
        "id": series.puzzle_id("authored", number),
        "number": number,
        "series": "authored",
        "name": name,
        "setter": setter,
        "date": day.isoformat(),
        "dimensions": {"cols": size, "rows": size},
        "entries": entries,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fill", default="tools/data/sample_fill_11.json")
    ap.add_argument("--clues", required=True)
    ap.add_argument("--number", type=int, required=True,
                    help="our own running number: 1 is Cryptic Teacher No 1")
    ap.add_argument("--name", required=True)
    ap.add_argument("--setter", default="Cryptic Teacher")
    ap.add_argument("--date", type=datetime.date.fromisoformat, required=True,
                    help="publication day, YYYY-MM-DD")
    ap.add_argument("--annotated-by", required=True,
                    help="who wrote the annotations: human, or an exact model id")
    args = ap.parse_args()

    puzzle = build(args.fill, args.clues, args.number, args.name, args.setter, args.date)
    if provenance.has_hints(puzzle):
        try:
            puzzle = provenance.credit_annotator(puzzle, args.annotated_by,
                                                 had_hints=False)
        except ValueError as err:
            sys.exit(f"--annotated-by: {err}")
    out = write_puzzle_file(puzzle_paths.file_for(puzzle), puzzle,
                            generator="tools/build_authored_puzzle.py")
    print(f"wrote {out} — {len(puzzle['entries'])} entries")


if __name__ == "__main__":
    main()
