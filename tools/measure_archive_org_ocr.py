#!/usr/bin/env python3
"""Measure how many clue words and marks file_archive_org_puzzles.py misreads.

    python3 tools/measure_archive_org_ocr.py              # every hand-checked edition
    python3 tools/measure_archive_org_ocr.py --split heldout
    python3 tools/measure_archive_org_ocr.py -v           # each misread clue

tools/data/archive_org_ocr_gold.json holds clues transcribed by hand off the
scans, each edition marked "tune" (used to choose the voting rules) or
"heldout" (never looked at while tuning; Paul's 2% bar is judged on these).
Each edition is read as the filer reads it (no solution grid), and every
clue it files non-blank is scored against the transcription: the misreads
are the word-level edit distance between the two lists of words and voted
marks (file_archive_org_puzzles.marked, words compared without case), over
the transcription's words and marks in those clues. A clue filed blank is
no misread; the share of clues filed is reported beside the rate.
"""
import argparse
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import file_archive_org_puzzles as fa

GOLD = TOOLS / "data" / "archive_org_ocr_gold.json"


def units(text):
    return [w.lower() for w in fa.marked(fa.clean(text))]


def distance(a, b):
    """Word-level Levenshtein distance between two token lists."""
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def score(gold, read):
    """{"tokens", "misreads", "clues", "filed", "bad": [(light, gold, read)]}
    for one edition's transcription against the filer's {light: text}."""
    out = {"tokens": 0, "misreads": 0, "clues": len(gold), "filed": 0, "bad": []}
    for lid, want in gold.items():
        got = read.get(lid) or ""
        if not got.strip():
            continue
        out["filed"] += 1
        a, b = units(want), units(got)
        out["tokens"] += len(a)
        d = distance(a, b)
        out["misreads"] += d
        if d:
            out["bad"].append((lid, want, got))
    return out


def read(edition, number, cache=fa.CACHE):
    """{light: clue text} as the filer files edition's puzzle `number`."""
    d = cache / edition
    found = fa.scan(d)
    for hit in found["puzzles"]:
        if hit["number"] == number:
            verdict, puzzle = fa.read_puzzle(d, found, hit, {})
            if puzzle is None:
                return {}, verdict
            return {f"{e['number']}-{e['direction']}": (e.get("clue") or {}).get("text", "")
                    for e in puzzle["entries"]}, verdict
    return {}, {"refused": f"no heading for No {number}"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", choices=("tune", "heldout"))
    ap.add_argument("--gold", type=Path, default=GOLD)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    total = {"tokens": 0, "misreads": 0, "clues": 0, "filed": 0}
    for ed in json.loads(args.gold.read_text()):
        if args.split and ed["split"] != args.split:
            continue
        got, verdict = read(ed["edition"], ed["number"])
        s = score(ed["clues"], got)
        for k in total:
            total[k] += s[k]
        rate = s["misreads"] / max(s["tokens"], 1)
        print(f"times-{ed['number']} {ed['split']:7s} {s['misreads']:3d}/{s['tokens']:4d} "
              f"{rate:6.1%}  filed {s['filed']}/{s['clues']}"
              + ("" if got else f"  {verdict.get('refused') or verdict.get('pending')}"))
        if args.verbose:
            for lid, want, have in s["bad"]:
                print(f"    {lid:10s} {want}\n    {'':10s} {have}")
    rate = total["misreads"] / max(total["tokens"], 1)
    print(f"total {total['misreads']}/{total['tokens']} = {rate:.2%} misread; "
          f"filed {total['filed']}/{total['clues']} clues")
    return 0


if __name__ == "__main__":
    sys.exit(main())
