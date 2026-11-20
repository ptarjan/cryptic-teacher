"""Answer-level checks of validate_annotations.py: doubted model answers, every clue annotated, cryptic-definition blocks.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import re
import definitions
import groups
import provenance
from groups import entry_id

from validate_base import types_of, letters

# A cold solve's answer its own annotator would not stand behind. Every answer
# an official key later overturned had one of two marks on it, and every fill
# passed the solve gate because its crossings agreed: listener-3 40D SLA
# ("UNRESOLVED ... This fill is a placeholder until the published solution
# corrects it"; the key says SLY) and 6D KARNATIC ("Usually spelt Carnatic";
# the key says CARNATIC, and 6A KALYAN fell with it on their shared K). The
# phrases are the annotator talking about its own answer, never about a
# definition: LEGEND's "historically unverified" story or UP IN THE AIR's
# "unresolved state" do not match.
DOUBTS = re.compile(
    r"^\s*(?:unresolved|unconfirmed|unverified)\b"
    r"|\b(?:unresolved|unconfirmed|unverified)(?: guess)?:"
    r"|\b(?:unconfirmed|unverified|a placeholder|placeholder) until\b"
    r"|\btreat (?:this|it|that)\b[^.]{0,40}\bas (?:unconfirmed|unverified)\b"
    r"|\bnot fully parsed\b|\bparse is (?:only )?partial\b"
    r"|\bno wordplay\b[^.]{0,40}\bwas found\b|\bnothing found explains\b",
    re.I | re.M)

# "usually spelt X", where X is the answer one or two letters away: the grid
# took a variant whose odd letter sat where nothing checked it.
VARIANT_SPELLING = re.compile(r"\b(?:usually|normally|more often|commonly) spelt ((?:[A-Za-z'-]+ ?){1,3})", re.I)


def annotation_prose(ann):
    ex = ann.get("explanation") or {}
    return "\n".join([ex.get("walkthrough") or "", ex.get("definitionFit") or ""]
                     + [b.get("note") or "" for b in ann.get("blocks") or []])


def variant_named(answer, prose):
    """The usual spelling the prose names for `answer`, when it is a near-twin."""
    want = letters(answer)
    for m in VARIANT_SPELLING.finditer(prose):
        words = m.group(1).split()
        for n in range(1, len(words) + 1):
            other = letters(" ".join(words[:n]))
            if len(other) == len(want) and other != want:
                if sum(a != b for a, b in zip(other, want)) <= max(1, len(want) // 4):
                    return other
    return None


def doubted_model_answers(puzzle):
    """{entry id: why} for each model answer whose annotation doubts it and that
    may still be sent back: not printed by the paper, not graded by a key, not
    reopened before (tools/reopen_answers.py reopens an entry once)."""
    if provenance.solution_origin_from_file(puzzle) != "model":
        return {}
    detail = puzzle.get("solutions") or {}
    settled = (set(provenance.printed_answers(puzzle)) | set(detail.get("graded") or {})
               | set(detail.get("reopened") or {}))
    out = {}
    for e in puzzle["entries"]:
        ann = e.get("annotation")
        if entry_id(e) in settled or not isinstance(ann, dict) or not e.get("solution"):
            continue
        prose = annotation_prose(ann)
        m = DOUBTS.search(prose)
        if m:
            out[entry_id(e)] = f"its annotation says {m.group(0).strip()!r}"
            continue
        other = variant_named(e["solution"], prose)
        if other:
            out[entry_id(e)] = f"its annotation names the usual spelling {other}"
    return out


def check_model_answer_doubted(puzzle, errors, warnings, corpus=False):
    """A model answer the annotation doubts goes back to be solved, not shipped.

    The solve gate checks a fill against its own crossings, so a wrong letter
    on an unchecked cell, or two weak answers agreeing on a shared one, passes
    it; the annotator is the first reader who has to account for the word, and
    when it writes "unconfirmed" it has found it cannot. An error here makes the
    burn reopen the light once (tools/reopen_answers.py, which reads the same
    function), so the next solve sees the rejected word. In a corpus run it is
    a warning: those answers are already committed and reopened from there."""
    for eid, why in doubted_model_answers(puzzle).items():
        num, direction = eid.split("-")
        tag = f"{num}{'A' if direction == 'across' else 'D'}"
        (warnings if corpus else errors).append(
            f"{tag}: the model's answer is in doubt — {why}. Write the word the clue "
            f"really gives in `answer` if you can parse it, else leave the clue null; "
            f"either way it is solved again rather than shipped with a hedged hint")


def is_blank_clue(clue):
    """A grid entry the setter left without a clue: no text (an enumeration,
    if printed, is kept apart)."""
    return not (clue or "").strip()


#: A puzzle ships round its withheld clues until they are more than this share
#: of its clues; then most of it is unusable and the run withdraws.
WITHHELD_MOST = 0.5


def check_every_clue_is_annotated(entries, errors, warnings, misses=(), corpus=False, reopened=(),
                                  dropped=(), withheld=()):
    """Once a puzzle is annotated at all, every clue in it must be annotated.

    A blank annotation is the one failure no other check can see: it claims
    nothing, so it contradicts nothing, and the puzzle ships a clue with no
    teaching ladder behind it. It is also the escape hatch from every other
    rule here — blanking a clue avoids failing check_cryptic_definition_cap, which
    would turn a loud failure into a silent one. Erroring here is what stops a
    rule elsewhere from being paid for in blanks.

    That is a rule for the run that annotates. A corpus-wide run (`corpus`)
    reads committed puzzles, where a hole is a clue whose annotation was dropped
    because its text was corrected: the puzzle indexes as unannotated and the
    queue annotates it again, as it does a puzzle with no annotations at all.

    The one legitimate blank is a clue the setter left blank on purpose (a
    grid entry with no clue text, as in cryptic-30098 12A). That is detectable
    from the clue itself rather than from an allowlist: it has no text.

    The other is a cold solve's miss, in `misses`. A puzzle solved before its
    key was published is graded when the key arrives, and the grader drops the
    explanation of every clue the model got wrong, because an explanation built on a wrong answer is wrong from its
    first line. That blank is the grader's, decided after the run ended and off
    the published key, so it is not an escape hatch — the model cannot reach it.

    The last is a light in `reopened` (solutions.reopened): a model answer an
    annotation already failed to parse once, sent back to be solved again
    (tools/reopen_answers.py). Blank, it awaits that solve, and the hints
    around it stand; answered and still null, the second solve found no
    parse either, and it ships with answers only rather than being solved
    a third time.

    Not blank either: a clue in `dropped`, whose annotation tree_view left out
    of the view because its tree does not give the answer. Its `wordplay:`
    error already names it; calling it blank too sent toughie-2626 (10-23,
    1D MOBIUS) hunting for a clue it had written, for five turns.

    And a clue in `withheld` (fetch_puzzle.withheld_clues): one the run could
    not annotate honestly and said why, because the clue as held is cut short
    or garbled and no source gives the rest, or because its only parse has one
    word doing two jobs, which the grammar refuses on purpose. Before 11-04
    this error's only way out for such a clue was to withdraw the puzzle, and
    46 were withdrawn that day, nearly all over one or two clues, throwing away
    every other clue's hints. A withheld clue names itself and its reason, so
    it is not the silent blank this check exists to stop; it ships with answers
    only, and the reason stays on the entry until the clue is fixed. Only when
    withheld clues are more than WITHHELD_MOST of the puzzle is it unusable
    as a whole.
    """
    continuations = groups.leader_of(entries)
    blank, held, total = [], [], 0
    for e in entries:
        if entry_id(e) not in continuations and not is_blank_clue(e["clue"].get("text", "")):
            total += 1
        if e.get("annotation") or entry_id(e) in dropped:
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        if entry_id(e) in withheld:
            held.append(tag)
            if not corpus:
                warnings.append(f"{tag}: withheld — {withheld[entry_id(e)]}. It ships with "
                                f"answers only, and the reason is kept for whoever fixes the clue")
            continue
        if entry_id(e) in misses:
            warnings.append(
                f"{tag}: no annotation — the cold solve answered "
                f"{misses[entry_id(e)]!r} wrongly and the grader dropped its "
                f"explanation. It ships with answers only until someone annotates it")
            continue
        if is_blank_clue(e["clue"].get("text", "")):
            warnings.append(f"{tag}: no annotation, and no clue to annotate — "
                            f"the setter left this entry blank on purpose")
            continue
        if entry_id(e) in reopened:
            warnings.append(
                f"{tag}: no annotation — its answer was sent back to be solved again "
                f"(solutions.reopened), and that solve annotates it" if not e.get("solution") else
                f"{tag}: no annotation — solved twice and no parse found either time, "
                f"so it ships with answers only")
            continue
        if entry_id(e) in continuations:
            continue                      # annotated on its group's leader
        if corpus:
            warnings.append(f"{tag}: no annotation — queued to be annotated again")
            continue
        blank.append((tag, e.get("solutionConfidence") == "LIKELY"))
    if not corpus and held and len(held) > WITHHELD_MOST * total:
        tag = ",".join(held)
        errors.append(
            f"{tag}: withheld, {len(held)} of {total} clues — too much of the "
            f"puzzle to ship round. Annotate the ones you can after all, or run the check "
            f"once with `--withdraw \"<what is wrong with the clues>\"` and stop")
    if not blank:
        return
    # One line for every blank: a run that checks a half-written file would
    # otherwise get this paragraph once per clue it has not reached yet.
    tag = ",".join(t for t, _ in blank)
    likely = [t for t, is_likely in blank if is_likely]
    likely = (f" {', '.join(likely)}: a model's LIKELY fill, not the paper's: annotate "
              f"it only if you can derive the whole answer from the clue yourself."
              if likely else "")
    unwritten = (f" With {len(blank)} blank, write every one before running the check "
                 f"again: a check of a half-written file costs a turn."
                 if len(blank) > 1 else "")
    errors.append(
        f"{tag}: no annotation. Every clue in an annotated puzzle needs one — "
        f"a blank ships a clue with nothing to teach, and no other check can "
        f"see it.{unwritten} If a rule elsewhere is what stopped you, break that rule "
        f"loudly instead: it names the clue, a blank does not.{likely} A clue "
        f"you cannot annotate honestly (cut short or garbled as held and no source "
        f"gives the rest, or parsed only with one word doing two jobs, which the "
        f"check refuses) is withheld rather than left null: give it "
        f"{{\"withheld\": \"<the clue as held, and what is missing or which word does "
        f"two jobs>\"}} and the rest of the puzzle ships round it. A confident wrong "
        f"explanation ships and nothing catches it; a withheld clue can be fixed later")


def check_cryptic_definition_blocks(tag, ann, errors, warnings):
    """A cryptic definition's blocks may not give letters or spell the answer.

    The cap above asks whether a clue should be a cryptic definition at all.
    This asks a different question of the ones that legitimately are: does the
    annotation of it teach anything?

    There is exactly one block shape available to an annotator who does not
    think about it — the whole clue, giving the whole answer. Rendered, that is
    hint 3 of 4 reading “Might this keep you to time?” → WATCHSTRAP: the rung
    before it has just said there is no separable wordplay, and this one charges
    a hint for the solve.

    So `gives` is banned outright. A cryptic definition yields no letters from
    any fragment — that is the definition of the type — and a `gives` is
    therefore always the whole answer wearing a block's clothes.

    A cryptic definition is one block, the clue words once (cd([clue words]), which
    wordplay.cdefRepeat holds it to). A clue with two readings in two stretches is a
    double definition, and is typed as one. It is a presentation rule, not a lie
    detector: the clue can be a perfectly honest cryptic definition and still be
    annotated into a rung that hands over the answer.
    """
    if types_of(ann) != ["cryptic_definition"]:
        return
    blocks = ann.get("blocks") or []
    giving = [b.get("clueFragment") or "?" for b in blocks if (b.get("gives") or "").strip()]
    if giving:
        errors.append(
            f"{tag}: cryptic definition has blocks that 'give' letters "
            f"({', '.join(repr(g) for g in giving)}) — a cryptic definition has no "
            f"wordplay, so the only thing a fragment can give is the whole answer, "
            f"and the blocks rung is shown before the walkthrough. Drop `gives` and "
            f"put the explanation in `note`")
    # Banning `gives` only closes the obvious door. Splitting the clue properly
    # and then writing the answer into a note leaks it just the same, and it is
    # the likelier mistake once the shape is right: 30039 10A VANITY split into
    # "case" and "conceitedness" and then explained them as "points to the phrase
    # 'vanity case'" and "vanity = conceitedness". Elsewhere in the corpus a block
    # note may name the answer — the blocks rung is where a charade spells it out
    # — so this is the cryptic definition's own rule, and it exists because this
    # type has no walkthrough-free way to earn it.
    #
    # Read as the rungs render it — definition, then each fragment and its note
    # in order — because tools/smoke_test.js climbs the real ladder and rejects
    # the answer's letters anywhere in that text, across word and block joins.
    # A definition that hides the answer is a hidden word filed as a cryptic
    # definition (timesjumbo-1755 14A, "Unit of fighting Aussies?" = GAUSS).
    ans = re.sub(r"[^a-z]", "", str(ann.get("answer") or "").lower())
    if len(ans) >= 4:
        bare = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())
        defined = " / ".join(definitions.texts(ann))
        if ans in bare(defined):
            errors.append(
                f"{tag}: cryptic definition {defined!r} hides the answer "
                f"in its own letters, and the definition rung shows it before the "
                f"walkthrough. A clue that hides its answer is a hidden word: type it "
                f"as one, with the definition, the indicator and the fodder")
        run = "".join(bare(b.get("clueFragment")) + bare(b.get("note")) for b in blocks)
        if ans in run:
            errors.append(
                f"{tag}: cryptic definition blocks spell the answer out, read in order "
                f"as the blocks rung shows them, and that rung comes before the "
                f"walkthrough. For every other type the blocks are where the answer "
                f"is assembled; here there is nothing to assemble, so a note that "
                f"names it is just the solve. Describe the reading, not the word")