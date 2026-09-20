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
lives in the *login* keychain on a Mac, which is why the timed jobs cannot be
scheduled with cron there — cron runs outside the GUI login session and cannot
unlock it. In the bridge container there is no keychain and the credential is a
file under CLAUDE_CONFIG_DIR, which is why they are cron lines here.

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

There is a second, free source of the same number: the bridge samples it every
five minutes into /data/usage-history.csv, stamped with the window it belongs
to, needing no credential and making no request. Every fallback here reads the
newer of that and the cache, per field. It is a container path — where it is
absent this behaves exactly as it did before, on the cache alone.

We report the worst window in the requested group, not just the headline one.
The API returns an all-models weekly limit alongside per-model scoped ones
(Fable has its own), and hitting a scoped limit stops annotation just as dead as
hitting the overall one, so the max is the honest answer to "how close are we?".

Usage:
  python3 tools/weekly_usage.py                    # weekly, prints e.g. "68"
  python3 tools/weekly_usage.py --group session    # the five-hour window
  python3 tools/weekly_usage.py --resets-in        # hours left, e.g. "116.9"
  CT_SPEND_BY=2026-09-21T12:00:00-07:00 ...              # an earlier deadline
      than the weekly reset, for "have the remainder spent by Monday noon".
      Weekly only, sooner only, and ignored once it has passed. See _spend_by.
  python3 tools/weekly_usage.py --gate 50          # "spend" / "skip" / "unknown"
                                       # exits 2, printing why, if it can't tell
"""

import datetime
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
# The bridge samples this same number every five minutes and appends it here as
# `ts,kind,pct,resets_at`, whether or not anything in this repo runs. It needs
# no credential and makes no request, which is exactly why the gate reads it: a
# throttled or lapsed HTTP read is when a reading is wanted most. The kind
# column carries the API's own window names, so LEGACY_FIELD maps to it too.
SAMPLE_CSV_PATH = os.environ.get("USAGE_HISTORY_CSV", "/data/usage-history.csv")

READ_ERRORS = (OSError, urllib.error.URLError, ValueError, KeyError, IndexError,
               RuntimeError, subprocess.SubprocessError)

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
    """A setup token from CLAUDE_CODE_OAUTH_TOKEN, or "".

    An exported variable is the only place a setup token is read from. There
    is no file to fall back to: household retired the one it used to mint into
    its state dir, and treats a file reappearing there as something to delete,
    because it outranks the CLI's own store at the next boot and would undo a
    login that succeeded weeks earlier (household config.py, OAUTH_TOKEN_FILE).
    A token carries no whitespace, so stripping it is also the emptiness test.
    """
    return os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()


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


def _sampled_reading(group):
    """The newest sampled reading for `group`, or None if there is no sampler.

    Read from the end: the file holds a week of five-minute rows and only the
    last one is a reading of now.
    """
    kind = LEGACY_FIELD.get(group)
    try:
        with open(SAMPLE_CSV_PATH) as fh:
            rows = fh.readlines()
    except OSError:
        return None
    for line in reversed(rows):
        parts = line.strip().split(",")
        if len(parts) != 4 or parts[1] != kind:
            continue
        try:
            at, pct, resets = int(parts[0]), float(parts[2]), float(parts[3])
        except ValueError:
            continue
        stamp = lambda t: datetime.datetime.fromtimestamp(
            t, datetime.timezone.utc).isoformat()
        return {"value": pct, "at": stamp(at), "resets_at": stamp(resets),
                "stamped_at": stamp(at)}
    return None


def _fallback_reading(group):
    """The best reading available without a request, or None.

    Two places say where the window last stood: this script's own cache, written
    whenever a live read succeeds here, and the sampler's file, written every
    five minutes regardless. They are the same number from the same API, so the
    only question is which is newer, and it is almost always the sampler's — on
    2026-09-13 a 429 skipped a night of annotation against a 22h-old cache while
    a reading from forty seconds earlier sat on disk unread.

    Every row is stamped with the window it belongs to, which is what lets a
    reading be used as a floor: see gate().
    """
    cache = _cache_read()
    pct, resets = cache.get(f"{group}.percent"), cache.get(f"{group}.resets_at")
    cached = (pct or resets) and {
        "value": float(pct["value"]) if pct else None,
        "at": pct["at"] if pct else None,
        "resets_at": resets["value"] if resets else None,
        "stamped_at": resets["at"] if resets else None}
    readings = [r for r in (cached, _sampled_reading(group)) if r]
    if not readings:
        return None
    # Per field, with each field judged by when THAT field was read. The cache
    # writes the percentage and the reset stamp at different moments, so a cache
    # holding a minute-old percentage next to a week-old reset stamp would
    # otherwise carry the dead stamp in on the live number's timestamp — which
    # is how a fresh sampled reset lost to a stamp from the previous window.
    def newest(field, when):
        return max((r for r in readings if r[field] is not None), default=None,
                   key=lambda r: datetime.datetime.fromisoformat(r[when]))
    valued, stamped = newest("value", "at"), newest("resets_at", "stamped_at")
    if not valued and not stamped:
        return None
    return {"value": valued["value"] if valued else None,
            "at": valued["at"] if valued else stamped["stamped_at"],
            "resets_at": stamped["resets_at"] if stamped else None}


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
    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=20,
        )
    except FileNotFoundError:
        # No `security` binary means no keychain to read, which is a reason
        # this lookup failed and not a reason the whole chain should stop.
        # Raising here skipped every remaining credential source, so a Linux
        # host reported "cannot read the quota" while holding a live token.
        return None, None, f"{service}: no keychain on this platform"
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


def _credentials_file_lookup():
    """The CLI's own credential store, or (None, None, why-not).

    Same shape and same contents as a keychain entry — this is where the CLI
    writes an OAuth login on a platform with no keychain — so it yields a real
    expiry and a real usage percentage, unlike the setup token below it.
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or \
        os.path.expanduser("~/.claude")
    path = os.path.join(config_dir, ".credentials.json")
    try:
        with open(path) as fh:
            blob = json.load(fh)["claudeAiOauth"]
    except (OSError, ValueError, KeyError) as exc:
        return None, None, f"{path}: {exc}"
    if not blob.get("accessToken"):
        return None, None, f"{path}: empty accessToken (stale /login)"
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
    token, expires, problem = _credentials_file_lookup()
    if problem:
        problems.append(problem)
    else:
        return token, expires, False
    fallback = _fallback_token()
    if fallback:
        # A working CLI credential, just not one a keychain reader can see a
        # percentage in. Handed back rather than treated as another kind of
        # failure — see QuotaUnreadable, which is what the caller raises
        # instead of dying here.
        return fallback, None, True
    raise RuntimeError("no usable OAuth token — " + "; ".join(problems))


