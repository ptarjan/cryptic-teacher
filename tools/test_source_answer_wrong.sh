#!/bin/bash
# Does the corpus still hold the letters SOURCE_ANSWER_WRONG says it holds, and
# does the table still do anything?
#
#     bash tools/test_source_answer_wrong.sh
#
# fetch_puzzle.SOURCE_ANSWER_WRONG names answers the PAPER got wrong: cell (4,8)
# of cryptic 23,053, where the Guardian's own key holds T in both lights that
# cross there and its clues give R. Nothing else in this repo can notice that —
# the two lights agree with each other, so CROSS is silent, and both hold the
# letters their enumerations count, so LENGTH is silent — which is why the
# correction is a table and not a file edit: carry_recovered_clues carries clue
# text across a re-fetch and nothing carries a solution, so before the table one
# deliberate re-fetch restored the paper's letter and no check went red.
#
# Liveness — is the source STILL serving the wrong answer, or has the paper
# fixed it and left a stale key behind? — cannot be asked here. Nothing in this
# repo's tests touches the network (see .github/workflows/tests.yml), so it is
# asked at fetch time instead: correct_source_answers rewrites only an answer
# that arrives as the table's `served` value and prints a STALE warning for
# anything else, including the corrected value itself. That warning is the
# liveness check, and the fifth property below is the test of it. Last confirmed
# live by hand on 2026-09-18: /crosswords/prize/23053 serves GETSTEADY and
# XETOPHILY.
#
# What IS provable offline, and is proved here: every key names a real entry of
# a real puzzle whose stored answer is the corrected one; the table corrects
# something (served != corrected, same length, bare letters both); the
# correction actually happens on a page serving the wrong value; a page serving
# anything else is left alone and named; and — the reason the table exists —
# putting the paper's letters back into the stored puzzle leaves every corpus
# check silent.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }
field() { awk -v k="$1" '$1==k {$1=""; sub(/^ /, ""); print}' <<<"$2"; }

echo "every key names a real entry whose stored answer is the corrected one"
out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
from pathlib import Path
import fetch_puzzle as fetcher

table = fetcher.SOURCE_ANSWER_WRONG
print("SIZE", "some" if table else "none")
bad = []
for (pid, eid), (served, corrected, why) in table.items():
    path = fetcher.PUZZLE_DIR / f"{pid}.json"
    if not path.exists():
        bad.append(f"{pid}: no such puzzle file")
        continue
    entry = {e["id"]: e for e in fetcher.read_puzzle_file(path)["entries"]}.get(eid)
    if entry is None:
        bad.append(f"{pid} {eid}: no such entry")
        continue
    if entry.get("solution") != corrected:
        bad.append(f"{pid} {eid}: stored {entry.get('solution')!r}, table corrects "
                   f"to {corrected!r}")
    if served == corrected:
        bad.append(f"{pid} {eid}: corrects {served!r} to itself")
    if len(served) != len(corrected) or len(corrected) != entry["length"]:
        bad.append(f"{pid} {eid}: {served}/{corrected} against a light of "
                   f"{entry['length']}")
    if not (fetcher.is_bare_letters(served) and fetcher.is_bare_letters(corrected)):
        bad.append(f"{pid} {eid}: {served}/{corrected} is not bare letters")
    if len(why) < 40:
        bad.append(f"{pid} {eid}: the note is not evidence")
print("BAD", "; ".join(bad) or "none")
PY
)
same "the table is not empty" "$(field SIZE "$out")" "some"
same "every entry checks out against the file on disk" "$(field BAD "$out")" "none"

echo "the correction happens, and only where the table says"
out2=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import fetch_puzzle as fetcher


def entry(eid, solution):
    return {"id": eid, "number": 1, "direction": "across",
            "position": {"x": 0, "y": 0}, "length": len(solution or "") or 9,
            "clue": "As the page sends it (9)", "separatorLocations": {},
            "solution": solution, "annotation": None}


# The page as the Guardian serves it today, plus two lights the table says
# nothing about: one in another puzzle under a name the table DOES hold, one
# in this puzzle under a name it does not.
served = [entry("18-across", "GETSTEADY"), entry("15-down", "XETOPHILY"),
          entry("1-across", "GETSTEADY")]
fetcher.correct_source_answers("cryptic-23053", served)
by = {e["id"]: e["solution"] for e in served}
print("ACROSS", by["18-across"])
print("DOWN", by["15-down"])
print("UNNAMED_LIGHT", by["1-across"])

