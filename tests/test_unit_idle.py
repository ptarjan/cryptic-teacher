#!/usr/bin/env python3
# Does unit_queue.why_run let the books and daily ticks skip their worktree
# setup only when the tick would start nothing: a SELF_PLANNING queue (books)
# with nothing due, or any queue while the memory or CPU gate holds every unit
# back; never a queue whose shell plans the tick (daily) past the gates; and a
# full tick at least every FULL_EVERY?
#
#     python3 tests/test_unit_idle.py
#
# A fake queue and state in a temp dir; no network.
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
try:
    (tmp / "q").mkdir()
    (tmp / "q" / "fake_idle_units.py").write_text('''\
from unit_queue import Unit
LIMITS = {}
LOG = "fake.log"
SELF_PLANNING = True
DUE = []
def plan(ledger, now):
    return [Unit(key=k, argv=["true"], timeout=5, every=3600) for k in DUE]
''')
    (tmp / "q" / "fake_shell_units.py").write_text('''\
from unit_queue import Unit
LIMITS = {}
LOG = "fake.log"
def plan(ledger, now):
    return [Unit(key="x", argv=["true"], timeout=5)]
''')
    os.environ["UNIT_QUEUE_STATE"] = str(tmp / "state")
    os.environ["UNIT_QUEUE_PATH"] = str(tmp / "q")
    sys.path[:0] = [str(tmp / "q"), str(REPO / "tools")]

    import unit_queue as u
    import fake_idle_units as fi

    fails = 0

    def check(what, want, got):
        global fails
        print(("ok   " if want == got else "FAIL ") + what
              + ("" if want == got else f": expected {want!r}, got {got!r}"))
        fails += want != got

    u.QUEUES.update(idle="fake_idle_units", shell="fake_shell_units")
    u.STATE.mkdir(parents=True, exist_ok=True)
    u.MEM_READER = lambda: None            # memory unknown: room
    u.LOAD_READER = lambda: 0.0
    now = 1_000_000_000.0

    def stamp(q, ago):
        p = u.STATE / f"{q}.full_tick"
        p.write_text("")
        os.utime(p, (now - ago, now - ago))

    check("no full tick yet: run", "no full tick yet", u.why_run("idle", now))
    stamp("idle", 60)
    check("nothing due: skip", None, u.why_run("idle", now))
    fi.DUE[:] = ["borrow:x"]
    check("a unit due: run", "borrow:x is due", u.why_run("idle", now))
    fi.DUE[:] = []
    stamp("idle", u.FULL_EVERY)
    check("full tick an hour old: run", f"no full tick in {u.FULL_EVERY}s", u.why_run("idle", now))
    stamp("idle", 60)
    u.LOAD_READER = lambda: 1e6
    fi.DUE[:] = ["borrow:x"]
    check("host over its CPU gate, a unit due: skip (tick would start nothing)", None, u.why_run("idle", now))
    u.LOAD_READER = lambda: 0.0
    u.MEM_READER = lambda: 0
    check("host out of memory, a unit due: skip", None, u.why_run("idle", now))
    u.MEM_READER = lambda: None
    stamp("shell", 60)
    check("shell-planned queue, gates open: run", "its tick plans in the shell", u.why_run("shell", now))
    u.LOAD_READER = lambda: 1e6
    check("shell-planned queue, over the CPU gate: skip", None, u.why_run("shell", now))
    u.LOAD_READER = lambda: 0.0
    fi.DUE[:] = []
    (u.STATE / "idle.full_tick").touch()
    check("idle() says 0 to skip", 0, u.idle("idle"))
    (u.STATE / "shell.full_tick").unlink()
    check("idle() says 1 to run", 1, u.idle("shell"))
    check("idle() stamped the full tick", True, (u.STATE / "shell.full_tick").exists())
    import book_units
    check("books plan from the ledger and book_queue alone", True, book_units.SELF_PLANNING)
    if fails:
        sys.exit(1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

for f in ("acquire_books.sh", "daily_update.sh"):
    if 'unit_queue.py" idle' not in (REPO / "tools" / f).read_text():
        print(f"FAIL {f} lacks the idle guard")
        sys.exit(1)
    print(f"ok   {f} asks idle before its worktree")
