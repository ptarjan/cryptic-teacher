#!/usr/bin/env python3
"""Wake the room when GitHub opens a new security alert. Code only, no model call.

Lists open alerts from code-scanning, dependabot and secret-scanning with `gh api
--paginate`. A 403 or 404 on one source means the feature is off: skipped quietly.
Alert keys (source + number) already seen live in ~/.cache/security_alert_watch.json;
any open alert not in that set queues one quiet wake to the room, then is recorded, so
each alert wakes at most once. The first run only seeds the set. Runs at most once an
hour (timestamp in the same state file), from prereset_backfill.sh's checkpoint.

  security_alert_watch.py [--dry-run] [--force]
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

REPO = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(os.environ.get("ANNOTATE_CACHE", pathlib.Path.home() / ".cache"))
STATE = pathlib.Path(os.environ.get("SECURITY_WATCH_STATE", CACHE / "security_alert_watch.json"))
WAKE_SH = os.environ.get("WAKE_SH") or __import__("local_config").path("household_dir") + "/tools/wake.sh"
WAKE_ROOM = os.environ.get("SECURITY_WATCH_ROOM", "web.cryptic-crosswords")
GH = os.environ.get("GH_BIN", "gh")
MIN_INTERVAL_S = 3600
SOURCES = {
    "code-scanning": "repos/{owner}/{repo}/code-scanning/alerts?state=open&per_page=100",
    "dependabot": "repos/{owner}/{repo}/dependabot/alerts?state=open&per_page=100",
    "secret-scanning": "repos/{owner}/{repo}/secret-scanning/alerts?state=open&per_page=100",
}
TAIL = "Fix it in a Sonnet worker (isolation=worktree), push, re-scan, report to Paul."


def fetch(endpoint):
    """Open alerts for one source, or None when the source is off (403/404)."""
    r = subprocess.run([GH, "api", "--paginate", endpoint], capture_output=True, text=True,
                       cwd=REPO, check=False)
    if r.returncode:
        err = r.stderr + r.stdout
        if "403" in err or "404" in err:
            return None
        print(f"security watch: gh failed ({r.returncode}): {err.strip()[:200]}", file=sys.stderr)
        return None
    out = r.stdout.strip()
    if not out:
        return []
    # --paginate prints one JSON array per page, back to back
    dec, i, alerts = json.JSONDecoder(), 0, []
    while i < len(out):
        while i < len(out) and out[i].isspace():
            i += 1
        if i >= len(out):
            break
        page, i = dec.raw_decode(out, i)
        alerts.extend(page if isinstance(page, list) else [page])
    return alerts


def describe(source, a):
    url = a.get("html_url", "")
    if source == "code-scanning":
        loc = (a.get("most_recent_instance") or {}).get("location") or {}
        what = (a.get("rule") or {}).get("id", "?")
        where = f"{loc.get('path', '?')}:{loc.get('start_line', '?')}"
    elif source == "dependabot":
        dep = a.get("dependency") or {}
        what = (dep.get("package") or {}).get("name", "?")
        where = dep.get("manifest_path", "?")
    else:
        what = a.get("secret_type_display_name") or a.get("secret_type", "?")
        where = "secret"
    return f"- {source}: {what} at {where} {url}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="ignore the once-an-hour gate")
    args = ap.parse_args(argv)

    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    now = time.time()
    if not args.force and not args.dry_run and now - state.get("checked", 0) < MIN_INTERVAL_S:
        return 0
    seeded = "seen" in state
    seen = set(state.get("seen", []))
    new, open_keys = [], set()
    for source, endpoint in SOURCES.items():
        alerts = fetch(endpoint)
        if alerts is None:
            continue
        for a in alerts:
            key = f"{source}#{a.get('number')}"
            open_keys.add(key)
            if key not in seen:
                new.append((key, describe(source, a)))
    if seeded and new:
        text = ("New GitHub security alert(s) on the repo:\n" + "\n".join(d for _, d in new)
                + "\n" + TAIL)
        if args.dry_run:
            keys = ", ".join(k for k, _ in new)
            print(f"security watch: WOULD WAKE (dry run) for {len(new)} alert(s): {keys}")
            return 0
        rc = subprocess.run([WAKE_SH, "-q", "-c", WAKE_ROOM, text], check=False).returncode
        if rc:
            print(f"security watch: wake.sh exited {rc}; nothing recorded")
            return rc
        print(f"security watch: woke the room for {len(new)} alert(s)")
    elif args.dry_run:
        print(f"security watch: nothing to send (dry run); {len(open_keys)} open, "
              f"{'seeded' if seeded else 'first run would seed'}")
        return 0
    state = {"checked": now, "seen": sorted(seen | open_keys)}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
