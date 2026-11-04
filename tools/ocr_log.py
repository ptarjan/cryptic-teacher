#!/usr/bin/env python3
"""The OCR queue's human log: one plain-words line per unit, written from the queue's raw log.

    python3 tools/ocr_log.py --follow RAW_LOG READABLE_LOG [REPO]    seed from RAW_LOG, then follow it
    python3 tools/ocr_log.py --replay RAW_LOG READABLE_LOG [REPO]    rebuild READABLE_LOG from RAW_LOG
    some_command | python3 tools/ocr_log.py READABLE_LOG [REPO]       filter a stream

The edition queue prints everything it does to its raw log (full_pass.log): reasons, spool
counts, reload notes, tracebacks, thousands of lines an hour. This filter reads that stream and
writes only what Paul reads, one line each, every line starting with the clock (HH:MM) of the
queue's own stamps:

    09:41 ✓ Times 1947-05-10: puzzle No 5355 filed as times-5355
    09:42 ✗ Times 1947-04-03: No 5324 read, but 4 answers are still blank, so it was not filed
    09:42 ✗ 14 pages: image reader busy, each page waits its turn (nothing lost)
    09:45 ── 10 units at once · 12 Times filed/h · 3 puzzles updated/h · 41 image-reader asks/10 min · 5 reads queued

Repeats of one kind inside the same minute are one line with a count. A status line is written
every five minutes; REPO is the checkout whose commit history gives "Times filed/h" ("File
times-" commits) and "puzzles updated/h" (the N of "Update N puzzles" commits). Without a REPO
the filed count falls back to the filed lines this filter saw. Raw lines stay in the raw log.

A replay (and the seed of --follow) reads the raw log on the clock its own stamps keep, so a
restart never blanks the readable log. A restart of --follow resumes from the offset kept in
READABLE_LOG.pos after warming its state from the end of the raw log.
"""
import collections
import datetime
import os
import re
import subprocess
import sys
import time

HEARTBEAT_S = 5 * 60       # the status line is written at least this often
IDLE_AFTER_S = 5 * 60      # nothing started this long, nothing running: idle
ASK_WINDOW_S = 10 * 60
RUN_MAX_S = 70 * 60        # a unit with no end line this long is forgotten
ASK_LOG_TAIL = 512 * 1024  # bytes of the reader's call log read for the ask count
ASK_LINE = re.compile(r"^(\d\d):(\d\d):(\d\d) vlm ask ")
DEDUPE_S = 180            # the same result line twice inside this is one
WARM_BYTES = 8 * 1024 * 1024
TS = re.compile(r"^(\d\d):(\d\d):(\d\d) (.*)$")
SLICE = re.compile(r"^=== slice from (\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)")
PAPERS = {"GaleTimes": "Times", "NewsUK": "Times", "GaleFT": "Financial Times",
          "FinancialTimes": "Financial Times", "GaleTelegraph": "Telegraph"}
# (what the raw reason looks like, kind, plain words). First match wins.
REFUSALS = (
    (re.compile(r"no reading parses"), "noparse", "none of its clues could be read"),
    (re.compile(r"the ink under the title is|^no grid"), "nogrid", "no grid was found on the page"),
    (re.compile(r"is not near the|out of date order|already filed for|scan page No|already holds|implies"),
     "number", "its number does not fit its date"),
    (re.compile(r"requested .* but the page served|another puzzle's|served the clues"),
     "wrongpage", "the page shows a different puzzle"),
    (re.compile(r"refusing to write"), "checks", "its answers failed our safety checks"),
    (re.compile(r"crashed"), "crash", "the reader crashed on it"),
    (re.compile(r"no title read|solution headings"), "notitle", "its title could not be read"),
    (re.compile(r"no linked solution grid|answers-only"), "nosolgrid", "no answer grid was found to check it against"),
    (re.compile(r"clues' counts|unread"), "gridunread", "the grid could not be read"),
    (re.compile(r"prints no daily cryptic"), "noprint", None),
)
RETRY = {"crash": " (it will be tried again)"}
PROBLEM = re.compile(r"^ALERT: ")

