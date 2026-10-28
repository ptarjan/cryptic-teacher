#!/usr/bin/env python3
"""Repair a parsed clue list from another reading of the same clues.

A newspaper OCR's clue list loses about one clue a puzzle: a clue number
read as junk ("tfl" for 10) glues that clue onto the one before, a broken
bracket ("(6,\\n4> , ,") eats an enumeration, and "(S)" reads as 5 or 8.
Each blocks tools/reconstruct_grid.py. Both scan filers
(tools/file_trove_puzzles.py, tools/file_archive_org_puzzles.py) hand a
parsed list to repaired() with the other readings of the page's clue
columns: tools/ocr_clues.py's READERS and the VLM (tools/vlm_reader.py),
the one set of readings that also vote on every clue's words. This module
reads nothing itself.

Another reading loses things too (RapidOCR often drops brackets and the bold
clue numbers), so it never replaces a list. It is a second witness, and
every change it makes is anchored by text both readings share:

  1. A clue number missing from the list is split off the clue before it
     when the other reading has that number in front of words that the
     list's text of the clue before contains.
  2. A clue with no enumeration, or one read several ways, takes the counts
     the other reading has right after the clue's last words, less the next
     clue's number. A count the list left ambiguous must be one of its
     readings; digits the list kept in a broken bracket must be the same
     digits in the same order. The counts keep their parts: the readers
     print a comma as a period ("(3.6.5)" for SIR EDWARD ELGAR's 3,6,5),
     read here as the comma; a hyphen read as a hyphen stays one. A period
     may be a hyphen read small, but the word break is the print's either
     way, and a bare total ("14") files the answer as one word.
  3. A clue number read several ways takes the number the other reading has
     right before the clue's first words, when it is one of those ways.
"""
import re
import clue_text

#: Letters a text anchor must share; fewer match by chance.
ANCHOR = 12
#: Letters at a span's edge the two readings may disagree on.
SLIDE = 8
#: Characters after a clue's last words searched for its enumeration.
TAIL = 30


# ------------------------------------------------------------ the repair

def letters(text):
    """(lowercase letters of text, the index in text of each)."""
    idx = [i for i, ch in enumerate(text) if ch.isalpha()]
    return "".join(text[i].lower() for i in idx), idx


def slide(hay, near, least, backward=False):
    """Where `near` (letters from one reading, `near[0]` the edge of the
    span) begins in `hay` (the other reading), letting a few letters at the
    edge differ: the first ANCHOR-letter window of near found once in hay
    places it, shifted back by its offset, when that is at least `least`.
    backward: near runs leftward from the span's end, and the result is
    the end. None when no window places it."""
    for off in range(SLIDE + 1):
        w = near[off:off + ANCHOR]
        if len(w) < ANCHOR:
            return None
        if backward:
            at = find_once(hay, w[::-1])
            if at is not None:
                return at + ANCHOR + off
        else:
            at = find_once(hay, w)
            if at is not None and at - off >= least:
                return at - off
    return None


def find_once(hay, needle):
    """needle's one position in hay, or None when absent or repeated."""
    at = hay.find(needle)
    return at if at >= 0 and hay.find(needle, at + 1) < 0 else None


def numbers(parsed):
    return {next(iter(c["tokens"][0])) for v in parsed.values() for c in v
            if len(c["tokens"][0]) == 1}




def tail_enum(seg, nxt):
    """The enumeration printed in `seg` (the text between a clue's last word
    and the next clue's first), less the next clue's number `nxt` (its
    readings), or None."""
    m = re.search(r"(\d{1,2})\s*[.,]?\s*$", seg)
    if m and int(m.group(1)) in nxt and re.search(r"\d", seg[:m.start()]):
        seg = seg[:m.start()]
    m = clue_text.ENUM_SEG.fullmatch(seg)
    if not m:
        return None
    enum = re.sub(r"\s*-\s*", "-", m.group(1))
    enum = re.sub(r"\s*[,.]\s*|\s+", ",", enum)
    parts = [int(n) for n in re.findall(r"\d+", enum)]
    return enum if all(parts) and sum(parts) <= 15 else None


