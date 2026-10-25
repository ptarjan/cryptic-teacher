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
#: A line that is only the tail of a count the line before opened ("3, 5)." under
#: "took second innings (5, 2,": Gale 1952-10-03's 5 down): the clue ends there, so
#: the next line with no number is a clue whose number was lost, as after "(7).".
COUNT_TAIL_LINE = re.compile(r"^\d[\d,.\- ]{0,8}\)\W{0,2}$")
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


#: A cross-reference's number 1 read as a letter or bar: "(see lac)", "10 See I
#: across", "See | Down"; at a text's end or before the way it runs.
_SEE_LETTER_ONE = re.compile(r"(\bsee\s+)[lI|](?=\s*(?:ac|dn|across|down)\b|\W*$)", re.IGNORECASE)


def see_one(text):
    """`text` with a cross-reference to 1 read as a lookalike put back:
    "(see lac)" is "(see 1ac)", "See I across" is "See 1 across"."""
    return _SEE_LETTER_ONE.sub(r"\g<1>1", text)


#: A linked head's number list as a list prints it: "11, 14 Clue words".
_LINK_HEAD = re.compile(r"^(\W{0,2})(\d{1,2}(?:\s*[,/+]\s*\d{1,2})+)(?=\s)")


def mend_link_tails(lines):
    """`lines`, one list's printed clue lines, with a linked head's tail that is
    one digit too many put right: "11/14" for "11/4" when 14 also opens a
    clue of its own in this list (a tail is the head's, it prints no clue of
    its own but a "See" row) and 4 opens none; the digit is dropped only when
    that leaves a number the list lacks. Lines not so linked are returned
    as they were."""
    leads = {}
    for ln in lines:
        m = re.match(r"^\W{0,2}(\d{1,2})\W{0,2}\s+(?!\(?\s*see\b)\S", ln, re.IGNORECASE)
        if m:
            leads[int(m[1])] = leads.get(int(m[1]), 0) + 1
    out = []
    for ln in lines:
        m = _LINK_HEAD.match(ln)
        if m:
            nums = re.split(r"\s*[,/+]\s*", m[2])
            sep = re.findall(r"\s*[,/+]\s*", m[2])
            for i, n in enumerate(nums[1:], 1):
                if len(n) == 2 and leads.get(int(n)) and not any(
                        int(c) in leads for c in (n[1:],)) and n[1] != "0" and int(n) != int(nums[0]):
                    nums[i] = n[1:]
            joined = nums[0] + "".join(sp + n for sp, n in zip(sep, nums[1:]))
            ln = m[1] + joined + ln[m.end():]
        out.append(ln)
    return out


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


# ---------------------------------------------------------------- numerals

#: A "See N" clue, which carries no words of its own.
SEE_WORD = r"s[ec]e"
#: A cross-reference's number, OCR'd: l or I read for a 1 only touching a
#: digit ("l5", "1l"), never a lone letter (a real "see I"). Compile with IGNORECASE.
SEE_NUMBER = r"(?:[lI]\d|\d[lI](?![a-z])|\d{1,2})"
SEE_RE = re.compile(rf"^{SEE_WORD}\s+({SEE_NUMBER})", re.IGNORECASE)


def see_number(text):
    """The int a SEE_NUMBER capture names ("l5" is 15; a lone l or I is 1)."""
    return int(text.translate(str.maketrans("lI", "11")))

#: The letters a digit standing alone may be a reader's misread of.
DIGIT_LETTERS = {"0": "o", "1": "ilt", "3": "a", "5": "s"}

#: The letters a printed digit is misread as in a clue's number or count
#: ("I I" for 11, "is" for 18, "ig" for 4), and the brackets about a count.
NUMBER_LETTERS = {"0": "oqd", "1": "ilj", "2": "z", "3": "a", "4": "ag", "5": "s", "6": "bh",
                  "7": "t", "8": "sb", "9": "gq"}
COUNT_OPENS, COUNT_CLOSES = "ijlft", "ijl"

#: Every letter a printed figure or a count's bracket is misread as.
FIGURE_LETTERS = set("".join(NUMBER_LETTERS.values()) + COUNT_OPENS + COUNT_CLOSES)


def number_digits(text):
    """A clue-list number as OCR reads it, as an int, its leading 1 read as T,
    I, i or l mended ("T8,339" is 18339)."""
    return int(re.sub(r"\D", "", re.sub(r"^[TIil]", "1", text.strip())))


# ------------------------------------------------------------------ counts

#: A count: "(15)", "(5,4)", "(3-2)".
COUNT_IN = r"\(\d{1,2}(?:\s*[,;\-.]\s*\d{1,2})*\)"
#: What follows a clue number standing for a light, not a word.
LIGHT_WORD = re.compile(r"(?:across|down|ac|dn|ack|dwn)\b", re.IGNORECASE)
#: A clue number opening a capitalised clue, not a cross-reference ("1
#: Down", "No. 1 Court", "e.g. 10 Downing Street").
NEXT_CLUE = r"\s+\d{1,2}\.?\s+(?!(?:Down|Across|Ac|Dn)\b)[A-Z\"'][a-z]"

#: A clue number opening a capitalised clue anywhere in a filed clue's
#: text: another clue, or the page's text, read into this one ("Poles 22
#: Affected by", "Saturday 26 The point is"). A cross-reference names its
#: list ("9 Across", "17 Down") and a date its month ("5 November").
NUMBERED_IN = re.compile(
    r"(?:^|\s)\d{1,2}\.?\s+(?!(?:Down|Across|Ac|Dn|Up|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]*\b)(?:[A-Z][a-z]|[\"'\u201c\u2018][A-Z])")

#: The page's own words read into a clue: a pointer to another page's
#: puzzle ("Concise crossword, page 22"), a notice of a solution ("The
#: solution to the Collins Competition", "Prize Puzzle No 18,178"), or a
#: count with text after it ("(41. Times Two", "(5 _ Concise", the
#: previous clue's "(6;3). Covered" run in ahead), not an aside the clue
#: closes ("(2 Hen. IV)").
PAGE_TEXT = re.compile(r"\bcr\w{4,8}d\W{1,3}(?:page|p)\W{0,2}\d"
                       r"|\bpuzzle\s+no\W{0,2}\s*\d"
                       r"|\bsolution\s+(?:to|of)\s+(?:\S+\s+){0,4}(?:puzzle|competition)\b"
                       r"|(?-i:\(\s*\d{1,2}(?:\s?[,.;:\-]\s?\d{1,2})*(?:\)[.,;:]?|\.)?\s+(?:_|[A-Z])(?![^()]*\)))",
                       re.IGNORECASE)


def cut_at_count(text, enum):
    """A clue's text cut at its own count (`enum`) inside it: what follows
    is the next clue's specks or start, or the page's text, run on. The
    count's bracket may read as a full stop or be lost ("spotty (6. The
    solution", "outs (5 _ Concise")."""
    for m in re.finditer(r"\s*\((\d{1,2}(?:\s*[,;\-.]\s*\d{1,2})*)(?:\)|\.|(?=\s))\W*\S", text or ""):
        if enum and re.sub(r"\D+", ",", m.group(1)) == re.sub(r"\D+", ",", enum):
            return text[:m.start()].rstrip()
    return text


#: A cross-reference or a count with its unit, which may run digits into letters.
COUNTED = re.compile(r"\d+(?:st|nd|rd|th|s|d|p|cc|pm|am|k|m|ac|dn|a|d|x\d+)", re.IGNORECASE)

#: Figures standing after a clue's last word: its count with the brackets
#: read as ones or lost, or any numbers, from a bracket at most on either
#: side ("7", "151.", "i7j", "1 7V 3").
#: Each figure token parses one way only (its first digit, then at most one
#: letter), so a long run of digits and specks cannot backtrack.
STANDING_FIGURES = re.compile(r"(?<=[A-Za-z?!.'\u2019])"
                              r"(?:\s+[A-Za-z]?[^\sA-Za-z?!\d]*\d[^\sA-Za-z]*(?:[A-Za-z][^\sA-Za-z]*)?)+\s*$")


