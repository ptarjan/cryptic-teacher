#!/usr/bin/env python3
"""A code-only (no model) cryptic solver prototype, built to answer "can the corpus solve or validate clues?"

    python3 tools/det_solve.py corpus            # cache every annotated clue of every series (about 90 seconds, 8 processes)
    python3 tools/det_solve.py measure [--n 500]    # sample 30 Times puzzles, hold out their answers, measure VERIFY and SOLVE
    python3 tools/det_solve.py signal            # VERIFY vs the stored annotation: the disagreement list

Tables are built from the whole annotated corpus (wordplay trees): indicator phrase -> op, clue phrase -> letters
(synonyms and abbreviations), definition phrase -> answer. Test clues are drawn from the Times series only. Every
clue whose answer is a test answer is left out of the tables, so neither number leaks (--hold-puzzles is the old,
much harsher rule: drop each test puzzle and every puzzle sharing a test answer, about a third of all puzzles).

VERIFY gets the clue and the answer: is there a parse (a definition at one end, a wordplay that builds the
answer exactly from table pieces and indicator ops)? SOLVE gets the enumeration only (optionally some crossing
letters): is the true answer the top candidate the parses and definition tables produce?
Prototype only: nothing imports it and no queue runs it. Caches live in ~/.cache/detsolve/.
"""
import argparse
import collections
import glob
import gzip
import itertools
import json
import math
import os
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
CACHE = Path.home() / ".cache" / "detsolve"
SERIES = ("times", "sundaytimes", "timesjumbo", "timesquick", "timesclub")
LINK = {"and", "with", "then", "by", "to", "for", "of", "on", "in", "from", "is", "has", "gets", "get", "given",
        "giving", "provides", "after", "before", "a", "the", "as", "at", "one's", "its", "it", "that", "makes",
        "make", "for", "when", "so", "are", "be", "an", "gives", "produces", "going", "to", "'s", "with"}
SELECT_KINDS = ("first", "last", "middle", "outer", "alternate")


def letters(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper().replace("É", "E").replace("È", "E"))


def norm(s):
    s = (s or "").lower().replace("’", "'")
    return " ".join(re.findall(r"[a-z0-9'\-]+", s))


def tokens(text):
    """Clue words lowercased; a possessive 's becomes its own token."""
    out = []
    for w in re.findall(r"[\w'’\-]+", text.lower().replace("’", "'")):
        w = w.strip("'-")
        if not w:
            continue
        if w.endswith("'s") and len(w) > 2:
            out += [w[:-2], "'s"]
        else:
            out.append(w)
    return out


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def fmt(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100 * k / max(n, 1):.1f}% [{100 * lo:.1f}, {100 * hi:.1f}]"


# ---------------------------------------------------------------- corpus

def load_corpus(force=False):
    """Every annotated clue of the Times family: dicts with pid, clue, enum, answer, defs, tree."""
    f = CACHE / "corpus.json.gz"
    if f.exists() and not force:
        return json.load(gzip.open(f, "rt"))
    CACHE.mkdir(parents=True, exist_ok=True)
    paths = sorted(glob.glob(str(ROOT / "puzzles" / "*" / "*" / "*.json")))
    from multiprocessing import Pool
    with Pool(min(8, os.cpu_count() or 2)) as pool:
        rows = [r for part in pool.imap(_load_one, paths, chunksize=64) for r in part]
    json.dump(rows, gzip.open(f, "wt"))
    return rows


def _load_one(p):
    """Annotated clues of one puzzle file (every series under puzzles/)."""
    try:
        d = json.load(open(p))
    except Exception:
        return []
    out = []
    s = Path(p).parent.parent.name
    for e in d.get("entries", []):
        a = e.get("annotation") or {}
        w = a.get("wordplay")
        if not w or not e.get("solution"):
            continue
        out.append({"pid": d["id"], "series": s, "num": e["number"], "dir": e["direction"],
                    "clue": e["clue"]["text"], "enum": e["clue"].get("enumeration", ""),
                    "answer": letters(e["solution"]),
                    "defs": [x.get("text", "") for x in a.get("definitions", [])],
                    "tree": w, "andlit": bool(a.get("andLit"))})
    return out


def clue_type(tree):
    op = tree.get("op")
    if op == "cryptic":
        return "cryptic def"
    if op in ("charade", "anagram", "container", "reversal", "deletion", "hidden", "homophone"):
        return op
    if op in SELECT_KINDS or op in ("regular", "nth"):
        return "selection"
    return "other:" + str(op)


# ---------------------------------------------------------------- tables

