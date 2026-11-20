#!/usr/bin/env python3
"""The synonym dictionary of tools/det_solve.py: clue phrase -> {letters it can give: score}, from many sources.

Sources, best first (the score is what the search adds for using that leaf):
  corpus      leaf table X -> Y from annotated wordplay trees (1.0 .. 1.75 by count)
  abbr        build_abbreviations (0.9)
  corpus_rev  the same leaf table read backwards, Y -> X (0.75 .. 1.0)
  def         definition table, definition phrase -> answer (0.7 .. 0.85)
  def_rev     answer -> definition phrase (0.65 .. 0.8)
  moby        Moby Thesaurus II (public domain), listed both ways 0.5, one way 0.42
  wn_direct   every WordNet synset's members (0.48)
  codef       two definitions of the same answer (0.4, single words only)
  wn_near     members of similar_to / also_see / derivational / hypernym / hyponym neighbours (0.3)
  infl        any of the above on a stem, re-inflected (s, es, ed, ing, er, ly): that score minus 0.2

The Moby file is downloaded by tools/fetch_moby.py into downloads.MOBY/<dir>/mthesaur.txt (data only,
never executed) and compacted on demand into ~/.cache/detsolve/moby.json.gz (not committed).
"""
import collections
import glob
import gzip
import json
import os
import re
from pathlib import Path

import downloads

CACHE = Path.home() / ".cache" / "detsolve"
MOBY_GLOB = str(downloads.MOBY / "*" / "mthesaur.txt")
MOBY_JSON = CACHE / "moby.json.gz"
ORDER = ("corpus", "abbr", "corpus_rev", "def", "def_rev", "moby", "wn_direct", "codef", "variant", "wn_near", "infl")
STRONG = ("corpus", "abbr")    # always offered to SOLVE; the rest only where these have nothing, a few per phrase
_load_moby_memo = []


def letters(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper().replace("É", "E").replace("È", "E"))


def load_moby():
    """(forward {root: [syns]}, inverse {word: [roots]}) from the compact json, building it from the raw file on demand."""
    if _load_moby_memo:
        return _load_moby_memo[0]
    fwd = {}
    if not MOBY_JSON.exists():
        raw = sorted(glob.glob(MOBY_GLOB))
        if not raw:
            _load_moby_memo.append(({}, {}))
            return _load_moby_memo[0]
        rows = {}
        for line in open(raw[0], encoding="latin-1"):
            parts = [x.strip().lower() for x in line.split(",")]
            parts = [x for x in parts if x]
            if len(parts) > 1:
                rows[parts[0]] = parts[1:]
        json.dump(rows, gzip.open(MOBY_JSON, "wt"))
    fwd = json.load(gzip.open(MOBY_JSON, "rt"))
    inv = collections.defaultdict(list)
    for root, syns in fwd.items():
        for s in syns:
            inv[s].append(root)
    _load_moby_memo.append((fwd, inv))
    return _load_moby_memo[0]


def stems(p):
    """(stem, kind) readings of a single word as an inflected form."""
    out = []
    if " " in p or len(p) < 4:
        return out
    if p.endswith("ies"):
        out.append((p[:-3] + "y", "S"))
    if p.endswith("es"):
        out.append((p[:-2], "S"))
    if p.endswith("s") and not p.endswith("ss"):
        out.append((p[:-1], "S"))
    if p.endswith("ied"):
        out.append((p[:-3] + "y", "ED"))
    if p.endswith("ed"):
        out += [(p[:-2], "ED"), (p[:-1], "ED")]
        if len(p) > 5 and p[-3] == p[-4]:
            out.append((p[:-3], "ED"))
    if p.endswith("ing"):
        out += [(p[:-3], "ING"), (p[:-3] + "e", "ING")]
        if len(p) > 6 and p[-4] == p[-5]:
            out.append((p[:-4], "ING"))
    if p.endswith("ier"):
        out.append((p[:-3] + "y", "ER"))
    if p.endswith("er"):
        out += [(p[:-2], "ER"), (p[:-1], "ER")]
        if len(p) > 5 and p[-3] == p[-4]:
            out.append((p[:-3], "ER"))
    if p.endswith("ly"):
        out.append((p[:-2], "LY"))
    return [(s, k) for s, k in out if len(s) >= 3]


