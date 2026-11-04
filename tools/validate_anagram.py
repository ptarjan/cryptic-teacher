"""Anagram checks of validate_annotations.py: fodder letters, setter errors, the cryptic-definition cap, blind misses.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import json
import re
import annotation
import wordplay
from annotation import assembly, explanation
from fetch_puzzle import load_source_table
from find_answer_leaks import light_solutions
from groups import entry_id

from validate_base import ROOT, types_of, letters
from validate_walkthrough import MAX_CRYPTIC_DEFINITIONS

    # Deliberately NOT checked: -LY (plenty of adverbs don't end in -ly: "always"),
    # and -ing definitions for non-ing answers ("Working vessel" = DREDGER is fine).
    # A noisy warning is a warning nobody reads.


def multiset_diff(a, b):
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    extra = "".join(sorted((ca - cb).elements()))
    missing = "".join(sorted((cb - ca).elements()))
    return extra, missing


#: Clues whose printed wordplay is the SETTER's slip: the paper printed these
#: words, and they cannot give the answer. Keyed "puzzle id/entry id", each row
#: holds the anagram fodder as printed, the letters it should give, and the
#: evidence that the print says so (the source page read, not a guess);
#: setter_error_problems says which rows fit. Unlike
#: tools/data/source_clue_wrong.json nothing is corrected: the clue stays as
#: printed, the annotation explains it as printed, and its walkthrough tells the
#: solver what is wrong with it.
SETTER_ERROR = load_source_table("setter_error")

#: The letters a setter's slip may cost an anagram, extra and missing together:
#: one wrong letter (quiptic-32 13-down, ELF OIL for KISS OF LIFE's FF and one L).
#: A parse further out than that is a wrong parse, not a slip.
SETTER_ERROR_LETTERS = annotation.SLIP_LETTERS


def setter_error_problems(puzzle, eid, row, ann=None):
    """What stops `row`, a setter_error row ["<fodder>", "<gives>", "<evidence>"],
    being filed for light `eid` of `puzzle` annotated as `ann` (default: the
    light's own annotation); [] when it may be. Each problem says what to write
    instead.

    A row is checkable from the page: each fodder word is one the clue prints,
    a block's fragment of it (PAPER out of "Notepaper"), or a block's `gives`
    read off words it prints (CLUB for "group"), its
    gives is the answer (a linked answer's every light) or the part of it the
    anagram supplies (UNANT of UNGALLANT), and fodder and gives are at most
    SETTER_ERROR_LETTERS apart. Anything else is a wrong parse, not a slip."""
    fodder, gives, why = (list(row) + ["", "", ""])[:3]
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    e = by_id[eid]
    ann = e.get("annotation") if ann is None else ann
    if isinstance(ann, dict) and "blocks" not in ann and ("wordplay" in ann or "definitions" in ann):
        # An annotation stores a tree: its blocks are view()'s.
        import annotation as annotation_view
        try:
            ann = annotation_view.view(ann, e, puzzle)
        except (wordplay.WordplayError, KeyError, TypeError, ValueError):
            ann = {}
    answer = "".join(letters(s or "") for s in light_solutions(e, by_id)) or letters(e["solution"])
    clue = e["clue"].get("text") or ""
    printed = {letters(w) for w in re.split(r"[\s\-\u2013\u2014/]+", clue)}
    read = [b for b in (ann or {}).get("blocks") or ()
            if isinstance(b, dict) and letters(b.get("clueFragment") or "")
            and letters(b.get("clueFragment") or "") in letters(clue)]
    derived = {letters(b.get(k) or "") for b in read for k in ("clueFragment", "gives")}
    out = []
    unprinted = [w for w in fodder.split() if letters(w) not in printed | derived]
    if unprinted:
        out.append(f"setterError fodder {' '.join(unprinted)!r} is neither words the clue "
                   f"prints ({clue!r}) nor a block's gives: write each fodder word as the "
                   f"clue prints it, or as the gives of the block that reads it off the clue")
    extra_over_answer, _ = multiset_diff(letters(gives), answer)
    if not letters(gives) or extra_over_answer:
        out.append(f"setterError gives {letters(gives) or '-'}, but the answer is {answer} "
                   f"({extra_over_answer or 'nothing'} not in it): write the letters the "
                   f"anagram supplies, the whole answer [\"<fodder>\", \"{answer}\", "
                   f"\"<evidence>\"] or the part of it the anagram gives")
    elif not unprinted:
        extra, missing = multiset_diff(letters(fodder), letters(gives))
        if len(extra) + len(missing) > SETTER_ERROR_LETTERS and not wordplay.run_slip(letters(fodder), letters(gives)):
            out.append(f"setterError fodder {letters(fodder)} is {len(extra) + len(missing)} "
                       f"letters from {letters(gives)} (extra: {extra or '-'}, missing: "
                       f"{missing or '-'}); a slip is at most {SETTER_ERROR_LETTERS}, so "
                       f"this is a wrong parse: drop setterError and re-parse")
    if not why.strip():
        out.append("setterError needs its evidence: what the source page prints")
    return out


def check_anagram_has_fodder(tag, ann, warnings):
    """A clue typed anagram names its shuffle in `assembly.anagrams`: the
    anagram ring on the blocks rung deals that fodder, so a clue without it
    shows the solver no ring at all.
    apply_annotations derives it wherever the blocks rebuild the answer, so one
    still missing is a shuffle the blocks cannot show and has to be written."""
    if "anagram" in types_of(ann) and not assembly(ann).get("anagrams"):
        warnings.append(f"{tag}: typed anagram but no assembly.anagrams — write "
                        f"{{\"fodder\": every letter shuffled, \"gives\": what they become}} "
                        f"so the solver gets the anagram ring")


def check_anagram_letters(pid, eid, tag, ann, errors):
    """Each anagram's fodder holds exactly the letters it gives, unless
    SETTER_ERROR names this light's fodder and gives letter for letter; such a
    row must then be used, cost at most SETTER_ERROR_LETTERS letters, and come
    with an explanation.walkthrough telling the solver of the slip."""
    row = SETTER_ERROR.get((pid, eid))
    declared = row and (letters(row[0]), letters(row[1]))
    used = False
    # The row may instead correct letters of any other step: a sound anagram
    # whose fodder is the corrected letters, or a block that reads the printed
    # words as the corrected letters (a hidden run, a charade's or a
    # container's spelt piece).
    if declared:
        used = any(not any(multiset_diff(letters(a.get("fodder")), letters(a.get("gives"))))
                   and letters(a.get("gives")) == declared[1]
                   for a in assembly(ann).get("anagrams", [])) \
            or any(isinstance(b, dict) and letters(b.get("gives")) == declared[1]
                   and declared[0] in letters(b.get("clueFragment"))
                   for b in ann.get("blocks") or [])
    for a in assembly(ann).get("anagrams", []):
        fodder, gives = letters(a["fodder"]), letters(a["gives"])
        extra, missing = multiset_diff(fodder, gives)
        if not (extra or missing):
            continue
        if (fodder, gives) == declared:
            used = True
            continue
        errors.append(
            f"{tag}: anagram fodder {fodder} != its gives {gives}"
            f" (fodder extra: {extra or '-'}, fodder missing: {missing or '-'})"
            + ("" if row else
               ". If the clue as the paper printed it truly cannot give these letters "
               "(the setter's slip, checked against the source page, not an OCR "
               "misread), give its _ann entry \"setterError\": [\"<fodder words as "
               "printed>\", \"<letters the anagram should give>\", \"<evidence>\"]"))
    if not row:
        return
    extra, missing = multiset_diff(*declared)
    if not used:
        errors.append(f"{tag}: tools/data/setter_error.json names fodder {declared[0]} "
                      f"giving {declared[1]}, and no anagram of this annotation has "
                      f"that fodder and gives: annotate the clue as printed, or delete "
                      f"the row")
    if len(extra) + len(missing) > SETTER_ERROR_LETTERS and not wordplay.run_slip(*declared):
        errors.append(f"{tag}: tools/data/setter_error.json's row is {len(extra) + len(missing)} "
                      f"letters out (extra: {extra or '-'}, missing: {missing or '-'}); a "
                      f"setter's slip is at most {SETTER_ERROR_LETTERS}, so this parse is "
                      f"wrong, not the clue")
    if not explanation(ann).get("walkthrough"):
        errors.append(f"{tag}: the setter's slip in tools/data/setter_error.json needs an "
                      f"explanation.walkthrough telling the solver what the printed clue "
                      f"gets wrong")


def check_cryptic_definition_cap(entries, errors, warnings=None, authored=False):
    """A puzzle may not lean on cryptic definitions (see MAX_CRYPTIC_DEFINITIONS).

    This is the one check that looks at the puzzle rather than the clue: every
    individual cryptic definition can be perfectly good and the set still be
    wrong.

    Over the cap is an error only when we set the puzzle, because that is the
    only case where the count is ours to change. On a fetched puzzle it warns,
    at the cap or over it, and names every cryptic definition for a human to
    read. Reaching the cap warns at all because a cryptic definition is the
    only type an annotator can reach for without solving anything, which makes
    the count a measure of giving up: an annotator can land on exactly the cap
    by spending its whole surrender budget on clues that do have wordplay (30078
    9A OPERA STAR, 19D CHUKKAS = CHAS round UK + K).
    Nothing mechanical can tell a real cryptic definition from a shrug: it
    claims no letters, so it contradicts nothing. On the benchmark clues, a
    block handing over the answer catches 4 of 9, a whole-clue definition 8 of
    9, and an indicator word appearing in the clue 3 of 9 — all of them also
    true of correct annotations, so none of them is a rule. A human reading the
    named clues is the only check there is, and this warning is how they get
    named.
    """
    cds = [f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
           for e in entries
           if types_of(e.get("annotation") or {}) == ["cryptic_definition"]]
    if len(cds) < MAX_CRYPTIC_DEFINITIONS:
        return
    if len(cds) > MAX_CRYPTIC_DEFINITIONS and authored:
        errors.append(
            f"puzzle: {len(cds)} cryptic definitions ({', '.join(cds)}) — at most "
            f"{MAX_CRYPTIC_DEFINITIONS} allowed in a puzzle we set ourselves. A cryptic "
            f"definition has no checkable wordplay, so past two the puzzle stops being "
            f"solvable and starts being guessable; rewrite these clues around a "
            f"mechanism (AUTHORING.md)")
        return
    if warnings is not None:
        warnings.append(
            f"puzzle: {len(cds)} cryptic definitions ({', '.join(cds)}), at or over the "
            f"cap of {MAX_CRYPTIC_DEFINITIONS}. Not an error, but this is where an "
            f"annotator that could not solve a clue puts it, and nothing downstream can "
            f"tell that from a real cryptic definition. Read those clues and satisfy "
            f"yourself there is no wordplay in them")


def blind_misses(pid):
    """The entries a blind run got wrong, whose explanations the grader dropped.

    Written by tools/fetch_puzzle.py's record_misses after the run has ended,
    by comparing what the model derived against the published key (the blind
    solve's grader). The model never sees this
    file and cannot write it, which is what makes it safe to soften the check
    below: it is the one blank the annotator did not choose.
    """
    path = ROOT / "tools" / "data" / "blind_misses.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(pid, {})
    except (OSError, ValueError):
        return {}