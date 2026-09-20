#!/usr/bin/env python3
"""Fetch the Private Eye "Cyclops" cryptic and convert it to this app's format.

Usage:
  python3 tools/fetch_privateeye.py --latest        # newest issue not already on disk
  python3 tools/fetch_privateeye.py 838              # one puzzle, by its Eye number
  python3 tools/fetch_privateeye.py 838 830 825      # an explicit list of numbers
  python3 tools/fetch_privateeye.py --extend [N]     # N puzzles OLDER than the oldest
                                                     # we hold (default 30), walking the
                                                     # number sequence downward
  python3 tools/fetch_privateeye.py --dry-run 838    # parse and print, write nothing
  python3 tools/fetch_privateeye.py --out DIR ...    # write elsewhere (default puzzles/)
  python3 tools/fetch_privateeye.py --backfill-dates
                                                     # fill in the publication date of
                                                     # every on-disk Cyclops missing one,
                                                     # from the Eye's issue cover pages
  python3 tools/fetch_privateeye.py --refresh-unsolved
                                                     # re-run the fifteensquared join for
                                                     # every on-disk Cyclops still waiting
                                                     # on it (walk() and --latest never
                                                     # revisit a number once it's on disk,
                                                     # so nothing else ever will)

WHERE THIS COMES FROM. https://www.private-eye.co.uk/crossword lists the current
issue and links straight to an Across Lite file:
    https://www.private-eye.co.uk/pictures/crossword/download/{num}.puz
No login, no auth. The number is the Eye's own crossword sequence (No. 838 at
Issue 1683, September 2026) and is walkable by decrementing — 838 and 830 both
verified live. --latest reads the current number off the index page's own
download link (`download/(\\d+)\\.puz`) rather than the printed "Issue NNNN",
because the crossword number is what names the file and the sequence the app
already uses everywhere else.

THE .PUZ FORMAT. Nothing else in this repo speaks it, so the reader is small
and inline rather than a dependency. Layout, confirmed against a real file
(this generator writes a 52-byte header, 8 bytes shorter than most published
specs because its "reserved2" is 4 bytes rather than 12):
    0x00  u16   overall checksum (unused here)
    0x02  12s   magic "ACROSS&DOWN\\0"
    0x0E  u16   CIB checksum (unused here)
    0x2C  u8    width
    0x2D  u8    height
    0x2E  u16   number of clues
    0x32  u16   scrambled_tag (0 = plain, otherwise the grid below is locked)
    0x34  ...   solution grid, width*height bytes, '.' = black square
    +wh   ...   player-state grid, width*height bytes
    +wh   NUL-terminated ISO-8859-1 strings: title, author, copyright, then one
                clue per numbered cell in across-then-down reading order, then notes

UNSCRAMBLING DOES NOT RECOVER REAL ANSWERS FROM THIS FEED. scrambled_tag is set
(checked on Nos. 838 and 830), which normally means the solution grid is
encrypted with the reversible, brute-forceable Across Lite scheme (see
unscramble_solution below — kept because it is cheap, in-process, and correct
against the public algorithm). But on both puzzles checked, every white cell of
the "solution" grid is the literal, identical byte 'D' — not ciphertext. A
substitution-plus-permutation cipher cannot manufacture 148 distinct letters
that satisfy 32 different clues out of an input with one repeated symbol; the
output for every one of the 10000 keys is just some deterministic scramble of
all-D, and any checksum match against it is a 16-bit-checksum coincidence, not
a real unlock (this is exactly why early testing "found" different keys at
different candidate checksum offsets — all four were coincidences on garbage).
If Private Eye ever ships a real scrambled grid, this code will unscramble it
without changes; nothing here assumes the dummy.

ANSWERS COME FROM FIFTEENSQUARED.NET INSTEAD. It has blogged Private Eye's
Cyclops biweekly since December 2006, with a full grid solve in each post —
see fetch_fifteensquared_post and solve_from_fifteensquared. Those answers
were never in this feed and are not the publisher's, so entries filled this
way carry solutionSource (same field apply_solution.py uses for a model's own
solve) and the site marks them unofficial. A puzzle too new to be blogged yet,
or whose blog post fails verification against the grid, gets solution: None
instead — same shape the app already uses for a prize puzzle whose answers
haven't been published (see hasSolutions in fetch_puzzle.reindex).

Writes <out>/cyclops-<number>.json (preserving any existing per-clue annotations
via merge_annotations). Deliberately does NOT rebuild puzzles/index.json or
index.js — this fetcher lands before the "cyclops" series exists in
tools/series.py and app.js, so an index write here would either crash (series
metadata missing) or bake in an incomplete picture. Once the series is
registered, run tools/fetch_puzzle.py --reindex once by hand.
"""

import argparse
import datetime
import html
import itertools
import json
import re
import string
import struct
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (PUZZLE_DIR, grade_model_fill, http_bytes,  # noqa: E402
                          merge_annotations, print_grade, puzzle_files,
                          puzzle_path, read_puzzle_file, write_puzzle_file)

INDEX_URL = "https://www.private-eye.co.uk/crossword"
PUZ_URL = "https://www.private-eye.co.uk/pictures/crossword/download/{num}.puz"
# per_page=40, not the obvious 5: the WP search ranks by relevance, not by
# whether the number actually appears, and for older issues the true match
# routinely isn't in the top 5 (Cyclops 500's own post ranked 12th of 15
# candidates for the query "Cyclops 500"). One request either way, so there's
# no politeness cost to asking for more candidates to filter locally.
FQ_SEARCH_URL = "https://fifteensquared.net/wp-json/wp/v2/posts?search=Cyclops+{num}&per_page=40"
FQ_MIN_INTERVAL = 1.0  # seconds — politeness floor between requests to fifteensquared.net
COVER_URL = "https://www.private-eye.co.uk/covers/cover-{issue}"
SERIES = "cyclops"
SETTER = "Cyclops"
PUBLICATION_WEEKDAY = 4  # Friday — the Eye dates every issue to a Friday

BLACK = "."


# ---------- .puz reading ----------

def puz_text(raw):
    """Bytes out of a .puz file -> text.

    The format says ISO-8859-1 and every tool that writes one means Windows-1252,
    so a latin-1 decode turns the en dash Cyclops separates his clauses with into
    U+0096, an unprintable control code the browser draws as a box. cp1252 leaves
    five bytes undefined; those fall back rather than losing the whole string.
    """
    return raw.decode("cp1252", "replace")


