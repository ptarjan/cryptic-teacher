#!/usr/bin/env python3
"""Rank clues whose wordplay tree is probably wrong, from shape signals (read-only on puzzles/).

    nice -n 19 python3 tools/shape_suspects.py --collect /tmp/shape_all.jsonl   # one corpus pass
    python3 tools/shape_suspects.py --sample /tmp/shape_all.jsonl N [seed] [ncommon]
    nice -n 19 python3 tools/shape_suspects.py --rank /tmp/shape_all.jsonl      # write tools/data/shape_suspects.json

Imports the skeleton code from tools/clue_shapes.py.
"""
import collections
import json
import random
import re
import sys
from pathlib import Path

import clue_shapes as cs
import puzzle_paths
import wordplay

OUT = Path(__file__).resolve().parent / "data" / "shape_suspects.json"


def collect(dest):
    with open(dest, "w") as f:
        for path in puzzle_paths.puzzle_files():
            try:
                pz = json.loads(Path(path).read_text())
            except (OSError, ValueError):
                continue
            series = Path(path).parent.parent.name
            pid = pz.get("id") or Path(path).stem
            for e in pz.get("entries") or []:
                ann = e.get("annotation")
                if not ann or ann.get("wordplay") is None:
                    continue
                wp = ann["wordplay"]
                clue = (e.get("clue") or {}).get("text", "")
                sk = cs.analyse(wp)[0]
                f.write(json.dumps({"id": f"{pid}#{e.get('number')}{(e.get('direction') or '?')[:1]}", "series": series,
                                    "clue": clue, "sol": e.get("solution", ""), "sk": sk, "line": cs.compact(wp),
                                    "wp": wp, "defs": ann.get("definitions") or [], "andLit": bool(ann.get("andLit"))}) + "\n")


def L(s):
    return cs.letters(s)


def nodes(wp):
    out = [wp]
    for p in (wp.get("parts") or []):
        out += nodes(p)
    return out


def leaves(wp):
    return [n for n in nodes(wp) if "op" not in n]


def d_arity_ins(r):
    """A container with other than two parts: the thing held or the holder is missing (13 of 13 sampled wrong)."""
    for n in nodes(r["wp"]):
        if n.get("op") == "container" and len(n.get("parts") or []) != 2:
            return f"ins has {len(n.get('parts') or [])} parts, takes 2"


def d_arity_other(r):
    """del/sub/homophone with more parts than the evaluator takes (del 3+, sub != 3, sound 3+)."""
    for n in nodes(r["wp"]):
        op, k = n.get("op"), len(n.get("parts") or [])
        if (op == "deletion" and k >= 3) or (op == "substitution" and k != 3) or (op == "homophone" and k >= 3) \
                or (op in ("reversal", "hidden", "cycling") + wordplay.SELECT and k != 1):
            return f"{cs.SHORT.get(op, op)} has {k} parts"


def d_del_single(r):
    """A deletion with one part: the letters it removes are not stated."""
    for n in nodes(r["wp"]):
        if n.get("op") == "deletion" and len(n.get("parts") or []) == 1:
            return "del with one part (what it removes is not stated)"


def d_span_overlap(r):
    """Two leaves, or a leaf and an indicator, covering the same clue letters."""
    if r["wp"].get("op") == "cryptic":
        return None
    sp = []
    for n in nodes(r["wp"]):
        if "op" not in n and n.get("words") and n.get("at") is not None:
            sp.append((n["at"], n["at"] + len(n["words"]), n["words"], "leaf"))
        for i in n.get("indicators") or []:
            if i.get("at") is not None and i.get("text"):
                sp.append((i["at"], i["at"] + len(i["text"]), i["text"], "indicator"))
    for x in range(len(sp)):
        for y in range(x + 1, len(sp)):
            a, b = sp[x], sp[y]
            if a[3] == b[3] == "leaf" and a[:2] == b[:2]:
                continue  # one clue word doing two jobs (validate_annotations.span_overlaps)
            if "leaf" in (a[3], b[3]) and min(a[1], b[1]) - max(a[0], b[0]) >= 3:
                return f"{a[3]} '{a[2]}' overlaps {b[3]} '{b[2]}'"


