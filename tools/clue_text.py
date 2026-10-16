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
  COUNT_BODY, COUNT_END, COUNT_INSIDE, is_count_end(line)
                            a clue's "(5,3)" count, its digits read as letters
  mend_count(line)          a count torn at a line's end, read whole again
  see_numeral(text)         "See I3" / "(seel3" put back as "See 13"
  as_digits(text, s)        letters for numerals ("I3", "lO") put back in digits
  HEADING_LINE              regex (MULTILINE): whole lines that are a heading
  CAPS_HEADING              regex: ACROSS / DOWN in capitals inside a line
  HEADING_BEFORE_ONE        regex: a heading opening the text before clue 1
  HEADING_AFTER_COUNT       regex: a capitals heading closing a line after a count
  ones_read(text)           "l9th" / "I3" for a numeral's lone 1 read as a letter
  strip_count(text)         the text without the count ending it, torn or whole
  is_stray_count(line)      a line of only a torn count's tail ("U0).")
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


#: A whole line that is a heading, however the word was read, "Clues" and
#: marks about it allowed ("CLUES ACROSS:", "D0WN"); use with MULTILINE text.
HEADING_LINE = re.compile(rf"^\W*(?:clues\s+)?{DIRECTION}\W*$", re.IGNORECASE | re.MULTILINE)

#: ACROSS or DOWN in capitals inside a line: no clue prints that, so it is
#: a list's heading read into one.
CAPS_HEADING = re.compile(r"(?<![\w'])(?:ACROSS|D[O0]WN)(?![\w'])")

#: A heading, in any case, opening the text before the first clue's number,
#: that 1 read as i, I, l, | or !: "Down i Beginning", "ACROSS 1 Fish".
#: Group 1 is the word; the clue's own text follows the match.
HEADING_BEFORE_ONE = re.compile(r"^\W*((?i:across|d[o0]wn))\W*\s+(?:\d{1,2}|[iIl|!])\W?\s+(?=[A-Z\"'])")

#: A heading in capitals closing a line after a clue's count: "(5) DOWN".
HEADING_AFTER_COUNT = re.compile(r"(?<=\))\W{0,2}\s+(ACROSS|D[O0]WN)\W*$")


def heading_of(line):
    """"ACROSS" or "DOWN" for a line that is the list's heading alone, read
    however badly ("DOW'N", "DOIN", "AROSS"); else None."""
    if exact := exact_heading(line):
        return exact  # spelled whole in any case ("AcRoss", "d0wn")
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




#: What a clue's count may hold, OCR'd: digits, S for 5, I or l for 1.
COUNT_BODY = r"[\dSIl,.\- ]"
#: A closed count ending a line ("(8)", "(3,7)."), the bracket's body read badly.
_COUNT_CLOSED_END = re.compile(rf"\(\s*{COUNT_BODY}{{1,9}}\)\W{{0,2}}$")
#: A count closing a line, its bracket maybe torn: "(8)", "(8", "(3,7)".
COUNT_END = re.compile(rf"\(\s*{COUNT_BODY}{{1,9}}\)?\W{{0,2}}$")
#: A closed count with text after it: the next clue ran on.
COUNT_INSIDE = re.compile(rf"\(\s*{COUNT_BODY}*\)\s*\S")


def is_count_end(line):
    """True when `line` ends on a whole count ("(7)", "(S)", "(3,7)." )."""
    return bool(_COUNT_CLOSED_END.search(line))


#: A count torn at a clue's end: "(" read as 1, I or l ("17).", "IS).") or
#: lost, ")" read as a letter or lost ("(5X", "(8k", "(8"); both torn: "("
#: read as T, t, f or j and ")" lost ("T10"), or a lone digit between
#: "(" read as 1, I or l and ")" as j, J, l or I ("16j", "I6l").
TORN_COUNT = re.compile(r"(?<=\S)\s*(?:\(([\dS]{1,2})[A-Za-z]?|(?<=\s)[1Il]([\dS]{1,2})\)"
                        r"|(?<=\s)[Ttfj]([\dS]{1,2})\)?|(?<=\s)([1Il][\dS])[jJlI])\W{0,2}$")


def mend_count(line):
    """`line` with a count torn at its end read whole: "writer 17)." is
    "writer (7)" (a count of 17 could not go in a 15-square grid), "hair (8"
    is "hair (8)". The line is returned as it was when its count is whole,
    absent, or too doubtful ("12)" may be 12 or 2): the caller decides whether
    this line ends a clue. S in a count is 5 only where the caller reads digits."""
    if is_count_end(line):
        return line
    m = TORN_COUNT.search(line)
    if not m:
        return line
    if m[2] and m[2].isdigit() and int("1" + m[2]) <= 15:
        return line  # "12)": a count of 12 lost its bracket, or of 2 its "(": unsure
    if m[4] and m[4].isdigit() and int(m[4]) <= 15:
        return line  # "12l": a count of 12 or of 2: unsure
    return line[:m.start()] + f" ({m[1] or m[2] or m[3] or m[4][1:]})"


#: A cross-reference's number whose 1 was read as I or l and run on to "see":
#: "SeeI3", "(seel3", "see l3", or the space lost ("(see13").
_SEE_NUMERAL = re.compile(r"\b(see)\s*([Il])?(?=\d)", re.IGNORECASE)


def see_numeral(text):
    """`text` with a cross-reference's number put back: "SeeI3." is "See 13.",
    "(seel3ac)" is "(see 13ac)", "(see13)" is "(see 13)"."""
    return _SEE_NUMERAL.sub(lambda m: m[1] + (" 1" if m[2] else " "), text)


def as_digits(text, s="5"):
    """`text` with the letters OCR reads for numerals put back: I and l are 1,
    O and o are 0, S is `s` (5 in a count; 8 in a 1930s old-style clue number,
    "4S." for 48)."""
    return text.translate(str.maketrans("IlOoS", "1100" + s))


def ones_read(text):
    """`text` with a 1 read as l or I before another digit put back
    ("l9th-century" is "19th-century")."""
    return re.sub(r"\b[lI](?=\d)", "1", text)


def strip_count(text):
    """`text` without the count that ends it, whole or torn ("hair (8)",
    "hair (8", "writer 17)." all lose theirs); else `text` as it was."""
    return re.sub(r"\s*\(\s*[\dSIl,.\- ]{1,9}\)\W{0,2}$", "", mend_count(text))


#: A line holding nothing but a bracket and a digit or so, a count's tail.
_STRAY_COUNT = re.compile(r"\W{0,2}(?:[A-Za-z]?\d{1,2}|\d[A-Za-z])\)\W{0,2}")


def is_stray_count(line):
    """True when `line` is only the tail of a count whose "(" and digits were
    unread ("U0).", "5)."); the caller knows the count from elsewhere."""
    return bool(_STRAY_COUNT.fullmatch(line))
