"""Remove a queue's idle slot trees (<TREE>-1 .. <TREE>-<SLOTS>) when its run ends.

The slot trees are full checkouts (2.5-4.5 GB each) that tools/nightly_worktree.sh
keeps between runs; left alone they fill the disk. unit_queue.tick calls sweep()
once nothing in the queue is running, started or waiting, so a tree lives for the
day's run and not past it. The next run's lease rebuilds a missing tree.

The safety rule is nightly_worktree.sh's CT_REMOVE_TREE one, plus a guard for
fetched data: a tree goes only when
  * its lease lock (.<name>.tree.lock in the main checkout) is free (flock -n),
  * `git cherry origin/master HEAD` is empty (no commit origin lacks),
  * no tracked file is edited,
  * no untracked, un-ignored file is in it (an unpublished fetched puzzle), and
  * no ignored path named raw/ is in it (a raw fetch cache).
The shared-state symlinks (.claude, .alert-state, ...) are removed with the tree
by `git worktree remove --force`, which unlinks a symlink and never follows it.
"""
import fcntl
import re
import subprocess
from pathlib import Path

RAW = re.compile(r"(^|/)raw/?$")


def _git(tree, *args):
    r = subprocess.run(["git", "--no-optional-locks", "-C", str(tree), *args],
                       capture_output=True, text=True, check=False)
    return r.stdout if r.returncode == 0 else None


def removable(tree):
    """Why `tree` must stay, or None when nothing in it is worth keeping."""
    cherry = _git(tree, "cherry", "origin/master", "HEAD")
    if cherry is None or cherry.strip():
        return "commits origin/master lacks"
    if (_git(tree, "status", "--porcelain", "--untracked-files=no") or "x").strip():
        return "tracked edits"
    if (_git(tree, "ls-files", "--others", "--exclude-standard") or "x").strip():
        return "untracked files"
    ignored = _git(tree, "status", "--porcelain", "--ignored", "--untracked-files=normal")
    if ignored is None:
        return "unreadable status"
    if any(line.startswith("!! ") and RAW.search(line[3:].strip()) for line in ignored.splitlines()):
        return "a raw fetch cache"
    return None


def sweep(main, root, names, log=print):
    """Remove each idle tree among `names` under `root`; `main` is the main checkout.
    Returns the names removed."""
    gone = []
    for name in names:
        tree = Path(root) / name
        if not tree.is_dir() or tree.is_symlink():
            continue
        lock = Path(main) / f".{name}.tree.lock"
        with open(lock, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue  # leased: a unit is using it
            why = removable(tree)
            if why:
                log(f"tree_sweep: keeping {name}: {why}")
                continue
            r = subprocess.run(["git", "-C", str(main), "worktree", "remove", "--force", str(tree)],
                               capture_output=True, text=True, check=False)
            if r.returncode or tree.exists():
                log(f"tree_sweep: could not remove {name}: {r.stderr.strip()[:200]}")
            else:
                gone.append(name)
        subprocess.run(["git", "-C", str(main), "worktree", "prune"], capture_output=True, check=False)
    if gone:
        log(f"tree_sweep: removed idle {' '.join(gone)}")
    return gone