def walk(node, tab, parent=None):
    op = node.get("op")
    if op is None:
        words, gives = node.get("words"), letters(node.get("gives", ""))
        if words and gives and parent not in ("anagram", "hidden", "homophone") and parent not in SELECT_KINDS:
            if letters(words) != gives and not node.get("unchecked"):
                tab["syn"][norm(words)][gives] += 1
        return
    kind = op
    parts = node.get("parts", [])
    if op == "deletion" and len(parts) == 1 and node.get("gives") and parts[0].get("words"):
        src = letters(parts[0].get("gives", ""))
        g = letters(node["gives"])
        if src and g == src[1:]:
            kind = "delfirst"
        elif src and g == src[:-1]:
            kind = "dellast"
        elif src and g == src[1:-1]:
            kind = "delouter"
    for ind in node.get("indicators", []):
        k = norm(ind.get("text", ""))
        if k:
            tab["ind"][k][kind] += 1
    for p in parts:
        walk(p, tab, op)


def build_tables(rows, exclude_pids, exclude_answers):
    tab = {"syn": collections.defaultdict(collections.Counter), "ind": collections.defaultdict(collections.Counter),
           "def": collections.defaultdict(collections.Counter)}
    bad = set(exclude_pids)
    for r in rows:
        if r["pid"] in bad:
            continue
        if r["answer"] in exclude_answers:
            continue
        walk(r["tree"], tab)
        for dtext in r["defs"]:
            k = norm(dtext)
            if k:
                tab["def"][k][r["answer"]] += 1
    return tab


def puzzles_sharing(rows, answers):
    """pids that contain any of these answers (they are held out of the tables too)."""
    return {r["pid"] for r in rows if r["answer"] in answers}


# ---------------------------------------------------------------- lexicon, wordnet, abbreviations

class Resources:
    def __init__(self, train_answers):
        self.words = {}          # LETTERS -> frequency rank
        for line in open(ROOT / "tools" / "data" / "lexicon.tsv", encoding="utf-8", errors="replace"):
            if line.startswith("#"):
                continue
            p = line.split("\t")
            if len(p) > 2 and p[0].isalpha():
                w = letters(p[0])
                if w and w not in self.words:
                    self.words[w] = int(p[1]) if p[1].isdigit() else 10 ** 6
        for a in train_answers:
            self.words.setdefault(a, 10 ** 6)
        self.by_len = collections.defaultdict(list)
        self.anag = collections.defaultdict(list)
        for w in self.words:
            self.by_len[len(w)].append(w)
            self.anag["".join(sorted(w))].append(w)
        wn = json.load(gzip.open(ROOT / "tools" / "data" / "wordnet.json.gz", "rt"))
        self.wn_words = wn["words"]
        self.wn_syn = wn["synsets"]
        self.members = collections.defaultdict(list)
        for w, ids in self.wn_words.items():
            for i in ids:
                self.members[i].append(w)
        try:
            import build_abbreviations as ba
            self.abbr = collections.defaultdict(list)
            for w, k in ba.dictionary():
                self.abbr[norm(w)].append(letters(k))
        except Exception:
            self.abbr = collections.defaultdict(list)

    def wn_neighbours(self, phrase, depth=2):
        """lowercase members of phrase's synsets and their hypernyms (depth)."""
        key = phrase.replace(" ", "_")
        out = {}
        seen = set()
        front = list(self.wn_words.get(key, []))
        direct = set(front)
        for d in range(depth):
            nxt = []
            for s in front:
                if s in seen:
                    continue
                seen.add(s)
                for m in self.members.get(s, []):
                    out.setdefault(letters(m), d if s in direct else d + 1)
                nxt += self.wn_syn[s][1]
            front = nxt
        return out

    def wn_synonyms(self, phrase):
        key = phrase.replace(" ", "_")
        res = []
        for s in self.wn_words.get(key, [])[:6]:
            for m in self.members.get(s, []):
                L = letters(m)
                if L and L != letters(phrase) and L not in res:
                    res.append(L)
        return res

    def def_support(self, dphrase, answer):
        """0 none, 1 wordnet near (shared synset or hypernym either way), 2 stored definition."""
        nb = self.wn_neighbours(dphrase)
        if answer in nb:
            return 1
        # def is a hypernym of the answer
        for w in dphrase.split():
            for a in self.wn_neighbours(answer.lower()).keys():
                if a == letters(w):
                    return 1
        return 0


# ---------------------------------------------------------------- search

def item_len(it):
    return len(it) - 1 if it[:1] == "*" else len(it) - 2 if it[:1] == "~" else len(it)


def pat_len(p):
    return sum(item_len(i) for i in p)


