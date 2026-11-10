#!/usr/bin/env python3
"""Shortlist real clues to teach each clue type with, for /learn/ (tools/tutorial.html).

    python3 tools/learn_examples.py                 # puzzles/ on disk
    python3 tools/learn_examples.py --rev HEAD      # puzzle files read out of git
    python3 tools/learn_examples.py --type anagram --top 40

A lesson example has to do two jobs: show the device plainly, and read as a
sentence you might actually say. The rule below does the first in code and
ranks for the second; a person reads the shortlist and picks, and each pick
is recorded with its reason in tools/data/learn_examples.json.

The rule, per clue:
  - explained by this site (an `annotation`, not a blog's marked-up facts), so
    the lesson can quote a definition, indicator and pieces we stand behind;
  - device-pure: every op in its wordplay is the one type being taught (a
    charade may join plain pieces; an anagram may gather fodder words), so the
    example shows one idea, not three;
  - short (at most MAX_WORDS words) and self-contained: no cross-reference to
    another clue ("See 14", "13 down"), no leading or trailing ellipsis;
  - ranked: a clue a blog commenter named as a favourite first, then the
    surface grade tools/favourite_grading.py gave it, then the site's own
    feature notes (aptDefinition, misdirectedWord: a surface built to mislead),
    then fewer words.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import annotation
from annotation import OP_TYPE

MAX_WORDS = 9
CROSS_REF = re.compile(r"\b\d+\b|\b(?:across|down)\b|^\s*(?:\.\.\.|…)|(?:\.\.\.|…)\s*$", re.IGNORECASE)
GRADES = ROOT / "tools" / "data" / "favourite_grading"


def grades():
    """{(puzzle id, entry id): (voted favourite, surface grade)}."""
    key = json.loads((GRADES / "key.json").read_text(encoding="utf-8"))
    surface = {}
    for f in sorted((GRADES / "scores").glob("*.json")):
        for row in json.loads(f.read_text(encoding="utf-8")):
            surface[row["label"]] = row.get("surface") or 0
    return {(v["puzzle"], v["entry"]): (bool(v["voted"]), surface.get(k, 0)) for k, v in key.items()}


def ops(node, parent=None):
    """The clue types of every op under node, skipping joins that only gather
    pieces (annotation._types's rule, without its wordplay import)."""
    out = set()
    if not isinstance(node, dict):
        return out
    op = node.get("op")
    gather = op in ("charade", "repeat") and not node.get("indicators") and (
        (parent or {}).get("op") in ("anagram", "container", "reversal", "hidden", "homophone"))
    if op and not gather:
        out.add(OP_TYPE.get(op, op))
    for p in node.get("parts") or ():
        out |= ops(p, node)
    return out


def clue_type(ann):
    """The one type a clue teaches, or None when it mixes devices."""
    wp = ann.get("wordplay")
    defs = ann.get("definitions") or []
    if ann.get("andLit") or ann.get("type") == "and_lit":
        return "and_lit"
    if not wp:
        return "double_definition" if len(defs) >= 2 else None
    found = ops(wp)
    if not found and len(defs) >= 2:
        return "double_definition"
    if len(found) == 1:
        return found.pop()
    return None


def pool(extra=()):
    """The puzzles a shortlist reads: every one holding a clue
    tools/favourite_grading.py graded (blog commenters' favourites and their
    neighbours), plus any named. Not the whole corpus: that is CI's to scan."""
    key = json.loads((GRADES / "key.json").read_text(encoding="utf-8"))
    return sorted({v["puzzle"] for v in key.values()} | set(extra))


def read_puzzles(ids, rev=None, root=ROOT):
    """Each named puzzle file, from a checkout's puzzles/ or out of git at rev
    (a sparse checkout has no puzzles/ on disk)."""
    listing = subprocess.run(["git", "ls-tree", "-r", "--name-only", rev or "HEAD", "--", "puzzles"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    path_of = {Path(n).stem: n for n in listing if n.endswith(".json")}
    for pid in ids:
        name = path_of.get(pid)
        if not name:
            continue
        if rev:
            text = subprocess.run(["git", "show", f"{rev}:{name}"], check=False, cwd=ROOT,
                                  capture_output=True, text=True).stdout
        else:
            f = Path(root) / name
            text = f.read_text(encoding="utf-8") if f.exists() else ""
        if '"annotation"' in text:
            yield json.loads(text)


def candidates(puzzles, want=None):
    graded = grades()
    for puz in puzzles:
        for e in puz.get("entries") or ():
            ann = e.get("annotation")
            text = ((e.get("clue") or {}).get("text") or "").strip()
            if not ann or ann.get("fromBlog") or not text or CROSS_REF.search(text):
                continue
            words = text.split()
            if len(words) > MAX_WORDS:
                continue
            t = clue_type(ann)
            if not t or (want and t != want):
                continue
            eid = f"{e['number']}-{e['direction']}"
            voted, surface = graded.get((puz["id"], eid), (False, 0))
            feats = ann.get("features") or {}
            score = (voted, surface, bool(feats.get("aptDefinition")),
                     bool(feats.get("misdirectedWord")), -len(words))
            yield t, score, {
                "puzzle": puz["id"], "entry": eid, "clue": text,
                "enumeration": (e.get("clue") or {}).get("enumeration"),
                "answer": annotation.whole_answer(e, puz) or None, "voted": voted, "surface": surface,
                "gloss": (ann.get("explanation") or {}).get("surface"),
            }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rev", help="read puzzle files out of git at this revision")
    ap.add_argument("--root", default=str(ROOT), help="a checkout whose puzzles/ to read")
    ap.add_argument("--puzzles", nargs="*", default=(), help="more puzzle ids to read")
    ap.add_argument("--type", help="one clue type only")
    ap.add_argument("--top", type=int, default=25, help="candidates kept per type")
    args = ap.parse_args(argv)
    src = read_puzzles(pool(args.puzzles), args.rev, args.root)
    best = {}
    for t, score, row in candidates(src, args.type):
        best.setdefault(t, []).append((score, row))
    out = {t: [row for _, row in sorted(rows, key=lambda sr: sr[0], reverse=True)[:args.top]]
           for t, rows in sorted(best.items())}
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
