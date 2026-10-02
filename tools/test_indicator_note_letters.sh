#!/usr/bin/env bash
# An indicator note may name a block's clue words but never its letters or the
# answer: the indicator rung is shown before the blocks, and every note in the
# corpus is held to it.
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

star = {"answer": "STAR", "blocks": [{"clueFragment": "Rats", "gives": "RATS"}]}
check("a block's clue words", [],
      v.letters_given_in("returning means the word rats is read backwards", star))
check("what it turns into", ["STAR"],
      v.letters_given_in("returning means RATS becomes STAR", star))
ann = {"blocks": [{"clueFragment": "cracked lips", "gives": "SPLI"},
                  {"clueFragment": "Nurse", "gives": "TEND"}]}
check("a block's letters", ["TEND"],
      v.letters_given_in("the lips' letters come first, before TEND", ann))
check("what the word does", [],
      v.letters_given_in("puts the piece after it at the front", ann))
check("letters inside a longer word", [],
      v.letters_given_in("so THEHOUSE is read backwards", {"blocks": [{"clueFragment": "what", "gives": "EH"}]}))
check("a word of the answer", ["CHAUVINIST"],
      v.letters_given_in("so the pieces make CHAUVINIST", {"answer": "MALE CHAUVINIST"}))
errors = []
v.check_indicator_notes_name_no_block("1A", {
    "blocks": [{"clueFragment": "Nurse", "gives": "TEND"}],
    "indicators": [{"text": "at first", "note": "the lips come first, before TEND"}]}, errors)
check("an error on any note, not only a new one", 1, len(errors))
raise SystemExit(fails)
PY
