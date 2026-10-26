#!/usr/bin/env python3
# Does every backticked path and function in the prose docs still exist?
#
#     python3 tests/test_doc_pointers.py
#
# A backticked name in a doc is a live pointer: `tools/foo.py`, `series.puzzle_id`,
# `check_coverage()`. When the thing it points at is renamed or deleted the
# sentence keeps reading as true, so this fails instead. Bare (unbackticked) text
# is free prose and is not checked.
#
# What is checked, inside inline backticks outside fenced blocks:
#   - a path with a "/" must be tracked, a tracked directory, or gitignored
#     (generated output such as puzzles/index.json), resolved from the repo
#     root, the doc's own directory, or tools/;
#   - a bare file name (`latest.json`) must be one of those, or the basename of
#     a tracked file, or be named in tracked code (a cache file a tool writes);
#   - `module.name` or `module.name()`, where module.py is a tracked file, needs
#     `name` to appear in that module;
#   - `name()` needs `name` to appear in some tracked .py/.js/.sh/.html file.
# Tokens with spaces, placeholders (<x>, *, {}, $), URLs, flags and absolute or
# home paths are prose, not pointers, and are skipped.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)


import re
import subprocess

DOCS = ["README.md", "docs/APP.md", "docs/STYLE.md", "docs/BACKFILLS.md", "docs/LAYOUT.md",
        "docs/AI_SOLVING.md", "docs/ARCHIVE_COVERAGE.md", "docs/FEATURES.md", "docs/PUZZLE_FORMAT.md",
        "docs/ADDING_PUZZLES.md", "docs/NIGHTLY.md", "tools/AUTHORING.md", "tools/data/README.md",
        "vendor/README.md"]
EXT = ("py sh js json jsonl md html css yml yaml toml txt ps1 csv tsv gz "
       "traineddata webmanifest svg png ico").split()

tracked = set(subprocess.run(["git", "ls-files"], capture_output=True,
                             text=True, check=True).stdout.split("\n")) - {""}
dirs = {str(Path(t).parent) for t in tracked}
for d in list(dirs):
    while "/" in d:
        d = d.rsplit("/", 1)[0]
        dirs.add(d)
# This file is left out: its own mirror names below would vouch for themselves.
code = [t for t in tracked if t.endswith((".py", ".js", ".sh", ".html"))
        and t != "tests/test_doc_pointers.py"]
source = "\n".join(Path(t).read_text(errors="ignore") for t in code)
words = set(re.findall(r"\w+", source))
basenames = {Path(t).name for t in tracked}


def candidates(tok, doc):
    tok = tok.rstrip("/")
    seen = []
    for base in ("", str(Path(doc).parent), "tools"):
        c = os.path.normpath(os.path.join(base, tok)) if base else tok
        if c not in seen:
            seen.append(c)
    return seen


def resolve(tok, doc):
    for c in candidates(tok, doc):
        if c in tracked or c in dirs:
            return c
    return None


def ignored(tok, doc):
    for c in candidates(tok, doc):
        if subprocess.run(["git", "check-ignore", "-q", "--no-index", c]).returncode == 0:
            return True
    return False


# Ratchet fields (wordplay.anagramCharade) are keys of the backlog file, not
# attributes of the module that happens to share their first word.
import json
ratchet = set(json.loads(Path("tools/annotation_backlog.json").read_text()))


def problem(tok, doc):
    if tok in ratchet:
        return None
    if re.search(r"[\s<>*{}$|=~\[\]\"',;]", tok) or "://" in tok:
        return None
    if tok.startswith(("-", "/", "#", ".", "origin/", "gui/")):
        return None
    m = re.fullmatch(r"(\w+)\(\)", tok)
    if m:
        return None if m.group(1) in words else f"no function {m.group(1)} in any tracked code"
    path = tok.split(":")[0].split("#")[0]
    is_path = "/" in path or re.fullmatch(r"[\w.-]*\w\.(%s)" % "|".join(EXT), path)
    if is_path and (resolve(path, doc) or ignored(path, doc)):
        return None
    if is_path and "/" not in path and (path in basenames or path in source):
        return None
    m = re.fullmatch(r"([\w/-]+)\.(\w+)(?:\([^()]*\))?", tok)
    if m and m.group(2) not in EXT:
        mod = resolve(m.group(1) + ".py", doc)
        if mod:
            body = set(re.findall(r"\w+", Path(mod).read_text(errors="ignore")))
            return None if m.group(2) in body else f"{mod} has no {m.group(2)}"
    if is_path:
        return "no such tracked or gitignored path"
    return None


# The mirror: a checker that passes everything passes this file too.
for tok, dead in (("tools/series.py", False), ("series.puzzle_id", False),
                  ("tools/no_such_tool.py", True), ("series.no_such_name", True),
                  ("no_such_function_anywhere()", True), ("no_such_cache.json", True)):
    if bool(problem(tok, "README.md")) != dead:
        sys.exit(f"FAIL the checker {'missed' if dead else 'flagged'} `{tok}`")

fails = 0
# Every ratchet field is explained in PUZZLE_FORMAT.md (an annotator meets it only as a
# validator message, so an undocumented rule has no written meaning).
_format = Path("docs/PUZZLE_FORMAT.md").read_text(encoding="utf-8")
_validator = Path("tools/validate_annotations.py").read_text(encoding="utf-8")
for key in sorted(ratchet - {"_why"}):
    if f"`{key}`" not in _format:
        print(f"FAIL docs/PUZZLE_FORMAT.md: backlog key `{key}` is not documented")
        fails += 1
    if f'"{key}":' not in _validator:
        print(f"FAIL tools/validate_annotations.py: backlog key `{key}` has no message entry")
        fails += 1
for doc in DOCS:
    text = Path(doc).read_text(encoding="utf-8")
    # Blank fenced blocks line for line, so the reported line numbers hold.
    text = re.sub(r"^```.*?^```", lambda m: "\n" * m.group(0).count("\n"),
                  text, flags=re.S | re.M)
    for n, line in enumerate(text.split("\n"), 1):
        for tok in re.findall(r"`([^`\n]+)`", line):
            why = problem(tok.strip(), doc)
            if why:
                print(f"FAIL {doc}:{n}: `{tok}`: {why}")
                fails += 1
if fails:
    print(f"{fails} dead pointer(s). Point the doc at what exists now, or drop the "
          "backticks if the name is history rather than a pointer.")
    sys.exit(1)
print(f"ok   every backticked path and function in {len(DOCS)} docs exists")
