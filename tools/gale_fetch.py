#!/usr/bin/env python3
"""Download the Gale Times pages still wanted, then the Listener's, then
the other papers' (gale_inbox.OTHERS), at a hand's pace, with no model in
the loop (Paul 2026-10-11, "Mac script, at hand pace").

Times rows come in gale_inbox.next_up's order (Times No 1, then the rest as
the progress page lists them), from row SKIP + 1 (--skip). Once fewer than
REPLAN Times rows are left, the Listener's follow (gale_listener.wanted:
each printed puzzle not filed or read, and each "Report on Crossword No. N"
page with its answers that no saved page holds, earliest first), then each
other paper's unfiled dates (gale_inbox.other_wanted), paper by paper in
OTHERS' order, newest first. Each row's document is looked up here
(gale_docs.lookup, or lookup_report for a report; kept in gale_docs.CACHE,
which only this script writes). Each PDF is
Gale's own Download (gale_docs.download_url) fetched in an Alberta Research
Portal session (geo-IP: this runs on the home connection, in the container
or on the Mac, same address) and checked to be a PDF whose citation names
its document. The session is browsed as Chrome (Session): Chrome's TLS,
HTTP/2 and headers through curl_cffi when installed, each document's page
opened before its Download, each request with the Referer of the page it
was clicked on. The date is known, so nothing matches it: it is laid out
straight away as that date's edition (gale_inbox.lay_out_fetched), which
tools/gale_read.sh reads and files (the Times'; file_archive_org_puzzles.py
reads the other papers', the Telegraph and FT in those papers' runs); a
Listener page goes to gale_listener.SAVED (gale_listener.lay_out_fetched),
which the standing pass reads and files (gale_listener.plan). Each is kept
as GALE_<doc>.pdf in its paper's Fetched folder on the Mac (fetched_dir).
Every paper's downloads count against the one LIMITS
window: Gale's cap is per IP, not per archive.

Pace (Pacer): GAP seconds between downloads, jittered, an occasional
longer PAUSE, never more than WINDOW_MAX in WINDOW seconds.

Gale's download limit counts per IP/institution over time, not per portal
session (Paul's browser agent, 2026-10-11: caps hit after ~475-500
downloads; a fresh session right after one was still blocked; a cap hit at
09:29 UTC was open again by 16:00). LIMITS holds the current count window
(its start, and downloads in it made elsewhere, e.g. by the browser), each
refusal and each recovery. At the cap (none until a refusal teaches
CAP_SHARE of the fewest downloads one came after) it waits until the
window's start plus the window length (WINDOW_SEED, until a recovery
teaches a shorter one), then starts a new window.

An answer that is not the PDF (HTTP 401/403/429, a login or other HTML
page, a non-PDF) is first taken for Gale having logged the session out: a
fresh session retries it at once, and that is only recorded (relogins).
Refused again, it is a refusal: recorded (when, downloads in the window, in
the last hour and day, the status, the answer's first bytes), the room told
quietly, and one fresh-session download tried every PROBE_EVERY seconds
until one works, each refused probe's time recorded, so the reset time is
pinned to within PROBE_EVERY; that recovery starts a new window.

It stops, and wakes the room (tools/wake.sh), at a captcha, a PDF too small
or naming another document, the portal not opening a session, Gale still
refusing after every probe, or MAX_ERRORS errors in a row (each retried
after a backoff). Resumable: a row whose document is in the Times folder,
its Set aside folder, a Fetched folder or this script's own log (FETCHED),
or whose date is staged, set aside or filed, is skipped. With no row left it waits IDLE
seconds, at most IDLE_MAX times in a row.

    python3 tools/gale_fetch.py [--max N] [--skip N] [--dry-run]
    bash tools/gale_fetch.sh            # the long run, from its own worktree
"""
import argparse
import collections
import datetime
import http.client
import json
import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import gale_docs
import hot_reload
import local_config
import media_manifest
from gale_http import Chrome, click_headers, verifies

