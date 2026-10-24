#!/usr/bin/env python3
"""Is the puzzle CORPUS sound — before anyone spends a model on annotating it?

Run it:

    python3 tools/puzzle_integrity.py            # every defect, with a per-check tally
    python3 tools/puzzle_integrity.py --quiet     # only the defects; silent when clean
    python3 tools/puzzle_integrity.py --quotes FILE...  # QUOTE alone, on those files
    python3 tools/puzzle_integrity.py --refused FILE... # those of the files the pre-push would refuse, a line each

Everything else in tools/ checks the work we ADD to a puzzle: validate_annotations.py
grades the annotation, coverage_report.py counts what each series holds. This
checks the puzzle underneath, because a puzzle that arrives wrong stays wrong and
the cost lands later — a duplicate gets annotated twice at full model price and then
shows up twice on the site, and a clue whose enumeration contradicts its own answer
teaches a learner to count wrong. Both are cheap to find mechanically and neither is
findable by eye across the corpus. This is that sweep.

The flags, in the order they matter:

  DUPLICATE two or more files holding the same puzzle. Content-hashed over the
            entries — clue, solution, grid position, length — and over the grid
            dimensions, deliberately NOT over id, number, date, name, setter or
            annotation, because the question is whether the PUZZLE is the same and
            a resend arrives under a fresh number and date. Copies are grouped, so
            three files of one puzzle print as one group of three, not three pairs.
  NEARDUP   two files, of any series or number, sharing at least 80% of their
            clues (clue_index.THRESHOLD): a page that served another puzzle's
            clues under a new id, which DUPLICATE misses when one clue differs.
            Found through an index of clue text -> ids, not pairwise.
            clue_index.REPRINTS lists the pairs known to be a setter's rerun,
            clue_index.SYNDICATED the series that reprint another's puzzles;
            a DUPLICATE group every pair of which is one of those is not flagged.
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
  DATE      a series whose dates do not rise with its numbers: a later number
            dated on or before an earlier one.
  ALTERED   an entry's `alteration` that does not turn the clue's word into
            what the grid holds: each step's op (ALTERATION_OPS) is applied to
            the letters before it, and the last step must end on `solution`.
            The instruction to alter must be printed: in the preamble, or in
            the entry's own clue (the 1930s Listeners say "(reversed)" there).
  SETTER    a byline that is a placeholder ("Unknown"), carries whitespace or a
            copyright notice, or is null in a series whose source prints one
            on every puzzle (series.py `bylined`).
  PROV      a puzzle that does not say where it came from, or says something
            tools/provenance.py does not allow. The one that matters is
            solutions.origin: a grid the setter published is ground truth, a grid
            this repo cold-solved is our guess, and without provenance the two
            are the same 15x15 of capital letters with nothing to tell them
            apart. So the check refuses an origin outside the enum, an
            origin that contradicts the file it sits on (claiming "published"
            over solutions detail that says "model", or "unsolved" over a grid
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
            puzzle, a date in the future or before EARLIEST_YEAR, a date that
            is not a real calendar day written YYYY-MM-DD, a book puzzle whose `year` is not its
            book's `published` year or that holds a date, a `year` on a paper's
            puzzle, no date at all where the source prints one, a blog's brace markup left in a clue,
            a count closing a clue with marks after it that its entry cannot
            have (another entry's text, or a misread count), a
            clue transcribed from a blog with no enumeration or opening with
            what is left of the blog's clue number ("a Bizarre ..."), and — from
            validate_annotations — markup or an undecodable character in the
            puzzle's text, or the legs of a linked answer naming different
            groups.
  QUOTE     an annotation quoting words its clue does not hold: a definition,
            indicator, link word or block's clueFragment that is not a substring
            of the clue text. A clue's text cleaned in place ("(7))" cut off the
            end) without its annotation is the usual way in. Checked on every
            write and, for the puzzle files a commit stages, by
            .githooks/pre-commit (`--quotes FILE...`).
  CURLY     clue text (or an annotation's quote of it) holding a curly quote
            or a backtick: it is stored with ' and " and curled on display
            (tools/quotes.py, quotes.js). Checked on every write, which
            straightens first.
  DASH      clue text spelling a dash between words other than " — ", or an
            ellipsis other than "…" (tools/dashes.py): any clue dashes.normal
            would still change. Checked on every write, which normalises
            first.
  LEAD      an OCR channel's clue text opening with a quote nothing after it
            closes — a speck read as a quote ("'Hasten.") or one with the
            clue's printed number leaked after it ('"5 Covered with a coat') —
            where only a quotation's matched pair may open a clue
            (tools/leading_quote.py): any OCR clue leading_quote.clean would
            still change. Checked on every write, which mends first.
  FILED    a puzzle file that is not where puzzle_paths.file_for puts it:
            puzzles/<series>/<year>/<id>.json, the year its `date`'s. A file in
            the wrong year folder, under a name that is not its id, or left flat
            at puzzles/<id>.json is a copy every reader that finds by id either
            misses or trips over, so every .json under puzzles/ that is not the
            generated index, an authored draft or generated series output is
            checked against the puzzle it holds.

Every check that one file answers on its own is in check_puzzle, and
fetch_puzzle.write_puzzle_file runs it on every write: a fetcher cannot write
what this sweep reports. The write also refuses to blank a clue the file on
disk has words for.

An entry whose solution carries non-letters is reported once, as SHAPE, and then
left out of LENGTH and CROSS — its letter count is not a second defect, it is the
same one counted again.

Puzzles published without answers (Saturday prize crosswords, until the paper
catches up about a week later) are not a defect: LENGTH and CROSS simply have
nothing to weigh for them and skip. Only entries that actually carry a solution
are checked, so an empty grid passes and a half-filled one is still checked as far
as it goes.

The corpus it reads is the puzzle files on disk, puzzle_paths.puzzle_files(),
each read once, the per-file checks spread over every core (parallel.pmap).
A whole-corpus run keeps each file's own findings in tools/row_cache.py, keyed
by its git blob sha and the code _file_row reaches, so only files that moved
(or whose cover date came within reach of today) are viewed again.
puzzles/index.json is neither read nor rebuilt: the nightly reindexes on its own.

Pass puzzle ids or paths to judge just those files — every per-file check, and
the DUPLICATE, NEARDUP and DATE findings that name one of them, weighed against
the rest of the corpus through a cache of each file's clue keys, content hash
and date (~/.cache/cryptic-teacher), keyed by git blob sha so any file whose
content changed is re-read. That is the check for one edit:

    python3 tools/puzzle_integrity.py --quiet cryptic-29000

Every check is on by default and none sits behind a flag.

Exits 1 if anything is flagged, so the nightly can alert on it. It reports and
never writes: a defect here is a fetcher bug or a bad source page, and the fix
belongs in the fetcher or in a re-fetch, not in a repair pass over the files.
"""

import copy
import hashlib
import inspect
import json
import os
import pickle
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import combinations, pairwise, zip_longest
from pathlib import Path

import boilerplate
import dashes
import enumeration
import errata
import groups  # linked answers
import leading_quote
import ocr_clues
import parallel
import provenance
import punctuation
import puzzle_paths
import puzzle_schema
import quotes
import reprints
import series as series_meta
import wordplay
from apply_solution import (
    check_fill,
    check_geometry,
    normalise,
    off_board,
)
from clue_index import (
    MIN_CLUES,
    THRESHOLD,
    ClueIndex,
    clue_keys,
    known_copy,
)
from fetch_puzzle import (
    PER_LIGHT_ENUMERATION,
    PRINTED_COUNT_WRONG,
    count_lights,
    clued,
    corrected_clue,
    duplicated_clues,
    group_orders,
    has_words,
    printed_count_wrong,
    is_bare_letters,
    is_continuation,
    is_grid_answer,
    prints_own_count,
    read_puzzle_file,  # the tests read raw fixtures through this module
    read_puzzle_view,
    source_clue,
)
from groups import entry_id
from reconstruct_grid import grid_of, lights_from_grid, lights_of


