"""Held-out refit of difficulty.WEIGHTS, by date third, rotating the held-out third.

Targets, Times daily, annotated puzzles only:
  snitch    NITCH minus its weekday mean (snitch_report.rated_rows()).
  comments  TftT comment DNF share (dnf / comments) minus its weekday mean,
            from tools/data/blog_comment_difficulty.json.
Fits: a non-negative weight grid (step 0.05, weights summing to 1; the index is
rank-invariant to scale) maximising Spearman on the two training thirds, and
ridge regression of the target on the four z-scores (negatives clipped to 0).
The index is rebuilt exactly as difficulty.score() builds it: a weighted mean
over the components present.
"""
import json
import sys
from datetime import date, datetime, timezone
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D
import snitch_report as S

K = list(D.WEIGHTS)


def idx(z, w):
    ks = [k for k in K if z.get(k) is not None]
    tot = sum(w[k] for k in ks)
    return sum(w[k] * z[k] for k in ks) / tot if tot else 0.0


def rho(rows, w):
    return D._spearman([idx(r["z"], w) for r in rows], [r["y"] for r in rows])


def resid(rows):
    by = {}
    for r in rows:
        by.setdefault(r["wd"], []).append(r["y"])
    for r in rows:
        r["y"] -= sum(by[r["wd"]]) / len(by[r["wd"]])
    return rows


def snitch_rows():
    out = []
    for r in S.rated_rows().get("times", []):
        out.append({"date": r["date"], "y": r["resid"],
                    "z": {k: r["f"].get("z_" + k) for k in K}})
    return out


def comment_rows():
    tab = json.loads((ROOT / "tools/data/blog_comment_difficulty.json").read_text())
    ctx = D.context()
    out = []
    for pid, v in tab.items():
        if pid.rpartition("-")[0] != "times" or not v.get("comments"):
            continue
        path = ROOT / "puzzles" / f"{pid}.json"
        if not path.exists():
            continue
        puz = D.read_puzzle_file(path)
        s = D.score(puz, ctx)
        d = puz.get("date")
        if not s or not d:
            continue
        d = (datetime.fromtimestamp(d / 1000, timezone.utc).date() if isinstance(d, (int, float))
             else date.fromisoformat(str(d)[:10]))
        out.append({"date": d.isoformat(), "wd": d.weekday(),
                    "y": v["dnf"] / v["comments"], "z": {k: s["z"].get(k) for k in K}})
    out.sort(key=lambda r: r["date"])
    return resid(out)


GRID = [dict(zip(K, (a / 20, b / 20, c / 20, (20 - a - b - c) / 20)))
        for a, b, c in product(range(21), repeat=3) if a + b + c <= 20]


def grid_fit(train):
    return max(GRID, key=lambda w: rho(train, w))


def ridge_fit(train, lam=10.0):
    import numpy as np
    X = np.array([[r["z"].get(k) or 0.0 for k in K] for r in train])
    y = np.array([r["y"] for r in train])
    X = X - X.mean(0)
    y = y - y.mean()
    b = np.linalg.solve(X.T @ X + lam * np.eye(len(K)), X.T @ y)
    b = np.clip(b, 0, None)
    tot = b.sum() or 1
    return {k: round(float(v / tot), 3) for k, v in zip(K, b)}


def folds(name, rows):
    n = len(rows)
    th = [rows[: n // 3], rows[n // 3: 2 * n // 3], rows[2 * n // 3:]]
    print(f"\n{name}: n={n}  thirds " + " | ".join(f"{t[0]['date']}..{t[-1]['date']} n={len(t)}" for t in th))
    for i, test in enumerate(th):
        train = [r for j, t in enumerate(th) if j != i for r in t]
        g, rr = grid_fit(train), ridge_fit(train)
        print(f"  hold {i}: current {rho(test, D.WEIGHTS):+.3f}  grid {rho(test, g):+.3f} {g}"
              f"  ridge {rho(test, rr):+.3f} {rr}")
    print(f"  all-data grid fit {grid_fit(rows)}  ridge {ridge_fit(rows)}")
    return th


def score_weights(name, rows, w):
    n = len(rows)
    th = [rows[: n // 3], rows[n // 3: 2 * n // 3], rows[2 * n // 3:]]
    print(f"  {name}: " + " ".join(f"{rho(t, w):+.3f}" for t in th) + f"  all {rho(rows, w):+.3f}  {w}")


if __name__ == "__main__":
    sn, cm = snitch_rows(), comment_rows()
    folds("SNITCH resid", sn)
    folds("comment DNF resid", cm)
    for w in sys.argv[1:]:
        w = dict(zip(K, map(float, w.split(","))))
        score_weights("SNITCH", sn, w)
        score_weights("comments", cm, w)