# A quota read that is merely throttled has not learned anything about the
# quota, and the gate fails closed on an unreadable one — so a single 429 costs
# a night of annotation. Retried instead, honouring Retry-After; the sleeps are
# short and bounded because a handful of these run between puzzles.
RETRY_STATUSES = (429, 500, 502, 503, 504)
RETRY_BACKOFF_SECONDS = (5, 20)
RETRY_AFTER_CAP_SECONDS = 45


def _retry_after(exc, default):
    """How long the server asked us to wait, clamped to something a nightly job
    can afford. Absent or unparseable means the default backoff."""
    try:
        wait = float(exc.headers.get("Retry-After", ""))
    except (AttributeError, TypeError, ValueError):
        return default
    return max(0.0, min(wait, RETRY_AFTER_CAP_SECONDS))


def _fetch(req, attempt):
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp), None
    except urllib.error.HTTPError as exc:
        if exc.code not in RETRY_STATUSES or attempt >= len(RETRY_BACKOFF_SECONDS):
            raise
        return None, _retry_after(exc, RETRY_BACKOFF_SECONDS[attempt])


def _payload():
    token, expires, fallback = access_token()
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
    })
    try:
        for attempt in range(len(RETRY_BACKOFF_SECONDS) + 1):
            data, wait = _fetch(req, attempt)
            if wait is None:
                return data, fallback
            print(f"note: quota read throttled, retrying in {wait:.0f}s",
                  file=sys.stderr)
            time.sleep(wait)
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
        cached = _fallback_reading(group)
        if not cached or cached["value"] is None:
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
    cached = _fallback_reading(group)
    if not cached or cached["value"] is None or not cached["resets_at"]:
        if unreadable_by_design:
            print(f"{live_error}, and no recent reading to bound it",
                  file=sys.stderr)
            return "spend"
        print(f"cannot read {group} usage and no recent reading to bound it: "
              f"{live_error}", file=sys.stderr)
        return "unknown"
    if datetime.datetime.fromisoformat(cached["resets_at"]) <= _now():
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
        cached = _fallback_reading(group)
        if not cached or not cached["resets_at"]:
            raise
        soonest = datetime.datetime.fromisoformat(cached["resets_at"])
        if soonest <= _now():
            period = datetime.timedelta(hours=WINDOW_LENGTH_HOURS[group])
            rolled = soonest + period
            if rolled <= _now():
                raise RuntimeError(
                    f"{exc}; the last known {group} reset "
                    f"({soonest.astimezone():%b %d %H:%M}) is more than one "
                    f"window old, so even the next one it implies has passed "
                    "and there is no telling where the window stands") from exc
            print(f"note: {exc}; the last known {group} reset "
                  f"({soonest.astimezone():%b %d %H:%M}) has passed, so the "
                  f"window turned over then and the next is no sooner than "
                  f"{rolled.astimezone():%b %d %H:%M}", file=sys.stderr)
            return _spend_by(group, rolled, True)
        print(f"note: {exc}; using the last known {group} reset "
              f"{soonest.astimezone():%b %d %H:%M}", file=sys.stderr)
    else:
        _cache_write(f"{group}.resets_at", soonest.isoformat())
    return _spend_by(group, soonest, derived=False)


