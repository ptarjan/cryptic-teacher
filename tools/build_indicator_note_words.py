#!/usr/bin/env python3
"""Write tools/data/indicator_note_words.json: the words of the language indicator
notes are written in.

    python3 tools/build_indicator_note_words.py

check_indicator_notes_name_no_block refuses a note that uses a block's clue
word, since the indicators rung comes before the blocks. A word that hundreds
of the corpus's notes use about other clues ("something", "new", "another",
"letters", "end") is how indicator notes talk, so on the clue where it is also
a block's word it names nothing. Every corpus note is held to the check, so a
word's count here comes only from notes where it is not a block's word.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from fetch_puzzle import puzzle_files, read_puzzle_file  # noqa: E402

OUT = TOOLS / "data" / "indicator_note_words.json"
MIN_NOTES = 500     # of ~150k notes; the commonest block-only word ("money") is in 150


def note_words(note):
    return set(re.findall(r"[a-z]+", re.sub(r"['’]s\b", "", str(note or "").lower())))


def main():
    df = Counter()
    for path in puzzle_files():
        for e in read_puzzle_file(path).get("entries", []):
            for ind in (e.get("annotation") or {}).get("indicators") or []:
                if isinstance(ind, dict) and ind.get("note"):
                    df.update(note_words(ind["note"]))
    words = sorted(w for w, n in df.items() if n >= MIN_NOTES)
    OUT.write_text(json.dumps(words, indent=0) + "\n", encoding="utf-8")
    print(f"{len(words)} words in at least {MIN_NOTES} indicator notes -> {OUT.relative_to(TOOLS.parent)}")


if __name__ == "__main__":
    main()
