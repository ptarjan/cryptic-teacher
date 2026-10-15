#!/usr/bin/env python3
"""Where a puzzle's file lives: puzzles/<series>/<year>/<id>.json.

The one place the corpus layout is spelled. Everything that reads or writes a
puzzle file asks here; tools/puzzle_paths.js is the same rule for node.

  series  from the id (series.parse_id), so an id alone narrows the search to
          one folder.
  year    series.puzzle_year(): the year of the puzzle's `date`, or a book
          puzzle's `year` — the year build_seo_pages.py prints. A puzzle with
          neither (a datedFromNeighbours series whose neighbours are not held
          yet) goes in `undated`, and moves out when a write gives it a date.

The year is a fact about the contents, so a file can only be placed by
something that has the puzzle: file_for(). Something holding only an id finds
the file with find(), a stat in each of that series' year folders — there is no
second table to keep in step with the tree.

Generated files are NOT here: the index and the per-puzzle .js shims the
browser loads stay flat at puzzles/index.* and puzzles/<id>.js, and the
crawlable pages at puzzles/<id>/index.html, so no public URL depends on this.

  python3 tools/puzzle_paths.py ID...   # print each held puzzle's path
"""
import functools
import os
import sys
import threading
from pathlib import Path

import series as series_meta

ROOT = Path(__file__).resolve().parent.parent
# Reassignable: the tests point it at a scratch tree, and every function here
# reads it at call time.
PUZZLE_DIR = ROOT / "puzzles"
UNDATED = "undated"


def year_folder(puzzle):
    """The folder a puzzle files under: its year, or UNDATED."""
    year = series_meta.puzzle_year(puzzle)
    return UNDATED if year is None else str(year)


def series_folder(pid):
    """The series folder for an id, or a SystemExit naming an id with none."""
    series, _ = series_meta.parse_id(str(pid))
    if not series:
        raise SystemExit(f"{pid} is not a namespaced puzzle id (<series>-<number>)")
    return series


def file_for(puzzle):
    """THE path function: where this puzzle's file belongs."""
    pid = puzzle["id"]
    return PUZZLE_DIR / series_folder(pid) / year_folder(puzzle) / f"{pid}.json"


def find(pid):
    """The file holding puzzle `pid`, or None if it is not held."""
    folder = PUZZLE_DIR / series_folder(pid)
    # A stat per year folder: a glob would list every file in every one.
    hits = sorted(p for d in folder.iterdir() if (p := d / f"{pid}.json").is_file()) if folder.is_dir() else []
    if len(hits) > 1:
        raise SystemExit(f"{pid} is filed twice: " + ", ".join(map(str, hits)))
    return hits[0] if hits else None


#: {series: (stamp, {id: path or None})}: folder_listing's last listing.
_LISTED = {}


#: This thread's {series: listing} while inside listed_once(), else None.
_ONCE = threading.local()


class listed_once:
    """Within it (this thread), folder_listing lists each series once: a plan
    asks find_listed for thousands of ids, and each ask was a scandir and a
    stat of every year folder to see whether the listing stood. A puzzle filed
    meanwhile is seen by the next scope, as held_files' held_once does."""

    def __enter__(self):
        self.outer = getattr(_ONCE, "seen", None) is not None
        if not self.outer:
            _ONCE.seen = {}

    def __exit__(self, *exc):
        if not self.outer:
            _ONCE.seen = None


def folder_listing(series):
    """{id: its file} of every file under a series' year folders (None for an
    id filed twice: find raises), listed again only when a year folder's
    mtime moved (a file written by os.replace, filed or removed moves its
    folder's). Callers asking after a few ids of a series each plan (find
    is a stat per year folder per id) read one stat per folder instead."""
    once = getattr(_ONCE, "seen", None)
    if once is not None and series in once:
        return once[series]
    out = _folder_listing(series)
    if once is not None:
        once[series] = out
    return out


def _folder_listing(series):
    root = PUZZLE_DIR / series
    try:
        folders = sorted((e.path, e.stat().st_mtime_ns) for e in os.scandir(root) if e.is_dir())
    except (FileNotFoundError, NotADirectoryError):
        return {}
    stamp = (str(root), tuple(folders))
    hit = _LISTED.get(series)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    out = {}
    for path, _ in folders:
        for e in os.scandir(path):
            if e.name.endswith(".json") and e.is_file():
                out[e.name[:-5]] = None if e.name[:-5] in out else Path(e.path)
    _LISTED[series] = (stamp, out)
    return out


def find_listed(pid):
    """find(pid) off folder_listing."""
    got = folder_listing(series_folder(pid)).get(str(pid))
    return got or (find(pid) if str(pid) in folder_listing(series_folder(pid)) else None)


