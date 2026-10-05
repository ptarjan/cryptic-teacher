"""A clue's printed enumeration: the letter counts in brackets after its words.

The clue object keeps the two apart: `text` is the words, `enumeration` the
bracket's content in one spelling, "5,4" or "2-3,4" or "6 and 5". split() is
the one place a printed clue string is cut into the two; every writer calls it
when it builds a clue. printed() joins them back into the line a solver reads.

The enumeration is stored rather than rebuilt from `separators` and the
light's length: a linked answer's leader prints the whole group's count, a
Private Eye continuation prints its own, and some prints ("6 and 5", "1 4",
"(8) (8)") carry what separators cannot say."""

import re

# Digit runs joined by one mark each, as printed: "5,4", "2-3", "4'1", "3/5",
# "6 and 5", "1 4" (a space alone as the break), "6.6".
_MARK = r"(?:[,\-–—\u2011.;:/'’′]|\band\b)"
_PRINTED = r"\d+(?:(?:\s*" + _MARK + r"){0,2}\s*\d+)*"

# The trailing bracket: an enumeration, or "()" where a feed lost it. A stray
# trailing comma inside ("(9,)") is a misprint of the same count, and a closing
# quote or mark after it ("(4)’", "(4))", "(7)!", "(5)>": a blog's
# markup or a feed's punctuation leaking) is no part of the clue.
_JUNK = r"[\s’”\"'()\[\]<>;.!?:,\-–—…|]*"
_TAIL = re.compile(r"\s*\(\s*(?:(" + _PRINTED + r")[\s,]*)?\)(" + _JUNK + r")$")

#: The largest total a tail's junk is trusted behind: a bracket of bigger
#: numbers followed by a mark is a year or a quantity in the clue's own words
#: ("... Wall Street share prices (1929)?").
JUNK_LIMIT = 60

#: The stored form (the schema's `enumeration` pattern): marks unspaced,
#: dashes as "-", apostrophes as "'", a lone space or " and " between counts.
FORM = re.compile(r"\d+(?:(?:[,\-.;:/']| | and )\d+)*")


#: A count in words at a clue's end, the Mephisto's "(11, two words)": the
#: total and how many words, with no breaks. It stays in the clue's text as
#: printed, since `enumeration` holds counts and marks alone.
WORDED = re.compile(r"\(\s*(\d{1,2})\s*,\s*(two|three|four|five|six|seven|eight)\s+words\s*\)\s*$",
                    re.IGNORECASE)
NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}


def worded(text):
    """(total, words) for a text ending in a count in words, else None."""
    m = WORDED.search(text or "")
    return (int(m.group(1)), NUMBER_WORDS[m.group(2).lower()]) if m else None


