#!/usr/bin/env python3
"""Fill the blank lights of a blog-keyed puzzle that the grid itself settles.

A blog write-up that leaves a light out gives a puzzle `solutions.partial`
naming it (tools/apply_blog_answers.py). Where every cell of such a blank is
crossed by an answered light the letters are known, so the answer is fixed and
nothing is guessed. A blank with exactly one unchecked cell is filled only on
the blog's own word: a word in that puzzle's cached write-up with the light's
exact length, the crossing letters in place, in the lexicon, and the only such
word. The lexicon alone never fills a light. Nothing already answered is
touched; filled lights leave `solutions.partial`, and a puzzle left with no
blanks is complete (fetch_puzzle.puzzle_is_solved).

Write-ups are read from the cache apply_blog_answers keeps; nothing is fetched.

  python3 tools/fill_checked_lights.py            # report counts
  python3 tools/fill_checked_lights.py --write    # fill and save
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import apply_blog_answers as blog
import parse_timesforthetimes as ptt
from fetch_puzzle import puzzle_is_solved, read_puzzle_file, write_puzzle_file
from groups import entry_id

ROOT = Path(__file__).resolve().parent.parent
MIN_LENGTH = 4      # a shorter word is too easy to find in prose by chance


def spots(entry):
    x, y = entry["position"]["x"], entry["position"]["y"]
    return [(x + i, y) if entry["direction"] == "across" else (x, y + i)
            for i in range(entry["length"])]


def letter_cells(puzzle):
    """cell -> letter from the answered lights, or None when two answers
    disagree at a cell (the file is not to be trusted there)."""
    cells = {}
    for e in puzzle["entries"]:
        word = (e.get("solution") or "").strip()
        if not word:
            continue
        if len(word) != e["length"]:
            return None
        for cell, ch in zip(spots(e), word.upper()):
            if cells.setdefault(cell, ch) != ch:
                return None
    return cells


def blanks(puzzle):
    return [e for e in puzzle["entries"] if not (e.get("solution") or "").strip()]


def pattern(entry, cells):
    """The light's letters known from answered crossings; None where unchecked."""
    return [cells.get(s) for s in spots(entry)]


def blog_text(puzzle):
    """The plain text of the puzzle's cached write-ups ('' when none is cached)."""
    series, number = puzzle["id"].rsplit("-", 1)[0], puzzle["number"]
    texts = []
    if series in blog.CATEGORIES:
        day = datetime.date.fromisoformat(puzzle["date"])
        for y, m in {(day.year, day.month), (day.year + (day.month == 12), day.month % 12 + 1)}:
            for cat in blog.CATEGORIES[series]:
                path = blog.CACHE / f"{cat}-{y}-{m:02d}.json"
                if path.exists():
                    texts += [p["content"]["rendered"] for p in json.loads(path.read_text(encoding="utf-8"))
                              if ptt.puzzle_number(p) == number]
    else:
        path = (blog.CACHE / "ft" / f"ftcryptic-{number}.json" if series == "ftcryptic"
                else blog.CACHE / f"azed-{number}.json" if series == "azed"
                else blog.CACHE / "bigdave-2" / f"{series}-{number}.json")
        if path.exists():
            for p in json.loads(path.read_text(encoding="utf-8")):
                texts.append(p["content"]["rendered"] if "content" in p
                             else " ".join(str(r[2]) for r in p.get("rows", [])))
    return " ".join(blog.cell_text(t) for t in texts)


def named_words(text, known):
    """Distinct upper-case runs (one to three words of the text) that fit `known`
    exactly: the light's length, the crossing letters in place."""
    words = blog.WORDS.findall(text)
    found = set()
    for i in range(len(words)):
        for n in (1, 2, 3):
            run = words[i:i + n]
            letters = re.sub(r"[^A-Z]", "", "".join(run).upper())
            if (len(run) == n and len(letters) == len(known)
                    and all(k is None or k == c for k, c in zip(known, letters))):
                found.add(letters)
    return found


def fill_puzzle(puzzle, text=None):
    """{entry id: answer} for the blanks the grid or the write-up settles.
    Rounds repeat, since a filled light checks the cells of the next."""
    fill = {}
    cells = letter_cells(puzzle)
    if cells is None:
        return fill
    text = blog_text(puzzle) if text is None else text
    lexicon = blog.lexicon()
    for _ in range(len(puzzle["entries"])):
        progress = False
        for e in blanks(puzzle):
            eid = entry_id(e)
            if eid in fill:
                continue
            known = pattern(e, cells)
            unchecked = known.count(None)
            if unchecked == 0:
                word = "".join(known)
            elif unchecked == 1 and e["length"] >= MIN_LENGTH:
                fits = {w for w in named_words(text, known) if w in lexicon}
                if len(fits) != 1:
                    continue
                word = fits.pop()
            else:
                continue
            fill[eid] = word
            for cell, ch in zip(spots(e), word):
                cells[cell] = ch
            progress = True
        if not progress:
            break
    return fill


def apply(puzzle, fill):
    """Write the fill into the puzzle and drop the filled ids from solutions.partial."""
    for e in puzzle["entries"]:
        if entry_id(e) in fill:
            e["solution"] = fill[entry_id(e)]
    detail = puzzle.get("solutions") or {}
    left = [i for i in detail.get("partial") or [] if i not in fill]
    if left:
        detail["partial"] = left
    else:
        detail.pop("partial", None)


def candidates():
    """The paths of the files that carry solutions.partial."""
    out = subprocess.run(["git", "grep", "-l", '"partial"', "--", "puzzles"], cwd=ROOT,
                         capture_output=True, text=True, check=False).stdout.split()
    return [ROOT / p for p in out if p.endswith(".json")]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    count = Counter()
    touched = []
    for path in candidates():
        puzzle = read_puzzle_file(path)
        if not isinstance((puzzle.get("solutions") or {}).get("partial"), list):
            continue
        before = blanks(puzzle)
        if not before:
            continue
        count["puzzles with blanks"] += 1
        count["blank lights"] += len(before)
        cells = letter_cells(puzzle) or {}
        count["blanks fully checked"] += sum(pattern(e, cells).count(None) == 0 for e in before)
        fill = fill_puzzle(puzzle)
        if fill:
            count["lights filled"] += len(fill)
            touched.append(puzzle["id"])
            if args.write:
                apply(puzzle, fill)
                write_puzzle_file(path, puzzle)
            count["now complete"] += not blanks(puzzle) and puzzle_is_solved(puzzle) if args.write else (
                len(fill) == len(before))
        left = [e for e in blanks(puzzle)] if args.write else [e for e in before if entry_id(e) not in fill]
        count["blanks left"] += len(left)
        after = letter_cells(puzzle) or {}
        count["left with 2+ unchecked"] += sum(pattern(e, after).count(None) >= 2 for e in left)
    count["puzzles touched"] = len(touched)
    print(json.dumps(dict(count), indent=1))
    print("touched:", " ".join(touched))


if __name__ == "__main__":
    sys.exit(main())
