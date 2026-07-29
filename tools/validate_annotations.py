#!/usr/bin/env python3
"""Validate clue annotations in puzzles/*.js.

Checks, for every annotated entry:
  - annotation has type, definition, walkthrough, answer, blocks
  - every " + "-joined part of `type` is in the controlled vocabulary (TYPE_PARTS)
  - answer letters match the grid solution (group-aware for linked entries)
  - definition / definition2 / every indicator is an exact substring of the clue
  - anagram fodder letters match the answer letters (multiset)
  - charade/container "pieces" concatenate exactly to the answer letters
  - hidden answers actually occur in the clue's letters
  - subAnagrams are letter-for-letter anagrams; subReversals reverse correctly
  - linkedTo targets exist and cover their group

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


def letters(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def words_of(s):
    """Lowercase word list, with the (8) enumeration and punctuation dropped."""
    return re.findall(r"[a-z]+", re.sub(r"\([^)]*\)", " ", (s or "").lower()))


def check_coverage(tag, ann, clue, warnings):
    """Every content word of the clue must be claimed by the parse.

    A clue word that is in neither the definition, an indicator, nor a block
    fragment is wordplay the annotation silently dropped (feedback 2026-07-29:
    30067 13A never accounted for 'state' = CAL, and the walkthrough hedged
    instead of admitting it)."""
    claimed = set()
    for src in [ann.get("definition"), ann.get("definition2")]:
        claimed |= set(words_of(src))
    for ind in ann.get("indicators", []):
        claimed |= set(words_of(ind))
    for b in ann.get("blocks", []):
        claimed |= set(words_of(b.get("clueFragment")))
    loose = [w for w in words_of(clue) if w not in claimed and w not in FILLER_WORDS]
    if loose:
        warnings.append(
            f"{tag}: clue word(s) {', '.join(sorted(set(loose)))} belong to neither the "
            f"definition, an indicator, nor a block — wordplay may be unaccounted for")


def check_part_of_speech(tag, ann, warnings):
    """The definition must be substitutable for the answer, which means their
    inflections agree: a plural answer needs a plural definition, an -ing answer
    an -ing definition (feedback 2026-07-29 — "the part of speech needs to be
    right"). Only the mechanical, unambiguous endings are checked here; the
    judgement call lives in STYLE.md and tools/annotate_prompt.md."""
    ans = letters(ann.get("answer"))
    dwords = words_of(ann.get("definition"))
    if not ans or not dwords:
        return
    ends = lambda sufs: any(w.endswith(sufs) for w in dwords)
    # A long definition is usually a descriptive phrase ("About to go off perhaps"
    # = TICKING), where the -ing test says nothing; only short ones are meaningful.
    if ans.endswith("ING") and len(ans) > 5 and len(dwords) <= 2 and not ends(("ing",)):
        warnings.append(f"{tag}: answer ends -ING but no word in the definition does "
                        f"({ann.get('definition')!r}) — check the part of speech")
    elif ans.endswith("S") and len(ans) > 4 and not ans.endswith(("SS", "US", "IS", "OUS")) \
            and not ends(("s",)):
        warnings.append(f"{tag}: answer looks plural but the definition "
                        f"({ann.get('definition')!r}) is not — check the part of speech")
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