def _spelling(printed):
    s = (printed.replace("–", "-").replace("—", "-").replace("\u2011", "-")
         .replace("’", "'").replace("′", "'"))
    s = re.sub(r"\s*([,\-.;:/'])\s*", r"\1", s)
    s = re.sub(r"'[,\-.;:/]", "'", s)    # "3-1'-4-5": the apostrophe is the break
    s = re.sub(r"\s*\band\b\s*", " and ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tail(printed):
    """The trailing count bracket of a printed line, or None. Marks after the
    bracket belong to it only behind a count small enough to be one."""
    m = _TAIL.search(printed)
    if m and m.group(2).strip() and m.group(1) and sum(counts(m.group(1))) > JUNK_LIMIT:
        return None
    return m


def two_counts(clue):
    """True when the clue's text closes on the first of two counts the source
    printed, the second being `enumeration`: "Mother's cross raised (3); (4)"
    is text "... (3);" over "4", Big Dave's "Platform from up on high? (5) (7)"
    is text "... (5)" over "7", and "(6;6)" holds both in one bracket. The
    first is the paper's own: a preamble's second count, a theme's count of
    the letters the wordplay makes, a cross-reference to other clues, or a
    misprint the blog corrected after it."""
    m = _tail(clue.get("text") or "")
    if not (m and m.group(1)):
        return False
    return _paired(m) or (not m.group(2).strip() and "enumeration" in clue)


def _paired(m):
    """A tail written as the first of two counts with ";" after or inside it:
    the two counts may share a total (Cyclops 537's "(6,5); (4,7)"), so this
    is never an echo to cut."""
    return ";" in m.group(1) or m.group(2).strip() == ";"


def _own(clue, totals):
    stored = clue.get("enumeration")
    return {*totals, *((sum(counts(stored)),) if stored else ())}


def stray(clue, totals=()):
    """True when a clue's text ends in its own count with marks after it
    ("... (4))", "... (7)!"): a copy of the count the light, its group or the
    stored enumeration (`totals`) already says, behind a feed's or a blog's
    markup, which split() cuts (the write gate refuses these). A count that
    says anything else is no copy; disagrees() names it."""
    m = _tail(clue.get("text") or "")
    if not (m and m.group(1) and m.group(2).strip()) or two_counts(clue):
        return False
    return sum(counts(m.group(1))) in _own(clue, totals)


def disagrees(clue, totals=()):
    """The count closing a clue's text, as printed, when marks follow it and
    it names neither the light, its group nor the stored enumeration
    (`totals`), else None: "... (7.8) ' -" read off a scan's "(7,6)". It is
    no copy for split() to cut and no second count (two_counts()), so the
    text is another entry's or the count was misread, and cutting it would
    hide which; the write gate refuses it. A year or quantity above
    JUNK_LIMIT is the clue's own words."""
    m = _tail(clue.get("text") or "")
    if not (m and m.group(1) and m.group(2).strip()) or two_counts(clue):
        return None
    total = sum(counts(m.group(1)))
    if total > JUNK_LIMIT or total in _own(clue, totals):
        return None
    return m.group(1)


def split(printed):
    """A printed clue line -> (text or None, enumeration or None).

    Only a bracket at the very end that holds counts is an enumeration; "See 5"
    and "(see 3dn.)" stay text. An empty "()" is dropped as a lost enumeration.
    text is None when the line held nothing but the enumeration."""
    printed = printed or ""
    m = _tail(printed)
    if not m:
        return (printed.rstrip() or None), None
    text = printed[:m.start()].rstrip()
    enum = _spelling(m.group(1)) if m.group(1) else None
    # A source that prints the count itself and has one appended after it
    # ("Set meal (5,1'4) (5,5)") leaves the same total twice; the echo is cut
    # with the count it repeats.
    while enum and (e := _tail(text)) and e.group(1) and counts(e.group(1)) \
            and not _paired(e) and sum(counts(e.group(1))) == sum(counts(enum)):
        text = text[:e.start()].rstrip()
    return (text or None), enum


def clue(printed, **keys):
    """A clue object from a printed line plus its other keys (separators,
    italics, missing, ...); empty values are left out."""
    text, enumeration = split(printed)
    out = {"text": text, "enumeration": enumeration, **keys}
    out["italics"] = clip_italics(out.get("italics"), text)
    return {k: v for k, v in out.items() if v not in (None, "", [], {}, False)}


def clip_italics(italics, text):
    """Italic spans cut to the words: a span the paper ran over the space
    before the enumeration ends where the words do."""
    n, out = len(text or ""), []
    for r in italics or ():
        end = min(r["at"] + r["length"], n)
        if end > r["at"]:
            out.append({"at": r["at"], "length": end - r["at"]})
    return out


def printed(clue):
    """The clue as a solver reads it: its words, then "(enumeration)"."""
    text, enumeration = clue.get("text", ""), clue.get("enumeration")
    if not enumeration:
        return text
    return f"{text} ({enumeration})" if text else f"({enumeration})"


def counts(enumeration):
    """The letter counts an enumeration prints: "2-3,4" -> [2, 3, 4]."""
    return [int(n) for n in re.findall(r"\d+", enumeration or "")]


def unsplit(clue, totals=()):
    """True when a clue's text still ends in an enumeration it should have
    handed to `enumeration` (the write gate refuses these).

    With no enumeration key, any trailing count is one. With one, the text
    holds a second copy of it, recognised by a total that is the light's, its
    linked group's, or the stored enumeration's (`totals`): "Set meal (5,1'4)"
    over "5,5". A bracket whose numbers are no such total is the clue's own
    words ("... (1917)", "... (500)") and stays."""
    m = _tail(clue.get("text") or "")
    if m and m.group(1) and _paired(m) and "enumeration" in clue:
        return False
    enum = split(clue.get("text", ""))[1]
    if enum is None:
        return False
    if "enumeration" not in clue:
        return True
    return sum(counts(enum)) in {*totals, sum(counts(clue["enumeration"]))}
