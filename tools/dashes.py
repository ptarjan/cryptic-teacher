"""Clue text spells a dash between words " — " and an ellipsis "…".

Sources print the same dash as " — " (Times, Telegraph), " – " (FT, Azed),
" - " (the Guardian's older feed, scans), "--" (typewritten blogs) or a
book's closed-up "word—word", and the same ellipsis as "…", "..." or
". . .", so a corpus that kept what each served would hold one clue five
ways. Every puzzle file therefore stores one spelling of each, as it does
straight quotes (tools/quotes.py): fetch_puzzle.write_puzzle_file puts every
write through normalise(), puzzle_integrity's DASH check refuses a clue that
normalise() would still change, and the site shows the text as stored.

A dash between words, in any spelling, becomes HOUSE (" — "), the dash the
book/scan vote also writes (ocr_clues.dash_voted):
  - spaced both sides: "-", "--", "---", "–", "—", "―" or "−";
  - spaced one side: "--", "---", "–", "—" or "―" (a lone "-" is a hyphen
    broken at a line end: "pit- workers", "pot -boiler");
  - closed up: "—" or "―" alone (an en dash closed up is a hyphen or a
    range: "so–and–so", "5–10").
"Between words" means a word, a closing bracket, quote or stop before it and
a word or quote after it. Left alone:
  - a hyphen inside a word ("20-look", "Press-cutting");
  - a dash at the clue's start or end: a continued clue's leader or
    trailer ("— and 5", "See 7 —");
  - a run of dashes ("——", "———-", "----"): a blank, the print's long
    rule;
  - a dash before a bracket or a mark ("Jades of - (2 Hen. IV)", "Cry —!",
    "Soap and — . . ."), or closed up on a quote it is inside ("'—rank and
    gross'", "like smiling --\""): a blank for the quotation's missing words;
  - a dash closed up on a one-letter word ("b— off", "b-- off", "I—I",
    "—k off"): a bowdlerised word or a stammer.
A blank printed " — " between words ("Thus — doth make") is already the
house form, so no rule has to tell it from a dash.

An ellipsis is ELLIPSIS ("…"), one character, from any run of three or more
stops, spaced or not ("...", ". . .", "...."). One character because the
corpus's other marks are typeset ones (the house dash is " — "), because the
publisher feeds that serve most clues (the Guardian, the Times) serve "…",
and because a run of stops is also how a scan misreads specks, so "…" says
the print had an ellipsis. Two stops ("..") are left alone: a speck as often
as a mark.

Unlike straightening quotes, these change the clue's length, so every offset
into it moves with the text (enumeration.rewrite_entry: italics, definition
offsets, hiddenLetter, the annotation's quoted phrases).

    python3 tools/dashes.py [--dry-run] [FILE...]   # every held puzzle and clues-only file, or just those
"""
import copy
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enumeration

HOUSE = " \u2014 "
ELLIPSIS = "\u2026"

_SP = " \u00a0\u2009\u200a\u202f"  # a space, no-break, thin, hair, narrow no-break
_MARKS = "-\u2013\u2014\u2015\u2212"  # hyphen, en, em, bar, minus
_DASH = re.compile(
    "(?<=[\\w)\\]!?.,;:'\"…])"         # a word, or what closes one, before
    f"(?P<l>[{_SP}]*)"
    f"(?<![{_MARKS}])(?P<d>-+|[{_MARKS[1:]}])(?![{_MARKS}])"
    f"(?P<r>[{_SP}]*)"
    "(?=[\\w'\"])")                         # a word, or a quote opening one, after
_STOPS = re.compile(f"\\.(?:[{_SP}]?\\.){{2,}}")


def _at_map(text, spans):
    """(text with each (start, end, new) of `spans` replaced, [new offset of
    each old offset 0..len(text)]). An old offset inside a replaced span
    moves to the same place in its replacement, clipped to it."""
    out, at, pos, size = [], [], 0, 0
    for start, end, new in spans:
        at.extend(size + k for k in range(start - pos))
        size += start - pos
        at.extend(size + min(k, len(new)) for k in range(end - start))
        out += [text[pos:start], new]
        size += len(new)
        pos = end
    at.extend(size + k for k in range(len(text) - pos + 1))
    out.append(text[pos:])
    return "".join(out), at


