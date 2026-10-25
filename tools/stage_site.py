#!/usr/bin/env python3
"""Name the published site, then check that it links up.

  python3 tools/stage_site.py --list LIST  # REPO's site, as a tar file list
  python3 tools/stage_site.py --check LIST # every link in a listed site
  python3 tools/stage_site.py              # REPO -> REPO/_site, linked
  python3 tools/stage_site.py SRC OUT      # any built tree

.github/workflows/pages.yml uploads the site, not the checkout. The checkout also
holds tools/ and its data, the puzzle sources (puzzles/<series>/<year>/<id>.json,
which the browser never reads: it loads the flat puzzles/<id>.js shim built from
each one, so no PUBLISH glob reaches into a series folder),
docs, scratch and the card manifest. None of it is part of the site. So the
site is what PUBLISH names and nothing else, and a new directory has to be
named here to ship.

A file PUBLISH forgets is caught rather than silently 404ing: every src=, href=
and og:image in every published page, and every file puzzles/index.json names,
has to resolve inside the site, or this exits 1 listing what is missing.

The build uses --list and --check, not the _site/ tree: hard-linking ~138k
files into _site/ (67k directories) was 23s of a 45s step (run 38385716791),
for a tree whose only reader was tar. --list writes what tar should archive
(the directories, then the files, each ./-relative to REPO), so tar reads the
checkout itself; --check reads the pages where they are. The link check is
its own invocation so the workflow can run it beside the upload.

The shims ship gzipped. Pages counts the artifact's files uncompressed against
its 1 GB, and the ~45k shims were ~530 MB of it; gzip -9 takes them to ~180 MB
(0.335 of raw, measured 10-13 over the whole corpus). Pages cannot serve a
.gz with Content-Encoding, so only a file the app fetches itself can ship
compressed: app.js fetches puzzles/<id>.js.gz and inflates it in the page
(DecompressionStream, or inflate.js where a browser lacks it). So the site
carries puzzles/<id>.js.gz in place of puzzles/<id>.js; the .js stays in the
checkout for file:// and every tool and harness that reads it. Each .gz is
written beside its shim and rewritten only when the shim's bytes change
(SHIM_GZ_MANIFEST, cached with the shims), so a deploy compresses only what
moved.
"""
import gzip
import hashlib
import json
import os
import posixpath
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

import parallel  # the pages across the cores

REPO = Path(__file__).resolve().parent.parent
ORIGIN = "https://cryptic.paultarjan.com"

# Globs relative to the repo root. Root-level globs are by type so that a new
# icon or script at the root ships without an edit here; *.md does not match.
PUBLISH = [
    "CNAME", "*.html", "*.js", "*.css", "*.png", "*.ico", "*.svg", "*.xml",
    "*.txt", "*.webmanifest",
    "vendor/*", "sync/*.js",
    "og/*.png", "og/page/*.png",
    "learn/index.html", "abbreviations/index.html", "indicators/index.html",
    "difficulty/index.html", "progress/index.html", "showcase/index.html", "showcase/*/index.html",
    "puzzles/index.html", "puzzles/index.json", "puzzles/*.js",
    "puzzles/*/index.html", "puzzles/series/**/*",
]

# A puzzle's shim, which ships as SHIM.gz; puzzles/index.js, the catalogue
# index.html loads as a script, stays plain.
SHIM = re.compile(r"puzzles/(?!index(?:-core)?\.js$)[^/]+\.js")
# md5 of each shim's bytes as of its .gz: not published (no PUBLISH glob).
SHIM_GZ_MANIFEST = "puzzles/shims.gz.json"

LINK = re.compile(r'''\b(?:src|href)="([^"]*)"|'''
                  r'''property="og:image"\s+content="([^"]*)"''')


def select(src):
    """The published files under src, as sorted relative paths with /."""
    found = set()
    for pattern in PUBLISH:
        for f in src.glob(pattern):
            # Two globs may name one file (puzzles/*/index.html and
            # puzzles/series/**/* both match puzzles/series/index.html).
            if f.is_file():
                found.add(f.relative_to(src).as_posix())
    return sorted(found)


#: (src, manifest) for gzip_shim(), set by publish() before its workers fork.
_GZ = None


def gzip_shim(rel):
    """Write src/rel.gz unless the manifest says it already holds rel's
    bytes; (rel, md5 of rel)."""
    src, manifest = _GZ
    js, gz = src / rel, src / (rel + ".gz")
    data = js.read_bytes()
    digest = hashlib.md5(data).hexdigest()
    if manifest.get(rel) != digest or not gz.is_file():
        tmp = gz.with_name(gz.name + ".tmp")
        # mtime=0: the same shim always makes the same bytes.
        tmp.write_bytes(gzip.compress(data, 9, mtime=0))
        os.replace(tmp, gz)
    return rel, digest


