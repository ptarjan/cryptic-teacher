#!/usr/bin/env python3
"""Clue types, fodder and indicators read off the letters, where the blog left them out.

Given the answer, the clue and what blog_facts.py already holds for it (the
definition, the blocks), some wordplay is a matter of arithmetic: a run of
clue words that is a permutation of the answer is anagram fodder, the answer
spelt across word boundaries is hidden, and blocks that put together make the
answer say how they were put together. Only a reading that is the one reading
the letters allow is kept.

    python3 tools/letter_facts.py --measure   # precision per type where the blog named it
    python3 tools/letter_facts.py --fill      # what it would add to untyped clues
    python3 tools/letter_facts.py --clue 'Men on phone exchange will be a rarity' PHENOMENON
"""
import argparse
import collections
import functools
import itertools
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from blog_facts import ABBR, GOLD, OUT, PART_ORDER, clue_body, fold

PUZZLES = ROOT / "puzzles"
WORD = re.compile(r"[\w'’\-]+")
#: A hidden answer shorter than this turns up by chance in too many clues.
MIN_HIDDEN = 4
#: Nor is an anagram of fewer letters worth a claim: ERA in "are" is as often a literal.
MIN_ANAGRAM = 4
#: An indicator is a phrase blogs have named for that part in this many clues.
MIN_INDICATOR = 3
#: A spoonerism swaps sounds, so its letters look like an anagram's.
SPOONER = re.compile(r'\bspooner', re.I)
#: What a reading costs: of two that spell the answer, the one with fewer of
#: these is the setter's, as S+CORE+R is a charade and not CORES anagrammed round R.
OPERATIONS = {"anagram", "container", "reversal", "hidden word", "hidden word + reversal"}
#: A cut takes at most this many letters from a word: "endlessly", "heartless".
MAX_CUT = 2
#: The most blocks put together; more is a blog listing alternatives.
MAX_BLOCKS = 5


def letters(s):
    return "".join(f for f in map(fold, s) if f.isalnum() and f.isascii()).upper()


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
    return " + ".join(p for p in PART_ORDER if p in parts) or None


# ------------------------------------------------------------ blocks

def cut(w, bl):
    """Whether `bl` is `w` with one run of at most MAX_CUT letters taken out."""
    return 0 < len(w) - len(bl) <= MAX_CUT and any(
        w[:i] + w[i + len(w) - len(bl):] == bl for i in range(len(bl) + 1))


def derivation(bl, src):
    """The parts a block's letters say it was taken from its clue words by:
    set() for a synonym, literal or abbreviation, {'first letter'} and the
    like for a selection or cut, None when the letters allow two.

    A selection or cut needs a word to say so, so it is read only off a
    source of two or more words: Y from "Yokohama" is an abbreviation, D
    from "Delius' overture" a first letter. A lone word cut short (MARC
    from "March") is the exception: no abbreviation drops a letter or two."""
    sw = [letters(w) for w in WORD.findall(src or "") if letters(w)]
    if len(sw) == 1 and len(bl) >= 3 and cut(sw[0], bl):
        return {"deletion"}
    if len(sw) < 2 or bl == "".join(sw) or bl.lower() in ABBR and src.lower().strip() in ABBR[bl.lower()]:
        return set()
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
    return cands if len(cands) <= 1 else None


def match(seg, piece):
    """How `piece` gives the letters `seg`: as itself, reversed or anagrammed."""
    if seg == piece:
        return frozenset()
    if seg == piece[::-1]:
        return frozenset({"reversal"})
    if len(piece) >= 3 and sorted(seg) == sorted(piece):
        return frozenset({"anagram"})
    return None


