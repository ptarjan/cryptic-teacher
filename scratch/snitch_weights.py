"""Held-out refit of difficulty.WEIGHTS against the SNITCH, split by date.
Needs scratch/snitch_rows.json from scratch/snitch_tune.py."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D
rows = json.loads((ROOT / "scratch/snitch_rows.json").read_text())
base = D.load_baseline()
def z(r, k): return (r[k] - base[k]["mean"]) / base[k]["sd"]
def idx(r, w):
    ks = [k for k in w if r.get(k) is not None and w[k] > 0] or list(w)
    return sum(w[k] * z(r, k) for k in ks) / (sum(w[k] for k in ks) or 1)
ser = lambda r: r["id"].rpartition("-")[0]
def within(rs, w):
    """n-weighted mean of the per-series rho, and the per-series values."""
    out = {}
    for s in ("times", "sundaytimes"):
        g = [r for r in rs if ser(r) == s]
        if len(g) >= 8:
            out[s] = (D._spearman([r["nitch"] for r in g], [idx(r, w) for r in g]), len(g))
    tot = sum(n for _, n in out.values())
    return sum(r * n for r, n in out.values()) / tot, out
ann = sorted([r for r in rows if r["device"] is not None and r["obscurity"] is not None], key=lambda r: r["date"])
W0 = dict(D.WEIGHTS)
grid = [i / 20 for i in range(21)]
cands = [{"checking": c, "obscurity": o, "device": round(1 - c - o, 3)} for c in grid for o in grid if c + o <= 1.0001]
for frac in (0.5, 0.6, 0.7):
    cut = ann[int(len(ann) * frac)]["date"]
    train = [r for r in ann if r["date"] < cut]; test = [r for r in ann if r["date"] >= cut]
    bw = max(cands, key=lambda w: within(train, w)[0])
    # also: fit the grid-only ratio on every rated puzzle before the cut, annotated or not,
    # then the device share on the annotated train
    print(f"cut {cut} train {len(train)} test {len(test)}")
    for name, w in (("current", W0), ("fitted", bw)):
        tr, te = within(train, w), within(test, w)
        print(f"  {name:<8} {w}  train {tr[0]:+.3f}  test {te[0]:+.3f}  " +
              " ".join(f"{s} {r:+.3f}(n={n})" for s, (r, n) in te[1].items()))
# Times daily only, like the +0.30 in the brief
t = [r for r in ann if ser(r) == "times"]
print("times daily annotated", len(t), t[0]["date"], t[-1]["date"])
for frac in (0.5, 0.6, 0.7):
    cut = t[int(len(t) * frac)]["date"]
    train = [r for r in t if r["date"] < cut]; test = [r for r in t if r["date"] >= cut]
    f = lambda rs, w: D._spearman([r["nitch"] for r in rs], [idx(r, w) for r in rs])
    bw = max(cands, key=lambda w: f(train, w))
    print(f"  times cut {cut} train {len(train)} test {len(test)}: current train {f(train, W0):+.3f} test {f(test, W0):+.3f} | fitted {bw} train {f(train, bw):+.3f} test {f(test, bw):+.3f}")
    for k in W0:
        print(f"      {k} alone test {D._spearman([r['nitch'] for r in test], [z(r, k) for r in test]):+.3f} train {D._spearman([r['nitch'] for r in train], [z(r, k) for r in train]):+.3f}")
