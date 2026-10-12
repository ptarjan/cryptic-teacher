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

Counted in puzzles: each edition or Listener page prints one cryptic; a
Trove article counts the share of read articles that filed a puzzle.

    python3 tools/edition_backlog.py     # {series: [downloaded, queued]} and each source's raw counts
"""
import json
import os
import sys

import downloads
import file_archive_org_puzzles as fa
import file_trove_puzzles as ftp
import gale_listener
import scan_queue


def archive_counts(cache=downloads.ARCHIVE_ORG):
    """{paper key: [editions on disk, never read]} over FILERS."""
    read = set()
    for key in {fa.ledger_of(cache, p) for p in fa.FILERS.values()}:
        read.update(r["edition"] for r in scan_queue.jsonl_rows(key) if "inputs" in r)
    out = {}
    for item in (os.listdir(cache) if cache.is_dir() else ()):
        paper = fa.filer_of(item)
        if paper is None or not (cache / item).is_dir():
            continue
        c = out.setdefault(paper.key, [0, 0])
        for ed in os.listdir(cache / item):
            if (cache / item / ed / "pages.json").exists():
                c[0] += 1
                c[1] += f"{item}/{ed}" not in read
    return out


def listener_counts(inbox=gale_listener.MIRROR, store=gale_listener.STORE):
    """[saved pages, never read]."""
    names = {row.get("file") for row in gale_listener.load_ledger(store).values()}
    pages = [p.name for p in gale_listener.page_files(inbox)]
    return [len(pages), sum(n not in names for n in pages)]


def trove_counts(cache=ftp.CACHE):
    """[articles, never read, articles filed, articles read]."""
    rows = scan_queue.ledger_rows(cache / "filed.jsonl", "article")
    names = os.listdir(cache) if cache.is_dir() else []
    unread = sum(n not in rows and (cache / n / "meta.json").exists() for n in names)
    read = sum(n in rows for n in names)
    return [read + unread, unread, sum(bool(r.get("id")) for r in rows.values()), len(rows)]


def counts():
    """({series: [downloaded, queued]} in puzzles, {source: raw counts})."""
    raw = {**archive_counts(), "listener": listener_counts(), "trove": trove_counts()}
    out = {}

    def add(series, n, q):
        c = out.setdefault(series, [0, 0])
        c[0] += round(n)
        c[1] += round(q)
    for key, c in raw.items():
        if key in fa.FILERS:
            add(fa.FILERS[key].series, *c)
    add(gale_listener.lp.SERIES, *raw["listener"])
    n, q, filed, read = raw["trove"]
    share = filed / read if read else 0
    add(ftp.SERIES, n * share, q * share)
    return out, raw


if __name__ == "__main__":
    by_series, raw = counts()
    print(json.dumps({"series": by_series, "sources": raw}, indent=1, sort_keys=True))
    sys.exit(0)
