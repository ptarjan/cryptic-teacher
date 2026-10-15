#!/usr/bin/env python3
"""Exit 0 when a cryptic-gale-inbox tick would do nothing, so tools/gale_inbox.sh
stops before tools/nightly_worktree.sh (a fetch, the main checkout's follow,
a `reset --hard` of a 57k-file tree: ~20 processes a minute). Exit 1 means
run the tick.

A `gale_inbox.py sync` tick does two things (gale_inbox.sync):
  * re-render the progress page when tools/gale_fetch.py logged a download
    since the last render (FETCHED newer than CHECKLIST) or RENDER_EVERY passed
    (here a download makes it due only RENDER_MIN after the last render);
  * start the full pass (kick) when an edition laid out in the last FRESH
    seconds waits unread and no pass runs and none is held.
This answers both from file times and running.json alone, erring towards
running: any edition row written within FRESH counts as maybe unread. It
imports nothing of the repo's, so it costs one python start.

A full tick also runs at least every MAX_SKIP seconds whatever this finds,
so a pushed fix (to this file too) reaches the tick's worktree.
"""
import json
import os
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
CHECKLIST = HOME / ".cache/gale_inbox/Checklist.html"      # gale_inbox.CHECKLIST
FETCHED = HOME / ".cache/gale_inbox/fetched.json"           # gale_fetch.FETCHED
EDITIONS = Path(os.environ.get("CT_MANIFEST") or HOME / ".cryptic-teacher/media-manifest") / "gale-editions.jsonl"
RUNNING = HOME / ".cache/corpus_queue/running.json"         # corpus_queue.RUNNING
STATE = HOME / ".cache/corpus_queue/state.json"             # corpus_queue.STATE
#: When the last full tick started (tools/gale_inbox.sh touches it).
FULL = HOME / ".cache/gale_inbox/full_tick.stamp"
RENDER_EVERY = 3600                                         # gale_inbox.RENDER_EVERY
FRESH = 3600                                                # file_archive_org_puzzles.FRESH
MAX_SKIP = 15 * 60
#: A download since the last render makes the page due once the render is
#: this old: gale_fetch downloads every minute or so while it runs, and a
#: page re-rendered each of those minutes is ~5x the work for a progress
#: page nobody watches by the minute.
RENDER_MIN = 5 * 60


def mtime(p):
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def pass_running():
    """corpus_queue.running(), without importing it."""
    try:
        r = json.loads(RUNNING.read_text())
        stat = Path(f"/proc/{r['pid']}/stat").read_text().rsplit(")", 1)[1].split()
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return False
    return stat[0] != "Z" and stat[19] == r.get("start")


def held():
    try:
        return bool(json.loads(STATE.read_text()).get("held"))
    except (OSError, ValueError, AttributeError):
        return False


def why_run(now=None):
    """Why the tick must run, or None when it would do nothing."""
    now = time.time() if now is None else now
    full = mtime(FULL)
    if full is None or now - full >= MAX_SKIP:
        return "no full tick in MAX_SKIP"
    if not EDITIONS.exists():
        return None  # sync skips until the manifest is built
    rendered = mtime(CHECKLIST)
    if rendered is None or now - rendered > RENDER_EVERY:
        return "progress page due"
    fetched = mtime(FETCHED)
    if fetched is not None and fetched > rendered and now - rendered >= RENDER_MIN:
        return "gale_fetch logged a download"
    laid = mtime(EDITIONS)
    if laid is not None and now - laid <= FRESH and not pass_running() and not held():
        return "a fresh edition may wait with no pass running"
    return None


if __name__ == "__main__":
    sys.exit(0 if why_run() is None else 1)
