#!/usr/bin/env python3
"""Send a model-solved grid's unparseable answers back to be solved again.

    python3 tools/reopen_answers.py <ID> --which    # the ids to reopen, one line
    python3 tools/reopen_answers.py <ID> <id> ...   # blank them in the file
    python3 tools/reopen_answers.py <ID> --ran <run's file> <id> ...

A cold solve's answer can satisfy every crossing and still be wrong, and the
annotator that cannot parse it leaves the clue null, or writes a hint that
doubts it ("unconfirmed until the published key"), and either fails validation.
Parked in tools/failed_inputs.py, that puzzle would wait forever, because
nothing changes its inputs. So the burn blanks those answers instead: the
puzzle is unsolved again, the queue solves it cold around everything else, and
the solve is shown the answer that failed (tools/solve_packet.py).

Once per entry. Each answer blanked is kept in solutions.reopened, which
apply_solution.py carries across the re-solve, and --which leaves out every
entry already in it, so a second null on the same clue is parked as usual.
The paper's printed answers are never reopened; provenance.check refuses it.

--which reads the file as the annotate run left it, before the burn discards
the run: the nulls it lists are the run's. It prints nothing for a grid that is
not a model's.

--ran names a copy of that file. A puzzle solved and hinted in one run has no
committed solve, so the file the discard puts back holds no answers to blank;
the run's answers and solution detail are taken from the copy first, and its
annotations left behind. A clues-only puzzle that run promoted has no grid
file once discarded: its grid is built again from the copy's answers
(clues_only.promote), and writing it retires the clues-only file.
"""
import re
import sys
from pathlib import Path

import annotate_check
import clues_only
import provenance
import puzzle_paths
import validate_annotations
from fetch_puzzle import read_puzzle_file, resolve_puzzle, write_puzzle_file
from groups import entry_id


def reopenable(puzzle):
    """The leader ids of the model answers left null that may be reopened."""
    if provenance.solution_origin_from_file(puzzle) != "model":
        return []
    printed = provenance.printed_answers(puzzle)
    done = (puzzle.get("solutions") or {}).get("reopened") or {}
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    out = []
    # A null the run left, or an answer its annotation doubts
    # (validate_annotations.doubted_model_answers): both are a parse the
    # annotator could not stand behind, and both fail validation.
    doubted = validate_annotations.doubted_model_answers(puzzle)
    for e in annotate_check.unsolved(puzzle) + [e for e in puzzle["entries"] if entry_id(e) in doubted]:
        lights = [entry_id(e)] + [i for i in e.get("group") or [] if i != entry_id(e)]
        if all(i in by_id and by_id[i].get("solution") and i not in printed
               and i not in done for i in lights):
            out.append(entry_id(e))
    return out


def with_runs_answers(puzzle, ran):
    """`puzzle` carrying `ran`'s model solve, when only the run holds one."""
    if (provenance.solution_origin_from_file(puzzle) == "model"
            or provenance.solution_origin_from_file(ran) != "model"):
        return puzzle
    answers = {entry_id(e): e["solution"] for e in ran["entries"] if e.get("solution")}
    for e in puzzle["entries"]:
        if entry_id(e) in answers:
            e["solution"] = answers[entry_id(e)]
    return {**puzzle, "solutions": ran["solutions"]}


def jigsaw_answers(record, ran):
    """{"unplaced": [...]}: the run's answer to each of jigsaw `record`'s
    clues, in the printed order. The run filed each clue on whichever light
    its answer fitted, so a clue is found by its text, on its leader or its
    off-grid item; a linked answer is the leader's letters, then each
    continuation's ("See N" lights carry no clue of their own)."""
    by_id = {entry_id(e): e for e in ran["entries"]}
    found = {}
    for e in ran["entries"]:
        lights = [entry_id(e)] + [i for i in e.get("group") or [] if i != entry_id(e)]
        found.setdefault(clue_text(e.get("clue")),
                         "".join(by_id[i].get("solution") or "" for i in lights if i in by_id))
    for item in ran.get("offGrid") or []:
        found.setdefault(clue_text(item.get("clue")), item.get("solution") or "")
    return {"unplaced": [found.get(clue_text(light["clue"]), "")
                         for light in record["clues"]["unplaced"]]}


def clue_text(clue):
    """A clue's words, from a file's {"text": ...} or a string, its count dropped."""
    text = (clue.get("text") if isinstance(clue, dict) else clue) or ""
    return re.sub(r"\s*\([\d,\-\s]+\)$", "", text).strip()


def promoted(record, ran):
    """Clues-only `record`'s grid, unsolved, as the run `ran` promoted it."""
    if "unplaced" in record["clues"]:
        answers = jigsaw_answers(record, ran)
    else:
        answers = {d: [e.get("solution") or "" for e in sorted(
            (e for e in ran["entries"] if e["direction"] == d), key=lambda e: e["number"])]
            for d in clues_only.DIRECTIONS}
    puzzle, problems = clues_only.promote(record, answers)
    if problems:
        raise SystemExit(f"reopen_answers: {record['id']}: the run's answers do not rebuild "
                         f"its grid: {'; '.join(problems[:3])}")
    return puzzle


def reopen(puzzle, ids, ran=None):
    """`puzzle` with the lights of `ids` blanked and listed in solutions.reopened."""
    if ran is not None:
        puzzle = with_runs_answers(puzzle, ran)
    allowed = set(reopenable(puzzle))
    refused = [i for i in ids if i not in allowed]
    if refused:
        raise SystemExit(f"reopen_answers: {puzzle['id']}: {', '.join(refused)} cannot be "
                         f"reopened — only a model answer left null or doubted by its annotation, once")
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    log = dict((puzzle.get("solutions") or {}).get("reopened") or {})
    for eid in ids:
        for light in by_id[eid].get("group") or [eid]:
            log[light] = by_id[light]["solution"]
            del by_id[light]["solution"]
            # A hedged hint for the word being sent back explains nothing.
            by_id[light].pop("annotation", None)
    return provenance.with_solution_detail(
        puzzle, {**provenance.solution_detail(puzzle), "reopened": log})


def main(argv):
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv[:1] in (["-h"], ["--help"]) else 2
    ran = generator = None
    if argv[1] == "--ran":
        ran = read_puzzle_file(Path(argv[2]))
        argv = argv[:1] + argv[3:]
    record = ran and not puzzle_paths.find(argv[0]) and clues_only.read(argv[0])
    if record:
        puzzle = promoted(record, ran)
        path, generator = puzzle_paths.file_for(puzzle), record["source"]["acquiredBy"]
    else:
        path = resolve_puzzle(argv[0])
        puzzle = read_puzzle_file(path)
    if argv[1] == "--which":
        print(" ".join(reopenable(puzzle)))
        return 0
    write_puzzle_file(path, reopen(puzzle, argv[1:], ran), generator=generator)
    print(f"reopen_answers: {puzzle['id']}: {', '.join(argv[1:])} blanked to be solved again")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
