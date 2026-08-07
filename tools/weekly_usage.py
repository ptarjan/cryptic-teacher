#!/usr/bin/env python3
"""Print how much of a Claude quota window is spent, as a percent.

The annotation step is the only expensive thing this repo does: three headless
`claude -p` runs a night, each 10-25 minutes of inference. That is fine when the
week is young and a waste of the account when it isn't — a crossword backlog is
never worth being rate-limited for real work. daily_update.sh gates on this.

Two windows matter, and they fail differently:

  weekly  — the account's seven-day quota. Checked once, before the run: if the
            week is already half gone, tonight's puzzles can wait for the reset.
  session — the rolling five-hour window. This one is spent BY THIS SCRIPT, so
            it has to be re-read between puzzles. Checked once at the start it
            is always near zero and always says yes, which is how run after run
            got two puzzles annotated and then died on the third.

Where the numbers come from: the same place the CLI's /usage screen gets them,
`GET /api/oauth/usage` with the subscription's OAuth access token. The token
lives in the *login* keychain, which is also why the daily job is a LaunchAgent
and not a crontab entry — cron runs outside the GUI login session and cannot
unlock it. Do not convert either one to cron.

The keychain item is keyed by CLAUDE_CONFIG_DIR, exactly as the CLI keys it:
"Claude Code-credentials-<first 8 of sha256(configdir)>". Hard-coding the legacy
un-suffixed name cost seven days (2026-08-01 to 08-07): a file-based /login had
blanked that entry to an empty accessToken, so every run sent `Bearer ` with no
token, the API answered 429, and the gate — which fails open on purpose — waved
through three annotations a night with no idea the week was 68% spent. An empty
token is therefore a hard error here rather than a request nobody authorised.

We report the worst window in the requested group, not just the headline one.
The API returns an all-models weekly limit alongside per-model scoped ones
(Fable has its own), and hitting a scoped limit stops annotation just as dead as
hitting the overall one, so the max is the honest answer to "how close are we?".

Usage:
  python3 tools/weekly_usage.py                    # weekly, prints e.g. "68"
  python3 tools/weekly_usage.py --group session    # the five-hour window
  python3 tools/weekly_usage.py --resets-in        # hours left, e.g. "116.9"
                                       # exits 2, printing why, if it can't tell
"""

import datetime
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
# The old shape's field name, per group, for when `limits` isn't in the payload.
LEGACY_FIELD = {"weekly": "seven_day", "session": "five_hour"}


def keychain_services():
    """The credential item names to try, best first.

    The CLI suffixes the service with a hash of its config directory, so a
    machine that has logged in under an explicit CLAUDE_CONFIG_DIR has BOTH
    names present and only one of them holds a live token.
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or \
        os.path.expanduser("~/.claude")
    suffix = hashlib.sha256(config_dir.encode()).hexdigest()[:8]
    return [f"Claude Code-credentials-{suffix}", "Claude Code-credentials"]


def access_token():
    problems = []
    for service in keychain_services():
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=20,
        )
        if raw.returncode != 0:
            problems.append(f"{service}: {raw.stderr.strip() or 'not found'}")
            continue
        token = json.loads(raw.stdout)["claudeAiOauth"]["accessToken"]
        if not token:
            problems.append(f"{service}: empty accessToken (stale /login)")
            continue
        return token
    raise RuntimeError("no usable OAuth token — " + "; ".join(problems))


def _payload():
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {access_token()}",
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def usage_pct(group="weekly"):
    data = _payload()
    pcts = [lim["percent"] for lim in data.get("limits") or []
            if lim.get("group") == group and lim.get("percent") is not None]
    # Older shape, kept as a fallback so a schema change degrades to the
    # headline number rather than to "no idea".
    legacy = (data.get(LEGACY_FIELD.get(group, "")) or {}).get("utilization")
    if not pcts and legacy is not None:
        pcts = [legacy]
    if not pcts:
        raise RuntimeError(f"no {group} window in response: {sorted(data)}")
    return max(float(p) for p in pcts)


def resets_in_hours(group="weekly"):
    """Hours until the window turns over, from the API's own `resets_at`.

    The pre-reset backfill needs this because it is defined by the reset, not by
    the clock: "the last hour of the week" was hard-coded as 04:00-04:55 daily,
    which made an ungated hour of inference run SEVEN nights a week instead of
    one, and that is what kept the week at 68% and the 06:15 job crashing into
    limits. The reset time is a fact the API will tell you; do not infer it.
    """
    data = _payload()
    stamps = [lim["resets_at"] for lim in data.get("limits") or []
              if lim.get("group") == group and lim.get("resets_at")]
    legacy = (data.get(LEGACY_FIELD.get(group, "")) or {}).get("resets_at")
    if not stamps and legacy:
        stamps = [legacy]
    if not stamps:
        raise RuntimeError(f"no {group} resets_at in response: {sorted(data)}")
    # The soonest one: whichever window turns over first ends the current week
    # for the purpose of "is it worth spending the remainder now".
    soonest = min(datetime.datetime.fromisoformat(s) for s in stamps)
    delta = soonest - datetime.datetime.now(datetime.timezone.utc)
    return delta.total_seconds() / 3600.0


def main():
    group = "weekly"
    if "--group" in sys.argv:
        group = sys.argv[sys.argv.index("--group") + 1]
        if group not in LEGACY_FIELD:
            print(f"unknown group {group!r}; expected one of "
                  f"{', '.join(sorted(LEGACY_FIELD))}", file=sys.stderr)
            return 2
    want = "resets" if "--resets-in" in sys.argv else "usage"
    try:
        if want == "resets":
            print(f"{resets_in_hours(group):.1f}")
        else:
            print(f"{usage_pct(group):.0f}")
    except (OSError, urllib.error.URLError, ValueError, KeyError, IndexError,
            RuntimeError, subprocess.SubprocessError) as exc:
        print(f"cannot read {group} {want}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
