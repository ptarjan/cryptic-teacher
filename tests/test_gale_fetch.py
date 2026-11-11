#!/usr/bin/env python3
# Does tools/gale_fetch.py keep a hand's pace (a jittered gap, never more
# than WINDOW_MAX in WINDOW seconds, a rest after the learned session cap),
# record each refusal (login page, HTML, non-PDF) and how long until a
# download works again, learn its cap from them, stop at a captcha or short
# PDF, after every probe fails, and after MAX_ERRORS errors in a row (but
# ride out one), skip documents already got, and give up after IDLE_MAX
# waits? Does it plan the Listener after the Times and before the other
# papers, and fetch a Listener report from its own issue?
#
#     python3 tests/test_gale_fetch.py
#
# Gale, the Mac and the clock are stand-ins: nothing is asked of Gale or the
# Mac, nobody is woken, nothing is written outside a temp dir.
import _path  # puts tools/ on sys.path
import os
import sys
import atexit
import shutil
import tempfile
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
tmp = tempfile.mkdtemp()
atexit.register(shutil.rmtree, tmp, True)
sys.argv[1:] = [tmp]

import bisect, datetime, json, random, sys, urllib.error, urllib.parse
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

    def store(body, prod, day, doc, e):
        stored.append(f"GALE_{doc}.pdf")
        have.add(doc)

    told.clear()
    kw = dict(pacer=pacer(clock), fetch=fetch, store=store, got_of=lambda: set(have),
              plan_of=lambda g: [("TTDA", d, e) for d, e in all_rows if e["doc"] not in g], log=lambda *a: None,
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
# A reload asked (tools/hot_reload.py) ends the run between two downloads, never in one.
clock, starts, stored, kw = harness()
try:
    gf.run(limit=30, reload=lambda: len(stored) >= 4, **kw)
    raise AssertionError("the reload was not raised")
except gf.Reload:
    assert len(stored) == 4 == len(starts), (len(stored), len(starts))

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
assert gf.verdict(PDF, "CS111", text_of=lambda b: "\n\n\n") is None, "a scanned issue (blank first pages) is not a wrong doc"

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

# 3b. One document that always 500s is skipped (and recorded, so never offered
#     again); the next is fetched. 500s on different documents still stop.
def five(url):
    return urllib.error.HTTPError(url, 500, "boom", None, None)


bad = rows(3)[1][1]["doc"]
clock, starts, stored, kw = harness(n_rows=3)
inner = kw["fetch"]
kw["fetch"] = lambda url: (_ for _ in ()).throw(five(url)) if bad in url else inner(url)
kw["broken"] = tmp / f"broken{_n[0]}.json"
n, _ = gf.run(limit=2, **kw)
assert stored == [f"GALE_{d}.pdf" for d in (rows(3)[0][1]["doc"], rows(3)[2][1]["doc"])], stored
assert [b["doc"] for b in gf.load(kw["broken"])["docs"]] == [bad], gf.load(kw["broken"])
clock, starts, stored, kw = harness(n_rows=5, bodies=lambda i: five("u") if i >= 1 else PDF)
kw["broken"] = tmp / f"broken{_n[0]}b.json"
turn = [0]


def rotating(g):
    turn[0] += 1
    todo = [("TTDA", d, e) for d, e in rows(5) if e["doc"] not in g]
    return todo[turn[0] % 3:] + todo[:turn[0] % 3]


kw["plan_of"] = rotating
try:
    gf.run(limit=10, **kw)
    raise AssertionError("ran on past 500s on different documents")
except gf.Stop as e:
    assert f"{gf.MAX_ERRORS} errors in a row" in str(e), e

# 3c. A skip is provisional. (a) One document 5xx x3, then the next downloads:
#     it stays in broken. (b) A 5xx x3 and then B 5xx x3 with no download between
#     is Gale failing broadly: A is taken back out of broken, B not recorded, the
#     run probes (a 5xx probe is still refused) and carries on once one works.
a_doc, b_doc = rows(3)[0][1]["doc"], rows(3)[1][1]["doc"]
clock, starts, stored, kw = harness(n_rows=3, bodies=lambda i: five("u") if i < gf.MAX_ERRORS else PDF)
kw["broken"] = tmp / f"broken{_n[0]}c.json"
gf.run(limit=2, **kw)
assert [b["doc"] for b in gf.load(kw["broken"])["docs"]] == [a_doc], gf.load(kw["broken"])
assert not json.loads(kw["limits"].read_text()).get("refusals"), "one broken doc is not a refusal"
two = 2 * gf.MAX_ERRORS
clock, starts, stored, kw = harness(n_rows=3, bodies=lambda i: five("u") if i <= two else PDF)  # probe 1 (i == two) 5xx too
kw["broken"] = tmp / f"broken{_n[0]}d.json"
n, _ = gf.run(limit=2, **kw)
kept = json.loads(kw["limits"].read_text())
assert b_doc in " ".join(stored) and n == 2, (n, stored)
assert not gf.load(kw["broken"]).get("docs"), gf.load(kw["broken"])
assert len(kept["refusals"]) == 1 and kept["refusals"][0]["status"] == 500, kept
assert len(kept["recoveries"]) == 1 and kept["recoveries"][0]["probes"] == 2, kept
assert clock.slept.count(gf.PROBE_EVERY) == 2 and len(told) == 2, (clock.slept, told)

# 4. Resumable: a document already got (inbox, set aside, Fetched, the
#    log) is never fetched again.
first = [e["doc"] for _, e in rows(5)]
clock, starts, stored, kw = harness(n_rows=5, got=first[:3])
kw["plan_of"] = lambda g: [("TTDA", d, e) for d, e in rows(5)]  # even if the plan still lists them
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
kw["plan_of"] = lambda g: [("TTDA", d, None) for d, e in rows(3) if e["doc"] not in g]
kw["lookup_of"] = lambda prod, day: asked.append(day) or (
    {"why": "no crossword in the issue's contents"} if day == rows(3)[1][0]
    else dict(next(e for d, e in rows(3) if d == day)))
n, _ = gf.run(limit=2, **kw)
assert stored == [f"GALE_{rows(3)[i][1]['doc']}.pdf" for i in (0, 2)], stored
assert len(starts) == 2, "a row with no crossword costs no download"

# 6b. A lookup answered HTTP 5xx is a Gale outage: waited out (5, 10, 20 min, ...),
#     not counted among the MAX_ERRORS; only one outlasting OUTAGE_WAITS stops
#     it. A 4xx still stops after MAX_ERRORS.
def lookups(code, fail):
    clock, starts, stored, kw = harness(n_rows=3)
    seen = []
    kw["plan_of"] = lambda g: [("TTDA", d, None) for d, e in rows(3) if e["doc"] not in g]

    def look(prod, day):
        if (prod, day) == gf.CONTROL:  # the control lookup fails while Gale is down
            if len(seen) <= fail:
                raise urllib.error.HTTPError("u", code, f"HTTP {code}", None, None)
            return {"why": "Gale has no issue that day"}
        seen.append(day)
        if len(seen) <= fail:
            raise urllib.error.HTTPError("u", code, f"HTTP {code}", None, None)
        return dict(next(e for d, e in rows(3) if d == day))
    kw["lookup_of"] = look
    return clock, stored, kw


oclock, ostored, okw = lookups(504, 4)
n, _ = gf.run(limit=2, **okw)
assert n == 2 and oclock.slept[:4] == list(gf.OUTAGE_WAITS[:4]), (n, oclock.slept)
oclock, ostored, okw = lookups(504, 99)
try:
    gf.run(limit=2, **okw)
    raise AssertionError("ran on through an outage past OUTAGE_WAITS")
except gf.Stop as e:
    assert "Gale answered 5xx" in str(e), e
assert [x for x in oclock.slept if x in gf.OUTAGE_WAITS] == list(gf.OUTAGE_WAITS)
oclock, ostored, okw = lookups(404, 99)
try:
    gf.run(limit=2, **okw)
    raise AssertionError("ran on past repeated 4xx")
except gf.Stop as e:
    assert f"{gf.MAX_ERRORS} errors in a row" in str(e), e

# 6c. A 5xx on one day while the control lookup answers is that day's alone:
#     set aside (kept as a "why" entry), no wait, and the next row goes on.
clock, starts, stored, kw = harness(n_rows=3)
kept = {}
bad = rows(3)[0][0]
kw["plan_of"] = lambda g: [("TTDA", d, kept.get(gf.key("TTDA", d))) for d, e in rows(3)
                           if e["doc"] not in g and not (gf.key("TTDA", d) in kept and "doc" not in kept[gf.key("TTDA", d)])]


def alone(prod, day):
    if (prod, day) == gf.CONTROL:
        return {"why": "Gale has no issue that day"}
    if day == bad:
        raise urllib.error.HTTPError("u", 500, "HTTP 500", None, None)
    return dict(next(e for d, e in rows(3) if d == day))


kw["lookup_of"] = alone
kw["keep"] = lambda k, e: kept.__setitem__(k, e)
n, _ = gf.run(limit=2, **kw)
assert n == 2 and not [x for x in clock.slept if x in gf.OUTAGE_WAITS], (n, clock.slept)
assert kept[gf.key("TTDA", bad)]["why"] == gf.DAY_ALONE and "doc" not in kept[gf.key("TTDA", bad)], kept

# 6d. The Independent on Sunday wants nothing past its last print issue.
import datetime as _dt
import gale_inbox
assert max(gale_inbox.sunday_wanted("INDA", _dt.date(2026, 11, 1), laid=set())) <= gale_inbox.LAST_PRINTED["INDA"]

# 7. Each download is written to the log.
assert set(gf.load(kw["fetched"])) == {rows(3)[i][1]["doc"] for i in (0, 2)}

# 8. The session is browsed as a person does: the portal, its Times link
#    landing on Gale, then each document's page before its Download, every
#    request with the Referer of the page it was clicked on; only the
#    portal's certificate goes unverified; 401/403/429 is a refusal.
import gale_docs, gale_http
START = "https://go.gale.com/ps/start.do?p=TTDA&u=alberta_portal&sid=geolinks"
sent = []


def transport(answers):
    def get(url, headers, verify):
        sent.append((url, headers, verify))
        if url.endswith("/collections"):
            return 200, b"<html>", url
        if "auth.php" in url:
            return 200, b"<html>", START
        return answers(url)
    return get


day, e = rows(1)[0]
url = gale_docs.download_url("TTDA", day, e)
page = gale_docs.page_url("TTDA", e["doc"])
assert "id=GALE%7CCS400000000" in page and page.startswith(gale_docs.GALE + "/i.do?"), page
s = gf.Session(transport=transport(lambda u: (200, PDF if "BulkPDF" in u else b"<html>doc", u)))
assert s.download(url) == PDF
assert [u for u, _, _ in sent] == [f"{gale_docs.PORTAL}/collections", f"{gale_docs.PORTAL}/actions/auth.php?db=ttda",
                                   page, url], sent
assert [v for _, _, v in sent] == [False, False, True, True], sent
assert sent[0][1] == {} and sent[1][1]["Referer"] == f"{gale_docs.PORTAL}/collections"
assert sent[1][1]["Sec-Fetch-Site"] == "same-origin"
assert sent[2][1] == {"Referer": START, "Sec-Fetch-Site": "same-origin"}, sent[2]
assert sent[3][1] == {"Referer": page, "Sec-Fetch-Site": "same-origin"}, sent[3]
assert gale_http.fetch_site(f"{gale_docs.PORTAL}/collections", START) == "cross-site"
assert gale_http.fetch_site("https://link.gale.com/apps/x", START) == "same-site"
sent.clear()
s = gf.Session(transport=transport(lambda u: (403, b"<html>blocked", u) if "BulkPDF" in u else (200, b"<html>", u)))
try:
    s.download(url)
    raise AssertionError("a 403 was not a refusal")
except gf.Stop as stop:
    assert stop.refused and stop.status == 403 and stop.head == b"<html>blocked", stop
try:
    gf.Session(transport=transport(lambda u: (500, b"", u))).download(url)
    raise AssertionError("a 500 was not an error")
except urllib.error.HTTPError as err:
    assert err.code == 500
try:
    gf.Session(transport=lambda u, h, v: (200, b"<html>", "https://go.gale.com/ps/login.do"))
    raise AssertionError("a login landing opened a session")
except gf.Stop as stop:
    assert not stop.refused and "did not open" in str(stop)

# 9. Another paper's rows: its session opens through its own portal link
#    (a session on one archive 500s on another's), its Download names its
#    product, store and the log are told the product, and its downloads
#    count in the one window with the Times' (Gale's cap is per IP).
sent.clear()
gf.Session(prod="TGRH", transport=transport(lambda u: (200, b"<html>", u)))
assert sent[1][0] == f"{gale_docs.PORTAL}/actions/auth.php?db=tgrh", sent
tday, te = rows(1)[0]
turl = gale_docs.download_url("TGRH", tday, te)
assert gf.prod_of(turl) == "TGRH" and gf.prod_of(url) == "TTDA"
assert "Daily Telegraph" in urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlsplit(turl).query)
                                                 ["citationTextJson"][0])
