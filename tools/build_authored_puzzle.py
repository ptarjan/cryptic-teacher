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
source names us as publisher with no url, since nothing was fetched. It
refuses to write a puzzle tools/validate_annotations.py has an ERROR for, so
the authoring rules (a stated scene on every clue, a joke on half of them)
cannot be skipped by not running the validator. It also refuses a hidden
answer that sits inside one word or starts or ends on a word boundary
(hidden_edge_errors), a rule for
clues we set that the corpus validator does not hold published clues to.

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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import definitions  # noqa: E402
import provenance  # noqa: E402
import puzzle_paths  # noqa: E402
import puzzle_schema  # noqa: E402
import series  # noqa: E402
import validate_annotations  # noqa: E402
from fetch_puzzle import write_puzzle_file  # noqa: E402
from groups import entry_id  # noqa: E402


def build(fill_path, clues_path, number, name, setter, day):
    fill = json.loads(Path(fill_path).read_text())
    clues = json.loads(Path(clues_path).read_text())

    entries = []
    missing = []
    for e in fill["entries"]:
        eid = entry_id(e)
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

    extra = set(k for k in clues if not k.startswith("_")) - {entry_id(e) for e in entries}
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


# A word, with any apostrophe or hyphen inside it: "friend's" and
# "ham-fistedly" are one word each.
WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")


def hidden_edge_errors(puzzle):
    """A hidden answer, read forwards or reversed, must take letters from two or
    more words and neither start nor end on a word boundary: CHEAP in "Che
    apparel" starts on the whole word "Che", and PREY in "Osprey" sits inside
    one word and ends where it does. Of 2,591 published forward hidden words, 2
    start on a boundary and 2 end on one; 267 sit inside one word, a device we
    do not use. An answer found more than once passes if any one run does."""
    errors = []
    for e in puzzle["entries"]:
        ann = e.get("annotation") or {}
        types = set(ann.get("type") or [])
        if "hidden_word" not in types or not types <= {"hidden_word", "reversal"}:
            continue
        letters, word = [], []
        for n, w in enumerate(WORD.findall(e["clue"]["text"])):
            for c in w:
                if c.isalpha():
                    letters.append(c.upper())
                    word.append(n)
        text = "".join(letters)
        target = e["solution"][::-1] if "reversal" in types else e["solution"]
        runs = [i for i in range(len(text)) if text.startswith(target, i)]
        inside = [i for i in runs
                  if 0 < i and word[i - 1] == word[i]
                  and i + len(target) < len(text)
                  and word[i + len(target)] == word[i + len(target) - 1]
                  and word[i] != word[i + len(target) - 1]]
        if not inside:
            where = ("is not in the clue" if not runs else
                     "starts or ends on a word boundary, or sits inside one word")
            errors.append(f"{e['number']}-{e['direction']}: hidden {target} {where}; "
                          "a hidden answer must cross a space and begin and end inside words "
                          "(tools/author_trial_author.md, hidden words)")
    return errors


def finish(puzzle, annotated_by):
    """The built puzzle as write_puzzle_file will write it, and its validator
    ERRORs. The refusal must judge the written form: the schema requires the
    `source`, `solutions` and definition offsets that the write path adds.
    Raises ValueError for an --annotated-by that provenance does not accept."""
    if provenance.has_hints(puzzle):
        puzzle = provenance.credit_annotator(puzzle, annotated_by, had_hints=False)
    puzzle = provenance.stamp(puzzle, "tools/build_authored_puzzle.py")
    puzzle = puzzle_schema.order(definitions.place_puzzle(puzzle_schema.prune(puzzle)))
    _, errors, warnings = validate_annotations.validate_puzzle(puzzle)
    # The Pages build runs the corpus validator, ratchet included, over this
    # puzzle; refusing less here would ship a file that fails the deploy.
    errors += validate_annotations.backlog_errors(puzzle["id"], warnings)
    return puzzle, errors + hidden_edge_errors(puzzle)


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
    try:
        puzzle, errors = finish(puzzle, args.annotated_by)
    except ValueError as err:
        sys.exit(f"--annotated-by: {err}")
    if errors:
        sys.exit("refusing to write: tools/validate_annotations.py has "
                 f"{len(errors)} ERROR(s)\n  " + "\n  ".join(errors))
    out = write_puzzle_file(puzzle_paths.file_for(puzzle), puzzle,
                            generator="tools/build_authored_puzzle.py")
    print(f"wrote {out} — {len(puzzle['entries'])} entries")


if __name__ == "__main__":
    main()
