#!/bin/bash
# Does tools/corpus_queue.py count a chunk directory's progress without its
# .tries files (under a dotted path like ~/.cache), take a recycled pid for a
# dead job, see a filer's ledger lock, kill all of a dead job's session, and
# count a launch that read no chunk; and does tools/archive_coverage.py count the editions the Times
# printed (no Sundays, no Christmas, none in the 1979 lock-out) and give an
# unfiled edition the class its ledger row says?
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
HOME="$tmp" python3 - <<'PY'
import fcntl, json, os, sys, time
sys.path.insert(0, "tools")
from pathlib import Path
import corpus_queue as q
import archive_coverage as cov

d = Path(os.environ["HOME"]) / ".cache" / "t.chunks"
d.mkdir(parents=True)
for n in ("c_001_times_times", "c_001_times_times.tries", "c_aa"):
    (d / n).write_text("NewsUK1987UKEnglish/1987-06-10_62791\n")
job = {"name": "t", "chunks": str(d)}
assert [c.name for c in q.remaining(job)] == ["c_001_times_times", "c_aa"], q.remaining(job)
assert q.editions_of(job) == ["NewsUK1987UKEnglish/1987-06-10_62791"] * 2
assert q.chunk_files(d) == q.remaining(job) and q.chunk_files(d / "failed") == []

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

q.jobs = lambda: [job]
q.wake = lambda text, dry: None
state = {"gates": {}, "jobs": {"t": {"remainingAtLaunch": 2}}}
q.account("t", state, False)
q.account("t", state, False)
assert state["jobs"]["t"]["deadLaunches"] == 2 and state["jobs"]["t"]["held"], state

q.STATE_DIR.mkdir(parents=True, exist_ok=True)
q.RUNNING.write_text(json.dumps({"name": "t", "pid": os.getpid(), "start": q.proc_start(os.getpid())}))
assert q.running()["pid"] == os.getpid()
q.RUNNING.write_text(json.dumps({"name": "t", "pid": os.getpid(), "start": "1"}))
assert q.running() is None, "a recycled pid is not the job"

lock = Path(os.environ["HOME"]) / "filed.lock"
q.LEDGER_LOCKS = [lock]
lock.touch()
assert q.ledger_held() is None
with open(lock, "w") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    assert q.ledger_held() == lock

import datetime
days = list(cov.printed_dates("times", datetime.date(1980, 12, 31)))
assert sum(d.startswith("1979") for d in days) == 41, sum(d.startswith("1979") for d in days)
assert "1980-12-25" not in days and "1980-12-28" not in days and "1980-12-27" in days

cases = [
    ({"verdicts": []}, "no-crossword-found"),
    ({"verdicts": [{"number": 1, "refused": "no reading parses"}]}, "no-reading-parses"),
    ({"verdicts": [{"number": 1, "refused": "the ink under the title is 1x2, not a grid"}]}, "not-a-grid"),
    ({"verdicts": [{"number": 1, "pending": "no grid: the white cells span 14 rows"}]}, "no-grid"),
    ({"verdicts": [{"number": 1, "pending": "rebuilt grid disagrees: 5-down"}]}, "clues-dont-fit"),
    ({"verdicts": [{"number": 1, "id": "times-1", "blank": {"1-across": "readings differ"}}]}, "blank-clues"),
    ({"verdicts": [{"number": 7, "id": "times-7"}]}, "filed-other-date"),
]
for row, want in cases:
    got = cov.verdict_class(row, {7: "1990-01-01"})
    assert got == want, (row, got, want)
print("corpus_queue and archive_coverage: ok")
PY