class Clue:
    """Pieces of one clue: P(i, j) gives scored patterns for a span of words."""

    def __init__(self, text, n, tab, res, answer=None, ind_cache=None):
        self.text = text
        self.t = tokens(text)
        self.m = len(self.t)
        self.n = n
        self.tab = tab
        self.res = res
        self.answer = answer
        self.memo = {}
        self.units_memo = {}
        self.pcount = 0
        if answer:
            self.subs = set()
            for s in (answer, answer[::-1]):
                for a in range(len(s)):
                    for b in range(a + 1, len(s) + 1):
                        self.subs.add(s[a:b])

    def key(self, i, j):
        return " ".join(self.t[i:j])

    def lit(self, i, j):
        return letters("".join(self.t[i:j]))

    def ok(self, p):
        """verify-mode prune: fixed items must occur in the answer (either direction)."""
        if self.answer is None:
            return True
        for it in p:
            if not it or (it[0] not in "*~" and it not in self.subs):
                return False
            if it[0] == "*" and len(it) - 1 > self.n:
                return False
        return True

    def kinds(self, i, j):
        return self.tab["ind"].get(self.key(i, j))

    def units(self, i, j):
        k = (i, j)
        if k in self.units_memo:
            return self.units_memo[k]
        out = {}
        key = self.key(i, j)
        width = j - i
        if width <= 4:
            syn = self.tab["syn"].get(key)
            if syn:
                for g, c in syn.most_common(400 if self.answer else 30):
                    if len(g) <= self.n and (not self.answer or g in self.subs or len(g) <= 3 or g[::-1] in self.subs
                                             or len(syn) < 30):
                        out[(g,)] = (1.0 + min(c, 5) * 0.15, f"{key}->{g}")
            for g in self.res.abbr.get(key, [])[:10]:
                if g and len(g) <= self.n:
                    out.setdefault((g,), (0.9, f"{key}->{g}"))
            if width <= 2 and not self.tab["syn"].get(key):
                for g in self.res.wn_synonyms(key)[:30]:
                    if 2 <= len(g) <= self.n - 1 or (self.n == len(g)):
                        out.setdefault((g,), (0.45, f"{key}~{g}"))
            if width == 1:
                L = self.lit(i, j)
                if 1 <= len(L) <= 5 and len(L) < self.n:
                    out.setdefault((L,), (0.35, f"{key}=lit"))
                if key == "'s":
                    out.setdefault(("S",), (0.4, "'s=S"))
        self.units_memo[k] = out
        return out

    def P(self, i, j, depth=0):
        k = (i, j)
        if k in self.memo:
            return self.memo[k]
        self.memo[k] = {}
        out = {}

        def add(p, sc, d):
            if not p or pat_len(p) > self.n or any(not x for x in p):
                return
            if p not in out or out[p][0] < sc:
                out[p] = (sc, d)

        for p, (sc, d) in self.units(i, j).items():
            add(p, sc, d)
        if j - i >= 1 and depth < 3:
            self.ops(i, j, add, depth)
            for mid in range(i + 1, j):
                left = self.P(i, mid, depth + 1)
                right = self.P(mid, j, depth + 1)
                if not left or not right:
                    continue
                for lp, (ls, ld) in itertools.islice(sorted(left.items(), key=lambda x: -x[1][0]), 30):
                    for rp, (rs, rd) in itertools.islice(sorted(right.items(), key=lambda x: -x[1][0]), 30):
                        q = lp + rp
                        if pat_len(q) <= self.n and self.ok(q):
                            add(q, ls + rs, f"({ld}+{rd})")
            if self.t[i] in LINK and j - i > 1:
                for p, (sc, d) in self.P(i + 1, j, depth).items():
                    add(p, sc - 0.4, d)
            if self.t[j - 1] in LINK and j - i > 1:
                for p, (sc, d) in self.P(i, j - 1, depth).items():
                    add(p, sc - 0.4, d)
        if len(out) > 80:
            ranked = sorted(out.items(), key=lambda x: -x[1][0])
            keep = [x for x in ranked if not x[1][1].startswith("(")][:80] + \
                   [x for x in ranked if x[1][1].startswith("(")][:60]
            out = dict(keep)
        self.memo[k] = out
        return out

    def fixed1(self, i, j, depth):
        """operand patterns that are one fixed string (charades joined)."""
        res = []
        for p, (sc, d) in self.P(i, j, depth + 1).items():
            if all(it.isalpha() for it in p) and not d.startswith("hid"):
                res.append(("".join(p), sc, d))
        return res

    def ops(self, i, j, add, depth):
        t = self.t
        # indicator at the left end: ind [i,l), operand [l,j) ; at the right end: operand [i,k), ind [k,j)
        for (ia, ib, oa, ob) in [(i, l, l, j) for l in range(i + 1, min(j, i + 5))] + \
                                [(k, j, i, k) for k in range(max(i + 1, j - 4), j)]:
            kinds = self.kinds(ia, ib)
            if not kinds or oa >= ob:
                continue
            ind = self.key(ia, ib)
            for kind, cnt in kinds.most_common(4):
                w = 1.2 + min(cnt, 20) * 0.05
                if kind == "anagram":
                    L = self.lit(oa, ob)
                    if 3 <= len(L) <= self.n:
                        add(("*" + "".join(sorted(L)),), w + 0.8, f"ana<{ind}>({self.key(oa, ob)})")
                    if ob - oa >= 2:
                        for s, sc, d in self.fixed1(oa, ob, depth):
                            if 3 <= len(s) <= self.n and s != L:
                                add(("*" + "".join(sorted(s)),), sc + w + 0.5, f"ana<{ind}>({d})")
                elif kind == "reversal":
                    for s, sc, d in self.fixed1(oa, ob, depth):
                        add((s[::-1],), sc + w, f"rev<{ind}>({d})")
                elif kind in ("first", "last", "middle", "outer", "alternate"):
                    for s in self.selection(kind, oa, ob):
                        add((s,), w + 0.7, f"{kind}<{ind}>({self.key(oa, ob)})")
                elif kind in ("delfirst", "dellast", "delouter"):
                    for s, sc, d in self.fixed1(oa, ob, depth):
                        if len(s) >= 3:
                            r = s[1:] if kind == "delfirst" else s[:-1] if kind == "dellast" else s[1:-1]
                            add((r,), sc + w, f"{kind}<{ind}>({d})")
        # three-part: X ind Y  (container / deletion)
        for ka in range(i + 1, j):
            for kb in range(ka + 1, min(j, ka + 4) + 0):
                kinds = self.kinds(ka, kb)
                if not kinds or kb >= j:
                    continue
                ind = self.key(ka, kb)
                for kind, cnt in kinds.most_common(4):
                    w = 1.2 + min(cnt, 20) * 0.05
                    if kind == "anagram":
                        L = self.lit(i, ka) + self.lit(kb, j)
                        if 3 <= len(L) <= self.n:
                            add(("*" + "".join(sorted(L)),), w + 0.6, f"ana<{ind}>({self.key(i, ka)} | {self.key(kb, j)})")
                        continue
                    if kind not in ("container", "deletion"):
                        continue
                    X = self.P(i, ka, depth + 1)
                    Y = self.P(kb, j, depth + 1)
                    if not X or not Y:
                        continue
                    for (xp, (xs, xd)), (yp, (ys, yd)) in itertools.product(
                            itertools.islice(sorted(X.items(), key=lambda a: -a[1][0]), 14),
                            itertools.islice(sorted(Y.items(), key=lambda a: -a[1][0]), 14)):
                        if kind == "container":
                            for (op_, ip_, a_, b_) in ((xp, yp, xd, yd), (yp, xp, yd, xd)):
                                if len(op_) == 1 and op_[0][:1] == "*" and len(op_[0]) >= 3 \
                                        and all(x[:1] not in ("*", "~") for x in ip_) and ip_:
                                    q = ("~" + op_[0][1:] + "|" + "".join(ip_),)
                                    if pat_len(q) <= self.n:
                                        add(q, xs + ys + w, f"ins<{ind}>({a_},{b_})")
                                if op_ and all(x[:1] not in ("*", "~") for x in op_) and len("".join(op_)) >= 2:
                                    s = "".join(op_)
                                    for c in range(1, len(s)):
                                        q = (s[:c],) + ip_ + (s[c:],)
                                        if pat_len(q) <= self.n and self.ok(q):
                                            add(q, xs + ys + w, f"ins<{ind}>({a_},{b_})")
                        else:
                            for (a_, b_, ad, bd) in ((xp, yp, xd, yd), (yp, xp, yd, xd)):
                                if len(a_) == 1 and len(b_) == 1 and a_[0][0] != "*" and b_[0][0] != "*":
                                    s, r = a_[0], b_[0]
                                    if r and r in s and len(s) > len(r):
                                        q = (s.replace(r, "", 1),)
                                        if self.ok(q):
                                            add(q, xs + ys + w, f"del<{ind}>({ad},{bd})")
                                        if len(r) == 1 and s.count(r) > 1:
                                            q = (s.replace(r, ""),)
                                            if self.ok(q):
                                                add(q, xs + ys + w, f"del<{ind}>({ad},{bd})")
        # hidden / reversed hidden: only meaningful for a whole wordplay; produce fixed substrings of length n
        for (ia, ib, oa, ob) in [(i, l, l, j) for l in range(i + 1, min(j, i + 5))] + \
                                [(k, j, i, k) for k in range(max(i + 1, j - 4), j)]:
            kinds = self.kinds(ia, ib)
            if not kinds or oa >= ob or "hidden" not in kinds:
                continue
            L = self.lit(oa, ob)
            for rev in (False, True):
                S = L[::-1] if rev else L
                for a in range(0, len(S) - self.n + 1):
                    s = S[a:a + self.n]
                    add((s,), 2.6, f"hid{'rev' if rev else ''}<{self.key(ia, ib)}>({self.key(oa, ob)})")
                    break_ = False
        return

    def selection(self, kind, a, b):
        toks = [letters(x) for x in self.t[a:b] if letters(x)]
        if not toks:
            return []
        out = []
        if kind == "first":
            out.append("".join(x[0] for x in toks))
            if len(toks) == 1:
                out = [toks[0][0]]
        elif kind == "last":
            out.append("".join(x[-1] for x in toks))
            if len(toks) == 1:
                out = [toks[0][-1]]
        elif kind == "outer":
            out.append("".join(x[0] + x[-1] if len(x) > 1 else x for x in toks))
        elif kind == "middle":
            for x in toks[:1]:
                if len(x) >= 3:
                    c = len(x) // 2
                    out.append(x[c] if len(x) % 2 else x[c - 1:c + 1])
        elif kind == "alternate":
            s = "".join(toks)
            out += [s[0::2], s[1::2]]
        return [o for o in out if o]

    # --- top-level
    def splits(self):
        """(definition span, wordplay span): the definition is 1..6 words at one end."""
        res = []
        for k in range(1, min(self.m, 7)):
            res.append(((0, k), (k, self.m)))
            res.append(((self.m - k, self.m), (0, self.m - k)))
        return res


