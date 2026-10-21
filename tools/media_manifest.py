#!/usr/bin/env python3
"""What the media disk holds, kept on the SSD so no scheduled job walks it.

The media disk (downloads.ROOT) spins: a job that globs,
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
import importlib
import json
import os
import sys
import threading
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
#: The Trove articles' meta.json titles ("01 Jan 1972 - ..."), one row each:
#: {"article": id, "title", "at"}. tools/fetch_trove.py appends one as it
#: writes an article's meta.json; file_trove_puzzles.article_date appends
#: one for each it had to read off the disk, so a killed plan keeps what it
#: read. A memo, not a listing: a missing row means "read meta.json once".
TROVE_TITLES = "trove-titles"
#: The archive.org edition dirs under downloads.ARCHIVE_ORG holding pages.json,
#: one row each: {"edition": "<item>/<edition dir>", "files": edition_files,
#: "at"}. fetch_archive_org_editions appends one as it writes an edition's
#: pages.json; edition_backlog counts them (with gale-editions' Gale ones);
#: file_archive_org_puzzles lists, keys and dates editions by them
#: (edition_rows). A row with no "files" (an older one) is filled once off
#: the disk and appended.
ARCHIVE_EDITIONS = "archiveorg-editions"
#: The Trove search listings' print dates, one row a hit:
#: {"article": id, "date": "Thursday 11 December 1980", "at"}, in index
#: order (downloads.TROVE/index/<year>.jsonl, oldest year first).
#: `fetch_trove.py search` appends a row for each hit it adds to a year's index.
TROVE_DATES = "trove-dates"
#: Whether a Trove article has clue zones to read (file_trove_puzzles.has_readings):
#: {"article": id, "readings": bool, "at"}. fetch_trove.fetch_zones appends
#: one as it writes an article's zone PNGs (downloads.TROVE_CLUES/<id>/).
TROVE_ZONES = "trove-zones"
#: A Trove article's inputs as file_trove_puzzles.input_hash keys them:
#: {"article": id, "files": trove_files(its dir), "at"}, which tools/fetch_trove.py
#: appends as it writes the article, and {"article": id, "zones":
#: trove_zone_names(its zone dir), "at"}, as it writes the zone PNGs.
#: input_hash appends both for an article it had to read off the disk. A
#: memo: a missing field means "take it off the disk once".
TROVE_INPUTS = "trove-inputs"
#: The files of a Trove article dir (downloads.TROVE/<id>/) a read takes in.
TROVE_FILES = ("meta.json", "ocr.txt", "grid.jpg")
#: The book leaves' readings of held puzzles under downloads.BOOK_REPRINTS
#: (<pid>/<identifier>-<position>.txt), one row each: {"pid", "file", "size",
#: "at"}. book_queue.save_reprint appends one as it writes a reading;
#: book_reprints folds them, so a plan (file_archive_org_puzzles.reprint_key,
#: asked of every puzzle of every edition) never lists or stats a folder per
#: puzzle on the media disk (each a Samba round trip, ~90 ms: ~2900 a gale
#: plan). Complete only once its build ran (complete_path), as a partial
#: manifest would read as "no reprint" for every pid it lacks.
BOOK_REPRINTS = "book-reprints"


def trove_files(d):
    """Trove article dir `d`'s TROVE_FILES by size and modification time in
    whole seconds (a copy to another disk keeps those, not the nanoseconds),
    as one string; a missing file is "<name>:-"."""
    out = []
    for name in TROVE_FILES:
        try:
            st = os.stat(os.path.join(d, name))
        except (FileNotFoundError, NotADirectoryError):
            st = None
        out.append(f"{name}:{st.st_size}:{int(st.st_mtime)}" if st else f"{name}:-")
    return "".join(out)


def trove_zone_names(zdir):
    """The clue zone images in Trove zone dir `zdir` (downloads.TROVE_CLUES/<id>/)
    by name, in print order, space-joined; "" when it is no dir."""
    try:
        names = os.listdir(zdir)
    except (FileNotFoundError, NotADirectoryError):
        names = []
    return " ".join(sorted((n for n in names if n.startswith("zone") and n.endswith(".png")),
                           key=lambda n: int(n[4:-4])))


def record_edition(d):
    """Append edition dir `d` (its pages.json just written) to ARCHIVE_EDITIONS,
    with its files' hash (edition_files), which it returns."""
    d = os.path.normpath(os.fspath(d))
    files = edition_files(d)
    record(ARCHIVE_EDITIONS, d, edition=edition_rel(d), files=files)
    return files


