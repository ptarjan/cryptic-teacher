"""Run a whole-history `git log` once per HEAD, not once per caller.

The history walks (backlog_burndown.events, progress_record.annotate_dates,
renamed_ids.from_history) each re-read every commit object, ~290 MB/min of
disk reads on a busy machine. Their output depends only on HEAD and the
arguments, so it is kept in the git dir keyed by both, and a caller whose HEAD
has not moved reads a file instead. Entries for older HEADs are dropped.

HEAD moves every few minutes, so when an entry exists for an older HEAD that is
an ancestor of the current one, only `<old>..HEAD` is walked and spliced on:
appended for --reverse, prepended otherwise. Rename detection (-M) is a
per-commit diff, so a pathspec-limited range gives the same per-commit records
as the full walk. Args where a range splice would change the result (-n,
--max-count, -<N>, --skip, --since/--until, --follow, ...) and a non-ancestor
old HEAD (force-push, rebase) fall back to the full walk.
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


_UNSAFE = ("-n", "--max-count", "--skip", "--since", "--until", "--after",
           "--before", "--follow", "--max-age", "--min-age", "--no-walk",
           "--ancestry-path", "--first-parent", "-g", "--walk-reflogs")


def _splice_safe(args):
    for a in args:
        if a == "--":
            break
        if a.lstrip("-").isdigit() and a.startswith("-"):
            return False
        if a.split("=")[0] in _UNSAFE or a.startswith(("-n", "--max-count")):
            return False
    return True


def _range_args(args, old):
    """args with the revision limited to old..HEAD (explicit HEAD replaced)."""
    rng = f"{old}..HEAD"
    if "HEAD" in args:
        return [rng if a == "HEAD" else a for a in args]
    if "--" in args:
        i = args.index("--")
        return args[:i] + [rng] + args[i:]
    return [*args, rng]


def _incremental(cwd, cache, key, head, args):
    """Cached output for an older ancestor HEAD plus the new range, or None."""
    if not _splice_safe(args):
        return None
    for old_path in cache.glob(f"{key}-*.txt"):
        old = old_path.stem.split("-", 1)[1]
        try:
            subprocess.run(
                ["git", "--no-optional-locks", "merge-base", "--is-ancestor", old, head],
                cwd=cwd, check=True, capture_output=True)
            base = old_path.read_text(encoding="utf-8")
            new = _git(cwd, "log", *_range_args(args, old))
        except (subprocess.CalledProcessError, OSError):
            continue
        if not new:
            return base
        if base and not base.endswith("\n"):  # --format= output has no trailing newline
            base += "\n"
        return base + new if "--reverse" in args else new + base
    return None


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
    out = _incremental(cwd, cache, key, head, args)
    if out is None:
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
