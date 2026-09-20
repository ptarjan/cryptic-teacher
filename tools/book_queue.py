#!/usr/bin/env python3
"""Which registered archive.org books have not been read yet, best first.

A book is UNREAD here when the corpus holds no puzzle from it at all. That is
a fact the repo can answer — count `puzzles/book-<index*1000+position>.json` —
rather than a fraction of `estimated_puzzle_count`, which the ranking's own
README says runs high because front and back matter print no puzzles. A
threshold against a number known to be wrong would put books in and out of this
queue on the strength of the error.

Books that hold SOME puzzles are deliberately NOT queued. They were read by
another route (the Penguin OCR, a hand-filed leaf), and their gaps are missing
leaves inside a book somebody already has, not a book nobody has read. Filing
those needs the page numbers, not another whole-book run.

Order is the ranking's own: tools/data/book_candidates.json lists candidates
best first, and the loan that is granted should be spent on the best book still
missing. Anything registered but absent from the ranking goes last, since
nothing measured it.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
POSITIONS_PER_VOLUME = 1000


def filed_counts():
    """{book_index: puzzles filed} over the real corpus."""
    counts = {}
    for path in (ROOT / "puzzles").glob("book-*.json"):
        try:
            number = int(path.stem.split("-", 1)[1])
        except ValueError:
            continue
        counts[number // POSITIONS_PER_VOLUME] = \
            counts.get(number // POSITIONS_PER_VOLUME, 0) + 1
    return counts


def queue():
    """[(identifier, title, estimated_puzzle_count)] — unread, best first."""
    books = json.loads((ROOT / "tools" / "data" / "books.json")
                       .read_text(encoding="utf-8"))["books"]
    ranking = json.loads((ROOT / "tools" / "data" / "book_candidates.json")
                         .read_text(encoding="utf-8"))["ranking"]
    rank_of = {row["identifier"]: i for i, row in enumerate(ranking)}
    estimate = {row["identifier"]: row.get("estimated_puzzle_count")
                for row in ranking}
    counts = filed_counts()
    unread = [b for b in books if not counts.get(b["book_index"])]
    unread.sort(key=lambda b: rank_of.get(b["identifier"], len(ranking)))
    return [(b["identifier"], b["title"], estimate.get(b["identifier"]))
            for b in unread]


def main(argv):
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
