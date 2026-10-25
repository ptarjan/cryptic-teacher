#!/usr/bin/env python3
"""Remove the puzzles/*.js shims (and their .gz) that the index no longer names.

A restored shim cache carries last run's shims; a puzzle deleted or renamed
since has no row in puzzles/index.json, and a clean build would not have its
shim. Run after `fetch_puzzle.py --reindex` in pages.yml and tests.yml.
"""
import json
import pathlib

d = pathlib.Path("puzzles")
index = json.loads((d / "index.json").read_text(encoding="utf-8"))
keep = {"index.js", "index-core.js"} | {p["file"] for p in index["puzzles"] + index.get("unlisted", [])}
gone = [f for f in d.glob("*.js") if f.name not in keep]
# and the .gz stage_site.py made of one (index.js is never gzipped)
gone += [f for f in d.glob("*.js.gz") if f.name[:-3] not in keep or f.name == "index.js.gz"]
for f in gone:
    f.unlink()
print(f"removed {len(gone)} shim(s) no puzzle has")