def match_pattern(p, answer):
    """Does a pattern build the answer exactly?"""
    pos = 0
    for it in p:
        if it[0] == "~":
            B, s = it[1:].split("|")
            L = len(B) + len(s)
            seg = answer[pos:pos + L]
            if len(seg) != L or not any(seg[c:c + len(s)] == s and "".join(sorted(seg[:c] + seg[c + len(s):])) == B
                                        for c in range(1, len(B))):
                return False
            pos += L
        elif it[0] == "*":
            L = len(it) - 1
            seg = answer[pos:pos + L]
            if len(seg) != L or "".join(sorted(seg)) != it[1:]:
                return False
            pos += L
        else:
            if answer[pos:pos + len(it)] != it:
                return False
            pos += len(it)
    return pos == len(answer)


def verify(cl, answer, res):
    """Best parse building the answer with a definition at one end: (score, desc, def phrase, def_support)."""
    best = None
    for (da, db), (wa, wb) in cl.splits():
        if wb - wa < 1:
            continue
        for p, (sc, d) in cl.P(wa, wb).items():
            if match_pattern(p, answer):
                dp = cl.key(da, db)
                if best is None or sc > best[0]:
                    best = (sc, d, dp, None, (da, db))
    if best:
        sup = def_score(cl, best[2], answer, res)
        best = (best[0], best[1], best[2], sup)
    return best


