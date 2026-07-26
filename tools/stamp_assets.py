#!/usr/bin/env python3
"""Cache-bust index.html's asset URLs with content hashes.

GitHub Pages serves style.css/app.js with `cache-control: max-age=14400`, so a
phone can keep showing a four-hour-old stylesheet even after a reload. Rewriting
the references as `style.css?v=<hash>` makes every deploy a new URL, so changes
show up on the next load with no hard refresh.

Usage:
  python3 tools/stamp_assets.py           # rewrite index.html
  python3 tools/stamp_assets.py --check   # exit 1 if any stamp is stale
"""

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "index.html"
ASSETS = ["style.css", "tutorial.js", "app.js", "puzzles/index.js"]


def digest(rel):
    return hashlib.md5((ROOT / rel).read_bytes()).hexdigest()[:8]


def stamp(text):
    for rel in ASSETS:
        pattern = re.compile(r'(["\'])' + re.escape(rel) + r'(\?v=[0-9a-f]+)?\1')
        text = pattern.sub(lambda m: f'{m.group(1)}{rel}?v={digest(rel)}{m.group(1)}', text)
    return text


def main():
    original = INDEX_HTML.read_text(encoding="utf-8")
    stamped = stamp(original)
    if "--check" in sys.argv:
        if stamped != original:
            print("STALE: index.html asset stamps are out of date — "
                  "run python3 tools/stamp_assets.py")
            return 1
        print("asset stamps up to date")
        return 0
    if stamped != original:
        INDEX_HTML.write_text(stamped, encoding="utf-8")
        print("stamped: " + ", ".join(f"{a}?v={digest(a)}" for a in ASSETS))
    else:
        print("asset stamps already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
