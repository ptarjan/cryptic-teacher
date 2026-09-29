#!/usr/bin/env bash
# An anagram's fodder is drawn from the clue: its wordplay's words and the
# letters its blocks give. GROAN is not the fodder of a clue that says grain.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def flagged(clue, fodder, definition, authored=False, blocks=(), types=("anagram",)):
    ann = {"type": list(types), "definitions": [{"text": definition}], "blocks": list(blocks),
           "assembly": {"anagrams": [{"fodder": fodder, "gives": "X"}]}}
    errors, warnings = [], []
    v.check_anagram_fodder_from_clue("1A", ann, clue, authored, errors, warnings)
    return len(errors), len(warnings)

CLUE = "Crushed grain makes a complaint"
check("fodder in the clue", (0, 0), flagged(CLUE, "GRAIN", "a complaint"))
check("fodder not in the clue, published", (0, 1), flagged(CLUE, "GROAN", "a complaint"))
check("fodder not in the clue, ours", (1, 0), flagged(CLUE, "GROAN", "a complaint", authored=True))
check("a letter only the definition has", (0, 1), flagged("Crushed grin is a complaint", "GRAIN", "a complaint"))
check("an &lit draws on the whole clue", (0, 0), flagged(CLUE, "GRAINMAKES", CLUE, types=("and_lit",)))
check("a whole-clue definition is not removed", (0, 0), flagged(CLUE, "GRAINMAKES", CLUE))
check("a block's letters count", (0, 0),
      flagged("Crushed grain and nothing makes a complaint", "GRAINO", "a complaint",
              blocks=[{"clueFragment": "nothing", "gives": "O"}]))
check("ours scattered, not in order nor from blocks", (1, 0),
      flagged("Crushed grain makes a complaint", "NIARG", "a complaint", authored=True))
raise SystemExit(fails)
PY
