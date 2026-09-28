#!/usr/bin/env python3
"""Stage the published site into _site/, then check that it links up.

  python3 tools/stage_site.py              # REPO -> REPO/_site
  python3 tools/stage_site.py SRC OUT      # any built tree

.github/workflows/pages.yml uploads _site/, not the checkout. The checkout also
holds tools/ and its data, the puzzle sources (puzzles/<id>.json, which the
browser never reads: it loads the puzzles/<id>.js shim built from each one),
docs, scratch and the card manifest. None of it is part of the site, and GitHub
Pages caps a site at 1 GB. So the site is what PUBLISH names and nothing else,
and a new directory has to be named here to ship.

A file PUBLISH forgets is caught rather than silently 404ing: every src=, href=
and og:image in every staged page, and every file puzzles/index.json names,
has to resolve inside _site/, or this exits 1 listing what is missing.

Files are hard-linked, not copied, so staging costs no disk.
"""
import json
import os
import posixpath
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO = Path(__file__).resolve().parent.parent
ORIGIN = "https://cryptic.paultarjan.com"

# Globs relative to the repo root. Root-level globs are by type so that a new
# icon or script at the root ships without an edit here; *.md does not match.
PUBLISH = [
    "CNAME", "*.html", "*.js", "*.css", "*.png", "*.ico", "*.svg", "*.xml",
    "*.txt", "*.webmanifest",
    "vendor/*", "sync/*.js",
    "og/*.png", "og/page/*.png",
    "learn/index.html", "abbreviations/index.html", "difficulty/index.html",
    "puzzles/index.html", "puzzles/index.json", "puzzles/*.js",
    "puzzles/*/index.html", "puzzles/series/**/*",
]

LINK = re.compile(r'''\b(?:src|href)="([^"]*)"|'''
                  r'''property="og:image"\s+content="([^"]*)"''')


def stage(src, out):
    """Link PUBLISH into out; the set of paths staged, relative, with /."""
    if out.exists():
        shutil.rmtree(out)
    staged = set()
    for pattern in PUBLISH:
        for f in src.glob(pattern):
            if not f.is_file():
                continue
            rel = f.relative_to(src).as_posix()
            dest = out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(f, dest)
            except OSError:
                shutil.copy2(f, dest)
            staged.add(rel)
    return staged


def target(page, url):
    """The staged path a link on page (itself a staged path) asks for, or None
    if it is off-site."""
    if url.startswith(ORIGIN):
        url = url[len(ORIGIN):] or "/"
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or not parts.path:
        return None
    path = unquote(parts.path)
    joined = path if path.startswith("/") else posixpath.join(posixpath.dirname(page), path)
    t = posixpath.normpath("/" + joined).lstrip("/")
    return posixpath.join(t, "index.html") if path.endswith("/") or not t else t


def check(out, staged):
    """Every broken link in the staged site, as 'page -> url' lines. A link
    to a directory without its trailing slash counts as broken on purpose:
    Pages answers it with a redirect, not the page."""
    missing = []
    for page in sorted(p for p in staged if p.endswith(".html")):
        text = (out / page).read_text(encoding="utf-8", errors="replace")
        for m in LINK.finditer(text):
            url = m.group(1) if m.group(1) is not None else m.group(2)
            t = target(page, url)
            if t is not None and t not in staged:
                missing.append(f"{page} -> {url}")
    index = json.loads((out / "puzzles/index.json").read_text(encoding="utf-8"))
    for p in index["puzzles"]:
        if f"puzzles/{p['file']}" not in staged:
            missing.append(f"puzzles/index.json -> puzzles/{p['file']}")
    return missing


def main(argv):
    src = Path(argv[0]) if argv else REPO
    out = Path(argv[1]) if len(argv) > 1 else src / "_site"
    staged = stage(src, out)
    missing = check(out, staged)
    if missing:
        print(f"stage_site: {len(missing)} link(s) in {out} point at nothing "
              "(a file PUBLISH does not name, or a page linking a file that "
              "was never built):", file=sys.stderr)
        for line in missing[:50]:
            print("  " + line, file=sys.stderr)
        return 1
    print(f"stage_site: {len(staged)} files staged in {out}, every link resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
