#!/usr/bin/env python3
"""Strip the leaf notes that only restate the abbreviation table, corpus-wide.

    python3 tools/strip_abbreviation_notes.py puzzles/              # count, write nothing
    python3 tools/strip_abbreviation_notes.py puzzles/ --write      # rewrite in place
    python3 tools/strip_abbreviation_notes.py puzzles/ --commit     # rewrite, then one commit

A leaf whose clue words -> letters pair is in
tools/build_abbreviations.table() needs no note: annotation.view() shows
"W is a standard abbreviation for with" from the table. A stored note that
says only that (annotation.restates_abbreviation) is a derivable field, which
annotation.from_model drops and validate_annotations refuses (a run's new
ones now; every file once this commit sets ABBREVIATION_NOTES_STRIPPED). This
removes the ones already filed: one schema-migration commit, exempt from one commit per
puzzle (as f59e109ad6). A corpus job: run it with nothing else writing puzzles/
(corpus_queue.py status idle, the burn paused). Each file is rewritten whole
(a .part renamed over it) in the shape it was read, so a kill loses nothing
and the same command resumes: a stripped file has nothing left to strip.
"""
import argparse
import collections
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import annotation  # noqa: E402
import puzzle_schema  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def strip_puzzle(puzzle):
    """Notes dropped from every annotation of the puzzle, in place: a list of
    (where, words, gives, note)."""
    out = []
    for where, _, ann in puzzle_schema.annotations(puzzle):
        stack = [ann.get("wordplay")] if isinstance(ann.get("wordplay"), dict) else []
        while stack:
            node = stack.pop()
            if annotation.restates_abbreviation(node):
                out.append((where, node["words"], node["gives"], node.pop("note")))
            stack += [p for p in node.get("parts") or [] if isinstance(p, dict)]
    return out


def strip_file(path, write):
    with open(path, encoding="utf-8") as fh:
        puzzle = json.load(fh)
    dropped = strip_puzzle(puzzle)
    if dropped and write:
        part = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.part")
        with open(part, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n")
        os.replace(part, path)
    return dropped


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="the puzzles/ folder")
    ap.add_argument("--write", action="store_true", help="rewrite the files in place")
    ap.add_argument("--commit", action="store_true", help="--write, then make the one migration commit")
    a = ap.parse_args()
    write = a.write or a.commit
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(a.root) for f in fs
                   if f.endswith(".json") and not f.startswith("."))
    notes, puzzles, words = 0, 0, collections.Counter()
    for i, path in enumerate(files, 1):
        dropped = strip_file(path, write)
        if dropped:
            puzzles += 1
            notes += len(dropped)
            words.update(f"{w.lower()} {g}" for _, w, g, _ in dropped)
        if i % 5000 == 0:
            print(f"strip: {i}/{len(files)} files, {notes} notes", file=sys.stderr, flush=True)
    subject = f"Strip abbreviation notes the table derives: {notes} notes in {puzzles} puzzles"
    print(subject)
    print("commonest: " + ", ".join(f"{k} ({n})" for k, n in words.most_common(12)))
    if not a.commit or not notes:
        return
    body = (f"{subject}\n\nA leaf whose clue words -> letters pair is in "
            f"tools/build_abbreviations.table() stores no note that only restates it: "
            f"annotation.view() shows \"W is a standard abbreviation for with\" from the "
            f"table. tools/strip_abbreviation_notes.py over {len(files)} files. A schema "
            f"migration, exempt from one commit per puzzle (as f59e109ad6). The old text "
            f"is in this commit's parent.\n\nCommonest pairs: "
            + ", ".join(f"{k} ({n})" for k, n in words.most_common(20)) + "\n")
    trailer = subprocess.run([sys.executable, os.path.join(REPO, "tools", "provenance.py"), "trailer"],
                             capture_output=True, text=True).stdout.strip()
    if trailer:
        body += "\n" + trailer + "\n"
    # From this commit on every file is held to the rule, not only a run's new notes.
    va = os.path.join(REPO, "tools", "validate_annotations.py")
    with open(va, encoding="utf-8") as fh:
        text = fh.read()
    with open(va, "w", encoding="utf-8") as fh:
        fh.write(text.replace("ABBREVIATION_NOTES_STRIPPED = False", "ABBREVIATION_NOTES_STRIPPED = True", 1))
    subprocess.run(["git", "-C", REPO, "add", "--", os.path.relpath(os.path.abspath(a.root), REPO),
                    os.path.relpath(va, REPO)], check=True)
    subprocess.run(["git", "-C", REPO, "commit", "-q", "-F", "-"], input=body, text=True, check=True)
    print(subprocess.run(["git", "-C", REPO, "log", "-1", "--format=committed: %h %s"],
                         capture_output=True, text=True).stdout.strip())


if __name__ == "__main__":
    main()
