#!/usr/bin/env python3
"""Validate clue annotations in puzzles/*.js.

Checks, for every annotated entry:
  - annotation has type, definition, walkthrough, answer, blocks
  - every " + "-joined part of `type` is in the controlled vocabulary (TYPE_PARTS)
  - answer letters match the grid solution (group-aware for linked entries)
  - definition / definition2 / every indicator / every linkWord is an exact
    substring of the clue, and every content word of the clue is claimed by one
    of those or by a block (check_coverage)
  - definition and answer agree in inflection, unless a definitionNote explains
    why they don't (check_part_of_speech)
  - anagram fodder letters match the answer letters (multiset)
  - charade/container "pieces" concatenate exactly to the answer letters
  - hidden answers actually occur in the clue's letters
  - subAnagrams are letter-for-letter anagrams; subReversals reverse correctly
  - linkedTo targets exist and cover their group

And five checks that apply only to puzzles we WROTE (see is_authored):
  - no block may have an empty `gives`: every word of an authored clue is
    definition, wordplay or joinery, never surface padding (check_two_pieces)
  - the walkthrough stays inside MAX_WALKTHROUGH_WORDS when the blocks already
    spell the answer out (check_walkthrough_budget)
  - every linkWord stands in for an equals sign (check_link_words_are_equivalences)
  - an anagram indicator touches its fodder (check_indicator_adjacency)
  - and is not made of the fodder's own letters (check_indicator_outside_fodder)
  - a reversal indicator points the way the entry runs (check_reversal_direction)

And one whole-puzzle check:
  - at most MAX_CRYPTIC_DEFINITIONS clues typed "cryptic definition"

Usage: python3 tools/validate_annotations.py [--unscoped] [--tighten] [puzzle-number ...]
With no arguments, validates every puzzle that has at least one annotation.
`--unscoped` runs the authored-only checks on published puzzles too — that is
the CALIBRATION harness, not a mode to ship in: a check that flags Araucaria is
a broken check, so every authored-only rule is measured across the eight
annotated Guardian puzzles before it is trusted. Exits non-zero if any check
fails.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUZZLE_DIR = ROOT / "puzzles"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import puzzle_files, resolve_puzzle  # noqa: E402 — one glob, one id resolver
from find_answer_leaks import says  # noqa: E402 — one matcher, shared with the finder
JSON_START = "/*JSON-START*/"
JSON_END = "/*JSON-END*/"

# The controlled vocabulary for `type`. Compound types join parts with " + " and
# must name EVERY mechanism the wordplay uses (see STYLE.md — "honest types").
TYPE_PARTS = {
    # base clue types
    "anagram", "charade", "container", "hidden word", "homophone", "reversal",
    "deletion", "double definition", "cryptic definition", "&lit", "spoonerism",
    # letter-selection mechanisms
    "first letter", "first letters", "last letter", "last letters",
    "middle letter", "middle letters", "outer letters", "alternate letters",
    # a single letter picked by its position in the word (12420 14D takes the
    # second letter of master for the A of AGO), and the plural case where a run
    # of words each give up the same position (30065 6D takes the second letter
    # of read advertising watchdog's email to spell EDAM). Note the comments in
    # this block carry no double quotes: tools/smoke_test.js reads every quoted
    # string between the braces as a type part.
    "second letter", "second letters",
    # the same device counted one place further in: 12405 3D takes the third
    # letter of students for the U of GURU. Not a middle letter, which is what
    # third of means only when the word has five letters (30068 6D, those).
    "third letter", "third letters",
    # "alternate letters" is the every-SECOND case; a setter may count in any
    # step (30077 17D takes every third letter of HOPE TO GOD to spell POD)
    "regular letters",
    # letter-movement mechanisms: a rotation that keeps letter order (30079 7D
    # TSUNAMIS = A MIST SUN cycled), and a swap of one indicated letter for
    # another (30079 15D LAUGH LINE = TAUGHT IN E with Ls covering the Ts)
    "cycling", "substitution",
    # the answer is its own reversal: 30052 23D PULL-UP, clued Stop going both
    # ways. Not a reversal, since nothing is turned round to make something
    # else, so no fragment hands over letters and the blocks split into
    # readings rather than chunks, the way a cryptic definition's do. As above,
    # no double quotes in this comment: the smoke test would read them as parts.
    "palindrome",
}


# A cryptic definition has no checkable mechanism: the solver either sees the
# joke or is stuck. One or two per puzzle is a treat, more is a quiz. Measured
# over the annotated puzzles in puzzles/: only one published puzzle (30039)
# carries any cryptic definitions at all, and it carries exactly two — so this
# ceiling has never fired on a Guardian grid. It exists because OUR authoring
# pass drifts over it: chasing a funny surface produced six in one rewrite of
# A001, since a funny sentence is far easier to find than a funny mechanism
# (feedback 2026-07-29: "they don't have wordplay anymore"). See AUTHORING.md,
# "The sentence AND the wordplay".
MAX_CRYPTIC_DEFINITIONS = 2


# "A good cryptic clue doesn't have anything superfluous which isn't directly
# part of the wordplay. It should be exactly two pieces. Definition, optional
# joinery and wordplay." (feedback 2026-07-29). A word that exists only to make
# the surface read nicely is a fault, and in this schema it has exactly one
# signature: a block with an empty `gives`, i.e. "surface only" padding.
#
# A walkthrough budget for the companion rule: "When you basically give the whole
# answer in the building blocks you don't need to have the full walkthrough."
# 45 is measured, not invented — across the 231 annotated walkthroughs in
# puzzles/ the median is 32 words and the 90th percentile is 42, while the A001
# set that prompted the feedback ran 44-63 with a median of 54.
MAX_WALKTHROUGH_WORDS = 45


# Set by --unscoped: run the authored-only checks on published puzzles as well.
# This exists so the calibration in every authored check's docstring can be
# reproduced in one command instead of a throwaway script.
FORCE_AUTHORED_CHECKS = False


def is_authored(puzzle):
    """Did we write this puzzle, or is it a published Guardian grid?

    Ours carry series "authored" (tools/series.py). This used to read the first
    character of the id, because ours began with a letter and every published
    one began with a digit — and then ids grew their series on 2026-08-19, every
    id began with a letter, and every Guardian puzzle was silently held to the
    authoring rules. A field, not a spelling. The distinction matters because
    the checks below are AUTHORING rules, not annotation rules: real setters
    pad their surfaces and write long clues, and an annotation of a published
    grid has to be able to record that faithfully."""
    return FORCE_AUTHORED_CHECKS or puzzle.get("series") == "authored"


def check_two_pieces(tag, ann, errors):
    """Every word of a clue we wrote must be doing one of three jobs.

    Definition, wordplay (fodder or indicator), or joinery. Nothing else — and a
    block with an empty `gives` is the annotation saying out loud that a word is
    there for the surface alone. That is legitimate when ANNOTATING a published
    clue (30039 5A, 30040 16A and 30067 20D all carry one, and STYLE.md's
    "leftover words" rule tells the annotator to record it rather than drop it),
    which is why this only fires on authored puzzles.

    The deeper point, from AUTHORING.md: a funny sentence is easy if you are
    allowed filler. Banning filler is what separates a clue from a joke that
    happens to contain the answer."""
    for b in ann.get("blocks", []):
        if not str(b.get("gives") or "").strip():
            frag = b.get("clueFragment") or "(no fragment)"
            errors.append(
                f"{tag}: block {frag!r} has an empty 'gives' — surface padding is not "
                f"allowed in a clue we wrote. Every word must be definition, wordplay "
                f"or joinery: rewrite the clue without it, or work out which job it is "
                f"really doing (AUTHORING.md, 'Exactly two pieces')")


def check_walkthrough_budget(tag, ann, warnings):
    """When the blocks already spell the answer out, the walkthrough is short.

    Honest about what this can and cannot see: it is a BUDGET, not a redundancy
    detector. It cannot tell a long walkthrough that teaches something from a
    long one that re-narrates the blocks — but in our own puzzles the long ones
    have always been the re-narrating ones (19 of the 20 A001 walkthroughs that
    prompted the rule were over budget, and every one of them restated its
    blocks). A semantic detector was tried and thrown away: scoring the fraction
    of walkthrough vocabulary already present in the clue and blocks separated
    nothing (A001 before 0.21, after 0.16, published puzzles 0.30 — the good
    walkthroughs scored WORSE than the bad ones, because naming the joke means
    reusing the clue's own words). Do not re-add it without new evidence.

    The judgement half stays procedure: keep only what the blocks cannot show —
    why the surface misleads, the joke, a convention (ER = Queen), or why the
    definition is fair."""
    wt = (ann.get("walkthrough") or "").split()
    has_blocks = any(b.get("gives") or b.get("note") for b in ann.get("blocks", []))
    if has_blocks and len(wt) > MAX_WALKTHROUGH_WORDS:
        warnings.append(
            f"{tag}: walkthrough is {len(wt)} words with a building-blocks rung above it "
            f"(budget {MAX_WALKTHROUGH_WORDS}) — cut whatever the blocks already say and "
            f"keep only what they cannot show (STYLE.md, 'the blocks already told them')")


# A link word stands in for an equals sign. It may assert equivalence (is, are,
# 's), derivation (gives, makes, becomes, yields, produces, leads to, means,
# spells, indicates, reveals, to locate) or plain prepositional joining (for,
# from, of, in, with, by, as, after) — and it may be grammatical glue holding
# those together (articles, determiners, pronouns, relative pronouns). Anything
# else is a content word doing surface work, i.e. padding wearing a link word's
# coat, and it makes the clue a THREE-piece clue.
#
# Built from the standard link-word vocabulary, then widened by measurement:
# `after` (x3) and `having` (x1) were added because published clues use them in
# the joinery position. See check_link_words_are_equivalences for the counts.
EQUIVALENCE_LINKS = {
    # equivalence
    "is", "are", "was", "were", "be", "been", "being", "am", "s",
    # derivation: the wordplay turns into / hands you the answer
    "gives", "give", "given", "giving", "makes", "make", "made", "making",
    "becomes", "become", "became", "becoming", "yields", "yield", "yielding",
    "produces", "produce", "producing", "provides", "provide", "providing",
    "has", "have", "had", "having", "shows", "show", "showing", "brings",
    "bring", "bringing", "gets", "get", "getting", "got", "leads", "lead",
    "leading", "means", "meaning", "meant", "spells", "spelling", "needs",
    "need", "reveals", "reveal", "revealing", "finds", "find", "finding",
    "locate", "locates", "locating", "indicates", "indicate", "indicating",
    "denotes", "denote", "denoting",
    # prepositional joining
    "for", "from", "in", "of", "with", "to", "into", "as", "by", "at", "on",
    "after", "and", "or",
    # grammatical glue: articles, determiners, pronouns, relatives
    "a", "an", "the", "another", "this", "that", "these", "those", "one",
    "his", "her", "its", "their", "our", "your", "my",
    "what", "who", "whom", "which", "where", "when", "there", "here",
    "it", "he", "she", "they", "you", "we", "i", "not", "no", "all",
}


def check_link_words_are_equivalences(tag, ann, errors):
    """A link word has to stand in for an equals sign (feedback 2026-07-30).

    "lives on" does not. It joins nothing and asserts nothing; it is surface
    padding wearing a link word's coat, and declaring it in `linkWords` makes
    the annotation look sound while the clue is quietly in three pieces —
    wordplay, PADDING, definition. That is the same fault check_two_pieces
    catches when the annotator is honest enough to file it as a block with an
    empty `gives`; this check closes the other door.

    CALIBRATION (unscoped, the eight annotated Guardian puzzles): the corpus
    declares only TWO link words in 234 entries — `indicating` (30039 18D) and
    `to locate` (30040 14D) — and both pass. Two data points is thin, so the
    whitelist was also measured against a proxy with 50x the sample: every clue
    word in the corpus that the annotation claims for nothing (definition,
    indicator, block, link) is a word sitting in the joinery position. There are
    105 such occurrences over 28 distinct words; 101 were already whitelisted
    and the four misses were `after` (x3) and `having` (x1), both plainly
    grammatical, both since added. Hit rate on published work: 0/105.

    The rule bites on our own clues, where it caught three of twenty: `would be
    better spent` (THERE), `mistake it for` (LEADERSHIP), `lives on` (STOREY).
    If it ever fires on a link word a real setter would use, WIDEN THE LIST —
    the whitelist is the rule, and a false positive here means the vocabulary is
    short, not that the setter is wrong."""
    for lw in ann.get("linkWords", []):
        bad = [t for t in words_of(lw) if t not in EQUIVALENCE_LINKS]
        if bad:
            errors.append(
                f"{tag}: linkWord {lw!r} is not a link word — {', '.join(bad)} asserts no "
                f"equivalence between wordplay and definition. A link word stands in for an "
                f"equals sign (is/gives/makes/for/from/'s); anything else is padding, and a "
                f"clue with padding is in three pieces, not two (AUTHORING.md, 'Link words "
                f"are an equals sign'). Rewrite the clue, or widen EQUIVALENCE_LINKS if a "
                f"real setter would use this")


# What may stand between an anagram indicator and its fodder: grammatical glue
# binding the one to the other, and nothing else. `Naples WAS flattened`, `A grub
# seen wriggling`, `Latin song IN parts swapped` are all fine.
FODDER_GLUE = {
    "a", "an", "the", "this", "that", "these", "those", "another",
    "is", "are", "was", "were", "be", "been", "being", "s",
    "with", "of", "in", "and", "to", "for", "from", "by", "as", "at", "on",
    "its", "his", "her", "their",
}


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
    grammatical glue may stand between the two (FODDER_GLUE) — plus the
    definition, which really does sometimes sit in the gap, and any span the
    annotation has already confessed to as padding (a block with an empty
    `gives`, itself an ERROR in an authored puzzle).

    Note this is NOT the withdrawn advice in AUTHORING.md about indicator
    placement. That one said do not put the indicator next to the fodder, as a
    style preference, and was killed by measurement (88.9% of published anagrams
    do exactly that). This says the opposite thing about a different subject: it
    is a soundness rule, and the measurement supports it.

    CALIBRATION (unscoped, the eight annotated Guardian puzzles): 42 anagram
    clues, 39 with a locatable fodder span, 0 flagged. The three unlocatable
    ones (30040 8A, 30040 11A, 30041 20A) all build their fodder by deleting
    letters, so no span in the clue holds it; they are skipped, and an authored
    clue in that shape gets a warning rather than a false ERROR. The two
    allowances above are each carrying exactly one published clue: 30043 1A
    (`Bans recitals - where this is played?`, definition in the gap) and 30067
    20D (`Bertie develops from bad to worse`, annotated padding in the gap)."""
    if not ann.get("anagram"):
        return
    spans = _fodder_spans(clue, ann["anagram"].get("fodder"), ann.get("blocks", []))
    inds = [(clue.find(i), clue.find(i) + len(i), i) for i in ann.get("indicators", [])
            if i in clue]
    if not inds:
        return
    if not spans:
        warnings.append(
            f"{tag}: cannot locate the anagram fodder in the clue text, so adjacency is "
            f"unchecked — normal when letters are deleted to build the fodder, but in a "
            f"clue we wrote, check by eye that the indicator touches it")
        return
    allowed = set(FODDER_GLUE)
    for src in (ann.get("definition"), ann.get("definition2")):
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


def check_indicator_outside_fodder(tag, ann, clue, errors):
    """An anagram indicator cannot be made of letters the anagram eats.

    The instruction and the material are two different jobs, and one word cannot
    hold both: if `spin` is inside PAID TO SPIN then its letters are already
    spoken for, and whatever tells you to shuffle them has to be some other word.
    Obvious once stated, and easy to get backwards anyway — `spin`, `cooked`,
    `broken`, `wild` all read as instructions wherever they appear, so a reader
    (or a model annotating in bulk) will happily nominate one that is really
    fodder. That is exactly what happened on 30,079 13D, where the annotation had
    it right and a human review of the card had it wrong.

    Adjacency alone cannot catch this: check_indicator_adjacency measures the gap
    BETWEEN indicator and fodder, and an indicator sitting inside the fodder has
    no gap at all, so it scores as perfectly placed.

    Only flagged when every locatable reading of the fodder swallows the
    indicator, matching the adjacency check's rule that any clean reading wins.

    CALIBRATION (2026-08-08, all 116 annotations carrying a fodder): 0 flagged.
    A guard against a future annotation, not a description of a present one.
    """
    if not ann.get("anagram"):
        return
    spans = _fodder_spans(clue, ann["anagram"].get("fodder"), ann.get("blocks", []))
    if not spans:
        return
    for ind in ann.get("indicators", []):
        i = clue.find(ind)
        if i < 0:
            continue
        if all(i < fe and i + len(ind) > fs for fs, fe in spans):
            errors.append(
                f"{tag}: anagram indicator {ind!r} sits inside the fodder "
                f"{ann['anagram']['fodder']!r} — its letters are already being "
                f"shuffled, so it cannot also be the instruction to shuffle them. "
                f"The indicator is some other word in the clue.")


# A reversal runs along the entry, so the indicator has to name the entry's own
# direction. Words that name a horizontal reversal (fine in an across entry,
# wrong in a down one) and a vertical one (the mirror). Anything not listed —
# turning, revolutionary, overturned, about, over, regressed, withdraw, tipped,
# given a twirl, reversal — is direction-neutral and always fair.
HORIZONTAL_REVERSAL = {
    "back", "backs", "backed", "backing", "backward", "backwards",
    "returning", "returned", "returns", "retreating", "retreats", "retreat",
    "west", "westward", "westwards", "westerly", "left", "leftward", "leftwards",
}
VERTICAL_REVERSAL = {
    "up", "upward", "upwards", "uphill", "rising", "rises", "risen", "rise",
    "climbing", "climbs", "climb", "ascending", "ascends", "ascent", "ascend",
    "lifted", "lifting", "lifts", "lift", "raised", "raises", "raising",
    "elevated", "elevating", "elevates", "erected", "hoisted", "mounting",
    "north", "northward", "northwards", "northerly", "below", "underneath",
}


def check_reversal_direction(tag, ann, direction, errors):
    """A reversal indicator must point the way the entry runs.

    An across answer reads right to left when it is reversed, so it comes
    `back`, `returning`, `west`. A down answer reads bottom to top, so it comes
    `up`, `rising`, `climbing`, `from below`. `Back at the pool` cannot reverse
    a DOWN entry: there is no backwards on a vertical axis.

    CALIBRATION (unscoped, the eight annotated Guardian puzzles): 19 reversal
    clues, 0 flagged, and the convention is not merely un-violated but actively
    observed — of the 19, ten down entries use a vertical indicator (`pulled
    up`, `up`, `from below`, `elevating`, `set up`, `to climb`) and four across
    entries a horizontal one (`backing`, `Turning left`, `Looking west`,
    `regressed`), with no crossover in either direction. The remaining five use
    direction-neutral indicators (`turning`, `Revolutionary`, `given a twirl`,
    `reversal`, `Withdraw`), which is the escape hatch when the surface wants a
    word the axis will not license.

    Only declared indicators are examined, and only on clues whose type or
    subReversals say a reversal happens, so an ordinary `up` elsewhere in the
    surface is not the check's business (30039 11A reverses UP itself)."""
    if "reversal" not in (ann.get("type") or "") and not ann.get("subReversals"):
        return
    wrong = VERTICAL_REVERSAL if direction == "across" else HORIZONTAL_REVERSAL
    axis = ("an across entry reads right to left when reversed, so it wants "
            "back / returning / west"
            if direction == "across" else
            "a down entry reads bottom to top, so it wants up / rising / "
            "climbing / lifted / from below")
    for ind in ann.get("indicators", []):
        hits = [w for w in words_of(ind) if w in wrong]
        if hits:
            errors.append(
                f"{tag}: reversal indicator {ind!r} points the wrong way for a "
                f"{direction} entry ({', '.join(hits)}) — {axis} (AUTHORING.md, "
                f"'A reversal runs along the entry')")


# Words that carry no wordplay on their own, so they don't need to be claimed by
# the definition, an indicator or a block (see check_coverage).
FILLER_WORDS = {
    "a", "an", "and", "the", "of", "to", "in", "on", "at", "for", "with", "by",
    "from", "as", "is", "are", "was", "were", "be", "s", "that", "this", "it",
    "its", "his", "her", "their", "some", "one", "or", "but", "not", "no",
    "into", "up", "out", "off", "over", "about", "after", "before", "when",
    "we", "you", "i", "he", "she", "they", "me", "him", "them", "us",
    # linking verbs: connective grammar, never fodder on their own
    "has", "have", "had", "having", "been", "being", "get", "gets", "got",
    "make", "makes", "made", "may", "might", "can", "will", "would", "must",
    "do", "does", "did", "gives", "give", "goes", "go", "if", "so", "all",
}
# Hedges that excuse an unexplained chunk instead of parsing it. A walkthrough
# that needs one is nearly always hiding a wrong parse (feedback 2026-07-29:
# 30067 13A "jokingly adjectived" was papering over state = CAL).
HEDGES = ("jokingly", "if you squint", "hand-wave", "handwave", "somehow",
          "for some reason", "don't ask", "close enough")

# Working-out left in the published text. A walkthrough is the finished
# explanation; if it is still arguing with itself, the model shipped its scratch
# pad. Found 2026-08-05 benchmarking Haiku 4.5 as a cheaper annotator: it passed
# every mechanical check on 30073 and then handed the reader a 1A walkthrough
# that backtracked five times ("No wait—", "Still wrong.", "That's not it
# either.") and gave up without a parse. Nothing here caught it, because every
# field was present and every letter added up — the checks were all about
# structure and none about whether the prose was finished.
#
# Two guards, deliberately: the phrase list below, and WALKTHROUGH_HARD_MAX.
# The phrases are a text match and so only catch the wordings seen so far; the
# word cap is structural and catches dumped reasoning whatever it says, because
# reasoning-in-public is long and a finished walkthrough is short.
#
# It is a second, higher ceiling on top of MAX_WALKTHROUGH_WORDS (45), not a
# replacement: that one is a style budget and warns, on authored puzzles only,
# when the prose repeats what the blocks already said. This one is an ERROR on
# every puzzle and asks a cruder question — is this even a walkthrough? The
# longest of the 405 in the repo when this went in was 37 words, so 60 is slack
# and nothing that hits it is a near miss on the style budget.
BACKTRACKS = ("no wait", "no, wait", "hold on", "scratch that", "still wrong",
              "that's not it", "that is not it", "not it either", "re-examine",
              "let me try", "let me reconsider", "on second thought",
              "correct parse", "actually:", "ignore that", "wait—", "wait --")
WALKTHROUGH_HARD_MAX = 60

# `definitionFit` — one sentence on why the ANSWER means the DEFINITION — became
# required on 2026-08-01 (feedback: "in the full walkthrough explain why the
# answer matches the definition"). Puzzles annotated before it existed lack it;
# see the ratchet at the bottom of this file for how they are grandfathered
# without letting a new puzzle skip it.


def check_definition_fit(tag, ann, errors, warnings):
    """Why the answer MEANS the definition — the non-mechanical half of a clue.

    Two failure modes worth catching mechanically. Thin: a handful of words that
    assert rather than explain. Backwards: the definition read out again with the
    answer swapped in ("an army ant is a crawler"), which looks like an
    explanation and teaches nothing — detectable because it contains no content
    word that isn't already in the definition or the answer.
    """
    fit = ann.get("definitionFit")
    if fit is None:
        msg = (f"{tag}: no definitionFit — say in one sentence why the answer means "
               f"the definition (tools/annotate_prompt.md)")
        warnings.append(msg)
        return
    fit = str(fit).strip()
    if len(fit) < 25:
        errors.append(f"{tag}: definitionFit {fit!r} is too thin — name the relation "
                      f"(synonym, definition by example, crossword sense), don't assert it")
        return
    if len(fit.split()) > 30:
        warnings.append(f"{tag}: definitionFit is {len(fit.split())} words — 30 max")
    known = set(re.findall(r"[a-z']+", (ann.get("definition") or "").lower()))
    known |= set(re.findall(r"[a-z']+", (ann.get("definition2") or "").lower()))
    known |= set(re.findall(r"[a-z']+", (ann.get("answer") or "").lower()))
    fresh = [w for w in re.findall(r"[a-z']+", fit.lower())
             if w not in known and w not in FILLER_WORDS and len(w) > 2]
    if len(fresh) < 3:
        errors.append(f"{tag}: definitionFit {fit!r} just restates the definition with the "
                      f"answer in it — explain WHY the two mean the same")

# An early rung must not contain the answer. The hint ladder is a ladder: rung 1
# names the family, rung 2 the definition, rung 3 the indicators, and only the
# building blocks and the walkthrough are entitled to spell the answer out. A
# field rendered above that line which names the answer collapses the ladder —
# the solver pays a hint and is handed the solve.
#
# Found 2026-08-09 by Paul, on 1392 11-across: `definitionNote` read "the setter
# defines trump cards by what their holders enjoy", printed on the DEFINITION
# rung. Sixteen notes in the corpus did the same, and the reason is structural
# rather than careless — a definitionNote exists to explain why the definition
# does not agree with the ANSWER, so it is written about the answer and always
# will be. It was moved to the walkthrough rung rather than reworded, because
# rewording would leave the next one free to make the same mistake.
#
# So this guards the fields that stay early, where naming the answer is never
# necessary and never fair. Matched with `says`, the same word-run matcher
# check_block_notes_dont_name_the_answer uses: the answer's letters have to line
# up with whole words of the field, so "trump cards" is still caught by
# TRUMPCARDS and a stray hyphen or apostrophe still cannot slip it through.
#
# This check was written first, with a bare substring test, and `says` was built
# afterwards for the sibling check precisely because a bare substring finds a
# short answer inside an unrelated longer word. The clue that proved the two
# needed to agree is everyman-4121 1A, "'Not fully overhead?' I'm never
# overhead!" — RHEA hides in ove(RHEA)d, the setter uses that word in BOTH
# halves, and so every possible definition span contains the answer's letters.
# There the letters are the clue's own, on screen from the start, and the
# definition rung adds nothing the solver could not already see; a leak is text
# the annotator WROTE that the clue does not say.
EARLY_RUNG_FIELDS = ("definition", "definition2", "indicators", "linkWords",
                     "indicatorNotes")


def check_no_answer_in_early_rungs(tag, ann, errors, warnings):
    """No field shown before the building blocks may spell out the answer."""
    ans = re.sub(r"[^a-z]", "", str(ann.get("answer") or "").lower())
    if len(ans) < 4:
        return  # too short to distinguish a leak from a coincidence
    for field in EARLY_RUNG_FIELDS:
        val = ann.get(field)
        if not val:
            continue
        parts = list(val.values()) if isinstance(val, dict) else \
            (val if isinstance(val, list) else [val])
        for part in parts:
            if says(part, ans):
                errors.append(
                    f"{tag}: {field} {part!r} contains the answer — it is shown "
                    f"before the building blocks, so it hands over the solve for "
                    f"the price of a hint. Say it in the walkthrough instead.")

def check_block_notes_dont_name_the_answer(tag, ann, errors, warnings):
    """The building blocks are a rung early too — the walkthrough is the reveal.

    The check above stops at the fields shown BEFORE the blocks, because the
    blocks rung was thought of as the place the answer lands. It is not: the
    walkthrough is, and a learner buying the blocks has deliberately not bought
    the solve. 167 notes said the word anyway — "to please is to delight" for
    PLEASE, "hidden inside st-ARGUE-sts" for ARGUE. app.js suppresses a `gives`
    that equals the answer, so only the prose can still leak.
    """
    answer = ann.get("answer")
    for block in ann.get("blocks") or []:
        if says(block.get("note"), answer):
            errors.append(
                f"{tag}: block note {block.get('note')!r} names the answer, and "
                f"the blocks are the rung before the walkthrough. Write the note "
                f"about the fragment — what it means, where its letters sit, "
                f"which convention is in play — and let the walkthrough spell it.")


# An indicator rung that names the words and not the reason is the rung solvers
# keep saying is not worth paying for ("Spot the indicator words shouldn't be
# content free clues… they would explain like minute cryptic", 2026-08-02; and
# again on 4096 20a RENOVATOR, "the indicator didn't explain why stable no was
# an indicator", 2026-08-17 — the clue is "Fixer-up ran over to stable? No", and
# "stable? No" is an anagram signal because unstable means not fixed in place,
# which the rung never said). The general sentence about what an anagram
# indicator does is the same on every clue in the corpus; the reason THIS word
# is one is the only part that teaches anything.
#
# Grandfathered the same way as definitionFit — 793 clues had indicators and no
# notes the day it was added — but only for the puzzles that already existed:
# see the ratchet at the bottom of this file.


def check_indicator_notes(tag, ann, errors, warnings):
    """Why THIS word is the indicator — one sentence per indicator."""
    inds = ann.get("indicators") or []
    notes = ann.get("indicatorNotes")
    if not inds:
        if notes:
            errors.append(f"{tag}: indicatorNotes but no indicators to explain")
        return
    if not notes:
        msg = (f"{tag}: no indicatorNotes — say in one sentence per indicator why "
               f"that word does that job (tools/annotate_prompt.md)")
        warnings.append(msg)
        return
    if not isinstance(notes, dict):
        errors.append(f"{tag}: indicatorNotes must be an object keyed by the indicator")
        return
    for key, note in notes.items():
        if key not in inds:
            errors.append(f"{tag}: indicatorNotes has {key!r}, which is not one of the "
                          f"indicators {inds!r} — the key is what gets highlighted")
        note = str(note or "").strip()
        if len(note) < 25:
            errors.append(f"{tag}: indicatorNote for {key!r} is {note!r} — too thin to "
                          f"teach; name the sense of the word that does the work")
        # "'shuffled' tells you to shuffle" is the failure this catches: a note
        # made only of words already in the indicator has restated it.
        elif not (set(words_of(note)) - set(words_of(key)) - DEFINITION_STOPWORDS):
            errors.append(f"{tag}: indicatorNote for {key!r} only says {key!r} again — "
                          f"say WHY the word means that, in words the clue does not use")
    for missing in [i for i in inds if i not in notes]:
        msg = (f"{tag}: indicator {missing!r} has no note — every indicator gets one, "
               f"or the rung is content-free for the ones that do not")
        warnings.append(msg)


SOUND_TYPES = ("homophone", "spoonerism")


def check_sound_names_its_source(tag, ann, errors, warnings):
    """A homophone must name the word you say aloud, as a field, not as prose.

    "24d in 4096 doesn't explain that the original word is hoard but it is a
    homophone and you drop the h to it. Don't just fix one clue extrapolate"
    (Paul, 2026-08-17). "Cockney mob loudly" → OARED, and the block read
    “Cockney mob” → OARED. Every step of the actual clue happened off-screen:
    a mob is a HORDE, a Cockney drops the aitch to leave ’ORDE, and ’ORDE said
    aloud is OARED. The rung asserted the answer and taught nothing — 18 of the
    corpus's 48 sound clues did the same, which is the whole point of the type
    being skipped 18 times.

    The source word cannot live only in a note, because a note is prose and
    prose is unenforceable: 4096 24d DID mention a horde in passing, buried
    mid-sentence, and it still read as a leap. So `soundsLike` is a tracked
    field on the block that does the sounding, it is required on every clue
    whose type declares a sound, and it must differ from what the block gives —
    a `soundsLike` equal to the output is not a homophone, it is a spelling.
    """
    is_sound = any(t in (ann.get("type") or "").lower() for t in SOUND_TYPES)
    heard = [b for b in ann.get("blocks", []) if b.get("soundsLike")]
    for b in heard:
        if not b.get("gives"):
            errors.append(f"{tag}: block {b.get('clueFragment')!r} has soundsLike "
                          f"{b['soundsLike']!r} but no `gives` — say what it comes out as")
        elif letters(b["soundsLike"]) == letters(b["gives"]):
            errors.append(f"{tag}: soundsLike {b['soundsLike']!r} and gives "
                          f"{b['gives']!r} are the same letters, so nothing was heard. "
                          f"A homophone is two spellings of one sound")
    if not is_sound:
        if heard:
            errors.append(f"{tag}: a block declares soundsLike but the type is "
                          f"{ann.get('type')!r} — add the sound to the type or drop the field")
        return
    if not heard:
        errors.append(
            f"{tag}: type {ann.get('type')!r} but no block says what is said aloud. "
            f"Add `soundsLike` to the block that does the sounding: the word you "
            f"HEAR is the clue's whole mechanism, and a block that jumps a "
            f"fragment straight to the answer has taught none of it")


# A real English wordlist, used to tell a genuine inflection from a coincidence:
# MARAUDING is a gerund (MARAUD is a word) but VIKING is not (VIK is not), and
# EARPHONES is a plural (EARPHONE is a word). Without it the part-of-speech
# checks fire on every answer that merely happens to end in -S or -ING.
def _load_words():
    for p in ("/usr/share/dict/words", "/usr/dict/words"):
        try:
            return {w.strip().lower() for w in open(p, encoding="utf-8", errors="ignore")}
        except OSError:
            continue
    return set()  # no dictionary here: the inflection checks quietly stand down


WORDS = _load_words()


def letters(s):
    """The A-Z letters of a string, with accents folded rather than dropped.

    A hidden word is checked against the clue's own letters, so a clue that
    spells the answer across an accented word used to fail that check outright:
    12422 23A hides PESTO in "canapés today", and stripping the É said the
    answer was not in the clue at all. The Independent and the Guardian both
    print accents (canapés, café, née), and a solver reads them as the plain
    letter — so the validator has to as well. NFD splits É into E plus a
    combining acute; the character class then keeps the E and drops the mark."""
    s = unicodedata.normalize("NFD", (s or "").upper())
    return re.sub(r"[^A-Z]", "", s)


def words_of(s):
    """Lowercase word list, with markup, the (8) enumeration and punctuation dropped.

    Guardian clue text sometimes carries literal HTML — 30046 19A and 30072 27A
    both italicise a word — and without the strip the coverage check reported
    the tag name 'span' as an unclaimed clue word. There is nothing honest to
    claim it with, because it isn't a word of the clue.
    """
    s = re.sub(r"<[^>]*>", " ", s or "")
    return re.findall(r"[a-z]+", re.sub(r"\([^)]*\)", " ", s.lower()))


# A clue may hide its answer across the join between its own words and another
# entry's SOLUTION: indysunday-1863 22D, "Spirit's teeth 16D contains", hides
# ETHOS in te(ETH OS)suary, where OSSUARY is what 16 down spells. The solver
# writes that answer into the grid and then reads the span, so the hidden-word
# check has to read it the same way — otherwise the only honest annotation of
# such a clue fails, and the annotator is pushed towards typing it as something
# it is not. Only ever ADDS letters, and only for clues already typed hidden, so
# it can only make that one check more lenient.
REFERENCE_RE = re.compile(r"\b(\d+)\s*(across|down|a|d)?\b", re.I)

# The enumeration, and nothing else in brackets. This used to be r"\([^)]*\)",
# which also deleted a parenthetical aside — and an aside is ordinary clue text
# that a hidden word may run straight through: everyman-4122 15A, "Madman seen
# in Psycho (the adaptation)", hides HOTHEAD across psyc(HO THE AD)aptation.
# Stripping the bracket said the answer was not in the clue at all, which pushes
# the annotator towards typing an honest hidden word as something it is not.
# Digits and separators only, so "(7)", "(4,6)" and "(4-6)" still go and no
# bracketed words do.
ENUMERATION_RE = re.compile(r"\([\d\s,.\-–—]+\)")


def expand_cross_references(clue, entries):
    """The clue with '16D' / '16 down' replaced by that entry's solution.

    The enumeration is stripped first, so "(5)" cannot be read as a reference to
    entry 5. A bare number is only expanded when exactly one entry carries it —
    an ambiguous one is left alone rather than guessed at, since a wrong
    expansion would let a wrong hidden claim pass.
    """
    def sub(m):
        num, direction = int(m.group(1)), (m.group(2) or "").lower()
        hits = [e for e in entries if e.get("number") == num
                and (not direction or e.get("direction", "").startswith(direction[0]))]
        return f" {hits[0].get('solution', '')} " if len(hits) == 1 else m.group(0)
    return REFERENCE_RE.sub(sub, ENUMERATION_RE.sub(" ", clue or ""))


def check_coverage(tag, ann, clue, warnings):
    """Every content word of the clue must be claimed by the parse.

    A clue word that is in neither the definition, an indicator, a link phrase,
    nor a block fragment is wordplay the annotation silently dropped (feedback
    2026-07-29: 30067 13A never accounted for 'state' = CAL, and the walkthrough
    hedged instead of admitting it)."""
    claimed = set()
    for src in [ann.get("definition"), ann.get("definition2")]:
        claimed |= set(words_of(src))
    for ind in ann.get("indicators", []):
        claimed |= set(words_of(ind))
    for lw in ann.get("linkWords", []):
        claimed |= set(words_of(lw))
    for b in ann.get("blocks", []):
        claimed |= set(words_of(b.get("clueFragment")))
    loose = [w for w in words_of(clue) if w not in claimed and w not in FILLER_WORDS]
    if loose:
        warnings.append(
            f"{tag}: clue word(s) {', '.join(sorted(set(loose)))} belong to neither the "
            f"definition, an indicator, nor a block — wordplay may be unaccounted for")


def is_word(s):
    return s.lower() in WORDS


# Words that end in S with a dictionary word in front of it, yet are not
# plurals at all: ALAS is an interjection, not more than one ALA (a wing),
# ALWAYS an adverb, not more than one ALWAY (its archaic self). LENS is one
# piece of glass, not several LENs (12444 12A). The -ICS
# academic subjects are the same trap on a bigger scale — SEMANTICS is one
# field taking a singular verb, not several SEMANTICs (30076 11A). STAPES is
# one bone in one ear, not several STAPs (30095 5D) — the Latin nominative
# happens to end in S.
# Without this the plural check invites a definitionNote that would lie —
# same principle as INVARIANT_PLURALS below, on the answer side.
NOT_PLURALS = {"ALAS", "ALWAYS", "LENS", "STAPES", "SEMANTICS", "PHYSICS", "MATHEMATICS",
               "ECONOMICS", "LINGUISTICS", "POLITICS", "ETHICS", "GENETICS",
               "ACOUSTICS", "AEROBICS", "ATHLETICS", "GYMNASTICS", "LOGISTICS",
               "MECHANICS", "OPTICS", "PHONETICS", "ROBOTICS", "STATISTICS"}


def is_plural(ans):
    """Is the answer really a plural, or does it just end in S? Checked against a
    real wordlist so PEANUTS (PEANUT) warns and CHAOS / TENNIS never do."""
    if not ans.endswith("S") or ans.endswith(("SS", "US", "IS")) or ans in NOT_PLURALS:
        return False
    return is_word(ans[:-1]) or (ans.endswith("ES") and is_word(ans[:-2]))


# Nouns that are already plural without an -S, so "aircraft" really does define
# PLANES and "cattle" really does define COWS. Without these the plural check
# fires on a perfectly fair definition and invites a definitionNote that would
# be a lie — the definition agrees with the answer, English just spells it oddly.
INVARIANT_PLURALS = {
    "aircraft", "cattle", "clergy", "crossroads", "deer", "fish", "folk",
    "grouse", "headquarters", "means", "offspring", "people", "police",
    "salmon", "series", "sheep", "species", "swine", "trout", "vermin",
    "youth", "kin", "poultry", "livestock", "personnel", "staff", "troops",
    "media", "data", "criteria", "phenomena", "bacteria", "amoebae",
    "children", "men",
    "women", "feet", "teeth", "geese", "mice", "lice", "oxen", "dice",
    # Not nouns, but the plural head of a definition all the same: "Those in
    # charge" defines RULERS and "these" and "those" carry the number on their
    # own (30051 3D). Without them the check asks for a definitionNote about a
    # mismatch that isn't there. "They print" defines PRESSES the same way
    # (12401 18A) — the pronoun is plural without an S.
    "those", "these", "they",
}


def is_gerund(ans):
    """Is the answer really an -ING form? MARAUDING is (MARAUD is a word);
    VIKING, STRING and SPRING are not, which is what made this check noisy.

    A stem has to be long enough to be a verb, too: WING scored as a gerund
    because the +E test turned its one-letter stem into WE (30052 26A), and no
    English verb is a single letter, so a one-letter stem is always the
    coincidence this check exists to ignore."""
    if not ans.endswith("ING"):
        return False
    stem = ans[:-3]
    if len(stem) < 2:
        return False
    return (is_word(stem) or is_word(stem + "E")
            or (len(stem) > 2 and stem[-1] == stem[-2] and is_word(stem[:-1])))


def check_part_of_speech(tag, ann, warnings):
    """The definition must be substitutable for the answer, which means their
    inflections agree: a plural answer needs a plural definition, an -ing answer
    an -ing definition (feedback 2026-07-29 — "the part of speech needs to be
    right"). Only the mechanical, unambiguous endings are checked here; the
    judgement call lives in STYLE.md and tools/annotate_prompt.md.

    A `definitionNote` silences this: some setters genuinely define a plural with
    a mass noun ("Lousy payment" = PEANUTS), and the honest response is to
    explain that to the learner, not to fake agreement the clue does not have."""
    ans = letters(ann.get("answer"))
    dwords = words_of(ann.get("definition"))
    if not ans or not dwords or ann.get("definitionNote"):
        return
    ends = lambda sufs: any(w.endswith(sufs) for w in dwords)
    # A long definition is usually a descriptive phrase ("About to go off perhaps"
    # = TICKING), where the -ing test says nothing; only short ones are meaningful.
    if is_gerund(ans) and len(dwords) <= 2 and not ends(("ing",)):
        warnings.append(f"{tag}: answer ends -ING but no word in the definition does "
                        f"({ann.get('definition')!r}) — check the part of speech, or "
                        f"add a definitionNote saying why it is fair")
    # Multi-word answers are phrases whose trailing -S is rarely the head's
    # inflection: PICK UP THE PIECES is a verb phrase, defined by a verb phrase.
    elif (is_plural(ans) and " " not in (ann.get("answer") or "")
          and not ends(("s",)) and not (set(dwords) & INVARIANT_PLURALS)):
        warnings.append(f"{tag}: answer looks plural but the definition "
                        f"({ann.get('definition')!r}) is not — check the part of speech, "
                        f"or add a definitionNote saying why it is fair")
    # Deliberately NOT checked: -LY (plenty of adverbs don't end in -ly: "always"),
    # and -ing definitions for non-ing answers ("Working vessel" = DREDGER is fine).
    # A noisy warning is a warning nobody reads.


def load(path):
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(JSON_START, 1)[1].rsplit(JSON_END, 1)[0])


