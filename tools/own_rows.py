#!/usr/bin/env python3
"""One puzzle's rows of the shared source-correction tables, and no one else's.

    python3 tools/own_rows.py stage ID    # index: HEAD's file + ID's rows as the tree has them
    python3 tools/own_rows.py revert ID   # tree: ID's rows put back as HEAD has them

The pre-reset backfill runs several puzzles at once in one tree, and every run
files its source corrections as rows of shared files: SOURCE_CLUE_WRONG and
SOURCE_ANSWER_WRONG in tools/data/source_clue_wrong.json and
tools/data/source_answer_wrong.json (keyed "puzzle id/entry id"), the other
SOURCE_* tables (SOURCE_LIGHT_WRONG, ...) in tools/fetch_puzzle.py. So a
puzzle's commit never stages those files from the tree: `stage` writes HEAD's
version with only ID's rows changed straight into the index, and the rows the
puzzles still in flight filed stay in the tree for their own commits. `revert`
is the discard: the puzzle file goes back to HEAD, so its rows do too.

A row is keyed by its puzzle id: the key itself when it is a string, its first
element when it is a tuple. Its text is its whole lines, with the comment lines
directly above it. Everything outside ID's rows is copied byte for byte, and
the result is checked to hold exactly the donor's rows for ID and the base's
for everyone else before anything is written.
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
FETCHER = TOOLS / "fetch_puzzle.py"
REL = "tools/fetch_puzzle.py"
DATA_RELS = ("tools/data/source_answer_wrong.json", "tools/data/source_clue_wrong.json")


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


def stage(pid):
    head = git("show", f"HEAD:{REL}")
    _stage_blob(REL, splice(head, FETCHER.read_text(), pid))
    for rel in DATA_RELS:
        _stage_blob(rel, splice_json(git("show", f"HEAD:{rel}"),
                                     (TOOLS.parent / rel).read_text(), pid))


def revert(pid):
    tree = FETCHER.read_text()
    kept = splice(tree, git("show", f"HEAD:{REL}"), pid)
    if kept != tree:
        FETCHER.write_text(kept)
        print(f"  [{pid}] put its rows of {REL} back as HEAD has them")
    for rel in DATA_RELS:
        path = TOOLS.parent / rel
        text = path.read_text()
        kept = splice_json(text, git("show", f"HEAD:{rel}"), pid)
        if kept != text:
            path.write_text(kept)
            print(f"  [{pid}] put its rows of {rel} back as HEAD has them")


def main(argv):
    if len(argv) != 2 or argv[0] not in ("stage", "revert"):
        raise SystemExit(__doc__)
    {"stage": stage, "revert": revert}[argv[0]](argv[1])


if __name__ == "__main__":
    main(sys.argv[1:])