other = [entry("18-across", "GETSTEADY")]
fetcher.correct_source_answers("cryptic-30000", other)
print("OTHER_PUZZLE", other[0]["solution"])

# A prize puzzle published without its key: nothing to correct and nothing to
# complain about either.
unsolved = [entry("18-across", None), entry("15-down", None)]
fetcher.correct_source_answers("cryptic-23053", unsolved)
print("UNSOLVED", unsolved[0]["solution"], unsolved[1]["solution"])
PY
2>/tmp/saw_quiet.err)
same "the wrong across answer is corrected" "$(field ACROSS "$out2")" "GETSREADY"
same "the wrong down answer is corrected" "$(field DOWN "$out2")" "XEROPHILY"
same "a light the table does not name keeps the paper's answer" \
  "$(field UNNAMED_LIGHT "$out2")" "GETSTEADY"
same "another puzzle's same-named light is untouched" \
  "$(field OTHER_PUZZLE "$out2")" "GETSTEADY"
same "an unpublished key is neither corrected nor complained about" \
  "$(field UNSOLVED "$out2")" "None None"
same "and correcting a page the table describes says nothing on stderr" \
  "$(wc -l < /tmp/saw_quiet.err)" "0"

echo "staleness: a source that no longer serves the wrong answer is named, not overwritten"
out3=$(PYTHONPATH="$REPO/tools" python3 - <<'PY' 2>/tmp/saw_stale.err
import fetch_puzzle as fetcher

# The day the Guardian fixes its own key, the table has stopped describing the
# source and must stop acting on it: overriding an answer nobody disputes is how
# a correction outlives the error it was written for.
fixed = [{"id": "18-across", "length": 9, "solution": "GETSREADY"},
         {"id": "15-down", "length": 9, "solution": "XEROPHILY"}]
fetcher.correct_source_answers("cryptic-23053", fixed)
print("FIXED", fixed[0]["solution"], fixed[1]["solution"])

# Or the page changes under the table some other way.
changed = [{"id": "18-across", "length": 9, "solution": "SOMETHING"},
           {"id": "15-down", "length": 9, "solution": "SOMEOTHER"}]
fetcher.correct_source_answers("cryptic-23053", changed)
print("CHANGED", changed[0]["solution"])

# Or the light the key names stops being in the puzzle at all.
fetcher.correct_source_answers("cryptic-23053", [])
PY
)
stale=$(cat /tmp/saw_stale.err)
same "the paper's own fix is kept as published" "$(field FIXED "$out3")" "GETSREADY XEROPHILY"
same "an answer that changed some other way is kept too" "$(field CHANGED "$out3")" "SOMETHING"
same "every stale case warns" "$(grep -c 'SOURCE_ANSWER_WRONG' <<<"$stale")" "6"
same "and says which key to delete" \
  "$(grep -c 'delete the key\|delete it' <<<"$stale")" "6"
same "a vanished entry is named too" \
  "$(grep -c 'no such entry' <<<"$stale")" "2"
rm -f /tmp/saw_quiet.err /tmp/saw_stale.err

echo "why the table exists: the paper's letters break no corpus check at all"
out4=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import copy
from datetime import datetime, timezone
import fetch_puzzle as fetcher
import puzzle_integrity as pi

today = datetime.now(timezone.utc).date()
puzzle = copy.deepcopy(pi.read_puzzle_file(pi.PUZZLE_DIR / "cryptic-23053.json"))
by_id = {e["id"]: e for e in puzzle["entries"]}
for (pid, eid), (served, corrected, _) in fetcher.SOURCE_ANSWER_WRONG.items():
    if pid == puzzle["id"]:
        assert by_id[eid]["solution"] == corrected, "fixture assumption broken"
        by_id[eid]["solution"] = served

flags = []
checkable = pi.check_shape(puzzle, today, flags)
pi.check_length(puzzle, checkable, flags)
pi.check_grid(puzzle, flags)
pi.check_cross(puzzle, checkable, flags)
print("FINDINGS", len(flags))
# The two wrong lights cross at one cell and agree about it, which is exactly
# why no check can speak: it is the paper that is wrong, not the data.
print("SHARED_CELL", by_id["18-across"]["solution"][4],
      by_id["15-down"]["solution"][2])
PY
)
same "reverting to the served answers leaves every check silent" \
  "$(field FINDINGS "$out4")" "0"
same "because the two wrong lights agree about the cell they share" \
  "$(field SHARED_CELL "$out4")" "T T"

[ "$fails" = 0 ] && echo "source_answer_wrong: all checks passed" \
  || echo "source_answer_wrong: $fails FAILED"
exit $((fails > 0))
