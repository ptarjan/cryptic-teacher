#!/usr/bin/env python3
"""Clue types, fodder and indicators read off the letters, where the blog left them out.

Given the answer, the clue and what blog_facts.py already holds for it (the
definition, the blocks), some wordplay is a matter of arithmetic: a run of
clue words that is a permutation of the answer is anagram fodder, the answer
spelt across word boundaries is hidden, and blocks that put together make the
answer say how they were put together. Only a reading that is the one reading
the letters allow is kept.

The blocks a blog left out ("D[utch] + ADA + IS + [Utrech]T" glosses two of
four; bigdave44 writes prose) are read the same way: the answer split into
the blocks the blog gave and runs of the other clue words, each run read as
blogs read those words in other puzzles, kept where the split is the only
one (see infer_blocks). Each is held as [letters, clue words, "inferred"]
and written as a block object with `inferred: true` (blog_facts.fact_json
gives the file shape).
An anagram the blog gave no blocks has its fodder for its one block (see infer_fodder).
Where a write-up gives its blocks in prose ("GAFFE or error", "a synonym of
'misrepresent' followed by Female"), what it prints (blog_facts.leads) says
which pieces to try, and the split is kept on the same terms (see
infer_fuzzy_blocks); anagram fodder is written with "anagrammed" after.
A hidden word's one block is its carrier, the one run of clue words
outside the definition that spells it (see infer_carrier), as our own
annotations write it. A homophone's or a spoonerism's blocks are the blog's,
heard ([letters, clue words, {"soundsLike": the words heard}], see
blog_facts.heard_blocks), and want that part's indicator.

Where the blog then has the definition and every block but named no
indicator, the part the blocks want one for (a container, a reversal, ...)
is given the one run of the other clue words blogs name that part's
indicator in other puzzles, all the rest link words (see infer_indicators);
"indicators" is then named in the clue's "inferred".

Where the blog named no definition, it is the one span at an end of the
clue, clear of the wordplay, that blogs underlined for the same answer
elsewhere, where the word inside it is wordplay or a word blogs leave out
of definitions (see infer_definition); "definitions" is then named in the
clue's "inferred". It is read before the indicators, which want one.

    python3 tools/letter_facts.py --measure   # precision per type where the blog named it
    python3 tools/letter_facts.py --measure-blocks  # the inferred blocks on 1 puzzle in 20, held out
    python3 tools/letter_facts.py --measure-indicators  # the inferred indicators the same way
    python3 tools/letter_facts.py --measure-definitions  # the inferred definitions the same way
    python3 tools/letter_facts.py --measure-fuzzy-blocks  # the blocks read off write-ups' prose the same way
    python3 tools/letter_facts.py --measure-blockless  # hidden, homophone and spoonerism blocks and indicators, free-word indicators
    python3 tools/letter_facts.py --coverage  # what the written facts cover, and why the rest fall short
    python3 tools/letter_facts.py --fill      # what it would add to untyped clues
    python3 tools/letter_facts.py --clue 'Men on phone exchange will be a rarity' PHENOMENON
"""
import argparse
import collections
import copy
import functools
import hashlib
import itertools
import json
import os
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import enumeration  # noqa: E402 -- the clue rows below are printed lines, count included
from blog_facts import (
    ABBR,
    ENUM_TAIL,
    GOLD,
    INFERRED,
    LEADS,
    OUT,
    PART_ORDER,
    clue_body,
    fact_from_json,
    fact_json,
    file_text,
    heard_blocks,
)
from indicator_keys import WORD, letters
from indicator_keys import indicator_words as _key
from puzzle_paths import find as find_puzzle
from puzzle_paths import puzzle_files

#: A hidden answer shorter than this turns up by chance in too many clues.
MIN_HIDDEN = 4
#: Nor is an anagram of fewer letters worth a claim: ERA in "are" is as often a literal.
MIN_ANAGRAM = 4
#: An indicator is a phrase blogs have named for that part in this many clues.
MIN_INDICATOR = 3
#: A spoonerism swaps sounds, so its letters look like an anagram's.
SPOONER = re.compile(r'\bspooner', re.IGNORECASE)
#: What a reading costs: of two that spell the answer, the one with fewer of
#: these is the setter's, as S+CORE+R is a charade and not CORES anagrammed round R.
OPERATIONS = {"anagram", "container", "reversal"}
#: Anagramming a block costs one more: a blog writes a block's letters as they
#: stand in the answer, so TOAST around IE is its reading and not TOA + STIE.
BLOCK_ANAGRAM = "block anagram"


def cost(parts):
    return len(parts & OPERATIONS) + (BLOCK_ANAGRAM in parts)
#: A cut takes at most this many letters from a word: "endlessly", "heartless".
MAX_CUT = 2
#: The types written into the corpus, as tuples: each at least 97% the blog's
#: own type on the held-out blog-typed clues (--measure). Any other reading is
#: left out.
TRUSTED = frozenset({("anagram",), ("hidden_word",), ("hidden_word", "reversal"), ("deletion",)})
#: The readings whose core type (see core()) is written where the full type
#: is not trusted: each read at least 100 times in the held-out clues and its
#: core at least 97% the core of the blog's type there. How a block was taken
#: from its words is where the letters and the blogs disagree, so the type is
#: written without it and marked "typeCore": the clue is at least this, and
#: may be this plus a selection or cut ("container" may be "container + letter_selection").
CORE_TRUSTED = frozenset({("container",), ("charade", "container"), ("reversal",), ("anagram", "deletion"),
                          ("container", "letter_selection"), ("charade", "deletion")})
MIN_CORE_CLAIMS = 100
PRECISION_BAR = 0.97
#: The most blocks put together; more is a blog listing alternatives.
MAX_BLOCKS = 5


def texts(inds):
    """The clue words of indicator objects: each one's `text`."""
    return [i["text"] for i in inds or ()]


def words(body):
    """The clue's words as (text, letters), punctuation dropped."""
    return [(m.group(), letters(m.group())) for m in WORD.finditer(body) if letters(m.group())]


def locate(phrase, ws):
    """The word indices of the first run of `ws` that is `phrase`, or None."""
    target = [letters(w) for w in WORD.findall(phrase) if letters(w)]
    n = len(target)
    for i in range(len(ws) - n + 1):
        if n and [w[1] for w in ws[i:i + n]] == target:
            return set(range(i, i + n))
    return None


def type_name(parts):
    """The type a set of parts makes, as a tuple in PART_ORDER, or None."""
    return tuple(p for p in PART_ORDER if p in parts) or None


def show(t):
    return " + ".join(t) if isinstance(t, (list, tuple)) else str(t)


# ------------------------------------------------------------ blocks

def cut(w, bl):
    """Whether `bl` is `w` with one run of at most MAX_CUT letters taken out."""
    return 0 < len(w) - len(bl) <= MAX_CUT and any(
        w[:i] + w[i + len(w) - len(bl):] == bl for i in range(len(bl) + 1))


def listed(bl, src):
    """Whether ABBREVIATIONS gives the letters `bl` for the clue words `src`."""
    return bl.lower() in ABBR and src.lower().strip() in ABBR[bl.lower()]


def derivation(bl, src):
    """The parts a block's letters say it was taken from its clue words by:
    set() for a synonym, literal or listed abbreviation, {'letter_selection'}
    or {'deletion'} for a selection or cut, None when the letters allow two
    (a first letter of one word and the last of another are two).

    D from "Delius' overture" is a first letter, and so is Y from a lone
    "Yokohama" unless ABBREVIATIONS lists it: blogs split on those, and a
    clue typed with a selection is one this does not claim (see TRUSTED)."""
    sw = [letters(w) for w in WORD.findall(src or "") if letters(w)]
    if not sw or bl == "".join(sw) or listed(bl, src):
        return set()
    if len(sw) == 1 and len(bl) == 1:
        return {"letter_selection"} if sw[0][0] == bl and len(sw[0]) > 1 else set()
    cands = set()
    for w in sw:
        if w == bl:
            return set()
        if len(bl) == 1:
            cands |= {"first letter"} if w[0] == bl else set()
            cands |= {"last letter"} if len(w) > 1 and w[-1] == bl else set()
        else:
            if len(w) > 2 and bl == w[0] + w[-1]:
                cands.add("outer letters")
            if len(w) >= 4 and bl in (w[::2], w[1::2]):
                cands.add("alternate letters")
            if cut(w, bl):
                cands.add("deletion")
    for i in range(len(sw) - len(bl)):
        run = sw[i:i + len(bl)]
        if len(bl) > 1 and "".join(w[0] for w in run) == bl:
            cands.add("first letters")
        if len(bl) > 1 and "".join(w[-1] for w in run) == bl:
            cands.add("last letters")
    return {"deletion" if c == "deletion" else "letter_selection" for c in cands} if len(cands) <= 1 else None


def match(seg, piece):
    """How `piece` gives the letters `seg`: as itself, reversed or anagrammed."""
    if seg == piece:
        return frozenset()
    if seg == piece[::-1]:
        return frozenset({"reversal"})
    if len(piece) >= 3 and sorted(seg) == sorted(piece):
        return frozenset({"anagram"})
    return None


def parses(answer, pieces, fodder=None):
    """Every set of parts by which all of `pieces` spell `answer`: each piece
    in one stretch, or around the pieces inside it (a container), each
    literal, reversed or anagrammed; two or more side by side are a charade."""
    everything = frozenset(range(len(pieces)))
    mark = lambda m, i: m | {BLOCK_ANAGRAM} if m and "anagram" in m and i != fodder else m

    @functools.cache
    def fill(lo, hi, avail):
        if lo == hi:
            return {(frozenset(), frozenset(), 0)}
        out = set()
        for i in avail:
            s, n, rest = pieces[i], len(pieces[i]), avail - {i}
            if lo + n <= hi and (m := mark(match(answer[lo:lo + n], s), i)) is not None:
                out |= {(u | {i}, p | m, k + 1) for u, p, k in fill(lo + n, hi, rest)}
            for a in range(1, n):
                for mid in range(lo + a + 1, hi - (n - a) + 1):
                    m = mark(match(answer[lo:lo + a] + answer[mid:mid + n - a], s), i)
                    if m is None:
                        continue
                    for u1, p1, k1 in fill(lo + a, mid, rest):
                        if not u1:
                            continue
                        inner = p1 | m | {"container"} | ({"charade"} if k1 > 1 else set())
                        out |= {(u1 | u2 | {i}, inner | p2, k2 + 1)
                                for u2, p2, k2 in fill(mid + n - a, hi, rest - u1)}
        return out

    if sum(map(len, pieces)) != len(answer):
        return set()
    return {p | ({"charade"} if k > 1 else set())
            for u, p, k in fill(0, len(answer), everything) if u == everything}


def deleted(pieces, depth=2):
    """`pieces` with up to `depth` of them taken out of another as one run:
    (pieces, parts) for each way, the untouched set first."""
    out = [(tuple(pieces), frozenset())]
    if depth:
        for i, j in itertools.permutations(range(len(pieces)), 2):
            y, d = pieces[i], pieces[j]
            k = y.find(d)
            while k >= 0 and len(y) > len(d):
                rest = [p for n, p in enumerate(pieces) if n not in (i, j)] + [y[:k] + y[k + len(d):]]
                out += [(ps, parts | {"deletion"}) for ps, parts in deleted(rest, depth - 1)]
                k = y.find(d, k + 1)
    return out


# ------------------------------------------------------------ inference

def hidden(answer, ws, free):
    """(fodder word indices, reversed?) for each place the answer, or its
    reversal, is spelt inside a stretch of free words other than as whole words."""
    found = set()
    i = 0
    while i < len(ws):
        if i not in free:
            i += 1
            continue
        j = i
        while j + 1 < len(ws) and j + 1 in free:
            j += 1
        run = "".join(ws[k][1] for k in range(i, j + 1))
        starts, at = [], 0
        for k in range(i, j + 1):
            starts.append(at)
            at += len(ws[k][1])
        for target, rev in ((answer, False), (answer[::-1], True)):
            k = run.find(target)
            while k >= 0:
                end = k + len(target)
                first = max(n for n, s in enumerate(starts) if s <= k)
                last = max(n for n, s in enumerate(starts) if s < end)
                whole = k == starts[first] and end == (starts[last + 1] if last + 1 < len(starts) else len(run))
                if not whole:
                    found.add((tuple(range(i + first, i + last + 1)), rev))
                k = run.find(target, k + 1)
        i = j + 1
    return sorted(found)


def free_runs(ws, free):
    for i in range(len(ws)):
        for j in range(i, len(ws)):
            if j not in free:
                break
            yield tuple(range(i, j + 1)), "".join(ws[k][1] for k in range(i, j + 1))


def readings(answer, ws, free, blocks):
    """(type tuple, fodder word indices, why, cost) for every way the letters allow."""
    out = []
    if not blocks and len(answer) >= MIN_HIDDEN:
        for run, rev in hidden(answer, ws, free):
            out.append((("hidden_word", "reversal") if rev else ("hidden_word",), run,
                        f"{'reversed ' if rev else ''}{answer} is spelt in {' '.join(ws[k][0] for k in run)!r}", 1))
    derived = set()
    for bl, src in blocks:
        d = derivation(bl, src)
        if d is None:
            return [(("undecided block",), (), f"{bl} from {src!r} is more than one selection", 0)]
        derived |= d
    need = collections.Counter(answer)
    for pieces, parts in deleted([b for b, *_ in blocks]) if len(blocks) <= MAX_BLOCKS else ():
        gap = len(answer) - sum(map(len, pieces))
        runs = [((), "")] if gap == 0 else [
            (r, s) for r, s in free_runs(ws, free) if len(s) == gap
            and collections.Counter(s) + collections.Counter("".join(pieces)) == need]
        for run, fod in runs:
            if fod and len(fod) < 3 and fod != answer[::-1] and fod not in answer:
                continue
            got = parses(answer, list(pieces) + ([fod] if fod else []), len(pieces) if fod else None)
            src = f"{' '.join(ws[k][0] for k in run)!r}" if run else ""
            what = " + ".join(filter(None, [src, "+".join(b for b, *_ in blocks)]))
            if not got and len(pieces) + bool(fod) > 1 and collections.Counter(fod + "".join(pieces)) == need:
                got = {frozenset({"anagram"})}
            for p in got:
                if p | parts | derived:
                    out.append((type_name(p | parts | derived), run, f"{what} make {answer}", cost(p)))
    if blocks and not out and len(answer) >= MIN_ANAGRAM:
        extra = collections.Counter("".join(b for b, *_ in blocks))
        for run, s in free_runs(ws, free):
            c = collections.Counter(s)
            if len(s) > len(answer) and c - extra == need and extra - c == collections.Counter():
                out.append((("subtractive anagram",), run, f"{' '.join(ws[k][0] for k in run)!r} less the blocks has the letters of {answer}", 1))
    return [r for r in out if not (r[0] == ("anagram",) and len(answer) < MIN_ANAGRAM)]