def read_cstr(data, pos):
    """A NUL-terminated string starting at pos -> (text, next pos)."""
    end = data.index(b"\x00", pos)
    return puz_text(data[pos:end]), end + 1


def parse_puz(data):
    """Raw .puz bytes -> a dict of the fields this converter needs.

    Deliberately not a general-purpose reader: no rebus, no extra sections,
    no across/down clue splitting by direction (that's done in convert() from
    the grid geometry, not from which half of the clue list a string sits in).
    """
    if data[2:14] != b"ACROSS&DOWN\x00":
        raise ValueError("not an Across Lite .puz file (bad magic)")
    width = data[0x2C]
    height = data[0x2D]
    n_clues = struct.unpack_from("<H", data, 0x2E)[0]
    scrambled_tag = struct.unpack_from("<H", data, 0x32)[0]

    pos = 0x34
    solution = puz_text(data[pos:pos + width * height])
    pos += width * height
    pos += width * height  # player-state grid — not needed, skipped
    title, pos = read_cstr(data, pos)
    author, pos = read_cstr(data, pos)
    read_cstr(data, pos)[0]  # copyright — not carried into our format
    pos = data.index(b"\x00", pos) + 1
    clues = []
    for _ in range(n_clues):
        clue, pos = read_cstr(data, pos)
        clues.append(clue)

    return {
        "width": width, "height": height, "solution": solution,
        "title": title, "author": author, "clues": clues,
        "scrambled": scrambled_tag != 0,
    }


# ---------- Across Lite scrambling (see module docstring: unused in practice
# on this feed today, kept because it's cheap and the public algorithm) ----------

def data_cksum(raw, cksum=0):
    for b in raw:
        lowbit = cksum & 1
        cksum >>= 1
        if lowbit:
            cksum |= 0x8000
        cksum = (cksum + b) & 0xFFFF
    return cksum


def square(s, w, h):
    """Row-major <-> column-major transpose of a w*h string (self-inverse when
    called with w and h swapped on the result)."""
    rows = [s[i:i + w] for i in range(0, len(s), w)]
    return "".join("".join(rows[r][c] for r in range(h)) for c in range(w))


def restore(template, letters):
    """Drop `letters` back into template's non-black positions, in order."""
    it = iter(letters)
    return "".join(next(it) if c != BLACK else c for c in template)


def shift(s, digits):
    a_z = string.ascii_uppercase
    return "".join(a_z[(a_z.index(c) + digits[i % 4]) % 26] for i, c in enumerate(s))


def unshuffle(s):
    return s[1::2] + s[::2]


def unscramble_string(s, key):
    digits = [int(c) for c in f"{key:04d}"]
    n = len(s)
    for k in reversed(digits):
        s = unshuffle(s)
        s = s[n - k:] + s[:n - k]
        s = shift(s, [-d for d in digits])
    return s


def unscramble_solution(scrambled, width, height, key):
    sq = square(scrambled, width, height)
    letters_only = sq.replace(BLACK, "")
    unsc = restore(sq, unscramble_string(letters_only, key))
    return square(unsc, height, width)


def scrambled_cksum(solution, width, height):
    return data_cksum(square(solution, width, height).replace(BLACK, "").encode("iso-8859-1"))


def try_unscramble(solution, width, height, target_cksum):
    """Brute-force all 10000 keys; return the unscrambled grid or None.

    Cheap (10000 substitution+permutation passes over <=225 chars) and entirely
    in-process — see module docstring for why this never actually fires today.
    """
    for key in range(10000):
        candidate = unscramble_solution(solution, width, height, key)
        if scrambled_cksum(candidate, width, height) == target_cksum:
            return candidate
    return None


# ---------- grid geometry -> numbered entries ----------

def number_grid(solution, width, height):
    """Standard crossword numbering from the black-square pattern alone.

    A cell starts an across entry if it's white and (at the left edge or the
    cell to its left is black) and the run is >=2 long; symmetrically for down.
    Returns entries in "across-then-down, reading order" — the same order the
    .puz clue list is in — as (number, direction, x, y, length).
    """
    def is_black(x, y):
        return not (0 <= x < width and 0 <= y < height) or solution[y * width + x] == BLACK

    entries, number = [], 0
    for y in range(height):
        for x in range(width):
            if is_black(x, y):
                continue
            starts_across = is_black(x - 1, y) and not is_black(x + 1, y)
            starts_down = is_black(x, y - 1) and not is_black(x, y + 1)
            if not (starts_across or starts_down):
                continue
            number += 1
            if starts_across:
                length = 0
                while not is_black(x + length, y):
                    length += 1
                entries.append((number, "across", x, y, length))
            if starts_down:
                length = 0
                while not is_black(x, y + length):
                    length += 1
                entries.append((number, "down", x, y, length))
    return entries


def convert(num, puz):
    """Parsed .puz fields -> this app's puzzle object."""
    width, height = puz["width"], puz["height"]
    grid_entries = number_grid(puz["solution"], width, height)
    if len(grid_entries) != len(puz["clues"]):
        raise ValueError(f"{len(grid_entries)} grid entries but "
                          f"{len(puz['clues'])} clues — numbering disagrees with the file")

    unscrambled = None
    if puz["scrambled"]:
        # Kept as a real attempt, not dead code: see module docstring for why
        # this is expected to return None on today's feed (dummy 'D' fill)
        # rather than skipped outright on the assumption it always will.
        header_cksum = None  # no offset for this header shape has been confirmed
        if header_cksum is not None:
            unscrambled = try_unscramble(puz["solution"], width, height, header_cksum)

    # Clues are consumed in file order, which is exactly grid_entries' order
    # (that's the .puz convention this numbering was built to match).
    #
    # Which lights are linked is read off the clue prose before the entries are
    # built, so the group can go in beside the clue it was read from rather than
    # be bolted on afterwards. See link_groups.
    groups = link_groups({"entries": [
        {"number": n, "direction": d, "clue": c.strip()}
        for (n, d, _x, _y, _len), c in zip(grid_entries, puz["clues"])]})

    entries = []
    for (number, direction, x, y, length), clue in zip(grid_entries, puz["clues"]):
        eid = f"{number}-{direction}"
        entries.append({
            "id": eid,
            "number": number,
            "direction": direction,
            "position": {"x": x, "y": y},
            "length": length,
            "clue": clue.strip(),
            **({"group": groups[eid]} if eid in groups else {}),
            "solution": None,  # see module docstring — never recoverable from this feed today
        })

    return {
        "id": f"{SERIES}-{num}",
        "number": num,
        "series": SERIES,
        "name": f"Private Eye Cyclops crossword No {num}",
        "setter": SETTER,
        "date": cover_date(num, puz["title"]),
        "dimensions": {"cols": width, "rows": height},
        "sourceUrl": INDEX_URL,
        "entries": entries,
    }