# kind -> (mark, text for one page, text for several). {who} {n} {k} {nos}: see Log.render.
AGG = {
    "scan": ("✓", "{who} checked, {k}", "{n} pages checked, {k}"),
    "held": ("✓", "{who}: puzzle already on file, nothing new", "{n} puzzles already on file, nothing new"),
    "nofile": ("✗", "{who}: read, but no puzzle came out of it",
               "{n} pages read, but no puzzle came out of them"),
    "ask": ("✗", "{who}: partly read, {k} sent to the image reader, it finishes when the reader answers (nothing lost)",
            "{n} pages partly read, {k} sent to the image reader, they finish when it answers (nothing lost)"),
    "busy": ("✗", "{who}: image reader busy, page waits its turn (nothing lost)",
             "{n} pages: image reader busy, each page waits its turn (nothing lost)"),
    "down": ("✗", "{who}: image reader unreachable, page waits until it is back (nothing lost)",
             "{n} pages: image reader unreachable, they wait until it is back (nothing lost)"),
    "game": ("✗", "{who}: stopped for a game, page waits (nothing lost)",
             "{n} pages stopped for a game, they wait (nothing lost)"),
    "recheck": ("✓", "{who} re-checked", "{n} filed puzzles re-checked"),
    "fetched": ("✓", "{who} downloaded", "{n} editions downloaded"),
    "stopped": ("✗", "{who}: stopped unexpectedly, will be tried again (nothing lost)",
                "{n} pages stopped unexpectedly, they will be tried again (nothing lost)"),
    "toolong": ("✗", "{who}: took too long and was stopped, left for the next run (nothing lost)",
                "{n} pages took too long and were stopped, left for the next run (nothing lost)"),
}


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def clip(text, n=150):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def stamp(t):
    return datetime.datetime.fromtimestamp(t).strftime("%H:%M")


def pretty(unit):
    """A unit's raw name in words: the paper and the date."""
    m = re.match(r"([A-Za-z]+?)\d{4}UKEnglish/(\d{4}-\d\d-\d\d)", unit)
    if m:
        return f"{PAPERS.get(m.group(1), m.group(1))} {m.group(2)}"
    m = re.match(r"per_times_the-times_(\d{4}-\d\d-\d\d)", unit)
    if m:
        return f"Times {m.group(1)}"
    if unit.isdigit():
        return f"article {unit}"
    m = re.match(r"(?:GALE_)?([A-Z]{2}\w*?)(\w{6})\.pdf$", unit)
    if m or unit.endswith(".pdf"):
        return "Gale file " + (m.group(2) if m else unit[-12:-4])
    return clip(unit, 40)


