#!/usr/bin/env python3
"""Download the Gale Times pages the checklist wants, at a hand's pace, with
no model in the loop (Paul 2026-10-11, "Mac script, at hand pace": it took
over from a Claude-in-browser that clicked each Download row).

Rows come in the checklist's own order (gale_inbox.next_up: Times No 1,
then the rest as the page lists them), from row SKIP + 1 (--skip; deep by
default, below wherever a person or browser agent clicks from the top).
Each row's document is looked up here (gale_docs.lookup, kept in
gale_docs.CACHE, which only this script writes for the Times). Each PDF is
Gale's own Download (gale_docs.download_url) fetched in an Alberta Research
Portal session (geo-IP: this runs on the home connection, in the container
or on the Mac, same address) and checked to be a PDF whose citation names
its document. The date is known, so nothing matches it: it is laid out
straight away as that date's edition (gale_inbox.lay_out_fetched), which
tools/gale_read.sh reads and files, and kept as FETCHED_DIR/GALE_<doc>.pdf
on the Mac (out of the inbox, so no sweep, match or set-aside sees it).

Pace (Pacer): GAP seconds between downloads, jittered, an occasional
longer PAUSE, never more than WINDOW_MAX in WINDOW seconds; after a
session cap (learned, below) it rests and opens a fresh portal session.

Gale's download limit (Paul 2026-10-11: his browser hit one at about 500)
is learned, not guessed: a download answered by HTTP 401/403/429, a login
or other HTML page, or a non-PDF is a refusal. Each is recorded in LIMITS
(when, downloads this portal session, since the last rest, in the last hour
and day, the status and the first bytes of the answer), the room is told
quietly, and one fresh-session download is tried after each wait of PROBES
until one works; that wait is recorded too. The session cap is then
CAP_SHARE of the fewest downloads any refusal came after, and the rest at
least the longest wait seen (learned). With none recorded there is no cap.

It stops, and wakes the room (tools/wake.sh), at a captcha, a PDF too small
or naming another document, the portal not opening a session, Gale still
refusing after every probe, or MAX_ERRORS errors in a row (each retried
after a backoff). Resumable: a row whose document is in the inbox, its Set
aside folder, FETCHED_DIR or this script's own log (FETCHED), or whose date
is staged, set aside or filed, is skipped. With no row left it waits IDLE
seconds, at most IDLE_MAX times in a row.

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
#: The shortest rest after a session cap (learned may lengthen it).
REST = (1800.0, 3600.0)
#: Each refusal (Gale's limit) and how long until a download worked again.
LIMITS = Path(os.path.expanduser("~/.cache/gale_inbox/limits.json"))
#: After a refusal, one download is tried after each of these waits (s),
#: about 7 hours in all, then it stops.
PROBES = (600, 600, 1200, 1800, 3600, 3600, 7200, 7200)
#: The cap is this share of the fewest downloads a refusal came after, and
#: never below CAP_FLOOR.
CAP_SHARE, CAP_FLOOR = 0.9, 50
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
HOST = os.environ.get("GALE_INBOX_HOST", "pt@host.docker.internal")
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "HostKeyAlias=localhost",
       "-i", os.path.expanduser("~/.ssh/host_hatch")]
GALE_ROOT = "/Volumes/Media/Gale crosswords"
INBOX = f"{GALE_ROOT}/Times"
ASIDE = "Set aside"
#: Where each downloaded PDF is kept on the Mac: inside the Times folder,
#: below the inbox's own files, which are all a sweep or mirror looks at.
FETCHED_DIR = f"{INBOX}/Fetched"
CHANNEL = os.environ.get("GALE_FETCH_CHANNEL", "cryptic-crosswords")
DOC = re.compile(r"[A-Z]{2}\d{8,12}", re.IGNORECASE)


class Stop(Exception):
    """Stop the run (and say why). `refused`: an answer Gale's download
    limit may give (run learns from it), with its HTTP `status` and first
    bytes `head`."""

    def __init__(self, why, refused=False, status=None, head=b""):
        super().__init__(why)
        self.refused, self.status, self.head = refused, status, head


class Pacer:
    """When the next download may start. `clock`, `sleep` and `rand` are
    injectable so the test runs it on a fake clock."""

    def __init__(self, clock=time.time, sleep=time.sleep, rand=None, limits=LIMITS):
        self.clock, self.sleep, self.rand = clock, sleep, rand or random.Random()
        self.done = collections.deque()  # start times of the last WINDOW_MAX downloads
        self.last = None  # when the last download ended
        self.session = 0  # downloads since the last rest
        self.limits = limits
        self.cap, self.rests = learned(limits)

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
        return self.cap is not None and self.session >= self.cap

    def rest(self):
        self.sleep(self.rand.uniform(*self.rests))
        self.session = 0
        self.last = self.clock()

    def relearn(self):
        self.cap, self.rests = learned(self.limits)


def learned(path=LIMITS):
    """(session cap or None, rest range) from the refusals in `path`."""
    kept = load(path)
    after = [r["since_rest"] for r in kept.get("refusals", ())]
    cap = max(CAP_FLOOR, int(CAP_SHARE * min(after))) if after else None
    longest = max((r["waited"] for r in kept.get("recoveries", ())), default=0.0)
    return cap, (max(REST[0], longest), max(REST[1], 1.5 * longest))


def record(path, kind, entry):
    """Append `entry` to list `kind` of `path` (LIMITS), whole or not at all."""
    kept = load(path)
    kept.setdefault(kind, []).append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(kept, indent=1))
    tmp.replace(path)


def recent(fetched, now, seconds):
    """Downloads logged in `fetched` in the `seconds` before `now`."""
    n = 0
    for e in load(fetched).values():
        try:
            n += now - datetime.datetime.fromisoformat(e["at"]).timestamp() <= seconds
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
                raise Stop(f"Gale answered HTTP {e.code} for {url[:80]}", refused=True, status=e.code,
                           head=e.read()[:300]) from e
            raise


def ssh(command, **kw):
    return subprocess.run([*SSH, HOST, command], capture_output=True, check=True, timeout=180, **kw)


def have_docs():
    """The documents already got: named in the inbox, its Set aside folder
    or FETCHED_DIR, or in FETCHED."""
    q = shlex.quote
    names = ssh(f"cd {q(INBOX)} && ls -1 . {q(ASIDE)} {q(FETCHED_DIR)} 2>/dev/null; exit 0", text=True).stdout
    return {m.group(0).upper() for m in DOC.finditer(names)} | set(load(FETCHED))


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
SKIP = int(os.environ.get("GALE_FETCH_SKIP", "0"))


def plan(got, skip=SKIP):
    """[(date, cache entry or None)] to fetch, in next_up order past its
    first `skip` rows: wanted, not staged, set aside or gone from Gale, and
    not a document in `got`. None: not looked up yet (run looks it up)."""
    import dir_cache
    import gale_inbox
    dir_cache.load(gale_inbox.DIR_CACHE)
    rows = gale_inbox.wanted()
    docs = gale_docs.load()
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
    """The cache entry for `day` (gale_docs.lookup), kept in gale_docs.CACHE
    under the sync's lock (the Listener's lookups write the same file)."""
    import gale_inbox
    e = gale_docs.lookup("TTDA", day, gale)
    e["at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    if "doc" not in e:
        e["matcher"] = gale_docs.MATCHER
    with gale_inbox.locked():
        kept = gale_docs.load()
        kept[f"TTDA/{day.isoformat()}"] = e
        gale_inbox.save_json(gale_docs.CACHE, kept)
    return e


def put(body, name):
    """Write `body` into FETCHED_DIR on the Mac as `name` (whole or not at all)."""
    q = shlex.quote
    tmp = f"{FETCHED_DIR}/.{name}.part"
    ssh(f"mkdir -p {q(FETCHED_DIR)} && cat > {q(tmp)} && mv -f {q(tmp)} {q(FETCHED_DIR + '/' + name)}", input=body)


def file_page(body, day, doc, e):
    """Keep the PDF on the Mac and lay it out as `day`'s edition."""
    import gale_inbox
    put(body, f"GALE_{doc}.pdf")
    with gale_inbox.locked():
        gale_inbox.lay_out_fetched(day, doc, body, e)


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
        fetched=FETCHED, text_of=None, skip=SKIP, lookup_of=None, limits=LIMITS, tell=None):
    """Fetch until `limit` downloads, no row left, or a stop. The hooks
    (`fetch(url) -> body`, `store(body, day, doc, entry)`, `plan_of(got)`,
    `got_of()`, `lookup_of(day)`, `fetched`, `limits`, `tell(text)`) stand
    in for Gale, the Mac, the logs and the room in the test. Returns
    (downloads, why it ended); raises Stop to stop."""
    pacer = pacer or Pacer(limits=limits)
    session = None
    in_session = 0  # downloads since the portal session opened

    def real_fetch(url):
        nonlocal session
        session = session or Session()
        return session.open(url)[0]

    def fresh_session():
        nonlocal session, in_session
        session, in_session = None, 0

    fetch = fetch or real_fetch
    store = store or file_page
    plan_of = plan_of or (lambda got: plan(got, skip))
    tell = tell or (lambda text: alert(text, quiet=True))
    gale = None

    def real_lookup(day):
        nonlocal gale
        gale = gale or gale_docs.Gale()
        return look_up(day, gale)

    def recover(refusal, url, day, doc):
        """Record `refusal`, then try one download in a fresh session after
        each of PROBES; the body that came, the wait recorded. Raises Stop
        when none came."""
        now = pacer.clock()
        at = datetime.datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds")
        entry = {"at": at, "session": in_session, "since_rest": pacer.session, "run": n,
                 "last_hour": recent(fetched, now, 3600), "last_day": recent(fetched, now, 86400),
                 "status": refusal.status, "why": str(refusal), "head": refusal.head.decode("utf-8", "replace")}
        record(limits, "refusals", entry)
        pacer.relearn()
        tell(f"Gale refused a download after {pacer.session} since the last rest ({in_session} this portal session,"
             f" {entry['last_hour']} in the last hour): {refusal}. Recorded in {limits}; trying again after"
             f" {PROBES[0] // 60} min and longer waits. Session cap now {pacer.cap}.")
        log(f"refused after {pacer.session} since the last rest: {refusal}")
        for i, wait in enumerate(PROBES, 1):
            pacer.sleep(wait)
            fresh_session()
            try:
                body = pdf_of(fetch, url, day, doc, text_of)
            except Stop as again:
                if not again.refused:
                    raise
                log(f"probe {i}: still refused ({again})")
                continue
            except (urllib.error.URLError, http.client.HTTPException, OSError) as ex:
                log(f"probe {i}: {type(ex).__name__}: {ex}")
                continue
            waited = pacer.clock() - now
            record(limits, "recoveries", {"refused_at": at, "waited": waited, "probes": i})
            pacer.session = 0
            pacer.relearn()
            log(f"Gale works again after {waited / 60:.0f} min; session cap {pacer.cap}, rest"
                f" {pacer.rests[0] / 60:.0f}-{pacer.rests[1] / 60:.0f} min")
            return body
        raise Stop(f"Gale still refused {sum(PROBES) / 3600:.1f} h after a refusal ({refusal})")

    lookup_of = lookup_of or real_lookup
    got_of = got_of or have_docs
    n, errors, idle = 0, 0, 0
    while limit is None or n < limit:
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
            url = gale_docs.download_url("TTDA", day, e)
            if dry:
                log(f"would fetch {day} {doc} {e.get('title', '')}")
                n += 1
                continue
            pacer.wait()
            try:
                try:
                    body = pdf_of(fetch, url, day, doc, text_of)
                except Stop as refusal:
                    if not refusal.refused:
                        raise
                    body = recover(refusal, url, day, doc)
                store(body, day, doc, e)
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
            note(doc, day, f"GALE_{doc}.pdf", fetched)
            n += 1
            in_session += 1
            log(f"{datetime.datetime.now():%H:%M:%S} got {day} {doc} ({len(body):,} bytes) [{n}]")
            if pacer.finished():
                log(f"session cap {pacer.cap} reached; resting before a fresh portal session")
                fresh_session()
                pacer.rest()
        if dry:
            return n, "dry run: one plan shown"
    return n, f"reached --max {limit}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--max", type=int, help="stop after this many downloads")
    ap.add_argument("--skip", type=int, default=SKIP, help=f"pass over this many next-up rows first (default {SKIP})")
    ap.add_argument("--dry-run", action="store_true", help="list what would be fetched")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)
    cap, rests = learned()
    print(f"=== Gale downloads from {datetime.datetime.now():%F %T}: gap {GAP[0]:.0f}-{GAP[1]:.0f}s, "
          f"<= {WINDOW_MAX}/{WINDOW:.0f}s, session cap {cap or 'none until a refusal is seen'}, "
          f"rest {rests[0] / 60:.0f}-{rests[1] / 60:.0f} min, next-up rows from {a.skip + 1} ===")
    try:
        n, why = run(a.max, a.dry_run, skip=a.skip)
    except Stop as e:
        alert(f"{e}. Nothing more is fetched until it is restarted.")
        return 2
    print(f"=== done: {n} downloaded; {why} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