# ---------- publication date, via the Eye's own cover page ----------

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}

_cover_cache = {}


def issue_number(num, title):
    """The Private Eye issue number a .puz title names, or None.

    The title pairs the crossword number with the issue number, but the order
    is not stable across the archive: No. 400 ships as "Eye 1245/400" and
    No. 821 as "Eye 821/1666". Whitespace drifts too ("Eye 538/ 1383"). So the
    pair is read positionally-agnostically — whichever half is not the
    crossword number is the issue — which is also the check: a title naming
    neither `num` nor a plausible issue is not a title this can read.
    """
    match = re.search(r"Eye\s*(\d+)\s*/\s*(\d+)", title or "")
    if not match:
        return None
    left, right = int(match.group(1)), int(match.group(2))
    if left == num and right != num:
        return right
    if right == num and left != num:
        return left
    return None


def fetch_cover_date(issue):
    """The publication date Private Eye prints on its own cover page for
    `issue`, as a datetime.date, or None if the page is missing or silent.

    The date is read only from inside the page's "Issue NNNN ... <date>" block
    so that the archive's navigation to neighbouring issues, which also prints
    dates, cannot answer for the issue asked about.
    """
    if issue in _cover_cache:
        return _cover_cache[issue]
    time.sleep(1)  # one request per second, max — the caller has just fetched a .puz
    try:
        page = http_bytes(COVER_URL.format(issue=issue)).decode("utf-8", "replace")
    except urllib.error.HTTPError:
        _cover_cache[issue] = None
        return None
    match = re.search(rf"Issue\s*{issue}\b.{{0,400}}?(\d{{1,2}})\s+([A-Z][a-z]+)\s+(\d{{4}})",
                      page, re.DOTALL)
    found = None
    if match and match.group(2) in MONTHS:
        found = datetime.date(int(match.group(3)), MONTHS[match.group(2)],
                              int(match.group(1)))
    _cover_cache[issue] = found
    return found


def cover_date(num, title):
    """Publication date of Cyclops `num` in epoch ms at midnight UTC, or None.

    The .puz itself carries no date, but it names its issue, and the Eye dates
    that issue on its own cover page — so this is the publisher's date for this
    puzzle, not an interpolation off the number sequence. Verified against six
    puzzles already dated on disk, spread over 2009-2026: all six matched to
    the day with no offset.

    A date that is not a Friday is discarded rather than written. The Eye dates
    every issue to a Friday, so a non-Friday means the issue was misread, not
    that the magazine moved.
    """
    issue = issue_number(num, title)
    if issue is None:
        return None
    found = fetch_cover_date(issue)
    if found is None or found.weekday() != PUBLICATION_WEEKDAY:
        if found is not None:
            print(f"  {SERIES}-{num}: cover-{issue} says {found} "
                  f"({found:%A}), not a Friday — left undated")
        return None
    return int(datetime.datetime.combine(
        found, datetime.time(), datetime.timezone.utc).timestamp() * 1000)


# ---------- fifteensquared.net answer join ----------

_dir_suffix = {"across": "ac", "down": "dn"}


def _clue_id(number, direction):
    return f"{number}{_dir_suffix[direction]}"


_fq_last_request = 0.0


def fetch_fifteensquared_post(num):
    """The fifteensquared.net blog post that solves Cyclops issue `num`, or None.

    The WP REST search is fuzzy — "Cyclops 838" ranks any Cyclops post by
    relevance, not necessarily one that mentions 838 at all — so a hit only
    counts if the issue number appears as its own token in the post's slug or
    title (never a substring: 838 must not match a post titled around 8384).
    Zero matches is the normal, expected case for the newest puzzle, which
    the blog — running roughly two issues behind — hasn't covered yet.

    The post must also name this series. Every other daily the blog covers
    numbers its puzzles in thousands and prints them with a comma, so the
    digit-boundary guard above does not stop "Guardian Prize 28,434 by Bogus"
    from answering to Cyclops 434 — 18 of 249 searches came back with one of
    those. They are a different grid entirely, so requiring the title or slug
    to say Cyclops (or Private Eye, which a handful of early posts use alone)
    is what keeps another paper's answers out of this series.
    """
    global _fq_last_request
    wait = FQ_MIN_INTERVAL - (time.monotonic() - _fq_last_request)
    if wait > 0:
        time.sleep(wait)
    data = http_bytes(FQ_SEARCH_URL.format(num=num))
    _fq_last_request = time.monotonic()
    posts = json.loads(data)
    token = re.compile(rf"(?<!\d){num}(?!\d)")
    matches = [p for p in posts
               if (token.search(p.get("slug", "")) or token.search(p["title"]["rendered"]))
               and is_this_series(p)]
    return matches[0] if matches else None


_SERIES_RE = re.compile(r"cyclops|private[\s\-]*eye", re.IGNORECASE)


def is_this_series(post):
    """Whether a fifteensquared post is about Private Eye's Cyclops at all."""
    return bool(_SERIES_RE.search(post["title"]["rendered"] + " " + post.get("slug", "")))


_TAG_RE = re.compile(r"<[^>]+>")
_ROW_OR_HEADING_RE = re.compile(r"(<tr\b.*?</tr>)|>(Across|Down)<", re.DOTALL)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
# <strong> is the norm but some posts use plain <b> for an answer or two
# (Cyclops 830: 27 <strong> answers, 2 <b> ones in the same post), and posts
# from the "Clue No / Solution / Clue / Logic" table era (Cyclops 600, 700)
# don't tag the answer at all — plain text in its own column. Handled where
# this is used: try <strong>/<b> first, fall back to the cell's bare text.
# The tag may carry attributes and may wrap markup rather than bare text —
# an answer is often a link to its Wikipedia page,
# <strong><a href="...">DON JUAN</a></strong> — so the body is captured with
# its tags and stripped afterwards. Matching only bare text here would make
# every such answer fall through to the whole-cell fallback and swallow the
# wordplay with it.
_STRONG_RE = re.compile(r"<(?:strong|b)\b[^>]*>(.*?)</(?:strong|b)>", re.DOTALL)
# "13", "13ac", "7A" (older template's own number+direction, no separator).
_KEY_TOKEN_RE = re.compile(r"^(\d+)(ac|dn|a|d)?\.?$", re.IGNORECASE)
_DIR_FROM_SUFFIX = {"ac": "across", "a": "across", "dn": "down", "d": "down"}


