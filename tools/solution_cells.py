#!/usr/bin/env python3
"""Train trove_solution_ocr's cell classifier (tools/data/solution_cells.npz).

    solution_cells.py harvest OUT [--origin published] [--min-date 1970] [--start 0 --step 1 --limit N]
    solution_cells.py train MODEL.npz DIR [DIR...] [--epochs 12] [--holdout]

harvest cuts each Times puzzle's printed solution grid off its page, as
file_archive_org_puzzles.read_solution cuts it (the heading the ledgers'
scans link, the answers left unread), lays the lattice read_framed's best
framing finds, and saves every light cell's glyph() with the letter the
puzzle's file holds there ("?" where none): OUT/<id>.npz. A page is read one
at a time (~1 GB). The model behind CELL_MODEL_SHA was trained on ~125k
cells: 399 grids of the corpus's cached crops (1940s-90s, the answers their
reads accepted), 241 published 1970s-90s grids and 259 model-solved ones
(whose answers a model typed: AXMINSTER is printed where one solve has
ADMONITOR). Its vetoed()/classified_reads() thresholds were set on two
models each trained without half the model-solved grids, each grid scored
by the one that never saw it.

train fits a 1024-384-128-26 network to the glyphs' 32-pixel middles, each
batch slid up to GLYPH_SHIFT pixels (the cut is a few pixels off the
letter), and writes it as float16; --holdout reports the accuracy on a fifth
of the grids it left out. CELL_MODEL_SHA is then the file's sha256.
"""
import argparse
import glob
import json
import os
import sys
import zlib
from pathlib import Path

import numpy as np

import trove_solution_ocr as T

G, S = T.GLYPH, T.GLYPH_SHIFT


def cells_of(crop, grid):
    """(cells, glyphs, numbered, blocks) of a solution crop on read_framed's best-fitting framing."""
    from PIL import Image
    gray = np.asarray(Image.open(crop).convert("L"))
    framed = T.framings(gray, grid)
    scores = [T.block_agreement(g, grid, (ys, xs)) for g, ys, xs in framed]
    g, ys, xs = framed[int(np.argmax(scores))]
    lts = T.lights(grid)
    numbers = {cs[0] for cs in lts.values()}
    cells = sorted({rc for cs in lts.values() for rc in cs})
    return cells, np.stack([T.glyph(g, ys, xs, *rc) for rc in cells]), [rc in numbers for rc in cells], max(scores)


def harvest(out, origins, min_date="", start=0, step=1, limit=None):
    import file_archive_org_puzzles as fa
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    fa.CROPS = out
    real = fa.trove_solution_ocr.read_answers
    fa.trove_solution_ocr.read_answers = lambda *a, **k: ({}, {"blocks": 1.0})
    files = {Path(f).stem: f for f in glob.glob(str(T.TOOLS.parent / "puzzles" / "times" / "*" / "*.json"))}
    heads, last = {}, {}
    try:
        for paper in (fa.TIMES, fa.GALE):
            for r in fa.scan_queue.jsonl_rows(fa.ledger_of(fa.CACHE, paper)):
                name = r.get("edition", "").split("/")[-1]
                for h in (r.get("scan") or {}).get("solutions") or ():
                    heads[(name, h["leaf"], h["number"])] = (r["edition"], h)
                for v in r.get("verdicts") or ():
                    if str(v.get("id", "")).startswith("times-") and v.get("solutionFrom") \
                            and "refused" not in (v.get("solution") or {}):
                        last[v["id"]] = v["solutionFrom"]
        todo = []
        for pid, frm in sorted(last.items()):
            p = json.loads(Path(files[pid]).read_text()) if pid in files else None
            if not p or (p.get("solutions") or {}).get("origin") not in origins or p["date"] < min_date:
                continue
            name, leaf = frm.split(" leaf ")
            h = heads.get((name, int(leaf), int(pid.split("-")[1])))
            if h and any(e.get("solution") for e in p["entries"]):
                todo.append((pid, p, h))
        for pid, p, (ed, h) in todo[start::step][:limit]:
            dest = out / f"{pid}.npz"
            if dest.exists():
                continue
            grid, d = T.puzzle_grid(p), fa.CACHE / ed
            _, stats = fa.read_solution(fa.page(d, h["leaf"]), {**h, "dir": d}, grid,
                                        above=fa.paper_of(d).solution_above)
            if "refused" in stats:
                continue
            crop = out / "solutions" / f"{d.name}_{h['number']}.png"
            cells, glyphs, numbered, blocks = cells_of(crop, grid)
            lab, lts = {}, T.lights(grid)
            for e in p["entries"]:
                cs = lts.get((e["number"], e["direction"]))
                if e.get("solution") and cs and len(cs) == len(e["solution"]):
                    lab.update(zip(cs, e["solution"]))
            np.savez_compressed(dest, glyphs=(glyphs * 255).astype(np.uint8), cells=np.array(cells),
                                labels=np.array([lab.get(rc, "?") for rc in cells]), numbered=np.array(numbered),
                                blocks=blocks, pid=pid, date=p["date"], crop=str(crop))
            print(pid, p["date"], flush=True)
    finally:
        fa.trove_solution_ocr.read_answers = real


