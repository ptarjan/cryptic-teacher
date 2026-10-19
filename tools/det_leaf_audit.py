#!/usr/bin/env python3
"""Why does the corpus leaf table miss a held-out leaf?  python3 tools/det_leaf_audit.py [--show N]

For the 500 held-out Times test clues (same sample and hold-out as `det_solve.py measure`), every non-literal leaf
(words -> gives, not under anagram/hidden/homophone/selection) the leaf table cannot give by exact lookup lands in one bucket:
  key_mismatch   the pair is in the table, but under another spelling of the key than the one the clue lookup builds
  walk_skipped   the pair is in the corpus outside the held-out clues, but build_tables/walk() did not record it
  held_out_only  the pair is in the corpus only under held-out clues (test clues, or clues sharing a test answer)
  words_not_in_clue  the leaf's words are not a contiguous run of the clue's words (annotation oddity)
  unseen_key     the words never occur as a leaf anywhere (even held out)
  unseen_pair    the words occur with other gives, never with this one
"""
import argparse
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import det_solve as D  # noqa: E402
import det_synonyms  # noqa: E402

SEL = D.SELECT_KINDS


def raw_leaves(node, parent=None, out=None):
    """Every leaf with words and gives: (words, gives, parent op, unchecked)."""
    if out is None:
        out = []
    if node.get("op") is None:
        if node.get("words") and node.get("gives"):
            out.append((node["words"], D.letters(node["gives"]), parent, bool(node.get("unchecked"))))
        return out
    for p in node.get("parts", []):
        raw_leaves(p, node.get("op"), out)
    return out


def skip_reason(words, gives, parent, unchecked):
    if D.letters(words) == gives:
        return "literal"
    if parent in ("anagram", "hidden", "homophone"):
        return "under " + parent
    if parent in SEL:
        return "under selection"
    if unchecked:
        return "unchecked"
    return "recorded"


def audit(show=0):
    rows = D.load_corpus()
    pids, test = D.sample_clues(rows, 30, 500, 7)
    held = {r["answer"] for r in test}
    tab = D.build_tables(rows, set(), held)
    train_raw = collections.defaultdict(collections.Counter)    # (key, gives) -> skip reasons, outside held-out
    all_raw = set()
    where = {}
    old_pairs = set()          # what the tables held before this change: the old key spelling, the old walk() filter
    leaves = []
    keys_any = collections.defaultdict(set)
    for r in rows:
        for w, g, par, unc in raw_leaves(r["tree"]):
            k = D.norm(w)
            all_raw.add((k, g))
            where.setdefault((k, g), set()).add((r["pid"], r["num"], r["dir"]))
            if r["answer"] not in held:
                keys_any[k].add(g)
                train_raw[(k, g)][skip_reason(w, g, par, unc)] += 1
                if not unc and par not in ("anagram", "hidden", "homophone") and par not in SEL and D.letters(w) != g:
                    old_pairs.add((old_norm(w), g))
    rev = collections.defaultdict(set)         # letters of a table key -> the keys, for the backwards check
    for words in tab["syn"]:
        rev[D.letters(words)].add(words)
    buckets = collections.Counter()
    examples = collections.defaultdict(list)
    total = 0
    for r in test:
        ctoks = D.tokens(r["clue"])
        for w, g, par, unc in raw_leaves(r["tree"]):
            if skip_reason(w, g, par, unc) not in ("recorded", "unchecked"):
                continue
            total += 1
            k = D.norm(w)
            leaves.append((k, g))
            ck = " ".join(D.tokens(w))
            if g in tab["syn"].get(k, {}):
                b = "hit"
            elif g in tab["syn"].get(ck, {}):
                b = "key_mismatch"
            elif (k, g) in train_raw and "recorded" not in train_raw[(k, g)]:
                b = "walk_skipped:" + "/".join(sorted(train_raw[(k, g)]))
            elif (k, g) in train_raw:
                b = "key_mismatch"
            elif len(where.get((k, g), ())) > 1:
                b = "held_out_only(other clue sharing a test answer)"
            else:
                wt = D.tokens(w)
                inclue = any(ctoks[i:i + len(wt)] == wt for i in range(len(ctoks)))
                b = ("words_not_in_clue" if not inclue else "unseen_key" if k not in keys_any else "unseen_pair")
                kt = k.split()
                var = {" ".join(kt[1:]), " ".join(kt[:-1]), k.rstrip("s"), k + "s", k.replace("'s", "")}
                if any(g in tab["syn"].get(v, {}) for v in var if v and v != k):
                    b += ":variant_key_has_it"
                elif any(D.letters(w) in tab["syn"][x] for x in rev.get(g, ())):
                    b += ":reverse_has_it"
            buckets[b] += 1
            if len(examples[b]) < show:
                examples[b].append((r["clue"], w, g))
    print("test leaves (non-literal, recorded kind):", total)
    for b, c in buckets.most_common():
        print(f"  {b:34s} {c:5d} {100 * c / total:5.1f}%")
    for b, ex in examples.items():
        print("--", b)
        for e in ex:
            print("   ", e)
    res = D.Resources({r["answer"] for r in rows if r["answer"] not in held})
    sd = det_synonyms.get_sd(tab, res)
    n, srows, old = det_synonyms.coverage(sd, leaves)
    old_tab = sum(1 for k, g in leaves if (k, g) in old_pairs)
    old_all = sum(1 for k, g in leaves if (k, g) in old_pairs or g in res.abbr.get(k, []) or g in res.wn_synonyms(k))
    print(f"\nleaf coverage over {n} test leaves")
    print(f"  BEFORE leaf table as the search reached it: {old_tab} = {100 * old_tab / n:.1f}%; "
          f"with abbreviations and wn_synonyms: {old_all} = {100 * old_all / n:.1f}%")
    print(f"  {'source':12s} {'alone':>12s} {'new vs earlier sources':>24s} {'cumulative':>14s}")
    for s, alone, new, cum in srows:
        print(f"  {s:12s} {alone:5d} {100 * alone / n:5.1f}% {new:+10d} {100 * new / n:+6.1f}% {cum:8d} {100 * cum / n:5.1f}%")


def old_norm(s):
    s = (s or "").lower().replace("’", "'")
    return " ".join(re.findall(r"[a-z0-9'\-]+", s))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=0)
    audit(ap.parse_args().show)