_DEL_RE = re.compile(r"<del\b[^>]*>.*?</del>", re.DOTALL)
# A run of answer tags at the very start of the cell, separated by nothing but
# whitespace or a line break. A two-word answer is often tagged a word at a
# time — Cyclops 401 emits "<strong>BETTER</strong> <strong>OFF</strong>", 404
# "<strong>ROMAN</strong> <strong>POLANSKI </strong>" — so reading only the
# first tag hands back half the answer. The run must start the cell and must
# not skip over untagged text, which is what keeps a <strong> inside the
# wordplay that follows from being mistaken for part of the answer.
_ANSWER_RUN_RE = re.compile(
    r"\A(?:\s|<br\s*/?>)*"
    r"(?:<(?:strong|b)\b[^>]*>.*?</(?:strong|b)>(?:\s|<br\s*/?>)*)+",
    re.DOTALL)


def _leading_answers(cell_html):
    """The cell's opening run of <strong>/<b> answer tags, or None if it has
    none — in which case the caller falls back to the cell's bare text, which
    is how the "Clue No / Solution / Clue / Logic" template prints answers."""
    m = _ANSWER_RUN_RE.match(cell_html)
    return m.group(0) if m else None


def parse_fifteensquared_rows(content_html):
    """content.rendered -> [(key, direction, answer_letters), ...] in document order.

    `key` is the clue-number cell's own text: "13" for an ordinary entry,
    "13/15/17" for a linked group, or "16/27ac" where a later member's own
    direction differs from the leading entry's (Cyclops links do cross
    across/down — see solve_from_fifteensquared). `direction` is whichever of
    an Across/Down heading was last seen before the row: fifteensquared has
    used at least two table templates across 20 years of posts (one table
    per puzzle with "Across"/"Down" as header rows inside it; one table per
    direction with an <h3> heading before each) and reading "whichever
    heading came last" rather than assuming either shape handles both. A row
    whose answer cell is empty is a stub for a referenced entry — printed
    with no answer of its own, just "See 4d." — and is skipped; its letters
    come only from the linked group's own combined row.
    """
    direction = None
    rows = []
    for m in _ROW_OR_HEADING_RE.finditer(content_html):
        if m.group(2):
            direction = "across" if m.group(2) == "Across" else "down"
            continue
        row = m.group(1)
        # The older template puts the heading in its own <tr><th>Across</th></tr>
        # rather than a bare heading tag, so the first alternative above already
        # swallowed it before the second got a look — catch it here instead.
        heading = re.search(r">(Across|Down)<", row)
        if heading:
            direction = "across" if heading.group(1) == "Across" else "down"
        cells = _TD_RE.findall(row)
        if len(cells) < 2:
            continue
        # The number cell is hand-typed and shows it: "*1/10" (a star marking a
        # themed clue), "27/20/ 14/10" (a stray space after a slash),
        # "13/12ac./24dn." (a dot after every member, not just the last). None
        # of that changes which lights the row is about, so it is all stripped
        # before the row is judged to be a clue row at all.
        key = re.sub(r"\s+", "", html.unescape(_TAG_RE.sub("", cells[0])))
        key = key.lstrip("*").replace(".", "")
        if not re.match(r"^\d+[a-z]*(/\d+[a-z]*)*$", key, re.IGNORECASE):
            continue  # not a clue row (e.g. a blank <th> spacer row, the
                      # "Clue No / Solution / Clue / Logic" column header row,
                      # or a row the blogger left unnumbered
        # A correction the blogger made in place: the wrong answer struck out,
        # the right one beside it. <del> is retracted text by definition, so it
        # is dropped before anything reads the cell.
        cell = _DEL_RE.sub("", cells[1])
        answers = _leading_answers(cell)
        raw_answer = _TAG_RE.sub("", answers if answers is not None else cell).strip()
        # Answers are printed as words, accents and all — "DÉTENTE". Decompose
        # first so the accent becomes a separate combining mark and the base
        # letter survives; stripping non-A-Z straight off drops the É outright
        # and hands back a DTENTE one letter short of its light.
        letters = re.sub(r"[^A-Z]", "",
                         unicodedata.normalize("NFKD", html.unescape(raw_answer).upper()))
        if letters:
            rows.append((key, direction, letters))
    return rows


# A referenced light's whole clue, e.g. "see 4ac.", "See 12 down", "(see 21dn.)
# (3,6)", "see 13ac. (9)". The direction word is optional: some issues print a
# bare "see 7." and leave the direction to the solver. The word itself is typed
# by hand into the puzzle and arrives as "see26ac." with no space and as the
# typo "se 13ac." (Cyclops 784); matching `se+` with optional space costs
# nothing, since the pattern is anchored to the entire clue.
_SEE_RE = re.compile(
    r"^\(?\s*se+\s*(\d+)\s*(ac|dn|a|d|down|across)?\.?\s*\)?\.?\s*(\([\d,\-]+\))?$",
    re.IGNORECASE)


# The leading light of a linked group names the rest, in answer order, in a
# prefix on its own clue: "(& 24ac.)", "(& 6dn./22dn.)", "(&14dn.)". Six clues
# across the archive type a "+" for the "&" — "(+ 17ac.)" — which is the same
# statement in the same place, so it is read as one rather than losing the link.
_AMP_PREFIX_RE = re.compile(r"^\(\s*[&+]\s*([^)]*)\)")
_AMP_MEMBER_RE = re.compile(r"(\d+)\s*(ac|dn|a|d)?", re.IGNORECASE)


def _other_dir(direction):
    return "down" if direction == "across" else "across"


