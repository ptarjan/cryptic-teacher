#!/usr/bin/env python3
# Does the cost ledger wake the room only when $/clue drifts or a new cause leads?
#
#     python3 tests/test_annotate_ledger.py
#
# Fake ledger rows in, wake / no-wake decisions out (tools/annotate_ledger.py).
import datetime
import json
import os
import pathlib
import sys
import tempfile
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path
import annotate_audit as A
import annotate_ledger as L

# Hermetic: the live /progress/ backlog must not decide these checks. 1,000 clues left makes
# a $0.01/clue cause save $5 (< the $6 fix cost) and a $0.025/clue one $12.50.
CLUES_LEFT = 1000
L.clues_left = lambda mean_clues, days=None: CLUES_LEFT  # set via left(n) below
L.NO_LEVER = pathlib.Path("/nonexistent/annotate_no_lever.json")
L.PENDING_NO_LEVER = pathlib.Path("/nonexistent/annotate_no_lever_pending.json")
L.in_main_checkout = lambda repo=None: False   # CI runs in a main checkout; each check below sets its own

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
today = now.date().isoformat()
nl = {"rule:a": {"per_clue": 0.01, "date": today, "count": 3}}
check(L.should_wake(flat, None, quiet, now, nl)[0], None, "no-lever cause, same $/clue: quiet")
check("investigated 3 times, last " + today in L.should_wake(flat, None, quiet, now, nl)[1], True,
      "a muted cause is mentioned as investigated N times, last <date>")
check(L.should_wake(worse, fix, quiet, now, nl)[0], None,
      "no-lever holds across a new annotate-code commit (11-19: no lapse on commits)")
check(L.should_wake(flat, None, quiet, now, {"rule:a": {"per_clue": 0.0066, "date": today}})[0] is not None,
      True, "no-lever cause whose $/clue rose past 1.5x the recorded: wakes again")
check(L.should_wake(flat, None, quiet, now, {"rule:a": {"per_clue": 0.0070, "date": today}})[0], None,
      "no-lever cause under 1.5x the recorded $/clue: quiet")
check(L.should_wake(flat, None, quiet, now, {"rule:b": {"per_clue": 0.01, "date": today}})[0] is not None,
      True, "no-lever on a different cause does not mute this one")
rec = {"per_clue": 0.01, "date": "2026-11-01"}
d14, d15 = datetime.datetime(2026, 11, 15, 12, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 11, 16, 12, tzinfo=datetime.timezone.utc)
check((L.muted(rec, 0.01, d14), L.muted(rec, 0.01, d15)), (True, False), "muted for 14 days, then lapses")
check(L.muted(rec, 0.0149, d14), True, "under 1.5x: muted")
check(L.muted(rec, 0.015, d14), False, "at 1.5x: lifted")
check(L.muted(None, 0.01, d14), False, "no record: not muted")
check(L.investigated({"date": "2026-11-01"}), "investigated 1 time, last 2026-11-01", "an old record counts once")
# each prior investigation adds $6 to the assumed fix cost: $0.01 x 1,000 x 0.5 = $5 here
left(2400)   # saving $12: worth the $6 fix, not worth $12 (count 1) or $18
check(L.should_wake(flat, None, quiet, now)[0] is not None, True, "no record: $12 saving beats the $6 fix")
check(L.should_wake(flat, None, quiet, now, {"rule:a": {"per_clue": 0.001, "date": "2026-01-01", "count": 1}})[0],
      None, "after one investigation the fix costs $12: $12 saving is not worth it")
left(10 ** 9)   # a big backlog, so the saving beats any fix cost and facts is the dict
check(L.should_wake(flat, None, quiet, now)[1]["fix_cost"], 6.0, "no record: the base fix cost")
check(L.should_wake(flat, None, quiet, now, {"rule:a": {"per_clue": 0.001, "date": "2026-01-01", "count": 2}})[1]["fix_cost"],
      18.0, "two investigations: the base plus $12")
# the horizon is the clues the burn does in 30 days: flat rows do 100 clues an hour
check(L.burn_clues_per_day(flat), 2400.0, "burn pace from the recent rows' clues/hour")
left(10 ** 9)
_, facts = L.should_wake(flat, None, quiet, now)
check(facts["left"], 2400.0 * 30, "payback horizon capped at 30 days of burn")
left(1000)   # saving $5 is under the $6 fix, so no wake and facts is the reason string: cheapen the fix to see the facts
fix_cost, L.FIX_COST = L.FIX_COST, 1.0
_, facts = L.should_wake(flat, None, quiet, now)
L.FIX_COST = fix_cost
check(facts["left"], 1000, "a smaller backlog still bounds it")
# a not-worth-fixing wake drops the instruction to spawn a fixer
cheap_facts = {"cur": 0.04, "best": 0.03, "saving": 1.0, "left": 100, "per_clue": 0.01, "fix_cost": 12.0,
               "rate": 0.5, "investigated": "investigated 2 times, last 2026-11-01"}
