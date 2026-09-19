#!/usr/bin/env python3
"""Is the puzzle CORPUS sound — before anyone spends a model on annotating it?

Run it:

    python3 tools/puzzle_integrity.py            # every defect, with a per-check tally
    python3 tools/puzzle_integrity.py --quiet     # only the defects; silent when clean

Everything else in tools/ checks the work we ADD to a puzzle: validate_annotations.py
grades the annotation, coverage_report.py counts what each series holds. Nothing
checked the puzzle underneath, so a puzzle that arrived wrong stayed wrong and the
cost landed later — a duplicate gets annotated twice at full model price and then
shows up twice on the site, and a clue whose enumeration contradicts its own answer
teaches a learner to count wrong. Both are cheap to find mechanically and neither is
findable by eye at 6,800 puzzles. This is that sweep.

The flags, in the order they matter:

  DUPLICATE two or more files holding the same puzzle. Content-hashed over the
            entries — clue, solution, grid position, length — and over the grid
            dimensions, deliberately NOT over id, number, date, name, setter or
            annotation, because the question is whether the PUZZLE is the same and
            a resend arrives under a fresh number and date. Copies are grouped, so
            three files of one puzzle print as one group of three, not three pairs.
  LENGTH    an answer that contradicts the length the data itself states. Two
            statements exist per entry and both are checked: the grid's `length`
            field, and the (5,4)-style enumeration at the end of the clue. On a
            LINKED clue the enumeration is allowed to count either that light or
            the whole group, because the papers in this corpus do both — see
            check_length, which has the numbers. Some findings are excepted by
            name, in two tables keyed the same way but stating different things:
            PUBLISHED_WRONG is the Guardian contradicting itself, what it printed
            there cannot be reconciled with the grid beside it; UNLINKED_IN_SOURCE
            is the Guardian never recording a link at all, so the rest of the
            answer sits in a light this corpus has no license to invent a
            connection to.
  GRID      an entry list that is not a coherent grid: a light running off the
            board, two lights in one direction sitting on the same cell, one
            square carrying two clue numbers, a light nothing crosses, or so few
            checked cells that the thing is not a cryptic grid. The puzzle format
            has no block map — the geometry IS the entries, and a grid that was
            guessed or built off the wrong template can satisfy every length and
            every crossing and still be nonsense. The rule lives in
            apply_solution.check_geometry so the model-solve gate refuses to
            write a fill into an incoherent grid for the same reason.
  NUMBER    the stored clue numbers disagree with the numbers the puzzle's own
            grid would print. A blocked crossword's numbering is a pure function
            of its black squares (reconstruct_grid.lights_from_grid): scanning
            row-major, a cell takes the next number iff it starts an across or
            down light. So lights_from_grid(grid_of(puzzle)) must exactly equal
            lights_of(puzzle) — where it doesn't, a clue was given the wrong
            number, and every later clue numbered off the same collision drifts
            with it. Reported once per puzzle, at the first light where the two
            lists diverge, because a single wrong number is usually the root
            cause and everything after it is the same defect restated.
  CROSS     two entries that share a grid cell and disagree about its letter. One
            wrong answer normally breaks three or four of these, so a clean sheet
            is real evidence the fill is the paper's and not a mangling of it.
  PROV      a puzzle that does not say where it came from, or says something
            tools/provenance.py does not allow. The one that matters is
            solutionOrigin: a grid the setter published is ground truth, a grid
            this repo cold-solved is our guess, and until provenance existed
            the two were the same 15x15 of capital letters with nothing to tell
            them apart. So the check refuses an origin outside the enum, an
            origin that contradicts the file it sits on (claiming "published"
            over a solutionSource that says "model", or "unsolved" over a grid
            full of answers), a retrieval channel that disagrees with the tool
            that did the retrieving, and a publisher or series that disagrees
            with the puzzle's own id. Every allowed value is enumerated in
            tools/provenance.py and read from there, so this file does not hold
            a second copy of the list to fall out of step with the first.
  SHAPE     data that cannot be right whatever the puzzle says: no entries at all,
            a clue that is blank once its enumeration is removed, a puzzle whose
            clues are ALL blank — a grid with no puzzle in it, which no amount of
            per-clue forgiveness can be — a solution
            carrying something other than letters, the same entry id twice in one
            puzzle, or a date in the future or before EARLIEST_YEAR.

An entry whose solution carries non-letters is reported once, as SHAPE, and then
left out of LENGTH and CROSS — its letter count is not a second defect, it is the
same one counted again.

Puzzles published without answers (Saturday prize crosswords, until the paper
catches up about a week later) are not a defect: LENGTH and CROSS simply have
nothing to weigh for them and skip. Only entries that actually carry a solution
are checked, so an empty grid passes and a half-filled one is still checked as far
as it goes.

The corpus it reads is the puzzle files on disk. puzzles/index.json names them
and is generated, so it is rebuilt here before it is read — see fetch_puzzle.reindex.

Cost: one rebuild of the index, then one pass, one read per file, no network. All
six checks together, the index rebuild included, read the whole corpus in about
half a minute — 13,969 puzzles, ~400k clues, on 2026-09-18 — so every check is on
by default and none sits behind a flag. Nothing here is expensive enough to be worth
the confusion of an off-by-default check.

Exits 1 if anything is flagged, so the nightly can alert on it. It reports and
never writes: a defect here is a fetcher bug or a bad source page, and the fix
belongs in the fetcher or in a re-fetch, not in a repair pass over the files.
"""

import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_solution import (check_fill, check_geometry,  # noqa: E402
                            normalise)
from fetch_puzzle import (ENUMERATION, PER_LIGHT_ENUMERATION,  # noqa: E402
                          PUZZLE_DIR, has_words, is_bare_letters,
                          is_continuation, prints_own_count, puzzle_path,
                          read_puzzle_file, reindex)
from reconstruct_grid import grid_of, lights_from_grid, lights_of  # noqa: E402
import provenance  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# The flags, in the order they are reported. One tuple, read by both the
# per-finding listing and the tally, so a check cannot be added to one and
# missed from the other.
FLAGS = ("LENGTH", "CROSS", "GRID", "NUMBER", "SHAPE", "PROV")

# No cryptic crossword in this corpus predates the Guardian's, which began in 1929.
# A date below this is a page the publisher mis-filed or a fetcher that lost one,
# not an old puzzle. A backstop only: the Guardian serves such a page — its
# /crosswords/cryptic/1183 answers 200 with Quiptic 1,183's clues under a date of
# 1934-01-18 — but 1934 clears this bar, so what actually refuses it is the
# date-against-webPublicationDate check in fetch_puzzle.convert().
EARLIEST_YEAR = 1930