# An earlier deadline than the account's own reset, for the one case where the
# window is not what we are racing: "have the remainder spent by Monday noon".
# Everything downstream — the start gate, still_behind, the wave width, the stop
# time — asks resets_in_hours() and nothing else, so overriding it here is the
# only way all five agree. Setting it in one caller and not the others is how a
# job starts on one deadline and paces itself to another.
SPEND_BY_VAR = "CT_SPEND_BY"


def _spend_by(group, when, derived):
    """(hours, derived) until `when`, or until $CT_SPEND_BY if that is sooner.

    Three rules, each of which is load-bearing:

    SOONER ONLY. The override can pull the deadline in, never push it out. A
    later one would have the backfill spending the NEXT week's quota on this
    week's backlog, which is the opposite of the point, and would do it while
    reporting hours that no meter agrees with.

    WEEKLY ONLY. The five-hour window is a physical limit, not a target; moving
    it would mis-size every wave against a turnover that is still going to
    happen when it was always going to.

    A PASSED DEADLINE IS IGNORED. It expires into ordinary behaviour rather than
    latching, because the alternative is negative hours-until-reset — which
    reads as "the reset is behind us", opens the gate, computes a stop time in
    the past and exits having spent nothing, hourly, forever. A deadline we
    missed must leave the real reset still to aim at.
    """
    raw = os.environ.get(SPEND_BY_VAR, "").strip()
    if raw and group == "weekly":
        try:
            deadline = datetime.datetime.fromisoformat(raw)
        except ValueError:
            print(f"note: ignoring {SPEND_BY_VAR}={raw!r}: not an ISO 8601 "
                  "timestamp", file=sys.stderr)
        else:
            if deadline.tzinfo is None:
                deadline = deadline.astimezone()
            if deadline <= _now():
                print(f"note: ignoring {SPEND_BY_VAR} "
                      f"({deadline.astimezone():%b %d %H:%M}): it has passed, "
                      "so the real reset is the deadline again",
                      file=sys.stderr)
            elif deadline < when:
                print(f"note: {SPEND_BY_VAR} brings the weekly deadline "
                      f"forward to {deadline.astimezone():%b %d %H:%M} from "
                      f"{when.astimezone():%b %d %H:%M}", file=sys.stderr)
                # Not derived: a deadline handed to us is a fact, and it is the
                # binding one even when the reset behind it was only inferred.
                when, derived = deadline, False
    return (when - _now()).total_seconds() / 3600.0, derived


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
    global _live_usage_pct, _cache_read, _sampled_reading
    live, read, err = _live_usage_pct, _cache_read, sys.stderr
    sample = _sampled_reading
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
        # These cases are about the cache, so the machine's real sampler file —
        # which outranks it whenever it is fresher — is taken off the table.
        _sampled_reading = lambda _group: None
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
        _sampled_reading = sample
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
    global _live_resets_at, _cache_read, _sampled_reading
    live, read, err = _live_resets_at, _cache_read, sys.stderr
    sample = _sampled_reading
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
        _sampled_reading = lambda _group: None
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
        _sampled_reading = sample
    for f in failures:
        print(f"SELF-TEST FAILED — {f}", file=sys.stderr)
    return 1 if failures else 0


