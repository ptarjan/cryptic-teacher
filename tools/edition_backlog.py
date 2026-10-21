#!/usr/bin/env python3
"""The read queue's size without planning it: per series, the scans on the
media disk that a read queue (tools/edition_queue.py) reads, and how many of
them were never read. A count of directories against the ledgers, no input
hashes, so it runs nightly (tools/progress_record.py) where
edition_queue.py plan takes minutes.

  archive.org and Gale editions  an edition dir holding pages.json whose item
                                 a file_archive_org_puzzles paper reads, unread
                                 while no row of its ledger holds a read
                                 ("inputs", the plan's "never read")
  Gale Listener pages            a saved page no ledger row names ("file")
  Trove articles                 an article dir holding meta.json with no
                                 ledger row

Counted in puzzles: each edition prints one cryptic; Listener pages count
once per puzzle number the ledger read them as (a puzzle can span pages and
its report page: on 2026-10-15, 606 pages were 552 numbers), an unread or
unmatched page one each; a Trove article counts the share of read articles
whose row holds a Canberra puzzle (trove_puzzle(): not a Times reprint, a
copy of another puzzle, or a print since folded into the Times; on
2026-10-15, 760 rows held an id and 664 a Canberra puzzle). An
edition is counted once per series and print date (edition_day()), however
many copies are on disk: the Gale Times and archive.org's NewsUK Times both
hold 1970-1999, and an item can hold a date twice, so on 2026-10-13 the Times
had 14,712 edition dirs for 13,467 dates. A date is read once any copy is.

An edition series' downloaded is its filed puzzles plus the unread scans plus
the dates read and not filed (read_not_filed()), so progress's Read failed
(downloaded less filed less queued) is those dates and To fetch excludes them.

    python3 tools/edition_backlog.py     # {series: [downloaded, queued]} and each source's raw counts

dated() and history() give the same counts for past days, for
progress_record.py backfill: a scan landed on the day of its file's mtime
(pages.json, the Listener page, meta.json) and left the queue on the day of
its first ledger read (readAt, the Listener's readOn).
"""
import collections
import datetime
import json
import os
import re
import sys

import canberra_london_numbers
import archive_coverage
import downloads
import file_archive_org_puzzles as fa
import file_trove_puzzles as ftp
import gale_listener
import media_manifest
import renamed_ids
import scan_queue


def edition_day(ed):
    """The print date an edition dir names ("1989-10-10_30968" -> "1989-10-10"),
    else the dir's whole name, so an undated dir counts on its own."""
    return ed[:10] if re.match(r"\d{4}-\d\d-\d\d(?!\d)", ed) else ed


def by_day(editions):
    """{series: [print dates, dates no copy of which was read]} from
    (series, edition dir, read) rows, one per copy on disk."""
    days = {}
    for series, ed, read in editions:
        key = (series, edition_day(ed))
        days[key] = days.get(key, False) or bool(read)
    out = {}
    for (series, _), read in days.items():
        c = out.setdefault(series, [0, 0])
        c[0] += 1
        c[1] += not read
    return out


def _editions(cache):
    """(paper key, item, edition dir) for each edition on disk holding
    pages.json whose item a FILERS paper reads: off the archiveorg-editions
    and gale-editions manifests when `cache` is on the media disk (never a
    walk of it), else (a test's folder) listed."""
    if not media_manifest.on_media(cache):
        yield from _editions_listed(cache)
        return
    eds = (set(media_manifest.latest(media_manifest.ARCHIVE_EDITIONS, "edition"))
           | set(media_manifest.latest(media_manifest.GALE_EDITIONS, "edition")))
    for rel in sorted(eds):
        item, _, ed = rel.partition("/")
        paper = fa.filer_of(item)
        if paper is not None and ed:
            yield paper.key, item, ed


def _editions_listed(cache):
    """_editions of a folder off the media disk, by listing it."""
    for item in (os.listdir(cache) if cache.is_dir() else ()):
        paper = fa.filer_of(item)
        if paper is None or not (cache / item).is_dir():
            continue
        for ed in os.listdir(cache / item):
            if (cache / item / ed / "pages.json").exists():
                yield paper.key, item, ed