def count_read(figures, count):
    """Whether `figures` read as the clue's count (digits, groups joined),
    its brackets read as ones or lost ("151" for "(5)", "15" for "(5")."""
    digits, want = re.sub(r"\D", "", figures), re.sub(r"\D", "", count or "")
    return bool(want) and re.fullmatch(rf"1?{want}1?", digits) is not None


#: Words a clue does not end on, so a number after one is a reference the
#: clue makes ("See 15", "No 10", "Channel 5", "company in 18", "being 8").
REFERENCE_WORDS = frozenset("""see no nos number channel in of by for from to with at on about under
    before after around into over than as and or nor the a an is are was were be being been""".split())


def count_left(text, cells, lights):
    """`text` without the figures standing after its last word when they are
    its count misread, filling its `cells` ("Song of joy 141" for "(4)",
    "restaurant? 15-41" for "(5-4)": brackets read as ones); else None. A
    figure with a unit ("8s", "100p") is the clue's, and so is a reference:
    numbers that are all `lights` (the puzzle's clue numbers) after a word
    of REFERENCE_WORDS ("See 15")."""
    m = STANDING_FIGURES.search(text or "")
    if not m or not cells or any(COUNTED.fullmatch(t) for t in m.group().split()):
        return None
    word = re.search(r"([A-Za-z]+)\.?$", text[:m.start()])
    if (word and word.group(1).lower() in REFERENCE_WORDS
            and all(int(n) in lights for n in re.findall(r"\d+", m.group()))):
        return None
    groups = re.findall(r"\d+", re.sub(r"^\D*1(?=\d)|1(?=\D*$)", "", m.group().strip()))
    if not (count_read(m.group(), str(cells)) or len(groups) > 1 and sum(map(int, groups)) == cells):
        return None
    return text[:m.start()].rstrip(" ,;:")


#: A closed count of four or more parts, digits and separators only: "(6, 5, 2, 3, 5)".
_COUNT_LONG = re.compile(r"\((\s*\d{1,2}(?:\s*[,.]\s*\d{1,2}){3,}\s*)\)")
#: A closed count with specks after it ("(8)'", "(5).·", "(5). _").
_COUNT_SPECKS = re.compile(r"(\(\s*[\dSIl,.\- ]{1,9}\))(?:[^\w(]|_){1,3}$")
#: A count whose ")" was read as j or J, or whose "(" was lost, after a word
#: (not "see": "(See 4)" is a reference, not a count).
_COUNT_CLOSE_MISREAD = re.compile(r"(?<=[a-z])(?<![Ss]ee)\s?\(?(\d{1,2}(?:[,.\-]\d{1,2})*)[)jJ]$")
#: A count left open at its end, a speck where the bracket was: "(5r", "(5".
_COUNT_OPEN_END = re.compile(r"\((\d{1,2})[^\d)\s]?$")


def count_closed(line):
    """`line` with a count ending it mended: its ")" read as j or J, or its "("
    lost ("hair 8j" is "hair (8)"), and the specks after a whole count dropped
    ("(8)'" is "(8)")."""
    line = _COUNT_CLOSE_MISREAD.sub(r" (\1)", line)
    # A linked clue's long count, its spaces closed ("(6, 5, 2, 3, 5)" is 13 characters, past the
    # 12 file_trove_puzzles.BRACKET takes as a count, so the clue ran on into the next: Gale 1952-10-15's 1, 9).
    line = _COUNT_LONG.sub(lambda m: "(" + re.sub(r"\s+", "", m.group(1)) + ")", line)
    return _COUNT_SPECKS.sub(r"\1", line)


def count_closed_open(line):
    """`line` whose count is left open at its very end ("(5r") with it closed
    ("(5)"): for a list's last clue, where nothing follows to carry it on."""
    return _COUNT_OPEN_END.sub(r"(\1)", line)


# ------------------------------------------------------- clue-number reads

#: The number opening a clue's line, maybe run into its first word:
#: "25Recipient", "21.Measures"; group 1 holds the digits, read with I, l, |.
OPENING_NUMBER = re.compile(r"^\W{0,2}([\dIl|]{1,2}?)(?:[.,:;\-]\s*|\s+|(?=[A-Z\"'\u2018\u201c]))(?=\S)")
#: A number read with a speck ("151", "128") holding the next light's.
OPENING_SPECK = re.compile(r"^\W{0,2}(\d{3})\W{0,2}\s*(?=[A-Z\"'\u2018\u201c])")
#: ACROSS or DOWN set alone on its line, however set: a clue column's heading.
HEADING_ALONE = re.compile(r"\W*(?:across|down)\W*$", re.IGNORECASE)


#: A line that is a list heading in plain words, "Across" or "Down:" with a colon
#: or stop after it, "Across clues" too: group 1 is the word.
PLAIN_HEADING = re.compile(r"^\s*(across|down)(?:\s+clues)?\b[\s:.]*$", re.I)


#: A clue number run into its first word, as a reader drops the space: "1.An
#: African bird", or its stop and a dagger lost too: "29A town".
GLUED = re.compile(r"^(\W{0,2}\d{1,2}[.,:])(?=[A-Za-z*\u2020\u2021'\"\u2018\u201c])"
                   r"|^(\W{0,2}\d{1,2})(?=[A-Z][a-z]|[AI]\s)")
#: A footnote's dagger opening a clue ("28.\u2020Not far from 13"), read as
#: a small t or f run into the clue's capital ("tNot", "fA famous"), or
#: run into its number ("29tA town").
DAGGER = re.compile(r"^(\W{0,2}\d{1,2}[.,:]? ?)?[tf\u2020](?=[A-Z](?:[a-z]|\s|$))")
#: A clue number glued to "rev." (and to a linked light's number).
REV_GLUED = re.compile(r"^(\W{0,2}\d{1,2})\s*rev\.\s*(?:,\s*(\d{1,2})\.)?\s*")


#: A clue number (up to three digits or their lookalikes) opening a line.
HEAD_NUMBER = re.compile(r"^[\dIlJ!|oO]{1,3}[.,:]?\s+")


def head_off(text):
    """A line's text without the clue number its first line opens on (HEAD_NUMBER)."""
    return HEAD_NUMBER.sub("", (text or "").strip())


def mend_opening(text):
    """`text`, a clue's opening, with a number run into "rev." ("20rev.,24.Charade:"
    is "20 rev., 24. Charade:"), a number run into its first word parted, and
    a footnote's dagger read as a letter put back (GLUED, DAGGER, REV_GLUED)."""
    text = REV_GLUED.sub(lambda m: f"{m.group(1)} rev." + (f", {m.group(2)}." if m.group(2) else "") + " ",
                         text).rstrip()
    text = GLUED.sub(lambda m: (m.group(1) or m.group(2)) + " ", text)
    return DAGGER.sub(lambda m: (m.group(1) or "").rstrip() + (" " if m.group(1) else "") + "\u2020", text)


