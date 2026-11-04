"""Coverage, number and part-of-speech feature checks of validate_annotations.py.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import re
import definitions

from validate_base import indicator_texts, WORDS, letters, _whole_word, words_of
from validate_walkthrough import FILLER_WORDS

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


#: A number written out in words (NINETEENEIGHTYTWO), letters only: nothing but number words.
SPELLED_NUMBER = re.compile(
    r"(?:ZERO|NOUGHT|OH|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|THIRTEEN|FOURTEEN|"
    r"FIFTEEN|SIXTEEN|SEVENTEEN|EIGHTEEN|NINETEEN|TWENTY|THIRTY|FORTY|FIFTY|SIXTY|SEVENTY|EIGHTY|NINETY|"
    r"HUNDRED|THOUSAND|MILLION|AND)+")


def spelled_numbers(ann):
    """The letters of each numeral a hidden word reads written out: hid<in>([1982]NINETEENEIGHTYTWO)
    hides NEIGH in nineteEN EIGHty (toughie-336 4d). Only a hid() leaf whose words hold digits and whose
    `gives` is made of number words counts, so the spelling is the annotation's own, stated, and the
    clue's printed letters are not widened for any other leaf."""
    out, stack = [], [ann.get("wordplay")]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        stack += node.get("parts") or []
        leaf = (node.get("parts") or [None])[0]
        if node.get("op") == "hidden" and isinstance(leaf, dict) and "op" not in leaf \
                and re.search(r"\d", str(leaf.get("words"))) and SPELLED_NUMBER.fullmatch(letters(leaf.get("gives"))):
            out.append(letters(leaf["gives"]))
    return out


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
    judgement call lives in docs/STYLE.md and tools/annotate_prompt.md.

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