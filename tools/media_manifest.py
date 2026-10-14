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
    python3 tools/media_manifest.py build posts-fifteensquared  # once each, reads every post

A blog's post cache (<blog>/posts/<id>.json, never rewritten) has one,
posts-<blog>, that its fetcher appends to (record_post) with what a reader
looks a post up by. A parser that turns posts into records keeps a cursor
into it (unread, advance) and reads only the posts added since its last run;
a missing cursor, a rebuilt manifest or a changed parser (`version`) makes it
read them all once.
"""
import argparse
import hashlib
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


def cursor_path(name, reader):
    return DIR / f"{name}.{reader}.cursor"


def unread(name, reader, version=""):
    """(rows, whole, mark): the rows of manifest `name` that `reader` has not
    yet advanced past. `whole` is True, and rows are every row, when the reader
    has no cursor, the manifest was rebuilt since (write drops its cursors),
    or the cursor was taken at another `version` (source_version of the
    parser). Pass `mark` to advance once what the rows fed is saved."""
    every = rows(name)
    try:
        c = json.loads(cursor_path(name, reader).read_text())
    except (FileNotFoundError, ValueError):
        c = None
    if not c or c.get("version") != version or c.get("rows", 0) > len(every):
        return every, True, len(every)
    return every[c["rows"]:], False, len(every)


def advance(name, reader, mark, version=""):
    """Record that `reader` has handled the first `mark` rows of manifest `name`."""
    DIR.mkdir(parents=True, exist_ok=True)
    p = cursor_path(name, reader)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"rows": mark, "version": version}))
    os.replace(tmp, p)


def source_version(*files, extra=b""):
    """A digest of the named files under tools/ (and `extra`): a reader's
    cursor `version`, so a parser change reads every post again once."""
    h = hashlib.sha1(extra)
    for f in files:
        h.update((Path(__file__).parent / f).read_bytes())
    return h.hexdigest()[:16]


def posts_name(posts_dir):
    """The manifest of the post cache `posts_dir` (<blog>/posts)."""
    return f"posts-{Path(posts_dir).parent.name}"


def post_row(post):
    """What a reader looks a post up by: {"id", "date", "title", "link", "slug", "categories"}."""
    title = post.get("title")
    if isinstance(title, dict):
        title = title.get("rendered")
    return {"id": int(post["id"]), "date": post.get("date") or "", "title": title or "",
            "link": post.get("link") or "", "slug": post.get("slug") or "",
            "categories": post.get("categories") or []}


def record_post(posts_dir, post):
    """Append the post just saved as <posts_dir>/<id>.json to its manifest."""
    record(posts_name(posts_dir), Path(posts_dir) / f"{post['id']}.json", **post_row(post))


def posts(posts_dir):
    """{post id: its row} for every post in the cache `posts_dir`."""
    return latest(posts_name(posts_dir), "id")


def post_ids(posts_dir):
    return set(posts(posts_dir))


def parse_new(posts_dir, reader, version, parse, store, want=lambda row: True):
    """([parse(post) of every post in `posts_dir` whose manifest row `want`s,
    in file-name order], save). Only the posts past `reader`'s cursor are
    opened; the earlier ones' results come from `store`, a JSON-lines file of
    {"file", "out"}, which save() rewrites before moving the cursor. Call
    save() once what the results fed is written. All are opened when there
    is no cursor or store, the manifest was rebuilt, or `version` moved."""
    name = posts_name(posts_dir)
    new, whole, mark = unread(name, reader, version)
    held = {}
    if not whole:
        try:
            with open(store, encoding="utf-8") as f:
                for ln in f:
                    if ln.strip():
                        row = json.loads(ln)
                        held[row["file"]] = row["out"]
        except FileNotFoundError:
            whole = True
    if whole:
        new = rows(name)
    for r in new:
        if want(r):
            f = Path(posts_dir) / f"{r['id']}.json"
            held[f.name] = parse(json.loads(f.read_text(encoding="utf-8")))

    def save():
        part = Path(store).with_name(Path(store).name + ".part")
        with open(part, "w", encoding="utf-8") as f:
            for k in sorted(held):
                f.write(json.dumps({"file": k, "out": held[k]}, ensure_ascii=False) + "\n")
        part.replace(store)
        advance(name, reader, mark, version)

    return [held[k] for k in sorted(held)], save


def comments_name(comments_dir):
    return f"comments-{Path(comments_dir).parent.name}"


def record_comments(comments_dir, key):
    """Append the comment file <comments_dir>/<key>.json just saved (a post
    id on fifteensquared, a month YYYY-MM on a WordPress blog)."""
    record(comments_name(comments_dir), Path(comments_dir) / f"{key}.json", key=str(key))


def comment_keys(comments_dir):
    return set(latest(comments_name(comments_dir), "key"))


def build_posts(posts_dir, out=sys.stdout):
    """List `posts_dir` once and read every post the manifest lacks into it
    (all of them the first time), oldest id first. A rerun, after the
    fetchers began recording, reads only what landed in between; it keeps
    the rows and so the readers' cursors. Never scheduled."""
    name = posts_name(posts_dir)
    held = posts(posts_dir) if built(name) else {}
    found = []
    for e in os.scandir(posts_dir):
        if e.name.endswith(".json") and not e.name.startswith(".") and e.name[:-5].isdigit() \
                and int(e.name[:-5]) not in held:
            post = json.loads(Path(e.path).read_text(encoding="utf-8"))
            found.append(dict(post_row(post), at=e.stat().st_mtime))
    found.sort(key=lambda r: r["id"])
    if held:
        for r in found:
            record(name, Path(posts_dir) / f"{r['id']}.json", **r)
    else:
        write(name, found)
    print(f"{len(found)} post(s) added to {path(name)}, {len(held)} already there", file=out)
    return found


