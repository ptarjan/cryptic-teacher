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
    before a capital, to a space after a word no sentence ends on
    ("of.Scotland") or a clue's capitalised first word ("Forever.Amber"),
    and to ". " after a title ("Mr.Quiverful"); else it stands ("Ursa.Minor",
    "Indo.European", "Bull.The");
  - two apostrophes for a double quote (''Master Spy''): mended to '"'
    when the clue's double quotes then pair, save one beside another quote;
    a word's "''s" ("sight''s") is mended to "'s"; a "''" paired with a
    single "'" ("'The Planets''", "''fits are violent'") is mended to "'"
    when the clue's quote marks open and close in turn, save beside a
    clipped word ("''coz of monster'");
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

A mend that leaves its clue one the write gate refuses (gate_refuses) is
not made on a filed clue (unmend_refused): the held words pass as they are.
"""
import copy
import re

#: Endings after a stop that make a web address, not two words.
WEB = {"com", "net", "org", "co", "uk", "tv", "eu", "io", "gov", "edu", "info", "biz", "ac", "fm", "me", "ie", "au", "de", "fr"}
#: Words written with a stop that a word may follow: "etc. require".
ABBREVIATIONS = {"etc", "viz", "esp", "approx", "incl", "cf", "vs", "op", "cit", "no", "nos", "st", "mr", "mrs", "ms",
                 "dr", "co", "ltd", "inc", "vol", "pp", "ed", "eds", "fig", "ch", "sq", "rev", "hon", "rt", "sr", "jr",
                 "bros", "gen", "col", "capt", "lt", "sgt", "prof", "abbr", "misc", "cont", "max", "min", "ft", "ad", "bc",
                 "am", "pm", "ie", "eg", "nb", "ps", "pt", "mt"}

#: Titles written with a stop before a name: "Mr. Quiverful".
TITLES = {"mr", "mrs", "ms", "dr", "st", "no", "prof", "capt", "lt", "sgt", "mt"}
#: Words no sentence ends on, so a stop glued after one ends no sentence.
NO_SENTENCE_END = {"the", "an", "of", "for", "and", "with", "into", "from", "which", "at", "by"}
#: Words a second sentence opens on: "Stop.Then go" may be "Stop. Then go".
SENTENCE_OPENERS = set("""the a an then it he she they we you i this that these those there here but so
    now what how why who where when if and or not no yes all one his her its our their my your in on at to
    for with as is was do does did let just still yet""".split())

GLUED_STOP = re.compile(r"(?<![\w.'@/])([A-Za-z]{2,})\.([A-Za-z][a-z]*)\b(?![.@/]\w)")
TWO_APOSTROPHES = re.compile(r"''")
TWO_MARKS = re.compile(r"[,;:][,;:]|[,;:]\.(?!\.)|(?<![\w.])([A-Za-z]{2,})\.(?=[,;:])")
SPACED_COMMA = re.compile(r"(?<=[A-Za-z]) ,(?=[ A-Za-z]|$)")
#: Marks a reader made of a speck: a middle dot (never print), a stop standing
#: alone between two words ("grey . donkey"), two stops at a clue's start or
#: end (a leader or trailer: ".. and 5", "dive ..": dashes.py leaves ".." in
#: the middle alone), and the stop after a lone "a" ("for a. child"; not "M.A. or").
MIDDLE_DOT = re.compile(r" ?· ?")
LONE_STOP = re.compile(r"(?<=\S) \.(?= \S)")
DOUBLE_STOP = re.compile(r"^\.\.(?![.…])|(?<![.…])\.\.$")
ARTICLE_STOP = re.compile(r"(?<![\w.])[Aa]\.(?= [a-z])")


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


#: A quote mark of one or two apostrophes not inside a word ("Lady's").
QUOTE_MARK = re.compile(r"''?")


#: Words clipped with an apostrophe that may follow a quote's opener:
#: "''coz of monster'" is "'" and "'coz", not a stray mark.
CLIPPED = {"coz", "cos", "cause", "em", "tis", "twas", "twere", "n", "til", "ere", "bout", "neath", "un", "ow"}


def _clipped(text, a, b):
    """Whether the quote pair `a`, `b` (QUOTE_MARK spans) holds a word's own
    apostrophe beside a mark: an opener before a clipped word ("'coz",
    "'ole" for "hole") or a closer after one ("huntin'" for "hunting")."""
    import ocr_clues
    first = re.match(r"[A-Za-z]+", text[a[1]:])
    last = re.search(r"[A-Za-z]+$", text[:b[0]])
    if first:
        w = first.group().lower()
        if w in CLIPPED or not ocr_clues.is_word(w) and ocr_clues.is_word("h" + w):
            return True
    if last:
        w = last.group().lower()
        if w.endswith("in") and not ocr_clues.is_word(w) and ocr_clues.is_word(w + "g"):
            return True
    return False


def _single_pairs(text):
    """[(start, end, "'")] for each "''" that pairs with a single "'":
    "'The Planets''" and "''fits are violent'" are single quotes. Only when
    every quote mark of the clue outside a word opens or closes in turn
    (an opener after a space or the clue's start, a closer before one or
    its end), no double quote among them: a plural's "boys'" or a "'n'"
    breaks the turn and leaves the clue for the re-read."""
    if '"' in text:
        return []
    marks = []
    for m in QUOTE_MARK.finditer(text):
        left = text[m.start() - 1] if m.start() else " "
        right = text[m.end()] if m.end() < len(text) else " "
        if left.isalnum() and right.isalnum():
            if m.group() == "'":
                continue  # a word's own: "Lady's", "don't"
            return []
        opens = not left.isalnum() and left not in ".,;:!?" and not right.isspace()
        closes = not right.isalnum() and not left.isspace()
        if opens == closes:
            return []
        marks.append((m.start(), m.end(), opens))
    if not marks or len(marks) % 2 or any(o != (i % 2 == 0) for i, (_, _, o) in enumerate(marks)):
        return []
    out = []
    for a, b in zip(marks[::2], marks[1::2]):
        widths = {a[1] - a[0], b[1] - b[0]}
        if _clipped(text, a, b):
            continue
        if widths == {1, 2}:
            two = a if a[1] - a[0] == 2 else b
            out.append((two[0], two[1], "'"))
        elif widths == {2}:
            out += [(a[0], a[1], '"'), (b[0], b[1], '"')]
    return out


def _edits(text):
    """[(start, end, replacement)] of each certain mend in `text`, in order,
    none overlapping."""
    import ocr_clues
    out = []
    for m in GLUED_STOP.finditer(text):
        if not _glued(m):
            continue
        dot = m.start() + len(m[1])
        if not m[2].islower():
            # A capital after the stop may open a sentence ("Bull.The"),
            # save after a title ("Mr.Quiverful": a space after the stop),
            # a word no sentence ends on ("of.Scotland") or a clue's
            # capitalised first word ("Forever.Amber"): a space for the stop.
            if m[1].lower() in TITLES:
                out.append((dot + 1, dot + 1, " "))
            elif m[1] in NO_SENTENCE_END or m.start() == 0 and m[1].istitle() \
                    and m[1].lower() not in ABBREVIATIONS and ocr_clues.is_word(m[1].lower()) \
                    and m[2].lower() not in SENTENCE_OPENERS:
                out.append((dot, dot + 1, " "))
            continue
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
    else:
        out += _single_pairs(text)
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
    for m in MIDDLE_DOT.finditer(text):
        lone = m.start() == 0 or m.end() == len(text) or text[m.end()] in "?!,.;:)"
        out.append((m.start(), m.end(), "" if lone else " "))
    for m in LONE_STOP.finditer(text):
        out.append((m.start(), m.end(), ""))
    for m in DOUBLE_STOP.finditer(text):
        out.append((m.start(), m.end(), "…"))
    for m in ARTICLE_STOP.finditer(text):
        out.append((m.end() - 1, m.end(), ""))
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
    annotation moved with them (enumeration.rewrite_entry), its prose
    mended alike. Whether anything changed."""
    import enumeration
    if not enumeration.rewrite_entry(entry, mend):
        return False
    note = entry.get("annotation") if isinstance(entry.get("annotation"), dict) else {}
    prose = note.get("explanation")
    if isinstance(prose, str):
        note["explanation"] = mended(prose)
    elif isinstance(prose, list):
        note["explanation"] = [mended(t) if isinstance(t, str) else t for t in prose]
    return True