def multiset_diff(a, b):
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    extra = "".join(sorted((ca - cb).elements()))
    missing = "".join(sorted((cb - ca).elements()))
    return extra, missing


def check_cryptic_definition_cap(entries, errors, warnings=None):
    """A puzzle may not lean on cryptic definitions (see MAX_CRYPTIC_DEFINITIONS).

    This is the one check that looks at the puzzle rather than the clue: every
    individual cryptic definition can be perfectly good and the set still be
    wrong, which is exactly how six of them got into A001 unnoticed.

    Sitting exactly ON the cap warns as well as going over it, because a
    cryptic definition is the only type an annotator can reach for without
    solving anything, which makes the count a measure of giving up. The
    2026-08-08 model benchmark is the evidence: Sonnet annotated two puzzles
    and landed on exactly 2 in both, passing by spending its whole surrender
    budget — and on 30078, where Fable's annotation of the same clues existed
    to diff against, both of its cryptic definitions turned out to be clues
    Fable had solved (9A OPERA STAR, 19D CHUKKAS = CHAS round UK + K).
    Nothing mechanical can tell a real cryptic definition from a shrug: it
    claims no letters, so it contradicts nothing. Measured on this corpus, a
    block handing over the answer catches 4 of 9, a whole-clue definition 8 of
    9, and an indicator word appearing in the clue 3 of 9 — all of them
    Fable's own correct work, so none of them is a rule. A human reading the
    two named clues is the only check there is, and this warning is how they
    get named.
    """
    cds = [f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
           for e in entries
           if (e.get("annotation") or {}).get("type") == "cryptic definition"]
    if len(cds) == MAX_CRYPTIC_DEFINITIONS and warnings is not None:
        warnings.append(
            f"puzzle: at the cryptic-definition cap ({', '.join(cds)}). Not an error, "
            f"but this is where an annotator that could not solve a clue puts it, and "
            f"nothing downstream can tell that from a real cryptic definition. Read "
            f"those two clues and satisfy yourself there is no wordplay in them")
    if len(cds) > MAX_CRYPTIC_DEFINITIONS:
        errors.append(
            f"puzzle: {len(cds)} cryptic definitions ({', '.join(cds)}) — at most "
            f"{MAX_CRYPTIC_DEFINITIONS} allowed. A cryptic definition has no checkable "
            f"wordplay, so past two the puzzle stops being solvable and starts being "
            f"guessable; find the mechanism these clues are hiding (AUTHORING.md)")


