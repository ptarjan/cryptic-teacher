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
import contextlib
import fcntl
import hashlib
import json
import os
import sys
import tempfile
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
    """{entry id ("22-across"): reason} for this puzzle's pending clues, less the
    stale ones (settled(): no detector the row names fires on the tree now), so
    the burn's bag and a run skip them without the file being rewritten under it;
    tools/prune_shape_queue.py drops the rows."""
    got = _by_entry(puzzle, pending().get(puzzle.get("id")))
    by_id = {f"{e['number']}-{e['direction']}": e for e in puzzle.get("entries") or []}
    return {k: why for k, why in got.items() if not settled(by_id[k], why)}


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


def _validator_rules():
    """{reason class: fn(tree, ann, clue) -> truthy when it fires}: the
    tools/validate_annotations.py rules a row's reason can name. The shape_suspects
    detectors (arity_ins, del_single, ...) are read from findings() instead."""
    import validate_annotations as V
    return {"anagramOfContainer": lambda t, a, c: V.anagram_of_container(t),
            "scrambledLeaf": lambda t, a, c: V.scrambled_leaves(t),
            "indFolded": lambda t, a, c: V.folded_indicators(t),
            "fakeParts": lambda t, a, c: V.fake_parts(t),
            "bareInCharade": lambda t, a, c: V.bare_in_charade(t, a),
            "inDefinition": lambda t, a, c: V.in_definition(a),
            "leafFold": lambda t, a, c: V.leaf_folds(t),
            "anaCharade": lambda t, a, c: V.anagram_charades(t)}


def settled(entry, reason):
    """True when every detector the row's reason names is known and none fires on
    the entry's annotation as it stands: the row is stale (the clue was fixed
    by another sweep, or the detector changed after the row was queued) and a
    run on it would redo a clue nothing flags (~4k tokens). A reason that names
    anything else (model-fixable, walkthrough, ...) or a clue with no tree is
    never settled: only the model can say those are done."""
    ann = entry.get("annotation")
    if not ann or ann.get("wordplay") is None:
        return False
    names = [p.split(":")[0].strip() for p in str(reason).split("; ")]
    rules = _validator_rules()
    import shape_suspects as ss
    if not names or any(n not in rules and n not in ss.PRECISION for n in names):
        return False
    fired = {f.split(":")[0] for f in findings(entry)}
    clue = (entry.get("clue") or {}).get("text", "")
    for n in names:
        if n in fired:
            return False
        if n in rules and rules[n](ann["wordplay"], ann, clue):
            return False
    return True


def regressions(entry, new):
    """Ways a listed clue's new annotation `new` gives up what the old one on
    file (the entry's own) had, as strings; [] when it gives up nothing. The
    comparison lives in the one validator, validate_annotations.redo_regressions."""
    import validate_annotations as V
    return V.redo_regressions(entry.get("annotation"), new, (entry.get("clue") or {}).get("text", ""))


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
    with locked():
        out = []
        for r in json.loads(PATH.read_text()):
            p, _, c = r["id"].partition("#")
            if p == puzzle["id"] and c in verdict:
                if verdict[c]:
                    out.append({**r, "tried": True})
                continue
            out.append(r)
        write(dump(out))
    return len(mine)


@contextlib.contextmanager
def locked():
    """Exclusive lock for a read-modify-write of the list. The lock is a file of
    its own, not PATH, because write() replaces PATH's inode."""
    lock = Path(tempfile.gettempdir()) / f"ct-shape-queue-{hashlib.sha1(str(PATH).encode()).hexdigest()[:12]}.lock"
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def write(text, path=None):
    """Replace the list with `text` in one step (a temp file beside it, then
    os.replace), so a reader, and the burn's `git add`, which takes no lock,
    sees the old file or the new one and never a truncated half: 16 "Annotate"
    commits (10-17) captured it empty while done() rewrote it in place."""
    path = Path(path or PATH)
    part = path.with_name(f".{path.name}.{os.getpid()}.part")
    with open(part, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(part, path)


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