def clue_number_opening(line):
    """`line`, a clue's line after a count or a heading, with its clue number
    put right: a speck before the number dropped, its 1 read as I, l, J, ! or
    | back, a speck run into its first word taken out ("1'In the" is "1 In
    the"), and a number read as specks alone dropped (the grid places that
    clue)."""
    line = mend_opening(line)
    # A speck or star before a clue's number: ". 1 Miss", ":1 An", "*1 Land".
    line = re.sub(r"^[.,:;*'_\u2022\u00b7]{1,2}\s?(?=[\dIl]\d?\s)", "", line)
    # A clue's number 1 read as I or l: "I7 More", "IA fruitful".
    line = re.sub(r"^[Il](?=\d\b|\d\s|[A-Z]\s)", "1", line)
    # A clue's number 11 read as two or three ones-shaped letters before a
    # capitalised word: "ll1 Red", "ll At", "1l After", "IIl Flier", "II Flier",
    # "!! Examine" (RapidOCR's both readers on the 2000-14 Gale Times, whose
    # 11 across then opened in no reading and its page went unfiled). The
    # word "Ill" is left.
    line = re.sub(r"^(?!Ill\s)(?:[Il|!]{2}[1Il|!]?|1[Il|!]|[Il|!]1[Il|!1]?)(?=\s+[A-Z\"'‘“])", "11", line)
    # A clue's number with a speck run into its first word: "1'In the",
    # "1.Associate's", "l^Finished", ". 1. Maltreat", "-1--He said".
    line = re.sub(r"^(?:[^\w\s(]|_){1,3}\s?(?=[Il]?\d{1,2}(?:[^\w\s(]|_){0,3}\s?[A-Z\"'])", "", line)
    line = re.sub(r"^[Il]?(\d{1,2})(?:[^\w\s(]|_){1,3}\s?(?=[A-Z\"'])", r"\1 ", line)
    line = re.sub(r"^[Il](\d)?(?:[^\w\s(]|_){1,3}\s?(?=[A-Z][a-z])", lambda m: f"1{m[1] or ''} ", line)
    # A 1 read as I, J, ! or | run into a capitalised word: "IPheasant",
    # "JTool", "!What makes".
    line = re.sub(r"^[IlJ!|](?=[A-Z][a-z])", "1 ", line)
    # A number read as specks alone: ") With", "\u2022 \u00a3\u25a0 So"; the grid
    # places the clue.
    return re.sub(r"^(?:[^\w\s(\"'][^\w\s(]{0,2}\s?){1,3}(?=[A-Z][a-z])", "", line)


# ----------------------------------------------------------- torn brackets

#: The brackets a clue pairs.
PAIRS = {")": "(", "]": "["}


def unpaired(text):
    """The index of the first bracket `text` never closes or never opened
    ("is (this", "for ) record", "[9)"), or None."""
    stack = []
    for i, c in enumerate(text or ""):
        if c in "([":
            stack.append((c, i))
        elif c in PAIRS:
            if not stack or stack[-1][0] != PAIRS[c]:
                return i
            stack.pop()
    return stack[0][1] if stack else None


def trim_torn_count(text):
    """A clue's text without the torn count and specks round its brackets:
      - a last token with no word in it and a bracket the clue never opened
        ("0,6)", "S).", "writer 1 7).") or a digit among symbols ("&%S4),");
      - a square-bracketed count ending it ("[5]", "[3,4)");
      - a count torn open at its end ("hair-dresser (6", "(5.41.", "( 8 .")
        and a speck read as a bracket before its first word (") The man")."""
    while "(" not in text or ((k := unpaired(text)) is not None and text[k] in ")]"):
        head, _, last = text.rpartition(" ")
        if not head or re.search(r"[A-Za-z]{2}", last) or not (
                ")" in last or (re.search(r"\d", last) and re.search(r"[&#@]", last))):
            break
        text = head.rstrip()
        if re.fullmatch(r"[1l]", text.rpartition(" ")[2]) and re.search(r"\d", last):
            text = text.rpartition(" ")[0].rstrip()  # "currency 1 7).": the count's "(" read as 1
    text = re.sub(r"\s*\[\s*\d{1,2}(?:\s*[,\-]\s*\d{1,2})*\s*[\])][^\w(\[]*$", "", text)
    k = unpaired(text)
    if k is not None and text[k] in "([" and re.fullmatch(r"[(\[]\s*[\dSIl$]{0,2}(?:\s*[,.\-]\s*[\dSIl]{0,2})*[^\w(\[]*",
                                                         text[k:]):
        text = text[:k].rstrip()
    k = unpaired(text)
    if k is not None and not text[:k].strip():
        text = text[k + 1:].lstrip()
    return text


# ---------------------------------------------------------------- counts

def count_total(enum):
    """The squares a printed count spans: "3,7" and "3-7" are 10, "(5)" is 5;
    0 for text with no figures."""
    return sum(int(n) for n in re.findall(r"\d+", enum or ""))


#: A clean printed count ending a line, however its digits are spaced and
#: joined: "(8)", "(3,7).", "(4-4)", "(2 , 3)". Strict (no OCR letters, a
#: closed bracket); COUNT_END is the loose reading of a scan.
PRINTED_COUNT = re.compile(r"\(\s*\d{1,2}(?:\s*[,\-–]\s*\d{1,2})*\s*\)\W{0,2}$")


#: A printed count anywhere in a clue, as a source's text spells it: digits
#: split by a comma, hyphen, stop, colon, slash, apostrophe, "and" or a
#: space, a separator left dangling before the bracket ("(4-4 )", "(5.)").
ENUM_COUNT = r"\(\s*\d(?:[\d,\-.;:/'\s]|and(?=\s*\d))*\)"

#: That, or the "(see 14 across)" a linked light prints in its place. Source
#: of a pattern.
ENUM_OR_SEE = (r"\((?:\d(?:[\d,\-.;:/'\s]|and(?=\s*\d))*"
               r"|see \d{1,2}[^)]{0,12})\)")

#: "(6, two words)": the count of words is the print's, not an enumeration.
WORDS_COUNT = re.compile(r"\(\s*(\d{1,2}(?:\s*[,\-]\s*\d{1,2})*)\s*[,.]\s*\(?\s*[a-z]{2,5}\s+w[a-z]{3,4}\s*\)",
                         re.IGNORECASE)

#: The shared core of a clue number opening a clue inside another clue's text:
#: the number (a 11 read "1l]"), then a stop, then a capital or quote, and not
#: a direction word. RUN_ON_NUMBER and NEXT_NUMBER are both built from it.
#: Nor a direction's letter that ends the clue or stands before its count:
#: No 601 2D's "Playful division of the second of 1 A" names 1 across.
RUN_ON_NUM = r"\d{1,2}|[1l]\]"
RUN_ON_AFTER = (r"[.:]?\s+(?!(?i:across|down|ac|dn)\b)(?![AD]\.?\s*(?:$|\(\d))"
                r"(?=[A-Z\u2018\u201c'\"])")

#: The next clue's number (">0" for a misread 10) and first word inside a
#: clue's text.
NEXT_NUMBER = re.compile(rf"\s\S?(?:{RUN_ON_NUM}){RUN_ON_AFTER}")

#: A clue number and the ellipsis its clue opens on: glued to the number
#: ("5... the"), a speck between ("5_ ... the"), dots lost ("6 . stabbed"),
#: no space after ("6 ...stabbed"). Line-anchored; apply per line of text.
ELLIPSIS_HEAD = re.compile(r"^(\d{1,2})(?:[ _~]*(?:\.\s?\.(?:\s?\.)?|…)[ ]*(?=[A-Za-z\"'‘])| +\. *(?=[a-z]))",
                           re.MULTILINE)


# ------------------------------------------------------- list headings read in

#: The next puzzle's heading read onto a clue, with that puzzle's preamble
#: and clues after it: a book prints "Alphabetical Jigsaw" (Araucaria book
#: 2, read onto the last Down light of No 15, 20, 34, 50 and 66). Only as
#: a heading sets it, in capitals: a clue may say "alphabetical jigsaw"
#: (cryptic-28672).
PUZZLE_HEADING = re.compile(r"(?<![\w'])(?:Alphabetical|ALPHABETICAL)\W{1,3}(?:Jigsaw|JIGSAW)(?![\w'])")

#: A list's heading read into a clue: "ACROSS" or "DOWN" in capitals,
#: which no clue prints, or either opening the text before the first
#: clue's number ("Down i Beginning", "ACROSS 1 Fish").
HEADING_IN = re.compile(CAPS_HEADING.pattern + "|" + HEADING_BEFORE_ONE.pattern)