def archive_counts(cache=downloads.ARCHIVE_ORG):
    """({paper key: [edition dirs on disk, never read]} over FILERS, the raw
    copies; {series: by_day()} of them, the puzzles)."""
    read = set()
    for key in {fa.ledger_of(cache, p) for p in fa.FILERS.values()}:
        read.update(r["edition"] for r in scan_queue.jsonl_rows(key) if "inputs" in r)
    out, rows = {}, []
    for key, item, ed in _editions(cache):
        unread = f"{item}/{ed}" not in read
        c = out.setdefault(key, [0, 0])
        c[0] += 1
        c[1] += unread
        rows.append((fa.FILERS[key].series, ed, not unread))
    return out, by_day(rows), read_not_filed(rows)


def read_not_filed(rows):
    """{series: print dates read with no puzzle filed for the date}, from
    (series, edition dir, read) rows: the scans that were read and gave
    nothing (coverage's blank-clues, no-crossword-found, crashed...). A date
    is filed by its own date (archive_coverage.corpus), whichever source
    filed it; a date is read once any copy is (by_day)."""
    state = {}
    for series, ed, read in rows:
        k = (series, edition_day(ed))
        state[k] = state.get(k, False) or bool(read)
    out = {}
    for (series, day), read in state.items():
        if read and day not in archive_coverage.corpus(series)[0]:
            out[series] = out.get(series, 0) + 1
    return out


def listener_counts(inbox=gale_listener.SAVED, store=gale_listener.STORE):
    """[saved pages, never read, puzzles, puzzles never read]: a read page
    counts as the puzzle number its ledger row matched it to, so the pages of
    one puzzle and its report count once; an unread page, or one matched to
    no number, counts on its own."""
    rows = {row.get("file"): row for row in gale_listener.load_ledger(store).values()}
    pages = [p.name for p in gale_listener.page_files(inbox)]
    unread = sum(n not in rows for n in pages)
    numbers = {rows[n].get("number") for n in pages if n in rows}
    unmatched = sum(n in rows and rows[n].get("number") is None for n in pages)
    return [len(pages), unread, len(numbers - {None}) + unmatched + unread, unread]


#: A refusal naming a print that is another puzzle: a Times reprint, filed as
#: the Times original, and a page serving the clues of another number.
COPY_REFUSALS = ("REPRINT reprints ", "but the page served the clues of ")


def trove_puzzle(row, held, renamed, london=()):
    """Does a Trove ledger row hold a Canberra puzzle of its own: an id not
    renamed into another series (renamed_ids), an article `london`
    (canberra_london_numbers) does not number as a London Times reprint,
    whose write was not refused as a copy (COPY_REFUSALS), and that is filed
    (`held`, the filed ids) or held back (refusedWrite, pending) unfiled? A
    clean write whose file is gone was folded into the Times (2026-10-08, 44
    reprints), its row left as read."""
    pid = row.get("id")
    if not pid or pid in renamed or row.get("article") in london:
        return False
    why = row.get("refusedWrite") or ""
    if any(c in why for c in COPY_REFUSALS):
        return False
    return pid in held or bool(why or row.get("pending"))


def trove_ids(series=ftp.SERIES):
    """(the ids filed under series, off the file names; the ids renamed; the
    articles numbered as London Times reprints)."""
    held = {p.stem for p in (renamed_ids.ROOT / "puzzles" / series).glob(f"*/{series}-*.json")}
    try:
        renamed = set(renamed_ids.read())
    except (OSError, ValueError):
        renamed = set()
    return held, renamed, set(canberra_london_numbers.load())


def trove_counts(cache=ftp.CACHE, ids=None):
    """[articles, never read, articles holding a puzzle (trove_puzzle), articles read]."""
    ids = ids or trove_ids()
    rows = scan_queue.ledger_rows(media_manifest.trove_ledger(cache), "article")
    if media_manifest.on_media(cache) and media_manifest.complete(media_manifest.TROVE_TITLES):
        # The articles holding meta.json, off the trove-titles manifest
        # (fetch_trove appends one per meta.json): no listing of the disk.
        # Listed until `media_manifest.py build trove-titles` completes it.
        names = list(media_manifest.memo(media_manifest.TROVE_TITLES, "article", "title"))
    else:
        names = _trove_listed(cache)
    unread = sum(n not in rows for n in names)
    read = sum(n in rows for n in names)
    return [read + unread, unread, sum(trove_puzzle(r, *ids) for r in rows.values()), len(rows)]


def _trove_listed(cache):
    """Article names in a Trove folder off the media disk (a test's): every
    dir name that is read or holds meta.json, by listing it."""
    rows = scan_queue.ledger_rows(media_manifest.trove_ledger(cache), "article")
    names = os.listdir(cache) if cache.is_dir() else []
    return [n for n in names if n in rows or (cache / n / "meta.json").exists()]


