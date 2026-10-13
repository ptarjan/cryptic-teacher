"""The desktop's addresses, defined once in desktop_hosts.json (LAN first,
tailnet as fallback) for python callers (import desktop_hosts) and shell ones:

    OCR_REMOTE="${OCR_REMOTE-$(python3 tools/desktop_hosts.py remote)}"

`remote` prints user@address,user@address; `addresses` one address a line;
`urls` the VLM's base URLs, one a line.
"""
import json
import sys
from pathlib import Path

_DATA = json.loads((Path(__file__).resolve().parent / "desktop_hosts.json").read_text())
USER = _DATA["user"]
ADDRESSES = tuple(_DATA["addresses"])
VLM_PORT = _DATA["vlm_port"]
REMOTE = ",".join(f"{USER}@{a}" for a in ADDRESSES)
VLM_URLS = tuple(f"http://{a}:{VLM_PORT}" for a in ADDRESSES)

if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "remote"
    out = {"remote": [REMOTE], "addresses": ADDRESSES, "urls": VLM_URLS}.get(what)
    if out is None:
        sys.exit("usage: desktop_hosts.py remote|addresses|urls")
    print("\n".join(out))
