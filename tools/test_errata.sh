#!/usr/bin/env bash
# A paper's erratum in the preamble fixes its clue and leaves the preamble;
# the instructions beside it stay, and the write gate refuses one left behind.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import errata
import puzzle_integrity

def entry(number, direction, text, enum, **more):
    return {"number": number, "direction": direction, "length": 9,
            "clue": {"text": text, "enumeration": enum}, **more}

BASE = {"id": "cryptic-1", "entries": [
    entry(5, "down", "Senor of the road as well as in the dance", "9",
          annotation={"type": ["charade"]}),
    entry(18, "across", "Are these the main reasons for afternoon business in cafe, increases in naps?", "11"),
    entry(18, "down", "Something else entirely", "4"),
    entry(1, "down", "2s attributed to 22: Milk-calf as seen in veloute", "1,5,1,5",
          group=["1-down", "10-across", "4-down", "17-across"]),
    entry(1, "across", "Unrelated", "6"),
    entry(2, "down", "Corrected already", "6", group=["2-down", "20-across"]),
    entry(25, "across", "5  plus  11 = 4 x 4", "7,7", annotation={"type": ["charade"]}),
    entry(7, "down", "Me, pretentious, girl? Au contraire, in a manner of speaking", "5"),
    entry(17, "down", "Height 3pi   plus50  solved in old battlefield", "8"),
    entry(21, "across", "Woman harbouring classy derriere, keeping the nation hot", "6,3,5",
          annotation={"type": ["container"]}),
    entry(17, "across", "Painting, inaccurate portrayal of Moliere plot", "6,5"),
    entry(10, "across", "See 1", "5"),
]}

fails = 0
def check(name, ok, got=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else got)

def run(preamble):
    p = copy.deepcopy(BASE)
    p["preamble"] = preamble
    return p, errata.apply(p)

def clue(p, number, direction):
    return next(e for e in p["entries"] if e["number"] == number and e["direction"] == direction)

p, changed = run('Clue 5 down should read: "Señor of the road as well as in the dance"')
check("should read restores the accent", clue(p, 5, "down")["clue"]["text"].startswith("Señor"))
check("an erratum-only preamble is removed", "preamble" not in p, p.get("preamble"))
check("an accent alone keeps the annotation", "annotation" in clue(p, 5, "down") and not changed)

p, changed = run('Clue 5 down shoould read: "Señor of the road as well as in the dance"')
check("a misspelt should read is applied", clue(p, 5, "down")["clue"]["text"].startswith("Señor")
      and "preamble" not in p, p.get("preamble"))

p, changed = run("For 21 across read 'derrière'")
check("for N read restores the word in place",
      clue(p, 21, "across")["clue"]["text"] == "Woman harbouring classy derrière, keeping the nation hot"
      and "preamble" not in p and "annotation" in clue(p, 21, "across") and not changed,
      clue(p, 21, "across"))

p, _ = run("For 'Moliere' read 'Molière'.")
check("for X read Y replaces X in the clue holding it",
      clue(p, 17, "across")["clue"]["text"] == "Painting, inaccurate portrayal of Molière plot"
      and "preamble" not in p, clue(p, 17, "across"))

p, _ = run("Two writers are asterisked. The following clues should be asterisked: "
           "1 down and 10 across, 7 down.")
check("should be asterisked marks the clues, a linked clue by its leader",
      clue(p, 1, "down")["clue"]["text"].startswith("* 2s") and clue(p, 7, "down")["clue"]["text"]
      .startswith("* Me") and clue(p, 10, "across")["clue"]["text"] == "See 1"
      and p.get("preamble") == "Two writers are asterisked.", p.get("preamble"))

for note, kept in (("1 September 2016. The clue for 1 across has been modified.", None),
                   ("12/12/2020: changes, not affecting the solutions, have been made to five "
                    "of the original clues", None),
                   ("A ‘to’ has been restored to 17ac and a stray apostrophe removed from 4d.", None),
                   ("A word in the entry for 25 across no longer appears in the clue", None),
                   ("The clue for 25 across has been ammended.", None),
                   ("Thirty-three solutions consist of two parts. [10 January 2019: Clue for "
                    "25 across altered]", "Thirty-three solutions consist of two parts.")):
    p, _ = run(note)
    check(f"a correction without text is dropped: {note[:40]}",
          errata.find(note) and p.get("preamble") == kept and "annotation" in clue(p, 25, "across"),
          p.get("preamble"))

try:
    run("For 18 down read 'café'")
    check("a for-read whose word is not in the clue raises", False)
