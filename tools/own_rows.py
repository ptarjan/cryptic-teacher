#!/usr/bin/env python3
"""One puzzle's rows of the shared source-correction tables, and no one else's.

    python3 tools/own_rows.py stage ID...   # index: HEAD's file + each ID's rows as the tree has them
    python3 tools/own_rows.py revert ID   # tree: ID's rows put back as HEAD has them
    python3 tools/own_rows.py paths       # the files holding those rows, one per line
    python3 tools/own_rows.py graft ID DIR  # tree: ID's rows put back as DIR's copies have them

The pre-reset backfill runs several puzzles at once in one tree, and every run
files its source corrections as rows of shared files: SOURCE_CLUE_WRONG and
SOURCE_ANSWER_WRONG in tools/data/source_clue_wrong.json and
tools/data/source_answer_wrong.json, a setter's slips in
tools/data/setter_error.json (each keyed "puzzle id/entry id"), the other
SOURCE_* tables (SOURCE_LIGHT_WRONG, ...) in tools/fetch_puzzle.py. So a
puzzle's commit never stages those files from the tree: `stage` writes HEAD's
version with only ID's rows changed straight into the index, and the rows the
puzzles still in flight filed stay in the tree for their own commits. `revert`
is the discard: the puzzle file goes back to HEAD, so its rows do too. `paths`
is the list every other commit of the burn leaves out, so no row reaches
master before the clue it corrects. `graft` is the restore of a run that was
interrupted: DIR holds copies of those files from the tree it ran in
(tools/puzzle_worker.sh worker_set_aside), and ID's rows come back from them
onto whatever the tree holds now.

A row is keyed by its puzzle id: the key itself when it is a string, its first
element when it is a tuple. Its text is its whole lines, with the comment lines
directly above it. Everything outside ID's rows is copied byte for byte, and
the result is checked to hold exactly the donor's rows for ID and the base's
for everyone else before anything is written.
"""
import ast
import contextlib
import json
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
FETCHER = TOOLS / "fetch_puzzle.py"
REL = "tools/fetch_puzzle.py"
DATA_RELS = ("tools/data/setter_error.json", "tools/data/source_answer_wrong.json",
             "tools/data/source_clue_wrong.json", "tools/data/blog_disagree.json")
#: Lists of {"id": "<puzzle>#<clue>", ...} rows, spliced by tools/shape_queue.splice:
#: the shape re-annotation list, whose rows a run prunes as it files their trees.
#: Skipped where the file is not there (a test repo without it).
LIST_RELS = ("tools/data/shape_reannotate.json",)


def tables(source):
    """{table name: (line of its `{`, [(pid, key node, value node, first line,
    last line)])}, 1-based and inclusive, a row's lead comments included."""
    lines = source.splitlines()
    out = {}
    for node in ast.parse(source).body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.startswith("SOURCE_")):
            continue
        rows, floor = [], node.value.lineno
        for k, v in zip(node.value.keys, node.value.values):
            key = ast.literal_eval(k)
            pid = key if isinstance(key, str) else key[0]
            first = k.lineno
            while first - 1 > floor and lines[first - 2].lstrip().startswith("#"):
                first -= 1
            rows.append((pid, k, v, first, v.end_lineno))
            floor = v.end_lineno
        out[node.targets[0].id] = (node.value.lineno, rows)
    return out


def _sig(row):
    return ast.dump(row[1]) + ast.dump(row[2])


