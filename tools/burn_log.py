#!/usr/bin/env python3
"""The burn's human log: .prereset.log, written from the burn's full output.

    tools/prereset_backfill.sh | python3 tools/burn_log.py .prereset.log

The burn prints everything it does to .prereset.debug.log (loss checks, push
batching, syncs, ledger, backlog lists, pool checkpoints, planner inputs). This
filter reads that same stream and writes only what Paul reads, one line each,
every line starting with the Alberta time (HH:MM):

    09:41 ✓ azed-2702 wrote hints
    09:42 ✗ everyman-3470 gave up: 1-down MUNTJAC has no clean parse — skipped until the puzzle changes
    09:45 ── 15 at once (limit: memory) · 93 done last hour · week 98% used, resets in 19h
    09:50 ⚠️ push failed: ...

A puzzle line is written when the puzzle ends, in plain words; a status line when
the width or its limit changes (and at most every 15 minutes otherwise, when
puzzles ended since); a ⚠️ line for a real problem. Anything else is not here.
"""
import collections
import contextlib
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

ABT = ZoneInfo("America/Edmonton")
HEARTBEAT_S = 5 * 60       # the status line is written at least this often
IDLE_AFTER_S = 5 * 60      # nothing queued this long before the log says "idle"
FILL_WINDOW_S = 120        # starts this close together are one pool fill
DONE_KINDS = re.compile(r"^(Annotate|Backfill|Re-check)\b")
BAG_COUNT = re.compile(r"\b(\d+) puzzles\b")
PUZZLE = r"([a-z][a-z0-9]*-\d+)"


def puzzles_in(subject):
    """How many puzzles one burn commit finished: a bag's commit names its count
    ("Re-check against its blog: 12 puzzles", "Backfill x for 16 puzzles"), any other is one."""
    if not DONE_KINDS.match(subject):
        return 0
    m = BAG_COUNT.search(subject)
    return int(m.group(1)) if m else 1
CAP_ORDER = ("load", "cpu", "memory", "quota pace")  # which cap is named when several tie
PROBLEM = re.compile(
    r"^ERROR|Traceback \(most recent|could not push|push (failed|refused)|push_puzzle_commit.*(failed|rejected|conflict)"
    r"|lost track of its runs|cannot authenticate|^ALERT: |CI (is )?red|\bKilled\b|timed out|terminated by signal")
WASTE_SHARE = 0.15         # ⚠️ when more than this share of the last hour's finished puzzles changed nothing
WASTE_MIN = 20             # ... out of at least this many
SHORT_S = 15 * 60          # far fewer runs than the width, or behind pace, this long is a problem
# ⚠️ above this many tokens per clue written in the last hour. Weighted (TokenIndex: cache reads at 0.1,
# so a bag's turns show): a finished 30-clue blog bag measured ~12k a clue, 18k when it hit its turn cap
# (11-03, 53 bags; 3-4k before cache reads were counted); a session per puzzle is several times that.
TOKENS_PER_CLUE_MAX = 30_000
TOKENS_MIN_CLUES = 5
COST_FACTOR = 2.0          # ⚠️ when meter points per clue written pass this x the trailing average
WAKE_EVERY_S = 3600        # one wake per kind of warning per hour; the rest are counted
WAKE_ROOM = os.environ.get("BURN_WAKE_ROOM", "cryptic-crosswords")
GAVE_UP = re.compile(r"^  \[" + PUZZLE + r"\] (.*(?:solve rejected|rejected|(?<!rather than )discard|held|gave up|cannot be|could not be).*)$")
KINDS = (  # commit-message prefix -> what was done
    (re.compile(r"^Annotate\b"), "wrote hints"),
    (re.compile(r"^Re-check against its blog"), "re-checked against its blog"),
    (re.compile(r"^Backfill (\S+)"), lambda m: f"backfilled {m.group(1)}"),
)


