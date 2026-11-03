"""Indicator checks of validate_annotations.py: adjacency, fodder, early rungs, block notes, the indicator table.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import collections
import re
import definitions
from annotation import whole_anagram
from find_answer_leaks import _run, named, pieces_of, says

from validate_base import TYPE_NAMES, types_of, indicator_texts, letters, words_of
from validate_link import link_vocabulary
from validate_definition import DEFINITION_STOPWORDS

# What may stand between an anagram indicator and its fodder is the link-word
# vocabulary: `Naples WAS flattened`, `A grub seen wriggling`, `Latin song IN
# parts swapped`, `lie WHEN disturbed`. A content word between them is not.


def _letter_offsets(clue):
    """The clue's letters, plus the index in `clue` each one came from."""
    idx = [i for i, ch in enumerate(clue) if ch.isalpha()]
    return "".join(clue[i].upper() for i in idx), idx


def _fodder_spans(clue, fodder, blocks):
    """Where in the clue text the anagram fodder sits, as (start, end) offsets.

    Two ways to find it, and every candidate either way is returned, because the
    adjacency check passes if ANY reading of the clue is clean:

    1. verbatim: the fodder's letters, in order, inside the clue's letters —
       then snapped outwards to whole words. Snapping is what makes `Bedsore
       very` work for fodder BEDSORE V (the letters stop mid-`very`); it can
       only widen a span, so it can only make the check more lenient.
    2. from the blocks that feed the anagram, when together they account for all
       of the fodder — the case where the fodder is scattered (`B BEAT BLUE`).
    """
    from collections import Counter
    spans = []
    letts, idx = _letter_offsets(clue)
    f = letters(fodder)
    if f:
        for m in re.finditer("(?=" + re.escape(f) + ")", letts):
            s, e = idx[m.start()], idx[m.start() + len(f) - 1] + 1
            while s > 0 and clue[s - 1].isalpha():
                s -= 1
            while e < len(clue) and clue[e].isalpha():
                e += 1
            spans.append((s, e))
    parts, total = [], ""
    for b in blocks:
        g, frag = letters(b.get("gives")), b.get("clueFragment")
        if not g or not frag or frag not in clue:
            continue
        if not (Counter(g) - Counter(f)):        # this block feeds the anagram
            i = clue.find(frag)
            parts.append((i, i + len(frag)))
            total += g
    if parts and sorted(total) == sorted(f):
        spans.append((min(s for s, _ in parts), max(e for _, e in parts)))
    return spans


def check_indicator_adjacency(tag, ann, clue, errors, warnings):
    """An anagram indicator has to be next to the fodder it operates on.

    `ground` cannot reach back over `lives on the` to shuffle `The oyster`. Only
    link words may stand between the two (link_vocabulary()) — plus the
    definition, which really does sometimes sit in the gap, and any span the
    annotation has already confessed to as padding (a block with an empty
    `gives`, itself an ERROR in an authored puzzle).

    This is a soundness rule, not a style preference: it does not contradict
    AUTHORING.md's withdrawn advice against placing the indicator next to the
    fodder (88.9% of published anagrams do exactly that).

    CALIBRATION (unscoped, 74,474 annotated published clues):
    10,201 anagram clues with an indicator; 9,914 have a locatable fodder span
    and 24 of those are flagged (0.24%), each with a content word in the gap
    that reads as an annotation slip (`ecstasy`, `oxygen`, `daughter`).
    287 are unlocatable because their fodder is built by deleting letters;
    they are skipped, with a warning when the clue is ours."""
    fodder = whole_anagram(ann)
    if not fodder:
        return
    spans = _fodder_spans(clue, fodder, ann.get("blocks", []))
    inds = [(clue.find(i), clue.find(i) + len(i), i) for i in indicator_texts(ann, "anagram")
            if i in clue]
    if not inds:
        return
    if not spans:
        warnings.append(
            f"{tag}: cannot locate the anagram fodder in the clue text, so adjacency is "
            f"unchecked — normal when letters are deleted to build the fodder, but in a "
            f"clue we wrote, check by eye that the indicator touches it")
        return
    allowed = set(link_vocabulary())
    for src in definitions.texts(ann):
        allowed |= set(words_of(src))
    for b in ann.get("blocks", []):
        if not str(b.get("gives") or "").strip():
            allowed |= set(words_of(b.get("clueFragment")))
    best = None
    for fs, fe in spans:
        for istart, iend, ind in inds:
            gap = clue[fe:istart] if istart >= fe else clue[iend:fs] if iend <= fs else ""
            bad = [w for w in words_of(gap) if w not in allowed]
            if not bad:
                return
            if best is None or len(bad) < len(best[1]):
                best = (ind, bad)
    errors.append(
        f"{tag}: anagram indicator {best[0]!r} is separated from its fodder by "
        f"{', '.join(best[1])} — an indicator only operates on what it stands next to. "
        f"Move it against the fodder, or cut the words in between (AUTHORING.md, "
        f"'An indicator operates on what it touches')")


