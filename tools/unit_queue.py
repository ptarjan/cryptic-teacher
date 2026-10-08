#!/usr/bin/env python3
"""Scheduled work as a queue of small units: one phase, puzzle or book each.

    python3 tools/unit_queue.py tick <queue> [--dry-run]   # start every due unit, detached; returns at once
    python3 tools/unit_queue.py plan <queue>               # what is due and why; starts nothing
    python3 tools/unit_queue.py status <queue>             # each unit's last outcome, and what runs now
    python3 tools/unit_queue.py run --timeout S [--cls C] <queue> <key> -- <argv...>   # one unit (what tick starts)

The queues are the nightly's (tools/daily_units.py, run by
tools/daily_update.sh) and the archive.org books' (tools/book_units.py, run by
tools/acquire_books.sh). Their scheduled entry points are ticks: the scheduler
fires one every few minutes, it plans what is due and starts each due unit as
a process of its own, detached, and exits. So one slow unit holds up only
itself, and a puzzle that lands mid-morning is fetched, filed and annotated
within the next ticks rather than at the next 04:45. The same pattern as
tools/edition_queue.py's editions: fork per item, a lock per item, an
append-only ledger row per outcome, re-planned every tick.

A unit (Unit below) is a command with
  * its own lock (STATE/<queue>.locks/), so a tick never starts one twice;
  * its own time limit: past it the unit's process group is TERMed, then
    KILLed STOP_GRACE later, recorded as rc 124 and alerted;
  * its own tree: a queue with SLOTS runs each unit in one of SLOTS worktrees
    (<TREE>-1 .. <TREE>-<SLOTS>, tools/nightly_worktree.sh via CT_JOB), each
    holding only that unit's changes, so its commit is `git add -A` of its
    own tree, and a dropped unit's commits are salvaged by the next unit to
    take that tree;
  * rows in STATE/<queue>.jsonl: "start" and "end" (rc, seconds).
What is due comes from the ledger: a unit with `every` is due that long after
its last good start; one listed as an item (every=None) is due once, and
again ITEM_AGAIN later if it is still listed; a failure is retried after
RETRY seconds, doubling per failure in a row up to MAX_BACKOFF. `after` holds
a unit back while any unit it names is running or due (an explicit
dependency), and `trigger` makes it due when a unit it names ended well since
its own last start. `cls` caps how many of a kind run at once (the queue's
LIMITS), and SLOTS caps them all.
A backfill drains at the source's own pace, not a cadence: a unit that stops
with work left (its wall-clock budget spent) calls backlog_left(), its end
row says "more", and it is due again at the next tick, whatever its `every`.
"""
import argparse
import dataclasses
import fcntl
import hashlib
import importlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import mem_gate

TOOLS = Path(__file__).resolve().parent
QUEUES = {"daily": "daily_units", "books": "book_units"}
STATE = Path(os.environ.get("UNIT_QUEUE_STATE")
             or Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "cryptic-teacher" / "units")
RETRY = 600
MAX_BACKOFF = 6 * 3600
ITEM_AGAIN = 24 * 3600
STOP_GRACE = 60
#: A unit's exit when its tree was taken under it: not run, retried.
LEASE_BUSY = 75
#: Rows older than this are dropped when the ledger is compacted (the last
#: start and end of each unit always stay).
KEEP_DAYS = 14


@dataclasses.dataclass
class Unit:
    key: str
    argv: list
    timeout: int
    cls: str = ""
    every: int | None = None
    after: tuple = ()
    trigger: tuple = ()
    retry: int = RETRY
    why: str = ""
    #: A label kept on its start row, which a queue counts budgets by.
    tag: str = ""
    #: False: a failure is retried every `retry`, never further apart (a
    #: refusal that is news about the account, not the unit).
    doubling: bool = True


def backlog_left():
    """Say, from inside a unit, that it stopped with backlog left: it is due
    again at the next tick rather than after its `every`. A no-op outside a
    unit (run by hand)."""
    path = os.environ.get("UNIT_MORE")
    if path:
        Path(path).touch()


def log(line, out=sys.stderr):
    print(f"{time.strftime('%H:%M:%S')} {line}", file=out, flush=True)


def queue_module(name):
    """The queue's module; UNIT_QUEUE_PATH adds a folder whose <name>_units.py
    defines one (tools/test_unit_queue.sh's fake)."""
    sys.path.insert(0, str(TOOLS))
    extra = os.environ.get("UNIT_QUEUE_PATH")
    if extra:
        sys.path.insert(0, extra)
    if name not in QUEUES and not extra:
        sys.exit(f"unit_queue: no queue {name!r} (one of {', '.join(QUEUES)})")
    return importlib.import_module(QUEUES.get(name) or f"{name}_units")


