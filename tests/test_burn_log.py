#!/usr/bin/env python3
# Does the burn's human log say, line by line, what each puzzle did and how wide it runs?
#
#     python3 tests/test_burn_log.py
#
# Raw burn lines in, human lines out (tools/burn_log.py); noise out.
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path
import burn_log as B

fails = 0
def check(got, want, what):
    global fails
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'}: {what}" + ("" if ok else f"\n    got {got!r}, wanted {want!r}"))
    fails += not ok

T = 1_800_000_000  # a fixed instant; only the clock text depends on the zone
def run(lines, t=T):
    log = B.Log()
    out = []
    for i, line in enumerate(lines):
        out += log.feed(line, t + i)
    return out
def bare(lines):  # without the HH:MM stamp
    return [x.split(" ", 1)[1] for x in lines]

WIDTH = ("width 15 (cap: memory 15, cpu —, load 20, quota pace 22) · weekly 98% now, 19.4h to its reset, "
         "aiming 19.40h out; bridge 2.1 pts/h; was 21")
check(bare(run([WIDTH])), ["── 15 at once (memory) · 0 done/h · 0 no-change/h · weekly 98% used"],
      "a width line becomes a status line naming the cap that binds")
check(bare(run(["width 22 (cap: memory 22, cpu —, load —, quota pace 22) · weekly 50% now, 80.0h to its reset"])),
      ["── 22 at once (memory) · 0 done/h · 0 no-change/h · weekly 50% used"],
      "a tie between caps names the first in order")
check(bare(run(["width 0 (cap: memory 0, cpu —, load —, quota pace 0) · weekly 100% now, 3.0h to its reset"])),
      ["── paused: weekly 100% used, resets in 3h"], "width 0 with the week spent is a pause")
check(len(run([WIDTH, WIDTH])), 1, "the same width twice says nothing new")
RUSH = ("width 15 (cap: memory 15, cpu —, load —, quota pace rush) · weekly 6% now, 140.0h to its reset; "
        "bridge 2.1 pts/h; cores unread; memory 6.2 GB available less 4 GB kept free, 250 MB a run, "
        "swap 4.0/4.0 GB used; was 13")
check(bare(run([RUSH])), [("── 15 at once (memory: 6.2 GB free, 4 GB kept back, swap full · rushing) · 0 done/h · "
                           "0 no-change/h · weekly 6% used")],
      "a memory limit says what memory holds, and a rush is said, not shown as a pace that ties memory")
check(bare(run(["  why: weekly 10% now; memory 6.9 GB available less 4 GB kept free, 250 MB a run, swap 3.3/4.0 GB used; was 12",
                 "width 11 (cap: memory 11, cpu —, load —, quota pace rush) · 0 in flight · 0 committed last hour"])),
      ["── 11 at once (memory: 6.9 GB free, 4 GB kept back · rushing) · 0 done/h · 0 no-change/h"],
      "the burn's width line takes the memory numbers from the why: line before it")
check(B.limit_note("usage pace", False, "memory 9.0 GB available less 4 GB kept free"), None,
      "only a memory limit carries the memory numbers")

check(bare(run(["committed Annotate azed-2702"])), ["✓ azed-2702 wrote hints"], "annotate commit")
check(bare(run(["committed Backfill wordplay.anaLoneEdge for azed-2581"])),
      ["✓ azed-2581 re-shaped anagram of a lone edge letter"], "backfill commit")
check(bare(run(["  [azed-2581] bag of 4 puzzles, 6 clues: wordplay.anaLoneEdge — with: a-1 b-2 c-3 "])),
      ["▶ bag of 4 puzzles, 6 clues: re-shape anagram of a lone edge letter"], "a backfill bag names its rule in plain words")
check(bare(run(["  [azed-2581] bag of 9 puzzles, 31 clues: annotate — with: a-1"])),
      ["▶ bag of 9 puzzles, 31 clues: write the missing hints"], "an annotate bag")
check(bare(run(["  [azed-2581] bag of 3 puzzles: wordplay.anaLoneEdge — with: a-1 b-2"])),
      ["▶ bag of 3 puzzles: re-shape anagram of a lone edge letter"], "a resumed bag, its clue count not known")
check(bare(run(["committed Re-check against its blog: times-25738"])),
      ["✓ times-25738 re-checked against its blog"], "blog re-check commit")
check(bare(run(["  [everyman-3470] the run withdrew its own work, so nothing it wrote ships — 1-down MUNTJAC has no clean parse"])),
      ["✗ everyman-3470 gave up: 1-down MUNTJAC has no clean parse — skipped until the puzzle changes"],
      "a withdrawal keeps its reason in one line")
