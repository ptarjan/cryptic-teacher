"""Checks of validate_annotations.py that compare an annotation with the blog's own parse of the clue.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import re
import clue_types
import definitions
from fetch_puzzle import blog_facts_for, load_source_table
from groups import entry_id

from validate_base import types_of, letters
from validate_anagram import multiset_diff
from validate_definition import LINKING_WORDS

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