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

# a printedClue that corrects nothing, whose evidence names the swap: mended from that evidence
FIVE = "Retain a few in sheltered situation"
f = {"def": "Retain", "wp": "ins<in>([sheltered situation]LEE, [a]A + [five]V)",
     "printedClue": [FIVE, "OCR misread: five (V) for few"]}
row = M.mend(f, FIVE, True)
check("a no-op printedClue with evidence naming the swap is mended",
      row == ["Retain a five in sheltered situation", "OCR misread: five (V) for few"])
check("the same swap without a printedClue is mended: few for five is the OCR's known misread",
      M.mend({k: v for k, v in f.items() if k != "printedClue"}, FIVE, True)
      == ["Retain a five in sheltered situation", "OCR misread: the text has 'few' where the wordplay needs 'five'"])
check("another real-word pair that is no known misread is not mended",
      M.repaired(["fee"], "Retain a few in sheltered situation")[0] is None)
check("a look-alike glyph: 'A1' for the clue's 'Al'", M.repaired(["A1 meal"], "Woman cooking Al meal")[0] == "Woman cooking A1 meal")
check("a look-alike glyph: 'Ai' for 'Al'", M.repaired(["Ai"], "Al band playing")[0] == "Ai band playing")
check("rn read as m: 'turn' for the clue's 'tum'", M.repaired(["turn"], "Lively tum I've put on")[0] == "Lively turn I've put on")
check("two look-alike clue words are not mended", M.repaired(["A1"], "Al and Ai meal")[0] is None)
check("a look-alike the quote itself uses is not mended", M.repaired(["Al", "A1"], "Al meal")[0] is None)
FEE = "Retain a fee in sheltered situation"
check("evidence that does not name the words is not enough",
      M.mend({**f, "printedClue": [FEE, "the scan is wrong here somewhere"]}, FEE, True) is None)
check("a printedClue that corrects something is left",
      M.mend({**f, "printedClue": ["Retain a fee in sheltered situation", "OCR misread: five for fee"]}, FIVE, True) is None)
import definitions
check("a quote that drops the crossref number is the clue's run",
      definitions.damaged_run("in position, to match down", "Salute in position to match 1 down")
      == "in position to match 1 down")
check("a dropped number at the run's edge is not mended",
      definitions.damaged_run("match 1", "Salute in position to match 1 down") == "match 1")
check("two runs with the number dropped are not mended",
      definitions.damaged_run("match down", "match 1 down or match 2 down") is None)

# the model copied the clue as scanned into printedClue[0] and put the right reading only in the evidence
def _declared(clue, wp, evidence, d="x"):
    a = {"def": d, "wp": wp, "printedClue": [clue, evidence]}
    return M.mend(a, clue, True)


row = _declared("Theatre to indulge in dn?", "[to indulge in]PLAY + [1dn]HOUSE", "OCR misread: 1dn", "Theatre")
check("a dropped digit ('dn' for 1dn) is mended from evidence naming it", row and row[0] == "Theatre to indulge in 1dn?")
row = _declared("4 reminder to me to get around people", "ins<to get around>([me]ME + [to]TO, [people]MEN)",
                "OCR misread: A", "A reminder")
check("a single letter read as a digit ('4' for A) is mended", row and row[0] == "A reminder to me to get around people")
row = _declared("I go astray in South American plain", "ins<in>([South American]SA, [I]I + [go astray]ERR)",
                "OCR misread: chain (a mountain range)", "chain")
check("the evidence need not name the clue word when exactly one is within two edits",
      row and row[0] == "I go astray in South American chain")
row = _declared("Suppressing a letter reversing rumours \u2014 about El /.",
                "ins<about>(rev<reversing>([rumours]NOISE), [51]LI)",
                "the wordplay needs 51 (LI), read as 'El /.'", "Suppressing a letter")
check("a run of debris the evidence quotes is replaced by the one absent quote word",
      row and row[0] == "Suppressing a letter reversing rumours \u2014 about 51")
check("two clue words within reach of the quote word are not mended",
      _declared("Ring plain, shain", "[chain]CH", "OCR misread: chain", "x") is None)
check("a short word with no digit is not mended from a near clue word",
      _declared("Not an all-American name", "[a]A + [man]MAN", "OCR misread: a man", "x") is None)

raise SystemExit(fails > 0)
