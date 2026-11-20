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

    python3 tools/build_indicator_roles.py --limit 200   # trial on ~200 puzzles, writes nothing

tools/data/indicator_kinds.json says which kind of selection (first, last,
middle, outer, alternate, nth) or deletion (head, tail, heart, outer, named)
each kept word was used for, read off the op (selection) or the letters cut
(deletion); the /indicators/ page splits those types by it.

Rows: {indicator letters: {op type: uses}}, the op types of
validate_annotations._OP_LEXICON (anagram, reversal, container, deletion,
hidden_word, homophone, letter_selection, spoonerism) plus charade and others.
"""

import collections
import json
import sys
from pathlib import Path

import wordplay
from puzzle_paths import puzzle_files

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "data" / "indicator_roles.json"
KINDS_OUT = ROOT / "tools" / "data" / "indicator_kinds.json"

ROLE_KEEP_USES = 20
HEART_SLACK = 1  # how far from the exact centre a cut may sit and still be the heart


def _single(node):
    """The one string a node gives, or None (several readings, or it needs the answer)."""
    try:
        got = wordplay.values(node)
    except Exception:  # _NeedTarget, WordplayError: this node cannot be read alone
        return None
    return next(iter(got)) if len(got) == 1 else None


def deletion_kind(node):
    """Which cut a deletion makes, read off its letters: head (the whole's start
    comes off), tail (its end), heart (the centre, within HEART_SLACK of exact),
    outer (first and last together), or named (letters from elsewhere, the
    indicator naming what goes). None where the parts cannot be read or the cut
    fits two kinds (ALA less A)."""
    parts = wordplay.parts_of(node)
    if len(parts) < 2:
        return None
    whole = _single(parts[0])
    gone = [_single(p) for p in parts[1:]]
    if not whole or not all(gone):
        return None
    cut = "".join(gone)
    if len(cut) >= len(whole):
        return None
    kinds = set()
    if whole.startswith(cut):
        kinds.add("head")
    if whole.endswith(cut):
        kinds.add("tail")
    if len(whole) > 2 and cut == whole[0] + whole[-1]:
        kinds.add("outer")
    at = whole.find(cut)
    if 0 < at and at + len(cut) < len(whole) and abs(at - (len(whole) - at - len(cut))) <= HEART_SLACK:
        kinds.add("heart")
    if not kinds:
        return "named"
    return kinds.pop() if len(kinds) == 1 else None


def node_kind(node):
    """(op type, kind) for a selection or deletion node, else None."""
    op = node.get("op")
    if op in wordplay.SELECT:
        return "letter_selection", {"alternate": "alternate", "regular": "alternate"}.get(op, op)
    if op == "deletion":
        kind = deletion_kind(node)
        return ("deletion", kind) if kind else None
    return None


def derive(limit=None):
    """(rows, kinds): rows {indicator: {op type: uses}} as above; kinds
    {indicator: {"letter_selection:first": uses, "deletion:tail": uses, ...}} for
    the same kept words. `limit` reads about that many puzzles, evenly spread
    (a trial run)."""
    import validate_annotations as va
    table = collections.defaultdict(collections.Counter)
    kind_table = collections.defaultdict(collections.Counter)
    files = puzzle_files()
    if limit:
        files = files[::max(1, len(files) // limit)]
    for path in files:
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
                kind = node_kind(node) if node.get("indicators") else None
                for ind in node.get("indicators") or []:
                    key = va.indicator_role_key(ind.get("text"))
                    if key:
                        table[key][va._OP_LEXICON.get(op, op)] += 1
                        if kind:
                            kind_table[key][f"{kind[0]}:{kind[1]}"] += 1
    keep = {}
    for key, counts in table.items():
        total = sum(counts.values())
        if total >= ROLE_KEEP_USES:
            keep[key] = dict(sorted(counts.items()))
    kinds = {k: dict(sorted(c.items())) for k, c in sorted(kind_table.items()) if k in keep}
    return dict(sorted(keep.items())), kinds


def _write(path, rows):
    path.write_text("{\n" + ",\n".join(f"{json.dumps(k)}: {json.dumps(v, sort_keys=True)}"
                                       for k, v in rows.items()) + "\n}\n")


def main():
    limit = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--limit" else None
    rows, kinds = derive(limit)
    if limit:  # a trial: show, write nothing
        print(f"{len(rows)} words, {len(kinds)} with kinds; sample:")
        for k in list(kinds)[:15]:
            print(" ", k, kinds[k])
        return
    _write(OUT, rows)
    _write(KINDS_OUT, kinds)
    print(f"{len(rows)} indicator words -> {OUT.relative_to(ROOT)}; "
          f"{len(kinds)} with kinds -> {KINDS_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
