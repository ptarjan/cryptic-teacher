"""This machine's own details, kept out of the repo.

The repo is public, so nothing that says where the maintainer's machines are
(addresses, ssh users and key files, the media disk's mount, home directories)
is tracked. It lives in one untracked JSON file, by default
~/.config/cryptic-teacher/local.json (CT_LOCAL_CONFIG names another), e.g.:

    {"desktop_user": "gpuuser",
     "desktop_addresses": ["192.0.2.10", "100.64.0.10"],
     "vlm_port": 8000,
     "desktop_home": "C:\\\\ocr",
     "mac_host": "user@mac.example",
     "mac_ssh_key": "~/.ssh/id_ed25519",
     "media_root": "/mnt/media",
     "household_dir": "~/github/household"}

Every key can also be given by environment variable, CT_<KEY IN CAPITALS>
(CT_DESKTOP_ADDRESSES="a b"), which wins over the file: the tests set these to
fake values. A key set nowhere takes the neutral default below, which names no
real machine: a caller needing a host that is unset fails on the empty value
(require() says which key), it never reaches a stranger's machine.
"""
import json
import os
from pathlib import Path

PATH = Path(os.path.expanduser(os.environ.get("CT_LOCAL_CONFIG") or "~/.config/cryptic-teacher/local.json"))

#: key -> neutral default.
DEFAULTS = {
    "desktop_user": "",
    "desktop_addresses": [],
    "vlm_port": 0,
    "desktop_home": "",
    "mac_host": "",
    "mac_ssh_key": "",
    "media_root": "~/media",
    "household_dir": "~/github/household",
}


def _file():
    try:
        got = json.loads(PATH.read_text())
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def get(key):
    """`key`'s value: the CT_<KEY> environment variable, else the file's, else
    the default. A list-valued key from the environment is split on commas and
    whitespace, an int one is parsed."""
    default = DEFAULTS[key]
    env = os.environ.get("CT_" + key.upper())
    if env is not None:
        if isinstance(default, list):
            return env.replace(",", " ").split()
        return int(env) if isinstance(default, int) else env
    got = _file().get(key)
    if got is None or type(got) is not type(default):
        return default
    return got


def path(key):
    """`key`'s value as a path string with ~ expanded."""
    return os.path.expanduser(get(key))


def require(key):
    """`key`'s value, or a SystemExit naming the key when it is unset."""
    got = get(key)
    if not got:
        raise SystemExit(f"{key} is not set: add it to {PATH} or export CT_{key.upper()}")
    return got


if __name__ == "__main__":
    # For shell callers: `python3 tools/local_config.py household_dir` prints
    # the value (a list one a line, a string ~-expanded).
    import sys
    if len(sys.argv) != 2 or sys.argv[1] not in DEFAULTS:
        sys.exit("usage: local_config.py " + "|".join(DEFAULTS))
    _v = get(sys.argv[1])
    print("\n".join(_v) if isinstance(_v, list) else os.path.expanduser(str(_v)))