def check_cryptic_definition_blocks(tag, ann, errors, warnings):
    """A cryptic definition's blocks must split the clue, and may not spell the answer.

    The cap above asks whether a clue should be a cryptic definition at all.
    This asks a different question of the ones that legitimately are: does the
    annotation of it teach anything?

    There is exactly one block shape available to an annotator who does not
    think about it — the whole clue, giving the whole answer — and four of the
    nine cryptic definitions in the corpus had it. Rendered, that is hint 3 of
    4 reading “Might this keep you to time?” → WATCHSTRAP: the rung before it
    has just said there is no separable wordplay, and this one charges a hint
    for the solve (Paul, 1392 22-across, 2026-08-10).

    So `gives` is banned outright. A cryptic definition yields no letters from
    any fragment — that is the definition of the type — and a `gives` is
    therefore always the whole answer wearing a block's clothes.

    And a single block is banned, because a block spanning the whole clue
    restates the clue. What a cryptic definition CAN be taken apart into is
    ideas: the reading the surface pushes you towards and the reading the
    setter meant. Two blocks is the smallest annotation that shows the seam,
    and the four good ones in the corpus (NUDISM, VANITY, NINETEENTH) already
    look exactly like this. It is a presentation rule, not a lie detector: the
    clue can be a perfectly honest cryptic definition and still be annotated
    into a rung that hands over the answer.
    """
    if (ann.get("type") or "").lower() != "cryptic definition":
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
    if len(blocks) < 2:
        errors.append(
            f"{tag}: cryptic definition has {len(blocks)} block(s) — one block spans "
            f"the whole clue and so only restates it. Split the clue into the reading "
            f"the surface pushes and the reading the setter meant, one block each, so "
            f"the rung teaches the seam instead of announcing the answer")
    # Banning `gives` only closes the obvious door. Splitting the clue properly
    # and then writing the answer into a note leaks it just the same, and it is
    # the likelier mistake once the shape is right: 30039 10A VANITY split into
    # "case" and "conceitedness" and then explained them as "points to the phrase
    # 'vanity case'" and "vanity = conceitedness". Elsewhere in the corpus a block
    # note may name the answer — the blocks rung is where a charade spells it out
    # — so this is the cryptic definition's own rule, and it exists because this
    # type has no walkthrough-free way to earn it.
    ans = re.sub(r"[^a-z]", "", str(ann.get("answer") or "").lower())
    if len(ans) >= 4:
        for b in blocks:
            note = b.get("note") or ""
            if ans in re.sub(r"[^a-z]", "", note.lower()):
                errors.append(
                    f"{tag}: cryptic definition block note {note!r} spells the answer "
                    f"out, and the blocks rung is shown before the walkthrough. For "
                    f"every other type the blocks are where the answer is assembled; "
                    f"here there is nothing to assemble, so a note that names it is "
                    f"just the solve. Describe the reading, not the word")


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
DEFINITION_REUSE_EXEMPT = ("&lit", "double definition", "cryptic definition")