except ValueError as err:
    check("a for-read whose word is not in the clue raises, naming it", "18 down" in str(err), err)

p, _ = run('Clue 18 should read: "Are these the main reasons for afternoon business in café, increases in naps?"')
check("a number without direction resolves when one clue fits",
      "café" in clue(p, 18, "across")["clue"]["text"]
      and clue(p, 18, "down")["clue"]["text"] == "Something else entirely")

p, _ = run('Clue 1,10,4,17 should read "2s attributed to 22: Milk-calf as seen in velouté" (1,5,1,5)')
check("a linked clue is found by its group's numbers",
      clue(p, 1, "down")["clue"] == {"text": "2s attributed to 22: Milk-calf as seen in velouté",
                                     "enumeration": "1,5,1,5"}, clue(p, 1, "down")["clue"])

p, _ = run("Clue 25 across should read: \"5 + 11 = 4 x 4 (7,7)\"")
check("a reworded clue loses its annotation", clue(p, 25, "across")["clue"]["text"] == "5 + 11 = 4 x 4"
      and "annotation" not in clue(p, 25, "across"))

p, _ = run("7 November 2018: the clue for 2,20 has been corrected")
check("a correction note without text is dropped", "preamble" not in p, p.get("preamble"))

p, _ = run("Note added 16 August 2011. The clue for 22 across has been changed.")
check("its date head goes with it", "preamble" not in p, p.get("preamble"))

p, _ = run("Most across solutions are of a kind. Clue 5 down should read "
           "\"Señor of the road as well as in the dance (9)\" This puzzle was published "
           "under the title \"A walk\".")
check("instructions beside an erratum are kept",
      p.get("preamble") == "Most across solutions are of a kind. This puzzle was published "
      "under the title \"A walk\".", p.get("preamble"))

p, _ = run("In 7 down, au contraire should be in italics")
check("an italics erratum sets the span",
      clue(p, 7, "down")["clue"].get("italics") == [{"at": 23, "length": 12}],
      clue(p, 7, "down")["clue"])

p, _ = run("17 down should contain symbol for Pi and + but our tool cannot input these.")
check("spelt-out symbols are printed", clue(p, 17, "down")["clue"]["text"]
      == "Height 3π + 50 solved in old battlefield", clue(p, 17, "down")["clue"])

p, _ = run("Note: 2 December 2016. Five 5 solutions are not further defined, not six as originally indicated")
check("an amended instruction keeps the instruction",
      p.get("preamble") == "Five 5 solutions are not further defined", p.get("preamble"))

for keep in ("The solution to 13 should be interested in 10 others, not otherwise defined",
             "These letters must be returned to the correct clues before solving.",
             "This puzzle was originally published in the December issue of the magazine.",
             "Cuts have been made to fit the quote in the grid.",
             "There are minor changes and a hyphen, a dash and two full stops are lacking.",
             "One word ('that') has been omitted.",
             "For 12 clues an antonym of the solution – of the same length – is to be entered.",
             "For the subsidiary parts of the clues these letters are deemed to have been restored.",
             "This is Paul's first puzzle, published 25 years ago tomorrow, with a few clues updated.",
             "Solutions to asterisked clues are of a kind and may not be further defined.",
             # The paper confessing a flaw the grid keeps: no fix to apply.
             "There was an error in this Cryptic Crossword. The clue given for 18 down was \"German "
             "numero uno infiltrating group as kaiser?\" The answer was \"reigning\", but only the "
             "homophone, \"reining\" would fit.",
             "Unfortunately the answer to clue 21 across is a misspelling. We said that the flying "
             "machine made from canes was a CESNA. This should have been CESSNA. Our apologies.",
             "Note added 8 September 2011. There is a spelling mistake, involving one P too many, "
             "in the solution to 9 across.",
             "* there is an error in the clue and solution for 12 down"):
    p, _ = run(keep)
    check(f"not an erratum: {keep[:40]}", p.get("preamble") == keep and not errata.find(keep),
          p.get("preamble"))

try:
    run('Clue 9 down should read: "Nothing numbered 9 down"')
    check("an erratum naming no clue raises", False)
except ValueError as err:
    check("an erratum naming no clue raises, naming it", "Clue 9 down" in str(err), err)

flags = []
puzzle_integrity.check_preamble({"id": "x", "preamble": "Clue 5 down should read: Something"}, flags)
check("the write gate refuses an erratum left in a preamble", bool(flags), flags)
raise SystemExit(fails)
PY
echo "all errata checks passed"
