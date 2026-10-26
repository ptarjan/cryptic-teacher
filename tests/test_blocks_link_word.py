#!/usr/bin/env python3
# When a clue's blocks are short by exactly the letters of a word filed under
# linkWords, that word is fodder, and the warning says the edit to make.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import os
import sys
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def warned(answer, blocks, link_words):
    ann = {"type": ["anagram"], "definitions": [{"text": "kidney trouble"}],
           "linkWords": link_words, "blocks": blocks}
    entry = {"number": 24, "direction": "across", "solution": answer, "annotation": ann}
    errors, warnings = [], []
    v.check_blocks_account_for_answer([entry], errors, warnings)
    return warnings

hint = 'remove it from linkWords and add the block {"clueFragment": "in", "gives": "IN"}'
w = warned("NEPHRITIS", [{"clueFragment": "hipster", "gives": "HIPSTER"}], ["in"])
check("missing letters are a link word: the warning names the edit", True, len(w) == 1 and hint in w[0])
w = warned("NEPHRITIS", [{"clueFragment": "hipster", "gives": "HIPSTER"}], ["at"])
check("a link word that is not the missing letters: no edit named", True,
      len(w) == 1 and "linkWords" not in w[0])
w = warned("NEPHRITIS", [{"clueFragment": "hipster", "gives": "HIPSTER"},
                         {"clueFragment": "in", "gives": "IN"}], ["in"])
check("blocks already add up: no warning", [], w)
raise SystemExit(fails)
