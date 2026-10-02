#!/usr/bin/env bash
# An indicator note names no block, by its letters or its clue words: the
# indicator rung is shown before the blocks, and every note in the corpus is
# held to it.
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

ann = {"blocks": [{"clueFragment": "cracked lips", "gives": "SPLI"},
                  {"clueFragment": "Nurse", "gives": "TEND"}]}
at_first = {"text": "at first"}
check("a block's clue words", ["lips"],
      v.blocks_named_in("the lips come first", ann, at_first))
check("letters and clue words", ["TEND", "lips"],
      v.blocks_named_in("the lips' letters come first, before TEND", ann, at_first))
check("the indicator's own words", [],
      v.blocks_named_in("cracked things are broken up", ann, {"text": "cracked"}))
check("what the word does", [],
      v.blocks_named_in("puts the piece after it at the front", ann, at_first))
check("a block's letters", ["EH"],
      v.blocks_named_in("so EH is read backwards", {"blocks": [{"clueFragment": "what", "gives": "EH"}]},
                        {"text": "about"}))
check("letters inside a longer word", [],
      v.blocks_named_in("so THEHOUSE is read backwards", {"blocks": [{"clueFragment": "what", "gives": "EH"}]},
                        {"text": "about"}))
check("a word hundreds of notes use", [],
      v.blocks_named_in("something exciting is stirred into a new order",
                        {"blocks": [{"clueFragment": "new group", "gives": "NEWGROUP"},
                                    {"clueFragment": "Something in wardrobe", "gives": "HANGER"}]},
                        {"text": "Exciting"}))
check("a block's own content word still counts", ["river"],
      v.blocks_named_in("a piece crossing a river straddles it",
                        {"blocks": [{"clueFragment": "river", "gives": "R"}]}, {"text": "Crossing"}))
puzzle = {"id": "x-1", "entries": [{"number": 1, "direction": "across", "annotation": {
    "blocks": [{"clueFragment": "Nurse", "gives": "TEND"}],
    "indicators": [{"text": "at first", "note": "the lips come first, before TEND"}]}}]}
errors = []
v.check_indicator_notes_name_no_block("1A", puzzle["entries"][0]["annotation"], errors)
check("an error on any note, not only a new one", 1, len(errors))
raise SystemExit(fails)
PY
