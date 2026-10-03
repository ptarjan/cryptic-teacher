"""A preamble's publishing boilerplate is not something a solver needs.

The note above the clues on a paper's page carries, besides a puzzle's
instructions, text about the paper itself: prize and postal-entry blurbs,
closing dates, charity cheque addresses, links to a print or PDF copy or to
clues held elsewhere, notes for the paper's own interactive grid, "not
available online", bonus-puzzle adverts, CMS identifiers and test strings.
None of it can be acted on from our page. strip() takes each such sentence (or
clause) out; what is left is the preamble, none left means no preamble. find()
is the write gate's test that no stored preamble still holds one
(puzzle_integrity.check_preamble).

A tribute, an anniversary, a title or a theme hint stays: it is the setter
talking to the solver, not the paper talking about its edition."""

import re

#: A sentence that is wholly the paper's: matched anywhere in the sentence.
SENTENCE = re.compile("|".join([
    # Prize, postal entry and closing date.
    r"\bbook tokens\b", r"\bcorrect solutions opened\b", r"\bpostmarked\b", r"\bPO Box\b",
    r"\bwinners will be (?:published|announced)\b", r"\bextra time for solvers\b",
    r"\bDeadline for (?:this|the) puzzle\b", r"\bclosing date\b",
    # A charity appeal's cheque and address.
    r"\bplease send a cheque\b", r"\bcheques?\b[^.]*\b(?:payable|made out)\b",
    # A link to the print/PDF copy or to clues held elsewhere.
    r"\bclick(?:ing)? here\b", r"\b(?:found|available|clues) here\b", r"\bSee here\b",
    r"\bfollow(?:ing)? (?:this|the) link\b", r"\bto go back to the (?:prize )?crossword\b", r"\bthis pdf\b", r"\bpdf of\b",
    r"\bprin?table\b", r"\bpritable\b", r"^For the annotated solution\b",
    # The paper's own interactive grid.
    r"\binteractive grid\b", r"\bclick on the grid\b", r"\bReveal All\W{1,3}button\b",
    # Not on the web page, or a bonus in the print edition.
    r"\bcannot be (?:posted|published) online\b", r"\bnot available online\b",
    r"\bbonus (?:jumbo|puzzle)\b",
    # A CMS test string.
    r"\btest instructions\b",
    # What a removed link leaves behind: a bare "And".
    r"^(?:And|Or)\W*$",
]), re.IGNORECASE)

#: A clause that is the paper's inside a sentence that is not.
CLAUSE = re.compile(
    r",\s*(?:the second part of )?which (?:can|may) be found here(?:,(?= and))?"
    r"|\b(?:To see|For) the clues(?: (?:for|to) this crossword)?,? please click here\b\.?\s*"
    r"|\bgdn\.[\w.]+(?:\(\d*\))?", re.IGNORECASE)


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s*(?=[A-Z])", text) if s.strip()]


def find(preamble):
    """The boilerplate a preamble still holds, as text; [] when it has none."""
    text = preamble or ""
    found = [m.group(0) for m in CLAUSE.finditer(text)]
    found += [s.strip() for s in _sentences(CLAUSE.sub("", text)) if SENTENCE.search(s.strip())]
    return found


def strip(preamble):
    """The preamble without its boilerplate, or None when nothing is left."""
    if not preamble or not find(preamble):
        return preamble
    text = CLAUSE.sub("", preamble)
    kept = [s.strip() for s in _sentences(text) if not SENTENCE.search(s.strip())]
    rest = " ".join(" ".join(kept).split())
    return rest if re.search(r"\w\w", rest) else None


def apply(puzzle):
    """Take the boilerplate out of `puzzle`'s preamble (in place); the
    preamble goes when nothing is left."""
    text = puzzle.get("preamble")
    rest = strip(text)
    if rest == text:
        return
    if rest:
        puzzle["preamble"] = rest
    else:
        puzzle.pop("preamble", None)
