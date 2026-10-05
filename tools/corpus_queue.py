#!/usr/bin/env python3
"""The standing corpus OCR job: tools/ocr_full_pass.sh, one run at a time.

    python3 tools/corpus_queue.py status             # running, held or idle, and how the last pass ended
    python3 tools/corpus_queue.py tick [--dry-run]   # check the running pass, else start one
    python3 tools/corpus_queue.py nightly [--dry-run]# coverage; wake the room when the pass needs a person
    python3 tools/corpus_queue.py adopt PID          # a pass started by hand is this queue's
    python3 tools/corpus_queue.py stop               # kill the pass's whole session and hold it
    python3 tools/corpus_queue.py release            # let a held pass start again

There is one job and it takes no edition list. The scan filers decide what
is due (each one's due_reason: never read, inputs changed, read without the
VLM that now answers, read before ocr_full_pass.sh's REREAD_BEFORE) and the
pass reads all of it, plus the open annotation re-read requests, then ends.
So a reader change that should change past readings bumps REREAD_BEFORE,
and a VLM that was down when a source was read is used once it answers:
the next tick's pass reads them. A pass with nothing due ends in minutes.

One corpus job at a time. Another one is running when the pid in
~/.cache/corpus_queue/running.json is alive and started when it says (so a
recycled pid is not mistaken for it), or when a scan filer holds a ledger
lock (tools/scan_queue.py lock(): any filer run by hand). A tick that finds
either does nothing but check the pass's log: no new line for STALL_MINUTES
wakes the room once per stall. A pass that ends, not finished, without a
ledger row read is a dead launch; DEAD_LAUNCHES in a row hold the pass and
tell the room. The pass is its own session; when its leader is gone the
tick kills whatever of the session is left before it starts anything.
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
FULL_PASS = ROOT / "tools" / "ocr_full_pass.sh"
HOME = Path(os.path.expanduser("~"))
STATE_DIR = HOME / ".cache" / "corpus_queue"
RUNNING = STATE_DIR / "running.json"
STATE = STATE_DIR / "state.json"
#: The pass's exit status, written when it ends; a killed pass writes none.
EXIT = STATE_DIR / "full_pass.exit"
LOG = STATE_DIR / "full_pass.log"
LEDGERS = [HOME / ".cache" / "archive_org_editions" / "filed.jsonl", HOME / ".cache" / "trove" / "filed.jsonl"]
WAKE_SH = os.environ.get("WAKE_SH", "/Users/pt/github/household/tools/wake.sh")
ROOM = "cryptic-crosswords"
NAME = "full_pass"
STALL_MINUTES = 60
#: Launches in a row that end unfinished with no ledger row read before the pass is held.
DEAD_LAUNCHES = 2


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


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
    """Kill whatever is left of a pass's session: launch() starts it as a
    session leader, so its filers and `timeout`s (which move their child into
    a process group of its own) all carry its pid as their session id, and
    the kernel does not reuse that number while any of them lives. TERM, then
    KILL what is still there after `grace` seconds. Returns the pids."""
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
    """Each ledger's (size, mtime_ns): a filer saves its ledger after every
    source it reads, so a mark that moved means the pass read something."""
    out = {}
    for ledger in LEDGERS:
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
    """What launch() runs: the full pass, its exit status kept in EXIT."""
    return ["bash", "-c", 'bash "$1"; echo $? > "$2"', NAME, str(FULL_PASS), str(EXIT)]


def launch(dry):
    if dry:
        print(f"[dry run] would start {' '.join(command())}")
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    EXIT.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("CT_IN_WORKTREE", "CT_MAIN_CHECKOUT")}
    with open(LOG, "a") as log:
        p = subprocess.Popen(command(), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True, env=env, cwd=ROOT)
    for _ in range(50):
        start = proc_start(p.pid)
        if start:
            break
        time.sleep(0.1)
    RUNNING.write_text(json.dumps({"name": NAME, "pid": p.pid, "start": start, "ledgers": ledger_marks(),
                                   "launched": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}))
    print(f"started the full pass (pid {p.pid}); log {LOG}")


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
    RUNNING.unlink()
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
    rc = exit_status()
    state["lastExit"] = {"rc": rc, "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    if rc == 0 or ledger_marks() != r["ledgers"]:
        state["deadLaunches"] = 0
    else:
        state["deadLaunches"] = state.get("deadLaunches", 0) + 1
    if state["deadLaunches"] >= DEAD_LAUNCHES:
        state["held"] = True
        wake(f"the full pass ended {state['deadLaunches']} times in a row unfinished (last exit "
             f"{'killed' if rc is None else rc}) without reading a source; held. Log: {LOG}. "
             "Clear with: corpus_queue.py release", dry)
    save_state(state)


def tick(dry):
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
    held = ledger_held()
    if held:
        print(f"a scan filer holds {held}; nothing started")
        return "busy"
    launch(dry)
    return "started"


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


def nightly(dry):
    """Save the coverage count. Wake the room when the pass is held, or when
    it finished (everything due is read) and recoverable editions are still
    unfiled: what is left needs a reader change that bumps REREAD_BEFORE."""
    import archive_coverage
    cov = archive_coverage.main(["--save"] if not dry else [])
    state, run = load_state(), running()
    if run or ledger_held():
        print("a corpus job is running; no wake")
        return
    lines = []
    for s, c in cov["series"].items():
        fix = [k for k in c["classes"] if k["recoverable"] and k["editions"]]
        if fix:
            lines.append(f"{s}: " + "; ".join(f"{k['class']} {k['editions']}" for k in fix[:4]))
    if state.get("held"):
        head = f"the full pass is held after {state.get('deadLaunches', 0)} dead launches; log {LOG}. "
    elif (state.get("lastExit") or {}).get("rc") == 0 and lines:
        head = ("the full pass has read everything due, and recoverable archive editions remain unfiled. "
                "A reader fix that bumps REREAD_BEFORE in tools/ocr_full_pass.sh gets them. ")
    else:
        print("nothing for a person to do; no wake")
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
    wake(head + ("\nRecoverable unfiled editions: " + " | ".join(lines) if lines else "")
         + (f"\nTimes filed/printed (delta): {years}" if years else "")
         + "\nFull table: python3 tools/archive_coverage.py", dry)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("tick", "nightly"):
        sub.add_parser(name).add_argument("--dry-run", action="store_true")
    sub.add_parser("status")
    sub.add_parser("adopt").add_argument("pid", type=int)
    sub.add_parser("stop", help="kill the running pass and everything it started, and hold it")
    sub.add_parser("release")
    args = ap.parse_args(argv)
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
        print(f"held; killed session {r['pid']}: {end_session(r['pid'])}")
        RUNNING.unlink()


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "tools"))
    main()