#: Seconds between one download's end and the next request, drawn uniformly.
GAP = (8.0, 22.0)
#: Now and then a longer look away: (chance per download, seconds range).
PAUSE = (0.05, (60.0, 180.0))
#: At most WINDOW_MAX downloads in any WINDOW seconds (the pace asked for:
#: about 15 per 3 minutes at most).
WINDOW, WINDOW_MAX = 180.0, 15
#: The count window, each refusal, recovery and re-login.
LIMITS = Path(os.path.expanduser("~/.cache/gale_inbox/limits.json"))
#: No cap until a refusal is recorded (Paul 2026-10-11: learn the limit; a
#: refusal costs no more than waiting), and how long a window lasts until a
#: recovery says (a cap at 09:29 UTC was open by 16:00). With no cap the
#: window is never ended, so a refusal records the whole count.
CAP_SEED, WINDOW_SEED = None, 6.5 * 3600
#: The learned cap is this share of the fewest downloads in a window a
#: refusal came after, and never below CAP_FLOOR.
CAP_SHARE, CAP_FLOOR = 0.9, 50
#: After a refusal, one download every PROBE_EVERY seconds, at most
#: PROBE_MAX (a day), then it stops.
PROBE_EVERY, PROBE_MAX = 1800.0, 48
#: Errors in a row (network, 5xx, a write to the Mac) before it stops;
#: each one waits BACKOFF * its number first.
MAX_ERRORS = 3
BACKOFF = 60.0
#: With no row left to fetch: wait this long for a sync to move the list,
#: at most IDLE_MAX times in a row, then end.
IDLE, IDLE_MAX = 180.0, 20
#: The queue is worked out again after this many downloads (wanted() and
#: the staged dates move only with a sync).
REPLAN = 15
#: A Gale page PDF is a whole newspaper page: far more than this.
MIN_PDF = 20_000
FETCHED = Path(os.path.expanduser("~/.cache/gale_inbox/fetched.json"))
HOST = os.environ.get("GALE_INBOX_HOST") or local_config.get("mac_host")
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "HostKeyAlias=localhost",
       *(["-i", local_config.path("mac_ssh_key")] if local_config.get("mac_ssh_key") else [])]
GALE_ROOT = local_config.path("media_root") + "/Gale crosswords"
INBOX = f"{GALE_ROOT}/Times"
ASIDE = "Set aside"
#: Where each downloaded Times PDF is kept on the Mac (fetched_dir: each
#: paper's own).
FETCHED_DIR = f"{INBOX}/Fetched"
#: The Listener's folder under GALE_ROOT.
LISTENER = "Listener"
CHANNEL = os.environ.get("GALE_FETCH_CHANNEL", "cryptic-crosswords")
DOC = re.compile(r"[A-Z]{2}\d{8,12}", re.IGNORECASE)


class Stop(Exception):
    """Stop the run (and say why). `refused`: an answer Gale's download
    limit may give (run learns from it), with its HTTP `status` and first
    bytes `head`."""

    def __init__(self, why, refused=False, status=None, head=b""):
        super().__init__(why)
        self.refused, self.status, self.head = refused, status, head


class Reload(Exception):
    """A reload was asked (SIGHUP, or origin/master's tools/ code moved:
    tools/hot_reload.py). Raised between downloads and out of a wait, never in
    one: the run ends RELOAD_RC and tools/gale_fetch.sh moves the tree and
    starts it again, resuming off the log."""


