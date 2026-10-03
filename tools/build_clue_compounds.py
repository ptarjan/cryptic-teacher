#!/usr/bin/env python3
"""Count how the corpus's clues print two-word compounds: hyphenated or closed.

    python3 tools/build_clue_compounds.py      # rewrites tools/data/clue_compounds.tsv

A scan's line-end hyphen may break a word ("back-" / "street") or be a
compound's own ("short-" / "lived"), and a reader that returns its text
unbroken (the VLM) keeps that hyphen inside the line ("pre-decessor").
tools/ocr_clues.py's clean() and unhyphen() ask this table: each row is
"first-second<TAB>clues printing it hyphenated<TAB>clues printing it closed",
for compounds of two lexicon words whose closed form the lexicon lacks, and
for every hyphenated form the clues print of a word the lexicon has closed
("co-operate").
"""
import collections
import glob
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from ocr_clues import rank


def is_word(word):
    """Whether the lexicon itself has the word: not ocr_clues.is_word, which
    also takes this table's closed compounds, so a rebuild would drop them."""
    return rank(word) is not None or word in ("a", "i")


OUT = TOOLS / "data" / "clue_compounds.tsv"


def counts():
    seen = collections.Counter()
    for path in glob.glob(str(ROOT / "puzzles" / "*" / "*" / "*.json")):
        try:
            puzzle = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        for e in puzzle.get("entries", ()):
            text = ((e.get("clue") or {}).get("text") or "").lower()
            seen.update(re.findall(r"[a-z]+(?:-[a-z]+)*", text))
    return seen


def rows(seen):
    out = {}
    for token, n in seen.items():
        parts = token.split("-")
        if len(parts) == 2:
            a, b = parts
            if is_word(a + b) or (len(a) > 1 and len(b) > 1 and is_word(a) and is_word(b)):
                out[token] = (n, seen.get(a + b, 0))
        elif len(parts) == 1 and n >= 2 and not is_word(token):
            for i in range(2, len(token) - 1):
                a, b = token[:i], token[i:]
                if is_word(a) and is_word(b):
                    out.setdefault(f"{a}-{b}", (seen.get(f"{a}-{b}", 0), n))
    return out


def main():
    found = rows(counts())
    lines = [f"{k}\t{h}\t{c}" for k, (h, c) in sorted(found.items())]
    OUT.write_text("# compound\thyphenated\tclosed  (tools/build_clue_compounds.py)\n"
                   + "\n".join(lines) + "\n")
    print(f"{len(found)} compounds -> {OUT}")


if __name__ == "__main__":
    main()
