"""Single-reading clue-text OCR fixes, shared by every filer.

One home for repairs that work on one reading of a line (no second OCR to
vote against), so a fix found on one source reaches all of them. Today that
is the ACROSS / DOWN list heading: read however badly ("DOW'N", "AROSS",
"D0WN", "A C R O S S"), whichever scan, PDF or book it came from.

  heading_of(line)          fuzzy: a line that is the heading alone
  numbered_heading(line)    the same, led by the puzzle's number
  exact_heading(line)       strict spelling, any case, spaced letters, 0 for O
  LEADING_HEADING           regex: a heading opening a line that goes on
  direction(word)           "across" / "down" for any reading of the word
  DIRECTION                 regex source for the word with repeated letters
"""
import re
from difflib import SequenceMatcher

#: The heading word, a letter possibly repeated ("DOwNn") or 0 for O.
DIRECTION = r"(A+C+R+[O0]+S+|D+[O0]+W+N+)"

#: A heading opening a line that carries more after it ("Across 1, ..." or
#: "Clues Across: Foo"): group 2 is the word, match.end() the rest of the line.
LEADING_HEADING = re.compile(r"\s*(clues\s+)?(across|d[o0]wn|acr[o0]ss)\b\W*", re.IGNORECASE)

_EXACT = re.compile(r"^(?:A\s*C\s*R\s*[O0]\s*S\s*S|D\s*[O0]\s*W\s*N)$", re.IGNORECASE)


def direction(word):
    """"across" or "down" for a word already known to be a heading reading."""
    return "across" if word.strip()[:1] in ("A", "a") else "down"


def exact_heading(line):
    """"ACROSS" or "DOWN" for a line spelling the word whole (any case, letters
    spaced out, a zero for the O); else None. For sources whose text is exact."""
    line = line.strip()
    return direction(line).upper() if _EXACT.match(line) else None


#: A list heading led by the puzzle's number: the Telegraph's "No. 18,340
#: ACROSS", read "No. T8,338ACROSS", "Ko. 18.339 ACROSS", "No. 18-340ACROM",
#: "No. 18.339ACR0SS".
NUMBERED_HEADING = re.compile(r"^\W*[NK][o0]\W{0,3}\s*[\dTIl]\d?[,.\-\s]?\d{3}\s*([A-Za-z0']{3,8})\W*$")


def numbered_heading(line):
    """"ACROSS" or "DOWN" for a heading led by the puzzle's number; else None."""
    m = NUMBERED_HEADING.match(line)
    return heading_of(m.group(1)) if m else None


def heading_of(line):
    """"ACROSS" or "DOWN" for a line that is the list's heading alone, read
    however badly ("DOW'N", "DOIN", "AROSS"); else None."""
    letters = re.sub(r"[^A-Za-z]", "", line)
    if len(line) <= 9 and letters in ("Across", "Down"):
        # The Guardian's, in title case: read whole, never guessed at.
        return letters.upper()
    if len(line) > 9 or not 3 <= len(letters) <= 7 or not letters.isupper():
        return None
    for word in ("ACROSS", "DOWN"):
        if SequenceMatcher(None, letters, word).ratio() >= 0.7:
            return word
    return None


