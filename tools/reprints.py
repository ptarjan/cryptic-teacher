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
    `date` (the original's print date; None leaves it undated), with the
    reprint's print recorded."""
    oid = original_of(reprint)
    series, number = series_meta.parse_id(oid)
    pub, kind = series_meta.publisher(series), series_meta.kind(series).lower()
    source = {k: v for k, v in (reprint.get("source") or {}).items()
              if k in ("url", "acquiredOn", "retrievedFrom", "gridOrigin")}
    out = {k: v for k, v in reprint.items() if k != "date"}
    out = {**out, "id": oid, "number": number, "series": series,
           "name": f"{pub} {kind} crossword No {number:,}", "source": source,
           **({"date": date} if date else {})}
    return with_print(out, reprint["series"], reprint["number"], reprint["date"])


def light(entry):
    return entry["number"], entry["direction"]


def mismatch(original, reprint):
    """Why `reprint` is not a print of `original`'s grid and answers, or None:
    the two must hold the same lights at the same cells, and answer each light
    alike wherever both answer it."""
    if original["dimensions"] != reprint["dimensions"]:
        return f"dimensions {reprint['dimensions']} against {original['dimensions']}"
    held = {light(e): e for e in original["entries"]}
    if set(held) != {light(e) for e in reprint["entries"]}:
        return "a different set of lights"
    for e in reprint["entries"]:
        o = held[light(e)]
        if (o["position"], o["length"]) != (e["position"], e["length"]):
            return f"{e['number']}-{e['direction']} at another cell"
        if o.get("solution") and e.get("solution") and o["solution"] != e["solution"]:
            return f"{e['number']}-{e['direction']} answered {e['solution']} against {o['solution']}"
    return None


def merged(original, reprint):
    """`original` with what its print `reprint` holds and it lacks, the
    reprint's print recorded. Light by light: an annotation travels with the
    clue words it was written against, so a light the original leaves
    unannotated takes the reprint's annotated clue whole; any other light
    keeps the original's clue and takes the reprint's answer, count or words
    where the original has none. The solutions block is that of the copy
    answering more lights. Call mismatch() first."""
    held = {light(e): e for e in reprint["entries"]}
    entries, carried = [], False
    for e in original["entries"]:
        r = held[light(e)]
        if r.get("annotation") and not e.get("annotation"):
            e = {**e, "clue": r["clue"], "solution": r.get("solution") or e.get("solution"),
                 "annotation": r["annotation"]}
            carried = True
        else:
            clue = dict(e["clue"])
            for k in ("text", "enumeration"):
                if not clue.get(k) and r["clue"].get(k):
                    clue[k] = r["clue"][k]
                    if k == "text":
                        clue.pop("missing", None)
            e = {**e, "clue": clue}
            if not e.get("solution") and r.get("solution"):
                e["solution"] = r["solution"]
        entries.append(e)
    out = {**original, "entries": entries}
    answered = lambda p: sum(bool(e.get("solution")) for e in p["entries"])
    if answered(reprint) > answered(original):
        out["solutions"] = reprint["solutions"]
    if carried:
        out["annotatedBy"] = sorted({*original.get("annotatedBy", ()), *reprint.get("annotatedBy", ())})
    return with_print(out, reprint["series"], reprint["number"], reprint["date"])


def lost(reprint, held):
    """The lights of `reprint` the filed `held` does not keep: missing, moved,
    its answer gone or changed, its clue left without words, or its
    annotation dropped where `held` carries its clue words."""
    have = {light(e): e for e in held["entries"]}
    out = []
    for e in reprint["entries"]:
        h = have.get(light(e))
        name = f"{e['number']}-{e['direction']}"
        if h is None or (h["position"], h["length"]) != (e["position"], e["length"]):
            out.append(f"{name} gone or moved")
        elif e.get("solution") and h.get("solution") != e["solution"]:
            out.append(f"{name} answer {e['solution']} now {h.get('solution')}")
        elif e["clue"].get("text") and not h["clue"].get("text"):
            out.append(f"{name} clue words gone")
        elif e.get("annotation") and not h.get("annotation"):
            out.append(f"{name} annotation gone")
    return out
