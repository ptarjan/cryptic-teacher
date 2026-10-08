#!/usr/bin/env python3
"""The archive.org and Gale editions' read queue: one small unit per edition.

    python3 tools/edition_queue.py run [--paper P ...] [--reread BEFORE] [--seconds N] [--workers N] [--fetch SRC]
    python3 tools/edition_queue.py plan [--paper P ...] [--reread BEFORE] [--fetch SRC]  # what is due; reads nothing

Each unit is one edition's scan (file_archive_org_puzzles.scan_unit) or one
edition's read and filing (read_unit), run in a process of its own, forked
from this one, with its own time limit (SCAN_SECONDS, READ_SECONDS) and its
own lock on the edition (scan_queue.source_lock), adding its own ledger row
(scan_queue.append). So one slow edition holds up only its own slot, and two
queues (tools/ocr_full_pass.sh's and tools/gale_read.sh's) never read one
edition twice.

What is due comes from file_archive_org_puzzles.plan(), every paper's, made
again every REPLAN seconds, so an edition that lands mid-run (a Gale page
Paul saved, an archive.org fetch) is started within about a minute. The
most urgent first (plan's RANKS): Gale pages saved by hand, then never-read
editions and the re-reads annotation asked for (tools/scan_queue.py), then
editions whose inputs moved, then the re-reads --reread BEFORE makes due.
A read waits until the scans it needs (its own, and the SOLUTION_DAYS after
it, where its solution prints) are made; those scans take the read's rank.
Scans run in SCAN_WORKERS slots (this host's CPU), reads in --workers slots
(mostly a wait on the desktop VLM).

--fetch SOURCE adds a fetcher's units (FETCHERS: archive.org, one edition
each, fetch_archive_org_editions.fetch_unit) in a pool of their own, its
plan() made with the rest; what a fetch lands is scanned and read from the
next plan on. A unit is tried once a run: one that runs out of time or fails is left for
the next run. --seconds stops starting units after N seconds and lets those
running finish, then prints "left for the next run" when anything due was
not started, as the batch filers do, so tools/ocr_full_pass.sh runs it in
slices and moves its tree to origin/master between them. --beside runs a
batch filer (the Trove filer) beside the units, again while it says "left
for the next run", each run under its own time limit, so it never waits on
the editions nor they on it. SIGTERM stops starting units, passes the
TERM to each one running and waits up to STOP_GRACE seconds for them.
"""
import argparse
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import fetch_archive_org_editions as fetch_ao  # noqa: E402
import file_archive_org_puzzles as fa  # noqa: E402
import scan_queue  # noqa: E402

#: The papers in the order a rank's units are taken.
PAPERS = ["gale", "times", "telegraph", "guardian", "ft"]
WORKERS = 20
SCAN_WORKERS = 3
#: A unit still running this long is killed and left for the next run.
SCAN_SECONDS = 1200
READ_SECONDS = 1200
#: How often (seconds) the queue is planned again.
REPLAN = 60
#: How long a stop waits for the units it TERMed before it KILLs them.
STOP_GRACE = 30
#: A unit's exit status: what read_unit/scan_unit/a fetcher's unit returned.
EXITS = {"read": 0, "scanned": 0, "current": 0, "fetched": 0, "busy": 3, "held": 4, "outage": 5,
         "throttled": 6, "disk": 7}

#: The fetch units (--fetch SOURCE): each source's plan() of units, its unit
#: runner, how many run at once and each one's time limit. archive.org
#: throttles each connection (~100 KB/s), not the client, so its units run
#: in parallel, one connection each; an answer 429 lowers its slots by one,
#: and FETCH_OUTAGES units in a row finding it down stop its fetches for
#: the run (fetch_archive_org_editions.outage).
FETCHERS = {
    "archive.org": {"plan": lambda: fetch_ao.plan(fetch_ao.downloads.ARCHIVE_ORG),
                    "run": lambda u: fetch_ao.fetch_unit(fetch_ao.downloads.ARCHIVE_ORG, u),
                    "workers": 12, "seconds": 1200},
}
FETCH_OUTAGES = fetch_ao.FAILURES_IN_A_ROW


def log(line):
    print(f"{time.strftime('%H:%M:%S')} {line}", file=sys.stderr, flush=True)


