#!/usr/bin/env python3
"""Add "setter" to filed puzzles that lack it, from the title bylines the cached OCR already holds.

  byline_backfill.py [--apply] ledger.jsonl [...]   Gale Independent / Gale FT rows (a grep of filed.jsonl)
  byline_backfill.py [--apply] --tls                 TLS ("TLS Crossword 946 by Tantalus") page words

Only where the byline is unambiguous: the page's RapidOCR en5 and ch reads must name the same word; a TLS number's
readings must all name one setter, one that prints for two or more numbers (a misread stands alone). Without
--apply it only counts. Read-time data only: no image is opened and no scan key is touched."""
import collections
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import byline

CROPS = Path(os.path.expanduser("~/.cache/archive_org_crops/titles"))
TLS_PAGES = Path(os.path.expanduser("~/.cache/gale_listener/ocr"))
SERIES_OF = {"galeindependent": "independent", "galeft": "ftcryptic"}


def page_words(item, date, leaf, reader):
    for suffix in ("", ".gf"):
        f = CROPS / f"{item}_{date}_{leaf}_page.{reader}{suffix}.json"
        if f.exists():
            return json.loads(f.read_text())["words"]
    return None


def agreed_name(item, date, leaf, box):
    """The setter en5 and ch both read round `box` of a Gale page, or None."""
    names = []
    for reader in ("en5", "ch"):
        words = page_words(item, date, leaf, reader)
        if words is None:
            return None
        names.append(byline.near_title(words, box, right=200))
    return names[0] if names[0] and names[0] == names[1] else None


def ledger_names(paths):
    """{puzzle id: setter} over ledger rows (the newest row of an edition last)."""
    out = {}
    for path in paths:
        for line in open(path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            scan = r.get("scan") or {}
            item = scan.get("item", "")
            m = re.match(r"Gale(Independent|FT)\d{4}UKEnglish$", item)
            if not m:
                continue
            series = "independent" if m.group(1) == "Independent" else "ftcryptic"
            for v in r.get("verdicts") or ():
                pid = v.get("id")
                hit = next((p for p in scan.get("puzzles", ()) if p["number"] == v.get("number")), None)
                if not pid or not hit or byline.is_unprinted(series, scan["date"]):
                    continue
                name = agreed_name(item, scan["date"], hit["leaf"], hit["box"])
                if name:
                    out[pid] = name
    return out


TLS_TITLE = re.compile(r"TLS\s+cross\s?word\s*(?:No\.?)?\s*(\d{3,4})\b\W{0,3}(?:(?i:by)\s+([A-Z][A-Za-z]+))?", re.I)


def tls_names():
    """{puzzle id: setter} from the TLS page words: every title reading of a number must agree."""
    readings = collections.defaultdict(set)
    for f in TLS_PAGES.iterdir():
        if ".page." not in f.name:
            continue
        try:
            text = " ".join(w[4] for w in json.loads(f.read_text()))
        except (ValueError, IndexError):
            continue
        for m in TLS_TITLE.finditer(text):
            n = int(m.group(1))
            name = m.group(2) and byline.name_in("by " + m.group(2).title())
            if name or n >= 894:
                readings[n].add(name)
    by_name = collections.defaultdict(set)
    for n, names in readings.items():
        for name in names - {None}:
            by_name[name].add(n)
    known = {name for name, ns in by_name.items() if len(ns) >= 2}
    return {f"tls-{n}": next(iter(names - {None}))
            for n, names in readings.items()
            if len(names - {None}) == 1 and next(iter(names - {None})) in known
            and not byline.is_unprinted("tls", "2011-09-16")}


def write(pid, name, apply):
    """Whether puzzle `pid`'s file lacks a setter (and gets `name` when apply)."""
    import puzzle_paths
    path = puzzle_paths.find(pid)
    if not path:
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("setter"):
        return False
    if apply:
        out = {}
        for k, v in data.items():
            out[k] = v
            if k == "date":
                out["setter"] = name
        out.setdefault("setter", name)
        path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def main(argv):
    apply = "--apply" in argv
    args = [a for a in argv if not a.startswith("--")]
    names = tls_names() if "--tls" in argv else ledger_names(args)
    filled = sum(write(pid, name, apply) for pid, name in sorted(names.items()))
    print(f"{len(names)} bylines read, {filled} files {'filled' if apply else 'would be filled'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