def check_anagram_fodder_from_clue(tag, ann, clue, authored, errors, warnings):
    """Every anagram's fodder has to come from the clue: its letters are
    drawn from the wordplay's words (the clue less its definition, unless
    the definition is the whole clue) and the letters its blocks give.
    Recording GROAN as the fodder of a clue that says "grain" passed every
    other check. For a clue we wrote, the fodder must also be found whole,
    in order or from its blocks (_fodder_spans), since we chose the words.

    CALIBRATION (14,898 anagram steps in published puzzles):
    11 flagged, each a definition sharing words with the fodder (semi-&lit
    typed as a plain anagram), so published clues get a warning."""
    text = clue
    if "and_lit" not in types_of(ann):
        for d in definitions.texts(ann):
            if d and d in text and letters(d) != letters(text):
                text = text.replace(d, " ", 1)
    pool = collections.Counter(letters(text))
    for b in ann.get("blocks") or []:
        if letters(b.get("gives")) != letters(b.get("clueFragment")):
            pool += collections.Counter(letters(b.get("gives")))
    for step in (ann.get("assembly") or {}).get("anagrams") or []:
        fodder = step.get("fodder") or ""
        extra = collections.Counter(letters(fodder)) - pool
        if extra:
            (errors if authored else warnings).append(
                f"{tag}: anagram fodder {fodder!r} has {''.join(sorted(extra.elements()))} "
                f"that neither the wordplay's words nor its blocks supply. The fodder is "
                f"the clue's own letters: copy them from the words the indicator works on")
        elif authored and not _fodder_spans(clue, fodder, ann.get("blocks", [])):
            errors.append(f"{tag}: anagram fodder {fodder!r} is not in the clue in order, nor made "
                          f"of its blocks. In a clue we wrote the fodder is words we chose: "
                          f"print them")


def check_indicator_outside_fodder(tag, ann, clue, errors):
    """An anagram indicator cannot be made of letters the anagram eats.

    The instruction and the material are two different jobs, and one word cannot
    hold both: if `spin` is inside PAID TO SPIN then its letters are already
    spoken for, and whatever tells you to shuffle them has to be some other word.
    Easy to get backwards — `spin`, `cooked`,
    `broken`, `wild` all read as instructions wherever they appear, so a reader
    (or a model annotating in bulk) will happily nominate one that is really
    fodder.

    Adjacency alone cannot catch this: check_indicator_adjacency measures the gap
    BETWEEN indicator and fodder, and an indicator sitting inside the fodder has
    no gap at all, so it scores as perfectly placed.

    Only flagged when every locatable reading of the fodder swallows the
    indicator, matching the adjacency check's rule that any clean reading wins.

    CALIBRATION (all 116 annotations carrying a fodder when written): 0 flagged.
    A guard against a future annotation, not a description of a present one.
    """
    fodder = whole_anagram(ann)
    if not fodder:
        return
    spans = _fodder_spans(clue, fodder, ann.get("blocks", []))
    if not spans:
        return
    for ind in indicator_texts(ann, "anagram"):
        i = clue.find(ind)
        if i < 0:
            continue
        if all(i < fe and i + len(ind) > fs for fs, fe in spans):
            errors.append(
                f"{tag}: anagram indicator {ind!r} sits inside the fodder "
                f"{fodder!r} — its letters are already being "
                f"shuffled, so it cannot also be the instruction to shuffle them. "
                f"The indicator is some other word in the clue.")