check(bare(run(["  [a-1] transient failure — its conversation is kept to resume at the next start"])),
      ["✗ a-1 cut off (limit or crash), will resume"], "a cut-off run")

noise = ["annotation loss check: 1 puzzle(s), none left short", "push_puzzle_commit: batched 4 commit(s); pushing in 45s",
         "  [azed-2702] started", "sync: tree at 34b6b4e82dd, 0 runs in flight", "annotate ledger: 0 sessions since 2026-11-03",
         "wordplay.anaSelectEdge backlog: azed-1 azed-2", "  weekly 99% -> 99% in 0.087h at width 6.18",
         "  [x-1] did not validate — handing the errors back rather than discarding the puzzle",
         "(JSON: `entries` is a list of strings", "  [a-1] bag of 4: 2 changed, 1 produced no change, 1 not shipped, 0 to solve again",
         "x-1 failed on this puzzle and is skipped until it changes"]
check(run(noise), [], "debug lines produce nothing")
check(bare(run(["  [a-1] bag hit its turn limit after 9 of 30 puzzles; 21 untouched go back in the queue (3 changed, 6 kept ours, 0 not shipped)"])),
      ["✂ bag hit its turn limit after 9 of 30 puzzles; 21 untouched go back in the queue"], "a bag stopped by its turn limit is one plain line")

EMPTY = "--- pool of 6: 0 in flight (0 running), 0 queued ---"
check(run([EMPTY]), [], "an empty queue for a moment is not idle")
log = B.Log()
log.feed(EMPTY, T)
check(bare(log.feed("sync: tree at x", T + 301)), ["── idle: nothing queued"], "idle after five empty minutes")
check(log.feed("sync: tree at x", T + 400), [], "idle is said once")

log = B.Log()
log.feed(WIDTH, T)
got = []
for i, line in enumerate(["wordplay.anagramCharade backlog: a-1 a-2", "--- pool of 15: 0 in flight (0 running), 290 queued ---"]):
    got += log.feed(line, T + 10 + i)
check(bare(got), ["── next: re-shape anagram fodder filed as a charade, 290 queued",
                  "── 15 at once (memory) · 0 done/h · 0 no-change/h · 290 queued · weekly 98% used"],
      "a switch of backlog is a next: line in plain words and a full status line")

log = B.Log()
log.backlog = {"wordplay.anagramCharade": {"azed-1759": 2, "azed-2689": 1}, "unknown.key": {"x-1": 3}}
log.feed(WIDTH, T)
got = []
for i, line in enumerate(["wordplay.anagramCharade backlog: azed-1759 azed-2689", "--- pool of 15: 0 in flight (0 running), 2 queued ---"]):
    got += log.feed(line, T + 10 + i)
check(bare(got)[0], "── next: re-shape anagram fodder filed as a charade: 2 puzzles, 3 clues", "next: gives the totals")
log.touched = lambda subject, pid: ["14A"]
check(bare(log.feed("committed Backfill wordplay.anagramCharade for azed-2689", T + 30)),
      ["✓ azed-2689 re-shaped anagram fodder filed as a charade in 1 clue (14A)"], "a commit names the rule, count and clues")
log.touched = lambda subject, pid: ["1A", "3D"]
check(bare(log.feed("committed Backfill wordplay.anagramCharade for azed-1759", T + 31)),
      ["✓ azed-1759 re-shaped anagram fodder filed as a charade in 2 clues (1A, 3D)"], "several clues")
log.touched = lambda subject, pid: []
check(bare(log.feed("committed Backfill wordplay.anagramCharade for azed-2689", T + 32)),
      ["· azed-2689 nothing to change (1 clue) [re-shape anagram fodder filed as a charade]"], "a run that changed nothing is quiet")
check(bare(run(["  [azed-2422] skipped: already fully hinted and nothing is due on it"])),
      ["· azed-2422 nothing to change (already hinted)"], "a skipped puzzle is quiet")
log2 = B.Log()
check(bare(log2.feed("committed Backfill some.unknownKey for azed-5", T)), ["✓ azed-5 backfilled some.unknownKey"],
      "a field with no phrase shows its key")

log = B.Log()
got = []
for i in range(15):
    got += log.feed(f"  [azed-{1000 + i}] started", T + 5 * i)
