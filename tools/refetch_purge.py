"""Move aside the OCR caches derived from an edition whose source files were refetched.

A Gale edition the fetcher room lays out again keeps its leaf file names and (often) their sizes,
and the caches under file_archive_org_puzzles.CROPS are keyed by item/date/leaf, so a read of the
new page found the OLD page's words (11-28: GaleSundayTimes 1983-10-23 and 1994-07-24 read the old
title words). Derived reads are invalid once their source changes: purge() moves an edition's
cache files to CROPS/stale_refetch/<stamp>/titles/ (moved, not deleted) so the next read redoes
them. media_manifest.notice_refetched finds the editions; edition_queue.notice_refetches calls
purge on them. Not scan-reached: no reader imports this, so no scan key moves.

Plan-time safe: it never lists a cache dir (titles/ holds ~1M files). It builds the exact names
fa writes, titles/<item>_<edition dir>_<leaf>_page.<reader_key><tail>.json for every page reader
(ocr_clues.reader_key of ch, en5 and each TESS_MODELS reader), tail "" and ".gf", every leaf of the
edition dir (and leaves 0..LEAVES when it cannot be listed), and stats each. About 10 ms an edition.

NOT covered, because their names carry what only a listing gives (a band's pixel box, a clue
number, a Times puzzle number): titles/<key>_<band>.<reader>.json, titles/<key>_over_/quick_/head_
bands, rapid/<edition dir>_<number>*.json, solutions/, solution_reads/, grids/, retry/. Those
are keyed by the band box or crop bytes, and rapid/solutions/grids by date alone, so another paper
of the same date would share them. The one-off for them is a hand sweep, not plan-time code.

CLI: python3 tools/refetch_purge.py --since <iso> [--dry]   (editions of gale-editions.jsonl, or
archiveorg-editions.jsonl, whose newest row is at/after the time and which an older row of
different files shows were refetched; only cache files older than that row move)."""
import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

import downloads
import media_manifest

CROPS = Path(os.path.expanduser("~/.cache/archive_org_crops"))
STALE = "stale_refetch"
TAILS = ("", ".gf")
READERS = ("ch", "en5")
#: Leaves tried when the edition dir cannot be listed.
LEAVES = 200


def reader_keys():
    """The names fa's page readers cache under: ocr_clues.reader_key of PAGE_READERS and of every
    TESS_MODELS reader (a Times model's name carries its file's hash)."""
    try:
        import ocr_clues
        return sorted({ocr_clues.reader_key(w) for w in (*READERS, *ocr_clues.TESS_MODELS)})
    except (ImportError, OSError, AttributeError):
        return list(READERS)


def leaves_of(root, rel):
    """Leaf numbers of edition `rel`'s dir under `root` (leaf_NNNN.jpg), or 0..LEAVES."""
    found = set(range(1))
    try:
        with os.scandir(Path(root) / rel) as it:
            for e in it:
                n = e.name
                if n.startswith("leaf_") and n.endswith(".jpg") and n[5:-4].isdigit():
                    found.add(int(n[5:-4]))
    except OSError:
        return list(range(LEAVES))
    return sorted(found)


def plan(rels, crops=None, root=None, before=None):
    """[(family, file name)] of the cache files that exist for editions `rels` ("<item>/<dir>"),
    by exact-name stat only. `before`: {rel: time}, only files written before it count."""
    crops = Path(CROPS if crops is None else crops)
    root = downloads.ARCHIVE_ORG if root is None else root
    keys = reader_keys()
    before = before or {}
    out = []
    for rel in rels:
        item, _, ed = rel.partition("/")
        if not ed:
            continue
        limit = before.get(rel, float("inf"))
        for leaf in leaves_of(root, rel):
            for rk in keys:
                for tail in TAILS:
                    name = f"{item}_{ed}_{leaf}_page.{rk}{tail}.json"
                    try:
                        if os.stat(crops / "titles" / name).st_mtime < limit:
                            out.append(("titles", name))
                    except OSError:
                        continue
    return sorted(set(out))


def purge(rels, crops=None, root=None, before=None, dry=False, stamp=None):
    """Move the cache files `plan` finds to CROPS/stale_refetch/<stamp>/<family>/; returns how many
    (would move, when dry). A file gone already (another process) is skipped."""
    crops = Path(CROPS if crops is None else crops)
    todo = plan(rels, crops, root, before)
    if dry or not todo:
        return len(todo)
    stamp = stamp or time.strftime("%Y%m%dT%H%M%S")
    n = 0
    for sub, name in todo:
        dest = crops / STALE / stamp / sub
        dest.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(crops / sub / name, dest / name)
            n += 1
        except FileNotFoundError:
            continue
    return n


def refetched_since(since, names=(media_manifest.GALE_EDITIONS, media_manifest.ARCHIVE_EDITIONS)):
    """{rel: at} of the editions whose newest ledger row is at/after epoch `since` and which an
    earlier row of other files shows were laid out again (not first seen)."""
    hist = {}
    for name in names:
        try:
            lines = Path(media_manifest.path(name)).read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                r = json.loads(line)
                hist.setdefault(r["edition"], []).append((r["at"], r["files"]))
            except (ValueError, KeyError, TypeError):
                continue
    out = {}
    for rel, rows in hist.items():
        rows.sort()
        at, files = rows[-1]
        if at >= since and any(f != files for _, f in rows[:-1]):
            out[rel] = at
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Move aside OCR caches of editions refetched since a time")
    ap.add_argument("--since", required=True, help="ISO time (UTC unless it carries an offset)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--crops", default=None)
    a = ap.parse_args(argv)
    t = datetime.datetime.fromisoformat(a.since)
    since = t.timestamp() if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc).timestamp()
    eds = refetched_since(since)
    n = purge(list(eds), a.crops, None, eds, dry=a.dry)
    print(f"{len(eds)} editions refetched since {a.since}; {n} cache files "
          + ("would move" if a.dry else "moved"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
