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

NOT LENDABLE. A book archive.org lends to no one and will not let this account
read (tools/fetch_ia_book.NotLendable) is recorded in book_reads.json with a
"not_lendable" reason and never queued again, whatever REREAD_BEFORE says.
"""
import json
import pathlib
import sys

import downloads

ROOT = pathlib.Path(__file__).resolve().parent.parent
POSITIONS_PER_VOLUME = 1000
# A reader change that should file more of a book's leaves moves this to the
# time it lands, in UTC: the commit's own `git log -1 --format=%cI` converted.
# Reads are stamped the same way, so the two compare as strings.
REREAD_BEFORE = "2026-10-06T07:38:34+00:00"
# Where a borrowed book's page OCR is kept: the only way back is another loan.
TEXT_DIR = downloads.IA_BOOKS
# A book leaf whose clues are a held puzzle's is that puzzle reprinted, not a
# new book-N: tools/acquire_book.py files no copy and leaves its reading here,
# <held id>/<identifier>-<position>.txt, one more voter on the held puzzle's
# clues (tools/file_archive_org_puzzles.reprint_readings). Outside the repo,
# as the book text it is read from.
REPRINT_DIR = downloads.BOOK_REPRINTS
# Each book's last read: {identifier: {"on": "<UTC ISO time>", "found": N,
# "filed": N}}, written by tools/acquire_book.py after every read.
READS = ROOT / "tools" / "data" / "book_reads.json"


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


def record_not_lendable(identifier, reason):
    """Note that archive.org lends identifier to no one and will not let this
    account read it: no reader change or wait brings its text, so it leaves
    the queue for good, the reason kept beside it. Delete the row to ask
    again."""
    import datetime
    rows = reads()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    rows[identifier] = {"on": now, "not_lendable": reason}
    READS.write_text(json.dumps(dict(sorted(rows.items())), indent=1) + "\n",
                     encoding="utf-8")


def record_no_puzzles(identifier, reason):
    """Note that identifier's text holds no puzzle region the reader can find
    (parse_penguin_book.NoPuzzleRegion). It is read as of today, so it is not
    due again until a reader change moves REREAD_BEFORE; the reason is kept
    beside it. Its text stays on disk."""
    import datetime
    rows = reads()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    rows[identifier] = {"on": now, "found": 0, "filed": 0, "no_puzzles": reason}
    READS.write_text(json.dumps(dict(sorted(rows.items())), indent=1) + "\n",
                     encoding="utf-8")


def no_puzzles(identifier):
    """The reason the reader found no puzzles in identifier's text, or None."""
    return (reads().get(identifier) or {}).get("no_puzzles")


def not_lendable(identifier):
    """archive.org's reason identifier can never be borrowed, or None."""
    return (reads().get(identifier) or {}).get("not_lendable")


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
              if due(b["identifier"]) and not text_of(b["identifier"])
              and not not_lendable(b["identifier"])]
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


def reprint_readings(pid, root=None):
    """[Path] each book leaf's reading of held puzzle `pid` (REPRINT_DIR)."""
    d = pathlib.Path(root or REPRINT_DIR) / pid
    return sorted(d.glob("*.txt")) if d.is_dir() else []


def save_reprint(pid, identifier, position, across, down, root=None):
    """Keep a book leaf that reprints held puzzle `pid` as a reading of it:
    one clue a line, "<number> <text> (<count>)", under ACROSS and DOWN, as
    the archive.org filer's column readings are set out. `across` and `down`
    are light_spec lights ([number, length, source, printed]); a light whose
    number the OCR lost (None) is set out without one, as a lost number
    reads in a column."""
    lines = []
    for heading, lights in (("ACROSS", across), ("DOWN", down)):
        lines.append(heading)
        for light in lights:
            printed = (light[3] if len(light) > 3 else None) or {}
            if printed.get("clue"):
                head = "" if light[0] is None else f"{light[0]} "
                count = f" ({printed['enumeration']})" if printed.get("enumeration") else ""
                lines.append(f"{head}{printed['clue']}{count}")
    d = pathlib.Path(root or REPRINT_DIR) / pid
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{identifier}-{position}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