class Log:
    """Raw queue lines in, human lines out (returned, so a test can read them)."""

    def __init__(self, repo=None, day=None, ask_log=None):
        self.repo = repo                  # checkout whose commits count filed and updated
        self.ask_log = ask_log            # the image reader's own call log (UTC clock): the live ask count
        self.day0 = datetime.datetime.combine(day or datetime.date.today(), datetime.time()).timestamp()
        self.t = None                     # the log's clock, seconds
        self.last_wall = None
        self.running = {}                 # (kind, unit) -> when it started
        self.last_start = None
        self.paused = False
        self.queued = 0
        self.asks = collections.deque()   # (time, asks sent to the image reader)
        self.filed = collections.deque()  # times of filed lines seen (the fallback count)
        self.agg = {}                     # kind -> record, one per minute
        self.seen = {}                    # result text -> when last (duplicates)
        self.said = {}                    # throttled one-line notices -> when last
        self.status_at = None
        self.git_cache = (None, None)

    # -- clock -----------------------------------------------------------
    def set_clock(self, h, m, s):
        cand = self.day0 + h * 3600 + m * 60 + s
        if self.t is not None and cand < self.t - 12 * 3600:
            self.day0 += 86400
            cand += 86400
        self.t = cand

    def advance(self, wall):
        """Live: the clock keeps moving between lines."""
        if wall is not None:
            if self.t is not None and self.last_wall is not None:
                self.t += max(0.0, wall - self.last_wall)
            self.last_wall = wall

    # -- output ----------------------------------------------------------
    def out(self, mark, text, t=None):
        return f"{stamp(self.t if t is None else t)} {mark} {text}"

    def add(self, kind, unit=None, k=0, no=None):
        rec = self.agg.get(kind)
        if rec is None:
            rec = self.agg[kind] = {"min": int(self.t // 60), "t": self.t, "n": 0, "units": [], "k": 0, "nos": []}
        rec["n"] += 1
        rec["k"] += k
        if unit and len(rec["units"]) < 3:
            rec["units"].append(unit)
        if no:
            rec["nos"].append(no)

    def render(self, kind, rec):
        mark, one, many = AGG[kind]
        n, k = rec["n"], rec["k"]
        who = pretty(rec["units"][0]) if rec["units"] else "page"
        if kind == "scan":
            k = (f"{plural(k, 'puzzle')} found" if n > 1 else
                 f"{plural(k, 'puzzle')} found on it" if k else "no puzzle on it")
        elif kind == "ask":
            k = plural(k, "question")
        return self.out(mark, (one if n == 1 else many).format(who=who, n=n, k=k), rec["t"])

    def flush(self, upto_min=None):
        """The pending one-per-minute lines whose minute is over (all of them when upto_min is None)."""
        out = []
        for kind in list(self.agg):
            rec = self.agg[kind]
            if upto_min is None or rec["min"] < upto_min:
                out.append((rec["t"], self.render(kind, rec)))
                del self.agg[kind]
        return [text for _, text in sorted(out, key=lambda x: x[0])]

    def refused(self, kind, why, unit, no):
        """A page whose puzzle was not filed: one line per kind per minute, saying what is missing."""
        rec_key = "no:" + kind
        if rec_key not in AGG:
            if why is None:
                AGG[rec_key] = ("✓", "{who}: no cryptic is printed that day", "{n} days with no cryptic printed")
            else:
                suffix = RETRY.get(kind, "")
                AGG[rec_key] = ("✗", "{who}: " + why + ", so it was not filed (still missing)" + suffix,
                                "{n} puzzles not filed: " + why + " (still missing)" + suffix)
        self.add(rec_key, unit, no=no)

    # -- status ----------------------------------------------------------
    def git_counts(self, t):
        """(Times filed, puzzles updated) in the hour before t, from the commit history; None if unknown."""
        if not self.repo:
            return None
        if self.git_cache[0] is not None and abs(t - self.git_cache[0]) < 60:
            return self.git_cache[1]
        try:
            # Filter by commit time here, not with --since: git stops walking at the first commit older
            # than --since, so a back-dated or rebased tip hides every commit behind it.
            res = subprocess.run(["git", "-C", self.repo, "log", "-n", "5000", "--format=%ct %s"],
                                 capture_output=True, text=True, timeout=30, check=True)
            filed = updated = 0
            for row in res.stdout.splitlines():
                when, _, subject = row.partition(" ")
                if not t - 3600 <= int(when) <= t:
                    continue
                if subject.startswith("File times-"):
                    filed += 1
                m = re.match(r"^Update (\d+) puzzles", subject)
                if m:
                    updated += int(m.group(1))
                elif re.match(r"^Update [a-z]+-\d+$", subject):
                    updated += 1        # the queue's single-puzzle commit, "Update times-727"
            counts = (filed, updated)
        except (OSError, ValueError, subprocess.SubprocessError):
            counts = None
        self.git_cache = (t, counts)
        return counts

    def ask_count(self):
        """Asks the image reader answered in the last ASK_WINDOW_S. Live, that is the reader's own call log
        (one line per real server call); the queue's "N asks spooled" lines count only the asks a read
        queued the moment it was deferred, a small part of what the reader then works through."""
        if self.ask_log and self.last_wall is not None:
            try:
                with open(self.ask_log, "rb") as fh:
                    fh.seek(0, os.SEEK_END)
                    size = fh.tell()
                    fh.seek(max(0, size - ASK_LOG_TAIL))
                    lines = fh.read().decode("utf-8", "replace").splitlines()
            except OSError:
                lines = None
            if lines is not None:
                now = datetime.datetime.fromtimestamp(self.t, datetime.timezone.utc)
                now_s = now.hour * 3600 + now.minute * 60 + now.second
                n = 0
                for row in lines:
                    m = ASK_LINE.match(row)
                    # the log has no date: a line's age is the clock difference, wrapped over midnight
                    if m and (now_s - int(m.group(1)) * 3600 - int(m.group(2)) * 60 - int(m.group(3))) % 86400 <= ASK_WINDOW_S:
                        n += 1
                return n
        return sum(a for _, a in self.asks)

    def status(self, force=False):
        if self.t is None:
            return []
        if self.status_at is None and not force:
            self.status_at = self.t         # the first status comes one heartbeat after the first line
            return []
        if not force and self.t - self.status_at < HEARTBEAT_S:
            return []
        self.status_at = self.t
        for key in [k for k, t0 in self.running.items() if t0 < self.t - RUN_MAX_S]:
            del self.running[key]
        while self.filed and self.filed[0] < self.t - 3600:
            self.filed.popleft()
        while self.asks and self.asks[0][0] < self.t - ASK_WINDOW_S:
            self.asks.popleft()
        counts = self.git_counts(self.t)
        filed, updated = counts if counts else (len(self.filed), "–")
        n = len(self.running)
        parts = [f"{n} unit{'' if n == 1 else 's'} at once", f"{filed} Times filed/h",
                 f"{updated} puzzles updated/h", f"{self.ask_count()} image-reader asks/10 min",
                 f"{self.queued} reads queued"]
        if self.paused:
            parts.append("paused for a game")
        elif n == 0 and (self.last_start is None or self.t - self.last_start >= IDLE_AFTER_S):
            parts.append("idle")
        return [self.out("──", " · ".join(parts))]

    def notice(self, key, text, every=600):
        if self.t - self.said.get(key, -1e18) < every:
            return []
        self.said[key] = self.t
        return [self.out("──", text)]

    # -- lines -----------------------------------------------------------
    def feed(self, line, wall=None):
        line = line.rstrip("\n")
        self.advance(wall)
        if not line or line[0] == " " or line.startswith(("vlm_reader:", "Traceback", "File ")):
            return self.tick_out()
        m = TS.match(line) if line[0].isdigit() else None
        if m:
            self.set_clock(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            body = m.group(4)
        else:
            s = SLICE.match(line)
            if s:
                g = [int(x) for x in s.groups()]
                self.t = datetime.datetime(*g).timestamp()
                self.day0 = datetime.datetime(g[0], g[1], g[2]).timestamp()
                return self.tick_out()
            body = line
        if self.t is None:
            return []
        return self.flush(int(self.t // 60)) + self.handle(body) + self.tick_out(flushed=True)

    def tick(self, wall):
        """No line arrived: let the clock, the minute's pending lines and the status move on."""
        self.advance(wall)
        return self.tick_out()

    def tick_out(self, flushed=False):
        if self.t is None:
            return []
        return ([] if flushed else self.flush(int(self.t // 60))) + self.status()

    def once(self, text):
        """True the first time this result text is seen in DEDUPE_S (the queue prints some twice)."""
        if self.t - self.seen.get(text, -1e18) < DEDUPE_S:
            return False
        self.seen[text] = self.t
        if len(self.seen) > 5000:
            self.seen = {k: v for k, v in self.seen.items() if v > self.t - DEDUPE_S}
        return True

    def handle(self, body):
        head = body.split(" ", 1)[0]
        if head == "start":
            m = re.match(r"^start (read|scan|fetch) (.+?)(?: \(|$)", body)
            if m:
                self.running[(m.group(1), m.group(2))] = self.t
                self.last_start = self.t
            return []
        if head == "end":
            m = re.match(r"^end (read|scan|fetch) (.+?)(?: \(\w+\))?: (done|deferred|failed|ended|busy)\b(.*)$", body)
            if not m:
                return []
            kind, unit, how, rest = m.groups()
            self.running.pop((kind, unit.split(" (")[0]), None)
            if how == "failed" and self.once(body[:80] + unit):
                self.add("stopped", unit)
            elif how == "done" and kind == "fetch" and self.once("fetched " + unit):
                self.add("fetched", unit)
            return []
        if head == "read":
            return self.read_line(body)
        if head == "scanned":
            m = re.match(r"^scanned (\S+): (\d+) puzzle\(s\)", body)
            if m and self.once(body):
                self.add("scan", m.group(1), k=int(m.group(2)))
            return []
        if head == "answers-only":
            m = re.match(r"^answers-only cpu (\d{4}-\d\d-\d\d) No (\d+):", body)
            if m:
                self.add("recheck", f"Times {m.group(1)} No {m.group(2)}")
            return []
        if head == "failed":
            m = re.match(r"^failed (\S+): (\w+)", body)
            if m:
                kind = "err:" + m.group(2)
                if kind not in AGG:
                    AGG[kind] = ("✗", "{who}: the program hit an error (" + m.group(2) + "), page will be tried again (nothing lost)",
                                 "{n} pages hit a program error (" + m.group(2) + "), they will be tried again (nothing lost)")
                self.add(kind, m.group(1))
            return []
        if head == "desktop":
            if "yielding: game" in body and not self.paused:
                self.paused = True
                return [self.out("──", "paused: a game is running, image work waits until it ends")]
            if "resuming" in body and self.paused:
                self.paused = False
                return [self.out("──", "resumed: the game is over, image work goes on")]
            return []
        if head == "desktop-bound:":
            if "yielding" in body and not self.paused:
                self.paused = True
                return [self.out("──", "paused: a game is running, image work waits until it ends")]
            return []
        if head == "vlm":
            m = re.match(r"^vlm stage: \d+ asks spooled, (\d+) reads waiting", body)
            if m:
                self.queued = int(m.group(1))
            return []
        if head == "VLM":
            m = re.match(r"^VLM down \(unreachable\): (\d+) scans? deferred", body)
            if m:
                return self.notice("vlmdown", f"image reader unreachable: {plural(int(m.group(1)), 'page')} wait until it is back "
                                              "(nothing lost; other work goes on)")
            return []
        if head == "code":
            m = re.match(r"^code changed .*; re-exec, (\d+) running", body)
            if m:
                return [self.out("──", f"queue restarting on new code, {plural(int(m.group(1)), 'unit')} carried on")]
            return []
        if head == "reload:":
            m = re.search(r"no unit starts, (\d+) running are handed to the next run", body)
            if m:
                return [self.out("──", f"queue reloading on new code, {plural(int(m.group(1)), 'unit')} handed on")]
            return []
        if head == "started" and body.startswith("started from the last plan"):
            return [self.out("──", "queue back up after a reload")]
        if head.endswith(".pdf:"):
            m = re.match(r"^(\S+): No (\d+) \([^)]*\), (?:(\d+)/(\d+) clues read|no reading parses)", body)
            if m and self.once(body[:70]):
                if m.group(3):
                    k = f"only {m.group(3)} of {m.group(4)} clues could be read, the rest are missing"
                else:
                    k = "none of its clues could be read, so it was not filed"
                return [self.out("✗", f"{pretty(m.group(1))} (No {m.group(2)}): {k}")]
            return []
        if body.startswith("ALERT: ") and PROBLEM.search(body):
            text = clip(body[7:], 200)
            if self.t - self.said.get(text, -1e18) >= 6 * 3600:
                self.said[text] = self.t
                return [self.out("⚠️", text)]
        return []

    def read_line(self, body):
        m = re.match(r"^read (\S+) ran past ([\d.]+)s; killed", body)
        if m:
            if self.once(body[:90]):
                self.add("toolong", m.group(1))
            return []
        m = re.match(r"^read (\S+): (.*)$", body)
        if not m:
            return []
        unit, rest = m.groups()
        if rest.startswith("deferred"):
            if not self.once(body[:120]):
                return []
            a = re.match(r"^deferred, (\d+) VLM asks spooled", rest)
            if a:
                self.asks.append((self.t, int(a.group(1))))
                self.add("ask", unit, k=int(a.group(1)))
            elif "VLM is down" in rest:
                self.add("down", unit)
            elif "game" in rest:
                self.add("game", unit)
            else:
                self.add("busy", unit)
            return []
        if not self.once(body[:150]):
            return []
        rest = re.sub(r" \(vlm [^)]*\)$", "", rest)
        if rest.startswith("nothing filed"):
            self.add("nofile", unit)
            return []
        out = []
        for part in re.split(r"; (?=\d+ )", rest):
            pm = re.match(r"^(\d+) (.*)$", part)
            no, what = (pm.group(1), pm.group(2)) if pm else (None, part)
            w = re.match(r"^(?:wrote )?(\S+-\d+)(?: \(incomplete: (\d+) blank, unfiled\))?$", what)
            if w or what == "read":
                if w and w.group(2):
                    out.append(self.out("✗", f"{pretty(unit)}: No {no} read, but {plural(int(w.group(2)), 'answer')} "
                                             "are still blank, so it was not filed (still missing)"))
                elif w:
                    self.filed.append(self.t)
                    out.append(self.out("✓", f"{pretty(unit)}: puzzle No {no} filed"))
                else:
                    out.append(self.out("✓", f"{pretty(unit)}: puzzle No {no} read"))
                continue
            if what.startswith("already held"):
                self.add("held", unit)
                continue
            for pat, kind, why in REFUSALS:
                if pat.search(what):
                    self.refused(kind, why, unit, no)
                    break
            else:
                self.refused("other", "the queue refused it (reason in the full log)", unit, no)
        return out


def feed_all(log, lines, sink):
    for raw in lines:
        sink(log.feed(raw))


def open_lines(path, start, stop):
    """Complete lines of path between two byte offsets, with the offset after each."""
    with open(path, "rb") as fh:
        fh.seek(start)
        pos = start
        while stop is None or pos < stop:
            raw = fh.readline()
            if not raw.endswith(b"\n"):
                break
            pos += len(raw)
            yield raw.decode("utf-8", "replace"), pos


def replay(raw_path, out_path, repo=None):
    """Rebuild out_path from raw_path (atomically: a reader never sees it half-written)."""
    log = Log(repo)
    tmp = out_path + ".tmp"
    with open(tmp, "w") as out:
        out.write("── OCR queue log: one line per unit; full detail in the raw queue log\n")
        n = 0
        for raw, _ in open_lines(raw_path, 0, os.path.getsize(raw_path)):
            out.writelines(text + "\n" for text in log.feed(raw))
            n += 1
        out.writelines(text + "\n" for text in log.flush())
    os.replace(tmp, out_path)
    print(f"replayed {n} lines from {raw_path}", file=sys.stderr)
    return 0


def ask_log_path():
    """Where vlm_reader writes one line per real server call (CT_VLM_ASK_LOG overrides)."""
    return os.environ.get("CT_VLM_ASK_LOG") or os.path.expanduser("~/.cache/corpus_queue/vlm_asks.log")


def follow(raw_path, out_path, repo=None, poll=1.0):
    log = Log(repo, ask_log=ask_log_path())
    pos_path = out_path + ".pos"
    try:
        with open(pos_path) as fh:
            pos = int(fh.read().strip())
        resume = os.path.getsize(out_path) > 0
    except (OSError, ValueError):
        pos, resume = 0, False
    with open(out_path, "a", buffering=1) as out:
        def save(p):
            with open(pos_path, "w") as fh:
                fh.write(str(p))
        while not os.path.exists(raw_path):
            time.sleep(poll)
        size = os.path.getsize(raw_path)
        if resume and pos <= size:
            for raw, _ in open_lines(raw_path, max(0, pos - WARM_BYTES), pos):
                log.feed(raw)       # warms the state; what it would say was said before
            log.agg.clear()
            log.status_at = log.t
        else:
            if os.path.getsize(out_path) == 0:
                out.write("── OCR queue log: one line per unit; full detail in the raw queue log\n")
            pos = 0
            for raw, p in open_lines(raw_path, 0, size):
                out.writelines(text + "\n" for text in log.feed(raw))
                pos = p
            save(pos)
        ino = os.stat(raw_path).st_ino
        while True:
            try:
                st = os.stat(raw_path)
            except OSError:
                time.sleep(poll)
                continue
            if st.st_ino != ino or st.st_size < pos:      # rotated or truncated: start the new file
                ino, pos = st.st_ino, 0
            moved = False
            try:
                for raw, p in open_lines(raw_path, pos, None):
                    out.writelines(text + "\n" for text in log.feed(raw, time.time()))
                    pos, moved = p, True
            except OSError:
                time.sleep(poll)
                continue
            if moved:
                save(pos)
            else:
                out.writelines(text + "\n" for text in log.tick(time.time()))
            time.sleep(poll)


def stream(out_path, repo=None):
    import queue
    import threading
    log = Log(repo, ask_log=ask_log_path())
    lines = queue.Queue()

    def reader():
        for raw in sys.stdin:
            lines.put(raw)
        lines.put(None)
    threading.Thread(target=reader, daemon=True).start()
    with open(out_path, "a", buffering=1) as out:
        while True:
            try:
                raw = lines.get(timeout=30)
            except queue.Empty:
                out.writelines(text + "\n" for text in log.tick(time.time()))
                continue
            if raw is None:
                out.writelines(text + "\n" for text in log.flush())
                return 0
            out.writelines(text + "\n" for text in log.feed(raw, time.time()))


def main(argv):
    if len(argv) >= 4 and argv[1] == "--follow":
        return follow(argv[2], argv[3], argv[4] if len(argv) > 4 else None)
    if len(argv) >= 4 and argv[1] == "--replay":
        return replay(argv[2], argv[3], argv[4] if len(argv) > 4 else None)
    if len(argv) >= 2 and not argv[1].startswith("--"):
        return stream(argv[1], argv[2] if len(argv) > 2 else None)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
