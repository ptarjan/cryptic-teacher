#!/usr/bin/env python3
"""Write tools/data/lexicons/spellings.json: answer letters -> the spelling with an
apostrophe or an accent that an annotation in puzzles/ gives it (`spelling`).

tools/lesson_checks.py reads it to flag the same answer filed without one
(FLANEUR for FLÂNEUR, ILLSAY for I'LL SAY). Run it again after annotations land;
it keeps every entry it has and adds what the corpus now attests, the commonest
spelling winning, so it only grows.

    python3 tools/build_spellings.py
"""
import collections
import json
import multiprocessing
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "data" / "lexicons" / "spellings.json"
#: The marks that make a spelling worth keeping: an apostrophe or any non-ASCII letter.
MARKED = re.compile(r"['’]|[^\x00-\x7f]")


def _read(path):
    try:
        puzzle = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for e in puzzle.get("entries") or []:
        said = (e.get("annotation") or {}).get("spelling")
        if said and MARKED.search(said):
            out.append(said)
    return out


def main():
    import lesson_checks
    files = sorted((ROOT / "puzzles").glob("**/*.json"))
    seen = collections.defaultdict(collections.Counter)
    with multiprocessing.Pool() as pool:
        for spellings in pool.imap_unordered(_read, files, 32):
            for said in spellings:
                seen[lesson_checks.letters(said)][said.replace("’", "'")] += 1
    known = json.loads(OUT.read_text()) if OUT.exists() else {}
    for key, counts in seen.items():
        known.setdefault(key, counts.most_common(1)[0][0])
    OUT.write_text(json.dumps(dict(sorted(known.items())), ensure_ascii=False, indent=0) + "\n")
    print(f"{len(known)} spellings in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
