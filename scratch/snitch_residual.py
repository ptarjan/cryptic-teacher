"""What predicts SNITCH difficulty beyond the weekday, on annotated Times puzzles.

Target: NITCH minus the mean NITCH of its series and weekday, the means taken
from the training part only. That residual is the part of difficulty the
Times's weekly ramp does not explain, and so the part that should carry to
series without one. Split by date, 70/30 per series; times and sundaytimes are
pooled after residualising. Fit nothing: each candidate reports Spearman rho on
train and test separately, and counts only if the sign holds and test p < 0.05.

Result, 2026-09-26 (times n=128, sundaytimes n=97): the pooled 70/30 split
flatters everything, because its test third is Aug-Sep 2026 and nearly every
feature is flat on train and strong on test. By date tercile within series,
the signal that holds in all three Times-daily thirds is how much machinery a
clue carries: indicators per clue +0.23/+0.21/+0.19 (all +0.22, p=0.014),
clue length in words +0.22, share of 3-device clues +0.20. Our index is +0.13
(p=0.14) against the residual, its device term +0.15, obscurity +0.06,
checking ~0. The Sunday Times residual tracks nothing (every |rho| <= 0.10 over
its full span). Too few rated puzzles to fit weights; this ranks candidates.

Run: python3 scratch/snitch_residual.py"""
import datetime
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D  # noqa: E402

sn = json.loads((ROOT / "tools/data/snitch.json").read_text())
rank, base = D.ranks(), D.load_baseline()
LETTER_SEL = {"first letter", "first letters", "last letter", "last letters", "middle letter",
              "middle letters", "outer letters", "alternate letters", "regular letters"}


def share(xs, f):
    return sum(1 for x in xs if f(x)) / len(xs) if xs else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def topk(xs, k=5):
    xs = sorted((x for x in xs if x is not None), reverse=True)[:k]
    return sum(xs) / len(xs) if xs else None


def feats(puz):
    s = D.score(puz, rank, base)
    if not s:
        return None
    anns, costs, logr = [], [], []
    for e in puz["entries"]:
        a = e.get("annotation") or {}
        parts = [p.strip().lower() for p in (a.get("type") or "").split("+") if p.strip()]
        if not parts:
            continue
        pieces = [str(p) for p in (a.get("pieces") or [])]
        clue = re.sub(r"\s*\([\d,\s\-–]+\)\s*$", "", e.get("clue") or "")
        cw = clue.split()
        d = (a.get("definition") or "").strip().lower()
        low = clue.lower()
        pos = low.find(d) if d else -1
        edge = pos == 0 or (pos >= 0 and low[pos + len(d):].strip(" ?!.,;:'\"") == "")
        ftr = a.get("features") if isinstance(a.get("features"), dict) else {}
        recog = max(D.DEVICE_COST.get(p, D.DEVICE_DEFAULT) for p in parts)
        c = recog + D.STACKING_COST * (len(parts) - 1)
        if not a.get("indicators") and not set(parts) & D.ALWAYS_UNINDICATED:
            c += D.UNINDICATED_COST
        c += D.SEAM_COST * max(0, len(pieces) - 2)
        c += D.OPAQUE_PIECE_COST * sum(1 for p in pieces if 0 < len([ch for ch in p if ch.isalpha()]) <= D.OPAQUE_LEN)
        costs.append(min(1.0, c))
        ws = (e.get("solution") or "").upper().split()
        if ws:
            logr.append(math.log10(max(max(rank.get(w.strip("'-"), D.MISSING_RANK) for w in ws), 10)))
        anns.append(dict(parts=parts, recog=recog, pieces=len(pieces),
                         opaque=sum(1 for p in pieces if 0 < len([ch for ch in p if ch.isalpha()]) <= 2),
                         ind=len(a.get("indicators") or []), link=bool(a.get("linkWords")),
                         defw=len(d.split()), defratio=len(d.split()) / max(len(cw), 1),
                         mid=pos > 0 and not edge, cw=len(cw), q=clue.rstrip().endswith("?"),
                         mis=bool(ftr.get("misdirectedWord")), scene=bool(ftr.get("answerInScene")),
                         joke=bool(ftr.get("joke")), apt=bool(ftr.get("aptDefinition"))))
    has = lambda t: lambda x: t in x["parts"]
    return {
        "index": s["index"], **{"z_" + k: v for k, v in s["z"].items()},
        "device_top5": topk(costs), "device_max": max(costs),
        "device_sd": (mean([(c - mean(costs)) ** 2 for c in costs]) or 0) ** 0.5,
        "recognition": mean([x["recog"] for x in anns]),
        "multi_device": share(anns, lambda x: len(x["parts"]) >= 2),
        "three_device": share(anns, lambda x: len(x["parts"]) >= 3),
        "pieces": mean([x["pieces"] for x in anns]),
        "opaque_pieces": mean([x["opaque"] for x in anns]),
        "indicators": mean([x["ind"] for x in anns]),
        "unindicated": share(anns, lambda x: x["ind"] == 0),
        "link_words": share(anns, lambda x: x["link"]),
        "def_words": mean([x["defw"] for x in anns]),
        "def_ratio": mean([x["defratio"] for x in anns]),
        "def_mid": share(anns, lambda x: x["mid"]),
        "clue_words": mean([x["cw"] for x in anns]),
        "question_marks": share(anns, lambda x: x["q"]),
        "misdirected": share(anns, lambda x: x["mis"]),
        "answer_in_scene": share(anns, lambda x: x["scene"]),
        "joke": share(anns, lambda x: x["joke"]),
        "apt_definition": share(anns, lambda x: x["apt"]),
        "rarity_top5": topk(logr), "rarity_mean": mean(logr),
        "unknown_words": share(logr, lambda r: r >= math.log10(D.MISSING_RANK)),
        **{"t_" + k: share(anns, has(k)) for k in ("anagram", "charade", "container", "deletion",
                                                  "reversal", "hidden word", "homophone",
                                                  "double definition", "cryptic definition", "&lit")},
        "t_letter_selection": share(anns, lambda x: bool(set(x["parts"]) & LETTER_SEL)),
    }


