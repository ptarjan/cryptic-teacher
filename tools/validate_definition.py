"""Definition checks of validate_annotations.py: separators, definition fit, reuse, and a definition that is also fodder.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import re
import definitions
from annotation import explanation

from validate_base import types_of
from validate_walkthrough import FILLER_WORDS

# `definitionFit` — one sentence on why the ANSWER means the DEFINITION — is
# required. Puzzles annotated before it existed lack it; see the ratchet at the
# bottom of this file for how they are grandfathered without letting a new
# puzzle skip it.


# The paper's own word divisions, as the source filed them: clue.separators
# lists each mark with the letter count it follows, so a clue printed (5,1,1)
# arrives as [{"at": 5, "mark": ","}, {"at": 6, "mark": ","}]. Tracked data, not a second parse of the
# enumeration in brackets — app.js already parses that, and one rule spelled
# twice is a rule that drifts.
#
# Only one direction is an error. An answer written solid against a divided
# enumeration is ordinary: the paper prints I.C.I. as (1,1,1) and we store ICI.
# An answer that breaks where the paper does not is our own spelling, and the
# letter strip draws its gaps over the wrong squares.
def check_answer_matches_separators(tag, ann, entry, errors):
    seps = entry["clue"].get("separators") or []
    answer = ann.get("answer")
    if not seps or not answer:
        return
    # A linked group files the whole group's answer on its leading light while
    # the separators describe that light alone, so the two are not comparable.
    if entry.get("group"):
        return
    # An apostrophe occupies no square and starts no new word, so it comes out
    # of both sides: DON'T is one four-letter word either way.
    breaks, letters = [], 0
    for ch in answer:
        if ch in "'\u2019":
            continue
        if ch in " -\u2013":
            breaks.append(letters)
        else:
            letters += 1
    if not breaks:
        return
    # A separator at the light's own end (or past it) is the paper running the
    # answer on into another light (cryptic-21625 6D DANCE TO THE MUSIC, printed
    # "5,2,3,5,2,4" for A DANCE TO THE MUSIC OF TIME): no gap inside this
    # answer can stand for it.
    filed = sorted({s["at"] for s in seps if s["mark"] not in ("'", "\u2019") and 0 < s["at"] < letters})
    if breaks != filed:
        errors.append(
            f"{tag}: answer {answer!r} breaks after {breaks}, but the paper "
            f"divides this light after {filed} — respell the answer so the "
            f"letter strip puts its gaps where the enumeration does")


DEFINITION_FIT_MAX = 30
DEFINITION_FIT_HOW = (
    "Name the relation rather than asserting it: a plain synonym, a definition by "
    "example, a crossword-only sense, a regional use, an idiom. Never read the "
    "definition back — 'army ants move in a crawling column, and crawler also "
    "carries the grovelling sense the surface points at', not 'an army ant is a "
    "crawler'. A double definition covers both senses; an &lit says why the whole "
    "clue reads straight")


def check_definition_fit(tag, ann, errors, warnings):
    """Why the answer MEANS the definition — the non-mechanical half of a clue.

    Two failure modes worth catching mechanically. Thin: a handful of words that
    assert rather than explain. Backwards: the definition read out again with the
    answer swapped in ("an army ant is a crawler"), which looks like an
    explanation and teaches nothing — detectable because it contains no content
    word that isn't already in the definition or the answer. One such word is
    enough: "Cardiff is the capital city of Wales" for "City" teaches, and
    asking for more only buys padding.
    """
    fit = explanation(ann).get("definitionFit")
    if fit is None:
        msg = (f"{tag}: no explanation.definitionFit — say in one sentence (up to {DEFINITION_FIT_MAX} words) why the "
               f"answer means the definition. {DEFINITION_FIT_HOW}")
        warnings.append(msg)
        return
    fit = str(fit).strip()
    if len(fit) < 25:
        errors.append(f"{tag}: definitionFit {fit!r} is too thin. {DEFINITION_FIT_HOW}")
        return
    if len(fit.split()) > DEFINITION_FIT_MAX:
        warnings.append(f"{tag}: definitionFit is {len(fit.split())} words — "
                        f"{DEFINITION_FIT_MAX} max")
    known = set(re.findall(r"[a-z']+", " ".join(definitions.texts(ann)).lower()))
    known |= set(re.findall(r"[a-z']+", (ann.get("answer") or "").lower()))
    fresh = [w for w in re.findall(r"[a-z']+", fit.lower())
             if w not in known and w not in FILLER_WORDS and len(w) > 2]
    if not fresh:
        errors.append(f"{tag}: definitionFit {fit!r} just restates the definition with the "
                      f"answer in it. {DEFINITION_FIT_HOW}")


# Function words are shared by every English phrase; an overlap on "of" or "in"
# between a definition and a block is a coincidence, not a reused definition.
DEFINITION_STOPWORDS = frozenset(
    "a an the of in on at to for and or is are be by with from as that it its "
    "this his her their s no not".split())

# Real setters do sometimes make the definition word earn its keep twice — "Blunt?
# Use 'blunt' to anagram this answer", "Nobody drunk now nobody drinks!". Across
# the 671 annotated clues in this repo that happens 4 times, never twice in one
# puzzle. So one is a device and a handful is a broken annotation run.
MAX_DEFINITION_REUSE = 3

# The two halves of a cryptic sit side by side and do not overlap: &lit means the
# whole clue is both at once, a double definition is two definitions and no
# wordplay, a cryptic definition is no wordplay at all.
DEFINITION_REUSE_EXEMPT = ("and_lit", "double_definition", "cryptic_definition")


#: Words too common to say two definitions are the same stretch of the clue.
LINKING_WORDS = {"a", "an", "the", "of", "to", "in", "for", "and", "or", "is", "s", "it", "on", "as"}


def _fragment_clear_of_definitions(entry, ann, frag):
    """True when every place `frag` sits in the clue lies outside every placed
    definition: sharing a word (azed-2693 30A "Small amount of money, very
    small, last in purse": def "Small amount of money", block "very small") is
    a coincidence of vocabulary, not one stretch of clue doing both jobs. False
    when the clue, the fragment or a definition's `at` cannot be pinned down."""
    clue = ((entry.get("clue") or {}).get("text") or "")
    spans = [(d["at"], d["at"] + len(d["text"])) for d in ann.get("definitions") or []
             if isinstance(d, dict) and isinstance(d.get("at"), int) and d.get("text")]
    if not clue or not frag or not spans or len(spans) != len(ann.get("definitions") or []):
        return False
    low, f, i, found = clue.lower(), frag.lower(), 0, False
    while (i := low.find(f, i)) >= 0:
        found = True
        if any(i < b and a < i + len(f) for a, b in spans):
            return False
        i += 1
    return found


def check_definition_not_fodder(entries, errors, warnings):
    """The definition's words may not also be the wordplay's letters.

    A clue is two pieces — definition, optional joinery, wordplay — so a block
    that yields letters out of words the definition has already claimed is the
    annotation eating its own tail. The commonest form is a block whose fragment
    IS the definition and whose `gives` is the whole answer: "Hard rock" > HORSE.
    That says the answer is the answer, and every existing check passes it, since
    the letters concatenate and the substrings are verbatim.

    A model that cannot solve the clue can still satisfy a consistency checker:
    wrong definitions dressed up in blocks that restate them pass every other
    check, so consistency is not the bar; this is.

    CALIBRATION (all 671 annotated clues): 4 warn, in 4 different puzzles, all
    genuine setter devices where the definition word is deliberately reused as
    fodder. None reach the cap; a run that never solved its clues hits it in one
    puzzle.
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann:
            continue
        if any(x in types_of(ann) for x in DEFINITION_REUSE_EXEMPT):
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        dw = set(re.findall(r"[a-z]+", " ".join(definitions.texts(ann)).lower()))
        dw -= DEFINITION_STOPWORDS
        if not dw:
            continue
        for b in ann.get("blocks", []):
            # An empty `gives` is surface padding, which claims no letters and so
            # cannot be stealing any from the definition.
            if not re.sub(r"[^A-Za-z]", "", str(b.get("gives") or "")):
                continue
            frag = b.get("clueFragment") or ""
            shared = dw & set(re.findall(r"[a-z]+", frag.lower()))
            if shared and _fragment_clear_of_definitions(e, ann, frag):
                continue
            if shared:
                hits.append(tag)
                warnings.append(
                    f"{tag}: block {frag!r} gives {b.get('gives')!r} out of "
                    f"{sorted(shared)}, which the definition {' / '.join(definitions.texts(ann))!r} "
                    f"has already claimed. A clue is definition + wordplay, not one "
                    f"phrase doing both — unless the setter reuses the word on "
                    f"purpose, this parse is faked out of the definition. If the "
                    f"reuse is the setter's, leave it: this is a warning, up to "
                    f"{MAX_DEFINITION_REUSE} a puzzle pass, and nothing marks one as meant")
                break
    if len(hits) > MAX_DEFINITION_REUSE:
        errors.append(
            f"puzzle: {len(hits)} clues ({', '.join(hits)}) build wordplay out of "
            f"their own definition — at most {MAX_DEFINITION_REUSE} allowed. One is a "
            f"setter's device; this many means the clues were not solved, only "
            f"described. Re-annotate rather than patch")