#!/usr/bin/env python3
# Does the burn's human log say, line by line, what each puzzle did and how wide it runs?
#
#     python3 tests/test_burn_log.py
#
# Raw burn lines in, human lines out (tools/burn_log.py); noise out.
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "tools")
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
check(bare(run([WIDTH])), ["── 15 at once (memory) · 0 done/h · weekly 98% used"],
      "a width line becomes a status line naming the cap that binds")
check(bare(run(["width 22 (cap: memory 22, cpu —, load —, quota pace 22) · weekly 50% now, 80.0h to its reset"])),
      ["── 22 at once (memory) · 0 done/h · weekly 50% used"],
      "a tie between caps names the first in order")
check(bare(run(["width 0 (cap: memory 0, cpu —, load —, quota pace 0) · weekly 100% now, 3.0h to its reset"])),
      ["── paused: weekly 100% used, resets in 3h"], "width 0 with the week spent is a pause")
check(len(run([WIDTH, WIDTH])), 1, "the same width twice says nothing new")

check(bare(run(["committed Annotate azed-2702"])), ["✓ azed-2702 hints written"], "annotate commit")
check(bare(run(["committed Backfill wordplay.anaLoneEdge for azed-2581"])),
      ["✓ azed-2581 re-shaped anagram of a lone edge letter"], "backfill commit")
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
         "(JSON: `entries` is a list of strings", "x-1 failed on this puzzle and is skipped until it changes"]
check(run(noise), [], "debug lines produce nothing")

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
                  "── 15 at once (memory) · 0 done/h · 290 queued · weekly 98% used"],
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
      ["· azed-2689 nothing to change (1 clue)"], "a run that changed nothing is quiet")
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
                  "── 15 at once (memory) · 0 done/h · 40 queued · weekly 98% used"],
      "a restart says so and restates the status at once")

log = B.Log()
log.feed(WIDTH, T)
check(bare(log.feed("sync: tree at x", T + 301)), ["── 15 at once (memory) · 0 done/h · weekly 98% used"],
      "the status is written every five minutes")

check(bare(run(["ERROR: boom", "ERROR: boom"])), ["⚠️ ERROR: boom"], "a problem is said once inside the repeat window")

sys.exit(1 if fails else 0)
