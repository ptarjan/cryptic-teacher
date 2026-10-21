"""The desktop's addresses, defined once in the untracked local config
(tools/local_config.py: LAN first, tailnet as fallback) for python callers (import desktop_hosts) and shell ones:

    OCR_REMOTE="${OCR_REMOTE-$(python3 tools/desktop_hosts.py remote)}"

`remote` prints user@address,user@address; `addresses` one address a line;
`urls` the VLM's base URLs, one a line; `live` the addresses ranked() for
ssh, the ones answering now first.

The desktop's LAN lease flaps (DHCP: .180 and .198 on 2026-10-14/15), so no
static order is right for long: ranked(port) probes every address at once
(an ssh banner for 22, a TCP connect otherwise), puts those that answered
first (LAN before tailnet: the tailnet path goes silent in bursts; callers that
only probe, the VLM and the game-yield probe, pass tailnet_first) and
keeps that order host-wide for TTL seconds. A caller whose address then
fails calls forget(port), and the next ranked() probes afresh. When no LAN
address answers ssh but the tailnet one does, the desktop is asked over the
tailnet for its LAN addresses (learn), kept LEARN_TTL seconds, so a lease
the config never listed is still found.
"""
import ipaddress
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import local_config

USER = local_config.get("desktop_user")
ADDRESSES = tuple(local_config.get("desktop_addresses"))
VLM_PORT = local_config.get("vlm_port")
REMOTE = ",".join(f"{USER}@{a}" for a in ADDRESSES)
VLM_URLS = tuple(f"http://{a}:{VLM_PORT}" for a in ADDRESSES) if VLM_PORT else ()

#: The port whose probe needs an ssh banner, not a connect alone.
SSH_PORT = 22
#: Seconds a ranking stands, host-wide, before ranked() probes again.
TTL = 60
#: Seconds each address has to answer a probe (all are probed at once).
PROBE_TIMEOUT = 3.0
#: Seconds the LAN addresses the desktop reported (learn) stand.
LEARN_TTL = 3600
#: The host-wide state: {"ranked": {port: {"t", "order"}}, "learned": {"t", "addresses"}}.
STATE = Path(tempfile.gettempdir()) / "desktop_hosts.state.json"
clock = time.time


def tailnet(address):
    try:
        return ipaddress.ip_address(address) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


def _load():
    try:
        got = json.loads(STATE.read_text())
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state):
    tmp = STATE.with_suffix(f".{os.getpid()}.{threading.get_ident()}.part")
    try:
        tmp.write_text(json.dumps(state))
        tmp.replace(STATE)
    except OSError:
        pass


def learned():
    """The LAN addresses the desktop last reported (learn), while fresh."""
    got = _load().get("learned") or {}
    if clock() - got.get("t", 0) < LEARN_TTL:
        return [a for a in got.get("addresses", []) if isinstance(a, str)]
    return []


def candidates():
    """Every address the desktop may be at: the config's, then any it reported."""
    return list(dict.fromkeys([*ADDRESSES, *learned()]))


def is_desktop(address):
    return address in ADDRESSES or address in learned()


def answers(address, port, timeout=None):
    """Whether `address` answers on `port` within `timeout`: for ssh (22) its
    sshd sends its banner (a stale lease can accept a connect and say nothing),
    else the connect is taken."""
    timeout = PROBE_TIMEOUT if timeout is None else timeout
    end = time.monotonic() + timeout  # one deadline for the connect and the banner
    try:
        with socket.create_connection((address, port), timeout=timeout) as s:
            if port != SSH_PORT:
                return True
            s.settimeout(max(0.05, end - time.monotonic()))
            return s.recv(64).startswith(b"SSH-")
    except OSError:
        return False


def probe_all(addresses, port, timeout=None):
    """{address: answered} for every one of `addresses`, probed at once: one
    dead address costs `timeout` once, never one timeout each in turn."""
    timeout = PROBE_TIMEOUT if timeout is None else timeout
    got = {}

    def one(a):
        got[a] = answers(a, port, timeout)
    threads = [threading.Thread(target=one, args=(a,), daemon=True) for a in addresses]
    for t in threads:
        t.start()
    end = time.monotonic() + timeout + 1
    for t in threads:
        t.join(max(0.0, end - time.monotonic()))
    return {a: got.get(a, False) for a in addresses}


