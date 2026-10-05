#!/usr/bin/env python3
"""The queue of corpus OCR jobs: refile lists and passes, run one at a time.

    python3 tools/corpus_queue.py status              # every job: done, running, next, blocked
    python3 tools/corpus_queue.py tick [--dry-run]    # check the running job, else start the next
    python3 tools/corpus_queue.py nightly [--dry-run] # coverage + wake the room if work is idle
    python3 tools/corpus_queue.py adopt NAME PID      # a job started by hand is this queue's job
    python3 tools/corpus_queue.py pass-gate NAME WHY  # NAME's precondition is met (WHY: the evidence)
    python3 tools/corpus_queue.py stop NAME           # kill NAME's whole session and hold it
    python3 tools/corpus_queue.py release NAME        # let a held job start again

The jobs, in order, are tools/data/corpus_queue.json. Each names a list of
archive.org editions (`list`, one "<item>/<slug>" a line) or the open
re-read requests (`"requested": true`, tools/scan_queue.py). Starting a job
splits it into 20-edition chunk files under its `chunks` directory
(~/.cache/corpus_queue/<name>.chunks unless the job names one);
tools/corpus_job.sh reads, commits and pushes a chunk at a time and deletes
it, so the directory is the job's progress and a restart resumes. A job is
done when its chunk directory is empty; a chunk that fails three times is
moved to its failed/ subdirectory, not retried forever.

One corpus job at a time. Another one is running when the pid in
~/.cache/corpus_queue/running.json is alive and started when it says (so a
recycled pid is not mistaken for it), or when a scan filer holds a ledger
lock (tools/scan_queue.py lock(): the archive.org and Trove filers,
ocr_full_pass.sh). A tick that finds either does nothing but check the
job's log: no new line for STALL_MINUTES wakes the room once per stall. A
job that ends twice in a row without finishing a chunk is held and the room
is told. Each job is its own session; when its leader is gone the tick kills
whatever of the session is left before it starts anything.

`gate` names something a person must check before the job may start; tick
stops there until pass-gate records it.
"""
import argparse
import datetime
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "tools" / "data" / "corpus_queue.json"
HOME = Path(os.path.expanduser("~"))
STATE_DIR = HOME / ".cache" / "corpus_queue"
RUNNING = STATE_DIR / "running.json"
STATE = STATE_DIR / "state.json"
LEDGER_LOCKS = [HOME / ".cache" / "archive_org_editions" / "filed.lock", HOME / ".cache" / "trove" / "filed.lock"]
WAKE_SH = os.environ.get("WAKE_SH", "/Users/pt/github/household/tools/wake.sh")
ROOM = "cryptic-crosswords"
CHUNK = 20
STALL_MINUTES = 60
#: Launches of one job in a row that finish no chunk before it is held.
DEAD_LAUNCHES = 2


def expand(p):
    return Path(os.path.expanduser(p))


def jobs():
    return json.loads(QUEUE.read_text())["jobs"]


def chunks_dir(job):
    return expand(job["chunks"]) if job.get("chunks") else STATE_DIR / f"{job['name']}.chunks"


def chunk_files(d):
    """The chunk files in directory `d`: c_* with no suffix (not .tries, .left)."""
    return sorted(c for c in Path(d).glob("c_*") if "." not in c.name and c.is_file())


def remaining(job):
    d = chunks_dir(job)
    return chunk_files(d) if d.is_dir() else None


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"gates": {}, "jobs": {}}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))


def proc_start(pid):
    """The kernel's start time of `pid` (clock ticks since boot), None if it is gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return stat.rsplit(")", 1)[1].split()[19]


def session_of(pid):
    """The session id of `pid`, None if it is gone."""
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[3])
    except (OSError, IndexError, ValueError):
        return None


def session_pids(sid):
    """Every live process in session `sid`."""
    out = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit() and session_of(p.name) == sid:
            out.append(int(p.name))
    return out


def end_session(sid, grace=10):
    """Kill whatever is left of a job's session: launch() starts each job as a
    session leader, so its reindex, filer and `timeout` (which moves its child
    into a process group of its own) all carry the job's pid as their session
    id, and the kernel does not reuse that number while any of them lives.
    TERM, then KILL what is still there after `grace` seconds. Returns the pids."""
    if sid == os.getsid(0):
        return []
    pids = session_pids(sid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        if sig == signal.SIGKILL:
            break
        for _ in range(grace * 10):
            if not session_pids(sid):
                return pids
            time.sleep(0.1)
    return pids


def running():
    """running.json's job when its process is alive, else None."""
    try:
        r = json.loads(RUNNING.read_text())
    except (OSError, ValueError):
        return None
    return r if proc_start(r["pid"]) == r["start"] else None