def check_definition_not_fodder(entries, errors, warnings):
    """The definition's words may not also be the wordplay's letters.

    A clue is two pieces — definition, optional joinery, wordplay — so a block
    that yields letters out of words the definition has already claimed is the
    annotation eating its own tail. The commonest form is a block whose fragment
    IS the definition and whose `gives` is the whole answer: "Hard rock" > HORSE.
    That says the answer is the answer, and every existing check passes it, since
    the letters concatenate and the substrings are verbatim.

    This is the hole a 2026-08-08 Haiku benchmark fell through: 29/29 annotated,
    validator OK, and 17 of 27 non-exempt clues had no real wordplay in them at
    all — wrong definitions dressed up in blocks that restated them. A model that
    cannot solve the clue can still satisfy a consistency checker, so consistency
    was never the bar; this is.

    CALIBRATION (2026-08-08, all 671 annotated clues): 4 warn, in 4 different
    puzzles, all genuine setter devices where the definition word is deliberately
    reused as fodder. None reach the cap. The Haiku run scores 17 in one puzzle.
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann or "linkedTo" in ann:
            continue
        if any(x in (ann.get("type") or "") for x in DEFINITION_REUSE_EXEMPT):
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        dw = set(re.findall(r"[a-z]+", (ann.get("definition") or "").lower()))
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
            if shared:
                hits.append(tag)
                warnings.append(
                    f"{tag}: block {frag!r} gives {b.get('gives')!r} out of "
                    f"{sorted(shared)}, which the definition {ann.get('definition')!r} "
                    f"has already claimed. A clue is definition + wordplay, not one "
                    f"phrase doing both — unless the setter reuses the word on "
                    f"purpose, this parse is faked out of the definition")
                break
    if len(hits) > MAX_DEFINITION_REUSE:
        errors.append(
            f"puzzle: {len(hits)} clues ({', '.join(hits)}) build wordplay out of "
            f"their own definition — at most {MAX_DEFINITION_REUSE} allowed. One is a "
            f"setter's device; this many means the clues were not solved, only "
            f"described. Re-annotate rather than patch")


# Mechanisms where the blocks legitimately do not add up to the answer: a
# deletion or substitution names letters that are taken away, and the three
# definition-only types plus the sound types claim no letters at all.
UNBALANCED_TYPES = ("deletion", "substitution", "cryptic definition",
                    "double definition", "homophone", "spoonerism", "&lit")

# Per puzzle, not per clue. One under-decomposed clue is a judgement call a real
# annotator makes; several is a run that stopped doing the work. Across the 671
# annotated clues here the worst puzzle has exactly one of each.
MAX_UNBALANCED = 2
MAX_UNDECOMPOSED = 2


def check_blocks_account_for_answer(entries, errors, warnings):
    """The letters the blocks hand over have to be the answer's letters.

    Not a restatement of the `pieces` check: `pieces` is the annotator's own
    summary and is checked against the answer, so a parse can have immaculate
    pieces and blocks that say something else entirely. Haiku's TRIGGER did:
    pieces T/RIG/GER, blocks T + R + IG. The blocks are what the app renders —
    they are what the learner reads — and nothing was comparing them to anything.

    CALIBRATION (2026-08-08, 489 in-scope clues): 2 warn. 30045 10A (MEME, where
    "repeated" doubles a single ME block) is the honest exception this stays a
    warning for; 30079 15D is a substitution and is now out of scope.
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann or "linkedTo" in ann:
            continue
        if any(x in (ann.get("type") or "") for x in UNBALANCED_TYPES):
            continue
        from collections import Counter
        got = "".join(letters(b.get("gives")) for b in ann.get("blocks", []))
        if not got:
            continue
        want = letters(ann.get("answer") or e.get("solution"))
        if Counter(got) != Counter(want):
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            hits.append(tag)
            extra, missing = multiset_diff(got, want)
            warnings.append(
                f"{tag}: the blocks give {got!r}, but the answer is {want!r}"
                + (f" (extra {extra!r})" if extra else "")
                + (f" (missing {missing!r})" if missing else "")
                + " — the blocks are what the learner actually reads, so they have "
                  "to be the parse, not a sketch of one")
    if len(hits) > MAX_UNBALANCED:
        errors.append(
            f"puzzle: {len(hits)} clues ({', '.join(hits)}) have blocks whose letters "
            f"are not the answer's — at most {MAX_UNBALANCED} allowed. Letters that "
            f"don't add up mean the wordplay was described rather than worked out")


