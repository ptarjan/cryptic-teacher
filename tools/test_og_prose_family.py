#!/usr/bin/env python3
"""Does the og card's own-prose family check ignore words quoted from the clue?

    python3 tools/test_og_prose_family.py

azed-2475 ("... hidden and twisted in so") is an anagram whose fodder piece is
the clue word "hidden" meaning SECRET. The compound-anagram tail quotes it as
“hidden” gives SECRET, and the check read that clue word as the card naming
the hidden-word device, which stopped the whole deploy's card step.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import clue_types
import make_og_card as m

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


fam = {"name": "anagram", "label": "Anagram"}


def raises(prose):
    try:
        m.check_prose_stays_in_family(prose, fam, "anagram")
    except RuntimeError:
        return True
    return False


check("a quoted clue word 'hidden' is not the card's own signal",
      not raises("The rest: “hidden” gives SECRET, and <mark class=\"ind\">twisted</mark> says what to do."))
check("the card's own 'hidden' still trips the check",
      raises("The answer is hidden in the clue itself"))

print("FAIL" if fails else "ok")
sys.exit(1 if fails else 0)