def plan(papers, cache=fa.CACHE, reread=None, newer=None, out=None):
    """(scan units, read units) of every paper, each list most urgent
    first: by rank, then the paper's place in `papers`, then plan's order.
    A paper whose ledger a batch run holds throughout is left out (its units
    could not add their rows). `newer` (a time.time()) keeps only the reads
    of editions laid out since then and the scans they need."""
    asked = {}
    try:
        for req in scan_queue.all_open_requests():
            if req["filer"] == "archive":
                p = fa.filer_of(req["source"])
                if p is not None:
                    asked.setdefault(p.key, set()).add(req["source"])
    except (OSError, ValueError) as e:
        log(f"the annotation re-read requests did not load ({type(e).__name__}: {e}); planned without them")
    scans, reads = [], []
    for k, key in enumerate(papers):
        paper = fa.FILERS[key]
        if scan_queue.held(fa.ledger_of(cache, paper)):
            if out is not None:
                out.append(f"{key}: a run holds {fa.ledger_of(cache, paper).with_suffix('.lock')}; left out")
            continue
        sc, rd = fa.plan(paper, cache, reread=reread, asked=asked.get(key, ()))
        if newer is not None:
            rd = [u for u in rd if fa.staged_at(Path(cache) / u["rel"]) >= newer]
            need = {rel for u in rd for rel in u["needs"]}
            sc = [u for u in sc if u["rel"] in need]
        scans += [(u["rank"], k, n, u) for n, u in enumerate(sc)]
        reads += [(u["rank"], k, n, u) for n, u in enumerate(rd)]
    return [u for *_, u in sorted(scans, key=lambda t: t[:3])], [u for *_, u in sorted(reads, key=lambda t: t[:3])]


def key_of(unit):
    return unit["kind"], unit["paper"], unit["rel"]


def slot_of(unit):
    """The pool a unit runs in: "scan", "read", or its fetch source."""
    return unit["paper"] if unit["kind"] == "fetch" else unit["kind"]


def plan_fetches(sources):
    """Every fetch source's units, each source's in its plan's order."""
    out = []
    for src in sources:
        out += [{**u, "kind": "fetch", "paper": src, "rank": 1} for u in FETCHERS[src]["plan"]()]
    return out


def run_unit(unit, cache, puzzles, reread):
    """In the forked child: the unit's outcome (EXITS)."""
    if unit["kind"] == "fetch":
        return FETCHERS[unit["paper"]]["run"](unit)
    paper = fa.FILERS[unit["paper"]]
    if unit["kind"] == "scan":
        return fa.scan_unit(paper, unit["rel"], cache)
    return fa.read_unit(paper, unit["rel"], cache, puzzles=puzzles, reread=reread, force=unit.get("force"))


#: Each --beside run's --seconds when the queue has no --seconds of its own,
#: and how long past its --seconds it is let run before it is killed.
BESIDE_SECONDS = 3600
BESIDE_GRACE = 1200


class Beside:
    """A batch filer (one taking --seconds) run beside the units, again
    while its output says "left for the next run" and starting is allowed,
    each run given the queue's time left (or BESIDE_SECONDS) as its
    --seconds and killed BESIDE_GRACE after it. Its output goes to a file
    this loop copies to the log as it grows: no thread, since the units are
    forked from this process."""

    def __init__(self, argv):
        self.argv, self.seconds = argv, 0
        self.proc, self.started, self.again, self.done = None, 0.0, True, False
        self.out, self.pos, self.text = None, 0, ""

    def copy(self):
        self.out.seek(self.pos)
        new = self.out.read()
        self.pos += len(new)
        if new:
            sys.stderr.write(new.decode(errors="replace"))
            sys.stderr.flush()
            self.text = (self.text + new.decode(errors="replace"))[-4096:]

    def poll(self, may_start, remaining=None):
        if self.proc is not None:
            self.copy()
            rc = self.proc.poll()
            if rc is None:
                if time.monotonic() - self.started > self.seconds + BESIDE_GRACE:
                    log(f"beside: {shlex.join(self.argv)} ran {BESIDE_GRACE}s past its --seconds; killed")
                    os.killpg(self.proc.pid, signal.SIGKILL)
                return
            self.copy()
            self.out.close()
            self.again = "left for the next run" in self.text
            log(f"beside: {shlex.join(self.argv)[:120]} ended (rc={rc})"
                + ("; it left work, so it runs again" if self.again and rc == 0 else ""))
            self.proc = None
            if rc != 0:
                self.done = True
        if self.done or not self.again or not may_start:
            return
        self.again, self.text, self.pos = False, "", 0
        import tempfile
        self.out = tempfile.TemporaryFile()
        self.seconds = max(60, int(BESIDE_SECONDS if remaining is None else remaining))
        self.proc = subprocess.Popen([*self.argv, "--seconds", str(self.seconds)], stdout=self.out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     start_new_session=True)
        self.started = time.monotonic()

    def busy(self):
        return self.proc is not None

    def stop(self, sig):
        if self.proc is not None and self.proc.poll() is None:
            os.killpg(self.proc.pid, sig)


