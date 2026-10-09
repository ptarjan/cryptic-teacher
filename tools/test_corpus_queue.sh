#!/bin/bash
# Does tools/corpus_queue.py take a recycled pid for a dead job, see a
# filer's ledger lock, kill all of a dead job's session, start the full pass
# with no edition list, count a pass that finished or read a source as
# progress (or fetched one) and hold it after two dead launches, chain the
# next pass straight on after one that finished having fetched, and refuse any edition-list
# job; and does tools/archive_coverage.py count the editions the Times
# printed (no Sundays, no Christmas, none in the 1979 lock-out) and give an
# unfiled edition the class its ledger row says?
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
HOME="$tmp" CT_DOWNLOADS="$tmp/downloads" python3 - <<'PY'
import fcntl, json, os, sys, time
sys.path.insert(0, "tools")
from pathlib import Path
import corpus_queue as q
import archive_coverage as cov

import signal, subprocess
p = subprocess.Popen(["bash", "-c", "sleep 300 & sleep 300 & wait"], start_new_session=True)
for _ in range(50):
    if len(q.session_pids(p.pid)) == 3:
        break
    time.sleep(0.1)
assert len(q.session_pids(p.pid)) == 3, q.session_pids(p.pid)
p.send_signal(signal.SIGKILL)
p.wait()
assert len(q.session_pids(p.pid)) == 2, "the leader's children outlive it"
q.end_session(p.pid, grace=2)
assert q.session_pids(p.pid) == [], q.session_pids(p.pid)
assert q.end_session(os.getsid(0)) == [], "never its own session"

q.STATE_DIR.mkdir(parents=True, exist_ok=True)
q.RUNNING.write_text(json.dumps({"name": "t", "pid": os.getpid(), "start": q.proc_start(os.getpid())}))
assert q.running()["pid"] == os.getpid()
q.RUNNING.write_text(json.dumps({"name": "t", "pid": os.getpid(), "start": "1"}))
assert q.running() is None, "a recycled pid is not the job"
q.RUNNING.unlink()

ledger = Path(os.environ["HOME"]) / "filed.jsonl"
lock = q.lock_of(ledger)
q.LEDGERS = [ledger]
lock.touch()
assert q.ledger_held() is None
with open(lock, "w") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    assert q.ledger_held() == lock
    assert q.tick(False) == "busy", "a filer run by hand is a corpus job"

# The standing job: tick starts the full pass, with no edition list, and the
# pass's end is accounted from its exit status and the ledgers.
woken = []
q.wake = lambda text, dry: woken.append(text)
fake = Path(os.environ["HOME"]) / "pass.sh"
args = Path(os.environ["HOME"]) / "args"
q.FULL_PASS = fake
q.CHAIN = ["true"]
def wait_end(pid):
    """The pass is this process's child here (the tick's in use exits first).
    Its pid comes from running.json: launch()'s Popen, collected, may already
    have reaped a pass that ended, and running() then calls it gone."""
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
def run_pass(body):
    """Start a pass running `body`, let it end, and reap it as the next tick does first."""
    fake.write_text(f'echo "$@" > {args}\n' + body)
    assert q.tick(False) == "started"
    wait_end(json.loads(q.RUNNING.read_text())["pid"])
    q.reap(q.load_state(), False)
    return q.load_state()
st = run_pass("exit 0")
assert args.read_text().strip() == "", "the pass takes no arguments: no edition list"
assert st["lastExit"]["rc"] == 0 and st["deadLaunches"] == 0, st
# (mirror) a pass that writes its row before launch() has its pid's start time
# still made progress: the marks are taken before it runs.
slow_start = q.proc_start
q.proc_start = lambda pid: (time.sleep(0.5), slow_start(pid))[1]
assert run_pass(f"echo row >> {ledger}; exit 1")["deadLaunches"] == 0, "an unfinished pass that read a source made progress"
q.proc_start = slow_start
q.FETCHED[0].parent.mkdir(parents=True, exist_ok=True)
assert run_pass(f"echo edition >> {q.FETCHED[0]}; exit 1")["deadLaunches"] == 0, "one that fetched made progress"
assert run_pass("exit 1")["deadLaunches"] == 1, "one that read and fetched nothing is a dead launch"
assert run_pass("exit 1")["held"], "two in a row hold the pass"
assert q.tick(False) == "held" and "held" in woken[-1], woken
q.main(["release"])
assert run_pass("exit 0")["deadLaunches"] == 0, "a released pass starts again"

