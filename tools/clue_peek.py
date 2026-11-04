"""Look at one clue of a puzzle file, and try a `wp` on it, without a script.

    python3 tools/annotate_check.py --show ID 6-down 9-across   # clue, answer, annotation on file
    python3 tools/annotate_check.py --try ID 6-down "<wp>"      # does this `wp` give 6-down's answer?

Annotation runs kept writing `python3 -c` for these two jobs and failing: a puzzle
file's `entries` are objects with `number` and `direction` and no `id`, their stored
annotation is under `annotation` with `wordplay` only where the clue has one, and
`wordplay.evaluate` wants the answer as well as the tree. Each such miss cost a turn
and a re-read of the whole conversation. These two commands do the lookup the way the
checker does, so there is nothing to get wrong.
"""
import json

import annotation
import wordplay


def find(puzzle, eid):
    """The entry whose id is `eid` ("6-down"), or None."""
    return next((e for e in puzzle.get("entries", []) if annotation.entry_id(e) == eid), None)


def _unknown(puzzle, eid):
    ids = ", ".join(annotation.entry_id(e) for e in puzzle.get("entries", []))
    return f"{eid}: no such entry; the puzzle's ids are {ids}"


def show(puzzle, ids):
    """Each named entry as filed: its clue, answer and stored annotation."""
    out = []
    for eid in ids:
        e = find(puzzle, eid)
        if e is None:
            out.append(_unknown(puzzle, eid))
            continue
        clue = e.get("clue") or {}
        head = f"{eid}  {e.get('solution')}  {clue.get('text')} ({clue.get('enumeration')})"
        ann = e.get("annotation")
        out.append(head + "\n" + (json.dumps(ann, ensure_ascii=False, indent=1) if ann
                                  else "(no annotation on file)"))
    return "\n\n".join(out)


def try_wp(puzzle, eid, wp):
    """What the checker would say of `wp` for entry `eid`: the stored tree when it
    gives the answer, else the same refusal line the apply step prints."""
    e = find(puzzle, eid)
    if e is None:
        return _unknown(puzzle, eid)
    clue = (e.get("clue") or {}).get("text") or ""
    answer = e.get("solution") or ""
    try:
        tree = wordplay.translate({"wp": wp, "notes": {}}, clue, answer)
    except wordplay.WordplayError as err:
        return f"{eid} {answer}: {err}"
    return f"{eid} {answer}: ok, the letters come out\n" + json.dumps(tree, ensure_ascii=False, indent=1)
