#!/usr/bin/env python3
"""Download the Gale Times pages the checklist wants, at a hand's pace, with
no model in the loop (Paul 2026-10-11, "Mac script, at hand pace": it took
over from a Claude-in-browser that clicked each Download row).

Rows come in the checklist's own order (gale_inbox.next_up: Times No 1,
then the rest as the page lists them), from row SKIP + 1 (--skip; deep by
default, below wherever a person or browser agent clicks from the top).
A row tools/gale_docs.py has looked up uses its link; one not looked up
yet is looked up here (gale_docs.lookup, kept in OWN_DOCS). Each PDF is Gale's own Download (gale_docs.download_url) fetched in
an Alberta Research Portal session (geo-IP: this runs on the home
connection, in the container or on the Mac, same address), checked to be a
PDF whose citation names its document, and written into the Mac's Times
inbox as GALE_<doc>.pdf, where the next gale_inbox sync mirrors, matches
and stages it like a click's file. Nothing new files it.

Pace (Pacer): GAP seconds between downloads, jittered, an occasional
longer PAUSE, never more than WINDOW_MAX in WINDOW seconds; a portal
session is dropped after SESSION_CAP downloads (Paul's own sessions ran
100-460 clicks; his browser stalled after a 459-click one) and the next
starts after a REST.

It stops, and wakes the room (tools/wake.sh), at the first login or
password page, captcha, HTML or other non-PDF where a PDF should be, HTTP
403/429, or MAX_ERRORS errors in a row (each retried after a backoff).
Resumable: a row whose document is in the inbox, its Set aside folder,
Arrived.js or this script's own log (FETCHED), or whose date is staged,
set aside or filed, is skipped. With no linked row left it waits IDLE
seconds for the sync's lookups, at most IDLE_MAX times in a row.

    python3 tools/gale_fetch.py [--max N] [--skip N] [--dry-run]
    bash tools/gale_fetch.sh            # the long run, from its own worktree
"""
import argparse
import collections
import datetime
import http.client
import http.cookiejar
import json
import os
import random
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import gale_docs

#: Seconds between one download's end and the next request, drawn uniformly.
GAP = (8.0, 22.0)
#: Now and then a longer look away: (chance per download, seconds range).
PAUSE = (0.05, (60.0, 180.0))
#: At most WINDOW_MAX downloads in any WINDOW seconds (the pace asked for:
#: about 15 per 3 minutes at most).
WINDOW, WINDOW_MAX = 180.0, 15
#: Downloads per portal session, then REST seconds before a fresh one.
SESSION_CAP = 400
REST = (1800.0, 3600.0)
#: Errors in a row (network, 5xx, a write to the Mac) before it stops;
#: each one waits BACKOFF * its number first.
MAX_ERRORS = 3
BACKOFF = 60.0
#: With no linked row to fetch: wait this long for the sync's lookups, at
#: most IDLE_MAX times in a row, then end.
IDLE, IDLE_MAX = 180.0, 20
#: The queue is worked out again after this many downloads (wanted() and
#: the staged dates move only with a sync).
REPLAN = 15
#: A Gale page PDF is a whole newspaper page: far more than this.
MIN_PDF = 20_000
FETCHED = Path(os.path.expanduser("~/.cache/gale_inbox/fetched.json"))
HOST = os.environ.get("GALE_INBOX_HOST", "pt@host.docker.internal")
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "HostKeyAlias=localhost",
       "-i", os.path.expanduser("~/.ssh/host_hatch")]
GALE_ROOT = "/Volumes/Media/Gale crosswords"
INBOX = f"{GALE_ROOT}/Times"
ASIDE = "Set aside"
ARRIVED = f"{GALE_ROOT}/Arrived.js"
CHANNEL = os.environ.get("GALE_FETCH_CHANNEL", "cryptic-crosswords")
DOC = re.compile(r"[A-Z]{2}\d{8,12}", re.IGNORECASE)


class Stop(Exception):
    """Gale refused: stop the run (and say why)."""


class Pacer:
    """When the next download may start. `clock`, `sleep` and `rand` are
    injectable so the test runs it on a fake clock."""

    def __init__(self, clock=time.time, sleep=time.sleep, rand=None):
        self.clock, self.sleep, self.rand = clock, sleep, rand or random.Random()
        self.done = collections.deque()  # start times of the last WINDOW_MAX downloads
        self.last = None  # when the last download ended
        self.session = 0  # downloads in this portal session

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
        """A download ended. True when the session is at its cap (the caller
        rests (rest()) and opens a fresh one)."""
        self.last = self.clock()
        self.session += 1
        return self.session >= SESSION_CAP

    def rest(self):
        self.sleep(self.rand.uniform(*REST))
        self.session = 0
        self.last = self.clock()


