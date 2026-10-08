"""A reprint is filed as its original, never as a puzzle of its own.

A series whose tools/series.py meta names `reprints` prints another series'
puzzle under the same number later (the Globe and Mail's No N is the Times
Quick Cryptic No N, about seven weeks on), and a file whose source names
`reprintOf` is a known copy of that puzzle. Either way the original's id is
known, so the corpus holds the original alone: the reprint's own number and
print date go on the original as source.reprintedIn, which the index lists
under the reprinting paper as a pointer to the original.

puzzle_integrity.check_reprint refuses a reprint file, so no filer can write
one. PENDING lists the reprint files held before the rule, each to be folded
into its original; it only shrinks.
"""
import json
from pathlib import Path

import series as series_meta

TOOLS = Path(__file__).resolve().parent
PENDING_PATH = TOOLS / "data" / "reprints_pending.json"

#: {reprinting series: the series it reprints, number for number}.
REPRINTS = {key: meta["reprints"] for key, meta in series_meta.SERIES.items()
            if meta.get("reprints")}


def pending():
    """The held reprint files not yet folded into their originals."""
    return frozenset(json.loads(PENDING_PATH.read_text(encoding="utf-8"))["ids"])


def original_of(puzzle):
    """The id of the puzzle `puzzle` reprints, or None where it is an original
    or its original is not identified."""
    series = series_meta.parse_id(puzzle["id"])[0]
    if series in REPRINTS:
        return series_meta.puzzle_id(REPRINTS[series], puzzle["number"])
    return (puzzle.get("source") or {}).get("reprintOf")


def with_print(original, series, number, date):
    """`original` with the print of it in `series` as No `number` on `date`
    recorded in source.reprintedIn, one entry per series and number."""
    prints = [p for p in (original.get("source") or {}).get("reprintedIn") or []
              if (p["series"], p["number"]) != (series, number)]
    prints.append({"series": series, "number": number, "date": date})
    prints.sort(key=lambda p: (p["date"], p["series"], p["number"]))
    return {**original, "source": {**(original.get("source") or {}), "reprintedIn": prints}}


def as_original(reprint, date):
    """The original of `reprint`, read off the reprint's own print: its grid,
    clues, answers and annotations under the original's id and name, dated
    `date` (the original's print date), with the reprint's print recorded."""
    oid = original_of(reprint)
    series, number = series_meta.parse_id(oid)
    pub, kind = series_meta.publisher(series), series_meta.kind(series).lower()
    source = {k: v for k, v in (reprint.get("source") or {}).items()
              if k in ("url", "acquiredOn")}
    out = {**reprint, "id": oid, "number": number, "series": series,
           "name": f"{pub} {kind} crossword No {number:,}", "date": date, "source": source}
    return with_print(out, reprint["series"], reprint["number"], reprint["date"])