# The flags, in the order they are reported. One tuple, read by both the
# per-finding listing and the tally, so a check cannot be added to one and
# missed from the other.
FLAGS = ("LENGTH", "ORDER", "APOSTROPHE", "CROSS", "CELLS", "ALTERED", "GRID", "NUMBER", "DATE", "SETTER", "SHAPE", "PROV", "QUOTE", "CURLY", "DASH", "LEAD", "FILED", "NEARDUP", "REPRINT", "COUNT")

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
    ("cryptic-22813", "15-down: clue says (2,6) = 8, answer holds 10"):
        "SUSTAINING is one word of ten letters and fills the ten cells the grid "
        "gives it, under a clue the paper printed (2,6)",
    ("cryptic-21640",
     "1-across + 17-down + 5-across + 9-across + 14-down: clue says "
     "(6,1,3-4,6,4,2) = 26, answer holds 7 alone or 45 linked"):
        "the Guardian grouped all five lights itself and filled them with "
        "THERE'S A ONE-EYED YELLOW IDOL TO THE NORTH OF KHATMANDU, 45 cells, "
        "under an enumeration it printed only as far as the first 26",
    ("cryptic-22575",
     "10-across + 12-down + 10-across: clue says (6-3,6-4) = 19, answer holds "
     "9 alone or 28 linked"):
        "the perfect figures are THIRTY-SIX TWENTY-FOUR THIRTY-SIX, and the "
        "clue's own \"(and 10 again)\" asks for the repeat; the printed count "
        "stops before it",
    ("cyclops-206", "23-down: clue says (2,5) = 7, answer holds 5"):
        "AT SEA (Labour's second letter, A, + SEAT \"lost\") fills the "
        "five cells the grid gives it; Private Eye's own cyclops206.puz prints "
        "the clue (2,5)",
    ("azed-2636", "40-across: clue says (5) = 5, answer holds 4"):
        "STEE (CASTERED less C-A-R-D; STEEPLY less PLY) fills the four cells "
        "the grid gives it under a preamble saying bracketed numbers are entry "
        "lengths; the Observer's own AZ_2636 PDF prints the clue (5)",
    ("azed-2168", "26-down: clue says (6) = 6, answer holds 5"):
        "LUKIE (LUCKIE less a C, wordplay LUKE round I) fills the five cells "
        "the grid gives it under a preamble saying numbers are entry lengths; "
        "the clue's (6) counts the untreated LUCKIE",
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
    (("cryptic-25430",
      "22-down + 23-down + 12-across: clue says (6,1,5,3,4,2,6,3) = 30, "
      "answer holds 6 alone or 21 linked"),
     "Landor's epitaph repeats NATURE, which the grid holds only once, and ends "
     "in ART — already spent on 8-down + 19-across's ART DECO; no single light "
     "supplies the gap"),
    (("cryptic-24575",
      "9-across + 18-down + 7-down + 16-down + 19-across + 29-across: "
      "clue says (3,4,2,3,8,3,3,9,3,5,3,5) = 51, answer holds 9 alone or 42 "
      "linked"),
     "the White Queen's line repeats JAM three times and adds AND once; the "
     "grid holds JAM only once and has no AND at all, so no light can supply "
     "the repeats"),
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
    (("cryptic-23834",
      "11-across + 27-across: clue says (7,11,13) = 31, answer holds 7 alone or "
      "21 linked"),
     "no light in this grid is blank, spare, or grouped toward the ten missing "
     "letters"),
    # 23,821 is the shape this table exists for, seven times over. Its theme is
    # LEFT, RIGHT and CENTRE, and the paper clues each of the three lights
    # holding them into several answers at once — RIGHT alone finishes MISTER
    # RIGHT, INSIDE RIGHT, RIGHT NOTE and RIGHT AS RAIN. Each of the three
    # lights reads "See" and one number, so it sits in that one leader's group,
    # and these are the answers left over. (RIGHT AS RAIN is no longer one:
    # 22-across leads it from its second light, 23-down named in selfClued.)
    (("cryptic-23731",
      "3-down + 16-down + 4-down + 5-down + 11-across + 21-across: "
      "clue says (2,2,4,4,4,3,4,4,5,4,2,4,4,7) = 53, answer holds 4 alone or 49 "
      "linked"),
     "the Macbeth line repeats WERE, DONE and IT; the grid holds each only once, "
     "so no light can supply the repeats"),
    (("cryptic-23651",
      "8-down + 16-down + 1-across + 4-across + 15-across + 25-across: "
      "clue says (3,3,4,3,3,3,6,6,2,1,4,4,4) = 46, answer holds 13 alone or 40 "
      "linked"),
     "the song lyric repeats SHE WAS; the grid holds it only once, so no light "
     "can supply the repeat"),
    (("cryptic-23541",
      "4-down + 19-down + 8-down: clue says (6,1,5 and 4,2,6,3) = 27, "
      "answer holds 6 alone or 23 linked"),
     "no light in this grid is blank, spare, or grouped toward the four missing "
     "letters"),
    (("cryptic-23299", "12-across: clue says (4,5,2) = 11, answer holds 4"),
     "no light in this grid is blank, spare, or grouped toward the seven "
     "missing letters"),
    (("cryptic-22968",
      "3-down + 21-down: clue says (4,2,3,3,2,3,3,4) = 24, answer holds 4 "
      "alone or 12 linked"),
     "Forsyth's catchphrase says NICE and TO SEE YOU twice each; the grid holds "
     "each once, at 3-down and 21-down, and every other light in it carries its "
     "own clue and its own answer"),
    (("cryptic-22841",
      "8-down + 21-down + 12-down: clue says (4,2,3,2,3,4,6) = 24, answer "
      "holds 4 alone or 18 linked"),
     "the CHANCE that finishes HAVE AN EYE TO THE MAIN CHANCE is 1-down, "
     "already spent on 1-down + 15-across + 2-down's CHANCE WOULD BE A FINE "
     "THING"),
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
    (("cryptic-21625", "12-across: clue says (5,2,4) = 11, answer holds 5"),
     "the same 7-down OF TIME finishes 6-down's DANCE TO THE MUSIC OF TIME, "
     "and 7-down has no clue text to say it continues either answer"),
    (("cryptic-22490",
      "20-down + 4-down + 4-across: clue says (5,6,3,5,8) = 27, answer holds "
      "5 alone or 22 linked"),
     "SEVEN BRIDES FOR SEVEN BROTHERS needs SEVEN twice and the paper gave it "
     "one five-cell light: 20-down holds the first, 4-down BRIDES FOR and "
     "4-across BROTHERS the rest, and the second SEVEN has no light anywhere "
     "in this grid"),
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
     "spent on 21-across + 9-across + 23-down + 11-across's WHAT SORT OF TIME "
     "DO YOU CALL THIS THEN, and a light that starts one answer cannot "
     "continue another"),
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
        (entry_id(e), e.get("number"), e.get("direction"),
         (e.get("position") or {}).get("x"), (e.get("position") or {}).get("y"),
         e.get("length"), enumeration.printed(e["clue"]), e.get("solution"))
        for e in puzzle.get("entries") or []
    )
    dims = puzzle.get("dimensions") or {}
    blob = json.dumps([dims.get("cols"), dims.get("rows"), entries], ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


#: What a blog's clue number leaves when a parser takes the number and not
#: its direction: "a Bizarre eponym ...", "ac. Seaman ...", "dFares ...", or a
#: blogger's typo in the suffix's place, "s Sailor ...". A clue never opens
#: with a lone lowercase letter or two before a capitalised word.
NUMBER_RESIDUE = re.compile(r"^(?:(?:ac|dn|[a-z]{1,2})\.?\s+(?=[A-Z])|[ad](?=[A-Z][a-z]))")


def check_shape(puzzle, today, flags):
    """Defects visible in one entry on its own, plus the puzzle-level ones.

    Returns the entries fit to weigh for LENGTH and CROSS — those whose solution is
    present and is letters only. Everything else has already been reported here."""
    pid = puzzle["id"]
    entries = puzzle.get("entries") or []
    if not entries:
        flags.append(("SHAPE", pid, "no entries at all"))
        return []

    series = series_meta.of(puzzle) or "cryptic"  # a file stores none
    # A book puzzle's `year` is its book's imprint year, read off the registry
    # by the filer; any other value is a book cited under the wrong year. Only
    # a book holds a year: a paper prints the day.
    if series_meta.is_book(series):
        want = series_meta.published(series, puzzle.get("number"))
        if puzzle.get("year") != want:
            flags.append(("SHAPE", pid, f"year {puzzle.get('year')!r}, but its "
                          f"book (tools/data/books.json) was published in {want!r}"))
    elif "year" in puzzle:
        flags.append(("SHAPE", pid, f"has year {puzzle['year']!r}, but only a "
                      f"book puzzle holds a year; a paper prints the day"))
    if "date" in puzzle and series_meta.is_book(series):
        flags.append(("SHAPE", pid, "has a date, but a book's imprint prints "
                      "only a year"))
    elif "date" not in puzzle:
        # Every paper puzzle has a day: a series dated off its neighbours
        # gets a best fit (file_blog_puzzles.fit_undated), and a missing date
        # is a hole in every listing.
        if not series_meta.is_book(series):
            flags.append(("SHAPE", pid, f"no date; a {series} puzzle always "
                          f"has one (file_blog_puzzles.fit_undated)"))
    elif (d := date_of(puzzle)) is None:
        flags.append(("SHAPE", pid, f"date {puzzle['date']!r} is not a calendar "
                      f"day written YYYY-MM-DD"))
    elif d > today + timedelta(days=(lead := series_meta.cover_date_lead(series))):
        # A cover-dated weekly is online days before its issue's date
        # (series.py coverDateLead); anything further ahead is a misread.
        flags.append(("SHAPE", pid, f"dated {d}, which is in the future"
                      + (f" by more than the {lead} days a {series} issue is "
                         f"online before its cover date" if lead else "")))
    elif d.year < EARLIEST_YEAR:
        flags.append(("SHAPE", pid, f"dated {d}, before cryptics existed"))

    # A clue marked clue.missing is forgiven one at a time, because a setter who
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
    if not clued(entries):
        flags.append(("SHAPE", pid, f"all {len(entries)} clues are blank"))

    from_blog = (puzzle.get("source") or {}).get("retrievedFrom") == "blog"
    seen, checkable = set(), []
    by_id = {entry_id(e): e for e in entries}
    for e in entries:
        eid = entry_id(e)
        if eid in seen:
            flags.append(("SHAPE", pid, f"entry id {eid} appears twice"))
        seen.add(eid)

        # A clue is its words. has_words is the one definition of "the paper
        # printed nothing here" — the same rule fetch_puzzle.convert() uses to
        # set clue.missing at fetch time — so this reads the words off the same
        # test rather than reimplementing a stripped-enumeration check that can
        # drift from it: cyclops-309's 17-across is "(see 3dn.)", a bare
        # cross-reference wholly inside one parenthesis and a whole clue by
        # has_words' own rule, which stripping the enumeration would empty.
        #
        # Unless the paper printed it blank, which setters do as the trick itself:
        # cryptic-30098's 12-across is wordless so that its own number is the only
        # thing left pointing at NOONDAY, and cryptic-29345's 5-down is wordless
        # over (1,6,3,1,4) for I HAVEN'T GOT A CLUE. Both are the joke and must
        # never be filled in or filtered out. fetch_puzzle.convert() settles which
        # is which at fetch time, where the paper's own data is still in front of
        # it, and records the answer as clue.missing — so this reads that field
        # rather than guessing again from the text and reaching a different
        # verdict. An unmarked blank clue is still a defect and still reported.
        clue = e["clue"].get("text", "")
        missing = e["clue"].get("missing", False)
        if not missing and not has_words(clue):
            flags.append(("SHAPE", pid, f"{eid}: clue is blank"))
        # Text that is only a count ("(8)") is an empty clue that looks filled
        # in: it passes a truthiness test and fails has_words. Store it the way
        # a printed-blank clue is stored, as missing with no text.
        if clue.strip() and not has_words(clue):
            flags.append(("SHAPE", pid, f"{eid}: clue text {clue!r} is only an "
                          f"enumeration; store it as clue.missing with no text"))
        # The enumeration has its own key; a writer that left it on the words
        # did not build its clue with enumeration.clue().
        group_total = sum(by_id[g]["length"] for g in e.get("group") or () if g in by_id)
        if enumeration.unsplit(e["clue"], {e.get("length"), group_total}):
            flags.append(("SHAPE", pid, f"{eid}: clue text {clue!r} ends in its "
                          f"enumeration; enumeration.split() it into clue.enumeration"))
        # Marks left after the clue's own count ("(4))", "(7)!") are a feed's
        # or a blog's markup; split() cuts them with it.
        elif enumeration.stray(e["clue"], {e.get("length"), group_total}):
            flags.append(("SHAPE", pid, f"{eid}: clue text {clue!r} has stray "
                          f"marks after its enumeration; enumeration.split() "
                          f"it into clue.enumeration"))
        # A count the source printed that this entry cannot have: the text is
        # another entry's or the count was misread. It is the evidence of
        # which, so it is never cut; the clue is re-read from its source.
        elif (printed := enumeration.disagrees(e["clue"], {e.get("length"), group_total})):
            flags.append(("SHAPE", pid, (f"{eid}: clue text {clue!r} prints "
                                         f"({printed}), which is not this entry's "
                                         f"{e.get('length')} letters; re-read it "
                                         f"from the source")))
        # A letter left stuck to the clue's last mark ("gateau?d") is a source's
        # stray character: no clue prints a letter directly after "?" or "!".
        if re.search(r"[?!][A-Za-z]{1,2}$", clue):
            flags.append(("SHAPE", pid, f"{eid}: clue {clue!r} ends in a stray "
                          f"letter fused to its last mark"))
        # Braces are a blogger's markup for a deletion or a hidden word, and no
        # paper prints one in a clue.
        if "{" in clue or "}" in clue:
            flags.append(("SHAPE", pid, f"{eid}: clue {clue!r} keeps a blog's "
                          f"brace markup; a clue line keeps the letters and "
                          f"loses only the braces"))
        if from_blog and NUMBER_RESIDUE.match(clue):
            flags.append(("SHAPE", pid, f"{eid}: clue {clue!r} opens with what is "
                          f"left of the blog's clue number; strip it, and check "
                          f"the parser did not also eat a leading \"A\""))
        # A blogger copying a clue can leave its count off, and the count is
        # then the answer's word lengths. A paper's own feed prints what it
        # printed, so only a transcribed clue is held to this; a count in
        # words ("(5, two words)") is a count, kept in the text as printed.
        if (from_blog and has_words(clue) and not missing
                and not is_continuation(clue) and "enumeration" not in e["clue"]
                and not enumeration.worded(clue)):
            flags.append(("SHAPE", pid, f"{eid}: clue {clue!r}, transcribed from "
                          f"a blog, has no enumeration"))

        solution = e.get("solution")
        if not solution:
            continue
        # One rule, spelled in the fetcher: a solution is A-Z and nothing else.
        # convert() stores a puzzle unsolved rather than write anything that
        # fails it — a page serving a masked answer ("T?S?R", Guardian cryptic
        # 28,691 3-down) — so what this catches came from a fetcher that does
        # not go through convert().
        if not is_grid_answer(solution, puzzle):
            flags.append(("SHAPE", pid, f"{eid}: solution {solution!r} is not bare "
                          + ("digits" if puzzle.get("numeric") is True else "letters")))
            continue
        checkable.append(e)
    return checkable


def leads_by_pointers(group, by_id, lead=None):
    """Is every light of `group` but its leader `lead` (default its first) a
    pointer ("See 19"), or the leader again? Such a group is linked by what its
    legs print, so its leader's count may be its own light's (check_length)."""
    lead = lead or group[0]
    legs = [g for g in group if g != lead]
    return bool(legs) and all(
        g in by_id and is_continuation((by_id[g].get("clue") or {}).get("text", ""))
        for g in legs)


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
    such as a clue promising 23 letters over a group the Guardian's own data
    truncated to 15."""
    pid = puzzle["id"]
    by_id = {entry_id(e): e for e in puzzle.get("entries") or []}
    group_of = groups.group_of(puzzle.get("entries") or [])
    for e in checkable:
        eid, solution = entry_id(e), e["solution"]
        if len(solution) != e.get("length"):
            flags.append(("LENGTH", pid, (f"{eid}: {solution} is {len(solution)} letters, "
                                          f"grid wants {e.get('length')}")))
            continue

        # A continuation leg ("See 23") carries no count of its own; its length
        # is stated once, on the leg that holds the clue.
        # A count the paper printed wrong is measured as intended: the row in
        # fetch_puzzle.PRINTED_COUNT_WRONG is the finding, held by
        # check_printed_counts.
        printed = e["clue"].get("enumeration")
        counts = enumeration.counts(printed_count_wrong(pid, eid, printed) or printed)
        if not counts:
            continue
        group = group_of.get(eid) or [eid]
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
        per_light = (series_meta.of(puzzle) in PER_LIGHT_ENUMERATION
                     or prints_own_count(e))
        # A counted continuation inside a linked answer is not measured at all.
        # Only the leading clue enumerates the answer; a leg's count describes
        # lights, and which lights depends on markup this file does not see —
        # the Guardian's pre-2015 pairs put a chain's middle leg in a sub-group
        # of its own, so "See 26 (7,8)" on cryptic-22249's 17-across counts that
        # leg plus 20-across, neither its own seven cells nor the answer's 31.
        # Measuring it against either reports the head's correct enumeration as
        # a defect on the leg. The head is still checked, so nothing goes unread.
        if len(group) > 1 and is_continuation(e["clue"].get("text", "")):
            continue
        # A leading clue may print its own light's count, in any paper, when
        # every other light of its group is a bare pointer at it. The Guardian
        # did this through about 1999-2005 (cryptic-21704's 19-across WOOD
        # "(4)" over WOOD SHED, 13-across "See 19"), and the Telegraph still
        # does (telegraph-30039's 6-down PLATE "(5)", 20-across "See 6 Down").
        # The pointers are what make the group, so the count is not needed as
        # evidence for it; a group whose other legs carry clues of their own
        # is still held to the whole answer's count.
        per_light = per_light or (e.get("group") == group and leads_by_pointers(group, by_id, eid))
        if sum(counts) == held or (len(group) > 1 and per_light
                                   and sum(counts) == len(solution)):
            continue
        # Two counts in one bracket, "(6;4,6)": a themed Genius prints the clue's
        # answer and then what the grid holds (genius-38, refused 2026-10-13
        # as 16 over 10). Either side measured alone is the count.
        enum = e["clue"].get("enumeration") or ""
        if ";" in enum and any(
                (side := sum(enumeration.counts(part))) == held
                or (len(group) > 1 and per_light and side == len(solution))
                for part in enum.split(";")):
            continue
        # An altered entry's count may be the clue's own word's, not the grid's.
        if len(group) == 1 and e.get("alteration") and sum(counts) == len(
                _alpha(e["alteration"].get("from"))):
            continue
        where = eid if len(group) == 1 else " + ".join(group)
        holds = f"{held}" if len(group) == 1 else f"{len(solution)} alone or {held} linked"
        finding = (f"{where}: clue says ({e['clue']['enumeration']}) = "
                   f"{sum(counts)}, answer holds {holds}")
        if (pid, finding) in PUBLISHED_WRONG or (pid, finding) in UNLINKED_IN_SOURCE:
            continue
        flags.append(("LENGTH", pid, finding))



def apostrophes(enum):
    """The letter positions an enumeration prints an apostrophe after:
    "6,1'8" -> [7], "3-1'4-5" -> [4]."""
    out, pos = [], 0
    for count, marks in re.findall(r"(\d+)(\D*)", enum or ""):
        pos += int(count)
        if "'" in marks:
            out.append(pos)
    return out


def check_unsolved_counts(puzzle, flags):
    """A light with no answer yet, alone in no linked group, against its own
    count: the printed enumeration is the one length statement it holds
    besides its cells, and check_length weighs only solved lights. Without
    this a misread count on an unsolved puzzle (Cyclops No 30's 22-down read
    "(6)" over five cells) writes as cleanly as the page itself, and a
    SOURCE_LIGHT_WRONG row putting it right has nothing to refuse. A
    continuation prints no count of its own, and a "(6;4,6)" passes when
    either side is the light's. Only a paper that counts each light
    (perLightEnumeration): elsewhere a count may be the answer's before an
    alteration the preamble gives (Azed's specials, the Genius), which no
    unsolved light can be measured against."""
    pid = puzzle.get("id")
    if series_meta.of(puzzle) not in PER_LIGHT_ENUMERATION:
        return
    entries = puzzle.get("entries") or []
    group_of = groups.group_of(entries)
    for e in entries:
        eid, length = entry_id(e), e.get("length")
        if e.get("solution") or not isinstance(length, int):
            continue
        if len(group_of.get(eid) or [eid]) > 1 or e.get("alteration"):
            continue
        clue = e.get("clue") or {}
        if is_continuation(clue.get("text", "")):
            continue
        printed = clue.get("enumeration")
        enum = printed_count_wrong(pid, eid, printed) or printed or ""
        if not enumeration.counts(enum):
            continue
        if any(sum(enumeration.counts(side)) == length for side in enum.split(";")):
            continue
        finding = (f"{eid}: clue says ({printed}) = {sum(enumeration.counts(enum))}, "
                   f"its light has {length} cells")
        if (pid, finding) in PUBLISHED_WRONG or (pid, finding) in UNLINKED_IN_SOURCE:
            continue
        flags.append(("LENGTH", pid, finding))


def check_apostrophes(puzzle, flags):
    """An apostrophe in a clue's enumeration and an "'" mark in its lights'
    separators, one for one. "6,1'8" over CHARGEDAFFAIRES is the separators
    [{"at": 6, "mark": ","}, {"at": 7, "mark": "'"}]: a "," at 7 is a word
    break the paper does not print, and the answer check then demands one.
    On a linked clue the positions run through the group in order, as
    fetch_puzzle.separators() places them; a count that is neither the light's
    nor the group's is check_length's finding, not this one's."""
    entries = puzzle.get("entries") or []
    by_id = {entry_id(e): e for e in entries}
    group_of = groups.group_of(entries)
    for e in entries:
        eid, enum = entry_id(e), e["clue"].get("enumeration")
        total = sum(enumeration.counts(enum))
        if not total:
            continue
        group = [by_id[g] for g in group_of.get(eid) or [eid] if g in by_id]
        if (group[0] is e or e.get("group")) and total == sum(g["length"] for g in group):
            lights = group
        elif total == e["length"]:
            lights = [e]
        else:
            continue
        want, start = set(), 0
        for at in apostrophes(enum):
            start = 0
            for light in lights:
                if at <= start + light["length"]:
                    want.add((entry_id(light), at - start))
                    break
                start += light["length"]
        have = {(entry_id(light), s["at"]) for light in lights
                for s in light["clue"].get("separators") or [] if s["mark"] == "'"}
        other = {(entry_id(light), s["at"]) for light in lights
                 for s in light["clue"].get("separators") or [] if s["mark"] != "'"}
        if want != have or want & other:
            def spell(pairs):
                return ", ".join(f"{lid} at {at}" for lid, at in sorted(pairs)) or "none"
            flags.append(("APOSTROPHE", puzzle.get("id"), (
                f"{eid}: enumeration ({enum}) prints an apostrophe at {spell(want)}; "
                f"separators mark \"'\" at {spell(have)}"
                + (f" and a break at {spell(want & other)}" if want & other else ""))))


def check_printed_counts(puzzle, flags):
    """Each fetch_puzzle.PRINTED_COUNT_WRONG row of this puzzle against the
    file: the light is there, its enumeration is still the one the row says
    the paper printed, and its answer's separators are the intended count's,
    cut over the lights that count adds up to (mend_printed_counts writes
    them). A row that no longer describes the file is a finding too, so a
    correction cannot outlive its misprint."""
    from fetch_puzzle import separators
    pid = puzzle.get("id")
    entries = puzzle.get("entries") or []
    by_id = {entry_id(e): e for e in entries}
    for (row_pid, eid), (printed, intended, _why) in PRINTED_COUNT_WRONG.items():
        if row_pid != pid:
            continue
        e = by_id.get(eid)
        if e is None or e["clue"].get("enumeration") != printed:
            held = "no such light" if e is None else f"({e['clue'].get('enumeration')})"
            flags.append(("LENGTH", pid, f"{eid}: PRINTED_COUNT_WRONG says the paper "
                          f"printed ({printed}), but the file holds {held}; delete "
                          f"or mend the row"))
            continue
        lights = count_lights(entries, e, intended)
        if not lights:
            flags.append(("LENGTH", pid, f"{eid}: PRINTED_COUNT_WRONG's intended "
                          f"({intended}) adds up to neither the light nor its group"))
            continue
        want = separators(intended, [m["length"] for m in lights])
        have = [m["clue"].get("separators") or [] for m in lights]
        if want != have:
            flags.append(("LENGTH", pid, f"{eid}: printed ({printed}) for "
                          f"({intended}), but its lights' separators are {have}, "
                          f"not {want}; fetch_puzzle.mend_printed_counts writes them"))


def check_group_order(puzzle, flags):
    """A linked answer whose group lists its lights out of word order: see
    fetch_puzzle.group_orders, which write_puzzle_file applies on every write."""
    by_id = {entry_id(e): e for e in puzzle.get("entries") or []}
    for lead, order in group_orders(puzzle).items():
        flags.append(("ORDER", puzzle.get("id"), (
            f"{lead}: group {' + '.join(by_id[lead]['group'])} spells "
            + "".join(by_id[m].get("solution") or "" for m in by_id[lead]["group"])
            + f"; its words are in the order {' + '.join(order)}")))

def check_grid(puzzle, flags):
    """The grid the entries describe, from tools/apply_solution.py — the same
    check that gates a model fill before it is written. It is asked of the whole
    entry list, answered or not, because a light is in the grid whether or not
    anyone has filled it in yet."""
    pid = puzzle["id"]
    dims = puzzle.get("dimensions") or {}
    unforgivable = {off_board(e, dims.get("cols"), dims.get("rows"))
                    for e in puzzle.get("entries") or []} - {None}
    for problem in check_geometry(puzzle):
        if (pid, problem) in PUBLISHED_WRONG and problem not in unforgivable:
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
    fill = {entry_id(e): e["solution"] for e in checkable}
    _, _, problems = check_fill({**puzzle, "entries": checkable}, fill)
    for p in problems:
        # The same guard check_grid and check_length carry. A crossing conflict
        # is as much "the Guardian contradicting itself" as an off-grid light
        # is — cryptic-22482 is one grid's worth of them — and without this the
        # table could hold a key no run could ever reach, which is the one thing
        # test_puzzle_integrity.py fails on.
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


# Strings that stand in for a setter nobody knows. Every reader prints the
# byline verbatim, so one of these reaches a page as "Set by Unknown".
PLACEHOLDER_SETTERS = {"", "unknown", "none", "null", "undefined", "n/a"}


def check_setter(puzzle, flags):
    """The byline is a name as printed, or no setter key when nobody is known.

    A series whose source prints a byline on every puzzle (series.py
    `bylined`) never has a null one: null there is a parser that missed it.
    A puzzle read off a newspaper page is exempt: the print edition is not
    that source, and older papers ran puzzles with no byline (the 1970s FT).
    So is a puzzle the series lists in `unbylined`: no source names its setter.
    And, where the series sets `unbylinedUnsolved`, a puzzle with no post: filed
    unsolved, or solved since by the model ("model"), it has no post to name one,
    and the filer files it only once its page names none."""
    pid, setter = puzzle["id"], puzzle.get("setter")
    series = series_meta.of(puzzle) or "cryptic"  # a file stores none
    if setter is None:
        scanned = provenance.channel_of(
            (puzzle.get("source") or {}).get("acquiredBy")) == "newspaper"
        meta = series_meta.meta(series)
        if (meta.get("bylined") and not series_meta.is_book(series) and not scanned
                and puzzle.get("number") not in meta.get("unbylined", {})
                and not (meta.get("unbylinedUnsolved")
                         and (puzzle.get("solutions") or {}).get("origin") in ("unsolved", "model"))):
            flags.append(("SETTER", pid, f"no setter, but {series} prints a byline "
                          f"on every puzzle"))
        return
    if not isinstance(setter, str) or setter.strip().casefold() in PLACEHOLDER_SETTERS:
        flags.append(("SETTER", pid, f"setter {setter!r} is a placeholder; a puzzle "
                      f"with no known setter has no setter key"))
    elif setter != setter.strip() or "\u00a9" in setter:
        flags.append(("SETTER", pid, f"setter {setter!r} carries more than the "
                      f"name: whitespace or a copyright notice"))


def check_puzzle_text(puzzle, flags):
    """validate_annotations' checks on the puzzle's own text and groups: no
    markup or undecodable character, and each linked answer's group on its
    leader alone. Annotations are left to that validator, which grades them."""
    import validate_annotations  # lazy: it imports this module's fetcher
    bare = {**puzzle, "entries": [{k: v for k, v in e.items() if k != "annotation"}
                                  for e in puzzle.get("entries") or []]}
    errors = []
    validate_annotations.check_no_markup(bare, errors)
    validate_annotations.check_groups(bare, errors)
    # A further linked answer a light starts (alsoLeads) counts its own
    # group: the checks above that read an entry's enumeration see only the
    # light's first answer.
    by_id = {entry_id(e): e for e in bare["entries"]}
    for e in bare["entries"]:
        for k, item in enumerate(e.get("alsoLeads") or []):
            total = sum(enumeration.counts((item.get("clue") or {}).get("enumeration")))
            cells = sum((by_id.get(g) or {}).get("length") or 0 for g in item.get("group") or [])
            if total and total != cells:
                errors.append(f"{entry_id(e)}: alsoLeads[{k}] enumeration "
                              f"({item['clue']['enumeration']}) counts {total} letters, "
                              f"its group {item.get('group')} holds {cells}")
    # A clue entered off the grid (offGrid) crosses nothing: its enumeration
    # is its length, and its answer must be that long.
    for cid, item in groups.off_grid(bare):
        total = sum(enumeration.counts((item.get("clue") or {}).get("enumeration")))
        if not total:
            errors.append(f"{cid}: no enumeration; an answer entered off the grid has no light to count it")
        elif item.get("solution") and len(item["solution"]) != total:
            errors.append(f"{cid}: solution {item['solution']} is {len(item['solution'])} letters, "
                          f"its enumeration ({item['clue']['enumeration']}) counts {total}")
    flags.extend(("SHAPE", puzzle["id"], err) for err in errors)


def entry_letters(puzzle):
    """(x, y) -> the letter the answered entries put there, for every square
    some entry covers ("" where none of its entries is answered)."""
    out = {}
    for e in puzzle.get("entries") or []:
        pos, sol = e.get("position") or {}, e.get("solution") or ""
        if not isinstance(pos.get("x"), int) or not isinstance(pos.get("y"), int):
            continue
        for i in range(e.get("length") or 0):
            cell = (pos["x"] + i, pos["y"]) if e.get("direction") == "across" else (pos["x"], pos["y"] + i)
            letter = sol[i] if len(sol) == e["length"] else ""
            out[cell] = out.get(cell) or letter
    return out


def check_extra_cells(puzzle, flags):
    """The squares that are not entries' own: `unclued` lights and `printed`
    letters. An unclued light lies on the board, one letter per square, no
    square twice, and agrees with every answered entry it crosses; one with
    no solution is unsolved, and only its squares are checked. A printed
    letter sits on a white square, an entry's or an unclued light's, and is
    the solution's letter there."""
    pid = puzzle.get("id")
    cols, rows = puzzle["dimensions"]["cols"], puzzle["dimensions"]["rows"]
    letters = entry_letters(puzzle)
    for n, light in enumerate(puzzle.get("unclued") or [], 1):
        cells = [(c.get("x"), c.get("y")) for c in light.get("cells") or []]
        sol = light.get("solution") or ""
        if "solution" in light and len(sol) != len(cells):
            flags.append(("CELLS", pid, f"unclued light {n}: solution {sol!r} has "
                          f"{len(sol)} letters for {len(cells)} squares"))
        if len(set(cells)) != len(cells):
            flags.append(("CELLS", pid, f"unclued light {n}: lists a square twice"))
        for i, (x, y) in enumerate(cells):
            if not (isinstance(x, int) and isinstance(y, int) and 0 <= x < cols and 0 <= y < rows):
                flags.append(("CELLS", pid, f"unclued light {n}: square ({x}, {y}) "
                              f"is off the {cols}x{rows} board"))
                continue
            mine = sol[i] if i < len(sol) else ""
            theirs = letters.get((x, y))
            if mine and theirs and mine != theirs:
                flags.append(("CELLS", pid, f"unclued light {n}: square ({x}, {y}) "
                              f"is {mine} but the entry crossing it has {theirs}"))
            if (x, y) not in letters or mine:
                letters[(x, y)] = theirs or mine
    for p in puzzle.get("printed") or []:
        x, y, letter = p.get("x"), p.get("y"), p.get("letter")
        if (x, y) not in letters:
            flags.append(("CELLS", pid, f"printed {letter} at ({x}, {y}) is not "
                          f"on a white square"))
        elif letters[(x, y)] and letters[(x, y)] != letter:
            flags.append(("CELLS", pid, f"printed {letter} at ({x}, {y}) but the "
                          f"solution there is {letters[(x, y)]}"))


def _moved(before, after):
    """`after` is `before` with one run of letters cut out and put back elsewhere."""
    n = len(before)
    for i in range(n):
        for j in range(i + 1, n + 1):
            rest, run = before[:i] + before[j:], before[i:j]
            for k in range(len(rest) + 1):
                if k != i and rest[:k] + run + rest[k:] == after:
                    return True
    return False


def _subsequence(short, long):
    it = iter(long)
    return all(ch in it for ch in short)


#: Each op of an entry's alteration: does it turn `before` into `after`? Both A-Z.
#: The one list of ops: the schema's alterationOp enum is checked against it
#: (puzzle_schema.py). An alteration maps letters to letters, one per cell, so a
#: puzzle with multi-letter cells, numerical entries, or a grid altered after
#: the fill (Listener 3975's moved answers, 4554's final change) files its fill
#: before that change, or is not filed.
ALTERATION_OPS = {
    "reversal": lambda before, after: before[::-1] == after != before,
    "anagram": lambda before, after: sorted(before) == sorted(after) and before != after,
    "move": _moved,
    "deletion": lambda before, after: len(after) < len(before) and _subsequence(after, before),
    "insertion": lambda before, after: len(after) > len(before) and _subsequence(before, after),
    "substitution": lambda before, after: len(before) == len(after) and before != after,
}


def check_alterations(puzzle, flags):
    """Each entry's `alteration` turns its `from` into its `solution`, step by step."""
    pid = puzzle.get("id")
    for e in puzzle.get("entries") or []:
        alt = e.get("alteration")
        if not isinstance(alt, dict):
            continue
        where = f"{e.get('number')}-{e.get('direction')}"
        if not (puzzle.get("preamble") or e.get("clue", {}).get("text")):
            flags.append(("ALTERED", pid, (f"{where}: an alteration, but neither a preamble "
                          f"nor the clue is printed to say how the answer is altered")))
        if not e.get("solution"):
            flags.append(("ALTERED", pid, f"{where}: an alteration with no solution to end on"))
            continue
        word = _alpha(alt.get("from"))
        steps = alt.get("steps") or []
        for n, step in enumerate(steps, 1):
            last = n == len(steps)
            if last and "gives" in step:
                flags.append(("ALTERED", pid, (f"{where}: the last step names `gives`; "
                              f"its result is the solution {e['solution']}")))
            if not last and not step.get("gives"):
                flags.append(("ALTERED", pid, (f"{where}: step {n} of {len(steps)} has no "
                              f"`gives`")))
                break
            after = _alpha(e["solution"] if last else step["gives"])
            op = ALTERATION_OPS.get(step.get("op"))
            if op is None or not op(word, after):
                flags.append(("ALTERED", pid, (f"{where}: step {n} {step.get('op')!r} does "
                              f"not turn {word} into {after}")))
                break
            word = after


def _alpha(s):

    return re.sub(r"[^A-Z]", "", unicodedata.normalize("NFD", str(s or "")).upper())


#: A clue that sends the solver to the preamble: "See preamble", "(see the
#: preamble)", "[See special instructions]" (genius-7, 40, 84, 92 and
#: times-15043 print "instructions", which this once missed).
SEE_PREAMBLE = re.compile(r"(?i)\bsee (?:the )?(?:special )?(?:preamble|instructions)\b")


#: A fifteensquared Azed post names a special after its number
#: (".../azed-no-2566-playfair/"); a plain puzzle's slug says "plain" or
#: nothing besides its competition and Christmas tags.
AZED_SPECIAL = re.compile(r"azed-no-?\d+-([a-z-]+?)/?$")
AZED_PLAIN_WORDS = {"plain", "competition", "puzzle", "christmas"}


def special_without_preamble(puzzle):
    """An Azed special filed from its blog post, which never quotes the
    preamble its clues are written against."""
    m = AZED_SPECIAL.search((puzzle.get("source") or {}).get("url") or "")
    return series_meta.of(puzzle) == "azed" and bool(m) and bool(set(m.group(1).split("-")) - AZED_PLAIN_WORDS)


def awaits_preamble(puzzle):
    """Whether the puzzle needs a preamble it does not hold: a clue says
    "see preamble", it is a special filed without one, or an annotation run
    found answers only the preamble defines (`awaitsPreamble`, written by
    tools/await_preamble.py). Such a puzzle stays
    in the corpus (its clues are all it must have) but no annotator is sent
    it: its clues cannot be explained without the preamble. The index row
    carries it as `awaitsPreamble`, which both annotation pickers
    (tools/daily_update.sh, tools/prereset_plan.backlog) read."""
    return not puzzle.get("preamble") and (
        puzzle.get("awaitsPreamble") is True or special_without_preamble(puzzle) or any(
        SEE_PREAMBLE.search((e.get("clue") or {}).get("text") or "")
        for e in puzzle.get("entries") or []))


def check_preamble(puzzle, flags):
    """A preamble holds no erratum and no publishing boilerplate:
    errata.apply and boilerplate.apply take them out on every write, so one
    still there was written past that. `awaitsPreamble` never sits beside
    one: write_puzzle_file drops it when a preamble is filed."""
    if puzzle.get("preamble") and "awaitsPreamble" in puzzle:
        flags.append(("SHAPE", puzzle.get("id"), "awaitsPreamble beside a preamble: the "
                      "preamble it awaited is here (write_puzzle_file drops the flag)"))
    for found in errata.find(puzzle.get("preamble")):
        flags.append(("SHAPE", puzzle.get("id"), f"preamble holds an erratum, not "
                      f"instructions: {found[:120]!r} (tools/errata.py applies it)"))
    for found in boilerplate.find(puzzle.get("preamble")):
        flags.append(("SHAPE", puzzle.get("id"), (f"preamble holds the paper's publishing "
                      f"boilerplate, not instructions: {found[:120]!r} "
                      f"(tools/boilerplate.py strips it)")))


def check_theme_clue(puzzle, flags):
    """`themeClue` names the entry whose clue states the theme (a themed
    puzzle that prints its gimmick in a clue, not a preamble), so it must be
    an entry of this puzzle with clue words."""
    tc = puzzle.get("themeClue")
    if tc is None:
        return
    e = {entry_id(e): e for e in puzzle.get("entries", [])}.get(tc)
    if e is None:
        flags.append(("SHAPE", puzzle.get("id"), f"themeClue {tc!r} is not an entry of "
                      f"this puzzle: it names the clue that states the theme"))
    elif not (e.get("clue") or {}).get("text") or (e.get("clue") or {}).get("missing"):
        flags.append(("SHAPE", puzzle.get("id"), f"themeClue {tc!r} has no clue words "
                      f"to state a theme"))


def check_puzzle(puzzle, today, flags):
    """Every check that one puzzle file answers on its own. audit() runs it on
    the corpus and fetch_puzzle.write_puzzle_file on every write, so a fetcher
    cannot put on disk what this sweep would report."""
    dims = puzzle.get("dimensions") or {}
    if not (isinstance(dims.get("cols"), int) and isinstance(dims.get("rows"), int)):
        flags.append(("SHAPE", puzzle.get("id"), "no dimensions: the grid's "
                      "cols and rows are what every light is placed in"))
        return
    checkable = check_shape(puzzle, today, flags)
    check_setter(puzzle, flags)
    check_provenance(puzzle, flags)
    check_grid(puzzle, flags)
    check_numbering(puzzle, flags)
    check_length(puzzle, checkable, flags)
    check_unsolved_counts(puzzle, flags)
    check_semicolon_counts(puzzle, flags)
    check_group_order(puzzle, flags)
    check_printed_counts(puzzle, flags)
    check_apostrophes(puzzle, flags)
    check_cross(puzzle, checkable, flags)
    check_extra_cells(puzzle, flags)
    check_alterations(puzzle, flags)
    check_puzzle_text(puzzle, flags)
    check_preamble(puzzle, flags)
    check_theme_clue(puzzle, flags)
    check_duplicated_clues(puzzle, flags)
    check_annotation_quotes(puzzle, flags)
    check_curly_quotes(puzzle, flags)
    check_dashes(puzzle, flags)
    check_leading_quotes(puzzle, flags)
    check_reprint(puzzle, flags)


def check_reprint(puzzle, flags):
    """REPRINT: a reprint whose original is identified, filed as a puzzle of
    its own. It is filed as the original, with its own print in the
    original's source.reprintedIn (tools/reprints.py)."""
    original = reprints.original_of(puzzle)
    if original and puzzle["id"] not in reprints.pending():
        flags.append(("REPRINT", puzzle["id"], f"reprints {original}: file it as {original}, "
                      "with this print in its source.reprintedIn (tools/reprints.py)"))


def annotation_quotes(ann):
    """(what, text) for every piece of clue text an annotation quotes."""
    defs = [d for d in ann.get("definitions") or [] if isinstance(d, dict)]
    out = [("definition", d.get("text")) for d in defs]
    # It quotes the clue in its definitions' indicators and its wordplay
    # tree's indicators and leaf words; link words are derived from the clue,
    # so they are in it.
    out += [("indicator", i.get("text")) for d in defs for i in d.get("indicators") or []
            if isinstance(i, dict)]
    todo = [ann["wordplay"]] if isinstance(ann.get("wordplay"), dict) else []
    while todo:
        node = todo.pop()
        out += [("indicator", i.get("text")) for i in node.get("indicators") or [] if isinstance(i, dict)]
        out += [("wordplay words", node.get("words"))] if "op" not in node else []
        todo += [p for p in wordplay.parts_of(node) if isinstance(p, dict)]
    return [(what, t) for what, t in out if isinstance(t, str) and t]


def check_annotation_quotes(puzzle, flags):
    """Every word an annotation quotes is in its clue, so editing a clue's text
    without its annotation is refused on write and at commit (.githooks/pre-commit)."""
    for e in puzzle.get("entries") or []:
        ann = e.get("annotation")
        if not isinstance(ann, dict):
            continue
        clue = (e.get("clue") or {}).get("text", "")
        for what, text in annotation_quotes(ann):
            if text not in clue:
                flags.append(("QUOTE", puzzle.get("id"), f"{entry_id(e)}: {what} {text!r} is not "
                              f"in the clue {clue!r}; edit the annotation with the clue"))


def check_curly_quotes(puzzle, flags):
    """CURLY: clue text holding a curly quote, a backtick or a Unicode ligature
    (fi, fl, ff, ffi, ffl codepoints). It is stored with
    ' and " (tools/quotes.py) and curled on display (quotes.js)."""
    for e, key, text in quotes.curly(puzzle):
        flags.append(("CURLY", puzzle.get("id"), f"{entry_id(e)}: {key} {text!r} holds a curly "
                      "quote, backtick or ligature; clue text is stored straight (quotes.straight)"))


def check_dashes(puzzle, flags):
    """DASH: clue text spelling a dash between words or an ellipsis other
    than the house " \u2014 " and "\u2026", or an annotation quoting the clue
    with them spelt other than the clue does (tools/dashes.py)."""
    for e, text in dashes.unnormal(puzzle):
        flags.append(("DASH", puzzle.get("id"), f"{entry_id(e)}: {text!r} spells a dash or ellipsis "
                      f"other ways; clue text is stored {dashes.normal(text)!r} (dashes.normal)"))
    for e in puzzle.get("entries") or []:
        clue = (e.get("clue") or {}).get("text", "")
        for holder, key in dashes.stale(e):
            flags.append(("DASH", puzzle.get("id"), f"{entry_id(e)}: annotation quotes {holder[key]!r} "
                          f"for the clue's {dashes.quote(holder[key], clue)!r}; quoted clue words "
                          "spell a dash or ellipsis as the clue does (dashes.quote)"))


def _lead_finding(e, text, name=None):
    return (f"{name or entry_id(e)}: {text!r} opens with a quote nothing closes; an OCR clue is "
            f"stored {leading_quote.clean(text)!r} (leading_quote.clean)")


def _light_name(record, light):
    """A clues-only `light` named by its list and place in it ("across light
    3", "unplaced clue 3"): such a record holds no clue numbers, and a
    jigsaw's clues no direction either."""
    for d in ("across", "down", "unplaced"):
        for i, l in enumerate((record.get("clues") or {}).get(d) or (), 1):
            if l is light:
                return f"{d} {'clue' if d == 'unplaced' else 'light'} {i}"
    return "a light"


def check_leading_quotes(puzzle, flags):
    """LEAD: an OCR clue opening with a stray quote, or a quote and a leaked
    clue number, that leading_quote.clean would still mend."""
    for e, text in leading_quote.unclean(puzzle):
        flags.append(("LEAD", puzzle.get("id"), _lead_finding(e, text)))


def check_semicolon_counts(puzzle, flags):
    """COUNT: an enumeration holding a ";" between counts that fill its light
    or its linked group (enumeration.comma_misread): a scan's "," read with
    a speck, which draws no word break. A ";" whose counts fill neither is
    the paper's own (two answers' counts in one bracket) and stands. Only
    an OCR channel's file: a publisher's feed prints the paper's own ";"
    (the Guardian's two-answer clues over linked lights, cryptic-26974)."""
    if (puzzle.get("source") or {}).get("retrievedFrom") not in provenance.OCR_CHANNELS:
        return
    entries = puzzle.get("entries") or []
    by_id = {entry_id(e): e for e in entries}
    group_of = groups.group_of(entries)
    for e in entries:
        clue = e.get("clue") if isinstance(e.get("clue"), dict) else {}
        eid = entry_id(e)
        totals = {e.get("length"), sum((by_id.get(i) or {}).get("length") or 0 for i in group_of.get(eid) or [eid])}
        if any(enumeration.semicolon_misread(clue, t) for t in totals if t):
            flags.append(("COUNT", puzzle.get("id"), (f"{eid}: enumeration ({clue['enumeration']}) "
                          f"fills the light with a \";\", a misread \",\": build it through "
                          f"enumeration.comma_misread")))


def check_new_bleed(old, new, flags):
    """SHAPE: a clue an OCR channel's write brings that holds another clue's
    or the page's text (ocr_clues.bled: the previous clue and its count run
    in ahead, "Division (6;3). Covered inside"). A clue the held file
    already had as it is stays for the re-read to mend."""
    if (new.get("source") or {}).get("retrievedFrom") not in provenance.OCR_CHANNELS:
        return
    was = {entry_id(e): (e.get("clue") or {}).get("text") for e in (old or {}).get("entries") or []
           if isinstance(e.get("clue"), dict)}
    for e in new.get("entries") or []:
        clue = e.get("clue") if isinstance(e.get("clue"), dict) else {}
        text = clue.get("text")
        if text and was.get(entry_id(e)) != text and (why := ocr_clues.bled(text, clue.get("asPrinted") or ())):
            flags.append(("SHAPE", new.get("id"), (f"{entry_id(e)}: {why}; cut it (ocr_clues.run_in) "
                          f"or file the clue blank")))


def check_new_spaces(old, new, flags):
    """SHAPE: a clue an OCR channel's write brings that holds a run of
    spaces ("Toe  so"), a reader's join the print never has; build the
    clue through enumeration.clue, which cuts it to one. A clue the held
    file already had as it is stays for the re-read (edition_commit.spaced
    makes it due). Publisher feeds are collapsed by their filers instead."""
    if (new.get("source") or {}).get("retrievedFrom") not in provenance.OCR_CHANNELS:
        return
    was = {entry_id(e): (e.get("clue") or {}).get("text") for e in (old or {}).get("entries") or []
           if isinstance(e.get("clue"), dict)}
    for e in new.get("entries") or []:
        text = (e.get("clue") if isinstance(e.get("clue"), dict) else {}).get("text")
        if text and "  " in text and was.get(entry_id(e)) != text:
            flags.append(("SHAPE", new.get("id"), (f"{entry_id(e)}: clue {text!r} holds a run of "
                          f"spaces; cut it to one (enumeration.collapse_spaces)")))


def check_new_punctuation(old, new, flags):
    """SHAPE: a clue an OCR channel's write brings that breaks a rule of
    English punctuation no print breaks (punctuation.faults: "by.clever",
    "''" for a double quote, ",.", "word , word"). The write path makes the
    certain mends itself (punctuation.mend_puzzle); what is left is a
    reader's mark only a re-read mends. A clue the held file already had as
    it is stays for that re-read (edition_commit.strayed makes it due)."""
    if (new.get("source") or {}).get("retrievedFrom") not in provenance.OCR_CHANNELS:
        return
    was = {entry_id(e): (e.get("clue") or {}).get("text") for e in (old or {}).get("entries") or []
           if isinstance(e.get("clue"), dict)}
    for e in new.get("entries") or []:
        text = (e.get("clue") if isinstance(e.get("clue"), dict) else {}).get("text")
        if text and was.get(entry_id(e)) != text and (found := punctuation.faults(text)):
            flags.append(("SHAPE", new.get("id"), (f"{entry_id(e)}: clue {text!r} holds "
                          + "; ".join(f"{why} ({snip!r})" for why, snip in found)
                          + ": file the reading that prints it right (punctuation.faults)")))


def check_duplicated_clues(puzzle, flags):
    """An OCR-read puzzle (provenance.OCR_CHANNELS) holds no clue on two
    lights of one list (fetch_puzzle.duplicated_clues, `one_list`), where it
    is a misread that lost the others' clues, unless
    fetch_puzzle.SOURCE_CLUE_WRONG prints one of them; one clue under ACROSS
    and DOWN is printed in each list. Elsewhere each light's clue is served
    as text, and a clue on two lights is the setter's."""
    if (puzzle.get("source") or {}).get("retrievedFrom") not in provenance.OCR_CHANNELS:
        return
    for ids in duplicated_clues(puzzle.get("entries") or [], one_list=True):
        if any(corrected_clue(puzzle.get("id"), i) is not None for i in ids):
            continue
        flags.append(("SHAPE", puzzle.get("id"), f"{', '.join(ids)}: one clue read onto "
                      f"{len(ids)} lights, so the others' clues were lost: file it on the light "
                      f"it fits and the rest blank (ocr_clues.one_light_each), or the printed "
                      f"clue in tools/data/source_clue_wrong.json"))


def check_rewrite(old, new, flags):
    """What writing `new` over the file's `old` may not lose: a clue's words,
    and the puzzle itself (most of its answers gone is another puzzle).
    A re-fetch of a page that serves the grid without the text (the Guardian's
    2005-08 prizes) would otherwise undo a recovery; see
    fetch_puzzle.carry_recovered_clues."""
    # A clue on two lights of an OCR reading was lost on all but one, and one
    # holding another clue's or the page's text (ocr_clues.bled) is not its
    # own, and one with a doubled word or a stray letter (ocr_clues.stray)
    # is not the print's: blanking any of them loses nothing.
    lost = {i for ids in duplicated_clues(old.get("entries") or []) for i in ids} \
        | {entry_id(e) for e in clued(old.get("entries") or [])
           if ocr_clues.bled(e["clue"]["text"]) or ocr_clues.stray(e["clue"]["text"])} \
        if (old.get("source") or {}).get("retrievedFrom") in provenance.OCR_CHANNELS else set()
    # A placeholder the source serves where it holds no clue (quiptic-71's
    # "?????"), which SOURCE_CLUE_WRONG prints as nothing, loses nothing either.
    lost |= {entry_id(e) for e in clued(old.get("entries") or [])
             if not source_clue(old.get("id"), entry_id(e), e["clue"]["text"]).strip()}
    was ={entry_id(e): e["clue"]["text"] for e in clued(old.get("entries") or []) if entry_id(e) not in lost}
    for e in new.get("entries") or []:
        if has_words(was.get(entry_id(e))) and not has_words(e["clue"].get("text", "")):
            flags.append(("SHAPE", new["id"], f"{entry_id(e)}: would replace the clue "
                          f"{was[entry_id(e)]!r} with a blank one; carry it across "
                          f"(fetch_puzzle.merge_annotations)"))
    # A light the new file still has but leaves blank is an answer withdrawn
    # (a model's fill over a blog write-up taken back), not another puzzle's.
    blank = {entry_id(e) for e in new.get("entries") or [] if not e.get("solution")}
    held = [e.get("solution") for e in old.get("entries") or []
            if e.get("solution") and entry_id(e) not in blank]
    now = {e.get("solution") for e in new.get("entries") or [] if e.get("solution")}
    kept = sum(a in now for a in held)
    if len(held) >= 4 and len(now) >= 4 and kept * 2 < len(held):
        flags.append(("FILED", new["id"], f"would replace the held puzzle with another: "
                      f"{kept} of its {len(held)} answers kept; a source under a misprinted "
                      f"number is not this puzzle"))


class RefusedWrite(ValueError):
    """A write refused; `.flags` is the structured [(kind, puzzle id, text)]."""

    def __init__(self, message, flags):
        super().__init__(message)
        self.flags = flags


def annotated_for(ann, word):
    """Whether annotation `ann` explains `word` (letters only). It stores no
    answer: by its `spelling`, or else by its wordplay tree giving `word`."""
    if not isinstance(ann, dict):
        return False
    if ann.get("spelling"):
        return re.sub(r"[^A-Z]", "", ann["spelling"].upper()) == word
    if not isinstance(ann.get("wordplay"), dict):
        return False
    try:
        wordplay.evaluate(copy.deepcopy(ann["wordplay"]), word)
    except (wordplay.WordplayError, KeyError, TypeError, ValueError, StopIteration):
        return False
    return True


def check_key_grades_model(old, new, flags):
    """A key that replaces a model's solve grades it: each light it overturns is
    in tools/data/blind_misses.json and has lost the hint written for the old
    word (fetch_puzzle.grade_model_fill does both). listener-3's archive key
    (listener_puzzles.graded_by_key) overturned three answers and recorded
    none, so the nightly miss diagnosis never saw them. Any road that files a
    key over a cold solve now has to grade it, or the write is refused."""
    if "model" not in provenance.solution_detail(old) or "model" in provenance.solution_detail(new):
        return
    import validate_annotations  # lazy: it imports this module's fetcher
    recorded = validate_annotations.blind_misses(new.get("id"))
    have = {entry_id(e): e for e in new.get("entries") or []}
    for eid, mine in provenance.model_answers(old).items():
        e = have.get(eid)
        if not mine or not e or not e.get("solution") or e["solution"] == mine:
            continue
        stale = annotated_for(e.get("annotation"), mine)
        if eid not in recorded or stale:
            flags.append(("UNGRADED", new["id"], f"{eid}: the key says {e['solution']} where the "
                          f"model's solve said {mine}; grade it through fetch_puzzle.grade_model_fill "
                          f"(records the miss, drops the old hint) before writing"))


def refuse_bad_write(puzzle, old=None):
    """Raise RefusedWrite (a ValueError) naming every finding `puzzle` would bring to disk."""
    flags = []
    check_puzzle(puzzle, newest_today(), flags)
    # No setter never holds a puzzle (Paul's standing rule: never hold a puzzle
    # for its form): a write refuses only one that drops a byline the held file
    # has, which is a reader that broke. The audit (and so the pre-push) passes
    # a Genius with no post, solved or not (check_setter); genius-26 committed
    # and could not push while it flagged a model-solved one (10-13).
    # Seen 2026-10-13: Genius 43-109, filed unsolved with none (series.py
    # unbylinedUnsolved), refused on SETTER the moment the backfill solved them.
    if puzzle.get("setter") is None and not (old or {}).get("setter"):
        flags = [f for f in flags if not (f[0] == "SETTER" and f[2].startswith("no setter"))]
    elif puzzle.get("setter") is None and not any(f[0] == "SETTER" for f in flags):
        flags.append(("SETTER", puzzle.get("id"), "no setter, but the held file has "
                      f"{old['setter']!r}: a write never drops a byline"))
    flags += [("SCHEMA", puzzle.get("id"), p) for p in puzzle_schema.validate(puzzle)]
    if old is not None:
        check_rewrite(old, puzzle, flags)
        check_key_grades_model(old, puzzle, flags)
    check_new_bleed(old, puzzle, flags)
    check_new_spaces(old, puzzle, flags)
    check_new_punctuation(old, puzzle, flags)
    if flags:
        raise RefusedWrite(f"refusing to write {puzzle['id']}: "
                           + "; ".join(f"{flag} {what}" for flag, _, what in flags), flags)


def refuse_bad_clues_only(record):
    """Raise RefusedWrite unless `record` is a whole clues-only puzzle
    (tools/clues_only.py): its schema ($defs/cluesOnly has no number, position
    or answer to half-fill), a builder for its filer and grid kind, and an id
    not already filed with a grid. A puzzle is held in one state at a time: in
    puzzles/ with its grid, or in clues_only/ with its clues and nothing else."""
    import clues_only
    import puzzle_paths
    pid = record.get("id")
    flags = [("SCHEMA", pid, p) for p in puzzle_schema.validate_clues_only(record)]
    flags += [("LEAD", pid, _lead_finding(l, t, _light_name(record, l)))
              for l, t in leading_quote.unclean_clues_only(record)]
    import validate_annotations  # lazy: it imports this module's fetcher
    markup = []
    validate_annotations.text_errors(record, markup)
    flags += [("SHAPE", pid, err) for err in markup]
    by =(record.get("source") or {}).get("acquiredBy")
    # A jigsaw is held as data: its clues are the must-have, and no builder
    # fits a word list into a grid yet (clues_only.builder).
    if clues_only.builder(record) is None and not record.get("cluesUnplaced"):
        flags.append(("STATE", pid, (f"no builder in clues_only.BUILDERS for a "
                                     f"{clues_only.grid_kind(record)} grid filed by {by}, "
                                     f"so its answers could never become a grid puzzle")))
    if pid and puzzle_paths.find(pid):
        flags.append(("STATE", pid, "already filed with its grid in puzzles/"))
    if flags:
        raise RefusedWrite(f"refusing to write clues-only {pid}: "
                           + "; ".join(f"{flag} {what}" for flag, _, what in flags), flags)


ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def newest_today():
    """The latest calendar day anywhere on Earth (UTC+14). A paper prints its
    own local day, so a UK Sunday puzzle is out while UTC is still Saturday.
    Seen 2026-10-24 23:32 UTC: everyman-4175, dated 10-25, refused as future."""
    return (datetime.now(timezone.utc) + timedelta(hours=14)).date()


def date_of(puzzle):
    """series.puzzle_day() of a paper puzzle whose `date` is a real calendar
    day written YYYY-MM-DD; None for anything else (an int, "2024-02-30",
    "20240101"), which check_puzzle flags."""
    date = puzzle.get("date")
    if not isinstance(date, str) or not ISO_DAY.fullmatch(date):
        return None
    try:
        return series_meta.puzzle_day(puzzle)
    except ValueError:
        return None


def check_dates(held, flags):
    """A series' dates rise with its numbers: one puzzle per issue, numbered in
    the order they are printed. A later number dated on or before an earlier
    one is a date read off the wrong day. A series that renumbered
    (series.py renumberedBelow) is checked one numbering at a time. `held` is (series, number, day, id)
    per puzzle, the day a datetime.date or None."""
    by_series = defaultdict(list)
    for series, number, date, pid in held:
        if not series_meta.is_book(series):
            restart = series_meta.meta(series).get("renumberedBelow")
            run = (series, bool(restart and number < restart))
            by_series[run].append((number, date, pid))
    for (series, _), rows in by_series.items():
        rows.sort()
        dated = [(n, d, pid) for n, d, pid in rows if d is not None]
        for (a, da, _), (_b, db, pid) in pairwise(dated):
            if db <= da:
                finding = f"dated {db}, not after {series}-{a}'s {da}"
                if (pid, finding) not in PUBLISHED_WRONG:
                    flags.append(("DATE", pid, finding))


def _numbering(series, number):
    """Which numbering run of `series` `number` is in (check_dates' split)."""
    restart = series_meta.meta(series).get("renumberedBelow")
    return bool(restart and number < restart)


def filed_neighbours(puzzle):
    """((number, day, id) or None, same): the nearest puzzles filed under
    puzzle_paths.PUZZLE_DIR below and above `puzzle`'s number, in its
    numbering run, that carry a date. Names only are listed; two files read."""
    try:
        series, number = series_meta.parse_id(puzzle.get("id"))
    except (AssertionError, ValueError):
        return None, None
    folder = puzzle_paths.PUZZLE_DIR / str(series)
    if not series or series_meta.is_book(series) or not folder.is_dir():
        return None, None
    run, prefix = _numbering(series, number), f"{series}-"
    below, above = [], []
    for year in folder.iterdir():
        if not year.is_dir():
            continue
        for name in os.listdir(year):
            tail = name[len(prefix):-5] if name.startswith(prefix) and name.endswith(".json") else ""
            if tail.isdigit() and (n := int(tail)) != number and _numbering(series, n) == run:
                (below if n < number else above).append((n, year / name))

    def nearest(candidates):
        for n, path in candidates:
            try:
                day = date_of(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
            if day is not None:
                return n, day, f"{series}-{n}"
        return None
    return nearest(sorted(below, reverse=True)), nearest(sorted(above))


def check_new_date(old, new, flags):
    """DATE at write time, so no writer can file what check_dates reports.
    A puzzle whose date it brings (new, or moved) must fall after the filed
    puzzle numbered below it and before the one numbered above. And a reading
    off a scan may not move a filed puzzle to a later issue's date: a later
    issue carrying the same puzzle (a prize reprinted with its solution, or
    another day's pages bound into the scan, as archive.org's Financial Times
    items are) is not when it was printed. Seen 2026-10-11: ftcryptic-8021
    re-filed off the 12 December 1992 scan, 8425/8427/8948/9304/9306 filed
    under the dates of scans that also hold their real day's puzzle."""
    day = date_of(new)
    if day is None:
        return
    pid = new.get("id")
    was = date_of(old) if old is not None else None
    if was == day:
        return
    url = (new.get("source") or {}).get("url")
    if (was is not None and day > was and url != ((old or {}).get("source") or {}).get("url")
            and (new.get("source") or {}).get("retrievedFrom") in provenance.OCR_CHANNELS):
        flags.append(("DATE", pid, f"would move {pid} from {was} to {day}: a later issue "
                      "printing it again is not its date"))
    below, above = filed_neighbours(new)
    if below and day <= below[1]:
        finding = f"dated {day}, not after {below[2]}'s {below[1]}"
        if (pid, finding) not in PUBLISHED_WRONG:
            flags.append(("DATE", pid, finding))
    if above and day >= above[1]:
        finding = f"dated {day}, not before {above[2]}'s {above[1]}"
        if (pid, finding) not in PUBLISHED_WRONG:
            flags.append(("DATE", pid, finding))


def refuse_misdated_write(puzzle, old=None):
    """Raise RefusedWrite when writing `puzzle` into the corpus would break its
    series' number/date order (check_new_date). Only for the real corpus: it
    reads the neighbours filed beside it."""
    flags = []
    check_new_date(old, puzzle, flags)
    if flags:
        raise RefusedWrite(f"refusing to write {puzzle['id']}: "
                           + "; ".join(f"{flag} {what}" for flag, _, what in flags), flags)


def _rel(path):
    try:
        return str(path.relative_to(puzzle_paths.PUZZLE_DIR.parent))
    except ValueError:
        return str(path)


def check_filed(path, puzzle, flags):
    """FILED: `path` is not file_for(the puzzle it holds)."""
    try:
        want = puzzle_paths.file_for(puzzle)
    except SystemExit as err:
        flags.append(("FILED", puzzle.get("id"), f"{_rel(path)}: {err}"))
        return
    if path != want:
        flags.append(("FILED", puzzle["id"], f"{_rel(path)} belongs at {_rel(want)}"))


def check_strays(published, flags, files):
    """FILED for every .json under puzzles/ that puzzle_files() does not walk
    — a flat puzzles/<id>.json, one loose in a series folder — other than the
    generated index and series output and the authored drafts."""
    root = puzzle_paths.PUZZLE_DIR
    prefix = root.relative_to(puzzle_paths.PUZZLE_DIR.parent).as_posix() + "/"
    for name in sorted(files, key=lambda n: n.split("/")):
        rel = name[len(prefix):].split("/")
        if name in published or name == prefix + "index.json" or rel[0] in ("series", "authored"):
            continue
        path = puzzle_paths.PUZZLE_DIR.parent / name
        try:
            puzzle = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            flags.append(("FILED", path.stem, f"{_rel(path)}: not a puzzle file ({err})"))
            continue
        if not isinstance(puzzle, dict) or "id" not in puzzle:
            flags.append(("FILED", path.stem, f"{_rel(path)}: not a puzzle file"))
            continue
        check_filed(path, puzzle, flags)


_TODAY = None


def _one_file(path):
    """Everything audit() needs from one file, for parallel.pmap: its own
    flags, and what the cross-file checks weigh it by."""
    return _findings(path, read_puzzle_view(path))


def _findings(path, puzzle):
    """_one_file's answer for the file at `path` holding the viewed `puzzle`."""
    flags = []
    check_filed(path, puzzle, flags)
    pid = puzzle["id"]
    held = (series_meta.of(puzzle) or "cryptic", puzzle["number"], date_of(puzzle), pid)
    row = (pid, content_hash(puzzle), clue_keys(puzzle), held)
    check_puzzle(puzzle, _TODAY, flags)
    return flags, row


def _file_row(path):
    """_one_file(path) plus the first day the file's findings no longer
    depend on: check_shape's future-date finding is the only one that reads
    today, and fires while today < date - the series' cover-date lead. None
    for a file with no calendar date."""
    puzzle = read_puzzle_view(path)
    d = date_of(puzzle)
    horizon = None if d is None else d - timedelta(
        days=series_meta.cover_date_lead(series_meta.of(puzzle) or "cryptic"))
    return (*_findings(path, puzzle), horizon)


def _today_deps(path, row):
    """What a cached _file_row read besides its file and code: whether
    today is before its horizon, so the row is made afresh the day its
    future-date finding would come or go."""
    return row[2] is not None and _TODAY < row[2]


#: Below this many judged files (a pre-push check of a few edits) the row
#: cache costs more than it saves: following the code to its key and data
#: files takes seconds, viewing a file a few milliseconds.
ROW_CACHE_MIN = 500


def _table_salt():
    """A hash of the tools/data tables that fetch_puzzle.load_source_table
    reads by a computed name, which row_cache.data_files() cannot follow;
    _one_file reaches SOURCE_ANSWER_WRONG and SOURCE_CLUE_WRONG."""
    data = Path(__file__).resolve().parent / "data"
    src = (Path(__file__).resolve().parent / "fetch_puzzle.py").read_text(encoding="utf-8")
    h = hashlib.sha1()
    for name in sorted(set(re.findall(r'load_source_table\("(\w+)"\)', src))):
        f = data / f"{name}.json"
        h.update(name.encode() + b"\0" + (f.read_bytes() if f.exists() else b"absent") + b"\0")
    return h.hexdigest()[:16]


def _judge(paths, files=None):
    """[_one_file(p) for p in paths], over every core; a long list through
    row_cache, so a file whose content, code and horizon are those of its
    stored row is not viewed again. `files` is the caller's listing(), whose
    blob shas key the rows: not read a second time."""
    if len(paths) < ROW_CACHE_MIN:
        return parallel.pmap(_one_file, paths)
    import row_cache
    rows = row_cache.cached_map("puzzle_integrity", _file_row, paths, salt=_table_salt(), deps=_today_deps,
                                listed=files, stale_ok=True)
    return [([f for f in flags if not _forgiven(f)], row) for flags, row, _ in rows]


_OFF_BOARD = re.compile(r": \d+ cells (?:across|down) from \(")


def _forgiven(flag):
    """Whether the tables as they are now forgive `flag`. The check_* functions
    forgive as they go, but a stale_ok row was made by older code, so its
    findings are judged again here by the current PUBLISHED_WRONG and
    UNLINKED_IN_SOURCE, with the same keys and scope: UNLINKED_IN_SOURCE
    forgives LENGTH only, and an off-board GRID finding is forgiven by none."""
    kind, pid, finding = flag
    if kind == "GRID" and _OFF_BOARD.search(finding):
        return False
    if (pid, finding) in PUBLISHED_WRONG:
        return kind in ("LENGTH", "GRID", "NUMBER", "CROSS", "DATE")
    return kind == "LENGTH" and (pid, finding) in UNLINKED_IN_SOURCE


CACHE = Path.home() / ".cache" / "cryptic-teacher" / "integrity-rows.sqlite"


def _git(*args):
    out = subprocess.run(["git", "-C", str(puzzle_paths.PUZZLE_DIR.parent), *args], capture_output=True, check=True).stdout
    return [x for x in out.decode("utf-8", "surrogateescape").split("\0") if x]


def _blob_sha(path):
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def listing():
    """{name: git blob sha}, name being the path under the repo root as a
    string (pathlib is the cost at 80k paths), of every .json under puzzles/ that is tracked or
    untracked-and-not-ignored — what puzzle_files() and check_strays() walk,
    read off git's index in a fraction of a second instead of a 40k-entry
    directory walk. A file edited since the index was written is hashed from
    its bytes. Outside a git checkout, every file is hashed."""
    root = puzzle_paths.PUZZLE_DIR.parent
    try:
        tracked = {}
        for rec in _git("ls-files", "-s", "-z", "--", "puzzles"):
            meta, name = rec.split("\t", 1)
            tracked[name] = meta.split()[1]
        for name in _git("ls-files", "-d", "-z", "--", "puzzles"):
            tracked.pop(name, None)
        dirty = set(_git("ls-files", "-m", "-z", "--", "puzzles")) | set(
            _git("ls-files", "-o", "--exclude-standard", "-z", "--", "puzzles"))
        names = {n: (None if n in dirty else tracked.get(n))
                 for n in set(tracked) | dirty if n.endswith(".json") and n not in ()}
    except (OSError, subprocess.CalledProcessError):
        names = {p.relative_to(root).as_posix(): None for p in puzzle_paths.PUZZLE_DIR.rglob("*.json")}
    out = {}
    for n, sha in names.items():
        if sha is None:
            try:
                sha = _blob_sha(root / n)
            except OSError:
                continue
        out[n] = sha
    return out


PUBLISHED_NAME = re.compile(r"[^/]*-[0-9][^/]*\.json")


def published(files):
    """The names in listing() that puzzle_files() would return, sorted."""
    prefix = puzzle_paths.PUZZLE_DIR.relative_to(puzzle_paths.PUZZLE_DIR.parent).as_posix() + "/"
    out = []
    for name in files:
        if name.startswith(prefix):
            rel = name[len(prefix):].split("/")
            if len(rel) == 3 and PUBLISHED_NAME.fullmatch(rel[2]):
                out.append(name)
    return sorted(out, key=lambda n: n.split("/"))


def _fingerprint():
    here = Path(__file__).resolve().parent
    h = hashlib.sha1()
    for name in ("clue_index.py", "series.py"):
        h.update((here / name).read_bytes())
    h.update(inspect.getsource(content_hash).encode())
    h.update(inspect.getsource(date_of).encode())
    return h.hexdigest()


def cache_path(fp):
    return CACHE.with_name(f"{CACHE.stem}-{fp[:16]}{CACHE.suffix}")


def _prune(keep, days=3):
    """Drop cache files of other fingerprints untouched for `days`, and the
    old single-file cache."""
    cutoff = time.time() - days * 86400
    for old in [CACHE, *CACHE.parent.glob(f"{CACHE.stem}-*{CACHE.suffix}*")]:
        if old.name.startswith(keep.name):
            continue
        try:
            if old == CACHE or old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass


def _open_cache():
    """The sqlite cache of cross-puzzle facts, keyed by git blob sha so that it
    holds across checkouts and worktrees: one row per distinct file content
    (id, digest, number of clue keys, the dated row) and one (clue key, row)
    pair per clue key, indexed by key so a single puzzle's neighbours are an
    index lookup instead of a 50 MB load."""
    fp = _fingerprint()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    path = cache_path(fp)
    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA synchronous=OFF")
    # One file per source fingerprint: a worktree with different source never
    # touches this file, so nothing is ever dropped under a running audit.
    with conn:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS rows(id INTEGER PRIMARY KEY, blob TEXT UNIQUE, pid TEXT, digest TEXT,"
            " nkeys INTEGER, held BLOB);"
            "CREATE TABLE IF NOT EXISTS clues(key TEXT, id INTEGER, PRIMARY KEY(key, id)) WITHOUT ROWID;")
    _prune(path)
    return conn


def _store(conn, new):
    """new: [(blob, (pid, digest, keys, held))] — rows the cache lacks."""
    with conn:
        for blob, (pid, digest, keys, held) in new:
            cur = conn.execute("INSERT OR IGNORE INTO rows(blob, pid, digest, nkeys, held) VALUES(?,?,?,?,?)",
                               (blob, pid, digest, len(keys), pickle.dumps(held)))
            if cur.rowcount:
                conn.executemany("INSERT OR IGNORE INTO clues VALUES(?,?)",
                                 ((k, cur.lastrowid) for k in keys))


def _cached(conn, files):
    """{blob: (id, pid, digest, nkeys, held)} for the blobs of `files` the cache holds."""
    wanted = set(files.values())
    out = {}
    for rid, blob, pid, digest, nkeys, held in conn.execute("SELECT id, blob, pid, digest, nkeys, held FROM rows"):
        if blob in wanted:
            out[blob] = (rid, pid, digest, nkeys, pickle.loads(held))
    return out


def _summary(item):
    """_one_file's cross-file row alone, for a file the run does not judge.
    CI's puzzle fast path checks out only the changed puzzles' folders, so a
    file the row cache misses is read from its blob instead of the disk."""
    path, blob = item
    if path.exists():
        puzzle = read_puzzle_view(path)
    else:
        import annotation
        raw = subprocess.run(["git", "cat-file", "blob", blob], cwd=Path(__file__).resolve().parent,
                             capture_output=True, check=True).stdout
        puzzle = annotation.view_puzzle(json.loads(raw))
    pid = puzzle["id"]
    return (pid, content_hash(puzzle), clue_keys(puzzle),
            (series_meta.of(puzzle) or "cryptic", puzzle["number"], date_of(puzzle), pid))


def _neardups(conn, cached, files, paths, mine_rows):
    """The NEARDUP findings that name one of `mine_rows` ((pid, keys) pairs),
    from the cache's clue index: every other puzzle sharing at least THRESHOLD
    of the smaller one's clues, exactly what ClueIndex.pairs() reports for
    those pairs."""
    by_id = {}
    for path in paths:                       # the last file of an id wins, as in ClueIndex
        rid, pid, _, nkeys, _ = cached[files[path]]
        by_id[pid] = (rid, nkeys)
    found = set()
    for pid, keys in mine_rows:
        if not keys:
            continue
        marks = ",".join("?" * len(keys))
        ids = dict(conn.execute(f"SELECT id, count(*) FROM clues WHERE key IN ({marks}) GROUP BY id", list(keys)))
        for other, (rid, nkeys) in by_id.items():
            shared = ids.get(rid)
            if not shared or other == pid:
                continue
            small = min(len(keys), nkeys)
            if small >= MIN_CLUES and shared >= THRESHOLD * small and not known_copy(pid, other):
                a, b = sorted((pid, other))
                na, nb = (len(keys), nkeys) if a == pid else (nkeys, len(keys))
                found.add((a, b, shared, na, nb))
    return sorted(found)


def check_table_ids(held, flags):
    """A FILED finding for each puzzle PUBLISHED_WRONG or UNLINKED_IN_SOURCE
    forgives a finding of that is not among the filed ids `held`: a row written
    ahead of its puzzle (or left after it went) forgives nothing, and is a
    finding here rather than a crash in whatever reads the puzzle it names.
    Not part of audit(): its test repos hold none of the tables' puzzles, so
    test_puzzle_integrity.py runs it over the real corpus instead."""
    for name, table in (("PUBLISHED_WRONG", PUBLISHED_WRONG), ("UNLINKED_IN_SOURCE", UNLINKED_IN_SOURCE)):
        for pid in sorted({pid for pid, _ in table} - held):
            flags.append(("FILED", pid, f"{name} forgives findings of {pid}, which is not filed"))


def audit(files, paths, today, only=None):
    """One flat list of (flag, puzzle id, what) plus the duplicate groups, over
    the puzzle files `paths` (published(files)) in `files` ({name: blob sha}, from listing()) and whatever
    else sits under puzzles/.

    With `only` (a set of published files), just those files are judged: their
    own checks, and the DUPLICATE, NEARDUP and DATE findings that name one of
    them, weighed against every other file through the cache."""
    global _TODAY
    _TODAY = today
    judged = paths if only is None else [n for n in paths if n in only]
    root = puzzle_paths.PUZZLE_DIR.parent
    results = _judge([root / n for n in judged], files)
    flags, rows = [], {}
    for path, (own, row) in zip(judged, results):
        flags.extend(own)
        rows[path] = row
    conn = _open_cache()
    cached = _cached(conn, files)
    have = {files[p]: rows[p] for p in judged if files[p] not in cached}
    rest = {}
    for p in paths:
        if files[p] not in cached and files[p] not in have:
            rest.setdefault(files[p], p)
    for blob, row in zip(rest, parallel.pmap(_summary, [(root / n, b) for b, n in rest.items()])):
        have[blob] = row
    if have:
        _store(conn, list(have.items()))
        cached = _cached(conn, files)
    by_content = defaultdict(list)
    held = []
    for path in paths:
        _, pid, digest, _, row = cached[files[path]]
        by_content[digest].append(pid)
        held.append(row)
    cross = []
    check_dates(held, cross)
    if only is None:
        check_strays(set(paths), cross, files)
        index = ClueIndex()
        for path in paths:
            index.add_keys(rows[path][0], rows[path][2])
        pairs = index.pairs()
    else:
        pairs = _neardups(conn, cached, files, paths, [(rows[p][0], rows[p][2]) for p in judged])
    for a, b, k, na, nb in pairs:
        cross.append(("NEARDUP", a, f"{k} of {na} clues are the same as {b}'s ({nb}) "
                                    "— one is another's copy filed under a wrong id"))
    # A group every pair of which clue_index lists as a known copy (a reprint,
    # a syndication) is the paper printing one puzzle twice, not a filing slip.
    copies = sorted(sorted(ids) for ids in by_content.values() if len(ids) > 1
                    and not all(known_copy(a, b) for a, b in combinations(ids, 2)))
    if only is not None:
        mine = {rows[p][0] for p in judged}
        names = re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(mine))) + r")\b")
        cross = [f for f in cross if f[1] in mine or names.search(f[2])]
        copies = [ids for ids in copies if mine & set(ids)]
    conn.close()
    return flags + cross, copies


