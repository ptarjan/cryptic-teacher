#!/usr/bin/env python3
# When a clue's blocks give too many letters and none too few, the warning names
# the single-block edits that take exactly the surplus away.
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def warned(answer, blocks, types=("charade",)):
    ann = {"type": list(types), "definitions": [{"text": "fixation"}], "blocks": blocks}
    entry = {"number": 10, "direction": "across", "solution": answer, "annotation": ann}
    errors, warnings = [], []
    v.check_blocks_account_for_answer([entry], errors, warnings)
    return warnings

w = warned("OBSESSION", [{"clueFragment": "old boys", "gives": "OBS"},
                         {"clueFragment": "meeting", "gives": "SESSION"}])
check("a doubled letter at a join: the edit that keeps answer order comes first", True,
      len(w) == 1 and "make the one the clue supports: block 'old boys' gives 'OB', not 'OBS'" in w[0]
      and "block 'meeting' gives 'ESSION', not 'SESSION'" in w[0])
w = warned("FLATBACK", [{"clueFragment": "apartment", "gives": "FLAT"},
                        {"clueFragment": "a", "gives": "A"},
                        {"clueFragment": "large tub", "gives": "BACK"}])
check("a surplus block: one edit, drop it", True,
      len(w) == 1 and "one edit makes them add up: drop block 'a' > 'A'" in w[0]
      and "note" not in w[0].split("drop block")[1])
w = warned("SCAR", [{"clueFragment": "vehicles", "gives": "CARS"},
                    {"clueFragment": "son", "gives": "S"}], ("cycling",))
check("a letter given twice: drop the block or cut the other", True,
      len(w) == 1 and "drop block 'son' > 'S'" in w[0] and "gives 'CAR', not 'CARS'" in w[0])
w = warned("NATTY", [{"clueFragment": "New York", "gives": "NY"},
                     {"clueFragment": "lawyer", "gives": "ATTY"}], ("container",))
check("a surplus no block can lose cleanly still names a cut", True,
      len(w) == 1 and "gives 'ATT', not 'ATTY'" in w[0])
w = warned("PANDA", [{"clueFragment": "father", "gives": "PA"}])
check("letters missing, none extra: no surplus edit", True, len(w) == 1 and "add up" not in w[0])
w = warned("CELT", [{"clueFragment": "cel", "gives": "LECR"}])
check("letters both extra and missing: no surplus edit", True, len(w) == 1 and "add up" not in w[0])
w = warned("OBSESSION", [{"clueFragment": "old boy", "gives": "OB"},
                         {"clueFragment": "meeting", "gives": "SESSION"}])
check("blocks already add up: no warning", [], w)

# Real drafts of 2026-10-23 that the check refused before fb49e09 (96 of 116
# sampled error lines): a rep<> step shows one copy as its blocks, so the blocks
# fall one copy short of the answer by design, alone or inside a charade.
import annotation

def repeat_warned(answer, d, wp, notes):
    clue = d + " " + " ".join(notes) + " " + wp.replace("<", " ").replace(">", " ")
    entry = {"number": 1, "direction": "across", "solution": answer, "clue": {"text": clue},
             "enumeration": str(len(answer))}
    m = {"def": d, "wp": wp, "notes": notes, "explanation": {"surface": "x", "definitionFit": "y"}}
    entry["annotation"] = annotation.view(annotation.from_model(m, entry), entry)
    errors, warnings = [], []
    v.check_blocks_account_for_answer([entry], errors, warnings)
    return errors + warnings

for ans, d, wp, notes in [
    ("CRISIS", "emergency", "[Credit]CR + rep<double>([is])",
     {"double": "double means the word is written out twice", "Credit": "CR is the accounting abbreviation for credit"}),
    ("NEEDED", "called for", "first<cut by half>([News]) + rep<repeatedly>([editor]ED)",
     {"cut by half": "cut by half keeps only the front half of the word news",
      "repeatedly": "repeatedly says the editor abbreviation appears twice",
      "editor": "ED is the standard abbreviation for editor"}),
    ("SKIFF", "Glide", "[Glide over water]SKI + rep<double>([force]F)",
     {"double": "double means the abbreviation for force is written twice in a row",
      "force": "F is the abbreviation for force in physics"}),
    ("MIAMI", "city in Florida", "ins<about>(rep<repeated>([Note]MI), [a])",
     {"Note": "MI is the third note of the sol-fa scale", "repeated": "says the note is written down twice in a row",
      "about": "the doubled note goes around the single letter, cut open to hold it"}),
    ("RAHRAH", "Boisterously enthusiastic", "rep<repeated>(first<initially>([reunion], [at], [home]))",
     {"initially": "initially tells us to take the opening letter of each of the words reunion, at and home",
      "repeated": "repeated says the three letters just picked appear twice in a row"}),
]:
    check(f"{ans}: a repeat's one copy in the blocks is not a refusal", [], repeat_warned(ans, d, wp, notes))
raise SystemExit(fails)