def def_score(cl, dphrase, answer, res):
    tab = cl.tab["def"].get(dphrase)
    if tab and answer in tab:
        return 2
    return res.def_support(dphrase, answer)


def mask_ok(w, mask):
    return mask is None or all(c == "?" or c == x for c, x in zip(mask, w))


def solve(cl, res, mask=None, enum_words=1):
    """Ranked candidates [(score, word, why)] from wordplay parses and definition tables."""
    n = cl.n
    cands = {}

    def put(w, sc, why):
        if len(w) != n or w not in res.words or not mask_ok(w, mask):
            return
        if w not in cands or cands[w][0] < sc:
            cands[w] = (sc, why)

    for (da, db), (wa, wb) in cl.splits():
        dp = cl.key(da, db)
        dsc = {}
        for a, c in cl.tab["def"].get(dp, {}).items():
            if len(a) == n:
                dsc[a] = 2.5
        for a, v in res.wn_neighbours(dp).items():
            if len(a) == n:
                dsc.setdefault(a, 1.2 - 0.3 * v)
        if da == 0 and db == cl.m:
            continue
        for a, v in dsc.items():
            put(a, v - 0.5 * (db - da > 3), f"def[{dp}]")
        for p, (sc, d) in cl.P(wa, wb).items():
            if pat_len(p) != n:
                continue
            bags = [x for x in p if x[0] in "*~"]
            words = []
            if not bags:
                words = ["".join(p)]
            elif len(bags) == 1:
                bi = [x for x in p].index(bags[0])
                pre = "".join(p[:bi])
                suf = "".join(p[bi + 1:])
                b = bags[0]
                key = b[1:] if b[0] == "*" else "".join(sorted(b[1:].replace("|", "")))
                words = [w for w in res.anag.get(key, []) if w.startswith(pre) and w.endswith(suf)
                         and match_pattern(p, w)]
            for w in words:
                bonus = dsc.get(w, 0)
                freq = 0.9 / (1 + math.log10(1 + res.words.get(w, 10 ** 6)) / 2)
                put(w, sc + bonus * 1.5 + freq, d + (f" +def[{dp}]" if bonus else ""))
    # double definition: two stored/wordnet definitions agreeing is covered by dsc across splits
    return sorted(((s, w, y) for w, (s, y) in cands.items()), reverse=True)


