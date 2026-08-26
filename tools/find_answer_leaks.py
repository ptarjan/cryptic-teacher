#!/usr/bin/env python3
"""Find block notes that say the answer out loud.

The building blocks are the rung before the walkthrough, so a learner reads them
having deliberately not bought the solve. `app.js` refuses to render a `gives`
that equals the answer, which makes the letters safe; the prose is not, and a
note like "pulses are the crop family beans belong to" hands PULSE over.

Matching is word-run based rather than substring: the answer's letters have to
line up with whole words of the note, optionally carrying a short inflection, so
"run-in" is caught inside "a run-in is a quarrel" and OSLO inside "n(O SLO)venian"
while a short answer is not caught inside an unrelated longer word.

  python3 tools/find_answer_leaks.py            # ranked summary
  python3 tools/find_answer_leaks.py --json     # per-clue targets for a rewrite
"""

import argparse
import collections
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from fetch_puzzle import read_puzzle_file  # noqa: E402

PUZZLES = pathlib.Path(__file__).parent.parent / "puzzles"

# An inflection the same word can carry without becoming a different word. Longer
# tails are a different word and not a leak: "cutter" does not give away CUT.
INFLECTIONS = ("", "s", "es", "ed", "d", "ing", "n", "r", "rs", "ers")


def letters(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def says(text, answer):
    """Does `text` contain `answer` as a run of whole words?"""
    target = letters(answer)
    if len(target) < 3:
        return False
    words = [letters(w) for w in re.split(r"[^A-Za-z]+", text or "") if letters(w)]
    for i in range(len(words)):
        run = ""
        for j in range(i, min(i + len(target), len(words))):
            run += words[j]
            if len(run) > len(target) + 3:
                break
            if run.startswith(target) and run[len(target):] in INFLECTIONS:
                return True
    return False


def leaks():
    for path in sorted(PUZZLES.glob("*.js")):
        try:
            puzzle = read_puzzle_file(path)
        except Exception:
            continue
        for entry in puzzle.get("entries", []):
            ann = entry.get("annotation") or {}
            answer = ann.get("answer")
            if not answer:
                continue
            bad = [b for b in (ann.get("blocks") or []) if says(b.get("note"), answer)]
            if bad:
                yield {
                    "file": path.name,
                    "entry": entry.get("id"),
                    "clue": entry.get("clue"),
                    "type": ann.get("type"),
                    "answer": answer,
                    "notes": [{"clueFragment": b.get("clueFragment"), "note": b.get("note")}
                              for b in bad],
                }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit per-clue targets")
    args = ap.parse_args()

    found = list(leaks())
    if args.json:
        json.dump(found, sys.stdout, indent=1)
        return 1 if found else 0

    by_file = collections.Counter(f["file"] for f in found)
    by_type = collections.Counter(f["type"] for f in found)
    print(f"{len(found)} clue(s) in {len(by_file)} puzzle(s) name the answer in a block note.\n")
    print("worst puzzles:")
    for name, n in by_file.most_common(12):
        print(f"  {n:4d}  {name}")
    print("\nby type:")
    for name, n in by_type.most_common(10):
        print(f"  {n:4d}  {name}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
