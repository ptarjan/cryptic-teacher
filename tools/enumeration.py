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
# trailing comma inside ("(9,)") is a misprint of the same count.
_TAIL = re.compile(r"\s*\(\s*(?:(" + _PRINTED + r")[\s,]*)?\)\s*$")

#: The stored form (the schema's `enumeration` pattern): marks unspaced,
#: dashes as "-", apostrophes as "'", a lone space or " and " between counts.
FORM = re.compile(r"\d+(?:(?:[,\-.;:/']| | and )\d+)*")


def _spelling(printed):
    s = (printed.replace("–", "-").replace("—", "-").replace("\u2011", "-")
         .replace("’", "'").replace("′", "'"))
    s = re.sub(r"\s*([,\-.;:/'])\s*", r"\1", s)
    s = re.sub(r"'[,\-.;:/]", "'", s)    # "3-1'-4-5": the apostrophe is the break
    s = re.sub(r"\s*\band\b\s*", " and ", s)
    return re.sub(r"\s+", " ", s).strip()


def split(printed):
    """A printed clue line -> (text or None, enumeration or None).

    Only a bracket at the very end that holds counts is an enumeration; "See 5"
    and "(see 3dn.)" stay text. An empty "()" is dropped as a lost enumeration.
    text is None when the line held nothing but the enumeration."""
    printed = printed or ""
    m = _TAIL.search(printed)
    if not m:
        return (printed.rstrip() or None), None
    text = printed[:m.start()].rstrip()
    enum = _spelling(m.group(1)) if m.group(1) else None
    # A source that prints the count itself and has one appended after it
    # ("Set meal (5,1'4) (5,5)") leaves the same total twice; the echo is cut
    # with the count it repeats.
    while enum and (e := _TAIL.search(text)) and e.group(1) and counts(e.group(1)) \
            and sum(counts(e.group(1))) == sum(counts(enum)):
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
    enum = split(clue.get("text", ""))[1]
    if enum is None:
        return False
    if "enumeration" not in clue:
        return True
    return sum(counts(enum)) in {*totals, sum(counts(clue["enumeration"]))}
