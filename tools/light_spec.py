#!/usr/bin/env python3
"""Turn one OCR'd clue list into the light spec tools/reconstruct_grid.py wants.

This is the parser the 2026-09-18 Penguin sweep was run under, and it is
GATED: tools/test_acquire_book.sh reproduces the ten-puzzle vol-5 control and
fails if any grid, or any node count, moves. It is that gate, not this
docstring, that makes a change here safe -- the search is deterministic, so a
node count that moves means the spec moved, and a spec that moves has to be
argued for.

tools/reconstruct_grid.py's parse_lights reads a direction's list POSITIONALLY: the
lights must be given in printed (row-major) order, numbers strictly
increasing where known, None in place where the OCR lost one. v1 emitted a
linked field ("15,10") as two lights side by side in the direction the field
was printed under, which is wrong on both counts -- the second light is
printed at its own slot, which may be in the OTHER direction -- and so threw
"numbers must strictly increase" on every puzzle that had one.

Three generic rules replace the per-book hand patches:

1. LINKED FIELD. Only the first number is printed here; it keeps this slot.
   Each further number is placed at ITS own slot, found in this order:
     a. the "See N" redirect placeholder that carries that number, in
        whichever direction it was printed (this is what makes a
        cross-direction link -- a down clue "15,10" whose 10 is an across
        light -- come out right);
     b. failing that, by sorted insertion into the field's own direction.
        A slot reached this way has no printed entry of its own in what the
        OCR recovered, so its clue text is set to "See <leader>". That is
        not a guess at what the book said: it is the fixed convention every
        one of these books prints over a continuation, it is the exact text
        tools/normalise_linked_enumerations.py parses to tie the group back
        together, and it is what the corpus already stores (penguin5-3's
        17-down). The light carries synthesised=True so a caller can report
        which entries were written from convention rather than read.
   The enumeration's tokens are dealt out in the field's number order, the
   last number taking the sum of whatever tokens are left over; too few
   tokens means every light in the link gets an unknown length.

2. SWALLOWED CLUE. OCR that ran two clues together leaves the first clue's
   own enumeration embedded in the text, followed by the next clue's number
   and text ("...sniffer (8) _ 19 Northern seat"). Split there: the embedded
   enumeration is the first clue's length, and the leftover tokens of the
   entry's enumeration field -- those the embedded one does not account for
   -- are the swallowed clue's. No leftovers means its length is unknown.
   This recovers a light that would otherwise be missing entirely. A single
   split is a repair; an entry needing two or more is a smear, and the
   puzzle is excluded rather than guessed at.

4. WHAT THE BOOK PRINTED AT THIS SLOT rides along as a fourth element,
   {"clue": ..., "enumeration": ...}, so the caller can file the clue list
   without re-deriving which printed entry ended up at which slot -- the one
   thing rules 1 and 2 make impossible to work out from the outside, since
   they move entries between directions and split one entry into two. A slot
   with no printed clue of its own (rule 1b, a linked light whose partner
   printed no "See" placeholder) carries None, which is the caller's signal
   that this light cannot be filed with text.

3. IMPOSSIBLE NUMBER. A number that is 0, or that does not strictly increase
   on the previous one in its direction, is OCR dropping a digit. It becomes
   None -- an unknown number in a known slot, which the solver constrains
   structurally -- rather than a hand-guessed value.
"""
import re

SEE_RE = re.compile(r"^see\s+(\d+)\s*\.?$", re.IGNORECASE)
LEADING_NUM_RE = re.compile(r"^(\d{1,2})\b")
# THE PRINTED CLUE NUMBER IS NOT PART OF THE CLUE. The book prints "23" and
# then the clue; the scan sometimes puts a rule fragment, a leader dot or a
# stray dash between the two ("23 = The little devil...", "11 —Runcinate...",
# "| Took advantage..."), and the number then fails whatever pattern the
# segmenter strips a clean "23 " with, so it rides into the clue text and out
# the far end onto the page a solver reads. Measured on The Herald Crossword
# Book 2, where the numbers survived the scan: 125 of 1,276 clues, 9.8%.
#
# Two things keep this from eating a clue that really does start with a digit.
# The number must be followed by whitespace or by one of those separator
# glyphs, so "20th century" is untouched; and the digits must be the number
# this slot already has, so a number that is part of the clue has nothing to
# match. A bare glyph with no digits is stripped on its own — no clue starts
# with a pipe, and a pipe is what this scan makes of a 1.
GLYPHS = r"|!\[\]l—–‐~=_.,:;«»*•·+<>/\\-"
LEADING_LABEL_RE = re.compile(
    rf"^[\s{GLYPHS}]*"
    rf"(?:(?P<num>\d{{1,2}})(?=[\s{GLYPHS}])|(?P<pipe>[|!\[\]]))?"
    rf"[\s{GLYPHS}]*(?=[A-Za-z(“‘\"'])")


