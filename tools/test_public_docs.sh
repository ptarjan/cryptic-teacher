#!/bin/bash
# Do the public docs describe the project rather than one person's machines?
#
#     bash tools/test_public_docs.sh
#
# The repo is public. Its docs name hosts by role (the OCR host, the GPU host,
# the data disk whose path tools/downloads.py sets), never by a local path,
# a home directory, a LAN address or whose machine it is. This fails on any of
# those in README.md, docs/*.md, BACKFILLS.md, APP.md or tools/data/README.md.
# docs/LAYOUT.md is generated from tools/build_readme.py's table, so a hit
# there is fixed in that table.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import glob
import re
import sys

files = ["README.md", "BACKFILLS.md", "APP.md", "tools/data/README.md"] + sorted(glob.glob("docs/*.md"))
DENY = [
    ("a macOS volume path", re.compile(r"/Volumes/")),
    ("a macOS home path", re.compile(r"/Users/")),
    ("a host home path", re.compile(r"/data/home\b")),
    ("whose machine it is", re.compile(r"\bMac's\b|\bPaul's (?:desktop|laptop|Mac)\b|\bhis (?:desktop|laptop|Mac)\b", re.I)),
    ("what the owner is doing", re.compile(r"playing a game", re.I)),
    ("a LAN address", re.compile(r"\b(?:192\.168\.\d{1,3}|10\.\d{1,3}\.\d{1,3})\.\d{1,3}\b|\b192\.168\.")),
]
bad = 0
for f in files:
    try:
        lines = open(f, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        continue
    for n, line in enumerate(lines, 1):
        for why, rx in DENY:
            m = rx.search(line)
            if m:
                bad += 1
                print(f"{f}:{n}: {why}: {m.group(0)!r}", file=sys.stderr)
if bad:
    print(f"FAIL: {bad} machine detail(s) in the public docs; name the host by role "
          "(the OCR host, the GPU host, the data disk)", file=sys.stderr)
    sys.exit(1)
print(f"ok: {len(files)} public docs name no local path, home, LAN address or owner's machine")
PY
