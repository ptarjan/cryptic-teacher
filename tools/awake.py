#!/usr/bin/env python3
"""When the owner is asleep, learned from the times of his own messages.

The burn must not fill the weekly meter while he sleeps: at 100% every room is
locked out until he resets it, and he can reset only when awake (owner 11-01:
"try to know when I'm awake so you don't lock me out when I'm sleeping").

The source is the bridge's message store, STORE/*.jsonl: one row per post in
every room, Discord and Telegram ones included, with `from` "user" for his own.
The bridge's own notices
filed as his ("\U0001f511 The owner gave the secrets deputy ...") are skipped. Over
LEARN_SPAN_S the profile is, for each SLOTS-th of the day (Pacific), the share
of the days he wrote at all on which he wrote in it; his night is the longest
run of slots under SLEEP_SHARE of the median slot's share, widened by BED_PAD_H
and WAKE_PAD_H, the same every day (a weekday has four nights a month: too
few to tell one from another). Under MIN_DAYS days, or no store (CI), it is
FIXED, 23:00-07:00. The profile is cached in CACHE under the burn's
checkout, rebuilt when REFRESH_S old.

A message within AWAKE_RECENT_S says he is awake now: the night he is up in
starts that long after his last message instead (last_message reads only the
tails of the files written since).

    tools/awake.py            # the profile and whether he is awake now
    tools/awake.py --self-test
"""
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    PACIFIC = ZoneInfo("America/Los_Angeles")
except (ImportError, ZoneInfoNotFoundError):  # no tz database: a fixed PST
    PACIFIC = dt.timezone(dt.timedelta(hours=-8))

STORE = Path(os.environ.get("CT_WEB_STORE") or "/data/web")
CACHE = ".prereset.awake"
LEARN_SPAN_S = 30 * 86400
REFRESH_S = 3600
AWAKE_RECENT_S = 75 * 60
TAIL_BYTES = 1 << 18
SLOTS = 48
SLEEP_SHARE = 0.75
MIN_DAYS = 10
BED_PAD_H = WAKE_PAD_H = 0.5
# Hours past the evening's midnight: 23:00 to the next day's 07:00.
FIXED = (23.0, 31.0)
NOTICE = "\U0001f511"


def _his(row):
    """The epoch of a row that is one of the owner's own messages, else None."""
    if not isinstance(row, dict) or row.get("from") != "user":
        return None
    if str(row.get("text") or "").startswith(NOTICE):
        return None
    try:
        return float(row["at"])
    except (KeyError, TypeError, ValueError):
        return None


def _rows(data):
    for line in data.splitlines():
        if b'"user"' not in line:
            continue
        try:
            yield json.loads(line)
        except ValueError:
            continue


def user_times(store, since):
    """Sorted epochs of the owner's messages in `store` at or after `since`."""
    out = []
    for path in Path(store).glob("*.jsonl"):
        try:
            if path.stat().st_mtime < since:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        out += [t for t in map(_his, _rows(data)) if t is not None and t >= since]
    return sorted(out)


def last_message(store, now, recent=AWAKE_RECENT_S):
    """The epoch of the owner's newest message in the last `recent` seconds, else None."""
    best = None
    for path in Path(store).glob("*.jsonl"):
        try:
            if path.stat().st_mtime < now - recent:
                continue
            with path.open("rb") as f:
                f.seek(max(0, f.seek(0, 2) - TAIL_BYTES))
                data = f.read()
        except OSError:
            continue
        for t in map(_his, _rows(data)):
            if t is not None and now - recent <= t <= now and (best is None or t > best):
                best = t
    return best


def _midnight(day, tz=PACIFIC):
    return dt.datetime.combine(day, dt.time(0), tz)


