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
  - a reversal indicator points the way the entry runs (check_reversal_direction)

And one whole-puzzle check:
  - at most MAX_CRYPTIC_DEFINITIONS clues typed "cryptic definition"

Usage: python3 tools/validate_annotations.py [--unscoped] [puzzle-number ...]
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUZZLE_DIR = ROOT / "puzzles"
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
    # letter-movement mechanisms: a rotation that keeps letter order (30079 7D
    # TSUNAMIS = A MIST SUN cycled), and a swap of one indicated letter for
    # another (30079 15D LAUGH LINE = TAUGHT IN E with Ls covering the Ts)
    "cycling", "substitution",
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

    Authored puzzles get IDs starting with a letter (A001) — the convention
    tools/build_authored_puzzle.py already uses. The distinction matters because
    the checks below are AUTHORING rules, not annotation rules: real setters
    pad their surfaces and write long clues, and an annotation of a published
    grid has to be able to record that faithfully."""
    return FORCE_AUTHORED_CHECKS or not str(puzzle.get("id", ""))[:1].isdigit()


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
# answer matches the definition"). The 14 hand-annotated puzzles predate it, so
# absence is a WARNING with a running backlog count printed at the end of a full
# run. Flip this to True the moment that count reaches zero; leaving it False
# once the backfill is done turns a rule into a suggestion, and the whole point
# of putting checks here is that feedback stops depending on anyone remembering.
REQUIRE_DEFINITION_FIT = False


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
        (errors if REQUIRE_DEFINITION_FIT else warnings).append(msg)
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
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def words_of(s):
    """Lowercase word list, with markup, the (8) enumeration and punctuation dropped.

    Guardian clue text sometimes carries literal HTML — 30046 19A and 30072 27A
    both italicise a word — and without the strip the coverage check reported
    the tag name 'span' as an unclaimed clue word. There is nothing honest to
    claim it with, because it isn't a word of the clue.
    """
    s = re.sub(r"<[^>]*>", " ", s or "")
    return re.findall(r"[a-z]+", re.sub(r"\([^)]*\)", " ", s.lower()))


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
# plurals at all: ALAS is an interjection, not more than one ALA (a wing).
# Without this the plural check invites a definitionNote that would lie —
# same principle as INVARIANT_PLURALS below, on the answer side.
NOT_PLURALS = {"ALAS"}


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
    "media", "data", "criteria", "phenomena", "bacteria", "children", "men",
    "women", "feet", "teeth", "geese", "mice", "lice", "oxen", "dice",
}


def is_gerund(ans):
    """Is the answer really an -ING form? MARAUDING is (MARAUD is a word);
    VIKING, STRING and SPRING are not, which is what made this check noisy."""
    if not ans.endswith("ING"):
        return False
    stem = ans[:-3]
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


def check_cryptic_definition_cap(entries, errors):
    """A puzzle may not lean on cryptic definitions (see MAX_CRYPTIC_DEFINITIONS).

    This is the one check that looks at the puzzle rather than the clue: every
    individual cryptic definition can be perfectly good and the set still be
    wrong, which is exactly how six of them got into A001 unnoticed."""
    cds = [f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
           for e in entries
           if (e.get("annotation") or {}).get("type") == "cryptic definition"]
    if len(cds) > MAX_CRYPTIC_DEFINITIONS:
        errors.append(
            f"puzzle: {len(cds)} cryptic definitions ({', '.join(cds)}) — at most "
            f"{MAX_CRYPTIC_DEFINITIONS} allowed. A cryptic definition has no checkable "
            f"wordplay, so past two the puzzle stops being solvable and starts being "
            f"guessable; find the mechanism these clues are hiding (AUTHORING.md)")


def validate_puzzle(puzzle):
    errors, warnings = [], []
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
            clue_letters = letters(clue)
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

        check_coverage(tag, ann, clue, warnings)
        check_part_of_speech(tag, ann, warnings)
        if authored:
            check_two_pieces(tag, ann, errors)
            check_walkthrough_budget(tag, ann, warnings)
            check_link_words_are_equivalences(tag, ann, errors)
            check_indicator_adjacency(tag, ann, clue, errors, warnings)
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
        check_cryptic_definition_cap(puzzle["entries"], errors)

    return annotated, errors, warnings


def main(argv):
    global FORCE_AUTHORED_CHECKS
    if "--unscoped" in argv:
        FORCE_AUTHORED_CHECKS = True
        argv = [a for a in argv if a != "--unscoped"]
        print("--unscoped: authoring rules applied to published puzzles too. This is "
              "CALIBRATION — every hit is either a broken check or a rare setter's "
              "liberty, and the default reading is the former.")
    if argv:
        paths = [PUZZLE_DIR / f"{a}.js" for a in argv]
    else:
        paths = sorted(PUZZLE_DIR.glob("[0-9]*.js"))
    failed = False
    fit_backlog = 0
    for path in paths:
        if not path.exists():
            print(f"MISSING {path}")
            failed = True
            continue
        puzzle = load(path)
        annotated, errors, warnings = validate_puzzle(puzzle)
        total = len(puzzle["entries"])
        if annotated == 0 and not argv:
            print(f"{puzzle['id']}: unannotated ({total} clues) — skipped")
            continue
        status = "OK" if not errors else "FAIL"
        print(f"{puzzle['id']} ({puzzle['setter']}): {annotated}/{total} annotated — {status}")
        for w in warnings:
            if annotated:
                print(f"  warn: {w}")
        for err in errors:
            print(f"  ERROR: {err}")
        if errors:
            failed = True
        fit_backlog += sum("no definitionFit" in w for w in warnings)
    # Printed as one number rather than 400 warning lines' worth of noise, and
    # printed even when everything passes: this is a backlog that has to reach
    # zero before REQUIRE_DEFINITION_FIT can be flipped, and a backlog nobody
    # sees is a backlog nobody drains.
    if fit_backlog:
        print(f"\ndefinitionFit backlog: {fit_backlog} clue(s) still have no explanation of "
              f"why the answer means the definition. Flip REQUIRE_DEFINITION_FIT at zero.")
    elif not REQUIRE_DEFINITION_FIT and not argv:
        # Only a FULL run can prove the backlog empty — a single-puzzle run
        # counts only its own clues, and saying "empty" there once prompted a
        # premature flip that broke every backfill puzzle (2026-08-07).
        print("\ndefinitionFit backlog is EMPTY — set REQUIRE_DEFINITION_FIT = True now.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
