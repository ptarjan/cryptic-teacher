#!/usr/bin/env python3
"""Count the words and word pairs of every clue in the corpus, and its answers.

    python3 tools/build_clue_lm.py      # rewrites tools/data/clue_lm.tsv.gz

tools/file_archive_org_puzzles.py reads scanned clues with several OCR
readers; where they differ, the puzzles we already have say which reading
a clue setter would print. Each row is "word<TAB>count" (a word of the
clues, lower case), "word word<TAB>count" (two words in a row in a clue,
kept when seen twice) or "=answer-word<TAB>count" (a word of an answer,
from its enumeration's split; names like Hornblower). Puzzles sharing
three clues with tools/data/archive_org_ocr_gold.json are left out, so the
gold transcriptions never score themselves.
"""
import collections
import glob
import gzip
import json
import re
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
OUT = TOOLS / "data" / "clue_lm.tsv.gz"
GOLD = TOOLS / "data" / "archive_org_ocr_gold.json"
WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
#: Pairs seen fewer times than this are dropped (they are mostly one clue).
PAIR_FLOOR = 2


def words(text):
    return WORD.findall(text.lower().replace("’", "'"))


def answer_words(entry):
    sol = re.sub(r"[^A-Za-z]", "", entry.get("solution") or "").lower()
    enum = (entry.get("clue") or {}).get("enumeration") or ""
    sizes = [int(n) for n in re.findall(r"\d+", enum)]
    if not sol or sum(sizes) != len(sol):
        return [sol] if sol else []
    out, at = [], 0
    for n in sizes:
        out.append(sol[at:at + n])
        at += n
    return out


def counts(root=ROOT, gold=GOLD):
    held = {" ".join(words(t)) for ed in json.loads(gold.read_text())
            for t in ed["clues"].values() if t}
    uni, pair, ans = collections.Counter(), collections.Counter(), collections.Counter()
    for path in glob.glob(str(root / "puzzles" / "*" / "*" / "*.json")):
        try:
            entries = json.loads(Path(path).read_text()).get("entries", ())
        except (OSError, ValueError):
            continue
        texts = [words((e.get("clue") or {}).get("text") or "") for e in entries]
        if sum(" ".join(t) in held for t in texts if len(t) > 2) >= 3:
            continue
        for t in texts:
            uni.update(t)
            pair.update(zip(t, t[1:]))
        for e in entries:
            ans.update(answer_words(e))
    return uni, pair, ans


def main():
    uni, pair, ans = counts()
    rows = [f"{w}\t{n}" for w, n in sorted(uni.items())]
    rows += [f"{a} {b}\t{n}" for (a, b), n in sorted(pair.items()) if n >= PAIR_FLOOR]
    rows += [f"={w}\t{n}" for w, n in sorted(ans.items()) if len(w) > 1]
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as f:
        f.write("# clue word / pair / =answer word\tcount  (tools/build_clue_lm.py)\n")
        f.write("\n".join(rows) + "\n")
    print(f"{OUT}: {len(uni)} words, {sum(n >= PAIR_FLOOR for n in pair.values())} pairs, "
          f"{len(ans)} answer words")


if __name__ == "__main__":
    main()
