#!/usr/bin/env python3
"""Write tools/data/wordnet.json.gz: the part of WordNet tools/difficulty.py's
definition_unrelated component reads.

    python3 -m pip install --user nltk && python3 -c 'import nltk; nltk.download("wordnet")'
    python3 tools/build_wordnet.py

Only this builder needs nltk. The file is committed, like lexicon.tsv, so a
rating never depends on whether the machine scoring it has WordNet installed.

It holds, for every word in the lexicon and in the corpus's answers and
definitions, the synsets WordNet finds for it (base forms included, so
"lines" finds "line"), and for every synset those reach: its hypernyms,
whether it sits near the root, and for a word's own synsets the one-step
neighbours difficulty.near_synsets() follows and the gloss words a clue could
match (those in the vocabulary). No lemma names: a word that names a synset
already finds it through its own synsets.
"""
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D  # noqa: E402
from fetch_puzzle import puzzle_files, read_puzzle_file  # noqa: E402
from nltk.corpus import wordnet as wn  # noqa: E402


def vocabulary():
    with D.LEXICON.open(encoding="utf-8") as fh:
        words = {line.split("\t", 1)[0].lower() for line in fh if not line.startswith("#")}
    blog = D.blog_definitions()
    for path in puzzle_files():
        puz = read_puzzle_file(path)
        bd = blog.get(puz["id"], {})
        for e in puz["entries"]:
            _, ws = D.answer_words(e)
            if ws:
                words.add("_".join(w.lower() for w in ws))
                words.update(w.lower() for w in ws)
            d = bd.get(e.get("id")) or D.definition_key((e.get("annotation") or {}).get("definition"))
            if d:
                words.update(d.split())
    return {w for w in words if re.fullmatch(r"[a-z_]+", w)}


def synsets(phrase):
    out = set(wn.synsets(phrase))
    if "_" not in phrase:
        for pos in ("n", "v", "a", "r"):
            m = wn.morphy(phrase, pos)
            if m:
                out.update(wn.synsets(m, pos))
    return out


def neighbours(s):
    out = set(s.hyponyms() + s.similar_tos() + s.also_sees() + s.verb_groups()
              + s.member_holonyms() + s.part_holonyms())
    for lem in s.lemmas():
        out.update(d.synset() for d in lem.derivationally_related_forms())
        out.update(p.synset() for p in lem.pertainyms())
    return out


def main():
    vocab = vocabulary()
    words = {}
    for w in sorted(vocab):
        ss = synsets(w)
        if ss:
            words[w] = ss
    # Everything a lookup can reach: a word's synsets, their neighbours, and
    # their hypernyms up to near_synsets()'s depth.
    need = set().union(*words.values())
    frontier = set(need)
    for s in list(need):
        frontier |= neighbours(s)
    reach = set(frontier)
    level = set(need)
    for _ in range(D.HYPERNYM_DEPTH):
        level = {h for s in level for h in s.hypernyms() + s.instance_hypernyms()} - reach
        reach |= level
    order = sorted(reach, key=lambda s: s.name())
    ix = {s: i for i, s in enumerate(order)}
    rows = []
    for s in order:
        full = s in need
        rows.append([
            " ".join(sorted(set(re.findall(r"[a-z]+", s.definition().lower())) & vocab)) if full else "",
            sorted(ix[h] for h in s.hypernyms() if h in ix),
            sorted(ix[h] for h in s.instance_hypernyms() if h in ix),
            sorted(ix[n] for n in neighbours(s) if n in ix) if full else [],
            int(s.min_depth() <= D.GENERIC_DEPTH),
        ])
    data = {"_comment": "Written by tools/build_wordnet.py from WordNet "
                        f"{wn.get_version()} (Princeton WordNet licence). Rows: "
                        "[gloss words, hypernyms, instance hypernyms, neighbours, generic].",
            "words": {w: sorted(ix[s] for s in ss) for w, ss in words.items()},
            "synsets": rows}
    raw = json.dumps(data, separators=(",", ":")).encode()
    D.WORDNET.write_bytes(gzip.compress(raw, 9, mtime=0))
    print(f"{len(words)} words, {len(rows)} synsets, "
          f"{D.WORDNET.stat().st_size / 1e6:.2f} MB ({len(raw) / 1e6:.1f} MB unpacked)")


if __name__ == "__main__":
    main()