def _strip_label(clue, number):
    """The clue as the book set it, with the printed number and the scan's
    leftovers in front of it taken off. Returns the clue unchanged unless the
    leading digits ARE this light's number."""
    m = LEADING_LABEL_RE.match(clue)
    if not m or not m.end():
        return clue
    if m.group("num") is not None and (number is None or int(m.group("num")) != number):
        return clue
    end = m.end()
    # An ellipsis in front of a clue is the book's own punctuation — it is how
    # the second half of a clue split over two lights is printed ("...he was
    # officially secretary to Mary") — so the separator run stops before one
    # rather than swallowing it.
    dots = re.search(r"\.{2,}\s*$", clue[:end])
    if dots:
        end = dots.start()
    return clue[end:]
NUM_RE = re.compile(r"\d+")
# "<clue text> (8) <junk> 19 <next clue text>"
SWALLOW_RE = re.compile(
    r"^(?P<head>.{8,}?)\s*\(\s*(?P<enum>\d{1,2}(?:\s*[,\-–]\s*\d{1,2})*)\s*\)"
    r"\s*(?:\S{1,2}\s+)?(?P<num>\d{1,2})\s+(?P<tail>[^\s].{6,})$", re.S)
MAX_LIGHT_NUMBER = 60


def _tokens(enum):
    return [int(t) for t in NUM_RE.findall(enum)] if enum else []


def _num_of(field):
    if isinstance(field, int):
        return field
    if isinstance(field, str) and field.strip().isdigit():
        return int(field.strip())
    return None


def _split_swallowed(entries, notes, direction, damage):
    """Rule 2. Returns a new entry list with run-together clues separated."""
    out = []
    for e in entries:
        clue = (e.get("clue") or "").strip()
        m = SWALLOW_RE.match(clue)
        if not m:
            out.append(e)
            continue
        if SWALLOW_RE.match(m.group("tail").strip()):
            damage.append(f"{direction} entry '{clue[:50]}...' has three or "
                          f"more clues smeared into one; not repairable")
            out.append(e)
            continue
        embedded = _tokens(m.group("enum"))
        field = _tokens(e.get("enumeration"))
        leftover = list(field)
        for t in embedded:          # remove the embedded tokens once each
            if t in leftover:
                leftover.remove(t)
        first_num = _num_of(e.get("number"))
        second_num = int(m.group("num"))
        out.append({"number": e.get("number"),
                    "clue": m.group("head").strip(),
                    "enumeration": ",".join(str(t) for t in embedded)})
        out.append({"number": str(second_num),
                    "clue": m.group("tail").strip(),
                    "enumeration": ",".join(str(t) for t in leftover) or None})
        notes.append(
            f"{direction} {first_num}/{second_num}: OCR ran two clues into one "
            f"entry; split at the embedded enumeration "
            f"({m.group('enum')} -> {first_num}, leftover "
            f"{leftover or 'none, length unknown'} -> {second_num})")
    return out


def _redirect_slots(parsed):
    """{number: (direction, index)} for every unfilled 'See N' placeholder."""
    slots = {}
    for direction, lights in parsed.items():
        for i, lg in enumerate(lights):
            if lg[2] == "redirect" and lg[0] is not None:
                slots[lg[0]] = (direction, i)
    return slots


def _insert_sorted(lights, number, length, source, notes, direction, printed=None):
    lo, hi = 0, len(lights)
    for i, lg in enumerate(lights):
        if lg[0] is not None and lg[0] < number:
            lo = i + 1
        if lg[0] is not None and lg[0] > number:
            hi = i
            break
    at = max(lo, hi) if hi >= lo else lo
    if any(lights[i][0] is None for i in range(lo, at)):
        notes.append(f"{direction} {number}: linked light placed after the "
                     f"unnumbered light(s) it prints near; its exact slot "
                     f"among them is not recoverable from the OCR")
    lights.insert(at, [number, length, source, printed])


