#!/usr/bin/env python3
# tools/git_ancestry.py: the date shortcut answers "no" for a commit committed over a day
# after the other without a history walk, and agrees with git otherwise.
#
#     python3 tests/test_git_ancestry.py
import _path  # puts tools/ on sys.path
import os, subprocess, tempfile
import git_ancestry

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

def commit(d, name, when):
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    open(os.path.join(d, name), "w").write(name)
    subprocess.run(["git", "-C", d, "add", name], check=True, env=env)
    subprocess.run(["git", "-C", d, "commit", "-qm", name], check=True, env=env)
    return subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()

with tempfile.TemporaryDirectory() as d:
    subprocess.run(["git", "init", "-q", d], check=True)
    old = commit(d, "a", "2026-01-01T00:00:00Z")
    close = commit(d, "b", "2026-01-01T06:00:00Z")
    new = commit(d, "c", "2026-03-01T00:00:00Z")
    check("newer by months is flagged", git_ancestry.newer_than_by_a_day(d, new, old))
    check("older is not flagged", not git_ancestry.newer_than_by_a_day(d, old, new))
    check("within a day is not flagged", not git_ancestry.newer_than_by_a_day(d, close, old))
    check("unknown sha is not flagged", not git_ancestry.newer_than_by_a_day(d, "0" * 40, old))
    check("newer is no ancestor of older", not git_ancestry.is_ancestor(d, new, old))
    check("older is ancestor of newer", git_ancestry.is_ancestor(d, old, new))
    check("close dates fall back to git (ancestor)", git_ancestry.is_ancestor(d, old, close))
    check("close dates fall back to git (not ancestor)", not git_ancestry.is_ancestor(d, close, old))
    check("a commit is its own ancestor", git_ancestry.is_ancestor(d, new, new))

raise SystemExit(1 if fails else 0)