def published(rel):
    """The path rel is published at: a shim as its .gz."""
    return rel + ".gz" if SHIM.fullmatch(rel) else rel


def publish(src):
    """select(src) with every shim swapped for its .gz, compressing the
    shims whose .gz is missing or stale."""
    global _GZ
    files = select(src)
    shims = [f for f in files if SHIM.fullmatch(f)]
    if not shims:
        return files
    path = src / SHIM_GZ_MANIFEST
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    _GZ = src, manifest
    try:
        done = dict(parallel.pmap(gzip_shim, shims))
    finally:
        _GZ = None
    path.write_text(json.dumps(done, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return sorted(published(f) for f in files)


def stage(src, out):
    """Link PUBLISH into out; the set of paths staged, relative, with /."""
    if out.exists():
        shutil.rmtree(out)
    staged, made = set(publish(src)), set()
    for rel in staged:
        dest = out / rel
        if dest.parent not in made:
            dest.parent.mkdir(parents=True, exist_ok=True)
            made.add(dest.parent)
        try:
            os.link(src / rel, dest)
        except OSError:
            shutil.copy2(src / rel, dest)
    return staged


def tar_list(files):
    """files as a `tar --no-recursion -T` list: every directory, parents
    first, then the files, each ./-relative, as tar of a staged tree wrote."""
    dirs = {"."}
    for rel in files:
        d = posixpath.dirname(rel)
        while d and d not in dirs:
            dirs.add(d)
            d = posixpath.dirname(d)
    return ["./" if d == "." else f"./{d}" for d in sorted(dirs)] + [f"./{rel}" for rel in files]


def read_list(path):
    """The files a tar_list() names, relative, with /: every entry but the
    directories, which are exactly the entries some other entry sits in."""
    entries = {line[2:] for line in Path(path).read_text(encoding="utf-8").splitlines()
               if line != "./"}
    return entries - {posixpath.dirname(e) for e in entries}


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


#: (out, staged) for page_missing(), set by check() before its workers fork.
_CHECK = None


def page_missing(page):
    """The broken links on one staged page, as check() reports them."""
    out, staged = _CHECK
    text = (out / page).read_text(encoding="utf-8", errors="replace")
    missing = []
    for m in LINK.finditer(text):
        url = m.group(1) if m.group(1) is not None else m.group(2)
        t = target(page, url)
        if t is not None and t not in staged:
            missing.append(f"{page} -> {url}")
    return missing


def check(out, staged):
    """Every broken link in the staged site, as 'page -> url' lines. A link
    to a directory without its trailing slash counts as broken on purpose:
    Pages answers it with a redirect, not the page."""
    global _CHECK
    _CHECK = out, staged
    pages = sorted(p for p in staged if p.endswith(".html"))
    missing = [line for lines in parallel.pmap(page_missing, pages) for line in lines]
    _CHECK = None
    index = json.loads((out / "puzzles/index.json").read_text(encoding="utf-8"))
    for p in index["puzzles"] + index.get("unlisted", []):
        if published(f"puzzles/{p['file']}") not in staged:
            missing.append(f"puzzles/index.json -> {published('puzzles/' + p['file'])}")
    return missing


def report(where, missing):
    if missing:
        print(f"stage_site: {len(missing)} link(s) in {where} point at nothing "
              "(a file PUBLISH does not name, or a page linking a file that "
              "was never built):", file=sys.stderr)
        for line in missing[:50]:
            print("  " + line, file=sys.stderr)
        return 1
    return 0


def main(argv):
    if argv[:1] == ["--list"] and len(argv) == 2:
        t0 = time.monotonic()
        files = publish(REPO)
        Path(argv[1]).write_text("".join(f"{line}\n" for line in tar_list(files)), encoding="utf-8")
        print(f"stage_site: {len(files)} files listed in {argv[1]} in {time.monotonic() - t0:.1f}s")
        return 0
    if argv[:1] == ["--check"] and len(argv) == 2:
        t0 = time.monotonic()
        missing = check(REPO, read_list(argv[1]))
        print(f"stage_site: checked in {time.monotonic() - t0:.1f}s")
        if report(argv[1], missing):
            return 1
        print("stage_site: every link resolves")
        return 0
    src = Path(argv[0]) if argv else REPO
    out = Path(argv[1]) if len(argv) > 1 else src / "_site"
    t0 = time.monotonic()
    staged = stage(src, out)
    t1 = time.monotonic()
    missing = check(out, staged)
    print(f"stage_site: linked in {t1 - t0:.1f}s, checked in {time.monotonic() - t1:.1f}s")
    if report(out, missing):
        return 1
    print(f"stage_site: {len(staged)} files staged in {out}, every link resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