def check_blocks_decompose(entries, errors, warnings):
    """If `pieces` takes the answer apart, the blocks must take it apart too.

    A charade with `pieces: ["SOD", "DEN"]` and one block reading
    `"Two types of earth" > SODDEN` has named the mechanism and then not
    performed it, which is the whole of what a learner came for. The comparison
    is free: the annotation already contains both halves and nothing checked
    that they agree.

    CALIBRATION (2026-08-08): 5 of 398 clues with 2+ pieces, one per puzzle, and
    all five are genuine under-decomposition in this repo's own annotations
    (30039 27A SODDEN, 30045 17A MUG UP, 30072 14D TOM CRUISE, 30078 18D
    TRIFLING, 1388 21A LINED). Warned, not errored, so the backlog surfaces
    without failing a build that was already green.
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann or "linkedTo" in ann:
            continue
        pieces = ann.get("pieces") or []
        if len(pieces) < 2:
            continue
        # `pieces` spelled out letter by letter — A+L+F+A, N+U+D+I+T+Y — is an
        # anagram's letter list, not a charade's chunks, and one block holding the
        # whole fodder is exactly right there. Ten of the fifteen first flagged
        # were this; a rule that lights up honest work is a broken rule.
        if all(len(letters(p)) <= 1 for p in pieces):
            continue
        full = [b for b in ann.get("blocks", [])
                if letters(b.get("gives")) == letters(ann.get("answer"))]
        lettered = [b for b in ann.get("blocks", []) if letters(b.get("gives"))]
        if full and len(lettered) == 1:
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            hits.append(tag)
            warnings.append(
                f"{tag}: pieces are {'+'.join(ann['pieces'])} but there is one block "
                f"handing over the whole answer — split it, one block per piece. "
                f"Naming a charade is not doing the charade")
    if len(hits) > MAX_UNDECOMPOSED:
        errors.append(
            f"puzzle: {len(hits)} clues ({', '.join(hits)}) name a multi-piece parse "
            f"and then give the answer in one block — at most {MAX_UNDECOMPOSED}")


# Zero, unlike its neighbours, because the backlog it found was cleared in the
# same commit that added the check (2026-08-09) and the fix is mechanical — there
# is one ordering of the blocks that spells the answer, so there is nothing to
# weigh up. A check whose corpus is clean should start its gate closed.
MAX_MISORDERED = 0


def check_blocks_in_answer_order(entries, errors, warnings):
    """A charade's blocks have to be listed in the order the answer reads.

    The app renders blocks top to bottom, so a learner reads them as the build.
    `PEAS` then `SWEET` for SWEET PEAS (1388 23A) hands over the right letters in
    the wrong order and quietly asks the learner to do the reassembly that the
    annotation exists to show. Nothing caught it: `check_blocks_account_for_answer`
    compares multisets, so a permutation passes it perfectly.

    This is the one of the four checks measured on 2026-08-08 and shelved that
    turned out to be worth having. It was shelved as "11 of 175 charades, all of
    them correct" — correct being the wrong word. The letters are correct; the
    ORDER is the teaching, and it is wrong. Backlog size is not a reason to drop
    a check (Paul, 2026-08-09), only false positives are, and re-measured under a
    tight scope there are none.

    SCOPE is the whole trick. It applies only to `type == "charade"` exactly.
    Any positional mechanism in the mix legitimately lists blocks out of final
    order: a container's inner piece goes inside rather than after, and a
    rotation is *defined* by blocks assembled before the spin — 30079 7D TSUNAMIS
    is A + MIST + SUN and only then cycled, which a looser scope flags and which
    is perfectly annotated. Widening from `charade` to "charade and nothing
    positional" adds 4 hits, 2 of them false. So it stays narrow.

    CALIBRATION (2026-08-09): 10 of 127 pure charades, every one a genuine
    misordering (1388 23A, 30039 24A, 30041 28D, 30042 8D, 30043 7D, 30044 19D,
    30078 25A, 30079 8D/11A/22A). Warned so the backlog surfaces without failing
    a build that was already green; errors past MAX_MISORDERED, because a run
    that does it repeatedly is listing blocks off the clue rather than the parse.
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann or "linkedTo" in ann:
            continue
        if (ann.get("type") or "").strip() != "charade":
            continue
        got = "".join(letters(b.get("gives")) for b in ann.get("blocks", []))
        want = letters(ann.get("answer") or e.get("solution"))
        if not got or got == want:
            continue
        from collections import Counter
        # Wrong letters are a different fault, already reported by
        # check_blocks_account_for_answer. Only a permutation is this one.
        if Counter(got) != Counter(want):
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        hits.append(tag)
        warnings.append(
            f"{tag}: the blocks read {got!r} but the answer is {want!r} — same "
            f"letters, wrong order. The app renders blocks top to bottom, so "
            f"list them in answer order and let each clueFragment point back at "
            f"wherever it sits in the clue")
    if len(hits) > MAX_MISORDERED:
        errors.append(
            f"puzzle: {len(hits)} charades ({', '.join(hits)}) list their blocks in "
            f"clue order rather than answer order — at most {MAX_MISORDERED}")