t = L.work_order("why", cheap_facts, worse, ("abc123", "x", "Annotate fix"))
check(("Sonnet worker" in t, "not worth a fix" in t, "investigated 2 times" in t), (False, True, True),
      "not worth fixing: no 'have one Sonnet worker fix it', and the investigation count shows")
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d)
    saved = L.NO_LEVER
    L.NO_LEVER = d / "data" / "nl.json"
    check(L.read_no_lever(), {}, "no repo file: empty book")
    rows5 = [row(i, 0.04) for i in range(1, 4)]
    r1 = L.mark_no_lever("rule:a", rows5, (None, None, None), now)
    r2 = L.mark_no_lever("rule:a", rows5, (None, None, None), now)
    check((r1["count"], r2["count"]), (1, 2), "re-marking the same key counts the investigation")
    # The burn's worktree has only the pushed repo book: a record from another checkout reaches it
    # through the pending book outside every checkout.
    saved_p = L.PENDING_NO_LEVER
    L.PENDING_NO_LEVER = d / "pending.json"
    L.mark_no_lever("rule:a", rows5, (None, None, None), now)
    L.NO_LEVER = d / "burn" / "nl.json"
    L.NO_LEVER.parent.mkdir()
    L.NO_LEVER.write_text(json.dumps({"rule:a": {"date": "2000-01-01", "count": 1}}))
    check(L.read_no_lever()["rule:a"]["count"], 3, "a pending record newer than the repo book's wins")
    L.NO_LEVER.write_text(json.dumps({"rule:a": {"date": "2999-01-01", "count": 9}}))
    check(L.read_no_lever()["rule:a"]["count"], 9, "an older pending record never undoes a newer pushed one")
    # In the main checkout the tracked file stays untouched; only the pending cache is written.
    L.NO_LEVER = d / "main" / "nl.json"
    L.PENDING_NO_LEVER = d / "pending2.json"
    L.in_main_checkout = lambda repo=None: True
    L.mark_no_lever("rule:a", rows5, (None, None, None), now)
    check((L.NO_LEVER.exists(), "rule:a" in json.loads(L.PENDING_NO_LEVER.read_text())), (False, True),
          "main checkout: pending cache only, tracked file not written")
    L.in_main_checkout = lambda repo=None: False
    L.mark_no_lever("rule:a", rows5, (None, None, None), now)
    check(json.loads(L.NO_LEVER.read_text())["rule:a"]["count"], 2, "worktree: tracked file written with pending folded in")
    L.PENDING_NO_LEVER = saved_p
    L.NO_LEVER = saved
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

# Hint-backfill rows (kind "hint") are their own line in the ledger: the review reports their
# $/clue apart, and no wake rule or window ever counts them with annotation's.
check(A.session_kind("Annotate these crosswords in this one session: a-1 a-2. Read"), "annotate", "a bag is annotation")
check(A.session_kind("These crosswords are already annotated, and their hints are fine"), "hint", "a shape/blog bag is hint backfill")
check(A.session_kind("In this repo, add the missing features to every annotated clue in @PATH@"), "hint", "a field backfill is hint backfill")
check(A.session_kind("Fix the validator"), None, "other runs are neither")
res = {"since": "a", "until": "b", "sessions": 3, "puzzles": 4, "clues": 40, "cost": 2.0,
       "cost_per_clue": 0.05, "turns_per_clue": 1.0, "first_fail": None, "causes": []}
hrow = L.make_row(res, "abc", L.HINT)
check(hrow["kind"], "hint", "a hint row carries kind=hint")
check("kind" in L.make_row(res, "abc"), False, "an annotation row has no kind field, as before")
mixed = flat + [hrow, dict(hrow, cost=100.0, end=(T0 + datetime.timedelta(hours=9)).isoformat())]
with tempfile.TemporaryDirectory() as d:
    path = pathlib.Path(d) / "ledger.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in mixed))
    check(len(L.read_ledger(path)), len(flat), "read_ledger returns annotation rows only")
    check(len(L.read_ledger(path, kind=L.HINT)), 2, "hint rows are read on request")
rep = L.report(mixed)
check(round(rep["annotate"]["cost_per_clue"], 4), 0.04, "annotate $/clue ignores hint rows")
check(round(rep["hint"]["cost_per_clue"], 4), round(102.0 / 80, 4), "hint $/clue is its own")