def split_lost(direction, parsed, stream, s_letters, s_idx, notes):
    """Step 1: clues the other reading numbers that the list lacks."""
    import file_trove_puzzles as ftp
    out = parsed[direction]
    top = max(numbers(parsed), default=0)
    # A number a linked head of the list names after its first ("1, 9 But are there talking
    # pictures ...") is that clue's, never one the list lost: the other reading's "1, 9 But"
    # read its 9 before words, so 9 was split off the head, the head left with no words and its
    # count moved to a clue 9 on 8 cells, and no reading laid 9 across (failure shapes r27,
    # Gale 1954-06-19, 1966-05-31: "no reading laid a clue on it").
    # With the linked-clue mends off (clue_text.set_linked_mends), split as before, the keep noted.
    linked = {n for c in out for t in c["tokens"][1:] if len(t) == 1 for n in t}
    for m in re.finditer(r"(?<![\w(,.\-])(\d{1,2})\s*[.,]?\s*(?=[A-Z])", stream):
        n = int(m.group(1))
        if n > top or any(c["tokens"][0] == {n} for c in out):
            continue
        if n in linked:
            if clue_text.linked_mends():
                continue
            clue_text.linked_missed(True)
        k = next((i for i, c in enumerate(out) if len(c["tokens"][0]) == 1
                  and next(iter(c["tokens"][0])) < n
                  and (i + 1 == len(out) or min(out[i + 1]["tokens"][0] or {99}) > n)), None)
        if k is None or out[k]["see"] is not None:
            continue
        at = next((j for j, i in enumerate(s_idx) if i >= m.end()), None)
        if at is None:
            continue
        c = out[k]
        c_letters, c_idx = letters(c["text"])
        pos = slide(c_letters, s_letters[at:at + ANCHOR + SLIDE], 1)
        if not pos:
            continue
        cut = c_idx[pos]
        before = c["text"][:cut].rstrip()
        # The junk the list read for the number ("tfl", "6."), then the bracket.
        before = re.sub(rf"\s*(?:{ftp.NUM}|{ftp.JUNK_NUM}|\S{{1,3}})[.,]?$", "", before)
        enums = set()
        b = re.search(r"\(([^()]{1,12})\)[\s.,]*$", before)
        if b:
            enums = ftp.enum_readings(b.group(1))
            before = before[:b.start()].rstrip()
        split(out, k, cut, before, enums, n)
        notes.append(f"{n} {direction}: split off {c_number(c)} {direction}")
    # The list kept the number but a broken bracket before it hid the clue's
    # start: "sat (6, 4> , , 6. Rumour", "'1^7). 16 Eminent", the number one
    # the list lacks.
    k = 0
    while k < len(out):
        c = out[k]
        lo = min(c["tokens"][0] or {99})
        hi = min(out[k + 1]["tokens"][0] or {99}) if k + 1 < len(out) else 99
        for m in re.finditer(rf"(?:\([^()a-zA-Z]{{0,12}}|[\d)>\]}}][).,]*)\s({ftp.NUM})[.,]?\s+(?=[A-Z])", c["text"]):
            ns = {n for n in ftp.readings(m.group(1)) if lo < n < hi
                  and not any(n in o["tokens"][0] for o in out)}
            if len(ns) == 1 and c["see"] is None:
                n = ns.pop()
                split(out, k, m.end(), c["text"][:m.start(1)].rstrip(), set(), n)
                notes.append(f"{n} {direction}: split off {c_number(c)} {direction} at the list's own number")
                break
        k += 1


def split(out, k, cut, before, enums, n):
    """Clue k becomes `before` (with `enums`) and clue n from `cut` on."""
    c = out[k]
    out[k:k + 1] = [dict(c, text=before, enums=enums),
                    {"tokens": [{n}], "text": c["text"][cut:].strip(),
                     "enums": c["enums"], "see": None}]


def c_number(c):
    return "/".join(map(str, sorted(c["tokens"][0]))) or "?"