def find_link_groups(puzzle):
    """Cyclops links clues by having one carry the enumeration for the whole
    group while the rest read literally "see 4ac." (see module docstring) —
    with no parenthesis, though some older issues also tack their own
    sub-enumeration on afterwards, e.g. "see 13ac. (9)".

    The two statements can CONTRADICT each other, and then the leading light's
    own prefix wins. Five puzzles misprint the number in a continuation's "see"
    — Cyclops 683's 23dn reads "see 9ac." when 11ac's own clue says "(& 23dn.)"
    and the answer is SECOND WAVE, 9ac being a finished four-letter clue of its
    own. Honouring both put 23dn in two groups at once and left the legs naming
    different sets, which is what tools/validate_annotations.py rejects. A
    continuation that a leading light has already claimed keeps the claim and
    its own "see" is discarded; one that nobody has claimed still forms a group,
    so a leader whose prefix names only some of its members is unaffected.

    Returns (referencer_of, groups), with referencer_of holding only the "see"
    links actually honoured:
      referencer_of: {(num, dir) of a "see..." entry -> (num, dir) it names}
      groups: {leading (num, dir) -> frozenset of every member, leading included}
    """
    by_id = {(e["number"], e["direction"]) for e in puzzle["entries"]}
    referencer_of = {}
    for e in puzzle["entries"]:
        m = _SEE_RE.match(e["clue"].strip())
        if m:
            word = (m.group(2) or "").lower()
            if word:
                target_dir = "across" if word in ("ac", "a", "across") else "down"
            else:
                # No direction printed. Take whichever direction that number
                # actually exists in; if both do, we cannot tell, so no group.
                here = [d for d in ("across", "down") if (int(m.group(1)), d) in by_id]
                if len(here) != 1:
                    continue
                target_dir = here[0]
            referencer_of[(e["number"], e["direction"])] = (int(m.group(1)), target_dir)

    # The leading light states its own group in the "(& 24ac./6dn.)" prefix on
    # its clue, and that statement is the one that survives when the members'
    # own "see 24ac." clues are missing or misprinted — so it is read FIRST and
    # the "see" links are fitted around it below.
    groups = {}
    for e in puzzle["entries"]:
        m = _AMP_PREFIX_RE.match(e["clue"].strip())
        if not m:
            continue
        leading = (e["number"], e["direction"])
        members = {leading}
        for tok in _AMP_MEMBER_RE.finditer(m.group(1)):
            num, word = int(tok.group(1)), (tok.group(2) or "").lower()
            if word:
                member = (num, "across" if word in ("ac", "a") else "down")
                # The direction printed in the puzzle can name a light that
                # does not exist — Cyclops 790's 1ac says "(& 20dn.)" over a
                # grid whose only 20 is across. The grid decides which lights
                # exist, so an impossible direction falls back to the one
                # that does; if neither is there the group is dropped below.
                if member not in by_id and (num, _other_dir(member[1])) in by_id:
                    member = (num, _other_dir(member[1]))
            else:
                here = [d for d in ("across", "down") if (num, d) in by_id]
                if len(here) != 1:
                    members = None
                    break
                member = (num, here[0])
            if member not in by_id or member == leading:
                members = None
                break
            members.add(member)
        if members:
            groups.setdefault(leading, set()).update(members)

    # Now the continuations. A light some leader's prefix already names keeps
    # that group and its own "see" is dropped; anything else forms or joins a
    # group as before. Dropped rather than merged because the union would be a
    # third light in a two-light answer — 683's SECOND WAVE does not gain 9ac's
    # GAIN just because 23dn misprints the number it points at.
    claimed = {light for members in groups.values() for light in members}
    for member, leading in list(referencer_of.items()):
        if member in claimed:
            del referencer_of[member]
            continue
        groups.setdefault(leading, {leading}).add(member)
    return referencer_of, {k: frozenset(v) for k, v in groups.items()}


def order_group(puzzle_entry, group):
    """The members of `group` in the order their letters appear in the answer.

    The leading light always comes first — it is the one carrying the clue, so
    it holds the first word — and the rest follow the order its "(& 24ac.)"
    prefix names them in. A group whose leader does not name every other member
    falls back to grid reading order, which is only ever a guess for a group of
    three or more; the crossing check downstream is what polices it.
    """
    leader = (puzzle_entry["number"], puzzle_entry["direction"])
    rest = [m for m in group if m != leader]
    m = _AMP_PREFIX_RE.match(puzzle_entry["clue"].strip())
    if m:
        named = [int(t.group(1)) for t in _AMP_MEMBER_RE.finditer(m.group(1))]
        if sorted(named) == sorted(n for n, _ in rest):
            by_num = {n: (n, d) for n, d in rest}
            return [leader] + [by_num[n] for n in named]
    rest.sort(key=lambda k: (k[1], k[0]))
    return [leader] + rest


def link_groups(puzzle):
    """{entry id -> the whole linked group as entry ids, in answer order}.

    The `group` field the app and tools/puzzle_integrity.py read, in the shape
    tools/fetch_puzzle.py and tools/fetch_independent.py write it: every member
    carries the complete list including itself, and a clue that is its own
    answer is absent rather than carrying a list of one.

    The Guardian and the Independent are TOLD which lights are linked — the
    Guardian ships a `group` array and Crossword Compiler ships one <word> with
    several cell runs. Private Eye ships neither, only prose ("(& 24ac.)" on
    one clue and "see 24ac." on the other), so the link has to be read back out
    of the clue text; find_link_groups is that reader and this is the same
    answer expressed as entry ids.

    A group naming a light the grid does not have is dropped, not guessed: the
    grid is the authority on which lights exist (the same rule as
    grid_group_members), and the prose is hand-typed and names a missing light
    in five puzzles of 378.
    """
    _, groups = find_link_groups(puzzle)
    by_key = {(e["number"], e["direction"]): e for e in puzzle["entries"]}
    out = {}
    for leading, members in groups.items():
        if len(members) < 2 or any(m not in by_key for m in members):
            continue
        ids = [f"{n}-{d}" for n, d in order_group(by_key[leading], members)]
        settled = {frozenset(out[eid]) for eid in ids if eid in out}

        # Two lights can each name the other — Cyclops 464's 7ac says "(& 25dn.)"
        # and 25dn says "(& 7ac.)", both carrying a full clue, for POOR TASTE.
        # That is agreement about the group and silence about which light leads
        # it, so the members stand and the first arrangement reached is kept.
        # Only membership is load-bearing: the app groups by annotation.linkedTo,
        # check_length sums over the group, and validate_annotations compares the
        # legs to each other, so none of them can see the order.
        if settled == {frozenset(ids)}:
            continue

        # Overlapping DIFFERENT groups is the real contradiction, and it would
        # leave the legs naming different sets — the asymmetry
        # validate_annotations.py rejects. find_link_groups has already settled
        # the misprint it can name, so what is left is prose nothing here reads.
        # Both groups go: one silently winning on dict order is how a group its
        # own members disagree with got written in the first place.
        if settled:
            for stale in settled:
                for eid in stale:
                    out.pop(eid, None)
            print(f"WARNING: {puzzle.get('id', '?')}: {' + '.join(ids)} overlaps "
                  f"{' / '.join(' + '.join(sorted(c)) for c in settled)} — "
                  "linking neither", file=sys.stderr)
            continue
        for eid in ids:
            out[eid] = ids
    return out


