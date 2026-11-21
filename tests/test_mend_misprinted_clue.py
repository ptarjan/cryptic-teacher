#!/usr/bin/env python3
# The mend for a quote of a clue word the clue prints misspelt: the repaired clue becomes printedClue only
# when the quote is a word, the clue's is not, and one clue word fits.
#
#     python3 tests/test_mend_misprinted_clue.py
import _path  # puts tools/ on sys.path
import mend_misprinted_clue as M
import wordplay

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


CLUE = "An arrempt to accommodate old folk that could be a disaster"
a = {"def": "could be a disaster", "wp": wordplay.render({"words": "arrempt", "gives": "TRY"}).replace("arrempt", "attempt")}
row = M.mend(a, CLUE, True)
check("a repaired clue and evidence", row and row[0] == "An attempt to accommodate old folk that could be a disaster"
      and row[1].startswith("OCR misread: ") and len(row[1]) >= 25)
check("a typed book or newspaper only", M.mend(a, CLUE, False) is None)
check("an entry with a printedClue is left", M.mend({**a, "printedClue": ["x", "y"]}, CLUE, True) is None)
check("both words real ('sought' for the clue's 'sort') is not mended",
      M.repaired(["sought-after"], "Part of London which is not quite so sort-after")[0] is None)
check("neither word in the lexicon is not mended",
      M.repaired(["Malpighian layer"], "Section of redder Maphigian layer of skin")[0] is None)
check("a quote that is no word is not turned into the clue's word",
      M.repaired(["balme"], "They admit blame for hospital treatment")[0] is None)
check("two clue words one slip away are not mended",
      M.repaired(["attempt"], "An arrempt and an atrempt to accommodate")[0] is None)
check("a short word is not mended", M.repaired(["owl"], "Ow, unusually, at ground-level")[0] is None)
check("a quote's capital is kept for a capitalised clue word",
      M.repaired(["Attempt"], "Arrempt to accommodate old folk")[0] == "Attempt to accommodate old folk")

raise SystemExit(fails > 0)
