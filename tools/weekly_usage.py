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
# How long each window lasts. Not a fitted constant standing in for a queryable
# fact — it is the window's definition, and the API's own field names say it
# ("seven_day", "five_hour"). Used only to roll a reset stamp forward when the
# API has turned the window over without re-stamping it, and only ever to
# conclude "not now"; see resets_in_hours().
WINDOW_LENGTH_HOURS = {"weekly": 7 * 24.0, "session": 5.0}
CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".usage_cache.json")
# How stale a cached percentage may be before it is a guess rather than a fact.
PCT_MAX_AGE_HOURS = 6

READ_ERRORS = (OSError, urllib.error.URLError, ValueError, KeyError, IndexError,
               RuntimeError, subprocess.SubprocessError)

# Where a setup token lives when there is no keychain entry to read one from.
# `claude setup-token` (the bridge's Discord re-login drives this one) writes a
# bare sk-ant-oat01-... string here and touches no keychain at all — see
# household's tools/claude-auth.sh, which is what actually authenticates the
# `claude` runs this script gates. Only ever read here, never written.
FALLBACK_TOKEN_FILE = os.path.expanduser("~/github/household/oauth-token")


class QuotaUnreadable(RuntimeError):
    """The only credential available cannot be read for quota.

    Raised — via _payload(), _live_usage_pct() or _live_resets_at() — only
    when every keychain entry was unusable AND the fallback setup token that
    stood in for them carries no percentage or reset timestamp to read. That
    is not the same fact as "logged out": the CLI itself authenticates fine
    with that token, so a caller that treats "cannot read the quota" as
    "logged out, skip the work" is wrong twice over — once about the account,
    and once about what happens next, since the CLI enforces the real limit
    on its own regardless of what this script can see. gate() is the only
    place this is caught for anything other than a bound made from a stale
    cache; see there for what "cannot see it" is allowed to mean.
    """


def _fallback_token():
    """A setup token: CLAUDE_CODE_OAUTH_TOKEN, else the file it lives in.

    An explicitly exported variable wins — the same preference order the CLI
    itself applies — over a file that may just be left over from a login
    months ago. A token carries no whitespace, so stripping it is also the
    emptiness test. Reading the file is allowed to fail outright: a machine
    signed in normally through the keychain has no such file, which is the
    ordinary case, not an error.
    """
    env = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if env:
        return env
    try:
        with open(FALLBACK_TOKEN_FILE) as fh:
            return fh.read().strip()
    except OSError:
        return ""


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


def _keychain_lookup(service):
    """One keychain entry's token and expiry, or (None, None, why-not).

    Split out of access_token() so a blank-keychain scenario — the exact
    failure this file exists to survive — can be simulated in a test without
    shelling out to `security` or touching a real login.
    """
    raw = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True, text=True, timeout=20,
    )
    if raw.returncode != 0:
        return None, None, f"{service}: {raw.stderr.strip() or 'not found'}"
    blob = json.loads(raw.stdout)["claudeAiOauth"]
    if not blob.get("accessToken"):
        return None, None, f"{service}: empty accessToken (stale /login)"
    expires = blob.get("expiresAt")
    expires_dt = (datetime.datetime.fromtimestamp(expires / 1000,
                                                   datetime.timezone.utc)
                  if expires else None)
    return blob["accessToken"], expires_dt, None


def access_token():
    """The live token, when it lapses (None if unknown), and whether it came
    from the keychain rather than the fallback setup token — the third value
    callers need to decide what an unreadable quota should mean; see
    QuotaUnreadable and gate().
    """
    problems = []
    for service in keychain_services():
        token, expires, problem = _keychain_lookup(service)
        if problem:
            problems.append(problem)
            continue
        return token, expires, False
    fallback = _fallback_token()
    if fallback:
        # A working CLI credential, just not one a keychain reader can see a
        # percentage in. Handed back rather than treated as another kind of
        # failure — see QuotaUnreadable, which is what the caller raises
        # instead of dying here.
        return fallback, None, True
    raise RuntimeError("no usable OAuth token — " + "; ".join(problems))


