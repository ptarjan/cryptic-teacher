#!/usr/bin/env python3
# The mend for an anagram inside a deletion, del(ana(F), D): it becomes comp(F, D) when that gives the answer;
# an anagram inside a substitution stays as filed (refused).
#
#     python3 tests/test_mend_ana_deletion.py
import _path  # puts tools/ on sys.path
import mend_ana_deletion as M
import wordplay

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


CLUE = "Perhaps someone has lost a rare sapphire"
WP = "del<lost>(ana<rare>([sapphire]), [someone]I)"


def gives(wp):
    try:
        wordplay.evaluate(wordplay.parse(wp, CLUE), "PERHAPS")
        return True
    except wordplay.WordplayError:
        return False


a = {"wp": WP}
check("the filed shape is refused", not gives(WP))
check("the mend reports a change", M.mend(a, CLUE, "PERHAPS"))
check("the new wp is a comp", a["wp"].startswith("comp<lost><rare>("))
check("the new wp gives the answer", gives(a["wp"]))
check("a wrong answer is not mended", not M.mend({"wp": WP}, CLUE, "PERHAPT"))
check("an anagram under sub is left alone",
      not M.mend({"wp": "sub<lost>(ana<rare>([sapphire]), [someone]I, [a]A)"}, CLUE, "PERHAPS"))
check("no clue or answer, no change", not M.mend({"wp": WP}, "", ""))

print("FAILED" if fails else "all ok")
raise SystemExit(1 if fails else 0)
