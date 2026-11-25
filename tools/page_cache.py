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
    inputs below, LINKED_ONLY and tools/*.py, whose file name is a string
    constant in a reached definition (indicators.json ...), by its git
    blob sha, a dirty or untracked one by its content. A file only a comment
    or docstring mentions is not read. A name built at run time would be
    missed; the reached code builds only per-page ones (a puzzle's own file,
    its blog facts, its card), which page_key covers;
  - the page's own inputs, which build_seo_pages.page_key() lists: its
    puzzle file's git blob id (blob_id()), the hash of the puzzle as the solver's view of it
    gives it (the index row's "pageView": the solver's code is not in the
    build-wide key, only what it made of this puzzle, so a solver commit
    re-renders the pages whose view it changed), its blog-facts sidecar's
    blob id, the part of its index row
    the page prints (build_seo_pages.page_row()), its pager
    neighbours and whether its card is on disk;
  - every stamped asset URL the render asked for (asset(): the card's ?v=,
    the stylesheet's), recomputed and compared before reuse;
  - the file on disk, whose hash must be the one the render wrote. A cold
    cache, a hand-edited page or another tree's page is rendered again.

Three data files the reached code names are not in the build-wide key, because
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
  - setter_error.json (PER_PUZZLE): keyed "puzzle id/entry id", so a page's
    key holds its own puzzle's rows, and a "Annotate <id>" burn commit that
    files one re-renders that puzzle's page alone;
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
VERSION = "6"

PUZZLE_FILE = re.compile(r"puzzles/[^/]+/[0-9]{4}/[^/]+\.json")
#: A puzzle's blog-facts sidecar, beside its file: a per-page input like it.
BLOG_SIDECAR = re.compile(r"puzzles/[^/]+/[0-9]{4}/[^/]+\.blog")
# Per-page inputs (keyed in page_key) or not inputs to a puzzle page at all.
# index.html is restamped by every reindex, and no puzzle page reads it.
NOT_GLOBAL = ("docs/", "tools/data/blog_facts/")
#: Data the stored entry itself is checked against (see the docstring).
PER_ENTRY = {"tools/data/lexicons/indicators.json"}
#: A table keyed "puzzle id/entry id": wordplay.slipped_run reads it, but a
#: page's key holds its own puzzle's rows (build_seo_pages.setter_rows), so a
#: row filed for another puzzle (a burn commit, ~10 a day) re-renders nothing.
PER_PUZZLE = {"tools/data/setter_error.json"}
NOT_GLOBAL_FILES = {"index.html"} | PER_ENTRY | PER_PUZZLE
#: Where a puzzle page's code starts, in build_seo_pages: what outputs() runs
#: per page in its workers, and the list and pager those pages are made from.
ROOTS = ("puzzle_page_job", "page_key", "puzzles", "series_neighbours")
#: Definitions whose output a stored page is checked against before reuse,
#: so neither their code nor the data they read is in the build-wide key.
OPAQUE = ("stamp_assets.asset_url", "annotation.abbreviation_pairs",
          # The solver: a page is made from what it printed of these, whose
          # output the index row hashes (fetch_puzzle.index_row's "pageView",
          # build_seo_pages.page_key), so a solver commit moves the hash of the
          # puzzles it changed and no other page's key. annotation.whole_answer
          # and whole_anagram are called by the page itself and stay code.
          "fetch_puzzle.read_puzzle_view", "fetch_puzzle.with_blog_facts", "annotation.view_puzzle",
          # Matched again, not rendered again, when its code moves (the stored
          # lexicon hash, build_seo_pages.indicator_lexicon_hash).
          "indicator_keys.clue_pairs",
          # The row machinery behind puzzles(): its code moves rows, not pages.
          "row_cache.cached_map", "puzzle_integrity", "budget", "unit_more")
#: A file name (the last part of a path) in a string constant, as ast.dump
#: writes one in code_reach's hashed form.
NAMED = re.compile(r"Constant\(value='(?:[^'\\]*/)?([\w.\-]+\.(?:json|tsv|txt|md|csv|yaml|yml|html|js|"
                   r"css|webmanifest|svg|png|ico|xml))'")
#: Data files read only through a parser that keeps part of them: the page is
#: made from that part, so it (not the file's bytes) is in the key. An edit to
#: app.js's comments or its browser code leaves every page reusable.
DERIVED = {"app.js"}
TOOLS_PY = re.compile(r"tools/[^/]+\.py")
#: Files a puzzle page only links, by a stamped URL (build_seo_pages.asset()):
#: the page is made from the URL, which each stored entry records and
#: build_seo_pages.reuse_page() compares and rewrites, never from the file's
#: bytes. So they are not in the build-wide key: a stylesheet edit re-stamps
#: the stored pages in place instead of rendering all of them again.
LINKED_ONLY = {"style.css", "reader.js", "analytics.js", "appnav.js", "landing.js", "og.png",
               "favicon.svg", "favicon.ico", "apple-touch-icon.png"}


def _per_page(path):
    return bool(PUZZLE_FILE.fullmatch(path) or BLOG_SIDECAR.fullmatch(path) or path.startswith(NOT_GLOBAL)
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
                  and p not in DERIVED and not _per_page(p) and not TOOLS_PY.fullmatch(p)
                  and p not in LINKED_ONLY)


def derived(code):
    """[(name, value)] for the DERIVED files the reached `code` names: what
    app_tables parses out of app.js, or the file's bytes if it does not parse."""
    names = {m for v in code.values() for m in NAMED.findall(v)}
    if not names & DERIVED:
        return []
    import app_tables
    try:
        src = app_tables.source()
        return [("app.js", repr((app_tables.ladder(src), app_tables.series_blurbs(src))))]
    except (OSError, SystemExit):
        try:
            return [("app.js", hashlib.sha256(app_tables.source().encode()).hexdigest())]
        except OSError:
            return [("app.js", "gone")]


#: {ROOT-relative path: git blob id} of every tracked file git's own stat check
#: (`ls-files -m`) calls unmodified, from fingerprint()'s listing: blob_id()
#: answers from it without reading the file. Filled before the workers fork.
_CLEAN = {}


def blob_id(path):
    """The git blob id of the bytes at `path`, None when there is no file.

    A tracked file git calls unmodified gives its index entry's id, which git
    keeps equal to the work-tree bytes (its stat check re-reads a file whose
    stat moved, or one written in the second the index was); anything else
    (dirty, untracked, outside ROOT, before a fingerprint()) is read and hashed
    as git hashes a blob, so the same bytes give the same id either way."""
    rel = puzzle_paths.relative(path, ROOT)
    if rel in _CLEAN:
        return _CLEAN[rel]
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return None
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


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
    _CLEAN.clear()
    _CLEAN.update((p, b) for p, b in blobs.items() if b)
    h = hashlib.sha256(f"page-cache {VERSION}\0".encode())
    for k, v in sorted(code.items()):
        h.update(f"{k}\0{v}\0".encode("utf-8", "surrogateescape"))
    for path in inputs(code, blobs):
        blob = blobs[path]
        if blob is None:  # dirty or untracked: its bytes
            p = ROOT / path
            blob = hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else "gone"
        h.update(f"{path}\0{blob}\0".encode("utf-8", "surrogateescape"))
    for name, value in derived(code):
        h.update(f"{name}\0{value}\0".encode("utf-8", "surrogateescape"))
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


def may_skip_save(rendered, fp, env=os.environ):
    """Whether the store on disk, the one this run restored, may stand in for
    this run's: the deploy's fast path leaves it unwritten (~11s of the page
    step) when the workflow will not pack it either.

    pages.yml's Save the puzzle pages runs after more than PAGE_STORE_SKIP_UP_TO
    pages were rendered, or when the restored store was saved under another
    page fingerprint. Only when neither holds is the pack skipped, and so only
    then is the pickle written for nothing: the next run renders the few pages
    this one did, as a store that is a few runs stale always has. PAGE_STORE_MATCHED
    is the matched cache key; unset (a local build, the full path), the store is
    always written."""
    matched, limit = env.get("PAGE_STORE_MATCHED", ""), env.get("PAGE_STORE_SKIP_UP_TO", "")
    if not (matched and fp and limit.isdigit()):
        return False
    return rendered <= int(limit) and fp in matched


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
