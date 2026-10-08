#!/usr/bin/env python3
"""Git merge driver and clean filter for the keyed JSON data files several
writers append to.

    git config merge.json-keys.driver "python3 tools/json_merge.py %O %A %B"
    git config filter.json-keys.clean "python3 tools/json_merge.py --clean"

registered by tools/nightly_worktree.sh on every scheduled run, and named per
file in .gitattributes. Git hands it the ancestor (%O), the current side (%A)
and the other side (%B); the merge is written over %A, and exit 0 means
resolved.

A line merge of these files conflicts whenever two writers add neighbouring
keys, and `merge=union` is no answer: it keeps both lines and loses the comma
between them, so the result is not JSON. Here the merge is per key, three-way:
a key only one side changed takes that side; a key both sides added or changed
alike is kept once; a key both changed differently merges as dicts key by key,
as lists by union, and otherwise takes %B (in a rebase, the commit being
replayed), with a note on stderr. A rebase stopped on a ledger row strands every
later commit, which costs far more than either side's version of one row.

Every one of these files is laid out by dump_lines, one line per top-level key,
and the merge writes that layout whatever the sides were in, since a side that
parses is mergeable however it was spaced. Keys and lists that were sorted stay
sorted. Anything that does not parse as a JSON object exits 1 and git falls back
to an ordinary conflict.

`--puzzle` is the driver for the puzzle files (puzzles/**/*.json), which the
daily update and the pre-reset burn both annotate: when they annotate the same
puzzle in the same night, the two commits rewrite every entry's lines and a line
merge cannot place them. Here the merge is the same three-way walk, except that
`entries` merge entry by entry (both sides must hold the same lights in the same
order), an entry's `annotation` is one value (two annotations are never spliced
together; when both sides wrote one, %A's is kept, which in a rebase and in
push_puzzle_commit.sh's merge-tree is the one already on origin and so already
on the site), `annotatedBy` is a union, and anything else both sides changed
differently is a real conflict, written with conflict markers by
`git merge-file` so no caller can stage it as resolved. The result is written in
write_puzzle_file's layout.

The clean filter is what keeps that layout in the repository: `git add` stores
dump_lines of whatever is on disk, so a row typed in by hand (an annotating
model editing the file) is staged in the canonical layout. Input that does not
parse is staged as it is, and the merge refuses it later.
"""
import json
import subprocess
import sys
from pathlib import Path

import puzzle_schema

MISSING = object()


def dump_lines(held):
    """One line per top-level key, keys sorted, so writers touching different
    keys touch different lines."""
    lines = [f" {json.dumps(k, ensure_ascii=False)}: "
             f"{json.dumps(held[k], sort_keys=True, ensure_ascii=False)}"
             for k in sorted(held)]
    return "{\n" + ",\n".join(lines) + "\n}\n"


def _sorted(seq):
    try:
        return list(seq) == sorted(seq)
    except TypeError:
        return False


def merge_lists(o, a, b):
    base = o if isinstance(o, list) else []
    gone = [x for x in base if x not in a or x not in b]
    out = [x for x in a if x not in gone]
    out += [x for x in b if x not in out and x not in gone]
    return sorted(out) if _sorted(a) and _sorted(b) else out


def merge(o, a, b, path=""):
    if a == b:
        return a
    if a == o:
        return b
    if b == o:
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        base = o if isinstance(o, dict) else {}
        out = {}
        for k in list(a) + [k for k in b if k not in a]:
            v = merge(base.get(k, MISSING), a.get(k, MISSING), b.get(k, MISSING),
                      f"{path}/{k}")
            if v is not MISSING:
                out[k] = v
        if _sorted(list(a)) and _sorted(list(b)):
            out = dict(sorted(out.items()))
        return out
    if isinstance(a, list) and isinstance(b, list):
        return merge_lists(o, a, b)
    print(f"json_merge: {path or '/'} changed on both sides; kept the replayed "
          f"side's {json.dumps(b, ensure_ascii=False)[:200]}", file=sys.stderr)
    return b


class Conflict(Exception):
    pass


def entry_key(e):
    return (e.get("number"), e.get("direction")) if isinstance(e, dict) else e


def merge_puzzle(o, a, b, path=""):
    if a == b:
        return a
    if a == o:
        return b
    if b == o:
        return a
    key = path.rsplit("/", 1)[-1]
    if key == "annotation":
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        base = o if isinstance(o, dict) else {}
        out = {}
        for k in list(a) + [k for k in b if k not in a]:
            v = merge_puzzle(base.get(k, MISSING), a.get(k, MISSING),
                             b.get(k, MISSING), f"{path}/{k}")
            if v is not MISSING:
                out[k] = v
        return out
    if isinstance(a, list) and isinstance(b, list):
        if key == "annotatedBy":
            return merge_lists(o, a, b)
        if key == "entries" and isinstance(o, list) and \
                [entry_key(e) for e in o] == [entry_key(e) for e in a] == \
                [entry_key(e) for e in b]:
            return [merge_puzzle(x, y, z, f"{path}/{entry_key(y)}")
                    for x, y, z in zip(o, a, b)]
    raise Conflict(path or "/")


def main_puzzle(o_path, a_path, b_path):
    try:
        o, a, b = (json.loads(Path(p).read_text(encoding="utf-8"))
                   for p in (o_path, a_path, b_path))
        merged = puzzle_schema.order(merge_puzzle(o, a, b))
    except (ValueError, Conflict) as err:
        print(f"json_merge --puzzle: {type(err).__name__} at {err}; "
              "leaving a marked conflict", file=sys.stderr)
        subprocess.run(["git", "merge-file", "-L", "current", "-L", "base",
                        "-L", "other", a_path, o_path, b_path], check=False)
        return 1
    with open(a_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(merged, indent=1, ensure_ascii=False) + "\n")
    return 0


def main(o_path, a_path, b_path):
    texts = []
    for p in (o_path, a_path, b_path):
        with open(p, encoding="utf-8") as f:
            texts.append(f.read())
    try:
        o, a, b = (json.loads(t) if t.strip() else {} for t in texts)
    except ValueError as err:
        print(f"json_merge: not JSON ({err}); leaving the conflict", file=sys.stderr)
        return 1
    if not all(isinstance(x, dict) for x in (o, a, b)):
        print("json_merge: not a JSON object; leaving the conflict", file=sys.stderr)
        return 1
    with open(a_path, "w", encoding="utf-8") as f:
        f.write(dump_lines(merge(o, a, b)))
    return 0


def clean(text):
    """dump_lines of `text` when it is a JSON object, else `text` unchanged."""
    try:
        held = json.loads(text)
    except ValueError as err:
        print(f"json_merge --clean: not JSON ({err}); staged as it is", file=sys.stderr)
        return text
    if not isinstance(held, dict):
        print("json_merge --clean: not a JSON object; staged as it is", file=sys.stderr)
        return text
    return dump_lines(held)


if __name__ == "__main__":
    if sys.argv[1:] == ["--clean"]:
        sys.stdout.write(clean(sys.stdin.read()))
        sys.exit(0)
    if len(sys.argv) == 5 and sys.argv[1] == "--puzzle":
        sys.exit(main_puzzle(*sys.argv[2:]))
    if len(sys.argv) != 4:
        sys.exit("usage: json_merge.py [--puzzle] ANCESTOR CURRENT OTHER | json_merge.py --clean")
    sys.exit(main(*sys.argv[1:]))