def fix_enum(direction, parsed, stream, s_letters, s_idx, notes):
    """Step 2: an enumeration the list lost or left ambiguous."""
    import file_trove_puzzles as ftp
    out = parsed[direction]
    for i, c in enumerate(out):
        if c["see"] is not None or len(c["enums"]) == 1:
            continue
        text = c["text"]
        broken = re.search(r"\s*[(\[{]([^()a-zA-Z]{0,12})$", text)
        loose = None
        kept = re.sub(r"\D", "", broken.group(1)) if broken else ""
        bare = text[:broken.start()] if broken else text
        # What is left of a bracket the OCR broke: "warmth 0).", "nian'1^7).".
        junk = re.search(r"[^A-Za-z?!]*\d[^A-Za-z?!]*$", bare)
        if junk and not broken:
            loose = re.sub(r"\D", "", junk.group(0))
            bare = bare[:junk.start()]
        c_letters, _ = letters(bare)
        end = slide(s_letters, c_letters[::-1][:ANCHOR + SLIDE], 0, backward=True)
        if end is None or end > len(s_idx):
            continue
        start = s_idx[end - 1] + 1
        nxt_at = end if end < len(s_idx) else None
        end = min(s_idx[nxt_at] if nxt_at is not None else len(stream), start + TAIL)
        seg = stream[start:end]
        nxt = out[i + 1]["tokens"][0] if i + 1 < len(out) else {1}
        enum = tail_enum(seg, nxt)
        if enum is None:
            continue
        if c["enums"] and enum not in c["enums"]:
            continue
        if kept and re.sub(r"\D", "", enum) != kept:
            continue
        # Without its "(" a bracket's ")" reads as 1 and "(" as 0: the other
        # digits must be the count's.
        if loose and loose.strip("01") and re.sub(r"\D", "", enum) not in loose:
            continue
        if len(c["tokens"]) == 1 and ftp.count(enum) > 15:
            continue
        # The count is filed in its parts. Dropping them (once a guard
        # against a hyphen read as a period) filed the bare letter total,
        # "14" for "(3.6.5)", and lost every word break.
        out[i] = dict(c, text=bare.rstrip(), enums={enum})
        notes.append(f"{c_number(c)} {direction}: enumeration ({enum}), the list read "
                     f"{sorted(c['enums']) or repr(text[-12:])}")


def fix_number(direction, parsed, stream, s_letters, s_idx, notes):
    """Step 3: a clue number read several ways."""
    out = parsed[direction]
    for i, c in enumerate(out):
        if len(c["tokens"][0]) == 1:
            continue
        c_letters, _ = letters(c["text"])
        pos = find_once(s_letters, c_letters[:ANCHOR])
        if len(c_letters) < ANCHOR or pos is None:
            continue
        m = re.search(r"(?<!\d)(\d{1,2})\s*[.,]?\s*$", stream[max(0, s_idx[pos] - 8):s_idx[pos]])
        if m and int(m.group(1)) in c["tokens"][0]:
            out[i] = dict(c, tokens=[{int(m.group(1))}] + c["tokens"][1:])
            notes.append(f"{int(m.group(1))} {direction}: number, the list read {sorted(c['tokens'][0])}")


def repair(parsed, stream):
    """(the parsed lists with what the other reading `stream` settles, [what changed])."""
    parsed = {d: [dict(c) for c in v] for d, v in parsed.items()}
    s_letters, s_idx = letters(stream)
    notes = []
    for direction in parsed:
        fix_number(direction, parsed, stream, s_letters, s_idx, notes)
        split_lost(direction, parsed, stream, s_letters, s_idx, notes)
        fix_enum(direction, parsed, stream, s_letters, s_idx, notes)
    return parsed, notes


# ------------------------------------------------- the repairs from one reading

def heads(c):
    """The one number a clue carries, or None."""
    return next(iter(c["tokens"][0])) if len(c["tokens"][0]) == 1 else None


def taken(parsed):
    """Every number a clue of either list names, its links too."""
    return {n for v in parsed.values() for c in v for t in c["tokens"] for n in t if len(t) == 1}




# ------------------------------------------- the slips of one clue's own text
#
# Where the OCR readings and the VLM disagreed on a clue (425 clues of the
# 10-16..18 "Update times-" commits, a vision reread of a filed text), most
# differences were a few kinds of slip a rule can undo from the clue alone:
# marks (punctuation.mend: a middle dot, a lone stop, ".." for an ellipsis),
# the count left in the text ("gossip 9."), another clue's text and count
# glued on in front ("... (4) 101 Our clue"), a drop capital or a bar read as
# a lone letter ("I Long pair of shorts?"), a word broken by a space
# ("de pressed"), a one-letter misread of a word the lexicon lacks ("mesal").
# mend_text() undoes them. Not rules: a lone quote mark (the VLM adds as many
# as it cuts), a hyphen against a dash, a figure for a letter ("11 pm" is
# print too), a word the OCR dropped.

#: Letters one OCR slip swaps for another (r/t/f, h/b, l/i, c/e, u/a/n, y/j ...).
CONFUSED = ("rtf", "hb", "lit", "ce", "uan", "oc", "yj", "sz", "nm", "dl", "gq", "vy")
SWAPS = {}
for _g in CONFUSED:
    for _a in _g:
        SWAPS.setdefault(_a, set()).update(_g.replace(_a, ""))