#: backlog field -> (what the run does, what it did): the plain words for tools/annotation_backlog.json's keys.
PHRASES = {
    "wordplay.anagramCharade": ("re-shape anagram fodder filed as a charade", "re-shaped anagram fodder filed as a charade"),
    "wordplay.anaStandIn": ("re-shape anagram stand-ins", "re-shaped anagram stand-ins"),
    "wordplay.anaSelectEdge": ("re-shape anagram edge-letter picks", "re-shaped anagram edge-letter picks"),
    "wordplay.anaDoubleInd": ("re-shape anagrams with two indicators", "re-shaped anagrams with two indicators"),
    "wordplay.anaIsMove": ("re-shape anagrams that are a letter move", "re-shaped anagrams that are a letter move"),
    "wordplay.anaLoneEdge": ("re-shape anagram of a lone edge letter", "re-shaped anagram of a lone edge letter"),
    "wordplay.anaLiteralEdge": ("re-shape anagram holding a clue word at its edge", "re-shaped anagram holding a clue word at its edge"),
    "wordplay.delWide": ("re-shape deletion listing several pieces", "re-shaped deletion listing several pieces"),
    "wordplay.delStraddle": ("re-shape deletion across two pieces", "re-shaped deletion across two pieces"),
    "wordplay.delWrapsCharade": ("re-shape deletion wrapping a charade", "re-shaped deletion wrapping a charade"),
    "wordplay.charadeInCharade": ("flatten a charade inside a charade", "flattened a charade inside a charade"),
    "blocks.note": ("add block notes", "added block notes"),
    "explanation.surface": ("add surface reading", "added surface reading"),
    "explanation.definitionFit": ("add definition-fit notes", "added definition-fit notes"),
    "indicators.note": ("add indicator notes", "added indicator notes"),
    "features": ("add clue features", "added clue features"),
    "messages": ("add hidden-letter messages", "added hidden-letter messages"),
}


def phrase(field):
    """(base, past) for a backlog field; the key itself when it has no phrase."""
    return PHRASES.get(field) or (field, f"backfilled {field}")


MEM_DETAIL = re.compile(r"memory ([\d.]+) GB available less ([\d.]+) GB kept free"
                        r"(?:, \d+ MB a run)?(?:, swap ([\d.]+)/([\d.]+) GB used)?")