# 11-21 (Paul: "Price isn't the thing to optimized. It is wall time"): rows with wall time are
# judged in wall s/clue, the top cause is the one adding the most wall minutes, the payback
# counts burn hours against agent-minutes, and an acknowledged cause stays quiet.
def wrow(i, wall_min, top="rule:a", cause_min=6.0, sessions=5):
    r = row(i, 0.040, top)
    r["wall_min"] = wall_min
    r["top_causes"] = [{"key": top, "label": top, "sessions": sessions, "cost_after_check": 1.0,
                        "wall_after_check_min": cause_min}]
    return r
left(10 ** 6)
wflat = [wrow(i, 100.0) for i in range(1, 7)]   # 100 min over 100 clues = 60 s/clue
check(L.wall_level(wflat[:1]), 60.0, "wall s/clue is session wall over clues")
check(L.wall_level([wflat[0], row(9, 0.04)]), None, "a window with a row lacking wall time is judged in dollars")
check(L.cause_wall(wflat, "rule:a"), (3.6, 6.0, 0.5), "cause: 6 min over 100 clues = 3.6 s/clue, 6 min/h, 5/10 sessions")
reason, facts = L.should_wake(wflat, None, quiet, now)
check((facts["timed"], round(facts["saving_h"], 2), facts["fix_min"]), (True, round(3.6 * min(1e6, L.burn_clues_per_day(wflat) * L.PAYBACK_DAYS) * 0.5 / 3600, 2), 30.0),
      "payback counted in burn hours over a 30 agent-min fix")
check(("s/clue after check" in reason, "agent-min fix" in reason, "$" in reason.split("fix")[0]), (True, True, True),
      "reason speaks wall time with dollars as a side column")
wbad = wflat[:5] + [wrow(6, 200.0)]
left(100)   # payback too small to wake on its own, so the wall regression decides
check(L.should_wake(wflat, None, quiet, now)[0], None, "flat wall time, small backlog: quiet")
check("s/clue is +" in (L.should_wake(wbad, None, quiet, now)[0] or ""), True,
      "wall s/clue 10%+ over the best wakes even with $/clue flat")
left(10 ** 6)
# a cause's rank is by wall minutes, not dollars or sessions
rank = sorted([{"key": "x", "wall_after_check_min": 1.0, "sessions": 9, "cost_after_check": 5.0},
               {"key": "y", "wall_after_check_min": 4.0, "sessions": 1, "cost_after_check": 0.1}],
              key=lambda c: (-c["wall_after_check_min"], -c["sessions"], -c["cost_after_check"], c["key"]))
check(rank[0]["key"], "y", "most wall time first")
mr = L.make_row({"since": "a", "until": "b", "sessions": 3, "puzzles": 4, "clues": 40, "cost": 2.0,
                 "cost_per_clue": 0.05, "turns_per_clue": 1.0, "first_fail": None, "wall_min": 30.0,
                 "wall_s_per_clue": 45.0, "causes": [{"key": "k", "label": "k", "sessions": 1, "share": 0.3,
                                                      "cost_after_check": 0.1, "wall_after_check_min": 2.5}]}, "abc")
check((mr["wall_min"], mr["top_causes"][0]["wall_after_check_min"]), (30.0, 2.5), "the row records wall time")
# acknowledged cause: quiet until its wall s/clue rises 1.5x or 14 days pass
ack = {"rule:a": {"per_clue": 0.0001, "wall_s_per_clue": 3.6, "date": today, "count": 1}}
check(L.should_wake(wflat, None, quiet, now, ack)[0], None, "acknowledged cause, same wall share: quiet")
check("marked no-lever" in L.should_wake(wflat, None, quiet, now, ack)[1], True, "...and says why")
check(L.should_wake(wflat, None, quiet, now, {"rule:a": dict(ack["rule:a"], wall_s_per_clue=2.0)})[0] is not None,
      True, "wall share 1.8x the acknowledged: re-alerts")
wf = L.should_wake(wflat, None, quiet, now, ack)
text = L.work_order("why", L.should_wake(wflat, None, quiet, now)[1], wflat, ("abc123", "x", "Annotate fix"))
check(all(s in text for s in ("Annotate wall time: 60.0 s/clue", "burn hours", "agent-min to fix",
                              "Optimise WALL TIME", "--no-lever", "ONE Sonnet worker")), True,
      "the work order headlines wall time, pays back in time, and tells the agent to acknowledge")
check("$81" in text or "vs ~$6" in text, False, "the dollar payback framing is gone")

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
