#!/bin/bash
# Does tools/gale_fetch.py keep a hand's pace (a jittered gap, never more
# than WINDOW_MAX in WINDOW seconds, a rest after the learned session cap),
# record each refusal (login page, HTML, non-PDF) and how long until a
# download works again, learn its cap from them, stop at a captcha or short
# PDF, after every probe fails, and after MAX_ERRORS errors in a row (but
# ride out one), skip documents already got, and give up after IDLE_MAX
# waits?
#
#     bash tools/test_gale_fetch.sh
#
# Gale, the Mac and the clock are stand-ins: nothing is asked of Gale or the
# Mac, nobody is woken, nothing is written outside a temp dir.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp" <<'PY'
import bisect, datetime, json, random, sys, urllib.error
from pathlib import Path
import gale_fetch as gf

tmp = Path(sys.argv[1])
fetched = tmp / "fetched.json"


class Clock:
    def __init__(self):
        self.t, self.slept = 1_000_000.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        assert s >= 0, s
        self.slept.append(s)
        self.t += s


_n = [0]


def limits_file(refusals=(), spans=()):
    _n[0] += 1
    path = tmp / f"limits{_n[0]}.json"
    path.write_text(json.dumps({"refusals": [{"in_window": r} for r in refusals],
                                "recoveries": [{"since_window_start": s} for s in spans]}))
    return path


def pacer(clock, seed=1):
    return gf.Pacer(clock=clock, sleep=clock.sleep, rand=random.Random(seed))


PDF = b"%PDF-1.4 " + b"x" * gf.MIN_PDF


def rows(n):
    day = datetime.date(1982, 12, 1)
    return [(day + datetime.timedelta(days=i), {"doc": f"CS{400000000 + i}", "title": f"No {i}", "page": 20,
                                                 "records": ["R1"]}) for i in range(n)]


def text_of(body):
    return " ".join(e["doc"] for _, e in rows(2000))  # every citation names its doc


def harness(n_rows=2000, bodies=None, got=(), refusals=()):
    """run() over `n_rows` rows on a fake clock; `bodies(i)` is the i-th
    fetch's answer (bytes, or an exception to raise); `refusals` the
    in_window of each refusal already recorded."""
    clock, starts, stored = Clock(), [], []
    limits = limits_file(refusals)
    fetched = tmp / f"fetched{_n[0]}.json"
    all_rows = rows(n_rows)
    have = set(got)

    def fetch(url):
        starts.append(clock())
        b = (bodies or (lambda i: PDF))(len(starts) - 1)
        clock.t += 2.0  # a download takes a while
        if isinstance(b, Exception):
            raise b
        return b

    def store(body, day, doc, e):
        stored.append(f"GALE_{doc}.pdf")
        have.add(doc)

    told.clear()
    kw = dict(pacer=pacer(clock), fetch=fetch, store=store, got_of=lambda: set(have),
              plan_of=lambda g: [(d, e) for d, e in all_rows if e["doc"] not in g], log=lambda *a: None,
              fetched=fetched, text_of=text_of, limits=limits, tell=told.append)
    return clock, starts, stored, kw


told = []


