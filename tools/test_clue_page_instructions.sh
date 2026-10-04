#!/usr/bin/env bash
# A 2005-08 Guardian prize's special instructions are on the old-site clue page
# its note links to; the fetcher reads them from there and files them with the
# note (cryptic-23646 was filed with only "the numbers on this grid should be
# ignored", and its asterisked clues had nothing to define them).
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import fetch_puzzle as fp

fails = 0
def check(name, ok, got=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else repr(got))

NOTE_23646 = ('<a href="http://www.guardian.co.uk/crossword/page/0,13867,1672130,00.html">Click here</a> '
              'for clues and special instructions. <br /><br />Please note the numbers on this grid '
              'should be ignored. Please <a href="http://image.guardian.co.uk/sys-files/Guardian/documents/'
              '2005/12/23/prize_241205.pdf">click here</a> to see a pdf of the grid for clarification.  '
              '<br /><br />Click <a href="http://www.guardian.co.uk/crossword/page/0,13867,1675657,00.html">'
              'here</a> for an annotated explanation of the solutions.')
got = fp.clue_page_urls(NOTE_23646)
check("clue page link followed, pdf and annotated links not", got ==
      ["https://www.theguardian.com/crossword/page/0,13867,1672130,00.html"], got)
NOTE_23669 = ('<a href="http://www.guardian.co.uk/crossword/page/0,13867,1691401,00.html">Click here for '
              'the clues.</a><a href="http://www.guardian.co.uk/crossword/page/0,13867,1696455,00.html">'
              'Click here for an annotated explanation of the solutions.</a>')
got = fp.clue_page_urls(NOTE_23669)
check("adjacent links told apart", got ==
      ["https://www.theguardian.com/crossword/page/0,13867,1691401,00.html"], got)
NOTE_22929 = ('Solve the clues and fit the answers in jigsaw-wise.<br /><br /><A HREF="http://www.guardian.co.uk/'
              'crossword/page/0,13867,1031125,00.html ">Click here to see the clues</A>')
check("upper-case tag, padded href", len(fp.clue_page_urls(NOTE_22929)) == 1, fp.clue_page_urls(NOTE_22929))

PAGE_ACROSS = ('<FONT><B>Guardian/Collins holiday prize crossword No 23,646 Set by Araucaria</B><BR>The opening '
               'words of a novel are to go across the top.<br><br>Characters in the novel are asterisked.'
               '</FONT></TD></TR><TR><TD><FONT><B>Across</B><BR><b>1</b> A pretended laryngitis? (6)<br>')
got = fp.clue_page_instructions(PAGE_ACROSS)
check("note above Across", got == "The opening words of a novel are to go across the top. Characters "
      "in the novel are asterisked.", got)
PAGE_LETTERS = ('<B>Clues for Prize crossword No. 23681, by Araucaria</B></FONT></TD></TR><TR><TD><FONT><BR>'
                'Solve the clues and enter the solutions in the grid, jigsaw-wise wherever they will go.<br>'
                '</FONT></TD></TR></TABLE><!-- End trailblock widget --><!-- interp: /Widgets/Text/0,,5388307'
                '-111553-,00.html --><FONT><b>A</b> Blend with something else 997 years ago (5)<br>')
got = fp.clue_page_instructions(PAGE_LETTERS)
check("note above clues listed by letter, comments dropped", got == "Solve the clues and enter the "
      "solutions in the grid, jigsaw-wise wherever they will go.", got)
check("no clue list, no note", fp.clue_page_instructions("<b>Guide to solutions</b> Theme: x") is None)

got = fp.merge_preamble("Please note the numbers on this grid should be ignored.",
                        "Characters in the novel are asterisked.")
check("instructions first, then the note", got == "Characters in the novel are asterisked. Please "
      "note the numbers on this grid should be ignored.", got)
own = ("Solve the clues and fit them into the grid wherever they will go jigsaw-wise. You will need "
       "to disregard the numbers on the electronic version of the grid.")
check("note that holds the instructions kept as is", fp.merge_preamble(
    own, "Solve the clues and fit them into the grid wherever they will go jigsaw-wise.") == own)
own = ("Because of the symmetry of the diagram, acrosses and downs would be interchangeable; please "
       "arrange it so that the six solutions featuring seven similarly placed men all go across.")
check("one instruction worded twice: the note's wording", fp.merge_preamble(own, own.replace(
    "six solutions featuring seven", "five solutions featuring six")) == own)
check("no note: the instructions", fp.merge_preamble(None, "Jigsaw.") == "Jigsaw.")
check("no clue page: the note", fp.merge_preamble("Jigsaw.", None) == "Jigsaw.")
PAGE_23598 = ('<TD><B>Method</B><BR>Solve the clues and enter solutions in the grid jigsaw-wise, wherever '
              'they will go. <br><a href="http://x/y">Click here</b> to go back to the Prize crossword.</TD>'
              '<TD><b>A</b>\tA profit (5)<br><b>B</b>\tVoid (7)')
got = fp.clue_page_instructions(PAGE_23598)
check("a stray </b> in the note is not the title", got == "Solve the clues and enter solutions in the grid "
      "jigsaw-wise, wherever they will go.", got)
raise SystemExit(fails)
PY