def limit_note(limit, rush, rest):
    """The limit as the status line shows it. Memory comes with what it is made of
    (Paul 11-03: "it says memory is the limiter but memory looks fine": 6 GB available,
    of which the planner keeps 4 GB free, with swap full); a rush, where the planner asks
    for as many runs as memory holds, says so instead of passing for a usage pace."""
    if limit != "memory":
        return None
    m = MEM_DETAIL.search(rest)
    note = "memory"
    if m:
        note += f": {m.group(1)} GB free, {m.group(2)} GB kept back"
        if m.group(3) and float(m.group(4)) > 0 and float(m.group(3)) >= 0.9 * float(m.group(4)):
            note += ", swap full"
    return note + (" · rushing" if rush else "") if (m or rush) else None


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


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
        self.pool_raw = self.width_raw = None
        self.backlog = None       # field -> {puzzle: clues}, read when a backlog starts
        self.snap = {}            # field -> its counts when its backlog started
        self.width = None
        self.limit = None
        self.limit_note = None    # the limit as shown: memory with its numbers, a rush said
        self.reset_plan = None    # the planner's rush decision: "pacing to ... reset, 0 of 15 manual resets left"
        self.mem_said = ""        # the last "  why:" line: the burn prints the width's inputs there
        self.week = None          # (percent used, hours to reset)
        self.done = collections.deque()  # times of the last hour's finished puzzles
        self.said_status = (None, None)
        self.status_at = 0.0
        self.outcomes_since = 0
        self.idle = False
        self.problems = {}        # text -> when last said
        self.events = collections.deque()    # (time, "ok"|"nc", rule) of finished puzzles
        self.nc_lines = collections.deque(maxlen=3)   # the last no-change lines: evidence
        self.kept = {}   # puzzle -> clues a blog re-check kept ours on, until its commit line
        self.fail_count = collections.Counter()       # puzzle -> failures and no-changes
        self.waste_tier = 0
        self.waste_said = 0.0
        self.repeats = []         # puzzles past their second failure since the last repeat line
        self.repeat_said = -WAKE_EVERY_S
        self.warned = set()       # one-shot warnings already said
        self.active = {}          # warning kind -> text while it holds
        self.since = {}           # warning kind -> when its condition began
        self.raw = collections.deque(maxlen=3)        # the last raw lines: evidence
        self.pool = None          # (width, in flight, queued) of the latest pool line
        self.stopping = False     # the burn said it is stopping (deadline, pause): an empty pool is meant
        self.need = None          # runs the week needs, from the latest width line
        self.meters = collections.deque(maxlen=400)   # (time, points spent, commits since the last, clues since the last)
        self.commits_since_meter = 0
        self.clues_since_meter = 0
        self.last_meter = collections.deque(maxlen=3)
        self.wakes = []           # (time, kind, text) sent
        self.wake_at = {}         # kind -> last wake time
        self.wake_more = collections.Counter()
        self.notify = None        # callable(text) that files a wake
        self.tokens_of = None     # callable(puzzle) -> tokens its backfill session spent
        self.costs = collections.deque()   # (time, tokens, clues, rule, puzzle) of the last hour's backfills

    def out(self, now, mark, text):
        return f"{stamp(now)} {mark} {text}"

    def load_backlog(self):
        """tools/annotation_backlog.json of the burn's worktree: field -> {puzzle: clues}."""
        if self.backlog is not None:
            return self.backlog
        try:
            with open(os.path.join(self.repo, "tools", "annotation_backlog.json")) as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError, TypeError):
            return {}

    def touched(self, subject, pid):
        """The clue labels (14A, 3D) the commit with this subject changed in puzzle pid; None
        when the history cannot say."""
        if not self.repo:
            return None
        try:
            git = ["git", "-C", self.repo]
            log = subprocess.run(git + ["log", "-n", "40", "--format=%H%x1f%s%x1f%b%x1e"], capture_output=True, text=True,
                                 timeout=20, check=True).stdout.split("\x1e")
            rows = [r.strip("\n").split("\x1f") for r in log if r.strip()]
            # A bag's puzzles ride in one commit, "<what> N puzzles" with the ids in its body.
            lead = subject.rsplit(" ", 1)[0] + " "
            sha = next(r[0] for r in rows if len(r) > 2 and (r[1] == subject or (
                r[1].startswith(lead) and r[1].endswith(" puzzles") and pid in r[2].split())))
            names = subprocess.run(git + ["diff-tree", "--no-commit-id", "--name-only", "-r", sha],
                                   capture_output=True, text=True, timeout=20, check=True).stdout.split()
            path = next(n for n in names if n.endswith(f"/{pid}.json"))

            def entries(rev):
                raw = subprocess.run(git + ["show", f"{rev}:{path}"], capture_output=True, text=True,
                                     timeout=30, check=True).stdout
                return {(e["number"], e["direction"]): e for e in json.loads(raw)["entries"]}
            before, after = entries(sha + "^"), entries(sha)
            keys = sorted(k for k in after if after[k] != before.get(k))
            return [f"{n}{d[:1].upper()}" for n, d in keys]
        except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError):
            return None

    def finished(self, now, ok, pid=None, rule=None, nochange=False, clues=None):
        """Record a puzzle's end; returns ⚠️ lines when it is a puzzle's second failure."""
        self.outcomes_since += 1
        if ok and not nochange:
            self.done.append(now)
            self.commits_since_meter += 1
            self.clues_since_meter += clues or 1  # per clue: a 1-hint mend and a 29-hint puzzle are not one unit
            self.events.append((now, "ok", rule))
        if nochange:
            self.events.append((now, "nc", rule))
        if pid and (nochange or not ok):
            self.fail_count[pid] += 1
            if self.fail_count[pid] == 2 and pid not in self.warned:
                self.warned.add(pid)
                # The first is said at once; the rest of the hour's are one summary line (checks).
                if now - self.repeat_said >= WAKE_EVERY_S:
                    self.repeat_said = now
                    return self.warn(now, f"repeat:{pid}", f"{pid} failed or changed nothing twice",
                                     list(self.nc_lines)[-2:] + [f"rule: {rule or 'annotate'}"], wake=False)
                self.repeats.append(pid)
        return []

    def window(self, now):
        """(no-change count, finished count by commits, top rule and its count) over the last hour."""
        while self.events and self.events[0][0] < now - 3600:
            self.events.popleft()
        nc = collections.Counter(r for _, k, r in self.events if k == "nc")
        total_nc = sum(nc.values())
        top = nc.most_common(1)[0] if nc else (None, 0)
        return total_nc, self.last_hour(now), top

    def tokens_window(self, now):
        """(tokens per clue written in the last hour, clues, the costliest rule and its rate, evidence)."""
        while self.costs and self.costs[0][0] < now - 3600:
            self.costs.popleft()
        clues = sum(c for _, _, c, _, _ in self.costs)
        if clues < TOKENS_MIN_CLUES:
            return None
        by_rule = collections.defaultdict(lambda: [0, 0])
        for _, tok, c, rule, _ in self.costs:
            by_rule[rule][0] += tok
            by_rule[rule][1] += c
        rule, (tok, c) = max(by_rule.items(), key=lambda kv: kv[1][0])
        evidence = [f"{pid}: {tok // 1000}k tokens for {plural(c, 'clue')}" for _, tok, c, _, pid in list(self.costs)[-3:]]
        return sum(t for _, t, _, _, _ in self.costs) / clues, clues, (rule, tok / c), evidence

    def cost(self, now, pid, rule, clues, counted=True):
        """The session's tokens for puzzle pid, against the clues it wrote or checked, into the hour's
        tokens-per-clue window (a backfill, or a blog re-check solo or bagged)."""
        tok = self.tokens_of(pid) if (self.tokens_of and counted) else None
        if tok:
            self.costs.append((now, tok, clues or 1, rule, pid))

    def warn(self, now, kind, text, evidence, wake=True, wake_kind=None):
        """A ⚠️ line, plus a wake (at most one per kind of warning per hour) with its evidence."""
        line = self.out(now, "⚠️", text)
        key = wake_kind or kind.split(":")[0]
        if not wake:
            return [line]
        if now - self.wake_at.get(key, -WAKE_EVERY_S) >= WAKE_EVERY_S:
            more = self.wake_more.pop(key, 0)
            body = "Burn: " + text + (f" ({more} more warnings of this kind in the last hour)" if more else "")
            body += "".join("\n  " + clip(e, 200) for e in list(evidence)[-3:])
            self.wake_at[key] = now
            self.wakes.append((now, key, body))
            if self.notify:
                self.notify(body)
        else:
            self.wake_more[key] += 1
        return [line]

    def condition(self, now, kind, bad, text, evidence, clear_text, held_for=0):
        """Warn once when `bad` has held for held_for seconds, and say once when it clears."""
        if bad:
            self.since.setdefault(kind, now)
            if kind not in self.active and now - self.since[kind] >= held_for:
                self.active[kind] = text
                return self.warn(now, kind, text, evidence)
            return []
        self.since.pop(kind, None)
        if kind in self.active:
            del self.active[kind]
            return [self.out(now, "──", f"cleared: {clear_text}")]
        return []

    def checks(self, now):
        """The warnings that hold over time: wasted runs, too few runs, behind pace, cost."""
        out = []
        if self.repeats and now - self.repeat_said >= WAKE_EVERY_S:
            ids, self.repeats, self.repeat_said = self.repeats, [], now
            # A storm of repeats is the waste warning's own evidence: it shares its hourly wake.
            out += self.warn(now, "repeat:more", f"{plural(len(ids), 'more puzzle')} failed or changed nothing twice in the last hour",
                             [", ".join(ids[:12])], wake=len(ids) >= 10, wake_kind="waste")
        nc, done, (top, top_n) = self.window(now)
        total = nc + done
        share = nc / total if total else 0.0
        rule = phrase(top)[0] if top and top != "annotate" else top
        tier = 0 if total < WASTE_MIN or share <= WASTE_SHARE else 1 + (share > 2 * WASTE_SHARE) + (share > 3 * WASTE_SHARE)
        if tier > self.waste_tier >= 1 and now - self.waste_said >= 600:  # worse than when it was said: the new number
            self.waste_said = now
            out += self.warn(now, "waste", f"wasted runs worse: {nc} of {total} puzzles ({share:.0%}) in the last hour changed "
                             f"nothing, most from {rule} ({top_n})", self.nc_lines)
        self.waste_tier = max(self.waste_tier, tier) if tier else 0
        out += self.condition(
            now, "waste", total >= WASTE_MIN and share > WASTE_SHARE,
            f"wasted runs: {nc} of {total} puzzles ({share:.0%}) in the last hour changed nothing, most from {rule} ({top_n})",
            self.nc_lines, f"wasted runs down to {share:.0%}")
        if self.pool:
            w, n, q = self.pool
            out += self.condition(
                now, "short", w > 0 and n < 0.75 * w and q > 0 and not self.stopping,
                f"only {n} runs in flight against a width of {w}, with {q} queued", [self.pool_raw] if self.pool_raw else [],
                f"{n} of {w} runs in flight", SHORT_S)
        out += self.condition(
            now, "pace", self.width is not None and self.need is not None and self.width < self.need and self.limit != "memory",
            f"behind pace: {self.width} at once, {self.need} needed to spend the week by its reset"
            + (f" (limit: {self.limit})" if self.limit else ""),
            [self.width_raw] if self.width_raw else [], "back on pace", SHORT_S)
        tw = self.tokens_window(now)
        out += self.condition(
            now, "tokens", bool(tw and tw[0] > TOKENS_PER_CLUE_MAX),
            (f"tokens per clue: {phrase(tw[2][0])[0]} ran at {tw[2][1] / 1000:.0f}k tokens per clue written over the last hour "
             f"({plural(tw[1], 'clue')} in all, {tw[0] / 1000:.0f}k overall; one run per puzzle; a bag is about 12k)")
            if tw else "", tw[3] if tw else [], "tokens per clue back under 30k")
        # Per clue written, not per puzzle: the queue moves between one-hint mends and whole
        # puzzles of ~29 hints, and a per-puzzle rate called that mix change a cost spike.
        recent = [(p, c, k) for t, p, c, k in self.meters if t > now - 3600]
        trail = [(p, c, k) for t, p, c, k in self.meters if now - 6 * 3600 < t <= now - 3600]
        pr, cr, kr = (sum(x[i] for x in recent) for i in range(3))
        pt, ct, kt = (sum(x[i] for x in trail) for i in range(3))
        costly = bool(cr >= 5 and ct >= 20 and pt >= 8 and pr >= 4 and (pr / kr) > COST_FACTOR * (pt / kt))
        out += self.condition(
            now, "cost", costly,
            f"cost per clue doubled: {pr} meter points for {kr} clues ({cr} puzzles) committed in the last hour, "
            f"against {pt / kt * 1000:.1f} points per 1000 clues before",
            self.last_meter, "cost per clue back to normal")
        return out

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
                self.done_cache = (now, sum(puzzles_in(x) for x in res.stdout.splitlines()))
            except (OSError, ValueError, subprocess.SubprocessError):
                self.done_cache = (now, -1)
        return self.done_cache[1] if self.done_cache[1] >= 0 and self.repo else len(self.done)

    def status(self, now, force=False):
        """The full status line, whenever the width or its limit changed, five minutes passed,
        or the caller forces it (after a restart, a "next:" or an "idle:" line)."""
        if self.width is None or self.restart:  # a restart says its own status first
            return []
        changed = (self.width, self.limit, self.reset_plan) != self.said_status
        if not (changed or force or now - self.status_at >= HEARTBEAT_S):
            return []
        self.said_status, self.status_at = (self.width, self.limit, self.reset_plan), now
        week = f"weekly {self.week[0]:g}% used" if self.week else None
        if self.width == 0:
            if self.week and self.week[0] >= 99:
                return [self.out(now, "──", f"paused: {week}, resets in {self.week[1]:.0f}h")]
            return [self.out(now, "──", "waiting: nothing may start right now" + (f" · {week}" if week else ""))]
        nc, done, _ = self.window(now)
        share = f" ({nc / (nc + done):.0%})" if nc + done else ""
        shown = self.limit_note or self.limit
        parts = [f"{self.width} at once" + (f" ({shown})" if shown else ""),
                 f"{done} done/h", f"{nc} no-change/h{share}"]
        tw = self.tokens_window(now)
        if tw:
            parts.append(f"{tw[0] / 1000:.0f}k tok/clue")
        if self.queued is not None:
            parts.append(f"{self.queued} queued")
        if week:
            parts.append(week)
        if self.reset_plan:
            parts.append(self.reset_plan)
        return [self.out(now, "──", " · ".join(parts))]

    def nothing(self, now, pid, rule, allowed):
        """A run that changed nothing: a quiet line, and it counts as waste."""
        line = self.out(now, "·", f"{pid} nothing to change" + (f" ({plural(allowed, 'clue')})" if allowed else "")
                        + (f" [{phrase(rule)[0]}]" if rule not in ("annotate", "blog re-check") else f" [{rule}]"))
        self.nc_lines.append(line)
        return [line] + self.finished(now, True, pid, rule, nochange=True)

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
        self.raw.append(line)
        # Any line carries the five-minute status: the burn's width and pool lines can be far apart.
        return (self.flush_fill(now) + self.handle(line, now) + self.idle_check(now) + self.status(now)
                + self.checks(now))

    def idle_check(self, now):
        """"idle" only once nothing has been queued for IDLE_AFTER_S: the pool also shows an
        empty queue for a moment between two backlogs."""
        if self.nothing_since is None or self.idle or now - self.nothing_since < IDLE_AFTER_S:
            return []
        self.idle = True
        return [self.out(now, "──", "idle: nothing queued")] + self.status(now, force=True)

    def handle(self, line, now):
        if line.startswith("  why: ") and MEM_DETAIL.search(line):
            self.mem_said = line
            return []
        old = re.match(r"^width (\d+): need (\d+) .*?\(([\d.]+)% now, ([\d.]+)h to its reset.*?memory cap (\w+), "
                       r"cpu cap (\w+).*?load cap (\w+)", line)
        if old:  # the format before 11-03, so a replay of the older log works
            line = (f"width {old.group(1)} (cap: memory {old.group(5)}, cpu {old.group(6)}, load {old.group(7)}, "
                    f"quota pace {old.group(2)}) · weekly {old.group(3)}% now, {old.group(4)}h to its reset")
        m = re.match(r"^width (\d+) \(cap: ([^)]*)\)(?: · (.*))?$", line)
        if m:
            self.width_raw = line
            # prereset_plan.rush_choice's words, ";" for "," so the caps split keeps them whole.
            rp = re.search(r"reset plan ([^,]*)", m.group(2))
            self.reset_plan = rp.group(1).replace("; ", ", ") if rp else None
            caps = {}
            for part in m.group(2).split(", "):
                name, _, val = part.rpartition(" ")
                caps[name] = int(val) if val.isdigit() else None
            caps.setdefault("quota pace", None)
            self.width = int(m.group(1))
            self.limit = next((n for n in CAP_ORDER if caps.get(n) == self.width), None)
            self.need = caps.get("quota pace")
            if self.limit == "quota pace":
                self.limit = "usage pace"
            # The burn's width line ends "· N in flight"; the planner's inputs (memory among them)
            # follow on a "  why:" line, so the last one seen stands in until the next arrives.
            self.limit_note = limit_note(self.limit, "quota pace rush" in m.group(2),
                                         m.group(3) if MEM_DETAIL.search(m.group(3) or "") else self.mem_said)
            w = re.search(r"weekly ([\d.]+)% now, ([\d.]+)h to its reset", m.group(3) or "")
            if w:
                self.week = (float(w.group(1)), float(w.group(2)))
            self.idle = False
            return self.status(now)
        m = re.match(r"^weekly (\d+)% -> (\d+)%", line.strip())
        if m:
            self.last_meter.append(line.strip())
            self.meters.append((now, int(m.group(2)) - int(m.group(1)), self.commits_since_meter, self.clues_since_meter))
            self.commits_since_meter = self.clues_since_meter = 0
            if self.week:
                self.week = (float(m.group(2)), self.week[1])
            return []
        m = re.match(r"^--- pool of (\d+): (\d+) in flight \(\d+ running\), (\d+) queued", line)
        if m:
            self.pool, self.pool_raw = (int(m.group(1)), int(m.group(2)), int(m.group(3))), line.strip("- ")
            m = re.match(r"^--- pool of \d+: (\d+) in flight \(\d+ running\), (\d+) queued", line)
            self.queued = int(m.group(2))
            if m.group(1) == "0" and self.queued == 0:
                self.nothing_since = self.nothing_since or now
                return self.status(now)
            self.nothing_since, self.idle = None, False
            if self.next_work:
                field, self.next_work = self.next_work[0], None
                counts = self.snap.get(field)
                totals = (f": {plural(len(counts), 'puzzle')}, {plural(sum(counts.values()), 'clue')}"
                          if counts else f", {self.queued} queued")
                return [self.out(now, "──", f"next: {phrase(field)[0]}{totals}")] + self.status(now, force=True)
            return self.status(now)
        m = re.match(r"^(\S+) backlog: (.*)$", line)
        if m:
            field = m.group(1)
            counts = self.load_backlog().get(field)
            if counts is not None:
                self.snap[field] = dict(counts)
            self.next_work = (field, m.group(2).split())
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
            pid = ids[-1]
            field = (re.match(r"^Backfill (\S+) for ", msg) or [None, None])[1]
            if field:
                what = phrase(field)[1]
            elif re.match(r"^Re-check against its blog", msg):
                what = "re-checked against its blog"
            elif re.match(r"^Annotate\b", msg):
                what = "wrote hints"
            else:
                what = msg
            kept = self.kept.pop(pid, None) if what == "re-checked against its blog" else None
            labels = self.touched(msg, pid) if not kept else None
            if kept:  # a re-check that filed "ours stands" and left the puzzle alone: work, not waste
                self.finished(now, True, pid, "blog re-check")
                self.cost(now, pid, "blog re-check", kept)
                return [self.out(now, "✓", f"{pid} kept ours on {plural(kept, 'clue')} against its blog")]
            allowed = (self.snap.get(field) or {}).get(pid) if field else None
            rule = field or ("blog re-check" if "Re-check" in msg else "annotate")
            if labels == [] and field:
                return self.nothing(now, pid, rule, allowed)
            n = len(labels) if labels else allowed
            where = f" in {plural(n, 'clue')}" if n else ""
            if what == "wrote hints" and n:  # "wrote 28 hints", not "hints written in 28 clues"
                what, where = f"wrote {plural(n, 'hint')}", ""
            if labels and len(labels) <= 8:
                where += f" ({', '.join(labels)})"
            self.finished(now, True, pid, rule, clues=n)
            self.cost(now, pid, rule, n, field or what == "re-checked against its blog")
            return [self.out(now, "✓", f"{pid} {what}{where}")]
        m = re.match(r"^  \[" + PUZZLE + r"\] bag of (\d+) puzzles(?:, (\d+) clues)?: (\S+)", line)
        if m:  # pool_bag: one session for several puzzles of the same rule
            rule = m.group(4)
            words = "write the missing hints" if rule == "annotate" else phrase(rule)[0]
            clues = f", {m.group(3)} clues" if m.group(3) else ""
            return [self.out(now, "▶", f"bag of {m.group(2)} puzzles{clues}: {words}")]
        m = re.match(r"^  \[" + PUZZLE + r"\] (bag hit its turn limit after .*?)(?: \(\d+ changed.*)?$", line)
        if m:  # puzzle_worker.worker_finish_bag: what it finished shipped, the rest is requeued
            return [self.out(now, "✂", m.group(2))]
        m = re.match(r"^  \[" + PUZZLE + r"\] skipped: already fully hinted", line)
        if m:
            return [self.out(now, "·", f"{m.group(1)} nothing to change (already hinted)")]
        m = re.match(r"^Re-check against its blog:? " + PUZZLE + r" kept ours on (\d+) clues?$", line)
        if m:  # remembered for the "committed" line that follows
            self.kept[m.group(1)] = int(m.group(2))
            return []
        m = re.match(r"^(.*) " + PUZZLE + r" produced no change$", line)
        if m:
            field = (re.match(r"^Backfill (\S+) for", m.group(1)) or [None, None])[1]
            rule = field or ("blog re-check" if "Re-check" in m.group(1) else "annotate")
            return self.nothing(now, m.group(2), rule, (self.snap.get(field) or {}).get(m.group(2)) if field else None)
        m = re.match(r"^  \[" + PUZZLE + r"\] the run withdrew its own work, so nothing it wrote ships — (.*)$", line)
        if m:
            # Nobody read these reasons and the same puzzles were bought again and withdrawn
            # again (11-03: ~50 retries), so each new withdrawal wakes the room to triage it
            # (`failed_inputs.py triage annotate`; the record is held until it is cleared).
            return [self.out(now, "✗", f"{m.group(1)} gave up: {clip(m.group(2))} — skipped until the puzzle changes")] + \
                self.warn(now, "withdrawal", f"{m.group(1)} withdrew its own work; triage it with "
                          f"`failed_inputs.py triage annotate`", [f"{m.group(1)}: {m.group(2)[:200]}"]) + \
                self.finished(now, False, m.group(1), "annotate")
        m = re.match(r"^  \[" + PUZZLE + r"\] (transient failure) — its conversation is kept", line)
        if m:
            return [self.out(now, "✗", f"{m.group(1)} cut off (limit or crash), will resume")]
        m = re.match(r"^  \[" + PUZZLE + r"\] failed with the weekly meter below", line)
        if m:
            return [self.out(now, "✗", f"{m.group(1)} stopped by the usage limit, dropped for this run")]
        m = GAVE_UP.match(line)
        if m:
            return [self.out(now, "✗", f"{m.group(1)} {clip(m.group(2))}")] + self.finished(now, False, m.group(1), "annotate")
        if re.match(r"^(deadline reached|paused \()", line):
            self.stopping = True
            return [self.out(now, "──", f"stopping: {clip(line)}")]
        if PROBLEM.search(line):
            text = clip(line.removeprefix("ALERT: "), 200)
            if now - self.problems.get(text, -1e18) < 6 * 3600:
                return []
            self.problems[text] = now
            return self.warn(now, "problem", text, list(self.raw)[:-1])
        return []