def _payload():
    token, expires, fallback = access_token()
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp), fallback
    except urllib.error.HTTPError as exc:
        if fallback:
            # A setup token has no expiresAt to blame a 401 on, and there is
            # no /login to suggest — the CLI itself is authenticated fine
            # with this same token. See QuotaUnreadable.
            raise QuotaUnreadable(
                f"quota unreadable with the fallback OAuth token ({exc}); "
                "proceeding — the CLI enforces the real limit on its own"
            ) from exc
        # Say which kind of 401 this is. Nothing here can fix an expired token —
        # the CLI refreshes it as a side effect of running — so "log in again"
        # would be wrong advice, and "you are rate limited" wronger still.
        if exc.code == 401 and expires and expires <= _now():
            raise RuntimeError(
                f"access token expired {expires.astimezone():%H:%M} and only "
                "the claude CLI refreshes it; this reads it. Any claude run "
                "renews it for ~8h") from exc
        raise
    except (urllib.error.URLError, ValueError) as exc:
        if fallback:
            raise QuotaUnreadable(
                f"quota unreadable with the fallback OAuth token ({exc}); "
                "proceeding — the CLI enforces the real limit on its own"
            ) from exc
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
    data, fallback = _payload()
    pcts = [lim["percent"] for lim in data.get("limits") or []
            if lim.get("group") == group and lim.get("percent") is not None]
    # Older shape, kept as a fallback so a schema change degrades to the
    # headline number rather than to "no idea".
    legacy = (data.get(LEGACY_FIELD.get(group, "")) or {}).get("utilization")
    if not pcts and legacy is not None:
        pcts = [legacy]
    if not pcts:
        if fallback:
            # The exact shape a setup token's own /usage read takes: it
            # authenticates fine and the response has nothing this script
            # can turn into a percentage. See QuotaUnreadable.
            raise QuotaUnreadable(
                f"no {group} window in a response read with the fallback "
                "OAuth token; proceeding — the CLI enforces the real limit "
                "on its own")
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
    # A QuotaUnreadable means a working credential that this script simply
    # cannot read a percentage from — not a logged-out account. Skipping real
    # work over that is the exact bug this file exists to fix, so absent
    # concrete evidence of being over the limit (the cached-floor branches
    # below), the answer is "proceed", never "unknown".
    unreadable_by_design = isinstance(live_error, QuotaUnreadable)
    cache = _cache_read()
    cached, resets = cache.get(f"{group}.percent"), cache.get(f"{group}.resets_at")
    if not cached or not resets:
        if unreadable_by_design:
            print(f"{live_error}, and no cached reading to bound it",
                  file=sys.stderr)
            return "spend"
        print(f"cannot read {group} usage and no cached reading to bound it: "
              f"{live_error}", file=sys.stderr)
        return "unknown"
    if datetime.datetime.fromisoformat(resets["value"]) <= _now():
        if unreadable_by_design:
            print(f"{live_error}; the cached reading is from a window that "
                  "has since reset, so it bounds nothing", file=sys.stderr)
            return "spend"
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
    if unreadable_by_design:
        print(f"{live_error}; the reading from {age_h:.1f}h ago was "
              f"{floor:.0f}%, under the {limit}% limit", file=sys.stderr)
        return "spend"
    print(f"cannot read {group} usage; the reading from {age_h:.1f}h ago was "
          f"{floor:.0f}%, under the {limit}% limit, and a floor cannot show it "
          f"has stayed there: {live_error}", file=sys.stderr)
    return "unknown"


