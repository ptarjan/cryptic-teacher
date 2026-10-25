#!/usr/bin/env python3
"""The archive.org and Gale editions' read queue: one small unit per edition.

    python3 tools/edition_queue.py run [--paper P ...] [--reread BEFORE] [--seconds N] [--workers N] [--fetch SRC]
    python3 tools/edition_queue.py plan [--paper P ...] [--reread BEFORE] [--fetch SRC]  # what is due; reads nothing
    python3 tools/edition_queue.py unit KIND PAPER REL  # one unit; the queue starts these (CT_EDITION_UNIT)

Each unit is one edition's scan (file_archive_org_puzzles.scan_unit) or one
edition's read and filing (read_unit), run in a process of its own, started
as `python3 tools/edition_queue.py unit ...` (never forked from this one), so
it runs the code its tree holds when it starts, with its own time limit (SCAN_SECONDS, READ_SECONDS) and its
own lock on the edition (scan_queue.source_lock), adding its own ledger row
(scan_queue.append). So one slow edition holds up only its own slot, and no
two units read one edition at once.

What is due comes from file_archive_org_puzzles.plan(), every paper's, made
again every REPLAN seconds on a thread. A paper whose inputs did not move is
its last plan again; one whose ledger a unit's row landed in is its last plan
brought up to date (file_archive_org_puzzles.PaperPlan: only the editions
that row touches are worked out again), and planned whole only at a
process's start and every PLAN_FULL seconds. An edition just laid out (a Gale page Paul saved, an
archive.org fetch: fresh) is found apart from it, every FRESH_POLL seconds
on the dispatch loop, and its scan and read start ahead of everything
planned, so it is read within minutes whatever the planner is doing. Then
the most urgent first (plan's RANKS): Gale pages the fetcher downloaded, then never-read
editions and the re-reads annotation asked for (tools/scan_queue.py), then
the re-reads that can change what was filed (inputs moved, a fix for a
refusal cause), then the whole-corpus ones (a scan-code change, --reread
BEFORE), which start only once nothing more urgent waits in any pool; each
rank the reads predicted to file the most puzzles whole first (fa.likely:
a fix since their last read mends what held them), then the newest edition.
A read waits until the scans it needs (its own, and the SOLUTION_DAYS after
it, where its solution prints) are made; those scans take the read's rank.
A read never starts before its own planned scan has ended done: a read
unit making that scan itself does it at the reads' idle desktop priority
and then reads the whole edition here, not prepared, past READ_SECONDS.
Scans run whole on the desktop (ocr_remote.scan, its CPU) in SCAN_WORKERS
slots, reads in --workers slots (mostly the desktop's CPU: its VLM is idle
most of the time). A scan holds while the next --workers ready reads of
its rank or more urgent are there and none of them needs it: scans run
above the reads there and finish ten times as fast, so unchecked they keep
most of the desktop's cores while the scanned editions' reads queue behind them.

--fetch SOURCE adds a fetcher's units (FETCHERS: archive.org, one edition
each, fetch_archive_org_editions.fetch_unit) in a pool of their own, its
plan() made with the rest every FETCH_REPLAN seconds; what a fetch lands is scanned and read from the
next plan on. A unit is tried once a run: one that runs out of time or fails is left for
the next run. --seconds stops starting units after N seconds and lets those
running finish, then prints "left for the next run" when anything due was
not started, as the batch filers do, so tools/ocr_full_pass.sh runs it in
slices and moves its tree to origin/master between them. With --handoff
FILE a slice does not wait for its units: at --seconds it writes those still
running to FILE and ends, and the next slice, started from the moved tree,
takes them on (counts them in its pools, kills them at their limits, TERMs
them on a stop) while it starts new units at once. --beside runs a
batch filer (the Trove filer) beside the units, again while it says "left
for the next run", each run under its own time limit, so it never waits on
the editions nor they on it. SIGTERM stops starting units, passes the
TERM to each one running and waits up to STOP_GRACE seconds for them.

The queue follows its tree too: when a tools/ module it loaded changes on
disk (tools/durable.sh's DURABLE_RESYNC moves the tree to origin/master while
it runs), it hands its running units to its own new image (--resume, or
--handoff when it has one) and re-execs itself, same pid, same --seconds
end, so no run outlives the code it started on by more than a REPLAN.

SIGHUP reloads the queue (tools/hot_reload.py): no unit starts, the units
running are handed over to the next image (--handoff; without it they get
CT_RELOAD_GRACE seconds, then are TERMed and left deferred) and the run exits
75, which tools/ocr_full_pass.sh takes as "move the tree to origin/master and
start again at once". The queue asks for that itself when a fetch of
origin/master (every CT_RELOAD_POLL, 180s) shows tools/ code changed, not
puzzles, and only in the queue's own code (hot_reload.queue_code: what it
imports at module level, transitively, the scripts it starts and its wrappers;
a change elsewhere in tools/ logs "reload: ignoring N changed files" and
waits for the next relevant one). CT_AUTO_RELOAD=0 opts out.

With CT_YIELD_HOSTS set (space-separated ssh hosts, e.g. "user@host.example";
unset by default) the queue yields to those hosts too, even with OCR_REMOTE
empty (scans and reads OCR here, on a machine Paul also games on): while
desktop_busy.busy says one is busy, nothing but fetches starts, exactly as
with a busy OCR_REMOTE desktop; units already running are left alone, as there.
CT_SCAN_WORKERS (default 1, SCAN_WORKERS) raises the most scans at once; with
it above 1 each scan pins to a core no other scan holds (spread_cpu),
unless OCR_SCAN_CPU names one.
Each process loads all its code as it starts (code_reach.modules: lazy
imports too), under a shared lock on the tree's code (snapshot) that
tools/durable.sh's tree move takes whole, so none pairs modules of two
versions of the tree. A scan or read unit loads only its paper's module
(UNIT_MODULES) and what that may load (load_unit), not the queue's.

With a desktop set (OCR_REMOTE) and not busy, an archive.org or Gale read's
request is made here as its unit starts (prepare: file_archive_org_puzzles.brief,
this process's ledger, scans and corpus already loaded), and its unit is
tools/edition_commit.py's: it loads only its MODULES (under the same lock),
sends the request, waits and commits what the desktop decided; any other
outcome runs the whole unit in its place.
A fetch unit loads only its source's module and that module's MODULES
(FETCH_UNITS; under the same lock), what its fetch_unit reaches.
"""
import argparse
import datetime
import functools
import hashlib
import itertools
import importlib
import importlib.util
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent


