#!/usr/bin/env python3
"""Settle the one conflict a promotion races into, for tools/push_puzzle_commit.sh.

    python3 tools/resolve_promotion_conflict.py PARENT BASE COMMIT TREE PATH...

Promoting a clues-only puzzle (tools/apply_solution.py) deletes
clues_only/<series>/<id>.json and adds puzzles/<series>/<year>/<id>.json. The
book reader (tools/acquire_books.sh) may meanwhile re-read the same leaf and
re-write the clues-only file. Replaying either commit onto the other is then a
modify/delete conflict that git cannot settle, and the promoted puzzle never
reaches origin. Both directions are handled:

  * COMMIT promotes, BASE (origin) re-read: the deletion stands.
  * COMMIT re-reads, BASE already promoted: the re-read is dropped, so it
    never resurrects the clues-only copy of a filed puzzle.

Either way the re-read's clue text is carried into the promoted puzzle, clue by
clue (lights matched by direction and printed order, the order the clues-only
file holds them in), only where the puzzle's clue is still the pre-promotion
reading (PARENT's clues-only file): a clue the annotator corrected keeps its
correction. A clue whose annotation names fragments the new text no longer
holds keeps the old text too. Everything not carried is reported on stderr.

TREE is merge-tree's conflicted result; PATH... its conflicted paths. Prints
the settled tree, or exits 1 with nothing on stdout when any path is not this
conflict (the caller then refuses the commit as before).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

CLUES_ONLY = re.compile(r"clues_only/([^/]+)/([^/]+)\.json")
DIRECTIONS = ("across", "down")


def git(*args, stdin=None, env=None):
    return subprocess.run(("git",) + args, input=stdin, capture_output=True,
                          text=True, check=True, env=env).stdout


def blob(rev, path):
    """The text of `path` at `rev`, or None when it is not there."""
    try:
        return git("cat-file", "-p", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return None


def promoted_path(rev, series, pid):
    """The puzzles/ path holding `pid` at `rev`, or None."""
    out = git("ls-tree", "-r", "--name-only", rev, "--", f"puzzles/{series}/")
    hits = [p for p in out.splitlines() if p.rsplit("/", 1)[-1] == f"{pid}.json"]
    return hits[0] if len(hits) == 1 else None


def fragments(annotation):
    """[(text, at)] of every clue fragment the annotation names (`at` None
    when it gives no offset)."""
    out = []
    ann = annotation or {}
    out += [(d.get("text"), d.get("at")) for d in ann.get("definitions") or []]
    out += [(i.get("text"), None) for i in ann.get("indicators") or []]
    out += [(b.get("clueFragment"), None) for b in ann.get("blocks") or []]
    out += [(w, None) for w in ann.get("linkWords") or []]
    assembly = ann.get("assembly") or {}
    out += [(a.get("fodder"), None) for a in assembly.get("anagrams") or []]
    return [(t, at) for t, at in out if isinstance(t, str) and t]


def fits(annotation, old, new):
    """Does every fragment the annotation found in `old` still sit in `new`?"""
    for text, at in fragments(annotation):
        if isinstance(at, int) and old[at:at + len(text)] == text:
            if new[at:at + len(text)] != text:
                return False
        elif text in old and text not in new:
            return False
    return True


def carry(puzzle_text, old_text, new_text, pid):
    """(puzzle text with the re-read's clues carried in, notes)."""
    import annotation
    puzzle = json.loads(puzzle_text)
    old, new = json.loads(old_text), json.loads(new_text)
    # Fragments are read from the derived view; edits go to the raw entries.
    viewed = annotation.view_puzzle(puzzle)
    ann_of = {id(e): v.get("annotation") or e.get("annotation")
              for e, v in zip(puzzle.get("entries", []), viewed.get("entries", []))}
    notes = []
    for direction in DIRECTIONS:
        entries = sorted((e for e in puzzle.get("entries", [])
                          if e.get("direction") == direction),
                         key=lambda e: e.get("number", 0))
        was = (old.get("clues") or {}).get(direction) or []
        now = (new.get("clues") or {}).get(direction) or []
        if not (len(entries) == len(was) == len(now)):
            notes.append(f"{direction}: {len(entries)} lights filed, {len(was)} read "
                         f"before, {len(now)} re-read; kept every filed clue")
            continue
        for entry, before, after in zip(entries, was, now):
            o = (before.get("clue") or {}).get("text")
            n = (after.get("clue") or {}).get("text")
            clue = entry.get("clue") or {}
            p = clue.get("text")
            label = f"{entry.get('number')}{direction[0]}"
            if n == o or n == p or not isinstance(n, str):
                continue
            if p != o:
                notes.append(f"{label}: kept the filed {p!r}; re-read {n!r}")
            elif not fits(ann_of.get(id(entry)), o, n):
                notes.append(f"{label}: kept {p!r}, its annotation does not fit "
                             f"the re-read {n!r}")
            else:
                clue["text"] = n
                notes.append(f"{label}: carried the re-read {n!r} over {p!r}")
    out = json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n"
    if json.dumps(json.loads(puzzle_text), indent=1, ensure_ascii=False) + "\n" != puzzle_text:
        return puzzle_text, [f"{pid}: puzzle file not in the house layout; "
                             f"kept it whole, dropped: " + "; ".join(notes)]
    return out, notes


def main(argv):
    parent, base, commit, tree, *paths = argv
    if not paths:
        return 1
    removals, rewrites = [], {}
    for path in paths:
        m = CLUES_ONLY.fullmatch(path)
        if not m:
            return 1
        series, pid = m.groups()
        old = blob(parent, path)
        on_base, on_commit = blob(base, path), blob(commit, path)
        if old is None:
            return 1
        if on_commit is None and on_base is not None:     # we promote, origin re-read
            promoted, new = promoted_path(commit, series, pid), on_base
        elif on_base is None and on_commit is not None:   # we re-read, origin promoted
            promoted, new = promoted_path(base, series, pid), on_commit
        else:
            return 1
        if promoted is None or blob(tree, promoted) is None:
            return 1
        current = rewrites.get(promoted) or blob(tree, promoted)
        try:
            text, notes = carry(current, old, new, pid)
        except (ValueError, KeyError, TypeError) as err:
            text, notes = current, [f"could not compare the readings ({err}); kept the filed clues"]
        for note in notes:
            print(f"resolve_promotion_conflict: {pid}: {note}", file=sys.stderr)
        print(f"resolve_promotion_conflict: {pid}: kept {promoted}, dropped {path}",
              file=sys.stderr)
        removals.append(path)
        if text != current:
            rewrites[promoted] = text
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
        git("read-tree", tree, env=env)
        for path in removals:
            git("update-index", "--force-remove", "--", path, env=env)
        for path, text in rewrites.items():
            sha = git("hash-object", "-w", "--stdin", stdin=text).strip()
            git("update-index", "--cacheinfo", f"100644,{sha},{path}", env=env)
        print(git("write-tree", env=env).strip())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except subprocess.CalledProcessError as err:
        print(f"resolve_promotion_conflict: {err} {err.stderr}", file=sys.stderr)
        sys.exit(1)