def counts():
    """({series: [downloaded, queued]} in puzzles, {source: raw counts})."""
    copies, editions, failed = archive_counts()
    raw = {**copies, "listener": listener_counts(), "trove": trove_counts()}
    out = {}

    def add(series, n, q):
        c = out.setdefault(series, [0, 0])
        c[0] += round(n)
        c[1] += round(q)
    for series, (n, q) in editions.items():
        # Downloaded is what the funnel can subtract from known: the filed
        # puzzles (whichever source filed them, scans need not be among
        # them), the unread and the read-and-not-filed scans. Without the
        # last, a scan read and refused was neither here nor filed, and
        # progress's "To fetch" counted it as a puzzle not yet downloaded.
        filed = len(archive_coverage.corpus(series)[0])
        add(series, max(n, filed + q + failed.get(series, 0)), q)
    add(gale_listener.lp.SERIES, *raw["listener"][2:])
    n, q, filed, read = raw["trove"]
    share = filed / read if read else 0
    add(ftp.SERIES, n * share, q * share)
    return out, raw


def _day(path):
    return datetime.date.fromtimestamp(os.stat(path).st_mtime).isoformat()


def _first_reads(rows, key, stamp):
    """{row[key]: the earliest day a row holding stamp gives}."""
    out = {}
    for r in rows:
        if r.get(stamp) and r.get(key) is not None:
            d = r[stamp][:10]
            out[r[key]] = min(out.get(r[key], d), d)
    return out


def dated(cache=downloads.ARCHIVE_ORG, inbox=gale_listener.SAVED, store=gale_listener.STORE,
          trove=ftp.CACHE):
    """[(series, puzzles, day landed, day first read or None)], one per scan
    counts() counts. A read before the file's mtime (a scan fetched again)
    dates its landing to the read."""
    out = []

    def add(series, n, landed, read):
        out.append((series, n, min(landed, read) if read else landed, read))
    reads = {}
    for key in {fa.ledger_of(cache, p) for p in fa.FILERS.values()}:
        for ed, d in _first_reads((r for r in scan_queue.jsonl_rows(key) if "inputs" in r),
                                  "edition", "readAt").items():
            reads[ed] = min(reads.get(ed, d), d)
    # One scan per series and print date (by_day): landed with its first
    # copy, read with its first read copy.
    days = {}
    for key, item, ed in _editions(cache):
        try:
            landed = _day(cache / item / ed / "pages.json")
        except FileNotFoundError:
            continue
        read = reads.get(f"{item}/{ed}")
        k = (fa.FILERS[key].series, edition_day(ed))
        was = days.get(k)
        days[k] = (landed, read) if was is None else (
            min(was[0], landed), min((d for d in (was[1], read) if d), default=None))
    for (series, _), (landed, read) in days.items():
        add(series, 1, landed, read)
    read = _first_reads(gale_listener.load_ledger(store).values(), "file", "readOn")
    for p in gale_listener.page_files(inbox):
        add(gale_listener.lp.SERIES, 1, _day(p), read.get(p.name))
    rows = scan_queue.jsonl_rows(media_manifest.trove_ledger(trove))
    last = {r["article"]: r for r in rows if "article" in r}
    ids = trove_ids()
    share = sum(trove_puzzle(r, *ids) for r in last.values()) / len(last) if last else 0
    read = _first_reads(rows, "article", "readAt")
    for n in (os.listdir(trove) if trove.is_dir() else ()):
        try:
            landed = _day(trove / n / "meta.json")
        except (FileNotFoundError, NotADirectoryError):
            continue
        # A row with no readAt (stamped later): read the day it landed.
        add(ftp.SERIES, share, landed, read.get(n, landed if n in last else None))
    return out


def history(scans, days):
    """{day: {series: [downloaded, queued]}} over days from dated()'s scans:
    those landed by the day's end, and of them the ones not yet read."""
    out = {}
    for day in days:
        c = collections.defaultdict(lambda: [0.0, 0.0])
        for series, n, landed, read in scans:
            if landed <= day:
                c[series][0] += n
                c[series][1] += n if read is None or read > day else 0
        out[day] = {s: [round(a), round(q)] for s, (a, q) in c.items()}
    return out


if __name__ == "__main__":
    by_series, raw = counts()
    print(json.dumps({"series": by_series, "sources": raw}, indent=1, sort_keys=True))
    sys.exit(0)