def edition_rel(d):
    """"<item>/<edition dir>" of edition dir `d`."""
    d = os.path.normpath(os.fspath(d))
    return f"{os.path.basename(os.path.dirname(d))}/{os.path.basename(d)}"


def edition_files(d):
    """Edition dir `d`'s files by name and size, hashed: what
    file_archive_org_puzzles.input_hash keys a read by. Lists and stats the
    dir: only a writer that just wrote it, or a memo filling once, calls this."""
    h = hashlib.sha256()
    for n in sorted(os.listdir(d)):
        h.update(f"{n}:{os.stat(os.path.join(d, n)).st_size}".encode())
    return h.hexdigest()[:16]


def _fold_edition(acc, line):
    """Fold one archiveorg-editions or gale-editions row into {rel: {"files",
    "at"}}: a later row's fields stand, "at" when it was last laid out."""
    try:
        row = json.loads(line)
        held = acc.setdefault(row["edition"], {})
    except (ValueError, KeyError, TypeError):
        return  # a torn last line
    held.update({k: row[k] for k in ("files", "at") if k in row})


def edition_rows():
    """{"<item>/<edition dir>": {"files": its input hash when recorded, "at":
    when it was laid out}} of every edition under downloads.ARCHIVE_ORG
    holding pages.json, off the archiveorg-editions and gale-editions
    manifests, folding only the rows appended since the last call. Raises
    SystemExit when either was never built (it would read as no editions).

    The merged dict is this thread's own and kept while neither manifest's
    fold gained a key or was started afresh: its values are the folds' own
    row dicts, which later rows update in place, so it stays current. The
    queue asks this once a queued scan unit a pass (input_hash), and merging
    ~100k rows afresh each time held a core. Callers only read it."""
    me = threading.get_ident()
    hit = _EDITION_ROWS.get(me)
    now = time.monotonic()
    # Asked once a queued unit a pass (thousands a pass): the manifests are
    # opened again only EDITION_ROWS_FRESH seconds on, or once this process
    # appended to one (record), not on every ask.
    if hit is not None and hit[4] == _RECORDED[0] and now - hit[5] < EDITION_ROWS_FRESH:
        return hit[3]
    import dir_cache
    accs = []
    for name in (ARCHIVE_EDITIONS, GALE_EDITIONS):
        acc = dir_cache.appended(path(name), dict, _fold_edition)
        if not acc and not built(name):
            rows(name)  # raises, naming its build
        accs.append(acc)
    key = tuple((id(a), len(a)) for a in accs)
    if hit is not None and hit[0] == key and hit[1] is accs[0] and hit[2] is accs[1]:
        _EDITION_ROWS[me] = hit[:4] + (_RECORDED[0], now)
        return hit[3]
    out = {}
    for acc in accs:
        out.update(acc)
    if len(_EDITION_ROWS) > 64:  # threads come and go
        _EDITION_ROWS.clear()
    _EDITION_ROWS[me] = (key, accs[0], accs[1], out, _RECORDED[0], now)
    return out


#: {thread ident: (fold key, archive fold, gale fold, merged, _RECORDED when
#: folded, time.monotonic() when folded)} of edition_rows.
_EDITION_ROWS = {}
#: How long (seconds) edition_rows trusts its last fold of the manifests
#: before opening them again: a row another process appended is seen this
#: late at most.
EDITION_ROWS_FRESH = 2.0
#: [how many rows this process appended (record)]: edition_rows folds again
#: after one, however fresh its last fold.
_RECORDED = [0]


def memo(name, key, value):
    """{row[key]: row[value]} of manifest `name`, {} when it was never
    written (a cold memo, unlike rows' listing manifests)."""
    try:
        text = path(name).read_text()
    except FileNotFoundError:
        return {}
    out = {}
    for ln in text.splitlines():
        try:
            r = json.loads(ln)
            out[r[key]] = r[value]
        except (ValueError, KeyError, TypeError):
            continue  # a torn last line
    return out


_PATHS = {}


def path(name):
    """Manifest `name`'s file; the Path is kept per DIR (a plan asks ~20k times)."""
    k = (DIR, name)
    hit = _PATHS.get(k)
    if hit is None:
        hit = _PATHS[k] = DIR / f"{name}.jsonl"
    return hit


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
    _RECORDED[0] += 1


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