def check_blocks_carry_notes(entries, warnings):
    """A block that claims letters has to say why it gets them.

    The `note` is where the convention lives — `worker` = ANT, `setter` = ME —
    and it is the only field that can be wrong in a way the letters can't reveal.
    Haiku left 10 of its 50 letter-bearing blocks unexplained, including the ones
    it had invented. CALIBRATION: 1 of 1347 across this repo (30044 2D, `a` > A,
    where there is genuinely nothing to say). Warning only, for that reason.
    """
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann or "linkedTo" in ann:
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        for b in ann.get("blocks", []):
            if letters(b.get("gives")) and not str(b.get("note") or "").strip():
                warnings.append(
                    f"{tag}: block {b.get('clueFragment')!r} > {b.get('gives')!r} has "
                    f"no note. Say why those words give those letters — that sentence "
                    f"is the teaching, and its absence is how an invented block hides")


GLOSSARY = ROOT / "tools" / "data" / "abbreviations.json"

# A note describing what was done TO the letters, rather than what they stand
# for. "The first letter of Trout" is an operation the clue's indicator asked
# for; "ch. is the chess notation for check" is knowledge. Only the second kind
# belongs in a glossary.
OPERATION_RE = re.compile(
    r"first letter|initial|leading|opening|leader|front|head of|begins|starts? with|"
    r"beginning|last letter|final|ends? with|closing|tail|outer|outermost|extremes?|"
    r"edges|borders|vacat|empt|hollow|shell|case of|insides|middle|odd letters|"
    r"even letters|alternate|every other|regularly|occasionally|intermittently|half|"
    r"almost|endless|docked|without its|drop|lopped|cut off|stopping short|minus|"
    r"strips?|scooped|taken off|anagram|reversed|upside|said aloud|homophone|"
    r"face value|taken as|lifted|its own|start(?:ing)? letters?|introduc|poured|"
    r"keeps only", re.I)