def verdict(body, doc, text_of=None):
    """Why `body` is not the PDF of document `doc`, or None when it is."""
    if body[:5] == b"%PDF-":
        if len(body) < MIN_PDF:
            return f"a PDF of only {len(body)} bytes"
        if text_of is None:
            import gale_inbox  # pypdf; only once a PDF came
            text_of = gale_inbox.pdf_text
        text = text_of(body)
        if text and doc.upper() not in text.upper():
            return "a PDF whose citation does not name the document asked for"
        return None
    text = body[:200_000].decode("utf-8", "replace").lower()
    if re.search(r"captcha|are you a robot|verify you are human|unusual traffic", text):
        return "a captcha page"
    if re.search(r"password|log ?in|sign ?in|authenticat", text):
        return "a login page"
    if "<html" in text or "<!doctype" in text:
        return "an HTML page instead of a PDF"
    return f"not a PDF ({body[:40]!r})"


class Session:
    """One Alberta Research Portal session on Gale's Times archive."""

    def __init__(self, timeout=120):
        self.timeout = timeout
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                              urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        self.op.addheaders = [("User-Agent", gale_docs.UA)]
        self.open(f"{gale_docs.PORTAL}/collections")
        _, url = self.open(f"{gale_docs.PORTAL}/actions/auth.php?db=ttda")
        # Gale's start page itself carries login forms (Okta), so only the
        # address it lands on is judged.
        if "gale.com/ps/" not in url or re.search(r"login|authenticat|password", url, re.IGNORECASE):
            raise Stop(f"the portal did not open a Gale session (landed on {url})")

    def open(self, url):
        try:
            with self.op.open(url, timeout=self.timeout) as r:
                return r.read(), r.geturl()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                raise Stop(f"Gale answered HTTP {e.code} for {url[:80]}") from e
            raise


def ssh(command, **kw):
    return subprocess.run([*SSH, HOST, command], capture_output=True, check=True, timeout=180, **kw)


def have_docs():
    """The documents already got: named in the inbox or its Set aside
    folder, marked in Arrived.js, or in FETCHED."""
    q = shlex.quote
    out = ssh(f"cd {q(INBOX)} && ls -1 . {q(ASIDE)} 2>/dev/null; echo ===; cat {q(ARRIVED)} 2>/dev/null; exit 0",
              text=True).stdout
    names, _, arrived = out.partition("===")
    got = {m.group(0).upper() for m in DOC.finditer(names)}
    got |= {m.group(0).upper() for m in DOC.finditer(arrived)}
    return got | set(load(FETCHED))


