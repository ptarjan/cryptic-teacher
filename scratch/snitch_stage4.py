"""Stage 4: definition indirectness, screened on a fresh set as well as the old one.

    nice -n 19 python3 scratch/snitch_stage4.py dump   # rows to ~/.cache/cryptic-stage4-rows.json
    nice -n 19 python3 scratch/snitch_stage4.py test   # every candidate, both sets, held out
    nice -n 19 python3 scratch/snitch_stage4.py order  # series-order margin, per component
    nice -n 19 python3 scratch/snitch_stage4.py compare A.json B.json  # base index of two dumps

Two evaluation sets:
  annotated  the annotated Times dailies (and Sunday Times), scored by the full
             index, as scratch/snitch_stage3.py did.
  fresh      the rated Times dailies with no annotation, which no earlier screen
             scored, by the portable index: the components that need no
             annotation (PORTABLE).
Each set splits into its own date thirds, each third against the NITCH minus
the weekday mean of every rated Times daily outside it. A candidate's sign is
fixed in CANDIDATES before it is measured, not read off the residual.

Definitions and types are the blog's (blog_facts), else our annotation's, the
same order pairing_novelty reads them in. The candidates' relatedness uses
WordNet through nltk (python3 -m pip install --user nltk;
nltk.download("wordnet")); wn_unrelated_content is the shipped
definition_unrelated, which reads the committed subset instead.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D
import difficulty_check as C
from fetch_puzzle import (
    puzzle_files,
    puzzle_is_annotated,
    read_puzzle_file,
)

CACHE = Path(os.environ.get("STAGE4_ROWS") or Path.home() / ".cache" / "cryptic-stage4-rows.json")
PORTABLE = D.PORTABLE
#: name -> expected sign (higher raw value = harder when +1), fixed in advance.
CANDIDATES = {"wn_unrelated": +1, "defonly_share": +1, "example_markers": +1,
              "long_anagram_cells": -1, "def_indirect": +1,
              "wn_unrelated_head": +1, "wn_unrelated_content": +1,
              "plain_anagrams": -1, "phrase_answers": +1, "clue_words": -1}
MARKER = re.compile(r"(?i)\b(perhaps|say|for example|for instance|e\.?g\.?|maybe|possibly|for one)\b")
DEFONLY = {"double definition", "cryptic definition"}
STOP = {"a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "is", "be", "with",
        "by", "at", "as", "that", "this", "it", "one", "s", "from", "who", "what", "may",
        "some", "being", "one's", "its", "his", "her", "their", "not", "no"}


def blog_facts():
    out = {}
    for f in sorted(D.BLOG_FACTS.glob("*.json")):
        for pid, v in json.loads(f.read_text(encoding="utf-8")).items():
            out[pid] = v.get("entries") or {}
    return out


_WN = None


def wn():
    global _WN
    if _WN is None:
        from nltk.corpus import wordnet
        _WN = wordnet
    return _WN


_REL = {}
#: Hypernyms this close to the root ("object", "person", "act") relate everything.
GENERIC_DEPTH = 3


def synsets(phrase):
    """WordNet synsets of a phrase or word, its base forms included."""
    w = wn()
    out = set(w.synsets(phrase))
    if "_" not in phrase:
        for pos in ("n", "v", "a", "r"):
            m = w.morphy(phrase, pos)
            if m:
                out.update(w.synsets(m, pos))
    return out


def near(answer):
    """(synsets, lemma names, gloss words) around an answer: its own synsets,
    their hypernyms five deep but short of the generic top of the tree,
    hyponyms and look-alikes one deep."""
    if answer in _REL:
        return _REL[answer]
    ss = set()
    gloss = set()
    for s in synsets(answer):
        ss.add(s)
        ss.update(h for h in s.closure(lambda x: x.hypernyms() + x.instance_hypernyms(), depth=5)
                  if h.min_depth() > GENERIC_DEPTH)
        ss.update(s.hyponyms() + s.similar_tos() + s.also_sees() + s.verb_groups()
                  + s.member_holonyms() + s.part_holonyms())
        for l in s.lemmas():
            ss.update(d.synset() for d in l.derivationally_related_forms())
            ss.update(p.synset() for p in l.pertainyms())
        gloss.update(re.findall(r"[a-z]+", s.definition().lower()))
    names = {l.name().lower() for s in ss for l in s.lemmas()}
    _REL[answer] = (ss, names, gloss - STOP)
    return _REL[answer]


def wn_related(answer_phrase, definition, judge="ends"):
    """Whether WordNet ties the definition to the answer: a synset near the
    answer's (near()), a gloss word, or the answer in the definition's gloss.
    None when WordNet lacks the answer. `judge` picks what of the definition
    is tried: "ends" the whole of it and its first and last content words,
    "head" its head word alone (D.definition_head), "content" each of its
    content words."""
    ws = re.findall(r"[a-z]+", definition.lower())
    if not ws:
        return None
    ss, names, gloss = near(answer_phrase)
    if not ss:
        return None
    content = [x for x in ws if x not in STOP] or ws
    ans_words = set(answer_phrase.split("_"))
    tries = {"ends": {"_".join(ws), content[0], content[-1]},
             "head": {D.definition_head(" ".join(ws))},
             "content": set(content)}[judge]
    for c in tries:
        ds = synsets(c)
        if ds & ss or c in names or c in gloss:
            return True
        # a sibling: the definition's own hypernym is one of the answer's
        if {h for d in ds for h in d.hypernyms() if h.min_depth() > GENERIC_DEPTH} & ss:
            return True
        for d in ds:
            if ans_words & set(re.findall(r"[a-z]+", d.definition().lower())):
                return True
    return False


def clue_rows(puz, facts):
    """(entry, clue text, definition key, type parts) for each real clue."""
    out = []
    for e in puz["entries"]:
        if not e.get("solution"):
            continue
        clue = D.ENUMERATION.sub("", e.get("clue") or "").strip()
        if not clue or re.match(r"(?i)see\b", clue):
            continue
        f = facts.get(e.get("id")) or {}
        ann = e.get("annotation") or {}
        d = D.definition_key(f.get("definition")) or D.definition_key(ann.get("definition"))
        t = ann.get("type") or f.get("type") or ""
        parts = [p.strip().lower() for p in t.split("+") if p.strip()]
        out.append((e, clue, d, parts))
    return out


def plain_anagram(e, clue):
    """Whether a run of whole clue words is the answer's letters rearranged."""
    a = sorted(D.letters(e["solution"]))
    ws = [w for w in (D.letters(x) for x in clue.split()) if w]
    for i in range(len(ws)):
        s = ""
        for w in ws[i:]:
            s += w
            if len(s) >= len(a):
                break
        if sorted(s) == a and s != D.letters(e["solution"]):
            return True
    return False


