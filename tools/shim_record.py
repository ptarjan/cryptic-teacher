"""The md5[:8] of each puzzles/<id>.js shim, vouched for by its stat.

    shim_record.md5(shim)   # == hashlib.md5(shim.read_bytes()).hexdigest()[:8], or None
    shim_record.save()      # keep what this process hashed for the next one

fetch_puzzle.index_row_deps() checks that every reused index row's shim is
the one the row was made with, by its hash. Reading every shim to hash it
was ~90k small reads, nearly all of the deploy's reindex step. Here a shim
is read only when its stat is not the one recorded beside its hash.

The record is RECORD in puzzles/, beside the shims, and travels in the
deploy's shim cache with them (tools/cache_tar.sh), so a CI run starts with
the record of the very files it unpacked. An entry is [md5[:8], size,
mtime in whole seconds]: whole seconds because tar keeps no more, so a shim
that went through the cache still matches. Inode and ctime are left out for
the same reason: tar cannot keep them.

Why a matching stat means the same bytes: an entry is written only for a
shim whose mtime was more than RACY_NS before the clock read just ahead of
its stat. Any write after that stat stamps an mtime at least that clock
reading, so a later second, and the stat no longer matches. A write before
the stat is in the stat. The clock that judges this is the one the next
write will be stamped by, so another machine's clock (a restored cache's
mtimes) cannot make an entry that a write here would match. What it cannot
see is a writer that sets an old mtime on purpose (touch -d, cp -p) to a
file of the same size; nothing writes shims that way, and tar does it only
when it unpacks the archive that also carries this record.

The record is a cache of hashes and nothing else: lost, unreadable or
stale, it costs reads, never a wrong answer, since every entry is checked
against the file's stat before it is believed.
"""
import hashlib
import json
import os
import time

import puzzle_paths

RECORD = "shims.md5.json"
#: A shim written this recently, when it is hashed, gets no entry: a write
#: in the same second could leave its stat alike. Shims written by this run's
#: rows are hashed once more by the next run, which records them.
RACY_NS = 2 * 10**9

#: {puzzles dir: [record, changed]}, loaded once per process per dir.
_LOADED = {}


def _record(folder):
    if folder not in _LOADED:
        try:
            rec = json.loads((folder / RECORD).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rec = {}
        _LOADED[folder] = [rec if isinstance(rec, dict) else {}, False]
    return _LOADED[folder]


def md5(shim):
    """md5[:8] of the shim's bytes, None when there is no shim. A shim outside
    puzzle_paths.PUZZLE_DIR (a fixture's, beside its file) is always read."""
    folder = puzzle_paths.PUZZLE_DIR
    if shim.parent != folder:
        try:
            return hashlib.md5(shim.read_bytes()).hexdigest()[:8]
        except FileNotFoundError:
            return None
    held = _record(folder)
    now = time.time_ns()  # before the stat: see the module docstring
    try:
        st = os.stat(shim)
    except FileNotFoundError:
        return None
    sig = [st.st_size, st.st_mtime_ns // 10**9]
    known = held[0].get(shim.name)
    if isinstance(known, list) and known[1:] == sig:
        return known[0]
    try:
        got = hashlib.md5(shim.read_bytes()).hexdigest()[:8]
    except FileNotFoundError:
        return None
    if now - st.st_mtime_ns > RACY_NS:
        held[0][shim.name] = [got, *sig]
        held[1] = True
    return got


def save():
    """Write each record this process added to, whole or not at all, by a
    rename (a concurrent writer's entries may be lost: that costs the next
    run reads, nothing more)."""
    for folder, held in _LOADED.items():
        if not held[1]:
            continue
        part = folder / f".{RECORD}.{os.getpid()}.part"
        try:
            part.write_text(json.dumps(held[0], separators=(",", ":")), encoding="utf-8")
            os.replace(part, folder / RECORD)
        except OSError:
            part.unlink(missing_ok=True)
            continue
        held[1] = False