def shares(times, tz=PACIFIC):
    """(days with a message, [share of those days with one in each SLOTS-th
    of the day])."""
    days, seen = set(), [set() for _ in range(SLOTS)]
    for t in times:
        local = dt.datetime.fromtimestamp(t, tz)
        days.add(local.date())
        seen[(local.hour * 60 + local.minute) * SLOTS // 1440].add(local.date())
    return len(days), [len(s) / max(1, len(days)) for s in seen]


def profile(times, tz=PACIFIC):
    """{"days", "shares", "span": (bed, wake)} learned from `times`, in hours
    past the evening's midnight; span None on under MIN_DAYS days or no night."""
    n, share = shares(times, tz)
    out = {"days": n, "shares": [round(x, 3) for x in share], "span": None}
    if n < MIN_DAYS:
        return out
    ranked = sorted(share)
    cut = SLEEP_SHARE * (ranked[SLOTS // 2 - 1] + ranked[SLOTS // 2]) / 2
    low = [x < cut for x in share]
    if all(low) or not any(low):
        return out
    best = (0, 0)  # (length, first slot) of the longest circular run of quiet slots
    for first in range(SLOTS):
        if low[first] and not low[first - 1]:
            length = next(k for k in range(1, SLOTS + 1) if not low[(first + k) % SLOTS])
            best = max(best, (length, first))
    length, first = best
    bed = first * 24 / SLOTS - BED_PAD_H
    bed += 24 if bed < 12 else 0
    wake = (first + length) * 24 / SLOTS + WAKE_PAD_H
    while wake <= bed:
        wake += 24
    out["span"] = (round(bed, 3), round(wake, 3))
    return out


def load(home, now=None, store=None):
    """{"span", "days", "shares", "at", "last"} for the pacer: the cached profile
    (rebuilt when REFRESH_S old) and his newest message."""
    now = time.time() if now is None else now
    store = STORE if store is None else Path(store)
    path = Path(home) / CACHE
    cached = None
    try:
        cached = json.loads(path.read_text())
        if not 0 <= now - float(cached["at"]) < REFRESH_S:
            cached = None
    except (OSError, ValueError, KeyError, TypeError):
        cached = None
    if cached is None:
        cached = dict(profile(user_times(store, now - LEARN_SPAN_S)), at=now)
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(cached) + "\n")
            tmp.replace(path)
        except OSError as exc:
            print(f"awake: {path} not written: {exc}", file=sys.stderr)
    return dict(cached, last=last_message(store, now))


def span(sleep):
    """(bed, wake) hours past the evening's midnight: learned, else FIXED."""
    got = (sleep or {}).get("span")
    return tuple(got) if got and len(got) == 2 else FIXED


def next_sleep(epoch, sleep=None, tz=PACIFIC):
    """(start, end) epochs of the night `epoch` falls in, else the next one.
    A night he messaged in within AWAKE_RECENT_S starts that long after it."""
    bed, wake = span(sleep)
    last = (sleep or {}).get("last")
    day = dt.datetime.fromtimestamp(epoch, tz).date() - dt.timedelta(days=1)
    for _ in range(9):
        base = _midnight(day, tz)
        start = (base + dt.timedelta(hours=bed)).timestamp()
        end = (base + dt.timedelta(hours=wake)).timestamp()
        if last is not None and start < last + AWAKE_RECENT_S:
            start = max(start, last + AWAKE_RECENT_S)
        if end > epoch and start < end:
            return start, end
        day += dt.timedelta(days=1)
    return epoch, epoch


def asleep(epoch, sleep=None):
    """True when the owner is predicted asleep at `epoch`."""
    start, end = next_sleep(epoch, sleep)
    return start <= epoch < end


def clock(hours):
    h = hours % 24
    return f"{int(h):02d}:{round(h % 1 * 60) % 60:02d}"


def describe(sleep, now=None, nights=3):
    """Lines saying what the profile is, the next `nights` nights, and
    whether he is awake now."""
    now = time.time() if now is None else now
    sleep = sleep or {}
    bed, wake = span(sleep)
    if sleep.get("span"):
        head = (f"awake model: the owner's messages on {sleep['days']} days in {STORE}: "
                f"asleep {clock(bed)}-{clock(wake)} Pacific")
    else:
        head = (f"awake model: {sleep.get('days', 0)} days of the owner's messages, under "
                f"{MIN_DAYS}: the fixed {clock(bed)}-{clock(wake)} Pacific")
    share = sleep.get("shares") or []
    bars = "".join(" .:-=+*#%@"[min(9, int(x * 10))] for x in share)
    lines = [head] + ([f"  share of days he writes, 00:00..23:30 by 30 min: |{bars}|"] if bars else [])
    t, out = now, []
    for _ in range(nights):
        start, end = next_sleep(t, sleep)
        out.append(f"{dt.datetime.fromtimestamp(start, PACIFIC):%a %H:%M}-"
                   f"{dt.datetime.fromtimestamp(end, PACIFIC):%a %H:%M}")
        t = end
    lines.append("  nights ahead: " + ", ".join(out))
    last = sleep.get("last")
    lines.append(f"  awake now: his last message {(now - last) / 60:.0f} min ago" if last
                 else f"  no message from him in {AWAKE_RECENT_S // 60} min")
    return lines


def _utc(*when):
    return dt.datetime(*when, tzinfo=dt.UTC).timestamp()


def self_test():
    import tempfile
    bad = n = 0
    def check(what, got, want):
        nonlocal bad, n
        n += 1
        if got != want:
            print(f"FAIL {what} = {got} (want {want})", file=sys.stderr)
            bad += 1
    # Three synthetic weeks of November (PST, UTC-8): messages every 30 min
    # from 06:00 to 22:30, but Fridays to 01:00 and Saturdays from 09:00.
    times = []
    for d in range(2, 24):
        base = dt.datetime(2026, 11, d, tzinfo=PACIFIC).timestamp()
        day = dt.date(2026, 11, d).weekday()
        times += [base + h * 1800 for h in range(18 if day == 5 else 12, 51 if day == 4 else 46)]
    prof = profile(times)
    check("days found", prof["days"], 22)
    # quiet 23:00-06:00 (one late Friday in seven is still quiet), padded 30 min
    check("learned span", prof["span"], (22.5, 30.5))
    check("thin data: no span", profile(times[:300])["span"], None)
    sleep = {"span": prof["span"], "last": None}
    mon = dt.datetime(2026, 11, 9, tzinfo=PACIFIC).timestamp()
    for hour, want in [(22.4, False), (22.5, True), (26.0, True), (30.49, True), (30.5, False)]:
        check(f"asleep at Mon +{hour}h", asleep(mon + hour * 3600, sleep), want)
    check("next_sleep from Mon noon", next_sleep(mon + 12 * 3600, sleep),
          (mon + 22.5 * 3600, mon + 30.5 * 3600))
    # awake now: a message at 23:00 pushes the night's start 75 min on
    up = dict(sleep, last=mon + 23 * 3600)
    check("asleep at 23:30 having written at 23:00", asleep(mon + 23.5 * 3600, up), False)
    check("asleep at 00:20", asleep(mon + 24.33 * 3600, up), True)
    check("fallback is 23:00-07:00", next_sleep(mon + 12 * 3600, None),
          (mon + 23 * 3600, mon + 31 * 3600))
    with tempfile.TemporaryDirectory() as tmp:
        store, home = Path(tmp) / "web", Path(tmp) / "home"
        store.mkdir()
        home.mkdir()
        rows = [{"from": "user", "at": t, "text": "hi"} for t in times]
        rows += [{"from": "bot", "at": mon + 26 * 3600, "text": "a bot at 02:00"},
                 {"from": "user", "at": mon + 27 * 3600, "text": NOTICE + " The owner gave ..."}]
        (store / "web.room.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        now = times[-1] + 600
        os.utime(store / "web.room.jsonl", (now, now))
        got = load(home, now, store)
        check("load: span from the store", span(got), prof["span"])
        check("load: last message", got["last"], times[-1])
        check("load: cached", json.loads((home / CACHE).read_text())["days"], 22)
        check("load: awake gone after 75 min", load(home, now + AWAKE_RECENT_S, store)["last"], None)
        check("load: empty store", load(Path(tmp), now, Path(tmp) / "none")["span"], None)
        check("describe names the nights", len(describe(got, now)), 4)
    print(f"awake self-test FAILED: {bad} of {n}" if bad else f"awake self-test: {n} cases pass")
    return 1 if bad else 0


def main():
    if "--self-test" in sys.argv:
        return self_test()
    print("\n".join(describe(load(Path(os.environ.get("CT_MAIN_CHECKOUT") or "."), store=STORE))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