def d_ind_in_leaf(r):
    for n in nodes(r["wp"]):
        for i in n.get("indicators") or []:
            t = L(i.get("text"))
            if len(t) < 3:
                continue
            for lf in leaves(r["wp"]):
                ws = [L(x) for x in (lf.get("words") or "").split()]
                if len(ws) > 1 and t in ws and lf.get("words") and L(lf["words"]) != t:
                    return f"indicator '{i.get('text')}' also sits inside leaf '{lf['words']}'"


def d_leaf_in_def(r):
    if r["andLit"] or r["wp"].get("op") == "cryptic":
        return None
    for lf in leaves(r["wp"]):
        w = L(lf.get("words"))
        if len(w) < 4 or lf.get("gives") is None or L(lf["gives"]) == w:
            continue
        for d in r["defs"]:
            dt = L(d.get("text"))
            if dt and w in dt:
                return f"leaf '{lf['words']}' is inside the definition '{d.get('text')}'"


def d_unchecked_leaf_word(r):
    """An unchecked leaf (gives taken as filed) with clue words."""
    for lf in leaves(r["wp"]):
        if lf.get("unchecked") and lf.get("words") and "dropped" not in (lf.get("note") or ""):
            return f"unchecked leaf '{lf['words']}'"


def d_unchecked_rare(r, c):
    if r["sk"].count("?") and c[r["sk"]] <= 3 and r["wp"].get("op") != "cryptic":
        return "unchecked op in a skeleton seen at most 3 times"


def d_op_over_charade(r):
    for n in nodes(r["wp"]):
        if n.get("op") in ("deletion", "container", "reversal") and any(
                k.get("op") == "charade" for k in (n.get("parts") or [])[:1]):
            return f"{cs.SHORT[n['op']]} applied to a whole charade"


def d_bare(r):
    for lf in leaves(r["wp"]):
        if "words" not in lf and "dropped" not in (lf.get("note") or "") and "answer" not in (lf.get("note") or ""):
            return f"bare letters {lf.get('gives')} with no clue words"


def d_nested_same(r):
    for n in nodes(r["wp"]):
        for k in n.get("parts") or []:
            if n.get("op") and n.get("op") == k.get("op") and n["op"] not in ("charade", "cryptic"):
                return f"{cs.SHORT.get(n['op'], n['op'])} directly inside {cs.SHORT.get(n['op'], n['op'])}"


def d_singleton(r, c):
    if c[r["sk"]] == 1 and r["sk"].count("(") >= 3 and r["wp"].get("op") != "cryptic":
        return "skeleton seen once, 3+ brackets"


_WORDS = set()
_REF = re.compile(r"^\d+[AD]?(\s+\d+[AD]?)*\s*\??$")


def is_rebus_clue(text, solution):
    """Whether the clue text is a rebus to read, not words to parse: no lowercase letter,
    a solution that is not the clue itself (a straight puzzle), no word of 3+ letters the
    lexicon knows (ordinary capitals: CLUE TO COME), and not a bare clue reference ("9 15")
    or a lone "?". HIJKLMNO, CO2?, P?, 1984? and 50 + 0 = 0? qualify."""
    text = (text or "").strip()
    if not text or not solution or re.search("[a-z]", text) or re.sub(r"\s", "", text) == solution:
        return False
    if _REF.match(text) or not re.search(r"[^\s?]", text):
        return False
    if not _WORDS:
        lex = Path(__file__).resolve().parent / "data" / "lexicon.tsv"
        with lex.open(encoding="utf-8") as f:
            _WORDS.update(w for w in (ln.split("\t")[0].strip().upper() for ln in f)
                          if len(w) >= 3 and w.isalpha())
    return not any(k in _WORDS for k in re.findall("[A-Z]{3,}", text))


def d_rebus(r):
    """A rebus clue (is_rebus_clue) whose tree is not the rebus op: Paul 10-16, "put a rebus
    puzzle or two at the front of the queue once you build support to annotate them"."""
    if r["wp"].get("op") not in ("rebus", "picture") and is_rebus_clue(r["clue"], r["sol"]):
        return f"rebus clue '{r['clue']}' is not annotated with rebus()"


DETECTORS = {"arity_ins": d_arity_ins, "arity_other": d_arity_other, "del_single": d_del_single,
             "span_overlap": d_span_overlap, "ind_in_leaf": d_ind_in_leaf, "unchecked_leaf": d_unchecked_leaf_word,
             "rebus": d_rebus}
