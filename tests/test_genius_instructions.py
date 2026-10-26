#!/usr/bin/env python3
# Is a puzzle whose clues point at instructions we do not hold kept from the
# annotators, and does filing a preamble later let a parked failure retry?
#
#     python3 tests/test_genius_instructions.py
#
# No Guardian article page (Genius No 138 and before) prints its special
# instructions. genius-15 filed with none and no flag, so the burn annotated
# it and every block holding a border letter failed ("needs a puzzle with a
# preamble"); genius-7/40/84/92 print "See special instructions", which
# SEE_PREAMBLE (built for "See preamble") missed. And failed_inputs hashed no
# preamble, so filing one never unparked the failure.
import atexit
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
os.chdir(REPO)

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: expected [{want}], got [{got}]")
        fails += 1


tmp = tempfile.mkdtemp()
atexit.register(shutil.rmtree, tmp, True)

# What the shell's $(...) captured: everything the checks below print.
_stdout = sys.stdout
sys.stdout = io.StringIO()


import copy, glob, json
import genius_puzzles as G
import puzzle_integrity as PI

def clue(t):
    return {"number": 1, "direction": "across", "clue": {"text": t, "enumeration": "6"}}

said = [PI.awaits_preamble({"entries": [clue(t)]}) for t in
        ("See special instructions", "[See special instructions]", "See the preamble",
         "(See instructions)", "Audible instruction to get rid of mule, perhaps",
         "No briefer instruction to solver: look above and below")]
print("see-instructions", said)
print("held-anyway", PI.awaits_preamble({"preamble": "Two letters go.", "entries": [clue("See special instructions")]}))

page = {"preamble": None, "clues": [{"clue": "See special instructions"}], "marked": set()}
print("unheld-clue", G.instructions_unheld(page))
print("unheld-marked", G.instructions_unheld(dict(page, clues=[], marked={(11, "across")})))
print("unheld-plain", G.instructions_unheld(dict(page, clues=[{"clue": "Nice art"}])))
print("unheld-has-preamble", G.instructions_unheld(dict(page, preamble="Enter the border.")))

# Every filed Genius whose clues point at instructions holds one or awaits it.
bad = []
for f in glob.glob("puzzles/genius/*/*.json"):
    p = json.load(open(f))
    if any(PI.SEE_PREAMBLE.search((e.get("clue") or {}).get("text") or "")
                                    for e in p["entries"]):
        if not PI.awaits_preamble(p) and not p.get("preamble"):
            bad.append(p["id"])
print("filed-held", sorted(bad))

# A preamble filed since a failure moves its hash; none filed keeps it.
import failed_inputs as F
d = Path(tmp) / "genius" / "2004"
d.mkdir(parents=True)
p = {"id": "genius-15", "dimensions": {"cols": 1, "rows": 1}, "entries": [clue("Nice art")]}
(d / "genius-15.json").write_text(json.dumps(p))
import puzzle_paths
puzzle_paths.PUZZLE_DIR = Path(tmp)
before = F.input_hash("genius-15")
(d / "genius-15.json").write_text(json.dumps(dict(p, awaitsPreamble=True)))
same = F.input_hash("genius-15") == before
(d / "genius-15.json").write_text(json.dumps(dict(p, preamble="Missing letters go round the border.")))
print("hash", same, F.input_hash("genius-15") != before)


out_text = sys.stdout.getvalue()
sys.stdout = _stdout


def get(key):
    return "\n".join(l[len(key) + 1:] for l in out_text.splitlines() if l.startswith(key + " "))

check('a clue sending the solver to instructions or the preamble awaits it; one using the word does not',
      '[True, True, True, True, False, False]',
      get('see-instructions'))

check('a puzzle holding its preamble awaits nothing',
      'False',
      get('held-anyway'))

check('the filer flags a page whose clue says See special instructions with no preamble read',
      'True',
      get('unheld-clue'))

check('the filer flags a page whose marked light points at instructions',
      'True',
      get('unheld-marked'))

check('a page with no pointer is not flagged',
      'False',
      get('unheld-plain'))

check('a page with its preamble read is not flagged',
      'False',
      get('unheld-has-preamble'))

check('no filed Genius pointing at instructions is left for the annotators without them',
      '[]',
      get('filed-held'))

check("failed_inputs: awaitsPreamble keeps a failure's hash, a filed preamble moves it",
      'True True',
      get('hash'))


if fails:
    print(f"{fails} failed")
    sys.exit(1)
print("all passed")