got += log.feed("sync: tree at x", T + 200)
check(bare(got), ["▶ started 15: azed-1000, azed-1001, azed-1002, … (+12)"], "a pool fill is one line")
log = B.Log()
log.feed("  [azed-1] started", T)
check(log.feed("sync: tree at x", T + 200), [], "one or two starts are not a fill")

log = B.Log()
got = []
for line in ["=== pre-reset backfill re-execed onto 35ec545 2026-11-03 10:00 ===", WIDTH,
             "--- pool of 15: 3 in flight (3 running), 40 queued ---", "adopted 3 runs in flight: 1 2 3"]:
    got += log.feed(line, T)
check(bare(got), ["── restarted on 35ec545, 3 runs carried on",
                  "── 15 at once (memory) · 0 done/h · 0 no-change/h · 40 queued · weekly 98% used"],
      "a restart says so and restates the status at once")

log = B.Log()
log.feed(WIDTH, T)
check(bare(log.feed("sync: tree at x", T + 301)), ["── 15 at once (memory) · 0 done/h · 0 no-change/h · weekly 98% used"],
      "the status is written every five minutes")

check(bare(run(["ERROR: boom", "ERROR: boom"])), ["⚠️ ERROR: boom"], "a problem is said once inside the repeat window")

# Waste: a run that changed nothing is a quiet line, and an hour of them is one warning and one wake.
log = B.Log()
sent = []
log.notify = sent.append
got = log.feed("Annotate azed-9 produced no change", T)
check(bare(got), ["· azed-9 nothing to change [annotate]"], "no-change run, quiet line")
lines = []
for i in range(30):
    lines += log.feed(f"Annotate x-{i} produced no change", T + 10 + i)
for i in range(10):
    lines += log.feed(f"committed Annotate y-{i}", T + 50 + i)
warns = [x for x in lines if "⚠️" in x]
check(len(warns) >= 1 and "wasted runs" in warns[0], True, "an hour of no-change runs warns")
check(len(sent), 1, "the warning wakes the room once")
check(sent[0].startswith("Burn: wasted runs") and sent[0].count("\n") == 3, True, "the wake carries the line and three lines of evidence")
more = log.feed("ERROR: boom", T + 100) + log.feed("ERROR: other", T + 101)
check(len(sent), 2, "a different kind of warning wakes once")
log.feed("ERROR: third thing", T + 102)
check(len(sent), 2, "a second ERROR inside the hour is counted, not sent")
for pid in ("p-1", "p-1"):
    rep = log.feed(f"Annotate {pid} produced no change", T + 200)
check([x for x in rep if "twice" in x][:1] != [], True, "the same puzzle twice is a warning line")
check(len(sent), 2, "a repeat puzzle alone does not wake")
ordinary = B.Log()
ordinary.notify = sent.append
ordinary.feed(WIDTH, T)
ordinary.feed("committed Annotate z-1", T + 1)
check(len(sent), 2, "a status or a commit never wakes")

# Tokens per clue: one run per puzzle at 17k tokens a clue is an alarm; the status line shows the rate.
log = B.Log()
sent = []
log.notify = sent.append
log.tokens_of = lambda pid: 45_000
log.feed(WIDTH, T)
lines = []
for i in range(6):
    lines += log.feed(f"committed Backfill wordplay.anaStandIn for azed-{100 + i}", T + 10 + i)
check(any("tokens per clue: re-shape anagram stand-ins ran at 45k tokens per clue" in x for x in lines), True,
      "45k tokens a clue warns, naming the rule")
check(len(sent), 1, "and wakes the room once")
check(any("45k tok/clue" in x for x in log.feed("sync: tree at x", T + 400)), True, "the status line carries tokens per clue")
log = B.Log()
log.tokens_of = lambda pid: 12_000
lines = []
for i in range(8):
    lines += log.feed(f"committed Backfill wordplay.anaStandIn for azed-{100 + i}", T + i)
check([x for x in lines if "tokens per clue" in x], [], "12k tokens a clue (a bag) is fine")

# A blog re-check, kept-only or changed, counts its tokens too: the status line shows tok/clue during it.
log = B.Log()
log.tokens_of = lambda pid: 8_000
log.feed(WIDTH, T)
for i in range(3):
    log.feed(f"Re-check against its blog: quiptic-{200 + i} kept ours on 2 clues", T + 10 + i)
    log.feed(f"committed Re-check against its blog: quiptic-{200 + i}", T + 10 + i)
check(any("4k tok/clue" in x for x in log.feed("sync: tree at x", T + 400)), True,
      "blog re-checks (6 clues, 24k tokens) show tok/clue on the status line")

sys.exit(1 if fails else 0)