# 1. Pace: gaps of at least GAP[0], never more than WINDOW_MAX starts in any
#    WINDOW; at the window's cap (CAP_SEED, or 90% of the fewest downloads a
#    refusal came after) it waits out the window (WINDOW_SEED, or the
#    shortest a recovery showed), then counts afresh.
assert gf.learned(limits_file([480, 520], [5 * 3600.0])) == (432, 5 * 3600.0)
assert gf.learned(limits_file()) == (None, gf.WINDOW_SEED)
clock, starts, stored, kw = harness(refusals=[400])
cap = gf.learned(kw["limits"])[0]
n, why = gf.run(limit=900, **kw)
assert n == 900 and len(stored) == 900, (n, len(stored))
gaps = [b - a for a, b in zip(starts, starts[1:])]
assert min(gaps) >= gf.GAP[0], min(gaps)
most = max(bisect.bisect_left(starts, t + gf.WINDOW) - i for i, t in enumerate(starts))
assert most <= gf.WINDOW_MAX, most
rests = [g for g in gaps if g >= 3600]
assert cap == 360 and len(rests) == 2 and all(r <= gf.WINDOW_SEED for r in rests), (len(rests), rests, cap)
per3 = len(starts) / ((starts[-1] - starts[0] - sum(rests)) / 180)
assert 5 <= per3 <= gf.WINDOW_MAX, per3
assert len(set(round(g, 3) for g in gaps)) > 100, "the gap is jittered"
assert len(set(stored)) == 900, "no document twice"
print(f"pace: {per3:.1f} downloads per 3 min, max {most} in any {gf.WINDOW:.0f}s, {len(rests)} rests")
# Downloads made elsewhere count: with a cap of 450 (a refusal at 500), a
# window seeded with the browser's 440 lets 10 more through, then waits out
# the window.
clock, starts, stored, kw = harness(refusals=[500])
gf.new_window(kw["limits"], clock() - 3600, 440)
gf.run(limit=12, **kw)
gaps = [b - a for a, b in zip(starts, starts[1:])]
assert max(range(len(gaps)), key=gaps.__getitem__) == 9 and max(gaps) >= gf.WINDOW_SEED - 3600 - 600, gaps
assert json.loads(kw["limits"].read_text())["window"]["before"] == 0, "a new window after the wait"
# With no cap (no refusal yet) nothing waits and the window is never ended,
# however long: a refusal then records the whole count.
clock, starts, stored, kw = harness()
gf.new_window(kw["limits"], clock() - 10 * 3600, 440)
gf.run(limit=30, **kw)
assert max(b - a for a, b in zip(starts, starts[1:])) < 3600
assert gf.in_window(kw["limits"], kw["fetched"], clock())[1] == 470

# 2. Stops at a captcha or a short PDF, having stored only before it.
for bad, said in ((b"<html>Please complete the CAPTCHA</html>", "captcha"),
                  (b"%PDF-1.4 tiny", "only")):
    clock, starts, stored, kw = harness(bodies=lambda i, bad=bad: bad if i == 2 else PDF)
    try:
        gf.run(limit=10, **kw)
        raise AssertionError(f"ran on past {said}")
    except gf.Stop as e:
        assert said in str(e), (said, str(e))
    assert len(stored) == 2 and len(starts) == 3, (said, stored, starts)
    assert not told, told

# 2b. A login page, other HTML or a non-PDF that a fresh session gets past
#     at once is a logout: only noted, nobody told, no wait.
for bad, said in ((b"<!DOCTYPE html><html><form>Password</form></html>", "login page"),
                  (b"<html><body>Service unavailable</body></html>", "HTML page"),
                  (b'{"error": "nope"}', "not a PDF")):
    clock, starts, stored, kw = harness(bodies=lambda i, bad=bad: bad if i == 2 else PDF)
    n, _ = gf.run(limit=10, **kw)
    kept = json.loads(kw["limits"].read_text())
    assert n == 10 and not kept["refusals"] and said in kept["relogins"][0]["why"] and not told, (said, kept, told)
    assert gf.PROBE_EVERY not in clock.slept
# Refused in a fresh session too: a refusal, recorded with the window's
# count, the room told; probed every PROBE_EVERY, each refused probe's time
# kept, until one works; that recovery starts a new window.
clock, starts, stored, kw = harness(bodies=lambda i: b"<html>Too many requests</html>" if 3 <= i <= 6 else PDF)
n, _ = gf.run(limit=10, **kw)
kept = json.loads(kw["limits"].read_text())
r, rec = kept["refusals"][0], kept["recoveries"][0]
assert n == 10 and r["in_window"] == 3 and r["head"] and len(told) == 2, (n, r, told)
assert r["mean_gap_last_20"] >= gf.GAP[0] and r["last_10min"] == 3, r
assert rec["probes"] == 3 and rec["waited"] >= 3 * gf.PROBE_EVERY and rec["last_refused_at"] < rec["ok_at"], rec
assert clock.slept.count(gf.PROBE_EVERY) == 3 and kept["window"]["start"] == rec["ok_at"], kept
assert gf.learned(kw["limits"]) == (gf.CAP_FLOOR, rec["since_window_start"])
# Refused through every probe: it stops, the refusal kept, no recovery.
clock, starts, stored, kw = harness(bodies=lambda i: b"<html>Too many requests</html>" if i >= 3 else PDF)
try:
    gf.run(limit=10, **kw)
    raise AssertionError("ran on past a refusal no probe got past")