#: A heading with a stray glyph or a lone letter beside it ("| ACROSS",
#: "DOwNn", "DOWN i"): a book's grid shares the leaf, the scans double a
#: letter. A clue cannot match: it has words and a count.
_STRAY = r"[^A-Za-z0-9]{0,3}(?:\s+[A-Za-z][^A-Za-z0-9]{0,2})?"
_STRAY_HEADING = re.compile(r"^[^A-Za-z0-9]{0,3}" + DIRECTION + _STRAY + "$", re.IGNORECASE)
#: A heading led by the book's running head ("Cryptic Across", "CryBHE
#: Across"): one or two alphabetic words, no digits, so "13. See 14 Across"
#: (a real clue) is no heading; a head that is itself "See" is refused too,
#: for OCR loses the leading number.
_RUNNING_HEADING = re.compile(r"^(?P<head>(?:[A-Za-z]{2,12}[^A-Za-z0-9\s]{0,2}\s+){1,2})"
                              + DIRECTION + r"[^A-Za-z0-9]{0,3}$", re.IGNORECASE)


def tolerant_heading(line):
    """"ACROSS" or "DOWN" for a line that is a heading with specks or a
    running head round it (see _STRAY_HEADING, _RUNNING_HEADING); else None."""
    line = line.strip()
    m = _STRAY_HEADING.match(line)
    word = m.group(1) if m else None
    m = None if m else _RUNNING_HEADING.match(line)
    if m and "see" not in m.group("head").lower():
        word = m.group(2)
    if word is None:
        return None
    return "ACROSS" if word[0] in "Aa" else "DOWN"


# ------------------------------------------------------------ cross-references

#: "see 14", "See 14 Across", "see 3 dn": the number and, if printed, the
#: way it runs. Source of a pattern; compile it with IGNORECASE.
SEE_DIRECTED = rf"{SEE_WORD}\s+({SEE_NUMBER})\s*(across|down|ac|dn)?\b"


# ------------------------------------------------------ clue numbers read badly

#: A clue number in the 1930s' old-style figures, read as letters: "I."
#: for 1, "II." for 11, "Io." for 10, "I3." for 13, "4S." for 48; a lone
#: "S." is a word.
OLD_FIGURES = re.compile(r"^(\W{0,2})([IlO\d]?[IloO\d]|\dS)([.,:])(?=\s|[A-Z]|$)")


def old_figures(word):
    """`word` with its opening clue number read as letters put back in
    digits ("II." is "11."; "4S." is "48."); a number cannot open on 0, so
    "O." and "Oo." stay words. Returns `word` unchanged when it holds none."""
    m = OLD_FIGURES.match(word)
    n = m and as_digits(m.group(2), "8")
    if m and n.isdigit() and n[0] != "0" and not m.group(2).isdigit():
        return m.group(1) + n + m.group(3) + word[m.end():]
    return word


def mend_scan_text(part):
    """A scan's run-together clue text with its common OCR slips mended: a
    stray rule ("|"), "S" and "A" read for 5 and 4 in a clue number ("4S",
    "2A", "1/Sac", "See Sdn"), a clue number run into its first word ("12T he",
    "20ac.They"), specks and junk between a count and the next clue, and "|",
    "l" or "I" read for the 1 that opens a list ("DOWN | Picture of crack
    plugged (8)", Private Eye No 328)."""
    part = re.sub(r"^\s*[|lI](?=\s+[A-Z‘“'\"])", " 1", part)
    part = re.sub(r"\s[|]+(?=\s|$)", " ", part)
    part = re.sub(r"(?<=[\s/])S(?=\s*(?:ac|dn)\b)", "5", part)
    # A speck of punctuation after a closing bracket, before the next clue's number
    # ("13 (see 1dn) : 15 Monument"): it hid the see-row and merged 13 into 15 (No 123).
    part = re.sub(r"(\))\s+[:;.,]+(?=\s+\d{1,2}\s)", r"\1", part)
    # OCR junk after an enumeration, before the next clue ("(7) ins eee 29 2 Leader"):
    # it hid the count and merged clue 2 into 1 (No 262).
    part = re.sub(r"(\))(?:\s+[a-z]{1,5}){1,4}(?:\s+\d{1,2})?(?=\s+\d{1,2}\s+[A-Z‘“'\"])", r"\1", part)
    # "(seel3ac)" for "(see 13 ac)": no space, the 1 read as l.
    part = see_numeral(part)
    part = re.sub(r"(?<=\s)(\d)S(?=\s)", r"\g<1>5", part)
    part = re.sub(r"(?<=\s)(\d)A(?=\s+[A-Z‘“'\"])", r"\g<1>4", part)
    part = re.sub(r"(?<=\s)(\d{1,2})([A-Z]) ([a-z]{1,3})\b", r"\1 \2\3", part)
    part = re.sub(r"(?<=\d)(ac|dn)\.(?=[A-Z‘“'\"])", r"\1. ", part)
    part = mend_between_clues(part)
    return WORDS_COUNT.sub(r"(\1)", part)


# ======================================================================
# The one pipeline every OCR reader sends its clue text through.
# ======================================================================

#: A brace, square, angle or full-width bracket (RapidOCR's ch recogniser)
#: read for a round one.
BRACKETS = str.maketrans({"{": "(", "[": "(", "<": "(", "}": ")", "]": ")", "（": "(", "）": ")"})
_LIKE_FIGURES = str.maketrans("IlioOzZsSg", "1110022559")
_WIDE_BRACKETS = str.maketrans("（）", "()")


def figures_like(text):
    """`text` with each letter an OCR reads for a figure ("Is", "4o", "z1")
    put back as that figure; its length is kept."""
    return text.translate(_LIKE_FIGURES)


def wide_brackets_narrowed(text):
    """`text` with a full-width bracket read as a round one; length kept."""
    return text.translate(_WIDE_BRACKETS)


def counts_mended(lines):
    """`lines` with the torn count that ends a clue (its next line a clue's
    number, a heading or the column's end) read as a count: "writer 17)."
    is "writer (7)", for a count of 17 could not go in a 15-square grid,
    and "(8" before "4 American city" is (8). A whole count is left alone."""
    out = list(lines)
    for k, line in enumerate(out):
        nxt = out[k + 1] if k + 1 < len(out) else None
        if nxt is not None and not (re.match(r"\d{1,2}\s+\S", nxt) or heading_of(nxt)):
            continue
        if is_count_end(line):
            continue
        mended = mend_count(line)
        if mended == line:
            if is_stray_count(line) and not (
                    k and out[k - 1].count("(") > out[k - 1].count(")")):
                # A line of nothing but a bracket and a digit or so ("U0).")
                # is the clue's count, unread: the grid gives it; after a
                # count left open ("(5-"), it is that count's end.
                out[k] = "(?)"
            continue
        out[k] = mended
    return out


#: A cross-reference clue on its own line: "See 19", "? See 4 down."; it has no count.
_SEE_ONLY = re.compile(r"^(?:\?\s+)?see\s+\d{1,2}\s*(?:across|down|ac|dn)?\.?\s*$", re.IGNORECASE)


def _closes(line):
    """True when `line` ends a clue: on its count, or as a cross-reference alone."""
    return bool(COUNT_END.search(line) or _SEE_ONLY.match(line))


def uncounted_dropped(lines):
    """`lines` (a column's) without text that is no clue: after a "? " line (a
    clue whose number was lost), lines with no count of their own that run
    into the next clue's number, a heading or the column's end ("Prize
    Crossword in The Times tomorrow", a notice printed across the columns). A
    clue whose number was lost ("? Holds fast (5)") still ends on its count."""
    out, k = [], 0
    while k < len(lines):
        if not lines[k].startswith("? "):
            out.append(lines[k])
            k += 1
            continue
        end = k
        while end < len(lines) and not _closes(lines[end]) and (
                end == k or not (re.match(r"\d{1,2}\b", lines[end]) or heading_of(lines[end])
                                 or lines[end].startswith("? "))):
            end += 1
        if end < len(lines) and _closes(lines[end]) and not (
                end > k and (re.match(r"\d{1,2}\b", lines[end]) or heading_of(lines[end]))):
            out.extend(lines[k:end + 1])
            k = end + 1
        else:
            k = end
    return out