def spend_by_self_test():
    """Prove $CT_SPEND_BY can only ever pull the weekly deadline closer.

    The override exists so "have the remainder spent by Monday noon" can be
    asked for without editing five call sites, and every way of getting it
    wrong spends real quota: one that pushed the deadline out would spend next
    week's, one that moved the five-hour window would mis-size every wave, and
    one that stayed set after it passed would wedge the gate open on a stop
    time already in the past and burn nothing, hourly, forever.
    """
    global _live_resets_at, _cache_read, _sampled_reading
    live, read, err = _live_resets_at, _cache_read, sys.stderr
    sample = _sampled_reading
    now = _now()
    h = datetime.timedelta(hours=1)
    week = WINDOW_LENGTH_HOURS["weekly"]
    reset_at = now + 80 * h

    cases = [
        # label, env value, group, live reset or None for the derived path,
        # expected (hours, derived)
        ("unset changes nothing", None, "weekly", reset_at, (80, False)),
        ("a sooner deadline binds", (now + 41 * h).isoformat(), "weekly",
         reset_at, (41, False)),
        ("a later deadline is ignored", (now + 99 * h).isoformat(), "weekly",
         reset_at, (80, False)),
        ("a passed deadline is ignored", (now - 1 * h).isoformat(), "weekly",
         reset_at, (80, False)),
        ("an unparseable deadline is ignored", "monday noon", "weekly",
         reset_at, (80, False)),
        ("the five-hour window is never moved", (now + 1 * h).isoformat(),
         "session", now + 4 * h, (4, False)),
        # A deadline is something we were told; an inferred reset is not. The
        # caller refuses to spend on `derived`, so a binding deadline has to
        # clear it or the override would be unusable in the hour after a reset.
        ("a deadline beats an inferred reset, as a fact",
         (now + 2 * h).isoformat(), "weekly", None, (2, False)),
    ]
    failures = []
    try:
        _sampled_reading = lambda _group: None
        sys.stderr = io.StringIO()
        for label, value, group, stamp, want in cases:
            if stamp is None:      # nothing live, cache holds a just-passed one
                def unreachable(_group):
                    raise RuntimeError("no resets_at in response: ['limits']")
                _live_resets_at = unreachable
                _cache_read = lambda: {
                    f"{group}.resets_at": {"value": (now - 1 * h).isoformat(),
                                           "at": now.isoformat()}}
            else:
                _live_resets_at = lambda _group, at=stamp: at
                _cache_read = dict
            if value is None:
                os.environ.pop(SPEND_BY_VAR, None)
            else:
                os.environ[SPEND_BY_VAR] = value
            try:
                hours, derived = resets_in_hours(group)
                got = (round(hours), derived)
            except READ_ERRORS as exc:
                got = repr(exc)
            if got != want:
                failures.append(f"{label}: got {got!r}, want {want!r}")
    finally:
        _live_resets_at, _cache_read, sys.stderr = live, read, err
        _sampled_reading = sample
        os.environ.pop(SPEND_BY_VAR, None)
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
    global _keychain_lookup, _credentials_file_lookup, _fallback_token
    global _live_usage_pct, _cache_read, _sampled_reading
    orig = (_keychain_lookup, _credentials_file_lookup, _fallback_token,
            _live_usage_pct, _cache_read, _sampled_reading)
    err = sys.stderr
    failures = []
    try:
        def _mock_lookup(service):
            return None, None, f"{service}: empty accessToken (stale /login)"
        def _mock_credentials():
            return None, None, "no credentials file"
        def _mock_fallback():
            return "sk-ant-oat01-test-token-not-a-real-secret"
        _keychain_lookup = _mock_lookup
        _credentials_file_lookup = _mock_credentials
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
        _sampled_reading = lambda _group: None
        got = gate(50)
        if got != "spend":
            failures.append(
                "gate() with blank keychain + fallback token + no cache: "
                f"got {got!r}, want 'spend'")
    finally:
        (_keychain_lookup, _credentials_file_lookup, _fallback_token,
         _live_usage_pct, _cache_read, _sampled_reading) = orig
        sys.stderr = err
    for f in failures:
        print(f"SELF-TEST FAILED — {f}", file=sys.stderr)
    return 1 if failures else 0


