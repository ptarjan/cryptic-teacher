"""An OCR'd clue opens with a quote mark only when it is a quotation.

A scan's OCR reads a speck beside a clue's printed number as a quote mark,
and with the mark in front of it the number is no longer read as a number:
book-43001's 5-across was filed as `"5 Covered with a coat and prepared for
stardom perhaps`. The same speck before an unnumbered clue leaves a lone
opening quote that nothing closes ("'Hasten.", '"Recant (anag.).'). A clue
that opens with a quote is legitimate when the quote is closed later
(`'Things are in the — , And ride mankind.' (Emerson)`), and a leading
apostrophe is legitimate as an elision or a dropped h ('Tis, '70s, 'Orrible,
'ampshire).

So, for clue text whose leading quote nothing after it closes (a quote mark
later in the text that is not a contraction's apostrophe: That's, can't,
I'd, we'll, they're, I've, I'm):
  - LEAKED NUMBER: a quote, a one- or two-digit number and a capital
    ("\\"5 Covered", "' 16 Trivial", "'7 It's wrong", "\\"2Foul") loses the
    quote and the number;
  - ATTRIBUTED: a quotation that lost only its closing quote, ending in a
    capitalised attribution ('"Alone and palely — (Keats)'), is closed before
    the attribution ('"Alone and palely —" (Keats)');
  - STRAY DOUBLE: a leading " is dropped ('"Recant (anag.).'), unless an
    elision follows it ('"Tis');
  - STRAY SINGLE: a leading ' is dropped when a space or a capital consonant
    follows it ("' A savage", "'Hasten", "'Track") and it is no elision
    ('Tis, 'Twas, 'Neath, 'Zine). A ' before a vowel or a lower-case letter
    is a dropped h or an elision and stands.
A quote that is closed later is never touched, whatever follows it.

Only an OCR channel's clue (provenance.OCR_CHANNELS, and every clues-only
record, all of them book reads) is mended: a publisher's or a blog's text is
typed, and a number after its quote is the clue's own ("'54 English
railway company's insignia" is LIV-E-RY). The book reader
(parse_penguin_book.parse_clue_chunk) and the newspaper vote
(ocr_clues.trimmed) both finish a clue through clean();
fetch_puzzle.write_puzzle_file and clues_only.write put every OCR write
through normalise(), and puzzle_integrity's LEAD check refuses an OCR clue
clean() would still change. Offsets into the clue move with the text
(enumeration.rewrite_entry).

    python3 tools/leading_quote.py [--dry-run] [--from LIST] [FILE...]
"""
import copy
import json
import os
import re
import sys
from pathlib import Path

import enumeration
import quotes

OCR_CHANNELS = ("newspaper", "book")   # provenance.OCR_CHANNELS, asserted by the test
_QUOTES = "\"'‘’“”`"
_DOUBLE = "\"“”"
_NUMBER = re.compile(r"[ \t]*\d{1,2}[ \t]*[.\-—]?[ \t]*(?=[A-Z])")
_CONTRACTION = re.compile(r"(?:s|t|d|ll|re|ve|m)(?![A-Za-z])")
# Elisions quotes._ELISION does not hold, read before a capital consonant.
_MORE_ELISION = re.compile(
    r"(?:struth|strewth|scuse|spose|fraid|gator|possum|cello|phone|plane|bus|nam|zine)(?![A-Za-z])", re.I)
_CONSONANT = re.compile(r"[ \t]+|[B-DF-HJ-NP-TV-Z]")
_ATTRIBUTION = re.compile(r"(?<=\S)[ \t]*\([ \t]*[A-Z][^()]*\)[ \t.]*$")


def _closed(text):
    """Whether a quote mark after text[0] closes it: any quote but a
    contraction's apostrophe ("That's", "can't")."""
    for i in range(1, len(text)):
        if text[i] in _QUOTES and not (text[i - 1].isalpha() and _CONTRACTION.match(text, i + 1)):
            return True
    return False


def _elided(text):
    return bool(quotes._ELISION.match(text, 1) or _MORE_ELISION.match(text, 1))


def _lead(text):
    """How many leading characters to drop: the quote and whatever space follows it."""
    return len(text) - len(text[1:].lstrip(" \t"))