def _split_headings(text):
    """The lines of a column `text` with each list heading read onto another
    line made a line of its own: a heading opening the line of its first clue
    ("Down i Beginning", "ACROSS 1 Fish"), or closing the last clue of the
    list before ("chance (5) DOWN"). One inside a line, another column's read
    across ("on the DOWN board"), is no word, and goes."""
    lines = []
    for line in text.splitlines():
        m = HEADING_BEFORE_ONE.match(line)
        if m:
            lines += [direction(m[1]).upper(),
                      (re.search(r"\d+", line[m.end(1):m.end()]) or ["1"])[0] + " " + line[m.end():]]
            continue
        m = HEADING_AFTER_COUNT.search(line)
        tail = [m[1]] if m else []
        line = line[:m.start()] if m else line
        lines += [re.sub(rf"(?<=\S)\s+{CAPS_HEADING.pattern}(?=\s+\S)", "", line)] + tail
    return lines


def _heading_in(line, running_head, extra_headings):
    """"ACROSS" / "DOWN" for a line that is a list heading by any of the
    readings: the plain fuzzy one, the puzzle-numbered ("No. 18,340 ACROSS"),
    the publisher's own words (`extra_headings`, {"HORIZONTAL": "ACROSS"}), and,
    when `running_head`, a book's running head or specks round it."""
    if heading := heading_of(line) or numbered_heading(line):
        return heading
    if extra_headings and (heading := extra_headings.get(re.sub(r"[^A-Za-z]", "", line).upper())):
        return heading
    return tolerant_heading(line) if running_head else None


def heading_in(line, running_head=False, extra_headings=None):
    """"ACROSS" / "DOWN" for a line that is a list heading by any of the
    pipeline's readings (see tidy_ocr_clues), else None."""
    return _heading_in(line, running_head, extra_headings)


def _inline_slips(line):
    """Slips that hold anywhere in a clue's text, whichever its line: a count
    set wide, a speck read as a middle dot, a backtick, a
    cross-reference's number read as letters."""
    line = re.sub(r"\((\d) (\d)\)", r"(\1\2)", line)  # a two-digit count set wide, "(1 1)"
    if "\u00b7" in line:  # a speck read as a middle dot ("study·money", "in· France")
        line = re.sub(r"\s*\u00b7\s*", " ", line).strip()
    line = re.sub(r"(?<=\w)`", " `", line).replace("`", "\u2018")  # a backtick is an opening quote read
    line = re.sub(r"(?<=[A-Za-z\"\u201d\u2019?!.])\((?=[\d\u2013\u2014-])", " (", line)  # space lost before a bracket
    # A cross-reference set after the count, "(3,4,3) (see also 12 ac.)"
    # (Cyclops 250): the count no longer ends the clue, so the next clue ran
    # on into it. The reference goes before the count, as every other does.
    line = re.sub(r"(\(\s*\d{1,2}(?:\s*[,\-\u2013]\s*\d{1,2})*\s*\))\s*(\(\s*see also[^()]*\))\W{0,2}$",
                  r"\2 \1", line, flags=re.I)
    line = see_one(line)  # a reference to 1 read as its lookalike ("10 See lac.")
    line = ones_read(see_numeral(line))  # "SeeI3." is "See 13."; "l9th" is "19th"
    return WORDS_COUNT.sub(r"(\1)", line)  # "(6, two words)" is "(6)"


def _line_slips(line):
    """One column line's slips that anchor on its start, where its clue number
    is: specks before the number, an ellipsis head, a number split or run into
    its word, a "rev." misread; then _inline_slips."""
    line = re.sub(r"^[.:;,'`\u2018\u2019 ]+(?=[\dIl])", "", line)  # specks left before a clue number
    # A clue opening on an ellipsis ("5... the", "5_ ... the", "6 . stabbed"). A
    # lone stop glued to the number ("5. the") is the number's own.
    line = ELLIPSIS_HEAD.sub(r"\1 ... ", line)
    line = re.sub(r"^(\d{1,2})(?=[\"\u201c\u2018'])", r"\1 ", line)  # space lost between number and opening quote
    # Not before a lowercase word: "6 3 put more negatively" is 6 down whose
    # clue opens on a reference to 3 (Cyclops No 19), not 63.
    line = re.sub(r"^(\d) (\d) (?=[^\sa-z])", r"\1\2 ", line)
    line = re.sub(r"^(\d{1,2})(?=[A-Z]{2})", r"\1 ", line)
    line = re.sub(r"^(\d{1,2})\s?re[vy][.,]?\s*(?=[A-Z\"'\u2018])", r"\1 rev. ", line)
    return _inline_slips(line)


def tidy_ocr_clues(text, *, scope="column", running_head=False, extra_headings=None, line_hook=None,
                   torn_counts="mend", cells=None, lights=()):
    """The one tidy-up every OCR reader sends its clue text through, so a fix
    found on one source reaches all of them. Stages run in this fixed order,
    each on what the one before left; every stage is safe on any source's
    text unless a comment says so.

    `scope` is how much of the page `text` is:
      "column": a whole column of lines with its ACROSS / DOWN headings.
          1 headings first: one read onto another line made its own line,
            then every line that is a heading made the canonical word
            (heading_of, numbered_heading, `extra_headings`, `running_head`);
          2 brackets (BRACKETS), then each line's number and opening (a
            lower-case "down" carries on the line before; clue_number_opening
            after a count or heading; GLUED; `line_hook`; _line_slips: see_one,
            see_numeral, ones_read, ELLIPSIS_HEAD, WORDS_COUNT);
          3 counts: count_closed per line, a "? " marking a number lost,
            counts_mended for a clue's torn count, count_closed_open at a
            list's end, uncounted_dropped for text that is no clue;
          4 joins: mend_link_tails on each list ("11/4" for "11/14").
          The four stages go round until the text stops changing (three
          times at most), so the result is idempotent.
      "clue": one clue's text (no heading, no number, no neighbours): stage
          2's slips that hold anywhere in a line (_inline_slips),
          then the count: `torn_counts` "mend" reads a torn count whole
          (mend_count), "trim" cuts it with the specks round it
          (trim_torn_count) for a reader that knows the count elsewhere.
      "line": one printed line of a column whose place in a list a reader
          keeps (it lays the line by its box): brackets, the opening, the
          line's slips, then the line's torn count (mend_count). Never
          drops, joins or adds a line.
      "lines": one list's printed lines, as a list: mend_link_tails only.
      "run": a scan's whole column run together on one line (no line
          breaks): mend_scan_text.
      "piece": one OCR word or fragment of unknown place on its line: only
          what holds for a word alone (old_figures, mend_opening,
          see_numeral, see_one, ones_read).

    `cells` (clue) is the length of the light the clue is for: figures
    standing after its last word that are its count misread, filling the
    cells, go (count_left; `lights` are the puzzle's clue numbers, so
    "See 15" keeps its figure), unless that would leave no words.

    `running_head` (column) reads "Cryptic Across" or "| ACROSS" as a heading
    (tolerant_heading). It is OFF by default: it also matches a clue's
    continuation line like "Come down", so only a source whose lines are known
    to hold running heads (a book's leaf) sets it. `extra_headings` maps a
    publisher's own heading word, upper-case letters only, to "ACROSS" or
    "DOWN". `line_hook(line)` is a source's own last say on a clue line (a
    lexicon check the pipeline cannot make)."""
    if scope == "run":
        return mend_scan_text(text)
    if scope == "lines":
        return mend_link_tails(text)
    if scope == "line":
        return mend_count(_line_slips(mend_opening(text.translate(BRACKETS))))
    if scope == "piece":
        text = old_figures(text)
        text = mend_opening(text)
        return ones_read(see_one(see_numeral(text)))
    if scope == "clue":
        bare = count_left(text, cells, set(lights)) if cells else None
        text = bare if bare and re.search(r"[A-Za-z]", bare) else text
        text = _inline_slips(text)
        if torn_counts == "trim":
            return trim_torn_count(text)
        return mend_count(text) if torn_counts == "mend" else text
    if scope != "column":
        raise ValueError(f"unknown scope {scope!r}")
    # One pass leaves work for the next (a number is opened only once the
    # count before it is mended; a count closed gains its space), so the
    # column goes round until it stops changing, three times at most.
    for _ in range(3):
        again = _column_pass(text, running_head, extra_headings, line_hook)
        if again == text:
            break
        text = again
    return text


