#!/usr/bin/env python3
"""The difficulty index and each of its components against the SNITCH, by date third.

    python3 tools/snitch_report.py            # print it
    python3 tools/snitch_report.py --write    # and write tools/data/snitch_report.txt

Two targets for every annotated, SNITCH-rated Times puzzle, per series:

  raw       the NITCH itself.
  residual  the NITCH minus its series' mean NITCH for that weekday. The Times
            ramps from Monday to Friday by editorial choice, so most of the raw
            agreement any score gets is the weekday; the residual is the part of
            difficulty the ramp does not explain, and so the part that should
            carry to series without one.

Each row is a Spearman rho, in each date third (oldest first) and over all of
it with its p, for the index and every component in difficulty.WEIGHTS.
Nothing is fitted: a component earns its place by the held-out test that
tools/difficulty.py's docstring states, and these rows show whether it keeps
holding as ratings and annotations arrive. Then, once Times for the Times
comments reach puzzles we have annotated, the same components per clue against
the clues commenters flagged hard or named as their last one in, ranked within
each puzzle (tools/blog_comment_difficulty.py, from its committed table).

The nightly job runs --write, so the file's git history is the record of how
each number moves as ratings, annotations and comments arrive. No model calls.
"""
import argparse
import contextlib
import io
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import blog_comment_difficulty as B  # noqa: E402
import difficulty as D  # noqa: E402

OUT = ROOT / "tools" / "data" / "snitch_report.txt"
#: The components, then counts measured alongside them that are not in the index.
ROWS = ["index", *(f"z_{k}" for k in D.WEIGHTS), "indicators", "three_device", "clue_words"]


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def feats(puz, s):
    """The index, its z-scores, and the clue counts beside them."""
    clues = []
    for e in puz["entries"]:
        a = e.get("annotation") or {}
        parts = [p for p in (a.get("type") or "").split("+") if p.strip()]
        if parts:
            clue = re.sub(r"\s*\([\d,\s\-–]+\)\s*$", "", e.get("clue") or "")
            clues.append((len(a.get("indicators") or []), len(parts), len(clue.split())))
    return {"index": s["index"], **{"z_" + k: v for k, v in s["z"].items()},
            "indicators": mean([c[0] for c in clues]),
            "three_device": mean([c[1] >= 3 for c in clues]),
            "clue_words": mean([c[2] for c in clues])}


def rated_rows():
    """{series: [row, ...]} oldest first, each with its NITCH, residual and features."""
    sn, ctx = D.load_snitch(), D.context()
    out = {}
    for pid, v in sn.items():
        series = pid.rpartition("-")[0]
        path = ROOT / "puzzles" / f"{pid}.json"
        if series not in D.SNITCH_SERIES or not path.exists():
            continue
        puz = D.read_puzzle_file(path)
        s = D.score(puz, ctx)
        if s:
            out.setdefault(series, []).append({
                "date": v["date"], "nitch": v["nitch"],
                "wd": date.fromisoformat(v["date"]).weekday(), "f": feats(puz, s)})
    for rows in out.values():
        rows.sort(key=lambda r: r["date"])
        by = {}
        for r in rows:
            by.setdefault(r["wd"], []).append(r["nitch"])
        for r in rows:
            r["f"]["weekday_mean"] = mean(by[r["wd"]])
            r["resid"] = r["nitch"] - r["f"]["weekday_mean"]
    return out


def rho(rows, key, target):
    pairs = [(r["f"][key], r[target]) for r in rows if r["f"].get(key) is not None]
    if len(pairs) < 10 or len({a for a, _ in pairs}) < 3:
        return None, None
    a, b = zip(*pairs)
    r = D._spearman(list(a), list(b))
    return r, math.erfc(abs(r) * math.sqrt(len(a) - 1) / math.sqrt(2))


def zscored(rows, key):
    xs = [r["f"][key] for r in rows]
    m = mean(xs)
    sd = mean([(x - m) ** 2 for x in xs]) ** 0.5 or 1
    return [(x - m) / sd for x in xs]


def series_block(series, rows):
    n = len(rows)
    thirds = [rows[: n // 3], rows[n // 3: 2 * n // 3], rows[2 * n // 3:]]
    print(f"{series}: n={n}, thirds " + " | ".join(
        f"{t[0]['date']}..{t[-1]['date']} n={len(t)}" for t in thirds))
    # A series printed on one day of the week has no weekday to remove.
    one_day = len({r["wd"] for r in rows}) == 1
    for target in ("nitch",) if one_day else ("resid", "nitch"):
        label = "vs NITCH minus weekday mean" if target == "resid" else "vs raw NITCH"
        print(f"  {label:30s}  old   mid   new   all")
        keys = ROWS if target == "resid" or one_day else ROWS + ["weekday_mean", "index+weekday"]
        for k in keys:
            if k == "index+weekday":
                for r, a, b in zip(rows, zscored(rows, "index"), zscored(rows, "weekday_mean")):
                    r["f"][k] = a + b
            cells = [rho(t, k, target)[0] for t in thirds]
            r, p = rho(rows, k, target)
            if r is None:
                continue
            print(f"    {k:28s}" + "".join(" -----" if c is None else f" {c:+.2f}" for c in cells)
                  + f"  {r:+.2f} (p={p:.3f})")


def comments_block():
    path = B.OUT
    if not path.exists():
        print("per clue: no tools/data/blog_comment_difficulty.json")
        return
    table = json.loads(path.read_text(encoding="utf-8"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        B.per_clue(table)
    print(buf.getvalue().rstrip())


def report():
    rows = rated_rows()
    sn = D.load_snitch()
    print(f"SNITCH ratings held: {len(sn)}, newest {max(v['date'] for v in sn.values())}; "
          f"index weights {D.WEIGHTS}")
    for series in D.SNITCH_SERIES:
        if len(rows.get(series, [])) >= 30:
            print()
            series_block(series, rows[series])
    print()
    comments_block()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help=f"also write {OUT.relative_to(ROOT)}")
    a = ap.parse_args()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report()
    text = buf.getvalue()
    print(text, end="")
    if a.write:
        OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