def credentials_file_self_test():
    """Prove a host with no keychain still reaches its own credential store.

    `security` does not exist off macOS, and the lookup used to raise
    FileNotFoundError out of the loop over keychain_services() — so every
    later credential source was skipped and a machine holding a live token
    reported that it could not read the quota. The token here must come back
    with its real expiry and fallback=False: it is a full credential, not a
    setup token, and the caller is entitled to a percentage from it.
    """
    global _keychain_lookup
    orig = _keychain_lookup
    tmp = tempfile.mkdtemp()
    prev = os.environ.get("CLAUDE_CONFIG_DIR")
    failures = []
    try:
        def _no_security(service):
            return None, None, f"{service}: no keychain on this platform"
        _keychain_lookup = _no_security
        os.environ["CLAUDE_CONFIG_DIR"] = tmp
        expires_ms = int((_now().timestamp() + 3600) * 1000)
        with open(os.path.join(tmp, ".credentials.json"), "w") as fh:
            json.dump({"claudeAiOauth": {
                "accessToken": "sk-ant-oat01-test-token-not-a-real-secret",
                "expiresAt": expires_ms}}, fh)

        token, expires, fallback = access_token()
        if not (token and expires is not None and not fallback):
            failures.append(
                "access_token() with no keychain and a credentials file: got "
                f"{(bool(token), expires, fallback)!r}, want (True, <a date>, False)")
    finally:
        _keychain_lookup = orig
        if prev is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = prev
        shutil.rmtree(tmp, ignore_errors=True)
    for f in failures:
        print(f"SELF-TEST FAILED — {f}", file=sys.stderr)
    return 1 if failures else 0


def retry_self_test():
    """Prove a throttled quota read is retried rather than treated as a verdict.

    A 429 says nothing about the quota, but the gate fails closed on a read it
    cannot make, so one throttled request used to cost a whole night of
    annotation. Both directions are pinned: a 429 that clears is invisible to
    the caller, and a 401 is still fatal on the first try — retrying an
    authentication failure would only spend the same wrong token again.
    """
    global access_token
    real_token, err = access_token, sys.stderr
    access_token = lambda: ("t", None, False)
    slept, calls = [], []

    def _http(code):
        return urllib.error.HTTPError(USAGE_URL, code, "no", {}, None)

    def run(codes):
        """Answer each request with the next code, or the payload when spent."""
        del calls[:], slept[:]

        def _urlopen(_req, timeout=None):
            calls.append(1)
            if len(calls) <= len(codes):
                raise _http(codes[len(calls) - 1])
            return io.BytesIO(b'{"limits": [{"group": "weekly", '
                              b'"percent": 3}]}')
        real_open, real_sleep = urllib.request.urlopen, time.sleep
        urllib.request.urlopen = _urlopen
        time.sleep = slept.append
        try:
            return _payload()[0], None
        except urllib.error.HTTPError as exc:
            return None, exc
        finally:
            urllib.request.urlopen, time.sleep = real_open, real_sleep

    failures = []
    try:
        sys.stderr = io.StringIO()
        data, exc = run([429])
        if exc or not data or len(calls) != 2 or not slept:
            failures.append("a 429 that clears should be retried and the "
                            f"answer returned, got {exc or data} in "
                            f"{len(calls)} call(s)")
        data, exc = run([429] * 9)
        if not exc or exc.code != 429:
            failures.append(f"a 429 that never clears should surface, got {data}")
        if len(calls) != len(RETRY_BACKOFF_SECONDS) + 1:
            failures.append(f"retries should be bounded, made {len(calls)} calls")
        data, exc = run([401])
        if not exc or exc.code != 401 or len(calls) != 1:
            failures.append("a 401 is a verdict, not a throttle; it should be "
                            f"raised on the first call, made {len(calls)}")
    finally:
        access_token, sys.stderr = real_token, err
    for f in failures:
        print(f"SELF-TEST FAILED — {f}", file=sys.stderr)
    return 1 if failures else 0