UNSUPPORTED = {"homophone", "substitution", "cycling", "spoonerism", "composite", "palindrome", "reverse", "rebus",
               "move", "cryptic", "regular", "nth", None}


def gaps(node, tab, res, parent=None, out=None):
    """What the stored tree uses that the tables have never seen: ('op', kind), ('syn', words, gives), ('ind', text, kind)."""
    if out is None:
        out = []
    op = node.get("op")
    if op is None:
        words, gives = node.get("words"), letters(node.get("gives", ""))
        if words and gives and parent not in ("anagram", "hidden", "homophone") and parent not in SELECT_KINDS \
                and letters(words) != gives:
            key = norm(words)
            if gives not in tab["syn"].get(key, {}) and gives not in res.abbr.get(key, []) \
                    and gives not in res.wn_synonyms(key):
                out.append(("syn", words, gives))
        return out
    kind = op
    parts = node.get("parts", [])
    if op == "deletion" and len(parts) == 1 and node.get("gives") and parts[0].get("words"):
        src, g = letters(parts[0].get("gives", "")), letters(node["gives"])
        kind = "delfirst" if src and g == src[1:] else "dellast" if src and g == src[:-1] else \
            "delouter" if src and g == src[1:-1] else op
    if op in UNSUPPORTED:
        out.append(("op", op))
    for ind in node.get("indicators", []):
        k = norm(ind.get("text", ""))
        if k and kind not in tab["ind"].get(k, {}):
            out.append(("ind", ind.get("text", ""), kind))
    for p in parts:
        gaps(p, tab, res, op, out)
    return out


def failure_cause(g):
    """The single most basic reason a parse could not be found."""
    for want in ("op", "syn", "ind"):
        if any(x[0] == want for x in g):
            return {"op": "op not implemented (homophone/substitution/move/cd...)",
                    "syn": "synonym/abbreviation not in tables", "ind": "indicator not in tables for that op"}[want]
    return "tables cover it: search/engine limit"


# ---------------------------------------------------------------- evaluation

def sample_clues(rows, n_puz=30, n_clues=500, seed=7):
    rnd = random.Random(seed)
    by = collections.defaultdict(list)
    for r in rows:
        if r["series"] in SERIES:     # tests come from Times clues only, so numbers compare across corpus sizes
            by[r["pid"]].append(r)
    pids = sorted(p for p, v in by.items() if len(v) >= 14)
    rnd.shuffle(pids)
    pids = pids[:n_puz]
    per = n_clues // n_puz + 1
    out = []
    for p in pids:
        v = by[p][:]
        rnd.shuffle(v)
        out += v[:per]
    return pids, out[:n_clues]


def enum_len(e):
    return sum(int(x) for x in re.findall(r"\d+", e or ""))


