#!/usr/bin/env bash
# A paper's publishing boilerplate in the preamble goes; a puzzle's
# instructions, tributes and kept errata stay; the write gate refuses it.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import boilerplate
import puzzle_integrity

fails = 0
def check(name, ok, got=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else repr(got))

GONE = {
    "prize blurb": "£15 book tokens for the first five correct solutions opened. Solutions "
                   "postmarked not later than Saturday night to: The Observer PO Box 6604, "
                   "Birmingham, B26 3RW The first three correct solutions opened will receive "
                   "a set of stylish Penguin Dictionaries (worth £30).",
    "extra time": "We have allowed extra time for solvers who requested copies of Everyman "
                  "No. 3,065, inadvertently omitted from the paper on June 19. Solution and "
                  "winners will be published next week on July 10.",
    "bonus jumbo": "Today’s print edition has a bonus jumbo puzzle by Maskarade.",
    "reveal all + bonus": "Solution via ‘Reveal All’ button on 30 August 2025. The print "
                          "edition of 23 August 2025 includes a bonus jumbo puzzle.",
    "CMS id": "gdn.cryptic.29354.edcomments(2)",
    "test string": "This is a set of test instructions for crossword 21716",
    "not online": "Unfortunately, this week's Prize crossword cannot be posted online.",
    "print link": "For the print version of this crossword please click here.",
    "pdf instead": "Due to the unusual nature of this crossword please ignore the across and "
                   "down clues and instead use this pdf to solve the puzzle",
    "interactive grid": "For all clues containing 19 across, please click on the grid to enter "
                        "your answer.",
    "clues elsewhere": "Find today's crossword clues here.",
    "back link": "to go back to the Prize crossword.",
    "annotated stub": "For the annotated solution to this crossword",
}
for name, text in GONE.items():
    check(f"stripped whole: {name}", boilerplate.strip(text) is None, boilerplate.strip(text))

PART = [
    ("Paul intends to go on a sponsored trek in 26. To help him, please send a cheque payable "
     "to NDCS, addressed to: Fleur Deeson, NDCS, 15 Dufferin St, London EC1Y 8UR",
     "Paul intends to go on a sponsored trek in 26."),
    ("Solutions to the seven paired across clues should be placed in the grid as the down "
     "solutions allow. Deadline for this puzzle is Friday 10 June.",
     "Solutions to the seven paired across clues should be placed in the grid as the down "
     "solutions allow."),
    ("To see the clues for this crossword please click here Method: Solve the clues and fit "
     "the solutions in the diagram wherever they will go.",
     "Method: Solve the clues and fit the solutions in the diagram wherever they will go."),
    ("Method: Solve the clue, which can be found here, and fit the solutions into the diagram.",
     "Method: Solve the clue and fit the solutions into the diagram."),
    ("This Easter special is a double grid, the second part of which can be found here. "
     "Numbers used in cross-references always apply to the OTHER puzzle.",
     "This Easter special is a double grid. Numbers used in cross-references always apply to "
     "the OTHER puzzle."),
    ("Solve the clues and fit them into the grid wherever they will go jigsaw-wise.To avoid "
     "confusion with the numbers, the clues for this grid can be found here. You will need to "
     "disregard the numbers on the electronic version of the grid.",
     "Solve the clues and fit them into the grid wherever they will go jigsaw-wise. You will "
     "need to disregard the numbers on the electronic version of the grid."),
    ("Please note the numbers on this grid should be ignored. Please click here to see a pdf "
     "of the grid for clarification.", "Please note the numbers on this grid should be ignored."),
    ("Solve the clues and fit them into the grid wherever they will go, jigsaw-wise. And",
     "Solve the clues and fit them into the grid wherever they will go, jigsaw-wise."),
]
for text, want in PART:
    got = boilerplate.strip(text)
    check(f"instructions kept: {want[:40]}", got == want, got)

KEEP = [
    # Listener and Azed-style instructions.
    "Solvers must highlight in the grid a name that will explain their experience in entering "
    "the answers to the across clues; down answers are entered normally. Chambers Dictionary "
    "(2003) is the primary reference.",
    "In 22 clues, one letter has somehow moved to the clue above. These letters must be "
    "returned to the correct clues before solving, always creating or leaving behind real words.",
    "Clues are listed in alphabetical order of their solutions. Solutions are to be placed in "
    "the diagram jigsaw-wise, wherever they will fit.",
    # Errata the grid keeps (cryptic-24204, 24988, 25416, 25846).
    "There was an error in this Cryptic Crossword. The clue given for 18 down was \"German "
    "numero uno infiltrating group as kaiser?\" The answer was \"reigning\", but only the "
    "homophone, \"reining\" would fit.",
    "Unfortunately the answer to clue 21 across is a misspelling. We said that the flying "
    "machine made from canes was a CESNA. This should have been CESSNA. Our apologies.",
    "Note added 8 September 2011. There is a spelling mistake, involving one P too many, in "
    "the solution to 9 across.",
    "* there is an error in the clue and solution for 12 down",
    # The setter talking to the solver: titles, tributes, theme hints.
    "Most across solutions are of a kind and most of their clues lack definition. This puzzle "
    "was published in the print version of The Guardian under the title \"A walk on the wild side\".",
    "Araucaria has 18 down of the 19. This puzzle was originally published in the December "
    "issue of the magazine, 1 Across.",
    "This crossword is sponsored by Bells. The sponsor's products will appear in the diagonals.",
    "Paul in a 22 across 26 will be taking part on 26 April in aid of Sense, the charity for "
    "the deafblind.",
    "Running clockwise around the shaded squares, starting top left, is an extract from "
    "'The Headmistress Writes' (Mrs T. May) in 2018.",
]
for text in KEEP:
    check(f"kept: {text[:40]}", boilerplate.strip(text) == text and not boilerplate.find(text),
          boilerplate.strip(text))

p = {"id": "x", "preamble": GONE["print link"]}
boilerplate.apply(p)
check("a preamble of boilerplate only is removed", "preamble" not in p, p)

flags = []
puzzle_integrity.check_preamble({"id": "x", "preamble": GONE["bonus jumbo"]}, flags)
check("the write gate refuses boilerplate left in a preamble", bool(flags), flags)
flags = []
puzzle_integrity.check_preamble({"id": "x", "preamble": KEEP[0]}, flags)
check("the write gate passes instructions", not flags, flags)
raise SystemExit(fails)
PY
echo "all boilerplate checks passed"
