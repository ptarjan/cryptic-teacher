#!/usr/bin/env python3
"""Warn about the clue shapes that lose to human setters in blind grading.

tools/validate_annotations.py proves a clue is *sound*. Blind grading against
published clues showed soundness is not the problem — we scored +0.72 on fairness
and still lost overall, because we scored -1.21 on misdirection and -0.98 on
penny-drop. The clues were correct and lifeless.

This tool cannot see wit; nothing can. What it can see is the *shape* that
lifeless clues share, which turned out to be strikingly consistent across our six
worst-scoring clues: the parts of the mechanism listed in order, joined by a
comma or a copula, with no sentence wrapped around them.

  Later rewritten, to change          (2.47/5 — fodder, indicator, definition)
  Cold heap is inexpensive            (2.33/5 — part + part IS definition)
  Identity tucked into southeast      (2.80/5 — pure assembly instructions)

Every warning here is a smell, not an error. Exit status is 0 either way — this
informs the setter, it does not block the build.

How well each check actually predicts a judge's score, measured on the 20 clues
of A001 (mean judge score when the check fires, minus when it does not):

    copula-definition        -0.46   (fired on 2)
    indicator-abuts-fodder   -0.45   (fired on 4)
    terse                    -0.27   (fired on 10)
    fenced-definition        +0.16   (fired on 3)
    stock-indicator          +1.22   (fired on 1)

Only the first three point the way they were designed to, and n=20 clues judged
by 3 judges is far too small to call any of them established. The last two are
currently evidence *against* themselves — `stock-indicator` fired once, on our
single best clue. They are kept because the reasoning behind them is sound and
one clue cannot refute it, but do not treat them as authority. Re-run this table
after the next graded puzzle; a check that keeps pointing the wrong way should be
deleted, not defended.

  python3 tools/clue_quality.py tools/data/authored_A001_clues.json
"""

import argparse
import json
import re
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = Path.home() / "cryptic-setter-data" / "georgeho" / "data.db"

# Verbs that bolt a definition onto assembled wordplay. Real setters use these
# too, but as part of a sentence that means something; when one sits exactly at
# the seam between wordplay and definition it is doing no surface work at all.
COPULAS = r"(?:is|are|was|were|gives|makes|means|provides|produces|becomes|yields)"

# How rare an indicator has to be before it stops shouting. Published setters use
# 92% of their indicators exactly once; ours clustered in the top few percent by
# frequency, which is why judges could see the mechanism coming.
STOCK_PERCENTILE = 0.02


def words(clue):
    return re.findall(r"[A-Za-z']+", clue)


def strip_enum(clue):
    return re.sub(r"\s*\([\d,\-\s]+\)\s*$", "", clue).strip()


def load_corpus_norms(path):
    """Median clue length by answer length, and indicator frequencies."""
    if not Path(path).exists():
        return None
    db = sqlite3.connect(path)
    lengths = {}
    for ans, clue in db.execute(
        "select answer, clue from clues where answer is not null "
        "and length(answer) between 3 and 12 limit 120000"
    ):
        n = len("".join(c for c in ans if c.isalpha()))
        lengths.setdefault(n, []).append(len(words(strip_enum(clue))))
    median_words = {n: statistics.median(v) for n, v in lengths.items() if len(v) > 50}

    freq = {}
    for (ind,) in db.execute("select indicator from indicators"):
        if ind:
            freq[ind.strip().lower()] = freq.get(ind.strip().lower(), 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: -kv[1])
    cutoff = max(1, int(len(ranked) * STOCK_PERCENTILE))
    stock = {w for w, _ in ranked[:cutoff]}
    return {"median_words": median_words, "stock": stock, "known": set(freq)}


def check(eid, spec, norms):
    """Return a list of (code, message) smells for one clue."""
    clue = strip_enum(spec["clue"])
    ann = spec.get("annotation", {})
    out = []
    ws = words(clue)
    lower = clue.lower()
    definition = (ann.get("definition") or "").strip()

    # 1. Definition welded on with a copula, at the seam of the wordplay.
    if definition:
        d = re.escape(definition.lower())
        if re.search(rf"\b{COPULAS}\s+(?:an?\s+|the\s+)?{d}\b", lower):
            out.append(("copula-definition",
                        f"'{definition}' is bolted on with a copula; the clue "
                        f"states its own answer rather than describing a scene"))

    # 2. Definition fenced off by punctuation — the giveaway of a parts list.
    for chunk in re.split(r"\s*[,:;]\s*", lower):
        c = re.sub(r"^(?:to|a|the|an)\s+", "", chunk).strip()
        if definition and c == definition.lower():
            out.append(("fenced-definition",
                        f"'{definition}' sits alone behind punctuation, so the "
                        f"surface never has to accommodate it"))
            break

    # 3. Anagram indicator jammed against its own fodder.
    fodder = ((ann.get("anagram") or {}).get("fodder") or "").strip()
    if fodder:
        for ind in ann.get("indicators") or []:
            pat = rf"\b{re.escape(fodder.lower())}\s+{re.escape(ind.lower())}\b|" \
                  rf"\b{re.escape(ind.lower())}\s+{re.escape(fodder.lower())}\b"
            if re.search(pat, lower):
                out.append(("indicator-abuts-fodder",
                            f"'{ind}' sits directly against '{fodder}', which "
                            f"points at the anagram instead of hiding it"))
                break

    if norms:
        # 4. Stock indicators. Rarity is the cheapest misdirection there is.
        for ind in ann.get("indicators") or []:
            k = ind.strip().lower()
            if k in norms["stock"]:
                out.append(("stock-indicator",
                            f"'{ind}' is one of the most-used indicators in the "
                            f"corpus; solvers read it as a signpost"))

        # 5. Too short to carry a picture. Not a rule against brevity — a rule
        #    against having no room for a surface idea.
        n = len("".join(c for c in ann.get("answer", "") if c.isalpha()))
        med = norms["median_words"].get(n)
        if med and len(ws) < med - 1:
            out.append(("terse",
                        f"{len(ws)} words against a published median of "
                        f"{med:.0f} for {n}-letter answers; there may be no room "
                        f"for a surface"))

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clues", nargs="?",
                    default="tools/data/authored_A001_clues.json")
    ap.add_argument("--corpus", default=str(CORPUS))
    args = ap.parse_args()

    path = Path(args.clues)
    if not path.is_absolute():
        path = ROOT / path
    data = json.loads(path.read_text())
    norms = load_corpus_norms(args.corpus)
    if norms is None:
        print(f"note: no corpus at {args.corpus} — skipping frequency and "
              f"length checks", file=sys.stderr)

    flagged = 0
    total = 0
    for eid, spec in sorted(data.items()):
        if eid.startswith("_"):
            continue
        total += 1
        smells = check(eid, spec, norms)
        if not smells:
            continue
        flagged += 1
        print(f"\n{eid}: {spec['clue']}")
        for code, msg in smells:
            print(f"  [{code}] {msg}")

    print(f"\n{flagged}/{total} clues carry at least one smell.")
    print("These are smells, not errors. Three on one clue means it is a list "
          "of parts wearing a sentence's clothes.")


if __name__ == "__main__":
    main()