def infer(clue, answer, known, lexicon=None):
    """What the letters say about one clue: {type, fodder, indicators, why}, or
    {undecided: [readings]} when they allow more than one, or None."""
    answer = letters(answer or "")
    ws = words(clue_body(clue))
    if len(answer) < 3 or not ws or SPOONER.search(clue):
        return None
    taken = set()
    for d in known.get("definition", []):
        taken |= locate(d, ws) or set()
    blocks = []
    for bl, src, *op in known.get("blocks", []):
        if op:
            continue  # anagram fodder: its words stay free, where readings finds fodder itself
        taken |= locate(src, ws) or set()
        blocks.append((letters(bl), src))
    free = set(range(len(ws))) - taken
    rs = readings(answer, ws, free, [b for b in blocks if b[0]])
    if not rs:
        return None
    least = min(r[3] for r in rs)
    rs = [r for r in rs if r[3] == least]
    types = {r[0] for r in rs}
    if types == set(HIDDEN):  # spelt both ways ("top position" OPPO): reading it forward takes no reversal
        rs = [r for r in rs if r[0] == ("hidden_word",)]
        types = {("hidden_word",)}
    if len(types) > 1 or types & {("undecided block",), ("subtractive anagram",)}:
        return {"undecided": sorted({(show(t), " ".join(ws[k][0] for k in run)) for t, run, *_ in rs}),
                "why": rs[0][2]}
    t = rs[0][0]
    out = {"type": list(t), "why": rs[0][2]}
    runs = {r[1] for r in rs}
    if len(runs) == 1 and rs[0][1]:
        run = rs[0][1]
        out["fodder"] = " ".join(ws[k][0] for k in run)
    else:
        run = ()
    if lexicon is not None:
        ind = indicators(ws, free - set(run), set(run), t, lexicon)
        if ind:
            out["indicators"] = ind
    return out


def indicators(ws, free, fodder, t, lexicon):
    """Free clue phrases blogs name as an indicator of one of the parts of `t`,
    next to the fodder when there is fodder, longest first, not overlapping."""
    parts = set(t)
    near = set()
    for k in fodder:
        near |= {k - 3, k - 2, k - 1, k + 1, k + 2, k + 3}
    out, used = [], set()
    for n in (3, 2, 1):
        for i in range(len(ws) - n + 1):
            span = set(range(i, i + n))
            if not span <= free or span & used or (fodder and not span & near):
                continue
            phrase = vote_key(" ".join(w[0] for w in ws[i:i + n]))
            votes = lexicon.get(phrase)
            if votes and sum(votes[p] for p in parts) >= MIN_INDICATOR \
                    and max(votes, key=votes.get) in parts:
                out.append((i, " ".join(w[0] for w in ws[i:i + n])))
                used |= span
    return [p for _, p in sorted(out)]


# ------------------------------------------------------------ lexicon blocks

#: The most clue words one block is read from.
MAX_RUN = 4
#: A reading of some clue words is one blogs gave at least this many times,
MIN_SEEN = 3
#: in at least this share of the clues those words stand in: "and" is D in
#: a few write-ups and a link word in thousands.
MIN_RATE = 0.005
#: A word left over beside an inferred block may be outside it only where
#: blogs, with it on that side of a block, leave it out at least MIN_APART
#: times and put it at the block's edge at most MAX_ATTACH of the time: they
#: write "Chinese dynasty" for MING, and "dynasty" alone is a guess at the span.
MIN_APART = 5
MAX_ATTACH = 0.05
#: Or, where the block read with it spells nothing blogs or the write-up
#: give those letters for, where it is at the edge of at most this share of
#: the blocks it stands beside, seen beside at least MIN_EDGE_SEEN.
EDGE_SHARE = 0.2
MIN_EDGE_SEEN = 20
#: More partial splits than this over one stretch of the answer is a clue
#: the letters cannot decide.
MAX_SPLITS = 200
#: Types whose letters are not a sequence of blocks, so a split found in them is chance.
NO_SPLIT = ("anagram", "hidden_word", "homophone", "spoonerism", "double_definition", "cryptic_definition")
POSSESSIVE = re.compile(r"[a-z]['’]s$", re.IGNORECASE)


ABBR_OF = collections.defaultdict(set)
for _l, _ws in ABBR.items():
    for _w in _ws:
        ABBR_OF[_key(_w)].add(_l.upper())


class Lexicon:
    """What blogs read clue words as, from the blocks they gave; with
    `extra`, what our annotations read them as too, which only
    export_lexicons publishes: inference reads the blogs' alone, as ours
    cost infer_blocks precision.

    `seen`: clue words (their letters, word by word) -> {letters: blocks}.
    `uses`: clue words -> clues they stand in. `edge`: (side, word) ->
    [blocks whose words end with it on that side, blocks it stood beside
    on that side and was left out of] (see MAX_ATTACH)."""

    def __init__(self, corpus, skip=frozenset(), extra=()):
        self.seen, self.edge, keys = self._count(itertools.chain(corpus, extra), skip)
        self.uses = self._uses(keys, self.seen)

    @staticmethod
    def _uses(keys, seen):
        uses = collections.Counter()
        for ks in keys:
            uses.update({ks[i:i + n] for i in range(len(ks)) for n in range(1, MAX_RUN + 1)
                         if i + n <= len(ks) and ks[i:i + n] in seen})
        return uses

    @staticmethod
    def _count(corpus, skip=frozenset()):
        seen = collections.defaultdict(collections.Counter)
        edge = collections.defaultdict(lambda: [0, 0])
        keys = []
        for pid, eid, clue, answer, facts in corpus:
            if pid in skip:
                continue
            ws = words(clue_body(clue))
            keys.append(tuple(sys.intern(l) for _, l in ws))
            spans = []
            for bl, src, *op in facts.get("blocks", ()):
                if op:
                    continue
                k, b = _key(src), letters(bl)
                if b and 0 < len(k) <= MAX_RUN:
                    seen[k][b] += 1
                spans.append(sorted(locate(src, ws) or ()))
            covered = {k for sp in spans for k in sp}
            for d in facts.get("definition", []):
                covered |= locate(d, ws) or set()
            for sp in filter(None, spans):
                for side, inner, outer in (("L", sp[0], sp[0] - 1), ("R", sp[-1], sp[-1] + 1)):
                    if len(sp) > 1:
                        edge[side, ws[inner][1]][0] += 1
                    if 0 <= outer < len(ws) and outer not in covered:
                        edge[side, ws[outer][1]][1] += 1
        return dict(seen), dict(edge), keys

    def spellings(self, key):
        """The letters blogs read these clue words as, often enough, and any
        listed abbreviation of them."""
        least = max(MIN_SEEN, MIN_RATE * self.uses.get(key, 0))
        return {b for b, n in self.seen.get(key, {}).items() if n >= least} | ABBR_OF.get(key, set())

    def apart(self, side, word):
        """Whether blogs leave `word` out of a block it stands on `side` of."""
        joined, apart = self.edge.get((side, word), (0, 0))
        return apart >= MIN_APART and joined <= MAX_ATTACH * (joined + apart)

    def seldom_in(self, side, word):
        """Whether blogs, with `word` on `side` of a block, leave it out often
        and take it in seldom (EDGE_SHARE): "in" ends 8% of the blocks it
        stands beside, so it is outside one where the words with it read as nothing."""
        joined, apart = self.edge.get((side, word), (0, 0))
        return apart >= MIN_EDGE_SEEN and joined <= EDGE_SHARE * (joined + apart)

    def attached(self, side, word):
        """Whether blogs take `word` into a block it ends on `side` of: "first" in "first shower"."""
        joined, apart = self.edge.get((side, word), (0, 0))
        return joined >= MIN_APART and apart <= MAX_ATTACH * (joined + apart)


class _TooMany(Exception):
    pass


#: The most pieces of fodder anagrammed together.
MAX_FODDER = 3


def splits(answer, pieces):
    """Every set of `pieces`, [(letters, word mask, anagrammed?)], that spells
    `answer` with no piece twice and no word in two: in a sequence of units,
    a unit a piece, a piece reversed, a piece around a sequence, or anagram
    fodder in any order, up to MAX_FODDER pieces of it together where no two
    stand side by side in the clue ("arena with band" for NAAN BREAD)."""
    n = len(answer)
    unit = collections.defaultdict(list)
    around = collections.defaultdict(list)
    fodder = [x for x, p in enumerate(pieces) if p[2]]
    for k in range(2, MAX_FODDER + 1):  # fodder in several pieces is anagrammed as one
        for combo in itertools.combinations(fodder, k):
            masks = [pieces[x][1] for x in combo]
            if any(a & b or a << 1 & b or b << 1 & a for a, b in itertools.combinations(masks, 2)):
                continue  # overlapping, or side by side, where fodder is one piece
            bl = sorted("".join(pieces[x][0] for x in combo))
            for i in range(n - len(bl) + 1):
                if sorted(answer[i:i + len(bl)]) == bl:
                    unit[i, i + len(bl)].append((sum(masks), frozenset(combo)))
    for x, (bl, mask, anagrammed) in enumerate(pieces):
        size = len(bl)
        if anagrammed:
            for i in range(n - size + 1):
                if sorted(answer[i:i + size]) == sorted(bl):
                    unit[i, i + size].append((mask, frozenset([x])))
            continue
        for s in {bl, bl[::-1]}:
            i = answer.find(s)
            while i >= 0:
                unit[i, i + size].append((mask, frozenset([x])))
                i = answer.find(s, i + 1)
        for a in range(1, size):
            head, tail = bl[:a], bl[a:]
            i = answer.find(head)
            while i >= 0:
                m = answer.find(tail, i + a + 1)
                while m >= 0:
                    around[i, m + len(tail)].append((x, mask, i + a, m))
                    m = answer.find(tail, m + 1)
                i = answer.find(head, i + 1)

    @functools.cache
    def units(i, j):
        out = list(unit.get((i, j), ()))
        for x, mask, k, m in around.get((i, j), ()):
            out += [(mask | m2, p | {x}) for m2, p in seq(k, m) if not mask & m2 and x not in p]
        return out

    @functools.cache
    def seq(i, j):
        out = set(units(i, j))
        for k in range(i + 1, j):
            head = units(i, k)
            if head:
                out |= {(m1 | m2, p1 | p2) for m2, p2 in seq(k, j) for m1, p1 in head
                        if not m1 & m2 and not p1 & p2}
        if len(out) > MAX_SPLITS:
            raise _TooMany
        return tuple(out)

    return {p for _, p in seq(0, n)} if n else set()


def infer_blocks(clue, answer, facts, lex):
    """The blocks a blog left out, where the answer splits one way only into
    the blocks it gave and runs of the other clue words, each run read as
    blogs read those words elsewhere (`lex`): [(letters, clue words)] to add,
    [] when nothing is missing or no split is found, None when the split is
    not the only one."""
    answer = letters(answer or "")
    t = facts.get("type") or ()
    given = facts.get("blocks") or []
    if len(answer) < 2 or any(x in t for x in NO_SPLIT) and not any(op for _, _, *op in given):
        return []
    ws = words(clue_body(clue))
    bare = [(w[:-2], l[:-1]) if POSSESSIVE.search(w) else (w, l) for w, l in ws]
    taken = set()
    for phrase in facts.get("definition", []) + texts(facts.get("indicators")):
        taken |= locate(phrase, ws) or set()
    pieces, runs = [], []
    for bl, src, *op in given:
        span = locate(src, ws) or set()
        taken |= span
        pieces.append((letters(bl), sum(1 << k for k in span), bool(op)))
    if sorted("".join(p[0] for p in pieces)) == sorted(answer):
        return []
    have = len(pieces)
    free = set(range(len(ws))) - taken
    need = collections.Counter(answer)
    for i in range(len(ws)):
        for size in range(1, MAX_RUN + 1):
            if i + size > len(ws) or i + size - 1 not in free:
                break
            key = tuple(l for _, l in ws[i:i + size])
            # "son’s" is S as "son" is, and blogs write whichever they write more
            short = key[:-1] + (bare[i + size - 1][1],)
            whole, part = lex.spellings(key), lex.spellings(short) if short != key else set()
            for s in whole | part:
                cut = s in part and lex.seen.get(short, {}).get(s, 0) > lex.seen.get(key, {}).get(s, 0)
                if len(s) < len(answer) and not collections.Counter(s) - need:
                    pieces.append((s, sum(1 << k for k in range(i, i + size)), False))
                    runs.append((i, size, cut))
    try:
        got = splits(answer, pieces)
    except _TooMany:
        return None
    everything = frozenset(range(have))
    new = {p - everything for p in got if p >= everything and len(p) >= 2 and p - everything}
    if len(new) != 1:
        return None if new else []
    new = sorted(x - have for x in new.pop())
    used = taken | {k for x in new for k in range(runs[x][0], runs[x][0] + runs[x][1])}
    out = []
    for x in new:
        i, size, cut = runs[x]
        j = i + size
        if i > 0 and i - 1 not in used and not lex.apart("L", ws[i - 1][1]) \
                or j < len(ws) and j not in used and not lex.apart("R", ws[j][1]):
            return None
        out.append((pieces[have + x][0], " ".join([w for w, _ in ws[i:j - 1]] + [(bare if cut else ws)[j - 1][0]])))
    return out


# ------------------------------------------------------------ blocks from the write-up's prose

def verified(c, src, key, lex, dlex, printed=frozenset(), own=None):
    """Whether the clue words `src` (letters `key`) give the letters `c` by
    what the letters or the blogs say: literally, as a listed abbreviation,
    a selection or cut of the one word, a reading blogs gave them as a block, or an
    answer blogs underlined them for; or as one of those two with its first
    or last letter cut (FATHE(r) from "old man"), unless the write-up
    prints that word whole (`printed`): T(OG)ETHER is TETHER around OG, and
    not T and a cut TETHER. One or two letters are what blogs read them as
    often enough (Lexicon.spellings): "close to" is R in three write-ups.
    An answer `own` is left out of those blogs underlined them for."""
    if c == "".join(key) or listed(c, src) or len(key) == 1 and derivation(c, src):
        return True
    if len(c) < 3:  # one or two letters blogs give in passing: as often as infer_blocks reads them
        return c in lex.spellings(key)
    whole = set(lex.seen.get(key, ())) | dlex.by_words.get(key, set())
    whole.discard(own)
    return c in whole or any(c in (w[1:], w[:-1]) and w not in printed for w in whole)