def cand(puz, facts):
    rows = clue_rows(puz, facts)
    if not rows:
        return None
    typed = [r for r in rows if r[3]]
    rel = []
    ind = []
    rel_head, rel_content = [], []
    for e, clue, d, parts in rows:
        dd = bool(parts) and set(parts) <= DEFONLY
        _, words = D.answer_words(e)
        r = wn_related("_".join(w.lower() for w in words), d) if d else None
        if r is not None:
            rel.append(not r)
            aw = "_".join(w.lower() for w in words)
            rel_head.append(not wn_related(aw, d, "head"))
            rel_content.append(not wn_related(aw, d, "content"))
        if dd or r is not None:
            ind.append(dd or (r is False))
    cells = sum(e["length"] for e, *_ in rows) or 1
    return {
        "wn_unrelated": sum(rel) / len(rel) if len(rel) >= 5 else None,
        "defonly_share": sum(1 for r in typed if set(r[3]) <= DEFONLY) / len(typed) if len(typed) >= 10 else None,
        "example_markers": sum(1 for r in rows if MARKER.search(r[1])) / len(rows),
        "long_anagram_cells": (sum(e["length"] for e, _, _, p in rows if e["length"] >= 10 and "anagram" in p)
                               / cells) if len(typed) >= 10 else None,
        "wn_unrelated_head": sum(rel_head) / len(rel_head) if len(rel_head) >= 5 else None,
        "wn_unrelated_content": sum(rel_content) / len(rel_content) if len(rel_content) >= 5 else None,
        "def_indirect": sum(ind) / len(ind) if len(ind) >= 10 else None,
        "plain_anagrams": sum(plain_anagram(e, c) for e, c, *_ in rows) / len(rows),
        "phrase_answers": sum(len(D.answer_words(e)[1]) > 1 for e, *_ in rows) / len(rows),
        "clue_words": sum(len(c.split()) for _, c, *_ in rows) / len(rows),
        "_wn_cover": len(rel) / len(rows), "_typed": len(typed) / len(rows),
    }