assert gf.fetched_dir("TGRH") == f"{gf.GALE_ROOT}/Telegraph/Fetched" and gf.fetched_dir("TTDA") == gf.FETCHED_DIR
assert gf.fetched_dir("TGRH", None, datetime.date(1965, 3, 7)) == f"{gf.GALE_ROOT}/Sunday Telegraph/Fetched"
assert gf.fetched_dir("INDA", None, datetime.date(2008, 6, 1)) == f"{gf.GALE_ROOT}/Independent on Sunday/Fetched"
assert gf.fetched_dir("INDA", None, datetime.date(2008, 5, 31)) == f"{gf.GALE_ROOT}/Independent/Fetched"
assert gf.fetched_dir("LSNR") == f"{gf.GALE_ROOT}/Listener/Fetched"
clock, starts, stored, kw = harness(n_rows=4)
mixed = [("TTDA" if i < 2 else "TGRH", d, e) for i, (d, e) in enumerate(rows(4))]
kw["plan_of"] = lambda g: [r for r in mixed if r[2]["doc"] not in g]
got_prods = []
kw["store"] = lambda body, prod, day, doc, e: got_prods.append(prod)
n, _ = gf.run(limit=4, **kw)
assert got_prods == ["TTDA", "TTDA", "TGRH", "TGRH"], got_prods
log = gf.load(kw["fetched"])
assert [log[e["doc"]].get("prod") for _, _, e in mixed] == [None, None, "TGRH", "TGRH"], log
assert gf.in_window(kw["limits"], kw["fetched"], clock())[1] == 4

