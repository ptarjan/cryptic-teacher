#!/usr/bin/env python3
"""Count which op each indicator word is filed under, across the annotated corpus.

    python3 tools/build_indicator_roles.py   # rewrite tools/data/indicator_roles.json

tools/validate_annotations.wrong_role_indicators reads the table: an indicator
the corpus files under one op type nearly always ("to limit" on a container,
"returned" on a reversal) is flagged on an op of another type. Every word of at
least ROLE_KEEP_USES uses is kept: the rule reads a word's owner off its counts,
and a word that serves several ops (about, over, out, round) shows no owner
there. Published puzzles only, unchecked steps skipped, so a hand-written clue
cannot vote for its own rule.

Rows: {indicator letters: {op type: uses}}, the op types of
validate_annotations._OP_LEXICON (anagram, reversal, container, deletion,
hidden_word, homophone, letter_selection, spoonerism) plus charade and others.
"""

import collections
import json
from pathlib import Path

import wordplay
from puzzle_paths import puzzle_files

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "data" / "indicator_roles.json"

ROLE_KEEP_USES = 20


def derive():
    import validate_annotations as va
    table = collections.defaultdict(collections.Counter)
    for path in puzzle_files():
        try:
            puzzle = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        if puzzle.get("series") == "authored":
            continue
        for entry in puzzle.get("entries") or []:
            tree = (entry.get("annotation") or {}).get("wordplay")
            for node in va._walk(tree) if tree else ():
                op = node.get("op")
                if not op or node.get("unchecked"):
                    continue
                for ind in node.get("indicators") or []:
                    key = va.indicator_role_key(ind.get("text"))
                    if key:
                        table[key][va._OP_LEXICON.get(op, op)] += 1
    keep = {}
    for key, counts in table.items():
        total = sum(counts.values())
        if total >= ROLE_KEEP_USES:
            keep[key] = dict(sorted(counts.items()))
    return dict(sorted(keep.items()))


def main():
    rows = derive()
    OUT.write_text("{\n" + ",\n".join(f"{json.dumps(k)}: {json.dumps(v, sort_keys=True)}"
                                      for k, v in rows.items()) + "\n}\n")
    print(f"{len(rows)} indicator words -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