def run_eval(n_clues=500, seed=7, budget=150, hold=True):
    t0 = time.time()
    rows = load_corpus()
    pids, test = sample_clues(rows, 30, n_clues, seed)
    ans = {r["answer"] for r in test}
    # hold out the whole sampled puzzles and every puzzle holding any of their answers
    all_test_answers = ans
    n_all = len({r["pid"] for r in rows})
    legacy = set(pids) | puzzles_sharing(rows, all_test_answers)
    if hold == "puzzle":
        # legacy: drop the test puzzles and every puzzle sharing a test answer
        excl, excl_ans = legacy, set()
    elif hold:
        # drop only the clues whose answer is a test answer (and the test clues themselves): no leakage, little loss
        excl, excl_ans = set(), set(all_test_answers)
    else:
        excl, excl_ans = set(), set()
    tab = build_tables(rows, excl, excl_ans)
    train_answers = {r["answer"] for r in rows if r["pid"] not in excl and r["answer"] not in excl_ans}
    res = Resources(train_answers)
    n_clue_drop = sum(1 for r in rows if r["pid"] in excl or r["answer"] in excl_ans)
    print(f"tables: syn {len(tab['syn'])} ind {len(tab['ind'])} def {len(tab['def'])}; "
          f"legacy puzzle hold-out would drop {len(legacy)} of {n_all} puzzles; this run drops {len(excl)} puzzles "
          f"and {n_clue_drop} of {len(rows)} clues; {time.time() - t0:.0f}s", flush=True)
    results = []
    for idx, r in enumerate(test):
        if time.time() - t0 > budget:
            print("budget hit at", idx, flush=True)
            break
        n = enum_len(r["enum"]) or len(r["answer"])
        t1 = time.time()
        cl = Clue(r["clue"], n, tab, res, answer=r["answer"])
        v = verify(cl, r["answer"], res)
        cl2 = Clue(r["clue"], n, tab, res)
        ranked = solve(cl2, res)
        words = [w for _, w, _ in ranked]
        rank = words.index(r["answer"]) + 1 if r["answer"] in words else None
        mask = "".join(c if (hash((r["pid"], r["num"], i)) % 5) < 2 else "?" for i, c in enumerate(r["answer"]))
        mask = "".join(c if random.Random(f"{r['pid']}{r['num']}{i}").random() < 0.4 else "?"
                       for i, c in enumerate(r["answer"]))
        ranked_m = solve(cl2, res, mask=mask)
        words_m = [w for _, w, _ in ranked_m]
        rank_m = words_m.index(r["answer"]) + 1 if r["answer"] in words_m else None
        results.append({"pid": r["pid"], "num": r["num"], "dir": r["dir"], "clue": r["clue"], "enum": r["enum"],
                        "answer": r["answer"], "type": clue_type(r["tree"]), "verify": v, "rank": rank,
                        "rank_mask": rank_m, "top": ranked[:3], "secs": time.time() - t1,
                        "gaps": gaps(r["tree"], tab, res), "stored": r["tree"], "defs": r["defs"], "multiword": len(re.findall(r"\d+", r["enum"])) > 1})
    json.dump(results, open(CACHE / "eval.json", "w"))
    return results


def report(results):
    byt = collections.defaultdict(list)
    for r in results:
        byt["ALL"].append(r)
        byt[r["type"]].append(r)
    print(f"{'type':14s} {'n':>4s}  VERIFY(parse)                      +def-supported                 SOLVE top1                       top5                            top1 w/40% letters")
    for t in sorted(byt, key=lambda x: (x != "ALL", -len(byt[x]))):
        v = byt[t]
        n = len(v)
        vp = sum(1 for r in v if r["verify"])
        vd = sum(1 for r in v if r["verify"] and r["verify"][3])
        t1 = sum(1 for r in v if r["rank"] == 1)
        t5 = sum(1 for r in v if r["rank"] and r["rank"] <= 5)
        tm = sum(1 for r in v if r["rank_mask"] == 1)
        print(f"{t:14s} {n:4d}  {fmt(vp, n):34s} {fmt(vd, n):30s} {fmt(t1, n):32s} {fmt(t5, n):32s} {fmt(tm, n)}")
    sw = [r for r in results if not r["multiword"]]
    print("single-word answers:", fmt(sum(1 for r in sw if r["rank"] == 1), len(sw)), "top1;",
          fmt(sum(1 for r in sw if r["rank"] and r["rank"] <= 5), len(sw)), "top5")
    fails = [r for r in results if not r["verify"]]
    c = collections.Counter(failure_cause([tuple(x) for x in r["gaps"]]) for r in fails)
    print("VERIFY failures by first cause:", {k: f"{v} ({100 * v / max(len(fails), 1):.0f}%)" for k, v in c.items()})
    print("mean secs/clue", sum(r["secs"] for r in results) / max(len(results), 1))


R30 = Path("/data/home/.cache/fpfn_20261019_r30")


def r30_misses():
    """The judged FN misses (verdict A/B/E/S) of the r30 kit: their stored rows."""
    rows = json.load(open(R30 / "fn_sample.json"))
    out = []
    for f in glob.glob(str(R30 / "v_fn_*.txt")):
        for line in open(f):
            m = re.match(r"\s*(\d+)\s+([ABCESX])\b\s*(.*)", line)
            if m and m.group(2) in "ABES":
                out.append((rows[int(m.group(1))], m.group(2), m.group(3)))
    return out


def flags_for(tree, clue, answer, n, tab, res):
    """Signal flags for one stored annotation: unseen synonym (F1), unseen indicator (F2), and whether a parse exists."""
    g = gaps(tree, tab, res)
    cl = Clue(clue, n, tab, res, answer=answer)
    v = verify(cl, answer, res)
    f = []
    if any(x[0] == "syn" for x in g):
        f.append("F1 unseen synonym")
    if any(x[0] == "ind" for x in g):
        f.append("F2 unseen indicator")
    if f and v:
        f.append("F3 table parse exists, differs from stored")
    cut = ("deletion", "delfirst", "dellast", "delouter", "first", "last", "middle", "outer", "alternate")
    for x in g:
        if x[0] == "syn":
            hit = [w for w in tokens(x[1]) if sum(tab["ind"].get(w, {}).get(k, 0) for k in cut) >= 3 and sum(tab["ind"].get(w, {}).get(k, 0) for k in cut) >= 0.6 * sum(tab["ind"].get(w, {}).values())
                   ]
            if hit:
                f.append(f"F4 unseen synonym leaf swallows indicator word {hit[0]!r}")
                break
    return f, g, v