#: Folders whose file names a scheduled reader lists, each with the manifest
#: its writer appends to (record_file) and the files it holds:
#: {name: (folder getter, glob)}. build_files lists one once.
FOLDERS = {
    # cross_validate.Independent.fetch_one; served() reads its rows' "pid".
    "independent-source": (lambda: downloads.ROOT / "independent-source", "c_*.xml"),
    # ft_pdf_puzzles.fetch_one / orphans; cross_validate.FT.ids.
    "ft-pdf": (lambda: downloads.FT_PDF / "pdf", "*.pdf"),
    # edition_commit.writer (file_archive_org_puzzles); cross_validate.ArchiveOrg.ids.
    "archiveorg-source": (lambda: downloads.ARCHIVE_ORG_SOURCE, "*.json"),
    # file_gale_listener.run; cross_validate.ListenerReport.ids.
    "listenerreport-source": (lambda: downloads.ROOT / "listenerreport-source", "*.json"),
    # cross_validate.Globe.fetch_one: each day's payload (<date>.json) or its .404.
    "globe-source": (lambda: downloads.ROOT / "globe-source", "*"),
}


def trove_ledger(cache):
    """The Trove filer's ledger for the article folder `cache`: on the SSD
    (DIR/trove-filed.jsonl, its lock and unit locks beside it) when `cache` is
    on the media disk, so nothing scheduled spins that disk to read or lock it;
    <cache>/filed.jsonl for a test's own folder. The first call that finds the
    old <cache>/filed.jsonl and no new ledger moves it, rows and all."""
    if not on_media(cache):
        return Path(cache) / "filed.jsonl"
    new = DIR / "trove-filed.jsonl"
    if not new.exists():
        old = Path(cache) / "filed.jsonl"
        if old.exists():
            DIR.mkdir(parents=True, exist_ok=True)
            tmp = new.with_suffix(".moving")
            tmp.write_bytes(old.read_bytes())
            if tmp.stat().st_size != old.stat().st_size:
                tmp.unlink()
                raise OSError(f"copy of {old} to {new} came short")
            tmp.replace(new)  # the new ledger exists only whole
            old.unlink()
            for stale in (old.with_suffix(".lock"), old.with_suffix(".tmp")):
                stale.unlink(missing_ok=True)
    return new


def on_media(folder):
    """Whether `folder` is on the media disk (under downloads.ROOT); a test's
    temp folder is not. Path arithmetic only: no stat."""
    root = os.path.abspath(downloads.ROOT)
    f = os.path.abspath(folder)
    return f == root or f.startswith(root + os.sep)


def record_file(name, written, **extra):
    """Append the file `written` (just saved) to folder manifest `name`
    (FOLDERS), keyed by its file name."""
    record(name, written, key=Path(written).name, **extra)


def folder_files(name, folder, pattern="*"):
    """{file name: its row} of the files in `folder` matching `pattern`: off
    manifest `name` when the folder is on the media disk, never a listing of
    it; a folder elsewhere (a test's) is globbed, see _glob_off_media."""
    import fnmatch
    if not on_media(folder):
        return _glob_off_media(folder, pattern)
    return {k: r for k, r in sorted(latest(name, "key").items()) if fnmatch.fnmatch(k, pattern)}


def _glob_off_media(folder, pattern):
    """folder_files for a folder not on the media disk (on_media): a glob is fine there."""
    return {p.name: {"key": p.name} for p in sorted(Path(folder).glob(pattern))}


def build_files(name, out=sys.stdout, extra=lambda path: {}):
    """List folder `name` of FOLDERS once into its manifest (rows from
    `extra(path)` too). Never scheduled."""
    get, pattern = FOLDERS[name]
    folder = get()
    found = []
    for p in sorted(folder.glob(pattern)) if folder.is_dir() else ():
        found.append({"key": p.name, "at": p.stat().st_mtime, **extra(p)})
    write(name, found)
    print(f"{len(found)} file(s) written to {path(name)}", file=out)
    return found


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


