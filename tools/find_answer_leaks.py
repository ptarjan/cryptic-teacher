#!/usr/bin/env python3
"""Find block notes that say the answer out loud.

The building blocks are the rung before the walkthrough, so a learner reads them
having deliberately not bought the solve. `app.js` refuses to render a `gives`
that equals the answer, which makes the letters safe; the prose is not, and a
note like "pulses are the crop family beans belong to" hands PULSE over.

Matching is word-run based rather than substring: the answer's letters have to
line up with whole words of the note, optionally carrying a short inflection, so
"run-in" is caught inside "a run-in is a quarrel" and OSLO inside "n(O SLO)venian"
while a short answer is not caught inside an unrelated longer word.

  python3 tools/find_answer_leaks.py            # ranked summary, whole corpus
  python3 tools/find_answer_leaks.py 30104      # just this puzzle, clue by clue
  python3 tools/find_answer_leaks.py --json     # per-clue targets for a rewrite

Name a puzzle rather than grepping the corpus run for its number: annotation
sessions were piping the whole-corpus summary through `grep -i <num>` roughly
once a session, which matches the filename and prints the ranking line, not the
notes that are wrong.
"""

import argparse
import collections
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import clue_types  # noqa: E402
from fetch_puzzle import (  # noqa: E402 — one glob, one reader, one id resolver
    puzzle_files, read_puzzle_file, resolve_puzzle)
from groups import entry_id  # noqa: E402

# An inflection the same word can carry without becoming a different word. Longer
# tails are a different word and not a leak: "cutter" does not give away CUT.
INFLECTIONS = ("", "s", "es", "ed", "d", "ing", "n", "r", "rs", "ers")


