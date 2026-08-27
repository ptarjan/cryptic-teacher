#!/usr/bin/env python3
"""Cache-bust asset URLs with content hashes.

GitHub Pages serves style.css/app.js with `cache-control: max-age=14400`, so a
phone can keep showing a four-hour-old stylesheet even after a reload. Rewriting
the references as `style.css?v=<hash>` makes every deploy a new URL, so changes
show up on the next load with no hard refresh.

The social card is an asset like any other, and forgetting that cost a week: the
og.png grid was a hand-drawn lattice that no crossword could have (two-letter
lights), it was replaced with a real puzzle's geometry, and the picture stayed
wrong anyway — because Discord, Slack, iMessage and Twitter cache an unfurl
against the image URL, and the URL had not changed. A cache you cannot purge is
a cache you have to out-name. So every static file whose URL is written into a
page is stamped, and `--check` sweeps the generated pages too: an unstamped
reference is a fix that will not reach anyone who has already seen the old one.

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
SITE = "https://paultarjan.com/cryptic-teacher/"
# The generated pages write these as absolute URLs and index.html as relative
# ones; both forms are stamped, so the same file is one cache entry either way.
ASSETS = ["style.css", "app.js", "analytics.js", "abbreviations.js", "sync/merge.js",
          "sync/events.js",
          "puzzles/index.js",
          "og.png", "favicon.svg", "favicon.ico", "apple-touch-icon.png"]


def digest(rel):
    return hashlib.md5((ROOT / rel).read_bytes()).hexdigest()[:8]


def asset_url(rel, base=""):
    """The stamped URL for an asset — for pages generated whole, which are
    written correctly in the first place rather than rewritten afterwards."""
    return f"{base}{rel}?v={digest(rel)}"


def ref(rel):
    """Matches a quoted reference to `rel`, absolute or relative, stamp or not."""
    return re.compile(r'(["\'])((?:' + re.escape(SITE) + r')?)'
                      + re.escape(rel) + r'(\?v=[0-9a-f]+)?\1')


def stamp(text):
    for rel in ASSETS:
        text = ref(rel).sub(
            lambda m: f'{m.group(1)}{m.group(2)}{rel}?v={digest(rel)}{m.group(1)}',
            text)
    return text


def unstamped(path):
    """Asset references on a page that carry no ?v= — i.e. URLs that will go on
    serving whatever a cache already holds, however often the bytes change."""
    text = path.read_text(encoding="utf-8")
    return [rel for rel in ASSETS
            if any(not m.group(3) for m in ref(rel).finditer(text))]


def pages():
    """Every published page. tools/ is skipped: og_card.html is the source the
    social card is rendered from, not something a browser ever loads."""
    return sorted(p for p in ROOT.glob("**/*.html")
                  if "tools" not in p.relative_to(ROOT).parts)


def main():
    original = INDEX_HTML.read_text(encoding="utf-8")
    stamped = stamp(original)
    if "--check" in sys.argv:
        if stamped != original:
            print("STALE: index.html asset stamps are out of date — "
                  "run python3 tools/stamp_assets.py")
            return 1
        bare = [(p.relative_to(ROOT), rels) for p in pages()
                if (rels := unstamped(p))]
        if bare:
            for page, rels in bare:
                print(f"UNSTAMPED: {page} references {', '.join(rels)} "
                      "with no ?v= — caches will keep serving the old bytes")
            print("Generated pages: fix asset_url() use in "
                  "tools/build_seo_pages.py. Hand-written: run stamp_assets.py.")
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
