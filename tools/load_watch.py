#!/usr/bin/env python3
"""Wake the room when the machine is overloaded, with who is using the CPU.

    tools/load_watch.py            # the cron entry: check, maybe sample, maybe wake
    tools/load_watch.py --dry-run  # same, but print the message instead of waking

Paul's rule: the box has os.cpu_count() cores and the desktop has more, so a 5-minute
load average above the core count on two runs in a row is work that belongs on the
desktop CPU. The wake carries a ranked breakdown so the room can go and move it.

The sample reads /proc only (no ps text). Per process it takes utime+stime, plus
cutime+cstime of the parent, because a reindex pool's workers are born and reaped
inside the window and never appear in two snapshots. A parent's cutime delta holds
every child it reaped in the window, but also the pre-window ticks of a child that
was already running when the window opened; those are known from the first
snapshot and are subtracted, so nothing is counted twice.

Quiet by design: one wake per 60 minutes unless the top consumer changed, one jsonl
line per check in load_watch.jsonl beside the state file.
"""
import collections
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOM = "-1003929432016:61"
SAMPLE_SECONDS = 30
REPEAT_SECONDS = 3600
CONSECUTIVE = 2
LOG_KEEP = 1000
MIN_CORES = 0.05  # a consumer below this is noise in the ranking
SHOW = 6
# Keys that only launch something else; a parent label climbs past them.
WRAPPERS = {"bash", "sh", "flock", "env", "timeout", "nice", "setsid", "?"}
WAKE_SH = os.environ.get("LOAD_WATCH_WAKE", "/app/tools/wake.sh")
STATE_DIR = Path(os.environ.get("LOAD_WATCH_STATE", "") or Path.home() / ".local/state/cryptic-teacher")

TASK = ("Find what is running in the container that could run on the desktop CPU instead "
        "(Paul: 'we should be using the desktop cpu'), move or throttle the top consumer, "
        "and fix whatever we are causing. Reply once it is handled.")


def read_loadavg(proc):
    f = (Path(proc) / "loadavg").read_text().split()
    return float(f[0]), float(f[1]), float(f[2])


def read_pressure(proc):
    """avg10/avg60/avg300 of the 'some' line of /proc/pressure/cpu, or None."""
    try:
        for line in (Path(proc) / "pressure/cpu").read_text().splitlines():
            kind, *rest = line.split()
            if kind == "some":
                kv = dict(x.split("=") for x in rest)
                return {k: float(kv[k]) for k in ("avg10", "avg60", "avg300")}
    except (OSError, ValueError, KeyError):
        pass
    return None


def read_proc(proc, pid):
    """One process: state, ppid, own ticks, reaped-children ticks, argv. None if gone."""
    d = Path(proc) / str(pid)
    try:
        stat = (d / "stat").read_text()
        f = stat.rsplit(")", 1)[1].split()  # f[0]=state, f[1]=ppid, f[11..14]=u s cu cs
        argv = [a.decode(errors="replace") for a in (d / "cmdline").read_bytes().split(b"\0") if a]
        return {"state": f[0], "ppid": int(f[1]), "own": int(f[11]) + int(f[12]),
                "kids": int(f[13]) + int(f[14]), "start": int(f[19]), "argv": argv}
    except (OSError, IndexError, ValueError):
        return None


def snap(proc):
    out = {}
    for name in os.listdir(proc):
        if name.isdigit():
            p = read_proc(proc, int(name))
            if p:
                out[int(name)] = p
    return out


def key(argv):
    """The job a process belongs to: script name, or edition_queue unit kind, or the burn."""
    if len(argv) == 1:
        argv = argv[0].split()  # a process that retitled itself: one space-joined string
    if not argv:
        return "?"
    if os.path.basename(argv[0]) == "claude" and "-p" in argv:
        return "claude -p (burn)"
    for i, a in enumerate(argv):
        if a.endswith((".py", ".sh", ".js")):
            k = os.path.basename(a)
            rest = argv[i + 1:]
            if k == "edition_queue.py" and len(rest) >= 2 and rest[0] == "unit":
                return f"{k} unit {rest[1]}"
            flag = next((x for x in rest if x.startswith("--")), None)
            return f"{k} {flag}" if flag else k
    return os.path.basename(argv[0])


