#!/usr/bin/env python3
"""The shipped difficulty rating's scorecard against the SNITCH, as JSON.

    python3 tools/difficulty_check.py            # print it
    python3 tools/difficulty_check.py --write    # and write tools/data/difficulty_check.json

The held-out test tools/difficulty.py's docstring states for a candidate
component, run on the index as it ships:

  annotated    the annotated Times dailies, full index (score()).
  unannotated  the rated Times dailies with no annotation, scored by the
               components that need none (difficulty.PORTABLE).
  sunday       the annotated Sunday Times, full index, against the raw NITCH
               (one day a week, so no weekday to remove).

Each set is split into date thirds, oldest first, and each third is scored
(Spearman) against the NITCH minus the weekday mean of the rated puzzles
OUTSIDE that third, so no puzzle helps set its own target. The "blended" rows
are the same sets under the badges' comment blend (difficulty.blend()), with
its per-series moments taken over the set, as scratch/comment_blend.py did.
Then the gentle-series margin: the mean index of every other series minus
that of difficulty.GENTLE_SERIES, in the index's own sd.

The file records the weights and the baseline it was measured under, so the
difficulty page (tools/build_seo_pages.py) can refuse to quote numbers that
describe a different index. The nightly job runs --write. No model calls.
"""
import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D  # noqa: E402
from fetch_puzzle import puzzle_files, puzzle_is_annotated, read_puzzle_file  # noqa: E402

OUT = ROOT / "tools" / "data" / "difficulty_check.json"


def fingerprint():
    """What a set of numbers describes: the weights, the portable subset and
    the frozen baseline. A page quoting the numbers checks this first."""
    return {"weights": D.WEIGHTS, "portable": list(D.PORTABLE),
            "baseline_sha256": hashlib.sha256(D.BASELINE.read_bytes()).hexdigest()[:16]}


def rows():
    """One row per puzzle that is SNITCH-rated or scored: its series, date,
    NITCH, index, portable index and component z-scores."""
    sn, ctx = D.load_snitch(), D.context()
    out = []
    for path in puzzle_files():
        puz = read_puzzle_file(path)
        pid = puz["id"]
        s = D.score(puz, ctx)
        rated = pid in sn and pid.rpartition("-")[0] in D.SNITCH_SERIES
        if not rated and not s:
            continue
        rw = D.raw(puz, ctx)
        pz = {k: (rw[k] - ctx.base[k]["mean"]) / ctx.base[k]["sd"]
              for k in D.PORTABLE if rw.get(k) is not None}
        tot = sum(D.WEIGHTS[k] for k in pz)
        out.append({"pid": pid, "series": puz.get("series") or pid.rpartition("-")[0],
                    "date": D.puzzle_day(puz), "nitch": sn[pid]["nitch"] if rated else None,
                    "annotated": puzzle_is_annotated(puz),
                    "index": s["index"] if s else None, "z": s["z"] if s else None,
                    "portable": sum(D.WEIGHTS[k] * z for k, z in pz.items()) / tot if tot else None,
                    "pz": pz})
    return out


def weekday_resid_target(all_rated, lo, hi):
    """NITCH minus the weekday mean of the (date, nitch) pairs dated outside lo..hi."""
    by = {}
    for d, x in all_rated:
        if not lo <= d <= hi:
            by.setdefault(date.fromisoformat(d).weekday(), []).append(x)
    return lambda r: r["nitch"] - sum(by[date.fromisoformat(r["date"]).weekday()]) / len(
        by[date.fromisoformat(r["date"]).weekday()])


def heldout(rows, key, sel, series="times"):
    """([rho per date third], n) of `key` over the rated rows of `series` that
    `sel` picks. The Times daily is scored against the weekday-removed NITCH,
    anything else against the raw NITCH."""
    allr = sorted((r["date"], r["nitch"]) for r in rows
                  if r["nitch"] is not None and r["series"] == series)
    got = sorted((r for r in rows if r["series"] == series and r["nitch"] is not None and sel(r)
                  and r.get(key) is not None), key=lambda r: r["date"])
    n = len(got)
    out = []
    for t in (got[: n // 3], got[n // 3: 2 * n // 3], got[2 * n // 3:]):
        if series == "times":
            f = weekday_resid_target(allr, t[0]["date"], t[-1]["date"])
            y = [f(r) for r in t]
        else:
            y = [r["nitch"] for r in t]
        out.append(D._spearman([r[key] for r in t], y))
    return out, n


def margin_of(rows, key="index"):
    """(mean `key` of the other series minus the gentle series', n gentle, n other)."""
    rows = [r for r in rows if r["index"] is not None and r.get(key) is not None]
    g = [r[key] for r in rows if r["series"] in D.GENTLE_SERIES]
    h = [r[key] for r in rows if r["series"] not in D.GENTLE_SERIES]
    return sum(h) / len(h) - sum(g) / len(g), len(g), len(h)


def with_blend(rows, key, sel):
    """rows[r]["blend"] = `key` blended with its comment signal (difficulty.blend()),
    moments per series over the rows `sel` picks; `key` itself where there is none.
    Returns {series: puzzles blended}."""
    com = D.load_comments()
    vals = {r["pid"]: r[key] for r in rows if sel(r) and r.get(key) is not None}
    cm = D.comment_moments(vals, com)
    n = {}
    for r in rows:
        b = D.blend(r["pid"], r[key], com, cm) if r["pid"] in vals else None
        r["blend"] = r[key] if b is None else b
        r["_blended"] = b is not None
        if b is not None:
            n[r["series"]] = n.get(r["series"], 0) + 1
    return n


#: name -> (base key, row filter, series). The three held-out sets.
SETS = {
    "annotated": ("index", lambda r: r["index"] is not None, "times"),
    "unannotated": ("portable", lambda r: not r["annotated"], "times"),
    "sunday": ("index", lambda r: r["index"] is not None, "sundaytimes"),
}


def cell(h):
    thirds, n = h
    return {"thirds": [round(x, 3) for x in thirds], "mean": round(sum(thirds) / 3, 3), "n": n}


def check(rs=None):
    rs = rows() if rs is None else rs
    sn = D.load_snitch()
    out = {**fingerprint(), "snitch_newest": max(v["date"] for v in sn.values()),
           "heldout": {}, "blended": {}, "components": {}}
    for name, (key, sel, series) in SETS.items():
        out["heldout"][name] = cell(heldout(rs, key, sel, series))
        n = with_blend(rs, key, sel)
        out["blended"][name] = {**cell(heldout(rs, "blend", sel, series)),
                                "puzzles_blended": n.get(series, 0)}
    # Each component alone, same test, on the annotated Times dailies.
    sel = SETS["annotated"][1]
    for k in D.WEIGHTS:
        for r in rs:
            r["_c"] = (r["z"] or {}).get(k)
        out["components"][k] = cell(heldout(rs, "_c", sel))
    m, ng, nh = margin_of(rs)
    out["gentle_margin"] = {"margin": round(m, 3), "floor": D.MARGIN_FLOOR,
                            "gentle_n": ng, "other_n": nh, "series": sorted(D.GENTLE_SERIES)}
    return out


def current(data):
    """Whether `data` (a loaded difficulty_check.json) describes the index as it is now."""
    return all(data.get(k) == v for k, v in fingerprint().items())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help=f"also write {OUT.relative_to(ROOT)}")
    a = ap.parse_args()
    text = json.dumps(check(), indent=2) + "\n"
    print(text, end="")
    if a.write:
        OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