# A pass that finished having fetched starts the next at once; one that
# fetched nothing, or did not finish, leaves it to the hourly tick.
st = run_pass(f"echo edition >> {q.FETCHED[0]}; exit 0")
assert st["lastExit"]["fetched"], st
fake.write_text("exit 0")
assert q.tick(False, chained=True) == "started"
wait_end(json.loads(q.RUNNING.read_text())["pid"])
q.reap(q.load_state(), False)
assert q.load_state()["lastExit"]["fetched"] is False
assert q.tick(False, chained=True) == "idle", "a pass that fetched nothing does not chain"
run_pass(f"echo row >> {ledger}; echo edition >> {q.FETCHED[0]}; exit 1")
assert q.tick(False, chained=True) == "idle", "an unfinished pass does not chain"

# chain() leaves the pass's session and runs the chained tick once the
# pass's leader (its parent) has exited.
marker = Path(os.environ["HOME"]) / "chained"
leader = subprocess.Popen(["bash", "-c", 'python3 -c "$1"; echo $$ > "$2.leader"', "x",
                           f"import sys; sys.path.insert(0, 'tools'); import corpus_queue as q; "
                           f"q.CHAINED_TICK = ['bash', '-c', 'echo $$ $(ps -o sid= $$) > {marker}']; q.chain()",
                           str(marker)], start_new_session=True)
leader.wait()
for _ in range(100):
    if marker.exists() and marker.read_text().strip():
        break
    time.sleep(0.1)
pid, sid = map(int, marker.read_text().split())
assert sid != leader.pid and pid == sid, (pid, sid, leader.pid)

# An edition-list job has nowhere to go: no queue file, no job argument.
assert not (q.ROOT / "tools" / "data" / "corpus_queue.json").exists(), "edition-list jobs are gone; never bring them back"
assert not hasattr(q, "jobs") and "--edition" not in q.command()
for bad in (["tick", "times_cluefit"], ["adopt", "times_cluefit", "1"], ["tick", "--list", "eds.txt"]):
    try:
        q.main(bad)
    except SystemExit as e:
        assert e.code == 2, (bad, e.code)
    else:
        raise AssertionError(f"{bad} was taken")

import datetime
days = list(cov.printed_dates("times", datetime.date(1980, 12, 31)))
assert sum(d.startswith("1979") for d in days) == 41, sum(d.startswith("1979") for d in days)
assert "1980-12-25" not in days and "1980-12-28" not in days and "1980-12-27" in days

cases = [
    ({"verdicts": []}, "no-crossword-found"),
    # Scanned, not yet read: the scan's titles wait for the read; a scan
    # with none is no crossword whether it is read or not.
    ({"scan": {"puzzles": [{"number": 5644, "leaf": 39}], "solutions": []}}, "not-read"),
    ({"scan": {"puzzles": [], "solutions": []}}, "no-crossword-found"),
    ({"scan": {"puzzles": [{"number": 1652, "leaf": 1}], "solutions": []}, "inputs": "x", "verdicts": []},
     "no-crossword-found"),
    ({"verdicts": [{"number": 1, "refused": "no reading parses", "cause": "no-reading-parses"}]}, "no-reading-parses"),
    ({"verdicts": [{"number": 1, "refused": "1x2, not a grid", "cause": "not-a-grid"}]}, "not-a-grid"),
    # The class is the verdict's fields, never its prose.
    ({"verdicts": [{"number": 1, "refused": "the ink is not a grid"}]}, "refused-no-cause"),
    ({"verdicts": [{"number": 1, "pending": "no grid: the white cells span 14 rows"}]}, "no-grid"),
    ({"verdicts": [{"number": 1, "pending": "no grid: anything", "grid": "#..."}]}, "clues-dont-fit"),
    ({"verdicts": [{"number": 1, "id": "times-1", "blank": {"1-across": "readings differ"}}]}, "blank-clues"),
    ({"verdicts": [{"number": 7, "id": "times-7"}]}, "filed-other-date"),
]
for row, want in cases:
    got = cov.verdict_class(row, {7: "1990-01-01"})
    assert got == want, (row, got, want)
print("corpus_queue and archive_coverage: ok")
PY
