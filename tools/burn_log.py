#!/usr/bin/env python3
"""The burn's human log: .prereset.log, written from the burn's full output.

    tools/prereset_backfill.sh | python3 tools/burn_log.py .prereset.log

The burn prints everything it does to .prereset.debug.log (loss checks, push
batching, syncs, ledger, backlog lists, pool checkpoints, planner inputs). This
filter reads that same stream and writes only what Paul reads, one line each,
every line starting with the Alberta time (HH:MM):

    09:41 ✓ azed-2702 hints written
    09:42 ✗ everyman-3470 gave up: 1-down MUNTJAC has no clean parse — skipped until the puzzle changes
    09:45 ── 15 at once (limit: memory) · 93 done last hour · week 98% used, resets in 19h
    09:50 ⚠️ push failed: ...

A puzzle line is written when the puzzle ends, in plain words; a status line when
the width or its limit changes (and at most every 15 minutes otherwise, when
puzzles ended since); a ⚠️ line for a real problem. Anything else is not here.
"""
import collections
import datetime
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

ABT = ZoneInfo("America/Edmonton")
HEARTBEAT_S = 5 * 60       # the status line is written at least this often
IDLE_AFTER_S = 5 * 60      # nothing queued this long before the log says "idle"
FILL_WINDOW_S = 120        # starts this close together are one pool fill
DONE_KINDS = re.compile(r"^(Annotate|Backfill|Re-check)\b")
PUZZLE = r"([a-z][a-z0-9]*-\d+)"
CAP_ORDER = ("load", "cpu", "memory", "quota pace")  # which cap is named when several tie
PROBLEM = re.compile(
    r"^ERROR|Traceback \(most recent|could not push|push (failed|refused)|push_puzzle_commit.*(failed|rejected|conflict)"
    r"|lost track of its runs|cannot authenticate|^ALERT: |CI (is )?red")
GAVE_UP = re.compile(r"^  \[" + PUZZLE + r"\] (.*(?:solve rejected|rejected|discard|held|gave up|cannot be|could not be).*)$")
KINDS = (  # commit-message prefix -> what was done
    (re.compile(r"^Annotate\b"), "hints written"),
    (re.compile(r"^Re-check against its blog"), "re-checked against its blog"),
    (re.compile(r"^Backfill (\S+)"), lambda m: f"backfilled {m.group(1)}"),
)


def clip(text, n=150):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def stamp(now):
    return datetime.datetime.fromtimestamp(now, ABT).strftime("%H:%M")


