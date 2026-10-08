"""Clue text is stored with straight quotes; the site curls them on display.

Sources serve the same apostrophe as ' or ’, and OCR reads one as `, so a
corpus that kept what each source served would hold one clue three ways and
compare them as three clues. Every puzzle file therefore stores ' and " only:
fetch_puzzle.write_puzzle_file straightens every write through straighten(),
puzzle_integrity's CURLY check refuses anything else, and app.js turns them
back into ‘ ’ “ ” when it shows a clue (quotes.js).

Each mapping is one character for one, so every offset into a clue (a
definition's `at`, italics, a mark) means the same before and after.

    python3 tools/quotes.py            # straighten every held puzzle file
    python3 tools/quotes.py FILE...    # just those
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STRAIGHT = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "`": "'"})
CURLY = frozenset("\u2018\u2019\u201c\u201d`")


def straight(text):
    """`text` with every curly quote and backtick made ' or "."""
    return text.translate(STRAIGHT) if isinstance(text, str) else text


def _clue_strings(entry):
    """(holder, key) of every string in `entry` that holds the clue's own
    words: the clue, and each annotation field that quotes it
    (puzzle_integrity.annotation_quotes, features.misdirectedWord, an
    anagram's fodder), which must keep matching it character for character."""
    out = [(entry.get("clue") or {}, "text")]
    ann = entry.get("annotation")
    if isinstance(ann, dict):
        for name, key in (("definitions", "text"), ("indicators", "text"), ("blocks", "clueFragment")):
            out += [(d, key) for d in ann.get(name) or [] if isinstance(d, dict)]
        words = ann.get("linkWords")
        if isinstance(words, list):
            out += [(words, i) for i in range(len(words))]
        out.append((ann.get("features") or {}, "misdirectedWord"))
        out += [(a, "fodder") for a in (ann.get("assembly") or {}).get("anagrams") or []
                if isinstance(a, dict)]
    return [(h, k) for h, k in out
            if isinstance(h, list) or (isinstance(h, dict) and isinstance(h.get(k), str))]


def straighten(puzzle):
    """`puzzle` with its clue text straight: itself when it already is, else
    a copy, so the caller's puzzle is left as it was."""
    if not curly(puzzle):
        return puzzle
    puzzle = copy.deepcopy(puzzle)
    for e in puzzle.get("entries") or []:
        for holder, key in _clue_strings(e):
            if isinstance(holder[key], str):
                holder[key] = straight(holder[key])
    return puzzle


def curly(puzzle):
    """[(entry, field, text)] of each clue string still holding a curly quote
    or a backtick."""
    out = []
    for e in puzzle.get("entries") or []:
        for holder, key in _clue_strings(e):
            text = holder[key]
            if isinstance(text, str) and CURLY & set(text):
                out.append((e, key, text))
    return out


def main(argv):
    import puzzle_paths
    from fetch_puzzle import read_puzzle_file
    paths = [Path(a) for a in argv] or sorted(puzzle_paths.PUZZLE_DIR.glob("*/*/*.json"))
    files = chars = 0
    for path in paths:
        puzzle = read_puzzle_file(path)
        found = sum(sum(c in CURLY for c in text) for _, _, text in curly(puzzle))
        if not found:
            continue
        body = json.dumps(straighten(puzzle), indent=1, ensure_ascii=False) + "\n"
        path.write_text(body, encoding="utf-8")
        files += 1
        chars += found
    print(f"straightened {chars} quote marks in {files} of {len(paths)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
