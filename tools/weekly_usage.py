#!/usr/bin/env python3
"""Print how much of the Claude account's WEEKLY quota is spent, as a percent.

The annotation step is the only expensive thing this repo does: three headless
`claude -p` runs a night, each 10-25 minutes of inference. That is fine when the
week is young and a waste of the account when it isn't — a crossword backlog is
never worth being rate-limited for real work. daily_update.sh gates on this.

Where the number comes from: the same place the CLI's /usage screen gets it,
`GET /api/oauth/usage` with the subscription's OAuth access token. The token
lives in the *login* keychain, which is also why the daily job is a LaunchAgent
and not a crontab entry — cron runs outside the GUI login session and cannot
unlock it. Do not convert either one to cron.

We report the worst of every window in the "weekly" group, not just the
headline one. The API returns an all-models weekly limit alongside per-model
scoped ones (Fable has its own), and hitting a scoped limit stops annotation
just as dead as hitting the overall one, so the max is the honest answer to
"how close are we?".

Usage:
  python3 tools/weekly_usage.py        # prints e.g. "74" and exits 0
                                       # exits 2, printing why, if it can't tell
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
KEYCHAIN_SERVICE = "Claude Code-credentials"


def access_token():
    raw = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True, timeout=20,
    )
    if raw.returncode != 0:
        raise RuntimeError(f"keychain read failed: {raw.stderr.strip()}")
    return json.loads(raw.stdout)["claudeAiOauth"]["accessToken"]


def weekly_pct():
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {access_token()}",
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    pcts = [lim["percent"] for lim in data.get("limits") or []
            if lim.get("group") == "weekly" and lim.get("percent") is not None]
    # Older shape, kept as a fallback so a schema change degrades to the
    # headline number rather than to "no idea".
    if not pcts and (data.get("seven_day") or {}).get("utilization") is not None:
        pcts = [data["seven_day"]["utilization"]]
    if not pcts:
        raise RuntimeError(f"no weekly window in response: {sorted(data)}")
    return max(float(p) for p in pcts)


def main():
    try:
        print(f"{weekly_pct():.0f}")
    except (OSError, urllib.error.URLError, ValueError, KeyError,
            RuntimeError, subprocess.SubprocessError) as exc:
        print(f"cannot read weekly usage: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