def main_checkout():
    """The checkout every tree shares state with (its logs, the tree leases)."""
    if os.environ.get("CT_MAIN_CHECKOUT"):
        return Path(os.environ["CT_MAIN_CHECKOUT"])
    common = subprocess.run(["git", "-C", str(TOOLS), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent


def lock_path(queue, key):
    d = STATE / f"{queue}.locks"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha256(key.encode()).hexdigest()[:20] + ".lock")


def try_lock(path):
    """An open file holding `path`'s lock, or None when another holds it."""
    f = open(path, "a")  # noqa: SIM115 -- returned open: the lock is held while it is
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


def held(path):
    if not path.exists():
        return False
    f = try_lock(path)
    if f is None:
        return True
    f.close()
    return False


class Ledger:
    def __init__(self, queue):
        self.queue = queue
        self.path = STATE / f"{queue}.jsonl"
        self.rows = []
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = ""
        for line in text.split("\n"):
            if line.strip():
                try:
                    self.rows.append(json.loads(line))
                except ValueError:
                    continue  # a line cut off by a kill mid-write
        self.last_start, self.last_end, self.last_ok, self.fails = {}, {}, {}, {}
        for r in self.rows:
            k = r["key"]
            if r["event"] == "start":
                self.last_start[k] = r
            elif r["event"] == "end":
                self.last_end[k] = r
                if r.get("rc") == 0:
                    self.last_ok[k] = r
                    self.fails[k] = 0
                else:
                    self.fails[k] = self.fails.get(k, 0) + 1

    def append(self, row):
        STATE.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (json.dumps(row) + "\n").encode())
        finally:
            os.close(fd)

    def running(self, key):
        return held(lock_path(self.queue, key))

    def running_units(self):
        """{key: its start row} of every unit whose lock is held now."""
        return {k: r for k, r in self.last_start.items()
                if (k not in self.last_end or self.last_end[k]["at"] < r["at"]) and self.running(k)}

    def started_since(self, prefix, t, tag=None):
        return sum(1 for r in self.rows if r["event"] == "start" and r["key"].startswith(prefix) and r["at"] >= t
                   and (tag is None or r.get("tag") == tag))

    def compact(self):
        """Drop rows older than KEEP_DAYS, keeping each unit's last start and
        end; whole-or-none (temp + rename). Skipped while another tick holds
        the queue's lock."""
        cut = time.time() - KEEP_DAYS * 86400
        keep = {id(r) for r in (*self.last_start.values(), *self.last_end.values())}
        rows = [r for r in self.rows if r["at"] >= cut or id(r) in keep]
        if len(rows) == len(self.rows):
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        tmp.replace(self.path)


def why_due(unit, ledger, now, due_keys=()):
    """Why `unit` is due now, or None when it is not."""
    k = unit.key
    if ledger.running(k):
        return None
    for a in unit.after:
        if ledger.running(a) or a in due_keys:
            return None
    start, end, ok = ledger.last_start.get(k), ledger.last_end.get(k), ledger.last_ok.get(k)
    if end is not None and end.get("rc") != 0 and (ok is None or end["at"] > ok["at"]):
        wait = min(unit.retry * 2 ** max(0, ledger.fails.get(k, 1) - 1), MAX_BACKOFF) if unit.doubling else unit.retry
        if now - end["at"] < wait:
            return None
        return f"retry after rc={end.get('rc')} ({ledger.fails.get(k, 1)} in a row)"
    if start is not None and (end is None or end["at"] < start["at"]):
        # Started and never ended, and its lock is free: the run was dropped.
        if now - start["at"] < unit.retry:
            return None
        return "its last run was dropped"
    if ok is not None and ok is end and ok.get("more"):
        return "backlog left"
    for t in unit.trigger:
        tok = ledger.last_ok.get(t)
        if tok is not None and (start is None or tok["at"] > start["at"]):
            return f"{t} ended well since"
    if ok is None:
        return unit.why or "never run"
    every = ITEM_AGAIN if unit.every is None else unit.every
    if now - ledger.last_start.get(k, ok)["at"] >= every:
        return unit.why or f"last ran {(now - ok['at']) / 3600:.1f}h ago"
    return None


def due_units(mod, ledger, now=None):
    """[(unit, why)] in the queue's order, each due now, before the class
    and slot caps."""
    now = time.time() if now is None else now
    units = mod.plan(ledger, now)
    # Two passes: `after` looks at what else is due.
    first = {u.key for u in units if why_due(u, ledger, now) is not None}
    out = []
    for u in units:
        why = why_due(u, ledger, now, first - {u.key})
        if why is not None:
            out.append((u, why))
    return out