# 10. The plan: the Times' rows first; the other papers' only once fewer
#     than REPLAN Times rows are left, in OTHERS' order; a date Gale has
#     no crossword for, or whose document is got, is left out.
import dir_cache, gale_inbox, gale_listener
D = datetime.date
saved = {k: getattr(gale_inbox, k) for k in ("wanted", "aside_days", "staged_matches", "other_wanted", "misfiled", "sunday_wanted")}
saved_wanted = gale_listener.wanted
gale_listener.wanted = lambda: []
dir_cache.load = lambda *a: None
import gale_jumbo
gale_jumbo.wanted = lambda: []  # tested below
gale_jumbo.solution_days = lambda: []  # tested below
gale_inbox.aside_days = lambda: {}
gale_inbox.staged_matches = lambda: {}
gale_inbox.misfiled = lambda prod="TGRH": []  # it reads the media manifest, absent here
gale_inbox.sunday_wanted = lambda prod: []  # tested below
gale_inbox.other_wanted = lambda prod: {"TGRH": [D(2000, 1, 4), D(2000, 1, 3)], "FTHA": [D(2010, 1, 4)]}.get(prod, [])
saved_tld = gf.times_listener_days
gf.REQUESTS = Path("/nonexistent/requests.txt")  # not the machine's real request list
gf.HOLDS = Path("/nonexistent/holds.txt")  # nor its holds
gf.times_listener_days = lambda docs: []  # the Saturday Listener articles are tested below
docs ={"TGRH/2000-01-03": {"why": "no crossword in the issue's contents", "matcher": gale_docs.MATCHER["TGRH"]}, "FTHA/2010-01-04": {"doc": "HS1"}}
gale_docs.load = lambda *a: docs
gale_inbox.wanted = lambda: [(D(2001, 1, 2), "no-scan")]
assert gf.plan(set(), 0) == [("TTDA", D(2001, 1, 2), None), ("TGRH", D(2000, 1, 4), None),
                             ("FTHA", D(2010, 1, 4), {"doc": "HS1"})], gf.plan(set(), 0)
