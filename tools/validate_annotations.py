#!/usr/bin/env python3
"""Validate clue annotations in puzzles/<series>/<year>/*.json.

Checks, for every annotated entry:
  - annotation has type, definitions, answer, blocks
  - `type` is an array of names from tools/data/clue_types.json (check_type)
  - answer letters match the grid solution (group-aware for linked entries)
  - each definition sits at its `at` in the clue (tools/definitions.py), every
    indicator and every linkWord is an exact substring of the clue, and every content word of the clue is claimed by one
    of those or by a block (check_coverage)
  - no link word overlaps an indicator or a definition, so an &lit has none
    (check_link_word_is_clear_of_other_marks)
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
       python3 tools/validate_annotations.py --explain [check-name]
With no arguments, validates every puzzle that has at least one annotation.
`--shard i/n` (the deploy runs 0/4 .. 3/4) does that for the puzzles whose id
hashes to i of n; the ratchet is per puzzle, so each shard enforces its own
slice and the backlog totals it prints are the slice's.
`--unscoped` runs the authored-only checks on published puzzles too — that is
the CALIBRATION harness, not a mode to ship in: a check that flags Araucaria is
a broken check, so every authored-only rule is measured across the annotated
published puzzles before it is trusted. Exits non-zero if any check
fails.
"""

import ast
import collections
import copy
import difflib
import functools
import itertools
import hashlib
import json
import multiprocessing
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
import clue_types
import definitions  # where each definition sits; tools/definitions.py
import enumeration  # a clue's printed counts; tools/enumeration.py
import groups  # linked answers; tools/groups.py
import lesson_checks  # findings read off a second annotation run; tools/lesson_checks.py
import provenance  # where each puzzle came from; tools/provenance.py
import puzzle_schema  # tools/data/puzzle.schema.json
import wordplay  # tools/wordplay.py
import annotation  # the derived fields: view(), view_puzzle()
from annotation import assembly, explanation, whole_anagram, wordplay_letters
from fetch_puzzle import (  # one reader, one exemption
    blog_facts_for,
    clue_words,
    corrected_clue,
    has_words,
    leaders_named,
    load_source_table,
    read_puzzle_file,
    source_clue,
    SOURCE_CLUE_WRONG,
)
from find_answer_leaks import _run, light_solutions, named, pieces_of, says  # one matcher, shared with the finder
from groups import entry_id
from hidden_messages import block_letters, check_preamble, letter_problems, message_problems
from puzzle_paths import (  # one glob, one id resolver
    puzzle_files,
    resolve_puzzle,
)

ROOT = Path(__file__).resolve().parent.parent

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
# because OUR authoring pass drifts over it: a funny sentence is far easier to
# find than a funny mechanism. See AUTHORING.md, "The sentence AND the wordplay".
#
# The cap is a HARD limit on authored puzzles and only a warning on fetched
# ones, because a published setter's count is a fact about their puzzle and not
# a budget we get to set. An error there would push the annotator to ship the
# surplus clues BLANK, which teaches nothing and which only
# check_every_clue_is_annotated can see.
MAX_CRYPTIC_DEFINITIONS = 2


# "A good cryptic clue doesn't have anything superfluous which isn't directly
# part of the wordplay. It should be exactly two pieces. Definition, optional
# joinery and wordplay." A word that exists only to make
# the surface read nicely is a fault, and in this schema it has exactly one
# signature: a block with an empty `gives`, i.e. "surface only" padding.
#
# A walkthrough budget for the companion rule: "When you basically give the whole
# answer in the building blocks you don't need to have the full walkthrough."
# 45 sits above the 99th percentile: across 74,474 published walkthroughs with
# blocks the median is 19 words, p90 32, p99 40, and 0.1% run over 45.
MAX_WALKTHROUGH_WORDS = 45

# Opening formulas that spend the first clause on something other than the clue.
# Anchored at the start and kept to fixed phrasings on purpose — the same words
# are unremarkable once the sentence is under way, and a matcher that chased
# them there would fire on half the corpus. The patterns are the shapes found in
# the 6,403 published walkthroughs, not every stiff opening anyone can imagine.
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
# "This is a ..." is deliberately not a pattern: its corpus hits are contrastive —
# "This is a rotation, not a reversal" — which is the trick stated, not a
# preamble to it. A check that warns on good sentences gets ignored on the bad
# ones.

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

    Ours carry series "authored" (tools/series.py). The field decides, never the
    spelling of the id. The distinction matters because
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
    (check_cryptic_definition_blocks forbids one). Nor is a definition's own
    block, which view() gives a double definition with no `gives`."""
    if types_of(ann) == ["cryptic_definition"]:
        return
    defs = {d.get("text") for d in ann.get("definitions") or [] if isinstance(d, dict)}
    for b in ann.get("blocks", []):
        if not str(b.get("gives") or "").strip() and b.get("clueFragment") not in defs:
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
    and the sentence reads oddly. The other
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
    conclusion handed back to them.

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
    have always been the re-narrating ones. A semantic detector does not work:
    the fraction of walkthrough vocabulary already present in the clue and
    blocks separates nothing — good walkthroughs score WORSE than bad ones,
    because naming the joke means reusing the clue's own words.

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
    """A link word has to stand in for an equals sign.

    "lives on" does not. It joins nothing and asserts nothing; it is surface
    padding wearing a link word's coat, and declaring it in `linkWords` makes
    the annotation look sound while the clue is quietly in three pieces —
    wordplay, PADDING, definition. That is the same fault check_two_pieces
    catches when the annotator is honest enough to file it as a block with an
    empty `gives`; this check closes the other door.

    CALIBRATION (unscoped, 74,474 annotated published clues):
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


def check_link_word_is_clear_of_other_marks(tag, ann, clue, errors):
    """A link word needs a copy of its own in the clue, clear of every indicator
    and every definition.

    app.js claims link words after indicators and definitions, so a connective
    the clue uses twice ("in" inside the indicator and "in" linking) lands on
    the free copy. With no free copy it lands on the other mark, wholly or in
    part. On an indicator it takes words off a hint the solver has paid for:
    times-29616 6D filed "of" inside "on top of", everyman-3925 4D filed "'s
    written" across "written about". Inside a definition it breaks the band and
    the hint calls a word of the definition "just a link": azed-2718 1A, an
    &lit whose whole clue is the definition, filed "with" as a link. A link
    joins wordplay to definition, so it cannot sit inside either; an &lit has
    none. tools/smoke_test.js rejects the render; this rejects the annotation
    before it is committed.
    """
    clue = clue or ""
    placed = place_fragments(ann, clue)
    for kind, lw, i in placed:
        if kind != "link":
            continue
        for other, name in (("ind", "an indicator"), ("def", "the definition")):
            if any(o == other and i < j + len(t) and j < i + len(lw) for o, t, j in placed):
                errors.append(
                    f"{tag}: linkWord {lw!r} has no copy in the clue clear of {name}, "
                    f"so marking it as a link takes words off {name}. Each clue word "
                    f"is one of definition, indicator or link; drop it from one list "
                    f"(an &lit's whole clue is its definition, so it has no link words)")


def check_link_word_is_not_inside_a_block(tag, ann, clue, errors):
    """A link word may not be a word a block parses.

    A link adds no letters, so a word in both lists is counted twice: the page
    marks it a link, and the block's fragment is then never what the clue has
    left. cyclops-491 20A filed "when" as a link and "when that's" as the
    anagram fodder, and the building-blocks rung asked for fodder that took
    back a word the definition rung had called a link. Refused when no choice
    of copies puts every link word on words no block fragment uses.
    """
    clue = clue or ""
    links = [t for t in ann.get("linkWords") or [] if isinstance(t, str) and t]
    frags = [b.get("clueFragment") for b in ann.get("blocks") or [] if isinstance(b, dict)]
    frags = [f for f in frags if isinstance(f, str) and f]
    hits = lambda t: [(i, i + len(t)) for i in _starts(t, clue)]
    link_hits, frag_hits = [hits(t) for t in links], [hits(f) for f in frags]
    if not links or not frags or not all(link_hits + frag_hits):
        return              # a fragment not in the clue is reported elsewhere
    clear = lambda s, taken: not any(s[0] < d and c < s[1] for c, d in taken)

    # Links take words of their own; blocks may share words with each other (a
    # container's outer piece holds its inner one), so given the links' copies
    # each block needs only one copy clear of them.
    def fits(k, taken):
        if k == len(links):
            return all(any(clear(s, taken) for s in fh) for fh in frag_hits)
        return any(fits(k + 1, taken + [s]) for s in link_hits[k] if clear(s, taken))

    if not fits(0, []):
        fix = "; ".join(link_in_block_hints(ann, links)) or "drop it from one list"
        errors.append(
            f"{tag}: linkWords {links} have no copy in the clue clear of the block "
            f"fragments {frags}, so a word is counted twice: once as a "
            f"link adding no letters, once as wordplay. Each clue word is either link "
            f"or wordplay: {fix}")


def link_adds_nothing(frag, lw, gives):
    """True when a block's `gives` is drawn from its fragment's own letters
    (anagram, hidden or selected fodder) and the fragment without `lw` still
    holds every one of them: the link word gives the block nothing ("met with
    fatal" giving METFATAL), so it is no fodder."""
    want, have = collections.Counter(letters(gives)), collections.Counter(letters(frag))
    if not want or want - have:
        return False
    return not want - collections.Counter(letters(frag.replace(lw, " ", 1)))


def link_in_block_hints(ann, links):
    """The edit to make for each link word sitting inside a block fragment, said
    in the clue's own words, so the fix takes one turn and not a guess."""
    out = []
    for lw in links:
        for b in ann.get("blocks") or []:
            frag = b.get("clueFragment") if isinstance(b, dict) else None
            if not isinstance(frag, str) or lw not in frag:
                continue
            gives = b.get("gives")
            if frag == lw:
                out.append(f"the block {frag!r} is the link word itself: if it gives "
                           f"{letters(gives) or 'no letters'}, take {lw!r} out of linkWords, "
                           f"else drop the block")
            elif link_adds_nothing(frag, lw, gives):
                left, _, right = frag.partition(lw)
                parts = [x.strip(" ,;:") for x in (left, right) if x.strip(" ,;:")]
                out.append(f"{lw!r} gives none of {letters(gives)}, so it is not fodder: "
                           + (f"cut the block {frag!r} to {parts[0]!r}" if len(parts) == 1 else
                              f"split the block {frag!r} into {' and '.join(map(repr, parts))}"))
            elif frag.startswith(lw) or frag.endswith(lw):
                rest = (frag[len(lw):] if frag.startswith(lw) else frag[:-len(lw)]).strip(" ,;:")
                out.append(f"if {lw!r} only links, the block is {rest!r}; if the block "
                           f"uses its letters, take {lw!r} out of linkWords")
            else:
                out.append(f"{lw!r} is inside the block {frag!r}: if the block uses its "
                           f"letters, take it out of linkWords")
    return out


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
        hits = list(_starts(ind, clue)) if ind else []
        if hits and all(any(i < e and i + len(ind) > s and not s <= i < i + len(ind) <= e
                                for s, e in spans) for i in hits):
            errors.append(
                f"{tag}: indicator {ind!r} runs across the edge of the definition, so the "
                f"two cannot both be marked. Take the shared words off one of them")


def check_link_word_is_not_an_order(tag, ann, clue, warnings):
    """A link word that put the pieces in that order is an indicator.

    In 30,099 25A, "Post on half of wage when things are developing", `on` is
    why the post ends up at the BACK of the answer: across the grid, one thing
    written on another has been reached after it. The word carries the only
    instruction in the clue, so filing it under linkWords makes the page say it
    "contributes no letters of its own" and never says why the post comes second.

    Flagged only where the joiner is demonstrably the thing that did the
    reordering: two blocks listed in the opposite order from the clue, the
    joiner sitting between them, and no declared indicator between them to take
    the blame instead. A container or reversal that shuffles the blocks past
    each other therefore clears the joiner, which is the point — `model in
    Channel Islands on ecstasy` (everyman-4093 9A) is reordered by `in`, and
    `on` there really is joinery.

    CALIBRATION (the whole corpus): 65 entries declare a positional
    joiner as a link word and 12 of them list blocks out of clue order, but only
    3 survive the two conditions above — 30,099 25A and indysunday-1885 14A and
    25A. All three are real, and the two Filbert ones are the proof: their
    walkthroughs SAY "in an across clue one thing 'on' another sits after it"
    and file `on` as a link word in the same breath. A warning, because three
    is a thin sample for an error."""
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

    CALIBRATION (published annotations): the convention is
    lopsided. Vertical words almost never reverse an across entry (`up` 2 of
    168 single-word uses). Horizontal words reverse down entries all the time:
    `back` sits on a down entry in 25 of 170 single-word uses and `returning`
    in 17 of 72. So `back` is neutral, not horizontal. With the measured lists,
    25 of 2,087 axis-word reversals cross over (1.2%).

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
# that needs one is nearly always hiding a wrong parse (30067 13A "jokingly
# adjectived" was papering over state = CAL).
HEDGES = ("jokingly", "if you squint", "hand-wave", "handwave", "somehow",
          "for some reason", "don't ask", "close enough")
_QUOTED = re.compile(r"'([^']+)'|\"([^\"]+)\"|‘([^’]+)’|“([^”]+)”")


def walkthrough_hedges(walk, clue):
    """The HEDGES a walkthrough uses as its own words. A word the clue prints is quoted, not
    used: "'Somehow' rearranges UNCLE" names the anagram indicator (a third of the first-check
    hedge refusals in the annotate audit 10-24/25), so a quoted run that is in the clue is
    set aside before the hedges are looked for."""
    clue_low = (clue or "").lower()
    low = _QUOTED.sub(lambda m: " " if next(g for g in m.groups() if g).lower().strip(" ,.;:!?") in clue_low
                      else m.group(0), (walk or "").lower())
    return [h for h in HEDGES if h in low]

# Working-out left in the published text. A walkthrough is the finished
# explanation; if it is still arguing with itself ("No wait—", "Still wrong.",
# "That's not it either."), the model shipped its scratch pad, and every
# structural check passes anyway because every field is present and every
# letter adds up.
#
# Two guards, deliberately: the phrase list below, and WALKTHROUGH_HARD_MAX.
# The phrases are a text match and so only catch the wordings seen so far; the
# word cap is structural and catches dumped reasoning whatever it says, because
# reasoning-in-public is long and a finished walkthrough is short.
#
# It is a second, higher ceiling on top of MAX_WALKTHROUGH_WORDS (45), not a
# replacement: that one is a style budget and warns, on authored puzzles only,
# when the prose repeats what the blocks already said. This one is an ERROR on
# every puzzle and asks a cruder question — is this even a walkthrough? 60 is
# well clear of any real walkthrough, so nothing that hits it is a near miss on
# the style budget.
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
        warnings.append(f"{tag}: no explanation.surface — say in one sentence (up to {SURFACE_MAX} words) what "
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
    if no_note and len(no_note) == len(texts):
        warnings.append(f"{tag}: no indicator notes — give every indicator a `note`. "
                        f"{INDICATOR_NOTE_HOW}")
    else:
        for text in no_note:
            warnings.append(f"{tag}: indicator {text!r} has no note — every indicator "
                            f"gets one. {INDICATOR_NOTE_HOW}")


SOUND_TYPES = ("homophone", "spoonerism")


def _sound_over_step(tree):
    """The op of a step (first, del, hid, ...) a sound() wraps, else None."""
    nodes = [tree]
    while nodes:
        n = nodes.pop()
        if isinstance(n, dict):
            if n.get("op") == "homophone":
                for p in n.get("parts") or []:
                    if isinstance(p, dict) and p.get("op") not in (None, "homophone"):
                        return p["op"]
            nodes.extend(n.get("parts") or [])
    return None


def plain_spoonerism(ann):
    """True when the only sound in the clue is a spoon: spoon(a, b) swaps the
    onsets in the letters the two blocks give (CORE FAST -> FORE CAST), and
    spoon(a, b, SPELT) swaps them by sound, the blocks giving the words said
    ([marry]MARRY, [fan]FAN) and SPELT the answer's spelling (FERRYMAN). Either
    way the heard words are the blocks' own `gives`, so there is nothing for
    `soundsLike` to carry; demanding one trapped runs into sound([x]W, W),
    which fails the 'nothing was heard' rule instead. A spoon filed over a
    sound() (the older form) has a homophone type, so it is not plain and is
    still held to the sound rule."""
    if "homophone" in types_of(ann):
        return False
    nodes, found = [ann.get("wordplay")], []
    while nodes:
        n = nodes.pop()
        if isinstance(n, dict):
            if n.get("op") == "spoonerism":
                found.append(n)
            nodes.extend(n.get("parts") or [])
    return bool(found)


def check_sound_names_its_source(tag, ann, errors, warnings):
    """A homophone must name the word you say aloud, as a field, not as prose.

    In "Cockney mob loudly" → OARED, a block reading “Cockney mob” → OARED
    leaves every step of the actual clue off-screen: a mob is a HORDE, a Cockney
    drops the aitch to leave ’ORDE, and ’ORDE said aloud is OARED. That rung
    asserts the answer and teaches nothing.

    The source word cannot live only in a note, because a note is prose and
    prose is unenforceable: a horde mentioned in passing, buried mid-sentence,
    still reads as a leap. So `soundsLike` is a tracked
    field on the block that does the sounding, it is required on every clue
    whose type declares a sound, and it must differ from what the block gives —
    a `soundsLike` equal to the output is not a homophone, it is a spelling.
    """
    is_sound = any(t in types_of(ann) for t in SOUND_TYPES) and not plain_spoonerism(ann)
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
        if heard and not plain_spoonerism(ann):
            errors.append(f"{tag}: a block declares soundsLike but the type is "
                          f"{ann.get('type')!r} — add the sound to the type or drop the field")
        return
    if not heard:
        blocks = [b for b in ann.get("blocks", []) if b.get("clueFragment") and b.get("gives")]
        ours = [b for b in blocks if letters(b["gives"]) == letters(ann.get("answer") or "")]
        pick = (ours or blocks[-1:] or [None])[-1]
        here = ""
        if pick:
            frag, gives = pick["clueFragment"], pick["gives"]
            here = (f"In this clue the block to fix is {frag!r} > {gives!r}: write it in "
                    f"`wp` as sound<indicator>([{frag}]HEARD, {gives}) with HEARD the "
                    f"word you say aloud for {frag!r}, not {gives!r} itself. ")
        over = _sound_over_step(ann.get("wordplay"))
        if over:
            here = (f"Here sound() wraps a `{over}` step, and a sound takes ONE leaf: "
                    f"write the letters that step gives as the leaf, "
                    f"sound<indicator>([the clue words]LETTERS, SPELT), and say in the "
                    f"leaf's note how the words give those letters. ") + here
        errors.append(
            f"{tag}: type {ann.get('type')!r} but no block says what is said aloud. "
            f"{here}"
            f"Add `soundsLike` to the block that does the sounding: the word you "
            f"HEAR is the clue's whole mechanism, and a block that jumps a "
            f"fragment straight to the answer has taught none of it. The note "
            f"carries the step before the sound: \"Cockney mob loudly\" -> OARED is "
            f"soundsLike ’ORDE, gives OARED, the note saying a mob is a HORDE and a "
            f"Cockney drops the aitch. A mechanism feeding the sound gets its own "
            f"earlier block. In `wp` that block is `sound<indicator>(x, SPELT)` "
            f"where x is ONE leaf, [the clue words you say]LETTERS HEARD (merge a "
            f"charade of leaves into a single leaf, or put the charade outside the "
            f"sound), and SPELT is the letters it comes out as. A Spoonerism is "
            f"not written with sound(): swap written letters with `spoon(a, b)`, or "
            f"swap by sound with `spoon<indicator>([marry]MARRY, [fan]FAN, FERRYMAN)`, "
            f"the leaves giving the words said and the third argument the answer")


def check_sound_is_not_a_letter_swap(tag, ann, errors, warnings):
    """A spoonerism trades SOUNDS. A soundsLike made by trading letters is a fake.

    In quiptic 1398 9A, blocks giving DOUGH and NOUGHT followed by a third block
    declaring the pair sounded like "NOUGH DOUGHT" is a string arrived at by
    exchanging the two words' first LETTERS and re-spelling nothing else. It is
    not a word, not a pronunciation and not anything the solver can say aloud,
    so the rung ends at gibberish and the reader must leap from it to NO DOUBT
    unaided. Spooner swaps the opening sounds: "doh" and "nawt" become "noh" and
    "dawt", which are then SPELT NO and DOUBT, and the respelling is the lesson.

    The tell is arithmetic. When a sounded form uses exactly the letters the
    earlier blocks already gave, only in a different order, no sound was
    recorded — the annotator shuffled characters between the chunks. In the
    corpus: 3 hits in 328 sound clues (quiptic-1398 9A "NOUGH DOUGHT",
    independent-12412 5D "FOG BOE", indysunday-1871 13A "FONE CALL"), all the
    same defect. A sounded form that legitimately restates the earlier
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
    spells the answer across an accented word must keep the accented letter:
    12422 23A hides PESTO in "canapés today", and dropping the É would put the
    answer outside the clue. The Independent and the Guardian both
    print accents (canapés, café, née), and a solver reads them as the plain
    letter — so the validator has to as well. NFD splits É into E plus a
    combining acute; the character class then keeps the E and drops the mark."""
    s = unicodedata.normalize("NFD", (s or "").upper())
    return re.sub(r"[^A-Z]", "", s)


def _starts(needle, text):
    """Where `needle` (non-empty) occurs in `text`, not overlapping: re.finditer
    over re.escape(needle) without compiling a pattern per needle, which at
    ~1 per link word and fragment per clue overran the re cache and was
    ~1/3 of the full check's time."""
    i = text.find(needle)
    while i >= 0:
        yield i
        i = text.find(needle, i + len(needle))


@functools.lru_cache(maxsize=None)
def _whole_word(word):
    return re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)")


def words_of(s):
    """Lowercase word list, with markup, the (8) enumeration and punctuation dropped.

    Guardian clue text sometimes carries literal HTML — 30046 19A and 30072 27A
    both italicise a word — and a tag name such as 'span' is not a word of the
    clue, so nothing could honestly claim it in the coverage check.
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

# The enumeration, and nothing else in brackets. A parenthetical aside is
# ordinary clue text that a hidden word may run straight through: everyman-4122
# 15A, "Madman seen in Psycho (the adaptation)", hides HOTHEAD across
# psyc(HO THE AD)aptation, and stripping the bracket would put the answer
# outside the clue. Digits and separators only, so "(7)", "(4,6)" and "(4-6)" still go and no
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
    nor a block fragment is wordplay the annotation silently dropped (30067 13A
    never accounted for 'state' = CAL)."""
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
        elif not _whole_word(plain(word.strip())).search(plain(clue or "")):
            errors.append(f"{tag}: features.misdirectedWord {word!r} does not occur "
                          f"in the clue {clue!r}")


def plain(text):
    """`text` lowercased with curly apostrophes straightened, for matching a
    word the annotation names against the clue it came from."""
    return text.lower().replace("\u2019", "'").replace("\u2018", "'")


def check_part_of_speech(tag, ann, warnings):
    """The definition must be substitutable for the answer, which means their
    inflections agree: a plural answer needs a plural definition, an -ing answer
    an -ing definition. Only the mechanical, unambiguous endings are checked here; the
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
        # A long definition is usually a descriptive phrase ("About to go off
        # perhaps" = TICKING), where the -ing test says nothing; only short ones
        # are meaningful.
        if is_gerund(ans) and len(dwords) <= 2 and not any(w.endswith("ing") for w in dwords):
            warnings.append(f"{tag}: answer ends -ING but no word in the definition does "
                            f"({d.get('text')!r}). The definition must substitute "
                            f"for the answer in a sentence: say the swap out loud. If it "
                            f"does not, the definition is probably a different span of the "
                            f"clue; if the setter really is loose, give the definition a "
                            f"`note` saying in a sentence why that is fair")
        # Multi-word answers are phrases whose trailing -S is rarely the head's
        # inflection: PICK UP THE PIECES is a verb phrase, defined by a verb phrase.
        elif (is_plural(ans) and " " not in (ann.get("answer") or "")
              and not any(w.endswith("s") for w in dwords) and not (set(dwords) & INVARIANT_PLURALS)):
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
        import wordplay
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
        if len(extra) + len(missing) > SETTER_ERROR_LETTERS:
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
    if len(extra) + len(missing) > SETTER_ERROR_LETTERS:
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


def check_every_clue_is_annotated(entries, errors, warnings, misses=(), corpus=False, reopened=()):
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
    """
    continuations = groups.leader_of(entries)
    blank = []
    for e in entries:
        if e.get("annotation"):
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
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
        f"loudly instead: it names the clue, a blank does not.{likely} Only a "
        f"clue you cannot parse without inventing wordplay stays null: the "
        f"puzzle fails and can be retried, whereas a confident wrong "
        f"explanation ships and nothing catches it")


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

#: {(puzzle id, entry id): (fields, why)}: clues where an annotating run checked
#: our reading against the blog's and kept ours. `fields` is a comma list of
#: definition, type and blocks; `why` is one sentence on why ours stands. Filed
#: by tools/annotate_check.py from an entry's `blogDisagree`, never by hand. A
#: blog is a second opinion, not the key (bloggers underline wordplay, miss a
#: piece, call a container a charade), so a disagreement is a prompt to look,
#: and this is the record that someone looked. tools/blog_compare.py counts
#: what is left.
BLOG_DISAGREE = load_source_table("blog_disagree")
#: The names a blog_disagree row's first field may hold.
BLOG_FIELDS = ("definition", "type", "blocks")


def blog_kept(puzzle, e, field):
    """Whether a run has already checked `field` of entry `e` against the blog
    and filed why ours stands (BLOG_DISAGREE)."""
    row = BLOG_DISAGREE.get((puzzle.get("id"), entry_id(e)))
    return bool(row) and field in [f.strip() for f in row[0].split(",")]


def blog_file_hint(field):
    """The one line every blog disagreement ends with: what to do about it."""
    return (f"Fix ours if the blog is right; if ours stands, add "
            f"\"blogDisagree\": [\"{field}\", \"<one sentence: why ours is right>\"] to the entry")


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
        if not defined or not theirs or blog_kept(puzzle, e, "definition"):
            continue
        ours = set().union(*map(words, defined))
        if not any(words(t) & ours for t in theirs):
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            warnings.append(
                f"{tag}: definition {' / '.join(defined)!r} shares no word with the "
                f"definition {row['name']} underlined ({' / '.join(map(repr, theirs))}, "
                f"{row['url']}). Bloggers slip too (theirs may be wordplay). " + blog_file_hint("definition"))


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
        if not ann.get("blocks") or not theirs or blog_kept(puzzle, e, "blocks"):
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
                f"parse misses a piece. " + blog_file_hint("blocks"))


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
        if "cryptic_definition" not in types_of(ann) or blog_kept(puzzle, e, "type"):
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
                f"{clue_types.label(named[0])} is there, annotate it. " + blog_file_hint("type"))


#: Clue types by what the clue is made of. Two types in one family are a
#: labelling choice (a cryptic or a double definition, a container or a
#: charade, a deletion or a selection) and are never reported; two readings
#: with no family in common disagree about how the clue works.
TYPE_FAMILIES = {
    "cryptic_definition": "definition only", "double_definition": "definition only",
    "charade": "assembly", "container": "assembly", "deletion": "assembly",
    "letter_selection": "assembly", "hidden_word": "assembly", "reversal": "assembly",
    "substitution": "assembly", "cycling": "assembly", "move": "assembly", "palindrome": "assembly",
    "anagram": "anagram", "homophone": "homophone", "spoonerism": "spoonerism",
}


def type_families(types):
    return {TYPE_FAMILIES[t] for t in types if t in TYPE_FAMILIES}


def check_type_against_blog(puzzle, warnings):
    """Our clue type should share a family (TYPE_FAMILIES) with the blogger's.

    Measured 2026-10-12 over 205,390 clues both sides type: 1.9% have no type
    in common, mostly labelling (cryptic against double definition 952,
    container against charade 367). Families leave the ones that say the clue
    works another way: double definition against charade (717), a definition
    against wordplay, an anagram the other side does not see. &lit is a whole
    clue read twice and goes with anything; a type tools/letter_facts.py
    inferred is not the blogger's and is skipped; ours as a cryptic definition
    against named wordplay is check_cryptic_definition_against_blog's."""
    row = blog_facts_for(puzzle)
    if not row:
        return
    for e in puzzle["entries"]:
        ann = e.get("annotation") or {}
        fact = row["entries"].get(entry_id(e)) or {}
        theirs, ours = list(fact.get("type") or []), types_of(ann)
        if (not theirs or not ours or "type" in fact.get("inferred", ())
                or "and_lit" in theirs or "and_lit" in ours or blog_kept(puzzle, e, "type")):
            continue
        if "cryptic_definition" in ours and any(w in theirs for w in BLOG_WORDPLAY):
            continue
        a, b = type_families(ours), type_families(theirs)
        if a and b and not a & b:
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            warnings.append(
                f"{tag}: typed {clue_types.labels(ours)!r}, but {row['name']} parses it as "
                f"{'at least ' if fact.get('typeCore') else ''}{clue_types.labels(theirs)!r} "
                f"({row['url']}). One of the two reads the clue another way. "
                + blog_file_hint("type"))


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


# Mechanisms where the blocks legitimately do not add up to the answer: a
# deletion, substitution or composite anagram names letters that are taken away,
# a move names letters its fodder already holds (ALBION, and the O it moves),
# and the three definition-only types plus the sound types claim no letters at all.
UNBALANCED_TYPES = ("deletion", "substitution", "move", "composite_anagram", "cryptic_definition",
                    "double_definition", "homophone", "spoonerism", "and_lit")

# A clue whose whole mechanism is one letter selection hands over those letters
# and nothing else, so when the answer is longer the answer is DESCRIBING the
# extraction rather than being built from it — 12423 16A, MIDDLE OF NOWHERE.
# Matched exactly: a compound that merely includes a selection
# (charade + letter_selection) does have to add up.
UNBALANCED_EXACT_TYPES = (["letter_selection"],)

# The three block-shape checks below allow no per-puzzle tolerance. None of them
# has a false positive, so none has a reason to let a hit through: a tolerance
# would keep forgiving the same defect on every puzzle fetched.


def blocks_miss_letters(ann, entry):
    """Whether check_blocks_account_for_answer reports this entry: its blocks give
    letters, not the answer's, and its type builds from them."""
    atype = types_of(ann)
    if any(x in atype for x in UNBALANCED_TYPES) or atype in UNBALANCED_EXACT_TYPES:
        return False
    got = "".join(letters(b.get("gives")) for b in ann.get("blocks") or [] if isinstance(b, dict))
    want = block_letters(ann, wordplay_letters(ann, entry))
    # A repeat shows one copy as its blocks (annotation.repeat_copy_letters).
    got2 = got + annotation.repeat_copy_letters(ann.get("wordplay"))
    return bool(got) and sorted(got) != sorted(want) and sorted(got2) != sorted(want) \
        and sorted(got) != sorted(slipped_letters(ann, want))


def slipped_letters(ann, want):
    """`want` as the blocks hand it over when an anagram of the annotation is a
    setter's slip (fodder that does not hold the letters it gives): its fodder
    as printed in place of what it gives. check_anagram_letters lets such an
    anagram stand only when tools/data/setter_error.json names it, so this
    forgives nothing else. (An unchecked step may instead have respelt a block to
    hide the slip; its blocks then add up to `want` itself.)"""
    from collections import Counter
    have = Counter(want)
    for a in assembly(ann).get("anagrams") or []:
        if not isinstance(a, dict):
            continue
        f, g = Counter(letters(a.get("fodder") or "")), Counter(letters(a.get("gives") or ""))
        if f != g and not (g - have):
            have = have - g + f
    return "".join(sorted(have.elements()))


def missing_link_word_fix(ann, extra, missing):
    """The exact edit when the blocks' missing letters are a word filed under
    linkWords: that word is fodder, so it becomes a block and leaves linkWords."""
    if extra or not missing:
        return ""
    for w in ann.get("linkWords") or []:
        if isinstance(w, str) and sorted(letters(w)) == sorted(missing):
            return (f". {w!r} is in linkWords but its letters are the missing ones: "
                    f"remove it from linkWords and add the block "
                    f"{{\"clueFragment\": {json.dumps(w)}, \"gives\": {json.dumps(letters(w))}}}")
    return ""


MAX_SURPLUS_EDITS = 3


def surplus_letters_fix(ann, extra, missing, want):
    """The single-block edits that take exactly the surplus letters away when the
    blocks give too many and none too few: drop a block whose letters are the
    surplus, or cut the surplus off one block's ends. Edits that also leave the
    blocks spelling the answer in order are listed first."""
    if missing or not extra:
        return ""
    blocks = [b for b in ann.get("blocks") or [] if isinstance(b, dict)]
    gives = [letters(b.get("gives")) for b in blocks]
    edits = []
    for i, g in enumerate(gives):
        if sorted(g) == sorted(extra):
            edits.append((i, ""))
            continue
        for k in range(len(extra) + 1):
            cut = g[k:len(g) - (len(extra) - k)]
            if cut and sorted(g[:k] + g[len(g) - (len(extra) - k):]) == sorted(extra) \
                    and (i, cut) not in edits:
                edits.append((i, cut))
    if not edits:
        return ""
    edits.sort(key=lambda e: "".join(e[1] if j == e[0] else g
                                     for j, g in enumerate(gives)) != want)
    said = []
    for i, cut in edits[:MAX_SURPLUS_EDITS]:
        frag = blocks[i].get("clueFragment")
        if cut:
            said.append(f"block {frag!r} gives {cut!r}, not {gives[i]!r}")
        else:
            said.append(f"drop block {frag!r} > {gives[i]!r}"
                        + (" (a word used for nothing goes in linkWords)" if frag else ""))
    head = ("one edit makes them add up: " if len(said) == 1 else
            "each of these single edits makes them add up — make the one the clue supports: ")
    tail = (". A cut block's note must name the cut word; if the clue itself removes "
            "the letters, type it deletion and list the indicator"
            if any(cut for _, cut in edits[:MAX_SURPLUS_EDITS]) else "")
    return f". {head}{'; or '.join(said)}{tail}"


def check_blocks_account_for_answer(entries, errors, warnings):
    """The letters the blocks hand over have to be the answer's letters.

    Not a restatement of the `pieces` check: `pieces` is the annotator's own
    summary and is checked against the answer, so a parse can have immaculate
    pieces and blocks that say something else entirely (pieces T/RIG/GER with
    blocks T + R + IG for TRIGGER). The blocks are what the app renders — they
    are what the learner reads.

    CALIBRATION: 0 of 671. The one exception, 12423 16A (MIDDLE OF NOWHERE), is
    not a defect: the answer describes where the H sits rather than being built
    out of letters, which is a property of its type, so UNBALANCED_EXACT_TYPES
    exempts that type. Any other hit is an error.
    """
    hits = []
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann:
            continue
        if blocks_miss_letters(ann, e):
            got = "".join(letters(b.get("gives")) for b in ann.get("blocks", []))
            want = block_letters(ann, wordplay_letters(ann, e))
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            hits.append(tag)
            extra, missing = multiset_diff(got, want)
            warnings.append(
                f"{tag}: the blocks give {got!r}, but the answer is {want!r}"
                + (f" (extra {extra!r})" if extra else "")
                + (f" (missing {missing!r})" if missing else "")
                + " — the blocks are what the learner actually reads, so they have "
                  "to be the parse, not a sketch of one"
                + missing_link_word_fix(ann, extra, missing)
                + surplus_letters_fix(ann, extra, missing, want))
    if hits:
        errors.append(
            f"puzzle: {len(hits)} clue(s) ({', '.join(hits)}) have blocks whose letters "
            f"are not the answer's. Letters that don't add up mean the wordplay was "
            f"described rather than worked out, or, when they build a real word a "
            f"letter or two from a printed answer that is not one, that the key is "
            f"misprinted: give that _ann entry \"answerTypo\": [\"<letters the "
            f"wordplay builds>\", \"<evidence>\"]")


def check_blocks_decompose(entries, errors, warnings):
    """If `pieces` takes the answer apart, the blocks must take it apart too.

    A charade with `pieces: ["SOD", "DEN"]` and one block reading
    `"Two types of earth" > SODDEN` has named the mechanism and then not
    performed it, which is the whole of what a learner came for.

    CALIBRATION: 0 of 398 clues with 2+ pieces, and errors on any hit. There is
    no case where the annotator is entitled to both fields disagreeing — one of
    the two is wrong, and which one is the annotator's call (ATOM: its wordplay
    yields the single string "A TO M" and nothing clues the TO, so the block is
    right and `pieces` describes a parse not done).
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
        # whole fodder is exactly right there.
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

    The letters of such a clue are correct; the ORDER is the teaching, and it is
    wrong. Backlog size is not a reason to drop a check, only false positives
    are, and under the tight scope below there are none.

    SCOPE is the whole trick. It applies only to `type == ["charade"]` exactly.
    Any positional mechanism in the mix legitimately lists blocks out of final
    order: a container's inner piece goes inside rather than after, and a
    rotation is *defined* by blocks assembled before the spin — 30079 7D TSUNAMIS
    is A + MIST + SUN and only then cycled, which a looser scope flags and which
    is perfectly annotated. Widening from `charade` to "charade and nothing
    positional" adds 4 hits, 2 of them false. So it stays narrow.

    CALIBRATION: 10 of 127 pure charades, every one a genuine misordering (1388
    23A, 30039 24A, 30041 28D, 30042 8D, 30043 7D, 30044 19D, 30078 25A, 30079
    8D/11A/22A). Each clue still warns with its own letters, and any hit fails the puzzle: the
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


#: What the block warning says in place of "has no note", so the ratchet's
#: indicators.note marker ("has no note") cannot count it.
BLOCK_NO_NOTE = "has no block note"


def check_blocks_carry_notes(entries, warnings):
    """A block that claims letters has to say why it gets them.

    The `note` is where the convention lives — `worker` = ANT, `setter` = ME —
    and it is the only field that can be wrong in a way the letters can't reveal.
    An unexplained block is where an invented one hides. CALIBRATION: 1 of 1347 across this repo (30044 2D, `a` > A,
    where there is genuinely nothing to say). Warning only, for that reason.
    """
    for e in entries:
        ann = e.get("annotation") or {}
        if not ann:
            continue
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        for b in ann.get("blocks", []):
            if not letters(b.get("gives")) or str(b.get("note") or "").strip():
                continue
            # No clue words: nothing to key a note on (`notes` is keyed by the
            # fragment, so the advice below would say `notes: {'': ...}`). The
            # block is either preamble-supplied letters or already an error in
            # _validate_puzzle ("a block with no clueFragment"); one cause, one line.
            if not str(b.get("clueFragment") or "").strip():
                continue
            # A fragment that is its own letters ('a' > A, 'in' > IN) has
            # nothing to teach and app.js shows its letters without a note.
            if letters(b.get("clueFragment")) == letters(b.get("gives")):
                continue
            frag = str(b.get("clueFragment") or "")
            warnings.append(
                f"{tag}: block {b.get('clueFragment')!r} > {b.get('gives')!r} {BLOCK_NO_NOTE}. "
                f"Say why those words give those letters — that sentence is the "
                f"teaching, and its absence is how an invented block hides. In the "
                f"annotation add the leaf's words to `notes`: \"notes\": {{{frag!r}: "
                f"\"<why {frag!r} gives {b.get('gives')}>\"}} (wp `[{frag}]{b.get('gives')}`); "
                f"this is a block note, not an indicator note")


#: A tag, an entity, or a tag's remnant with its "<" lost to a reader that
#: began mid-tag: genius's article reader filed ` class="dcr-47amn7">` as
#: the preamble of 25 puzzles.
MARKUP_RE = re.compile(r"</?[a-zA-Z][^>]*>|&(?:[a-zA-Z]+|#\d+);"
                       r"|\b(?:class|style|id|href|src|data-[\w-]+)\s*=\s*[\"'][^\"']*[\"']"
                       r"|\bdcr-[a-z0-9]{4,}\b")
# Bytes 0x80-0x9F are punctuation in Windows-1252 and unprintable control
# codes in Unicode, so a source decoded as latin-1 turns every dash and curly
# quote into one of these and the browser draws a box. Some of them reached
# the site. Repairing them is a lookup, so the message carries it.
CP1252_C1 = {0x82: "\u201a", 0x83: "\u0192", 0x84: "\u201e", 0x85: "\u2026",
             0x86: "\u2020", 0x87: "\u2021", 0x88: "\u02c6", 0x89: "\u2030",
             0x8b: "\u2039", 0x91: "\u2018", 0x92: "\u2019", 0x93: "\u201c",
             0x94: "\u201d", 0x95: "\u2022", 0x96: "\u2013", 0x97: "\u2014",
             0x99: "\u2122", 0x9b: "\u203a"}
C1_RE = re.compile(r"[\x80-\x9f\ufffd]")


def verbatim_hint(fragment, clue):
    """What to say when a fragment is not verbatim in its clue: the clue's own
    spelling of it (definitions.respell), or the clue words its words skip."""
    spelt = definitions.respell(str(fragment), clue)
    if spelt != fragment:
        return (f" — the clue spells it {spelt!r}: copy it from the file rather "
                f"than retyping it")
    misread = respelt_words(str(fragment), clue)
    if misread:
        return (f" — the clue prints {' and '.join(f'{c!r} where this has {f!r}' for c, f in misread)}. "
                f"Quote the clue as it stands; if the page prints your word and the "
                f"clue is misread, give the entry `printedClue`: [\"<clue as printed, "
                f"no count>\", \"OCR misread: <what the wordplay needs>\"]")
    skipped = skipped_words(str(fragment), clue)
    if skipped:
        return (f" — its words are not consecutive in the clue, which prints "
                f"{' and '.join(map(repr, skipped))} between them. Quote one unbroken "
                f"run of clue words; the words between are their own block, "
                f"indicator or link word")
    return (" — copy it character for character from the clue, which is the "
            "only text it may be")


def respelt_words(fragment, clue):
    """[(clue word, fragment word)] where `fragment` is a run of clue words
    with one or two of them spelt a letter or two differently ("jumbled" for
    the clue's "iumbled"): a clue misread, or retyped. [] otherwise."""
    fold = lambda w: w.translate(definitions.LOOKALIKES).casefold()
    want = definitions.WORD.findall(fragment)
    words = definitions.WORD.findall(clue)
    for k in range(len(words) - len(want) + 1):
        pairs = [(c, f) for c, f in zip(words[k:k + len(want)], want) if fold(c) != fold(f)]
        if pairs and len(pairs) <= 2 and len(pairs) < len(want) + (len(want) == 1) and all(
                len(f) > 2 and difflib.SequenceMatcher(None, fold(c), fold(f)).ratio() >= 0.75
                for c, f in pairs):
            return pairs
    return []


def skipped_words(fragment, clue):
    """The clue words between `fragment`'s words, where its words are clue
    words in clue order with others between them: the fewest skipped of any
    such reading. [] when there is no such reading."""
    fold = lambda w: w.translate(definitions.LOOKALIKES).casefold()
    want = [fold(w) for w in definitions.WORD.findall(fragment)]
    words = list(definitions.WORD.finditer(clue))
    best = None
    for k in range(len(words)):
        at, gaps = k, []
        for j, w in enumerate(want):
            start = at
            while at < len(words) and fold(words[at].group()) != w:
                at += 1
            if at == len(words) or (j == 0 and at != k):
                break
            if at > start and j:
                gaps.append(clue[words[start].start():words[at - 1].end()])
            at += 1
        else:
            if want and gaps and (best is None or len(gaps) < len(best)):
                best = gaps
    return best or []


def is_pointer_text(e):
    """Is entry e's clue a bare pointer ("See 17", counted or not)?"""
    return groups.is_pointer(e["clue"].get("text", ""), counted=True)


def check_groups(puzzle, errors):
    """A linked answer is one answer over several lights. Its leader carries
    `group`, the answer's lights in word order, and the whole annotation;
    every other light carries neither a group nor an annotation. No group at
    all is the ordinary case: the entry is its own answer.

    The leader is the light that prints the clue, and it is first in its
    group unless the paper printed the clue on a later light of the answer:
    cryptic-21673 prints VESTED INTEREST's clue at 26-across, so 26-across
    holds ["25-across", "26-across"]. Each light before such a leader prints
    no clue of its own (blank, or a pointer), or is named in `selfClued`
    (cryptic-23821's 23-down RIGHT has its own clue and also starts 22-across's
    RIGHT AS RAIN).

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
        also = e.get("alsoLeads") or []
        if also and not e.get("group"):
            errors.append(f"{entry_id(e)}: alsoLeads with no group. A light's first "
                          f"linked answer is its own clue and group; alsoLeads holds the rest")
        seen = [e.get("group")]
        for item in also:
            if item.get("group") in seen:
                errors.append(f"{entry_id(e)}: alsoLeads repeats the group {item.get('group')}. "
                              f"Each linked answer it starts is listed once")
            seen.append(item.get("group"))
    for e, holder in groups.linked(puzzle["entries"]):
        group = holder["group"]
        if len(set(group)) < 2:
            errors.append(f"{entry_id(e)}: group {group} must name two or more "
                          f"different lights. A clue that is its own answer "
                          f"carries no group at all.")
            continue
        if entry_id(e) not in group:
            errors.append(f"{entry_id(e)}: group {group} does not name this entry. "
                          f"Only the leader carries the group, and it is one of its lights")
            continue
        clued = groups.self_clued(holder)
        for gid in sorted(clued - set(group) | (clued & {entry_id(e)})):
            errors.append(f"{entry_id(e)}: selfClued names {gid}, which is not another "
                          f"light of its group {group}")
        if group[0] != entry_id(e):
            if is_pointer_text(e) or not has_words(e["clue"].get("text", "")):
                errors.append(f"{entry_id(e)}: group {group} starts on another light, "
                              f"but this entry prints no clue to lead it from. A group "
                              f"starts with its leader unless the paper printed the "
                              f"clue on a later light")
            for gid in group[:group.index(entry_id(e))]:
                other = by_id.get(gid)
                if other is None or gid in clued:
                    continue
                if has_words(other["clue"].get("text", "")) and not is_pointer_text(other):
                    errors.append(f"{entry_id(e)}: group {group} starts on {gid}, whose "
                                  f"clue is a clue of its own. A leader prints its clue "
                                  f"on a later light only when the answer's first light "
                                  f"prints none (blank, or \"See N\"), or names that "
                                  f"light in selfClued")
        for gid in dict.fromkeys(group):
            if gid == entry_id(e):
                continue                  # the leader, or an answer that repeats it
            other = by_id.get(gid)
            if other is None:
                errors.append(f"{entry_id(e)}: group names {gid}, which is not in this puzzle")
                continue
            if gid in clued:
                # An answer of its own that this one also runs through: it
                # keeps its own clue (cryptic-21893's THERE in BATTLE HYMN OF
                # THE REPUBLIC), or it continues another answer (cryptic-25126's
                # MINOR, "See 17", ends both MAJOR AND MINOR and ASIA MINOR).
                # A pointer continuing nothing else is a plain continuation.
                elsewhere = any(gid in h["group"] and gid != entry_id(lead)
                                and gid not in groups.self_clued(h)
                                for lead, h in groups.linked(puzzle["entries"]))
                if is_pointer_text(other) and not elsewhere:
                    errors.append(f"{gid}: in {entry_id(e)}'s selfClued, but its clue is a "
                                  f"pointer and it continues no other answer; a light whose "
                                  f"clue is \"See N\" is a plain continuation")
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
    escaped, so a tag reaches the solver as a tag: "<span>Film part of </span><i>
    Black Narcissus</i>?" would appear on the page verbatim. Both papers ship clues as
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
        lost = [t for t in e["clue"].get("asPrinted") or () if t not in text.split()]
        if lost:
            errors.append(f"{entry_id(e)}: clue.asPrinted {lost!r} is no token of the clue text "
                          f"{text!r}: it keeps the print's own spelling of words in the text, so "
                          f"an edit to the text must carry it.")

    text_errors(puzzle, errors)


def text_errors(obj, errors):
    """check_no_markup's walk: every string in `obj`, a puzzle or a
    clues-only record, free of markup and of C1 control characters."""
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
    walk(obj, "")


def committed_entries(path):
    """{entry id: entry} as HEAD has this puzzle, or None when it is not committed."""
    was = committed_top(path)
    return None if was is None else {entry_id(e): e for e in was.get("entries", [])}


def committed_top(path):
    """The puzzle as HEAD has it, or None when it is not committed."""
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        return None
    shown = subprocess.run(["git", "show", f"HEAD:{rel.as_posix()}"], cwd=ROOT,
                           capture_output=True, text=True, check=False)
    return None if shown.returncode else json.loads(shown.stdout)


def check_theme_clue_unchanged(puzzle, path, errors):
    """`themeClue` is filed at filing or review, never by an annotator: it is
    what lets a run's clue-word-less blocks stand, so a run that wrote it
    would be granting itself the exception. A file whose themeClue differs
    from HEAD's (added, changed or dropped) is refused."""
    was = committed_top(path)
    if was is None:
        return
    if was.get("themeClue") != puzzle.get("themeClue"):
        errors.append(
            f"themeClue changed from {was.get('themeClue')!r} to "
            f"{puzzle.get('themeClue')!r}. It names the clue that states the theme "
            f"and is filed by hand, not by the annotator: put it back. If a clue "
            f"states the theme and none is filed, withdraw and say which")


def check_spelling_kept(puzzle, path, errors):
    """A re-annotation may not drop the `spelling` HEAD's annotation of the same
    answer carries. The `spelling.unsaid` ratchet counts clues per puzzle, not
    which clue, so an allowance left over from before the spelling was filled
    (book-26021 22D, APERÇU, 10-17) absorbed the loss and CI caught it
    hours later. Comparing with HEAD sees it in the run itself."""
    committed = committed_entries(path)
    if committed is None:
        return
    for e in puzzle["entries"]:
        was = committed.get(entry_id(e))
        if not was or (was.get("solution") or "").upper() != (e.get("solution") or "").upper():
            continue
        spelling = (was.get("annotation") or {}).get("spelling")
        if spelling and e.get("annotation") and not e["annotation"].get("spelling"):
            errors.append(
                f"{entry_id(e)}: the committed annotation spells the answer {spelling!r} "
                f"and this one has no spelling. Keep it: in the model's shape write "
                f"`answer` as {spelling!r}")


#: The letters an OCR'd clue's SOURCE_CLUE_WRONG correction may change: a
#: misread letter or two ("judge" for "fudge", "rn" for "m"), never a reword.
OCR_MISREAD_EDITS = 3


def edit_distance(a, b):
    """Levenshtein distance between two strings."""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def ocr_misread_edits(served, printed):
    """The letters an OCR'd clue's correction changes, by clue_words. A run of
    capitals the OCR glued on before the clue ("BEBGOWNAURWN A second
    Cromwell?", a page header read into the column) is stray text dropped,
    not the clue reworded, so it is measured without that run when the
    printed clue does not open with it."""
    edits = edit_distance(clue_words(served), clue_words(printed))
    head = re.match(r"\s*([A-Z]{6,})\s+(?=\S)", served or "")
    if head and not clue_words(printed).startswith(head.group(1).lower()):
        edits = min(edits, edit_distance(clue_words(served[head.end():]), clue_words(printed)))
    return edits


#: How a SOURCE_CLUE_WRONG row's evidence opens when its clue was read off
#: the printed page (tools/scan_crop.py), not mended from the wordplay.
SCAN_READ = "Scan reads: "


def clue_row_problems(served, printed, why):
    """What stops a SOURCE_CLUE_WRONG row [served, printed, why] being a
    correction with evidence: it must change the text, and its note must argue
    the case (an OCR misread needs only a short one, a clue read off the scan
    is evidenced by the page however short the clue). One rule for the filer
    (annotate_check) and tools/test_source_answer_wrong.py."""
    floor = (len(SCAN_READ) + 1 if why.startswith(SCAN_READ)
             else 25 if why.startswith("OCR misread: ") else 40)
    problems = []
    if served.strip() == printed.strip():
        problems.append("corrects nothing: the clue as printed is the clue as shown, "
                        "so put the corrected clue first and the evidence second")
    if len(why) < floor:
        problems.append(f"the evidence {why!r} is under {floor} characters: say what the "
                        f"OCR read and what the page prints")
    return problems


def scan_read(pid, eid):
    """Whether light `eid`'s SOURCE_CLUE_WRONG row was read off `pid`'s scan,
    which tools/scan_crop.py can show: a clue read off the page is the
    print's, however far the OCR strayed from it."""
    why = SOURCE_CLUE_WRONG.get((pid, eid), (None, None, ""))[2]
    if not why.startswith(SCAN_READ):
        return False
    import scan_crop
    try:
        scan_crop.crop(pid)
    except scan_crop.NoCrop:
        return False
    return True


def check_clue_unchanged(puzzle, path, errors):
    """An annotation explains the clue it was written against, and the clue is
    the source's. An annotated entry whose clue's words differ from the
    committed file's is a run that rewrote the clue to suit its parse, unless
    the new words are the ones fetch_puzzle.SOURCE_CLUE_WRONG prints for that
    light: a correction filed there is what every re-fetch writes, so the
    annotation written for it stands in the same run. An OCR'd clue
    (provenance.OCR_CHANNELS) takes one only within OCR_MISREAD_EDITS letters,
    unless it was read off the scan (scan_read). Typography (quotes,
    dashes, accents, spacing) is not a different clue."""
    committed = committed_entries(path)
    if committed is None:
        return                  # not committed yet: nothing to compare with
    was = {i: enumeration.printed(e["clue"]) for i, e in committed.items()}
    for e in puzzle["entries"]:
        now = enumeration.printed(e["clue"])
        if (e.get("annotation") is None or entry_id(e) not in was
                or clue_words(was[entry_id(e)]) == clue_words(now)):
            continue
        filed = corrected_clue(puzzle.get("id"), entry_id(e))
        ocr = (puzzle.get("source") or {}).get("retrievedFrom") in provenance.OCR_CHANNELS
        if filed is not None and clue_words(filed) == clue_words(e["clue"].get("text")):
            misread = ocr_misread_edits(was[entry_id(e)], filed)
            if not ocr or misread <= OCR_MISREAD_EDITS or scan_read(puzzle.get("id"), entry_id(e)):
                continue
            errors.append(
                f"{entry_id(e)}: SOURCE_CLUE_WRONG changes {misread} letters of the "
                f"OCR's {was[entry_id(e)]!r}; a misread is at most {OCR_MISREAD_EDITS} "
                f"(judge for fudge). A clue that needs more is not the OCR's to mend: "
                f"put it back and leave the entry null, unless the puzzle has a scan "
                f"(tools/scan_crop.py) and the row's evidence opens {SCAN_READ!r}")
            continue
        errors.append(
            f"{entry_id(e)}: clue changed from {was[entry_id(e)]!r} to {now!r} "
            f"under an annotation. The clue text is the source's, not the "
            f"annotator's: put it back, or, when the source serves it wrong, "
            f"give its _ann entry \"printedClue\": [\"<clue as printed, no "
            f"count>\", \"<evidence>\"], which files the change so it and this "
            f"annotation pass together")


def check_clue_rows_held(puzzle, errors):
    """A puzzle holds every tools/data/source_clue_wrong.json row filed for
    it: a clue still as the source served it, where the row prints it
    otherwise, ships the misprint beside the row that mends it.
    tools/annotate_check.py writes the rows in (apply_annotations.mend_clues)."""
    for e in puzzle["entries"]:
        text = e["clue"].get("text")
        printed = source_clue(puzzle.get("id"), entry_id(e), text)
        if clue_words(printed) != clue_words(text):
            errors.append(
                f"{entry_id(e)}: tools/data/source_clue_wrong.json prints this clue "
                f"as {printed!r}, but the file holds {text!r}. Run python3 "
                f"tools/annotate_check.py {puzzle.get('id')}, which writes the row in")


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
# "capital of" and the block "Bahrain" (telegraph-31356 24D). A block that swallows its selector teaches the
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
    import annotation
    committed = committed_entries(path) or {}
    # Changed is judged on the stored annotation; the blocks are derived
    # (the file stores a tree, so they come from view()).
    for e, seen in zip(puzzle["entries"], annotation.view_puzzle(puzzle)["entries"]):
        ann = e.get("annotation")
        if not isinstance(ann, dict) or ann == (committed.get(entry_id(e)) or {}).get("annotation"):
            continue
        for b in (seen.get("annotation") or {}).get("blocks") or []:
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
    """(annotated, errors, warnings). A light leading more than one linked
    answer (groups.holders) has each alsoLeads answer checked as if it were
    the light's own clue, group and annotation (groups.as_leader); those
    findings name it "<tag> alsoLeads[k]".

    The file is checked through annotation.view_puzzle(): its trees are
    evaluated (one that does not give the answer is an error), and every
    check below reads the fields view() derives (blocks, assembly, type)."""
    schema_errors = [f"schema: {p}" for p in puzzle_schema.validate(puzzle)]
    treed = {_tag_of(puzzle, where) for where, _, ann in puzzle_schema.annotations(puzzle)
             if ann.get("wordplay")}
    puzzle, tree_errors, tree_warnings = tree_view(puzzle)
    annotated, errors, warnings = _validate_puzzle(puzzle, corpus, schema=False)
    errors[:0] = schema_errors + tree_errors
    warnings[:0] = tree_warnings
    for i, e in enumerate(puzzle["entries"]):
        for k, item in enumerate(e.get("alsoLeads") or []):
            if not item.get("annotation"):
                continue
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            n, errs, warns = _validate_puzzle(groups.as_leader(puzzle, i, k), corpus, schema=False)
            mine = (f"{tag}:", f"{entry_id(e)}:")
            annotated += 1
            errors += [f"{tag} alsoLeads[{k}]:{m.split(':', 1)[1]}" for m in errs if m.startswith(mine)]
            warnings += [f"{tag} alsoLeads[{k}]:{m.split(':', 1)[1]}" for m in warns if m.startswith(mine)]
    # A clue entered off the grid (offGrid) is checked on a light of its own
    # (groups.alone); its findings name it "<k>-offgrid".
    for cid, item in groups.off_grid(puzzle):
        if not item.get("annotation"):
            continue
        k = cid.split("-")[0]
        n, errs, warns = _validate_puzzle(groups.alone(puzzle, cid), corpus, schema=False)
        mine = (f"{k}A:", f"{k}-across:")
        annotated += n
        errors += [f"{cid}:{m.split(':', 1)[1]}" for m in errs if m.startswith(mine)]
        warnings += [f"{cid}:{m.split(':', 1)[1]}" for m in warns if m.startswith(mine)]
    # A clue stored as a wordplay tree has nothing to write under `assembly`:
    # the schema refuses the key, and view() derives it. Either the evaluator
    # checked every node against the answer (a tree that fails is an error
    # above, and is left out of the view), or the tree has an unchecked step,
    # which its own warning and ratchet (wordplay.unchecked) already count. A
    # top-level deletion, selection or substitution builds the answer in one
    # chunk, so view() gives it no `pieces`, and "Give `assembly.pieces`" sent
    # runs to write a key apply_annotations then refused.
    warnings = [w for w in warnings if w.split(":", 1)[0] not in treed
                or not any(m in w for m in SUPERSEDED_BY_TREE)]
    return annotated, errors, warnings


UNCHECKED_STEP = "unchecked wordplay step"
#: The finding for a charade filed directly under an anagram. An anagram's
#: fodder is one pool of letters, so its pieces are the anagram's own parts
#: (`ana(x + y)` stores x and y there): nothing under it is joined in order, and
#: a charade label there says something that is not happening. wordplay.parse
#: cannot write one; the ratchet (wordplay.anagramCharade) lets a puzzle keep
#: the ones tools/flatten_anagram_fodder.py could not flatten as they stand
#: (a join with an indicator of its own, or an unchecked one), and no more.
ANAGRAM_CHARADE = "charade directly under an anagram"


def _stand_in_piece(p):
    """A fodder piece that is not the clue's own words scrambled: an abbreviation or synonym
    leaf (a selection like first(x) is a common legitimate fodder letter, so not one)."""
    if "op" in p:
        return False
    g, w = wordplay.letters(p.get("gives")), wordplay.letters(p.get("words"))
    return bool(p.get("select") or p.get("soundsLike") or (g and g != w and sorted(g) != sorted(w)))


def _pulled_edges(tree, node, j, k):
    """A copy of `tree` with the first j and last k parts of anagram `node` taken out of it and
    set beside it in a charade (the answer's edge letters standing outside the scramble)."""
    t = copy.deepcopy(tree)
    stack = [(t, None, 0)]
    while stack:
        cur, par, i = stack.pop()
        if cur.get("op") == "anagram" and cur.get("parts") == node.get("parts") and cur.get("indicators") == node.get("indicators"):
            mid = {key: v for key, v in cur.items() if key != "parts"}
            mid["parts"] = cur["parts"][j:len(cur["parts"]) - k]
            new = {"op": "charade", "parts": cur["parts"][:j] + [mid] + cur["parts"][len(cur["parts"]) - k:]}
            if par is None:
                return new
            par["parts"][i] = new
            return t
        stack += [(p, cur, x) for x, p in enumerate(cur.get("parts") or []) if isinstance(p, dict)]
    return None


def anagram_edge_pieces(tree, answer, stand=_stand_in_piece):
    """How many anagrams in `tree` hold, at the edge of their own fodder (first or last parts, in
    clue order), abbreviation / synonym / sub-operation pieces whose letters stand at that edge of
    the scramble's output: the tree still gives the answer with those pieces taken out of the
    anagram and set beside it. (Paul 10-19: a letter correctly placed outside the anagram should
    not be in it.) Needs the answer."""
    if not answer or not isinstance(tree, dict):
        return 0
    try:
        wordplay.evaluate(copy.deepcopy(tree), answer)
    except Exception:
        return 0
    found, stack = 0, [tree]
    while stack:
        node = stack.pop()
        parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        stack += parts
        if node.get("op") != "anagram" or node.get("unchecked") or len(parts) < 2 or len(parts) != len(node.get("parts")):
            continue
        st = [stand(p) for p in parts]
        lead = next((i for i, s in enumerate(st) if not s), len(st))
        trail = next((i for i, s in enumerate(reversed(st)) if not s), len(st))
        if lead >= len(st):
            continue
        done = False
        for j in range(lead + 1):
            for k in range(trail + 1):
                if j + k and j + k < len(parts) and not done:
                    cand = _pulled_edges(tree, node, j, k)
                    try:
                        wordplay.evaluate(cand, answer)
                        done = True
                    except Exception:
                        pass
        found += done
    return found


def anagram_charades(tree, answer=None):
    """How many charades sit directly under an anagram anywhere in `tree`, plus (given the
    answer) how many anagrams fold an edge piece of the answer into their fodder."""
    n, stack = 0, [tree] if isinstance(tree, dict) else []
    while stack:
        node = stack.pop()
        parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") == "anagram":
            n += sum(p.get("op") == "charade" for p in parts)
        stack += parts
    return n + anagram_edge_pieces(tree, answer)
#: Wordplay tree shapes that parse() cannot write or that say something the clue
#: does not. Each is a finding with its own ratchet field (below): a puzzle keeps
#: the clues it already has (tools/tidy_wordplay_shapes.py rewrote every one that
#: could be rewritten without changing view(), and recorded the rest), and no more.
CHARADE_IN_CHARADE = "charade directly inside a charade"
NO_INDICATOR = "operation with no indicator"
CDEF_REPEAT = "cryptic definition with more than one leaf"
STORED_ARITY = "operation with the wrong number of parts"
SPAN_OVERLAP = "clue words claimed twice"
IN_DEFINITION = "wordplay words inside the definition"
LEAF_FOLD = "leaf gives a stretch of its own words"
REPEATED_SELECTION = "same letter selection repeated word by word"
SINGLE_LEAF = "wordplay that is one leaf"
BARE_IN_CHARADE = "answer letters with no clue words in a charade"
ANAGRAM_OF_CONTAINER = "anagram wrapped around a container"
#: The tools/shape_suspects.py detectors that were hand-measured precise (a sample of
#: 20 each was wrong in every case), now rules. They count what the checked rules above
#: skip: an `unchecked` step (filed before trees were checked) can hold any part count,
#: and a leaf may swallow its own indicator word. Each has its ratchet field.
ARITY_INS = "container with other than two parts"
ARITY_OTHER = "deletion, substitution, homophone or one-armed op with the wrong part count"
DEL_SINGLE = "deletion with one part, so what it removes is not stated"
IND_IN_LEAF = "indicator word also inside a leaf"
SCRAMBLED_LEAF = "leaf gives its clue words' letters out of order"
#: Ops that are signalled by an indicator word. A charade, a cryptic definition,
#: a rebus, a reverse clue and a palindrome of the whole answer are not.
NEEDS_INDICATOR = frozenset(wordplay.ARITY) - {"cryptic", "rebus", "reverse", "palindrome"}


#: Until this time (epoch seconds) a push and CI let through a puzzle's shape
#: findings that have no allowance yet, because a pusher on code from before the
#: rules writes them without seeing the rule, and cannot sync onto the new code
#: while its commits are refused. A run's own `annotate_check` still reports every
#: one as an error. Before it passes, `tools/tidy_wordplay_shapes.py <puzzles>
#: --write` records what the grace let in as allowances (it adds puzzles the
#: list lacks), and the same commit sets this to 0.
SHAPE_GRACE_UNTIL = 0
SHAPE_GRACE_FIELDS = ("wordplay.anagramCharade", "wordplay.charadeInCharade", "wordplay.noIndicator",
                      "wordplay.cdefRepeat", "wordplay.arity", "wordplay.spanOverlap",
                      "wordplay.inDefinition", "wordplay.leafFold", "wordplay.repeatedSelection",
                      "wordplay.singleLeaf", "wordplay.bareInCharade", "wordplay.anagramOfContainer",
                      "wordplay.arityIns", "wordplay.arityOther", "wordplay.delSingle", "wordplay.indInLeaf", "wordplay.scrambledLeaf",
                      "wordplay.indFolded", "wordplay.fakeParts", "wordplay.paddingLeaf",
                      "wordplay.ddMissesWordplay", "spelling.unsaid")


def whole_rebus(ann, clue):
    """True when a viewed annotation is a rebus of the whole clue (every
    letter and figure in it), which leaves no words to define the answer."""
    blocks = ann.get("blocks") or []
    return (ann.get("type") == ["rebus"] and len(blocks) == 1
            and wordplay._alnum(blocks[0].get("clueFragment")) == wordplay._alnum(clue))


def _walk(tree):
    stack = [tree] if isinstance(tree, dict) else []
    while stack:
        node = stack.pop()
        yield node
        stack += [p for p in node.get("parts") or [] if isinstance(p, dict)]


def _stored_arity(op):
    """(fewest, most) parts a checked `op` node stores: a homophone or spoonerism
    keeps its spelling in `spelt` and a rebus or reverse clue its `reading`, not as a part,
    and an anagram's parts are its pool."""
    lo, hi = wordplay.ARITY.get(op, (2, 99))
    if op in ("homophone", "spoonerism", "rebus", "reverse"):
        lo, hi = lo - 1, hi - 1
    return (lo, 99) if op == "anagram" else (lo, hi)


def charade_in_charade(tree):
    """How many charades with no indicator sit directly inside another charade:
    a join of a join, which is the one charade written in pieces. Not under a
    charade with an indicator of its own ("A after B"): the order is stated
    there and each side is a group (independent-11509 19a, PF + ENIG after)."""
    n = 0
    for node in _walk(tree):
        if node.get("op") == "charade" and not node.get("unchecked") and not node.get("indicators"):
            n += sum(p.get("op") == "charade" and not p.get("indicators") and not p.get("unchecked")
                     and "gives" not in p for p in node.get("parts") or [] if isinstance(p, dict))
    return n


def _bare_shape(node):
    """`node` without its indicators and notes, all the way down: what makes two ops the same."""
    return {k: ([_bare_shape(p) if isinstance(p, dict) else p for p in v] if k == "parts" else v)
            for k, v in node.items() if k not in ("indicators", "note", "at")}


def _repeated_copies(tree):
    """ids of ops that repeat an earlier sibling exactly under a parent whose indicator is a
    repeat word (mephisto-3095 30a GRISGRIS: (ins<protected by>(GIS, R) + ins(GIS, R))<repeatedly>).
    The one indicator on the parent says the copy is made, so the copy needs none."""
    out = set()
    for parent in _walk(tree):
        if not any(set(re.findall(r"[a-z]+", str(i.get("text") or "").lower())) & REPEAT_WORDS
                   for i in parent.get("indicators") or []):
            continue
        seen = []
        for p in parent.get("parts") or []:
            if not isinstance(p, dict) or "op" not in p:
                continue
            shape = json.dumps(_bare_shape(p), sort_keys=True, default=str)
            if shape in seen:
                out.add(id(p))
            seen.append(shape)
    return out


_BOUNDARY_WORDS = re.compile(r"boundar|edge|border|extrem|outer|outside|limit|ends? of|fring|margin|perimeter", re.I)


def _moved_letter_ops(tree):
    """ids of ops one word of an indicator already covers (round 14 unindicatedBare flags): the
    substitution whose replacement is the replaced letters turned (UNITE, IT -> rev<turn>(IT)),
    and the first and last of one word as the two boundary letters ("to enter the boundaries of")."""
    out = set()
    for parent in _walk(tree):
        kids = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        # A letter taken out by a deletion and put back by the container (NERVE) is NOT accepted:
        # Paul ruled it an error, round 15 (a real move op is coming); it is flagged again.
        if parent.get("op") == "deletion" and any(_POSITION_WORD.search(str(i.get("text") or ""))
                                                  for i in parent.get("indicators") or []):
            # del<initially removed>(BALDER, first(bark)): the deletion's own words name the end it takes
            out.update(id(p) for p in kids[1:] if p.get("op") in ("first", "last") and not p.get("indicators"))
        if parent.get("op") == "container" and parent.get("indicators"):
            if any(_BOUNDARY_WORDS.search(str(i.get("text") or "")) for i in parent["indicators"]):
                for c in kids:
                    cs = [p for p in c.get("parts") or [] if isinstance(p, dict)]
                    if c.get("op") == "charade" and len(cs) == 2 and {p.get("op") for p in cs} == {"first", "last"} \
                            and len({json.dumps([(q.get("words"), q.get("at")) for q in p.get("parts") or []
                                                 if isinstance(q, dict)], default=str) for p in cs}) == 1:
                        out.update(id(p) for p in cs)
        if parent.get("op") == "substitution" and not parent.get("indicators") and len(kids) == 3:
            rep = kids[2]
            leaf = [p for p in rep.get("parts") or [] if isinstance(p, dict) and "op" not in p]
            if "op" in rep and rep.get("indicators") and len(leaf) == 1 and sorted(
                    wordplay.letters(leaf[0].get("gives"))) == sorted(wordplay.letters(kids[1].get("gives"))) != []:
                out.add(id(parent))
    return out


_SUBSTITUTE_WORD = re.compile(r"\b(usurp\w*|replac\w*|substitut\w*|supplant\w*|swap\w*|instead|displac\w*|ousting|"
                              r"ousts?|for|replaced by|exchang\w*)\b", re.I)
_CONTAINER_WORD = re.compile(r"\b(in|inside|within|case|around|about|round|holding|housing|boxing|framing|"
                             r"covering|wrapping|outside)\b", re.I)


def _self_signed_ops(tree):
    """ids of bare ops that a neighbour's words already sign (round 15, 8 of 12 judged-fine
    unindicatedBare flags): a deletion whose leaf marks the dropped letter with an apostrophe ('irsute,
    'orse), a deletion under a container whose indicator says one letter replaces another (ins<usurps>
    (del(ATTEST, S), MP)), an inner container that repeats the outer's letters under its one indicator
    (ins<bathing in>(ins(MIGHT, R), R)), and a container whose picked part carries "in case of"."""
    out = set()
    for parent in _walk(tree):
        kids = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        if parent.get("op") == "deletion" and kids and "op" not in kids[0] \
                and re.search(r"(?:^|\s)['’](?![sS]\b)\w", str(kids[0].get("words") or "")):
            out.add(id(parent))
        if parent.get("op") == "container" and kids:
            inds = " ".join(str(i.get("text") or "") for i in parent.get("indicators") or [])
            if kids[0].get("op") == "deletion" and _SUBSTITUTE_WORD.search(inds):
                out.add(id(kids[0]))
            if kids[0].get("op") == "container" and inds and len(kids) == 2 and "op" not in kids[1]:
                inner = [p for p in kids[0].get("parts") or [] if isinstance(p, dict)]
                if len(inner) == 2 and "op" not in inner[1] and wordplay.letters(inner[1].get("gives")) \
                        == wordplay.letters(kids[1].get("gives")) != "":
                    out.add(id(kids[0]))
            if not parent.get("indicators") and any(
                    k.get("op") in wordplay.SELECT and _CONTAINER_WORD.search(
                        " ".join(str(i.get("text") or "") for i in k.get("indicators") or [])) for k in kids):
                out.add(id(parent))
    return out


#: Letters of a holder's words that already say "holds / is held in": onboard, interpolar, inside, within.
_HOLDER_WORD = re.compile(r"^(?:onboard|inter|inside|within|inner)|(?:board|hold|holder)$")


def _self_holding_containers(tree):
    """ids of bare containers whose holder leaf says it holds (round 17, 14 of 97 sampled unindicatedBare
    flags judged fine): [Onboard]SS, [interpolar]SN (a holder of one or two letters from a short phrase),
    [Indeed]DEED (the holder's word is the indicator word plus the holder). The same word-is-both
    reading shared_indicators allows."""
    out = set()
    for node in _walk(tree):
        kids = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "container" or node.get("indicators") or len(kids) != 2 or "op" in kids[0]:
            continue
        w, g = wordplay.letters(kids[0].get("words")), wordplay.letters(kids[0].get("gives"))
        if not w or not g or w == g:
            continue
        nwords = len(str(kids[0].get("words") or "").split())
        rest = w[:len(w) - len(g)] if w.endswith(g) else (w[len(g):] if w.startswith(g) else "")
        w = w.lower()
        edge = bool(_HOLDER_WORD.search(w))
        if (len(g) <= 2 and nwords <= 2 and edge) or (nwords == 1 and rest and _CONTAINER_WORD.fullmatch(rest.lower())):
            out.add(id(node))
    return out


def _lone_implicit_op(tree):
    """ids of the only op in a tree that needs an indicator when no node of the tree carries one (round 17,
    35 of 51 sampled flags of this shape judged fine, 12 more unclear, 3 real): a bare homophone, hidden word,
    anagram or container whose clue states its signal inside a leaf's words or not at all (HEAR, IOTA,
    COARSEN, REMAINS). With other ops in the tree the same flag stays: there an indicator is misfiled or
    swapped (16 of 16 real). A lone bare deletion or pick stays flagged (the tests hold it)."""
    nodes = list(_walk(tree))
    ops = [n for n in nodes if n.get("op") in NEEDS_INDICATOR and not n.get("unchecked")]
    if len(ops) == 1 and ops[0].get("op") in ("homophone", "hidden", "anagram", "container") \
            and not any(n.get("indicators") for n in nodes):
        return {id(ops[0])}
    return set()


def _lone_bare_sound(tree):
    """ids of a bare homophone or hidden word that is the only bare op of its tree (round 17, 12 of 13 sampled
    flags of this shape judged fine, none of the real ones): the other ops carry their indicators, so no
    word of the clue is misfiled, and a sound or a hidden run is often left unsigned by the setter."""
    nodes = list(_walk(tree))
    bare = [n for n in nodes if n.get("op") in NEEDS_INDICATOR and not n.get("unchecked") and not n.get("indicators")]
    if len(bare) == 1 and bare[0].get("op") in ("homophone", "hidden") \
            and sum(1 for n in nodes if n.get("op") == bare[0]["op"]) == 1:  # a hidden word split in two stays flagged (TENOR)
        return {id(bare[0])}
    return set()


def _lone_bare_first(tree):
    """ids of the only bare op of a tree when it is a first-letter pick of one clue word that no other leaf uses
    (round 18, 218 DIRGE "includes Grangemouth", 269 OCEANUS "Upstart", 279 HER "Halpern": 3 of 3 judged fine, the
    two real ones had a word used twice or a phrase): the setter leaves a lone initial unsigned."""
    nodes = list(_walk(tree))
    bare = [n for n in nodes if n.get("op") in NEEDS_INDICATOR and not n.get("unchecked") and not n.get("indicators")]
    if len(bare) != 1 or bare[0].get("op") != "first" or any(n.get("op") == "charade" and n.get("indicators") for n in nodes) \
            or any(n is not bare[0] and n.get("op") in wordplay.SELECT for n in nodes):
        return set()  # an indicator filed on the charade, or a twin pick, is the swap or share the other rules look for
    words = _leaf_words(bare[0])
    if len(words) != 1 or len(str(next(q for q in _walk(bare[0]) if q.get("words")).get("words")).split()) != 1:
        return set()
    return {id(bare[0])} if sum(1 for q in nodes if "op" not in q and wordplay.letters(q.get("words")) == words[0]) == 1 else set()


def _leaf_words(node):
    return tuple(wordplay.letters(q.get("words")) for q in _walk(node) if "op" not in q and q.get("words"))


def _paired_ends(tree):
    """ids of a bare first/last/outer whose twin on the same words carries the indicator (round 18, 4 of 4
    sampled: "Either end of terrific" first<end of>/last, "either side of duff"): one phrase names both ends."""
    out = set()
    for parent in _walk(tree):
        group = {}
        for p in parent.get("parts") or []:
            if isinstance(p, dict) and p.get("op") in ("first", "last", "outer") and not p.get("unchecked"):
                group.setdefault(_leaf_words(p), []).append(p)
        for twins in group.values():
            both = any(_BOUNDARY_WORDS.search(str(i.get("text") or "")) or re.search(r"\bsides?\b", str(i.get("text") or ""))
                       for t in twins for i in t.get("indicators") or [])  # "start" / "outskirts" of two words is a swap (WASHBOWL)
            if len(twins) == 2 and both and sum(1 for t in twins if t.get("indicators")) == 1 and twins[0]["op"] != twins[1]["op"]:
                out.update(id(t) for t in twins if not t.get("indicators"))
    return out


def _indicator_inside_run(picks):
    """Whether every indicator of the picks stands between the first and last word of their leaves, as far as
    places are known (an indicator before the run, far from it, is VIOLA's: it signs the first pick alone)."""
    words = [q["at"] for p in picks for q in _walk(p) if "op" not in q and q.get("words") and isinstance(q.get("at"), int)]
    inds = [i["at"] for p in picks for i in p.get("indicators") or [] if isinstance(i.get("at"), int)]
    return not words or not inds or all(min(words) <= a <= max(words) for a in inds)


def _picks_with_indicator(tree):
    """ids of bare picks in a run of 3+ picks under one parent when one of them carries an indicator (round 18,
    "initially ... heading for" over five initials, "in successive locations" over nth letters): one phrase
    signs the whole run."""
    out = set()
    for parent in _walk(tree):
        picks = [p for p in parent.get("parts") or [] if isinstance(p, dict) and p.get("op") in wordplay.SELECT
                 and not p.get("unchecked")]
        if len(picks) >= 3 and any(p.get("indicators") for p in picks) and _indicator_inside_run(picks):
            out.update(id(p) for p in picks if not p.get("indicators"))
        sounds = [p for p in parent.get("parts") or [] if isinstance(p, dict) and p.get("op") == "homophone"
                  and not p.get("unchecked")]  # TWO BY FOUR: three sounds, one "Trumpet"
        if len(sounds) >= 3 and any(p.get("indicators") for p in sounds):
            out.update(id(p) for p in sounds if not p.get("indicators"))
    return out


def _outer_in_boundary_container(tree):
    """ids of a bare outer/first/last under a container whose indicator names the edges ("between fringes of"):
    the container's words pick the ends (round 18 SPADES)."""
    return {id(k) for n in _walk(tree) if n.get("op") == "container" and any(
        _BOUNDARY_WORDS.search(str(i.get("text") or "")) for i in n.get("indicators") or [])
        for k in n.get("parts") or [] if isinstance(k, dict) and k.get("op") in ("outer", "first", "last")
        and not k.get("indicators")}


def _chained_deletions(tree):
    """ids of bare deletions on the first-part chain under a deletion that has an indicator (round 17
    OPAL): del<Piss taken out of>(del(del(Pop Sails, P), I), S) - one indicator for the run of cuts."""
    out = set()
    for node in _walk(tree):
        if node.get("op") != "deletion" or not node.get("indicators"):
            continue
        cur = node
        while True:
            kids = [p for p in cur.get("parts") or [] if isinstance(p, dict)]
            if not kids or kids[0].get("op") != "deletion" or kids[0].get("indicators"):
                break
            out.add(id(kids[0]))
            cur = kids[0]
    return out


def _substituting_containers(tree):
    """ids of bare containers whose first part is a deletion signed with a swap word (round 17 BLUFFS:
    ins(del<ousting>(BLUES, E), FF)): the one "ousting" says the cut letter is replaced by the rest."""
    return {id(n) for n in _walk(tree) if n.get("op") == "container" and not n.get("indicators")
            for kids in [[p for p in n.get("parts") or [] if isinstance(p, dict)]]
            if kids and kids[0].get("op") == "deletion"
            and _SUBSTITUTE_WORD.search(" ".join(str(i.get("text") or "") for i in kids[0].get("indicators") or []))}


def unindicated_ops(tree):
    """How many checked ops that need an indicator word have none.

    Not a sound under a Spoonerism: an older tree may still file
    spoon<Spooner's>(sound([word]HEARD, SPELT), b) (the prompt now teaches
    spoon<Spooner's>([marry]MARRY, [fan]FAN, FERRYMAN)), and a clue's one
    indicator ("Spooner's ...") is the Spoonerism's, so a sound under it has no
    word of its own to name. Counting it made indysunday-1910 16A and cryptic-30133 17A
    (both Spoonerisms with a flagged hint) impossible to clear: no tree passed
    both this rule and the one that wants the sound written (10-17)."""
    spoken = {id(p) for s in _walk(tree) if s.get("op") == "spoonerism"
              for p in s.get("parts") or [] if isinstance(p, dict) and p.get("op") == "homophone"}
    copies = _repeated_copies(tree)
    return sum(1 for n in _walk(tree) if n.get("op") in NEEDS_INDICATOR
               and not n.get("unchecked") and not n.get("indicators") and id(n) not in spoken
               and id(n) not in copies)


def cdef_repeats(tree):
    """Extra leaves under a cryptic definition: the clue words once is the whole of it."""
    return sum(max(0, len(n.get("parts") or []) - 1) for n in _walk(tree)
               if n.get("op") == "cryptic" and not n.get("unchecked"))


def bad_arity(tree):
    """How many checked ops store a part count their op cannot take."""
    n = 0
    for node in _walk(tree):
        op = node.get("op")
        if op and op != "charade" and not node.get("unchecked"):
            lo, hi = _stored_arity(op)
            n += not lo <= len(node.get("parts") or []) <= hi
        elif op == "charade" and not node.get("unchecked"):
            n += len(node.get("parts") or []) < 2
    return n


def _claimed(tree):
    """(kind, start, end, text) for each indicator and clue-word leaf with an `at`,
    leaving out whatever is under a cryptic definition (its leaves are the clue)."""
    out, stack = [], [tree] if isinstance(tree, dict) else []
    while stack:
        node = stack.pop()
        if node.get("op") == "cryptic":
            continue
        for i in node.get("indicators") or []:
            if "at" in i:
                out.append(("indicator", i["at"], i["at"] + len(i["text"]), i["text"]))
        if "words" in node and "at" in node:
            out.append(("leaf", node["at"], node["at"] + len(node["words"]), node["words"]))
        stack += [p for p in node.get("parts") or [] if isinstance(p, dict)]
    return out


def span_overlaps(tree):
    """Pairs of indicator/leaf spans that share clue words.

    Not a pair: two leaves on the very same span. One clue word doing two jobs
    ("seen twice" -> first(seen) + first(seen); "Pieces" -> BIT + PART; "record"
    -> first half + second half; "Ocean's" picked three times by nth) can only
    be written as the same words in two leaves, so a model asked to fix it had
    nothing honest to change (read off 8 of the 27 span_overlap rows of
    tools/data/shape_reannotate.json, 10-17). A leaf that merely overlaps
    another, or an indicator over a leaf, is still counted."""
    sp = _claimed(tree)
    return sum(1 for i, a in enumerate(sp) for b in sp[i + 1:]
               if a[1] < b[2] and b[1] < a[2]
               and not (a[0] == b[0] == "leaf" and a[1] == b[1] and a[2] == b[2]))


def _with_places(ann, clue):
    """`ann` with an `at` filled in on every definition, indicator and leaf that has none and whose
    text stands once in `clue` (whole words): round 14 found annotations filed without places
    (ETNA, NATANT) that the place rules cannot see, two of 20 missed errors in 600 passing clues."""
    flat = str(clue or "")

    def find(text):
        hits = [m.start() for m in re.finditer(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(str(text)), flat, re.I)]
        return hits[0] if len(hits) == 1 else None

    def fill(item, key):
        if isinstance(item, dict) and "at" not in item and item.get(key):
            at = find(item[key])
            return {**item, "at": at} if at is not None else item
        return item

    def walk(node):
        node = {**node}
        if "words" in node and "op" not in node:
            node = fill(node, "words")
        if node.get("indicators"):
            node["indicators"] = [fill(i, "text") for i in node["indicators"]]
        if node.get("parts"):
            node["parts"] = [walk(p) if isinstance(p, dict) else p for p in node["parts"]]
        return node
    out = {**ann, "definitions": [fill(d, "text") for d in ann.get("definitions") or []]}
    if isinstance(ann.get("wordplay"), dict):
        out["wordplay"] = walk(ann["wordplay"])
    return out


def in_definition(ann, clue=None):
    """Wordplay spans inside a definition of a clue that is not &lit. With `clue`, spans filed
    without places are located in it first (_with_places).

    Two shapes are the setter's, not a fault, and are not counted (read off the
    45 grandfathered rows, 10-17):
      * the definition is the fodder: a palindrome or reversal over one leaf on
        exactly the definition's words ("Bread, either way" NAAN, "Touch, one way
        or the other" TAP), the clue's two halves being the same words;
      * a word split in two: the leaf takes the whole word and the definition
        only the end or start of it ("Woollen hat found lying under stopcock"
        BANTAM: STOP gives BAN, definition "cock"; "Guard's company" SCREW,
        S from "Guard's", definition "Guard"). The page can only mark whole
        leaves, so the definition is the part and the leaf the word."""
    if ann.get("andLit"):
        return 0
    if clue:
        # a definition on the whole clue is an &lit the file did not mark (round 14: 7 of 11 new hits)
        if any(isinstance(d, dict) and wordplay.letters(d.get("text")) == wordplay.letters(clue)
               for d in ann.get("definitions") or []):
            return 0
        ann = _with_places(ann, clue)
    ds = [(d["at"], d["at"] + len(d["text"]), d["text"]) for d in ann.get("definitions") or []
          if isinstance(d, dict) and "at" in d and d.get("text")]
    n, stack = 0, [(ann.get("wordplay"), None)] if isinstance(ann.get("wordplay"), dict) else []
    while stack:
        node, parent = stack.pop()
        if node.get("op") == "cryptic":
            continue
        spans = [("indicator", i["at"], i["at"] + len(i["text"]), i["text"])
                 for i in node.get("indicators") or [] if "at" in i]
        if "words" in node and "at" in node:
            spans.append(("leaf", node["at"], node["at"] + len(node["words"]), node["words"]))
        for kind, s0, s1, text in spans:
            for a, b, dtext in ds:
                if not (s0 < b and a < s1):
                    continue
                if kind == "leaf" and (s0, s1) == (a, b) and parent and parent.get("op") in ("palindrome", "reversal"):
                    continue
                lo, dl = text.lower(), dtext.lower()
                if kind == "leaf" and len(lo) > len(dl) and s0 <= a and b <= s1 and (
                        (lo.endswith(dl) and lo[-len(dl) - 1].isalpha())
                        or (lo.startswith(dl) and not lo[len(dl)].isspace())):
                    continue
                n += 1
                break
        stack += [(p, node) for p in node.get("parts") or [] if isinstance(p, dict)]
    return n


def leaf_folds(tree):
    """Leaves that give a stretch (3+ letters) of their own words and say nothing
    else: the stretch is a selection, a deletion or a hidden word, written as a leaf.

    Not folds: a leaf the abbreviation table holds (engineering/ENG), a leaf directly under a hidden-word op (the prompt's own form,
    hid([say no before]YNOBE): the op is there and the leaf names what it finds)
    and a leaf that only drops a possessive or plural S ([Mike's]MIKE)."""
    n = 0
    stack = [(tree, None)] if isinstance(tree, dict) else []
    while stack:
        node, parent = stack.pop()
        stack += [(p, node) for p in node.get("parts") or [] if isinstance(p, dict)]
        if "words" in node and "gives" in node and not node.get("unchecked") and not node.get("note"):
            if parent and parent.get("op") == "hidden":
                continue
            w, g = wordplay.letters(node["words"]), node["gives"]
            if annotation.is_abbreviation(node):
                continue  # a standard abbreviation that happens to open the word (ENG, DEM)
            n += len(g) >= 3 and g != w and g in w and w != g + "S"
    return n


def repeated_selections(tree):
    """Charades holding two or more of the same letter selection, each over one
    leaf (an acrostic written word by word): one selection over a multi-word leaf
    is the same pick."""
    n = 0
    for node in _walk(tree):
        if node.get("op") == "charade" and not node.get("unchecked"):
            picks = collections.Counter(
                (p["op"], p.get("n")) for p in node.get("parts") or []
                if isinstance(p, dict) and p.get("op") in wordplay.SELECT and not p.get("unchecked")
                and len(p.get("parts") or []) == 1 and "words" in p["parts"][0])
            n += sum(k > 1 for k in picks.values())
    return n


def single_leaf(tree):
    """1 when the whole wordplay is one leaf: a synonym for the answer, no mechanism."""
    return int(isinstance(tree, dict) and "op" not in tree and not tree.get("unchecked"))


# A bare leaf's note that says the puzzle, not a clue word, supplies the letters
# (Genius/Azed/themed puzzles: "the letter the preamble says the wordplay omits").
DEVICE_NOTE = re.compile(
    r"preamble|theme|unclued|ignored|omit|leaves? out|left out|missing|collid|grid.s edge|"
    r"(?:left|right|top|bottom) edge|doubled|instruction|restores?", re.I)


def bare_in_charade(tree, ann=None):
    """Pieces of a checked charade that are bare letters with no clue words.

    A bare leaf whose note says where the letters come from (DEVICE_NOTE: the
    preamble, the theme, an omitted or ignored letter) counts as a device leaf.

    Two kinds of bare letters are no fault. A clue with a `hiddenLetter` (the
    puzzle's extra/omitted/misprint device) has its letter in the answer or
    wordplay from no clue word. A leaf marked `"device": true` is letters the
    preamble or theme supplies (a Genius edge letter, an Azed collision's
    shared letters); the marker is the annotator's claim, so it stays in the
    stored tree where a reader can see it."""
    if isinstance(ann, dict) and ann.get("hiddenLetter"):
        return 0
    return sum(1 for node in _walk(tree) if node.get("op") == "charade" and not node.get("unchecked")
               for p in node.get("parts") or []
               if isinstance(p, dict) and "op" not in p and "words" not in p and not p.get("unchecked")
               and not p.get("device") and not DEVICE_NOTE.search(p.get("note") or ""))


def anagram_of_container(tree):
    """Anagrams whose fodder is a container's result: the container is the
    outer step in nearly every such clue, with the anagram its inner arm."""
    return sum(1 for node in _walk(tree) if node.get("op") == "anagram"
               and any(isinstance(p, dict) and p.get("op") == "container" for p in node.get("parts") or []))


def _unchecked_ops(tree):
    return [n for n in _walk(tree) if n.get("op") and n.get("unchecked")]


def _spoon_swap_ok(sounds, gives, originals=()):
    """Whether `gives` is the spoonerism the leaf's `soundsLike` says. `originals` are the
    two words the setter swaps when the tree files them as parts (TWO, BEAKS): the sound
    reading then opens with the second one's letter and the first one's follows, and the
    answer is spelt from it. Else two sound words are the swap of each other's openings
    (by letters, or by the frame when the spelling shifts with the sound), and one word is
    a sound-alike whose letters the swap rearranges, so the answer uses nearly the same."""
    ws = [wordplay.letters(w) for w in str(sounds or "").split()]
    if not gives or not ws or not all(ws):
        return False
    if len(originals) == 2 and len(ws) == 2 and all(originals) and ws == list(originals):
        # soundsLike names the two words as they stand (FULL APACE, BOG LOOK): the swap
        # trades their opening sounds, so the answer is the same letters rearranged
        # (PULLAFACE, LOGBOOK), changed at the start, and not the two words run together
        joined = ws[0] + ws[1]
        return len(gives) >= 4 and sorted(gives) == sorted(joined) and gives != joined and gives[0] != joined[0]
    if len(originals) == 2 and len(ws) == 2 and all(originals):
        (a, b), (x, y) = originals, ws
        return x[0] == b[0] and y[0] == a[0] and gives[0] == x[0] and gives[-1] == y[-1] and len(gives) >= 4
    if len(ws) == 2:
        a, b = ws
        swapped = {wordplay._onset(b) + a[len(wordplay._onset(a)):] + wordplay._onset(a) + b[len(wordplay._onset(b)):],
                   b[:1] + a[1:] + a[:1] + b[1:]}
        return gives in swapped or wordplay._spoon_sound(sounds, gives)
    if len(ws) == 1 and len(ws[0]) >= 4 and gives != ws[0] and len(gives) >= 3 and gives[0] != ws[0][0]:
        c, d = collections.Counter(ws[0]), collections.Counter(gives)
        return sum(((c - d) + (d - c)).values()) <= 2
    return False


def step_verified(node):
    """Whether an `unchecked` op step is one whose letters can be computed from its leaf, so
    the flag only records a precaution (fix round 4, 14 of 20 sampled unchecked_step rows
    were right): first / last / middle / outer pick `gives` from the clue words of the one
    leaf under them, and a spoonerism's `gives` is the swap of the leaf's `soundsLike`. A
    step whose leaf and `gives` disagree, or whose pick the words cannot make, stays unchecked."""
    return _verified_leaf(node) is not None


def _verified_substitution(node, parts):
    """The first part of an unchecked two-part substitution whose result the pieces compute,
    else None. Two forms the evaluator's centre swap does not take, both with the result the
    node gives: a pair of letters that trade places through the other piece (SW in SELLNEWS
    -> WELLNESS, cryptic-29499 8d), and one letter that takes the place of the other piece's
    first or last (G for the leader of RULES -> GULES, timesjumbo-1354 52d)."""
    want = wordplay.letters(node.get("gives"))
    if len(parts) == 3 and want:  # whole, the piece that goes, the piece that replaces it (OMEGA, G, RT -> OMERTA)
        try:
            for whole in wordplay.values(parts[0]):
                for old in wordplay.values(parts[1]):
                    for new in wordplay.values(parts[2]):
                        if old and whole.count(old) == 1 and whole.replace(old, new) == want and new != old:
                            return parts[0]
        except (wordplay.WordplayError, KeyError, TypeError, ValueError, IndexError):
            return None
        return None
    if len(parts) == 1 and want and "op" not in parts[0] and not parts[0].get("gives") and parts[0].get("words"):
        # one word and a swap its indicator names ("Russia/EU trade": U out, E in), the result
        # then anagrammed (ARISES): the result is the word's letters with exactly that swap
        have, left = collections.Counter(wordplay.letters(parts[0]["words"])), collections.Counter(want)
        out_, in_ = have - left, left - have
        said = wordplay.letters(" ".join(str(i.get("text") or "") for i in node.get("indicators") or []))
        if len(want) == len(wordplay.letters(parts[0]["words"])) and sum(out_.values()) == 1 == sum(in_.values()) \
                and set(out_) | set(in_) <= set(said):
            return parts[0]
        return None
    if len(parts) != 2 or not want:
        return None
    try:
        for new_part, old_part in ((parts[0], parts[1]), (parts[1], parts[0])):
            for new in wordplay.values(new_part):
                for old in wordplay.values(old_part):
                    if len(new) == 2 and new[0] != new[1] and len(old) == len(want) and any(
                            {old[i], old[j]} == set(new) and old[:i] + old[j] + old[i + 1:j] + old[i] + old[j + 1:] == want
                            for i in range(len(old)) for j in range(len(old)) if i < j):
                        return parts[0]
                    if len(new) == 1 and len(old) == len(want) >= 3 and old != want \
                            and want in (new + old[1:], old[:-1] + new):  # not the piece itself back
                        return parts[0]
                    if len(new) == 1 and len(old) == len(want) >= 5 and new_part is parts[1] \
                            and sum(a != b for a, b in zip(old, want)) == 1 \
                            and any(o != w and w == new for o, w in zip(old, want)):
                        return parts[0]  # one letter inside swapped for the piece (COCKATOO -> COCKAPOO)
    except (wordplay.WordplayError, KeyError, TypeError, ValueError, IndexError):
        return None
    return None


def _verified_leaf(node):
    """The leaf step_verified checked the unchecked step `node` against, else None."""
    op, parts = node.get("op"), [p for p in node.get("parts") or [] if isinstance(p, dict)]
    if not node.get("unchecked"):
        return None
    if op == "spoonerism":  # the swapped words may ride along as parts; the leaf with soundsLike is the claim
        two = [p for p in _walk(node) if p.get("soundsLike") and "op" not in p]
        if len(two) == 2 and all(p.get("gives") for p in two):
            # two sound-alikes trade their opening sounds, each leaf giving its own word's new
            # spelling (stake/hock + birdhouse/coop -> COCK + HOOP, cryptic-29218 7d)
            (ga, gb), (sa, sb) = [[wordplay.letters(p[k]).lower() for p in two] for k in ("gives", "soundsLike")]
            oa, ob = wordplay._onset(sa), wordplay._onset(sb)
            if sa and sb and oa != ob and ga.startswith(ob[:1]) and gb.startswith(oa[:1]) \
                    and ga[len(ob):] == sa[len(oa):] and gb[len(oa):] == sb[len(ob):]:
                return two[0]
        sound = [p for p in parts if p.get("soundsLike") and "op" not in p]
        want = wordplay.letters(node.get("gives"))
        others = [wordplay.letters(p.get("gives")) for p in parts if p is not sound[0] and "op" not in p] if sound else []
        if len(sound) == 1 and want and wordplay.letters(sound[0].get("gives")) == want \
                and _spoon_swap_ok(sound[0]["soundsLike"], want, others):
            return sound[0]
        return None
    if op == "substitution":
        return _verified_substitution(node, parts)
    if op == "anagram" and len(parts) == 1 and parts[0].get("op") and _verified_leaf(parts[0]) is not None \
            and sorted(wordplay.letters(node.get("gives"))) == sorted(wordplay.letters(parts[0].get("gives"))) \
            and node.get("gives"):
        return parts[0]  # a scramble of a step already computed (ARISES: Russia, U for E, then scrambled)
    if len(parts) == 1 and op == "hidden" and parts[0].get("op") in wordplay.SELECT and parts[0].get("unchecked") \
            and wordplay.letters(node.get("gives")) == wordplay.letters(parts[0].get("gives")) and node.get("gives"):
        return _verified_leaf(parts[0])  # a hidden word over a selection already computed (INCA, mid of skincare)
    if len(parts) != 1 or "op" in parts[0]:
        return None
    leaf = parts[0]
    if op == "charade" and len(wordplay.letters(leaf.get("gives"))) >= 3 and set(wordplay.letters(leaf.get("gives"))) <= set("NSEW") \
            and wordplay.letters(leaf.get("gives")) == wordplay.letters(node.get("gives")) \
            and re.search(r"\b(?:directions?|points?|compass|quarters?)\b", str(leaf.get("words")), re.I):
        return leaf  # "directions" = SEWN: each letter is a compass point, in the order the indicator names (round 13)
    given = {wordplay.letters(x.get("gives")) for x in (node, leaf) if x.get("gives")}
    if len(given) != 1 or not (want := next(iter(given))):
        return None
    if op not in wordplay.SELECT or op == "nth" or not leaf.get("words"):
        return None
    try:
        got = wordplay.values({"op": op, "parts": [{"words": leaf["words"], "select": op}]})
    except wordplay.WordplayError:
        return None
    if want in got:
        return leaf
    word = wordplay.letters(leaf["words"]).lower()
    if len(str(leaf["words"]).split()) == 1:
        # sweetheart = the heart of sweet (WOOED), mountaintop = top of mountain: the compound names the pick
        # and the rest is the source word (round 13)
        for k in _SELECT_COMPOUND.get(op, ()):
            for rest in ((word[:-len(k)] if word.endswith(k) else None), (word[len(k):] if word.startswith(k) else None)):
                if rest and len(rest) >= 3:
                    try:
                        if want in wordplay.values({"op": op, "parts": [{"words": rest, "select": op}]}):
                            return leaf
                    except wordplay.WordplayError:
                        pass
    return None


_SELECT_COMPOUND = {"middle": ("heart", "centre", "center", "core", "middle"),
                    "first": ("top", "head", "leader", "front"), "last": ("tail", "foot", "bottom")}


def unverified_unchecked(tree, answer=None):
    """The nodes still carrying the `unchecked` flag once the steps step_verified can
    compute are set aside (each with the one leaf under it). With the clue's `answer`,
    a verified step counts only in a tree that gives the answer: a right pick in a tree
    that is wrong elsewhere (cryptic-28632 23d, cryptic-26974 53a) is still the redo's."""
    done = set()
    if not any(n.get("unchecked") for n in _walk(tree)):
        return []  # most trees: no flag, nothing to evaluate
    if answer is not None:
        try:
            wordplay.evaluate(tree, answer)
        except (wordplay.WordplayError, KeyError, TypeError, ValueError, IndexError):
            return [n for n in _walk(tree) if n.get("unchecked")]
    for n in _walk(tree):
        leaf = _verified_leaf(n) if n.get("op") else None
        if leaf is not None:
            done |= {id(n), id(leaf)}
            if n.get("op") == "spoonerism":
                done |= {id(q) for q in _walk(n)}
    for n in _walk(tree):
        if n.get("op") and n.get("unchecked") and id(n) not in done and _recomputes(n):
            done |= {id(q) for q in _walk(n)}
    return [n for n in _walk(tree) if n.get("unchecked") and id(n) not in done]


def _strip_unchecked(node):
    if not isinstance(node, dict):
        return node
    return {k: ([_strip_unchecked(p) for p in v] if k == "parts" else v) for k, v in node.items() if k != "unchecked"}


def _pool(node):
    """The letters (sorted) a fodder piece contributes to an anagram: a leaf's `gives` or words, a deletion's first
    piece less the rest, any other op's `gives`; None when they cannot be told."""
    parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    if "op" not in node:
        return collections.Counter(wordplay.letters(node.get("gives") or node.get("words")))
    if node["op"] == "deletion" and len(parts) >= 2 and all(_pool(p) is not None for p in parts):
        left = _pool(parts[0])
        for p in parts[1:]:
            left = left - _pool(p)
        return left if sum(_pool(parts[0]).values()) - sum(left.values()) == sum(sum(_pool(p).values()) for p in parts[1:]) else None
    return collections.Counter(wordplay.letters(node["gives"])) if node.get("gives") else None


def _recomputes(node):
    """Whether an unchecked op step is computed by its pieces (round 18, 9 of 11 sampled unchecked_step flags
    judged fine): the flag only records a precaution when the evaluator, with the flag lifted, gives the stated
    letters; when an anagram's fodder (a deletion's remainder included) has exactly its stated letters; or when a
    hidden or middle pick states a run of its leaf's own letters."""
    live = _strip_unchecked(node)
    want = wordplay.letters(node.get("gives"))
    try:
        if node["op"] == "anagram" and want:
            pools = [_pool(p) for p in live.get("parts") or [] if isinstance(p, dict)]
            if pools and all(p is not None for p in pools) and sum(pools, collections.Counter()) == collections.Counter(want):
                return True
        if node["op"] in ("hidden", "middle") and want:
            run = "".join(wordplay.letters(q.get("words")) for q in _walk(live) if "op" not in q and q.get("words"))
            if want in run and len(want) < len(run):
                return True
        if want:
            wordplay.evaluate(live, want)
            return True
        return bool(wordplay.values(live))
    except Exception:  # any failure to compute leaves the step flagged
        return False


def arity_ins(tree):
    """Unchecked containers that do not hold exactly two parts (the held and the holder)."""
    return sum(len(n.get("parts") or []) != 2 for n in _unchecked_ops(tree) if n["op"] == "container")


def arity_other(tree):
    """Unchecked ops with more parts than their evaluator takes: a deletion of 3+, a
    substitution not of 3, a homophone of 3+, a reversal, hidden word, cycling or
    letter selection not of 1."""
    n = 0
    for node in _unchecked_ops(tree):
        op, k = node["op"], len(node.get("parts") or [])
        if op == "substitution" and k > 3:  # a bare link word among 4+ parts is not one of the three
            k -= sum(1 for p in node.get("parts") or [] if isinstance(p, dict) and "op" not in p
                     and not p.get("gives") and wordplay.letters(p.get("words")) in _SUB_LINKS)
        n += ((op == "deletion" and k > 9) or (op == "substitution" and k != 3)
              or (op == "homophone" and k >= 3)
              or (op in ("reversal", "hidden", "cycling") + wordplay.SELECT and k != 1))
    return n


def _not_a_rotation(node):
    """An unchecked `cycling` step whose result is not its one part's letters rotated: a letter moved
    to the front (HEARS -> RHEAS, times-28709 22d) is not cycling, and "unchecked" hid it (round 13)."""
    part = node["parts"][0]
    have, want = wordplay.letters(part.get("gives")), wordplay.letters(node.get("gives"))
    return bool(isinstance(part, dict) and have and want and len(have) == len(want) and have != want
                and want not in {have[k:] + have[:k] for k in range(len(have))})


_DEL_ALL = re.compile(r"\b(both|each|every|cases|ends|edges|tops|heads|tails|boundar(?:y|ies)|borders|"
                      r"limits|margins|fringes|outskirts|extremities)\b", re.I)
#: Link words a substitution may list among its parts beside the three it takes
#: ("changing book to IF": [by] is the clue's link, not a part), round 10 (JUSTIFY).
_SUB_LINKS = frozenset("BY FOR WITH TO IN OF AND FROM".split())


def del_single(tree):
    """Unchecked deletions with one part: the letters taken out are not stated.

    Not counted: a deletion whose only part is a single leaf and which carries an
    indicator ("lifting both ends of" barbells > WEIGHTS > EIGHT, "short" leg >
    STAGE > STAG): the indicator says what comes off the leaf's `gives`, a
    correct parse (sample of 13, 5 of them this shape). A composite part (a
    charade wrapped as one deletion, cryptic-22711 31d GON+AD) is still counted:
    the indicator applies to one piece, not to the joined result."""
    def lone_leaf(n):
        parts = n.get("parts") or []
        return (n.get("indicators") and isinstance(parts[0], dict) and "op" not in parts[0]
                and parts[0].get("gives") and parts[0].get("words"))
    # Also not counted (fix round 4, ftcryptic-17845 18d KINETIC, times-29330 5d ENCHANTER,
    # telegraph-31189 11a ENHANCE): a lone leaf cut and then scrambled (the anagram comes
    # after the cut), and a deletion over a charade of 2+ pieces whose indicator speaks of
    # every piece ("both topless", "after losing cases") and so covers all of them.
    fodder = {id(p) for a in _walk(tree) if a.get("op") == "anagram"
              for p in a.get("parts") or [] if isinstance(p, dict)}

    def cut_then_scrambled(n):
        p = (n.get("parts") or [{}])[0]
        return id(n) in fodder and n.get("indicators") and isinstance(p, dict) and "op" not in p and p.get("words")

    def covers_all(n):
        p = (n.get("parts") or [{}])[0]
        if not (isinstance(p, dict) and p.get("op") == "charade" and len(p.get("parts") or []) >= 2
                and not any("op" in q for q in p["parts"] if isinstance(q, dict))):
            return False
        return any(_DEL_ALL.search(str(i.get("text") or "")) for i in n.get("indicators") or [])
    return sum(len(n.get("parts") or []) == 1 and not lone_leaf(n) and not cut_then_scrambled(n)
               and not covers_all(n)
               for n in _unchecked_ops(tree) if n["op"] == "deletion")


def ind_in_leaf(tree, clue=None):
    """Indicators (3+ letters) that also sit, as a whole word, inside a longer leaf of
    clue words: the leaf took the indicator's word as well as its own.

    With the `clue` the count is by occurrence: a word the clue says twice
    ("Jog without clothes, without much money") can be an indicator once and
    inside a leaf once, so it is flagged only when the leaves and indicators
    use it more times than the clue has it. Without the clue any repeat fires."""
    nodes = list(_walk(tree))
    leaves = [n for n in nodes if "op" not in n and n.get("words")]
    leaf_words = [[wordplay.letters(x) for x in n["words"].split()] for n in leaves]
    said = collections.Counter(wordplay.letters(x) for x in (clue or "").split())
    used = collections.Counter(wordplay.letters(i.get("text")) for node in nodes
                               for i in node.get("indicators") or [])
    n = 0
    for node in nodes:
        # The repeat is cosmetic when the leaf is the op's own direct part and the op
        # evaluates (checked: azed-1928 8d) or is a selection (its leaf names the word
        # it picks from: times-29067 1d). A leaf under another op is a misfiled
        # indicator (timesjumbo-1742 10d, times-29198 24a) and still counts.
        own = node.get("op") in wordplay.SELECT or not node.get("unchecked")
        direct = {id(p) for p in node.get("parts") or [] if isinstance(p, dict)} if own else set()
        mine = [ws for ws, leaf in zip(leaf_words, leaves) if id(leaf) not in direct and len(ws) > 1]
        every = [ws for ws in leaf_words if len(ws) > 1]
        for i in node.get("indicators") or []:
            t = wordplay.letters(i.get("text"))
            iw = [w for w in (wordplay.letters(x) for x in str(i.get("text") or "").split()) if w]
            # an indicator the corpus gives to another op ("retreating" on a container, 156 of 167 uses a
            # reversal) is not the cosmetic repeat of a leaf's own word: it is the other op's, folded in
            # the leaf as well (times-29174 22d FORCE, round 12)
            owner = _owner_type(i.get("text"))
            mine_i = every if owner and owner != _OP_LEXICON.get(node.get("op")) else mine
            if len(iw) > 1 and len(t) >= 3 and any(
                    ws != iw and any(ws[k:k + len(iw)] == iw for k in range(len(ws) - len(iw) + 1)) for ws in mine_i):
                # a phrase indicator ("Half of") whose words open a leaf of more words (times-29100 9a URN)
                n += not (clue and wordplay.letters(clue).count(t) > 1)
                continue
            if len(t) >= 3 and any(t in ws and ws != [t] for ws in mine_i):
                if clue and said[t] >= used[t] + sum(ws.count(t) for ws in leaf_words):
                    continue  # the clue says the word often enough for each use
                n += 1
    return n


def scrambled_leaves(tree, min_len=4):
    """Leaves (checked or not) whose `gives` is a permutation of their own clue
    letters, not equal to them.

    A fodder leaf gives its own letters in order; only an anagram op scrambles, so
    a leaf that arrives scrambled hides a bad tree (CULTIVATE =
    ana(ins([clever]CUTE, [vital]LTIVA)), [gaunt]GUTAN). Under an anagram the
    fodder is verbatim: [Lido]IDOL under ana is a made-up synonym (shape round 3,
    10-17: 4,654 such clues repaired by tools/fix_scrambled_gives.py, the rule now
    covers them). Not flagged: a leaf directly under a reversal or cycling op (the
    corpus writes the op's input or result there), 3 or fewer letters, and any `gives` with other
    letters (a synonym or abbreviation). A same-first-letter sub-multiset out of
    order was measured too and is mostly a coincident synonym (summer clothes >
    SHORTS), so it is not a rule."""
    n = 0
    stack = [(tree, None)] if isinstance(tree, dict) else []
    while stack:
        node, parent = stack.pop()
        stack += [(p, node) for p in node.get("parts") or [] if isinstance(p, dict)]
        if "op" in node or not node.get("words") or not node.get("gives"):
            continue
        if parent and parent.get("op") in ("reversal", "cycling"):
            continue
        w, g = wordplay.letters(node["words"]), wordplay.letters(node["gives"])
        n += len(g) >= min_len and g != w and collections.Counter(g) == collections.Counter(w)
    return n


#: Three more shapes a re-parse can pass the gates above with (audit of the burn's
#: redos, 10-17). Each is a ratchet field like the rest.
#:   * IND_FOLDED: the indicator words moved into a leaf that has a `gives`
#:     (everyman-4162 25a: "Principally, Everyman, more than once" one leaf giving ES),
#:     so ind_in_leaf (which needs the indicator listed on an op) sees nothing;
#:   * FAKE_PARTS: a substitution padded to its three parts with wordless nodes
#:     whose `gives` the clue never says (tls-1146 16a: sub(sub(non-fiction, R, L), AL, AR));
#:   * PADDING_LEAF: a leaf of clue words that is `unchecked` with no `gives`: it claims
#:     the words without saying what they contribute (mephisto-3436 18d, "no shock").
#: Not counted: a spoonerism's sound leaves and the selection ops' leaves (another
#: worker's job), a leaf whose note says it was dropped.
IND_FOLDED = "indicator words folded into a leaf"
FAKE_PARTS = "substitution padded with wordless parts that are not in the clue"
PADDING_LEAF = "unchecked clue-word leaf with no letters given"
#: Leaf this wide (words) giving at most half as many letters is not one synonym.
FOLD_WIDE_WORDS = 5
FOLD_MIN_USES = 50
_OP_LEXICON = {"anagram": "anagram", "reversal": "reversal", "container": "container",
               "deletion": "deletion", "hidden": "hidden_word", "homophone": "homophone",
               "spoonerism": "spoonerism", **{s: "letter_selection" for s in wordplay.SELECT}}


@functools.lru_cache(maxsize=1)
def _indicator_lexicon():
    """{lexicon type: {key: clues}} from tools/data/lexicons/indicators.json."""
    path = ROOT / "tools" / "data" / "lexicons" / "indicators.json"
    return json.loads(path.read_text()) if path.exists() else {}


def folded_indicators(tree):
    """Multi-word leaves that carry a `gives` and also hold an indicator.

    Only a leaf giving 1-2 letters (a selection's or a homophone's result is
    short; a synonym's is not). Flagged when the words at either edge of the leaf
    are a multi-word known indicator (lexicon, 6+ letters, FOLD_MIN_USES+ uses)
    for an op this tree uses; or the leaf is FOLD_WIDE_WORDS+ words and has such
    an edge for any op (everyman-4162 25a uses only a homophone, yet its leaf
    opens with a selection's "Principally"). One-word edges ("perhaps", "without")
    are ordinary leaf words (100s of definitions), so they are not counted
    unless the leaf is wide."""
    nodes = list(_walk(tree))
    used = {_OP_LEXICON[n["op"]] for n in nodes if n.get("op") in _OP_LEXICON}
    lex = _indicator_lexicon()
    n = 0
    for node in nodes:
        if "op" in node or not node.get("words") or not node.get("gives") or node.get("unchecked"):
            continue
        ws = [w for w in (wordplay.letters(x) for x in node["words"].split()) if w]
        if len(ws) < 2:
            continue
        gives = wordplay.letters(node["gives"])
        if len(gives) > 2:
            continue
        runs = [" ".join(r) for k in range(1, len(ws)) for r in (ws[:k], ws[-k:])]

        def known(types, runs=runs):
            return any(lex.get(t, {}).get(key, 0) >= FOLD_MIN_USES and len(key.replace(" ", "")) >= 6
                       for t in types for key in runs if " " in key or len(ws) >= FOLD_WIDE_WORDS)
        n += known(used) or (len(ws) >= FOLD_WIDE_WORDS and known(lex))
    return n


def fake_parts(tree):
    """Substitutions whose replaced and replacement parts are wordless `gives`
    of 2+ letters directly after a substitution: the swap was made up to fill
    the three parts, not read from the clue. Also an unchecked `cycling` that is
    no rotation of its part: the step was named for what it is not."""
    n = 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") == "substitution" and not node.get("unchecked") and len(parts) == 3 \
                and isinstance(parts[0], dict) and parts[0].get("op") == "substitution":
            n += all(isinstance(p, dict) and "op" not in p and "words" not in p
                     and len(p.get("gives") or "") >= 2 for p in parts[1:])
        # an unchecked cycling that is no rotation (HEARS -> RHEAS moves one letter, times-28709 22d, round 13)
        n += bool(node.get("op") == "cycling" and node.get("unchecked") and len(parts) == 1
                  and isinstance(parts[0], dict) and _not_a_rotation(node))
    return n


def padding_leaves(tree):
    """Unchecked leaves of clue words with no `gives`, under a charade or another
    op that joins pieces. Not under a spoonerism or a selection op, and not one
    whose note says it was dropped."""
    n, stack = 0, [(tree, None)] if isinstance(tree, dict) else []
    while stack:
        node, parent = stack.pop()
        stack += [(p, node) for p in node.get("parts") or [] if isinstance(p, dict)]
        if "op" in node or not node.get("unchecked") or not node.get("words") or node.get("gives"):
            continue
        if parent and (parent.get("op") in ("spoonerism", "palindrome") or parent.get("op") in wordplay.SELECT):
            continue
        n += "dropped" not in (node.get("note") or "")
    return n


#: Why checked trees that cannot be what the setter wrote still evaluate to the answer
#: (times-29420 24a ABUSE, timesjumbo-1707 48d BISCAY, azed-2333 24d SLIMY): the letter
#: evaluator lets an inserted piece land at ANY gap, including inside a container's own
#: result, so ins(ins(ABE, U), S) spells ABUSE (really AB(U+S)E) and nothing objects.
#: A container nested as the HOLDER of another is almost always the wrong nesting: what
#: goes in two pieces together is a charade of them (ins(ABE, U+S)), and a piece in a
#: piece in a third is ins(third, ins(second, first)). measured 20/20 real (10-18).
NESTED_CONTAINER = "container whose holder is itself a container"
#: An indicator is filed on the op it acts on. One the indicator lexicon knows only for
#: another op (times-29420 16d: "End of", a letter selection's, on the charade) is on
#: the wrong op. Needs a 50-use lexicon entry for the other op and none for this one.
MISPLACED_INDICATOR = "indicator filed on an op it does not signal"
#: The lexicon is rebuilt nightly, so a word can cross this and flag puzzles that were clean;
#: tools/requeue_drift.py (run by the rebuild, and by hand after editing any rule) queues
#: those clues and raises their allowance so the deploy does not go red.
MISPLACED_MIN_USES = 200
#: Plain ordering / juxtaposition words that setters put on a charade as often as on
#: the op the lexicon knows them for ("at first", "opening", "off", "taking",
#: "backing": 5 of 10 sampled flags were correct charades, 10-18). Not flagged; the
#: rule keeps container, reversal and anagram verbs ("eating", "to secure", "around").
ORDERING_INDICATORS = frozenset(
    "at first|opening|off|taking|backing|after|before|following|behind|ahead of|beside|next to|"
    "by|with|and|then|leading|heading|first|starting|beginning|at the start|at the front|"
    "in front of|going before|preceding|followed by|supporting|on|to|for|from|getting|"
    "having|bringing|giving|making|showing|catching|joining|meeting|alongside|against|"
    "early|late|last|finally|at last|at the end|in the end|"
    "to follow|coming after|going after|in pursuit of|pursuing|close to|near|adjacent to|"
    "touching|joined to|attached to|to begin with|wanting".split("|"))
#: Position words, read "A initially B" = A first, "A covers B" = A above B in a down clue, that
#: pass as a charade once the letters concatenate (ANGELUS, TELESCOPE, OUTDO, PLEAD; fix round 3):
#: a container misfiled this way would not spell the answer in order. Still flagged when a
#: selection op in the charade has no indicator of its own (quiptic-170 1a ADAMANT first(talk)),
#: the sign the word belongs to that op. Cleared rows judged 16/20 before that guard.
#: Words that mark a leaf's clue words as an example of the thing they give ("commercial vehicle,
#: perhaps" = VAN); on a charade of plain leaves they are the setter's hedge, not an anagram.
EXAMPLE_MARKERS = frozenset("perhaps|say|maybe|for example|for instance|for one|as an example|possibly".split("|"))
#: Round 18: "originally", "primarily", "firstly" read as "initially" does (UPRIGHTS, WASTED: A primarily B = A first).
POSITION_INDICATORS = frozenset("initially|originally|primarily|firstly|covers|covering|covered by|to cover".split("|"))


#: An inner container whose indicator says its piece goes in apart from the other
#: ("separately", "in two places"): the two pieces land at different points of one
#: holder, which no charade of them can say (WILBERFORCE, UNDERTHEWEATHER).
SEPARATE_INSERTION = re.compile(r"separate|apart|two places|different|both|each|respective|twice", re.I)


def _separate_insertion(outer, inner):
    """True when `outer` = ins(inner = ins(holder, x), y) puts x and y in at different
    points on purpose: the inner indicator says so, or x and y are the same letters
    (a letter put in twice, MALAYAN) since a charade of the two is not a fair parse
    of a repeated piece named once."""
    if any(SEPARATE_INSERTION.search(str(i.get("text") or "")) for i in inner.get("indicators") or []):
        return True
    x = (inner.get("parts") or [None, None])[1:2]
    y = (outer.get("parts") or [None, None])[1:2]
    same = lambda p: wordplay.letters(p.get("gives") or p.get("words")) if isinstance(p, dict) and "op" not in p else None
    return bool(x and y and same(x[0]) and same(x[0]) == same(y[0]))


def _flat_insert_reaches(outer, inner, answer):
    """Whether the two pieces `outer` and `inner` put into one holder can be joined into one
    charade, in either order, that goes into the holder at a single gap and spells `answer`.
    False when they must go in at two gaps (independent-10817 7d BIOMEDICINE: I into BONE after
    B, then MEDICI after BIO, two insertions with an indicator each): the nesting is the
    only parse. Unreadable pieces count as reaching, so the flag stays."""
    try:
        holder = wordplay.values(inner["parts"][0])
        xs, ys = wordplay.values(inner["parts"][1]), wordplay.values(outer["parts"][1])
        target = wordplay.letters(answer)
        if target not in wordplay.values(outer):
            return True  # the nesting does not even give the answer: a wrong tree, not a double gap
        return any(o[:k] + a + b + o[k:] == target for o in holder for x in xs for y in ys
                   for a, b in ((x, y), (y, x)) for k in range(1, len(o)))
    except Exception:  # an anagram in the pieces needs the target: leave the flag
        return True


def nested_containers(tree, answer=None):
    """How many checked containers hold, as their first part, another checked container
    (less the ones that put two pieces into one holder at different points on purpose, and,
    with the `answer` for a nesting that is the whole tree, the ones no single insertion of
    both pieces can spell: the two gaps are the setter's)."""
    return sum(1 for n in _walk(tree) if n.get("op") == "container" and not n.get("unchecked")
               for p in (n.get("parts") or [])[:1]
               if isinstance(p, dict) and p.get("op") == "container" and not p.get("unchecked")
               and not _separate_insertion(n, p)
               and not (answer and n is tree and len(n["parts"]) == 2 and len(p.get("parts") or []) == 2
                        and not _flat_insert_reaches(n, p, answer)))


#: An anagram scrambles the clue's own letters. A leaf in its fodder that gives a
#: synonym (toughie-3430 3d WISCONSIN: ana<Wild>(cows in + [wrong]SIN); the answer is
#: ana(cows in) + SIN) has a stand-in word scrambled, which the clue cannot mean.
#: One-letter gives are abbreviations (S for southern), which clues do scramble.
ANAGRAM_SYNONYM = "synonym scrambled inside an anagram"


def anagram_synonyms(tree, ann=None, clue=None):
    """How many leaves of 2+ letters, giving other letters than their own words, sit in a
    charade directly under an anagram beside a leaf that gives its own words (the mix
    of fodder and stand-in), or directly under the anagram beside such a leaf (azed-2671
    16a BAROCCOS: ana(crab, [lettuce]COS)). A lone synonym scrambled is not counted
    unless, with the annotation and clue given, a content word of the clue is claimed by
    nothing (independent-12261 8d DIEHARD: ana(caught = HEARD), "heroin" left over): the
    unclaimed word is the letter the real parse moves or drops. A leaf that gives its words
    twice over (IT -> ITIT) is a literal doubling, not a synonym."""
    n = 0
    # Round 22c: with the answer known only a synonym at its edge counts (G + ana(FIRE)); a piece mid-answer
    # scrambled with the rest is fodder (14 of 40 judged hits fine, all mid-answer; 10 of 10 edge hits errors).
    ans = wordplay.letters((ann or {}).get("_answer") or "")
    for node in _walk(tree):
        if node.get("op") != "anagram":
            continue  # unchecked steps count: toughie-3430 3d files its stand-in unchecked
        pools = [node] + [p for p in node.get("parts") or [] if isinstance(p, dict) and p.get("op") == "charade"]
        for p in pools:  # a lone synonym scrambled is an indirect anagram, which setters do write
            pool = [q for q in p.get("parts") or [] if isinstance(q, dict) and "op" not in q
                    and q.get("words")]
            same = [q for q in pool if not q.get("gives") or wordplay.letters(q["gives"]) == wordplay.letters(q["words"])]
            n += bool(same) and sum(1 for q in pool if len(wordplay.letters(q.get("gives"))) >= 2
                                    and wordplay.letters(q["gives"]) != wordplay.letters(q["words"])
                                    and not _doubled(q) and not _near_literal(q) and not _phrase_letters(q)
                                    and not _repeats_sibling(q, pool)
                                    and not q.get("select")
                                    and (not ans or ans.startswith(wordplay.letters(q["gives"]))
                                         or ans.endswith(wordplay.letters(q["gives"])))
                                    and (p is not node or _stand_in(q)))
        n += bool(clue) and _lone_stand_in(node) and bool(_loose_words(ann, clue))
    return n


def _repeats_sibling(leaf, pool):
    """Whether `leaf` is a lone repeat word ("again", "twice") giving the letters another fodder leaf of
    the pool already holds: ana<torment>(set, [again]SET) is SET twice, not a synonym (round 17 TSETSE)."""
    ws = re.findall(r"[A-Za-z]+", str(leaf.get("words") or ""))
    if len(ws) != 1 or ws[0].lower() not in REPEAT_WORDS:
        return False
    gives = wordplay.letters(leaf.get("gives"))
    return any(q is not leaf and gives in (wordplay.letters(q.get("words")), wordplay.letters(q.get("gives")))
               for q in pool)


def _phrase_letters(leaf):
    """Whether a leaf of 2+ clue words gives 3+ letters that all come from those words, each as often as
    they stand there (twice or three times with a repeat or count word: "double-headed besom's" BBESOM,
    "trio of women" WWW, "tunes lacking essential character" TUES). Round 15, 4 of 5 judged-fine
    anaSynonym flags: the words are cut or repeated by their own instruction, not swapped for a synonym."""
    words = str(leaf.get("words") or "")
    gives = collections.Counter(wordplay.letters(leaf.get("gives")))
    have = collections.Counter(wordplay.letters(words))
    times = 3 if {w.lower() for w in re.findall(r"[A-Za-z]+", words)} & (REPEAT_WORDS | COUNT_WORDS | {"trio", "pair", "couple", "duo"}) else 1
    return len(words.split()) >= 2 and sum(gives.values()) >= 3 and gives != have and all(have[c] * times >= n for c, n in gives.items())


REPEAT_WORDS = frozenset("twice double doubly doubled again repeatedly repeated two both".split())
#: Count words that say how often the next word's letters come: "three daughters" is DDD,
#: "two ends" ENDEND (quiptic-1168 12a, independent-10551 10a, azed-1886 2d).
COUNT_WORDS = frozenset("two three four five six seven eight nine ten triple treble thrice".split())


def _doubled(leaf):
    """Whether a leaf gives its own words repeated (IT -> ITIT, DO -> DODO), or one letter
    repeated as many times as the clue counts (three eggs -> OOO, three daughters -> DDD): the
    clue's letters again and again, which an anagram may scramble. A count word and a plural S
    on the repeated word are the count's, not letters of it."""
    gives = wordplay.letters(leaf.get("gives"))
    if len(gives) >= 2 and len(set(gives)) == 1 and any(
            w.lower() in COUNT_WORDS for w in re.findall(r"[A-Za-z]+", str(leaf.get("words") or ""))):
        return True  # a letter said several times over
    kept = [w for w in re.findall(r"[A-Za-z]+", str(leaf.get("words") or ""))
            if w.lower() not in REPEAT_WORDS | COUNT_WORDS]
    words = wordplay.letters("".join(kept))
    for base in {words, words[:-1] if words.endswith("S") else words}:
        if base and len(gives) > len(base) and len(gives) % len(base) == 0 and gives == base * (len(gives) // len(base)):
            return True
    return False


def _near_literal(leaf):
    """Whether a leaf's `gives` is its own words with at most one letter off: a typo (eve -> EYE)
    or a number word read as its numeral (anyone -> ANYI, one -> I) inside fodder."""
    w, g = wordplay.letters(str(leaf["words"]).replace("&", " and ")), wordplay.letters(leaf["gives"])
    if len(w) == len(g):
        return sum(a != b for a, b in zip(w, g)) <= 1
    pre = len(os.path.commonprefix([w, g]))
    suf = len(os.path.commonprefix([w[::-1], g[::-1]]))
    return len(g) >= 3 and max(pre, suf) >= len(g) - 1 and max(pre, suf) >= 3


MIDWORD_LEAF = "leaf gives a stretch of its clue words that starts or ends inside a word, with no op for the cut"


@functools.lru_cache(maxsize=1)
def _lexicon_letters():
    """The words of tools/data/lexicon.tsv as lower-case letter strings; empty when it is absent."""
    path = ROOT / "tools" / "data" / "lexicon.tsv"
    if not path.exists():
        return frozenset()
    with path.open(encoding="utf-8", errors="ignore") as f:
        return frozenset(re.sub(r"[^a-z]", "", line.split("\t", 1)[0].lower()) for line in f if line[:1] != "#")


def midword_leaves(tree, clue=None):
    """Leaves of several clue words giving 4+ letters that are a stretch of their own letters
    starting or ending inside a word and are no word of the lexicon or attested pair: a cut
    folded into the leaf, with no op to say it (toughie-3428 4d THEMED: [the day]THED is THE + D;
    sundaytough-211 3d ASPARAGUS: [Taking lid off, burps]URPS is BURPS less B). A wholly made-up
    leaf (RRAUQ, AXIM) was measured too and dropped: 15,336 hits, mostly names, constellations
    and hidden stretches. Needs the lexicon; with none it counts nothing."""
    lex = _lexicon_letters()
    if not lex:
        return 0
    n = 0
    stack = [(tree, ())] if isinstance(tree, dict) else []
    while stack:
        node, anc = stack.pop()
        stack += [(p, anc + (node,)) for p in node.get("parts") or [] if isinstance(p, dict)]
        if "op" in node or not node.get("words") or not node.get("gives") or node.get("select") \
                or node.get("soundsLike") or any(a.get("op") in ("cryptic", "homophone", "spoonerism", "rebus", "reverse",
                                                                 "hidden", "cycling", "reversal") for a in anc):
            continue
        said = re.sub(r"['’]s\b", "", str(node["words"]), flags=re.I)  # a dropped 's is the clue's, not a cut
        g, w = wordplay.letters(node["gives"]).lower(), wordplay.letters(said).lower()
        ends = list(itertools.accumulate(len(wordplay.letters(x)) for x in said.split()))
        if len(ends) < 2 or len(g) < 4 or g in lex or g not in w or re.search(r"\d", str(node["words"])):
            continue
        edges = {0, *ends}  # a stretch is a piece of whole words only if it starts and ends on word edges
        if any(s in edges and s + len(g) in edges for s in range(len(w) - len(g) + 1) if w[s:s + len(g)] == g):
            continue
        # r28+r30 judged: every hit with a cut word in the leaf (half, stripped, limits, skinned, deposing leader) was
        # wrong; the three fine ones (INCR "one in credit", CAPT "captain, briefly", SINGULARP) joined an abbreviation
        cutters = [x for x in re.findall(r"[a-z']+", str(node["words"]).lower()) if x != "briefly"]
        if not any(x in CUT_WORDS or _owner_type(x) in ("deletion", "letter_selection") for x in cutters):
            continue
        if not _known_pair(node["words"], wordplay.letters(node["gives"])):
            n += 1
    return n


def _lone_stand_in(node):
    """Whether anagram `node` scrambles one leaf and that leaf is a plain stand-in word."""
    ps = node.get("parts") or []
    return len(ps) == 1 and isinstance(ps[0], dict) and "op" not in ps[0] and bool(ps[0].get("words")) \
        and bool(ps[0].get("gives")) and not ps[0].get("select") and _stand_in(ps[0])


def _loose_words(ann, clue):
    """Content words of `clue` that no leaf, indicator, definition or link word of annotation
    `ann` claims, less connectives and link-word vocabulary."""
    ann = ann or {}
    return _clue_words(clue) - _accounted_words(ann) - CONNECTIVE_WORDS - link_vocabulary()


def _stand_in(leaf, min_len=2):
    """Whether a leaf directly under an anagram plainly gives a different word for its words: 2+
    letters (round 21: 4 of 4 two-letter hits in 1,254 clean clues were real: ER, EG, CA, RR UP), no digit (a cross-reference gives the other answer, whose letters are the fodder),
    and not a piece of its own letters (BIN -> BI is a cut the leaf did inline). Measured 10-18:
    without these, 10 of 20 sampled direct-leaf hits were right. A well-known pair (lettuce
    -> COS) is not exempt: scrambling it is the fault."""
    words, gives = wordplay.letters(leaf["words"]), wordplay.letters(leaf["gives"])
    return len(gives) >= min_len and not re.search(r"\d", str(leaf["words"])) \
        and not (words.startswith(gives) or words.endswith(gives) or gives in words)


#: Indicator roles swapped between ops that pass every evaluator check (timesjumbo-1682
#: 5d PERSUADE "to limit" on the reversal; independent-12339 13a HAPPY outer<about>,
#: ins<Extremely>; times-29467 9a CATSUIT hid<returned>, rev<from>; cryptic-29995 6d
#: HANGOUT): an indicator the corpus files under ONE other op type nearly always and under
#: this one almost never (tools/data/indicator_roles.json, counted by
#: tools/build_indicator_roles.py over the annotations: the uses of each owned word under
#: each op). Words that serve several ops (about, over, out, round, in) fail the ownership
#: bar and are never flagged. The charade is no owner: its words are plain juxtaposition
#: ("after") that setters put on other ops too.
ROLE_MIN_USES = 20
ROLE_OWNED = 0.95
ROLE_OWN_MAX = 0.02
#: The corroboration a lone flag needs (a swap of two ops flags both): the tree holds an op
#: of the owner type with no indicator or one the corpus files there at most this often.
#: Without it a lone "flipping" on an anagram (BIRTHDATE) or "coming back" on a homophone
#: was a legitimate setter's use in 3 of 20 sampled hits.
ROLE_WEAK = 0.05
ROLE_TYPES = frozenset(_OP_LEXICON.values())
#: Words that are a link between fodder and result as much as an indicator: "tie, poles INTO
#: small diagram" is an anagram (INSET, RUIN: 2 of 3 sampled "into" hits were right).
ROLE_LINKS = frozenset({"INTO"})


def indicator_role_key(text):
    """An indicator phrase as indicator_roles.json keys it: each word's letters, space-joined."""
    return " ".join(w for w in (wordplay.letters(x) for x in str(text or "").split()) if w)


@functools.lru_cache(maxsize=1)
def _indicator_roles():
    """{indicator: {op type: uses}} from tools/data/indicator_roles.json; {} when absent."""
    path = ROOT / "tools" / "data" / "indicator_roles.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _indicators_foreign(op, kind):
    """Whether every indicator of `op` is a well-used word (ROLE_MIN_USES+) that the corpus files under
    `kind` at most ROLE_LOOSE_OWN_MAX of the time."""
    for i in op.get("indicators") or []:
        counts = _role_counts(indicator_role_key(i.get("text")))
        total = sum(counts.values())
        if total < ROLE_MIN_USES or counts.get(kind, 0) > ROLE_LOOSE_OWN_MAX * total:
            return False
    return True


def wrong_role_indicators(tree):
    """How many indicators on a checked op of a type (anagram, reversal, container,
    deletion, hidden, homophone, selection) whose lexicon word is owned by another type:
    at least ROLE_MIN_USES uses there making up ROLE_OWNED of its uses, and at most
    ROLE_OWN_MAX of them under this op's own type."""
    nodes = [n for n in _walk(tree) if _OP_LEXICON.get(n.get("op")) and not n.get("unchecked")]
    loose = []  # (id, own, top) of words a looser bar calls the other op's; flagged only as a mutual pair
    misfiled = []  # (id, own, counts, total) of words their op's type hardly ever carries (round 12 trade)
    flagged, swappable = set(), []  # flagged: (node, indicator) ids; swappable: (id, node type, owner type)
    for node in nodes:
        own = _OP_LEXICON[node["op"]]
        for at, i in enumerate(node.get("indicators") or []):
            key = indicator_role_key(i.get("text"))
            counts = _role_counts(key)
            total = sum(counts.values())
            if total < ROLE_MIN_USES or key in ROLE_LINKS or {own, max(counts, key=counts.get)} == {"hidden_word", "letter_selection"}:
                continue
            top = max(counts, key=counts.get)
            if counts.get(own, 0) <= ROLE_LOOSE_OWN_MAX * total:
                misfiled.append(((id(node), at), own, counts, total))
            if top != own and "hidden_word" not in (own, top) and counts[top] >= ROLE_LOOSE_OWNED * total \
                    and counts.get(own, 0) <= ROLE_LOOSE_OWN_MAX * total:
                loose.append(((id(node), at), own, top))
            if top == own or counts.get(own, 0) > ROLE_OWN_MAX * total:
                continue
            if counts[top] >= ROLE_SWAP_OWNED * total:
                swappable.append(((id(node), at), own, top))
            if (own == "hidden_word" and top == "container") or counts[top] < ROLE_OWNED * total:
                continue  # a hidden word is signalled by container words ("to welcome", "holding")
                #           and by selection words ("essentially", "somewhat"); see ROLE_LINKS
            if any(_OP_LEXICON[o["op"]] == top and _lacks_role(o, top) for o in nodes) \
                    or (top == "deletion" and own == "container" and not any(o.get("op") == "deletion" for o in _walk(tree))):
                # ... or a cut word where the tree has no deletion at all: the cut was folded into a leaf
                # (timesjumbo-1750 27d RHODESIA ins<almost>(late -> DEA, ..)). A lone reversal word
                # ("returned") is let go: the leaf may hold the reversed letters
                
                flagged.add((id(node), at))
    # a charade carrying a word of another op ("elevated" 94% reversal) beside an op carrying a word the
    # corpus files elsewhere is the same swap (timesjumbo-1787 12d NOSY: rev<at the end>, charade<elevated>)
    charade_tops = set()
    for node in _walk(tree):
        if node.get("op") == "charade" and not node.get("unchecked"):
            for i in node.get("indicators") or []:
                counts = _role_counts(indicator_role_key(i.get("text")))
                total = sum(counts.values())
                if total >= ROLE_MIN_USES and counts[max(counts, key=counts.get)] >= 0.9 * total:
                    charade_tops.add(max(counts, key=counts.get))
    # the other direction (times-29578 26a UNSPORTSMANLIKE: charade<poorly>(ana<by>(..), IKE)): a charade
    # carrying a word that is all one op's ("poorly" 97% anagram) while a checked op of that type in the tree
    # has only indicators the corpus files under it under 10% ("by" is 6% anagram) -- the words trade places
    for node in _walk(tree):
        if node.get("op") != "charade" or node.get("unchecked"):
            continue
        for at, i in enumerate(node.get("indicators") or []):
            counts = _role_counts(indicator_role_key(i.get("text")))
            total = sum(counts.values())
            if total < ROLE_MIN_USES:
                continue
            top = max(counts, key=counts.get)
            if counts[top] >= 0.9 * total and top in ("anagram", "reversal") and any(
                    _OP_LEXICON.get(o.get("op")) == top and o.get("indicators") and not o.get("unchecked")
                    and _indicators_foreign(o, top) for o in nodes):
                flagged.add((id(node), at))
    for a, own_a, top_a in swappable:
        if own_a in charade_tops and top_a not in charade_tops:
            flagged.add(a)
    for a, own_a, top_a in swappable:  # a is (node id, indicator index); a mutual swap is its own corroboration (EGRET)
        if any(b[0][0] != a[0] and b[1] == top_a and _swap_alike(b[2], own_a) for b in swappable):
            flagged.add(a)
    # a trade where one word is the other op's and the second is shared between several types, none of them its
    # op's (cryptic-29932 7d EMAIL rev<of some>, hid<upset>: "of some" is 90% hidden, "upset" is reversal or
    # anagram and 0.3% hidden): the first must be mostly the other's type, the second at least a third of this one's
    for x, own_x, cx, tx in misfiled:
        for y, own_y, cy, ty in misfiled:
            if x[0] != y[0] and own_x != own_y and cx.get(own_y, 0) >= 0.5 * tx and cy.get(own_x, 0) >= 0.3 * ty:
                flagged.add(x)
                flagged.add(y)
    for a, own_a, top_a in loose:  # two ops that each carry the other's word: the indicators trade places
        if any(b[0][0] != a[0] and b[1] == top_a and b[2] == own_a for b in loose):
            flagged.add(a)
    return len(flagged) + reversal_of_anagram(tree) + selection_of_one_letter(tree) \
        + extremes_as_one_end(tree) + folded_deletion_leaves(tree) + selection_phrase_elsewhere(tree)


#: A selection phrase ("Last couple in", "first three") filed as the indicator of an anagram, reversal,
#: container or homophone: it names letters to pick, which that op does not do (cryptic-29924 20d BRAVERY
#: ana<Last couple in><re-ordered>(bar), round 12).
SELECTION_PHRASE = re.compile(r"^(?:the\s+)?(?:first|last|final|opening|closing|initial)\s+(?:couple|two|three|four|few|pair|letters?)\b", re.I)


def selection_phrase_elsewhere(tree):
    return sum(1 for node in _walk(tree) if node.get("op") in ("anagram", "reversal", "container", "homophone")
               and not node.get("unchecked")
               for i in node.get("indicators") or [] if SELECTION_PHRASE.match(str(i.get("text") or "").strip()))


#: Both-ends words only: the singular "edge of", "extreme of", "in the extreme" name one end (round 13: RUNES,
#: THOUGHT, OPTICAL, RASP were flagged for last<edge of>, first<edge of>, last<the other extreme of>).
EXTREMES_WORD = re.compile(r"\b(?:extremely|extremities|outer|edges)\b", re.I)
DELETION_LEAF_WORD = re.compile(
    r"\b(?:dropping|drops?|dropped|losing|loses?|lost|leaving|leaves|left|without|missing|shedding|"
    r"sheds?|removing|removed|ejecting|abandoning|dumping|skipping|omitting|lacking)\b", re.I)


def extremes_as_one_end(tree):
    """A first/last op whose indicator says both ends ("extremely", "extremities", "outer",
    "edges"): it picks one letter, so the op should be outer."""
    return sum(1 for node in _walk(tree)
               if node.get("op") in ("first", "last") and not node.get("unchecked")
               and any(EXTREMES_WORD.search(i.get("text") or "") for i in node.get("indicators") or []))


#: Deletion words that are also plain words ("Get left behind" = LAG, "leaf on left" = VO,
#: "tea leaves"): read as a deletion only with a source before and a thing taken after, and
#: not after a verb of being/getting or a preposition/article, nor before a particle.
AMBIGUOUS_DELETION = frozenset("left leaves leaving lost leave".split())
NOT_BEFORE_DELETION = frozenset(
    "whats thats whos get gets got getting be is are was were been being on to the a an of at from in by turn turned "
    "turns and or for with it its his her their our my your tea".split())
NOT_AFTER_DELETION = frozenset("behind over out alone off there here on in up back and or".split())


def _deletion_word_in(words, gives=""):
    """Whether `words` use a deletion word as a deletion: it has a source word before it and
    a removed word after it; an ambiguous one (left, leaves) also needs a clear context."""
    ws = str(words).split()
    for i, w in enumerate(ws):
        bare = re.sub(r"\W", "", w).lower()
        if not DELETION_LEAF_WORD.fullmatch(bare):
            continue
        nxt = re.sub(r"\W", "", ws[i + 1]).lower() if i + 1 < len(ws) else ""
        if bare in ("lacking", "lacks") and (not nxt or nxt in ("in", "of")):
            continue  # nothing follows to be taken out ("Sun quite lacking" = DARK), or "lacking in" = without (WILD): round 13
        if (bare in ("drop", "drops") and nxt == "of" and len(gives) > 1) or (bare in ("shed", "sheds", "shedding") and nxt == "light") \
                or (bare in ("lacking", "lacks") and nxt in ("sense", "brains", "wit")) \
                or (bare in AMBIGUOUS_DELETION and nxt in ("wing", "hand", "side", "bank", "field", "back", "luggage")):
            continue  # idioms and nouns: a drop of water, shed light on, one lacking sense (a NIT), left wing
        if bare in AMBIGUOUS_DELETION:
            if i == 0 or i == len(ws) - 1 or re.sub(r"\W", "", ws[i - 1]).lower() in NOT_BEFORE_DELETION \
                    or re.sub(r"\W", "", ws[i + 1]).lower() in NOT_AFTER_DELETION:
                continue
        return True
    return False


def _is_subsequence(small, big):
    it = iter(big)
    return all(c in it for c in small)


def _cut_evidence(node):
    """Whether a leaf folds a cut into its words rather than meaning a short word. It does only when its
    letters run in order through one of its own clue words (pupils -> PUP). Round 18: a deletion verb among the
    words ("sweetheart removing old", "couple losing millions" = ITE) and a longer word its note names (ITEM less
    M) no longer count: 12 of 13 sampled flags of those shapes were judged fine, a phrase read as one synonym."""
    g = wordplay.letters(node["gives"])
    for t in str(node["words"]).split():
        bare = re.sub(r"\W", "", t)
        w = wordplay.letters(bare)
        if DELETION_LEAF_WORD.fullmatch(bare):
            continue  # round 18: "lacking good manners" = RUDE, "losing millions" = ITE read as one phrase (8 of 9 judged fine)
        if len(w) > len(g) and _is_subsequence(g, w):
            return True
    return False  # round 18: a note naming a longer word (ITEM less M, UNION less O) is a synonym phrase, 12 of 13 judged fine


def folded_deletion_leaves(tree):
    """A leaf of 3+ words holding a deletion word (dropping, losing, ...) that gives only a few
    letters cut from one of its words: the deletion is an op, not folded into the leaf (stylish
    man dropping dead -> UDE)."""
    return sum(1 for node in _walk(tree)
               if "words" in node and "gives" in node and "op" not in node and not node.get("unchecked")
               and len(str(node["words"]).split()) >= 3 and len(node["gives"]) <= 4
               and _deletion_word_in(node["words"], node["gives"]) and _cut_evidence(node))


def selection_of_one_letter(tree):
    """A selection with an indicator over a one-letter word (reg<not until the fourth>([a])
    in everyman-4155 15d MEAN): choosing letters of "a" changes nothing, so the indicator was
    hung on the wrong word (it belongs to "round"). Cross-references ("22's", "K2") are not
    one-letter words."""
    n = 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") in wordplay.SELECT and node.get("indicators") and not node.get("unchecked") \
                and len(parts) == 1 and isinstance(parts[0], dict) and "op" not in parts[0] \
                and not re.search(r"\d", str(parts[0].get("words") or "")):
            n += len(wordplay.letters(parts[0].get("words"))) == 1
    return n


#: Owner share a word needs when the swap with another op is the corroboration: sundaytimes-5202
#: 22a EGRET files rev<stuffing>(hid<back>(..)): "back" is 92% reversal (the rest selections),
#: "stuffing" 82% container, neither at ROLE_OWNED.
ROLE_SWAP_OWNED = 0.8
#: The looser bar for a mutual swap of two ops (timesjumbo-1807 4d ACKNOWLEDGEMENT: ins<bent>(
#: ana<in possession of>(..), L); sundaytimes-5214 21a DWELLINGS: ins<rebuilt>(ana<around>(..), LL)):
#: each carries a word the corpus files mostly under the other's type, which both ops carrying
#: the other's word at once makes certain. "around" is 79% container and 8% anagram.
ROLE_LOOSE_OWNED = 0.7
ROLE_LOOSE_OWN_MAX = 0.10


def _swap_alike(top, own):
    """Whether an op of type `own` may carry a word whose owner is `top`: the same type, or a
    container word on a hidden word (the exemption above)."""
    return top == own or {top, own} == {"container", "hidden_word"}


def reversal_of_anagram(tree):
    """A reversal with an indicator that wraps an anagram directly while another reversal in the
    tree has none: the reversal indicator ("back") was hung on the anagram, whose own indicator
    already scrambles it, and the real reversal was left bare (mephisto-3148 18a STRESSOR:
    rev<back>(ana<troubled>(rest)) + rev(ROSS))."""
    nodes = [n for n in _walk(tree) if n.get("op") == "reversal" and not n.get("unchecked")]
    bare = any(not n.get("indicators") for n in nodes)
    return sum(1 for n in nodes if bare and n.get("indicators") and any(
        isinstance(p, dict) and p.get("op") == "anagram" for p in n.get("parts") or []))


def _role_counts(key):
    """{op type: uses} of an indicator key from indicator_roles.json, the types a vote counts
    for (a charade, substitution or composite is none)."""
    return {t: c for t, c in (_indicator_roles().get(key) or {}).items() if t in ROLE_TYPES}


def _lacks_role(op, kind):
    """Whether op node `op`, of type `kind`, has no indicator, or only ones the corpus never
    files under `kind` (at most ROLE_WEAK of the uses of a word of ROLE_MIN_USES+, or a word
    rarer than that)."""
    for i in op.get("indicators") or []:
        counts = _role_counts(indicator_role_key(i.get("text")))
        total = sum(counts.values())
        if total >= ROLE_MIN_USES and counts.get(kind, 0) > ROLE_WEAK * total:
            return False  # a word the corpus knows for this type; a rarer one ("an anagram of") is no known one
    return True


def _positional_charade(node, key):
    """Whether a POSITION_INDICATORS word on charade `node` plausibly says order. Not when a
    selection op among its pieces has no indicator of its own (quiptic-170 1a ADAMANT
    first(talk): the word belongs to that op), nor "initially" over a run of one-letter pieces
    (cryptic-29255 SCAM: it picks the initials), nor a cover word beside a container or outer
    op (cryptic-29703 HIJACK: "covering" is the container's)."""
    parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    if any(p.get("op") in wordplay.SELECT and not p.get("indicators") for p in parts):
        return False
    if key in ("initially", "originally", "primarily", "firstly"):
        return not (len(parts) >= 3 and all("op" not in p and len(wordplay.letters(p.get("gives"))) == 1 for p in parts))
    return not any(p.get("op") in ("container", "outer") for p in parts)


def misplaced_indicators(tree):
    """How many indicators on a checked op that the lexicon files only under another op."""
    lex = _indicator_lexicon()
    if not lex:
        return 0
    n = 0
    under_container = {id(p) for c in _walk(tree) if c.get("op") == "container"
                       for p in c.get("parts") or [] if isinstance(p, dict)}
    for node in _walk(tree):
        op = node.get("op")
        if op != "charade" or node.get("unchecked"):
            continue  # the other ops share their words too widely for the lexicon to say
        own = "charade"
        # A charade of bare leaves, not held by a container, whose pieces concatenate to its
        # letters cannot hide a container: a container word on it ("carrying", "accepts",
        # "in") is a link between the pieces (telegraph-31202 6d DIVAN, cryptic-21866 8d DOSH).
        leaf_only = id(node) not in under_container and not any(
            "op" in p for p in node.get("parts") or [] if isinstance(p, dict))
        for i in node.get("indicators") or []:
            key = " ".join(w for w in (wordplay.letters(x) for x in str(i.get("text") or "").split()) if w)
            if not key or lex.get(own, {}).get(key, 0) or key.lower() in ORDERING_INDICATORS:
                continue
            if leaf_only and not any(c >= MISPLACED_MIN_USES for t, d in lex.items()
                                     if t not in (own, "container") for c in [d.get(key, 0)]):
                continue
            if key.lower() in POSITION_INDICATORS and _positional_charade(node, key.lower()):
                continue
            if leaf_only and key.lower() in EXAMPLE_MARKERS:
                continue  # "perhaps" marks a leaf as an example of its clue words (times-26889 15d VAN)
            n += any(c >= MISPLACED_MIN_USES for t, d in lex.items() if t != own
                     for c in [d.get(key, 0)])
    return n


#: Two ways a wrong clue passed every check (a resample of 100 passing clues found 4
#: wrong, 10-18); each is a ratchet field. The evaluator takes a leaf's `gives` as filed
#: and removes a deletion's letters from anywhere, so neither could be seen.
#:   * BARE_INITIAL: a leaf giving the first letter of its word where no abbreviation
#:     says so and no selection op sits above it (ZOCCO's `first` missing);
#:   * DELETION_SCOPE: a deletion over a charade whose indicator names an end and whose
#:     removed letters are not at that end (BORON, BORE+ON less E, "endlessly").
#: Two more were measured over the 506k trees and dropped, under the 80% bar:
#:   * a synonym nothing else attests (URTICARIA, [priest] ICA): 3-4 letter values that
#:     are no lexicon word and no known pair were about 15% wrong-looking (names, rivers
#:     and places are mostly right), with a corpus count of one about 35%: a fake synonym
#:     needs a thesaurus, not a table;
#:   * an indicator word filed as a leaf (MIMICS, [doubly]IM): "doubly" is not in the
#:     indicator lexicon, and short values on lexicon indicators (without EX, around C)
#:     were about 15% wrong; the narrow form, a repetition word valued like the leaf
#:     before it (117 clues), reads right to a solver ([twice]IT after [sex]IT) and a
#:     redo has no other way to write a repeat.
BARE_INITIAL = "leaf gives the first letter of its words with no selection"
DELETION_SCOPE = "deletion whose removed letters are not where its indicator says"
#: Two more, from the second resample (10-18, 7 wrong in 100 passing clues); see
#: wrong_role_indicators and deletion_inside_component. Measured over the 506k trees,
#: 20 random hits each judged by hand: 951 hits, 20/20 (and 20/20 on a second draw
#: before the lone-flag corroboration) for the role rule; 1124 hits, 20/20 and 20/20 for
#: the deletion rule. A third, a leaf giving a non-word (MORECAMBE CAMBE), was dropped:
#: 138k leaves give a letter string the word list lacks, and 17 of 20 sampled were right.
WRONG_ROLE = "indicator filed on an op of another type"
CONTAINER_INSIDE = "container over a charade whose piece goes in inside one piece of it"
DELETION_INSIDE = "deletion over a charade that takes letters from one piece, or a whole piece the charade added"
#: Round 7 (12 of 300 passing clues wrong, 4.0%): five shapes the earlier rules passed. Each hit
#: sample of 20 was judged by hand against the same standard as the rules above.
UNINDICATED_BARE = "op with no indicator of its own (or one indicator shared by several ops)"
SHARED_INDICATOR = "indicator words claimed twice: on two ops, or also as a leaf's clue words"
HALF_LEAF = "leaf giving half of its word with no op carrying the half"
DELETION_SCATTERED = "one 'half' deletion over several words, its letters picked out of all of them"
REVERSE_PHRASE = "reverse reading over a whole phrase of the clue"


@functools.lru_cache(maxsize=1)
def _attested():
    """(abbreviation pairs {(WORD, LETTERS)}, usage lexicon {WORD: {LETTERS: n}}): what
    clue words are known to give. Empty when a table is missing, so a rule stands down."""
    try:
        import build_abbreviations as ba
        pairs = {(ba.letters_of(w), k) for k, ws in ba.table().items() for w in ws}
        usage = json.loads((ROOT / "tools" / "data" / "lexicons" / "blocks.json").read_text())
    except (OSError, ValueError, ImportError):
        return set(), {}
    return pairs, {ba.letters_of(w): v for w, v in usage.items()}


#: Standard one-letter readings the tables lack (round 10: PRMAN "Played" P, EYING "electronically" E-).
_EXTRA_PAIRS = frozenset({("PLAYED", "P"), ("ELECTRONICALLY", "E"), ("ELECTRONIC", "E"),
                          ("KOSHER", "K"), ("LITTLE", "L"), ("QUALITY", "Q"),  # round 11
                          ("FAILING", "F"),  # round 12 (a grade)
                          ("ROUBLE", "R"), ("ROUBLES", "R"),  # round 13 (cryptic-22221 ARGENT)
                          ("VIOLET", "V"), ("LICENTIATE", "L"), ("ACROSS", "A"),  # round 14 (judged standard)
                          ("WESTERLY", "W"), ("EASTERLY", "E"), ("NORTHERLY", "N"), ("SOUTHERLY", "S"),  # round 17:
                          ("UNITED", "U"), ("WITHOUT", "W"),
                          ("METERS", "M"), ("METRES", "M"), ("INSTITUTE", "I")})  # round 18 (judged fine)  # compass adjectives, "united" and "without" (w/o), judged fine


def _known_pair(words, gives):
    """Whether (clue words, letters) is an abbreviation the table holds or a reading the
    usage lexicon has seen 3+ times (blocks.json keeps no rarer ones)."""
    pairs, usage = _attested()
    if (re.sub(r"[^A-Z]", "", str(words).upper()), gives) in _EXTRA_PAIRS:
        return True
    # "volume's" (V) and "uranium's" (U): the possessive is the clue's, not part of the word
    bare = re.sub(r"['’]s\b", "", str(words), flags=re.I)
    for text in (str(words), bare):
        key = re.sub(r"[^A-Z0-9]", "", text.upper())
        if (key, gives) in pairs or usage.get(key, {}).get(gives, 0) > 0:
            return True
    return False


def _abbreviation_pair(words, gives):
    """Whether the abbreviation table (not the usage lexicon, which holds letters that were picked
    from the word) or the extra pairs give `words` as the letter `gives`."""
    pairs, _ = _attested()
    key = re.sub(r"[^A-Z]", "", str(words).upper())
    return (key, gives) in pairs or (key, gives) in _EXTRA_PAIRS


def _word_leaves(tree):
    """(leaf, ancestors) for every leaf of clue words with a `gives`, each ancestor an op node."""
    stack = [(tree, ())] if isinstance(tree, dict) else []
    while stack:
        node, anc = stack.pop()
        stack += [(p, anc + (node,)) for p in node.get("parts") or [] if isinstance(p, dict)]
        if "op" not in node and node.get("words") and node.get("gives"):
            yield node, anc


BARE_INITIAL_MIN_LETTERS = 6
_ORDINALS = {w.upper(): chr(65 + i) for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
    "fifteenth sixteenth seventeenth eighteenth nineteenth twentieth".split())}


#: A deletion indicator that names the end it takes ("opening ... ignored by", hoaxer less the D
#: of Dalloway's): the cut leaf's letter is picked by that word (timesjumbo-1690 29a).
_POSITION_WORD = re.compile(r"\b(opening|first|initial\w*|start\w*|head|top|lead\w*|beginning|last|final\w*|"
                            r"end|tail|finish\w*|closing|hint|touch|trace)\b", re.I)


_ACROSTIC_WORD = re.compile(r"\b(primarily|originally|initially|firstly|at first|for starters|first of all|"
                            r"to begin with|at the start|in the beginning|at the outset)\b", re.I)


def _acrostic_run(leaf, anc):
    """Whether `leaf` stands in a charade beside a first-letter pick that carries the indicator
    ("primarily", "originally"): one indicator over the run of initials (round 15, 3 of 8 judged-fine
    bareInitial flags: first<primarily>(Proudly) + impenitent I + artiste A ...)."""
    return any(a.get("op") == "charade" and any(
        isinstance(p, dict) and p.get("op") == "first" and any(
            _ACROSTIC_WORD.search(str(i.get("text") or "")) for i in p.get("indicators") or [])
        for p in a.get("parts") or [])
        and any(p is leaf for p in a.get("parts") or []) for a in anc)


def _position_word_cut(leaf, anc):
    """Whether `leaf` is the cut part of a deletion and its own words name the end ("leader" -> L)."""
    return bool(_POSITION_WORD.search(str(leaf.get("words") or ""))) and any(
        a.get("op") == "deletion" and any(p is leaf for p in (a.get("parts") or [])[1:]) for a in anc)


def _split_word_leaf(leaf, anc):
    """Whether a sibling leaf holds the same word and gives its tail: one word split into its
    first letter and the rest (ins(STRIPED, P) from "pinstriped")."""
    w, g = wordplay.letters(leaf["words"]), wordplay.letters(leaf["gives"])
    return any(a.get("op") for a in anc[-1:]) and any(
        p is not leaf and isinstance(p, dict) and "op" not in p and wordplay.letters(p.get("words")) == w
        and len(wordplay.letters(p.get("gives"))) >= 3 and w.endswith(wordplay.letters(p.get("gives")))
        for p in anc[-1].get("parts") or [])


def bare_initials(tree):
    """Leaves of one clue word of BARE_INITIAL_MIN_LETTERS+ letters that give its first
    letter, where no selection op is above the leaf and the word has no one-letter
    reading in the abbreviation table or the usage lexicon. The initial was picked by a
    clue word elsewhere ("primarily") that no op carries, or by none (ZOCCO).
    Measured 10-18 over 506k trees: with shorter words, or two letters, a third to a
    half of the hits were abbreviations the tables lack (CO company, L little, E Earl's);
    this form was 23 of 25 real."""
    pairs, usage = _attested()
    if not usage:
        return 0  # no usage lexicon here: stand down
    n = 0
    for leaf, anc in _word_leaves(tree):
        gives = wordplay.letters(leaf["gives"])
        words = wordplay.letters(leaf["words"])
        bare = wordplay.letters(re.sub(r"['’]s\b", "", leaf["words"], flags=re.I))  # "volume's" reads as volume
        if len(gives) != 1 or len(leaf["words"].split()) != 1 or len(words) < BARE_INITIAL_MIN_LETTERS \
                or not words.startswith(gives) or leaf.get("select"):
            continue
        if any(a.get("op") in wordplay.SELECT for a in anc):
            continue
        if any(a.get("op") == "deletion" and any(p is leaf for p in (a.get("parts") or [])[1:])
               and any(wordplay.letters(i.get("text")) == words or _POSITION_WORD.search(str(i.get("text") or ""))
                       for i in a.get("indicators") or []) for a in anc):
            continue  # del<Wifeless>(.., [Wifeless]W): the words that cut name what is cut (RIGHTING)
        if words in _ORDINALS and _ORDINALS[words] == gives:
            continue  # twentieth is T, the twentieth letter (FILET)
        if _acrostic_run(leaf, anc) or _position_word_cut(leaf, anc) or _split_word_leaf(leaf, anc):
            continue
        # kilograms -> K as kilos are: the unit's long form is its prefix's word plus "gram(s)"
        forms = {words, bare, re.sub(r"GRAMS?$", "", bare)}
        forms |= {wordplay.letters(h) for h in re.split(r"[-‐-―]", str(leaf["words"]))}  # gravity-force -> G
        if not any(len(k) == 1 for w in forms for k in usage.get(w, {})) and not _known_pair(leaf["words"], gives) \
                and not any((w, gives) in pairs for w in forms):
            n += 1
    return n


_DEL_END = re.compile(
    r"\b(endless(ly)?|unending|curtail\w*|docked|tailless|detailed|unfinished|incomplete|not finished|"
    r"cut short|shortly|shortened|short|abridged|truncated|clipped|almost|nearly|not quite|"
    r"(?:without|losing|dropping|missing|lacking|shedding|abandoning) (?:its |his |her |their |the |an? )?"
    r"(?:end|tail|finish|finishing|ending|last))\b", re.I)
_DEL_HEAD = re.compile(
    r"\b(headless(ly)?|beheaded|topless|decapitated|unopened|leaderless|not starting|"
    r"(?:without|losing|dropping|missing|lacking|shedding|abandoning) (?:its |his |her |their |the |an? )?"
    r"(?:head|top|lead|start|opening|first|beginning))\b", re.I)


#: Indicators that point inside a word, so a deletion by one may take a middle letter.
_DEL_MIDDLE = re.compile(r"\b(heart|centre|center|middle|core|inside|interior|gutted|empty|emptied|hollow|"
                         r"disheartened|heartless|innards|guts|bowels|ends?|edges?|extremities|"
                         r"outsides?|regularly|alternate|odd|even)\w*", re.I)


#: The middle indicators that name the heart of a word, which a deletion may take from
#: one piece of a charade when the letters are not the whole's centre.
_DEL_HEART = re.compile(r"\b(heart|centre|center|middle|core|disheartened|heartless|half-?hearted)\w*", re.I)
_DEL_HALF = re.compile(r"\bhalf\b|\bhalf-", re.I)


#: Bare function words whose letters a deletion over their phrase may take (independent-11544
#: 25a THROW: THE+ROW less E, "saving energy").
FUNCTION_PIECES = frozenset("THE A AN OF TO AND IN".split())
#: How far from the exact middle of the whole a cut may sit and still be "the heart of the whole".
HEART_SLACK = 1


def deletion_inside_component(tree, clue=None, answer=None):
    """Deletions over a charade (indicator anywhere in the clue) that take letters from
    ONE piece, or take whole pieces the charade added. ARCH+IDEA+CON less I,
    "originally dismissed" after "notion" (indysunday-1538 9d): an indicator acts on the
    piece it sits by, so the deletion is del(IDEA, I) inside the charade. Three forms,
    each with every reading of the removed letters:
      - letters strictly inside one piece, touching neither end of the whole, with an
        indicator that names no end, head or middle (a heart word counts when the letters
        are not the whole's own centre; "half" counts when they touch the whole's end);
        CON+SIDE+RABBLE less B, "half-hearted" (sundaytel-2922 3d), DIAL+SECT less S,
        "ignoring singular" (everyman-3750 11a), FAVE+LAGS less GS, "half-cut"
        (sundaytimes-4834 21d), whether the indicator is among the pieces or after them;
      - letters that are exactly whole pieces: a charade adds a piece for the deletion to
        remove (NICE+ICE less NICE; Actor+more+English less EE, telegraph-30860 20a); also
        when one reading is such a piece and another sits inside a different one (A+CHING+I
        less I, ACHING: the I that goes is the piece just added);
      - letters at the whole's own end or start that are wholly inside the last or first
        piece, whatever the indicator (round 6, 4 of 12 resampled false negatives: FAT+ALE
        less E "finished early", RAM+BUNCH less H "mostly", ODO+ROUSE less E "endless"):
        the same cut is del(ALE, E) inside the charade, which is where the indicator sits.
        3699 newly counted over the corpus, 20 of 20 sampled judged wrong.
    With `answer`, a deletion that is the whole tree is also read on only the readings that
    leave the answer (round 7: INSPIRATION, IN+SPIN+RATION less N "before its conclusion":
    the N that makes the answer is SPIN's, but the other Ns made the letters ambiguous).
    Needs the clue text; with none it counts nothing."""
    if not clue:
        return 0
    n = 0
    want_all = wordplay.letters(answer) if answer else None
    fodder = {id(p) for a in _walk(tree) if a.get("op") == "anagram" for p in a.get("parts") or [] if isinstance(p, dict)}
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "deletion" or len(parts) < 2 or node.get("unchecked") \
                or not all(isinstance(p, dict) for p in parts) or parts[0].get("op") != "charade":
            continue
        text = " ".join(str(i.get("text") or "") for i in node.get("indicators") or [])
        comps = parts[0].get("parts") or []
        if len(comps) < 2 or not all(isinstance(c, dict) for c in comps):
            continue
        try:
            cvals = [sorted(wordplay.values(c)) for c in comps]
            cuts = [sorted(wordplay.values(p)) for p in parts[1:]]
        except Exception:
            continue
        if any(not v for v in cvals) or any(not v for v in cuts):
            continue
        heart, half = bool(_DEL_HEART.search(text)), bool(_DEL_HALF.search(text))
        named = bool(_DEL_END.search(text) or _DEL_HEAD.search(text) or (_DEL_MIDDLE.search(text) and not heart))
        for want in ((None, want_all) if want_all and node is tree else (None,)):
            seen, in_piece, whole_pieces = 0, True, True
            end_piece, any_piece, seam, in_function, all_centred = True, False, False, True, True
            for combo in itertools.product(*cvals):
                f = "".join(combo)
                bounds = [0]
                for c in combo:
                    bounds.append(bounds[-1] + len(c))
                for rs in itertools.product(*cuts):
                    for r in {"".join(rs), "".join(reversed(rs))}:
                        if not r:
                            continue
                        for m in re.finditer("(?=" + re.escape(r) + ")", f):
                            s, e = m.start(), m.start() + len(r)
                            if want and f[:s] + f[e:] != want:
                                continue
                            seen += 1
                            one = any(a <= s and e <= b for a, b in zip(bounds, bounds[1:]))
                            is_piece = any(a == s and b == e for a, b in zip(bounds, bounds[1:]))
                            # a doubled letter at the end (CAL[L], MIT[T]) leaves the same word cut either way
                            edge = s == 0 or e == len(f) or f[:s] + f[e:] in (f[len(r):], f[:-len(r)])
                            centred = abs(s - (len(f) - len(r)) / 2) <= HEART_SLACK
                            # a letter doubled across a seam (HOPS+SCOTCH less S) is the seam's, not one piece's
                            seam = seam or (e in bounds[1:-1] and f[e:e + len(r)] == r) \
                                or (s in bounds[1:-1] and s >= len(r) and f[s - len(r):s] == r)
                            # letters out of a bare function word ("the" in THE+ROW less E, "saving
                            # energy") are the phrase's: the cut takes them from the whole phrase
                            in_function = in_function and any(
                                a <= s and e <= b and "op" not in c and wordplay.letters(c.get("words")) in FUNCTION_PIECES
                                for (a, b), c in zip(zip(bounds, bounds[1:]), comps))
                            whole_pieces = whole_pieces and s in bounds and e in bounds
                            all_centred = all_centred and centred  # BROOCH+URE less O: one O is off-centre
                            in_piece = in_piece and one and not is_piece and (not edge or half)
                            end_piece = end_piece and one and not is_piece and edge
                            any_piece = any_piece or is_piece
            # anagram fodder whose cut letters sit in one piece only (BORSTAL: Bolts+are less E,
            # "endlessly"; round 9, 5 of 5 sampled fine): the indicator is by that piece and the
            # scramble hides the seam, so the inner deletion would say nothing more; not for "not half": the half
            # is one piece's (azed-2517 31a SEAMANLIKE, round 12)
            # round 18: also when the letters occur in several pieces (TAKE+RECEIPT less E, HEADWAY+SURRENDER
            # less E; 5 of 6 judged fine): a scramble hides every seam, so only a piece the charade added counts
            lone = id(node) in fodder and not half
            if seen and ((not named and in_piece and not seam and not in_function and not (heart and all_centred)
                          and not lone) or whole_pieces or (end_piece and not lone) or any_piece):
                n += 1
                break
    return n


def container_inside_component(tree, answer=None):
    """1 when the whole tree is a container over a charade holder whose piece goes in at gaps
    that all lie inside ONE of the holder's pieces, never at a join (timesjumbo-1490 38d
    LIVINGWAGE: ins(LIV+IN+GAGE, W) is really LIV+IN+G(W)AGE; toughie-3357 17d LASTGASP:
    ins(LAG+ASP, ST) is LA(ST)G+ASP). The indicator acts on the one piece it sits by, so the
    container goes inside the charade: ins(piece, letters). The evaluator lets the piece land
    at any gap, so the wide holder passed. A container under another op (everyman-3751 8d
    ELEANORRIGBY: ins(E+LEAN+ORB, RIG) is OR(RIG)B, in a charade with Y) is read on a result that
    sits inside the answer. Needs the answer; with none it counts nothing."""
    if not answer or not isinstance(tree, dict):
        return 0
    want = wordplay.letters(answer)
    # a container right under reversals that are the whole tree is read on the answer turned back
    # (ftcryptic-17934 3d TRADESMAN: rev(ins(NAMED+ART, S)): the S goes inside NAMED, round 12)
    top, flips = tree, 0
    while top.get("op") == "reversal" and not top.get("unchecked") and len(top.get("parts") or []) == 1 \
            and isinstance(top["parts"][0], dict):
        top, flips = top["parts"][0], flips + 1
    if flips and top.get("op") == "container":
        rest = sum(_container_inside(node, want, False) for node in _walk(top) if node is not top)
        return rest + _container_inside(top, want[::-1] if flips % 2 else want, True)
    return sum(_container_inside(node, want, node is tree) for node in _walk(tree))


def _container_inside(tree, want, whole):
    """1 when container `tree` puts its piece only inside one piece of its charade holder, its
    result being the answer `want` (`whole`) or a stretch of it."""
    if tree.get("op") != "container" or tree.get("unchecked"):
        return 0
    parts = tree.get("parts") or []
    if len(parts) != 2 or not all(isinstance(p, dict) for p in parts) or parts[0].get("op") != "charade" \
            or parts[0].get("unchecked"):
        return 0
    comps = parts[0].get("parts") or []
    if len(comps) < 2 or not all(isinstance(c, dict) for c in comps):
        return 0
    # one selection over several words (last<tips from>(Wills, Kate)) is one letter per word: the
    # join between those words is a join between pieces, where the wide holder is fair
    comps = [x for c in comps for x in (
        [{**c, "parts": [q]} for q in c["parts"]]
        if c.get("op") in wordplay.SELECT and len(c.get("parts") or []) > 1 and not c.get("unchecked")
        and all(isinstance(q, dict) for q in c["parts"]) else [c])]
    try:
        cvals = [sorted(wordplay.values(c)) for c in comps]
        ins = sorted(wordplay.values(parts[1]))
    except Exception:
        return 0
    seen = False
    for combo in itertools.product(*cvals):
        f = "".join(combo)
        bounds = {0}
        for c in combo:
            bounds.add(max(bounds) + len(c))
        for i in ins:
            for k in range(1, len(f)):
                got = f[:k] + i + f[k:]
                if got == want if whole else (len(got) < len(want) and got in want):
                    if k in bounds:
                        return 0  # one reading puts it at a join: the wide holder is fair
                    seen = True
    return int(seen)


def deletion_scope(tree, any_whole=False, answer=None):
    """Deletions over a charade (or, with `any_whole`, over anything) whose indicator
    names one end and where no reading of the removed letters sits at that end of the
    whole. The evaluator removes the letters from anywhere (BORE+ON less E spells BORON
    though "endlessly" takes the N). With `answer`, a deletion that is the whole tree also has
    to leave the answer: (SURE+F+ACE) less E "nearly" leaves SUREFAC at the end of the whole,
    but the E that makes SURFACE is SURE's, so "nearly" acts on SURE alone (timesjumbo-1479
    19d, round 11)."""
    n = 0
    want = wordplay.letters(answer) if answer else None
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "deletion" or len(parts) < 2 or not all(isinstance(p, dict) for p in parts):
            continue
        if not any_whole and parts[0].get("op") != "charade":
            continue
        text = " ".join(str(i.get("text") or "") for i in node.get("indicators") or [])
        end, head = bool(_DEL_END.search(text)), bool(_DEL_HEAD.search(text))
        if end == head:
            continue
        try:
            wholes = wordplay.values(parts[0])
            cuts = [sorted(wordplay.values(p)) for p in parts[1:]]
        except Exception:
            continue
        ok = False
        for f in wholes:
            for rs in itertools.product(*cuts):
                for r in {"".join(rs), "".join(reversed(rs))}:
                    hit = f.endswith(r) if end else f.startswith(r)
                    if hit and want and node is tree:
                        hit = (f[:len(f) - len(r)] if end else f[len(r):]) == want
                    ok = ok or hit
        n += not ok
    return n


def deletion_scope_answer(tree, answer):
    """Deletions the plain deletion_scope passes that fail once the answer picks the reading:
    the whole tree is (SURE+F+ACE) less E "nearly", a final E exists (ACE's) so the end reads
    fine, but the E whose loss makes SURFACE is SURE's (timesjumbo-1479 19d, round 11)."""
    return max(0, deletion_scope(tree, answer=answer) - deletion_scope(tree)) if answer else 0


#: Selections that two adjacent words may share one indicator for ("so extend tops" over
#: first(so) + first(extend)) and the sound pair ("doubly" over two homophones): the one
#: shared form a solver is still told the truth by (cyclops-591 7d SPARSE judged fine in
#: round 7). Any other op, or three of these, with one indicator is a lie about the clue.
#: "deletion" joins them (round 14, 10 of 28 sampled false flags): "Reserve volume endlessly", "kings
#: must leave" cut one letter from each of two neighbouring words, the one indicator's plural or
#: position says both; _pair_adjacent holds the two to neighbouring words as for a selection.
_SHARED_OK = frozenset(wordplay.SELECT) | {"homophone", "deletion"}


def unindicated_uncovered(tree):
    """Checked ops that need an indicator and have none, other than the second of an
    adjacent pair of one selection or homophone op whose twin carries the indicator.
    unindicated_ops counts those too; this is the stricter reading (round 7, 12 of 300
    passing clues wrong: VIOLA, mid<essentially> shared by three middles; MARACA, one
    "all names withheld" over three deletions; ETUI, CHATE, the insertion and the hidden
    word nothing signals). Same exclusions as unindicated_ops."""
    spoken = {id(p) for s in _walk(tree) if s.get("op") == "spoonerism"
              for p in s.get("parts") or [] if isinstance(p, dict) and p.get("op") == "homophone"}
    n = 0
    copies = _repeated_copies(tree) | _moved_letter_ops(tree) | _self_signed_ops(tree) \
        | _self_holding_containers(tree) | _chained_deletions(tree) | _substituting_containers(tree) \
        | _lone_implicit_op(tree) | _lone_bare_sound(tree) | _paired_ends(tree) | _picks_with_indicator(tree) \
        | _outer_in_boundary_container(tree) | _lone_bare_first(tree)
    for parent in [{"parts": [tree]}] + list(_walk(tree)):
        groups = {}
        kids = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        for p in kids:
            if p.get("op") in NEEDS_INDICATOR and not p.get("unchecked") \
                    and id(p) not in spoken and id(p) not in copies:
                groups.setdefault(p["op"], []).append(p)
        for op, ns in groups.items():
            bare = [x for x in ns if not x.get("indicators") and not _folded_signal(x, len(ns) == 1)]
            if op == "deletion" and parent.get("op") == "deletion" and parent.get("indicators"):
                # del(del(Variety, five), lines) "taken from": one indicator over both cuts (EAUDEVIE)
                bare = [x for x in bare if x is not kids[0]]
            if bare and (op in wordplay.SELECT or op == "deletion") and len(ns) > 2 and _list_run(kids, ns):
                continue  # initials of a list: the one indicator stands at the run's end (GARB)
            if bare and not (op in _SHARED_OK and len(ns) == 2 and len(bare) == 1 and _pair_adjacent(ns)):
                n += len(bare)
    return n


#: The most clue characters (one short word and its spaces) that may lie between the two words one
#: shared selection or sound indicator serves: "so extend tops", not "Marsh was awash with plants
#: initially" (times-29450 6a SWAMP, round 12).
SHARED_PAIR_GAP = 5


def _pair_adjacent(ns):
    """Whether two same-op nodes stand side by side in the clue, each counted with its indicator (or
    have no places given). Only picks of letters are held to it: a pair of sounds shares its one
    indicator across a longer stretch (cyclops-591 7d, round 7)."""
    if ns[0].get("op") not in wordplay.SELECT and ns[0].get("op") != "deletion":
        return True
    spans = []
    for x in ns:
        items = [(q["at"], q["at"] + len(q["words"])) for q in _walk(x)
                 if "op" not in q and q.get("words") and isinstance(q.get("at"), int)]
        items += [(i["at"], i["at"] + len(str(i.get("text") or ""))) for q in _walk(x)
                  for i in q.get("indicators") or [] if isinstance(i, dict) and isinstance(i.get("at"), int)]
        leaves = [q for q in _walk(x) if "op" not in q and q.get("words")]
        if not items or any(not isinstance(q.get("at"), int) for q in leaves):
            return True
        spans.append((min(a for a, _ in items), max(b for _, b in items)))
    (a0, a1), (b0, b1) = sorted(spans)
    return b0 - a1 <= SHARED_PAIR_GAP


#: Words an op's indicator can be a prefix or suffix of inside one compound clue word
#: (Oversell = over + sell, heartbroken = heart + broken), beside the indicator lexicon's.
_FOLD_AFFIX = {"reversal": ("over", "back", "about", "return", "upset"),
               "anagram": ("broken", "mixed", "wild", "crazy", "drunk"),
               "first": ("top", "head", "leader"),  # mountaintop -> M (nation-3423 19a FARM); redhead, ringleader, knucklehead (round 12)
               "last": ("tail", "foot", "bottom")}
_FOLD_PHRASE = {op: re.compile(r"(?:%s)\s+(?:of|in|from)\s+\w+" % words, re.I) for op, words in (
    ("outer", "extremes|ends|edges|sides|borders|limits|fringes|outskirts|boundaries|extremities|margins"),
    ("first", "first|initial|opening|start|head|top|beginning|front|half|drop"),
    ("last", "final|last|end|close|closing|ending|tail|finish|back|bottom|half"),
    ("nth", "second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"),
    ("middle", "heart|centre|center|middle|core"))}


_NOPOSS = re.compile(r"(?!)")
#: Compounds that end in an affix word but are not a pick of the other word (a skinhead is a person; round 11).
_NOT_COMPOUND = frozenset()  # round 14: skinhead is S in two judged-fine clues (STALKER, SURFEIT); no longer excluded
#: "champion's top": the leaf's own words end in the pick's word after a possessive (round 12 UNEXCITED).
_FOLD_POSS = {op: re.compile(r"^\S+['\u2019]s?\s+(?:%s)$" % words, re.I) for op, words in (
    ("first", "first|initial|opening|start|head|top|beginning|front"),
    ("last", "final|last|end|close|closing|ending|tail|finish|bottom"),
    ("nth", "second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"))}


def _folded_signal(node, alone=True):
    """Whether bare op `node` holds one leaf whose single clue word is a compound with the op's
    indicator at an edge and 3+ letters of the other word left (Oversell for a reversal), or a
    pick the leaf's own words name (final of competition, champion's top), or a pick of a word
    whose first letter is a known reading of it (first(President) is P: the leaf could be P), or
    an anagram whose fodder leaf carries the indicator as a prefix or suffix (Outdated -> DATED).
    The known-pair reading is for a pick that stands alone: two picks of one op beside an indicator
    that serves both (Marsh, plants initially) leave the first with none."""
    ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    if node.get("op") in ("container", "hidden"):
        # roundabout = round + about (FE around RE), Something = some + thing (HINGIS hidden in "thing I s..."):
        # a leaf word that opens or closes with the op's own well-used indicator (round 13)
        kind = "container" if node["op"] == "container" else "hidden_word"
        for p in ps:
            ws = str(p.get("words") or "").split()
            if "op" in p or not ws or (node["op"] == "container" and len(ws) != 1):
                continue
            edges = [wordplay.letters(ws[0]).upper()] + ([wordplay.letters(ws[-1]).upper()] if len(ws) > 1 else [])
            if any(len(w) - len(k) >= 3 and (w.startswith(k) if i == 0 else w.endswith(k))
                   for i, w in enumerate(edges) for k in _compound_indicator_keys(kind)):
                return True
    if node.get("op") == "anagram":
        said = _anagram_indicator_letters()
        for p in ps:
            w, g = wordplay.letters(p.get("words")), wordplay.letters(p.get("gives"))
            if "op" not in p and len(str(p.get("words") or "").split()) == 1 and len(g) >= 2 and w != g and any(
                    len(k) >= 3 and ((w.startswith(k) and w[len(k):] == g) or (w.endswith(k) and w[:-len(k)] == g))
                    for k in said):
                return True
    if len(ps) == 1 and "op" not in ps[0] and node.get("op") in _FOLD_PHRASE:
        # "final of competition" for last(..): the leaf's own opening words name the pick
        # (times-28920 22d ARENA); the words still do one job, so no indicator is filed.
        if _FOLD_PHRASE[node["op"]].match(str(ps[0].get("words") or "")) \
                or _FOLD_POSS.get(node["op"], _NOPOSS).match(str(ps[0].get("words") or "").strip()):
            return True
        lw = wordplay.letters(re.sub(r"['’]s\b", "", str(ps[0].get("words") or ""), flags=re.I))
        if alone and node["op"] in ("first", "last") and len(str(ps[0].get("words") or "").split()) == 1 and lw and _abbreviation_pair(
                lw, lw[0] if node["op"] == "first" else lw[-1]):
            return True
    if len(ps) != 1 or "op" in ps[0] or len(str(ps[0].get("words") or "").split()) != 1:
        return False
    w = wordplay.letters(ps[0]["words"]).lower()
    return w not in _NOT_COMPOUND and any(
        len(w) - len(k) >= 3 and (w.startswith(k) or w.endswith(k)) for k in _FOLD_AFFIX.get(node.get("op"), ()))


def _list_run(kids, ns):
    """Whether the same-op nodes `ns` among `kids` are adjacent, plain-leaf, and exactly one
    carries an indicator, standing first or last in the run ("starts off game, at, rock, bottom")."""
    idx = [i for i, p in enumerate(kids) if any(p is x for x in ns)]
    if idx != list(range(idx[0], idx[0] + len(idx))):
        return False
    ind = [x for x in ns if x.get("indicators")]
    if not (len(ind) == 1 and (ind[0] is ns[0] or ind[0] is ns[-1]) and all(
            x.get("parts") and isinstance(x["parts"][0], dict) and "op" not in x["parts"][0] for x in ns)):
        return False
    # with the clue positions given, the indicator must stand right beside the run (VIOLA: an
    # indicator elsewhere in the clue is a lie about the other words)
    leaves = [x["parts"][0] for x in ns]
    marks = ind[0]["indicators"]
    if all("at" in q and q.get("words") for q in leaves) and all("at" in i for i in marks):
        lo, hi = min(q["at"] for q in leaves), max(q["at"] + len(q["words"]) for q in leaves)
        return any(lo - (i["at"] + len(i["text"])) in range(0, 4) or i["at"] - hi in range(0, 4) for i in marks)
    return True


@functools.lru_cache(maxsize=None)
def _compound_indicator_keys(kind):
    """Lexicon indicators of type `kind` that are one word of 4-8 letters with 100+ uses: the ones that
    can open or close a compound clue word (round, some) without being a stray syllable."""
    return tuple(k for k, n in (_indicator_lexicon().get(kind) or {}).items() if 4 <= len(k) <= 8 and n >= 100)


@functools.lru_cache(maxsize=1)
def _anagram_indicator_letters():
    """The anagram indicator lexicon's keys as bare letters (MIXED), for a leaf that gives one."""
    return frozenset(wordplay.letters(k) for k in _indicator_lexicon().get("anagram") or {})


def shared_indicators(tree, clue=None):
    """Indicator words claimed twice: the same text (at the same `at`, or with none) filed on
    two ops, or an indicator whose words are also a leaf's clue words. toughie-3361 12a
    PRAWNCRACKERS: "possibly" is the anagram indicator and again the leaf that gives
    CRACKERS. Leaves in a cryptic definition are the clue, not claims. A word the clue
    itself says twice ("Ruin, ruin") may be both, so it is let go when `clue` is given."""
    flat = wordplay.letters(clue) if clue else ""
    seen, texts, leaves, cut_words, multiword = {}, [], [], set(), []
    said_ind = _anagram_indicator_letters()
    for node in _walk(tree):
        if node.get("op") == "cryptic":
            continue
        for i in node.get("indicators") or []:
            key = (wordplay.letters(i.get("text")), i.get("at"))
            w = key[0].lower()
            if len(str(i.get("text") or "").split()) == 1 and w not in _NOT_COMPOUND and any(
                    len(w) - len(k) >= 3 and (w.startswith(k) or w.endswith(k)) for k in _FOLD_AFFIX.get(node.get("op"), ())):
                cut_words.add(key[0])  # "fightback" = fight + back: the compound is the leaf (FIGHT -> WAR) and its indicator (round 13 RAW)
            if key[0] and flat.count(key[0]) < 2:
                seen[key] = seen.get(key, 0) + 1
                texts.append((key[0], i.get("at"), str(i.get("text") or "").lower().split()))
        if "op" not in node and node.get("words") and "at" not in node:
            leaves.append(wordplay.letters(node["words"]))
            if len(str(node["words"]).split()) >= 2 and len(wordplay.letters(node["words"])) >= 8:
                multiword.append(str(node["words"]).lower().split())
            if node.get("gives") and wordplay.letters(node["gives"]) in said_ind \
                    and re.search(r"\breverse\b|\banswer's\b", str(node.get("note") or ""), re.I):
                cut_words.add(wordplay.letters(node["words"]))  # reverse clue: the words give the indicator word (MIXED)
        if str(node.get("op")).startswith("pal"):
            # a palindrome is its own clue ("rising and falling" REFER, round 10): the indicator
            # words are the leaf's, the one phrase read both ways
            cut_words |= {wordplay.letters(p.get("words")) for p in node.get("parts") or []
                          if isinstance(p, dict) and "op" not in p}
        if node.get("op") in ("deletion", "container", "substitution"):
            # "topless" over [topless]S names what goes; "onboard" over [onboard]SS is the
            # holder and says it holds: the one word is truthfully both
            # only for a short reading of the indicator word itself (SS, S): a synonym the indicator
            # word also gives ([sleeping]BED under ins<sleeping>) is one word doing two jobs
            cut_words |= {wordplay.letters(p.get("words")) for p in (node.get("parts") or [])[1:]
                          if isinstance(p, dict) and "op" not in p}
            if node["op"] == "container":
                cut_words |= {wordplay.letters(p.get("words")) for p in (node.get("parts") or [])[:1]
                              if isinstance(p, dict) and "op" not in p and len(wordplay.letters(p.get("gives"))) <= 2}
                # Withholding = WITH + holding (round 14): the holder is the word's own opening or ending
                cut_words |= {wordplay.letters(p.get("words")) for p in (node.get("parts") or [])[:1]
                              if isinstance(p, dict) and "op" not in p and len(wordplay.letters(p.get("gives"))) >= 3
                              and len(str(p.get("words")).split()) == 1
                              and wordplay.letters(p.get("words")) != wordplay.letters(p.get("gives"))
                              and wordplay.letters(p.get("words")).startswith(wordplay.letters(p.get("gives")))}
        if node.get("op") in ("anagram", "homophone"):
            # Round 17 (4 of 6 sampled sharedIndicator flags judged fine): outpost = out + POST, Twinkletoes =
            # twinkle + TOES (the leaf's word opens or ends with the anagram indicator), and "See" read as the
            # letter C (the sound of a letter's name is its own word, no other indicator to give)
            for p in node.get("parts") or []:
                if not isinstance(p, dict) or "op" in p:
                    continue
                w, g = wordplay.letters(p.get("words")), wordplay.letters(p.get("gives"))
                if node["op"] == "homophone" and len(wordplay.letters(node.get("spelt"))) == 1 \
                        and len(str(p.get("words") or "").split()) == 1:
                    cut_words.add(w)
                elif node["op"] == "anagram" and g and w != g and len(str(p.get("words") or "").split()) == 1 and (
                        (w.endswith(g) and w[:-len(g)] in said_ind) or (w.startswith(g) and w[len(g):] in said_ind)):
                    cut_words.add(w)
        if node.get("op") == "reversal":
            # Return in transport = BUS round GO reversed (round 14, 3 of 6 sampled sharedIndicator flags judged fine):
            # the leaf's words are the reversal's, "go back" read as one phrase; the tree cannot say it shorter
            cut_words |= {wordplay.letters(p.get("words")) for p in node.get("parts") or []
                          if isinstance(p, dict) and "op" not in p}
    n = sum(c - 1 for c in seen.values() if c > 1)
    n += sum(1 for t, at, _ in texts if at is None and t in leaves and t not in cut_words)
    # a leaf's whole multi-word clue words standing inside a longer indicator (azed-1946 17a TURNTURTLE:
    # leaf "This instruction" and the reversal indicator "This instruction makes")
    n += sum(1 for t, at, raw in texts if at is None and t not in cut_words and any(
        re.search(r"(?:^|\s)%s(?:\s|$)" % re.escape(" ".join(l)), " ".join(raw)) and " ".join(l) != " ".join(raw)
        and wordplay.letters(" ".join(l)) not in cut_words for l in multiword))
    return n


def half_leaves(tree):
    """Leaves of one clue word that give exactly its first or last half, with no selection
    op above and no abbreviation saying so: quiptic-1389 22d LION, "only half of" filed on
    live -> LI and again, unmarked, on ones -> ON (one indicator over two words)."""
    pairs, usage = _attested()
    if not usage or not any(re.search(r"\bhalf\b|\bhalves\b|50\s*%|\bhalf-", str(i.get("text") or ""), re.I)
                            for n in _walk(tree) for i in n.get("indicators") or []):
        return 0  # no half indicator in the tree: a short leaf is an abbreviation (STR strait, DOL dollar)
    n = 0
    for leaf, anc in _word_leaves(tree):
        words, gives = wordplay.letters(leaf["words"]), wordplay.letters(leaf["gives"])
        if len(leaf["words"].split()) != 1 or len(words) < 4 or len(gives) * 2 != len(words) \
                or not (words.startswith(gives) or words.endswith(gives)) or leaf.get("select"):
            continue
        if any(a.get("op") in wordplay.SELECT or a.get("op") == "hidden" for a in anc) \
                or _known_pair(leaf["words"], gives):
            continue
        n += 1
    return n


def deletion_scattered(tree):
    """Deletions over a charade whose removed letters (3+) are in no reading a run of the
    charade's letters: they are picked out of several pieces at once (everyman-3903 6d
    TOLKIEN, "Not half" taking MANLITS across Tolman, Kili and Ents). One "half" acts on
    one piece; the evaluator removes the letters from anywhere, so it passes."""
    n = 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "deletion" or node.get("unchecked") or len(parts) != 2 \
                or not all(isinstance(p, dict) for p in parts) or parts[0].get("op") != "charade" \
                or len(parts[0].get("parts") or []) < 2:
            continue
        text = " ".join(str(i.get("text") or "") for i in node.get("indicators") or [])
        if parts[1].get("words") and "op" not in parts[1] and len(wordplay.letters(parts[1]["words"])) >= 4 \
                and wordplay.letters(parts[1].get("gives")) == wordplay.letters(parts[1]["words"]) \
                and not parts[1].get("unchecked"):
            # a whole clue word taken out of a charade it is not a run of (azed-2427 7d STANCES:
            # MOST+ANCESTORS less MOTORS "around" is MO(STANCES)TORS, a container, round 12)
            try:
                wholes, cuts = wordplay.values(parts[0]), wordplay.values(parts[1])
            except Exception:
                continue
            n += bool(wholes and cuts and not any(r in f for f in wholes for r in cuts))
            continue
        if parts[1].get("words") or not re.search(r"\bhalf\b|\bhalves\b|50\s*%|\bhalf-", text, re.I):
            continue  # only the "half" form is measured: "lacking leaders" over each word is told true
        try:
            wholes, cuts = wordplay.values(parts[0]), wordplay.values(parts[1])
        except Exception:
            continue
        if wholes and cuts and all(len(r) >= 3 for r in cuts) and not any(r in f for f in wholes for r in cuts):
            n += 1
    return n


def reverse_phrase(tree):
    """A reverse (self-referential) reading over 3+ clue words: the wordplay is the answer
    read as an instruction on the whole phrase, which a solver cannot check or follow
    (sundaytimes-5086 12a ROUGHHEWN, quiptic-1146 20d LINEDUP). A phrase that says "this" points
    at the answer and is the Azed form ("This could make pals" SLAPUP), so it is left."""
    return sum(1 for n in _walk(tree) if n.get("op") == "reverse" and not n.get("unchecked")
               and any(len(str(p.get("words") or "").split()) >= 3 and not re.search(r"\bthis\b", str(p["words"]), re.I)
                       and not _reading_reuses_words(n, p)
                       for p in n.get("parts") or [] if isinstance(p, dict)))


def _reading_reuses_words(node, leaf):
    """Whether a word of the reverse reading (3+ letters) is an anagram of the last 1-4 words of the
    leaf (round 15, 3 of 4 reversePhrase flags judged fine: NATE for "neat", STEP for "pets", POTATOES
    for "to a poet's"): the answer then tells how the clue words were made, which a solver can check."""
    words = re.findall(r"[A-Za-z']+", str(leaf.get("words") or ""))
    runs = {"".join(sorted(wordplay.letters("".join(words[len(words) - k:])))) for k in (1, 2, 3, 4)
            if k <= len(words)}  # the end of the phrase, as in "What makes pets" (ROUGH + HEWN fails on "When")
    return any(len(w) >= 3 and "".join(sorted(w.upper())) in runs
               for w in re.findall(r"[A-Za-z]+", str(node.get("reading") or "")))


#: The ops a single indicator word signals one of: one indicator per op (Paul, 10-18: "Beginning is
#: one indicator and end is another"). Two indicators on one of these is two ops filed as one.
_ONE_IND_OPS = frozenset({"reversal", "deletion", "hidden"}) | frozenset(wordplay.SELECT)
DELETION_SCOPE_ANSWER = "deletion over a charade whose indicator names an end, but the letters that make the answer are not at it"
DOUBLE_INDICATOR = "one op carries two indicators, or stacks two ops on one"
MOVED_LETTER = "a letter taken out by a deletion and put back by a sibling leaf is a move, not an add-then-delete"


def moved_letters(tree):
    """Deletions whose removed letters a sibling leaf of the same parent gives again (Paul, round 15:
    ALBINO = del<dropping>(ALBION, O) + [ball]O is an error; the tree is move<dropping>(ALBION, O)).
    Counts a deletion once per tree place; a removed part that is a leaf with letters, a sibling that is
    a leaf with the same letters."""
    n = 0
    for parent in _walk(tree):
        kids = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        for d in kids:
            ps = [p for p in d.get("parts") or [] if isinstance(p, dict)]
            if d.get("op") != "deletion" or d.get("unchecked") or len(ps) != 2 or "op" in ps[1]:
                continue
            cut = wordplay.letters(ps[1].get("gives"))
            # A plain truncation beside a leaf of the same letter is a coincidence, as in
            # _sibling_gives (cryptic-30087 11a: [Old]O + ... + del<without finishing>([too]ALSO, O)).
            n += bool(cut) and ((not _plain_cut(d) and any(
                "op" not in k and k is not d and wordplay.letters(k.get("gives")) == cut
                for k in kids)) or bool(_sibling_gives(kids, d, ps[1])))
        n += _leaf_cut_put_back(kids)
    return n


def _plain_cut(d):
    """Whether the deletion `d`'s indicator is a plain truncation (endless, without finishing)."""
    said = " ".join(str(i.get("text") or "") for i in d.get("indicators") or [] if isinstance(i, dict))
    return bool(_DEL_END.search(said) or _DEL_HEAD.search(said)
                or re.search(r"\b(?:losing|largely|mostly|made|less)\b", said, re.I))


def _sibling_gives(kids, d, cut_part):
    """1 when a sibling first/last pick gives the letters the deletion `d` removes (r30 FN SHAH:
    del<advancing>(HASH, S) beside last<finally>(enemies)): the same move, one letter taken out and put back."""
    if _plain_cut(d):
        return 0  # r31 judged: a plain truncation indicator beside a pick of the same letter is a coincidence (9 of 40 fine)
    try:
        cut = wordplay.values(cut_part)
        return int(any(k.get("op") in ("first", "last", "nth") and not k.get("unchecked") and wordplay.values(k) & cut
                       for k in kids if k is not d))
    except Exception:
        return 0


_LEAF_CUT_NOTE = re.compile(r"\b(?:without|minus|losing|lacking|dropping|missing)\b", re.I)


def _leaf_cut_put_back(kids):
    """1 when a leaf's note says its word is a longer one without a letter (EDGE, "LEDGE ... without its front
    letter") and a sibling leaf gives that letter again (L; r30 FN EDGETOOL): a move, not a cut and an add."""
    for a in kids:
        if "op" in a or a.get("unchecked") or not _LEAF_CUT_NOTE.search(str(a.get("note") or "")):
            continue
        g = wordplay.letters(a.get("gives"))
        for w in re.findall(r"\b[A-Z]{3,}\b", str(a.get("note"))):
            gone = [wordplay.letters(b.get("gives")) for b in kids if b is not a and "op" not in b]
            if len(w) == len(g) + 1 and any(len(x) == 1 and sorted(w) == sorted(g + x) for x in gone if x):
                return 1
    return 0


def _ind_adjacent(a, b):
    """Whether two indicators with known places touch in the clue: the two halves of one phrase."""
    if not all(isinstance(i.get("at"), int) for i in (a, b)):
        return False
    lo, hi = sorted((a, b), key=lambda i: i["at"])
    return 0 <= hi["at"] - (lo["at"] + len(str(lo.get("text") or ""))) <= 1


_OWN_DELETION_WORD = re.compile(r"\w+less\b|\b(without|minus|lacking|dropping|losing|missing)\b", re.I)


def _own_word(op, text):
    """Whether indicator `text` is, on its own, a word of `op`'s type: the corpus files it there
    in at least half of 5+ uses, or (a deletion) it says "-less"/"without". The two halves of one
    phrase around the fodder (Bring ... back, Half of ... is forgotten, less ... on top) are not:
    one half is a selection's or a bare verb, so two own words are two ops."""
    counts = _role_counts(indicator_role_key(text))
    total = sum(counts.values())
    if total >= 5:
        return counts.get(_OP_LEXICON[op], 0) >= 0.5 * total
    return op == "deletion" and bool(_OWN_DELETION_WORD.search(str(text or "").lstrip("'\u2019")))


def _owner_type(text):
    """The op type the corpus files indicator `text` under in 80%+ of 5+ uses, else None."""
    counts = _role_counts(indicator_role_key(text))
    total = sum(counts.values())
    top = max(counts, key=counts.get) if counts else None
    return top if total >= 5 and counts[top] >= 0.8 * total else None


TRADED_INDICATOR = "two ops each carry the other's indicator word, or a hidden word carries a reversal's word"


def traded_indicators(tree):
    """Indicators that trade places (round 19, listed miss REALALES: rev<about>(ins<knocking back>), where
    "about" is 78% container and "knocking back" 91% reversal; ADORE: rev<masks>(hid<up>), "up" being 93%
    reversal and a hidden word's indicator under 1%). Counts the indicators of a checked op whose word the
    corpus files, in 20+ uses, 75%+ under another op's type and at most 20% under this one's, when a second op
    carries the first's type's word the same way; or, for a hidden word
    carrying a near-reversal word (90%+, under 2% hidden), when the tree's reversal has no indicator the
    corpus knows for a reversal."""
    nodes = [n for n in _walk(tree) if _OP_LEXICON.get(n.get("op")) and not n.get("unchecked") and n.get("indicators")]
    found = []  # (node id, own type, other type, strict)
    for node in nodes:
        own = _OP_LEXICON[node["op"]]
        for i in node["indicators"]:
            counts = _role_counts(indicator_role_key(i.get("text")))
            total = sum(counts.values())
            if total < ROLE_MIN_USES:
                continue
            top = max(counts, key=counts.get)
            if top == own:
                continue
            if counts[top] >= 0.75 * total and counts.get(own, 0) <= 0.2 * total:
                found.append((id(node), own, top, False))
            if counts[top] >= 0.9 * total and counts.get(own, 0) <= 0.02 * total:
                found.append((id(node), own, top, True))
    mutual = {a for a in found if any(b[0] != a[0] and b[1] == a[2] and b[2] == a[1] for b in found)}
    hid = {a for a in found if a[3] and a[1] == "hidden_word" and a[2] == "reversal" and any(
        _OP_LEXICON[o["op"]] == "reversal" and _lacks_role(o, "reversal") for o in nodes)}
    return len({(a[0], a[1]) for a in mutual | hid})


def double_indicators(tree):
    """Reversals, deletions, hidden words and selections that file two indicators (cryptic-29317
    6d NEEDIER rev<turned up><elevated>: two reversals; independent-12251 2d IRON
    del<'eadless><without an aitch>: two deletions), and a hidden word over a selection that has no
    indicator of its own (times-16960 6d EARL hid<inside>(mid(pearly)): one word, two ops). Two
    indicators that touch in the clue are one phrase cut in two and are left."""
    n = 0
    for node in _walk(tree):
        op = node.get("op")
        if op not in _ONE_IND_OPS:
            continue
        ins = [i for i in node.get("indicators") or [] if isinstance(i, dict)]
        if len(ins) >= 2 and not all(_ind_adjacent(ins[k], ins[k + 1]) for k in range(len(ins) - 1)) \
                and sum(_own_word(op, i.get("text")) for i in ins) >= 2:
            n += 1
        elif op == "hidden" and not ins:
            continue
        elif op == "hidden" and any(isinstance(p, dict) and p.get("op") in wordplay.SELECT
                                    and not p.get("indicators") for p in node.get("parts") or []):
            n += 1
    return n


def _subtree_spans(node, clue, low):
    """[(start, end)] of every leaf and indicator under `node`, by its `at` or else where its words
    first occur in the clue; a piece the clue does not show is left out."""
    out = []
    for m in _walk(node):
        items = [(m.get("words"), m.get("at"))] if "words" in m else []
        items += [(i.get("text"), i.get("at")) for i in m.get("indicators") or [] if isinstance(i, dict)]
        for text, at in items:
            text = str(text or "")
            if not text:
                continue
            at = at if isinstance(at, int) else low.find(text.lower())
            if at >= 0:
                out.append((at, at + len(text)))
    return out


POOL_GAP = "anagram fodder with another op's words between its pieces"


def pool_gaps(tree, clue):
    """Anagrams of 2+ fodder pieces with a leaf or indicator of some other op sitting in the clue
    between the pieces: the pool is read off words the anagram does not gather (ftcryptic-18053 2d
    AMERICANPIE ana<tangled>(in camera, P): "pressure" is far past "that is opened by", and P goes
    before IE; cryptic-29127 27a, cyclops-409 12a). The anagram's own indicator may stand between."""
    if not clue:
        return 0
    low = clue.lower()
    try:    # stored trees carry no offsets: place every span as view() does, or "a" is found inside "Jars"
        tree = wordplay.locate(copy.deepcopy(tree), clue)
    except Exception:
        pass
    n = 0
    for node in _walk(tree):
        parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "anagram" or len(parts) < 2 or node.get("unchecked"):
            continue
        spans = [_subtree_spans(p, clue, low) for p in parts]
        spans = [(min(a for a, _ in s), max(b for _, b in s)) for s in spans if s]
        if len(spans) < 2:
            continue
        lo, hi = min(a for a, _ in spans), max(b for _, b in spans)
        mine = {id(m) for m in _walk(node)}
        gap = False
        for m in _walk(tree):
            if id(m) in mine:
                continue
            if "op" in m and any(q is node for q in _walk(m)):
                continue  # round 17, kept in 18: an enclosing op's indicator ("keeps ... in", "when framing") may stand between the pieces
            for x, y in _subtree_spans({"words": m["words"], "at": m.get("at")} if "words" in m and "op" not in m
                                       else {"indicators": m.get("indicators")}, clue, low):
                if lo < x and y < hi and not any(a <= x and y <= b for a, b in spans):
                    gap = True
        n += gap
    return n


def _located(tree, clue):
    """`tree` with every span placed in `clue` (a stored tree carries no offsets); as filed on a failure."""
    try:
        return wordplay.locate(copy.deepcopy(tree), clue)
    except Exception:
        return tree


def _extent(node, clue, low):
    """(start, end) of everything under `node` in the clue, or None when the clue shows none of it."""
    spans = _subtree_spans(node, clue, low)
    return (min(a for a, _ in spans), max(b for _, b in spans)) if spans else None


CHARADE_ORDER = "charade whose pieces sit in the clue in another order than it joins them"
#: Words that let a charade's pieces come out in a different order than the clue gives them.
ORDER_FLIPPERS = re.compile(
    r"\b(after|before|behind|following|follows?|followers?|followed|below|beneath|under|above|atop|ahead|preceding|"
    r"precedes|preceded|leading|leads?|leaders?|goes|going|put|puts|coming|comes?|by|in|inside|within|provided|"
    r"to the|at the end|at end|end of|start of|on|over|supporting|heading|heads|tops|capping|beyond|past|"
    r"at the back|at the front|then|next|and then|finally|ending|finishing|starting|opening)\b", re.I)


def charade_out_of_order(tree, clue):
    """Charades with no indicator whose pieces are joined in another order than the clue gives them,
    and no word between them to say so (ftcryptic DODGE "Duke flipped for one party": DO + D + EG
    reversed, where the clue's order is D, EG, DO; SPIRE, PARADIDDLE). Round 22: 6 of 38 judged misses."""
    if not clue:
        return 0
    low = clue.lower()
    tree = _located(tree, clue)
    n = 0
    for node in _walk(tree):
        if node.get("op") != "charade" or node.get("indicators"):
            continue
        spans = [s for p in node.get("parts") or [] if isinstance(p, dict) and (s := _extent(p, clue, low))]
        if len(spans) < 2 or all(spans[i + 1][0] >= spans[i][0] for i in range(len(spans) - 1)):
            continue
        if not ORDER_FLIPPERS.search(clue[min(a for a, _ in spans):max(b for _, b in spans)]):
            n += 1
    return n


REVERSAL_SPLIT = "reversal whose indicator sits between two of the pieces it reverses"


def reversal_split(tree, clue):
    """Reversals over several pieces with their indicator word standing between those pieces in the clue:
    the indicator acts on the piece beside it (mephisto DEGAS "editor repelled with flatulence" reverses
    ED alone; LILAC, NOTHALF, ELAPSES). Round 22: 5 of 38 judged misses."""
    if not clue:
        return 0
    low = clue.lower()
    tree = _located(tree, clue)
    n = 0
    for node in _walk(tree):
        if node.get("op") != "reversal" or node.get("unchecked"):
            continue
        if any(m.get("op") in ("hidden", "alternate", "deletion") for m in _walk(node) if m is not node):
            continue  # round 22c: 12 of 14 judged-fine hits reversed a hidden, alternate-letters or deletion result, one stretch of the clue
        kids = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if len(kids) == 1 and (kids[0].get("op") in wordplay.SELECT or kids[0].get("op") == "substitution"):
            continue  # r42 judged: a reversal of one pick or substitution (rev<up>(middle<>(Bottoms))) is one piece, 2 of 4 fine, 0 of 38 errors
        spans = [s for p in node.get("parts") or [] if isinstance(p, dict) and (s := _extent(p, clue, low))]
        if not spans:
            continue
        lo, hi = min(a for a, _ in spans), max(b for _, b in spans)
        for ind in node.get("indicators") or []:
            text = str(ind.get("text") or "") if isinstance(ind, dict) else ""
            at = ind.get("at") if isinstance(ind.get("at"), int) else low.find(text.lower())
            if text and at >= 0 and lo < at and at + len(text) < hi:
                n += 1
                break
    return n


CUT_IN_LEAF = "leaf opens with a cut word (short, half, first) and gives fewer letters than its other words"
CUT_WORDS = frozenset("short shorter shortly half briefly brief first last lower upper heart centre initially ends "
                      "endless headless topless beheaded curtailed cut clipped docked reduced".split())


CUT_SUFFIXED = frozenset("endless headless topless beheaded curtailed cut clipped docked reduced".split())


def _cut_phrase(words):
    """Whether a leaf's opening words say a cut rather than name a thing: a cut word followed by "of"
    ("half of", "first part of"), a "-less"/clipped word, or "half" that is no half-dozen."""
    for i, w in enumerate(words[:2]):
        if w not in CUT_WORDS:
            continue
        if w in CUT_SUFFIXED or "of" in words[i + 1:i + 4]:
            return True
        if w == "half" and "dozen" not in words and words[i + 1:i + 2] != ["a"]:
            return True
    return False


def cut_in_leaf(tree, clue=None):
    """Leaves whose first words are a cut indicator ("short contract" giving DEA, "your lower half" giving UR,
    "First of branches" giving BRANCHES) that give fewer letters than the words after it: the cut is an op.
    Round 22: 3 of 38 judged misses."""
    n = 0
    for node in _walk(tree):
        if "words" not in node or "op" in node or node.get("unchecked") or not node.get("gives"):
            continue
        words = re.findall(r"[a-z']+", str(node["words"]).lower())
        if len(words) < 2 or words[0] not in CUT_WORDS | {"your", "a", "the"} or not any(w in CUT_WORDS for w in words[:2]):
            continue
        if not _cut_phrase(words):
            continue  # round 22c: "short film", "last month", "half-dozen" are synonyms (14 of 40 judged hits fine); "half of", "endless", "first part of" are cuts
        if len(re.sub(r"[^A-Z]", "", str(node["gives"]))) < sum(len(w) for w in words[1:]):
            n += 1
    return n


ANA_SELECT_EDGE = "anagram holds a first/last-letter pick at the edge of its fodder that the answer shows outside the scramble"
NON_WORD_OPERAND = "deletion, substitution or homophone acts on a leaf that is no word"
DEL_WIDE = "deletion lists several pieces before its indicator, so it cuts one piece, not the whole group"
IND_LEAF_OVERLAP = "indicator phrase takes a word that a leaf also gives"
ANA_DOUBLE_IND = "anagram carries two separate indicators"
DEL_STRADDLE = "deletion over a charade removes letters from across two of its pieces"


def _stand_in_or_select(p):
    """An anagram fodder piece that is a stand-in or a first/last-letter pick."""
    return (p.get("op") in wordplay.SELECT and not p.get("unchecked")) or _stand_in_piece(p)


def ana_select_edge(tree, answer=None):
    """Anagrams whose edge fodder is a letter pick (first(x), last(x)) that stays outside the scramble in the
    answer (r23 FN: GLEAM = G + ana(MALE), BRUSCHETTA = ana(SCHUBERT + T) + A). Counts only what the
    stand-in check (anaCharade) does not already count."""
    base = max(0, anagram_edge_pieces(tree, answer, _stand_in_or_select) - anagram_edge_pieces(tree, answer))
    return base or _select_edge_swapped(tree, answer)


def _select_edge_swapped(tree, answer):
    """1 when an anagram's one letter pick, first or last in the fodder, stands at the OTHER end of the
    answer once taken out (r23 FN GLEAM: ana<breaks>(Male, first<head>(gymnast's)) is G + ana(MALE))."""
    if not answer or not isinstance(tree, dict):
        return 0
    try:
        wordplay.evaluate(copy.deepcopy(tree), answer)
    except Exception:
        return 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "anagram" or node.get("unchecked") or len(parts) < 2 \
                or not all(isinstance(p, dict) for p in parts):
            continue
        for idx in (0, len(parts) - 1):
            if parts[idx].get("op") not in wordplay.SELECT or parts[idx].get("unchecked") \
                    or any(q.get("op") in wordplay.SELECT for k, q in enumerate(parts) if k != idx):
                continue
            for front in (True, False):
                t = copy.deepcopy(tree)
                for cur in _walk(t):
                    if cur.get("op") == "anagram" and cur.get("parts") == node.get("parts") \
                            and cur.get("indicators") == node.get("indicators"):
                        piece = cur["parts"].pop(idx)
                        mid = {k: v for k, v in cur.items()}
                        cur.clear()
                        cur.update({"op": "charade", "parts": [piece, mid] if front else [mid, piece]})
                        break
                try:
                    wordplay.evaluate(t, answer)
                    return 1
                except Exception:
                    pass
    return 0


def del_straddle(tree):
    """Deletions over a charade of lettered leaves whose removed letters run across a piece boundary at the
    charade's start or end (r23 FN PAPA: del<briefly>(PAPARAZZO + a, RAZZOA); ORKNEY del<Ignore>(W + WORK, WW)):
    the word cuts one piece, so the cut belongs inside the charade."""
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "deletion" or len(ps) != 2 or ps[0].get("op") != "charade" or "op" in ps[1] \
                or ps[1].get("words") or not ps[1].get("gives"):
            continue
        pcs = [p for p in ps[0].get("parts") or [] if isinstance(p, dict)]
        if len(pcs) < 2 or any("op" in p for p in pcs):
            continue
        gs = [wordplay.letters(p.get("gives") if p.get("gives") else p.get("words")) for p in pcs]
        cut, full = wordplay.letters(ps[1]["gives"]), "".join(gs)
        if cut and ((full.endswith(cut) and len(cut) > len(gs[-1]) and full != cut)
                    or (full.startswith(cut) and len(cut) > len(gs[0]) and full != cut)):
            n += 1
    return n


def non_word_operands(tree):
    """Deletions, substitutions and homophones whose operand leaf gives letters that are no word and no
    attested pair (r23 FN: sub(OXCOW), del(DICKEYE), sound(BOYCOT): two synonyms run together in one leaf,
    so the cut or the sound acts on one of them). Needs the lexicon."""
    lex = _lexicon_letters()
    if not lex:
        return 0
    n = 0
    for node in _walk(tree):
        if node.get("op") not in ("deletion", "substitution", "homophone"):
            continue
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        for p in ps[:1] if node["op"] != "homophone" else ps:
            g = wordplay.letters(p.get("gives")).lower()
            if "op" in p or not p.get("words") or p.get("unchecked") or len(g) < 5 or g in lex \
                    or p.get("select") or p.get("soundsLike") or re.search(r"\d", str(p["words"])):
                continue
            if not _known_pair(p["words"], wordplay.letters(p["gives"])):
                n += 1
    return n


def del_wide(tree, clue):
    """Deletions of 3+ parts whose indicator stands in the clue after two or more of their parts: the word
    cuts the one piece next to it, and the earlier pieces are the parent's (r23 FN MOUSETRAP
    ana<Spread>(del<lacking>(out, Parmesan, an)): OUT is no part of the cut)."""
    if not clue:
        return 0
    low = clue.lower()
    try:
        tree = wordplay.locate(copy.deepcopy(tree), clue)
    except Exception:
        pass
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "deletion" or len(ps) < 3:
            continue
        inds = [i for i in node.get("indicators") or [] if isinstance(i, dict) and str(i.get("text") or "")]
        if len(inds) != 1:
            continue
        t = str(inds[0]["text"])
        at = inds[0]["at"] if isinstance(inds[0].get("at"), int) else low.find(t.lower())
        spans = [(min(a for a, _ in s), max(b for _, b in s)) for s in (_subtree_spans(p, clue, low) for p in ps) if s]
        if at >= 0 and len(spans) == len(ps) and sum(b <= at for _, b in spans) >= 2:
            n += 1
    return n


def ind_leaf_overlap(tree, clue=None):
    """A multi-word indicator one of whose words is also a whole leaf (r23 FN STOIC ana<is broken>(cot, is)):
    the clue word serves as fodder and as indicator. Counted by occurrence when the clue is known."""
    nodes = list(_walk(tree))
    leafwords = collections.Counter(w for n in nodes if "op" not in n and n.get("words")
                                    for w in [wordplay.letters(n["words"])] if len(w) >= 2 and " " not in str(n["words"]).strip())
    said = collections.Counter(wordplay.letters(x) for x in (clue or "").split())
    n = 0
    for node in nodes:
        for i in node.get("indicators") or []:
            ws = [wordplay.letters(x) for x in str(i.get("text") or "").split()]
            if len(ws) != 2:
                continue  # longer phrases ("requiring electronic input") leave a gap the leaf may fill: 6 of 10 fine hits
            for w in set(ws):
                if w in leafwords and (not clue or said[w] < 2) and w not in ("a", "an", "the", "of", "to", "in", "it"):
                    n += 1
    return n


SWAPPED_PAIR = "a parent op and its child op carry each other's indicator words"
LINK_IN_LEAF = "leaf opens or closes with a link word and gives what the other words alone give"
_LEAF_LINKS = frozenset("in of to for with and at on by from into".split())
ANA_STAND_IN = "anagram scrambles an abbreviation or synonym beside the clue's own words"


def _role_share(text, op):
    """(share of the corpus's uses of indicator `text` filed under `op`'s type, total uses)."""
    counts = _role_counts(indicator_role_key(text))
    total = sum(counts.values())
    return (counts.get(_OP_LEXICON.get(op), 0) / total if total else 0.0), total


def swapped_pair(tree):
    """A parent op and a direct child op of another type whose indicators are swapped: the parent's word
    is almost never filed under its type but is the child's type's word at least 15% of the time, and the
    child's word is the parent's type's (r23 FN DATIVE ins<twists>(DATE, rev<in>(VI)))."""
    n = 0
    for p in _walk(tree):
        if p.get("op") not in _OP_LEXICON or p.get("unchecked"):
            continue
        for c in p.get("parts") or []:
            if not isinstance(c, dict) or c.get("op") not in _OP_LEXICON or c.get("op") == p["op"] or c.get("unchecked"):
                continue
            pi = [i.get("text") for i in p.get("indicators") or [] if isinstance(i, dict) and i.get("text")]
            ci = [i.get("text") for i in c.get("indicators") or [] if isinstance(i, dict) and i.get("text")]
            if not pi or not ci:
                continue
            ok = all(_role_share(t, p["op"])[0] < 0.05 and _role_share(t, p["op"])[1] >= 10
                     and _role_share(t, c["op"])[0] >= 0.15 for t in pi) \
                and all(_role_share(t, c["op"])[0] < 0.05 and _role_share(t, c["op"])[1] >= 20
                        and _role_share(t, p["op"])[0] >= 0.5 for t in ci)
            n += ok
    return n


def link_in_leaf(tree):
    """Leaves whose first or last clue word is a link word (in, of, to, with ...) when the remaining words
    alone are a known pair for the same letters and the whole phrase is not (r23 FN SWAMI
    [in Southwest]SW): the link word is the clue's join, not part of the leaf."""
    n = 0
    for node in _walk(tree):
        ws = str(node.get("words") or "").split()
        if "op" in node or len(ws) < 2 or not node.get("gives") or node.get("select") or node.get("soundsLike"):
            continue
        g = wordplay.letters(node["gives"])
        if _known_pair(node["words"], g):
            continue
        for lead, rest, link in ((True, ws[1:], ws[0]), (False, ws[:-1], ws[-1])):
            # a leading "to" is the infinitive of a verb leaf ("to shred" RIP, "to throw" SHY): 11 of 12 such hits were fine
            if wordplay.letters(link).lower() in _LEAF_LINKS and not (lead and link.lower() == "to") \
                    and _known_pair(" ".join(rest), g):
                n += 1
                break
    return n


def _initial_abbreviation(p):
    """A leaf giving one or two letters that start its words (R for right, N for new, CC for twice caught):
    the standard abbreviation mid-answer is genuine fodder (r26: 5 of 5 such anaStandIn hits fine, 0 of 4 others)."""
    g = wordplay.letters(p.get("gives"))
    initials = {x[0] for x in re.findall(r"[a-z]+", (p.get("words") or "").lower())}
    return bool(g) and len(g) <= 2 and g[0].lower() in initials


def ana_stand_in(tree):
    """Anagrams whose fodder mixes the clue's own words with a stand-in (abbreviation or synonym) leaf
    (r23 FN POLICYMAKERS ana<broadcast>(K, ER, Olympics)): the stand-in is spelled into the answer, not
    scrambled with the rest."""
    n = 0
    for outer in _walk(tree):
        if outer.get("op") != "container":
            continue  # only the anagram held by a container: judged, 11 of 11 such hits wrong; elsewhere 19 of 29 were fine (a mid-answer letter is fodder)
        for node in (p for p in outer.get("parts") or [] if isinstance(p, dict)):
            parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
            if node.get("op") != "anagram" or node.get("unchecked") or len(parts) < 2:
                continue
            st = [_stand_in_piece(p) and not p.get("select") and not _initial_abbreviation(p) for p in parts]
            n += any(st) and not all(st) and any("op" not in p and not s for p, s in zip(parts, st))
    return n


SELECT_WORD_IN_LEAF = "selection op whose leaf opens with the op's own indicator words"
SELECT_PHRASE_IN_LEAF = "leaf opens with a letter-selection phrase and gives fewer letters than its other words"
HALVED_AS_DELETION ="halving ('half of', '50 per cent', 'bottom half') written as a plain deletion"
SPLIT_SHARED_INDICATOR = "one indicator over two neighbouring same-kind ops, only one of them carrying it"
_NOT_A_HALVING = re.compile(r"hearted|more than half|almost half", re.I)
_HALVING =re.compile(r"\bhalf\b|\bsemi\b|\b\d{1,2}\s*(?:per\s*cent|%|percent)", re.I)  # any percentage: r36 FN "60% of", "about 57%"


def select_word_in_leaf(tree):
    """Selection ops (first, last, outer, middle ...) whose direct leaf opens with the op's own indicator
    words and holds more ("bit of breakfast" under first<bit of>, "end for beggar" under last<end for>,
    r26 FN: 3 misses): the leaf holds only the words that give its letters."""
    n = 0
    for node in _walk(tree):
        if node.get("op") not in wordplay.SELECT or node.get("unchecked"):
            continue
        inds = [re.findall(r"[a-z']+", str(i.get("text") or "").lower()) for i in node.get("indicators") or [] if isinstance(i, dict)]
        for p in (q for q in node.get("parts") or [] if isinstance(q, dict) and "op" not in q):
            words = re.findall(r"[a-z']+", str(p.get("words") or "").lower())
            n += any(iw and len(words) > len(iw) and words[:len(iw)] == iw for iw in inds)
    return n


def select_phrase_in_leaf(tree):
    """Leaves of 2+ words that open with a selection indicator phrase the corpus files under letter
    selection ("borders of scarlet" giving ST, "Heading off trouble" giving OTHER; r26 FN: 3 misses) and give
    fewer letters than the words after it: the selection is an op. cut_in_leaf takes the cut words."""
    n = 0
    for node in _walk(tree):
        if "op" in node or node.get("unchecked") or not node.get("gives") or not node.get("words"):
            continue
        words = re.findall(r"[a-z']+", str(node["words"]).lower())
        gives = len(re.sub(r"[^A-Z]", "", str(node["gives"])))
        for k in (1, 2, 3):
            rest = sum(len(w) for w in words[k:])
            if len(words) > k and gives < rest and _owner_type(" ".join(words[:k])) == "letter_selection" \
                    and words[0] not in CUT_WORDS:
                n += 1
                break
    return n


SELECTOR_AS_CUT = "deletion removes a leaf made of a first/last-letter word (leader, City's first), not a first/last pick"


def selector_as_cut(tree):
    """Deletions whose removed leaf is a selection word alone or closing a longer phrase ("leader" giving P,
    "City's first" giving C; r30 FN: 2 misses): the removed letter is a first/last pick with its own
    indicator, del(PACE, first<leader>(...)) -- the leaf holds only the words that give its letters."""
    n = 0
    for node in _walk(tree):
        if node.get("op") != "deletion" or node.get("unchecked"):
            continue
        for p in (q for q in (node.get("parts") or [])[1:] if isinstance(q, dict) and "op" not in q and q.get("gives")):
            words = re.findall(r"[a-z']+", str(p.get("words") or "").lower())
            gives = len(re.sub(r"[^A-Z]", "", str(p["gives"])))
            if {"second", "initials"} & set(words):
                continue  # r31 judged: "second" is the abbreviation S (6 of 9 fine hits)
            if words and gives <= 2 and (
                    (len(words) == 1 and _owner_type(words[0]) == "letter_selection") or
                    (len(words) > 1 and _owner_type(words[-1]) == "letter_selection"
                     and gives < sum(len(w) for w in words[:-1]))):
                n += 1
    return n


def halved_as_deletion(tree):
    """Deletions whose indicator says half ("half of", "50 per cent", "bottom half removed",
    "half-forgotten"; r26 FN: 5 misses): the word keeps half its letters, a halving selection, not a
    deletion of the other half. Not "half-hearted" (one of a doubled heart letter dropped: SOBBER to SOBER,
    7 of 9 fine r28 hits) nor "more than half" / "almost half" (not an exact half)."""
    return sum(1 for node in _walk(tree) if node.get("op") == "deletion" and not node.get("unchecked")
               and any(_HALVING.search(t) and not _NOT_A_HALVING.search(t)
                       for t in (str(i.get("text") or "") for i in node.get("indicators") or [] if isinstance(i, dict))))


TRIM_AS_SELECTION = ("first/last/middle pick of 2+ letters from a synonym, not the clue's own words, "
                     "written as a selection (a trim of a word the clue does not print is a deletion)")


def trims_as_selection(tree, answer):
    """Selections (first, last, middle) over one leaf whose letters are a synonym rather than the clue's
    own words, keeping 2+ letters but not all (cryptic-30087 17a: middle<without limits>([jumps]BOUNCES)
    for OUNCE). The family rung says a selection's letters sit in the clue, and these do not: the word is
    trimmed, del<without limits>([jumps]BOUNCES, B, S), the way 35k other trims of a synonym are filed.
    Not a halving (halved_as_deletion keeps those as selections), a single-letter pick (the first letter
    of a synonym), nor a pick a deletion takes out (its letters are the cut, not a word kept)."""
    if not tree or not answer:
        return 0
    try:
        got = wordplay.evaluate(tree, answer)
    except wordplay.WordplayError:
        return 0
    n = 0

    def walk(node, cut):
        nonlocal n
        if not isinstance(node, dict):
            return
        parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if not cut and node.get("op") in ("first", "last", "middle") and not node.get("unchecked") \
                and len(parts) == 1 and "op" not in parts[0] and parts[0].get("gives") \
                and not parts[0].get("select") and not parts[0].get("unchecked"):
            leaf, said = parts[0], [str(i.get("text") or "") for i in node.get("indicators") or [] if isinstance(i, dict)]
            whole, words = wordplay.letters(leaf["gives"]), str(leaf.get("words") or "")
            pick = got.get(id(node)) or ""
            n += (whole not in (wordplay.letters(words), wordplay.letters(re.sub(r"['’]s\b", "", words)))
                  and 2 <= len(pick) < len(whole)
                  and not any(_HALVING.search(t) and not _NOT_A_HALVING.search(t) for t in said))
        for k, p in enumerate(parts):
            walk(p, cut or (k > 0 and node.get("op") in ("deletion", "substitution", "move")))
    walk(tree, False)
    return n


def split_shared_indicators(tree):
    """Two neighbouring same-kind ops (deletion, homophone, a selection) under one parent where only one
    carries an indicator (r26 FN: "finishes off" over CHAD and BLISS, "leaders must leave" over Told that):
    one indicator, one multi-part op."""
    n = 0
    for parent in _walk(tree):
        groups = {}
        for p in (q for q in parent.get("parts") or [] if isinstance(q, dict)):
            if p.get("op") in _SHARED_OK and not p.get("unchecked"):
                groups.setdefault(p["op"], []).append(p)
        for ns in groups.values():
            n += len(ns) == 2 and sum(bool(x.get("indicators")) for x in ns) == 1 and _pair_adjacent(ns)
            n += len(ns) >= 3 and sum(bool(x.get("indicators")) for x in ns) == 1  # r40 FN NUMEROUNO: one "never-endingly" over four deletions
    return n


TRUNC_IN_LEAF = "leaf holds a truncation word (mostly, almost, cut short) and gives a word one letter short"
CUT_NOTE_LEAF = "leaf gives a non-word that its note says is a real word with letters cut, and no deletion op shows the cut"
OWN_IND_IN_LEAF = "op's own indicator words also sit inside its leaf (at the end, or the start of a non-selection)"
#: "briefly" and "concise" are left out: they are the abbreviation convention (Science briefly = SCI; 6 of 6 judged fine).
_TRUNC_WORDS = frozenset("mostly almost nearly largely curtailed endlessly practically virtually partly "
                         "shortened contracted abbreviated truncated clipped skimmed trimmed docked beheaded "
                         "decapitated topped tailed".split())
#: "briefly" counts only when the leaf's own note says a word was shortened ("RAVE, shortened"), r30 FN.
_BRIEFLY_CUT = re.compile(r"\b(?:shortened|clipped|without|loses|lost|drop\w*|truncated|last letter)\b", re.I)
#: r32 FN: a leaf ULE whose note says "YULE with its first letter removed" is a word, so only the note shows the cut.
_LETTER_REMOVED = re.compile(r"\b(?:letter|first|last|final|end)\b[^.;]{0,20}\bremoved\b", re.I)
_TRUNC_PHRASES = ("cut short", "not quite", "not entirely", "not completely", "not fully", "cut off")
_CUT_NOTE = re.compile(r"\b(?:without|minus|missing|losing|loses|lacking|dropp\w*|drops|clipped|truncated|shortened|"
                       r"lopped|omitting|stops short|loses|cut)\b[^.;]{0,40}\b(?:letter|last|first|final|end|head|"
                       r"initial|tail|front|back|ending|start|beginning)\b", re.I)


_CUT_LETTER = re.compile(r"\b(?:without|minus|losing|lacking|dropping|missing|less|killed|lost|loses)\s+"
                         r"(?:its\s+|the\s+|a\s+)?(?:[a-z]+\s+)?[A-Z]{1,2}\b"
                         r"|\b[A-Z]{1,2}\b[^.;]{0,25}\b(?:killed|removed|dropped|lost|taken off|deleted|lifted out)\b"
                         r"|\bwith\s+(?:its\s+)?[A-Z]{1,2}\b(?:\s*\([^)]{0,12}\))?\s+(?:missing|lifted out|removed)\b")


def _plain_leaves(tree):
    """Checked lettered leaves of two or more clue words, no op on them."""
    for node in _walk(tree):
        if "op" in node or node.get("unchecked") or not node.get("gives") or not node.get("words"):
            continue
        yield node, re.findall(r"[a-z']+", str(node["words"]).lower())


def trunc_in_leaf(tree):
    """Multi-word leaves holding a truncation word anywhere (not just first: "Nick mostly" giving SATA,
    "island almost" giving SAR, "life cut short" giving NELLI; r28 FN: 5 misses) that give a non-word one
    letter short of a word: the cut is a deletion with its own indicator. Not "briefly"/"concise" (the
    abbreviation convention) and no apostrophe. Needs the lexicon."""
    lex = _lexicon_letters()
    if not lex:
        return 0
    n = 0
    for node, words in _plain_leaves(tree):
        text = " ".join(words)
        briefly = "briefly" in words and _BRIEFLY_CUT.search(str(node.get("note") or ""))
        if len(words) < 2 or not (_TRUNC_WORDS & set(words) or any(p in text for p in _TRUNC_PHRASES) or briefly):
            continue
        g = wordplay.letters(node["gives"]).lower()
        note = str(node.get("note") or "")
        if len(g) >= 3 and (g not in lex or _BRIEFLY_CUT.search(note) or _LETTER_REMOVED.search(note)) and "'" not in note + text \
                and any(g + c in lex or c + g in lex for c in "abcdefghijklmnopqrstuvwxyz"):
            n += 1
    return n


def own_ind_in_leaf(tree):
    """Ops whose direct plain leaf opens or ends with the op's own indicator words and holds more
    ("French way back" under rev<back>, "arthropod's shell" under outer<shell>; r28 FN: 3 misses):
    the leaf holds only the words that give its letters. select_word_in_leaf counts the opening case
    for selection ops; this counts the end of the leaf for every op and the opening for the rest."""
    n = 0
    for node in _walk(tree):
        if "op" not in node or node.get("unchecked") or node["op"] == "anagram":
            continue
        inds = [re.findall(r"[a-z']+", str(i.get("text") or "").lower()) for i in node.get("indicators") or [] if isinstance(i, dict)]
        for p in (q for q in node.get("parts") or [] if isinstance(q, dict) and "op" not in q and q.get("gives")):
            words = re.findall(r"[a-z']+", str(p.get("words") or "").lower())
            n += any(iw and len(words) > len(iw) and (words[-len(iw):] == iw or (
                words[:len(iw)] == iw and node["op"] not in wordplay.SELECT)) for iw in inds)
            n += node["op"] == "deletion" and any(iw and words == iw and len(iw) > 1 for iw in inds)  # r30 FN: leaf "not at first" under the indicator "not at first"
    return n


REPEAT_IN_LEAF = "leaf holds a doubling word (twice, double, again) and gives a doubled string"
REPEAT_FORM = "write rep<twice>([boy]AL) for ALAL: the leaf gives one copy, rep() doubles it, the doubling word is rep's indicator"
HALF_IN_LEAF = "leaf holds half and gives half of another of its words, a halving selection folded into the leaf"
SELECT_IND_ENDS_LEAF = "selection op whose letter-less leaf ends with the op's own indicator words"
BEHEAD_IN_LEAF = "leaf holds a losing-head/tail phrase and gives the letters that are left"
_REPEAT_WORDS = frozenset("twice doubled double repeated repeatedly again thrice redoubled doubling doubles "
                          "repeating duplicated duplicating twofold doubly encored encore".split())
_STUTTER_WORDS = frozenset("stuttering stutter stutters stuttered stammering stammer stammers stammered".split())
_BEHEAD = re.compile(r"\b(?:losing|lost|without|minus|lacking|missing|dropping|loses|shedding|ignoring|dismissing|"
                     r"removing|ditching|discarding|dumping)\s+"
                     r"(?:its\s+|the\s+|his\s+|her\s+|their\s+)?(?:head|tail|top|bottom|leader|front|back|"
                     r"first letter|last letter|initial|first|last|foremost|leading|opening|ending|finish|tip|start|beginning)\b"
                     r"|\b(?:headless|tailless)\b", re.I)


def repeat_in_leaf(tree):
    """Plain leaves holding twice, double or again with another word that give a string made of one block
    twice (r34 FN ALFALF: "Boy called twice" giving ALFALF): the repeat is an op with its own indicator.
    r35 judged 0 of 40 fine."""
    n = 0
    for node, words in _plain_leaves(tree):
        g = wordplay.letters(node["gives"])
        h = len(g) // 2
        n += len(words) >= 2 and bool(_REPEAT_WORDS & set(words)) and len(g) >= 2 and len(g) % 2 == 0 and g[:h] == g[h:]
        # r36 FN: "Stuttering" giving LALA, one stutter word whose letters double
        n += len(words) == 1 and words[0] in _STUTTER_WORDS and len(g) >= 4 and len(g) % 2 == 0 and g[:h] == g[h:]
    # r36 FN TUTU: a leaf "two" giving the same letters as the leaf beside it
    for parent in _walk(tree):
        parts = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        for a, b in zip(parts, parts[1:]):
            if any("op" in x or x.get("unchecked") or not x.get("gives") or not x.get("words") for x in (a, b)):
                continue
            wb = set(re.findall(r"[a-z']+", str(b["words"]).lower()))
            n += (len(wordplay.letters(a["gives"])) >= 2 and wordplay.letters(a["gives"]) == wordplay.letters(b["gives"])
                  and bool((_REPEAT_WORDS | {"two"}) & wb) and len(wb) == 1)
    # r40 FN CHOWCHOW: a leaf "Twice" giving the letters the op beside it already gives
    for parent in _walk(tree):
        parts = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        for a, b in zip(parts, parts[1:]):
            for rep, other in ((a, b), (b, a)):
                if "op" in rep or rep.get("unchecked") or other.get("unchecked") or "op" not in other \
                        or not rep.get("gives") or len(str(rep.get("words") or "").split()) != 1 \
                        or str(rep["words"]).lower().strip(" ,.!?") not in _REPEAT_WORDS | {"two"}:
                    continue
                try:
                    n += len(wordplay.letters(rep["gives"])) >= 2 and wordplay.letters(rep["gives"]) in wordplay.values(other)
                except Exception:
                    pass
    # r42 FN AGARAGAR, CHACHA, PRETTYPRETTY: a leaf of "more than once", "repeated", "doubled up" giving the letters
    # the run of pieces beside it already gives
    for parent in _walk(tree):
        parts = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        for i, rep in enumerate(parts):
            if "op" in rep or rep.get("unchecked") or not rep.get("gives") or not rep.get("words"):
                continue
            ws = re.findall(r"[a-z']+", str(rep["words"]).lower())
            if not ws or not set(ws) <= _REPEAT_PHRASE or not (set(ws) & _REPEAT_WORDS or ws[-3:] == ["more", "than", "once"]
                                                              or ws == ["once", "more"]):
                continue
            g = wordplay.letters(rep["gives"])
            runs = [parts[j:i] for j in range(max(0, i - 4), i)] + [parts[i + 1:k] for k in range(i + 2, min(len(parts), i + 4) + 1)]
            # a one-word leaf beside one piece with letters of its own is the blocks above
            n += len(g) >= 2 and any(g in _run_values(run) for run in runs
                                     if len(run) >= 2 or len(ws) >= 2 or ("op" not in run[0] and not run[0].get("gives")))
    return n


_REPEAT_PHRASE = _REPEAT_WORDS | frozenset("more than once up over times two the same time".split())


def _run_values(run):
    """The strings a run of sibling pieces can spell side by side ({} when a piece is unchecked or has no value)."""
    out = {""}
    for p in run:
        if p.get("unchecked"):
            return set()
        try:
            vals = {wordplay.letters(p.get("gives") or p.get("words"))} if "op" not in p else set(wordplay.values(p))
        except Exception:
            return set()
        if not vals or len(out) * len(vals) > 200:
            return set()
        out = {a + b for a in out for b in vals}
    return out - {""}


def _half_of_synonym(words, g):
    """A leaf of 3+ words with "half of" in it (not "half of the letters", "almost half of", "better half of", a
    half-dozen, "half-hearted") that gives fewer letters than the words beside half: half of a synonym, which no
    substring check can see. Only a non-word (CHOO, IMB, EUS; r42 judged: half of a score, weekend or duo giving TEN, SAT,
    ANT is a fine definitional half, 26 of 51 fine overall, a non-word 1 of 11). Needs the lexicon."""
    if "half" not in words or len(words) < 3 or len(g) < 2:
        return False
    i = words.index("half")
    return (words[i + 1:i + 2] == ["of"] and words[i + 2:i + 3] != ["the"]
            and words[i - 1:i] not in (["almost"], ["left"], ["better"], ["more"], ["than"], ["a"], ["other"], ["and"],
                                       ["first"], ["second"], ["last"])
            and g not in (_lexicon_letters() or {g})
            and not {"dozen", "time", "term", "way", "than"} & set(words) and not any(w.startswith("heart") for w in words)
            and len(g) < sum(len(w) for w in words if w not in ("half", "of")))


def half_in_leaf(tree):
    """Plain leaves holding half (also half-done) beside a clue word whose first or last half they give
    (r34 FN TAMPA: "half-done taco" giving TA): the halving is a selection op with its own indicator.
    r35 judged 0 of 40 fine. r42 FN CHORIZO "half of train" giving CHOO, DEEPEST "Half of capital city" giving PEST,
    IDIOTIC "notion, half rejected" giving ID: also half of a synonym (_half_of_synonym)."""
    n = 0
    for node, words in _plain_leaves(tree):
        g = wordplay.letters(node["gives"]).lower()
        n += (len(words) >= 2 and "half" in words and bool(g) and any(
            w != "half" and len(w) >= 4 and len(g) in (len(w) // 2, (len(w) + 1) // 2) and (w.startswith(g) or w.endswith(g))
            for w in words)) or _half_of_synonym(words, g)
    return n


def select_ind_ends_leaf(tree):
    """Selection ops whose leaf has no letters of its own and ends with the op's indicator words and holds more
    (r34 FN BUTTERUP: first<on top>("cooked on top")): the leaf holds only the words that give its letters.
    own_ind_in_leaf takes the leaves that give letters. r35 judged 2 of 30 fine."""
    n = 0
    for node in _walk(tree):
        if node.get("op") not in wordplay.SELECT or node.get("unchecked"):
            continue
        inds = [re.findall(r"[a-z']+", str(i.get("text") or "").lower()) for i in node.get("indicators") or [] if isinstance(i, dict)]
        for p in (q for q in node.get("parts") or [] if isinstance(q, dict) and "op" not in q and not q.get("gives")):
            words = re.findall(r"[a-z']+", str(p.get("words") or "").lower())
            n += any(iw and len(words) > len(iw) and words[-len(iw):] == iw for iw in inds)
    return n


SPLIT_WORD_LEAVES = "one word split into two leaves over the same clue words, with an insert between"
MOVE_NOTE_LEAF = "leaf gives a non-word its note says has a letter moved, a move written as a leaf"
FIRST_SIBLING_LEAVES = "a first-letters op picks one word while sibling leaves give the other words' initials"
HIDDEN_IND_ABOVE = "hidden op with no indicator under an op whose indicator opens with a hidden-word marker"
DELETION_NO_CUT = "deletion with one leaf part and no cut piece, the leaf a word one letter short"
INITIALS_IN_LEAF = "leaf holds a first-letters word (primarily, initially) and gives the initials of its other words"
_MOVE_NOTE = re.compile(r"\b(?:moved|shifted|transposed|relocated)\b", re.I)
_INITIAL_NOTE = re.compile(r"\b(?:first|initial|opening|leading|head|top|start)\b", re.I)
_HIDDEN_OPENERS = frozenset("having holding contains containing within in some part parts of showing displaying".split())


def split_word_leaves(tree):
    """A leaf and the first leaf of a sibling container/charade piece holding the very same clue words, whose
    letters in tree order spell one word (r38 FN ELGAR: "Listener" giving EA, then R after the insert; the r39
    sample EID, PIPED, NOSE, BEE): one word is split around an insert, so it is the container's outer piece
    (container(EID, N)), not two leaves. Needs the lexicon."""
    lex = _lexicon_letters()
    if not lex:
        return 0
    n = 0
    for node in _walk(tree):
        if node.get("unchecked"):
            continue
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        for i, leaf in enumerate(ps):
            if "op" in leaf or not leaf.get("words") or not leaf.get("gives") or leaf.get("unchecked"):
                continue
            for j, sub in enumerate(ps):
                if j == i or sub.get("op") not in ("container", "charade"):
                    continue
                inner = sub
                while isinstance(inner, dict) and "op" in inner:   # the outermost piece: down the first parts
                    inner = next(iter(inner.get("parts") or []), None)
                if not isinstance(inner, dict) or not inner.get("gives") or wordplay.letters(inner.get("words")) != wordplay.letters(leaf["words"]):
                    continue
                a, b = wordplay.letters(inner["gives"]).lower(), wordplay.letters(leaf["gives"]).lower()
                joined = a + b if j < i else b + a
                n += len(joined) >= 4 and joined in lex and not (a in lex and b in lex and len(a) > 1 and len(b) > 1)
    return n


def move_note_leaf(tree):
    """Plain lettered leaves whose note says a letter was moved or shifted (r38 FN OLYMPIA: "Greasy" giving OLY,
    "OILY, with its I moved down"): a move is move<indicator>(fodder, MOVED), not a leaf."""
    lex = _lexicon_letters()
    return sum(1 for node, words in _plain_leaves(tree) if lex and _MOVE_NOTE.search(str(node.get("note") or ""))
               and len(wordplay.letters(node["gives"])) >= 3 and wordplay.letters(node["gives"]).lower() not in lex)


def first_sibling_leaves(tree):
    """Charades holding a first-letters op over one word beside two or more plain one-word leaves that give
    their own initials (r38 FN CHEF: first<heads>(cooked) + H + E + F, every "heads" word its own leaf): one
    first-letters indicator over the list is one multi-part op."""
    n = 0
    for node in _walk(tree):
        if node.get("op") != "charade" or node.get("unchecked"):
            continue
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        firsts = [p for p in ps if p.get("op") == "first" and len(p.get("parts") or []) == 1 and not p.get("unchecked")]
        bare = [p for p in ps if "op" not in p and p.get("words") and p.get("gives") and len(str(p["words"]).split()) == 1
                and len(wordplay.letters(p["gives"])) == 1 and len(wordplay.letters(p["words"])) >= 3
                and wordplay.letters(p["words"]).startswith(wordplay.letters(p["gives"]))
                and _INITIAL_NOTE.search(str(p.get("note") or ""))]
        n += bool(firsts) and len(bare) >= 2
    return n


def deletion_no_cut(tree):
    """Deletions with one leaf part, no cut piece, whose leaf gives a non-word (r38 FN ROUBLES-type leaves, r39:
    TER under half-term, ROUBLES for TROUBLES): the cut is folded into the leaf and the deletion names nothing;
    write the real word and its cut, or the selection (middle, half) as its own op. r39 judged the unrestricted
    form 7 of 40 fine, all real-word leaves; non-word leaves only here."""
    lex = _lexicon_letters()
    return sum(1 for node in _walk(tree) if lex and node.get("op") == "deletion" and len(node.get("parts") or []) == 1
               and isinstance(node["parts"][0], dict) and "op" not in node["parts"][0]
               and len(wordplay.letters(node["parts"][0].get("gives"))) >= 3
               and wordplay.letters(node["parts"][0].get("gives")).lower() not in lex
               and any(wordplay.letters(node["parts"][0]["gives"]).lower() + c in lex
                       or c + wordplay.letters(node["parts"][0]["gives"]).lower() in lex for c in "abcdefghijklmnopqrstuvwxyz"))


_POSITION_IND = frozenset("primarily initially originally firstly principally heads leaders fronts starts openers".split())
_INITIALS_SKIP = frozenset("and with of the a an".split())


def initials_in_leaf(tree):
    """Plain leaves of 3+ words holding a first-letters word (primarily, initially, starts) beside the words whose
    first letters they give (r38 FN PIZZAZZ: "zip and zing primarily" giving ZZ): the pick is first<primarily>
    over those words, its own op."""
    n = 0
    for node, words in _plain_leaves(tree):
        if len(words) < 3 or not _POSITION_IND & set(words):
            continue
        rest = [w for w in words if w not in _POSITION_IND and w not in _INITIALS_SKIP]
        n += len(rest) >= 2 and wordplay.letters(node["gives"]).lower() == "".join(w[0] for w in rest)
    return n


def hidden_ind_above(tree):
    """Hidden ops with no indicator of their own under an op whose indicator opens with a hidden-word marker
    (r38 FN CINEMA: rev<having returned>(hidden(Blame Nicola))): the marker is the hidden op's indicator."""
    n = 0
    for node in _walk(tree):
        if node.get("op") in (None, "hidden", "charade") or node.get("unchecked"):
            continue
        for ind in node.get("indicators") or []:
            ws = re.findall(r"[a-z']+", str((ind or {}).get("text") or "").lower())
            n += bool(ws) and ws[0] in _HIDDEN_OPENERS and any(
                p.get("op") == "hidden" and not p.get("indicators") for p in node.get("parts") or [] if isinstance(p, dict))
    return n


NESTED_SAME_OP = "an op nested directly in an op of the same kind, only one of the two carrying an indicator"
MIDDLE_SIBLING_LEAF = "a middle op picks one word while a sibling leaf gives the middle letters of its own word"
DEL_ONE_PIECE = "deletion wraps a charade though the cut lies inside one plain piece, so it cuts that piece"
ANA_IS_MOVE = "anagram of one word whose result is the word with a single letter moved, a move written as an anagram"
#: r41 judged: an anagram indicator that is no word of position or motion (shuffled, changed, new) is a real anagram
#: that happens to sit one move from the word (8 of 40 fine); with a movement word in the indicator, 0 of 25 fine.
_MOVE_IND = re.compile(r"\b(?:mov\w*|up|down|forwards?|backwards?|back|rais\w*|lower\w*|later|earlier|advanc\w*|ris\w*|"
                       r"sink\w*|sent|dropp?\w*|promot\w*|relocat\w*|shift\w*|east|west|north|south|tuck\w*|put|place\w*|"
                       r"position\w*|bring\w*|brought|transpos\w*|swap\w*|exchang\w*|jump\w*|go\w*|step\w*|slip\w*|"
                       r"travel\w*|head\w*|climb\w*|fall\w*|lift\w*|pass\w*|row|late|early)\b", re.I)
_NEST_KINDS = frozenset({"deletion", "container", "reversal", "first", "last", "middle", "outer"})


def nested_same_op(tree):
    """Deletions, containers, reversals or picks directly inside an op of the same kind where one of the two has
    no indicator (r40 FN: del<>(del<lacking>(UNRECOGNISABLE, GLOBE), BLE), container<kept in>(container<>(FILE, D+D), D)):
    one indicator is one op, so the two are one multi-part op."""
    n = 0
    for node in _walk(tree):
        if node.get("op") not in _NEST_KINDS or node.get("unchecked"):
            continue
        for p in node.get("parts") or []:
            if isinstance(p, dict) and p.get("op") == node["op"] and not p.get("unchecked") \
                    and bool(p.get("indicators")) != bool(node.get("indicators")):
                n += 1
    return n


def _centre_slice(g, w):
    """Whether g is the centred stretch of w (one or two letters shorter at each end alike)."""
    d = len(w) - len(g)
    return d >= 2 and any(w[a:a + len(g)] == g for a in {d // 2, (d + 1) // 2} if a >= 1)


def middle_sibling_leaf(tree):
    """A middle op beside a plain one-word leaf giving the middle letters of its own word (r40 FN MESSI:
    middle<the very essence of>(primeval) + passion giving SSI): one middle indicator over both words is one
    multi-part op."""
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("unchecked") or not any(p.get("op") == "middle" and not p.get("unchecked") for p in ps):
            continue
        n += any("op" not in p and p.get("words") and p.get("gives") and len(str(p["words"]).split()) == 1
                 and len(wordplay.letters(p["gives"])) >= 2 and _centre_slice(wordplay.letters(p["gives"]).lower(),
                                                                              wordplay.letters(p["words"]).lower())
                 for p in ps)
    return n


def del_one_piece(tree):
    """Deletions of a bare cut piece from a charade of 2+ plain leaves where the cut letters lie inside exactly
    one piece (r40 FN MELODRAMA del<no end>(MELODY + RAM, Y), AGAIN del<not entirely>(A + GANG, G); Paul ruling 1):
    the deletion acts on that piece, del(MELODY, Y), inside the charade."""
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "deletion" or node.get("unchecked") or len(ps) != 2 or ps[0].get("op") != "charade" \
                or "op" in ps[1] or ps[1].get("words") or not ps[1].get("gives"):
            continue
        pcs = [p for p in ps[0].get("parts") or [] if isinstance(p, dict)]
        if len(pcs) < 2 or any("op" in p or p.get("unchecked") for p in pcs):
            continue
        gs = [wordplay.letters(p.get("gives") or p.get("words")) for p in pcs]
        cut = wordplay.letters(ps[1]["gives"])
        hold = [g for g in gs if cut in g and len(g) > len(cut)]
        n += bool(cut) and len(hold) == 1 and sum(cut in g for g in gs) == 1 and not any(set(g) <= set(cut) for g in gs)
    return n


def ana_is_move(tree, answer=None):
    """Anagrams of one plain leaf of 5+ letters whose answer holds the leaf with exactly one letter moved and not
    the leaf itself (r40 FN BRASSERIE ana(BRASSIERE), INTER ana(INERT)): a letter move is move<indicator>(fodder, MOVED)."""
    ans = wordplay.letters(answer).lower() if answer else ""
    if not ans:
        return 0
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "anagram" or node.get("unchecked") or len(ps) != 1 or "op" in ps[0] or not ps[0].get("gives"):
            continue
        f = wordplay.letters(ps[0]["gives"]).lower()
        if len(f) < 5 or f in ans or not any(_MOVE_IND.search(str(i.get("text") or ""))
                                             for i in node.get("indicators") or [] if isinstance(i, dict)):
            continue
        moved = set()
        for i in range(len(f)):
            rest = f[:i] + f[i + 1:]
            moved |= {rest[:j] + f[i] + rest[j:] for j in range(len(f))}
        n += any(m != f and m in ans for m in moved)
    return n


DEL_AS_MOVE = "deletion whose indicator is a movement word (moved, shifting, relocating) and whose cut letters are no clue word, a move written as a deletion"
_MOVE_WORD_IND = re.compile(r"\b(?:mov(?:e|es|ed|ing)|shift\w*|relocat\w*|transpos\w*|migrat\w*|transferr?\w*|repositi\w*|displac\w*)\b", re.I)
_MOVE_AWAY = re.compile(r"\b(?:out|away|off|from|leav\w*|exit\w*|gone|departing|removed)\b", re.I)


def del_as_move(tree):
    """Deletions whose indicator is a movement word and whose cut piece is no clue word (r42 FN INGENUE
    del<being moved to take the lead>(GENUINE, IN), MARLONBRANDO del<relocating>(LONDON, N)): the letters appear from
    nowhere, so they are moved, not removed: move<indicator>(fodder, MOVED). Not "moved out/away/off" (a
    departure), and not a tree movedLetter already counts (a sibling gives the cut letter back). r42 judged 1 of
    20 fine; with the cut in a clue word ("shifting ton") 11 of 20 were fine plain deletions."""
    if moved_letters(tree):
        return 0
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        n += (node.get("op") == "deletion" and len(ps) >= 2 and all("op" not in p and not p.get("words") for p in ps[1:])
              and any(_MOVE_WORD_IND.search(t) and not _MOVE_AWAY.search(t)
                      for t in (str(i.get("text") or "") for i in node.get("indicators") or [] if isinstance(i, dict))))
    return n


def behead_in_leaf(tree):
    """Plain leaves of 2+ words holding "losing head", "without its tail", "headless" and giving letters
    (r34 FN IDLER: "Youngster losing head" giving ID): the cut is a deletion with its own indicator.
    r35 judged 3 of 33 fine."""
    return sum(1 for node, words in _plain_leaves(tree)
               if len(words) >= 2 and _BEHEAD.search(" ".join(words)) and len(wordplay.letters(node["gives"])) >= 2)


_NOTE_CAPS = re.compile(r"\b[A-Z]{3,}\b")


def _cut_from_note(g, note):
    """Whether g (lower case) is the start or end of a capitalised word in the note, one or two letters shorter."""
    return any(0 < len(t) - len(g) <= 2 and (t.lower().startswith(g) or t.lower().endswith(g))
               for t in _NOTE_CAPS.findall(note))


def cut_note_leaf(tree):
    """Leaves giving a non-word of 3+ letters whose note says it is a real word minus some letters
    (GAM "game losing its final E", STE "SITE without I", EARY "WEARY, leading W killed"; r28 FN: 5 misses):
    the leaf must be the real word with a deletion op. Needs the lexicon."""
    lex = _lexicon_letters()
    if not lex:
        return 0
    n = 0
    under_cut = {id(p) for node in _walk(tree) if node.get("op") in ("deletion", "move", "substitution")
                 for p in node.get("parts") or [] if isinstance(p, dict)}
    for node, words in _plain_leaves(tree):
        g = wordplay.letters(node["gives"]).lower()
        note = str(node.get("note") or "")
        if len(words) >= 2 and len(g) >= 2 and g in lex and id(node) not in under_cut and not node.get("select") \
                and "'" not in note + str(node.get("words")) and not node.get("soundsLike") \
                and (_CUT_NOTE.search(note) or _CUT_LETTER.search(note) or "cut short" in note) \
                and _cut_from_note(g, note):
            n += 1  # r36 FN: "Pope dismissing foremost" giving OPE, a word, but the note says POPE without the P
            continue
        if len(g) >= 3 and g not in lex and id(node) not in under_cut and not node.get("select") \
                and "'" not in note + str(node.get("words")) and "apostrophe" not in note.lower() \
                and not node.get("soundsLike") \
                and (_CUT_NOTE.search(note) or _CUT_LETTER.search(note)):
            n += 1
    return n


ANA_LONE_EDGE = "anagram scrambles a single letter that the answer shows at its start or end"
ANA_LITERAL_EDGE = "anagram holds a clue word as written at the edge of its fodder, and the answer shows it unscrambled at its edge"
DEL_WRAPS_CHARADE = "deletion wraps a charade though its indicator stands between the charade's pieces, so it cuts one piece"


def _pull_part(tree, node, idx, front):
    """A copy of `tree` with part `idx` of anagram `node` taken out and set beside it in a charade."""
    t = copy.deepcopy(tree)
    for cur in _walk(t):
        if cur.get("op") == "anagram" and cur.get("parts") == node.get("parts") and cur.get("indicators") == node.get("indicators"):
            piece = cur["parts"].pop(idx)
            mid = dict(cur)
            cur.clear()
            cur.update({"op": "charade", "parts": [piece, mid] if front else [mid, piece]})
            return t
    return None


def _anagrams_with_pulled_part(tree, answer, pick, keep_order=False):
    """How many anagrams in `tree` have a part `pick(parts, idx)` accepts that, set outside the anagram at
    the start or the end of a charade, still gives the answer. `keep_order`: a first part may only go to the
    start and a last part to the end (the piece stays where the clue put it)."""
    if not answer or not isinstance(tree, dict):
        return 0
    try:
        wordplay.evaluate(copy.deepcopy(tree), answer)
    except Exception:
        return 0
    n = 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "anagram" or node.get("unchecked") or len(parts) < 2 or not all(isinstance(p, dict) for p in parts):
            continue
        done = False
        for idx in (i for i in range(len(parts)) if pick(parts, i)):
            for front in (True, False):
                if keep_order and front != (idx == 0):
                    continue
                t = _pull_part(tree, node, idx, front)
                try:
                    wordplay.evaluate(t, answer)
                    done = True
                    break
                except Exception:
                    pass
            if done:
                break
        n += done
    return n


def _one_letter_part(parts, i):
    """A fodder part that is a single letter: a 1-letter leaf or a first/last pick of one letter."""
    p = parts[i]
    if p.get("unchecked"):
        return False
    if "op" in p:
        if p["op"] not in ("first", "last"):
            return False
        try:
            vals = wordplay.values(p)
        except Exception:
            return False
        return any(len(v) == 1 for v in vals)  # values() lists every reading of the pick: CAR, CA and C
    return len(wordplay.letters(p.get("gives") or p.get("words"))) == 1


def ana_lone_edge(tree, answer=None):
    """Anagrams with a single-letter fodder piece (an abbreviation, a first/last pick, a lone word like "a")
    anywhere in the fodder, that the answer shows at its start or end (r32 FN: ESPLANADES E + ana(SEDAN ALPS),
    REAWAKEN ana(A + WEAKER) + N, CYPRIOTS C + ana(...)). Paul 10-19: a lone letter that can sit outside the
    anagram must. A letter that sits mid-answer is genuine fodder (Paul's rule 9) and is not counted."""
    return _anagrams_with_pulled_part(tree, answer, _one_letter_part)


def ana_literal_edge(tree, answer=None):
    """Anagrams whose first or last fodder piece is 2+ clue-word letters taken as written, which the answer
    shows unscrambled at its edge (r32 FN: ZEROTOLERANCE ZERO + ana(TO + CLEANER) holds TO). Single letters
    are ana_lone_edge's."""
    def literal_edge(parts, i):
        p = parts[i]
        return i in (0, len(parts) - 1) and "op" not in p and not p.get("unchecked") and not _stand_in_piece(p) \
            and len(wordplay.letters(p.get("gives") or p.get("words"))) >= 2
    return _anagrams_with_pulled_part(tree, answer, literal_edge, keep_order=True)


def del_wraps_charade(tree, clue=None):
    """Deletions over a charade of plain leaves whose indicator stands in the clue between two of the
    charade's pieces (r32 FN: del<getting end away>(TWERP + KING, P), rev(del<short>(AS + LASS, S))): the word
    cuts the one piece next to it, so the deletion belongs on that piece inside the charade."""
    if not clue:
        return 0
    low = clue.lower()
    try:
        tree = wordplay.locate(copy.deepcopy(tree), clue)
    except Exception:
        pass
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "deletion" or node.get("unchecked") or len(ps) != 2 or ps[0].get("op") != "charade":
            continue
        pcs = [p for p in ps[0].get("parts") or [] if isinstance(p, dict)]
        inds = [i for i in node.get("indicators") or [] if isinstance(i, dict) and str(i.get("text") or "")]
        if len(pcs) < 2 or len(inds) != 1 or any("op" in p or p.get("unchecked") for p in pcs):
            continue
        gs = [wordplay.letters(p.get("gives") or p.get("words")) for p in pcs]
        cut = wordplay.letters(ps[1].get("gives"))
        if not cut or any(set(g) <= set(cut) for g in gs) or not any(len(g) > len(cut) and cut in g for g in gs):
            continue  # the removed letters are a piece of the charade itself (daughter D, then D removed): a group deletion
        t = str(inds[0]["text"])
        at = inds[0]["at"] if isinstance(inds[0].get("at"), int) else low.find(t.lower())
        spans = [(min(a for a, _ in s), max(b for _, b in s)) for s in (_subtree_spans(p, clue, low) for p in pcs) if s]
        if at >= 0 and len(spans) == len(pcs) and any(b <= at for _, b in spans) and any(a >= at + len(t) for a, _ in spans):
            n += 1
    return n


def ana_double_indicator(tree):
    """Anagrams with two indicators that are not touching halves of one phrase and both anagram words of
    their own (r23 FN RUDIMENTAL ana<out><unusually>): one op, one indicator."""
    n = 0
    for node in _walk(tree):
        if node.get("op") != "anagram":
            continue
        ins = [i for i in node.get("indicators") or [] if isinstance(i, dict)]
        if len(ins) >= 2 and not all(_ind_adjacent(ins[k], ins[k + 1]) for k in range(len(ins) - 1)) \
                and sum(_own_word("anagram", i.get("text")) for i in ins) >= 2:
            n += 1
    return n


def _clue_words(text):
    """Lower-case word set of clue text, markup and parentheticals removed."""
    return set(re.findall(r"[a-z]+", re.sub(r"<[^>]*>|\([^)]*\)", " ", (text or "").lower())))


# Connectives a stripped-down leaf may swallow ("with", "and", "'s"); the fix for
# an unchecked leaf of one is to take it out, so it is no loss when the redo does.
CONNECTIVE_WORDS = frozenset(
    "a an and as at be but by for from has having in is it of on or s that the this to when with".split())


# Words that join the pieces of a charade and do nothing else.
CHARADE_GLUE = frozenset("then after next before following plus beside alongside by over on".split())


def _accounted_words(ann, leaves=True):
    """The clue words an annotation accounts for: wordplay leaves (when `leaves`;
    "real" skips junk leaves, unchecked with no `gives`), indicators on any op or definition, definitions, and declared link words."""
    got = set()
    for n in _walk(ann.get("wordplay")):
        if leaves and "op" not in n and (leaves != "real" or n.get("gives") or not n.get("unchecked")):
            got |= _clue_words(n.get("words"))
        for i in n.get("indicators") or []:
            got |= _clue_words(i.get("text") if isinstance(i, dict) else i)
    for d in ann.get("definitions") or []:
        got |= _clue_words(d.get("text"))
        for i in d.get("indicators") or []:
            got |= _clue_words(i.get("text") if isinstance(i, dict) else i)
    for lw in ann.get("linkWords") or []:
        got |= _clue_words(lw)
    return got


def _old_roles(old, words):
    """For each word in `words`, how the annotation `old` used it, as a phrase for
    the dropped_words message: "leaf 'x y'", "indicator on charade", "definition"."""
    roles = {w: [] for w in words}
    for n in _walk((old or {}).get("wordplay")):
        if "op" not in n:
            for w in words & _clue_words(n.get("words")):
                roles[w].append(f"in leaf [{n.get('words')}]")
        for i in n.get("indicators") or []:
            text = i.get("text") if isinstance(i, dict) else i
            for w in words & _clue_words(text):
                roles[w].append(f"in the {n.get('op')} indicator '{text}'")
    for d in (old or {}).get("definitions") or []:
        for w in words & _clue_words(d.get("text")):
            roles[w].append("in the definition")
    return {w: "; ".join(dict.fromkeys(r)) or "in the old wordplay" for w, r in roles.items()}


def forgiven_dropped_words(old, new, clue):
    """The clue words a redo `new` of the annotated clue `old` may leave out of every
    leaf, indicator and definition: link words, which the stored annotation never
    carries (annotation.view() derives them as the clue's uncovered gaps, and the
    schema refuses a stored `linkWords`). They are the connectives ("for", "to", "and")
    and any other measured link word that only an old LEAF held ("use", "one", "once":
    the new tree gives the same letters without it). A word the old tree used as an
    indicator ("displayed") is not forgiven unless it is a connective.
    dropped_words refused ~1,200 redo lines in 48h (576 sessions), and the earlier fix,
    adding the word to the new `linkWords`, was itself refused by the schema (284
    sessions; the model's own `linkWords` is stripped as derived)."""
    lost = (_accounted_words(old) - _accounted_words(new)) & _clue_words(clue)
    # Words the old tree made an op work with (any indicator but a charade's, which is glue:
    # "then", "after", "carrying"; or a definition's indicator) stay refused. A leaf word,
    # a charade's glue word or a word of the old definition that the new tree narrowed away
    # is a link word now, when it can stand for an equals sign (audit 10-20: 31 of 171
    # dropped words after the earlier fix were charade glue or a narrowed definition).
    hard = set()
    for n in _walk(old.get("wordplay")):
        for i in n.get("indicators") or []:
            words = _clue_words(i.get("text") if isinstance(i, dict) else i)
            hard |= words - CHARADE_GLUE if n.get("op") == "charade" else words
    for d in old.get("definitions") or []:
        for i in d.get("indicators") or []:
            hard |= _clue_words(i.get("text") if isinstance(i, dict) else i)
    return lost & (CONNECTIVE_WORDS | (_accounted_words(old) - hard)) & link_vocabulary()


def redo_lost_words(old, new, clue):
    """The clue words the dropped_words gate refuses a redo `new` of `old` for losing."""
    lost = (_accounted_words(old) - _accounted_words(new)) & _clue_words(clue)
    # A connective only a leaf of the old tree held (an unchecked "with" leaf
    # the re-annotation exists to remove) may go; as an indicator, definition
    # or link word it still has to stay.
    lost -= CONNECTIVE_WORDS - _accounted_words(old, leaves="real")
    lost -= forgiven_dropped_words(old, new, clue)
    return lost


def carry_old_indicators(old, new, clue):
    """`new` with each indicator the redo cut short given back its full text from `old`.
    Audit 10-21: most dropped_words refusals were a model trimming a multi-word indicator
    to its head ("after leaving" -> "leaving", "worn by" -> "worn", "Nameless" -> "less")
    and the gate then refusing the words trimmed off. When a new indicator's span sits
    inside an old indicator's span (same clue text, no other span of the new tree in the
    way) and that old indicator holds a word the redo would lose, the new indicator takes
    the old one's text and position. The gate still judges the result, so nothing a redo
    really drops is carried. `new` back as it was when nothing applies."""
    lost = redo_lost_words(old or {}, new or {}, clue)
    wp = (new or {}).get("wordplay")
    if not lost or not isinstance(wp, dict) or not (old or {}).get("wordplay"):
        return new
    olds = [i for n in _walk(old["wordplay"]) for i in n.get("indicators") or []
            if isinstance(i, dict) and isinstance(i.get("at"), int) and i.get("text")
            and clue[i["at"]:i["at"] + len(i["text"])].lower() == i["text"].lower()
            and lost & _clue_words(i["text"])]
    if not olds:
        return new
    wp = copy.deepcopy(wp)

    def spans(skip):
        out = [(d["at"], d["at"] + len(d["text"])) for d in (new.get("definitions") or [])
               if isinstance(d.get("at"), int) and d.get("text")]
        for n in _walk(wp):
            for s in [n] if "op" not in n else n.get("indicators") or []:
                text = s.get("words") if "op" not in n else s.get("text")
                if isinstance(s, dict) and s is not skip and isinstance(s.get("at"), int) and text:
                    out.append((s["at"], s["at"] + len(text)))
        return out

    changed = False
    for n in _walk(wp):
        for ind in n.get("indicators") or []:
            if not (isinstance(ind, dict) and isinstance(ind.get("at"), int) and ind.get("text")):
                continue
            a, b = ind["at"], ind["at"] + len(ind["text"])
            for o in olds:
                oa, ob = o["at"], o["at"] + len(o["text"])
                if oa <= a and b <= ob and (oa, ob) != (a, b) \
                        and not any(s < ob and oa < e for s, e in spans(ind)):
                    ind["text"], ind["at"] = clue[oa:ob], oa
                    changed = True
                    break
    return {**new, "wordplay": wp} if changed else new


def redo_keep_words(old, clue):
    """The words a redo of `old` must keep, in clue order: what the gate refuses
    when the new annotation holds none of them. Shown to the redo up front."""
    lost = redo_lost_words(old or {}, {}, clue)
    seen = []
    for w in re.findall(r"[a-z]+", re.sub(r"<[^>]*>|\([^)]*\)", " ", (clue or "").lower())):
        if w in lost and w not in seen:
            seen.append(w)
    return seen


def redo_regressions(old, new, clue):
    """Ways a redo `new` of an already-annotated clue gives up what the annotation
    `old` on file had, as "kind: what" strings; [] when it gives up nothing. The
    shape rules only judge the new tree, so a rewrite that cut the problem leaf,
    nulled the wordplay, flattened it or dropped Spooner would pass them
    (timesjumbo-1784 6d, 10-17: the redo dropped "displayed, in"):
      - no_tree: a tree where there was one is not replaced by none (a double
        definition covering every clue word is not a loss);
      - lost_spoonerism: a Spooner clue keeps its spoonerism;
      - dropped_words: a clue word in a leaf or indicator of the old tree stays in
        a leaf, indicator, definition or link word of the new one;
      - downgraded: a real tree is not replaced by a bare `cryptic` op."""
    old, new = old or {}, new or {}
    out = []
    wp = new.get("wordplay")
    if not wp or not (wp.get("op") or wp.get("words")):
        if old.get("wordplay"):
            defs = new.get("definitions") or []
            if not (len(defs) >= 2 and _clue_words(clue) <= _accounted_words(new)):
                out.append("no_tree: the new annotation has no wordplay tree where the old one had one")
            return out
    elif "spooner" in (clue or "").lower() and not any(n.get("op") == "spoonerism" for n in _walk(wp)):
        out.append("lost_spoonerism: the clue names Spooner and the tree has no spoonerism op")
    if old.get("wordplay"):
        lost = redo_lost_words(old, new, clue)
        if lost:
            roles = _old_roles(old, lost)
            out.append("dropped_words: " + ", ".join(f"{w} ({roles[w]})" for w in sorted(lost))
                       + " are in no leaf, indicator or definition of the new annotation. Write each back "
                       "where it did work: inside a leaf `[words]` of `wp`, as the `<indicator>` of an op, "
                       "or in `def`. Do not add `linkWords`: it is worked out from `wp` and is dropped "
                       "before the check, so it changes nothing here")
        old_wp = old["wordplay"]
        if wp and wp.get("op") == "cryptic" and old_wp.get("op") not in (None, "cryptic"):
            out.append("downgraded: the old wordplay was a real tree and the new one is a bare cryptic op")
    return out


def lesson_warnings(tag, ann, held):
    """The findings tools/lesson_checks.py reads off a clue and its answer."""
    clue = ((held.get("clue") or {}).get("text")) or ""
    answer = held.get("solution") or ""
    out = []
    if len(held.get("group") or []) > 1:
        return out
    if how := lesson_checks.dd_misses_wordplay(ann, clue, answer):
        out.append(f"{tag}: {lesson_checks.DD_MISSES_WORDPLAY} ({how}): parse it, or keep one "
                   f"definition and the wordplay")
    if said := lesson_checks.spelling_unsaid(ann, answer, (held.get("clue") or {}).get("enumeration")):
        out.append(f"{tag}: {lesson_checks.SPELLING_UNSAID}: set `spelling` to {said!r}")
    return out


def shape_warnings(tag, ann, clue=None, answer=None):
    """The findings for one annotation's tree shape, each a ratchet marker."""
    tree = ann.get("wordplay")
    out = []
    if k := charade_in_charade(tree):
        out.append(f"{tag}: {k} {CHARADE_IN_CHARADE}: join the pieces in one charade")
    if k := unindicated_ops(tree):
        bare = sorted({n.get("op") for n in _walk(tree) if n.get("op") in NEEDS_INDICATOR
                       and not n.get("unchecked") and not n.get("indicators")})
        out.append(f"{tag}: {k} {NO_INDICATOR}(s) ({', '.join(bare)}): name the indicator word on the op, "
                   f"or the op is not in the clue")
    if k := cdef_repeats(tree):
        out.append(f"{tag}: {k} extra leaf(s): {CDEF_REPEAT}; write wp as ONE leaf, "
                   f"cd([the clue words once]), with one note on it")
    if k := bad_arity(tree):
        out.append(f"{tag}: {k} {STORED_ARITY}")
    if k := span_overlaps(tree):
        out.append(f"{tag}: {k} {SPAN_OVERLAP}: two leaves or indicators share clue words")
    if k := in_definition(ann):
        out.append(f"{tag}: {k} {IN_DEFINITION}: the definition and the wordplay do not share words "
                   f"unless the clue is &lit. Often the definition is drawn too wide: an "
                   f"article (\"a\", \"the\") or link word the wordplay uses belongs outside it "
                   f"(def \"little instrument\", not \"a little instrument\"). If one clue word "
                   f"is split (\"stopcock\": STOP = BAN in the wordplay, \"cock\" the definition) "
                   f"keep the leaf on the whole word and put the definition on only its "
                   f"part, \"at\" pointing inside the word")
    if k := leaf_folds(tree):
        out.append(f"{tag}: {k} {LEAF_FOLD}: a selection, deletion or hidden word is an op, "
                   f"not a leaf")
    if k := repeated_selections(tree):
        out.append(f"{tag}: {k} {REPEATED_SELECTION}: one selection over a multi-word leaf")
    if single_leaf(tree):
        out.append(f"{tag}: {SINGLE_LEAF}: a synonym for the answer is no wordplay; parse it, "
                   f"or it is a cryptic or double definition")
    if k := bare_in_charade(tree, ann):
        out.append(f"{tag}: {k} {BARE_IN_CHARADE}: put the clue word that supplies them in a leaf")
    if k := anagram_of_container(tree):
        out.append(f"{tag}: {k} {ANAGRAM_OF_CONTAINER}: ins(outer, ana(...)) puts the anagram inside")
    if k := arity_ins(tree):
        out.append(f"{tag}: {k} {ARITY_INS}: ins(outer, inner) holds one in the other")
    if k := arity_other(tree):
        out.append(f"{tag}: {k} {ARITY_OTHER}: write the step as an expression the evaluator takes")
    if k := del_single(tree):
        out.append(f"{tag}: {k} {DEL_SINGLE}: del(whole, removed)")
    if k := ind_in_leaf(tree, clue):
        out.append(f"{tag}: {k} {IND_IN_LEAF}: the leaf holds only the words that give its letters")
    if k := scrambled_leaves(tree):
        out.append(f"{tag}: {k} {SCRAMBLED_LEAF}: a leaf gives its own letters in order; "
                   f"only an anagram op scrambles")
    if k := folded_indicators(tree):
        out.append(f"{tag}: {k} {IND_FOLDED}: an indicator belongs on its op, and the leaf holds "
                   f"only the words that give its letters")
    if k := fake_parts(tree):
        out.append(f"{tag}: {k} {FAKE_PARTS}: a substitution swaps letters the clue names; "
                   f"do not invent pieces to reach three parts")
    if k := padding_leaves(tree):
        out.append(f"{tag}: {k} {PADDING_LEAF}: say what the words give, or take them out of the "
                   f"wordplay")
    if k := nested_containers(tree, answer):
        out.append(f"{tag}: {k} {NESTED_CONTAINER}: pieces that go in the same holder together are a "
                   f"charade (ins(AB E, U + S)); a piece in a piece in a third is "
                   f"ins(third, ins(second, first))")
    if k := anagram_synonyms(tree, {**(ann or {}), "_answer": answer}, clue):
        out.append(f"{tag}: {k} {ANAGRAM_SYNONYM}: only the clue's own words are scrambled; "
                   f"the synonym joins the anagram's result in a charade")
    if k := misplaced_indicators(tree):
        out.append(f"{tag}: {k} {MISPLACED_INDICATOR}: file each indicator on the op it acts on "
                   f"(a reversal's on rev<...>, a selection's on first/last<...>), not on the charade")
    if k := bare_initials(tree):
        out.append(f"{tag}: {k} {BARE_INITIAL}: a first letter is picked by an op (first<...>(word)), "
                   f"not given by a leaf")
    if k := deletion_scope(tree):
        out.append(f"{tag}: {k} {DELETION_SCOPE}: an end-cutting indicator acts on the one piece it "
                   f"follows, del(piece, letters) inside the charade")
    if k := wrong_role_indicators(tree):
        out.append(f"{tag}: {k} {WRONG_ROLE}: put each indicator on the op it signals (a reversal "
                   f"word on rev<...>, a container word on ins<...>, an anagram word on ana<...>)")
    if k := deletion_inside_component(tree, clue, answer):
        out.append(f"{tag}: {k} {DELETION_INSIDE}: the indicator acts on the one piece it sits by, "
                   f"del(piece, letters) inside the charade; add no piece only to remove it")
    if k := container_inside_component(tree, answer):
        out.append(f"{tag}: {k} {CONTAINER_INSIDE}: the indicator acts on the one piece it sits by, "
                   f"ins(piece, letters) inside the charade, not ins over the whole charade")
    if k := unindicated_uncovered(tree):
        out.append(f"{tag}: {k} {UNINDICATED_BARE}: give each op its own indicator word from the clue; "
                   f"one indicator covers one op (a pair of first/last/middle picks may share one)")
    if k := shared_indicators(tree, clue):
        out.append(f"{tag}: {k} {SHARED_INDICATOR}: a clue word does one job; name the indicator "
                   f"once and the leaf's letters from other words")
    if k := half_leaves(tree):
        out.append(f"{tag}: {k} {HALF_LEAF}: a half of a word is picked by an op "
                   f"(first/last of its letters), once per word")
    if k := deletion_scattered(tree):
        out.append(f"{tag}: {k} {DELETION_SCATTERED}: 'half' acts on one word; write a deletion "
                   f"per word, del(word, its half)")
    if k := reverse_phrase(tree):
        out.append(f"{tag}: {k} {REVERSE_PHRASE}: say what the words do (an anagram, a hidden "
                   f"word, a charade), not a reading of the whole phrase")
    if k := deletion_scope_answer(tree, answer):
        out.append(f"{tag}: {k} {DELETION_SCOPE_ANSWER}: the indicator acts on the one piece it sits "
                   f"by, so delete inside the charade, del(piece, letters)")
    if k := double_indicators(tree):
        out.append(f"{tag}: {k} {DOUBLE_INDICATOR}: one op per indicator; write two ops "
                   f"(two reversals, two deletions), and a hidden word needs no selection under it")
    if k := moved_letters(tree):
        out.append(f"{tag}: {k} {MOVED_LETTER}: write move<indicator>(fodder, MOVED), e.g. "
                   f"move<dropping>([England]ALBION, [ball]O)")
    if k := pool_gaps(tree, clue):
        out.append(f"{tag}: {k} {POOL_GAP}: the fodder is the words together under the indicator; "
                   f"a piece the clue places elsewhere belongs to the charade or insertion, not the pool")
    if k := midword_leaves(tree, clue):
        out.append(f"{tag}: {k} {MIDWORD_LEAF}: a cut is an op (del/first/last), not a leaf that "
                   f"gives part of a word")
    if k := traded_indicators(tree):
        out.append(f"{tag}: {k} {TRADED_INDICATOR}: file each indicator word on the op of its own kind")
    if k := charade_out_of_order(tree, clue):
        out.append(f"{tag}: {k} {CHARADE_ORDER}: keep the clue's order, or reverse the piece that moves")
    if k := reversal_split(tree, clue):
        out.append(f"{tag}: {k} {REVERSAL_SPLIT}: it reverses the one piece it sits by")
    if k := cut_in_leaf(tree):
        out.append(f"{tag}: {k} {CUT_IN_LEAF}: the cut word is an op's indicator, the leaf holds the rest")
    for fn, label, hint in (
            (lambda: ana_select_edge(tree, answer), ANA_SELECT_EDGE, "set the pick beside the anagram in a charade"),
            (lambda: non_word_operands(tree), NON_WORD_OPERAND, "give the op one word's letters; join the synonyms in a charade"),
            (lambda: del_wide(tree, clue), DEL_WIDE, "the piece before the indicator is the one cut; the others belong to the parent"),
            (lambda: ind_leaf_overlap(tree, clue), IND_LEAF_OVERLAP, "a clue word does one job"),
            (lambda: ana_double_indicator(tree), ANA_DOUBLE_IND, "one op, one indicator"),
            (lambda: del_straddle(tree), DEL_STRADDLE, "cut inside the one piece the word acts on"),
            (lambda: swapped_pair(tree), SWAPPED_PAIR, "file each indicator on the op of its own kind"),
            (lambda: link_in_leaf(tree), LINK_IN_LEAF, "the link word is the clue's join, not the leaf's"),
            (lambda: ana_stand_in(tree), ANA_STAND_IN, "spell the stand-in beside the anagram"),
            (lambda: select_word_in_leaf(tree), SELECT_WORD_IN_LEAF, "the leaf holds only the words that give its letters"),
            (lambda: select_phrase_in_leaf(tree), SELECT_PHRASE_IN_LEAF, "the selection is an op with its own indicator"),
            (lambda: halved_as_deletion(tree), HALVED_AS_DELETION, "keep half the word with a halving selection"),
            (lambda: trims_as_selection(tree, answer), TRIM_AS_SELECTION,
             "cut the synonym with a deletion, del<without limits>([jumps]BOUNCES, B, S)"),
            (lambda: split_shared_indicators(tree), SPLIT_SHARED_INDICATOR, "one indicator, one multi-part op"),
            (lambda: trunc_in_leaf(tree), TRUNC_IN_LEAF, "the truncation word is a deletion's indicator"),
            (lambda: cut_note_leaf(tree), CUT_NOTE_LEAF, "give the real word and cut it with a deletion op"),
            (lambda: selector_as_cut(tree), SELECTOR_AS_CUT, "the removed letter is a first/last pick with its own indicator"),
            (lambda: ana_lone_edge(tree, answer), ANA_LONE_EDGE, "set the letter beside the anagram in a charade"),
            (lambda: ana_literal_edge(tree, answer), ANA_LITERAL_EDGE, "set the word beside the anagram in a charade"),
            (lambda: del_wraps_charade(tree, clue), DEL_WRAPS_CHARADE, "cut inside the one piece the word acts on"),
            (lambda: repeat_in_leaf(tree), REPEAT_IN_LEAF, REPEAT_FORM),
            (lambda: split_word_leaves(tree), SPLIT_WORD_LEAVES, "the word is the container's outer piece, one leaf"),
            (lambda: move_note_leaf(tree), MOVE_NOTE_LEAF, "write move<indicator>(fodder, MOVED)"),
            (lambda: first_sibling_leaves(tree), FIRST_SIBLING_LEAVES, "one first-letters indicator over the list is one multi-part op"),
            (lambda: hidden_ind_above(tree), HIDDEN_IND_ABOVE, "the opening marker is the hidden op's indicator"),
            (lambda: deletion_no_cut(tree), DELETION_NO_CUT, "give the whole word and cut it with a deletion"),
            (lambda: initials_in_leaf(tree), INITIALS_IN_LEAF, "the pick is first<indicator> over those words"),
            (lambda: half_in_leaf(tree), HALF_IN_LEAF, "keep half the word with a halving selection"),
            (lambda: select_ind_ends_leaf(tree), SELECT_IND_ENDS_LEAF, "the leaf holds only the words that give its letters"),
            (lambda: nested_same_op(tree), NESTED_SAME_OP, "one indicator, one multi-part op"),
            (lambda: middle_sibling_leaf(tree), MIDDLE_SIBLING_LEAF, "one middle indicator over the list is one multi-part op"),
            (lambda: del_one_piece(tree), DEL_ONE_PIECE, "put the deletion on the piece it cuts, inside the charade"),
            (lambda: ana_is_move(tree, answer), ANA_IS_MOVE, "write move<indicator>(fodder, MOVED)"),
            (lambda: del_as_move(tree), DEL_AS_MOVE, "write move<indicator>(fodder, MOVED)"),
            (lambda: behead_in_leaf(tree), BEHEAD_IN_LEAF, "the cut is a deletion with its own indicator"),
            (lambda: own_ind_in_leaf(tree), OWN_IND_IN_LEAF, "the leaf holds only the words that give its letters")):
        if k := fn():
            out.append(f"{tag}: {k} {label}: {hint}")
    return out


SUPERSEDED_BY_TREE = ("typed anagram but no assembly.anagrams", "no machine-checkable assembly")


def _tag_of(puzzle, where):
    """The finding tag for an annotation path from puzzle_schema.annotations."""
    m = re.match(r"\$\.entries\[(\d+)\]\.(?:alsoLeads\[(\d+)\]\.)?annotation$", where)
    if m:
        e = puzzle["entries"][int(m.group(1))]
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        return tag + (f" alsoLeads[{m.group(2)}]" if m.group(2) else "")
    m = re.match(r"\$\.offGrid\[(\d+)\]", where)
    return f"{int(m.group(1)) + 1}-offgrid" if m else where


#: Whether the corpus holds no note that restates the abbreviation table:
#: then every file is held to check_no_abbreviation_notes. Until then only a
#: run's own new notes are (check_no_new_abbreviation_notes), so the files still
#: carrying them keep validating. tools/strip_abbreviation_notes.py --commit
#: sets it True in its migration commit.
ABBREVIATION_NOTES_STRIPPED = False


def _restating(tree):
    """[leaf] of every note in a tree that only restates the table."""
    out, stack = [], [tree] if isinstance(tree, dict) else []
    while stack:
        node = stack.pop()
        if annotation.restates_abbreviation(node):
            out.append(node)
        stack += [p for p in node.get("parts") or [] if isinstance(p, dict)]
    return out


def _abbreviation_error(tag, node):
    return (f"{tag}: leaf {node['words']!r} > {node['gives']!r} stores the note "
            f"{node['note']!r}, which only restates the abbreviation table; leave "
            f"it out (the site shows {annotation.abbreviation_gloss(node)!r} from the table)")


def check_no_new_abbreviation_notes(puzzle, path, errors):
    """check_no_abbreviation_notes for a run's own puzzle, on the notes the
    committed file does not already hold (until ABBREVIATION_NOTES_STRIPPED)."""
    if ABBREVIATION_NOTES_STRIPPED:
        return
    committed = committed_entries(path) or {}
    for e in puzzle["entries"]:
        ann = e.get("annotation") or {}
        was = (committed.get(entry_id(e)) or {}).get("annotation") or {}
        held = {(n["words"], n["gives"], n["note"]) for n in _restating(was.get("wordplay"))}
        for node in _restating(ann.get("wordplay")):
            if (node["words"], node["gives"], node["note"]) not in held:
                errors.append(_abbreviation_error(entry_id(e), node))


def check_no_abbreviation_notes(tag, tree, errors):
    """A leaf stores no note that only restates an abbreviation the table
    holds (annotation.restates_abbreviation): view() derives that gloss from
    tools/build_abbreviations.table(), so the stored note is a derivable field.
    A note that adds anything beyond the pair stays."""
    errors += [_abbreviation_error(tag, node) for node in _restating(tree)]


#: Ops that rearrange, cut or reshape letters, so the letters they give are a step
#: a solver cannot see from the leaves alone. A charade only joins.
TRANSFORMING_OPS = frozenset({"anagram", "reversal", "container", "deletion", "substitution",
                              "cycling", "move", "hidden", "homophone", "spoonerism", "composite",
                              "palindrome", *wordplay.SELECT})
#: Indicators that must stand against what they work on.
ADJACENT_OPS = ("anagram", "reversal", "hidden")
WALKTHROUGH_GAP = "walkthrough does not follow the wordplay"
INDICATOR_APART = "indicator not next to its fodder"


def _stem_match(a, b):
    """True when two lower-case words are one word inflected (wild/wildly, get/getting)."""
    if a == b:
        return True
    p = len(os.path.commonprefix([a, b]))
    return p >= 3 and p >= min(len(a), len(b)) - 1 and abs(len(a) - len(b)) <= 4


_PHRASE_FILLER = frozenset({"of", "the", "a", "an", "in", "from", "to", "at", "by", "for", "one"})
_FIRST_WORDS = frozenset({"first", "initial", "initially", "opening", "opener", "leader", "leading",
                          "lead", "head", "start", "starts", "beginning", "top"})
_LAST_WORDS = frozenset({"last", "final", "finally", "closing", "ending", "end", "ends", "tail",
                         "bottom", "finish", "terminal"})


def _mentions_phrase(walk_words, phrase, op=None):
    """The phrase's words, inflections allowed, appear in order and adjacent in the walkthrough.

    Two paraphrases are no gap: little words dropped from either side ("first of"
    read as "the first L": the indicator's filler "of" is not what the walkthrough
    must repeat), and for a first/last selection a walkthrough that says its
    position in other words (leader / first / initial / opening, or last / final /
    closing / end) than the indicator's own."""
    want = words_of(phrase)
    n = len(want)
    if not n:
        return False
    if any(all(_stem_match(v, w) for v, w in zip(walk_words[i:i + n], want))
           for i in range(len(walk_words) - n + 1)):
        return True
    core = [w for w in want if w not in _PHRASE_FILLER]
    walk = [w for w in walk_words if w not in _PHRASE_FILLER]
    m = len(core)
    if m and m < n and any(all(_stem_match(v, w) for v, w in zip(walk[i:i + m], core))
                           for i in range(len(walk) - m + 1)):
        return True
    for group in (_FIRST_WORDS, _LAST_WORDS):
        if op in ("first", "last") and set(core) & group and group & set(walk_words):
            return True
    return False


def walkthrough_gaps(tree, answer, walkthrough):
    """What the walkthrough leaves out of the wordplay tree: the text of each
    indicator it never names, and the letters each transforming op gives (bar
    the answer itself, and a single letter) that it never shows. `tree` must
    give `answer` (wordplay.evaluate). Returns [(kind, text)], kind "indicator"
    or "gives"."""
    got = wordplay.evaluate(tree, answer)
    walk_words = words_of(walkthrough)
    # Letters as the walkthrough writes them: a word, or a run of capitals and
    # hyphens or spaces ("I-N-A-T"), with the separators dropped.
    shown = {w.upper() for w in re.findall(r"[^\W\d_]+", walkthrough or "")}
    shown |= {letters(w) for w in re.findall(r"[A-Z](?:[- ][A-Z])+", walkthrough or "")}
    whole = letters(answer)
    out = []
    for node in _walk(tree):
        if node.get("unchecked"):
            continue
        for ind in node.get("indicators") or []:
            if not _mentions_phrase(walk_words, ind["text"], node.get("op")):
                out.append(("indicator", ind["text"]))
        g = got.get(id(node))
        if node.get("op") in TRANSFORMING_OPS and g and len(g) > 1 and g != whole:
            if g not in {letters(w) for w in shown}:
                out.append(("gives", g))
    return out


def _span_of(node):
    """(start, end) in the clue of every located leaf and indicator under `node`, or None."""
    spans = []
    for n in _walk(node):
        if "words" in n and "at" in n:
            spans.append((n["at"], n["at"] + len(n["words"])))
        spans += [(i["at"], i["at"] + len(i["text"])) for i in n.get("indicators") or [] if "at" in i]
    return (min(s for s, _ in spans), max(e for _, e in spans)) if spans else None


def apart_indicators(tree, clue):
    """[(indicator text, content words in the gap)] for each anagram, reversal or
    hidden indicator with a word between it and what it works on that is not a
    link word. The fodder is the located leaves under the op; an indicator among
    them is touching."""
    allowed = link_vocabulary()
    out = []
    for node in _walk(tree):
        if node.get("op") not in ADJACENT_OPS or node.get("unchecked"):
            continue
        fodder = [_span_of(p) for p in node.get("parts") or []]
        fodder = [f for f in fodder if f]
        if not fodder:
            continue
        fs, fe = min(s for s, _ in fodder), max(e for _, e in fodder)
        for ind in node.get("indicators") or []:
            if "at" not in ind:
                continue
            i0, i1 = ind["at"], ind["at"] + len(ind["text"])
            gap = clue[fe:i0] if i0 >= fe else clue[i1:fs] if i1 <= fs else ""
            bad = [w for w in words_of(gap) if w not in allowed]
            if bad:
                out.append((ind["text"], bad))
    return out


def follow_warnings(tag, ann, held, puzzle):
    """Findings a solver would hit following the hint: a walkthrough that never
    names an indicator or an intermediate result (WALKTHROUGH_GAP), and an
    anagram, reversal or hidden indicator with content words between it and its
    fodder (INDICATOR_APART). Findings only: no ratchet field counts them."""
    tree = ann.get("wordplay")
    clue = ((held.get("clue") or {}).get("text")) or ""
    if not tree or not clue:
        return []
    out = []
    for ind, bad in apart_indicators(tree, clue):
        out.append(f"{tag}: {INDICATOR_APART}: {ind!r} is separated from what it works on by "
                   f"{', '.join(bad)}; an indicator operates on what it touches")
    walk = (ann.get("explanation") or {}).get("walkthrough")
    # The walkthrough rung lists every op of the tree itself (app.js wordplaySteps:
    # each indicator marked, each intermediate result derived), so its prose need not
    # repeat them. Only a blog-derived ladder shows no such list, and there the prose is all
    # the solver has.
    if walk and ann.get("fromBlog"):
        alt = held.get("alteration")
        try:
            gaps = walkthrough_gaps(tree, alt["from"] if isinstance(alt, dict) and alt.get("from")
                                    else annotation.display_answer(held, puzzle), walk)
        except (wordplay.WordplayError, KeyError, TypeError, ValueError):
            gaps = []   # a tree that does not give its answer is already an error
        if gaps:
            inds = [t for k, t in gaps if k == "indicator"]
            mids = [t for k, t in gaps if k == "gives"]
            said = ([f"names the indicator{'s' if len(inds) > 1 else ''} " + ", ".join(map(repr, inds))]
                    if inds else []) + (["shows the intermediate letters " + ", ".join(mids)] if mids else [])
            out.append(f"{tag}: {WALKTHROUGH_GAP}: it never " + " or ".join(said)
                       + ". A solver must be able to follow every step from the walkthrough")
    return out


def tree_view(puzzle):
    """(the puzzle as annotation.view_puzzle shows it, errors, warnings). A
    tree that does not give the answer is an error, and its annotation is
    left out of the view. An `unchecked` node (a step filed before trees were
    checked, which the expression cannot write) warns, and the ratchet (wordplay.unchecked) lets a puzzle keep only the
    ones annotation_backlog.json allows it: new annotations may add none."""
    problems = []
    viewed = annotation.view_puzzle(puzzle, problems)
    errors = [f"{_tag_of(puzzle, where)}: wordplay: {msg}" for where, msg in problems]
    warnings = []
    for where, held, ann in puzzle_schema.annotations(puzzle):
        n = len(unverified_unchecked(ann.get("wordplay"), held.get("solution") or None))  # steps computable from their leaf are not unchecked
        if ABBREVIATION_NOTES_STRIPPED:
            check_no_abbreviation_notes(_tag_of(puzzle, where), ann.get("wordplay"), errors)
        if n:
            warnings.append(f"{_tag_of(puzzle, where)}: {n} {UNCHECKED_STEP}(s), taken as filed "
                            f"from the old blocks; write the step as an expression the "
                            f"evaluator checks (tools/wordplay.py)")
        if k := anagram_charades(ann.get("wordplay"), held.get("solution") or None):
            warnings.append(f"{_tag_of(puzzle, where)}: {k} {ANAGRAM_CHARADE}: an anagram's "
                            f"fodder is one pool of letters, so its pieces are its own parts "
                            f"(ana(x + y)); a word that only joins them is a link word, and an "
                            f"anagram indicator goes on ana<...>; a letter piece at the answer's edge "
                            f"belongs outside it (I + N + ana(RIP SIGN)), not scrambled in")
        warnings += shape_warnings(_tag_of(puzzle, where), ann, (held.get("clue") or {}).get("text"), held.get("solution") or None)
        warnings += lesson_warnings(_tag_of(puzzle, where), ann, held)
        warnings += follow_warnings(_tag_of(puzzle, where), ann, held, puzzle)
    return viewed, errors, warnings


def theme_source(puzzle):
    """What supplies a themed puzzle's letters that no clue word gives: its
    preamble, else the clue its `themeClue` names ("30-across"), else None."""
    if puzzle.get("preamble"):
        return "the preamble"
    if puzzle.get("themeClue"):
        return puzzle["themeClue"]
    return None


def _validate_puzzle(puzzle, corpus=False, schema=True):
    errors, warnings = [], []
    # The file's shape first: tools/fetch_puzzle.write_puzzle_file refuses to
    # write anything that breaks it, and this catches a file written any other way.
    if schema:
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
            if key == "definitions" and (ann.get("definedByPreamble") is True
                                         or whole_rebus(ann, clue)):
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
                              f"`at` is the offset in code points, filled in when "
                              f"the puzzle is written, if the text occurs once")
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
            # No clue words: letters the puzzle's preamble supplies, or the
            # clue that states its theme (`themeClue`, filed by hand, when the
            # paper prints the gimmick in a clue: nation-3337's 30-across).
            if not frag and not (b.get("gives") and theme_source(puzzle)):
                what = f" giving {b['gives']!r}" if b.get("gives") else ""
                left = clue_words_no_block_covers(ann, clue)
                what += (f" (clue words nothing covers yet: {', '.join(map(repr, left))}; "
                         f"one of them gives these letters)" if left else
                         " (every clue word is already covered, so these letters come from "
                         "words another block quotes: quote them again, "
                         "[Two bitters]COLD + [Two bitters#2]RAW)")
                errors.append(f"{tag}: a block with no clueFragment{what} is for letters the "
                              f"preamble supplies, and needs `gives` and a puzzle with a "
                              f"preamble (or a filed themeClue); otherwise quote the "
                              f"clue words it parses: in `wp` write that piece as "
                              f"[clue words]LETTERS rather than bare LETTERS. Letters "
                              f"a del() took out and an ins() puts back are still the "
                              f"letters of a clue word, so quote that word")

        # Letter mechanics.
        build = assembly(ann)
        check_anagram_letters(puzzle.get("id"), entry_id(e), tag, ann, errors)
        row = SETTER_ERROR.get((puzzle.get("id"), entry_id(e)))
        if row:
            errors += [f"{tag}: tools/data/setter_error.json's row: {p}"
                       for p in setter_error_problems(puzzle, entry_id(e), row, ann)]
        check_anagram_has_fodder(tag, ann, warnings)
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

        errors.extend(f"{tag}: {p}" for p in letter_problems(ann, e))
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
        # walkthrough is ours either way, and the faults these two find occur on
        # published grids. Gated, they would never fire.
        check_walkthrough_opener(tag, ann, warnings)
        check_walkthrough_closer(tag, ann, warnings)
        # Not under `authored` either, and for the same reason: the fault is in
        # OUR parse of a published clue, on somebody else's grid.
        check_link_word_is_not_an_order(tag, ann, clue, warnings)
        check_link_word_is_clear_of_other_marks(tag, ann, clue, errors)
        # 895 published clues predate it: a corpus sweep warns, a run writing a
        # puzzle must fix it.
        check_link_word_is_not_inside_a_block(tag, ann, clue, warnings if corpus else errors)
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
        for h in walkthrough_hedges(walk, clue):
            errors.append(f"{tag}: walkthrough hedges with {h!r} — parse the chunk "
                          f"properly instead of excusing it (STYLE.md); a clue word is quoted "
                          f"('{h}' is fine in quotes only if the clue prints it), else say what "
                          f"the word does (the pun, the indicator) without the hedge")
        if len(walk.split()) > WALKTHROUGH_HARD_MAX:
            errors.append(f"{tag}: walkthrough is {len(walk.split())} words "
                          f"(max {WALKTHROUGH_HARD_MAX}) — that length is working-out, "
                          f"not an explanation; the blocks already did the mechanics")
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
        # Notes and definitionFit are published too, so they get the same check.
        for field, text in ([("walkthrough", walk), ("surface", surface),
                             ("definitionFit", explanation(ann).get("definitionFit") or "")]
                            + [("block note", b.get("note") or "")
                               for b in ann.get("blocks", [])]):
            for marker in BACKTRACKS:
                if marker in text.lower():
                    errors.append(f"{tag}: {field} contains {marker!r} — that is "
                                  f"working-out, not an explanation. Settle the parse "
                                  f"first, then write the finished sentence")


    errors.extend(message_problems(puzzle))
    warnings.extend(check_preamble(puzzle))
    if annotated:
        check_every_clue_is_annotated(puzzle["entries"], errors, warnings,
                                      blind_misses(puzzle["id"]), corpus=corpus,
                                      reopened=(puzzle.get("solutions") or {}).get("reopened") or {})
        check_model_answer_doubted(puzzle, errors, warnings, corpus=corpus)
        check_cryptic_definition_cap(puzzle["entries"], errors, warnings,
                                     authored=authored)
        if authored:
            check_authored_puns(puzzle["entries"], errors)
        check_definition_not_fodder(puzzle["entries"], errors, warnings)
        if not corpus:
            check_definition_against_blog(puzzle, warnings)
            check_blocks_against_blog(puzzle, warnings)
            check_cryptic_definition_against_blog(puzzle, warnings)
            check_type_against_blog(puzzle, warnings)
        check_blocks_account_for_answer(puzzle["entries"], errors, warnings)
        check_blocks_decompose(puzzle["entries"], errors, warnings)
        check_blocks_in_answer_order(puzzle["entries"], errors, warnings)
        check_blocks_carry_notes(puzzle["entries"], warnings)

    return annotated, errors, warnings


# --- the ratchet -------------------------------------------------------------
#
# A rule added after many puzzles were already annotated cannot fail the corpus
# on day one, and a REQUIRE_X flag flipped by hand once a backfill drained the
# backlog would leave the rule optional for exactly the puzzles it was invented
# for — the next ones — for as long as anyone forgets.
#
# So the allowance is per puzzle and written down. A puzzle may carry as many
# unannotated clues as annotation_backlog.json records for it and not one more;
# a puzzle not in the file — every puzzle fetched since the field was
# added — is allowed none. The backlog can only ever shrink: a full run rewrites the file
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
    "blocks.note": (BLOCK_NO_NOTE,),
    "indicators.for": ("lack `for`",),
    "features": ("no features",),
    "explanation.surface": ("no explanation.surface",),
    "assembly.anagrams": ("no assembly.anagrams",),
    "messages": ("names a hidden-letter device",),
    "wordplay.unchecked": (UNCHECKED_STEP,),
    "wordplay.anagramCharade": (ANAGRAM_CHARADE,),
    "wordplay.charadeInCharade": (CHARADE_IN_CHARADE,),
    "wordplay.noIndicator": (NO_INDICATOR,),
    "wordplay.cdefRepeat": (CDEF_REPEAT,),
    "wordplay.arity": (STORED_ARITY,),
    "wordplay.spanOverlap": (SPAN_OVERLAP,),
    "wordplay.inDefinition": (IN_DEFINITION,),
    "wordplay.indFolded": (IND_FOLDED,),
    "wordplay.bareInitial": (BARE_INITIAL,),
    "wordplay.leafFold": (LEAF_FOLD,),
    "wordplay.repeatedSelection": (REPEATED_SELECTION,),
    "wordplay.singleLeaf": (SINGLE_LEAF,),
    "wordplay.bareInCharade": (BARE_IN_CHARADE,),
    "wordplay.anagramOfContainer": (ANAGRAM_OF_CONTAINER,),
    "wordplay.arityIns": (ARITY_INS,),
    "wordplay.arityOther": (ARITY_OTHER,),
    "wordplay.delSingle": (DEL_SINGLE,),
    "wordplay.indInLeaf": (IND_IN_LEAF,),
    "wordplay.scrambledLeaf": (SCRAMBLED_LEAF,),
    "wordplay.fakeParts": (FAKE_PARTS,),
    "wordplay.paddingLeaf": (PADDING_LEAF,),
    "wordplay.nestedContainer": (NESTED_CONTAINER,),
    "wordplay.anagramSynonym": (ANAGRAM_SYNONYM,),
    "wordplay.misplacedIndicator": (MISPLACED_INDICATOR,),
    "wordplay.deletionScope": (DELETION_SCOPE,),
    "wordplay.wrongRole": (WRONG_ROLE,),
    "wordplay.deletionInside": (DELETION_INSIDE,),
    "wordplay.containerInside": (CONTAINER_INSIDE,),
    "wordplay.sharedIndicator": (SHARED_INDICATOR,),
    "wordplay.halfLeaf": (HALF_LEAF,),
    "wordplay.deletionScattered": (DELETION_SCATTERED,),
    "wordplay.reversePhrase": (REVERSE_PHRASE,),
    "wordplay.midWordLeaf": (MIDWORD_LEAF,),
    "wordplay.deletionScopeAnswer": (DELETION_SCOPE_ANSWER,),
    "wordplay.doubleIndicator": (DOUBLE_INDICATOR,),
    "wordplay.movedLetter": (MOVED_LETTER,),
    "wordplay.poolGap": (POOL_GAP,),
    "wordplay.tradedIndicator": (TRADED_INDICATOR,),
    "wordplay.reversalSplit": (REVERSAL_SPLIT,),
    "wordplay.anaSelectEdge": (ANA_SELECT_EDGE,),
    "wordplay.delWide": (DEL_WIDE,),
    "wordplay.indLeafOverlap": (IND_LEAF_OVERLAP,),
    "wordplay.anaDoubleInd": (ANA_DOUBLE_IND,),
    "wordplay.delStraddle": (DEL_STRADDLE,),
    "wordplay.swappedPair": (SWAPPED_PAIR,),
    "wordplay.linkInLeaf": (LINK_IN_LEAF,),
    "wordplay.anaStandIn": (ANA_STAND_IN,),
    "wordplay.selectWordInLeaf": (SELECT_WORD_IN_LEAF,),
    "wordplay.halvedAsDeletion": (HALVED_AS_DELETION,),
    "wordplay.trimAsSelection": (TRIM_AS_SELECTION,),
    "wordplay.splitSharedIndicator": (SPLIT_SHARED_INDICATOR,),
    "wordplay.truncInLeaf": (TRUNC_IN_LEAF,),
    "wordplay.cutNoteLeaf": (CUT_NOTE_LEAF,),
    "wordplay.ownIndInLeaf": (OWN_IND_IN_LEAF,),
    "wordplay.repeatInLeaf": (REPEAT_IN_LEAF,),
    "wordplay.splitWordLeaves": (SPLIT_WORD_LEAVES,),
    "wordplay.moveNoteLeaf": (MOVE_NOTE_LEAF,),
    "wordplay.firstSiblingLeaves": (FIRST_SIBLING_LEAVES,),
    "wordplay.hiddenIndAbove": (HIDDEN_IND_ABOVE,),
    "wordplay.deletionNoCut": (DELETION_NO_CUT,),
    "wordplay.initialsInLeaf": (INITIALS_IN_LEAF,),
    "wordplay.halfInLeaf": (HALF_IN_LEAF,),
    "wordplay.selectIndEndsLeaf": (SELECT_IND_ENDS_LEAF,),
    "wordplay.nestedSameOp": (NESTED_SAME_OP,),
    "wordplay.middleSiblingLeaf": (MIDDLE_SIBLING_LEAF,),
    "wordplay.delOnePiece": (DEL_ONE_PIECE,),
    "wordplay.anaIsMove": (ANA_IS_MOVE,),
    "wordplay.delAsMove": (DEL_AS_MOVE,),
    "wordplay.beheadInLeaf": (BEHEAD_IN_LEAF,),
    "wordplay.selectorAsCut": (SELECTOR_AS_CUT,),
    "wordplay.anaLoneEdge": (ANA_LONE_EDGE,),
    "wordplay.anaLiteralEdge": (ANA_LITERAL_EDGE,),
    "wordplay.delWrapsCharade": (DEL_WRAPS_CHARADE,),
    "wordplay.ddMissesWordplay": (lesson_checks.DD_MISSES_WORDPLAY,),
    "spelling.unsaid": (lesson_checks.SPELLING_UNSAID,),
}


def load_backlog():
    """{field: {puzzle: allowance}}. A field the file has no list for yet is left
    out, and is not enforced until the --tighten that writes its list."""
    if not BACKLOG_PATH.exists():
        return {f: {} for f in BACKLOG_MARKERS}
    data = json.loads(BACKLOG_PATH.read_text())
    return {f: data[f] for f in BACKLOG_MARKERS if f in data}


def count_backlog(warnings):
    """Clues, not warnings: a clue missing two indicator notes warns twice, and
    noting one of them must not make the puzzle count more than before."""
    return {f: len({w.split(":", 1)[0] for w in warnings if any(m in w for m in ms)})
            for f, ms in BACKLOG_MARKERS.items()}


def _sort_key(kv):
    """Series, then number, for a namespaced id ("cryptic-30041"). An id whose
    tail is not a number sorts first in its series rather than raising."""
    series, _, num = kv[0].rpartition("-")
    return (series, int(num) if num.isdigit() else 0, kv[0])


def write_backlog(observed, allowed):
    """`observed` is {number: {field: count}} from a run over every puzzle.

    Writes the SMALLER of what was observed and what was already allowed, per
    puzzle per field, so "may only shrink" is enforced here rather than by a
    comment: recording whatever was seen would let a run that lost annotations
    raise the ceiling to fit them, and every run after it would agree the
    puzzle was fine."""
    ratchet = {f: {num: min(c[f], allowed.get(f, {}).get(num, c[f]))
                   for num, c in observed.items()} for f in BACKLOG_MARKERS}
    data = {"_why": "Per-puzzle allowance of clues predating a required annotation "
                    "field. Written by tools/validate_annotations.py; may only "
                    "shrink. A puzzle absent from a field's list must have none.",
            **{f: {num: n for num, n in sorted(ratchet[f].items(), key=_sort_key)
                   if n} for f in BACKLOG_MARKERS}}
    store_backlog(data)


def store_backlog(data, path=None):
    """Write the backlog in the layout git stores (the json-keys clean filter's:
    one line per top-level key). Every writer goes through here: a layout the
    filter would change shows as a code edit in the pre-reset backfill, which
    publishes with plumbing that skips the filter."""
    import json_merge
    (path or BACKLOG_PATH).write_text(json_merge.dump_lines(data))


def explain(name=None):
    """Print what a check actually does, read out of this file's own source.

    Annotation runs would otherwise page through this whole file to find one
    function, and every grep/sed call is a turn. The answer is the source, so
    this hands over the source: the definition asked for and the comment block
    above it, which is where the reason lives.

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
        # A run passes the words of a message it saw, and a message is built
        # inside a larger function, so show the lines that print it.
        words = [w.lower() for w in re.split(r"[_\W]+", name) if w and w.lower() != "check"]
        hits = [i for i, ln in enumerate(lines) if words and all(w in ln.lower() for w in words)]
        if not hits and len(words) > 1:
            hits = [i for i, ln in enumerate(lines)
                    if sum(w in ln.lower() for w in words) >= max(2, len(words) - 1)]
        if hits:
            print(f"# `{name}` is not a check; the source lines that mention it:\n")
            for i in hits[:2]:
                print("\n".join(lines[max(0, i - 6):i + 8]) + "\n")
            return 0
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
    name = name.strip().split(".")[-1]      # a ratchet field, `wordplay.cdefRepeat`, names its constant
    key = re.sub(r"[-\s]+", "_", re.sub(r"([a-z])([A-Z])", r"\1_\2", name)).strip("_")
    for exact in (name, key, f"check_{key}", f"check_{key.lower()}"):
        if exact in named:
            return [exact]
    folded = {k.lower(): k for k in named}      # cdefRepeat -> CDEF_REPEAT
    for exact in (key.lower(), f"check_{key.lower()}"):
        if exact in folded:
            return [folded[exact]]
    checks = [k for k in named if k.startswith("check_")]
    part = [k for k in checks if key.lower() in k.lower()]
    if part:
        return sorted(part, key=len)
    words = [w.lower().rstrip("s") for w in re.split(r"[_\W]+", key) if w]
    words = [w for w in words if w != "check"]
    if not words:
        return []
    source = {k: "\n".join(lines[named[k].lineno - 1:named[k].end_lineno]).lower() for k in checks}
    return sorted((k for k in checks if all(w in source[k] for w in words)),
                  key=lambda k: -sum(source[k].count(w) for w in words))


def _convention_exempt(stem, field):
    """True when `field` is a wordplay shape rule and the puzzle is Azed or Genius: their conventions
    make the judges accept the tree, so the rule stays a warning and the ratchet does not count it."""
    import shape_queue
    return (shape_queue.exempt(stem) and field.startswith("wordplay.")
            and field not in ("wordplay.unchecked", "wordplay.ddMissesWordplay"))


def _warning_only(field):
    """True when `field` ("wordplay.bareInitial") is a rule shape_queue.WARN_ONLY lists: it never fails a puzzle."""
    import shape_queue
    return field.startswith("wordplay.") and field.split(".", 1)[1] in shape_queue.WARN_ONLY


def backlog_errors(stem, warnings, allowed=None):
    """The ratchet's ERRORs for one puzzle: it may be short exactly as many
    notes as the backlog file records for it, and a puzzle absent from the file
    (anything annotated from now on, and every authored puzzle) is allowed 0."""
    allowed = load_backlog() if allowed is None else allowed
    errors = []
    for field, n in count_backlog(warnings).items():
        if field not in allowed or _convention_exempt(stem, field) or _warning_only(field):
            continue
        cap = allowed[field].get(stem, 0)
        if n > cap:
            ms = BACKLOG_MARKERS[field]
            named = [w.split(": ", 1)[1].split(". ", 1)[0] for w in warnings
                     if any(m in w for m in ms) and ": " in w][:4]
            errors.append(
                f"{n} clue(s) missing {field}, and this puzzle is allowed {cap} — "
                f"{field} is required on everything annotated since it was added. "
                f"The warnings above name them and say what to write."
                + (f" Missing: {'; '.join(named)}." if field in ("blocks.note", "wordplay.noIndicator") else ""))
    return errors


def check_against_committed(puzzle, path, errors):
    """The checks a run's own puzzle gets against the file as committed."""
    check_clue_unchanged(puzzle, path, errors)
    check_theme_clue_unchanged(puzzle, path, errors)
    check_spelling_kept(puzzle, path, errors)
    check_clue_rows_held(puzzle, errors)
    check_selectors_are_indicators(puzzle, path, errors)
    check_no_new_abbreviation_notes(puzzle, path, errors)


def run_errors(path, puzzle):
    """Every error `validate_annotations.py <id>` reports for `puzzle`, the
    run's copy of the file at `path`."""
    _, errors, warnings = validate_puzzle(puzzle)
    check_against_committed(puzzle, path, errors)
    return errors + backlog_errors(path.stem, warnings, load_backlog())


def flagged_clues(warnings, fields):
    """{field: sorted clue keys ("22a")} the warnings flag under each backlog field of `fields`."""
    return {f: sorted({w.split(":", 1)[0].lower() for w in warnings if any(m in w for m in BACKLOG_MARKERS[f])})
            for f in fields}


def check_one(path, corpus, allowed, requeue=()):
    """One puzzle's report: (its printed text, (stem, backlog counts) or None,
    whether it failed). Prints nothing itself, so a pool of workers can run it
    and the parent can print the reports in the order of the paths.

    `requeue` (the backlog fields tools/requeue_drift.py queues): a puzzle past its
    allowance in one of them is not an error here; the clues it flags come back as
    a third item of `seen`, {field: clue keys}, for the CI step that raises the
    allowance and queues them (requeue_drift.py --publish)."""
    out = []
    if not path.exists():
        return f"MISSING {path}\n", None, True
    puzzle = read_puzzle_file(path)
    annotated, errors, warnings = validate_puzzle(puzzle, corpus=corpus)
    if not corpus:          # a run's own puzzles; the corpus is HEAD already
        check_against_committed(puzzle, path, errors)
    total = len(puzzle["entries"])
    if annotated == 0 and corpus:
        # Nothing to check about annotations that do not exist yet — but
        # the checks that walk the whole file (markup) do apply, and
        # dropping them here would exempt exactly the puzzles nobody has
        # looked at.
        out.append(f"{puzzle['id']}: unannotated ({total} clues) — skipped\n")
        out += [f"{ERROR_PREFIX}{err}\n" for err in errors]
        return "".join(out), None, bool(errors)
    seen = (path.stem, count_backlog(warnings))
    if requeue:
        flagged = flagged_clues(warnings, requeue)
        over = {f: keys for f, keys in flagged.items() if f in allowed and len(keys) > allowed[f].get(path.stem, 0)}
        if over:
            seen += (over,)
            allowed = {**allowed, **{f: {**allowed[f], path.stem: len(keys)} for f, keys in over.items()}}
    errors += backlog_errors(path.stem, warnings, allowed)
    status = "OK" if not errors else "FAIL"
    by = f" ({puzzle['setter']})" if puzzle.get("setter") else ""
    out.append(f"{puzzle['id']}{by}: {annotated}/{total} annotated — {status}\n")
    out += [f"{WARN_PREFIX}{w}\n" for w in warnings if annotated]
    out += [f"{ERROR_PREFIX}{err}\n" for err in errors]
    return "".join(out), seen, bool(errors)


#: What a pool worker reads: set before the fork, so each inherits it.
_POOL_JOB = None
#: Puzzles a worker takes at a time: big enough that the pipe is not the cost.
POOL_CHUNK = 16
#: Fewer paths than this are checked in-process: forking costs more.
POOL_MIN = 200


def _pool_one(path):
    corpus, allowed, requeue = _POOL_JOB
    return check_one(path, corpus, allowed, requeue)


def check_all(paths, corpus, allowed, requeue=()):
    """check_one for each path, in the order of `paths`: spread across the
    cores when there are many (the full check, ~1,000s of puzzles, and every
    puzzle is independent), serial otherwise. The reports are identical either
    way, and so is the order they come back in. VALIDATE_JOBS=1 forces serial.
    Two workers by default, not cpu_count(): this runs on a shared host beside the
    burn and the bridge, and a full fan-out starved them (10-22). VALIDATE_JOBS
    overrides."""
    global _POOL_JOB
    jobs = int(os.environ.get("VALIDATE_JOBS") or 2)
    if jobs < 2 or len(paths) < POOL_MIN or "fork" not in multiprocessing.get_all_start_methods():
        for path in paths:
            yield check_one(path, corpus, allowed, requeue)
        return
    _POOL_JOB = (corpus, allowed, requeue)
    with multiprocessing.get_context("fork").Pool(jobs) as pool:
        yield from pool.imap(_pool_one, paths, POOL_CHUNK)


def shard_of(stem, n):
    """Which of n shards checks puzzle `stem`: a stable hash of the id (not
    Python's per-process hash()), so every step of the deploy agrees on the
    split. The same rule as tools/build_seo_pages.py's page shards."""
    return int.from_bytes(hashlib.sha256(stem.encode("utf-8")).digest()[:8], "big") % n


def shard_slice(paths, shard):
    """The paths of `paths` that belong to shard (i, n)."""
    i, n = shard
    return [p for p in paths if shard_of(p.stem, n) == i]


def take_shard_arg(argv):
    """(argv without `--shard i/n`, (i, n) or None)."""
    if "--shard" not in argv:
        return argv, None
    at = argv.index("--shard")
    try:
        i, n = map(int, argv[at + 1].split("/"))
    except (IndexError, ValueError):
        raise SystemExit("--shard takes i/n, e.g. --shard 0/4")
    if not 0 <= i < n:
        raise SystemExit(f"--shard {i}/{n}: i must be from 0 to n-1")
    return argv[:at] + argv[at + 2:], (i, n)


def main(argv):
    global FORCE_AUTHORED_CHECKS
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    argv, shard = take_shard_arg(argv)
    # --drift-out FILE (the deploy's full check): a puzzle past its allowance in a rule
    # tools/requeue_drift.py queues is no failure; its flagged clues go to FILE for
    # `requeue_drift.py --publish`, which raises the allowance and queues them.
    drift_out = None
    if "--drift-out" in argv:
        at = argv.index("--drift-out")
        drift_out, argv = argv[at + 1], argv[:at] + argv[at + 2:]
    if shard and "--tighten" in argv:
        raise SystemExit("--shard cannot --tighten: only an unsharded run has seen every puzzle")
    if shard and [a for a in argv if a != "--unscoped"]:
        raise SystemExit("--shard splits the full check: it takes no puzzle ids or files")
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
    # --deploy FILE...: the deploy's corpus rules (a dropped annotation is
    # queued, an unannotated puzzle skipped) on just these files, for the
    # hooks (.githooks/pre-commit, tools/pre_push.py) to refuse what would
    # turn the deploy red, and nothing the deploy lets through.
    deploy = "--deploy" in argv
    argv = [a for a in argv if a not in ("--tighten", "--deploy")]
    if argv:
        paths = [resolve_puzzle(a) for a in argv]
    else:
        paths = puzzle_files()
    full_run = not argv
    corpus = full_run or deploy
    allowed = load_backlog()
    if shard:
        # The ratchet is per puzzle, so a shard enforces exactly its slice of
        # it; the totals below are the slice's, and the shards' sum is the
        # whole corpus's. A failure in any shard fails its step, so the deploy.
        paths = shard_slice(paths, shard)
        print(f"shard {shard[0] + 1} of {shard[1]}: {len(paths)} puzzle(s)")
    if (deploy or full_run) and not tighten and time.time() < SHAPE_GRACE_UNTIL:
        # The hooks and CI, not a run's own annotate_check, wait for the pushers
        # still on code from before the shape rules (a pre-reset backfill cannot
        # sync until its commits push): see SHAPE_GRACE_UNTIL.
        allowed = {f: v for f, v in allowed.items() if f not in SHAPE_GRACE_FIELDS}
    observed = {}
    failed = False
    requeue, drift = (), {}
    if drift_out:
        import requeue_drift  # lazy: it imports this module
        requeue = tuple(requeue_drift.rule_fields())
    for text, seen, bad in check_all(paths, corpus, allowed, requeue):
        sys.stdout.write(text)
        if seen is not None:
            observed[seen[0]] = seen[1]
            for field, keys in (seen[2] if len(seen) > 2 else {}).items():
                drift.setdefault(field, {})[seen[0]] = keys
                print(f"{WARN_PREFIX}{seen[0]}: {len(keys)} {field} clue(s) past the allowance: queued for the burn")
        failed = failed or bad
    if drift_out:
        Path(drift_out).write_text(json.dumps(drift, indent=1) + "\n")
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
        moved = {f: sum(n for stem, n in allowed.get(f, {}).items()
                        if not shard or shard_of(stem, shard[1]) == shard[0])
                 - sum(c[f] for c in observed.values())
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
            # Not a failure: a shrink is the burn working. The nightly
            # tools/prereset_backfill.sh is the one writer of the file.
            print("backlog shrank (" + ", ".join(f"{f} -{n}" for f, n in moved.items() if n > 0)
                  + ") — not a failure; tools/prereset_backfill.sh records it tonight "
                    "with `python3 tools/validate_annotations.py --tighten`.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
