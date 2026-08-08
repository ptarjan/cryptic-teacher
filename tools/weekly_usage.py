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
token, the API answered 429, and the gate — which used to fail open — waved
through three annotations a night with no idea the week was 68% spent. An empty
token is therefore a hard error here rather than a request nobody authorised.
It fails closed now; see gate() and daily_update.sh.

Nothing here refreshes that token — only the CLI does, when it runs. The access
token lives about eight hours, so on a quiet machine every read after it lapses
gets HTTP 401 (found 2026-08-07, four hours of hourly alerts). 401 is not an
account problem and not throttling; it means "nobody has run claude lately". The
job that matters most, the pre-reset backfill, would hit that at 3am on reset
night and skip the one hour it exists for, so every successful read is cached to
.usage_cache.json and a failed read falls back to it. `resets_at` is an absolute
timestamp, which is exactly what makes it safe to cache: a stamp still in the
future is as true today as it was this morning. A percentage isn't, so a cached
one is only honoured for six hours as a *number* and says so on stderr — but it
never stops being a lower bound, because usage inside a window only goes up, and
gate() spends that fact where usage_pct() has to give up.

We report the worst window in the requested group, not just the headline one.
The API returns an all-models weekly limit alongside per-model scoped ones
(Fable has its own), and hitting a scoped limit stops annotation just as dead as
hitting the overall one, so the max is the honest answer to "how close are we?".

Usage:
  python3 tools/weekly_usage.py                    # weekly, prints e.g. "68"
  python3 tools/weekly_usage.py --group session    # the five-hour window
  python3 tools/weekly_usage.py --resets-in        # hours left, e.g. "116.9"
  python3 tools/weekly_usage.py --gate 50          # "spend" / "skip" / "unknown"
                                       # exits 2, printing why, if it can't tell
"""

import datetime
import hashlib
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
# The old shape's field name, per group, for when `limits` isn't in the payload.
LEGACY_FIELD = {"weekly": "seven_day", "session": "five_hour"}
CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".usage_cache.json")
# How stale a cached percentage may be before it is a guess rather than a fact.
PCT_MAX_AGE_HOURS = 6

READ_ERRORS = (OSError, urllib.error.URLError, ValueError, KeyError, IndexError,
               RuntimeError, subprocess.SubprocessError)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _cache_read():
    try:
        with open(CACHE_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _cache_write(key, value):
    """Remember one reading. Never fatal: a read-only checkout still works."""
    data = _cache_read()
    data[key] = {"value": value, "at": _now().isoformat()}
    try:
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, CACHE_PATH)
    except OSError as exc:
        print(f"note: cannot write {CACHE_PATH}: {exc}", file=sys.stderr)


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
    """The live token, plus when it lapses (None if the blob doesn't say)."""
    problems = []
    for service in keychain_services():
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=20,
        )
        if raw.returncode != 0:
            problems.append(f"{service}: {raw.stderr.strip() or 'not found'}")
            continue
        blob = json.loads(raw.stdout)["claudeAiOauth"]
        if not blob.get("accessToken"):
            problems.append(f"{service}: empty accessToken (stale /login)")
            continue
        expires = blob.get("expiresAt")
        return blob["accessToken"], (
            datetime.datetime.fromtimestamp(expires / 1000,
                                            datetime.timezone.utc)
            if expires else None)
    raise RuntimeError("no usable OAuth token — " + "; ".join(problems))


def _payload():
    token, expires = access_token()
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        # Say which kind of 401 this is. Nothing here can fix an expired token —
        # the CLI refreshes it as a side effect of running — so "log in again"
        # would be wrong advice, and "you are rate limited" wronger still.
        if exc.code == 401 and expires and expires <= _now():
            raise RuntimeError(
                f"access token expired {expires.astimezone():%H:%M} and only "
                "the claude CLI refreshes it; this reads it. Any claude run "
                "renews it for ~8h") from exc
        raise


