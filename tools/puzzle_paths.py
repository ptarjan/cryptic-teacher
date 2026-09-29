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
the file with find(), a glob across that series' year folders — there is no
second table to keep in step with the tree.

Generated files are NOT here: the index and the per-puzzle .js shims the
browser loads stay flat at puzzles/index.* and puzzles/<id>.js, and the
crawlable pages at puzzles/<id>/index.html, so no public URL depends on this.

  python3 tools/puzzle_paths.py ID...   # print each held puzzle's path
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import series as series_meta  # noqa: E402

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


def puzzle_path(series, number):
    """The held file for (series, number); if none is held, where an undated one
    would go — so .exists() answers "do we hold it?". A write never trusts the
    folder of this path: write_puzzle_file places the file by file_for()."""
    pid = series_meta.puzzle_id(series, number)
    return find(pid) or PUZZLE_DIR / series_folder(pid) / UNDATED / f"{pid}.json"


def puzzle_files():
    """Every published puzzle file: <series>-<number>.json one level under a
    year folder. Not generated output."""
    return sorted(PUZZLE_DIR.glob("*/*/*-[0-9]*.json"))


def resolve_puzzle(arg):
    """A puzzle file from either a namespaced id ("everyman-4165") or the bare
    number a person types ("4165").

    A bare number resolves only while it names exactly one puzzle; an ambiguous
    one is an error naming the candidates, never a guess — guessing would
    annotate one paper's grid from another paper's clues.
    """
    arg = str(arg)
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


def in_corpus(path):
    """Is `path` a puzzle file under PUZZLE_DIR (so placed by file_for), rather
    than a fixture or an out-dir copy written wherever its caller says?"""
    try:
        Path(path).resolve().relative_to(PUZZLE_DIR.resolve())
    except ValueError:
        return False
    return True


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
    for a in sys.argv[1:]:
        hit = resolve_puzzle(a)
        print(hit.relative_to(ROOT) if hit.is_relative_to(ROOT) else hit)