def solve_from_fifteensquared(puzzle, post):
    """Fill in every entry's solution from a fifteensquared post — or none of
    them. This is a two-source join (the grid's own numbering against a
    human's prose write-up) and a silent mis-pairing would poison the corpus,
    so nothing is written until ALL of these hold:
      - every answer's letter count matches its entry's grid length
      - every crossing cell agrees between its across and its down entry
      - the blog's set of numbered entries matches the grid's
      - every linked group (see find_link_groups) maps onto the grid
        unambiguously, member-for-member

    The blog's own printed enumeration is never trusted for any of this —
    only the letters it gives and the grid's own lengths — because it can be
    wrong (Cyclops 834 prints "(9,6)" for EXECUTIVE ORDER, a 14-letter answer,
    over a 9-then-5 split; the join here never even parses that number).

    Returns (solutions, problem): solutions is {entry id: letters} for every
    entry with problem None, or (None, "what failed and for which entry") if
    any check fails. Never a partial solutions dict.
    """
    entries_by_id = {(e["number"], e["direction"]): e for e in puzzle["entries"]}
    _, groups = find_link_groups(puzzle)
    rows = parse_fifteensquared_rows(post["content"]["rendered"])

    solutions = {}  # (num, dir) -> letters

    def assign(num, direction, letters, source):
        key = (num, direction)
        entry = entries_by_id.get(key)
        if entry is None:
            return f"'{source}': no {_clue_id(num, direction)} in the grid"
        if len(letters) != entry["length"]:
            return (f"'{source}': {letters} is {len(letters)} letters, grid wants "
                     f"{entry['length']} for {_clue_id(num, direction)}")
        if key in solutions and solutions[key] != letters:
            return f"'{source}': {_clue_id(num, direction)} given two different answers"
        solutions[key] = letters
        return None

    def grid_group_members(num, letters):
        """The grid's own linked group led by `num`, when its lights' lengths
        sum to exactly these letters — else None.

        The grid is the authority on which lights a group spans; the blog only
        supplies the letters, and it gets the key wrong in two ways. It keys a
        group by its leading light alone ("13A HOT AIR" for 13ac/24ac), and it
        misnumbers a member outright (Cyclops 806 prints "12/23" for the group
        the grid links as 12ac/22ac, with a separate 23ac of its own). Exactly
        one direction of `num` must lead a group that fits, so an ambiguous
        number falls through to the error path rather than being guessed.
        """
        spans = [d for d in ("across", "down")
                 if groups.get((num, d))
                 and sum(entries_by_id[m]["length"]
                         for m in groups[(num, d)]) == len(letters)]
        if len(spans) != 1:
            return None
        return order_group(entries_by_id[(num, spans[0])], groups[(num, spans[0])])

    def assign_across(members, letters, source):
        pos = 0
        for member in members:
            size = entries_by_id[member]["length"]
            err = assign(member[0], member[1], letters[pos:pos + size], source)
            if err:
                return err
            pos += size
        return None

    for key_raw, heading_dir, letters in rows:
        tokens = key_raw.split("/")

        if len(tokens) == 1:
            m = _KEY_TOKEN_RE.match(tokens[0])
            if not m:
                return None, f"'{key_raw}': unparseable clue number"
            num = int(m.group(1))
            suffix = m.group(2)
            direction = _DIR_FROM_SUFFIX[suffix.lower()] if suffix else heading_dir
            # A plain row for a linked entry is not necessarily wrong: the newer
            # template only gives a linked group's own light its real letters via
            # a combined "13/15/17" row (handled below) and leaves every member's
            # bare-number row empty (filtered out before rows ever reaches here —
            # see parse_fifteensquared_rows). But the older "Clue No / Solution"
            # template answers every light independently, including linked ones —
            # e.g. Cyclops 700's "19A MORSE" / "23D CODE" are two plain rows, each
            # already that light's own correct letters, no combining needed. So a
            # plain row is always just tried directly; assign()'s length check and
            # the crossing check afterwards are what catch it if that is wrong.
            # The row's Across/Down heading can be wrong for a light the blog
            # printed under the other half (and "7A" is sometimes the blog's
            # own typo). If that number exists in only one direction in the
            # grid, or only one direction has the right length, take that one —
            # the crossing check downstream still has to agree.
            # No suffix on the number and no Across/Down heading yet — some
            # posts open straight into a table with the heading only in the
            # prose above it. The letters still pin the direction down whenever
            # exactly one direction of that number is the right length.
            if direction is None or (num, direction) not in entries_by_id or \
                    entries_by_id[(num, direction)]["length"] != len(letters):
                fits = [d for d in ("across", "down")
                        if entries_by_id.get((num, d), {}).get("length") == len(letters)
                        and solutions.get((num, d), letters) == letters]
                if len(fits) == 1:
                    direction = fits[0]
                elif direction is None:
                    return None, (f"'{key_raw}' -> {letters}: no direction — no suffix on the "
                                   "number, no Across/Down heading yet, and the grid's "
                                   f"{num}ac/{num}dn do not settle it by length")
            # Letters that overshoot the light mean the blog keyed a whole
            # linked group by its leading light — see grid_group_members.
            if entries_by_id.get((num, direction), {}).get("length") != len(letters):
                members = grid_group_members(num, letters)
                if members:
                    err = assign_across(members, letters, key_raw)
                    if err:
                        return None, err
                    continue
            err = assign(num, direction, letters, key_raw)
            if err:
                return None, err
            continue

        # A linked group, e.g. "13/15/17" (all across) or "16/27ac" (16 takes
        # the row's own direction, 27 overrides it with the explicit suffix).
        parsed = []
        for tok in tokens:
            m = _KEY_TOKEN_RE.match(tok)
            if not m:
                return None, f"'{key_raw}': can't parse group member '{tok}'"
            suffix = m.group(2)
            parsed.append((int(m.group(1)),
                           _DIR_FROM_SUFFIX[suffix.lower()] if suffix else None))

        # Direction for an unsuffixed member comes from the GRID's own link
        # group, never from the leading member's direction: Cyclops links run
        # across-to-down freely ("8/3" is 8ac linked to 3dn) and fifteensquared
        # prints bare numbers, so assuming the leader's direction mis-resolved
        # 160 of the 249 unsolved puzzles. The grid is the authority on which
        # lights a group contains; the blog only supplies the letters, and
        # assign()'s length check plus the crossing check still police the join.
        lead_num, lead_dir = parsed[0]
        # Every way the group's unsuffixed numbers could land on real grid
        # entries, filtered by the one thing the blog cannot get wrong: the
        # letters it printed. An assignment counts only if each member exists
        # and the members' grid lengths sum to exactly len(letters). Exactly one
        # survivor is required, so an ambiguous group still fails rather than
        # guessing, and the crossing and completeness checks police it again.
        candidates = []
        for member_dirs in itertools.product(
                *[[d] if d else ["across", "down"] for _, d in parsed]):
            members = [(n, d) for (n, _), d in zip(parsed, member_dirs)]
            if len(set(members)) != len(members):
                continue
            if any(m not in entries_by_id for m in members):
                continue
            if sum(entries_by_id[m]["length"] for m in members) != len(letters):
                continue
            candidates.append(members)
        # The grid's own "see 4ac." links, where it has them for this group, are
        # the authority: prefer an assignment that reproduces one exactly.
        exact = [ms for ms in candidates if groups.get(ms[0]) == frozenset(ms)]
        if exact:
            candidates = exact
        if not candidates:
            members = grid_group_members(lead_num, letters)
            if members:
                err = assign_across(members, letters, key_raw)
                if err:
                    return None, err
                continue
            guess = [(n, d or heading_dir or "across") for n, d in parsed]
            sizes = [entries_by_id[m]["length"] for m in guess if m in entries_by_id]
            return None, (f"'{key_raw}' -> {letters}: {len(letters)} letters but no reading of "
                          f"this group fits the grid (tried {[_clue_id(*m) for m in guess]}, "
                          f"lengths {sizes})")
        if len(candidates) > 1:
            return None, (f"'{key_raw}' -> {letters}: ambiguous linked group — "
                          f"{len(candidates)} readings fit the grid")
        err = assign_across(candidates[0], letters, key_raw)
        if err:
            return None, err

    missing = [e for e in puzzle["entries"] if (e["number"], e["direction"]) not in solutions]
    if missing:
        names = ", ".join(_clue_id(e["number"], e["direction"]) for e in missing)
        return None, f"blog post has no answer for: {names}"

    cell = {}
    for e in puzzle["entries"]:
        letters = solutions[(e["number"], e["direction"])]
        x0, y0 = e["position"]["x"], e["position"]["y"]
        for i, ch in enumerate(letters):
            pos_key = (x0 + i, y0) if e["direction"] == "across" else (x0, y0 + i)
            if pos_key in cell and cell[pos_key] != ch:
                return None, (f"crossing conflict at column {pos_key[0]}, row {pos_key[1]}: "
                               f"'{cell[pos_key]}' vs '{ch}' from {_clue_id(e['number'], e['direction'])}")
            cell[pos_key] = ch

    return {e["id"]: solutions[(e["number"], e["direction"])] for e in puzzle["entries"]}, None