def _column_pass(text, running_head, extra_headings, line_hook):
    """One pass of tidy_ocr_clues' column stages 1 to 4, in order."""
    out, prev = [], ""
    for line in _split_headings(text):
        line = line.translate(BRACKETS).strip()
        # A speck read as a bracket after a clue's closed count ("(6) <").
        line = re.sub(r"(?<=\))\s*[(\[]$", "", line)
        if not line:  # a blank line parts nothing: the clue after it is judged by the line before it
            out.append(line)
            continue
        heading = _heading_in(line, running_head, extra_headings)
        if heading:
            line = heading
        elif out and re.match(r"(?:across|down)\b", line):
            # A lower-case "down (8)." carries on the line before it: no heading.
            out[-1] += " " + line
            prev = out[-1]
            continue
        ended = is_count_end(prev) or bool(COUNT_TAIL_LINE.match(prev))
        if ended or heading_of(prev) or not out:
            line = clue_number_opening(line)
        line = re.sub(r"^(\d{1,2})(?=[A-Z][a-z]|[A-Z]\s)", r"\1 ", line)
        if line_hook:
            line = line_hook(line)
        line = _line_slips(line)
        line = count_closed(line)
        if (ended or heading_of(prev)) and re.match(r"[A-Z][a-z]", line):
            line = "? " + line
        out.append(line)
        prev = line
    # A count left open at a list's end ("(5r", "(5-" before DOWN): a speck
    # took its bracket, as nothing follows to carry it on.
    for k, line in enumerate(out):
        if k + 1 == len(out) or heading_of(out[k + 1]):
            out[k] = count_closed_open(line)
    out = uncounted_dropped(counts_mended(out))
    # Last, once the lines are whole: a linked head's tail ("11/4" for
    # "11/14") is judged against the clue numbers its own list opens.
    lists, cur = [], []
    for line in out:
        if heading_of(line):
            lists.append(cur)
            cur = []
        cur.append(line)
    lists.append(cur)
    return "\n".join(line for lst in lists for line in mend_link_tails(lst))


#: A bare enumeration (the text between a clue's words and the next
#: clue): digits split by comma, stop, hyphen or space, brackets optional.
ENUM_SEG = re.compile(r"[\s.?!;:'\"]*[(\[{]?\s*(\d{1,2}(?:(?:\s*[,.\-]\s*|\s+)\d{1,2})*)\s*[)\]}]?[\s.,;:]*")

#: A clue number opening a clue inside another clue's text, with the count of
#: the clue before it in front when that count stands inside the text.
RUN_ON_NUMBER = re.compile(rf"(?:\((\d[\d,\-\u2013]*)\)\s*)?(?<![\d(])({RUN_ON_NUM}){RUN_ON_AFTER}")
#: A clue number and, run on after it, the clue before's one-figure count
#: ("... the town 25 5 Bury fat (9)": the count (5) lost its brackets and
#: line, and sits between the next clue's number and its words).
RUN_ON_STRAY = re.compile(r"(?<![\d(])(\d{1,2})\s+(\d)(?=\s+[A-Z])")
#: A clue that is only a cross-reference, its count never there.
BARE_SEE = re.compile(rf"\(?\s*{SEE_WORD}\s*({SEE_NUMBER}|[lI])\s*(?:ac|dn|across|down)?\.?\s*\)?$", re.I)


# ======================================================================
# Fixes that lived in one source's reader, moved here so every source has them.
# tools/test_ocr_text_central.py fails on a new one left in a reader.
# ======================================================================

#: Mac Roman's punctuation as cp1252 reads it: a PDF set in that encoding
#: reads "SantaÕs helpers Ð seamen" for "Santa's helpers - seamen".
MAC_PUNCTUATION = str.maketrans("ÕÔÒÓÐÑ", "’‘“”–—")


def mac_punctuation(text):
    """`text` with Mac Roman's punctuation put right. Only text that shows a
    Mac quote (Õ Ô Ò Ó, none of them English) is turned, so a legitimate Ð or
    Ñ elsewhere stays."""
    if not any(c in text for c in "ÕÔÒÓ"):
        return text
    return text.translate(MAC_PUNCTUATION)


def enum_figures(printed):
    """A printed count's figures with spaces dropped and an en dash made a
    hyphen: "5 – 3" is "5-3"."""
    return re.sub(r"\s+", "", printed).replace("\u2013", "-")


def same_text_key(text):
    """`text` boiled down to compare two readings of one clue: quotes
    straightened, spaces and dashes gone."""
    return re.sub(r"[\s\u2014\u2013-]+", "", re.sub("[\u2018\u2019]", "'", text))


def mend_list_start(text):
    """The number opening a list, with the stop or speck the scan put for its
    space: "1.Religion", "1-Chinese" are "1 Religion", "1 Chinese"."""
    return re.sub(r"^(\d{1,2})[.,:;'\u2019\-\u00bb\u2022]+\s*(?=[\"'A-Za-z])", r"\1 ", text)


def mend_between_clues(text):
    """A list's run-together text with the specks and punctuation read between
    a clue's count and the next clue's number taken out."""
    # A speck the OCR read between two clues ("(3-6). _ 3 It's") is not text.
    text = re.sub(r"(\)\.?)\s+[_|*\u2022~^#=+\-\u2014.]{1,3}(?=\s)", r"\1", text)
    # So is punctuation it read between a count and the next clue's number
    # ("(10). : 6 Angry", "(5)' 6 Salt", "(9). \u25a0 \u25a0 16 Bill", "(4, 3). , ' *4
    # Be"), and what it read after that number for a space or a comma
    # ("(9) 7;Ko-ko's", "(5) 11.12A product", "(9). 10' It's").
    text = re.sub(r"(\)\.?)[\s.,:;'\u2019\"`<>\u00ab\u00bb\u25a0_|*\u2022~^#=+\-\u2014]+(?=\d)", r"\1 ", text)
    return re.sub(r"(\)\.? )(\d{1,2}(?:[.,]\s?\d{1,2})*)(?:[.,;:'\u2019]\s?|(?=[A-Z]))(?=[A-Za-z\"'])",
                  lambda m: m[1] + m[2].replace(".", ",") + " ", text)


def space_before_quote(text):
    """A quote or bracket run onto the word before it: "in\u201cThe" is
    "in \u201cThe", "sire?(anag.)" is "sire? (anag.)"."""
    return re.sub(r"(?<=[A-Za-z?!])(?=[\u201c\u2018(])", " ", text)


def mend_numbered_run(part):
    """A scan's answer list run together, its numbers mended: the 1 that opens
    it read as "i" or "|" ("DOWN: i Emma 2 Orgasm", Private Eye 54), a speck
    before a number ("2 Belgrano -3 Oppo", 63), a number run into its word
    ("12Ethelred", "28See.", "8S and M", "22.Panorama"), an underscore or
    rule for the space ("18Hess_20 Clever dick"), and the direction letter a
    link's tail may carry ("6/20d")."""
    part = re.sub(r"^\s*[|lIi](?=\s+(?:[A-Z]|\(see))", "1", part)
    part = re.sub(r"\s[-\u2013\u2014~]+(?=\d)", " ", part)
    part = re.sub(r"(?:(?<=\s)|^)(\d{1,2})(?=[A-Za-z]{2,})", r"\1 ", part)
    part = re.sub(r"(?:(?<=\s)|^)(\d{1,2})(?=[A-Za-z]\s)", r"\1 ", part)
    part = re.sub(r"(?:(?<=\s)|^)(\d{1,2})\.(?=[A-Z])", r"\1 ", part)
    part = re.sub(r"(?<=[A-Za-z])[_|](?=\d)", " ", part)
    return re.sub(r"(?:(?<=\s)|^)(\d{1,2}(?:/\d{1,2})*/\d{1,2})[ad]\b", r"\1", part)