class Pacer:
    """When the next download may start. `clock`, `sleep` and `rand` are
    injectable so the test runs it on a fake clock."""

    def __init__(self, clock=time.time, sleep=time.sleep, rand=None):
        self.clock, self.sleep, self.rand = clock, sleep, rand or random.Random()
        self.done = collections.deque()  # start times of the last WINDOW_MAX downloads
        self.last = None  # when the last download ended

    def delay(self):
        """Seconds to wait before the next download."""
        now = self.clock()
        wait = 0.0
        if self.last is not None:
            gap = self.rand.uniform(*GAP)
            if self.rand.random() < PAUSE[0]:
                gap += self.rand.uniform(*PAUSE[1])
            wait = max(wait, self.last + gap - now)
        while self.done and self.done[0] <= now - WINDOW:
            self.done.popleft()
        if len(self.done) >= WINDOW_MAX:
            wait = max(wait, self.done[0] + WINDOW - now)
        return max(0.0, wait)

    def wait(self):
        d = self.delay()
        if d:
            self.sleep(d)
        self.done.append(self.clock())
        if len(self.done) > WINDOW_MAX:
            self.done.popleft()

    def finished(self):
        """A download ended."""
        self.last = self.clock()


def learned(path=LIMITS):
    """(cap, window seconds) from the refusals and recoveries in `path`."""
    kept = load(path)
    after = [r["in_window"] for r in kept.get("refusals", ()) if "in_window" in r]
    cap = max(CAP_FLOOR, int(CAP_SHARE * min(after))) if after else CAP_SEED
    spans = [r["since_window_start"] for r in kept.get("recoveries", ()) if "since_window_start" in r]
    return cap, min(spans, default=WINDOW_SEED)


def iso(ts):
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def stamp(text):
    return datetime.datetime.fromisoformat(text).timestamp()


def save(path, kept):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(kept, indent=1))
    tmp.replace(path)


def record(path, kind, entry):
    """Append `entry` to list `kind` of `path` (LIMITS), whole or not at all."""
    kept = load(path)
    kept.setdefault(kind, []).append(entry)
    save(path, kept)


def new_window(path, at, before=0):
    """Start a count window at `at`, `before` downloads in it made elsewhere."""
    kept = load(path)
    kept["window"] = {"start": iso(at), "before": before}
    save(path, kept)


def in_window(path, fetched, now):
    """(window start, downloads in it: those made elsewhere plus this
    script's since the start), a new window started at `now` when none is."""
    w = load(path).get("window")
    if not w:
        new_window(path, now)
        return now, 0
    start = stamp(w["start"])
    mine = 0
    for e in load(fetched).values():
        try:
            mine += stamp(e["at"]) >= start
        except (KeyError, ValueError):
            continue
    return start, w.get("before", 0) + mine


def mean_gap(fetched, now, last=20):
    """The mean seconds between this script's last `last` downloads before
    `now` (the pace a refusal came at), or None."""
    ats = []
    for e in load(fetched).values():
        try:
            ats.append(stamp(e["at"]))
        except (KeyError, ValueError):
            continue
    ats = sorted(t for t in ats if t <= now)[-last:]
    return round((ats[-1] - ats[0]) / (len(ats) - 1), 1) if len(ats) > 1 else None


def recent(fetched, now, seconds):
    """Downloads logged in `fetched` in the `seconds` before `now`."""
    n = 0
    for e in load(fetched).values():
        try:
            n += 0 <= now - stamp(e["at"]) <= seconds
        except (KeyError, ValueError):
            continue
    return n


def verdict(body, doc, text_of=None):
    """(why `body` is not the PDF of document `doc`, whether it is an answer
    a download limit may give), or None when it is the PDF."""
    if body[:5] == b"%PDF-":
        if len(body) < MIN_PDF:
            return f"a PDF of only {len(body)} bytes", False
        if text_of is None:
            import gale_inbox  # pypdf; only once a PDF came
            text_of = gale_inbox.pdf_text
        text = text_of(body)
        if text and doc.upper() not in text.upper():
            return "a PDF whose citation does not name the document asked for", False
        return None
    text = body[:200_000].decode("utf-8", "replace").lower()
    if re.search(r"captcha|are you a robot|verify you are human|unusual traffic", text):
        return "a captcha page", False
    if re.search(r"password|log ?in|sign ?in|authenticat", text):
        return "a login page", True
    if "<html" in text or "<!doctype" in text:
        return "an HTML page instead of a PDF", True
    return f"not a PDF ({body[:40]!r})", True


