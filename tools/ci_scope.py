#!/usr/bin/env python3
"""What tests.yml has to run for a push: the whole suite, or the puzzle fast path.

    python3 tools/ci_scope.py decide BASE   # BASE = last commit whose FULL suite passed
    -> "fast"                                  only puzzle data moved since BASE
    -> "full <reason>"                         anything else did (or cannot be told)
    python3 tools/ci_scope.py decide --site BASE  # the same, for pages.yml's build:
                                               SITE_INERT paths do not count either
    python3 tools/ci_scope.py files BASE      # BASE = last commit whose tests-passed was green
    -> the puzzle files added or modified since BASE, one per line (exit 3 when
       there are more than MAX_FILES: the fast path is for small checks)

Why two bases. A burst of pushes costs two runs, not one per push (the pending
run is replaced), so a commit can be skipped without ever being tested. The
guard that nothing but puzzle data moved therefore looks back to the last FULL
pass, which covers every skipped commit, while the puzzle check looks back only
to the last pass of either kind, so the fast path checks what nobody has yet.

Conservative by construction: a path this file does not name is code, a
puzzle deleted or renamed is code, and anything git cannot show is code. The
smoke shards the fast path skips are not lost: the next full run finds the new
puzzles missing from the result cache (tools/ci_cache.js) and checks them.
"""
import re
import subprocess
import sys
from pathlib import Path

import validate_scope

ROOT = Path(__file__).resolve().parent.parent
#: A puzzle file: puzzles/<series>/<year>/<id>.json (the shape validate_scope uses).
PUZZLE = re.compile(r"puzzles/[^/]+/[^/]+/[^/]+\.json")
#: A puzzle's blog facts (tools/blog_store.py): puzzle data, checked with its puzzle.
SIDECAR = re.compile(r"puzzles/[^/]+/[^/]+/[^/]+\.blog")
#: Work-queue state the burn jobs rewrite thousands of times a day. No test
#: reads the real file (they run against fixtures; tests/test_ci_scope.py pins
#: the list against ci_cache.js, which excludes the same files from the smoke
#: test's code key).
QUEUE_STATE = validate_scope.QUEUE_STATE
BACKLOG = validate_scope.BACKLOG
#: Derived files the daily jobs rewrite: blog_compare.py's report (only
#: build_readme.py's prose names it) and blog_facts.py's input hashes (read only by
#: blog_facts.py, blog_store.py and prereset_backfill.sh). No test or validator
#: reads either, so a change to one must not send the push down the full path.
DERIVED_DATA = {"tools/data/blog_compare.json", "tools/data/blog_facts/inputs.sha256"}
MAX_FILES = 1500
#: Paths the site build never reads: the test suite, the docs, the workflows
#: other than pages.yml (not .github/actions/, which pages.yml runs), and the
#: step budgets (read only by pages.yml's budgets job, from its own checkout).
#: pages.yml's build asks with --site, so a push that adds only these to puzzle
#: data keeps the puzzle fast path. A full build path costs ~7 minutes more
#: (run 43254092994, full for tests/test_burn_log.py alone: 15.1 minutes to the
#: deploy against ~8), and 8 of the 41 non-puzzle commits on 2026-11-12 touched
#: nothing else. tests.yml and check.yml ask without --site: a test change still
#: runs the whole suite.
SITE_INERT_DIRS = ("tests/", "docs/")
SITE_INERT_FILES = {
    ".github/workflows/check.yml", ".github/workflows/codeql.yml",
    ".github/workflows/fetch-puzzles.yml", ".github/workflows/nightly-smoke.yml",
    ".github/workflows/tests.yml", "tools/data/deploy_budgets.json",
}


def site_inert(path):
    return path.startswith(SITE_INERT_DIRS) or path in SITE_INERT_FILES


def decide(changes, base_text=None, head_text=None, site=False):
    """("fast", None) or ("full", reason) for `changes`, [(status, path)].

    site: the question is pages.yml's build path, so SITE_INERT paths are skipped."""
    if site:
        changes = [(st, path) for st, path in changes if not site_inert(path)]
    stems = set()
    backlog = None
    rows = set()
    for st, path in changes:
        if path in validate_scope.ENTRY_TABLES and st == "M" and base_text:
            old = base_text(path)
            new = head_text(path) if head_text else (ROOT / path).read_text(encoding="utf-8")
            moved = validate_scope.entry_rows_moved(old, new) if old is not None else None
            if moved is None:
                return "full", f"{path} lost a row or changed shape"
            rows |= moved
        elif PUZZLE.fullmatch(path) or SIDECAR.fullmatch(path):
            # A sidecar deleted with its facts is a fast-path change too; a puzzle's removal is not.
            if st not in ("A", "M") and not (st == "D" and SIDECAR.fullmatch(path)):
                return "full", f"{st} {path}"
            stems.add(Path(path).stem)
        elif path in QUEUE_STATE or path in DERIVED_DATA:
            if st not in ("A", "M"):
                return "full", f"{st} {path}"
        elif path == BACKLOG and st == "M" and base_text:
            backlog = (base_text(path), head_text(path) if head_text else (ROOT / path).read_text(encoding="utf-8"))
        else:
            return "full", f"{st} {path}"
    if rows - stems:
        # A row for a puzzle this push did not change binds a puzzle nobody re-checked.
        return "full", "an entry table row names an unchanged puzzle: " + ", ".join(sorted(rows - stems)[:3])
    if backlog:
        old, new = backlog
        lowered = validate_scope.backlog_tightened(old, new) if old is not None else None
        if lowered is None:
            return "full", f"{BACKLOG} raised an allowance or changed shape"
        # A lowered allowance binds a puzzle nobody re-checked if it is not in the diff.
        if lowered - stems:
            return "full", f"{BACKLOG} lowered the allowance of an unchanged puzzle: " + ", ".join(sorted(lowered - stems)[:3])
    return "fast", None


def puzzle_files(changes):
    return sorted({p if PUZZLE.fullmatch(p) else p[:-len(".blog")] + ".json" for st, p in changes
                   if st in ("A", "M") and (PUZZLE.fullmatch(p) or SIDECAR.fullmatch(p))})


def main(argv):
    site = argv[1:2] == ["--site"] and argv[0] == "decide"
    if site:
        argv = [argv[0]] + argv[2:]
    if len(argv) != 2 or argv[0] not in ("decide", "files"):
        print(__doc__)
        return 2
    mode, base = argv
    try:
        changes = validate_scope.git_changes(base)
    except subprocess.CalledProcessError as e:
        print(f"full cannot diff against {base}: {e}")
        return 0
    if mode == "files":
        files = puzzle_files(changes)
        print("\n".join(files))
        return 3 if len(files) > MAX_FILES else 0
    print(f"since {base}: {len(changes)} path(s) changed", file=sys.stderr)
    # HEAD from git, not the disk: CI's sparse checkouts leave tools/data out.
    verdict, why = decide(changes, validate_scope.git_show(base), validate_scope.git_show("HEAD"), site=site)
    print("fast" if verdict == "fast" else f"full {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
