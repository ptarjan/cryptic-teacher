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
check(bare(run([WIDTH])), ["── 15 at once (limit: memory) · 0 done last hour · week 98% used, resets in 19h"],
      "a width line becomes a status line naming the cap that binds")
check(bare(run(["width 22 (cap: memory 22, cpu —, load —, quota pace 22) · weekly 50% now, 80.0h to its reset"])),
      ["── 22 at once (limit: memory) · 0 done last hour · week 50% used, resets in 80h"],
      "a tie between caps names the first in order")
check(bare(run(["width 0 (cap: memory 0, cpu —, load —, quota pace 0) · weekly 100% now, 3.0h to its reset"])),
      ["── paused: week 100% used, resets in 3h"], "width 0 with the week spent is a pause")
check(len(run([WIDTH, WIDTH])), 1, "the same width twice says nothing new")

check(bare(run(["committed Annotate azed-2702"])), ["✓ azed-2702 hints written"], "annotate commit")
check(bare(run(["committed Backfill wordplay.anaLoneEdge for azed-2581"])),
      ["✓ azed-2581 backfilled wordplay.anaLoneEdge"], "backfill commit")
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

check(bare(run(["--- pool of 6: 0 in flight (0 running), 0 queued ---"] * 2)), ["── idle: nothing queued"],
      "idle is said once")
check(bare(run(["ERROR: boom", "ERROR: boom"])), ["⚠️ ERROR: boom"], "a problem is said once inside the repeat window")

log = B.Log()
got = []
for i, line in enumerate([WIDTH, "committed Annotate a-1", "committed Annotate b-2"]):
    got += log.feed(line, T + i)
got += log.feed("--- pool of 15: 3 in flight (3 running), 9 queued ---", T + 20 * 60)
check(bare(got)[-1], "── 15 at once (limit: memory) · 2 done last hour · week 98% used, resets in 19h",
      "the status repeats after 15 minutes when puzzles ended")

sys.exit(1 if fails else 0)
