"""Annotation-free features against the SNITCH NITCH, held out by date.

Every feature is computed from the clue text, grid and blog facts alone, so it
exists for all rated puzzles, not only the annotated ones. Fit nothing: report
each feature's Spearman rho on the earlier 70% and the later 30% separately; a
feature counts only if the sign holds and the later rho is significant."""
import json, sys, re, math, datetime, random
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D
from fetch_puzzle import read_puzzle_file
sn = json.loads((ROOT / "tools/data/snitch.json").read_text())
rank = D.ranks()
blog = {}
for s in ("times", "sundaytimes"):
    p = ROOT / f"tools/data/blog_facts/{s}.json"
    if p.exists():
        blog.update(json.loads(p.read_text()))
ANAG = re.compile(r"anagram", re.I)

def feats(pid, puz, date):
    ents = puz["entries"]
    clues = [re.sub(r"\s*\([\d,\s\-–]+\)\s*$", "", e.get("clue") or "") for e in ents]
    words = [len(c.split()) for c in clues if c]
    sols = [(e.get("solution") or "") for e in ents]
    rar = []
    unk = 0
    for e in ents:
        ws = (e.get("solution") or "").upper().split()
        if not ws: continue
        r = max(rank.get(w.strip("'-"), D.MISSING_RANK) for w in ws)
        unk += r >= D.MISSING_RANK
        rar.append(math.log10(max(r, 10)))
    f = {
        "weekday": datetime.date.fromisoformat(date).weekday(),
        "checking": D.checking(puz),
        "obscurity": sum(rar) / len(rar) if rar else None,
        "unknown_word_share": unk / len(rar) if rar else None,
        "clue_words": sum(words) / len(words) if words else None,
        "short_clues": sum(1 for w in words if w <= 4) / len(words) if words else None,
        "answer_len": sum(e["length"] for e in ents) / len(ents),
        "multiword": sum(1 for e in ents if re.search(r"[,\-]", str(e.get("enumeration") or e.get("clue") or "")[-12:])) / len(ents),
        "question_marks": sum(1 for c in clues if c.rstrip().endswith("?")) / len(clues),
        "n_entries": len(ents),
    }
    b = blog.get(pid, {}).get("entries", {})
    if b:
        typed = [v.get("type", "") for v in b.values() if v.get("type")]
        f["blog_anagram_share"] = sum(1 for t in typed if ANAG.search(t)) / len(typed) if typed else None
        f["blog_typed_share"] = len(typed) / len(ents)
        f["blog_blocks_per_clue"] = sum(len(v.get("blocks") or []) for v in b.values()) / len(ents)
    return f

rows = []
for pid, v in sn.items():
    path = ROOT / "puzzles" / f"{pid}.json"
    if not path.exists(): continue
    puz = read_puzzle_file(path)
    if not all(e.get("solution") for e in puz["entries"]): continue
    rows.append((pid.rsplit("-", 1)[0], v["date"], v["nitch"], feats(pid, puz, v["date"])))

def rho(pairs):
    pairs = [(a, b) for a, b in pairs if a is not None]
    if len(pairs) < 20: return None, len(pairs), None
    a, b = zip(*pairs)
    r = D._spearman(list(a), list(b))
    return r, len(a), math.erfc(abs(r) * math.sqrt(len(a) - 1) / math.sqrt(2))

for series in ("times", "sundaytimes"):
    rs = sorted([r for r in rows if r[0] == series], key=lambda r: r[1])
    cut = int(len(rs) * 0.7)
    print(f"\n{series}: n={len(rs)}, train to {rs[cut-1][1]}, test from {rs[cut][1]}")
    keys = sorted({k for r in rs for k in r[3]})
    for k in keys:
        tr = rho([(r[3].get(k), r[2]) for r in rs[:cut]])
        te = rho([(r[3].get(k), r[2]) for r in rs[cut:]])
        fmt = lambda t: "   n/a" if t[0] is None else f"{t[0]:+.3f} (n={t[1]}, p={t[2]:.3f})"
        print(f"  {k:22s} train {fmt(tr)}   test {fmt(te)}")