def _step(text):
    """One mend as (start, end, replacement), or None."""
    if not isinstance(text, str) or len(text) < 2 or text[0] not in _QUOTES or _closed(text):
        return None
    m = _NUMBER.match(text, 1)
    if m:
        return 0, m.end(), ""
    if _elided(text):
        return None
    a = _ATTRIBUTION.search(text)
    if a and text[1:a.start()].strip():
        return a.start(), a.start(), '"' if text[0] in _DOUBLE else "'"
    if not text[1:].strip():
        return None
    if text[0] in _DOUBLE or _CONSONANT.match(text, 1):
        return 0, _lead(text), ""
    return None


def mapped(text):
    """(clean(text), [new offset of each old offset 0..len(text)])."""
    at = list(range(len(text) + 1)) if isinstance(text, str) else []
    for _ in range(4):
        step = _step(text)
        if step is None:
            break
        start, end, new = step
        def move(i):
            return i if i < start else (start + len(new) if i < end else i - (end - start) + len(new))
        at = [move(i) for i in at]
        text = text[:start] + new + text[end:]
    return text, at


def clean(text):
    """`text` without a stray unclosed leading quote or a leaked clue number,
    or with its quotation closed before its attribution."""
    return mapped(text)[0]


def ocr(record):
    """Whether `record` (a puzzle or a clues-only record) is an OCR channel's."""
    return "clues" in record and "entries" not in record or \
        (record.get("source") or {}).get("retrievedFrom") in OCR_CHANNELS


def unclean(puzzle):
    """[(entry, text)] of each OCR clue whose text clean() would change."""
    if not ocr(puzzle):
        return []
    return [(e, t) for e in puzzle.get("entries") or ()
            if isinstance(t := (e.get("clue") or {}).get("text"), str) and clean(t) != t]


def normalise(puzzle):
    """`puzzle` with every OCR clue mended and every offset into it moved:
    itself when nothing changes, else a copy."""
    if not unclean(puzzle):
        return puzzle
    puzzle = copy.deepcopy(puzzle)
    for e in puzzle.get("entries") or ():
        enumeration.rewrite_entry(e, mapped)
    return puzzle


def _lights(record):
    return [l for d in ("across", "down", "unplaced") for l in (record.get("clues") or {}).get(d) or ()
            if isinstance(l, dict) and isinstance(l.get("clue"), dict)]


def unclean_clues_only(record):
    """[(light, text)] of each clues-only light whose text clean() would change."""
    return [(l, t) for l in _lights(record) if isinstance(t := l["clue"].get("text"), str) and clean(t) != t]


def normalise_clues_only(record):
    """A clues-only record (tools/clues_only.py) mended likewise: itself when
    nothing changes, else a copy."""
    if not unclean_clues_only(record):
        return record
    record = copy.deepcopy(record)
    for light in _lights(record):
        enumeration.rewrite_entry(light, mapped)
    return record


def main(argv=None):
    import argparse

    import puzzle_paths
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from", dest="listed", help="a file naming one path a line")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args(argv)
    if args.listed:
        args.files += [l.strip() for l in open(args.listed, encoding="utf-8") if l.strip()]
    paths = [Path(a) for a in args.files] or (
        sorted(puzzle_paths.PUZZLE_DIR.glob("*/*/*.json"))
        + sorted((puzzle_paths.PUZZLE_DIR.parent / "clues_only").glob("**/*.json")))
    files = clues = 0
    for path in paths:
        raw = path.read_text(encoding="utf-8")
        if not any(q in raw for q in ('"text": "\\"', '"text": "\'')):
            continue
        record = json.loads(raw)
        if not isinstance(record, dict):
            continue
        if "entries" in record:
            bad, out = unclean(record), normalise(record)
        else:
            bad, out = unclean_clues_only(record), normalise_clues_only(record)
        if out is record:
            continue
        files += 1
        clues += len(bad)
        for _, t in bad:
            print(f"{path}\t{t!r} -> {clean(t)!r}")
        if not args.dry_run:
            part = path.with_name(f".{path.name}.part")
            part.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(part, path)
    print(f"{clues} clues in {files} files{' (dry run)' if args.dry_run else ''}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
