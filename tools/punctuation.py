"""English punctuation no clue's print breaks, found and mended in OCR text.

Each rule below is a mark a reader made, not the setter: hand-read samples
of the OCR channels' clues (provenance.OCR_CHANNELS) found every hit an
error. faults() names them; mend() mends the ones whose fix is certain and
leaves the rest for a re-read (edition_commit.strayed makes the edition
due). An unpaired bracket is ocr_clues.bled's, not this module's.

  - a stop glued to the next word ("by.clever", "over.a", "in.Carroll's"),
    save a web address ("theguardian.com") and initials ("e.g", "Ph.D"):
    mended to a space when the words either side are dictionary words
    (or the next is "a") and the next is lower case, and to ". " after an abbreviation ("etc.require");
  - two apostrophes for a double quote (''Master Spy''): mended to '"'
    when the clue's double quotes then pair, save one beside another quote;
    a word's "''s" ("sight''s") is mended to "'s";
  - two marks in a row (",,", ",.", ";:", "boxer.,"), save an ellipsis and
    an abbreviation's stop ("etc.,"): a doubled mark mended to one, a stop
    after a comma, semicolon or colon (or after a word's own stop before
    one) dropped; two different marks of , ; : stand for the re-read;
  - a comma with a space before it and none of the words' marks around it
    ("Gaping , mouth", "the ,message"): no mend, the comma may stand for a
    lost dash.

A space before ? ! ; : is the old Times's own setting, and an odd count of
double quotes is a quote spanning clues or a seconds mark (4'33"): neither
is a rule.
"""
import re

#: Endings after a stop that make a web address, not two words.
WEB = {"com", "net", "org", "co", "uk", "tv", "eu", "io", "gov", "edu", "info", "biz", "ac", "fm", "me", "ie", "au", "de", "fr"}
#: Words written with a stop that a word may follow: "etc. require".
ABBREVIATIONS = {"etc", "viz", "esp", "approx", "incl", "cf", "vs", "op", "cit", "no", "nos", "st", "mr", "mrs", "ms",
                 "dr", "co", "ltd", "inc", "vol", "pp", "ed", "eds", "fig", "ch", "sq", "rev", "hon", "rt", "sr", "jr",
                 "bros", "gen", "col", "capt", "lt", "sgt", "prof", "abbr", "misc", "cont", "max", "min", "ft", "ad", "bc",
                 "am", "pm", "ie", "eg", "nb", "ps", "pt", "mt"}

GLUED_STOP = re.compile(r"(?<![\w.'@/])([A-Za-z]{2,})\.([A-Za-z][a-z]*)\b(?![.@/]\w)")
TWO_APOSTROPHES = re.compile(r"''")
TWO_MARKS = re.compile(r"[,;:][,;:]|[,;:]\.(?!\.)|(?<![\w.])([A-Za-z]{2,})\.(?=[,;:])")
SPACED_COMMA = re.compile(r"(?<=[A-Za-z]) ,(?=[ A-Za-z]|$)")


def _glued(m):
    """Whether the GLUED_STOP match `m` is two words, not an address or initials."""
    before, after = m[1], m[2]
    if after.islower() and after in WEB:
        return False
    return not (after[:1].isupper() and len(after) == 1)


def faults(text, capitals=True):
    """[(rule, snippet)] for each punctuation fault in `text`, in order.
    Without `capitals`, not a stop glued to a capital ("Bull.The"), which
    may end a sentence: its mend is a space after it, not its loss."""
    text = text or ""
    out = []
    for m in GLUED_STOP.finditer(text):
        if _glued(m) and (capitals or m[2].islower()):
            out.append((m.start(), "a stop glued to the next word", m.group()))
    for m in TWO_APOSTROPHES.finditer(text):
        out.append((m.start(), "two apostrophes for a double quote", text[max(0, m.start() - 8):m.end() + 8]))
    for m in TWO_MARKS.finditer(text):
        if m[1] and m[1].lower() in ABBREVIATIONS:
            continue
        out.append((m.start(), "two marks in a row", text[max(0, m.start() - 8):m.end() + 8]))
    for m in SPACED_COMMA.finditer(text):
        out.append((m.start(), "a space before a comma", text[max(0, m.start() - 8):m.end() + 8]))
    return [(why, snip.strip()) for _, why, snip in sorted(out)]