def load(dirs):
    X, y, grp = [], [], []
    for f in sorted(f for d in dirs for f in glob.glob(os.path.join(d, "*.npz"))):
        z = np.load(f)
        keep = z["labels"] != "?"
        if keep.any():
            X.append(z["glyphs"][keep])
            y.append(np.array([T.AZ.index(c) for c in z["labels"][keep]]))
            grp.append(np.full(keep.sum(), zlib.crc32(str(z["pid"]).encode()) % 5))
    return np.concatenate(X), np.concatenate(y), np.concatenate(grp)


def forward(P, x):
    h = np.maximum(0, x @ P["w1"] + P["b1"])
    h2 = np.maximum(0, h @ P["w2"] + P["b2"])
    return h, h2, h2 @ P["w3"] + P["b3"]


def softmax(z):
    e = np.exp(z - z.max(1, keepdims=True))
    return e / e.sum(1, keepdims=True)


def middles(X, dx, dy):
    return X[:, dy:dy + G, dx:dx + G].reshape(len(X), -1).astype(np.float32) / 255 - 0.25


def fit(X, y, epochs=12, seed=0):
    """Adam on the cross-entropy, 256 a batch, the rate cut by 3 for the last epochs."""
    rng = np.random.default_rng(seed)
    shapes = {"w1": (G * G, 384), "w2": (384, 128), "w3": (128, 26)}
    P = {}
    for k, (a, b) in shapes.items():
        P[k] = rng.normal(0, np.sqrt(2 / a), (a, b)).astype(np.float32)
        P["b" + k[1]] = np.zeros(b, np.float32)
    M = {k: np.zeros_like(v) for k, v in P.items()}
    V = {k: np.zeros_like(v) for k, v in P.items()}
    t, lr = 0, 1e-3
    for ep in range(epochs):
        order = rng.permutation(len(X))
        for i in range(0, len(X), 256):
            idx = order[i:i + 256]
            dx, dy = rng.integers(0, 2 * S + 1, 2)
            xb = middles(X[idx], dx, dy) + rng.normal(0, 0.05, (len(idx), G * G)).astype(np.float32)
            h, h2, z = forward(P, xb)
            g = softmax(z)
            g[np.arange(len(idx)), y[idx]] -= 1
            g /= len(idx)
            gh2 = (g @ P["w3"].T) * (h2 > 0)
            gh = (gh2 @ P["w2"].T) * (h > 0)
            grads = {"w3": h2.T @ g, "b3": g.sum(0), "w2": h.T @ gh2, "b2": gh2.sum(0), "w1": xb.T @ gh, "b1": gh.sum(0)}
            t += 1
            for k in P:
                M[k] = 0.9 * M[k] + 0.1 * grads[k]
                V[k] = 0.999 * V[k] + 0.001 * grads[k] ** 2
                P[k] -= lr * (M[k] / (1 - 0.9 ** t)) / (np.sqrt(V[k] / (1 - 0.999 ** t)) + 1e-8)
        if ep == epochs - 4:
            lr /= 3
        print("epoch", ep, flush=True)
    return P


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("harvest")
    h.add_argument("out")
    h.add_argument("--origin", action="append", default=None)
    h.add_argument("--min-date", default="")
    h.add_argument("--start", type=int, default=0)
    h.add_argument("--step", type=int, default=1)
    h.add_argument("--limit", type=int)
    t = sub.add_parser("train")
    t.add_argument("model")
    t.add_argument("dirs", nargs="+")
    t.add_argument("--epochs", type=int, default=12)
    t.add_argument("--holdout", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "harvest":
        harvest(a.out, a.origin or ["published"], a.min_date, a.start, a.step, a.limit)
        return 0
    X, y, grp = load(a.dirs)
    test = grp == 0 if a.holdout else np.zeros(len(y), bool)
    P = fit(X[~test], y[~test], a.epochs)
    if test.any():
        T._CELLS[:] = [P]
        got = T.classified({i: X[i].astype(np.float32) / 255 for i in np.nonzero(test)[0]})
        print("held-out accuracy", np.mean([got[i].argmax() == y[i] for i in got]))
    np.savez_compressed(a.model, **{k: v.astype(np.float16) for k, v in P.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
