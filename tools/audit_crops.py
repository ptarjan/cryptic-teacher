#!/usr/bin/env python3
"""Dry-run audit of the archive filer's clue-column crops, per year.

    audit_crops.py GaleTimes1949UKEnglish GaleTimes1960UKEnglish ... [-n 4] [--seed 1]

Samples N editions of each archive item, reads each OCR-only (no VLM, nothing
filed, OCR cache in a scratch directory) and prints one row per item: how
many pages the crop check (crop_window.poor) passed, how many only passed
once the gutter fallback moved the window, how many were refused, and, where
the page's puzzle is already filed, how many of its clues the OCR agrees
with. A layout year whose crop is wrong shows up here in minutes, not as a
fall in the filing rate.
"""
import argparse
import json
import random
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import file_archive_org_puzzles as fa  # noqa: E402

FILED = Path(__file__).resolve().parent.parent / "puzzles" / "times"


def words(t):
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def filed_clues(year, number):
    f = FILED / year / f"times-{number}.json"
    if not f.exists():
        return None
    return {f"{x['number']}-{x['direction']}": x["clue"]["text"] for x in json.loads(f.read_text())["entries"]}


def audit_page(d):
    found = fa.scan(d)
    hit = found["puzzles"][0]
    verdict, puzzle = fa.read_page(d, found, hit, {}, False)
    row = {"refused": bool(verdict.get("refused")), "poor": fa.crop_window.poor(verdict),
           "moved": verdict.get("cropFrom") == "gutter"}
    truth = filed_clues(d.name[:4], verdict.get("number", hit["number"]))
    if truth and puzzle:
        got = {f"{x['number']}-{x['direction']}": (x["clue"] or {}).get("text", "") for x in puzzle["entries"]}
        row["agree"] = sum(1 for k, s in truth.items() if words(got.get(k)) == words(s))
        row["of"] = len(truth)
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("items", nargs="+")
    ap.add_argument("-n", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    fa.CROPS = Path(tempfile.mkdtemp(prefix="audit-crops-"))
    rng = random.Random(args.seed)
    print(f"{'item':32} pages  pass  moved  refused  agree")
    for item in args.items:
        eds = sorted(p for p in (fa.CACHE / item).iterdir() if p.is_dir())
        rows = []
        for d in rng.sample(eds, min(args.n, len(eds))):
            try:
                rows.append(audit_page(d))
            except Exception as e:  # a page that crashes is a finding, not a stop
                rows.append({"refused": True, "poor": True, "moved": False, "error": repr(e)[:60]})
        ag, of = sum(r.get("agree", 0) for r in rows), sum(r.get("of", 0) for r in rows)
        print(f"{item:32} {len(rows):5} {sum(not r['poor'] for r in rows):5} {sum(r['moved'] for r in rows):6} "
              f"{sum(r['refused'] for r in rows):8}  {f'{ag}/{of}' if of else '-'}", flush=True)


if __name__ == "__main__":
    main()
