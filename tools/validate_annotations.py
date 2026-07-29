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

And one whole-puzzle check:
  - at most MAX_CRYPTIC_DEFINITIONS clues typed "cryptic definition"

Usage: python3 tools/validate_annotations.py [puzzle-number ...]
With no arguments, validates every puzzle that has at least one annotation.
Exits non-zero if any check fails.
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
    """Lowercase word list, with the (8) enumeration and punctuation dropped."""
    return re.findall(r"[a-z]+", re.sub(r"\([^)]*\)", " ", (s or "").lower()))


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


def is_plural(ans):
    """Is the answer really a plural, or does it just end in S? Checked against a
    real wordlist so PEANUTS (PEANUT) warns and CHAOS / TENNIS never do."""
    if not ans.endswith("S") or ans.endswith(("SS", "US", "IS")):
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
            if ans_letters not in letters(clue):
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

        check_coverage(tag, ann, clue, warnings)
        check_part_of_speech(tag, ann, warnings)
        low = (ann.get("walkthrough") or "").lower()
        for h in HEDGES:
            if h in low:
                errors.append(f"{tag}: walkthrough hedges with {h!r} — parse the chunk "
                              f"properly instead of excusing it (STYLE.md)")

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
    if argv:
        paths = [PUZZLE_DIR / f"{a}.js" for a in argv]
    else:
        paths = sorted(PUZZLE_DIR.glob("[0-9]*.js"))
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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