def snapshot():
    """Hold the tree's code still (a shared flock on <git dir>/code.lock,
    which durable_resync takes alone to move the tree) and return the lock's
    fd, or None outside a git tree. Found held, the tree is moving: wait it
    out and re-exec, since what this process read already may be the old."""
    import fcntl
    try:
        path = subprocess.run(["git", "-C", str(TOOLS), "rev-parse", "--path-format=absolute", "--git-path",
                               "code.lock"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        fcntl.flock(fd, fcntl.LOCK_SH)
        os.execv(sys.executable, [sys.executable, *sys.argv])
    return fd


def unit_title(unit):
    """A unit's command line in ps: its kind, paper (or fetch source) and
    edition, article or file, not the queue's."""
    return f"edition_queue.py unit {unit['kind']} {unit['paper']} {unit['rel']}"


#: The address space (MB) each unit may hold (RLIMIT_AS, inherited by its
#: tesseract and other children): a unit at ~360 MB, a runaway one (the
#: 363 MP Gale page of 2013-12-17, 11.8 GB) fails itself with a MemoryError
#: (unit_status: a failure naming the ceiling) instead of starving the host.
UNIT_MEMORY_MB = int(os.environ.get("CT_UNIT_MEMORY_MB") or 6144)


def cap_memory(mb=None):
    """In the unit's own process: hold it to `mb` (UNIT_MEMORY_MB) MB of
    address space, hard, so it cannot raise it again."""
    import resource
    n = (mb or UNIT_MEMORY_MB) << 20
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    n = n if hard == resource.RLIM_INFINITY else min(n, hard)
    resource.setrlimit(resource.RLIMIT_AS, (n, n))


def memory_failure(unit, e):
    """The failure a unit's MemoryError is logged as: the ceiling named."""
    import scan_queue
    why = MemoryError(f"{unit['kind']} {unit['rel']} hit its memory ceiling "
                      f"({UNIT_MEMORY_MB} MB address space, RLIMIT_AS): {e}")
    why.__cause__ = e
    return scan_queue.failure((unit["rel"],), why)


def titled():
    """Whether units can name themselves (setproctitle is installed)."""
    return importlib.util.find_spec("setproctitle") is not None


def vlm_deferral(e):
    """The log words for a unit deferred by VLM error `e`: its asks spooled, or the VLM down."""
    import vlm_reader
    if vlm_reader.cause() == "spooled":
        return f"deferred, {len(vlm_reader.spooled_by(os.getpid()))} VLM asks spooled"
    if vlm_reader.cause() == "spool full":
        return "deferred: VLM spool full"
    return f"deferred, the VLM is down ({e})"


def unit_status(unit, run):
    """In the unit's own process: name it after `unit`, run() it and return
    its exit status (EXITS; 1 for an error, logged; "deferred" when its
    desktop reads met a busy desktop and it defers, ocr_remote.DEFER; "lost"
    when the desktop stopped answering them, ocr_remote.DesktopLost)."""
    import edition_commit
    import ocr_remote
    import scan_queue
    if titled():
        import setproctitle
        setproctitle.setproctitle(unit_title(unit))
    try:
        return edition_commit.EXITS.get(run(), 1)
    except ocr_remote.DesktopLost as e:
        print(f"{unit['kind']} {unit['rel']}: deferred, the desktop was lost ({e})", file=sys.stderr, flush=True)
        return edition_commit.EXITS["lost"]
    except ocr_remote.DesktopBusy as e:
        print(f"{unit['kind']} {unit['rel']}: deferred, the desktop is busy ({e})", file=sys.stderr, flush=True)
        return edition_commit.EXITS["deferred"]
    except MemoryError as e:  # past UNIT_MEMORY_MB: a failure, its cause named
        memory_failure(unit, e)
        return 1
    except Exception as e:  # any raise: the unit's end is its exit status, logged
        if scan_queue.vlm_down(e):
            print(f"{unit['kind']} {unit['rel']}: {vlm_deferral(e)}", file=sys.stderr, flush=True)
            return edition_commit.EXITS["vlm"]
        if media_deferral(unit, e):
            return edition_commit.EXITS["media"]
        scan_queue.failure((unit["rel"],), e)
        return 1


def media_deferral(unit, e):
    """In the unit's own process: whether error `e` is the media share not answering
    (downloads.media_down); then say the unit ends deferred, retried once it answers."""
    import downloads
    if not downloads.media_down(e):
        return False
    print(f"{unit['kind']} {unit['rel']}: deferred, the media share is down ({type(e).__name__}: {e})",
          file=sys.stderr, flush=True)
    return True


#: Each fetch source's module and how its unit runs there. A fetch unit
#: loads only that module and its MODULES (what its fetch_unit reaches), not
#: the queue's filers: it is network work, started 30-70 times a minute.
FETCH_UNITS = {"archive.org": ("fetch_archive_org_editions", lambda m, u: m.fetch_unit(m.downloads.ARCHIVE_ORG, u)),
               "trove": ("fetch_trove", lambda m, u: m.fetch_unit(u))}


def load_fetcher(source):
    """Import fetch `source`'s module, its MODULES and what unit_status
    uses (a fetch unit's start, under the code lock); return the module."""
    module = importlib.import_module(FETCH_UNITS[source][0])
    for name in (*module.MODULES, "downloads", "edition_commit", "scan_queue"):
        importlib.import_module(name)
    return module


#: Each paper's module, whose read_unit (and scan_unit) its units run;
#: any other paper's is UNIT_MODULES[None], the archive.org and Gale filer.
UNIT_MODULES = {"trove": "file_trove_puzzles", "listener": "gale_listener", None: "file_archive_org_puzzles"}


def unit_module(paper):
    return importlib.import_module(UNIT_MODULES.get(paper, UNIT_MODULES[None]))


#: Scans at once: exactly one. A scan is CPU-bound OCR (on this host when the
#: desktop is off, and Gale pages always), and OCR runs as ONE process pinned
#: to one core at nice 19 (env OCR_SCAN_CPU, pin_scan); ten at once held this host's
#: load at 30+ on 6 cores. dispatch() caps any --scan-workers at this, or at
#: env CT_SCAN_WORKERS (scan_cap) when that is higher. (Above pin_scan: a unit
#: process runs it before the rest of this module is defined.)
SCAN_WORKERS = 1


def scan_cap():
    """The most scans at once: SCAN_WORKERS, or env CT_SCAN_WORKERS when it is a
    whole number above that (anything else is ignored)."""
    try:
        return max(SCAN_WORKERS, int(os.environ.get("CT_SCAN_WORKERS", "")))
    except ValueError:
        return SCAN_WORKERS


SCAN_CPU_LOCKS = []  # open lock files of the cores this process holds (kept for its life)


def spread_cpu(cpus):
    """The core for a scan when CT_SCAN_WORKERS allows several at once: the
    last one no other scan holds (an flock on a file per core in the temp
    dir, held while this process lives), else one by pid."""
    import fcntl
    import tempfile
    for cpu in reversed(cpus):
        fd = os.open(os.path.join(tempfile.gettempdir(), f"ct_scan_cpu_{cpu}.lock"), os.O_CREAT | os.O_RDWR, 0o666)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            continue
        SCAN_CPU_LOCKS.append(fd)
        return cpu
    return cpus[os.getpid() % len(cpus)]


def pin_scan():
    """The standing OCR rule in the scan's own process: one core (SCAN_CPU,
    the last by default; with CT_SCAN_WORKERS above 1 and no OCR_SCAN_CPU, a
    core of its own, spread_cpu), nice 19, one thread (OMP_NUM_THREADS, OCR_THREADS)."""
    os.environ["OMP_NUM_THREADS"] = os.environ["OCR_THREADS"] = "1"
    try:
        cpus = sorted(os.sched_getaffinity(0))
        if scan_cap() > 1 and "OCR_SCAN_CPU" not in os.environ:
            cpu = spread_cpu(cpus)
        else:
            cpu = cpus[int(os.environ.get("OCR_SCAN_CPU", "-1"))]
        os.sched_setaffinity(0, {cpu})
        os.nice(19)
    except (AttributeError, IndexError, OSError):
        pass  # no affinity here (macOS): nice and one thread still hold


def run_unit(unit, cache, puzzles, reread):
    """In the unit's process: its outcome (EXITS). A scan's desktop
    sessions run above the reads' (ocr_remote.PRIORITIES): a read waits on
    the scans its solution needs, so a starved scan holds up reads too."""
    if unit["kind"] == "scan":
        os.environ["OCR_REMOTE_PRIORITY"] = "scan"
        pin_scan()
    m = unit_module(unit["paper"])
    if unit["paper"] == "trove":
        return m.read_unit(unit["rel"], puzzles=None, reread=reread, force=unit.get("force"))
    if unit["paper"] == "listener":
        return m.read_unit(unit["rel"])
    paper = m.FILERS[unit["paper"]]
    if unit["kind"] == "scan":
        # A solution host is wanted for the solutions it prints: its solution bands alone are read.
        # (A unit process never imports fa: it exits before the queue's own imports.)
        return m.scan_unit(paper, unit["rel"], cache, host=unit.get("reason") in getattr(m, "HOST_REASONS", ()))
    return m.read_unit(paper, unit["rel"], cache, puzzles=puzzles, reread=reread, force=unit.get("force"),
                       also=unit.get("batch") or ())


def unit_main(spec):
    """In the unit's own process: run `spec` (CT_EDITION_UNIT: the unit and
    the queue's cache, puzzles and reread) and return its exit status
    (EXITS; 1 for an error, logged)."""
    import scan_queue
    unit = spec["unit"]
    return unit_status(unit, lambda: run_unit(unit, Path(spec["cache"]), spec["puzzles"] and Path(spec["puzzles"]),
                                              scan_queue.when(spec["reread"])))


def load_reach(names, reach):
    """Import `names`, tools/ modules. One whose third-party package is not
    installed here (fetch_ia_book's requests) is skipped: the path that
    needs it fails when taken, not every start. A missing module of
    `reach` (the tree's) raises."""
    for name in sorted(names):
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as err:
            if (err.name or "").partition(".")[0] in reach:
                raise


def load_unit(paper):
    """Import a scan or read unit of `paper`'s module, every tools/ module
    it may load (code_reach.modules: lazy imports too) and what unit_main
    uses: the unit's start, under the code lock. Not the queue's own
    modules (the other papers' filers, the fetchers)."""
    import code_reach
    reach = code_reach.modules(UNIT_MODULES.get(paper, UNIT_MODULES[None]))
    load_reach(reach | {"downloads", "edition_commit", "ocr_remote", "scan_queue"}, reach)


_snapshot = snapshot() if __name__ == "__main__" else None
_spec = json.loads(os.environ.get("CT_EDITION_UNIT") or "{}") if sys.argv[1:2] == ["unit"] else {}
if _spec.get("unit"):
    cap_memory()
if _spec.get("unit", {}).get("kind") == "fetch":
    _fetcher = load_fetcher(_spec["unit"]["paper"])
    if _snapshot is not None:
        os.close(_snapshot)
    sys.exit(unit_status(_spec["unit"], lambda: FETCH_UNITS[_spec["unit"]["paper"]][1](_fetcher, _spec["unit"])))
if _snapshot is not None and _spec.get("brief"):
    # A read the queue prepared: its unit loads only what it commits with.
    import edition_commit
    edition_commit.load()
    os.close(_snapshot)
    try:
        import setproctitle
        setproctitle.setproctitle(f"edition_queue.py unit read {_spec['unit']['paper']} {_spec['unit']['rel']} (desktop)")
    except ImportError:
        pass
    import ocr_remote
    try:
        sys.exit(edition_commit.main(_spec))
    except ocr_remote.DesktopLost:
        sys.exit(edition_commit.EXITS["lost"])
    except ocr_remote.DesktopBusy:
        sys.exit(edition_commit.EXITS["deferred"])
    except MemoryError as e:
        memory_failure(_spec["unit"], e)
        sys.exit(1)
    except Exception as e:  # any raise: the unit's end is its exit status, logged
        import scan_queue
        if scan_queue.vlm_down(e):
            print(f"read {_spec['unit']['rel']}: {vlm_deferral(e)}", file=sys.stderr, flush=True)
            sys.exit(edition_commit.EXITS["vlm"])
        if media_deferral(_spec["unit"], e):
            sys.exit(edition_commit.EXITS["media"])
        scan_queue.failure((_spec["unit"]["rel"],), e)
        sys.exit(1)
if _spec.get("unit", {}).get("kind") in ("scan", "read"):
    load_unit(_spec["unit"]["paper"])
    if _snapshot is not None:
        os.close(_snapshot)
    sys.exit(unit_main(_spec))
# The queue's own modules: imported only past the unit dispatch above, so a
# unit's process never loads them.
import code_reach
import dir_cache
import edition_commit
import fetch_archive_org_editions as fetch_ao
import fetch_trove
import file_archive_org_puzzles as fa
import file_trove_puzzles as ftp
import gale_listener
import hot_reload
import media_manifest
import mem_gate
import ocr_remote
import scan_queue
import vlm_reader

#: Modules the queue process reaches only through lazy imports of the blog filers' paths (clues_only's
#: _blog_build, ft_puzzles, ...) and never runs: it starts units, it reads no blog post. Loaded, they were in
#: queue_closure, so each push touching them reloaded the queue (a replan, 55-175 s) for nothing. The units
#: that do use them are their own processes, which load their own reach (load_unit).
#: (Named inside never_loaded, not in a module-level constant: hot_reload._needs reads a module-level
#: string as a module the file loads, which would put them in the static closure.)
def never_loaded(reach, tools=None):
    """The modules of `reach` the queue process does not load: file_blog_puzzles, parse_timesforthetimes
    and each module outside the queue's own static closure (hot_reload.queue_code) that imports one at
    module level, so loading it would load them again."""
    tools = TOOLS if tools is None else Path(tools)
    names = {p.name for p in tools.iterdir() if p.suffix == ".py"}
    static = {Path(p).stem for p in hot_reload.queue_code(tools)}
    skip = {"file_blog_puzzles", "parse_timesforthetimes"}
    while True:
        more = {m for m in reach if m not in skip and m not in static
                and {Path(n).stem for n in hot_reload._needs(tools, f"{m}.py", names)} & skip}
        if not more:
            return skip & set(reach)
        skip |= more


if _snapshot is not None:
    _reach = code_reach.modules("edition_queue")
    load_reach(_reach - {"edition_queue"} - never_loaded(_reach), _reach)
    os.close(_snapshot)

#: The papers in the order a rank's units are taken; "trove" is the
#: Canberra Times articles (tools/file_trove_puzzles.py), read in a pool of
#: their own (TROVE_WORKERS) beside the editions', and "listener" the
#: Listener pages tools/gale_fetch.py downloads (tools/gale_listener.py), LISTENER_WORKERS
#: at once (this host's Tesseract, no VLM) within LISTENER_SECONDS.
PAPERS = ["gale", "listener", "times", "telegraph", "guardian", "ft",
          "galeindependent", "galesundaytimes", "galetls", "trove"]
#: Reads at once: mostly waits on the desktop (mem_gate and desktop_room
#: hold the rest back when either host is short of memory).
WORKERS = 25
TROVE_WORKERS = 6
#: Paul 10-23: the Listener ahead of FT's never-read pages. ~2,950 unread pages (Gale 1930-91, on the
#: media disk since 10-20); each unit is one page's local OCR, no VLM, so they share the unit ceiling
#: (mem_gate's controller: Windows' free RAM) with the reads but take no GPU turn. Measured on the
#: desktop 10-23 (4 at once): 0.3-0.75 GB RSS and ~1 core each, 17-19 min a page (half its read, half
#: filing: its neighbours' grids, each page's found once). 8 is a bound: the idle-core gate
#: (local_cpu) and the unit ceiling hold them back first.
LISTENER_WORKERS = int(os.environ.get("CT_LISTENER_WORKERS") or 8)
#: Paul 10-24: "Remember times is the most important". While a CT_NEWEST_FIRST paper's (the Times')
#: read or scan is due or running, the Listener pool shrinks to this many units, so its ~17-min
#: local-OCR pages (8 of a 16 ceiling) don't hold the slots Times reads and scans want.
LISTENER_BESIDE_TIMES = int(os.environ.get("CT_LISTENER_BESIDE_TIMES") or 2)
LISTENER_SECONDS = 1800
#: The core a scan unit pins itself to (-1: the host's last), OCR's one core.
SCAN_CPU = "OCR_SCAN_CPU"
#: A unit still running this long is killed and left for the next run.
def seconds_from_env(name, default):
    """Seconds from the environment variable `name`, or `default` when unset, not a number, or not above 0."""
    try:
        got = float(os.environ.get(name) or default)
    except ValueError:
        return default
    return got if got > 0 else default


#: CT_SCAN_SECONDS / CT_READ_SECONDS raise them: a read waits its turn on the one-slot VLM
#: (~7.6 requests a minute across every unit), so with many reads at once 1200s kills
#: reads that are only waiting; their cached replies (vlm_reader.ask_png) survive the kill.
SCAN_SECONDS = seconds_from_env("CT_SCAN_SECONDS", 1200)
READ_SECONDS = seconds_from_env("CT_READ_SECONDS", 1200)
#: Reads allowed to wait for the VLM at once (env CT_VLM_WAITING, default 4: the
#: slot, its pipeline and one more): at ~7 asks a puzzle the one-slot VLM finishes
#: ~1 read a minute, so ~30 started reads sat ~30 min each in its lock holding
#: ~0.5 GB apiece, past the read limit, and lost on every restart. While this many
#: processes have an ask under way (vlm_reader.waiting_now, not the queue's own drainer) no read starts
#: (spool off; spool on: see vlm_spool_max); reads OCR
#: settles without an ask never wait, so they still flow at CPU speed.
def vlm_waiting_cap():
    try:
        return max(1, int(os.environ.get("CT_VLM_WAITING", "4")))
    except ValueError:
        return 4


#: Spooled asks (vlm_reader.spooled) at which no read starts (env CT_VLM_SPOOL_MAX): at ~6.7 asks
#: a minute 200 are half an hour of the VLM's work, and each read begun past that only waits.
#: A number in ~/.cache/corpus_queue/vlm_spool_max (env CT_VLM_SPOOL_MAX_FILE) beats the env, so
#: the depth is tunable live: a deep spool adds no throughput, it only delays new code's asks.
#: Defined in vlm_reader (a read past it spools nothing and ends deferred: "spool full"); one
#: source for the reader and the queue.
def vlm_spool_max():
    return vlm_reader.vlm_spool_max()


def vlm_drainer(stop, threads):
    """The VLM stage: one thread per ask in flight (vlm_reader.slots() + PIPELINE) takes the
    oldest spooled ask (vlm_reader.drain_one), asks the server and caches the answer, so no
    read blocks on the VLM. Idle, or the VLM down (vlm_up), it waits and looks again."""
    def work():
        while not stop.is_set():
            if not (vlm_reader.spooled() and vlm_up()) or not vlm_reader.drain_one():
                stop.wait(5)
    vlm_reader.requeue_claimed()
    for _ in range(max(1, vlm_reader.slots() + max(0, vlm_reader.PIPELINE))):
        threading.Thread(target=work, daemon=True).start()
        threads.append(1)


#: How often (seconds) the queue is planned again.
REPLAN = 60
#: While no core is idle, a plan is made every REPLAN * IDLE_BACKOFF seconds
#: (5 minutes), as long as the last plan holds enough untried units to keep
#: the pools full: the planner thread's stats are CPU the burn wants.
IDLE_BACKOFF = 5
#: A plan may use at most 1/PLAN_DUTY of the wall clock: the next waits PLAN_DUTY times
#: as long as the last took (2026-10-17: plans of 29k scans and 47k reads took a median 48 s,
#: p90 280 s, max 5000 s on a host at load 28, replanned every 60-300 s, so the planner ran
#: near-continuously against the OCR it feeds). The queue is a burn of ~190 scans and ~310
#: reads an hour; a plan stale by a few minutes costs nothing.
PLAN_DUTY = 10
#: ... but never more than this many seconds.
PLAN_WAIT_MAX = 1800
#: How often (seconds) the dispatch loop looks for editions just laid out
#: (fresh): a listing of the cache and a stat of each item dir, ~0.3s.
FRESH_POLL = 30
#: How long a stop waits for the units it TERMed before it KILLs them.
STOP_GRACE = 30


GAME_DROP_EVERY = 900  # seconds between page-cache drops while a game lasts

def game_scans():
    """Scans left running while a game runs (CT_GAME_SCAN_WORKERS, 3): the rest are TERMed and left deferred."""
    try:
        return max(0, int(os.environ.get("CT_GAME_SCAN_WORKERS", "3")))
    except ValueError:
        return 3


def yield_grace():
    """Seconds the running units get to finish once the desktop yields (CT_YIELD_GRACE, 50: the game-guard drains the VLM for 60)."""
    try:
        return float(os.environ.get("CT_YIELD_GRACE", "50"))
    except ValueError:
        return 50.0
#: A unit's exit status: what read_unit/scan_unit/a fetcher's unit returned.
EXITS = edition_commit.EXITS

#: The fetch units (--fetch SOURCE): each source's plan() of units (its unit
#: runs FETCH_UNITS), how many run at once and each one's time limit. archive.org
#: throttles each connection (~100 KB/s), not the client, so its units run
#: in parallel, one connection each; an answer 429 lowers its slots by one,
#: and FETCH_OUTAGES units in a row finding it down stop its fetches for
#: the run (fetch_archive_org_editions.outage).
FETCHERS = {
    "archive.org": {"plan": lambda: fetch_ao.plan(fetch_ao.downloads.ARCHIVE_ORG), "workers": 12, "seconds": 1200},
    # Trove is asked at most once a second across every unit (fetch_trove
    # pace()); three at once overlap one's request with the others' waits.
    "trove": {"plan": lambda: fetch_trove.plan(), "workers": 3, "seconds": 900},
}
FETCH_OUTAGES = fetch_ao.FAILURES_IN_A_ROW
#: How often (seconds) a run makes each fetch source's plan again, from when
#: the last was made: archive.org's stats every done edition's dirs (minutes
#: on the media mount) and a fetch due a few minutes late costs nothing.
FETCH_REPLAN = 600


def log(line):
    print(f"{time.strftime('%H:%M:%S')} {line}", file=sys.stderr, flush=True)


def plan(papers, cache=fa.CACHE, reread=None, out=None):
    """(scan units, read units) of every paper, each list most urgent
    first: by rank, then the paper's place in `papers`, then plan's order.
    A paper whose ledger a batch run holds throughout is left out (its units
    could not add their rows)."""
    load_caches()
    try:
        # One scope for the whole plan: each series is listed and the VLM probed once, not per paper.
        with fa.held_once():
            return _plan_kept(papers, cache, reread, out)
    finally:
        # The listings are a hint for the next process (each stands only while its dir_key does), and
        # pickling them is ~1s CPU a plan: written at most every DIR_SAVE_EVERY seconds, first plan included.
        # So are the parse caches (~35 MB, rewritten on nearly every plan as puzzles are filed): each entry
        # stands only while its file's stat does, so an older snapshot costs the next process a few re-parses.
        if time.monotonic() - _DIR_SAVED[0] >= DIR_SAVE_EVERY:
            dir_cache.save(DIR_CACHE)
            fa.save_held(HELD_CACHE)
            fa.save_likely(LIKELY_CACHE)
            scan_queue.save_count_left(COUNT_LEFT_CACHE)
            _DIR_SAVED[0] = time.monotonic()


#: Seconds between plan()'s writes of DIR_CACHE, and when the last was (monotonic).
DIR_SAVE_EVERY = 600
_DIR_SAVED = [float("-inf")]


def load_caches():
    """Take what the last process's plan() saved (DIR_CACHE, HELD_CACHE,
    LIKELY_CACHE, COUNT_LEFT_CACHE), once a process: plan() and prepare()
    call it, as a re-exec starts units from the last plan whose briefs would
    else parse every filed puzzle (held_files) before its first plan loads
    them."""
    with _LOAD_LOCK:
        if not _LOADED:
            dir_cache.load(DIR_CACHE)
            fa.load_held(HELD_CACHE)
            fa.load_likely(LIKELY_CACHE)
            scan_queue.load_count_left(COUNT_LEFT_CACHE)
            _LOADED.append(True)


_LOAD_LOCK = threading.Lock()


#: Where plan() keeps the edition and article dirs' listings between
#: processes (dir_cache.save): a slice or a re-exec starts warm, not with a
#: stat of every file on the media mount.
DIR_CACHE = Path(os.path.expanduser("~/.cache/corpus_queue/dir_cache.pickle"))
#: Where plan() keeps held_files' parse of each filed puzzle between
#: processes (fa.save_held), so a re-exec does not parse the corpus again.
HELD_CACHE = Path(os.path.expanduser("~/.cache/corpus_queue/held_files.pickle"))
#: Where plan() keeps what fa.likely read between processes: the solution
#: headings in each edition's archive.org text, each filed puzzle's state.
LIKELY_CACHE = Path(os.path.expanduser("~/.cache/corpus_queue/likely.pickle"))
#: Where plan() keeps scan_queue.count_left_requests' verdict on each filed
#: puzzle between processes, so a re-exec's first plan parses only the files
#: that moved, not ~8k (most of a minute on a loaded host).
COUNT_LEFT_CACHE = Path(os.path.expanduser("~/.cache/corpus_queue/count_left.pickle"))
#: Non-empty once this process has loaded DIR_CACHE and HELD_CACHE: later
#: plans hold everything those had, so they are read once a process.
_LOADED = []


#: The last whole plan (see _plan_kept): {"key", "stamps", "extra", "made", "out", "notes"}.
_QUEUE = {}


#: {(paper key, source): what the open requests said} as _asked last saw them:
#: the puzzle and the checks that met a misread, for the "annotation asked" log line.
_ASKED_WHY = {}


def _ask_detail(req):
    return f"puzzle {req.get('id')}: {', '.join(req.get('why') or ())}"[:200]


def _asked():
    """{paper key: {source}} the annotation asked to have read again."""
    asked = {}
    why = {}
    try:
        for req in scan_queue.all_open_requests():
            if req["filer"] == "archive":
                p = fa.filer_of(req["source"])
                if p is not None:
                    asked.setdefault(p.key, set()).add(req["source"])
                    why.setdefault((p.key, req["source"]), []).append(_ask_detail(req))
            elif req["filer"] == "trove":
                asked.setdefault("trove", set()).add(req["source"])
                why.setdefault(("trove", req["source"]), []).append(_ask_detail(req))
    except (OSError, ValueError) as e:
        log(f"the annotation re-read requests did not load ({type(e).__name__}: {e}); planned without them")
    _ASKED_WHY.clear()
    _ASKED_WHY.update({k: "; ".join(v)[:300] for k, v in why.items()})
    return asked


#: The reasons a reread or rescan is planned for: a puzzle never read or
#: scanned, laid out just now, or with concrete evidence of a bug (the
#: annotation asked, a refusal whose fix landed since). The rest are blanket:
#: "inputs changed", "titles changed", "scan stale*", "--reread", "read by
#: another VLM", "read without the VLM", "solution moved", "solution short, read
#: by other code", "short Times page, its third clue column read since" and the
#: listener's "version changed" flag no puzzle in particular, so they are not
#: planned unless CT_BLANKET_REREADS=1 (the old behaviour).
def evidence_reason(reason):
    return (reason in ("never read", "never scanned", "never read (Gale fetch)", "just laid out", "annotation asked",
                       fa.UNCONFIGURED_READ)  # read OCR-only by accident (the VLM URL empty): as good as unread
            or (reason.startswith("refused ") and reason.endswith(" before its fix"))
            or reason == fa.NO_TITLE_RESCAN  # a Gale 1957-62 or 2000-14 page no title was found on, scan code since
            or reason == "unfiled before its fix"  # a puzzle written with blank clues, a column-layout fix since
            # A 2000-14 Times page written unfiled before the 10-25 clue-11 and cut-window fixes (fa.unfiled_modern).
            or reason == fa.UNFILED_MODERN
            # A puzzle its read wrote that the corpus no longer holds (fa.lost_writes): as good as unread.
            or reason == fa.LOST_WRITE
            # A title its scan found whose read gave no verdict, its puzzle unheld (fa.unread_titles): unread.
            or reason == fa.UNREAD_TITLES
            # A held 2005-06 Gale Times page whose clue window ran into the box beside DOWN, read before
            # right_foreign() cut it at the gutter (fa.right_foreign_held): once.
            or reason == fa.RIGHT_FOREIGN_READ
            # A held puzzle whose solution grid read 3+ lights short before unlisted_reads (Paul 10-24: every
            # short grid current code may improve, once); no likely gain, so after the 1-2-short ones.
            or reason == fa.SHORT_WIDE
            # A held puzzle whose grid read 1-2 lights short since unlisted_reads, before the VLM's unlisted
            # strip words stood (fa.unlisted_word): likely() predicts it nothing, so this keeps it, once.
            or reason == fa.VLM_UNLISTED
            # A held puzzle whose linked solution grid was refused (its blocks, or its ink's size) before
            # read_solution looked for it by its blocks (matched_box), once. likely() predicts nothing for
            # a refused grid, so without this only_evidence dropped every one: Paul 10-24, ~650 Times
            # puzzles held short (1980s ~250, 1990s ~115, 1970s ~105) stood so, none planned.
            or reason == fa.REFUSED_GRID
            # A held puzzle whose grid read short at blocks just under SURE_BLOCKS (a heavy print's inked
            # letters read as blocks) before the classifier read such grids (fa.heavy_short), once.
            or reason == fa.HEAVY_PRINT
            # A held file with a suspect clue whose answers-only reading went to --out (fa.suspect_held), once.
            or reason == fa.SUSPECT_HELD
            # The other two answers_only rereads likely() predicts nothing for: a grid older code read short
            # (cells unclassified) for a puzzle held short from its page that short_again passes over (its
            # blocks under SURE_BLOCKS), and a held puzzle with a clue filed without its count. Paul 10-24:
            # ~670 and ~275 Times puzzles held every clue short of answers so, none planned. Each once: a
            # reread writes this solution_key; unenumerated_held wants a read before REREAD_UNENUMERATED.
            # Plain "solution short, its cells unclassified" (no puzzle answers_only can read) stays out.
            or reason in (fa.UNCLASSIFIED_HELD, "answers held back by a clue with no enumeration")
            # A page whose scan finds no title while the puzzle filed from it waits on its answers
            # (fa.held_titles: Paul 10-25, ~240 Times puzzles a host's heading names): answers-only, once.
            or reason == fa.HELD_TITLE
            or reason.endswith(" cured since"))  # trove: the fix for the cause a read was refused for landed


#: Paul 10-22: ~1,500 Gale Times 2000-14 editions had no puzzle filed. 2007's 312 (each read once on 10-12,
#: ~10 down clues blank: the third clue column under the grid) were never reread: their reason is the blanket
#: "short Times page, its third clue column read since", which only_evidence dropped, and the 2008-13 pages
#: the same fix reread (10-18) no longer leave that column blank. Also ~270 pages of 2006-11 whose rescan
#: found a title the read never covered ("titles changed", no verdict: a puzzle never read). Each is concrete
#: evidence of a page that can file, so planned, for the years named here (widen them as each is read).
THREE_COLUMNS = fa.THREE_COLUMNS
THREE_COLUMNS_YEARS = fa.THREE_COLUMNS_YEARS
#: The Gale Times years whose "titles changed" rereads (a title no verdict covers) are planned.
NEW_TITLE_YEARS = (2000, 2014)
#: ...except these: Paul 10-22, of the ~86 2005-06 rereads started 08:23-09:30, every 2005 one (17) filed nothing and
#: every 2006 one that wrote only rewrote a puzzle already filed (the old scan's titles were false).
NEW_TITLE_SKIP_YEARS = (2005, 2006)


def year_evidence(unit):
    """Whether `unit` is a Gale Times reread planned for the page's own evidence (see THREE_COLUMNS):
    a short third-column page of THREE_COLUMNS_YEARS, or a "titles changed" one of NEW_TITLE_YEARS."""
    year = (unit.get("date") or "")[:4]
    if unit.get("paper") != "gale" or not year.isdigit():
        return False
    reason = unit.get("reason")
    if reason == THREE_COLUMNS:
        return THREE_COLUMNS_YEARS[0] <= int(year) <= THREE_COLUMNS_YEARS[1]
    return (reason == "titles changed" and NEW_TITLE_YEARS[0] <= int(year) <= NEW_TITLE_YEARS[1]
            and int(year) not in NEW_TITLE_SKIP_YEARS)


def blanket_rereads():
    return os.environ.get("CT_BLANKET_REREADS", "") not in ("", "0")


def only_evidence(paper, scans, reads, out=None):
    """`scans`, `reads` (fa.plan's units of one paper) without the blanket
    rereads, each kept read carrying "detail" (the puzzle and what the
    annotation or the refusal said); a scan stays when it is a first scan or a
    kept read waits on it."""
    # A read fa.likely() predicts to file a puzzle whole (e.g. "answers linked": a scan now links the
    # printed solution of a puzzle filed without answers) is evidence too. Paul 10-21: filling the
    # Times answers printed in the papers takes priority over the other papers.
    reads = [u for u in reads if evidence_reason(u["reason"]) or year_evidence(u) or fa.likely_gain(u) > 0]
    # Paul 10-21: "The goal is to get the solutions to the puzzles that have all their clues already in
    # hand but no solutions." The Times scans kept for that are fa.HOST_SCAN's alone (planned by
    # fa.solution_hosts: the one issue printing such a puzzle's solution, OCR with no VLM ask); once
    # one links the heading the puzzle's read is due with "answers linked" likely (answers_only, 0
    # asks), which is evidence above. No scan of a read's own edition or the week after it is kept for
    # a Times read (it was cd3554e547d's, ~10,000 rescans).
    times = getattr(fa.FILERS.get(paper), "series", None) == fa.SERIES
    for u in reads:
        if year_evidence(u) and not u.get("detail"):
            u["detail"] = "a title no read covered" if u["reason"] == "titles changed" else "clues short of lights"
        if not evidence_reason(u["reason"]) and not u.get("detail"):
            u["detail"] = ", ".join(f"{k} x{n}" for k, n in sorted((u.get("likely") or {}).items()))
        if u["reason"] == "annotation asked" and not u.get("detail"):
            u["detail"] = _ASKED_WHY.get((paper, u["rel"]), "")
    # Paul 10-22: the stale full scans of the editions in the week after a Times or Gale Times read
    # (its "needs" beyond its own page) were ~1,340 of the queue's 2,647 scans. A read needs its own
    # page scanned (prepare: SCAN_FIRST) and nothing else to file its puzzle; where the printed solution
    # is, is a HOST_SCAN's business once the puzzle is filed with every clue and no answers.
    if times:
        needed = {u["rel"] for u in reads if u["reason"] not in fa.STALE_SCAN and u["rel"] in (u.get("needs") or ())}
        week = {rel for u in reads if u["reason"] not in fa.STALE_SCAN for rel in u.get("needs") or ()} - needed
    else:
        needed = {rel for u in reads for rel in u.get("needs") or ()}
        week = set()
    gated = [u for u in scans if u["reason"] == "scan stale" and u["rel"] in week]
    scans = [u for u in scans if u["reason"] in ("never scanned", *fa.HOST_REASONS) or u["rel"] in needed]
    # The scans a year_evidence read waits on go with it (a "scan stale" scan is tier 2, so those reads, tier 1,
    # waited behind every other unit for the scan they need: 2007's 312 pages stood unread for that).
    fixed = {rel for u in reads if year_evidence(u) or u["reason"] == fa.NO_TITLE_RESCAN for rel in u.get("needs") or ()}
    scans = [{**u, "fix": True} if u["rel"] in fixed and u["reason"] == "scan stale" else u for u in scans]
    if gated and out is not None:
        out.append(f"{paper}: left out {len(gated)} stale scans of editions only in the week after a kept read "
                   f"(its own page's scan is kept; a solution host's is planned by fa.solution_hosts)")
    return scans, reads


def plan_inputs(papers, cache, reread, asked):
    """(key, stamps, extra): what a plan of `papers` is made of, each cheap to
    read (stats, one listing per series, one VLM probe). `key` is the request
    (papers, cache, reread, CT_NEWEST_FIRST); `stamps` each archive paper's
    fa.plan_stamp and whether a run holds its ledger (None for any: not told
    cheaply, as off the media disk); `extra` the Listener's and Trove's units
    (small, and Trove's kept for TROVE_REPLAN seconds on their own)."""
    key = (tuple(papers), str(cache), reread, tuple(sorted(newest_first_papers())), blanket_rereads())
    stamps = {}
    for k in papers:
        if k in ("listener", "trove"):
            continue
        paper = fa.FILERS[k]
        stamp = fa.plan_stamp(paper, cache, reread, asked.get(k, ()))
        stamps[k] = None if stamp is None else (stamp, bool(scan_queue.held(fa.ledger_of(cache, paper))))
    extra = {}
    if "listener" in papers:
        extra["listener"] = gale_listener.plan()
    if "trove" in papers:
        led = media_manifest.trove_ledger(ftp.CACHE)
        extra["trove"] = (bool(scan_queue.held(led)), None if scan_queue.held(led) else trove_plan(reread, asked.get("trove", ())))
    return key, stamps, extra


def _plan_kept(papers, cache, reread, out):
    """_plan's answer, the last whole plan's lists themselves while nothing it
    is made of moved (plan_inputs equal, and under fa.PLAN_REUSE seconds old,
    fa's own backstop): the queue is built once and consumed (dispatch drops
    each unit it has tried), not derived again each tick. Any input moving
    (a ledger row, a new scan or fetch, filed puzzles, the scan code, the
    VLM, the request, CT_NEWEST_FIRST) derives it again, whole, as before:
    each paper through fa's own per-paper memo, so only what moved is worked
    out."""
    asked = _asked()
    key, stamps, extra = plan_inputs(papers, cache, reread, asked)
    last = _QUEUE.get("last")
    if (last is not None and last["key"] == key and None not in stamps.values() and last["stamps"] == stamps
            and last["extra"] == extra and time.monotonic() - last["made"] < fa.PLAN_REUSE):
        if out is not None:
            out.extend(last["notes"])
        return last["result"]
    notes = []
    result = _plan(papers, cache, reread, notes, asked)
    if out is not None:
        out.extend(notes)
    # Notes about a slow plan describe that plan, not the one that reuses it.
    _QUEUE["last"] = {"key": key, "stamps": stamps, "extra": extra, "made": time.monotonic(), "result": result,
                      "notes": [n for n in notes if not n.startswith("slow plan")]}
    return result


def _plan(papers, cache, reread, out, asked=None):
    asked = _asked() if asked is None else asked
    scans, reads = [], []
    blanket = blanket_rereads()
    if vlm_reader.unconfigured() and out is not None:
        out.append(f"VLM NOT CONFIGURED: {vlm_reader.UNCONFIGURED}; treated as VLM down, "
                   "reads that need it wait (an explicitly empty VLM_READER_URL is the OCR-only opt-out)")
    began, took = time.monotonic(), {}
    for k, key in enumerate(papers):
        took[key] = time.monotonic()
        if key == "listener":
            reads += [(u["rank"], k, n, {**u, "kind": "read", "paper": "listener"})
                      for n, u in enumerate(gale_listener.plan()) if blanket or evidence_reason(u["reason"])]
            continue
        if key == "trove":
            led = media_manifest.trove_ledger(ftp.CACHE)
            if scan_queue.held(led):
                if out is not None:
                    out.append(f"trove: a run holds {led.with_suffix('.lock')}; left out")
                continue
            _, tr = (None, trove_plan(reread, asked.get("trove", ())))
            if not blanket:
                _, tr = only_evidence("trove", [], tr)
            reads += [(u["rank"], k, n, u) for n, u in enumerate(tr)]
            continue
        paper = fa.FILERS[key]
        if scan_queue.held(fa.ledger_of(cache, paper)):
            if out is not None:
                out.append(f"{key}: a run holds {fa.ledger_of(cache, paper).with_suffix('.lock')}; left out")
            continue
        sc, rd = fa.plan(paper, cache, reread=reread, asked=asked.get(key, ()))
        if not blanket:
            sc, rd = only_evidence(key, sc, rd, out)
        scans += [(u["rank"], k, n, u) for n, u in enumerate(sc)]
        reads += [(u["rank"], k, n, u) for n, u in enumerate(rd)]
    scans, reads = hold_refusal_rereads(scans, reads, out)
    scans, reads = hold_low_yield_eras(scans, reads, out)
    ended = time.monotonic()
    if out is not None and ended - began >= SLOW_PLAN:
        out.append(slow_plan_note(took, ended, began))
    return by_urgency(scans, serves=solution_needs(t[3] for t in reads)), by_urgency(reads)


def solution_needs(reads):
    """The (paper, rel) of every edition a newest-first paper's solution read (times_solution_work)
    waits on: its own and its needs. by_urgency puts the scans of these first with that work: on 10-24
    3,528 such rereads waited on their own stale scan, 3,385 of those scans past 5,000 in the scan list."""
    named = newest_first_papers()
    return {(u["paper"], rel) for u in reads if u.get("paper") in named and times_solution_work(u)
            for rel in [u["rel"], *(u.get("needs") or ())]}


#: Reasons of a puzzle never read or scanned: new work, filed before any refusal is read again.
NEW_WORK = ("never read", "never scanned", "never read (Gale fetch)", "just laid out")


def refusal_reread(reason):
    return (reason.endswith(" cured since") or reason in FIX_LANDED
            or (reason.startswith("refused ") and reason.endswith(" before its fix")))


#: Refusal rereads whose cause a 10-PAGE CANARY proved fixed: they skip the hold below and
#: are ordered (by_urgency) right after the never-read units of the CT_NEWEST_FIRST papers,
#: alongside other papers' never-read work, ahead of every other reread. One tuple per case:
#: (paper key, refusal cause as in "refused <cause> before its fix", first year, last year, note).
#: RULE: add a line only after a 10-page canary of that cause and era was read with the
#: current code and mostly parsed; the note records the date and the canary's result.
CANARY_PROVEN = (
    ("gale", "no-reading-parses", 1960, 1966, "10-18 canary: 20 of 22 sample pages parsed"),
    ("gale", "no-reading-parses", 2005, 2006, "10-18 canary: 20 of 22 sample pages parsed"),
    # cause "unfiled" is the reason "unfiled before its fix" (a page written with blank clues).
    ("gale", "unfiled", 2005, 2006, "10-20 canary: 8 of 10 Dec 2005 pages read complete, 0 uncached VLM asks"),
    ("ft", "unfiled", 1986, 1986, "10-20 canary: 4 of 5 pages read complete, 0 uncached VLM asks"),
    ("gale", "no-reading-parses", 1950, 1959, "10-21 canary: 8 of 9 1950s pages parsed from OCR alone (was 0 of 6), 0 VLM asks"),
    ("gale", "unfiled", 1950, 1959, "10-21 canary: 8 of 10 one-blank 1950s pages read complete from OCR alone (was 0 of 10), 4 of 4 filed pages still complete"),
    # Since 10-24 unfiled_blank leaves out a puzzle already filed with every clue, so these are pages never filed.
    ("gale", "unfiled", 1945, 1949, "10-24 canary: 3 of 8 never-filed 1945-48 pages filed whole (was 0), blanks 32 -> 5 "
                                    "on the 6 written, 1 refused, 1 found nothing; 51 live rereads since 10-22: blanks 366 -> 24"),
)


#: Refusal rereads that a canary or live reading showed still fail: held even for the
#: CT_NEWEST_FIRST papers, until the cause is fixed. Same tuple shape as CANARY_PROVEN.
CANARY_FAILED = (
    # Paul 10-21: "Why are we rereading times when all we want is their solutions": these reread the
    # clue pages, and live they rewrote the same blanks (~350 writes an hour, 5 new filings).
    # 10-24: most were puzzles already filed whole (now left out by unfiled_blank); a canary of 4 never-filed
    # 1974-84 pages filed 2 (times-13689, -15170), cut 1 from 8 blanks to 1, and left 1 worse (9 blanks -> 26:
    # its clues laid on no light, nothing written). Under the 10-page rule: ~116 such pages left to sample.
    ("times", "unfiled", 1785, 2100, "10-21 live: ~350 writes/h made 5 new filings; 10-24 canary 2 of 4 filed"),
    ("gale", "unfiled", 1785, 1944, "10-20 canary: 1 of 3 1945-49 pages with blanks improved (1945-49 proven 10-24)"),
)


def canary_failed(unit):
    """The CANARY_FAILED note of a refusal reread `unit`, or None."""
    return canary_match(unit, CANARY_FAILED)


def canary_proven(unit):
    """The CANARY_PROVEN note of a refusal reread `unit`, or None."""
    return canary_match(unit, CANARY_PROVEN)


def canary_match(unit, table):
    reason, year = unit.get("reason") or "", (unit.get("date") or "")[:4]
    if not year.isdigit():
        return None
    for paper, cause, first, last, note in table:
        # A cause naming its whole reason (one with a space: fa.UNFILED_MODERN) is that reason.
        want = "unfiled before its fix" if cause == "unfiled" else cause if " " in cause else f"refused {cause} before its fix"
        if (unit.get("paper") == paper and reason == want
                and first <= int(year) <= last):
            return note
    return None


def refusal_rereads_wanted():
    return os.environ.get("CT_REFUSAL_REREADS", "") not in ("", "0")


def hold_refusal_rereads(scans, reads, out=None):
    """(scans, reads) (_plan's (rank, k, n, unit) tuples) without the refusal
    rereads while the plan holds any never-read or never-scanned unit: they
    spend the one-slot VLM that new puzzles wait for. "annotation asked"
    rereads stay (concrete bug evidence), as do scans a kept read needs; a
    scan only a held read needed goes too. CT_REFUSAL_REREADS=1 keeps all.
    One note says how many were held and why."""
    new = any(u["reason"] in NEW_WORK for _, _, _, u in scans + reads)
    proven = [t for t in reads if refusal_reread(t[3]["reason"]) and canary_proven(t[3])]
    if proven and out is not None:
        for note in dict.fromkeys(canary_proven(t[3]) for t in proven):
            out.append(f"canary-proven rereads: kept {sum(canary_proven(t[3]) == note for t in proven)} ({note})")
    # CT_NEWEST_FIRST papers' refusal rereads are never held: Paul 10-21, "Read the remaining times
    # puzzles before doing ft" (their never-read pages ran out; ~1,200 rereads waited behind FT's).
    named = newest_first_papers()
    # Nor are the Listener's: read on local OCR in their own pool (LISTENER_WORKERS), they ask no VLM, so
    # holding them saved the VLM nothing. Held, its 619 pages read before the paragraph-list fixes
    # (CLUES_FIX) waited behind 2,858 never-read ones (~110 h of its pool, 10-24), and no Listener filed.
    held = [t for t in reads if refusal_reread(t[3]["reason"]) and not canary_proven(t[3])
            and t[3]["paper"] != "listener" and (t[3]["paper"] not in named or canary_failed(t[3]))]
    if not held:
        return scans, reads
    if refusal_rereads_wanted():
        if out is not None:
            out.append(f"refusal rereads: {len(held)} kept (CT_REFUSAL_REREADS=1)")
        return scans, reads
    if not new:
        if out is not None:
            out.append(f"refusal rereads: {len(held)} kept, no never-read or never-scanned unit left")
        return scans, reads
    reads = [t for t in reads if t not in held]
    kept = {(t[3]["paper"], rel) for t in reads for rel in t[3].get("needs") or ()}
    gone = {(t[3]["paper"], rel) for t in held for rel in t[3].get("needs") or ()} - kept
    before = len(scans)
    scans = [t for t in scans if t[3]["reason"] in NEW_WORK or (t[3]["paper"], t[3]["rel"]) not in gone]
    if out is not None:
        out.append(f"refusal rereads: held {len(held)} (and {before - len(scans)} scans only they needed) "
                   f"while never-read or never-scanned units remain; CT_REFUSAL_REREADS=1 restores them")
    return scans, reads


#: Trove print years whose never-read articles file rarely: measured on
#: trove-filed.jsonl (articles read, not skipped; filed = a puzzle id and no
#: refusal), 1973-1989 file 306 of 4331 reads (7.1%; per year 1973 9%, 1974 3%,
#: 1975 14%, 1976 4%, 1977 9%, 1978 0.5%, 1979 18%, 1980 14%, 1981 5%, 1982 1%,
#: 1983 19%, 1984 6%, 1985-1989 0.6-17%), the rest "zones-not-fetched" and
#: "no-grid". Every other year is above 20% (1972 39%, 1990 29%, 1992+ 32-54%);
#: 1968 and 1971 dip on 63 and 46 reads but 1967-1970 average higher, so they stay.
LOW_YIELD_YEARS = range(1973, 1990)


def low_yield_eras_held():
    return os.environ.get("CT_LOW_YIELD_ERAS", "") not in ("", "0")


def low_yield_trove(unit):
    return (unit["paper"] == "trove" and unit["reason"] in NEW_WORK
            and unit.get("date", "")[:4].isdigit() and int(unit["date"][:4]) in LOW_YIELD_YEARS)


def hold_low_yield_eras(scans, reads, out=None):
    """(scans, reads) without the never-read Trove articles of LOW_YIELD_YEARS
    while the plan holds any other never-read or never-scanned unit: they
    spend the one-slot VLM on articles that mostly refuse. Once only they
    are left they come back. CT_LOW_YIELD_ERAS=1 keeps them. One note says how many."""
    held = [t for t in reads if low_yield_trove(t[3])]
    if not held:
        return scans, reads
    if low_yield_eras_held():
        if out is not None:
            out.append(f"low-yield eras: {len(held)} kept (CT_LOW_YIELD_ERAS=1)")
        return scans, reads
    if not any(u["reason"] in NEW_WORK for _, _, _, u in scans + reads if not low_yield_trove(u)):
        if out is not None:
            out.append(f"low-yield eras: {len(held)} kept, no other never-read or never-scanned unit left")
        return scans, reads
    if out is not None:
        out.append(f"low-yield eras: held {len(held)} never-read Trove articles of {LOW_YIELD_YEARS[0]}-{LOW_YIELD_YEARS[-1]} "
                   f"(filing yield under 20%) while other never-read or never-scanned units remain; "
                   f"CT_LOW_YIELD_ERAS=1 restores them")
    return scans, [t for t in reads if t not in held]


#: A plan of the papers that takes this many seconds says, in its notes, what each paper cost.
SLOW_PLAN = 30


def slow_plan_note(starts, ended, began):
    """The note a slow plan logs: the whole in seconds and the three papers
    that took the most (a paper's span is from its start to the next's)."""
    stamps = list(starts.items())
    spans = sorted(((nxt - at, key) for (key, at), (_, nxt) in zip(stamps, [*stamps[1:], (None, ended)])), reverse=True)
    return (f"slow plan: papers took {ended - began:.0f}s; "
            + ", ".join(f"{key} {s:.0f}s" for s, key in spans[:3]))


def fresh(papers, cache=fa.CACHE, now=None):
    """(scan units, read units) of the editions of `papers` laid out in the
    last fa.FRESH seconds with no reading of their current files, each the
    latest laid out first, ranked fa.RANKS["just laid out"]; found without a
    plan, so dispatch starts them ahead of everything planned however long
    the planner takes. On the media disk the editions come off the edition
    manifests (media_manifest.edition_rows: the fetcher and gale_inbox append
    a row as they lay one out), so this 30 s tick lists and stats nothing
    there. A read needs its own scan and those of the fresh editions
    dated SOLUTION_DAYS after it (where its solution prints)."""
    now = time.time() if now is None else now
    cache = Path(cache)
    if media_manifest.on_media(cache):
        # The edition manifests' rows laid out within FRESH, never a listing.
        laid = [(row["at"], cache / rel) for rel, row in media_manifest.edition_rows().items()
                if now - row.get("at", 0) <= fa.FRESH and "/" in rel]
    else:
        laid = _laid_out_listed(cache, now)
    rank = fa.RANKS["just laid out"]
    scans, reads = [], []
    for key in papers:
        paper = fa.FILERS.get(key)
        if paper is None:
            continue
        found, rows = [], None
        for staged, d in laid:
            if not any(p.item.match(d.parent.name) for p in (paper, *paper.also)):
                continue
            rows = fa.standing(paper, cache) if rows is None else rows
            row = rows.get(f"{d.parent.name}/{d.name}") or {}
            try:
                if "inputs" not in row or row.get("filesHash") != fa.input_hash(d):
                    found.append((staged, d))
            except OSError:
                continue
        found.sort(key=lambda t: t[0], reverse=True)
        dirs = [d for _, d in found]
        planned = fa._PLANNED_DIRS.get((str(cache), key))
        known_dirs = set(planned) if planned is not None and dirs else None
        if known_dirs is not None and not set(dirs) <= known_dirs:
            # A read prepared here (brief) finds its solution among them.
            fa._PLANNED_DIRS[(str(cache), key)] = [*planned, *(d for d in dirs if d not in known_dirs)]
        rel = {d: f"{d.parent.name}/{d.name}" for d in dirs}

        def needs(d, dirs=dirs, rel=rel):
            day = fa.edition_date(d)
            after = [o for o in dirs if day and fa.edition_date(o)
                     and day < fa.edition_date(o) <= day + datetime.timedelta(days=fa.SOLUTION_DAYS)]
            return [rel[d]] + [rel[o] for o in after]
        scans += [{"kind": "scan", "paper": key, "rel": rel[d], "rank": rank, "date": fa.day_of(d),
                   "reason": "just laid out"} for d in dirs]
        reads += [{"kind": "read", "paper": key, "rel": rel[d], "rank": rank, "date": fa.day_of(d),
                   "reason": "just laid out", "needs": needs(d), "force": False} for d in dirs]
    return scans, reads


def _laid_out_listed(cache, now):
    """fresh's [(staged_at, edition dir)] laid out within fa.FRESH of a folder
    off the media disk (a test's), listed: only items moved within FRESH are
    looked in (laying an edition out renames or makes a dir in its item)."""
    try:
        names = os.listdir(cache)
    except OSError:
        return []
    out = []
    for name in names:
        try:
            if now - (cache / name).stat().st_mtime > fa.FRESH:
                continue
            editions = os.listdir(cache / name)
        except OSError:
            continue
        for e in editions:
            try:
                staged = fa.staged_at(cache / name / e)
            except OSError:
                continue
            if now - staged <= fa.FRESH:
                out.append((staged, cache / name / e))
    return out


def alternate(a, b):
    """The items of `a` and `b` taken one from each in turn, the longer's tail last."""
    out = [x for pair in zip(a, b) for x in pair]
    return out + a[len(b):] + b[len(a):]


def by_urgency(units, serves=frozenset()):
    """The units of (rank, paper's place, plan's place, unit) by rank, then
    the most puzzles predicted to file whole (fa.likely_gain), then the
    newest edition first ("date") across papers, rank 0 (never read, Gale fetch) in
    its plans' order, then the paper's place and plan's order. With
    CT_NEWEST_FIRST set (newest_first), the units of those papers come first,
    ahead of rank 0 (hand-saved pages) too, strictly newest edition first whatever their rank and
    fa.likely_gain (scans and reads alike: a read's scan is its edition's
    date too), the paper's place and plan's order breaking a tie; the rest
    keep the order above after them. Last, with CT_NEWEST_FIRST: those papers' solution work
    (times_solution_work, or a scan whose (paper, rel) is in `serves`) first of all, then their
    never-read units, then the Listener's, then the rest."""
    units = sorted(units, key=lambda t: t[1:3])
    units.sort(key=lambda t: "" if t[0] == 0 else t[3].get("date", ""), reverse=True)
    units.sort(key=lambda t: (t[0], -fa.likely_gain(t[3])))
    if newest_first_papers():
        named = newest_first_papers()
        newest = [t for t in units if t[3].get("paper") in named]
        newest.sort(key=lambda t: "9" if unproven_first(t[3]) else t[3].get("date", ""), reverse=True)
        # stable: newest first in each group; the scans of the issues printing the answers of puzzles
        # filed without them (fa.HOST_SCAN) first of the Times work (Paul 10-21: printed answers first)
        # A read whose answers a stored heading links (fa.LIKELY[0]) goes ahead of the host scans: they ran
        # all first and 663 Gale 2001-05 solution headings were linked on 10-22 with no answer filed from
        # them (each read files its puzzle's answers by OCR alone, ~110 s; a scan only links the next).
        newest.sort(key=lambda t: (files_likely_tier(t[0], t[3]),
                                   0 if t[3].get("kind") == "read" and fa.LIKELY[0] in (t[3].get("likely") or {})
                                   else 1 if t[3].get("reason") in fa.HOST_REASONS else 2))
        rest = [t for t in units if t[3].get("paper") not in named]
        # Another paper's never read/scanned units go ahead of the named papers' rereads: once the named
        # papers' new pages are read, those rereads mostly end "already held" or an update (10-18: 34 new
        # filings of 184 writes), and 3,300 never-read FT pages waited behind ~30k of them.
        # CANARY_PROVEN rereads are interleaved with that never-read work, one for one: on 10-20 the named
        # papers' new pages ran out and 3,300 FT never-read reads (most end in seconds, their scan found no
        # puzzle) went first, leaving the GPU idle while ~970 proven Times rereads waited behind them.
        proven = [t for t in units if canary_proven(t[3])]
        newest = [t for t in newest if t not in proven]
        rest = [t for t in rest if t not in proven]
        # The Listener's units go first below (by their own alternation): left in `rest` (rank 0 and 1)
        # they took the alternation's slots and moved the other papers' work among themselves. Taken out
        # here, in the order they held, the others alternate as if there were none.
        listener_units = [t for t in newest + rest if t[3].get("paper") == "listener"]
        newest = [t for t in newest if t[3].get("paper") != "listener"]
        rest = [t for t in rest if t[3].get("paper") != "listener"]
        # Paul 10-21: "Read the remaining times puzzles before doing ft": the named papers' likely filers
        # and proven rereads go before any other paper's. Their other rereads alternate one for one with
        # other papers' never-read work: on 10-21 with only those rereads left, ~350 writes an hour made
        # 5 new filings (most rewrote the same blanks) while 1,304 never-read FT pages waited.
        units = (listener_units + [t for t in newest if files_likely_tier(t[0], t[3]) == 0] + [t for t in proven if t[3].get("paper") in named]
                 + alternate([t for t in newest if files_likely_tier(t[0], t[3]) > 0],
                             alternate([t for t in rest if t[0] <= 1], [t for t in proven if t[3].get("paper") not in named]))
                 + [t for t in rest if t[0] > 1])
    # Paul 10-23: "switch from filing the FT next to doing the listener". Behind the Times' likely filers
    # (thousands) a Listener unit never met a free ceiling slot: FT reached them as the VLM's fills, which
    # a Listener read (local OCR, no VLM) never is. So the Listener's go first: its own pool
    # (LISTENER_WORKERS), the idle-core gate and the fill reserve keep them from taking more.
    # Its pages read before a reader fix alternate one for one with its never-read ones: ranked after
    # them, the 619 read short or unparsed before CLUES_FIX waited behind 2,858 (~110 h of its pool),
    # while a 10-24 canary of the near-complete ones read whole (No 2: 42 -> 43 of 43 clues) and
    # never-read pages read that day filed none.
    listener, again = [], []
    for *_, u in units:
        if u.get("paper") == "listener":
            (again if refusal_reread(u.get("reason") or "") else listener).append(u)
    listener_order = alternate(again, listener)
    others = [u for *_, u in units if u.get("paper") != "listener"]
    # Paul 10-24: "Remember times is the most important", "getting them with their solutions is highest
    # priority". The named papers' solution rereads (answers-only work, few or no VLM asks) go first of
    # all, not interleaved with any other paper's; then their never-read pages; then the Listener's; then
    # the rest in the order above. On 10-24 2,727 Listener never-read reads stood ahead of every Times
    # solution reread and ~3,300 more were alternated one for one with Telegraph never-read pages.
    # gpu_fill still picks VLM-asking reads (FT, Telegraph) out of order to keep an idle GPU busy.
    named = newest_first_papers()
    if not named:
        return listener_order + others
    solution = [u for u in others if u.get("paper") in named
                and (times_solution_work(u) or (u.get("paper"), u.get("rel")) in serves)]
    first = {id(u) for u in solution}
    new = [u for u in others if u.get("paper") in named and id(u) not in first and u.get("rank", 9) <= 1]
    first |= {id(u) for u in new}
    return solution + new + listener_order + [u for u in others if id(u) not in first]


def times_solution_work(unit):
    """Whether `unit` is solution work of a newest-first paper's puzzle: its reason one of
    TIMES_SOLUTION's (below LOW_ASK), or a read whose answers a stored heading links (fa.LIKELY[0])."""
    reason = unit.get("reason") or ""
    return (reason.startswith(TIMES_SOLUTION)
            or (unit.get("kind") == "read" and fa.LIKELY[0] in (unit.get("likely") or {})))


#: The rank 2 reasons whose last read was refused or short and a fix landed
#: since: fa.likely_gain is 0 for these (it counts only fa.LIKELY causes), yet
#: they are the rereads that can file. Other rank 2 reasons ("inputs changed",
#: "titles changed", ...) are held behind them unless likely_gain > 0.
FIX_LANDED = ("short Times page, its third clue column read since", "solution short, read by other code",
              "solution short, its cells unclassified", "read without the VLM", "unfiled before its fix",
              "titles changed", fa.NO_TITLE_RESCAN, "answers held back by a clue with no enumeration",
              fa.SHORT_UNFITTED, fa.UNMERGED, fa.UNLISTED, fa.VLM_UNLISTED, fa.SHORT_WIDE, fa.REFUSED_GRID, fa.UNCLASSIFIED_HELD,
              fa.LOST_WRITE, fa.RIGHT_FOREIGN_READ, fa.UNFILED_MODERN, fa.HEAVY_PRINT, fa.SUSPECT_HELD)


def unproven_first(unit):
    """Whether `unit` is a Gale 2000 "no title found" reread (or the scan one waits on): ordered ahead of
    the newer year_evidence units so a first batch is read and judged (the 2007 third-column rereads had
    10 of 10 filed complete on 10-22; 2000's had not run, newest-first put them after all 2007's 301)."""
    return unit.get("paper") == "gale" and (unit.get("reason") == fa.NO_TITLE_RESCAN
                                            or bool(unit.get("fix") and (unit.get("date") or "")[:4] == "2000"))


def files_likely_tier(rank, unit):
    """A newest-first paper's unit's tier: 0 for one likely to file new
    (rank 0 or 1, fa.likely_gain > 0), 1 for a reread a fix landed for (a
    refusal's or one in FIX_LANDED), 2 for any other. A refusal's reread is
    not tier 0: "a fix landed" only means code touching its cause changed,
    and on 10-18 the 1,126 Gale no-reading-parses rereads (mostly the
    2005-06 layout) held 3,300 never-read FT pages behind them."""
    reason = unit.get("reason") or ""
    if rank <= 1 or fa.likely_gain(unit) > 0:
        return 0
    # Paul 10-22: 2007's 312 short third-column pages and 2000's ~208 "no title found" ones were planned but
    # stood at reads 4,534+ of 6,222 (tier 1, alternated one for one with FT never-read work, behind ~4,500
    # older "solution short" rereads): no 2007 read had started. Each is concrete evidence of a page that
    # can file, so they (and the scans they wait on, "fix") go in the first tier with the likely filers,
    # newest first among them.
    # A puzzle its read wrote that the corpus lost (fa.LOST_WRITE) is as good as never read: its page
    # filed once, so it files again (10-25: ~1,800 Gale Times pages, 1945-2014).
    if unit.get("fix") or year_evidence(unit) or reason in (fa.NO_TITLE_RESCAN, fa.LOST_WRITE, fa.HELD_TITLE):
        return 0
    if unit.get("fix") or reason in FIX_LANDED or (reason.startswith("refused ") and reason.endswith(" before its fix")):
        return 1
    return 2


def newest_first_papers():
    """The papers CT_NEWEST_FIRST names (comma-separated keys, e.g.
    "gale,times"), read at each call so a plan after an env change follows
    it; empty when unset: the order is then by rank and fa.likely_gain."""
    return frozenset(k.strip() for k in os.environ.get("CT_NEWEST_FIRST", "").split(",") if k.strip())


def fills_gpu(unit):
    """Whether `unit` is a read that asks the VLM: another paper's never-read read, or a
    CT_NEWEST_FIRST paper's reread of a page refused or unfiled before its fix (it reads
    its clue columns again; those papers' other rereads run on OCR alone). Paul 10-21:
    Times work goes ahead of FT's, and the GPU stays busy; the plan's order puts these
    Times rereads first."""
    if unit["kind"] != "read" or not needs_vlm(unit):
        return False
    reason = unit.get("reason") or ""
    if reason.startswith(CPU_ONLY):
        return False  # answers_only: links answers, asks the VLM nothing
    if reason.startswith(LOW_ASK):
        return False  # solution rereads: minutes of CPU for 1-3 asks; they do not keep the VLM fed
    # Never-read reads of any paper, fix-landed rereads and canary-proven rereads ask the VLM.
    return (unit["rank"] <= 1 or "before its fix" in reason or reason in FIX_LANDED
            or canary_proven(unit))


#: Reasons of rereads that finish on CPU alone (answers_only, no VLM ask): they never feed the GPU.
#: fa.UNMERGED: a solution grid a full read read whole, its answers never merged; answers_only reads it
#: again whole (no light short, no strip asked) and merges them.
#: fa.HELD_TITLE: a page its scan found no title on, read answers-only under its held puzzle's number.
CPU_ONLY = ("inputs changed: answers linked", "scan stale, answers linked", fa.UNMERGED, fa.HELD_TITLE)
#: Reasons of rereads that ask the VLM only a little: a Times solution reread spends 30-250 s of CPU, spools
#: 1-3 asks (solution strips are capped at vlm_reader STRIP_MAX) and defers. Paul 10-22: with all 18 slots
#: on these the GPU sat ~27% busy (~160 asks/h of ~400) while 798 FT never-read reads waited. They keep
#: their place in the plan (Times first) but are no fill: while spooled asks are under the feed target,
#: gpu_fill's reserve holds slots for reads that do ask. Unlike CPU_ONLY they are not answers-linked
#: (no batching) and not under the cpu-only cap (they would starve behind it).
LOW_ASK = ("solution short, its cells unclassified", "solution short, read by other code",
           "answers held back by a clue with no enumeration", fa.SHORT_UNFITTED, fa.UNLISTED, fa.VLM_UNLISTED, fa.SHORT_WIDE,
           fa.REFUSED_GRID, fa.UNCLASSIFIED_HELD, fa.HEAVY_PRINT, fa.SUSPECT_HELD)
#: Reason prefixes of a newest-first paper's solution work, ordered first of all (by_urgency; Paul 10-24:
#: the Times with their solutions first): the short-solution rereads (LOW_ASK), the answers-linked and
#: unmerged ones (CPU_ONLY) and the scans of the issues printing the answers (fa.HOST_REASONS).
TIMES_SOLUTION = LOW_ASK + CPU_ONLY + fa.HOST_REASONS


def vlm_feed_reads():
    """The most gpu_fill reads running at once: CT_VLM_FEED_READS (default 8). A fill spends 100-500 s
    on OCR before its first ask and then makes only a few, so keeping the VLM fed takes many reads in
    the pipe, not just slots + PIPELINE; this cap is separate from the Times read pool."""
    try:
        return max(1, int(os.environ.get("CT_VLM_FEED_READS", "8")))
    except ValueError:
        return 8


def vlm_feed_target():
    """The asks (spooled plus VLM-needing reads in flight) the queue keeps the VLM fed with:
    CT_VLM_FEED (default 4), at least the stage's slots + PIPELINE (vlm_reader.feed_target: a read
    below it waits in-process for its spooled asks' answers rather than defer)."""
    return vlm_reader.feed_target()


def vlm_feed_scans():
    """The most scans gpu_fill keeps running for fill reads that wait on them: CT_VLM_FEED_SCANS (default 4)."""
    try:
        return max(0, int(os.environ.get("CT_VLM_FEED_SCANS", "4")))
    except ValueError:
        return 4


def gpu_fill(read_cands, tried, busy, waits, vlm_waits, spooled, full, running_fills, max_fills,
             scan_of=None, scanning=frozenset(), max_scans=0):
    """The units to start ahead of the queue's order because the VLM stage is short of asks (spooled
    below vlm_reader.slots() + PIPELINE) while CT_NEWEST_FIRST papers' OCR-only work holds the read
    pool: the next never-read reads of other papers that ask the VLM, as many as keep running fills
    (all of them, however old: each is asks still to come) under `max_fills` (the caller bounds it by
    CT_VLM_FEED_READS and the free read slots, not by Times' share of the pool). Empty with a fed VLM or
    a full spool.

    Only when no such read is ready (Paul 10-23: GPU 0% for 6+ min, all 656 FT never-read reads waiting
    on FT scans planned behind ~1,850 Gale stale scans, the Gale before-its-fix rereads on their own
    pages' stale scans) does it return the scans those fill reads wait on (`scan_of(u)`: the scan unit or
    None), in the reads' order, one per page, so that at most `max_scans` such scans run at once (a
    running scan in `scanning` that a fill read waits on counts). Ready reads always come first: on
    10-21, when a waiting read's scan was taken whenever met, 15 of ~25 feed starts were scans."""
    target = vlm_feed_target()
    if full or spooled >= target:
        return []
    left = min(max_fills - running_fills, target - spooled)
    out, waiting = [], []
    for u, k in read_cands:
        if left <= 0:
            break
        if not (fills_gpu(u) and k not in tried and k not in busy and not vlm_waits(u)):
            continue
        if not waits(u):
            out.append(u)
            left -= 1
        elif not out and scan_of is not None and max_scans > 0:
            waiting.append(u)
    if out or not waiting:
        return out
    # No fill read is ready: bring forward the scans the waiting ones need.
    feeding = {(u["paper"], u["rel"]) for u in waiting if (u["paper"], u["rel"]) in scanning}
    room = max_scans - len(feeding)
    seen = set(feeding)
    for u in waiting:
        if room <= 0:
            break
        pr = (u["paper"], u["rel"])
        if pr in seen:
            continue
        seen.add(pr)
        s = scan_of(u)
        if s is None or key_of(s) in tried or key_of(s) in busy:
            continue
        out.append(s)
        room -= 1
    return out


def cpu_only_unit(unit):
    """Whether `unit` never asks the VLM: a "scan stale" scan or an answer-linked reread."""
    reason = unit.get("reason") or ""
    if unit["kind"] == "scan":
        return reason.startswith("scan stale")
    return unit["kind"] == "read" and reason.startswith(CPU_ONLY)


#: The most answers-linked rereads of one item read in one unit process (CT_ANSWERS_BATCH; 1 turns
#: batching off). Each such read costs ~110 s wall / ~135 CPU-s, nearly all per-process setup (ledger and
#: held lists, the solution-heading index, OCR model init); in one process the 2nd-6th puzzle cost ~0 s.
ANSWERS_BATCH = max(1, int(os.environ.get("CT_ANSWERS_BATCH") or 8))
#: Seconds a batch's read limit grows by for each edition past its first (up to the larger of the
#: read limit and BATCH_LIMIT_MAX).
BATCH_EXTRA_SECONDS = 120
BATCH_LIMIT_MAX = 3600


def answers_linked(unit):
    """Whether read `unit` is due only because a solution grid is linked now (its reread is answers_only):
    its reason is one of CPU_ONLY, or its "likely" kinds (what fa.likely predicts the read files, shown
    as its detail, "answers linked x1") are all "answers linked" (the reason itself is then "inputs
    changed" or "scan stale, answers missing")."""
    if unit["kind"] != "read" or unit["paper"] not in fa.FILERS:
        return False
    if (unit.get("reason") or "").startswith(CPU_ONLY):
        return True
    kinds = set(unit.get("likely") or ()) or {k.rpartition(" x")[0] or k for k in (unit.get("detail") or "").split(", ") if k}
    return kinds == {"answers linked"}


def batch_mates(unit, cands, tried, busy, ready, size=None):
    """The reads that go with answers-linked read `unit` in its process: up to `size` - 1 (ANSWERS_BATCH) of
    `cands` ((unit, key) pairs in the queue's order) of the same paper and item (the part of the edition's
    name before the "/"), the same rank, due for the same cheap reason, not tried nor busy and for which
    `ready(unit)` holds (not waiting on a scan or the VLM). Empty for any other unit."""
    size = ANSWERS_BATCH if size is None else size
    if size <= 1 or not answers_linked(unit):
        return []
    item = unit["rel"].partition("/")[0]
    out = []
    for v, k in cands:
        if len(out) >= size - 1:
            break
        if (v["paper"] != unit["paper"] or v["rel"] == unit["rel"] or v["rank"] != unit["rank"]
                or v["rel"].partition("/")[0] != item or k in tried or k in busy or not answers_linked(v)):
            continue
        if ready(v):
            out.append(v)
    return out


def batch_mate_keys(unit):
    """The keys of the other editions read in `unit`'s process (its "batch"): none for a unit read alone."""
    return [("read", unit["paper"], r) for r in unit.get("batch") or ()]


def batch_note(unit):
    """What a log line says of the editions batched with `unit`: " (+N batched)" or nothing."""
    return f" (+{len(unit['batch'])} batched)" if unit.get("batch") else ""


def unit_limit(unit, base):
    """Seconds `unit` may run before it is killed: `base` (its kind's limit), and for a read batching
    several editions BATCH_EXTRA_SECONDS more for each past the first, never past the larger of `base`
    and BATCH_LIMIT_MAX."""
    extra = len(unit.get("batch") or ())
    if not extra or unit["kind"] != "read":
        return base
    return min(base + BATCH_EXTRA_SECONDS * extra, max(base, BATCH_LIMIT_MAX))


def newest_first(unit):
    """Whether `unit` is of a paper CT_NEWEST_FIRST names and not rank 0.
    Such a unit is never held back as a backlog's (queue's `fed`) nor as a
    whole-corpus re-read (fa.BLANKET) behind more urgent work: it is the
    most urgent there is, so its scan is not starved by ready older reads."""
    return unit["rank"] != 0 and unit["paper"] in newest_first_papers()


#: How often (seconds) the Trove articles are planned again: stat-ing
#: every article's inputs takes ~5s, and a new article is never urgent.
TROVE_REPLAN = 300
_TROVE = {}


def trove_plan(reread, asked):
    """file_trove_puzzles.plan()'s units, made again every TROVE_REPLAN
    seconds or when the annotation asks change."""
    asked = frozenset(asked)
    if _TROVE.get("asked") != asked or time.monotonic() - _TROVE.get("at", -TROVE_REPLAN) >= TROVE_REPLAN:
        units = [{**u, "kind": "read", "paper": "trove"} for u in ftp.plan(reread=reread, asked=asked)]
        _TROVE.update(asked=asked, at=time.monotonic(), units=units)
    return _TROVE["units"]


def key_of(unit):
    return unit["kind"], unit["paper"], unit["rel"]


def scan_share(ceiling, reads_due):
    """The most scans at once while reads are due: a third of the unit ceiling, at least 1.
    None when no read waits (scans keep their whole pool)."""
    return max(1, ceiling // 3) if reads_due else None


def times_scans_pending(scan_lists, tried, busy, scanned):
    """The CT_NEWEST_FIRST papers' queued scans not yet tried, running or done: each is for a read of
    those papers (only_evidence keeps no other scan), so while any is left the Times work still has
    something to start and FT may fill only the slots it cannot use. Empty with no CT_NEWEST_FIRST."""
    named = newest_first_papers()
    if not named:
        return []
    return [u for us in scan_lists for u in us
            if u["paper"] in named and key_of(u) not in tried and key_of(u) not in busy
            and (u["paper"], u["rel"]) not in scanned]


def listener_free(free_listener, other_due, ceiling_left):
    """The Listener pool's free slots this pass: its fixed pool's (LISTENER_WORKERS, `free_listener`)
    while other read or scan work is due or running (`other_due`), else every unit-ceiling slot left
    (`ceiling_left`): its units ask no VLM, so nothing else wants them. The ceiling still bounds it."""
    if other_due or ceiling_left <= 0:
        return free_listener
    return max(free_listener, ceiling_left)


def times_scan_room(pending, ready_reads, free_scan, free_read, ceiling_left):
    """How many scans may start now while the CT_NEWEST_FIRST papers' scans are `pending` (a count):
    every unit-ceiling slot but those their `ready_reads` will take (at most `free_read`), so the
    reads waiting on those scans are not left idle behind the scan share while FT reads fill the
    slots. Never fewer than `free_scan` (the pool's own room)."""
    if not pending:
        return free_scan
    return max(free_scan, min(pending, ceiling_left - min(ready_reads, free_read)))


def slot_of(unit):
    """The pool a unit runs in: "scan", "read", "trove" (its article reads)
    or its fetch source ("fetch archive.org", "fetch trove")."""
    if unit["kind"] == "fetch":
        return f"fetch {unit['paper']}"
    return unit["paper"] if unit["paper"] in ("trove", "listener") else unit["kind"]


def rels_by_paper(pairs):
    """{paper: {rel}} of (paper, rel) pairs: what read_waits tests needs against."""
    out = {}
    for p, r in pairs:
        out.setdefault(p, set()).add(r)
    return out


_NONE = frozenset()


def unchanged(old, new):
    """`old` when `new` holds the very same units in the same order, else
    `new`: dispatch keys its queue memo on the lists' ids, so a list rebuilt
    each pass to the same units (the stopped sources' fetches left out) must
    keep its id or the memo misses every pass (~25k units re-keyed)."""
    if len(old) == len(new) and all(a is b for a, b in zip(old, new)):
        return old
    return new


def unchanged_eq(old, new):
    """`old` when `new` equals it (fresh() builds new unit dicts each tick),
    else `new`: the same id-keeping as unchanged() for lists whose units are
    rebuilt equal, so queue_memo does not miss on every FRESH_POLL."""
    return old if old == new else new


def read_waits(u, scanning, unscanned, rescanned):
    """Whether read `u` waits on a scan: one it needs running, its own
    planned and not yet done, or one of a stale-scan re-read's ended since
    the plan. `scanning` and `rescanned` are rels_by_paper maps: each read's
    needs are tested in one isdisjoint, not a pair built per need (a pass
    asks it of every queued read, ~43k)."""
    p = u["paper"]
    return (not scanning.get(p, _NONE).isdisjoint(u["needs"]) or (p, u["rel"]) in unscanned
            or (u["reason"] in fa.STALE_SCAN and not rescanned.get(p, _NONE).isdisjoint(u["needs"])))


def plan_fetches(sources):
    """Every fetch source's units, each source's in its plan's order."""
    out = []
    for src in sources:
        out += [{**u, "kind": "fetch", "paper": src, "rank": 1} for u in FETCHERS[src]["plan"]()]
    return out


#: The script a unit is started as (tests swap it).
UNIT_SCRIPT = Path(__file__).resolve()


def unit_argv(unit):
    """A unit's command line: its kind, paper (or fetch source) and edition,
    article or file, also its name in ps."""
    return [sys.executable, str(UNIT_SCRIPT), "unit", unit["kind"], unit["paper"], unit["rel"]]


#: Set in the environment of an image a re-exec started (may_reexec).
REEXEC_ENV = "EDITION_QUEUE_REEXECED"


def code_files():
    """{path: sha1} of this run's own code: every loaded module under tools/
    and the script it was started as."""
    paths = {Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m, "__file__", None)}
    paths = {f for f in paths if f.parent == TOOLS}
    main_file = getattr(sys.modules.get("__main__"), "__file__", None)
    if main_file:
        paths.add(Path(main_file).resolve())
    return {f: digest(f) for f in paths}


def queue_closure():
    """The tools/ files (repo-relative) whose change reloads this queue:
    hot_reload.queue_code's, and every module this process has loaded."""
    mine = {f"tools/{f.name}" for f in code_files()}
    return hot_reload.queue_code(TOOLS) | mine


def digest(path):
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


#: Times a unit ends lost (the desktop stopped answering its reads, though it
#: answers others) before it is started with no desktop: an edition whose read
#: ends the desktop's server each time is read here, not deferred forever.
LOST_TRIES = 3

#: Where prepare() leaves each read it made for its unit (edition_commit.load_brief removes it).
BRIEFS = Path(os.environ.get("TMPDIR") or "/tmp") / "edition-briefs"


#: What prepare() returns for a read whose own scan is stale or missing: a
#: scan unit runs first, then the read is prepared for the desktop.
SCAN_FIRST = "scan first"

#: What a read's brief is while a pool thread makes it (brief_of).
PENDING = object()
#: Threads making briefs (prepare: held_files, the desktop request) beside the dispatch loop.
PREPARERS = 3
#: Seconds the loop waits for a brief it has just asked a pool thread for.
BRIEF_WAIT = 0.2
#: Seconds a made brief waits for its unit to be asked again before it is dropped.
BRIEF_KEEP = 600


def prepare(unit, cache, puzzles, reread):
    """The file of an archive.org or Gale read unit's read made here
    (file_archive_org_puzzles.brief), for its unit to send to the desktop
    and commit (tools/edition_commit.py); SCAN_FIRST when its own scan is
    stale or missing; or None: the unit runs whole, each cause logged as a
    "whole read <rel>: <why>" line (no desktop set, it is busy, not due,
    or making it failed)."""
    import desktop_busy
    import ocr_remote
    if unit["kind"] != "read" or unit["paper"] not in fa.FILERS:
        return None
    if not ocr_remote.hosts():
        return whole(unit, "no desktop (OCR_REMOTE unset)")
    why = desktop_busy.busy(ocr_remote.hosts())
    if why:
        return whole(unit, f"desktop busy ({why})")
    try:
        paper = fa.FILERS[unit["paper"]]
        load_caches()  # a re-exec's briefs start before its first plan loads them
        made = fa.brief(paper, unit["rel"], cache, puzzles=puzzles, reread=reread, force=unit.get("force"))
        if made is None:
            return whole(unit, "not due") if fa.scan_stands(paper, unit["rel"], cache) else SCAN_FIRST
        import tempfile
        BRIEFS.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(dir=BRIEFS, suffix=".brief")
        os.close(fd)
        edition_commit.save_brief(path, *made)
        return path
    except Exception as e:  # any raise: the unit runs whole and says nothing of it; the cause is logged here
        return whole(unit, f"brief failed: {scan_queue.failure((unit['rel'],), e)}")


def whole(unit, why):
    """Log why the read unit runs whole here, not prepared for the desktop (prepare returns this None)."""
    log(f"whole {unit['kind']} {unit['rel']}: {why}")


#: Each --beside run's --seconds when the queue has no --seconds of its own,
#: and how long past its --seconds it is let run before it is killed.
BESIDE_SECONDS = 3600
BESIDE_GRACE = 1200


class Beside:
    """A batch filer (one taking --seconds) run beside the units, again
    while its output says "left for the next run" and starting is allowed,
    each run given the queue's time left (or BESIDE_SECONDS) as its
    --seconds and killed BESIDE_GRACE after it. Its output goes to a file
    this loop copies to the log as it grows: no thread, so the queue's
    re-exec (code_files) leaves nothing half done."""

    def __init__(self, argv):
        self.argv, self.seconds = argv, 0
        self.proc, self.started, self.again, self.done = None, 0.0, True, False
        self.out, self.pos, self.text = None, 0, ""
        self.paused_at = None  # when a game stopped it, or None

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
                if self.paused_at is None and time.monotonic() - self.started > self.seconds + BESIDE_GRACE:
                    log(f"beside: {shlex.join(self.argv)} ran {BESIDE_GRACE}s past its --seconds; killed")
                    os.killpg(self.proc.pid, signal.SIGKILL)
                return
            self.copy()
            self.out.close()
            self.again = "left for the next run" in self.text
            log(f"beside: {shlex.join(self.argv)[:120]} ended (rc={rc})"
                + ("; it left work, so it runs again" if self.again and rc == 0 else ""))
            self.proc, self.paused_at = None, None
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
            if sig in (signal.SIGTERM, signal.SIGKILL):
                self.resume()  # a stopped group does not act on a TERM until continued
            os.killpg(self.proc.pid, sig)

    def pause(self):
        """SIGSTOP its group for a game; its --seconds clock stops with it (resume credits the time)."""
        if self.proc is not None and self.paused_at is None and self.proc.poll() is None:
            self.paused_at = time.monotonic()
            os.killpg(self.proc.pid, signal.SIGSTOP)

    def resume(self):
        if self.paused_at is not None:
            self.started += time.monotonic() - self.paused_at
            self.paused_at = None
            if self.proc is not None and self.proc.poll() is None:
                try:
                    os.killpg(self.proc.pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass


#: What the memory gate reads (tests swap it); None is mem_gate.available.
mem_gate_reader = None
#: What the CPU gate reads (tests swap it); None is mem_gate.load.
cpu_gate_reader = None
#: What the idle-core gate reads (tests swap it); None is mem_gate.idle_cores.
idle_gate_reader = None
#: What the burn-first gate reads (tests swap it); None is mem_gate.burn_state.
burn_gate_reader = None
#: Why the desktop is busy, or None (tests swap it); None is desktop_busy.busy over ocr_remote.hosts().
desktop_gate_reader = None
#: (when read, the desktop's free memory in MB), or None (tests swap it);
#: None is desktop_busy.free_mb over ocr_remote.hosts().
desktop_mem_reader = None
#: Whether the desktop's VLM answers (tests swap it); None is vlm_reader.up(),
#: asked at most every vlm_reader.UP_EVERY seconds, never once a unit.
vlm_gate_reader = None
#: Seconds a read ending deferred for the VLM (EXITS["vlm"]) holds the reads
#: that need it, whatever the last answer: the queue does not restart them on
#: an answer from before it went down.
VLM_RECHECK = 60
#: A read that has ended deferred for the VLM's asks (spooled, or the spool full) twice running
#: in a row waits DEFER_BACKOFF * 2 ** (n - 2) seconds (at most DEFER_BACKOFF_MAX) before it
#: starts again: each start redoes its OCR, and one that finds a few new asks per pass (the
#: next stage's asks need the last's answers; a spool just below its cap) burned ~4 page
#: OCR passes a restart, 20+ restarts a read (the 10-21 log).
DEFER_BACKOFF = 120
DEFER_BACKOFF_MAX = 1800
#: At most this many seconds a pass that would walk the queue as the last
#: idle one did skips it (dispatch's idle_key): the walk is the loop's CPU.
IDLE_WALK = 5
#: The dispatch loop's tick while the reads left wait for the VLM and nothing
#: runs: it checks again, but does not walk the queue every second for nothing.
VLM_IDLE = 10
#: A pass that started nothing with every slot full waits this long (cut short by a child's exit or a TERM/INT) before the
#: next: the queue walk each pass costs ~20% of a core, and nothing it reads moves faster than this
#: except a unit ending, which wakes it (adopted units, a plan's end, a gate easing: a few seconds late).
QUIET_NAP = 5
_wake = []  # [read end] of the self-pipe SIGCHLD/TERM/INT write to, made once


def nap(seconds):
    """Sleep up to `seconds`, waking at once on SIGCHLD, TERM or INT (self-pipe)."""
    import select
    if not _wake:
        r, w = os.pipe()
        os.set_blocking(r, False)
        os.set_blocking(w, False)
        signal.signal(signal.SIGCHLD, lambda *_: None)  # a handler, so the signal is delivered to the wakeup fd
        signal.set_wakeup_fd(w, warn_on_full_buffer=False)
        _wake.append(r)
    if select.select([_wake[0]], [], [], seconds)[0]:
        try:
            while os.read(_wake[0], 4096):
                pass
        except BlockingIOError:
            pass


#: While the media share is down (downloads.media_down: the Mac's SMB server refused the session
#: for a minute, 10-20 08:03 and 10-23 12:44, and the pass died), it is probed this often.
MEDIA_PROBE_EVERY = 20
#: A probe that has not answered in this many seconds found the share down (a hung SMB stat).
MEDIA_PROBE_TIMEOUT = 10
#: A unit ending deferred for the share this many times in a run while each probe found it up
#: fails instead: an errno on one path of a share that answers is that path's, not an outage.
MEDIA_TRIES = 3
#: The dispatch loop's own media error noted this many times in MEDIA_BLIP_WINDOW seconds, each
#: found answering at the first probe, is raised: a path the share refuses while it answers.
MEDIA_BLIPS = 5
MEDIA_BLIP_WINDOW = 600
#: The dispatch loop's nap between passes while the share is down (cut short by a unit's exit or a TERM).
MEDIA_NAP = 5
_media_reexec = [None, None]  # dispatch's reexec and the pids of its running units, for media_restart


def media_wait_limit():
    """Seconds the queue waits for the media share before it gives up (env CT_MEDIA_WAIT, 1800)."""
    return seconds_from_env("CT_MEDIA_WAIT", 1800)


_media_probe = [None]  # the probe thread last started (one at a time: a hung stat is not stacked)


def media_reachable(root=None, timeout=MEDIA_PROBE_TIMEOUT):
    """Whether the media share answers: a stat and a listing of `root` (downloads.ROOT) within
    `timeout` seconds, on a thread, so a hung SMB call never holds the dispatch loop."""
    import downloads
    root = root or downloads.ROOT
    if _media_probe[0] is not None and _media_probe[0].is_alive():
        return False  # the last one still hangs
    box = []

    def probe():
        try:
            os.stat(root)
            os.listdir(root)
            box.append(True)
        except OSError:
            box.append(False)
    _media_probe[0] = threading.Thread(target=probe, daemon=True, name="media probe")
    _media_probe[0].start()
    _media_probe[0].join(timeout)
    return bool(box and box[0])


class MediaGone(Exception):
    """The media share stayed down past media_wait_limit(): the queue ends nonzero."""


class MediaGate:
    """The dispatch loop's hold while the media share is down. down(e) notes an outage (a
    unit that ended deferred for it, EXITS["media"], or the loop's own error on a media
    path); hold() then probes (`probe`, media_reachable) at once and every `every` seconds,
    and while the share does not answer no unit starts: "media down: waiting" is logged
    once, "media back" when it answers again. Past `limit` seconds down, hold() raises
    MediaGone. A note the first probe finds answered is let go without a line."""

    def __init__(self, probe=None, every=None, limit=None, clock=None, say=None):
        self.probe, self.clock = probe or media_reachable, clock or time.monotonic
        self.every = MEDIA_PROBE_EVERY if every is None else every
        self.limit = media_wait_limit() if limit is None else limit
        self.say = say or log
        self.since = None  # when the outage was first noted
        self.next_probe = None
        self.waiting = False  # "media down: waiting" logged, "media back" owed
        self.why = None
        self.error = None  # the loop's own error behind the note, if any
        self.blips = []  # when a note of the loop's own error met a share that answered
        self.seen_down = False  # a probe has found the share down

    def down(self, e=None):
        """Note an outage when `e` is None (a unit's EXITS["media"]) or downloads.media_down(e);
        whether it was noted (False: `e` is no outage, raise it)."""
        import downloads
        if e is not None and not downloads.media_down(e):
            return False
        if self.since is None:
            self.since = self.clock()
            self.next_probe = self.since
        if e is not None:
            self.why = f"{type(e).__name__}: {e}"
            self.error = e
        return True

    def held(self):
        """Whether an outage is noted and not yet seen over (no probe run)."""
        return self.since is not None

    def hold(self):
        """Whether no unit may start now: probes when one is due."""
        if self.since is None:
            return False
        now = self.clock()
        if now >= self.next_probe:
            self.next_probe = now + self.every
            if self.probe():
                if self.waiting:
                    self.say(f"media back after {now - self.since:.0f}s down; units start again")
                    self.blips.clear()
                elif self.error is not None:
                    self.blips = [t for t in self.blips if now - t < MEDIA_BLIP_WINDOW] + [now]
                    if len(self.blips) >= MEDIA_BLIPS:
                        raise self.error  # the share answers, this path does not: a bug, not an outage
                self.since, self.waiting, self.why, self.error = None, False, None, None
                return False
            self.seen_down = True
            if not self.waiting:
                self.waiting = True
                self.say(f"media down: waiting ({self.why or 'a unit ended deferred for it'}); no unit starts, "
                         f"probed every {self.every:.0f}s, given up after {self.limit:.0f}s")
        if now - self.since > self.limit:
            raise MediaGone(f"the media share has been down {now - self.since:.0f}s (CT_MEDIA_WAIT {self.limit:.0f}s)")
        return True

    def wait(self, sleep=None):
        """Block until the share answers (hold() false); MediaGone past the limit."""
        sleep = sleep or (lambda s: time.sleep(s))
        while self.hold():
            sleep(max(0.0, min(self.every, self.next_probe - self.clock())))


def vlm_up():
    """Whether the VLM answers: vlm_gate_reader(), else vlm_reader.up(). False
    when no VLM address was ever configured (vlm_reader.unconfigured: it is
    down, never OCR-only by accident); True under an explicitly empty
    VLM_READER_URL (the opt-out: then the reads are made without it)."""
    if vlm_gate_reader is not None:
        return vlm_gate_reader()
    import vlm_reader
    if vlm_reader.unconfigured():
        return False
    return not vlm_reader.URL or vlm_reader.up()


def needs_vlm(unit):
    """Whether `unit` is not started while the VLM is down: an archive.org
    or Gale edition's read (its clue columns are read with the VLM). Any
    other read starts and, asking for the VLM (vlm_reader.wanted), ends
    deferred, so a Trove article that is no crossword still files; one that
    has ended deferred so waits too (dispatch's vlm_held)."""
    return unit["kind"] == "read" and unit["paper"] in fa.FILERS


#: The desktop's free memory, in MB, it keeps: its VLM (~22 GB) and OCR
#: sessions page below it, so no unit that opens a session there starts.
DESKTOP_FLOOR_MB = 4096
#: What one OCR session takes on the desktop (private MB, 0.85-1.3 GB seen).
DESKTOP_SESSION_MB = 1024
#: Seconds a free-memory reading gates starts. desktop_busy keeps the last
#: one through every probe that fails (a saturated desktop, a LAN address
#: gone), so an old low reading would hold each desktop unit back until the
#: probe answered again; past this it is no reading, and the unit tries the
#: connection (ocr_remote alerts and reads here when none works).
DESKTOP_STALE_S = 600


def load_gated(unit):
    """Whether this host's load average holds `unit` back: a fetch always; a
    scan or read only with no desktop set. With one, its OCR and searches run
    there, and whatever it would read here waits for one of ocr_remote's
    LOCAL_SLOTS, so the burn's load on this host does not idle the desktop."""
    return unit["kind"] == "fetch" or not ocr_remote.hosts()


#: The pools whose units work on this host's CPU with a desktop set: a Trove
#: article's OCR and grid search (file_trove_puzzles), the Listener's
#: Tesseract. Scans and edition reads wait on the desktop, fetches on the
#: network: those pools stay their full width.
LOCAL_POOLS = ("trove", "listener")


def local_cpu(unit):
    """Whether `unit` works on this host's CPU, so starts only while the
    cores everything else leaves idle hold one more (mem_gate.idle_room): a
    LOCAL_POOLS unit, or any scan or read with no desktop set. Its pool is
    then as wide as the idle cores, at most its fixed count; units running
    are never touched."""
    return slot_of(unit) in LOCAL_POOLS or (unit["kind"] != "fetch" and not ocr_remote.hosts())


#: The desktop address the yield probe last put first, to log a switch once.
_YIELD_VIA = [None]


def yield_hosts():
    """The ssh hosts whose busyness the queue yields to: OCR_REMOTE's, then
    any more in CT_YIELD_HOSTS (space-separated; unset or empty adds none).
    A host at one of the desktop's addresses (desktop_hosts) stands for the
    desktop: it is replaced by the desktop's every address, ranked (the ones
    answering now first, the tailnet one before the LAN ones), so a LAN
    lease that moved under CT_YIELD_HOSTS does not blind the probe. One line
    is logged when the address put first changes."""
    import desktop_hosts
    import ocr_remote
    hosts = ocr_remote.hosts()
    hosts = hosts + [h for h in os.environ.get("CT_YIELD_HOSTS", "").split() if h not in hosts]
    out = []
    for h in hosts:
        user, _, address = h.rpartition("@")
        if desktop_hosts.is_desktop(address):
            for a in desktop_hosts.ranked(22, tailnet_first=True):
                r = f"{user}@{a}" if user else a
                if r not in out:
                    out.append(r)
        elif h not in out:
            out.append(h)
    first = next((h.rpartition("@")[2] for h in out if desktop_hosts.is_desktop(h.rpartition("@")[2])), None)
    if first and first != _YIELD_VIA[0]:
        if _YIELD_VIA[0]:
            log(f"game-yield probe: desktop now at {first} (was {_YIELD_VIA[0]})")
        _YIELD_VIA[0] = first
    return out


def desktop_yielding():
    """Why the desktop OCR hosts are yielding to Paul, or None (also None
    when no desktop is set: then every read is made here anyway)."""
    if desktop_gate_reader is not None:
        return desktop_gate_reader()
    import desktop_busy
    hosts = yield_hosts()
    return desktop_busy.busy(hosts) if hosts else None


def desktop_free():
    """desktop_mem_reader(): (when read, free MB) of the desktop, or None."""
    if desktop_mem_reader is not None:
        return desktop_mem_reader()
    import desktop_busy
    import ocr_remote
    hosts = ocr_remote.hosts()
    return desktop_busy.free_mb(hosts) if hosts else None


#: Seconds a session runs before its memory surely shows in a reading: an
#: end is credited back only for a unit started this long before the
#: reading (or since it), not one whose session was still loading then.
DESKTOP_SETTLE_S = 30


def desktop_sessions(t, opened, closed=()):
    """The OCR sessions opened on the desktop since a reading at `t` and not
    closed again: each start in `opened` (start times) since it, less each
    unit in `closed` ((start, end) times) that ended since it, having
    started since it or DESKTOP_SETTLE_S before it (its memory was in the
    reading). Never below none."""
    ended = sum(e >= t and (s >= t or s <= t - DESKTOP_SETTLE_S) for s, e in closed)
    return max(0, sum(s >= t for s in opened) - ended)


def desktop_room(reading, opened, closed=()):
    """Whether the desktop has room for one more OCR session: its free
    memory at `reading` (desktop_free; None, or one over DESKTOP_STALE_S
    old: room), less a session for each still open of those started since
    that reading (desktop_sessions: starts less ends since it), stays above
    DESKTOP_FLOOR_MB after it.
    Counting only starts held the queue to (free - floor) / session starts
    per reading (~one a minute) however many units had ended: ~4 a minute
    at 9 GB free, so 6-12 units ran on a desktop with room for more."""
    if reading is None or time.time() - reading[0] > DESKTOP_STALE_S:
        return True
    t, free = reading
    return free - DESKTOP_SESSION_MB * (desktop_sessions(t, opened, closed) + 1) >= DESKTOP_FLOOR_MB


def dispatch(papers=PAPERS, cache=fa.CACHE, puzzles=None, reread=None, seconds=None, workers=WORKERS,
             scan_workers=SCAN_WORKERS, beside=None, read_seconds=READ_SECONDS,
             scan_seconds=SCAN_SECONDS, replan=REPLAN, fetch=(), trove_workers=TROVE_WORKERS, handoff=None,
             resume=None, fetch_replan=None, upkeep=None, plan_reuse=None, watch=True):
    """Run the queue until nothing due is left to start (or `seconds` have
    passed, or a TERM), then wait for the units running. `fetch` names the
    FETCHERS whose units run too, in pools of their own. With `handoff` (a
    path), the units another run handed over there are taken on (counted in
    their pools, killed at their limits, TERMed on a stop), and when
    `seconds` pass the units still running are handed over there in turn and
    this run ends at once, not waiting for them. `resume` (a path) is the
    hand-over of this run's own image before a re-exec (code_files changed),
    taken on the same way. Each fetch source's plan is made again
    `fetch_replan` (FETCH_REPLAN when None) seconds after the last.
    `upkeep` (main's ledger_upkeep) runs once before the first plan made
    here: on the planner thread when the run starts units from the last
    plan, so a slice's or re-exec's slots refill at once, not after it.
    Returns the exit status: 0, or 143 after a TERM."""
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(signal.SIGTERM))
    signal.signal(signal.SIGINT, lambda *_: stop.append(signal.SIGINT))
    # SIGHUP (or the watcher: origin/master's tools/ code moved) reloads: see reload_check.
    reload = []  # why a reload was asked, once
    reload_since = [None]  # when this run began to wind down for it
    reload_termed_at = [None]  # when the first TERM went at the end of the grace
    signal.signal(signal.SIGHUP, lambda *_: reload.append("SIGHUP"))
    # A re-exec blocks these across it (reexec); the handlers are in place now.
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM, signal.SIGINT, signal.SIGHUP})
    code = code_files()
    watcher = hot_reload.Watcher(TOOLS.parent, closure=queue_closure()).start() if hot_reload.enabled() and watch else None
    begun = code_checked = time.monotonic()
    running = {}  # pid: (unit, started)
    tried = set()
    finished = {}
    scanned, scan_failed = set(), set()  # (paper, rel) of the scans that ended done, or failed, this run
    outcomes = {}
    losses = {}  # key_of(unit): times it ended lost (EXITS["lost"])
    unbatched = set()  # keys of the editions of a batch that ended deferred: read alone from then on (batch_mates)
    # Paul 10-13: "If the vision model is down and you need it just go onto
    # the next scan and do it when it is back". The reads that ended deferred
    # for the VLM (EXITS["vlm"]), held with needs_vlm's while it is down.
    vlm_held = set()
    vlm_lost_at = [float("-inf")]  # when a read last ended deferred for it
    vlm_logged = [None, 0]  # (when the "VLM down" line was last logged, its count)
    vlm_pending = [0]  # the reads waiting for it at the last pass that could start units
    idle_walk = [None, None]  # (idle_key, (held flags, vlm_deferred)) of the last pass whose walk began nothing
    # The media share down (a unit's EXITS["media"], or this loop's own error on a media path):
    # no unit starts until it answers, and past CT_MEDIA_WAIT the run ends 1 (MediaGate).
    media = MediaGate()
    media_tries = {}  # key_of(unit): times it ended deferred for the share this run (MEDIA_TRIES)
    media_gone = []  # why the run gave up on the share
    beside = [Beside(argv) for argv in beside or ()]
    scans = reads = fetches = []
    # The editions just laid out (fresh), looked for every FRESH_POLL
    # seconds on this loop, not the planner's thread, and started first.
    fresh_scans = fresh_reads = []
    fresh_at = None
    first = []  # scan units of reads whose own scan was stale when they were to start (start)
    planned = None  # when the plan in force was begun
    plan_done = None  # when it was made
    planner = None  # (thread, its result box) making the next plan
    # The last plan is kept beside the hand-over, so a re-exec or the next
    # slice starts units from it at once while its own plan is made.
    plan_file = Path(f"{handoff or resume or f'/tmp/edition-queue-{os.getpid()}.json'}.plan")
    plan_key = [list(papers), str(cache), reread and reread.isoformat(), sorted(fetch), plan_version(code)]
    plan_at = None  # when the plan in force was made (wall clock), once one is kept
    plan_reuse = PLAN_REUSE if plan_reuse is None else plan_reuse
    planned_took = [0.0]  # seconds the last whole plan took (replan_after)
    if handoff or resume:
        kept, plan_at, kept_took = last_plan(plan_file, plan_key)
        if kept:
            scans, reads, fetches = kept
            planned = time.monotonic()
            log(f"started from the last plan: {len(scans)} scans, {len(reads)} reads, {len(fetches)} fetches")
            if time.time() - plan_at < plan_reuse:
                # Young enough to stand as made: the next whole plan comes when it
                # would have without the re-exec (fresh() already looks for new
                # editions every FRESH_POLL), and the image may re-exec again at once.
                plan_done = planned
                planned_took[0] = kept_took
                log(f"the plan is {time.time() - plan_at:.0f}s old: kept, not made again now")
    queue = []  # the units of the last pass, started or not
    idle_seen = [None, True]  # when idle cores were last read (monotonic), and whether one was idle
    scan_workers = min(scan_workers, scan_cap())
    pool_width = scan_workers + workers

    def replan_after():
        """Seconds after the last plan the next is made: `replan`, or
        IDLE_BACKOFF times it while no core is idle and the last plan still
        holds more untried units than the pools are wide (read at most every
        FRESH_POLL seconds)."""
        if planned_took[0] * PLAN_DUTY > replan and planned_took[0]:
            wait = min(planned_took[0] * PLAN_DUTY, PLAN_WAIT_MAX)
        else:
            wait = 0
        # Counting stops past pool_width: the queue is ~25k units and the untried come early.
        if sum(1 for _ in itertools.islice((u for u in queue if key_of(u) not in tried), pool_width + 1)) <= pool_width:
            return replan
        if idle_seen[0] is None or time.monotonic() - idle_seen[0] >= FRESH_POLL:
            idle_seen[:] = [time.monotonic(), mem_gate.idle_room(0, idle_gate_reader)]
        return max(wait, replan if idle_seen[1] else replan * IDLE_BACKOFF)

    upkept = [upkeep] if upkeep else []  # run, and emptied, before the first plan made here
    left = 0
    pools = {"scan": scan_workers, "read": workers, "trove": trove_workers, "listener": LISTENER_WORKERS,
             **{f"fetch {src}": FETCHERS[src]["workers"] for src in fetch}}
    outages = dict.fromkeys(fetch, 0)
    memory_bound = cpu_bound = desktop_bound = desk_mem_bound = False  # logged once per slice
    idle_bound = False  # logged once each time the idle cores run out
    vlm_bound = False  # logged once each time the VLM-waiting cap is met
    drainer = []  # the VLM stage's threads, started with the first spooled ask
    drainer_stop = threading.Event()
    spool_wait = {}  # {key_of(read): its spooled asks' keys} of the reads deferred for the drainer
    full_wait = {}  # {key_of(read): None} of the reads deferred for a full spool, oldest first: released as the spool has room
    spool_held = [0, 0.0]  # reads the last log line said were held for a full spool, and when (once a minute, or per 10)
    defer_runs = {}  # {key_of(read): times in a row it ended deferred for the VLM's asks}
    defer_until = {}  # {key_of(read): monotonic time before which it is not started again (DEFER_BACKOFF)}
    defer_file = Path(f"{handoff or resume}.defer") if handoff or resume else None  # kept across re-execs
    if defer_file:
        defer_runs, defer_until = last_defers(defer_file)
    stage_seen = [None, float("-inf")]  # the "vlm stage" line's last (spooled, waiting) and when
    cpu_cap_bound = False  # logged once each time the CPU-only cap holds a start back
    reserve_bound = False  # logged once each time the VLM-fill slot reserve holds a start back
    ceiling_bound = False  # logged once each time the unit-children ceiling is met
    listener_wide = False  # logged once each time the Listener pool widens to the ceiling or narrows back
    times_first = [False]  # logged once each time the Times scans take the slots FT would
    scan_held = False  # logged once each time the scans are held to their share for the reads
    opened = []  # when this run started each unit that opens a desktop session (desktop_room), the last hour's
    closed = []  # (start, end) wall times of those units that ended, the last hour's (desktop_sessions)
    burn_bound = False  # logged once each time the burn starts starving
    stopped = set()  # fetch sources started no more this run
    adopted = {**(take_over(handoff) if handoff else {}), **(take_over(resume) if resume else {})}  # pid: (unit, started)
    if not titled():
        log("setproctitle is not installed: every unit's command line shows the queue's (pip install setproctitle)")
    for unit, _ in adopted.values():
        tried.add(key_of(unit))
        log(f"taken over: {unit['kind']} {unit['rel']}")

    def units_running():
        return list(running.items()) + list(adopted.items())

    # Opt-in (CT_YIELD_HOSTS set): when a game starts, no new unit starts, the running ones get
    # CT_YIELD_GRACE seconds to finish, then are TERMed (STOP_GRACE, then KILLed) and left deferred.
    yield_since = [None]  # when this yield began
    yield_termed = set()  # pids stopped for it
    yield_termed_at = [None]  # when the first TERM went
    yield_killed = [False]
    yield_held = set()  # scans that ended deferred (desktop busy) during a yield: not retried until it ends

    def yield_stop(yielding):
        if not yielding:
            yield_held.clear()
        if not (yielding and os.environ.get("CT_YIELD_HOSTS", "").split()):
            yield_since[0] = yield_termed_at[0] = None
            yield_killed[0] = False
            return
        now = time.monotonic()
        if yield_since[0] is None:
            yield_since[0] = now
            flag = os.environ.get("DURABLE_NOW")  # durable.sh commits what is filed now, before units stop
            if flag:
                try:
                    Path(flag).touch()
                except OSError:
                    pass
            log(f"yield: {yielding}; no read starts, the {len([1 for _, (u, _) in units_running() if u['kind'] == 'read'])} "
                f"running get {yield_grace()}s to finish, then are stopped and left for after the game")
        if now - yield_since[0] < yield_grace():
            return
        fresh_pids = [pid for pid, (u, _) in units_running() if u["kind"] == "read" and pid not in yield_termed]
        if fresh_pids:
            if yield_termed_at[0] is None:
                yield_termed_at[0] = now
                log(f"yield: grace over, TERM to {len(fresh_pids)} unit(s), up to {STOP_GRACE}s")
            for pid in fresh_pids:
                yield_termed.add(pid)
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        if yield_termed_at[0] is not None and not yield_killed[0] and now - yield_termed_at[0] >= STOP_GRACE:
            yield_killed[0] = True
            for pid in list(yield_termed):
                if pid in running or pid in adopted:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    # A game also sheds the CPU work (Paul 10-17: WoW choppy, WSL2's VM competes as a whole, nice does not
    # help; a SIGSTOPped scan keeps its ~0.6 GB, and Windows paged at 3.8k/s): the scans beyond
    # CT_GAME_SCAN_WORKERS (3; the oldest keep running) are TERMed, then KILLed after STOP_GRACE, and end
    # deferred (a scan is ~200 s of work; yield_termed makes reap count it deferred, never a failure) to run
    # again once the game ends. No scan starts beyond that cap. Fetches (network) go on. The --beside filers
    # (a long batch, costly to lose) are SIGSTOPped instead, their --seconds clock stopped with them (resume
    # credits the time), and SIGCONTed when the game ends, on a TERM, or before a hand-over.
    shed = {}  # pid: when its TERM went
    game_now = [False]

    # A game also wants the RAM the WSL VM holds: Linux's page cache stays in the VM (Windows sees it
    # as vmmemWSL) after the units end (Paul 10-18: "wow is slow ... you're not freeing your ram hog
    # thing"; Windows was down to 1 GB free, 7 GB after a drop). CT_GAME_DROP_CACHE, a shell command
    # (unset runs none), runs once the stopped units are gone (or their grace is over), then
    # every GAME_DROP_EVERY seconds while the game lasts, in the background.
    drop_at = [None, None]  # (when the game began, when the last drop ran)

    def drop_cache(now):
        cmd = os.environ.get("CT_GAME_DROP_CACHE", "").strip()
        if not cmd:
            return
        began, last = drop_at
        if last is None:
            if any(u["kind"] != "fetch" for _, (u, _) in units_running()) and now - began < 2 * STOP_GRACE + yield_grace():
                return
        elif now - last < GAME_DROP_EVERY:
            return
        drop_at[1] = now
        try:
            subprocess.Popen(["sh", "-c", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            log("game: dropping the VM's page cache so Windows gets the RAM back")
        except OSError as e:
            log(f"game: page-cache drop failed: {e}")

    def freeze(game):
        game_now[0] = game
        if not game:
            thaw()
            shed.clear()
            drop_at[:] = [None, None]
            return
        now = time.monotonic()
        if drop_at[0] is None:
            drop_at[0] = now
        live = sorted((t0, pid) for pid, (u, t0) in units_running() if u["kind"] == "scan" and pid not in shed)
        new = [pid for _, pid in live[game_scans():]]  # the oldest scans keep running
        for pid in new:
            shed[pid] = now
            yield_termed.add(pid)
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for pid, at in list(shed.items()):
            if pid not in running and pid not in adopted:
                del shed[pid]
            elif now - at >= STOP_GRACE:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for b in beside:
            b.pause()
        if new:
            log(f"game: TERM to {len(new)} scan(s) beyond the {game_scans()} that may run on; they are left for after it")
        drop_cache(now)

    def thaw():
        """SIGCONT the stopped --beside filers, crediting them the time stopped."""
        for b in beside:
            b.resume()

    fetch_made = {}  # source: (when its plan was made, its units)
    # The queue's units with their key and slot, made once per plan (the lists' (id, len)
    # change with it), not per unit per pass: (signature, queue, keys, slots, last index of
    # each slot, (unit, key, slot) of the urgent candidates, (unit, key) of the read-slot reads, lists,
    # the urgent candidates' keys, {key: its first index among them}).
    queue_memo = [None] * 13
    scan_of_rel = [None, {}]  # the scan_keys lists, their scans by (paper, rel): gpu_fill's scan_of
    fill_scan_logged = [0]  # the fill scans last logged: logged again when their count changes
    scan_keys = [None, frozenset(), None]  # the lists' (id, len), their scans' (paper, rel), the lists

    def replan_all(notes=None):
        sc, rd = plan(papers, cache, reread, notes)
        live = [s for s in fetch if s not in stopped]
        for src in live:
            if src not in fetch_made or time.monotonic() - fetch_made[src][0] >= (
                    FETCH_REPLAN if fetch_replan is None else fetch_replan):
                t0 = time.monotonic()
                units = plan_fetches([src])
                fetch_made[src] = (time.monotonic(), units)
                if notes is not None and fetch_made[src][0] - t0 >= SLOW_PLAN:
                    notes.append(f"slow plan: {src} fetches took {fetch_made[src][0] - t0:.0f}s")
        return sc, rd, [u for src in live for u in fetch_made[src][1]]

    def may_start():
        return not stop and not reload and (seconds is None or time.monotonic() - begun < seconds)

    def reload_check():
        """A reload asked (SIGHUP, or the watcher saw code change on origin/master):
        say so once and, at once, have what is filed committed (the wrapper's
        move to origin/master follows). With a handoff the main loop then hands
        the running units over and ends; without one they are waited for, and
        after CT_RELOAD_GRACE TERMed and left deferred, as a game does."""
        if watcher is not None and watcher.hit and not reload:
            reload.append(f"origin/master changed {hot_reload.summary(watcher.hit)}")
        if not reload:
            return
        now = time.monotonic()
        if reload_since[0] is None:
            reload_since[0] = now
            flag = os.environ.get("DURABLE_NOW")
            if flag:
                try:
                    Path(flag).touch()
                except OSError:
                    pass
            log(f"reload: {reload[0]}; no unit starts, {len(running) + len(adopted)} running "
                + ("are handed to the next run" if handoff else f"get {hot_reload.grace_seconds():.0f}s to finish, then are stopped and left deferred"))
        if handoff or now - reload_since[0] < hot_reload.grace_seconds():
            return
        for pid, (unit, _) in units_running():
            if pid not in yield_termed:
                yield_termed.add(pid)
                log(f"reload: grace over, TERM to {unit['kind']} {unit['rel']}")
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        if reload_termed_at[0] is None:
            reload_termed_at[0] = now
        elif now - reload_termed_at[0] >= STOP_GRACE:
            for pid in list(yield_termed):
                if pid in running or pid in adopted:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    spec = {"cache": str(cache), "puzzles": puzzles and str(puzzles), "reread": reread and reread.isoformat()}

    preparing = {}  # key: (when submitted, the future of prepare(unit)) of the reads being briefed
    briefers = ThreadPoolExecutor(PREPARERS, "brief")

    def brief_of(unit):
        """The prepare() result of read `unit`, made on a pool thread so the
        loop goes on reaping and starting others meanwhile: PENDING until it
        is made (asked again every pass), then the result, once."""
        key = key_of(unit)
        if key not in preparing:
            preparing[key] = (time.monotonic(), briefers.submit(lambda: prepare(unit, cache, puzzles, reread)))
            concurrent.futures.wait([preparing[key][1]], timeout=BRIEF_WAIT)  # a quick one starts this pass
        if not preparing[key][1].done():
            return PENDING
        return preparing.pop(key)[1].result()

    def drop_stale_briefs():
        """Forget the briefs no pass asked for in BRIEF_KEEP seconds (a
        unit that left the plan), removing the file each made."""
        for key, (t, fut) in list(preparing.items()):
            if time.monotonic() - t >= BRIEF_KEEP and fut.done():
                del preparing[key]
                path = fut.result()
                if path and path is not SCAN_FIRST:
                    Path(path).unlink(missing_ok=True)

    def start(unit, mates=()):
        """Start `unit`; False when it is not started: a read whose own scan
        is stale or missing waits on a scan unit queued for it (first).
        PENDING while its brief is being made. `mates` (batch_mates): more
        answers-linked reads of its item read in the same process, whole
        (answers_only needs no desktop), each logged and tracked as a unit."""
        sys.stdout.flush()
        sys.stderr.flush()
        alone = losses.get(key_of(unit), 0) >= LOST_TRIES
        if mates and not alone:
            unit = {**unit, "batch": [v["rel"] for v in mates]}
        else:
            mates = ()
        argv = unit_argv(unit)
        if alone or mates or unit["kind"] != "read" or unit["paper"] not in fa.FILERS:
            made = None
        else:
            made = brief_of(unit)
            if made is PENDING:
                return PENDING
        if made == SCAN_FIRST and (unit["paper"], unit["rel"]) in scanned:
            made = whole(unit, "own scan stale or missing, scanned this run already")
        elif made == SCAN_FIRST:
            first.append({"kind": "scan", "paper": unit["paper"], "rel": unit["rel"], "rank": unit["rank"],
                          "reason": "its read's own scan is stale or missing"})
            return False
        env = {**os.environ, "CT_EDITION_UNIT": json.dumps({**spec, "unit": unit, **({"brief": made} if made else {})}),
               # setproctitle then keeps /proc/<pid>/environ (the title fits
               # in its argv), so the room tag the bridge's watchdog reads stays.
               "SPT_NOENV": "1"}
        if unit["kind"] == "read":
            # A read needing the VLM while it is down ends deferred, never read without it (vlm_reader.wanted).
            env[vlm_reader.DEFER_ENV] = "1"
            # ... and its ask the VLM has not answered is spooled for the drainer, not waited for (vlm_reader.SPOOL_ENV).
            if os.environ.get(vlm_reader.SPOOL_ENV, "1") != "0":
                env[vlm_reader.SPOOL_ENV] = "1"
        if alone:
            env["OCR_REMOTE"] = ""
        elif unit["kind"] != "fetch":
            # Its OCR is not moved onto this host while the desktop yields: it ends deferred, run again once idle.
            env[ocr_remote.DEFER] = "1"
        pid = os.posix_spawn(argv[0], argv, env, setpgroup=0, setsigmask=())
        running[pid] = (unit, time.monotonic())
        tried.add(key_of(unit))
        log(f"start {unit['kind']} {unit['rel']} ({unit['reason']}{': ' + unit['detail'] if unit.get('detail') else ''})"
            + (f" in a batch of {len(mates) + 1}" if mates else ""))
        for v in mates:
            tried.add(key_of(v))
            log(f"start {v['kind']} {v['rel']} ({v['reason']}) in the batch of {unit['rel']}")
        return True

    def ended(unit, t0):
        # Its desktop session has closed: desktop_room credits it back.
        if not load_gated(unit):
            now = time.time()
            closed.append((now - (time.monotonic() - t0), now))

    def reap():
        # A unit this process started before a re-exec is adopted and still its child.
        while running or adopted:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            if pid == 0:
                return
            if pid not in running and pid not in adopted:
                continue
            unit, t0 = running.pop(pid) if pid in running else adopted.pop(pid)
            ended(unit, t0)
            rc = os.waitstatus_to_exitcode(status)
            # TERMed or KILLed for a game (yield_stop): left for the next run, never a failure.
            parked = pid in yield_termed and rc in (-signal.SIGTERM, -signal.SIGKILL, 128 + signal.SIGTERM)
            yield_termed.discard(pid)
            if parked:
                tried.discard(key_of(unit))
                tried.difference_update(batch_mate_keys(unit))
                outcomes["deferred"] = outcomes.get("deferred", 0) + 1
                log(f"end {unit['kind']} {unit['rel']}{batch_note(unit)}: deferred (stopped for a game) in {time.monotonic() - t0:.0f}s")
                continue
            if rc == EXITS["lost"]:
                losses[key_of(unit)] = losses.get(key_of(unit), 0) + 1
            # The media share did not answer: deferred, and no unit starts until it does (media.hold).
            # One deferred for it MEDIA_TRIES times this run fails: that path's error, not an outage.
            media_retry = False
            if rc == EXITS["media"]:
                media_tries[key_of(unit)] = media_tries.get(key_of(unit), 0) + 1
                media_retry = media_tries[key_of(unit)] <= MEDIA_TRIES
                media.down()
            if rc == EXITS["vlm"]:
                spooled_by = vlm_reader.spooled_by(pid)
                spooled_end = bool(spooled_by)
                full_end = vlm_reader.full_mark(pid).exists()
                if full_end:
                    vlm_reader.full_mark(pid).unlink(missing_ok=True)
                    full_wait.pop(key_of(unit), None)
                    full_wait[key_of(unit)] = None  # started again once the spool has room for it
                if spooled_by or full_end:
                    n = defer_runs[key_of(unit)] = defer_runs.get(key_of(unit), 0) + 1
                    if n >= 2:
                        defer_until[key_of(unit)] = time.monotonic() + min(DEFER_BACKOFF_MAX, DEFER_BACKOFF * 2 ** (n - 2))
                    if defer_file:
                        keep_defers(defer_file, defer_runs, defer_until)
                if spooled_by:
                    spool_wait[key_of(unit)] = set(spooled_by)  # started again once the drainer has answered them
                    full_wait.pop(key_of(unit), None)  # its asks are spooled: the answers, not the cap, release it
                elif not full_end:
                    vlm_held.add(key_of(unit))
                    vlm_lost_at[0] = time.monotonic()
            if rc in (EXITS["deferred"], EXITS["lost"], EXITS["vlm"]) or media_retry:
                tried.discard(key_of(unit))  # started again once the desktop is idle, the VLM or the media share answers
                tried.difference_update(batch_mate_keys(unit))  # ... each batched edition on its own
                if unit.get("batch"):
                    unbatched.update(batch_mate_keys(unit))
                    unbatched.add(key_of(unit))
                if desktop_bound and unit["kind"] == "scan":
                    yield_held.add(key_of(unit))
            else:
                finished[key_of(unit)] = time.monotonic()
                for k in batch_mate_keys(unit):
                    finished[k] = finished[key_of(unit)]
                if defer_runs.pop(key_of(unit), None) is not None and defer_file:
                    defer_until.pop(key_of(unit), None)
                    keep_defers(defer_file, defer_runs, defer_until)
                defer_until.pop(key_of(unit), None)
            if unit["kind"] == "scan" and rc == 0:
                scanned.add((unit["paper"], unit["rel"]))
            elif unit["kind"] == "scan" and rc != EXITS["deferred"] and not media_retry:
                scan_failed.add((unit["paper"], unit["rel"]))
            what = {0: "done", 3: "busy (another unit has it)", 4: "held (a run holds the ledger)",
                    5: "failed, the source looks down", 6: "done, but throttled (429)",
                    7: "not started: the disk is full",
                    EXITS["media"]: "deferred (the media share is down)" if media_retry
                    else f"failed (the media share's error {MEDIA_TRIES + 1} times this run)",
                    EXITS["deferred"]: "deferred (the desktop is busy)",
                    EXITS["lost"]: "deferred (the desktop was lost)",
                    EXITS["vlm"]: "deferred (spooled)" if rc == EXITS["vlm"] and spooled_end
                    else "deferred: VLM spool full" if rc == EXITS["vlm"] and full_end else "deferred (the VLM is down)"}.get(rc, f"failed (rc={rc})")
            if unit["kind"] == "fetch":
                src = unit["paper"]
                outages[src] = outages[src] + 1 if rc == 5 else 0
                if rc == 6 and pools[f"fetch {src}"] > 1:
                    pools[f"fetch {src}"] -= 1
                    log(f"{src}: answered 429; at most {pools[f'fetch {src}']} fetches at once from now on")
                if (rc == 7 or outages[src] >= FETCH_OUTAGES) and src not in stopped:
                    stopped.add(src)
                    log(f"{src}: no more fetches this run ({'disk full' if rc == 7 else f'{outages[src]} in a row found it down'})")
            outcomes[what.split(" ")[0]] = outcomes.get(what.split(" ")[0], 0) + 1
            log(f"end {unit['kind']} {unit['rel']}: {what} in {time.monotonic() - t0:.0f}s")
            for r in unit.get("batch") or ():
                log(f"end {unit['kind']} {r}: {what} in the batch of {unit['rel']}")

    def reap_adopted():
        for pid, (unit, t0) in list(adopted.items()):
            if not alive(pid):
                del adopted[pid]
                ended(unit, t0)
                if pid in yield_termed:  # stopped for a game: left for the next run
                    yield_termed.discard(pid)
                    tried.discard(key_of(unit))
                    tried.difference_update(batch_mate_keys(unit))
                    log(f"end {unit['kind']} {unit['rel']}{batch_note(unit)}: deferred (stopped for a game, taken over) in {time.monotonic() - t0:.0f}s")
                    continue
                finished[key_of(unit)] = time.monotonic()
                for k in batch_mate_keys(unit):
                    finished[k] = finished[key_of(unit)]
                log(f"end {unit['kind']} {unit['rel']}: ended (taken over) in {time.monotonic() - t0:.0f}s")

    def overdue():
        for pid, (unit, t0) in units_running():
            limit = (FETCHERS[unit["paper"]]["seconds"] if unit["kind"] == "fetch" else
                     LISTENER_SECONDS if unit["paper"] == "listener" else
                     unit_limit(unit, read_seconds) if unit["kind"] == "read" else scan_seconds)
            if time.monotonic() - t0 > limit:
                log(f"{unit['kind']} {unit['rel']}{batch_note(unit)} ran past {limit}s; killed, left for the next run")
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def keep_untried():
        # What the next run starts from: the plan in force less the units
        # this one started (done, running or failed), so its first pass
        # fills the slots with new work, not units already done.
        if plan_at is not None:
            keep_plan(plan_file, plan_key, [[u for u in us if key_of(u) not in tried]
                                            for us in (scans, reads, fetches)], plan_at, planned_took[0])

    def reexec(why=None):
        """Hand the running units to this run's new image and become it."""
        path = handoff or resume or Path(f"/tmp/edition-queue-{os.getpid()}.json")
        thaw()  # the next image does not know the filers are stopped
        hand_over(path, units_running())
        keep_untried()
        argv =[sys.executable, *sys.argv]
        if seconds is not None:
            argv += ["--seconds", str(max(0.0, seconds - (time.monotonic() - begun)))]
        if not handoff:
            argv += ["--resume", str(path)]
        log(f"{why or 'code changed (' + ', '.join(sorted(f.name for f, h in code.items() if digest(f) != h)) + ')'}; "
            f"re-exec, {len(running) + len(adopted)} running unit(s) kept")
        sys.stdout.flush()
        sys.stderr.flush()
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT, signal.SIGHUP})
        os.environ[REEXEC_ENV] = "1"
        os.execv(argv[0], argv)

    # A slice's first image (started by the shell, not by a re-exec) runs the
    # plan the last slice kept, which can be a whole plan (half an hour on a
    # loaded host) older than the code it was started on, so it re-execs on a
    # change at once, mid-plan. Every image after a re-exec makes a plan of
    # its own first: changes landing faster than a plan takes still get plans
    # made on new code, and the chain re-execs without one at most once.
    def may_reexec():
        return plan_done is not None or not os.environ.get(REEXEC_ENV)

    # A media error this loop does not catch itself ends dispatch; main waits for the share
    # and hands the running units to a new image through this (media_restart).
    _media_reexec[:] = [reexec, lambda: [pid for pid, _ in units_running()]]

    # The unit ceiling follows the Windows host's free RAM and CPU (mem_gate.ceiling_controller; opt-in by
    # env, hosts default from CT_YIELD_HOSTS and the VLM's /metrics); its probes run on a thread.
    ceiling_ctl = mem_gate.ceiling_controller(f"{vlm_reader.URLS[0]}/metrics" if vlm_reader.URLS else None)
    if ceiling_ctl:
        log(f"ceiling controller on: host {ceiling_ctl.host}, metrics {ceiling_ctl.metrics}, every {ceiling_ctl.every} s")

    while True:
        reap()
        reap_adopted()
        overdue()
        reload_check()
        if ceiling_ctl:
            for line in ceiling_ctl.poll():
                log(line)
        for b in beside:
            b.poll(may_start() and not game_now[0], None if seconds is None else seconds - (time.monotonic() - begun))
        # The media share down: nothing is planned, looked for or started (each would meet it) until a
        # probe finds it answering; units running are reaped and kept to their limits meanwhile. A stop,
        # a reload or the slice's end goes on as ever (none starts a unit).
        if may_start():
            try:
                media_holds = media.hold()
            except MediaGone as e:
                log(f"media down: giving up, {e}; stopping")
                media_gone.append(str(e))
                stop.append("media")
                media_holds = False
            if media_holds:
                nap(MEDIA_NAP)
                continue
        # A plan stats every edition and article (minutes on the media
        # mount), so after the first it is made on a thread while this loop
        # goes on reaping and starting from the plan before it.
        # Checked apart from planning: a plan can take minutes (a cold cache
        # on the media mount), and the code it would run is the old. An image
        # a re-exec started re-execs only once it has made a whole plan of
        # its own (kept in plan_file for the next), or changes landing faster
        # than a plan takes would leave every image running the last kept,
        # stale plan; a slice's first image need not (may_reexec).
        if may_start() and may_reexec() and time.monotonic() - code_checked >= replan:
            code_checked = time.monotonic()
            if not any(b.busy() for b in beside) and any(digest(f) != h for f, h in code.items()):
                reexec()
        if may_start() and (fresh_at is None or time.monotonic() - fresh_at >= min(replan, FRESH_POLL)):
            fresh_at = time.monotonic()
            try:
                new_scans, new_reads = fresh(papers, cache)
            except OSError as e:
                if not media.down(e):
                    raise
                new_scans, new_reads = fresh_scans, fresh_reads  # looked for again once the share answers
            fresh_scans, fresh_reads = unchanged_eq(fresh_scans, new_scans), unchanged_eq(fresh_reads, new_reads)
        if may_start() and planner is None and not media.held() and (
                plan_done is None or time.monotonic() - plan_done >= replan and time.monotonic() - plan_done >= replan_after()):
            box = {"begun": time.monotonic(), "notes": []}

            def make(box=box):
                try:
                    while upkept:
                        upkept.pop()()
                    box["plan"] = replan_all(box["notes"])
                except BaseException as e:  # raised again on the dispatch loop
                    box["error"] = e
            planner = (threading.Thread(target=make, daemon=True), box)
            if planned is None and fetch:
                # Scans and reads start first; the fetch plan (every done
                # edition's siblings, minutes off a cold cache) is made on
                # the thread at once after.
                try:
                    while upkept:
                        upkept.pop()()
                    box["plan"], box["partial"] = (*plan(papers, cache, reread, box["notes"]), []), True
                except BaseException as e:  # raised again below, as make()'s
                    box["error"] = e
            elif planned is None:
                make()
            else:
                planner[0].start()
        if planner is not None and not planner[0].is_alive() and "error" in planner[1] and media.down(planner[1]["error"]):
            planner = None  # the plan met the media share down: made again once it answers (media.hold)
        if planner is not None and not planner[0].is_alive():
            box, planner = planner[1], None
            if "error" in box:
                raise box["error"]
            scans, reads, fetches = box["plan"]
            planned, plan_done = box["begun"], None if box.get("partial") else time.monotonic()
            if plan_done is not None:
                planned_took[0] = plan_done - planned
                plan_at = time.time()
                keep_plan(plan_file, plan_key, box["plan"], plan_at, planned_took[0])
            for n in box["notes"]:
                log(n)
            log(f"planned: {len(scans)} scans, {len(reads)} reads"
                + (", fetches next" if box.get("partial") else f", {len(fetches)} fetches" if fetch else "")
                + f" due in {time.monotonic() - planned:.0f}s; running {len(running) + len(adopted)}")
        fetches = unchanged(fetches, [u for u in fetches if u["paper"] not in stopped])
        busy = {key_of(u) for _, (u, _) in units_running()}
        # A read of an edition read before, waiting only on a new scan, starts
        # after the plan that follows its scans: the scan may leave it not due.
        rescanned = {(p, r) for (k, p, r), t in finished.items() if k == "scan" and t > (planned or 0)}
        # A read waits on the scans it needs while they run, and on its own
        # edition's planned scan until that ends done (a scan that failed or
        # was killed leaves the read for the next run); a days-after scan
        # still queued behind a full scan pool stands as last scanned.
        scanning = {(p, r) for k, p, r in busy if k == "scan"}
        # The (paper, rel) of every queued scan, made again only when one of
        # its lists is replaced or grows (~25k units, a pass a second).
        scan_lists = tuple((id(us), len(us)) for us in (fresh_scans, scans, first))
        if scan_keys[0] != scan_lists:
            scan_keys[:] = [scan_lists, frozenset((u["paper"], u["rel"]) for u in fresh_scans + scans + first),
                            (fresh_scans, scans, first)]  # held, so no id is reused while keyed
        unscanned = set(scan_keys[1])
        unscanned -= scanned
        free = dict(pools)
        for _, (u, _) in units_running():
            free[slot_of(u)] = free.get(slot_of(u), 0) - 1
        # The unit-children ceiling (mem_gate.unit_ceiling) over every pool but the
        # fetches: the pools' widths stay, the slots left are zeroed once it is met.
        ceiling_left = mem_gate.unit_ceiling() - sum(1 for _, (u, _) in units_running() if u["kind"] != "fetch")
        if ceiling_left <= 0:
            free.update({sl: 0 for sl in free if not sl.startswith("fetch ")})
            if not ceiling_bound and any(pools[sl] for sl in pools if not sl.startswith("fetch ")):
                ceiling_bound = True
                log(f"unit ceiling: {mem_gate.unit_ceiling()} unit children running; no read or scan starts until one exits")
        else:
            ceiling_bound = False
        vlm_waiting = vlm_reader.waiting_now()
        queued = vlm_reader.spooled()
        if queued and not drainer:
            vlm_drainer(drainer_stop, drainer)
        stage = (len(queued), len(spool_wait))
        if stage != stage_seen[0] and (stage[0] or stage_seen[0]) and time.monotonic() - stage_seen[1] >= 30:
            stage_seen[:] = [stage, time.monotonic()]
            log(f"vlm stage: {stage[0]} asks spooled, {stage[1]} reads waiting")
        # With the spool on, a spooled read holds no RAM and no slot, so it never counts: the gate is the
        # spool's depth (CT_VLM_SPOOL_MAX) plus the OTHER processes blocked in an ask. The queue's own mark
        # (its drainer threads asking, slots()+PIPELINE) is not one: counting it held every read start
        # while the GPU drained, so the CPU idled. Spool off: the old cap on reads waiting in the VLM's lock.
        spool_on = os.environ.get(vlm_reader.SPOOL_ENV, "1") != "0"
        if spool_on and (vlm_reader._waiting_dir() / str(os.getpid())).exists():
            vlm_waiting -= 1
        if spool_on:
            # A full spool does not stop reads: one that needs an uncached ask then ends deferred
            # ("VLM spool full", vlm_reader.ask_png) and waits in full_wait; OCR-only reads go on.
            vlm_full = vlm_waiting >= vlm_waiting_cap()
        else:
            vlm_waiting += len(queued) * vlm_waiting_cap() // vlm_spool_max()  # a full spool counts as a full cap
            vlm_full = vlm_waiting >= vlm_waiting_cap()
        if vlm_full != vlm_bound:
            vlm_bound = vlm_full
            if vlm_full:
                log(f"vlm-bound: {vlm_waiting} reads wait for the VLM (CT_VLM_WAITING {vlm_waiting_cap()}), "
                    f"{len(queued)} asks spooled (CT_VLM_SPOOL_MAX {vlm_spool_max()}); no read starts until it drains")
        spool_cap_hit = len(queued) >= vlm_spool_max()
        # Of the reads held for a full spool only as many as the spool has room for start this pass, oldest first:
        # all at once they would OCR their pages and defer again as it fills.
        full_free = list(full_wait)[:max(0, vlm_spool_max() - len(queued))]
        begun_now = charged = 0
        costs = None  # unit_costs, measured at this pass's first start
        held_back = cpu_held = idle_held = False
        local_now = 0  # local_cpu units begun this pass, a core each
        idle_read = {}
        starved = mem_gate.burn_starved(burn_gate_reader)
        if starved and not burn_bound:
            log(f"{mem_gate.burn_line(starved)} ({len(running) + len(adopted)} running are left alone)")
        burn_bound = bool(starved)
        # While the desktop yields, its OCR would fall back to this host's
        # CPU: only fetches start until it is idle again.
        yielding = desktop_yielding()
        if yielding and not desktop_bound:
            log(f"desktop-bound: desktop yielding ({yielding}); only fetches start until it is idle "
                f"({len(running) + len(adopted)} running are left alone)")
        desktop_bound = bool(yielding)
        yield_stop(yielding)
        game = bool(yielding) and str(yielding).startswith("game")  # desktop_busy's "game: ..."
        freeze(game)
        live_scans = sum(1 for pid, (u, _) in units_running() if u["kind"] == "scan")
        yield_opt_in = bool(os.environ.get("CT_YIELD_HOSTS", "").split())  # scans go on during a game only then
        desk_mem = desktop_free() if not yielding else None
        opened[:] = [s for s in opened if s > time.time() - 3600]
        closed[:] = [c for c in closed if c[1] > time.time() - 3600]
        desk_held = False
        vlm_now = []  # whether the VLM answers, asked once a pass and only when a read needs it
        full_held = set()  # reads this pass held for a full spool (full_wait)

        def vlm_waits(u, vlm_now=vlm_now):
            """Whether read `u` waits for the VLM: it needs it (needs_vlm,
            or it ended deferred for it) and it is down."""
            if u["kind"] == "read" and key_of(u) in full_wait and key_of(u) not in spool_wait:
                # Ended deferred for a full spool with no ask spooled (any paper, needs_vlm or not): its
                # OCR would be redone for nothing. A read with spooled asks is in spool_wait and never held here.
                if key_of(u) not in full_free:
                    full_held.add(key_of(u))
                    return True  # not again until the spool has room for it
                full_wait.pop(key_of(u), None)
            if u["kind"] != "read" or not (key_of(u) in vlm_held or needs_vlm(u)):
                return False
            if spool_cap_hit and key_of(u) not in spool_wait and key_of(u) not in full_wait:
                # The spool is at its cap: a fresh read that may ask would OCR its pages (~25 CPU-s),
                # be refused ("VLM spool full") and start again once held, churning while the drainer
                # works. It waits here, free, until the spool is below its cap.
                full_held.add(key_of(u))
                return True
            if key_of(u) in spool_wait:
                if any(vlm_reader.pending(k) for k in spool_wait[key_of(u)]):
                    return True
                del spool_wait[key_of(u)]  # answered: its asks hit the cache now
                # ... and it starts at once: the backoff spares OCR redone for asks still unanswered, and
                # 10-24 held reads whose asks an idle drainer answered in seconds for 120 s+ (the GPU at 0%).
                defer_until.pop(key_of(u), None)
            elif defer_until.get(key_of(u), 0) > time.monotonic():
                return True  # deferred again and again for its asks: backed off (DEFER_BACKOFF)
            if not vlm_now:
                vlm_now.append(time.monotonic() - vlm_lost_at[0] >= VLM_RECHECK and vlm_up())
                if vlm_now[0] and vlm_held:
                    log(f"VLM back: {len(vlm_held)} read(s) deferred for it start again")
                    vlm_held.clear()
                if vlm_now[0]:
                    vlm_logged[0] = None
            return not vlm_now[0]
        vlm_deferred = 0
        # The whole-corpus re-reads (fa.BLANKET) wait until nothing more
        # urgent is left to start, in any pool: new and fixed work first
        # (a read waiting for the VLM holds none back).
        lists = (first, fresh_scans, fresh_reads, scans, reads, fetches)
        sig = tuple((id(l), len(l)) for l in lists)
        times_papers = newest_first_papers()
        if queue_memo[0] != sig:
            q = first + fresh_scans + fresh_reads + scans + reads + fetches
            qkeys, qslots, last_of = [key_of(u) for u in q], [slot_of(u) for u in q], {}
            for i, sl in enumerate(qslots):
                last_of[sl] = i
            body = fresh_scans + fresh_reads + scans + reads
            cands = [(u, key_of(u), slot_of(u)) for u in body
                     if (u["rank"] < fa.BLANKET or newest_first(u)) and pools.get(slot_of(u))]
            first_at = {}  # each urgent candidate's key: its first index in cands
            for i, (_, k, _) in enumerate(cands):
                first_at.setdefault(k, i)
            queue_memo[:] = [sig, q, qkeys, qslots, last_of, cands,
                             [(v, key_of(v)) for v in fresh_reads + reads if slot_of(v) == "read"], lists,  # lists held: no id reused
                             frozenset(first_at), first_at,
                             # A whole-corpus re-read (fa.BLANKET) waits behind the Listener's due reads anyway, so it
                             # is not "other work due": 10-24 five held FT/Guardian --reread units kept the pool at 8
                             # of 24 slots while it, in turn, held them (load 8, one File in 25 min).
                             frozenset(k for u, k, sl in zip(q, qkeys, qslots) if sl != "listener" and not sl.startswith("fetch ")
                                       and (u["rank"] < fa.BLANKET or newest_first(u))),
                             frozenset(k for k, sl in zip(qkeys, qslots) if sl == "listener"),
                             frozenset(k for u, k, sl in zip(q, qkeys, qslots) if sl in ("read", "scan") and u["paper"] in times_papers)]
        (_, queue, qkeys, qslots, last_of, urgent_cands, read_cands, _, urgent_keys, urgent_first,
         other_keys, listener_keys, times_keys) = queue_memo
        # Paul 10-24: the plan held only Listener reads (local OCR, no VLM) and its fixed pool ran 8 of the
        # 24 ceiling slots, 16 idle. While no other read or scan is due (queued untried) or running, the
        # Listener pool takes every ceiling slot left; once one is, it is back to LISTENER_WORKERS.
        other_due = bool(other_keys - tried) or any(
            slot_of(v) != "listener" and v["kind"] != "fetch" for _, (v, _) in units_running())
        widen = not other_due and bool(listener_keys - tried)
        if widen:
            free["listener"] = listener_free(free.get("listener", 0), other_due, ceiling_left)
        if widen != listener_wide and (widen or listener_wide):
            n_listener = sum(1 for _, (v, _) in units_running() if slot_of(v) == "listener")
            log(f"listener pool: widened to {n_listener + max(0, free['listener'])}, nothing else due "
                f"(unit ceiling {mem_gate.unit_ceiling()})" if widen else
                f"listener pool: back to {pools['listener']} (CT_LISTENER_WORKERS), "
                + ("other work due" if other_due else "no Listener read left"))
        listener_wide = widen
        # Times first (Paul 10-24): while its work is due or running, the Listener keeps at most
        # LISTENER_BESIDE_TIMES units.
        if (times_keys - tried) or any(v["paper"] in times_papers and slot_of(v) in ("read", "scan")
                                        for _, (v, _) in units_running()):
            n_listener = sum(1 for _, (v, _) in units_running() if slot_of(v) == "listener")
            free["listener"] = max(0, min(free.get("listener", 0), LISTENER_BESIDE_TIMES - n_listener))
        # Whether an untried urgent unit is not waiting for the VLM. The untried keys come from one set
        # difference (stored hashes, C speed), not a key built and looked up per candidate each pass
        # (~half the loop's CPU while all are tried); the walk then starts at the first untried one, so
        # vlm_waits is asked of the same units in the same order as a walk of them all.
        untried_urgent = urgent_keys - tried
        urgent = bool(untried_urgent) and any(
            k not in tried and not vlm_waits(u)
            for u, k, _ in itertools.islice(urgent_cands, min(map(urgent_first.__getitem__, untried_urgent)), None))
        # A pass with no free slot starts nothing; and once a gate holds
        # one unit back it holds every later one (begun_now only grows), so
        # the gates are read at most once a unit begun, not once a unit due.
        mem_read, cpu_read = {}, {}
        # Each ledger read once a pass, not once a queued scan: a scan unit
        # checks its row again before it scans (scan_unit's "current").
        stands = {}
        stand_keys, cache_s = {}, os.fspath(cache)  # current_keys by paper, a pass's; the cache's str, not a Path to fspath each ask

        def stood(u, stands=stands):
            paper = fa.FILERS[u["paper"]]
            if u["paper"] not in stands:
                stands[u["paper"]] = fa.standing(paper, cache)
            return fa.scan_stands(paper, u["rel"], cache_s, stands[u["paper"]], stand_keys, u.get("reason") in fa.HOST_REASONS)

        scanning_by = rels_by_paper(scanning)  # kept in step as scans begin below

        # Whether a read waits on a scan; a partial, not a closure: no Python frame of its own.
        waits = functools.partial(read_waits, scanning=scanning_by, unscanned=unscanned,
                                  rescanned=rels_by_paper(rescanned))
        # Reads feed the VLM and file puzzles; scans only find them. While a read is due the scans
        # keep to scan_share of the unit ceiling, so they cannot crowd the reads out of it.
        # Paul 10-21: "Read the remaining times puzzles before doing ft". While the CT_NEWEST_FIRST papers'
        # scans are pending, their reads wait on them (1,123 Times answer fills behind ~1,200 scans), so FT
        # reads, FT scans and the scan share took the slots: the scans those reads need take every slot
        # the ready Times reads will not, and FT fills only what is left, plus the few gpu_fill reads that
        # keep an otherwise idle VLM fed.
        named_now = newest_first_papers()
        tf_pending = times_scans_pending(scan_keys[2], tried, busy, scanned) if named_now else []
        tf_ready = sum(1 for u, k in read_cands if u["paper"] in named_now and k not in tried and k not in busy
                       and not waits(u)) if named_now else 0
        reads_due = not vlm_full and not yielding and (
            tf_ready > 0 or (not tf_pending and any(k not in tried and not waits(u) for u, k in read_cands)))
        share = scan_share(mem_gate.unit_ceiling(), reads_due)
        if free.get("scan", 0) > 0 and share is not None:
            live = sum(1 for _, (v, _) in units_running() if v["kind"] == "scan")
            if live + free["scan"] > share:
                free["scan"] = max(0, share - live)
                if not scan_held and free["scan"] == 0:
                    scan_held = True
                    log(f"scan held for reads: {live} scans running of {share} allowed while reads are due "
                        f"(unit ceiling {mem_gate.unit_ceiling()})")
        if tf_pending and not yielding and ceiling_left > 0 and may_start():
            room = times_scan_room(len(tf_pending), tf_ready, free.get("scan", 0), free.get("read", 0), ceiling_left)
            if room > free.get("scan", 0):
                free["scan"] = room
                if not times_first[0]:
                    times_first[0] = True
                    log(f"times first: {len(tf_pending)} Times/Gale scans pending for {tf_ready} ready reads and "
                        f"the reads waiting on them; scans may use {room} slots, FT fills only what is left")
        elif times_first[0] and not tf_pending:
            times_first[0] = False
        if free.get("scan", 0) > 0 or share is None:
            scan_held = False
        # A fresh scan is never held for a backlog's reads (fed).
        firsts = {key_of(u) for u in first + fresh_scans}
        ready = []
        heads = {}  # rank: the scans the next full read pool at that rank needs, or None (not full)

        def ready_reads(reads=read_cands, busy=busy, waits=waits):
            return [v for v, k in reads if k not in tried and k not in busy and not waits(v) and not vlm_waits(v)]

        def fed(u, ready=ready, heads=heads):
            """Whether scan `u` only feeds a backlog: the next full read pool
            of ready reads ranked as it or more urgent, in the queue's order,
            are there and none needs it. Then its desktop CPU (scans run above
            reads there) is the reads' instead. Worked out once a pass per
            rank: a pass asks it of every queued scan (~12k)."""
            if vlm_full:
                return False  # reads cannot start (vlm-bound), so no scan is held for their CPU
            if not ready:
                ready.append(ready_reads())
            if u["rank"] not in heads:
                nxt = [v for v in ready[0] if v["rank"] <= u["rank"]][:pools["read"]]
                heads[u["rank"]] = ({(v["paper"], r) for v in nxt for r in v["needs"]}
                                    if len(nxt) >= pools["read"] else None)
            needed = heads[u["rank"]]
            return needed is not None and (u["paper"], u["rel"]) not in needed
        walked = may_start() and any(v > 0 for v in free.values())
        # An idle GPU is a bug: with the VLM stage short of asks, other papers' never-read reads (which
        # ask the VLM) go ahead of the CT_NEWEST_FIRST papers' OCR-only rereads (gpu_fill).
        def fill_scan(u, scan_keys=scan_keys, unscanned=unscanned):
            """The queued scan read `u` waits on (its own, not yet done), or None."""
            if (u["paper"], u["rel"]) not in unscanned:
                return None
            if scan_of_rel[0] is not scan_keys[2]:
                scan_of_rel[:] = [scan_keys[2], {(s["paper"], s["rel"]): s for us in scan_keys[2] for s in us}]
            return scan_of_rel[1].get((u["paper"], u["rel"]))
        fills_running = sum(1 for _, (v, _at) in units_running() if fills_gpu(v))
        fill = gpu_fill(read_cands, tried, busy, waits, vlm_waits, len(queued), vlm_full or spool_cap_hit,
                        fills_running,
                        # Paul 10-21: "you should also be letting things through which use gpu so it doesn't sit
                        # idle". Fills run up to CT_VLM_FEED_READS at once (each spends minutes on OCR before
                        # its first ask), never past the free read slots; Times work still starts first.
                        min(vlm_feed_reads(), fills_running + free.get("read", 0)),
                        fill_scan, scanning,
                        # Paul 10-23: no fill read ready, GPU 0%: the scans they wait on start, a few at once.
                        min(vlm_feed_scans(), max(1, mem_gate.unit_ceiling() // 3))
                        ) if (free.get("read", 0) > 0 and may_start() and not yielding and not starved) else []
        fill_keys = {key_of(u) for u in fill}
        fill_scans = sum(1 for u in fill if u["kind"] == "scan")
        if fill_scans and free.get("scan", 0) < fill_scans and ceiling_left > 0:
            # The scan share held scans for reads, but no fill read can start until these end.
            free["scan"] = min(fill_scans, ceiling_left)
            if fill_scans != fill_scan_logged[0]:
                log(f"vlm feed: no VLM-asking read ready ({len(queued)} asks spooled, target {vlm_feed_target()}); "
                    f"{fill_scans} scan(s) they wait on start ahead of the queue")
        fill_scan_logged[0] = fill_scans
        if fill and free.get("scan", 0) > 0 and not vlm_full:
            # The fill reads start ahead of the queue: the pool fed() asks about is the one before they begin,
            # else a scan no read waits on is "not fed" the moment they take the last read slot and starts
            # ahead of them (the queue lists scans first).
            ready.append(ready_reads())
        # Paul 10-21: CPU-only units (answers-linked rereads, scans) filled the whole unit ceiling and the
        # GPU sat idle. While fills are wanted, that many ceiling slots (at most a third) are kept for them.
        reserve = min(len(fill), max(1, mem_gate.unit_ceiling() // 3)) if fill else 0
        reserve_hit = False
        # While the GPU is underfed the CPU-only units (stale scans, answer-linked rereads) share at most a
        # third of the ceiling, so the rest goes to reads that ask the VLM.
        cpu_cap = mem_gate.unit_ceiling() // 3 if len(queued) < vlm_feed_target() else None
        cpu_live = sum(1 for _, (v, _at) in units_running() if cpu_only_unit(v)) if cpu_cap is not None else 0
        cpu_capped = False

        def idle_key(gates, urgent=urgent, free=free, starved=starved, yielding=yielding, desk_mem=desk_mem):
            """What a walk of the queue (~12k units) that begins nothing
            depends on: the plan, the units running and tried, the gates it
            read (`gates`: the (mem, cpu, idle) readings by their arguments),
            and the IDLE_WALK slot of time (a ledger another process moved,
            the VLM back, a desktop session aged out: noticed within
            IDLE_WALK seconds)."""
            return (planned, plan_done, fresh_at, len(queue), len(first), len(tried), len(scanned), len(scan_failed),
                    sum(losses.values()), len(vlm_held), len(spool_wait), len(full_wait), spool_cap_hit, vlm_full, tuple(running), tuple(adopted), tuple(sorted(free.items())),
                    len(stopped), urgent, tuple(fill_keys), bool(starved), bool(yielding), desk_mem, len(opened), len(closed),
                    int(time.monotonic() // IDLE_WALK), gates)

        def gates_again(gates):
            """The gates the last idle walk read, read again with the same
            arguments: once each, as that walk did."""
            mem, cpu, idle = gates
            return (tuple((k, mem_gate.room(k[0], mem_gate_reader, unit=k[1])) for k, _ in mem),
                    tuple((k, mem_gate.cpu_room(k, cpu_gate_reader)) for k, _ in cpu),
                    tuple((k, mem_gate.idle_room(k, idle_gate_reader)) for k, _ in idle))
        # A pass the last idle one's state and gates stand for would begin
        # nothing again: its outcome stands, the walk is skipped. The state
        # is compared first: the gates are read only when it matches.
        skip_walk = (walked and idle_walk[0] is not None and idle_key(idle_walk[0][-1]) == idle_walk[0]
                     and gates_again(idle_walk[0][-1]) == idle_walk[0][-1])
        if skip_walk:
            held_back, desk_held, cpu_held, idle_held, vlm_deferred = idle_walk[1]
        # The walk ends past the last unit of any pool with a free slot: no later unit can start.
        reach = max((last_of.get(sl, -1) for sl, v in free.items() if v > 0), default=-1)
        for i, (u, ukey, uslot) in enumerate(itertools.chain(((v, key_of(v), slot_of(v)) for v in fill), zip(queue, qkeys, qslots))
                                             if reach >= 0 and not skip_walk else (), -len(fill)):
            if i > reach or media.held():
                break  # (the media share noted down this pass: nothing more starts until it answers)
            if not may_start() or free[uslot] <= 0 or ukey in tried:
                continue
            if reserve and ukey not in fill_keys and not uslot.startswith("fetch ") and ceiling_left <= reserve:
                reserve_hit = True  # the last slots are for reads that ask the VLM
                continue
            if (cpu_cap is not None and cpu_live >= cpu_cap and cpu_only_unit(u) and ukey not in fill_keys
                    and not (listener_wide and uslot == "listener")):  # no VLM-asking read is due to keep slots for
                cpu_capped = True  # the GPU is underfed: the rest of the ceiling is for reads that ask the VLM
                continue
            if urgent and u["kind"] != "fetch" and u["rank"] >= fa.BLANKET and not newest_first(u):
                continue
            # Held before its ledger row is checked: stood() stats the
            # edition's files, and a held scan is asked again every pass.
            if u["kind"] == "scan" and ukey not in firsts and ukey not in fill_keys and fed(u) and not newest_first(u):
                continue
            try:
                stands_now = u["kind"] == "scan" and u["paper"] in fa.FILERS and stood(u)
            except OSError as e:  # its ledger or files on the media share, which did not answer (10-20, 10-23)
                if not media.down(e):
                    raise
                break
            if stands_now:
                # Scanned since the plan was made (a kept plan, a read, another queue): its reads may go on.
                tried.add(ukey)
                scanned.add((u["paper"], u["rel"]))
                continue
            if u["kind"] == "read" and waits(u):
                if (u["paper"], u["rel"]) in unscanned and (u["paper"], u["rel"]) in scan_failed:
                    tried.add(ukey)
                continue
            # A game stops the VLM: no read starts (nor a scan its desktop deferred) while it yields;
            # scans and fetches go on (CPU work).
            # Nor does a scan during a game beyond CT_GAME_SCAN_WORKERS running (the rest are shed).
            if starved or (yielding and (u["kind"] == "read" or ukey in yield_held
                                         or (u["kind"] == "scan" and (not yield_opt_in or (game and live_scans >= game_scans()))))):
                continue
            if vlm_waits(u):
                vlm_deferred += ukey not in spool_wait and ukey not in full_wait and ukey not in defer_until  # a read for the drainer is no "VLM down"
                continue
            if vlm_full and u["kind"] == "read":
                continue
            if costs is None:
                costs = mem_gate.unit_costs({pid: slot_of(v) for pid, (v, _) in units_running()})
            cost = costs.get(uslot, mem_gate.UNIT)
            if not held_back and (charged, cost) not in mem_read:
                mem_read[charged, cost] = mem_gate.room(charged, mem_gate_reader, unit=cost)
            if held_back or not mem_read[charged, cost]:
                held_back = True
                continue
            if not load_gated(u):
                if desk_held or not desktop_room(desk_mem, opened, closed):
                    desk_held = True
                    continue
            if load_gated(u):
                if not cpu_held and begun_now not in cpu_read:
                    cpu_read[begun_now] = mem_gate.cpu_room(begun_now, cpu_gate_reader)
                if cpu_held or not cpu_read[begun_now]:
                    cpu_held = True
                    continue
            local = local_cpu(u)
            if local:
                if not idle_held and local_now not in idle_read:
                    idle_read[local_now] = mem_gate.idle_room(local_now, idle_gate_reader)
                if idle_held or not idle_read[local_now]:
                    idle_held = True
                    continue
            # Answers-linked rereads of one item go in one process: the setup is ~all of their cost.
            # (An edition of a batch that ended deferred is read alone from then on: one needing the VLM's
            # asks would end its whole batch again, the other editions unread.)
            began = start(u, [] if ukey in unbatched else batch_mates(
                u, read_cands, tried, busy | unbatched,
                lambda v: not waits(v) and not vlm_waits(v) and key_of(v) not in firsts))
            if not began and began is not PENDING:
                unscanned.add((u["paper"], u["rel"]))
                continue
            if ukey in fill_keys:
                log(f"vlm feed: start {ukey[0]} {ukey[1]} {ukey[2]} ({u.get('reason') or 'rank ' + str(u['rank'])}; "
                    f"{len(queued)} asks spooled, target {vlm_feed_target()})")
            # A unit whose brief is being made holds its slot and its gates' charges as if begun.
            local_now += local
            begun_now += 1
            live_scans += u["kind"] == "scan"
            cpu_live += cpu_only_unit(u)
            charged += cost
            if began is not PENDING and not load_gated(u):
                opened.append(time.time())
            free[uslot] -= 1
            if not uslot.startswith("fetch "):
                ceiling_left -= 1
                if ceiling_left <= 0:
                    free.update({sl: 0 for sl in free if not sl.startswith("fetch ")})
            if free[uslot] <= 0:
                reach = max((last_of.get(sl, -1) for sl, v in free.items() if v > 0), default=-1)
            if began is PENDING:
                continue
            if u["kind"] == "scan":
                scanning.add((u["paper"], u["rel"]))
                scanning_by.setdefault(u["paper"], set()).add(u["rel"])
        if not skip_walk:
            if len(full_held) != spool_held[0] and (time.monotonic() - spool_held[1] >= 60 or len(full_held) // 10 != spool_held[0] // 10):
                spool_held[:] = [len(full_held), time.monotonic()]
                if full_held:
                    log(f"spool full: {len(full_held)} reads that ended deferred for it held until it is below its cap "
                        f"({len(queued)} asks spooled, CT_VLM_SPOOL_MAX {vlm_spool_max()}); reads with spooled asks go on")
            if reserve_hit and not reserve_bound:
                log(f"slot reserve: {reserve} of {mem_gate.unit_ceiling()} unit slots held for VLM-asking reads "
                    f"({len(queued)} asks spooled, target {vlm_feed_target()}); other starts wait")
            reserve_bound = reserve_hit
            if cpu_capped and not cpu_cap_bound:
                log(f"cpu-only cap: {cpu_live} stale scans/answer-linked rereads running of {cpu_cap} allowed "
                    f"while {len(queued)} asks spooled (target {vlm_feed_target()}); the rest wait for VLM-asking reads")
            cpu_cap_bound = cpu_capped
        if walked and not skip_walk and not begun_now:
            idle_walk[:] = [idle_key((tuple(sorted(mem_read.items())), tuple(sorted(cpu_read.items())),
                                      tuple(sorted(idle_read.items())))),
                            (held_back, desk_held, cpu_held, idle_held, vlm_deferred)]
        elif not skip_walk:
            idle_walk[:] = [None, None]
        if held_back and not memory_bound:
            memory_bound = True
            log(f"memory-bound: {((mem_gate_reader or mem_gate.available)() or 0) >> 20} MB available, floor {mem_gate.FLOOR >> 20} MB, "
                f"memory pressure {mem_gate.pressure()} (max {mem_gate.psi_max()}), "
                f"{charged >> 20} MB charged to {begun_now} begun this pass; a unit costs "
                + ", ".join(f"{k} {v >> 20} MB" for k, v in sorted((costs or {}).items()))
                + f" (else {mem_gate.UNIT >> 20} MB); no unit starts until a later pass finds room "
                f"({len(running) + len(adopted)} running are left alone)")
        if desk_held and not desk_mem_bound:
            log(f"desktop-memory-bound: {desk_mem[1]} MB free there {time.time() - desk_mem[0]:.0f}s ago, "
                f"{desktop_sessions(desk_mem[0], opened, closed)} session(s) opened since and still open "
                f"at {DESKTOP_SESSION_MB} MB each, "
                f"floor {DESKTOP_FLOOR_MB} MB; only fetches start until it has room "
                f"({len(running) + len(adopted)} running are left alone)")
        desk_mem_bound = desk_held
        if walked:
            vlm_pending[0] = vlm_deferred
        if vlm_deferred and (vlm_logged[0] is None or time.monotonic() - vlm_logged[0] >= 600):
            vlm_logged[:] = [time.monotonic(), vlm_deferred]
            log(f"VLM down ({vlm_reader.cause() or 'unreachable'}): {vlm_deferred} scans deferred; their reads start once it answers, "
                f"scans, fetches and reads that do not ask it go on ({len(running) + len(adopted)} running)")
        if cpu_held and not cpu_bound:
            cpu_bound = True
            log(f"cpu-bound: load over {mem_gate.LOAD_PER_CORE:g} per core; only units the desktop reads start until it falls "
                f"({len(running) + len(adopted)} running are left alone)")
        if idle_held and not idle_bound:
            idle = (idle_gate_reader or mem_gate.idle_cores)()
            log(f"idle-bound: {idle if idle is None else round(idle, 1)} idle core(s), {local_now} local unit(s) "
                f"begun this pass; no unit that works on this host's CPU (local_cpu) starts until a core "
                f"is idle, those waiting on the desktop or the network go on "
                f"({sum(local_cpu(v) for _, (v, _) in units_running())} local running are left alone)")
        idle_bound = idle_held
        if stop:
            break
        if handoff and not may_start() and not any(b.busy() for b in beside):
            left = sum(k not in tried for k in qkeys) + len(running) + len(adopted)
            thaw()
            hand_over(handoff, units_running())
            keep_untried()
            log(f"slice over: {len(running) + len(adopted)} unit(s) handed over to the next run, still running")
            running.clear()
            adopted.clear()
            break
        if not running and not adopted and planner is None and not any(b.busy() for b in beside) and not (
                media.held() and may_start()):
            untried = sum(k not in tried for k in qkeys)
            if not may_start():
                left = untried + sum(b.again and not b.done for b in beside)
                break
            if not untried:
                # Nothing left to start: one more plan, in case something
                # landed, made on the new code when it changed.
                if may_reexec() and any(digest(f) != h for f, h in code.items()):
                    reexec()
                try:
                    scans, reads, fetches = replan_all()
                    new_scans, new_reads = fresh(papers, cache)
                except OSError as e:
                    if not media.down(e):
                        raise
                    continue  # planned again once the media share answers (media.hold)
                fresh_scans, fresh_reads = unchanged_eq(fresh_scans, new_scans), unchanged_eq(fresh_reads, new_reads)
                fresh_at = time.monotonic()
                fetches = unchanged(fetches, [u for u in fetches if u["paper"] not in stopped])
                planned = time.monotonic()
                if all(key_of(u) in tried for u in first + fresh_scans + fresh_reads + scans + reads + fetches) and not any(b.again and not b.done
                                                                             for b in beside):
                    break
                continue
        # Only reads waiting for the VLM left to start, and nothing running:
        # look again every VLM_IDLE seconds (vlm_up is asked once a minute).
        drop_stale_briefs()
        if vlm_deferred and not begun_now and not running and not adopted:
            time.sleep(VLM_IDLE)
        elif not begun_now and not any(v > 0 for v in free.values()):
            nap(1 if game_now[0] else QUIET_NAP)  # a game: shed scans past the cap soon. Every slot full: only an exit (or a stop) can change what this pass would start
        else:
            time.sleep(1)
    if stop:
        log(f"stop asked: TERM to {len(running) + len(adopted)} running unit(s), up to {STOP_GRACE}s")
        thaw()  # SIGCONT first: a stopped filer would sit on the TERM, then be left stopped
        for pid in list(running) + list(adopted):
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for b in beside:
            b.stop(signal.SIGTERM)
        end = time.monotonic() + STOP_GRACE
        while (running or adopted) and time.monotonic() < end:
            reap()
            reap_adopted()
            time.sleep(0.2)
        for pid in list(running) + list(adopted):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for b in beside:
            b.stop(signal.SIGKILL)
        reap()
        if media_gone:
            print(f"edition queue: the media share stayed down; {media_gone[0]}")
            return 1
        return 143
    print(f"edition queue: {len(tried)} units started; " + ", ".join(f"{v} {k}" for k, v in sorted(outcomes.items())))
    if vlm_pending[0]:
        print(f"  VLM down: {vlm_pending[0]} scans deferred")
    if left:
        print(f"  {left:5d}  left for the next run")
    if reload:
        print(f"reload: {reload[0]}; exiting {hot_reload.RELOAD_RC} for the wrapper to move the tree and start again")
        return hot_reload.RELOAD_RC
    return 0


def alive(pid):
    """Whether process `pid` still runs (a zombie has ended)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def child(pid):
    """Whether `pid` is this process's child (one it started before a
    re-exec): ended or not, reap() collects its status."""
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1]) == os.getpid()
    except (OSError, IndexError, ValueError):
        return False


#: How old a kept plan (keep_plan) a run may start from.
PLAN_KEPT = 7200

#: Under this many seconds old, a kept plan a run starts from also stands as
#: that run's own whole plan: a re-exec on a code change (261 in full_pass.log,
#: each replanning 55-175 s, up to ~1600 s under load) no longer replans.
PLAN_REUSE = 600


def plan_version(code):
    """What a kept plan depends on besides its arguments, so a plan kept by
    other code, scan keys or environment is not started from (a restart after
    a change started units the new code would have skipped): the digests of
    the planner's own files (`code`, code_files()), each paper's scan key and
    the solution key, CT_NEWEST_FIRST and the request files' path."""
    own = [code.get(Path(f).resolve()) for f in (__file__, fa.__file__, scan_queue.__file__)]
    keys = [sorted(fa.current_keys(p)) for p in fa.FILERS.values()]
    return json.loads(json.dumps([own, keys, fa.solution_key(), sorted(newest_first_papers()),
                                  str(scan_queue.REQUESTS)], default=str))


def keep_plan(path, key, made, at, took=0.0):
    """Save plan `made` (scans, reads, fetches), made at `at` (time.time())
    in `took` seconds, for a run with `key`'s arguments."""
    tmp = Path(f"{path}.tmp")
    tmp.write_text(json.dumps({"key": key, "at": at, "took": took, "plan": made}))
    tmp.replace(path)


def last_plan(path, key):
    """(the plan keep_plan saved at `path` for these arguments, when it was
    made, how long it took), if under PLAN_KEPT seconds old, else
    (None, None, 0.0): its units may be done by now, and each says so as it
    starts (\"current\")."""
    try:
        kept = json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        return None, None, 0.0
    if kept.get("key") != json.loads(json.dumps(key)) or time.time() - kept.get("at", 0) > PLAN_KEPT:
        return None, None, 0.0
    return tuple(kept["plan"]), kept["at"], kept.get("took", 0.0)


def keep_defers(path, runs, until):
    """Save the deferral backoff (DEFER_BACKOFF) at `path`, beside the hand-over, so a
    re-exec does not restart the backed-off reads at once: [key, runs, wall time until]."""
    now_wall, now = time.time(), time.monotonic()
    rows = [[list(k), n, now_wall + (until[k] - now) if k in until else 0] for k, n in runs.items()]
    tmp = Path(f"{path}.tmp")
    tmp.write_text(json.dumps(rows))
    tmp.replace(path)


def last_defers(path):
    """(defer_runs, defer_until) the last run kept at `path`; a read whose wait ended
    over DEFER_BACKOFF_MAX seconds ago is forgotten (its run count would restart too)."""
    try:
        rows = json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        return {}, {}
    now_wall, now = time.time(), time.monotonic()
    runs, until = {}, {}
    for k, n, at in rows:
        if at < now_wall - DEFER_BACKOFF_MAX:
            continue
        runs[tuple(k)] = n
        if at > now_wall:
            until[tuple(k)] = now + (at - now_wall)
    return runs, until


def hand_over(path, units):
    """Write the units still running for the next run to take on."""
    now_wall, now = time.time(), time.monotonic()
    rows = [{"pid": pid, "unit": unit, "startedAt": now_wall - (now - t0)} for pid, (unit, t0) in units]
    tmp = Path(f"{path}.tmp")
    tmp.write_text(json.dumps(rows))
    tmp.replace(path)


def take_over(path):
    """{pid: (unit, started)} of the units a run handed over at `path` that
    still run or are this process's children; the file is removed."""
    try:
        rows = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    Path(path).unlink()
    now_wall, now = time.time(), time.monotonic()
    return {r["pid"]: (r["unit"], now - (now_wall - r["startedAt"])) for r in rows if alive(r["pid"]) or child(r["pid"])}


def ledger_upkeep(papers, cache):
    """Re-key and fold each paper's ledger (under its lock, so units append
    meanwhile): tens of seconds on the media mount."""
    for key in [k for k in papers if k != "listener"]:
        ledger = media_manifest.trove_ledger(ftp.CACHE) if key == "trove" else fa.ledger_of(cache, fa.FILERS[key])
        if key != "trove" and (n := fa.rekey_scans(ledger)):
            log(f"{ledger.name}: {n} scans re-keyed to the narrowed scan key")
        if key == "trove" and (n := ftp.rekey_unchanged(ledger)):
            log(f"{ledger.name}: {n} articles re-keyed: their files are as they were read")
        # No fold here (scan_queue.compact, kept for a ledger no other machine writes): replacing a
        # ledger the Mac also appends to leaves its SMB client writing at the old, longer EOF, which
        # tore filed-gale.jsonl (a partial row, hundreds of NULs, a full row; 10-21). Readers keep
        # the last row a key (scan_queue.ledger_rows), so duplicates only cost file size.


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("unit", help="run one unit (the queue starts these; CT_EDITION_UNIT holds it)")
    u.add_argument("kind")
    u.add_argument("paper")
    u.add_argument("rel")
    for name in ("run", "plan"):
        p = sub.add_parser(name)
        p.add_argument("--paper", action="append", choices=PAPERS, help="default: every paper, in PAPERS order")
        p.add_argument("--cache", type=Path, default=fa.CACHE)
        p.add_argument("--reread", metavar="BEFORE", help="re-read every edition last read before BEFORE (ISO)")
        p.add_argument("--fetch", action="append", default=[], choices=sorted(FETCHERS),
                       help="this source's fetch units too, each source in a pool of its own")
    r = sub.choices["run"]
    r.add_argument("--out", type=Path, help="where a puzzle with a blank clue goes (file_archive_org_puzzles --out)")
    r.add_argument("--seconds", type=float, help="start no unit after this many seconds")
    r.add_argument("--workers", type=int, default=WORKERS, help="reads at once")
    r.add_argument("--scan-workers", type=int, default=scan_cap())
    r.add_argument("--handoff", type=Path, metavar="FILE",
                   help="take on the units a run handed over in FILE; after --seconds, hand those still "
                        "running over there and end at once")
    r.add_argument("--resume", type=Path, metavar="FILE", help="take on the units this run's own image handed "
                   "over in FILE before re-exec'ing on a code change")
    r.add_argument("--trove-workers", type=int, default=TROVE_WORKERS, help="Trove article reads at once")
    r.add_argument("--wait", action="store_true", help="accepted for tools/ocr_full_pass.sh's slices; units never wait")
    r.add_argument("--beside", action="append", default=[], metavar="COMMAND",
                   help="a batch filer taking --seconds to run beside the units (shell words), again while it "
                        "leaves work")
    args = ap.parse_args(argv)
    if args.cmd == "unit":
        return unit_main(json.loads(os.environ["CT_EDITION_UNIT"]))
    papers = args.paper or PAPERS
    reread = scan_queue.when(args.reread)
    if args.cmd == "plan":
        notes = []
        scans, reads = plan(papers, args.cache, reread, notes)
        for n in notes:
            print(n)
        print(f"{len(fresh(papers, args.cache)[1])} reads just laid out, started before any of these")
        for kind, units in (("scans", scans), ("reads", reads)):
            counts = {}
            for u in units:
                counts[(u["rank"], u["paper"], u["reason"])] = counts.get((u["rank"], u["paper"], u["reason"]), 0) + 1
            print(f"{len(units)} {kind} due")
            for (rank, paper, reason), n in sorted(counts.items()):
                print(f"  rank {rank}  {paper:9s} {reason:22s} {n:6d}")
        likely = {}
        for u in reads:
            for fix, n in (u.get("likely") or {}).items():
                k = likely.setdefault((u["rank"], u["paper"], fix), [0, 0])
                k[0], k[1] = k[0] + 1, k[1] + n
        print(f"{sum(bool(u.get('likely')) for u in reads)} reads first in their rank: predicted to file puzzles whole")
        for (rank, paper, fix), (n, whole) in sorted(likely.items()):
            print(f"  rank {rank}  {paper:9s} {fix:38s} {n:6d} reads {whole:6d} puzzles")
        fetches = plan_fetches(args.fetch)
        if args.fetch:
            print(f"{len(fetches)} fetches due")
        counts = {}
        for u in fetches:
            counts[(u["paper"], u["reason"])] = counts.get((u["paper"], u["reason"]), 0) + 1
        for (src, reason), n in sorted(counts.items()):
            print(f"  {src:11s} {reason:22s} {n:6d}")
        return 0
    try:
        return dispatch(papers, args.cache, args.out, reread, args.seconds, args.workers, args.scan_workers,
                        [shlex.split(b) for b in args.beside], fetch=args.fetch, trove_workers=args.trove_workers,
                        handoff=args.handoff, resume=args.resume,
                        # A re-exec onto new code keeps its slice's ledgers: their upkeep ran at the slice's start.
                        upkeep=None if args.resume else lambda: ledger_upkeep(papers, args.cache))
    except OSError as e:
        import downloads
        if not downloads.media_down(e):
            raise
        return media_restart(e)


def media_restart(e, gate=None, execv=None):
    """The dispatch loop met the media share down (`e`, downloads.media_down) where it does
    not wait for it itself: wait for it (MediaGate), then hand the running units to a new
    image (dispatch's reexec; else re-exec as started). A share that answers at the first
    probe raises `e` again: that path's error is a bug, not an outage. 1 past CT_MEDIA_WAIT."""
    gate = gate or MediaGate()
    gate.down(e)

    def stopped(signum, _frame):  # dispatch's handlers are gone with it: a stop TERMs its units and ends
        for pid in (_media_reexec[1]() if _media_reexec[1] else ()):
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        raise SystemExit(128 + signum)
    if execv is None:
        signal.signal(signal.SIGTERM, stopped)
        signal.signal(signal.SIGINT, stopped)
    try:
        gate.wait()
    except MediaGone as gone:
        log(f"media down: giving up, {gone}")
        return 1
    if not gate.seen_down:
        raise e
    why = f"media back: the loop met it down ({type(e).__name__}: {e})"
    if _media_reexec[0] is not None and execv is None:
        _media_reexec[0](why)
    log(f"{why}; re-exec")
    sys.stdout.flush()
    sys.stderr.flush()
    (execv or os.execv)(sys.executable, [sys.executable, *sys.argv])
    return 0


if __name__ == "__main__":
    sys.exit(main())
