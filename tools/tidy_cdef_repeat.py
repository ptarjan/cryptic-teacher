#!/usr/bin/env python3
"""Rewrite cryptic definitions stored as several leaves, corpus-wide (wordplay.cdefRepeat).

    python3 tools/tidy_cdef_repeat.py puzzles/              # count, 10 examples per case, write nothing
    python3 tools/tidy_cdef_repeat.py puzzles/ --write      # rewrite in place, empty the allowance
    python3 tools/tidy_cdef_repeat.py puzzles/ --commit     # rewrite, then one commit

A cryptic definition is one cd([clue words]); validate_annotations counts every
extra leaf (CDEF_REPEAT). A clue stored as cd([a], [b]) is one of two things:

  double   the leaves cover separate stretches of the clue, so they are two
           definitions: the annotation becomes a double definition, in the form
           the corpus already has (`definitions` of two or more, each with the
           leaf's note as its `meaning`, and no `wordplay`);
  merged   the leaves overlap (the same clue words stored twice), or the clue
           cannot be a double definition (a preamble-defined clue, a clue that
           already has two definitions, a cd inside another op): the leaves join
           into ONE leaf over the clue words they span, with their notes joined.

Every other field (explanation, features, spelling, notes) is kept. A clue is
rewritten only if annotation.view() still builds from the result; one that does
not is left and counted. Re-runnable: a rewritten clue has nothing left to do.
The model-shaped clues in tools/data/authored_*_clues.json get the same
treatment (cd([a], [b]) becomes `def` of two and no `wp`).
"""
import argparse
import collections
import copy
import json
import os
import re
import subprocess
import sys

import annotation
import puzzle_schema
import validate_annotations as V

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find(clue, words, used):
    """First place `words` sits in `clue` clear of every span in `used`, else None."""
    for hay, needle in ((clue, words), (clue.casefold(), words.casefold())):
        i = hay.find(needle)
        while i != -1:
            if all(i + len(needle) <= s or i >= e for s, e in used):
                return i
            i = hay.find(needle, i + 1)
    return None


def locate(clue, parts):
    """[(start, end) per part, None where it has no free copy]: parts with an
    `at` first, then the longest first, as wordplay.locate does."""
    spans, used = [None] * len(parts), []
    for k, p in enumerate(parts):
        if isinstance(p.get("at"), int):
            spans[k] = (p["at"], p["at"] + len(p["words"]))
            used.append(spans[k])
    for k in sorted(range(len(parts)), key=lambda k: -len(parts[k]["words"])):
        if spans[k] is None:
            i = _find(clue, parts[k]["words"], used)
            if i is not None:
                spans[k] = (i, i + len(parts[k]["words"]))
                used.append(spans[k])
    return spans


def _first(clue, words):
    i = clue.find(words)
    return i if i != -1 else clue.casefold().find(words.casefold())


def joined_note(parts):
    notes = []
    for p in parts:
        n = p.get("note")
        if n and n not in notes:
            notes.append(n)
    return "; ".join(notes)


def plan(node, clue, ann, top):
    """('double', definitions) or ('merged', leaf) for one cd node with extra
    leaves, else None."""
    parts = node.get("parts") or []
    if not all(isinstance(p, dict) and "words" in p and "op" not in p for p in parts):
        return None
    spans = locate(clue, parts)
    defs = ann.get("definitions") or []
    # one clue whose text a gap splits (Printer's Devilry, a quotation with a
    # word missing): the halves are not two definitions, so never a double
    gap_split = re.search(r"gap falls|the gap is|Printer.s Devilry:",
                          json.dumps([parts, ann.get("explanation")]), re.I)
    if (top and not gap_split and None not in spans and len(parts) >= 2 and len(defs) <= 1
            and not ann.get("definedByPreamble") and not node.get("indicators")
            and set(node) <= {"op", "parts"}):
        new = []
        for k in sorted(range(len(parts)), key=lambda k: spans[k]):
            s, e = spans[k]
            d = {"text": clue[s:e], "at": s}
            if parts[k].get("note"):
                d["meaning"] = parts[k]["note"]
            new.append(d)
        if defs:
            for key, v in defs[0].items():
                if key not in ("text", "at", "note", "meaning"):
                    new[0][key] = v
            if "note" in defs[0]:
                new[0]["note"] = defs[0]["note"]
        # the schema's key order: text, at, note, meaning, then the rest
        first = ("text", "at", "note", "meaning")
        new = [{**{k: d[k] for k in first if k in d}, **{k: v for k, v in d.items() if k not in first}}
               for d in new]
        return "double", new
    got = list(spans)
    for k, s in enumerate(got):
        if s is None:
            i = _first(clue, parts[k]["words"])
            got[k] = (i, i + len(parts[k]["words"])) if i != -1 else None
    leaf = {}
    if all(g is not None for g in got):
        lo, hi = min(g[0] for g in got), max(g[1] for g in got)
        leaf["words"] = clue[lo:hi]
        if any("at" in p for p in parts):
            leaf["at"] = lo
    else:
        leaf["words"] = max(parts, key=lambda p: len(p["words"]))["words"]
    if joined_note(parts):
        leaf["note"] = joined_note(parts)
    return "merged", leaf