def pdf_of(fetch, url, day, doc, text_of=None):
    """The PDF `fetch(url)` answers for `doc`; raises Stop when it is not."""
    body = fetch(url)
    bad = verdict(body, doc, text_of)
    if bad:
        raise Stop(f"{day} ({doc}) came back as {bad[0]}", refused=bad[1], head=body[:300])
    return body


def fetched_dir(prod):
    """The Mac folder product `prod`'s downloaded PDFs are kept in."""
    import gale_inbox
    if prod == "TTDA":
        return FETCHED_DIR
    return f"{GALE_ROOT}/{LISTENER if prod == 'LSNR' else gale_inbox.OTHERS[prod].folder}/Fetched"


def prod_of(url):
    """The Gale product a Download target is in (its p=)."""
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["p"][0]


class Session:
    """One Alberta Research Portal session on Gale's archive `prod`, browsed
    as a person in Chrome does: the portal's collections page, its link to
    the archive (which lands on Gale), then for each download the document's page
    and its Download, each sent with the Referer of the page it was clicked
    on. `transport` (Chrome's call signature) stands in for the network in
    the test."""

    def __init__(self, timeout=120, transport=None, prod="TTDA"):
        self.get = transport or Chrome(timeout)
        self.referer = None
        _, page = self.open(f"{gale_docs.PORTAL}/collections")
        self.referer = page
        _, url = self.open(f"{gale_docs.PORTAL}/actions/auth.php?db={gale_docs.PRODUCTS[prod][0]}")
        # Gale's start page itself carries login forms (Okta), so only the
        # address it lands on is judged.
        if "gale.com/ps/" not in url or re.search(r"login|authenticat|password", url, re.IGNORECASE):
            raise Stop(f"the portal did not open a Gale session (landed on {url})")
        self.referer = url

    def open(self, url, referer=None):
        """(body, final url) of `url`, clicked on page `referer` (default:
        the last page opened)."""
        referer = referer or self.referer
        headers = click_headers(referer, url)
        status, body, final = self.get(url, headers, verifies(url, gale_docs.PORTAL))
        if status in (401, 403, 429):
            raise Stop(f"Gale answered HTTP {status} for {url[:80]}", refused=True, status=status, head=body[:300])
        if status >= 400:
            raise urllib.error.HTTPError(final, status, f"HTTP {status}", None, None)
        return body, final

    def download(self, url):
        """The body of Download target `url` (gale_docs.download_url),
        clicked on its document's page, opened first as a person would."""
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        _, page = self.open(gale_docs.page_url(q["p"][0], q["dl"][0]))
        self.referer = page
        return self.open(url, referer=page)[0]


def ssh(command, **kw):
    return subprocess.run([*SSH, HOST, command], capture_output=True, check=True, timeout=180, **kw)


def have_docs():
    """The documents already got: those this script fetched (FETCHED, which
    note() rewrites as each lands, so this run's own count), those filed into
    an edition (the SSD gale-editions manifest gale_inbox appends to) and
    those set aside (gale_inbox.SET_ASIDE). Asked of the SSD every pass of
    run(): never a listing of the media disk's Gale folders (Paul
    2026-10-14: nothing regularly scans the spinning disk; an ssh `ls` there
    under load also killed a run)."""
    import gale_inbox
    got = {d.upper() for d in load(FETCHED)}
    for row in media_manifest.rows(gale_inbox.EDITIONS):
        for s in row.get("sources") or ():
            got |= {m.group(0).upper() for m in DOC.finditer(f"{s.get('docId') or ''} {s.get('file') or ''}")}
    got |= {m.group(0).upper() for f in load(gale_inbox.SET_ASIDE) for m in DOC.finditer(f)}
    return got


def load(path):
    """A snapshot-plus-record-lines file (gale_docs.read_log), or the plain
    JSON object the older files are."""
    return gale_docs.read_log(path)[0]


