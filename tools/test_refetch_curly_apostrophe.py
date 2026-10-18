#!/usr/bin/env python3
"""A re-fetch serving curly apostrophes must not strip the annotations of the
clues that hold them.

cryptic-30140 lost the annotation of every clue with an apostrophe each night:
the Guardian serves "resident’s", we store "resident's", the merge carried the
annotation across (same words) and the write then dropped it as stale, because
it judged the curly text before straightening it and the annotation quotes the
straight one. Each loss cost a burn re-annotation.

    python3 tools/test_refetch_curly_apostrophe.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
os.chdir(REPO)
import fetch_puzzle as fetcher

old = fetcher.read_puzzle_file(fetcher.resolve_puzzle("cryptic-30140"))
fresh = copy.deepcopy(old)
for e in fresh["entries"]:
    e.pop("annotation", None)
    e["clue"]["text"] = e["clue"]["text"].replace("'", "’")
curled = sum(1 for e in fresh["entries"] if "’" in e["clue"]["text"])
fetcher.merge_annotations(fresh, old)
with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "cryptic-30140.json"
    path.write_text(json.dumps(old))
    fetcher.write_puzzle_file(path, fresh)
    back = json.loads(path.read_text())

held = sum(1 for e in old["entries"] if e.get("annotation"))
kept = sum(1 for e in back["entries"] if e.get("annotation"))
if curled >= 4 and kept == held:
    print(f"ok: {curled} curly clues re-fetched, {kept}/{held} annotations kept")
else:
    print(f"FAIL: {curled} curly clues, kept {kept} of {held} annotations")
    sys.exit(1)