def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def note(doc, day, name, path=FETCHED):
    kept = load(path)
    kept[doc] = {"date": day.isoformat(), "file": name,
                 "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(kept, indent=0, sort_keys=True))
    tmp.replace(path)


#: Next-up rows passed over by default, so the run works well below
#: wherever a person or browser agent is clicking from the top (Paul
#: 2026-10-11: "start your script deeper down the list until I turn off the
#: browser"). --skip 0 once nobody else is downloading.
SKIP = int(os.environ.get("GALE_FETCH_SKIP", "2000"))
#: Download links this script looked up itself, for rows past what the
#: sync's lookups (gale_docs.resolve, in next-up order) have reached; its
#: own file, so neither writer drops the other's entries.
OWN_DOCS = Path(os.path.expanduser("~/.cache/gale_inbox/fetch_docs.json"))


def plan(got, skip=SKIP):
    """[(date, cache entry or None)] to fetch, in next_up order past its
    first `skip` rows: wanted, not staged, set aside or gone from Gale, and
    not a document in `got`. None: not looked up yet (run looks it up)."""
    import dir_cache
    import gale_inbox
    dir_cache.load(gale_inbox.DIR_CACHE)
    rows = gale_inbox.wanted()
    docs = {**load(OWN_DOCS), **gale_docs.load()}
    aside = gale_inbox.aside_days()
    passed = set(gale_inbox.staged_files()) | set(aside)
    passed |= {d for d, _ in rows if gale_inbox.not_on_gale(d, docs, aside)}
    out = []
    for day, _ in gale_inbox.next_up(rows, passed, None)[skip:]:
        e = docs.get(f"TTDA/{day.isoformat()}")
        if e is None:
            out.append((day, None))
        elif "doc" in e and e["doc"].upper() not in got:
            out.append((day, e))
    return out


def look_up(day, gale):
    """The cache entry for `day` (gale_docs.lookup), kept in OWN_DOCS."""
    e = gale_docs.lookup("TTDA", day, gale)
    e["at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    if "doc" not in e:
        e["matcher"] = gale_docs.MATCHER
    kept = load(OWN_DOCS)
    kept[f"TTDA/{day.isoformat()}"] = e
    OWN_DOCS.parent.mkdir(parents=True, exist_ok=True)
    tmp = OWN_DOCS.with_suffix(".tmp")
    tmp.write_text(json.dumps(kept, indent=0, sort_keys=True))
    tmp.replace(OWN_DOCS)
    return e


def put(body, name):
    """Write `body` into the Mac's Times inbox as `name` (whole or not at all)."""
    q = shlex.quote
    tmp = f"{INBOX}/.{name}.part"
    ssh(f"cat > {q(tmp)} && mv -n {q(tmp)} {q(INBOX + '/' + name)} && rm -f {q(tmp)}", input=body)


def alert(text):
    """Wake the room; never raises."""
    print(f"ALERT: {text}", flush=True)
    for wake in (os.environ.get("GALE_FETCH_WAKE"), "/app/tools/wake.sh", shutil.which("wake.sh"),
                 str(Path(__file__).resolve().parents[3] / "household/tools/wake.sh")):
        if wake and os.access(wake, os.X_OK):
            try:
                subprocess.run([wake, "-c", CHANNEL, f"Gale downloader stopped: {text}"], timeout=60)
            except (OSError, subprocess.SubprocessError) as e:
                print(f"wake failed: {e}", flush=True)
            return
    print("no wake.sh found", flush=True)


def run(limit=None, dry=False, pacer=None, fetch=None, store=None, plan_of=None, got_of=None, log=print,
        fetched=FETCHED, text_of=None, skip=SKIP, lookup_of=None):
    """Fetch until `limit` downloads, no row left, or Gale refuses. The
    hooks (`fetch(url) -> body`, `store(body, name)`, `plan_of(got)`,
    `got_of()`, `lookup_of(day)`, `fetched`) stand in for Gale, the Mac and the log in the test. Returns
    (downloads, why it ended); raises Stop when Gale refused."""
    pacer = pacer or Pacer()
    session = None

    def real_fetch(url):
        nonlocal session
        session = session or Session()
        return session.open(url)[0]

    fetch = fetch or real_fetch
    store = store or put
    plan_of = plan_of or (lambda got: plan(got, skip))
    gale = None

    def real_lookup(day):
        nonlocal gale
        gale = gale or gale_docs.Gale()
        return look_up(day, gale)

    lookup_of = lookup_of or real_lookup
    got_of = got_of or have_docs
    n, errors, idle = 0, 0, 0
    while limit is None or n < limit:
        got = got_of()
        todo = plan_of(got)[:REPLAN]
        if not todo:
            idle += 1
            if idle > IDLE_MAX:
                return n, f"no linked row to fetch after {IDLE_MAX} waits"
            log(f"no linked row to fetch; waiting {IDLE:.0f}s for the sync's lookups ({idle}/{IDLE_MAX})")
            pacer.sleep(IDLE)
            continue
        idle = 0
        for day, e in todo:
            if limit is not None and n >= limit:
                break
            if e is None:
                if dry:
                    log(f"would look up {day}, then fetch it")
                    continue
                try:
                    e = lookup_of(day)
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
            name = f"GALE_{doc}.pdf"
            url = gale_docs.download_url("TTDA", day, e)
            if dry:
                log(f"would fetch {day} {doc} {e.get('title', '')}")
                n += 1
                continue
            pacer.wait()
            try:
                body = fetch(url)
                why = verdict(body, doc, text_of)
                if why:
                    raise Stop(f"{day} ({doc}) came back as {why}")
                store(body, name)
            except Stop:
                raise
            except (urllib.error.URLError, http.client.HTTPException, OSError,
                    subprocess.SubprocessError) as ex:
                errors += 1
                log(f"{day} {doc}: {type(ex).__name__}: {ex} (error {errors}/{MAX_ERRORS})")
                if errors >= MAX_ERRORS:
                    raise Stop(f"{MAX_ERRORS} errors in a row, the last {type(ex).__name__}: {ex}")
                session = None
                pacer.sleep(BACKOFF * errors)
                break  # plan again: the row is still wanted
            errors = 0
            got.add(doc)
            note(doc, day, name, fetched)
            n += 1
            log(f"{datetime.datetime.now():%H:%M:%S} got {day} {doc} ({len(body):,} bytes) -> {name} [{n}]")
            if pacer.finished():
                log(f"session cap {SESSION_CAP} reached; resting before a fresh portal session")
                session = None
                pacer.rest()
        if dry:
            return n, "dry run: one plan shown"
    return n, f"reached --max {limit}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--max", type=int, help="stop after this many downloads")
    ap.add_argument("--skip", type=int, default=SKIP,
                    help=f"pass over this many next-up rows first (default {SKIP}; 0 once no one else downloads)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be fetched")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)
    print(f"=== Gale downloads from {datetime.datetime.now():%F %T}: gap {GAP[0]:.0f}-{GAP[1]:.0f}s, "
          f"<= {WINDOW_MAX}/{WINDOW:.0f}s, {SESSION_CAP} a session, "
          f"next-up rows from {a.skip + 1} ===")
    try:
        n, why = run(a.max, a.dry_run, skip=a.skip)
    except Stop as e:
        alert(f"{e}. Nothing more is fetched until it is restarted.")
        return 2
    print(f"=== done: {n} downloaded; {why} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