except gf.Stop as e:
    assert "still refused" in str(e), e
kept = json.loads(kw["limits"].read_text())
assert len(kept["refusals"]) == 1 and not kept["recoveries"] and len(starts) == 5 + gf.PROBE_MAX, (kept, starts)
# HTTP 429 from Gale, in a fresh session too, is a refusal.
clock, starts, stored, kw = harness(bodies=lambda i: gf.Stop("Gale answered HTTP 429", refused=True, status=429,
                                                             head=b"slow down") if i in (1, 2) else PDF)
n, _ = gf.run(limit=3, **kw)
assert n == 3 and json.loads(kw["limits"].read_text())["refusals"][0]["status"] == 429
assert gf.verdict(PDF, "CS999", text_of=lambda b: "link.gale.com/apps/doc/CS111/TTDA") is not None, "wrong doc"
assert gf.verdict(PDF, "CS111", text_of=lambda b: "link.gale.com/apps/doc/CS111/TTDA") is None

# 3. One error is ridden out (after a backoff); MAX_ERRORS in a row stop it.
clock, starts, stored, kw = harness(bodies=lambda i: urllib.error.URLError("reset") if i == 1 else PDF)
n, _ = gf.run(limit=5, **kw)
assert n == 5 and len(starts) == 6 and gf.BACKOFF in clock.slept, (n, starts, clock.slept)
clock, starts, stored, kw = harness(bodies=lambda i: urllib.error.URLError("down") if i >= 1 else PDF)
try:
    gf.run(limit=10, **kw)
    raise AssertionError("ran on past repeated errors")
except gf.Stop as e:
    assert f"{gf.MAX_ERRORS} errors in a row" in str(e), e
assert len(starts) == 1 + gf.MAX_ERRORS and len(stored) == 1, (starts, stored)

# 4. Resumable: a document already got (inbox, set aside, Fetched, the
#    log) is never fetched again.
first = [e["doc"] for _, e in rows(5)]
clock, starts, stored, kw = harness(n_rows=5, got=first[:3])
kw["plan_of"] = lambda g: rows(5)  # even if the plan still lists them
n, _ = gf.run(limit=2, **kw)
assert stored == [f"GALE_{d}.pdf" for d in first[3:]], stored

# 5. No linked row: IDLE_MAX bounded waits, then it ends.
clock, starts, stored, kw = harness(n_rows=0)
n, why = gf.run(**kw)
assert n == 0 and clock.slept == [gf.IDLE] * gf.IDLE_MAX and "waits" in why, (n, clock.slept, why)

# 6. A row not looked up yet is looked up first; one Gale has no crossword
#    for is passed over, never fetched.
clock, starts, stored, kw = harness(n_rows=3)
asked = []
kw["plan_of"] = lambda g: [(d, None) for d, e in rows(3) if e["doc"] not in g]
kw["lookup_of"] = lambda day: asked.append(day) or (
    {"why": "no crossword in the issue's contents"} if day == rows(3)[1][0]
    else dict(next(e for d, e in rows(3) if d == day)))
n, _ = gf.run(limit=2, **kw)
assert stored == [f"GALE_{rows(3)[i][1]['doc']}.pdf" for i in (0, 2)], stored
assert len(starts) == 2, "a row with no crossword costs no download"

# 7. Each download is written to the log.
assert set(json.loads(kw["fetched"].read_text())) == {rows(3)[i][1]["doc"] for i in (0, 2)}
print("test_gale_fetch: ok")
PY
