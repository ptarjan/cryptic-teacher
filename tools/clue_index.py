#!/usr/bin/env python3
"""Which puzzle files share clues: normalised clue text -> puzzle ids.

A page that copies another puzzle under a new id (a Guardian URL that serves a
different puzzle's clues) is caught by looking its clues up here, whatever the
other puzzle's series or number. Used by puzzle_integrity.py (whole corpus) and
fetch_puzzle.py (before filing). No pairwise comparison: each clue is looked up
once and the hits are counted per puzzle.

StoredClueIndex answers the same questions off a sqlite store of every file
content's clue keys, keyed by git blob sha, so a write looks up its own clues
instead of parsing the whole corpus first.
"""
import fcntl
import hashlib
import inspect
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import puzzle_paths  # noqa: E402

#: A pair sharing at least this fraction of the smaller puzzle's clues is one
#: puzzle filed twice.
THRESHOLD = 0.8
#: Fewer clues than this say nothing (a stub shares its three clues with anyone).
MIN_CLUES = 6

#: Pairs of puzzle ids that legitimately share clues, each with the reason.
#: Exempted by id, not by raising THRESHOLD: a threshold loose enough to pass
#: these would pass a copy filed under the wrong number. Each pair here is a
#: setter re-running an old puzzle with a few clues reworded, or a book or paper
#: reprinting one; both files come from their own dated publication, so neither
#: is a mis-filed copy of the other.
REPRINTS = {
    frozenset(pair): why for pair, why in (
        (("book-19003", "book-23183"), "Telegraph Book 28 No 3, reprinted as Big Book of Brain Sharpener vol 1 No 183"),
        (("book-19005", "book-23185"), "Telegraph Book 28 No 5, reprinted as Big Book of Brain Sharpener vol 1 No 185"),
        (("book-19012", "book-23191"), "Telegraph Book 28 No 12, reprinted as Big Book of Brain Sharpener vol 1 No 191"),
        (("book-19028", "book-23184"), "Telegraph Book 28 No 28, reprinted as Big Book of Brain Sharpener vol 1 No 184"),
        (("book-19050", "book-23211"), "Telegraph Book 28 No 50, reprinted as Big Book of Brain Sharpener vol 1 No 211"),
        (("canberra-720523", "canberra-720926"), "the Canberra Times printed one Times puzzle twice, 1972-05 and 1972-09"),
        (("cryptic-25328", "cryptic-26328"), "Pasquale prize, rerun 2011 -> 2014"),
        (("ftcryptic-13761", "ftcryptic-14223"), "Jason rerun, one clue reworded"),
        (("ftcryptic-14853", "ftcryptic-14947"), "Aardvark rerun, one clue reworded"),
        (("ftcryptic-15011", "ftcryptic-15128"), "Dante rerun, one clue reworded"),
        (("ftcryptic-16776", "ftcryptic-16806"), "Basilisk rerun, one clue reworded"),
        (("ftcryptic-16016", "ftcryptic-18479"), "Orense memorial rerun after his death in 2026-08"),
        (("independent-8933", "independent-9036"), "Quixote rerun, one clue reworded"),
        (("independent-9623", "independent-9802"), "Punk rerun, three clues reworded"),
        (("telegraph-26049", "telegraph-26216"), "rerun, one clue reworded"),
        (("times-27331", "times-29539"), "Times rerun, five clues reworded"),
    )
}
# Series that bought another paper's puzzles and printed them weeks later:
# their copies are the same puzzle by design, not a page under a wrong id.
SYNDICATED = {
    frozenset(pair): why for pair, why in (
        (("canberra", "times"), "the Canberra Times reprinted the Times's cryptic in the 1970s"),
    )
}


def known_copy(a, b):
    """Whether ids `a` and `b` are a listed rerun or a syndicated reprint."""
    series = frozenset(pid.rsplit("-", 1)[0] for pid in (a, b))
    return frozenset((a, b)) in REPRINTS or series in SYNDICATED


