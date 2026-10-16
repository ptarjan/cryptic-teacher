#!/usr/bin/env python3
"""The clues whose wordplay tree tools/shape_suspects.py flags and
tools/fix_shape_suspects.py could not repair: tools/data/shape_reannotate.json,
{"id": "<puzzle>#<number><a|d>", "reason": ...} per clue (Paul 10-15: "Mechanical
fixes first, re-annotate the rest behind hinting", per clue, not per puzzle).

The burn queues their puzzles as the LAST tier (prereset_plan.backlog), and a run
on one writes just the listed clues (annotate_check.to_write), with the flag
reason in the view (`flagged`). The old annotation stays live until the new one
validates; a null never blanks it (apply_annotations holds it).

A clue leaves the list when apply_annotations files its new annotation (done(),
at the end of apply): the row is pruned when the detectors no longer flag the new
tree. A tree still flagged keeps its row marked "tried", so it is not redone and
the list never grows: pending() skips tried rows."""
import fcntl
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PATH = Path(__file__).resolve().parent / "data" / "shape_reannotate.json"
_cache = {}


def rows():
    """The list's rows, re-read only when the file changes."""
    try:
        st = PATH.stat()
    except OSError:
        return []
    key = (st.st_mtime_ns, st.st_size, str(PATH))
    if _cache.get("key") != key:
        try:
            _cache.update(key=key, rows=json.loads(PATH.read_text()))
        except ValueError:
            _cache.update(key=key, rows=[])
    return _cache["rows"]


def pending():
    """{puzzle id: {clue key ("22a"): reason}} for the rows not yet tried."""
    out = {}
    for r in rows():
        if r.get("tried"):
            continue
        pid, _, clue = r["id"].partition("#")
        out.setdefault(pid, {})[clue] = r.get("reason", "")
    return out


def puzzle_ids():
    return set(pending())


def clue_key(entry):
    return f"{entry.get('number')}{(entry.get('direction') or '?')[:1]}"


def flagged(puzzle):
    """{entry id ("22-across"): reason} for this puzzle's pending clues."""
    want = pending().get(puzzle.get("id"))
    if not want:
        return {}
    return {f"{e['number']}-{e['direction']}": want[clue_key(e)]
            for e in puzzle.get("entries") or [] if clue_key(e) in want}


def still_flagged(entry):
    """The detectors' verdict on this entry's annotation as it stands now."""
    import clue_shapes as cs
    import shape_suspects as ss
    ann = entry.get("annotation")
    if not ann or ann.get("wordplay") is None:
        return False
    wp = ann["wordplay"]
    row = {"id": "", "series": "", "clue": (entry.get("clue") or {}).get("text", ""),
           "sol": entry.get("solution", ""), "sk": cs.analyse(wp)[0], "line": cs.compact(wp),
           "wp": wp, "defs": ann.get("definitions") or [], "andLit": bool(ann.get("andLit"))}
    return any(k in ss.PRECISION for _, hits in ss.run_detectors([row]) for k in hits)


def done(puzzle, written):
    """Account for the clues a run just filed: `written` is the entry ids it
    gave an annotation. Prune those no longer flagged, mark the rest tried.
    Returns how many listed clues it settled."""
    by_id = {f"{e['number']}-{e['direction']}": e for e in puzzle["entries"]}
    mine = {k for k in flagged(puzzle) if k in written and k in by_id}
    if not mine:
        return 0
    verdict = {clue_key(by_id[k]): still_flagged(by_id[k]) for k in mine}
    with open(PATH, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        out = []
        for r in json.load(f):
            p, _, c = r["id"].partition("#")
            if p == puzzle["id"] and c in verdict:
                if verdict[c]:
                    out.append({**r, "tried": True})
                continue
            out.append(r)
        f.seek(0)
        f.truncate()
        f.write("[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n]\n")
    return len(mine)