def resets_in_hours(group="weekly"):
    """Hours until the window turns over, and whether that is a fact or a floor.

    Returns `(hours, derived)`. `derived` False means an absolute `resets_at`
    said so, live or cached. True means nobody said so and the number is one
    window length past the last reset we saw — see below.

    The pre-reset backfill needs this because it is defined by the reset, not by
    the clock: "the last hour of the week" was hard-coded as 04:00-04:55 daily,
    which made an ungated hour of inference run SEVEN nights a week instead of
    one, and that is what kept the week at 68% and the 06:15 job crashing into
    limits. The reset time is a fact the API will tell you; do not infer it.

    Cached, and honoured while it is still in the future — an absolute stamp
    does not rot. That is what keeps the 3am backfill from going blind on the
    one night it matters, when nothing has run claude since the afternoon before
    and the access token lapsed hours ago.

    The gap that left, found 2026-08-12 05:05: the reset had happened at 04:59,
    and for the hour after it the API returned the weekly window with
    `resets_at: null` — turned over, not yet re-stamped. Live read empty, cached
    stamp just expired, so this raised and the backfill fired its "can't tell
    whether this is the hour" alert. It could tell. A window that reset sixty
    seconds ago is the one moment in the week when "is this the last hour of the
    window" has a confident answer, and the answer is no.

    So a passed cached stamp is rolled forward by one window length instead of
    thrown away, and flagged. The flag is the point: a derived number may only
    ever be used to say "not now". Spending an ungated hour of inference on an
    inferred reset time is precisely the mistake the hard-coded 04:00 was, and
    one that would land ON the guess rather than near it. The caller enforces
    that; see prereset_backfill.sh. Rolling more than one window forward means we
    have been unable to read for a whole period, which is a real outage and still
    raises.
    """
    try:
        soonest = _live_resets_at(group)
    except READ_ERRORS as exc:
        cached = _cache_read().get(f"{group}.resets_at")
        if not cached:
            raise
        soonest = datetime.datetime.fromisoformat(cached["value"])
        if soonest <= _now():
            period = datetime.timedelta(hours=WINDOW_LENGTH_HOURS[group])
            rolled = soonest + period
            if rolled <= _now():
                raise RuntimeError(
                    f"{exc}; the cached {group} reset "
                    f"({soonest.astimezone():%b %d %H:%M}) is more than one "
                    f"window old, so even the next one it implies has passed "
                    "and there is no telling where the window stands") from exc
            print(f"note: {exc}; the cached {group} reset "
                  f"({soonest.astimezone():%b %d %H:%M}) has passed, so the "
                  f"window turned over then and the next is no sooner than "
                  f"{rolled.astimezone():%b %d %H:%M}", file=sys.stderr)
            return (rolled - _now()).total_seconds() / 3600.0, True
        print(f"note: {exc}; using the cached {group} reset "
              f"{soonest.astimezone():%b %d %H:%M}", file=sys.stderr)
    else:
        _cache_write(f"{group}.resets_at", soonest.isoformat())
    return (soonest - _now()).total_seconds() / 3600.0, False


def _live_resets_at(group):
    data, fallback = _payload()
    stamps = [lim["resets_at"] for lim in data.get("limits") or []
              if lim.get("group") == group and lim.get("resets_at")]
    legacy = (data.get(LEGACY_FIELD.get(group, "")) or {}).get("resets_at")
    if not stamps and legacy:
        stamps = [legacy]
    if not stamps:
        if fallback:
            raise QuotaUnreadable(
                f"no {group} resets_at in a response read with the fallback "
                "OAuth token")
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
            def _mock_cache(p=pct, a=age, u=until):
                return {
                    "weekly.percent": {"value": p, "at": (now - a).isoformat()},
                    "weekly.resets_at": {"value": (now + u).isoformat(),
                                         "at": (now - a).isoformat()}}
            _cache_read = _mock_cache
            got = gate(50)
            if got != want:
                failures.append(f"{label}: got {got!r}, want {want!r}")
    finally:
        _live_usage_pct, _cache_read, sys.stderr = live, read, err
    for f in failures:
        print(f"SELF-TEST FAILED — {f}", file=sys.stderr)
    return 1 if failures else 0


