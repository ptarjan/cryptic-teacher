"""Hide a puzzle's published answers from the annotator, then grade what it
derived against them.

  python3 tools/blind_annotate.py hide cryptic-30103   # stash the key, blank it
  python3 tools/blind_annotate.py restore              # put it back, grade, report

WHY. The annotator is handed the published solution and told to make its parse
produce those letters. That is a check, and it is the reason a shipped hint is
trustworthy — but it is also a way to be wrong invisibly. A model that already
knows the answer is BLIND MOTIVATED to find some route to it, and a plausible
route to the right letters is not the same thing as the setter's actual
wordplay. Nothing in the pipeline can tell those apart, because the answer the
explanation "arrives at" was in the prompt.

Taking the key away restores the one measurement the key destroys: an
explanation that reaches the wrong answer is visibly wrong. Accuracy against
the withheld key is therefore a lower bound on how often the wordplay was
actually understood rather than reverse-engineered.

WHAT IT COSTS, AND WHAT IT DOES NOT. Nothing here re-annotates a puzzle that
already has hints — this runs on the night a puzzle is first annotated, on the
same single pass it was going to get anyway, so a blind night costs what a
sighted night costs. The comparison is against the runs already in the corpus.

SAFETY. The site never ships a wrong answer because of this. restore always
puts the published key back, whatever the model wrote; only the ANNOTATION is
affected, and only on entries the model got wrong, where it is dropped
entirely. An explanation built on a wrong answer is wrong from its first line,
so a missed entry ships with no teaching ladder rather than a confident one —
the same policy fetch_puzzle.merge_annotations applies when a prize puzzle's
official key finally lands.

The stash is written before the puzzle file is blanked, and restore sweeps
every stash it finds rather than taking an id, so a run that dies between the
two leaves the key recoverable by the next run rather than only by git.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_puzzle import read_puzzle_file, resolve_puzzle, write_puzzle_file

ROOT = Path(__file__).resolve().parent.parent
STASH_DIR = ROOT / ".blind"


def hide(arg):
    path = resolve_puzzle(arg)
    puzzle = read_puzzle_file(path)
    stash = STASH_DIR / f"{puzzle['id']}.json"
    if stash.exists():
        # The stash is the only copy of the key at this point. Blanking a file
        # that is already blank would overwrite it with nothing.
        raise SystemExit(f"{stash} already exists — run `restore` first")

    key = {e["id"]: e.get("solution") for e in puzzle["entries"]}
    if not all(key.values()):
        raise SystemExit(f"{puzzle['id']} has no published key to hide "
                         f"({sum(1 for v in key.values() if not v)} entries "
                         f"unanswered) — it is already a blind solve")
    if (puzzle.get("solutionSource") or {}).get("kind") == "model":
        # A prize grid we filled ourselves. The letters are there, but they are
        # our own guess, so hiding them and grading against them would score the
        # model against itself and call the agreement accuracy.
        raise SystemExit(f"{puzzle['id']}'s answers are our own model fill, not a "
                         f"published key — there is no ground truth to grade against")

    STASH_DIR.mkdir(exist_ok=True)
    stash.write_text(json.dumps(key, indent=1, ensure_ascii=False), encoding="utf-8")

    for e in puzzle["entries"]:
        e["solution"] = ""
    write_puzzle_file(path, puzzle, generator="tools/blind_annotate.py --hide")
    print(f"BLIND ANNOTATE: hid {len(key)} answers for {puzzle['id']}")
    return 0


def restore():
    """Put every stashed key back, grade what the model wrote against it.

    Sweeps rather than taking an id: the caller that hid a key may not be alive
    to name it, and a key left stashed is a key only git still has.
    """
    stashes = sorted(STASH_DIR.glob("*.json")) if STASH_DIR.is_dir() else []
    if not stashes:
        return 0

    for stash in stashes:
        path = resolve_puzzle(stash.stem)
        puzzle = read_puzzle_file(path)
        key = json.loads(stash.read_text(encoding="utf-8"))

        # A grid still completely blank is one nothing ran against: the hide
        # succeeded and the annotation call died, or the run was killed between
        # the two. Grading that scores the model on a paper it never sat and
        # nulls all 29 annotations, which is how this pass would turn a crashed
        # night into a destroyed puzzle. Put the key back and say nothing.
        if not any((e.get("solution") or "").strip() for e in puzzle["entries"]):
            for e in puzzle["entries"]:
                if key.get(e["id"]):
                    e["solution"] = key[e["id"]]
            write_puzzle_file(path, puzzle, generator="tools/fetch_puzzle.py")
            print(f"BLIND ANNOTATE: {puzzle['id']} was never attempted — key restored, "
                  f"nothing graded")
            stash.unlink()
            continue

        wrong = []
        for e in puzzle["entries"]:
            truth = key.get(e["id"])
            if truth is None:          # an entry the stash never covered
                continue
            guess = e.get("solution") or ""
            if guess.strip().upper() != truth.strip().upper():
                wrong.append((e["id"], guess or "(nothing)", truth))
                e["annotation"] = None
            e["solution"] = truth

        write_puzzle_file(path, puzzle, generator="tools/fetch_puzzle.py")
        total = len(key)
        print(f"BLIND ANNOTATE GRADED {puzzle['id']}: {total - len(wrong)}/{total} "
              f"correct without the key")
        for eid, mine, theirs in wrong:
            print(f"  miss {eid}: model said {mine}, answer is {theirs}")
        stash.unlink()
    return 0


def main(argv):
    if len(argv) == 3 and argv[1] == "hide":
        return hide(argv[2])
    if len(argv) == 2 and argv[1] == "restore":
        return restore()
    raise SystemExit(__doc__.strip().splitlines()[2].strip() + "\n"
                     "usage: blind_annotate.py hide <puzzle> | restore")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