class Log:
    """Raw burn lines in, human lines out (returned, so a test can read them)."""

    def __init__(self, repo=None):
        self.repo = repo          # the burn's worktree: its commits are the done count
        self.done_cache = (0.0, 0)
        self.queued = None
        self.nothing_since = None
        self.next_work = None     # (name, ids) of the backlog line last seen
        self.fill = []            # ids started in the pool fill being gathered
        self.fill_at = 0.0
        self.restart = None
        self.width = None
        self.limit = None
        self.week = None          # (percent used, hours to reset)
        self.done = collections.deque()  # times of the last hour's finished puzzles
        self.said_status = (None, None)
        self.status_at = 0.0
        self.outcomes_since = 0
        self.idle = False
        self.problems = {}        # text -> when last said

    def out(self, now, mark, text):
        return f"{stamp(now)} {mark} {text}"

    def finished(self, now, ok):
        self.outcomes_since += 1
        if ok:
            self.done.append(now)

    def last_hour(self, now):
        """Puzzles committed in the last hour, from the burn's own commit history (a restart
        loses nothing); the lines this filter saw are the fallback."""
        while self.done and self.done[0] < now - 3600:
            self.done.popleft()
        if self.repo and now - self.done_cache[0] >= 60:
            try:
                import subprocess
                res = subprocess.run(["git", "-C", self.repo, "log", "--since=1 hour ago", "--format=%s"],
                                     capture_output=True, text=True, timeout=20, check=True)
                self.done_cache = (now, sum(bool(DONE_KINDS.match(x)) for x in res.stdout.splitlines()))
            except (OSError, ValueError, subprocess.SubprocessError):
                self.done_cache = (now, -1)
        return self.done_cache[1] if self.done_cache[1] >= 0 and self.repo else len(self.done)

    def status(self, now, force=False):
        """The full status line, whenever the width or its limit changed, five minutes passed,
        or the caller forces it (after a restart, a "next:" or an "idle:" line)."""
        if self.width is None or self.restart:  # a restart says its own status first
            return []
        changed = (self.width, self.limit) != self.said_status
        if not (changed or force or now - self.status_at >= HEARTBEAT_S):
            return []
        self.said_status, self.status_at = (self.width, self.limit), now
        week = f"weekly {self.week[0]:g}% used" if self.week else None
        if self.width == 0:
            if self.week and self.week[0] >= 99:
                return [self.out(now, "──", f"paused: {week}, resets in {self.week[1]:.0f}h")]
            return [self.out(now, "──", "waiting: nothing may start right now" + (f" · {week}" if week else ""))]
        parts = [f"{self.width} at once" + (f" ({self.limit})" if self.limit else ""),
                 f"{self.last_hour(now)} done/h"]
        if self.queued is not None:
            parts.append(f"{self.queued} queued")
        if week:
            parts.append(week)
        return [self.out(now, "──", " · ".join(parts))]

    def flush_fill(self, now, force=False):
        """One ▶ line for a pool fill (three or more runs started within FILL_WINDOW_S)."""
        if not self.fill or not (force or now - self.fill_at >= FILL_WINDOW_S):
            return []
        ids, self.fill = self.fill, []
        if len(ids) < 3:
            return []
        more = f", … (+{len(ids) - 3})" if len(ids) > 3 else ""
        return [self.out(self.fill_at, "▶", f"started {len(ids)}: {', '.join(ids[:3])}{more}")]

    def feed(self, line, now=None):
        now = time.time() if now is None else now
        line = line.rstrip("\n")
        m = re.match(r"^  \[" + PUZZLE + r"\] started", line)
        if m:
            if not self.fill:
                self.fill_at = now
            self.fill.append(m.group(1))
            return self.flush_fill(now)
        return self.flush_fill(now) + self.handle(line, now) + self.idle_check(now)

    def idle_check(self, now):
        """"idle" only once nothing has been queued for IDLE_AFTER_S: the pool also shows an
        empty queue for a moment between two backlogs."""
        if self.nothing_since is None or self.idle or now - self.nothing_since < IDLE_AFTER_S:
            return []
        self.idle = True
        return [self.out(now, "──", "idle: nothing queued")] + self.status(now, force=True)

    def handle(self, line, now):
        m = re.match(r"^width (\d+) \(cap: ([^)]*)\)(?: · (.*))?$", line)
        if m:
            caps = {}
            for part in m.group(2).split(", "):
                name, _, val = part.rpartition(" ")
                caps[name] = int(val) if val.isdigit() else None
            self.width = int(m.group(1))
            self.limit = next((n for n in CAP_ORDER if caps.get(n) == self.width), None)
            if self.limit == "quota pace":
                self.limit = "usage pace"
            w = re.search(r"weekly ([\d.]+)% now, ([\d.]+)h to its reset", m.group(3) or "")
            if w:
                self.week = (float(w.group(1)), float(w.group(2)))
            self.idle = False
            return self.status(now)
        m = re.match(r"^weekly (\d+)% -> (\d+)%", line.strip())
        if m and self.week:
            self.week = (float(m.group(2)), self.week[1])
            return []
        m = re.match(r"^--- pool of \d+: (\d+) in flight \(\d+ running\), (\d+) queued", line)
        if m:
            self.queued = int(m.group(2))
            if m.group(1) == "0" and self.queued == 0:
                self.nothing_since = self.nothing_since or now
                return self.status(now)
            self.nothing_since, self.idle = None, False
            if self.next_work:
                name, self.next_work = self.next_work[0], None
                return [self.out(now, "──", f"next: {name}, {self.queued} queued")] + self.status(now, force=True)
            return self.status(now)
        m = re.match(r"^(\S+) backlog: (.*)$", line)
        if m:
            self.next_work = (m.group(1), m.group(2).split())
            return []
        if line.startswith("  not a backfill"):
            self.next_work = None
            return []
        m = re.match(r"^=== pre-reset backfill re-execed onto (\w+)", line)
        if m:
            self.restart = m.group(1)
            return []
        m = re.match(r"^adopted (\d+) runs in flight", line)
        if m and self.restart:
            sha, self.restart = self.restart, None
            self.said_status = (None, None)  # the next width line, or the one known, restates it
            return [self.out(now, "──", f"restarted on {sha}, {m.group(1)} runs carried on")] + self.status(now, force=True)
        m = re.match(r"^committed (.*)$", line)
        if m:
            msg = m.group(1)
            ids = re.findall(PUZZLE, msg)
            if not ids:
                return []
            what = msg
            for rx, kind in KINDS:
                k = rx.match(msg)
                if k:
                    what = kind(k) if callable(kind) else kind
                    break
            self.finished(now, True)
            return [self.out(now, "✓", f"{ids[-1]} {what}")]
        m = re.match(r"^  \[" + PUZZLE + r"\] skipped: already fully hinted", line)
        if m:
            self.finished(now, True)
            return [self.out(now, "✓", f"{m.group(1)} already hinted, nothing to change")]
        m = re.match(r"^  \[" + PUZZLE + r"\] the run withdrew its own work, so nothing it wrote ships — (.*)$", line)
        if m:
            self.finished(now, False)
            return [self.out(now, "✗", f"{m.group(1)} gave up: {clip(m.group(2))} — skipped until the puzzle changes")]
        m = re.match(r"^  \[" + PUZZLE + r"\] (transient failure) — its conversation is kept", line)
        if m:
            self.finished(now, False)
            return [self.out(now, "✗", f"{m.group(1)} cut off (limit or crash), will resume")]
        m = re.match(r"^  \[" + PUZZLE + r"\] failed with the weekly meter below", line)
        if m:
            self.finished(now, False)
            return [self.out(now, "✗", f"{m.group(1)} stopped by the usage limit, dropped for this run")]
        m = GAVE_UP.match(line)
        if m:
            self.finished(now, False)
            return [self.out(now, "✗", f"{m.group(1)} {clip(m.group(2))}")]
        if re.match(r"^(deadline reached|paused \()", line):
            return [self.out(now, "──", f"stopping: {clip(line)}")]
        if PROBLEM.search(line):
            text = clip(line.removeprefix("ALERT: "), 200)
            if now - self.problems.get(text, 0) < HEARTBEAT_S:
                return []
            self.problems[text] = now
            return [self.out(now, "⚠️", text)]
        return []


def main(argv):
    path = argv[1]
    log = Log(argv[2] if len(argv) > 2 else None)
    fresh = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", buffering=1) as out:
        if fresh:
            out.write(f"{stamp(time.time())} ── burn log (Alberta time); full detail in .prereset.debug.log\n")
        for raw in sys.stdin:
            out.writelines(text + "\n" for text in log.feed(raw))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