# Words that make a fragment a compound rather than a convention: "a daughter"
# is A + D, two pieces the annotator ran together, and AD is not a table entry.
COMPOUND_HEADS = {"a", "an", "the", "of", "to", "in", "on", "and", "two", "is"}


def convention_used(ann, b):
    """The (letters, word) a block leans on as a standing convention, or None.

    Shaped, not guessed: the letters have to be an abbreviation OF the words —
    a prefix of a single word, or the initials of two — because that is what an
    abbreviation is. Everything else a block can do to letters is either a
    different shape (outer letters, odd letters) or an operation the clue asked
    for with an indicator, and both are excluded.
    """
    gives = str(b.get("gives") or "").strip().upper()
    frag = str(b.get("clueFragment") or "").strip().lower().strip("“”\"'‘’?,!.")
    if not re.fullmatch(r"[A-Z]{1,3}", gives) or len(frag) < 3:
        return None
    words = [w for w in re.split(r"[\s-]+", re.sub(r"[^a-z\s-]", "", frag)) if w]
    if not words or len(words) > 2 or words[0] in COMPOUND_HEADS:
        return None
    if "".join(words).upper() == gives:  # the clue's own letters, not a convention
        return None
    # An indicator inside the fragment means the clue is operating on those
    # words, not quoting a table.
    for ind in ann.get("indicators") or []:
        if str(ind).strip().lower() in frag:
            return None
    if OPERATION_RE.search(str(b.get("note") or "")):
        return None
    fits = (gives.lower() == "".join(words)[:len(gives)] if len(words) == 1
            else gives.lower() == "".join(w[0] for w in words))
    return (gives, " ".join(words)) if fits else None


def check_conventions_are_in_the_glossary(entries, warnings):
    """Every convention a clue leans on has to be in the solver's glossary.

    The blocks rung names a piece as a standing convention only when
    abbreviations.json holds it, so a missing entry means the hint hands over
    letters without ever saying they were the learnable kind — "look this up
    once, own it forever" reads as "think harder". The table was seeded for the
    clue-writer's assembler and had never been audited against what the corpus
    actually uses, which is how CH = check went missing.
    """
    table = json.loads(GLOSSARY.read_text())["abbreviations"]
    known = {k: {w.lower() for w in v} for k, v in table.items()}
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann or "linkedTo" in ann:
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        for b in ann.get("blocks", []):
            hit = convention_used(ann, b)
            if hit and hit[1] not in known.get(hit[0], ()):
                warnings.append(
                    f"{tag}: {hit[1]!r} = {hit[0]} is a convention the glossary does not "
                    f"have. Add it to tools/data/abbreviations.json and rerun "
                    f"tools/build_abbreviations.py, or say in the note what was done to "
                    f"the letters if it was an operation rather than a standing sense")


MARKUP_RE = re.compile(r"</?[a-zA-Z][^>]*>|&(?:[a-zA-Z]+|#\d+);")


def check_no_markup(puzzle, errors):
    """No HTML anywhere in a puzzle file. Every string here is displayed
    escaped, so a tag reaches the solver as a tag — which is exactly what the
    Independent's clues did (Paul, 2026-08-15): "<span>Film part of </span><i>
    Black Narcissus</i>?" on the page, verbatim. Both papers ship clues as
    HTML and tools/fetch_puzzle.plain_text flattens them on the way in; this
    is the guard that says so out loud if a third source, or a hand edit, ever
    puts one back.

    It also protects the hint highlighting, which locates its <mark> spans by
    character offset into the clue string: markup in the clue shifts every
    offset after it, so an annotation could no longer point at its own words.
    Walks the whole object rather than a list of fields, because the next
    field someone adds should not have to be remembered here.
    """
    for e in puzzle["entries"]:
        for r in e.get("clueItalics") or []:
            ok = (isinstance(r, list) and len(r) == 2
                  and all(isinstance(n, int) for n in r)
                  and r[0] >= 0 and r[1] > 0 and r[0] + r[1] <= len(e["clue"]))
            if not ok:
                errors.append(f"{e['id']}: clueItalics range {r!r} is not inside the "
                              f"{len(e['clue'])}-character clue. The ranges index the clue "
                              f"string, so editing one without the other silently italicises "
                              f"the wrong words.")

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
        elif isinstance(o, str):
            m = MARKUP_RE.search(o)
            if m:
                errors.append(f"{path.lstrip('.')}: HTML in text — {m.group(0)!r} in "
                              f"{o[:70]!r}. Puzzle text is displayed escaped; run it "
                              f"through fetch_puzzle.plain_text().")
    walk(puzzle, "")


def validate_puzzle(puzzle):
    errors, warnings = [], []
    check_no_markup(puzzle, errors)
    by_id = {e["id"]: e for e in puzzle["entries"]}
    annotated = 0
    authored = is_authored(puzzle)

    for e in puzzle["entries"]:
        ann = e.get("annotation")
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        if ann is None:
            warnings.append(f"{tag}: no annotation")
            continue
        annotated += 1

        if "linkedTo" in ann:
            target = by_id.get(ann["linkedTo"])
            if not target:
                errors.append(f"{tag}: linkedTo {ann['linkedTo']} does not exist")
            elif not (target.get("annotation") or {}).get("coversGroup"):
                errors.append(f"{tag}: linkedTo target is not marked coversGroup")
            continue

        clue = e["clue"]
        for key in ("type", "definition", "walkthrough", "answer", "blocks"):
            if not ann.get(key):
                errors.append(f"{tag}: missing annotation field '{key}'")

        for part in (ann.get("type") or "").split(" + "):
            if part and part not in TYPE_PARTS:
                errors.append(
                    f"{tag}: type part {part!r} not in the controlled vocabulary "
                    f"(see TYPE_PARTS in this script / STYLE.md)")

        # What letters must the wordplay produce?
        if ann.get("coversGroup"):
            target_letters = "".join(letters(by_id[gid]["solution"]) for gid in e["group"])
        else:
            target_letters = letters(e.get("solution"))
        ans_letters = letters(ann.get("answer"))
        if target_letters and ans_letters != target_letters:
            errors.append(f"{tag}: answer '{ann.get('answer')}' != grid solution {target_letters}")

        # Definition and indicators must appear verbatim in the clue.
        for field in ("definition", "definition2"):
            d = ann.get(field)
            if d and d not in clue:
                errors.append(f"{tag}: {field} {d!r} not found in clue {clue!r}")
        for ind in ann.get("indicators", []):
            if ind not in clue:
                errors.append(f"{tag}: indicator {ind!r} not found in clue {clue!r}")
        # Link words ("to locate", "indicating") join definition to wordplay and
        # carry no letters of their own — they must still be named, not ignored.
        for lw in ann.get("linkWords", []):
            if lw not in clue:
                errors.append(f"{tag}: linkWord {lw!r} not found in clue {clue!r}")
        for b in ann.get("blocks", []):
            frag = b.get("clueFragment")
            if frag and frag not in clue:
                warnings.append(f"{tag}: block fragment {frag!r} is not verbatim in clue")

        # Letter mechanics.
        if ann.get("anagram"):
            fodder = letters(ann["anagram"].get("fodder"))
            extra, missing = multiset_diff(fodder, ans_letters)
            if extra or missing:
                errors.append(
                    f"{tag}: anagram fodder {fodder} != answer {ans_letters}"
                    f" (fodder extra: {extra or '-'}, fodder missing: {missing or '-'})")
        if ann.get("pieces"):
            joined = letters("".join(ann["pieces"]))
            if joined != ans_letters:
                errors.append(f"{tag}: pieces {ann['pieces']} join to {joined}, expected {ans_letters}")
        if "hidden" in (ann.get("type") or ""):
            # A reversed hidden word sits in the clue back to front (30045 26A
            # hides LEND across "commanD NELson"), so when the type also declares
            # the reversal, the mirror image counts as found.
            clue_letters = letters(expand_cross_references(clue, puzzle["entries"]))
            reversed_ok = ("reversal" in ann["type"]
                           and ans_letters[::-1] in clue_letters)
            if ans_letters not in clue_letters and not reversed_ok:
                errors.append(f"{tag}: hidden answer {ans_letters} not found inside clue letters")
        if not (ann.get("anagram") or ann.get("pieces")
                or "hidden" in (ann.get("type") or "")
                or "definition" in (ann.get("type") or "")
                or "homophone" in (ann.get("type") or "")):
            warnings.append(f"{tag}: no machine-checkable assembly (pieces/anagram) provided")

        # A definitionNote silences the part-of-speech check, so it has to say
        # something: a one-word "fine" would turn the check into an off switch.
        note = ann.get("definitionNote")
        if note is not None and len(str(note).strip()) < 25:
            errors.append(f"{tag}: definitionNote {note!r} is too thin — explain to the "
                          f"learner why the mismatch is fair, or drop the note")

        check_definition_fit(tag, ann, errors, warnings)
        check_sound_names_its_source(tag, ann, errors, warnings)
        check_indicator_notes(tag, ann, errors, warnings)
        check_no_answer_in_early_rungs(tag, ann, errors, warnings)
        check_block_notes_dont_name_the_answer(tag, ann, errors, warnings)
        check_cryptic_definition_blocks(tag, ann, errors, warnings)

        check_coverage(tag, ann, clue, warnings)
        check_part_of_speech(tag, ann, warnings)
        if authored:
            check_two_pieces(tag, ann, errors)
            check_walkthrough_budget(tag, ann, warnings)
            check_link_words_are_equivalences(tag, ann, errors)
            check_indicator_adjacency(tag, ann, clue, errors, warnings)
            check_indicator_outside_fodder(tag, ann, clue, errors)
            check_reversal_direction(tag, ann, e["direction"], errors)
        walk = ann.get("walkthrough") or ""
        low = walk.lower()
        for h in HEDGES:
            if h in low:
                errors.append(f"{tag}: walkthrough hedges with {h!r} — parse the chunk "
                              f"properly instead of excusing it (STYLE.md)")
        if len(walk.split()) > WALKTHROUGH_HARD_MAX:
            errors.append(f"{tag}: walkthrough is {len(walk.split())} words "
                          f"(max {WALKTHROUGH_HARD_MAX}) — that length is working-out, "
                          f"not an explanation; the blocks already did the mechanics")
        # Notes and definitionFit are published too, so they get the same check.
        for field, text in ([("walkthrough", walk),
                             ("definitionFit", ann.get("definitionFit") or "")]
                            + [("block note", b.get("note") or "")
                               for b in ann.get("blocks", [])]):
            for marker in BACKTRACKS:
                if marker in text.lower():
                    errors.append(f"{tag}: {field} contains {marker!r} — that is "
                                  f"working-out, not an explanation. Settle the parse "
                                  f"first, then write the finished sentence")

        for sub in ann.get("subAnagrams", []):
            extra, missing = multiset_diff(letters(sub["fodder"]), letters(sub["gives"]))
            if extra or missing:
                errors.append(f"{tag}: subAnagram {sub['fodder']} !~ {sub['gives']}")
        for sub in ann.get("subReversals", []):
            if letters(sub["from"])[::-1] != letters(sub["to"]):
                errors.append(f"{tag}: subReversal {sub['from']} reversed != {sub['to']}")

    if annotated:
        check_cryptic_definition_cap(puzzle["entries"], errors, warnings)
        check_definition_not_fodder(puzzle["entries"], errors, warnings)
        check_blocks_account_for_answer(puzzle["entries"], errors, warnings)
        check_blocks_decompose(puzzle["entries"], errors, warnings)
        check_blocks_in_answer_order(puzzle["entries"], errors, warnings)
        check_blocks_carry_notes(puzzle["entries"], warnings)
        check_conventions_are_in_the_glossary(puzzle["entries"], warnings)

    return annotated, errors, warnings