def run_signal(n_clues=500, seed=7, n_judge=40, budget=150):
    t0 = time.time()
    rows = load_corpus()
    pids, test = sample_clues(rows, 30, n_clues, seed)
    misses = r30_misses()
    r30_pids = {m[0]["id"].split("#")[0] for m in misses}
    # a puzzle under validation is checked against every OTHER puzzle: leave the checked ones out
    tab = build_tables(rows, set(pids) | r30_pids, set())
    res = Resources({r["answer"] for r in rows})
    print(f"signal tables: syn {len(tab['syn'])} ind {len(tab['ind'])}; {time.time() - t0:.0f}s", flush=True)
    flagged, allrows = [], []
    for r in test:
        n = enum_len(r["enum"]) or len(r["answer"])
        f, g, v = flags_for(r["tree"], r["clue"], r["answer"], n, tab, res)
        allrows.append((r, f, g, v))
        if f:
            flagged.append((r, f, g, v))
    c = collections.Counter(x for _, f, _, _ in allrows for x in f)
    anyf = sum(1 for _, f, _, _ in allrows if f)
    print("sample", len(allrows), "flagged any", fmt(anyf, len(allrows)), dict(c))
    rnd = random.Random(seed)
    pick = rnd.sample(flagged, min(n_judge, len(flagged)))
    import wordplay
    with open(CACHE / "judge_items.txt", "w") as fh:
        for i, (r, f, g, v) in enumerate(pick):
            fh.write(f"{i}\nCLUE: {r['clue']} ({r['enum']})\nANSWER: {r['answer']}\nDEFINITION(S): {'; '.join(r['defs'])}\n"
                     f"TREE: {wordplay.render(r['tree'])}\nVALIDATOR FLAG: {'; '.join(f)}; unseen={[x[1:] for x in g][:4]}"
                     f"{'; table parse: ' + v[1] if v else ''}\n\n")
    print("wrote", len(pick), "items to", CACHE / "judge_items.txt")
    f4 = [x for x in flagged if any(s.startswith("F4") for s in x[1])]
    print("F4 flagged:", fmt(len(f4), len(allrows)))
    with open(CACHE / "judge_items_f4.txt", "w") as fh:
        for i, (r, f, g, v) in enumerate(f4[:40]):
            fh.write(f"{i}\nCLUE: {r['clue']} ({r['enum']})\nANSWER: {r['answer']}\nDEFINITION(S): {'; '.join(r['defs'])}\n"
                     f"TREE: {wordplay.render(r['tree'])}\nVALIDATOR FLAG: {'; '.join(f)}\n\n")
    # r30 overlap
    hit = hit4 = 0
    detail = []
    for row, verdict, why in misses:
        a = letters(row["solution"])
        f, g, v = flags_for(row["wordplay"], row["clue"], a, len(a), tab, res)
        hit += bool(f)
        hit4 += any(s.startswith("F4") for s in f)
        detail.append((row["id"], verdict, f, bool(v)))
    print("r30 FN misses flagged:", fmt(hit, len(misses)), "; F4 only:", fmt(hit4, len(misses)))
    print("r30 misses with a table parse:", sum(1 for d in detail if d[3]), "of", len(detail))
    json.dump({"detail": detail}, open(CACHE / "signal_r30.json", "w"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["corpus", "measure", "report", "signal"])
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--budget", type=int, default=150)
    ap.add_argument("--leaky", action="store_true", help="ceiling check: tables include the test puzzles")
    ap.add_argument("--hold-puzzles", action="store_true", help="legacy hold-out: drop whole puzzles sharing a test answer")
    a = ap.parse_args()
    if a.cmd == "corpus":
        t = time.time()
        rows = load_corpus(force=True)
        print(len(rows), "annotated clues", f"{time.time() - t:.0f}s")
        print(collections.Counter(clue_type(r["tree"]) for r in rows).most_common())
    elif a.cmd == "measure":
        report(run_eval(a.n, a.seed, a.budget, False if a.leaky else "puzzle" if a.hold_puzzles else "answer"))
    elif a.cmd == "report":
        report(json.load(open(CACHE / "eval.json")))
    elif a.cmd == "signal":
        run_signal(a.n, a.seed)


if __name__ == "__main__":
    main()