def order(addresses, alive, tailnet_first=False):
    """`addresses` with those in `alive` first, LAN before tailnet (tailnet
    before LAN with `tailnet_first`: the tailnet address is stable across the
    KVM's wired/Wi-Fi switch, the LAN ones are not), each
    group in `addresses`' order."""
    return sorted(addresses, key=lambda a: (a not in alive, tailnet(a) != tailnet_first))


def learn(via, timeout=30):
    """The desktop's IPv4 LAN addresses, asked over ssh to `via` (its tailnet
    address), kept host-wide LEARN_TTL seconds; [] when it does not answer."""
    cmd = ("powershell -NoProfile -NonInteractive -Command \"Get-NetIPAddress -AddressFamily IPv4 | "
           "Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | "
           "ForEach-Object { $_.IPAddress }\"")
    try:
        res = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                              "-o", f"HostKeyAlias={ADDRESSES[-1]}", f"{USER}@{via}", cmd],
                             capture_output=True, timeout=timeout, check=False)
        found = [a.strip() for a in res.stdout.decode(errors="replace").split() if a.strip()]
        found = [a for a in found if _ipv4(a) and not tailnet(a)]
    except (OSError, subprocess.TimeoutExpired):
        return []
    if found:
        state = _load()
        state["learned"] = {"t": clock(), "addresses": found}
        _save(state)
    return found


def _ipv4(a):
    try:
        return isinstance(ipaddress.ip_address(a), ipaddress.IPv4Address)
    except ValueError:
        return False


def ranked(port=22, fresh=False, tailnet_first=False):
    """candidates() ranked for `port`, those answering now first (order),
    the ranking kept host-wide TTL seconds unless `fresh`. Every address is
    in it: a caller still tries the silent ones, last. With
    DESKTOP_HOSTS_STATIC set (the tests: no network), the configured order,
    LAN first, unprobed. `tailnet_first` re-sorts that (answering ones still
    first) with the tailnet address before the LAN ones."""
    out = _ranked(port, fresh)
    if not tailnet_first:
        return out
    if os.environ.get("DESKTOP_HOSTS_STATIC"):
        return order(out, set(), True)
    alive = set(((_load().get("ranked") or {}).get(str(port)) or {}).get("alive", []))
    return order(out, alive, True)


def _ranked(port, fresh):
    if os.environ.get("DESKTOP_HOSTS_STATIC"):
        return order(list(ADDRESSES), set())
    key = str(port)
    state = _load()
    cands = candidates()
    kept = (state.get("ranked") or {}).get(key)
    if (not fresh and kept and clock() - kept.get("t", 0) < TTL
            and sorted(kept.get("order", [])) == sorted(cands)):
        return list(kept["order"])
    alive = {a for a, ok in probe_all(cands, port).items() if ok}
    if port == SSH_PORT and alive and not any(not tailnet(a) for a in alive):
        # Only the tailnet answers: the LAN lease moved somewhere the json
        # never listed. Ask the desktop where, and probe what it says.
        new = [a for a in learn(next(a for a in alive if tailnet(a))) if a not in cands]
        if new:
            cands += new
            alive |= {a for a, ok in probe_all(new, port).items() if ok}
    out = order(cands, alive)
    state = _load()
    state.setdefault("ranked", {})[key] = {"t": clock(), "order": out, "alive": sorted(alive)}
    _save(state)
    return out


def forget(port=22):
    """Drop `port`'s kept ranking: an address it put first failed, and the
    next ranked() probes again."""
    state = _load()
    if (state.get("ranked") or {}).pop(str(port), None) is not None:
        _save(state)


def remotes(user=USER, port=22, tailnet_first=False):
    """user@address for every ranked() address."""
    return [f"{user}@{a}" for a in ranked(port, tailnet_first=tailnet_first)]


def vlm_urls():
    """The VLM's base URLs, ranked() for its port."""
    return [f"http://{a}:{VLM_PORT}" for a in ranked(VLM_PORT, tailnet_first=True)]


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "remote"
    if what == "live":
        print("\n".join(ranked(22, fresh=True)))
        sys.exit(0)
    out = {"remote": [REMOTE], "addresses": ADDRESSES, "urls": VLM_URLS}.get(what)
    if out is None:
        sys.exit("usage: desktop_hosts.py remote|addresses|urls|live")
    print("\n".join(out))