def norm(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def clue_keys(puzzle):
    """The set of normalised clue texts of a puzzle (empty clues dropped)."""
    keys = set()
    for e in puzzle.get("entries") or []:
        c = e.get("clue")
        text = c.get("text") if isinstance(c, dict) else c
        if isinstance(text, str) and (k := norm(text)):
            keys.add(k)
    return keys


class ClueIndex:
    def __init__(self):
        self.by_clue = defaultdict(set)   # clue key -> ids
        self.size = {}                    # id -> number of clue keys

        self.keys = {}                    # id -> its clue keys

    def add(self, pid, puzzle):
        self.add_keys(pid, clue_keys(puzzle))

    def add_keys(self, pid, keys):
        self.discard(pid)
        self.size[pid] = len(keys)
        self.keys[pid] = keys
        for k in keys:
            self.by_clue[k].add(pid)

    def discard(self, pid):
        """Forget `pid` (a file deleted, or about to be re-added)."""
        for k in self.keys.pop(pid, ()):
            self.by_clue[k].discard(pid)
        self.size.pop(pid, None)

    @classmethod
    def build(cls, paths=None):
        idx = cls()
        for path in (puzzle_paths.puzzle_files() if paths is None else paths):
            try:
                puzzle = json.loads(Path(path).read_text(encoding="utf-8"))
                idx.add(puzzle.get("id") or Path(path).stem, puzzle)
            except (OSError, ValueError, AttributeError):
                continue
        return idx

    def matches(self, pid, keys):
        """[(other id, shared, mine, theirs)] for every other puzzle sharing at
        least THRESHOLD of the smaller one's clues, best first."""
        hits = Counter()
        for k in keys:
            for other in self.by_clue.get(k, ()):
                if other != pid:
                    hits[other] += 1
        out = []
        for other, shared in hits.items():
            small = min(len(keys), self.size[other])
            if (small >= MIN_CLUES and shared >= THRESHOLD * small
                    and not known_copy(pid, other)):
                out.append((other, shared, len(keys), self.size[other]))
        return sorted(out, key=lambda m: -m[1])

    def pairs(self):
        """Every near-duplicate pair (a, b, shared, na, nb) with a < b.

        A pair passes only when the smaller puzzle shares at least `need` of
        its clues, so any (size - need + 1) of its clues hold at least one
        shared one. Each puzzle therefore looks up only that many of its
        rarest clues, against partners no smaller than itself, and counts the
        overlap exactly for each partner found. A clue every puzzle carries
        ("See 1") is never what pairs two puzzles up."""
        found = set()
        for a, keys in self.keys.items():
            size = len(keys)
            if size < MIN_CLUES:
                continue
            need = _need(size)
            rarest = sorted(keys, key=lambda k: (len(self.by_clue[k]), k))
            for k in rarest[:size - need + 1]:
                for b in self.by_clue[k]:
                    if b != a and self.size[b] >= size:
                        found.add((a, b) if a < b else (b, a))
        out = []
        for a, b in sorted(found):
            shared = len(self.keys[a] & self.keys[b])
            small = min(self.size[a], self.size[b])
            if (small >= MIN_CLUES and shared >= THRESHOLD * small
                    and not known_copy(a, b)):
                out.append((a, b, shared, self.size[a], self.size[b]))
        return out


class StoredClueIndex:
    """ClueIndex.build() of the real corpus, read off STORE_DIR instead of
    parsing every file: one row per distinct file content (git blob sha ->
    id, number of clue keys) and one (clue key, row) pair per key, indexed by
    key. A content is parsed once, by whichever process first meets it, under
    a lock so that units starting together do not all parse the same files.
    The store's file name carries a hash of norm() and clue_keys(), so code
    that keys clues differently never reads keys made by other code.

    The corpus is listed once, at open(), as ClueIndex.build() reads it once;
    add() and discard() change this process's view only, as on a ClueIndex.
    Any sqlite failure falls back to ClueIndex.build(): a store that cannot be
    read answers nothing, it never answers "no copy"."""

    def __init__(self, conn, by_pid):
        self.conn = conn
        self.by_pid = by_pid              # id -> (row, number of clue keys)
        self.of_row = defaultdict(list)   # row -> the ids it is the file of
        for pid, (row, _) in by_pid.items():
            self.of_row[row].append(pid)
        self.mine = {}                    # id -> keys added here, None: discarded
        self.fallback = None

    @classmethod
    def open(cls, store_dir=None):
        store_dir = STORE_DIR if store_dir is None else store_dir
        for attempt in (1, 2):
            try:
                return cls._open(store_dir)
            except sqlite3.Error as err:
                print(f"clue index store {_store_path(store_dir)}: {err!r}; "
                      + ("rebuilding it" if attempt == 1 else "building in memory"),
                      file=sys.stderr)
                for f in store_dir.glob(_store_path(store_dir).name + "*"):
                    f.unlink(missing_ok=True)
        return _Memory(ClueIndex.build())

    @classmethod
    def _open(cls, store_dir):
        import puzzle_integrity  # noqa: PLC0415 — it imports this module
        files = puzzle_integrity.listing()
        names = puzzle_integrity.published(files)
        store_dir.mkdir(parents=True, exist_ok=True)
        path = _store_path(store_dir)
        for old in store_dir.glob("clue-keys-*.sqlite*"):
            if not old.name.startswith(path.name) and _days_old(old) > 2:
                old.unlink(missing_ok=True)
        conn = sqlite3.connect(path, timeout=600)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS rows(id INTEGER PRIMARY KEY, blob TEXT UNIQUE,"
            " pid TEXT, nkeys INTEGER);"
            "CREATE TABLE IF NOT EXISTS clues(key TEXT, id INTEGER, PRIMARY KEY(key, id)) WITHOUT ROWID;"
            "CREATE INDEX IF NOT EXISTS clues_id ON clues(id);")
        rows = {blob: (rid, pid, n) for rid, blob, pid, n in
                conn.execute("SELECT id, blob, pid, nkeys FROM rows")}
        if any(files[n] not in rows for n in names):
            with open(path.with_name(path.name + ".lock"), "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                rows = {blob: (rid, pid, n) for rid, blob, pid, n in
                        conn.execute("SELECT id, blob, pid, nkeys FROM rows")}
                root = puzzle_paths.PUZZLE_DIR.parent
                with conn:
                    for name in names:
                        if files[name] in rows:
                            continue
                        try:
                            data = (root / name).read_bytes()
                        except OSError:
                            continue
                        # A file rewritten since the listing is stored as what was read.
                        blob = files[name] = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
                        if blob in rows:
                            continue
                        pid, keys = _parse(data)
                        cur = conn.execute("INSERT INTO rows(blob, pid, nkeys) VALUES(?,?,?)",
                                           (blob, pid, -1 if keys is None else len(keys)))
                        conn.executemany("INSERT INTO clues VALUES(?,?)",
                                         ((k, cur.lastrowid) for k in keys or ()))
                        rows[blob] = (cur.lastrowid, pid, -1 if keys is None else len(keys))
                    live = {files[n] for n in names}
                    if len(rows) > 1.5 * len(live) + 1000:
                        dead = [rows.pop(b)[0] for b in list(rows) if b not in live]
                        conn.executemany("DELETE FROM clues WHERE id=?", ((r,) for r in dead))
                        conn.executemany("DELETE FROM rows WHERE id=?", ((r,) for r in dead))
        by_pid = {}
        for name in names:                # the last file of an id wins, as in build()
            if files[name] not in rows:   # gone since the listing
                continue
            rid, pid, n = rows[files[name]]
            if n >= 0:
                by_pid[pid or Path(name).stem] = (rid, n)
        return cls(conn, by_pid)

    def add(self, pid, puzzle):
        self.add_keys(pid, clue_keys(puzzle))

    def add_keys(self, pid, keys):
        self.mine[pid] = set(keys)
        if self.fallback:
            self.fallback.add_keys(pid, keys)

    def discard(self, pid):
        self.mine[pid] = None
        if self.fallback:
            self.fallback.discard(pid)

    def _size(self, pid):
        return len(self.mine[pid]) if pid in self.mine else self.by_pid[pid][1]

    def matches(self, pid, keys):
        """ClueIndex.matches, from the store."""
        if self.fallback:
            return self.fallback.matches(pid, keys)
        keys = list(keys)
        try:
            per_row = Counter()
            for i in range(0, len(keys), 500):
                part = keys[i:i + 500]
                per_row.update(dict(self.conn.execute(
                    f"SELECT id, count(*) FROM clues WHERE key IN ({','.join('?' * len(part))})"
                    " GROUP BY id", part)))
        except sqlite3.Error as err:
            print(f"clue index store: {err!r}; building in memory", file=sys.stderr)
            return self._memory().matches(pid, keys)
        hits = Counter()
        for row, shared in per_row.items():
            for other in self.of_row.get(row, ()):
                if other not in self.mine:
                    hits[other] = shared
        for other, theirs in self.mine.items():
            if theirs:
                hits[other] = sum(k in theirs for k in keys)
        out = []
        for other, shared in hits.items():
            if other == pid or not shared:
                continue
            small = min(len(keys), self._size(other))
            if (small >= MIN_CLUES and shared >= THRESHOLD * small
                    and not known_copy(pid, other)):
                out.append((other, shared, len(keys), self._size(other)))
        return sorted(out, key=lambda m: (-m[1], m[0]))

    def pairs(self):
        """ClueIndex.pairs, over every key in the store."""
        if self.fallback:
            return self.fallback.pairs()
        try:
            keys = defaultdict(set)
            for k, row in self.conn.execute("SELECT key, id FROM clues"):
                if row in self.of_row:
                    keys[row].add(k)
        except sqlite3.Error as err:
            print(f"clue index store: {err!r}; building in memory", file=sys.stderr)
            return self._memory().pairs()
        idx = ClueIndex()
        for pid, (row, _) in self.by_pid.items():
            idx.add_keys(pid, keys[row])
        self._apply(idx)
        return idx.pairs()

    def _memory(self):
        self.fallback = ClueIndex.build()
        self._apply(self.fallback)
        return self.fallback

    def _apply(self, idx):
        for pid, keys in self.mine.items():
            if keys is None:
                idx.discard(pid)
            else:
                idx.add_keys(pid, keys)


class _Memory(StoredClueIndex):
    """A StoredClueIndex that could not open its store: ClueIndex.build()."""

    def __init__(self, idx):  # no store, so no super().__init__
        self.mine, self.fallback = {}, idx


STORE_DIR = Path.home() / ".cache" / "cryptic-teacher"


def _store_path(store_dir):
    code = (inspect.getsource(norm) + inspect.getsource(clue_keys)).encode()
    return store_dir / f"clue-keys-{hashlib.sha1(code).hexdigest()[:12]}.sqlite"


def _days_old(path):
    try:
        return (time.time() - path.stat().st_mtime) / 86400
    except OSError:
        return 0


def _parse(data):
    """(id in the file or None, its clue keys) from a file's bytes — keys None
    when the file is no puzzle ClueIndex.build() would read."""
    try:
        puzzle = json.loads(data.decode("utf-8"))
        return puzzle.get("id") or None, clue_keys(puzzle)
    except (ValueError, AttributeError):
        return None, None


def _need(size):
    """The fewest shared clues that pass THRESHOLD for a puzzle of `size`."""
    need = int(THRESHOLD * size)
    return need if need >= THRESHOLD * size else need + 1

if __name__ == "__main__":
    for a, b, k, na, nb in ClueIndex.build().pairs():
        print(f"{a} {b} {k} of {na}/{nb}")
