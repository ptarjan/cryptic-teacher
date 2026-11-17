#!/usr/bin/env python3
# The 'wordplay does not give the answer' refusals of the 11-16 annotate runs: an anagram whose fodder
# carries a link word ('and', 'a', 'the') is mended, a leaf whose clue word the table abbreviates another way
# (CO for OC, M for MI) is swapped when that alone gives the answer, and the audit replay counts refusals it cannot replay.
#
#     python3 tests/test_refusal_mends.py
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path
import wordplay as W
import refusal_replay as R

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

def tr(wp, clue, ans):
    try:
        return W.render(W.translate({"wp": wp, "notes": {}}, clue, ans))
    except W.WordplayError as e:
        return "REFUSED: " + str(e)

out = tr("ana<smashing>([Lion] + [and] + [ape])", "Lion and ape smashing glass", "OPALINE")
check("an anagram's middle link word 'and' is dropped (OPALINE)", not out.startswith("REFUSED") and "and" not in out)
out = tr("ana<disaster>([a real])", "Haig was a real disaster", "EARL")
check("a leading 'a' in a one-leaf fodder is trimmed (EARL)", not out.startswith("REFUSED") and "[real]" in out)
out = tr("ana<broken>([the leg rotten])", "If broken the glass might make the leg rotten", "LORGNETTE")
check("a leading 'the' in a one-leaf fodder is trimmed (LORGNETTE)", not out.startswith("REFUSED") and "[leg rotten]" in out)
out = tr("ana<smashing>([Lion] + [and] + [ape] + [glass])", "Lion and ape smashing glass", "OPALINE")
check("a fodder two words too long is not guessed at", out.startswith("REFUSED"))
out = tr("ana<disaster>([real])", "Haig was a real disaster", "EARL")
check("an anagram that already fits is untouched", out == "ana<disaster>([real])")

out = tr("ins<entry is in>([New]LATE, [officer]CO)", "New officer entry is in place", "LOCATE")
check("CO for 'officer' is mended to the table's OC (LOCATE)", not out.startswith("REFUSED") and "[officer]OC" in out)
out = tr("ins<taking in>([grant]DONATION, [motorway]M)", "Government grant taking in motorway", "DOMINATION")
check("[motorway]M is mended to the table's MI when only that gives the answer (DOMINATION)",
      not out.startswith("REFUSED") and "[motorway]MI" in out)
out = tr("ins<taking in>([grant]DONATION, [motorway]M)", "Government grant taking in motorway", "DONATIONS")
check("an abbreviation swap that does not give the answer stays refused", out.startswith("REFUSED"))

# a refusal whose clue is not on this host is counted, not dropped
item = {"pid": "no-such-puzzle-0", "eid": "1-across", "ans": "ABC", "wp": "[x]AB", "sess": "s", "retries": 0,
        "cleared": True}
rows = R.replay([item], index={})
check("replay keeps a refusal whose clue it cannot find", len(rows) == 1 and rows[0]["now"] == "unreplayed")
check("replay's report counts them", "1 could not be replayed" in R.report(rows))

sys.exit(1 if fails else 0)