def infer_fuzzy_blocks(clue, answer, facts, lex, dlex, said, sources=None, why=None):
    """The blocks of a clue whose write-up says them in prose ("GAFFE or
    error", "a synonym for 'misrepresent' followed by Female"): the one split
    of the answer into the blocks the blog gave and pieces of the other clue
    words, as infer_blocks, where each new piece is one the write-up leads to
    (`said`, see blog_facts.leads): a capital block it prints, from clue words
    that give those letters (see verified) or, where none do, that it prints
    next to them; anagram fodder, where it names an anagram; or a reading
    blogs give those words as a block, of words it prints. [(letters, clue
    words, *how)] to add, [] when nothing is missing or none is found, None
    when the split is not the only one. `sources`, a list, is given what led
    to each: "caps verified", "caps near", "lexicon caps", "lexicon printed"
    or "anagram". `why`, a list, is given the reason for a [] or None:
    "no split", "two splits", "too many splits", "edge" (a word beside a
    new piece that blogs do not leave out) or "own answer" (a piece read
    only as the answer less a letter, where the blog underlined nothing)."""
    note = lambda r, v: (why.append(r) if why is not None else None) or v
    answer = letters(answer or "")
    t = facts.get("type") or ()
    given = facts.get("blocks") or []
    if len(answer) < 2 or not said or any(x in t for x in NO_SPLIT if x != "anagram"):
        return []
    ws = words(clue_body(clue))
    bare = [(w[:-2], l[:-1]) if POSSESSIVE.search(w) else (w, l) for w, l in ws]
    taken = set()
    for phrase in facts.get("definition", []) + texts(facts.get("indicators")):
        taken |= locate(phrase, ws) or set()
    pieces, runs, seen = [], [], set()
    for bl, src, *op in given:
        span = locate(src, ws) or set()
        taken |= span
        pieces.append((letters(bl), sum(1 << k for k in span), bool(op)))
        seen.add(pieces[-1])
    if sorted("".join(p[0] for p in pieces)) == sorted(answer):
        return []
    have = len(pieces)
    free = set(range(len(ws))) - taken
    need = collections.Counter(answer)
    capset = set(said.get("caps", ()))
    caps = sorted(c for c in capset if not collections.Counter(c) - need)
    near = collections.defaultdict(set)
    for c, phrase in said.get("near", ()):
        near[c].add(_key(phrase))
    printed, phrases = set(), {_key(p) for p in said.get("printed", ())}
    for k in phrases:
        printed |= {k[a:z] for a in range(len(k)) for z in range(a + 1, len(k) + 1)}

    tags = []

    def add(s, i, size, cut, how, anagram=False, tag=""):
        mask = sum(1 << k for k in range(i, i + size))
        if (s, mask, anagram) not in seen:
            seen.add((s, mask, anagram))
            pieces.append((s, mask, anagram))
            runs.append((i, size, cut, how))
            tags.append(tag)

    found, selections = collections.defaultdict(list), set()
    for i in range(len(ws)):
        for size in range(1, MAX_RUN + 1):
            if i + size > len(ws) or i + size - 1 not in free:
                break
            key = tuple(l for _, l in ws[i:i + size])
            src = " ".join(w for w, _ in ws[i:i + size])
            short = key[:-1] + (bare[i + size - 1][1],)
            whole, part = lex.spellings(key), lex.spellings(short) if short != key else set()
            for s in whole | part:
                cut_ = s in part and lex.seen.get(short, {}).get(s, 0) > lex.seen.get(key, {}).get(s, 0)
                if len(s) < len(answer) and not collections.Counter(s) - need:
                    add(s, i, size, cut_, "lead" if s in caps or key in printed else "lexicon",
                        tag="lexicon caps" if s in caps else "lexicon printed")
            if size == 1 and said.get("letter") and key in printed and len(key[0]) > 1:
                for c in {key[0][0], key[0][-1]} - lex.spellings(key):
                    if not listed(c, src) and c in need:
                        selections.add((c, 1 << i))
                        found[c].append((i, 1, False))
            for c in caps:
                if size == 1 and c != key[0] and not listed(c, src) and derivation(c, src) \
                        and c not in lex.spellings(key):
                    selections.add((c, sum(1 << k for k in range(i, i + size))))
                if verified(c, src, key, lex, dlex, capset):
                    b = bare[i + size - 1]
                    own = b[1] != key[-1] and verified(c, " ".join([w for w, _ in ws[i:i + size - 1]] + [b[0]]), short, lex, dlex, capset)
                    found[c].append((i, size, own))
            for fod, own in {("".join(key), False), ("".join(short), True)}:
                # fodder where the write-up names an anagram, or prints the
                # clue words in capitals as letters the answer holds neither
                # in a row nor reversed
                if (said.get("anagram") or fod in capset and fod not in answer and fod[::-1] not in answer) \
                        and len(fod) >= MIN_ANAGRAM \
                        and fod != answer and not collections.Counter(fod) - need:
                    add(fod, i, size, own and short != key, "lead", anagram=True, tag="anagram")
    caps += sorted(set(found) - set(caps))  # a letter the write-up says is taken from a word it prints
    for c in caps:  # a letter taken from one word, and the words beside it blogs take in with it
        for i, size, own in list(found[c]):
            if (c, 1 << i) in selections:
                for a, z, side, k in ((i - 1, i + 1, "L", i - 1), (i - 2, i + 1, "L", i - 2),
                                      (i, i + 2, "R", i + 1), (i, i + 3, "R", i + 2)):
                    if 0 <= a and z <= len(ws) and set(range(a, z)) <= free and lex.attached(side, ws[k][1]):
                        found[c].append((a, z - a, False))
    for c in caps:
        tag = "caps verified" if found[c] else "caps near"
        at = found[c] or [(i, size) for i in range(len(ws)) for size in range(1, MAX_RUN + 1)
                          if len(c) >= 3 and tuple(l for _, l in ws[i:i + size]) in near[c]
                          and len("".join(l for _, l in ws[i:i + size])) >= 3
                          and set(range(i, i + size)) <= free]
        for i, size, *own in at:
            add(c, i, size, bool(own and own[0]), "lead", tag=tag)
    drop = narrowest(pieces[have:], ws, lex, phrases)
    use = [k for k in range(len(pieces)) if k < have or k - have not in drop]
    try:
        got = {frozenset(use[x] for x in p) for p in splits(answer, [pieces[k] for k in use])}
    except _TooMany:
        return note("too many splits", None)
    everything = frozenset(range(have))
    new = {p - everything for p in got if p >= everything and p - everything
           and (len(p) >= 2 or pieces[min(p)][2])}  # one piece is the whole answer anagrammed
    new = {p for p in new if all(runs[x - have][3] == "lead" for x in p)}
    if len(new) > 1:  # fodder read as one piece, where it is, over the same letters from several
        new = {p for p in new if sum(pieces[x][2] for x in p) < 2} or new
    if len(new) != 1:
        return note("two splits", None) if new else note("no split", [])
    new = sorted(x - have for x in new.pop())
    for x in new if not facts.get("definition") else ():
        # a piece read only as this answer less a letter (LUMBAGO from "Lead"
        # for PLUMBAGO) is the definition the blog left out, not a block
        i, size, cut_, _ = runs[x]
        src = " ".join([w for w, _ in ws[i:i + size - 1]] + [(bare if cut_ else ws)[i + size - 1][0]])
        s, key = pieces[have + x][0], _key(src)
        if tags[x] == "caps verified" and verified(s, src, key, lex, dlex, capset) \
                and not verified(s, src, key, lex, dlex, capset, own=answer):
            return note("own answer", None)
    used = taken | {k for x in new for k in range(runs[x][0], runs[x][0] + runs[x][1])}
    out = []
    for x in new:
        i, size, cut_, _ = runs[x]
        j = i + size
        # a letter taken from a word: blogs write "first of ewes" as often as "ewes"
        reach = 2 if pieces[have + x][:2] in selections else 1
        for side, ks in (("L", range(i - 1, i - 1 - reach, -1)), ("R", range(j, j + reach))):
            for k in ks:
                if not 0 <= k < len(ws) or k in used:
                    break
                # or, for a piece whose words were checked, seldom in one and
                # with it, reading as nothing the blogs or the write-up give
                a, z = (k, j) if side == "L" else (i, k + 1)
                wider, s = tuple(l for _, l in ws[a:z]), pieces[have + x][0]
                if not lex.apart(side, ws[k][1]) and not (
                        tags[x] != "caps near" and lex.seldom_in(side, ws[k][1])
                        and wider not in phrases and wider not in near[s]
                        and not verified(s, " ".join(w for w, _ in ws[a:z]), wider, lex, dlex, capset)):
                    return note("edge", None)
        src = " ".join([w for w, _ in ws[i:j - 1]] + [(bare if cut_ else ws)[j - 1][0]])
        out.append((pieces[have + x][0], src, "anagrammed") if pieces[have + x][2] else (pieces[have + x][0], src))
        if sources is not None:
            sources.append(tags[x])
    return out


def narrowest(pieces, ws, lex, phrases=frozenset()):
    """The indices of `pieces`, [(letters, word mask, anagrammed?)], another
    beats on where it ends: the same letters from a run of words and from
    that run and the words beside it, "beer" and "tucked into beer", are
    the one the write-up prints as a phrase of its own (`phrases`, clue
    words' letters), else the shorter where blogs leave out the word next to
    it, else the longer where they take the outer word into a block on that
    side, else both stand."""
    drop = set()
    for x, y in itertools.permutations(range(len(pieces)), 2):
        (sx, mx, fx), (sy, my, fy) = pieces[x], pieces[y]
        if sx != sy or fx != fy or mx & my != mx or mx == my:
            continue
        span = [k for k in range(len(ws)) if mx >> k & 1]
        extra = [k for k in range(len(ws)) if (my & ~mx) >> k & 1]
        if extra[-1] < span[0]:
            side, outer, inner = "L", extra[0], extra[-1]
        elif extra[0] > span[-1]:
            side, outer, inner = "R", extra[-1], extra[0]
        else:
            continue
        kx = tuple(ws[k][1] for k in span)
        ky = tuple(ws[k][1] for k in sorted(span + extra))
        if ky in phrases:
            drop.add(x)
        elif kx in phrases or lex.apart(side, ws[inner][1]):
            drop.add(y)
        elif lex.attached(side, ws[outer][1]):
            drop.add(x)
    return drop


# ------------------------------------------------------------ lexicon indicators

#: The parts a clue's own words must signal. A charade's pieces sit side by
#: side, and a letter selection is read with its block's words ("Delius' overture").
SIGNALLED = frozenset({"anagram", "container", "reversal", "deletion", "letter_selection"})
#: What blog types name an indicator for, as the parts SIGNALLED is drawn from.
IND_PARTS = SIGNALLED | {"hidden_word", "homophone", "spoonerism"}
#: The parts the indicator lexicon counts: a charade's too, where blogs name
#: "after" and "supporting".
VOTED_PARTS = IND_PARTS | {"charade"}
#: The most clue words one indicator is.
MAX_IND = 4
#: A phrase is read as an indicator of a part where blogs named it one at
#: least MIN_INDICATOR times, this share of them for that part, and this share
#: of the times it was left over.
MIN_SHARE = 0.5
MIN_LEFT = 0.3
#: With no phrase named MIN_LEFT of the times, one named this share is read
#: where it is the only one: "in" (19%), and not "is" (0.2%).
MIN_LEFT_ALONE = 0.1
#: A word left over in at least this many write-ups, and named less than
#: MIN_LEFT of them, is a link word; any other word left over beside the
#: indicators read is one this does not account for.
MIN_LINK_SEEN = 20
#: Where blogs name a run or a shorter run of it, the one named this share of the times.
BOUNDARY = 0.9


def wordplay(answer, blocks):
    """The parts by which `blocks`, [letters, clue words, *how], put together
    make `answer`, where the least costly reading is the only one; else None."""
    answer = letters(answer or "")
    if not blocks or len(blocks) > MAX_BLOCKS:
        return None
    fod = [k for k, b in enumerate(blocks) if "anagrammed" in b[2:]]
    derived = set()
    for k, (bl, src, *_) in enumerate(blocks):
        if k not in fod:
            d = derivation(letters(bl), src)
            if d is None:
                return None
            derived |= d
    pieces = [letters(b[0]) for k, b in enumerate(blocks) if k not in fod]
    if fod:  # fodder in several pieces is anagrammed as one
        pieces.append("".join(letters(blocks[k][0]) for k in fod))
    got = parses(answer, pieces, len(pieces) - 1 if fod else None)
    if not got:
        return None
    least = min(map(cost, got))
    reads = {p - {BLOCK_ANAGRAM} for p in got if cost(p) == least}
    if len(reads) != 1:
        return None
    return reads.pop() | derived | ({"anagram"} if fod else set())


def needed(answer, blocks, t=""):
    """The parts (SIGNALLED) that `blocks` spelling `answer` want an indicator
    for in the clue words outside them, or None where the wordplay is not
    the only one: a letter taken from one word ("F" from "Found") wants its
    own, where "Delius' overture" holds it. A hidden word (see carried)
    wants one for the hiding, and one for the reversal where spelt backwards;
    a homophone's or a spoonerism's (type `t`) heard block (see sounds_like)
    one for that."""
    if sounds_like(answer, blocks):
        return {"spoonerism" if "spoonerism" in (t or ()) else "homophone"}
    how = carried(answer, blocks)
    if how:
        return {"hidden_word", "reversal"} if how == "reversed" else {"hidden_word"}
    ops = wordplay(answer, blocks)
    if ops is None:
        return None
    need = set(ops & SIGNALLED) - {"deletion"}
    for bl, src, *how in blocks:
        bl, sw = letters(bl), [l for _, l in words(src)]
        if "anagrammed" in how or len(sw) != 1 or bl == sw[0] or listed(bl, src):
            continue
        rest = iter(sw[0])
        if all(c in rest for c in bl):  # its letters, in order, out of the one word
            need.add("deletion" if cut(sw[0], bl) else "letter_selection")
    return need


