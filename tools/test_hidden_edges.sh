#!/bin/bash
# Does tools/build_authored_puzzle.py refuse a hidden answer that sits inside one
# word or starts or ends on a word boundary, forwards or reversed, and pass one
# that crosses a space and begins and ends inside words? And does
# tools/validate_annotations.py refuse an annotation whose answer runs across a
# word break in its wordplay when the type has no hidden_word and no block or
# indicator note calls it a coincidence?
#
#     bash tools/test_hidden_edges.sh
#
# "Some Che apparel is shoddy" starts CHEAP on the whole word "Che"; published
# setters almost never do that (2 of 2,578 forward hidden words start on a
# boundary, 2 end on one), so our own clues may not. "Osprey swallows victim"
# hides PREY inside one word; 267 of those published clues do that, and we don't.
set -uo pipefail
cd "$(dirname "$0")/.."

PYTHONPATH=tools python3 - <<'PY'
import sys
from build_authored_puzzle import hidden_edge_errors

def verdict(text, answer, types=("hidden_word",)):
    entry = {"number": 1, "direction": "across", "solution": answer,
             "clue": {"text": text}, "annotation": {"type": list(types)}}
    return not hidden_edge_errors({"entries": [entry]})

REV = ("hidden_word", "reversal")
cases = [
    ("Some Che apparel is shoddy", "CHEAP", (), False),      # starts on "Che"
    ("Osprey swallows victim", "PREY", (), False),           # ends where "Osprey" does
    ("an apple a day", "PLEA", (), False),                   # ends on "a"
    ("Wise man holds up fingers", "NAMES", REV, False),      # reversed, ends on "man"
    ("Milan side buried in print errors", "INTER", (), True),
    ("Some quiche appetisers look tacky", "CHEAP", (), True),
    ("Ospreys swallow victim", "PREY", (), False),           # inside one word
    ("Milan side is in splinters", "INTER", (), False),      # inside one word
    ("Wise manager holds up fingers", "NAMES", REV, True),
    ("People, as ever, hide the magic word", "PLEASE", (), True),
    ("rejigging ham-fistedly", "GINGHAM", (), True),          # a hyphen joins one word
    ("left-wing", "TWIN", (), False),                        # ... so this is inside one
    ("a friend's cottage", "SCOT", (), True),                # the S is inside "friend's"
    ("no such letters here", "CHEAP", (), False),            # not hidden at all
]
fails = []
for text, answer, types, want in cases:
    got = verdict(text, answer, types or ("hidden_word",))
    if got != want:
        fails.append(f"{answer} in {text!r}: {'passed' if got else 'refused'}, "
                     f"want {'pass' if want else 'refusal'}")
# A clue that is not a pure hidden word is not this check's business.
if not verdict("Son leaves room for walk", "PACE", ("deletion",)):
    fails.append("a deletion was judged as a hidden word")

for f in fails:
    print("  FAIL:", f)
if fails:
    sys.exit(1)
print(f"  ok: {len(cases)} hidden words judged on their edges")

import validate_annotations as v

def unmarked(clue, answer, types, definition, notes=()):
    ann = {"answer": answer, "type": list(types),
           "definitions": [{"text": definition, "at": clue.index(definition)}],
           "blocks": [{"clueFragment": clue, "gives": answer, "note": n} for n in notes]}
    errors = []
    v.check_unmarked_hidden_word("1A", ann, clue, errors)
    return errors

EGRET = "One likely to wade in after getting pushed around"
checks = [
    ("reversed, typed as a cryptic definition", 1,
     unmarked(EGRET, "EGRET", ["cryptic_definition"], "One likely to wade in")),
    ("reversed and typed", 0,
     unmarked(EGRET, "EGRET", ["hidden_word", "reversal"], "One likely to wade in")),
    ("inside the definition only", 0,
     unmarked(EGRET, "EGRET", ["cryptic_definition"], EGRET)),
    ("forwards, typed as a container", 1,
     unmarked("Soldier out in Egypt bears standard", "ROUTINE", ["container"], "standard")),
    ("a coincidence the note owns", 0,
     unmarked("Party food is cold, in short supply", "DISCO", ["charade"], "Party",
              ["the pieces sit side by side, a coincidence the setter does not signal"])),
    ("whole words are not hidden", 0,
     unmarked("It’s a revolution in sparkling wine", "ASTI", ["reversal"], "sparkling wine")),
]
bad = [f"{name}: {len(errs)} errors, want {want} {errs}" for name, want, errs in checks
       if len(errs) != want]
for f in bad:
    print("  FAIL:", f)
if bad:
    sys.exit(1)
print(f"  ok: {len(checks)} unmarked hidden words judged")
PY