assert ("FTHA", D(2010, 1, 4), {"doc": "HS1"}) not in gf.plan({"HS1"}, 0)
# The Sunday papers' rows are not gated by the Times' backlog: they follow its
# rows at once, whatever their number.
gale_inbox.sunday_wanted = lambda prod: {"TGRH": [D(2000, 12, 31), D(2000, 12, 24)], "INDA": [D(2016, 12, 25)]}.get(prod, [])
_sp = gf.plan(set(), 0)
assert [r[:2] for r in _sp[:5]] == [("TTDA", D(2001, 1, 2)), ("TGRH", D(2000, 12, 31)), ("TGRH", D(2000, 12, 24)),
                                    ("INDA", D(2016, 12, 25)), ("TGRH", D(2000, 1, 4))] or \
    [r[:2] for r in _sp[:5]][1:4] == [("TGRH", D(2000, 12, 31)), ("TGRH", D(2000, 12, 24)), ("INDA", D(2016, 12, 25))], _sp
# The Times Jumbo rows (kind "jumbo", their own cache key) come after the
# Sunday Telegraph's and before the Independent on Sunday's (6eee53dfe1a: IoS
# runs after the Jumbos), then the Telegraph redo and other papers' rows.
gale_jumbo.wanted = lambda: [D(2000, 2, 5), D(2000, 1, 29)]
_jp = gf.plan(set(), 0)
assert [r[:2] for r in _jp[1:7]] == [("TGRH", D(2000, 12, 31)), ("TGRH", D(2000, 12, 24)), ("TTDA", D(2000, 2, 5)),
                                      ("TTDA", D(2000, 1, 29)), ("INDA", D(2016, 12, 25)), ("TGRH", D(2000, 1, 4))], _jp
