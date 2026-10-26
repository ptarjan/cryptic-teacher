#!/usr/bin/env python3
"""File the daily Times cryptics in archive.org's scans of The Times 1974-99.

    python3 tools/file_archive_org_puzzles.py               # file what is new on disk
    python3 tools/file_archive_org_puzzles.py --dry-run     # count, write nothing
    python3 tools/file_archive_org_puzzles.py --limit 40    # read at most 40 new editions
    python3 tools/file_archive_org_puzzles.py --show NewsUK1990UKEnglish/1990-01-02_63592
    python3 tools/file_archive_org_puzzles.py --check-filed  # list filed puzzles with a clue it refuses now

Reads what tools/fetch_archive_org_editions.py leaves in
downloads.ARCHIVE_ORG/<item>/<date>_<issue>/ (djvu.xml.gz with word
positions, leaf_NNNN.jpg of each crossword page, pages.json) for the items
NewsUK19xxUKEnglish, and files each "Times Crossword Puzzle No N" as times-N:

  - The title is found in djvu.xml's words; on a crossword page whose words
    hold none, READERS read it over and under each grid-shaped patch of ink
    (ocr_titles), the number most of them read standing. The grid is the
    largest patch of ink under it (tools/trove_grid.py reads its blocks); the
    clues are the two columns under the grid, cut where the column's text
    stops being clues ("Solution to Puzzle No", another heading, a gap).
  - The columns are read four ways: archive.org's words, RapidOCR at twice
    the size with two recognisers (multilingual PP-OCRv4 and English
    PP-OCRv5), and Tesseract, whose errors are not RapidOCR's (READERS). Each is parsed as file_trove_puzzles.py parses
    Trove's text, after tidy() undoes the print's commonest slips, and each
    list is repaired from each other reading in turn (tools/clue_repair.py).
  - A reading votes only when it has clue words and its clues lie on the
    scanned grid by number and count and read like the others' clues of
    those numbers (screened): one with every clue blank is no reading, and
    one of another part of the page is dropped whole.
  - The grid read off the scan is used when it is symmetric and a list lies
    on it whole, or when at least LOOSE_SHARE of its lights each take a
    clue by that clue's own number and count (lay_loose); the rest are
    misreads, filed blank. Else it is rebuilt from the clue list
    (tools/reconstruct_grid.py), nearest the scan when several fit, and the
    puzzle is filed only when the clues lie on the rebuilt grid. When no
    grid fits the clues the scan's grid stands, the lights no clue lies on
    blank: on the 1970s-80s scans the grid reads true and the clue OCR is
    what fails.
  - Every clue's words and marks are then put to the other readings
    (agree): each word takes the lexicon spelling most readings share, a
    tie going to the one most like every reading's word; a non-word stands
    only when three read it (or two read it as a name inside the clue); a
    mark no other reading has is dropped, and a word or mark most other
    readings have where this one has none (lost, run together, or before
    the first word or after the last) is put in. The clue
    is filed blank (its count kept) when no spelling wins, when its count
    was lost, or when it holds another clue's number.
  - The answers come from the solution grid a later edition prints under
    "Solution to Puzzle No N", read by tools/trove_solution_ocr.py's
    read_framed (each cell between its own rules; a numbered or unsure cell
    matched to the grid's own letters, settled by its lights' words): a
    light only when every letter is read and it is a word, and the whole
    solution only when its blocks are the puzzle's.
  - Only a puzzle whose every clue has text goes into puzzles/times: one
    with a blank clue goes to --out (or nowhere without it).
  - A number already held is not written (unless this tool filed it and the
    new reading beats it on clues or answers, improves), but takes the
    reading's answers when this tool filed it (merge_answers: a new answer
    replaces the held one, and a held answer the re-read of its solution
    grid did not read again, or a new one crosses on another letter,
    goes); the reading goes to
    downloads.ARCHIVE_ORG_SOURCE, where tools/cross_validate.py's
    `archiveorg` adapter votes with it. Every reading goes there, filed or not.

A Times run also reads the 1930 Times (TIMES_1930: archive.org's pub_times,
one item an issue, "THE TIMES CROSSWORD PUZZLE No. 27"). Its pages are
scanned 13663px wide, so page() and leaf_lines() shrink them 4x to the
1974-99 scale. A 1-3 digit title number must lie within 3 of the one its
date implies (six a week from No 1 on 1 Feb 1930), else the page's
"SOLUTION OF PUZZLE No. N" gives N+1. The clues are four columns under the
grid (columns_of_four): ACROSS down the first two over the DOWN heading,
DOWN under it and on down the third and fourth. They print no counts, so
each reading gets the scanned grid's (counted()) and is filed without
them; a grid that does not read refuses the title. A count that fits any
text cannot show a clue whose lost number ran it into the one before, so
each reading's clues must name the grid's lights in order: a clue next to
a break (a light skipped, a number repeated, a list ending short) is
dropped from that reading, its lights left to the others or blank. Only RapidOCR's two
recognisers and the VLM (each virtual column read on its own) read them:
archive.org's words and the tuned Tesseract read these pages as junk.

--paper ft does the same for the Financial Times (items
FinancialTimes19xxUKEnglish, the same uploader): "CROSSWORD" over "No. 8,650
Set by DANTE", the grid under it and two clue columns under the grid, the
previous puzzle's grid under "Solution 8,649" in the next edition. Its
numbers run on into our ftcryptic series (No 13,232 in Nov 2009), so a
puzzle files as ftcryptic-N, with the setter when the name is one our
ftcryptic files know or a dictionary word.

--paper guardian does the same for the Guardian (items
TheGuardian19xxUKEnglish: 1971, 1984-85, 1995-98): "Guardian Crossword No
20,538" over "Set by Rufus", the grid under it, the previous puzzle's grid
beside it over "CROSSWORD SOLUTION 20,537", and three clue columns, the
third under that solution grid. Its numbers are our cryptic series' (the
feed starts at 21,620), so a puzzle files as cryptic-N.

--paper telegraph does the same for the Daily Telegraph (items
TheDailyTelegraph19xxUKEnglish and SundayTelegraph1971UKEnglish): "No.
18,340 ACROSS" heads the left of two clue columns, DOWN the right, and
the grid is under them (clues_above); the previous puzzle's grid prints
under "SOLUTION No. 18,339". Its numbers run on into our telegraph series
(No 25,846 in Feb 2009), so a puzzle files as telegraph-N.

The other papers' Gale pages tools/gale_fetch.py lays out
(Gale<Paper><year>UKEnglish/<date>, one page and no text, read as --paper
gale's are) are papers of their own: GALE_TELEGRAPH (also "CROSSWORD /
21,502" over the clues from ~1990) and GALE_FT, read by the telegraph and ft
runs (ALSO), and GALE_INDEPENDENT (--paper galeindependent, from No 1 on 7
October 1986, the numbers of our independent series) and GALE_SUNDAY_TIMES
(--paper galesundaytimes, weekly from No 1 on 11 January 1925, our
sundaytimes series' numbers), and GALE_TLS (--paper galetls, the TLS's
Friday crossword, No 102 by 5 June 1992, our tls series' numbers).

--paper gale reads the Times pages Paul saves from Gale's Times Digital
Archive (tools/gale_inbox.py lays each date out as
GaleTimes<year>UKEnglish/<date>; tools/edition_queue.py reads them minutes
after they land), under a ledger of its own (downloads.GALE_LEDGER). A Gale
page has no archive.org text, so READERS read its whole ink for the title
(ocr_headings); each solution heading is read again in its own band
(solution_bands: from each "Solution" word any reader read, and over each
solution-sized grid), where half the readers must read its number. Its
puzzles' source.url is the Gale document's page (pages.json "url"), which
provenance files as an OCR'd newspaper page, so annotation can ask for one
to be read again (tools/scan_queue.py). A Monday prints no solution, and a
Saturday prize's solution prints the next Saturday.

Resumable: downloads.ARCHIVE_ORG/filed.jsonl records each edition's
headings and verdicts against its inputs (its files, the solutions seen,
whether the VLM read it), after each edition. Editions never read go first, then the stale by when they were read
(tools/scan_queue.py), so a capped run (--limit, --seconds) never starts over.
--workers N reads N editions at once (one's VLM wait overlaps another's OCR).
A change to a paper's heading code (scan_key: the code scan() reaches,
method by method and across modules, tools/code_reach.py, the papers left
out, then that paper's own definition) makes each of its editions' scans
stale, so they are scanned again on their next read; adding or changing one
paper makes no other paper's edition due. Any
other change to this code or the VLM model makes nothing due: whoever makes it
runs the re-read once, `--reread [BEFORE]` (every edition last read before
BEFORE, an ISO time, default now; slices of one re-read share a BEFORE).
--no-scan reads only the due editions whose scans stand, and the scans of the
SOLUTION_DAYS after them (where their solutions print), and scans nothing.

The standing pass does not run this as a batch: tools/edition_queue.py
plans what is due (plan(): the same due_reason, scanning nothing) and runs
each edition as a unit of its own, scan_unit() or read_unit(), each locking
its edition and appending its own ledger row (scan_queue.append), so units
run side by side and a batch run (this CLI, holding the ledger's lock
throughout) holds them off: a unit then ends "held", left for the next plan.
"""
import argparse
import ast
import bisect
import collections
import copy
import contextlib
import datetime
import functools
import gzip
import hashlib
import json
import math
import os
import pickle
import re
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path
import clue_repair
import clue_text
import quotes
import crop_window
from clue_text import (CAPS_HEADING, COUNT_END, HEADING_ALONE, NUMBERED_HEADING, OPENING_NUMBER, OPENING_SPECK,
                       count_left, counts_mended, direction, heading_of, number_digits, numbered_heading,
                       uncounted_dropped)
import enumeration
import file_trove_puzzles as ftp
import ocr_clues
import provenance
import punctuation
import reconstruct_grid as rg
import scan_queue
import series as series_meta
import trove_grid
import trove_solution_ocr
import ocr_retry
import vlm_reader as vlm
from file_penguin_puzzle import separators
from groups import entry_id
import dir_cache
import media_manifest
import puzzle_paths
import downloads
import edition_commit
from edition_commit import filer_path, strayed
from ocr_clues import (
    READERS,
    UPSCALE,
    edits,
    engine,
    is_word,
    one_light_each,
    rank,
    read_words,
    reader_key,
    reconcile,
    similar,
    suspect,
)

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent

SERIES = "times"
CACHE = downloads.ARCHIVE_ORG
CROPS = Path(os.path.expanduser("~/.cache/archive_org_crops"))
SOURCE = downloads.ARCHIVE_ORG_SOURCE
TOOL = edition_commit.TOOL
#: archive.org's Times items.
ITEM = re.compile(r"NewsUK(19\d\d)UKEnglish$")
#: The Gale page images tools/gale_inbox.py lays out as Times editions of the
#: same shape (GaleTimes<year>UKEnglish/<date>), read as a paper of their own
#: (GALE).
GALE_ITEM = re.compile(r"GaleTimes((?:19|20)\d\d)UKEnglish$")
#: {edition} is "<item>/<file base name>", quoted: an item holds a whole year
#: of editions, and archive.org opens one's scan only at the path naming its
#: file ("May 28 1974, The Times, #59100, UK (en)"); the item alone opens
#: whichever edition it chooses.
PAGE_URL = "https://archive.org/details/{edition}/page/n{leaf}/mode/1up"


#: {edition dir as text: (its input_hash, pages.json's "url", its "edition")} of
#: pages_facts: on the media disk the two facts stand while the edition's
#: files do, so a plan (filed_number asks page_url of every title it judges,
#: two reads of pages.json each, ~3 ms a Samba read: ~17 s of an FT plan)
#: reads none again; save_likely and load_likely keep it between processes too.
_PAGES_FACTS = {}


def pages_facts(d):
    """(url, edition) of edition directory `d`'s pages.json ("url" and
    "edition", None when absent). For an edition on the media disk, read once
    while its input_hash stands (a pages.json is only ever replaced, which
    moves the manifest's hash when its size does: the PLAN_FULL caveat of any
    memo here); one elsewhere (a test's) is read every time."""
    k = os.fspath(d)
    files = None
    if media_manifest.on_media(d):
        try:
            files = input_hash(d)
        except OSError:
            files = None
        seen = _PAGES_FACTS.get(k)
        if files is not None and seen is not None and seen[0] == files:
            return seen[1], seen[2]
    pages = json.loads((Path(d) / "pages.json").read_text())
    if files is not None:
        _PAGES_FACTS[k] = (files, pages.get("url"), pages.get("edition"))
        _LIKELY_MOVED.append(True)
    return pages.get("url"), pages.get("edition")


def edition_of(d, found):
    """The {edition} of PAGE_URL for edition directory `d`: its item, then
    its file's base name (pages.json) unless that is the item itself."""
    name = pages_facts(d)[1]
    item = found["item"]
    return item if not name or name == item else f"{item}/{urllib.parse.quote(name, safe='')}"


def page_url(d, found, leaf):
    """Where a reader opens leaf `leaf` of edition directory `d`: the
    pages.json "url" of a page that is not archive.org's (a Gale page), else
    archive.org's PAGE_URL."""
    url = pages_facts(d)[0]
    return url or PAGE_URL.format(edition=edition_of(d, found), leaf=leaf)


#: The Times's numbers ran 4 digits ("8,565") until No 10,000 in May 1962.
NUMBER = r"(\d{1,2}[,.\s]?\d{3})"
#: The daily cryptic's title: not the Concise, the Jumbo, Times Two, the
#: Listener or a solution heading (none of those words before "Crossword").
#: The OCR garbles the words before "Crossword" ("Tfee Th:es", "THETIMES",
#: "I he l imes"), puts a mark before or after it ("Crossword . No."), runs
#: "No" on ("PuzzleNo") and "Times" into it ("TimesCrossword"), garbles
#: "Puzzle" before a "No" ("Pnzzle No", "Pu/zle No"), splits "Crossword" ("Or ossword"), drops "No",
#: splits the number ("1 8,862", "17,1 11"),
#: reads its comma as any mark ("21*065") and its 1 as i ("i.5,543"); the
#: number is four digits before No 10,000 (1962: "No. 8,565");
#: read_puzzle checks the number against the date.
TITLE = re.compile(r"^\W*(?:(?!(?:sunday|conc\w*|jumbo|two|quick|\w*stener|solutions?|to|of)\b)\S{1,8}\s+){0,4}?"
                   r"(?:(?:the)?\s?t[il1]mes)?\W{0,3}[co0]r\s?ossword\W{0,3}"
                   r"(?:puzzle\W{0,3}|[^\s\d]{4,7}?\s*(?=n[o0]\b))?(?:n[o0]\W{0,3})?\s*"
                   r"([\dTIil][.,]?\s?\d[^\w\s]{0,2}\s?\d\s?\d(?:\s?\d)?)(?!\d)", re.IGNORECASE)
#: The previous puzzle's solution, printed under the clues ("to" read "tn").
SOLUTION = re.compile(r"^\W*solution\s+(?:t[o0n]|o[fl])\s+puzzle\s+n[o0]\.?\s*" + NUMBER, re.I)
#: How many puzzles before a page's title the solutions under it are: the day
#: before's, and on a Saturday also the prize from the Saturday before.
SOLUTION_LAGS = (1, 6)
#: How many puzzles before a Saturday's title the Saturday before's prize is
#: in a week a holiday took one or two issues from (Christmas: 16,618 under
#: 16,622).
HOLIDAY_LAGS = (4, 5)
#: A solution heading as the OCR garbles it ("Solution of Push No. 15,645",
#: "Solution to Tuzzle No I5.13S", 1986's "Solution to No 16,983"): a word, a
#: connective, a word ("Puzzle"; none when the first is "Solution"), maybe "No",
#: the connective run into the word where the OCR lost the space between
#: ("Solution ofPtazfe No 15,761", "Solution oTPnzzle No 16.147": a lowercase
#: letter, then a capital),
#: then the number, maybe read in pieces ("15 ,751", "19,7 1 1", "1 9.037",
#: ". 15, 244", the 1960s' "No. 1 10,530": a speck before the whole number, its piece six marks), and
#: the dot leader the 1940s-60s heading runs on into read glued to it ("SOLUTION OF PUZZLE No. 10,052....",
#: 1962-07-28: ten marks, past the seven a number takes; "PUZZLE.No.-10,308..-");
#: solution_number() decides.
LOOSE_NUMBER = r"(?:[nm][^\s\d]{0,2}\s*)?(\S{1,7}(?:\s\S{1,6}){0,2})[-.,:;]{0,8}$"
#: A heading's number read whole and clean after a speck of one or two marks ("1 10,530", ".1 10,846"):
#: solution_at takes it where it is one expected, the speck's digit read on making it none.
SPECKED_NUMBER = re.compile(r"^\S{1,2}\s+(\d{1,2}[,.]\d{3})\W{0,8}$")
#: How many puzzles before a Monday's title the Saturday prize it prints the solution of is
#: (2006-10-23's 23,427: "Solution to Prize Crossword 23,420"): the Gale Times of 2000-2012
#: printed a Saturday's prize solution on the Monday week after, nine days on, headed "Solution
#: to Prize Crossword N" (2006) or "Prize solution N" (2009).
PRIZE_LAG = 7
#: That heading: maybe "Solution to", then "Prize" and "Crossword" or "Solution", then the
#: number (LOOSE_NUMBER); prize_words() judges the words.
PRIZE_SOLUTION = re.compile(r"^\W*(?:(\S{4,11})\s+(\S{1,3})\s+)?(\S{4,7})\s+(\S{5,10})\W*\s+" + r"(?:[nm][^\s\d]{0,2}\s*)?"
                            r"(\S{1,7}(?:\s\S{1,5}){0,2})$", re.IGNORECASE)
#: The 2006-07 Gale Times Monday's heading of the Saturday prize's solution: "Competition Solution 23,450"
#: (2006-11-27; no "Prize" word, so no PRIZE_SOLUTION): its words like "competition" and "solution".
COMPETITION_SOLUTION = re.compile(r"^\W*(\S{9,13})\s+(\S{6,10})\W*\s+(\S{1,7}(?:\s\S{1,5}){0,2})$", re.IGNORECASE)


def prize_words(m):
    """Whether PRIZE_SOLUTION match `m`'s words read as "Solution to Prize Crossword" or "Prize
    solution"."""
    lead, _, prize, word = m.groups()[:4]
    if not like(prize, "prize"):
        return False
    if lead:
        return like(lead, "solution") and (like(word, "crossword") or like(word, "puzzle"))
    return like(word, "solution")


YESTERDAY_SOLUTION = re.compile(r"^\W*yesterday\W?s\s+s[o0]l\w{3,5}\s+" + LOOSE_NUMBER, re.IGNORECASE)
LOOSE_SOLUTION = re.compile(r"^\W*(\S{4,11})\s+(\S{1,3})(?:\s+|(?-i:(?<=[a-z])(?=[A-Z])))(?:(\S{3,9})\s+)?" + LOOSE_NUMBER,
                            re.IGNORECASE)
#: The 1980s-90s heading: "The Solution" over "No 16,219".
SOLUTION_OVER = re.compile(r"^\W*(?:the\s+)?(\S{6,10})\W*$", re.IGNORECASE)
NUMBER_UNDER = re.compile(r"^\W*" + LOOSE_NUMBER, re.IGNORECASE)
#: What each digit reads as: letters and marks first; a digit misread as
#: another (8 as 3) costs half a wrong one.
DIGIT_READS = {"0": ("ODQUoucC()", "689"), "1": ("IilLTtJj|!/]", "7"), "2": ("Zz", "7"), "3": ("B", "85"),
               "4": ("Aa", "1"), "5": ("Ss$", "63"), "6": ("Gb", "580"), "7": ("?", "12"),
               "8": ("BS&", "3605"), "9": ("gq", "0")}
#: What each side of a 0 the OCR reads as two marks ("211443" for 20,443,
#: "2IL287" for 20,287) reads as: a 0 read so costs a digit-for-digit misread.
ZERO_HALVES = "1IilL|!()[]"
#: The most a misread number may cost (solution_number: a wrong digit 2, a
#: digit-for-digit misread 1, one dropped or extra 2).
REPAIR_COST = 2


def read_cost(read, want):
    """What it costs to read the digits `want` as `read` (separators gone)."""
    def at(r, w):
        letters, digits_ = DIGIT_READS[w]
        return 0 if r == w or r in letters else 1 if r in digits_ else 2
    if len(read) == len(want):
        return sum(at(r, w) for r, w in zip(read, want))
    if len(read) == len(want) - 1:
        return 2 + min(read_cost(read, want[:k] + want[k + 1:]) for k in range(len(want)))
    if len(read) == len(want) + 1:
        split = [1 + read_cost(read[:k] + w + read[k + 2:], want) for k, w in enumerate(want)
                 if w == "0" and read[k] in ZERO_HALVES and read[k + 1] in ZERO_HALVES]
        return min([2 + min(read_cost(read[:k] + read[k + 1:], want) for k in range(len(read)))] + split)
    return REPAIR_COST + 1


def solution_number(text, expected):
    """The number of `expected` a heading's misread number `text` is, or
    None: the one it costs least to read as (read_cost, at most
    REPAIR_COST), and no other as cheap. A clean read near one expected
    but not it ("15,683" under the title 15,683) is the title or the
    heading misread, and which is unknowable: None."""
    read = clue_text.number_figures(text)
    if read.isdigit() and int(read) in expected:
        return int(read)
    if read.isdigit() and any(abs(int(read) - e) < 10 for e in expected):
        return None
    costs = sorted((read_cost(read, str(e)), e) for e in expected if e > 0)
    if costs and costs[0][0] <= REPAIR_COST and (len(costs) == 1 or costs[1][0] > costs[0][0]):
        return costs[0][1]
    return None


def like(word, model):
    return SequenceMatcher(None, word.lower(), model).ratio() >= 0.6


def solution_headings(lines, titles):
    """[(number, box)] of the solution headings on a leaf whose titles are
    `titles`: each line, or its tail past a clue column the OCR ran it on
    from, reading as LOOSE_SOLUTION with "solution" or "puzzle" like
    itself, whose number is one SOLUTION_LAGS before a title
    (solution_number), or read clean as one HOLIDAY_LAGS before (a week
    short of an issue: linked_solutions keeps it only where the filed
    dates say a prize was). With no title read, SOLUTION's exact headings."""
    if not titles:
        return headings(lines, SOLUTION)
    expected = {t - lag for t in titles for lag in SOLUTION_LAGS}
    clean = {t - lag for t in titles for lag in HOLIDAY_LAGS} - expected
    prize = {t - PRIZE_LAG for t in titles}
    found = []
    for ws in lines:
        k = 0
        while k < len(ws):
            end = solution_at(ws, k, expected, clean, prize)
            if end is None:
                k += 1
                continue
            n, j = end
            part = ws[k:j + 1]
            found.append((n, (min(v[0] for v in part), min(v[1] for v in part),
                              max(v[2] for v in part), max(v[3] for v in part))))
            k = j + 1
    return found + solutions_over(lines, expected)


def solution_at(ws, k, expected, clean=(), prize=()):
    """(number, last word's index) of the shortest LOOSE_SOLUTION heading
    opening at word `k` of a line whose number is one of `expected`
    (solution_number), or read digit for digit as one of `clean`, or a
    PRIZE_SOLUTION heading numbered one of `prize`, or None. A line may hold two ("Solution to Puzzle
    No 19,243 Solution to Punk No 19.248"): solution_headings reads on past
    the first."""
    text = ""
    for j in range(k, len(ws)):
        text = (text + " " + ws[j][4]).strip()
        if prize:
            p = PRIZE_SOLUTION.match(text)
            if p and prize_words(p) and not re.search(r"\d", "".join(g or "" for g in p.groups()[:4])):
                n = solution_number(p[5], prize)
                if n is not None:
                    return n, j
            c = COMPETITION_SOLUTION.match(text)
            if c and like(c[1], "competition") and like(c[2], "solution") and not re.search(r"\d", c[1] + c[2]) \
                    and re.fullmatch(r"\d{1,2}[,.]\d{3}\W?", c[3]) and number_of(c[3].rstrip(".,:;")) in prize:
                return number_of(c[3].rstrip(".,:;")), j  # read clean, no repair: one reader's "23, 530"
                # beside the others' "23,539" (2007-03-12) is no number of its own
        y = YESTERDAY_SOLUTION.match(text)
        if y:  # the 2009-10 Gale Times: "Yesterday's solution 24,378" over its grid
            n = solution_number(y[1], expected)
            if n is not None:
                return n, j
            continue
        m = LOOSE_SOLUTION.match(text) or LOOSE_SOLUTION.match(unspecked(text))
        if not m or not (like(m[1], "solution") or m[3] and like(m[3], "puzzle")) \
                or re.search(r"\d", m[1] + (m[3] or "")) or len(re.findall(r"\d", m[4])) < 2:
            continue  # (a number of fewer than two digits is a word: "SoL.uTioN OF Puzzt" read
            # its "Puzzt" as 10221, u 0, z 2, t 1, and linked 1964-02-12's grid of 10,530 to it)
        n = solution_number(m[4], expected)
        s = n is None and SPECKED_NUMBER.match(m[4])
        if s and number_of(s[1]) in expected:
            n = number_of(s[1])
        read = re.sub(r"[\s,.]", "", m[4])
        if n is None and read.isdigit() and int(read) in clean:
            n = int(read)
        if n is not None:
            return n, j
    return None


#: Marks the OCR glues between a heading's words ("Solution to.Puzzle",
#: "Solution-to", "Puzzle:No"), or between its last word and the number ("Solution to Crossword.21,677",
#: "Crossword. 21,677": 2001-03-17).
GLUED_MARKS = re.compile(r"(?<=[A-Za-z])[.:\-'’`]+(?=[A-Za-z]|\s?\d)")
#: A speck read as a word of its own between a heading's words: marks
#: ("No : 14,276"), or one character before a word ("Solution 1 to Puzzle",
#: RapidOCR's "Solution" + "n of Puzzle" where its second box starts inside
#: the first).
SPECK = re.compile(r"(?<=\s)(?:[^\w\s]+\s+|\w\s+(?=[A-Za-z]))")


def unspecked(text):
    """A heading line's `text` with GLUED_MARKS parted and SPECK words
    dropped: what solution_at reads where the line as read is no
    LOOSE_SOLUTION."""
    return SPECK.sub("", GLUED_MARKS.sub(" ", text))


def solutions_over(lines, expected):
    """[(number, box)] of each "The Solution" line (SOLUTION_OVER) with a
    "No 16,219" line (NUMBER_UNDER, solution_number) next under it, the two
    overlapping across, or under a "Prize Puzzle" line (PRIZE_UNDER) next
    under it (the 1984 Monday's Saturday prize solution)."""
    found = []
    for ws in lines:
        m = SOLUTION_OVER.match(" ".join(w[4] for w in ws))
        if not m or not like(m[1], "solution"):
            continue
        under = lines_under(lines, ws)
        if under and PRIZE_UNDER.match(" ".join(w[4] for w in under[0])):
            under = lines_under(lines, under[0])
        for u in under[:1]:
            num = NUMBER_UNDER.match(" ".join(w[4] for w in u))
            n = num and solution_number(num[1], expected)
            if n:
                found.append((n, box_of(ws + u)))
    return found


def lines_under(lines, ws):
    """The `lines` starting within two of line `ws`'s heights under it and
    overlapping it across, top first."""
    top = box_of(ws)
    return sorted((u for u in lines if u is not ws and top[3] <= box_of(u)[1] <= top[3] + 2 * (top[3] - top[1])
                   and box_of(u)[0] < top[2] and box_of(u)[2] > top[0]), key=lambda u: box_of(u)[1])


#: The line between "The Solution" and its number on a prize puzzle's.
PRIZE_UNDER = re.compile(r"^\W*prize\s+p\S{4,6}\W*$", re.IGNORECASE)


#: A column line that ends the clues.
STOP = re.compile(r"^\W*(solution|yesterday\W?s\s+solution|crossword|concise|times\s+two|the\s+times\s+crossword|the\s+solution\s+(?:to|of)"
                  r"|championship|jumbo|\w{0,10}\s+(of|to)\s+puzzle|\S{4,9}\s+t[ao]m+or+ow|publ\w+\s+by"
                  r"|\S+\s+cr[o0]s+w[o0u]r?d\W+\w{2,5}\s+\d+)\b", re.I)
#: A line opening on a lowercase word ("championship. possibly (4).") runs
#: on a clue from the line above: a notice opens on a capital.
CONTINUED = re.compile(r"\W*[a-z]{4,}\b")
#: The solution heading under a column, its opening misread ("cotution of
#: Puzzle No 13.682", "^j^on D f Puzzle No 13.682", 1974): no clue's line
#: ends on a puzzle's number.
PUZZLE_NO = re.compile(r"\bp[uo]\S{2,4}\s+n[o0]\.?\s*\d{1,2}\s?[.,]?\s?\d{3}\W{0,2}$", re.I)


def stops(text):
    """Whether a column line ends the clues: a STOP line, never a clue's
    run-on line, or one ending on a puzzle's number."""
    return bool(STOP.match(text)) and not CONTINUED.match(text) or bool(PUZZLE_NO.search(text))


#: The vertical gap, in pixels at the scan's 3296x4672, that ends a column.
GAP = 80
#: How far, in pixels, a line must start left of the split between two
#: columns and run on right of it to be printed across both (a centred
#: notice); a right-hand clue's outdented number starts a pixel or two left.
ACROSS_GUTTER = 60
#: What a line printed across both columns reads as in columns().
NOTICE = "\x00across the columns"


def number_of(text):
    return int(re.sub(r"\D", "", text))


# ------------------------------------------------------------ djvu.xml

def leaf_lines(xml_path, leaves):
    """{leaf: [[(x0, y0, x1, y1, text), ...] per printed line]} for the leaves
    asked for. Only those leaves' OBJECT elements are parsed: the n-th
    "<OBJECT" in the file is leaf n. {} when there is no such file (a
    Gale page has no archive.org text)."""
    if not Path(xml_path).exists():
        return {}
    with gzip.open(xml_path) as f:
        data = f.read()
    out = {}
    shrink = paper_of(Path(xml_path).parent).shrink
    for n, m in enumerate(OBJECT_TAG.finditer(data)):
        if n not in leaves:
            continue
        end = data.index(b"</OBJECT>", m.start()) + len(b"</OBJECT>")
        el = ET.fromstring(data[m.start():end])
        lines = []
        for line in el.iter("LINE"):
            ws = []
            for w in line.iter("WORD"):
                x0, y1, x1, y0 = (int(v) // shrink for v in w.get("coords").split(",")[:4])
                t = (w.text or "").strip()
                if t:
                    ws.append((x0, y0, x1, y1, t))
            if ws:
                lines.append(ws)
        out[n] = lines
        if len(out) == len(leaves):
            break
    return out


OBJECT_TAG = re.compile(rb"<OBJECT[\s>]")


def headings(lines, pattern):
    """[(number, (x0, y0, x1, y1))] of each line opening with `pattern`; the
    box spans the words up to the number, not junk the OCR ran on into."""
    found = []
    for ws in lines:
        text = ""
        for k, w in enumerate(ws):
            text = (text + " " + w[4]).strip()
            m = pattern.match(text)
            if m and not re.search(r"\w", text[m.end():]):
                box = (min(v[0] for v in ws[:k + 1]), min(v[1] for v in ws[:k + 1]),
                       max(v[2] for v in ws[:k + 1]), max(v[3] for v in ws[:k + 1]))
                found.append((number_digits(m.group(1)), box))
                break
    return found


# ------------------------------------------------------------ the page

def ink_box(img, close=0):
    """The largest patch of ink in a PIL image, as (x0, y0, x1, y1), or None;
    with `close`, gaps up to that many pixels across closed first (a frame
    the scan broke)."""
    import numpy as np
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    ink = gray < trove_grid.otsu(gray)
    if close:
        cv2 = ocr_clues.capped_cv2()
        ink = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((close, close), np.uint8)) > 0
    return trove_grid.largest_component(ink)


def grid_shaped(box):
    """Whether an ink box is a grid's size and shape at the scans' 3296px
    page width."""
    if box is None:
        return False
    gw, gh = box[2] - box[0], box[3] - box[1]
    return 500 <= gw <= 1100 and 0.85 <= gw / max(gh, 1) <= 1.18


#: The page width grid_shaped() is measured at.
SCAN_WIDTH = 3296


def shaped_on(img, box):
    """grid_shaped() for a box on page `img`: a few pages are scanned at
    twice SCAN_WIDTH, their grid twice as wide."""
    return box is not None and grid_shaped(tuple(v * SCAN_WIDTH / img.width for v in box))


#: The papers (keys) whose grid is right of the clues their title heads,
#: never elsewhere (locate_grid's `right`), and wider than grid_shaped's:
#: the TLS's 15x15 is 38% of its page's width.
GRID_RIGHT = {"galetls"}
WIDE_GRID = 1400


def wide_shaped(img, box):
    """shaped_on(), up to WIDE_GRID wide at SCAN_WIDTH."""
    if box is None:
        return False
    gw, gh = ((v1 - v0) * SCAN_WIDTH / img.width for v0, v1 in ((box[0], box[2]), (box[1], box[3])))
    return 500 <= gw <= WIDE_GRID and 0.85 <= gw / max(gh, 1) <= 1.18


#: How far, in pixels, a crop grows on a side its largest ink touches, and
#: how many times, so a grid wider or further from its title than the
#: first crop is read whole.
GROW, GROW_TIMES = 200, 6


def ink_in(img, crop, fixed=()):
    """The largest ink in `crop` of `img`, in page coordinates, the crop
    grown on each side (but those named in `fixed`, of "left", "top",
    "right", "bottom") that the ink touches. Ink that grows out of a grid's
    shape (a grid joined to a rule across the page) gives the last
    grid-shaped box instead."""
    crop, shaped = list(crop), None
    for _ in range(GROW_TIMES + 1):
        box = ink_box(img.crop(tuple(crop)))
        if box is None:
            return shaped
        page_box = (crop[0] + box[0], crop[1] + box[1], crop[0] + box[2], crop[1] + box[3])
        shaped = page_box if shaped_on(img, page_box) else shaped
        cw, ch = crop[2] - crop[0], crop[3] - crop[1]
        grow = {"left": box[0] <= 2 and crop[0] > 0, "top": box[1] <= 2 and crop[1] > 0,
                "right": box[2] >= cw - 2 and crop[2] < img.width,
                "bottom": box[3] >= ch - 2 and crop[3] < img.height}
        grow = [side for side, on in grow.items() if on and side not in fixed]
        if not grow:
            break
        for side in grow:
            k = ("left", "top", "right", "bottom").index(side)
            crop[k] = max(0, crop[k] - GROW) if k < 2 else min((img.width, img.height)[k - 2], crop[k] + GROW)
    return page_box if shaped_on(img, page_box) or shaped is None else shaped


#: How far over its title a grid printed over it may end (the 1980s Times'
#: touches it).
ABOVE_GAP = 80


#: How many times wider than the grid under a title a grid left of it must be
#: for the one under it to be a solution's, not the puzzle.
LIVE_OVER_SOLUTION = 1.5


def locate_grid(img, title, right=False):
    """(box, side) of the grid a title heads: the largest ink under it, else
    over it (the 1980s Times prints its title under the grid), else left of
    it (the FT's Monday Prize prints it right of the grid's top), else right
    of it (the 1983-86 FT heads the clue column left of the grid's top);
    `side` is "below", "above", "left" or "right". (box, None) when no ink
    there is a grid, the box the ink under the title; (None, None) when
    there is none. A title box may reach past the page's edge (an FT one is
    widened to FT_GRID_SPAN about its middle): the crops are clipped to it.
    `right`: only right of it, out to the page's edge (the TLS heads its
    clues with its title, the grid beyond them, the last solution's grid
    left of them)."""
    x0, y0, x1, y1 = title
    w = x1 - x0
    span = int(1.3 * w) + 80
    cx = (x0 + x1) / 2
    tries = (("below", (max(0, x0 - 120), y1, min(img.width, x1 + 120), min(img.height, y1 + span)), ("top",)),
             ("above", (max(0, x0 - 120), max(0, y0 - span), min(img.width, x1 + 120), y0), ("bottom",)),
             ("left", (max(0, x0 - span), max(0, y0 - 80), min(img.width, x0), min(img.height, y0 + span)), ()),
             ("right", (max(0, int(cx)), max(0, y0 - 80), min(img.width, int(cx) + span), min(img.height, y0 + span)),
              ()))
    if right:
        tries = (("right", (max(0, int(cx)), max(0, y0 - 80), img.width, min(img.height, y0 + 3 * w)), ()),)
    first = None
    for side, crop, fixed in tries:
        if crop[2] - crop[0] < 2 or crop[3] - crop[1] < 2:
            continue
        box = footed(img, ink_in(img, crop, fixed))
        # The 1986 Saturday prize page sets the last puzzles' solution grids
        # under the title, its own grid further down: the crop starts under
        # them.
        if side == "below" and box is not None and solution_shaped(img)(box):
            crop = (crop[0], box[3], crop[2], min(img.height, box[3] + span))
            box = footed(img, ink_in(img, crop, fixed))
        # A grid under its title clears the title's line, one over it ends
        # within ABOVE_GAP of it, one left of it ends short of the title's
        # middle, and one right of it starts past it: other ink is something
        # else's (an article over the 1983 FT's title beside its grid).
        clear = box is not None and (side != "below" or box[1] > crop[1] + 2
                                     or starts_under(img, box, crop[1])) \
            and (side != "above" or box[3] >= y0 - ABOVE_GAP) \
            and (side != "below" or box[0] <= x1 + 120) \
            and (side != "left" or box[2] < cx) and (side != "right" or box[0] > cx)
        if clear and (wide_shaped if right else shaped_on)(img, box):
            # A grid under the title that a grid left of it dwarfs is the
            # day's solution (the 2005 Times, "Solution to Crossword" under
            # the live grid's clue columns): the live one is beside the title.
            if side == "below" and not right:
                _, lcrop, lfixed = tries[2]
                lbox = footed(img, ink_in(img, lcrop, lfixed)) if lcrop[2] - lcrop[0] >= 2 else None
                if lbox is not None and lbox[2] < cx and shaped_on(img, lbox) \
                        and lbox[2] - lbox[0] >= LIVE_OVER_SOLUTION * (box[2] - box[0]):
                    return lbox, "left"
            return box, side
        # A grid another side's crop finds whole under the title, across its
        # middle, is the grid under it: the one under-crop joins it to the
        # clue column (Times 16,977) or cuts it at a title it touches
        # (Times 14,132).
        if box is not None and box[1] > crop[1] + 2 and box[1] >= y1 - TITLE_OVERLAP \
                and box[0] < cx < box[2] and shaped_on(img, box):
            return box, "below"
        first = first or box
    return first, None


#: The share of a grid box's width a row of ink must cover to be the grid's
#: frame: a line of text, even one touching the grid, has gaps.
FRAME_SHARE = 0.8
#: How far up a grid box (a share of its height) its foot frame may lie:
#: ink under it is a heading or clue line touching the grid.
FOOT_INSET = 0.1
#: How far, in pixels, a grid's top frame may reach up into its title's box.
TITLE_OVERLAP = 12
#: The most of a pixel row's width a fold or speck crossing a clear row inks.
CLEAR_SHARE = 0.05
#: The share of a strip's pixel rows a column of ink must fill to be a
#: rule running down through it.
RULE_SHARE = 0.7
#: The fewest rules crossing a row of cells: a 15x15 grid's has 16, less
#: those its blocks join.
MIN_RULES = 8
#: How deep, in pitches between the rules crossing it, a grid's last row of
#: cells is, with the foot frame under it.
ROW_DEPTH = (0.75, 1.5)
#: The least pitch, as a share of the grid's width: a 27x27 grid's.
MIN_PITCH = 0.03


def rule_runs(ink):
    """[(x0, x1)] of each run of columns of a strip of ink that fill
    RULE_SHARE of its rows: the vertical rules (and blocks) crossing it."""
    import numpy as np
    full = np.concatenate(([False], ink.mean(axis=0) >= RULE_SHARE, [False]))
    edges = np.flatnonzero(full[1:] != full[:-1])
    return list(zip(edges[::2].tolist(), edges[1::2].tolist()))


def cells_under(ink, foot):
    """Whether the strip of `ink` under row `foot` is a row of cells:
    MIN_RULES rules cross it, and it is as deep as the pitch between them.
    A clue line touching the grid has no rules crossing it, or is shallower."""
    import numpy as np
    runs = rule_runs(ink[foot + 1:])
    if len(runs) < MIN_RULES:
        return False
    gaps = [g for g in np.diff([a for a, _ in runs]) if g >= MIN_PITCH * ink.shape[1]]
    if not gaps:
        return False
    pitch = float(np.median(gaps))
    return ROW_DEPTH[0] * pitch <= ink.shape[0] - foot - 1 <= ROW_DEPTH[1] * pitch


def footed(img, box):
    """`box` ending at the grid's foot frame, the lowest row in its bottom
    FOOT_INSET that ink covers FRAME_SHARE of: "ACROSS" printed touching the
    grid joins its ink, and the box would end under the first clue line,
    which every clue crop then loses. Unchanged when no row is a frame, or
    the strip under it is the grid's last row of cells (its own foot frame
    too faint or turned to fill FRAME_SHARE of any one row)."""
    import numpy as np
    if box is None:
        return None
    gray = np.asarray(img.crop(box).convert("L"), dtype=np.uint8)
    ink = gray < trove_grid.otsu(gray)
    rows = ink.mean(axis=1)
    reach = int(FOOT_INSET * len(rows))
    foot = next((k for k in range(len(rows) - 1, len(rows) - 1 - reach, -1) if rows[k] >= FRAME_SHARE), None)
    if foot is None or foot == len(rows) - 1 or cells_under(ink, foot):
        return box
    trimmed = (box[0], box[1], box[2], box[1] + foot + 1)
    return trimmed if shaped_on(img, trimmed) else box


def starts_under(img, box, top):
    """Whether the ink of `box`, cut at `top` (its title's foot), starts
    within TITLE_OVERLAP over it: the grid's top frame reaching into the
    title's box, not ink running down through the title. A row within
    TITLE_OVERLAP either side of `top` that only a fold or a speck crosses
    (CLEAR_SHARE of it inked), with a row as wide as a frame (FRAME_SHARE)
    under it there, parts the title from the grid whatever runs down
    through both (a fold in the paper, No 54 of 1930-04-04; a title's
    descender over a frame 2px under its foot, Gale's 1987-01-07)."""
    import numpy as np
    if box[1] > top + 2:
        return True
    band = (box[0], max(0, top - TITLE_OVERLAP), box[2], top + 1)
    above = ink_box(img.crop(band))
    if above is None or above[1] > 0:
        return True
    gray = np.asarray(img.crop((band[0], band[1], box[2], box[3])).convert("L"), dtype=np.uint8)
    rows = (gray < trove_grid.otsu(gray))[: top + TITLE_OVERLAP + 1 - band[1]].mean(axis=1)
    return any(rows[k] <= CLEAR_SHARE and rows[k + 1:].max() >= FRAME_SHARE / 2 for k in range(len(rows) - 1))


def grid_box(img, title):
    """Where the grid a title heads is on the page; see locate_grid()."""
    return locate_grid(img, title)[0]


def grid_under_clues(img, title):
    """Where the grid is when the clues are printed over it: the largest ink
    in the CLUES_ABOVE_SPAN under the title, which is the left column's
    head. When that ink is no grid (the ~1995 Gale Telegraph centres its
    "CROSSWORD / 21,502" banner over both columns, so the span starts mid
    ACROSS column and takes in the solution grid), the nearest grid-shaped
    ink under the title within the span either side of it."""
    x0, _, x1, y1 = title
    crop = (max(0, x0 - 80), y1, min(img.width, x0 + CLUES_ABOVE_SPAN[0]),
            min(img.height, y1 + CLUES_ABOVE_SPAN[1]))
    box = ink_box(img.crop(crop))
    if box is None:
        return None
    box = (crop[0] + box[0], crop[1] + box[1], crop[0] + box[2], crop[1] + box[3])
    if shaped_on(img, box):
        return box
    reach = CLUES_ABOVE_SPAN[0] * img.width / SCAN_WIDTH
    under = [g for g in grids_on(img, shaped=lambda b: shaped_on(img, b))
             if y1 <= g[1] <= y1 + CLUES_ABOVE_SPAN[1] * img.width / SCAN_WIDTH
             and g[0] >= x0 - reach and g[2] <= x1 + reach]
    return min(under, key=lambda g: g[1]) if under else box


#: How far right of and below the title of a clues-above puzzle its grid
#: may reach (the two columns and the grid under them).
CLUES_ABOVE_SPAN = (800, 1700)
#: How far the right column of a clues-above puzzle may run past the grid
#: (its end is the gap nearest the grid's edge in that span; see gutter()).
OVERHANG = 40


def clues_left(grid, title, margin=40):
    """The x where the two clue columns over a clues-above grid start:
    `margin` left of the grid, or of the title ("No. 15,302 ACROSS" heads
    the across column) when it starts further left. The 1970s Telegraph
    indents its grid under the clues, the Quick crossword's clues in the
    gap: a crop from the grid's edge cut every across clue's number off."""
    return min(grid[0] - margin, title[0] - margin)


def gutter(lines, grid, top, lo=None, hi=None):
    """The x between two clue columns over the grid: the middle of the
    longest run of x in [lo, hi) (by default the grid's middle half) that
    the fewest words (`lines`, every reading's) from `top` down to the grid
    cross. Near the grid's right edge, it is where the right column ends."""
    gx0, gy0, gx1, _ = grid
    lo = int(gx0 + 0.3 * (gx1 - gx0)) if lo is None else int(lo)
    hi = int(gx0 + 0.75 * (gx1 - gx0)) if hi is None else int(hi)
    cover = [0] * (hi - lo)
    for ws in lines:
        for w in ws:
            if top <= w[1] < gy0:
                for x in range(max(lo, w[0]), min(hi, w[2])):
                    cover[x - lo] += 1
    least = min(cover)
    best, run = (0, lo), None
    for k, c in enumerate(cover + [least + 1]):
        if c == least:
            run = k if run is None else run
        elif run is not None:
            best = max(best, (k - run, lo + (run + k) // 2))
            run = None
    return best[1]


#: How far right of the grid a clue line under it may end when it starts
#: well inside the grid's width (a skewed page's long line overhangs the
#: grid): the reach of the crop the RapidOCR readers read (rapid_lines()).
#: A word starting nearer the grid's edge than ACROSS_GUTTER is held to the
#: window's right edge, so a speck in the margin beside it joins no clue.
RIGHT_REACH = 30


#: The 1945-49 Times prints its last clues in a strip between the title and
#: the grid (1945-07-12: 26 and 27 down; 1945-08-10: 20, 21, 23, 24, 27 down):
#: every window began at the grid's foot or the title's foot, left of the grid,
#: and read none of it. The strip lies over the grid, from the title's foot
#: (STRIP_TITLE px up, the title box is a little tall) to the grid's top,
#: and is at least STRIP_MIN px high (anything less is paper between them).
STRIP_YEARS = ("1945", "1950")
STRIP_TITLE, STRIP_MIN, STRIP_INK, STRIP_RULE = 2, 30, 0.02, 0.6
#: Its columns split at a run of STRIP_GUTTER pixel columns holding next to no ink
#: (a rule between them does not break it), STRIP_EDGE from either end of it.
STRIP_GUTTER, STRIP_EDGE = 20, 60


def strip_over(img, grid, title, year):
    """(top, bottom, [x between columns]) of the clue strip over a 1945-49
    Times grid, or None when the page has none: the band from the title's foot
    to the grid's top is inked like text and at least STRIP_MIN px high."""
    if not STRIP_YEARS[0] <= year < STRIP_YEARS[1]:
        return None
    import numpy as np
    gx0, gy0, gx1, _ = grid
    top, bottom = title[3] - STRIP_TITLE, gy0 - 3
    if bottom - top < STRIP_MIN or bottom - top > 0.25 * (gx1 - gx0):
        return None
    ink = np.asarray(img.crop((gx0 - 5, top, gx1 + 15, bottom)).convert("L")) < 128
    if ink.mean() < STRIP_INK:
        return None
    share = ink.mean(axis=0)
    blank = share < 0.03
    runs, i = [], 0
    while i < len(blank):
        if not blank[i]:
            i += 1
            continue
        j = i
        while j < len(blank) and blank[j]:
            j += 1
        if runs and i - runs[-1][1] <= 5:
            runs[-1][1] = j
        else:
            runs.append([i, j])
        i = j
    # A gutter holds the rule printed between the columns (a short clue's
    # line end leaves a blank as wide); failing a rule, only a wide blank is one.
    inner = [(lo, hi) for lo, hi in runs if STRIP_EDGE <= (lo + hi) // 2 <= len(blank) - STRIP_EDGE]
    ruled = [(lo, hi) for lo, hi in inner if hi - lo >= STRIP_GUTTER and (share[lo:hi] > STRIP_RULE).any()]
    cuts = [gx0 - 5 + (lo + hi) // 2 for lo, hi in ruled or [r for r in inner if r[1] - r[0] >= 2 * STRIP_GUTTER]]
    return top, bottom, cuts


def windows(grid, third=None, margin=40, above=None, left=None, split=None, lead=None, right=None, strip=None):
    """windows_of() and, under the grid, the columns of the strip over it
    (`strip`, strip_over()) last, each with its own foot: a fifth element."""
    out = windows_of(grid, third, margin, above, left, split, lead, right)
    if strip and not (right or left or above):
        top, bottom, cuts = strip
        edges = [grid[0] - 5] + list(cuts) + [grid[2] + 15]
        out = out + [(a, b, b, top, bottom) for a, b in zip(edges, edges[1:])]
    return out


def windows_of(grid, third=None, margin=40, above=None, left=None, split=None, lead=None, right=None):
    """[(x0, x1, right edge, top)] of each clue column: a word whose left edge
    is in [x0, x1), right edge at most the right edge and top at least the
    top is in it. The two columns under the grid, and with `third`, (width,
    top), a column that wide right of the grid from `top` down. With `lead`,
    (x0, top, split), a column of the words starting from x0 to `split` (by
    the grid's left edge) and ending by the grid's edge, from `top` (its
    title's foot) down, comes first, and the column under the grid starts at
    `split` (lead_column(): the 1983-86 FT). The left
    column starts `margin` left of the grid (the Times outdents its numbers).
    A `split` tuple (first, second, end) is three columns under the grid.
    With `right`, (x1, gutter, bottom) (right_columns()), the two columns are
    right of the grid, from RIGHT_RISE over its top down to `bottom`, split
    at the gutter, the second ending at x1 (the 2014 Times).
    With `above`, (top, gutter, right[, x0]), the two columns are over the
    grid instead, from `top` down, split at the gutter, the right one ending
    at `right` (it may overhang the grid), the left starting at x0 (by
    default `margin` left of the grid; clues_left()). With `left`, (x0, gutter, bottom),
    they are left of the grid from x0, split at the gutter, from LEFT_RISE
    over the grid's top down to `bottom`; with no gutter, they are one
    column (left_column()). Under the grid, the columns split at `split`
    (under_gutter()), by default the grid's middle."""
    gx0, gy0, gx1, gy1 = grid
    if right:
        x1, split, _ = right
        return [(gx1 + 5, split, split, gy0 - RIGHT_RISE), (split, x1, x1, gy0 - RIGHT_RISE)]
    if left:
        x0, split, _ = left
        if split is None:
            return [(x0, gx0 - 5, gx0 - 5, gy0 - LEFT_RISE)]
        return [(x0, split, split, gy0 - LEFT_RISE), (split, gx0 - 5, gx0 - 5, gy0 - LEFT_RISE)]
    if above:
        top, split, right, x0 = (above + (gx0 - margin,))[:4]
        return [(x0, split, split, top), (split, right, right, top)]
    if isinstance(split, tuple):
        # Three columns under the grid, the last overhanging it (over_gutters()).
        g1, g2, x1 = split
        return [(gx0 - margin, g1, g1, gy1 - 5), (g1, g2, g2, gy1 - 5), (g2, x1, x1, gy1 - 5)]
    mid = gx0 + (gx1 - gx0) / 2 - 10 if split is None else split
    out = [(gx0 - margin, mid, gx1 + 15, gy1 - 5), (mid, gx1 + 15, gx1 + 15, gy1 - 5)]
    if lead:
        x0, top, edge, *inner = lead
        # With an inner gutter (lead_split(): ACROSS and DOWN in two columns
        # left of the grid), the lead is two columns, not one whose rows
        # would glue an ACROSS line to the DOWN line beside it.
        first = [(x0, inner[0], inner[0], top), (inner[0], edge, max(edge, gx0 - 5), top)] if inner \
            else [(x0, edge, max(edge, gx0 - 5), top)]
        out = first + [(edge,) + out[0][1:]] + out[1:]
    if third:
        out.append((gx1 + 15, gx1 + 15 + third[0], gx1 + 15 + third[0], third[1]))
    return out


#: Where a clue starts inside a recogniser's line: its number ("12", "l4",
#: "I6", "18:") and a capital.
#: A stop may close the line before it with no space ("out-. .23' Fires", Gale 1956-02-16's 23 down).
NEXT_CLUE = re.compile(r"(?<=[\s\-.])(?:\d{1,2}|[IlJ|!]\d|\d[IlsSoO])\W{0,2}\s*[A-Z\"'\u2018\u201c]")
#: The solution box's heading ("SOLUTION OF PUZZLE No. 7,091", read "SoLUTioN'orPuzzLB"), which the
#: 1950s Times sets in the row of the clue beside it: a cut like a clue's number (Gale 1952-12-13's 8 down).
SOLUTION_HEAD = re.compile(r"(?<=[\s.\-])s[o0]l[ui]t[il1]?[o0]n\W*[o0]\w?\W*p[uv]zz", re.IGNORECASE)
#: How far, in pixels, from a gutter a clue's number in a line read across
#: it may be placed by its share of the line's characters.
SPLIT_SLACK = 80
#: The most a row may lie over a gutter, as a share of its width left of it, to be a
#: column's row spilled over it and not a notice across both columns (split_across).
SPLIT_SPILL = 0.35


def split_across(ws, gutters, height=None):
    """`ws` with each word read across a gutter (RapidOCR reads two
    columns' rows as one line where the gutter is narrow: "11 Scandinavian
    has no right to 12 Sympathetic type") cut at the clue number placed
    nearest that gutter, the halves either side of it. A line with no clue
    number near the gutter (a notice printed across both) stays whole. A
    word taller than `height` (a line's) spans two rows set at different
    heights: each half is given that height about its middle, so the line
    printed under either half is not read as a second copy of it."""
    out = []
    for w in ws:
        if height and w[3] - w[1] > height:
            mid = (w[1] + w[3]) / 2
            tall = (w[0], mid - height / 2, w[2], mid + height / 2, w[4])
        else:
            tall = w
        for x in gutters:
            if not (w[0] < x and w[2] > x + ACROSS_GUTTER):
                continue
            text, width = w[4], w[2] - w[0]
            at = [(abs(w[0] + width * m.start() / len(text) - x), m.start())
                  for m in [*NEXT_CLUE.finditer(text), *SOLUTION_HEAD.finditer(text)] if m.start()]
            near = min((a for a in at if a[0] <= SPLIT_SLACK), default=None)
            if near is None and w[0] < x - ACROSS_GUTTER and w[2] - x <= SPLIT_SPILL * (x - w[0]) and " " in text:
                # A row's end that spilled over a narrow gutter ("(25 and part back (4,3,4) up!",
                # the next column's "Shut up! (4,4)" ending), not a notice printed across both
                # (which lies far into the next column): cut at the space nearest the gutter, so
                # the row is not taken for a notice that ends the column (FT 1981).
                spaces = [i for i, c in enumerate(text) if c == " "]
                cut = min(spaces, key=lambda i: abs(w[0] + width * i / len(text) - x))
                if abs(w[0] + width * cut / len(text) - x) <= SPLIT_SLACK and text[:cut].strip() and text[cut:].strip():
                    out.append((w[0], tall[1], x - 1, tall[3], text[:cut].rstrip()))
                    w = tall = (x, tall[1], w[2], tall[3], text[cut:].lstrip())
                    continue
            if near is None:
                if x - w[0] <= ACROSS_GUTTER and w[2] - x > x - w[0]:
                    # Starting just left of the gutter and lying mostly right
                    # of it: a skewed page's right-column line, its left edge
                    # drifted over the straight gutter.
                    w, tall = (x,) + w[1:], (x,) + tall[1:]
                continue
            out.append((w[0], tall[1], x - 1, tall[3], text[:near[1]].rstrip()))
            w = tall = (x, tall[1], w[2], tall[3], text[near[1]:])
        out.append(w)
    return out


def columns(lines, grid, third=None, margin=40, above=None, left=None, split=None, lead=None, right=None, strip=None):
    """The clue columns under the grid (and with `third`, right of it; with
    `above`, over it; with `left`, left of it; with `lead`, first one left of
    it; see windows()): [[(y0, y1, x0,
    x1, text) per line] per column, left to right], each cut where the clues
    stop."""
    gx0, gy0, gx1, gy1 = grid
    bottom = gy0 - 3 if above else right[2] if right else left[2] if left else gy1 + 1.8 * (gx1 - gx0)
    wins = windows(grid, third, margin, above, left, split, lead, right, strip)
    main = [w for w in wins if len(w) == 4]
    reach = gx1 + RIGHT_REACH if above is None and not left and not right and not isinstance(split, tuple) else None
    cols = [[] for _ in wins]
    heights = sorted(w[3] - w[1] for ws in lines for w in ws)
    height = heights[len(heights) // 2] if heights else None
    for ws in lines:
        ws = split_across(ws, [w[1] for w in main[:-1]], height)
        if len(main) < len(wins):
            # The strip's rows: read across its gutters, cut like the others.
            gaps = [w[1] for w in wins[len(main):-1]]
            ws = [w for w in ws if not strip[0] <= w[1] <= strip[1]] + \
                split_across([w for w in ws if strip[0] <= w[1] <= strip[1]], gaps, height)
        for side, (x0, x1, right, top, *foot) in enumerate(wins):
            foot = foot[0] if foot else bottom
            # The lead column's right edge is the next column's left: no
            # overhang.
            over = reach if (side >= (len(lead) - 2 if lead else 0) or not lead) and side < len(main) else None
            part = [w for w in ws if x0 <= w[0] < x1 and top <= w[1] <= foot and (
                w[2] <= right or over and w[2] <= over and w[0] < gx1 - ACROSS_GUTTER)]
            if part:
                text = " ".join(w[4] for w in part)
                if side + 1 < len(main) and min(w[0] for w in part) < x1 - ACROSS_GUTTER \
                        and max(w[2] for w in part) > x1 + ACROSS_GUTTER:
                    # A line printed across both columns, not a clue's ("Prize
                    # Crossword in The Times tomorrow", "The solution to the
                    # Collins Competition ..."): it ends the column like STOP.
                    text = NOTICE
                cols[side].append((min(w[1] for w in part), max(w[3] for w in part),
                                   min(w[0] for w in part), max(w[2] for w in part), text))
    out = []
    for side, col in enumerate(cols):
        col = merge_rows(col)
        kept, last = [], None
        for line in col:
            if kept and (stops(line[4]) or line[4] == NOTICE or line[0] - last > GAP):
                break
            if line[4] == NOTICE:
                continue
            if not re.search(r"[A-Za-z0-9]", line[4]):
                continue  # specks read as marks: no clue text
            heading = numbered_heading(line[4])
            if heading:
                line = line[:4] + (heading,)
            # A heading read badly ("ACRUSS", Gale 1952-04-17's) is the heading, kept: dropped, the
            # list is headless and file_trove_puzzles.heads() puts ACROSS back before the first
            # plain clue number, losing a linked first clue ("1, 9 To give quarter") and with it
            # the tail light, which then no reading lays (Gale 1952-04-17, 1952-09-18, 1954-08-10).
            if not kept and not re.match(r"\W*(across|down)\b", line[4], re.I) and last is None \
                    and not heading_of(line[4]):
                # The column's first line is ACROSS, DOWN or a clue: a stray
                # word the grid's numbers left is not. A column under the
                # grid after the first may open on a clue whose number was
                # lost ("Peer inside the pearly gates").
                carried = side and above is None and not left and (
                    re.match(r"[A-Z][a-z]", line[4]) and len(re.findall(r"[A-Za-z]{2,}", line[4])) >= 3
                    # The rest of the clue the last column ended in, its
                    # count not yet printed ("6 Chewing nuts with tea may"
                    # over "cause lock-jaw (7)").
                    or out and out[-1] and not COUNT_END.search(out[-1][-1][4])
                    and re.match(r"[a-z]", line[4]))
                # A clue's number 1 read as I, l, J, ! or | (tidy() reads it
                # back): "I Very late at night".
                if not re.match(r"\W*(?:\d|[IlJ!|]\s?(?=[A-Z][a-z]))", line[4]) and not carried:
                    continue
            kept.append(line)
            last = line[1]
        out.append(kept)
    return out


#: How far either side of each quarter of the grid's width, as a share of
#: it, a gutter between the 1930 Times' four clue columns may lie.
FOUR_SPAN = 0.06
#: How far under the grid, as a share of its height, the 1930 clues run.
FOUR_DEPTH = 1.2
#: The note under the 1930 clues: "The twenty-eighth crossword puzzle in
#: this series, together with the solution of puzzle No. 27, will appear".
FOUR_STOP = re.compile(r"in\s*this\s*series|will\s*appear|crossword\s*puzzle\s*in\b|solution\s*(?:of|to)\b|puzzle\s*n[o0]\b",
                       re.IGNORECASE)


#: The readers of the 1930 clues: archive.org's words and Tesseract's (tuned
#: on the 1974-99 print) read these columns as junk that outvotes the rest.
FOUR_READERS = ("ch", "en5")


def four_gutters(lines, grid):
    """The three x's between the four clue columns under a 1930 grid: where
    the fewest words (`lines`, every reading's) cross near each quarter."""
    gx0, _, gx1, gy1 = grid
    w = gx1 - gx0
    bottom = gy1 + FOUR_DEPTH * (grid[3] - grid[1])
    return [gutter(lines, (gx0, bottom, gx1, bottom), gy1, gx0 + q * w / 4 - FOUR_SPAN * w,
                   gx0 + q * w / 4 + FOUR_SPAN * w) for q in (1, 2, 3)]


def down_at(lines, grid, gutters):
    """The y of the DOWN heading over the 1930 Times' first two columns,
    the median of every reading's, or None when none read it."""
    gx0, _, _, gy1 = grid
    ys = sorted(w[1] for ws in lines for w in ws
                if gx0 - 40 <= w[0] < gutters[1] and w[1] > gy1 and heading_of(w[4]) == "DOWN")
    return ys[len(ys) // 2] if ys else None


def columns_of_four(lines, grid, gutters, down):
    """The 1930 Times' clues under its grid, as columns() returns them but
    in reading order: ACROSS runs down the first column and on down the
    second over the DOWN heading (printed across both), then DOWN under it
    in the same two columns and on down the third and fourth, which end at
    the previous solution's heading."""
    gx0, gy0, gx1, gy1 = grid
    edges = [gx0 - 40] + list(gutters) + [gx1 + RIGHT_REACH]
    bottom = gy1 + FOUR_DEPTH * (gy1 - gy0)
    heights = sorted(w[3] - w[1] for ws in lines for w in ws)
    height = heights[len(heights) // 2] if heights else None
    cols = [[] for _ in range(4)]
    # Each column ends at the first line over it that FOUR_STOP matches,
    # read whole before any cut at a gutter.
    stops = [bottom] * 4
    for ws in lines:
        if FOUR_STOP.search(" ".join(w[4] for w in ws)):
            x0, x1, y0 = min(w[0] for w in ws), max(w[2] for w in ws), min(w[1] for w in ws)
            for side in range(4):
                if x0 < edges[side + 1] and x1 > edges[side] and y0 > gy1 + 20:
                    stops[side] = min(stops[side], y0 - 2)
    for ws in lines:
        ws = cut_at_gutters(split_across(ruled_apart(ws), gutters, height), gutters)
        for side in range(4):
            part = [w for w in ws if edges[side] <= w[0] < edges[side + 1] and gy1 - 5 <= w[1] <= stops[side]]
            if part:
                cols[side].append((min(w[1] for w in part), max(w[3] for w in part),
                                   min(w[0] for w in part), max(w[2] for w in part), " ".join(w[4] for w in part)))
    kept = []
    for col in cols:
        out, last = [], None
        for line in merge_rows(col):
            if FOUR_STOP.search(line[4]) or (out and line[0] - last > GAP):
                if out:
                    break
                continue
            if heading_of(line[4]) or not re.search(r"[A-Za-z0-9]", line[4]):
                continue
            out.append(line)
            last = line[1]
        kept.append(out)
    def headed(heading, col):
        # The heading on the column's first line's box, so a box drawn
        # round the column's lines (vlm_reader.boxes) is the column's.
        return [col[0][:4] + (heading,)] + col if col else [(gx0, gy1, gx0, gy1, heading)]
    if down is None:
        return [headed("ACROSS", kept[0]), kept[1]]
    over = [[ln for ln in c if ln[0] + ln[1] < 2 * down] for c in kept[:2]]
    under = [[ln for ln in c if ln[0] + ln[1] > 2 * down] for c in kept[:2]]
    return [headed("ACROSS", over[0]), over[1], headed("DOWN", under[0]), under[1], kept[2], kept[3]]


def vlm_four(img, cols, only=None):
    """The VLM's reading of the 1930 clues: each of columns_of_four()'s
    columns (`cols`, every reading's) read on its own, in that order, the
    list headings put back where they open the first and third. `only`:
    the indexes of the columns to read (None: all)."""
    wins = [None] * max(len(c) for c in cols)
    parts = []
    for k, box in enumerate(vlm.boxes(img, wins, cols)):
        if only is not None and k not in only:
            continue
        if k in (0, 2) and k < len(wins):
            parts.append(("ACROSS", "DOWN")[k // 2])
        if box:
            parts.append(vlm.read(vlm.crop(img, box)))
    return "\n".join(p for p in parts if p)


def cut_at_gutters(ws, gutters):
    """`ws` with each word still read across a gutter (two columns' rows
    run into one, "1WinneroftheoGanymedetothe") cut there, at the space
    nearest its share of the characters, or at that share: no notice is
    printed across the 1930 columns but the one under them (FOUR_STOP)."""
    out = []
    for w in ws:
        for x in gutters:
            if not (w[0] < x - ACROSS_GUTTER and w[2] > x + ACROSS_GUTTER) or heading_of(w[4]):
                continue
            at = round(len(w[4]) * (x - w[0]) / (w[2] - w[0]))
            spaces = [m.start() for m in re.finditer(r"\s", w[4]) if abs(m.start() - at) <= 3]
            at = min(spaces, key=lambda k: abs(k - at)) if spaces else at
            out.append((w[0], w[1], x - 1, w[3], w[4][:at].strip()))
            w = (x, w[1], w[2], w[3], w[4][at:].strip())
        out.append(w)
    return out


def ruled_apart(ws):
    """`ws` with each word read across a column rule ("22Thedesert'sone|32
    Split thisaim and") cut at the "|" the rule reads as, each piece's
    x placed by its share of the characters."""
    out = []
    for w in ws:
        parts = re.split(r"\s*\|\s*", w[4])
        if len(parts) < 2:
            out.append(w)
            continue
        width = w[2] - w[0]
        for m in re.finditer(r"[^|]+", w[4]):
            if m[0].strip():
                x0 = w[0] + width * (m.start() + len(m[0]) - len(m[0].lstrip())) / len(w[4])
                out.append((round(x0), w[1], round(w[0] + width * m.end() / len(w[4])), w[3], m[0].strip()))
    return out


#: The rarest two-letter word word_split() cuts out: "me" and "no", never
#: "ut" ("entertainmeut" is a misread, not "entertain me ut").
SHORT_RANK = 1000


def word_split(word):
    """The fewest lexicon words, commonest first on a tie, that `word` is
    run together from ("hadelevenofthese" is "had eleven of these"), or
    None. A lone letter is a word only as "a" or "I", two letters only
    within SHORT_RANK."""
    low, best = word.lower(), [None] * (len(word) + 1)
    best[0] = (0, 0.0, [])
    for i in range(1, len(word) + 1):
        for j in range(max(0, i - 20), i):
            piece = low[j:i]
            if best[j] is None or (len(piece) == 1 and piece not in "ai") or not is_word(piece) \
                    or (len(piece) == 2 and (rank(piece) or SHORT_RANK + 1) > SHORT_RANK):
                continue
            c = (best[j][0] + 1, best[j][1] + math.log(rank(piece) or 10 ** 6), best[j][2] + [word[j:i]])
            if best[i] is None or c[:2] < best[i][:2]:
                best[i] = c
    return best[-1][2] if best[-1] else None


def spaced(text):
    """A reading with the words RapidOCR ran together on the small 1930
    print ("Thesepeopleare", "isno") put apart: a run of letters the
    lexicon lacks that splits whole into its words."""
    def one(m):
        word = m[0]
        if len(word) < 4 or ocr_clues.known(word):
            return word
        parts = word_split(word)
        return " ".join(parts) if parts else word
    # A clue's number run into its first word ("25Holdsan") parts first.
    text = re.sub(r"(?m)^(\W{0,2}\d{1,2}[.,]?)(?=[A-Za-z])", r"\1 ", text)
    # A speck between two words ("flat.and", "for.misdeed"), and a quote or
    # bracket run onto the word before it ("in“The", "sire?(anag.)").
    text = re.sub(r"(?<=[a-z]{2})[.,·](?=[a-z]{2})", " ", text)
    text = clue_text.space_before_quote(text)
    # Half a word broken over a line end ("esta-", "blished") is no run.
    return re.sub(r"(?<![\w\-])[A-Za-z]+(?:'[a-z]+)?(?![\w\-])", lambda m: m[0] if text[:m.start()].endswith(("-\n", "- ")) else one(m), text)


def counted(text, grid):
    """A 1930 column text with each clue's count put after it from the
    scanned grid, as later papers print it, for the parse that ends a clue
    at its count: a clue starts at a line opening on a number that names a
    light of its list above the last clue's; other lines carry it on.

    A clue whose number was lost runs into the clue before it, and the
    count, being the grid's, cannot show it. So the list must name the
    grid's lights in order: a clue followed by one of a later light than
    the next (a light skipped), or by one of its own or an earlier light,
    or ending its list before the list's last light, may hold another's
    text and is dropped, its light and the skipped ones left to the other
    readings or blank. The grid's light list says where a lost number
    was: a line opening on a capital after a clue's full stop, or on a
    misread number holding the next light's ("151 Meta-" for 15), starts
    the next light's clue."""
    lights = {(n, d): len(cells) for (n, d), cells in rg.light_cells(grid).items()}
    sections = []  # [heading, [[number, lines, guessed, dropped]]]
    for line in text.splitlines():
        heading = heading_of(line)
        if heading:
            sections.append([heading, []])
            continue
        if not sections:
            continue
        section, clues = sections[-1][0].lower(), sections[-1][1]
        last = clues[-1][0] if clues else 0
        nxt = min((n for n, d in lights if d == section and n > last), default=None)
        # The number, maybe run into its first word: "25Recipient", "21.Measures".
        m = OPENING_NUMBER.match(line)
        m = m if m and re.search(r"\d", m[1]) else None
        read = [n for n in (ftp.readings(m[1]) if m else ()) if (n, section) in lights]
        nums = sorted(n for n in read if n > last)
        # A number read with a speck ("151", "128") holding the next light's.
        speck = OPENING_SPECK.match(line)
        if nums:
            clues.append([nums[0], [line[m.end():]], False, False])
        elif read and clues:
            # A number at or before the last clue's: this list is out of
            # step with the grid here. When it is the last clue's guessed
            # number, the guess split one clue in two and this is its own.
            clues[-1][3] = True
            if clues[-1][2] and last in read:
                clues.append([last, [line[m.end():]], False, False])
            else:
                clues[-1][1].append(line)
        elif speck and nxt and str(nxt) in speck[1]:
            clues.append([nxt, [line[speck.end():]], False, False])
        elif re.match(r"\W{0,2}[A-Z]", line) and nxt and (
                re.search(r"[.!?][\"'\u2019\u201d)]?$", clues[-1][1][-1]) if clues else True):
            # A capital after a clue's full stop, or opening the list,
            # starts the next clue, its number lost ("light.. /
            # Slender-waisted."): the next light's.
            clues.append([nxt, [line.strip()], True, False])
        elif clues:
            clues[-1][1].append(line)
    out = []
    for heading, clues in sections:
        out.append(heading)
        order = sorted(n for n, d in lights if d == heading.lower())
        for k, (n, _, _, _) in enumerate(clues):
            after = [x for x in order if x > n]
            follows = clues[k + 1][0] if k + 1 < len(clues) else None
            if after[:1] != [follows] if follows else after:
                clues[k][3] = True
        # A guessed number counts on from the clue before, so a break after
        # it may lie anywhere back to the last number read: the clues
        # between are dropped with it.
        for k in range(len(clues) - 1, 0, -1):
            if clues[k][3] and clues[k][2]:
                clues[k - 1][3] = True
        out += [f"{n} " + "\n".join(lines) + f" ({lights[(n, heading.lower())]})"
                for n, lines, _, bad in clues if not bad]
    return "\n".join(out)


#: How far either side of the grid's middle, as a share of its width, the
#: gutter between the two clue columns under the grid may lie.
UNDER_SPAN = 0.1


#: Where, as shares of the grid's width from its left edge, the gutter of the
#: 1950-59 Times' two columns under the grid may lie: the first column is the
#: narrower (the 1957-03-04 page: text to 0.33, the second from 0.39 of 720px),
#: so the usual window about the grid's middle began inside the second.
UNDER_FIFTIES = (0.25, 0.45)


def under_gutter(lines, grid, shares=None):
    """The x between the two clue columns under the grid: where the fewest
    words (`lines`, every reading's) cross near the grid's middle (or in
    `shares` of the grid's width from its left edge). A paper's
    columns need not split at the grid's middle, and a right-hand clue
    whose number starts left of it is read into the left column's row."""
    gx0, _, gx1, gy1 = grid
    mid, span = gx0 + (gx1 - gx0) / 2 - 10, UNDER_SPAN * (gx1 - gx0)
    if shares:
        mid, span = gx0 + (gx1 - gx0) * sum(shares) / 2, (gx1 - gx0) * (shares[1] - shares[0]) / 2
    bottom = gy1 + 1.8 * (gx1 - gx0)
    return gutter(lines, (gx0, bottom, gx1, bottom), gy1, mid - span, mid + span)


#: How far over the grid's top, and under its foot as a share of its height,
#: clue columns left of the grid may run.
LEFT_RISE, LEFT_DROP = 80, 0.3


def left_bottom(grid):
    return grid[3] + LEFT_DROP * (grid[3] - grid[1])


def left_columns(lines, grid):
    """(x0, gutter, bottom) of the two clue columns left of the grid (the
    FT's Monday Prize): from a grid's width left of it, split where the
    fewest words (`lines`, every reading's) cross."""
    gx0, gy0, gx1, _ = grid
    x0 = max(0, gx0 - (gx1 - gx0) - 60)
    floor = left_bottom(grid)
    lo, hi = x0 + 0.3 * (gx0 - x0), x0 + 0.7 * (gx0 - x0)
    return x0, gutter(lines, (lo, floor, hi, floor), gy0 - LEFT_RISE, lo, hi), floor


#: How far under the grid's foot, as a share of its height, the one clue
#: column left of a Times Saturday prize grid runs (DOWN goes on past the
#: grid, beside the solution grids under it).
COLUMN_DROP = 1.1


def left_column(lines, grid, margin=60):
    """(x0, None, bottom) of the one clue column left of a grid whose title
    is over it (the 1987 Times Saturday prize: ACROSS level with the grid's
    top, DOWN running on under its foot, the last puzzles' solutions under
    the grid), from `margin` left of the column's heading; None when no
    ACROSS or DOWN alone on its line (`lines`, the djvu text's) lies within
    a grid's width left of the grid, from LEFT_RISE over its top to its
    foot (a heading under the grid, outdented or not, heads the columns
    under it)."""
    gx0, gy0, gx1, gy1 = grid
    gh = gy1 - gy0
    heads = [ws[0] for ws in lines if len(ws) == 1 and HEADING_ALONE.match(ws[0][4])
             and gx0 - (gx1 - gx0) <= ws[0][0] and ws[0][2] < gx0
             and gy0 - LEFT_RISE <= ws[0][1] < gy1]
    if not heads:
        return None
    return max(0, min(w[0] for w in heads) - margin), None, gy1 + COLUMN_DROP * gh


#: The 2014 Times pages (Gale, from about 2014-02): the grid at the page's
#: foot with the two clue columns right of it, the second ending
#: RIGHT_SPAN of the grid's width from its right edge (a rule and the
#: solution grid, or an advert box, start just past it), the columns' gutter
#: between RIGHT_GUTTER of that span; the clues rise RIGHT_RISE over the
#: grid's top (the headings) and run RIGHT_DROP of its height under its foot.
RIGHT_SPAN, RIGHT_GUTTER, RIGHT_RISE, RIGHT_DROP = 1.055, (0.35, 0.65), 50, 0.3
#: How much of that strip must be ink for it to hold clues.
RIGHT_INK = 0.03


#: The 2005 to 2006-10 Times pages: the grid at the page's foot left of its
#: title (locate_grid's "left"), the clues right of it out to this much of the
#: grid's width past its right edge.
RIGHT_SPAN_LEFT = 1.45


def right_columns(img, grid, span=RIGHT_SPAN):
    """(x1, bottom) of the two clue columns right of `grid`, or None when the
    clues are not there: they are only when the page ends too soon under the
    grid for clues (1.8 grids' widths, the layout every other page has) and
    the strip right of the grid, as wide as `span`, is inked like text."""
    gx0, gy0, gx1, gy1 = grid
    gw = gx1 - gx0
    x1 = int(gx1 + span * gw)
    if x1 > img.width or img.height - gy1 >= 1.2 * gw:
        return None
    bottom = int(gy1 + RIGHT_DROP * (gy1 - gy0))
    strip = img.crop((gx1 + 5, gy0, x1, min(img.height, bottom))).convert("L")
    hist = strip.histogram()
    if sum(hist[:128]) < RIGHT_INK * strip.width * strip.height:
        return None
    return x1, bottom


#: How far in from the right clue columns' far edge (right_columns()), as a
#: share of the grid's width, right_foreign() looks for other print the
#: window cut into.
RIGHT_FOREIGN = 0.2


def right_foreign(rapid, grid, right):
    """(right, rapid): `right` (right_columns()'s (x1, bottom)) with x1 pulled
    in to the gutter before the column of other print its window reached
    into (crop_window.foreign_edge, off each reader's words: the rightmost
    any finds, so one word-level reading's chance run of blanks inside the
    clues cuts nothing), and every reading (`rapid`: {reader: [[word]]}) without the
    boxes past it; as they were when none did. right_columns()' span is a
    share of the grid's width, so on the 2005 Times page it ended inside the
    advert or solution box beside DOWN, whose line ends read into the clues
    level with them (20 down's "Books Fi") and left the last clue on no light."""
    x1, bottom = right
    reach = RIGHT_FOREIGN * (grid[2] - grid[0])
    cuts = [c for c in (crop_window.foreign_edge([w for ws in lines for w in ws], x1, reach)
                        for lines in rapid.values()) if c is not None and c > grid[2]]
    if not cuts:
        return right, rapid
    cut = max(cuts)
    return (cut, bottom), {k: [ws for ws in lines if ws and ws[0][0] < cut] for k, lines in rapid.items()}


def right_or_over(img, grid, right_ok=True):
    """(right, over) for a grid under its title: right_columns() when the
    clues lie right of it, else overhang(), never both. A page that ends
    that soon under the grid has no room for three columns, and the
    "Yesterday's solution" box under its grid is inked like a third column's
    text: overhang() alone read it as one (the Feb to May 2014 Times, whose
    clues were then cropped from under the grid and found no lists)."""
    right = right_columns(img, grid) if right_ok else None
    return right, (None if right else overhang(img, grid))


def right_gutter(lines, grid, right):
    """`right` (right_columns()) with the x between its two columns: where
    the fewest words (`lines`, every reading's) cross."""
    gx0, gy0, gx1, _ = grid
    x1, bottom = right
    lo, hi = gx1 + RIGHT_GUTTER[0] * (x1 - gx1), gx1 + RIGHT_GUTTER[1] * (x1 - gx1)
    return x1, gutter(lines, (lo, bottom, hi, bottom), gy0 - RIGHT_RISE, lo, hi), bottom


#: The Times' three clue columns under a grid (Gale, ~2006-12 to 2013, where
#: a box of text sits beside the grid): they are each a third of the span from
#: the grid's left edge to where the ink under it ends (overhang()), so the
#: third column overhangs the grid. The band under the grid's foot, from
#: OVER_BAND of the grid's width right of its edge, is inked like text only
#: there (a two-column page's margin is clean paper and binder holes).
OVER_BAND, OVER_DEPTH, OVER_INK = (0.08, 0.3), (0.05, 0.6), 0.03
#: How far past the grid's edge, as a share of its width, the third column
#: may end; the window (px) and ink share that make an x a column's.
OVER_REACH, OVER_WINDOW, OVER_COLUMN_INK = 0.7, 9, 0.04
#: How far either side of a third of the span, as a share of the grid's
#: width, a gutter between the three columns may lie.
OVER_GUTTER = 0.06


def overhang(img, grid):
    """The x where a third clue column under `grid` ends (it overhangs the
    grid's right edge), or None for the usual two columns: the band right of
    the grid's edge and under its foot is inked like text (OVER_INK of it)
    and the page leaves room there."""
    gx0, gy0, gx1, gy1 = grid
    gw = gx1 - gx0
    box = (int(gx1 + OVER_BAND[0] * gw), int(gy1 + OVER_DEPTH[0] * gw),
           int(gx1 + OVER_BAND[1] * gw), int(gy1 + OVER_DEPTH[1] * gw))
    if box[2] > img.width or box[3] > img.height:
        return None
    band = img.crop(box).convert("L")
    if sum(band.histogram()[:128]) < OVER_INK * band.width * band.height:
        return None
    # Where the columns end: the last x whose neighbourhood is inked like
    # text, out to OVER_REACH (a speck or a punched hole is not a column).
    from PIL import Image
    x0, far = int(gx1 + OVER_BAND[0] * gw), min(img.width, int(gx1 + OVER_REACH * gw))
    strip = img.crop((x0, box[1], far, int(gy1 + OVER_DEPTH[1] * gw))).convert("L").point(lambda v: 255 if v < 128 else 0)
    ink = [v / 255 for v in strip.resize((strip.width, 1), Image.BOX).getdata()]
    ends = [x for x in range(len(ink)) if sum(ink[x:x + OVER_WINDOW]) >= OVER_WINDOW * OVER_COLUMN_INK]
    return x0 + ends[-1] + OVER_WINDOW if ends else None


def over_gutters(lines, grid, x1):
    """(first, second, x1): the two x's between the three clue columns under
    `grid` that end at `x1` (overhang()), each where the fewest words
    (`lines`, every reading's) cross near a third of the span."""
    gx0, _, gx1, gy1 = grid
    gw = gx1 - gx0
    bottom = gy1 + 1.8 * gw
    out = []
    for k in (1, 2):
        mid = gx0 + k * (x1 - gx0) / 3 - 10
        out.append(gutter(lines, (gx0, bottom, gx1, bottom), gy1, mid - OVER_GUTTER * gw, mid + OVER_GUTTER * gw))
    return out[0], out[1], x1


def lead_column(title, grid, margin=40):
    """(x0, top) of the clue column under a title printed left of its grid
    (the 1983-86 FT: ACROSS and the first DOWN clues there, the rest in the
    two columns under the grid): the column is centred under the title and
    ends at the grid's left edge, so it starts as far left of the title's
    middle, less `margin`."""
    cx = (title[0] + title[2]) / 2
    return max(0, int(2 * cx - grid[0]) - margin), title[3]


#: How far right of its title's left edge, as a share of the grid's width,
#: a grid under its title starts when a clue column is printed left of it.
TITLE_INDENT = 0.15


#: How wide a gap (a share of the grid's width) the title's words may leave
#: when title_left() walks its line leftward, and the ink share of a pixel
#: column that makes it the line's.
TITLE_GAP, TITLE_COL_INK = 0.07, 0.04


def title_left(img, title, grid):
    """`title` with its left edge moved out to where its printed line starts: a
    title the readers read from its second word ("CROSSWORD PUZZLE NO. 10,136"
    of "THE TIMES CROSSWORD ...", the 1962-11-02 Times) sits level with its grid,
    so indented_column() found no column left of it and the clue column was
    never cropped (every read there was refused "no reading parses")."""
    from PIL import Image
    x0, y0, x1, y1 = title
    gap = int(TITLE_GAP * (grid[2] - grid[0]))
    band = img.crop((0, y0, x0, y1)).convert("L").point(lambda v: 255 if v < 128 else 0)
    if band.width < 1:
        return title
    ink = [v / 255 for v in band.resize((band.width, 1), Image.BOX).getdata()]
    edge, blank = x0, 0
    for x in range(x0 - 1, -1, -1):
        if ink[x] >= TITLE_COL_INK:
            edge, blank = x, 0
        else:
            blank += 1
            if blank > gap:
                break
    return (edge, y0, x1, y1)


def indented_column(title, grid, margin=40):
    """(x0, top) of the clue column left of a grid under its title, set in
    from the title's left edge by TITLE_INDENT or more (the Times to
    1967-04-10: ACROSS and the first DOWN clues there, the rest in the
    columns under the grid, as lead_column()'s), else None. The column's
    numbers stand out left of the title by up to half the indent."""
    indent = grid[0] - title[0]
    if indent < TITLE_INDENT * (grid[2] - grid[0]):
        return None
    return max(0, int(title[0] - indent / 2) - margin), title[3]


#: Ink share of a pixel column under which it is a gutter's, the narrowest
#: gutter (pixels, at a 4300px page) trimmed_lead() trusts, and how far into
#: the column's span (a share of it) it looks for one.
GUTTER_INK = 0.1
GUTTER_MIN = 6
#: The widest rule (pixels) a gutter may hold.
GUTTER_RULE = 5
#: and the widest a rule printed heavy may be when its pixel columns average
#: is inked at least GUTTER_RULE_INK down the window (the 1948-11-10 Times:
#: a 7px rule between the small ads and the clue column, its two margins
#: each under GUTTER_MIN wide, so no gutter was found and the ad's line ends
#: ran into the ACROSS list: no list parsed).
GUTTER_RULE_THICK = 8
GUTTER_RULE_INK = 0.3
GUTTER_SPAN = 0.4
#: The print left of a gutter is a column of text (a share of GUTTER_DENSE
#: ink over GUTTER_LEFT pixels at least), not the sparse numbers' margin the
#: clue column hangs its text from (the 1951 Times' gap after "12").
GUTTER_LEFT = 40
GUTTER_DENSE = 0.12
#: and at least this share of those pixel columns carry ink: the margin
#: before a column of numbers is blank in part of them.
GUTTER_SOLID = 0.75


def edge_candidates(img, grid, lead):
    """[x]: the gutters left and right of lead's x0 (crop_window), the
    window's other left edges when its own fails its check."""
    x0, top = lead
    # Reach 500, not 300: a 1947 Times page with ACROSS and DOWN in two columns
    # left of the grid has its lead edge at the gutter between them, and the
    # ACROSS column's own left gutter is 350px further left (times-5369).
    return crop_window.edge_candidates(img, (max(0, x0 - 600), top, grid[0], grid[3]), x0, reach=500)


def far_edges(img, box, nominal):
    """[x]: the gutters near `nominal` with print left of them only (the far
    edge of a clue column), nearest first, the window's other right edges
    when its own fails its check."""
    return crop_window.edge_candidates(img, box, nominal, side="left")[1:]


def trimmed_lead(img, grid, lead):
    """`lead` (lead_column()'s (x0, top)) with x0 moved right to the gutter
    between the clue column and the column of print left of it, when its
    window reaches into that neighbour: lead_column() centres the window under
    the title, which on the 1945-49 Times pages starts it 100px or more left
    of the clue column (the 1949-11-19 ACROSS column reads with the small ads'
    line ends running through it, and no list parses). The gutter is the
    first run of GUTTER_MIN pixel columns with next to no ink, after dense print (from
    the title's foot to the grid's foot) in the first GUTTER_SPAN of the
    window; with none, `lead` stands."""
    import numpy as np
    x0, top = lead
    edge = grid[0]
    if edge - x0 < 200 or grid[3] <= top:
        return lead
    ink = np.asarray(img.crop((x0, top, edge, grid[3])).convert("L")) < 128
    share = ink.mean(axis=0)
    blank = share < GUTTER_INK
    last = GUTTER_SPAN * len(share)
    # A thin rule inside the gutter (inked down part of its height) does not
    # break it: gaps of GUTTER_RULE pixels or less between blank runs close;
    # failing that, a heavy rule's (GUTTER_RULE_THICK) too.
    best = None
    for thick in (False, True):
        runs, i = [], 0
        while i < len(blank):
            if not blank[i]:
                i += 1
                continue
            j = i
            while j < len(blank) and blank[j]:
                j += 1
            gap = i - runs[-1][1] if runs else 0
            if runs and (gap <= GUTTER_RULE or (thick and gap <= GUTTER_RULE_THICK
                                                and share[runs[-1][1]:i].mean() >= GUTTER_RULE_INK)):
                runs[-1][1] = j
            else:
                runs.append([i, j])
            i = j
        for lo, hi in runs:
            if lo >= last:
                break
            left = share[max(lo - GUTTER_LEFT, 0):lo]
            if hi - lo >= GUTTER_MIN and len(left) == GUTTER_LEFT and left.mean() >= GUTTER_DENSE \
                    and (left >= GUTTER_INK).mean() >= GUTTER_SOLID:
                best = hi
                break
        if best:
            break
    return (x0 + best - 2, top) if best else lead


#: The share of the grid's width a lead window must reach to hold two columns.
LEAD_TWO = 0.75


def lead_split(lines, grid, lead, margin=40):
    """`lead` (lead_column()) with the x between it and the column under the
    grid: where the fewest words (`lines`, every reading's) under the grid
    cross, from `margin` left of the grid's edge (where that column's numbers
    start, outdented) to just inside it."""
    gx0, _, gx1, gy1 = grid
    bottom = gy1 + 1.8 * (gx1 - gx0)
    edge = gutter(lines, (gx0, bottom, gx1, bottom), gy1, gx0 - margin, gx0 + 10)
    # A window nearly as wide as the grid holds two columns (the 1947 Times:
    # ACROSS, then DOWN, both left of the grid): split it where the fewest
    # words of its height cross.
    if edge - lead[0] >= LEAD_TWO * (gx1 - gx0):
        mid = gutter(lines, (lead[0], gy1, edge, gy1), lead[1], lead[0] + 0.3 * (edge - lead[0]),
                     lead[0] + 0.7 * (edge - lead[0]))
        return lead + (edge, mid)
    return lead + (edge,)


def read_cache(cache_path):
    """The JSON a reader's cache file holds, or None when it is missing or
    unreadable: a read killed mid-write (rc=-9) left an empty file, and
    every later one of the page died on it (JSONDecodeError) instead of
    reading the page again. band_words (the scan's heading bands, the
    JSONDecodeError seen in scan_unit) still reads its cache bare: a change
    there moves scan_key and rescans every Gale edition."""
    try:
        return json.loads(cache_path.read_text())
    except (OSError, ValueError):
        return None


def write_cache(cache_path, data):
    """`data` as JSON at `cache_path`, whole or not at all (os.replace), so a
    reader killed mid-write leaves no half file for read_cache to refuse."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, cache_path)


def rapid_lines(img, grid, which, cache_path, third=None, margin=40, above=None, left=None, lead=None, x0=None,
                right=None):
    """One recogniser's reading of the page under the grid (RapidOCR's, or
    Tesseract's for a TESS_MODELS reader), as djvu-style lines of one word each, in page
    coordinates; cached as JSON with the crop it read, so a reading of another
    crop is read again (a bare list kept no crop and is used as it stands).
    With `left`, (x0, bottom), the crop is left of the grid instead, from x0
    and LEFT_RISE over the grid's top down to `bottom`. With `above` (the
    clues' top over the grid), `x0` is where they start (clues_left())."""
    gx0, gy0, gx1, gy1 = grid
    gw = gx1 - gx0
    box = (max(0, gx0 - margin), gy1, min(img.width, gx1 + RIGHT_REACH), min(img.height, int(gy1 + 1.8 * gw)))
    if third:
        box = (box[0], min(gy1, third[1]), min(img.width, gx1 + 15 + third[0]), box[3])
    if above is not None:
        box = (max(0, int(gx0 - margin if x0 is None else x0)), max(0, int(above)), min(img.width, gx1 + OVERHANG), gy0)
    if left:
        box = (max(0, int(left[0])), max(0, gy0 - LEFT_RISE), gx0, min(img.height, int(left[1])))
    if lead:
        box = (max(0, int(lead[0])), max(0, int(lead[1])), box[2], box[3])
    if right:
        box = (gx1 + 5, max(0, gy0 - RIGHT_RISE), right[0], min(img.height, right[1]))
    cached = read_cache(cache_path)
    others = []
    if cached is not None:
        if isinstance(cached, list):
            return [[tuple(w)] for w in cached]
        try:
            if tuple(cached["box"]) == box:
                return [[tuple(w)] for w in cached["words"]]
            # A page read from several windows (read_page's alts) keeps each
            # window's reading: one box per file made every re-run read the
            # windows again, each overwriting the last.
            for o in cached.get("more", ()):
                if tuple(o["box"]) == box:
                    return [[tuple(w)] for w in o["words"]]
            others = [{"box": cached["box"], "words": cached["words"]}, *cached.get("more", ())][:MORE_WINDOWS]
        except (KeyError, TypeError):
            others = []  # an unreadable cache is a miss
    crop = img.crop(box)
    if lead:
        # The grid inside the crop is blanked: its numbers are no clue's.
        crop.paste("white", (gx0 - box[0], gy0 - box[1], gx1 - box[0], gy1 - box[1]))
    words = [(x0 + box[0], y0 + box[1], x1 + box[0], y1 + box[1], t)
             for x0, y0, x1, y1, t in read_words(crop, which)]
    write_cache(cache_path, {"box": box, "words": words, **({"more": others} if others else {})})
    return [[w] for w in words]


#: How many other windows' readings a reader's cache file keeps besides the last.
MORE_WINDOWS = 8


def glued_a(line):
    """`line` with a clue's opening "A" run into the next word parted:
    "15 Adanger out east" is "15 A danger out east", unless the whole is a
    misspelling of a commoner word ("Arived"). A word the lexicon lacks
    (is_word's closed list: "whore", "togo") has no rank, and ranks below
    every word it has. The lexicon is why this is the archive filer's hook
    into clue_text.tidy_ocr_clues."""
    glued = re.match(r"^(\d{1,2}(?:,\s?\d{1,2})*\s+)A([a-z]{3,})\b", line)
    word = glued and glued.group(2)
    if glued and is_word(word) and not is_word("a" + word) and not any(
            (rank(e) or 10 ** 9) < (rank(word) or 10 ** 9) for e in edits("a" + word) if e != word):
        return f"{glued.group(1)}A {line[glued.end(1) + 1:]}"
    return line


def tidy(text):
    """A column text with OCR's commonest slips in the print's shape undone
    (clue_text.tidy_ocr_clues, the one pipeline every OCR source shares): a
    brace or square bracket read for a round one, a clue number run into
    its first word, and a number lost altogether (a line starting a word
    straight after a line that ended on a count) marked "?", which
    file_trove_puzzles.match places by the grid alone."""
    return clue_text.tidy_ocr_clues(text, line_hook=glued_a)


#: {column text: its parse's answer}: the readers' vote asks parse of the same few
#: column texts once per light (readings_for: 779 lights x 4 readings on a Times
#: page, 2846 parses of ~30 texts, 108 of the read's 257 CPU seconds), and the
#: window passes of one page read the same texts again. Bounded, so a pass over
#: many pages keeps no more than the last few; read-side only (scan() never parses).
_PARSED = {}
PARSED_KEEP = 64


def parse(text):
    """({"across": [...], "down": [...]}, None) or (None, why) for a column text.
    Each call has its own copy, as the parse made afresh would be: callers edit it."""
    got = _PARSED.get(text)
    if got is None:
        if len(_PARSED) >= PARSED_KEEP:
            _PARSED.pop(next(iter(_PARSED)))
        got = _PARSED[text] = parse_text(text)
    return copy.deepcopy(got)


def parse_text(text):
    """parse() made afresh."""
    secs = ftp.sections(tidy(text))
    if secs is None:
        return None, "no ACROSS and DOWN lists under the grid"
    parsed = {}
    for direction, t in secs.items():
        parsed[direction], why = ftp.clues(t)
        if why:
            return None, f"{direction} clues do not parse: {why}"
    return clue_repair.split_run_on(parsed)[0], None


def merge_rows(col):
    """One line per printed row: pieces whose middles fall inside each other's
    height (a clue number read apart from its words) joined left to right."""
    rows = []
    for piece in sorted(col, key=lambda l: (l[0] + l[1]) / 2):
        mid = (piece[0] + piece[1]) / 2
        # The row's band is all its pieces': "Am-" read apart from
        # "understood" and both above "1 Historian" are one printed row.
        if rows and min(p[0] for p in rows[-1]) <= mid <= max(p[1] for p in rows[-1]):
            over = [p for p in rows[-1] if min(p[3], piece[3]) - max(p[2], piece[2])
                    > 0.5 * (piece[3] - piece[2])]
            if not over:
                rows[-1].append(piece)
            elif (mid > max(p[1] for p in rows[-1]) - 0.5 * (piece[1] - piece[0])
                  and not any(similar(p[4], piece[4]) > 0.5 or piece[4] in p[4] for p in over)):
                # Under the row, not beside it: a short last line ("turn
                # (6)") whose box the line above overhangs.
                rows.append([piece])
            # Else the OCR's second copy of words it already has: dropped.
        else:
            rows.append([piece])
    out = []
    for r in rows:
        r.sort(key=lambda l: l[2])
        texts = [l[4] for l in r]
        for k in range(len(r) - 1):
            # A box cut through a word reads its first letters again at its
            # end, where the next box reads the whole word (No 3's "45.
            # Insert an A and t" beside "this is what every"): dropped.
            head, _, last = texts[k].rpartition(" ")
            first = r[k + 1][4].split(" ", 1)[0]
            if (head and r[k][3] > r[k + 1][2] and last.isalpha() and first.isalpha()
                    and len(last) < len(first) and first.lower().startswith(last.lower())):
                texts[k] = head
        out.append((min(l[0] for l in r), max(l[1] for l in r), r[0][2], max(l[3] for l in r),
                    " ".join(texts)))
    return out


def column_text(cols):
    return "\n".join(line[4] for col in cols for line in col)


#: The share of the scanned grid's lights that clues must lie on, each by its
#: own number and count, for the grid to stand without the rest.
LOOSE_SHARE = 0.8


#: Two clues read as one: a count, or a clue's number and capital, inside the
#: text. Never laid by position, where the count that ends it proves nothing.
RUN_ON = re.compile(r"\(\s*\d|[?!.,;)]\s+\d{1,2}\s+[A-Z]")


def lay_loose(parsed, grid, taken=None):
    """({light: (text, enumeration, group)}, [clues not laid]): each clue laid
    alone on the light its number names in its list's direction, when its
    number reads one way that names a light not yet taken and one of its
    count readings fills that light; a linked clue on the lights its numbers
    name, when one count fills them all. "See" clues are not laid.
    With `taken` (the lights every reading laid by number), clues whose
    numbers were lost or misread also take the lights their laid neighbours
    leave between them, one each in order: the lights outside `taken`, or
    failing that every light this reading left free, when there are as many
    lights as clues and each count fills its light."""
    lights = rg.light_cells(grid)
    out, bad = {}, []
    for direction in ("across", "down"):
        at = {}  # the clue's place in its list -> the light number it took
        for k, clue in enumerate(parsed[direction]):
            if len(clue["tokens"]) > 1 and clue["see"] is None:
                # A linked clue ("9 & 12"): each number names one free light
                # in the list's direction, and one count fills them all.
                # The tails read "See 9", as the paper's own files have it.
                names = [[n for n in tok if (n, direction) in lights and f"{n}-{direction}" not in out]
                         for tok in clue["tokens"]]
                ids = [f"{ns[0]}-{direction}" for ns in names if len(ns) == 1]
                cells = sum(len(lights[(int(i.split("-")[0]), direction)]) for i in ids)
                fits = [e for e in clue["enums"] if ftp.count(e) == cells]
                if len(ids) == len(names) == len(set(ids)) and len(fits) == 1:
                    out[ids[0]] = (clue["text"], fits[0], ids)
                    for tail in ids[1:]:
                        out[tail] = (f"See {ids[0].split('-')[0]}", None, None)
                    at[k] = int(ids[0].split("-")[0])
                else:
                    bad.append(f"{direction} {[sorted(t) for t in clue['tokens']]}")
                continue
            names = [n for n in clue["tokens"][0]
                     if (n, direction) in lights and f"{n}-{direction}" not in out]
            if len(clue["tokens"]) != 1 or clue["see"] is not None or len(names) != 1:
                bad.append(f"{direction} {sorted(clue['tokens'][0])}")
                continue
            lid = f"{names[0]}-{direction}"
            fits = [e for e in clue["enums"] if ftp.count(e) == len(lights[(names[0], direction)])]
            if len(fits) != 1:
                bad.append(lid)
                continue
            out[lid] = (clue["text"], fits[0], None)
            at[k] = names[0]
        # Clues whose numbers were lost or misread ("Made to smile ... (6)"
        # or "74 Made ..." between 1 and 9, or after the list's last laid
        # clue) take the lights their laid neighbours in the list leave free
        # between them, in order, when there are as many of each and every
        # count fills its light.
        clues = parsed[direction]
        if taken is None:
            continue
        laid_at = sorted(at)
        for lo_k, hi_k in zip([-1] + laid_at, laid_at + [len(clues)]):
            between = list(range(lo_k + 1, hi_k))
            if not between or any(len(clues[j]["tokens"]) != 1 or clues[j]["see"] is not None
                                  or RUN_ON.search(clues[j]["text"]) for j in between):
                continue
            lo = at[lo_k] if lo_k >= 0 else 0
            hi = at[hi_k] if hi_k < len(clues) else math.inf
            # The lights no reading laid by number, else every light this
            # reading left free: one clue a light either way.
            free = [sorted(n for (n, d) in lights if d == direction and lo < n < hi
                           and f"{n}-{d}" not in out and (f"{n}-{d}" not in taken or every))
                    for every in (False, True)]
            free = next((f for f in free if len(f) == len(between)), None)
            if free is None:
                continue
            fits = [[e for e in clues[j]["enums"] if ftp.count(e) == len(lights[(n, direction)])]
                    for j, n in zip(between, free)]
            if all(len(f) == 1 for f in fits):
                for j, n, f in zip(between, free, fits):
                    out[f"{n}-{direction}"] = (clues[j]["text"], f[0], None)
    return out, bad


# ------------------------------------------------------------ the puzzle

def build(number, day, grid, how, laid, edition, leaf, series=SERIES, name=None, url=None, printed=None):
    """The puzzle filed from `laid`; `printed` ({light: tokens}) is each
    clue's `asPrinted` (ocr_clues.printed_alike)."""
    lights = rg.light_cells(grid)
    by_id, entries = {}, []
    for (n, d), cells in lights.items():
        e = {"number": n, "direction": d, "position": {"x": cells[0][1], "y": cells[0][0]},
             "length": len(cells)}
        entries.append(e)
        by_id[entry_id(e)] = e
    seps, groups = {}, {}
    # The counts the grid gave (ocr_clues.GridCount): no reader's survived.
    from_grid = {lid for lid, (_, enum, _) in laid.items() if isinstance(enum, ocr_clues.GridCount)}
    for lid, (text, enum, group) in list(laid.items()):
        # A ";" between counts that fill the light is a misread ",".
        enum = enumeration.comma_misread(enum, sum(by_id[i]["length"] for i in group or [lid] if i in by_id))
        laid[lid] = (text, enum, group)
        if enum:
            try:
                seps.update(separators(group or [lid], by_id, enum))
            except SystemExit:
                laid[lid] = (text, None, None)
                continue
            if group:
                groups[lid] = group
    # A linked light with no clue of its own ("1,4 Ancient ..." prints none
    # for 4) reads "See 1", as the paper's own files have it.
    laid = dict(laid)
    for lid, group in groups.items():
        for tail in group[1:]:
            if not (laid.get(tail) or ("",))[0].strip():
                laid[tail] = (f"See {lid.split('-')[0]}", None, None)
    from fetch_puzzle import has_words, source_clue
    pid = series_meta.puzzle_id(series, number)
    for e in entries:
        lid = entry_id(e)
        text, enum, _ = laid.get(lid, ("", None, None))
        text = source_clue(pid, lid, text)
        # A reading that kept only a count ("(8)") has lost the clue: file it
        # as the blank it is, not as words that are really an enumeration.
        if not has_words(text):
            text = ""
        line = f"{text} ({enum})" if enum else text
        e["clue"] = enumeration.clue(line, separators=seps.get(lid), missing=not text.strip())
        if kept := [t for t in (printed or {}).get(lid, ()) if t in text.split()]:
            e["clue"]["asPrinted"] = kept
        if enum and lid in from_grid and e["clue"].get("enumeration") == str(enum):
            e["clue"]["countFrom"] = "grid"
        if lid in groups:
            e["group"] = groups[lid]
        e["solution"] = None
    return {
        "id": pid,
        "number": number,
        "series": series,
        "name": name or f"Times cryptic crossword No {number:,}",
        "date": day.isoformat(),
        "dimensions": {"cols": len(grid[0]), "rows": len(grid)},
        "source": {"url": url or PAGE_URL.format(edition=edition, leaf=leaf),
                   "gridOrigin": "published" if how == "image" else "reconstructed"},
        "entries": entries,
    }


# ------------------------------------------------------------ an edition

def edition_dirs(cache=CACHE, paper=None):
    """Every cached edition of `paper` (the Times by default), the years taken in turn (each year's first
    edition, then each year's second, ...), so a capped run reaches every
    decade the fetch has. On the media disk, off the edition manifests
    (media_manifest.edition_rows), never a listing of it."""
    papers = run_papers(paper or TIMES)
    if media_manifest.on_media(cache):
        rows = media_manifest.edition_rows()
        # edition_rows keeps its dict (the same object) while neither fold gained a key, and
        # this reads only the keys: the same dict and length is the same answer, not a re-sort of ~25k paths.
        stamp = (str(cache), tuple(p.key for p in papers))
        hit = _EDITION_DIRS.get(stamp)
        if hit is not None and hit[0] is rows and hit[1] == len(rows):
            return list(hit[2])
        by_item, ours = {}, {}
        for rel in rows:
            item, _, ed = rel.partition("/")
            if not ed:
                continue
            mine = ours.get(item)
            if mine is None:
                mine = ours[item] = any(p.item.match(item) for p in papers)
            if mine:
                by_item.setdefault(item, []).append(ed)
        # One item's editions sort as their names do (one parent): strings, not ~25k Paths compared.
        years = [[base / ed for ed in sorted(eds)] for base, eds in
                 ((Path(cache) / item, eds) for item, eds in sorted(by_item.items()))]
    else:
        stamp = None
        years = _edition_years_listed(cache, papers)
    out = []
    for k in range(max(map(len, years), default=0)):
        out += [y[k] for y in years if k < len(y)]
    if stamp is not None:
        _EDITION_DIRS[stamp] = (rows, len(rows), out)
        return list(out)
    return out


#: {(cache, paper keys): (edition_rows' dict, its length, edition_dirs' answer)}.
_EDITION_DIRS = {}


def _edition_years_listed(cache, papers):
    """edition_dirs' editions by item of a folder off the media disk (a test's), listed."""
    if not cache.exists():
        return []
    return [sorted(item / n for n in with_pages(item))
            for item in (cache / n for n in dir_cache.listed(cache))
            if any(p.item.match(item.name) for p in papers)]


def with_pages(item):
    """The names of item dir `item`'s editions holding a pages.json. One found
    holding it is not looked at again while the item's dir_key is unmoved:
    pages.json is only ever replaced (write_atomic, gale_inbox.relink), and an
    edition goes or comes back whole (gale_inbox.stage's rmtree and rename),
    which moves the item."""
    try:
        _, names, memo = dir_cache.seen(item)
    except (FileNotFoundError, NotADirectoryError):
        return []
    known = memo.setdefault("with_pages", set())
    known.update(n for n in names if n not in known and "pages.json" in dir_cache.listed(item / n))
    return [n for n in names if n in known]


def scan(d):
    """{"puzzles": [...], "solutions": [...]} for one edition directory: each
    heading's number, leaf and box. Read here, in one of
    tools/ocr_remote.py's local slots (its title OCR on the desktop)."""
    import ocr_remote
    with ocr_remote.local_slot():
        return _scan(d)


def grid_first_on():
    """CT_GRID_FIRST=1, or the live switch file CT_GRID_FIRST_FILE (default
    ~/.cache/corpus_queue/grid_first) holding 1, so the queue can turn it on
    without a restart: units are fresh execs and read it each scan."""
    flag = os.environ.get("CT_GRID_FIRST")
    if flag is not None:
        return flag == "1"
    path = os.environ.get("CT_GRID_FIRST_FILE") or os.path.expanduser(
        "~/.cache/corpus_queue/grid_first")
    try:
        with open(path) as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def scan_anywhere(d):
    """scan(d), made whole on the desktop when it answers (ocr_remote.scan
    runs _scan there), else here. Not inside scan(): scan_key() hashes what
    scan() reaches, so an edit there re-scans every edition."""
    import ocr_remote
    if grid_first_on():
        return grid_first_scan(d)
    found = ocr_remote.scan(d)
    return scan(d) if found is None else found


#: Thread-local state of grid_first_scan: the paper being scanned, the windows
#: found on the page being read (page id, windows) and the detector's boxes of
#: the page band last read (key, results), which both page readers share.
_GRID_FIRST = threading.local()
#: How far past a window a detected text line may lie and still be read, in
#: pixels at the page's own scale.
GRID_FIRST_PAD = 8


def grid_first_scan(d):
    """scan(d) found grid-first (opt-in: CT_GRID_FIRST=1, scan_anywhere): the
    same scan, its whole-page RapidOCR read cut to the lines in the windows a
    title or solution heading can stand in. The detector runs over the whole
    page as the full read does, so every line's box is the full read's own to
    the pixel; only the recogniser, the bulk of the cost, reads fewer lines
    (grid_first_words). A page with no grid, or no window on it, is read whole.
    Defined apart from scan() and what it reaches: scan_key() hashes those, and
    this changes no scan's result but for a line outside every window, so no
    key moves."""
    import ocr_remote
    _grid_first_install()
    with ocr_remote.local_slot():
        _GRID_FIRST.paper = paper_of(d)
        try:
            found = _scan(d)
        finally:
            _GRID_FIRST.paper = None
            _GRID_FIRST.windows = _GRID_FIRST.detected = None
    # Two grids' bands (a patch of ink round the real grid) can read one title:
    # the title is one, its box twice a pixel apart.
    kept = []
    for p in found["puzzles"]:
        if not any(q["number"] == p["number"] and q["leaf"] == p["leaf"] and boxes_overlap(q["box"], p["box"])
                   for q in kept):
            kept.append(p)
    found["puzzles"] = kept
    return found


def boxes_overlap(a, b, share=0.5):
    """Whether boxes `a` and `b` (x0, y0, x1, y1) overlap by at least `share`
    of the smaller's area."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return False
    return w * h >= share * min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]), key=abs)


#: The unpatched band_words and grids_on, kept by _grid_first_install.
_PLAIN = {}
#: The fewest vertical and the fewest horizontal rules (rule_runs) a grid's
#: ink crosses: a 13x13 has 14 of each, a photograph or a column of type few
#: or none (and a ruled table many more of one than the other).
GRID_RULES = 8


def grid_ruled(img, box):
    """Whether the ink of `box` on `img` is ruled like a crossword grid:
    GRID_RULES vertical and horizontal rules, neither twice the other's number."""
    import numpy as np
    gray = np.asarray(img.crop(box).convert("L"), dtype=np.uint8)
    ink = gray < trove_grid.otsu(gray)
    v, h = len(rule_runs(ink)), len(rule_runs(ink.T))
    return v >= GRID_RULES and h >= GRID_RULES and 0.5 <= v / h <= 2


def _grid_first_install():
    """Put grid_first_band_words and grid_first_grids in band_words' and
    grids_on's places, once: they read as the originals do for any thread not
    inside grid_first_scan."""
    global band_words, grids_on
    if "band_words" in _PLAIN:
        return
    _PLAIN["band_words"], _PLAIN["grids_on"] = band_words, grids_on

    def band_words(img, band, which, cache_path):
        if getattr(_GRID_FIRST, "paper", None) is None or which not in PAGE_READERS:
            return _PLAIN["band_words"](img, band, which, cache_path)
        return grid_first_words(img, band, which, cache_path)

    def grids_on(img, step=2, shaped=grid_shaped):
        found = _PLAIN["grids_on"](img, step, shaped)
        if getattr(_GRID_FIRST, "paper", None) is None:
            return found
        return [g for g in found if grid_ruled(img, g)] or found


def grid_first_windows(img, paper):
    """[(x0, y0, x1, y1)] of the page where a title or a solution heading can
    stand: the bands round each ruled grid-shaped patch of ink that ocr_titles
    reads titles in (title_bands), and the bands solution_bands reads headings
    in over each ruled solution grid. None where the page has no ruled grid."""
    plain = _PLAIN["grids_on"]
    # Measured at the page's own scale (shaped_on): a page scanned wider than
    # SCAN_WIDTH (Gale 2005-06, 4664px) has its puzzle grid too wide for the
    # unscaled grid_shaped, and its solution grid alone passed for the puzzle's.
    grids = [g for g in plain(img, 2, lambda b: shaped_on(img, b)) if grid_ruled(img, g)]
    if not grids:
        return None
    wins = [b for g in grids for b in title_bands(img, g, False, paper.title_heights)]
    # The title heading the clue column right of the grid (Gale 2005..2006-10:
    # "THE TIMES CROSSWORD 23,142", its top level with the grid's).
    wins += [(g[0], max(0, g[1] - GRID_FIRST_PAD), min(img.width, g[2] + 2 * (g[2] - g[0])),
              min(img.height, g[1] + TITLE_REACH)) for g in grids]
    # Across the whole page: printed_lines clusters rows by height over every
    # word, so a title's row-mates left or right of its window (2012-09-17:
    # "April 2011 Takes a four-stroke lead", a line left of "Times Crossword
    # 25,270") change which words share its row, and so the box it is read at.
    return [(0, w[1], img.width, w[3]) for w in wins + solution_bands(img, [])]


def grid_first_words(img, band, which, cache_path):
    """band_words, RapidOCR's page readers' (PAGE_READERS) in grid_first_scan:
    the words the whole read gives, to the pixel. The page band keeps those of
    the lines the detector finds in a window of grid_first_windows (the whole
    read, where the page has no ruled grid); a smaller band all, the detector's
    boxes shared by both readers. Kept apart from the whole reads' cache (a
    .gf suffix) with the windows it read."""
    held = getattr(_GRID_FIRST, "windows", None)
    if held is None or held[0] is not img:
        _GRID_FIRST.windows = held = (img, grid_first_windows(img, _GRID_FIRST.paper))
    wins = held[1]
    if f"_page.{reader_key(which)}." in cache_path.name:
        if wins is None:
            return _PLAIN["band_words"](img, band, which, cache_path)
    else:
        wins = [band]
    path = cache_path.with_name(cache_path.name.replace(".json", ".gf.json"))
    try:
        cached = json.loads(path.read_text())
        if tuple(cached["box"]) == tuple(band) and [list(w) for w in cached["windows"]] == [list(w) for w in wins]:
            return [tuple(w) for w in cached["words"]]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    words = [(x0 + band[0], y0 + band[1], x1 + band[0], y1 + band[1], t)
             for x0, y0, x1, y1, t in ocr_clues.windowed_words(
                 img.crop(band), which, [(w[0] - band[0] - GRID_FIRST_PAD, w[1] - band[1] - GRID_FIRST_PAD,
                                          w[2] - band[0] + GRID_FIRST_PAD, w[3] - band[1] + GRID_FIRST_PAD)
                                         for w in wins], _GRID_FIRST)]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"box": list(band), "windows": [list(w) for w in wins], "words": words}))
    os.replace(tmp, path)
    return words


def _scan(d):
    pages = json.loads((d / "pages.json").read_text())
    leaves = {p["leaf"] for p in pages.get("crossword_pages", ())
              if (d / f"leaf_{p['leaf']:04d}.jpg").exists()}
    found = {"date": pages["date"], "item": pages["item"], "puzzles": [], "solutions": []}
    if not leaves:
        return found
    paper = paper_of(d)
    text = leaf_lines(d / "djvu.xml.gz", leaves)
    for leaf in sorted(leaves):
        if leaf not in text:
            img = page(d, leaf)
            # A whole-page read runs a title into the column beside it; the
            # bands round each grid read it alone (ocr_titles).
            titles, sols = ocr_headings(img, paper, f"{d.parent.name}_{d.name}_{leaf}",
                                        datetime.date.fromisoformat(pages["date"]))
        else:
            titles, sols = paper.headings(text[leaf])
            titles = [(n, box, setter, None) for n, box, setter in titles] or \
                ocr_titles(page(d, leaf), paper, datetime.date.fromisoformat(pages["date"]), f"{d.name}_{leaf}")
            if paper is TIMES and titles and not {n for n, _ in sols} & \
                    {t[0] - lag for t in titles for lag in SOLUTION_LAGS}:
                sols = sols + band_solutions(page(d, leaf), [t[0] for t in titles], text[leaf],
                                      f"{d.parent.name}_{d.name}_{leaf}", [t[1] for t in titles])
        for n, box, setter, readers in titles:
            found["puzzles"].append({"number": n, "leaf": leaf, "box": box,
                                     **({"setterRead": setter} if setter else {}),
                                     **({"titleReadBy": readers} if readers else {})})
        for n, box in sols:
            found["solutions"].append({"number": n, "leaf": leaf, "box": box})
    if paper is TIMES and not found["puzzles"]:
        found["puzzles"] = solution_titled(d, found["solutions"])
    # A puzzle's solution prints in a later edition, never its own: one
    # numbered like a title here is a misread heading (15,682's grid read as
    # 15,683's under 15,683).
    titled = {p["number"] for p in found["puzzles"]}
    found["solutions"] = [s for s in found["solutions"] if s["number"] not in titled]
    return found


#: How far over a solution heading the grid of the puzzle it is printed
#: under ends, in that grid's heights (the 1977-97 Times: 0.6 to 0.95).
SOLUTION_REACH = 1.5


def solution_titled(d, sols):
    """[{"number", "leaf", "box", "fromSolutions"}] of the puzzle on an
    edition no title was read in (its title line lost: Times 14,590's page
    shows only "Solution of Puzzle No 14,539" under the clues): on the first
    leaf with solution headings `sols` and a grid that ends over one of them,
    across it, within SOLUTION_REACH of its height, the number after its
    highest heading, the box a line over that grid. filed_number() files it
    only as the number its filed neighbours give (solution_title)."""
    for leaf in sorted({s["leaf"] for s in sols}):
        heads = [s for s in sols if s["leaf"] == leaf]
        img = page(d, leaf)
        grids = [g for g in grids_on(img, shaped=lambda b: shaped_on(img, b)) if not solution_shaped(img)(g)]
        near = [(h["box"][1] - g[3], g) for h in heads for g in grids
                if 0 <= h["box"][1] - g[3] <= SOLUTION_REACH * (g[3] - g[1]) and g[0] < h["box"][2] and g[2] > h["box"][0]]
        if near:
            g = min(near)[1]
            gap = 10 * img.width // SCAN_WIDTH
            return [{"number": max(h["number"] for h in heads) + 1, "leaf": leaf,
                     "box": (g[0], g[1] - 4 * gap, g[2], g[1] - gap), "fromSolutions": sorted(h["number"] for h in heads)}]
    return []


#: The least share of its box a grid's ink fills: a frame round a panel
#: (3%) is not a grid; grids fill 35-45%, but one with stippled grey blocks
#: thresholds to specks and fills 13% (the 1980 Times, 15,200).
GRID_FILL = 0.1
#: How far over and under a grid its title is looked for when archive.org's
#: text has none: the 1995 Times prints it 250px over the grid.
TITLE_REACH = 300


def grids_on(img, step=2, shaped=grid_shaped):
    """[box] of each grid-shaped patch of ink on a page (`shaped`, at least
    GRID_FILL of its box inked), found on a 1/step subsample."""
    import numpy as np
    cv2 = ocr_clues.capped_cv2()
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    ink = (gray < trove_grid.otsu(gray))[::step, ::step].astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=4)
    out = []
    for x, y, w, h, area in stats[1:].tolist():
        box = (x * step, y * step, (x + w) * step, (y + h) * step)
        if shaped(box) and area >= GRID_FILL * w * h:
            out.append(box)
    return out


def title_bands(img, grid, far=False, heights=1):
    """The crops a grid's title is read in, in turn: over and under it,
    TITLE_REACH deep, half the grid's width wider each side (the Guardian's
    title runs left of its grid); then a grid's width left of it, from its
    top down TITLE_REACH (the 1983-86 FT's "F.T. CROSSWORD" over "PUZZLE
    No. 5,607" heads the clue column beside the grid); with `far`, last, a
    grid's height over it (a Gale page's Saturday prize title, over its
    entry form), or `heights` of them as wide as the band over it (a Gale
    Telegraph's "No. 15,301 ACROSS", over the clue columns over its grid)."""
    x0, y0, x1, y1 = grid
    xa, xb = max(0, x0 - (x1 - x0) // 2), min(img.width, x1 + (x1 - x0) // 2)
    return ((xa, max(0, y0 - TITLE_REACH), xb, y0), (xa, y1, xb, min(img.height, y1 + TITLE_REACH)),
            (max(0, x0 - (x1 - x0)), y0, x0, min(img.height, y0 + TITLE_REACH))) \
        + (() if not far else ((x0, max(0, y0 - (y1 - y0)), x1, y0),) if heights == 1
           else ((xa, max(0, y0 - heights * (y1 - y0)), xb, y0),))


def printed_lines(words):
    """djvu-style lines of OCR words, (x0, y0, x1, y1, text) each: words
    each of whose middles lies within the other's height share a row (a
    column rule read as one tall word joins none), left to right, a row
    split where a gap wider than three heights parts two columns. A word
    no row's first word takes joins a row whose other words left of it are
    all under half its tallest word's height (a title the grid's clue numbers
    beside it opened; a tall heading of another column, right of the number,
    does not part them: Gale's "THE TIMES CROSSWORD" 22,779 beside "Around
    Britain") when it and that tallest word share a row so and it is no
    more than a tenth taller (a number's digits stand a little over a
    title's capitals): the title's number joins the title; a title beside a
    shorter body line, or a body line's run of words, does not."""
    def mid(w):
        return (w[1] + w[3]) / 2

    def height(w):
        return w[3] - w[1]

    def alike(a, b):
        return a[1] <= mid(b) <= a[3] and b[1] <= mid(a) <= b[3]

    def apart(row, w):
        return min(max(x[0] - w[2], w[0] - x[2], 0) for x in row)
    rows, tallest = [], []
    for w in sorted(words, key=mid):
        k = next((k for k, r in enumerate(rows) if alike(r[0], w)), None)
        taller = next((j for j, (r, t) in enumerate(zip(rows, tallest))
                       if 10 * height(w) <= 11 * height(t) and alike(t, w)
                       and all(2 * height(x) < height(t) for x in r if x is not t and x[0] < w[0])), None)
        # A number beside its title joins the title's row, not the row of a
        # speck of another column that shares its height further along.
        if k is None or taller is not None and taller != k and apart(rows[taller], w) < apart(rows[k], w):
            k = taller
        if k is None:
            rows.append([w])
            tallest.append(w)
        else:
            rows[k].append(w)
            tallest[k] = max(tallest[k], w, key=height)
    lines = []
    for row in rows:
        row.sort()
        line = [row[0]]
        for w in row[1:]:
            if w[0] - line[-1][2] > 3 * (w[3] - w[1]):
                lines.append(line)
                line = []
            line.append(w)
        lines.append(line)
    return lines


def band_words(img, band, which, cache_path):
    """Reader `which`'s words in a band of the page, in page coordinates;
    cached as JSON with the band it read."""
    try:
        cached = json.loads(cache_path.read_text())
        if tuple(cached["box"]) == tuple(band):
            return [tuple(w) for w in cached["words"]]
    except (OSError, ValueError, KeyError, TypeError):
        pass  # missing or unreadable (empty, truncated by a killed read): a miss
    words = [(x0 + band[0], y0 + band[1], x1 + band[0], y1 + band[1], t)
             for x0, y0, x1, y1, t in read_words(img.crop(band), which)]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"box": list(band), "words": words}))
    os.replace(tmp, cache_path)
    return words


def ocr_titles(img, paper, day, key, far=False):
    """[(number, box, setter, readers)] of the titles our own readers
    (READERS) find over or under each grid on a page whose archive.org text
    has none: per band, the number most readers read (a tie to the one
    nearest the date's), with the box and setter of the first reader that
    read it; `far`, title_bands' far band too. read_puzzle still holds the
    number to the date."""
    found = []
    for g in grids_on(img):
        for band in title_bands(img, g, far, paper.title_heights):
            reads = {}
            for which in READERS:
                path = CROPS / "titles" / f"{key}_{'_'.join(map(str, band))}.{reader_key(which)}.json"
                titles = paper.headings(printed_lines(band_words(img, band, which, path)))[0]
                if titles:
                    reads[which] = titles[0]
            if reads:
                votes = {}
                for which, (n, _, _) in reads.items():
                    votes.setdefault(n, []).append(which)
                n = min(votes, key=lambda n: (-len(votes[n]), abs(n - paper.expected(day))))
                _, box, setter = reads[votes[n][0]]
                found.append((n, box, setter, votes[n]))
                break
    return found


#: Heading words as our readers misread them on a Gale page ("Cressword",
#: "Solotion"), read as the word.
OCR_MISREADS = ((re.compile(r"cr[eo0]s{1,2}w[o0]rd", re.IGNORECASE), "Crossword"),
                (re.compile(r"s[o0]l[uo0]ti[o0]n", re.IGNORECASE), "Solution"))
#: A word (RapidOCR's: a phrase) a heading opens on: a line our readers ran a clue column into
#: ("27 Order observed in 16 con- Solution to Puzzle No 17,246") is read
#: from each.
HEADING_START = re.compile(r"\W*(?:the|solution)\b", re.IGNORECASE)


def mend_misreads(text):
    for pattern, word in OCR_MISREADS:
        text = pattern.sub(word, text)
    return text


#: A word our readers read where a solution heading starts ("Solution", or a
#: RapidOCR phrase holding it: "grass Solution to Puzzle No 17,245").
SOLUTION_WORD = re.compile(r"\bsolution\b", re.IGNORECASE)
#: A solution heading's band, re-read whole by every reader: from just left of
#: its "Solution" word (or its grid's left edge) this far right, and this far
#: over and under the word (over the grid, this far up from its top), in
#: pixels at SCAN_WIDTH. The heading is set over its own solution grid, the
#: clue column left of it (a whole-page read runs the two together, or reads
#: neither), the next column past it; two side by side (a Saturday's) are
#: read apart, each from its own word or grid.
SOLUTION_BAND = (30, 560, 25, 70)
#: The width of a solution grid at SCAN_WIDTH (the puzzle's own is 680-770).
SOLUTION_GRID = (200, 480)


def solution_shaped(img):
    """grids_on's `shaped` for a solution grid on page `img`."""
    k = SCAN_WIDTH / img.width
    # A page wider than SCAN_WIDTH (the Gale Times's 4600 px pages of 2004-06) prints its
    # grids larger on the page than a 3296 px one: its solution grid is 510 wide at
    # SCAN_WIDTH, and its puzzle's 1070; the cap grows with the page's width.
    most = SOLUTION_GRID[1] * max(1, img.width / SCAN_WIDTH)

    def shaped(box):
        w, h = (box[2] - box[0]) * k, (box[3] - box[1]) * k
        return SOLUTION_GRID[0] <= w <= most and 0.85 <= w / max(h, 1) <= 1.18
    return shaped


def solution_bands(img, words):
    """The bands (x0, y0, x1, y1) a page's solution headings are re-read in:
    one per "Solution" word any reader read (SOLUTION_WORD), and one over
    each solution grid's top (grids_on), where no reader's whole-page pass
    read the heading at all (Gale's 1987-01-17); those of one heading once."""
    k = img.width / SCAN_WIDTH
    left, right, pad, over = (int(v * k) for v in SOLUTION_BAND)
    starts = []
    for x0, y0, x1, y1, text in words:
        m = SOLUTION_WORD.search(text)
        if m:
            starts.append((x0 + (x1 - x0) * m.start() // max(len(text), 1), y0 - pad, y1 + pad))
    starts += [(g[0], g[1] - over, g[1] + pad // 5) for g in grids_on(img, shaped=solution_shaped(img))]
    bands = []
    for x, top, foot in starts:
        band = (max(0, x - left), max(0, top), min(img.width, x + right), min(img.height, foot))
        if not any(abs(band[0] - b[0]) < 2 * left and min(band[3], b[3]) > max(band[1], b[1]) for b in bands):
            bands.append(band)
    return bands


def row_lines(words):
    """printed_lines() with each row's lines joined: a heading read with a
    wide gap between its words ("Solution tn Puzzle" ... "No 17,245") is one
    line."""
    rows = []
    for ln in printed_lines(words):
        row = next((r for r in rows if r[0][1] <= (ln[0][1] + ln[0][3]) / 2 <= r[0][3]), None)
        if row is None:
            rows.append(list(ln))
        else:
            row.extend(ln)
            row.sort()
    return rows


#: The readers that read a Gale page's whole ink (ocr_headings); the other
#: READERS (Tesseract) read only the strips round their words a heading
#: could be (hint_strips). A whole-page Tesseract read cost 60 CPU-s of a
#: scan's 142 (RapidOCR's ch 37, en5 45), its strips 16; RapidOCR reads a
#: strip at a finer detection scale than a whole page, so strips cost it
#: more, not less, and would move the boxes the read's crops are cut from.
PAGE_READERS = ("ch", "en5")
#: A word a heading could be, however misread: a number of four digits or
#: more ("17,554", "17.58l" reads "17.58"), or "solution", "crossword" or
#: "puzzle" as our readers misread them.
HEADING_HINT = re.compile(r"\d[\d,.' ]{2,}\d|s[o0]l[uo0]t|cr[o0e]ss|puzz|pvzz", re.IGNORECASE)
#: How far a hint's strip reaches past its word: this many pixels at
#: SCAN_WIDTH left and right, this many of its heights over and under.
HINT_PAD = (150, 1)


def hint_strips(img, words):
    """The bands (x0, y0, x1, y1) round each of `words` HEADING_HINT
    matches, padded by HINT_PAD and clipped to the page, those that
    overlap merged, so no word is read twice."""
    k = img.width / SCAN_WIDTH
    bands = []
    for x0, y0, x1, y1, text in words:
        if HEADING_HINT.search(text):
            h = y1 - y0
            bands.append([max(0, int(x0 - HINT_PAD[0] * k)), max(0, int(y0 - HINT_PAD[1] * h)),
                          min(img.width, int(x1 + HINT_PAD[0] * k)), min(img.height, int(y1 + HINT_PAD[1] * h))])
    merged = True
    while merged:
        merged = False
        for i, a in enumerate(bands):
            for b in bands[i + 1:]:
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    a[:] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    bands.remove(b)
                    merged = True
                    break
            if merged:
                break
    return sorted(tuple(b) for b in bands)


def ocr_headings(img, paper, key, day=None):
    """([(number, box, setter, readers)], [(number, box)]) of the titles and
    solution headings on a page archive.org has no text for (a Gale page:
    one article, so its whole ink is read): each title's number at least
    half our readers read on the page, with the box and setter of the
    first; a title fewer read stands when it is the number after a solution
    heading read on the page (the day before's, printed under the clues).
    A solution heading is read again in its own band (solution_bands) by
    every reader, and stands where at least half read its number there: a
    whole-page read misses its small type or runs it into the clue column.
    A band is read against the titles at least half read on the page
    (solution_headings), as a leaf's text is: "Solution to -— No 17,694"
    under 17,695 is its heading. Where no title has half the readers and
    the edition's `day` is given, the titles ocr_titles reads round the
    page's grids stand instead, and the bands are read against them (the
    1988 Gale page's title "PUZZLE NO 17,581" a line under "THE TIMES
    CROSSWORD")."""
    box = img.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
    if box is None:
        return ([] if day is None else ocr_titles(img, paper, day, key, far=True)), []
    titles, page_words, read = {}, [], {}
    for which in sorted(READERS, key=lambda r: r not in PAGE_READERS):
        # PAGE_READERS read the whole ink; the others only the strips round
        # their words a heading could be (hint_strips), or the whole ink too
        # when they read nothing.
        hints = [w for r in PAGE_READERS for w in read.get(r, ())]
        bands = [box] if which in PAGE_READERS or not hints else hint_strips(img, hints)
        read[which] = []
        for band in bands:
            name = "page" if band == box else "_".join(map(str, band))
            try:
                read[which] += [(*w[:4], mend_misreads(w[4])) for w in band_words(
                    img, band, which, CROPS / "titles" / f"{key}_{name}.{reader_key(which)}.json")]
            except subprocess.TimeoutExpired:  # this reader read nothing; the vote still needs half of READERS
                pass
    for which in READERS:
        words = read[which]
        page_words += words
        lines = printed_lines(words)
        lines += [ln[k:] for ln in lines for k in range(1, len(ln)) if HEADING_START.match(ln[k][4])]
        for n, b, setter in paper.headings(lines)[0]:
            if which not in (r[0] for r in titles.get(n, ())):
                titles.setdefault(n, []).append((which, b, setter))
    least = len(READERS) / 2
    voted = [n for n, reads in titles.items() if len(reads) >= least]
    near = [] if voted or day is None else ocr_titles(img, paper, day, key, far=True)
    voted = voted or [t[0] for t in near]
    sols = {}
    for band in solution_bands(img, page_words):
        for which in READERS:
            path = CROPS / "titles" / f"{key}_{'_'.join(map(str, band))}.{reader_key(which)}.json"
            words = [(*w[:4], mend_misreads(w[4])) for w in band_words(img, band, which, path)]
            lines = row_lines(words)
            lines += [ln[k:] for ln in lines for k in range(1, len(ln)) if HEADING_START.match(ln[k][4])]
            for n, b in {n: b for n, b in reversed(paper.headings(lines, voted)[1])}.items():
                if which not in (r[0] for r in sols.get(n, ())):
                    sols.setdefault(n, []).append((which, b))
    # With titles voted, solution_headings reads only a number SOLUTION_LAGS before one, so one
    # reader's read of it stands (the thin band RapidOCR drops the number from, Tesseract keeps:
    # 1971-09-09's "Solution of Puzzle No 12,869"): read_solution checks the grid against the
    # puzzle's (blocks, lengths, crossings) before any answer files.
    sols = {n: reads for n, reads in sols.items() if len(reads) >= (1 if voted else least)}
    found = [(n, reads[0][1], reads[0][2], [r[0] for r in reads]) for n, reads in titles.items()
             if len(reads) >= least or n - 1 in sols] or near
    return gale_headings(img, paper, key, day, found, [(n, reads[0][1]) for n, reads in sols.items()])


def gale_headings(img, paper, key, day, titles, sols):
    """(titles, sols) of ocr_headings with what the page's other headings show
    is no title moved off them: a "Solution to yesterday's / crossword
    22,778" heading, its second line read as a title, is the solution heading
    of the title SOLUTION_LAGS above it on the page (22,779), so a solution;
    and a number far off the date's, with another title read on the page
    near it ("The Times Crossword 2000", a bookshop advertisement in 1999),
    is no title. Titles all read in the page's foot, where the solution
    headings are printed, are the headings only: the title's own words lost
    to the whole-page read (Times 22,211's "THE TIMES CROSSWORD"), the
    titles ocr_titles reads round the grids that stand SOLUTION_LAGS past
    one of them are the page's."""
    if day is not None and titles and all(t[1][3] > 0.8 * img.height for t in titles):
        titles = [t for t in ocr_titles(img, paper, day, key, far=True)
                  if any(t[0] - x[0] in SOLUTION_LAGS for x in titles)] + titles
    nums = {t[0] for t in titles}
    moved = [t for t in titles if any(t[0] + lag in nums for lag in SOLUTION_LAGS)]
    titles = [t for t in titles if t not in moved]
    if day is not None and any(abs(t[0] - paper.expected(day)) <= paper.slack for t in titles):
        titles = [t for t in titles if abs(t[0] - paper.expected(day)) <= paper.slack]
    held = {n for n, _ in sols}
    return titles, sols + [(t[0], t[1]) for t in moved if t[0] not in held]


#: The strip under a Times title that the day before's solution heading is
#: printed in, under the clues (the heading and its grid where archive.org's
#: text holds no word of them and grids_on finds no solution grid: 1986-08-12,
#: 1996-02-09): from this far left of the title to this far right of its
#: left edge, in pixels at SCAN_WIDTH, down to the page's foot.
TITLE_STRIP = (40, 900)


def title_strips(img, boxes):
    """The bands (x0, y0, x1, y1) under each title box in `boxes`
    (TITLE_STRIP)."""
    k = img.width / SCAN_WIDTH
    left, right = (int(v * k) for v in TITLE_STRIP)
    return [(max(0, int(b[0]) - left), int(b[3]), min(img.width, int(b[0]) + right), img.height)
            for b in boxes if b and int(b[3]) < img.height]


def band_solutions(img, titles, lines, key, boxes=()):
    """[(number, box)] of the solution headings on a Times leaf whose
    archive.org text `lines` reads none for its titles `titles` ("Solution,
    of PnzZle-No'lS^GZ" for 15,562, "No 164750" for 16,950): each band
    solution_bands() finds off the text's words, read by every reader, and a
    number standing where at least half read it as a heading one
    SOLUTION_LAGS before a title (solution_headings). Where those bands read
    none, the strip under each title box in `boxes` (title_strips) is read
    the same way."""
    found = band_votes(img, solution_bands(img, [w for ws in lines for w in ws]), titles, key)
    return found or band_votes(img, title_strips(img, boxes), titles, key)


def band_votes(img, bands, titles, key):
    """band_solutions' vote over `bands`."""
    reads = {}
    for band in bands:
        for which in READERS:
            path = CROPS / "titles" / f"{key}_{'_'.join(map(str, band))}.{reader_key(which)}.json"
            try:
                words = [(*w[:4], mend_misreads(w[4])) for w in band_words(img, band, which, path)]
            except subprocess.TimeoutExpired:  # this reader read nothing; the vote still needs half of READERS
                words = []
            rows = row_lines(words)
            rows += [ln[k:] for ln in rows for k in range(1, len(ln)) if HEADING_START.match(ln[k][4])]
            for n, b in solution_headings(rows, titles):
                if which not in (r[0] for r in reads.get(n, ())):
                    reads.setdefault(n, []).append((which, b))
    return [(n, r[0][1]) for n, r in reads.items() if len(r) >= len(READERS) / 2]


def page(d, leaf):
    """Leaf `leaf`'s scan, shrunk by its paper's `shrink` (the JPEG decoded
    at that scale, so a 13663px 1930 page costs what a 3296px one does)."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    img = Image.open(d / f"leaf_{leaf:04d}.jpg")
    shrink = paper_of(d).shrink
    if shrink > 1:
        img.draft(img.mode, (img.width // shrink, img.height // shrink))
        img = img.convert("L")
    return img


#: A dated Times cryptic either side of the 1978-79 shutdown, and the run
#: of six a week (none on Sunday) from it.
ANCHORS = ((datetime.date(1974, 5, 1), 13676), (datetime.date(1990, 1, 2), 18180))
RESUMED = datetime.date(1979, 11, 13)
#: How far a number may stray from that run before the edition's date is
#: distrusted.
NUMBER_SLACK = 300


def expected_number(day):
    start, number = ANCHORS[day >= RESUMED]
    return number + round((day - start).days * 6 / 7)


#: Dated FT cryptics read off the scans and our own first ftcryptic file:
#: the number between two is interpolated, outside them run on six a week.
FT_ANCHORS = ((datetime.date(1975, 5, 1), 2766), (datetime.date(1995, 1, 3), 8650),
              (datetime.date(2009, 11, 12), 13232))


def anchored(pts, day):
    """The number a date implies from dated (day, number) anchors in order:
    interpolated between two, run on six a week outside them."""
    if day <= pts[0][0] or day >= pts[-1][0]:
        start, number = pts[0] if day <= pts[0][0] else pts[-1]
        return number + round((day - start).days * 6 / 7)
    (d0, n0), (d1, n1) = next((a, b) for a, b in zip(pts, pts[1:]) if day <= b[0])
    return n0 + round((n1 - n0) * (day - d0).days / (d1 - d0).days)


def ft_expected_number(day):
    return anchored(FT_ANCHORS, day)


#: Dated Guardian cryptics: our own 1970, 1982 and first 1999 files, and
#: 20,538 read off the 2 January 1996 scan.
GUARDIAN_ANCHORS = ((datetime.date(1970, 8, 25), 12575), (datetime.date(1982, 1, 27), 16176),
                    (datetime.date(1996, 1, 2), 20538), (datetime.date(1999, 6, 24), 21620))


def guardian_expected_number(day):
    return anchored(GUARDIAN_ANCHORS, day)


#: The FT's title: "CROSSWORD" (or "MONDAY PRIZE CROSSWORD") over
#: "No. 8,650 Set by DANTE" in the 1990s, "F.T. CROSSWORD" over "PUZZLE
#: No. 5,613" in the 1980s, "CROSSWORD PUZZLE No. 2,766" on one line in
#: the 1970s.
FT_TITLE = re.compile(r"^\W*(?:[a-z.]+\s+){0,2}(?:cross\s?word(?:\s+puzzle)?|cross\s+puzzle)\b\W*(.*)$", re.IGNORECASE)
FT_NUMBER = re.compile(r"^\W*(?:puzzle\s+)?no\W{0,2}\s*(\d[,.?^]?\d{3})\b(.*)$", re.IGNORECASE)
#: How many leading words of a line ft_headings drops to find a numbered
#: title: the OCR runs the next column's last word into the title's line
#: ("~nTupblfih“parkCtT- CROSSWORD PUZZLE NO. 1,652").
FT_LEAD_JUNK = 2
FT_SETTER = re.compile(r"set\s+by\s+([A-Za-z][A-Za-z'-]+)", re.IGNORECASE)
#: The previous puzzle's solution grid: "Solution 8,650", or in the 1970s
#: "SOLUTION TO PUZZLE" over "No. 2,765".
FT_SOLUTION = re.compile(r"^\W*solution\s+(?:(?:to|of)\s+)?(?:puzzle\b)?\W*(.*)$", re.IGNORECASE)
#: The width of the grid and of the solution grid under an FT heading,
#: which is narrower than either: the box grid_box and read_solution crop
#: around is this wide, centred on the heading.
FT_GRID_SPAN = 960
FT_SOLUTION_SPAN = 360


def box_of(ws):
    return (min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws), max(w[3] for w in ws))


def centred(box, span):
    cx = (box[0] + box[2]) // 2
    return (cx - span // 2, box[1], cx + span // 2, box[3])


_SETTERS = {}


def setters(series):
    """The setters our files of `series` name."""
    if series not in _SETTERS:
        _SETTERS[series] = {json.loads(p.read_text()).get("setter")
                            for p in (ROOT / "puzzles" / series).glob("*/*.json")}
    return _SETTERS[series]


def ft_headings(lines, titles=()):
    """([(number, box, setter)], [(number, box)]): each FT crossword title,
    its number on its own line or the line just under it, and each
    "Solution N" heading; boxes widened to the grid's span."""
    def numbered(ws, rest):
        """(the "No. N" match, the line it is on): on this line, else
        on a line just under it."""
        num = FT_NUMBER.match(rest)
        if num or re.search(r"\d", rest):
            return num, ws
        box = box_of(ws)
        cx = (box[0] + box[2]) / 2
        for v in lines:
            if v is not ws and box[3] - 5 <= box_of(v)[1] <= box[3] + 80 \
                    and box_of(v)[0] - 150 <= cx <= box_of(v)[2] + 150:
                num = FT_NUMBER.match(" ".join(w[4] for w in v))
                if num:
                    return num, v
        return None, ws

    puzzles, solutions = [], []
    for ws in lines:
        text = " ".join(w[4] for w in ws)
        m = FT_SOLUTION.match(text)
        if m:
            rest = m.group(1)
            num, under = numbered(ws, rest if re.match(r"\W*no\b", rest, re.IGNORECASE) else "no " + rest)
            if num and not num.group(2).strip(" .'"):
                solutions.append((number_of(num.group(1)), centred(box_of(ws + under), FT_SOLUTION_SPAN)))
            continue
        # The whole line, else (numbered only) the line less its first
        # FT_LEAD_JUNK words.
        for k in range(min(FT_LEAD_JUNK, len(ws) - 1) + 1):
            line = ws[k:] if k else ws
            m = FT_TITLE.match(" ".join(w[4] for w in line))
            # Words after "CROSSWORD" and no number: prose ("No crossword
            # appears in today's edition"), not a title over its number.
            prose = m and re.search(r"[a-z]", m.group(1), re.IGNORECASE) and not re.search(r"\d", m.group(1))
            num, under = numbered(line, m.group(1)) if m and not prose else (None, line)
            if num:
                ws = line
                break
        if not num:
            continue
        box, whole = box_of(ws), box_of(ws + under)
        setter = FT_SETTER.search(num.group(2))
        puzzles.append((number_of(num.group(1)), centred((box[0], whole[1], box[2], whole[3]), FT_GRID_SPAN),
                        setter.group(1).title() if setter else None))
    return puzzles, solutions


#: The Guardian's title, "Guardian Crossword No 20,538" over "Set by
#: Rufus" ("CROSSWORD 17,101" in the 1980s), and the previous puzzle's solution grid, over its label
#: "CROSSWORD SOLUTION 20,537". archive.org reads a comma as "^" at times.
G_NUMBER = r"(\d{2}[,.\s^']?\d{3})"
GUARDIAN_TITLE = re.compile(r"^\W*(?:the\s+)?(?:guardian\s+)?(?:prize\s+)?crossword\s+(?:puzzle\s+)?(?:no\W{0,2}\s*)?"
                            + G_NUMBER + r"\b(.*)$", re.IGNORECASE)
GUARDIAN_SOLUTION = re.compile(r"^\W*(?:guardian\s+)?(?:prize\s+)?crossword\s+\w?o[l1]ut[il1]on\b\W*(.*)$",
                               re.IGNORECASE)
#: The Guardian's third clue column, right of the grid under the solution
#: grid: this wide, from its left edge.
GUARDIAN_THIRD = 360


def guardian_headings(lines, titles=()):
    """([(number, box, setter)], [(number, box)]): each Guardian crossword
    title with the setter on it or the line under it, and each solution
    label (the solution grid is above it). A label whose number is misread
    ("20^39") is the previous puzzle's, beside the page's one title."""
    puzzles, solutions = [], []
    for ws in lines:
        text = " ".join(w[4] for w in ws)
        m = GUARDIAN_SOLUTION.match(text)
        if m:
            num = re.fullmatch(G_NUMBER + r"\W*", m.group(1))
            solutions.append((number_of(num.group(1)) if num else None, box_of(ws)))
            continue
        m = GUARDIAN_TITLE.match(text)
        if not m:
            continue
        box = box_of(ws)
        setter = FT_SETTER.search(m.group(2))
        if not setter:
            for v in lines:
                b = box_of(v)
                if v is not ws and box[3] - 5 <= b[1] <= box[3] + 80 and abs(b[0] - box[0]) <= 150:
                    setter = FT_SETTER.search(" ".join(w[4] for w in v)) or setter
        puzzles.append((number_of(m.group(1)), box, setter.group(1).title() if setter else None))
    solutions = [(n if n is not None else puzzles[0][0] - 1, box) for n, box in solutions
                 if n is not None or len(puzzles) == 1]
    return puzzles, solutions


#: Dated Telegraph cryptics: 18,340 read off the 4 January 1985 scan, and
#: our first telegraph file.
TELEGRAPH_ANCHORS = ((datetime.date(1985, 1, 4), 18340), (datetime.date(2009, 2, 7), 25846))


def telegraph_expected_number(day):
    return anchored(TELEGRAPH_ANCHORS, day)


#: The previous Telegraph puzzle's solution grid, under "SOLUTION No.
#: 18,339", which is narrower than the grid: the box read_solution crops
#: around is this wide, centred on the heading.
TELEGRAPH_SOLUTION = re.compile(r"^\W*s\w?[l1]ut[il1]on\s+n[o0]\W{0,3}\s*([\dTIl]\d?[,.\-\s]?\d{3})\W*$",
                                re.IGNORECASE)
TELEGRAPH_SOLUTION_SPAN = 380


def telegraph_headings(lines, titles=()):
    """([(number, box, None)], [(number, box)]): each Telegraph cryptic's
    title, "No. 18,340 ACROSS" over the left clue column, and each
    "SOLUTION No. 18,339" heading, its box widened to the solution grid's."""
    puzzles, solutions = [], []
    for ws in lines:
        text = " ".join(w[4] for w in ws)
        m = TELEGRAPH_SOLUTION.match(text)
        if m:
            solutions.append((number_digits(m.group(1)), centred(box_of(ws), TELEGRAPH_SOLUTION_SPAN)))
            continue
        m = NUMBERED_HEADING.match(text)
        if m and heading_of(m.group(1)) == "ACROSS":
            num = re.search(r"[\dTIl]\d?[,.\-\s]?\d{3}", text)
            puzzles.append((number_digits(num.group(0)), box_of(ws), None))
    return puzzles, solutions


#: A Gale Telegraph page's title from ~1990: a banner "CROSSWORD / 21,502"
#: over both clue columns (before it, "No. 15,301 ACROSS": telegraph_headings).
TELEGRAPH_BANNER = re.compile(r"^\W*cr[o0]ssw[o0]rd\W{1,4}([\dTIl]\d?[,.\-\s]?\d{3})\W*$", re.IGNORECASE)


def gale_telegraph_headings(lines, titles=()):
    """telegraph_headings(), and each TELEGRAPH_BANNER title."""
    puzzles, solutions = telegraph_headings(lines)
    for ws in lines:
        m = TELEGRAPH_BANNER.match(" ".join(w[4] for w in ws))
        if m:
            puzzles.append((number_digits(m.group(1)), box_of(ws), None))
    return puzzles, solutions


#: A number of one to five digits, as the Independent and Sunday Times
#: print theirs ("No. 12", "No 2,345").
SMALL_NUMBER = r"([\dTIl]?\d?[,.]?\d{1,3})(?![\d,])"


def titled_headings(lines, title, solution):
    """([(number, box, setter)], [(number, box)]) of each line opening with
    `title` (its number group 1, any setter after it, "Set by X", in group
    2) and each opening with `solution` (number group 1)."""
    puzzles, solutions = [], []
    for ws in lines:
        text = " ".join(w[4] for w in ws)
        m = solution.match(text)
        if m:
            solutions.append((number_digits(m.group(1)), box_of(ws)))
            continue
        m = title.match(text)
        if m:
            setter = FT_SETTER.search(m.group(2))
            puzzles.append((number_digits(m.group(1)), box_of(ws), setter.group(1).title() if setter else None))
    return puzzles, solutions


#: The Independent's title (from its first issue, 7 October 1986): "THE
#: INDEPENDENT CROSSWORD No 1,234", "Saturday Crossword No. 5,678", "Cryptic
#: crossword #9,101", maybe "Set by" its setter after; never the Quick or
#: Concise crossword. Its solution heading: "Solution to No 1,233",
#: "Yesterday's solution No. 1,233", "Saturday's solution to Crossword 5,677".
INDEPENDENT_TITLE = re.compile(r"^\W*(?:the\s+)?(?:independent\s+)?(?:(?:saturday|weekend|tuesday|prize|cryptic)\s+){0,2}"
                               r"cr[o0]ss\s?w[o0]rd\W{0,3}(?:puzzle\W{0,3})?(?:n[o0]\W{0,3}|#)?\s*" + SMALL_NUMBER
                               + r"(.*)$", re.IGNORECASE)
INDEPENDENT_SOLUTION = re.compile(r"^\W*(?:(?:yesterday|saturday|last\s+week)'?s\s+)?s[o0][l1]ut[il1][o0]n\W{0,3}"
                                  r"(?:t[o0]\s+)?(?:(?:cr[o0]ssw[o0]rd|puzzle)\W{0,3})?(?:n[o0]\W{0,3}|#)?\s*"
                                  + SMALL_NUMBER + r"\W*$", re.IGNORECASE)
#: Dated Independent cryptics: No 1 in its first issue, and our first and
#: latest independent files.
INDEPENDENT_ANCHORS = ((datetime.date(1986, 10, 7), 1), (datetime.date(2011, 1, 15), 7566),
                       (datetime.date(2026, 10, 10), 12483))


def independent_expected_number(day):
    return anchored(INDEPENDENT_ANCHORS, day)


def independent_headings(lines, titles=()):
    """titled_headings() of an Independent page."""
    return titled_headings(lines, INDEPENDENT_TITLE, INDEPENDENT_SOLUTION)


#: The Sunday Times's title: "Cross-word Puzzle—No. 1" (11 January 1925),
#: "THE SUNDAY TIMES CROSSWORD No 2,345", "Prize Crossword No. 3,456"; never
#: Mephisto, the Concise or a solution heading. Its solution heading:
#: "Solution to Cross-word Puzzle No. 1", "SOLUTION TO No 2,344",
#: "Last week's solution No. 3,455".
SUNDAY_TIMES_TITLE = re.compile(r"^\W*(?:the\s+)?(?:sunday\s+times\s+)?(?:prize\s+)?cr[o0]ss\W{0,3}w[o0]rd\W{0,3}"
                                r"(?:puzzle\W{0,3})?(?:n[o0]\W{0,3})?\s*" + SMALL_NUMBER + r"(.*)$", re.IGNORECASE)
SUNDAY_TIMES_SOLUTION = re.compile(r"^\W*(?:last\s+week'?s\s+)?s[o0][l1]ut[il1][o0]n\W{0,3}(?:(?:t[o0]|of)\s+)?"
                                   r"(?:(?:prize\s+)?cr[o0]ss\W{0,3}w[o0]rd\W{0,3})?(?:puzzle\W{0,3})?(?:n[o0]\W{0,3})?\s*"
                                   + SMALL_NUMBER + r"\W*$", re.IGNORECASE)
#: Dated Sunday Times cryptics: No 1 (11 January 1925), our first
#: sundaytimes file and No 5,000 (27 March 2022); one a week between, less
#: the weeks it was not printed (1978-79), so interpolated.
SUNDAY_TIMES_ANCHORS = ((datetime.date(1925, 1, 11), 1), (datetime.date(2014, 5, 11), 4589),
                        (datetime.date(2022, 3, 27), 5000))
#: How far a Sunday Times title's number may stray from its date's: one a
#: week, so a year is 52.
SUNDAY_TIMES_SLACK = 80


def sunday_times_expected_number(day):
    return anchored(SUNDAY_TIMES_ANCHORS, day)


def sunday_times_headings(lines, titles=()):
    """titled_headings() of a Sunday Times page."""
    return titled_headings(lines, SUNDAY_TIMES_TITLE, SUNDAY_TIMES_SOLUTION)



#: The TLS's title: "TLS CROSSWORD 835" over its clues (an unbylined weekly
#: prize puzzle), never its entry address's "TLS Crossword 835," or "The
#: winner of Crossword 831". Its solution heading, four weeks on, under the
#: solution grid left of the clues: "SOLUTION TO CROSSWORD 831".
TLS_TITLE = re.compile(r"^\W*(?:t\W?l\W?s\W{0,3})?cr[o0]ss\W{0,3}w[o0]rd\W{0,3}(?:n[o0]\W{0,3})?\s*" + SMALL_NUMBER
                       + r"(.*)$", re.IGNORECASE)
TLS_SOLUTION = re.compile(r"^\W*s[o0][l1]ut[il1][o0]n\W{0,3}(?:(?:t[o0]|of)\s+)?(?:(?:tls\s+)?cr[o0]ss\W{0,3}w[o0]rd\W{0,3})?"
                          r"(?:n[o0]\W{0,3})?\s*" + SMALL_NUMBER + r"\W{0,3}\w?\W*$", re.IGNORECASE)
#: Dated TLS crosswords, read off Gale's contents (2026-10-12) and our own
#: tls files: weekly, less the double issues, and sparse before 1995.
TLS_ANCHORS = ((datetime.date(1992, 6, 5), 102), (datetime.date(1995, 1, 6), 128),
               (datetime.date(1996, 6, 7), 168), (datetime.date(2000, 6, 2), 363),
               (datetime.date(2010, 6, 4), 835), (datetime.date(2014, 12, 26), 1055),
               (datetime.date(2017, 5, 19), 1176))
#: How far a TLS title's number may stray from its date's.
TLS_SLACK = 30


def tls_expected_number(day):
    """anchored(TLS_ANCHORS), one a week outside them."""
    first, last = TLS_ANCHORS[0], TLS_ANCHORS[-1]
    if first[0] < day < last[0]:
        return anchored(TLS_ANCHORS, day)
    start, number = first if day <= first[0] else last
    return number + round((day - start).days / 7)


def tls_headings(lines, titles=()):
    """titled_headings() of a TLS page."""
    return titled_headings(lines, TLS_TITLE, TLS_SOLUTION)


#: The Times crossword's first day, No 1 (a Saturday); it ran six days a
#: week, none on a day the paper was not printed.
TIMES_1930_FIRST = datetime.date(1930, 2, 1)
TIMES_1930_CLOSED = {datetime.date(1930, 4, 18)}  # Good Friday
#: How far a 1930 title's 1-3 digit number may stray from its date's: a
#: misread digit ("200" for 209) lands further off.
TIMES_1930_SLACK = 3


def times1930_expected_number(day):
    n, d = 1, TIMES_1930_FIRST
    while d < day:
        d += datetime.timedelta(days=1)
        n += d.weekday() != 6 and d not in TIMES_1930_CLOSED and (d.month, d.day) != (12, 25)
    return n


#: "THE TIMES CROSSWORD PUZZLE No. 27"; the OCR often reads the number apart
#: from the words, or not at all, splits "CROSS WORD" or "PUZ ZLE", reads
#: "PUBZLE", or runs the next column's words on ahead of "TIMES" (split
#: "TIM ES"); after TIMES any one word stands for CROSSWORD ("ROBSWORD").
_HEAD_1930 = (r"(?:^\W*(?:\S{1,8}\s+){0,3}?cross\s?word|\btim\s?es\W{0,3}\s*(?:cross\s?word|\S{6,10}))"
              r"\W{0,3}\s*pu[zb]\s?[zb]le\W{0,3}")
TITLE_1930 = re.compile(_HEAD_1930 + r"\s*n[o0]\W{0,3}\s*(\d{1,3})(?!\d)", re.IGNORECASE)
TITLE_1930_BARE = re.compile(_HEAD_1930 + r"\s*(?:n[o0]\W{0,3})?\s*\S{0,4}$", re.IGNORECASE)
#: "SOLUTION OF PUZZLE No. 26", under the clues.
SOLUTION_1930 = re.compile(r"^\W*(?:\S{1,2}\s+)?solution\s+(?:of|to)\s+puzzle\s+n[o0]\W{0,3}\s*(\d{1,3})(?!\d)", re.IGNORECASE)


def times1930_headings(lines, titles=()):
    """([(number, box, None)], [(number, box)]) of the 1930 titles and
    solution headings in `lines`. A title whose number was not read takes
    the number after the page's solution heading's; with none, the page
    has no title read here (ocr_titles() reads it)."""
    titles, sols, bare = [], [], []
    for ws in lines:
        text = " ".join(w[4] for w in ws)
        m = SOLUTION_1930.match(text)
        if m:
            sols.append((int(m[1]), box_of(ws)))
            continue
        m = TITLE_1930.search(text)
        if m:
            at = [len(" ".join(w[4] for w in ws[:k])) + (k > 0) for k in range(len(ws))]
            titles.append((int(m[1]), box_of([w for w, a in zip(ws, at) if a >= m.start()]), None))
        elif TITLE_1930_BARE.search(text):
            bare.append(box_of(ws))
    if not titles and bare and len(sols) == 1:
        titles = [(sols[0][0] + 1, bare[0], None)]
    return titles, sols


#: A line that is only "NO 21,610", the number the Gale Times of 2000 (from
#: 2000-03-13) prints on its own row under "THE TIMES CROSSWORD".
BARE_NUMBER = re.compile(r"^\W*n[o0]\W{0,3}\s*([\dTIil][.,]?\s?\d[^\w\s]{0,2}\s?\d\s?\d(?:\s?\d)?)\W*$", re.IGNORECASE)
#: The words of a "THE TIMES CROSSWORD" line, up to "CROSSWORD".
CROSSWORD_END = re.compile(r"[co0]r\s?ossword\W*$", re.IGNORECASE)


def joined_numbers(lines):
    """`lines` with each bare "NO n,nnn" row (BARE_NUMBER) joined to the
    "THE TIMES CROSSWORD" row just over it, starting at the same x, as one
    line (the title's words up to "CROSSWORD", then the number's)."""
    out = list(lines)
    for bare in lines:
        if not BARE_NUMBER.match(" ".join(w[4] for w in bare)):
            continue
        bx0, by0 = bare[0][0], bare[0][1]
        height = max(w[3] for w in bare) - min(w[1] for w in bare)
        for ws in lines:
            if ws is bare or not (-height / 2 <= by0 - ws[0][3] <= height) or abs(ws[0][0] - bx0) > 3 * height:
                continue
            text = ""
            for k, w in enumerate(ws):
                text = (text + " " + w[4]).strip()
                if CROSSWORD_END.search(text):
                    out.append(list(ws[:k + 1]) + list(bare))
                    break
    return out


def times_headings(lines, titles=()):
    """headings() of a Times page: TITLE, and solution headings read against
    its titles and `titles`."""
    found = headings(joined_numbers(lines), TITLE)
    return [(n, box, None) for n, box in found], solution_headings(lines, [n for n, _ in found] + list(titles))


class Paper:
    """One newspaper's run of archive.org items: where its editions are, how
    its titles and solution headings read, the number its date implies, and
    the series its puzzles file as."""

    def __init__(self, key, series, item, name, expected, parse=None, third=0, solution_above=False, margin=40,
                 clues_above=False, shrink=1, slack=None, four=False, title_heights=1):
        self.key, self.series, self.item, self.name, self.expected = key, series, item, name, expected
        #: Its headings parser, (lines, titles) -> headings(): the Times's
        #: (times_headings) unless named.
        self.parse = parse or times_headings
        #: The width of a clue column right of the grid (0: none), whether
        #: the solution grid is printed above its heading, how far left
        #: of the grid the clue numbers may start, and whether the clues are
        #: printed over the grid, the title heading the left column.
        self.third, self.solution_above, self.margin = third, solution_above, margin
        self.clues_above = clues_above
        #: How many times the scans' SCAN_WIDTH its pages are scanned at
        #: (page() and leaf_lines() shrink them to it), and how far a
        #: title's number may stray from the one its date implies.
        self.shrink, self.slack = shrink, NUMBER_SLACK if slack is None else slack
        #: Four clue columns under the grid and no counts printed (the 1930
        #: Times): columns_of_four() reads them, the grid gives the counts.
        self.four = four
        #: How many of a grid's heights over it a title is looked for on a
        #: page with no text (title_bands' far band).
        self.title_heights = title_heights

    def headings(self, lines, titles=()):
        """([(number, box, setter)], [(number, box)]) of the titles and
        solution headings in `lines`; a solution heading is read against
        those titles and `titles`, read elsewhere on the page (a solution
        band holds no title)."""
        return self.parse(lines, titles)

    @property
    def also(self):
        """The papers of the same series in other items whose editions a
        run of this one reads too (ALSO)."""
        return ALSO.get(self.key, ())


#: The 1930 Times: archive.org's pub_times, one item an issue
#: ("per_times_the-times_1930-03-04_45452"), each page scanned 13663px wide.
TIMES_1930 = Paper("times1930", SERIES, re.compile(r"per_times_the-times_(19\d\d)-\d\d-\d\d_\d+$"),
                   "Times crossword puzzle No {:,}", times1930_expected_number, times1930_headings, margin=15,
                   shrink=4, slack=TIMES_1930_SLACK, four=True)
TIMES = Paper("times", SERIES, ITEM, "Times cryptic crossword No {:,}", expected_number)
FT = Paper("ft", "ftcryptic", re.compile(r"FinancialTimes(19\d\d)UKEnglish$"),
           "Financial Times cryptic crossword No {:,}", ft_expected_number, ft_headings)
GUARDIAN = Paper("guardian", "cryptic", re.compile(r"TheGuardian(19\d\d)UKEnglish$"),
                 "Cryptic crossword No {:,}", guardian_expected_number, guardian_headings, third=GUARDIAN_THIRD,
                 solution_above=True, margin=15)
TELEGRAPH = Paper("telegraph", "telegraph", re.compile(r"(?:TheDaily|Sunday)Telegraph(19\d\d)UKEnglish$"),
                  "Telegraph cryptic crossword No {:,}", telegraph_expected_number, telegraph_headings, margin=15,
                  clues_above=True)
#: The Times pages Paul saves from Gale (tools/gale_inbox.py), under a ledger
#: of their own: a run of them, minutes after a page lands, never waits on the
#: full pass holding filed.jsonl for an hour-long slice, and the full pass's
#: Times runs never read them.
GALE = Paper("gale", SERIES, GALE_ITEM, "Times cryptic crossword No {:,}", expected_number)
#: The other papers' Gale pages tools/gale_fetch.py lays out
#: (gale_inbox.OTHERS: Gale<Paper><year>UKEnglish/<date>), one page each.
GALE_TELEGRAPH = Paper("galetelegraph", "telegraph", re.compile(r"GaleTelegraph((?:19|20)\d\d)UKEnglish$"),
                       "Telegraph cryptic crossword No {:,}", telegraph_expected_number, gale_telegraph_headings,
                       margin=15, clues_above=True, title_heights=2)
GALE_FT = Paper("galeft", "ftcryptic", re.compile(r"GaleFT((?:19|20)\d\d)UKEnglish$"),
                "Financial Times cryptic crossword No {:,}", ft_expected_number, ft_headings)
GALE_INDEPENDENT = Paper("galeindependent", "independent", re.compile(r"GaleIndependent((?:19|20)\d\d)UKEnglish$"),
                         "Independent cryptic crossword No {:,}", independent_expected_number, independent_headings)
GALE_SUNDAY_TIMES = Paper("galesundaytimes", "sundaytimes", re.compile(r"GaleSundayTimes((?:19|20)\d\d)UKEnglish$"),
                          "Sunday Times cryptic crossword No {:,}", sunday_times_expected_number,
                          sunday_times_headings, slack=SUNDAY_TIMES_SLACK)
GALE_TLS = Paper("galetls", "tls", re.compile(r"GaleTLS((?:19|20)\d\d)UKEnglish$"), "TLS crossword No {:,}",
                 tls_expected_number, tls_headings, slack=TLS_SLACK)
#: The archive.org papers (coverage counts each series once, off these).
PAPERS = {p.key: p for p in (TIMES, FT, GUARDIAN, TELEGRAPH)}
#: Every --paper a run can read: each ledger's editions.
FILERS = {**PAPERS, GALE.key: GALE, GALE_INDEPENDENT.key: GALE_INDEPENDENT,
          GALE_SUNDAY_TIMES.key: GALE_SUNDAY_TIMES, GALE_TLS.key: GALE_TLS}
#: The papers of the same series in other items whose editions a run of
#: FILERS[key] reads too.
ALSO = {TIMES.key: (TIMES_1930,), TELEGRAPH.key: (GALE_TELEGRAPH,), FT.key: (GALE_FT,)}
#: Every Gale paper but the Times files its puzzles under the document's
#: link.gale.com permalink, so each needs provenance's row for that host: one
#: added without it would file puzzles the validator flags, so it fails here.
_NO_GALE_ROW = sorted({q.series for q in (*FILERS.values(), *(x for v in ALSO.values() for x in v))
                       if q.key.startswith("gale") and q.series != "times"
                       and (q.series, "link.gale.com") not in provenance.ACQUISITION_BY_SOURCE})
if _NO_GALE_ROW:
    raise RuntimeError(f"Gale papers with no (series, 'link.gale.com') row in provenance.ACQUISITION_BY_SOURCE: {_NO_GALE_ROW}")
#: Each run's ledger in the cache, filed.jsonl unless named here.
LEDGER_NAMES = {GALE.key: downloads.GALE_LEDGER.name}
#: The runs whose never-read editions are read latest laid out first (pages
#: downloaded by the Gale fetcher, whose watcher waits to see them filed), not a year at a time.
NEWEST_FIRST = {GALE.key}


def run_papers(paper):
    """`paper` and the papers whose editions a run of it reads too (ALSO)."""
    return (paper, *ALSO.get(paper.key, ()))


def paper_of(d):
    """The Paper an edition directory's item belongs to (memoized by item
    name, and by the directory itself: a read's brief asks it of every
    edition of a paper, the same Path objects each time, where Path(d).parent
    costs more than the dict hit)."""
    hit = _PAPER_OF.get(d)
    if hit is not None:
        return hit
    item = Path(d).parent.name
    hit = _PAPER_OF.get(item)
    if hit is None:
        hit = _PAPER_OF[item] = next((q for p in FILERS.values() for q in run_papers(p) if q.item.match(item)),
                                     TIMES)
    if isinstance(d, Path):
        _PAPER_OF[d] = hit
    return hit


#: {item name or edition Path: paper_of's answer}; FILERS is fixed at import.
_PAPER_OF = {}


def filer_of(rel):
    """The FILERS paper whose run reads edition `rel` ("<item>/<edition>"),
    or None."""
    item = rel.split("/")[0]
    return next((p for p in FILERS.values() if any(q.item.match(item) for q in run_papers(p))), None)


def issues_between(a, b):
    """How many issues (six a week, none on Sunday) follow day `a` up to and
    including the later day `b`."""
    weeks, rest = divmod((b - a).days, 7)
    return weeks * 6 + sum((a + datetime.timedelta(days=i)).weekday() != 6 for i in range(1, rest + 1))


#: {path: ((mtime_ns, size), (date or None, source.url, date's first 10
#: characters))} of each puzzle file held_files has read: a file is read
#: again only when its stat moves, so a worker's every title costs a stat of
#: the series, not a parse of it. held_dates and held_scans share it, so
#: plan()'s warming of it in the queue's process serves both in every unit
#: forked after.
_HELD = {}


#: Paths held_files parsed since save_held last wrote _HELD.
_HELD_MOVED = []

#: {series: held_files(series)} while this thread is inside held_once(): a
#: unit start or a paper's plan reads a series once, not once per asker.
_HELD_NOW = threading.local()


@contextlib.contextmanager
def held_once():
    """Within it, held_files reads each series once (this thread); nested,
    the outer scope's reads stand."""
    if getattr(_HELD_NOW, "files", None) is not None:
        yield
        return
    _HELD_NOW.files = {}
    _HELD_NOW.vlm = []
    try:
        with puzzle_paths.listed_once():  # find_listed's year-folder stats too, once a scope
            yield
    finally:
        _HELD_NOW.files = None
        _HELD_NOW.vlm = None


def vlm_seen():
    """The VLM version the readings now depend on, or None when it is not
    reachable. Inside a held_once scope (a plan) it is probed once: the probe
    is an ssh to the desktop (13-76 s under load) and a plan asked it twice a
    paper (stamp and plan), 16-17 times a plan."""
    memo = getattr(_HELD_NOW, "vlm", None)
    if memo:
        return memo[0]
    seen = vlm.version() if vlm.reachable() else None
    if memo is not None:
        memo.append(seen)
    return seen


def save_held(path):
    """Write _HELD to `path` when held_files parsed a file since the last
    save, for load_held in the next process (a re-exec or the next slice)."""
    if not _HELD_MOVED:
        return
    _HELD_MOVED.clear()
    tmp = f"{os.fspath(path)}.{os.getpid()}.tmp"
    os.makedirs(os.path.dirname(os.fspath(path)) or ".", exist_ok=True)
    # Keyed by str: pickling ~14k Paths (Path.__reduce__ each) was most of a
    # plan's save; load_held makes them Paths again.
    with open(tmp, "wb") as f:
        pickle.dump(dict(list(_HELD.items())), f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def load_held(path):
    """Take the parses save_held wrote to `path` for each file this process
    has not parsed; each stands only while its stat is unmoved (held_files)."""
    try:
        with open(path, "rb") as f:
            snap = pickle.load(f)
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ValueError):
        return
    for k, v in snap.items():
        _HELD.setdefault(k, v)  # str keys: a Path hashes by re-normalising its string


#: {(series, number): its file} as held_files last listed them.
_HELD_PATH = {}
#: {(series, number): its file's year folder name} as held_files last listed them.
_HELD_FOLDER = {}


def held_files(series):
    """[(number, (date or None, source url, date text))] of every puzzle
    filed in a series, each file parsed once a process and again only when
    its stat moves."""
    return list(_held_listing(series)[1])


def _held_listing(series):
    """(version, tuple of held_files' entries) of a series: the version
    moves only when what a listing found differs from the last listing, so
    held_dates and held_scans key their answers on it (a brief inside
    held_once keeps its own listing while another lists afresh). One thread
    lists a series at a time: a re-exec's briefs start together, and each
    parsing the corpus for itself costs minutes of a core."""
    now = getattr(_HELD_NOW, "files", None)
    if now is not None and series in now:
        return now[series]
    with _HELD_LOCKS.setdefault(series, threading.Lock()):
        got = _held_list(series)
    if now is not None:
        now[series] = got
    return got


#: Where each series' parses are kept between processes (a fresh read unit
#: would else parse all ~15k times puzzles, 15 s of CPU, for held_dates):
#: {file path: (stamp, entry)} of one series a file, each entry standing only
#: while its file's (mtime, size) does, as _HELD's. None turns it off.
HELD_SERIES_CACHE = os.path.expanduser("~/.cache/held_dates")
#: {series: when its snapshot was last written (monotonic)}.
_HELD_SAVED = {}
#: Seconds between a series' snapshot writes while files keep being parsed.
HELD_SAVE_EVERY = 30


def _series_snapshot_path(series):
    return os.path.join(HELD_SERIES_CACHE, f"{series}.pickle") if HELD_SERIES_CACHE else None


def _load_series_snapshot(series):
    """Take the parses _save_series_snapshot wrote for a series, for each
    file this process has not parsed."""
    path = _series_snapshot_path(series)
    if path is None:
        return
    try:
        with open(path, "rb") as f:
            snap = pickle.load(f)
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ValueError):
        return
    if isinstance(snap, dict):
        for k, v in snap.items():
            _HELD.setdefault(k, v)


def _save_series_snapshot(series, force=False):
    """Write the series' parses (at most every HELD_SAVE_EVERY seconds; an
    older snapshot only costs the next process a few re-parses)."""
    path = _series_snapshot_path(series)
    now = time.monotonic()
    if path is None or not force and now - _HELD_SAVED.get(series, float("-inf")) < HELD_SAVE_EVERY:
        return
    _HELD_SAVED[series] = now
    prefix = os.fspath(ROOT / "puzzles" / series) + os.sep
    snap = {k: v for k, v in list(_HELD.items()) if k.startswith(prefix)}
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "wb") as f:
            pickle.dump(snap, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    except OSError:
        pass


def _held_list(series):
    # The last listing stands while no year folder moved (a puzzle written
    # by os.replace, filed or removed moves its folder's mtime) and it is
    # under HELD_FRESH seconds old: each read's brief stats ~14k files else.
    # Under HELD_FRESH since the last full listing, only the folders whose
    # mtime moved are listed again (filing one puzzle moves one folder, and
    # the times series alone is ~14k files); a full listing, the backstop
    # for in-place rewrites, comes HELD_FRESH after the one before.
    folders = _held_folders(series)
    hit = _HELD_LISTED.get(series)
    if hit is None:
        _load_series_snapshot(series)
    parsed = 0
    now = time.monotonic()
    if hit is not None and hit[1] == folders and now - hit[0] < HELD_FRESH:
        return hit[2]
    partial = hit is not None and now - hit[0] < HELD_FRESH and len(hit) > 3
    listed_at = hit[0] if partial else now
    out, by_folder = [], {}
    for name, mtime in folders.items():
        if partial and hit[1].get(name) == mtime and name in hit[3]:
            entries = hit[3][name]
        else:
            entries = []
            for de in os.scandir(ROOT / "puzzles" / series / name):
                if not de.name.endswith(".json"):
                    continue
                p = Path(de.path)
                st = de.stat()
                stamp = (st.st_mtime_ns, st.st_size)
                ps = de.path
                seen = _HELD.get(ps)
                if seen is None or seen[0] != stamp:
                    try:
                        d = json.loads(p.read_text())
                    except ValueError:
                        # A write cut off by a kill leaves an empty file: one torn
                        # puzzle mustn't crash every read of its series.
                        print(f"held listing: {p} is not parsable; skipped", file=sys.stderr)
                        continue
                    date = d.get("date")
                    seen = _HELD[ps] = (stamp, (date and datetime.date.fromisoformat(date[:10]),
                                               (d.get("source") or {}).get("url"), (date or "")[:10]))
                    _HELD_MOVED.append(p)
                    parsed += 1
                # The number off the entry's name: Path.stem parses the path (~2 s a full listing).
                entries.append((int(de.name[:-5].split("-")[1]), seen[1], p))
        by_folder[name] = entries
        for number, entry, p in entries:
            out.append((number, entry))
            _HELD_PATH[series, number] = p
            _HELD_FOLDER[series, number] = name
    out = tuple(out)
    if parsed:
        _save_series_snapshot(series)
    if hit is None or hit[2][1] != out:
        _HELD_VERSION[series] = _HELD_VERSION.get(series, 0) + 1
    got = (_HELD_VERSION[series], out)
    _HELD_LISTED[series] = (listed_at, folders, got, by_folder)
    return got


#: {series: threading.Lock} serialising _held_listing's listings of it.
_HELD_LOCKS = {}
#: {series: how many listings of it found something the one before did not}.
_HELD_VERSION = {}


def _held_memo(memo, series, make):
    """make(entries) of the series' current listing, kept per listing
    version (the last HELD_MEMO of them): the same object while the
    listing's content stands."""
    version, files = _held_listing(series)
    by = memo.setdefault(series, {})
    if version not in by:
        by[version] = make(files)
        while len(by) > HELD_MEMO:
            del by[min(by)]
    return by[version]


#: How many listing versions held_dates and held_scans keep answers for: a
#: brief inside held_once may still be on the one before.
HELD_MEMO = 3


#: How long held_files trusts its last listing of a series while no year
#: folder's mtime moved: a backstop for a file rewritten in place.
HELD_FRESH = 60

#: {series: (when held_files last listed every folder of it (monotonic),
#: _held_folders then, (version, its entries), {folder: [(number, entry,
#: path)] as last listed})}.
_HELD_LISTED = {}


def _held_folders(series):
    """{year folder name: its st_mtime_ns} of a series' puzzle folder."""
    try:
        return {e.name: e.stat().st_mtime_ns for e in os.scandir(ROOT / "puzzles" / series) if e.is_dir()}
    except (FileNotFoundError, NotADirectoryError):
        return {}


class Held(dict):
    """{number: date} of a series' filed puzzles, read-only, with its
    (date, number) pairs sorted once: neighbours bisects them and hosted
    looks a day up, where a scan of every filed puzzle per edition costs
    seconds a read start (sister_solutions links every sister edition)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.pairs = sorted((d, m) for m, d in self.items())
        self.numbers = sorted(self)
        self.on_day = {}
        for d, m in self.pairs:
            self.on_day.setdefault(d, []).append(m)

    @classmethod
    def of(cls, held):
        return held if isinstance(held, cls) else cls(held)

    def iso(self):
        """{str(number): date.isoformat()}, worked out once (a desktop
        request carries it every unit)."""
        if getattr(self, "_iso", None) is None:
            self._iso = {str(n): day.isoformat() for n, day in self.items()}
        return self._iso

    def _read_only(self, *a, **k):
        raise TypeError("Held is read-only: make a new one")

    __setitem__ = __delitem__ = __ior__ = update = pop = popitem = setdefault = clear = _read_only


def held_dates(series):
    """{number: date} of every dated puzzle filed in a series (Held): the
    same object while the series' listing finds what it found before
    (_held_listing's version), so a unit start does not sort the corpus
    again and callers may key memos on its identity."""
    return _held_memo(_HELD_DATES, series, lambda files: Held({n: day for n, (day, _, _) in files if day}))


#: {series: {listing version: Held}} of held_dates.
_HELD_DATES = {}


#: Where the Canberra Times reprints of London Times puzzles are cached:
#: Trove's text of each article (tools/fetch_trove.py), our readers' text of
#: its clue columns beside the zones (tools/file_trove_puzzles.page_readings),
#: and the London number of each (tools/canberra_london_numbers.py).
TROVE = ftp.CACHE
#: The series a Canberra reprint is a copy of.
REPRINTED = "times"
#: {London number: [article dirs]}, read once a process.
_REPRINTS = {}


def reprint_files(number, trove=None):
    """[Path] each cached text of the Canberra reprints of London Times
    `number`: Trove's article text and each reader's of its clue columns.
    Only what is cached: nothing is read or fetched here."""
    trove = Path(trove or TROVE)
    if trove not in _REPRINTS:
        import canberra_london_numbers
        by = {}
        for aid, row in canberra_london_numbers.load(trove / "london_numbers.json").items():
            if row.get("number"):
                by.setdefault(int(row["number"]), []).append(trove / aid)
        _REPRINTS[trove] = by
    out = []
    for d in sorted(_REPRINTS[trove].get(int(number), ())):
        out += [p for p in [d / "ocr.txt"] + sorted((ftp.clue_zones(d) / d.name).glob("read.*.txt")) if p.is_file()]
    return out


def reprint_text(text):
    """A reprint reading as a column reading sets it out: its two lists
    alone (the article's page text, solution note and next puzzle cut off),
    one clue a line as "<number> <text> (<count>)", each number as its list's
    order reads it ("I They're" is clue 1, no lost word "I") and a line-end
    hyphen kept at a line end. A list that does not parse is kept cut to
    its lists; None when there are none. Runs of spaces read as one (a
    book's justified line, "Author  of  'Crown  and  Roundhead'")."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    parsed, _ = parse(text)
    if parsed is None:
        secs = ftp.sections(tidy(text))
        return None if secs is None else f"ACROSS\n{secs['across']}\nDOWN\n{secs['down']}\n"
    parsed, _ = ftp.renumber(parsed)
    out = []
    for direction in ("across", "down"):
        out.append(direction.upper())
        for c in parsed[direction]:
            head = ", ".join(str(min(t)) for t in c["tokens"] if t) if c["tokens"] and c["tokens"][0] else ""
            words = re.sub(r"(?<=[A-Za-z])- (?=[A-Za-z])", "-\n", c["text"].strip())
            count = f" ({next(iter(c['enums']))})" if len(c.get("enums") or ()) == 1 else ""
            out.append(f"{head} {words}{count}".strip())
    return "\n".join(out) + "\n"


def book_reprint_files(number, series, root=None):
    """[Path] each book leaf's reading of `series`-`number`: a page of an
    anthology (a Times crossword book) that reprints it, kept by
    tools/acquire_book.py in place of a book-N copy (book_queue.save_reprint)."""
    import book_queue
    return book_queue.reprint_readings(series_meta.puzzle_id(series, number), root)


def reprint_readings(number, series=REPRINTED):
    """{reading name: text} of the reprints of `number` in `series`
    (reprint_text): the Canberra Times's of a Times puzzle and any book's.
    Each is one more copy of the same print, its readings voters beside the
    scan's own (the London scan and the Canberra one misread apart). {} for
    a number no reprint is held of."""
    out = {}
    for p in reprint_files(number) if series == REPRINTED else ():
        text = reprint_text(p.read_text(encoding="utf-8", errors="replace"))
        if text:
            out[f"canberra:{p.parent.name}:{p.stem}"] = text
    out.update(book_readings(number, series))
    return out


def book_readings(number, series):
    """{"book:<leaf>": text} of each book's reprint of `series`-`number`
    (reprint_text)."""
    out = {}
    for p in book_reprint_files(number, series):
        text = reprint_text(p.read_text(encoding="utf-8", errors="replace"))
        if text:
            out[f"book:{p.stem}"] = text
    return out


def book_clues(readings):
    """{light: (clue text, its count or None)} of the book readings among
    `readings` ({name: text}, reprint_readings'), the first book's where
    two print a light."""
    out = {}
    for k, text in readings.items():
        if not k.startswith("book:"):
            continue
        parsed, _ = parse(text)
        if parsed is None:
            continue
        for (n, d), (clue, enums) in numbered(ftp.renumber(parsed)[0]).items():
            if clue and clue.strip():
                out.setdefault(f"{n}-{d}", (clue.strip(), next(iter(enums)) if len(enums or ()) == 1 else None))
    return out


def book_marked(laid, books):
    """`laid` ({light: (text, enum, group)}) with each clue's marks and
    spaces between words as the book's reprint (`books`, book_clues) prints
    them (ocr_clues.reprint_marked): the book's is a second, cleaner print
    of the same clue, and the two vote on them (a book's lost-mark-free
    count too, ocr_clues.reprint_count); the words stay the scan's, the
    newspaper's own."""
    out = {}
    for lid, (t, e, g) in laid.items():
        book, count = books.get(lid) or (None, None)
        out[lid] = (ocr_clues.reprint_marked(t, book) if t and book else t, ocr_clues.reprint_count(e, count), g)
    return out


def reprint_key(numbers, series=REPRINTED):
    """What the reprints of an edition's `numbers` hold (the Canberra Times's
    and the books'), by file name and size: part of the edition's inputs, so
    a reprint downloaded or read after the edition was makes it due. ""
    when there is none."""
    files, books = [], False
    for n in sorted(set(numbers)):
        for p in (reprint_files(n) if series == REPRINTED else []):
            files.append(f"{p.parent.name}/{p.name}:{p.stat().st_size}")
        for pid, name, size in book_reprint_listing(n, series):
            files.append(f"{pid}/{name}:{size}")
            books = True
    if not files:
        return ""
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode())
    if books:
        h.update(f"book vote {BOOK_VOTE}".encode())
    return h.hexdigest()[:16]


def book_reprint_listing(number, series):
    """[(pid, file name, size)] of book_reprint_files' readings: off the
    manifest (media_manifest.book_reprints) when the folder is on the media
    disk, so asking it of every puzzle of a plan stats nothing there; a
    test's own folder is listed and stat'ed."""
    import book_queue
    pid = series_meta.puzzle_id(series, number)
    if media_manifest.on_media(book_queue.REPRINT_DIR):
        return [(pid, name, size) for name, size in media_manifest.book_reprints().get(pid, ())]
    return [(p.parent.name, p.name, p.stat().st_size) for p in book_queue.reprint_readings(pid)]


#: The version of how a book's reprint votes on an edition's clues
#: (book_marked, ocr_clues.run_in, reprint_text): part of reprint_key, so a
#: change to it makes each edition a book reprints due again, and no other.
BOOK_VOTE = 1


def held_scans(series):
    """{(source.url, date): [numbers]} of every filed puzzle in a series that
    names a scan page: one page on one day is one puzzle. Worked out again
    only when the series' listing finds something new (_held_listing's
    version), not every call: a read's brief asks it of the whole corpus.
    Callers must not mutate it."""
    def make(files):
        out = {}
        for n, (_, url, day) in files:
            if url:
                out.setdefault((url, day), []).append(n)
        return out
    return _held_memo(_HELD_SCANS, series, make)


#: {series: {listing version: held_scans' answer}}
_HELD_SCANS = {}


def same_scan(number, url, day, series):
    """Why `number` cannot file (None if it can): another number in the series
    already holds this scan page `url` for `day`, so the OCR misread one
    number."""
    others = [m for m in held_scans(series).get((url, day.isoformat()), ()) if m != number]
    if others:
        return f"No {number} is the scan page No {others[0]} already holds ({url}, {day})"
    return None


def neighbours(day, held):
    """(before, after): the nearest filed (date, number) either side of
    `day` in `held` ({number: date}), each None when there is none."""
    pairs = Held.of(held).pairs
    i, j = bisect.bisect_left(pairs, (day,)), bisect.bisect_right(pairs, (day, math.inf))
    return pairs[i - 1] if i else None, pairs[j] if j < len(pairs) else None


def implied(day, held):
    """The number `day`'s puzzle has when its nearest filed neighbours
    either side run unbroken, one number an issue; else None."""
    before, after = neighbours(day, held)
    if before and after and after[1] - before[1] == issues_between(before[0], after[0]):
        return before[1] + issues_between(before[0], day)
    return None


#: How near the number its date implies a title's number, one digit worth
#: 100 or more mended, must lie (mended_digit): those digits' variants lie
#: 100 apart, so at most one is this near.
DIGIT_SLACK = 10


def mended_digit(n, day, expected, held):
    """The number a title read as `n`, far from the `expected` its date
    implies, names with one digit misread (the 1983 FT's "5,401" for 5,101)
    or lost (the 1930 Times' "8" for 88): the one its filed neighbours imply
    (implied) when that differs from `n` in one digit or by one digit more,
    else, with no such neighbours, the one a digit worth 100
    or more mended puts within DIGIT_SLACK of `expected`; None when neither."""
    text = str(n)
    fixed = implied(day, held)
    if fixed is not None:
        other = str(fixed)
        lost = any(other[:k] + other[k + 1:] == text for k in range(len(other)))
        return fixed if lost or len(other) == len(text) and sum(a != b for a, b in zip(text, other)) == 1 else None
    for k in range(len(text) - 2):
        for digit in "0123456789":
            m = int(text[:k] + digit + text[k + 1:])
            if digit != text[k] and abs(m - expected) <= DIGIT_SLACK:
                return m
    return None


def solution_title(day, sols, held):
    """(number, None) of `day`'s puzzle known only by the solution headings
    `sols` its page prints, or (None, why): the number a count of issues
    from a filed neighbour gives (from both, when they run unbroken:
    implied) of which each heading reads (solution_number) as one
    SOLUTION_LAGS before, when exactly one does. A number no neighbour
    counts to is never filed."""
    fixed = implied(day, held)
    before, after = neighbours(day, held)
    counts = {fixed} if fixed is not None else \
        {m + issues_between(b, day) for b, m in [before] * bool(before)} | \
        {m - issues_between(day, a) for a, m in [after] * bool(after)}
    fits = sorted(n for n in counts
                  if all(solution_number(str(s), {n - lag for lag in SOLUTION_LAGS}) is not None for s in sols))
    if len(fits) == 1:
        return fits[0], None
    return None, (f"no title read; the solution headings No {', '.join(map(str, sols))} fit "
                  f"{'none' if not fits else 'more than one'} of the numbers the filed neighbours give {day}: "
                  f"{sorted(counts) or 'none filed'}")


def linked_solutions(paper, found, held):
    """An edition's Times solution headings `found["solutions"]` as they
    link to puzzles. A heading read as a number its edition does not host
    (a misread of the day before's, or of another paper's) would link a
    stranger, so each stands as the number solution_number reads it as of
    those the edition hosts (hosted), and no title of the edition is (a
    puzzle's solution never prints with it); else it is dropped. A title
    read off a solution heading's own print (heading_titles) is no title."""
    if paper not in (TIMES, GALE) or not found["solutions"]:
        return found["solutions"]
    expected = hosted(found, held)
    printed = {p["number"] for p in found["puzzles"]} - heading_titles(found)
    out = []
    for s in found["solutions"]:
        n = solution_number(str(s["number"]), expected)
        if n is not None and n not in printed:
            out.append({**s, "number": n})
    return out


def heading_titles(found):
    """The numbers of `found`'s titles each read off a solution heading's own print: a title box
    on a heading's leaf, at least HEADING_TITLE_SHARE of it inside that heading's box, its number
    the heading's digits. The 2003-04 Gale Saturday's scan read "Crossword 22,269" and "22,264", its
    two solution headings, as its titles (its own 22,270 unread), so linked_solutions dropped both
    headings as the edition's titles; their solutions_only read found them in the same place. Paul
    10-26: 13 Times puzzles' hosts so read their heading and linked none."""
    out = set()
    for p in found["puzzles"]:
        pb = p.get("box")
        if not pb:
            continue
        area = max(1, (pb[2] - pb[0]) * (pb[3] - pb[1]))
        for s in found["solutions"]:
            sb = s.get("box")
            if not sb or s.get("leaf") != p.get("leaf") or re.sub(r"\D", "", str(s["number"])) != str(p["number"]):
                continue
            w = min(pb[2], sb[2]) - max(pb[0], sb[0])
            h = min(pb[3], sb[3]) - max(pb[1], sb[1])
            if w > 0 and h > 0 and w * h >= HEADING_TITLE_SHARE * area:
                out.add(p["number"])
    return out


#: The share of a title's box within a solution heading's box past which heading_titles takes the
#: title for the heading read again (the 2003-04 Saturdays': over 0.8).
HEADING_TITLE_SHARE = 0.5


def hosted(found, held):
    """The numbers whose solutions an edition `found` may print: the issue
    before each of its titles, and on a Saturday title the Saturday
    before's prize; a filed puzzle one issue before a day of the edition,
    or its Saturday a week before, or one whose host_days name the day (past
    a day with no paper). A title may be misread, so the numbers
    its filed neighbours in `held` ({number: date}) within SOLUTION_DAYS
    count to stand as titles too, unless one is a title read. A puzzle whose
    next issue is missing is hosted by none: the week-later issue prints
    another's."""
    day = datetime.date.fromisoformat(found["date"])
    before, after = neighbours(day, held)
    own = [p["number"] for p in found["puzzles"] if "fromSolutions" not in p]
    near = [(d, m) for d, m in filter(None, (before, after)) if abs((d - day).days) <= SOLUTION_DAYS]
    counts = {m + issues_between(d, day) if d < day else m - issues_between(day, d) for d, m in near}
    days = {t: issue_day(day, t, own, found.get("item")) for t in own}
    if not counts & set(own):
        days.update({m: day for m in counts if m not in days})
    on = set(days.values()) | {day}
    one = datetime.timedelta(days=1)
    prior = {h - one - one * ((h - one).weekday() == 6) for h in on} | \
        {h - 7 * one for h in on if h.weekday() == 5} | {h - 9 * one for h in on if prize_monday(h)} | \
        {d for h in on for d in hosts_of(h)}
    return {t - 1 for t in days} | {t - 6 for t, d in days.items() if d.weekday() == 5} | \
        {t - PRIZE_LAG for t, d in days.items() if prize_monday(d)} | \
        {m for d in prior for m in Held.of(held).on_day.get(d, ())}


#: The first day a Monday prints the Saturday before's prize solution (PRIZE_LAG).
PRIZE_MONDAYS = datetime.date(2000, 1, 1)


def prize_monday(day):
    """Whether `day` is a Monday that prints the solution of the prize of the Saturday nine days
    before (PRIZE_LAG: the Gale Times from 2000)."""
    return day.weekday() == 0 and day >= PRIZE_MONDAYS


def hosted_window(paper, found):
    """(first, last) date of the filed puzzles linked_solutions(paper, found,
    held) reads of `held`, or None when it reads none: hosted's neighbours
    count only within SOLUTION_DAYS of the edition's day, and its prior days
    lie at most HOST_REACH days before a day the edition's titles print on. Two helds
    alike between them link alike (solution_sources)."""
    if paper not in (TIMES, GALE) or not found["solutions"] or not found.get("date"):
        return None
    day = datetime.date.fromisoformat(found["date"])
    own = [p["number"] for p in found["puzzles"] if "fromSolutions" not in p]
    on = {issue_day(day, t, own, found.get("item")) for t in own} | {day}
    span = datetime.timedelta(days=SOLUTION_DAYS)
    return min(day - span, *(h - datetime.timedelta(days=HOST_REACH) for h in on)), max(day + span, max(on))


def held_between(held, window):
    """The (date, number) pairs of `held` dated within `window` (hosted_window)."""
    if window is None:
        return ()
    pairs = Held.of(held).pairs
    return tuple(pairs[bisect.bisect_left(pairs, (window[0],)):bisect.bisect_right(pairs, (window[1], math.inf))])


def placed(n, day, held, vouched=False):
    """(number, None) that an edition of `day` read as No `n` files as, or
    (None, why) it cannot file. The edition's date is trusted over a number
    OCR read: when the nearest filed puzzles either side run unbroken, one
    number an issue, the date fixes the number (implied); otherwise No `n`
    must sit in date order among them and not be filed for another day.

    A `vouched` title (its page prints the solution of No `n` - 1, the issue
    before: filed_number) is not overruled by the count: the count is only as
    good as the neighbours it counts from and the days it counts, and one
    filed a number off, or a day the paper skipped (Christmas Day), turns a
    whole run of right titles into wrong numbers. Times 22129, filed for
    2002-08-28 (whose page prints No 22130 over the solution of 22129), and
    22232 on 2002-12-26 "ran unbroken" over 25 December, so every title
    between them filed one low and the real 22130 was refused as taken. A
    vouched title still sits in date order and on no other day's number. Only
    one issue off the count: further off, the OCR misread the same digit in the
    title and the heading (1968-07-24's "11999" over "11998" for 11909), and the
    count stands."""
    before, after = neighbours(day, held)
    fixed = implied(day, held)
    if fixed is not None and not (vouched and abs(fixed - n) == 1):
        return fixed, None
    if n in held and held[n] != day:
        return None, f"No {n} is already filed for {held[n]}, not {day}"
    if before and n <= before[1] or after and n >= after[1]:
        return None, (f"No {n} on {day} is out of date order with "
                      f"{' and '.join(f'No {m} on {d}' for d, m in (before, after) if d)}")
    return n, None


#: A Gale item, Gale<Paper><year>UKEnglish/<date> (gale_inbox, gale_fetch):
#: each edition is one page of that day's paper, binding no other day.
ONE_DAY_ITEM = re.compile(r"Gale[A-Za-z]+(?:19|20)\d\dUKEnglish$")


def issue_day(day, n, numbers, item=""):
    """The date of No `n` in an edition dated `day` holding `numbers`: an item
    can bind the next days' papers too, so each number above the lowest is one
    issue later (six a week, none on Sunday), but only while `numbers` run
    unbroken from the lowest up to `n`. Across a gap the lowest is a stray read
    (a solution heading, a misread), not an earlier issue, and No `n` keeps
    the edition's date. A Gale page (ONE_DAY_ITEM) binds one day only, so a
    lower number on it is always a stray: Monday 9 April 2001's page tells
    "The solution to Saturday's Prize Crossword 21,696 will appear next
    Saturday" beside No 21,697, which had filed as Tuesday's."""
    if ONE_DAY_ITEM.match(item or ""):
        return day
    low = min(numbers)
    if n - low > 6 or not set(range(low, n + 1)) <= set(numbers):
        return day
    for _ in range(n - low):
        day += datetime.timedelta(days=1 + (day.weekday() == 5))
    return day


#: An archive.org FT edition dir's name, "<date>_<issue>": the date its item
#: title gives and the masthead's issue number, one an issue (six a week,
#: none on Sunday). The titles are wrong now and then (#26722 is titled
#: Jul 16 1975 between #26721 of Jul 18 and #26723 of Jul 21), and so are the
#: issue numbers (#26664 for #26655 on 1 May 1975), so issue_dated weighs
#: each against the other.
EDITION_ISSUE = re.compile(r"(\d{4}-\d\d-\d\d)_(\d+)$")
#: How many issues from the item title's date a date its puzzle number's
#: filed neighbours count to may lie for numbered_day to move it there.
MOVE_ISSUES = 6


def issue_step(day, k):
    """The day `k` issues after `day` (before it, `k` negative): six a week,
    none on Sunday."""
    one = datetime.timedelta(days=1 if k > 0 else -1)
    for _ in range(abs(k)):
        day += one
        day += one * (day.weekday() == 6)
    return day


def edition_issues(names):
    """[(issue, date)] of the "<date>_<issue>" edition dir `names`."""
    return _edition_issues(tuple(names))


@functools.lru_cache(maxsize=256)
def _edition_issues(names):
    """edition_issues of a tuple, kept: a plan weighs every FT edition."""
    out = []
    for m in filter(None, map(EDITION_ISSUE.match, names)):
        try:
            out.append((int(m.group(2)), datetime.date.fromisoformat(m.group(1))))
        except ValueError:
            continue
    return out


def item_editions(d, found):
    """The edition dir names of `d`'s item: the scan's `editions` when the
    request carries them (a desktop read holds only its own edition's dir),
    else the item's listing."""
    return found.get("editions") or dir_cache.listed(d.parent)


def issue_dated(name, day, names):
    """(day, None, sure) the edition dir `name` ("<date>_<issue>"), its item
    title dating it `day`, prints, among its item's edition dir `names`; or
    (None, why, False) when nothing settles it. The editions numbered either
    side of its issue (the nearest, each number held by one edition only)
    weigh the title: a date strictly between theirs and no Sunday stands
    (`sure` when both count to it, one number an issue). Else the day both
    count to stands (`sure`), unless another edition is dated it: then the
    issue number is the misread. Else a title date no other edition holds and
    no Sunday stands, not sure; a clashing one is refused."""
    m = EDITION_ISSUE.match(name)
    if not m:
        return day, None, False
    issue = int(m.group(2))
    eds = [(i, e) for i, e in edition_issues(names) if f"{e.isoformat()}_{i}" != name]
    count = collections.Counter(i for i, _ in eds)
    once = [(i, e) for i, e in eds if count[i] == 1 and i != issue]
    below = max((p for p in once if p[0] < issue), default=None)
    above = min((p for p in once if p[0] > issue), default=None)
    counted = [issue_step(e, issue - i) for i, e in filter(None, (below, above))]
    if day.weekday() != 6 and (not below or below[1] < day) and (not above or day < above[1]):
        return day, None, len(counted) == 2 and counted[0] == counted[1] == day
    dated = {e for _, e in eds}
    if len(counted) == 2 and counted[0] == counted[1] and counted[0] not in dated:
        return counted[0], None, True
    if day.weekday() != 6 and day not in dated:
        return day, None, False
    return None, (f"edition {name} is dated {day}{' (a Sunday)' * (day.weekday() == 6)}, out of order with "
                  f"{' and '.join(f'#{i} of {e}' for i, e in filter(None, (below, above))) or 'no other edition'}, "
                  f"which do not settle its date"), False


def numbered_either_side(n, held):
    """(lo, hi): the nearest filed numbers below and above `n` in `held`
    ({number: date}), each None when there is none."""
    numbers = Held.of(held).numbers
    i, j = bisect.bisect_left(numbers, n), bisect.bisect_right(numbers, n)
    return numbers[i - 1] if i else None, numbers[j] if j < len(numbers) else None


def numbered_day(n, held):
    """The day the filed puzzles numbered either side of No `n` in `held`
    ({number: date}) both count to, one number an issue, or None when
    either is missing or they disagree."""
    lo, hi = numbered_either_side(n, held)
    if lo is None or hi is None:
        return None
    day = issue_step(held[lo], n - lo)
    return day if day == issue_step(held[hi], n - hi) else None


def ft_dated(n, day, held, sure):
    """(day, None) No `n`, printed in an FT edition the item title (issue_dated
    weighed) dates `day`, files for, or (None, why). A date another number is
    filed for, or not strictly between the dates of the filed puzzles
    numbered either side of `n`, clashes: the day those count to (numbered_day,
    within MOVE_ISSUES) stands instead when it is free, unless the edition's
    issue neighbours vouch for `day` (`sure`) and nothing is filed for it,
    when the number is the misread (placed: ftcryptic-2262, from #26148
    titled Aug 30 1973, files for Aug 31 between 2261 on Aug 30 and 2264 on
    Sep 3)."""
    held = Held.of(held)
    on = [m for m in held.on_day.get(day, ()) if m != n]
    lo, hi = numbered_either_side(n, held)
    clash = on or (lo is not None and held[lo] >= day) or (hi is not None and held[hi] <= day) \
        or n in held and held[n] != day
    if not clash:
        return day, None
    moved = numbered_day(n, held)
    free = moved is not None and moved.weekday() != 6 and not held.on_day.get(moved) \
        and held.get(n, moved) == moved
    if free and (on or not sure) and abs(moved - day).days <= MOVE_ISSUES * 7 / 6 + 1:
        return moved, None
    if on:
        return None, f"No {n} on {day}: No {on[0]} is filed for that day and its neighbours do not settle another"
    return day, None


def filed_number(d, found, hit):
    """(number, day, None) that a title files as, or (None, day, why) it is
    refused."""
    n = hit["number"]
    paper = paper_of(d)
    edition = datetime.date.fromisoformat(found["date"])
    sure = False
    if paper is FT:
        dated, why, sure = issue_dated(d.name, edition, item_editions(d, found))
        if why:
            return None, edition, why
        edition = dated
    day = issue_day(edition, n, [h["number"] for h in found["puzzles"]], found.get("item"))
    if paper in (TIMES, GALE) and day.weekday() == 6:
        return None, day, f"{day} is a Sunday and the Times prints no daily cryptic on it: a Sunday paper's puzzle"
    held = held_dates(paper.series)
    if paper is FT:
        moved, why = ft_dated(n, day, held, sure)
        if why:
            return None, day, why
        day = moved
    if "fromSolutions" in hit:
        n, why = solution_title(day, hit["fromSolutions"], held)
        if why:
            return None, day, why
    if abs(n - paper.expected(day)) > paper.slack:
        # A short number misread ("200" for 209): the page's solution
        # heading names the day before's.
        sols = [s["number"] + 1 for s in found["solutions"] if s["leaf"] == hit["leaf"]]
        n = next((m for m in sols if abs(m - paper.expected(day)) <= paper.slack), n)
    if abs(n - paper.expected(day)) > paper.slack:
        n = mended_digit(n, day, paper.expected(day), held) or n
    if abs(n - paper.expected(day)) > paper.slack:
        return None, day, (f"No {n} is not near the {paper.expected(day)} the date "
                           f"{day} implies: the item's date is wrong")
    # The title as read, and the page's heading of the issue before's solution
    # reading one less: two prints agreeing, which a count of issues may not overrule.
    vouched = n == hit["number"] and any(s["number"] == n - 1 for s in found["solutions"]
                                         if s.get("leaf", hit["leaf"]) == hit["leaf"])
    number, why = placed(n, day, held, vouched)
    if number is not None:
        why = same_scan(number, page_url(d, found, hit["leaf"]), day, paper.series)
    return number, day, why


#: Why a title was refused: the verdict's `cause`, which tools/coverage.py
#: buckets by. `refused` keeps the detail for a person.
REFUSALS = ("number-date-mismatch", "not-a-grid", "no-reading-parses", "crashed")
#: {cause: ISO time}: an edition a title of which was refused for `cause`
#: and read before that time is read again (due_reason), when the code
#: behind that refusal changes; the rest of the corpus is not.
REREAD_REFUSED = {"not-a-grid": "2026-10-19T02:29:00+00:00", "no-reading-parses": "2026-10-19T01:44:00+00:00",
                  "number-date-mismatch": "2026-10-09T10:00:00+00:00",
                  # The crashes since fixed: the 6144 MB RLIMIT_AS bad_alloc (launcher's CT_UNIT_MEMORY_MB),
                  # an unreadable band_words cache, trove_solution_ocr's unloaded word list.
                  "crashed": "2026-10-19T00:56:00+00:00"}

#: {writeFailed message: ISO time}: an edition a puzzle of which failed to
#: write with that message and was read before that time is read again
#: (fix_reason) as "refused writeFailed before its fix". A writeFailed verdict
#: has no `cause`, so REREAD_REFUSED cannot name it.
REREAD_WRITE_FAILED = {
    # 107 FT 1992-93 editions: a clue with no "text" (a blank one) raised in the write path,
    # held in their ledger rows since; blank clues are now held, never a crash.
    "KeyError: 'text'": "2026-10-19T04:41:00+00:00"}


def refuse(verdict, cause, why):
    """`verdict` refused for `cause` (one of REFUSALS), `why` the detail."""
    if cause not in REFUSALS:
        raise ValueError(f"refusal cause {cause!r} is not one of {REFUSALS}")
    verdict["refused"], verdict["cause"] = why, cause
    return verdict


#: Readings that must print a clue as filed (the same words) for it to stand
#: with no VLM look: the scan's own readers (djvu, RapidOCR's two, Tesseract,
#: the reprint) are several, and one alone may be the misread.
OCR_CONFIRM = 2


def words_of(text):
    """A clue's letters and digits, lower case, accents folded, for comparing readings."""
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", (text or "").lower()))


#: A clue's last word that a cross-reference or more words must follow: a clue every reader
#: ends there lost what came after it (Gale 2005-03-17's 13 down "Separated but linked, like",
#: the "21" all of them dropped), which only the image has, so the light is weak.
OPEN_END = re.compile(r"(?<=\s)(?:like|see|of|and|the|a|an|with|than|versus|between)$")


def weak_lights(read, laid, blank, lengths, confirmed=()):
    """The lights whose clue the scan's own readers do not settle: blank, or
    printed as filed by fewer than OCR_CONFIRM readings of `read`. `confirmed`:
    lights whose filed clue the variant readings (ocr_retry) printed too."""
    weak = set()
    for lid in lengths:
        text = (laid.get(lid) or ("",))[0]
        if not text.strip() or lid in blank or OPEN_END.search(text.strip()):
            weak.add(lid)
            continue
        if lid in confirmed:
            continue
        if re.fullmatch(r"See \d+", text.strip()) and see_settled(read, lid, parse, lengths) == text.strip():
            continue
        mine = words_of(text)
        # Each reading as filed clues are: its own slips mended first, so
        # a count or a drop capital left in one reading is no disagreement.
        enum = laid[lid][1]
        agreeing = sum(1 for t, _ in ocr_clues.readings_for(read, lid, parse)
                       if words_of(clue_repair.mend_text(t, enum)) == mine)
        if agreeing < OCR_CONFIRM and not re.match(r"\d", text):
            # A reading's own number run into its clue ("2 Foozle" for 22).
            agreeing = sum(1 for t, _ in ocr_clues.readings_for(read, lid, parse)
                           if words_of(clue_repair.mend_text(clue_repair.leaked_number(t, lid), enum)) == mine)
        if agreeing < OCR_CONFIRM:
            agreeing = sum(1 for t in read.values() if prints_clue(t, mine))
        if 0 < agreeing < OCR_CONFIRM:
            # A reading with one slip of its own in a word the other printed right ("fourish",
            # "simp!y", "curé" read "cure") is no disagreement with a clue another prints whole.
            agreeing += sum(1 for t, _ in ocr_clues.readings_for(read, lid, parse)
                            if words_of(clue_repair.mend_text(t, enum)) != mine
                            and clue_repair.slip_of(text, clue_repair.mend_text(t, enum)))
        if agreeing < OCR_CONFIRM and words_confirmed(text, enum, ocr_clues.readings_for(read, lid, parse)):
            continue
        if agreeing < OCR_CONFIRM:
            weak.add(lid)
    return weak


#: The fewest words a clue has for words_confirmed: a shorter one is one slip from another word.
CONFIRM_WORDS = 4


def words_confirmed(text, enum, readings):
    """Whether every word of the filed clue `text` is printed by OCR_CONFIRM of the `readings`
    ((text, ...) per reader, each mended first): the vote's own rule, word by word, for a clue
    no two readers print whole because each has a slip of its own in another word (FT 1985:
    "Lily's head replaced by song in jaunty manner" read three ways, each missing a different
    letter). Not a clue with a figure or a short one."""
    if re.search(r"\d", text):
        return False
    laid = re.findall(r"[a-z']+", quotes.straight(text).lower())
    if len(laid) < CONFIRM_WORDS:
        return False
    sets = [set(re.findall(r"[a-z']+", quotes.straight(clue_repair.mend_text(t, enum)).lower()))
            for t, _ in readings]
    if len(sets) < OCR_CONFIRM:
        return False
    return all(sum(w in s for s in sets) >= OCR_CONFIRM for w in laid)


def retry_weak(img, key, cols, read, laid, blank, lengths, tail):
    """(laid, blank, {light: variant text}) with each weak light (weak_lights of what `tail`
    makes of the readings so far) a blank clue the variant readings settle (ocr_retry, the
    CPU's pass before the VLM is asked) filled by that text, held to the readings as the
    VLM's pick is. A weak light that has a clue keeps it: the variants only confirm it
    (the returned text is the one they printed)."""
    if not ocr_retry.enabled():
        return laid, blank, {}
    t_laid, t_blank, _ = tail(laid, blank)
    weak = {lid for lid in weak_lights(read, t_laid, t_blank, lengths) if lid in laid}
    if not weak:
        return laid, blank, {}
    readings = {lid: [t for t, _ in ocr_clues.readings_for(read, lid, parse)] for lid in weak}
    try:
        got = ocr_retry.retry(img, key, cols, weak, readings,
                              lambda t, lid: clue_repair.mend_text(t, laid[lid][1]))
    except Exception as e:  # the retry only spares asks: a failure of its own leaves the page as read without it
        print(f"ocr_retry: {key}: {type(e).__name__}: {e}", file=sys.stderr)
        return laid, blank, {}
    laid, blank, voted = dict(laid), dict(blank), {}
    for lid, text in got.items():
        mine = (laid[lid][0] or "").strip()
        if mine and lid not in blank:
            if words_of(clue_repair.mend_text(text, laid[lid][1])) == words_of(clue_repair.mend_text(mine, laid[lid][1])):
                voted[lid] = text
            continue
        cands = ocr_clues.candidates(read, lid, parse)
        filled = ocr_clues.trimmed(ocr_clues.held(ocr_clues.clean(ocr_clues.strip_count(text)), cands), lid)
        if ocr_clues.tokens(filled) and not ocr_clues.merged(filled):
            laid[lid] = (filled, laid[lid][1], laid[lid][2])
            blank.pop(lid, None)
            voted[lid] = text
    return laid, blank, voted


def log_vlm_corpus(key, cols, read, lengths, parse, laid):
    """Append a corpus row (ocr_retry.record) for each light the VLM's column reading answered
    that fewer than OCR_CONFIRM of the scan's own readers printed alike: the OCR's readings next to
    the VLM's, which readers matched. Not in a dry run (it replays what is already cached)."""
    if vlm.dryrun():
        return
    for lid in lengths:
        theirs = ocr_clues.readings_for({"vlm": read["vlm"]}, lid, parse)
        if not theirs:
            continue
        enum = (laid.get(lid) or (None, None))[1]
        mine = words_of(clue_repair.mend_text(theirs[0][0], enum))
        per = {k: got[0][0] for k, t in read.items() if k != "vlm"
               if (got := ocr_clues.readings_for({k: t}, lid, parse))}
        matched = [k for k, t in per.items() if words_of(clue_repair.mend_text(t, enum)) == mine]
        if len(matched) >= OCR_CONFIRM:
            continue
        lines, _ = ocr_retry.clue_lines(cols, lid)
        box = [min(l[2] for l in lines), min(l[0] for l in lines), max(l[3] for l in lines),
               max(l[1] for l in lines)] if lines else None
        ocr_retry.record(key, lid, box, per, theirs[0][0], matched)


def leaked_laid(read, laid, blank, parse):
    """(laid, blank) with each blank light laid from the clue two readings
    print alike once the number each ran into it is taken off
    (clue_repair.leaked_number): the vote found no two readings alike only
    for those figures. unfit_blanked() checks the text again."""
    laid, blank = dict(laid), dict(blank)
    for lid in list(blank):
        if (laid.get(lid) or ("",))[0].strip():
            continue
        seen = {}
        for t, _ in ocr_clues.readings_for(read, lid, parse):
            t = clue_repair.mend_text(clue_repair.leaked_number(t, lid), (laid.get(lid) or (None, None))[1])
            seen.setdefault(words_of(t), []).append(t)
        best = max(seen.items(), key=lambda kv: len(kv[1]), default=None)
        if best and len(best[0]) >= RUN_LETTERS and len(best[1]) >= OCR_CONFIRM:
            laid[lid] = (best[1][0], laid[lid][1] if lid in laid else None, laid[lid][2] if lid in laid else None)
            del blank[lid]
    return laid, blank


def see_readings(read, lid, parse, lengths):
    """The "See N" texts ("See 5") the readings print for the light `lid`: each reading whose
    clue for it is only a cross-reference to another numbered light of the grid."""
    n, direction = lid.split("-")
    out = []
    for t in read.values():
        parsed, _ = parse(t) if t.strip() else (None, None)
        for c in (parsed or {}).get(direction, []):
            if c["tokens"] and int(n) in c["tokens"][0]:
                if (c["see"] is not None and len(c["tokens"]) == 1 and c["see"] != int(n)
                        and any(f"{c['see']}-{d}" in lengths for d in ("across", "down"))):
                    out.append(f"See {c['see']}")
                break
    return out


def see_settled(read, lid, parse, lengths):
    """The "See N" clue OCR_CONFIRM readings print alike for `lid`, else None."""
    seen = collections.Counter(see_readings(read, lid, parse, lengths))
    best = seen.most_common(1)
    return best[0][0] if best and best[0][1] >= OCR_CONFIRM else None


def see_laid(read, laid, blank, lengths, parse):
    """(laid, blank) with each blank light laid as "See N", the filed form of a linked clue's
    tail, when OCR_CONFIRM readings print it as only a cross-reference ("12 See 5 across"):
    it carries no clue words or count for the vote to settle, so it was left to the VLM."""
    laid, blank = dict(laid), dict(blank)
    for lid in list(blank):
        if (laid.get(lid) or ("",))[0].strip() or lid not in lengths:
            continue
        text = see_settled(read, lid, parse, lengths)
        if text:
            laid[lid] = (text, None, None)
            del blank[lid]
    return laid, blank


#: The fewest letters a clue has for a reading to print it as a run inside its
#: text (prints_clue): a shorter one could be a stretch of any other clue.
RUN_LETTERS = 14


def prints_clue(text, mine):
    """Whether one reading's `text` prints the clue (`mine`: its words_of)
    whole, though its parse does not give the light that clue: the reader lost
    the clue's number ("4 These go before us" read "These go before us"), or
    ran the clue's count into the next column's text ("(6) nem EDGES
    PuattsuiN"). The reading's letters hold the clue's letters unbroken."""
    return len(mine) >= RUN_LETTERS and mine in words_of(text)


def columns_with(cols, lights, all_if_lost=False):
    """The indexes of the clue columns that hold a number of `lights`
    ("N-across"): a number in no column's lines is not asked for (every
    column read for it cost a full page of asks, and a clue outside the
    crop, or one no reading has a line for, is in none of the crops the VLM is
    shown), so the set may be empty. `all_if_lost`: None instead (then every
    column is read) when a number is in no column. `cols`: each reading's
    columns() output."""
    want = {int(lid.split("-")[0]) for lid in lights}
    got, seen = set(), set()
    width = max((len(c) for c in cols), default=0)
    for i in range(width):
        text = "\n".join(column_text([c[i]]) for c in cols if i < len(c))
        for m in re.finditer(r"^\s*(\d{1,2})\b", text, re.M):
            if int(m.group(1)) in want:
                got.add(i)
                seen.add(int(m.group(1)))
    return None if all_if_lost and not seen >= want else got


def why_lights(lights, blank=(), cap=6):
    """A space-free list of `lights` ("12-across" -> "12a") for vlm_asks.log's why= field, each
    marked "(blank)" when in `blank`, else "(unsettled)"; at most `cap`, then "+N"."""
    names = sorted(lights, key=lambda l: (int(l.split("-")[0]), l))
    out = [f"{l.split('-')[0]}{l.split('-')[1][:1]}({'blank' if l in blank else 'unsettled'})" for l in names[:cap]]
    return ",".join(out) + (f",+{len(names) - cap}" if len(names) > cap else "")


def read_page_why(why, *args, **kw):
    """read_page with every ask it spools tagged `why` in vlm_asks.log (logging only)."""
    with vlm.because(why):
        return read_page(*args, **kw)


def fallback_futile(paper, d):
    """True for a page whose "no reading parses" refusal the VLM's every-column read has
    not turned into a puzzle: the 10-21 vlm_asks.log (5h) has 19 such reads (104 asks) of
    FT 1981 (8 reads, 32 asks: the clues stand left of the grid and the page's foot ads are
    read for them) and Gale 1960-66 (11 reads, 88 asks) and not one filed. The page ends
    refused, as it did after the asks."""
    year = d.name[:4]
    return (paper.key == "ft" and year == "1981") or (paper.key == "gale" and "1960" <= year <= "1966")


def read_puzzle(d, found, hit, solutions, ocr_first=True):
    """(verdict, puzzle or None) for one title on one page. The scan's own
    readers read it first; the desktop's VLM (one at a time, ~8 asks a
    minute) is asked only for the clue columns that hold a clue they leave
    blank or do not settle (weak_lights), every column when the grid does not
    lie on them or nothing parses. A page they settle is filed with no ask."""
    if (hit or {}).get("heldTitle"):
        # The title the page's scan lost, its held puzzle's (HELD_TITLE): the answers alone, never a full
        # read (the page has no title box to lay its clues from); no VLM ask but for a HELD_STRIPS reread
        # (_HELD_ASK), and then only of a grid that proves the held puzzle's (answers_only: held_proven).
        got = answers_only(d, found, hit, solutions, ask_vlm=d is not None and d.name in _HELD_ASK["names"],
                           crossed=True)
        return got or ({"number": hit["number"], "leaf": hit["leaf"], "heldTitle": True,
                        "skip": "a held title read answers-only: no linked solution grid gave its answers"}, None)
    if not ocr_first:
        return read_page_why("direct:no-ocr-first", d, found, hit, solutions, None)
    cheap = answers_only(d, found, hit, solutions)
    if cheap is not None:
        return cheap
    verdict, puzzle = read_page(d, found, hit, solutions, False)
    weak = verdict.pop("_weak", None)
    window = verdict.pop("_alt", None)
    dead = verdict.pop("_dead", None)
    # The VLM is shown the window the readers settled on, not the layout's
    # again (read_page's `first`); passed only when there is one.
    ask_with = {"first": window} if window is not None else {}
    if dead:
        ask_with["dead"] = dead
    if puzzle is None:
        if verdict.get("cause") == "no-reading-parses" or "pending" in verdict:
            if held_settled(d, verdict):
                return verdict, puzzle
            if verdict.get("cause") == "no-reading-parses" and fallback_futile(paper_of(d), d):
                verdict["vlmSkipped"] = "no reading parses here, and the VLM's every-column read rescued none of these pages"
                verdict["vlmAsks"] = 0
                return verdict, puzzle
            # the VLM's page
            return read_page_why(f"fallback:{verdict.get('cause') or 'pending'}", d, found, hit, solutions, None)
        return verdict, puzzle
    twin = held_copy(d, verdict, puzzle)
    if twin:
        # The readers' own list is a held puzzle's already: the write refuses it as a copy
        # whatever the VLM adds (the 10-20 log: 28 reads, 95 asks "page served the clues of
        # book-...", every one filed by the readers' complete list before the asks).
        verdict["vlmSkipped"] = f"the readers' clues are {twin}'s: a copy is refused whatever the VLM reads"
        verdict["vlmAsks"] = 0
        return verdict, puzzle
    if weak is None:
        if held_settled(d, verdict):
            return verdict, puzzle
        return read_page_why("fallback:no-weak-info", d, found, hit, solutions, None)
    if not weak and verdict.get("grid") == "image" and "imageDisagrees" not in verdict:
        verdict["vlmAsks"] = 0
        return verdict, puzzle
    if held_settled(d, verdict):
        return verdict, puzzle
    off = disagreeing(verdict)
    if verdict.get("grid") != "image" or off is None:
        return read_page_why("fallback:grid-not-image", d, found, hit, solutions, None, **ask_with)
    blanks = verdict.get("blank") or ()
    if not off:
        return read_page_why("weak:" + why_lights(weak, blanks), d, found, hit, solutions, sorted(weak), **ask_with)
    # The grid disagrees with a light the readers name (FT 1985-09-13: 13-across's count read
    # "5,8,2" on a 10-letter light): only the columns holding it and the weak lights are read
    # (every column cost 3 reads there for one weak light), and the readers' own puzzle
    # stands for every other light. A pass shown part of the columns leads and lays the page
    # differently (that page lost 26-down to a blank and 21-down read "out THE ward"), so it
    # gives only the lights it was asked about, and a light the readers left blank.
    # A light the grid disagrees with that the readers still laid (a loose lay needs a count reading
    # that fills the light) with the clue printed by OCR_CONFIRM readers is not weak: its count
    # slip (14 for 4, 5 for 5,5) is settled by the grid's length, so it is not asked about. A
    # light no reading laid is blank, so weak, and still asked. The 10-21 vlm_asks.log: 174
    # pages / 492 reads tagged "count:", 8 pages (10 reads) with no weak light in the tag.
    # (A light the puzzle holds with no text or count, or a speck in its text, is merged_read's to
    # take from the VLM's column too, so it is asked.)
    # The off light's column read is also where a neighbour light's missing count or speck is
    # mended (FT 1981-06-15, 07-23: 3 of 10 sampled pages), so the light stays asked unless
    # every light of the puzzle is whole.
    loose_ends = {f"{e['number']}-{e['direction']}" for e in puzzle.get("entries") or ()
                  if not settled_light(puzzle, f"{e['number']}-{e['direction']}")}
    asked = set(weak) | ({k for k in off} | loose_ends if loose_ends else set())
    if not asked:
        verdict["vlmAsks"] = 0
        return verdict, puzzle
    v, p = read_page_why("count:" + why_lights(off, blanks) + (";weak:" + why_lights(weak, blanks) if weak else ""),
                         d, found, hit, solutions, sorted(asked), **ask_with)
    return merged_read(verdict, puzzle, v, p, asked)


#: The prompt of the VLM's one ask about a light the solution grid's cells left unread.
SOLUTION_PROMPT = Path(__file__).resolve().parent / "vlm_solution_prompt.md"


#: The least probability the cell classifier gives each letter of a word the VLM names. The VLM
#: reads a strip of squares as a word it expects: PLAT for FLAT (the classifier gave P 0.0004),
#: BISCUITS for BESOUGHT (0.0); the 17 it read right gave every letter 0.0078 or more.
VLM_FLOOR = trove_solution_ocr.CLASS_FLOOR

#: How likely the cell classifier must read each letter of a VLM word no list holds (vlm_word's
#: unlisted_word): the VLM and the classifier then both read the name. The VLM's wrong unlisted
#: words on 1940s-50s Times strips (STROGONOFF, MADITANA, BAROSMIA) each had a letter at 0.38 or
#: less; its right ones (PERSHORE, HARPAGON, DUNVEGAN, SPENNYMOOR) read every letter at 0.7+.
VLM_UNLISTED_TOP = 0.7

#: A VLM word with VLM_ALONE_OPEN or more open cells (no crossing holds them) the classifier reads
#: every one of under VLM_ALONE_P is the VLM's read alone: refused. 10-26, a 3-5-short 1993 Times grid:
#: RUMPLE for RUMPUS ("Strange cat lost tail in brawl", ?U????, its five open letters at 0.01-0.38);
#: none of 99 VLM words vlm_word took that were right (56 known lights held out, 43 last lights of
#: 1-2-short grids) was so (THESIS's 3 of 4 the most).
VLM_ALONE_OPEN, VLM_ALONE_P = 3, 0.5


def vlm_word(reply, pattern, sizes, probs, enum=None):
    """The word of the VLM's `reply` for a light whose crossings give `pattern` (a letter
    where an accepted light holds it, else "?"), made of words of `sizes` letters, or None:
    its letters are as many as the light's, agree with every crossing letter, each is at
    least VLM_FLOOR likely in its cell by the classifier's `probs` (one list of 26 a cell)
    but for a word the classifier reads too (floor_word), and each piece is a listed word
    (trove_solution_ocr.piece_listed), or the whole is a name both readers agree on
    (unlisted_word, by the light's enumeration `enum`); never one the classifier reads alone of every
    open letter (VLM_ALONE_OPEN, VLM_ALONE_P)."""
    word = re.sub(r"[^A-Za-z?]", "", (reply or "").strip().splitlines()[0] if (reply or "").strip() else "").upper()
    if len(word) != len(pattern) or "?" in word:
        return None
    if any(p != "?" and p != ch for p, ch in zip(pattern, word)):
        return None
    opened = [i for i, p in enumerate(pattern) if p == "?"]
    if len(opened) >= VLM_ALONE_OPEN and all(probs[i][trove_solution_ocr.AZ.index(word[i])] < VLM_ALONE_P for i in opened):
        return None
    low = [i for i, (p, ch) in enumerate(zip(probs, word)) if p[trove_solution_ocr.AZ.index(ch)] < VLM_FLOOR]
    if low and not floor_word(word, pattern, sizes, probs, low):
        return None
    # A listed word, or a name the classifier reads too (unlisted_word): a name the lexicons lack
    # is also what both may misread together (BALINITY for SALINITY, 1973 print), so it stands
    # only with no listed word one open letter off.
    at = 0
    for size in sizes:
        if not trove_solution_ocr.piece_listed(word[at:at + size], len(sizes) > 1):
            return word if unlisted_word(word, pattern, probs, enum) else None
        at += size
    return word


#: floor_word: a listed VLM word the classifier reads under VLM_FLOOR in at most FLOOR_CELLS cells, each
#: piece holding one the likeliest listed word its crossings leave (trove_solution_ocr.decoded) by
#: FLOOR_MARGIN (log odds) over the next. 10-25: 650 Times puzzles stood 1-2 lights short after their
#: VLM_UNLISTED reread; 176 of their lights had a VLM word thrown away under the floor alone, the right
#: ones one faint letter off the classifier's (LATITUDINARIANS' L at 0.003, ANTIPODES' D at 0.005, the
#: classifier's own pick by 2-50 log odds), the wrong ones not listed (ACCED, ULTRE) or another listed
#: word the classifier likes better (HOSTER for its HOSIER, LIGHT for EIGHT). Of 67 so taken, 62 with one
#: cell under fit their clues, every one; a second (CUBER for "Die content", both at 0.0) does not.
FLOOR_CELLS = 1
FLOOR_MARGIN = math.log(7)


def floor_word(word, pattern, sizes, probs, low):
    """Whether VLM word `word` stands though the classifier reads its cells `low` (indexes) under
    VLM_FLOOR: at most FLOOR_CELLS of them, every piece of `sizes` a listed word, and each piece
    holding one no surname alone (name_only) and decoded() the likeliest listed word agreeing with the
    crossings `pattern` by FLOOR_MARGIN: the two readers name it."""
    import numpy as np
    if len(low) > FLOOR_CELLS:
        return False
    held = {i: ch for i, ch in enumerate(pattern) if ch != "?"}
    cells = {i: np.asarray(p, float) for i, p in enumerate(probs)}
    at = 0
    for size in sizes:
        span, piece = list(range(at, at + size)), word[at:at + size]
        at += size
        if not trove_solution_ocr.piece_listed(piece, len(sizes) > 1):
            return False
        if not any(i in span for i in low):
            continue
        if trove_solution_ocr.name_only(piece):
            return False
        top, margin = trove_solution_ocr.decoded(span, cells, {i: held[i] for i in span if i in held})
        if top != piece or margin < FLOOR_MARGIN:
            return False
    return True


def unlisted_word(word, pattern, probs, enum):
    """Whether VLM word `word`, which no list holds, stands for its light (crossings
    `pattern`, the classifier's `probs`). 10-25: 135 Times strips in 3 h of answer rereads
    (1940s-50s names: PERSHORE, TAKORADI, LAETITIA) were asked, answered and thrown away for
    want of a list holding the word. The classifier reads each letter at least VLM_UNLISTED_TOP likely, the light's
    enumeration `enum` counts its letters (a linked light's "See 8" has none), and no listed
    word, of the light or of a piece of its enumeration, differs from it in one letter no
    crossing holds (trove_solution_ocr.one_away; answers_only's misread_word drops such a
    word anyway). A piece of a phrase is so tried only when it is no word itself (piece_listed) and
    longer than PIECE_SHORT: a listed piece is one letter off another as often as any listed word is,
    which vlm_word takes outright, and nearly every string of 1-3 letters lies one off some word.
    10-25: 12 Times phrase strips stood refused so after their rereads, the classifier reading every
    letter at 0.74+ (FEMME DE CHAMBRE's DE, UN-ENGLISH's UN, ST SWITHINS DAY's ST, ARNOLD BAX's BAX, ECO-
    LABELLING's ECO); 11 now stand, each right by its clue, and DEFINATE ARTICLE stays refused."""
    parts = [int(x) for x in re.findall(r"\d+", enum or "")]
    if not parts or sum(parts) != len(word):
        return False
    if any(p[trove_solution_ocr.AZ.index(ch)] < VLM_UNLISTED_TOP for p, ch in zip(probs, word)) \
            and not agreed_word(word, probs):
        return False
    held = {i: ch for i, ch in enumerate(pattern) if ch != "?"}
    if trove_solution_ocr.one_away(word, list(range(len(word))), held):
        return False
    at = 0
    for size in (parts if len(parts) > 1 else ()):
        span, piece = list(range(at, at + size)), word[at:at + size]
        at += size
        if size <= PIECE_SHORT or trove_solution_ocr.piece_listed(piece, True):
            continue
        if trove_solution_ocr.one_away(piece, span, held):
            return False
    return True


#: unlisted_word: the longest piece of a phrase not tried one letter off a listed word.
PIECE_SHORT = 3

#: agreed_word: the least probability the cell classifier may give a letter of an unlisted VLM word
#: under VLM_UNLISTED_TOP, the classifier's own likeliest letter in every cell of it.
AGREED_TOP = 0.4


def agreed_word(word, probs):
    """Whether the cell classifier's `probs` (one list of 26 a cell) read VLM word `word` as it stands,
    each cell's likeliest letter its letter, at AGREED_TOP or more: the two readers spell the same name,
    though not every letter at VLM_UNLISTED_TOP (unlisted_word's other checks stand). 10-26: of 666
    Times puzzles 1-2 short with no unit planned, such names stood blank on one faint letter (PALGRAVE
    for "Treasury man", its A at 0.58; BAYSWATER's A 0.48; TICHBORNE's B 0.54); on held-out lights of
    the same prints whose classifier word fit the crossings but was wrong (SPINOEF, ELASHMAN, HOLET),
    the VLM's plain strip read spelled it so none of 55 times (see CLUE_SHORT)."""
    t = trove_solution_ocr
    for p, ch in zip(probs, word):
        q = [float(x) for x in p]
        i = t.AZ.index(ch)
        if q[i] < AGREED_TOP or max(q) > q[i]:
            return False
    return True


def vlm_lights(answers, strips, grid, enums, asked=None):
    """(answers with the VLM's words added, {light: word} it gave): each light of `strips` (the
    cells of a light the grid's reading left, trove_solution_ocr.light_strip's PNGs) asked about
    once, as its row of squares with the letters its accepted crossings hold; the word stands
    by vlm_word(). An ask the spool or the server did not answer leaves its light as it was (the
    read ends deferred, and runs again once the drainer has answered). `asked` (a dict) gets
    {light: reply} of every ask answered, taken or not (answers_only's rejudged)."""
    import base64
    import io
    from PIL import Image
    lts = trove_solution_ocr.lights(grid)
    held = {}
    for lid, w in answers.items():
        n, _, dr = lid.partition("-")
        for rc, ch in zip(lts.get((int(n), dr), ()), w):
            held[rc] = ch
    prompt = SOLUTION_PROMPT.read_text()
    got = {}
    for lid, strip in sorted(strips.items()):
        b64 = strip["png"]
        n, _, dr = lid.partition("-")
        cells = lts[(int(n), dr)]
        sizes = trove_solution_ocr.pieces_of(enums.get((int(n), dr)), len(cells))
        pattern = "".join(held.get(rc, "?") for rc in cells)
        shape = (f"one word of {len(cells)} letters" if len(sizes) == 1 else
                 "words of " + ", ".join(map(str, sizes[:-1])) + f" and {sizes[-1]} letters, run together")
        known = f" The letters already known, ? for the others: {pattern}." if set(pattern) != {"?"} else ""
        try:
            with vlm.because("solution:" + lid):
                reply = vlm.ask(Image.open(io.BytesIO(base64.b64decode(b64))),
                                prompt.format(count=len(cells), shape=shape, known=known), max_tokens=40)
        except RuntimeError:  # spooled, or the server is down: asked again when the read runs again
            continue
        if asked is not None:
            asked[lid] = reply
        word = vlm_word(reply, pattern, sizes, strip["p"], enums.get((int(n), dr)))
        if word:
            got[lid] = word
            held.update(zip(cells, word))
    return {**answers, **got}, got


def uncrossed(answers, grid, enums=None, probs=None, rivals=None):
    """The lights of `answers` ({"12-across": word}) holding a cell another light of `grid` crosses
    with no answer of the grid's reading: a letter only its own word gives. A listed word read a
    letter off there stands on nothing (Times 8,564's 6-across BATES for PATES, "They're made of
    paste", its P crossed by an unread 6-down; 6,978's BUATS for BUSTS). One pass: an answer left out
    here still checked its crossers' letters as read (taken again, every one would go).
    Also one with a cell no other light holds (unchecked) that is no word (worded, by its `enums`
    count) nor a corpus answer: a letter there is checked by nothing, and a listed name read a letter
    off stands (10,927's RUSSUM, a surname list's, for RUSTUM in a grid read whole).
    With `probs` (a callable giving the cell classifier's {cell: 26 probabilities} of the grid's
    crop, trove_solution_ocr.cell_probs, or None when it has none), only such an answer whose
    lone cells (unchecked, or crossed unanswered) the classifier reads as a listed word one letter
    off is left out (misread_rival): the check alone left out 6,909 of the 97,685 Times answers
    filed 10-22..25, nearly all right (a partial grid's MILOMETER, HEZEKIAH, BETSEYTROTWOOD).
    It is called only when an answer would be left out that a listed word lies one lone letter off
    (no other can be read as one: with none, every answer stands); with no reading, every one is left
    out. `rivals` (a dict) gets {light: word} of those left out whose rival word stands in their place
    (rival_stands: AGHASI's lone I read as T, AGHAST)."""
    lts = trove_solution_ocr.lights(grid)
    on = {}
    for (n, dr), cells in lts.items():
        for rc in cells:
            on.setdefault(rc, []).append(f"{n}-{dr}")
    out = {k for k in answers if any(o not in answers for rc in lts.get(_light_key(k), ()) for o in on[rc] if o != k)}
    for k, a in answers.items():
        cells = lts.get(_light_key(k), ())
        if k not in out and any(len(on[rc]) == 1 for rc in cells) \
                and not worded(a, (enums or {}).get(_light_key(k))) and a.upper() not in trove_solution_ocr.corpus_words():
            out.add(k)
    if not out or probs is None:
        return out
    # Only an answer a listed word lies one lone letter off can be read as one (misread_rival): with
    # none, the crop's ~5 s classifier read is spared and every answer stands.
    lone = {k: lone_cells(k, lts, on, answers) for k in out}
    near = {k for k in out if any(i in {j for j, _, _ in lone[k]} for i, _ in trove_solution_ocr.one_change(answers[k].upper()))}
    if not near:
        return set()
    got = probs()
    if got:
        named = {k: misread_rival(answers[k], lone[k], got) for k in near}
        out = {k for k, rival in named.items() if rival}
        if rivals is not None:
            rivals.update({k: rival for k, rival in named.items()
                           if rival and rival_stands(answers[k], rival, (enums or {}).get(_light_key(k)))})
    return out


def lone_cells(k, lts, on, answers):
    """[(index, cell, letter)] of light `k`'s answer in `answers` where no other answer holds the
    cell, whether another light crosses there unanswered or none does: letters checked by nothing
    (uncrossed)."""
    return [(i, rc, ch) for i, (rc, ch) in enumerate(zip(lts.get(_light_key(k), ()), answers[k].upper()))
            if len(on[rc]) == 1 or any(o not in answers for o in on[rc] if o != k)]


#: A lone letter the classifier reads another letter over at this or more, that letter making a
#: listed word, is a misread (misread_rival). On 373 suspects of the Times answers filed 10-18..25
#: (a lone cell, a listed word one letter off there), .5 named 27: 24 misreads by their clues
#: (LOUCHING for TOUCHING, REMOTED for REMOTER, TOBAGI, ARELARD, MUCKLE for BUCKLE...), 3 right
#: (BUFF, DUMAS, CESSION); the plain UNLISTED_TOP bar on the filed letter took ~5 misreads in 40.
RIVAL_P = 0.5


def misread_rival(word, lone, probs):
    """The listed word answer `word` turns into where the classifier's `probs` read one of its `lone`
    letters [(index, cell, letter)] (lone_cells) as another at RIVAL_P and over its own, or None:
    8,564's BATES for PATES, its B read .035 and R over it (RATES)."""
    t = trove_solution_ocr
    w = word.upper()
    for i, rc, ch in lone:
        p = probs.get(rc)
        if p is None or ch not in t.AZ:
            continue
        own = float(p[t.AZ.index(ch)])
        for j in sorted(range(26), key=lambda j: -float(p[j])):
            if float(p[j]) < RIVAL_P or float(p[j]) <= own:
                break
            rival = w[:i] + t.AZ[j] + w[i + 1:]
            if t.AZ[j] != ch and t.listed(rival):
                return rival
    return None


def rival_stands(word, rival, enum=None):
    """Whether the listed word `rival` that misread_rival reads answer `word` as is filed in its place,
    not a blank: `word` is no answer of the corpus, and `rival` is one, or a word (worded, by `enum`)
    where `word` is none. Of the 534 Times answers repair_uncrossed blanked 10-25 (45074e48bb7), 208
    pass, 39 of 40 at random right by their clues (AGHASI: AGHAST, HALTBUT: HALIBUT, PACKER: BACKER;
    DEFEASIBLE: DEFENSIBLE wrong); the rest a word of the corpus or both no word are left blank, their
    rival right ~60% (FLICKER: ELICKER, BIGGLES: HIGGLES, SETH: NETH)."""
    corpus = trove_solution_ocr.corpus_words()
    if word.upper() in corpus:
        return False
    if rival.upper() in corpus:
        return True
    return worded(rival, enum) and not worded(word, enum)


def answers_only(d, found, hit, solutions, ask_vlm=True, crossed=True):
    """(verdict, puzzle) of a title whose clues are already filed whole and
    whose solution grid is linked now, read from the solution grid alone, or
    None (the full read): no clue is OCR'd again, as the held file's clues
    are the ones a full read of the same page would file.

    The held file is this tool's, from this page, every clue worded (complete,
    none shared or strayed), and an answer short; the edition is not one asked
    to be read again (_KEEP_VLM: a fix, an annotation, --reread). The puzzle
    returned is the held file with its answers as the solution grid reads
    them (solved, the full read's own reader), its verdict "answersOnly": decide()
    merges them into the held file (merge_answers) and takes no whole reading
    over it. A held answer the grid reads otherwise is settled light by light
    (settle_held: solution.heldClash), not the whole reading refused. None when two
    answers cross on different letters, or the grid is not the Times's (cells classified).
    Not `ask_vlm`: the lights the grid's reading left stay unanswered (no strip asked). `crossed` (every
    Times answers-only read, not only HELD_TITLE's since 10-25): an answer with a letter no other answer
    checks is left out (uncrossed) when the classifier reads one such letter off the grid's crop as
    another making a listed word (misread_rival; cell_probs, asked only when one would be left out),
    or with no crop read; a held title's (HELD_TITLE) every time."""
    if d is None or hit is None or not solutions or d.name in _KEEP_VLM["names"]:
        return None
    paper = paper_of(d)
    if paper.key not in CELLS_CLASSIFIED:
        return None
    number, _, why = filed_number(d, found, hit)
    sol = solutions.get(number) if number is not None and not why else None
    if not sol:
        return None
    old = held_file(paper.series, number)
    es = (old or {}).get("entries") or ()
    if not es or (old.get("source") or {}).get("acquiredBy") != TOOL \
            or (old["source"].get("url") != page_url(d, found, hit["leaf"])) or all(e.get("solution") for e in es):
        return None
    from fetch_puzzle import duplicated_clues
    # Every clue worded and counted, none shared or faulty. A blank, or a clue short of its count, was
    # cut by an earlier read and the full read may still fill it. A clue the readers filed but did not
    # settle (a stray mark, a word the readers disagreed on) is no reason: the answers add nothing to
    # it, the full read would spend the VLM's asks (a Times 1984 page: 3-6 per reread) on clue text
    # the "read without the VLM that now answers" rereads mend at their own turn, and the held clues
    # are the ones this reread keeps.
    # A clue filed with no enumeration is no reason either (the Gale page's clue column left it
    # off): the grid's light settles its count, the answers add nothing to the clue, and the full
    # read of a puzzle already held whole in clues never merged its answers (decide(): its reading
    # is not complete, it filed to --out) - 650 linked grids (10-22: 79 of them 2000s Times for
    # the Times write-ups left partial) stayed unanswered behind it. Since 10-25 (UNFILED_HELD)
    # decide() fills such a held file's blank lights from the full read too.
    if filled(old)[0] != len(es) or any(duplicated_clues(es)) or faults(old):
        return None
    grid = trove_solution_ocr.puzzle_grid(old)
    enums = {(e["number"], e["direction"]): (e["clue"] or {}).get("enumeration") for e in es}
    answers, info = solved(sol, grid, above=paper_of(sol["dir"]).solution_above, lean=True, enums=enums)
    # A grid read unsure of its blocks whose crop reads whole as another grid (printed_grid) is another
    # puzzle's: the page's other heading's grid, when its page printed the two under each other's
    # headings (swapped_heading), else none of this puzzle's.
    if not info.get("refused") and info.get("blocks", 0) < trove_solution_ocr.SURE_BLOCKS:
        printed = printed_grid(solution_crop(sol, number), grid)
        if printed is not None:
            moved = swapped_heading(sol, number, solutions, printed, grid, paper.series, enums)
            if moved:
                sol, answers, info = moved
            else:
                verdict = {"number": number, "leaf": hit["leaf"], "answersOnly": True, "vlmAsks": 0,
                           "solutionFrom": solution_source(sol), "wrongGrid": OTHER_GRID,
                           "skip": f"the linked solution grid is another puzzle's: {OTHER_GRID}"}
                if number != hit["number"]:
                    verdict["read_as"] = hit["number"]
                return verdict, None
    # Another puzzle's grid (wrong_grid) files none of its answers, nor does a full read of it.
    other = wrong_grid(es, answers, paper.series, number)
    if other:
        verdict = {"number": number, "leaf": hit["leaf"], "answersOnly": True, "vlmAsks": 0,
                   "solutionFrom": solution_source(sol), "wrongGrid": other,
                   "skip": f"the linked solution grid is another puzzle's: {other}"}
        if number != hit["number"]:
            verdict["read_as"] = hit["number"]
        return verdict, None
    # A held title (HELD_STRIPS) asks the VLM only of a grid its reading proves the held puzzle's (held_proven):
    # with no title read, a grid that gives the held answers is the only sign the strips are this puzzle's.
    if ask_vlm and hit.get("heldTitle") and not held_proven(es, answers):
        ask_vlm = False
    # The cells of the few lights the grid's reading left: the VLM is asked each one's word.
    strips = info.pop("strips", None)
    asked = {}
    if strips and ask_vlm and vlm.wanted():
        answers, by_vlm = vlm_lights(answers, strips, grid, enums, asked)
        if by_vlm:
            info = {**info, "vlmLights": sorted(by_vlm), "accepted": info.get("accepted", 0) + len(by_vlm)}
    # A reading at odds with itself (an answer its light's length does not fit, two crossing on different
    # letters) is the full read's, judged before the misread and uncrossed drops below: a drop would
    # hide the clash and leave an answers-only read that files nothing.
    if not fits_lights(old["entries"], answers):
        return None
    # A held title (HELD_TITLE) whose grid reading gives HELD_PROOF of the held answers word for word, and
    # another word for none, is this puzzle's grid as surely as a titled page's: its answers take the
    # titled read's uncrossed check (misread_rival), not every-uncrossed-goes (held_proven).
    every = bool(hit.get("heldTitle")) and not held_proven(es, answers)
    answers, info, clash = checked_answers(es, answers, grid, enums, info, solution_crop(sol, number),
                                           crossed=crossed, every=every,
                                           blog="blog" in (old.get("solutions") or {}))
    if asked:
        answers, info = rejudged(es, answers, info, asked, strips, grid, enums, solution_crop(sol, number),
                                 crossed=crossed, every=every,
                                 blog="blog" in (old.get("solutions") or {}))
    if ask_vlm:
        answers, info = late_strips(es, answers, info, strips or {}, grid, enums, solution_crop(sol, number),
                                    crossed=crossed, every=every,
                                    blog="blog" in (old.get("solutions") or {}))
    # A Times grid left short: the clue-constrained read, and the VLM's picks among a light's candidates
    # where they could complete the puzzle or nearly (6+ short, or 1-2: CLUE_SHORT).
    answers, info = candidate_reads(es, answers, info, grid, enums, solution_crop(sol, number), crossed=crossed,
                                    every=every, blog="blog" in (old.get("solutions") or {}), ask=ask_vlm)
    # A grid's last 1-2 lights whose VLM strip read clashes with held crossings their re-read makes words
    # (clash_reads, CLASH_SHORT): the held crossings are re-read with it.
    answers, info, recrossed = clash_reads(es, answers, info, grid, enums, solution_crop(sol, number), crossed=crossed,
                                           every=every, blog="blog" in (old.get("solutions") or {}), ask=ask_vlm)
    clash = {**clash, **recrossed}
    puzzle = copy.deepcopy(old)
    # Each answer must fill its light and agree with the held one it reads again.
    letters = {}
    for e in puzzle["entries"]:
        a = answers.get(entry_id(e))
        if not a:
            continue
        if len(a) != e["length"] or e.get("solution") and e["solution"] != a and clash.get(entry_id(e), {}).get("took") != "read":
            return None
        x, y, across = e["position"]["x"], e["position"]["y"], e["direction"] == "across"
        for i, ch in enumerate(a):
            if letters.setdefault((x + i * across, y + i * (not across)), ch) != ch:
                return None
    # A held answer the reading gives none for stands (decide merges answers-only with no reread drop: before
    # 10-25 every such one went, times-7522's 26 for a reading that took none), unless a read answer crosses
    # it on another letter: it goes for the read one (merge_answers), named here.
    gone = sorted(entry_id(e) for e in puzzle["entries"] if e.get("solution") and entry_id(e) not in answers
                  and any(letters.get((e["position"]["x"] + i * (e["direction"] == "across"),
                                       e["position"]["y"] + i * (e["direction"] != "across")), ch) != ch
                          for i, ch in enumerate(e["solution"])))
    if gone:
        info = {**info, "heldCrossed": gone}
    for e in puzzle["entries"]:
        e["solution"] = None
    verdict = {"number": number, "leaf": hit["leaf"], "grid": "image" if (old["source"].get("gridOrigin") == "published") else "rebuilt",
               "readings": ["held"], "clues": len(es), "complete": True, "lights": len(es), "agreed": len(es),
               "vlmAsks": 0, "answersOnly": True, "solutionFrom": solution_source(sol), "solution": info}
    if number != hit["number"]:
        verdict["read_as"] = hit["number"]
    verdict["answers"] = trove_solution_ocr.fill(puzzle, answers)
    return verdict, puzzle


#: The blank lights a held puzzle's answers-only reading may leave and late_strips still ask the VLM
#: of, one ask a light (read_framed's own strips stop at trove_solution_ocr.STRIP_MAX, 2: there each
#: ask is of a whole reading's last lights, not a held file's). 10-25: 769 Times puzzles read on that
#: day's code stood 1-16+ short with no ask at all; 401 of them held 3-5 blanks (WIDE_STRIPS).
LATE_MAX = 5


def rejudged(entries, answers, info, asked, strips, grid, enums, crop, crossed=True, every=False, blog=False):
    """(answers, info) of answers_only's checked reading `answers` of a held puzzle's `entries` with the
    VLM's words of `asked` ({light: reply}, vlm_lights') taken that vlm_lights threw away, judged again
    (vlm_word, the strip's `strips` probabilities) on the crossings as they stand after the checks: the
    held answers', then the checked reading's. vlm_lights judges each word on the grid's raw reading,
    whose misread crossing (checked_answers settles it to the held letter, or drops it) refuses the
    right word, and late_strips cuts no strip for a light that has one. A word stands only where the
    answers-only checks (checked_answers) keep it beside the rest, every other answer as it was; no
    ask is made. 10-25: 9 Times lights of 1-2-short files stood so after their rereads, each right by
    its clue (FORMOSA refused on the reading's P?R?O?A, held F?R?O?A; BRITAIN on S?I?A?N, TERRORIST on
    T?R?O?L?T)."""
    held = {entry_id(e): e["solution"] for e in entries if e.get("solution")}
    known = {**held, **answers}
    lts = trove_solution_ocr.lights(grid)
    letters = {}
    for lid, w in known.items():
        for rc, ch in zip(lts.get(_light_key(lid), ()), w):
            letters[rc] = ch
    by = {}
    for lid, reply in sorted(asked.items()):
        if lid in known or lid not in strips:
            continue
        key = _light_key(lid)
        cells = lts.get(key)
        if not cells:
            continue
        pattern = "".join(letters.get(rc, "?") for rc in cells)
        word = vlm_word(reply, pattern, trove_solution_ocr.pieces_of(enums.get(key), len(cells)), strips[lid]["p"],
                        enums.get(key))
        if word:
            by[lid] = word
            letters.update(zip(cells, word))
    if not by:
        return answers, info
    checked, _, _ = checked_answers(entries, {**answers, **by}, grid, enums, {}, crop, crossed=crossed,
                                    every=every, blog=blog)
    took = {k: w for k, w in by.items() if checked.get(k) == w}
    if not took:
        return answers, info
    info = {**info, "vlmLights": sorted(set(info.get("vlmLights") or ()) | set(took)), "rejudged": sorted(took),
            "accepted": info.get("accepted", 0) + len(took)}
    return {**answers, **took}, info


def late_strips(entries, answers, info, strips, grid, enums, crop, crossed=True, every=False, blog=False):
    """(answers, info) of answers_only's checked reading `answers` of a held puzzle's `entries` with
    the VLM's words added for the last 1 to LATE_MAX lights the held file and
    the reading leave blank whose strip read_framed did not cut (`strips`: the ones it cut, asked
    already): the reading was 3+ short, or its word was dropped after (misread_word, uncrossed).
    Their strips are cut off the grid's `crop` (trove_solution_ocr.crop_strips) and asked as
    vlm_lights asks, its known letters the held answers' and the reading's; a word stands only where
    the answers-only checks (checked_answers) keep it beside the rest, every other answer as it was.
    10-25: of 338 blank lights of 1-2-short Times files read on that day's code, none had a strip:
    171 had been read and dropped (misread 46, uncrossed 42, a full read's 83), 131 read by a full
    read (no enumerations: no strip)."""
    held = {entry_id(e): e["solution"] for e in entries if e.get("solution")}
    left = [entry_id(e) for e in entries if not e.get("solution") and not answers.get(entry_id(e))]
    if not left or len(left) > LATE_MAX:
        return answers, info
    want = [_light_key(k) for k in left if k not in strips]
    if not want or crop is None or not crop.exists() or not vlm.wanted():
        return answers, info
    cut = trove_solution_ocr.crop_strips(crop, grid, want)
    if not cut:
        return answers, info
    _, by = vlm_lights({**held, **answers}, cut, grid, enums)
    info = {**info, "lateStrips": sorted(cut)}
    if not by:
        return answers, info
    checked, _, _ = checked_answers(entries, {**answers, **by}, grid, enums, {}, crop, crossed=crossed,
                                    every=every, blog=blog)
    took = {k: w for k, w in by.items() if checked.get(k) == w}
    if not took:
        return answers, info
    info = {**info, "vlmLights": sorted(set(info.get("vlmLights") or ()) | set(took)),
            "accepted": info.get("accepted", 0) + len(took)}
    return {**answers, **took}, info


#: The prompt of candidate_reads' ask: a light's strip, its clue and the words it may be.
CANDIDATE_PROMPT = Path(__file__).resolve().parent / "vlm_candidate_prompt.md"
#: The candidates a candidate_reads ask offers, the likeliest by the cell classifier (alphabetical in
#: the prompt), and the most it asks of one puzzle.
CANDIDATE_OFFER, CANDIDATE_ASKS = 10, 40
#: candidate_reads asks only of a puzzle its asks could leave at most this many lights blank.
CANDIDATE_SLACK = 2
#: A clue read word of a grid left 1 to LATE_MAX short stands with at most CLUE_WEAK_CELLS open cells the
#: classifier reads its letter under CLUE_WEAK. 10-26, 1-2-short Times: CONFIDENCE CRICK for "Trusty device
#: used by criminal?" (10,5), on a held crossing's misread C, had F, D and N at 0.24, 0.12, 0.12; the 24
#: others read so, every one right by its clue, had one at most (HISPANIC's S 0.07, CANADA's A 0.35); on
#: 422 held-out lights of the same grids the clue read was the held answer every time.
CLUE_WEAK, CLUE_WEAK_CELLS = 0.5, 1


def reply_word(reply):
    """The letters (A-Z and ?) of the first line of a VLM reply, in capitals."""
    lines = (reply or "").strip().splitlines()
    return re.sub(r"[^A-Z?]", "", lines[0].upper()) if lines else ""


def candidate_pick(free, reply, offered, cells, probs, held, enum):
    """The word candidate_reads takes for a light, or None: the VLM's `reply` to its ask (the strip,
    the clue and the `offered` candidates) is one of them and is the word its plain strip read `free`
    (vlm_lights' ask, which offers no word) spells letter for letter; each piece of it is a word
    (piece_listed, and no name only cmudict lists), and the classifier's `probs` read none of its
    letters no taken crossing in `held` holds as another letter at trove_solution_ocr.CLUE_SURE.
    10-25, held out on 370 known lights of 1930s-90s Times grids left with 2+ candidates: the pick alone
    was the held word 291 times, another 72 (ONWARD read INWARD, ADIT EDIT, REGIMENT EFFERENT, STEAL
    STEAM); the two asks agreeing (133), every one was but 4, each right by its clue and the held file
    wrong (SWAY for AWAY, REBATE, SNIPE, OAFS); past these checks 116 stand (31%), none wrong."""
    t = trove_solution_ocr
    word = reply_word(reply)
    if word not in offered or reply_word(free) != word:
        return None
    sizes = t.pieces_of(enum, len(cells))
    at = 0
    for size in sizes:
        piece = word[at:at + size]
        at += size
        if not t.piece_listed(piece, len(sizes) > 1) or t.name_only(piece):
            return None
    for rc, ch in zip(cells, word):
        p = probs[rc]
        if rc not in held and float(p.max()) >= t.CLUE_SURE and int(p.argmax()) != t.AZ.index(ch):
            return None
    return word


def candidate_reads(entries, answers, info, grid, enums, crop, crossed=True, every=False, blog=False, ask=True):
    """(answers, info) of answers_only's checked reading `answers` of a held puzzle's `entries` that
    leaves a light blank, with the clue-constrained read's words (trove_solution_ocr
    .clue_reads: each light's listed words of its enumeration, the crossings, the classifier's letters
    off the grid's `crop`) and the VLM's picks among a light's candidates added. The VLM is asked
    (one ask a light, its strip, clue and CANDIDATE_OFFER likeliest candidates) only where every blank
    light but CANDIDATE_SLACK has 2+ candidates, so its picks could complete the puzzle or nearly; a
    pick stands by candidate_pick, then the read runs again on it. Not `ask`: the clue read alone. Every
    word stands only where the answers-only checks (checked_answers) keep it beside the rest. 10-25:
    192 Times puzzles of the 1970s-80s held 6+ short on a classified grid, 1,976 lights blank. Since
    10-26 (CLUE_SHORT) a grid left 1 to LATE_MAX short is read so too, asked only 1 to CANDIDATE_SLACK
    short: 666 Times puzzles stood 1-2 short with no unit planned, their last lights never clue-read. Since
    10-26 (CLUE_WIDE) a grid left 3 to LATE_MAX short is asked too once the clue read leaves it at most
    CANDIDATE_SLACK short: 260 Times puzzles stood 3-5 short with no unit planned."""
    import base64
    import io
    from PIL import Image
    t = trove_solution_ocr
    held = {entry_id(e): e["solution"] for e in entries if e.get("solution")}
    left = [entry_id(e) for e in entries if not e.get("solution") and not answers.get(entry_id(e))]
    if not left or crop is None or not crop.exists():
        return answers, info
    # 1 to LATE_MAX left: the picks only once the clue read leaves at most CANDIDATE_SLACK lights open (CLUE_SHORT,
    # CLUE_WIDE), each of which could complete the puzzle; 3 to LATE_MAX the clue read alone till then (late_strips
    # asked each light's strip).
    probs = crop_cell_probs(crop, grid)
    if not probs:
        return answers, info
    lts = t.lights(grid)
    known = {_light_key(k): w for k, w in {**held, **answers}.items() if _light_key(k) in lts}
    keys = {_light_key(k): k for k in left}
    asks = 0
    prompt, plain = CANDIDATE_PROMPT.read_text(), SOLUTION_PROMPT.read_text()
    clue = {entry_id(e): " ".join(((e.get("clue") or {}).get("text") if isinstance(e.get("clue"), dict)
                                   else e.get("clue") or "").split()) for e in entries}
    picked, tried = {}, set()

    def firm(got):
        # A grid's last lights (1 to LATE_MAX left) are its hardest cells: the list may settle one faint
        # letter of a clue read word, not more (CLUE_WEAK).
        if len(left) > LATE_MAX:
            return got
        mine = {rc: ch for k, w in {**known, **picked}.items() for rc, ch in zip(lts[k], w)}
        return {k: w for k, w in got.items() if sum(1 for rc, ch in zip(lts[k], w) if rc not in mine
                                                    and float(probs[rc][t.AZ.index(ch)]) < CLUE_WEAK) <= CLUE_WEAK_CELLS}
    while True:
        got, cands = t.clue_reads(lts, {**known, **picked}, probs, enums)
        got = firm(got)
        found = {**picked, **got}
        open_ = [k for k in keys if k not in found]
        askable = [k for k in open_ if len(cands.get(k) or ()) >= 2 and (k, tuple(w for w, _ in cands[k][:CANDIDATE_OFFER])) not in tried]
        if not ask or not askable or len(open_) - len(askable) > CANDIDATE_SLACK or asks >= CANDIDATE_ASKS \
                or (len(left) <= LATE_MAX and len(open_) > CANDIDATE_SLACK) or not vlm.wanted():
            break
        held_letters = {rc: ch for k, w in {**known, **found}.items() for rc, ch in zip(lts[k], w)}
        strips = t.crop_strips(crop, grid, askable)
        new = False
        for k in sorted(askable, key=lambda k: (len(cands[k]), k)):
            lid = keys[k]
            cells = lts[k]
            tried.add((k, tuple(w for w, _ in cands[k][:CANDIDATE_OFFER])))
            # A pick earlier in this pass holds its letters: a candidate crossing one otherwise is not offered.
            top = [w for w, _ in cands[k] if all(held_letters.get(rc, ch) == ch for rc, ch in zip(cells, w))][:CANDIDATE_OFFER]
            if lid not in strips or asks >= CANDIDATE_ASKS or len(top) < 2:
                continue
            sizes = t.pieces_of(enums.get(k), len(cells))
            pattern = "".join(held_letters.get(rc, "?") for rc in cells)
            shape = (f"one word of {len(cells)} letters" if len(sizes) == 1 else
                     "words of " + ", ".join(map(str, sizes[:-1])) + f" and {sizes[-1]} letters, run together")
            known_txt = f" The letters already known, ? for the others: {pattern}." if set(pattern) != {"?"} else ""
            img = Image.open(io.BytesIO(base64.b64decode(strips[lid]["png"])))
            try:
                with vlm.because("candidates:" + lid):
                    # The strip read plain first (vlm_lights' ask): only a read that spells a candidate
                    # can stand, so the pick is asked only then.
                    asks += 1
                    free = vlm.ask(img, plain.format(count=len(cells), shape=shape, known=known_txt), max_tokens=40)
                    if reply_word(free) not in top:
                        continue
                    asks += 1
                    reply = vlm.ask(img, prompt.format(count=len(cells), shape=shape, known=known_txt,
                                                       clue=clue.get(lid) or "(none)", choices=", ".join(sorted(top))),
                                    max_tokens=24)
            except RuntimeError:  # spooled, or the server is down: asked again when the read runs again
                continue
            word = candidate_pick(free, reply, top, cells, probs, held_letters, enums.get(k))
            if word:
                picked[k] = word
                held_letters.update(zip(cells, word))
                new = True
        if not new:
            break
    got = firm(t.clue_reads(lts, {**known, **picked}, probs, enums)[0])
    by = {keys[k]: w for k, w in {**got, **picked}.items() if k in keys}
    if not by:
        return answers, info
    checked, _, _ = checked_answers(entries, {**answers, **by}, grid, enums, {}, crop, crossed=crossed,
                                    every=every, blog=blog)
    took = {k: w for k, w in by.items() if checked.get(k) == w}
    info = {**info, "clueRead": sorted(k for k in took if _light_key(k) not in picked),
            "candidateAsks": asks}
    if not took:
        return answers, info
    vl = sorted(k for k in took if _light_key(k) in picked)
    if vl:
        info["vlmLights"] = sorted(set(info.get("vlmLights") or ()) | set(vl))
    info["accepted"] = info.get("accepted", 0) + len(took)
    return {**answers, **took}, info


#: held_recrossed: the most held crossings one VLM word may re-read (WELL-PLACED over TEASE, NATO, ROPY).
CLASH_CROSSINGS = 3


def held_recrossed(word, key, lts, known, held, probs, enums, cell_p=None):
    """{crossing key: its word re-read} for VLM word `word` of blank light `key` (of grid lights `lts`)
    that crosses answers `known` ({key: word}) on other letters, each such crossing a `held` one
    (keys), or None. The held crossings are older code's reads of the same printed grid, and on the
    last lights of a short Times grid the VLM's plain strip read clashing with one is as often the held
    letter misread (TOTA for IOTA, PLAT for FLAT, UTTER for OTTER, SUS for BUS) as its own slip.
    It stands when: at most CLASH_CROSSINGS held crossings clash, each on one cell, and each one's word
    with the VLM's letter there is a listed word (worded, or a corpus answer; no misread_word); the
    VLM word passes vlm_word on its crossings with those cells open (`cell_p` the strip's probabilities
    a cell, else the grid's `probs`), and is a word the clue-constrained read gives the light with those
    crossings open (trove_solution_ocr.clue_reads: the word taken, or one of its CANDIDATE_OFFER
    likeliest candidates). 10-26, of 131 Times lights 1-2 short with a VLM read against a held
    crossing, most such reads were the VLM's (HAPPYHO, THANKPUZZLES), each crossing word re-read no
    word (ROLYPOLP) or the read no candidate (JACENT for DECENT, CEREAL with RAISA)."""
    t = trove_solution_ocr
    cells = lts.get(key)
    if not cells or len(word) != len(cells) or not word.isalpha() or misread_word(word, enums.get(key)):
        return None
    letters = {rc: ch for k, w in known.items() for rc, ch in zip(lts[k], w)}
    off = [i for i, rc in enumerate(cells) if rc in letters and letters[rc] != word[i]]
    if not off:
        return None
    alts = {}
    for i in off:
        on = [k for k in known if k != key and cells[i] in lts[k]]
        if len(on) != 1 or on[0] not in held:
            return None
        j = on[0]
        ji = lts[j].index(cells[i])
        was = alts.get(j, known[j])
        alts[j] = was[:ji] + word[i] + was[ji + 1:]
    if len(alts) > CLASH_CROSSINGS or len(alts) != len(off):
        return None
    for j, alt in alts.items():
        if misread_word(alt, enums.get(j)) or not (worded(alt, enums.get(j)) or alt in t.corpus_words()):
            return None
    opened = {k: w for k, w in known.items() if k not in alts}
    pattern = "".join("?" if i in off else letters.get(rc, "?") for i, rc in enumerate(cells))
    p = cell_p if cell_p is not None else [probs[rc] for rc in cells]
    if vlm_word(word, pattern, t.pieces_of(enums.get(key), len(cells)), p, enums.get(key)) != word:
        return None
    got, cands = t.clue_reads(lts, opened, probs, enums)
    if got.get(key) != word and word not in [w for w, _ in (cands.get(key) or ())[:CANDIDATE_OFFER]]:
        return None
    return alts


def clash_reads(entries, answers, info, grid, enums, crop, crossed=True, every=False, blog=False, ask=True):
    """(answers, info, clash) of answers_only's checked reading `answers` of a held puzzle's `entries` left
    1 to CANDIDATE_SLACK lights blank after candidate_reads, with each such light's VLM plain strip read
    (vlm_lights' ask, its strip cut off the grid's `crop`) taken where it clashes with held crossings that
    held_recrossed re-reads: the light takes the VLM word and each such crossing its word re-read, all
    standing together where the answers-only checks (checked_answers; settle_held takes each re-read
    crossing as the read answer, its changed letter checked by the VLM word) keep them. `clash` is
    settle_held's {light: {"held", "read", "took"}} of the crossings so changed. A blog's held answers
    (`blog`) always stand: none is re-read. 10-26 (CLASH_SHORT): of 666 Times puzzles 1-2 short with no
    unit planned, 131 blank lights had a VLM read against a held crossing."""
    import base64
    import io
    from PIL import Image
    t = trove_solution_ocr
    held = {entry_id(e): e["solution"] for e in entries if e.get("solution")}
    left = [entry_id(e) for e in entries if not e.get("solution") and not answers.get(entry_id(e))]
    if blog or not ask or not left or len(left) > CANDIDATE_SLACK or crop is None or not crop.exists() \
            or not vlm.wanted():
        return answers, info, {}
    probs = crop_cell_probs(crop, grid)
    if not probs:
        return answers, info, {}
    lts = t.lights(grid)
    cut = t.crop_strips(crop, grid, [_light_key(k) for k in left])
    if not cut:
        return answers, info, {}
    asked = {}
    vlm_lights({**held, **answers}, cut, grid, enums, asked)
    known = {_light_key(k): w for k, w in {**held, **answers}.items() if _light_key(k) in lts}
    mine = {_light_key(k) for k in held}
    by = {}
    for lid, reply in sorted(asked.items()):
        key = _light_key(lid)
        word = reply_word(reply)
        alts = held_recrossed(word, key, lts, {**known, **{_light_key(k): w for k, w in by.items()}},
                              mine - {_light_key(k) for k in by}, probs, enums, cut[lid]["p"])
        if alts is None:
            continue
        by[lid] = word
        by.update({f"{j[0]}-{j[1]}": w for j, w in alts.items()})
    if not by:
        return answers, info, {}
    checked, _, clash = checked_answers(entries, {**answers, **by}, grid, enums, {}, crop, crossed=crossed,
                                        every=every, blog=blog)
    if any(checked.get(k) != w for k, w in by.items()):
        return answers, info, {}
    clash = {k: c for k, c in clash.items() if k in by and c.get("took") == "read"}
    info = {**info, "clashRead": sorted(k for k in by if k not in clash),
            "vlmLights": sorted(set(info.get("vlmLights") or ()) | {k for k in by if k not in clash}),
            "heldClash": {**(info.get("heldClash") or {}), **clash},
            "accepted": info.get("accepted", 0) + len(by) - len(clash)}
    return {**answers, **by}, info, clash


def solution_crop(sol, number):
    """The crop read_solution leaves of solution heading `sol`'s grid (CROPS/solutions), which
    trove_solution_ocr.cell_probs reads for uncrossed's misread_rival."""
    return CROPS / "solutions" / f"{Path(sol['dir']).name}_{sol.get('number', number)}.png"


def checked_answers(entries, answers, grid, enums, info, crop=None, crossed=True, every=False, blog=False):
    """(answers, info, clash) of a solution grid's reading `answers` ({"12-across": word}) of a puzzle
    whose held file's `entries` (or, with none held, the reading's own, answerless) lie on `grid`, past
    the checks every answer read off a grid takes before it files, answers_only's and the full read's
    (full_read_answers) alike:
    - misread_word: an answer no word that one letter's change makes one goes ("misread"); a held answer
      the grid reads alike goes with it ("heldMisread", held_drops);
    - with `crossed`, uncrossed: an answer with a letter no other answer checks goes when the classifier
      reads one such letter off `crop` (cell_probs) as another making a listed word (misread_rival), that
      word taken for it where rival_stands ("rivals"), or, with `every` (a held title, HELD_TITLE), whenever uncrossed names it ("uncrossed");
      a word for a light the held file leaves blank goes when misread_rival reads a letter of it no other light
      holds as another (held_blank_unchecked, "unchecked");
    - settle_held: a held answer the reading reads otherwise is settled light by light ("heldClash"),
      the held answers kept filed with the reading's; a blog's (`blog`) always stand.
    `enums` {(number, direction): enumeration}; `info` the reading's stats, returned with the checks'
    keys added. Each held answer the reading gives none for stands (decide: merge_answers with no reread
    drop), but by held_drops."""
    # An answer no word (worded) that one letter's change makes one is a misread, not a name: dropped.
    misread = {k for k, a in answers.items() if misread_word(a, enums.get(_light_key(k)))}
    if misread:
        # A held answer the grid reads alike is the same misread: it goes too (heldMisread, merge_answers drop).
        # Every other held answer the reading does not give stands (decide: no reread drop).
        was = {entry_id(e): e.get("solution") for e in entries}
        held_misread = sorted(k for k in misread if was.get(k) and was[k] == answers[k])
        answers = {k: a for k, a in answers.items() if k not in misread}
        info = {**info, "misread": sorted(misread), "accepted": info.get("accepted", 0) - len(misread)}
        if held_misread:
            info["heldMisread"] = held_misread
    if crossed:
        # A held title (HELD_TITLE) stands on no title read: every answer uncrossed leaves out goes. The
        # rest go only as the classifier reads them another word (misread_rival), that word filed in
        # their place where it stands (rival_stands: AGHASI read AGHAST), not left blank.
        rivals = {}
        lone = uncrossed(answers, grid, enums, probs=None if every else (
            lambda: crop_cell_probs(crop, grid) if crop is not None and crop.exists() else None), rivals=rivals)
        if lone:
            took = {k: rivals[k] for k in sorted(lone) if k in rivals}
            answers = {**{k: a for k, a in answers.items() if k not in lone}, **took}
            info = {**info, "uncrossed": sorted(lone), "accepted": info.get("accepted", 0) - len(lone) + len(took)}
            if took:
                info["rivals"] = took
        # A word read for a light the held file (with answers) leaves blank goes where a letter of it on a cell
        # no other light holds the classifier reads as another letter making a listed word (misread_rival):
        # nothing checks that letter (10-26, a 1942 Times grid's last lights: DINE for PINE, "This apple
        # doesn't grow on this tree", its D at 0.07 under P's 0.80). Left blank, no rival filed.
        fresh = held_blank_unchecked(entries, answers, grid, set(lone or ()))
        if fresh and not every and crop is not None and crop.exists():
            got = crop_cell_probs(crop, grid)
            gone = sorted(k for k, cells in fresh.items() if got and misread_rival(answers[k], cells, got))
            if gone:
                answers = {k: a for k, a in answers.items() if k not in gone}
                info = {**info, "unchecked": gone, "accepted": info.get("accepted", 0) - len(gone)}
    # A held answer the reading reads otherwise no longer refuses the whole reading (settle_held):
    # the read one replaces it when a listed word fitting every crossing, else the held one stands and
    # the read answers crossing it on another letter go; the held answers kept are filed with the reading's.
    answers, kept, clash = settle_held(entries, answers, enums, blog=blog)
    if clash:
        info = {**info, "heldClash": clash}
        answers = {**answers, **kept}
    return answers, info, clash


def held_blank_unchecked(entries, answers, grid, skip=()):
    """{light: [(index, cell, letter)]} of the answers in `answers` (but `skip`) for lights a held file's
    `entries` leave blank, the file holding some answer, each light's letters on cells no other light of
    `grid` holds, where a listed word lies one such letter off (trove_solution_ocr.one_change): the ones
    checked_answers' misread_rival reads again."""
    if not any(e.get("solution") for e in entries):
        return {}
    blank = {entry_id(e) for e in entries if not e.get("solution")}
    lts = trove_solution_ocr.lights(grid)
    on = {}
    for key, cells in lts.items():
        for rc in cells:
            on[rc] = on.get(rc, 0) + 1
    out = {}
    for k, a in answers.items():
        if k not in blank or k in skip:
            continue
        cells = [(i, rc, ch) for i, (rc, ch) in enumerate(zip(lts.get(_light_key(k), ()), a.upper())) if on[rc] == 1]
        if cells and any(i in {j for j, _, _ in cells} for i, _ in trove_solution_ocr.one_change(a.upper())):
            out[k] = cells
    return out


def crop_cell_probs(crop, grid):
    """trove_solution_ocr.cell_probs of solution-grid crop `crop` for `grid`, the last one kept
    (_CELL_PROBS) by the crop's size and time: a page's full read runs _read_page more than once
    (another window, the VLM's columns), each on the same grid's crop (~5 s of CPU a read)."""
    st = crop.stat()
    key = (str(crop), st.st_size, st.st_mtime_ns, tuple("".join(r) for r in grid))
    kept = _CELL_PROBS.get("last")
    if kept and kept[0] == key:
        return kept[1]
    probs = trove_solution_ocr.cell_probs(crop, grid)
    _CELL_PROBS["last"] = (key, probs)  # one tuple: a worker thread reads the pair whole
    return probs


_CELL_PROBS = {}


def full_read_answers(paper, number, puzzle, sol, grid, answers, info):
    """(answers, info) of a full read's (_read_page) reading `answers` of `sol`'s solution grid for
    `puzzle` (the full read's, on `grid`), checked as answers_only checks its own (checked_answers:
    misread_word, uncrossed with the classifier's misread_rival, settle_held against the held file).
    Before 10-25 a full read filed every answer the grid gave: 6+ short Times files, a held file with
    a blank clue, and every first read took a misread (BATES for PATES) an answers-only reread drops.
    Only a paper whose cells are classified (CELLS_CLASSIFIED, answers_only's); a refused or empty
    reading, and another puzzle's grid (wrong_grid: decide files none of its answers, judged on the
    reading as read), are returned as read. The held file's entries settle a clash only when it is
    this tool's on the same grid; else the reading's own (no held answer) do."""
    if paper.key not in CELLS_CLASSIFIED or not answers or "refused" in info:
        return answers, info
    old = held_file(paper.series, number) or {}
    held = bool((old.get("source") or {}).get("acquiredBy") == TOOL and old.get("entries")
                and trove_solution_ocr.puzzle_grid(old) == trove_solution_ocr.puzzle_grid(puzzle))
    es = old["entries"] if held else puzzle["entries"]
    if held and wrong_grid(es, answers, paper.series, number):
        return answers, info
    enums = {(e["number"], e["direction"]): (e.get("clue") or {}).get("enumeration") for e in es}
    enums.update({(e["number"], e["direction"]): (e.get("clue") or {}).get("enumeration")
                  for e in puzzle["entries"] if (e.get("clue") or {}).get("enumeration")})
    answers, info, _ = checked_answers(es, answers, grid, enums, info, solution_crop(sol, number),
                                       blog=held and "blog" in (old.get("solutions") or {}))
    return answers, info


def fits_lights(entries, answers):
    """Whether every answer of `answers` ({"12-across": word}) fills its entry's light of `entries`
    and no two cross on different letters (answers_only)."""
    letters = {}
    for e in entries:
        a = answers.get(entry_id(e))
        if not a:
            continue
        if len(a) != e["length"]:
            return False
        x, y, across = e["position"]["x"], e["position"]["y"], e["direction"] == "across"
        for i, ch in enumerate(a):
            if letters.setdefault((x + i * across, y + i * (not across)), ch) != ch:
                return False
    return True


#: A held puzzle within this many numbers of a reading's whose answers it gives more of than its own
#: (wrong_grid): the grid linked is that one's (times-21706 read as 21707, its 12 answers 21707's).
WRONG_GRID_REACH = 7
#: At least this many of a reading's answers alike at the same lights for another held puzzle to be
#: its grid's (wrong_grid): a short word may sit at one light of two grids by chance.
WRONG_GRID_ALIKE = 3


#: The cells a solution crop's blocks must miss of a puzzle's grid, and as many it must read as blocks
#: where the grid has light, for printed_grid to call it another grid.
OTHER_GRID_CELLS = 2
#: answers_only's wrongGrid of a crop printed_grid reads as another grid, no heading of its page the
#: puzzle's (swapped_heading).
OTHER_GRID = "its blocks read whole as another grid's"


def blocks_of(grid):
    """The block mask of `grid` (rows of cells, "#" a block) as a tuple of tuples."""
    return tuple(tuple(ch == "#" for ch in row) for row in grid)


def printed_grid(crop, grid):
    """The block mask (blocks_of) of another crossword grid than `grid` that a solution grid's crop
    (solution_crop) reads as, or None: on its best-fitting framing every cell read a block or light,
    the blocks in 180-degree turn symmetry, every light cell in a light of 2 or more, and at least
    OTHER_GRID_CELLS of `grid`'s blocks read light and of its lights read blocks. A heavy print's
    inked letters (blocks only, scattered) or a grey screen's blocks read paper (lights only) are not.
    10-26: of the Times held 6+ short, 13 linked crops read so, each another puzzle's grid exactly
    (times-18089's page prints 18,094's grid under its heading, 18094's 18,089's; 20015 off 1999's
    misread 21015; 21976 off 21971's heading read twice), every held grid fitting its own clues."""
    import numpy as np
    from PIL import Image
    try:
        gray = np.asarray(Image.open(crop).convert("L"))
        framed = trove_solution_ocr.framings(gray, grid)
    except (OSError, ValueError):
        return None
    fits = [trove_solution_ocr.block_agreement(g, grid, (ys, xs)) for g, ys, xs in framed]
    g, ys, xs = framed[int(np.argmax(fits))]
    n = len(grid)
    seen = trove_solution_ocr.blocks_read(g, (ys, xs), n)
    if None in seen.values() or any(len(row) != n for row in grid):
        return None
    mask = tuple(tuple(bool(seen[(r, c)]) for c in range(n)) for r in range(n))
    if any(mask[r][c] != mask[n - 1 - r][n - 1 - c] for r in range(n) for c in range(n)):
        return None
    own = blocks_of(grid)
    missed = sum(own[r][c] and not mask[r][c] for r in range(n) for c in range(n))
    extra = sum(mask[r][c] and not own[r][c] for r in range(n) for c in range(n))
    if missed < OTHER_GRID_CELLS or extra < OTHER_GRID_CELLS:
        return None
    rows = ["".join("#" if b else "." for b in row) for row in mask]
    lit = {rc for cells in trove_solution_ocr.lights(rows).values() if len(cells) >= 2 for rc in cells}
    if any(not mask[r][c] and (r, c) not in lit for r in range(n) for c in range(n)):
        return None
    return mask


def swapped_heading(sol, number, solutions, printed, grid, series, enums):
    """(heading, answers, info) of puzzle No `number`'s grid `grid` read under another solution heading
    of `sol`'s page and leaf, or None: one whose puzzle is held on another grid that is exactly the
    one `sol`'s crop reads as (`printed`, printed_grid), and under which `grid` reads at SURE_BLOCKS.
    The page printed the two grids under each other's headings (Saturdays 1987-90: 17,424 and 17,429,
    18,089 and 18,094, 18,316 and 18,321, 18,394 and 18,399, each heading over the other's grid, its
    answers the other's clues'). The heading is relabelled `number`, so its crop and read are this
    puzzle's (solution_crop, solved)."""
    here = (os.fspath(sol["dir"]), sol["leaf"], tuple(sol["box"]))
    day = Path(sol["dir"]).name[:10]
    seen, cands = set(), []
    # The same day's other editions too (the archive.org and Gale copies of one paper): 1990-06-16's
    # archive.org scan read only the 18,316 heading, the Gale page both.
    linked = [{**s, "dir": Path(k)} for (k, _), v in _LINKED.items() if Path(k).name[:10] == day for s in v[4]]
    for s in list(solutions.values()) + linked:
        at = (os.fspath(s["dir"]), s["leaf"], tuple(s["box"]))
        if s["number"] == number or at == here or (s["number"], at) in seen \
                or (at[1] != here[1] if at[0] == here[0] else Path(at[0]).name[:10] != day):
            continue
        seen.add((s["number"], at))
        cands.append(s)
    mine = blocks_of(grid)
    for s in cands:
        theirs = held_file(series, s["number"])
        if not theirs:
            continue
        other = blocks_of(trove_solution_ocr.puzzle_grid(theirs))
        if other != printed or other == mine:
            continue
        moved = {**s, "number": number}
        answers, info = solved(moved, grid, above=paper_of(moved["dir"]).solution_above, lean=True, enums=enums)
        if info.get("refused") or info.get("blocks", 0) < trove_solution_ocr.SURE_BLOCKS:
            continue
        return moved, answers, {**info, "swappedHeading": s["number"]}
    return None


def whole_word(held, read):
    """Whether `read` is another word than `held`, not an OCR slip of it (more than 2 letters off, or
    another length): the HELD_CLASH split."""
    return len(held) != len(read) or sum(a != b for a, b in zip(held, read)) > 2


def wrong_grid(entries, answers, series, number):
    """Why a solution grid's reading `answers` ({"12-across": word}) is not puzzle No `number`'s of
    `series`, whose held file has `entries` (None: none held), or None. Two cases (10-25's whole-word
    held clashes): the reading gives other words than 2 or more held answers and agrees on fewer
    (another puzzle's grid alike in blocks: times-11998 off July's 11998, times-15492 numbered
    off by one), or a held puzzle within WRONG_GRID_REACH numbers holds more of its answers at the
    same lights (WRONG_GRID_ALIKE at least) than this one's held file does (times-21706 and
    times-22186 read off the next day's grid). Such a grid's answers are none of this puzzle's."""
    read = {k: a for k, a in answers.items() if a}
    if not read:
        return None
    held = {entry_id(e): e.get("solution") for e in entries or () if e.get("solution")}
    both = [k for k in read if k in held]
    agree = sum(held[k] == read[k] for k in both)
    whole = sorted(k for k in both if whole_word(held[k], read[k]))
    if len(whole) >= 2 and len(whole) > agree:
        return (f"it reads other words than {len(whole)} held answers ({', '.join(whole[:4])}) "
                f"and agrees on {agree}")
    for n in sorted(range(number - WRONG_GRID_REACH, number + WRONG_GRID_REACH + 1), key=lambda m: abs(m - number)):
        other = held_file(series, n) if n != number else None
        if not other:
            continue
        theirs = {entry_id(e): e.get("solution") for e in other.get("entries") or () if e.get("solution")}
        alike = sum(theirs.get(k) == a for k, a in read.items())
        if alike >= WRONG_GRID_ALIKE and alike > agree:
            return f"{alike} of its answers are No {n}'s held ones at the same lights ({agree} this one's)"
    return None


#: The held answers a held title's (HELD_TITLE) grid reading must give word for word, giving another
#: word for none, for its grid to stand as the puzzle's (held_proven).
HELD_PROOF = 4


def held_proven(entries, answers):
    """Whether a solution grid's reading `answers` ({"12-across": word}) proves the grid the held puzzle's
    (its `entries`): HELD_PROOF or more held answers read word for word and none as another word
    (whole_word). A held title (HELD_TITLE) stands on no title read, so answers_only left out every
    answer uncrossed named (an unread crossing light, none of the classifier's misread_rival check);
    10-25: 135 Times files read so stood 1-16 short on ~630 lights their reading gave, each agreeing
    with every held letter (times-8025's TERRITORIALARMY, EXPLAINS: 26 held answers read alike), while
    wrong_grid already refuses a grid giving other words than 2 held ones."""
    held = {entry_id(e): e.get("solution") for e in entries or () if e.get("solution")}
    both = [k for k, a in answers.items() if a and k in held]
    agree = sum(held[k] == answers[k] for k in both)
    return agree >= HELD_PROOF and not any(whole_word(held[k], answers[k]) for k in both)


def settle_held(entries, answers, enums=None, blog=False):
    """(answers, held, clash) for an answers-only reading `answers` ({"12-across": word}) of a held
    file's `entries` some of whose held answers it reads otherwise. Before 10-25 one such light
    refused the whole reading (times-5432, times-11238: every other new answer lost).

    Each clashing light takes the reading's answer when it is a listed word (worded, or a corpus
    answer) that fits every letter crossing it (each read answer's not itself clashing, else the
    held answer's of a light not read), a letter it reads otherwise so crossed; else it keeps the
    held one (unchecked letters are no evidence: times-7267's OOS for DOS, printed COS). The held answers are older
    code's reads of the same printed grid: on 10-25's dry run of 11 such Times lights the reading
    was right on every one, held words too (RIKSDAG for RIGSDAG, "rotten in the state"; TITIS for
    TITUS, "Andronicus"; SATED for SATYR, "Trays broken"). A blog's (`blog`, solutions.blog) always
    stand, as merge_answers keeps them. A kept held answer drops
    its reading, and every read answer that crosses it on another letter (that letter is the
    reading's at odds with the held file). `held` is {light: held answer} of each light whose
    held answer stands where the reading's went, every one agreeing with the answers kept, so the
    merge (merge_answers, reread) does not drop it; `clash` {light: {"held", "read", "took": "read",
    "held", or "dropped" (a read answer taken, then crossing a kept held one: neither filed)}}."""
    def cells(e):
        x, y, across = e["position"]["x"], e["position"]["y"], e["direction"] == "across"
        return [(x + i * across, y + i * (not across)) for i in range(e["length"])]
    by = {entry_id(e): e for e in entries}
    was = {k: e["solution"] for k, e in by.items() if e.get("solution")}
    clash = {k: {"held": was[k], "read": a} for k, a in answers.items() if was.get(k) and was[k] != a}
    if not clash:
        return answers, {}, {}
    def listed(w, k):
        return worded(w, (enums or {}).get(_light_key(k))) or w.upper() in trove_solution_ocr.corpus_words()
    on = {}
    for k, e in by.items():
        for i, rc in enumerate(cells(e)):
            on.setdefault(rc, []).append((k, i))
    def crossers(k):
        return [(i, j, ji) for i, rc in enumerate(cells(by[k])) for j, ji in on[rc] if j != k]
    out = dict(answers)
    held = {}
    for k, c in clash.items():
        h, a = c["held"], c["read"]
        # The letters crossing k: each read answer's (not itself clashing), else the held answer's
        # of a light the reading does not read otherwise.
        crossing = []
        for i, j, ji in crossers(k):
            if j in clash:
                continue
            if j in answers:
                crossing.append((i, answers[j][ji]))
            elif was.get(j):
                crossing.append((i, was[j][ji]))
        # A letter the reading reads otherwise must be checked: a crossing letter there (of a light not
        # itself clashing) agreeing with the read one. Read otherwise only on unchecked letters, the
        # reading has no evidence over the held answer, which stands (10-25: times-7267's OOS for DOS,
        # times-5693's BEAR for DEAR, their first letters unchecked, the printed answers COS and REAR;
        # times-5432's AIRS for AIDE, its R checked by GOODWOODRACES, still gives way).
        checked = {i for i, _ in crossing}
        better = not blog and listed(a, k) and all(a[i] == ch for i, ch in crossing) \
            and len(a) == len(h) and any(i in checked for i in range(len(a)) if a[i] != h[i])
        c["took"] = "read" if better else "held"
        if not better:
            out.pop(k, None)
            held[k] = h
    # A read answer crossing a kept held answer on another letter goes with it.
    for k in held:
        for i, j, ji in crossers(k):
            if j in out and out[j][ji] != held[k][i]:
                out.pop(j)
                if j in clash:
                    clash[j]["took"] = "dropped"
    # Each light left with no read answer keeps its held one where it agrees with every letter kept.
    letters = {rc: ch for k, a in {**out, **held}.items() for rc, ch in zip(cells(by[k]), a)}
    for k in list(by):
        if k not in out and k not in held and was.get(k) and k not in clash \
                and all(letters.get(rc, ch) == ch for rc, ch in zip(cells(by[k]), was[k])):
            held[k] = was[k]
            letters.update(zip(cells(by[k]), was[k]))
    for k in [k for k in held if k not in clash]:
        if k not in answers:
            del held[k]  # never read: it stands unless crossed (merge_answers; answers-only takes no reread drop)
    return out, held, clash


def _light_key(lid):
    """(number, direction) of a light id "12-down"."""
    n, _, d = lid.partition("-")
    return (int(n), d) if n.isdigit() else (lid, d)


def misread_word(word, enum=None):
    """Whether solution-grid answer `word` is a misread: no word (worded), held by no list as it
    stands (cmudict's, the lexicon's, the corpus's: a name such as RUFUS, BULGARIA stands), only
    by an inflection the reader builds (WordNet's lemma "adores" + s gave ADORESS, a 1973 print's
    ADDRESS), and one letter's change makes a word."""
    if not word or worded(word, enum):
        return False
    t = trove_solution_ocr
    t.listed("A")
    w = word.upper()
    if w in (t._LISTED or ()) or w in t.corpus_words():
        return False
    return any(worded(x, enum) for _, x in t.one_change(w))


#: A stray mark glued to a word's front in a clue ("source of -warmth", "from .late"): a reader's
#: speck, which the VLM's reading of the same column does not have.
STRAY_MARK = re.compile(r"(?:^|\s)[-.,;]\w")


def settled_light(puzzle, lid):
    """Whether the readers' `puzzle` has light `lid` whole: a clue text with no stray mark
    and an enumeration (the grid's count settles a count slip; it does not give the
    enumeration's commas and hyphens a light was laid without, or mend a speck in the text)."""
    for e in (puzzle or {}).get("entries") or ():
        if f"{e['number']}-{e['direction']}" == lid:
            clue = e.get("clue") or {}
            text = (clue.get("text") or "").strip()
            if re.fullmatch(r"See \d+.*", text):
                return True  # a "See 9" tail has no count of its own
            return bool(text and clue.get("enumeration") and not STRAY_MARK.search(text))
    return False


def merged_read(verdict, puzzle, v, p, asked):
    """(verdict, puzzle): the readers' own `puzzle` with each light of `asked`, and each
    light it left blank, taken from the VLM pass's `p` when that pass filed a clue for it.
    The VLM pass stands as it is when it filed no puzzle or another grid."""
    if p is None or puzzle is None:
        return v, p
    def lid(e):
        return f"{e['number']}-{e['direction']}"
    def text(e):
        return ((e.get("clue") or {}).get("text") or "").strip()
    mine = {lid(e): e for e in puzzle.get("entries") or ()}
    theirs = {lid(e): e for e in p.get("entries") or ()}
    if set(mine) != set(theirs) or any(mine[k].get("length") != theirs[k].get("length") for k in mine) \
            or puzzle.get("grid") != p.get("grid"):
        return v, p
    want = set(asked) | {k for k, e in mine.items() if not text(e)} | {
        k for k, e in mine.items() if not (e.get("clue") or {}).get("enumeration")
        and (theirs[k].get("clue") or {}).get("enumeration")}
    # A linked light comes with its whole group.
    for k in list(want):
        for e in (mine.get(k), theirs.get(k)):
            want |= set((e or {}).get("group") or ())
    took = {k for k in want if k in theirs and text(theirs[k])}
    for k in list(took):
        took |= set(theirs[k].get("group") or ()) & set(theirs)
    out = dict(puzzle)
    out["entries"] = [theirs[lid(e)] if lid(e) in took else e for e in puzzle.get("entries") or ()]
    got = dict(v)
    blank = {k: why for k, why in (verdict.get("blank") or {}).items() if k not in took}
    blank.update({k: why for k, why in (v.get("blank") or {}).items() if k in took})
    got.pop("blank", None)
    if blank:
        got["blank"] = blank
    got["agreed"] = sum(1 for e in out["entries"] if text(e))
    got["vlmMerged"] = sorted(took)
    return got, out


def disagreeing(verdict):
    """The lights the readers' imageDisagrees names ("13-across: the enumeration ..."), an
    empty set when there is no disagreement; None when it names none (then every column)."""
    why = verdict.get("imageDisagrees")
    if why is None:
        return set()
    got = set(re.findall(r"\b(\d{1,2}-(?:across|down))\b", str(why)))
    return got or None


def held_copy(d, verdict, puzzle):
    """The id of the held puzzle whose clues the readers' own list for a NEW puzzle (its number
    not held) already repeats, else None: fetch_puzzle.check_not_copy refuses the write of such
    a page, so no ask can change its fate. Only when the readers' clues that match are at
    least the share THRESHOLD of every light, so the final list (a VLM pick only fills a
    blank) shares as much."""
    if puzzle is None or d is None or d.name in _KEEP_VLM["names"] or verdict.get("number") is None:
        return None
    try:
        from fetch_puzzle import clue_index, clue_keys
        import clue_index as ci
        if verdict["number"] in held_dates(paper_of(d).series):
            return None
        entries = len(puzzle.get("entries") or ())
        keys = clue_keys(puzzle)
        for other, shared, _, _ in clue_index().matches(puzzle["id"], keys):
            if entries and shared >= ci.THRESHOLD * entries:
                return other
            # A few blank lights (the VLM's to fill): the clues the readers did print are the
            # held puzzle's (THRESHOLD of them), they are two thirds of the page's lights, and the
            # blanks alone would carry the share over THRESHOLD of every light. (The 10-20 log:
            # 2005-04-11, 30 lights, 3 blank, 23 of 27 printed clues book-11003's: 6 asks, then refused.)
            if (entries and shared >= ci.THRESHOLD * len(keys) and shared >= 2 * entries / 3
                    and shared + (entries - len(keys)) >= ci.THRESHOLD * entries):
                return other
    except Exception:  # no index here: the VLM is asked as before
        return None
    return None


#: Editions (dir names) the VLM is asked about even for a puzzle already held:
#: an annotation asked, a refusal read before its fix, an explicit --reread.
#: Set by _run, and on the desktop by ocr_remote.read_edition_here.
_KEEP_VLM = {"names": set()}
#: (series, number) -> the held file's parsed puzzle or None. The desktop
#: points it at the held files the Mac sent.
_HELD_READER = {"read": None}
#: Titles whose VLM asks held_settled spared, this process.
VLM_SKIPPED = []


def held_file(series, number):
    """The parsed held file of `series`' puzzle `number`, or None."""
    reader = _HELD_READER["read"]
    try:
        if reader is not None:
            return reader(series, number)
        p = _HELD_PATH.get((series, number)) or filer_path(("held", number), series, None)
        return json.loads(Path(p).read_text())
    except (OSError, ValueError, KeyError):
        return None


def held_settled(d, verdict):
    """Whether this page's puzzle needs no VLM ask: its number (known once
    filed_number placed it) is already held, and the held file leaves the
    VLM nothing to mend: not this tool's (decide() only merges answers
    there), or this tool's with every clue worded and none shared, strayed
    or faulty (mend_held's lost lights, which the blank-clue re-read fills).
    False when the edition is one asked to be read again (_KEEP_VLM). Notes
    verdict["heldSkip"] and "vlmAsks" 0 when it spares the asks."""
    if d is None or d.name in _KEEP_VLM["names"] or verdict.get("number") is None:
        return False
    series = paper_of(d).series
    n = verdict["number"]
    if n not in held_dates(series):
        return False
    old = held_file(series, n)
    if old is None:
        return False
    if (old.get("source") or {}).get("acquiredBy") == TOOL:
        from fetch_puzzle import duplicated_clues
        es = old.get("entries") or ()
        if any(not ((e.get("clue") or {}).get("text") or "").strip() for e in es) \
                or any(duplicated_clues(es)) or strayed(old, spaces=False) or faults(old):
            return False
    verdict["heldSkip"] = True
    verdict["vlmAsks"] = 0
    VLM_SKIPPED.append(n)
    return True


def two_columns_only(paper, d):
    """True for an FT page of 1982-86 (1983-12-02 too: overhang() = 1336, past the
    grid's 840, where the listings stand): its clues are the two columns under the grid and
    the page's TV listings stand in the band right of it (overhang() read them as a
    third clue column: the readers then laid the listings' lines, no reading had
    the clues of 22-down on 1984-11-10, and the VLM was asked to pick for them).
    Also a Gale Times of 1950-59: the grid stands mid-page with ACROSS and the first
    DOWN clues in a column left of it and the rest in two columns under it; the
    adverts right of it were read as a third column (overhang() = 1732 on the
    1957-03-04 page, grid ending at 1222), which dropped the left column
    (no lead) and every reading was refused "no ACROSS and DOWN lists"."""
    if paper.key == "gale" and d is not None and "1950" <= d.name[:4] <= "1959":
        return True
    return paper.key == "ft" and d is not None and "1982" <= d.name[:4] <= "1986"


def clues_may_be_right(paper, d):
    """False for a Gale edition before 2014: its clues never lie right of the grid."""
    return not (paper.key == "gale" and d.name[:4] < "2014")


#: The windows (the layout's, the readers' settled one, the gutters near its edge) a page's VLM
#: reads are shown at most (env CT_VLM_WINDOWS; 0: no cap): read_page's alt loop stops there.
VLM_WINDOWS = int(os.environ.get("CT_VLM_WINDOWS") or 3)


def read_page(d, found, hit, solutions, vlm_for=False, first=None, dead=()):
    """read_puzzle's one read: `vlm_for` False asks the VLM nothing; None
    asks it every column; a list of lights, the columns holding them.

    A crop that did not hold the clue columns (crop_window.poor(): refused
    unreadable, no grid-fitting list, lights left blank) is read again from
    the other gutters near the window's left edge, and the best reading
    stands: the window is right by its own check, not by the layout's offset.

    `first` is the window (an alt) the scan's readers alone settled on
    (the "_alt" of their read, read_puzzle's): the VLM pass tries it before
    anything else. An FT page whose layout window was poor cost the VLM a
    full page of asks there (3 reads and 2 picks) before the window it
    could have been shown at once (5 more), and the alternatives tried in
    that order still stand if `first` is poor too."""
    alts = []
    # A window that left an ask for the VLM's drainer (vlm_reader.unanswered) is judged by
    # blanks that are only unanswered: another window is not read (each costs a full page of
    # asks, spooled in this same pass), and the read, deferred, runs again once the drainer has
    # answered, to judge this window by its answers and try the next only if it is poor.
    waiting = vlm.unanswered()
    # A poor window with another to try is not picked for (_read_page's "_deferred"): the
    # best window is read again with its picks once chosen.
    if first is not None:
        v, p = _read_page(d, found, hit, solutions, vlm_for, first, None, defer=True)
        v.pop("_laid", None)
        if vlm.unanswered() != waiting:
            v.pop("_deferred", None)
            return v, p
        if not crop_window.poor(v, image_ok=vlm_for is not False):
            v["cropFrom"] = "gutter"
            return v, p
    verdict, puzzle = _read_page(d, found, hit, solutions, vlm_for, None, alts, defer=None)
    if not alts or not crop_window.poor(verdict, image_ok=vlm_for is not False) or vlm.unanswered() != waiting:
        verdict.pop("_laid", None)
        verdict.pop("_deferred", None)
        return verdict, puzzle
    best = (crop_window.score(verdict, puzzle), verdict, puzzle)
    settled = None
    gone = []
    judged = 1 + (first is not None)  # windows the VLM has been shown (and found poor) so far
    for i, alt in enumerate(alts):
        if alt == first:
            continue
        # A page whose first VLM_WINDOWS windows were all poor is not shown more of them: each costs a
        # full page of column reads (2-3 asks) and the next window of such a page has not filed it (the
        # 10-21 vlm_asks.log, 5.75h: 150 new filings, none from a page that took 7 or more column
        # reads; the 15 pages that did took 125 asks and ended refused or unfiled). The windows
        # already read stand (cached): the best of them is the page's reading, as before.
        if vlm_for is not False and VLM_WINDOWS and judged >= VLM_WINDOWS and alt not in dead:
            break
        # A window the readers found no clue in at all (FT 1980-81: the cut right of the
        # grid, 0 of 32 lights) is not shown to the VLM: it would read the page's other print.
        if alt in dead:
            continue
        # Every light filled, none blank: no other window can score higher
        # (a tie keeps the earlier), so the VLM is not shown more of them.
        if vlm_for is not False and best[2] is not None and best[0] == (1, best[1].get("lights") or -1):
            break
        # The VLM is not asked again for a clue the best window so far already has
        # (lend_laid): another window is read for the clues that one is still missing.
        lent = best[1].get("_laid") if vlm_for is not False else None
        more = any(a != first for a in alts[i + 1:])
        if vlm_for is not False and VLM_WINDOWS and judged + 1 >= VLM_WINDOWS:
            more = False  # the last window shown: its picks are not deferred to a window that will not come
        v, p = _read_page(d, found, hit, solutions, vlm_for, alt, None, **({"lent": lent} if lent else {}), defer=more)
        if vlm.unanswered() != waiting:
            break  # this window's asks are spooled: the read defers; the windows after it wait
        judged += 1
        if vlm_for is False and not (v.get("agreed") or 0) and d is not None and paper_of(d).key == "ft":
            gone.append(alt)
        if crop_window.score(v, p) > best[0]:
            best = (crop_window.score(v, p), v, p)
        if not crop_window.poor(v, image_ok=vlm_for is not False):
            settled = alt
            break
    chosen = best[1].pop("_deferred", None)
    if chosen is not None and vlm.unanswered() == waiting:
        # The window stands, its picks not yet asked: read it again (every column read is
        # cached) with them, for the blanks of this window alone.
        was = best[1] is verdict
        lent = chosen["lent"]
        v, p = _read_page(d, found, hit, solutions, vlm_for, chosen["alt"], None, **({"lent": lent} if lent else {}))
        best = (crop_window.score(v, p), v, p)
        if was:
            verdict = v
    for v in (verdict, best[1]):
        v.pop("_laid", None)
        v.pop("_deferred", None)
    if best[1] is not verdict:
        best[1]["cropFrom"] = "gutter"
    # The readers' own pass notes the window that held the columns (not
    # necessarily the best scored: the layout's may score higher while the
    # readers disagree with the grid), for the VLM pass to try first.
    if vlm_for is False and settled is not None:
        best[1]["_alt"] = settled
    if gone:
        best[1]["_dead"] = gone
    return best[1], best[2]


def lend_laid(laid, blank, lent):
    """(laid, blank, {lights}) with each blank light that `lent` (another window's laid
    clues, light -> (text, count, group)) has a clue for, of the same count, laid with
    that clue: the VLM is then asked only for what no window has read yet."""
    laid, blank, got = dict(laid), dict(blank), set()
    for lid in list(blank):
        theirs, mine = lent.get(lid), laid.get(lid)
        if theirs and (theirs[0] or "").strip() and mine is not None and theirs[1] == mine[1]:
            laid[lid] = (theirs[0], mine[1], mine[2])
            del blank[lid]
            got.add(lid)
    return laid, blank, got


def _read_page(d, found, hit, solutions, vlm_for, alt, alts, lent=None, defer=False):
    """read_page's one read from a window: `alt` is (kind, x) and moves the
    window edge of that kind ("lead": a lead column's left edge; "right": the
    right clue columns' far edge; "over": the third column's; "under": the
    gutter between the two columns under the grid) to x, or ("plain", None)
    reads the layout without right or overhanging columns; `alts` (a list)
    is filled with the other windows near the one used, for read_page to
    try."""
    kind, alt_x = alt or (None, None)
    vlm_on = vlm_for is not False
    n, leaf = hit["number"], hit["leaf"]
    verdict = {"number": n, "leaf": leaf}
    paper = paper_of(d)
    number, day, why = filed_number(d, found, hit)
    if why:
        return refuse(verdict, "number-date-mismatch", why), None
    if number != n:
        verdict["read_as"], n = n, number
        verdict["number"] = n
    img = page(d, leaf)
    lines = leaf_lines(d / "djvu.xml.gz", {leaf}).get(leaf, [])
    gbox, side = (grid_under_clues(img, hit["box"]), "below") if paper.clues_above else locate_grid(img, hit["box"], paper.key in GRID_RIGHT)
    if gbox is None:
        return refuse(verdict, "not-a-grid", "no ink under the title"), None
    gw, gh = gbox[2] - gbox[0], gbox[3] - gbox[1]
    if side is None or not (wide_shaped if paper.key in GRID_RIGHT else shaped_on)(img, gbox):
        return refuse(verdict, "not-a-grid", f"the ink under the title is {gw}x{gh}, not a grid"), None
    key = f"{d.name}_{n}"
    third = (paper.third, third_top(img, gbox, paper.third)) if paper.third else None
    m = paper.margin
    # Clues over the grid: from the title line down, split where the fewest
    # words of any reading cross.
    top = hit["box"][1] - 10 if paper.clues_above else None
    x0 = clues_left(gbox, hit["box"], m) if top is not None else None
    beside = side == "left"
    # The clues read from a crop left of the grid: two columns a grid's
    # width wide (beside), or the one column left_column() finds.
    column = left_column(lines, gbox) if side == "below" and top is None and not paper.four else None
    # A Gale page has no djvu text, so the 1987 Saturday prize's column
    # (left_column) found no heading and every such page was refused "no
    # reading parses": its heading is read from a RapidOCR strip left of the grid.
    if column is None and not lines and paper.key == "gale" and "1980" <= d.name[:4] < "1990" \
            and side == "below" and top is None and not paper.four:
        probe = rapid_lines(img, gbox, "ch", CROPS / "rapid" / f"{key}.probe.json", None, m, None,
                            (gbox[0] - (gbox[2] - gbox[0]) - 60, left_bottom(gbox)), None, None, None)
        column = left_column(probe, gbox)
    crop =(gbox[0] - (gbox[2] - gbox[0]) - 60, left_bottom(gbox)) if beside else column and column[::2]
    # The 2006-13 Times' three columns under the grid, the third overhanging
    # it: read from a crop that reaches its end (a page that ends soon under
    # the grid is not the 2014 Times' clues right of it).
    # The 2014 Times: the clue columns right of a grid at the page's foot.
    # Asked first: a page that ends that soon under the grid has no room for
    # three columns, and the "Yesterday's solution" box under its grid is
    # inked like the third column's text (overhang() read it as one, and the
    # Feb to May 2014 pages were cropped under the grid: no clue lists).
    # Only from 2014 on: before it the strip right of a grid near the page's
    # foot is an advert (the 1961 Times page 1.15 grids' widths from its foot
    # was read for clue columns, and every page of the year was refused "no
    # reading parses"); the clue column stands left of such a grid (lead).
    # A Gale page before 2014 never has its clues right of the grid: the strip
    # there is an advert column (1947-48: the grid at the page's foot made
    # right_columns() read the ads, and the clue column left of the grid went unread).
    right, over = right_or_over(img, gbox, clues_may_be_right(paper, d)) if side == "below" and top is None \
        and not column and not paper.four and not third and kind != "plain" and not two_columns_only(paper, d) \
        else (None, None)
    if (right or over) and alts is not None:
        alts.append(("plain", None))
    # The 2005 Times: the same, the grid left of its title (side "left").
    if side == "left" and paper.key in ("times", "gale") and not paper.four and not third:
        right = right_columns(img, gbox, RIGHT_SPAN_LEFT) if kind != "plain" else None
        if right:
            beside, crop = False, None
            if alts is not None:
                alts.append(("plain", None))
    lead = lead_column(hit["box"], gbox, m) if side == "right" else \
        (indented_column(hit["box"], gbox, m) or (indented_column(title_left(img, hit["box"], gbox), gbox, m)
                                                   if paper.key == "gale" and d.name[:4] < "1968" else None)) \
        if side == "below" and top is None and not column and not right \
        and not over and not paper.four else None
    if lead:
        lead = trimmed_lead(img, gbox, lead)
        if kind == "lead":
            lead = (alt_x, lead[1])
        elif alts is not None:
            alts.extend(("lead", x) for x in edge_candidates(img, gbox, lead)[1:])
    if right and kind == "right":
        right = (alt_x, right[1])
    elif right and alts is not None:
        alts.extend(("right", x) for x in far_edges(img, (gbox[0], gbox[1] - RIGHT_RISE, right[0] + 300, right[1]), right[0]))
    if over and kind == "over":
        over = alt_x
    elif over and alts is not None:
        ybox = (gbox[0], gbox[3], over + 300, gbox[3] + int(OVER_DEPTH[1] * gw))
        alts.extend(("over", x) for x in far_edges(img, ybox, over))
    rapid = {which: rapid_lines(img, gbox, which, CROPS / "rapid" / f"{key}.{reader_key(which)}.json",
                                (over - gbox[2] - 15, gbox[3]) if over else third, m, top,
                                crop, lead, x0, right) for which in READERS}
    if right:
        was = right
        right, rapid = right_foreign(rapid, gbox, right)
        # A window whose edge runs through its own clue column (no other print past it: the
        # cut boxes are clue lines) is widened to that column's far edge and read again
        # (crop_window.cut_edge: the mid-2014 Times' down column, its line ends cut off).
        wider = None if right != was else max(
            (x for x in (crop_window.cut_edge(img, [w for ws in lines for w in ws],
                                              (gbox[2] + 5, gbox[1] - RIGHT_RISE, right[0], right[1]))
                         for lines in rapid.values()) if x is not None), default=None)
        if wider:
            right = (wider, right[1])
            rapid = {which: rapid_lines(img, gbox, which, CROPS / "rapid" / f"{key}.{reader_key(which)}.json",
                                        None, m, top, crop, lead, x0, right) for which in READERS}
            right, rapid = right_foreign(rapid, gbox, right)
    # The scan's grid, read before the clues: the 1930 Times prints no
    # counts, so its clues take theirs from it.
    gpath = CROPS / "grids" / f"{key}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)
    # Cut afresh on every read, so the crop is always of this grid box.
    img.crop((gbox[0] - 6, gbox[1] - 6, gbox[2] + 6, gbox[3] + 6)).save(gpath)
    image, why = trove_grid.read_grid(gpath)
    g = image
    if not g:
        verdict["imageUnread"] = why
    above = left = None
    every = lines + [ws for r in rapid.values() for ws in r]
    if paper.four:
        if not g:
            return refuse(verdict, "not-a-grid", f"the grid gives the clues' counts, and it is unread: {why}"), None
        gutters = four_gutters(every, gbox)
        down = down_at(every, gbox, gutters)
        cols = {which: columns_of_four(rapid[which], gbox, gutters, down) for which in FOUR_READERS}
        texts = {k: column_text(c) for k, c in cols.items()}
        wins = [None] * max(len(c) for c in cols.values())
        if vlm_on and vlm.wanted():
            try:
                texts["vlm"] = vlm_four(img, list(cols.values()),
                                        columns_with(list(cols.values()), vlm_for, True) if vlm_for else None)
            except RuntimeError:
                pass
        texts = {k: counted(spaced(t), g) for k, t in texts.items()}
    elif top is not None:
        # The gutter is sought in the middle of the columns' span: from the
        # grid's left edge, or from x0 when the clues start further left.
        span = min(gbox[0], x0 + m)
        mid = (span + 0.3 * (gbox[2] - span), span + 0.75 * (gbox[2] - span)) if span < gbox[0] else (None, None)
        above = (top, gutter(every, gbox, top, *mid), gutter(every, gbox, top, gbox[2] - OVERHANG, gbox[2] + OVERHANG), x0)
    if beside:
        left = left_columns(every, gbox)
    elif column:
        left = column
    if lead:
        lead = lead_split(every, gbox, lead, m)
    if right:
        right = right_gutter(every, gbox, right)
    if not paper.four:
        split = over_gutters(every, gbox, over) if over else \
            under_gutter(every, gbox, UNDER_FIFTIES if paper.key == "gale" and "1950" <= d.name[:4] <= "1959" else None) if above is None and left is None and not right else None
        if split is not None and not over:
            if kind == "under":
                split = alt_x
            elif alts is not None:
                bottom = gbox[3] + int(1.8 * gw)
                alts.extend(("under", x) for x in crop_window.edge_candidates(
                    img, (gbox[0], gbox[3], gbox[2], min(img.height, bottom)), split, reach=int(UNDER_SPAN * gw))[1:])
        # The 1945-49 Times' last clues in a strip between title and grid.
        strip = strip_over(img, gbox, hit["box"], d.name[:4]) if paper.key == "gale" and top is None else None
        cols = {"djvu": columns(lines, gbox, third, m, above, left, split, lead, right, strip)}
        for which in READERS:
            cols[which] = columns(rapid[which], gbox, third, m, above, left, split, lead, right, strip)
        texts = {k: column_text(c) for k, c in cols.items()}
        wins = windows(gbox, third, m, above, left, split, lead, right, strip)
    # The desktop's VLM, when it answers, is one more reading (the 1930
    # page's, vlm_four's above).
    if not paper.four and vlm_on and vlm.wanted():
        try:
            only = columns_with(list(cols.values()), vlm_for) if vlm_for else None
            # No weak light in any column: nothing for the VLM to read.
            asked = "\n".join(vlm.read_columns(f"{d}#{n}", img, [box for i, box in enumerate(vlm.boxes(img, wins, list(cols.values())))
                                                                 if box and (only is None or i in only)])) if only is None or only else None
            if asked is not None:
                texts["vlm"] = "\n".join(numbered_heading(t) or t for t in asked.splitlines())
        except RuntimeError:
            pass  # gone mid-run: read as without it; run() files it to be read again
    # The Canberra Times reprint of the same puzzle is another copy of the
    # print, its readings voters like the scan's own.
    reprints = reprint_readings(n, paper.series)
    # Worn type reads an e as c, o or x the same way in every reader ("cra",
    # "somo"): each scan reading has the one lexicon word it wore from put
    # back (ocr_clues.worn), so the readers agree on it.
    texts = {k: t if k == "vlm" else ocr_clues.unworn(t) for k, t in texts.items()}
    texts.update(reprints)
    texts, dropped = screened(texts, g)
    if dropped:
        verdict["dropped"] = dropped
    # Each reading in turn is the list, repaired from the other: archive.org's
    # against RapidOCR's, and where archive.org has no words for the columns,
    # RapidOCR's two recognisers against each other. The first list that
    # lies on the scanned grid wins; failing all, the most complete list is
    # rebuilt.
    pairs = ([("djvu", "ch"), ("ch", "djvu"), ("djvu", "en5"), ("en5", "djvu")]
             if texts.get("djvu", "").strip() else [("ch", "en5"), ("en5", "ch")])
    # A reading the screen dropped is in no pair; the readings no pair names
    # (Tesseract's, the VLM's) lead when none of those parses.
    pairs = [o for o in pairs if all(k in texts for k in o)]
    named = {k for o in pairs for k in o}
    rest = [(k, next((o for o in texts if o != k), k)) for k in texts if k not in named]
    tried = []
    for order in pairs + rest:
        if order in rest and tried:
            break
        parsed, why = parse(texts[order[0]])
        if parsed is None:
            verdict.setdefault("unparsed", {})[order[0]] = why
            continue
        # A clue this list lost is taken from each other reading in turn.
        parsed, _ = clue_repair.repaired(
            parsed, [texts[k] for k in [order[1]] + [k for k in texts if k not in order]])
        # A number its list's order refuses ("12" after 19) is left for the
        # grid to place, never handed to the rebuild as read.
        parsed, _ = ftp.renumber(parsed)
        laid, why = ftp.match(parsed, g) if g else (None, None)
        tried.append((laid is not None, clue_repair.complete(parsed),
                      sum(len(v) for v in parsed.values()), -len(tried), order, parsed, laid, why))
        if laid is not None:
            break
    if not tried:
        return refuse(verdict, "no-reading-parses", "no reading parses"), None
    ok, done, count, _, order, parsed, laid, why = max(tried, key=lambda t: t[:4])
    verdict["readings"] = list(order)
    verdict["clues"] = count
    verdict["complete"] = done
    # Every other reading votes on the list's words.
    stream = [t for k, t in texts.items() if k != order[0] and t.strip()]
    grid, how = (g, "image") if ok else (None, None)
    if g and not ok:
        verdict["imageDisagrees"] = why
        # The scan's grid stands when nearly every clue lies on it: the few
        # that do not are misreads, filed blank, never forced to fit.
        # Each light takes the first reading whose clue lies on it, and is
        # checked against another reading than its own.
        # The readings no pair tried (the VLM's, Tesseract's) come last.
        lists = [(o, p) for _, _, _, _, o, p, _, _ in tried]
        for k in texts:
            if k not in {o[0] for o, _ in lists} and texts[k].strip():
                p, _ = parse(texts[k])
                if p is not None:
                    lists.append(((k,), ftp.renumber(p)[0]))
        loose, src = {}, {}
        for o, p in lists:
            for lid, v in lay_loose(p, g)[0].items():
                if lid not in loose:
                    loose[lid], src[lid] = v, o
        # Then the clues whose number was lost, into the lights no reading
        # laid by number.
        by_number = set(loose)
        for o, p in lists:
            for lid, v in lay_loose(p, g, by_number)[0].items():
                if lid not in loose:
                    loose[lid], src[lid] = v, o
        verdict["looseLaid"] = len(loose)
        if len(loose) >= LOOSE_SHARE * len(rg.light_cells(g)):
            grid, how, laid = g, "image", loose
            verdict["readings"] = sorted({o[0] for o in src.values()})
            stream = [{lid: t for lid, o in src.items() if k != o[0]}
                      for k, t in texts.items() if t.strip()]
    if grid is None:
        g, why = ftp.rebuild(parsed, image)
        if g is None and image:
            # No grid fits the clues, so the misreads are the clues': the
            # scan's grid stands, its unlaid lights blank for the clue
            # re-read.
            grid, how, laid = image, "image", loose
        elif g is None:
            verdict["pending"] = f"no grid: {why}"
            return verdict, None
        else:
            laid, why = ftp.match(parsed, g)
            if laid is None:
                verdict["pending"] = f"rebuilt grid disagrees: {why}"
                return verdict, None
            grid, how = g, "rebuilt"
    verdict["grid"] = how
    lengths = {f"{n_}-{d_}": len(cells) for (n_, d_), cells in rg.light_cells(grid).items()}
    fits = {lid for lid, (_, enum, group) in laid.items()
            if enum and not group and ftp.count(enum) == lengths.get(lid)}
    bare = {lid for lid in lengths if not (laid.get(lid) or ("",))[0].strip()}
    laid, blank = unfit_blanked(*reconcile(laid, stream, lengths), lengths)
    # A clue the vote left blank, laid again from each reading that printed
    # it whole (the reprint's among them) and put to the rest.
    read = {k: t for k, t in texts.items() if t.strip()}
    laid, blank = ocr_clues.relaid(read, laid, blank, parse, lengths)
    # A light the readings print as only "See N" is that clue, not a blank to ask the VLM for.
    laid, blank = see_laid(read, laid, blank, lengths, parse)
    def tail(laid, blank):
        """(laid, blank, alike) after the steps that follow the VLM's pick."""
        # A light no reading laid and the VLM's pick left blank, laid from the
        # readers that agree on its clue.
        laid, blank = ocr_clues.relaid(read, laid, blank, parse, lengths, bare=bare)
        laid, blank = leaked_laid(read, laid, blank, parse)
        # Each filed clue as the readings print it: its count's shape, each word's
        # capital, hyphen and spelling.
        laid, blank = ocr_clues.as_printed(texts, laid, blank, parse, lengths)
        laid, blank = one_light_each(laid, blank, fits)
        # A clue read in ahead of another's, its count and all, is cut off it;
        # one no laid clue prints is left for bled() to refuse.
        laid = ocr_clues.runs_in_cut(laid)
        # The slips one clue's own text shows (its count left after its words,
        # a drop capital, a word broken by a space): tools/clue_repair.mend_text.
        laid = {lid: (clue_repair.mend_text(t, e) if t else t, e, g) for lid, (t, e, g) in laid.items()}
        laid = book_marked(laid, book_clues(reprints))
        # A word no lexicon knows, or a bracket never shut, that the readings
        # print alike is the print's own ("ignis"): filed as its asPrinted.
        alike = {lid: got for lid, (t, _, _) in laid.items() if t and lid not in blank and (
            got := ocr_clues.printed_alike(t, [r for r, _ in ocr_clues.readings_for(read, lid, parse)]))}
        laid, blank = unfit_blanked(laid, blank, lengths, alike)
        alike = {lid: got for lid, got in alike.items() if lid not in blank}
        if paper.four:
            # The counts were the grid's, not the paper's: filed without.
            laid = {lid: (t, None, None) for lid, (t, _, _) in laid.items()}
        return laid, blank, alike

    def doomed():
        """True when the page would be refused whatever the VLM picks for its blank
        clues: a clue already laid (not blank) breaks a write rule of
        puzzle_integrity.refuse_bad_write. A pick only fills a blank clue, so the
        asks for the blank ones would be spent on a page that is not written."""
        import puzzle_integrity
        try:
            t_laid, t_blank, t_alike = tail(laid, blank)
            trial = build(n, day, grid, how, t_laid, edition_of(d, found), leaf, series=paper.series,
                          name=paper.name.format(n), url=page_url(d, found, leaf), printed=t_alike)
            puzzle_integrity.refuse_bad_write(trial)
        except puzzle_integrity.RefusedWrite as e:
            open_lights = set(blank) | set(t_blank)
            for kind, _, what in e.flags:
                m = re.match(r"(\d+-(?:across|down)): ", what)
                if kind in ("SHAPE", "LENGTH") and m and m.group(1) not in open_lights and "blank" not in what:
                    return True
        except Exception:  # a trial that cannot be judged spends no ask less
            pass
        return False

    # The CPU reads each weak clue's lines again before the VLM is asked about it.
    retried = {}
    if not paper.four:
        laid, blank, retried = retry_weak(img, key, cols, read, laid, blank, lengths, tail)
        if retried:
            verdict["retried"] = sorted(retried)
    if lent and blank and "vlm" in texts and vlm_on and vlm.wanted():
        laid, blank, lent_to = lend_laid(laid, blank, lent)
        if lent_to:
            verdict["lent"] = sorted(lent_to)
    if blank and "vlm" in texts and vlm_on and vlm.wanted():
        # A light no reading laid, that the readers (two of the one scan) print alike under its
        # number with its count, is laid now as tail() would lay it after the pick: the pick of
        # the VLM was spent on a clue the readers had already agreed (FT 1983-03-26: 4 across,
        # "doctor" in two readings, 1 across, 26 across).
        early, left = ocr_clues.relaid(read, laid, blank, parse, lengths, bare=bare)
        # Not one a reader printed with a mark glued to the next word ("happened.A small"): the
        # VLM's pick has the space the print has, so that one is still asked.
        for lid in blank.keys() - left.keys():
            if not SENTENCE_GLUED.search(early[lid][0] or ""):
                laid[lid] = early[lid]
                blank = {k: v for k, v in blank.items() if k != lid}
    # A window already poor before any pick, with another to try (`defer`; None: when `alts`
    # holds one), is not picked for: the best window is chosen first, and read_page picks
    # that one's blanks alone (FT 1982-02-16: 8 picks over two poor windows, then a third).
    if blank and "vlm" in texts and vlm_on and vlm.wanted() and (defer or (defer is None and alts)):
        try:
            t_laid, t_blank, _ = tail(laid, blank)
            now = {"lights": len(rg.light_cells(grid)), "blank": t_blank,
                   "agreed": sum(1 for t, _, _ in t_laid.values() if t)}
            if crop_window.poor(now, image_ok=True):
                verdict["_deferred"] = {"alt": alt, "lent": lent}
        except Exception:  # a trial that cannot be judged defers nothing
            pass
    if "_deferred" in verdict:
        verdict["vlmSkipped"] = "poor window, another to try: the best one is picked after"
    elif blank and "vlm" in texts and vlm_on and vlm.wanted():
        if doomed():
            verdict["vlmSkipped"] = "a laid clue is refused whatever the VLM picks"
        elif unpickable(texts, blank, len(rg.light_cells(grid))):
            verdict["vlmSkipped"] = "a blank clue no reading has: no pick can make the page whole"
        else:
            try:
                with vlm.because("pick:" + why_lights(blank, blank)):
                    laid, blank = vlm_pick(img, wins, list(cols.values()), texts, laid, blank, lengths)
            except RuntimeError:
                pass
    if vlm_on:
        verdict["_laid"] = {lid: v for lid, v in laid.items() if (v[0] or "").strip() and lid not in blank}
    laid, blank, alike = tail(laid, blank)
    if alike:
        verdict["asPrinted"] = alike
    if not vlm_on:
        verdict["_weak"] = weak_lights(read, laid, blank, lengths, retried)
    elif "vlm" in read and not paper.four:
        log_vlm_corpus(key, cols, read, lengths, parse, laid)
    verdict["lights"] = len(rg.light_cells(grid))
    verdict["agreed"] = sum(1 for t, _, _ in laid.values() if t)
    if blank:
        verdict["blank"] = blank
    puzzle = build(n, day, grid, how, laid, edition_of(d, found), leaf, series=paper.series,
                   name=paper.name.format(n), url=page_url(d, found, leaf), printed=alike)
    setter = byline(img, hit, paper.series)
    if setter:
        puzzle["setter"] = setter
    sol = solutions.get(n)
    if sol:
        answers, info = solved(sol, grid, above=paper_of(sol["dir"]).solution_above)
        # The answers-only checks (misread_word, uncrossed, settle_held): before 10-25 a full read filed
        # every answer its grid gave, misreads an answers-only reread of the same grid drops.
        answers, info = full_read_answers(paper, n, puzzle, sol, grid, answers, info)
        verdict["solutionFrom"] = solution_source(sol)
        verdict["solution"] = info
        verdict["answers"] = trove_solution_ocr.fill(puzzle, answers)
    return verdict, puzzle


#: The share of a reading's clues that must lie on the scanned grid by their
#: own number and count, and agree with the other readings' clue of that
#: number, for the reading to vote at all.
FIT_SHARE = 0.5
#: How like the other readings' clue of its number a clue must read to agree.
AGREE_SIMILAR = 0.5
#: How many numbered clues a reading needs before its share is judged.
FIT_MIN = 4


def numbered(parsed):
    """{(number, direction): (text, enums)} of each clue that names one light."""
    return {(next(iter(c["tokens"][0])), d): (c["text"], c["enums"])
            for d in ("across", "down") for c in parsed[d]
            if len(c["tokens"]) == 1 and len(c["tokens"][0]) == 1 and c["see"] is None}


def screened(texts, grid):
    """({reader: text} that vote, {reader: why} dropped): a reading with no
    clue words (every clue blank, or nothing but headings) is no reading,
    and one whose clues mostly name no light of the scanned grid with
    their count, or mostly disagree with what the other readings print
    under the same numbers, read another part of the page."""
    clues = {}
    for k, t in texts.items():
        p = parse(t)[0] if t.strip() else None
        clues[k] = numbered(p) if p else None
    lights = rg.light_cells(grid) if grid else None
    keep, dropped = {}, {}
    for k, t in texts.items():
        if not t.strip():
            continue
        cs = clues[k]
        if not ocr_clues.tokens(CAPS_HEADING.sub("", t)) or (
                cs and not any(ocr_clues.tokens(text) for text, _ in cs.values())):
            dropped[k] = "no clue words"
            continue
        if not cs or len(cs) < FIT_MIN:
            keep[k] = t
            continue
        # A clue whose count was lost says nothing of where it was read, and
        # a reading that lost most counts is judged by its text alone.
        counted = {key: enums for key, (_, enums) in cs.items() if enums}
        if lights and len(counted) >= max(FIT_MIN, len(cs) / 2):
            fit = sum(1 for (n, d), enums in counted.items()
                      if (n, d) in lights and any(ftp.count(e) == len(lights[(n, d)]) for e in enums))
            if fit < FIT_SHARE * len(counted):
                dropped[k] = f"{fit} of {len(counted)} counted clues lie on the grid"
                continue
        shared = []
        for key, (text, _) in cs.items():
            others = [clues[j][key][0] for j in texts if j != k and clues[j] and key in clues[j]]
            if others:
                shared.append(max(similar(text.lower(), o.lower()) for o in others))
        agree = sum(1 for v in shared if v >= AGREE_SIMILAR)
        if len(shared) >= FIT_MIN and agree < FIT_SHARE * len(shared):
            dropped[k] = f"{agree} of {len(shared)} clues agree with the other readings"
            continue
        keep[k] = t
    return keep, dropped


#: A sentence end glued to the next word's capital ("happened.A"): a space a reader lost.
SENTENCE_GLUED = re.compile(r"[a-z][.?!,;:][A-Z]")


def unpickable(texts, blank, lights):
    """True when asking the VLM to pick the `blank` clues of a page of `lights` cannot make
    it whole and the window stays: a blank light no reading has any text for is never asked
    (ocr_clues.vlm_pick has no candidates for it), so the page is unfiled however the other
    blanks go, and the picks for those are asks spent on it (the 10-20 log: 90 reads ended
    "incomplete ... unfiled", 495 asks, 78% of their blanks "no reading laid a clue on it").
    Not when the window is poor already (crop_window.poor(): FILLED/BLANK), as another window
    is read for it and the picks decide which scores best."""
    if not lights or len(blank) <= 1:
        return False  # one blank, unfillable: no pick is asked anyway
    if lights - len(blank) < crop_window.FILLED * lights or len(blank) > crop_window.BLANK * lights:
        return False
    return any(not ocr_clues.candidates(texts, lid, parse) for lid in blank)


def vlm_pick(img, wins, readings, texts, laid, blank, lengths=None):
    """ocr_clues.vlm_pick for a scan page: the VLM shown the clue columns
    (`wins`, boxed by every reading's lines); `lengths`: each light's letters."""
    return ocr_clues.vlm_pick(texts, laid, blank, parse,
                              lambda lid, cands: vlm.pick(img, wins, readings, lid, cands), lengths)


def third_top(img, grid, width):
    """Where the clue column right of the grid starts: under the solution
    grid printed beside the grid and its label ("CROSSWORD SOLUTION
    20,539", whose top lies within LABEL_DROP of the grid's foot), or level
    with the grid when none is there."""
    gx0, gy0, gx1, gy1 = grid
    crop = (gx1 + 15, max(0, gy0 - 60), min(img.width, gx1 + 15 + width), gy1)
    box = ink_box(img.crop(crop))
    if box is None:
        return gy0 - 5
    bw, bh = box[2] - box[0], box[3] - box[1]
    if not (0.4 * width <= bw <= width and 0.85 <= bw / max(bh, 1) <= 1.18):
        return gy0 - 5
    return crop[1] + box[3] + LABEL_DROP


#: How far under the solution grid its label's top may lie.
LABEL_DROP = 25


def byline(img, hit, series=FT.series):
    """The setter archive.org's words name under the title ("Set by DANTE"),
    when it is one the series' files name, a dictionary word, or what
    RapidOCR reads there too: archive.org alone misreads ("Grifftn")."""
    read = hit.get("setterRead")
    if not read or read in setters(series) or is_word(read.lower()):
        return read
    import numpy as np
    x0, y0, x1, y1 = hit["box"]
    crop = img.crop((x0, y0 - 10, x1, y1 + 10)).convert("RGB")
    crop = crop.resize((crop.width * UPSCALE, crop.height * UPSCALE))
    for which in ("en5", "ch"):
        res, _ = engine(which)(np.asarray(crop), use_cls=False)
        m = FT_SETTER.search(" ".join(t for _, t, _ in res or ()))
        if m and m.group(1).title() == read:
            return read
    return None


#: The share of a solution grid's cells that must be block or light exactly
#: where the puzzle's grid has them, for its letters to count; below
#: trove_solution_ocr.SURE_BLOCKS (a noisy print: heavy letters, stippled
#: blocks) only its lights bounded_light() keeps.
SOLUTION_BLOCKS = 0.85
#: The papers whose solution grids trove_solution_ocr's cell classifier
#: reads (read_framed(classify=True)): the Times prints it was trained on.
CELLS_CLASSIFIED = ("times", "gale")
#: The gap, in pixels, closed across a solution grid's ink before its box is
#: taken: a frame the scan broke leaves a part of the grid the largest ink
#: (Gale's 1987-01-15, 248px of its 340).
SOLUTION_CLOSE = 3


#: The width over height a solution grid's ink box may have (the grids are square; a print's
#: slant and frame give a little).
SQUARE_MIN, SQUARE_MAX = 0.85, 1.18
#: A box this far from square (wide over tall) either way holds the grid and something joined
#: to it; the grid is the square part of it (squares()).
SQUARE_FAR = (0.6, 1.7)
#: How far from square, in pixels, a box must be for squares() to cut it.
SQUARE_SLACK = 8


def squares(crop, box, above=False, at=None):
    """The square cuts of `box` (the largest ink of `crop`, a solution grid's window) that may
    be the grid when the ink holds it and something joined to it, as boxes of `crop`: a photo
    or an ad under it (the box taller than wide: its top `width`, or with `above` its bottom),
    a neighbouring column's text beside it (wider than tall: the `height`-wide window of the
    most ink, a grid being the densest ink there, and the one centred on `at`, the heading's
    middle). [] when the box is square already or beyond SQUARE_FAR of it."""
    import numpy as np
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    if abs(bw - bh) <= SQUARE_SLACK or not (SQUARE_FAR[0] <= bw / max(bh, 1) <= SQUARE_FAR[1]):
        return []
    if bw < bh:
        return [(x0, y1 - bw, x1, y1) if above else (x0, y0, x1, y0 + bw)]
    gray = np.asarray(crop.convert("L"), dtype=np.uint8)[y0:y1, x0:x1]
    ink = (gray < trove_grid.otsu(gray)).sum(axis=0)
    sums = np.concatenate([[0], np.cumsum(ink)])
    dense = int(np.argmax(sums[bh:] - sums[:len(sums) - bh]))
    out = [(x0 + dense, y0, x0 + dense + bh, y1)]
    if at is not None:
        mid = min(max(int(at - x0 - bh / 2), 0), bw - bh)
        if abs(mid - dense) > SQUARE_SLACK:
            out.append((x0 + mid, y0, x0 + mid + bh, y1))
    return out


#: The share of a matched lattice's cells (matched_box) kept in from its rules when its cells'
#: paper is measured, and the pitch step (pixels) it is searched in.
MATCH_MARGIN, MATCH_STEP = 0.2, 0.5


def matched_box(window, grid, sides):
    """(agreement, box, pitch) of the n x n lattice in `window` (a solution grid's window) whose cells
    are blocks (under trove_solution_ocr.BLOCK_PAPER of their middle paper) most nearly where
    `grid` has them, its side within `sides` ((lo, hi) pixels); None when none fits. For a grid
    whose largest ink is no box of it: joined to a neighbour's ink on a near-square box squares()
    keeps whole (1974-78's 444x434 for a 313px grid), or its frame broken (306x212)."""
    import numpy as np
    gray = np.asarray(window.convert("L"), dtype=np.uint8)
    n = len(grid)
    paper = trove_solution_ocr.opened((gray >= trove_grid.otsu(gray)).astype(np.uint8), 2).astype(np.float64)
    h, w = paper.shape
    integ = np.zeros((h + 1, w + 1))
    integ[1:, 1:] = paper.cumsum(0).cumsum(1)
    want = np.array([[ch == "#" for ch in row] for row in grid])
    best = None
    for pitch in np.arange(sides[0] / n, sides[1] / n + 1e-9, MATCH_STEP):
        side = pitch * n
        ny, nx = int(h - side) + 1, int(w - side) + 1
        if ny <= 0 or nx <= 0:
            break
        k = max(1, int(round(pitch * (1 - 2 * MATCH_MARGIN))))
        # The mean paper of the k x k square at each top-left (y, x).
        m = (integ[k:, k:] - integ[:-k, k:] - integ[k:, :-k] + integ[:-k, :-k]) / (k * k)
        off = int(round(pitch * MATCH_MARGIN))
        score = np.zeros((ny, nx))
        for r in range(n):
            y = int(round(r * pitch)) + off
            for c in range(n):
                x = int(round(c * pitch)) + off
                blk = m[y:y + ny, x:x + nx] < trove_solution_ocr.BLOCK_PAPER
                score += blk if want[r, c] else ~blk
        # Of lattices whose blocks fit alike (a smaller or larger one fits big blocks as well), the
        # one whose frame lies on the grid's ink: its frame's paper share, under one cell's worth.
        s = int(round(side))
        rows = (integ[1:, s:] - integ[:-1, s:] - integ[1:, :-s] + integ[:-1, :-s]) / s
        cols = (integ[s:, 1:] - integ[s:, :-1] - integ[:-s, 1:] + integ[:-s, :-1]) / s
        frame = (rows[:ny, :nx] + rows[s - 1:s - 1 + ny, :nx] + cols[:ny, :nx] + cols[:ny, s - 1:s - 1 + nx]) / 4
        fit = score - 0.5 * frame
        y0, x0 = divmod(int(fit.argmax()), nx)
        if best is None or fit[y0, x0] > best[3]:
            best = (float(score[y0, x0]) / (n * n), (x0, y0, x0 + s, y0 + s), pitch, float(fit[y0, x0]))
    return best and best[:3]


def worded(word, enum=None):
    """Whether answer `word` is a word (is_word), or the words its enumeration ("5-4", "(3,5)")
    cuts it into are."""
    if is_word(word.lower()):
        return True
    parts = [int(x) for x in re.findall(r"\d+", enum or "")]
    if len(parts) < 2 or sum(parts) != len(word):
        return False
    at = 0
    for p in parts:
        if not is_word(word[at:at + p].lower()):
            return False
        at += p
    return True


def read_solution(img, sol, grid, above=False, lean=False, enums=None):
    """({light: answer}, stats) read off the solution grid under a "Solution
    to Puzzle No N" heading on page `img`, or with `above`, over it (the
    Guardian's). Its code is solution_key()'s. With `lean` (answers_only, which
    checks every answer against its light and crossings) a grid is read on the
    one lattice that accepts every light, not on all three (read_framed).
    The largest ink under the heading is the grid when it is square; when it is not
    (a photo under it, a neighbour column's text beside it: 1993's pages, 103 of
    them refused as 344x426) or its blocks are not the puzzle's, the square cuts of it
    (squares()) are read too, and the one whose blocks agree most is the grid."""
    d = sol["dir"]
    x0, y0, x1, y1 = sol["box"]
    from PIL import Image
    w = x1 - x0
    crop = (max(0, x0 - 80), y1, min(img.width, x1 + 140), min(img.height, y1 + int(1.4 * w) + 60))
    if above:
        crop = (max(0, x0 - 80), max(0, y0 - int(1.4 * w) - 60), min(img.width, x1 + 140), y0)
    window = img.crop(crop)
    box = ink_box(window, SOLUTION_CLOSE)
    # A heading box that lost its first words ("terday's solution 25,266", Gale 2012: 137px of a
    # 357px grid) leaves the grid's left and foot beyond the window: the window is grown left and
    # down (up, with `above`) while the ink touches those edges, and kept so only where it brings
    # the ink nearer a square.
    for _ in range(3):
        if box is None:
            break
        left = box[0] <= 2 and crop[0] > 0
        far = box[1] <= 2 and crop[1] > 0 if above else box[3] >= window.height - 2 and crop[3] < img.height
        if not (left or far):
            break
        grown = (max(0, crop[0] - 80) if left else crop[0],
                 max(0, crop[1] - 80) if far and above else crop[1], crop[2],
                 min(img.height, crop[3] + 80) if far and not above else crop[3])
        more = ink_box(img.crop(grown), SOLUTION_CLOSE)
        if more is None or abs((more[2] - more[0]) - (more[3] - more[1])) > abs((box[2] - box[0]) - (box[3] - box[1])):
            break
        crop, box = grown, more
        window = img.crop(crop)
    if box is None:
        return {}, {"refused": "no ink under the heading"}
    bw, bh = box[2] - box[0], box[3] - box[1]
    cuts = squares(window, box, above, (x0 + x1) / 2 - crop[0])
    boxes = [box] if SQUARE_MIN <= bw / max(bh, 1) <= SQUARE_MAX else []
    boxes += cuts
    boxes = [b for b in boxes if 200 <= b[2] - b[0] <= 800 and SQUARE_MIN <= (b[2] - b[0]) / max(b[3] - b[1], 1) <= SQUARE_MAX]
    classify = paper_of(d).key in CELLS_CLASSIFIED
    if not boxes and not classify:
        return {}, {"refused": f"the ink under the heading is {bw}x{bh}"}
    path = CROPS / "solutions" / f"{d.name}_{sol['number']}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    best = None

    def read(b):
        # Cut afresh on every read, so the crop is always this code's cut.
        cut = window.crop(b)
        # The recogniser reads the ~23px cells far surer at three times the size.
        cut.resize((cut.width * 3, cut.height * 3), Image.BICUBIC).save(path)
        # The crop is the grid, frame to frame: read on its own rules; a Times
        # print's cells by the cell classifier too, which was trained on them.
        return trove_solution_ocr.read_answers(path, grid, tight=True, bounded=True, classify=classify,
                                               lean=lean, enums=enums)
    for b in boxes:
        answers, stats = read(b)
        if best is None or stats["blocks"] > best[1]["blocks"]:
            best = (answers, stats)
        if stats["blocks"] >= SOLUTION_BLOCKS:
            break
    if (best is None or best[1]["blocks"] < SOLUTION_BLOCKS) and classify:
        # No ink box is the grid (joined to a neighbour's ink, or its frame broken): the lattice
        # in the window whose blocks match the puzzle's is, its frame kept in a quarter cell's
        # margin. Its read stands only as any read does, by its own blocks (SOLUTION_BLOCKS).
        found = matched_box(window, grid, (200, min(800, window.width, window.height)))
        if found and found[0] >= SOLUTION_BLOCKS:
            pad = int(round(found[2] / 4))
            x0, y0, x1, y1 = found[1]
            answers, stats = read((max(0, x0 - pad), max(0, y0 - pad), min(window.width, x1 + pad),
                                   min(window.height, y1 + pad)))
            # A matched grid's ink is read past what joined it, its letters less sure: an answer
            # stands only as a word, or words by its enumeration (1978's AQUALUNG read AGUALUNG).
            kept = {k: w for k, w in answers.items() if worded(w, (enums or {}).get(k))}
            if best is None or stats["blocks"] > best[1]["blocks"]:
                best = (kept, {**stats, "matched": round(found[0], 3), "accepted": len(kept),
                               "unworded": len(answers) - len(kept)})
    if best is None:
        return {}, {"refused": f"the ink under the heading is {bw}x{bh}"}
    answers, stats = best
    if stats["blocks"] < SOLUTION_BLOCKS:
        return {}, {**stats, "refused": "its blocks are not the puzzle's"}
    return {f"{n}-{d}": w for (n, d), w in answers.items()}, stats


# ------------------------------------------------------------ the run

#: Editions read at once: the desktop VLM serves one request at a time, so a
#: second one's OCR fills the first one's wait; more contend for the host's
#: four cores.
WORKERS = 2
#: How often (seconds) the scan phase saves the ledger.
SAVE_EVERY = 300


def scan_key(paper=None):
    """A hash of the code that finds `paper`'s (the Times's by default)
    titles and solution headings, and no other paper's (scan_keys)."""
    import code_reach
    return scan_keys(code_reach.TRANSPORT + code_reach.SIZING)[_paper_name(paper)]


def sized_scan_key(paper=None):
    """scan_key() with the thread-pool sizing in: the same scan, re-keyed
    to scan_key() (rekey_scans), never scanned again."""
    import code_reach
    return scan_keys(code_reach.TRANSPORT)[_paper_name(paper)]


def paper_defs(tree):
    """(papers, tables) of a module syntax tree: the module-level names
    bound to a Paper(...), and those of every other module-level assignment
    that names one (PAPERS, FILERS, ALSO)."""
    papers, tables = set(), set()
    assigns = [n for n in tree.body if isinstance(n, ast.Assign)]
    for n in assigns:
        if isinstance(n.value, ast.Call) and getattr(n.value.func, "id", None) == "Paper":
            papers.update(t.id for t in n.targets if isinstance(t, ast.Name))
    for n in assigns:
        names = {t.id for t in n.targets if isinstance(t, ast.Name)}
        if not names & papers and any(isinstance(x, ast.Name) and x.id in papers for x in ast.walk(n.value)):
            tables |= names
    return papers, tables


def scan_keys(opaque, texts=None):
    """{Paper's module-level name: its scan key}. A key hashes what scan()
    reaches (tools/code_reach.py: a method only when called, comments and
    docstrings left out) with every Paper and every table naming one left
    out, then what that paper's own definition reaches (its item, its
    headings parser, the number its date implies) with the other papers
    left out, past the `opaque` modules and definitions (the desktop
    transport and thread-pool sizing). So adding or changing one paper
    moves only its own key, and a scan made by other code is made again;
    an edit to code scan() never runs changes nothing. `texts` ({module:
    source}) stands in for files (tests)."""
    if texts is None and opaque in _SCAN_KEYS:
        return _SCAN_KEYS[opaque]
    import code_reach
    me = "file_archive_org_puzzles"
    papers, tables = paper_defs(ast.parse((texts or {}).get(me) or Path(__file__).read_text(encoding="utf-8")))
    left = tuple(f"{me}.{n}" for n in sorted(papers | tables))
    shared = code_reach.key(me, SCAN_ROOTS, texts, opaque=opaque + left)
    out = {}
    for name in sorted(papers):
        own = code_reach.key(me, {name}, texts, opaque=opaque + tuple(n for n in left if n != f"{me}.{name}"))
        out[name] = hashlib.sha256(f"{shared}\n{own}".encode()).hexdigest()[:16]
    if texts is None:
        _SCAN_KEYS[opaque] = out
    return out


def _paper_name(paper):
    """The module-level name of Paper `paper` (TIMES by default)."""
    paper = paper or TIMES
    name = _PAPER_NAMES.get(id(paper))
    if name is None or globals().get(name) is not paper:
        name = _PAPER_NAMES[id(paper)] = next(k for k, v in globals().items() if v is paper and k.isupper())
    return name


#: {id(Paper): _paper_name}, the name checked still bound to it on each hit:
#: the queue's main thread asks scan_current of every queued scan each pass,
#: and a walk of the module's ~500 globals was most of each ask.
_PAPER_NAMES = {}


#: The corpus-wide scan keys of the code before each paper had a key of its
#: own, each with {paper key: the scan_key() of that same code}: a row under
#: one stands while its paper's key is the one named (current_keys), and
#: rekey_scans moves it there.
_CORPUS_PAPERS = {"times": "0e663a8f51a2d840", "times1930": "9bd5e92db2bd9a53", "ft": "ec1c493d7a63b2ae",
                  "guardian": "503a6e254efafd7c", "telegraph": "7d84cc09fe38bd9d", "gale": "9563e1b93356e0dc"}
CORPUS_KEYS = {"f5d96d62730b57d5": _CORPUS_PAPERS, "631672b37146c86b": _CORPUS_PAPERS}
#: {paper key: (scan_key, sized_scan_key) before band_words wrote its cache atomically and
#: read an unreadable one as a miss, scan_key after}: that edit is to code scan() reaches but
#: moves no scan's result, so the scans under the old keys stand (current_keys) and
#: rekey_scans moves them.
_BAND_CACHE_FIX = {
    "ft": ("2a16e9f1fd466f50", "56fe3caebad2b5bb", "b5a9547b6ba1b011"),
    "gale": ("6ebe01438fbef354", "6a011e7e5d96ec18", "dedd7fe3f7abfefb"),
    "galeft": ("3241c7509ed886ca", "dc2225eceb34355d", "42259f1d59f49601"),
    "galeindependent": ("aa42976d3d002fa5", "9266e203d752b6a7", "01bdb8d0a846dd0f"),
    "galesundaytimes": ("cf19092cd0a9c451", "fd7048d9bb2d5f17", "035bd707b488443f"),
    "galetelegraph": ("4ae0f3e07bbb68cd", "8726b988f05e0cc2", "fc62368f9ce2f471"),
    "galetls": ("d7509cafb9ea40c4", "82178c19e214a9c4", "c20a08156e78314f"),
    "guardian": ("2cdda7edc65acd51", "998022d2180ffa29", "70e174678220d20e"),
    "telegraph": ("b3809b473f0fd01d", "563016d857904d06", "24c84ee2abcf3607"),
    "times": ("1743a4444df41960", "46c602ea68b713c2", "e5e7a6fad3527737"),
    "times1930": ("ebb010eefdcdbb6d", "a3cc6c34daf75219", "9ef2131e09133cb0"),
}
CORPUS_KEYS.update({old: {paper: pins[2]} for paper, pins in _BAND_CACHE_FIX.items() for old in pins[:2]})
#: {paper key: (scan_key, sized_scan_key, scan_key after)} before printed_lines
#: joined a title's number to its title past another column's speck and
#: gale_headings read a Gale page's "Solution to yesterday's crossword" as the
#: solution heading it is: an edit to code every paper's scan reaches, but
#: only the Gale Times pages' scans (no djvu text, title read off the page)
#: it moves; the other papers' scans stand under their old keys. The Gale
#: Times (gale) is scanned again.
_LINES_FIX = {
    "ft": ("b5a9547b6ba1b011", "38bb34a8c63766dc", "873f163269afb857"),
    "galeft": ("42259f1d59f49601", "c1cdd7ff200f6886", "2aa5bda7ccc446d2"),
    "galeindependent": ("01bdb8d0a846dd0f", "03899a7fd1014aec", "49e5aa898f77c900"),
    "galesundaytimes": ("035bd707b488443f", "9da58a9026e6f5d3", "da64c98f54178a8c"),
    "galetelegraph": ("fc62368f9ce2f471", "aab5380b0deca0ae", "80896c9302ec7e7b"),
    "galetls": ("c20a08156e78314f", "afa2632c0a58943a", "cf369c2954aa9130"),
    "guardian": ("70e174678220d20e", "5dfdc58dc3f12eae", "34ed1a212a8cddc4"),
    "telegraph": ("24c84ee2abcf3607", "4c5024af88621236", "df3912f16a91f7f5"),
    "times": ("e5e7a6fad3527737", "cf95a7905201b627", "930dd842c679fca1"),
    "times1930": ("9ef2131e09133cb0", "e2816b3064f23306", "81aad3c2558f6560"),
}
CORPUS_KEYS.update({old: {paper: pins[2]} for paper, pins in _LINES_FIX.items() for old in pins[:2]})
# The keys before the band cache fix stand where the lines fix leaves their paper's scans.
CORPUS_KEYS.update({old: {paper: _LINES_FIX[paper][2]} for paper, pins in _BAND_CACHE_FIX.items()
                    if paper in _LINES_FIX for old in pins[:2]})
#: {paper key: (scan_key, sized_scan_key, scan_key after)} before FT_TITLE read
#: "FT CROSS PUZZLE No. 6,319" (the 1987 weekday title, "WORD" lost to the
#: print) as a title: the FT's and the Gale FT's scans of every other page
#: find the same, so they stand under their old keys. The 1987 editions the
#: fetcher gave new leaves (FT_UNIT_TRUST_BACKS) are due by their files.
_TITLE_FIX = {
    "ft": ("873f163269afb857", "04fb1bafc559cf02", "f8fa782027006f36"),
    "galeft": ("2aa5bda7ccc446d2", "b5b783223398fc74", "b91e60f0bf486bd0"),
}
for _paper, _pins in _TITLE_FIX.items():
    for _keys in CORPUS_KEYS.values():
        if _keys.get(_paper) == _pins[0]:
            _keys[_paper] = _pins[2]
    CORPUS_KEYS.update({old: {_paper: _pins[2]} for old in _pins[:2]})
#: {paper key: (scan_key, sized_scan_key, scan_key after)} before ocr_clues.read_words kept its
#: readings on disk (WORDS_CACHE: a restarted read reads each crop once): an edit to code every
#: paper's scan reaches that moves no reading, so the scans under the old keys stand.
_WORDS_CACHE_FIX = {
    'ft': ('f8fa782027006f36', 'd70116d5b4587cfb', '6f126cec76a9da34'),
    'gale': ('d470e20725cfad05', '576a9788a8fc47e2', '3129653d3ea92bb6'),
    'galeft': ('b91e60f0bf486bd0', '94aed6451a6413f7', 'e56475066ddb1198'),
    'galeindependent': ('49e5aa898f77c900', '79254bacf6b39b92', '435c9cfc94ae8e79'),
    'galesundaytimes': ('da64c98f54178a8c', '29ac688546d9bf23', 'ab29b4d8a0d49880'),
    'galetelegraph': ('80896c9302ec7e7b', '747de3620207d8d7', '2710eb7f5728dfad'),
    'galetls': ('cf369c2954aa9130', 'e310838465482ff7', 'ef730323537ce941'),
    'guardian': ('34ed1a212a8cddc4', '2b7c3f6cc94d05e0', '3e8d1907b65b2142'),
    'telegraph': ('df3912f16a91f7f5', 'e97d6b32e0954c12', '3e84c20d8749529a'),
    'times': ('930dd842c679fca1', 'ed3db9056c358409', '6c00a2f34e6f42d7'),
    'times1930': ('81aad3c2558f6560', 'd17fad46a07843fc', '37c08a1d050a7f0d'),
}
for _paper, _pins in _WORDS_CACHE_FIX.items():
    for _keys in CORPUS_KEYS.values():
        if _keys.get(_paper) == _pins[0]:
            _keys[_paper] = _pins[2]
    CORPUS_KEYS.update({old: {_paper: _pins[2]} for old in _pins[:2]})
#: {paper key: (scan_key, sized_scan_key, scan_key after)} before LOOSE_SOLUTION took a
#: nine-letter middle word, YESTERDAY_SOLUTION joined the solution patterns, a single
#: reader's solution headings stood once the titles were voted, and the grid-size cap went
#: 700 -> 800: edits that move only the Times's and the Gale Times's scans (the only
#: papers whose headings they read), so every other paper's scans stand under their old
#: keys. The Times (times) and the Gale Times (gale) are scanned again.
_SOLUTION_HEADINGS_FIX = {
    "ft": ("6f126cec76a9da34", "7cf1a456b14bf436", "db66b411d68b6315"),
    "galeft": ("e56475066ddb1198", "a78424e2e7cb39df", "4e9bd3af3ac0e35e"),
    "galeindependent": ("435c9cfc94ae8e79", "57557f9430b62de8", "91aa916982ce2a89"),
    "galesundaytimes": ("ab29b4d8a0d49880", "0c45ee654e8a1eb1", "98239ec5a4bfa3f2"),
    "galetelegraph": ("2710eb7f5728dfad", "0cd985fc79b727f9", "1b1dfd8b6e92ff89"),
    "galetls": ("ef730323537ce941", "1699c866c2be4a6a", "2dcf3e24dcf440b8"),
    "guardian": ("3e8d1907b65b2142", "50a3f494a6f34248", "aa76462452b63be8"),
    "telegraph": ("3e84c20d8749529a", "c794daa7354d3395", "a08343d90831fdcf"),
    "times1930": ("37c08a1d050a7f0d", "e9488468f838b696", "5356ffb7ac6d88b0"),
}
for _paper, _pins in _SOLUTION_HEADINGS_FIX.items():
    for _keys in CORPUS_KEYS.values():
        if _keys.get(_paper) == _pins[0]:
            _keys[_paper] = _pins[2]
    CORPUS_KEYS.update({old: {_paper: _pins[2]} for old in _pins[:2]})
#: {paper key: (scan_key, sized_scan_key, scan_key after)} before PRIZE_SOLUTION headings (a Saturday
#: prize's solution, printed on the Monday week after) were read: an edit that moves only the Gale
#: Times's Mondays of 2000 on (prize_rescan) and the Times's scans, so every other scan stands under its
#: old key. The Gale Times's other days print no such heading; its Mondays are scanned again.
_PRIZE_HEADINGS_FIX = {
    "ft": ("db66b411d68b6315", "9be2dfe9f810e4d5", "604efcc22e60dab4"),
    "gale": ("1fd1f7be060ac3f9", "c257cea80704b3eb", "9a03612709722b4c"),
    "galeft": ("4e9bd3af3ac0e35e", "e9d481128c481509", "39493020d8bde34a"),
    "galeindependent": ("91aa916982ce2a89", "8e4dad8a3e9af3da", "a469fc46cf0886a4"),
    "galesundaytimes": ("98239ec5a4bfa3f2", "f324bc6d512dc84b", "1e08d552cfc3d213"),
    "galetelegraph": ("1b1dfd8b6e92ff89", "5972e3edbf2cd079", "8d387b0dc084706c"),
    "galetls": ("2dcf3e24dcf440b8", "58313ebc0991967b", "0a6f00f16d61d22e"),
    "guardian": ("aa76462452b63be8", "c72d5c8a1a8bffd9", "2800b3094dc4239d"),
    "telegraph": ("a08343d90831fdcf", "92ef1f1314da72a2", "209b8be1c3754753"),
    "times1930": ("5356ffb7ac6d88b0", "3d22e9da5ce57d51", "6af567f7553f1ad4"),
}
for _paper, _pins in _PRIZE_HEADINGS_FIX.items():
    for _keys in CORPUS_KEYS.values():
        if _keys.get(_paper) == _pins[0]:
            _keys[_paper] = _pins[2]
    CORPUS_KEYS.update({old: {_paper: _pins[2]} for old in _pins[:2]})
#: {paper key: (scan_key, sized_scan_key, scan_key after)} before SOLUTION_BAND widened 420 -> 560
#: (a solution heading's "Solution to Crossword 23,xxx" was cut after "23" on the Gale Times's
#: 4664 px pages of mid-2005 to mid-2006): an edit that moves only those pages' readings
#: (BAND_RESCAN), so every other paper's, and every other year's, scans stand under their old keys.
_BAND_WIDTH_FIX = {
    "ft": ("604efcc22e60dab4", "fa7c29482db09656", "7d90c2e969e56a3e"),
    "gale": ("9a03612709722b4c", "24ec9bfd50ad1727", "a96808d5cf7321db"),
    "galeft": ("39493020d8bde34a", "e302fec8ca39c63d", "97fba7a8662935b9"),
    "galeindependent": ("a469fc46cf0886a4", "f9354413a479d93e", "cc18a3c765cea272"),
    "galesundaytimes": ("1e08d552cfc3d213", "94d82dc19efcce25", "b022b18869e67e6a"),
    "galetelegraph": ("8d387b0dc084706c", "8cbe789f6e12b38f", "ac23af44ca0b657e"),
    "galetls": ("0a6f00f16d61d22e", "e4b4f05f021de79f", "3576aeefb5be4ac2"),
    "guardian": ("2800b3094dc4239d", "6c168b074df2f5e3", "6de21c994894fdd0"),
    "telegraph": ("209b8be1c3754753", "92a2c4f29be0d52f", "745aa185e086920e"),
    "times": ("7907f625fccc7220", "9b817267fc1c746e", "147f0d4168d00f9d"),
    "times1930": ("6af567f7553f1ad4", "ac6cd9c7944a9a81", "07bb383d98cafae3"),
}
for _paper, _pins in _BAND_WIDTH_FIX.items():
    for _keys in CORPUS_KEYS.values():
        if _keys.get(_paper) == _pins[0]:
            _keys[_paper] = _pins[2]
    CORPUS_KEYS.update({old: {_paper: _pins[2]} for old in _pins[:2]})
#: {paper key: (scan_key, sized_scan_key, scan_key after)} before solution_shaped's cap on a solution
#: grid's width grew with the page's (a 4664 px page's grid is 510 wide at SCAN_WIDTH, the cap was
#: 480, so those pages found no solution heading at all): an edit that moves only the pages wider
#: than SCAN_WIDTH (BAND_RESCAN), so every other paper's, and every other year's, scans stand.
_GRID_CAP_FIX = {
    "ft": ("7d90c2e969e56a3e", "d6ae6220db7a22f4", "a8b00443824ec045"),
    "gale": ("a96808d5cf7321db", "8f1bbdca0d22cbaf", "ca46afbc28bc7691"),
    "galeft": ("97fba7a8662935b9", "7d16a027df235a2b", "02c31abdb042191e"),
    "galeindependent": ("cc18a3c765cea272", "c94a71a0f4d063e2", "0e7c077fe1b3301b"),
    "galesundaytimes": ("b022b18869e67e6a", "08388ac36b8c7084", "9072b147a8ea77a7"),
    "galetelegraph": ("ac23af44ca0b657e", "022767a6ea18d16d", "bda8c1b263bb6491"),
    "galetls": ("3576aeefb5be4ac2", "d89487f9425f3a5d", "16fa4037d19595f8"),
    "guardian": ("6de21c994894fdd0", "ececeb7447008dbc", "b35ed17631eaeb15"),
    "telegraph": ("745aa185e086920e", "780fc6ff358d1a77", "839dc6737436fd27"),
    "times": ("147f0d4168d00f9d", "c79e36c96055e1c7", "37544b124ba27f6a"),
    "times1930": ("07bb383d98cafae3", "6abcdaccd5d602b9", "56eea6322c5e26e5"),
}
for _paper, _pins in _GRID_CAP_FIX.items():
    for _keys in CORPUS_KEYS.values():
        if _keys.get(_paper) == _pins[0]:
            _keys[_paper] = _pins[2]
    CORPUS_KEYS.update({old: {_paper: _pins[2]} for old in _pins[:2]})
#: {paper key: (scan_key, sized_scan_key, scan_key after)} before solution_number skipped
#: expected numbers below 1 (a 1930 page's count back from its first puzzle gave -1, and
#: str(-1) has no DIGIT_READS: KeyError '-'): pages that crashed now read, every other scan stands.
_NEG_EXPECTED_FIX = {
    "ft": ("a8b00443824ec045", "13c1fe5834f72ff7", "43018f01942ece0f"),
    "gale": ("ca46afbc28bc7691", "769569d7ffc90869", "5e9af7144cffef60"),
    "galeft": ("02c31abdb042191e", "22196a13cf05d976", "2d5b8b81e4fb0d47"),
    "galeindependent": ("0e7c077fe1b3301b", "871c55e8bc565891", "b8c1b025d61124da"),
    "galesundaytimes": ("9072b147a8ea77a7", "1c225740a32eb657", "7fc67a9979068268"),
    "galetelegraph": ("bda8c1b263bb6491", "4e85918347adf664", "acde5a14a395d485"),
    "galetls": ("16fa4037d19595f8", "b223a8c16d1635df", "006dfca3e9281e15"),
    "guardian": ("b35ed17631eaeb15", "119f0e7f9feca41c", "10e9613a68e1357f"),
    "telegraph": ("839dc6737436fd27", "4ae775bb707087b6", "baab35690b42642d"),
    "times": ("37544b124ba27f6a", "1aba9eed995b236f", "80a310e7930c3dea"),
    "times1930": ("56eea6322c5e26e5", "99a87675da2c6c4e", "ec9192e295a4f7f6"),
}
for _paper, _pins in _NEG_EXPECTED_FIX.items():
    for _keys in CORPUS_KEYS.values():
        if _keys.get(_paper) == _pins[0]:
            _keys[_paper] = _pins[2]
    CORPUS_KEYS.update({old: {_paper: _pins[2]} for old in _pins[:2]})
#: {paper key: (scan_key, sized_scan_key, scan_key after)} before LOOSE_NUMBER took a dot leader glued
#: to a heading's number ("SOLUTION OF PUZZLE No. 10,052...."): it links only headings that linked
#: nothing, so every scan stands, the Times's and the Gale Times's too; the Gale hosts of puzzles
#: filed with no answer are read in their solution bands once more (REREAD_HOST_HEADINGS, cached band
#: reads). Paul 10-25: ~190 unanswered Times puzzles' hosts read such a heading and linked none.
_DOT_LEADER_FIX = {
    "ft": ("43018f01942ece0f", "b17950eef3d4a500", "470b3be9817bc707"),
    "gale": ("5e9af7144cffef60", "f0905ad7ac1e794d", "88e35d105e756b77"),
    "galeft": ("2d5b8b81e4fb0d47", "7c599da499cc7b83", "901ab903027df717"),
    "galeindependent": ("b8c1b025d61124da", "9e26168d4725643d", "d06b4823d93fa78c"),
    "galesundaytimes": ("7fc67a9979068268", "aada3ee5d883be70", "82609412d7065146"),
    "galetelegraph": ("acde5a14a395d485", "54337e87fa502f94", "7396432ab4bcf5b4"),
    "galetls": ("006dfca3e9281e15", "4bcca0f41ccad621", "278bb7c3611fced5"),
    "guardian": ("10e9613a68e1357f", "f21be155ce2fba8f", "60a33bf7f44aaa68"),
    "telegraph": ("baab35690b42642d", "87cffdd755e9f090", "844c851a165304e5"),
    "times": ("80a310e7930c3dea", "6c9889a44722c970", "a0f82f7d8ff7c028"),
    "times1930": ("ec9192e295a4f7f6", "121387b8415f6bae", "9282185cc921b19a"),
}
for _paper, _pins in _DOT_LEADER_FIX.items():
    for _keys in CORPUS_KEYS.values():
        if _keys.get(_paper) == _pins[0]:
            _keys[_paper] = _pins[2]
    CORPUS_KEYS.update({old: {_paper: _pins[2]} for old in _pins[:2]})
#: {paper key: (scan_key, sized_scan_key, scan_key after)} before solution_at read the 2006-07 Monday's
#: "Competition Solution 23,450" (COMPETITION_SOLUTION) and unspecked parted a mark glued before a heading's
#: number ("Solution to Crossword.21,677"): both link only headings that linked nothing, so every scan
#: stands, the Times's and the Gale Times's too. The Gale hosts of puzzles filed with no answer are read in
#: their solution bands once more (REREAD_HOST_HEADINGS), where day_headings also reads "Solution to
#: yesterday's" over "Crossword 22,204". Paul 10-25: ~50 unanswered 2000s Times puzzles' hosts printed these.
_DAY_HEADING_FIX = {
    "ft": ("470b3be9817bc707", "c12ba916bedcebfe", "07726c4a4c88f8eb"),
    "gale": ("88e35d105e756b77", "295644727aaf0696", "b22cb4022147145e"),
    "galeft": ("901ab903027df717", "24aae059123f354f", "fe8ad8a8474e675f"),
    "galeindependent": ("d06b4823d93fa78c", "ac3d167690e7f51d", "efec33309a8a7e9a"),
    "galesundaytimes": ("82609412d7065146", "832816eaa8ccd12c", "6be8a305b502ea0d"),
    "galetelegraph": ("7396432ab4bcf5b4", "dcd620c2efaea810", "93c86242b7ba3542"),
    "galetls": ("278bb7c3611fced5", "dd122ab1f6de2c04", "f63e8c6f5679c7c7"),
    "guardian": ("60a33bf7f44aaa68", "a76b1c68318476f6", "360c98fc36e63266"),
    "telegraph": ("844c851a165304e5", "5c6bc4e0faad0739", "9e498503509faf7c"),
    "times": ("a0f82f7d8ff7c028", "76835109ba9c42e2", "516f28b9e031d6a9"),
    "times1930": ("9282185cc921b19a", "4657569ce8da974c", "5d9d486af4b94a99"),
}
for _paper, _pins in _DAY_HEADING_FIX.items():
    for _keys in CORPUS_KEYS.values():
        if _keys.get(_paper) == _pins[0]:
            _keys[_paper] = _pins[2]
    CORPUS_KEYS.update({old: {_paper: _pins[2]} for old in _pins[:2]})
#: The Gale Times days (first, last) whose pages are 4600 px wide, scanned again for the wider
#: band and grid cap.
BAND_RESCAN = (datetime.date(2005, 5, 1), datetime.date(2006, 9, 30))


def prize_rescan(paper, key, rel):
    """Whether a scan of edition `rel` of `paper` under scan key `key` is due again for a heading
    reader fix: a Gale Times Monday (prize_monday) scanned before the prize headings
    (_PRIZE_HEADINGS_FIX), or a Gale Times day of BAND_RESCAN scanned before the wider
    SOLUTION_BAND (_BAND_WIDTH_FIX) and the grid cap grown with the page (_GRID_CAP_FIX)."""
    if paper is not GALE or not isinstance(rel, str) or (day := _date_in(rel)) is None:
        return False
    if key in _PRIZE_HEADINGS_FIX["gale"][:2] and prize_monday(day):
        return True
    return (key not in (_GRID_CAP_FIX["gale"][2], _NEG_EXPECTED_FIX["gale"][2], _DOT_LEADER_FIX["gale"][2],
                        _DAY_HEADING_FIX["gale"][2])
            and BAND_RESCAN[0] <= day <= BAND_RESCAN[1])


def current_keys(paper):
    """The scanKeys a scan of one of `paper`'s editions stands under."""
    key, sized = scan_key(paper), sized_scan_key(paper)
    corpus = tuple(k for k, keys in CORPUS_KEYS.items() if keys.get(paper.key) == key)
    hit = _CURRENT_KEYS.get((key, sized, corpus))
    if hit is None:
        hit = _CURRENT_KEYS[(key, sized, corpus)] = frozenset({key, sized, *corpus})
    return hit


#: current_keys by everything it is made of, so a pass's thousands of asks
#: share one set (a test that moves CORPUS_KEYS gets another).
_CURRENT_KEYS = {}


def rekey_scans(ledger):
    """Re-key the rows of `ledger` scanned under another of their paper's
    current_keys() to its scan_key(), unless a run holds it; how many."""
    import fcntl
    if not ledger.exists():
        return 0
    with open(scan_queue.lock_path(ledger), "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        rows = scan_queue.jsonl_rows(ledger)
        moved = {}
        for k, r in enumerate(rows):
            paper = paper_of(r.get("edition", ""))
            new = scan_key(paper)
            if r.get("scanKey") != new and r.get("scanKey") in current_keys(paper) \
                    and not prize_rescan(paper, r.get("scanKey"), r.get("edition")):
                moved[k] = new
        if moved:
            tmp = ledger.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps({**r, "scanKey": moved[k]} if k in moved else r) + "\n"
                                   for k, r in enumerate(rows)), encoding="utf-8")
            tmp.replace(ledger)
            scan_queue.stamp(ledger)
        return len(moved)


#: Where scan_key() starts.
SCAN_ROOTS = {"scan"}
_SCAN_KEYS = {}


def solution_key():
    """A hash of the code that reads a solution grid off its page
    (read_solution and what it reaches), past the transport and thread-pool
    sizing: a row whose solution was read in part or refused by other code
    is read again (fix_reason)."""
    if not _SOLUTION_KEY:
        import code_reach
        _SOLUTION_KEY.append(code_reach.key("file_archive_org_puzzles", {"read_solution"},
                                            opaque=code_reach.TRANSPORT + code_reach.SIZING))
    return _SOLUTION_PINS.get(_SOLUTION_KEY[0], _SOLUTION_KEY[0])


_SOLUTION_KEY = []
#: {solution key of newer code: the key it stands in for}, for a change that reads the same
#: answers (read_framed's `lean` for answers_only, and listed_of built off the words' bytes):
#: the rows read under the old key are not read again for it (fix_reason). unlisted_reads (answers_only
#: only, reads more) is pinned too: the rows it may improve are due once by REREAD_UNLISTED instead
#: (short_again), not every short Times row as "read by other code". So is matched_box, which reads
#: only a grid every ink box was refused for: those rows are due once as REFUSED_GRID. So is
#: name_only (a surname cmudict alone lists decodes only where every cell is sure: TROEGER), which
#: only takes fewer lights: a row read before it reads no more for it.
_SOLUTION_PINS = {"5686cee2aa70239b": "41a56d0904b08e42", "b41c45427ac4fa11": "f9c2185f7546a1b8",
                  "056213fe33f38ceb": "8417cfb08f3a9706", "a2b38825dd50dc6a": "8417cfb08f3a9706",
                  "e1f457cc02985dda": "8417cfb08f3a9706", "f9e93b539e79a435": "8417cfb08f3a9706",
                  # blocks_sure (a heavy print's grid classified): those rows are due once as HEAVY_PRINT.
                  "c152cf1325047f62": "8417cfb08f3a9706",
                  # sure_framing and VERY_HEAVY_EXTRA (classify grids none was classified on): due once
                  # as SURE_FRAMING.
                  "fd768722a95d6269": "8417cfb08f3a9706",
                  # LOOSE_NUMBER's dot leader (_DOT_LEADER_FIX): no grid is read otherwise.
                  "7a7113210025b6ae": "8417cfb08f3a9706",
                  # COMPETITION_SOLUTION and a mark glued before a number (_DAY_HEADING_FIX): no grid is
                  # read otherwise.
                  "707dd4b1636238eb": "8417cfb08f3a9706"}


def solved(sol, grid, above=False, lean=False, enums=None):
    """read_solution of `sol`'s page for `grid`, kept under
    CROPS/solution_reads by everything it reads from (its code and page()'s,
    the leaf's size, the heading's box, `above`, the grid), so a re-read for
    a clue-vote change runs no solution OCR. Outside read_solution's reach:
    solution_key() stays the reader's."""
    if not _SOLVED_CODE:
        import code_reach
        _SOLVED_CODE.append(code_reach.key("file_archive_org_puzzles", {"read_solution", "page"},
                                           opaque=code_reach.TRANSPORT + code_reach.SIZING))
    d, leaf = sol["dir"], sol["leaf"]
    key = hashlib.sha256(json.dumps([_SOLVED_CODE[0], os.stat(d / f"leaf_{leaf:04d}.jpg").st_size, leaf,
                                     list(sol["box"]), bool(above), list(grid)]
                                    + ([True] if lean else [])
                                    + ([sorted([n, d, e] for (n, d), e in enums.items())] if enums is not None else [])
                                    ).encode()).hexdigest()[:20]
    path = CROPS / "solution_reads" / f"{d.name}_{sol['number']}.json"
    if path.exists():
        kept = json.loads(path.read_text())
        if kept.get("key") == key:
            return kept["answers"], kept["stats"]
    answers, stats = read_solution(page(d, leaf), sol, grid, above=above, lean=lean, enums=enums)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.part")
    tmp.write_text(json.dumps({"key": key, "answers": answers, "stats": stats}))
    tmp.replace(path)
    return answers, stats


_SOLVED_CODE = []


def input_hash(d):
    """The edition's files by name and size (media_manifest.edition_files).
    On the media disk, off the edition manifests, which the fetcher and
    gale_inbox append to as they write an edition, so a replan stats no
    edition; one with no hash there is taken off the disk once and appended
    (_edition_off_disk)."""
    k = os.fspath(d)
    erel = _INPUT_RELS.get(k)
    if erel is None:
        # Path arithmetic alone, the same for a given path: kept (a plan asks ~25k).
        erel = media_manifest.edition_rel(d) if media_manifest.on_media(d) else False
        if os.path.isabs(k):  # a relative one hangs on the cwd
            _INPUT_RELS[k] = erel
    if erel is False:
        return _input_hash_listed(d)
    return _held_hash(d, erel)


#: {edition dir as text: its media_manifest.edition_rel, or False off the media disk} of input_hash.
_INPUT_RELS = {}


def _held_hash(d, erel):
    """input_hash of edition dir `d` on the media disk, its manifest key `erel`."""
    held = media_manifest.edition_rows().get(erel) or {}
    if "files" not in held:
        held = _edition_off_disk(d, held)
    return held["files"]


def _edition_off_disk(d, held):
    """input_hash's and staged_at's facts of edition dir `d` on the media
    disk that its manifest row `held` lacks, taken off the disk and appended
    to archiveorg-editions (its "at" kept: when it was laid out)."""
    at = held.get("at")
    if at is None:
        at = (Path(d) / "pages.json").stat().st_mtime
    new = {"files": held.get("files") or media_manifest.edition_files(d), "at": at}
    media_manifest.record(media_manifest.ARCHIVE_EDITIONS, d, edition=media_manifest.edition_rel(d), **new)
    return new


def _input_hash_listed(d):
    """input_hash of an edition off the media disk (a test's), listed once
    while its dir_key is unmoved."""
    _, names, memo = dir_cache.seen(d)
    if "inputs" not in memo:
        if "sizes" not in memo:
            memo["sizes"] = tuple(os.stat(d / n).st_size for n in names)
        h = hashlib.sha256()
        for n, size in zip(names, memo["sizes"], strict=True):
            h.update(f"{n}:{size}".encode())
        memo["inputs"] = h.hexdigest()[:16]
    return memo["inputs"]


def held_numbers(series=SERIES):
    if getattr(_HELD_NOW, "files", None) is not None:  # held_once: held_files lists the series once
        return {n for n, _ in held_files(series)}
    return {int(p.stem.split("-")[1]) for p in (ROOT / "puzzles" / series).glob("*/*.json")}


def destination(puzzles, complete=True):
    """Where a puzzle files: None for the corpus, the `puzzles` dir, or False
    for nowhere. Only a `complete` puzzle (every clue has text) goes to the
    corpus, whatever the paper or year: a solver cannot work one with a blank
    clue, so that one goes to `puzzles` (--out) when given, else nowhere."""
    if complete:
        return None
    return puzzles or False


def complete(puzzle, unclued=()):
    """Whether every clue of a puzzle has text, none with a word OCR made
    up (ocr_clues.suspect; a token its `asPrinted` keeps is the print's) or
    unfit to file (faults). An entry `unclued` names ("25-down") is one the
    page prints with no clue: its `{"missing": true}` is the print's."""
    blank = sum(1 for e in puzzle["entries"]
                if f"{e.get('number')}-{e.get('direction')}" in unclued and e.get("clue") == {"missing": True})
    return filled(puzzle)[0] + blank == len(puzzle["entries"]) and not any(
        suspect((e.get("clue") or {}).get("text", ""), printed=(e.get("clue") or {}).get("asPrinted") or ())
        for e in puzzle["entries"]) and not faults(puzzle)


def unfit_blanked(laid, blank, lengths, printed=None):
    """(laid, blank) with each clue complete() would refuse filed blank and
    why in `blank`, so a puzzle with an empty `blank` is complete: a clue
    ocr_clues.fault refuses (its count kept when it fills the light), one
    with a word ocr_clues.suspect flags, and each light of `lengths` with
    no text that is no linked clue's tail ("See 1"). `printed` ({light:
    tokens}) holds what each clue's `asPrinted` will keep."""
    printed = printed or {}
    laid, blank = dict(laid), dict(blank)
    tails = {t for _, _, group in laid.values() for t in (group or [])[1:]}
    for lid in lengths:
        if lid not in tails and not (laid.get(lid) or ("",))[0].strip():
            laid[lid] = laid.get(lid) or ("", None, None)
            blank.setdefault(lid, "no reading laid a clue on it")
    for lid, (text, enum, group) in list(laid.items()):
        cells = sum(lengths.get(i, 0) for i in group or [lid])
        why = ocr_clues.unfit(text, enum, cells, printed.get(lid, ()))
        if (cut := ocr_clues.footer_laid(text, cells)) and not ocr_clues.unfit(cut[0], cut[1], cells, printed.get(lid, ())):
            # The solution-box footer the vote laid with the last clue, cut at its count: no
            # blank, so no pick is asked of the VLM for it. Cut too when unfit() passes the
            # text ("being sticky (5) 22,926 Solutic", no count laid: Gale 2005-03-17's 28
            # across, filed with the footer until the VLM's column read it clean).
            laid[lid] = (cut[0], cut[1], group)
            continue
        if why:
            laid[lid] = ("", None if why.startswith("its count") else enum, group)
            blank[lid] = why
    return laid, blank


def faults(puzzle):
    """{entry id: why} of each clue of a filed puzzle ocr_clues.fault refuses."""
    def lid(e):
        return f"{e.get('number')}-{e.get('direction')}"
    length = {lid(e): e.get("length") for e in puzzle["entries"]}
    out = {}
    for e in puzzle["entries"]:
        clue = e.get("clue") or {}
        cells = sum(length.get(i) or 0 for i in e.get("group") or [lid(e)])
        why = ocr_clues.fault(clue.get("text"), clue.get("enumeration"), cells, clue.get("asPrinted") or ())
        if why:
            out[lid(e)] = why
    return out


def check_filed(out=sys.stdout):
    """List every puzzle this tool filed whose clues faults() refuses, by
    class; returns the count of failing puzzles."""
    from fetch_puzzle import read_puzzle_file
    bad, classes = 0, {}
    for path in sorted((ROOT / "puzzles").glob("*/*/*.json")):
        try:
            puzzle = read_puzzle_file(path)
        except (OSError, ValueError):
            continue
        if (puzzle.get("source") or {}).get("acquiredBy") != TOOL:
            continue
        found = faults(puzzle)
        if not found:
            continue
        bad += 1
        for lid, why in found.items():
            kind = why.split(":")[0].split(" (")[0]
            classes.setdefault(kind, set()).add(puzzle["id"])
            print(f"{puzzle['id']} {lid}: {why}", file=out)
    for kind, ids in sorted(classes.items()):
        print(f"{len(ids)} puzzles: {kind}", file=out)
    print(f"{bad} puzzles filed by {TOOL} fail the clue check", file=out)
    return bad


def progress(line):
    """One line per source as it is read, to stderr, so a long run's log moves."""
    print(f"{time.strftime('%H:%M:%S')} {line}", file=sys.stderr, flush=True)


def ledger_of(cache=CACHE, paper=None, ledger=None):
    """The ledger a run of `paper` keeps under `cache` (LEDGER_NAMES), or `ledger`."""
    return Path(ledger or cache / LEDGER_NAMES.get((paper or TIMES).key, "filed.jsonl"))


def _known_row(row):
    if "hash" in row and "inputs" not in row:
        # A row keyed by code and files together: its read stands
        # for the files it was read with.
        row.pop("hash")
        row["inputs"] = row.get("filesHash")
    return row


def load_known(ledger):
    """{edition: row} of a ledger, the last row of each standing."""
    return {k: _known_row(row) for k, row in scan_queue.ledger_rows(ledger, "edition").items()}


def _fold_known(known, line):
    for row in scan_queue.parse_line(line):
        if "edition" in row:
            known[row["edition"]] = _known_row(row)


def _planned_known(ledger):
    """load_known(ledger) for plan(), which reads its rows and changes none:
    only the lines appended since the last call are parsed (dir_cache.appended,
    whose dict is this thread's own: the planner thread and the queue's main
    thread, via sister_solutions, both read it)."""
    return dir_cache.appended(ledger, dict, _fold_known)


def _fold_standing(known, line):
    _fold_known(known, line)


def standing(paper, cache=CACHE):
    """{edition: ledger row} of `paper`'s ledger now, for scan_stands."""
    return _standing(ledger_of(cache, paper))


def _standing(ledger):
    """standing() of `ledger`: the queue's main thread's fold of it, shared
    by scan_stands and brief(), which read its rows and change none."""
    return dir_cache.appended(ledger, dict, _fold_standing)


def scan_stands(paper, rel, cache=CACHE, rows=None, keys=None, host=False):
    """Whether edition `rel`'s ledger row holds a current scan (scan_current)
    now: the queue asks before it starts a scan unit from a plan made
    earlier. Its own fold of the ledger (dir_cache.appended, only lines
    appended since parsed), apart from plan()'s on the planner thread;
    `rows`, a standing() taken earlier, saves the ledger's re-read; `keys`
    ({paper name: current_keys(paper)}, the caller's, for a pass) saves
    asking for them. The row's cheap facts (a scan, a current key) are
    tested before the files' hash: most queued scans have neither."""
    row = (standing(paper, cache) if rows is None else rows).get(rel)
    if host and host_rescan_due(paper, row):
        return False  # a HOST_RESCAN (or HOST_SCAN) host's solutions-only read is due once more
    if host and row and "solOnly" in row and only_current(row, paper, _stand_hash(cache, rel)):
        return True  # a HOST_SCAN unit's solutions-only read is done; the edition's own scan is not asked
    if not row or "scan" not in row:
        return False
    p = _CURRENT_PAPER.get(rel)
    if p is None:
        p = _CURRENT_PAPER[rel] = paper_of(rel)
    cur = keys.get(p.key) if keys is not None else None
    if cur is None:
        cur = current_keys(p)
        if keys is not None:
            keys[p.key] = cur
    return row.get("scanKey") in cur and not prize_rescan(p, row.get("scanKey"), rel) \
        and row.get("filesHash") == _stand_hash(cache, rel)


#: {(cache, rel): (its edition dir, on_media of it, edition_rel of it)} for
#: _stand_hash: path arithmetic alone, the same for a given absolute cache.
#: The queue asks scan_stands of every queued scan each pass, and building the
#: Path and its abspath and normpath anew each time was most of the cost.
_STAND_DIRS = {}


def _stand_hash(cache, rel):
    """input_hash(Path(cache) / rel), the dir's path facts kept (_STAND_DIRS)
    when `cache` is absolute (a relative one hangs on the cwd)."""
    k = (os.fspath(cache), rel)
    hit = _STAND_DIRS.get(k)
    if hit is None:
        d = Path(cache) / rel
        if not os.path.isabs(k[0]):
            return input_hash(d)
        media = media_manifest.on_media(d)
        hit = _STAND_DIRS[k] = (d, media, media_manifest.edition_rel(d) if media else None)
    d, media, erel = hit
    return _held_hash(d, erel) if media else _input_hash_listed(d)


def sister_solutions(cache, paper):
    """{number: solution heading, its "dir" set} from the last scans in the
    ledgers of `paper`'s series' other FILERS, scanning nothing: the solution
    to a Times puzzle archive.org holds prints in the next issue, which may be
    a Gale page alone, and the reverse. A run's own headings come first;
    each links as linked_solutions() reads it."""
    out, held = {}, held_dates(paper.series)
    for p in FILERS.values():
        path = ledger_of(cache, p)
        if p is paper or p.series != paper.series or not path.exists():
            continue
        st = path.stat()
        stamp = (st.st_mtime_ns, st.st_size)
        hit = _SISTER_LINKS.get(path)
        if hit is None or hit[0] != stamp or hit[1] is not held:
            # Each row links through _linked's memo: a sister ledger moves
            # with every row a unit appends, and held with every puzzle
            # filed, and only the rows those touch are linked again.
            links = []
            memo = _SISTER_ROWS.setdefault(path, {})
            own = run_papers(p)
            for rel, row in _planned_known(path).items():
                m = memo.get(rel)
                if m is None or m[0] is not row or m[1] is not held:
                    d = _sister_dir(cache, rel)
                    # Only the sister's own papers' rows: filed.jsonl is every PAPERS run's ledger
                    # (the Guardian's, the FT's, the Telegraph's too), and their solution headings
                    # linked as the Times's filed another paper's grid under the same number (10-25:
                    # times-6003 took 7 answers off the FT's 1986-04-23 "solution No 6003",
                    # times-20624 3 off the Guardian's 1996-04-12; ~120 Times verdicts so linked).
                    m = memo[rel] = (row, held, [] if paper_of(d) not in own else
                                     [(s["number"], {**s, "dir": d})
                                      for s in _linked(d, scan_of(row, p) or _NO_SCAN, held, p)])
                links += m[2]
            hit = _SISTER_LINKS[path] = (stamp, held, links)
        for n, s in hit[2]:
            out.setdefault(n, s)
    return out


#: {sister ledger: ((mtime_ns, size), held_dates, [(number, linked heading)])}
#: of sister_solutions: worked out again only when the ledger or the
#: series' filed puzzles move.
_SISTER_LINKS = {}
#: {sister ledger: {edition: (its row, held, its [(number, heading)])}}: a
#: ledger that moved relinks only the rows (the planner's fold keeps the
#: identity of one no line touched) or the held that did.
_SISTER_ROWS = {}
#: An edition row without a scan, as sister_solutions links it.
_NO_SCAN = {"puzzles": [], "solutions": []}


def _sister_dir(cache, rel):
    """Path(cache) / rel, kept: sister_solutions asks it of every row of a
    sister ledger each time that ledger moves."""
    k = (os.fspath(cache), rel)
    d = _SISTER_DIRS.get(k)
    if d is None:
        d = _SISTER_DIRS[k] = Path(cache) / rel
    return d


#: {(cache, rel): edition dir} of _sister_dir.
_SISTER_DIRS = {}


def run(cache=CACHE, write=True, ledger=None, out=sys.stdout, puzzles=None, limit=None,
        source=SOURCE, paper=None, seconds=None, workers=1, wait=False, reread=None, editions=None, scan_new=True,
        newer=None):
    """File what is new under `cache`: complete puzzles into the corpus, ones
    with a blank clue into `puzzles` when given. At most `limit` editions are
    read, none started after `seconds`, `workers` at once (scan_queue).
    `reread` (a datetime) reads again every edition last read before it;
    `editions` ("ITEM/EDITION" names) reads those again and no other.
    Without `scan_new`, nothing is scanned and only the editions whose read
    waits on no scan are read (unsettled). `newer` (a time.time()) reads
    only the due editions laid out since then (staged_at).
    Returns the ledger rows; [] when another run holds the ledger and `wait`
    is not set."""
    deadline = None if seconds is None else time.monotonic() + seconds
    paper = paper or TIMES
    ledger = ledger_of(cache, paper, ledger)
    with scan_queue.lock(ledger, wait) as mine:
        if not mine:
            print(f"another run holds {ledger.with_suffix('.lock')}: nothing read", file=out)
            return []
        return _run(cache, write, ledger, out, puzzles, limit, source, paper, deadline, workers, reread,
                    editions, scan_new, newer)


def inputs_of(files_hash, found, series, reprints=None):
    """An edition's inputs: its files (input_hash), for a puzzle the
    Canberra Times reprinted the reprint's cached texts (reprint_key), and
    whether a puzzle of it filed by this tool holds a clue ocr_clues.stray
    flags, which a read mends or blanks (mend_held). _run keys the ledger
    by the inputs after its write, so an edition is read once for it: a
    clue the read could not mend (a reading on another grid) stays as it
    is until the edition's other inputs move."""
    numbers = [p["number"] for p in found["puzzles"]]
    if reprints is None:
        reprints = reprint_key(numbers, series)
    return edition_commit.inputs(files_hash, reprints, series, numbers)


def solution_source(sol):
    """Where a linked solution heading `sol` prints: a verdict's solutionFrom."""
    return f"{sol['dir'].name} leaf {sol['leaf']}"


def solution_sources(dirs, scans, rels, held, sister):
    """({number: the solution heading a read takes, its "dir" set}, {number:
    {solution_source} of every page linking it}): each of `dirs`' linked
    headings, the first per number standing, over the `sister` ones."""
    first, every = {}, {}
    for d in dirs:
        for s in _linked(d, scans[rels[d]], held):
            first.setdefault(s["number"], {**s, "dir": d})
            every.setdefault(s["number"], set()).add(solution_source({**s, "dir": d}))
    for n, s in sister.items():
        every.setdefault(n, set()).add(solution_source(s))
    return {**sister, **first}, every


def _linked(d, scan, held, paper=None):
    """linked_solutions of edition dir `d`'s `scan` and `held` (of `paper`,
    else paper_of(d)), linked again only when its scan differs or the filed
    puzzles in its hosted_window do: a puzzle filed anywhere makes
    held_dates a new Held, and a unit start links every edition of its
    paper. Each thread folds the ledger into rows of its own
    (dir_cache.appended), so a scan another thread linked is the same scan
    when equal, not only when the same object."""
    if paper is None:
        paper = paper_of(d)
    k = (os.fspath(d), paper)  # str: a Path key re-normalises its string on every hash
    hit = _LINKED.get(k)
    same = hit is not None and (hit[0] is scan or hit[0] == scan)
    if same and hit[1] is held:
        if hit[0] is not scan:
            _LINKED[k] = (scan, *hit[1:])
        return hit[4]
    window = hit[2] if same else hosted_window(paper, scan)
    near = held_between(held, window)
    if same and hit[3] == near:
        out = hit[4]
    else:
        out = linked_solutions(paper, scan, held)
    _LINKED[k] = (scan, held, window, near, out)
    return out


#: {(edition dir, paper): (its scan, held, hosted_window, held_between then,
#: linked_solutions of them)} of solution_sources and sister_solutions: an
#: edition's scan and held_dates' Held stay the same until they move.
_LINKED = {}


#: (first day, last day, ISO time) of the Gale Times pages (about 2006-11 to
#: 2013) whose third clue column (overhang()) was not read before that time:
#: a held row with fewer clues than lights, read before it, is read again.
REREAD_THREE_COLUMNS = ("2006-11-01", "2013-12-31", "2026-10-18T04:37:45+00:00")


#: {day: ISO time}: a Gale edition of that day whose page no scan reader parsed
#: ("no ACROSS and DOWN lists", the VLM then reading it whole) and was read
#: before that time is read again as "refused unparsed before its fix": the
#: fix reads it now (1948-11-10: trimmed_lead's 7px rule between the small ads
#: and the clue column ran the ad's line ends into the ACROSS column). One
#: day per fix proved on its page, never a blanket over the unparsed.
REREAD_UNPARSED = {"1948-11-10": "2026-10-19T18:00:00+00:00"}


def unparsed_fixed(row):
    """Whether `row` is a REREAD_UNPARSED day's edition with a puzzle every
    scan reader left unparsed, read before that fix."""
    t = REREAD_UNPARSED.get(str((row.get("scan") or {}).get("date", "")))
    return bool(t) and scan_queue.read_before(row, scan_queue.when(t)) and any(
        v.get("unparsed") and not v.get("refused") and not v.get("complete") for v in row.get("verdicts", ()))


#: The reason of a Gale Times page of 2000-2014 whose scan found no crossword title and whose scan code
#: has changed since: 208 pages of 2000 read 10-13 found none, and the current scan finds the title
#: ("THE TIMES CROSSWORD / NO 21,363" under the Sport page's grid, 2000-03-14: no change was needed).
NO_TITLE_RESCAN = "no title found before its scan fix"
#: The (first, last) years of the Gale Times whose pages read with no title found by older scan code are
#: scanned again: 2000-14, and 1957-62 (~1,260 pages scanned 10-15/16 under an older key, Gale citing "The
#: Times Crossword Puzzle" on each; 1958 and 1959 filed none of ~311; the current scan finds 1958-06-17's
#: 8,777, 1958-12-31's 8,944 and 1959-12-19's 9,246 with the day before's solution: no change was needed).
UNTITLED_YEARS = (("1957", "1962"), ("2000", "2014"))


def untitled_rescan(row):
    """Whether `row` is a Gale Times edition of UNTITLED_YEARS read with no title found (no puzzle in its
    scan, no verdict) by scan code other than the current one: scanned again, it may find one."""
    scan = row.get("scan") or {}
    year = str(scan.get("date", ""))[:4]
    if not str(scan.get("item", "")).startswith("GaleTimes") or not any(a <= year <= b for a, b in UNTITLED_YEARS) \
            or "inputs" not in row or scan.get("puzzles") or row.get("verdicts") or scan.get("failed"):
        return False
    return row.get("scanKey") != scan_key(paper_of(Path(row["edition"])))


#: The due reason of a Times page whose scan by current scan code finds no title (no puzzle; no verdict, or
#: only the held puzzle's an older scan read, 10-25),
#: while the one puzzle its series holds for the page's date was filed from this very page (an older
#: scan read its title) with every clue and not every answer: no read takes its title, so a solution
#: heading a host prints for it links nothing. Read answers-only under the held number (held_titles), no
#: VLM ask: no clue is read again. Paul 10-25: 241 Times puzzles (1945-66 ~225: 1956-09-15's 8,235 under
#: the 09-17 heading "Solution of Puzzle No 8,235") stood so of ~690 linking no solution grid.
HELD_TITLE = "untitled page, its held puzzle's answers read"
#: Once: a row read before this is due HELD_TITLE. 10-26: again, its answers judged by held_proven
#: (10-25's reads left out every uncrossed answer of a grid that gave the held answers).
REREAD_HELD_TITLE = "2026-10-26T01:00:00+00:00"
#: The due reason of a Times row a held-title read (HELD_TITLE: answers-only, no VLM ask) read before
#: REREAD_HELD_STRIPS, its held puzzle (every clue, from this page) left 1 to LATE_MAX lights blank and the
#: grid's crop kept (held_strips): read so again, its blank lights' strips asked (vlm_lights, late_strips)
#: when its grid reading proves the held puzzle's (held_proven). 10-26 03:20Z: 172 Times puzzles (1950s 108,
#: 1960s 39, 1940s 18) stood 1-5 short after their HELD_TITLE rereads with no unit planned: 158 blank lights
#: with a strip cut and never asked, ~160 with none cut; every grid proven. Once, as an answers-only reread
#: (SOLUTION_FIXES).
HELD_STRIPS = "solution short, its held title's strips asked since"
REREAD_HELD_STRIPS = "2026-10-26T04:15:00+00:00"
#: Editions (dir names) a held-title read asks the VLM for (HELD_STRIPS), set by _run like _KEEP_VLM.
_HELD_ASK = {"names": set()}


def held_strips(row, cache=None):
    """Whether Times ledger `row` is due HELD_STRIPS: a held title (held_titles, read before
    REREAD_HELD_STRIPS) of a puzzle held 1 to LATE_MAX answers short whose linked grid's crop is kept."""
    hits = held_titles(row, cache, REREAD_HELD_STRIPS)
    if not hits:
        return False
    paper = paper_of(row.get("edition", ""))
    for v in row.get("verdicts", ()):
        if not v.get("solutionFrom") or v.get("wrongGrid") or v.get("number") != hits[0]["number"]:
            continue
        try:
            held = json.loads(_HELD_PATH[(paper.series, hits[0]["number"])].read_text())
        except (KeyError, OSError, ValueError):
            continue
        blank = sum(1 for e in held.get("entries") or () if not e.get("solution"))
        if 0 < blank <= LATE_MAX and (CROPS / "solutions" / f"{v['solutionFrom'].rsplit(' leaf ', 1)[0]}_{v['number']}.png").exists():
            return True
    return False


def held_titles(row, cache=None, before=REREAD_HELD_TITLE):
    """[{"number", "leaf", "box": None, "heldTitle": True}] for Times ledger `row` (HELD_TITLE): its scan by
    current scan code holds no title and it has no verdict but one (not refused) of the held puzzle's
    number (its title the scan lost), read before `before` (REREAD_HELD_TITLE; held_strips' later), and the one
    puzzle its series holds for the scan's date is held with every clue and not every answer, by this
    tool, from a leaf of this edition (page_url); else []. The hit is the held puzzle's title as the
    page's lost one: filed_number files it only as the number the date's count gives, and answers_only
    reads it only from the held file of this page."""
    scan = row.get("scan") or {}
    # A row a held-title read wrote keeps its scan with that held title as its one title (held_titled):
    # no title of the page's own, so read again as one after REREAD_HELD_TITLE moves (10-26: held_proven).
    if "inputs" not in row or any(not p.get("heldTitle") for p in scan.get("puzzles") or ()) \
            or scan.get("failed") or not scan.get("date"):
        return []
    # A verdict the page's older scan read under the title it lost (10-25: 82 Times rows of 1949-89, one
    # verdict each, the held puzzle's, its title gone from the scan by current code) stands for that
    # title: due_reason answered "inputs changed" for them, a blanket reason, and no held title was read.
    verdicts = row.get("verdicts") or ()
    if len(verdicts) > 1 or any(v.get("refused") for v in verdicts):
        return []
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED or row.get("scanKey") not in current_keys(paper) \
            or not scan_queue.read_before(row, scan_queue.when(before)):
        return []
    try:
        day = datetime.date.fromisoformat(scan["date"])
    except ValueError:
        return []
    nums = Held.of(held_dates(paper.series)).on_day.get(day, ())
    if len(nums) != 1 or filed_state(paper.series, nums[0]) != (False, True) \
            or any(v.get("read_as", v.get("number")) != nums[0] for v in verdicts):
        return []
    d = Path(cache or CACHE) / row["edition"]
    try:
        old = json.loads(_HELD_PATH[(paper.series, nums[0])].read_text())
        pages = json.loads((d / "pages.json").read_text())
    except (KeyError, OSError, ValueError):
        return []
    src = old.get("source") or {}
    if src.get("acquiredBy") != TOOL:
        return []
    for leaf in sorted({p["leaf"] for p in pages.get("crossword_pages", ()) if isinstance(p.get("leaf"), int)}):
        if page_url(d, scan, leaf) == src.get("url"):
            return [{"number": nums[0], "leaf": leaf, "box": None, "heldTitle": True}]
    return []


def held_titled(row, cache=None, before=REREAD_HELD_TITLE):
    """`row`'s scan with its held_titles (read before `before`) as its titles, or None when it has none."""
    hits = held_titles(row, cache, before)
    return {**row["scan"], "puzzles": hits} if hits else None


THREE_COLUMNS = "short Times page, its third clue column read since"
#: The years whose short third-column pages are read first (tools/edition_queue.year_evidence): a stale one
#: was "scan stale, answers missing" (the answers-missing test came first), a blanket reason no plan keeps,
#: so 2007's 312 pages (every read once, ~10 down clues blank) were never reread (10-22).
THREE_COLUMNS_YEARS = (2006, 2007)


def third_column_first(row):
    """Whether `row` is a short Gale Times page of THREE_COLUMNS_YEARS read before the third column was."""
    scan = row.get("scan") or {}
    year = str(scan.get("date", ""))[:4]
    return year.isdigit() and THREE_COLUMNS_YEARS[0] <= int(year) <= THREE_COLUMNS_YEARS[1] \
        and short_three_columns(row) and scan_queue.read_before(row, scan_queue.when(REREAD_THREE_COLUMNS[2]))


def short_three_columns(row):
    """Whether `row` is a Gale Times edition of REREAD_THREE_COLUMNS' days with
    a puzzle held short of clues (fewer than lights, none refused)."""
    scan = row.get("scan") or {}
    first, last, _ = REREAD_THREE_COLUMNS
    return str(scan.get("item", "")).startswith("GaleTimes") and first <= str(scan.get("date", "")) <= last and any(
        not v.get("complete") and not v.get("refused") and v.get("clues", 0) < v.get("lights", 0)
        for v in row.get("verdicts", ()))


#: The reason of a Gale Times page of the 2005 to 2006-10 layout (the grid left of its title, its clues
#: right of it out to RIGHT_SPAN_LEFT) held with a blank clue, read before right_foreign() pulled the clue
#: window's far edge in to the gutter before the advert or solution box beside DOWN. Paul 10-25: 2005 filed
#: 216 of ~310 (56 held blank, none due); the window ended ~90px inside that box, its line ends ("Books Fi",
#: "Check tod") read into the DOWN clues level with them, and the last DOWN clue laid on no light (64 of
#: the 2005 blanks). Offline over the cached crops, 34 of the held 2005-06 pages' windows are cut, every
#: dropped box the neighbour's print; 74 of the filed pages' too, none of their clue text.
RIGHT_FOREIGN_READ = "short Times page, its clue window cut at its gutter since"
#: (first day, last day, ISO time): a held row of those days read before the time is read again once.
REREAD_RIGHT_FOREIGN = ("2005-01-01", "2006-10-31", "2026-10-25T07:00:00+00:00")


def right_foreign_held(row):
    """Whether `row` is a Gale Times edition of REREAD_RIGHT_FOREIGN's days, read before its time, with
    a puzzle held with a blank clue (or fewer clues than lights, none refused) that the corpus does not
    already hold with every clue (filed_state)."""
    scan = row.get("scan") or {}
    first, last, at = REREAD_RIGHT_FOREIGN
    if not str(scan.get("item", "")).startswith("GaleTimes") or not first <= str(scan.get("date", "")) <= last \
            or not scan_queue.read_before(row, scan_queue.when(at)):
        return False
    # A write refused (a book's copy: fetch_puzzle.check_not_copy) is refused again however it reads.
    return any(v.get("id") and not v.get("complete") and not v.get("refused") and not v.get("refusedWrite")
               and (v.get("blank") or v.get("clues", 0) < v.get("lights", 0))
               and not (filed_state(v["id"].rsplit("-", 1)[0], v.get("number")) or (False, False))[1]
               for v in row.get("verdicts", ()))


#: ISO time of the last fix to how a Gale page's clue columns are laid out (vlm_reader.MIN_BOX
#: 80 -> 55: the strip over the grid's two-line columns were left out of every pick's crop, 21d
#: 24d 25d asked and left blank on 1945-47 pages): an edition whose read wrote a puzzle to the
#: unfiled dir (a clue blank, destination()) before it is read again once, as "unfiled before its
#: fix". A read after it that is incomplete again is not due until a newer time is set here.
#: 10-20 18:45: ocr_clues.footer_cut also cuts a footer number torn at the crop edge ("(7) WORD 23,0"),
#: which left the last across clue of 5 of 19 Gale 2005 pages blank.
#: 10-20 21:25: unfit_blanked cuts a footer the vote laid with the last across clue at its count
#: (ocr_clues.footer_laid): 40 of 73 blanks of the unfiled Gale/FT pages read 19:05-21:05.
#: 10-21 23:42: suspect() keeps the print's own tokens ("l.-b.-w.", "tam-o'-shanter", "N—D—S",
#: "20cwt", "Ven.", "s. d."), clue_repair.mend_text spaces a run of dashes, and clue_text marks a clue
#: whose number was lost after a count wrapped onto its own line: 8 of 10 one-blank 1950s Gale pages.
#: 10-22 00:25: a misread ACROSS heading ("ACRUSS") no longer dropped from the column (its list lost a linked
#: first clue, "1, 9 ...", and the tail light no reading laid), a stop-closed line cut at the next clue's
#: number, the solution box's heading cut off the clue set in its row, a long count's spaces closed: 7 of 8
#: sample 1950s Gale one-blank pages (no blank clue left), 4 of 4 filed pages unchanged.
REREAD_UNFILED = "2026-10-22T00:25:00+00:00"

#: The reason, and its fix's time, of a 2000-14 Times page (Gale or News UK) whose read wrote its
#: puzzle unfiled (unfiled_blank) before the 10-25 reader fixes: clue_text.clue_number_opening
#: opens a clue numbered 11 that RapidOCR read as "ll1", "ll", "1l", "IIl", "II" or "!!" (11 across
#: blank "starts mid-clue" or "readings differ: Il / II / I" on ~10 pages of 2000-13), and
#: crop_window.cut_edge widens a right-hand clue window that cut its own down column (mid-2014:
#: "shaking out t", one clue blank as a stray letter). Paul 10-25: 87 such pages stood unfiled and
#: undue (2004 15, 2005 14, 2006 11, 2007 11, 2014 8; read 10-20..24, after REREAD_UNFILED; 20 of
#: them 2005-06 pages already due as a short page). An OCR-only read by current code (no VLM) left
#: no blank on 3 of 15 random such pages and 8 of 14 picked by cause (2004's "no reading laid a clue
#: on it" pages among them, mended by code since their read); the rest keep one or two blanks a
#: window misses (11 down, 24 down) or a vote refuses. Once each.
UNFILED_MODERN = "unfiled before its fix, Times 2000-14"
REREAD_UNFILED_MODERN = "2026-10-25T07:50:00+00:00"
UNFILED_MODERN_YEARS = ("2000", "2014")


def unfiled_modern(row):
    """Whether ledger `row` is a 2000-14 Times page (UNFILED_MODERN_YEARS) read before
    REREAD_UNFILED_MODERN whose read left a puzzle unfiled: a verdict with an "unfiled"
    count, or its id's copy in CROPS/unfiled, not refused, its puzzle not held with every
    clue (filed_state). Not unfiled_blank's test: 29 of the 87 such pages (10-25) were read
    "complete" (the list parsed whole, a clue then blank) or carry "unfiled" with no "wrote"."""
    rel = row.get("edition") or ""
    if paper_of(Path(rel)).key not in ("gale", "times"):
        return False
    year = Path(rel).name[:4]
    if not (UNFILED_MODERN_YEARS[0] <= year <= UNFILED_MODERN_YEARS[1]) \
            or not scan_queue.read_before(row, scan_queue.when(REREAD_UNFILED_MODERN)):
        return False
    for v in row.get("verdicts", ()):
        if v.get("refused") or v.get("skip") or not v.get("id"):
            continue
        if not v.get("unfiled") and not (CROPS / "unfiled" / f"{v['id']}.json").exists():
            continue
        if not (filed_state(v["id"].rsplit("-", 1)[0], v.get("number")) or (False, False))[1]:
            return True
    return False


def unfiled_blank(row):
    """[(puzzle id, blank clues)] of the puzzles of ledger `row` its read wrote
    unfiled (not complete, written, its file in CROPS/unfiled), else []. The count is
    the verdict's "unfiled", else its named blanks, else lights short of clues.
    A puzzle the corpus already holds with every clue (filed_state: another edition's
    read, or an earlier one) is left out: Paul 10-24, of the ~1,600 Times pages held for
    this reason ~1,470 were such, and their rereads only rewrote a filed file (10-21:
    ~350 writes an hour, 5 new filings; 10-22..24: 113 of 114 1990s writes)."""
    out = []
    for v in row.get("verdicts", ()):
        if v.get("complete") or v.get("refused") or not v.get("wrote") or v.get("skip") or v.get("mended") or not v.get("id"):
            continue
        if v.get("unfiled") is None and not (CROPS / "unfiled" / f"{v['id']}.json").exists():
            continue
        if (filed_state(v["id"].rsplit("-", 1)[0], v.get("number")) or (False, False))[1]:
            continue
        k = v.get("unfiled")
        if k is None:
            k = len(v["blank"]) if isinstance(v.get("blank"), dict) and v["blank"] else max(v.get("lights", 0) - v.get("clues", 0), 0)
        out.append((v["id"], k))
    return out


#: The reason of an edition whose ledger row says its read wrote a puzzle to the corpus that the corpus
#: no longer holds: no file of that number, none renamed from its id, no copy in CROPS/unfiled. Paul
#: 10-25: 2,286 Times puzzles stood so (1945-56 ~50 a year, 1970-73 ~110, 2007-08 ~145), all read
#: 10-06..10-17, so due_reason saw them read and nothing re-read them: the biggest unfiled cause of
#: the Times years under 300. ~2,210 of them had a blank clue, so decide() wrote them to --out
#: (CROPS/unfiled) as it should, on the host the queue ran on until 10-17 16:09 MDT, whose cache did
#: not move with it; the ledger marked no --out write "unfiled" until 10-19. None read since is
#: missing from origin/master. Read again once (REREAD_LOST) with the current reader: a whole read
#: files to the corpus, one still blank goes to --out as "unfiled" (unfiled_blank's from then on).
LOST_WRITE = "written, its file gone"
#: ISO time before which a read whose write is gone (lost_writes) is read again once. A read after it
#: that loses its file again is not due until a newer time is set here.
REREAD_LOST = "2026-10-25T04:45:00+00:00"


@functools.lru_cache(maxsize=1)
def _renamed_ids():
    """{old id: new id} of tools/data/renamed_ids.json ({} when unreadable)."""
    try:
        return json.loads((ROOT / "tools" / "data" / "renamed_ids.json").read_text())
    except (OSError, ValueError):
        return {}


_SPAN = {}


def _held_span(series):
    """(lowest, highest) number the series' listing (_held_list) holds, None when it holds none."""
    version, held = _held_list(series)
    hit = _SPAN.get(series)
    if hit is None or hit[0] != (version, len(held)):
        nums = [n for n, _ in held]
        hit = _SPAN[series] = ((version, len(held)), (min(nums), max(nums)) if nums else None)
    return hit[1]


_DAYS = {}


def _held_days(series):
    """The dates ("YYYY-MM-DD") of the puzzles the series' listing (_held_list) holds."""
    version, held = _held_list(series)
    hit = _DAYS.get(series)
    if hit is None or hit[0] != (version, len(held)):
        hit = _DAYS[series] = ((version, len(held)), frozenset(e[2] for _, e in held if e and e[2]))
    return hit[1]


def _row_day(row):
    """The date ("YYYY-MM-DD") of ledger `row`'s edition: its dir name's, else its scan's; None."""
    m = re.search(r"\d{4}-\d{2}-\d{2}", row.get("edition") or "")
    return m.group() if m else ((row.get("scan") or {}).get("date") or "")[:10] or None


def lost_writes(row):
    """[puzzle id] of the puzzles ledger `row`'s read wrote to the corpus that it no
    longer holds (LOST_WRITE): a written verdict (not refused, skipped, mended or
    answers-only, so its write was the reading itself) whose number lies between
    the lowest and highest the series' listing holds (_held_span: a gap in it; a
    series with no listing, or a number past its ends, is never told gone) and
    has no file, not renamed since (renamed_ids.json), and not written unfiled
    (its "unfiled" count or a CROPS/unfiled copy: unfiled_blank's), while the
    series holds no puzzle of the edition's date: one that does was filed under
    another number since (10-24's renumber, tools/repair_fetched.py --renumbered,
    leaves no renamed_ids.json row: times-22158 is times-22159 now), and a
    re-read would file the page's puzzle twice."""
    out = []
    day = _row_day(row)
    for v in row.get("verdicts", ()):
        if (v.get("refused") or not v.get("wrote") or v.get("skip") or v.get("mended") or v.get("answersOnly")
                or not v.get("id") or v.get("unfiled") is not None or "number" not in v):
            continue
        series = v["id"].rsplit("-", 1)[0]
        span = _held_span(series)
        if span is None or not span[0] < v["number"] < span[1]:
            continue  # no listing of that series, or a number past its ends: nothing can be told gone
        if filed_state(series, v["number"]) is not None or v["id"] in _renamed_ids():
            continue
        if (CROPS / "unfiled" / f"{v['id']}.json").exists():
            continue
        if day and day in _held_days(series):
            continue  # the edition's puzzle is filed, under another number
        out.append(v["id"])
    return out


#: ISO time of answers_only's no longer refusing a held file with a clue filed without its enumeration:
#: a Times edition whose solution grid is linked, read before it, whose held puzzle is still short of
#: answers and has such a clue is read again once ("answers held back by a clue with no enumeration").
REREAD_UNENUMERATED = "2026-10-22T16:30:00+00:00"
#: {puzzle file: (its stat, whether it has a clue with no enumeration and a light with no answer)}.
_UNENUMERATED = {}


def unenumerated_held(row):
    """Whether Times ledger `row`, read before REREAD_UNENUMERATED, linked a solution grid for a
    puzzle whose held file lacks an answer and has a clue with no enumeration (not a "See 9" tail)."""
    if not scan_queue.read_before(row, scan_queue.when(REREAD_UNENUMERATED)):
        return False
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED:
        return False
    for v in row.get("verdicts", ()):
        if not v.get("solutionFrom") or v.get("answersOnly") or v.get("refused") or not v.get("id"):
            continue
        p = _HELD_PATH.get((paper.series, v.get("number")))
        if p is None:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        stamp = (st.st_mtime_ns, st.st_size)
        hit = _UNENUMERATED.get(p)
        if hit is None or hit[0] != stamp:
            es = json.loads(p.read_text()).get("entries") or ()
            bare = any(not (e.get("clue") or {}).get("enumeration")
                       and not re.fullmatch(r"See \d+.*", ((e.get("clue") or {}).get("text") or "").strip()) for e in es)
            hit = _UNENUMERATED[p] = (stamp, bare and not all(e.get("solution") for e in es))
        if hit[1]:
            return True
    return False


#: The due reason of a Times edition whose linked solution grid this solution code (solution_key) read
#: but for 1 to STRIP_MAX lights, its held puzzle every clue and not every answer: the full read's
#: solved() had no enumerations, so neither fitted_reads nor the VLM's strips ran for the last lights.
#: answers_only reads them (SOLUTION_FIXES), once: rows read before REREAD_SHORT_FITTED.
#: Paul 10-23: ~1,936 Times puzzles stood so, none due.
SHORT_UNFITTED = "solution short, not read fitted"
REREAD_SHORT_FITTED = "2026-10-24T04:30:00+00:00"


def short_unfitted(row):
    """Whether Times ledger `row`, read before REREAD_SHORT_FITTED by this solution code, linked a
    solution grid it read but for 1 to trove_solution_ocr.STRIP_MAX lights, not by answers_only, for
    a puzzle filed with every clue and not every answer (filed_state)."""
    if row.get("solutionKey") != solution_key() or not scan_queue.read_before(row, scan_queue.when(REREAD_SHORT_FITTED)):
        return False
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED:
        return False
    for v in row.get("verdicts", ()):
        s = v.get("solution")
        if (not v.get("solutionFrom") or v.get("answersOnly") or v.get("refused") or not v.get("id")
                or not isinstance(s, dict) or s.get("refused")):
            continue
        if 0 < s.get("lights", 0) - s.get("accepted", 0) <= trove_solution_ocr.STRIP_MAX \
                and filed_state(paper.series, v.get("number")) == (False, True):
            return True
    return False


#: The due reason of a Times edition whose full read read a linked solution grid whole (answers_whole)
#: for a puzzle held with every clue and no answer at all: the reading was not complete (a clue it
#: left blank or unsettled, the held file's standing), so decide() kept the held file and its answers
#: were never merged; and held_short took the whole grid read for answers filed, so no fix was due.
#: answers_only reads the grid alone (SOLUTION_FIXES: CPU, no VLM ask) and merges them, once: rows
#: read before REREAD_UNMERGED. Paul 10-24: 220 Times puzzles (1940s-2010s) stood so, none due.
UNMERGED = "solution read whole, its answers never filed"
REREAD_UNMERGED = "2026-10-24T21:00:00+00:00"


def held_unanswered(series, number, url=None):
    """Whether `series`' puzzle `number` is held with every clue and not one answer (filed_state, then
    its file read again for the answers it holds); with `url`, filed from that page (answers_only
    reads only a puzzle held from the page it reads: another's falls to the full read)."""
    if filed_state(series, number) != (False, True):
        return False
    try:
        held = json.loads(_HELD_PATH[(series, number)].read_text())
    except (KeyError, OSError, ValueError):
        return False
    es = held.get("entries") or ()
    if url is not None and (held.get("source") or {}).get("url") != url:
        return False
    return bool(es) and not any(e.get("solution") for e in es)


def unmerged(row, v):
    """Whether verdict `v` of Times ledger `row`, read before REREAD_UNMERGED, read a linked solution
    grid whole by a full read (not answers_only) for a puzzle held with every clue and no answer
    (held_unanswered)."""
    if not v.get("id") or v.get("refused") or v.get("pending") or v.get("answersOnly") or not answers_whole(v):
        return False
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED or not scan_queue.read_before(row, scan_queue.when(REREAD_UNMERGED)) \
            or not held_unanswered(paper.series, v.get("number")):
        return False
    try:
        url = page_url(CACHE / row["edition"], row["scan"], v["leaf"])
    except (KeyError, OSError, ValueError):
        return True  # no pages.json to tell (a test's row): answers_only judges
    return held_unanswered(paper.series, v.get("number"), url)


def unmerged_whole(row):
    """Whether Times ledger `row` has a verdict whose answers never merged (unmerged)."""
    return any(unmerged(row, v) for v in row.get("verdicts", ()))


#: The due reasons of a Times edition whose linked solution grid was read short (blocks read at
#: SURE_BLOCKS, so the classifier read its cells) for a puzzle held with every clue and not every
#: answer, from this page, read before REREAD_UNLISTED: since then answers_only also takes a light
#: no word list holds (trove_solution_ocr.unlisted_reads: a name or a phrase run together, every
#: cell the classifier's and every checked one an accepted crossing's). UNLISTED for a grid 1 to
#: STRIP_MAX lights short (Paul 10-24: ~1,570 Times puzzles stood so after their answers-only reread,
#: ARCOT, INVERESK, ST SWITHINS DAY among the lights left); SHORT_WIDE for one more lights short,
#: by this code or (more than SHORT_GAP short, which short_cause predicts nothing for) by older
#: solution code: read again once, after the UNLISTED ones (no likely gain: files_likely_tier 1).
UNLISTED = "solution short, read again for unlisted words"
SHORT_WIDE = "solution short of 3+ lights, read again"
REREAD_UNLISTED = "2026-10-24T23:00:00+00:00"
#: The due reason of such a grid read since REREAD_UNLISTED, 1 to STRIP_MAX lights short, before
#: REREAD_VLM_UNLISTED: since then the VLM's word for a strip (vlm_lights) stands when no list holds
#: it but the classifier reads every letter of it too (unlisted_word). 10-25: of 252 Times answer
#: rereads in 3 h that filed nothing, 135 strips had such a word thrown away (1940s-50s names:
#: PERSHORE, TAKORADI, HARPAGON). Once; the VLM's replies are cached, so the reread asks nothing new.
VLM_UNLISTED = "solution short, its VLM word unlisted"
REREAD_VLM_UNLISTED = "2026-10-25T12:15:00+00:00"
#: The due reason of such a grid read since REREAD_VLM_UNLISTED, before REREAD_VLM_FLOOR, 1 to STRIP_MAX
#: lights short, whose reading (solved()'s CROPS/solution_reads copy) kept a strip of a light the held file
#: leaves blank: since then the VLM's word for it stands one cell under VLM_FLOOR when the classifier
#: decodes it too (floor_word). 10-25: 650 Times puzzles stood 1-2 short so, none due. Once; the VLM's
#: replies are cached, so the reread asks only strips never answered.
VLM_FLOOR_SHORT = "solution short, its VLM word one cell under the floor"
REREAD_VLM_FLOOR = "2026-10-25T19:45:00+00:00"
#: {(held path, reading path): ((held stamp, reading stamp), whether a strip's light is blank in the held file)}
_FLOOR_STRIPS = {}


def strip_blank(series, number, sol_dir):
    """Whether `series`' puzzle `number`, held by this tool with every clue filled and an answer short,
    leaves blank a light whose strip its linked solution grid's reading (the solution page's edition
    dir name `sol_dir`) kept; parsed again only when either stat moves."""
    p = _HELD_PATH.get((series, number))
    if p is None:
        return False
    q = CROPS / "solution_reads" / f"{sol_dir}_{number}.json"
    stamp = (_stat_stamp(p), _stat_stamp(q))
    if None in stamp:
        return False
    hit = _FLOOR_STRIPS.get((p, q))
    if hit is None or hit[0] != stamp:
        try:
            held, read = json.loads(p.read_text()), json.loads(q.read_text())
        except (OSError, ValueError):
            return False
        es = held.get("entries") or ()
        strips = ((read.get("stats") or {}).get("strips")) or {}
        blank = bool(es) and (held.get("source") or {}).get("acquiredBy") == TOOL and filled(held)[0] == len(es) \
            and any(not e.get("solution") and entry_id(e) in strips for e in es)
        hit = _FLOOR_STRIPS[p, q] = (stamp, blank)
    return hit[1]


def floor_short(row, paper):
    """Whether Times ledger `row` (of `paper`) has a verdict 1 to STRIP_MAX short (answerable_gaps)
    whose reading kept a strip of a light its held file leaves blank (strip_blank)."""
    gaps = answerable_gaps(row, paper)
    if not gaps or min(gaps) > trove_solution_ocr.STRIP_MAX:
        return False
    for v in row.get("verdicts", ()):
        if not v.get("id") or v.get("refused") or not v.get("solutionFrom") \
                or filed_state(paper.series, v.get("number")) != (False, True):
            continue
        if strip_blank(paper.series, v.get("number"), v["solutionFrom"].rsplit(" leaf ", 1)[0]):
            return True
    return False


#: The due reason of a Times row read since REREAD_VLM_UNLISTED, before REREAD_LATE_STRIPS, whose held
#: puzzle (every clue, from this page) leaves 1 to STRIP_MAX lights blank, one of them with no strip in
#: its reading (strip_missing) though the grid's cells were classified: read_framed cuts strips only when
#: its own reading is 1-2 short, and a full read (no enumerations) cuts none. Since then answers_only cuts
#: the strip off the crop after its checks (late_strips). 10-25: of 338 blank lights of 1-2-short Times
#: files with no strip, 171 were read and dropped after (misread 46, uncrossed 42, by a full read 83),
#: 131 read by a full read; none due. Once, as an answers-only reread (SOLUTION_FIXES).
LATE_STRIPS = "solution short, its last lights' strips cut since"
REREAD_LATE_STRIPS = "2026-10-25T20:00:00+00:00"
#: {(held path, reading path): ((held stamp, reading stamp), whether a blank light has no strip)}
_LATE_STRIPS = {}


#: The due reason of a Times row read since REREAD_UNLISTED, before REREAD_WIDE_STRIPS, not due
#: otherwise, whose held puzzle (every clue, from this page) leaves STRIP_MAX+1 to LATE_MAX lights
#: blank, one with no strip in its reading, the grid's cells classified and its crop kept: since then
#: late_strips asks the VLM of up to LATE_MAX such lights (before, 2). 10-25: 401 such Times puzzles
#: stood short with no ask and no unit planned. Once, as an answers-only reread (SOLUTION_FIXES).
WIDE_STRIPS = "solution short, its 3-5 last lights' strips cut since"
REREAD_WIDE_STRIPS = "2026-10-25T19:55:00+00:00"
#: The due reason of a Times row read since REREAD_VLM_UNLISTED, before REREAD_VLM_REJUDGED, due none of
#: those above, 1 to STRIP_MAX short, whose reading kept a strip of a light its held file leaves blank
#: (floor_short): since then answers_only judges the VLM's word for such a strip again on the checked
#: crossings (rejudged), and unlisted_word takes a phrase whose short or listed piece lies one letter
#: off a word (PIECE_SHORT). 10-25 22:40Z: 321 Times puzzles linked to their solution grid stood 1-2
#: short with no unit planned, every one read since the last of those stamps; 255 of their blank lights
#: had a strip and a cached VLM reply, 9 refused on a misread crossing and 12 phrases on a short piece.
#: Once, as an answers-only reread (SOLUTION_FIXES); the VLM's replies are cached, so it asks nothing new.
VLM_REJUDGED = "solution short, its VLM word judged on the checked crossings"
REREAD_VLM_REJUDGED = "2026-10-25T23:59:00+00:00"
#: The due reason of a Times row read before REREAD_CANDIDATES, due none of those above, whose held
#: puzzle (every clue, from this page) leaves more than LATE_MAX lights blank, the grid's cells
#: classified and its crop kept (many_short): since then answers_only reads such a grid by its clues'
#: enumerations (candidate_reads: trove_solution_ocr.clue_reads) and asks the VLM to pick among a
#: light's candidates where the picks could complete the puzzle or leave it CANDIDATE_SLACK short.
#: 10-25: 192 such Times puzzles (mostly 1970s-80s), 1,976 lights blank, none due. Once, as an
#: answers-only reread (SOLUTION_FIXES).
CANDIDATE_READS = "solution short, its lights read by their clues' candidates since"
REREAD_CANDIDATES = "2026-10-26T04:30:00+00:00"
#: The due reason of a Times row read before REREAD_CLUE_SHORT, due none of those above, whose held
#: puzzle (every clue, from this page) leaves 1 to CANDIDATE_SLACK lights blank, the grid's cells
#: classified and its crop kept (many_short's few): since then answers_only reads such a light by its
#: clue's candidates (candidate_reads: trove_solution_ocr.clue_reads, and the VLM's pick that its plain
#: strip read spells), and takes an unlisted VLM word the classifier spells too, every cell its likeliest
#: letter (agreed_word). 10-26: 666 Times puzzles (1980s 320, 1990s 162) stood 1-2 short with no unit
#: planned. Once, as an answers-only reread (SOLUTION_FIXES).
CLUE_SHORT = "solution short, its last lights read by their clues' candidates since"
REREAD_CLUE_SHORT = "2026-10-26T06:00:00+00:00"
#: The due reason of a Times row read before REREAD_CLASH_SHORT, due none of those above (CLUE_SHORT's
#: rows read before REREAD_CLUE_SHORT take both fixes in one reread), whose held puzzle leaves 1 to
#: CANDIDATE_SLACK lights blank as many_short's few: since then answers_only takes such a light's VLM
#: strip read against held crossings that read again with its letters as listed words, the clue read
#: giving it too (clash_reads, held_recrossed). 10-26: of 666 Times puzzles 1-2 short with no unit
#: planned, 131 blank lights had a VLM read against a held crossing; 21 stand so, 24 held answers re-read
#: (TOTA for IOTA, PLAT for FLAT, UTTER for OTTER), each right by its clue. Once, answers-only.
CLASH_SHORT = "solution short, its last lights' VLM reads against held crossings settled since"
REREAD_CLASH_SHORT = "2026-10-26T07:00:00+00:00"
#: The due reason of a Times row read before REREAD_CLUE_WIDE, due none of those above, whose held puzzle
#: (every clue, from this page) leaves CANDIDATE_SLACK+1 to LATE_MAX lights blank as many_short's wide:
#: candidate_reads has read such a grid's last lights by their clues' candidates only since CLUE_SHORT's
#: code (10-26 04:49Z), and neither CANDIDATE_READS (6+) nor CLUE_SHORT (1-2) made one due; since this
#: stamp it asks the VLM's picks (and clash_reads its strips) once the clue read leaves CANDIDATE_SLACK
#: lights open. 10-26 05:40Z: 260 Times puzzles stood 3-5 short, grid linked, with no unit planned
#: (1980s 117, 1940s 67), 240 read before 04:49Z. Once, as an answers-only reread (SOLUTION_FIXES).
CLUE_WIDE = "solution short, its 3-5 last lights read by their clues' candidates since"
REREAD_CLUE_WIDE = "2026-10-26T08:00:00+00:00"
#: {(held path, reading path): ((held stamp, reading stamp), held_blanks' answer)}
_MANY_SHORT = {}


def held_blanks(series, number, sol_dir):
    """The answers `series`' puzzle `number`, held by this tool with every clue filled, leaves blank, its
    linked solution grid's reading (the solution page's edition dir name `sol_dir`) having classified its
    cells and the grid's crop kept; 0 for any other. Parsed again only when either stat moves."""
    p = _HELD_PATH.get((series, number))
    if p is None:
        return 0
    q = CROPS / "solution_reads" / f"{sol_dir}_{number}.json"
    stamp = (_stat_stamp(p), _stat_stamp(q))
    if None in stamp:
        return 0
    hit = _MANY_SHORT.get((p, q))
    if hit is None or hit[0] != stamp:
        try:
            held, read = json.loads(p.read_text()), json.loads(q.read_text())
        except (OSError, ValueError):
            return 0
        es = held.get("entries") or ()
        stats = read.get("stats") or {}
        blank = [e for e in es if not e.get("solution")]
        ok = bool(es) and (held.get("source") or {}).get("acquiredBy") == TOOL and filled(held)[0] == len(es) \
            and "classified" in stats and (CROPS / "solutions" / f"{sol_dir}_{number}.png").exists()
        hit = _MANY_SHORT[p, q] = (stamp, len(blank) if ok else 0)
    return hit[1]


def many_blank(series, number, sol_dir):
    """Whether `series`' puzzle `number`, held by this tool with every clue filled, leaves more than
    LATE_MAX answers blank, its linked solution grid's reading (the solution page's edition dir name
    `sol_dir`) classified its cells and the grid's crop is kept (held_blanks)."""
    return held_blanks(series, number, sol_dir) > LATE_MAX


def many_short(row, paper, few=False, wide=False):
    """Whether Times ledger `row` (of `paper`) has a verdict whose linked solution grid it read for a
    puzzle held with every clue from this page, more than LATE_MAX answers blank (many_blank); `few`:
    1 to CANDIDATE_SLACK blank (held_blanks); `wide`: CANDIDATE_SLACK+1 to LATE_MAX blank."""
    for v in row.get("verdicts", ()):
        s = v.get("solution")
        if (not v.get("id") or v.get("refused") or v.get("pending") or not v.get("solutionFrom")
                or not isinstance(s, dict) or s.get("refused") or v.get("wrongGrid")
                or filed_state(paper.series, v.get("number")) != (False, True)):
            continue
        try:
            held = json.loads(_HELD_PATH[(paper.series, v["number"])].read_text())
            if (held.get("source") or {}).get("url") != page_url(CACHE / row["edition"], row["scan"], v["leaf"]):
                continue
        except (KeyError, OSError, ValueError):
            pass  # no pages.json or held file to tell (a test's row): answers_only judges
        sol_dir = v["solutionFrom"].rsplit(" leaf ", 1)[0]
        if few or wide:
            lo, hi = (1, CANDIDATE_SLACK) if few else (CANDIDATE_SLACK + 1, LATE_MAX)
            if lo <= held_blanks(paper.series, v.get("number"), sol_dir) <= hi:
                return True
        elif many_blank(paper.series, v.get("number"), sol_dir):
            return True
    return False


def strip_missing(series, number, sol_dir, most=None):
    """Whether `series`' puzzle `number`, held by this tool with every clue filled and 1 to STRIP_MAX
    answers short (`most`: 1 to that many), leaves blank a light whose strip its linked solution grid's
    reading (the solution page's edition dir name `sol_dir`, its cells classified) did not keep, and
    the grid's crop is kept (late_strips cuts it there); parsed again only when either stat moves."""
    p = _HELD_PATH.get((series, number))
    if p is None:
        return False
    q = CROPS / "solution_reads" / f"{sol_dir}_{number}.json"
    stamp = (_stat_stamp(p), _stat_stamp(q))
    if None in stamp:
        return False
    most = trove_solution_ocr.STRIP_MAX if most is None else most
    hit = _LATE_STRIPS.get((p, q, most))
    if hit is None or hit[0] != stamp:
        try:
            held, read = json.loads(p.read_text()), json.loads(q.read_text())
        except (OSError, ValueError):
            return False
        es = held.get("entries") or ()
        stats = read.get("stats") or {}
        strips = stats.get("strips") or {}
        blank = [entry_id(e) for e in es if not e.get("solution")]
        missing = bool(es) and (held.get("source") or {}).get("acquiredBy") == TOOL and filled(held)[0] == len(es) \
            and "classified" in stats and 0 < len(blank) <= most \
            and any(k not in strips for k in blank) \
            and (CROPS / "solutions" / f"{sol_dir}_{number}.png").exists()
        hit = _LATE_STRIPS[p, q, most] = (stamp, missing)
    return hit[1]


def late_short(row, paper, most=None):
    """Whether Times ledger `row` (of `paper`) has a verdict whose linked solution grid it read at
    SURE_BLOCKS (by answers_only or a full read) for a puzzle held with every clue and not every answer,
    from this page, leaving blank a light with no strip (strip_missing, 1 to `most` blank)."""
    for v in row.get("verdicts", ()):
        s = v.get("solution")
        if (not v.get("id") or v.get("refused") or v.get("pending") or not v.get("solutionFrom")
                or not isinstance(s, dict) or s.get("refused") or v.get("wrongGrid")
                or filed_state(paper.series, v.get("number")) != (False, True)):
            continue
        try:
            held = json.loads(_HELD_PATH[(paper.series, v["number"])].read_text())
            if (held.get("source") or {}).get("url") != page_url(CACHE / row["edition"], row["scan"], v["leaf"]):
                continue
        except (KeyError, OSError, ValueError):
            pass  # no pages.json or held file to tell (a test's row): answers_only judges
        if strip_missing(paper.series, v.get("number"), v["solutionFrom"].rsplit(" leaf ", 1)[0], most):
            return True
    return False


def short_again(row):
    """UNLISTED or SHORT_WIDE for Times ledger `row`, read before REREAD_UNLISTED, with a verdict whose
    linked solution grid it read short at SURE_BLOCKS for a puzzle held with every clue and not every
    answer, filed from this page (answers_only reads only such a puzzle); else None. UNLISTED when any
    such verdict is at most trove_solution_ocr.STRIP_MAX short. VLM_UNLISTED for such a row read since,
    before REREAD_VLM_UNLISTED, at most STRIP_MAX short; VLM_FLOOR_SHORT for one read since, before
    REREAD_VLM_FLOOR, whose reading kept a strip of a light left blank (floor_short); LATE_STRIPS for one
    read since REREAD_VLM_UNLISTED, before REREAD_LATE_STRIPS, not due so, whose held file leaves a light
    blank with no strip (late_short); WIDE_STRIPS for one read since REREAD_UNLISTED, before
    REREAD_WIDE_STRIPS, due none of those, whose held file leaves up to LATE_MAX lights blank, one with
    no strip; VLM_REJUDGED for one read since REREAD_VLM_UNLISTED, before REREAD_VLM_REJUDGED, due none of
    those, whose reading kept a strip of a light left blank (floor_short); CANDIDATE_READS for one read
    before REREAD_CANDIDATES, due none of those, whose held file leaves more than LATE_MAX lights blank
    (many_short); CLUE_SHORT for one read before REREAD_CLUE_SHORT, due none of those, whose held file
    leaves 1 to CANDIDATE_SLACK lights blank (many_short's few); CLASH_SHORT for such a row read since,
    before REREAD_CLASH_SHORT; CLUE_WIDE for one read before REREAD_CLUE_WIDE, due none of those, whose
    held file leaves CANDIDATE_SLACK+1 to LATE_MAX lights blank (many_short's wide)."""
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED:
        return None
    why = _short_again(row, paper)
    if (why is None and scan_queue.read_before(row, scan_queue.when(REREAD_WIDE_STRIPS))
            and not scan_queue.read_before(row, scan_queue.when(REREAD_UNLISTED)) and late_short(row, paper, LATE_MAX)):
        return WIDE_STRIPS
    if (why is None and scan_queue.read_before(row, scan_queue.when(REREAD_VLM_REJUDGED))
            and not scan_queue.read_before(row, scan_queue.when(REREAD_VLM_UNLISTED)) and floor_short(row, paper)):
        return VLM_REJUDGED
    if why is None and scan_queue.read_before(row, scan_queue.when(REREAD_CANDIDATES)) and many_short(row, paper):
        return CANDIDATE_READS
    if why is None and scan_queue.read_before(row, scan_queue.when(REREAD_CLUE_SHORT)) and many_short(row, paper, few=True):
        return CLUE_SHORT
    if why is None and scan_queue.read_before(row, scan_queue.when(REREAD_CLASH_SHORT)) and many_short(row, paper, few=True):
        return CLASH_SHORT
    if why is None and scan_queue.read_before(row, scan_queue.when(REREAD_CLUE_WIDE)) and many_short(row, paper, wide=True):
        return CLUE_WIDE
    return why


def _short_again(row, paper):
    """short_again's reason for `row` (of `paper`, its cells classified) but WIDE_STRIPS."""
    if not scan_queue.read_before(row, scan_queue.when(REREAD_LATE_STRIPS)):
        return None
    if not scan_queue.read_before(row, scan_queue.when(REREAD_VLM_FLOOR)):
        return LATE_STRIPS if late_short(row, paper) else None
    if not scan_queue.read_before(row, scan_queue.when(REREAD_VLM_UNLISTED)):
        if floor_short(row, paper):
            return VLM_FLOOR_SHORT
        return LATE_STRIPS if late_short(row, paper) else None
    if not scan_queue.read_before(row, scan_queue.when(REREAD_UNLISTED)):
        gaps = answerable_gaps(row, paper)
        return VLM_UNLISTED if gaps and min(gaps) <= trove_solution_ocr.STRIP_MAX else None
    gaps = answerable_gaps(row, paper)
    if not gaps:
        return None
    return UNLISTED if min(gaps) <= trove_solution_ocr.STRIP_MAX else SHORT_WIDE


def answerable_gaps(row, paper, sure=True):
    """[lights short] of each verdict of ledger `row` (of `paper`) whose linked solution grid it read
    short (at SURE_BLOCKS, unless not `sure`) for a puzzle held with every clue and not every answer,
    filed from this page: those answers_only reads again."""
    gaps = []
    for v in row.get("verdicts", ()):
        s = v.get("solution")
        if (not v.get("id") or v.get("refused") or v.get("pending") or not v.get("solutionFrom")
                or not isinstance(s, dict) or s.get("refused")
                or sure and s.get("blocks", 0) < trove_solution_ocr.SURE_BLOCKS):
            continue
        gap = s.get("lights", 0) - s.get("accepted", 0)
        if gap <= 0 or filed_state(paper.series, v.get("number")) != (False, True):
            continue
        try:
            held = json.loads(_HELD_PATH[(paper.series, v["number"])].read_text())
            if (held.get("source") or {}).get("url") != page_url(CACHE / row["edition"], row["scan"], v["leaf"]):
                continue
        except (KeyError, OSError, ValueError):
            pass  # no pages.json or held file to tell (a test's row): answers_only judges
        gaps.append(gap)
    return gaps


#: The due reason of a Times edition whose linked solution grid was refused (its blocks not the
#: puzzle's, or its ink no grid's size) before read_solution looked for the grid by its blocks
#: (matched_box): the largest ink under a 1970s-90s heading is often the grid joined to a
#: neighbour's ink, or a part of it its broken frame left, and no box of it is the grid. The
#: solution key is pinned past that change (_SOLUTION_PINS), so answers_only reads these again
#: (SOLUTION_FIXES), once: rows read before REREAD_REFUSED_GRID. Paul 10-24: 699 Times puzzles
#: (1970s 132, 1980s 288, 1990s 135) stood refused so.
REFUSED_GRID = "solution short, its grid refused unmatched"
#: The due reason of a Times edition whose solution grid older code read short, its cells never
#: classified, for a puzzle held with every clue and not every answer from this page (answerable_gaps,
#: at any blocks), that short_again passes over (its grid read under SURE_BLOCKS). likely() predicts
#: it nothing, so it is edition_queue evidence of its own; the rest of "solution short, its cells
#: unclassified" (no such puzzle: not held, held whole or from another page; answers_only would
#: refuse each, and the full read spend VLM asks for no answer) stays unplanned. Paul 10-24: ~670
#: Times puzzles stood so (1940s-90s), none planned. Once: the reread writes this solution_key.
UNCLASSIFIED_HELD = "solution short, its cells unclassified, its puzzle held short"
REREAD_REFUSED_GRID = "2026-10-24T22:00:00+00:00"
#: The refusals matched_box may mend.
GRID_REFUSALS = ("its blocks are not the puzzle's", "the ink under the heading is ")


#: The due reason of an edition whose puzzle filed a number off its title (verdict "read_as") and
#: has since been renumbered to that title (repair_fetched --renumbered, placed's vouched titles):
#: its solution heading names the title, so the answers it read (or could not link) are read
#: again, once: rows read before REREAD_RENUMBERED. Paul 10-25: 80 Times puzzles stood one low
#: (2002-08-28..12-24 73, 2001-04 4, 1982-09 3), each host linking the puzzle after.
RENUMBERED = "renumbered to its title, answers read again"
REREAD_RENUMBERED = "2026-10-25T04:30:00+00:00"
#: The refusals a renumber may lift: the title's number held for another day, or its page held
#: under another number (placed, same_scan).
TAKEN_REFUSALS = (" is already filed for ", " is the scan page No ")
#: A write refused for its date out of order with the number before's (fetch_puzzle's DATE check):
#: Times 21704 on 2001-04-17, when 21703 stood misdated the 17th.
ORDER_REFUSED = ", not after "


def renumbered(row):
    """RENUMBERED, "refused number-date-mismatch before its fix", or None for ledger `row`
    read before REREAD_RENUMBERED: a verdict filed off its title (read_as) whose series
    now holds that title on the edition's day is RENUMBERED (its clues stand); a title
    refused as taken (TAKEN_REFUSALS) or its write refused out of date order
    (ORDER_REFUSED), or one filed a number off its title with neither number now held
    on the day, whose title its series now holds on the edition's day or not at all, is
    the refusal, read in full. A title filed further off is a misread, not a renumber."""
    if not row.get("verdicts") or not scan_queue.read_before(row, scan_queue.when(REREAD_RENUMBERED)):
        return None
    day = (row.get("scan") or {}).get("date")
    if not day:
        return None
    paper = paper_of(row.get("edition", ""))
    day = datetime.date.fromisoformat(day)
    held = None
    for v in row["verdicts"]:
        title, number = v.get("read_as", v.get("number")), v.get("number")
        taken = v.get("cause") == "number-date-mismatch" and any(t in str(v.get("refused")) for t in TAKEN_REFUSALS) \
            or ORDER_REFUSED in str(v.get("refusedWrite") or "")
        if title is None or not taken and (v.get("refused") or number is None or abs(title - number) != 1):
            continue
        held = held_dates(paper.series) if held is None else held
        if not taken and v.get("id") and held.get(title) == day:
            return RENUMBERED
        if held.get(title, day) == day and (taken or held.get(number) != day):
            return "refused number-date-mismatch before its fix"
    return None


def refused_grid(row):
    """Whether Times ledger `row`, read before REREAD_REFUSED_GRID, refused a linked solution grid
    for its blocks or its ink's size (GRID_REFUSALS), for a puzzle held without every answer."""
    if not scan_queue.read_before(row, scan_queue.when(REREAD_REFUSED_GRID)):
        return False
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED:
        return False
    for v in row.get("verdicts", ()):
        s = v.get("solution")
        if not v.get("solutionFrom") or not v.get("id") or not isinstance(s, dict) \
                or not str(s.get("refused") or "").startswith(GRID_REFUSALS):
            continue
        filed = filed_state(paper.series, v.get("number"))
        if filed is not None and not filed[0]:
            return True
    return False


#: The due reason of a Times edition whose linked solution grid read short with its blocks under
#: SURE_BLOCKS yet no further off than HEAVY_FLOOR (trove_solution_ocr.HEAVY_EXTRA light cells read
#: as blocks of a 15x15 grid), for a puzzle held with every clue and not every answer from this page:
#: since REREAD_HEAVY read_framed's classifier reads such a grid too when every block is found
#: (blocks_sure: a heavy print's inked letters, not a lattice off the grid). 10-25: of 4,466 Times
#: puzzles held 6+ lights short, 869 read at 0.90-0.97, none classified. answers_only, once.
HEAVY_PRINT = "solution short, its heavy print's cells classified since"
REREAD_HEAVY = "2026-10-25T12:40:00+00:00"
HEAVY_FLOOR = 1 - trove_solution_ocr.HEAVY_EXTRA / 225


def heavy_short(row):
    """Whether Times ledger `row`, read before REREAD_HEAVY, read a linked solution grid short at
    blocks HEAVY_FLOOR to SURE_BLOCKS for a puzzle answers_only reads (answerable_gaps)."""
    if not scan_queue.read_before(row, scan_queue.when(REREAD_HEAVY)):
        return False
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED:
        return False
    band = dict(row, verdicts=[v for v in row.get("verdicts", ()) if isinstance(v.get("solution"), dict)
                               and HEAVY_FLOOR <= v["solution"].get("blocks", 0) < trove_solution_ocr.SURE_BLOCKS])
    return bool(band["verdicts"]) and bool(answerable_gaps(band, paper, sure=False))


#: The due reason of a Times edition read before REREAD_SURE_FRAMING whose linked solution grid read
#: short with no cell classified (its best framing's blocks not blocks_sure) at blocks SOLUTION_BLOCKS
#: to SURE_BLOCKS, for a puzzle answers_only reads (answerable_gaps): since then read_framed's
#: classifier reads the best framing whose blocks are sure (trove_solution_ocr.sure_framing), not only
#: the best-fitting one, and a print whose every block is found with up to VERY_HEAVY_EXTRA inked
#: letters read as blocks. With no classifier read, uncrossed also left out every lone-letter answer
#: (times-19148: 9 of 13 read). 10-25: of the 303 Times puzzles held 6+ short with no unit planned,
#: 142 had no cell classified. answers_only, once.
SURE_FRAMING = "solution short, its cells classified on a sure framing since"
REREAD_SURE_FRAMING = "2026-10-25T20:20:00+00:00"


def unsure_short(row):
    """Whether Times ledger `row`, read before REREAD_SURE_FRAMING, read a linked solution grid short at
    blocks SOLUTION_BLOCKS to SURE_BLOCKS with no cell classified, for a puzzle answers_only reads
    (answerable_gaps)."""
    if not scan_queue.read_before(row, scan_queue.when(REREAD_SURE_FRAMING)):
        return False
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED:
        return False
    band = dict(row, verdicts=[v for v in row.get("verdicts", ()) if isinstance(v.get("solution"), dict)
                               and "classified" not in v["solution"]
                               and SOLUTION_BLOCKS <= v["solution"].get("blocks", 0) < trove_solution_ocr.SURE_BLOCKS])
    return bool(band["verdicts"]) and bool(answerable_gaps(band, paper, sure=False))


#: The due reason of a Times edition read before REREAD_OTHER_GRID whose linked solution grid read short at
#: blocks SOLUTION_BLOCKS to SURE_BLOCKS, no cell classified: since then answers_only reads its crop for
#: another puzzle's grid (printed_grid), the grid printed under the page's other heading taken
#: (swapped_heading), else none (OTHER_GRID). 10-26: 13 Times held 6+ short so, 8 of them on four
#: Saturday pages that print the two grids under each other's headings. answers_only, once.
OTHER_GRID_SHORT = "solution short, its blocks read for another puzzle's grid since"
REREAD_OTHER_GRID = "2026-10-26T03:00:00+00:00"


def other_grid_short(row):
    """Whether Times ledger `row`, read before REREAD_OTHER_GRID, read a linked solution grid short at blocks
    SOLUTION_BLOCKS to SURE_BLOCKS with no cell classified, for a puzzle answers_only reads (answerable_gaps):
    unsure_short's band, read again for printed_grid and swapped_heading."""
    if not scan_queue.read_before(row, scan_queue.when(REREAD_OTHER_GRID)):
        return False
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED:
        return False
    band = dict(row, verdicts=[v for v in row.get("verdicts", ()) if isinstance(v.get("solution"), dict)
                               and "classified" not in v["solution"] and not v["solution"].get("refused")
                               and v["solution"].get("accepted", 0) < v["solution"].get("lights", 0)
                               and SOLUTION_BLOCKS <= v["solution"].get("blocks", 0) < trove_solution_ocr.SURE_BLOCKS])
    return bool(band["verdicts"]) and bool(answerable_gaps(band, paper, sure=False))


#: The due reason of a Times edition read before REREAD_SUSPECT whose linked solution grid gave answers
#: (accepted > 0, not refused) for a puzzle held from its page with every clue, not every answer, but
#: not complete(): a clue holding a word OCR made up (ocr_clues.suspect). decide() sent such a held
#: file's answers-only reading to --out, so its answers never reached the held file; since
#: REREAD_SUSPECT an answers-only reading always merges into the held file. answers_only, once.
#: 10-25: 111 Times files (2,390 lights) held so, 98 of them 6+ short.
SUSPECT_HELD = "solution short, its answers kept from a held file with a suspect clue"
REREAD_SUSPECT = "2026-10-25T13:30:00+00:00"
#: {held path: ((mtime_ns, size), whether this tool's, every clue filled, an answer short and not complete())}
_SUSPECT = {}


def suspect_held_file(series, number):
    """Whether `series`' puzzle `number` is held by this tool with every clue filled and an answer
    short, yet complete() refuses it (a suspect word in a clue); parsed again only when its stat moves."""
    p = _HELD_PATH.get((series, number))
    if p is None:
        return False
    try:
        st = p.stat()
    except OSError:
        return False
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _SUSPECT.get(p)
    if hit is None or hit[0] != stamp:
        try:
            held = json.loads(p.read_text())
        except (OSError, ValueError):
            return False
        es = held.get("entries") or ()
        bad = bool(es) and (held.get("source") or {}).get("acquiredBy") == TOOL \
            and filled(held)[0] == len(es) and not all(e.get("solution") for e in es) and not complete(held)
        hit = _SUSPECT[p] = (stamp, bad)
    return hit[1]


def suspect_held(row):
    """Whether Times ledger `row`, read before REREAD_SUSPECT, has a verdict whose linked solution grid
    gave answers for a puzzle suspect_held_file holds."""
    if not scan_queue.read_before(row, scan_queue.when(REREAD_SUSPECT)):
        return False
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED:
        return False
    for v in row.get("verdicts", ()):
        s = v.get("solution")
        if not v.get("id") or v.get("refused") or not isinstance(s, dict) or s.get("refused") \
                or not s.get("accepted"):
            continue
        if filed_state(paper.series, v.get("number")) == (False, True) \
                and suspect_held_file(paper.series, v.get("number")):
            return True
    return False


#: The due reason of a Times edition read before REREAD_UNFILED_HELD whose linked solution grid gave
#: answers for a puzzle this tool holds with every clue, an answer short, yet whose answers never
#: reached the held file: a full read (answers_only stood aside: a held answer the grid reads otherwise,
#: the held file from another page, a reread that keeps the VLM) with a clue blank went to --out whole
#: (decide()), its answers with it; or its write was refused whole over a held clue the certain
#: punctuation mends left faulted (mend_held: "one . , owner" to "one , owner"). Since REREAD_UNFILED_HELD
#: decide() fills the held file's blank lights from such a reading, and mend_held keeps such a clue as
#: held. answers_only first, once. 10-25: 227 Times grids (3,825 answers in their --out copies) and 17
#: refused writes.
UNFILED_HELD = "solution short, its answers filed to --out over a held file with every clue"
REREAD_UNFILED_HELD = "2026-10-25T14:30:00+00:00"
#: {(held path, copy path): ((held stamp, copy stamp), whether the copy answers a light the held file leaves blank)}
_UNFILED_GAIN = {}


def unfiled_gain(series, number, pid):
    """Whether `series`' puzzle `number`, held by this tool with every clue filled on the grid of
    its --out copy CROPS/unfiled/`pid`.json, leaves blank a light that copy answers; parsed again only
    when either stat moves."""
    p = _HELD_PATH.get((series, number))
    if p is None:
        return False
    q = CROPS / "unfiled" / f"{pid}.json"
    stamp = (_stat_stamp(p), _stat_stamp(q))
    if None in stamp:
        return False
    hit = _UNFILED_GAIN.get((p, q))
    if hit is None or hit[0] != stamp:
        try:
            held, out = json.loads(p.read_text()), json.loads(q.read_text())
        except (OSError, ValueError):
            return False
        es = held.get("entries") or ()
        read = {entry_id(e): e.get("solution") for e in out.get("entries") or () if e.get("solution")}
        gain = bool(es) and (held.get("source") or {}).get("acquiredBy") == TOOL and filled(held)[0] == len(es) \
            and trove_solution_ocr.puzzle_grid(held) == trove_solution_ocr.puzzle_grid(out) \
            and any(not e.get("solution") and read.get(entry_id(e)) for e in es)
        hit = _UNFILED_GAIN[p, q] = (stamp, gain)
    return hit[1]


#: The write gate's refusals of a held clue that a mend left faulted (UNFILED_HELD's second cause).
GATE_REFUSALS = ("(punctuation.faults)", "holds the page's text")


def unfiled_held(row):
    """Whether Times ledger `row`, read before REREAD_UNFILED_HELD, has a verdict whose linked solution
    grid gave answers for a puzzle held with every clue and an answer short, that went to --out (a full
    read, "unfiled", its copy answering a light the held file leaves blank: unfiled_gain) or whose write
    the gate refused over a clue (GATE_REFUSALS)."""
    if not scan_queue.read_before(row, scan_queue.when(REREAD_UNFILED_HELD)):
        return False
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED:
        return False
    for v in row.get("verdicts", ()):
        s = v.get("solution")
        if not v.get("id") or v.get("refused") or not isinstance(s, dict) or s.get("refused") \
                or not s.get("accepted") or filed_state(paper.series, v.get("number")) != (False, True):
            continue
        refused = str(v.get("refusedWrite") or "")
        if "SHAPE" in refused and any(g in refused for g in GATE_REFUSALS):
            return True
        if v.get("unfiled") and not v.get("answersOnly") and unfiled_gain(paper.series, v.get("number"), v["id"]):
            return True
    return False


#: The due reason of a Times edition read before REREAD_HELD_CLASH whose linked solution grid's reading
#: (solved()'s CROPS/solution_reads copy) reads a held answer otherwise, for a puzzle this tool holds from
#: a printed grid (gridOrigin "published", no blog) with every clue and an answer short. answers_only
#: refused the whole reading over one such light before settle_held (times-5432's AIDE for AIRS, every
#: other new answer lost); since, the reading's word replaces the held one when listed, fitting every
#: crossing, and a letter it reads otherwise checked (REREAD_HELD_CLASH: an unchecked one alone took
#: times-7267's OOS for DOS, printed COS). Only OCR slips (each clashing light within CLASH_LETTERS
#: letters of the held answer): a reading that differs on whole words is another puzzle's grid
#: (times-11998 linked to July's solutions in November), not a misread. answers_only, once. 10-25: of
#: 7,125 such Times files held short, 62 had a cached reading clashing, 52 of them as slips.
HELD_CLASH = "solution short, a held answer its grid reads otherwise settled since"
REREAD_HELD_CLASH = "2026-10-25T17:15:00+00:00"
CLASH_LETTERS = 2
#: {(held path, reading path, gale): ((held stamp, reading stamp), whether the reading clashes as a slip)}
_HELD_CLASH = {}


def slip_clash(held, read):
    """Whether `read` ({"12-across": word}, a solution grid's reading) reads a held answer of puzzle
    `held` otherwise, each such light within CLASH_LETTERS letters of the held word (same length)."""
    was = {entry_id(e): e.get("solution") for e in held.get("entries") or ()}
    clash = [(was[k], a) for k, a in read.items() if was.get(k) and a and a != was[k]]
    return bool(clash) and all(len(h) == len(a) and sum(x != y for x, y in zip(h, a)) <= CLASH_LETTERS
                               for h, a in clash)


def held_clash_file(series, number, sol_dir, gale):
    """Whether `series`' puzzle `number`, held by this tool off a printed grid (no blog) with every
    clue filled and an answer short, from a Gale page when `gale` else an archive.org one (answers_only
    reads only the held file's own page), has a held answer its linked solution grid's reading (the
    solution page's edition dir name `sol_dir`) reads otherwise as a slip (slip_clash); parsed again
    only when either stat moves."""
    p = _HELD_PATH.get((series, number))
    if p is None:
        return False
    q = CROPS / "solution_reads" / f"{sol_dir}_{number}.json"
    stamp = (_stat_stamp(p), _stat_stamp(q))
    if None in stamp:
        return False
    hit = _HELD_CLASH.get((p, q, gale))
    if hit is None or hit[0] != stamp:
        try:
            held, read = json.loads(p.read_text()), json.loads(q.read_text()).get("answers") or {}
        except (OSError, ValueError):
            return False
        es = held.get("entries") or ()
        src = held.get("source") or {}
        bad = bool(es) and src.get("acquiredBy") == TOOL and src.get("gridOrigin") == "published" \
            and ("go.gale.com" in str(src.get("url") or "")) == gale \
            and "blog" not in (held.get("solutions") or {}) and filled(held)[0] == len(es) \
            and not all(e.get("solution") for e in es) and slip_clash(held, read)
        hit = _HELD_CLASH[p, q, gale] = (stamp, bad)
    return hit[1]


def held_clash(row):
    """Whether Times ledger `row`, read before REREAD_HELD_CLASH, has a verdict whose linked solution
    grid's reading clashes with a held answer of a puzzle held_clash_file holds."""
    if not scan_queue.read_before(row, scan_queue.when(REREAD_HELD_CLASH)):
        return False
    paper = paper_of(row.get("edition", ""))
    if paper.key not in CELLS_CLASSIFIED:
        return False
    for v in row.get("verdicts", ()):
        if not v.get("id") or v.get("refused") or not v.get("solutionFrom") \
                or filed_state(paper.series, v.get("number")) != (False, True):
            continue
        if held_clash_file(paper.series, v.get("number"), v["solutionFrom"].rsplit(" leaf ", 1)[0],
                           paper.key == GALE.key):
            return True
    return False


def fix_reason(row):
    """Why a read `row` is read again for a reader fix landed since, or None:
    a refusal read before its cause's fix (REREAD_REFUSED), or a solution
    grid read in part or refused by other solution code (solution_key): a
    Times paper's read in part before the cell classifier read its cells
    (no "classified" in its stats) is due as such; another paper's read
    under a SOLUTION_UNCLASSIFIED key stands, the classifier not reading
    its grids. Due
    whether its scan stands or not, so a stale scan never sinks it to the
    whole-corpus rank."""
    for v in row.get("verdicts", ()):
        t = REREAD_REFUSED.get(v.get("cause"))
        if t and scan_queue.read_before(row, scan_queue.when(t)):
            return f"refused {v['cause']} before its fix"
        t = REREAD_WRITE_FAILED.get(v.get("writeFailed"))
        if t and scan_queue.read_before(row, scan_queue.when(t)):
            return "refused writeFailed before its fix"
    why = renumbered(row)
    if why:
        return why
    if unparsed_fixed(row):
        return "refused unparsed before its fix"
    if untitled_rescan(row):
        return NO_TITLE_RESCAN
    if held_titles(row):
        return HELD_TITLE
    if held_strips(row):
        return HELD_STRIPS
    # Ahead of the short third column: a lost write's reread is a full read by current code (the third
    # column's too), and evidence; that reason is a blanket one bar THREE_COLUMNS_YEARS' (10-25: no such
    # unit planned, 273 of 2007-08's pages lost so).
    if scan_queue.read_before(row, scan_queue.when(REREAD_LOST)) and lost_writes(row):
        return LOST_WRITE
    if short_three_columns(row) and scan_queue.read_before(row, scan_queue.when(REREAD_THREE_COLUMNS[2])):
        return "short Times page, its third clue column read since"
    if right_foreign_held(row):
        return RIGHT_FOREIGN_READ
    if scan_queue.read_before(row, scan_queue.when(REREAD_UNFILED)) and unfiled_blank(row):
        return "unfiled before its fix"
    if unfiled_modern(row):
        return UNFILED_MODERN
    # Ahead of unenumerated_held: a refused grid is the evidence (edition_queue.evidence_reason), and
    # both are answers_only rereads (SOLUTION_FIXES), so the read is the same.
    if refused_grid(row):
        return REFUSED_GRID
    if unenumerated_held(row):
        return "answers held back by a clue with no enumeration"
    if heavy_short(row):
        return HEAVY_PRINT
    if unsure_short(row):
        return SURE_FRAMING
    if other_grid_short(row):
        return OTHER_GRID_SHORT
    if suspect_held(row):
        return SUSPECT_HELD
    if unfiled_held(row):
        return UNFILED_HELD
    if held_clash(row):
        return HELD_CLASH
    if row.get("solutionKey") != solution_key():
        paper = paper_of(row.get("edition", "")).key
        for v in row.get("verdicts", ()):
            s = v.get("solution")
            if isinstance(s, dict) and (s.get("refused") or s.get("accepted", 0) < s.get("lights", 0)):
                # More than SHORT_GAP short, short_cause predicts it nothing (only_evidence dropped it):
                # read once by this code, after the rest (short_again).
                if paper in CELLS_CLASSIFIED and not s.get("refused") \
                        and s.get("lights", 0) - s.get("accepted", 0) > SHORT_GAP and short_again(row) in (UNLISTED, SHORT_WIDE):
                    return SHORT_WIDE
                if paper in CELLS_CLASSIFIED and not s.get("refused") and "classified" not in s:
                    if answerable_gaps(row, paper_of(row.get("edition", "")), sure=False):
                        return UNCLASSIFIED_HELD
                    return "solution short, its cells unclassified"
                if paper not in CELLS_CLASSIFIED and row.get("solutionKey") in SOLUTION_UNCLASSIFIED:
                    continue
                return "solution short, read by other code"
    if short_unfitted(row):
        return SHORT_UNFITTED
    if unmerged_whole(row):
        return UNMERGED
    return short_again(row)


#: The solution_key()s before the cell classifier (CELLS_CLASSIFIED): it reads
#: only the Times papers' grids, so another paper's row read under one of
#: these reads its solution as it would now and stands.
SOLUTION_UNCLASSIFIED = frozenset({"49e26fb92ece9e33"})


#: The fixes a re-read is predicted to file a puzzle whole by (every clue
#: and every answer) that its last read left short (likely()): its answers'
#: solution heading links now in a stored scan; the next issue's heading,
#: which that issue's re-read rescans, links now in its archive.org text
#: (text_headings); its solution grid, read before read_framed (no
#: "lattices" in its stats), lacks at most PARTIAL_GAP lights; every clue
#: it held blank is one a VOTE_MENDED change since its read mends.
#: Also (LIKELY[4]) its solution grid, read by other code (solution_key), lacks at most
#: SHORT_GAP lights: answers_only reads it again with fitted_reads and, for the lights left, the
#: VLM's word for their cells (vlm_lights); or, read by this code's full read (no fitted read, no
#: strip asked), lacks at most trove_solution_ocr.STRIP_MAX (SHORT_UNFITTED).
LIKELY = ("answers linked", "answers in the next issue's text", "solution grid read before read_framed",
          "blanks a vote fix mends", "solution grid read before the fitted and VLM reads",
          "solution grid read whole, its answers never merged", "solution grid short of words no list holds")
#: The lights a solution grid read by other code may lack and be read again for the fitted and VLM
#: reads (trove_solution_ocr.STRIP_MAX, 2, caps the lights the VLM is asked of).
SHORT_GAP = 5
#: The lights a solution grid read before read_framed may lack and still be
#: predicted whole: read_framed read about two more a grid (84 Times crops,
#: 1,443 lights accepted to 1,617).
PARTIAL_GAP = 2


def filed_state(series, number):
    """(every answer, every clue) filed, of `series`' puzzle `number` as
    its file holds it, or None when none is filed; parsed again only when
    the file's stat moves (_WHOLE)."""
    p = _HELD_PATH.get((series, number))
    if p is None:
        return None
    try:
        st = p.stat()
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _WHOLE.get(p)
    if hit is None or hit[0] != stamp:
        es = json.loads(p.read_text()).get("entries") or ()
        hit = _WHOLE[p] = (stamp, (all(e.get("solution") for e in es), all(e.get("clue") for e in es)))
        _LIKELY_MOVED.append(True)
    return hit[1]


def answers_whole(v):
    """Whether verdict `v` read every answer: a solution grid read whole."""
    s = v.get("solution")
    return (bool(v.get("solutionFrom")) and isinstance(s, dict) and not s.get("refused")
            and s.get("accepted", 0) >= s.get("lights", 0))


def held_short(series, row, v):
    """(answers short, blanks mended) of verdict `v` of ledger `row` whose
    re-read could file it whole: its answers not filed whole yet, and
    whether its clues stand only by a VOTE_MENDED change; None when it is
    whole already or held by what no fix since mends (a refusal, a pending
    grid, a blank clue no change mends)."""
    if not v.get("id") or v.get("refused") or v.get("pending"):
        return None
    filed = filed_state(series, v["number"])
    clues = bool(filed and filed[1]) or not v.get("blank")
    mended = not clues and scan_queue.mended_at(row, v) is not None
    # A grid read whole stands for answers filed, bar a full read's whose answers never merged (UNMERGED).
    answers = not (filed and filed[0]) and (not answers_whole(v) or unmerged(row, v))
    if not (clues or mended) or not (answers or mended):
        return None
    return answers, mended


def short_cause(series, row, v, solutions):
    """The fix (LIKELY) a re-read is predicted to file verdict `v` of
    ledger `row` whole by, `solutions` the headings linked now ({number:
    heading}); None when it is whole already or no fix since mends what
    holds it (held_short; no heading linked; a solution grid read_framed
    read, or more than PARTIAL_GAP lights short, or refused)."""
    held = held_short(series, row, v)
    if held is None:
        return None
    answers, mended = held
    if not answers:
        return LIKELY[3]
    if not v.get("solutionFrom"):
        return LIKELY[0] if v["number"] in solutions else None
    s = v.get("solution")
    if not isinstance(s, dict) or s.get("refused"):
        return None
    gap = s.get("lights", 0) - s.get("accepted", 0)
    if gap <= 0:
        return LIKELY[5]  # held_short: read whole, its answers never merged (UNMERGED)
    if "lattices" not in s and gap <= PARTIAL_GAP:
        return LIKELY[2]
    # A grid read by other code (answers_only reads it again: the classifier, fitted_reads, and
    # for the lights still short the VLM's strips) that left at most SHORT_GAP lights; or one this
    # code's full read left at most STRIP_MAX lights short, never read fitted (SHORT_UNFITTED).
    if paper_of(row.get("edition", "")).key not in CELLS_CLASSIFIED or gap <= 0:
        return None
    if row.get("solutionKey") != solution_key():
        return LIKELY[4] if gap <= SHORT_GAP and s.get("blocks", 0) >= trove_solution_ocr.SURE_BLOCKS else None
    if (gap <= trove_solution_ocr.STRIP_MAX and not v.get("answersOnly")
            and scan_queue.read_before(row, scan_queue.when(REREAD_SHORT_FITTED))):
        return LIKELY[4]
    # Read short by at most STRIP_MAX before unlisted_reads (UNLISTED): its last lights may be names.
    if (gap <= trove_solution_ocr.STRIP_MAX and s.get("blocks", 0) >= trove_solution_ocr.SURE_BLOCKS
            and scan_queue.read_before(row, scan_queue.when(REREAD_UNLISTED))):
        return LIKELY[6]
    return None


#: {edition dir: (djvu.xml.gz's stat, [(number, leaf)])}: the solution
#: headings in each edition's archive.org text as paper.headings reads them
#: (text_headings), the stat taken with its paper's scan_key; {puzzle file: (its
#: stat, filed_state)}. save_likely and load_likely keep both between
#: processes.
_HEADINGS = {}
_WHOLE = {}
_LIKELY_MOVED = []
#: {edition dir: (its input_hash, its djvu.xml.gz's (mtime_ns, size) or None)}:
#: text_headings stats the text again only once the edition's files moved;
#: save_likely and load_likely keep it between processes too.
_HEADINGS_STAT = {}
#: How long (seconds) one plan spends reading headings out of archive.org
#: text not yet in _HEADINGS (~0.5s CPU, ~1s an edition on the media
#: mount); the rest wait for the next plan, their reads ranked as if none links.
HEADING_SECONDS = 3.0
#: ... and a plan brought up to date (PaperPlan) this many: those come every
#: few minutes, not every half hour, so the texts are read as fast in all.
HEADING_UPDATE_SECONDS = 0.5


def text_headings(d, deadline=None):
    """[(number, leaf)] of the solution headings edition dir `d`'s
    archive.org text prints on its crossword leaves, as its rescan reads
    them (_scan, a leaf with text); [] with no text. None when not read yet
    and time.monotonic() is past `deadline`."""
    xml = d / "djvu.xml.gz"
    try:
        files = input_hash(d)
    except OSError:
        files = None
    seen = _HEADINGS_STAT.get(str(d))
    if files is not None and seen is not None and seen[0] == files:
        st = seen[1]  # its files unmoved since that stat: a plan stats no edition again
    else:
        try:
            st = xml.stat()
            st = (st.st_mtime_ns, st.st_size)
        except OSError:
            st = None
        _HEADINGS_STAT[str(d)] = (files, st)
        _LIKELY_MOVED.append(True)
    if st is None:
        return []
    paper = paper_of(d)
    stamp = (*st, scan_key(paper))
    hit = _HEADINGS.get(str(d))
    if hit is not None and hit[0] == stamp:
        return hit[1]
    if deadline is not None and time.monotonic() > deadline:
        return None
    try:
        leaves = {p["leaf"] for p in json.loads((d / "pages.json").read_text()).get("crossword_pages", ())}
    except (OSError, ValueError):
        return []
    text = leaf_lines(xml, leaves)
    out = [(n, leaf) for leaf in sorted(text) for n, _ in paper.headings(text[leaf])[1]]
    _HEADINGS[str(d)] = (stamp, out)
    _LIKELY_MOVED.append(True)
    return out


def save_likely(path):
    """Write _HEADINGS, _WHOLE, _HEADINGS_STAT and _PAGES_FACTS to `path` when one moved since the last save."""
    if not _LIKELY_MOVED:
        return
    _LIKELY_MOVED.clear()
    tmp = f"{os.fspath(path)}.{os.getpid()}.tmp"
    os.makedirs(os.path.dirname(os.fspath(path)) or ".", exist_ok=True)
    with open(tmp, "wb") as f:
        pickle.dump({"headings": dict(_HEADINGS), "whole": dict(_WHOLE), "stat": dict(_HEADINGS_STAT),
                     "pages": dict(_PAGES_FACTS)}, f,
                    protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def load_likely(path):
    """Take what save_likely wrote to `path` (a heading stands while its
    stat, scan key in, does)."""
    try:
        with open(path, "rb") as f:
            snap = pickle.load(f)
        heads, whole = snap["headings"], snap["whole"]
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ValueError, TypeError, KeyError):
        return
    for k, v in whole.items():
        _WHOLE.setdefault(k, v)
    for k, v in heads.items():
        _HEADINGS.setdefault(k, v)
    # Each edition's djvu.xml stat stands while its input_hash does, so a
    # re-exec's first plan stats no edition again (text_headings).
    for k, v in (snap.get("stat") or {}).items():
        _HEADINGS_STAT.setdefault(k, v)
    # pages.json's url and edition stand while the edition's input_hash does (pages_facts).
    for k, v in (snap.get("pages") or {}).items():
        _PAGES_FACTS.setdefault(k, v)


def likely(paper, known, reads, rels, scans, solutions, held, order, st=None, fhs=None):
    """{edition dir: {fix: puzzles}} of the `reads` (dir: reason) whose
    re-read is predicted to file puzzles whole that their last read left
    short, by each fix (LIKELY, short_cause). An edition due as the issue
    printing an answerless puzzle's solution (STALE_SCAN[0]) counts each
    such puzzle whose heading its archive.org text links now (text_headings:
    HEADING_SECONDS a plan, the dirs in `order` first) and whose clues
    would stand. With `st` (a PaperPlan) and `fhs` (each read's input_hash),
    each row's and each edition's part is kept there while what it reads
    stands (_row_likely, _text_linked)."""
    update = st is not None and bool(st.rows)
    st = st or PaperPlan(None)
    out, wanting, causes = {}, set(), {}
    for rel, row in known.items():
        causes[rel], want = _row_likely(st, paper.series, rel, row, solutions)
        wanting.update(want)
    for d in reads:
        by = causes.get(rels[d])
        if by:
            out[d] = dict(by)
    deadline = time.monotonic() + (HEADING_UPDATE_SECONDS if update else HEADING_SECONDS)
    for d in [d for d in order if reads[d] == STALE_SCAN[0]] if wanting else ():
        scan = scans[rels[d]]
        day = scan.get("date") or day_of(d)
        linked = _text_linked(st, paper, d, rels[d], scan, day, held, deadline, (fhs or {}).get(d)) if day else None
        n = len(linked & wanting) if linked else 0
        if n:
            out.setdefault(d, {})[LIKELY[1]] = n
    return out


def _filed_folder(series, number):
    """(year folder, its mtime as held_files last listed it) of the filed
    puzzle `number` of `series`, or None: a puzzle rewritten (os.replace)
    moves its folder's mtime, so _row_likely's key sees it without a stat."""
    p = _HELD_PATH.get((series, number))
    if p is None:
        return None
    name = _HELD_FOLDER.get((series, number))
    return p, name, (_HELD_LISTED.get(series) or (0, {}))[1].get(name)


def _row_likely(st, series, rel, row, solutions):
    """({fix: puzzles} likely() counts for ledger `row`, [the numbers of its
    puzzles read without answers no heading links yet that a link would file
    whole]), kept in PaperPlan `st` while the row is the same object, the
    links of its verdicts' numbers stand and their filed puzzles' folders are
    unmoved."""
    vs = row.get("verdicts", ())
    if not vs:
        return (), ()
    key = (tuple(v.get("number") in solutions for v in vs), tuple(_filed_folder(series, v.get("number")) for v in vs))
    hit = st.rows.get(rel)
    if hit is not None and hit[0] is row and hit[1] == key:
        return hit[2], hit[3]
    by, wanting = {}, []
    for v in vs:
        cause = short_cause(series, row, v, solutions)
        if cause:
            by[cause] = by.get(cause, 0) + 1
        if (not v.get("solutionFrom") and v.get("number") not in solutions
                and (held_short(series, row, v) or (False,))[0]):
            wanting.append(v["number"])
    st.rows[rel] = (row, key, by, wanting)
    return by, wanting


def _text_linked(st, paper, d, rel, scan, day, held, deadline, fh):
    """{number} of the puzzles edition dir `d`'s archive.org text links a
    solution heading to (text_headings, linked_solutions of them), or None
    when it has none or they are not read yet (`deadline` passed). Kept in
    PaperPlan `st` while its scan and files stand, linked again only when the
    filed puzzles in its hosted_window move (as _linked)."""
    hit = st.texts.get(rel)
    if fh is not None and hit is not None and (hit[0] is scan or hit[0] == scan) and hit[1] == fh:
        if hit[4] is held:
            return hit[5]
        near = held_between(held, hit[2])
        if near == hit[3]:
            st.texts[rel] = (*hit[:4], held, hit[5])
            return hit[5]
    heads = text_headings(d, deadline)
    if not heads:
        if heads is not None and fh is not None:
            st.texts[rel] = (scan, fh, None, (), held, None)
        return None
    titled = {p["number"] for p in scan["puzzles"]}
    found = {"date": day, "puzzles": scan["puzzles"],
             "solutions": [{"number": n, "leaf": leaf} for n, leaf in heads if n not in titled]}
    window = hosted_window(paper, found)
    linked = frozenset(s["number"] for s in linked_solutions(paper, found, held))
    if fh is not None:
        st.texts[rel] = (scan, fh, window, held_between(held, window), held, linked)
    return linked


#: The due reason of a verdict recorded while no VLM address was configured
#: (vlm_reader.unconfigured): read OCR-only by accident, so incomplete or
#: unfiled for want of the asks. Evidence (edition_queue.evidence_reason) and
#: ranked like never-read work, not a blanket reread.
UNCONFIGURED_READ = "read while the VLM was unconfigured"
#: Spans (first, last readAt, UTC ISO text) of rows written before rows carried
#: the "vlmUnset" mark, when no VLM address was configured: 10-21 06:59-07:34,
#: the live queue (HOME=/data/home) had no ~/.config/cryptic-teacher/local.json
#: after commit 763b3d76b2 moved the addresses there. Only rows with no "vlm" count.
UNCONFIGURED_SPANS = (("2026-10-21T06:59:00+00:00", "2026-10-21T07:34:59+00:00"),)


def read_unconfigured(row):
    """Whether ledger `row` records a read made while the VLM URL was empty
    by accident: marked "vlmUnset" when written (edition_commit.row), or, with
    no VLM version, read within UNCONFIGURED_SPANS."""
    if row.get("vlm"):
        return False
    at = row.get("readAt") or ""
    return bool(row.get("vlmUnset")) or any(a <= at <= b for a, b in UNCONFIGURED_SPANS)


#: The reason of an edition whose scan found a title and whose read gave no verdict at all (not a
#: solutions-only read), its puzzle held by no file: never read as a puzzle. Due as "titles changed"
#: before, a blanket reason no plan keeps. Paul 10-25: ~430 Times pages stood so, unfiled (Gale 2000
#: 181, 2001 20, 2006 46, 2008-11 ~150, 1957 22; read 10-12..13 with an empty verdict list).
UNREAD_TITLES = "titles found, never read"


def unread_titles(row):
    """Whether ledger `row` holds a scan with titles, no verdict, no solutions-only read
    (solOnly), and none of those titles' puzzles held (filed_state, its series listed first)."""
    pz = (row.get("scan") or {}).get("puzzles") or ()
    if not pz or row.get("verdicts") or row.get("solOnly") or not row.get("edition"):
        return False
    series = paper_of(Path(row["edition"])).series
    _held_list(series)
    return all(filed_state(series, p.get("number")) is None for p in pz)


def blanket_or_fix(row, blanket):
    """`blanket` ("inputs changed", "titles changed": a reason only_evidence plans no unit for) for
    ledger `row`, but for a Times row whose fix_reason is an answers-only solution fix (SOLUTION_FIXES):
    that one. 10-25: 251 Times puzzles held 6+ answers short (fix_reason SHORT_WIDE) were never planned,
    their rows' solutionsSeen (or stored titles) no longer the planner's links, so due_reason answered
    the blanket reason before fix_reason was asked. Not for a row whose scan lost a verdict's title
    (answers_only reads only a title the scan holds, so the reread files nothing) unless the lost title
    is its held puzzle's (held_titles: HELD_TITLE reads it under that number; 10-25, 82 Times rows)."""
    if getattr(paper_of(row.get("edition", "")), "series", None) != SERIES:
        return blanket
    titles = {p.get("number") for p in (row.get("scan") or {}).get("puzzles") or ()}
    if any(v.get("read_as", v.get("number")) not in titles for v in row.get("verdicts", ())) \
            and not held_titles(row):
        return blanket
    why = fix_reason(row)
    return why if why in SOLUTION_FIXES else blanket


def due_reason(row, inputs, sol_seen, vlm_up, reread=None, sol_from=None):
    """Why an edition's ledger `row` is read again, or None: never read, its
    files (input_hash) or the solutions it can see moved, a solution it read
    off a page that no longer links it (`sol_from`: {number: {solution_source}}
    of every page linking each solution it sees; any of them may be the one
    read), its titles moved
    since its verdicts (a scan by new code, see scan_key), read without the
    VLM that now answers, or last read before `reread` (a datetime: the
    explicit --reread), or by another VLM version (vlm_reader.version: a new
    model or prompt; the whole-corpus rank, behind everything else)."""
    if "inputs" not in row:
        return "never read"
    if vlm_up and read_unconfigured(row):
        return UNCONFIGURED_READ
    if row["inputs"] != inputs or row.get("solutionsSeen") != sol_seen:
        # A found title never read is unread work whether or not its files moved since: Paul 10-25, 174
        # Gale Times pages of 2006-12 (137 of them 2009-11, mostly Saturdays, their wrong pages fetched
        # again) stood unfiled as "inputs changed", a blanket reason no plan keeps.
        return UNREAD_TITLES if unread_titles(row) else blanket_or_fix(row, "inputs changed")
    if any(v.get("solutionFrom") and v["solutionFrom"] not in (sol_from or {}).get(v["number"], {v["solutionFrom"]})
           for v in row.get("verdicts", ())):
        # 10-25: ~15 short Times rows stood "solution moved", a blanket reason no plan keeps.
        return blanket_or_fix(row, "solution moved")
    if sorted(p["number"] for p in row["scan"]["puzzles"]) != sorted(v.get("read_as", v["number"])
                                                                     for v in row.get("verdicts", ())):
        return UNREAD_TITLES if unread_titles(row) else blanket_or_fix(row, "titles changed")
    if vlm_up and not row.get("vlm"):
        # 10-25: ~16 short Times rows stood so; an answers-only fix due reads the answers, not the clues.
        return blanket_or_fix(row, "read without the VLM")
    why = fix_reason(row)
    if why:
        return why
    if reread and scan_queue.read_before(row, reread):
        return "--reread"
    if vlm_up and row.get("vlm") != vlm_up:
        return "read by another VLM"
    return None


#: Days after an edition whose scans a run limited to it reads afresh: the
#: next day's paper prints its solution, after a Sunday or a holiday later.
SOLUTION_DAYS = 7


def edition_date(d):
    """The date in an edition dir's name, or None."""
    return _date_in(d.name)


@functools.lru_cache(maxsize=None)
def _date_in(name):
    """edition_date of a dir name (pure, so kept: a plan asks it ~200k times for ~25k names)."""
    m = re.search(r"\d{4}-\d{2}-\d{2}", name)
    return datetime.date.fromisoformat(m.group()) if m else None


def unsettled(dirs, unscanned):
    """The `dirs` whose read waits on a scan in `unscanned`: those and each
    dated within SOLUTION_DAYS before one (its solution may print there);
    every dir when an unscanned one, or the dir itself, has no date."""
    if not unscanned:
        return set()
    pending = [edition_date(d) for d in unscanned]
    if None in pending:
        return set(dirs)
    pending.sort()
    out = set(unscanned)
    for d in dirs:
        day = edition_date(d)
        k = len(pending) if day is None else bisect.bisect_left(pending, day)
        if day is None or k < len(pending) and (pending[k] - day).days <= SOLUTION_DAYS:
            out.add(d)
    return out


def scan_near(dirs, rels, editions):
    """The edition dirs a run limited to `editions` scans: each named one and
    those of its item dated within SOLUTION_DAYS after it."""
    named = [d for d in dirs if rels[d] in editions]
    out = set(named)
    for n in named:
        start = edition_date(n)
        out |= {d for d in dirs if d.parent == n.parent and start and edition_date(d)
                and 0 < (edition_date(d) - start).days <= SOLUTION_DAYS}
    return out


def day_of(d):
    """Edition dir `d`'s date as ISO text, "" when its name has none: the
    key tools/edition_queue.py takes a rank's units by, newest first."""
    day = edition_date(d)
    return day.isoformat() if day else ""


def staged_at(d):
    """When edition dir `d` was laid out: its pages.json's mtime (written
    last); on the media disk, its edition manifest row's "at" (appended as
    pages.json was written), the dir stat'd only when it has no row."""
    if not media_manifest.on_media(d):
        return _staged_listed(d)
    held = media_manifest.edition_rows().get(media_manifest.edition_rel(d)) or {}
    if "at" not in held:
        held = _edition_off_disk(d, held)
    return held["at"]


def _staged_listed(d):
    """staged_at of an edition off the media disk (a test's)."""
    return (d / "pages.json").stat().st_mtime


#: An edition laid out this recently (staged_at) with no reading of its
#: current files is "just laid out": a download or a Gale page Paul saved,
#: which tools/edition_queue.py finds without a plan (fresh) and reads before
#: anything planned. An hour covers a queue that was down a while.
FRESH = 3600


# ------------------------------------------------------------ the per-edition queue

#: How urgent each reason to read an edition is (tools/edition_queue.py
#: takes the lowest first): 0 pages the Gale fetcher downloaded (never read), and any edition
#: just laid out (edition_queue.fresh, started ahead of the rank's planned
#: units); 1 any other
#: never-read edition and annotation's asks; 2 a re-read that can change
#: what it filed: its inputs or titles moved, it was read without the VLM,
#: a fix landed for what it refused, or its solution read short by other
#: solution code (solution_key); 3 the whole-corpus
#: re-reads: a scan by older scan code (scan_key) and --reread BEFORE, which
#: edition_queue.dispatch starts only once nothing ranked below 3 waits; so
#: does a read by another VLM version (a model or prompt change).
#: Within a rank, the reads likely() predicts to file the most puzzles
#: whole go first. Every reason due_reason or plan gives is named here.
#: The reason of the scan (OCR alone, no VLM ask) of the edition printing the solution of a Times puzzle
#: filed with every clue and not every answer (solution_hosts); rank 1, ahead of the other scans.
HOST_SCAN = "scan stale, solution host"
#: The reason of the solutions-only read (scan_unit's `host`) of a Gale Times edition printing the
#: solution of a Times puzzle filed with every clue and not every answer, whose scan stands (or
#: whose solutions_only read is done) but links none of it, read before REREAD_HOST_HEADINGS:
#: solutions_only now reads the bands at the "Solution" words its page reads left in the cache
#: (cached_page_words) and a Monday's "Solution to Crossword N" prize heading (prize_headings).
#: Paul 10-24: ~480 such Times puzzles' hosts held the heading's text, ~220 read clean.
#: Then (10-25) its misread "Solution" words too (solution_like: 1945-60s "SoL.UTION oF PvzzLe"),
#: "The Solution of" over its number (1973-74) and "SolutiontoCrossword" (host_heading_lines).
#: Then (10-25 evening) a number with its dot leader glued on ("No. 10,052....": LOOSE_NUMBER).
#: Then (10-25 night) the 2000s' headings by the day: "Solution to yesterday's" over "Crossword 22,204",
#: "Solution to last Saturday's" over "Crossword 22,199" (day_headings), "Competition Solution 23,450", "Crossword.21,677".
HOST_RESCAN = "solution host, its headings read before their fix"
#: Once: a host whose solutions_only read ("solOnly" "at") is older than this is due (host_rescan_due).
REREAD_HOST_HEADINGS = "2026-10-25T22:30:00+00:00"
#: The reason of the same read of a host read since REREAD_HOST_HEADINGS, before REREAD_HOST_GRIDS: solutions_only
#: now also reads a band over each near-square solution grid solution_shaped refuses (loose_bands). Paul 10-26:
#: 133 unanswered Times puzzles' hosts were on disk and the right page, yet read no heading for them; the 1940s
#: hosts (40) print theirs over a grid whose ink box reads 0.74-0.84 or 1.19-1.5 wide for its height.
HOST_GRID_RESCAN = "solution host, its loose solution grids unread"
#: Once: a host whose solutions_only read is older than this is due (host_rescan_due); HOST_GRID_RESCAN when
#: that read is newer than REREAD_HOST_HEADINGS (host_rescan_reason).
REREAD_HOST_GRIDS = "2026-10-26T07:45:00+00:00"
#: The reason of the same read of a host read since REREAD_HOST_GRIDS, before REREAD_HOST_COLUMNS: solutions_only
#: now also reads a heading set in a narrow column beside another, its number on the row under it
#: (column_headings: 1950's "SOLUTION OF PUZZLE" over "No. 6,235.", 1970's "The Solution to Crossword" over
#: "12,475, the fourth entry"), and the 2007-14 "Monday's Solution 23,792" (named_day_headings). Paul 10-26: 25
#: unanswered Times puzzles' hosts read their heading's words but linked none; 20 now link, 0 to another number.
HOST_COLUMN_RESCAN = "solution host, its column headings unread"
#: Once: a host whose solutions_only read is older than this is due (host_rescan_due); HOST_COLUMN_RESCAN when
#: that read is newer than REREAD_HOST_GRIDS (host_rescan_reason).
REREAD_HOST_COLUMNS = "2026-10-26T08:45:00+00:00"
#: The reasons of a scan unit read in its solution bands alone (scan_unit's `host`).
HOST_REASONS = (HOST_SCAN, HOST_RESCAN, HOST_GRID_RESCAN, HOST_COLUMN_RESCAN)
RANKS = {HOST_SCAN: 1, HOST_RESCAN: 1, HOST_GRID_RESCAN: 1, HOST_COLUMN_RESCAN: 1, "just laid out": 0, "never read (Gale fetch)": 0, "never read": 1, "annotation asked": 1, UNCONFIGURED_READ: 1, "inputs changed": 2, "titles changed": 2,
         "solution moved": 2, "read without the VLM": 2, "solution short, read by other code": 2,
         "solution short, its cells unclassified": 2, UNCLASSIFIED_HELD: 2, "refused clues-short before its fix": 2,
         **{f"refused {c} before its fix": 2 for c in (*REFUSALS, "writeFailed", "unparsed")}, "scan stale, answers missing": 2,
         "scan stale, answers linked": 2, "short Times page, its third clue column read since": 2, "unfiled before its fix": 2, UNFILED_MODERN: 2,
         "answers held back by a clue with no enumeration": 2, SHORT_UNFITTED: 2, UNMERGED: 2, UNLISTED: 2, VLM_UNLISTED: 2, VLM_FLOOR_SHORT: 2, LATE_STRIPS: 2, WIDE_STRIPS: 2, VLM_REJUDGED: 2, CANDIDATE_READS: 2, CLUE_SHORT: 2, CLASH_SHORT: 2, CLUE_WIDE: 2, HELD_STRIPS: 2, SHORT_WIDE: 2,
         HEAVY_PRINT: 2, SURE_FRAMING: 2, OTHER_GRID_SHORT: 2, SUSPECT_HELD: 2, UNFILED_HELD: 2, HELD_CLASH: 2,
         REFUSED_GRID: 2, RENUMBERED: 2, LOST_WRITE: 2, UNREAD_TITLES: 1, HELD_TITLE: 2, RIGHT_FOREIGN_READ: 2,
         NO_TITLE_RESCAN: 2, "scan stale": 3, "--reread": 3,
         # A Saturday Times Listener page read before its cut's fix (gale_listener.TIMES_CUTS).
         "Times Listener page read before its cut's fix": 2,
         "read by another VLM": 3,
         # A Listener page numbered by its title read, or refused unnumbered, while
         # its citation's date went unread (gale_listener.CITE_FIX): never read as
         # its own puzzle, as good as unread, and 35 held another's clues (10-24).
         "refused misnumbered before its fix": 0}
#: The reasons of a read whose scan is by older scan code: "answers missing"
#: when a stored title is a puzzle read without answers that no page links a
#: solution heading to and an edition is dated within SOLUTION_DAYS after it
#: (its read waits on that scan, whose code may now read the heading), or the
#: one after such a puzzle (six after a Saturday's prize), the issue printing
#: that solution;
#: "answers linked" when a puzzle it read without answers would now file
#: whole (likely(): a stored scan links its solution heading now).
STALE_SCAN = ("scan stale, answers missing", "scan stale", "scan stale, answers linked")
#: The rank of the re-reads that sweep the whole corpus.
BLANKET = 3


def rank_of_reason(reason):
    return RANKS[reason]


def scan_current(row, fh, rel=None):
    """Whether ledger `row` (of edition `rel`, else its own "edition") holds
    a scan of files `fh` by its paper's scan code."""
    if not (row and row.get("filesHash") == fh and "scan" in row):
        return False
    rel = rel or row.get("edition", "")
    paper = _CURRENT_PAPER.get(rel) if isinstance(rel, str) else None
    if paper is None:
        paper = paper_of(rel)
        if isinstance(rel, str):
            _CURRENT_PAPER[rel] = paper
    return row.get("scanKey") in current_keys(paper) and not prize_rescan(paper, row.get("scanKey"), rel)


#: {"<item>/<edition>": paper_of it} for scan_current, which the queue asks of
#: every queued scan each pass by name (paper_of memoizes Paths only). Kept
#: here, not in paper_of: scan() reaches paper_of, so a change there moves
#: every scan_key.
_CURRENT_PAPER = {}


def plan(paper, cache=CACHE, ledger=None, reread=None, asked=(), dirs=None):
    """What a run of `paper` has to do, scanning nothing: ([scan unit],
    [read unit]), each a dict with "rel", "rank" (RANKS), "reason"; a read
    unit's "needs" are the editions whose scans it waits on (its own and
    those dated SOLUTION_DAYS after it: its solution prints there), a scan
    unit's rank the most urgent read needing it. `asked` are the editions
    annotation asked to have read again (read whatever their row says);
    `dirs` limits the plan to those editions. Each list is by rank, then
    newest first: by edition date ("date", day_of), NEWEST_FIRST papers by
    staged_at (the page Paul saved last first)."""
    with held_once():
        return _plan_paper(paper, cache, ledger, reread, asked, dirs)


#: {(cache, paper key, ledger): (stamp, when (monotonic), (scan units, read units))}
#: of _plan_paper's last plan: reused (copied) while its stamp stands.
_PLANNED = {}
#: Seconds a kept plan is trusted at most, whatever its stamp (a backstop for
#: an input the stamp does not see, such as a puzzle file rewritten in place).
PLAN_REUSE = 3600


class PaperPlan:
    """What _plan_paper_fresh worked out of each edition of one paper, kept
    between its plans so a plan after a ledger row lands works out again only
    the editions that row (or what it moved) touches: each memo is keyed on
    the very row object the planner's fold of the ledger holds (a fold
    re-parses only the lines appended, so every other row keeps its
    identity) and on the slice of the corpus-wide inputs (solutions linked,
    answerless numbers, filed puzzles' folders) that edition reads. The paper
    is planned whole again (a new PaperPlan) at a process's start and every
    PLAN_FULL seconds after: the backstop for what no key sees (a reprint's
    size, a puzzle file rewritten in place)."""

    def __init__(self, request):
        self.request = request  # (reread, dirs): another request is another plan
        self.made = time.monotonic()
        self.rels = {}  # edition dir as text: "<item>/<edition>" (rel)
        self.newest = {}  # rel: its staged_at (NEWEST_FIRST papers)
        self.inputs = {}  # (filesHash, puzzle numbers): inputs_of
        self.reasons = {}  # rel: (row, memo key, why or None) of _edition_reason
        self.rows = {}  # rel: (row, memo key, {fix: puzzles}, [wanting numbers]) of _row_likely
        self.texts = {}  # rel: (scan, files hash, window, held_between, held, linked numbers) of _text_linked


#: {(cache, paper key, ledger): PaperPlan} of _plan_paper.
_PAPER_PLANS = {}
#: Seconds a PaperPlan is brought up to date before its paper is planned whole
#: again (Paul 10-17: "a queue to burn through", not a replan each row).
PLAN_FULL = 86400


def _stat_stamp(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _plan_stamp(paper, cache, ledger, reread, asked, dirs):
    """Everything _plan_paper's answer is made of, cheap to read, or None when
    it cannot be told cheaply (a cache off the media disk, a test's): the
    ledger and the sister ledgers (sister_solutions), the edition manifests
    (edition_dirs, input_hash, staged_at: append-only, so their stat says), the
    held listing's version and year folders (held_files), the scan and
    solution code's keys, the VLM version, and the request (`reread`,
    `asked`, `dirs`)."""
    if not media_manifest.on_media(cache):
        return None
    sisters = tuple(_stat_stamp(ledger_of(cache, p)) for p in FILERS.values()
                    if p is not paper and p.series == paper.series)
    held = _held_listing(paper.series)[0]
    folders = tuple(sorted((_HELD_LISTED.get(paper.series) or (0, {}))[1].items()))
    manifests = tuple(_stat_stamp(media_manifest.path(n)) for n in (media_manifest.ARCHIVE_EDITIONS,
                                                                    media_manifest.GALE_EDITIONS))
    return (_stat_stamp(ledger), sisters, manifests, held, folders, current_keys(paper), solution_key(),
            vlm_seen(), reread, frozenset(asked),
            None if dirs is None else tuple(dirs))


def plan_stamp(paper, cache=CACHE, reread=None, asked=()):
    """_plan_stamp of the whole-paper plan(): equal stamps mean plan() would
    answer the same units (None: not told cheaply, so always plan afresh).
    Within a held_once scope the listing and the VLM probe are made once."""
    return _plan_stamp(paper, cache, ledger_of(cache, paper), reread, tuple(asked), None)


def _plan_paper(paper, cache, ledger, reread, asked, dirs):
    """_plan_paper_fresh's answer, kept per paper: while no input of it moved
    (_plan_stamp) a replan is the last one's units copied, not every edition
    of the paper worked through again (seconds a paper on a loaded host, every
    cycle, for a queue that mostly has nothing new). When one moved (a ledger
    row landed), the paper's PaperPlan brings its last plan up to date: only
    the editions whose memo keys moved are worked out again."""
    ledger = ledger_of(cache, paper, ledger)
    asked = tuple(asked)
    stamp = _plan_stamp(paper, cache, ledger, reread, asked, dirs)
    k = (str(cache), paper.key, str(ledger))
    hit = _PLANNED.get(k)
    if stamp is not None and hit is not None and hit[0] == stamp and time.monotonic() - hit[1] < PLAN_REUSE:
        _PLANNED_DIRS[(str(cache), paper.key)] = hit[3]
        return _units_copy(hit[2])
    # The ledger is stamped before it is read, so a row appended during the plan makes the next one fresh.
    made = _plan_paper_fresh(paper, cache, ledger, reread, asked, dirs, paper_plan(cache, paper, ledger, reread, dirs))
    if stamp is not None:
        _PLANNED[k] = (stamp, time.monotonic(), _units_copy(made), _PLANNED_DIRS.get((str(cache), paper.key)))
    return made


def _units_copy(made):
    """(scan units, read units) of `made` in lists of their own, the units
    shared: no caller changes a unit (edition_queue builds new ones, {**u}),
    and a deepcopy of ~30k units was seconds a plan, a dict copy of each 1.5 s."""
    return tuple(list(us) for us in made)


def paper_plan(cache, paper, ledger, reread, dirs):
    """The PaperPlan _plan_paper brings up to date for this request, a new
    one (the paper planned whole) when there is none, it was for another
    `reread` or `dirs`, or it is PLAN_FULL seconds old."""
    k = (str(cache), paper.key, str(ledger))
    request = (reread, None if dirs is None else tuple(dirs))
    st = _PAPER_PLANS.get(k)
    if st is None or st.request != request or time.monotonic() - st.made >= PLAN_FULL:
        st = _PAPER_PLANS[k] = PaperPlan(request)
    return st


def _edition_reason(st, paper, d, rel, row, fh, stale, scan, solutions, sources, answerless, answerless_own,
                    has_host, seen_by, reread):
    """Why edition `d` (its ledger `row`, files hash `fh`) is read, or None
    (_plan_paper_fresh's reason, before an annotation ask): kept in PaperPlan
    `st` while the row is the same object and the corpus-wide facts its
    puzzles read (solutions linked, answerless numbers) are as they were."""
    nums = [p["number"] for p in scan["puzzles"]]
    if stale:
        own = tuple(n in answerless_own for n in nums)
        key = (True, fh, tuple(n in answerless for n in nums), own, any(own) and has_host(d))
    else:
        key = (False, fh, tuple(n in solutions for n in nums), seen_by,
               tuple(sources.get(v["number"]) for v in row.get("verdicts", ()) if v.get("solutionFrom")))
    hit = st.reasons.get(rel)
    if hit is not None and hit[0] is row and hit[1] == key:
        return hit[2]
    if stale:
        # Its files moved, or only the scan code: the latter is every
        # edition at once, a whole-corpus re-read.
        why = ("never read" if "inputs" not in row else
               "inputs changed" if row.get("filesHash") != fh else
               THREE_COLUMNS if third_column_first(row) else
               blanket_or_fix(row, STALE_SCAN[0]) if any(n in answerless or n in answerless_own and has_host(d)
                                                         for n in nums) else
               fix_reason(row) or STALE_SCAN[1])
    else:
        sol_seen = sorted(n for n in nums if n in solutions)
        ik = (row["filesHash"], tuple(nums))
        if ik not in st.inputs:
            st.inputs[ik] = inputs_of(row["filesHash"], scan, paper.series)
        why = due_reason(row, st.inputs[ik], sol_seen, seen_by, reread, sources)
    st.reasons[rel] = (row, key, why)
    return why


def _plan_paper_fresh(paper, cache, ledger, reread, asked, dirs, st=None):
    """_plan_paper's answer worked out; with `st` (a PaperPlan) each
    edition's part is taken from it while its memo key stands, else worked
    out and kept there. A new PaperPlan, or none, plans the paper whole."""
    st = st or PaperPlan((reread, None if dirs is None else tuple(dirs)))
    ledger = ledger_of(cache, paper, ledger)
    known = _planned_known(ledger)
    every = _PLANNED_DIRS[(str(cache), paper.key)] = edition_dirs(cache, paper)
    held_files(paper.series)  # cached here, so each unit forked after this reads only what changed
    dirs = every if dirs is None else [d for d in every if d in set(dirs)]
    # Keyed by the dir's text: edition_dirs' Paths are new objects when it lists again, and a
    # Path key's every lookup by an equal one is a Path __eq__ (~1.5 s a plan of the papers).
    rels = {}
    for d in every:
        s = os.fspath(d)
        rel = st.rels.get(s)
        if rel is None:
            rel = st.rels[s] = f"{d.parent.name}/{d.name}"
        rels[d] = rel
    seen_by = vlm_seen()
    fhs = {d: input_hash(d) for d in dirs}
    stale = [d for d in dirs if not scan_current(known.get(rels[d]), fhs[d], rels[d])]
    stale_set = set(stale)
    scans = {rels[d]: scan_of(known.get(rels[d]), paper, fhs.get(d)) or {"puzzles": [], "solutions": []} for d in every}
    held = held_dates(paper.series)
    solutions, sources = solution_sources(every, scans, rels, held, sister_solutions(cache, paper))
    asked = set(asked)
    unanswered = {(v["number"], datetime.date.fromisoformat(row["scan"]["date"]).weekday() == 5)
                  for row in known.values() if (row.get("scan") or {}).get("date") for v in row.get("verdicts", ())
                  if v.get("number") and not (v.get("solutionFrom") or v.get("refused") or v.get("pending"))
                  and v["number"] not in solutions}
    later = sorted(filter(None, map(edition_date, every)))

    def has_host(d):
        day = edition_date(d)
        k = len(later) if day is None else bisect.bisect_right(later, day)
        return k < len(later) and (later[k] - day).days <= SOLUTION_DAYS
    answerless = {n + (6 if sat else 1) for n, sat in unanswered}
    answerless_own = {n for n, _ in unanswered}
    reads = {}
    for d in dirs:
        rel, row = rels[d], known.get(rels[d]) or {}
        why = _edition_reason(st, paper, d, rel, row, fhs[d], d in stale_set, scans[rel], solutions, sources,
                              answerless, answerless_own, has_host, seen_by, reread)
        if not why and rel in asked:
            why = "annotation asked"
        if why == "never read" and paper.key in NEWEST_FIRST:
            why = "never read (Gale fetch)"
        if why:
            reads[d] = why
    # An edition whose puzzles will not file is not queued at all.
    skipped = {}
    reads_before = len(reads)
    for d in list(reads):
        rel = rels[d]
        label = None if d in stale_set and reads[d] != STALE_SCAN[1] else \
            unit_skip(paper, d, scans[rel], known.get(rel) or {}, reads[d], held)
        # A "scan stale" read whose puzzle is filed with every clue and no answers, its solution heading
        # linked now, is likely()'s "scan stale, answers linked" (answers_only: CPU, no VLM ask), not a
        # VLM-only reread of a puzzle already held. Paul 10-23: 1,136 Gale Times editions (~1,080
        # puzzles, 1940s-2010s) were skipped as "already held (VLM-only reason)" here before likely() ran.
        if label and LIKELY[0] in _row_likely(st, paper.series, rel, known.get(rel) or {}, solutions)[0]:
            label = None
        if label:
            del reads[d]
            skipped[f"read: {label}"] = skipped.get(f"read: {label}", 0) + 1
    # Which stale scans each read waits on: its own and the SOLUTION_DAYS after it.
    dated = sorted((edition_date(d), rels[d]) for d in stale if edition_date(d))
    undated = [rels[d] for d in stale if not edition_date(d)]
    days = [day for day, _ in dated]

    def needs(d):
        day = edition_date(d)
        if day is None:
            return [rels[s] for s in stale]
        lo = bisect.bisect_left(days, day)
        hi = bisect.bisect_right(days, day + datetime.timedelta(days=SOLUTION_DAYS))
        return [rel for _, rel in dated[lo:hi]] + undated
    if paper.key in NEWEST_FIRST:
        def newest(d):
            # staged_at kept: an edition's laid-out time stands (PLAN_FULL re-reads it).
            at = st.newest.get(rels[d])
            if at is None:
                at = st.newest[rels[d]] = staged_at(d)
            return at
    else:
        def newest(d):
            return edition_date(d) or datetime.date.min
    fixes = likely(paper, known, reads, rels, scans, solutions, held, sorted(reads, key=newest, reverse=True), st, fhs)
    for d, by in fixes.items():
        # A whole-corpus re-read a fix now completes a puzzle of is one that can change what was filed.
        if reads[d] == STALE_SCAN[1] and LIKELY[0] in by:
            reads[d] = STALE_SCAN[2]
    # Each rank's reads predicted to file the most puzzles whole first, then newest first.
    gain = {d: sum(fixes.get(d, {}).values()) for d in reads}
    queue = sorted(sorted(reads, key=newest, reverse=True), key=lambda d: (rank_of_reason(reads[d]), -gain[d]))
    read_units = [{"kind": "read", "paper": paper.key, "rel": rels[d], "reason": reads[d], "rank": rank_of_reason(reads[d]),
                   "date": day_of(d), "needs": needs(d), "force": reads[d] == "annotation asked",
                   **({"detail": refusal_detail(known.get(rels[d]) or {}, reads[d])} if reads[d].startswith("refused ") else {}),
                   **({"detail": "; ".join(f"puzzle {i}: {k} blank" for i, k in unfiled_blank(known.get(rels[d]) or {}))}
                      if reads[d] in ("unfiled before its fix", UNFILED_MODERN) else {}),
                   **({"detail": "gone: " + ", ".join(lost_writes(known.get(rels[d]) or {}))}
                      if reads[d] == LOST_WRITE else {}),
                   **({"likely": fixes[d]} if d in fixes else {})} for d in queue]
    rank_of, gain_of = {}, {}
    for u in read_units:
        for rel in u["needs"]:
            rank_of[rel] = min(rank_of.get(rel, 9), u["rank"])
            gain_of[rel] = max(gain_of.get(rel, 0), likely_gain(u))
    hosts = solution_hosts(paper, st, dirs, rels, stale_set, scans, solutions, held, fhs, known)
    scan_units = [{"kind": "scan", "paper": paper.key, "rel": rels[d], "rank": rank_of.get(rels[d], RANKS["scan stale"]),
                   "date": day_of(d), "reason": "scan stale" if "scan" in (known.get(rels[d]) or {}) else "never scanned",
                   **({"gain": gain_of[rels[d]]} if gain_of.get(rels[d]) else {})}
                  for d in sorted(sorted(stale, key=newest, reverse=True),
                                  key=lambda d: (rank_of.get(rels[d], RANKS["scan stale"]), -gain_of.get(rels[d], 0)))]
    if hosts:
        # The scans that link the answers of puzzles filed with every clue and not every answer go first.
        for u in scan_units:
            if u["rel"] in hosts and u["reason"] in ("scan stale", "never scanned"):
                u.update(reason=HOST_SCAN, rank=RANKS[HOST_SCAN], gain=hosts[u["rel"]])
        scan_units.sort(key=lambda u: u["reason"] != HOST_SCAN)  # stable: the order within each group stands
    # Hosts whose scan stands but whose solution bands were read before REREAD_HOST_COLUMNS, ahead too.
    rescans = host_rescans(paper, dirs, rels, stale_set, solutions, held, known)
    if rescans:
        scan_units[:0] = [{"kind": "scan", "paper": paper.key, "rel": rels[d], "rank": RANKS[HOST_RESCAN], "date": day_of(d),
                           "reason": host_rescan_reason((known or {}).get(rels[d])), "gain": rescans[rels[d]]}
                          for d in sorted((d for d in dirs if rels[d] in rescans), key=newest, reverse=True)]
    # A scan no read waits on, of an edition whose last scan found only puzzles that will not file.
    scans_before = len(scan_units)
    kept = []
    for u in scan_units:
        row = known.get(u["rel"]) or {}
        label = None if u["rel"] in rank_of or u["reason"] != "scan stale" else \
            unit_skip(paper, next(d for d in stale if rels[d] == u["rel"]), scans[u["rel"]], row, "scan stale", held)
        if label:
            skipped[f"scan: {label}"] = skipped.get(f"scan: {label}", 0) + 1
        else:
            kept.append(u)
    scan_units = kept
    if skipped:
        progress(f"plan {paper.key}: reads {reads_before} -> {len(read_units)}, scans {scans_before} -> {len(scan_units)}; "
                 "skipped " + ", ".join(f"{k} x{v}" for k, v in sorted(skipped.items())))
    return scan_units, read_units


def answerless_puzzles(series, held, solutions=()):
    """{number: date} of the puzzles of `series` filed with every clue and not every answer (filed_state), whose
    solution no heading in `solutions` links yet."""
    out = {}
    for n, day in held.items():
        if n in solutions:
            continue
        state = filed_state(series, n)
        if state and state[1] and not state[0]:
            out[n] = day
    return out


#: The first Saturday whose solution prints a week on (1981-07-11 holds 15,569 of 07-04): a Saturday
#: before it prints in the next issue, the Monday (1981-06-29 holds 15,563 of 06-27; hosted reads it as
#: the issue before the title). Paul 10-24: 55 Times Saturdays 1945-81 linked no solution, their
#: Mondays never read for one; 8 of 11 printed it.
WEEK_ON_SATURDAYS = datetime.date(1981, 7, 4)


@functools.lru_cache(maxsize=None)
def good_friday(year):
    """The Good Friday of `year` (Gregorian Easter, two days before)."""
    a, (b, c) = year % 19, divmod(year, 100)
    d, e = divmod(b, 4)
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    n = h + l - 7 * m + 114
    return datetime.date(year, n // 31, n % 31 + 1) - datetime.timedelta(days=2)


def no_paper(day):
    """Whether no Times is published on `day`: a Sunday or Christmas Day (no 25 Dec edition is in the
    archive in any year), so a solution due then prints in the next issue."""
    return day.weekday() == 6 or (day.month, day.day) == (12, 25)


def maybe_no_paper(day):
    """Whether the Times of `day` was published some years only: Boxing Day (on disk in 1987, 1989,
    1991 and from 1998, none before) and Good Friday (on disk from 1986, none before)."""
    return (day.month, day.day) == (12, 26) or day == good_friday(day.year)


def next_issue(day):
    """`day`, or the first day after it that is not no_paper."""
    while no_paper(day):
        day += datetime.timedelta(days=1)
    return day


def host_day(day):
    """The date of the issue printing the solution of the puzzle of `day`: the next day's, a Saturday's
    prize a week on, a Saturday's before WEEK_ON_SATURDAYS the Monday after (hosted: the issue before
    each title, the Saturday before's prize); a day with no paper (no_paper) gives way to the next issue.
    Paul 10-24: 12 puzzles were hosted by a 25 Dec, never on disk."""
    if day.weekday() != 5:
        return next_issue(day + datetime.timedelta(days=1))
    return next_issue(day + datetime.timedelta(days=7 if day >= WEEK_ON_SATURDAYS else 2))


#: The most days after a puzzle's that host_days may name (a Saturday's prize Monday on 25 Dec, the
#: 26th without a paper: the 27th): hosted reads the held puzzles this far before each day it prints on.
HOST_REACH = 11


def host_days(day, on=None):
    """Every date that may print the solution of the puzzle of `day`: host_day, and for a Saturday
    from PRIZE_MONDAYS also the Monday week after (nine days on: PRIZE_LAG). A host that is
    maybe_no_paper and not in `on` (the dates on disk; None: unknown) has the next issue after it too."""
    more = [next_issue(day + datetime.timedelta(days=9))] if day.weekday() == 5 and day >= PRIZE_MONDAYS else []
    out = []
    for h in (host_day(day), *more):
        gap = maybe_no_paper(h) and (on is None or h not in on)
        for g in (h, next_issue(h + datetime.timedelta(days=1))) if gap else (h,):
            if g not in out:
                out.append(g)
    return out


def hosts_of(day):
    """The dates of the puzzles whose solution an issue of `day` may print (host_days inverted)."""
    return [d for d in (day - datetime.timedelta(days=k) for k in range(1, HOST_REACH + 1)) if day in host_days(d)]


def host_rescan_due(paper, row):
    """Whether Gale Times ledger `row` of a solution host is due its solutions_only read once more
    (HOST_RESCAN, HOST_GRID_RESCAN, HOST_COLUMN_RESCAN): none made at or after REREAD_HOST_COLUMNS (a "solOnly"
    with no "at" is older)."""
    return paper is GALE and bool(row) and str((row.get("solOnly") or {}).get("at") or "") < REREAD_HOST_COLUMNS


def host_rescan_reason(row):
    """The reason a host_rescan_due ledger `row` is read: HOST_RESCAN when its solutions_only read is older
    than REREAD_HOST_HEADINGS (or there is none), HOST_GRID_RESCAN when older than REREAD_HOST_GRIDS (loose_bands
    new to it), else HOST_COLUMN_RESCAN (only column_headings and named_day_headings are)."""
    at = str(((row or {}).get("solOnly") or {}).get("at") or "")
    return HOST_RESCAN if at < REREAD_HOST_HEADINGS else HOST_GRID_RESCAN if at < REREAD_HOST_GRIDS \
        else HOST_COLUMN_RESCAN


def host_rescans(paper, dirs, rels, stale_set, solutions, held, known):
    """{rel: puzzles} of the Gale Times editions whose scan stands, host_days of a puzzle filed with
    every clue and not every answer (answerless_puzzles), that link none of those puzzles and are
    host_rescan_due: solution_hosts' stale hosts' kin, read in their solution bands alone (HOST_RESCAN)."""
    if paper is not GALE:
        return {}
    want, on = {}, set(map(edition_date, dirs))
    for n, day in answerless_puzzles(paper.series, held, solutions).items():
        for host in host_days(day, on):
            want.setdefault(host, []).append(n)
    out = {}
    for d in dirs:
        nums = want.get(edition_date(d)) if d not in stale_set else None
        if nums and host_rescan_due(paper, (known or {}).get(rels[d])):
            out[rels[d]] = len(nums)
    return out


def solution_hosts(paper, st, dirs, rels, stale_set, scans, solutions, held, fhs, known=None):
    """{rel: puzzles} of the editions of `paper` whose scan by current code is due because they print the
    solution of puzzles filed with every clue and not every answer (answerless_puzzles): the issue
    host_day names, scanned alone (no week after, not the puzzle's own edition). One not stale is left out
    (its scan by this code links what it links), as is one whose archive.org text prints headings that link
    none of its puzzles (_text_linked); one with no text or whose text is not read yet is kept."""
    if paper.series != SERIES:
        return {}
    want, on = {}, set(map(edition_date, dirs))
    for n, day in answerless_puzzles(paper.series, held, solutions).items():
        for host in host_days(day, on):
            want.setdefault(host, []).append(n)
    if not want:
        return {}
    deadline = time.monotonic() + HEADING_UPDATE_SECONDS
    out = {}
    for d in dirs:
        day = edition_date(d)
        nums = want.get(day)
        if not nums or d not in stale_set:
            continue
        rel = rels[d]
        if only_current((known or {}).get(rel), paper, fhs.get(d)) and not host_rescan_due(paper, (known or {}).get(rel)):
            continue  # its solution bands are read (solutions_only): linked, or there are none for these puzzles
        linked = _text_linked(st, paper, d, rel, scans[rel], scans[rel].get("date") or day_of(d), held, deadline, fhs.get(d))
        if linked is not None and not linked & set(nums):
            continue
        out[rel] = len(nums)
    return out


#: Reasons an edition is read for a bug: never skipped (a reread is wanted).
BUG_READS = ("refused ", "unfiled before", "short Times page", "solution short", "annotation asked", "--reread", LOST_WRITE)
#: The fix reasons a read is due for its solution grid alone (fix_reason): its clues stand, so it is
#: not one whose clues the VLM must read again (_KEEP_VLM). answers_only reads it first (the
#: classifier, fitted_reads and the VLM's strips for the last lights), the full read when it cannot.
#: Paul 10-23: kept for the VLM, every such reread took the full read, whose solved() has no
#: enumerations: no fitted read, no strip asked (no ledger verdict ever had "vlmLights").
SOLUTION_FIXES = ("solution short, its cells unclassified", "solution short, read by other code",
                  "answers held back by a clue with no enumeration", SHORT_UNFITTED, UNMERGED, UNLISTED, VLM_UNLISTED, SHORT_WIDE,
                  REFUSED_GRID, UNCLASSIFIED_HELD, RENUMBERED, HELD_TITLE, HEAVY_PRINT, SUSPECT_HELD, UNFILED_HELD,
                  HELD_CLASH, VLM_FLOOR_SHORT, LATE_STRIPS, WIDE_STRIPS, SURE_FRAMING, OTHER_GRID_SHORT, VLM_REJUDGED, CANDIDATE_READS,
                  HELD_STRIPS, CLUE_SHORT, CLASH_SHORT, CLUE_WIDE)


def keeps_vlm(why, row, unit=None):
    """Whether a read due for `why` (due_reason of its ledger `row`; `unit` the queue's, None for a
    whole-corpus run) reads its clues again (_KEEP_VLM: no answers_only): a bug's reread or a fix
    landed, bar SOLUTION_FIXES; a forced one; a run with no queue unit of an edition not due."""
    fix = fix_reason(row)
    return ((why or "").startswith(BUG_READS) and why not in SOLUTION_FIXES or bool(fix) and fix not in SOLUTION_FIXES
            or unit is not None and bool(unit.get("force")) or not why and unit is None)
#: Reasons that are the VLM's alone (not new files, solutions or titles).
VLM_READS = ("read without the VLM", "read by another VLM", STALE_SCAN[1])


def unit_skip(paper, d, scan, row, reason, held):
    """Why edition `d` need not be scanned or read for `reason` (None: it
    does), judged from its last `scan` and ledger `row`, with no image and no
    VLM: every title is refused by the date checks (filed_number: a Sunday,
    a number the date does not imply), or its puzzle is already held whole
    (every clue and answer) at the number and day the title files as, or,
    when `reason` is the VLM's alone, held at all or last refused as no
    grid. An edition with bug evidence (BUG_READS, fix_reason) is kept."""
    if reason.startswith(BUG_READS) or reason == "titles changed" or fix_reason(row):
        return None
    hits = scan.get("puzzles") or []
    if not hits or "failed" in scan or not scan.get("date"):
        return None
    vlm_only = reason in VLM_READS or reason == "scan stale"
    verdicts = {v.get("read_as", v.get("number")): v for v in row.get("verdicts", ())}
    labels = set()
    for hit in hits:
        try:
            number, day, why = filed_number(d, scan, hit)
        except Exception:
            return None
        if why:
            if "Sunday" not in why and reason in STALE_SCAN:
                return None  # the scan code moved: its numbers may read otherwise
            labels.add("sunday" if "Sunday" in why else "number-date check")
        elif number in held and held[number] == day and filed_state(paper.series, number) == (True, True):
            labels.add("already held whole")
        elif vlm_only and number in held:
            labels.add("already held (VLM-only reason)")
        elif vlm_only and (verdicts.get(hit["number"]) or {}).get("cause") == "not-a-grid":
            labels.add("not a grid")
        else:
            return None
    return "/".join(sorted(labels))


def refusal_detail(row, reason):
    """Which puzzle of ledger `row` a "refused <cause> before its fix" read is
    for and what the refusal said (truncated), for the queue's log line."""
    cause = reason[len("refused "):-len(" before its fix")]
    return "; ".join(f"puzzle {v.get('number') or v.get('id') or '?'}: {str(v.get('refused') or v.get('writeFailed'))[:100]}"
                     for v in row.get("verdicts", ()) if v.get("cause") == cause or (cause == "writeFailed" and v.get("writeFailed")))[:300]


def likely_gain(unit):
    """How many puzzles a read unit is predicted to file whole (its
    "likely" fixes, plan), or a scan unit's reads at most ("gain")."""
    return unit.get("gain", 0) + sum((unit.get("likely") or {}).values())


#: {(cache, paper key): edition dirs} as the last plan() listed them: a unit
#: forked after it starts from this list (its own edition added), not a
#: listing of every item of its own (seconds each on a loaded host).
_PLANNED_DIRS = {}


#: The rule version of solutions_only's reads: a "solOnly" ledger field made by
#: another stands for nothing (only_current). Not part of scan_key(): scan()
#: reaches none of this, and the edition's own scan is never taken for it.
SOLUTIONS_ONLY = 1


def solutions_only(d):
    """The scan-shaped {"date", "item", "puzzles": [], "solutions": [...]} of
    Gale edition `d` read in its solution bands alone (a solution grid's
    shape, solution_bands, each band read by every reader), 20-60 CPU-s a page
    where _scan's whole-page read is 150-200: the solution headings it prints,
    judged against the titles the date implies (expected +- slack, one reader
    standing) since no title is read. None when a leaf has archive.org text
    (its scan is cheap and whole). Never reaches scan(): it is no scan of the
    edition (no puzzle is found), and a row of it never stands for one."""
    pages = json.loads((d / "pages.json").read_text())
    leaves = sorted(p["leaf"] for p in pages.get("crossword_pages", ()) if (d / f"leaf_{p['leaf']:04d}.jpg").exists())
    if leaf_lines(d / "djvu.xml.gz", set(leaves)):
        return None
    day = datetime.date.fromisoformat(pages["date"])
    paper = paper_of(d)
    expected = paper.expected(day)
    voted = list(range(expected - paper.slack, expected + paper.slack + 1))
    found = {"date": pages["date"], "item": pages["item"], "puzzles": [], "solutions": []}
    # A Monday's "Solution to Crossword 22,845" (2004-12-20: no "Prize" word, so neither PRIZE_SOLUTION
    # nor a SOLUTION_LAGS number) is the Saturday prize's, PRIZE_LAG before the date's title.
    prize = {t - PRIZE_LAG for t in voted} if prize_monday(day) and paper.series == SERIES else set()
    # "Solution to yesterday's" over "Crossword 22,204" (day_headings): any number a heading may print.
    lagged = {t - lag for t in voted for lag in SOLUTION_LAGS + HOLIDAY_LAGS}
    # A heading set in a narrow column beside another (column_headings): the numbers solution_headings expects.
    lags = {t - lag for t in voted for lag in SOLUTION_LAGS}
    import ocr_remote
    with ocr_remote.local_slot():
        for leaf in leaves:
            img = page(d, leaf)
            key = f"{d.parent.name}_{d.name}_{leaf}"
            sols = {}
            # column_headings' and named_day_headings' finds, taken after every other read's, less the numbers
            # any read saw deferred ("will appear on Wednesday")
            columns, deferred = {}, set()
            read = cached_page_words(key)

            def judge(lines, pool=None):
                if paper.series == SERIES:
                    for n, b in day_headings(lines, lines if pool is None else pool, lagged):
                        sols.setdefault(n, b)
                lines = host_heading_lines(lines, pool)
                lines += [ln[k:] for ln in lines for k in range(1, len(ln))
                          if HEADING_START.match(ln[k][4]) or solution_like(ln[k][4])]
                for n, b in {n: b for n, b in reversed(paper.headings(lines, voted)[1] + prize_headings(lines, prize))}.items():
                    sols.setdefault(n, b)
                if paper.series == SERIES:
                    for n, b in column_headings(lines, lines if pool is None else pool, lags, deferred) \
                            + named_day_headings(lines, lagged):
                        columns.setdefault(n, b)
            for band in loose_bands(img, solution_bands(img, [(*w[:4], marked_solution(w[4])) for words in read for w in words])):
                for which in READERS:
                    path = CROPS / "titles" / f"{key}_{'_'.join(map(str, band))}.{reader_key(which)}.json"
                    judge(row_lines([(*w[:4], mend_misreads(w[4])) for w in band_words(img, band, which, path)]))
            for words in read:  # the page's whole reads, as its scan read them (no OCR: cached), on the
                # lines with a "Solution" word, however misread (solution_like), each joined to its number's
                # line under it where it has none (host_heading_lines): a title line's "PUZZLE No. 4,950"
                # alone is no heading
                lines = printed_lines(words)
                judge([ln for ln in lines if any(solution_like(w[4]) for w in ln)], lines)
            for n, b in columns.items():
                if n not in deferred:
                    sols.setdefault(n, b)
            found["solutions"] +=[{"number": n, "leaf": leaf, "box": box} for n, box in sols.items()
                                   if n not in {s["number"] for s in found["solutions"]}]
    return found


#: The width over height a solution grid's ink box may read at in loose_bands, past solution_shaped's
#: 0.85-1.18: the 1940s Times's small solution grid, left of the puzzle's under the clue columns, thresholds
#: to a box 0.74-0.84 (its heading's ink run into its top) or 1.19-1.5 (its foot rows broken off).
LOOSE_GRID = (0.7, 1.55)


def loose_bands(img, bands):
    """`bands` (solution_bands) and one over each grid on page `img` as wide as a solution grid
    (SOLUTION_GRID) whose box is near square (LOOSE_GRID) but not solution_shaped, reaching down by
    as far as the box is taller than wide (the heading run into the grid's top lies inside it), where
    no band of `bands` covers it already. Paul 10-26: the 1940s Times hosts' "Solution of Puzzle
    No. 3,718" is set in type the whole-page reads lose, over a grid solution_shaped refuses, so no
    band was cut and no heading read. solutions_only's alone: scan() reaches none of it."""
    k = img.width / SCAN_WIDTH
    left, right, pad, over = (int(v * k) for v in SOLUTION_BAND)
    shaped, most = solution_shaped(img), SOLUTION_GRID[1] * max(1, img.width / SCAN_WIDTH)

    def loose(box):
        w, h = (box[2] - box[0]) / k, (box[3] - box[1]) / k
        return SOLUTION_GRID[0] <= w <= most and LOOSE_GRID[0] <= w / max(h, 1) <= LOOSE_GRID[1] and not shaped(box)
    out = list(bands)
    for g in grids_on(img, shaped=loose):
        band = (max(0, g[0] - left), max(0, g[1] - over), min(img.width, g[0] + right),
                min(img.height, g[1] + max(0, (g[3] - g[1]) - (g[2] - g[0])) + pad // 5))
        if not any(abs(band[0] - b[0]) < 2 * left and min(band[3], b[3]) > max(band[1], b[1]) for b in out):
            out.append(band)
    return out


def cached_page_words(key):
    """[words] of each whole-page read (PAGE_READERS, plain or grid-first) the scans of leaf `key`
    ("<item>_<edition>_<leaf>") left in the crop cache, mend_misreads applied; [] where none did.
    Read, never made: solutions_only takes from them the "Solution" words its bands start at
    (solution_bands) and the headings they read, where no solution grid's top band holds the heading
    (1945-04-27's "Solution of Puzzle No. 4,725", a scan whose grid-first title read lost the title)."""
    out = []
    for which in PAGE_READERS:
        for tail in ("", ".gf"):
            try:
                words = json.loads((CROPS / "titles" / f"{key}_page.{reader_key(which)}{tail}.json").read_text())["words"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            out.append([(*w[:4], mend_misreads(w[4])) for w in words if len(w) == 5])
    return out


#: A "Solution" word run into its connective and the next word ("SolutiontoCrossword 21,584", 2000-11-28).
SOLUTION_GLUED = re.compile(r"^(\W*\S{5,9}?)(t[o0]|[o0][fl])((?:cr|p)\S{3,8})?$", re.IGNORECASE)
#: How many lines under a host's heading line with no number host_heading_lines joins it to, for the
#: number: 1980's "Solution of Puzzle No" over "15,294"; 1973's "The Solution of", "Puzzle No.", "13,313".
HEADING_RUN = 2


def solution_like(text):
    """Whether OCR word (or phrase) `text` holds a "Solution" word as our readers misread one in a host's
    small type ("SoL.UTION", "SoLuTinN", "Solltion", "SLuTIoN", "sSolution": the clue column's last
    letter run on): SOLUTION_WORD, or a word of 6-10 letters and no digit, its first an "s", like
    "solution" at 0.75 (not "evolution", "resolution"), or one run into its connective (SOLUTION_GLUED)."""
    if SOLUTION_WORD.search(text):
        return True
    for tok in text.split():
        if not 6 <= len(tok) <= 24 or tok.lstrip("\"'([-:.,|")[:1] not in ("s", "S") or re.search(r"\d", tok):
            continue  # no letters enough, or not opening at an "s" (most of a page's ~10k words)
        g = SOLUTION_GLUED.match(tok) if len(tok) > 10 else None
        letters = re.sub(r"[^a-z]", "", (g[1] if g and g[3] else tok).lower())
        if 6 <= len(letters) <= 10 and letters[0] == "s" and SequenceMatcher(None, letters, "solution").ratio() >= 0.75:
            return True
    return False


def marked_solution(text):
    """`text` with each solution_like word that SOLUTION_WORD misses read as "Solution", so solution_bands
    starts a band at it."""
    return re.sub(r"\S+", lambda m: m[0] if SOLUTION_WORD.search(m[0]) or not solution_like(m[0]) else "Solution", text)


def split_words(ln):
    """Line `ln` with each word of several (a RapidOCR phrase: "The Solution of") split at its spaces, its
    box cut across by the letters, and a glued "SolutiontoCrossword" (SOLUTION_GLUED) as its three."""
    out = []
    for w in ln:
        parts = w[4].split()
        if len(parts) > 1:
            per, at = (w[2] - w[0]) / max(len(w[4]), 1), 0
            for p in parts:
                at = w[4].index(p, at)
                out.append((int(w[0] + per * at), w[1], int(w[0] + per * (at + len(p))), w[3], p))
                at += len(p)
        else:
            out.append(w)
    words = []
    for w in out:
        g = SOLUTION_GLUED.match(w[4]) if len(w[4]) > 10 and not re.search(r"\d", w[4]) else None
        words += [(*w[:4], g[1]), (*w[:4], g[2]), (*w[:4], g[3])] if g and g[3] and solution_like(g[1]) else [w]
    return words


def host_heading_lines(lines, pool=None):
    """`lines` as a host's misread headings read as solution_headings knows them (split_words), and each
    with a solution_like word and no digit after it joined to the HEADING_RUN lines under it in `pool`
    (the page's lines; `lines` when None) up to the first holding a digit, if any: "Solution of Puzzle
    No" over "15,294" (1980) reads "Solution of Puzzle No 15,294"; "The Solution of" over "Puzzle No."
    over "13,313" (1973) "The Solution of Puzzle No. 13,313"."""
    pool = lines if pool is None else pool
    out = [split_words(ln) for ln in lines]
    for ln, words in zip(lines, list(out)):
        at = next((k for k, w in enumerate(words) if solution_like(w[4])), None)
        if at is None or any(re.search(r"\d", w[4]) for w in words[at:]):
            continue
        run, cur = list(words), ln
        for _ in range(HEADING_RUN):
            under = lines_under(pool, cur)[:1]
            if not under:
                break
            cur = under[0]
            run += split_words(cur)
            if any(re.search(r"\d", w[4]) for w in cur):
                out.append(run)
                break
    return out


def prize_headings(lines, prize):
    """[(number, box)] of the LOOSE_SOLUTION headings in `lines` ("Solution to Crossword 22,845") whose
    number reads clean, digit for digit, as one of `prize` (a Monday's Saturday prize numbers): no
    repair, so a misread of another number never stands for one."""
    found = []
    for ws in lines:
        for k in range(len(ws)):
            text = ""
            for j in range(k, len(ws)):
                text = (text + " " + ws[j][4]).strip()
                m = LOOSE_SOLUTION.match(text)
                if not m or not like(m[1], "solution") or not (m[3] and like(m[3], "crossword")):
                    continue
                read = re.sub(r"[\s,.]", "", m[4])
                if read.isdigit() and int(read) in prize:
                    found.append((int(read), box_of(ws[k:j + 1])))
                break
    return found


#: A Gale Times host's heading that names its puzzle by the day: "Solution to yesterday's" and "Solution to
#: last Saturday's" (2002-04 Saturdays) over "Crossword 22,204", "Crossword 22,199". Its "Solution"
#: capitalised: prose's "the solution to yesterday's crisis" is none. (2012-13's "The Solution to
#: yesterday's" prints no number and has no grid under it: the ink there is a 142x20 rule.)
DAY_HEADING = re.compile(r"^\W*((?-i:S)\S{5,9})\s+t\S?\s+(?:yesterday|last\s+saturday)\W{0,2}s\W*$", re.IGNORECASE)
#: The "Crossword 22,204" line under a DAY_HEADING (a mark may be glued on: "Crossword.21,677").
CROSSWORD_UNDER = re.compile(r"^\W*([A-Za-z]\S{5,10}?)[\s.,:;\-]*(\d[\d\s.,]{3,7}?)\W*$")


def day_headings(lines, pool, expected):
    """[(number, box)] of the DAY_HEADING headings in `lines` with "Crossword N" under them in `pool` (the
    nearest line under holding words below the heading's own span, those words alone: a two-column band's
    "Crossword 22,204 Crossword 22,199" under "Solution to yesterday's Solution to last Saturday's"), N one
    of `expected` (solution_number)."""
    found = []
    for ln in lines:
        words = split_words(ln)
        for k in range(len(words)):
            for span in (3, 4):
                head = words[k:k + span]
                m = len(head) == span and DAY_HEADING.match(" ".join(w[4] for w in head))
                if not m or not like(m[1], "solution") or re.search(r"\d", m[1]):
                    continue
                x0, x1, h = head[0][0], head[-1][2], head[0][3] - head[0][1]
                top, foot = min(w[1] for w in head), max(w[3] for w in head)
                under = []  # (not lines_under: "Crossword 22,204" opens above the foot "yesterday's" sets)
                for u in sorted((u for u in pool if u is not ln and (top + foot) / 2 < box_of(u)[1] <= foot + 2 * h),
                                key=lambda u: box_of(u)[1]):
                    under = [w for w in split_words(u) if x0 - h <= (w[0] + w[2]) / 2 <= x1 + h]
                    if under:
                        break
                c = CROSSWORD_UNDER.match(" ".join(w[4] for w in under))
                n = c and like(c[1].lower(), "crossword") and solution_number(c[2], expected)
                if n:
                    found.append((n, box_of(head + under)))
    return found


#: How far past a heading word, in its heights, the next word on its line may start and be the heading's:
#: a band's line runs on into the column beside it ("Solution OF PUZZLE" then, 94 px on, "DORKING-REIGATE").
COLUMN_GAP = 1.5
#: A deferral's words after a heading's number ("Solution of Puzzle No. 12,747 will appear on Wednesday",
#: read "willappearon", "will annear", "1 Bnnear"): that host prints no grid for it.
DEFERRED = re.compile(r"will|[a-z][pn]{2}[ec]ar", re.IGNORECASE)


def column_headings(lines, pool, expected, deferred=None):
    """[(number, box)] of the headings in `lines` set in a narrow column, a band's line running on into the
    one beside it: from each solution_like word, the words on its line up to a gap of COLUMN_GAP heights,
    joined to the rows under it in `pool` (the page's or band's lines) whose words start within two
    heights left of the heading (of a short word just before it: "The") and centre within three right of
    it, up to HEADING_RUN rows and the
    first holding a number (two digits or more: a speck under a misread "3.24" is no digit of it, 1942-06-01),
    read as solution_at reads a line (`expected`, solution_number). Paul 10-26:
    25 unanswered Times puzzles' hosts read their heading's words, never linked: 1950's "SOLUTION OF
    PUZZLE" over "No. 6,235." beside an advertisement column, 1970's "The Solution to Crossword" over
    "12,475, the fourth entry", 1976-86's "Solution of Puzzle No" over "14,322". None where words like
    "will appear" follow its number (DEFERRED: 1971-04-19, 1981-01-10 print no grid): its number is added
    to `deferred` (a set, when given) for the caller to refuse it from every other read of the leaf too
    (one read "will annear" as "1 Bnnear"). solutions_only's alone: scan() reaches none of it."""
    words = list({tuple(w): None for u in pool for w in split_words(u)})
    found = []
    for ln in lines:
        for w in split_words(ln):
            if not solution_like(w[4]) or re.search(r"\d", w[4]):
                continue
            h = max(w[3] - w[1], 1)
            mid = (w[1] + w[3]) / 2
            run = [w]
            # the next word on its row, in any line of `pool` (a band may split the row), up to its number: the
            # next column's clue number is none of it ("No. 4,14" then "5 A wooden-headed fellow": 4,145, 1943-06-09)
            def next_on_row(cur, seen):
                nxt = [v for v in words if -h <= v[0] - cur[2] <= COLUMN_GAP * h and v[0] > cur[0]
                       and abs((v[1] + v[3]) / 2 - mid) <= h / 2 and v not in seen]
                return min(nxt, key=lambda v: v[0]) if nxt else None
            while len(re.findall(r"\d", run[-1][4])) < 2:
                v = next_on_row(run[-1], run)
                if v is None:
                    break
                run.append(v)
            beyond = []  # the words on past its number, for DEFERRED alone ("No 15.419 will appear")
            for _ in range(3):
                v = next_on_row((beyond or run)[-1], run + beyond)
                if v is None:
                    break
                beyond.append(v)
            # the column's left from a short word just before ("The", "he": 1970's number sets under it)
            lead = [v for v in words if len(v[4]) <= 3 and 0 <= w[0] - v[2] <= COLUMN_GAP * h
                    and abs((v[1] + v[3]) / 2 - mid) <= h / 2]
            x0, x1 = min([w[0]] + [v[0] for v in lead]), max(v[2] for v in run)
            top, foot, rows = w[1], max(v[3] for v in run), []
            for _ in range(HEADING_RUN + 1):
                cand = [v for v in words if (v[1] + v[3]) / 2 > (top + foot) / 2 + h / 2 and v[1] <= foot + 1.5 * h
                        and v[0] >= x0 - 2 * h and (v[0] + v[2]) / 2 <= x1 + 3 * h]
                if not cand:
                    break
                first = min(v[1] for v in cand)
                row = sorted((v for v in cand if v[1] <= first + h / 2), key=lambda v: v[0])
                rows.append(row)
                top, foot = min(v[1] for v in row), max(v[3] for v in row)
            text = [(*v[:4], v[4] if re.search(r"\d", v[4]) else v[4].lstrip(".,:;'-") or v[4]) for v in run]
            for k, row in enumerate([[]] + rows[:HEADING_RUN]):
                text += row
                if not any(re.search(r"\d", v[4]) for v in text):
                    continue
                end = solution_at(text, 0, expected)
                if end is not None and not column_heading_like(text[:end[1] + 1], end[0]):
                    end = None
                if end is not None:
                    n, j = end
                    after = text[j + 1:] + (rows[k] if k < len(rows) else []) + (beyond if k == 0 else [])
                    if not any(DEFERRED.search(v[4]) for v in after):
                        found.append((n, box_of(text[:j + 1])))
                    elif deferred is not None:
                        deferred.add(n)
                    break
                if any(len(re.findall(r"\d", v[4])) >= 2 for v in text):
                    break  # its number read but none expected: no speck under it read on ("3.24" + "7": 3,747)
    return found


def column_heading_like(words, n):
    """Whether column_headings' joined heading `words` (up to its number, read as `n`) reads as one: a
    word like "Puzzle" or "Crossword" in it, and its number's digits all of `n`'s but one at most, not
    junk solution_at repairs ("Solution gto 4, (6" over a speck "6": 4,061, 1943-05-01)."""
    named = any(like(re.sub(r"[^a-z]", "", w[4].lower()), m) for w in words for m in ("puzzle", "crossword"))
    return named and len(re.findall(r"\d", "".join(w[4] for w in words))) >= len(str(n)) - 1


#: The 2007-14 Gale Times heading by the day: "Monday's Solution 23,792", "Wednesday's solution 24,105",
#: "Yesterday's solution 25,814" read glued ("Yesterday'ssolution25,814") or cut ("ay's", "terday's"):
#: a day's "...day's" (or its "ay's"), a "solution" word, its number read clean.
DAY_SOLUTION = re.compile(r"^\W*[A-Za-z]{0,7}?(?:day|ay)\W{0,2}s?\s*(s[o0]l[a-z]{3,6}?)\s*(\d{2}[,.]\d{3})(?![\d,.]?\d)",
                          re.IGNORECASE)


def named_day_headings(lines, expected):
    """[(number, box)] of the DAY_SOLUTION headings in `lines` whose "solution" word reads like one and
    whose number, read digit for digit, is one of `expected`: no repair (a misread of another number never
    stands for one). Paul 10-26: 6 unanswered 2007-14 Times puzzles' hosts read "Monday's Solution 23,792"
    (2007-12-26: the Christmas issue gap), "Wednesday's" or a glued "Yesterday'ssolution25,814", which
    YESTERDAY_SOLUTION (spaced, "yesterday" whole) misses. solutions_only's alone."""
    found = []
    for ln in lines:
        ws = split_words(ln)
        for k in range(len(ws)):
            for j in range(k, min(len(ws), k + 3)):
                m = DAY_SOLUTION.match(" ".join(v[4] for v in ws[k:j + 1]))
                if m and like(m[1].lower(), "solution") and number_of(m[2]) in expected:
                    found.append((number_of(m[2]), box_of(ws[k:j + 1])))
                    break
    return found


def only_current(row, paper, fh=None):
    """Whether ledger `row` holds a solutions_only read by this rule and
    scan code (of the files `fh`, when given)."""
    only = (row or {}).get("solOnly")
    return bool(only) and only.get("v") == SOLUTIONS_ONLY and only.get("scanKey") in current_keys(paper) \
        and not prize_rescan(paper, only.get("scanKey"), row.get("edition")) \
        and (fh is None or only.get("filesHash") == fh)


def scan_of(row, paper, fh=None):
    """The scan of ledger `row` the solution reads take: its own when it
    stands (scan code current, files `fh` when given); else its solutions_only
    read's solutions, over a stale scan's other fields; else the stale scan
    (None: neither). Used for solutions only: a solutions_only read finds no
    puzzle and never stands as the edition's scan (scan_current)."""
    scan = (row or {}).get("scan")
    if scan and row.get("scanKey") in current_keys(paper) and (fh is None or row.get("filesHash") == fh) \
            and not prize_rescan(paper, row.get("scanKey"), row.get("edition")):
        if only_current(row, paper, fh):  # a HOST_RESCAN's headings over a standing scan's
            have = {s["number"] for s in scan.get("solutions", ())}
            more = [s for s in row["solOnly"]["scan"]["solutions"] if s["number"] not in have]
            if more:
                return {**scan, "solutions": list(scan.get("solutions", ())) + more}
        return scan
    if only_current(row, paper, fh):
        # a failed stale scan has no "date": take the solutions_only read's
        return {**row["solOnly"]["scan"], **scan, "solutions": row["solOnly"]["scan"]["solutions"]} \
            if scan else row["solOnly"]["scan"]
    return scan


def scan_unit(paper, rel, cache=CACHE, ledger=None, host=False):
    """Scan one edition and add its row to the ledger (scan_queue.append),
    unless another unit holds it or its scan stands: "scanned", "busy",
    "current" or "held" (a run holds the ledger throughout). With `host` (a
    HOST_SCAN unit, wanted for the solutions it prints) a Gale page is read in
    its solution bands alone (solutions_only) and kept in the row's "solOnly",
    its "scan" left as it was: the edition's own scan, if due, still runs."""
    ledger = ledger_of(cache, paper, ledger)
    if scan_queue.held(ledger, scan_queue.UNIT_HOLD_WAIT):
        return "held"
    d = Path(cache) / rel
    with scan_queue.source_lock(ledger, rel) as mine:
        if not mine:
            return "busy"
        fh = input_hash(d)
        row = load_known(ledger).get(rel) or {}
        # A host due its solutions-only read once more (HOST_RESCAN) is read so whether its scan stands or not.
        due = host and host_rescan_due(paper_of(d), row)
        current = scan_current(row, fh, rel)
        if current and not due:
            return "current"
        if host:
            if only_current(row, paper, fh) and not due:
                return "current"
            try:
                found = solutions_only(d)
            except Exception as e:  # as below: the whole scan then runs and stands as one that raises
                if downloads.media_down(e):
                    raise  # the media share down: the unit ends deferred, no row kept
                progress(f"solutions-only read of {rel} failed, scanning whole: {scan_queue.failure((rel,), e)}")
                found = None
            if found is not None:
                progress(f"scanned {rel} for its solutions: {len(found['solutions'])} solution heading(s)")
                scan_queue.append(ledger, [{**row, "edition": rel, "solOnly": {
                    "v": SOLUTIONS_ONLY, "scanKey": scan_key(paper_of(d)), "filesHash": fh, "scan": found,
                    "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}}])
                return "scanned"
            if current:
                return "current"  # its scan stands: no whole scan for a host's solutions
        try:
            found = scan_anywhere(d)
        except Exception as e:  # any raise, as _run: a scan that raises stands as one with no headings
            if downloads.media_down(e):
                raise  # ... but not a page the media share did not serve: the unit ends deferred, no row kept
            found ={"puzzles": [], "solutions": [], "failed": scan_queue.failure((rel,), e)}
        progress(f"scanned {rel}: " + (f"failed: {found['failed']}" if "failed" in found
                                       else f"{len(found['puzzles'])} puzzle(s)"))
        scan_queue.append(ledger, [{**row, "edition": rel, "scan": found, "filesHash": fh,
                                    "scanKey": scan_key(paper_of(d))}])
        return "scanned"


def read_unit(paper, rel, cache=CACHE, ledger=None, puzzles=None, source=SOURCE, reread=None, force=False,
              out=sys.stdout, also=()):
    """Read one edition (its own scan made first if it is stale) and file
    what it holds, adding its row to the ledger, unless another unit holds
    it or it is no longer due (`force`: read it anyway): "read", "busy" or
    "held" (a run holds the ledger throughout). `also`: more editions read
    in the same process (the queue's batch of answers-linked rereads: the
    ledger, held lists, solution index and OCR models are set up once, not
    per edition); each is locked on its own and one another unit holds is
    left out. Each edition keeps its own ledger row and read line."""
    ledger = ledger_of(cache, paper, ledger)
    if scan_queue.held(ledger, scan_queue.UNIT_HOLD_WAIT):
        return "held"
    import contextlib
    with contextlib.ExitStack() as stack:
        mine = [r for r in dict.fromkeys([rel, *also]) if stack.enter_context(scan_queue.source_lock(ledger, r))]
        if not mine:
            return "busy"
        dirs = _PLANNED_DIRS.get((str(cache), paper.key))
        if dirs is not None:
            dirs = [*dirs, *(Path(cache) / r for r in mine if Path(cache) / r not in dirs)]
        _run(cache, True, ledger, out, puzzles, None, source, paper, None, 1, reread, editions=mine,
             unit={"force": force, "dirs": dirs})
        return "read"


def brief(paper, rel, cache=CACHE, ledger=None, puzzles=None, source=SOURCE, reread=None, force=False):
    """(desktop request header, its tar, the row's context) of read_unit's
    read, made here (the edition queue, its ledger, scans and corpus
    loaded) for tools/edition_commit.py's unit to send and commit; None when
    read_unit has to run: its scan is stale, or it is not due."""
    ledger = ledger_of(cache, paper, ledger)
    dirs = _PLANNED_DIRS.get((str(cache), paper.key))
    if dirs is None:
        # Before this process's first plan of the paper (a re-exec's first
        # minutes) the briefs share one listing a BRIEF_DIRS_FRESH window,
        # not one each (the interleave of every edition costs seconds).
        hit = _BRIEF_DIRS.get((str(cache), paper.key))
        if hit is None or time.monotonic() - hit[0] >= BRIEF_DIRS_FRESH:
            hit = _BRIEF_DIRS[(str(cache), paper.key)] = (time.monotonic(), edition_dirs(cache, paper))
        dirs = hit[1]
    if Path(cache) / rel not in dirs:
        dirs = [*dirs, Path(cache) / rel]
    with held_once():
        return _run(cache, False, ledger, None, puzzles, None, source, paper, None, 1, reread, editions=[rel],
                    unit={"force": force, "dirs": dirs, "brief": True})


#: {(cache, paper key): (when listed (monotonic), edition_dirs)} of brief's
#: listings made before a plan filled _PLANNED_DIRS, each trusted
#: BRIEF_DIRS_FRESH seconds (a unit's own edition is added regardless).
_BRIEF_DIRS = {}
BRIEF_DIRS_FRESH = 30


def _run(cache, write, ledger, out, puzzles, limit, source, paper, deadline, workers, reread, editions=None,
         scan_new=True, newer=None, unit=None):
    prepared = bool((unit or {}).get("brief"))
    # A row appended past here is one brief()'s unit looks for (edition_commit.read_since).
    ledger_size = ledger.stat().st_size if prepared and ledger.exists() else 0
    # brief() shares the queue's standing() rows (only lines appended since
    # parsed): it returns before any scan or read writes to known.
    known = _standing(ledger) if prepared else load_known(ledger)
    # A unit (read_unit) adds the rows it changed to the ledger; a run
    # holding the ledger's lock throughout rewrites it whole.
    changed = set()

    def flush():
        if not write:
            return
        if unit is not None:
            scan_queue.append(ledger, [known[k] for k in sorted(changed)])
        else:
            save(ledger, known)
        changed.clear()
    # The VLM's readings are an input: an edition read without it is read
    # again once it answers, and one read with it stands while it is down.
    seen_by = vlm.version() if vlm.reachable() else None
    dirs = (unit or {}).get("dirs") or edition_dirs(cache, paper)
    rels = {d: f"{d.parent.name}/{d.name}" for d in dirs}
    # With `newer`, only the editions laid out since then are read, and only
    # they and the days after them scanned.
    fresh = None if newer is None else {rels[d] for d in dirs if staged_at(d) >= newer}
    # Every heading first: a puzzle's solution is in a later edition.
    # With `editions`, only those and the days after them (where their
    # solutions print) are scanned afresh; every other edition's last scan
    # stands, stale or not, and one never scanned offers no solution.
    # A unit scans its own edition alone: the queue scans the others (scan_unit).
    near = ({d for d in dirs if rels[d] in editions} if unit is not None else
            scan_near(dirs, rels, editions or fresh) if editions or fresh is not None else None)
    scans, unscanned = {}, {}
    for d in dirs:
        row = known.get(rels[d])
        if near is not None and d not in near:
            scans[rels[d]] = scan_of(row, paper) or {"puzzles": [], "solutions": []}
            continue
        fh = input_hash(d)
        if scan_current(row, fh, rels[d]):
            scans[rels[d]] = row["scan"]
        else:
            unscanned[d] = fh
    if prepared and unscanned:
        return None
    # Without scan_new, an edition whose read waits on a scan is left for
    # the run that scans; every other edition's last scan stands.
    held_back = set()
    if not scan_new:
        held_back = unsettled(dirs, unscanned)
        for d in unscanned:
            scans[rels[d]] = scan_of(known.get(rels[d]), paper) or {"puzzles": [], "solutions": []}
        unscanned = {}
    # A scan that raises stands as one with no headings, kept under this
    # scan_key, so it is not made again until the scan code changes.
    saved = time.monotonic()
    for (d,), found in scan_queue.parallel([(d,) for d in unscanned], scan_anywhere, workers,
                                           failed=lambda item, error: {"puzzles": [], "solutions": [],
                                                                       "failed": error}):
        scans[rels[d]] = found
        progress(f"scanned {rels[d]}: " + (f"failed: {found['failed']}" if "failed" in found
                                           else f"{len(found['puzzles'])} puzzle(s)"))
        known[rels[d]] = {**known.get(rels[d], {}), "edition": rels[d], "scan": found, "filesHash": unscanned[d],
                          "scanKey": scan_key(paper_of(d))}
        changed.add(rels[d])
        # Saved as it goes: the scans of a whole paper take hours, and a kill
        # then loses at most SAVE_EVERY seconds of them.
        if time.monotonic() - saved >= SAVE_EVERY:
            flush()
            saved = time.monotonic()
    if unscanned:
        flush()
    solutions, sources = solution_sources(dirs, scans, rels, held_dates(paper.series),
                                          sister_solutions(cache, paper or TIMES))
    due = {}
    keep_vlm, held_ask = set(), set()
    for d in dirs:
        rel = rels[d]
        if editions and rel not in editions or d in held_back or fresh is not None and rel not in fresh:
            continue
        fh = known[rel]["filesHash"]
        h = inputs_of(fh, scans[rel], paper.series)
        sol_seen = sorted(n for n in (p["number"] for p in scans[rel]["puzzles"]) if n in solutions)
        why = due_reason(known[rel], h, sol_seen, seen_by, reread, sources)
        titled = held_titled(known[rel], cache) if why == HELD_TITLE else \
            held_titled(known[rel], cache, REREAD_HELD_STRIPS) if why == HELD_STRIPS else None
        if titled and why == HELD_STRIPS:
            held_ask.add(d.name)
        if titled:
            # Read under its held puzzle's title (held_titles), answers-only; the row keeps that scan, so
            # its titles and solutionsSeen stand as read.
            scans[rel] = titled
            h = inputs_of(fh, titled, paper.series)
            sol_seen = sorted(n for n in (p["number"] for p in titled["puzzles"]) if n in solutions)
        if why or editions and (unit is None or unit.get("force")):
            if keeps_vlm(why, known[rel], unit):
                keep_vlm.add(d.name)
            due[d] =(h, sol_seen, fh, reprint_key([p["number"] for p in scans[rel]["puzzles"]], paper.series))
        elif unit is not None:
            progress(f"not due {rel}: its scan stands as read, or it was read since it was queued")
    # Read only when something is due: a unit that finds nothing due ends here.
    held = held_numbers(paper.series) if due else set()
    _KEEP_VLM["names"] = keep_vlm
    _HELD_ASK["names"] = held_ask
    if due:
        held_dates(paper.series)  # read once here: the forked workers start with it
    keys = sorted(due, key=staged_at, reverse=True) if paper.key in NEWEST_FIRST else list(due)
    queue = scan_queue.order(keys, {d: known[rels[d]] for d in due}, lambda row: "inputs" not in row)
    if limit is not None:
        queue = queue[:limit]
    if prepared:
        if not queue:
            return None
        import ocr_remote
        d = queue[0]
        h, sol_seen, fh, read_with = due[d]
        found = scans[rels[d]]
        if any(p.get("heldTitle") for p in found["puzzles"]):
            return None  # answers-only here (read_edition): never the desktop's full read
        set_solutions(solutions, puzzles)
        head, tar = ocr_remote.edition_request(d, found, solutions)
        return head, tar, {
            "rel": rels[d], "ledger": str(ledger), "ledgerSize": ledger_size, "series": paper.series,
            "puzzles": puzzles and str(puzzles), "source": str(source), "crops": str(CROPS), "found": found,
            "filesHash": fh, "solutionsSeen": sol_seen, "scanKey": scan_key(paper_of(d)), "solutionKey": solution_key(),
            "vlmVersion": vlm.version(),
            "reprints": read_with}
    fresh, read_now = 0, set()
    for (d, found), (results, vlm_ok, *decided) in scan_queue.parallel(
            [(d, scans[rels[d]]) for d in queue], read_edition, workers, deadline,
            init=set_solutions, initargs=(solutions, puzzles), failed=edition_failed):
        rel = rels[d]
        h, sol_seen, fh, read_with = due[d]
        fresh += 1

        commit = edition_commit.writer(source, paper.series, puzzles)
        if decided and decided[0] is not None:
            # Decided on the desktop: only its writes are made here.
            verdicts = edition_commit.commit_decided(decided[0], commit if write else None)
        else:
            verdicts = []
            for verdict, puzzle in results:
                decide(verdict, puzzle, paper.series, puzzles, held, commit if write else None)
                verdicts.append(verdict)
        # Keyed by the inputs after this read's writes: a stray clue it
        # mended no longer makes the edition due.
        h = inputs_of(fh, found, paper.series, read_with)
        known[rel] = edition_commit.row(rel, h, found, fh, scan_key(paper_of(d)), sol_seen, verdicts, vlm_ok and seen_by,
                                        solution_key())
        changed.add(rel)
        read_now.add(rel)
        flush()
        progress(edition_commit.read_line(rel, verdicts))
    flush()
    # Only this run's verdicts: the ledger's lifetime totals reprinted old
    # refusals (long since fixed) after every read, reading as fresh errors.
    tally = report(known[rels[d]] for d in dirs if rels[d] in read_now)
    if len(due) > fresh:
        tally["left for the next run"] = len(due) - fresh
    print(f"{len(dirs)} {paper.key} editions in {cache}; {fresh} read this run"
          + (f"; {len(held_back)} wait on a scan" if held_back else ""), file=out)
    for k in sorted(tally):
        print(f"  {tally[k]:5d}  {k}", file=out)
    return list(known.values())


def decide(verdict, puzzle, series, puzzles, held, commit, path=filer_path):
    """Decide what one title's reading files, noting it on `verdict`, and
    make each write through `commit(where, puzzle, verdict)` (True when
    written; where None is the raw reading's source copy, else what
    `path(where, series, puzzles)` names): the held file mended, its answers
    merged, a better reading over it, or a new file. `held` is the series'
    filed numbers, a new file's added. `commit` None writes nothing."""
    hit_number = verdict["number"]
    if puzzle is None:
        return
    verdict["id"] = puzzle["id"]
    if commit is None:
        def commit(where, puzzle, verdict):
            return False
    held_at = ("held", puzzle["number"])
    held_path = path(held_at, series, puzzles)
    if verdict.get("solutionFrom") and not verdict.get("answersOnly"):
        # A full read's answers off another puzzle's grid (wrong_grid; answers_only refuses its own):
        # its clues may file, none of its answers.
        old = json.loads(held_path.read_text()) if held_path.exists() else {}
        other = wrong_grid(old.get("entries"), {entry_id(e): e.get("solution") for e in puzzle["entries"]},
                           series, puzzle["number"])
        if other:
            verdict["wrongGrid"] = other
            puzzle = copy.deepcopy(puzzle)
            for e in puzzle["entries"]:
                e["solution"] = None
    commit(None, puzzle, verdict)
    mended = mend_held(puzzle, held_path) if held_path.exists() else None
    # A reading drops no held answer it gives none for, but by a named rule (held_drops): its misread and
    # uncrossed filters left out reads, not the held answers (10-22..25: 312 Times files lost 986 held
    # answers so to answers-only rereads, times-7522 all 26 for a reading that took none). A full read's
    # answers take the same checks since 10-25 (full_read_answers), so it merges the same way: no reread
    # drop, a held answer going only by held_drops or a read answer crossing it on another letter.
    reread = False
    drop = held_drops(verdict)
    if mended is not None:
        verdict["mended"] = mended[1]
        answered = merge_answers(mended[0], puzzle, reread=reread, drop=drop)
        if answered:
            verdict["answered"] = answered
        commit(held_at, mended[0], verdict)
        return
    # An answers-only reading (answers_only) is the held file's own clues, already in the corpus: its
    # answers merge into the held file whatever complete() says of those clues. complete() also refuses
    # a clue with a word OCR made up (suspect), which answers_only does not check, so with --out such a
    # reading filed its answers to the --out copy and the held file never took one (10-25: 111 Times
    # files, 2,390 lights; times-18329's "...like an onion.-" kept 32 read answers out).
    dest = None if verdict.get("answersOnly") else destination(puzzles, complete(puzzle))
    if dest is False:
        verdict["skip"] = "a clue is blank: only a puzzle with every clue goes to the corpus"
        old = json.loads(held_path.read_text()) if held_path.exists() else None
        answered = old is not None and merge_answers(old, puzzle, reread=reread, drop=drop)
        if answered:
            verdict["answered"] = answered
            commit(held_at, old, verdict)
        return
    # A full reading not complete() (a clue blank or suspect) whose puzzle the corpus holds with every
    # clue: the held clues stand, and its answers are the held file's, not --out's. Only a blank held
    # light takes one, crossing no held letter on another (merge_answers keep): this reading's own
    # clues were short, and no held answer goes for it. Filed to --out, the held file never took one
    # (10-25: 227 Times grids, 3,825 answers read; held answers differing on 53 of them).
    old = json.loads(held_path.read_text()) if dest and held_path.exists() else None
    if old is not None and (old.get("source") or {}).get("acquiredBy") == TOOL \
            and filled(old)[0] == len(old.get("entries") or ()) > 0 \
            and trove_solution_ocr.puzzle_grid(old) == trove_solution_ocr.puzzle_grid(puzzle):
        verdict["heldWhole"] = True
        answered = merge_answers(old, puzzle, keep=True)
        if answered:
            verdict["answered"] = answered
            commit(held_at, old, verdict)
        return
    where = ("out", puzzle["id"]) if dest else held_at
    if dest:  # not complete(): it files to --out, not the corpus; the log line says so
        verdict["unfiled"] = len(puzzle["entries"]) - filled(puzzle)[0]
    target = path(where, series, puzzles)
    # An answers-only reading (answers_only) is the held file's own clues: merged, never laid over it.
    better = target.exists() and not verdict.get("answersOnly") and improves(puzzle, target)
    if better:
        kept = keep_held_clues(puzzle, json.loads(target.read_text()))
        if kept:
            verdict["heldClues"] = kept
    old = json.loads(target.read_text()) if target.exists() and not better else None
    # An answers-only reading drops no held answer it did not read again (reread above; a stale short read
    # of times-16268 would have dropped 11), complete() or not.
    answered = old is not None and merge_answers(old, puzzle, reread=reread, drop=drop)
    if answered:
        verdict["answered"] = answered
        commit(where, old, verdict)
    elif hit_number in held and not dest and not better:
        verdict["skip"] = "already held: the reading votes in cross_validate.py"
    elif (better or not target.exists()) and commit(where, puzzle, verdict):
        held.add(hit_number)


_SOLUTIONS = {}
#: Each process's {"puzzles": the run's --out}: where decide() files a
#: puzzle with a blank clue, which a desktop read decides there too.
_FILING = {"puzzles": None}


def set_solutions(solutions, puzzles=None):
    """Each process's {number: solution heading} (read_edition's) and the
    run's --out (_FILING)."""
    _SOLUTIONS.clear()
    _SOLUTIONS.update(solutions)
    _FILING["puzzles"] = puzzles and str(puzzles)


def read_edition(d, found):
    """([(verdict, puzzle or None)] for each title in an edition, whether the
    VLM still answers after it): read on the desktop when tools/ocr_remote.py
    can, the same reading as here. Read there, a third item is each title's
    decide() writes, decided there too (None: decide here)."""
    import ocr_remote
    # A held title (HELD_TITLE) is read answers-only here: the desktop's read would read the page in full.
    got = None if any(p.get("heldTitle") for p in found["puzzles"]) else ocr_remote.edition(d, found, _SOLUTIONS)
    if got is not None:
        return got
    results = []
    with ocr_remote.local_slot():
        for hit in found["puzzles"]:
            try:
                verdict, puzzle = read_puzzle(d, found, hit, _SOLUTIONS)
            except vlm.Down:
                raise  # the VLM down: the whole edition waits for it (vlm_reader.wanted)
            except Exception as e:  # any raise: one bad page is a verdict, not a crash
                if downloads.media_down(e):
                    raise  # the media share down: the edition is read again once it answers, no "crashed" kept
                verdict, puzzle = refuse({"number": hit["number"]}, "crashed",
                                         f"crashed: {type(e).__name__}: {e}"), None
            results.append((verdict, puzzle))
    return results, vlm.reachable()


def edition_failed(item, error):
    """read_edition's result for an edition whose read raised: each title
    refused, as read_edition refuses a title whose read raises."""
    _, found = item
    return [(refuse({"number": hit["number"]}, "crashed", f"crashed: {error}"), None)
            for hit in found["puzzles"]], False


def filled(puzzle):
    """(clues with text, answers) of a puzzle."""
    es = puzzle["entries"]
    return (sum(1 for e in es if ((e.get("clue") or {}).get("text") or "").strip()),
            sum(1 for e in es if e.get("solution")))


def improves(puzzle, path, tool=TOOL):
    """Whether `puzzle` should replace the file at `path`: one `tool`
    filed, on the same grid, that the new reading beats on clues or answers
    and loses on neither."""
    old = json.loads(path.read_text())
    if (old.get("source") or {}).get("acquiredBy") != tool \
            or trove_solution_ocr.puzzle_grid(old) != trove_solution_ocr.puzzle_grid(puzzle):
        return False
    def have(p, field):
        return {entry_id(e) for e in p["entries"]
                if field == "clue" and ((e.get("clue") or {}).get("text") or "").strip()
                or field == "solution" and e.get("solution")}
    # Nothing the file has may go blank: only a reading that keeps every
    # clue and answer and adds some replaces it.
    if not all(have(old, f) <= have(puzzle, f) for f in ("clue", "solution")):
        return False
    return filled(puzzle) != filled(old)


def keep_held_clues(puzzle, old):
    """[lights] whose held clue of `old` (this tool's, on this grid) `puzzle`
    takes back, in place, as a reading that improves() the file lays itself
    over it whole: a held clue with words (no shared, strayed or refused
    clue, nor one whose count the new reading changes) stays unless the new
    words correct() it. A reread's OCR with no VLM to pick lays the
    neighbouring print's words in a clue ("by For the fiddler"), which the
    held, validated words never had."""
    from fetch_puzzle import duplicated_clues
    if (old.get("source") or {}).get("acquiredBy") != TOOL \
            or trove_solution_ocr.puzzle_grid(old) != trove_solution_ocr.puzzle_grid(puzzle):
        return []
    lost = {i for ids in duplicated_clues(old["entries"]) for i in ids} | strayed(old, spaces=False) | set(faults(old))
    was = {entry_id(e): e for e in old["entries"]}
    kept = []
    for e in puzzle["entries"]:
        lid, h = entry_id(e), was.get(entry_id(e))
        held, now = (h or {}).get("clue") or {}, e.get("clue") or {}
        if h is None or lid in lost or not (held.get("text") or "").strip() or ocr_clues.bled(held["text"]):
            continue
        # A count that trades word breaks the answer bears out for other breaks
        # ("2,3,2,3,2" to "5,7"), a count no reader printed (countFrom "grid": the
        # light's length) over a held count with breaks ("4,2,3,6" to "15")
        # (count_slipped), or another clue's words over a whole held one ("See 25"
        # to "Cambridge Park, E 11 01-989"), is the reread's slip: the held clue
        # stands (tools/audit_updates.py's g:enum-structure and f:rewrite). A lone
        # count read off the print ("5,2" to "7") is the print's: it is taken.
        slipped = count_slipped(held, now, h.get("solution") or e.get("solution")) \
            or rewritten(held["text"], now.get("text"))
        if not slipped and (held.get("enumeration") != now.get("enumeration") or held.get("text") == now.get("text")):
            continue
        if not slipped and (now.get("text") or "").strip() \
                and corrects(held["text"], now["text"], now.get("asPrinted") or ()):
            continue
        e["clue"] = held
        if h.get("annotation"):
            e["annotation"] = h["annotation"]
        kept.append(lid)
    return kept


def mend_held(puzzle, path, tool=TOOL):
    """(the held file at `path` mended, {light: its clue now}), or None: each
    light the file gives a clue it gives another light too
    (fetch_puzzle.duplicated_clues), or a clue faults() refuses, takes this
    reading's clue for it, which one_light_each left on one light at most
    and unfit_blanked let stand. With none, a light on a shared clue or one
    holding another clue's or the page's text (ocr_clues.bled, which no
    write may keep) goes blank for the blank-clue re-read, and another
    refused clue stands: its words are all the corpus has of it
    (puzzle_integrity.check_rewrite). A light
    whose clue changes loses its annotation, written against the old words.
    A clue with a doubled word or a stray letter (strayed) is never kept:
    it takes this reading's clue, or goes blank.
    Any other held clue this reading corrects() takes its words
    (corrected_clues), unless the reading improves() the file and so
    replaces it whole.
    None when no clue changes, the file is not `tool`'s, or it lies on
    another grid than this reading. With no reading (`puzzle` None: its
    scan now reads as another number), only the shared clues go."""
    from fetch_puzzle import duplicated_clues
    old = json.loads(path.read_text())
    puzzle = puzzle or {"entries": []}
    if (old.get("source") or {}).get("acquiredBy") != tool \
            or puzzle["entries"] and trove_solution_ocr.puzzle_grid(old) != trove_solution_ocr.puzzle_grid(puzzle):
        return None
    shared = {i for ids in duplicated_clues(old["entries"]) for i in ids}
    # A held clue's run of spaces (edition_commit.spaced) is cut to one, and
    # its punctuation's certain mends made (punctuation.mend_puzzle), in
    # place, annotation and all: the words stand.
    before = {entry_id(e): copy.deepcopy(e) for e in old["entries"]}
    # A mend that leaves its clue one the write gate refuses as a new clue (a fault the certain mends
    # leave, "one . , owner" to "one , owner"; the page's text, "(7,.4) Original" to "(7, 4) Original")
    # is not made: the held words stand as they were, which the gate passes, for the re-read. Made, the
    # write was refused whole and its answers with it (10-25: 17 Times grids).
    collapsed = punctuation.unmend_refused(old, before, {**collapse_held_spaces(old), **punctuation.mend_puzzle(old)})
    stray = strayed(old, spaces=False)
    lost = shared | stray | set(faults(old))
    # A reading that improves() the file replaces it, its words and all.
    fixed = {} if not puzzle["entries"] or improves(puzzle, path, tool) else corrected_clues(puzzle, old, skip=lost)
    fixed = {**collapsed, **fixed}
    if not lost:
        return (old, fixed) if fixed else None
    now = {entry_id(e): e["clue"] for e in puzzle["entries"] if (e["clue"] or {}).get("text")}
    was = {entry_id(e): e.get("clue") for e in old["entries"]}
    blank = enumeration.clue("", missing=True)

    def fallback(lid):
        return blank if lid in shared | stray or ocr_clues.bled((was[lid] or {}).get("text")) else was[lid]
    for e in old["entries"]:
        if entry_id(e) in lost:
            e["clue"] = now.get(entry_id(e)) or fallback(entry_id(e))
    # This reading's clue for a lost light may be one the file keeps on
    # another: that light's falls back too.
    for ids in duplicated_clues(old["entries"]):
        for e in old["entries"]:
            if entry_id(e) in ids and entry_id(e) in lost:
                e["clue"] = fallback(entry_id(e))
    text = lambda clue: (clue or {}).get("text") or ""
    changed = {entry_id(e) for e in old["entries"]
               if entry_id(e) in lost and text(e["clue"]) != text(was[entry_id(e)])}
    if not changed:
        return (old, fixed) if fixed else None
    for e in old["entries"]:
        if entry_id(e) in changed:
            e.pop("annotation", None)
    return old, {**fixed, **{entry_id(e): text(e["clue"]) for e in old["entries"] if entry_id(e) in lost}}


def collapse_held_spaces(old):
    """{light: its clue now} after cutting each run of spaces in `old`'s
    clue texts to one (enumeration.collapse_entry_spaces), in place."""
    return {entry_id(e): e["clue"]["text"] for e in old.get("entries") or ()
            if enumeration.collapse_entry_spaces(e)}


def spaces_collapsed(was, now):
    """Whether `now` is the held `was` with its runs of spaces cut to one
    and nothing else changed (enumeration.collapse_spaces)."""
    return bool(was and now and now != was and enumeration.collapse_spaces(was)[0] == now)


#: A clue's words for corrects(): letters of any script ("Schönberg's"),
#: figures, and a word's "'s".
CLUE_TOKEN = re.compile(r"[^\W_]+(?:'[^\W_]+)?")
#: Symbols no clue gains from a re-read: a reader's specks ('"*inside').
SPECK_SYMBOLS = set("*~^|<>{}[]\\@#=+")


def lone_stops_dropped(was, now):
    """Whether `now` is `was` with one or more stops after a lone letter
    (ocr_clues.LONE_STOP) gone and nothing else changed: the vote's speck
    removal ("A. Frontier" to "A Frontier"), not a reader's marks."""
    lone = re.compile(ocr_clues.LONE_STOP)
    return lone.sub("", was) == lone.sub("", now) and len(lone.findall(was)) > len(lone.findall(now))


def mends(w, v, was):
    """Whether the held clue `was`'s token `w`, no word, reads `v` mended: a
    letter misread in a word ("Fudqe", "Aristic"), a figure misread digit
    for digit ("58" to "56"), a lone figure read for the letter it looks
    like ("3 state", not "£1"), or a speck glued to a word or figure
    ("2to", "E25"). A figure that loses or gains a digit ("1961" to "196")
    is no mend."""
    lw, lv = w.lower(), v.lower()
    if any(c.isdigit() for c in lw + lv):
        if lw.isdigit() and lv.isdigit():
            return len(lw) == len(lv) and ocr_clues.within_one(lw, lv)
        if lw.isdigit():
            return ocr_clues.digit_word(lw, lv) and not re.search(r"[£$€]\s*" + re.escape(w) + r"\b", was)
        return re.sub(r"\d", "", lw) == lv and ocr_clues.known(lv) or re.sub(r"\D", "", lw) == lv
    return not ocr_clues.known(lw) and ocr_clues.within_one(lw, lv) and ocr_clues.known(lv)


def inside(text, at):
    """Whether the token at `at` in `text` stands inside a sentence: not the
    clue's first, nor after a stop, query or exclamation."""
    return bool(text[:at].strip()) and text[:at].rstrip()[-1] not in ".?!"


#: A figure with its ordinal ending ("1st", "22nd"): a word of the print, not a figure with a speck.
ORDINAL = re.compile(r"\d+(?:st|nd|rd|th)$", re.I)


def regressions(was, now, printed=()):
    """[(kind, held token, new token)] where the clue text `now` reads worse
    than the held `was`, a word the print gave and the reread loses:
    "edge", a held word (or ordinal, "1st") whose new token is the same cut
    at its start or end ("1st" to "st", "heart" to "hear", "highly" to
    "ighly"); "nonword", a held lexicon word that becomes a token the
    lexicon does not know ("Humpty" to "Humply", "to" to "0") while the
    words around it stand. A token `printed` (its asPrinted) keeps is the
    print's."""
    seen = " ".join(printed or ()).lower()
    old_t = [m.group() for m in CLUE_TOKEN.finditer(was or "")]
    new_t = [m.group() for m in CLUE_TOKEN.finditer(now or "")]
    found = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, [w.lower() for w in old_t], [w.lower() for w in new_t],
                                              autojunk=False).get_opcodes():
        if op != "replace":
            continue
        gained = new_t[j1:j2]
        for k, a in enumerate(old_t[i1:i2]):
            la = a.lower()
            if not (ocr_clues.is_word(la) or ORDINAL.match(a)):
                continue
            # A word split in two ("bath-room", "be come") is not cut: its rest follows.
            # A word glued to its neighbour ("fora a" to "for a", "pre prehistoric" to "pre historic") is mended, not cut.
            after = old_t[i1 + k + 1].lower() if i1 + k + 1 < len(old_t) else None
            before = old_t[i1 + k - 1].lower() if i1 + k >= 1 else None
            hit = next((("edge", a, b) for b in gained if 0 < len(b) < len(a)
                        and (la.startswith(b.lower()) or la.endswith(b.lower()))
                        and la[len(b):] != after and la[:len(la) - len(b)] != before
                        and not any(ocr_clues.within_one(la, (b + c).lower()) or ocr_clues.within_one(la, (c + b).lower())
                                    for c in gained if c is not b)), None)
            if hit is None and len(gained) == i2 - i1 == 1 and not ocr_clues.is_word(gained[k].lower()) \
                    and la not in gained[k].lower():  # "Windblow" to "Windblown", "ret" to "Surete" add letters
                hit = ("nonword", a, gained[k])
            if hit and not (seen and re.search(r"\b" + re.escape(hit[2].lower()) + r"\b", seen)):
                found.append(hit)
    return found


#: Below this likeness (clue_text.likeness) a reading of a held clue is another clue's words.
REWRITE_LIKENESS = 0.5


def rewritten(was, now):
    """Whether the reading `now` of the held clue `was` is other words
    altogether (clue_text.likeness under REWRITE_LIKENESS): a reread laid
    another clue's or the page's text on the light ("Bill's relations" to
    "Virtue"). Neither blank."""
    return bool((was or "").strip() and (now or "").strip()) and clue_text.likeness(was, now) < REWRITE_LIKENESS


def grid_count_over(held, now):
    """Whether the clue `now` takes its count from the grid (no reader printed
    one) where the `held` clue's printed count has word breaks it drops."""
    return now.get("countFrom") == "grid" and held.get("countFrom") != "grid" \
        and enumeration.structure_lost(held.get("enumeration"), now.get("enumeration"))


def breaks_lost(was, now, answer):
    """Whether the enumeration `now` drops word breaks of the held `was`
    (enumeration.structure_lost) that the light's `answer` bears out
    (enumeration.answer_breaks), for other breaks: the reread took a
    neighbour's count ("2,3,2,3,2" over ONTHEUPANDUP to "5,7", The Times
    18,561). A lone count ("5,2" to "7") is no slip: the paper prints one
    over answers other puzzles break (CATCHUP "(7)", TIMEWORN "(8)",
    SHEEPSHEARING "(13)"), and the held breaks were the corpus's guess
    (fetch_puzzle.settled_breaks), not the print; a lone count no reader
    printed is grid_count_over's."""
    return len(enumeration.counts(now)) > 1 and enumeration.structure_lost(was, now) \
        and enumeration.answer_breaks(was, answer, ocr_clues.is_word)


def count_slipped(held, now, answer):
    """Whether the clue `now`'s count is a reread's slip over the `held`
    clue's (breaks_lost, grid_count_over): the held count stands."""
    return breaks_lost(held.get("enumeration"), now.get("enumeration"), answer) or grid_count_over(held, now)


def held_count(clue, held):
    """`clue` with the `held` clue's count, its marks and its countFrom."""
    clue = {k: v for k, v in clue.items() if k not in ("enumeration", "separators", "countFrom")}
    return {**clue, **{k: held[k] for k in ("enumeration", "separators", "countFrom") if k in held}}


def regressed(was, now, printed=()):
    """Whether the reread `now` loses print the held `was` read right
    (regressions): the held clue stays."""
    return bool(regressions(was, now, printed))


def corrects(was, now, printed=()):
    """Whether the clue text `now` may replace the held `was` as a better
    reading of the same print. `now` has words, none OCR made up
    (ocr_clues.suspect; a token `printed`, its asPrinted, keeps is the
    print's), bled, strayed or a speck symbol, and splits no held word over
    a hyphen ("Schö- berg's"). Each held word it lacks is no word that `now`
    mends (mends): a name inside the clue (a capital) only to a name the
    lexicon knows, never a dictionary word ("Mather" to "Mother"). Beyond
    those it gains one dictionary word at most (a lost "A"), and not:
    a lone "I" (a speck read as one); a capital inside the clue; a short
    word hyphened to its neighbour ("source-of"); a fragment of its
    longer neighbour ("consumer sumer", "be-between", "corn conversely");
    a word of four letters or more the clue has already; an opening word
    before the held clue's capital ("Is Be responsible", a misread
    number), save the article "A"; nor a word the corpus's clues never
    print beside either neighbour ("have oil cut", "Vera bit Pam"); the
    article "A" goes before any word, so it needs no such pairing.
    "Frontier cantonment." to "A Frontier cantonment." does; so
    does a change that only drops a stop after a lone letter
    (lone_stops_dropped), only cuts a run of spaces to one
    (spaces_collapsed), or only makes punctuation's certain mends
    (punctuation.mended: "by.clever" to "by clever"); one that breaks a
    punctuation rule (punctuation.faults) does not. A reading that loses a real word, swaps one,
    reorders them, or changes other marks only (a held file's quotes are
    straightened, its specks cleaned) does not; nor does one that
    regressed() a held word: a lexicon word turned to a non-word, or a word
    cut at its edge ("1st" to "st", "heart" to "hear")."""
    if not (was or "").strip() or not ocr_clues.tokens(now or "") or now == was:
        return False
    if regressed(was, now, printed):
        return False
    # A glitch only a reader makes that the held clue lacks: page furniture, a
    # line-end hyphen with a page number, "E25", "2A", an unpaired quote, "1 would",
    # the count left in the text (clue_text.REFUSED_GLITCHES; tools/audit_updates.py).
    if clue_text.gains_glitch(was, now):
        return False
    if spaces_collapsed(was, now) or punctuation.mended(was) == now:
        return True
    if ocr_clues.suspect(now, printed=printed) or ocr_clues.bled(now, printed) or ocr_clues.stray(now) \
            or punctuation.faults(now):
        return False
    if set(now) & SPECK_SYMBOLS - set(was):
        return False
    # A lone "&" the held clue lacks is a scan's "a" or a speck, never a re-read's gain
    # ("Lone wolf unimpeded by a weapon" to "... by & a weapon", times-12467).
    if now.split().count("&") > was.split().count("&"):
        return False
    old_t, new_t = list(CLUE_TOKEN.finditer(was)), list(CLUE_TOKEN.finditer(now))
    old, new = [m.group().lower() for m in old_t], [m.group().lower() for m in new_t]
    if old == new:
        return lone_stops_dropped(was, now)
    for m in re.finditer(r"([^\W\d_]+)-\s+([^\W\d_]+)", now):
        if any(ocr_clues.within_one((m[1] + m[2]).lower(), w) for w in old):
            return False
    gone, gained = [], []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op != "equal":
            gone += range(i1, i2)
            gained += range(j1, j2)
    for i in gone:
        w = old_t[i].group()
        name = w[:1].isupper() and inside(was, old_t[i].start())
        fix = next((j for j in gained if mends(w, new_t[j].group(), was)
                    and not (name and ocr_clues.is_word(new[j]))), None)
        if fix is None:
            return False
        gained.remove(fix)
    if len(gained) > 1:
        return False
    _, pairs, _ = ocr_clues.clue_lm()
    for j in gained:
        v, tok = new[j], new_t[j]
        if not ocr_clues.is_word(v) or v == "i" or tok.group()[:1].isupper() and inside(now, tok.start()):
            return False
        near = [(k, new[k]) for k in (j - 1, j + 1) if 0 <= k < len(new)]
        for k, u in near:
            glue = now[min(tok.end(), new_t[k].end()):max(tok.start(), new_t[k].start())]
            if len(v) <= 2 and "-" in glue:
                return False
            if len(u) > len(v) >= 2 and (u.startswith(v) or u.endswith(v) or len(v) >= 4 and any(
                    sum(a != b for a, b in zip(v, end)) == 1 for end in (u[:len(v)], u[-len(v):]))):
                return False
        if len(v) >= 4 and v in old:
            return False
        if j == 0 and v != "a" and len(new) > 1 and new_t[1].group()[:1].isupper():
            return False
        if v != "a" and not any(pairs.get(f"{a} {b}") for a, b in [(u, v) if k < j else (v, u) for k, u in near]):
            return False
    return True


def count_dropped(was, now, cells, lights, printed=()):
    """Whether `now` reads the held `was` with its misread count dropped
    (count_left), the rest as corrects() lets a reading change it: the
    re-read's vote cut those figures (ocr_clues.agree), the grid says they
    fill the light."""
    bare = count_left(was, cells, lights)
    if bare is None or not ocr_clues.tokens(bare):
        return False
    return now.strip() == bare and not ocr_clues.suspect(now, printed=printed) or corrects(bare, now, printed)


def corrected_clues(puzzle, old, skip=()):
    """{light: its clue now} after taking `puzzle`'s reading of each held
    clue of `old` (in place) that corrects() it: a reader's fix to a clue's
    words reaching a file already held. A light in `skip`, one annotated
    (the annotation was written against the held words), one a
    source_clue_wrong or setter_error row names (keyed to the held words),
    and one whose new words another light of its list holds are left as
    they are. A clue whose marks alone change is taken when they are a
    book reprint's (book_marked): the held file's words with the book's
    marks. A held count is mended even where the words stand
    (book_counted). The caller has checked the two lie on one grid."""
    from fetch_puzzle import SOURCE_CLUE_WRONG, duplicated_clues, load_source_table
    rows = set(SOURCE_CLUE_WRONG) | set(load_source_table("setter_error"))
    # reprint_readings, not book_readings: a read on the desktop is handed
    # the edition's reprints in its request (ocr_remote).
    books = book_clues(reprint_readings(old["number"], series_meta.of(old))) if old.get("number") and series_meta.of(old) else {}
    now = {entry_id(e): e["clue"] for e in puzzle["entries"] if (e.get("clue") or {}).get("text")}
    fixed, lights = {}, {e["number"] for e in old["entries"]}
    for e in old["entries"]:
        lid, was = entry_id(e), e.get("clue") or {}
        if lid in skip or lid not in now or e.get("annotation") or (old.get("id"), lid) in rows \
                or not (corrects(was.get("text"), now[lid]["text"], now[lid].get("asPrinted") or ())
                        or book_marks(was.get("text"), now[lid]["text"], (books.get(lid) or (None,))[0])
                        or count_dropped(was.get("text"), now[lid]["text"], e.get("length"),
                                         lights, now[lid].get("asPrinted") or ())):
            continue
        clue = {**now[lid]}
        # A count that lost word breaks the answer bears out to other breaks, or a
        # grid's count over a printed one (count_slipped), keeps the held one's.
        if "enumeration" in was and ("enumeration" not in clue or count_slipped(was, clue, e.get("solution"))):
            clue = held_count(clue, was)
        e["clue"] = clue
        if any(lid in ids for ids in duplicated_clues(old["entries"], one_list=True)):
            e["clue"] = was
            continue
        fixed[lid] = clue["text"]
    for lid in book_counted(old, books, skip=skip):
        fixed.setdefault(lid, (by_light(old).get(lid, {}).get("clue") or {}).get("text") or "")
    return fixed


def by_light(puzzle):
    return {entry_id(e): e for e in puzzle.get("entries") or ()}


def book_counted(old, books, skip=()):
    """The lights of the held `old` whose enumeration this changes, in
    place, with its separators: a ";" whose counts fill the light read as
    the "," it is (enumeration.comma_misread, times-15602 7D's "6;3"), and
    a bare count the book's reprint (`books`, book_clues) prints with its
    marks at the same total (ocr_clues.reprint_count, "9" for "5,4"). The
    clue's words need not change: a held file's count is mended alone.
    A light in `skip`, or whose new count its lights cannot hold, stays."""
    lights, out = by_light(old), []
    for e in old.get("entries") or ():
        lid, clue = entry_id(e), e.get("clue") if isinstance(e.get("clue"), dict) else None
        if lid in skip or not clue or not clue.get("enumeration"):
            continue
        group = [g for g in e.get("group") or [lid] if g in lights]
        was = clue["enumeration"]
        now = enumeration.comma_misread(was, sum(lights[g]["length"] for g in group))
        now = ocr_clues.reprint_count(now, (books.get(lid) or (None, None))[1])
        if now == was:
            continue
        try:
            seps = separators(group, lights, now)
        except SystemExit:
            continue
        clue["enumeration"] = now
        for g in group:
            target = lights[g].get("clue") if isinstance(lights[g].get("clue"), dict) else None
            if target is None:
                continue
            if seps.get(g):
                target["separators"] = seps[g]
            else:
                target.pop("separators", None)
        out.append(lid)
    return out


def book_marks(was, now, book):
    """Whether `now` is the held clue `was` with the marks a book's reprint
    of it prints (`book`; ocr_clues.reprint_marked) and nothing else."""
    return bool(was and book and now != was and ocr_clues.reprint_marked(was, book) == now)


def held_drops(verdict):
    """The held lights an answers-only `verdict` blanks by a named rule though it reads no answer
    there: heldMisread (the grid read the held word alike, a misread_word) and each heldClash light
    settle_held "dropped" (neither its held nor its read answer filed). Every other held answer it
    gives none for stands (merge_answers with no reread drop)."""
    sol = verdict.get("solution") or {}
    return set(sol.get("heldMisread") or ()) | {k for k, c in (sol.get("heldClash") or {}).items() if c.get("took") == "dropped"}


def merge_answers(old, puzzle, tool=TOOL, reread=False, keep=False, drop=()):
    """{light: its answer now (None: dropped)} after taking `puzzle`'s
    answers into the held filing `old` (in place): each light this reading
    answers takes its answer, and a held answer a new one crosses on
    another letter is dropped; with `reread` (this reading read the
    solution grid) so is every held answer it did not read again, the
    older reader's sure reads having filed wrong ones (BAYED for DATED).
    With `keep`, no held answer changes or goes: only a blank light takes
    this reading's answer, and only one that crosses no held letter on
    another (_fill_writeup_blanks). Each light of `drop` (held_drops: an
    answers-only reading's named rules) this reading does not answer goes
    too. A light whose answer changes loses its
    annotation, written against the old answer. {} when `old` is not
    `tool`'s or lies on another grid."""
    if (old.get("source") or {}).get("acquiredBy") != tool \
            or trove_solution_ocr.puzzle_grid(old) != trove_solution_ocr.puzzle_grid(puzzle):
        return {}
    def cells(e):
        x, y, across = e["position"]["x"], e["position"]["y"], e["direction"] == "across"
        return [(x + i * across, y + i * (not across)) for i in range(e["length"])]
    new = {entry_id(e): e["solution"] for e in puzzle["entries"] if e.get("solution")}
    letters = {rc: ch for e in puzzle["entries"] if e.get("solution") for rc, ch in zip(cells(e), e["solution"])}
    if keep or "blog" in (old.get("solutions") or {}):
        return _fill_writeup_blanks(old, new, cells)
    changed = {}
    for e in old["entries"]:
        lid, was = entry_id(e), e.get("solution")
        now = new.get(lid, was)
        if lid not in new and was and (reread or lid in drop or any(letters.get(rc, ch) != ch for rc, ch in zip(cells(e), was))):
            now = None
        if now != was:
            e["solution"] = now
            e.pop("annotation", None)
            changed[lid] = now
    return changed


def _fill_writeup_blanks(old, new, cells):
    """merge_answers for a file a blog's write-up keyed (solutions.blog): the
    blog's answers stand as printed, never dropped or changed by a reading
    of the paper's grid; only a blank light takes the grid's answer, unless
    it crosses a held letter on another one. solutions.partial then lists
    only the lights still blank (the key goes when none is)."""
    held = {}
    for e in old["entries"]:
        if e.get("solution"):
            held.update(zip(cells(e), e["solution"]))
    changed = {}
    for e in old["entries"]:
        lid, a = entry_id(e), new.get(entry_id(e))
        if e.get("solution") or not a or len(a) != e["length"] \
                or any(held.get(rc, ch) != ch for rc, ch in zip(cells(e), a)):
            continue
        e["solution"] = a
        held.update(zip(cells(e), a))
        e.pop("annotation", None)
        changed[lid] = a
    solutions = old["solutions"]
    if changed and isinstance(solutions.get("partial"), list):
        blank = {entry_id(e) for e in old["entries"] if not (e.get("solution") or "").strip()}
        left = [i for i in solutions["partial"] if i in blank]
        if left:
            solutions["partial"] = left
        else:
            del solutions["partial"]
    return changed


def solution_read(verdict):
    """Whether a title's read took its answers off its solution grid."""
    return "solution" in verdict and "refused" not in verdict["solution"]


def save(ledger, known):
    ledger.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in known.values()))
    tmp.replace(ledger)
    scan_queue.stamp(ledger)


# ------------------------------------------------------------ the Canberra reprints

#: match_canberra's view of each Times reading in SOURCE, on the SSD:
#: {"key": file name, "at": its archiveorg-source row's, "id", "date",
#: "shingles", "grid"} a line, rewritten whole when one moved.
READINGS_STORE = "archiveorg-source-shingles.jsonl"


def source_readings(source=SOURCE):
    """{file name: {"id", "date", "shingles": set, "grid"}} of each Times
    reading (times-*.json) in `source`. On the media disk, its files come off
    the archiveorg-source manifest (edition_commit appends a row as it writes
    one) and only a file whose row moved since the SSD store (READINGS_STORE)
    is opened, so a pass lists and opens nothing it read before."""
    if not media_manifest.on_media(source):
        return _source_readings_listed(source)
    files = media_manifest.folder_files("archiveorg-source", source, "times-*.json")
    store = media_manifest.DIR / READINGS_STORE
    held = {}
    try:
        for ln in store.read_text().splitlines():
            r = json.loads(ln)
            held[r["key"]] = r
    except (FileNotFoundError, ValueError):
        held = {}
    out, moved = {}, False
    for name, row in files.items():
        r = held.get(name)
        if r is None or r.get("at") != row.get("at"):
            r = {"key": name, "at": row.get("at"), **_reading_of(json.loads((Path(source) / name).read_text()))}
            moved = True
        out[name] = r
    if moved or len(out) != len(held):
        tmp = store.with_name(f".{store.name}.{os.getpid()}.tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in out.values()))
        os.replace(tmp, store)
    return {name: {**r, "shingles": set(r["shingles"])} for name, r in out.items()}


def _reading_of(r):
    """source_readings' row of the Times reading `r` ("grid" None when it lays none out)."""
    try:
        grid = trove_solution_ocr.puzzle_grid(r)
    except (KeyError, IndexError, TypeError):
        grid = None
    return {"id": r["id"], "date": r["date"], "shingles": sorted(shingles(r)), "grid": grid}


def _source_readings_listed(source):
    """source_readings of a folder off the media disk (a test's), globbed and read whole."""
    return {p.name: {**_reading_of(r := json.loads(p.read_text())), "shingles": shingles(r)}
            for p in sorted(Path(source).glob("times-*.json"))}


def shingles(puzzle):
    """The word triples of a puzzle's clues: what two OCR'd copies of one
    clue list share even where each misreads a word or two."""
    out = set()
    for e in puzzle["entries"]:
        w = re.findall(r"[a-z]+", ((e.get("clue") or {}).get("text") or "").lower())
        out |= {" ".join(w[k:k + 3]) for k in range(len(w) - 2)}
    return out


#: The share of the smaller copy's word triples the two must share, and how
#: far the best match must lead the next.
MATCH_SHARE = 0.3
MATCH_LEAD = 2.0


def match_canberra(source=SOURCE, write=True, out=sys.stdout, canberra=ROOT / "puzzles" / "canberra"):
    """Name the Times puzzle each canberra file reprints: the archive.org
    reading sharing the most clue word triples, when it shares at least
    MATCH_SHARE of them, leads the runner-up MATCH_LEAD times over, was
    printed in London first, and the grids are the same. Returns
    {canberra id: times id}."""
    import puzzle_integrity  # it imports the write path, so not at the top
    from fetch_puzzle import read_puzzle_file, write_puzzle_file
    readings, index = {}, {}
    for r in source_readings(source).values():
        readings[r["id"]] = r
        for sh in r["shingles"]:
            index.setdefault(sh, set()).add(r["id"])
    found = {}
    for path in sorted(canberra.glob("*/*.json")):
        c = read_puzzle_file(path)
        mine = shingles(c)
        if len(mine) < 20:
            continue
        hits = {}
        for sh in mine:
            for tid in index.get(sh, ()):
                hits[tid] = hits.get(tid, 0) + 1
        ranked = sorted(hits.items(), key=lambda kv: -kv[1])
        if not ranked:
            continue
        tid, n = ranked[0]
        r = readings[tid]
        share = n / min(len(mine), len(r["shingles"]) or 1)
        lead = n / ranked[1][1] if len(ranked) > 1 else float("inf")
        same_grid = trove_solution_ocr.puzzle_grid(c) == r["grid"]
        if share < MATCH_SHARE or lead < MATCH_LEAD or r["date"] > c["date"] or not same_grid:
            continue
        found[c["id"]] = tid
        print(f"{c['id']} reprints {tid}: {n} clue word triples shared ({share:.0%})", file=out)
        if write and (c.get("source") or {}).get("reprintOf") != tid:
            c["source"] = {**c["source"], "reprintOf": tid}
            # A reprint outside reprints_pending.json is refused
            # (puzzle_integrity.check_reprint): it waits for its fold.
            try:
                write_puzzle_file(path, c)
            except puzzle_integrity.RefusedWrite as e:
                print(f"{c['id']}: skipped, {e}", file=out)
    print(f"{len(found)} canberra files matched to a Times reading", file=out)
    return found


def report(rows):
    tally = {}

    def add(k, n=1):
        tally[k] = tally.get(k, 0) + n
    for row in rows:
        for v in row.get("verdicts", ()):
            add("puzzles found")
            if v.get("complete"):
                add("clue lists complete")
            if v.get("grid"):
                add(f"grid {v['grid']}")
            if v.get("id"):
                add("puzzles read")
                add("answers read", v.get("answers", 0))
                add("clues blank (readings disagree)", len(v.get("blank", {})))
            if v.get("wrote"):
                add("written")
            if v.get("refusedWrite"):
                add("write refused")
            if v.get("writeFailed"):
                add(f"write failed: {v['writeFailed'].split(':')[0][:50]}")
            for k in ("refused", "pending"):
                if v.get(k):
                    add(f"{k}: {v[k].split(':')[0][:50]}")
    return tally


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--ledger", type=Path, help="default <cache>/filed.jsonl (--paper gale: filed-gale.jsonl)")
    ap.add_argument("--out", type=Path,
                    help="write puzzles with a blank clue here; complete ones still go into puzzles/")
    ap.add_argument("--source", type=Path, default=SOURCE,
                    help="where every reading goes for cross_validate.py")
    ap.add_argument("--limit", type=int, help="read at most N new or changed editions")
    ap.add_argument("--seconds", type=float,
                    help="start no edition after N seconds; the rest wait for the next run")
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help=f"editions read at once (default {WORKERS}): one's VLM wait overlaps another's OCR")
    ap.add_argument("--wait", action="store_true",
                    help="wait for another run's hold on the ledger instead of reading nothing")
    ap.add_argument("--reread", nargs="?", const="now", metavar="BEFORE",
                    help="read again every edition last read before BEFORE (an ISO time; default now): "
                         "the one-off after a change to this code or the VLM model, which alone makes nothing due")
    ap.add_argument("--edition", action="append", metavar="ITEM/EDITION",
                    help="read this edition again, and no other (repeatable)")
    ap.add_argument("--mend-held", nargs="+", metavar="ID",
                    help="blank each clue these held filings give two lights, with no reading")
    ap.add_argument("--newer-than", type=float, metavar="SECONDS",
                    help="read only the due editions laid out in the last SECONDS (a Gale page just saved)")
    ap.add_argument("--no-scan", action="store_true",
                    help="scan nothing; read only the due editions whose scans, and those of the days after "
                         "them, stand")
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    ap.add_argument("--show", metavar="ITEM/EDITION", help="one edition's verdicts")
    ap.add_argument("--paper", choices=sorted(FILERS), default="times",
                    help="whose editions to file: the Times (times-N), the FT (ftcryptic-N), the Guardian "
                         "(cryptic-N), the Telegraph (telegraph-N) or the Times pages saved from Gale (gale)")
    ap.add_argument("--check-filed", action="store_true",
                    help="list every puzzle this tool filed with a clue it would refuse now; write nothing")
    ap.add_argument("--match-canberra", action="store_true",
                    help="only name the Times puzzle each canberra file reprints")
    args = ap.parse_args(argv)
    if args.check_filed:
        return 1 if check_filed() else 0
    if args.match_canberra:
        match_canberra(args.source, write=not args.dry_run)
        return 0
    if args.mend_held:
        from fetch_puzzle import puzzle_paths, write_puzzle_file
        for pid in args.mend_held:
            path = puzzle_paths.find(pid)
            mended = path and mend_held(None, path)
            print(pid, mended[1] if mended else "nothing to mend")
            if mended and not args.dry_run:
                write_puzzle_file(path, mended[0], generator=TOOL)
        return 0
    if args.show:
        d = args.cache / args.show
        found = scan(d)
        sols = {}
        for e in edition_dirs(args.cache, paper_of(d)):
            for s in scan(e)["solutions"] if e.parent == d.parent else ():
                sols.setdefault(s["number"], {**s, "dir": e})
        for hit in found["puzzles"]:
            verdict, puzzle = read_puzzle(d, found, hit, sols)
            print(json.dumps(verdict, indent=1))
            if puzzle:
                for e in puzzle["entries"]:
                    print(f"  {e['number']:2d}{e['direction'][0]} {e.get('solution') or '-':15s} "
                          f"{(e['clue'] or {}).get('text', '')} ({(e['clue'] or {}).get('enumeration')})")
        return 0
    run(args.cache, write=not args.dry_run, ledger=args.ledger, puzzles=args.out,
        limit=args.limit, source=args.source, paper=FILERS[args.paper], seconds=args.seconds,
        workers=args.workers, wait=args.wait, reread=scan_queue.when(args.reread), editions=args.edition,
        scan_new=not args.no_scan, newer=None if args.newer_than is None else time.time() - args.newer_than)
    if FILERS[args.paper].series == SERIES:
        match_canberra(args.source, write=not args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