def inflect(g, kind):
    """Plausible spellings of letters g (a stem) with the suffix kind."""
    v = "AEIOU"
    res = []
    if kind == "S":
        if g.endswith(("S", "X", "Z", "CH", "SH")):
            res.append(g + "ES")
        elif g.endswith("Y") and len(g) > 2 and g[-2] not in v:
            res.append(g[:-1] + "IES")
        else:
            res.append(g + "S")
    elif kind in ("ED", "ER"):
        suf = kind
        if g.endswith("E"):
            res.append(g + suf[1:])
        elif g.endswith("Y") and len(g) > 2 and g[-2] not in v:
            res.append(g[:-1] + "I" + suf)
        else:
            res.append(g + suf)
            if len(g) >= 3 and g[-1] not in v + "WXY" and g[-2] in v and g[-3] not in v:
                res.append(g + g[-1] + suf)
    elif kind == "ING":
        if g.endswith("E") and not g.endswith("EE"):
            res.append(g[:-1] + "ING")
        else:
            res.append(g + "ING")
            if len(g) >= 3 and g[-1] not in v + "WXY" and g[-2] in v and g[-3] not in v:
                res.append(g + g[-1] + "ING")
    elif kind == "LY":
        res.append(g[:-1] + "ILY" if g.endswith("Y") else g + "LY")
    return res


def get_sd(tab, res):
    """The SynDict of a table set, built once. DETSYN_OFF=moby,infl,... switches sources off (for ablations)."""
    if "_sd" not in tab:
        tab["_sd"] = SynDict(tab, res, off=[x for x in os.environ.get("DETSYN_OFF", "").split(",") if x])
    return tab["_sd"]