# An early rung must not contain the answer. The hint ladder is a ladder: the
# spotting rungs name the indicators, the definition and the family, and only the
# building blocks and the walkthrough are entitled to spell the answer out. A
# field rendered above that line which names the answer collapses the ladder —
# the solver pays a hint and is handed the solve.
#
# A definition's `note` exists to explain why the definition does not agree with
# the ANSWER, so it is written about the answer and always will be; that is why
# it is shown on the walkthrough rung, not the definition rung.
#
# So this guards the fields that stay early, where naming the answer is never
# necessary and never fair. Matched with `says`, the same word-run matcher
# check_block_notes_dont_name_the_answer uses: the answer's letters have to line
# up with whole words of the field, so "trump cards" is still caught by
# TRUMPCARDS and a stray hyphen or apostrophe still cannot slip it through.
#
# A bare substring test would find a short answer inside an unrelated longer
# word, which is why `says` is used. A field that quotes clue words which
# already spell the answer is not a leak: in everyman-4121 1A, "'Not fully
# overhead?' I'm never overhead!", RHEA hides in ove(RHEA)d and the setter uses
# that word in BOTH halves, so every possible definition span contains the
# answer's letters. Those letters are the clue's own, on screen from the start;
# a leak is text the annotator WROTE that the clue does not say.
EARLY_RUNG_FIELDS = ("definitions", "indicators", "linkWords")


def clue_words_no_block_covers(ann, clue):
    """The clue's words left once its definitions, indicators, link words and
    block fragments are taken out (each once), in clue order."""
    rest = clue or ""
    spans = [d.get("text") for d in ann.get("definitions") or [] if isinstance(d, dict)]
    spans += list(indicator_texts(ann)) + list(ann.get("linkWords") or [])
    spans += [b.get("clueFragment") for b in ann.get("blocks") or []]
    for s in sorted((s for s in spans if s), key=len, reverse=True):
        rest = rest.replace(s, " " * len(s), 1)
    return re.findall(r"[\w'’]+", rest)


def check_no_answer_in_early_rungs(tag, ann, clue, errors, warnings):
    """No field shown before the building blocks may spell out the answer,
    unless the field quotes clue words that already do: a given entry (Listener
    29 24A, clue "MEAE") prints its answer as its clue."""
    ans = re.sub(r"[^a-z]", "", str(ann.get("answer") or "").lower())
    if len(ans) < 4:
        return  # too short to distinguish a leak from a coincidence
    on_screen = says(clue or "", ans)
    for field in EARLY_RUNG_FIELDS:
        val = ann.get(field)
        if not val:
            continue
        if field == "indicators":
            parts = [p for i in val if isinstance(i, dict)
                     for p in (i.get("text"), i.get("note")) if p]
        elif field == "definitions":
            parts = [d.get("text") for d in val if isinstance(d, dict) and d.get("text")]
        else:
            parts = val if isinstance(val, list) else [val]
        for part in parts:
            if says(part, ans) and not (on_screen and str(part).lower() in (clue or "").lower()):
                errors.append(
                    f"{tag}: {field} {part!r} contains the answer — it is shown "
                    f"before the building blocks, so it hands over the solve for "
                    f"the price of a hint. Say it in the walkthrough instead.")

def check_block_notes_dont_name_the_answer(tag, ann, errors, warnings, lights=()):
    """The building blocks are a rung early too — the walkthrough is the reveal.

    The check above stops at the fields shown BEFORE the blocks. The blocks rung
    is not where the answer lands: the walkthrough is, and a learner buying the
    blocks has deliberately not bought the solve. app.js suppresses a `gives` that equals the answer, so only the
    prose can still leak.

    `lights` are the solutions of a linked answer's lights, and each is an
    answer in the grid: "to prime a gun is to make it ready" hands over 1A of
    PRIME MINISTER as surely as naming the whole phrase would.
    """
    answer = ann.get("answer")
    pieces = pieces_of(ann)
    for block in ann.get("blocks") or []:
        name = named(block.get("note"), answer, lights, pieces)
        if name is None:
            continue
        what = ("the answer" if name == answer
                else f"{name!r}, the answer to one of this clue's linked lights")
        note = str(block.get("note"))
        span = _run(note, name, pieces)
        words = f" (the words {note[span[0]:span[1]]!r})" if span else ""
        errors.append(
            f"{tag}: block note {block.get('note')!r} names {what}{words}, and "
            f"the blocks are the rung before the walkthrough. Write the note "
            f"about the fragment — what it means, where its letters sit, "
            f"which convention is in play — and let the walkthrough spell it.")


