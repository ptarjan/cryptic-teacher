"""Blog facts, stored per puzzle beside the puzzle: puzzles/<series>/<year>/<id>.blog.

One file a puzzle (about 5 KB of JSON: {"blog", "name", "url", "entries"}),
not one 20 MB file a series, so the nightly rewrites only the puzzles whose
facts moved and a push carries only those. The suffix is `.blog`, not
`.blog.json`, on purpose: every glob over puzzles/ (`*-[0-9]*.json`, the
folder listing, the schema walk, the site build) asks for `.json`, and a
sidecar ending in it would be read as a puzzle. tools/ci_scope.py treats a
changed sidecar as puzzle data (the fast path) and re-checks its puzzle.

tools/data/blog_facts/ keeps only inputs.sha256 (see blog_facts.STAMP).
"""
import hashlib
import json
import os
from pathlib import Path

import puzzle_paths

SUFFIX = ".blog"
ROOT = Path(__file__).resolve().parent.parent
#: What is left of the old tools/data/blog_facts/ files: the inputs digest.
STAMP_DIR = ROOT / "tools" / "data" / "blog_facts"


def body_of_line(line):
    """The JSON object of a `"<id>": {...}` line (blog_facts.row_line), as the file holds it."""
    return line[line.index('": ') + 3:].rstrip(",\n") + "\n"


def encode(row):
    from puzzle_schema import order  # the schema's key order, so a file is the same bytes whoever writes it
    return json.dumps(order({**row, "entries": dict(sorted(row["entries"].items()))}, "#/$defs/blogFacts"),
                      ensure_ascii=False) + "\n"


def sidecar_of(puzzle_file):
    return Path(puzzle_file).with_suffix(SUFFIX)


def files(series=None):
    """{puzzle id: sidecar Path} of every sidecar (of one series folder), in id order."""
    root = puzzle_paths.PUZZLE_DIR
    out = {}
    try:
        folders = [root / series] if series else sorted(Path(e.path) for e in os.scandir(root) if e.is_dir())
        for folder in folders:
            for year in os.scandir(folder):
                if year.is_dir():
                    for e in os.scandir(year.path):
                        if e.name.endswith(SUFFIX):
                            out[e.name[:-len(SUFFIX)]] = Path(e.path)
    except (FileNotFoundError, NotADirectoryError):
        pass
    return dict(sorted(out.items()))


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rows(series=None):
    """(puzzle id, row) of every sidecar (of one series folder), in id order."""
    for pid, path in files(series).items():
        yield pid, read(path)


def row_for(puzzle):
    """This puzzle's row, or None: the sidecar beside its file."""
    try:
        path = sidecar_of(puzzle_paths.file_for(puzzle))
        return json.loads(path.read_bytes())
    except (FileNotFoundError, KeyError, ValueError):
        return None


def row_of_id(pid):
    """Row of puzzle id `pid` (wherever it is filed), or None."""
    found = puzzle_paths.find(pid)
    if found is None:
        return None
    try:
        return json.loads(sidecar_of(found).read_bytes())
    except FileNotFoundError:
        return None


def hashes():
    """{puzzle id: a hash of its sidecar's bytes}: what a row read off a puzzle's
    blog facts depends on (tools/row_cache.py), found without parsing them."""
    out = {}
    for pid, path in files().items():
        out[pid] = hashlib.sha1(path.read_bytes()).hexdigest()[:16]
    return out


def put(path, text):
    """Write `text` to the sidecar `path` unless it already holds those bytes; 1 if written."""
    data = text.encode("utf-8")
    try:
        if Path(path).read_bytes() == data:
            return 0
    except FileNotFoundError:
        pass
    tmp = Path(path).with_name(Path(path).name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return 1


def sync(bodies, only_series=None):
    """Make the sidecars `bodies`, an iterable of (puzzle id, file text): write those whose bytes
    differ, delete the rest (a puzzle that lost its facts). `only_series` limits
    deletion to those series folders. Returns (written, deleted, unfiled)."""
    listing, written, unfiled = {}, 0, 0
    keep = set()
    for pid, text in bodies:
        folder = puzzle_paths.series_folder(pid)
        if folder not in listing:
            listing[folder] = puzzle_paths.folder_listing(folder)
        pf = listing[folder].get(pid)
        if pf is None:
            unfiled += 1
            continue
        path = sidecar_of(pf)
        keep.add(path)
        written += put(path, text)
    deleted = 0
    for folder in ([only_series] if only_series else [p.name for p in puzzle_paths.PUZZLE_DIR.iterdir() if p.is_dir()]):
        for path in files(folder).values():
            if path not in keep:
                path.unlink()
                deleted += 1
    return written, deleted, unfiled