def splice(base, donor, pid):
    """`base` with pid's rows of every SOURCE_* table replaced by `donor`'s. A
    row new to base goes after the nearest row above it in donor that base
    also holds, so a donor that differs from base only in pid's rows comes
    back byte for byte."""
    base_t, donor_t = tables(base), tables(donor)
    blines = base.splitlines(keepends=True)
    dlines = donor.splitlines(keepends=True)
    cut, after = set(), {}
    for name, (dopen, drows) in donor_t.items():
        if name not in base_t:
            if any(r[0] == pid for r in drows):
                raise SystemExit(f"own_rows: {name} is not in the base {REL}")
            continue
        bopen, brows = base_t[name]
        ends = {_key(r): r[4] for r in brows if r[0] != pid}
        for r in brows:
            if r[0] == pid:
                cut.update(range(r[3], r[4] + 1))
        anchor = bopen
        for r in drows:
            if r[0] != pid:
                anchor = ends.get(_key(r), anchor)
                continue
            after.setdefault(anchor, []).append("".join(dlines[r[3] - 1:r[4]]))
    for name, (_o, brows) in base_t.items():
        if name not in donor_t and any(r[0] == pid for r in brows):
            raise SystemExit(f"own_rows: {name} is not in the donor {REL}")
    out = []
    for n, line in enumerate(blines, 1):
        if n not in cut:
            out.append(line)
        out.extend(after.get(n, []))
    result = "".join(out)
    got = tables(result)
    for name, (_o, rrows) in got.items():
        want = [_sig(r) for r in base_t[name][1] if r[0] != pid]
        want += [_sig(r) for r in donor_t.get(name, (0, []))[1] if r[0] == pid]
        if sorted(_sig(r) for r in rrows) != sorted(want):
            raise SystemExit(f"own_rows: splicing {pid}'s rows of {name} went wrong; "
                             f"{REL} left as it was")
    return result


def _key(row):
    return ast.dump(row[1])


def git(*args, stdin=None):
    return subprocess.run(["git", "-C", str(TOOLS.parent), *args], input=stdin,
                          capture_output=True, text=True, check=True).stdout


def splice_json(base, donor, pid):
    """`base` (a keyed-JSON text) with pid's rows replaced by `donor`'s."""
    from json_merge import dump_lines
    held = {k: v for k, v in json.loads(base).items() if k.split("/", 1)[0] != pid}
    held.update({k: v for k, v in json.loads(donor).items()
                 if k.split("/", 1)[0] == pid})
    return dump_lines(held)


def _stage_blob(rel, blob):
    sha = git("hash-object", "-w", "--stdin", "--path", rel, stdin=blob).strip()
    mode = git("ls-tree", "HEAD", "--", rel).split()[0]
    git("update-index", "--cacheinfo", f"{mode},{sha},{rel}")


def splice_list(base, donor, pid):
    import shape_queue
    return shape_queue.splice(base, donor, pid)


def _lists():
    """The LIST_RELS this tree and its HEAD both hold as a JSON list (a test
    repo may hold none, or a symlink, whose blob is its target's path)."""
    out = []
    for rel in LIST_RELS:
        path = TOOLS.parent / rel
        head = subprocess.run(["git", "-C", str(TOOLS.parent), "show", f"HEAD:{rel}"],
                              capture_output=True, text=True)
        try:
            ok = (path.is_file() and not path.is_symlink() and head.returncode == 0
                  and isinstance(json.loads(head.stdout), list)
                  and isinstance(json.loads(path.read_text()), list))
        except ValueError:
            ok = False
        if ok:
            out.append(rel)
    return out


def _merger(rel):
    return splice if rel == REL else splice_list if rel in LIST_RELS else splice_json


def _landed(pid, clue):
    """Whether puzzle `pid`'s file in the tree holds a new annotation of clue key
    `clue` ("22a") that the shape detectors pass. By id only: one file is read."""
    import puzzle_paths
    import shape_queue
    try:
        path = puzzle_paths.find(pid)
        entries = json.loads(path.read_text(encoding="utf-8")).get("entries") or [] if path else []
    except (OSError, ValueError, SystemExit):
        return False
    for e in entries:
        if shape_queue.clue_key(e) == clue:
            return bool(e.get("annotation")) and not shape_queue.findings(e)
    return False