def spans(clue):
    """The clue's words as (text, letters) and each one's (start, end) in the clue body."""
    body = clue_body(clue)
    ms = [m for m in WORD.finditer(body) if letters(m.group())]
    return body, [(m.group(), letters(m.group())) for m in ms], [m.span() for m in ms]


class _Less(dict):
    """A read-only view of counts `base` less `delta`: a Counter less a
    Counter, a [count, count] less a [count, count], key by key."""

    def __init__(self, base, delta):
        super().__init__()
        self.base, self.delta = base, delta

    def get(self, k, d=None):
        v = self.base.get(k)
        if v is None or k not in self.delta:
            return d if v is None else v
        if isinstance(v, collections.Counter):
            return v - self.delta[k]
        return [a - b for a, b in zip(v, self.delta[k])]


class Indicators:
    """The indicators blogs stated, keyed to the part they signal.

    `votes`: clue words (their letters, word by word) -> Counter of the parts
    blogs named them an indicator for: each indicator counted under its own
    `for` where that is a part an indicator signals (VOTED_PARTS), and under
    nothing without one. `left`: clue
    words -> [write-ups naming indicators that left them outside the
    definition and blocks, those that named them an indicator]: "to" is left
    over in thousands and an indicator in a few. `inner`: clue words ->
    Counter of the shorter runs of them named where they were left over, so
    "consumed by" left over is named whole or as "consumed". `edge`: (side,
    word) -> [indicators it is the end word of on that side, indicators it
    stood beside on that side, in no other role, and was left out of]."""

    def __init__(self, corpus, skip=frozenset(), extra=()):
        extra = [r for r in extra if r[0] not in skip]
        self.own = {(r[2], r[3]): r for r in extra}
        self.votes, self.left, self.inner, self.edge = self._count(itertools.chain(corpus, extra), skip)
        self.left = {k: v for k, v in self.left.items() if v[1] or v[0] >= MIN_LINK_SEEN and len(k) == 1}

    def less(self, clue, answer):
        """This lexicon without what the `extra` row of this clue added, so a
        clue our annotations explain never confirms itself."""
        row = self.own.get((clue, answer))
        if row is None:
            return self
        view = copy.copy(self)
        for name, delta in zip(("votes", "left", "inner", "edge"), self._count([row])):
            setattr(view, name, _Less(getattr(self, name), delta))
        return view

    @staticmethod
    def _count(corpus, skip=frozenset()):
        votes = collections.defaultdict(collections.Counter)
        left = collections.defaultdict(lambda: [0, 0])
        inner = collections.defaultdict(collections.Counter)
        edge = collections.defaultdict(lambda: [0, 0])
        for pid, eid, clue, answer, facts in corpus:
            if pid in skip or not facts.get("indicators"):
                continue
            named = {_key(i["text"]) for i in facts["indicators"]}
            for i in facts["indicators"]:
                if i.get("for") in VOTED_PARTS:
                    votes[_key(i["text"])][i["for"]] += 1
            if not facts.get("definition"):
                continue
            ws = words(clue_body(clue))
            roles = set()
            for phrase in facts["definition"] + [b[1] for b in facts.get("blocks", ())]:
                roles |= locate(phrase, ws) or set()
            for i in range(len(ws)):
                for n in range(1, MAX_IND + 1):
                    if i + n > len(ws) or i + n - 1 in roles:
                        break
                    key = tuple(sys.intern(l) for _, l in ws[i:i + n])
                    left[key][0] += 1
                    left[key][1] += key in named
                    for a in range(n):
                        for z in range(a + 1, n + 1):
                            if z - a < n and key[a:z] in named:
                                inner[key][a, z] += 1
            inds = [sorted(locate(i["text"], ws) or ()) for i in facts["indicators"]]
            covered = roles | {k for sp in inds for k in sp}
            for sp in filter(None, inds):
                for side, end, out in (("L", sp[0], sp[0] - 1), ("R", sp[-1], sp[-1] + 1)):
                    if len(sp) > 1:
                        edge[side, ws[end][1]][0] += 1
                    if 0 <= out < len(ws) and out not in covered:
                        edge[side, ws[out][1]][1] += 1
        return dict(votes), dict(left), dict(inner), dict(edge)

    def rate(self, key):
        """The share of the write-ups these words were left over in that named them an indicator."""
        seen, named = self.left.get(key, (0, 0))
        return named / seen if seen else 0.0

    def indicates(self, key, part, rate=MIN_LEFT):
        """Whether blogs name these words the indicator of `part`: often
        enough, mostly for it, and at least `rate` of the times they are left over."""
        v = self.votes.get(key)
        return bool(v) and v[part] >= MIN_INDICATOR and v[part] >= MIN_SHARE * sum(v.values()) \
            and self.rate(key) >= rate

    def link(self, word):
        """Whether blogs, with this word left over, seldom name it an indicator: a link word."""
        seen, named = self.left.get((word,), (0, 0))
        return seen >= MIN_LINK_SEEN and named < MIN_LEFT * seen

    def side(self, side, word):
        """Whether blogs leave `word` out of an indicator it stands on `side` of
        (False), take it in (True), or do both (None)."""
        joined, apart = self.edge.get((side, word), (0, 0))
        if apart >= MIN_APART and joined <= MAX_ATTACH * (joined + apart):
            return False
        if joined >= MIN_APART and apart <= MAX_ATTACH * (joined + apart):
            return True
        return None

    def trim(self, key):
        """The run (a, z) of `key` blogs name where all of `key` is left over:
        itself, or a shorter run named at least BOUNDARY of the times one is;
        None if neither, False if blogs have seldom named any."""
        _, whole = self.left.get(key, (0, 0))
        opts = collections.Counter(self.inner.get(key, {}))
        opts[0, len(key)] += whole
        if sum(opts.values()) < MIN_INDICATOR:
            return False
        (a, z), n = opts.most_common(1)[0]
        return (a, z) if n >= BOUNDARY * sum(opts.values()) else None


def infer_indicators(clue, answer, facts, ilex):
    """The indicator a blog left out of a clue whose definition and blocks it
    gave, where the blocks want one (see needed): the one run of the other
    clue words blogs name that part's indicator elsewhere (`ilex`), every
    other word left over a link word, or for a forward hidden word or an
    anagram, where the lexicon reads none, the free words
    themselves (see free_words_indicator). A
    list of indicator objects, {"text": clue phrase} with "for" the part
    read where the clue's type is that one part, [] when none is wanted,
    None when the reading is not the only one.

    Where the blocks want two, blogs name one of them as often as both (74%
    of the phrases read were the blog's, against 98% for one), so those are
    left undecided."""
    if facts.get("indicators") or not facts.get("definition") or coverage(answer, facts) != "full":
        return []
    ilex = ilex.less(clue, answer)
    need = needed(answer, facts["blocks"], facts.get("type"))
    if need is None:
        return None
    if not need:
        return []
    if len(need) > 1:
        return None
    part, = need
    body, ws, at = spans(clue)
    taken = set()
    for phrase in facts["definition"] + [b[1] for b in facts["blocks"]]:
        span = locate(phrase, ws)
        if span is None:
            return None
        taken |= span
    got = _lexicon_indicator(ws, at, body, taken, part, ilex)
    if got is None and part in FREE_WORDS_PARTS:
        got = free_words_indicator(ws, at, body, taken, ilex)
    if got is None:
        return None
    t = {"for": part} if facts.get("type") == [part] else {}
    return [{"text": x, **t} for x in got]


#: The parts whose one indicator, where the lexicon reads none, is the free
#: words (free_words_indicator). Not a container: its blog blocks often take
#: in the containing word, leaving a link word free ("and", "with").
FREE_WORDS_PARTS = frozenset({"hidden_word", "anagram"})


def free_words_indicator(ws, at, body, taken, ilex):
    """The one indicator of a clue with one part to signal: the clue words
    outside its definition and blocks, where they are one run of at most
    MAX_IND, less an end word blogs leave out of indicators on that side
    (Indicators.side) and a closing "'s" (blogs name "criminal" in
    "criminal's"); None where they are not one run or blogs both take in
    and leave out an end word ("captured in" is named with and without "in")."""
    free = [k for k in range(len(ws)) if k not in taken]
    if not free or free[-1] + 1 - free[0] != len(free):
        return None
    i, j = free[0], free[-1] + 1
    while j - i > 1:
        a, z = ilex.side("L", ws[i][1]), ilex.side("R", ws[j - 1][1])
        if a is None or z is None:
            return None
        if a is False:
            i += 1
        elif z is False:
            j -= 1
        else:
            break
    if j - i > MAX_IND:
        return None
    return [re.sub(r"['’]s$", "", body[at[i][0]:at[j - 1][1]])]


def _lexicon_indicator(ws, at, body, taken, part, ilex):
    """The one run of the free clue words blogs name `part`'s indicator, every other a link word; else None."""
    runs = [(i, i + n) for i in range(len(ws)) for n in range(1, MAX_IND + 1)
            if i + n <= len(ws) and not taken & set(range(i, i + n))]
    for rate in (MIN_LEFT, MIN_LEFT_ALONE):  # none read so, one blogs name less often where it is left over
        found = [(i, j) for i, j in runs if ilex.indicates(tuple(l for _, l in ws[i:j]), part, rate)]
        if found:
            break
    # the longest phrase found, the only one not inside another
    best = [s for s in found if not any(o[0] <= s[0] and s[1] <= o[1] and o != s for o in found)]
    if len(best) != 1:
        return None
    span = trimmed(ws, *best[0], taken, ilex)
    if span is None:
        return None
    odd = [ws[k][0] for k in range(len(ws)) if k not in taken and not span[0] <= k < span[1] and not ilex.link(ws[k][1])]
    if odd:
        return None
    return [body[at[span[0]][0]:at[span[1] - 1][1]]]


def trimmed(ws, i, j, taken, ilex):
    """The run of free words blogs name as the indicator read at ws[i:j]:
    as named where the words around it were left over too, and a free word
    beside it no such run takes in left out only where blogs leave it out
    (Indicators.side). None where blogs differ."""
    picks, seen = set(), set()
    for a in range(max(0, j - MAX_IND), i + 1):
        for z in range(j, min(len(ws), a + MAX_IND) + 1):
            if any(k in taken for k in range(a, z)):
                continue
            got = ilex.trim(tuple(l for _, l in ws[a:z]))
            if got is None:
                return None
            if got:
                picks.add((a + got[0], a + got[1]))
                seen |= set(range(a, z))
    for side, k in (("L", i - 1), ("R", j)):
        if 0 <= k < len(ws) and k not in taken | seen and ilex.side(side, ws[k][1]) is not False:
            return None
    if len(picks) > 1:
        return None
    return picks.pop() if picks else (i, j)


def with_indicators(facts, new):
    """`facts` with the inferred indicators `new`, marked so: the blog stated none."""
    return {**facts, "indicators": new, "inferred": sorted({*facts.get("inferred", ()), "indicators"})}


def measure_indicators(corpus, n=1, show=30, seed=1):
    """Precision of infer_indicators on slice `n` of the puzzles, both
    lexicons built without them: the blog's own indicators hidden on the clues
    whose definition and full blocks it gave, and the coverage it adds."""
    test = {pid for pid, *_ in corpus if in_slice(pid, n)}
    lex = Lexicon(corpus, skip=test)
    rows_ = []
    for pid, eid, clue, answer, facts in corpus:
        if pid in test:
            new = infer_blocks(clue, answer, facts, lex)
            rows_.append((pid, eid, clue, answer, with_blocks(facts, new) if new else facts))
    report_indicators(n, rows_, Indicators(corpus, skip=test, extra=annotation_rows()), show, seed)


def report_indicators(n, rows_, ilex, show=30, seed=1):
    """measure_indicators on the held-out `rows_`, their blocks inferred."""
    rng = random.Random(seed)
    c = collections.Counter()
    by_part = collections.defaultdict(collections.Counter)
    wrong, sample = [], []
    for pid, eid, clue, answer, facts in rows_:
        stated_ind = facts.get("indicators")
        if stated_ind:
            hid = {k: v for k, v in facts.items() if k != "indicators"}
            got = infer_indicators(clue, answer, hid, ilex)
            if facts.get("definition") and coverage(answer, facts) == "full":
                c["eligible"] += 1
                c["undecided"] += got is None
            truth = {_key(i) for i in texts(stated_ind)}
            if got:
                c["clues"] += 1
                c["clue exact"] += {_key(i) for i in texts(got)} == truth
                parts = needed(answer, hid["blocks"], hid.get("type"))
                for i in texts(got):
                    ok = _key(i) in truth
                    c["claimed"] += 1
                    c["exact"] += ok
                    c["overlap"] += ok or any(set(_key(i)) & set(t) for t in truth)
                    for p in parts:
                        by_part[p]["claimed"] += 1
                        by_part[p]["exact"] += ok
                    if not ok:
                        kind = "boundary" if any(set(_key(i)) & set(t) for t in truth) else \
                            "blog omitted" if truth <= {_key(g) for g in texts(got)} else "other"
                        c["miss", kind] += 1
                        wrong.append((kind, clue, answer, got, stated_ind, hid.get("blocks")))
        full = bool(facts.get("definition")) and coverage(answer, facts) == "full"
        c["all"] += 1
        c["ind before"] += bool(stated_ind)
        c["three before"] += full and bool(stated_ind)
        after = stated_ind or infer_indicators(clue, answer, facts, ilex)
        c["ind after"] += bool(after)
        c["three after"] += full and bool(after)
        if full and not stated_ind:
            c["no indicator wanted"] += needed(answer, facts["blocks"], facts.get("type")) == set()
        if after and not stated_ind:
            c["filled"] += 1
            sample.append((pid, eid, clue, answer, facts, after))
    print(f"slice {n}: {len({r[0] for r in rows_})} puzzles held out, {len(ilex.votes)} indicator phrases")
    print(f"blog indicators hidden: {c['eligible']} clues with a definition and full blocks, "
          f"filled {c['clues']}, undecided {c['undecided']}")
    print(f"  phrases {c['claimed']}, exact {c['exact'] / max(1, c['claimed']):.4f}, "
          f"sharing a word {c['overlap'] / max(1, c['claimed']):.4f}; clues whose set is the blog's {c['clue exact'] / max(1, c['clues']):.4f}")
    for p, x in sorted(by_part.items()):
        print(f"  {p:10} {x['claimed']:6} exact {x['exact'] / max(1, x['claimed']):.4f}")
    t = max(1, c["all"])
    print(f"of {c['all']} clues: has indicators {c['ind before'] / t:.3f} -> {c['ind after'] / t:.3f}; "
          f"definition + full blocks + indicators {c['three before'] / t:.3f} -> {c['three after'] / t:.3f} "
          f"({c['three before']} -> {c['three after']}); filled {c['filled']}; "
          f"definition + full blocks wanting no indicator {c['no indicator wanted']}")
    print("  misses:", {k[1]: v for k, v in c.items() if k[0] == "miss"})
    for kind, clue, answer, got, truth, blocks in sorted(wrong)[:show]:
        print(f"   miss [{kind}] {clue} = {answer}: {got}; blog {truth}; blocks {blocks}")
    for pid, eid, clue, answer, facts, got in rng.sample(sample, min(show, len(sample))):
        print(f"   read {pid} {eid} | {clue} = {answer} | def {facts.get('definition')} "
              f"blocks {facts.get('blocks')} | + {got}")