def note(doc, day, name, path=FETCHED, at=None, prod="TTDA"):
    gale_docs.keep(doc, {"date": day.isoformat(), "file": name, "at": iso(time.time() if at is None else at),
                         **({} if prod == "TTDA" else {"prod": prod})}, path)


#: Next-up rows passed over by default, so the run works well below
#: wherever a person or browser agent is clicking from the top (Paul
#: 2026-10-11: "start your script deeper down the list until I turn off the
#: browser"). --skip 0 once nobody else is downloading.
SKIP = int(os.environ.get("GALE_FETCH_SKIP", "0"))


def plan(got, skip=SKIP):
    """[(product, date, cache entry or None, *ask)] to fetch: the Times' in
    next_up order past its first `skip` rows (wanted, not staged, set aside
    or gone from Gale); then, with fewer than REPLAN of those, the
    Listener's (gale_listener.wanted; ask is its (number, report)); then,
    still fewer, each OTHERS paper's other_wanted; none a document in
    `got`, none Gale has no crossword for. None: not looked up yet (run
    looks it up)."""
    import gale_inbox
    rows = gale_inbox.wanted()
    docs = gale_docs.load()
    aside = gale_inbox.aside_days()
    passed = {d for d, ms in gale_inbox.staged_matches().items() if not superseded(d, ms, docs)} | set(aside)
    passed |= {d for d, _ in rows if gale_inbox.not_on_gale(d, docs, aside)}
    out = []
    for day, _ in gale_inbox.next_up(rows, passed, None)[skip:]:
        out += want("TTDA", day, docs, got)
    if len(out) < REPLAN:
        import gale_listener
        for day, number, report in gale_listener.wanted():
            out += want("LSNR", day, docs, got, number, report)
    if len(out) < REPLAN:
        for prod in gale_inbox.OTHERS:
            for day in gale_inbox.other_wanted(prod):
                out += want(prod, day, docs, got)
    return out


def superseded(day, ms, docs):
    """Whether `day`'s staged pages `ms` are a page this script fetched that
    its Times cache entry no longer names, or names under an older matcher
    (gale_docs.stale): it is looked up again and, picked anew, fetched over."""
    import gale_inbox
    e = docs.get(f"TTDA/{day.isoformat()}")
    fetched = {(m.get("docId") or "").upper() for m in ms if m.get("how") == gale_inbox.FETCHED_HOW}
    return bool(e and fetched) and (gale_docs.stale("TTDA", e) or e.get("doc", "").upper() not in fetched)


def key(prod, day, number=None, report=False):
    """The gale_docs.CACHE key of a row: its date's, or the report's on
    puzzle `number`."""
    return f"{prod}/report/{number}" if report else f"{prod}/{day.isoformat()}"


def want(prod, day, docs, got, number=None, report=False):
    """[(prod, day, its cache entry or None, *ask)], or [] when Gale has no
    crossword that day (no report on `number`) or its document is in `got`.
    ask: (number, report), given a number (the Listener's rows). None: not
    looked up yet, or looked up by an older matcher (gale_docs.stale)."""
    ask = () if number is None else (number, report)
    e = docs.get(key(prod, day, number, report))
    if e is None or gale_docs.stale(prod, e):
        return [(prod, day, None, *ask)]
    return [(prod, day, e, *ask)] if "doc" in e and e["doc"].upper() not in got else []