def _parse_direction(entries, notes, direction, damage):
    """First pass: one slot per printed entry, linked extras held back."""
    entries = _split_swallowed(entries, notes, direction, damage)
    lights = []
    pending = []          # (number, length) printed at some other slot
    last = None
    for e in entries:
        clue = (e.get("clue") or "").strip()
        field = e.get("number")
        enum = e.get("enumeration")

        m = SEE_RE.match(clue)
        if m:
            own = _num_of(field)
            lights.append([own, None, "redirect", {"clue": clue, "enumeration": enum}])
            if own is not None:
                last = own if last is None else max(last, own)
            continue

        if isinstance(field, str) and "," in field:
            nums = [int(x) for x in field.split(",") if x.strip().isdigit()]
            tok = _tokens(enum)
            if len(tok) >= len(nums) and nums:
                lengths = tok[:len(nums) - 1] + [sum(tok[len(nums) - 1:])]
            else:
                lengths = [None] * len(nums)
                notes.append(f"{direction} {nums}: linked field '{field}' "
                             f"enumeration '{enum}' has too few tokens to "
                             f"split; all lengths left unknown")
            if not nums:
                continue
            lights.append([nums[0], lengths[0], "linked",
                           {"clue": clue, "enumeration": enum}])
            last = nums[0] if last is None else max(last, nums[0])
            # The leader rides along so a slot filled by rule 1b can be
            # given the continuation text that points back at it.
            pending.extend((n, l, nums[0]) for n, l in zip(nums[1:], lengths[1:]))
            continue

        number = _num_of(field)
        if number is None and field is not None:
            notes.append(f"{direction}: number field {field!r} is not a "
                         f"number (OCR); slot kept, number unknown")
        if number is None:
            mm = LEADING_NUM_RE.match(clue)
            if mm and (last is None or int(mm.group(1)) > last):
                number = int(mm.group(1))
                notes.append(f"{direction} {number}: number recovered from a "
                             f"digit embedded in the OCR'd clue text")
        if number is not None and (number == 0 or number > MAX_LIGHT_NUMBER
                                   or (last is not None and number <= last)):
            notes.append(f"{direction}: number '{number}' cannot follow "
                         f"'{last}' in printed order (OCR dropped a digit); "
                         f"slot kept, number unknown")
            number = None
        tok = _tokens(enum)
        length = sum(tok) or None
        lights.append([number, length, "plain",
                       {"clue": _strip_label(clue, number), "enumeration": enum}])
        if number is not None:
            last = number
    return lights, pending


def build_spec(puzzle):
    """-> (across, down, notes, damage).

    Lights are [number|None, length|None, source, printed|None], where
    `printed` is {"clue", "enumeration"} exactly as the book set it at that
    slot -- see rule 4.
    """
    notes, damage = [], []
    parsed, pending = {}, {}
    for d in ("across", "down"):
        parsed[d], pending[d] = _parse_direction(puzzle.get(d, []), notes, d, damage)

    # Rule 1b/1a: place each linked extra at its own printed slot.
    slots = _redirect_slots(parsed)
    for d in ("across", "down"):
        for number, length, leader in pending[d]:
            hit = slots.pop(number, None)
            if hit is not None:
                hd, i = hit
                # The redirect's OWN printed text ("See 15") stays on this
                # slot: it is what the book prints here, and the leader keeps
                # the full clue at its own slot.
                parsed[hd][i] = [number, length, "linked"
                                 + ("" if hd == d else f" (cross-direction, printed under {d})"),
                                 parsed[hd][i][3]]
                if hd != d:
                    notes.append(f"{hd} {number}: light printed under {d} as "
                                 f"part of a linked clue but redirected from "
                                 f"{hd}'s own 'See' entry; filed as {hd}")
            else:
                _insert_sorted(parsed[d], number, length, "linked", notes, d,
                               {"clue": f"See {leader}", "enumeration": None,
                                "synthesised": True})
                notes.append(f"{d} {number}: no 'See {leader}' entry survived the "
                             f"OCR for this linked light, so its clue is written "
                             f"from the convention every continuation is printed "
                             f"under rather than read off the page")

    # An unfilled redirect is a real light whose clue is glued onto its
    # partner's plain entry: neither length can be trusted.
    for number, (hd, i) in slots.items():
        notes.append(f"{hd} {number}: 'See' redirect with no linked field to "
                     f"pair with; kept as a light of unknown length")
        for d in ("across", "down"):
            for lg in parsed[d]:
                if lg[0] == number and lg[2] != "redirect" and lg[1] is not None:
                    lg[1] = None
                    notes.append(f"{d} {number}: enumeration shared with that "
                                 f"redirect; length forced to unknown")

    for d in ("across", "down"):
        last = None
        for lg in parsed[d]:
            if lg[0] is None:
                continue
            if last is not None and lg[0] <= last:
                damage.append(f"{d} numbers print out of order ({lg[0]} after "
                              f"{last}) even after repair")
            last = lg[0]
    return parsed["across"], parsed["down"], notes, damage


def coverage(a, d):
    lights = a + d
    if not lights:
        return 0.0
    return sum(1 for lg in lights if lg[0] is not None) / len(lights)
