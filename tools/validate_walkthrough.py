"""Walkthrough, surface and pun checks of validate_annotations.py: opener and closer budgets, hedges, filler words.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import re
from annotation import explanation

from validate_base import types_of

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


def check_two_pieces(tag, ann, errors):
    """Every word of a clue we wrote must be doing one of three jobs.

    Definition, wordplay (fodder or indicator), or joinery. Nothing else — and a
    block with an empty `gives` is the annotation saying out loud that a word is
    there for the surface alone. That is legitimate when ANNOTATING a published
    clue (30039 5A, 30040 16A and 30067 20D all carry one, and docs/STYLE.md's
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
            f"keep only what they cannot show (docs/STYLE.md, 'the blocks already told them')")


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
#: What to write when a derived field is empty: the run writes `def` and `wp`, never these keys.
MISSING_FIELD_FIX = {
    "definitions": " — the clue has no `def`: write the clue words that define the answer, as `def` "
                   "(two for a double definition). If the wordplay covers every clue word there is "
                   "none to write: the puzzle's preamble must define it (definedByPreamble)",
    "blocks": " — the wordplay gives no letters to show: write `wp` as an expression that builds the "
              "answer (a leaf [clue words]LETTERS for each piece), or a double definition (two `def`s, no `wp`)",
}
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