class SynDict:
    def __init__(self, tab, res, use_moby=True, off=()):
        self.tab, self.res, self.off = tab, res, set(off)
        self.rev = collections.defaultdict(collections.Counter)      # gives letters -> {words phrase: count}
        for words, gv in tab["syn"].items():
            for g, c in gv.items():
                self.rev[g][words] += c
        self.defrev = collections.defaultdict(collections.Counter)   # answer -> {definition phrase: count}
        for d, av in tab["def"].items():
            for a, c in av.items():
                self.defrev[a][d] += c
        self.moby = load_moby() if use_moby and "moby" not in self.off else ({}, {})
        self.memo, self.bmemo = {}, {}

    # ---- one source at a time
    def base(self, phrase):
        """{source: {gives: score}} for a phrase, no inflection."""
        if phrase in self.bmemo:
            return self.bmemo[phrase]
        L = letters(phrase)
        out = {s: {} for s in ORDER}
        tab, res = self.tab, self.res
        for g, c in tab["syn"].get(phrase, {}).items():
            out["corpus"][g] = 1.0 + min(c, 5) * 0.15
        for g in res.abbr.get(phrase, [])[:10]:
            if g:
                out["abbr"][g] = 0.9
        for words, c in self.rev.get(L, {}).items():
            g = letters(words)
            out["corpus_rev"][g] = max(out["corpus_rev"].get(g, 0), 0.75 + min(c, 5) * 0.05)
        for a, c in tab["def"].get(phrase, {}).items():
            out["def"][a] = 0.7 + min(c, 3) * 0.05
        for d, c in self.defrev.get(L, {}).items():
            g = letters(d)
            if g:
                out["def_rev"][g] = max(out["def_rev"].get(g, 0), 0.65 + min(c, 3) * 0.05)
        if " " not in phrase:
            for a in tab["def"].get(phrase, {}):
                for d in self.defrev.get(a, {}):
                    if " " not in d and d != phrase and letters(d):
                        out["codef"].setdefault(letters(d), 0.4)
        fwd, inv = self.moby
        one = fwd.get(phrase, [])
        back = inv.get(phrase, []) if inv else []
        both = set(one) & set(back)
        for w in set(one) | set(back):
            g = letters(w)
            if g:
                out["moby"][g] = 0.5 if w in both else 0.42
        kt = phrase.split()
        if len(kt) >= 2:
            # a modifier dropped: "desert plant" -> what "plant" gives; "driver 's warning" -> "warning" and "driver"
            for v in {" ".join(kt[1:]), " ".join(kt[:-1]), " ".join(kt[2:]) if kt[1] == "'s" else ""} - {""}:
                for g, c in tab["syn"].get(v, {}).items():
                    out["variant"][g] = max(out["variant"].get(g, 0), 0.3 + min(c, 5) * 0.04)
        key = phrase.replace(" ", "_")
        sids = res.wn_words.get(key, [])
        near = set()
        for s in sids:
            for m in res.members.get(s, []):
                out["wn_direct"][letters(m)] = 0.48
            row = res.wn_syn[s]
            for t in row[1] + row[2] + row[3]:
                near.add(t)
        for t in near:
            for m in res.members.get(t, []):
                out["wn_near"].setdefault(letters(m), 0.3)
        for s in ORDER:
            out[s].pop("", None)
            out[s].pop(L, None)
            if s in self.off:
                out[s] = {}
        self.bmemo[phrase] = out
        return out

    def sources(self, phrase):
        """base sources plus 'infl': the best stem readings re-inflected."""
        if phrase in self.memo:
            return self.memo[phrase]
        out = self.base(phrase)
        infl = {}
        if "infl" not in self.off:
            for stem, kind in stems(phrase):
                sb = self.base(stem)
                best = {}
                for s in ORDER[:-1]:
                    for g, sc in sb[s].items():
                        best[g] = max(best.get(g, 0), sc)
                for g, sc in best.items():
                    for v in inflect(g, kind):
                        if v != letters(phrase):
                            infl[v] = max(infl.get(v, 0), max(sc - 0.2, 0.2))
        out = dict(out)
        out["infl"] = infl
        self.memo[phrase] = out
        return out

    def all_gives(self, phrase):
        """Every spelling any source can give for the phrase."""
        src = self.sources(phrase)
        return set().union(*src.values())

    def cands(self, phrase, limit=None):
        """[(gives, score, source)] best score first (common words first among ties), at most limit."""
        best = {}
        for s in ORDER:
            for g, sc in self.sources(phrase)[s].items():
                if g not in best or best[g][0] < sc:
                    best[g] = (sc, s)
        rank = self.res.words
        items = sorted(((sc, s, g) for g, (sc, s) in best.items()), key=lambda x: (-x[0], rank.get(x[2], 10 ** 7), x[2]))
        if limit:
            items = items[:limit]
        return [(g, sc, s) for sc, s, g in items]


# ---------------------------------------------------------------- the leaf-coverage metric

def coverage(sd, leaves):
    """leaves: (phrase key, gives) of the non-literal test leaves. Per source in ORDER: (name, share alone, new, cumulative)."""
    n = len(leaves)
    alone = collections.Counter()
    first = collections.Counter()
    cum = set()
    gains = {}
    hit_by = [set() for _ in leaves]
    for i, (k, g) in enumerate(leaves):
        src = sd.sources(k)
        for s in ORDER:
            if g in src[s]:
                alone[s] += 1
                hit_by[i].add(s)
    rows = []
    seen = [False] * n
    for s in ORDER:
        new = 0
        for i in range(n):
            if not seen[i] and s in hit_by[i]:
                seen[i] = True
                new += 1
        rows.append((s, alone[s], new, sum(seen)))
    old = sum(1 for i in range(n) if hit_by[i] & {"corpus", "abbr"} or
              leaves[i][1] in sd.res.wn_synonyms(leaves[i][0]))
    return n, rows, old
