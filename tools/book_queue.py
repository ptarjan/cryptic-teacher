#!/usr/bin/env python3
"""Which registered archive.org books have not been read yet, best first.

A book is QUEUED to borrow when the reader in force has not read it and its
text is not on disk (see RE-READS): never read, or read once and its text lost.
Whether it holds puzzles already does not matter: clues-only filing
(tools/clues_only.py) files every leaf the reader can split, so a book's
unfiled leaves are worth a loan as much as a book nobody has read.

Order is the ranking's own: tools/data/book_candidates.json lists candidates
best first, and the loan that is granted should be spent on the best book still
missing. Anything registered but absent from the ranking goes last, since
nothing measured it.

PINNED BOOKS go before the ranking: tools/data/book_pins.json's "pinned" list,
first entry first. The ranking file is regenerated wholesale by
tools/rank_book_candidates.py, so a priority written into it is lost on the next
run; a person's "take this one next" lives in its own file. A pin only reorders
the queue: a pinned book that is read, or not registered, is skipped, so a
stale pin cannot re-borrow a read book.

RE-READS. A reader change (parser, light spec, grid search, filing) can turn a
book's unfiled leaves into puzzles, so every book is re-read by the reader in
force: a book is DUE when tools/data/book_reads.json has no read of it at or
after REREAD_BEFORE. Set REREAD_BEFORE to the time the reader change lands
(UTC, to the second): a reader that changes twice in a day must not count the
morning's reads as its own.
A due book whose text is in TEXT_DIR is re-read from that text with no loan
(`--reread`); one whose text is gone is queued to borrow (`--next`).
Re-reading is idempotent: tools/acquire_book.py skips every leaf the corpus
already holds, so a solved puzzle is never overwritten by its unsolved self.
"""
import json
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
POSITIONS_PER_VOLUME = 1000
# A reader change that should file more of a book's leaves moves this to the
# time it lands, in UTC: the commit's own `git log -1 --format=%cI` converted.
# Reads are stamped the same way, so the two compare as strings.
REREAD_BEFORE = "2026-10-06T07:38:34+00:00"
# Where a borrowed book's page OCR is kept. Not /tmp: a reboot wipes it, and
# the only way back is another loan.
TEXT_DIR = (pathlib.Path(os.environ.get("XDG_STATE_HOME")
                         or pathlib.Path.home() / ".local" / "state")
            / "cryptic-teacher" / "ia-books")
# Each book's last read: {identifier: {"on": "<UTC ISO time>", "found": N,
# "filed": N}}, written by tools/acquire_book.py after every read.
READS = ROOT / "tools" / "data" / "book_reads.json"
# Where earlier code left borrowed text. adopt_texts() moves it into TEXT_DIR.
OLD_TEXT_DIRS = (pathlib.Path("/tmp/cryptic-teacher-ia-books"),
                 pathlib.Path.home() / ".cryptic-teacher" / "ia-books")


def adopt_texts():
    """Copy whole-book texts the old locations still hold into TEXT_DIR."""
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OLD_TEXT_DIRS:
        for path in old.glob("*.txt") if old.is_dir() else ():
            if ".sample-" in path.name or (TEXT_DIR / path.name).exists():
                continue
            shutil.copy2(path, TEXT_DIR / path.name)


def text_of(identifier):
    """The cached whole-book text for identifier, or None."""
    path = TEXT_DIR / f"{identifier}.txt"
    return path if path.exists() and path.stat().st_size > 0 else None


def reads():
    return (json.loads(READS.read_text(encoding="utf-8"))
            if READS.exists() else {})


def record_read(identifier, found, filed):
    """Note that the reader in force read identifier today."""
    import datetime
    rows = reads()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    rows[identifier] = {"on": now,
                        "found": found, "filed": filed}
    READS.write_text(json.dumps(dict(sorted(rows.items())), indent=1) + "\n",
                     encoding="utf-8")


def due(identifier):
    """True when the reader in force has not read identifier yet."""
    return (reads().get(identifier) or {}).get("on", "") < REREAD_BEFORE


def queue():
    """[(identifier, title, estimated_puzzle_count)] to borrow, best first:
    the unread and the due books whose text is gone, in one ranking."""
    books = json.loads((ROOT / "tools" / "data" / "books.json")
                       .read_text(encoding="utf-8"))["books"]
    ranking = json.loads((ROOT / "tools" / "data" / "book_candidates.json")
                         .read_text(encoding="utf-8"))["ranking"]
    rank_of = {row["identifier"]: i for i, row in enumerate(ranking)}
    estimate = {row["identifier"]: row.get("estimated_puzzle_count")
                for row in ranking}
    # Unread, or due with its text gone: either way only a loan reads it.
    wanted = [b for b in books
              if due(b["identifier"]) and not text_of(b["identifier"])]
    pins_path = ROOT / "tools" / "data" / "book_pins.json"
    pinned = (json.loads(pins_path.read_text(encoding="utf-8"))["pinned"]
              if pins_path.exists() else [])
    pin_of = {identifier: i for i, identifier in enumerate(pinned)}
    wanted.sort(key=lambda b: (pin_of.get(b["identifier"], len(pinned)),
                               rank_of.get(b["identifier"], len(ranking))))
    return [(b["identifier"], b["title"], estimate.get(b["identifier"]))
            for b in wanted]


def rereads():
    """Registered identifiers due for a re-read whose text is on disk."""
    books = json.loads((ROOT / "tools" / "data" / "books.json")
                       .read_text(encoding="utf-8"))["books"]
    return [b["identifier"] for b in books
            if due(b["identifier"]) and text_of(b["identifier"])]


def main(argv):
    if "--reread" in argv:
        adopt_texts()
        for identifier in rereads():
            print(identifier)
        return 0
    rows = queue()
    if "--count" in argv:
        print(len(rows))
        return 0
    if "--next" in argv:
        # Nothing left is not a failure: it is the queue being finished, and a
        # scheduled caller has to be able to tell that from a broken run.
        if not rows:
            return 1
        print(rows[0][0])
        return 0
    for identifier, title, est in rows:
        print(f"{identifier}\t{est if est is not None else '?'}\t{title}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