# ------------------------------------------------------------ lexicon definitions

#: Types whose definition the blocks and indicators do not bound: a cryptic
#: definition is the whole clue in 80% of write-ups and part of it in the
#: rest, and a double definition is two spans, either of which reads as one.
UNBOUNDED_DEF = ("cryptic_definition", "double_definition")


class Definitions:
    """What blogs underline, from the definitions they gave.

    `of`: answer letters -> Counter of the clue words (their letters, word by
    word) blogs underlined for it. `edge`: (side, word) -> [definitions at the
    far end of a clue that hold it anywhere but their outer end ("L" for one
    that ends the clue), definitions it stood next to on that side]: "for"
    and "is" stand beside definitions and are never in one, where "and" is in
    "sad and lonely"."""

    def __init__(self, corpus, skip=frozenset()):
        of = collections.defaultdict(collections.Counter)
        edge = collections.defaultdict(lambda: [0, 0])
        for pid, eid, clue, answer, facts in corpus:
            if pid in skip or not facts.get("definition"):
                continue
            ws = words(clue_body(clue))
            n = len(ws)
            for d in facts["definition"]:
                of[sys.intern(letters(answer))][_key(d)] += 1
                sp = sorted(locate(d, ws) or ())
                if not sp or len(sp) == n:
                    continue
                if sp[-1] == n - 1:
                    side, inside, out = "L", sp[:-1], sp[0] - 1
                elif sp[0] == 0:
                    side, inside, out = "R", sp[1:], sp[-1] + 1
                else:
                    continue
                for k in inside:
                    edge[side, ws[k][1]][0] += 1
                edge[side, ws[out][1]][1] += 1
        self.of, self.edge = dict(of), dict(edge)
        self.by_words = collections.defaultdict(set)
        for a, ks in self.of.items():
            for k in ks:
                self.by_words[k].add(a)

    def apart(self, side, word):
        """Whether blogs leave `word` out of a definition it stands beside on
        `side` and seldom have it inside one there (see MAX_ATTACH)."""
        inside, beside = self.edge.get((side, word), (0, 0))
        return beside >= MIN_APART and inside <= MAX_ATTACH * (inside + beside)


def infer_definition(clue, answer, facts, dlex):
    """The definition a blog left out: the one span at an end of the clue,
    clear of the wordplay (see wordplay_words), that blogs underlined for
    this answer in other clues, where the word inside it is wordplay or one
    blogs leave out of definitions. A list of one clue phrase, [] when
    none is wanted or found, None when another span at either end is one
    too or the edge is unclear.

    Where the word inside it is none of those, blogs underline a longer span
    ("county town" for "town") one time in eight, and no count of how often
    the longer phrase is a definition elsewhere brought that under 7%; one
    time in eight too where it is a phrase blogs name an indicator ("sort of
    pasta")."""
    t = facts.get("type") or ()
    if facts.get("definition") or any(x in t for x in UNBOUNDED_DEF):
        return []
    known = dlex.of.get(letters(answer or ""))
    if not known or not enumerated(clue, answer):
        return []
    body, ws, at = spans(clue)
    taken = wordplay_words(clue, answer, facts, ws)
    n = len(ws)
    found = []
    for k in range(1, n):
        for inward, a, z, nxt in (("R", 0, k, k), ("L", n - k, n, n - k - 1)):
            if not taken & set(range(a, z)) and known.get(tuple(l for _, l in ws[a:z])):
                found.append((inward, a, z, nxt))
    if len(found) != 1:
        return None if found else []
    inward, a, z, nxt = found[0]
    if POSSESSIVE.search(ws[a if inward == "L" else z - 1][0]):
        return None  # blogs underline "Country" in "Country's flag"
    if nxt in taken or dlex.apart(inward, ws[nxt][1]):
        return [body[at[a][0]:at[z - 1][1]]]
    return None


def enumerated(clue, answer):
    """Whether the clue's enumeration, where it has one, adds up to the answer:
    SPRING for "(6,7)" is the half of SPRING CHICKEN its wordplay starts with,
    and the definitions blogs gave SPRING are that half's ("Season")."""
    m = ENUM_TAIL.search(clue or "")
    lens = [int(x) for x in re.findall(r"\d+", m.group())] if m else []
    return not lens or sum(lens) == len(letters(answer or ""))


def named_words(facts, ws):
    """The indices of the clue words in `facts`' blocks and indicators."""
    taken = set()
    for phrase in [b[1] for b in facts.get("blocks", ())] + texts(facts.get("indicators")):
        taken |= locate(phrase, ws) or set()
    return taken


def wordplay_words(clue, answer, facts, ws):
    """The indices of the clue words `facts` put in the wordplay: its blocks,
    its indicators, and anagram fodder or a hidden answer the letters read."""
    taken = named_words(facts, ws)
    got = infer(clue, answer, {"blocks": facts.get("blocks", [])})
    if got and got.get("fodder") and tuple(got.get("type") or ()) in TRUSTED:
        taken |= locate(got["fodder"], ws) or set()
    return taken


def with_definition(facts, new):
    """`facts` with the inferred definition `new`, marked so: the blog stated none."""
    return {**facts, "definition": new, "inferred": sorted({*facts.get("inferred", ()), "definition"})}


def measure_definitions(corpus, n=1, show=30, seed=1):
    """Precision of infer_definition on slice `n` of the puzzles, every lexicon
    built without them: the blog's own definitions hidden, the blocks
    inferred with them hidden as the write would, and the coverage it adds."""
    test = {pid for pid, *_ in corpus if in_slice(pid, n)}
    lex, ilex, dlex = Lexicon(corpus, skip=test), Indicators(corpus, skip=test, extra=annotation_rows()), Definitions(corpus, skip=test)
    trained = {letters(clue_body(clue)) for pid, _, clue, *_ in corpus if pid not in test}
    rng = random.Random(seed)
    c = collections.Counter()
    by = collections.defaultdict(collections.Counter)
    wrong, sample = [], []
    for pid, eid, clue, answer, facts in corpus:
        if pid not in test:
            continue
        stated_def = facts.get("definition")
        if stated_def:
            hid = {k: v for k, v in facts.items() if k != "definition"}
            new = infer_blocks(clue, answer, hid, lex)
            hid = with_blocks(hid, new) if new else hid
            got = infer_definition(clue, answer, hid, dlex)
            c["hidden"] += 1
            c["undecided"] += got is None
            if got:
                ok = {_key(d) for d in got} == {_key(d) for d in stated_def}
                seen = "clue seen in training" if letters(clue_body(clue)) in trained else "clue unseen"
                for key in ("all", boundary(clue, answer, hid, got), seen):
                    by[key]["claimed"] += 1
                    by[key]["exact"] += ok
                if not ok:
                    ws = words(clue_body(clue))
                    kind = "boundary" if any((locate(g, ws) or set()) & (locate(d, ws) or set())
                                             for g in got for d in stated_def) else "other end"
                    c["miss", kind] += 1
                    wrong.append((kind, clue, answer, got, stated_def, hid.get("blocks"), hid.get("indicators")))
        new = infer_blocks(clue, answer, facts, lex)
        before = with_blocks(facts, new) if new else facts
        add = infer_definition(clue, answer, before, dlex)
        after = with_definition(before, add) if add else before
        c["all"] += 1
        for name, f in (("before", before), ("after", after)):
            ind = infer_indicators(clue, answer, f, ilex)
            f = with_indicators(f, ind) if ind else f
            c["def", name] += bool(f.get("definition"))
            c["three", name] += all_three(answer, f)
        if add:
            sample.append((pid, eid, clue, answer, after))
    t = max(1, c["all"])
    print(f"slice {n}: {len(test)} puzzles held out, definitions of {len(dlex.of)} answers")
    print(f"blog definitions hidden: {c['hidden']} clues, claimed {by['all']['claimed']}, undecided {c['undecided']}")
    for key, x in sorted(by.items()):
        print(f"  {key:22} {x['claimed']:6} exact {x['exact'] / max(1, x['claimed']):.4f}")
    print("  misses:", {k[1]: v for k, v in c.items() if k[0] == "miss"})
    print(f"of {c['all']} clues: has definition {c['def', 'before'] / t:.3f} -> {c['def', 'after'] / t:.3f}; "
          f"definition + full blocks + indicators {c['three', 'before'] / t:.3f} -> {c['three', 'after'] / t:.3f} "
          f"({c['three', 'before']} -> {c['three', 'after']}); filled {len(sample)}")
    for kind, clue, answer, got, truth, blocks, inds in sorted(wrong)[:show]:
        print(f"   miss [{kind}] {clue} = {answer}: {got}; blog {truth}; blocks {blocks} ind {inds}")
    for pid, eid, clue, answer, f in rng.sample(sample, min(show, len(sample))):
        print(f"   read {pid} {eid} | {clue} = {answer} | + def {f['definition']} | blocks {f.get('blocks')} "
              f"ind {f.get('indicators')}")


def boundary(clue, answer, facts, got):
    """What bounds the inside edge of the definition `got` infer_definition
    read: "block or indicator" (the blog's or inferred), "fodder" the letters read, or "link word"."""
    ws = words(clue_body(clue))
    sp = sorted(locate(got[0], ws) or ())
    nxt = sp[0] - 1 if sp[-1] == len(ws) - 1 else sp[-1] + 1
    return "block or indicator" if nxt in named_words(facts, ws) else \
        "fodder" if nxt in wordplay_words(clue, answer, facts, ws) else "link word"


def all_three(answer, facts):
    """Whether a clue has a definition, blocks spelling the whole answer, and indicators."""
    return bool(facts.get("definition")) and coverage(answer, facts) == "full" and bool(facts.get("indicators"))


def complete(answer, facts):
    """Whether a clue has every part its kind has in the app's annotations: a
    double definition its two halves, a cryptic definition its definition,
    and any other clue a definition, blocks spelling the answer, and the
    indicators those blocks want (see needed), named or, as for most
    charades, none wanted."""
    t, d = facts.get("type") or [], facts.get("definition") or []
    if len(t) == 1 and t[0] in UNBOUNDED_DEF:
        return len(d) == 2 if t == ["double_definition"] else bool(d)
    if not d or coverage(answer, facts) != "full":
        return False
    return bool(facts.get("indicators")) or needed(answer, facts["blocks"], facts.get("type")) == set()


# ------------------------------------------------------------ corpus

def rows(said=None, as_written=False):
    """(puzzle id, entry id, clue, answer, blog facts) for every clue of every
    puzzle blog_facts has a post for, facts or none; with, under "leads",
    what the write-up says short of its blocks, where `said` (read_leads) has
    it. The facts are as the blog stated them (see stated), or `as_written`,
    with what this file inferred."""
    for f in sorted(OUT.glob("*.json")):
        for pid, rec in json.loads(f.read_text(encoding="utf-8")).items():
            path = find_puzzle(pid)
            if path is None:
                continue
            ents = {e["id"]: e for e in json.loads(path.read_text(encoding="utf-8"))["entries"]}
            got = (said or {}).get(pid, {})
            for eid, e in ents.items():
                if e.get("solution") and e["clue"].get("text"):
                    facts = fact_from_json(rec["entries"].get(eid, {}))
                    facts = facts if as_written else stated(facts)
                    yield (pid, eid, enumeration.printed(e["clue"]), e["solution"],
                           {**facts, "leads": got[eid]} if eid in got else facts)


def annotation_rows():
    """(puzzle id, entry id, clue, answer, facts) for every clue our own
    annotations (puzzles/) explain, in the shape of a blog's facts: a second
    source for the indicator lexicon."""
    for path in puzzle_files():
        p = json.loads(path.read_text(encoding="utf-8"))
        for e in p.get("entries", []):
            a = e.get("annotation") or {}
            if not (a.get("type") and e["clue"].get("text") and e.get("solution")):
                continue
            facts = {"type": a["type"], "definition": [d["text"] for d in a.get("definitions", ())],
                     "blocks": [[b["gives"], b["clueFragment"]] for b in a.get("blocks", ())
                                if b.get("gives") and b.get("clueFragment")]}
            if a.get("indicators"):
                facts["indicators"] = list(a["indicators"])
            yield p["id"], e["id"], enumeration.printed(e["clue"]), e["solution"], facts


def read_leads(required=False):
    """blog_facts.py's leads, {puzzle id: {entry id: leads}}; {} where it has
    written none, or, `required`, an exit saying how to get them."""
    if LEADS.exists():
        return json.loads(LEADS.read_text(encoding="utf-8"))
    if required:
        sys.exit(f"{LEADS} is missing: tools/blog_facts.py writes it from the blog caches, and this"
                 " reads the blocks write-ups give in prose off it; run that, which runs this after")
    return {}


def stated(facts):
    """A clue's facts as the blog stated them, without what this file inferred:
    a field named in "inferred" (the type, the definition, the indicators), or
    a block marked INFERRED, but for a heard one (with_heard), the blog's block it was read from."""
    ours = {"inferred", "typeCore", *facts.get("inferred", ())} - {"blocks"}
    out = {k: v for k, v in facts.items() if k not in ours and k != "blocks"}
    heard = lambda b: next((h["soundsLike"] for h in b[2:] if isinstance(h, dict) and "soundsLike" in h), None)
    blocks = [b if INFERRED not in b[2:] else [heard(b), b[1]]  # the blog's own words, read as heard (with_heard)
              for b in facts.get("blocks", ()) if INFERRED not in b[2:] or heard(b)]
    return {**out, "blocks": blocks} if blocks else out


