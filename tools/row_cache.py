"""A per-file pass over the corpus that parses only the files it has not seen.

    rows = row_cache.cached_map("index_row", index_row, paths, deps=deps, prepare=prepare)
    # == parallel.pmap(index_row, paths)

reindex() and difficulty.all_scores() each read all ~45k puzzle files, and
every job start whose tree moved ran them: minutes of CPU to re-derive rows
for files that had not changed. A row here is stored under a key of
  - the code the function reaches (code_reach.key over `fn`, plus `roots`),
  - the file's path under the repo and its git blob sha (puzzle_integrity's
    listing(), read off git's index; a dirty or untracked file is hashed),
  - `salt`, for an input shared by every row (a data file's hash),
so a row is reused exactly when the code and the file are those it was made
from. What a row reads besides its file, per row (a sidecar's line for the
puzzle's id, a generated file the call writes), is `deps(path, row)`: taken
when the row is made, taken again before it is reused, and the row is made
afresh when the two differ.

`prepare()` runs only when some row is missing, before the workers fork:
the place to load what only a miss needs (the lexicon, wordnet).

The store is one sqlite file under the git common dir, shared by every
worktree of the checkout and by nothing else (a fresh clone, CI, starts
empty). Outside a git checkout, or when the store cannot be opened, the map
runs in full and says why on stderr. Rows unused for PRUNE_DAYS are dropped.
"""
import hashlib
import pickle
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import code_reach
import parallel
import puzzle_paths

PRUNE_DAYS = 14
#: The store; None finds it under the git common dir. Tests set it.
STORE = None


def _store():
    if STORE is not None:
        return Path(STORE)
    root = puzzle_paths.ROOT
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         capture_output=True, text=True)
    if out.returncode:
        raise OSError(f"no git checkout at {root}: {out.stderr.strip()}")
    return Path(out.stdout.strip()) / "ct-rows.sqlite"


def _open():
    conn = sqlite3.connect(_store(), timeout=600)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("CREATE TABLE IF NOT EXISTS rows(key TEXT PRIMARY KEY, val BLOB, deps BLOB, used INTEGER)"
                 " WITHOUT ROWID")
    return conn


def _blobs(paths):
    """{path: git blob sha} for each path."""
    import puzzle_integrity  # noqa: PLC0415 — it imports fetch_puzzle, which imports this
    root = puzzle_paths.PUZZLE_DIR.parent  # what listing() names files under
    listed = puzzle_integrity.listing()
    out = {}
    for p in paths:
        try:
            name = p.resolve().relative_to(root).as_posix()
        except ValueError:
            name = None
        out[p] = listed.get(name) or _blob_sha(p)
    return out


def _blob_sha(path):
    import puzzle_integrity  # noqa: PLC0415
    return puzzle_integrity._blob_sha(path)


def _key(code, path, blob):
    try:
        name = path.resolve().relative_to(puzzle_paths.ROOT).as_posix()
    except ValueError:
        name = str(path.resolve())
    return hashlib.sha1(f"{code}\0{name}\0{blob}".encode()).hexdigest()


def cached_map(name, fn, paths, roots=(), salt="", deps=None, prepare=None):
    """[fn(p) for p in paths], each row reused when its file, its code and
    deps(p, row) are those it was made from. `name` is fn's module:
    code_reach.key(name, {fn.__name__, *roots})."""
    paths = list(paths)
    try:
        conn = _open()
        code = f"{name}.{fn.__name__}:{code_reach.key(name, {fn.__name__, *roots})}:{salt}"
        keys = {p: _key(code, p, b) for p, b in _blobs(paths).items()}
        stored = {}
        uniq = list(set(keys.values()))
        for i in range(0, len(uniq), 900):
            part = uniq[i:i + 900]
            stored.update((k, (v, d, u)) for k, v, d, u in conn.execute(
                f"SELECT key, val, deps, used FROM rows WHERE key IN ({','.join('?' * len(part))})", part))
    except (OSError, sqlite3.Error) as err:
        print(f"row cache for {name}.{fn.__name__}: {err!r}; computing every row", file=sys.stderr)
        if prepare:
            prepare()
        return parallel.pmap(fn, paths)
    deps = deps or (lambda path, row: None)
    out, miss = {}, []
    for p in paths:
        hit = stored.get(keys[p])
        if hit is not None:
            row = pickle.loads(hit[0])
            if pickle.loads(hit[1]) == deps(p, row):
                out[p] = row
                continue
        miss.append(p)
    missed = set(miss)
    if miss:
        if prepare:
            prepare()
        made = parallel.pmap(fn, miss)
        out.update(zip(miss, made))
    # A file rewritten since the listing was read as its new content: its row
    # is not stored under the old content's key.
    keep = [p for p in miss if p.exists() and _key(code, p, _blob_sha(p)) == keys[p]]
    today = int(time.time() // 86400)
    try:
        with conn:
            conn.executemany("INSERT OR REPLACE INTO rows VALUES(?,?,?,?)",
                             ((keys[p], pickle.dumps(out[p]), pickle.dumps(deps(p, out[p])), today) for p in keep))
            conn.executemany("UPDATE rows SET used=? WHERE key=?",
                             ((today, keys[p]) for p in paths if p not in missed and stored[keys[p]][2] != today))
            conn.execute("DELETE FROM rows WHERE used < ?", (today - PRUNE_DAYS,))
    except sqlite3.Error as err:
        print(f"row cache for {name}.{fn.__name__}: could not store {len(miss)} rows: {err!r}", file=sys.stderr)
    finally:
        conn.close()
    return [out[p] for p in paths]
