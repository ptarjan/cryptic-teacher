#!/usr/bin/env python3
"""Block until the live site is serving what is in the working tree.

"Fixed and pushed — reload the iPad" is a lie for the minute or two that GitHub
Pages takes to build, and the person who reloads inside that window sees the old
bug and reasonably concludes the fix did not work (Paul, 2026-08-16). Pushing is
not deploying. Nobody should be told to reload until this exits 0.

Two checks, because either one alone passes on a deploy that has not happened.
The commit GitHub Pages last built must be the local HEAD, which covers every
file in the push — a change to markup or to a generated page moves no asset
stamp, and a stamps-only check called such a deploy live the instant it was
pushed. And the live index.html must carry the local asset stamps, which the
commit check cannot see: the commit is built, but the CDN can still be handing
out the previous page, and the stamps are what a reload actually picks up.

    python3 tools/wait_for_deploy.py            # poll until live, or fail
    python3 tools/wait_for_deploy.py --check    # one look, no waiting

Exit 0 live, 1 timed out or mismatched. Run it as the last step of the deploy
pipeline, after the push.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

URL = "https://paultarjan.com/cryptic-teacher/"
STAMP = re.compile(r'(app\.js|style\.css|puzzles/index\.js)\?v=([a-f0-9]+)')


def stamps(text):
    return dict(STAMP.findall(text))


def fetch():
    # Pages sits behind a CDN; without this we can poll a cached copy of the old
    # page for the whole timeout and report a failure that never existed.
    req = urllib.request.Request(URL, headers={
        "Cache-Control": "no-cache", "Pragma": "no-cache",
        "User-Agent": "cryptic-teacher-deploy-check",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def built_commit():
    """The commit GitHub Pages is currently serving, or None if it cannot say.

    Unreachable API, no gh, no auth: return None and let the stamps decide, so a
    laptop without gh still gets the old check rather than a hard failure.
    """
    try:
        out = subprocess.run(
            ["gh", "api", "repos/ptarjan/cryptic-teacher/pages/builds/latest"],
            capture_output=True, text=True, timeout=30, cwd=ROOT)
        if out.returncode != 0:
            return None
        b = json.loads(out.stdout)
        return b.get("commit") if b.get("status") == "built" else ""
    except Exception:                                 # noqa: BLE001 - "cannot say"
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="one look, do not wait")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as f:
        want = stamps(f.read())
    if not want:
        print("no asset stamps in local index.html — run tools/stamp_assets.py", file=sys.stderr)
        return 1

    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, cwd=ROOT).stdout.strip()
    deadline = time.time() + (0 if args.check else args.timeout)
    while True:
        try:
            built = built_commit()
            live = stamps(fetch())
            diff = {k: (v, live.get(k)) for k, v in want.items() if live.get(k) != v}
            if not diff and built in (None, head):
                print("live: " + ", ".join(f"{k}?v={v}" for k, v in sorted(want.items()))
                      + (f", commit {head[:8]}" if built else ", commit unverified"))
                return 0
            note = "; ".join(f"{k} want {w} got {g}" for k, (w, g) in sorted(diff.items()))
            if built not in (None, head):
                note = ((note + "; ") if note else "") + (
                    f"Pages has {built[:8] or 'a build in flight'}, want {head[:8]}")
        except Exception as exc:                      # noqa: BLE001 - any failure is "not live yet"
            note = f"{type(exc).__name__}: {exc}"
        if time.time() >= deadline:
            print(f"NOT DEPLOYED: {note}", file=sys.stderr)
            return 1
        print(f"waiting for deploy ({note})", flush=True)
        time.sleep(10)


if __name__ == "__main__":
    sys.exit(main())
