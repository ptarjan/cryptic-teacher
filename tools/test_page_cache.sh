#!/usr/bin/env bash
# The deploy reuses last build's puzzle pages (tools/page_cache.py) unless
# something a puzzle page is made from moved. The build-wide part of that key
# is the code build_seo_pages' puzzle-page path reaches (tools/code_reach.py)
# plus the data files that code names: a fetcher, a test, the hub page's code,
# a comment or the budgets table leaves every page reusable; an edit to the
# page's code or to a table it reads re-renders them all.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'EOF'
import sys
sys.path.insert(0, "tools")
import page_cache as pc

src = open("tools/build_seo_pages.py", encoding="utf-8").read()
real_git = pc._git
base = pc.fingerprint()
assert base, "test_page_cache: no fingerprint in a checkout"

def fp(texts=None, blob_of=None):
    """The fingerprint with `texts` standing in for tools/ modules and
    `blob_of` ({path: sha}) for the index's blob of those files."""
    def git(*args):
        out = real_git(*args)
        if blob_of and args[:2] == ("ls-files", "-s"):
            lines = []
            for line in out.split("\0"):
                if line and line.split("\t", 1)[1] in blob_of:
                    meta, path = line.split("\t", 1)
                    mode, _, stage = meta.split()
                    line = f"{mode} {blob_of[path]} {stage}\t{path}"
                lines.append(line)
            out = "\0".join(lines)
        return out
    pc._git = git
    try:
        return pc.fingerprint(texts)
    finally:
        pc._git = real_git

def same(label, got):
    if got != base:
        sys.exit(f"test_page_cache: {label}: re-renders every page, should reuse them")

def moved(label, got):
    if got is None or got == base:
        sys.exit(f"test_page_cache: {label}: reuses stale pages")

def edit(old, new):
    assert src.count(old) == 1, f"test_page_cache: {old!r} is not in build_seo_pages.py once"
    return {"build_seo_pages": src.replace(old, new)}

same("the same tree twice", pc.fingerprint())
same("a comment", fp({"build_seo_pages": src + "\n# a comment\n"}))
same("the hub page's code", fp(edit("def hub_page(idx):", "def hub_page(idx, unused=None):")))
same("a fetcher nothing reaches", fp({"fetch_telegraph": "def nothing():\n    return 1\n"}))
moved("the puzzle page's code", fp(edit("def puzzle_page(puz, meta, prev_p, next_p):", "def puzzle_page(puz, meta, prev_p, next_p, unused=None):")))
Z = "0" * 40
moved("a table the page reads", fp(blob_of={"tools/data/lexicons/indicators.json": Z}))
moved("the stylesheet", fp(blob_of={"style.css": Z}))
same("the budgets table, a test, a doc", fp(blob_of={"tools/data/deploy_budgets.json": Z,
                                                      "tools/test_validate_scope.sh": Z, "APP.md": Z}))
same("the homepage, restamped by every reindex", fp(blob_of={"index.html": Z}))

code = pc.reached()
paths = ["tools/data/lexicons/indicators.json", "style.css", "index.html", "docs/indicators.json",
         "puzzles/times/2002/times-21965.json", "tools/data/blog_facts/times.json", "tools/fetch_puzzle.py",
         "tools/data/deploy_budgets.json"]
got = pc.inputs(code, paths)
assert got == ["style.css", "tools/data/lexicons/indicators.json"], f"test_page_cache: inputs {got}"

# A page's key holds the part of its index row the page prints (page_row),
# so a reindex that moves only the difficulty index, its basis, the tags or
# the file stamp reuses every page; a moved percentile, band, annotation or
# listing year re-renders it. puzzle_page() reads the row only through
# page_row(), and the reused page's showcase facts take the row's fresh.
import copy
import build_seo_pages as B
import showcase
from pathlib import Path

row = {"id": "cryptic-30000", "number": 30000, "series": "cryptic", "date": "2026-05-01",
       "file": "cryptic-30000.js", "v": "aaaa", "annotated": True, "tags": [],
       "difficulty": {"band": "Moderate", "index": -0.148, "percentile": 32, "basis": ["rarity"]}}
puz = {"id": "cryptic-30000", "number": 30000, "series": "cryptic", "date": "2026-05-01",
       "setter": "Pan", "dimensions": {"cols": 15, "rows": 15}, "entries": []}
pf = Path("tools/test_page_cache.sh")

def key(r):
    B._PAGES = [(pf, {"id": row["id"], "series": "cryptic"})], [(None, None)], {row["id"]: r}, True, "fp", {}
    try:
        return B.page_key(0)
    finally:
        B._PAGES = None

def changed(**edits):
    r = copy.deepcopy(row)
    for k, v in edits.items():
        if k in ("index", "basis", "band", "percentile"):
            r["difficulty"][k] = v
        else:
            r[k] = v
    return r

k0, page0 = key(row), B.puzzle_page(puz, row, None, None)
for label, r in (("the difficulty index", changed(index=0.5)), ("the basis", changed(basis=["device"])),
                 ("the tags", changed(tags=["big-grid"])), ("the file stamp", changed(v="bbbb"))):
    if key(r) != k0:
        sys.exit(f"test_page_cache: {label} moved: re-renders a page that does not print it")
    if B.puzzle_page(puz, r, None, None) != page0:
        sys.exit(f"test_page_cache: {label} moved the page but not its key: reuses a stale page")
for label, r in (("the percentile", changed(percentile=33)), ("the band", changed(band="Hard")),
                 ("the annotation", changed(annotated=False)), ("the date", changed(date="2025-05-01")),
                 ("the row", None)):
    if key(r) == k0:
        sys.exit(f"test_page_cache: {label} moved: reuses a stale page")
    if B.puzzle_page(puz, r, None, None) == page0:
        sys.exit(f"test_page_cache: {label} is keyed but the page does not print it")
fresh = changed(index=0.5, tags=["big-grid"])
if showcase.with_meta(showcase.file_facts(puz), fresh) != showcase.facts(puz, fresh):
    sys.exit("test_page_cache: a reused page's showcase facts are not the fresh row's")
print("test_page_cache: all passed")
EOF
