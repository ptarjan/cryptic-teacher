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
at the end of apply). The detectors are the gate, not the prompt: apply refuses
a tree for a listed clue that they still flag (findings()), so a run cannot
re-file the old tree with new prose and call it done. A clue the run nulls keeps
its old hint and its row, marked "tried", so it is not redone; pending() skips
tried rows. A later write in the same run still settles it (done() looks at
every listed row, tried or not).

The row changes ship in the puzzle's own commit (tools/own_rows.py), so a
pruned row reaches master with the tree that settled it, and a discarded run
puts its rows back."""
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


_pending_cache = {}


def pending():
    """{puzzle id: {clue key ("22a"): reason}} for the rows not yet tried."""
    rs = rows()
    if _pending_cache.get("rows") is not rs:  # rows() returns one list per file version
        out = {}
        for r in rs:
            if r.get("tried"):
                continue
            pid, _, clue = r["id"].partition("#")
            out.setdefault(pid, {})[clue] = r.get("reason", "")
        _pending_cache.update(rows=rs, out=out)
    return _pending_cache["out"]


def puzzle_ids():
    return set(pending())


def clue_key(entry):
    return f"{entry.get('number')}{(entry.get('direction') or '?')[:1]}"


def _by_entry(puzzle, want):
    if not want:
        return {}
    return {f"{e['number']}-{e['direction']}": want[clue_key(e)]
            for e in puzzle.get("entries") or [] if clue_key(e) in want}


def flagged(puzzle):
    """{entry id ("22-across"): reason} for this puzzle's pending clues."""
    return _by_entry(puzzle, pending().get(puzzle.get("id")))


def listed(puzzle):
    """{entry id: reason} for every listed clue of this puzzle, tried or not:
    the ones apply holds to the detectors."""
    want = {}
    for r in rows():
        pid, _, clue = r["id"].partition("#")
        if pid == puzzle.get("id"):
            want[clue] = r.get("reason", "")
    return _by_entry(puzzle, want)


def findings(entry, ann=None):
    """The precise detectors' findings on `ann` (default: the entry's own
    annotation) as "detector: what" strings; [] when they pass it."""
    import clue_shapes as cs
    import shape_suspects as ss
    ann = entry.get("annotation") if ann is None else ann
    if not ann or ann.get("wordplay") is None:
        return []
    wp = ann["wordplay"]
    row = {"id": "", "series": "", "clue": (entry.get("clue") or {}).get("text", ""),
           "sol": entry.get("solution", ""), "sk": cs.analyse(wp)[0], "line": cs.compact(wp),
           "wp": wp, "defs": ann.get("definitions") or [], "andLit": bool(ann.get("andLit"))}
    return [f"{k}: {v}" if isinstance(v, str) else k
            for _, hits in ss.run_detectors([row]) for k, v in hits.items() if k in ss.PRECISION]


def _tree_nodes(node):
    """Every node of a wordplay tree, the root first."""
    if isinstance(node, dict):
        yield node
        for part in node.get("parts") or []:
            yield from _tree_nodes(part)


def _words(text):
    import re
    return set(re.findall(r"[a-z]+", re.sub(r"<[^>]*>|\([^)]*\)", " ", (text or "").lower())))


def _accounted(ann, with_leaves=True):
    """The clue words an annotation accounts for: wordplay leaves (when
    `with_leaves`), indicators on any op or definition, definitions, and
    declared link words."""
    got = set()
    for n in _tree_nodes(ann.get("wordplay")):
        if with_leaves and "op" not in n:
            got |= _words(n.get("words"))
        for i in n.get("indicators") or []:
            got |= _words(i.get("text") if isinstance(i, dict) else i)
    for d in ann.get("definitions") or []:
        got |= _words(d.get("text"))
        for i in d.get("indicators") or []:
            got |= _words(i.get("text") if isinstance(i, dict) else i)
    for lw in ann.get("linkWords") or []:
        got |= _words(lw)
    return got


def _double_definition(ann, clue):
    """True when `ann` is a double (or triple) definition: two or more
    definitions and no wordplay tree, whose texts and link words cover every
    clue word."""
    defs = ann.get("definitions") or []
    return len(defs) >= 2 and _words(clue) <= _accounted(ann)


def regressions(entry, new):
    """Ways a listed clue's new annotation `new` gives up what the old one on
    file (the entry's own) had, as strings; [] when it gives up nothing. The
    detectors only judge the new tree's shape, so a rewrite that cut the
    problem leaf, nulled the wordplay or dropped Spooner would pass them:
      - a clue word that was in a wordplay leaf or an indicator of the old
        tree must still be in a leaf, an indicator, a definition or a link
        word of the new one (deleting unexplained text is not a fix);
      - a tree where there was one is not replaced by none;
      - a Spooner clue keeps its spoonerism."""
    old = entry.get("annotation") or {}
    out = []
    wp = (new or {}).get("wordplay")
    clue = (entry.get("clue") or {}).get("text", "")
    if not wp or not (wp.get("op") or wp.get("words")):
        if old.get("wordplay") and not _double_definition(new, clue):
            out.append("no_tree: the new annotation has no wordplay tree where the old one had one")
            return out
    elif "spooner" in clue.lower() and not any(n.get("op") == "spoonerism" for n in _tree_nodes(new["wordplay"])):
        out.append("lost_spoonerism: the clue names Spooner and the tree has no spoonerism op")
    if old.get("wordplay"):
        lost = (_accounted(old) - _accounted(new)) & _words(clue)
        if lost:
            out.append("dropped_words: " + ", ".join(sorted(lost)) + " were in the old wordplay "
                       "(a leaf or an indicator) and are in no leaf, indicator, definition or link word now")
    return out


def still_flagged(entry):
    """The detectors' verdict on this entry's annotation as it stands now."""
    return bool(findings(entry))


def done(puzzle, written, held=()):
    """Account for the clues a run just filed: `written` is the entry ids it
    gave an annotation, `held` the ones whose null kept the old hint. A written
    clue the detectors pass is pruned; a held one (or a written one they still
    flag, which apply refuses before it gets here) is marked tried. Every
    listed row counts, tried or not, so a fix later in the run still prunes.
    Returns how many listed clues it settled."""
    by_id = {f"{e['number']}-{e['direction']}": e for e in puzzle["entries"]}
    mine = {k for k in listed(puzzle) if (k in written or k in held) and k in by_id}
    if not mine:
        return 0
    verdict = {clue_key(by_id[k]): k in held or still_flagged(by_id[k]) for k in mine}
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
        f.write(dump(out))
    return len(mine)


def dump(out):
    """The list's layout: one row per line, as tools/fix_shape_suspects.py
    writes it, so rows of different puzzles are different lines."""
    return "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n]\n"


def splice(base, donor, pid):
    """`base` (the list's text) with pid's rows as `donor` has them, each after
    the row it follows in donor that base also holds, so splicing back the
    text a splice started from gives it byte for byte (tools/own_rows.py)."""
    def ours(r):
        return r["id"].partition("#")[0] == pid
    b, d = json.loads(base or "[]"), json.loads(donor or "[]")
    others = {r["id"] for r in b if not ours(r)}
    after, anchor = {}, None
    for r in d:
        if not ours(r):
            anchor = r["id"] if r["id"] in others else anchor
        else:
            after.setdefault(anchor, []).append(r)
    out = list(after.get(None, []))
    for r in b:
        if not ours(r):
            out += [r] + after.get(r["id"], [])
    return dump(out)