def written(t):
    """(type list, is it only the core) that a reading of type `t` is written as, or None."""
    t = tuple(t or ())
    if t in TRUSTED:
        return list(t), False
    return (list(type_name(core(t))), True) if t in CORE_TRUSTED else None


def inferred(clue, answer, facts, votes, lex, ilex, dlex, fuzzy=True):
    """`facts` with what the letters add, marked as inferred: a type in a
    TRUSTED or CORE_TRUSTED class, the blocks the blog left out or gave in
    prose, the definition where it named none, and then the indicator those
    blocks want where it named none."""
    if not facts.get("type"):
        got = infer(clue, answer, {k: facts[k] for k in ("definition", "blocks") if k in facts}, votes)
        w = written(got.get("type")) if got else None
        if w:
            facts = {**facts, "type": w[0], "inferred": ["type"], **({"typeCore": True} if w[1] else {})}
    new = infer_heard(clue, answer, facts)
    facts = with_heard(facts, new) if new else facts
    facts = with_all_blocks(clue, answer, facts, lex, dlex, fuzzy)
    new = infer_fodder(clue, answer, facts, votes)
    facts = with_blocks(facts, new) if new else facts
    new = infer_definition(clue, answer, facts, dlex)
    facts = with_definition(facts, new) if new else facts
    new = infer_carrier(clue, answer, facts)
    if new and facts.get("type") == ["hidden_word"] and carried(answer, new) == "reversed":
        facts = {**facts, "type": ["hidden_word", "reversal"], "inferred": sorted({*facts.get("inferred", ()), "type"})}
    facts = with_blocks(facts, new) if new else facts
    new = infer_indicators(clue, answer, facts, ilex)
    return with_indicators(facts, new) if new else facts


def infer_fodder(clue, answer, facts, votes):
    """An anagram's one block, as the blogs write it: [(the fodder in
    capitals, the fodder, "anagrammed")], the fodder the one run of clue
    words outside the definition with the answer's letters, where the type
    is an anagram and there are no blocks; else []."""
    if facts.get("type") != ["anagram"] or facts.get("blocks"):
        return []
    got = infer(clue, answer, {k: facts[k] for k in ("definition",) if k in facts}, votes)
    if not got or got.get("type") != ["anagram"] or not got.get("fodder"):
        return []
    return [(got["fodder"].upper(), got["fodder"], "anagrammed")]


#: A hidden word's type, and whether the answer is spelt backwards in its carrier.
HIDDEN = {("hidden_word",): False, ("hidden_word", "reversal"): True}


def infer_carrier(clue, answer, facts):
    """The one block of a hidden word, as our annotations write it: [(the
    answer, the clue words it is spelt in)], where the type is a hidden word
    and the answer (reversed, where the type says so) is spelt in one run of
    the clue words outside the definition and indicators; else []. A
    ["hidden_word"] not spelt forward there is looked for reversed."""
    rev = HIDDEN.get(tuple(facts.get("type") or ()))
    answer = letters(answer or "")
    if rev is None or facts.get("blocks") or len(answer) < 3:
        return []
    body, ws, at = spans(clue)
    taken = set()
    for phrase in facts.get("definition", []) + texts(facts.get("indicators")):
        taken |= locate(phrase, ws) or set()
    hits = hidden(answer, ws, set(range(len(ws))) - taken)
    if not rev and not any(not r for _, r in hits):
        rev = True  # a blog seldom names a hidden word's reversal
    got = [run for run, r in hits if r == rev]
    if len(got) != 1:
        return []
    return [(answer, body[at[got[0][0]][0]:at[got[0][-1]][1]])]


#: The types whose blocks are heard: the answer, from clue words read as words
#: it sounds like, the block's soundsLike (see blog_facts.heard_blocks).
SOUNDED = (["homophone"], ["spoonerism"])


def sounds_like(answer, blocks):
    """What `blocks` are heard as, where every one is heard (see
    blog_facts.heard_blocks) and they spell `answer`; else None."""
    heard = [next((h["soundsLike"] for h in b[2:] if isinstance(h, dict) and "soundsLike" in h), None)
             for b in blocks]
    if not blocks or None in heard or letters("".join(b[0] for b in blocks)) != letters(answer or ""):
        return None
    return " ".join(heard)


#: The CMU Pronouncing Dictionary, stress dropped: word -> its pronunciations.
CMUDICT = ROOT / "tools" / "data" / "cmudict.txt.gz"
PHONE_VOWELS = frozenset({"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"})
#: The most pronunciations one phrase is read as; the rest are not tried.
MAX_SAID = 64


@functools.cache
def _cmudict():
    import gzip
    with gzip.open(CMUDICT, "rt", encoding="utf-8") as f:
        return {w: [tuple(p.split()) for p in ps.split("|")]
                for w, ps in (line.rstrip("\n").split("\t") for line in f if not line.startswith("#"))}


def _british(p):
    """A pronunciation as British setters say it: no R but before a vowel."""
    return tuple(x for i, x in enumerate(p) if x != "R" or i + 1 < len(p) and p[i + 1] in PHONE_VOWELS)


@functools.cache
def said_word(w):
    """How the letters `w` are said: the dictionary's, or where it has no
    such word, those of words of three or more letters (or A, I) that spell it."""
    d, w = _cmudict(), letters(w).lower()
    at = {len(w): {()}}
    for i in range(len(w) - 1, -1, -1):
        at[i] = {p + rest for j in range(i + 1, len(w) + 1) if j - i >= 3 or w[i:j] in ("a", "i")
                 for p in d.get(w[i:j], ()) for rest in at[j]} if w[i:] not in d else set(d[w[i:]])
        if len(at[i]) > MAX_SAID:
            at[i] = set(sorted(at[i])[:MAX_SAID])
    return frozenset(map(_british, at[0])) if w else frozenset()


def said(phrase):
    """How `phrase` is said, word after word (see said_word); empty where a word is unknown."""
    got = {()}
    for _, w in words(phrase):
        ps = said_word(w)
        got = set(sorted(a + b for a in got for b in ps)[:MAX_SAID])
        if not got:
            break
    return got


def said_like(heard, answer, clue=""):
    """Whether `heard` is said as `answer` is, by the dictionary (see said):
    the answer read whole and, where the clue's enumeration splits it, as those words."""
    enum = [int(n) for n in re.findall(r"\d+", (ENUM_TAIL.search(clue) or [""])[0])]
    a, ways = letters(answer), said(answer)
    if len(enum) > 1 and sum(enum) == len(a):
        ends = list(itertools.accumulate(enum))
        ways |= said(" ".join(a[e - n:e] for e, n in zip(ends, enum)))
    return bool(ways) and not said(heard).isdisjoint(ways)


def infer_heard(clue, answer, facts):
    """A homophone's or a spoonerism's blocks read as heard (see
    blog_facts.heard_blocks), where the blog's are the words heard and they
    are said as the answer is by the dictionary (see said_like), not only by
    blog_facts.sounds_alike's spelling rules; else []."""
    blocks = facts.get("blocks") or []
    if facts.get("type") not in SOUNDED or not blocks or any(len(b) != 2 for b in blocks) \
            or letters("".join(b[0] for b in blocks)) == letters(answer or ""):
        return []
    new = heard_blocks(facts["type"], [list(b) for b in blocks], answer, clue_body(clue),
                       alike=lambda h, a: said_like(h, a, clue))
    return new if sounds_like(answer, new) else []


def with_heard(facts, new):
    """`facts` with the blog's blocks read as the heard blocks `new`, marked inferred."""
    return {**facts, "blocks": [[g, src, INFERRED, *how] for g, src, *how in new],
            "inferred": sorted({*facts.get("inferred", ()), "blocks"})}


def carried(answer, blocks):
    """Whether `blocks` are a hidden word's (see infer_carrier): one block
    whose letters are the answer, spelt inside its words and not all of them;
    "reversed" where spelt backwards."""
    answer = letters(answer or "")
    if len(blocks) != 1 or letters(blocks[0][0]) != answer or "anagrammed" in blocks[0][2:]:
        return False
    src = letters(blocks[0][1])
    return src != answer and ("forward" if answer in src else "reversed" if answer[::-1] in src else False)


def with_all_blocks(clue, answer, facts, lex, dlex, fuzzy=True):
    """`facts` with the blocks infer_blocks reads off the lexicon and then,
    `fuzzy`, those infer_fuzzy_blocks reads off the write-up's prose."""
    new = infer_blocks(clue, answer, facts, lex)
    facts = with_blocks(facts, new) if new else facts
    if not fuzzy or coverage(answer, facts) in ("full", "n/a") or not facts.get("leads"):
        return facts
    new = infer_fuzzy_blocks(clue, answer, facts, lex, dlex, facts["leads"])
    return with_blocks(facts, new) if new else facts


def write(corpus, votes):
    """Rewrite tools/data/blog_facts/ with the inferred fields in, as
    blog_facts.write lays it out. {field: clues it was inferred in}."""
    ours = list(annotation_rows())
    lex, ilex, dlex = Lexicon(corpus), Indicators(corpus, extra=ours), Definitions(corpus)
    by_pid = collections.defaultdict(dict)
    for pid, eid, clue, answer, facts in corpus:
        # Definitions are placed in the clue's words, as the puzzle stores them.
        new = fact_json(inferred(clue, answer, facts, votes, lex, ilex, dlex),
                        enumeration.split(clue)[0])
        if new:
            by_pid[pid][eid] = new
    n = collections.Counter()
    for f in sorted(OUT.glob("*.json")):
        rows_ = json.loads(f.read_text(encoding="utf-8"))
        for pid, rec in rows_.items():
            if pid in by_pid:
                n.update(k for v in by_pid[pid].values() for k in v.get("inferred", ()))
                rec["entries"] = dict(sorted(by_pid[pid].items()))
        f.write_text(file_text(rows_), encoding="utf-8")
    n.update(export_lexicons(Lexicon(corpus, extra=ours), ilex))
    return n


#: The combined lexicons as write() leaves them, for the site: clue words
#: -> {letters: blocks} read as, and type part -> {indicator: clues}.
LEXICON_OUT = ROOT / "tools" / "data" / "lexicons"


def export_lexicons(lex, ilex):
    """Write what infer_blocks and infer_indicators read clue words as, the
    blogs' and our annotations' together, to LEXICON_OUT: blocks.json, clue
    words -> {letters: blocks}, only readings spellings() takes; and
    indicators.json, type part -> {indicator: clues}, only those indicates()
    takes; each largest first. {file: entries}."""
    blocks = {}
    for key, got in lex.seen.items():
        keep = lex.spellings(key) & set(got)
        if keep:
            blocks[" ".join(key)] = dict(sorted(((b, got[b]) for b in keep), key=lambda kv: (-kv[1], kv[0])))
    parts = collections.defaultdict(dict)
    for key, v in ilex.votes.items():
        for part, n in v.items():
            if ilex.indicates(key, part):
                parts[part][" ".join(key)] = n
    out = {"blocks.json": dict(sorted(blocks.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))),
           "indicators.json": {p: dict(sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))
                               for p, d in sorted(parts.items(), key=lambda kv: -sum(kv[1].values()))}}
    LEXICON_OUT.mkdir(exist_ok=True)
    for name, data in out.items():
        (LEXICON_OUT / name).write_text("{\n" + ",\n".join(json.dumps(k, ensure_ascii=False) + ": " + json.dumps(v, ensure_ascii=False)
                                                           for k, v in data.items()) + "\n}\n", encoding="utf-8")
    return {name: len(data) if name == "blocks.json" else sum(map(len, data.values())) for name, data in out.items()}


def vote_key(phrase):
    """An indicator phrase as indicator_votes keys it."""
    return phrase.lower().replace("’", "'")


def indicator_votes(corpus):
    """Indicator phrase -> Counter of the types blogs named it an indicator
    for: each under its own `for`, and under nothing without one."""
    votes = collections.defaultdict(collections.Counter)
    for *_, facts in corpus:
        for i in facts.get("indicators", ()):
            if i.get("for"):
                votes[vote_key(i["text"])][i["for"]] += 1
    return votes


def without(votes, facts):
    """`votes` less this clue's own contribution, so a clue never confirms itself."""
    own = collections.defaultdict(collections.Counter)
    for i in facts.get("indicators", ()):
        if i.get("for"):
            own[vote_key(i["text"])][i["for"]] += 1
    if not own:
        return votes

    class Minus(dict):
        def get(self, k, d=None):
            v = votes.get(k)
            if v is None or k not in own:
                return v
            return collections.Counter(v) - own[k]
    return Minus()


#: The parts a blog names or leaves out by habit: how a block was taken from its words.
TAKEN = {"deletion", "letter_selection"}


def core(t):
    """A type less the parts that say how blocks were taken from their words."""
    return frozenset(t or ()) - TAKEN


def agrees(t, gold):
    """Whether the type read, `t`, is the blog's: the same, or a reversed
    hidden word the blog called hidden, since a blog seldom names the
    reversal and the letters read one only where the answer is not spelt forward."""
    t, gold = tuple(t or ()), tuple(gold or ())
    return t == gold or (t, gold) == (("hidden_word", "reversal"), ("hidden_word",))


def held_out(pid):
    """A quarter of the puzzles, fixed by id, kept back from tuning."""
    return hashlib.sha1(pid.encode()).digest()[0] % 4 == 0


