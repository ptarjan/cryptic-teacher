"""Remove job worktrees under ~/.cryptic-teacher that nothing is using, when the disk is short.

    python3 tools/tree_sweep.py idle [--hours H] [--dry-run] [--force]   # every tree unused for H hours

Every job tree tools/nightly_worktree.sh makes is a full checkout: 2.7 GB of
tracked files, plus ~2 GB of generated puzzle shims in a tree that rebuilds
them, plus the staged site in the nightly's. Re-cutting one reads the whole
corpus, so a tree is kept for reuse (nightly_worktree.sh fetches and resets it
to the wanted revision) and is swept only while the filesystem holding the
root is short of space: disk_low(), free under LOW_FREE_FRACTION of the disk
or under LOW_FREE_BYTES. With room to spare nothing is removed, whatever its
age (`--force` overrides). When space is short, a tree goes when it is not in use:
  * sweep(): unit_queue.tick drops a queue's slot trees (<TREE>-1 ..
    <TREE>-<SLOTS>) once nothing in the queue is running, started or waiting;
  * sweep_idle(): any tree under the root whose job has not started a run for
    IDLE_HOURS (unit_queue.tick, at most hourly). A job that ticks every few
    minutes keeps its tree; a daily or hand-started job's goes between runs.
The next run's lease rebuilds a missing tree from the shared object store.

The safety rule is nightly_worktree.sh's CT_REMOVE_TREE one, plus a guard for
fetched data: a tree goes only when
  * its lease lock (.<name>.tree.lock in the main checkout) is free (flock -n),
  * `git cherry origin/master HEAD` is empty (no commit origin lacks),
  * no tracked file is edited,
  * no untracked, un-ignored file is in it (an unpublished fetched puzzle), and
  * every ignored path in it is one the tree rebuilds by itself (REGENERABLE):
    a raw fetch cache, a scratch script or any file this list does not name
    keeps the tree, and the reason is logged.
The shared-state symlinks (.claude, .alert-state, ...) are removed with the tree
by `git worktree remove --force`, which unlinks a symlink and never follows it.
"""
import argparse
import fcntl
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

#: Ignored paths a tree makes again by itself: the share symlinks
#: nightly_worktree.sh adds, python bytecode, what ct_generated writes
#: (fetch_puzzle.py --reindex: shims, index, idx; build_abbreviations.py), and
#: what the nightly's site build stages (tools/stage_site.py).
REGENERABLE = re.compile(
    r"^(?:"
    r"\.alert-state|\.usage_cache\.json|\.claude/?|tools/data/minutecryptic/?"
    r"|(?:.*/)?__pycache__/"
    r"|abbreviations\.js"
    r"|puzzles/[^/]+\.js(?:\.gz)?|puzzles/shims\.gz\.json|puzzles/index\.(?:json|html)|puzzles/idx/|puzzles/series/"
    r"|puzzles/(?:[a-z]+\d*-)?\d+/"  # a staged puzzle page dir: puzzles/<id>/index.html
    r"|(?:abbreviations|difficulty|indicators|learn|og|showcase|progress)/"
    r"|sitemap(?:-[^/]+)?\.xml"
    r"|sync/\.wrangler/"
    r")$")

#: How long a tree may go without a run before sweep_idle() takes it.
IDLE_HOURS = 12

#: Trees are swept only when the filesystem has less free than either of these.
LOW_FREE_FRACTION = 0.15
LOW_FREE_BYTES = 40 * 1024 ** 3

#: Written in a tree's git dir by nightly_worktree.sh at the start of each run.
STAMP = "ct-last-run"


def _git(tree, *args):
    r = subprocess.run(["git", "--no-optional-locks", "-C", str(tree), *args],
                       capture_output=True, text=True, check=False)
    return r.stdout if r.returncode == 0 else None


def disk_low(path):
    """True when the filesystem holding `path` is short of free space."""
    u = shutil.disk_usage(path)
    return u.free < LOW_FREE_BYTES or u.free < LOW_FREE_FRACTION * u.total