def usage_pct(group="weekly"):
    """The live percentage, or a recent cached one if the read fails."""
    try:
        pct = _live_usage_pct(group)
    except READ_ERRORS as exc:
        cached = _cache_read().get(f"{group}.percent")
        if not cached:
            raise
        age = (_now() - datetime.datetime.fromisoformat(cached["at"]))
        age_h = age.total_seconds() / 3600.0
        if age_h > PCT_MAX_AGE_HOURS:
            raise RuntimeError(
                f"{exc}; the cached {group} reading is {age_h:.0f}h old, too "
                "stale to gate on") from exc
        print(f"note: {exc}; using the {group} reading from {age_h:.1f}h ago",
              file=sys.stderr)
        return float(cached["value"])
    _cache_write(f"{group}.percent", pct)
    return pct


def _live_usage_pct(group):
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


def gate(limit, group="weekly"):
    """Decide whether a spend is allowed: "spend", "skip", or "unknown".

    The caller's real question is not "what is the percentage" but "am I over the
    line", and those are not equally hard. Usage inside a window only ever goes
    up, so ANY reading taken inside the current window is a lower bound on where
    the window stands now, however old it is. A stale reading is therefore
    decisive in exactly one direction: a cached 75% from ten hours ago proves the
    week is at least 75% today, and if the limit is 50% that is a "skip" with no
    guesswork in it. It proves nothing the other way — a stale 20% may since have
    become 90% — so a low stale reading is "unknown", not "spend".

    That asymmetry is the whole point. usage_pct() refuses a cache older than six
    hours because a percentage rots as a *number*; it does not rot as a *floor*.
    Throwing the floor away is what happened on 2026-08-08: the gate held a
    10-hour-old 75%, declared itself blind, and waved through an annotation run
    against a 50% limit that the number it was holding already failed.

    What makes the reading a bound rather than a coincidence is that it belongs
    to the window we are still in, which is why the cached reset stamp is checked
    first. Once the window turns over the counter goes back to zero and yesterday
    says nothing about today.
    """
    try:
        return "skip" if usage_pct(group) > limit else "spend"
    except READ_ERRORS as exc:
        live_error = exc
    cache = _cache_read()
    cached, resets = cache.get(f"{group}.percent"), cache.get(f"{group}.resets_at")
    if not cached or not resets:
        print(f"cannot read {group} usage and no cached reading to bound it: "
              f"{live_error}", file=sys.stderr)
        return "unknown"
    if datetime.datetime.fromisoformat(resets["value"]) <= _now():
        print(f"cannot read {group} usage; the cached reading is from a window "
              f"that has since reset, so it bounds nothing: {live_error}",
              file=sys.stderr)
        return "unknown"
    age_h = (_now() - datetime.datetime.fromisoformat(cached["at"])
             ).total_seconds() / 3600.0
    floor = float(cached["value"])
    if floor > limit:
        print(f"cannot read {group} usage, but the reading from {age_h:.1f}h ago "
              f"was {floor:.0f}% and usage only rises within a window, so it is "
              f"at least that now — over the {limit}% limit", file=sys.stderr)
        return "skip"
    print(f"cannot read {group} usage; the reading from {age_h:.1f}h ago was "
          f"{floor:.0f}%, under the {limit}% limit, and a floor cannot show it "
          f"has stayed there: {live_error}", file=sys.stderr)
    return "unknown"


def resets_in_hours(group="weekly"):
    """Hours until the window turns over, from the API's own `resets_at`.

    The pre-reset backfill needs this because it is defined by the reset, not by
    the clock: "the last hour of the week" was hard-coded as 04:00-04:55 daily,
    which made an ungated hour of inference run SEVEN nights a week instead of
    one, and that is what kept the week at 68% and the 06:15 job crashing into
    limits. The reset time is a fact the API will tell you; do not infer it.

    Cached, and honoured while it is still in the future — an absolute stamp
    does not rot. That is what keeps the 3am backfill from going blind on the
    one night it matters, when nothing has run claude since the afternoon before
    and the access token lapsed hours ago.
    """
    try:
        soonest = _live_resets_at(group)
    except READ_ERRORS as exc:
        cached = _cache_read().get(f"{group}.resets_at")
        if not cached:
            raise
        soonest = datetime.datetime.fromisoformat(cached["value"])
        if soonest <= _now():
            raise RuntimeError(
                f"{exc}; the cached {group} reset "
                f"({soonest.astimezone():%b %d %H:%M}) has already passed, so "
                "there is no telling where the new window stands") from exc
        print(f"note: {exc}; using the cached {group} reset "
              f"{soonest.astimezone():%b %d %H:%M}", file=sys.stderr)
    else:
        _cache_write(f"{group}.resets_at", soonest.isoformat())
    return (soonest - _now()).total_seconds() / 3600.0