def charge(a, b, seconds, hz):
    """Cores used per key between snapshots a and b, with each key's biggest parent key."""
    ticks = collections.Counter()
    parents = collections.defaultdict(collections.Counter)
    gone = collections.defaultdict(int)  # parent pid -> inclusive pre-window ticks of vanished children
    alive = {pid for pid, p in a.items() if pid in b and b[pid]["start"] == p["start"]}
    for pid, p in a.items():
        if pid in alive:
            continue
        # The reaper is the parent, or after the parent died, the nearest live ancestor
        # (a subreaper such as claude) or pid 1; charge the pre-window ticks off both.
        up = p["ppid"]
        while up in a and up not in alive and up > 1:
            up = a[up]["ppid"]
        for reaper in {up, 1}:
            gone[reaper] += p["own"] + p["kids"]
    for pid, p in b.items():
        old = a.get(pid)
        if old and old["start"] != p["start"]:
            old = None  # a recycled pid is a new process
        own = p["own"] - (old["own"] if old else 0)
        kids = p["kids"] - (old["kids"] if old else 0) - gone.get(pid, 0)
        t = own + max(kids, 0)
        if t <= 0:
            continue
        argv = p["argv"] or (old["argv"] if old else [])  # a zombie has no cmdline left
        if not argv and p["ppid"] in b:
            argv = b[p["ppid"]]["argv"]  # an unreaped, never-seen child is its parent's work
        k = key(argv)
        ticks[k] += t
        up, depth = p["ppid"], 0
        while up > 1 and up in b and depth < 12 and key(b[up]["argv"]) in WRAPPERS | {k}:
            up, depth = b[up]["ppid"], depth + 1
        if up > 1 and up in b and depth < 12:
            parents[k][key(b[up]["argv"])] += t
    cores = {k: t / hz / seconds for k, t in ticks.items()}
    return cores, {k: c.most_common(1)[0][0] for k, c in parents.items()}


def sample(proc, seconds=SAMPLE_SECONDS, hz=None, sleep=time.sleep):
    hz = hz or os.sysconf("SC_CLK_TCK")
    a = snap(proc)
    sleep(seconds)
    b = snap(proc)
    cores, parent = charge(a, b, seconds, hz)
    states = collections.Counter(p["state"] for p in b.values())
    ranked = sorted(((v, k) for k, v in cores.items() if v >= MIN_CORES), reverse=True)
    return {"ranked": [(round(v, 2), k, parent.get(k)) for v, k in ranked],
            "total": round(sum(cores.values()), 2),
            "R": max(states["R"] - 1, 0),  # this sampler is itself runnable
            "D": states["D"]}


def message(load5, ncores, s, pressure):
    rows = [f"{v:.1f} cores {k}" + (f" (parent {par})" if par else "") for v, k, par in s["ranked"][:SHOW]]
    tail = f"{s['total']:.1f} cores used, {s['R']} running, {s['D']} in D-state"
    if pressure:
        tail += f", cpu pressure avg60 {pressure['avg60']:g}%"
    body = ", ".join(rows) if rows else "nothing above noise in the sample"
    return f"load {load5:g} on {ncores} cores: {body}. {tail}.\n{TASK}"


def append_log(path, rec):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    lines = path.read_text().splitlines()
    if len(lines) > LOG_KEEP:
        path.write_text("\n".join(lines[-LOG_KEEP // 2:]) + "\n")


def wake(text):
    return subprocess.run([WAKE_SH, "-c", ROOM, text], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60).returncode == 0


def main(proc="/proc", state_dir=STATE_DIR, ncores=None, now=time.time, sleep=time.sleep,
         waker=wake, hz=None, dry_run=False, seconds=SAMPLE_SECONDS):
    ncores = ncores or os.cpu_count()
    state_dir = Path(state_dir)
    state_file, log_file = state_dir / "load_watch.json", state_dir / "load_watch.jsonl"
    try:
        state = json.loads(state_file.read_text())
    except (OSError, ValueError):
        state = {}
    load5 = read_loadavg(proc)[1]
    over = state.get("over", 0) + 1 if load5 > ncores else 0
    state["over"] = over
    rec = {"t": int(now()), "load5": load5, "cores": ncores, "over": over}
    if over < CONSECUTIVE:
        rec["action"] = "ok" if over == 0 else "first-over"
    else:
        s = sample(proc, seconds, hz, sleep)
        top = s["ranked"][0][1] if s["ranked"] else None
        pressure = read_pressure(proc)
        text = message(load5, ncores, s, pressure)
        rec.update(top=top, R=s["R"], D=s["D"], total=s["total"], pressure=pressure,
                   ranked=s["ranked"][:SHOW])
        recent = "woke_at" in state and now() - state["woke_at"] < REPEAT_SECONDS
        if recent and top == state.get("woke_top"):
            rec["action"] = "quiet"
        elif dry_run:
            rec["action"] = "dry-run"
            print(text)
        elif waker(text):
            rec["action"] = "woke"
            state.update(woke_at=now(), woke_top=top)
        else:
            rec["action"] = "wake-failed"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state))
    append_log(log_file, rec)
    print(json.dumps(rec))
    return rec


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv[1:])
