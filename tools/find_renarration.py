#!/usr/bin/env python3
"""Find walkthroughs that re-narrate the blocks instead of adding to them.

A REVIEW TOOL, DELIBERATELY NOT A VALIDATOR CHECK.

The rule in annotate_prompt.md is that a walkthrough carries what the blocks
CANNOT show — the joke, the misdirection, the convention — and never restates
fragment -> letters, because the app already renders the blocks directly above
it. Measured on 2026-08-09 across the whole corpus: 202 of 689 walkthroughs name
at least one of their own letter chunks, and 76 name two or more.

76 sounded like a backlog worth gating on. Reading a sample says otherwise, and
the reason is worth writing down because it is the sort of check that looks
obviously right until you look at its output:

    1388 8D OCTOPUS  "OCT is the calendar abbreviation and OPUS the composer's
                      'work'"                                    <- the teaching
    1387 17D PREFACE "The official is a sports referee, tucked inside a stately
                      walk: P(REF)ACE."                          <- the defect

Both name two chunks. The first names them to teach two conventions a solver can
reuse forever; the second narrates an assembly the blocks already drew. No
lexical rule separates those, because the difference is what the sentence is FOR,
not which tokens it contains. Filtering on positional prepositions and excluding
convention language gets it to roughly half precision, which is not good enough
to fail a build or to feed a blind rewrite: the mixed cases are one bad clause
attached to a genuinely good sentence, and a model told to "fix" them will throw
the good half away with the bad.

So this prints candidates for a human or a model to READ, ranked worst-first, and
the rule itself is enforced where it can be enforced honestly: in the prompt, at
writing time, with both examples above in front of the annotator.

Usage:  python3 tools/find_renarration.py [puzzle-number ...]
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import puzzle_files, resolve_puzzle  # noqa: E402

CAPS = re.compile(r"\b[A-Z][A-Z’'-]{1,}\b")
# Assembly language: the walkthrough is placing pieces relative to one another,
# which is precisely the picture the blocks already render.
POSITIONAL = re.compile(
    r"\b(inside|around|round|in front|follows?|following|sits?|before|after|"
    r"precedes?|next to|side by side|within|wraps?|swallow\w*|contain\w*|"
    r"enclos\w*|goes? in|splits?|splitting|between|on top)\b", re.I)
# Convention language: the chunk is being named in order to TEACH it, which is
# the walkthrough doing its job. Not a defect, however many capitals it uses.
TEACHING = re.compile(
    r"\b(abbreviat\w*|staple\w*|worth banking|stands for|shorthand|standard|"
    r"convention\w*|vocabulary|crosswordese|every solver|symbol|"
    r"the setter\w* word)\b", re.I)


def load(path):
    s = open(path).read()
    i = s.index("{", s.index("CRYPTIC_PUZZLES["))
    return json.loads(s[i:s.rindex("}") + 1])


def chunks_of(ann):
    """Letter groups this annotation itself claims — blocks and pieces."""
    out = set()
    for b in ann.get("blocks") or []:
        g = (b.get("gives") or "").replace(" ", "").upper()
        if len(g) >= 2:
            out.add(g)
    for p in ann.get("pieces") or []:
        p = p.replace(" ", "").upper()
        if len(p) >= 2:
            out.add(p)
    return out


def scan(path):
    try:
        puz = load(path)
    except Exception:
        return []
    found = []
    for e in puz.get("entries", []):
        ann = e.get("annotation") or {}
        walk = ann.get("walkthrough")
        if not walk:
            continue
        answer = (ann.get("answer") or "").replace(" ", "").upper()
        owned = chunks_of(ann)
        named = {t.replace("’", "").replace("'", "").replace("-", "").upper()
                 for t in CAPS.findall(walk)}
        # The answer itself is not a chunk of itself, and another clue's answer
        # is a cross-reference rather than this clue's wordplay.
        hits = sorted(t for t in named if t in owned and t != answer)
        if len(hits) < 2:
            continue
        teaching = bool(TEACHING.search(walk))
        positional = bool(POSITIONAL.search(walk))
        # Worst first: assembly language and no attempt to teach anything.
        rank = 0 if (positional and not teaching) else 1 if positional else 2
        found.append((rank, os.path.basename(path)[:-3], e["id"], answer,
                      hits, walk))
    return found


def main(argv):
    if argv:
        paths = [str(resolve_puzzle(n)) for n in argv]
    else:
        paths = [str(p) for p in puzzle_files()]
    rows = [r for p in paths for r in scan(p)]
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    label = {0: "ASSEMBLY", 1: "MIXED", 2: "NAMES-ONLY"}
    for rank, puz, cid, answer, hits, walk in rows:
        print(f"[{label[rank]}] {puz} {cid} {answer}  names {', '.join(hits)}")
        print(f"    {walk}")
    print(f"\n{len(rows)} walkthroughs name two or more of their own chunks "
          f"across {len(paths)} puzzles.")
    for r in (0, 1, 2):
        print(f"  {label[r]:11} {sum(1 for x in rows if x[0] == r)}")
    print("\nRead them. ASSEMBLY is usually a real defect; NAMES-ONLY usually is "
          "not.\nNothing here fails a build — see the docstring for why.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
