#!/usr/bin/env python3
"""Git merge driver for the keyed JSON data files several writers append to.

    git config merge.json-keys.driver "python3 tools/json_merge.py %O %A %B"

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

The result keeps the file's own layout: tools/corroborate.py's one line per
top-level key (dump_lines), or json.dumps(indent=2). Keys and lists that were
sorted stay sorted. Anything that does not parse as a JSON object, or is laid
out in neither form, exits 1 and git falls back to an ordinary conflict.
"""
import json
import sys

MISSING = object()


def dump_lines(held):
    """One line per top-level key, keys sorted, so writers touching different
    keys touch different lines."""
    lines = [f" {json.dumps(k, ensure_ascii=False)}: "
             f"{json.dumps(held[k], sort_keys=True, ensure_ascii=False)}"
             for k in sorted(held)]
    return "{\n" + ",\n".join(lines) + "\n}\n"


def dump_indent(held):
    return json.dumps(held, indent=2, ensure_ascii=False) + "\n"


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
    dump = next((d for d in (dump_lines, dump_indent)
                 for t, x in ((texts[1], a), (texts[2], b)) if t.strip() and d(x) == t),
                None)
    if dump is None:
        print("json_merge: layout is neither one-line-per-key nor indent=2; "
              "leaving the conflict", file=sys.stderr)
        return 1
    with open(a_path, "w", encoding="utf-8") as f:
        f.write(dump(merge(o, a, b)))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: json_merge.py ANCESTOR CURRENT OTHER")
    sys.exit(main(*sys.argv[1:]))