def _edits(text):
    """[(start, end, replacement)] of each certain mend in `text`, in order,
    none overlapping."""
    import ocr_clues
    out = []
    for m in GLUED_STOP.finditer(text):
        if not _glued(m) or not m[2].islower():
            continue
        dot = m.start() + len(m[1])
        if m[1].lower() in ABBREVIATIONS:
            out.append((dot + 1, dot + 1, " "))
        elif (m[1].islower() or m[1].istitle()) and ocr_clues.is_word(m[1].lower()) \
                and (m[2] == "a" or ocr_clues.is_word(m[2])):
            out.append((dot, dot + 1, " "))
    quotes = []
    for m in TWO_APOSTROPHES.finditer(text):
        left = text[m.start() - 1] if m.start() else " "
        right = text[m.end()] if m.end() < len(text) else " "
        if left.isalpha() and re.match(r"s\b", text[m.end():]):
            out.append((m.start(), m.end(), "'"))  # a word's "'s": "Welshman''s"
            continue
        if left in "'\"" or right in "'\"" or left.isalnum() and right.isalnum():
            continue
        quotes.append((m.start(), m.end(), '"'))
    # Only when the clue's double quotes then pair: one "''" closing a
    # single quote ("'Kill''") is no double quote.
    if (text.count('"') + len(quotes)) % 2 == 0:
        out += quotes
    for m in TWO_MARKS.finditer(text):
        s = m.group()
        glued = m.end() + (1 if m[1] else 0) < len(text) and text[m.end() + (1 if m[1] else 0)].isalnum()
        if m[1]:
            if m[1].lower() not in ABBREVIATIONS and not glued:
                out.append((m.end() - 1, m.end(), ""))
        elif s[0] == s[1]:
            out.append((m.start() + 1, m.end(), " " if glued else ""))
        elif s[1] == ".":
            out.append((m.start() + 1, m.end(), " " if glued else ""))
    out.sort()
    kept = []
    for e in out:
        if not kept or e[0] >= kept[-1][1] and e[0] != kept[-1][0]:
            kept.append(e)
    return kept


def mend(text):
    """(`text` with each certain mend made, [new offset of each old offset
    0..len(text)])."""
    text = text or ""
    at, built, k = [], "", 0
    for start, end, rep in (_edits(text) if text else []) + [(len(text), len(text), "")]:
        while k < start:
            at.append(len(built))
            built += text[k]
            k += 1
        while k < end:
            at.append(len(built))
            k += 1
        built += rep
    at.append(len(built))
    return built, at


def mended(text):
    """`text` with each certain mend made (mend)."""
    return mend(text)[0]


def mend_entry(entry):
    """Make `entry`'s clue text's certain mends in place, its italics and
    annotation moved with them (enumeration.edit_entry). Whether anything
    changed."""
    import enumeration
    return enumeration.edit_entry(entry, mend, mended)


def mend_puzzle(puzzle):
    """{light: its clue now} for each clue of `puzzle` mend_entry changed,
    in place."""
    from groups import entry_id
    return {entry_id(e): e["clue"]["text"] for e in puzzle.get("entries") or () if mend_entry(e)}


def faulted(puzzle):
    """The lights of `puzzle` whose clue text faults() flags."""
    from groups import entry_id
    return {entry_id(e) for e in puzzle.get("entries") or ()
            if faults(((e.get("clue") if isinstance(e.get("clue"), dict) else None) or {}).get("text"))}
