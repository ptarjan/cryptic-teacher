#!/usr/bin/env python3
"""Drop the clues-only copy of a puzzle that is filed with its grid.

    python3 tools/drop_clues_only_twin.py puzzles/<series>/<year>/<id>.json ...
    python3 tools/drop_clues_only_twin.py --all      # every id held both ways

One id, one state (tools/clues_only.py): a puzzle filed under puzzles/ leaves
clues_only/<series>/<id>.json. apply_solution's promotion drops it, and
tools/commit_puzzles.sh calls this for every puzzle it commits, so no filer
leaves the stale reading behind (times-26591, 11-17). Prints each path it
staged for removal (git rm: index and tree). A twin is kept, and reported on
stderr, when it holds anything the puzzle lacks: the puzzle has no full grid
and clues, or has no clue text where the twin has one. The conflict resolver
(tools/resolve_promotion_conflict.py) carries re-read clue text for a racing
write; this is the plain case, and a difference is for a person to judge.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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


def main(argv):
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
        else:
            why = problems(puzzle, held)
        if why:
            kept += 1
            print(f"KEPT {twin}: {'; '.join(why)}", file=sys.stderr)
            continue
        subprocess.run(["git", "rm", "-q", "-f", "--ignore-unmatch", "--", str(twin)],
                       cwd=ROOT, check=True)
        print(twin)
    return 1 if kept else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