#: How often the clue corpus must print a word for a swap to read as it.
SWAP_USES = 20
#: A word a figure after it is the clue's reference to, not its count.
REFERS = frozenset("""see of no nos number page and or to by than from at with for in on as is are was
    between versus plus minus times""".split())
#: How often the clue corpus must print the word after a lone letter for the
#: letter to be a speck, not a word's start.
LEAD_USES = 10
#: A bar or a one read as a letter in front of a clue's first word.
LEAD_SPECKS = frozenset("I | ! 1 l".split())
#: A count and a clue number printed inside a text: "(4) 101 Next clue".
#: Words a clue's own first letter or number belongs to: "D Day", "1 Down's poet?"
#: (a cross-reference), "X Factor". lead_speck leaves these alone.
LEAD_KEEPS = frozenset("Day Hour Down Across Factor".split())
#: Phrases written in two words that mend_words must not join ("al fresco").
KEEP_APART = frozenset({"al fresco", "de rigueur"})
#: A word-piece that common, joined to a non-word piece to a word this many
#: times rarer, is two words ("to le", "for th", "be de"), not a broken one.
JOIN_RATIO = 60
#: Fewest uses a join of two pieces may have (rarer reads "dace" for "dance").
JOIN_USES = 7
#: Pieces that end a word on their own: a join with one is a split word.
JOIN_ENDS = frozenset({"ing", "ed"})
BLED_COUNT = re.compile(r"\(\s*(\d{1,2}(?:\s*[,\-]\s*\d{1,2})*)\s*\)\W{0,2}\s*\d{1,3}\s+(?=[A-Z])")


def lexicon():
    """(is_word, uses): the lexicon's test and the clue corpus's count of a
    word; loaded on first use (ocr_clues is heavy and imports this module's
    neighbours). The clue corpus (~3s to load) is read only when `uses` is
    first called, which the rules do only for a word the lexicon lacks, so
    a clue of lexicon words mends without it."""
    import ocr_clues

    def uses(w, nxt=None):
        """How often the corpus prints `w`, or `w` then `nxt`."""
        uni, pairs = ocr_clues.clue_lm()[:2]
        return uni.get(w.lower(), 0) if nxt is None else pairs.get(f"{w.lower()} {nxt.lower()}", 0)
    return ocr_clues.is_word, uses


SLIP_MIN_LETTERS = 5


def _fold(word):
    """A word's lower-case letters, digits and apostrophes with accents dropped ("curé" -> "cure")."""
    import unicodedata
    return re.sub(r"[^a-z0-9']", "", unicodedata.normalize("NFKD", word.lower()).encode("ascii", "ignore").decode())


def _unglue(mine, theirs):
    """`theirs` (a reading's words) with a word that is two adjacent words of the filed clue
    `mine` run together ("Springyour," for "Spring your") split back into them: a lost space
    is no other word's difference."""
    out = []
    for word in theirs:
        i = len(out)
        if i + 1 < len(mine) and _fold(word) and _fold(word) == _fold(mine[i]) + _fold(mine[i + 1]):
            out += mine[i:i + 2]
        else:
            out.append(word)
    return out


def slip_of(filed, reading, is_word=None):
    """Whether `reading` is the filed clue `filed` with one word's own slip: the same words, all
    alike (accents and marks aside) but one, which is a letter lost, added or changed in the
    reading ("fourish", "simp!y", "genera!", "ihe" for "flourish", "simply", "general", "the"),
    or a "1" for the "I" the clue opens with. The filed word must be a lexicon word of
    SLIP_MIN_LETTERS letters or more and the reading's one the lexicon lacks, so no real
    word's difference counts: only a reader's slip on a word the other reader got right.
    A reading with another word count, a figure, or two differing words is no slip of it."""
    if is_word is None:
        is_word = lexicon()[0]
    mine, theirs = (filed or "").split(), (reading or "").split()
    theirs = _unglue(mine, theirs)
    if len(mine) != len(theirs):
        return False
    odd = [(a, b) for a, b in zip(mine, theirs) if _fold(a) != _fold(b)]
    if not odd:
        return True  # the same words, only an accent apart
    if len(odd) != 1 or len(mine) < 3:
        return False
    a, b = odd[0]
    if a == "I" and b == "1" and mine[0] == a:
        return True
    a, b = _fold(a), re.sub(r"[^A-Za-z0-9']", "", b.lower())
    if len(a) < SLIP_MIN_LETTERS or not is_word(a) or not b or re.search(r"\d", b):
        return False
    import ocr_clues
    # known(), not is_word: a name the corpus's clues print ("Pyrrho") is no slip
    return not ocr_clues.known(b) and ocr_clues.within_one(a, b)


