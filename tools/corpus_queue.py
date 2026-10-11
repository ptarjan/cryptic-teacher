#!/usr/bin/env python3
"""The standing corpus OCR job: tools/ocr_full_pass.sh, one run at a time.

    python3 tools/corpus_queue.py status             # running, held or idle, and how the last pass ended
    python3 tools/corpus_queue.py tick [--dry-run]   # check the running pass, else start one
    python3 tools/corpus_queue.py chain              # (the pass's last step) start the next at once if it fetched
    python3 tools/corpus_queue.py adopt PID          # a pass started by hand is this queue's
    python3 tools/corpus_queue.py stop               # stop the pass (it commits what it filed first) and hold it
    python3 tools/corpus_queue.py release            # let a held pass start again

There is one job and it takes no edition list. Its archive.org, Gale and
Trove reads and its fetches (archive.org editions, Trove clue zones and
articles) are tools/edition_queue.py's units, one per source (each its own
process, time limit, lock and ledger row; new input first, planned every
minute), so a fetcher change such as a DETECTOR_VERSION bump is fetched by
the same pass. The scan filers decide what
is due (each one's due_reason: never read, inputs changed, read without the
VLM that now answers, read before ocr_full_pass.sh's REREAD_BEFORE) and the
pass reads all of it, plus the open annotation re-read requests, then ends.
So a reader change that should change past readings bumps REREAD_BEFORE,
and a VLM that was down when a source was read is used once it answers:
the next tick's pass reads them. A pass with nothing due ends in minutes.
A pass that finishes (exit 0) having fetched something (FETCHED moved) ran
its fetchers to their time limit or to the end of the backlog, so it starts
the next pass itself (chain: a tick --chained once its leader has exited),
and a backlog is fetched back to back, not a slice an hour; the first pass
that fetches nothing leaves the next start to the hourly tick.

One corpus job at a time. Another one is running when the pid in
~/.cache/corpus_queue/running.json is alive and started when it says (so a
recycled pid is not mistaken for it), or when a scan filer holds a ledger
lock (tools/scan_queue.py lock(): any filer run by hand). A tick that finds
either does nothing but check the pass's log: no new line for STALL_MINUTES
wakes the room once per stall. A pass that ends, not finished, without a
ledger row read or a scan fetched (FETCHED) is a dead launch; DEAD_LAUNCHES in a row hold the pass and
tell the room. The pass is its own session; when its leader is gone the
tick kills whatever of the session is left before it starts anything.

The pass runs under the bridge's tools/track-job.sh --run --restart (launch()):
a lane in the room's status while it runs, and a bridge restart that kills it
relaunches the same command, log and label. The session leader is track-job's
wrapper, and running.json's pid is that wrapper's (the pid track-job prints,
which is also the session id). The relaunched pass is not launch()'s child, so
the pass records itself: `begin` (its first step) writes running.json for its
own session, keeping the dead launch's ledger marks so the pass still counts
as one launch, and refuses to run beside another live pass (the hourly tick
may have started one in the gap). Resuming rather than redoing is the pass's
own: tools/durable.sh salvages what the killed run filed, and each filer skips
what is already filed. track-job wakes the room when a job ends and cannot be
quietened, so an ordinary end (exit 0) deregisters the job first (`finish`):
only a failed or killed pass wakes the room.

A stop is graceful: the pass's leader gets SIGTERM and up to STOP_GRACE
seconds to end, which it spends ending its filer and committing what it
filed (tools/durable.sh); only then is the rest of its session killed.
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
import downloads

ROOT = Path(__file__).resolve().parent.parent
FULL_PASS = ROOT / "tools" / "ocr_full_pass.sh"
HOME = Path(os.path.expanduser("~"))
STATE_DIR = HOME / ".cache" / "corpus_queue"
RUNNING = STATE_DIR / "running.json"
STATE = STATE_DIR / "state.json"
#: The pass's exit status, written when it ends; a killed pass writes none.
EXIT = STATE_DIR / "full_pass.exit"
LOG = STATE_DIR / "full_pass.log"
LEDGERS = [downloads.ARCHIVE_ORG / "filed.jsonl", downloads.GALE_LEDGER, downloads.TROVE / "filed.jsonl"]
#: What the pass's fetchers move when they fetch: the archive.org fetcher's
#: done.tsv, and the Trove caches' directories (an article fetched, or its
#: clue zones, is a new directory in them).
FETCHED = [downloads.ARCHIVE_ORG / "done.tsv", downloads.TROVE, downloads.TROVE_CLUES]
WAKE_SH = os.environ.get("WAKE_SH", "/Users/pt/github/household/tools/wake.sh")
TRACK_JOB = os.environ.get("TRACK_JOB", str(Path(WAKE_SH).parent / "track-job.sh"))
LABEL = "corpus OCR full pass"
ROOM = "cryptic-crosswords"
NAME = "full_pass"
STALL_MINUTES = 60
#: Launches in a row that end unfinished with no ledger row read before the pass is held.
DEAD_LAUNCHES = 2
#: What the pass's wrapper runs as it ends (command()): chain().
CHAIN = ["python3", str(ROOT / "tools" / "corpus_queue.py"), "chain"]
#: What chain() runs once the pass's leader has exited: a tick from the
#: queue's own worktree at origin/master, holding its lease, so it never
#: runs beside a scheduled tick.
CHAINED_TICK = [str(ROOT / "tools" / "corpus_queue.sh"), "tick", "--chained"]
#: How long chain() waits for the pass's leader to exit.
CHAIN_WAIT = 60
#: How long stop gives the pass, after SIGTERM, to end its filer and commit
#: what it filed (tools/durable.sh: DURABLE_STOP_GRACE plus a commit and push).
STOP_GRACE = 240


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))


def proc_start(pid):
    """The kernel's start time of `pid` (clock ticks since boot), None if it
    is gone or a zombie (exited, its parent not yet reaping it)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except OSError:
        return None
    return None if stat[0] == "Z" else stat[19]