def refused(targets, today):
    """{repo-relative path: [what]} of the puzzle files `targets` that the
    pre-push audit would refuse: a flag on the file's own puzzle, a DUPLICATE
    group holding it, or a cross-file finding that names it (DATE's "not after
    listener-93's"), so a committer can hold those back and commit the rest."""
    files = listing()
    paths = published(files)
    root = puzzle_paths.PUZZLE_DIR.parent
    only = {puzzle_paths.resolve_puzzle(a).resolve().relative_to(root).as_posix() for a in targets}
    flags, copies = audit(files, paths, today, only)
    out = {}
    for path in sorted(only & set(paths)):
        pid = json.loads((root / path).read_text(encoding="utf-8")).get("id")
        own = re.compile(rf"\b{re.escape(str(pid))}\b")
        why = [f"{flag} {fpid}: {what}" for flag, fpid, what in flags if fpid == pid or own.search(what)]
        why += ["DUPLICATE of " + ", ".join(i for i in ids if i != pid) for ids in copies if pid in ids]
        if why:
            out[path] = why
    return out


def main(argv):
    if argv[:1] == ["--refused"]:
        for path, why in refused(argv[1:], newest_today()).items():
            print(f"{path}\t{'; '.join(why)}")
        return 0
    if argv[:1] == ["--quotes"]:
        flags = []
        for path in argv[1:]:
            puzzle = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(puzzle, dict) and "entries" in puzzle:
                check_annotation_quotes(puzzle, flags)
        for flag, pid, what in flags:
            print(f"{flag:<9} {pid:<22} {what}")
        return 1 if flags else 0
    quiet = "--quiet" in argv
    targets = [a for a in argv if not a.startswith("--")]
    started = time.time()
    today = newest_today()
    # What this tool judges is the files, read straight off disk: the index
    # is not consulted, so a stale index.json is not a defect in them.
    files = listing()
    paths = published(files)
    only = {puzzle_paths.resolve_puzzle(a).resolve().relative_to(puzzle_paths.PUZZLE_DIR.parent).as_posix() for a in targets} if targets else None
    flags, copies = audit(files, paths, today, only)
    rows = only or paths

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
              "every puzzle says where it and its answers came from, "
              "and every file is where puzzle_paths.file_for puts it")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