def count_digits(enum):
    """The figures of a printed count: "5,4" is [5, 4]."""
    return [int(n) for n in re.findall(r"\d+", enum or "")]


def trailing_count(text, enum, lights=None):
    """`text` without the figures of its own count left after its last
    words ("idle gossip 9.", "neat study 2-5."), when they are the clue's
    count as the light has it. Only figures equal to the enumeration's
    parts or its total, and not after a word a reference follows ("see 9",
    "zero and 5"), so a date or a number the clue is about is not cut."""
    m = re.search(r"(?<=[A-Za-z?!,;])\s+(\d{1,3}(?:\s?[-,.]\s?\d{1,2})*)[\s.,;:]*$", text)
    if not m or not enum:
        return text
    got = count_digits(m.group(1))
    want = count_digits(enum)
    # A multi-part count may have a figure misread ("2-5" for 2-3).
    slipped = len(got) == len(want) > 1 and sum(a != b for a, b in zip(got, want)) == 1
    # The count with a bar glued to it ("robbing 81", "language 151."). Three
    # figures are no clue number; two are one unless `lights` (the puzzle's
    # clue numbers) says no light has that number ("about 18" is a reference).
    figures = m.group(1)
    specked = clue_text.count_specked(figures, sum(want)) and (
        len(figures) == 3 or lights is not None and int(figures) not in lights)
    if len(figures) == 3 and figures.isdigit() and not specked:
        return text
    if got != want and got != [sum(want)] and not slipped and not specked:
        return text
    before = re.findall(r"[A-Za-z]+", text[:m.start()])
    if before and before[-1].lower() in REFERS:
        return text
    return text[:m.start()].rstrip()


def bled_count(text, enum):
    """`text` with the neighbouring clue cut off where a count and a clue
    number stand inside it ("... (4) 101 Our clue" or "Our clue (9) 171 Next
    clue"): the clue is the side whose count is the light's `enum`, else the
    text after the bracket, which the previous clue's count and number lead
    to."""
    m = BLED_COUNT.search(text or "")
    if not m or not enum or not text[:m.start()].strip() or not text[m.end():].strip():
        return text
    if clue_text.count_total(m.group(1)) == clue_text.count_total(enum):
        return text[:m.end()].rsplit("(", 1)[0].strip()
    return text[m.end():].strip()


def lead_speck(text, is_word, uses):
    """`text` without a lone letter in front of its first word that is no
    word: a drop capital printed beside the clue ("S Sound judgment") or a
    bar read as I ("I Long pair of shorts?"), when a common capitalised
    word follows."""
    m = re.match(r"([A-Z|!1l]) ([A-Z][a-z]{2,})\b", text)
    if not m:
        return text
    lead, word = m.groups()
    if word in LEAD_KEEPS:
        return text
    if lead == word[0] or (lead in LEAD_SPECKS and is_word(word.lower()) and uses(word) >= LEAD_USES):
        return text[2:]
    return text


def mend_words(text, is_word=None, uses=None):
    """`text` with the words a rule can mend from the lexicon alone: two
    pieces of a word broken by a space, joined ("de pressed", "drink ing"; a
    piece of two letters or more, one of them no word, the next pair not a
    better join); a word that neither the lexicon nor the clue corpus has,
    replaced by the one common word a single OCR swap (SWAPS) away ("mesal"
    for "metal")."""
    if is_word is None:
        is_word, uses = lexicon()
    words = text.split(" ")
    if sum(1 for w in words if len(w) == 1) > 3:
        return text  # letters spaced out: a puzzle set that way
    strip = lambda w: re.sub(r"^\W+|\W+$", "", w)

    def joins(a, b):
        x, y = strip(a), strip(b)
        if not (a == x and b.rstrip(".,;:!?") == y and x.isalpha() and y.isalpha() and x.islower() and y.islower()
                and len(x) >= 2 and len(y) >= 2 and is_word(x + y)):
            return False
        # One piece is no word. (Both words, "in doors", "spy catcher", "noble
        # men": a setter's run-together or cut word is print, left alone.)
        if is_word(x) and is_word(y):
            return False
        if x + " " + y in KEEP_APART:
            return False
        n = uses(x + y)
        if n < 1:
            return False
        if y in JOIN_ENDS:
            return True
        # A piece that is a common word beside a rare join is two words ("to le").
        word = x if is_word(x) else y
        return n >= JOIN_USES and uses(word) < n * JOIN_RATIO

    def inflected(w):
        # "haled": a lexicon word with an ending, not a misreading of "hated"
        return any(w.endswith(s) and is_word(w[:len(w) - len(s)] + e)
                   for s, e in (("ed", "e"), ("ed", ""), ("s", ""), ("es", ""), ("ing", ""), ("ing", "e")))

    out, i = [], 0
    while i < len(words):
        w = words[i]
        bare = strip(w)
        if i + 1 < len(words) and joins(w, words[i + 1]) and not (
                i + 2 < len(words) and joins(words[i + 1], words[i + 2])):
            out.append(w + words[i + 1])
            i += 2
            continue
        around = (words[i - 1][-1:] if i else " ") + (words[i + 1][:1] if i + 1 < len(words) else " ")
        if len(bare) >= 5 and w == bare and bare.isalpha() and bare.islower() and i and "-" not in around \
                and not is_word(bare) and uses(bare) == 0 and not inflected(bare) \
                and not (i and words[i - 1][-1:] in ".…"):
            alt = {bare[:k] + c + bare[k + 1:] for k, ch in enumerate(bare) for c in SWAPS.get(ch, ())}
            alt = {a for a in alt if is_word(a) and uses(a) >= SWAP_USES}
            out.append(alt.pop() if len(alt) == 1 else w)
        else:
            out.append(w)
        i += 1
    return " ".join(out)


