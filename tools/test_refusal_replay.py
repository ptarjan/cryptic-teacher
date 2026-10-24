#!/usr/bin/env python3
# Does the wake's refusal section replay, group, count retries and name a cause?
#
#     python3 tools/test_refusal_replay.py
#
# A small fixture transcript holds one refusal that clears on the next check and
# one that never does; the evaluator is stubbed so the test needs no puzzles.
import datetime
import json
import os
import sys
import tempfile
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "tools")
import annotate_audit as aud
import refusal_replay as r

fails = 0
def check(got, want, what):
    global fails
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'}: {what}" + ("" if ok else f"\n    got {got!r}, wanted {want!r}"))
    fails += not ok

def refused(eid, ans, wp):
    return f"  {eid}: the wordplay does not give {ans}: {wp} gives XX; the answer needs {ans}\n"

def turn(i, report):
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{i}",
              "input": {"command": "python3 tools/annotate_check.py abc-1"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}",
              "content": report}]}}]

recs = [{"type": "user", "message": {"content": aud.BAG_PREFIX + " abc-1"}}]
recs += turn(1, refused("1-across", "CAT", "c + a, t") + refused("2-down", "DOG", "d + o + g"))
recs += turn(2, refused("2-down", "DOG", "d + o + g"))
recs += turn(3, "clean")
d = tempfile.mkdtemp()
path = os.path.join(d, "sess1234.jsonl")
with open(path, "w") as f:
    f.write("\n".join(json.dumps(x) for x in recs))

since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
items = {i["eid"]: i for i in r.refusals([path], since)}
check(sorted(items), ["1-across", "2-down"], "each refused entry is found once")
check((items["1-across"]["retries"], items["1-across"]["cleared"]), (1, True), "a refusal that clears costs 1 retry")
check((items["2-down"]["retries"], items["2-down"]["cleared"]), (2, True), "a refusal that clears on the third check costs 2")

# 10-24: a refusal line of another shape (here no "gives ...; the answer needs") crashed the
# audit section with StopIteration; the one that reads is still found, the other skipped.
odd = ("  3-down: the wordplay does not give EASEL; clue words no leaf, indicator or definition "
       "covers (a piece may be missing, or they are link words): 'after'\n")
recs2 = [{"type": "user", "message": {"content": aud.BAG_PREFIX + " abc-1"}}]
recs2 += turn(1, odd + refused("4-down", "ROLE", "r + o"))
recs2 += turn(2, "clean")
path2 = os.path.join(d, "sess5678.jsonl")
with open(path2, "w") as f:
    f.write("\n".join(json.dumps(x) for x in recs2))
check(sorted(i["eid"] for i in r.refusals([path2], since)), ["4-down"], "an unreadable refusal line is skipped, not a crash")

# stub the evaluator: only the comma form passes, and the long one is a reorder
def fake(wp, clue, ans):
    return None if "," in wp and ans != "BAD" else f"{ans}: wordplay gives {'ACT' if ans == 'CAT' else 'ZZZ'}; the answer needs {ans}"
r.try_translate = fake
r.clue_text = lambda index, pid, eid: "a clue"
rep = r.replay(list(items.values()), index={})
by = {i["eid"]: i for i in rep}
check(by["1-across"]["now"], "fixed", "an already-fixed refusal is counted as fixed")
check(by["2-down"]["now"], "fails", "a still-failing refusal stays failing")
check(by["2-down"]["rewrite"], "+ to comma", "a notation slip is rescued by the known rewrite")
check(r.cause([by["2-down"]])[0].split(" (")[0], "likeliest cause: notation slip, so prompt or message", "rewrite share names a slip")
check(r.cause([dict(rewrite=None, msg="x gives ACT", ans="CAT")])[0].split(" (")[0],
      "likeliest cause: evaluator gap", "right letters in the wrong order name an evaluator gap")
check(r.cause([dict(rewrite=None, msg="x gives ZZZ", ans="CAT")])[0].split(" (")[0],
      "likeliest cause: model parse error", "neither names a parse error")
check(r._hid_reversed("hid<held>([x]PASTERNAK)", "KANRETS"), "rev(hid<held>([x]PASTERNAK))", "hid over a reversed leaf is wrapped in rev")
check(r._hid_reversed("hid<held>([x]PASTERNAK)", "STERN"), "hid<held>([x]PASTERNAK)", "a forward hit is left alone")
check(r._ins_swapped("ins<in>(DIY, [x]RA)", ""), "ins<in>([x]RA, DIY)", "ins arguments are swapped")
check(r._ins_inner_reversed("ins<in>([a]DIY, [b]RA)", ""), "ins<in>([a]DIY, rev([b]RA))", "ins inner argument is reversed")
check(r._ins_swapped("ins<in>(a, b, c)", ""), "ins<in>(a, b, c)", "three arguments are not a swap")

text = r.report(rep)
check("2 distinct refused wordplays, 1 still fail, 1 already fixed" in text, True, "the replay counts lead the report")
check("d + o + g" in text and "a clue" in text, True, "a real example carries clue and wordplay")
check(len(r.report(rep, 200)) <= 200, True, "the budget is a hard cap")

# the wake stays under the cap even with a long section
item = {"title": "t", "detail": "d", "key": r.__name__, "share": 0.1}
aud.share = lambda i: "10%"
cur = {"n": 3, "turns": 5, "cost_per_puzzle": 1.0, "first_fail": 0.2}
check(len(aud.wake_text(item, "why", cur, "line\n" * 900)) <= aud.WAKE_CAP, True, "the wake text stays under the cap")

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