def mend_puzzle(puzzle):
    """{light: its clue now} for each clue of `puzzle` mend_entry changed,
    in place. A clue the mends would leave one the write gate refuses (gate_refuses:
    "one . , owner" to "one , owner") stays as it was (unmend_refused)."""
    from groups import entry_id
    before = {entry_id(e): copy.deepcopy(e) for e in puzzle.get("entries") or () if "number" in e and "direction" in e}
    return unmend_refused(puzzle, before, {entry_id(e): e["clue"]["text"]
                                           for e in puzzle.get("entries") or () if mend_entry(e)})


def gate_refuses(clue):
    """Whether puzzle_integrity's write gate refuses `clue` as a changed OCR clue: a fault
    (check_new_punctuation), a run of spaces (check_new_spaces) or the page's text (check_new_bleed)."""
    import ocr_clues
    text = clue.get("text") if isinstance(clue, dict) else None
    return bool(text) and bool(faults(text) or "  " in text or ocr_clues.bled(text, clue.get("asPrinted") or ()))


def unmend_refused(puzzle, before, mended):
    """`mended` ({light: its clue now}) less each light whose mended clue the write gate refuses
    (gate_refuses), that entry of `puzzle` put back as `before` ({light: the entry before}) holds
    it, in place. A certain mend that leaves a fault ("one . , owner" to "one , owner") or the
    page's text ("(7,.4) Original" to "(7, 4) Original") changes a held clue into one the gate
    refuses as new, and the write goes whole, its answers with it; the held words as they were pass
    and stay for the re-read. 10-25: 17 Times grids' answers refused so."""
    from groups import entry_id
    out = dict(mended)
    for e in puzzle.get("entries") or ():
        if "number" not in e or "direction" not in e:
            continue
        lid = entry_id(e)
        if lid in out and lid in before and gate_refuses(e.get("clue")):
            e.clear()
            e.update(copy.deepcopy(before[lid]))
            del out[lid]
    return out


def faulted(puzzle):
    """The lights of `puzzle` whose clue text faults() flags."""
    from groups import entry_id
    return {entry_id(e) for e in puzzle.get("entries") or ()
            if faults(((e.get("clue") if isinstance(e.get("clue"), dict) else None) or {}).get("text"))}