def letters(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def says(text, answer):
    """Does `text` contain `answer` as a run of whole words?"""
    target = letters(answer)
    if len(target) < 3:
        return False
    words = [letters(w) for w in re.split(r"[^A-Za-z]+", text or "") if letters(w)]
    for i in range(len(words)):
        run = ""
        for j in range(i, min(i + len(target), len(words))):
            run += words[j]
            if len(run) > len(target) + 3:
                break
            if run.startswith(target) and run[len(target):] in INFLECTIONS:
                return True
    return False


# A function word every sentence needs cannot be kept out of a note, and naming
# it hands over nothing: THE of THE TORTURED POETS DEPARTMENT, AND of SLAP AND
# TICKLE.
FUNCTION_WORDS = {"the", "and", "for", "but", "nor", "yet", "not", "from", "with", "its"}


def names(answer, lights=()):
    """What a block note must not name: the clue's answer and, on a linked
    answer, each light's own solution, since a light is an answer in the grid."""
    out = [answer] if answer else []
    for sol in lights:
        if (sol and letters(sol) not in FUNCTION_WORDS
                and letters(sol) not in {letters(a) for a in out}):
            out.append(sol)
    return out


def named(text, answer, lights=()):
    """The first of names(answer, lights) that `text` says, else None."""
    return next((n for n in names(answer, lights) if says(text, n)), None)


def light_solutions(entry, by_id):
    """The solutions of `entry`'s linked lights, in group order; () unlinked."""
    return [(by_id.get(gid) or {}).get("solution") for gid in entry.get("group") or ()]


# unname() rewrites a block note that names its answer, when the rewrite needs no
# judgement, so annotate_check applies it instead of spending a turn on
# check_block_notes_dont_name_the_answer. Each rule below takes the answer out
# of one clause and keeps the rest verbatim; a note no rule clears is left for
# the validator to reject.

# "a grating is a grid of metal bars", "to junk = to throw away": the answer as
# the subject, the gloss after it.
OPENER = re.compile(
    r"^\s*(?:(?:a|an|the|to)\s+)?(?P<subject>[A-Za-z'’ -]+?)\s*"
    r"(?:\s(?:is|are|was|means|can mean)\s+(?:also\s+)?|[=:—–]\s*|\s-\s+)(?P<rest>.+)$",
    re.DOTALL)
# "its middle", "a mean one": a gloss that leans on the subject it lost.
DANGLING = re.compile(r"^(?:its|their|his|her|one's)\b|\bone\s*[.!]?$")
# "the pick of the bunch is the cream": the answer as the complement.
TAIL = re.compile(
    r"^(?P<head>.+?)\s+(?:is|are|=|means)\s+(?:(?:to|a|an|the|one's|its|their)\s+)?"
    r"(?P<ans>[A-Za-z' -]+?)(?:\s+(?:it|them|one|out|up|off|down))?\s*[.!]?$", re.DOTALL)
LOOSE_END = re.compile(r"\b(?:he|she|it|they|you|we|I|and|or|so|that|which|who)\s*$", re.IGNORECASE)
# "read backwards gives RASH", "C sounds like SEA": the verb that hands over the
# assembled word, which can hand over "the answer" instead.
GIVES = re.compile(
    r"(?:\b(?:gives?|giving|makes?|making|spells?|spelling|produces?|yields?|leaves?|leaving"
    r"|becomes?|turns? into|sounds? (?:just |exactly )?(?:like|the same as)|said like"
    r"|pronounced like|reads? \w+ as|to get|to form|forming|to make|it is|you get|we get)"
    r"|->|→|=>|=)\s*(?P<ans>[A-Za-z' -]+?)\s*[.!]?$")
ALIKE = re.compile(r"\b(?:and|with)\s+(?P<ans>[A-Za-z' -]+?)\s+(?=sound|are pronounced|rhyme)")
# "fin(AL PHA)se", "chame-LEO-n", "p ART IS TE mpting": a hidden word displayed
# in its fodder, which becomes the clue's own words and where the letters start.
DISPLAY = re.compile(
    r"(?P<pre>[A-Za-z]*)(?:\((?P<a>[^()]+)\)|-(?P<b>[A-Z][A-Za-z ,'.]*?)-(?=[a-z])"
    r"|(?<=[a-z]) (?P<c>[A-Z]+(?: [A-Z]+)*) (?=[a-z]))(?P<post>[a-z]*)")
CLAUSE_BREAK = re.compile(r"(\s*[;:]\s+|\s+[—–]\s+|\s+-\s+|;\s*)")


def _words(s):
    return len(re.findall(r"[A-Za-z]+", s))


# "to worst someone is to beat them": words a subject can carry and still be the
# answer alone. "William Temple was ..." is about the man, and keeps its subject.
FILLER = {"someone", "something", "somebody", "sth", "sb", "one", "one's", "a", "an", "the",
          "up", "out", "off", "on", "in", "down", "against", "at", "for", "with", "it", "them"}


def _bare(subject, answer):
    """Is `subject` the answer word, give or take an inflection and FILLER words?"""
    left = subject.lower()
    for w in re.findall(r"[A-Za-z]+", answer.lower()):
        left = re.sub(rf"\b{w}\w{{0,3}}\b", " ", left, count=1)
    extra = [w for w in re.findall(r"[a-z']+", left) if w not in FILLER]
    return len(letters(" ".join(extra))) <= 3


def _span(clue, run):
    """(the whole words of `clue` holding the letter run `run`, letters before it)."""
    idx = [i for i, ch in enumerate(clue) if ch.isalpha()]
    flat = "".join(clue[i] for i in idx).lower()
    at = flat.find(run)
    if not run or at < 0 or flat.find(run, at + 1) >= 0:
        return None
    lo, hi = idx[at], idx[at + len(run) - 1] + 1
    while lo > 0 and clue[lo - 1].isalpha():
        lo -= 1
    while hi < len(clue) and clue[hi].isalpha():
        hi += 1
    return clue[lo:hi], sum(ch.isalpha() for ch in clue[lo:idx[at]])


def _undisplay(clause, answer, clue):
    for m in DISPLAY.finditer(clause):
        inner = m["a"] or m["b"] or m["c"]
        if (letters(inner) != letters(answer) or not (m["pre"] or m["post"])
                or re.match(r"['’\w]", clause[m.end():m.end() + 1])):
            continue
        found = _span(clue, letters(m["pre"] + inner + m["post"]))
        if found:
            span, before = found
            start = before + len(letters(m["pre"])) + 1
            end = start + len(letters(answer)) - 1
            return f"{clause[:m.start()]}letters {start}-{end} of '{span}'{clause[m.end():]}"
    return None


def _unname_clause(clause, answer, whole, clue):
    """`clause` without the answer in it, or None to drop the clause."""
    m = OPENER.match(clause)
    if (m and says(m["subject"], answer) and not says(m["rest"], answer)
            and _bare(m["subject"], answer) and not DANGLING.search(m["rest"])):
        return m["rest"]
    # "the answer" is only true of a block that gives the whole answer.
    for pat in (GIVES, ALIKE) if whole else ():
        m = pat.search(clause)
        if m and letters(m["ans"]) == letters(answer):
            return clause[:m.start("ans")] + "the answer" + clause[m.end("ans"):]
    m = TAIL.match(clause)
    if (m and letters(m["ans"]) == letters(answer) and not re.search(r"[,;]", m["head"])
            and _words(m["head"]) <= 6 and not LOOSE_END.search(m["head"])
            and not re.search(r"(?:^|\s)['\"‘“]", m["head"])):
        return m["head"]
    fixed = _undisplay(clause, answer, clue)
    if fixed is None and ", " in clause:
        # Only a trailing run of comma clauses goes: a leading one holds the subject.
        subs = clause.split(", ")
        while subs and says(subs[-1], answer):
            subs.pop()
        fixed = ", ".join(subs) if 0 < len(subs) <= clause.count(", ") else None
    return fixed


def unname(note, answer, gives=None, clue=""):
    """`note` rewritten so it no longer names `answer`, or None when that takes
    judgement. `gives` is the block's letters, `clue` the clue's text."""
    if not isinstance(note, str) or not says(note, answer):
        return None
    whole = gives is None or letters(gives) == letters(answer)
    parts = CLAUSE_BREAK.split(note)
    kept = []
    for clause, sep in zip(parts[0::2], [""] + parts[1::2]):
        fixed = clause if not says(clause, answer) else _unname_clause(clause, answer, whole, clue)
        if fixed is not None:
            kept.append([sep, fixed])
        elif sep.strip() == ":" and len(kept) > 1 and _words(kept[-1][1]) <= 2:
            kept.pop()  # "inside: R-EARL-IGHT" loses its label with its display
    if not kept:
        return None
    kept[0][0] = ""
    new = "".join(s + c for s, c in kept).strip(" ;:,-—–")
    # What is left must still be a note: not a stub, and most of what was written.
    if (says(new, answer) or _words(new) < 2 or len(letters(new)) < 6
            or len(letters(new)) < 0.4 * len(letters(note))):
        return None
    return new[0].upper() + new[1:] if note[:1].isupper() else new


def leaks(only=()):
    paths = [resolve_puzzle(n) for n in only] if only else puzzle_files()
    for path in paths:
        puzzle = read_puzzle_file(path)
        by_id = {entry_id(e): e for e in puzzle.get("entries", [])}
        for entry in puzzle.get("entries", []):
            ann = entry.get("annotation") or {}
            answer = ann.get("answer")
            if not answer:
                continue
            lights = light_solutions(entry, by_id)
            bad = [b for b in (ann.get("blocks") or []) if named(b.get("note"), answer, lights)]
            if bad:
                yield {
                    "file": path.name,
                    "entry": entry_id(entry),
                    "clue": entry["clue"].get("text"),
                    "type": ann.get("type"),
                    "answer": answer,
                    "notes": [{"clueFragment": b.get("clueFragment"), "note": b.get("note"),
                               "names": named(b.get("note"), answer, lights)}
                              for b in bad],
                }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("puzzle", nargs="*",
                    help="limit to these puzzles; default is the whole corpus")
    ap.add_argument("--json", action="store_true", help="emit per-clue targets")
    args = ap.parse_args()

    found = list(leaks(args.puzzle))
    if args.json:
        json.dump(found, sys.stdout, indent=1)
        return 1 if found else 0

    if args.puzzle:
        # A one-puzzle run is an annotation run checking its own work, and the
        # corpus ranking below answers a question it did not ask. Say the thing
        # it needs: which clues, and what the offending note actually says.
        if not found:
            print(f"no block note names its answer in {' '.join(args.puzzle)}")
            return 0
        for f in found:
            print(f"{f['file']} {f['entry']} ({f['answer']}, {clue_types.labels(f['type'])})")
            for n in f["notes"]:
                print(f"    {n['clueFragment']} (names {n['names']}): {n['note']}")
        return 1

    by_file = collections.Counter(f["file"] for f in found)
    by_type = collections.Counter(clue_types.labels(f["type"]) for f in found)
    print(f"{len(found)} clue(s) in {len(by_file)} puzzle(s) name the answer in a block note.\n")
    print("worst puzzles:")
    for name, n in by_file.most_common(12):
        print(f"  {n:4d}  {name}")
    print("\nby type:")
    for name, n in by_type.most_common(10):
        print(f"  {n:4d}  {name}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