# Does anything add beyond weekday? Residualise NITCH on the weekday mean (train
# means only), then fit a least-squares combo on train and score it on test.
import numpy as np
rs = sorted([r for r in rows if r[0] == "times"], key=lambda r: r[1])
cut = int(len(rs) * 0.7)
tr, te = rs[:cut], rs[cut:]
wd = {d: np.mean([r[2] for r in tr if r[3]["weekday"] == d]) for d in range(6)}
print("\ntimes train mean NITCH by weekday:", {d: round(v, 1) for d, v in wd.items()})
base = D.all_scores() if hasattr(D, "all_scores") else {}
def idx(pid): return None
KEYS = ["unknown_word_share", "question_marks", "obscurity", "clue_words", "multiword", "checking"]
print("within-weekday rho (NITCH minus its weekday mean):")
for k in KEYS:
    for name, part in (("train", tr), ("test", te)):
        pass
    a = rho([(r[3][k], r[2] - wd[r[3]["weekday"]]) for r in tr])
    b = rho([(r[3][k], r[2] - wd[r[3]["weekday"]]) for r in te])
    print(f"  {k:22s} train {a[0]:+.3f} p={a[2]:.3f}   test {b[0]:+.3f} p={b[2]:.3f}")
def X(part, keys):
    cols = [[r[3][k] if r[3][k] is not None else 0 for r in part] for k in keys]
    onehot = [[1.0 if r[3]["weekday"] == d else 0.0 for r in part] for d in range(6)]
    return np.array(cols + onehot).T
for keys in ([], ["unknown_word_share", "question_marks"], KEYS):
    Xt, yt = X(tr, keys), np.array([r[2] for r in tr])
    mu, sd = Xt.mean(0), Xt.std(0) + 1e-9
    w, *_ = np.linalg.lstsq(Xt, yt, rcond=None)
    pred = X(te, keys) @ w
    print(f"weekday + {keys or 'nothing'}: test rho {D._spearman(list(pred), [r[2] for r in te]):+.3f}")
def _rk(x):
    x = np.asarray(x, float); o = np.argsort(x, kind="stable"); r = np.empty(len(x)); r[o] = np.arange(len(x))
    for v in np.unique(x):
        m = x == v; r[m] = r[m].mean()
    return r
spearmanr = lambda a, b: (np.corrcoef(_rk(a), _rk(b))[0, 1],)
pearsonr = lambda a, b: (np.corrcoef(a, b)[0, 1],)
yte = [r[2] for r in te]
for keys in ([], ["unknown_word_share", "question_marks"], ["unknown_word_share", "question_marks", "clue_words"]):
    Xt, yt = X(tr, keys), np.array([r[2] for r in tr])
    w, *_ = np.linalg.lstsq(Xt, yt, rcond=None)
    pred = X(te, keys) @ w
    print(f"CHECK {keys}: spearman {spearmanr(pred, yte)[0]:+.3f} pearson {pearsonr(pred, yte)[0]:+.3f} mae {np.mean(np.abs(pred-yte)):.1f} w={np.round(w[:len(keys)],2)}")
# Does OUR index add anything beyond weekday, on the puzzles it fully scores?
rank_, base_ = D.ranks(), D.load_baseline()
ours = {}
for r in rs:
    pid = [k for k, v in sn.items() if v["date"] == r[1] and k.startswith("times-")]
    for k in pid:
        s = D.score(read_puzzle_file(ROOT / "puzzles" / f"{k}.json"), rank_, base_)
        if s:
            ours[r[1]] = s["index"]
allwd = {d: np.mean([r[2] for r in rs if r[3]["weekday"] == d]) for d in range(6)}
sub = [r for r in rs if r[1] in ours]
print(f"OURS annotated n={len(sub)}: rho vs NITCH {D._spearman([ours[r[1]] for r in sub], [r[2] for r in sub]):+.3f}; "
      f"weekday mean vs NITCH {D._spearman([allwd[r[3]['weekday']] for r in sub], [r[2] for r in sub]):+.3f}; "
      f"ours vs NITCH-minus-weekday {D._spearman([ours[r[1]] for r in sub], [r[2]-allwd[r[3]['weekday']] for r in sub]):+.3f}; "
      f"ours vs weekday {D._spearman([ours[r[1]] for r in sub], [r[3]['weekday'] for r in sub]):+.3f}")
z = lambda xs: (np.array(xs) - np.mean(xs)) / np.std(xs)
comb = z([ours[r[1]] for r in sub]) + z([allwd[r[3]['weekday']] for r in sub])
print(f"OURS+WEEKDAY equal weights: rho {D._spearman(list(comb), [r[2] for r in sub]):+.3f}")
