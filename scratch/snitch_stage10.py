"""Stage 10: clue- and answer-structure candidates, screened on both sets.

    nice -n 19 python3 scratch/snitch_stage10.py dump   # rows to ~/.cache/cryptic-stage10-rows.json
    nice -n 19 python3 scratch/snitch_stage10.py test   # every candidate, both sets, held out, + margin

Same sets, thirds and target as scratch/snitch_stage4.py (whose heldout/add it
reuses); only the candidates differ. Signs fixed in CANDIDATES before measuring:
  clue_count        clues in the puzzle: more clues, more to solve
  linked_clues      share of entries in a cross-reference ("See 5", "12 across")
  surface_capitals  share of clues with a capitalised word mid-sentence, the
                    proper-noun misdirection ("Bill", "Liberal")
  proper_answers    share of answers WordNet knows only capitalised
  pattern_ambiguity mean log10 of the top-50,000 lexicon words fitting a
                    single-word answer's checked letters: how little the
                    crossers pin it down
proper_answers needs nltk's WordNet (see snitch_stage4.py).
"""
import json
import math
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "scratch"))
import difficulty as D
import snitch_stage4 as S4
from fetch_puzzle import puzzle_files, puzzle_is_annotated, read_puzzle_file

CACHE = Path(os.environ.get("STAGE10_ROWS") or Path.home() / ".cache" / "cryptic-stage10-rows.json")
CANDIDATES = {"clue_count": +1, "linked_clues": +1, "surface_capitals": +1,
              "proper_answers": +1, "pattern_ambiguity": +1}
TOP_WORDS = 50000
XREF = re.compile(r"(?i)\b\d{1,2}\s*-?\s*(across|down|ac|dn)\b")
MIDCAP = re.compile(r"(?<![.!?:;\"'(‘“] )(?<=\S )([A-Z][a-z]+)")


class Patterns:
    """Top-TOP_WORDS lexicon words indexed by (length, position, letter)."""

    def __init__(self, rank):
        self.by_len, self.idx = {}, {}
        for w, r in rank.items():
            if r > TOP_WORDS or not w.isalpha():
                continue
            self.by_len.setdefault(len(w), set()).add(w)
            for i, c in enumerate(w):
                self.idx.setdefault((len(w), i, c), set()).add(w)

    def count(self, word, checked):
        sets = [self.idx.get((len(word), i, word[i]), set()) for i in checked]
        if not sets:
            return len(self.by_len.get(len(word), ()))
        sets.sort(key=len)
        out = set(sets[0])
        for s in sets[1:]:
            out &= s
        return len(out)


_PROPER = {}


def proper(phrase):
    if phrase not in _PROPER:
        names = [l.name() for s in S4.wn().synsets(phrase) for l in s.lemmas()
                 if l.name().lower() == phrase]
        _PROPER[phrase] = bool(names) and all(n[0].isupper() for n in names)
    return _PROPER[phrase]


def cand(puz, pats):
    ents = [e for e in puz["entries"] if e.get("solution")]
    if not ents:
        return None
    used = {}
    for e in ents:
        x, y = e["position"]["x"], e["position"]["y"]
        dx, dy = (1, 0) if e["direction"] == "across" else (0, 1)
        for i in range(e["length"]):
            used[(x + dx * i, y + dy * i)] = used.get((x + dx * i, y + dy * i), 0) + 1
    real, linked, caps, amb, prop = 0, 0, 0, [], 0
    for e in ents:
        clue = D.ENUMERATION.sub("", e.get("clue") or "").strip()
        if re.match(r"(?i)see\b", clue) or XREF.search(clue):
            linked += 1
        sol, words = D.answer_words(e)
        prop += proper("_".join(w.lower() for w in words))
        if len(words) == 1 and len(sol) == e["length"]:
            x, y = e["position"]["x"], e["position"]["y"]
            dx, dy = (1, 0) if e["direction"] == "across" else (0, 1)
            chk = [i for i in range(e["length"]) if used[(x + dx * i, y + dy * i)] >= 2]
            amb.append(math.log10(1 + pats.count(sol, chk)))
        if clue and not re.match(r"(?i)see\b", clue):
            real += 1
            caps += bool(MIDCAP.search(clue))
    return {"clue_count": real, "linked_clues": linked / len(ents),
            "surface_capitals": caps / real if real else None,
            "proper_answers": prop / len(ents),
            "pattern_ambiguity": sum(amb) / len(amb) if len(amb) >= 10 else None}


def dump():
    sn, ctx = D.load_snitch(), D.context()
    pats = Patterns(ctx.rank)
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
        pz = {k: (rw[k] - ctx.base[k]["mean"]) / ctx.base[k]["sd"] for k in S4.PORTABLE if rw.get(k) is not None}
        tot = sum(D.WEIGHTS[k] for k in pz)
        rows.append({"pid": pid, "series": series, "date": D.puzzle_day(puz),
                     "nitch": sn[pid]["nitch"] if rated else None,
                     "annotated": puzzle_is_annotated(puz),
                     "index": s["index"] if s else None, "z": s["z"] if s else None,
                     "portable": sum(D.WEIGHTS[k] * z for k, z in pz.items()) / tot if tot else None,
                     "pz": pz, "cand": cand(puz, pats)})
    CACHE.write_text(json.dumps(rows))
    print(len(rows), "rows")


def margin(rows, key):
    rows = [r for r in rows if r.get(key) is not None and r["index"] is not None]
    g = [r[key] for r in rows if r["series"] in D.GENTLE_SERIES]
    h = [r[key] for r in rows if r["series"] not in D.GENTLE_SERIES]
    return sum(h) / len(h) - sum(g) / len(g)


def test(keys):
    rows = json.loads(CACHE.read_text())
    tr = [r for r in rows if r["series"] == "times" and r["nitch"] is not None]
    print(f"margin now {margin(rows, 'index'):+.3f}")
    for name, (bk, wf, sel) in S4.SETS.items():
        print(f"\n== {name} set: base {bk}")
        print(f"  {'base':22s} times  {S4.fmt(S4.heldout(rows, bk, sel))}")
        if name == "annotated":
            print(f"  {'':22s} sunday {S4.fmt(S4.heldout(rows, bk, sel, 'sundaytimes'))}")
        for k in keys:
            sign = CANDIDATES[k]
            S4.add(rows, bk, k, sign, weight_of=wf)
            sub = [r for r in tr if sel(r) and r["cand"] and r["cand"].get(k) is not None]
            f = S4.weekday_resid_target([(r["date"], r["nitch"]) for r in tr], "9", "0")
            raw = D._spearman([r["cand"][k] for r in sub], [f(r) for r in sub])
            print(f"  {('+' if sign > 0 else '-') + k:22s} times  {S4.fmt(S4.heldout(rows, 'new', sel))}  raw {raw:+.3f}")
            if name == "annotated":
                print(f"  {'':22s} sunday {S4.fmt(S4.heldout(rows, 'new', sel, 'sundaytimes'))}"
                      f"  margin {margin(rows, 'new'):+.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "dump":
        dump()
    elif cmd == "test":
        test(sys.argv[2:] or list(CANDIDATES))
