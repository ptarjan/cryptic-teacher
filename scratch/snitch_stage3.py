"""Stage 3: residuals of the index against the SNITCH, and a held-out test harness.

    nice -n 19 python3 scratch/snitch_stage3.py dump      # cache rows to ~/.cache/cryptic-stage3-rows.json
    nice -n 19 python3 scratch/snitch_stage3.py resid     # 15 over- and 15 under-rated
    nice -n 19 python3 scratch/snitch_stage3.py base      # the index held out by date third
    nice -n 19 python3 scratch/snitch_stage3.py cand      # add candidate features to the cache
    nice -n 19 python3 scratch/snitch_stage3.py test [k]  # each candidate added at 0.25, held out

Held out: annotated puzzles split into their own date thirds, each scored
against the NITCH minus the weekday mean of every rated puzzle outside it (the
Sunday Times against the raw NITCH). A candidate's sign is taken from its rank
correlation with the index's rank residual over all of it, so the screen is
optimistic; a shipped component's sign must stand on its own.
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D  # noqa: E402

#: A derived table, so it lives outside the repo.
CACHE = Path.home() / ".cache" / "cryptic-stage3-rows.json"


def dump():
    sn, ctx = D.load_snitch(), D.context()
    rows = []
    for pid, v in sn.items():
        series = pid.rpartition("-")[0]
        path = ROOT / "puzzles" / f"{pid}.json"
        if series not in D.SNITCH_SERIES or not path.exists():
            continue
        puz = D.read_puzzle_file(path)
        s = D.score(puz, ctx)
        rows.append({"pid": pid, "series": series, "date": v["date"], "nitch": v["nitch"],
                     "index": s["index"] if s else None, "z": s["z"] if s else None})
    CACHE.write_text(json.dumps(rows))
    print(len(rows), sum(r["index"] is not None for r in rows))


def rank(xs):
    return D._rank_list(xs)


def heldout(rows, key, series="times"):
    """rho of key vs NITCH minus weekday mean of rated puzzles outside each third."""
    sn = D.load_snitch()
    allr = sorted(((v["date"], v["nitch"]) for p, v in sn.items() if p.rpartition("-")[0] == series))
    ann = sorted((r for r in rows if r["series"] == series and r.get(key) is not None),
                 key=lambda r: r["date"])
    n = len(ann)
    th = [ann[: n // 3], ann[n // 3: 2 * n // 3], ann[2 * n // 3:]]
    out = []
    for t in th:
        lo, hi = t[0]["date"], t[-1]["date"]
        if series == "times":
            by = {}
            for d, x in allr:
                if not lo <= d <= hi:
                    by.setdefault(date.fromisoformat(d).weekday(), []).append(x)
            y = [r["nitch"] - sum(by[date.fromisoformat(r["date"]).weekday()]) /
                 len(by[date.fromisoformat(r["date"]).weekday()]) for r in t]
        else:
            y = [r["nitch"] for r in t]
        out.append(D._spearman([r[key] for r in t], y))
    return out


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "dump":
        dump()
    elif cmd == "base":
        rows = json.loads(CACHE.read_text())
        for s in ("times", "sundaytimes"):
            h = heldout(rows, "index", s)
            print(s, " ".join(f"{x:+.3f}" for x in h), f"mean {sum(h)/3:+.3f}")
    elif cmd == "resid":
        rows = [r for r in json.loads(CACHE.read_text()) if r["series"] == "times" and r["index"] is not None]
        by = {}
        for r in rows:
            by.setdefault(date.fromisoformat(r["date"]).weekday(), []).append(r["nitch"])
        for r in rows:
            wd = date.fromisoformat(r["date"]).weekday()
            r["resid"] = r["nitch"] - sum(by[wd]) / len(by[wd])
        ri, ry = rank([r["index"] for r in rows]), rank([r["resid"] for r in rows])
        n = len(rows)
        for r, a, b in zip(rows, ri, ry):
            r["gap"] = (a - b) / n  # >0: index says harder than solvers found
        rows.sort(key=lambda r: -r["gap"])
        for label, sel in (("OVER-RATED", rows[:15]), ("UNDER-RATED", rows[-15:][::-1])):
            print(label)
            for r in sel:
                print(f"  {r['pid']} {r['date']} nitch {r['nitch']:.0f} resid {r['resid']:+.0f} "
                      f"index {r['index']:+.2f} gap {r['gap']:+.2f} "
                      + " ".join(f"{k[:4]}{v:+.1f}" for k, v in sorted(r["z"].items())))


ENUM = __import__("re").compile(r"\s*\([\d,.\s\-–']+\)\s*$")
DEFONLY = {"double definition", "cryptic definition", "&lit"}
GIVEN = {"anagram", "hidden word"}


def cand(puz):
    """Candidate features, from answers, grid, clue text and our annotation."""
    import re
    ents = [e for e in puz["entries"] if e.get("solution")]
    cells = sum(e["length"] for e in ents) or 1
    types = []
    for e in ents:
        t = [p.strip().lower() for p in ((e.get("annotation") or {}).get("type") or "").split("+") if p.strip()]
        types.append(t)
    clues = [ENUM.sub("", e.get("clue") or "").strip() for e in ents]
    real = [(e, c, t) for e, c, t in zip(ents, clues, types) if c and not re.match(r"(?i)^see\b", c)]
    defs = [D.definition_key((e.get("annotation") or {}).get("definition")) for e, _, _ in real]
    defs = [d for d in defs if d]
    multi = [bool(e.get("separatorLocations")) for e in ents]
    f = {
        "phrase_cells": sum(e["length"] for e, m in zip(ents, multi) if m) / cells,
        "long12_cells": sum(e["length"] for e in ents if e["length"] >= 12) / cells,
        "long_phrase_cells": sum(e["length"] for e, m in zip(ents, multi) if m and e["length"] >= 10) / cells,
        "defonly_share": sum(1 for t in types if t and set(t) <= DEFONLY) / max(1, sum(1 for t in types if t)),
        "dd_share": sum(1 for t in types if t == ["double definition"]) / max(1, sum(1 for t in types if t)),
        "cd_share": sum(1 for t in types if t == ["cryptic definition"]) / max(1, sum(1 for t in types if t)),
        "given_cells": sum(e["length"] for e, t in zip(ents, types) if t and set(t) & GIVEN) / cells,
        "anagram_cells": sum(e["length"] for e, t in zip(ents, types) if "anagram" in t) / cells,
        "pure_anagram_cells": sum(e["length"] for e, t in zip(ents, types) if t == ["anagram"]) / cells,
        "short_clue_share": sum(1 for _, c, _ in real if len(c.split()) <= 4) / max(1, len(real)),
        "clue_words": sum(len(c.split()) for _, c, _ in real) / max(1, len(real)),
        "words_per_letter": sum(len(c.split()) / e["length"] for e, c, _ in real) / max(1, len(real)),
        "def_words": sum(len(d.split()) for d in defs) / max(1, len(defs)),
        "def_one_word": sum(1 for d in defs if len(d.split()) == 1) / max(1, len(defs)),
        "answer_len": cells / max(1, len(ents)),
        "qmark_share": sum(1 for _, c, _ in real if c.endswith("?")) / max(1, len(real)),
    }
    return f


def dump_cand():
    rows = json.loads(CACHE.read_text())
    for r in rows:
        if r["index"] is None:
            continue
        r["cand"] = cand(D.read_puzzle_file(ROOT / "puzzles" / f"{r['pid']}.json"))
    CACHE.write_text(json.dumps(rows))


def with_new(rows, key, w=0.25, sign=1, pool=None):
    """index with key added at weight w, z-scored over pool (default: rows)."""
    pool = [r for r in (pool or rows) if r.get("cand")]
    xs = [r["cand"][key] for r in pool]
    m = sum(xs) / len(xs)
    sd = (sum((x - m) ** 2 for x in xs) / len(xs)) ** .5 or 1
    for r in rows:
        if r["index"] is None:
            r["new"] = None
            continue
        tot = sum(D.WEIGHTS[k] for k in r["z"])
        z = sign * (r["cand"][key] - m) / sd
        r["new"] = (r["index"] * tot + w * z) / (tot + w)


def test_all(keys):
    rows = json.loads(CACHE.read_text())
    base = {s: heldout(rows, "index", s) for s in ("times", "sundaytimes")}
    print(f"{'':22s} {'times thirds':>22s} mean | {'sunday thirds':>22s} mean | raw rho resid(times)")
    for s in base:
        pass
    print(f"{'index':22s} " + " ".join(f"{x:+.3f}" for x in base["times"]) + f" {sum(base['times'])/3:+.3f} | "
          + " ".join(f"{x:+.3f}" for x in base["sundaytimes"]) + f" {sum(base['sundaytimes'])/3:+.3f}")
    tr = [r for r in rows if r["series"] == "times" and r.get("cand")]
    by = {}
    for r in tr:
        by.setdefault(date.fromisoformat(r["date"]).weekday(), []).append(r["nitch"])
    y = [r["nitch"] - sum(by[date.fromisoformat(r["date"]).weekday()]) / len(by[date.fromisoformat(r["date"]).weekday()]) for r in tr]
    for k in keys:
        raw = D._spearman([r["cand"][k] for r in tr], y)
        # partial: against the rank residual of the index
        ri, ry = rank([r["index"] for r in tr]), rank(y)
        gap = [b - a for a, b in zip(ri, ry)]
        part = D._spearman([r["cand"][k] for r in tr], gap)
        sign = 1 if part > 0 else -1
        with_new(rows, k, sign=sign)
        t = heldout(rows, "new", "times")
        s = heldout(rows, "new", "sundaytimes")
        print(f"{('+' if sign > 0 else '-') + k:22s} " + " ".join(f"{x:+.3f}" for x in t) + f" {sum(t)/3:+.3f} | "
              + " ".join(f"{x:+.3f}" for x in s) + f" {sum(s)/3:+.3f} | {raw:+.3f} vs-gap {part:+.3f}")


if __name__ == "__main__" and sys.argv[1] == "cand":
    dump_cand()
if __name__ == "__main__" and sys.argv[1] == "test":
    test_all(sys.argv[2:] or list(next(r["cand"] for r in json.loads(CACHE.read_text()) if r.get("cand"))))
