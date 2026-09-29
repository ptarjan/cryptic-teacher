#!/usr/bin/env bash
# An indicator note may not write a block's letters: the indicator rung is
# shown before the blocks.
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

def warned(note, gives=("EH", "S"), answer="HES"):
    ann = {"answer": answer, "blocks": [{"clueFragment": "x", "gives": g} for g in gives],
           "indicators": [{"text": "about", "for": "reversal", "note": note}]}
    warnings = []
    v.check_indicator_notes_dont_give_blocks("1A", ann, warnings)
    return len(warnings)

check("block letters in capitals", 1, warned("'about' as in turned about, so EH is read backwards"))
check("described in words", 0, warned("'about' as in turned about, so the exclamation is read backwards"))
check("inside a longer word", 0, warned("so THEHOUSE is read backwards"))
check("a one-letter block", 0, warned("so S goes last"))
check("the whole answer is another check's", 0, warned("so HES appears", gives=("HES",)))
check("marker counts toward the backlog", 1,
      v.count_backlog(["1A: indicator note on 'about' writes a block's letters (EH)"])["indicators.noteLetters"])
raise SystemExit(fails)
PY
