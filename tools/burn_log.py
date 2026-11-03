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
HEARTBEAT_S = 15 * 60
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

    def __init__(self):
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
        while self.done and self.done[0] < now - 3600:
            self.done.popleft()
        return len(self.done)

    def status(self, now, force=False):
        """The width line, when the width or its limit changed or the heartbeat is due."""
        if self.width is None:
            return []
        changed = (self.width, self.limit) != self.said_status
        due = self.outcomes_since and now - self.status_at >= HEARTBEAT_S
        if not (changed or due or force):
            return []
        self.said_status, self.status_at, self.outcomes_since = (self.width, self.limit), now, 0
        week = ""
        if self.week:
            week = f"week {self.week[0]:g}% used, resets in {self.week[1]:.0f}h"
        if self.width == 0:
            if self.week and self.week[0] >= 99:
                return [self.out(now, "──", f"paused: {week}")]
            return [self.out(now, "──", "waiting: nothing may start right now" + (f" · {week}" if week else ""))]
        parts = [f"{self.width} at once" + (f" (limit: {self.limit})" if self.limit else ""),
                 f"{self.last_hour(now)} done last hour"]
        if week:
            parts.append(week)
        return [self.out(now, "──", " · ".join(parts))]

    def feed(self, line, now=None):
        now = time.time() if now is None else now
        line = line.rstrip("\n")
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
            nothing = m.group(1) == "0" and m.group(2) == "0"
            if nothing and not self.idle:
                self.idle = True
                return [self.out(now, "──", "idle: nothing queued")]
            if not nothing:
                self.idle = False
            return self.status(now)
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
    log = Log()
    fresh = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", buffering=1) as out:
        if fresh:
            out.write(f"{stamp(time.time())} ── burn log (Alberta time); full detail in .prereset.debug.log\n")
        for raw in sys.stdin:
            out.writelines(text + "\n" for text in log.feed(raw))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