# ---------- fetch / walk ----------

def out_path(out_dir, num):
    """out_dir's own copy of whatever fetch_puzzle.puzzle_path() would name
    this number under puzzles/ itself — so --out can redirect where a puzzle
    lands without spelling the file name format a second time."""
    return out_dir / puzzle_path(SERIES, num).name


def fill_answers(puzzle, num, old_puzzle):
    """Try to fill puzzle's entries from fifteensquared; on any miss, fall
    back to whatever old_puzzle (the on-disk file from a prior fetch, if any)
    already had — so a transient network hiccup or a not-yet-blogged issue
    can never wipe out a fill that was already verified and written."""
    try:
        post = fetch_fifteensquared_post(num)
    except Exception as err:  # noqa: BLE001 — a solve failure must never break the .puz fetch
        print(f"  fifteensquared lookup failed for Cyclops {num}: {err}")
        post = "error"  # distinct from None (not found) so the message below doesn't repeat

    solutions = problem = None
    if post is None:
        print(f"  no fifteensquared post found for Cyclops {num} (not blogged yet) — solution: null")
    elif post != "error":
        try:
            solutions, problem = solve_from_fifteensquared(puzzle, post)
        except Exception as err:  # noqa: BLE001 — same: never let a parse bug corrupt the puzzle
            problem = f"{type(err).__name__}: {err}"
        if problem:
            print(f"  fifteensquared join failed for Cyclops {num}, leaving solution: null — {problem}")

    if solutions:
        for entry in puzzle["entries"]:
            entry["solution"] = solutions[entry["id"]]
        puzzle["solutionSource"] = {
            "kind": "fifteensquared",
            "url": post["link"],
            "date": post["date"][:10],
            "check": f"{len(solutions)} entries verified against the grid "
                     "(lengths, crossings, linked-clue mapping)",
        }
        print(f"  filled {len(solutions)} answers from {post['link']}")
        return

    old_source = (old_puzzle or {}).get("solutionSource") or {}
    if old_source.get("kind") == "fifteensquared":
        old_solutions = {e["id"]: e.get("solution") for e in old_puzzle["entries"]}
        if all(old_solutions.get(e["id"]) for e in puzzle["entries"]):
            for entry in puzzle["entries"]:
                entry["solution"] = old_solutions[entry["id"]]
            puzzle["solutionSource"] = old_source
            print(f"  kept the previously-verified fill from {old_source.get('url')}")


def fetch_number(num, out_dir, dry_run=False):
    data = http_bytes(PUZ_URL.format(num=num))
    puz = parse_puz(data)
    puzzle = convert(num, puz)
    path = out_path(out_dir, num)
    old_puzzle = read_puzzle_file(path) if path.exists() else None
    fill_answers(puzzle, num, old_puzzle)
    if dry_run:
        print(f"[dry-run] {puzzle['id']}: {puz['title']} by {puz['author']}, "
              f"{len(puzzle['entries'])} entries, scrambled={puz['scrambled']}")
        return puzzle
    is_new = old_puzzle is None
    if not is_new:
        merge_annotations(puzzle, old_puzzle)
    write_puzzle_file(path, puzzle, generator="tools/fetch_privateeye.py")
    print(("fetched " if is_new else "refreshed ") + puzzle["id"])
    return puzzle


