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


ENUM_SEG = re.compile(r"[\s.?!;:'\"]*[(\[{]?\s*(\d{1,2}(?:(?:\s*[,.\-]\s*|\s+)\d{1,2})*)\s*[)\]}]?[\s.,;:]*")


def tail_enum(seg, nxt):
    """The enumeration printed in `seg` (the text between a clue's last word
    and the next clue's first), less the next clue's number `nxt` (its
    readings), or None."""
    m = re.search(r"(\d{1,2})\s*[.,]?\s*$", seg)
    if m and int(m.group(1)) in nxt and re.search(r"\d", seg[:m.start()]):
        seg = seg[:m.start()]
    m = ENUM_SEG.fullmatch(seg)
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
    for m in re.finditer(r"(?<![\w(,.\-])(\d{1,2})\s*[.,]?\s*(?=[A-Z])", stream):
        n = int(m.group(1))
        if n > top or any(c["tokens"][0] == {n} for c in out):
            continue
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
    notes = []
    for text in readings:
        if complete(parsed):
            break
        parsed, got = repair(parsed, text)
        notes += got
    return parsed, notes
