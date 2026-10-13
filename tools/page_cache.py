"""The puzzle pages a previous build wrote, reused when nothing they are made
from has moved.

build_seo_pages.py renders one page per puzzle: tens of thousands of them,
two minutes of the deploy's four cores, on a push that changed one puzzle
file. The deploy restores last run's puzzles/<id>/index.html files and this
store from an actions/cache, and a page is re-rendered only when its key or
its checks say so. A page is reused when all of these are what they were:

  - the code a puzzle page runs: every definition tools/code_reach.py says
    build_seo_pages' puzzle-page path (ROOTS) reaches, by its syntax tree
    without docstrings. An edit to a fetcher, a test, the hub page's code or
    a comment leaves every page reusable; an edit to anything a puzzle page
    runs re-renders them all;
  - the data that code names: every tracked file, outside the per-page
    inputs below and tools/*.py, whose file name is a string constant in a
    reached definition (indicators.json, style.css, og.png ...), by its git
    blob sha, a dirty or untracked one by its content. A file only a comment
    or docstring mentions is not read. A name built at run time would be
    missed; the reached code builds only per-page ones (a puzzle's own file,
    its blog facts, its card), which page_key covers;
  - the page's own inputs, which build_seo_pages.page_key() lists: its
    puzzle file's bytes, its blog-facts lines, the part of its index row
    the page prints (build_seo_pages.page_row()), its pager
    neighbours and whether its card is on disk;
  - every stamped asset URL the render asked for (asset(): the card's ?v=,
    the stylesheet's), recomputed and compared before reuse;
  - the file on disk, whose hash must be the one the render wrote. A cold
    cache, a hand-edited page or another tree's page is rendered again.

Two data files the reached code names are not in the build-wide key, because
a page's own check already covers them and both move with every "daily
blog-facts" commit (every few hours), which re-rendered all ~42k pages each
time for the few hundred whose text moved:
  - blocks.json and whatever else only stamp_assets.asset_url() reads to
    hash an asset (OPAQUE): every URL it gave is recomputed and compared
    before a page is reused, so a moved asset re-renders exactly the pages
    that link it; likewise abbreviations.json and blocks.json, which only
    annotation.abbreviation_pairs() reads (the table view() glosses a leaf
    from): each (clue word, letters) pair a render looked up is stored with
    its answer and looked up again before reuse;
  - indicators.json (PER_ENTRY): a page's HTML does not read it; only the
    /indicators/ candidates matched against it do, and a stored page keeps
    its candidates unmatched with the lexicon's hash, so a moved lexicon
    re-matches them (build_seo_pages.indicator_found) without a render.

A stale or missing store is never wrong, only slow. Each run rewrites the
store with exactly this run's pages, so it does not grow.
"""
import hashlib
import os
import pickle
import re
import subprocess
import sys
from pathlib import Path

import puzzle_paths

ROOT = puzzle_paths.ROOT
#: The store; gitignored, carried between deploys by the workflow's cache.
STORE = ROOT / ".page-cache.pickle"
#: Bump to drop every stored page (a change to how keys are made).
VERSION = "4"

PUZZLE_FILE = re.compile(r"puzzles/[^/]+/[0-9]{4}/[^/]+\.json")
# Per-page inputs (keyed in page_key) or not inputs to a puzzle page at all.
# index.html is restamped by every reindex, and no puzzle page reads it.
NOT_GLOBAL = ("docs/", "tools/data/blog_facts/")
#: Data the stored entry itself is checked against (see the docstring).
PER_ENTRY = {"tools/data/lexicons/indicators.json"}
NOT_GLOBAL_FILES = {"index.html"} | PER_ENTRY
#: Where a puzzle page's code starts, in build_seo_pages: what outputs() runs
#: per page in its workers, and the list and pager those pages are made from.
ROOTS = ("puzzle_page_job", "page_key", "puzzles", "series_neighbours")
#: Definitions whose output a stored page is checked against before reuse,
#: so neither their code nor the data they read is in the build-wide key.
OPAQUE = ("stamp_assets.asset_url", "annotation.abbreviation_pairs")
#: A file name (the last part of a path) in a string constant, as ast.dump
#: writes one in code_reach's hashed form.
NAMED = re.compile(r"Constant\(value='(?:[^'\\]*/)?([\w.\-]+\.(?:json|tsv|txt|md|csv|yaml|yml|html|js|"
                   r"css|webmanifest|svg|png|ico|xml))'")
TOOLS_PY = re.compile(r"tools/[^/]+\.py")


def _per_page(path):
    return bool(PUZZLE_FILE.fullmatch(path) or path.startswith(NOT_GLOBAL)
                or path in NOT_GLOBAL_FILES)


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          check=True).stdout.decode("utf-8", "surrogateescape")


def reached(texts=None):
    """{(module, definition): hashed form} for the puzzle-page code; `texts`
    ({module: source}) stands in for tools/ files (tests)."""
    import code_reach  # here: build_seo_pages' workers never need it
    return code_reach.reach("build_seo_pages", list(ROOTS), texts,
                            opaque=code_reach.TRANSPORT + OPAQUE)


def inputs(code, paths):
    """The paths (tracked or new files) that are a puzzle page's global data:
    named by a string constant of the reached `code`, not a tools/ module
    (the code itself is hashed by definition) and not a per-page input."""
    names = {m for v in code.values() for m in NAMED.findall(v)}
    return sorted(p for p in paths if p.rsplit("/", 1)[-1] in names
                  and not _per_page(p) and not TOOLS_PY.fullmatch(p))


def fingerprint(texts=None):
    """A hash of the code a puzzle page runs and of the data files that code
    names. None outside a git checkout, which turns the store off."""
    try:
        listed = _git("ls-files", "-s", "-z")
        changed = set(_git("ls-files", "-m", "-z").split("\0"))
        new = _git("ls-files", "-o", "--exclude-standard", "-z", "--", "tools").split("\0")
        code = reached(texts)
    except (OSError, subprocess.CalledProcessError, SyntaxError) as err:
        print(f"page cache: {err!r}; rendering every page", file=sys.stderr)
        return None
    blobs = {}
    for line in listed.split("\0"):
        if line:
            meta, path = line.split("\t", 1)
            blobs[path] = None if path in changed else meta.split()[1]
    blobs.update((p, None) for p in new if p)
    h = hashlib.sha256(f"page-cache {VERSION}\0".encode())
    for k, v in sorted(code.items()):
        h.update(f"{k}\0{v}\0".encode("utf-8", "surrogateescape"))
    for path in inputs(code, blobs):
        blob = blobs[path]
        if blob is None:  # dirty or untracked: its bytes
            p = ROOT / path
            blob = hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else "gone"
        h.update(f"{path}\0{blob}\0".encode("utf-8", "surrogateescape"))
    return h.hexdigest()


def load():
    """{key: entry} from the last run, or {} when there is none to read."""
    try:
        with open(STORE, "rb") as f:
            return pickle.load(f)
    except FileNotFoundError:
        return {}
    except Exception as err:  # a torn or foreign file is a cold cache
        print(f"page cache: unreadable {STORE.name} ({err!r}); rendering every page",
              file=sys.stderr)
        return {}


def save(entries):
    tmp = STORE.with_suffix(f".{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(entries, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, STORE)


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