#: A clue number's last figure and the one of like shape a reading takes it
#: for: the old-style 8 read "3" (No 3's "48." read "43."), 9 read "0".
FIGURE_SLIPS = {"3": "8", "8": "3", "0": "9", "9": "0"}


def number_figures(text):
    """A printed number read as figures only: the commas, stops, specks and
    spaces a scan put in it ("15,683", "1 5.683") taken out."""
    return re.sub(r"[\s,.^'*`\u2019\-]", "", text)


#: A figure read as a speck in front of a small word, glued to it ("0on", "2to",
#: "3go"). Only a figure 0-3 (a bar or a stroke), only before a lower-case
#: function word and not inside a longer figure, a unit ("3in") or a
#: direction ("1down"): those are print.
SPECK_FIGURE = re.compile(r"(?<![\w.,/\-])[0-3](?=(?:to|as|on|at|of|by|so|go|for|the)\b(?![\-'’\d]))")
#: The same speck in front of the clue's first "I" ("1I work", "3I'm held back").
SPECK_BEFORE_I = re.compile(r"^[0-3](?=I(?:\b|['’]))")
#: One underscore against a word's edge ("_the", "top_", "an_ uneasy"): a stroke
#: beside the print, never a blank (a blank is a run "____" or a lone " _ ").
STRAY_UNDERSCORE = re.compile(r"(?<![_\w])_(?=[a-z]{2})|(?<=[a-z]{2})_(?![_\w'’])")


def speck_figures(text):
    """`text` without the figure an OCR read in front of a small word or the
    clue's opening "I" ("0on the course" is "on the course")."""
    return SPECK_FIGURE.sub("", SPECK_BEFORE_I.sub("", text))


#: A lone "&" between two words of running text: `prev` the word before it (the
#: clue's first word, or one not capitalised), `next` a lower-case word. An old
#: scan's "a" reads as "&" ("unimpeded by & weapon"), and a reread that also reads
#: the "a" keeps the "&" in front of it ("by & a weapon"). A name's "&" ("Stalky &
#: Co", "B & B", "A & E") has a capital or figure on a side, so it is never one.
STRAY_AMPERSAND = re.compile(r"(?:^|(?<=\s))(?P<prev>[^\s&\d]+) & (?P<next>[a-z][^\s&]*)")
#: Least times the corpus prints "prev a" (and "a next") for "&" to read as "a".
AMPERSAND_A_USES = 3
#: Least product of the shares of `prev`'s uses the corpus prints before "a" and
#: of `next`'s it prints after "a", for "&" before a word to read as "a": "is &
#: mile" (5.8% x 36%), "for & current" (7.4% x 1.4%) are; "around & look" (2.8%
#: x 2.4%), "book & play", "almost & character" (under 0.07%) are print.
AMPERSAND_A_SHARE = 0.001


def stray_ampersand(text, uses=None):
    """`text` with a lone "&" in running text that is a scan's "a" mended
    (STRAY_AMPERSAND). Before "a"/"an" the "&" is dropped ("by & a weapon" is
    "by a weapon") when the corpus prints `prev` before "a" at least half as
    often as before "and" ("briefs & a Rolex", "rock & a hard place" are
    print); before another word it is the "a" ("is & mile up" is "is a mile
    up") when `prev` and `next` both go with "a" often (AMPERSAND_A_SHARE) and
    more than with "and" ("fish & chips", "I stick around & look" are print).
    `uses(w, nxt=None)` is the corpus's count of a word or a word pair
    (clue_repair.lexicon); without it nothing is mended. A clue with two
    "&"s or more, "&" after an article ("an & one") and "& co" are left as
    they are, and so is one no reading fits ("Contradiction & in law",
    "he didn't & fit in": a dropped "&" a word pair cannot tell from
    print)."""
    if uses is None or (text or "").count("&") != 1:
        return text
    m = STRAY_AMPERSAND.search(text)
    if not m:
        return text
    prev, nxt = m.group("prev"), m.group("next")
    first = not text[:m.start()].strip()
    bare_prev = re.sub(r"^\W+|\W+$", "", prev)
    bare_next = re.sub(r"\W+$", "", nxt)
    if not bare_prev or not bare_next or (prev[0].isupper() and not first) \
            or bare_prev.lower() in ("a", "an", "the") or bare_next.lower() == "co":
        return text
    amp = m.start("next") - 2
    before_a, before_and = uses(bare_prev, "a"), uses(bare_prev, "and")
    if bare_next in ("a", "an"):
        # the "&" a reread kept before the "a" it also read
        if before_a >= AMPERSAND_A_USES and 2 * before_a >= before_and:
            return text[:amp] + text[m.start("next"):]
        return text
    a_after, after_and = uses("a", bare_next), uses("and", bare_next)
    share = before_a / max(uses(bare_prev), 1) * a_after / max(uses(bare_next), 1)
    if min(before_a, a_after) >= AMPERSAND_A_USES and share >= AMPERSAND_A_SHARE \
            and min(before_a, a_after) > uses(bare_prev, bare_next) \
            and before_a > before_and and a_after > after_and:
        return text[:amp] + "a " + text[m.start("next"):]
    return text


def stray_underscore(text):
    """`text` without an underscore stuck to the edge of a word. A clue with
    two underscores or more is a puzzle of missing letters ("C_A_C_?") and
    is left as it is."""
    return STRAY_UNDERSCORE.sub("", text) if text.count("_") == 1 else text


def count_specked(figures, total):
    """Whether `figures` (2-3 digits after a clue's words) are the light's
    count `total` with a 1 glued on one or both ends, a bar the scan joined to
    it: "14", "81" and "151" for 4, 8 and 5."""
    if not (figures.isdigit() and len(figures) in (2, 3)):
        return False
    cut = []
    if figures[0] == "1":
        cut.append(figures[1:])
    if figures[-1] == "1":
        cut.append(figures[:-1])
    if len(figures) == 3 and figures[0] == figures[-1] == "1":
        cut.append(figures[1:-1])
    return any(c and int(c) == total for c in cut)


def mark_counts(text):
    """The punctuation marks in `text` as a Counter, to compare two readings
    of one clue: dashes made "-" and curly apostrophes "'" first, so a mark
    printed in either form counts the same."""
    import collections
    straight = re.sub("[\u2018\u2019]", "'", re.sub("[\u2010-\u2014]", "-", text))
    return collections.Counter(straight) - collections.Counter(
        ch for ch in text if ch.isalnum() or ch.isspace())


# ------------------------------------------- glitches a reread brings into a clue
#
# tools/audit_updates.py counts these in a clue's text before and after each
# reread ("Update ..." commits) and calls a class introduced when the new text
# has more of it, fixed when fewer. Seeded by the 7-day audit of 10-16..23
# (#cryptic-crosswords). Each is a shape the print never has, or has so seldom
# that a reread adding one is a slip: counted, not mended (see pound_sign and
# count_in_text for the two that are).

#: A space before "?" or "!" ("bone ?"). The old Times set it so (punctuation.py),
#: so it is a churn class to watch, not a rule.
SPACE_BEFORE_MARK = re.compile(r"(?<=[\w'\"\u2019\u201d)]) +[?!]")
#: The page's furniture inside a clue: a running head's "times," ("look times,
#: up", times-19892; not "At times," or "hard times,"), "crossword", a puzzle
#: number, a page number.
FURNITURE = re.compile(r"(?i)(?<![\w'])(?<!at )(?<!some )(?<!many )(?<!hard )(?<!good )(?<!bad )(?<!old )"
                       r"(?<!other )(?<!modern )times,(?=\s)|\bcrossword\b|\bno\.\s?\d{4,5}\b|\bpage\s?\d{1,3}\b")