def _one_letter(text, i, step):
    """Whether text[i] is a word of one letter, read from i in direction `step`."""
    j = i + step
    return text[i].isalnum() and not (0 <= j < len(text) and text[j].isalnum())


def _gap(m, text):
    """Whether dash match `m` in `text` is a dash between words."""
    left, right, d = m.group("l"), m.group("r"), m.group("d")
    if set(d) == {"-"} and len(d) > 3:
        return False
    if left and right:
        return True
    if d in ("-", "\u2212") or not left and not right and d not in "\u2014\u2015":
        return False
    before, after = m.start() - 1, m.end()
    if not left and (text[before] in "'\"" or _one_letter(text, before, -1)):
        return False
    return not (left and (not text[after].isalnum() or _one_letter(text, after, 1)))


def _dash_spans(text):
    return [(m.start(), m.end(), HOUSE) for m in _DASH.finditer(text)
            if _gap(m, text) and m.group(0) != HOUSE]


def mapped(text):
    """(`text` with its dashes between words HOUSE and its ellipses
    ELLIPSIS, [new offset of each old offset 0..len(text)])."""
    if not isinstance(text, str) or not text:
        return text, list(range(len(text or "") + 1))
    first, at1 = _at_map(text, _dash_spans(text))
    second, at2 = _at_map(first, [(m.start(), m.end(), ELLIPSIS) for m in _STOPS.finditer(first)])
    return second, [at2[i] for i in at1]


def normal(text):
    """`text` with its dashes and ellipses in the house spelling."""
    return mapped(text)[0]


def unnormal(puzzle):
    """[(entry, text)] of each clue whose text normal() would change."""
    return [(e, t) for e in puzzle.get("entries") or ()
            if isinstance(t := (e.get("clue") or {}).get("text"), str) and normal(t) != t]


def normalise(puzzle):
    """`puzzle` with its clue text's dashes and ellipses in the house spelling
    and every offset into it moved: itself when it already is, else a copy,
    so the caller's puzzle is left as it was."""
    if not unnormal(puzzle):
        return puzzle
    puzzle = copy.deepcopy(puzzle)
    for e in puzzle.get("entries") or ():
        enumeration.rewrite_entry(e, mapped)
    return puzzle


def normalise_clues_only(record):
    """A clues-only record (tools/clues_only.py) with its clue text in the
    house spelling: itself when it already is, else a copy."""
    lights = [l for d in ("across", "down") for l in (record.get("clues") or {}).get(d) or ()]
    if not any(isinstance(t := (l.get("clue") or {}).get("text"), str) and normal(t) != t
               for l in lights if isinstance(l.get("clue"), dict)):
        return record
    record = copy.deepcopy(record)
    for d in ("across", "down"):
        for light in record["clues"].get(d) or ():
            if isinstance(light.get("clue"), dict):
                enumeration.rewrite_entry(light, mapped)
    return record


def main(argv=None):
    import argparse

    import puzzle_paths
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args(argv)
    paths = [Path(a) for a in args.files] or (
        sorted(puzzle_paths.PUZZLE_DIR.glob("*/*/*.json"))
        + sorted((puzzle_paths.PUZZLE_DIR.parent / "clues_only").glob("**/*.json")))
    files = clues = 0
    for path in paths:
        raw = path.read_text(encoding="utf-8")
        if not any(c in raw for c in "-\u2013\u2014\u2015\u2212."):
            continue
        record = json.loads(raw)
        if not isinstance(record, dict):
            continue
        if "entries" in record:
            n, out = len(unnormal(record)), normalise(record)
        else:
            out = normalise_clues_only(record)
            n = sum(a["clue"]["text"] != b["clue"]["text"]
                    for d in ("across", "down")
                    for a, b in zip((record.get("clues") or {}).get(d) or (), (out.get("clues") or {}).get(d) or ())
                    if isinstance(a.get("clue"), dict) and "text" in a["clue"])
        if out is record:
            continue
        files, clues = files + 1, clues + n
        if not args.dry_run:
            part = path.with_name(f".{path.name}.part")
            part.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(part, path)
    print(f"{'would normalise' if args.dry_run else 'normalised'} {clues} clues in {files} of {len(paths)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
