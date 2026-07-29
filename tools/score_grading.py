#!/usr/bin/env python3
"""Join blind judges' scores to the provenance key and report the head-to-head.

The judges never saw the key, so this is the first point at which anyone knows
which clue was ours. Everything here is arithmetic on numbers that were fixed
before provenance was revealed — that ordering is the whole guarantee.

Reports, in order of how much they should change our behaviour:

  * per-axis mean, ours vs human, with the gap — where we actually lose
  * win rate per answer (our mean vs the best human clue for the same word)
  * favourite picks — how often a judge would put our clue in a puzzle
  * machine-guess accuracy — if judges spot us reliably, the axis scores are
    measuring a style tell rather than quality, and the comparison is weaker
    than it looks. This number is reported whether or not it flatters us.
  * inter-judge agreement, so a lopsided result from one harsh judge is visible

  python3 tools/score_grading.py --grading tools/data/grading \
      --scores /tmp/clue-judging/scores
"""

import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AXES = ["surface", "misdirection", "pennydrop", "economy", "fairness"]


def load_scores(scores_dir):
    out = {}
    for p in sorted(Path(scores_dir).glob("judge*.json")):
        out[p.stem] = json.loads(p.read_text())
    if not out:
        raise SystemExit(f"no judge*.json under {scores_dir}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grading", default="tools/data/grading")
    ap.add_argument("--scores", default="/tmp/clue-judging/scores")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    key = json.loads((ROOT / args.grading / "key.json").read_text())
    judges = load_scores(args.scores)

    # rows: (judge, answer, label, is_ours, {axis: score})
    rows = []
    favourites = []      # (judge, answer, picked_ours)
    guesses = []         # (judge, answer, guess, correct_or_none)
    for jname, packets in judges.items():
        for pk in packets:
            ans = pk["answer"]
            if ans not in key:
                continue
            ours = key[ans]["ours"]
            for label, sc in pk["scores"].items():
                if not all(a in sc for a in AXES):
                    continue
                rows.append((jname, ans, label, label == ours,
                             {a: float(sc[a]) for a in AXES}))
            if pk.get("favourite"):
                favourites.append((jname, ans, pk["favourite"] == ours))
            g = (pk.get("machine_guess") or "none").strip()
            if g.lower() in ("none", "", "n/a"):
                guesses.append((jname, ans, "none", None))
            else:
                guesses.append((jname, ans, g, g == ours))

    def mean(vals):
        return statistics.mean(vals) if vals else float("nan")

    mine = [r for r in rows if r[3]]
    theirs = [r for r in rows if not r[3]]

    print(f"{len(judges)} judges, {len(rows)} clue-scores "
          f"({len(mine)} ours, {len(theirs)} human)\n")

    print(f"{'axis':<14}{'ours':>7}{'human':>8}{'gap':>8}")
    axis_gap = {}
    for a in AXES:
        m, h = mean([r[4][a] for r in mine]), mean([r[4][a] for r in theirs])
        axis_gap[a] = m - h
        print(f"{a:<14}{m:>7.2f}{h:>8.2f}{m - h:>+8.2f}")
    om = mean([statistics.mean(r[4].values()) for r in mine])
    hm = mean([statistics.mean(r[4].values()) for r in theirs])
    print(f"{'OVERALL':<14}{om:>7.2f}{hm:>8.2f}{om - hm:>+8.2f}\n")

    # Per answer: our mean against the best human clue for the same word. Beating
    # the average human clue is easy; beating the best one is the real bar, since
    # a setter only publishes their best attempt at a word.
    print(f"{'answer':<12}{'ours':>6}{'best human':>12}  verdict")
    wins = 0
    per_answer = {}
    for ans in sorted(key):
        o = [statistics.mean(r[4].values()) for r in rows if r[1] == ans and r[3]]
        by_label = {}
        for r in rows:
            if r[1] == ans and not r[3]:
                by_label.setdefault(r[2], []).append(statistics.mean(r[4].values()))
        if not o or not by_label:
            continue
        om_a = mean(o)
        best = max(mean(v) for v in by_label.values())
        won = om_a >= best
        wins += won
        per_answer[ans] = {"ours": round(om_a, 2), "best_human": round(best, 2)}
        print(f"{ans:<12}{om_a:>6.2f}{best:>12.2f}  {'WIN ' if won else 'lose'}")
    print(f"\nbeat the best human clue on {wins}/{len(per_answer)} answers\n")

    fav_ours = sum(1 for f in favourites if f[2])
    print(f"favourite pick: ours chosen {fav_ours}/{len(favourites)} "
          f"(chance = {len(favourites) / 4:.0f})")

    named = [g for g in guesses if g[3] is not None]
    hit = sum(1 for g in named if g[3])
    abstain = len(guesses) - len(named)
    print(f"machine guess: judges named a clue {len(named)}/{len(guesses)} times "
          f"({abstain} abstained), correct {hit}/{len(named)}"
          + (f" = {hit / len(named):.0%}" if named else ""))
    print("  (chance is ~25%; well above that means judges can see a style tell,")
    print("   so treat the axis scores above as flattered by blindness we lost)")

    print("\nper-judge overall (ours / human):")
    for j in sorted(judges):
        jo = mean([statistics.mean(r[4].values()) for r in mine if r[0] == j])
        jh = mean([statistics.mean(r[4].values()) for r in theirs if r[0] == j])
        print(f"  {j:<10}{jo:>6.2f}{jh:>8.2f}{jo - jh:>+8.2f}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "axis_means_ours": {a: round(mean([r[4][a] for r in mine]), 3) for a in AXES},
            "axis_means_human": {a: round(mean([r[4][a] for r in theirs]), 3) for a in AXES},
            "axis_gap": {a: round(v, 3) for a, v in axis_gap.items()},
            "overall_ours": round(om, 3),
            "overall_human": round(hm, 3),
            "per_answer": per_answer,
            "wins_vs_best_human": wins,
            "answers": len(per_answer),
            "favourite_ours": fav_ours,
            "favourite_total": len(favourites),
            "machine_guess_correct": hit,
            "machine_guess_named": len(named),
        }, indent=1) + "\n")


if __name__ == "__main__":
    main()