CDETECTORS = {}
# Hand-measured precision (share of ~8-16 sampled hits per detector whose tree was wrong or unverifiable
# against the clue text, 2026-10-15). Detectors measured below 50% (leaf-in-definition ~40%, ins-in-ins,
# del/rev over a charade, rare skeleton alone, repeated leaf words, bare letters under del) are left out.
PRECISION = {"arity_ins": 0.95, "arity_other": 0.9, "del_single": 0.9, "span_overlap": 0.9, "ind_in_leaf": 0.85,
             "unchecked_leaf": 0.85, "rebus": 0.9}


def run_detectors(rows):
    c = collections.Counter(r["sk"] for r in rows)
    for r in rows:
        hits = {}
        for k, f in DETECTORS.items():
            try:
                x = f(r)
            except Exception:
                x = None
            if x:
                hits[k] = x
        for k, f in CDETECTORS.items():
            x = f(r, c)
            if x:
                hits[k] = x
        yield r, hits


def load(src):
    return [json.loads(line) for line in open(src)]


def main():
    a = sys.argv
    if a[1] == "--collect":
        collect(a[2])
    elif a[1] == "--hits":
        hits = []
        for r, h in run_detectors(load(a[2])):
            if h:
                hits.append({"id": r["id"], "series": r["series"], "clue": r["clue"], "sol": r["sol"], "skeleton": r["sk"],
                             "line": r["line"], "hits": h})
        json.dump(hits, open(a[3], "w"))
    elif a[1] == "--rank":
        # --rank HITS.json: keep detectors measured >= 50% precise, rank, write tools/data/shape_suspects.json
        import re
        v = cs.load_verdicts()
        pats = [(p, re.compile(p.get("re", "."))) for p in v["patterns"]]
        out = []
        for x in json.load(open(a[2])):
            keep = {k: why for k, why in x["hits"].items() if k in PRECISION}
            if not keep:
                continue
            miss = 1.0
            for k in keep:
                miss *= 1 - PRECISION[k]
            row, group = cs.judge(x["skeleton"], v, pats)
            out.append({"id": x["id"], "clue": x["clue"], "answer": x["sol"], "skeleton": x["skeleton"],
                        "reason": "; ".join(f"{k}: {w}" for k, w in keep.items()), "score": round(1 - miss, 3),
                        "shape_verdict": (row or {}).get("verdict"), "tree": x["line"]})
        out.sort(key=lambda r: (-r["score"], r["id"]))
        OUT.write_text(json.dumps({"precision": PRECISION, "count": len(out), "suspects": out}, indent=0) + "\n")
        print(len(out), "suspects")
    elif a[1] == "--detect":
        rows = load(a[2])
        per = collections.defaultdict(list)
        for r, hits in run_detectors(rows):
            for k, why in hits.items():
                per[k].append((r, why))
        random.seed(5)
        for k, v in sorted(per.items()):
            print("##", k, len(v))
            for r, why in random.sample(v, min(len(v), int(a[3]))):
                print(k, r["id"], "|", r["clue"], "|", r["sol"], "|", r["line"], "|", why)
    elif a[1] == "--sample":
        rows = load(a[2])
        n = int(a[3])
        c = collections.Counter(r["sk"] for r in rows)
        random.seed(int(a[4]) if len(a) > 4 else 1)
        by = collections.defaultdict(list)
        for r in rows:
            if c[r["sk"]] <= 3 and r["sk"] != "V":
                by[r["series"]].append(r)
        pick = []
        keys = sorted(by)
        while len(pick) < n and keys:
            for k in keys:
                if by[k] and len(pick) < n:
                    pick.append(by[k].pop(random.randrange(len(by[k]))))
            keys = [k for k in keys if by[k]]
        common = [r for r in rows if c[r["sk"]] >= 200]
        ctl = random.sample(common, int(a[5]) if len(a) > 5 else 30)
        for tag, rs in (("RARE", pick), ("COMMON", ctl)):
            for r in rs:
                print(tag, r["id"], c[r["sk"]], "|", r["clue"], "|", r["sol"], "|", r["line"], "|", r["sk"])


if __name__ == "__main__":
    main()
