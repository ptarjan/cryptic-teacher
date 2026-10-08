#!/usr/bin/env python3
"""The archive.org books' queue (tools/unit_queue.py): one loan or one read a unit.

tools/acquire_books.sh with no argument is the tick; each unit runs
`tools/acquire_books.sh unit <key>` in one of SLOTS trees:
  * borrow:<id>  one loan: the next book tools/book_queue.py --next names, its
                 text fetched onto disk and the loan returned (minutes). One at
                 a time (the account's loan). archive.org's lending limit
                 counts loans taken over a period it does not publish, so after
                 a refusal (rc 3, EXIT_LENDING_LIMIT) no loan is asked for
                 REFUSAL_WAIT, and at most BORROWS_PER_HOUR are taken an hour.
  * read:<id>    one book read from its text on disk, its grid searches on the
                 desktop (tools/ocr_remote.py): each book tools/book_queue.py
                 --reread lists, READS at once, so one slow book holds up only
                 itself and a book just borrowed is read at the next tick.
  * supersede    a held book file that reprints a held newspaper puzzle turned
                 into a reading of it (fetch_puzzle.py --supersede-books).
"""
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from unit_queue import Unit, main_checkout

LOG = ".books.log"
SLOTS = 3
TREE = "acquire_book"
READS = 2
LIMITS = {"loan": 1, "read": READS}
#: Started from the main checkout, as the scheduler starts the tick:
#: tools/nightly_worktree.sh takes the checkout a script runs from as the one
#: whose state (CT_MAIN_CHECKOUT, the shared files) every tree links to.
SCRIPT = "tools/acquire_books.sh"
HOUR = 3600
REFUSAL_WAIT = HOUR
BORROWS_PER_HOUR = 3
#: A read's own cap is 90 minutes inside the unit (acquire_books.sh); this is
#: the unit's, past which its process group is killed.
READ_SECONDS = 5400 + 900
BORROW_SECONDS = HOUR
#: acquire_book.py's EXIT_LENDING_LIMIT.
REFUSED = 3


def unit(key, **kw):
    return Unit(key=key, argv=["bash", str(main_checkout() / SCRIPT), "unit", key], **kw)


def book_queue(*args):
    run = subprocess.run([sys.executable, str(TOOLS / "book_queue.py"), *args], capture_output=True, text=True, check=False,
                         cwd=str(TOOLS.parent))
    return run.returncode, run.stdout.split()


def refused_since(ledger, now):
    """Whether a borrow was refused within REFUSAL_WAIT."""
    return any(k.startswith("borrow:") and e.get("rc") == REFUSED and now - e["at"] < REFUSAL_WAIT
               for k, e in ledger.last_end.items())


def plan(ledger, now):
    out = []
    if not refused_since(ledger, now) and ledger.started_since("borrow:", now - HOUR) < BORROWS_PER_HOUR:
        rc, ids = book_queue("--next")
        if rc == 0 and ids:
            # The account's refusal is no news about the book: retried
            # REFUSAL_WAIT later, like any book, by refused_since.
            out.append(unit(f"borrow:{ids[0]}", timeout=BORROW_SECONDS, cls="loan", retry=REFUSAL_WAIT, doubling=False,
                            why="next in tools/book_queue.py"))
    _, due = book_queue("--reread")
    for book in due:
        out.append(unit(f"read:{book}", timeout=READ_SECONDS, cls="read", why="its text is on disk and it is due"))
    out.append(unit("supersede", timeout=1200, every=HOUR))
    return out