def build_comments(comments_dir, out=sys.stdout):
    """List `comments_dir` once into its manifest. Never scheduled."""
    name = comments_name(comments_dir)
    held = comment_keys(comments_dir) if built(name) else set()
    found = sorted(({"key": e.name[:-5], "at": e.stat().st_mtime} for e in os.scandir(comments_dir)
                    if e.name.endswith(".json") and not e.name.startswith(".") and e.name[:-5] not in held),
                   key=lambda r: r["key"])
    if held:
        for r in found:
            record(name, Path(comments_dir) / f"{r['key']}.json", **r)
    else:
        write(name, found)
    print(f"{len(found)} comment file(s) written to {path(comments_name(comments_dir))}", file=out)
    return found


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
    for c in DIR.glob(f"{name}.*.cursor"):  # its readers start again from the top
        c.unlink()


#: The builders here; the Gale editions' is `python3 tools/gale_inbox.py build-manifest`.
def build_genius_files(out=sys.stdout):
    """List downloads.GENIUS's pdf/ and article/ once into genius-files
    (genius_puzzles.held). Never scheduled."""
    found = []
    for kind, folder, ext in (("pdf", "pdf", ".pdf"), ("article", "article", ".html")):
        d = downloads.GENIUS / folder
        if d.is_dir():
            found += [{"key": f"{kind}/{e.name[:-len(ext)]}", "at": e.stat().st_mtime} for e in os.scandir(d)
                      if e.name.endswith(ext) and e.name[:-len(ext)].isdigit()]
    write("genius-files", sorted(found, key=lambda r: r["key"]))
    print(f"{len(found)} Genius file(s) written to {path('genius-files')}", file=out)
    return found


def build_andlit_copies(out=sys.stdout):
    """List downloads.ANDLIT_AZED/copies once into andlit-copies
    (andlit_azed.cached). Never scheduled."""
    d = downloads.ANDLIT_AZED / "copies"
    found = sorted(({"key": e.name, "at": e.stat().st_mtime} for e in os.scandir(d)
                    if e.name.split(".")[0].isdigit() and e.name.count(".") == 1), key=lambda r: r["key"])
    write("andlit-copies", found)
    print(f"{len(found)} Azed copies written to {path('andlit-copies')}", file=out)
    return found


BUILDERS = {BOOK_TEXTS: build_book_texts, "genius-files": build_genius_files, "andlit-copies": build_andlit_copies}
for _blog in ("fifteensquared", "timesforthetimes", "bigdave44"):
    BUILDERS[f"posts-{_blog}"] = (lambda b: lambda: build_posts(downloads.ROOT / b / "posts"))(_blog)
    BUILDERS[f"comments-{_blog}"] = (lambda b: lambda: build_comments(downloads.ROOT / b / "comments"))(_blog)


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
