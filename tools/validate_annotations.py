#!/usr/bin/env python3
"""Validate clue annotations in puzzles/<series>/<year>/*.json.

Checks, for every annotated entry:
  - annotation has type, definitions, answer, blocks
  - `type` is an array of names from tools/data/clue_types.json (check_type)
  - answer letters match the grid solution (group-aware for linked entries)
  - each definition sits at its `at` in the clue (tools/definitions.py), every
    indicator and every linkWord is an exact substring of the clue, and every content word of the clue is claimed by one
    of those or by a block (check_coverage)
  - each definition and the answer agree in inflection, unless the definition's
    `note` explains why they don't (check_part_of_speech)
  - assembly: "pieces" concatenate exactly to the answer letters, each of
    "anagrams" is a letter-for-letter anagram of its gives, and each of
    "reversals" reverses correctly
  - hidden answers actually occur in the clue's letters, and an answer that
    runs across a word break in the wordplay, or sits inside one word other
    than at the front, back or middle a deletion or selection keeps, is typed
    hidden_word unless a note calls it a coincidence (check_unmarked_hidden_word)
  - a linked answer's `group` sits on its leader alone, leader first, and its
    other lights carry no annotation (check_groups)

And checks that apply only to puzzles we WROTE (see is_authored):
  - every clue states its scene in explanation.surface, without crossword
    vocabulary or the answer (check_authored_surface)
  - a clue tagged as a pun names its word (check_authored_puns)
  - no block may have an empty `gives`: every word of an authored clue is
    definition, wordplay or joinery, never surface padding (check_two_pieces)
  - the walkthrough stays inside MAX_WALKTHROUGH_WORDS when the blocks already
    spell the answer out (check_walkthrough_budget)
  - every linkWord stands in for an equals sign (check_link_words_are_equivalences)
  - and does not secretly order the wordplay (check_link_word_is_not_an_order)
  - an anagram indicator touches its fodder (check_indicator_adjacency)
  - and is not made of the fodder's own letters (check_indicator_outside_fodder)
  - no indicator runs across a definition's edge (check_indicator_does_not_straddle_a_definition)
  - a reversal indicator points the way the entry runs (check_reversal_direction)

And checks that need the whole puzzle in hand:
  - at most MAX_CRYPTIC_DEFINITIONS clues typed cryptic_definition
  - a definition's words are not also its wordplay's letters
  - the blocks hand over exactly the answer's letters, take it apart the way
    `assembly.pieces` does, and are listed in the order the answer reads
  - a block that claims letters says why it gets them
  - every convention a block leans on is in the solver's glossary

Usage: python3 tools/validate_annotations.py [--unscoped] [--tighten] [puzzle-number ...]
With no arguments, validates every puzzle that has at least one annotation.
`--unscoped` runs the authored-only checks on published puzzles too — that is
the CALIBRATION harness, not a mode to ship in: a check that flags Araucaria is
a broken check, so every authored-only rule is measured across the eight
annotated Guardian puzzles before it is trusted. Exits non-zero if any check
fails.
"""

import ast
import collections
import functools
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import clue_types  # noqa: E402
import definitions  # where each definition sits; tools/definitions.py
import enumeration  # noqa: E402 — a clue's printed counts; tools/enumeration.py
import groups  # noqa: E402 — linked answers; tools/groups.py
import puzzle_schema  # noqa: E402 — tools/data/puzzle.schema.json
from annotation import assembly, explanation, whole_anagram, wordplay_letters
from fetch_puzzle import (  # noqa: E402 — one reader, one exemption
    blog_facts_for,
    clue_words,
    leaders_named,
    read_puzzle_file,
)
from find_answer_leaks import light_solutions, named, pieces_of, says  # noqa: E402 — one matcher, shared with the finder
from groups import entry_id  # noqa: E402
from puzzle_paths import (  # noqa: E402 — one glob, one id resolver
    puzzle_files,
    resolve_puzzle,
)

# The controlled vocabulary for `type`: an array of names from
# tools/data/clue_types.json, naming EVERY mechanism the wordplay uses in the
# order it is applied (see STYLE.md — "honest types"). A letter_selection says
# which letters on the block that keeps them, as `select`.
TYPE_NAMES = clue_types.NAMES


def types_of(ann):
    """The annotation's type array; check_type reports anything else."""
    t = ann.get("type")
    return t if isinstance(t, list) else []


def indicator_texts(ann, kind=None):
    """The clue words of each indicator object; check_indicators reports bad shapes.

    With `kind`, only the indicators whose `for` is that type, plus those with
    no `for`, which could signal any of the clue's types."""
    return [i["text"] for i in ann.get("indicators") or []
            if isinstance(i, dict) and isinstance(i.get("text"), str)
            and (kind is None or i.get("for") in (None, kind))]


def check_type(tag, ann, errors):
    """`type` is a non-empty array of distinct names from clue_types.json, and a
    letter_selection has at least one block saying which letters (`select`)."""
    t = ann.get("type")
    if not isinstance(t, list) or not t:
        errors.append(
            f"{tag}: type must be a non-empty array of names from tools/data/"
            f"clue_types.json, e.g. [\"charade\", \"reversal\"]; got {t!r}")
        return
    for name in t:
        if name not in TYPE_NAMES:
            errors.append(
                f"{tag}: type {name!r} is not in the controlled vocabulary "
                f"({', '.join(TYPE_NAMES)}). The list is closed and this run "
                f"cannot extend it, so if no name fits, the parse is wrong: find "
                f"the mechanism the list does name")
    if len(set(t)) != len(t):
        errors.append(f"{tag}: type {t!r} names a mechanism twice; list each once")
    selects = [b["select"] for b in ann.get("blocks") or [] if "select" in b]
    for v in selects:
        if not clue_types.valid_select(v):
            errors.append(
                f"{tag}: block select {v!r} is not one of "
                f"{', '.join(clue_types.SELECT_WORDS)} or a letter position 2..20")
    if "letter_selection" in t and not selects:
        errors.append(
            f"{tag}: type has letter_selection but no block says which letters. "
            f"Put `select` on the block that keeps them: "
            f"{', '.join(clue_types.SELECT_WORDS)}, or n for the nth letter")
    if selects and "letter_selection" not in t:
        errors.append(f"{tag}: a block has `select` but type {t!r} has no "
                      f"letter_selection — add it or drop the field")


# A cryptic definition has no checkable mechanism: the solver either sees the
# joke or is stuck. One or two per puzzle is a treat, more is a quiz. It exists
# because OUR authoring pass drifts over it: chasing a funny surface produced
# six in one rewrite of A001, since a funny sentence is far easier to find than
# a funny mechanism (feedback 2026-07-29: "they don't have wordplay anymore").
# See AUTHORING.md, "The sentence AND the wordplay".
#
# The cap is a HARD limit on authored puzzles and only a warning on fetched
# ones, because a published setter's count is a fact about their puzzle and not
# a budget we get to set. Measured over the 331 annotated puzzles in puzzles/:
# 200 carry no cryptic definitions, 89 carry one, 42 carry two. Nothing carried
# three until quiptic-1372 (Harpo), which genuinely has five — and because the
# cap was an error there, the annotator solved all five and then shipped three
# of them BLANK to stay under it. A blank clue teaches nothing and no check
# could see it, so the cap was buying a silent failure at the price of a loud
# one. check_every_clue_is_annotated is the loud one now.
MAX_CRYPTIC_DEFINITIONS = 2


# "A good cryptic clue doesn't have anything superfluous which isn't directly
# part of the wordplay. It should be exactly two pieces. Definition, optional
# joinery and wordplay." (feedback 2026-07-29). A word that exists only to make
# the surface read nicely is a fault, and in this schema it has exactly one
# signature: a block with an empty `gives`, i.e. "surface only" padding.
#
# A walkthrough budget for the companion rule: "When you basically give the whole
# answer in the building blocks you don't need to have the full walkthrough."
# 45 sits above the 99th percentile: across 74,474 published walkthroughs with
# blocks (2026-09-28) the median is 19 words, p90 32, p99 40, and 0.1% run over
# 45. The A001 set that prompted the feedback ran 44-63 with a median of 54.
MAX_WALKTHROUGH_WORDS = 45

# Opening formulas that spend the first clause on something other than the clue.
# Anchored at the start and kept to fixed phrasings on purpose — the same words
# are unremarkable once the sentence is under way, and a matcher that chased
# them there would fire on half the corpus. Counts are from the 6,403 published
# walkthroughs on 2026-09-06, which is what makes these the shapes worth naming
# rather than every stiff opening anyone can imagine.
WALKTHROUGH_PREAMBLE = [
    (r"(An?|The)\s+(lovely|neat|nice|classic|clean|tidy|elegant|simple|pretty|smart|"
     r"clever|gentle|fiddly|textbook|standard|straightforward)\b[^.]*?:",
     "an appraisal of the clue, where the reader wants the clue"),
    (r"As\s+\w+\s+as\s+[^.]*?\bcomes?\b[^.]*?:",
     "a verdict on how hard it is, which the reader can judge themselves"),
    # Only when the thing being counted is machinery. "Two instructions stacked:"
    # announces a structure the next clause is about to show anyway; "Two ordinary
    # trade words are wearing capital letters:" counts something in the CLUE and is
    # the trick itself. Both open with a number, so the number is not the tell.
    (r"(Two|Three|Four|Both)\s+(\w+\s+){0,2}"
     r"(instruction|mechanism|step|device|operation|stage|move|thing)s?\b[^.]*?:",
     "a table of contents for a sentence one line long"),
]
# "This is a ..." was a fourth pattern and was cut after measuring it: all three
# corpus hits were contrastive — "This is a rotation, not a reversal" — which is
# the trick stated, not a preamble to it. A check that warns on good sentences
# gets ignored on the bad ones.

