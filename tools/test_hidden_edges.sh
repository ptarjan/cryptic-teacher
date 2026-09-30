#!/bin/bash
# Does tools/build_authored_puzzle.py refuse a hidden answer that sits inside one
# word or starts or ends on a word boundary, forwards or reversed, and pass one
# that crosses a space and begins and ends inside words?
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
PY
