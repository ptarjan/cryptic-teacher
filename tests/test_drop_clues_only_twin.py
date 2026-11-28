#!/usr/bin/env python3
# Does a clues-only twin's blog answer land on the right entry of the filed puzzle?
#
#     python3 tests/test_drop_clues_only_twin.py
#
# The clue's words and the answer's length place it; the twin's direction only
# breaks a tie, because a clues-only reading can list a down clue among the
# acrosses.
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _path  # puts tools/ on sys.path
import drop_clues_only_twin as twin

fails = 0


def check(why, got, want):
    global fails
    if got == want:
        print("  ok: %s" % why)
    else:
        print("  FAIL: %s\n    want %r\n    got  %r" % (why, want, got))
        fails += 1


def entry(direction, text, length):
    return {"direction": direction, "clue": {"text": text}, "length": length}


def light(text, answer):
    return {"clue": {"text": text}, "length": len(answer), "blogAnswer": answer}


puzzle = {"entries": [entry("down", "Stuck up ladder impatience shows", 5),
                      entry("across", "Very late", 4),
                      entry("down", "Very late", 4)]}
held = {"clues": {"across": [light("Stuck up ladder impatience shows", "MIRED"),
                             light("Very late", "DEAD")],
                  "down": [light("Very late", "GONE")]}}
changed, unplaced = twin.merge(puzzle, held)
check("a down clue the twin lists as across still finds its entry",
      puzzle["entries"][0].get("blogAnswer"), "MIRED")
check("two entries with the same words are told apart by direction",
      (puzzle["entries"][1].get("blogAnswer"), puzzle["entries"][2].get("blogAnswer")),
      ("DEAD", "GONE"))
check("nothing is left unplaced", (changed, unplaced), (True, []))

lost = {"entries": [entry("across", "Other words", 5)]}
check("a light whose words are not in the puzzle stays unplaced",
      twin.merge(lost, {"clues": {"across": [light("Stuck up", "MIRED")]}}),
      (False, ["across MIRED"]))

print("FAILED: %d" % fails if fails else "all ok")
sys.exit(1 if fails else 0)