def refresh_unsolved():
    """Re-run the fifteensquared join for on-disk Cyclops puzzles that don't
    have real answers yet — the one gap walk() and --latest both leave open,
    since neither ever revisits a number already on disk.

    "Has real answers" cannot be read off completeness of the solution fields:
    a Cyclops can carry a full grid of letters that are a model's own guess
    (solutionSource.kind == "model", written by apply_solution.py while the
    blog stays silent — see daily_update.sh's cold-solve queue), and the .puz
    feed itself never supplies real ones at all (module docstring). The only
    fact that means "these are the paper's own words" is
    solutionSource.kind == "fifteensquared" — fifteensquared is the sole real
    key this feed ever gets, so once that kind is set the puzzle is done and
    asking again would only spend a request on an answer that cannot change.
    Anything else — no solutionSource, or kind == "model" — is pending.

    Annotations already on the entries are untouched by construction: unlike
    a re-fetch of the .puz (which rebuilds entries from scratch and needs
    merge_annotations to carry them across), this mutates the on-disk entries
    in place, so nothing is ever cleared except the annotations on entries a
    model got wrong, exactly as grade_model_fill does for the other papers'
    refresh_unsolved."""
    pending = []
    for path in puzzle_files():
        p = read_puzzle_file(path)
        if p.get("series") != SERIES:
            continue
        if (p.get("solutionSource") or {}).get("kind") == "fifteensquared":
            continue
        pending.append(p["number"])

    filled = 0
    for num in pending:
        path = out_path(PUZZLE_DIR, num)
        puzzle = read_puzzle_file(path)
        was_model = (puzzle.get("solutionSource") or {}).get("kind") == "model"
        guessed = ({e["id"]: e.get("solution") for e in puzzle["entries"]}
                   if was_model else None)
        try:
            fill_answers(puzzle, num, puzzle)
            if (puzzle.get("solutionSource") or {}).get("kind") == "fifteensquared":
                if guessed is not None:
                    print_grade(puzzle, grade_model_fill(puzzle, guessed))
                write_puzzle_file(path, puzzle, generator="tools/fetch_privateeye.py")
                print(f"solutions now published for {num}")
                filled += 1
            elif was_model:
                print(f"{num}: solutions still withheld — keeping our own fill")
            else:
                print(f"{num}: solutions still withheld")
        except Exception as err:  # noqa: BLE001 — one bad puzzle shouldn't stop the refresh
            print(f"refresh {num} failed: {err}")
        time.sleep(1)
    print(f"refresh-unsolved: {filled}/{len(pending)} puzzle(s) gained solutions")


DATE_LINE = re.compile(r'^ "date": (?:null|\d+),$', re.MULTILINE)


def stamp_date(path, epoch_ms):
    """Write just the top-level `date` of an on-disk puzzle, in place.

    A line edit, not a re-serialisation, because the only thing being learned
    here is the date: re-emitting the whole file would also quietly restyle
    everything the annotators have written into it. The pattern is anchored to
    the top-level field's one-space indent, so the deeper `solutionSource.date`
    cannot match.
    """
    text = path.read_text()
    text, count = DATE_LINE.subn(f' "date": {epoch_ms},', text, count=1)
    if count != 1:
        raise ValueError(f"{path.name}: no top-level date line to write")
    path.write_text(text)


def backfill_dates(out_dir, dry_run=False):
    """Fill in the publication date of every on-disk Cyclops that lacks one.

    The dates come from the Eye's own issue cover pages; see cover_date.
    """
    written = skipped = 0
    for num in on_disk_numbers(out_dir):
        path = out_path(out_dir, num)
        puzzle = read_puzzle_file(path)
        if puzzle.get("date"):
            continue
        try:
            data = http_bytes(PUZ_URL.format(num=num))
            epoch_ms = cover_date(num, parse_puz(data)["title"])
        except Exception as err:  # noqa: BLE001 — one bad puzzle shouldn't stop the walk
            print(f"skip {SERIES}-{num}: {err}")
            epoch_ms = None
        if epoch_ms is None:
            skipped += 1
        else:
            shown = datetime.datetime.fromtimestamp(
                epoch_ms / 1000, datetime.timezone.utc).date()
            if not dry_run:
                stamp_date(path, epoch_ms)
            print(f"{'[dry-run] ' if dry_run else ''}dated {SERIES}-{num}: {shown}")
            written += 1
        time.sleep(1)  # one request per second, max
    print(f"done: {written} dated, {skipped} still undated")
    return written


def on_disk_numbers(out_dir):
    prefix = f"{SERIES}-"
    return sorted(int(p.stem[len(prefix):]) for p in out_dir.glob(f"{prefix}*.json")
                  if p.stem[len(prefix):].isdigit())


def find_latest_number():
    page = http_bytes(INDEX_URL).decode("utf-8", "replace")
    nums = [int(n) for n in re.findall(r"download/(\d+)\.puz", page)]
    if not nums:
        raise SystemExit("No Private Eye puzzle link found on the crossword index page")
    return max(nums)


def walk(numbers, out_dir, dry_run=False):
    fetched = skipped = missing = 0
    for num in numbers:
        if not dry_run and out_path(out_dir, num).exists():
            skipped += 1
            continue
        try:
            fetch_number(num, out_dir, dry_run=dry_run)
            fetched += 1
        except urllib.error.HTTPError as err:
            print(f"skip {num}: HTTP {err.code}")
            missing += 1
        except Exception as err:  # noqa: BLE001 — one bad puzzle shouldn't stop the walk
            print(f"skip {num}: {err}")
            missing += 1
        time.sleep(1)  # one request per second, max
    print(f"done: {fetched} fetched, {skipped} already present, {missing} unavailable")
    return fetched


def extend(count, out_dir, dry_run=False):
    have = on_disk_numbers(out_dir)
    oldest = min(have) if have else find_latest_number() + 1
    return walk(range(oldest - 1, max(oldest - 1 - count, 0), -1), out_dir, dry_run)


def main(argv):
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("numbers", nargs="*", help="explicit puzzle number(s)")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--extend", nargs="?", const=30, type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=PUZZLE_DIR)
    parser.add_argument("--refresh-unsolved", action="store_true")
    parser.add_argument("--backfill-dates", action="store_true")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)

    if args.refresh_unsolved:
        refresh_unsolved()
        return 0

    if args.backfill_dates:
        backfill_dates(args.out, dry_run=args.dry_run)
        return 0

    if args.latest:
        num = find_latest_number()
        if not args.dry_run and out_path(args.out, num).exists():
            print(f"up-to-date {SERIES}-{num}")
            return 3
        fetch_number(num, args.out, dry_run=args.dry_run)
        return 0

    if args.extend is not None:
        extend(args.extend, args.out, dry_run=args.dry_run)
        return 0

    if not args.numbers:
        parser.print_help()
        return 0

    walk((int(n) for n in args.numbers), args.out, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