def _live_resets_at(group):
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
    return min(datetime.datetime.fromisoformat(s) for s in stamps)


def self_test():
    """Prove the four gate verdicts without touching the network or the keychain.

    A gate is worth exactly what its wrong answers cost, and this one's wrong
    answers are "spend someone's whole week on crosswords". It has been wrong
    twice in production and both times the logic looked obviously right in the
    diff, so the four cases are pinned here and daily_update.sh runs them before
    it trusts a verdict. No fixtures on disk: the point is that the reasoning
    holds, not that a file parses.
    """
    global _live_usage_pct, _cache_read
    live, read, err = _live_usage_pct, _cache_read, sys.stderr
    now = _now()
    hours = datetime.timedelta(hours=1)
    cases = [
        # label, cached %, reading age, reset in, expected verdict
        ("stale reading over the limit is a floor, so it decides",
         75.0, 10 * hours, 96 * hours, "skip"),
        ("stale reading under the limit bounds nothing upward",
         20.0, 10 * hours, 96 * hours, "unknown"),
        ("a reading from a window that has since reset is not a floor",
         75.0, 200 * hours, -1 * hours, "unknown"),
        ("a fresh reading is just a reading",
         75.0, 2 * hours, 96 * hours, "skip"),
    ]
    failures = []
    try:
        def unreachable(_group):
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        _live_usage_pct = unreachable
        # The cases deliberately simulate an unreadable quota, and gate()
        # narrates that on stderr. Left unmuzzled it writes four "cannot read
        # weekly usage" lines into .update.log every night — the exact sentence
        # the real alert tells a human to go and look for. Swallow them.
        sys.stderr = io.StringIO()
        for label, pct, age, until, want in cases:
            _cache_read = lambda p=pct, a=age, u=until: {
                "weekly.percent": {"value": p, "at": (now - a).isoformat()},
                "weekly.resets_at": {"value": (now + u).isoformat(),
                                     "at": (now - a).isoformat()}}
            got = gate(50)
            if got != want:
                failures.append(f"{label}: got {got!r}, want {want!r}")
    finally:
        _live_usage_pct, _cache_read, sys.stderr = live, read, err
    for f in failures:
        print(f"SELF-TEST FAILED — {f}", file=sys.stderr)
    return 1 if failures else 0


def main():
    group = "weekly"
    if "--group" in sys.argv:
        group = sys.argv[sys.argv.index("--group") + 1]
        if group not in LEGACY_FIELD:
            print(f"unknown group {group!r}; expected one of "
                  f"{', '.join(sorted(LEGACY_FIELD))}", file=sys.stderr)
            return 2
    if "--self-test" in sys.argv:
        ok = self_test()
        print("gate self-test: 4 cases pass" if ok == 0 else "gate self-test FAILED")
        return ok
    if "--gate" in sys.argv:
        # A verdict, not a number, and never an empty string: a caller that has
        # to decide something must be handed a decision or an explicit "I don't
        # know", because "" reads as false in shell and quietly means "go".
        verdict = gate(float(sys.argv[sys.argv.index("--gate") + 1]), group)
        print(verdict)
        return 2 if verdict == "unknown" else 0
    want = "resets" if "--resets-in" in sys.argv else "usage"
    try:
        if want == "resets":
            print(f"{resets_in_hours(group):.1f}")
        else:
            print(f"{usage_pct(group):.0f}")
    except READ_ERRORS as exc:
        print(f"cannot read {group} {want}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