def build_book_reprints(out=sys.stdout):
    """List downloads.BOOK_REPRINTS once (a folder a puzzle, its .txt files)
    into BOOK_REPRINTS and mark it complete. book_reprints runs it once when
    the marker is missing; never scheduled."""
    found = []
    root = downloads.BOOK_REPRINTS
    for d in sorted(os.scandir(root), key=lambda e: e.name) if os.path.isdir(root) else ():
        if d.is_dir():
            found += [{"pid": d.name, "file": e.name, "size": e.stat().st_size, "at": e.stat().st_mtime}
                      for e in sorted(os.scandir(d.path), key=lambda e: e.name) if e.name.endswith(".txt")]
    write(BOOK_REPRINTS, found)
    complete_path(BOOK_REPRINTS).write_text(json.dumps({"at": time.time()}))
    _BOOK_REPRINTS.clear()
    print(f"{BOOK_REPRINTS}: {len(found)} readings", file=out)
    return found


def record_book_reprint(written):
    """Append the reading `written` (<BOOK_REPRINTS>/<pid>/<name>.txt, just
    saved) to BOOK_REPRINTS, with its size."""
    written = Path(written)
    record(BOOK_REPRINTS, written, pid=written.parent.name, file=written.name, size=written.stat().st_size)
    _BOOK_REPRINTS.clear()


def book_reprints():
    """{pid: [(file name, size)] by name} of BOOK_REPRINTS: off the manifest,
    never a listing of the disk; built once (build_book_reprints) when never
    built. Kept BOOK_REPRINTS_FRESH seconds (a plan asks it ~25k times), or
    until this process appended a row (record_book_reprint)."""
    hit = _BOOK_REPRINTS.get("memo")
    if hit is not None and time.monotonic() - hit[0] < BOOK_REPRINTS_FRESH:
        return hit[1]
    if not complete(BOOK_REPRINTS):
        with open(os.devnull, "w") as quiet:
            build_book_reprints(out=quiet)
    held = {}
    for r in memo_rows(BOOK_REPRINTS):
        # "name" is the key a first build wrote; a row of any other shape is skipped, never a crash.
        pid, file, size = r.get("pid"), r.get("file") or r.get("name"), r.get("size")
        if isinstance(pid, str) and isinstance(file, str) and isinstance(size, int):
            held.setdefault(pid, {})[file] = size
    out = {pid: sorted(files.items()) for pid, files in held.items()}
    _BOOK_REPRINTS["memo"] = (time.monotonic(), out)
    return out


#: {"memo": (time.monotonic() when folded, book_reprints' answer)}.
_BOOK_REPRINTS = {}
#: Seconds book_reprints trusts its fold: a reading another process appended is seen this late at most.
BOOK_REPRINTS_FRESH = 5.0


def memo_rows(name):
    """Every row of manifest `name` that parses, oldest first; [] when it
    was never written (a torn last line is skipped)."""
    try:
        text = path(name).read_text()
    except FileNotFoundError:
        return []
    out = []
    for ln in text.splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def write(name, found):
    """Replace manifest `name` whole with the rows `found`."""
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = path(name).with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in found))
    os.replace(tmp, path(name))
    for c in DIR.glob(f"{name}.*.cursor"):  # its readers start again from the top
        c.unlink()


#: The builders here; the Gale editions' is `python3 tools/gale_inbox.py build-manifest`.
def build_archive_editions(out=sys.stdout):
    """Walk downloads.ARCHIVE_ORG once for the edition dirs holding pages.json
    into ARCHIVE_EDITIONS. Never scheduled."""
    root = downloads.ARCHIVE_ORG
    found = [{"edition": f"{item}/{ed}", "at": (root / item / ed / "pages.json").stat().st_mtime,
              "files": edition_files(root / item / ed)}
             for item in sorted(os.listdir(root)) if (root / item).is_dir()
             for ed in sorted(os.listdir(root / item)) if (root / item / ed / "pages.json").exists()]
    write(ARCHIVE_EDITIONS, found)
    print(f"{ARCHIVE_EDITIONS}: {len(found)} editions", file=out)


def build_trove_titles(out=sys.stdout):
    """List downloads.TROVE once and read the title of every article holding
    meta.json that TROVE_TITLES lacks into it. Never scheduled."""
    have = memo(TROVE_TITLES, "article", "title")
    root, n = downloads.TROVE, 0
    for name in sorted(os.listdir(root)):
        if name in have:
            continue
        try:
            title = json.loads((root / name / "meta.json").read_text()).get("title", "")
        except (OSError, ValueError, AttributeError):
            continue
        record(TROVE_TITLES, root / name, article=name, title=title)
        n += 1
    complete_path(TROVE_TITLES).write_text(json.dumps({"at": time.time()}))
    print(f"{TROVE_TITLES}: {len(have)} held, {n} added", file=out)