def dispatch(papers=PAPERS, cache=fa.CACHE, puzzles=None, reread=None, seconds=None, workers=WORKERS,
             scan_workers=SCAN_WORKERS, newer=None, beside=None, read_seconds=READ_SECONDS,
             scan_seconds=SCAN_SECONDS, replan=REPLAN, fetch=()):
    """Run the queue until nothing due is left to start (or `seconds` have
    passed, or a TERM), then wait for the units running. `fetch` names the
    FETCHERS whose units run too, in pools of their own. Returns the exit
    status: 0, or 143 after a TERM."""
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(signal.SIGTERM))
    signal.signal(signal.SIGINT, lambda *_: stop.append(signal.SIGINT))
    begun = time.monotonic()
    running = {}  # pid: (unit, started)
    tried = set()
    finished = {}
    outcomes = {}
    beside = [Beside(argv) for argv in beside or ()]
    scans = reads = fetches = []
    planned = None
    left = 0
    pools = {"scan": scan_workers, "read": workers, **{src: FETCHERS[src]["workers"] for src in fetch}}
    outages = dict.fromkeys(fetch, 0)
    stopped = set()  # fetch sources started no more this run

    def replan_all(notes=None):
        sc, rd = plan(papers, cache, reread, newer, notes)
        live = [s for s in fetch if s not in stopped]
        return sc, rd, plan_fetches(live) if live else []

    def may_start():
        return not stop and (seconds is None or time.monotonic() - begun < seconds)

    def start(unit):
        sys.stdout.flush()
        sys.stderr.flush()
        pid = os.fork()
        if pid == 0:
            code = 1
            try:
                os.setpgid(0, 0)
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                code = EXITS.get(run_unit(unit, cache, puzzles, reread), 1)
            except BaseException as e:  # noqa: BLE001 -- the child's end is its exit status, logged
                scan_queue.failure((unit["rel"],), e)
            finally:
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(code)
        running[pid] = (unit, time.monotonic())
        tried.add(key_of(unit))
        log(f"start {unit['kind']} {unit['rel']} ({unit['reason']})")

    def reap():
        while running:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            if pid == 0:
                return
            if pid not in running:
                continue
            unit, t0 = running.pop(pid)
            finished[key_of(unit)] = time.monotonic()
            rc = os.waitstatus_to_exitcode(status)
            what = {0: "done", 3: "busy (another unit has it)", 4: "held (a run holds the ledger)",
                    5: "failed, the source looks down", 6: "done, but throttled (429)",
                    7: "not started: the disk is full"}.get(rc, f"failed (rc={rc})")
            if unit["kind"] == "fetch":
                src = unit["paper"]
                outages[src] = outages[src] + 1 if rc == 5 else 0
                if rc == 6 and pools[src] > 1:
                    pools[src] -= 1
                    log(f"{src}: answered 429; at most {pools[src]} fetches at once from now on")
                if (rc == 7 or outages[src] >= FETCH_OUTAGES) and src not in stopped:
                    stopped.add(src)
                    log(f"{src}: no more fetches this run ({'disk full' if rc == 7 else f'{outages[src]} in a row found it down'})")
            outcomes[what.split(" ")[0]] = outcomes.get(what.split(" ")[0], 0) + 1
            log(f"end {unit['kind']} {unit['rel']}: {what} in {time.monotonic() - t0:.0f}s")

    def overdue():
        for pid, (unit, t0) in list(running.items()):
            limit = {"read": read_seconds, "scan": scan_seconds}.get(unit["kind"]) or FETCHERS[unit["paper"]]["seconds"]
            if time.monotonic() - t0 > limit:
                log(f"{unit['kind']} {unit['rel']} ran past {limit}s; killed, left for the next run")
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    while True:
        reap()
        overdue()
        for b in beside:
            b.poll(may_start(), None if seconds is None else seconds - (time.monotonic() - begun))
        if may_start() and (planned is None or time.monotonic() - planned >= replan):
            notes = []
            scans, reads, fetches = replan_all(notes)
            planned = time.monotonic()
            for n in notes:
                log(n)
            log(f"planned: {len(scans)} scans, {len(reads)} reads" + (f", {len(fetches)} fetches" if fetch else "")
                + f" due; running {len(running)}")
        fetches = [u for u in fetches if u["paper"] not in stopped]
        busy = {key_of(u) for u, _ in running.values()}
        # A read of an edition read before, waiting only on a new scan, starts
        # after the plan that follows its scans: the scan may leave it not due.
        rescanned = {(p, r) for (k, p, r), t in finished.items() if k == "scan" and t > (planned or 0)}
        pending = {(u["paper"], u["rel"]) for u in scans if key_of(u) not in tried or key_of(u) in busy}
        free = dict(pools)
        for u, _ in running.values():
            free[slot_of(u)] -= 1
        for u in scans + reads + fetches:
            if not may_start() or free[slot_of(u)] <= 0 or key_of(u) in tried:
                continue
            if u["kind"] == "read" and any((u["paper"], r) in pending for r in u["needs"]):
                continue
            if u["reason"] == "scan stale" and any((u["paper"], r) in rescanned for r in u["needs"]):
                continue
            start(u)
            free[slot_of(u)] -= 1
        if stop:
            break
        if not running and not any(b.busy() for b in beside):
            untried = sum(key_of(u) not in tried for u in scans + reads + fetches)
            if not may_start():
                left = untried + sum(b.again and not b.done for b in beside)
                break
            if not untried:
                # Nothing left to start: one more plan, in case something landed.
                scans, reads, fetches = replan_all()
                fetches = [u for u in fetches if u["paper"] not in stopped]
                planned = time.monotonic()
                if all(key_of(u) in tried for u in scans + reads + fetches) and not any(b.again and not b.done
                                                                             for b in beside):
                    break
                continue
        time.sleep(1)
    if stop:
        log(f"stop asked: TERM to {len(running)} running unit(s), up to {STOP_GRACE}s")
        for pid in running:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for b in beside:
            b.stop(signal.SIGTERM)
        end = time.monotonic() + STOP_GRACE
        while running and time.monotonic() < end:
            reap()
            time.sleep(0.2)
        for pid in running:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for b in beside:
            b.stop(signal.SIGKILL)
        reap()
        return 143
    print(f"edition queue: {len(tried)} units started; " + ", ".join(f"{v} {k}" for k, v in sorted(outcomes.items())))
    if left:
        print(f"  {left:5d}  left for the next run")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "plan"):
        p = sub.add_parser(name)
        p.add_argument("--paper", action="append", choices=PAPERS, help="default: every paper, in PAPERS order")
        p.add_argument("--cache", type=Path, default=fa.CACHE)
        p.add_argument("--reread", metavar="BEFORE", help="re-read every edition last read before BEFORE (ISO)")
        p.add_argument("--newer-than", type=float, metavar="SECONDS",
                       help="only the editions laid out in the last SECONDS (and the scans they need)")
        p.add_argument("--fetch", action="append", default=[], choices=sorted(FETCHERS),
                       help="this source's fetch units too, each source in a pool of its own")
    r = sub.choices["run"]
    r.add_argument("--out", type=Path, help="where a puzzle with a blank clue goes (file_archive_org_puzzles --out)")
    r.add_argument("--seconds", type=float, help="start no unit after this many seconds")
    r.add_argument("--workers", type=int, default=WORKERS, help="reads at once")
    r.add_argument("--scan-workers", type=int, default=SCAN_WORKERS)
    r.add_argument("--wait", action="store_true", help="accepted for tools/ocr_full_pass.sh's slices; units never wait")
    r.add_argument("--beside", action="append", default=[], metavar="COMMAND",
                   help="a batch filer taking --seconds to run beside the units (shell words), again while it "
                        "leaves work")
    args = ap.parse_args(argv)
    papers = args.paper or PAPERS
    reread = scan_queue.when(args.reread)
    newer = None if args.newer_than is None else time.time() - args.newer_than
    if args.cmd == "plan":
        notes = []
        scans, reads = plan(papers, args.cache, reread, newer, notes)
        for n in notes:
            print(n)
        for kind, units in (("scans", scans), ("reads", reads)):
            counts = {}
            for u in units:
                counts[(u["rank"], u["paper"], u["reason"])] = counts.get((u["rank"], u["paper"], u["reason"]), 0) + 1
            print(f"{len(units)} {kind} due")
            for (rank, paper, reason), n in sorted(counts.items()):
                print(f"  rank {rank}  {paper:9s} {reason:22s} {n:6d}")
        fetches = plan_fetches(args.fetch)
        if args.fetch:
            print(f"{len(fetches)} fetches due")
        counts = {}
        for u in fetches:
            counts[(u["paper"], u["reason"])] = counts.get((u["paper"], u["reason"]), 0) + 1
        for (src, reason), n in sorted(counts.items()):
            print(f"  {src:11s} {reason:22s} {n:6d}")
        return 0
    for key in papers:
        ledger = fa.ledger_of(args.cache, fa.FILERS[key])
        folded = scan_queue.compact(ledger, "edition")
        if folded and folded[0] != folded[1]:
            log(f"{ledger.name}: {folded[0]} rows folded to {folded[1]}")
    return dispatch(papers, args.cache, args.out, reread, args.seconds, args.workers, args.scan_workers, newer,
                    [shlex.split(b) for b in args.beside], fetch=args.fetch)


if __name__ == "__main__":
    sys.exit(main())