class TokenIndex:
    """Tokens each backfill session spent, by puzzle: input + output + cache writes + cache reads
    at 0.1 (a turn re-reads the whole conversation, so reads are what a long session costs: left
    out, a bag of 57 turns and one of 20 looked alike), from the CLI's transcripts. Scanned in
    a thread so the filter never stalls the pipe the burn writes to."""

    # A backfill's prompt, the blog re-check's solo one, and a bag's (tools/annotate_bag_prompt.md,
    # under a shape or blog preface or alone): a bag names its puzzles after "this one session:", and
    # its tokens are shared out evenly among them.
    PREFIXES = ("In this repo, add the missing", "In this repo, the annotated crossword",
                "These crosswords are already annotated", "Annotate these crosswords in this one session:")
    BAG_IDS = re.compile(r"this one session: (.*?)\. Read tools/_bag_")

    def __init__(self, root=None):
        self.root = pathlib.Path(root or os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude")
        self.by_pid = {}
        self.seen = {}

    def scan(self, window_s=3 * 3600):
        floor = time.time() - window_s
        for path in self.root.glob("projects/*cryptic*/*.jsonl"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime < floor or self.seen.get(path) == mtime:
                continue
            self.seen[path] = mtime
            first, tokens, ids = None, 0.0, set()
            try:
                with path.open(errors="replace") as fh:
                    for line in fh:
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        msg = rec.get("message") or {}
                        if rec.get("type") == "user" and first is None:
                            content = msg.get("content")
                            first = content if isinstance(content, str) else json.dumps(content)
                            if not first.startswith(self.PREFIXES):
                                break
                        elif rec.get("type") == "assistant" and msg.get("id") not in ids:
                            ids.add(msg.get("id"))
                            u = msg.get("usage") or {}
                            tokens += (u.get("input_tokens", 0) + u.get("output_tokens", 0)
                                       + u.get("cache_creation_input_tokens", 0)
                                       + 0.1 * u.get("cache_read_input_tokens", 0))
            except OSError:
                continue
            if first and first.startswith(self.PREFIXES):
                tokens = int(tokens)
                bag = self.BAG_IDS.search(first) if first.startswith(self.PREFIXES[2:]) else None
                if bag:
                    members = bag.group(1).split()
                    for pid in members:
                        self.by_pid[pid] = tokens // len(members)
                    continue
                members = list(dict.fromkeys(re.findall(r"/" + PUZZLE + r"\.json", first)))
                if members:
                    self.by_pid[members[0]] = tokens

    def __call__(self, pid):
        return self.by_pid.get(pid)

    def keep_fresh(self, every=300):
        def loop():
            while True:
                with contextlib.suppress(Exception):  # a bad transcript must not end the thread
                    self.scan()
                time.sleep(every)
        threading.Thread(target=loop, daemon=True).start()


def send_wake(text):
    """Wake the room: a warning is news it must act on, so no -q (that only files a note for its
    next turn). Only warnings call this, at most one per kind per hour (Log.warn)."""
    try:
        import local_config
        wake = local_config.path("household_dir") + "/tools/wake.sh"
    except ImportError:  # no local_config beside us: fall back to the WAKE_SH override
        wake = os.environ.get("WAKE_SH", "")
    if wake and os.path.exists(wake):
        subprocess.run([wake, "-c", WAKE_ROOM, text[:1800]], check=False, timeout=60,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def replay(path, start=0, end=None, repo=None):
    """Feed an old log through the summariser on a clock the meter lines keep (each
    'weekly A% -> B% in Xh' moves it X hours): prints what it would have written and woken."""
    log = Log(repo)
    index = TokenIndex()
    index.scan(window_s=36 * 3600)
    log.tokens_of = index
    t = 1_800_000_000.0
    lines = __import__("pathlib").Path(path).read_text(errors="replace").splitlines()[start:end]
    for raw in lines:
        m = re.match(r"^\s*weekly \d+% -> \d+% in ([\d.]+)h", raw)
        out = log.feed(raw, t)
        if m:
            t += float(m.group(1)) * 3600
        for text in out:
            print(text)
    print(f"--- {len(lines)} lines, {t - 1_800_000_000:.0f}s of meter time; wakes that would have gone out:")
    for when, kind, body in log.wakes:
        print(f"  +{(when - 1_800_000_000) / 3600:.1f}h [{kind}] {body}")
    return 0


def main(argv):
    if argv[1] == "--replay":
        return replay(argv[2], int(argv[3]) if len(argv) > 3 else 0, int(argv[4]) if len(argv) > 4 else None,
                      argv[5] if len(argv) > 5 else None)
    path = argv[1]
    log = Log(argv[2] if len(argv) > 2 else None)
    log.notify = send_wake
    log.tokens_of = TokenIndex()
    log.tokens_of.keep_fresh()
    fresh = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", buffering=1) as out:
        if fresh:
            out.write(f"{stamp(time.time())} ── burn log (Alberta time); full detail in .prereset.debug.log\n")
        for raw in sys.stdin:
            out.writelines(text + "\n" for text in log.feed(raw))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
