#!/usr/bin/env bash
# tools/puzzle_style.py calls a puzzle straight (not a cryptic) when its clues
# are definitions with no wordplay, and nothing else: each verdict on a real
# puzzle read by eye, with its look-alike on the other side. A straight puzzle
# is unrated (difficulty.raw) and goes behind every cryptic in the hinting
# queue (prereset_plan), a No 1 or a series' oldest included.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import fetch_puzzle as fp
import prereset_plan as pp
import puzzle_style as ps

fails = 0
def check(name, ok, got=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else got)

# times-18 as judged, frozen (tools/fixtures/times-18.json): the live file has
# 11 plain definitions waiting for the burn to annotate them again, too thinly
# annotated to judge until then. The frozen copy reads each as the whole
# definition (a `cryptic` op), as the burn writes the rest of the puzzle.
FROZEN = {"times-18": "fixtures/times-18.json"}

def real(pid):
    if pid in FROZEN:
        from pathlib import Path
        return fp.read_puzzle_file(Path(FROZEN[pid]))
    return fp.read_puzzle_file(fp.resolve_puzzle(pid))

# Straight, by eye: general knowledge, plain definitions, puns with nothing to take apart.
for pid, why in [("listener-1", "'Quickly' = PRESTO"), ("listener-3", "towns of India"),
                 ("cryptic-12575", "'Fat' = LARD, 1970"), ("times-18", "1930 punning definitions"),
                 ("listener-9", "unannotated 1930, short clues")]:
    check(f"{pid} is straight ({why})", ps.is_straight(real(pid)), ps.style(real(pid)))
# Cryptic, by eye, though each looks like the straight ones somewhere.
for pid, why in [("times-5", "1930, has charades"), ("canberra-670909", "1967 cryptic definitions"),
                 ("azed-2291", "a special: every clue typed cryptic_definition, long clues"),
                 ("cryptic-28519", "2021, terse: 'Guy put off' = STAY"),
                 ("listener-121", "1932 cryptic verse, unannotated")]:
    check(f"{pid} is a cryptic ({why})", not ps.is_straight(real(pid)), ps.style(real(pid)))

# A numerical (numeric: true) is straight whatever its clues: it has no wordplay.
digits = copy.deepcopy(real("listener-121"))
digits["numeric"] = True
check("(mirror) a numerical puzzle is straight", ps.is_straight(digits), ps.style(digits))
# The clue text decides only before TEXT_BEFORE: the same clues dated 2021 are not enough.
moved = copy.deepcopy(real("listener-9"))
moved["date"] = "2021-01-01"
check("(mirror) an unannotated puzzle's short clues decide only for an early one", not ps.is_straight(moved))
# The annotation decides once it covers the puzzle: one indicator in most clues is a cryptic.
# (Edited on its view: type and indicators are derived, and style() takes a view as it is.)
import annotation
wordplay = copy.deepcopy(annotation.view_puzzle(real("listener-1")))
for e in wordplay["entries"][:len(wordplay["entries"]) // 2]:
    e["annotation"]["type"] = ["anagram"]
    e["annotation"]["indicators"] = [{"text": "out", "for": "anagram"}]
check("(mirror) half its clues with wordplay is a cryptic", not ps.is_straight(wordplay))
check("'See 9' pointers are not clues", ps.clue_texts({"entries": [
    {"clue": {"text": "See 9"}}, {"clue": {"text": "See 3 across"}}, {"clue": {"text": "Fat"}}]}) == ["Fat"])

# Unrated: every difficulty component is a cryptic's.
import difficulty
measured = difficulty.raw(real("listener-1"), None)
check("a straight puzzle measures nothing, so it has no difficulty score",
      set(measured.values()) == {None} and difficulty.rate(measured, False, {}) is None, measured)

# The queue: straight rows after LAST's lanes, and never pinned as a No 1 or a series' oldest.
rows = [{"id": "listener-1", "series": "listener", "date": "1930-04-02", "style": "straight", "annotated": False, "hasSolutions": True},
        {"id": "listener-2", "series": "listener", "date": "1930-04-09", "annotated": False, "hasSolutions": True},
        {"id": "canberra-670909", "series": "canberra", "date": "1967-09-09", "annotated": False, "hasSolutions": True},
        {"id": "times-29000", "series": "times", "date": "2024-01-01", "annotated": False, "hasSolutions": True}]
order = [p["id"] for p in pp.round_robin(rows)]
check("round_robin puts a straight puzzle after LAST's lanes", order[-1] == "listener-1", order)
queue, pinned, _ = pp.head_of_queue([r["id"] for r in rows], [], rows)
check("head_of_queue pins no straight puzzle, though it is the listener's No 1 and oldest",
      "listener-1" not in pinned and "listener-2" in pinned, pinned)
check("(mirror) a lockout's own pin still holds it",
      pp.head_of_queue([r["id"] for r in rows], ["listener-1"], rows)[1][0] == "listener-1")
raise SystemExit(fails)
PY