assert _jp[3][3:] == (None, False, "jumbo"), _jp[3]
docs["TTDA/jumbo/2000-02-05"] = {"doc": "JU1", "title": "Jumbo Crossword 269", "page": 38, "records": ["R"], "kind": "jumbo",
                                 "matcher": gale_docs.MATCHER["jumbo"]}
assert [r[:2] for r in gf.plan(set(), 0)].count(("TTDA", D(2000, 2, 5))) == 1
assert ("TTDA", D(2000, 2, 5)) not in [r[:2] for r in gf.plan({"JU1"}, 0)], "a Jumbo page got is left out"
del docs["TTDA/jumbo/2000-02-05"]
assert gf.fetched_dir("TTDA", "jumbo", D(2000, 2, 5)) == gf.TIMES_JUMBO_DIR
gale_jumbo.wanted = lambda: []
gale_jumbo.solution_days = lambda: [D(2000, 2, 12)]
_sp = [r for r in gf.plan(set(), 0) if r[3:] == (None, False, "jumbo-solution")]
assert [r[:2] for r in _sp] == [("TTDA", D(2000, 2, 12))], _sp
_all = gf.plan(set(), 0)
assert [r[3:] for r in _all].index((None, False, "jumbo-solution")) < len(_all) - 1 or len(_all) == 1
assert _all.index(_sp[0]) == 0 or _all[0][3:] == (), "the solutions come ahead of the Times' backlog"
assert gf.key("TTDA", D(2000, 2, 12), kind="jumbo-solution") == "TTDA/jumbo-solution/2000-02-12"
assert gf.fetched_dir("TTDA", "jumbo-solution", D(2000, 2, 12)) == gf.TIMES_JUMBO_SOLUTIONS_DIR
assert gf.TIMES_JUMBO_SOLUTIONS_DIR.endswith("/TimesJumbo/Solutions") and gf.TIMES_JUMBO_SOLUTIONS_DIR != gf.TIMES_JUMBO_DIR
import downloads
assert str(downloads.TIMES_JUMBO_SOLUTIONS).endswith("TimesJumbo/Solutions")
gale_jumbo.solution_days = lambda: []
gale_inbox.wanted = lambda: [(D(2001, 1, 2) - datetime.timedelta(days=i), "no-scan") for i in range(gf.REPLAN)]
assert ("INDA", D(2016, 12, 25), None) in gf.plan(set(), 0), "Sundays do not wait for the Times"
gale_inbox.wanted = lambda: [(D(2001, 1, 2), "no-scan")]
gale_inbox.sunday_wanted = lambda prod: []
gale_inbox.wanted = lambda: [(D(2001, 1, 2) - datetime.timedelta(days=i), "no-scan") for i in range(gf.REPLAN)]
assert {r[0] for r in gf.plan(set(), 0)} == {"TTDA"}, "other papers wait while the Times has a plan's worth"
# The Listener's rows come after the Times' and before the other papers',
# each with its number and whether it is the report; a report is cached
# under its own key, and one got is left out.
gale_inbox.wanted = lambda: [(D(2001, 1, 2), "no-scan")]
gale_listener.wanted = lambda: [(D(1955, 6, 2), 1309, False), (D(1955, 6, 2), 1309, True)]
rep_e = {"doc": "GM9", "title": "Report on Crossword No. 1,309", "page": 40, "records": ["R"], "day": "1955-06-16",
         "matcher": gale_docs.MATCHER["LSNR"]}
