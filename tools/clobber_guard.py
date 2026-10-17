#!/usr/bin/env python3
"""Refuse to publish a commit made from a stale tree.

    tools/clobber_guard.py [<commit>]        # default HEAD; exit 0 ok, 4 refused

A commit whose parent is current but whose files are an older checkout's
silently reverts everything pushed since (456d5a0397, 2026-10-16: an OCR change
undid 6093e30e56 and 45 filed puzzles, 61 files). Its diff from its parent
looks like any other, so this asks a different question: of the paths the
commit changes, do most hold exactly what an OLDER ancestor S held, and not
what the parent holds (one of them a file that still exists)? One such S, on at least MIN_PATHS paths and half of the
commit's paths, means the commit rolled those paths back to S; the commit is
refused and S named. A commit that means to roll back says so: a subject
starting "Revert" or "Restore", or CLOBBER_OK=1 in the environment.

Called by tools/push_puzzle_commit.sh and tools/push_checked.sh, the push
tools; there is no git hook (Paul's rule), so a push that bypasses them is
not guarded.
"""
import os
import subprocess
import sys

REFUSED = 4
MIN_PATHS = 3      # fewer rolled-back paths is an ordinary edit
LOOKBACK = 400     # ancestors of the parent tried as S
MAX_PATHS = 200    # paths of a very large commit sampled


def git(*args, stdin=None):
    return subprocess.run(["git", *args], input=stdin, capture_output=True, text=True, check=True).stdout


def blobs(specs):
    """{spec: blob sha or None} for 'commit:path' specs, in one process."""
    out = git("cat-file", "--batch-check", stdin="".join(s + "\n" for s in specs)).splitlines()
    return {s: (None if line.endswith(" missing") else line.split()[0]) for s, line in zip(specs, out)}


def rolled_back(commit):
    """(S, [paths]) of the ancestor `commit` rolled most paths back to, or None."""
    parent = git("rev-parse", "--verify", "-q", commit + "^").strip()
    paths = git("diff", "--no-renames", "--name-only", "-z", parent, commit).split("\0")[:-1][:MAX_PATHS]
    if len(paths) < MIN_PATHS:
        return None
    ancestors = git("rev-list", "-n", str(LOOKBACK), parent).split()[1:]
    now = blobs([f"{parent}:{p}" for p in paths] + [f"{commit}:{p}" for p in paths])
    theirs = {p: now[f"{commit}:{p}"] for p in paths}
    mine = {p: now[f"{parent}:{p}"] for p in paths}
    old = blobs([f"{s}:{p}" for s in ancestors for p in paths])
    best = (0, None, [])
    for s in ancestors:
        hit = [p for p in paths if old[f"{s}:{p}"] == theirs[p] and theirs[p] != mine[p]]
        if len(hit) > best[0]:
            best = (len(hit), s, hit)
    n, s, hit = best
    # Deleting recently added files matches every ancestor from before they
    # existed, so a rollback must also have put an existing file back.
    if n >= MIN_PATHS and 2 * n >= len(paths) and any(mine[p] and theirs[p] for p in hit):
        return s, hit
    return None


def check(commit):
    """None when `commit` may be published, else the reason."""
    if os.environ.get("CLOBBER_OK"):
        return None
    if git("log", "-1", "--format=%s", commit).startswith(("Revert", "Restore")):
        return None
    if subprocess.run(["git", "rev-parse", "--verify", "-q", commit + "^"], capture_output=True).returncode:
        return None
    found = rolled_back(commit)
    if not found:
        return None
    s, hit = found
    subject = git("log", "-1", "--format=%h %s", commit).strip()
    then = git("log", "-1", "--format=%h %ad %s", "--date=format:%m-%d %H:%M", s).strip()
    return (f"{subject}\n  holds {len(hit)} of its changed paths as they were at {then}, "
            "not as its parent has them: a commit from a stale tree reverts what was pushed since.\n  "
            + "\n  ".join(hit[:8]) + ("\n  ..." if len(hit) > 8 else "")
            + "\n  Rebase the real change onto origin/master. If rolling back is the point, "
              "start the subject with Revert or Restore, or set CLOBBER_OK=1.")


def main(argv):
    commit = git("rev-parse", "--verify", (argv[1] if len(argv) > 1 else "HEAD") + "^{commit}").strip()
    why = check(commit)
    if why:
        print("clobber_guard: refusing " + why, file=sys.stderr)
        return REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