def ledger_held():
    """The ledger lock a scan filer holds right now, or None."""
    for path in LEDGER_LOCKS:
        if not path.exists():
            continue
        with open(path, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return path
            fcntl.flock(f, fcntl.LOCK_UN)
    return None


def status_of(job, state, run):
    rest = remaining(job)
    if run and run["name"] == job["name"]:
        return "running"
    if rest == []:
        return "done"
    if state["jobs"].get(job["name"], {}).get("held"):
        return "held"
    if job.get("gate") and job["name"] not in state["gates"]:
        return "gated"
    return "partial" if rest else "pending"


def editions_of(job):
    """The editions `job` still has to read: its chunks once split, else its list."""
    rest = remaining(job)
    if rest is not None:
        return [ln.strip() for c in rest for ln in c.read_text().splitlines() if ln.strip()]
    if job.get("requested"):
        return requested()
    try:
        return [ln.strip() for ln in expand(job["list"]).read_text().splitlines() if ln.strip()]
    except OSError:
        return []


def requested():
    """The editions open re-read requests name (tools/scan_queue.py requested)."""
    out = []
    for paper in ("times", "ft", "guardian", "telegraph"):
        p = subprocess.run([sys.executable, str(ROOT / "tools" / "scan_queue.py"), "requested", "archive", paper],
                           capture_output=True, text=True, cwd=ROOT, check=False)
        out += [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
    return out


def queued_editions():
    """Every edition a job not yet done still has to read."""
    state, run = load_state(), running()
    out = set()
    for job in jobs():
        if status_of(job, state, run) != "done" and not job.get("requested"):
            out.update(editions_of(job))
    return out


def split(job):
    """Write `job`'s chunk files, CHUNK editions each, one paper a chunk:
    c_<NNN>_<paper>_<series>."""
    import file_archive_org_puzzles as filer  # the item patterns, from the filer itself
    by_paper = {}
    for ed in editions_of(job):
        paper = next((p for p in filer.PAPERS.values() if p.item.match(ed.split("/")[0])), None)
        if paper is None:
            print(f"{job['name']}: {ed} is no archive.org paper the filer reads; left out", file=sys.stderr)
            continue
        by_paper.setdefault(paper, []).append(ed)
    d = chunks_dir(job)
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for paper, eds in by_paper.items():
        for i in range(0, len(eds), CHUNK):
            n += 1
            (d / f"c_{n:03d}_{paper.key}_{paper.series}").write_text("\n".join(eds[i:i + CHUNK]) + "\n")
    return n


def wake(text, dry):
    text = "corpus queue: " + text
    if dry:
        print(f"[dry run] would wake #{ROOM}:\n{text}")
        return
    try:
        subprocess.run([WAKE_SH, "-c", ROOM, text[:1900]], timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"wake failed: {e}", file=sys.stderr)


def log_path(name):
    """Where job `name` writes: its `log`, else ~/.cache/corpus_queue/<name>.log."""
    job = next((j for j in jobs() if j["name"] == name), {})
    return expand(job["log"]) if job.get("log") else STATE_DIR / f"{name}.log"


def launch(job, dry):
    rest = remaining(job)
    if rest is None and not dry:
        print(f"{job['name']}: split into {split(job)} chunks")
    if dry:
        print(f"[dry run] would start {job['name']}: {len(editions_of(job))} editions left")
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("CT_IN_WORKTREE", "CT_MAIN_CHECKOUT")}
    with open(log_path(job["name"]), "a") as log:
        p = subprocess.Popen(["bash", str(ROOT / "tools" / "corpus_job.sh"), job["name"], str(chunks_dir(job))],
                             stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True, env=env, cwd=ROOT)
    for _ in range(50):
        start = proc_start(p.pid)
        if start:
            break
        time.sleep(0.1)
    RUNNING.write_text(json.dumps({"name": job["name"], "pid": p.pid, "start": start,
                                   "launched": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}))
    state = load_state()
    js = state["jobs"].setdefault(job["name"], {})
    js["launches"] = js.get("launches", 0) + 1
    js["remainingAtLaunch"] = len(remaining(job) or [])
    save_state(state)
    print(f"started {job['name']} (pid {p.pid}); log {log_path(job['name'])}")


def stall_check(run, state, dry):
    log = log_path(run["name"])
    if not log.exists():
        return
    age = (time.time() - log.stat().st_mtime) / 60
    key = f"{run['name']}@{int(log.stat().st_mtime)}"
    if age < STALL_MINUTES or state.get("stallAlerted") == key:
        return
    tail = log.read_text(errors="replace").splitlines()[-5:]
    wake(f"{run['name']} (pid {run['pid']}) has written nothing to {log} for {age:.0f} min. "
         "Last lines:\n" + "\n".join(t[:200] for t in tail), dry)
    if not dry:
        state["stallAlerted"] = key
        save_state(state)


def reap(state, dry):
    """running.json names a job whose leader is no longer running: kill what
    is left of its session, then account for the launch."""
    try:
        r = json.loads(RUNNING.read_text())
    except (OSError, ValueError):
        return
    if dry:
        print(f"[dry run] {r['name']} (pid {r['pid']}) has exited; would end session {r['pid']}: "
              f"{session_pids(r['pid'])}")
        return
    left = end_session(r["pid"])
    if left:
        print(f"{r['name']}: killed {len(left)} leftover processes of its session ({left})")
    RUNNING.unlink()
    account(r["name"], state, dry)


def account(name, state, dry):
    """A launch of job `name` has ended: count whether it finished a chunk,
    and hold the job after DEAD_LAUNCHES in a row that did not."""
    job = next((j for j in jobs() if j["name"] == name), None)
    if job is None:
        return
    js = state["jobs"].setdefault(job["name"], {})
    left = len(remaining(job) or [])
    if left and left >= js.get("remainingAtLaunch", left + 1):
        js["deadLaunches"] = js.get("deadLaunches", 0) + 1
    else:
        js["deadLaunches"] = 0
    if left and js["deadLaunches"] >= DEAD_LAUNCHES:
        js["held"] = True
        wake(f"{job['name']} exited {js['deadLaunches']} times without finishing a chunk ({left} left); "
             f"held. Log: {log_path(job['name'])}. Clear with: corpus_queue.py release {job['name']}", dry)
    save_state(state)


def tick(dry):
    state, run = load_state(), running()
    if run:
        print(f"running: {run['name']} (pid {run['pid']}, since {run.get('launched', '?')})")
        stall_check(run, state, dry)
        return "running"
    if RUNNING.exists():
        reap(state, dry)
    held = ledger_held()
    if held:
        print(f"a scan filer holds {held}; nothing started")
        return "busy"
    for job in jobs():
        st = status_of(job, state, None)
        if st in ("done", "held"):
            continue
        if st == "gated":
            print(f"blocked: {job['name']} waits on: {job['gate']}")
            return "gated"
        if not editions_of(job):
            print(f"{job['name']}: nothing to read")
            continue
        launch(job, dry)
        return "started"
    print("the queue is empty")
    return "empty"


def status():
    state, run = load_state(), running()
    for job in jobs():
        st = status_of(job, state, run)
        rest = remaining(job)
        failed = [c for c in (chunks_dir(job) / "failed").glob("c_*") if "." not in c.name] if chunks_dir(job).is_dir() else []
        n = len(editions_of(job)) if st != "done" else 0
        print(f"{st:8} {job['name']:<24} {n:5} editions left"
              + (f", {len(rest)} chunks" if rest else "")
              + (f", {len(failed)} chunks failed" if failed else "")
              + (f"  [gate: {job['gate']}]" if st == "gated" else ""))
    held = ledger_held()
    print("running job: " + (f"{run['name']} pid {run['pid']}" if run else "none")
          + (f"; a filer holds {held}" if held else ""))


def nightly(dry):
    import archive_coverage
    cov = archive_coverage.main(["--save"] if not dry else [])
    state, run = load_state(), running()
    busy = run["name"] if run else (str(ledger_held()) if ledger_held() else None)
    gated = next((j for j in jobs() if status_of(j, state, run) in ("gated", "held")), None)
    lines = []
    for s, c in cov["series"].items():
        fix = [k for k in c["classes"] if k["recoverable"] and k["editions"] > k["queued"]]
        if fix:
            lines.append(f"{s}: " + "; ".join(f"{k['class']} {k['editions'] - k['queued']}" for k in fix[:4]))
    if busy:
        print(f"a corpus job is running ({busy}); no wake")
        return
    if not lines and not gated:
        print("nothing recoverable left unqueued; no wake")
        return
    t = cov["series"].get("times")
    years = ""
    if t:
        prev = {}
        try:
            prev = json.loads((archive_coverage.STATE / "previous.json").read_text())["series"]["times"]["years"]
        except (OSError, ValueError, KeyError):
            pass
        years = " ".join(f"{y}:{c.get('filed', 0)}/{c.get('printed', 0)}"
                         + (f"({c.get('filed', 0) - prev[str(y)]['filed']:+d})"
                            if str(y) in prev and prev[str(y)].get("filed") != c.get("filed") else "")
                         for y, c in t["years"].items() if int(y) < 2000)
    text = ("no corpus job is running and fixable archive editions remain. Start the next fix "
            "(add a job to tools/data/corpus_queue.json, or pass its gate). "
            + (f"Queue stopped at {gated['name']}: {gated.get('gate') or 'held'}. " if gated else "")
            + "\nUnqueued recoverable editions: " + " | ".join(lines)
            + (f"\nTimes filed/printed (delta): {years}" if years else "")
            + "\nFull table: python3 tools/archive_coverage.py")
    wake(text, dry)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("tick", "nightly"):
        sub.add_parser(name).add_argument("--dry-run", action="store_true")
    sub.add_parser("status")
    a = sub.add_parser("adopt")
    a.add_argument("name")
    a.add_argument("pid", type=int)
    g = sub.add_parser("pass-gate")
    g.add_argument("name")
    g.add_argument("why")
    r = sub.add_parser("release")
    r.add_argument("name")
    s = sub.add_parser("stop", help="kill the running job and everything it started, and hold it")
    s.add_argument("name")
    c = sub.add_parser("chunks", help="the chunk files left in a directory, one path a line")
    c.add_argument("dir", type=Path)
    f = sub.add_parser("finished", help="corpus_job.sh's last act: clear running.json, start the next")
    f.add_argument("name")
    u = sub.add_parser("unread", help="the editions of a chunk file the ledger has not read since a time")
    u.add_argument("chunk", type=Path)
    u.add_argument("since")
    args = ap.parse_args(argv)
    names = {j["name"] for j in jobs()}
    if getattr(args, "name", None) and args.name not in names:
        sys.exit(f"no job {args.name!r} in {QUEUE}")
    if args.cmd == "status":
        status()
    elif args.cmd == "tick":
        tick(args.dry_run)
    elif args.cmd == "nightly":
        nightly(args.dry_run)
    elif args.cmd == "adopt":
        start = proc_start(args.pid)
        if not start:
            sys.exit(f"pid {args.pid} is not running")
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        RUNNING.write_text(json.dumps({"name": args.name, "pid": args.pid, "start": start, "adopted": True,
                                       "launched": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}))
        print(f"{args.name} is pid {args.pid}")
    elif args.cmd == "pass-gate":
        state = load_state()
        state["gates"][args.name] = {"why": args.why, "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
        save_state(state)
    elif args.cmd == "release":
        state = load_state()
        state["jobs"].setdefault(args.name, {}).update(held=False, deadLaunches=0)
        save_state(state)
    elif args.cmd == "finished":
        try:
            r = json.loads(RUNNING.read_text())
            if r["name"] == args.name:
                RUNNING.unlink()
        except (OSError, ValueError):
            pass
        # A job that ends with its chunks still there read none of them; it
        # counts like any other dead launch rather than starting itself again.
        account(args.name, load_state(), False)
        tick(False)
    elif args.cmd == "stop":
        r = running()
        if not r or r["name"] != args.name:
            sys.exit(f"{args.name} is not running")
        state = load_state()
        state["jobs"].setdefault(args.name, {})["held"] = True
        save_state(state)
        print(f"{args.name}: held; killed session {r['pid']}: {end_session(r['pid'])}")
        RUNNING.unlink()
    elif args.cmd == "chunks":
        for c in chunk_files(args.dir):
            print(c)
    elif args.cmd == "unread":
        sys.path.insert(0, str(ROOT / "tools"))
        import scan_queue
        rows = {r.get("edition"): r for r in scan_queue._rows(scan_queue.LEDGERS["archive"])}
        since = scan_queue.when(args.since)
        for ed in args.chunk.read_text().split():
            row = rows.get(ed)
            if row is None or scan_queue.read_before(row, since):
                print(ed)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "tools"))
    main()