def spawn(queue, unit, logfile):
    """Start `unit`'s runner in a session of its own, holding none of this
    process's descriptors (the scheduler's lock, the tick's tree lease)."""
    env = {k: v for k, v in os.environ.items() if k not in ("CT_IN_WORKTREE", "CT_JOB")}
    argv = [sys.executable, str(TOOLS / "unit_queue.py"), "run", "--timeout", str(unit.timeout), "--cls", unit.cls,
            *(["--tag", unit.tag] if unit.tag else []), queue, unit.key, "--", *unit.argv]
    with open(logfile, "a") as out:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env,
                         cwd=str(main_checkout()), start_new_session=True, close_fds=True)


#: What the memory gate reads (tests swap it); None is mem_gate.available.
MEM_READER = None
#: What the CPU gate reads (tests swap it); None is mem_gate.load.
LOAD_READER = None


def tick(queue, dry=False):
    mod = queue_module(queue)
    STATE.mkdir(parents=True, exist_ok=True)
    tl = try_lock(STATE / f"{queue}.tick.lock")
    if tl is None:
        print(f"{queue}: another tick is planning; leaving it")
        return 0
    ledger = Ledger(queue)
    if not dry:
        ledger.compact()
    now = time.time()
    running = ledger.running_units()
    per_cls = {}
    for r in running.values():
        per_cls[r.get("cls", "")] = per_cls.get(r.get("cls", ""), 0) + 1
    free = getattr(mod, "SLOTS", 0) - len(running) if getattr(mod, "SLOTS", 0) else None
    started, waiting = [], []
    memory_bound = cpu_bound = False
    for unit, why in due_units(mod, ledger, now):
        cap = mod.LIMITS.get(unit.cls)
        if (free is not None and free <= 0) or (cap is not None and per_cls.get(unit.cls, 0) >= cap):
            waiting.append(unit.key)
            continue
        if not mem_gate.room(len(started), MEM_READER):
            waiting.append(unit.key)
            if not memory_bound:
                memory_bound = True
                print(f"{queue}: memory-bound: under {(mem_gate.FLOOR + mem_gate.UNIT) >> 20} MB available; "
                      "due units wait for the next tick")
            continue
        if not mem_gate.cpu_room(len(started), LOAD_READER):
            waiting.append(unit.key)
            if not cpu_bound:
                cpu_bound = True
                print(f"{queue}: cpu-bound: load over {mem_gate.LOAD_PER_CORE:g} per core; due units wait for the next tick")
            continue
        print(f"{'[dry run] would start' if dry else 'start'} {unit.key} ({why})")
        if not dry:
            spawn(queue, unit, main_checkout() / mod.LOG)
        started.append(unit.key)
        per_cls[unit.cls] = per_cls.get(unit.cls, 0) + 1
        if free is not None:
            free -= 1
    print(f"{queue}: {len(running)} running ({' '.join(sorted(running)) or 'none'}), "
          f"{len(started)} started, {len(waiting)} due waiting for a slot"
          + (f" ({' '.join(waiting[:8])}{' ...' if len(waiting) > 8 else ''})" if waiting else ""))
    if hasattr(mod, "after_tick") and not dry:
        mod.after_tick(Ledger(queue), now)
    return 0


def take_slot(mod):
    """(fd, tree name) of the first free tree of the queue's SLOTS, its lease
    (tools/nightly_worktree.sh) held on fd 9; (None, None) when all are busy."""
    home = main_checkout()
    for n in range(1, mod.SLOTS + 1):
        name = f"{mod.TREE}-{n}"
        f = try_lock(home / f".{name}.tree.lock")
        if f is not None:
            os.dup2(f.fileno(), 9, inheritable=True)
            f.close()
            return 9, name
    return None, None


def alert(text):
    """tools/alert.sh's alert(): to the room, deduplicated there.
    UNIT_QUEUE_ALERT names a command to hand the text to instead (tests)."""
    if os.environ.get("UNIT_QUEUE_ALERT"):
        subprocess.run([*os.environ["UNIT_QUEUE_ALERT"].split(), text], check=False)
        return
    subprocess.run(["bash", "-c", '. "$1/alert.sh" && alert "$2"', "alert", str(TOOLS), text], cwd=str(main_checkout()),
                   check=False)