def trove_hits(root):
    """[(article id, its listing's date text)] of Trove cache `root`'s search
    listings (root/index/<year>.jsonl), in index order: off TROVE_DATES once
    `build trove-dates` has completed it, else read off the listings."""
    if on_media(root) and complete(TROVE_DATES):
        return [(str(r["article"]), r.get("date")) for r in rows(TROVE_DATES)]
    return _trove_hits_read(root)


def _trove_hits_read(root):
    """trove_hits read off the listings themselves."""
    out = []
    for p in sorted((Path(root) / "index").glob("*.jsonl")):
        for ln in p.read_text().splitlines():
            if ln.strip():
                hit = json.loads(ln)
                out.append((str(hit["id"]), hit.get("date")))
    return out


def build_trove_dates(out=sys.stdout):
    """Read downloads.TROVE/index/*.jsonl once into TROVE_DATES, whole. Never scheduled."""
    found = [{"article": a, "date": d, "at": time.time()} for a, d in _trove_hits_read(downloads.TROVE)]
    write(TROVE_DATES, found)
    complete_path(TROVE_DATES).write_text(json.dumps({"at": time.time()}))
    print(f"{TROVE_DATES}: {len(found)} hits", file=out)


def build_trove_zones(out=sys.stdout):
    """List downloads.TROVE_CLUES once: whether each article there has clue
    zones to read, into TROVE_ZONES, whole. Never scheduled."""
    has_readings = importlib.import_module("file_trove_puzzles").has_readings
    root = downloads.TROVE_CLUES
    found = [{"article": name, "readings": has_readings(name, root), "at": time.time()}
             for name in sorted(os.listdir(root)) if (root / name).is_dir()]
    write(TROVE_ZONES, found)
    complete_path(TROVE_ZONES).write_text(json.dumps({"at": time.time()}))
    print(f"{TROVE_ZONES}: {len(found)} articles, {sum(r['readings'] for r in found)} with readings", file=out)


def complete_path(name):
    """The marker a build of memo manifest `name` writes once it holds every
    file: before it, the memo (seeded, or appended as read) is partial."""
    return DIR / f"{name}.complete"


def complete(name):
    """Whether memo manifest `name` holds every file (complete_path)."""
    return complete_path(name).exists()


def build_genius_files(out=sys.stdout):
    """List downloads.GENIUS's pdf/ and article/ once into genius-files
    (genius_puzzles.held). Never scheduled."""
    found = []
    for kind, folder, ext in (("pdf", "pdf", ".pdf"), ("article", "article", ".html")):
        d = downloads.GENIUS / folder
        if d.is_dir():
            found += [{"key": f"{kind}/{e.name[:-len(ext)]}", "at": e.stat().st_mtime} for e in os.scandir(d)
                      if e.name.endswith(ext) and e.name[:-len(ext)].isdigit()]
    d = downloads.GENIUS / "article"
    if d.is_dir():  # fetch_article's pictures, <n>-<k>.img (genius_puzzles.image_paths)
        found += [{"key": f"image/{e.name[:-4]}", "at": e.stat().st_mtime} for e in os.scandir(d)
                  if e.name.endswith(".img")]
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
for _name in FOLDERS:
    BUILDERS[_name] = (lambda n: lambda: build_files(n))(_name)


# The builders' own modules load by name, only when a build runs: never by a
# scheduled reader (nor the page build's import graph, tools/ci_cache.js).
def _independent_row(p):
    return {"pid": importlib.import_module("cross_validate").Independent.pid_of(p)}


def _build_items():
    return importlib.import_module("fetch_archive_org_editions").build_items()


BUILDERS["ia-items"] = _build_items
BUILDERS["archiveorg-done"] = lambda: importlib.import_module("fetch_archive_org_editions").build_done()
BUILDERS["archiveorg-pages"] = lambda: importlib.import_module("fetch_archive_org_editions").build_pages()
BUILDERS[ARCHIVE_EDITIONS] = build_archive_editions
BUILDERS[BOOK_REPRINTS] = build_book_reprints
BUILDERS[TROVE_TITLES] = build_trove_titles
BUILDERS[TROVE_DATES] = build_trove_dates
BUILDERS[TROVE_ZONES] = build_trove_zones
BUILDERS["independent-source"] = lambda: build_files("independent-source", extra=_independent_row)


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