# --- the ratchet -------------------------------------------------------------
#
# "Don't just fix the things I point out, make sure future puzzles get the fixes
# too" (Paul, 2026-08-17). A rule added after 150 puzzles were already annotated
# cannot fail the corpus on day one, so the old shape was a REQUIRE_X = False
# flag to be flipped by hand once a backfill drained the backlog. That makes the
# rule optional for exactly the puzzles it was invented for — the next ones —
# and it stays optional for as long as anyone forgets.
#
# So the allowance is per puzzle and written down. A puzzle may carry as many
# unannotated clues as annotation_backlog.json records for it and not one more;
# a puzzle not in the file — which is every puzzle fetched from today on — is
# allowed none. The backlog can only ever shrink: a full run rewrites the file
# with what it observed, so draining a puzzle tightens the rule on it forever.
# Adding a new grandfathered field means adding it to BACKLOG_MARKERS and
# running --tighten once; nothing has to be remembered afterwards.
BACKLOG_PATH = ROOT / "tools" / "annotation_backlog.json"
BACKLOG_MARKERS = {
    "definitionFit": ("no definitionFit",),
    "indicatorNotes": ("no indicatorNotes", "has no note"),
}


def load_backlog():
    if not BACKLOG_PATH.exists():
        return {}
    data = json.loads(BACKLOG_PATH.read_text())
    return {f: data.get(f, {}) for f in BACKLOG_MARKERS}


def count_backlog(warnings):
    return {f: sum(any(m in w for m in ms) for w in warnings)
            for f, ms in BACKLOG_MARKERS.items()}


def _sort_key(kv):
    """Series, then number. The key is a namespaced id ("cryptic-30041"), and
    this used to be int(id) — which raised the moment ids stopped being bare
    numbers. Nobody saw it, because the one caller ran with output suppressed
    and `|| true`; see the note on that call in prereset_backfill.sh."""
    series, _, num = kv[0].rpartition("-")
    return (series, int(num) if num.isdigit() else 0, kv[0])


def write_backlog(observed, allowed):
    """`observed` is {number: {field: count}} from a run over every puzzle.

    Writes the SMALLER of what was observed and what was already allowed, per
    puzzle per field. "May only shrink" was a sentence in a comment and a line
    in the file's own _why, and neither of them is a mechanism: --tighten wrote
    whatever it saw, so a run that lost annotations would raise the ceiling to
    fit them and every run after it would agree the puzzle was fine."""
    ratchet = {f: {num: min(c[f], allowed.get(f, {}).get(num, c[f]))
                   for num, c in observed.items()} for f in BACKLOG_MARKERS}
    data = {"_why": "Per-puzzle allowance of clues predating a required annotation "
                    "field. Written by tools/validate_annotations.py; may only "
                    "shrink. A puzzle absent from a field's list must have none.",
            **{f: {num: n for num, n in sorted(ratchet[f].items(), key=_sort_key)
                   if n} for f in BACKLOG_MARKERS}}
    BACKLOG_PATH.write_text(json.dumps(data, indent=1) + "\n")


def main(argv):
    global FORCE_AUTHORED_CHECKS
    if "--unscoped" in argv:
        FORCE_AUTHORED_CHECKS = True
        argv = [a for a in argv if a != "--unscoped"]
        print("--unscoped: authoring rules applied to published puzzles too. This is "
              "CALIBRATION — every hit is either a broken check or a rare setter's "
              "liberty, and the default reading is the former.")
    tighten = "--tighten" in argv
    argv = [a for a in argv if a != "--tighten"]
    if argv:
        paths = [resolve_puzzle(a) for a in argv]
    else:
        paths = puzzle_files()
    full_run = not argv
    allowed = load_backlog()
    observed = {}
    failed = False
    for path in paths:
        if not path.exists():
            print(f"MISSING {path}")
            failed = True
            continue
        puzzle = load(path)
        annotated, errors, warnings = validate_puzzle(puzzle)
        total = len(puzzle["entries"])
        if annotated == 0 and not argv:
            # Nothing to check about annotations that do not exist yet — but
            # the checks that walk the whole file (markup) do apply, and
            # dropping them here would exempt exactly the puzzles nobody has
            # looked at.
            print(f"{puzzle['id']}: unannotated ({total} clues) — skipped")
            for err in errors:
                print(f"  ERROR: {err}")
            failed = failed or bool(errors)
            continue
        # The ratchet: this puzzle may be short exactly as many notes as the
        # file already records for it. Everything annotated from now on is
        # absent from the file, so its allowance is zero and the rule bites.
        counts = count_backlog(warnings)
        observed[path.stem] = counts
        for field, n in counts.items():
            cap = allowed.get(field, {}).get(path.stem, 0)
            if n > cap:
                errors.append(
                    f"{n} clue(s) with no {field}, and this puzzle is allowed {cap} — "
                    f"{field} is required on everything annotated since it was added "
                    f"(tools/annotate_prompt.md). The warnings above name them.")
        status = "OK" if not errors else "FAIL"
        print(f"{puzzle['id']} ({puzzle['setter']}): {annotated}/{total} annotated — {status}")
        for w in warnings:
            if annotated:
                print(f"  warn: {w}")
        for err in errors:
            print(f"  ERROR: {err}")
        if errors:
            failed = True
    # Printed as one number rather than 400 warning lines' worth of noise, and
    # printed even when everything passes: a backlog nobody sees is a backlog
    # nobody drains. Only a FULL run can total it — a single-puzzle run counts
    # only its own clues.
    if full_run:
        for field in BACKLOG_MARKERS:
            total = sum(c[field] for c in observed.values())
            print(f"\n{field} backlog: {total} clue(s) in {sum(1 for c in observed.values() if c[field])} "
                  f"puzzle(s)." if total else f"\n{field} backlog is EMPTY — every puzzle now carries it.")
        # Only a full run has visited every puzzle, so only a full run may
        # rewrite the file — and only when asked, because widening the
        # allowance is how a regression would get itself forgiven.
        moved = {f: sum(allowed.get(f, {}).values()) - sum(c[f] for c in observed.values())
                 for f in BACKLOG_MARKERS}
        if tighten and failed:
            # A failing run is the one run that must never record its own state:
            # what it saw includes whatever it is failing about, and recording
            # that is how a regression gets itself forgiven forever.
            print("NOT tightening: this run failed, so what it observed is not a "
                  "ceiling worth keeping. Fix the errors above and re-run.")
        elif tighten:
            write_backlog(observed, allowed)
            print("wrote tools/annotation_backlog.json: "
                  + ", ".join(f"{f} -{n}" if n >= 0 else f"{f} unchanged (observed {abs(n)} more, "
                              f"kept the tighter cap)" for f, n in moved.items()))
        elif any(v > 0 for v in moved.values()):
            print("backlog shrank (" + ", ".join(f"{f} -{n}" for f, n in moved.items() if n > 0)
                  + ") — run `python3 tools/validate_annotations.py --tighten` to record it, "
                    "or those clues can silently go missing again.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
