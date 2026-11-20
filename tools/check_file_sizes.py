#!/usr/bin/env python3
"""Fail when a tracked file outside puzzles/ is over 512 KB and not allowlisted.

    python3 tools/check_file_sizes.py            # check HEAD's tree
    python3 tools/check_file_sizes.py --list     # print every file over the limit
    python3 tools/check_file_sizes.py --range BASE HEAD   # only files HEAD adds/changes vs BASE
    python3 tools/check_file_sizes.py --staged [--unstage] # only what is staged (--unstage drops them)

--range and --staged are the cheap gates for a push or a commit (prepush_check.py, the jobs'
commit and push functions): they weigh only the changed blobs and ignore stale allowlist entries.

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


def changed_sizes(*diff_args, root=ROOT):
    """{path: size} of the files a `git diff --raw` (diff_args: `--cached`, or `BASE HEAD`) adds or
    modifies outside puzzles/, symlinks and submodules left out."""
    out = subprocess.run(["git", "-C", str(root), "diff", "--raw", "--abbrev=40", "-z", "--no-renames", "--diff-filter=AM",
                          *diff_args, "--", ":(exclude)puzzles"],
                         capture_output=True, text=True, check=True).stdout.split("\0")
    shas = {}
    for meta, path in zip(out[0::2], out[1::2]):
        _om, nm, _os, ns, _st = meta.lstrip(":").split()
        if nm in ("100644", "100755"):
            shas[path] = ns
    if not shas:
        return {}
    res = subprocess.run(["git", "-C", str(root), "cat-file", "--batch-check=%(objectname) %(objectsize)"],
                         input="".join(f"{s}\n" for s in shas.values()), capture_output=True, text=True,
                         check=True).stdout.splitlines()
    size = {sha: int(n) for sha, _, n in (line.partition(" ") for line in res) if n.isdigit()}
    return {p: size[s] for p, s in shas.items() if s in size}


def oversize(sizes, allow):
    """(path, message) for the (changed) files over the limit without an allowlist reason."""
    return [(path, m) for path in sorted(sizes) for m in problems({path: sizes[path]}, allow)
            if m.startswith(path + " ")]


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


#: Exit status of a gate that could not weigh anything (no git repo here, an unknown base ref, no
#: allowlist): callers refuse a push or commit only on 1 (a file is too big), never on this.
GATE_SKIPPED = 3


def worktree_root():
    """The work tree the gate runs in (the caller's cwd), else this script's own."""
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else ROOT


def gate(argv):
    """--range BASE HEAD / --staged [--unstage]: exit 1 and say why when a changed file is too big;
    GATE_SKIPPED (3) when it could not tell (unknown base, no allowlist)."""
    if not (argv[0] == "--staged" or (argv[0] == "--range" and len(argv) == 3)):
        print(__doc__, file=sys.stderr)
        return 2
    root = worktree_root()
    try:
        allow = json.loads((root / ALLOWLIST).read_text(encoding="utf-8"))
        if argv[0] == "--range":
            sizes = changed_sizes(argv[1], argv[2], root=root)
        else:
            sizes = changed_sizes("--cached", root=root)
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        print(f"check_file_sizes: skipped ({type(e).__name__}: {e})", file=sys.stderr)
        return GATE_SKIPPED
    bad = oversize(sizes, allow)
    for path, line in bad:
        print(f"check_file_sizes: refused: {line}", file=sys.stderr)
        if "--unstage" in argv:
            subprocess.run(["git", "-C", str(root), "reset", "-q", "--", path])
    return 1 if bad else 0


def main(argv):
    if argv and argv[0] in ("--range", "--staged"):
        return gate(argv)
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
