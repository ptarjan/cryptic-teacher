"""Per-clue difficulty features against YouTube solvers' waits, held out by puzzle.

    nice -n 19 python3 scratch/solver_clues.py dump   # per-clue rows -> ~/.cache/cryptic-solver-clues.json
    nice -n 19 python3 scratch/solver_clues.py test   # train/held-out rho per feature and per model

Target: each clue's wait from reading to solving, as a percentile within its
video, averaged over the expert and intermediate channels (CHANNELS; the
beginner channels' waits are mostly explanation). A puzzle solved on several
channels averages them. Every feature is ranked within its puzzle too, so a
puzzle's overall pace cancels and only which clues in it are slow is scored.
Puzzles split into train and held-out by a hash of the id, never clues, so no
puzzle's clues sit on both sides.

The same per-clue features are also scored against two targets we did not
build: Times for the Times commenters' "hard" mentions per clue (within
puzzle, posts with >= 10 comments) and No More Marking's comparative-judgement
scores for 464 Guardian clues (text-only features, pooled).

Result (2026-09-30, 581 puzzles / 12,908 clues with a wait; 203 puzzles held
out): the shipped per-clue composite scores held-out +.142 (TftT hard +.129,
NMM +.192 on its text-only parts). Answer length alone +.176 held out, and at
0.25 lifts the composite to +.180 and NMM to +.257 but drops TftT hard to
+.119; blocks per clue +.088 and machinery -> blocks +.152. Nothing else
clears +.08 held out: device flags, definition position, apt definition,
joke, misdirection all |rho| <= .06. Screened as puzzle components in
scratch/snitch_stage13.py, where all lose the adoption rule.
"""
import collections
import csv
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D
import ctc_transcripts as C
import puzzle_paths
from fetch_puzzle import read_puzzle_file

CACHE = Path(os.environ.get("SOLVER_ROWS") or Path.home() / ".cache" / "cryptic-solver-clues.json")
CHANNELS = ("ctc", "pat_cousins", "cryptics_uncovered", "lucyverbalist")
NMM = Path("/Users/pt/.cryptic-teacher/nmm")
MIN_CLUES = 8
DEVICES = ("anagram", "hidden_word", "cryptic_definition", "double_definition", "homophone",
           "reversal", "container", "charade", "deletion", "letter_selection", "and_lit",
           "spoonerism", "substitution")


def held(pid):
    return int(hashlib.md5(pid.encode()).hexdigest(), 16) % 3 == 0


def target():
    got = collections.defaultdict(list)
    for ch in CHANNELS:
        for k, v in C.wait_percentiles(ch).items():
            got[k].append(v)
    return {k: sum(v) / len(v) for k, v in got.items()}


def text_features(clue, sol, enum_words):
    """Features readable from the clue text and answer alone (NMM has no more)."""
    words = re.findall(r"[A-Za-z']+", clue)
    body = clue.strip().rstrip("\"'”’)")
    return {"length": len(sol), "answer_words": enum_words,
            "clue_words": len(words),
            "clue_letters_ratio": sum(len(w) for w in words) / max(1, len(sol)),
            "exclaim": float(body.endswith("!")),
            "midcaps": sum(1 for w in words[1:] if w[0].isupper()),
            "vowel_share": sum(c in "AEIOU" for c in sol) / max(1, len(sol))}