def session_of(pid):
    """The session id of `pid`, None if it is gone or a zombie."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if stat[0] == "Z" else int(stat[3])
    except (OSError, IndexError, ValueError):
        return None


def ppid_of(pid):
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return None


def session_pids(sid):
    """Every live process in session `sid`."""
    out = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit() and session_of(p.name) == sid:
            out.append(int(p.name))
    return out


def end_session(sid, grace=10, leader_grace=0):
    """Kill whatever is left of a pass's session: launch() starts it as a
    session leader, so its filers and `timeout`s (which move their child into
    a process group of its own) all carry its pid as their session id, and
    the kernel does not reuse that number while any of them lives. With
    `leader_grace`, the leader alone is sent TERM first and given that many
    seconds to exit (the pass commits what it filed); then TERM to all,
    then KILL what is still there after `grace` seconds. Returns the pids."""
    if sid == os.getsid(0):
        return []
    if leader_grace and proc_start(sid) is not None:
        # The leader is track-job's wrapper, which a TERM kills outright; the
        # command it runs (which passes TERM to the pass and waits) is its child.
        try:
            wrapped = b"deprioritize.sh" in Path(f"/proc/{sid}/cmdline").read_bytes()
        except OSError:
            wrapped = False
        for pid in [p for p in session_pids(sid) if ppid_of(p) == sid] if wrapped else [sid]:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for _ in range(leader_grace * 10):
            if proc_start(sid) is None:
                break
            time.sleep(0.1)
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
    """running.json's record when its process is alive, else None."""
    try:
        r = json.loads(RUNNING.read_text())
    except (OSError, ValueError):
        return None
    return r if proc_start(r["pid"]) == r["start"] else None


def lock_of(ledger):
    return ledger.with_suffix(".lock")


