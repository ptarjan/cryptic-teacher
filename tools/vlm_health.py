#!/usr/bin/env python3
"""Wake the room when the desktop VLM has been down for DOWN_FOR with no game
running (the cryptic-vlm-health plugin).

The VLM (vlm_reader.URL, llama-swap on Paul's desktop) can be down with
nothing saying so: the OCR pass reads on without it at worse quality, so an
outage looks like a quiet day. Gaming is the expected outage (D:\\llm\\game-guard.ps1 stops llama-swap for a game),
so minutes with a game running on the desktop do not count, and the clock
restarts after one. The wake carries the desktop's own account: llama
processes, the llamaswap-boot and gameguard tasks with their last results,
and the tail of game-guard.log. One wake per outage.
"""
import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import desktop_busy
import vlm_reader
import watchlib  # household's tools/, which tools/vlm_health.sh puts on PYTHONPATH

TOOLS = Path(__file__).resolve().parent

DOWN_FOR = 30 * 60
STATE = "vlm-health"
PROBE = TOOLS / "vlm_health_probe.ps1"
ROOM = "cryptic-crosswords"


def serving():
    """Whether the VLM answers /v1/models and lists vlm_reader.MODEL."""
    vlm_reader.resolve()
    try:
        with urllib.request.urlopen(vlm_reader.URL + "/v1/models", timeout=15) as r:
            ids = [m.get("id") for m in json.load(r).get("data", [])]
    except (OSError, ValueError):
        return False
    return vlm_reader.MODEL in ids


def desktop():
    """The desktop's account (vlm_health_probe.ps1) from the first address
    that answers, or None when none does."""
    enc = base64.b64encode(PROBE.read_text().encode("utf-16-le")).decode()
    import desktop_hosts
    for host in desktop_hosts.ranked(22):  # the ones answering now first
        try:
            r = subprocess.run([*desktop_busy.SSH, f"{desktop_busy.USER}@{host}",
                                f"powershell -NoProfile -NonInteractive -EncodedCommand {enc}"],
                               capture_output=True, timeout=60, check=False)
            got = json.loads(r.stdout)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            continue
        if isinstance(got, dict):
            return got
    return None


def lines(v):
    return v if isinstance(v, list) else [] if v is None else [v]


def read_state(seen):
    """The outage state this job keeps in its watcher's seen-list."""
    state = {}
    for line in seen:
        if line.startswith(f"{STATE}\t"):
            try:
                state = json.loads(line.split("\t", 1)[1])
            except ValueError:
                state = {}
    return state


def quick():
    """0 when the VLM serves and was not down at the last tick: nothing to
    record or send, so tools/vlm_health.sh skips its worktree setup. 1 when
    the full tick must run. Writes nothing."""
    if read_state(watchlib.Watcher(STATE).seen).get("down_since"):
        return 1
    return 0 if serving() else 1


def main():
    if "--quick" in sys.argv[1:]:
        return quick()
    w = watchlib.Watcher(STATE)
    state = read_state(w.seen)
    w.seen = [s for s in w.seen if not s.startswith(f"{STATE}\t")]
    now = time.time()

    if serving():
        if state.pop("down_since", None):
            print(f"{vlm_reader.URL} serving {vlm_reader.MODEL} again")
    else:
        box = desktop()
        game = (box or {}).get("game")
        if game:
            if state.pop("down_since", None):
                print(f"VLM down while gaming ({game}); the clock restarts after it")
        else:
            since = state.setdefault("down_since", now)
            print(f"VLM down {(now - since) / 60:.0f} min, no game"
                  + ("" if box else ", desktop not answering ssh"))
            if now - since >= DOWN_FOR:
                when = time.strftime("%H:%M %Z", time.localtime(since))
                if box is None:
                    detail = ("The desktop answers ssh on neither "
                              f"{' nor '.join(desktop_busy.DESKTOPS)}: off, or a hard reboot "
                              "sitting at the login screen.")
                else:
                    detail = "```\n" + "\n".join(
                        [*(lines(box.get("procs")) or ["no llama-swap / llama-server process"]),
                         *lines(box.get("tasks")), "game-guard.log:", *lines(box.get("log"))]) + "\n```"
                w.send(f"down:{int(since)}",
                       f"The desktop VLM ({vlm_reader.URL}, {vlm_reader.MODEL}) has been down "
                       f"since {when} with no game running, so OCR is reading without it.\n"
                       f"{detail}\nRestart: `ssh {desktop_busy.USER}@{desktop_busy.DESKTOPS[-1] if desktop_busy.DESKTOPS else 'desktop'} \"schtasks /run /tn "
                       "llamaswap-boot\"`; game-guard also restarts it 30s after a game ends.",
                       ROOM)
    w.seen.append(f"{STATE}\t{json.dumps(state, sort_keys=True)}")
    w.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