# The findings that are the PAPER, not the data we made of it: an enumeration no
# reading of the grid the Guardian published can satisfy, or a numbering the
# Guardian printed against itself, so no fetcher or repair can ever clear them
# and they would otherwise sit in the report for ever, teaching everyone to skim
# it. LENGTH, GRID and NUMBER all consult this table; a finding is forgiven by
# its own text, whichever check produced it.
#
# Keyed by puzzle AND by the whole finding, because the point is to forgive these
# two sentences and nothing else. Any other defect in the same clue — a changed
# answer, a light regrouped, a second count gone wrong — reads as a different
# finding and still reports.
#
# A third entry lived here for cryptic-27173 until 2026-09-17: 29-down and
# 23-down were never a real link (LINCOLN and OXFORD are cathedral cities in
# the puzzle's theme, not a linked answer), and d4ea38b's prune_one_sided_members
# later dropped that false group on its own account, for its own reason. The
# finding this forgave stopped occurring and nobody came back to remove the
# now-unreachable exception — caught by test_puzzle_integrity.sh proving every
# key here still matches a live finding, not just an exact one.
PUBLISHED_WRONG = {
    ("everyman-3072", "14-across: clue says (4,2,6) = 12, answer holds 13"):
        "ROAD TO NOWHERE fills the thirteen cells the grid gives it, and the "
        "Guardian's own separator positions (4 and 6) spell 4,2,7 under a count "
        "printed (4,2,6)",
    ("cryptic-23536", "23-down: clue says (5) = 5, answer holds 7"):
        "ERRHINE fills the seven cells the grid gives it under a clue printed (5)",
    ("quiptic-169", "13-down: clue says (4-5) = 9, answer holds 10"):
        "STEPPARENT is the anagram of the clue's own \"Repent past\" and fills the "
        "ten cells the grid gives it, under a count printed (4-5) for STEP-PARENT",
    ("cryptic-25949",
     "1-down + 24-across: clue says (4,5) = 9, answer holds 4 alone or 13 linked"):
        "1-down ASIL is counted (4,5) for ASIL NADIR, but NADIR is 26-across under "
        "a clue of its own and the paper linked 1-down to 24-across PANOPLIED (9)",
    ("cryptic-22813", "15-down: clue says (2,6) = 8, answer holds 10"):
        "SUSTAINING is one word of ten letters and fills the ten cells the grid "
        "gives it, under a clue the paper printed (2,6)",
    ("cryptic-21730",
     "11-across: 7 cells across from (0,83) runs off a 15x15 grid"):
        "the Guardian's own markup puts 11-across at \"position\":{\"x\":0,"
        "\"y\":83} on a grid it declares 15 rows tall; which row it meant is "
        "not something this data says",
    ("cryptic-21730",
     "numbering does not match the grid: 16 light(s) disagree, starting with "
     "the file's 12-across (7 cells) where the grid gives 12-across (5 cells)"):
        "11-across being off the board (see the finding above) is what the "
        "grid-derived numbering diverges on — with it missing from the grid, "
        "every number from 12 on is one light short of the file's; fixing the "
        "numbering would mean guessing where 11-across actually sits, which "
        "this data does not say",
    ("cryptic-21640",
     "1-across + 17-down + 5-across + 9-across + 14-down: clue says "
     "(6,1,3-4,6,4,2) = 26, answer holds 7 alone or 45 linked"):
        "the Guardian grouped all five lights itself and filled them with "
        "THERE'S A ONE-EYED YELLOW IDOL TO THE NORTH OF KHATMANDU, 45 cells, "
        "under an enumeration it printed only as far as the first 26",
# cryptic-22482 is the Guardian's 2002-04-01 Rufus puzzle, and its digitisation
# is rotated by one: from 14-down on, each clue sits beside the answer belonging
# to the light before it, and the lower half's coordinates are shifted with it.
# The across clues and the downs above 14 are all correct, so the grid pattern
# itself is a real, near-symmetric crossword — it is the paper's placement of
# the lower lights that is wrong, the same defect as cryptic-21730 below, at the
# scale of half a grid. Re-seating those lights would mean inventing coordinates
# the paper never printed, so they stay exactly as published.
    ("cryptic-22482", "26-down: clue says (6) = 6, answer holds 9"):
        "OVERSLEPT fills the nine cells the Guardian's own length gives "
        "26-down, under a count printed (6) — the clue beside it, \"Taking "
        "flight, running fast\", is 25-down FLYING's, one place up the rotated "
        "answer list",
    ("cryptic-22482",
     "cell (0, 7): crossing letters disagree — 14-down=R, 19-across=V"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (0, 9): crossing letters disagree — 14-down=C, 23-across=R"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (0, 11): crossing letters disagree — 14-down=I, 28-across=L"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (0, 13): crossing letters disagree — 14-down=A, 30-across=P"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (2, 7): crossing letters disagree — 15-down=U, 19-across=R"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (2, 9): crossing letters disagree — 15-down=F, 23-across=C"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (2, 13): crossing letters disagree — 15-down=K, 30-across=A"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (4, 7): crossing letters disagree — 16-down=L, 19-across=U"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (6, 6): crossing letters disagree — 17-across=A, 17-down=S"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (6, 7): crossing letters disagree — 17-down=P, 19-across=L"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (6, 8): crossing letters disagree — 17-down=Y, 21-across=L"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (7, 10): crossing letters disagree — 22-down=F, 27-across=A"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (7, 12): crossing letters disagree — 22-down=C, 29-across=A"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (8, 6): crossing letters disagree — 17-across=S, 18-down=A"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (8, 7): crossing letters disagree — 18-down=L, 20-across=P"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (8, 8): crossing letters disagree — 18-down=A, 21-across=Y"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (8, 10): crossing letters disagree — 18-down=A, 27-across=F"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (8, 12): crossing letters disagree — 18-down=A, 29-across=R"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (9, 10): crossing letters disagree — 24-down=D, 27-across=F"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (9, 12): crossing letters disagree — 24-down=T, 29-across=E"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (9, 14): crossing letters disagree — 24-down=R, 31-across=T"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (11, 10): crossing letters disagree — 25-down=L, 27-across=D"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (11, 12): crossing letters disagree — 25-down=I, 29-across=T"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (11, 14): crossing letters disagree — 25-down=G, 31-across=R"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (13, 10): crossing letters disagree — 26-down=V, 27-across=L"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (13, 12): crossing letters disagree — 26-down=R, 29-across=I"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "cell (13, 14): crossing letters disagree — 26-down=L, 31-across=G"):
        "the Guardian's answer list for this 2002-04-01 puzzle is rotated by "
        "one from 14-down on — 15-down's \"Realistic sort of joke for today\" "
        "clues 14-down's PRACTICAL, and 17-down's \"A couple of pounds for the "
        "lot\" clues 16-down's ALL — and the lower-half coordinates are "
        "rotated with it, so every crossing below row 6 disagrees; which "
        "cells the paper meant is not something this data says",
    ("cryptic-22482",
     "numbering does not match the grid: 10 light(s) disagree, starting with "
     "the file's 16-down (3 cells) where the grid gives 16-down (4 cells)"):
        "the same 2002-04-01 rotation that misplaces this puzzle's lower half "
        "(see the crossing and off-board findings above) leaves the grid's "
        "own numbering diverging from the file's from 16-down on; re-deriving "
        "it would mean guessing the coordinates the paper never printed",
    ("cryptic-22482",
     "26-down: 9 cells down from (13,9) runs off a 15x15 grid"):
        "the Guardian's own markup puts 26-down at \"position\":{\"x\":13,\"y\":9} "
        "with \"length\":9 on a grid it declares 15 rows tall; the same "
        "rotation that misplaces this puzzle's lower half put it there",
    ("cryptic-22061", "23-across: clue says (10,4) = 14, answer holds 10"):
        "the APPRENTICE BOYS who march by the Foyle need 24-across's BOYS, and "
        "24-across's pointer reads \"See 22\" — but 20-across PERSONAL + "
        "22-across NUMBER is already a complete (8,6) answer with no room in "
        "it for four more cells, so the number the paper printed on that "
        "pointer cannot be the one it meant",
}

# The LENGTH findings that are a light the Guardian never linked, not a mistake in
# either the clue or the grid: the enumeration counts letters that live somewhere
# else in the puzzle, and the only lights available for them already belong to a
# different answer, are still carrying their own separate clue, or do not exist at
# all — no light in the grid is blank, spare or grouped toward the missing
# letters. This repo's rule is to leave a light exactly as published —
# reconstructing the missing connection would be inventing a fact the paper never
# printed, so these can never be cleared by a fetcher or a repair pass either.
#
# Keyed the same way as PUBLISHED_WRONG — by puzzle and by the whole finding — and
# for the same reason: forgive exactly this sentence, not the clue it comes from,
# so any other defect on the same light still reports.
UNLINKED_IN_SOURCE = dict([
    (("cryptic-26330", "7-down: clue says (5-5) = 10, answer holds 5"),
     "BLANK, which would make POINT-BLANK, is not spare — its own clue commits it "
     "to 21-across's BLANK CHEQUE"),
    (("cryptic-26330", "10-across: clue says (14) = 14, answer holds 6"),
     "BREAKING, which would make GROUNDBREAKING, is not spare — its own clue "
     "commits it to 18-down's BREAKING POINT"),
    (("cryptic-26330", "15-across: clue says (11) = 11, answer holds 5"),
     "GROUND, which would make UNDERGROUND, is not spare — its own clue commits "
     "it to 10-across's GROUNDBREAKING"),
    (("cryptic-26330", "18-down: clue says (8,5) = 13, answer holds 8"),
     "POINT, which would make BREAKING POINT, is not spare — its own clue commits "
     "it to 7-down's POINT-BLANK"),
    (("cryptic-26330", "21-across: clue says (5,6) = 11, answer holds 5"),
     "CHEQUE, which would make BLANK CHEQUE, carries its own complete, "
     "self-contained clue and nothing links it here"),
    (("cryptic-26330", "25-down: clue says (10) = 10, answer holds 5"),
     "no light anywhere in this grid is blank, spare, or grouped toward "
     "completing it"),
    (("cryptic-26178", "6-across: clue says (8) = 8, answer holds 4"),
     "the WOOD that would make DASHWOOD is already spent on 1-down + 26-across's "
     "WOODHOUSE"),
    (("cryptic-25949", "17-across: clue says (5-3,5) = 13, answer holds 5"),
     "no group in this grid links it to the rest of the phrase, despite its own "
     "clue naming other numbers"),
    (("cryptic-25949", "20-across: clue says (7) = 7, answer holds 5"),
     "no group in this grid links it to the rest of the phrase, despite its own "
     "clue naming other numbers"),
    (("cryptic-25949", "22-across: clue says (9) = 9, answer holds 7"),
     "no group in this grid links it to the rest of the phrase, despite its own "
     "clue naming other numbers"),
    (("cryptic-25949", "28-across: clue says (9) = 9, answer holds 5"),
     "no group in this grid links it to the rest of the phrase, despite its own "
     "clue naming other numbers"),
    (("cryptic-25430",
      "22-down + 23-down + 12-across: clue says (6,1,5,3,4,2,6,3) = 30, "
      "answer holds 6 alone or 21 linked"),
     "Landor's epitaph repeats NATURE, which the grid holds only once, and ends "
     "in ART — already spent on 8-down + 19-across's ART DECO; no single light "
     "supplies the gap"),
    (("cryptic-25220",
      "23-across: clue says (3,7,4,2,8,4,2,5,2,3,7,1,4) = 52, answer holds 10"),
     "the missing 6 letters are 22-across LIFE IS (mislabelled '22-down' in the "
     "source), already spent on 14-across + 22-across's LIFE IS TOO SHORT"),
    (("cryptic-25126", "6-down: clue says (4,5) = 9, answer holds 4"),
     "the MINOR that would make ASIA MINOR is already spent on 17/19/20-across's "
     "MAJOR AND MINOR"),
    (("cryptic-25126", "8-down: clue says (4,5) = 9, answer holds 4"),
     "the MAJOR that would make DRUM MAJOR is already spent on 17/19/20-across's "
     "MAJOR AND MINOR"),
    (("cryptic-24951", "16-down: clue says (3,3,3,5,3,7) = 24, answer holds 3"),
     "the LET THE ... DOG SEE THE RABBIT it needs is already spent on "
     "18-down + 24-across + 8-down's own group"),
    (("cryptic-24640", "17-across: clue says (5,3,5) = 13, answer holds 5"),
     "the NEW and WORLD that would make BRAVE NEW WORLD are already spent on "
     "18/20/31-across's NEW WORLD ORDER"),
    (("cryptic-24575",
      "9-across + 18-down + 7-down + 16-down + 19-across + 29-across: "
      "clue says (3,4,2,3,8,3,3,9,3,5,3,5) = 51, answer holds 9 alone or 42 "
      "linked"),
     "the White Queen's line repeats JAM three times and adds AND once; the "
     "grid holds JAM only once and has no AND at all, so no light can supply "
     "the repeats"),
    (("cryptic-24540", "24-across: clue says (5,6) = 11, answer holds 5"),
     "no light in this grid is blank, spare, or grouped toward the six missing "
     "letters"),
    (("cryptic-24531", "22-across: clue says (3,4,3,4) = 14, answer holds 7"),
     "the LET IT BE that would finish SHE SAID LET IT BE is already spent on "
     "19-across + 6-down's own linked answer"),
    (("cryptic-24411", "4-down: clue says (4,4) = 8, answer holds 4"),
     "no light in this grid is blank, spare, or grouped toward the four missing "
     "letters"),
    (("cryptic-24303", "12-across: clue says (10) = 10, answer holds 5"),
     "HEART, which would make SWEETHEART, carries its own full separate clue at "
     "23-down (\"Try time at centre\")"),
    (("cryptic-24231",
      "4-across + 15-across + 12-across: clue says (6,8,4,3,4) = 25, "
      "answer holds 6 alone or 18 linked"),
     "no light in this grid is blank, spare, or grouped toward the seven missing "
     "letters"),
    (("cryptic-24133",
      "2-down + 16-down: clue says (6,3,5) = 14, answer holds 6 alone or 11 "
      "linked"),
     "no light in this grid is blank, spare, or grouped toward the three missing "
     "letters"),
    (("cryptic-24133",
      "21-across + 1-down: clue says (7,3,4) = 14, answer holds 7 alone or 11 "
      "linked"),
     "no light in this grid is blank, spare, or grouped toward the three missing "
     "letters"),
    (("cryptic-24133",
      "24-down + 8-down: clue says (4,7) = 11, answer holds 4 alone or 8 "
      "linked"),
     "no light in this grid is blank, spare, or grouped toward the three missing "
     "letters"),
    (("cryptic-24104", "13-across: clue says (6) = 6, answer holds 3"),
     "the ASH that would make POTASH is already spent on 18-down + 24-across's "
     "ASHORE"),
    (("cryptic-24104", "16-down: clue says (6) = 6, answer holds 3"),
     "the ORE that would complete it is already spent on 18-down + 24-across's "
     "ASHORE"),
    (("cryptic-23874", "18-down: clue says (5,8) = 13, answer holds 8"),
     "no light in this grid is blank, spare, or grouped toward the five missing "
     "letters"),
    (("cryptic-23837",
      "10-across + 1-down: clue says (3,4,4,3,2,5,5,4) = 30, answer holds 7 "
      "alone or 21 linked"),
     "no light in this grid is blank, spare, or grouped toward the nine missing "
     "letters"),
    (("cryptic-23834",
      "11-across + 27-across: clue says (7,11,13) = 31, answer holds 7 alone or "
      "21 linked"),
     "no light in this grid is blank, spare, or grouped toward the ten missing "
     "letters"),
    # 23,821 is the shape this table exists for, seven times over. Its theme is
    # LEFT, RIGHT and CENTRE, and the paper clues each of the three lights
    # holding them into several answers at once — RIGHT alone finishes MISTER
    # RIGHT, INSIDE RIGHT, RIGHT NOTE and RIGHT AS RAIN. `group` is one list per
    # entry, so each of the three can be written into exactly one of its
    # answers, and these are the answers left over.
    (("cryptic-23821", "4-across: clue says (6,5) = 11, answer holds 6"),
     "the RIGHT that would make MISTER RIGHT is already spent on "
     "23-down + 16-across's RIGHT NOTE"),
    (("cryptic-23821", "5-down: clue says (6,5) = 11, answer holds 6"),
     "the RIGHT that would make INSIDE RIGHT is already spent on "
     "23-down + 16-across's RIGHT NOTE"),
    (("cryptic-23821", "22-across: clue says (5,2,4) = 11, answer holds 6"),
     "the RIGHT that would make RIGHT AS RAIN is already spent on "
     "23-down + 16-across's RIGHT NOTE"),
    (("cryptic-23821", "15-across: clue says (4,6) = 10, answer holds 4"),
     "the CENTRE that would make SOFT CENTRE is already spent on "
     "20-down + 1-across's CENTRE SPREAD"),
    (("cryptic-23821", "17-across: clue says (9,6) = 15, answer holds 9"),
     "the CENTRE that would make DETENTION CENTRE is already spent on "
     "20-down + 1-across's CENTRE SPREAD"),
    (("cryptic-23821", "26-across: clue says (6,6) = 12, answer holds 6"),
     "the CENTRE that would make GARDEN CENTRE is already spent on "
     "20-down + 1-across's CENTRE SPREAD"),
    (("cryptic-23821", "16-down: clue says (7,4) = 11, answer holds 7"),
     "the LEFT that would make NOTHING LEFT is already spent on "
     "9-across + 11-across's LEFT UNDONE"),
    (("cryptic-23753",
      "1-across + 52-across: clue says (4,6-4) = 14, answer holds 4 alone or 8 "
      "linked"),
     "no light in this grid is blank, spare, or grouped toward the six missing "
     "letters"),
    (("cryptic-23753", "48-down: clue says (7) = 7, answer holds 3"),
     "no light in this grid is blank, spare, or grouped toward the four missing "
     "letters"),
    (("cryptic-23731",
      "3-down + 16-down + 4-down + 5-down + 11-across + 21-across: "
      "clue says (2,2,4,4,4,3,4,4,5,4,2,4,4,7) = 53, answer holds 4 alone or 49 "
      "linked"),
     "the Macbeth line repeats WERE, DONE and IT; the grid holds each only once, "
     "so no light can supply the repeats"),
    (("cryptic-23695",
      "13-down + 9-across: clue says (4-6,9,6) = 25, answer holds 10 alone or "
      "19 linked"),
     "no light in this grid is blank, spare, or grouped toward the six missing "
     "letters"),
    (("cryptic-23660", "7-down: clue says (4,1,5,3) = 13, answer holds 5"),
     "no light in this grid is blank, spare, or grouped toward the eight missing "
     "letters"),
    (("cryptic-23651",
      "8-down + 16-down + 1-across + 4-across + 15-across + 25-across: "
      "clue says (3,3,4,3,3,3,6,6,2,1,4,4,4) = 46, answer holds 13 alone or 40 "
      "linked"),
     "the song lyric repeats SHE WAS; the grid holds it only once, so no light "
     "can supply the repeat"),
    (("cryptic-23626", "22-down: clue says (4,2,4) = 10, answer holds 6"),
     "the LOVE that would make FALL IN LOVE is already spent on "
     "27-across + 28-across's own linked answer, whose clue names this light "
     "too (\"See 28 and 22\")"),
    (("cryptic-23625", "8-across: clue says (4,4,5) = 13, answer holds 8"),
     "no light in this grid is blank, spare, or grouped toward the five missing "
     "letters"),
    (("cryptic-23559",
      "7-down: clue says (1,4-2,3,3,4) = 17, answer holds 13"),
     "no light in this grid is blank, spare, or grouped toward the four missing "
     "letters"),
    (("cryptic-23541",
      "4-down + 19-down + 8-down: clue says (6,1,5 and 4,2,6,3) = 27, "
      "answer holds 6 alone or 23 linked"),
     "no light in this grid is blank, spare, or grouped toward the four missing "
     "letters"),
    (("cryptic-23501",
      "8-across + 9-across: clue says (3,5,2,3,5,5) = 23, answer holds 8 alone "
      "or 13 linked"),
     "no light in this grid is blank, spare, or grouped toward the ten missing "
     "letters"),
    (("cryptic-23429",
      "17-across + 27-across: clue says (1,4,7,4) = 16, answer holds 5 alone or "
      "9 linked"),
     "the BRITISH that would make A VERY BRITISH COUP is already spent on "
     "24-across + 29-across's BRITISH EMPIRE"),
    (("cryptic-23405", "23-down: clue says (5,4) = 9, answer holds 5"),
     "the ARMS that would make SLOPE ARMS is already spent on 9-across + "
     "24-down's ORDER ARMS"),
    (("cryptic-23314", "13-across: clue says (7,7) = 14, answer holds 7"),
     "no light in this grid is blank, spare, or grouped toward the seven "
     "missing letters"),
    (("cryptic-23299",
      "1-across + 19-down + 10-across: clue says (2,3,2,5,2,7,6) = 27, "
      "answer holds 7 alone or 22 linked"),
     "no light in this grid is blank, spare, or grouped toward the five missing "
     "letters, despite the clue naming other numbers"),
    (("cryptic-23299",
      "9-across + 24-down: clue says (5,4,6) = 15, answer holds 5 alone or 9 "
      "linked"),
     "no light in this grid is blank, spare, or grouped toward the six missing "
     "letters, despite the clue naming other numbers"),
    (("cryptic-23299", "12-across: clue says (4,5,2) = 11, answer holds 4"),
     "no light in this grid is blank, spare, or grouped toward the seven "
     "missing letters"),
    (("cryptic-23247", "19-down: clue says (7,4) = 11, answer holds 7"),
     "the TOWN that would make SWINDON TOWN is 9-across, whose own clue reads "
     "\"See 15 and 19\" and whose one `group` field the paper spent on "
     "15-across + 9-across's FREETOWN"),
    (("cryptic-22968",
      "3-down + 21-down: clue says (4,2,3,3,2,3,3,4) = 24, answer holds 4 "
      "alone or 12 linked"),
     "Forsyth's catchphrase says NICE and TO SEE YOU twice each; the grid holds "
     "each once, at 3-down and 21-down, and every other light in it carries its "
     "own clue and its own answer"),
    (("cryptic-22933", "22-down: clue says (8) = 8, answer holds 4"),
     "the PLAY that would make WORDPLAY is 8-down, whose clue reads \"See 1 "
     "across and 22\" — it ends the SCOTTISH PLAY too, and the paper's one "
     "`group` field is spent on 1-across"),
    (("cryptic-22841",
      "8-down + 21-down + 12-down: clue says (4,2,3,2,3,4,6) = 24, answer "
      "holds 4 alone or 18 linked"),
     "the CHANCE that finishes HAVE AN EYE TO THE MAIN CHANCE is 1-down, "
     "already spent on 1-down + 15-across + 2-down's CHANCE WOULD BE A FINE "
     "THING"),
    (("cryptic-22831", "12-across: clue says (6,6) = 12, answer holds 6"),
     "the ESTATE that would make FOURTH ESTATE is 25-across, which carries a "
     "full clue of its own and is pointed at by 7-down's \"See 25\" for ESTATE "
     "AGENTS"),
    (("cryptic-22831", "15-across: clue says (7,6) = 13, answer holds 7"),
     "the same 25-across ESTATE would make HOUSING ESTATE, and one light "
     "cannot be the second word of three answers at once"),
    (("cryptic-21640", "20-down: clue says (5,7) = 12, answer holds 5"),
     "the THERESA that makes SAINT THERESA is 1-across, spent on the paper's "
     "own five-light group for the ONE-EYED YELLOW IDOL line — 19-down's "
     "\"Whence 20,1across\" names both uses"),
    (("cryptic-22691",
      "8-down + 23-down + 11-across + 18-down: clue says "
      "(3,6,2,3,5,2,3,5,2,4,10) = 45, answer holds 14 alone or 31 linked"),
     "the KING CARACTACUS the song ends on is 1-across, which carries a full "
     "clue of its own"),
    (("cryptic-21750",
      "3-down + 17-down: clue says (3,5,11,7) = 26, answer holds 8 alone or "
      "15 linked"),
     "the SHAKESPEARE in THE ROYAL SHAKESPEARE COMPANY is 5-down, which "
     "carries a full clue of its own"),
    (("cryptic-21748", "16-down: clue says (4,4,7) = 15, answer holds 8"),
     "the FORWARD that finishes BEST FOOT FORWARD is 1-across, which carries a "
     "full clue of its own — 5-across names the pair as \"16 1across\""),
    (("cryptic-21718", "12-across: clue says (4,6) = 10, answer holds 4"),
     "the LITTLE that makes JOHN LITTLE is 19-down, already spent on 19-down + "
     "8-down's LITTLE GREEN MEN"),
    (("cryptic-21625", "6-down: clue says (5,2,3,5,2,4) = 21, answer holds 15"),
     "the OF TIME that finishes DANCE TO THE MUSIC OF TIME is 7-down, which "
     "12-across's AHEAD OF TIME needs just as much; one light, two answers"),
    (("cryptic-21625", "12-across: clue says (5,2,4) = 11, answer holds 5"),
     "the same 7-down OF TIME finishes 6-down's DANCE TO THE MUSIC OF TIME, "
     "and `group` cannot say a light ends both"),
    (("cryptic-22490",
      "20-down + 4-down + 4-across: clue says (5,6,3,5,8) = 27, answer holds "
      "5 alone or 22 linked"),
     "SEVEN BRIDES FOR SEVEN BROTHERS needs SEVEN twice and the paper gave it "
     "one five-cell light: 20-down holds the first, 4-down BRIDES FOR and "
     "4-across BROTHERS the rest, and the second SEVEN has no light anywhere "
     "in this grid"),
    (("cryptic-22575", "10-across: clue says (6-3,6-4) = 19, answer holds 9"),
     "the clue opens \"(and 10 again)\" — the paper spends one nine-cell light "
     "twice, printing THIRTY-SIX (6-3) in it and counting a second (6-4) "
     "answer it never gave a light to"),
    (("cryptic-22289", "21-across: clue says (5,5) = 10, answer holds 5"),
     "the ADLER that makes LARRY ADLER is 10-across, already spent on "
     "13-across + 10-across's IRENE ADLER in this Freud-themed grid; one "
     "light, two answers"),
    (("cryptic-22289", "21-down: clue says (6,5) = 11, answer holds 6"),
     "the FREUD that makes LUCIAN FREUD is 24-across, which 22-across + "
     "24-across's CLEMENT FREUD needs just as much, and `group` cannot say a "
     "light ends both"),
    (("cryptic-22327",
      "21-down + 20-down: clue says (6,6,6) = 18, answer holds 6 alone or 12 "
      "linked"),
     "WHEELS WITHIN WHEELS needs WHEELS twice and the paper gave it one "
     "six-cell light: 21-down holds it, 20-down holds WITHIN, and the closing "
     "WHEELS has no light of its own"),
    (("cryptic-22098",
      "5-across + 26-across + 12-across + 19-across: clue says "
      "(6,2,3,5,6,2,4,6) = 34, answer holds 6 alone or 28 linked"),
     "PLEASE DO NOT THROW STONES AT THIS NOTICE is 34 letters and the four "
     "lights the paper grouped hold 28 of them; the AT THIS (2,4) in the "
     "middle has no light anywhere in this grid"),
    (("cryptic-22081",
      "18-across + 22-across: clue says (3,6,1,4,3,7,5) = 29, answer holds 9 "
      "alone or 24 linked"),
     "Marvell's THE GRAVE'S A FINE AND PRIVATE PLACE is 29 letters and the "
     "two lights hold 24 - THE GRAVE'S (3,6) and AND PRIVATE PLACE (3,7,5); "
     "the A FINE (1,4) between them has no light of its own"),
    (("cryptic-22037",
      "3-down + 25-across: clue says (4,4,3,3,7,2) = 23, answer holds 4 alone "
      "or 19 linked"),
     "the WHAT that makes LOOK WHAT THE CAT DRAGGED IN is 21-across, already "
     "spent on 21-across + 23-down + 9-across + 11-across's WHAT SORT OF TIME "
     "DO YOU CALL THIS THEN; one light, two answers"),
    (("cryptic-22022", "24-across: clue says (8) = 8, answer holds 4"),
     "the FORD that makes Constable's FLATFORD is 24-down, whose own clue "
     "reads \"See 2 and 24 across\" and so names both leaders itself; `group` "
     "holds one list and it went to 2-down"),
    (("cryptic-21893", "11-across: clue says (6,4,2,3,8) = 23, answer holds 12"),
     "BATTLE HYMN OF THE REPUBLIC is 23 letters and 11-across holds the "
     "twelve of BATTLE HYMN OF; no light in this grid is blank, spare or "
     "grouped toward THE REPUBLIC, and 1-across's PUBLIC is a different word "
     "carrying its own clue, spent on 1-across + 9-across's PUBLIC NUISANCE"),
])

# PER_LIGHT_ENUMERATION names the series whose linked clues are enumerated one
# light at a time, and is imported rather than restated: the fetcher dissolves a
# group whose every leg counts its own light (dissolve_false_groups), and this
# check forgives exactly that shape. Two lists would let one paper be forgiven
# here and taken apart there. The Guardian and the Independent count the whole
# answer on the leading clue, so they are held to the strict reading and a group
# that has gone wrong there still shows up — with one exception that is about
# the CLUE and not the paper: a leg printed "See 3 (6)", which the Guardian did
# routinely before about 2015, is counting its own cells, and check_length reads
# it that way in every series. fetch_puzzle.is_continuation decides which clues
# those are.


def content_hash(puzzle):
    """A puzzle's identity as a solver would judge it: the same clues, in the same
    cells, with the same answers, in a grid of the same size. Entries are sorted so
    that a re-fetch which happens to emit them in another order still matches."""
    entries = sorted(
        (e.get("id"), e.get("number"), e.get("direction"),
         (e.get("position") or {}).get("x"), (e.get("position") or {}).get("y"),
         e.get("length"), e.get("clue"), e.get("solution"))
        for e in puzzle.get("entries") or []
    )
    dims = puzzle.get("dimensions") or {}
    blob = json.dumps([dims.get("cols"), dims.get("rows"), entries], ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def check_shape(puzzle, today, flags):
    """Defects visible in one entry on its own, plus the puzzle-level ones.

    Returns the entries fit to weigh for LENGTH and CROSS — those whose solution is
    present and is letters only. Everything else has already been reported here."""
    pid = puzzle["id"]
    entries = puzzle.get("entries") or []
    if not entries:
        flags.append(("SHAPE", pid, "no entries at all"))
        return []

    ms = puzzle.get("date")
    if ms is None:
        # coverage_report.py owns DATELESS; it can see which series it thins out.
        pass
    else:
        d = datetime.fromtimestamp(ms / 1000, timezone.utc).date()
        if d > today:
            flags.append(("SHAPE", pid, f"dated {d}, which is in the future"))
        elif d.year < EARLIEST_YEAR:
            flags.append(("SHAPE", pid, f"dated {d}, before cryptics existed"))

    # A clue marked clueMissing is forgiven one at a time, because a setter who
    # prints one blank clue means it. A puzzle where EVERY clue is blank is not a
    # setter's joke, it is a grid with no puzzle in it: nothing to solve, nothing
    # to annotate, and nothing the app can show. Per-entry forgiveness cannot see
    # that, so it is asked here, of the whole puzzle, once.
    #
    # These are recoverable, which is why there is no exception table for them.
    # The 14 of 15 in the corpus that fall on a Saturday say what went wrong: the
    # answers came off a prize puzzle's solution page and the clue text lives on
    # /crosswords/prize/<n>, not /crosswords/cryptic/<n>, and in the printable PDF
    # beside it. So this reports until someone goes and gets the clues.
    if not any(has_words(e.get("clue")) for e in entries):
        flags.append(("SHAPE", pid, f"all {len(entries)} clues are blank"))

    seen, checkable = set(), []
    for e in entries:
        eid = e.get("id")
        if eid in seen:
            flags.append(("SHAPE", pid, f"entry id {eid} appears twice"))
        seen.add(eid)

        # A clue is its words. has_words is the one definition of "the paper
        # printed nothing here" — the same rule fetch_puzzle.convert() uses to
        # set clueMissing at fetch time — so this reads the words off the same
        # test rather than reimplementing a stripped-enumeration check that can
        # drift from it. It did drift: cyclops-309's 17-across is "(see 3dn.)",
        # a bare cross-reference wholly inside one parenthesis and a whole clue
        # by has_words' own rule ("A bare cross-reference is a whole clue"), but
        # the old ENUMERATION.sub(...).strip() check here matched the whole
        # parenthesis as if it were an enumeration and stripped it to nothing,
        # reporting a real clue as blank.
        #
        # Unless the paper printed it blank, which setters do as the trick itself:
        # cryptic-30098's 12-across is wordless so that its own number is the only
        # thing left pointing at NOONDAY, and cryptic-29345's 5-down is wordless
        # over (1,6,3,1,4) for I HAVEN'T GOT A CLUE. Both are the joke and must
        # never be filled in or filtered out. fetch_puzzle.convert() settles which
        # is which at fetch time, where the paper's own data is still in front of
        # it, and records the answer as clueMissing — so this reads that field
        # rather than guessing again from the text and reaching a different
        # verdict. An unmarked blank clue is still a defect and still reported.
        clue = e.get("clue") or ""
        if not e.get("clueMissing") and not has_words(clue):
            flags.append(("SHAPE", pid, f"{eid}: clue is blank"))

        solution = e.get("solution")
        if not solution:
            continue
        # One rule, spelled in the fetcher: a solution is A-Z and nothing else.
        # convert() now refuses to WRITE anything that fails it — a page serving
        # a masked answer ("T?S?R", Guardian cryptic 28,691 3-down) is stored
        # unsolved instead — so anything caught here arrived before that guard
        # or from a fetcher that does not go through convert().
        if not is_bare_letters(solution):
            flags.append(("SHAPE", pid, f"{eid}: solution {solution!r} is not bare letters"))
            continue
        checkable.append(e)
    return checkable


def check_length(puzzle, checkable, flags):
    """The two length statements the data makes about an answer, against the answer.

    Grid length is per entry, and is checked per entry: an answer that does not fit
    its own light is wrong however the clue is printed.

    The enumeration is the looser one, because a LINKED clue is enumerated two ways
    and this corpus holds both. The Guardian and the Independent print the whole
    answer's count on the light that carries the clue and nothing on the others, so
    29,069's "(6,8,9)" belongs to LONDON + SYMPHONY + ORCHESTRA together. Private
    Eye prints each light its own count instead, on every light including the
    leading one: Cyclops 401's 2-down reads "(& 22dn.) … (4-6)" for its own ten
    cells while 22-down reads "see 2dn. (6)" for its six. Measured across 769
    linked Cyclops groups, 760 leading lights and 778 continuations count only
    their own light — and then nine leaders and two continuations print the group's
    whole count, in the same paper, so it is not even a rule per publisher.

    So a linked clue's enumeration is required to equal its own light or the whole
    group, and anything else is the defect. That is weaker than the unlinked check
    deliberately: the alternative is 1,538 Cyclops clues reported for obeying their
    own paper's convention, and a check nobody can read is a check nobody reads.
    The grid-length test above is untouched and still holds every light to its own
    cells, which is where a wrong ANSWER shows up; this one catches a wrong COUNT,
    and it still caught 29,069, whose clue promised 23 letters over a group the
    Guardian's own data had truncated to 15."""
    pid = puzzle["id"]
    by_id = {e["id"]: e for e in puzzle.get("entries") or []}
    for e in checkable:
        eid, solution = e["id"], e["solution"]
        if len(solution) != e.get("length"):
            flags.append(("LENGTH", pid, (f"{eid}: {solution} is {len(solution)} letters, "
                                          f"grid wants {e.get('length')}")))
            continue

        m = ENUMERATION.search(e.get("clue") or "")
        if not m:
            # A continuation leg ("See 23") carries no count of its own; its length
            # is stated once, on the leg that holds the clue.
            continue
        counts = [int(n) for n in re.findall(r"\d+", m.group(1))]
        if not counts:
            continue
        group = e.get("group") or [eid]
        legs = [by_id.get(gid, {}).get("solution") for gid in group]
        if any(not s for s in legs):
            continue  # part of the answer is unpublished; nothing to compare yet
        held = sum(len(normalise(s)) for s in legs)
        # A counted continuation counts its own light, in any paper. "See 2 (6)"
        # has no wordplay to count anything else with: cryptic-23578's 7-down is
        # that exactly, six cells of IGNATIUS LOYOLA whose "(8,6)" is printed
        # where it belongs, on 2-down. The Guardian did this routinely before
        # about 2015, so the reading is not a licence handed to a publisher but
        # one the clue itself asks for — see fetch_puzzle.prints_own_count,
        # which also covers the leg left wordless over its own cell count when
        # the pointer went missing, cryptic-21762's 26-across " (8)".
        per_light = (puzzle.get("series") in PER_LIGHT_ENUMERATION
                     or prints_own_count(e))
        # A counted continuation inside a linked answer is not measured at all.
        # Only the leading clue enumerates the answer; a leg's count describes
        # lights, and which lights depends on markup this file no longer sees —
        # the Guardian's pre-2015 pairs put a chain's middle leg in a sub-group
        # of its own, so "See 26 (7,8)" on cryptic-22249's 17-across counts that
        # leg plus 20-across, neither its own seven cells nor the answer's 31.
        # Measuring it against either reports the head's correct enumeration as
        # a defect on the leg. The head is still checked, so nothing goes unread.
        if len(group) > 1 and is_continuation(e.get("clue")):
            continue
        if sum(counts) == held or (len(group) > 1 and per_light
                                   and sum(counts) == len(solution)):
            continue
        where = eid if len(group) == 1 else " + ".join(group)
        holds = f"{held}" if len(group) == 1 else f"{len(solution)} alone or {held} linked"
        finding = (f"{where}: clue says ({m.group(1)}) = "
                   f"{sum(counts)}, answer holds {holds}")
        if (pid, finding) in PUBLISHED_WRONG or (pid, finding) in UNLINKED_IN_SOURCE:
            continue
        flags.append(("LENGTH", pid, finding))


def check_grid(puzzle, flags):
    """The grid the entries describe, from tools/apply_solution.py — the same
    check that gates a model fill before it is written. It is asked of the whole
    entry list, answered or not, because a light is in the grid whether or not
    anyone has filled it in yet."""
    pid = puzzle["id"]
    for problem in check_geometry(puzzle):
        if (pid, problem) in PUBLISHED_WRONG:
            continue
        flags.append(("GRID", pid, problem))


def check_numbering(puzzle, flags):
    """Clue numbers as a pure function of the grid, against the numbers stored.

    reconstruct_grid.lights_from_grid scans the puzzle's own grid (built from
    entry positions and lengths, the same grid_of() check_grid judges) row-major
    and hands out the next number exactly when a cell starts an across or down
    light. That is the whole rule a publisher's numbering follows, so it must
    reproduce reconstruct_grid.lights_of(puzzle) — the numbers, directions and
    lengths the file actually stores — exactly. Where it doesn't, a light was
    given the wrong number: a collision with another light's number, or a cell
    that starts both an across and a down light and wrongly got two different
    ones, and either shifts every later number that shares its row-major order.

    Reported once per puzzle rather than once per shifted light, at the first
    point the two lists diverge — everything downstream of a numbering
    collision is the same defect restated, not a second one."""
    pid = puzzle["id"]
    derived = sorted(lights_from_grid(grid_of(puzzle)))
    stored = sorted(lights_of(puzzle))
    if derived == stored:
        return

    def fmt(light):
        return "nothing" if light is None else f"{light[0]}-{light[1]} ({light[2]} cells)"

    diffs = [(d, s) for d, s in zip_longest(derived, stored) if d != s]
    d, s = diffs[0]
    finding = (f"numbering does not match the grid: {len(diffs)} light(s) disagree, "
               f"starting with the file's {fmt(s)} where the grid gives {fmt(d)}")
    if (pid, finding) in PUBLISHED_WRONG:
        return
    flags.append(("NUMBER", pid, finding))


def check_cross(puzzle, checkable, flags):
    """Crossing-letter agreement, from tools/apply_solution.py — the same check that
    gates a model-solved grid before it is written. It is handed only the entries
    that are answered and the right length, so every problem it returns is a
    crossing conflict and nothing has to be re-derived here."""
    if not checkable:
        return
    pid = puzzle["id"]
    fill = {e["id"]: e["solution"] for e in checkable}
    _, _, problems = check_fill({**puzzle, "entries": checkable}, fill)
    for p in problems:
        # The same guard check_grid and check_length carry. A crossing conflict
        # is as much "the Guardian contradicting itself" as an off-grid light
        # is — cryptic-22482 is one grid's worth of them — and without this the
        # table could hold a key no run could ever reach, which is the one thing
        # test_puzzle_integrity.sh fails on.
        if (pid, p) in PUBLISHED_WRONG:
            continue
        flags.append(("CROSS", pid, p))


def check_provenance(puzzle, flags):
    """Where the puzzle and its answers came from — tools/provenance.py.

    Every allowed value is enumerated in that module and nowhere else; this
    check only asks whether the file agrees with it. The reason it is a corpus
    check rather than a fetcher assert is that a fetcher can only vouch for the
    puzzles it wrote, and the failure this guards against is a grid we solved
    ourselves becoming indistinguishable from the setter's own answer key —
    which is a property of the corpus as a whole, and is only ever noticed if
    something sweeps the whole of it."""
    for finding in provenance.check(puzzle):
        flags.append(("PROV", puzzle["id"], finding))


def audit(rows, today):
    """One flat list of (flag, puzzle id, what) plus the duplicate groups."""
    flags = []
    by_content = defaultdict(list)
    for row in rows:
        # From the id, not from row["file"]: that field names the generated
        # .js shim the browser loads, and the puzzle itself is the .json.
        puzzle = read_puzzle_file(puzzle_path(row["series"], row["number"]))
        by_content[content_hash(puzzle)].append(puzzle["id"])
        checkable = check_shape(puzzle, today, flags)
        check_provenance(puzzle, flags)
        check_grid(puzzle, flags)
        check_numbering(puzzle, flags)
        check_length(puzzle, checkable, flags)
        check_cross(puzzle, checkable, flags)
    copies = sorted(sorted(ids) for ids in by_content.values() if len(ids) > 1)
    return flags, copies


def main(argv):
    quiet = "--quiet" in argv
    started = time.time()
    # Rebuilt, not read: reindex() writes one row per file it just walked, so
    # every row below names a file that is there. What this tool judges is the
    # corpus, and a stale manifest is not a defect in it.
    rows = reindex()["puzzles"]
    flags, copies = audit(rows, datetime.now(timezone.utc).date())

    for ids in copies:
        print(f"DUPLICATE {len(ids)} files hold the same puzzle: " + ", ".join(ids))
    by_flag = defaultdict(list)
    for flag, pid, what in flags:
        by_flag[flag].append((pid, what))
    for flag in FLAGS:
        for pid, what in by_flag[flag]:
            print(f"{flag:<9} {pid:<22} {what}")

    total = len(flags) + sum(len(ids) for ids in copies)
    if quiet:
        return 1 if total else 0

    elapsed = time.time() - started
    print(f"\n{len(rows)} puzzles indexed and read in {elapsed:.1f}s")
    print(f"  DUPLICATE {sum(len(i) for i in copies)} files in {len(copies)} groups")
    for flag in FLAGS:
        print(f"  {flag:<9} {len(by_flag[flag])}")
    if not total:
        print("\nno duplicates, every grid coherent, every grid's own numbering "
              "matches its clues, every stated length agrees, every crossing agrees, "
              "and every puzzle says where it and its answers came from")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