docs["LSNR/report/1309"] = rep_e
assert gf.plan(set(), 0) == [("TTDA", D(2001, 1, 2), None), ("LSNR", D(1955, 6, 2), None, 1309, False),
                             ("LSNR", D(1955, 6, 2), rep_e, 1309, True), ("TGRH", D(2000, 1, 4), None),
                             ("FTHA", D(2010, 1, 4), {"doc": "HS1"})], gf.plan(set(), 0)
assert ("LSNR", D(1955, 6, 2), rep_e, 1309, True) not in gf.plan({"GM9"}, 0)
gale_listener.wanted = lambda: []
# A fetched page staged for a date is passed, unless an older matcher
# picked it (gale_docs.stale): then it is looked up again, and fetched over
# when the new pick is another document.
day = D(2006, 5, 23)
gale_inbox.wanted = lambda: [(day, "no-scan")]
gale_inbox.staged_matches = lambda: {day: [{"how": "fetched", "docId": "IF1"}]}
gale_inbox.other_wanted = lambda prod: []
times = lambda got: gf.plan(got, 0)
docs["TTDA/2006-05-23"] = {"doc": "IF1", "title": "Crossword Today's Weather", "page": 2}
assert times({"IF1"}) == [("TTDA", day, None)], times({"IF1"})
docs["TTDA/2006-05-23"] = {"doc": "IF2", "title": "The Times Crossword 23,296", "page": 87,
                           "matcher": gale_docs.MATCHER["TTDA"]}
assert times({"IF1"}) == [("TTDA", day, docs["TTDA/2006-05-23"])], times({"IF1"})
docs["TTDA/2006-05-23"] = {"doc": "IF1", "title": "The Times Crossword 23,296", "page": 87}
assert times({"IF1"}) == [], "the cryptic, fetched, is passed"
# The Saturday Times' Listener articles (1991-03-23 to 2014): their own kind,
# keyed apart from the daily crossword's, never superseding it, after the
# magazine Listener's rows and before the other papers'.
gf.times_listener_days = saved_tld
gale_inbox.wanted = lambda: []
days = gf.times_listener_days({})
assert days[0] == D(1991, 3, 23) and days[-1] <= D(2014, 12, 31) and all(d.weekday() == 5 for d in days)
assert len(days) == 1241, len(days)
assert gf.times_listener_days({"TTDA/1991-03-23": {"why": "Gale has no issue that day"}})[0] == D(1991, 3, 30)
assert gf.key("TTDA", D(2006, 8, 12), kind="listener") == "TTDA/listener/2006-08-12" != gf.key("TTDA", D(2006, 8, 12))
assert gf.want("TTDA", D(2006, 8, 12), {}, set(), kind="listener") == [("TTDA", D(2006, 8, 12), None, None, False, "listener")]
le = {"doc": "IF0000000194", "title": "The Listener Crossword 3890", "page": 70, "records": ["R"], "kind": "listener",
      "matcher": gale_docs.MATCHER["listener"]}
assert gf.want("TTDA", D(2006, 8, 12), {"TTDA/listener/2006-08-12": le}, set(), kind="listener") == \
    [("TTDA", D(2006, 8, 12), le, None, False, "listener")]