def tidy_ann(ann, entry, puzzle=None):
    """None if the clue has nothing to do, else (case, before, after) with case
    'double', 'merged' or 'failed' (left as it was)."""
    tree = ann.get("wordplay")
    if not V.cdef_repeats(tree):
        return None
    clue = entry["clue"]["text"]
    before = copy.deepcopy(ann)
    done = []

    def go(node, top):
        if node.get("op") == "cryptic" and not node.get("unchecked") and len(node.get("parts") or []) > 1:
            r = plan(node, clue, ann, top)
            if r is None:
                return
            kind, out = r
            done.append(kind)
            if kind == "double":
                ann["definitions"] = out
                del ann["wordplay"]
            else:
                node["parts"] = [out]
            return
        for p in node.get("parts") or []:
            if isinstance(p, dict):
                go(p, False)

    go(tree, True)
    if not done or V.cdef_repeats(ann.get("wordplay")):
        ann.clear()
        ann.update(before)
        return ("failed", before, before)
    try:
        annotation.view(ann, entry, puzzle)
    except Exception:
        after = copy.deepcopy(ann)
        ann.clear()
        ann.update(before)
        return ("failed", before, after)
    return (done[0], before, copy.deepcopy(ann))


def tidy_authored(path, write):
    """The model-shaped clues: cd([a], [b]) -> a double definition (`def` of two, no `wp`)."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    n = 0
    for c in data.values():
        a = c.get("annotation") if isinstance(c, dict) else None
        m = a and re.fullmatch(r"cd\(\[(.+?)\], \[(.+?)\]\)", a.get("wp") or "")
        if not m:
            continue
        x, y = m.groups()
        notes = a.get("notes") or {}
        a["def"] = [x, y]
        del a["wp"]
        new = {x: notes.get(x, ""), y: notes.get(y, "")}
        # a note on the whole clue (about the ?) goes with the first sense
        for t, v in notes.items():
            if t not in (x, y):
                new[x] = (new[x] + "; " if new[x] else "") + v
        a["notes"] = {k: v for k, v in new.items() if v}
        n += 1
    if n and write:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return n


def short(ann):
    d = [x.get("text") for x in ann.get("definitions") or []]
    w = ann.get("wordplay")
    return f"defs={d} wordplay={json.dumps(w, ensure_ascii=False) if w else None}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--examples", type=int, default=10)
    a = ap.parse_args()
    write = a.write or a.commit
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(a.root) for f in fs
                   if f.endswith(".json") and not f.startswith("."))
    cnt, puzzles, ex = collections.Counter(), collections.defaultdict(set), collections.defaultdict(list)
    left = {}
    for i, path in enumerate(files, 1):
        with open(path, encoding="utf-8") as fh:
            puzzle = json.load(fh)
        pid = os.path.basename(path)[:-5]
        changed = False
        for _, entry, ann in puzzle_schema.annotations(puzzle):
            r = tidy_ann(ann, entry, puzzle)
            if not r:
                continue
            case, before, after = r
            cnt[case] += 1
            puzzles[case].add(pid)
            if len(ex[case]) < a.examples:
                ex[case].append(f"{pid} {entry['clue']['text']!r}\n    before {short(before)}\n    after  {short(after)}")
            if case == "failed":
                left[pid] = left.get(pid, 0) + V.cdef_repeats(before.get("wordplay"))
            else:
                changed = True
        if changed and write:
            part = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.part")
            with open(part, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n")
            os.replace(part, path)
        if i % 5000 == 0:
            print(f"cdef: {i}/{len(files)} files", file=sys.stderr, flush=True)
    for case in ("double", "merged", "failed"):
        print(f"== {case}: {cnt[case]} clues in {len(puzzles[case])} puzzles")
        for e in ex[case]:
            print("  " + e)
    data_dir = os.path.join(REPO, "tools", "data")
    authored = [os.path.join(data_dir, f) for f in sorted(os.listdir(data_dir))
                if f.startswith("authored_") and f.endswith("_clues.json")]
    na = sum(tidy_authored(p, write) for p in authored)
    print(f"== authored: {na} clues to double definitions")
    if write:
        bl = json.loads(V.BACKLOG_PATH.read_text())
        bl["wordplay.cdefRepeat"] = dict(sorted(left.items(), key=V._sort_key))
        V.BACKLOG_PATH.write_text(json.dumps(bl, indent=1) + "\n")
    if not a.commit:
        return
    body = (f"Cryptic definitions stored as several leaves: {cnt['double']} become double definitions, "
            f"{cnt['merged']} merge into one leaf\n\n"
            f"tools/tidy_cdef_repeat.py over {len(files)} files. Where the leaves of a cd([a], [b]) cover "
            f"separate stretches of the clue, the clue is a double definition: the annotation now says so "
            f"(`definitions` of two, each leaf's note its `meaning`), the form double definitions already "
            f"take. Where the leaves overlap (the same clue words stored twice), or the clue cannot be a "
            f"double definition, they merge into one leaf with the notes joined. Explanations, features and "
            f"every other field are kept. {cnt['double']} double, {cnt['merged']} merged, {cnt['failed']} left. "
            f"The wordplay.cdefRepeat allowances (and authored-1's) are gone, as is the authored A001 "
            f"clues' split cd.\n\nA schema migration, exempt from one commit per puzzle. The old text is in "
            f"this commit's parent.\n")
    trailer = subprocess.run([sys.executable, os.path.join(REPO, "tools", "provenance.py"), "trailer"],
                             capture_output=True, text=True).stdout.strip()
    if trailer:
        body += "\n" + trailer + "\n"
    paths = [os.path.relpath(os.path.abspath(a.root), REPO), os.path.relpath(str(V.BACKLOG_PATH), REPO)] + \
        [os.path.relpath(p, REPO) for p in authored]
    subprocess.run(["git", "-C", REPO, "add", "--"] + paths, check=True)
    subprocess.run(["git", "-C", REPO, "commit", "-q", "-F", "-"], input=body, text=True, check=True)
    print(subprocess.run(["git", "-C", REPO, "log", "-1", "--format=committed: %h %s"],
                         capture_output=True, text=True).stdout.strip())


if __name__ == "__main__":
    main()