def features(puz, rank, blog_defs):
    base = C.clue_features(puz, rank, blog_defs)
    out = {}
    for e in puz["entries"]:
        eid = D.entry_id(e)
        if eid not in base:
            continue
        sol, ws = D.answer_words(e)
        clue = e["clue"].get("text", "").strip()
        f = dict(base[eid])
        f.update(text_features(clue, sol, len(ws)))
        ann = e.get("annotation") or {}
        types = ann.get("type") or []
        feats = ann.get("features") or {}
        if types:
            for d in DEVICES:
                f["dev_" + d] = float(d in types)
            f["n_devices"] = len(types)
            f["n_indicators"] = len(ann.get("indicators") or [])
            f["n_blocks"] = len(ann.get("blocks") or [])
            f["apt_definition"] = float(bool(feats.get("aptDefinition")))
            f["joke"] = float(bool(feats.get("joke")))
            f["misdirected"] = float(bool(feats.get("misdirectedWord")))
            f["answer_in_scene"] = float(bool(feats.get("answerInScene")))
            defs = ann.get("definitions") or []
            if len(defs) == 1 and clue:
                d = defs[0]
                at, dl = d.get("at"), len(d.get("text") or "")
                if at is not None and dl and dl < len(clue) - 2:
                    f["def_at_end"] = float(at + dl >= len(clue) - 2)
                    f["def_length_ratio"] = len(D.letters(d["text"])) / max(1, len(sol))
                    f["def_words"] = len((d.get("text") or "").split())
        out[eid] = f
    return out


def dump():
    tgt = target()
    tftt = json.loads((ROOT / "tools/data/blog_comment_difficulty.json").read_text())
    rank, blog_defs = D.ranks(), D.blog_definitions()
    pids = {p for p, _ in tgt}
    pids |= {p for p, t in tftt.items() if t["comments"] >= 10 and p.startswith("times-")}
    rows = []
    for pid in sorted(pids):
        path = puzzle_paths.find(pid)
        if not path:
            continue
        puz = read_puzzle_file(path)
        t = tftt.get(pid)
        for eid, f in features(puz, rank, blog_defs).items():
            hard = None
            if t and t["comments"] >= 10:
                hard = t["clues"].get(eid, [0, 0, 0])[1]
            rows.append({"pid": pid, "eid": eid, "wait": tgt.get((pid, eid)), "hard": hard, "f": f})
    CACHE.write_text(json.dumps(rows))
    print(len(rows), "clue rows,", len({r["pid"] for r in rows}), "puzzles,",
          sum(r["wait"] is not None for r in rows), "with a wait")


def ranks(xs):
    return C._ranks(xs)


def within(rows, key, getter):
    """Pooled (feature pct, target pct) pairs, both ranked within each puzzle."""
    by = collections.defaultdict(list)
    for r in rows:
        x, y = getter(r), r[key]
        if x is not None and y is not None:
            by[r["pid"]].append((x, y))
    xs, ys = [], []
    for pairs in by.values():
        if len(pairs) < MIN_CLUES or len({p[0] for p in pairs}) < 2:
            continue
        xs += ranks([p[0] for p in pairs])
        ys += ranks([p[1] for p in pairs])
    return xs, ys


def rho(rows, key, getter):
    xs, ys = within(rows, key, getter)
    return (D._spearman(xs, ys) if len(xs) > 30 else float("nan")), len(xs)


def model(weights):
    """A fixed-weight sum of within-puzzle feature percentiles, each a
    feature's percentile among the clues of its puzzle that carry it; a
    missing feature drops out and its weight is redistributed."""
    def build(rows):
        by = collections.defaultdict(list)
        for r in rows:
            by[r["pid"]].append(r)
        out = {}
        for pid, rs in by.items():
            pct = {}
            for f, (w, sign) in weights.items():
                known = [(i, r["f"].get(f)) for i, r in enumerate(rs) if r["f"].get(f) is not None]
                if len(known) >= MIN_CLUES and len({v for _, v in known}) > 1:
                    p = ranks([sign * v for _, v in known])
                    pct[f] = dict(zip([i for i, _ in known], p))
            for i, r in enumerate(rs):
                parts = [(weights[f][0], pct[f][i]) for f in pct if i in pct[f]]
                out[(pid, r["eid"])] = sum(w * x for w, x in parts) / sum(w for w, _ in parts) if parts else None
        return lambda r: out.get((r["pid"], r["eid"]))
    return build