def find_many(pids):
    """{pid: find(pid)} for each of `pids` held, off one puzzle_files()
    listing: a find per puzzle is a stat per year folder, and the nightly
    reports looked up thousands. An id the listing misses is found as find()
    finds it."""
    by_name = {}
    for p in puzzle_files():
        by_name.setdefault(p.stem, []).append(p)
    out = {}
    for pid in pids:
        hits = sorted(p for p in by_name.get(pid, ()) if p.parent.parent == PUZZLE_DIR / series_folder(pid))
        if len(hits) > 1:
            raise SystemExit(f"{pid} is filed twice: " + ", ".join(map(str, hits)))
        path = hits[0] if hits else find(pid)
        if path is not None:
            out[pid] = path
    return out


def puzzle_path(series, number):
    """The held file for (series, number); if none is held, where an undated one
    would go — so .exists() answers "do we hold it?". A write never trusts the
    folder of this path: write_puzzle_file places the file by file_for()."""
    pid = series_meta.puzzle_id(series, number)
    return find(pid) or PUZZLE_DIR / series_folder(pid) / UNDATED / f"{pid}.json"


def puzzle_files(*series):
    """Every published puzzle file: <series>-<number>.json one level under a
    year folder. Not generated output. Name series to get only theirs, picked
    by file name: a nightly refresh that opened all 54k files to keep a few
    dozen ran past its hour on a loaded host."""
    if series:
        return sorted(f for s in series for f in PUZZLE_DIR.glob(f"*/*/{s}-[0-9]*.json"))
    return sorted(PUZZLE_DIR.glob("*/*/*-[0-9]*.json"))


def resolve_puzzle(arg):
    """A puzzle file from either a namespaced id ("everyman-4165") or the bare
    number a person types ("4165").

    A bare number resolves only while it names exactly one puzzle; an ambiguous
    one is an error naming the candidates, never a guess — guessing would
    annotate one paper's grid from another paper's clues. A path to a .json
    file is that file.
    """
    arg = str(arg)
    if arg.endswith(".json"):
        if Path(arg).is_file():
            return Path(arg)
        raise SystemExit(f"no puzzle file {arg}")
    series, _ = series_meta.parse_id(arg)
    if series:
        hit = find(arg)
        if hit:
            return hit
        raise SystemExit(f"no puzzle {arg} in {PUZZLE_DIR}")
    hits = sorted(PUZZLE_DIR.glob(f"*/*/*-{arg}.json"))
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"no puzzle {arg} in {PUZZLE_DIR}")
    raise SystemExit(f"{arg} names more than one puzzle — say which: "
                     + ", ".join(p.stem for p in hits))


@functools.cache
def _real_dir(folder):
    return os.path.realpath(folder)


def real(path):
    """str(Path(path).resolve()), with each folder resolved once per process.

    A whole-corpus pass names 45k files in a few hundred folders, and
    resolve() walks every component of every one: most of a reindex's CPU
    when the rows themselves come off tools/row_cache.py. The file's own
    name is resolved only when it is itself a link."""
    s = os.fspath(path)
    folder, name = os.path.split(s)
    if not os.path.isabs(s) or name in ("", ".", "..") or os.path.islink(s):
        return os.path.realpath(s)
    return os.path.join(_real_dir(folder), name)


def relative(path, root):
    """Path(path).resolve().relative_to(root).as_posix(), or None where the
    file is not under `root` (taken as given, as relative_to takes it)."""
    r, prefix = real(path), os.path.join(os.fspath(root), "")
    if r + os.sep == prefix:
        return "."
    return r[len(prefix):] if r.startswith(prefix) else None


def in_corpus(path):
    """Is `path` a puzzle file under PUZZLE_DIR (so placed by file_for), rather
    than a fixture or an out-dir copy written wherever its caller says?"""
    return relative(path, _real_dir(os.fspath(PUZZLE_DIR))) is not None


def shim_path(path):
    """The generated script the browser loads for a puzzle file. Flat at
    puzzles/<id>.js for the corpus, so its URL is independent of the layout;
    beside the file for anything outside it."""
    path = Path(path)
    if in_corpus(path):
        return PUZZLE_DIR / f"{path.stem}.js"
    return path.with_suffix(".js")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    import clues_only
    for a in sys.argv[1:]:
        # A puzzle held as its clues alone is held too: the solve loops ask
        # here for the file to hand the solver.
        hit = ("-" in a and not find(a) and clues_only.find(a)) or resolve_puzzle(a)
        print(hit.relative_to(ROOT) if hit.is_relative_to(ROOT) else hit)