def ledger_held():
    """The ledger lock a scan filer holds right now, or None."""
    for ledger in LEDGERS:
        path = lock_of(ledger)
        if not path.exists():
            continue
        with open(path, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return path
            fcntl.flock(f, fcntl.LOCK_UN)
    return None


def ledger_marks():
    """Each ledger's and FETCHED path's (size, mtime_ns): a filer saves its
    ledger after every source it reads and a fetcher moves its FETCHED path,
    so a mark that moved means the pass read or fetched something."""
    out = {}
    for ledger in LEDGERS + FETCHED:
        try:
            st = ledger.stat()
            out[str(ledger)] = [st.st_size, st.st_mtime_ns]
        except OSError:
            out[str(ledger)] = None
    return out


def wake(text, dry):
    text = "corpus queue: " + text
    if dry:
        print(f"[dry run] would wake #{ROOM}:\n{text}")
        return
    try:
        subprocess.run([WAKE_SH, "-c", ROOM, text[:1900]], timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"wake failed: {e}", file=sys.stderr)


def command():
    """What track-job runs: `begin` (records the pass as running; 3 means
    another pass is, and this one ends quietly), the full pass, `finish` (its
    exit status kept in EXIT, the job deregistered on exit 0), then CHAIN. A
    TERM to it (stop) is passed on to the pass, which commits what it filed
    before it exits, and waited for."""
    wrapper = ('python3 "$3" begin; b=$?; [ "$b" = 3 ] && exit 0; [ "$b" = 0 ] || exit "$b"; '
               'bash "$1" & p=$!; trap \'kill -TERM "$p" 2>/dev/null\' TERM INT HUP; wait "$p"; rc=$?; '
               'while kill -0 "$p" 2>/dev/null; do wait "$p"; rc=$?; done; python3 "$3" finish "$rc"; shift 3; "$@"')
    return ["bash", "-c", wrapper, NAME, str(FULL_PASS), str(EXIT), str(Path(__file__).resolve()), *CHAIN]


def tracked_jobs_dir():
    d = os.environ.get("TRACKED_JOBS_DIR") or (os.path.join(os.environ["STATE_DIR"], "tracked-jobs")
                                               if os.environ.get("STATE_DIR") else None)
    return Path(d) if d else None


def untrack(sid):
    """Stop track-job's bridge watching the job whose wrapper is pid `sid`, so
    its end does not wake the room (deleting its registry file is the
    documented way). Its exit-status file, written as it ends, is removed once
    the wrapper is gone."""
    d = tracked_jobs_dir()
    if not d or not d.is_dir():
        return
    for path in d.glob("*.json"):
        try:
            job = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if job.get("pid") != sid:
            continue
        path.unlink(missing_ok=True)
        exit_file = job.get("exit_file")
        if exit_file and not os.fork():
            os.setsid()
            for _ in range(600):
                if proc_start(sid) is None:
                    break
                time.sleep(1)
            Path(exit_file).unlink(missing_ok=True)
            os._exit(0)


def begin():
    """The pass's first step: make running.json name this session (the leader
    track-job started, or started again after a bridge restart). Returns 3 when
    another pass is alive: only one corpus job runs."""
    sid = os.getsid(0)
    start = proc_start(sid)
    try:
        old = json.loads(RUNNING.read_text())
    except (OSError, ValueError):
        old = {}
    if old.get("pid") != sid and proc_start(old.get("pid", 0)) == old.get("start") and old.get("start"):
        print(f"another full pass is running (pid {old['pid']}); this one does not start")
        untrack(sid)
        return 3
    if old.get("pid") == sid:
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    EXIT.unlink(missing_ok=True)
    RUNNING.write_text(json.dumps({
        "name": NAME, "pid": sid, "start": start, "ledgers": old.get("ledgers") or ledger_marks(),
        "launched": old.get("launched") or datetime.datetime.now().astimezone().isoformat(timespec="seconds")}))
    return 0


def finish(rc):
    """The pass's exit status goes to EXIT. An ordinary end (0) is not news:
    deregister the job so track-job's exit wake does not fire; a failed one
    stays registered and wakes the room."""
    EXIT.write_text(f"{rc}\n")
    if rc == 0:
        untrack(os.getsid(0))


def chain():
    """The pass's last step: leave its session (the next tick kills what is
    left of it) and, once its leader has exited, run CHAINED_TICK, which
    starts the next pass if this one finished having fetched something.
    Returns in the parent at once."""
    leader = os.getppid()
    sid = os.getsid(0)
    if os.fork():
        return
    os.setsid()
    try:  # the session leader is track-job's wrapper, which outlives the command by a moment
        wait_for = [leader] + ([sid] if json.loads(RUNNING.read_text()).get("pid") == sid else [])
    except (OSError, ValueError):
        wait_for = [leader]
    for _ in range(CHAIN_WAIT * 10):
        if all(proc_start(p) is None for p in wait_for):
            break
        time.sleep(0.1)
    os.execvp(CHAINED_TICK[0], CHAINED_TICK)


def launch(dry):
    """Start the pass under track-job --run --restart. Returns False if track-job did not start it."""
    if dry:
        print(f"[dry run] would start {TRACK_JOB} --restart ... -- {' '.join(command())}")
        return True
    for line in downloads.migrate():  # nothing is running: no job holds an old path
        print(line)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    EXIT.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("CT_IN_WORKTREE", "CT_MAIN_CHECKOUT")}
    marks = ledger_marks()  # before the pass can write a row
    done = subprocess.run([TRACK_JOB, "--log", str(LOG), "--restart", ROOM, "--run", LABEL,
                           f"tail -n 1 {LOG}", "--", *command()],
                          stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, env=env, cwd=ROOT, text=True)
    pid = done.stdout.strip()
    if done.returncode or not pid.isdigit():
        print(f"track-job did not start the full pass (exit {done.returncode}): {pid!r}", file=sys.stderr)
        return False
    pid = int(pid)  # the wrapper: the session leader, alive as long as the pass
    for _ in range(50):
        start = proc_start(pid)
        if start:
            break
        time.sleep(0.1)
    RUNNING.write_text(json.dumps({"name": NAME, "pid": pid, "start": start, "ledgers": marks,
                                   "launched": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}))
    print(f"started the full pass (pid {pid}); log {LOG}")
    return True


