"""Run a whole-history `git log` once per HEAD, not once per caller.

The history walks (backlog_burndown.events, progress_record.annotate_dates,
renamed_ids.from_history) each re-read every commit object, ~290 MB/min of
disk reads on a busy machine. Their output depends only on HEAD and the
arguments, so it is kept in the git dir keyed by both, and a caller whose HEAD
has not moved reads a file instead. Entries for older HEADs are dropped.
"""

import hashlib
import os
import subprocess
from pathlib import Path


def _git(cwd, *args):
    return subprocess.run(
        ["git", "--no-optional-locks", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def log(args, cwd=None):
    """stdout of `git log <args>`, cached per (HEAD, args)."""
    head = _git(cwd, "rev-parse", "HEAD").strip()
    gitdir = Path(
        _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    )
    key = hashlib.sha1("\0".join(args).encode()).hexdigest()[:12]
    cache = gitdir / "gitlog-cache"
    path = cache / f"{key}-{head}.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        pass
    out = _git(cwd, "log", *args)
    try:
        cache.mkdir(exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(out, encoding="utf-8")
        tmp.replace(path)
        for old in cache.glob(f"{key}-*.txt"):
            if old != path:
                old.unlink(missing_ok=True)
    except OSError:
        pass
    return out
