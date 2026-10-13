"""The puzzle pages a previous build wrote, reused when nothing they are made
from has moved.

build_seo_pages.py renders one page per puzzle: tens of thousands of them,
two minutes of the deploy's four cores, on a push that changed one puzzle
file. The deploy restores last run's puzzles/<id>/index.html files and this
store from an actions/cache, and a page is re-rendered only when its key or
its checks say so. A page is reused when all of these are what they were:

  - the build's code and data: every tracked file outside the puzzle files
    (puzzles/<series>/<year>/<id>.json), docs/, the blog-facts sidecars and
    index.html, by its git blob sha, a dirty or untracked one by its content
    (fingerprint()). Any edit to tools/, app.js, style.css or a data table
    re-renders every page, which is the full build the deploy ran before;
  - the page's own inputs, which build_seo_pages.page_key() lists: its
    puzzle file's bytes, its blog-facts lines, its index row, its pager
    neighbours and whether its card is on disk;
  - every stamped asset URL the render asked for (asset(): the card's ?v=,
    the stylesheet's), recomputed and compared before reuse;
  - the file on disk, whose hash must be the one the render wrote. A cold
    cache, a hand-edited page or another tree's page is rendered again.

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
VERSION = "1"

PUZZLE_FILE = re.compile(r"puzzles/[^/]+/[0-9]{4}/[^/]+\.json")
# Per-page inputs (keyed in page_key) or not inputs to a puzzle page at all.
# index.html is restamped by every reindex, and no puzzle page reads it.
NOT_GLOBAL = ("docs/", "tools/data/blog_facts/")
NOT_GLOBAL_FILES = {"index.html"}


def _global(path):
    return not (PUZZLE_FILE.fullmatch(path) or path.startswith(NOT_GLOBAL)
                or path in NOT_GLOBAL_FILES)


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          check=True).stdout.decode("utf-8", "surrogateescape")


def fingerprint():
    """A hash of every file a puzzle page can read through code or data that
    is not one of its own per-page inputs. None outside a git checkout, which
    turns the store off."""
    try:
        listed = _git("ls-files", "-s", "-z")
        changed = set(_git("ls-files", "-m", "-z").split("\0"))
        new = _git("ls-files", "-o", "--exclude-standard", "-z", "--", "tools").split("\0")
    except (OSError, subprocess.CalledProcessError) as err:
        print(f"page cache: {err!r}; rendering every page", file=sys.stderr)
        return None
    h = hashlib.sha256(f"page-cache {VERSION}\0".encode())
    for line in listed.split("\0"):
        if not line:
            continue
        meta, path = line.split("\t", 1)
        if not _global(path):
            continue
        if path in changed:
            p = ROOT / path
            blob = hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else "gone"
        else:
            blob = meta.split()[1]
        h.update(f"{path}\0{blob}\0".encode("utf-8", "surrogateescape"))
    for path in sorted(p for p in new if p and _global(p)):
        h.update(f"{path}\0{hashlib.sha1((ROOT / path).read_bytes()).hexdigest()}\0"
                 .encode("utf-8", "surrogateescape"))
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