def keep_unlanded(base, text, pids):
    """`text` (the list as staged) with back every row of `pids` that `base` (HEAD)
    holds and `text` dropped, unless its clue's new annotation is in the puzzle's
    file and passes. A row leaves the queue in its puzzle's own commit and only
    with the annotation that settled it: a run that was withdrawn, or failed
    validation, has pruned its rows in the tree (done() runs at apply, before the
    check), and those pruned rows must not ride out in anyone's commit
    (mephisto-3304, book-26025, mephisto-3388 lost theirs that way, 10-17)."""
    import shape_queue
    b, t = json.loads(base or "[]"), json.loads(text or "[]")
    have = {r["id"] for r in t}
    back = [r for r in b if r["id"] not in have and r["id"].partition("#")[0] in pids
            and not _landed(*r["id"].partition("#")[::2])]
    if not back:
        return text
    out = list(t)
    for r in back:
        before = [x["id"] for x in b[:b.index(r)]]
        at = max((i + 1 for i, x in enumerate(out) if x["id"] in before), default=0)
        out.insert(at, r)
        have.add(r["id"])
    return shape_queue.dump(out)


def drop_pruned(text):
    """`text` (the list as staged) without the rows the planner's prune dropped from the
    burn tree (prune_shape_queue.pending): nothing else commits that edit, so the
    committed list kept its ghost rows (1804 on master against 677 in the burn)."""
    import prune_shape_queue
    import shape_queue
    rows = json.loads(text or "[]")
    gone = prune_shape_queue.pending(r["id"] for r in rows)
    if not gone:
        return text
    return shape_queue.dump([r for r in rows if r["id"] not in gone])


def stage(*pids):
    """Several ids chain onto one another's result, so a batch commit holds every
    one's rows (staged one at a time, each would rebuild from HEAD and undo the last)."""
    import shape_queue
    for rel in (REL, *DATA_RELS, *_lists()):
        head = git("show", f"HEAD:{rel}")
        if rel in LIST_RELS:
            with shape_queue.locked():
                donor = (TOOLS.parent / rel).read_text()
        else:
            donor = (TOOLS.parent / rel).read_text()
        text = head
        for pid in pids:
            text = _merger(rel)(text, donor, pid)
        if rel in LIST_RELS:
            text = drop_pruned(text)
            text = keep_unlanded(head, text, set(pids))   # after the drop: a pid's unsettled row stays
        _stage_blob(rel, text)


def _guard(rel):
    """The queue's lock around a read-modify-write of a LIST_RELS file."""
    import shape_queue
    return shape_queue.locked() if rel in LIST_RELS else contextlib.nullcontext()


def _write(rel, path, text):
    """The list file is replaced atomically (git add takes no lock and must
    never see it half written); the others as before."""
    if rel in LIST_RELS:
        import shape_queue
        shape_queue.write(text, path)
    else:
        path.write_text(text)


def revert(pid):
    tree = FETCHER.read_text()
    kept = splice(tree, git("show", f"HEAD:{REL}"), pid)
    if kept != tree:
        FETCHER.write_text(kept)
        print(f"  [{pid}] put its rows of {REL} back as HEAD has them")
    for rel in (*DATA_RELS, *_lists()):
        path = TOOLS.parent / rel
        with _guard(rel):
            text = path.read_text()
            kept = _merger(rel)(text, git("show", f"HEAD:{rel}"), pid)
            if kept != text:
                _write(rel, path, kept)
                print(f"  [{pid}] put its rows of {rel} back as HEAD has them")


def graft(pid, donor_dir):
    for rel in (REL, *DATA_RELS, *LIST_RELS):
        donor = Path(donor_dir) / rel
        if not donor.is_file() or not (TOOLS.parent / rel).is_file():
            continue
        path = TOOLS.parent / rel
        with _guard(rel):
            text = path.read_text()
            merge = _merger(rel)
            kept = merge(text, donor.read_text(), pid)
            if kept != text:
                _write(rel, path, kept)
                print(f"  [{pid}] put its rows of {rel} back as the interrupted run left them")


def main(argv):
    if argv == ["paths"]:
        print("\n".join((REL, *DATA_RELS, *LIST_RELS)))
        return
    if len(argv) == 3 and argv[0] == "graft":
        graft(argv[1], argv[2])
        return
    if argv[:1] == ["stage"] and len(argv) >= 2:
        stage(*argv[1:])
        return
    if len(argv) != 2 or argv[0] != "revert":
        raise SystemExit(__doc__)
    revert(argv[1])


if __name__ == "__main__":
    main(sys.argv[1:])
