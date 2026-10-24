#!/usr/bin/env python3
# Does the cost ledger wake the room only when $/clue drifts or a new cause leads?
#
#     python3 tools/test_annotate_ledger.py
#
# Fake ledger rows in, wake / no-wake decisions out (tools/annotate_ledger.py).
import datetime
import os
import pathlib
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "tools")
import annotate_ledger as L

# Hermetic: the live /progress/ backlog must not decide these checks. 1,000 clues left makes
# a $0.01/clue cause save $5 (< the $6 fix cost) and a $0.025/clue one $12.50.
CLUES_LEFT = 1000
L.clues_left = lambda mean_clues, days=None: CLUES_LEFT  # set via left(n) below
L.NO_LEVER = pathlib.Path("/nonexistent/annotate_no_lever.json")

fails = 0
def check(got, want, what):
    global fails
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'}: {what}" + ("" if ok else f"\n    got {got!r}, wanted {want!r}"))
    fails += not ok

T0 = datetime.datetime(2026, 10, 20, 0, 0, tzinfo=datetime.timezone.utc)
def row(i, per_clue, top="rule:a"):
    end = T0 + datetime.timedelta(hours=i)
    return {"start": (end - datetime.timedelta(hours=1)).isoformat(), "end": end.isoformat(),
            "sessions": 10, "clues": 100, "cost": per_clue * 100, "cost_per_clue": per_clue,
            "top_causes": [{"key": top, "label": top, "sessions": 5, "cost_after_check": 1.0}]}
now = T0 + datetime.timedelta(hours=20)
quiet = {"woken": (T0 - datetime.timedelta(hours=30)).isoformat(), "top": "rule:a"}

flat = [row(i, 0.040) for i in range(1, 7)]
check(L.should_wake(flat, None, quiet, now)[0], None, "flat $/clue, same cause: quiet")
fix2 = (T0 + datetime.timedelta(hours=5.5)).isoformat()
check(L.should_wake(flat, fix2, quiet, now)[0], None, "1 row after a code commit: not yet")
def left(n):
    global CLUES_LEFT
    CLUES_LEFT = n
left(10000)  # $0.01/clue x 10,000 clues x 0.5 = $50 > the $6 fix: the payback wakes
check(L.should_wake(flat, (T0 + datetime.timedelta(hours=4.5)).isoformat(), quiet, now)[0] is not None,
      True, "2 rows after a code commit, big payback: wake")
left(1000)
bad = flat[:5] + [row(6, 0.157)]
check(L.should_wake(bad, None, quiet, now)[0] is not None, True, "one bad row is not averaged away")
thin = dict(row(6, 0.157), clues=20, cost=3.14)
check(L.should_wake(flat[:5] + [thin], None, quiet, now)[0] is not None, True,
      "a thin bad row merges with the row before and still wakes")
check(L.should_wake([dict(thin, clues=10), dict(thin, clues=10)], None, quiet, now)[0], None,
      "under 50 clues even merged: noise, quiet")

worse = [row(i, 0.030) for i in range(1, 4)] + [row(i, 0.040) for i in range(4, 7)]
check(L.should_wake(worse, None, quiet, now)[0] is not None, True, "rolling 33% over best: wake")
fix = (T0 + datetime.timedelta(hours=3.5)).isoformat()
check(L.should_wake(worse, fix, dict(quiet, commit=fix), now)[0], None,
      "rows before the last annotate-code commit do not set the best level")
left(10000)
check(L.should_wake(worse, fix, quiet, now)[0] is not None, True,
      "big payback 3 rows after a new annotate-code commit: wake for the next cause")
left(1000)

mild = [row(i, 0.040) for i in range(1, 4)] + [row(i, 0.043) for i in range(4, 7)]
check(L.should_wake(mild, None, quiet, now)[0], None, "7.5% over best: quiet")

