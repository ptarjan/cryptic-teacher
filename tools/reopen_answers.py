#!/usr/bin/env python3
"""Send a model-solved grid's unparseable answers back to be solved again.

    python3 tools/reopen_answers.py <ID> --which    # the ids to reopen, one line
    python3 tools/reopen_answers.py <ID> <id> ...   # blank them in the file

A cold solve's answer can satisfy every crossing and still be wrong, and the
annotator that cannot parse it leaves the clue null, which fails validation.
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
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import annotate_check  # noqa: E402
import provenance  # noqa: E402
from fetch_puzzle import read_puzzle_file, resolve_puzzle, write_puzzle_file  # noqa: E402
from groups import entry_id  # noqa: E402


def reopenable(puzzle):
    """The leader ids of the model answers left null that may be reopened."""
    if provenance.solution_origin_from_file(puzzle) != "model":
        return []
    printed = provenance.printed_answers(puzzle)
    done = (puzzle.get("solutions") or {}).get("reopened") or {}
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    out = []
    for e in annotate_check.unsolved(puzzle):
        lights = [entry_id(e)] + [i for i in e.get("group") or [] if i != entry_id(e)]
        if all(i in by_id and by_id[i].get("solution") and i not in printed
               and i not in done for i in lights):
            out.append(entry_id(e))
    return out


def reopen(puzzle, ids):
    """`puzzle` with the lights of `ids` blanked and listed in solutions.reopened."""
    allowed = set(reopenable(puzzle))
    refused = [i for i in ids if i not in allowed]
    if refused:
        raise SystemExit(f"reopen_answers: {puzzle['id']}: {', '.join(refused)} cannot be "
                         f"reopened — only a model answer left null, once")
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    log = dict((puzzle.get("solutions") or {}).get("reopened") or {})
    for eid in ids:
        for light in by_id[eid].get("group") or [eid]:
            log[light] = by_id[light]["solution"]
            del by_id[light]["solution"]
    return provenance.with_solution_detail(
        puzzle, {**provenance.solution_detail(puzzle), "reopened": log})


def main(argv):
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv[:1] in (["-h"], ["--help"]) else 2
    path = resolve_puzzle(argv[0])
    puzzle = read_puzzle_file(path)
    if argv[1] == "--which":
        print(" ".join(reopenable(puzzle)))
        return 0
    write_puzzle_file(path, reopen(puzzle, argv[1:]))
    print(f"reopen_answers: {puzzle['id']}: {', '.join(argv[1:])} blanked to be solved again")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