def removable(tree):
    """Why `tree` must stay, or None when nothing in it is worth keeping."""
    cherry = _git(tree, "cherry", "origin/master", "HEAD")
    if cherry is None or cherry.strip():
        return "commits origin/master lacks"
    # None is a failed git (keep the tree); "" is the clean answer.
    edits = _git(tree, "status", "--porcelain", "--untracked-files=no")
    if edits is None or edits.strip():
        return "tracked edits"
    others = _git(tree, "ls-files", "--others", "--exclude-standard")
    if others is None or others.strip():
        return "untracked files"
    ignored = _git(tree, "status", "--porcelain", "--ignored", "--untracked-files=normal")
    if ignored is None:
        return "unreadable status"
    for line in ignored.splitlines():
        path = line[3:].strip()
        if line.startswith("!! ") and not REGENERABLE.match(path):
            return f"ignored {path} is not rebuilt by itself"
    return None


def sweep(main, root, names, log=print, dry=False, force=False):
    """Remove each idle tree among `names` under `root`; `main` is the main checkout.
    Does nothing while the disk has room (disk_low), unless `force`.
    Returns the names removed (with `dry`, the names that would be)."""
    gone = []
    if not force and not disk_low(root):
        return gone
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
            if dry:
                gone.append(name)
                continue
            r = subprocess.run(["git", "-C", str(main), "worktree", "remove", "--force", str(tree)],
                               capture_output=True, text=True, check=False)
            if r.returncode or tree.exists():
                log(f"tree_sweep: could not remove {name}: {r.stderr.strip()[:200]}")
            else:
                gone.append(name)
        subprocess.run(["git", "-C", str(main), "worktree", "prune"], capture_output=True, check=False)
    if gone:
        log(f"tree_sweep: {'would remove' if dry else 'removed'} idle {' '.join(gone)}")
    return gone


def last_run(main, tree):
    """When the tree's job last started a run (epoch seconds): its STAMP, or for a
    tree made before the stamp existed, the newest of its lease lock, its git dir's
    HEAD and the tree's own directory."""
    gitfile = tree / ".git"
    times = []
    try:
        line = gitfile.read_text(encoding="utf-8").strip()
        gitdir = Path(line[len("gitdir:"):].strip()) if line.startswith("gitdir:") else None
    except OSError:
        gitdir = None
    if gitdir is not None:
        try:
            return (gitdir / STAMP).stat().st_mtime
        except OSError:
            pass
        times.append(gitdir / "HEAD")
    times += [Path(main) / f".{tree.name}.tree.lock", tree]
    return max((p.stat().st_mtime for p in times if p.exists()), default=time.time())


def sweep_idle(main, root, hours=IDLE_HOURS, log=print, dry=False, now=None, force=False):
    """Remove every worktree under `root` whose job has not run for `hours`."""
    now = time.time() if now is None else now
    names = sorted(d.name for d in Path(root).iterdir()
                   if d.is_dir() and not d.is_symlink() and (d / ".git").is_file()
                   and now - last_run(main, d) > hours * 3600)
    return sweep(main, root, names, log=log, dry=dry, force=force)


def worktree_root():
    return os.environ.get("CT_WORKTREE_ROOT") or str(Path.home() / ".cryptic-teacher")


def main_checkout():
    common = subprocess.run(["git", "-C", str(Path(__file__).resolve().parent), "rev-parse",
                             "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    idle = sub.add_parser("idle", help="remove every tree unused for --hours")
    idle.add_argument("--hours", type=float, default=IDLE_HOURS)
    idle.add_argument("--dry-run", action="store_true")
    idle.add_argument("--force", action="store_true", help="sweep even when the disk has room")
    a = p.parse_args(argv)
    sweep_idle(main_checkout(), worktree_root(), a.hours, log=print, dry=a.dry_run, force=a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
