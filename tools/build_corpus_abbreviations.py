#!/usr/bin/env python3
"""The abbreviations our own annotations attest, counted over the corpus.

    nice -n 19 python3 tools/build_corpus_abbreviations.py          # rewrite OUT
    nice -n 19 python3 tools/build_corpus_abbreviations.py --check  # exit 1 if OUT is stale

Paul 10-13: "For my d is deserter don't we have lots of data as to what is
common abbreviation and what isn't?" The dictionary (Wiktionary and
Wikipedia's crossword list, tools/data/lexicons/abbreviations.json) misses
some of the commonest conventions there are: US for american, N for name,
H for hot. Our ~52k annotated puzzles record every one of them, so the
corpus decides too.

A leaf (clue words -> letters, no op) whose note calls it an
abbreviation ("D is a recorded abbreviation for deserted") is one
attestation of that pair. A pair is standard when it is attested in at
least MIN_PUZZLES puzzles, from at least MIN_SERIES series and MIN_SETTERS
setters, so one setter's habit or one run's mis-annotation is not a
convention. No share of the pair's leaves need say "abbreviation": P for
quiet, R for queen and CE for church are mostly glossed as "piano",
"Regina", "Church of England", and at 2026-10-13 every pair over the counts
whose notes seldom say it was a real convention. OUT holds the pairs with
their counts, as provenance; build_abbreviations.table() reads it beside the
dictionary.

Keys follow the table's conventions: the clue words as the leaf wrote them,
lower case, each inflection its own sense (the dictionary lists "runs" and
"times" beside "run" and "time"). A span the table never holds is not
counted: one led by an article, a number or an abbreviation indicator ("a
year", "two seconds", "little energy": the gloss belongs to the bare word)
or a possessive ("fellow's"; "setter's" is MY, so the 's cannot just go).

Rerunning is stable: a leaf with no note whose pair the table holds counts
as noted (its note was stripped, or never written), so a pair once in OUT
stays when tools/strip_abbreviation_notes.py removes the notes it rests on;
its counts may grow, never its absence of evidence.

Reads puzzles/ only (a stats pass, not a corpus job: it writes no puzzle).
Rerun it after a backfill to refresh the counts; the leaf notes it reads
are kept for exactly these pairs until tools/strip_abbreviation_notes.py
removes them, and a stripped leaf is still counted (is_abbreviation()).
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

import puzzle_paths
import puzzle_schema

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "data" / "lexicons" / "abbreviations_corpus.json"

#: Thresholds for "standard". Chosen on the 2026-10-13 corpus (51,994
#: annotated-format puzzles): every pair at or above them read as a real convention; below
#: them, one-setter or one-series habits (S for sex: 17 puzzles, one setter)
#: and thin evidence (D for god, 8; O for on and G for girl, 3 series) start
#: to mix in.
MIN_PUZZLES = 10
MIN_SERIES = 4
MIN_SETTERS = 5
#: Abbreviations are short; a longer `gives` is a word, however it is glossed.
MAX_LETTERS = 4

#: First words of a span whose gloss belongs to the rest of it.
LEADERS = frozenset({"a", "an", "the", "two", "little", "short", "small"})
POSSESSIVE = re.compile(r"['’]s$")
#: A note that calls its leaf an abbreviation.
NOTED = re.compile(r"abbreviat", re.IGNORECASE)


def letters_of(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def leaves(puzzle):
    """Every (words, gives, note) leaf of a puzzle's annotations."""
    for _, _, ann in puzzle_schema.annotations(puzzle):
        stack = [ann.get("wordplay")] if isinstance(ann.get("wordplay"), dict) else []
        while stack:
            node = stack.pop()
            stack += [p for p in node.get("parts") or [] if isinstance(p, dict)]
            if "op" not in node and node.get("words") and isinstance(node.get("gives"), str):
                yield node["words"], node["gives"], node.get("note") or ""


def candidate(words, gives):
    """The pair key for a leaf that could be an abbreviation, or None."""
    if not gives or len(gives) > MAX_LETTERS or not gives.isupper():
        return None
    if letters_of(gives) == letters_of(words) or len(letters_of(words)) <= len(gives):
        return None
    words = " ".join(words.lower().split())
    if words.split()[0] in LEADERS or POSSESSIVE.search(words):
        return None
    return gives, words


def count(files, table_pairs=frozenset()):
    """{(letters, words): stats} over the puzzle files. A leaf counts as
    noted when its note says abbreviation, or when it has no note and the
    table already explains it (its note was stripped or never written)."""
    stats = collections.defaultdict(lambda: {"puzzles": set(), "noted": set(), "series": set(),
                                             "setters": set(), "leaves": 0, "notedLeaves": 0})
    for path in files:
        try:
            puzzle = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pid = puzzle.get("id") or Path(path).stem
        series = Path(path).parent.parent.name
        setter = " ".join((puzzle.get("setter") or "").lower().split()) or "?"
        for words, gives, note in leaves(puzzle):
            key = candidate(words, gives)
            if key is None:
                continue
            s = stats[key]
            s["puzzles"].add(pid)
            s["leaves"] += 1
            if NOTED.search(note) or (not note and (letters_of(key[1]), gives) in table_pairs):
                s["notedLeaves"] += 1
                s["noted"].add(pid)
                s["series"].add(series)
                s["setters"].add(setter)
    return stats


def summary(s):
    return {"puzzles": len(s["noted"]), "series": len(s["series"]), "setters": len(s["setters"]),
            "noted": round(s["notedLeaves"] / s["leaves"], 3), "leaves": s["leaves"]}


def standard(row):
    return (row["puzzles"] >= MIN_PUZZLES and row["series"] >= MIN_SERIES
            and row["setters"] >= MIN_SETTERS)


def build(stats):
    """OUT's content: letters -> {words: counts}, the pairs standard() passes."""
    out = {}
    for (gives, words), s in stats.items():
        row = summary(s)
        if standard(row):
            out.setdefault(gives, {})[words] = row
    return {k: dict(sorted(out[k].items())) for k in sorted(out)}


def render(data):
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if OUT differs from a rebuild")
    ap.add_argument("--dump", metavar="PATH", help="also write every candidate's counts here (for tuning)")
    args = ap.parse_args(argv)
    import annotation
    stats = count(puzzle_paths.puzzle_files(), annotation.abbreviation_pairs())
    if args.dump:
        rows = [{"gives": g, "words": w, **summary(s)} for (g, w), s in stats.items() if s["noted"]]
        Path(args.dump).write_text(json.dumps(rows, ensure_ascii=False) + "\n", encoding="utf-8")
    text = render(build(stats))
    if args.check:
        stale = not OUT.exists() or OUT.read_text(encoding="utf-8") != text
        print(f"{OUT.name}: {'stale' if stale else 'current'}")
        return 1 if stale else 0
    OUT.write_text(text, encoding="utf-8")
    print(f"{OUT.name}: {sum(map(len, json.loads(text).values()))} pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
