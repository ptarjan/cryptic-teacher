#!/bin/bash
# Does no scheduled tick walk the media disk?
#
#     bash tools/test_no_media_scans.sh
#
# The media disk (tools/downloads.py's ROOT, /Volumes/Media) spins; Paul
# 2026-10-14: "I don't want anything regularly scanning the spinning disk".
# The functions below run on a household schedule (every minute, every ten)
# and read what is there from tools/media_manifest.py's SSD manifests, which
# the writers append to. This fails on any listing, glob, walk or stat call
# in their bodies; reading the one file a job processes is done elsewhere.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import ast
import sys

#: {file: [function]} each scheduled tick runs (household-plugins/*/plugin.toml).
SCHEDULED = {
    # cryptic-gale-inbox, every minute: gale_inbox.py sync.
    "gale_inbox.py": ["sync", "_sync_locked", "kick", "fresh_unread", "staged_matches", "other_wanted",
                      "editions", "checklist"],
    # cryptic-books, every ten minutes: book_queue.py --next / --reread.
    "book_queue.py": ["text_of", "queue", "rereads"],
    "media_manifest.py": ["rows", "latest"],
}
SCANS = {"glob", "rglob", "iterdir", "listdir", "scandir", "walk", "stat", "exists", "is_file", "is_dir"}
#: Paths on the SSD those functions may stat: gale_fetch's log in ~/.cache,
#: the repo's pins file.
SSD = {"FETCHED", "pins_path"}
bad = []
for f, names in SCHEDULED.items():
    tree = ast.parse(open(f).read())
    defs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in names:
        if name not in defs:
            bad.append(f"{f}: {name} is gone; update SCHEDULED")
            continue
        for node in ast.walk(defs[name]):
            if isinstance(node, ast.Call):
                fn = node.func
                called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                on = getattr(fn, "value", None)
                if called in SCANS and not (isinstance(on, ast.Name) and on.id in SSD):
                    bad.append(f"{f}:{node.lineno}: {name} calls {called}()")
# fetch_fifteensquared.py runs at every daily ft/azed/genius unit: its cache
# report reads every post, so only --status runs it.
tree = ast.parse(open("fetch_fifteensquared.py").read())
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
for stmt in main.body:
    guarded = isinstance(stmt, ast.If) and "status" in ast.unparse(stmt.test)
    if not guarded and any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "status" for n in ast.walk(stmt)):
        bad.append(f"fetch_fifteensquared.py:{stmt.lineno}: main runs status() without --status")
if bad:
    print("A scheduled tick reads tools/media_manifest.py, not the media disk:\n" + "\n".join(bad))
    sys.exit(1)
print(f"ok: {sum(map(len, SCHEDULED.values()))} scheduled functions list, glob and stat nothing")
PY
