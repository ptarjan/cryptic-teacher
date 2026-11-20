#!/usr/bin/env python3
"""File answers a person read by eye off a paper's printed solution grid.

    python3 tools/hand_answers.py answers.txt          # check only
    python3 tools/hand_answers.py --apply answers.txt  # write
    python3 tools/hand_answers.py --apply -            # lines on stdin

Each line is "<puzzle id> <light> <ANSWER>", e.g. "times-1234 14A MARSHALL". The light is the clue
number and A (across) or D (down); blank lines and "#" comments are skipped. A line is refused,
and nothing of it written, unless the answer is letters only, as long as the light, agrees with
every letter its crossings already hold, and the light is blank (a held answer is replaced only
with --replace). A filled light is marked in the file's solutions.hand ({entry id: date}): the
print's answer, certain, which no reread, repair or merge changes or drops
(file_archive_org_puzzles._merge_answers and improves, repair_fetched's blankers). The file's
origin stays as it was; a model-solved file's solutions.printed takes the answer too.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

import provenance
import puzzle_integrity
import puzzle_paths
from fetch_puzzle import read_puzzle_file, write_puzzle_file
from groups import entry_id

LINE = re.compile(r"^(?P<id>[a-z]+-[\w.-]+)\s+(?P<num>\d+)\s*(?P<dir>[ADad]|across|down)\s+(?P<word>[A-Za-z][A-Za-z '\-]*)$", re.I)


def parse(text):
    """[(puzzle id, number, direction, ANSWER)] of the lines of `text`; ValueError on a bad line."""
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = LINE.match(line)
        if not m:
            raise ValueError(f"line {n}: {raw!r} is not '<puzzle id> <light> <ANSWER>'")
        d = "across" if m["dir"].lower() in ("a", "across") else "down"
        out.append((m["id"].lower(), int(m["num"]), d, re.sub(r"[^A-Z]", "", m["word"].upper())))
    return out


def cells(e):
    x, y, across = e["position"]["x"], e["position"]["y"], e["direction"] == "across"
    return [(x + i * across, y + i * (not across)) for i in range(e["length"])]


def fill(puzzle, number, direction, word, replace=False, today=None):
    """Put `word` in the light in place and mark it solutions.hand; the refusal as a string, else None."""
    light = next((e for e in puzzle["entries"] if e["number"] == number and e["direction"] == direction), None)
    if light is None:
        return f"no {number} {direction} in {puzzle['id']}"
    if len(word) != light["length"]:
        return f"{number} {direction} is {light['length']} long, {word} is {len(word)}"
    held = {}
    for e in puzzle["entries"]:
        if e is not light and e.get("solution") and len(e["solution"]) == e["length"]:
            held.update(zip(cells(e), e["solution"].upper()))
    clash = [(i, held[rc], ch) for i, (rc, ch) in enumerate(zip(cells(light), word)) if held.get(rc, ch) != ch]
    if clash:
        i, was, ch = clash[0]
        return f"{word} puts {ch} where a crossing holds {was} (letter {i + 1})"
    was = (light.get("solution") or "").strip()
    if was and was != word and not replace:
        return f"{number} {direction} already holds {was} (--replace to take {word})"
    lid = entry_id(light)
    if was != word:
        light["solution"] = word
        light.pop("annotation", None)
    solutions = puzzle.setdefault("solutions", {})
    solutions.setdefault("hand", {})[lid] = today or datetime.date.today().isoformat()
    listed = solutions.get("partial")
    if isinstance(listed, list):
        left = [i for i in listed if i != lid]
        if left:
            solutions["partial"] = left
        else:
            del solutions["partial"]
    if "model" in provenance.solution_detail(puzzle):
        import file_archive_org_puzzles as archive
        archive.sync_printed(puzzle, {lid: word})
    return None


def apply(rows, write=False, replace=False):
    """Fill `rows` (parse's); {"done": [...], "refused": [(row, why)]}. Each puzzle is written once, only
    if every line of it was taken and the file's provenance findings gain none."""
    by_puzzle = {}
    for row in rows:
        by_puzzle.setdefault(row[0], []).append(row)
    out = {"done": [], "refused": []}
    for pid, items in by_puzzle.items():
        path = puzzle_paths.find(pid)
        if path is None:
            out["refused"] += [(r, f"{pid} is not filed") for r in items]
            continue
        puzzle = read_puzzle_file(path)
        before = set(provenance.check(puzzle))
        failed = False
        for r in items:
            why = fill(puzzle, r[1], r[2], r[3], replace)
            if why:
                out["refused"].append((r, why))
                failed = True
        if failed:
            out["refused"] += [(r, "another line of its puzzle was refused") for r in items
                               if not any(r == x[0] for x in out["refused"])]
            continue
        gained = set(provenance.check(puzzle)) - before
        if gained:
            out["refused"] += [(r, "provenance: " + "; ".join(sorted(gained))) for r in items]
            continue
        if write:
            try:
                write_puzzle_file(path, puzzle)
            except puzzle_integrity.RefusedWrite as err:
                out["refused"] += [(r, f"write refused: {err}") for r in items]
                continue
        out["done"] += items
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", help="lines of '<puzzle id> <light> <ANSWER>', or - for stdin")
    ap.add_argument("--apply", action="store_true", help="write the files (default: check only)")
    ap.add_argument("--replace", action="store_true", help="take a hand answer over a held one")
    args = ap.parse_args(argv)
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
    try:
        rows = parse(text)
    except ValueError as err:
        print(f"hand_answers: {err}", file=sys.stderr)
        return 2
    got = apply(rows, write=args.apply, replace=args.replace)
    verb = "filed" if args.apply else "would file"
    for pid, n, d, word in got["done"]:
        print(f"hand_answers: {verb} {pid} {n} {d} {word}")
    for (pid, n, d, word), why in got["refused"]:
        print(f"hand_answers: REFUSED {pid} {n} {d} {word}: {why}", file=sys.stderr)
    return 1 if got["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
