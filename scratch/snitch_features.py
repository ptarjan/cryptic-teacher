"""Candidate puzzle features against the SNITCH, on every rated Times puzzle we hold.

    nice -n 19 python3 scratch/snitch_features.py

Not only the annotated puzzles: every SNITCH-rated Times daily and Sunday Times
with a full set of answers. Features come from the answers, the grid, the clue
text, and tools/data/blog_facts/ (the blogger's underlined definition, named
type, marked indicators and wordplay blocks). Nothing here reads an annotation,
so every row can be computed wherever a puzzle has answers, and the blog rows
wherever a blog writes it up.

Targets, per series:
  resid    NITCH minus the series' mean NITCH for that weekday
  raw      the NITCH itself
  minutes  median solving time stated in Times for the Times comments (>= 3)
  dnf      share of those comments that report not finishing
minutes and dnf are measured outcomes, Times only; they are targets, never
features.

Each feature gets Spearman rho against resid in each date third (oldest first)
and overall, then overall against raw, minutes and dnf. PORT says what the
feature needs: "grid", "answers" and "clue" exist for every series we file;
"blog" exists where a blog writes the puzzle up (Times for the Times for the
Times, fifteensquared for the Guardian, Independent and FT); "times" is
Times-only and never counts toward a portable model.

Held out: for each date third in turn, the other two pick the five portable
features with the largest |rho| against resid whose sign agrees in both, z-score
them on those two thirds, and sum them sign-weighted with equal weight. That
sum's rho on the held-out third is compared with the current index's, on the
annotated puzzles the index scores, and on every puzzle for the combination.
"""
import collections
import itertools
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D

PUZ = ROOT / "puzzles"
BLOG = ROOT / "tools" / "data" / "blog_facts"
COMMENTS = ROOT / "tools" / "data" / "blog_comment_difficulty.json"
LUFZ = ROOT / "tools" / "data" / "lufz-en-lexicon.js"
ABBR = ROOT / "tools" / "data" / "abbreviations.json"
RARE_LETTERS = set("JQXZKVW")
LETTER_SELECT = {"first letter", "first letters", "last letter", "last letters", "outer letters",
                 "alternate letters", "middle letter", "middle letters"}
TYPES = ["charade", "container", "anagram", "deletion", "reversal", "double definition",
         "hidden word", "homophone", "cryptic definition", "spoonerism"]
TOP_K = 5
ENUM = re.compile(r"\s*\([\d,.\s\-–']+\)\s*$")


