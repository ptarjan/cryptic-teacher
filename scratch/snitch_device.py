"""Held-out refit of the device costs in difficulty.py against the SNITCH.
Needs scratch/snitch_rows.json from scratch/snitch_tune.py."""
import json, sys, itertools
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D
from fetch_puzzle import read_puzzle_file
rows = json.loads((ROOT / "scratch/snitch_rows.json").read_text())
ann = sorted([r for r in rows if r["device"] is not None and r["obscurity"] is not None], key=lambda r: r["date"])
puz = {r["id"]: read_puzzle_file(ROOT / "puzzles" / f"{r['id']}.json") for r in ann}
base = D.load_baseline()
orig = {k: getattr(D, k) for k in ("SEAM_COST", "OPAQUE_PIECE_COST", "UNINDICATED_COST", "STACKING_COST")}
orig_cost = dict(D.DEVICE_COST)
def dev_all(p):
    for k, v in p.items():
        if k == "flat":
            D.DEVICE_COST.clear(); D.DEVICE_COST.update({n: 0.5 + v * (c - 0.5) for n, c in orig_cost.items()})
        else:
            setattr(D, k, v)
    out = {pid: D.device(pz) for pid, pz in puz.items()}
    for k, v in orig.items(): setattr(D, k, v)
    D.DEVICE_COST.clear(); D.DEVICE_COST.update(orig_cost)
    return out
ser = lambda r: r["id"].rpartition("-")[0]
def z(r, k, dev): 
    v = dev[r["id"]] if k == "device" else r[k]
    return (v - base[k]["mean"]) / base[k]["sd"]
def within(rs, dev, w=D.WEIGHTS):
    tot = acc = 0
    per = {}
    for s in ("times", "sundaytimes"):
        g = [r for r in rs if ser(r) == s]
        if len(g) >= 8:
            rho = D._spearman([r["nitch"] for r in g], [sum(w[k] * z(r, k, dev) for k in w) for r in g])
            per[s] = round(rho, 3); acc += rho * len(g); tot += len(g)
    return acc / tot, per
grid = {"SEAM_COST": [0, .05, .09, .15], "OPAQUE_PIECE_COST": [0, .03, .06, .1],
        "UNINDICATED_COST": [0, .06, .12], "STACKING_COST": [0, .12, .2], "flat": [0, .5, 1, 1.5]}
combos = [dict(zip(grid, vs)) for vs in itertools.product(*grid.values())]
devs = [(c, dev_all(c)) for c in combos]
cur = dev_all({})
for frac in (0.5, 0.6, 0.7):
    cut = ann[int(len(ann) * frac)]["date"]
    train = [r for r in ann if r["date"] < cut]; test = [r for r in ann if r["date"] >= cut]
    best = max(devs, key=lambda cd: within(train, cd[1])[0])
    print(f"cut {cut}: current train {within(train, cur)[0]:+.3f} test {within(test, cur)[0]:+.3f} {within(test, cur)[1]}")
    print(f"   fitted {best[0]} train {within(train, best[1])[0]:+.3f} test {within(test, best[1])[0]:+.3f} {within(test, best[1])[1]}")
