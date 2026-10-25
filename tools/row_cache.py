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

A map with `stale_ok` (puzzle_integrity's) also keeps, per file, a pointer to
the last row made for it; a code change then leaves the answer complete from
the older rows while fresh ones are made, deadline by deadline.

The store is one sqlite file under the git common dir, shared by every
worktree of the checkout and by nothing else (a fresh clone, CI, starts
empty). Outside a git checkout, or when the store cannot be opened, the map
runs in full and says why on stderr. Rows unused for PRUNE_DAYS are dropped.
"""
import hashlib
import json
import pickle
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import budget
import code_reach
import parallel
import puzzle_paths
import unit_more

PRUNE_DAYS = 3
#: The most missing rows made between deadline checks, under a deadline
#: (tools/budget.py): enough for every worker. Each batch is also cut to the
#: rows the time left holds at the pace measured so far (batch_size), so a stop
#: lands at the deadline, not a batch past it: 1024 cold puzzle views took
#: ~2 minutes at nice 19, and the burn's re-plan was killed waiting on one.
BATCH = 1024
#: The first batch, which measures the pace.
FIRST_BATCH = 64


def batch_size(left, per_row):
    """Rows for the next batch: what `left` seconds hold at `per_row` seconds a
    row, at least one, at most BATCH."""
    if per_row <= 0:
        return BATCH
    return max(1, min(BATCH, int(max(left, 0) / per_row)))
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


def _blobs(paths, listed=None):
    """{path: git blob sha} for each path, off `listed`
    (puzzle_integrity.listing(), read here unless the caller holds it)."""
    import puzzle_integrity  # lazy: it imports fetch_puzzle, which imports this
    root = puzzle_paths.PUZZLE_DIR.parent  # what listing() names files under
    if listed is None:
        listed = puzzle_integrity.listing()
    out = {}
    for p in paths:
        out[p] = listed.get(puzzle_paths.relative(p, root)) or _blob_sha(p)
    return out


def _blob_sha(path):
    import puzzle_integrity  # lazy, as in _blobs
    return puzzle_integrity._blob_sha(path)


def _legacy_key(code, path, blob):
    """The key rows were stored under before 2026-10-15: a bare sha1, which
    scatters one run's rows over the whole store."""
    name = puzzle_paths.relative(path, puzzle_paths.ROOT) or puzzle_paths.real(path)
    return hashlib.sha1(f"{code}\0{name}\0{blob}".encode()).hexdigest()


def _prefix(code):
    return hashlib.sha1(code.encode()).hexdigest()[:16]


def _key(code, path, blob):
    """`<code prefix>:<legacy key>`: every row one code made sorts together,
    so a map reads its rows in one range scan. Point lookups of ~55k sha1
    keys in a store of gigabytes cost a random page read each, ~10s per 900
    keys on a loaded host: most of a warm puzzle_integrity run (2026-10-15)."""
    return f"{_prefix(code)}:{_legacy_key(code, path, blob)}"


#: How many missing keys are looked up under their legacy key before the
#: rest are: a new code has no legacy rows, and looking up all ~55k of them
#: would cost minutes for nothing.
LEGACY_PROBE = 200


def _lookup(conn, code, keys):
    """({key: (val, deps, used)}, {key: legacy key}) for the wanted keys
    (the values of `keys`) stored under `code`: one range scan, then, for
    keys it lacks, their legacy keys if a probe of LEGACY_PROBE finds any.
    A row found only under its legacy key has used None, to be written anew."""
    lo = _prefix(code) + ":"
    want = set(keys.values())
    stored = {k: (v, d, u) for k, v, d, u in conn.execute(
        "SELECT key, val, deps, used FROM rows WHERE key >= ? AND key < ?", (lo, lo[:-1] + ";")) if k in want}
    legacy = {k: k[len(lo):] for k in want if k not in stored}
    names = list(legacy.values())
    found = {}
    parts = [names[:LEGACY_PROBE]] + [names[i:i + 900] for i in range(LEGACY_PROBE, len(names), 900)]
    for n, part in enumerate(p for p in parts if p):
        if n and not found:
            break
        found.update((k, (v, d)) for k, v, d in conn.execute(
            f"SELECT key, val, deps FROM rows WHERE key IN ({','.join('?' * len(part))})", part))
    moved = {}
    for k, old in legacy.items():
        if old in found:
            stored[k] = (*found[old], None)
            moved[k] = old
    return stored, moved


def data_files(name, roots):
    """The tools/data files (not folders) that code `roots` (in module
    `name`) reach, as Paths: each is hashed into every row's key by
    cached_map, so a new data-file read is keyed without being declared.
    A folder a row reads one file of must come through deps(). A file read
    only through a DERIVED definition is left out: that definition's output
    keys the row instead."""
    return keyed_inputs(name, roots)[0]


#: Definitions whose output, not the data files behind them, keys a row that
#: reaches them. build_abbreviations.table() is built from blocks.json's clue
#: counts (only whether a sense has a clue at all), and the blog-facts unit
#: commits a new blocks.json each run: keyed on the file's bytes, every
#: index_row, difficulty, blog_facts and puzzle_integrity row (~55k each) was
#: made again after each one, though the table rarely moves (2026-10-15).
DERIVED = {"build_abbreviations.table": lambda: __import__("build_abbreviations").table()}


def reach_past_derived(name, roots):
    """(what `roots` reach short of any DERIVED definition, the DERIVED
    definitions they reach)."""
    full = code_reach.reach(name, set(roots))
    derived = sorted(d for d in DERIVED if tuple(d.split(".", 1)) in full)
    if not derived:
        return full, []
    return code_reach.reach(name, set(roots), opaque=(*code_reach.TRANSPORT, *derived)), derived


def keyed_inputs(name, roots):
    """(data_files(name, roots), the DERIVED definitions they reach)."""
    import importlib
    data = (Path(__file__).resolve().parent / "data").resolve()
    found = set()
    reached, derived = reach_past_derived(name, roots)
    for mod, attr in reached:
        obj = getattr(importlib.import_module(mod), attr, None)
        if isinstance(obj, Path) and obj.is_relative_to(data) and not obj.is_dir():
            found.add(obj)
    return sorted(found), derived


#: keyed_inputs() per (module, roots, code key): following the code to its
#: data files took ~4s a call, and blog_facts.puzzle_rows calls three times a
#: run. The files are a function of the code, so the code key keys them; their
#: bytes, and the DERIVED outputs, are hashed afresh each call.
_DATA_FILES = {}


def _data_salt(name, roots, code_key=None):
    k = (name, frozenset(roots), code_key)
    if code_key is None or k not in _DATA_FILES:
        _DATA_FILES[k] = keyed_inputs(name, roots)
    files, derived = _DATA_FILES[k]
    h = hashlib.sha1()
    for p in files:
        h.update(p.name.encode() + b"\0" + (p.read_bytes() if p.exists() else b"absent") + b"\0")
    for d in derived:
        out = json.dumps(DERIVED[d](), sort_keys=True, separators=(",", ":"))
        h.update(d.encode() + b"\0" + out.encode() + b"\0")
    return h.hexdigest()[:16]


def _pointers(conn, ns):
    """{path under the repo: (blob, key, used)}: for each file, the key of the
    last row made for it by any code (written when `stale_ok`)."""
    lo = f"L:{ns}:"
    return {k[len(lo):]: (*pickle.loads(v), u) for k, v, u in conn.execute(
        "SELECT key, val, used FROM rows WHERE key >= ? AND key < ?", (lo, lo[:-1] + ";"))}


def _carry_over(conn, ptrs, want):
    """{path: row} for the files in `want` ({path: (rel, blob)}) whose pointer
    names a row of the same content made by older code: one range scan per old
    code (a code's rows sort together), not a point lookup per row."""
    by_code = {}
    for p, (rel, blob) in want.items():
        ptr = ptrs.get(rel)
        if ptr and ptr[0] == blob:
            by_code.setdefault(ptr[1].split(":", 1)[0], {})[ptr[1]] = p
    out = {}
    for prefix, keys in by_code.items():
        lo = prefix + ":"
        for k, v in conn.execute("SELECT key, val FROM rows WHERE key >= ? AND key < ?", (lo, lo[:-1] + ";")):
            if k in keys:
                out[keys[k]] = pickle.loads(v)
    return out


def code_for(name, fn_name, roots=(), salt=""):
    """The code part of every row key cached_map(name, fn, roots=roots,
    salt=salt) makes: the code fn reaches plus the data files it reads. Two
    checkouts with the same answer make the same row from the same file, so
    an index another machine built for that answer is the one this machine
    would build (fetch_puzzle.reindex_from_deploy)."""
    code_key = code_reach.key(name, {fn_name, *roots})
    return f"{name}.{fn_name}:{code_key}:{salt}:{_data_salt(name, {fn_name, *roots}, code_key)}"


class TooManyMisses(Exception):
    """cached_map found more missing rows than its `max_miss` allows."""

    def __init__(self, ns, misses, limit):
        super().__init__(f"row cache for {ns}: {misses} rows missing (limit {limit})")
        self.misses, self.limit = misses, limit


def cached_map(name, fn, paths, roots=(), salt="", deps=None, prepare=None, listed=None, stale_ok=False,
               max_miss=None):
    """[fn(p) for p in paths], each row reused when its file, its code and
    deps(p, row) are those it was made from. `name` is fn's module:
    code_reach.key(name, {fn.__name__, *roots}). `listed` is
    puzzle_integrity.listing() where the caller has read it already: read
    again here, it cost puzzle_integrity's whole-corpus run ~40s.

    `stale_ok`: every code change makes every row missing, and a map whose
    rows take longer than a unit's deadline to make (puzzle_integrity's
    validator changes most days; 55k rows, ~30 minutes) would never finish a
    build before the code moved again (2026-10-16: "0 were stored" at the
    start of each run). With it, a file whose content is unchanged since a
    row made by OLDER code keeps that row until a fresh one is made; rows no
    code has made come first; at the deadline the map returns, with the
    unit marked as having backlog left, instead of stopping, so the caller
    always has a complete answer and the rows catch up across runs.

    `max_miss`: raise TooManyMisses, making nothing, when more rows than this
    are missing."""
    paths = list(paths)
    try:
        conn = _open()
        code = code_for(name, fn.__name__, roots, salt)
        blobs = _blobs(paths, listed)
        keys = {p: _key(code, p, b) for p, b in blobs.items()}
        stored, moved = _lookup(conn, code, keys)
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
    if max_miss is not None and len(miss) > max_miss:
        # Before anything is made: a cache-key change must not silently turn
        # a cheap step into a whole-corpus scan (`max_miss`: raise instead).
        raise TooManyMisses(f"{name}.{fn.__name__}", len(miss), max_miss)
    missed = set(miss)
    today = int(time.time() // 86400)
    ns = f"{name}.{fn.__name__}"
    root = puzzle_paths.PUZZLE_DIR.parent
    rels = {p: puzzle_paths.relative(p, root) for p in paths} if stale_ok else {}
    ptrs, fresh_from = {}, 0
    if stale_ok:
        try:
            ptrs = _pointers(conn, ns)
            old = _carry_over(conn, ptrs, {p: (rels[p], blobs[p]) for p in miss}) if miss else {}
        except sqlite3.Error as err:
            print(f"row cache for {ns}: could not read older rows: {err!r}", file=sys.stderr)
            old = {}
        # Rows no code has made first; the ones with an older row after them.
        miss = [p for p in miss if p not in old] + [p for p in miss if p in old]
        fresh_from = len(miss) - len(old)
        out.update(old)

    def point(ps):
        """Pointer rows for `ps`, written where they are not those stored."""
        return ((f"L:{ns}:{rels[p]}", pickle.dumps((blobs[p], keys[p])), pickle.dumps(None), today)
                for p in ps if ptrs.get(rels[p], (None, None))[:2] != (blobs[p], keys[p]))

    def store(made):
        # A file rewritten since the listing was read as its new content: its
        # row is not stored under the old content's key.
        keep = [p for p in made if p.exists() and _key(code, p, _blob_sha(p)) == keys[p]]
        conn.executemany("INSERT OR REPLACE INTO rows VALUES(?,?,?,?)",
                         ((keys[p], pickle.dumps(out[p]), pickle.dumps(deps(p, out[p])), today) for p in keep))
        if stale_ok:
            conn.executemany("INSERT OR REPLACE INTO rows VALUES(?,?,?,?)", point(keep))

    unstored = miss
    if miss:
        if prepare:
            prepare()
        if budget.deadline() is None:
            out.update(zip(miss, parallel.pmap(fn, miss)))
        else:
            # Under a unit's deadline (tools/budget.py), a batch at a time,
            # each stored as it is made: a cold cache (new code, a grown
            # corpus) is then a few runs that each stop cleanly, not a kill.
            unstored = []
            i, n, spent_s = 0, min(BATCH, FIRST_BATCH), 0.0
            while i < len(miss):
                if stale_ok and i >= fresh_from and budget.spent():
                    # Only rows that have an older row are left: the answer is
                    # complete, so keep it and finish them next run.
                    unit_more.backlog_left()
                    print(f"out of time (CT_DEADLINE): row cache for {ns}: {i - fresh_from} of {len(old)} rows"
                          f" made afresh; the rest keep the row older code made, next run", file=sys.stderr)
                    break
                part = miss[i:min(i + n, fresh_from) if stale_ok and i < fresh_from else i + n]
                t = time.time()
                out.update(zip(part, parallel.pmap(fn, part)))
                spent_s += time.time() - t
                try:
                    with conn:
                        store(part)
                except sqlite3.Error as err:
                    print(f"row cache for {name}.{fn.__name__}: could not store {len(part)} rows: {err!r}",
                          file=sys.stderr)
                done = i = i + len(part)
                if done < len(miss) and budget.spent() and not (stale_ok and done >= fresh_from):
                    conn.close()
                    budget.stop(f"row cache for {name}.{fn.__name__}: made {done} of {len(miss)} missing rows"
                                f" ({len(paths) - len(miss)} were stored); the rest next run")
                n = batch_size(budget.left(), spent_s / done)
    try:
        with conn:
            store(unstored)
            # A row found under its legacy key is written under its new one;
            # the legacy row ages out with the prune.
            conn.executemany("INSERT OR REPLACE INTO rows VALUES(?,?,?,?)",
                             ((k, stored[k][0], stored[k][1], today)
                              for k in {keys[p] for p in paths if p not in missed and keys[p] in moved}))
            if stale_ok:
                conn.executemany("INSERT OR REPLACE INTO rows VALUES(?,?,?,?)",
                                 point(p for p in paths if p not in missed))
                conn.executemany("UPDATE rows SET used=? WHERE key=?",
                                 ((today, f"L:{ns}:{rels[p]}") for p in paths
                                  if p not in missed and ptrs.get(rels[p], (0, 0, today))[2] != today))
            conn.executemany("UPDATE rows SET used=? WHERE key=?",
                             ((today, keys[p]) for p in paths
                              if p not in missed and keys[p] not in moved and stored[keys[p]][2] != today))
            # The prune is a full scan (`used` has no index, and the store is
            # gigabytes: 2.6GB re-read per call, three calls a reindex, under
            # memory pressure), yet its cutoff moves only when the day does,
            # so it runs once a day: user_version holds the day it last ran.
            if conn.execute("PRAGMA user_version").fetchone()[0] != today:
                conn.execute("DELETE FROM rows WHERE used < ?", (today - PRUNE_DAYS,))
                conn.execute(f"PRAGMA user_version={today}")
    except sqlite3.Error as err:
        print(f"row cache for {name}.{fn.__name__}: could not store {len(miss)} rows: {err!r}", file=sys.stderr)
    finally:
        conn.close()
    return [out[p] for p in paths]
