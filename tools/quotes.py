"""Clue text is stored with straight quotes; the site curls them on display.

Sources serve the same apostrophe as ' or ’, and OCR reads one as `, so a
corpus that kept what each source served would hold one clue three ways and
compare them as three clues. Every puzzle file therefore stores ' and " only:
fetch_puzzle.write_puzzle_file straightens every write through straighten(),
puzzle_integrity's CURLY check refuses anything else, and app.js turns them
back into ‘ ’ “ ” when it shows a clue (quotes.js). The static pages and the
social cards curl with curl() here, which has quotes.js's rules; test_quotes.js
runs both over tools/quotes_cases.json, so they cannot drift.

Each quote mapping is one character for one, but a ligature is two or three
("\ufb01" -> "fi"), so straighten() rewrites each clue through
enumeration.rewrite_entry, which moves every offset into it (a definition's
`at`, italics, hiddenLetter) and every phrase its annotation quotes with it.

    python3 tools/quotes.py            # straighten every held puzzle file
    python3 tools/quotes.py FILE...    # just those
"""
import copy
import json
import re
import sys
from pathlib import Path

import wordplay


# A Unicode ligature (a PDF's or OCR's "\ufb01") is its letters: "fi", "ffl".
LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
             "\ufb05": "st", "\ufb06": "st"}
STRAIGHT = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "`": "'", **LIGATURES})
UNLIGATURE = str.maketrans(LIGATURES)
CURLY = frozenset("\u2018\u2019\u201c\u201d`" + "".join(LIGATURES))


# quotes.js's rules, character for character. \s is spelled out because JS and
# Python disagree on which characters it holds.
_SPACE = "\t\n\v\f\r    -     　﻿"
_OPENS_AFTER = re.compile("[" + _SPACE + r"([{—–\-/‘“]")
_ELISION = re.compile(
    r"(?:tis|twas|twere|twill|twould|em|n|til|cause|neath|bout|gainst|nuff|ere|\d\d?s?)(?![A-Za-z])",
    re.I | re.A)


def curl(text):
    """`text` as the page shows it: ' and " curled to ‘ ’ “ ”, one character
    for one, so every offset into the clue still points at the same letter.
    The same rules as quotes.js's curl: ' after a letter or digit is ’; a quote
    at the start or after a space, bracket, dash, slash or opening quote
    opens, except a leading elision ('tis, 'em, '90s), which is ’."""
    s = str(text)
    if "'" not in s and '"' not in s:
        return s
    out = []
    for i, c in enumerate(s):
        if c not in "'\"":
            out.append(c)
            continue
        opens = not i or _OPENS_AFTER.match(out[-1]) is not None
        if c == '"':
            out.append("“" if opens else "”")
        elif not opens or _ELISION.match(s, i + 1):
            out.append("’")
        else:
            out.append("‘")
    return "".join(out)


def unligature(text):
    """`text` with every Unicode ligature spelt as its letters, quotes left as
    printed (a PDF's "stu\ufb00" is "stuff")."""
    return text.translate(UNLIGATURE) if isinstance(text, str) else text


def straight(text):
    """`text` with every curly quote and backtick made ' or ", and every
    Unicode ligature spelt as its letters."""
    return text.translate(STRAIGHT) if isinstance(text, str) else text


def _clue_strings(entry):
    """(holder, key) of every string in `entry` that holds the clue's own
    words: the clue, and each annotation field that quotes it
    (puzzle_integrity.annotation_quotes, features.misdirectedWord, an
    anagram's fodder), which must keep matching it character for character."""
    out = [(entry.get("clue") or {}, "text")]
    ann = entry.get("annotation")
    if isinstance(ann, dict):
        # The definitions, their indicators, and the wordplay tree's
        # indicators and leaf words quote the clue.
        defs = [d for d in ann.get("definitions") or [] if isinstance(d, dict)]
        out += [(d, "text") for d in defs]
        out += [(i, "text") for d in defs for i in d.get("indicators") or [] if isinstance(i, dict)]
        todo = [ann["wordplay"]] if isinstance(ann.get("wordplay"), dict) else []
        while todo:
            node = todo.pop()
            out += [(i, "text") for i in node.get("indicators") or [] if isinstance(i, dict)]
            if "op" not in node:
                out.append((node, "words"))
            todo += [p for p in wordplay.parts_of(node) if isinstance(p, dict)]
        out.append((ann.get("features") or {}, "misdirectedWord"))
    return [(h, k) for h, k in out
            if isinstance(h, list) or (isinstance(h, dict) and isinstance(h.get(k), str))]


def straighten(puzzle):
    """`puzzle` with its clue text straight: itself when it already is, else
    a copy, so the caller's puzzle is left as it was."""
    if not curly(puzzle):
        return puzzle
    import enumeration  # lazy: it imports this module
    puzzle = copy.deepcopy(puzzle)
    mapper = enumeration.translated(STRAIGHT)
    for e in puzzle.get("entries") or []:
        # The clue and every offset and quoted phrase together; then any
        # annotation string the clue's rewrite did not reach.
        enumeration.rewrite_entry(e, mapper)
        for holder, key in _clue_strings(e):
            if isinstance(holder[key], str):
                holder[key] = straight(holder[key])
    return puzzle


def straighten_clues_only(record):
    """A clues-only record (tools/clues_only.py) with its clue text straight:
    itself when it already is, else a copy."""
    lights = [light for d in ("across", "down", "unplaced") for light in (record.get("clues") or {}).get(d) or []]
    if not any(isinstance(l.get("clue"), dict) and isinstance(l["clue"].get("text"), str)
               and CURLY & set(l["clue"]["text"]) for l in lights):
        return record
    record = copy.deepcopy(record)
    for d in ("across", "down", "unplaced"):
        for light in record["clues"].get(d) or []:
            if isinstance(light.get("clue"), dict):
                light["clue"]["text"] = straight(light["clue"].get("text"))
    return record


def curly(puzzle):
    """[(entry, field, text)] of each clue string still holding a curly quote
    or a backtick."""
    out = []
    for e in puzzle.get("entries") or []:
        for holder, key in _clue_strings(e):
            text = holder[key]
            if isinstance(text, str) and CURLY & set(text):
                out.append((e, key, text))
    return out


def main(argv):
    import puzzle_paths
    from fetch_puzzle import read_puzzle_file
    paths = [Path(a) for a in argv] or sorted(puzzle_paths.PUZZLE_DIR.glob("*/*/*.json"))
    files = chars = 0
    for path in paths:
        puzzle = read_puzzle_file(path)
        found = sum(sum(c in CURLY for c in text) for _, _, text in curly(puzzle))
        if not found:
            continue
        body = json.dumps(straighten(puzzle), indent=1, ensure_ascii=False) + "\n"
        path.write_text(body, encoding="utf-8")
        files += 1
        chars += found
    print(f"straightened {chars} quote marks in {files} of {len(paths)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