def letters(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def load_lufz():
    """letters-only key -> (rank, proper), over Lufz's full list: phrases and proper nouns included."""
    t = LUFZ.read_text(encoding="utf-8")
    i = t.index("JSON.parse(`") + len("JSON.parse(`")
    lex = json.loads(t[i:t.index("`)", i)])["lexicon"]
    out = {}
    for rank, w in enumerate(lex):
        k = letters(w)
        if not k:
            continue
        proper = w[:1].isupper()
        if k not in out:
            out[k] = [rank, proper]
        elif not proper:
            out[k][1] = False  # a lowercase form exists, so not only a name
    return out


def load_family():
    fam = {}
    for line in (ROOT / "tools/data/lexicon.tsv").open(encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 4 and p[1].isdigit():
            fam[p[0]] = int(p[3])
    return fam


def corpus():
    """Every puzzle file: {pid: (series, {entry id: answer})}. One pass, ~25 s."""
    out = {}
    for f in PUZ.glob("*.json"):
        if f.name == "index.json":
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(p, dict) or "entries" not in p:
            continue
        out[f.stem] = (p.get("series"), {e.get("id"): letters(e.get("solution")) for e in p["entries"]})
    return out


def load_blog():
    out = {}
    for f in BLOG.glob("*.json"):
        out.update(json.loads(f.read_text(encoding="utf-8")))
    return out


def norm(s):
    return " ".join(re.findall(r"[a-z]+", (s or "").lower()))


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def share(xs):
    xs = [x for x in xs if x is not None]
    return sum(1 for x in xs if x) / len(xs) if xs else None


def grid_feats(puz):
    used = collections.Counter()
    cells_of = []
    for e in puz["entries"]:
        x, y = e["position"]["x"], e["position"]["y"]
        dx, dy = (1, 0) if e["direction"] == "across" else (0, 1)
        cells = [(x + dx * i, y + dy * i) for i in range(e["length"])]
        used.update(cells)
        cells_of.append(cells)
    unch, dbl, first_unch, low_check = [], [], [], []
    for cells in cells_of:
        ch = [used[c] >= 2 for c in cells]
        unch.append(ch.count(False) / len(ch))
        dbl.append(any(not a and not b for a, b in itertools.pairwise(ch)))
        first_unch.append(not ch[0])
        low_check.append(sum(ch) / len(ch) < 0.5)
    return {"unch_share": mean(unch), "double_unch_share": share(dbl),
            "first_letter_unch": share(first_unch), "under_half_checked": share(low_check),
            "n_entries": len(cells_of), "white_cells": len(used)}


def answer_feats(puz, rank, lufz, fam, count, freq):
    rar, whole, missing, proper, polys, seen, fresh, lfreq, rare = [], [], [], [], [], [], [], [], []
    for e in puz["entries"]:
        sol = letters(e.get("solution"))
        if not sol:
            continue
        words = [w for w in re.split(r"[\s\-]+", (e.get("annotation") or {}).get("answer") or "") if w]
        if not words:
            # Split the letters where the enumeration does.
            cuts = sorted(i for v in (e.get("separatorLocations") or {}).values() for i in v)
            words, prev = [], 0
            for c in cuts + [len(sol)]:
                words.append(sol[prev:c])
                prev = c
        words = [letters(w) for w in words if letters(w)]
        worst = max(rank.get(w, D.MISSING_RANK) for w in words)
        rar.append(math.log10(max(worst, 10)))
        hit = lufz.get(sol)
        whole.append(math.log10(max(hit[0] if hit else 300000, 10)))
        missing.append(hit is None)
        proper.append(bool(hit and hit[1]))
        if len(words) == 1 and sol in fam:
            polys.append(math.log(1 + fam[sol]))
        c = count.get(sol, 1) - 1  # other puzzles holding this answer
        seen.append(math.log1p(c))
        fresh.append(c == 0)
        lfreq.append(mean([freq[ch] for ch in sol]))
        rare.append(sum(ch in RARE_LETTERS for ch in sol) / len(sol))
    lens = [e["length"] for e in puz["entries"]]
    multi = [bool(e.get("separatorLocations")) for e in puz["entries"]]
    worst3 = sorted(whole)[-3:]
    return {"obscurity_rarest_word": mean(rar), "obscurity_whole_answer": mean(whole),
            "obscurity_worst3": mean(worst3), "not_in_lufz": share(missing),
            "proper_noun_share": share(proper), "answer_polysemy": mean(polys),
            "answer_corpus_log_count": mean(seen), "answer_never_seen_elsewhere": share(fresh),
            "letter_logfreq": mean(lfreq), "rare_letter_share": mean(rare),
            "answer_len": mean(lens), "long_answer_share": share([n >= 10 for n in lens]),
            "multiword_share": share(multi)}


def clue_texts(puz):
    return [ENUM.sub("", e.get("clue") or "").strip() for e in puz["entries"]]


def clue_feats(puz):
    cl = clue_texts(puz)
    real = [c for c in cl if c and not re.match(r"(?i)^see\b", c)]
    wc = [len(c.split()) for c in real]
    lens = [e["length"] for e, c in zip(puz["entries"], cl) if c and not re.match(r"(?i)^see\b", c)]
    caps = []
    for c in real:
        ws = re.findall(r"[A-Za-z][\w'’]*", c)
        caps.append(sum(w[0].isupper() for w in ws[1:]) / max(1, len(ws) - 1))
    return {"clue_words": mean(wc), "clue_chars": mean([len(c) for c in real]),
            "words_per_letter": mean([w / n for w, n in zip(wc, lens)]),
            "short_clue_share": share([w <= 4 for w in wc]),
            "question_mark_share": share([c.endswith("?") for c in real]),
            "exclamation_share": share([c.endswith("!") for c in real]),
            "midclue_capitals": mean(caps),
            "linked_entry_share": share([bool(re.match(r"(?i)^see\b", c)) or not c for c in cl])}


def blog_feats(puz, bf, abbr, lufz, pair_count):
    ents = (bf or {}).get("entries") or {}
    if not ents:
        return {}
    by_id = {e["id"]: e for e in puz["entries"]}
    typed, parts_n, blocks, blen, short, abbrs, inds = [], [], [], [], [], [], []
    dwords, dshare, dstart, dend, dwhole, dq, drare, dfam, dsplit = [], [], [], [], [], [], [], [], []
    tshare = collections.Counter()
    for eid, v in ents.items():
        e = by_id.get(eid)
        if not e:
            continue
        clue = ENUM.sub("", e.get("clue") or "").strip()
        t = [p.strip() for p in (v.get("type") or "").split("+") if p.strip()]
        if t:
            typed.append(t)
            parts_n.append(len(t))
        b = v.get("blocks") or []
        if b:
            blocks.append(len(b))
            for L, _ in b:
                n = len(letters(L))
                blen.append(n)
                short.append(n <= 2)
                abbrs.append(n <= 3 and letters(L) in abbr)
        inds.append(len(v.get("indicators") or []))
        defs = [d for d in (v.get("definition") or []) if d]
        if defs and clue:
            cw = len(clue.split())
            nw = sum(len(d.split()) for d in defs)
            dwords.append(nw)
            dshare.append(nw / cw)
            dwhole.append(nw / cw >= 0.9)
            dsplit.append(len(defs) >= 2)
            lo, hi = norm(clue), [norm(d) for d in defs]
            dstart.append(any(lo.startswith(h) for h in hi))
            dend.append(any(lo.endswith(h) for h in hi))
            dq.append(any(d.rstrip().endswith("?") for d in defs))
            ws = [letters(w) for w in defs[0].split() if letters(w)]
            if ws:
                drare.append(math.log10(max(max((lufz.get(w) or [300000])[0] for w in ws), 10)))
            sol = letters(e.get("solution"))
            dfam.append(math.log1p(pair_count.get((sol, norm(defs[0])), 1) - 1))
    for t in typed:
        for p in set(t):
            tshare[p] += 1
    n_t = len(typed)
    f = {"blog_typed_share": n_t / len(puz["entries"]),
         "blog_multi_device_share": share([n >= 2 for n in parts_n]),
         "blog_three_device_share": share([n >= 3 for n in parts_n]),
         "blog_parts_per_typed": mean(parts_n),
         "blog_blocks_per_blocked": mean(blocks),
         "blog_block_letters": mean(blen),
         "blog_short_block_share": share(short),
         "blog_abbrev_block_share": share(abbrs),
         "blog_indicators_per_clue": mean(inds),
         "def_words": mean(dwords), "def_share_of_clue": mean(dshare),
         "def_whole_clue_share": share(dwhole), "def_split_share": share(dsplit),
         "def_at_start_share": share(dstart), "def_at_end_share": share(dend),
         "def_question_share": share(dq), "def_rarest_word": mean(drare),
         "def_answer_pair_log_count": mean(dfam),
         "def_answer_pair_fresh": share([x == 0 for x in dfam])}
    for k in TYPES:
        f["type_" + k.replace(" ", "_")] = tshare[k] / n_t if n_t else None
    f["type_letter_selection"] = (sum(1 for t in typed if set(t) & LETTER_SELECT) / n_t) if n_t else None
    return f


def port_of(k):
    if k.startswith(("blog_", "def_", "type_")):
        return "blog"
    if k in ("unch_share", "double_unch_share", "first_letter_unch", "under_half_checked",
             "n_entries", "white_cells"):
        return "grid"
    if k.startswith(("clue_", "words_per", "short_clue", "question", "exclam", "midclue", "linked")):
        return "clue"
    if k == "weekday_mean":
        return "times"
    return "answers"


def rank_arr(x):
    x = np.asarray(x, float)
    o = np.argsort(x, kind="stable")
    r = np.empty(len(x))
    r[o] = np.arange(len(x))
    _, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=r)
    return (sums / cnt)[inv]


def rho(a, b, floor=20):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < floor or len({x for x, _ in pairs}) < 3:
        return None, len(pairs), None
    x, y = map(np.array, zip(*pairs))
    r = float(np.corrcoef(rank_arr(x), rank_arr(y))[0, 1])
    return r, len(pairs), math.erfc(abs(r) * math.sqrt(len(pairs) - 1) / math.sqrt(2))


def build():
    sn = D.load_snitch()
    ctx = D.context()
    rank = ctx.rank
    lufz, fam = load_lufz(), load_family()
    abbr = {letters(k) for k in json.loads(ABBR.read_text(encoding="utf-8"))["abbreviations"]}
    blog = load_blog()
    cor = corpus()
    count = collections.Counter(a for _, ents in cor.values() for a in set(ents.values()) if a)
    lf = collections.Counter(ch for a in count for ch in a)
    tot = sum(lf.values())
    freq = {ch: math.log10(n / tot) for ch, n in lf.items()}
    pair_count = collections.Counter()
    for pid, v in blog.items():
        ents = cor.get(pid, (None, {}))[1]
        for eid, b in (v.get("entries") or {}).items():
            d = (b.get("definition") or [None])[0]
            if d and ents.get(eid):
                pair_count[(ents[eid], norm(d))] += 1
    cmt = json.loads(COMMENTS.read_text(encoding="utf-8"))
    rows = collections.defaultdict(list)
    for pid, v in sn.items():
        series = pid.rpartition("-")[0]
        path = PUZ / f"{pid}.json"
        if series not in D.SNITCH_SERIES or not path.exists():
            continue
        puz = D.read_puzzle_file(path)
        if not all(e.get("solution") for e in puz["entries"]):
            continue
        f = {**grid_feats(puz), **answer_feats(puz, rank, lufz, fam, count, freq),
             **clue_feats(puz), **blog_feats(puz, blog.get(pid), abbr, lufz, pair_count)}
        s = D.score(puz, ctx) if D.puzzle_is_annotated(puz) else None
        c = cmt.get(pid) or {}
        rows[series].append({
            "pid": pid, "date": v["date"], "nitch": v["nitch"], "f": f,
            "wd": date.fromisoformat(v["date"]).weekday(),
            "index": s["index"] if s else None,
            "minutes": c.get("median_minutes") if c.get("stated_times", 0) >= 3 else None,
            "dnf": c["dnf"] / c["comments"] if c.get("comments") else None})
    for rs in rows.values():
        rs.sort(key=lambda r: r["date"])
        set_resid(rs, rs)
    return rows


def set_resid(rs, train):
    by = collections.defaultdict(list)
    for r in train:
        by[r["wd"]].append(r["nitch"])
    allm = mean([r["nitch"] for r in train])
    for r in rs:
        r["resid"] = r["nitch"] - (mean(by[r["wd"]]) if by[r["wd"]] else allm)


def thirds(rs):
    n = len(rs)
    return [rs[: n // 3], rs[n // 3: 2 * n // 3], rs[2 * n // 3:]]


def col(rs, k):
    return [r["f"].get(k) for r in rs]


def table(series, rs):
    th = thirds(rs)
    one_day = len({r["wd"] for r in rs}) == 1
    tgt = "nitch" if one_day else "resid"
    print(f"\n{series}: n={len(rs)}; thirds " + " | ".join(
        f"{t[0]['date']}..{t[-1]['date']} n={len(t)}" for t in th))
    print(f"  rho vs {'raw NITCH' if one_day else 'NITCH minus weekday mean'} by third, then all; "
          "then all vs raw NITCH, comment minutes, DNF share. * = sign holds in all three thirds")
    print(f"  {'feature':30s} {'port':7s} {'old':>6s} {'mid':>6s} {'new':>6s} {'all':>6s} {'p':>7s} {'n':>5s}"
          f" | {'raw':>6s} {'min':>6s} {'dnf':>6s}")
    keys = sorted({k for r in rs for k in r["f"]})
    out = []
    for k in keys:
        cells = [rho(col(t, k), [r[tgt] for r in t])[0] for t in th]
        r, n, p = rho(col(rs, k), [r[tgt] for r in rs])
        if r is None:
            continue
        extra = [rho(col(rs, k), [x[t] for x in rs])[0] for t in ("nitch", "minutes", "dnf")]
        stable = all(c is not None and c * r > 0 for c in cells)
        out.append((abs(r) * stable, k, cells, r, p, n, extra, stable))
    out.sort(key=lambda o: (-o[7], -abs(o[3])))
    fmt = lambda x: "  ----" if x is None else f"{x:+6.2f}"
    for _, k, cells, r, p, n, extra, stable in out:
        print(f"  {k:30s} {port_of(k):7s} " + " ".join(fmt(c) for c in cells)
              + f" {r:+6.2f}{'*' if stable else ' '}{p:7.3f} {n:5d} | " + " ".join(fmt(x) for x in extra))
    return out


def combo(train, test, keys_pool, tgt):
    """Top-K by |rho| on train with the sign holding in both train thirds; equal-weight z-sum."""
    halves = [train[: len(train) // 2], train[len(train) // 2:]]
    cand = []
    for k in keys_pool:
        r, n, _ = rho(col(train, k), [x[tgt] for x in train])
        if r is None or n < 0.8 * len(train):
            continue
        hs = [rho(col(h, k), [x[tgt] for x in h])[0] for h in halves]
        if all(h is not None and h * r > 0 for h in hs):
            cand.append((abs(r), k, math.copysign(1, r)))
    cand.sort(reverse=True)
    picked = []
    for _, k, sgn in cand:
        # Skip a near-copy of one already picked.
        if any(abs(rho(col(train, k), col(train, j))[0] or 0) > 0.8 for j, _ in picked):
            continue
        picked.append((k, sgn))
        if len(picked) == TOP_K:
            break
    stats = {}
    for k, _ in picked:
        xs = np.array([x for x in col(train, k) if x is not None], float)
        stats[k] = (xs.mean(), xs.std() or 1.0)

    def pred(r):
        z = [s * ((r["f"][k] - stats[k][0]) / stats[k][1]) for k, s in picked if r["f"].get(k) is not None]
        return sum(z) / len(z) if z else None
    return picked, [pred(r) for r in test]


def heldout(rs, keys_pool):
    th = thirds(rs)
    print(f"\n  held out, rotating thirds: top {TOP_K} portable features picked and z-scored on the other two")
    print(f"  {'held-out third':24s} {'combo all':>10s} {'n':>5s} | {'combo annot':>11s} {'index annot':>11s}"
          f" {'n':>4s} | picked")
    agg = collections.defaultdict(list)
    for i, test in enumerate(th):
        train = [r for j, t in enumerate(th) if j != i for r in t]
        set_resid(train, train)
        set_resid(test, train)
        picked, p = combo(train, test, keys_pool, "resid")
        y = [r["resid"] for r in test]
        a = rho(p, y)
        ann = [(pp, r["index"], r["resid"]) for pp, r in zip(p, test) if r["index"] is not None]
        ca = rho([x[0] for x in ann], [x[2] for x in ann], 10)
        ia = rho([x[1] for x in ann], [x[2] for x in ann], 10)
        both = rho([x[0] + x[1] / (np.std([q[1] for q in ann]) or 1) for x in ann], [x[2] for x in ann], 10) \
            if ann else (None, 0, None)
        for name, v in (("combo", a), ("combo_ann", ca), ("index_ann", ia), ("both_ann", both)):
            if v[0] is not None:
                agg[name].append((v[0], v[1]))
        f = lambda v: "  ----" if v[0] is None else f"{v[0]:+.2f}"
        print(f"  {test[0]['date']}..{test[-1]['date']}   {f(a):>10s} {a[1]:5d} | {f(ca):>11s} {f(ia):>11s}"
              f" {ca[1]:4d} | " + ", ".join(("+" if s > 0 else "-") + k for k, s in picked)
              + f"   [combo+index annot {f(both)}]")
    wm = lambda xs: sum(r * n for r, n in xs) / sum(n for _, n in xs) if xs else float("nan")
    print("  n-weighted mean over thirds: " + ", ".join(f"{k} {wm(v):+.3f}" for k, v in agg.items()))

    # The annotated puzzles sit almost wholly in the newest third, so the
    # comparison with the index also rotates over THEIR date thirds: train on
    # every puzzle outside the held-out third's dates, test on its annotated ones.
    ann = [r for r in rs if r["index"] is not None]
    print(f"\n  annotated puzzles only (n={len(ann)}), rotating their own date thirds;"
          " the combo is trained on every rated puzzle outside the held-out dates")
    print(f"  {'held-out third':24s} {'combo':>6s} {'index':>6s} {'both':>6s} {'n':>4s} | picked")
    agg = collections.defaultdict(list)
    for test in thirds(ann):
        lo, hi = test[0]["date"], test[-1]["date"]
        train = [r for r in rs if not lo <= r["date"] <= hi]
        set_resid(train, train)
        set_resid(test, train)
        picked, p = combo(train, test, keys_pool, "resid")
        y = [r["resid"] for r in test]
        ix = [r["index"] for r in test]
        sd = np.std(ix) or 1.0
        res = {"combo": rho(p, y, 10), "index": rho(ix, y, 10),
               "both": rho([a + b / sd for a, b in zip(p, ix)], y, 10)}
        for k, v in res.items():
            agg[k].append((v[0], v[1]))
        print(f"  {lo}..{hi}   " + " ".join(f"{res[k][0]:+6.2f}" for k in ("combo", "index", "both"))
              + f" {len(test):4d} | " + ", ".join(("+" if s > 0 else "-") + k for k, s in picked))
    print("  n-weighted mean over thirds: " + ", ".join(f"{k} {wm(v):+.3f}" for k, v in agg.items()))
    set_resid(rs, rs)


def main():
    rows = build()
    for series in D.SNITCH_SERIES:
        rs = rows.get(series, [])
        if len(rs) < 30:
            continue
        out = table(series, rs)
        if len({r["wd"] for r in rs}) > 1:
            pool = [o[1] for o in out if port_of(o[1]) != "times"]
            heldout(rs, pool)
    # A series with nothing of its own to train on: the Times daily's combination,
    # trained on every Times daily, scored on the Sunday Times' raw NITCH.
    times, sun = rows.get("times", []), rows.get("sundaytimes", [])
    if times and len(sun) >= 30:
        picked, p = combo(times, sun, [k for k in times[0]["f"] if port_of(k) != "times"], "resid")
        cells = [rho(p[i:j], [r["nitch"] for r in sun[i:j]], 10)[0]
                 for i, j in ((0, len(sun) // 3), (len(sun) // 3, 2 * len(sun) // 3), (2 * len(sun) // 3, len(sun)))]
        r, n, pv = rho(p, [x["nitch"] for x in sun])
        ix = [(a, x["index"], x["nitch"]) for a, x in zip(p, sun) if x["index"] is not None]
        print("\nsundaytimes scored by the Times-trained combo: rho vs raw NITCH by third "
              + " ".join(f"{c:+.2f}" for c in cells) + f", all {r:+.2f} (p={pv:.3f}, n={n}); "
              f"on its {len(ix)} annotated: combo {rho([a for a, _, _ in ix], [c for _, _, c in ix], 10)[0]:+.2f}, "
              f"index {rho([b for _, b, _ in ix], [c for _, _, c in ix], 10)[0]:+.2f}; picked "
              + ", ".join(("+" if sg > 0 else "-") + k for k, sg in picked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