def measure(corpus, votes, show=8, split="held-out"):
    tally = collections.defaultdict(collections.Counter)
    fps = collections.defaultdict(list)
    undecided = collections.defaultdict(list)
    blog_types = collections.Counter()
    ind = collections.Counter()
    for pid, eid, clue, answer, facts in corpus:
        gold = tuple(facts.get("type") or ())
        if not gold or held_out(pid) != (split == "held-out"):
            continue
        blog_types[gold] += 1
        known = {k: facts[k] for k in ("definition", "blocks") if k in facts}
        got = infer(clue, answer, known, without(votes, facts))
        if not got:
            continue
        if "undecided" in got:
            tally[gold]["undecided"] += 1
            undecided[" | ".join(sorted({t for t, _ in got["undecided"]}))].append((gold, clue, answer, got))
            continue
        t = tuple(got["type"])
        tally[t]["claimed"] += 1
        if agrees(t, gold):
            tally[t]["right"] += 1
        if core(t) == core(gold):
            tally[t]["core"] += 1
        tally[t]["wrote"] += agrees((written(t) or (None,))[0], gold)
        if not agrees(t, gold):
            fps[t].append((gold, clue, answer, got))
        if facts.get("indicators") and got.get("indicators"):
            g = {w for i in texts(facts["indicators"]) for w in re.findall(r"[\w'’]+", i.lower())}
            p = {w for i in got["indicators"] for w in re.findall(r"[\w'’]+", i.lower())}
            for key in ("all", t) if t in TRUSTED else ("all",):
                ind[key, "tp"] += len(g & p)
                ind[key, "fp"] += len(p - g)
                ind[key, "fn"] += len(g - p)
    print(f"\n== {split}")
    print(f"{'type':34} {'claimed':>8} {'right':>7} {'prec':>6} {'core':>6} {'blog':>7} {'cover':>6} {'wrote':>6}")
    for t, c in sorted(tally.items(), key=lambda kv: -kv[1]["claimed"]):
        if not c["claimed"]:
            continue
        mark = "*" if t in TRUSTED else "c" if t in CORE_TRUSTED else " "
        print(f"{show(t):33}{mark} {c['claimed']:8} {c['right']:7} {c['right'] / c['claimed']:6.3f} {c['core'] / c['claimed']:6.3f} "
              f"{blog_types[t]:7} {c['right'] / max(1, blog_types[t]):6.3f} {c['wrote'] / c['claimed']:6.3f}")
        if split == "held-out" and t in TRUSTED and c["right"] / c["claimed"] < PRECISION_BAR:
            print(f"   ^ TRUSTED but under {PRECISION_BAR}: take it out of TRUSTED")
        if split == "held-out" and t in CORE_TRUSTED and (
                c["core"] / c["claimed"] < PRECISION_BAR or c["claimed"] < MIN_CORE_CLAIMS):
            print(f"   ^ CORE_TRUSTED but core under {PRECISION_BAR} or read under {MIN_CORE_CLAIMS} times: take it out")
    print(f"undecided: {sum(c['undecided'] for c in tally.values())}")
    for key in ["all", *sorted(TRUSTED)]:
        tp, fp, fn = (ind[key, x] for x in ("tp", "fp", "fn"))
        if tp + fp:
            print(f"indicator words, {show(key)} types, where the blog named some: "
                  f"P {tp / (tp + fp):.3f} R {tp / (tp + fn):.3f} ({tp} tp, {fp} fp)")
    for k, lst in sorted(undecided.items(), key=lambda kv: -len(kv[1]))[:15]:
        print(f"\n-- undecided between {k} ({len(lst)}); blog said", collections.Counter(g for g, *_ in lst).most_common(5))
        for g, clue, answer, got in lst[:4]:
            print(f"   [{show(g)}] {clue} = {answer}: {got['undecided']}")
    for t, lst in fps.items():
        print(f"\n-- claimed {show(t)}, blog said otherwise ({len(lst)}):")
        print("   blog types:", collections.Counter(g for g, *_ in lst).most_common(6))
        lst.sort(key=lambda r: core(r[0]) == core(t))
        for g, clue, answer, got in lst[:show] + lst[-(show // 2):]:
            print(f"   [{show(g)}] {clue} = {answer}: {got.get('why')}")


def in_slice(pid, n):
    """One puzzle in twenty, fixed by id: slice `n` of 20."""
    return hashlib.sha1(pid.encode()).digest()[1] % 20 == n


def block_key(b):
    return letters(b[0]), _key(b[1])


def coverage(answer, facts):
    """How far a clue's blocks spell its answer: full, partial, none, excess, or n/a
    for a type that has none (a hidden word has one, its carrier: see infer_carrier)."""
    t = facts.get("type") or []
    got = collections.Counter("".join(letters(b[0]) for b in facts.get("blocks") or ()))
    if t in (["double_definition"], ["cryptic_definition"]) or "hidden_word" in t and not got:
        return "n/a"
    if not got:
        return "none"
    need = collections.Counter(letters(answer))
    return "full" if got == need else "partial" if not got - need else "excess"


def leftover_runs(clue, facts):
    """The runs of clue words no definition, block or indicator takes."""
    ws = words(clue_body(clue))
    taken = set()
    for phrase in facts.get("definition", []) + texts(facts.get("indicators")) + [b[1] for b in facts.get("blocks", [])]:
        taken |= locate(phrase, ws) or set()
    return sum(1 for k in range(len(ws)) if k not in taken and (k == 0 or k - 1 in taken))


def with_blocks(facts, new):
    """`facts` with the inferred blocks `new` added, marked so: [letters,
    clue words, "inferred"], anagram fodder with "anagrammed" after it."""
    return {**facts, "blocks": [*facts.get("blocks", []), *([b, src, INFERRED, *how] for b, src, *how in new)],
            "inferred": sorted({*facts.get("inferred", ()), "blocks"})}


def measure_blocks(corpus, n=0, show=30, seed=1):
    """Precision of infer_blocks on slice `n` of the puzzles, the lexicon
    built without them or any puzzle we annotated: the blog's own blocks
    recovered with them hidden (all, or one), what it claims on clues whose
    type has no blocks, the coverage it adds, and how it agrees with ours."""
    annotated = {}
    for path in puzzle_files():
        p = json.loads(path.read_text(encoding="utf-8"))
        ann = {e["id"]: e["annotation"] for e in p.get("entries", []) if (e.get("annotation") or {}).get("blocks")}
        if ann:
            annotated[p["id"]] = ann
    test = {pid for pid, *_ in corpus if in_slice(pid, n)}
    lex = Lexicon(corpus, skip=test | set(annotated))
    rng = random.Random(seed)
    c = collections.Counter()
    before, after = collections.Counter(), collections.Counter()
    sample, wrong = [], []
    for pid, eid, clue, answer, facts in corpus:
        if pid in test:
            blocks = facts.get("blocks") or []
            cov = coverage(answer, facts)
            if cov == "full":
                for mode in ("all", "one"):
                    if mode == "one" and len(blocks) < 2:
                        continue
                    hide = set(range(len(blocks))) if mode == "all" else {rng.randrange(len(blocks))}
                    keep = {**facts, "blocks": [b for k, b in enumerate(blocks) if k not in hide]}
                    truth = {block_key(blocks[k]) for k in hide}
                    got = infer_blocks(clue, answer, keep, lex) or []
                    c[mode, "clues"] += 1
                    c[mode, "claimed"] += bool(got)
                    for b in got:
                        c[mode, "blocks"] += 1
                        c[mode, "exact"] += block_key(b) in truth
                        if block_key(b) not in truth:
                            wrong.append((mode, clue, answer, b, [blocks[k] for k in hide]))
            t = facts.get("type") or ()
            if not blocks and any(x in t for x in NO_SPLIT):
                c["typed", "clues"] += 1
                c["typed", "claimed"] += bool(infer_blocks(clue, answer, {k: v for k, v in facts.items() if k != "type"}, lex))
            new = infer_blocks(clue, answer, facts, lex)
            if new is None:
                c["undecided"] += 1
            filled = with_blocks(facts, new) if new else facts
            before[cov] += 1
            after[coverage(answer, filled)] += 1
            if new:
                c["filled clues"] += 1
                c["filled blocks"] += len(new)
                sample.append((pid, clue, answer, facts, new))
            if coverage(answer, filled) == "full":
                c["full, one leftover run"] += leftover_runs(clue, filled) == 1
                c["full, no leftover"] += leftover_runs(clue, filled) == 0
        if pid in annotated and eid in annotated[pid]:
            new = infer_blocks(clue, answer, facts, lex) or []
            ours = {(letters(b.get("gives") or ""), _key(b.get("clueFragment") or "")) for b in annotated[pid][eid]["blocks"]}
            for b in new:
                c["ann", "blocks"] += 1
                c["ann", "exact"] += block_key(b) in ours
                c["ann", "letters"] += letters(b[0]) in {g for g, _ in ours}
    print(f"slice {n}: {len(test)} puzzles held out, lexicon of {len(lex.seen)} clue phrases")
    for mode in ("all", "one"):
        print(f"blog blocks hidden ({mode}): {c[mode, 'clues']} clues, claimed {c[mode, 'claimed']} "
              f"({c[mode, 'claimed'] / max(1, c[mode, 'clues']):.3f}), {c[mode, 'blocks']} blocks, "
              f"exact {c[mode, 'exact'] / max(1, c[mode, 'blocks']):.4f}")
    print(f"clues of a type with no blocks, the type hidden: {c['typed', 'clues']}, claimed {c['typed', 'claimed']}")
    total = sum(before.values())
    print(f"coverage of {total} clues:", ", ".join(f"{k} {before[k] / total:.3f} -> {after[k] / total:.3f}"
                                               for k in ("full", "partial", "none", "excess", "n/a")))
    print(f"filled {c['filled clues']} clues with {c['filled blocks']} blocks; undecided {c['undecided']}; "
          f"now full with one leftover run {c['full, one leftover run']}, with none {c['full, no leftover']}")
    print(f"against our annotations: {c['ann', 'blocks']} inferred blocks, exact {c['ann', 'exact'] / max(1, c['ann', 'blocks']):.4f}, "
          f"letters {c['ann', 'letters'] / max(1, c['ann', 'blocks']):.4f}")
    for mode, clue, answer, b, truth in wrong[:show // 2]:
        print(f"   miss [{mode}] {clue} = {answer}: {b[0]} from {b[1]!r}; blog {truth}")
    for pid, clue, answer, facts, new in rng.sample(sample, min(show, len(sample))):
        print(f"   read {pid} | {clue} = {answer} | def {facts.get('definition')} ind {facts.get('indicators')} "
              f"blog {facts.get('blocks')} | + {new}")


def measure_fuzzy_blocks(corpus, votes, n=2, show=30, seed=1):
    """Precision of infer_fuzzy_blocks on slice `n` of the puzzles, every
    lexicon built without them or any puzzle we annotated: the blog's own
    full blocks recovered with them and the type hidden (all of them; all,
    with the write-up's capitals hidden too, as prose that names only clue
    words; one), against our annotations where the blog gave none, and the
    coverage it adds on the slice."""
    annotated = {}
    for path in puzzle_files():
        p = json.loads(path.read_text(encoding="utf-8"))
        ann = {e["id"]: e["annotation"] for e in p.get("entries", []) if (e.get("annotation") or {}).get("blocks")}
        if ann:
            annotated[p["id"]] = ann
    test = {pid for pid, *_ in corpus if in_slice(pid, n)}
    lex, dlex = Lexicon(corpus, skip=test | set(annotated)), Definitions(corpus, skip=test | set(annotated))
    ilex = Indicators(corpus, skip=test, extra=annotation_rows())
    rng = random.Random(seed)
    c = collections.Counter()
    by = collections.defaultdict(collections.Counter)
    wrong, sample = collections.defaultdict(list), []
    modes = ("all hidden", "capitals hidden too", "one hidden")
    for pid, eid, clue, answer, facts in corpus:
        said = facts.get("leads") or {}
        if pid in test and coverage(answer, facts) == "full" and said:
            blocks = facts["blocks"]
            bare = {k: v for k, v in facts.items() if k not in ("blocks", "type", "leads")}
            for mode in modes:
                hide = {rng.randrange(len(blocks))} if mode == "one hidden" else set(range(len(blocks)))
                if mode == "one hidden" and len(blocks) < 2:
                    continue
                keep = {**bare, "blocks": [b for k, b in enumerate(blocks) if k not in hide]}
                lead = {k: v for k, v in said.items() if k not in ("caps", "near")} if mode == modes[1] else said
                truth = {block_key(blocks[k]) for k in hide}
                srcs = []
                got = infer_fuzzy_blocks(clue, answer, keep, lex, dlex, lead, srcs) or []
                c[mode, "clues"] += 1
                c[mode, "claimed"] += bool(got)
                for b, how in zip(got, srcs):
                    ok = block_key(b) in truth
                    for key in ("all", how):
                        by[mode, key]["blocks"] += 1
                        by[mode, key]["exact"] += ok
                    if not ok:
                        wrong[mode].append((how, clue, answer, b, [blocks[k] for k in hide]))
        if pid in annotated and eid in annotated[pid] and coverage(answer, facts) != "full":
            srcs = []
            f = with_blocks(facts, infer_blocks(clue, answer, facts, lex) or [])
            got = infer_fuzzy_blocks(clue, answer, f, lex, dlex, said, srcs) or [] if coverage(answer, f) != "full" else []
            ours = {(letters(b.get("gives") or ""), _key(b.get("clueFragment") or "")) for b in annotated[pid][eid]["blocks"]}
            for b in got:
                by["ours", "all"]["blocks"] += 1
                by["ours", "all"]["exact"] += block_key(b) in ours
                by["ours", "all"]["letters"] += letters(b[0]) in {g for g, _ in ours}
                if block_key(b) not in ours:
                    wrong["ours"].append(("ours", clue, answer, b, sorted(ours)))
        if pid in test:
            before = inferred(clue, answer, facts, votes, lex, ilex, dlex, fuzzy=False)
            after = inferred(clue, answer, facts, votes, lex, ilex, dlex)
            c["all"] += 1
            for name, f in (("before", before), ("after", after)):
                cov = coverage(answer, f)
                c["cover", name, cov] += 1
                c["three", name] += all_three(answer, f)
                c["complete", name] += complete(answer, f)
                c["def + full", name] += bool(f.get("definition")) and cov == "full"
            new = [b for b in after.get("blocks", ()) if b not in before.get("blocks", ())]
            if new:
                c["filled", coverage(answer, before)] += 1
                sample.append((pid, eid, clue, answer, before.get("definition"), before.get("blocks"), new))
    print(f"slice {n}: {len(test)} puzzles held out, {len(annotated)} we annotated kept out of the lexicons")
    for mode in modes:
        x = by[mode, "all"]
        print(f"blog blocks {mode}: {c[mode, 'clues']} clues, claimed {c[mode, 'claimed']}, "
              f"{x['blocks']} blocks, exact {x['exact'] / max(1, x['blocks']):.4f}")
        for (m, how), y in sorted(by.items()):
            if m == mode and how != "all":
                print(f"   {how:16} {y['blocks']:6} exact {y['exact'] / max(1, y['blocks']):.4f}")
    x = by["ours", "all"]
    print(f"against our annotations, the blog's blocks short: {x['blocks']} blocks, exact "
          f"{x['exact'] / max(1, x['blocks']):.4f}, letters {x['letters'] / max(1, x['blocks']):.4f}")
    t = max(1, c["all"])
    print(f"of {c['all']} clues:", ", ".join(f"{k} {c['cover', 'before', k] / t:.3f} -> {c['cover', 'after', k] / t:.3f}"
                                            for k in ("full", "partial", "none", "excess", "n/a")))
    print(f"  full blocks {c['cover', 'before', 'full']} -> {c['cover', 'after', 'full']}; definition + full blocks "
          f"{c['def + full', 'before']} -> {c['def + full', 'after']}; definition + full blocks + indicators "
          f"{c['three', 'before']} -> {c['three', 'after']} ({c['three', 'before'] / t:.3f} -> {c['three', 'after'] / t:.3f}); "
          f"complete {c['complete', 'before']} -> {c['complete', 'after']}")
    print("  filled, by the coverage before:", {k[1]: v for k, v in c.items() if k[0] == "filled"})
    for mode, lst in wrong.items():
        for how, clue, answer, b, truth in rng.sample(lst, min(show // 3, len(lst))):
            print(f"   miss [{mode}, {how}] {clue} = {answer}: {b[0]} from {b[1]!r}; truth {truth}")
    for pid, eid, clue, answer, d, blocks, new in rng.sample(sample, min(show, len(sample))):
        print(f"   read {pid} {eid} | {clue} = {answer} | def {d} blog {blocks} | + {new}")


def report_coverage(said):
    """What tools/data/blog_facts/ holds, as shares of every clue with a post:
    full blocks, the three parts, complete (see complete), and why the rest
    fall short of full blocks, largest first."""
    c, why = collections.Counter(), collections.Counter()
    for pid, eid, clue, answer, facts in rows(said, as_written=True):
        cov = coverage(answer, facts)
        t, lead = facts.get("type") or [], facts.get("leads")
        c["clues"] += 1
        c["full blocks"] += cov == "full"
        c["definition + full blocks + indicators"] += all_three(answer, facts)
        c["complete"] += complete(answer, facts)
        if cov != "full":
            why["no facts: clue not found in the post" if set(facts) <= {"leads"} and not lead
                else f"type with no blocks: {show(t)}" if cov == "n/a"
                else f"sounds, no letters: {show(t)}" if cov == "none" and ("homophone" in t or "spoonerism" in t)
                else "partial blocks" if cov == "partial" else "blocks spell too many letters" if cov == "excess"
                else "no blocks, no leads" if not lead else "no blocks, capitals printed" if lead.get("caps")
                else "no blocks, prose with no capitals"] += 1
    n = max(1, c["clues"])
    print(f"{c['clues']} clues with a post")
    for k in ("full blocks", "definition + full blocks + indicators", "complete"):
        print(f"  {k:40} {c[k]:8} {c[k] / n:6.1%}")
    print("not full blocks:")
    for k, v in why.most_common(12):
        print(f"  {k:40} {v:8} {v / n:6.1%}")


def measure_blockless(corpus, votes, n=4, show=30, seed=1):
    """Precision of what is read for hidden words, whose wordplay is no
    split of the answer: their carriers (infer_carrier) against our
    annotations, and on slice `n` of the puzzles, the lexicon built without
    them, their indicators with the blog's hidden."""
    ann = {}
    for path in puzzle_files():
        p = json.loads(path.read_text(encoding="utf-8"))
        for e in p.get("entries", []):
            if (e.get("annotation") or {}).get("blocks"):
                ann[p["id"], e["id"]] = e["annotation"]
    test = {pid for pid, *_ in corpus if in_slice(pid, n)}
    ilex = Indicators(corpus, skip=test, extra=annotation_rows())
    rng = random.Random(seed)
    c, wrong, sample = collections.Counter(), collections.defaultdict(list), collections.defaultdict(list)
    for pid, eid, clue, answer, facts in corpus:
        if not facts.get("type"):
            got = infer(clue, answer, {k: facts[k] for k in ("definition", "blocks") if k in facts}, votes)
            w = written(got.get("type")) if got else None
            facts = {**facts, "type": w[0]} if w else facts
        t, ours = facts.get("type") or [], ann.get((pid, eid))
        if tuple(t) in HIDDEN:
            new = infer_carrier(clue, answer, facts)
            whole = [b for b in (ours or {}).get("blocks", ()) if letters(b.get("gives") or "") == letters(answer)]
            if new and whole:
                ok = _key(new[0][1]) == _key(whole[0].get("clueFragment") or "")
                c["carrier", "claimed"] += 1
                c["carrier", "exact"] += ok
                if not ok:
                    wrong["carrier"].append((clue, answer, new[0][1], whole[0].get("clueFragment")))
            if new and pid in test and facts.get("definition"):
                hid = with_blocks({k: v for k, v in facts.items() if k != "indicators"}, new)
                got = infer_indicators(clue, answer, hid, ilex)
                if facts.get("indicators") and got:
                    ok = {_key(i) for i in texts(got)} == {_key(i) for i in texts(facts["indicators"])}
                    c["hidden indicators", "claimed"] += 1
                    c["hidden indicators", "exact"] += ok
                    if not ok:
                        wrong["hidden indicators"].append((clue, answer, got, facts["indicators"]))
                elif got:
                    sample["hidden indicators"].append((clue, answer, new[0][1], got))
        if len(t) == 1 and t[0] in FREE_WORDS_PARTS - {"hidden_word"} and facts.get("definition"):
            _measure_free_words(clue, answer, facts, votes, ilex, pid in test, ours, c, wrong, sample)
        new = facts.get("blocks") if t in SOUNDED and sounds_like(answer, facts.get("blocks") or ()) else None
        if new:  # the blog's own blocks, heard (blog_facts.heard_blocks)
            pairs = [(b[1], next(h["soundsLike"] for h in b[2:] if isinstance(h, dict))) for b in new]
            heard = [b for b in (ours or {}).get("blocks", ()) if b.get("soundsLike")]
            if heard:  # ours say what is heard, block by block
                src = lambda f: {w for _, w in words(f or "")}
                ok = letters("".join(h for _, h in pairs)) == letters("".join(b["soundsLike"] for b in heard)) \
                    and set().union(*(src(f) for f, _ in pairs)) == set().union(*(src(b.get("clueFragment")) for b in heard))
                c["heard", "claimed"] += 1
                c["heard", "exact"] += ok
                if not ok:
                    wrong["heard"].append((clue, answer, pairs, [(b.get("clueFragment"), b["soundsLike"]) for b in heard]))
            if pid in test:
                c["heard on the slice"] += 1
                sample["heard"].append((pid, eid, clue, answer, facts.get("definition"), facts.get("indicators"), pairs))
                if facts.get("definition"):
                    hid = {k: v for k, v in facts.items() if k != "indicators"}
                    got = infer_indicators(clue, answer, hid, ilex)
                    if facts.get("indicators") and got:
                        ok = {_key(i) for i in texts(got)} == {_key(i) for i in texts(facts["indicators"])}
                        c["heard indicators", "claimed"] += 1
                        c["heard indicators", "exact"] += ok
                        if not ok:
                            wrong["heard indicators"].append((clue, answer, got, facts["indicators"]))
                    elif got:
                        sample["heard indicators"].append((clue, answer, pairs, got))
                    c["heard and complete on the slice"] += complete(
                        answer, with_indicators(hid, got) if got else {**hid, "indicators": facts.get("indicators", [])})
    print(f"slice {n}: {len(test)} puzzles held out")
    free = [f"{t} free words{o}" for o in ("", ", ours") for t in sorted(FREE_WORDS_PARTS - {"hidden_word"})]
    for k in ("carrier", "hidden indicators", "heard", "heard indicators", *free):
        print(f"  {k:26} {c[k, 'claimed']:6} claimed, exact {c[k, 'exact'] / max(1, c[k, 'claimed']):.4f}"
              + (" against our annotations" if k in ("carrier", "heard") or k.endswith("ours") else ""))
    print(f"  heard on the slice {c['heard on the slice']}, and complete {c['heard and complete on the slice']}")
    for k, lst in wrong.items():
        for x in rng.sample(lst, min(show // 3, len(lst))):
            print(f"   miss [{k}]", x)
    for k, lst in sample.items():
        for x in rng.sample(lst, min(show // 2, len(lst))):
            print(f"   read [{k}]", x)


def _measure_free_words(clue, answer, facts, votes, ilex, held, ours, c, wrong, sample):
    """measure_blockless for an anagram's indicator read as its free words
    (free_words_indicator), where the lexicon reads none: on a `held` out
    clue against the blog's, hidden, and on a clue the blog named none for,
    against `ours`, our annotation's."""
    new = infer_fodder(clue, answer, facts, votes)
    facts = with_blocks(facts, new) if new else facts
    (part,) = facts["type"]
    if coverage(answer, facts) != "full" or needed(answer, facts["blocks"], facts["type"]) != {part}:
        return
    hid = {k: v for k, v in facts.items() if k != "indicators"}
    body, ws, at = spans(clue)
    taken = set()
    for phrase in hid["definition"] + [b[1] for b in hid["blocks"]]:
        taken |= locate(phrase, ws) or set()
    if _lexicon_indicator(ws, at, body, taken, part, ilex.less(clue, answer)) is not None:
        return
    got = infer_indicators(clue, answer, hid, ilex)
    if not got:
        return
    key = f"{part} free words"
    if facts.get("indicators"):
        truth = facts["indicators"]
        if not held:
            return
    elif (ours or {}).get("indicators"):
        truth, key = ours["indicators"], key + ", ours"
    else:
        if held:
            sample[key].append((clue, answer, hid["blocks"], got))
        return
    ok = {_key(i) for i in texts(got)} == {_key(i) for i in texts(truth)}
    c[key, "claimed"] += 1
    c[key, "exact"] += ok
    if not ok:
        wrong[key].append((clue, answer, got, truth))


def score_gold(votes):
    tally = collections.Counter()
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        g = r["gold"].get("type")
        got = infer(r["clue"], r["answer"], {k: r["gold"][k] for k in ("definition", "blocks") if r["gold"].get(k)}, votes)
        if not got or "undecided" in got:
            tally["none"] += 1
            continue
        tally["claimed"] += 1
        if set(got["type"]) == set(g or ()):
            tally["right"] += 1
        else:
            print(f"   gold [{show(g)}] {r['clue']} = {r['answer']}: claimed {show(got['type'])} ({got['why']})")
    print(f"gold rows: {sum(tally.values())}, claimed {tally['claimed']}, right {tally['right']}")


def fill(corpus, votes):
    counts, fields = collections.Counter(), collections.Counter()
    for pid, eid, clue, answer, facts in corpus:
        if facts.get("type"):
            continue
        known = {k: facts[k] for k in ("definition", "blocks") if k in facts}
        got = infer(clue, answer, known, votes)
        if not got:
            continue
        if "undecided" in got:
            counts["undecided: " + " | ".join(sorted({t for t, _ in got["undecided"]}))] += 1
            continue
        counts[show(got["type"])] += 1
        fields["indicators"] += bool(got.get("indicators")) and not facts.get("indicators")
        fields["fodder"] += bool(got.get("fodder"))
    for t, n in counts.most_common(60):
        print(f"{t:34} {n:8}")
    print(dict(fields))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--fill", action="store_true")
    ap.add_argument("--gold", action="store_true")
    ap.add_argument("--write", action="store_true",
                    help="add the TRUSTED types and the inferred blocks to tools/data/blog_facts/, marked inferred")
    ap.add_argument("--measure-blocks", type=int, nargs="?", const=0, metavar="SLICE",
                    help="precision of the inferred blocks on one puzzle in twenty (default slice %(const)s)")
    ap.add_argument("--measure-indicators", type=int, nargs="?", const=1, metavar="SLICE",
                    help="precision of the inferred indicators on one puzzle in twenty (default slice %(const)s)")
    ap.add_argument("--measure-definitions", type=int, nargs="?", const=1, metavar="SLICE",
                    help="precision of the inferred definitions on one puzzle in twenty (default slice %(const)s)")
    ap.add_argument("--measure-fuzzy-blocks", type=int, nargs="?", const=2, metavar="SLICE",
                    help="precision of the blocks read off the write-ups' prose on one puzzle in twenty "
                         "(default slice %(const)s)")
    ap.add_argument("--measure-blockless", type=int, nargs="?", const=4, metavar="SLICE",
                    help="precision of hidden words' carriers, homophones' and spoonerisms' heard blocks,"
                         " and their indicators (default slice %(const)s)")
    ap.add_argument("--lexicons", action="store_true",
                    help="write only the combined lexicons, as --write does, to tools/data/lexicons/")
    ap.add_argument("--coverage", action="store_true",
                    help="what the written blog facts cover, and why the rest fall short")
    ap.add_argument("--clue", nargs=2, metavar=("CLUE", "ANSWER"))
    ap.add_argument("--definition", action="append", default=[])
    ap.add_argument("--block", action="append", default=[], help="LETTERS=clue words")
    args = ap.parse_args()
    if args.clue:
        known = {"definition": args.definition, "blocks": [b.split("=", 1) for b in args.block]}
        print(json.dumps(infer(*args.clue, known), ensure_ascii=False))
        return
    os.nice(19)
    if args.coverage:
        report_coverage(read_leads(required=True))
        return
    corpus = list(rows(read_leads(required=args.write or args.measure_fuzzy_blocks is not None)))
    votes = indicator_votes(corpus)
    if args.gold:
        score_gold(votes)
    if args.measure:
        measure(corpus, votes, split="dev")
        measure(corpus, votes, show=0, split="held-out")
    if args.fill:
        fill(corpus, votes)
    if args.measure_blocks is not None:
        measure_blocks(corpus, args.measure_blocks)
    if args.measure_indicators is not None:
        measure_indicators(corpus, args.measure_indicators)
    if args.measure_definitions is not None:
        measure_definitions(corpus, args.measure_definitions)
    if args.measure_fuzzy_blocks is not None:
        measure_fuzzy_blocks(corpus, votes, args.measure_fuzzy_blocks)
    if args.measure_blockless is not None:
        measure_blockless(corpus, votes, args.measure_blockless)
    if args.lexicons:
        ours = list(annotation_rows())
        print(export_lexicons(Lexicon(corpus, extra=ours), Indicators(corpus, extra=ours)))
    if args.write:
        n = write(corpus, votes)
        print(f"inferred a type for {n['type']} clues, blocks for {n['blocks']}, a definition for "
              f"{n['definition']} and indicators for {n['indicators']} in {OUT.relative_to(ROOT)}; "
              f"{n['blocks.json']} block and {n['indicators.json']} indicator readings in {LEXICON_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