def look_up(prod, day, gale, number=None, report=False):
    """The cache entry for `day` of `prod` (gale_docs.lookup), or for the
    report on puzzle `number` of `day` (gale_docs.lookup_report, its issue's
    date its "day"), kept in gale_docs.CACHE."""
    e = (gale_docs.lookup_report if report else gale_docs.lookup)(prod, day, gale, number)
    e["at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    e["matcher"] = gale_docs.MATCHER[prod]
    gale_docs.keep(key(prod, day, number, report), e)
    return e


def put(body, name, folder=FETCHED_DIR):
    """Write `body` into `folder` on the Mac as `name` (whole or not at all)."""
    q = shlex.quote
    tmp = f"{folder}/.{name}.part"
    ssh(f"mkdir -p {q(folder)} && cat > {q(tmp)} && mv -f {q(tmp)} {q(folder + '/' + name)}", input=body)


def file_page(body, prod, day, doc, e):
    """Keep the PDF on the Mac and lay it out as issue `day`'s: a
    Listener page for its reader (a report's entry carries its issue's
    "day"), any other as that date's edition."""
    put(body, f"GALE_{doc}.pdf", fetched_dir(prod))
    if prod == "LSNR":
        import gale_listener
        # In the container the Mac's media root is not mounted: the desktop's
        # standing pass reads the Fetched copy put() just wrote.
        if gale_listener.SAVED.parent.is_dir():
            gale_listener.lay_out_fetched(day, doc, body, report="day" in e)
        return
    import gale_inbox
    gale_inbox.lay_out_fetched(day, doc, body, e, prod=prod)


def alert(text, quiet=False):
    """Wake the room (`quiet`: queued for its next turn); never raises."""
    print(f"ALERT: {text}", flush=True)
    for wake in (os.environ.get("GALE_FETCH_WAKE"), "/app/tools/wake.sh", shutil.which("wake.sh"),
                 str(Path(__file__).resolve().parents[3] / "household/tools/wake.sh")):
        if wake and os.access(wake, os.X_OK):
            try:
                subprocess.run([wake, *(["-q"] if quiet else []), "-c", CHANNEL,
                                f"Gale downloader: {text}" if quiet else f"Gale downloader stopped: {text}"],
                               timeout=60)
            except (OSError, subprocess.SubprocessError) as e:
                print(f"wake failed: {e}", flush=True)
            return
    print("no wake.sh found", flush=True)


def run(limit=None, dry=False, pacer=None, fetch=None, store=None, plan_of=None, got_of=None, log=print,
        fetched=FETCHED, text_of=None, skip=SKIP, lookup_of=None, limits=LIMITS, tell=None, reload=None):
    """Fetch until `limit` downloads, no row left, or a stop. The hooks
    (`fetch(url) -> body`, `store(body, prod, day, doc, entry)`, `plan_of(got)`,
    `got_of()`, `lookup_of(prod, day)`, `fetched`, `limits`, `tell(text)`) stand
    in for Gale, the Mac, the logs and the room in the test. Returns
    (downloads, why it ended); raises Stop to stop, and Reload between two
    downloads when `reload()` says so."""
    pacer = pacer or Pacer()
    sessions = {}  # one per product: a session on one archive 500s on another's

    def real_fetch(url):
        prod = prod_of(url)
        sessions[prod] = sessions.get(prod) or Session(prod=prod)
        return sessions[prod].download(url)

    def fresh_session():
        sessions.clear()

    fetch = fetch or real_fetch
    store = store or file_page
    plan_of = plan_of or (lambda got: plan(got, skip))
    tell = tell or (lambda text: alert(text, quiet=True))
    gale = None

    def real_lookup(prod, day, *ask):
        nonlocal gale
        gale = gale or gale_docs.Gale()
        return look_up(prod, day, gale, *ask)

    def hold():
        """At the window's cap, wait out the window, then start a new one;
        a window past its length is ended either way."""
        cap, span = learned(limits)
        now = pacer.clock()
        start, count = in_window(limits, fetched, now)
        if cap is None:
            return
        if count >= cap and start + span > now:
            log(f"{count} downloads in the window since {iso(start)}, the cap is {cap}: waiting until"
                f" {iso(start + span)}")
            pacer.sleep(start + span - now)
            now = pacer.clock()
        if now >= start + span:
            new_window(limits, now)

    def refused(first, url, day, doc):
        """`first` was not the PDF. A fresh session retries at once (Gale
        logs a session out now and then); refused again, it is Gale's limit:
        recorded, then one fresh-session download every PROBE_EVERY until
        one works. The body that came; raises Stop when none did."""
        fresh_session()
        try:
            body = pdf_of(fetch, url, day, doc, text_of)
            record(limits, "relogins", {"at": iso(pacer.clock()), "why": str(first)})
            log(f"{day}: {first}; a fresh session got it (a logout)")
            return body
        except Stop as again:
            if not again.refused:
                raise
            refusal = again
        now = pacer.clock()
        start, count = in_window(limits, fetched, now)
        entry = {"at": iso(now), "in_window": count, "window_start": iso(start), "run": n,
                 "last_10min": recent(fetched, now, 600), "last_hour": recent(fetched, now, 3600),
                 "last_day": recent(fetched, now, 86400), "mean_gap_last_20": mean_gap(fetched, now),
                 "status": refusal.status, "why": str(refusal), "head": refusal.head.decode("utf-8", "replace")}
        record(limits, "refusals", entry)
        tell(f"Gale refused a download after {count} in the window since {entry['window_start']}"
             f" ({entry['last_hour']} in the last hour), in a fresh session too: {refusal}. Recorded in {limits};"
             f" trying one every {PROBE_EVERY / 60:.0f} min to time the reset. Cap now {learned(limits)[0]}.")
        log(f"refused after {count} in the window: {refusal}")
        last_refused = now
        for i in range(1, PROBE_MAX + 1):
            pacer.sleep(PROBE_EVERY)
            fresh_session()
            try:
                body = pdf_of(fetch, url, day, doc, text_of)
            except Stop as again:
                if not again.refused:
                    raise
                last_refused = pacer.clock()
                log(f"probe {i}: still refused ({again})")
                continue
            except (urllib.error.URLError, http.client.HTTPException, OSError) as ex:
                log(f"probe {i}: {type(ex).__name__}: {ex}")
                continue
            ok = pacer.clock()
            record(limits, "recoveries", {"refused_at": iso(now), "last_refused_at": iso(last_refused),
                                          "ok_at": iso(ok), "ok_utc": datetime.datetime.fromtimestamp(
                                              ok, datetime.timezone.utc).strftime("%H:%M"),
                                          "waited": ok - now, "since_window_start": ok - start, "probes": i})
            new_window(limits, ok)
            log(f"Gale works again at {iso(ok)} (refused still at {iso(last_refused)}); a new window starts")
            tell(f"Gale works again at {iso(ok)}, {(ok - now) / 60:.0f} min after the refusal (still refused at"
                 f" {iso(last_refused)}). Recorded in {limits}.")
            return body
        raise Stop(f"Gale still refused {PROBE_MAX * PROBE_EVERY / 3600:.0f} h after a refusal ({refusal})")

    lookup_of = lookup_of or real_lookup
    got_of = got_of or have_docs
    n, errors, idle = 0, 0, 0
    while limit is None or n < limit:
        if reload and reload():
            raise Reload("reload asked")
        got = got_of()
        todo = plan_of(got)[:REPLAN]
        if not todo:
            idle += 1
            if idle > IDLE_MAX:
                return n, f"no row to fetch after {IDLE_MAX} waits"
            log(f"no row to fetch; waiting {IDLE:.0f}s ({idle}/{IDLE_MAX})")
            pacer.sleep(IDLE)
            continue
        idle = 0
        for prod, day, e, *ask in todo:
            if limit is not None and n >= limit:
                break
            if reload and reload():
                raise Reload("reload asked")
            if e is None:
                if dry:
                    log(f"would look up {prod} {day}{' report' if ask[1:] == [True] else ''}, then fetch it")
                    continue
                try:
                    e = lookup_of(prod, day, *ask)
                except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, KeyError) as ex:
                    errors += 1
                    log(f"{day}: lookup {type(ex).__name__}: {ex} (error {errors}/{MAX_ERRORS})")
                    if errors >= MAX_ERRORS:
                        raise Stop(f"{MAX_ERRORS} errors in a row, the last a lookup's {type(ex).__name__}: {ex}")
                    gale = None
                    pacer.sleep(BACKOFF * errors)
                    break
                if "doc" not in e:
                    log(f"{day}: {e.get('why')}")
                    continue
            doc = e["doc"].upper()
            if doc in got:
                continue
            # A report is printed in a later issue than its puzzle's.
            day = datetime.date.fromisoformat(e["day"]) if "day" in e else day
            url = gale_docs.download_url(prod, day, e)
            if dry:
                log(f"would fetch {prod} {day} {doc} {e.get('title', '')}")
                n += 1
                continue
            hold()
            pacer.wait()
            try:
                try:
                    body = pdf_of(fetch, url, day, doc, text_of)
                except Stop as first:
                    if not first.refused:
                        raise
                    body = refused(first, url, day, doc)
                store(body, prod, day, doc, e)
            except Stop:
                raise
            except (urllib.error.URLError, http.client.HTTPException, OSError,
                    subprocess.SubprocessError) as ex:
                errors += 1
                log(f"{day} {doc}: {type(ex).__name__}: {ex} (error {errors}/{MAX_ERRORS})")
                if errors >= MAX_ERRORS:
                    raise Stop(f"{MAX_ERRORS} errors in a row, the last {type(ex).__name__}: {ex}")
                fresh_session()
                pacer.sleep(BACKOFF * errors)
                break  # plan again: the row is still wanted
            errors = 0
            got.add(doc)
            note(doc, day, f"GALE_{doc}.pdf", fetched, pacer.clock(), prod)
            n += 1
            log(f"{datetime.datetime.now():%H:%M:%S} got {prod} {day} {doc} ({len(body):,} bytes) [{n}]")
            pacer.finished()
        if dry:
            return n, "dry run: one plan shown"
    return n, f"reached --max {limit}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--max", type=int, help="stop after this many downloads")
    ap.add_argument("--skip", type=int, default=SKIP, help=f"pass over this many next-up rows first (default {SKIP})")
    ap.add_argument("--dry-run", action="store_true", help="list what would be fetched")
    ap.add_argument("--window", nargs=2, metavar=("START", "BEFORE"),
                    help="start the count window at ISO time START with BEFORE downloads made elsewhere, then run")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)
    for log in (FETCHED, gale_docs.CACHE):
        gale_docs.compact(log)  # once a run, if many lines have piled up
    if a.window:
        new_window(LIMITS, stamp(a.window[0]), int(a.window[1]))
    cap, span = learned()
    start, count = in_window(LIMITS, FETCHED, time.time())
    print(f"=== Gale downloads from {datetime.datetime.now():%F %T}: gap {GAP[0]:.0f}-{GAP[1]:.0f}s, "
          f"<= {WINDOW_MAX}/{WINDOW:.0f}s, cap {cap} a {span / 3600:.1f} h window ({count} in the one since "
          f"{iso(start)}), next-up rows from {a.skip + 1} ===")
    # SIGHUP (or the watcher: origin/master's tools/ code moved) reloads. Every
    # wait is cut short by it, as a download in flight is not.
    asked = threading.Event()
    signal.signal(signal.SIGHUP, lambda *_: asked.set())
    watcher = hot_reload.Watcher(Path(__file__).resolve().parent.parent).start() if hot_reload.enabled() else None

    def reload():
        return asked.is_set() or bool(watcher and watcher.hit)

    def nap(seconds):
        end = time.time() + seconds
        while (left := end - time.time()) > 0:
            if reload():
                raise Reload("reload asked")
            asked.wait(min(left, 5.0))

    try:
        n, why = run(a.max, a.dry_run, pacer=Pacer(sleep=nap), skip=a.skip, reload=reload)
    except Reload:
        why = "SIGHUP" if asked.is_set() else f"origin/master changed {hot_reload.summary(watcher.hit)}"
        print(f"reload: {why}; exiting {hot_reload.RELOAD_RC} for the wrapper to move the tree and start again", flush=True)
        return hot_reload.RELOAD_RC
    except Stop as e:
        alert(f"{e}. Nothing more is fetched until it is restarted.")
        return 2
    print(f"=== done: {n} downloaded; {why} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
