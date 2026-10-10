"""What a planner re-reads every minute off a slow disk, kept until it moves.

A dir's state is its (mtime, ctime): every writer of an edition dir
adds, replaces or removes an entry (fetch_archive_org_editions.write_atomic,
gale_inbox.stage's rename and relink), which moves them, so an unmoved key
is unmoved files. Not its inode: the Media mount (Docker's virtiofs)
numbers a dir afresh once the kernel forgets it, its files unmoved. A dir changed within SETTLED seconds is never kept: a
change within one tick of the filesystem's clock leaves the mtime unmoved.

A ledger is appended to or replaced whole (a new inode); appended() parses
only the whole lines added since its last call, and reads a ledger cut or
rewritten in place (its bytes before the mark moved) whole again.
"""
import json
import os
import pickle
import time

#: Seconds since a dir's last change before its state is kept.
SETTLED = 10

#: {dir: ((mtime, ctime), sorted names, {derived value: value})}
#: of each settled dir listed (seen).
_SEEN = {}

#: {(ledger, fold): (inode, bytes read, their last 64 bytes, folded)} (appended).
_READ = {}

#: The memo entries save() keeps: facts of the files (each name's size, a
#: meta.json's title), not values derived by code that may change.
FACTS = ("sizes", "title", "with_pages")

#: {(file, derive): ((mtime_ns, size), derive(its parsed JSON))} (derived).
_DERIVED = {}


def dir_key(d):
    """(key, settled): dir `d`'s (mtime, ctime) and whether it last
    changed over SETTLED seconds ago. Raises FileNotFoundError."""
    st = os.stat(d)
    return (st.st_mtime_ns, st.st_ctime_ns), time.time() - st.st_mtime > SETTLED


def seen(d):
    """Dir `d`'s (key, sorted names, memo), listed afresh only when its
    dir_key moved; `memo` holds what callers derive from the listing."""
    key, settled = dir_key(d)
    hit = _SEEN.get(d)
    if hit and hit[0] == key:
        return hit
    hit = (key, sorted(os.listdir(d)), {})
    if settled:
        _SEEN[d] = hit
    else:
        _SEEN.pop(d, None)
    return hit


def listed(d):
    """The sorted names in dir `d` ([] when it is no dir)."""
    try:
        return seen(d)[1]
    except (FileNotFoundError, NotADirectoryError):
        return []


def appended(ledger, start, fold):
    """fold(acc, line) over each whole line of `ledger` (bytes, no newline)
    into acc = start(), carried from the last call with this `fold` so only
    the lines appended since are folded. A missing ledger is start()."""
    k = (os.fspath(ledger), fold)
    try:
        fh = open(ledger, "rb")
    except FileNotFoundError:
        _READ.pop(k, None)
        return start()
    with fh:
        st = os.fstat(fh.fileno())
        ino, done, tail, acc = _READ.get(k, (None, 0, b"", None))
        if (acc is None or ino != st.st_ino or st.st_size < done
                or os.pread(fh.fileno(), len(tail), done - len(tail)) != tail):
            done, tail, acc = 0, b"", start()
        fh.seek(done)
        data = fh.read()
    end = data.rfind(b"\n") + 1
    for line in data[:end].split(b"\n"):
        if line.strip():
            fold(acc, line)
    done += end
    _READ[k] = (st.st_ino, done, (tail + data[:end])[-64:], acc)
    return acc


def derived(path, derive):
    """derive(the JSON in file `path`), parsed again only when its
    (mtime_ns, size) moved; a file changed within SETTLED seconds is
    parsed each call. Raises FileNotFoundError."""
    st = os.stat(path)
    stamp = (st.st_mtime_ns, st.st_size)
    k = (os.fspath(path), derive)
    hit = _DERIVED.get(k)
    if hit and hit[0] == stamp:
        return hit[1]
    with open(path, "rb") as f:
        value = derive(json.loads(f.read()))
    if time.time() - st.st_mtime > SETTLED:
        _DERIVED[k] = (stamp, value)
    else:
        _DERIVED.pop(k, None)
    return value


def save(path):
    """Write the settled dirs' listings and FACTS to `path`, for load() in
    the next process (a re-exec or the next slice) to start warm."""
    snap = {d: (key, names, {k: memo[k] for k in FACTS if k in memo}) for d, (key, names, memo) in _SEEN.items()}
    tmp = f"{os.fspath(path)}.{os.getpid()}.tmp"
    os.makedirs(os.path.dirname(os.fspath(path)) or ".", exist_ok=True)
    with open(tmp, "wb") as f:
        pickle.dump(snap, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def load(path):
    """Take the listings save() wrote to `path` for each dir this process
    has not listed; each stands only while its dir_key is unmoved (seen)."""
    try:
        with open(path, "rb") as f:
            snap = pickle.load(f)
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ValueError):
        return
    for d, hit in snap.items():
        _SEEN.setdefault(d, hit)
