#!/usr/bin/env python3
"""Whether a puzzle's clues can belong to its answers, asked before a session.

    python3 tools/clue_answer_fit.py check ID [ID ...]   # exit 1, saying why, for the first misfiled one

A fetch can pair one puzzle's clue text with another puzzle's grid (the Gale
Sunday Times pages print an earlier week's solution grid beside this week's
clues, and a solution heading read for the wrong week pairs the wrong two; see
tools/file_archive_org_puzzles.py SUNDAY_WEEKLY). The lengths fit, since the
grids are alike, so nothing structural gives it away. The annotate burn found out the expensive way: 11-16, eleven Sunday Times
puzzles (3612, 3865, 3911, 3960, 3964, 3968 ...) each paid a session before it
withdrew with "every clue is from a different puzzle".

The cheap test: in a cryptic clue the answer's letters usually show in the
clue's wordplay. A hidden word (the answer, or its reverse, inside the clue's
letters), an anagram (a run of up to six consecutive words with exactly the
answer's letters), an acrostic (the answer inside the clues' initials), or four
letters in a row the clue and the answer share. Measured over the 917 Sunday
Times files with 10 or more answers, about 14% of clues of a good puzzle show one
(a puzzle's 5th percentile is 4%), and a puzzle from another's grid shows
nearly none: 3612, 3960, 3964 show 0 of 30 to 32. So a puzzle is misfiled when it
has at least MIN_CLUES answered clues, shows at most MAX_HITS of them, and none of
its entries has an annotation (an annotated puzzle was read by a session that
found the clues fit). Deliberately narrow: it misses a puzzle with clues but no
answers (an unsolved one has nothing to compare), and it errs to skipping, which
costs a refetch, never to deleting: the caller records the puzzle in the failed
inputs ledger, which releases it by itself when the puzzle's file changes.
"""
import json
import re
import sys
from pathlib import Path

MIN_CLUES = 24
MAX_HITS = 1


OK_FILE = Path(__file__).parent / "data" / "clue_answer_fit_ok.txt"


def reviewed_ok(path=None):
    """Ids checked by hand whose clues fit (old-style definitions show few
    letters): one per line, `id  # reason`. `check` passes them."""
    path = Path(path or OK_FILE)
    if not path.exists():
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.add(line)
    return ids


def letters(text):
    return re.sub(r"[^a-z]", "", text.lower())


def shows_answer(text, answer):
    """True when the clue's letters show the answer's (hidden, anagram,
    acrostic or a shared run of four), False when not, None for a clue too
    short to say anything."""
    a = letters(answer)
    if len(a) < 4:
        return None
    text = re.sub(r"\(.*?\)\s*$", "", text)
    words = [letters(w) for w in re.findall(r"[A-Za-z']+", text)]
    flat = "".join(words)
    if a in flat or a[::-1] in flat:
        return True
    if a in "".join(w[0] for w in words if w):
        return True
    ordered = sorted(a)
    for i in range(len(words)):
        run = ""
        for word in words[i:i + 6]:
            run += word
            if len(run) == len(a) and sorted(run) == ordered:
                return True
            if len(run) > len(a):
                break
    return any(a[k:k + 4] in flat for k in range(len(a) - 3))


def misfiled(puzzle):
    """Why this puzzle's clues cannot be its answers', or None."""
    entries = puzzle.get("entries") or []
    if any(e.get("annotation") for e in entries):
        return None
    shown = counted = 0
    for e in entries:
        answer = e.get("solution")
        clue = e.get("clue")
        text = clue.get("text") if isinstance(clue, dict) else clue
        if not answer or not isinstance(text, str):
            continue
        fit = shows_answer(text, answer)
        if fit is None:
            continue
        counted += 1
        shown += bool(fit)
    if counted >= MIN_CLUES and shown <= MAX_HITS:
        return (f"its clues do not belong to its answers: only {shown} of {counted} clues show "
                f"their answer's letters (a good puzzle shows about 1 in 7), so the clue text "
                f"is from another puzzle than the grid; refetch it")
    return None


def main(argv):
    if argv[:1] != ["check"] or len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    import puzzle_paths
    ok = reviewed_ok()
    for pid in argv[1:]:
        if pid in ok:
            continue
        path = puzzle_paths.find(pid)
        if not path:
            continue
        why = misfiled(json.loads(Path(path).read_text(encoding="utf-8")))
        if why:
            print(f"{pid}: {why}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
