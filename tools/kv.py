"""The one way these tools reach the KV namespace.

Two copies of a wrangler call is two places to fix when wrangler changes, and
the retry below is exactly the kind of thing that gets added to one of them.

Lists keys and deletes them. Nothing here writes a value.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMESPACE = "85f9de552ea64b229c113df624fb6ca0"


def _run(args, timeout):
    return subprocess.run(["npx", "wrangler"] + args, cwd=ROOT / "sync",
                          capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=timeout)


def list_keys(prefix=None, timeout=180):
    """Every key name in the namespace, as wrangler's own list of dicts.

    An expired OAuth token comes back as `Authentication error [code: 10000]`
    rather than being refreshed, so the first call of the day fails on a login
    that is perfectly good — and the message reads like a revoked token, which
    sends you to `wrangler login` and a browser you did not need. `whoami` does
    do the refresh, so one of those and a second attempt turns the whole class
    of hourly expiry into nothing. A second failure is a real one.

    Success is the exit status, never a bracket in the output: a failed call
    prints an account table and a log path, and a bracket found in those is a
    bracket that skips the retry above and reaches json.loads as garbage.

    wrangler prints a banner before the JSON, so the output is sliced from the
    first bracket rather than parsed whole.
    """
    args = ["kv", "key", "list", "--namespace-id", NAMESPACE, "--remote"]
    if prefix:
        args += ["--prefix", prefix]
    out = _run(args, timeout)
    if out.returncode != 0:
        _run(["whoami"], 60)
        out = _run(args, timeout)
    if out.returncode != 0:
        raise SystemExit("wrangler gave no key list: "
                         + ((out.stderr or out.stdout).strip()[-500:] or "no output"))
    try:
        return json.loads(out.stdout[out.stdout.index("["):out.stdout.rindex("]") + 1])
    except ValueError as e:
        raise SystemExit(f"wrangler's key list did not parse ({e}): "
                         + (out.stdout.strip()[-500:] or "no output"))


def get_key(name, timeout=120):
    """One key's value, as text. Same expiry retry as list_keys, for the same
    reason: a run that lists fine can still meet the hourly expiry partway
    through reading the keys it just listed."""
    out = _run(["kv", "key", "get", name, "--namespace-id", NAMESPACE, "--remote"], timeout)
    if out.returncode != 0:
        _run(["whoami"], 60)
        out = _run(["kv", "key", "get", name, "--namespace-id", NAMESPACE, "--remote"], timeout)
    if out.returncode != 0:
        raise SystemExit(f"wrangler could not read {name}: "
                         + ((out.stderr or out.stdout).strip()[-500:] or "no output"))
    return out.stdout


def delete_key(name, timeout=120):
    """True if the key is gone, else the reason it is not."""
    out = _run(["kv", "key", "delete", name, "--namespace-id", NAMESPACE, "--remote"],
               timeout)
    return True if out.returncode == 0 else (out.stderr or out.stdout)[-400:]
