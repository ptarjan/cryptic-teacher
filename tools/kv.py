"""The one way these tools read the KV namespace.

Two copies of a wrangler call is two places to fix when wrangler changes, and
the retry below is exactly the kind of thing that gets added to one of them.

Reads only. Nothing here writes to KV.
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


def list_keys(timeout=180):
    """Every key name in the namespace, as wrangler's own list of dicts.

    An expired OAuth token comes back as `Authentication error [code: 10000]`
    rather than being refreshed, so the first call of the day fails on a login
    that is perfectly good — and the message reads like a revoked token, which
    sends you to `wrangler login` and a browser you did not need. `whoami` does
    do the refresh, so one of those and a second attempt turns the whole class
    of hourly expiry into nothing. A second failure is a real one.

    wrangler prints a banner before the JSON, so the output is sliced from the
    first bracket rather than parsed whole.
    """
    out = _run(["kv", "key", "list", "--namespace-id", NAMESPACE, "--remote"], timeout)
    if "[" not in out.stdout:
        _run(["whoami"], 60)
        out = _run(["kv", "key", "list", "--namespace-id", NAMESPACE, "--remote"], timeout)
    if "[" not in out.stdout:
        raise SystemExit("wrangler gave no key list: "
                         + ((out.stderr or out.stdout).strip()[-500:] or "no output"))
    return json.loads(out.stdout[out.stdout.index("["):out.stdout.rindex("]") + 1])


def delete_key(name, timeout=120):
    """True if the key is gone, else the reason it is not."""
    out = _run(["kv", "key", "delete", name, "--namespace-id", NAMESPACE, "--remote"],
               timeout)
    return True if out.returncode == 0 else (out.stderr or out.stdout)[-400:]