def dump():
    sn, ctx = D.load_snitch(), D.context()
    bf = blog_facts()
    rows = []
    for path in puzzle_files():
        puz = read_puzzle_file(path)
        pid = puz["id"]
        series = puz.get("series") or pid.rpartition("-")[0]
        s = D.score(puz, ctx)
        rated = pid in sn and pid.rpartition("-")[0] in D.SNITCH_SERIES
        if not rated and not s:
            continue
        rw = D.raw(puz, ctx)
        pz = {k: (rw[k] - ctx.base[k]["mean"]) / ctx.base[k]["sd"] for k in PORTABLE if rw.get(k) is not None}
        tot = sum(D.WEIGHTS[k] for k in pz)
        rows.append({"pid": pid, "series": series, "date": D.puzzle_day(puz),
                     "nitch": sn[pid]["nitch"] if rated else None,
                     "annotated": puzzle_is_annotated(puz),
                     "index": s["index"] if s else None, "z": s["z"] if s else None,
                     "portable": sum(D.WEIGHTS[k] * z for k, z in pz.items()) / tot if tot else None,
                     "pz": pz, "cand": cand(puz, bf.get(pid, {}))})
    CACHE.write_text(json.dumps(rows))
    print(len(rows), "rows")


# The shipped index's own check (tools/difficulty_check.py) defines the test.
weekday_resid_target, heldout = C.weekday_resid_target, C.heldout


def add(rows, base_key, k, sign, w=0.25, weight_of=None):
    """rows[r]["new"] = the base index with candidate k added at weight w."""
    xs = [r["cand"][k] for r in rows if r["cand"] and r["cand"].get(k) is not None]
    m = sum(xs) / len(xs)
    sd = (sum((x - m) ** 2 for x in xs) / len(xs)) ** .5 or 1
    for r in rows:
        b = r.get(base_key)
        if b is None:
            r["new"] = None
            continue
        tot = weight_of(r)
        v = (r["cand"] or {}).get(k)
        r["new"] = b if v is None else (b * tot + w * sign * (v - m) / sd) / (tot + w)


def full_w(r):
    return sum(D.WEIGHTS[k] for k in r["z"])


def port_w(r):
    return sum(D.WEIGHTS[k] for k in r["pz"])


def fmt(h):
    t, n = h
    return " ".join(f"{x:+.3f}" for x in t) + f"  mean {sum(t)/3:+.3f} (n={n})"


SETS = {
    "annotated": ("index", full_w, lambda r: r["index"] is not None),
    "fresh": ("portable", port_w, lambda r: not r["annotated"]),
}


def test(keys):
    rows = json.loads(CACHE.read_text())
    tr = [r for r in rows if r["series"] == "times" and r["nitch"] is not None]
    cov = [r["cand"] for r in tr if r["cand"]]
    print("coverage (times rated): wn", round(sum(c["_wn_cover"] for c in cov) / len(cov), 3),
          "typed", round(sum(c["_typed"] for c in cov) / len(cov), 3))
    for name, (bk, wf, sel) in SETS.items():
        print(f"\n== {name} set: base {bk}")
        print(f"  {'base':22s} times  {fmt(heldout(rows, bk, sel))}")
        if name == "annotated":
            print(f"  {'':22s} sunday {fmt(heldout(rows, bk, sel, 'sundaytimes'))}")
        for k in keys:
            sign = CANDIDATES[k]
            add(rows, bk, k, sign, weight_of=wf)
            sub = [r for r in tr if sel(r) and r["cand"] and r["cand"].get(k) is not None]
            f = weekday_resid_target([(r["date"], r["nitch"]) for r in tr], "9", "0")
            raw = D._spearman([r["cand"][k] for r in sub], [f(r) for r in sub])
            print(f"  {('+' if sign > 0 else '-') + k:22s} times  {fmt(heldout(rows, 'new', sel))}  raw {raw:+.3f}")
            if name == "annotated":
                print(f"  {'':22s} sunday {fmt(heldout(rows, 'new', sel, 'sundaytimes'))}")