rows = []
for pid, v in sn.items():
    series = pid.rsplit("-", 1)[0]
    path = ROOT / "puzzles" / f"{pid}.json"
    if series not in D.SNITCH_SERIES or not path.exists():
        continue
    f = feats(D.read_puzzle_file(path))
    if f:
        rows.append(dict(series=series, date=v["date"], nitch=v["nitch"],
                         wd=datetime.date.fromisoformat(v["date"]).weekday(), f=f))

train, test = [], []
for series in D.SNITCH_SERIES:
    rs = sorted((r for r in rows if r["series"] == series), key=lambda r: r["date"])
    cut = int(len(rs) * 0.7)
    tr, te = rs[:cut], rs[cut:]
    means = {}
    for r in tr:
        means.setdefault(r["wd"], []).append(r["nitch"])
    means = {k: sum(v) / len(v) for k, v in means.items()}
    for r in rs:
        r["resid"] = r["nitch"] - means.get(r["wd"], sum(means.values()) / len(means))
    train += tr
    test += te
    print(f"{series}: n={len(rs)} train to {tr[-1]['date']}, test from {te[0]['date']}")


def rho(part, k):
    pairs = [(r["f"].get(k), r["resid"]) for r in part if r["f"].get(k) is not None]
    if len(pairs) < 15:
        return None, len(pairs), None
    a, b = zip(*pairs)
    if len(set(a)) < 3:
        return None, len(pairs), None
    r = D._spearman(list(a), list(b))
    return r, len(a), math.erfc(abs(r) * math.sqrt(len(a) - 1) / math.sqrt(2))


out = []
for k in sorted({k for r in rows for k in r["f"]}):
    a, b = rho(train, k), rho(test, k)
    if a[0] is None or b[0] is None:
        continue
    ok = (a[0] > 0) == (b[0] > 0) and b[2] < 0.05
    out.append((k, a, b, ok))
out.sort(key=lambda t: -abs(t[2][0]) if t[3] else 1 - abs(t[2][0]))
print(f"\nrho vs NITCH-minus-weekday, pooled times+sundaytimes (train n={len(train)}, test n={len(test)}):")
for k, a, b, ok in out:
    print(f"  {'*' if ok else ' '} {k:20s} train {a[0]:+.3f} (p={a[2]:.3f})   test {b[0]:+.3f} (p={b[2]:.3f}, n={b[1]})")

# Train is flat and test is not, for nearly every feature. Is it the period or
# the series? Terciles by date within each series, residuals from all of it.
print("\nrho vs residual by series and date tercile (residual from each series' own full-period weekday means):")
KEYS = ["index", "z_device", "z_obscurity", "clue_words", "three_device", "indicators", "device_top5", "link_words"]
for series in D.SNITCH_SERIES:
    rs = sorted((r for r in rows if r["series"] == series), key=lambda r: r["date"])
    m = {}
    for r in rs:
        m.setdefault(r["wd"], []).append(r["nitch"])
    for r in rs:
        r["resid"] = r["nitch"] - sum(m[r["wd"]]) / len(m[r["wd"]])
    n = len(rs)
    thirds = [rs[: n // 3], rs[n // 3: 2 * n // 3], rs[2 * n // 3:]]
    print(f"  {series}: " + " | ".join(f"{t[0]['date']}..{t[-1]['date']} n={len(t)}" for t in thirds))
    for k in KEYS:
        print(f"    {k:14s} " + "  ".join(f"{(rho(t, k)[0] or 0):+.2f}" for t in thirds)
              + f"   all {rho(rs, k)[0]:+.2f} (p={rho(rs, k)[2]:.3f})")
