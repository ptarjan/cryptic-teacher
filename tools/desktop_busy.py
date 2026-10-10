"""Whether Paul is playing a game on his desktop, so the work we send there yields.

tools/ocr_remote.py's sessions and tools/vlm_reader.py's model run on the
desktop Paul games on, and even at idle priority they froze his game for
seconds at a time. busy(hosts) says why the desktop is busy, or None. It is
busy while

- a game runs there (GAMES, by process name), or
- its 3D engines are more than GPU_3D percent busy, summed over every
  process but VLM_SERVERS (llama-server's CUDA work shows there as 3D).

desktop_probe.ps1 reads both, and the desktop's free memory (free_mb), over ssh at low priority, at most once every
PROBE_EVERY seconds: the reading is shared by every process on this host
through a state file, and the process that probes logs one line when the
verdict changes. While the desktop is busy each probe also ends its OCR
sessions (ocr_remote.py serve), which outlive their ssh client. A desktop
that does not answer is not busy: the callers already work without it then.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
PROBE = TOOLS / "desktop_probe.ps1"
#: The desktop's addresses, and its user: a host elsewhere is never probed.
DESKTOPS = ("100.68.145.15", "192.168.1.198")
USER = "micro"
#: World of Warcraft's builds (retail, Classic, and their test clients).
GAMES = ("Wow", "WowClassic", "WowT", "WowB", "WowClassicT", "WowClassicB")
#: Summed 3D utilisation, in percent, above which some other game is running.
GPU_3D = 20
#: The VLM's processes (tools/vlm_reader.py), whose 3D load is our own work.
VLM_SERVERS = ("llama-server", "llama-swap")
PROBE_EVERY = 60
STATE = Path(tempfile.gettempdir())
#: Every DESKTOPS address is the one desktop, its host key known by its
#: tailnet address (this host's known_hosts is read-only).
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=15",
       "-o", "ServerAliveCountMax=4", "-o", "HostKeyAlias=100.68.145.15"]
clock = time.time


def _list(v):
    """A JSON field PowerShell may have written as a list, one value or null."""
    return v if isinstance(v, list) else [] if v is None else [v]


def probe(host):
    """The desktop's reading {"games", "gpu3d", "serving", "freeMB"} over ssh to
    `host`, or None when it does not answer one."""
    script = ("$Names = " + ", ".join(f"'{g}'" for g in GAMES) + "\n"
              + "$Vlm = " + ", ".join(f"'{v}'" for v in VLM_SERVERS) + "\n" + PROBE.read_text())
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    try:
        cmd = f'start "" /low /b /wait powershell -NoProfile -NonInteractive -EncodedCommand {enc}'
        res = subprocess.run([*SSH, host, cmd], capture_output=True, timeout=60, check=False)
        got = json.loads(res.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if not isinstance(got, dict):
        return None
    return {"games": [str(g) for g in _list(got.get("games"))], "gpu3d": float(got.get("gpu3d") or 0),
            "serving": [int(p) for p in _list(got.get("serving"))],
            "freeMB": None if got.get("freeMB") is None else int(got["freeMB"])}


def verdict(reading):
    """Why a desktop that read `reading` is busy, or None."""
    if reading is None:
        return None
    if reading["games"]:
        return "playing " + ", ".join(sorted(set(reading["games"])))
    if reading["gpu3d"] > GPU_3D:
        return f"3D engines {reading['gpu3d']:.0f}% busy"
    return None


def stop_sessions(host, pids):
    """End the desktop's OCR sessions `pids`."""
    ids = ",".join(str(p) for p in pids)
    cmd = f"powershell -NoProfile -NonInteractive -Command Stop-Process -Force -ErrorAction SilentlyContinue -Id {ids}"
    subprocess.run([*SSH, host, cmd], capture_output=True, timeout=60, check=False)


def log(line):
    print(f"{time.strftime('%H:%M:%S')} desktop [{os.getpid()}]: {line}", file=sys.stderr, flush=True)


def _read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def busy(hosts):
    """Why the desktop is busy, or None: `hosts` are ssh targets
    (user@address), tried in turn; any not at a DESKTOPS address is skipped."""
    hosts = [h for h in hosts if h.rpartition("@")[2] in DESKTOPS]
    if not hosts:
        return None
    import fcntl
    state = STATE / "desktop_busy.json"
    old = _read(state)
    if old and clock() - old["t"] < PROBE_EVERY:
        return old["why"]
    with open(STATE / "desktop_busy.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:  # another process is probing: its last verdict stands meanwhile
            return old["why"] if old else None
        old = _read(state)
        if old and clock() - old["t"] < PROBE_EVERY:
            return old["why"]
        reading = None
        for host in hosts:
            reading = probe(host)
            if reading is not None:
                break
        why = verdict(reading)
        # Saved before the sessions are ended: a process whose session ends
        # reads this verdict, so it waits for idle, not ocr_remote.RETRY.
        tmp = state.with_suffix(f".{os.getpid()}.part")
        # A probe that times out (a desktop saturated enough to page) keeps
        # the last free memory read, with when: its callers charge what they
        # started since against it (edition_queue.desktop_room).
        free = ([clock(), reading["freeMB"]] if reading and reading.get("freeMB") is not None
                else (old or {}).get("free"))
        tmp.write_text(json.dumps({"t": clock(), "why": why, "reading": reading, "free": free}))
        tmp.replace(state)
        if why and reading["serving"]:
            stop_sessions(host, reading["serving"])
        was = old["why"] if old else None
        if why and not was:
            log(f"yielding: {why}; desktop OCR and VLM wait until it is idle")
        elif was and not why:
            log("resuming: " + (f"idle (3D {reading['gpu3d']:.0f}%, no game)" if reading else "not answering"))
    return why


def free_mb(hosts):
    """(when it was read, the desktop's free physical memory in MB) at the
    last probe it answered, probing again when older than PROBE_EVERY
    (busy); None when it never answered or `hosts` holds no desktop."""
    if not [h for h in hosts if h.rpartition("@")[2] in DESKTOPS]:
        return None
    busy(hosts)
    got = _read(STATE / "desktop_busy.json")
    return tuple(got["free"]) if got and got.get("free") else None