def parses(answer, pieces):
    """Every set of parts by which all of `pieces` spell `answer`: each piece
    in one stretch, or around the pieces inside it (a container), each
    literal, reversed or anagrammed; two or more side by side are a charade."""
    everything = frozenset(range(len(pieces)))

    @functools.lru_cache(maxsize=None)
    def fill(lo, hi, avail):
        if lo == hi:
            return {(frozenset(), frozenset(), 0)}
        out = set()
        for i in avail:
            s, n, rest = pieces[i], len(pieces[i]), avail - {i}
            if lo + n <= hi and (m := match(answer[lo:lo + n], s)) is not None:
                out |= {(u | {i}, p | m, k + 1) for u, p, k in fill(lo + n, hi, rest)}
            for a in range(1, n):
                for mid in range(lo + a + 1, hi - (n - a) + 1):
                    m = match(answer[lo:lo + a] + answer[mid:mid + n - a], s)
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
    """(type, fodder word indices, why) for every way the letters allow."""
    out = []
    if not blocks and len(answer) >= MIN_HIDDEN:
        for run, rev in hidden(answer, ws, free):
            out.append(("hidden word + reversal" if rev else "hidden word", run,
                        f"{'reversed ' if rev else ''}{answer} is spelt in {' '.join(ws[k][0] for k in run)!r}"))
    derived = set()
    for bl, src in blocks:
        d = derivation(bl, src)
        if d is None:
            return [("undecided block", (), f"{bl} from {src!r} is more than one selection")]
        derived |= d
    need = collections.Counter(answer)
    for pieces, parts in deleted([b for b, _ in blocks]) if len(blocks) <= MAX_BLOCKS else ():
        gap = len(answer) - sum(map(len, pieces))
        runs = [((), "")] if gap == 0 else [
            (r, s) for r, s in free_runs(ws, free) if len(s) == gap
            and collections.Counter(s) + collections.Counter("".join(pieces)) == need]
        for run, fod in runs:
            if fod and len(fod) < 3 and fod != answer[::-1] and fod not in answer:
                continue
            got = parses(answer, list(pieces) + ([fod] if fod else []))
            src = f"{' '.join(ws[k][0] for k in run)!r}" if run else ""
            what = " + ".join(filter(None, [src, "+".join(b for b, _ in blocks)]))
            if not got and len(pieces) + bool(fod) > 1 and collections.Counter(fod + "".join(pieces)) == need:
                got = {frozenset({"anagram"})}
            for p in got:
                if p | parts | derived:
                    out.append((type_name(p | parts | derived), run, f"{what} make {answer}"))
    if blocks and not out and len(answer) >= MIN_ANAGRAM:
        extra = collections.Counter("".join(b for b, _ in blocks))
        for run, s in free_runs(ws, free):
            c = collections.Counter(s)
            if len(s) > len(answer) and c - extra == need and extra - c == collections.Counter():
                out.append(("subtractive anagram", run, f"{' '.join(ws[k][0] for k in run)!r} less the blocks has the letters of {answer}"))
    return [r for r in out if not (r[0] == "anagram" and len(answer) < MIN_ANAGRAM)]


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
    for bl, src in known.get("blocks", []):
        taken |= locate(src, ws) or set()
        blocks.append((letters(bl), src))
    free = set(range(len(ws))) - taken
    rs = readings(answer, ws, free, [b for b in blocks if b[0]])
    if not rs:
        return None
    cost = lambda t: len(set(t.split(" + ")) & OPERATIONS)
    least = min(cost(t) for t, _, _ in rs)
    rs = [r for r in rs if cost(r[0]) == least]
    types = {t for t, _, _ in rs}
    if len(types) > 1 or types & {"undecided block", "subtractive anagram"}:
        return {"undecided": sorted({(t, " ".join(ws[k][0] for k in run)) for t, run, _ in rs}),
                "why": rs[0][2]}
    t = rs[0][0]
    out = {"type": t, "why": rs[0][2]}
    runs = {run for _, run, _ in rs}
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
    parts = set(t.replace("hidden word", "hidden").split(" + "))
    near = set()
    for k in fodder:
        near |= {k - 3, k - 2, k - 1, k + 1, k + 2, k + 3}
    out, used = [], set()
    for n in (3, 2, 1):
        for i in range(len(ws) - n + 1):
            span = set(range(i, i + n))
            if not span <= free or span & used or (fodder and not span & near):
                continue
            phrase = " ".join(w[0] for w in ws[i:i + n]).lower().replace("’", "'")
            votes = lexicon.get(phrase)
            if votes and sum(votes[p] for p in parts) >= MIN_INDICATOR \
                    and max(votes, key=votes.get) in parts:
                out.append((i, " ".join(w[0] for w in ws[i:i + n])))
                used |= span
    return [p for _, p in sorted(out)]


# ------------------------------------------------------------ corpus

def rows():
    """(puzzle id, entry id, clue, answer, blog facts) for every clue blog_facts holds."""
    for f in sorted(OUT.glob("*.json")):
        for pid, rec in json.loads(f.read_text(encoding="utf-8")).items():
            path = PUZZLES / f"{pid}.json"
            if not path.exists():
                continue
            ents = {e["id"]: e for e in json.loads(path.read_text(encoding="utf-8"))["entries"]}
            for eid, facts in rec["entries"].items():
                e = ents.get(eid)
                if e and e.get("solution") and e.get("clue"):
                    yield pid, eid, e["clue"], e["solution"], facts


def indicator_votes(corpus):
    """Indicator phrase -> Counter of the type parts of the clues blogs named it in."""
    votes = collections.defaultdict(collections.Counter)
    for *_, facts in corpus:
        if facts.get("type") and facts.get("indicators"):
            parts = facts["type"].replace("hidden word", "hidden").split(" + ")
            for i in facts["indicators"]:
                for p in parts:
                    votes[i.lower().replace("’", "'")][p] += 1
    return votes