# Closing sentences that grade the walkthrough instead of continuing it. The
# predicate list is what makes these empty: "the whole difficulty", "the whole
# joke" are the reader's own reaction handed back, whereas "It is only the first
# letter going" ends on the same grammar and names a mechanism, so it must not
# match. Both patterns require a demonstrative subject pointing BACK at the
# sentence just written; that back-reference is the defect, not the wording.
WALKTHROUGH_EMPTY_CLOSER = [
    (r"(That|This|Those|These|Both|It)\b[\w' ’-]{0,45}?\b(is|are)\b[\w' ]{0,10}?"
     r"\b(whole|entire|only|real)\b(\s+of\s+the)?\s+\w{0,10}\s?"
     r"(difficulty|clue|trick|trap|point|joke|disguise|misdirection|wordplay|"
     r"instruction|deception|challenge|game)\b",
     "a verdict on the sentence before it, not a fact about the clue"),
    (r"(That|This|Those|These|Both|It)\b[\w' ’-]{0,45}?"
     r"\b(send|sends|lead|leads|take|takes|carry|carries|push|pushes|steer|"
     r"steers|walk|walks|march|marches)\b[^.]{0,45}?"
     r"\b(past|by|away|off|astray|elsewhere)\b",
     "a restatement that the trap is a trap, which the reader worked out from "
     "the trap"),
]


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
    happens to contain the answer.

    A pure cryptic definition is exempt: the whole clue is its definition, so no
    word is padding, and its blocks are the two readings with no `gives` at all
    (check_cryptic_definition_blocks forbids one)."""
    if types_of(ann) == ["cryptic_definition"]:
        return
    for b in ann.get("blocks", []):
        if not str(b.get("gives") or "").strip():
            frag = b.get("clueFragment") or "(no fragment)"
            errors.append(
                f"{tag}: block {frag!r} has an empty 'gives' — surface padding is not "
                f"allowed in a clue we wrote. Every word must be definition, wordplay "
                f"or joinery: rewrite the clue without it, or work out which job it is "
                f"really doing (AUTHORING.md, 'Exactly two pieces')")


def check_walkthrough_opener(tag, ann, warnings):
    """The walkthrough opens with the trick, not with an appraisal of the trick.

    The app prints this paragraph under the label "The trick", so an opening
    clause spent rating the clue — "A lovely match of surface and answer:",
    "As simple as charades come:" — puts the label and the first words at odds,
    and 2026-09-06 feedback was that the sentence "sounds weird". The other
    shape is a table of contents for a sentence one line long: "Two instructions
    stacked:" announces a structure the reader can already see.

    Only fixed opening formulas are matched, and only at the very start. That is
    deliberate: "two" and "simple" are ordinary words in the middle of a
    walkthrough and this must not chase them there. A warning, not an error —
    the sentence after the preamble is usually fine, so this asks for a cut, not
    a rewrite."""
    wt = (explanation(ann).get("walkthrough") or "").strip()
    if not wt:
        return
    for pat, why in WALKTHROUGH_PREAMBLE:
        m = re.match(pat, wt, re.I)
        if m:
            warnings.append(
                f"{tag}: walkthrough opens with {m.group(0).strip()!r} — {why}. "
                f"Cut the preamble and start with the trick itself; the app has "
                f"already labelled the paragraph 'The trick'")
            return


def check_walkthrough_closer(tag, ann, warnings):
    """The last sentence carries a fact, not a verdict on the sentence before it.

    Two shapes say nothing: "That switch is the whole difficulty" restates the
    trick just described and grades it, and "Both readings send you straight past
    the letters" restates that a trap is a trap. Both are the reader's own
    conclusion handed back to them — 2026-09-06 feedback on everyman-4167 22A was
    that "the last sentence was just useless".

    Matched only as a whole final sentence and only with an abstract predicate.
    "It is only the first letter going" and "It is only an equals sign, joining
    the definition to the two chunks" survive on purpose: they name a mechanism,
    which is a fact. A warning — the cure is deleting the sentence, and where the
    walkthrough has room, spending it on the surface joke instead."""
    wt = (explanation(ann).get("walkthrough") or "").strip()
    sents = [s for s in re.split(r"(?<=[.!?])\s+", wt) if s.strip()]
    if len(sents) < 2:
        return
    for pat, why in WALKTHROUGH_EMPTY_CLOSER:
        if re.match(pat, sents[-1], re.I):
            warnings.append(
                f"{tag}: walkthrough ends on {sents[-1]!r} — {why}. Cut it, or "
                f"spend the sentence on something the reader does not have yet: "
                f"what the surface is saying, or why the answer fits the "
                f"definition")
            return


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
    wt = (explanation(ann).get("walkthrough") or "").split()
    has_blocks = any(b.get("gives") or b.get("note") for b in ann.get("blocks", []))
    if has_blocks and len(wt) > MAX_WALKTHROUGH_WORDS:
        warnings.append(
            f"{tag}: walkthrough is {len(wt)} words with a building-blocks rung above it "
            f"(budget {MAX_WALKTHROUGH_WORDS}) — cut whatever the blocks already say and "
            f"keep only what they cannot show (STYLE.md, 'the blocks already told them')")


# A link word stands in for an equals sign. CORE_LINKS states the rule: it may
# assert equivalence (is, are, 's), derivation (gives, makes, becomes, yields,
# leads to, means, indicates, to locate), plain prepositional joining (for,
# from, of, in, with, by, as, after) or be grammatical glue holding those
# together. Anything else is a content word doing surface work, i.e. padding
# wearing a link word's coat, and it makes the clue a THREE-piece clue.
#
# What real setters use beyond the core is measured, not typed:
# tools/build_clue_joints.py adds every word published clues declare as a link
# word often enough (tools/data/clue_joints.json), and the nightly keeps it current.
CORE_LINKS = frozenset({
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
})

JOINTS_FILE = Path(__file__).resolve().parent / "data" / "clue_joints.json"


@functools.cache
def joints():
    """tools/data/clue_joints.json, read on first use so its builder can import this."""
    return json.loads(JOINTS_FILE.read_text())


def link_vocabulary():
    """Every word that may stand for an equals sign: the core plus measured use."""
    return CORE_LINKS | set(joints()["linkWords"])


def check_link_words_are_equivalences(tag, ann, errors):
    """A link word has to stand in for an equals sign (feedback 2026-07-30).

    "lives on" does not. It joins nothing and asserts nothing; it is surface
    padding wearing a link word's coat, and declaring it in `linkWords` makes
    the annotation look sound while the clue is quietly in three pieces —
    wordplay, PADDING, definition. That is the same fault check_two_pieces
    catches when the annotator is honest enough to file it as a block with an
    empty `gives`; this check closes the other door.

    CALIBRATION (unscoped, 74,474 annotated published clues, 2026-09-28):
    published annotations declare 24,755 link-word phrases. The core plus the
    measured words from tools/build_clue_joints.py cover 96.1% of their tokens;
    the rest is a long tail, no word in it used more than nine times.

    The rule bites on our own clues, where it caught three of twenty: `would be
    better spent` (THERE), `mistake it for` (LEADERSHIP), `lives on` (STOREY).
    None of `lives`, `mistake`, `spent` or `better` is ever declared a link word
    in a published clue. A word published setters do use gets in by measurement,
    not by hand."""
    for lw in ann.get("linkWords", []):
        vocab = link_vocabulary()
        bad = [t for t in words_of(lw) if t not in vocab]
        if bad:
            errors.append(
                f"{tag}: linkWord {lw!r} is not a link word — {', '.join(bad)} asserts no "
                f"equivalence between wordplay and definition. A link word stands in for an "
                f"equals sign (is/gives/makes/for/from/'s); anything else is padding, and a "
                f"clue with padding is in three pieces, not two (AUTHORING.md, 'Link words "
                f"are an equals sign'). Rewrite the clue; tools/build_clue_joints.py adds a word once "
                f"published setters use it")


POSITIONAL_JOINERS = {"on", "after", "behind", "below", "beneath", "under",
                      "following", "supporting"}


def check_link_word_is_not_inside_an_indicator(tag, ann, clue, errors):
    """A link word needs a copy of its own in the clue, clear of every indicator.

    app.js claims link words after indicators, so a connective the clue uses
    twice ("in" inside the indicator and "in" linking) lands on the free copy.
    With no free copy it lands on the indicator, wholly or in part, and takes
    those words off a hint the solver has paid for: times-29616 6D filed "of"
    inside "on top of", everyman-3925 4D filed "'s written" across "written
    about". tools/smoke_test.js rejects the render; this rejects the annotation
    before it is committed.
    """
    clue = clue or ""
    placed = place_fragments(ann, clue)
    inds = [(i, i + len(t)) for kind, t, i in placed if kind == "ind"]
    for kind, lw, i in placed:
        if kind == "link" and any(i < d and c < i + len(lw) for c, d in inds):
            errors.append(
                f"{tag}: linkWord {lw!r} has no copy in the clue clear of the indicators, "
                f"so marking it as a link takes words off an indicator. Each clue word "
                f"is either indicator or link; drop it from one list")


def place_fragments(ann, clue):
    """Where app.js placedFragments() puts each fragment: (kind, text, index).

    A copy of the app's rule, because the check above is only true if it agrees
    with the render. Definitions claim their stored `at`; the rest take the best
    occurrence still free, longest first, link words last. Ranking is whole word
    and free, then whole word, then free, earliest on a tie. An edge binds only
    where it is a letter, so "'s" may weld to the word before it.
    """
    is_letter = lambda c: c.isascii() and c.isalpha()
    frags = [("def", d.get("text"), d.get("at")) for d in ann.get("definitions") or []
             if isinstance(d, dict)]
    frags += [("ind", t, None) for t in indicator_texts(ann)]
    frags += [("link", t, None) for t in ann.get("linkWords") or [] if isinstance(t, str)]
    frags = [(k, t, at, n) for n, (k, t, at) in enumerate(frags) if t]
    taken, placed = [], []
    free = lambda i, n: not any(i < j + m and j < i + n for j, m in taken)
    for k, t, at, _ in frags:
        if at is None:
            continue
        if isinstance(at, int) and at >= 0 and clue[at:at + len(t)] == t:
            taken.append((at, len(t)))
            placed.append((k, t, at))

    def best(t):
        n, best_i, best_r = len(t), -1, 9
        i = clue.find(t)
        while i >= 0:
            edge = lambda x, y: x < len(clue) and y >= 0 and is_letter(clue[x]) and is_letter(clue[y])
            b = not edge(i, i - 1) and not edge(i + n, i + n - 1)
            f = free(i, n)
            r = 0 if b and f else 2 if b else 3 if f else 4
            if r < best_r:
                best_i, best_r = i, r
            i = clue.find(t, i + 1)
        return best_i

    rest = sorted((f for f in frags if f[2] is None),
                  key=lambda f: (f[0] == "link", -len(f[1]), f[3]))
    for k, t, _, _ in rest:
        i = best(t)
        if i >= 0:
            taken.append((i, len(t)))
            placed.append((k, t, i))
    return placed


def check_indicator_does_not_straddle_a_definition(tag, ann, clue, errors):
    """An indicator may not straddle a definition's edge.

    Inside a definition is an &lit, and app.js nests the marks. Across its edge
    the marks collide, one of them cannot be shown, and a hint the solver bought
    leaves the screen: independent-12233 3D filed "in the
    middle of" as the indicator and "of the sea" as the definition.
    tools/smoke_test.js rejects the render; this rejects the annotation first.
    """
    spans = []
    for d in ann.get("definitions") or []:
        t = d.get("text") or ""
        at = d.get("at", clue.find(t))
        if t and at is not None and at >= 0:
            spans.append((at, at + len(t)))
    for ind in indicator_texts(ann):
        hits = [m.start() for m in re.finditer(re.escape(ind), clue)] if ind else []
        if hits and all(any(i < e and i + len(ind) > s and not s <= i < i + len(ind) <= e
                                for s, e in spans) for i in hits):
            errors.append(
                f"{tag}: indicator {ind!r} runs across the edge of the definition, so the "
                f"two cannot both be marked. Take the shared words off one of them")


def check_link_word_is_not_an_order(tag, ann, clue, warnings):
    """A link word that put the pieces in that order is an indicator.

    Reported 2026-09-16 against 30,099 25A, "Post on half of wage when things
    are developing": the annotation filed `on` under linkWords, so the page told
    the solver it "contributes no letters of its own" and nothing anywhere said
    why the post ends up at the BACK of the answer. It ends up there because of
    `on` — across the grid, one thing written on another has been reached after
    it. The word carries the only instruction in the clue, and it was filed as
    furniture.

    Flagged only where the joiner is demonstrably the thing that did the
    reordering: two blocks listed in the opposite order from the clue, the
    joiner sitting between them, and no declared indicator between them to take
    the blame instead. A container or reversal that shuffles the blocks past
    each other therefore clears the joiner, which is the point — `model in
    Channel Islands on ecstasy` (everyman-4093 9A) is reordered by `in`, and
    `on` there really is joinery.

    CALIBRATION (2026-09-16, the whole corpus): 65 entries declare a positional
    joiner as a link word and 12 of them list blocks out of clue order, but only
    3 survive the two conditions above — 30,099 25A and indysunday-1885 14A and
    25A. All three are real, and the two Filbert ones are the proof: their
    walkthroughs SAY "in an across clue one thing 'on' another sits after it"
    and file `on` as a link word in the same breath. All three fixed with this
    rule. A warning, because three is a thin sample for an error."""
    joiners = [w for w in ann.get("linkWords", [])
               if w.strip().lower() in POSITIONAL_JOINERS]
    if not joiners:
        return
    blocks = [b for b in ann.get("blocks", []) if b.get("gives") and b.get("clueFragment")]
    pos = [clue.find(b["clueFragment"]) for b in blocks]
    if len(pos) < 2 or any(p < 0 for p in pos):
        return
    ind_at = [clue.find(i) for i in indicator_texts(ann)]
    for a in range(len(pos) - 1):
        if pos[a] <= pos[a + 1]:
            continue
        lo, hi = pos[a + 1], pos[a]
        if any(lo < p < hi for p in ind_at):
            continue
        for w in joiners:
            m = re.search(r"\b%s\b" % re.escape(w.strip()), clue, re.I)
            if not m or not lo < m.start() < hi:
                continue
            warnings.append(
                f"{tag}: the clue reads {blocks[a + 1]['clueFragment']!r} then "
                f"{blocks[a]['clueFragment']!r} and the answer takes them the other "
                f"way round, with linkWord {w!r} standing between them and no "
                f"indicator that could have done it — so {w!r} is what reversed them, "
                f"and a word that orders the wordplay is an indicator, not an equals "
                f"sign. Move it to `indicators` as {{\"text\": {w!r}, \"for\": ..., \"note\": ...}} "
                f"with a note saying which piece it sends second")
            return


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

    Note this is NOT the withdrawn advice in AUTHORING.md about indicator
    placement. That one said do not put the indicator next to the fodder, as a
    style preference, and was killed by measurement (88.9% of published anagrams
    do exactly that). This says the opposite thing about a different subject: it
    is a soundness rule, and the measurement supports it.

    CALIBRATION (unscoped, 74,474 annotated published clues, 2026-09-28):
    10,201 anagram clues with an indicator; 9,914 have a locatable fodder span
    and 24 of those are flagged (0.24%), each with a content word in the gap
    that reads as an annotation slip (`ecstasy`, `oxygen`, `daughter`). With
    the old hand list of articles and short prepositions there were 95, and
    the extra 71 had link words in the gap (`when` 15, `after` 14, `get` 7).
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

    CALIBRATION (2026-09-29, 14,898 anagram steps in published puzzles):
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


# A word, with any apostrophe or hyphen inside it: "friend's" and
# "ham-fistedly" are one word each. tools/build_authored_puzzle.py reads
# hidden words with it too.
HIDDEN_WORD_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")


def hidden_runs(clue, ann):
    """Where the answer, forwards or reversed, spells itself across a word break
    in the clue words outside every definition: (direction, words) pairs, the
    direction "forwards" or "reversed" and the words the run crosses. A run of
    whole words is not hidden (ASTI reverses "It's a" outright), so it is not
    reported."""
    answer = letters(ann.get("answer"))
    if len(answer) < 3:
        return []
    spans = [(d["at"], d["at"] + len(d["text"])) for d in ann.get("definitions") or []
             if isinstance(d, dict) and isinstance(d.get("at"), int)
             and isinstance(d.get("text"), str)]
    runs = []
    # A definition breaks the text into stretches; a run may not cross one.
    cuts = sorted(spans) + [(len(clue), len(clue))]
    start = 0
    for a, b in cuts:
        stretch = clue[start:a] if a > start else ""
        start = max(start, b)
        text, word, words = [], [], []
        for n, m in enumerate(HIDDEN_WORD_RE.finditer(stretch)):
            words.append(m.group())
            for ch in letters(m.group()):
                text.append(ch)
                word.append(n)
        text = "".join(text)
        targets = [("forwards", answer)]
        if answer != answer[::-1]:
            targets.append(("reversed", answer[::-1]))
        for direction, target in targets:
            for i in range(len(text) - len(target) + 1):
                j = i + len(target) - 1
                whole = ((i == 0 or word[i - 1] != word[i])
                         and (j + 1 == len(text) or word[j + 1] != word[j]))
                if text.startswith(target, i) and word[i] != word[j] and not whole:
                    run = (direction, " ".join(words[word[i]:word[j] + 1]))
                    if run not in runs:
                        runs.append(run)
    return runs


def inside_runs(clue, ann):
    """Where the answer, forwards or reversed, sits inside one clue word outside
    every definition without being all of it: (direction, word, left, right)
    tuples, left and right the counts of the word's letters on either side.
    A possessive's 's is not part of the word, so REMARK reversing "Kramer's"
    is a whole-word reversal."""
    answer = letters(ann.get("answer"))
    if len(answer) < 3:
        return []
    spans = [(d["at"], d["at"] + len(d["text"])) for d in ann.get("definitions") or []
             if isinstance(d, dict) and isinstance(d.get("at"), int)
             and isinstance(d.get("text"), str)]
    runs = []
    for m in HIDDEN_WORD_RE.finditer(clue):
        if any(m.start() < b and a < m.end() for a, b in spans):
            continue
        word = letters(re.sub(r"['’]s$", "", m.group(), flags=re.IGNORECASE))
        for direction, target in (("forwards", answer), ("reversed", answer[::-1])):
            if direction == "reversed" and target == answer:
                continue
            k = word.find(target)
            while k >= 0 and len(target) < len(word):
                run = (direction, m.group(), k, len(word) - k - len(target))
                if run not in runs:
                    runs.append(run)
                k = word.find(target, k + 1)
    return runs


# The devices that take a fixed stretch of one word: a deletion or selection
# keeps its front or back ("endless", "half", "first three") or its middle
# ("heart of", "uncovered", "centre"). An odd leftover puts the middle one
# letter off centre.
POSITIONAL_TYPES = {"deletion", "letter_selection"}


def trimmed_pieces(ann, words):
    """Whether blocks clue the run's words one by one, each giving its word whole
    or the front or back a deletion or selection keeps: APE from "a pet" as A +
    PE(T)."""
    frags = {letters(b.get("clueFragment")): letters(b.get("gives"))
             for b in ann.get("blocks") or [] if isinstance(b, dict)}
    for w in words.split():
        w, g = letters(w), frags.get(letters(w))
        if not g or not (w.startswith(g) or w.endswith(g)):
            return False
    return True


def check_unmarked_hidden_word(tag, ann, clue, errors):
    """An answer that spells itself across a word break in the wordplay is a
    hidden word, and its type says so, unless a block or indicator note says the
    run is a coincidence: pieces clued one by one that happen to sit side by
    side (TO + T in "to time", ILL + S in "will start").

    The same goes for an answer inside one word (TAR in "starting"), unless the
    type has a deletion or letter selection and the answer is the word's front,
    back or middle, the stretches those devices keep (TOSH as the heart of
    "Photoshop's", EXPO from "Sexpot stripped").

    CALIBRATION (published annotations, 2026-09-30): 57 of 85,250 hit it; 27
    were hidden words typed as something else (EGRET reversed in "after
    getting", ROUTINE in "Soldier out in Egypt"), 30 were coincidences. Inside
    one word, 82 non-hidden annotations hold the answer; 71 are a deletion's or
    selection's front, back or middle, and the other 11 were coincidences (TAR
    in "starting", PRESS opening "pressure")."""
    types = set(types_of(ann))
    if "hidden_word" in types:
        return
    notes = [str(x.get("note") or "") for key in ("blocks", "indicators")
             for x in ann.get(key) or [] if isinstance(x, dict)]
    if any("coinciden" in n.lower() for n in notes):
        return
    def fix(direction):
        return ("`hidden_word` and `reversal`" if direction == "reversed"
                else "`hidden_word`")
    positional = POSITIONAL_TYPES & types
    for direction, words in hidden_runs(clue, ann):
        if positional and direction == "forwards" and trimmed_pieces(ann, words):
            continue
        errors.append(
            f"{tag}: the answer runs {direction} across {words!r}, outside the "
            f"definition, but `type` has no hidden_word. Add {fix(direction)} to "
            f"`type` if the setter hid it there, or say in the note of the block "
            f"holding those words that it is a coincidence")
    for direction, word, left, right in inside_runs(clue, ann):
        if positional and (not left or not right or abs(left - right) <= 1):
            continue
        errors.append(
            f"{tag}: the answer sits {direction} inside {word!r} ({left} letters "
            f"before it, {right} after), outside the definition, but `type` has no "
            f"hidden_word. A deletion or letter selection keeps a word's front, back "
            f"or middle; a run anywhere else is a hidden word. Add {fix(direction)} "
            f"to `type` with {word!r} as the block, or say in that block's note "
            f"that it is a coincidence")


# A reversal runs along the entry, so the indicator has to name the entry's own
# direction. Which words name an axis is measured: tools/build_clue_joints.py
# binds a word to one when published reversal clues almost never use it on the
# other (`west` across, `up` down). Every other word is direction-neutral.


def check_reversal_direction(tag, ann, direction, errors):
    """A reversal indicator must point the way the entry runs.

    An across answer reads right to left when it is reversed, so `west`,
    `east` or `aback` fit it. A down answer reads bottom to top, so `up`,
    `rising`, `raised`, `climbing` or `north` fit it. Which words bind to an
    axis is measured by tools/build_clue_joints.py.

    CALIBRATION (published annotations, 2026-09-28): the convention is
    lopsided. Vertical words almost never reverse an across entry (`up` 2 of
    168 single-word uses). Horizontal words reverse down entries all the time:
    `back` sits on a down entry in 25 of 170 single-word uses and `returning`
    in 17 of 72. So `back` is neutral, not horizontal. With the measured lists,
    25 of 2,087 axis-word reversals cross over (1.2%), against 250 of 3,237 (7.7%) with
    the July hand lists, which bound `back` and `returning` to across.

    Only declared indicators are examined, and only on clues whose type or
    assembly.reversals say a reversal happens, so an ordinary `up` elsewhere in the
    surface is not the check's business (30039 11A reverses UP itself)."""
    if "reversal" not in types_of(ann) and not assembly(ann).get("reversals"):
        return
    wrong = set(joints()["vertical" if direction == "across" else "horizontal"])
    axis = ("an across entry reads right to left when reversed, so it wants "
            "west / east / aback"
            if direction == "across" else
            "a down entry reads bottom to top, so it wants up / rising / "
            "raised / climbing / north")
    for ind in indicator_texts(ann, "reversal"):
        hits = [w for w in words_of(ind) if w in wrong]
        if hits:
            errors.append(
                f"{tag}: reversal indicator {ind!r} points the wrong way for a "
                f"{direction} entry ({', '.join(hits)}) — {axis}, or a neutral word "
                f"such as turning, about or over (AUTHORING.md, "
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
# The surface is one sentence of picture. A warning, not an error: a long one is
# still better than a missing one.
SURFACE_MAX = 25
# A clue this short, or one that is nothing but definitions, may paint no
# picture apart from its mechanism (`Flat (4)`), so its surface is optional.
SURFACE_MIN_WORDS = 4
SURFACE_OPTIONAL_TYPES = {"double_definition", "cryptic_definition"}
WORD_RE = re.compile(r"[\w'’\-]+")


def check_surface(tag, ann, clue, warnings):
    """Every clue of SURFACE_MIN_WORDS or more words carries a `surface`,
    unless it is a pure double or cryptic definition, where the clue itself is
    the picture. Warned, and required through the ratchet: puzzles annotated
    before the rule are grandfathered in annotation_backlog.json."""
    if "surface" in explanation(ann) or set(types_of(ann)) <= SURFACE_OPTIONAL_TYPES:
        return
    words = WORD_RE.findall(clue or "")
    if len(words) >= SURFACE_MIN_WORDS:
        warnings.append(f"{tag}: no explanation.surface — say in one sentence (25 words max) what "
                        f"the clue pretends to be about; a clue of {len(words)} words "
                        f"paints a picture")

# A clue we set starts from its scene, so `surface` is where the scene is
# stated, in the world's words, before any mechanism exists. Published
# surfaces use crossword vocabulary in 1.6% of 11,695 clues, so a surface that
# needs it is describing the machinery, not the picture.
SURFACE_MECHANISM = re.compile(
    r"(?i)\b(anagram|indicator|fodder|letters?|revers|hidden|charade|container|"
    r"wordplay|definition|homophone|deletion|abbreviation|clue|answer|setter|solver)\w*")


def check_authored_surface(tag, ann, clue, errors):
    """Every clue we set states its scene in `surface`, and the scene is not the
    mechanism. No word-count or type exemption: a cryptic definition's scene is
    its joke, and a four-word clue still pretends to say something."""
    surface = (explanation(ann).get("surface") or "").strip()
    if not surface:
        errors.append(f"{tag}: no explanation.surface — a clue we set starts from its scene: "
                      f"say in one sentence what the clue is about, with no crossword in "
                      f"mind, before choosing the mechanism (AUTHORING.md, 'The surface is "
                      f"a sentence, and it carries a joke')")
        return
    hit = SURFACE_MECHANISM.search(surface)
    if hit:
        errors.append(f"{tag}: surface {surface!r} says {hit.group(0)!r} — that is the "
                      f"mechanism, not the scene. State what the sentence is about as a "
                      f"reader with no crossword in mind would")
    answer = re.sub(r"[^a-z]", "", (ann.get("answer") or "").lower())
    if len(answer) > 2 and answer in re.sub(r"[^a-z ]", "", surface.lower()).split():
        errors.append(f"{tag}: surface {surface!r} names the answer; the scene is what the "
                      f"clue pretends to say, and the answer is what it hides")


def check_authored_puns(entries, errors):
    """A pun in a puzzle we set names its word.

    A `pun` lives in one word's second sense, so it must name that word in
    `features.misdirectedWord`; a pun nobody can point at is not one."""
    for e in entries:
        feats = (e.get("annotation") or {}).get("features") or {}
        if feats.get("joke") == "pun" and not feats.get("misdirectedWord"):
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            errors.append(f"{tag}: features.joke is pun but no misdirectedWord — name the "
                          f"word whose second sense carries the pun")


# `definitionFit` — one sentence on why the ANSWER means the DEFINITION — became
# required on 2026-08-01 (feedback: "in the full walkthrough explain why the
# answer matches the definition"). Puzzles annotated before it existed lack it;
# see the ratchet at the bottom of this file for how they are grandfathered
# without letting a new puzzle skip it.


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
    filed = sorted({s["at"] for s in seps if s["mark"] not in ("'", "\u2019")})
    if breaks != filed:
        errors.append(
            f"{tag}: answer {answer!r} breaks after {breaks}, but the paper "
            f"divides this light after {filed} — respell the answer so the "
            f"letter strip puts its gaps where the enumeration does")


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
    word that isn't already in the definition or the answer.
    """
    fit = explanation(ann).get("definitionFit")
    if fit is None:
        msg = (f"{tag}: no explanation.definitionFit — say in one sentence (30 words max) why the "
               f"answer means the definition. {DEFINITION_FIT_HOW}")
        warnings.append(msg)
        return
    fit = str(fit).strip()
    if len(fit) < 25:
        errors.append(f"{tag}: definitionFit {fit!r} is too thin. {DEFINITION_FIT_HOW}")
        return
    if len(fit.split()) > 30:
        warnings.append(f"{tag}: definitionFit is {len(fit.split())} words — 30 max")
    known = set(re.findall(r"[a-z']+", " ".join(definitions.texts(ann)).lower()))
    known |= set(re.findall(r"[a-z']+", (ann.get("answer") or "").lower()))
    fresh = [w for w in re.findall(r"[a-z']+", fit.lower())
             if w not in known and w not in FILLER_WORDS and len(w) > 2]
    if len(fresh) < 3:
        errors.append(f"{tag}: definitionFit {fit!r} just restates the definition with the "
                      f"answer in it. {DEFINITION_FIT_HOW}")

# An early rung must not contain the answer. The hint ladder is a ladder: the
# spotting rungs name the indicators, the definition and the family, and only the
# building blocks and the walkthrough are entitled to spell the answer out. A
# field rendered above that line which names the answer collapses the ladder —
# the solver pays a hint and is handed the solve.
#
# Found 2026-08-09 by Paul, on 1392 11-across: a definition's `note` read "the setter
# defines trump cards by what their holders enjoy", printed on the DEFINITION
# rung. Sixteen notes in the corpus did the same, and the reason is structural
# rather than careless — a definition's note exists to explain why the definition
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
EARLY_RUNG_FIELDS = ("definitions", "indicators", "linkWords")


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

    The check above stops at the fields shown BEFORE the blocks, because the
    blocks rung was thought of as the place the answer lands. It is not: the
    walkthrough is, and a learner buying the blocks has deliberately not bought
    the solve. app.js suppresses a `gives` that equals the answer, so only the
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
        errors.append(
            f"{tag}: block note {block.get('note')!r} names {what}, and "
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
    if no_note and len(no_note) == len(texts):
        warnings.append(f"{tag}: no indicator notes — give every indicator a `note`. "
                        f"{INDICATOR_NOTE_HOW}")
    else:
        for text in no_note:
            warnings.append(f"{tag}: indicator {text!r} has no note — every indicator "
                            f"gets one. {INDICATOR_NOTE_HOW}")


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
    is_sound = any(t in types_of(ann) for t in SOUND_TYPES)
    heard = [b for b in ann.get("blocks", []) if b.get("soundsLike")]
    for b in heard:
        if not b.get("gives"):
            errors.append(f"{tag}: block {b.get('clueFragment')!r} has soundsLike "
                          f"{b['soundsLike']!r} but no `gives` — say what it comes out as")
        elif letters(b["soundsLike"]) == letters(b["gives"]):
            errors.append(f"{tag}: soundsLike {b['soundsLike']!r} and gives "
                          f"{b['gives']!r} are the same letters, so nothing was heard. "
                          f"A homophone is two spellings of one sound")
        elif letters(b["soundsLike"]) == letters(ann.get("answer") or ""):
            errors.append(f"{tag}: soundsLike {b['soundsLike']!r} is the answer itself, "
                          f"and the blocks rung prints it before the walkthrough. "
                          f"soundsLike is the word you say aloud and gives is what it "
                          f"comes out as: swap them (soundsLike {b['gives']!r}, gives "
                          f"{b['soundsLike']!r})")
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
            f"fragment straight to the answer has taught none of it. The note "
            f"carries the step before the sound: \"Cockney mob loudly\" -> OARED is "
            f"soundsLike ’ORDE, gives OARED, the note saying a mob is a HORDE and a "
            f"Cockney drops the aitch. A mechanism feeding the sound gets its own "
            f"earlier block")


def check_sound_is_not_a_letter_swap(tag, ann, errors, warnings):
    """A spoonerism trades SOUNDS. A soundsLike made by trading letters is a fake.

    "I have no idea how you get nought to oubt" (quiptic 1398 9A, 2026-09-07).
    That clue's blocks gave DOUGH and NOUGHT, and a third block then declared
    the pair sounded like "NOUGH DOUGHT" — a string arrived at by exchanging the
    two words' first LETTERS and re-spelling nothing else. It is not a word, not
    a pronunciation and not anything the solver can say aloud, so the rung ended
    at a piece of gibberish and the reader was left to leap from it to NO DOUBT
    unaided. Spooner swaps the opening sounds: "doh" and "nawt" become "noh" and
    "dawt", which are then SPELT NO and DOUBT, and the respelling is the lesson.

    The tell is arithmetic. When a sounded form uses exactly the letters the
    earlier blocks already gave, only in a different order, no sound was
    recorded — the annotator shuffled characters between the chunks. The corpus
    was measured before this landed: 3 hits in 328 sound clues (quiptic-1398 9A
    "NOUGH DOUGHT", independent-12412 5D "FOG BOE", indysunday-1871 13A "FONE
    CALL"), all three the same defect, all three fixed in the same commit as
    two-block exchanges. A sounded form that legitimately restates the earlier
    blocks — everyman-4134's SOLELY + HE -> "SOLELY HE" — is those letters in
    the SAME order, and is left alone.
    """
    blocks = ann.get("blocks", [])
    for i, b in enumerate(blocks):
        said = letters(b.get("soundsLike") or "")
        if not said:
            continue
        prior = "".join(letters(x.get("gives") or "") for x in blocks[:i])
        if prior and said != prior and sorted(said) == sorted(prior):
            errors.append(
                f"{tag}: soundsLike {b['soundsLike']!r} is the earlier blocks' own "
                f"letters ({prior}) rearranged, so it records a letter swap and not "
                f"a sound. Give each half of the answer its own block — the word it "
                f"sounds like before the swap, and the letters it comes out as after")


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
# The one-letter forms are written tight against the number ("16d"); spelt out,
# the direction may be spaced ("16 down"). Allowing a space before a bare "a"
# reads "from 26 a penny" as a reference to 26 across, which does not exist,
# and the reference is then dropped instead of expanded.
REFERENCE_RE = re.compile(r"\b(\d+)(?:\s*(across|down)|([ad]))?\b", re.I)

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
        num = int(m.group(1))
        direction = (m.group(2) or m.group(3) or "").lower()

        def find(d):
            return [e for e in entries if e.get("number") == num
                    and (not d or e.get("direction", "").startswith(d[0]))]

        hits, tail = find(direction), ""
        # "26 a penny" is not 26 across: a direction that names no entry at that
        # number is an ordinary word of the clue, so the bare number is tried
        # again on its own and the word is handed back to the clue (12373 16A
        # hides CHEAP across 26 down's solution and the a of a penny).
        if not hits and direction:
            hits, tail = find(""), (m.group(2) or m.group(3) or "")
        if len(hits) != 1:
            return m.group(0)
        return f" {hits[0].get('solution', '')} {tail} "
    return REFERENCE_RE.sub(sub, ENUMERATION_RE.sub(" ", clue or ""))


def check_coverage(tag, ann, clue, warnings):
    """Every content word of the clue must be claimed by the parse.

    A clue word that is in neither the definition, an indicator, a link phrase,
    nor a block fragment is wordplay the annotation silently dropped (feedback
    2026-07-29: 30067 13A never accounted for 'state' = CAL, and the walkthrough
    hedged instead of admitting it)."""
    claimed = set()
    for src in definitions.texts(ann):
        claimed |= set(words_of(src))
    for ind in indicator_texts(ann):
        claimed |= set(words_of(ind))
    for lw in ann.get("linkWords", []):
        claimed |= set(words_of(lw))
    for b in ann.get("blocks", []):
        claimed |= set(words_of(b.get("clueFragment")))
    loose = [w for w in words_of(clue) if w not in claimed and w not in FILLER_WORDS]
    if loose:
        warnings.append(
            f"{tag}: clue word(s) {', '.join(sorted(set(loose)))} belong to neither the "
            f"definition, an indicator, a linkWord nor a block's clueFragment. A leftover "
            f"word is one of: a link word; an indicator you missed; a letter you never "
            f"named (a deletion needs a block for the letter removed, `hard` = H); or "
            f"surface padding, recorded as a block with an empty `gives` and a note "
            f"saying so")


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
# Without this the plural check invites a definition note that would lie —
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
# fires on a perfectly fair definition and invites a definition note that would
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
    # own (30051 3D). Without them the check asks for a definition note about a
    # mismatch that isn't there. "They print" defines PRESSES the same way
    # (12401 18A) — the pronoun is plural without an S.
    "those", "these", "they",
}


# Nouns ending in -ING whose stem happens to be a word without the noun ever
# being a verb form: an AWN is the bristle on an ear of barley, so AWNING
# passes the stem test below and is still a plain noun fairly defined by a
# plain noun (30103 6D, "Canopy"). STRING is here for the same reason, and it
# is in the docstring below as an example the stem test handles — it does not.
# Same reasoning as NOT_PLURALS above: a warning on one of these invites a
# definition note explaining a mismatch that does not exist.
NOT_GERUNDS = {"AWNING", "STRING", "HERRING", "SHILLING", "CEILING", "MORNING",
               "PUDDING"}


def is_gerund(ans):
    """Is the answer really an -ING form? MARAUDING is (MARAUD is a word);
    VIKING, STRING and SPRING are not, which is what made this check noisy.

    A stem has to be long enough to be a verb, too: WING scored as a gerund
    because the +E test turned its one-letter stem into WE (30052 26A), and no
    English verb is a single letter, so a one-letter stem is always the
    coincidence this check exists to ignore."""
    if not ans.endswith("ING") or ans in NOT_GERUNDS:
        return False
    stem = ans[:-3]
    if len(stem) < 2:
        return False
    return (is_word(stem) or is_word(stem + "E")
            or (len(stem) > 2 and stem[-1] == stem[-2] and is_word(stem[:-1])))


JOKE_KINDS = ("pun", "absurd")


def check_features(tag, ann, clue, errors, warnings):
    """The `features` block is data, not teaching, and is checked like data.

    Absent is warned, and required through the ratchet: puzzles annotated
    before the block existed are grandfathered in annotation_backlog.json.
    Present means every key is present and typed, because
    the whole value of the block is that a missing row and a false row mean
    different things when these get counted against the favourite votes.

    `misdirectedWord` must be a single word that actually occurs in the clue.
    Naming a word the setter never wrote is the one failure mode that would
    quietly poison the count rather than shrink it, so it is an error.
    """
    feats = ann.get("features")
    if feats is None:
        warnings.append(f"{tag}: no features — add the block: misdirectedWord, joke, "
                        f"answerInScene, aptDefinition (false, or leave out misdirectedWord "
                        f"and joke, where there is none)")
        return
    if not isinstance(feats, dict):
        errors.append(f"{tag}: features must be an object, got {type(feats).__name__}")
        return

    for key in ("answerInScene", "aptDefinition"):
        if key not in feats:
            errors.append(f"{tag}: features.{key} is missing — write false rather "
                          f"than leaving it out, they are counted separately")
        elif not isinstance(feats[key], bool):
            errors.append(f"{tag}: features.{key} must be true or false, "
                          f"got {feats[key]!r}")

    joke = feats.get("joke")
    if joke is not None and joke not in JOKE_KINDS:
        errors.append(f"{tag}: features.joke must be one of "
                      f"{', '.join(JOKE_KINDS)} or left out, got {joke!r}")

    word = feats.get("misdirectedWord")
    if word is not None:
        if not isinstance(word, str) or not word.strip():
            errors.append(f"{tag}: features.misdirectedWord must be a word from "
                          f"the clue or left out, got {word!r}")
        elif len(word.split()) > 1:
            errors.append(f"{tag}: features.misdirectedWord {word!r} is more than "
                          f"one word — name the single word that misleads")
        elif not re.search(r"(?<!\w)" + re.escape(plain(word.strip())) + r"(?!\w)", plain(clue or "")):
            errors.append(f"{tag}: features.misdirectedWord {word!r} does not occur "
                          f"in the clue {clue!r}")


def plain(text):
    """`text` lowercased with curly apostrophes straightened, for matching a
    word the annotation names against the clue it came from."""
    return text.lower().replace("\u2019", "'").replace("\u2018", "'")


def check_part_of_speech(tag, ann, warnings):
    """The definition must be substitutable for the answer, which means their
    inflections agree: a plural answer needs a plural definition, an -ing answer
    an -ing definition (feedback 2026-07-29 — "the part of speech needs to be
    right"). Only the mechanical, unambiguous endings are checked here; the
    judgement call lives in STYLE.md and tools/annotate_prompt.md.

    A definition's `note` silences this for it: some setters genuinely define a
    plural with a mass noun ("Lousy payment" = PEANUTS), and the honest response
    is to explain that to the learner, not to fake agreement the clue does not
    have."""
    ans = letters(ann.get("answer"))
    for d in ann.get("definitions") or []:
        dwords = words_of(d.get("text"))
        if not ans or not dwords or d.get("note"):
            continue
        ends = lambda sufs: any(w.endswith(sufs) for w in dwords)  # noqa: B023
        # A long definition is usually a descriptive phrase ("About to go off
        # perhaps" = TICKING), where the -ing test says nothing; only short ones
        # are meaningful.
        if is_gerund(ans) and len(dwords) <= 2 and not ends(("ing",)):
            warnings.append(f"{tag}: answer ends -ING but no word in the definition does "
                            f"({d.get('text')!r}). The definition must substitute "
                            f"for the answer in a sentence: say the swap out loud. If it "
                            f"does not, the definition is probably a different span of the "
                            f"clue; if the setter really is loose, give the definition a "
                            f"`note` saying in a sentence why that is fair")
        # Multi-word answers are phrases whose trailing -S is rarely the head's
        # inflection: PICK UP THE PIECES is a verb phrase, defined by a verb phrase.
        elif (is_plural(ans) and " " not in (ann.get("answer") or "")
              and not ends(("s",)) and not (set(dwords) & INVARIANT_PLURALS)):
            warnings.append(f"{tag}: answer looks plural but the definition "
                            f"({d.get('text')!r}) is not. The definition must "
                            f"substitute for the answer in a sentence: say the swap out "
                            f"loud. If the setter really is loose (\"Lousy payment\" = "
                            f"PEANUTS), give the definition a `note` saying in a sentence "
                            f"why that is fair; do not stretch the definition to fit")
    # Deliberately NOT checked: -LY (plenty of adverbs don't end in -ly: "always"),
    # and -ing definitions for non-ing answers ("Working vessel" = DREDGER is fine).
    # A noisy warning is a warning nobody reads.


def multiset_diff(a, b):
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    extra = "".join(sorted((ca - cb).elements()))
    missing = "".join(sorted((cb - ca).elements()))
    return extra, missing


def check_cryptic_definition_cap(entries, errors, warnings=None, authored=False):
    """A puzzle may not lean on cryptic definitions (see MAX_CRYPTIC_DEFINITIONS).

    This is the one check that looks at the puzzle rather than the clue: every
    individual cryptic definition can be perfectly good and the set still be
    wrong, which is exactly how six of them got into A001 unnoticed.

    Over the cap is an error only when we set the puzzle, because that is the
    only case where the count is ours to change. On a fetched puzzle it warns,
    at the cap or over it, and names every cryptic definition for a human to
    read. Reaching the cap warns at all because a cryptic definition is the
    only type an annotator can reach for without solving anything, which makes
    the count a measure of giving up. The
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
    by comparing what the model derived against the published key — from the
    blind-annotate grader and the blind-solve one alike. The model never sees this
    file and cannot write it, which is what makes it safe to soften the check
    below: it is the one blank the annotator did not choose.
    """
    path = ROOT / "tools" / "data" / "blind_misses.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(pid, {})
    except (OSError, ValueError):
        return {}


def is_blank_clue(clue):
    """A grid entry the setter left without a clue: no text (an enumeration,
    if printed, is kept apart)."""
    return not (clue or "").strip()


def check_every_clue_is_annotated(entries, errors, warnings, misses=(), corpus=False):
    """Once a puzzle is annotated at all, every clue in it must be annotated.

    A blank annotation is the one failure no other check can see: it claims
    nothing, so it contradicts nothing, and the puzzle ships a clue with no
    teaching ladder behind it. It is also the escape hatch from every other
    rule here — quiptic-1372 solved five cryptic definitions and blanked three
    of them rather than fail check_cryptic_definition_cap, which turned a loud
    failure into a silent one. Erroring here is what stops a rule elsewhere
    from being paid for in blanks.

    That is a rule for the run that annotates. A corpus-wide run (`corpus`)
    reads committed puzzles, where a hole is a clue whose annotation was dropped
    because its text was corrected: the puzzle indexes as unannotated and the
    queue annotates it again, as it does a puzzle with no annotations at all.

    The one legitimate blank is a clue the setter left blank on purpose (a
    grid entry with no clue text, as in cryptic-30098 12A). That is detectable
    from the clue itself rather than from an allowlist: it has no text.

    The other is a blind run's miss, in `misses`. A blind night hides the key,
    and the grader afterwards drops the explanation of every clue the model got
    wrong, because an explanation built on a wrong answer is wrong from its
    first line. That blank is the grader's, decided after the run ended and off
    the published key, so it is not an escape hatch — the model cannot reach it.
    Treating it as an error meant one wrong answer in 33 failed the whole
    puzzle, and on 2026-09-11 took a second puzzle down with it.
    """
    continuations = groups.leader_of(entries)
    for e in entries:
        if e.get("annotation"):
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        if entry_id(e) in misses:
            warnings.append(
                f"{tag}: no annotation — the blind run answered "
                f"{misses[entry_id(e)]!r} wrongly and the grader dropped its "
                f"explanation. It ships with answers only until someone annotates it")
            continue
        if is_blank_clue(e["clue"].get("text", "")):
            warnings.append(f"{tag}: no annotation, and no clue to annotate — "
                            f"the setter left this entry blank on purpose")
            continue
        if entry_id(e) in continuations:
            continue                      # annotated on its group's leader
        if corpus:
            warnings.append(f"{tag}: no annotation — queued to be annotated again")
            continue
        likely = (" Its letters are a model's LIKELY fill, not the paper's: annotate "
                  "it only if you can derive the whole answer from the clue yourself."
                  if e.get("solutionConfidence") == "LIKELY" else "")
        errors.append(
            f"{tag}: no annotation. Every clue in an annotated puzzle needs one — "
            f"a blank ships a clue with nothing to teach, and no other check can "
            f"see it. If a rule elsewhere is what stopped you, break that rule "
            f"loudly instead: it names the clue, a blank does not.{likely} Only a "
            f"clue you cannot parse without inventing wordplay stays null: the "
            f"puzzle fails and can be retried, whereas a confident wrong "
            f"explanation ships and nothing catches it")


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


def check_definition_against_blog(puzzle, warnings):
    """Our definition should share a word with the one the blog underlined.

    tools/blog_facts.py keeps the definition span each clue's write-up marks.
    Where ours and theirs have not one content word in common, one of the two
    has taken the wrong end of the clue. A second opinion for the run that
    annotates, not a corpus sweep: where the two disagree the blogger's
    underline is usually the slip (it lands on the wordplay: CHAGALL underlined
    "Drink"), so a standing list of these would be mostly noise. Boundary
    differences ("prime minister" against "old prime minister") are not
    reported."""
    row = blog_facts_for(puzzle)
    if not row:
        return
    def words(s):
        every = set(re.findall(r"[a-z0-9]+", s.lower().replace("’", "'")))
        return (every - LINKING_WORDS) or every
    for e in puzzle["entries"]:
        ann = e.get("annotation") or {}
        fact = row["entries"].get(entry_id(e)) or {}
        # one tools/letter_facts.py read off other write-ups is not this blogger's underline
        theirs = None if "definitions" in fact.get("inferred", ()) else definitions.texts(fact)
        defined = definitions.texts(ann)
        if not defined or not theirs:
            continue
        ours = set().union(*map(words, defined))
        if not any(words(t) & ours for t in theirs):
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            warnings.append(
                f"{tag}: definition {' / '.join(defined)!r} shares no word with the "
                f"definition {row['name']} underlined ({' / '.join(map(repr, theirs))}, "
                f"{row['url']}). Bloggers slip too: keep ours if theirs is wordplay")


def check_blocks_against_blog(puzzle, warnings):
    """Every building block the blog names should turn up in ours.

    A blog block is LETTERS from a stretch of the clue. It is accounted for
    when our blocks spell those letters (forwards or reversed), when one of ours
    is them less a deletion, or when one of ours is taken from the same words
    (the blog gives the word heard, or the one before it is reversed, and we
    give what reaches the grid), or when ours hold its letters in another order
    (one of us wrote the anagram's fodder, the other its result). Anything left is a piece of wordplay one of us
    has and the other lacks. Measured at 99.9% agreement over the corpus, and
    the residue is mostly the blog's parse: a block taken from a lone link word
    ("in", "of") is skipped for that reason. Like the definition check, a
    second opinion for the run that annotates, not a corpus sweep."""
    row = blog_facts_for(puzzle)
    if not row:
        return
    def words(s):
        return set(re.findall(r"[a-z]{3,}", s.lower().replace("’", "'"))) - LINKING_WORDS
    def within(g, whole):
        rest = iter(whole)
        return all(c in rest for c in g)
    for e in puzzle["entries"]:
        ann = e.get("annotation") or {}
        theirs = (row["entries"].get(entry_id(e)) or {}).get("blocks")
        if not ann.get("blocks") or not theirs:
            continue
        gives = [letters(b.get("gives") or "") for b in ann["blocks"]]
        joined = "".join(gives)
        frags = [words(b.get("clueFragment") or "") for b in ann["blocks"]]
        for block in theirs:
            if block.get("inferred"):  # tools/letter_facts.py's split of the answer, not the blogger's word
                continue
            spelt, source = letters(block["gives"]), block["clueFragment"]
            if len(spelt) < 2 or not words(source):
                continue
            if (spelt in joined or spelt[::-1] in joined
                    or any(len(g) >= 2 and within(g, spelt) for g in gives)
                    or not multiset_diff(spelt, joined)[0]
                    or any(words(source) & f for f in frags)):
                continue
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            warnings.append(
                f"{tag}: {row['name']} reads {source!r} as {spelt}, and no block of ours "
                f"spells it or takes those words ({row['url']}). Check whether our "
                f"parse misses a piece; keep ours if theirs is wrong")


#: Wordplay a blog names in words, which a cryptic definition would leave out.
BLOG_WORDPLAY = ("anagram", "homophone", "spoonerism", "reversal", "container", "hidden_word")


def check_cryptic_definition_against_blog(puzzle, warnings):
    """A clue we call a cryptic definition should not be one the blog parses.

    The one type disagreement worth a warning: a cryptic definition claims no
    letters, so it is where an annotating run gives up quietly, and a blog that
    names an anagram or a homophone in it has found wordplay. Over the corpus it
    fires on 13 of 21,316 typed clues, and in most of them our walkthrough
    already spells the device out under a whole-clue label. Every other type
    difference (container against anagram in a compound, double against
    cryptic definition) is a labelling choice, so is not reported."""
    row = blog_facts_for(puzzle)
    if not row:
        return
    for e in puzzle["entries"]:
        ann = e.get("annotation") or {}
        fact = row["entries"].get(entry_id(e)) or {}
        theirs = fact.get("type") or []
        if "cryptic_definition" not in types_of(ann):
            continue
        named = [w for w in BLOG_WORDPLAY if w in theirs]
        # A type in "inferred" is tools/letter_facts.py's reading of the letters, not the
        # blogger's; with "typeCore" it is a lower bound, the clue that type and maybe a selection.
        who = "its letters read" if "type" in fact.get("inferred", ()) else f"{row['name']} parses it"
        least = "at least " if fact.get("typeCore") else ""
        if named:
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            warnings.append(
                f"{tag}: typed cryptic definition, but {who} as {least}"
                f"{clue_types.labels(theirs)!r} ({row['url']}). If the "
                f"{clue_types.label(named[0])} is there, annotate it")


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


# Mechanisms where the blocks legitimately do not add up to the answer: a
# deletion or substitution names letters that are taken away, and the three
# definition-only types plus the sound types claim no letters at all.
UNBALANCED_TYPES = ("deletion", "substitution", "cryptic_definition",
                    "double_definition", "homophone", "spoonerism", "and_lit")

# A clue whose whole mechanism is one letter selection hands over those letters
# and nothing else, so when the answer is longer the answer is DESCRIBING the
# extraction rather than being built from it — 12423 16A, MIDDLE OF NOWHERE.
# Matched exactly: a compound that merely includes a selection
# (charade + letter_selection) does have to add up.
UNBALANCED_EXACT_TYPES = (["letter_selection"],)

# The three block-shape checks below took a per-puzzle allowance of 2 until the
# corpus was drained of every hit (2026-09-07). None of them has a false positive
# left, so none of them has a reason to let one through: a tolerance that exists
# only because the corpus was dirty keeps forgiving the same defect on every
# puzzle fetched after the corpus was cleaned. Nine clues shipped a charade named
# but not performed while the allowance stood at two per puzzle.


def blocks_miss_letters(ann, entry):
    """Whether check_blocks_account_for_answer reports this entry: its blocks give
    letters, not the answer's, and its type builds from them."""
    atype = types_of(ann)
    if any(x in atype for x in UNBALANCED_TYPES) or atype in UNBALANCED_EXACT_TYPES:
        return False
    got = "".join(letters(b.get("gives")) for b in ann.get("blocks") or [] if isinstance(b, dict))
    return bool(got) and sorted(got) != sorted(wordplay_letters(ann, entry))


def check_blocks_account_for_answer(entries, errors, warnings):
    """The letters the blocks hand over have to be the answer's letters.

    Not a restatement of the `pieces` check: `pieces` is the annotator's own
    summary and is checked against the answer, so a parse can have immaculate
    pieces and blocks that say something else entirely. Haiku's TRIGGER did:
    pieces T/RIG/GER, blocks T + R + IG. The blocks are what the app renders —
    they are what the learner reads — and nothing was comparing them to anything.

    CALIBRATION (2026-09-07): 0 of 671. The single hit, 12423 16A (MIDDLE OF
    NOWHERE), is not a defect and is not a tolerance either: the answer describes
    where the H sits rather than being built out of letters, which is a property
    of its type, so UNBALANCED_EXACT_TYPES exempts that type and the gate shuts
    behind it. Any hit is now an error.
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann:
            continue
        if blocks_miss_letters(ann, e):
            got = "".join(letters(b.get("gives")) for b in ann.get("blocks", []))
            want = wordplay_letters(ann, e)
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            hits.append(tag)
            extra, missing = multiset_diff(got, want)
            warnings.append(
                f"{tag}: the blocks give {got!r}, but the answer is {want!r}"
                + (f" (extra {extra!r})" if extra else "")
                + (f" (missing {missing!r})" if missing else "")
                + " — the blocks are what the learner actually reads, so they have "
                  "to be the parse, not a sketch of one")
    if hits:
        errors.append(
            f"puzzle: {len(hits)} clue(s) ({', '.join(hits)}) have blocks whose letters "
            f"are not the answer's. Letters that don't add up mean the wordplay was "
            f"described rather than worked out")


def check_blocks_decompose(entries, errors, warnings):
    """If `pieces` takes the answer apart, the blocks must take it apart too.

    A charade with `pieces: ["SOD", "DEN"]` and one block reading
    `"Two types of earth" > SODDEN` has named the mechanism and then not
    performed it, which is the whole of what a learner came for. The comparison
    is free: the annotation already contains both halves and nothing checked
    that they agree.

    CALIBRATION (2026-09-07): 0 of 398 clues with 2+ pieces, and errors on any
    hit. The nine this check found were every one of them real, including the two
    that looked like judgement calls: ATOM was fixed the other way round, because
    its wordplay yields the single string "A TO M" and nothing clues the TO, so
    the block was right and `pieces` was the thing describing a parse it had not
    done. There is no case here where the annotator is entitled to both fields
    disagreeing — one of the two is wrong, and which one is the annotator's call.
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann:
            continue
        pieces = assembly(ann).get("pieces") or []
        if len(pieces) < 2:
            continue
        # `pieces` spelled out letter by letter — A+L+F+A, N+U+D+I+T+Y — is an
        # anagram's letter list, not a charade's chunks, and one block holding the
        # whole fodder is exactly right there. Ten of the fifteen first flagged
        # were this; a rule that lights up honest work is a broken rule.
        if all(len(letters(p)) <= 1 for p in pieces):
            continue
        full = [b for b in ann.get("blocks", [])
                if letters(b.get("gives")) == wordplay_letters(ann, e)]
        lettered = [b for b in ann.get("blocks", []) if letters(b.get("gives"))]
        if full and len(lettered) == 1:
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            hits.append(tag)
            warnings.append(
                f"{tag}: pieces are {'+'.join(pieces)} but there is one block "
                f"handing over the whole answer — split it, one block per piece. "
                f"Naming a charade is not doing the charade")
    if hits:
        errors.append(
            f"puzzle: {len(hits)} clue(s) ({', '.join(hits)}) name a multi-piece parse "
            f"and then give the answer in one block")


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

    SCOPE is the whole trick. It applies only to `type == ["charade"]` exactly.
    Any positional mechanism in the mix legitimately lists blocks out of final
    order: a container's inner piece goes inside rather than after, and a
    rotation is *defined* by blocks assembled before the spin — 30079 7D TSUNAMIS
    is A + MIST + SUN and only then cycled, which a looser scope flags and which
    is perfectly annotated. Widening from `charade` to "charade and nothing
    positional" adds 4 hits, 2 of them false. So it stays narrow.

    CALIBRATION (2026-08-09): 10 of 127 pure charades, every one a genuine
    misordering (1388 23A, 30039 24A, 30041 28D, 30042 8D, 30043 7D, 30044 19D,
    30078 25A, 30079 8D/11A/22A), all fixed in the commit that added the check.
    Each clue still warns with its own letters, and any hit fails the puzzle: the
    fix is mechanical, since exactly one ordering of the blocks spells the answer.
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann:
            continue
        if types_of(ann) != ["charade"]:
            continue
        got = "".join(letters(b.get("gives")) for b in ann.get("blocks", []))
        want = wordplay_letters(ann, e)
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
    if hits:
        errors.append(
            f"puzzle: {len(hits)} charade(s) ({', '.join(hits)}) list their blocks in "
            f"clue order rather than answer order")


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
        if not ann:
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        for b in ann.get("blocks", []):
            if letters(b.get("gives")) and not str(b.get("note") or "").strip():
                warnings.append(
                    f"{tag}: block {b.get('clueFragment')!r} > {b.get('gives')!r} has "
                    f"no note. Say why those words give those letters — that sentence "
                    f"is the teaching, and its absence is how an invented block hides")


MARKUP_RE = re.compile(r"</?[a-zA-Z][^>]*>|&(?:[a-zA-Z]+|#\d+);")
# Bytes 0x80-0x9F are punctuation in Windows-1252 and unprintable control
# codes in Unicode, so a source decoded as latin-1 turns every dash and curly
# quote into one of these and the browser draws a box. 1,937 of them reached
# the site this way. Repairing them is a lookup, so the message carries it.
CP1252_C1 = {0x82: "\u201a", 0x83: "\u0192", 0x84: "\u201e", 0x85: "\u2026",
             0x86: "\u2020", 0x87: "\u2021", 0x88: "\u02c6", 0x89: "\u2030",
             0x8b: "\u2039", 0x91: "\u2018", 0x92: "\u2019", 0x93: "\u201c",
             0x94: "\u201d", 0x95: "\u2022", 0x96: "\u2013", 0x97: "\u2014",
             0x99: "\u2122", 0x9b: "\u203a"}
C1_RE = re.compile(r"[\x80-\x9f\ufffd]")



# Characters that print alike and compare unequal. Guardian clues use curly
# quotes and en dashes, the Independent's straight ones and hyphens, and a model
# retyping a fragment writes whichever it prefers.
LOOKALIKES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"',
                            "\u201d": '"', "\u2013": "-", "\u2014": "-"})


def verbatim_hint(fragment, clue):
    """What to say when a fragment is not verbatim in its clue: the clue's own
    spelling of it, where only lookalike punctuation stood in the way."""
    want, have = str(fragment).translate(LOOKALIKES), clue.translate(LOOKALIKES)
    at = have.find(want)
    if at < 0:
        return (" — copy it character for character from the clue, which is the "
                "only text it may be")
    return (f" — the clue spells it {clue[at:at + len(want)]!r}: copy its quotes "
            f"and dashes from the file rather than retyping them")


def check_groups(puzzle, errors):
    """A linked answer is one answer over several lights. Its leader carries
    `group`, the answer's lights in order with itself first, and the whole
    annotation; every other light carries neither a group nor an annotation.
    No group at all is the ordinary case: the entry is its own answer.

    A light may continue more than one answer, and then it is in more than one
    group, but only when its own clue names more than one leader. Cryptic
    28,687's 1-down is CLUB, the second word of both GOLDFISH CLUB (8,4) at
    19-down and MONDAY CLUB (6,4) at 22-down, and reads "See 19, 22". A
    continuation naming one leader is in one group: Cyclops 683's 23-down reads
    "see 9ac.", so 11-across listing it too is an error. The count lives in
    fetch_puzzle.leaders_named, which prune_one_sided_members asks too, so the
    fetcher and this check exempt the same clues.
    """
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    held_by = {}
    for e in puzzle["entries"]:
        group = e.get("group")
        if group is None:
            continue
        if len(set(group)) < 2:
            errors.append(f"{entry_id(e)}: group {group} must name two or more "
                          f"different lights. A clue that is its own answer "
                          f"carries no group at all.")
            continue
        if group[0] != entry_id(e):
            errors.append(f"{entry_id(e)}: group {group} does not start with this "
                          f"entry. Only the leader carries the group, first in it")
            continue
        for gid in dict.fromkeys(group[1:]):
            if gid == entry_id(e):
                continue                  # an answer that repeats its first light
            other = by_id.get(gid)
            if other is None:
                errors.append(f"{entry_id(e)}: group names {gid}, which is not in this puzzle")
                continue
            held_by.setdefault(gid, []).append(entry_id(e))
            if other.get("annotation"):
                errors.append(f"{gid}: continues {entry_id(e)}'s linked answer, so it "
                              f"carries no annotation; the whole answer is "
                              f"annotated on {entry_id(e)}")
            if other.get("group"):
                errors.append(f"{gid}: continues {entry_id(e)}'s group {group} and "
                              f"leads its own {other['group']} — a light starts "
                              f"one answer at most, and only as its first light")
    for gid, leads in held_by.items():
        if len(leads) > 1 and leaders_named(by_id[gid]["clue"].get("text", "")) < 2:
            errors.append(f"{gid}: in the groups of {' and '.join(leads)}, but its "
                          f"clue names one leader. A light continues more than "
                          f"one answer only when its clue says so")


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
        text = e["clue"].get("text", "")
        for r in e["clue"].get("italics") or []:
            at, length = r.get("at"), r.get("length")
            ok = (isinstance(at, int) and isinstance(length, int)
                  and at >= 0 and length > 0 and at + length <= len(text))
            if not ok:
                errors.append(f"{entry_id(e)}: clue.italics range {r!r} is not inside the "
                              f"{len(text)}-character clue text. The ranges index the clue "
                              f"text, so editing one without the other silently italicises "
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
            c1 = C1_RE.search(o)
            if c1:
                want = CP1252_C1.get(ord(c1.group()), "")
                errors.append(f"{path.lstrip('.')}: U+{ord(c1.group()):04X} is not text "
                              f"— it draws as a box"
                              + (f", and is Windows-1252's {want!r}: the source was "
                                 f"decoded as latin-1, decode it as cp1252"
                                 if want else ", so a byte was lost in decoding")
                              + f". In {o[:70]!r}.")
    walk(puzzle, "")


def committed_entries(path):
    """{entry id: entry} as HEAD has this puzzle, or None when it is not committed."""
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        return None
    shown = subprocess.run(["git", "show", f"HEAD:{rel.as_posix()}"], cwd=ROOT,
                           capture_output=True, text=True, check=False)
    if shown.returncode:
        return None
    return {entry_id(e): e for e in json.loads(shown.stdout).get("entries", [])}


def check_clue_unchanged(puzzle, path, errors):
    """An annotation explains the clue it was written against. An annotated
    entry whose clue's words differ from the committed file's is either a run
    that rewrote the clue to suit its parse, or a correction that kept notes on
    the text it replaced. Either way the annotation goes: a corrected clue is
    committed without one and the queue annotates it afresh. Typography
    (quotes, dashes, accents, spacing) is not a different clue."""
    committed = committed_entries(path)
    if committed is None:
        return                  # not committed yet: nothing to compare with
    was = {i: enumeration.printed(e["clue"]) for i, e in committed.items()}
    for e in puzzle["entries"]:
        now = enumeration.printed(e["clue"])
        if (e.get("annotation") is not None and entry_id(e) in was
                and clue_words(was[entry_id(e)]) != clue_words(now)):
            errors.append(
                f"{entry_id(e)}: clue changed from {was[entry_id(e)]!r} to {now!r} "
                f"under an annotation. The clue text is the source's, not the "
                f"annotator's: put it back, or, correcting it, drop this entry's "
                f"annotation so it is annotated afresh")


# The indicators rung is a tier below the building blocks, and a note written as
# the operation happens hands the blocks over: "returning means RATS becomes
# STAR" solves the clue before the solver has found a piece. A note may point at
# a block's clue words ("returning means the word rats is read backwards"),
# since the solver can read those in the clue, but never at its letters: a
# block's `gives` where that is not just its clue words, or the answer. Every
# note in the corpus is held to it, so the app renders a note as written.
def letters_given_in(note, ann):
    """The capitalised words of `note` that spell a block's letters, where those
    are not just its own clue words, or the answer or one of its words."""
    bare = lambda s: re.sub(r"[^A-Za-z]", "", str(s or "")).upper()
    blocks = ann.get("blocks") or []
    letters = {bare(b.get("gives")) for b in blocks
               if bare(b.get("gives")) and bare(b.get("gives")) != bare(b.get("clueFragment"))}
    answer = str(ann.get("answer") or "")
    letters |= {bare(w) for w in [answer, *re.split(r"[\s-]+", answer)] if bare(w)}
    return [w for w in re.findall(r"\b[A-Z]+\b", str(note or ""))
            if w in letters and w not in ("A", "I")]


def check_indicator_notes_name_no_block(tag, ann, errors):
    """An indicator note spells no block's letters and not the answer."""
    for ind in ann.get("indicators") or []:
        if not isinstance(ind, dict):
            continue
        named = letters_given_in(ind.get("note"), ann)
        if named:
            errors.append(
                f"{tag}: note on indicator {ind.get('text')!r} gives away the "
                f"letters {', '.join(dict.fromkeys(named))} — {ind.get('note')!r}. "
                f"The indicators rung comes before the blocks, so say what these "
                f"words mean and what they do; a block's clue words may be named, "
                f"never its letters or the answer: \"returning means the word rats "
                f"is read backwards\", not \"returning means RATS becomes STAR\"")


# A selector is an indicator: "capital of Bahrain" giving B is the indicator
# "capital of" and the block "Bahrain" (telegraph-31356 24D, "capital should be
# an indicator", 2026-09-30). A block that swallows its selector teaches the
# letters with the instruction hidden inside them. The phrases are the ones the
# corpus uses to take a word's first, last or middle letters; a block is held to
# the rule only when its letters are that selection of the words left over, so
# "head of state" giving some other piece is not caught. Checked on the entries
# a run wrote, the way check_clue_unchanged is.
SELECT_NOUNS = {
    "first": "first|capital|head|heads|leader|leaders|start|starts|beginning|beginnings"
             "|opening|openings|top|front|source|origin|origins|onset|starter|starters"
             "|introduction|tip|foremost|entrance|face",
    "last": "last|end|ends|ending|close|back|tail|rear|finish|conclusion|finale|bottom"
            "|edge|terminal|ultimate",
    "middle": "middle|centre|center|heart|core|focus|inside",
}
SELECT_ADVERBS = {
    "first": "initially|originally|primarily|principally|firstly|at first|first of all"
             "|first|to begin with|for starters|at the outset|in the beginning|to start"
             "|beginning to|starting to|starts to|start to|first to|heading for|heading to"
             "|head for|leading",
    "last": "finally|ultimately|at last|lastly|in the end|at the end|eventually|last",
    "middle": "essentially|centrally|at heart|at the centre",
}


def _select_groups(table):
    return "|".join(f"(?P<{k}>{v})" for k, v in table.items())


SELECTOR_LEADS = [
    re.compile(r"^(?P<sel>(?:the\s+)?(?:" + _select_groups(SELECT_NOUNS)
               + r")\s+(?:of|to|for|in|from))\s+(?P<rest>.+)$", re.IGNORECASE),
    re.compile(r"^(?P<sel>" + _select_groups(SELECT_ADVERBS) + r"),?\s+(?P<rest>.+)$",
               re.IGNORECASE),
]
SELECTOR_TAIL_WORDS = _select_groups(
    {k: f"{SELECT_ADVERBS[k]}|(?:(?:at|in|to)\\s+(?:the\\s+)?)?(?:{SELECT_NOUNS[k]})"
     for k in SELECT_NOUNS})
SELECTOR_TAIL = re.compile(
    r"^(?P<rest>.+?)(?:['\u2019]s)?,?\s+(?P<sel>" + SELECTOR_TAIL_WORDS + r")$",
    re.IGNORECASE)
SELECTOR_ALONE = re.compile(r"^(?:" + SELECTOR_TAIL_WORDS + r")$", re.IGNORECASE)


def selector_in_block(block):
    """(selector words, source words) when `block`'s clue words are a letter
    selector plus the words it selects from and its letters are that selection
    (a first, last or middle letter, or one from each word); else None."""
    bare = lambda s: re.sub(r"[^A-Za-z]", "", str(s or "")).upper()
    fragment = str(block.get("clueFragment") or "").strip()
    gives = bare(block.get("gives"))
    if not gives or len(fragment.split()) < 2 or SELECTOR_ALONE.match(fragment):
        return None
    for pattern in [*SELECTOR_LEADS, SELECTOR_TAIL]:
        m = pattern.match(fragment)
        if not m:
            continue
        where = next(k for k in SELECT_NOUNS if m.group(k))
        words = [bare(w) for w in m.group("rest").split() if bare(w)]
        run = "".join(words)
        if not run:
            continue
        kept = {"first": {run[0], "".join(w[0] for w in words)},
                "last": {run[-1], "".join(w[-1] for w in words)},
                "middle": {run[(len(run) - 1) // 2:len(run) // 2 + 1]}}[where]
        if gives in kept:
            return m.group("sel").strip(" ,"), m.group("rest").strip(" ,")
    return None


def check_selectors_are_indicators(puzzle, path, errors):
    """A new or changed annotation's letter-selection block holds only the
    words it selects from; the selector is an indicator."""
    committed = committed_entries(path) or {}
    for e in puzzle["entries"]:
        ann = e.get("annotation")
        if not isinstance(ann, dict) or ann == (committed.get(entry_id(e)) or {}).get("annotation"):
            continue
        for b in ann.get("blocks") or []:
            found = isinstance(b, dict) and selector_in_block(b)
            if found:
                sel, rest = found
                errors.append(
                    f"{entry_id(e)}: block {b.get('clueFragment')!r} gives "
                    f"{b.get('gives')!r} with its selector inside it. {sel!r} is the "
                    f"instruction, so it is an indicator ({{\"text\": {sel!r}, \"for\": "
                    f"\"letter_selection\"}}, letter_selection in type), and the block "
                    f"is the source alone: {{\"clueFragment\": {rest!r}, \"gives\": "
                    f"{b.get('gives')!r}, \"select\": ...}}")


def validate_puzzle(puzzle, corpus=False):
    errors, warnings = [], []
    # The file's shape first: tools/fetch_puzzle.write_puzzle_file refuses to
    # write anything that breaks it, and this catches a file written any other way.
    errors.extend(f"schema: {p}" for p in puzzle_schema.validate(puzzle))
    check_no_markup(puzzle, errors)
    check_groups(puzzle, errors)
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    annotated = 0
    authored = is_authored(puzzle)

    for e in puzzle["entries"]:
        ann = e.get("annotation")
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        if ann is None:
            continue        # check_every_clue_is_annotated reports these
        annotated += 1

        clue = e["clue"].get("text", "")
        for key in ("type", "definitions", "answer", "blocks"):
            if key == "definitions" and ann.get("definedByPreamble") is True:
                continue
            if not ann.get(key):
                errors.append(f"{tag}: missing annotation field '{key}'")
        # A themed answer the puzzle's preamble defines ("the unclued answers
        # are birds") has no definition in its clue. Only a puzzle that prints
        # a preamble can say so, and the flag replaces the definition rather
        # than sitting beside one.
        if "definedByPreamble" in ann:
            if ann["definedByPreamble"] is not True:
                errors.append(f"{tag}: definedByPreamble is true or absent, "
                              f"never {ann['definedByPreamble']!r}")
            elif not puzzle.get("preamble"):
                errors.append(f"{tag}: definedByPreamble, but the puzzle has no "
                              f"preamble to define it. Give the definition from "
                              f"the clue")
            elif ann.get("definitions"):
                errors.append(f"{tag}: definedByPreamble and a definition "
                              f"{' / '.join(definitions.texts(ann))!r} — the clue defines it or the "
                              f"preamble does, not both")

        check_type(tag, ann, errors)

        # What letters must the wordplay produce?
        if e.get("group"):
            target_letters = "".join(letters((by_id.get(gid) or {}).get("solution") or "")
                                     for gid in e["group"])
        else:
            target_letters = letters(e.get("solution"))
        ans_letters = letters(ann.get("answer"))
        if target_letters and ans_letters != target_letters:
            errors.append(f"{tag}: answer '{ann.get('answer')}' != grid solution {target_letters}")

        # Definitions and indicators must appear verbatim in the clue, and each
        # definition's `at` must point at its text.
        for d in ann.get("definitions") or []:
            text = d.get("text") or ""
            if text not in clue:
                errors.append(f"{tag}: definition {text!r} not found in clue {clue!r}"
                              + verbatim_hint(text, clue))
            elif not definitions.span_ok(d, clue):
                errors.append(f"{tag}: definition {text!r} is not at {d.get('at')!r} in "
                              f"{clue!r}; it occurs at "
                              f"{', '.join(map(str, definitions.candidates(text, clue)))}. "
                              f"`at` is the offset in code points, filled by "
                              f"apply_annotations when the text occurs once")
        for ind in indicator_texts(ann):
            if ind not in clue:
                errors.append(f"{tag}: indicator {ind!r} not found in clue {clue!r}"
                              + verbatim_hint(ind, clue))
        # Link words ("to locate", "indicating") join definition to wordplay and
        # carry no letters of their own — they must still be named, not ignored.
        for lw in ann.get("linkWords", []):
            if lw not in clue:
                errors.append(f"{tag}: linkWord {lw!r} not found in clue {clue!r}"
                              + verbatim_hint(lw, clue))
        for b in ann.get("blocks", []):
            frag = b.get("clueFragment")
            if frag and frag not in clue:
                errors.append(f"{tag}: block fragment {frag!r} not found in clue {clue!r}"
                              + verbatim_hint(frag, clue))
            # No clue words: letters the puzzle's preamble supplies.
            if not frag and not (b.get("gives") and puzzle.get("preamble")):
                errors.append(f"{tag}: a block with no clueFragment is for letters the "
                              f"preamble supplies, and needs `gives` and a puzzle with a "
                              f"preamble; otherwise quote the clue words it parses")

        # Letter mechanics.
        build = assembly(ann)
        for a in build.get("anagrams", []):
            fodder, gives = letters(a["fodder"]), letters(a["gives"])
            extra, missing = multiset_diff(fodder, gives)
            if extra or missing:
                errors.append(
                    f"{tag}: anagram fodder {fodder} != its gives {gives}"
                    f" (fodder extra: {extra or '-'}, fodder missing: {missing or '-'})")
        for r in build.get("reversals", []):
            if letters(r["from"])[::-1] != letters(r["to"]):
                errors.append(f"{tag}: reversal {r['from']} reversed != {r['to']}")
        # The wordplay builds the clue's own word; an alteration then turns it
        # into the entry, and the write gate checks that step.
        built = wordplay_letters(ann, e)
        if build.get("pieces"):
            joined = letters("".join(build["pieces"]))
            if joined != built:
                errors.append(f"{tag}: pieces {build['pieces']} join to {joined}, expected {built}")
        if "hidden_word" in types_of(ann):
            # A reversed hidden word sits in the clue back to front (30045 26A
            # hides LEND across "commanD NELson"), so when the type also declares
            # the reversal, the mirror image counts as found.
            clue_letters = letters(expand_cross_references(clue, puzzle["entries"]))
            reversed_ok = ("reversal" in types_of(ann)
                           and built[::-1] in clue_letters)
            # A hidden homophone hides the sound, not the spelling: APHID from
            # s(AFE ID)iomatically, so the block's soundsLike is what is found.
            sound_ok = ("homophone" in types_of(ann)
                        and any(letters(b.get("soundsLike")) in clue_letters
                                for b in ann.get("blocks") or [] if b.get("soundsLike")))
            if built not in clue_letters and not reversed_ok and not sound_ok:
                errors.append(f"{tag}: hidden answer {built} not found inside clue letters")
        # apply_annotations derives the assembly wherever the blocks rebuild the
        # answer, so one still missing is a step the blocks cannot show, or blocks
        # that miss the answer's letters, which check_blocks_account_for_answer
        # already reports.
        if not (build.get("pieces") or whole_anagram(ann, e) or {"hidden_word", "double_definition", "cryptic_definition",
                    "homophone"} & set(types_of(ann)) or blocks_miss_letters(ann, e)):
            warnings.append(f"{tag}: no machine-checkable assembly, and the blocks do not "
                            f"rebuild the answer by joining them with the reversals, "
                            f"insertions and anagrams `type` names. Give `assembly.pieces` "
                            f"(the final chunks in answer order), and `assembly.anagrams` / "
                            f"`assembly.reversals` for each such step the blocks cannot show")

        # A definition's note silences the part-of-speech check, so it has to say
        # something: a one-word "fine" would turn the check into an off switch.
        for note in [d["note"] for d in ann.get("definitions") or [] if "note" in d]:
            if len(str(note).strip()) < 25:
                errors.append(f"{tag}: definition note {note!r} is too thin — it exists only "
                              f"where the definition disagrees with the answer in number or "
                              f"part of speech, and it must say in a real sentence why the "
                              f"setter is allowed that (\"Lousy payment\" = PEANUTS: a "
                              f"mass noun defining a plural, fair because peanuts is itself "
                              f"used as a mass noun for a pittance). Explain it or drop it")

        check_definition_fit(tag, ann, errors, warnings)
        check_answer_matches_separators(tag, ann, e, errors)
        check_sound_names_its_source(tag, ann, errors, warnings)
        check_sound_is_not_a_letter_swap(tag, ann, errors, warnings)
        check_indicators(tag, ann, clue, errors, warnings)
        check_unmarked_hidden_word(tag, ann, clue, errors)
        check_no_answer_in_early_rungs(tag, ann, clue, errors, warnings)
        check_block_notes_dont_name_the_answer(tag, ann, errors, warnings,
                                               light_solutions(e, by_id))
        check_indicator_notes_name_no_block(tag, ann, errors)
        check_cryptic_definition_blocks(tag, ann, errors, warnings)

        check_coverage(tag, ann, clue, warnings)
        check_part_of_speech(tag, ann, warnings)
        check_features(tag, ann, clue, errors, warnings)
        check_surface(tag, ann, clue, warnings)
        # Not under `authored`. is_authored means WE wrote the clue; the
        # walkthrough is ours either way, and every hit these two have ever had
        # was on a published grid. Gated, they would never fire.
        check_walkthrough_opener(tag, ann, warnings)
        check_walkthrough_closer(tag, ann, warnings)
        # Not under `authored` either, and for the same reason: the fault is in
        # OUR parse of a published clue, and every hit it has ever had was on
        # somebody else's grid.
        check_link_word_is_not_an_order(tag, ann, clue, warnings)
        check_link_word_is_not_inside_an_indicator(tag, ann, clue, errors)
        check_indicator_does_not_straddle_a_definition(tag, ann, clue, errors)
        check_anagram_fodder_from_clue(tag, ann, clue, authored, errors, warnings)
        if authored:
            check_authored_surface(tag, ann, clue, errors)
            check_two_pieces(tag, ann, errors)
            check_walkthrough_budget(tag, ann, warnings)
            check_link_words_are_equivalences(tag, ann, errors)
            check_indicator_adjacency(tag, ann, clue, errors, warnings)
            check_indicator_outside_fodder(tag, ann, clue, errors)
            check_reversal_direction(tag, ann, e["direction"], errors)
        walk = explanation(ann).get("walkthrough") or ""
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
        # Published under "What it seems to say" on the walkthrough rung, so it is held to the
        # length it was specified at rather than to the walkthrough's: it is one
        # sentence of picture, and a paragraph there pushes the trick off the screen.
        surface = explanation(ann).get("surface") or ""
        if len(surface.split()) > SURFACE_MAX:
            warnings.append(f"{tag}: surface is {len(surface.split())} words "
                            f"(max {SURFACE_MAX}) — it is the picture the clue paints, "
                            f"one sentence; the mechanics belong in walkthrough")
        # Same words in both fields means one of them is a heading with nothing
        # under it, and the rung prints them one after the other.
        if surface and surface.strip().lower() in walk.strip().lower():
            errors.append(f"{tag}: surface {surface!r} is repeated inside walkthrough — "
                          f"they are printed as two paragraphs, so say the picture once "
                          f"in surface and spend walkthrough on what the clue is doing")
        for field, text in ([("walkthrough", walk), ("surface", surface),
                             ("definitionFit", explanation(ann).get("definitionFit") or "")]
                            + [("block note", b.get("note") or "")
                               for b in ann.get("blocks", [])]):
            for marker in BACKTRACKS:
                if marker in text.lower():
                    errors.append(f"{tag}: {field} contains {marker!r} — that is "
                                  f"working-out, not an explanation. Settle the parse "
                                  f"first, then write the finished sentence")


    if annotated:
        check_every_clue_is_annotated(puzzle["entries"], errors, warnings,
                                      blind_misses(puzzle["id"]), corpus=corpus)
        check_cryptic_definition_cap(puzzle["entries"], errors, warnings,
                                     authored=authored)
        if authored:
            check_authored_puns(puzzle["entries"], errors)
        check_definition_not_fodder(puzzle["entries"], errors, warnings)
        if not corpus:
            check_definition_against_blog(puzzle, warnings)
            check_blocks_against_blog(puzzle, warnings)
            check_cryptic_definition_against_blog(puzzle, warnings)
        check_blocks_account_for_answer(puzzle["entries"], errors, warnings)
        check_blocks_decompose(puzzle["entries"], errors, warnings)
        check_blocks_in_answer_order(puzzle["entries"], errors, warnings)
        check_blocks_carry_notes(puzzle["entries"], warnings)

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
# The two shapes a line of this tool's output can take, named so a caller can
# count them without matching on prose that is free to change.
WARN_PREFIX = "  warn: "
ERROR_PREFIX = "  ERROR: "

BACKLOG_PATH = ROOT / "tools" / "annotation_backlog.json"
# Each field is the dotted path of the key it counts. The file lists them in
# this order, and tools/prereset_backfill.sh drains them in the file's order.
BACKLOG_MARKERS = {
    "explanation.definitionFit": ("no explanation.definitionFit",),
    "indicators.note": ("no indicator notes", "has no note"),
    "indicators.for": ("lack `for`",),
    "features": ("no features",),
    "explanation.surface": ("no explanation.surface",),
}


def load_backlog():
    """{field: {puzzle: allowance}}. A field the file has no list for yet is left
    out, and is not enforced until the --tighten that writes its list."""
    if not BACKLOG_PATH.exists():
        return {f: {} for f in BACKLOG_MARKERS}
    data = json.loads(BACKLOG_PATH.read_text())
    return {f: data[f] for f in BACKLOG_MARKERS if f in data}


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


def explain(name=None):
    """Print what a check actually does, read out of this file's own source.

    Annotation runs were opening this file and paging through 1800 lines to
    find one function, ten grep/sed calls at a time, and every one of those is
    a turn and a transcript that gets re-billed on every turn after it. The
    answer is the source, so this hands over the source: the definition asked
    for and the comment block above it, which is where the reason lives.

    Generated by reading the AST rather than by keeping a table of
    explanations, because a table is a second copy of the truth and would be
    wrong within a month.
    """
    src = Path(__file__).read_text()
    lines = src.splitlines()
    tree = ast.parse(src)
    named = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            named[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    named[t.id] = node

    if not name:
        print("Every check this file runs. `--explain <name>` prints one in full;\n"
              "constants and helpers (MARKUP_RE, TYPE_NAMES)\n"
              "work as names too.\n")
        for key, node in named.items():
            if not key.startswith("check_"):
                continue
            doc = ast.get_docstring(node) or ""
            print(f"  {key}\n      {doc.split(chr(10))[0] or '(no docstring)'}")
        return 0

    found = explain_matches(name, named, lines)
    if not found:
        print(f"no `{name}` in {Path(__file__).name}. Run --explain with no name for the list.")
        return 1
    if len(found) > EXPLAIN_AT_MOST:
        print(f"`{name}` is not a check's name; {len(found)} checks use it: "
              f"{', '.join(found)}. `--explain <one of these>` prints it.")
        return 0
    if found != [name]:
        print(f"# `{name}` is not a name here; the closest: {', '.join(found)}\n")
    for key in found:
        node = named[key]
        # The comment block immediately above a definition is this file's habit
        # for saying why it exists, so it is part of the answer.
        start = node.lineno - 1
        while start and lines[start - 1].lstrip().startswith("#"):
            start -= 1
        print("\n".join(lines[start:node.end_lineno]) + "\n")
    return 0


EXPLAIN_AT_MOST = 3


def explain_matches(name, named, lines):
    """The definitions `--explain name` means, best first.

    Runs pass what they saw, not a function name: a message's words
    (`definition-overlap`), a field (`definitionFit`), a type
    (`double_definition`). A refusal costs them a turn, so the name is taken
    as exact, then as part of a name, then as words every one of which the
    check's source contains."""
    key = re.sub(r"[-\s]+", "_", name.strip()).strip("_")
    for exact in (name, key, f"check_{key}", f"check_{key.lower()}"):
        if exact in named:
            return [exact]
    checks = [k for k in named if k.startswith("check_")]
    part = [k for k in checks if key.lower() in k.lower()]
    if part:
        return sorted(part, key=len)
    words = [w.lower().rstrip("s") for w in re.split(r"[_\W]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", key)) if w]
    words = [w for w in words if w != "check"]
    if not words:
        return []
    source = {k: "\n".join(lines[named[k].lineno - 1:named[k].end_lineno]).lower() for k in checks}
    return sorted((k for k in checks if all(w in source[k] for w in words)),
                  key=lambda k: -sum(source[k].count(w) for w in words))


def backlog_errors(stem, warnings, allowed=None):
    """The ratchet's ERRORs for one puzzle: it may be short exactly as many
    notes as the backlog file records for it, and a puzzle absent from the file
    (anything annotated from now on, and every authored puzzle) is allowed 0."""
    allowed = load_backlog() if allowed is None else allowed
    errors = []
    for field, n in count_backlog(warnings).items():
        if field not in allowed:
            continue
        cap = allowed[field].get(stem, 0)
        if n > cap:
            errors.append(
                f"{n} warning(s) for {field}, and this puzzle is allowed {cap} — "
                f"{field} is required on everything annotated since it was added. "
                f"The warnings above name them and say what to write.")
    return errors


def main(argv):
    global FORCE_AUTHORED_CHECKS
    if "--explain" in argv:
        rest = argv[argv.index("--explain") + 1:]
        return explain(rest[0] if rest else None)
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
        puzzle = read_puzzle_file(path)
        annotated, errors, warnings = validate_puzzle(puzzle, corpus=full_run)
        if not full_run:        # a run's own puzzles; the corpus is HEAD already
            check_clue_unchanged(puzzle, path, errors)
            check_selectors_are_indicators(puzzle, path, errors)
        total = len(puzzle["entries"])
        if annotated == 0 and not argv:
            # Nothing to check about annotations that do not exist yet — but
            # the checks that walk the whole file (markup) do apply, and
            # dropping them here would exempt exactly the puzzles nobody has
            # looked at.
            print(f"{puzzle['id']}: unannotated ({total} clues) — skipped")
            for err in errors:
                print(f"{ERROR_PREFIX}{err}")
            failed = failed or bool(errors)
            continue
        observed[path.stem] = count_backlog(warnings)
        errors += backlog_errors(path.stem, warnings, allowed)
        status = "OK" if not errors else "FAIL"
        by = f" ({puzzle['setter']})" if puzzle.get("setter") else ""
        print(f"{puzzle['id']}{by}: {annotated}/{total} annotated — {status}")
        for w in warnings:
            if annotated:
                print(f"{WARN_PREFIX}{w}")
        for err in errors:
            print(f"{ERROR_PREFIX}{err}")
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
                  + ", ".join(f"{f} recorded" if f not in allowed else f"{f} -{n}" if n >= 0
                              else f"{f} unchanged (observed {abs(n)} more, kept the tighter cap)"
                              for f, n in moved.items()))
        elif any(v > 0 for v in moved.values()):
            print("backlog shrank (" + ", ".join(f"{f} -{n}" for f, n in moved.items() if n > 0)
                  + ") — run `python3 tools/validate_annotations.py --tighten` to record it, "
                    "or those clues can silently go missing again.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