assert gf.want("TTDA", D(2006, 8, 12), {"TTDA/listener/2006-08-12": le}, {"IF0000000194"}, kind="listener") == []
# the daily page of that date is a different row, and a Listener entry does not make it superseded
assert gf.want("TTDA", D(2006, 8, 12), {"TTDA/listener/2006-08-12": le}, set()) == [("TTDA", D(2006, 8, 12), None)]
assert not gf.superseded(D(2006, 8, 12), [{"how": "fetched", "docId": "IF0000000194"}], {"TTDA/listener/2006-08-12": le})
plan_all = gf.plan(set(), 0)
tl = [r for r in plan_all if r[2:] and r[-1] == "listener"]
assert len(tl) == len(days) and {r[0] for r in tl} == {"TTDA"}, len(tl)
gale_listener.wanted = lambda: [(D(1955, 6, 2), 1309, False)]
gale_inbox.other_wanted = lambda prod: [D(2000, 1, 4)] if prod == "TGRH" else []
# Other papers come only while the plan has fewer than REPLAN rows, so give the
# Saturday list a few rows (the full 1241 would fill the plan and leave no TGRH).
gf.times_listener_days = lambda docs: days[:3]
order = [r[0] if not r[3:] or r[-1] != "listener" else "TTL" for r in gf.plan(set(), 0)]
gf.times_listener_days = saved_tld
assert order[0] == "LSNR" and order.index("TTL") < order.index("TGRH"), order[:3]
gale_listener.wanted = lambda: []
# its Fetched folder is its own, and file_page only keeps it (no edition, no magazine layout)
assert gf.fetched_dir("TTDA", "listener") == f"{gf.GALE_ROOT}/Listener/Times/Fetched" != gf.fetched_dir("TTDA")
kept = []
real_put, real_ssh = gf.put, gf.ssh
gf.put = lambda body, name, folder=gf.FETCHED_DIR: kept.append((name, folder))
gale_inbox_lay = gale_inbox.lay_out_fetched
gale_inbox.lay_out_fetched = lambda *a, **k: kept.append("laid out")
gf.file_page(b"%PDF", "TTDA", D(2006, 8, 12), "IF0000000194", le)
assert kept == [("GALE_IF0000000194.pdf", f"{gf.GALE_ROOT}/Listener/Times/Fetched")], kept
gf.put, gale_inbox.lay_out_fetched = real_put, gale_inbox_lay
for k, v in saved.items():
    setattr(gale_inbox, k, v)
gale_listener.wanted = saved_wanted

# 11. A Listener row is looked up with its number (a report by lookup_report)
#     and fetched from the issue its entry names: a report's from its own
#     issue, two weeks after its puzzle's.
clock, starts, stored, kw = harness(n_rows=0)
lday = D(1955, 6, 2)
asked, urls, kept = [], [], []
kw["plan_of"] = lambda g: [r for r in [("LSNR", lday, None, 1309, False), ("LSNR", lday, None, 1309, True)]
                           if not ({"GM1", "GM2"} <= g)]
kw["lookup_of"] = lambda prod, day, number, report: asked.append((prod, day, number, report)) or (
    {"doc": "GM2", "title": "Report on Crossword No. 1,309", "page": 40, "records": ["R"], "day": "1955-06-16"}
    if report else {"doc": "GM1", "title": "Crossword No. 1,309", "page": 42, "records": ["R"]})
kw["fetch"] = lambda url: urls.append(url) or PDF
kw["text_of"] = lambda body: "GM1 GM2"
kw["store"] = lambda body, prod, day, doc, e: kept.append((prod, day, doc))
n, _ = gf.run(limit=2, **kw)
assert asked == [("LSNR", lday, 1309, False), ("LSNR", lday, 1309, True)], asked
assert kept == [("LSNR", lday, "GM1"), ("LSNR", D(1955, 6, 16), "GM2")], kept
cites = [urllib.parse.unquote(urllib.parse.unquote(u)) for u in urls]
assert "Listener, 16 June 1955" in cites[1] and "Listener, 2 June 1955" in cites[0], cites
assert gf.key("LSNR", lday, 1309, True) == "LSNR/report/1309" and gf.key("LSNR", lday) == "LSNR/1955-06-02"
req = Path(tempfile.mkdtemp()) / "requests.txt"
assert gf.requested_days(req) == []
req.write_text("1981-06-20 bad 1930-04-18\n1981-06-20\n")
assert gf.requested_days(req) == [D(1981, 6, 20), D(1930, 4, 18)], gf.requested_days(req)
req.write_text("1981-06-20 INDA/1995-01-01 NOPE/1995-01-08 INDA/bad 1930-04-18\n")
assert gf.requested_rows(req) == [("TTDA", D(1981, 6, 20)), ("INDA", D(1995, 1, 1)), ("TTDA", D(1930, 4, 18))], gf.requested_rows(req)
assert gf.requested_days(req) == [D(1981, 6, 20), D(1930, 4, 18)]
hold = req.parent / "holds.txt"
assert gf.held_products(hold) == set()
hold.write_text("INDA  # reader not ready\n# FTHA\n")
assert gf.held_products(hold) == {"INDA"}, gf.held_products(hold)
print("test_gale_fetch: ok")