#: A word's line-end hyphen left in, with the page or column number the line
#: break let in ("look- 2119. ing", "sea- Wart seaside"). A "pre- and post-"
#: hyphen is print.
HYPHEN_LEAK = re.compile(r"(?<=[A-Za-z])-\s+\d{2,5}\b\.?|(?<=[a-z]{2})- [·.]?(?!(?:and|or|to|nor|cum)\b)(?=[A-Za-z])")
#: "\u00a3" read as "E" before a sum ("E25"; POUND_SUM below, which leaves the London
#: postcodes E1-E20 alone), and figures glued to a word ("2A former emperor",
#: "America25"): an ordinal, a decade, a unit or "4x4" is print.
GLUED_FIGURES = re.compile(
    r"(?<![\w\u00a3$\u20ac.,/:'\-])\d+(?!(?:st|nd|rd|th|s|am|pm|m|k|p|d|cc|ft|in|lb|oz|mph|kg|km|cm|mm|ml|mg|hp|bc|ad|v|x\d+)\b)"
    r"[A-Za-z]+\b|\b[A-Za-z]{2,}\d+\b")
#: A figure standing alone in running text, no reference word before it nor a
#: unit after it ("for 9 securing prisoners"). A lone 0 or 1 before a word is ZERO_ONE's.
LONE_FIGURE = re.compile(
    r"(?<![\w\u00a3$\u20ac.,:/'(\-])(?<!see )(?<!See )(?<!and )(?<!nos )(?<!No\. )(?![01] [a-z])\d{1,4}"
    r"(?![\w%.,:/')\-])(?! ?(?:across|down|ac|dn|per|and|or|to|x|in|pm|am)\b)")
#: Marks no clue prints: a symbol, an "&" inside a word ("champ&tre"), a lone
#: stop or middle dot between words, a run of mixed marks ("33 -.(Tennyson)").
SYMBOL_JUNK = re.compile(r"[*~^|<>{}\[\]\\@#=+\u2022\u00ac\u00a7\u00a6]|(?<=[A-Za-z])&(?=[A-Za-z])|(?<=\S) [.\u00b7,;:](?= \S)"
                         r"|\s-\.|\.\(|[,;:]{2,}|\u00b7")
#: The figure "0" or "1" for the letter "O" or "I" ("1 would", "0 command",
#: "c0mmand", "1ike").
ZERO_ONE = re.compile(
    r"(?<![\w\u00a3$\u20ac.,:/'\-])[01](?= [a-z]{2,})(?! (?:across|down|ac|dn|and|or|to|of|per|in|by|at|for|from|up|out|over)\b)"
    r"|(?<=[A-Za-z])[01](?=[A-Za-z])|(?<![\w\u00a3$\u20ac.,:/'\-])0(?=[a-z]{2,})|(?<![\w\u00a3$\u20ac.,:/'\-])1(?=[a-z]{2,}\b)(?!(?:st|th)\b)")
#: A count left inside a clue's text ("contest (7) guest?"): the text never holds one.
COUNT_IN_TEXT = re.compile(r"\(\s*\d{1,2}(?:\s*[,\-\u2013.]\s*\d{1,2})*\s*\)")
#: A double quote opening the clue that nothing closes.
LEADING_QUOTE = re.compile(r'^\s*["\u201c](?![^"\u201d]*["\u201d])')
#: A spaced hyphen where a dash stood ("risk - part").
SPACED_HYPHEN = re.compile(r"(?<=\w) - (?=\w)")
#: A word printed twice ("the the").
DOUBLED_WORD = re.compile(r"(?i)\b([a-z]{2,})\s+\1\b")


def unbalanced(text):
    """How many brackets and double quotes in `text` have no partner."""
    n = abs(text.count("(") - text.count(")")) + abs(text.count("[") - text.count("]"))
    n += text.count('"') % 2 + abs(text.count("\u201c") - text.count("\u201d"))
    return n


#: class -> function(text) -> how many of that glitch `text` holds.
GLITCHES = {
    "a:space-before-mark": lambda t: len(SPACE_BEFORE_MARK.findall(t)),
    "b:furniture": lambda t: len(FURNITURE.findall(t)),
    "c:hyphen-leak": lambda t: len(HYPHEN_LEAK.findall(t)),
    "d:pound-as-E": lambda t: len(POUND_SUM.findall(t)),
    "d:glued-figures": lambda t: len(GLUED_FIGURES.findall(t)),
    "d:lone-figure": lambda t: len(LONE_FIGURE.findall(t)),
    "e:unbalanced": unbalanced,
    "e:symbol-junk": lambda t: len(SYMBOL_JUNK.findall(t)),
    "h:zero-one": lambda t: len(ZERO_ONE.findall(t)),
    "i:count-in-text": lambda t: len(COUNT_IN_TEXT.findall(t)),
    "i:leading-quote": lambda t: len(LEADING_QUOTE.findall(t)),
    "i:spaced-hyphen": lambda t: len(SPACED_HYPHEN.findall(t)),
    "i:doubled-word": lambda t: len(DOUBLED_WORD.findall(t)),
    "i:ampersand": lambda t: len(STRAY_AMPERSAND.findall(t)),
}


def glitch_counts(text):
    """{class: count} of each GLITCHES class `text` holds (none: absent)."""
    text = text or ""
    return {c: n for c, f in GLITCHES.items() if (n := f(text))}


#: The classes a reading may not gain over a held clue (file_archive_org_puzzles.corrects):
#: each is a reader's, never the print's, in the 10-16..23 rereads.
REFUSED_GLITCHES = ("b:furniture", "c:hyphen-leak", "d:pound-as-E", "d:glued-figures", "e:unbalanced",
                    "h:zero-one", "i:count-in-text")


def gains_glitch(was, now, classes=REFUSED_GLITCHES):
    """The first of `classes` the text `now` holds more of than `was`, or None."""
    a, b = glitch_counts(was), glitch_counts(now)
    return next((c for c in classes if b.get(c, 0) > a.get(c, 0)), None)


def likeness(a, b):
    """How alike two clue texts read, 0..1: their characters' match ratio,
    case and marks aside. Under 0.5 they are two clues' words, not one's."""
    import difflib

    def norm(t):
        return " ".join(re.sub(r"[^\w\s]", " ", (t or "").lower()).split())
    return difflib.SequenceMatcher(None, norm(a), norm(b), autojunk=False).ratio()


#: "E" for "£" before a sum: two figures over 20, three or four, or a sum with
#: pence or thousands ("E25", "E500", "E1.000"). E1 to E20 are London postcodes
#: ("Lives in E8 back street"), print, and stand.
POUND_SUM = re.compile(r"(?<![\w£$€])E(?=(?:[2-9]\d|\d{3,4}|\d{1,4}[.,]\d{2,3})(?![\d\w]))")


def pound_sign(text):
    """`text` with the "E" a reader made of a "£" before a sum read back
    ("with E25 left" is "with £25 left"; POUND_SUM)."""
    return POUND_SUM.sub("£", text)


#: The clue's own count left in its text with a neighbour's scraps after it:
#: "experience (5). code.", "Sounds good (5,4) first".
COUNT_TAIL = re.compile(r"\s*\(\s*(\d{1,2}(?:\s*[,\-]\s*\d{1,2})*)\s*\)(?P<rest>[^()]*)$")
#: Most words the scraps after it may hold.
COUNT_TAIL_WORDS = 4


def count_in_text(text, enum):
    """`text` cut at its own count (COUNT_TAIL): the figures the light's
    enumeration `enum` prints, part for part, with at most COUNT_TAIL_WORDS
    words of a neighbour's after it and two words or more before. Another
    count is the clue's words ("(1917)") and stands, and so do words after
    it that end as a clue does, on "?" or "!" ("it (5,3) madly protected?"),
    unless a stop or a clue number leads them ("(8) 171 Hollywood's top
    twelve?")."""
    m = COUNT_TAIL.search(text or "")
    if not m or not enum:
        return text
    if re.findall(r"\d+", m.group(1)) != re.findall(r"\d+", enum):
        return text
    rest = m.group("rest").strip()
    if len(re.findall(r"[A-Za-z]+", rest)) > COUNT_TAIL_WORDS or len(text[:m.start()].split()) < 2:
        return text
    if rest and rest[-1] in "?!" and not re.match(r"[.,;:\d]", rest):
        return text
    return text[:m.start()].rstrip()
