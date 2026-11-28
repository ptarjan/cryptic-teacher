#!/usr/bin/env python3
"""Drop the clues-only copy of a puzzle that is filed with its grid.

    python3 tools/drop_clues_only_twin.py puzzles/<series>/<year>/<id>.json ...
    python3 tools/drop_clues_only_twin.py --all      # every id held both ways
    python3 tools/drop_clues_only_twin.py --force puzzles/<series>/<year>/<id>.json
                                                     # drop it though it holds more

One id, one state (tools/clues_only.py): a puzzle filed under puzzles/ leaves
clues_only/<series>/<id>.json. apply_solution's promotion drops it, and
tools/commit_puzzles.sh calls this for every puzzle it commits, so no filer
leaves the stale reading behind (times-26591, 11-17). Prints each path it
staged for removal (git rm: index and tree). A twin is kept, and reported on
stderr, when it holds anything the puzzle lacks: the puzzle has no full grid
and clues, or has no clue text where the twin has one. Whatever
the twin holds that an entry lacks (its blog answers, merge()) is written into
the puzzle and staged before the twin goes; --force drops a twin whose clue text
differs, but still keeps one whose blog answers fit no entry. The conflict resolver
(tools/resolve_promotion_conflict.py) carries re-read clue text for a racing
write; this is the plain case, and a difference is for a person to judge.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import puzzle_schema

ROOT = Path(__file__).resolve().parent.parent
DIRECTIONS = ("across", "down")


def twin_of(puzzle_path):
    """clues_only/<series>/<id>.json for puzzles/<series>/<year>/<id>.json."""
    parts = Path(puzzle_path).parts
    return Path("clues_only") / parts[-3] / parts[-1]


def problems(puzzle, twin):
    """Why dropping `twin` would lose something `puzzle` lacks; [] when nothing.
    The puzzle needs its grid (a position and length per light) and every
    clue's text; an unsolved puzzle needs no answers. Any clue text of the twin
    that the puzzle does not hold is a difference to judge, so the twin stays."""
    entries = puzzle.get("entries") or []
    if not entries:
        return ["the puzzle has no entries"]
    out = []
    for e in entries:
        name = f"{e.get('number')}{str(e.get('direction'))[:1]}"
        if not e.get("position") or not e.get("length"):
            out.append(f"{name} has no grid cell or length")
        if not (e.get("clue") or {}).get("text"):
            out.append(f"{name} has no clue text")
    if out:
        return out
    have = {" ".join(e["clue"]["text"].split()) for e in entries}
    for direction in DIRECTIONS:
        for light in (twin.get("clues") or {}).get(direction) or []:
            text = " ".join(((light.get("clue") or {}).get("text") or "").split())
            if text and text not in have:
                out.append(f"clue {text!r} is not in the puzzle")
    return out


def squash(text):
    """A clue's letters and digits alone: the two readings of one clue differ in spacing, dashes, markers."""
    return "".join(c for c in (text or "").lower() if c.isalnum())


def merge(puzzle, twin):
    """(changed, unplaced): carry what the twin's lights hold and the puzzle's
    entries lack into the puzzle (puzzle edited in place). A clues-only light
    carries a clue, a length and a `blogAnswer` (cluesOnlyLight); the clue and
    length the puzzle has, so the blog's answer is what moves, onto the one
    entry whose clue reads the same (letters and digits only) and whose length
    the answer fits. The twin's direction only breaks a tie between two such
    entries: a clues-only reading can list a down clue among the acrosses, while
    a clue's words and its answer's length are the puzzle's own. A light that
    names no such entry, or two in its own direction, is `unplaced`."""
    changed, unplaced = False, []
    entries = puzzle.get("entries") or []
    for direction in DIRECTIONS:
        for light in (twin.get("clues") or {}).get(direction) or []:
            answer = light.get("blogAnswer")
            if not answer:
                continue
            key = squash((light.get("clue") or {}).get("text"))
            at = [e for e in entries if squash((e.get("clue") or {}).get("text")) == key
                  and e.get("length") == len(answer)]
            if len(at) > 1:
                at = [e for e in at if e.get("direction") == direction]
            if len(at) != 1:
                unplaced.append(f"{direction} {answer}")
            elif at[0].get("blogAnswer") is None:
                at[0]["blogAnswer"] = answer
                changed = True
    return changed, unplaced


def main(argv):
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    if argv == ["--all"]:
        have = {p.name: p for p in (ROOT / "clues_only").glob("*/*.json")}
        argv = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "puzzles").glob("*/*/*.json"))
                if p.name in have and p.parent.parent.name == have[p.name].parent.name]
    kept = 0
    for name in argv:
        twin = twin_of(name)
        if not (ROOT / twin).is_file():
            continue
        try:
            puzzle = json.loads((ROOT / name).read_text(encoding="utf-8"))
            held = json.loads((ROOT / twin).read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            why = [f"unreadable ({err})"]
            puzzle = None
        else:
            why = problems(puzzle, held)
        forced = force and puzzle is not None
        if puzzle is not None and (not why or forced):
            # Nothing the twin holds is lost: its blog answers go into the puzzle first.
            changed, unplaced = merge(puzzle, held)
            if unplaced:
                why = why + [f"blog answers with no entry: {', '.join(unplaced)}"]
                forced = False
            elif changed:
                # Keys in the schema's order, as every puzzle writer keeps them.
                (ROOT / name).write_text(json.dumps(puzzle_schema.order(puzzle), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                subprocess.run(["git", "add", "--", name], cwd=ROOT, check=True)
        if why and not forced:
            kept += 1
            print(f"KEPT {twin}: {'; '.join(why)}", file=sys.stderr)
            continue
        subprocess.run(["git", "rm", "-q", "-f", "--ignore-unmatch", "--", str(twin)],
                       cwd=ROOT, check=True)
        print(twin)
    return 1 if kept else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
