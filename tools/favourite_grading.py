#!/usr/bin/env python3
"""Ask whether a judge's read of a clue predicts which clue solvers voted for.

tools/craft_report.py measures what arithmetic can see — device mix, repeated
indicators, entry lengths — and every one of those observations is a null
against the favourite-clue votes. That is not surprising: the four properties
fifteensquared commenters actually name (surface reading, cleverness, humour,
the penny-drop) are judgements about language, and none of them are in our
fields. This asks the obvious next question. A judge model *can* read a clue.
Does its reading predict the vote?

The design is matched pairs, one per puzzle: a clue that was named a favourite
against a clue from the same puzzle that was not. That is not a convenience,
it is the whole point. The share of a puzzle's clues that get named correlates
+0.833 with the size of the comment thread, so any test that compares puzzles
to each other is mostly measuring how many people turned up. Comparing two
clues from inside one thread holds the audience fixed by construction.

The two clues in a pair are matched on solution length, which is a fact about
the grid rather than about the writing. Matching on clue word count instead
would have been a mistake: named clues run longer (7.11 words to 6.78,
p = 0.0003), so matching that away would erase a real difference. Solution
length only removes the short-entry effect, which is a slot the setter was
handed, not a choice they made.

Blindness works the way tools/grade_clues.py established: the judge sees clue,
enumeration and solution in a globally shuffled flat list, never the vote, never
the puzzle, never which two clues are a pair. The key stays on this side of the
wall until --score. The axes are the five tools/score_grading.py already uses,
so a score here means what it meant there.

  python3 tools/favourite_grading.py --sample --votes /tmp/favourite_votes.json \
      --out tools/data/favourite_grading
  # grade every batch into <out>/scores/<batch>.json, then
  python3 tools/favourite_grading.py --score --out tools/data/favourite_grading

What a result looks like: per axis, the share of pairs where the voted clue
scored higher, tested against 50%. Ties are dropped and reported, because a
judge that scores everything 4 has an accuracy of 50% for a reason that has
nothing to do with clues.
"""

import argparse
import json
import pathlib
import random
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from difficulty import load  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUZZLE_DIR = ROOT / "puzzles"
AXES = ["surface", "misdirection", "pennydrop", "economy", "fairness"]
BATCH = 20
SEED = 20260909


def annotated_entries(puz):
    """Entries with a clue, a solution and an annotation - the ones a judge can read."""
    return [e for e in puz.get("entries", [])
            if e.get("clue") and e.get("solution") and e.get("annotation")]


def build_pairs(votes, rng):
    """One (voted, unvoted) pair per puzzle, matched on solution length."""
    voted = {}
    for v in votes:
        voted.setdefault(v["puzzle"], set()).add(v["entry"])

    pairs, skipped = [], []
    for pid in sorted(voted):
        path = PUZZLE_DIR / (pid + ".js")
        if not path.exists():
            skipped.append((pid, "no puzzle file"))
            continue
        entries = annotated_entries(load(path))
        yes = [e for e in entries if e["id"] in voted[pid]]
        no = [e for e in entries if e["id"] not in voted[pid]]
        if not yes or not no:
            skipped.append((pid, "no usable pair"))
            continue
        # Seeded draw first, then the closest length among the alternatives, so
        # the match is deterministic without always picking the same clue.
        pick = rng.choice(yes)
        gap = min(abs(len(e["solution"]) - len(pick["solution"])) for e in no)
        cands = [e for e in no if abs(len(e["solution"]) - len(pick["solution"])) == gap]
        pairs.append({"puzzle": pid, "voted": pick, "unvoted": rng.choice(cands),
                      "length_gap": gap})
    return pairs, skipped


def clue_row(pid, entry, label):
    return {"label": label, "clue": entry["clue"],
            "solution": entry["solution"], "_puzzle": pid, "_entry": entry["id"]}


