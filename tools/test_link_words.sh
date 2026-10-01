#!/bin/bash
# Does tools/validate_annotations.py refuse a link word that app.js would place
# on top of an indicator, wholly or in part, and pass one with a free copy?
# The placement is app.js placedFragments(), so these are the clues that
# reached the screen with a bought indicator half-erased.
#
#     bash tools/test_link_words.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PYTHONPATH=tools python3 - <<'PY'
from validate_annotations import check_link_word_is_not_inside_an_indicator as check

def refused(clue, inds, links, defs=()):
    ann = {"indicators": [{"text": t} for t in inds], "linkWords": list(links),
           "definitions": [{"text": t, "at": clue.index(t)} for t in defs]}
    errors = []
    check("1A", ann, clue, errors)
    return bool(errors)

cases = [
    # everyman-3925 4D: the link ran across the indicator's first word
    ("Rural museum's don's written about twins of old",
     ["written about"], ["'s written"], ["twins of old"], True),
    ("Rural museum's don's written about twins of old",
     ["written about"], ["'s"], ["twins of old"], False),
    # times-29616 6D: wholly inside
    ("Ring on top of the hill", ["on top of"], ["of"], [], True),
    # toughie-3640 1A: the link swallowed the indicator
    ("Detective left loads in front of sergeant",
     ["loads", "front of"], ["in front of"], ["Detective"], True),
    # two copies: the indicator takes one, the link the other
    ("Allied countries in a French article in France, say",
     ["in"], ["in"], ["France, say"], False),
    ("What about dividing strong drink to bring about sleep?",
     ["about", "dividing"], ["to bring about"], ["sleep"], False),
]
bad = 0
for clue, inds, links, defs, want in cases:
    got = refused(clue, inds, links, defs)
    if got != want:
        bad += 1
        print(f"FAIL: {clue!r} link {links} — refused={got}, want {want}")
print(f"{len(cases) - bad}/{len(cases)} link-word cases")
raise SystemExit(1 if bad else 0)
PY