def run(queue, key, timeout, cls, argv, tag=""):
    """One unit in the foreground: its lock, a tree, its time limit, its rows.
    Its output, each line prefixed with its key, goes to this process's
    stdout (the queue's log). Returns its exit status."""
    mod = queue_module(queue)
    lk = try_lock(lock_path(queue, key))
    if lk is None:
        log(f"[{key}] already running; not started twice")
        return 0
    env = dict(os.environ)
    pass_fds = ()
    if getattr(mod, "SLOTS", 0):
        fd, tree = take_slot(mod)
        if fd is None:
            log(f"[{key}] every one of the {mod.SLOTS} {mod.TREE} trees is busy; the next tick starts it")
            return 0
        env["CT_JOB"] = tree
        # A lease nightly_worktree.sh finds taken after all is this exit, not
        # a 0 that would read as the unit done.
        env["CT_LEASE_BUSY_RC"] = str(LEASE_BUSY)
        pass_fds = (fd,)
    more = lock_path(queue, key).with_suffix(".more")
    more.unlink(missing_ok=True)
    env["UNIT_MORE"] = str(more)
    ledger = Ledger(queue)
    t0 = time.time()
    ledger.append({"key": key, "event": "start", "at": t0, "cls": cls, "pid": os.getpid(),
                   "tree": env.get("CT_JOB"), **({"tag": tag} if tag else {})})
    log(f"[{key}] start{' in ' + env['CT_JOB'] if 'CT_JOB' in env else ''} (limit {timeout}s)")
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=env, pass_fds=pass_fds, start_new_session=True)
    if pass_fds:
        os.close(9)  # the child holds the lease now; it is freed when the unit's last process exits
    tail = []

    def copy():
        for raw in child.stdout:
            line = raw.decode(errors="replace").rstrip("\n")
            tail.append(line)
            del tail[:-12]
            sys.stdout.write(f"[{key}] {line}\n")
            sys.stdout.flush()

    reader = threading.Thread(target=copy, daemon=True)
    reader.start()
    stopped = []

    def on_signal(sig, _):
        stopped.append(sig)
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    timed_out = False
    deadline = t0 + timeout
    while True:
        try:
            rc = child.wait(timeout=min(5, max(0.1, deadline - time.time())) if not stopped else STOP_GRACE)
            break
        except subprocess.TimeoutExpired:
            if stopped:
                os.killpg(child.pid, signal.SIGKILL)
                continue
            if time.time() >= deadline and not timed_out:
                timed_out = True
                log(f"[{key}] ran past its {timeout}s limit; TERM, then KILL after {STOP_GRACE}s")
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.time() + STOP_GRACE
            elif timed_out and time.time() >= deadline:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    # Its output to the end (a `tee` the unit writes through finishes after
    # it), then what it left behind in its group goes with it.
    reader.join(timeout=10)
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    reader.join(timeout=5)
    if timed_out:
        rc = 124
    elif stopped:
        rc = 143
    secs = time.time() - t0
    left = more.exists()
    more.unlink(missing_ok=True)
    ledger.append({"key": key, "event": "end", "at": time.time(), "rc": rc, "secs": round(secs),
                   **({"more": True} if left else {})})
    log(f"[{key}] end: rc={rc} in {secs:.0f}s{', backlog left' if left else ''}")
    if timed_out:
        last = "\n".join(t[:200] for t in tail[-6:])
        alert(f"the {queue} unit `{key}` ran past its {timeout // 60}m limit and was killed; it is retried later and "
              f"nothing else waited on it. Its last lines:\n```\n{last}\n```")
    return rc


def status(queue):
    ledger = Ledger(queue)
    running = ledger.running_units()
    now = time.time()
    for k in sorted(set(ledger.last_start) | set(ledger.last_end)):
        e, s = ledger.last_end.get(k), ledger.last_start.get(k)
        if k in running:
            state = f"running {(now - s['at']) / 60:.0f}m{' in ' + s['tree'] if s.get('tree') else ''}"
        elif e:
            state = f"rc={e.get('rc')} {(now - e['at']) / 3600:.1f}h ago in {e.get('secs', 0)}s"
        else:
            state = "dropped"
        print(f"  {k:40s} {state}{'  (' + str(ledger.fails[k]) + ' failures in a row)' if ledger.fails.get(k) else ''}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("tick", "plan", "status"):
        p = sub.add_parser(name)
        p.add_argument("queue")
    sub.choices["tick"].add_argument("--dry-run", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("queue")
    r.add_argument("key")
    r.add_argument("--timeout", type=int, required=True)
    r.add_argument("--cls", default="")
    r.add_argument("--tag", default="")
    r.add_argument("argv", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    if args.cmd == "tick":
        return tick(args.queue, args.dry_run)
    if args.cmd == "plan":
        mod = queue_module(args.queue)
        for unit, why in due_units(mod, Ledger(args.queue)):
            print(f"  {unit.key:40s} {why}")
        return 0
    if args.cmd == "status":
        status(args.queue)
        return 0
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    return run(args.queue, args.key, args.timeout, args.cls, argv, args.tag)


if __name__ == "__main__":
    sys.exit(main())