def sampler_self_test():
    """Prove an unreadable API still gets an answer out of the sampler's file.

    On 2026-09-13 a 429 on both retries left the gate holding a 22-hour-old
    cached reading whose window had since reset, so it returned "unknown" and
    the night's annotation was skipped — while a reading taken forty seconds
    earlier sat in /data/usage-history.csv, stamped with the window it belonged
    to. The four cases pin that the file is read, parsed, and subject to exactly
    the same rules as the cache: fresh enough is a number, too old is only a
    floor, a window that has turned over is neither, and whichever source is
    newer wins.
    """
    global _live_usage_pct, _live_resets_at, _cache_read, SAMPLE_CSV_PATH
    live, read, path, err = (_live_usage_pct, _cache_read, SAMPLE_CSV_PATH,
                             sys.stderr)
    resets = _live_resets_at
    now, hours = _now(), datetime.timedelta(hours=1)
    tmp = tempfile.mkdtemp()
    cases = [
        # label, sampled (%, age, reset in), cached (%, age, reset in), verdict
        ("a fresh sample is read where the cache has gone stale",
         (70.0, 0.02 * hours, 96 * hours), (20.0, 22 * hours, -1 * hours),
         "skip"),
        ("a fresh sample under the limit is a reading, not a floor",
         (20.0, 0.02 * hours, 96 * hours), (75.0, 22 * hours, -1 * hours),
         "spend"),
        ("a sample from a window that has since reset is not a floor either",
         (70.0, 8 * hours, -1 * hours), None, "unknown"),
        ("the newer of the two sources decides",
         (20.0, 5 * hours, 96 * hours), (75.0, 1 * hours, 96 * hours), "skip"),
    ]
    failures = []
    try:
        def unreachable(_group):
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        _live_usage_pct = unreachable
        sys.stderr = io.StringIO()
        for i, (label, sampled, cached, want) in enumerate(cases):
            pct, age, until = sampled
            SAMPLE_CSV_PATH = os.path.join(tmp, f"usage-{i}.csv")
            with open(SAMPLE_CSV_PATH, "w") as fh:
                # A five-hour row first, so the kind column has to be honoured
                # rather than the last line taken on trust.
                fh.write(f"{int((now - age).timestamp())},five_hour,99.0,"
                         f"{int((now + until).timestamp())}\n")
                fh.write(f"{int((now - age).timestamp())},seven_day,{pct},"
                         f"{int((now + until).timestamp())}\n")
            if cached:
                c_pct, c_age, c_until = cached
                _cache_read = lambda p=c_pct, a=c_age, u=c_until: {
                    "weekly.percent": {"value": p, "at": (now - a).isoformat()},
                    "weekly.resets_at": {"value": (now + u).isoformat(),
                                         "at": (now - a).isoformat()}}
            else:
                _cache_read = lambda: {}
            got = gate(50)
            if got != want:
                failures.append(f"{label}: got {got!r}, want {want!r}")

        # And the reset stamp is chosen by when the STAMP was read, not by when
        # the percentage beside it was. The cache writes the two at different
        # moments, so a minute-old percentage next to a dead stamp from the
        # previous window used to drag that stamp in ahead of a fresh sampled
        # one, and resets_in_hours() answered with a rolled-forward guess while
        # holding the real answer.
        _live_resets_at = unreachable
        SAMPLE_CSV_PATH = os.path.join(tmp, "stamp.csv")
        with open(SAMPLE_CSV_PATH, "w") as fh:
            fh.write(f"{int((now - 5 * hours / 60).timestamp())},seven_day,20.0,"
                     f"{int((now + 96 * hours).timestamp())}\n")
        _cache_read = lambda: {
            "weekly.percent": {"value": 20.0, "at": now.isoformat()},
            "weekly.resets_at": {"value": (now - 1 * hours).isoformat(),
                                 "at": (now - 22 * hours).isoformat()}}
        try:
            hours_left, derived = resets_in_hours()
            got = (round(hours_left), derived)
        except READ_ERRORS:
            got = None
        if got != (96, False):
            failures.append("a sampled reset stamp beats a stale cached one "
                            f"even under a fresher cached percentage: got {got!r}"
                            ", want (96, False)")
    finally:
        _live_usage_pct, _cache_read, SAMPLE_CSV_PATH = live, read, path
        _live_resets_at = resets
        sys.stderr = err
        shutil.rmtree(tmp, ignore_errors=True)
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
        ok = (self_test() or reset_self_test() or spend_by_self_test()
              or fallback_self_test() or credentials_file_self_test()
              or retry_self_test() or sampler_self_test())
        print("gate self-test: all cases pass" if ok == 0
              else "gate self-test FAILED")
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
