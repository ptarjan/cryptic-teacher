#!/usr/bin/env python3
"""Fail when a tracked file outside puzzles/ is over 512 KB and not allowlisted.

    python3 tools/check_file_sizes.py            # check HEAD's tree
    python3 tools/check_file_sizes.py --list     # print every file over the limit

Git stores a whole new blob for each change of a file, so a big file that many
jobs rewrite (tools/data/source_clue_wrong.json and blog_disagree.json were each
changed in ~15% of recent commits and grew the repository ~18 MB a day) is the
costliest thing to keep in one piece. Such a ledger is split into shards
(tools/sharded_table.py) instead. A file that is legitimately big and rarely
rewritten is named in tools/data/large_file_allowlist.json, {path: "one-line
reason"}, and an entry for a file now under the limit or gone is stale and fails
too, so the list cannot rot.

Reads the index (`git ls-files -s`) and the sizes of its blobs
(`git cat-file --batch-check`): the tree at HEAD, never the history.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 512 * 1024
ALLOWLIST = "tools/data/large_file_allowlist.json"
#: Puzzle files are many and small; the guard is for everything else.
EXEMPT_PREFIX = "puzzles/"


def tracked_sizes(root=ROOT):
    """{path: size in bytes} of every file in the index outside puzzles/ (a
    symlink, and a submodule, which have no blob of their own to weigh, are left out)."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "-z", "--", ":(exclude)puzzles"],
                         capture_output=True, text=True, check=True).stdout
    shas = {}
    for rec in filter(None, out.split("\0")):
        meta, path = rec.split("\t", 1)
        mode, sha, _stage = meta.split()
        if mode == "100644" or mode == "100755":
            shas[path] = sha
    if not shas:
        return {}
    ask = "".join(f"{sha}\n" for sha in shas.values())
    res = subprocess.run(["git", "-C", str(root), "cat-file", "--batch-check=%(objectname) %(objectsize)"],
                         input=ask, capture_output=True, text=True, check=True).stdout.splitlines()
    size = {}
    for line in res:
        sha, _, n = line.partition(" ")
        if n.isdigit():
            size[sha] = int(n)
    return {p: size[s] for p, s in shas.items() if s in size and not p.startswith(EXEMPT_PREFIX)}


def problems(sizes, allow):
    """The messages for the files over the limit without an allowlist reason,
    and for allowlist entries that are stale or lack a reason."""
    out = []
    for path, n in sorted(sizes.items()):
        if n > LIMIT and not allow.get(path):
            out.append(f"{path} is {n // 1024} KB, over {LIMIT // 1024} KB: split it into small files "
                       f"(tools/sharded_table.py), or list it in {ALLOWLIST} with a one-line reason")
    for path, why in sorted(allow.items()):
        if not isinstance(why, str) or not why.strip():
            out.append(f"{ALLOWLIST}: {path} has no reason")
        elif path not in sizes:
            out.append(f"{ALLOWLIST}: {path} is not a tracked file; remove the entry")
        elif sizes[path] <= LIMIT:
            out.append(f"{ALLOWLIST}: {path} is {sizes[path] // 1024} KB, under the limit; remove the entry")
    return out


def main(argv):
    sizes = tracked_sizes()
    if argv == ["--list"]:
        for path, n in sorted(sizes.items(), key=lambda kv: -kv[1]):
            if n > LIMIT:
                print(f"{n // 1024:8d} KB  {path}")
        return 0
    allow = json.loads((ROOT / ALLOWLIST).read_text(encoding="utf-8"))
    bad = problems(sizes, allow)
    for line in bad:
        print(f"check_file_sizes: {line}", file=sys.stderr)
    if not bad:
        print(f"check_file_sizes: {len(sizes)} tracked files outside puzzles/, "
              f"{sum(n > LIMIT for n in sizes.values())} over {LIMIT // 1024} KB, all allowlisted")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
