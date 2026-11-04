#!/usr/bin/env python3
# A setter's slip in a clue that is no anagram (a hidden run, a charade's or a
# container's spelt piece) is annotated the way an anagram's is: the annotation
# carries the corrected letters, and a tools/data/setter_error.json row names the
# printed words and those letters. Without the row nothing is forgiven.
import _path  # puts tools/ on sys.path
import json
import os
import tempfile
from pathlib import Path

import validate_anagram as va
import validate_annotations as v
import wordplay

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

# run_slip: a run of the text with one wrong letter or two swapped; nothing else.
check("one wrong letter is a slip", True, wordplay.run_slip("XXTORARYXX", "TORERY"))
check("two swapped letters are a slip", True, wordplay.run_slip("BOLEROROTTENLY", "OREROT"))
check("a run held exactly is no slip", False, wordplay.run_slip("BOLEROROTTENLY", "EROROT"))
check("three letters out is no slip", False, wordplay.run_slip("BOLEROROTTENLY", "OXEXOT"))
check("longer than the text is no slip", False, wordplay.run_slip("AB", "ABC"))

# The hidden leaf is forgiven only for a pair the table names.
tmp = Path(tempfile.mkdtemp()) / "setter_error.json"
tmp.write_text(json.dumps({"p-1/8-down": ["bolero rottenly", "OREROT", "the page prints it"]}))
wordplay.SLIP_FILE = tmp
leaf = lambda words, gives: {"op": "hidden", "parts": [{"words": words, "gives": gives}]}
check("a named slip evaluates", {"OREROT"}, wordplay.values(leaf("bolero rottenly", "OREROT")))
check("another pair on the same words does not", set(), wordplay.values(leaf("bolero rottenly", "OREROX")))
check("the same run on other words does not", set(), wordplay.values(leaf("bolero rotten", "OREROT")))
tmp.write_text("{}")
os.utime(tmp, ns=(1, 2))   # a row filed mid-run changes the file
check("with the row gone it fails again", set(), wordplay.values(leaf("bolero rottenly", "OREROT")))

# The row is used by a block reading the printed words as the corrected letters.
va.SETTER_ERROR = {("p-1", "8-down"): ("bolero rottenly", "OREROT", "e")}
WALK = {"walkthrough": "The printed words hide EROROT, which reversed is TORORE."}
def errors(blocks, pid="p-1", eid="8-down", walk=WALK, row=None):
    ann = {"blocks": blocks, "explanation": walk}
    out = []
    va.check_anagram_letters(pid, eid, "X", ann, out)
    return out
HID = [{"clueFragment": "bolero rottenly", "gives": "OREROT"}]
check("a block giving the corrected run uses the row", [], errors(HID))
check("a row no block uses is refused", 1, len(errors([{"clueFragment": "bolero", "gives": "BOLERO"}])))
check("the slip must be told in the walkthrough", 1, len(errors(HID, walk={})))
check("another light has no row to use", [], errors(HID, eid="9-down"))

# A charade's or container's spelt piece: the row is checkable the same way.
va.SETTER_ERROR = {("p-1", "3-across"): ("fuel", "FLUEA", "e")}
check("a block giving corrected letters of a spelt piece uses the row", [],
      errors([{"clueFragment": "fuel", "gives": "FLUEA"}], eid="3-across"))

# A corrected anagram (fodder as it should be) uses its row too.
va.SETTER_ERROR = {("p-1", "13-down"): ("skis Elf oil", "KISSOFLIFE", "e")}
def ana(fodder):
    ann = {"assembly": {"anagrams": [{"fodder": fodder, "gives": "KISSOFLIFE"}]}, "explanation": WALK}
    out = []
    va.check_anagram_letters("p-1", "13-down", "X", ann, out)
    return out
check("an anagram corrected to the answer's letters uses the row", [], ana("SKISELFOIF"))
check("the printed fodder still uses it", [], ana("SKISELFOIL"))
check("a different wrong fodder fails and leaves the row unused", 2, len(ana("SKISELFOLL")))

# setter_error_problems takes a hidden row: the printed words, the corrected run.
PUZ = {"id": "p-1", "entries": [
    {"number": 8, "direction": "down", "solution": "TORERO",
     "clue": {"text": "Bullfighter held up in bolero rottenly"}}]}
P = lambda row: len(v.setter_error_problems(PUZ, "8-down", row, {}))
check("a hidden run a swap out of the print is filed", 0, P(["bolero rottenly", "OREROT", "e"]))
check("a hidden run three out is refused", 1, P(["bolero rottenly", "OXEXOT", "e"]))
raise SystemExit(fails)
