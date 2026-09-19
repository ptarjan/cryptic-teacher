#!/usr/bin/env python3
"""Parse the OCR text of "The New Penguin Book of The Guardian Crosswords 5"
into structured puzzle records, plus an honest per-puzzle quality report.

Input is the raw OCR dump produced by tools/fetch_ia_book.py for
newpenguinbkguar0000perk (never committed — it's a fetched artifact). Pages
are separated by form-feed (\\f). This is EXTRACTION ONLY: it does not touch
puzzles/, the corpus, or the site index, and it writes nowhere but the paths
given on the command line.

  python3 tools/parse_penguin_book.py IN.txt --out /tmp/penguin_puzzles.json \\
      --report-out /tmp/penguin_quality.json

BOOK LAYOUT (measured against this scan, 2026-09-18). Leaf 7 is the section
title "The Puzzles"; leaf 129 is the first leaf of "Solutions" (whose pages
are unreadable OCR of answer-grid IMAGES and are never read by this script).
Between them, puzzles alternate one CLUE leaf (an "Across"/"Down" clue list,
or for two Araucaria specials a flat "jigsaw" list introduced by "Method:")
followed by one GRID leaf (the grid image, OCR'd as noise, with the setter's
name usually the one clean line on it, and the printed page number as its
last line). This scan has 60 such pairs, not the 58 the book is nominally
described as containing — see COUNT DISCREPANCY below. Puzzle numbers are
assigned by POSITION (1..N, gapless, one per pair) rather than by reading the
book's own printed heading digit, because that heading is one of the worst-
OCR'd tokens in the whole scan (e.g. "4]" for 41, "a3" for 33, "NONNNAWN—"
for what sequence says must be 59) — position is load-bearing here, the
printed digit is corroboration only, kept as raw_number_ocr for that purpose.

COUNT DISCREPANCY: the task brief says 58 puzzles numbered 1-58. Structural
detection here (a clean, gapless run of clue-leaf/grid-leaf pairs from leaf 8
to leaf 127) finds 60. The last two are numbered 59 (leaf 124's heading OCRs
as "39" — a plausible 5/3 OCR confusion, not a break in sequence) and 60
(leaf 127's heading OCRs cleanly as "60"). This script reports what it finds
structurally rather than truncating to match the brief; see the parser's
printed summary and PENGUIN_BOOK_COUNT in the quality report for the number
actually produced by a given run.

CLUE SEGMENTATION. Only ~10 of the ~58-60 puzzle blocks kept their clue
numbers; enumerations "(7)", "(3,4)" etc. survived far better. So a clue
boundary is anchored on the enumeration at its END (or, for a linked
cross-reference clue like "17 See 15", on that reference pattern instead,
since such clues have no enumeration of their own by design) rather than on
a leading number, which is often simply gone. A leading number is captured
opportunistically when present; when absent it is left null — NEVER guessed
or interpolated (a fabricated number is worse than a missing one).

LAYOUT VARIANTS. The Penguin volumes are not the only print convention in
this series of scans, and the differences are typographic, not OCR damage —
the next book set in the same style will hit them all again, so they are
handled as variants of the shared patterns and nothing here is ever keyed to
an identifier. The one that had to be added second, the DOTTED-NUMBER LAYOUT,
prints:

  "Cryptic Across"     the running head glued onto the header line
  "13. Clue text"      dotted clue numbers
  "1 & 4 Ac. Clue"     linked clues with & and an explicit direction
  "13. See 14 Across"  cross-references that name the direction too
  ". Clue text"        what a dotted number leaves when OCR eats the digits

Counted over the 33 book scans on hand (2026-09-18): dotted numbers in 12 of
them, glued running heads in 8, direction-bearing cross-references in 9 — so
this is a convention, not a quirk. Untreated it is not a partial loss but a
total one in two stages: no header matches, so every puzzle in the book falls
through to jigsaw mode and loses its Across/Down split; and no leading number
matches, so clue-number recovery is 0%.

Measured on crypticcrossword0000unse, which prints all five forms: 17 of 17
puzzles fell to jigsaw mode before and 0 of 17 do after, and clue-number
recovery went from 0/394 to 68/401. That 17% is the honest ceiling, not a
shortfall: only 71 of this scan's printed numbers survived OCR as digits at
all (the rest are the ". Clue text" case, where the digit is simply gone and
inventing it would be worse than leaving it null), and 68 of those 71 are
recovered. Of the three not recovered, two are not clue numbers at all —
"1,000 request face-covering (4)" and "100 resigned..." are clue TEXT that
opens with a number, and are meant to be left alone.

GRID-BLEED NOISE. The facing grid-image page's OCR garbage sometimes leaks
onto the clue leaf (and vice versa) as a stray line with no real word in it
("23eS8ee 11", "DNPONADANRWN"). is_garbage_line() drops these before
segmentation using a case-transition heuristic: real words don't flip
upper/lower case mid-token more than once, OCR grid noise does constantly.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

FORM_FEED = "\f"

PUZZLES_SECTION_TITLE = "The Puzzles"
SOLUTIONS_MARKER = re.compile(r"\bSolutions\b")  # capital S: skips lowercase
# "solution(s)" occurring inside real clue text (confirmed: leaves 20, 30,
# 46, 106, 126 all use the lowercase word legitimately).

# Vols 2/3/7/11 have no "Solutions" banner leaf, but their answer-grid
# images are individually labelled "No. <n>" (the book's own puzzle
# number) wherever that OCR'd cleanly — used only as a refinement of the
# structural end-of-puzzles boundary in find_puzzle_range, never required.
SOLUTIONS_NO_MARKER_RE = re.compile(r"\bNo\.\s*\d+")

# Setters confirmed present by direct observation: either named in the task
# brief, or found as a clean, dictionary-plausible standalone line on a grid
# leaf (see the tally this was built from in the parser's own git history —
# not repeated here, this list IS the finding).
KNOWN_SETTERS = {
    "Rufus", "Araucaria", "Custos", "Gordius", "Enigmatist", "Bunthorne",
    "Shed", "Fidelio", "Crispa", "Janus", "Hendra", "Pasquale", "Orlando",
    "Logodaedalus", "Quantum", "Fawley", "Mercury", "Gemini",
}

# Trailing punctuation after the closing paren is deliberately permissive
# (up to 4 non-word, non-paren characters) rather than a fixed [.:!?]: a
# stray OCR artifact like the "<" that follows a perfectly good "(6)" on
# puzzle 49's last down clue must not cost a real, legible enumeration.
ENUMERATION_RE = re.compile(r"\(([\d]+(?:[\s,\-][\d]+)*)\)[^\w()]{0,4}$")
# The trailing direction ("See 14 Across") is the DOTTED-NUMBER LAYOUT's way
# of writing what the Penguin volumes write as "See 14" — same clue, one more
# printed word. Without it the line closes no chunk and silently glues itself
# onto the next clue, costing two clues instead of one.
SEE_REFERENCE_RE = re.compile(
    r"^(?:\d+(?:\s*,\s*\d+)*\s*[,.]?\s*)?See\s+\d+"
    r"\s*(?:Across|Down|Ac|Dn)?\b\.?\s*$")
# The lookahead's job is only to reject a bare digit run that isn't
# actually a clue number (grid-bleed noise, a number embedded mid-sentence)
# — requiring the very next character start a word/paren/quote is enough
# for that; requiring it be UPPERCASE additionally is not protecting
# against anything, it just throws away real numbers on real clues whose
# first letter OCR lowercased (guardiancrosswor0000perk, the 1974 book,
# does this constantly: "1 perehing clear..." is a genuine numbered clue
# with garbled text, not noise). Confirmed by direct comparison: broadening
# this to accept lowercase changes zero numbered-clue counts on vols
# 2/3/5/7/11 (their surviving leading numbers are followed by capitalised
# clue text) and recovers real numbers on the 1974 book that the
# upper-case-only version was dropping.
# Three spellings of the same thing, all live in the scans on hand:
#   "13 Clue text"      the Penguin volumes
#   "13. Clue text"     the DOTTED-NUMBER LAYOUT (see LAYOUT VARIANTS above)
#   "1 & 4 Ac. Clue"    a linked pair in that same layout, where the Penguin
#                       volumes print "1,4"
# The space before the direction is optional because the books print it both
# ways ("8 & 17 Ac." and "8 & 17Ac."). What keeps that from eating clue text
# is the \b after the direction word, not the space: "5 Acid test (4)" keeps
# its number and every letter of its text, because "Ac" followed by "id" is
# not a word boundary. The direction is consumed rather than captured, since
# which way a linked partner runs is already fixed by the header the clue
# sits under. Two-digit numbers only, so a clue whose TEXT opens with a
# number ("1,000 request face-covering (4)") is left alone rather than being
# renumbered into nonsense.
LEADING_NUMBER_RE = re.compile(
    r"^(\d{1,2}(?:\s*[,&]\s*\d{1,2})*)"
    r"(?:\s*(?:Across|Down|Ac|Dn)\b\.?)?"
    r"\s*\.?\s+(?=[A-Za-z(\"'‘])")

# A dotted number whose digits the OCR lost outright, leaving the printed dot
# behind (". Partly open a container (4)"). The number is gone and is never
# invented; the orphan dot is not clue text either, so it is dropped rather
# than filed as the first character of the clue.
ORPHAN_NUMBER_DOT_RE = re.compile(r"^\.\s+(?=[A-Za-z(\"'‘])")

# "ACROSS"/"DOWN" headers on guardiancrosswor0000perk sometimes OCR with a
# stray leading glyph from the facing grid bleeding onto the same leaf
# ("| ACROSS", "— ACROSS") since, unlike the Penguin volumes, this book has
# no separate grid leaf to absorb that noise — the grid and clue text share
# one page. A tolerant match (up to 3 non-letters on either side) recovers
# these as real headers instead of falling through to the jigsaw-detection
# path and losing the Across/Down split entirely.
HEADER_RE = re.compile(r"^[^A-Za-z0-9]{0,3}(ACROSS|DOWN)[^A-Za-z0-9]{0,3}$", re.IGNORECASE)

# The DOTTED-NUMBER LAYOUT prints its running head on the header line itself
# ("Cryptic Across", and where the OCR mangled the head, "CryBHE Across"), so
# nothing anchored at the start of the line can match it. The head is one or
# two purely alphabetic words: requiring that — no digits anywhere — is what
# keeps "13. See 14 Across", a real cross-reference clue printed in this very
# layout, from being read as a section header and throwing away every clue
# above it. A head that is itself the word "See" is rejected in _header_kind
# for the same reason, since OCR does lose the leading number.
GLUED_HEAD_RE = re.compile(
    r"^(?P<head>(?:[A-Za-z]{2,12}[^A-Za-z0-9\s]{0,2}\s+){1,2})"
    r"(ACROSS|DOWN)[^A-Za-z0-9]{0,3}$",
    re.IGNORECASE)


def _header_kind(line: str) -> str | None:
    line = line.strip()
    m = HEADER_RE.match(line)
    if m:
        return m.group(1).upper()
    m = GLUED_HEAD_RE.match(line)
    if m and "see" not in m.group("head").lower():
        return m.group(2).upper()
    return None


def load_leaves(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.split(FORM_FEED)


def find_puzzle_range(leaves: list[str]) -> tuple[int, int]:
    """Return (start, end) leaf indices spanning the puzzle section, end
    exclusive. Raises ValueError if no start boundary can be found at all —
    a silent wrong range would corrupt every puzzle downstream.

    START: vol 5 (newpenguinbkguar0000perk) prints an explicit "The
    Puzzles" section-title leaf, tried first. Some other scans in this
    series (vol 2) carry no title leaf at all — the Foreword runs straight
    into the first "Across" clue leaf. When the title is absent, start
    falls back to the first leaf in the whole book that looks like a real
    clue leaf (classify_clue_leaves' own >=8-enumeration-lines test,
    applied here before any range is known).

    END: vol 5 has a "Solutions" banner leaf. Other scans in this series
    (vols 2 and 3, confirmed by direct inspection) have neither a
    "Solutions" banner nor any other title text marking the boundary — the
    section just ends and answer-grid-image OCR noise follows. For those,
    end falls back to the first later leaf carrying a printed "No. <n>"
    solution-grid label if the OCR caught one (vol 2 has these; vol 3
    doesn't), and only if that also comes up empty, to the last clue-like
    leaf's own immediate trailing leaf — never guessed beyond what's
    actually in the text."""
    start = None
    for i, leaf in enumerate(leaves):
        if leaf.strip() == PUZZLES_SECTION_TITLE:
            start = i + 1
            break

    end = None
    if start is not None:
        for i in range(start, len(leaves)):
            if SOLUTIONS_MARKER.search(leaves[i]) and len(leaves[i].strip()) < 100:
                end = i
                break

    if start is None or end is None:
        clue_like = [i for i, leaf in enumerate(leaves) if _looks_like_clue_leaf(leaf)]
        if not clue_like:
            raise ValueError(
                f"could not find section title {PUZZLES_SECTION_TITLE!r}, and "
                "no leaf in the whole book looks like a clue leaf either "
                "(>=8 enumeration-terminated lines) — can't locate the "
                "puzzle region at all"
            )
        if start is None:
            start = clue_like[0]
        if end is None:
            for i in range(clue_like[-1] + 1, len(leaves)):
                if SOLUTIONS_NO_MARKER_RE.search(leaves[i]):
                    end = i
                    break
            if end is None:
                end = min(clue_like[-1] + 2, len(leaves))
    return start, end


def _case_transitions(token: str) -> int:
    """Count upper<->lower flips within a run of letters, ignoring digits.
    A real word has at most one (Title case); OCR grid noise flips
    constantly ("eS8ee", "AWwWnd")."""
    letters = [c for c in token if c.isalpha()]
    flips = 0
    for a, b in itertools.pairwise(letters):
        if a.isupper() != b.isupper():
            flips += 1
    return flips


def _vowel_ratio(token: str) -> float:
    letters = [c for c in token if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.lower() in "aeiou") / len(letters)


def is_garbage_line(line: str) -> bool:
    """Heuristic filter for grid-image OCR bleed onto a clue leaf (or a
    stray leaf/page number). A line is kept if it has at least one token
    that reads like a real word (3+ letters, at most one case flip); the
    enumeration and cross-reference patterns are always kept regardless,
    since they carry real clue-structural information even when short.

    A lone single-word line under 5 letters is dropped even if it passes
    that check (e.g. "Jbl", trailing off the end of a clue leaf after its
    last real clue already closed on its own enumeration): a genuine
    OCR-wrapped clue continuation is essentially never exactly one short
    word by itself, but that is exactly the shape one-off grid-bleed noise
    takes once the case-transition heuristic alone lets it through."""
    stripped = line.strip()
    if not stripped:
        return True
    if stripped in ("Across", "Down"):
        return False
    if ENUMERATION_RE.search(stripped) or SEE_REFERENCE_RE.match(stripped):
        return False
    words = stripped.split()
    if len(words) == 1 and len(re.sub(r"[^A-Za-z]", "", words[0])) < 5:
        return True
    for token in re.findall(r"[A-Za-z]+", stripped):
        if len(token) < 3 or _case_transitions(token) > 1:
            continue
        # A 5+ letter token with no case flips still needs a plausible
        # vowel ratio: all-caps grid noise ("NAYDHDN") has zero flips by
        # construction (nothing to flip between) but reads nothing like
        # English, unlike a real word or acronym-adjacent capitalised term.
        if len(token) >= 5 and _vowel_ratio(token) < 0.2:
            continue
        return False
    return True


def _looks_like_clue_leaf(leaf: str) -> bool:
    """A clue leaf is one with many lines ending in a parenthesised
    enumeration — true of both the normal Across/Down layout and the two
    flat "jigsaw" puzzles, and not true of grid/setter leaves or blanks.
    Shared by classify_clue_leaves (within a known range) and
    find_puzzle_range's structural fallback (over the whole book, when
    there's no title leaf to bound the range first)."""
    lines = [ln.strip() for ln in leaf.split("\n") if ln.strip()]
    enum_lines = sum(1 for ln in lines if ENUMERATION_RE.search(ln))
    return enum_lines >= 8


def classify_clue_leaves(leaves: list[str], start: int, end: int) -> list[int]:
    return [i for i in range(start, end) if _looks_like_clue_leaf(leaves[i])]


def group_into_puzzles(clue_idxs: list[int], end: int) -> list[tuple[int, list[int]]]:
    """Pair each clue leaf with the (grid/setter) leaves before the next
    clue leaf — normally exactly one leaf, occasionally zero (a fully
    blank grid page) or more."""
    groups = []
    for pos, idx in enumerate(clue_idxs):
        next_idx = clue_idxs[pos + 1] if pos + 1 < len(clue_idxs) else end
        trailing = list(range(idx + 1, next_idx))
        groups.append((idx, trailing))
    return groups


def extract_setter(leaves: list[str], trailing_idxs: list[int]) -> str | None:
    for i in trailing_idxs:
        for line in leaves[i].split("\n"):
            candidate = line.strip()
            if candidate in KNOWN_SETTERS:
                return candidate
    return None


def find_content_start(lines: list[str]) -> tuple[int, str]:
    """Skip leading noise (page-number/grid bleed) on a clue leaf to find
    where real clue content begins. Returns (index, mode).

    Tolerant on "Across" via _header_kind: the Penguin volumes (2/3/5/7/11)
    print it title-case cleanly, but the 1974 Hodder book
    (guardiancrosswor0000perk) prints "ACROSS"/"DOWN" in caps, on the same
    leaf as its grid rather than a separate clue leaf, and sometimes with a
    stray OCR glyph stuck to it ("| ACROSS") — one tolerant check covers
    both instead of a second layout-specific code path."""
    for i, line in enumerate(lines):
        if _header_kind(line) == "ACROSS":
            return i + 1, "across_down"
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("method:"):
            # The instruction runs on to a second line before a blank line
            # ("...into the / diagram jigsaw-wise, wherever they will go.");
            # skip through to that blank line so it doesn't get glued onto
            # the first real clue.
            j = i + 1
            while j < len(lines) and lines[j].strip():
                j += 1
            return j + 1, "jigsaw"
    for i, line in enumerate(lines):
        if ENUMERATION_RE.search(line.strip()):
            return i, "jigsaw"
    return len(lines), "unparsed"


def segment_clues(lines: list[str]) -> list[str]:
    """Join wrapped lines into one raw chunk per clue, boundary-anchored on
    the enumeration (or a "See N" cross-reference) at the END of a clue,
    since leading numbers are the field OCR damaged worst."""
    chunks = []
    current: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or is_garbage_line(line):
            continue
        current.append(line)
        if ENUMERATION_RE.search(line) or SEE_REFERENCE_RE.match(line):
            chunks.append(" ".join(current))
            current = []
    if current:
        # Trailing text with no enumeration ever closed it — OCR loss, not
        # a clue to silently drop. Keep it so the quality report can count
        # it as an incomplete clue rather than the parser hiding it.
        chunks.append(" ".join(current))
    return chunks


def parse_clue_chunk(chunk: str) -> dict:
    text = chunk
    number = None
    m = LEADING_NUMBER_RE.match(text)
    if m:
        number = m.group(1).replace(" ", "").replace("&", ",")
        text = text[m.end():]
    else:
        text = ORPHAN_NUMBER_DOT_RE.sub("", text)

    enumeration = None
    enum_m = ENUMERATION_RE.search(text)
    if enum_m:
        enumeration = enum_m.group(1).replace(" ", "")
        text = text[: enum_m.start()].rstrip()
    elif SEE_REFERENCE_RE.match(text.strip()):
        enumeration = None  # by design: a cross-reference clue has none

    return {
        "number": number,
        "clue": text.strip(" ,"),
        "enumeration": enumeration,
    }


def split_across_down(lines: list[str]) -> tuple[list[str], list[str]]:
    """Tolerant on "Down" via _header_kind, for the same reason as
    find_content_start's "Across" check — see its docstring."""
    down_idx = None
    for i, line in enumerate(lines):
        if _header_kind(line) == "DOWN":
            down_idx = i
            break
    if down_idx is None:
        return lines, []
    return lines[:down_idx], lines[down_idx + 1:]


def build_puzzle(seq_number: int, clue_leaf_idx: int, trailing_idxs: list[int],
                  leaves: list[str]) -> dict:
    raw_lines = leaves[clue_leaf_idx].split("\n")
    content_start, mode = find_content_start(raw_lines)
    raw_number_ocr = raw_lines[0].strip() if raw_lines and raw_lines[0].strip() else None
    content_lines = raw_lines[content_start:]

    setter = extract_setter(leaves, trailing_idxs)

    record: dict = {
        "book_number": seq_number,
        "raw_number_ocr": raw_number_ocr,
        "setter": setter,
        "mode": mode,
        "source_leaves": {"clue": clue_leaf_idx, "trailing": trailing_idxs},
    }

    if mode == "across_down":
        across_lines, down_lines = split_across_down(content_lines)
        record["across"] = [parse_clue_chunk(c) for c in segment_clues(across_lines)]
        record["down"] = [parse_clue_chunk(c) for c in segment_clues(down_lines)]
    elif mode == "jigsaw":
        record["clues"] = [parse_clue_chunk(c) for c in segment_clues(content_lines)]
        record["across"] = []
        record["down"] = []
    else:
        record["across"] = []
        record["down"] = []

    return record


def parse_book(text_path: Path) -> list[dict]:
    leaves = load_leaves(text_path)
    start, end = find_puzzle_range(leaves)
    clue_idxs = classify_clue_leaves(leaves, start, end)
    groups = group_into_puzzles(clue_idxs, end)
    return [
        build_puzzle(seq, clue_idx, trailing, leaves)
        for seq, (clue_idx, trailing) in enumerate(groups, start=1)
    ]


def _clue_stats(clues: list[dict]) -> dict:
    total = len(clues)
    numbered = sum(1 for c in clues if c["number"])
    enumerated = sum(1 for c in clues if c["enumeration"])
    empty_text = sum(1 for c in clues if not c["clue"])
    return {
        "count": total,
        "numbered": numbered,
        "enumerated": enumerated,
        "empty_text": empty_text,
    }


def build_quality_report(puzzles: list[dict]) -> dict:
    per_puzzle = []
    complete_count = 0
    for p in puzzles:
        if p["mode"] == "jigsaw":
            clue_stats = _clue_stats(p["clues"])
            across_stats = down_stats = None
        else:
            across_stats = _clue_stats(p["across"])
            down_stats = _clue_stats(p["down"])
            clue_stats = None

        total_clues = (
            clue_stats["count"] if clue_stats
            else across_stats["count"] + down_stats["count"]
        )
        total_enumerated = (
            clue_stats["enumerated"] if clue_stats
            else across_stats["enumerated"] + down_stats["enumerated"]
        )
        total_numbered = (
            clue_stats["numbered"] if clue_stats
            else across_stats["numbered"] + down_stats["numbered"]
        )
        total_empty = (
            clue_stats["empty_text"] if clue_stats
            else across_stats["empty_text"] + down_stats["empty_text"]
        )

        enum_fraction = total_enumerated / total_clues if total_clues else 0.0
        numbered_fraction = total_numbered / total_clues if total_clues else 0.0

        # No independent count of "how many clues this grid should have" is
        # available — the Solutions section is unreadable grid-image OCR,
        # so there is nothing to check the extracted count against. A fixed
        # "normal" clue-count floor was tried here and rejected: puzzle 23
        # (Enigmatist, a 13-across/10-down thematic grid) is a genuinely
        # complete 23-clue puzzle that such a floor would have mislabelled
        # as damaged purely for having a nonstandard, but real, shape. Only
        # a floor low enough to catch actual breakage (most of a puzzle
        # missing) is used, and only as an informational flag, never to
        # drive confidence down on its own.
        unusually_short = total_clues < 15

        if p["mode"] == "unparsed" or total_clues == 0 or total_empty > 0:
            confidence = "low"
        elif enum_fraction >= 0.9:
            confidence = "high" if numbered_fraction >= 0.9 else "medium"
        else:
            confidence = "low"

        reconstructable = enum_fraction >= 0.95 and total_empty == 0 and total_clues > 0
        if reconstructable:
            complete_count += 1

        per_puzzle.append({
            "book_number": p["book_number"],
            "raw_number_ocr": p["raw_number_ocr"],
            "setter": p["setter"],
            "mode": p["mode"],
            "across": across_stats,
            "down": down_stats,
            "flat_clues": clue_stats,
            "total_clues": total_clues,
            "enumeration_fraction": round(enum_fraction, 3),
            "numbered_fraction": round(numbered_fraction, 3),
            "confidence": confidence,
            "unusually_short": unusually_short,
            "reconstructable_without_numbers": reconstructable,
        })

    return {
        "penguin_book_count": len(puzzles),
        "note_on_count": (
            "Task brief said 58 puzzles numbered 1-58; structural detection "
            f"in this run found {len(puzzles)} clue/grid leaf pairs. See the "
            "module docstring (COUNT DISCREPANCY) for the evidence."
        ),
        "reconstructable_count": complete_count,
        "puzzles": per_puzzle,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("text_path", type=Path, help="OCR .txt from fetch_ia_book.py")
    ap.add_argument("--out", type=Path, required=True, help="puzzles JSON out path")
    ap.add_argument("--report-out", type=Path, required=True,
                     help="quality report JSON out path")
    args = ap.parse_args()

    puzzles = parse_book(args.text_path)
    report = build_quality_report(puzzles)

    args.out.write_text(json.dumps(puzzles, indent=2, ensure_ascii=False), encoding="utf-8")
    args.report_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"parsed {len(puzzles)} puzzles -> {args.out}", file=sys.stderr)
    print(f"quality report -> {args.report_out}", file=sys.stderr)
    print(f"reconstructable (no-number-ok): {report['reconstructable_count']}/{len(puzzles)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
