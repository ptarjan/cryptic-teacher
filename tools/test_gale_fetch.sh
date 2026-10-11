#!/bin/bash
# Does tools/gale_fetch.py keep a hand's pace (a jittered gap, never more
# than WINDOW_MAX in WINDOW seconds, a rest after SESSION_CAP), stop at the
# first login page, captcha, HTML or short PDF and after MAX_ERRORS errors in
# a row (but ride out one), skip documents already got, and give up after
# IDLE_MAX waits for links?
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
import bisect, datetime, random, sys, urllib.error
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


def pacer(clock, seed=1):
    return gf.Pacer(clock=clock, sleep=clock.sleep, rand=random.Random(seed))


PDF = b"%PDF-1.4 " + b"x" * gf.MIN_PDF


def rows(n):
    day = datetime.date(1982, 12, 1)
    return [(day + datetime.timedelta(days=i), {"doc": f"CS{400000000 + i}", "title": f"No {i}", "page": 20,
                                                 "records": ["R1"]}) for i in range(n)]


def text_of(body):
    return " ".join(e["doc"] for _, e in rows(2000))  # every citation names its doc


def harness(n_rows=2000, bodies=None, got=()):
    """run() over `n_rows` rows on a fake clock; `bodies(i)` is the i-th
    fetch's answer (bytes, or an exception to raise)."""
    clock, starts, stored = Clock(), [], []
    all_rows = rows(n_rows)
    have = set(got)

    def fetch(url):
        starts.append(clock())
        b = (bodies or (lambda i: PDF))(len(starts) - 1)
        clock.t += 2.0  # a download takes a while
        if isinstance(b, Exception):
            raise b
        return b

    def store(body, name):
        stored.append(name)
        have.add(name[5:-4])

    kw = dict(pacer=pacer(clock), fetch=fetch, store=store, got_of=lambda: set(have),
              plan_of=lambda g: [(d, e) for d, e in all_rows if e["doc"] not in g], log=lambda *a: None,
              fetched=fetched, text_of=text_of)
    return clock, starts, stored, kw


# 1. Pace: gaps of at least GAP[0], never more than WINDOW_MAX starts in any
#    WINDOW, a REST after every SESSION_CAP downloads.
clock, starts, stored, kw = harness()
n, why = gf.run(limit=900, **kw)
assert n == 900 and len(stored) == 900, (n, len(stored))
gaps = [b - a for a, b in zip(starts, starts[1:])]
assert min(gaps) >= gf.GAP[0], min(gaps)
most = max(bisect.bisect_left(starts, t + gf.WINDOW) - i for i, t in enumerate(starts))
assert most <= gf.WINDOW_MAX, most
rests = [g for g in gaps if g >= gf.REST[0]]
assert len(rests) == 900 // gf.SESSION_CAP - (900 % gf.SESSION_CAP == 0), (len(rests), gf.SESSION_CAP)
per3 = len(starts) / ((starts[-1] - starts[0] - sum(rests)) / 180)
assert 5 <= per3 <= gf.WINDOW_MAX, per3
assert len(set(round(g, 3) for g in gaps)) > 100, "the gap is jittered"
assert len(set(stored)) == 900, "no document twice"
print(f"pace: {per3:.1f} downloads per 3 min, max {most} in any {gf.WINDOW:.0f}s, {len(rests)} rests")

# 2. Stops at the first page that is not the PDF, having stored only before it.
for bad, said in ((b"<!DOCTYPE html><html><form>Password</form></html>", "login page"),
                  (b"<html>Please complete the CAPTCHA</html>", "captcha"),
                  (b"<html><body>Service unavailable</body></html>", "HTML page"),
                  (b"%PDF-1.4 tiny", "only"),
                  (b'{"error": "nope"}', "not a PDF")):
    clock, starts, stored, kw = harness(bodies=lambda i, bad=bad: bad if i == 2 else PDF)
    try:
        gf.run(limit=10, **kw)
        raise AssertionError(f"ran on past {said}")
    except gf.Stop as e:
        assert said in str(e), (said, str(e))
    assert len(stored) == 2 and len(starts) == 3, (said, stored, starts)
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

# 4. Resumable: a document already got (inbox, set aside, Arrived.js, the
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

# 6. A row the sync has not looked up yet is looked up first; one Gale has
#    no crossword for is passed over, never fetched.
clock, starts, stored, kw = harness(n_rows=3)
asked = []
kw["plan_of"] = lambda g: [(d, None) for d, e in rows(3) if e["doc"] not in g]
kw["lookup_of"] = lambda day: asked.append(day) or (
    {"why": "no crossword in the issue's contents"} if day == rows(3)[1][0]
    else dict(next(e for d, e in rows(3) if d == day)))
n, _ = gf.run(limit=2, **kw)
assert stored == [f"GALE_{rows(3)[i][1]['doc']}.pdf" for i in (0, 2)], stored
assert len(starts) == 2, "a row with no crossword costs no download"

# 7. The real store writes a document to the log.
assert set(__import__("json").loads(fetched.read_text())) >= set(first[3:])
print("test_gale_fetch: ok")
PY
