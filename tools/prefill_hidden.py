#!/usr/bin/env python3
"""Write the annotation of a near-certain hidden word without a model run.

    python3 tools/prefill_hidden.py                 # dry run over every puzzle: counts
    python3 tools/prefill_hidden.py -v PUZZLE.json  # the annotations, in the model's shape
    python3 tools/prefill_hidden.py --out DIR       # one DIR/<puzzle id>.json per puzzle
    python3 tools/prefill_hidden.py --write [--slice K/N] [--limit M] [FILES]

For each clue annotate_check.to_write would send to the annotator, the clue is
read by tools/hidden_mechanical.py; when it parses as a hidden word the model's
shape annotation (`def`, `wp`, `notes`, the prompt's Schema) is built here, run
through annotation.from_model onto a copy of the puzzle, and kept only if
validate_annotations finds nothing wrong with that clue. Nothing is written into
puzzles/: the --out files are what apply_annotations reads (`--annotate-only`
view lists the clues), and the annotator is shown the rest.

What a clue still needs from a model, because no table holds it: the
`explanation` (surface scene, definitionFit) and `features`. They are left out.
"""
import argparse
import copy
import json
import sys
from pathlib import Path

import annotate_check
import annotation
import apply_annotations
import hidden_mechanical
import puzzle_schema
import validate_annotations
import wordplay
from groups import entry_id

ROOT = Path(__file__).resolve().parent.parent

#: Credited in annotatedBy for --write: the model that ran the tool.
WRITER = "claude-opus-5-5"

HIDDEN_NOTE = "{} says the answer is a run of letters hidden inside the words that follow"
REVERSAL_NOTE = "{} says the hidden letters are read backwards"
FODDER_NOTE = "the letters run across the end of one word into the next"


def leaf(words, gives):
    return f"[{words}]{gives}"


def model_annotation(found, clue, answer):
    """The model's-shape annotation for a hidden_mechanical.find() result."""
    answer = "".join(c for c in answer.upper() if c.isalpha())
    words = found["fodder"]
    start = clue.index(words)
    fodder = clue[start:start + len(words)]
    hidden, reversal = found["hidden"], found["reversal"]
    reversed_ = found["direction"] == "reversed"
    inner = f"hid{'<' + hidden + '>' if hidden else ''}({leaf(fodder, answer[::-1] if reversed_ else answer)})"
    wp = f"rev<{reversal}>({inner})" if reversed_ else inner
    notes = {fodder: FODDER_NOTE}
    if hidden:
        notes[hidden] = HIDDEN_NOTE.format(hidden)
    if reversal:
        notes[reversal] = REVERSAL_NOTE.format(reversal)
    return {"def": found["definition"], "wp": wp, "notes": notes}


def candidates(puzzle):
    """The unannotated entries a run would write, as annotate_check.to_write
    lists them (the whole puzzle's clues when it has no hints yet)."""
    listed = annotate_check.to_write(puzzle, None)
    return [e for e in puzzle["entries"]
            if (listed is None or entry_id(e) in listed) and not e.get("annotation")
            and e.get("solution") and (e.get("clue") or {}).get("text")
            and not e.get("alteration")]


def tag_of(entry):
    return f"{entry['number']}{'A' if entry['direction'] == 'across' else 'D'}"


def prefill_puzzle(puzzle):
    """{entry id: model-shape annotation} for each candidate clue that is a
    near-certain hidden word and whose annotation validates."""
    found = {}
    for e in candidates(puzzle):
        clue = e["clue"]["text"]
        hit = hidden_mechanical.find(clue, e["solution"])
        if hit:
            found[entry_id(e)] = model_annotation(hit, clue, e["solution"])
    if not found:
        return {}
    trial = copy.deepcopy(puzzle)
    by_id = {entry_id(e): e for e in trial["entries"]}
    built = {}
    for eid, model in found.items():
        try:
            by_id[eid]["annotation"] = annotation.from_model(model, by_id[eid], trial)
            built[eid] = model
        except wordplay.WordplayError:
            continue
    _, errors, _ = validate_annotations.validate_puzzle(puzzle_schema.order(trial))
    return {eid: model for eid, model in built.items()
            if not any(err.startswith(tag_of(by_id[eid]) + ":") for err in errors)}


def whole_puzzle_errors(path, puzzle, got):
    """The errors `validate_annotations.py <id>` would report once `got` is
    written into the puzzle: the prefill has no surface, definitionFit or
    features, and a puzzle with any annotation must have every clue annotated
    and explained, so writing a prefill into a puzzle that is not otherwise
    finished turns an OK puzzle into a FAIL one."""
    trial = copy.deepcopy(puzzle)
    by_id = {entry_id(e): e for e in trial["entries"]}
    for eid, model in got.items():
        by_id[eid]["annotation"] = annotation.from_model(model, by_id[eid], trial)
    return validate_annotations.run_errors(path, puzzle_schema.order(trial))


def has_unannotated(path):
    """Cheap pre-filter: False when the file is unreadable or every clued entry
    already has an annotation, so the full parse is skipped."""
    try:
        data = json.loads(Path(path).read_text())
        entries = data["entries"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return any(isinstance(e, dict) and not e.get("annotation") and e.get("solution")
               and (e.get("clue") or {}).get("text") for e in entries)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", help="puzzle files (default: every puzzle)")
    ap.add_argument("--out", help="write DIR/<puzzle id>.json for each puzzle with a prefill")
    ap.add_argument("-v", action="store_true", help="print each annotation")
    ap.add_argument("--write", action="store_true",
                    help="write the annotations into the puzzle files (apply_annotations, annotateOnly)")
    ap.add_argument("--slice", metavar="K/N", help="only the Kth of N interleaved slices of the file list")
    ap.add_argument("--limit", type=int, help="stop after this many puzzles are prefilled")
    args = ap.parse_args(argv)
    import fetch_puzzle
    paths = [Path(p) for p in args.paths] or sorted((ROOT / "puzzles").rglob("*.json"))
    if args.slice:
        k, n = (int(x) for x in args.slice.split("/"))
        paths = paths[k::n]
    total = puzzles = blocked = 0
    for path in paths:
        if args.limit and puzzles >= args.limit:
            break
        if not has_unannotated(path):
            continue
        try:
            puzzle = fetch_puzzle.read_puzzle_file(path)
            got = prefill_puzzle(puzzle)
        except (OSError, ValueError, SystemExit):
            continue
        except Exception as err:  # one odd puzzle must not end a corpus run
            print(f"{path}: {type(err).__name__}: {err}", file=sys.stderr)
            continue
        if not got:
            continue
        puzzles += 1
        total += len(got)
        if args.v:
            print(path.name, json.dumps(got, indent=1, ensure_ascii=False))
        if args.write:
            failing = whole_puzzle_errors(path, puzzle, got)
            if failing:
                blocked += len(got)
                puzzles -= 1
                total -= len(got)
                continue
            try:
                apply_annotations.apply(path, got, by=WRITER, only=list(got))
            except SystemExit as err:   # a refusal leaves the file as it was
                print(f"{path.name}: refused: {err}", file=sys.stderr)
                puzzles -= 1
                total -= len(got)
                continue
            print(f"wrote {path.relative_to(ROOT)} {' '.join(got)}")
        if args.out:
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{puzzle['id']}.json").write_text(json.dumps(got, indent=1, ensure_ascii=False) + "\n")
    held = f", {blocked} more held back: the whole puzzle would fail validation" if blocked else ""
    print(f"{total} clues in {puzzles} puzzles prefilled{held}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
