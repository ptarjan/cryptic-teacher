#!/usr/bin/env python3
"""Measure how many clue words and marks file_archive_org_puzzles.py misreads.

    python3 tools/measure_archive_org_ocr.py              # every hand-checked edition
    python3 tools/measure_archive_org_ocr.py --split heldout
    python3 tools/measure_archive_org_ocr.py -v           # each misread clue

tools/data/archive_org_ocr_gold.json holds clues transcribed by hand off the
scans, each edition marked "tune" (used to choose the voting rules) or
"heldout" (never looked at while tuning; Paul's 2% bar is judged on these).
Editions with "series": "listener" are Saturday Listeners, read by
tools/archive_org_listener.py and split "listener" / "listener-heldout";
"series": "jumbo" ones are Saturday Jumbos, read by tools/archive_org_jumbo.py
and split "jumbo" / "jumbo-heldout"; "series": "ft" ones are Financial Times
cryptics (FinancialTimes<year>UKEnglish items), read by the same filer and
split "ft" / "ft-heldout"; "series": "guardian" ones are Guardian cryptics
(TheGuardian<year>UKEnglish items), split "guardian" / "guardian-heldout".
Each edition is read as the filer reads it (no solution grid; with the
desktop's VLM when it answers, tools/vlm_reader.py, so set VLM_READER_URL=
to measure without it), and every
clue it files non-blank is scored against the transcription: the misreads
are the word-level edit distance between the two lists of words and voted
marks (file_archive_org_puzzles.marked, words compared without case), over
the transcription's words and marks in those clues. A clue filed blank is
no misread; the share of clues filed is reported beside the rate, and so
is the count of puzzles with every clue filed: only those go into
puzzles/times, so that count is the measure of what the filer delivers.
The blank-inclusive rate counts every transcribed word and mark of a blank
clue as misread, so filling a blank with a wrong guess and blanking it
cost the same; it is the rate Paul's 2% bar is judged on.
"""
import argparse
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import archive_org_jumbo as jumbo
import archive_org_listener as listener
import file_archive_org_puzzles as fa
import ocr_clues

GOLD = TOOLS / "data" / "archive_org_ocr_gold.json"


def units(text):
    return [w.lower() for w in ocr_clues.marked(ocr_clues.clean(text))]


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
    out = {"tokens": 0, "misreads": 0, "clues": len(gold), "filed": 0, "blank": 0,
           "bad": []}
    for lid, want in gold.items():
        got = read.get(lid) or ""
        if not got.strip():
            out["blank"] += len(units(want))
            continue
        out["filed"] += 1
        a, b = units(want), units(got)
        out["tokens"] += len(a)
        d = distance(a, b)
        out["misreads"] += d
        if d:
            out["bad"].append((lid, want, got))
    return out


def read(edition, number, cache=fa.CACHE, series="times"):
    """{light: clue text} as the filer files edition's puzzle `number`."""
    d = cache / edition
    if series == "listener":
        found = listener.scan(d)
        for hit in found["puzzles"]:
            if hit["number"] == number:
                verdict, laid = listener.read(d, hit, found["solutions"])
                return {lid: t for lid, (t, _, _) in (laid or {}).items()}, verdict
        return {}, {"refused": f"no heading for Listener No {number}"}
    if series == "jumbo":
        found = jumbo.scan(d)
        for hit in found["puzzles"]:
            if hit["number"] == number:
                verdict, puzzle = jumbo.read(d, found, hit, {})
                if puzzle is None:
                    return {}, verdict
                return {f"{e['number']}-{e['direction']}": (e.get("clue") or {}).get("text", "")
                        for e in puzzle["entries"]}, verdict
        return {}, {"refused": f"no heading for Jumbo No {number}"}
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
    ap.add_argument("--split", choices=("tune", "heldout", "listener", "listener-heldout", "jumbo", "jumbo-heldout",
                                        "ft", "ft-heldout", "guardian", "guardian-heldout"))
    ap.add_argument("--gold", type=Path, default=GOLD)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    total = {"tokens": 0, "misreads": 0, "clues": 0, "filed": 0, "blank": 0}
    complete = {"tokens": 0, "misreads": 0}
    puzzles = whole = 0
    for ed in json.loads(args.gold.read_text()):
        if args.split and ed["split"] != args.split:
            continue
        got, verdict = read(ed["edition"], ed["number"], series=ed.get("series", "times"))
        s = score(ed["clues"], got)
        for k in total:
            total[k] += s[k]
        rate = s["misreads"] / max(s["tokens"], 1)
        puzzles += 1
        # A light the reading lost is a blank too.
        full = bool(got) and all((got.get(lid) or "").strip() for lid in ed["clues"]) \
            and all((t or "").strip() for t in got.values())
        whole += full
        if full:
            complete["tokens"] += s["tokens"]
            complete["misreads"] += s["misreads"]
        print(f"{ed.get('series', 'times')}-{ed['number']} {ed['split']:7s} {s['misreads']:3d}/{s['tokens']:4d} "
              f"{rate:6.1%}  filed {s['filed']}/{s['clues']}  "
              f"with blanks {(s['misreads'] + s['blank']) / max(s['tokens'] + s['blank'], 1):6.1%}"
              + ("" if got else f"  {verdict.get('refused') or verdict.get('pending')}"))
        if args.verbose:
            for lid, want, have in s["bad"]:
                print(f"    {lid:10s} {want}\n    {'':10s} {have}")
    rate = total["misreads"] / max(total["tokens"], 1)
    print(f"total {total['misreads']}/{total['tokens']} = {rate:.2%} misread; "
          f"filed {total['filed']}/{total['clues']} clues; "
          f"{whole}/{puzzles} puzzles have every clue")
    wrong, seen = total["misreads"] + total["blank"], total["tokens"] + total["blank"]
    print(f"with blanks counted as misread: {wrong}/{seen} = {wrong / max(seen, 1):.2%}; "
          f"complete puzzles alone: {complete['misreads']}/{complete['tokens']} = "
          f"{complete['misreads'] / max(complete['tokens'], 1):.2%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