def stub_before_word(text, is_word):
    """`text` without a piece of a word the OCR left in front of the whole
    word: a stub of two to four letters that is no word, then the lexicon word
    it begins ("a tem temporary measure", "nov novice"). The stub must be a
    lower-case run, the word at least three letters longer, and a French or
    other foreign word the lexicon lacks ("de deux") is not a word to keep."""
    words = text.split(" ")
    out = []
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        bare = nxt.rstrip(".,;:!?")
        if 2 <= len(w) <= 4 and w.isalpha() and w.islower() and not is_word(w) \
                and bare.isalpha() and bare.startswith(w) and len(bare) >= len(w) + 3 and is_word(bare):
            continue
        out.append(w)
    return " ".join(out)


def learned_mends(text, enum=None, is_word=None, lights=None):
    """`text` with only the mends learned from the rereads (tools/learn_postproc.py)
    made: a stray underscore, a figure speck before a small word, the count
    with a bar glued on, a stub of the next word. The rules mend_text applies
    among its others, alone, so tools/repair_fetched.py --learned can repair a
    held file with exactly what was measured."""
    t = clue_text.speck_figures(clue_text.stray_underscore(text or ""))
    t = trailing_count(t, enum, lights)
    return stub_before_word(t, is_word or lexicon()[0])


def leaked_number(text, lid):
    """`text`, one reading's clue for light `lid` ("22-down"), without the
    figures of a number the reader ran into it: its own number misread or
    doubled ("2 Foozle" for 22, "100 times it is almighty" for 18, "2 1 have
    left"). Only up to one figure more than the light's number, before a
    letter; a clue beginning with a cross-reference is left to its reading."""
    m = re.match(r"\s*(\d{1,3})[ .]?\s*(?=[A-Za-z1])", text or "")
    if not m or len(re.sub(r"\D", "", m.group(1))) > len(lid.split("-")[0]) + 1:
        return text
    return text[m.end():]


def mend_text(text, enum=None, is_word=None, uses=None, words=True, lights=None):
    """One clue's text with the slips of its own reading mended, each from
    the clue alone (see the section above). `enum`: the light's printed
    count, which tells the figures that are the count from those that are
    not; `words`: also the lexicon's mends (mend_words, lead_speck);
    `lights`: the puzzle's clue numbers, without which a count with a bar
    glued to it ("robbing 81") is cut only when it is three figures."""
    t = text or ""
    for _name, t in mend_steps(t, enum, is_word, uses, words, lights):
        pass
    return t