left(10000)
check(L.should_wake(flat, None, quiet, now)[0] is not None, True, "big payback, flat $/clue: wake")
# no-lever: the room investigated the cause and found nothing to fix.
nl = {"rule:a": {"per_clue": 0.01, "commit_time": None}}
check(L.should_wake(flat, None, quiet, now, nl)[0], None, "no-lever cause, same $/clue: quiet")
nl_c = {"rule:a": {"per_clue": 0.01, "commit_time": fix}}
check(L.should_wake(worse, fix, quiet, now, nl_c)[0], None, "no-lever cause, same last commit: quiet")
check(L.should_wake(worse, fix, quiet, now, nl)[0] is not None, True,
      "no-lever recorded before a NEW annotate-code commit: wakes again")
check(L.should_wake(flat, None, quiet, now, {"rule:a": {"per_clue": 0.0066, "commit_time": None}})[0] is not None,
      True, "no-lever cause whose $/clue rose past 1.5x the recorded: wakes again")
check(L.should_wake(flat, None, quiet, now, {"rule:a": {"per_clue": 0.0070, "commit_time": None}})[0], None,
      "no-lever cause under 1.5x the recorded $/clue: quiet")
check(L.should_wake(flat, None, quiet, now, {"rule:b": {"per_clue": 0.01, "commit_time": None}})[0] is not None,
      True, "no-lever on a different cause does not mute this one")
left(1000)

recent = {"woken": (now - datetime.timedelta(minutes=30)).isoformat(), "top": "rule:a"}
check(L.should_wake(worse, None, recent, now)[0], None, "woken 30 min ago: 1h cooldown holds")

cheap = [row(i, 0.020) for i in range(1, 4)] + [row(i, 0.021) for i in range(4, 7)]
check(L.should_wake(cheap, None, quiet, now)[0], None, "at the $0.022 target: quiet")

def hot(r, spend):
    return dict(r, top_causes=[dict(r["top_causes"][0], cost_after_check=spend)])
burning = cheap[:5] + [hot(cheap[5], 2.5)]
check("$0.0125/clue" in (L.should_wake(burning, None, quiet, now)[0] or ""), True,
      "under target but the top cause saves $6.25 > the $6 fix (1,000 clues left): wake")
check(L.should_wake(burning, None, recent, now)[0], None, "under target, burning, but inside the 1h cooldown: quiet")
check(L.should_wake(cheap[:5] + [hot(cheap[5], 1.9)], None, quiet, now)[0], None,
      "under target and the saving $5.75 is under the $6 fix: quiet")

text = L.work_order("why", {"cur": 0.04, "best": 0.03}, worse, ("abc123", "x", "Annotate fix"))
check(all(s in text for s in ("$0.040", "rule:a", "abc123", "ONE Sonnet worker")), True,
      "the work order carries the rows, top cause, last commit and the instruction")

# 10-24: the alert named 93e60a8b958 as the last annotate-code commit while two fixes to
# the refusal in tools/wordplay.py had landed: the evaluator and the check modules count.
check([p for p in ("tools/wordplay.py", "tools/apply_annotations.py", "tools/annotate_check.py",
                   "tools/find_answer_leaks.py") if p not in L.CODE_PATHS and not p.startswith("tools/annotate")],
      [], "the evaluator and the modules the checks import are annotate code")

# 10-24: the payback said ~7.8M clues left: backlog + filing inflow x horizon (290k puzzles)
# exceeded the 153k puzzles known but not hinted. Filing cannot outrun the corpus.
import progress
_nt, _fs, _rt = progress.nested_totals, progress.funnel_series, progress.rate
progress.nested_totals = lambda d: (175657, 79515, 62662, 47558, 22379)
progress.funnel_series = lambda days, i: i
progress.rate = lambda s, n: 585.0 if s == 4 else 952.0
back, inflow, hor = L.backlog_counts({"2026-10-23": {}})
progress.nested_totals, progress.funnel_series, progress.rate = _nt, _fs, _rt
check(round(back + inflow * hor), 175657 - 22379, "backlog + inflow never exceeds known less hinted")

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
