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

Writes <out>/cyclops-<number>.js (preserving any existing per-clue annotations
via merge_annotations). Deliberately does NOT rebuild puzzles/index.json or
index.js — this fetcher lands before the "cyclops" series exists in
tools/series.py and app.js, so an index write here would either crash (series
metadata missing) or bake in an incomplete picture. Once the series is
registered, run tools/fetch_puzzle.py --reindex once by hand.
"""

import argparse
import html
import json
import re
import string
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (PUZZLE_DIR, http_bytes, merge_annotations,  # noqa: E402
                          puzzle_files, read_puzzle_file, write_puzzle_file)

INDEX_URL = "https://www.private-eye.co.uk/crossword"
PUZ_URL = "https://www.private-eye.co.uk/pictures/crossword/download/{num}.puz"
# per_page=40, not the obvious 5: the WP search ranks by relevance, not by
# whether the number actually appears, and for older issues the true match
# routinely isn't in the top 5 (Cyclops 500's own post ranked 12th of 15
# candidates for the query "Cyclops 500"). One request either way, so there's
# no politeness cost to asking for more candidates to filter locally.
FQ_SEARCH_URL = "https://fifteensquared.net/wp-json/wp/v2/posts?search=Cyclops+{num}&per_page=40"
FQ_MIN_INTERVAL = 1.0  # seconds — politeness floor between requests to fifteensquared.net
SERIES = "cyclops"
SETTER = "Cyclops"

BLACK = "."


# ---------- .puz reading ----------

def read_cstr(data, pos):
    """A NUL-terminated ISO-8859-1 string starting at pos -> (text, next pos)."""
    end = data.index(b"\x00", pos)
    return data[pos:end].decode("iso-8859-1"), end + 1


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
    solution = data[pos:pos + width * height].decode("iso-8859-1")
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
    entries = []
    for (number, direction, x, y, length), clue in zip(grid_entries, puz["clues"]):
        entries.append({
            "id": f"{number}-{direction}",
            "number": number,
            "direction": direction,
            "position": {"x": x, "y": y},
            "length": length,
            "clue": clue.strip(),
            "separatorLocations": {},
            "solution": None,  # see module docstring — never recoverable from this feed today
            "annotation": None,
        })

    return {
        "id": f"{SERIES}-{num}",
        "number": num,
        "series": SERIES,
        "name": f"Private Eye Cyclops crossword No {num}",
        "setter": SETTER,
        "date": None,  # the .puz carries no publication date; the Eye issue does, but
                        # issue numbers and crossword numbers are two sequences and
                        # nothing here can safely correlate one to the other
        "dimensions": {"cols": width, "rows": height},
        "sourceUrl": INDEX_URL,
        "entries": entries,
    }


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
               if token.search(p.get("slug", "")) or token.search(p["title"]["rendered"])]
    return matches[0] if matches else None


_TAG_RE = re.compile(r"<[^>]+>")
_ROW_OR_HEADING_RE = re.compile(r"(<tr\b.*?</tr>)|>(Across|Down)<", re.DOTALL)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
# <strong> is the norm but some posts use plain <b> for an answer or two
# (Cyclops 830: 27 <strong> answers, 2 <b> ones in the same post), and posts
# from the "Clue No / Solution / Clue / Logic" table era (Cyclops 600, 700)
# don't tag the answer at all — plain text in its own column. Handled where
# this is used: try <strong>/<b> first, fall back to the cell's bare text.
_STRONG_RE = re.compile(r"<(?:strong|b)>\s*([^<]*?)\s*</(?:strong|b)>")
# "13", "13ac", "7A" (older template's own number+direction, no separator).
_KEY_TOKEN_RE = re.compile(r"^(\d+)(ac|dn|a|d)?\.?$", re.IGNORECASE)
_DIR_FROM_SUFFIX = {"ac": "across", "a": "across", "dn": "down", "d": "down"}


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
        key = _TAG_RE.sub("", cells[0]).strip().rstrip(".")
        if not re.match(r"^\d+[a-z]*(/\d+[a-z]*)*$", key, re.IGNORECASE):
            continue  # not a clue row (e.g. a blank <th> spacer row, or the
                      # "Clue No / Solution / Clue / Logic" column header row)
        strong = _STRONG_RE.search(cells[1])
        raw_answer = strong.group(1) if strong else _TAG_RE.sub("", cells[1]).strip()
        letters = re.sub(r"[^A-Z]", "", html.unescape(raw_answer).upper())
        if letters:
            rows.append((key, direction, letters))
    return rows


_SEE_RE = re.compile(r"^see\s+(\d+)\s*(ac|dn|down|across)\.?\s*(\([\d,]+\))?$", re.IGNORECASE)


def find_link_groups(puzzle):
    """Cyclops links clues by having one carry the enumeration for the whole
    group while the rest read literally "see 4ac." (see module docstring) —
    with no parenthesis, though some older issues also tack their own
    sub-enumeration on afterwards, e.g. "see 13ac. (9)".

    Returns (referencer_of, groups):
      referencer_of: {(num, dir) of a "see..." entry -> (num, dir) it names}
      groups: {leading (num, dir) -> frozenset of every member, leading included}
    """
    referencer_of = {}
    for e in puzzle["entries"]:
        m = _SEE_RE.match(e["clue"].strip())
        if m:
            target_dir = "across" if m.group(2).lower() in ("ac", "across") else "down"
            referencer_of[(e["number"], e["direction"])] = (int(m.group(1)), target_dir)

    groups = {}
    for member, leading in referencer_of.items():
        groups.setdefault(leading, {leading}).add(member)
    return referencer_of, {k: frozenset(v) for k, v in groups.items()}


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

    for key_raw, heading_dir, letters in rows:
        tokens = key_raw.split("/")

        if len(tokens) == 1:
            m = _KEY_TOKEN_RE.match(tokens[0])
            if not m:
                return None, f"'{key_raw}': unparseable clue number"
            num = int(m.group(1))
            suffix = m.group(2)
            direction = _DIR_FROM_SUFFIX[suffix.lower()] if suffix else heading_dir
            if direction is None:
                return None, (f"'{key_raw}' -> {letters}: no direction — no suffix on the "
                               "number and no Across/Down heading seen yet")
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
            err = assign(num, direction, letters, key_raw)
            if err:
                return None, err
            continue

        # A linked group, e.g. "13/15/17" (all across) or "16/27ac" (16 takes
        # the row's own direction, 27 overrides it with the explicit suffix).
        members = []
        for i, tok in enumerate(tokens):
            m = _KEY_TOKEN_RE.match(tok)
            if not m:
                return None, f"'{key_raw}': can't parse group member '{tok}'"
            n = int(m.group(1))
            suffix = m.group(2)
            if suffix:
                d = _DIR_FROM_SUFFIX[suffix.lower()]
            elif i == 0:
                d = heading_dir
            else:
                d = members[0][1]  # unsuffixed members default to the leading one's direction
            if d is None:
                return None, (f"'{key_raw}' -> {letters}: no direction for member '{tok}' — no "
                               "suffix and no Across/Down heading seen yet")
            members.append((n, d))
        leading = members[0]
        expected = groups.get(leading)
        if expected is None or expected != frozenset(members):
            return None, (f"'{key_raw}' -> {letters}: linked group doesn't match the grid "
                           f"(grid links {_clue_id(*leading)} to "
                           f"{sorted(_clue_id(*m) for m in groups.get(leading, ()))}, "
                           f"blog says {sorted(_clue_id(*m) for m in members)})")
        lengths = [entries_by_id[m]["length"] for m in members]
        if sum(lengths) != len(letters):
            return None, (f"'{key_raw}' -> {letters}: {len(letters)} letters but the grid wants "
                           f"{'+'.join(map(str, lengths))} = {sum(lengths)}")
        pos = 0
        for member, length in zip(members, lengths):
            err = assign(member[0], member[1], letters[pos:pos + length], key_raw)
            if err:
                return None, err
            pos += length

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

def puzzle_path(out_dir, num):
    return out_dir / f"{SERIES}-{num}.js"


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
    path = puzzle_path(out_dir, num)
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


def on_disk_numbers(out_dir):
    prefix = f"{SERIES}-"
    return sorted(int(p.stem[len(prefix):]) for p in out_dir.glob(f"{prefix}*.js")
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
        if not dry_run and puzzle_path(out_dir, num).exists():
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
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)

    if args.latest:
        num = find_latest_number()
        if not args.dry_run and puzzle_path(args.out, num).exists():
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