def sample(args):
    rng = random.Random(SEED)
    votes = json.loads(pathlib.Path(args.votes).read_text(encoding="utf-8"))
    pairs, skipped = build_pairs(votes, rng)

    rows, key = [], {}
    for i, p in enumerate(pairs):
        for side in ("voted", "unvoted"):
            label = "c%04d" % (2 * i + (side == "unvoted"))
            rows.append(clue_row(p["puzzle"], p[side], label))
            key[label] = {"puzzle": p["puzzle"], "entry": p[side]["id"],
                          "pair": i, "voted": side == "voted"}
    rng.shuffle(rows)

    out = pathlib.Path(args.out)
    (out / "packets").mkdir(parents=True, exist_ok=True)
    (out / "scores").mkdir(parents=True, exist_ok=True)
    for n in range(0, len(rows), BATCH):
        batch = [{k: v for k, v in r.items() if not k.startswith("_")}
                 for r in rows[n:n + BATCH]]
        (out / "packets" / ("batch%02d.json" % (n // BATCH))).write_text(
            json.dumps({"clues": batch}, indent=1) + "\n", encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")

    print("%d pairs from %d puzzles, %d clues, %d batches"
          % (len(pairs), len(pairs), len(rows), (len(rows) + BATCH - 1) // BATCH))
    exact = sum(1 for p in pairs if p["length_gap"] == 0)
    print("solution length matched exactly in %d of %d pairs" % (exact, len(pairs)))
    if skipped:
        print("skipped %d puzzles (%d with no puzzle file)"
              % (len(skipped), sum(1 for _, r in skipped if r == "no puzzle file")))


def binom_p(wins, n):
    """Two-sided exact binomial against p=0.5, no scipy in this repo."""
    from math import comb
    if not n:
        return 1.0
    k = min(wins, n - wins)
    tail = sum(comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def clue_words(text):
    """Words in the clue, minus the trailing enumeration - "(3,4)" is the grid talking."""
    return len(re.sub(r"\(\s*[\d,\-\s]+\s*\)\s*$", "", text).split())


def length_control(out, key, scores):
    """Re-run every axis inside each half of a split on which clue is longer.

    An axis that reverses across that split is counting words, not reading the
    clue. Named clues run longer, so a judge that rewards brevity will mark them
    down for a reason that has nothing to do with whether they are good.
    """
    words = {}
    for f in sorted((out / "packets").glob("*.json")):
        for row in json.loads(f.read_text(encoding="utf-8"))["clues"]:
            words[row["label"]] = clue_words(row["clue"])

    pairs = {}
    for label, k in key.items():
        if label in scores:
            pairs.setdefault(k["pair"], {})[k["voted"]] = label
    both = [p for p in pairs.values() if True in p and False in p]

    halves = [
        ("voted clue shorter", [p for p in both if words[p[True]] < words[p[False]]]),
        ("voted clue longer", [p for p in both if words[p[True]] > words[p[False]]]),
    ]
    print("\n  Length control - the same axes, split on which clue has more words:")
    for name, sub in halves:
        print("  %s (n = %d)" % (name, len(sub)))
        for axis in AXES:
            wins = sum(1 for p in sub if scores[p[True]][axis] > scores[p[False]][axis])
            dec = sum(1 for p in sub if scores[p[True]][axis] != scores[p[False]][axis])
            print("    %-14s %5.1f%%  p = %.4f  (%d of %d decided)"
                  % (axis, 100 * wins / dec if dec else 0, binom_p(wins, dec), wins, dec))


def score(args):
    out = pathlib.Path(args.out)
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    scores = {}
    for f in sorted((out / "scores").glob("*.json")):
        for row in json.loads(f.read_text(encoding="utf-8")):
            scores[row["label"]] = row
    print("%d of %d clues graded" % (len(scores), len(key)))

    pairs = {}
    for label, k in key.items():
        if label in scores:
            pairs.setdefault(k["pair"], {})[k["voted"]] = scores[label]
    both = [p for p in pairs.values() if True in p and False in p]
    print("%d complete pairs\n" % len(both))

    print("  %-14s %6s %6s %6s   %s" % ("axis", "voted", "other", "ties", "share voted higher"))
    for axis in AXES + ["total"]:
        wins = losses = ties = 0
        mv = mo = 0.0
        for p in both:
            a = sum(p[True].get(x, 0) for x in AXES) if axis == "total" else p[True].get(axis, 0)
            b = sum(p[False].get(x, 0) for x in AXES) if axis == "total" else p[False].get(axis, 0)
            mv += a
            mo += b
            if a > b:
                wins += 1
            elif a < b:
                losses += 1
            else:
                ties += 1
        n = wins + losses
        print("  %-14s %6.2f %6.2f %6d   %5.1f%%  p = %.4f"
              % (axis, mv / len(both), mo / len(both), ties,
                 100 * wins / n if n else 0, binom_p(wins, n)))
    print("\nTies are dropped from the test, not counted as half.")
    length_control(out, key, scores)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--votes", default="/tmp/favourite_votes.json")
    ap.add_argument("--out", default=str(ROOT / "tools" / "data" / "favourite_grading"))
    args = ap.parse_args()
    if args.sample:
        sample(args)
    elif args.score:
        score(args)
    else:
        ap.error("one of --sample or --score")


if __name__ == "__main__":
    main()