def without(votes, facts):
    """`votes` less this clue's own contribution, so a clue never confirms itself."""
    if not (facts.get("type") and facts.get("indicators")):
        return votes
    own = {i.lower().replace("’", "'") for i in facts["indicators"]}
    parts = facts["type"].replace("hidden word", "hidden").split(" + ")

    class Minus(dict):
        def get(self, k, d=None):
            v = votes.get(k)
            if v is None or k not in own:
                return v
            v = collections.Counter(v)
            for p in parts:
                v[p] -= 1
            return +v
    return Minus()


#: The parts a blog names or leaves out by habit: how a block was taken from its words.
TAKEN = {"deletion", "first letter", "first letters", "last letter", "last letters", "middle letter",
         "middle letters", "outer letters", "alternate letters"}


def core(t):
    """A type less the parts that say how blocks were taken from their words."""
    return frozenset(t.split(" + ")) - TAKEN


def measure(corpus, votes, show=8):
    tally = collections.defaultdict(collections.Counter)
    fps = collections.defaultdict(list)
    undecided = collections.defaultdict(list)
    blog_types = collections.Counter()
    ind = collections.Counter()
    for pid, eid, clue, answer, facts in corpus:
        gold = facts.get("type")
        if not gold:
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
        t = got["type"]
        tally[t]["claimed"] += 1
        if t == gold:
            tally[t]["right"] += 1
        if core(t) == core(gold):
            tally[t]["core"] += 1
        if t != gold:
            fps[t].append((gold, clue, answer, got))
        if facts.get("indicators") and got.get("indicators"):
            g = {w for i in facts["indicators"] for w in re.findall(r"[\w'’]+", i.lower())}
            p = {w for i in got["indicators"] for w in re.findall(r"[\w'’]+", i.lower())}
            ind["tp"] += len(g & p)
            ind["fp"] += len(p - g)
            ind["fn"] += len(g - p)
    print(f"{'type':34} {'claimed':>8} {'right':>7} {'prec':>6} {'core':>6} {'blog':>7} {'cover':>6}")
    for t, c in sorted(tally.items(), key=lambda kv: -kv[1]["claimed"]):
        if not c["claimed"]:
            continue
        print(f"{t:34} {c['claimed']:8} {c['right']:7} {c['right'] / c['claimed']:6.3f} {c['core'] / c['claimed']:6.3f} "
              f"{blog_types[t]:7} {c['right'] / max(1, blog_types[t]):6.3f}")
    print(f"undecided: {sum(c['undecided'] for c in tally.values())}")
    if ind["tp"] + ind["fp"]:
        print(f"indicator words where the blog named some: P {ind['tp'] / (ind['tp'] + ind['fp']):.3f} "
              f"R {ind['tp'] / (ind['tp'] + ind['fn']):.3f} ({ind['tp']} tp, {ind['fp']} fp)")
    for k, lst in sorted(undecided.items(), key=lambda kv: -len(kv[1]))[:15]:
        print(f"\n-- undecided between {k} ({len(lst)}); blog said", collections.Counter(g for g, *_ in lst).most_common(5))
        for g, clue, answer, got in lst[:4]:
            print(f"   [{g}] {clue} = {answer}: {got['undecided']}")
    for t, lst in fps.items():
        print(f"\n-- claimed {t}, blog said otherwise ({len(lst)}):")
        print("   blog types:", collections.Counter(g for g, *_ in lst).most_common(6))
        lst.sort(key=lambda r: core(r[0]) == core(t))
        for g, clue, answer, got in lst[:show] + lst[-(show // 2):]:
            print(f"   [{g}] {clue} = {answer}: {got.get('why')}")


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
        if set(got["type"].split(" + ")) == set((g or "").split(" + ")):
            tally["right"] += 1
        else:
            print(f"   gold [{g}] {r['clue']} = {r['answer']}: claimed {got['type']} ({got['why']})")
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
        counts[got["type"]] += 1
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
    ap.add_argument("--clue", nargs=2, metavar=("CLUE", "ANSWER"))
    ap.add_argument("--definition", action="append", default=[])
    ap.add_argument("--block", action="append", default=[], help="LETTERS=clue words")
    args = ap.parse_args()
    if args.clue:
        known = {"definition": args.definition, "blocks": [b.split("=", 1) for b in args.block]}
        print(json.dumps(infer(*args.clue, known), ensure_ascii=False))
        return
    os.nice(19)
    corpus = list(rows())
    votes = indicator_votes(corpus)
    if args.gold:
        score_gold(votes)
    if args.measure:
        measure(corpus, votes)
    if args.fill:
        fill(corpus, votes)


if __name__ == "__main__":
    main()