#: The shipped per-clue composite: tools/ctc_transcripts.py CLUE_WEIGHTS at the index's weights.
BASE = {f: (D.WEIGHTS[w], +1) for f, w in C.CLUE_WEIGHTS.items()}


def nmm_rows():
    """(features, scaledScore, clue_type) for the NMM clues, text features only."""
    scores = {}
    with open(NMM / "results_task_persons.csv") as fh:
        for r in csv.DictReader(fh):
            scores[r["firstName"]] = float(r["scaledScore"])
    rank = D.ranks()
    out = []
    with open(NMM / "clues_unified_sample.csv") as fh:
        for r in csv.DictReader(fh):
            key = f"{r['date'][:4]}_{r['clue_number']}_{r['direction']}"
            if key not in scores or not r["solution"]:
                continue
            sol = D.letters(r["solution"]).upper()
            ws = [w for w in re.split(r"[\s\-]+", r["solution"]) if w]
            clue = re.sub(r"\s*\([\d,\-\s]+\)\s*$", "", r["clue_text"])
            f = text_features(clue, sol, len(ws))
            low = sol.lower()
            rk = rank[low] if low in rank else max(rank.get(D.letters(w), D.MISSING_RANK) for w in ws)
            f["rarity"] = math.log10(max(rk, 10))
            f["question_mark"] = float(clue.strip().rstrip("\"'”’)").endswith("?"))
            out.append((f, scores[key], r["clue_type"]))
    return out


def test():
    rows = json.loads(CACHE.read_text())
    yt = [r for r in rows if r["wait"] is not None]
    train, hold = [r for r in yt if not held(r["pid"])], [r for r in yt if held(r["pid"])]
    hard = [r for r in rows if r["hard"] is not None]
    nmm = nmm_rows()
    print(f"YouTube: {len({r['pid'] for r in train})} train / {len({r['pid'] for r in hold})} held-out puzzles, "
          f"{len(train)}/{len(hold)} clues; TftT hard: {len({r['pid'] for r in hard})} puzzles; NMM {len(nmm)} clues")
    names = sorted({k for r in rows for k in r["f"]})
    print(f"\n{'feature':20s} {'train':>7s} {'held':>7s} {'n_held':>6s} {'tftt':>7s} {'nmm':>7s}")
    for f in names:
        g = lambda r, f=f: r["f"].get(f)
        a, _ = rho(train, "wait", g)
        b, n = rho(hold, "wait", g)
        c, _ = rho(hard, "hard", g)
        nm = [(x[0][f], x[1]) for x in nmm if f in x[0]]
        d = D._spearman(*zip(*nm)) if len(nm) > 30 else float("nan")
        print(f"{f:20s} {a:+7.3f} {b:+7.3f} {n:6d} {c:+7.3f} {d:+7.3f}")
    return rows, train, hold, hard, nmm


def evaluate(label, weights, train, hold, hard, nmm=None):
    m = model(weights)
    out = []
    for rs, key in ((train, "wait"), (hold, "wait"), (hard, "hard")):
        out.append(rho(rs, key, m(rs))[0])
    s = f"{label:34s} train {out[0]:+.3f}  held {out[1]:+.3f}  tftt-hard {out[2]:+.3f}"
    if nmm is not None:
        ws = {f: w for f, w in weights.items() if all(f in x[0] for x in nmm)}
        if ws:
            # rank each feature over the NMM pool, then weight
            pct = {f: ranks([s_ * x[0][f] for x in nmm]) for f, (w, s_) in ws.items()}
            comp = [sum(ws[f][0] * pct[f][i] for f in ws) / sum(ws[f][0] for f in ws) for i in range(len(nmm))]
            s += f"  nmm {D._spearman(comp, [x[1] for x in nmm]):+.3f} ({'+'.join(sorted(ws))})"
    print(s)
    return out


if __name__ == "__main__":
    if sys.argv[1] == "dump":
        dump()
    else:
        rows, train, hold, hard, nmm = test()
        print()
        evaluate("shipped composite", BASE, train, hold, hard, nmm)
