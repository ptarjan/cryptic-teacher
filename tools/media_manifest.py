#!/usr/bin/env python3
"""What the media disk holds, kept on the SSD so no scheduled job walks it.

The media disk (downloads.ROOT, /Volumes/Media) spins: a job that globs,
lists or stats its folders on a schedule keeps it awake (Paul 2026-10-14:
"I don't want anything regularly scanning the spinning disk"). So the code
that writes a file there appends a row to that folder's manifest here, and
a scheduled reader asks the manifest instead of the disk. Reading the one
file a job is processing stays fine; a listing is not.

Each manifest is DIR/<name>.jsonl, one JSON object a line, appended whole
(one write under O_APPEND); a later row for the same key stands over an
earlier one. A missing manifest is an error, not an empty disk: a reader
that took it for "nothing there" would fetch everything again.

    python3 tools/media_manifest.py build ia-books     # once, lists the disk
    python3 tools/gale_inbox.py build-manifest         # once, walks the Gale editions
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import downloads

#: The manifests: on the boot SSD, beside the job worktrees; beside a test's
#: own downloads root when CT_DOWNLOADS moves it (CT_MANIFEST moves them alone).
DIR = Path(os.environ.get("CT_MANIFEST")
           or (Path(os.environ["CT_DOWNLOADS"]) / ".manifest" if os.environ.get("CT_DOWNLOADS")
               else os.path.expanduser("~/.cryptic-teacher/media-manifest")))

#: The Gale editions tools/gale_inbox.py lays out under downloads.ARCHIVE_ORG
#: (gale_inbox.build_manifest), one row each: {"edition": "<item>/<date>", "files": fa.input_hash,
#: "sources": [match], "at": seconds}.
GALE_EDITIONS = "gale-editions"
#: The whole-book texts in downloads.IA_BOOKS (book_queue.save_text), one row
#: each: {"identifier", "chars", "at"}.
BOOK_TEXTS = "ia-books"


def path(name):
    return DIR / f"{name}.jsonl"


def built(name):
    """Whether manifest `name` exists (its one-off build ran)."""
    return path(name).exists()


def record(name, written, **row):
    """Append `row` (stamped "at" now unless given) to manifest `name` for
    the file or dir `written`. One outside downloads.ROOT (a test's temp
    folder) is not on the media disk and is not recorded."""
    if not Path(written).resolve().is_relative_to(downloads.ROOT.resolve()):
        return
    row.setdefault("at", time.time())
    DIR.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(row, sort_keys=True) + "\n").encode()
    fd = os.open(path(name), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def rows(name):
    """Every row of manifest `name`, oldest first. Raises SystemExit when it
    was never built (build)."""
    try:
        text = path(name).read_text()
    except FileNotFoundError:
        raise SystemExit(f"{path(name)} is missing: build it once (`python3 tools/media_manifest.py build {name}`, "
                         "or `python3 tools/gale_inbox.py build-manifest`; it walks the media disk, nothing scheduled may)") from None
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


def latest(name, key):
    """{row[key]: its last row} of manifest `name`."""
    return {r[key]: r for r in rows(name)}


def build_book_texts(out=sys.stdout):
    """List downloads.IA_BOOKS once and write a row for each whole-book text
    (<identifier>.txt, not a .sample-), as book_queue.save_text would have.
    Never scheduled."""
    found = []
    for e in sorted(os.scandir(downloads.IA_BOOKS), key=lambda e: e.name):
        if e.name.endswith(".txt") and ".sample-" not in e.name and e.is_file():
            found.append({"identifier": e.name[:-4], "chars": e.stat().st_size, "at": e.stat().st_mtime})
    write(BOOK_TEXTS, found)
    print(f"{len(found)} book text(s) written to {path(BOOK_TEXTS)}", file=out)
    return found


def write(name, found):
    """Replace manifest `name` whole with the rows `found`."""
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = path(name).with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in found))
    os.replace(tmp, path(name))


#: The builders here; the Gale editions' is `python3 tools/gale_inbox.py build-manifest`.
BUILDERS = {BOOK_TEXTS: build_book_texts}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="walk the disk once and write a manifest whole (never scheduled)")
    b.add_argument("name", choices=sorted(BUILDERS))
    a = ap.parse_args(argv)
    BUILDERS[a.name]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
