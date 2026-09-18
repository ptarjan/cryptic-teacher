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
SEE_REFERENCE_RE = re.compile(r"^(?:\d+(?:\s*,\s*\d+)*\s*[,.]?\s*)?See\s+\d+\s*$")
LEADING_NUMBER_RE = re.compile(r"^(\d{1,2}(?:\s*,\s*\d{1,2})*)\s+(?=[A-Z(\"'‘])")


def load_leaves(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.split(FORM_FEED)


def find_puzzle_range(leaves: list[str]) -> tuple[int, int]:
    """Return (start, end) leaf indices spanning "The Puzzles" section,
    end exclusive. Raises ValueError if either boundary can't be found —
    a silent wrong range would corrupt every puzzle downstream."""
    start = None
    for i, leaf in enumerate(leaves):
        if leaf.strip() == PUZZLES_SECTION_TITLE:
            start = i + 1
            break
    if start is None:
        raise ValueError(f"could not find section title {PUZZLES_SECTION_TITLE!r}")

    end = None
    for i in range(start, len(leaves)):
        if SOLUTIONS_MARKER.search(leaves[i]) and len(leaves[i].strip()) < 100:
            end = i
            break
    if end is None:
        raise ValueError("could not find the Solutions section boundary")
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


def classify_clue_leaves(leaves: list[str], start: int, end: int) -> list[int]:
    """A clue leaf is one with many lines ending in a parenthesised
    enumeration — true of both the normal Across/Down layout and the two
    flat "jigsaw" puzzles, and not true of grid/setter leaves or blanks."""
    idxs = []
    for i in range(start, end):
        lines = [ln.strip() for ln in leaves[i].split("\n") if ln.strip()]
        enum_lines = sum(1 for ln in lines if ENUMERATION_RE.search(ln))
        if enum_lines >= 8:
            idxs.append(i)
    return idxs


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
    where real clue content begins. Returns (index, mode)."""
    for i, line in enumerate(lines):
        if line.strip() == "Across":
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
        number = m.group(1).replace(" ", "")
        text = text[m.end():]

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
    down_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "Down":
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
