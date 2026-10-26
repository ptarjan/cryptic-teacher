#!/usr/bin/env python3
# Does tools/local_config.py keep this machine's details out of the repo,
# reading them from an untracked file or CT_* variables and failing clearly
# when a needed one is unset?
#
#     python3 tests/test_local_config.py
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "tools"
tmp = Path(tempfile.mkdtemp())
cfg = tmp / "local.json"
cfg.write_text(json.dumps({"desktop_user": "tester", "desktop_addresses": ["192.0.2.1", "100.64.0.1"],
                           "vlm_port": 9999, "media_root": "~/m", "mac_host": 5}))
for k in [k for k in os.environ if k.startswith("CT_") and k.split("_", 1)[1].lower() in
          ("desktop_user", "desktop_addresses", "vlm_port", "desktop_home", "mac_host",
           "mac_ssh_key", "media_root", "household_dir")]:
    del os.environ[k]
os.environ["CT_LOCAL_CONFIG"] = str(cfg)
sys.path.insert(0, str(HERE))
import local_config as lc

bad = 0


def check(name, want, got):
    global bad
    if want != got:
        bad += 1
        print(f"FAIL {name}: want {want!r}, got {got!r}", file=sys.stderr)


check("the file's string", "tester", lc.get("desktop_user"))
check("the file's list", ["192.0.2.1", "100.64.0.1"], lc.get("desktop_addresses"))
check("the file's int", 9999, lc.get("vlm_port"))
check("a wrong-typed value takes the default", "", lc.get("mac_host"))
check("a key the file lacks takes the neutral default", "", lc.get("mac_ssh_key"))
check("path() expands ~", os.path.expanduser("~/m"), lc.path("media_root"))
os.environ["CT_DESKTOP_ADDRESSES"] = "198.51.100.1, 198.51.100.2"
os.environ["CT_VLM_PORT"] = "1234"
check("the environment wins, a list split on commas and spaces", ["198.51.100.1", "198.51.100.2"], lc.get("desktop_addresses"))
check("the environment's int", 1234, lc.get("vlm_port"))
try:
    lc.require("mac_host")
    check("require() on an unset key", "SystemExit", "returned")
except SystemExit as e:
    check("require() names the key", True, "mac_host" in str(e))
lc.PATH = tmp / "missing.json"
check("no file: defaults", "", lc.get("desktop_user"))
got = subprocess.run([sys.executable, str(HERE / "local_config.py"), "desktop_user"], capture_output=True, text=True,
                     env={**os.environ, "CT_DESKTOP_USER": "cli"})
check("the shell form prints the value", "cli\n", got.stdout)
if bad:
    sys.exit(1)
print("ok: local_config reads the file, the environment over it, and defaults to no real machine")
