#!/bin/bash
# Does load_watch.py rank CPU by job, charge exited children to their parent, and
# wake only on two high runs in a row, once an hour unless the top consumer changes?
#
#     nice -n 19 bash tools/test_load_watch.sh
#
# A fake /proc in a temp dir and a stub waker: no real /proc, no ~/.cache, no wake.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

out=$(cd "$REPO/tools" && TMP="$tmp" python3 -I - <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
import load_watch as lw

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

tmp = Path(os.environ["TMP"])

def put(proc, pid, argv, ppid=1, state="S", u=0, s=0, cu=0, cs=0):
    d = Path(proc) / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    f = ["0"] * 20
    f[0], f[1] = state, str(ppid)
    f[11], f[12], f[13], f[14] = map(str, (u, s, cu, cs))
    (d / "stat").write_text(f"{pid} (we ird) ) " + " ".join(f))
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")

def drop(proc, pid):
    for n in ("stat", "cmdline"):
        (Path(proc) / str(pid) / n).unlink()
    (Path(proc) / str(pid)).rmdir()

def fresh(name, load5):
    p = tmp / name
    p.mkdir()
    (p / "loadavg").write_text(f"{load5} {load5} {load5} 3/100 999\n")
    (p / "pressure").mkdir()
    (p / "pressure/cpu").write_text("some avg10=1.50 avg60=2.25 avg300=3.00 total=1\n")
    return str(p)

# key(): script name, flag, edition_queue unit kind, the claude burn, plain binary.
check("python script", "fetch_puzzle.py --reindex", lw.key(["python3", "/x/tools/fetch_puzzle.py", "--reindex"]))
check("shell script", "gale_read.sh", lw.key(["bash", "/x/gale_read.sh", "arg"]))
check("edition_queue unit", "edition_queue.py unit ocr", lw.key(["python3", "edition_queue.py", "unit", "ocr", "times"]))
check("claude -p is the burn", "claude -p (burn)", lw.key(["/usr/bin/claude", "-p", "hello"]))
check("claude without -p is not", "claude", lw.key(["claude", "--resume"]))
check("retitled process", "edition_queue.py unit scan", lw.key(["edition_queue.py unit scan gale X/1976-07-02    "]))
check("plain binary", "node", lw.key(["/usr/bin/node", "-e", "1"]))

# charge(): live process delta, plus the reaped-children delta of its parent.
a = {
    10: dict(start=1, state="S", ppid=1, own=100, kids=500, argv=["bash", "gale_read.sh"]),
    11: dict(start=1, state="R", ppid=10, own=300, kids=0, argv=["python3", "fetch_puzzle.py", "--reindex"]),
    12: dict(start=1, state="R", ppid=11, own=50, kids=20, argv=["python3", "pool_worker.py"]),  # exits in window
}
b = {
    10: dict(start=1, state="S", ppid=1, own=100, kids=500, argv=["bash", "gale_read.sh"]),
    # live child: +200 own; its reaped pool children: the vanished 12 (pre 70) plus 400 new ticks
    11: dict(start=1, state="R", ppid=10, own=500, kids=470 + 0, argv=["python3", "fetch_puzzle.py", "--reindex"]),
}
cores, parent = lw.charge(a, b, 10, 100)
check("live delta + reaped children charged to the parent job, pre-window ticks removed",
      0.6, round(cores["fetch_puzzle.py --reindex"], 6))
check("the vanished child is not a row of its own", False, "pool_worker.py" in cores)
check("parent job is named", "gale_read.sh", parent["fetch_puzzle.py --reindex"])
check("an idle parent is not charged", False, "gale_read.sh" in cores)

# A child whose parent died is reaped by a subreaper ancestor (claude) or pid 1; its
# pre-window ticks come off that reaper, not off the dead parent.
r1 = {30: dict(start=1, state="S", ppid=1, own=0, kids=0, argv=["claude"]),
      31: dict(start=1, state="S", ppid=30, own=0, kids=0, argv=["bash", "-c", "x"]),
      32: dict(start=1, state="R", ppid=31, own=90000, kids=0, argv=["python3", "capture.py"])}
r2 = {30: dict(start=1, state="S", ppid=1, own=0, kids=90100, argv=["claude"])}
cores, _ = lw.charge(r1, r2, 10, 100)
check("orphan's lifetime is not charged to its subreaper", {"claude": 0.1}, cores)

# The parent label climbs past bash/flock wrappers, and names none when only wrappers remain.
w1 = {60: dict(start=1, state="S", ppid=1, own=0, kids=0, argv=["bash", "gale_read.sh"]),
      61: dict(start=1, state="S", ppid=60, own=0, kids=0, argv=["flock", "-n", "l", "x"]),
      62: dict(start=1, state="R", ppid=61, own=0, kids=0, argv=["python3", "w.py"]),
      70: dict(start=1, state="S", ppid=1, own=0, kids=0, argv=["bash", "-c", "cmd"]),
      71: dict(start=1, state="R", ppid=70, own=0, kids=0, argv=["python3", "v.py"])}
w2 = {pid: dict(p, own=100) for pid, p in w1.items() if pid in (62, 71)} | {k: v for k, v in w1.items() if k in (60, 61, 70)}
_, parent = lw.charge(w1, w2, 10, 100)
check("parent past a flock wrapper", "gale_read.sh", parent["w.py"])
check("only wrappers above means no parent label", False, "v.py" in parent)

# A recycled pid with another command line is a new process, not a negative delta.
c1 = {5: dict(start=1, state="S", ppid=1, own=900, kids=0, argv=["a.py"])}
c2 = {5: dict(start=2, state="S", ppid=1, own=100, kids=0, argv=["b.py"])}
cores, _ = lw.charge(c1, c2, 10, 100)
check("recycled pid", {"b.py": 0.1}, cores)

# A worker that exits but is not yet reaped loses its cmdline; it is still the same
# process (same start time), so only its in-window ticks count, under its own job.
z1 = {7: dict(start=1, state="R", ppid=1, own=1000, kids=0, argv=["python3", "w.py"])}
z2 = {7: dict(start=1, state="Z", ppid=1, own=1100, kids=0, argv=[])}
cores, _ = lw.charge(z1, z2, 10, 100)
check("zombie keeps its job and only in-window ticks", {"w.py": 0.1}, cores)
z3 = {8: dict(start=1, state="Z", ppid=9, own=500, kids=0, argv=[]),
      9: dict(start=1, state="S", ppid=1, own=0, kids=0, argv=["python3", "pool.py"])}
cores, _ = lw.charge({}, z3, 10, 100)
check("a never-seen zombie is charged to its parent's job", {"pool.py": 0.5}, cores)

# read_proc(): comm with spaces and parens; and states counted by sample().
proc = fresh("p0", 1)
put(proc, 20, ["python3", "x.py"], state="R", u=1, s=2, cu=3, cs=4)
put(proc, 21, ["sleep", "1"], state="D")
r = lw.read_proc(proc, 20)
check("stat fields", (3, 7, "R"), (r["own"], r["kids"], r["state"]))
check("missing pid", None, lw.read_proc(proc, 999))
check("pressure", {"avg10": 1.5, "avg60": 2.25, "avg300": 3.0}, lw.read_pressure(proc))
check("no pressure file", None, lw.read_pressure(str(tmp / "nothing")))

# main(): the whole flow.
woke = []
def waker(text):
    woke.append(text)
    return True

clock = [1000.0]
def run(proc, state, **kw):
    return lw.main(proc=proc, state_dir=state, ncores=6, now=lambda: clock[0], waker=waker,
                   hz=100, seconds=10, **kw)

state = tmp / "state"
proc = fresh("p1", 3.0)
put(proc, 30, ["python3", "/x/fetch_puzzle.py", "--reindex"], ppid=29, state="R", u=0)
put(proc, 29, ["bash", "/x/gale_read.sh"], ppid=1)
put(proc, 31, ["sleep", "9"], state="D")

def burn(ticks_by_pid):
    def sleep(_):
        for pid, t in ticks_by_pid.items():
            p = lw.read_proc(proc, pid)
            put(proc, pid, p["argv"], ppid=p["ppid"], state=p["state"], u=p["own"] + t)
    return sleep

check("quiet under the core count", "ok", run(proc, state, sleep=burn({}))["action"])
(Path(proc) / "loadavg").write_text("15 15 15 3/100 999\n")
check("first high run does not wake", "first-over", run(proc, state, sleep=burn({}))["action"])
check("no wake yet", [], woke)
clock[0] += 300
rec = run(proc, state, sleep=burn({30: 1260}))  # 12.6 s of CPU in a 10 s window
check("second high run wakes", "woke", rec["action"])
check("top consumer", "fetch_puzzle.py --reindex", rec["top"])
check("message is ranked and carries the work", True,
      woke[0].startswith("load 15 on 6 cores: tasks stalled waiting for CPU 2.25% of the last minute")
      and "Top consumers: 1.3 cores fetch_puzzle.py --reindex (parent gale_read.sh)" in woke[0]
      and "desktop CPU" in woke[0] and "1 in D-state" in woke[0])
check("running count excludes the sampler itself", 0, rec["R"])
(Path(proc) / "stat").write_text("cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 1 1 1 1\nprocs_running 9\n")
check("whole-VM busy ticks leave out idle and iowait", {"busy": 150, "running": 9}, lw.read_stat(proc))
check("message leads with the runnable threads", True, lw.message(
    11.4, 6, {"runnable": 8, "busy": 5.9, "total": 3.2, "R": 4, "D": 0, "ranked": []},
    {"avg60": 17.3}).startswith("load 11.4 on 6 cores: 8 threads runnable for 6 cores; "
                                "tasks stalled waiting for CPU 17.3% of the last minute; "
                                "the VM used 5.9 cores, our processes 3.2"))
(Path(proc) / "stat").unlink()
clock[0] += 300
check("same top inside the hour stays quiet", "quiet", run(proc, state, sleep=burn({30: 1000}))["action"])
check("still one wake", 1, len(woke))
put(proc, 40, ["claude", "-p", "go"], ppid=1, state="R")
clock[0] += 300
check("new top consumer wakes again", "woke", run(proc, state, sleep=burn({40: 3000}))["action"])
check("claude -p is named the burn", True, "claude -p (burn)" in woke[1])
clock[0] += 4000
check("same top after the hour wakes", "woke", run(proc, state, sleep=burn({40: 3000}))["action"])
(Path(proc) / "loadavg").write_text("2 2 2 3/100 999\n")
check("calm resets the streak", 0, run(proc, state, sleep=burn({}))["over"])
lines = (state / "load_watch.jsonl").read_text().splitlines()
check("one jsonl line per check", 7, len(lines))
check("log lines are json with an action", True, all("action" in json.loads(l) for l in lines))

# A failed wake is recorded and retried next run (no woke_at saved).
proc2 = fresh("p2", 20.0)
put(proc2, 50, ["python3", "z.py"], state="R")
st2 = tmp / "state2"
failing = lambda text: False
for _ in range(2):
    rec = lw.main(proc=proc2, state_dir=st2, ncores=6, now=lambda: 5.0, waker=failing, hz=100, seconds=1, sleep=lambda _: None)
check("failed wake is recorded", "wake-failed", rec["action"])
sys.exit(1 if fails else 0)
PY
)
rc=$?
echo "$out"
exit $rc
