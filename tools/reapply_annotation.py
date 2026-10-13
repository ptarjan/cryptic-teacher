#!/usr/bin/env python3
"""Re-apply a commit's annotation onto origin's copy of its puzzle, for
tools/push_puzzle_commit.sh, when the 3-way replay conflicts.

    python3 tools/reapply_annotation.py PARENT BASE COMMIT TREE PATH...

The puzzle merge driver (tools/json_merge.py --puzzle) refuses a puzzle both
sides changed in the same field differently: origin re-dated it, re-read a
clue, added a setter, while the burn's commit annotated it. Refusing stopped
the burn's sync for hours (10-13: 16 Genius annotations held from 05:05). The
annotation is what the commit is for, and it is still good on origin's file as
long as the clue words it explains are the same, so here origin's file is the
base: origin wins every field both sides changed, and the commit's
annotations, annotatedBy and every field only it changed are written onto it
(json_merge.reapply). What origin kept is noted on stderr.

TREE is merge-tree's conflicted result; PATH... its conflicted paths. Prints
the settled tree, or exits 1 with nothing on stdout when a path is not a
puzzle file both sides hold or no annotation the commit wrote survives (the
caller then refuses the commit as before).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import json_merge  # noqa: E402


def git(*args, stdin=None, env=None):
    return subprocess.run(("git",) + args, input=stdin, capture_output=True,
                          text=True, check=True, env=env).stdout


def blob(rev, path):
    try:
        return json.loads(git("cat-file", "-p", f"{rev}:{path}"))
    except subprocess.CalledProcessError:
        return None


def main(argv):
    if len(argv) < 5:
        print(__doc__, file=sys.stderr)
        return 1
    parent, base, commit, tree, *paths = argv
    rewrites = {}
    for path in paths:
        if not (path.startswith("puzzles/") and path.endswith(".json")):
            return 1
        o, a, b = blob(parent, path), blob(base, path), blob(commit, path)
        if a is None or b is None:
            return 1
        try:
            merged, notes = json_merge.reapply(o or {}, a, b)
        except json_merge.Conflict as err:
            print(f"reapply_annotation: {path}: cannot re-apply ({err})", file=sys.stderr)
            return 1
        for note in notes:
            print(f"reapply_annotation: {path}: {note}", file=sys.stderr)
        print(f"reapply_annotation: {path}: annotation re-applied onto origin's file",
              file=sys.stderr)
        rewrites[path] = json.dumps(merged, indent=1, ensure_ascii=False) + "\n"
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
        git("read-tree", tree, env=env)
        for path, text in rewrites.items():
            sha = git("hash-object", "-w", "--stdin", stdin=text).strip()
            git("update-index", "--cacheinfo", f"100644,{sha},{path}", env=env)
        print(git("write-tree", env=env).strip())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (subprocess.CalledProcessError, ValueError) as err:
        print(f"reapply_annotation: {err}", file=sys.stderr)
        sys.exit(1)