def order():
    """Gentle-series margin of the index, per component and without each."""
    rows = [r for r in json.loads(CACHE.read_text()) if r["index"] is not None]
    gentle = lambda r: r["series"] in D.GENTLE_SERIES

    def margin(vals):
        g = [v for r, v in vals if gentle(r)]
        h = [v for r, v in vals if not gentle(r)]
        return sum(h) / len(h) - sum(g) / len(g), len(g), len(h)

    def idx(r, drop=(), extra=None):
        z = {k: v for k, v in r["z"].items() if k not in drop}
        if extra and extra(r) is not None:
            z["_new"] = extra(r)
        w = {**D.WEIGHTS, "_new": 0.25}
        return sum(w[k] * v for k, v in z.items()) / sum(w[k] for k in z)

    m0, ng, nh = margin([(r, r["index"]) for r in rows])
    print(f"margin now {m0:+.3f} (gentle {ng}, daily {nh})")
    comps = sorted({k for r in rows for k in r["z"]})
    print("\ncomponent        daily-minus-gentle z   margin without it")
    for k in comps:
        vals = [(r, r["z"][k]) for r in rows if k in r["z"]]
        m = margin(vals)[0]
        print(f"  {k:16s} {m:+.3f}               {margin([(r, idx(r, drop=(k,))) for r in rows])[0]:+.3f}")
    for drop in ((), ("question_marks",), PORTABLE):
        print("without", drop or "-", f"{margin([(r, idx(r, drop=drop)) for r in rows])[0]:+.3f}")
    for k, sign in CANDIDATES.items():
        xs = [r["cand"][k] for r in rows if r["cand"] and r["cand"].get(k) is not None]
        m = sum(xs) / len(xs)
        sd = (sum((x - m) ** 2 for x in xs) / len(xs)) ** .5
        ex = lambda r, k=k, sign=sign, m=m, sd=sd: (
            None if not r["cand"] or r["cand"].get(k) is None else sign * (r["cand"][k] - m) / sd)
        vals = [(r, ex(r)) for r in rows if ex(r) is not None]
        print(f"+{k:20s} own gap {margin(vals)[0]:+.3f}  index margin {margin([(r, idx(r, extra=ex)) for r in rows])[0]:+.3f}")
    by = {}
    for r in rows:
        by.setdefault(r["series"], []).append(r)
    print("\nseries   n   " + " ".join(f"{k[:10]:>10s}" for k in comps))
    for s, rs in sorted(by.items()):
        print(f"  {s:12s} {len(rs):4d} " + " ".join(
            f"{sum(r['z'][k] for r in rs if k in r['z']) / max(1, sum(k in r['z'] for r in rs)):+10.3f}" for k in comps))


def margin_of(rows):
    return C.margin_of(rows)[0]


def compare(paths):
    """Each rows cache's base index side by side: a change to an existing
    component, dumped once before it and once after (STAGE4_ROWS)."""
    print(f"{'rows':32s} {'annotated times':28s} {'fresh times':28s} sunday  margin")
    for p in paths:
        rows = json.loads(Path(p).read_text())
        cells = []
        for bk, _, sel in SETS.values():
            t, _ = heldout(rows, bk, sel)
            cells.append(" ".join(f"{x:.3f}" for x in t) + f" = {sum(t) / 3:.3f}")
        sun, _ = heldout(rows, "index", SETS["annotated"][2], "sundaytimes")
        print(f"{Path(p).name:32s} {cells[0]:28s} {cells[1]:28s} {sum(sun) / 3:.3f}   {margin_of(rows):.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "dump":
        dump()
    elif cmd == "test":
        test(sys.argv[2:] or list(CANDIDATES))
    elif cmd == "order":
        order()
    elif cmd == "compare":
        compare(sys.argv[2:])