# An indicator rung that names the words and not the reason is not worth paying
# for. The general sentence about what an anagram indicator does is the same on
# every clue in the corpus; the reason THIS word is one is the only part that
# teaches anything ("Fixer-up ran over to stable? No": "stable? No" is an
# anagram signal because unstable means not fixed in place).
#
# A missing note and a missing `for` are grandfathered the same way as
# definitionFit, through the ratchet at the bottom of this file: stored puzzles
# may lack them up to their recorded allowance, and a newly annotated puzzle has
# none. Both warnings count clues, not indicators, except "has no note", which
# names each unexplained indicator on a clue whose other indicators have notes.


INDICATOR_NOTE_HOW = (
    "One sentence saying which sense of THIS word carries the instruction: "
    "\"'stable? No' means unstable, and something unstable will not stay in the "
    "order it is given\", not \"'stable? No' is the anagram indicator\"")

INDICATOR_KEYS = {"text", "for", "note"}


def check_indicators(tag, ann, clue, errors, warnings):
    """Each indicator is {"text", "for", "note"}: the clue words, the type they
    signal, and one sentence on why THIS word signals it. A text is listed at
    most as often as the clue prints it."""
    inds = ann.get("indicators")
    if inds is None:
        return
    if not isinstance(inds, list):
        errors.append(f"{tag}: indicators must be a list of "
                      f"{{\"text\", \"for\", \"note\"}} objects")
        return
    own = types_of(ann)
    no_for, no_note, texts = [], [], []
    for ind in inds:
        if not isinstance(ind, dict) or not isinstance(ind.get("text"), str) \
                or not ind["text"].strip():
            errors.append(f"{tag}: indicator {ind!r} must be an object with a "
                          f"non-empty `text`: {{\"text\": \"almost\", \"for\": "
                          f"\"deletion\", \"note\": \"...\"}}")
            continue
        text = ind["text"]
        extra = sorted(set(ind) - INDICATOR_KEYS)
        if extra:
            errors.append(f"{tag}: indicator {text!r} has {extra}; the keys are "
                          f"text, for and note")
        if texts.count(text) >= clue.count(text):
            errors.append(f"{tag}: indicator {text!r} is listed more often than "
                          f"the clue prints it")
        texts.append(text)
        kind = ind.get("for")
        if kind is None:
            no_for.append(text)
        elif kind not in TYPE_NAMES:
            errors.append(f"{tag}: indicator {text!r} is for {kind!r}, which is not a "
                          f"type name ({', '.join(TYPE_NAMES)})")
        elif kind not in own:
            errors.append(f"{tag}: indicator {text!r} is for {kind!r}, but the clue's "
                          f"type is {own!r}; `for` names one of the clue's own types")
        note = ind.get("note")
        if note is None:
            no_note.append(text)
            continue
        note = str(note).strip()
        if len(note) < 25:
            errors.append(f"{tag}: note on indicator {text!r} is {note!r} — too thin "
                          f"to teach. {INDICATOR_NOTE_HOW}")
        # "'shuffled' tells you to shuffle" is the failure this catches: a note
        # made only of words already in the indicator has restated it.
        elif not (set(words_of(note)) - set(words_of(text)) - DEFINITION_STOPWORDS):
            errors.append(f"{tag}: note on indicator {text!r} only says {text!r} "
                          f"again. {INDICATOR_NOTE_HOW}")
    if no_for:
        warnings.append(f"{tag}: indicator(s) {no_for!r} lack `for` — name the type "
                        f"each one signals, one of the clue's own {own!r}")
    where = (" Write it under the clue's `notes`, keyed by those clue words: "
             "{\"after\": \"...\"}; a charade's `+<after>` and a container's `ins<in>` link word "
             "are indicators too, and its note says which piece goes where")
    if no_note and len(no_note) == len(texts):
        warnings.append(f"{tag}: no indicator notes — give every indicator a `note`. "
                        f"{INDICATOR_NOTE_HOW}.{where}")
    else:
        for text in no_note:
            warnings.append(f"{tag}: indicator {text!r} has no note — every indicator "
                            f"gets one. {INDICATOR_NOTE_HOW}.{where}")