def stall_check(run, state, dry):
    log = LOG if run.get("name") == NAME else STATE_DIR / f"{run['name']}.log"
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
    try:
        RUNNING.unlink()
    except FileNotFoundError:
        return  # a tick beside this one (the pass's chained tick) reaped it and accounts for it
    if "ledgers" in r:
        account(r, state, dry)


def exit_status():
    try:
        return int(EXIT.read_text().strip())
    except (OSError, ValueError):
        return None


def account(r, state, dry):
    """A launch `r` (running.json's record) has ended: a pass that finished
    (exit 0) or read a source is progress; one that did neither is a dead
    launch, and DEAD_LAUNCHES in a row hold the pass."""
    rc, marks = exit_status(), ledger_marks()
    fetched = any(marks.get(str(p)) != r["ledgers"].get(str(p)) for p in FETCHED)
    state["lastExit"] = {"rc": rc, "fetched": fetched,
                         "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    if rc == 0 or marks != r["ledgers"]:
        state["deadLaunches"] = 0
    else:
        state["deadLaunches"] = state.get("deadLaunches", 0) + 1
    if state["deadLaunches"] >= DEAD_LAUNCHES:
        state["held"] = True
        wake(f"the full pass ended {state['deadLaunches']} times in a row unfinished (last exit "
             f"{'killed' if rc is None else rc}) without reading or fetching a source; held. Log: {LOG}. "
             "Clear with: corpus_queue.py release", dry)
    save_state(state)


def tick(dry, chained=False):
    """Start the full pass unless one runs, it is held, or a filer holds a
    ledger; `chained` (chain()) starts it only after a pass that finished
    having fetched something."""
    state, run = load_state(), running()
    if run:
        print(f"running: {run['name']} (pid {run['pid']}, since {run.get('launched', '?')})")
        stall_check(run, state, dry)
        return "running"
    if RUNNING.exists():
        reap(state, dry)
        state = load_state()
    if state.get("held"):
        print("the full pass is held; corpus_queue.py release lets it start again")
        return "held"
    last = state.get("lastExit") or {}
    if chained and not (last.get("rc") == 0 and last.get("fetched")):
        print("the last pass fetched nothing or did not finish; the hourly tick starts the next")
        return "idle"
    held = ledger_held()
    if held:
        print(f"a scan filer holds {held}; nothing started")
        return "busy"
    return "started" if launch(dry) else "failed"


def status():
    state, run = load_state(), running()
    held = ledger_held()
    if run:
        print(f"running: {run['name']} pid {run['pid']} since {run.get('launched', '?')}; log {LOG}")
    elif state.get("held"):
        print(f"held after {state.get('deadLaunches', 0)} dead launches; corpus_queue.py release")
    else:
        print("idle: the next tick starts the full pass" + (f" once the filer holding {held} ends" if held else ""))
    last = state.get("lastExit")
    if last:
        print(f"last pass ended {last['at']}: " + ("killed" if last["rc"] is None else f"exit {last['rc']}"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--chained", action="store_true", help="only after a pass that finished having fetched")
    sub.add_parser("chain", help="the pass's last step: start the next pass once it has exited, if it fetched")
    sub.add_parser("begin", help="(the pass's first step) record this session as the running pass")
    sub.add_parser("finish", help="(the pass's exit step) record its exit status").add_argument("rc", type=int)
    sub.add_parser("status")
    sub.add_parser("adopt").add_argument("pid", type=int)
    sub.add_parser("stop", help="kill the running pass and everything it started, and hold it")
    sub.add_parser("release")
    args = ap.parse_args(argv)
    if args.cmd == "status":
        status()
    elif args.cmd == "tick":
        tick(args.dry_run, args.chained)
    elif args.cmd == "chain":
        chain()
    elif args.cmd == "begin":
        sys.exit(begin())
    elif args.cmd == "finish":
        finish(args.rc)
    elif args.cmd == "adopt":
        start = proc_start(args.pid)
        if not start:
            sys.exit(f"pid {args.pid} is not running")
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        EXIT.unlink(missing_ok=True)
        RUNNING.write_text(json.dumps({"name": NAME, "pid": args.pid, "start": start, "adopted": True,
                                       "ledgers": ledger_marks(),
                                       "launched": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}))
        print(f"the full pass is pid {args.pid}")
    elif args.cmd == "release":
        state = load_state()
        state.update(held=False, deadLaunches=0)
        save_state(state)
    elif args.cmd == "stop":
        r = running()
        if not r:
            sys.exit("no corpus job is running")
        state = load_state()
        state["held"] = True
        save_state(state)
        print(f"held; stopping session {r['pid']} (up to {STOP_GRACE}s for it to commit what it filed)", flush=True)
        left = end_session(r["pid"], leader_grace=STOP_GRACE)
        print("stopped" + (f"; killed what its leader left running: {left}" if left else ""))
        RUNNING.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