def reset_self_test():
    """Prove what resets_in_hours() does when the API stops naming the reset.

    Pinned because the failure it fixes was silent in the worst way: the job
    alerted a human at 05:05 on reset morning saying it could not tell where the
    window stood, an hour after the window had visibly turned over in its own
    cache. The three cases below are the three shapes that exist, and the third
    is the one that must never become "spend".
    """
    global _live_resets_at, _cache_read
    live, read, err = _live_resets_at, _cache_read, sys.stderr
    now = _now()
    h = datetime.timedelta(hours=1)
    week = WINDOW_LENGTH_HOURS["weekly"]
    cases = [
        # label, cached stamp relative to now, expected (hours, derived)
        ("a cached stamp still ahead of us is a fact", 96 * h, (96.0, False)),
        ("a stamp that just passed means the window turned over then, and the "
         "next one is a window later", -1 * h, (week - 1, True)),
        ("a stamp more than a window old implies nothing", -(week + 1) * h,
         None),
    ]
    failures = []
    try:
        def unreachable(_group):
            raise RuntimeError("no weekly resets_at in response: ['limits']")
        _live_resets_at = unreachable
        sys.stderr = io.StringIO()
        for label, offset, want in cases:
            def _mock_cache(o=offset):
                return {
                    "weekly.resets_at": {"value": (now + o).isoformat(),
                                         "at": now.isoformat()}}
            _cache_read = _mock_cache
            try:
                hours, derived = resets_in_hours()
                got = (round(hours), derived)
            except READ_ERRORS:
                got = None
            if want is not None:
                want = (round(want[0]), want[1])
            if got != want:
                failures.append(f"{label}: got {got!r}, want {want!r}")
    finally:
        _live_resets_at, _cache_read, sys.stderr = live, read, err
    for f in failures:
        print(f"SELF-TEST FAILED — {f}", file=sys.stderr)
    return 1 if failures else 0


def fallback_self_test():
    """Prove a blank keychain plus a present fallback token decides "proceed".

    This is the bug as it shipped: both keychain entries blank, one env var
    or file holding a real setup token. access_token() must hand that token
    back rather than raise "no usable OAuth token", and gate() must answer
    "spend" for it rather than "unknown" — "cannot see the quota" is not
    "logged out", and a caller that skips real work on that confusion is
    exactly the failure this file exists to prevent. See QuotaUnreadable.
    """
    global _keychain_lookup, _fallback_token, _live_usage_pct, _cache_read
    orig = (_keychain_lookup, _fallback_token, _live_usage_pct, _cache_read)
    err = sys.stderr
    failures = []
    try:
        def _mock_lookup(service):
            return None, None, f"{service}: empty accessToken (stale /login)"
        def _mock_fallback():
            return "sk-ant-oat01-test-token-not-a-real-secret"
        _keychain_lookup = _mock_lookup
        _fallback_token = _mock_fallback
        sys.stderr = io.StringIO()

        token, expires, fallback = access_token()
        if not (token and fallback and expires is None):
            failures.append(
                "access_token() with both keychain entries blank and a "
                f"fallback token present: got {(bool(token), expires, fallback)!r}"
                ", want (True, None, True)")

        def unreadable(_group):
            raise QuotaUnreadable("no usage fields on a setup token")
        _live_usage_pct = unreadable
        def _mock_cache():
            return {}
        _cache_read = _mock_cache
        got = gate(50)
        if got != "spend":
            failures.append(
                "gate() with blank keychain + fallback token + no cache: "
                f"got {got!r}, want 'spend'")
    finally:
        _keychain_lookup, _fallback_token, _live_usage_pct, _cache_read = orig
        sys.stderr = err
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
        ok = self_test() or reset_self_test() or fallback_self_test()
        print("gate self-test: 9 cases pass" if ok == 0 else "gate self-test FAILED")
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
            hours, derived = resets_in_hours(group)
            print(f"{hours:.1f}")
            # Exit 3, not 0: the number is a lower bound inferred from a window
            # that has demonstrably turned over, not a stamp anybody handed us.
            # A caller that spends real quota on the answer has to be able to
            # tell the difference, and stdout is a float either way.
            return 3 if derived else 0
        print(f"{usage_pct(group):.0f}")
    except READ_ERRORS as exc:
        print(f"cannot read {group} {want}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