def mend_steps(text, enum=None, is_word=None, uses=None, words=True, lights=None, skip=()):
    """mend_text's rules one at a time: yields (rule name, text after it) for
    each, in the order they run. `skip`: rule names to leave out."""
    import punctuation
    if words and is_word is None:
        is_word, uses = lexicon()
    rules = [
        ("stray_underscore", lambda t: punctuation.mended(clue_text.stray_underscore(t))),
        # the clue's number glued on
        ("glued_number", lambda t: re.sub(r"^[0-9]{1,2}(?=[A-Z][a-z])", "", t)),
        ("speck_figures", clue_text.speck_figures),
        # A blank the clue prints as a run of dashes, set against a word with no space
        # ("in a——outworn", Gale 1955-11-22's 22 down): the dashes are the blank, not a mark in a word.
        ("dash_blank", lambda t: re.sub(r"(?<=[A-Za-z])(—{2,})(?=[A-Za-z])", r" \1 ", t)),
        ("spaces", lambda t: re.sub(r"\s{2,}", " ", t).strip()),
        ("bled_count", lambda t: bled_count(t, enum)),
        # the light's own count left in the text, a neighbour's scraps after it
        # ("experience (5). code."; tools/audit_updates.py's i:count-in-text)
        ("count_in_text", lambda t: clue_text.count_in_text(t, enum)),
        ("trailing_count", lambda t: trailing_count(t, enum, lights)),
        # "£" read as "E" before a sum ("with E25 left"; audit_updates' d:pound-as-E)
        ("pound_sign", clue_text.pound_sign),
    ]
    if words:
        rules += [
            # a scan's "a" read as "&" ("by & a weapon", "is & mile up")
            ("stray_ampersand", lambda t: clue_text.stray_ampersand(t, uses)),
            ("lead_speck", lambda t: lead_speck(t, is_word, uses)),
            ("stub_before_word", lambda t: stub_before_word(t, is_word)),
            ("mend_words", lambda t: mend_words(t, is_word, uses)),
        ]
    t = text or ""
    for name, rule in rules:
        if name not in skip:
            t = rule(t)
        yield name, t


def split_run_on(parsed):
    """`parsed` with a clue the OCR ran into the one before it split off: the
    printed numbers skip N (no clue carries it, which the grid rebuild
    refuses) and " N Capital" stands inside another clue's text. Three ways
    the join happens: that clue's count was lost ("... at one time 17 Go down
    ..."); the text before it is only a cross-reference whose count was never
    there ("(sce 22) 3 Supported", "(see lac.) 22 Vacillating"); or its count
    stands inside the text ("... chopper (7) 1] Those who've ..."), the
    clue's own count being the later clue's. Only a number the lists skip is
    split at, only above the clue's own and below the next clue's, so a list
    that was whole is not touched. Needs no second reading.
    (parsed, [what changed])."""
    parsed = {d: [dict(c) for c in v] for d, v in parsed.items()}
    notes = []
    while True:
        have = taken(parsed)
        missing = set(range(1, max(have) + 1)) - have if have else set()
        if not have:
            return parsed, notes
        for direction, out in parsed.items():
            for i, c in enumerate(out):
                own = heads(c)
                if own is None or not c["text"] or c["see"] is not None:
                    continue
                after = next((heads(x) for x in out[i + 1:] if heads(x) is not None), None)
                found = [(m, m.group(2), m.group(1), m.start(), m.end()) for m in clue_text.RUN_ON_NUMBER.finditer(c["text"])]
                # The next clue's number then the figure that is this clue's count
                # (never a number the list has, so only where it is missing).
                found += [(m, m.group(1), m.group(2), m.start(), m.end()) for m in clue_text.RUN_ON_STRAY.finditer(c["text"])
                          if int(m.group(1)) in missing]
                for m, num, count, m_start, m_end in found:
                    n = 11 if num[-1] == "]" else int(num)
                    first = c["text"][:m_start].strip()
                    see = clue_text.BARE_SEE.match(first)
                    if not (n in missing or (after is None and n not in have and n <= 36) or (after is not None and n in have and len(re.findall(clue_text.RUN_ON_NUMBER, c["text"])) == 1)) or n <= own or not first or (m_start < 3 and not see):
                        continue
                    if after is not None and n >= after:
                        continue  # a clue between two others numbers between them
                    later = {"tokens": [{n}], "text": c["text"][m_end:].strip(),
                             "enums": c["enums"], "see": None}
                    if see:
                        ref = str(clue_text.see_number(see.group(1)))
                        head = dict(c, text=f"See {ref}", enums=set(), see=int(ref))
                    else:
                        head = dict(c, text=first, enums={count.replace("\u2013", "-")} if count else set())
                    out[i:i + 1] = [head, later]
                    notes.append(f"{n} {direction}: split off {own} {direction}, which ran on into it")
                    break
                else:
                    continue
                break
            else:
                continue
            break
        else:
            return parsed, notes


