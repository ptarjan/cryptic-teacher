"""The commit that last deleted a path, read from a cache.

`git log -1 --diff-filter=D -- <path>` walks all of history for every path it
is asked about, which takes minutes on this repo. last_deletion() answers the
same question from a map of path -> the commits that deleted it, newest first,
built by one walk of history and stored under the git common dir, so every
worktree shares it. The stored map names the tip it covers and is extended
with `<tip>..HEAD` when HEAD descends from that tip. A HEAD that does not (an
older or diverged worktree) is answered by dropping the deletions HEAD cannot
reach and adding the ones on its own side of the merge base; a HEAD sharing no
history with the tip (a rewrite) rebuilds the map. Writers hold a lock and
replace the file atomically, so concurrent callers never see half a map.

Only paths under `prefix` are mapped; a path outside it is answered by git.
Renames count as a deletion of the old path, as the per-path log reports them.
"""
import fcntl
import json
import os
import subprocess
import tempfile
from pathlib import Path

VERSION = 1


def _git(root, *args, check=True):
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                         check=False)
    if check and out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} in {root} failed "
                           f"({out.returncode}): {out.stderr.strip()}")
    return out


def _walk(root, revs, prefix):
    """{path: [deleting commit, newest first]} over `revs`, limited to prefix."""
    out = _git(root, "log", "--no-renames", "--diff-filter=D", "--name-only",
               "--format=@%H", *revs, "--", prefix).stdout
    found, commit = {}, None
    for line in out.splitlines():
        if line.startswith("@"):
            commit = line[1:]
        elif line:
            found.setdefault(line, []).append(commit)
    return found


def _merged(newer, older):
    keys = newer.keys() | older.keys()
    return {k: newer.get(k, []) + older.get(k, []) for k in keys}


def _store_path(root, prefix):
    common = Path(_git(root, "rev-parse", "--git-common-dir").stdout.strip())
    if not common.is_absolute():
        common = Path(root) / common
    name = prefix.strip("/").replace("/", "_") or "all"
    return common / "cryptic-teacher" / f"deleted-paths-{name}.json"


def _load(store, prefix):
    try:
        data = json.loads(store.read_text())
    except (OSError, ValueError):
        return None
    if data.get("version") != VERSION or data.get("prefix") != prefix:
        return None
    return data


def _is_ancestor(root, a, b):
    return _git(root, "merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def _save(store, data):
    fd, tmp = tempfile.mkstemp(dir=store.parent, prefix=store.name + ".")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, store)


def _fresh(root, prefix, head):
    """The stored map: extended to `head` when head descends from its tip,
    returned as is when head is behind or beside it, and rebuilt when there
    is none or it shares no history with head."""
    store = _store_path(root, prefix)
    data = _load(store, prefix)
    if data and data["tip"] == head:
        return data
    store.parent.mkdir(parents=True, exist_ok=True)
    with open(store.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _load(store, prefix)  # another writer may have done the work
        if data and data["tip"] == head:
            return data
        if data and _is_ancestor(root, data["tip"], head):
            deleted = _merged(_walk(root, [f"{data['tip']}..{head}"], prefix), data["deleted"])
        elif data and _git(root, "merge-base", data["tip"], head, check=False).returncode == 0:
            return data  # head is behind or beside the tip; deletions() adjusts
        else:
            deleted = _walk(root, [head], prefix)
        data = {"version": VERSION, "prefix": prefix, "tip": head, "deleted": deleted}
        _save(store, data)
        return data


_memo = {}


def deletions(root, prefix):
    """{path: [commits that deleted it, newest first]} as seen from root's HEAD."""
    root = str(root)
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    key = (root, prefix, head)
    if key in _memo:
        return _memo[key]
    data = _fresh(root, prefix, head)
    deleted = data["deleted"]
    if data["tip"] != head:
        # head is behind or beside the stored tip: drop what head cannot reach,
        # add what only head has.
        unreachable = set(_git(root, "rev-list", f"{head}..{data['tip']}").stdout.split())
        own = _walk(root, [f"{data['tip']}..{head}"], prefix)
        deleted = _merged(own, {p: kept for p, cs in deleted.items()
                                if (kept := [c for c in cs if c not in unreachable])})
    _memo.clear()
    _memo[key] = deleted
    return deleted


def last_deletion(root, rel, prefix):
    """The newest commit reachable from HEAD that deleted `rel`, or None —
    what `git log -1 --diff-filter=D --format=%H -- rel` prints."""
    if not rel.startswith(prefix.rstrip("/") + "/"):
        gone = _git(root, "log", "-1", "--diff-filter=D", "--format=%H", "--", rel,
                    check=False).stdout.strip()
        return gone or None
    found = deletions(root, prefix).get(rel)
    return found[0] if found else None