def order(parsed):
    """`parsed` with its numbers put in order where their increase says how.
    Each list's numbers rise, so (1) a number out of place between two
    neighbours that bracket it is a misread of the one number in that gap
    that no clue carries; (2) a down list that starts with a rising run past
    the across list's last number and then falls back is the across list's
    tail, its columns read in the wrong order. (parsed, [what changed])."""
    parsed = {d: [dict(c) for c in v] for d, v in parsed.items()}
    notes = []
    for direction, rows in parsed.items():
        for i in range(1, len(rows) - 1):
            lo, x, hi = heads(rows[i - 1]), heads(rows[i]), heads(rows[i + 1])
            if None in (lo, x, hi) or lo >= hi or lo < x < hi:
                continue
            gap = [n for n in range(lo + 1, hi) if n not in taken(parsed)]
            if len(gap) == 1 and len(rows[i]["tokens"]) == 1:
                rows[i] = dict(rows[i], tokens=[{gap[0]}])
                notes.append(f"{gap[0]} {direction}: number, the list read {x}")
    a, d = parsed.get("across", []), parsed.get("down", [])
    nums = [heads(c) for c in d]
    if a and d and None not in nums and heads(a[-1]) is not None:
        k = next((j for j in range(1, len(nums)) if nums[j] <= nums[j - 1]), None)
        if k and nums[0] > heads(a[-1]) and nums[k] < nums[0] and all(
                nums[j] < nums[j + 1] for j in range(k, len(nums) - 1)):
            notes.append(f"{nums[0]}..{nums[k - 1]}: moved from down to across")
            parsed = dict(parsed, across=a + d[:k], down=d[k:])
    return parsed, notes


def from_rows(rows):
    """Parsed clues of light_spec rows ({"number": "23,4", "clue",
    "enumeration"}), each keeping its row."""
    out = []
    for r in rows:
        nums = r["number"].split(",")
        see = re.fullmatch(r"See (\d{1,2})", r["clue"] or "")
        out.append({"tokens": [{int(n)} if n.isdigit() else set() for n in nums],
                    "text": r["clue"] or "", "see": int(see.group(1)) if see else None,
                    "enums": {r["enumeration"]} if r["enumeration"] else set(), "row": r})
    return out


def to_rows(clues):
    """The rows of parsed clues from_rows made, a repaired clue's number, text
    and count replaced and its other keys (linkSides) kept."""
    rows = []
    for c in clues:
        r = c.get("row") or {"number": "", "clue": "", "enumeration": None}
        was = from_rows([r])[0] if r["number"] else None
        if was and (was["tokens"], was["text"], was["enums"]) == (c["tokens"], c["text"], c["enums"]):
            rows.append(r)
            continue
        number = ",".join(str(next(iter(t))) for t in c["tokens"]) if all(len(t) == 1 for t in c["tokens"]) else r["number"]
        rows.append({**r, "number": number, "clue": c["text"],
                     "enumeration": next(iter(c["enums"])) if len(c["enums"]) == 1 else None})
    return rows


def repair_rows(across, down):
    """(across rows, down rows) with split_run_on() and order() applied: the
    repairs of lists no second reading backs."""
    parsed = {"across": from_rows(across), "down": from_rows(down)}
    parsed, _ = split_run_on(parsed)
    parsed, _ = order(parsed)
    return to_rows(parsed["across"]), to_rows(parsed["down"])


def complete(parsed):
    """Whether a clue list pins every number and count down: each clue one
    number and (unless a "See") one enumeration, each list increasing, and
    together the two lists number 1..N without a gap."""
    for v in parsed.values():
        prev = 0
        for c in v:
            if len(c["tokens"][0]) != 1 or (c["see"] is None and len(c["enums"]) != 1):
                return False
            n = next(iter(c["tokens"][0]))
            if n <= prev:
                return False
            prev = n
    nums = numbers(parsed)
    return bool(nums) and nums == set(range(1, max(nums) + 1))


def repaired(parsed, readings):
    """(parsed, [what changed]) with the list repaired from each reading in
    `readings` (texts) in turn until it is complete()."""
    parsed, notes = split_run_on(parsed)
    for text in readings:
        if complete(parsed):
            break
        parsed, got = repair(parsed, text)
        notes += got
    return parsed, notes


def fill_missing_sizes(across, down, given):
    """A plain light whose count the OCR lost (No 164's 17ac) takes the length
    of the answer the next issue printed for it. `given`: {(number, direction):
    LETTERS}. A linked light's length is the group's to split, so it keeps None."""
    for d, lights in (("across", across), ("down", down)):
        for lg in lights:
            word = given.get((str(lg[0]), d))
            if lg[1] is None and word and not lg[2].startswith("linked"):
                lg[1] = len(word)
