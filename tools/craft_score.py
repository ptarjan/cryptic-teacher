#!/usr/bin/env python3
"""Score how well *set* each puzzle is, from what the puzzle file already says.

`tools/difficulty.py` asks how hard a puzzle is. This asks a different question
that solvers argue about far more: is it any good? The two are independent — a
brutal puzzle can be lazily set and a gentle one can be a delight.

There is no ground truth for craft, for the same reason there is none for
difficulty, and the reason is worth stating so nobody re-derives it: nobody
publishes a per-puzzle quality rating for our five series. Fifteensquared blogs
all of them, but in prose. What it *does* carry, and what difficulty.py's search
correctly did not need, is the blogger's and commenters' *favourite clues* —
per-clue quality nominations rather than a scale, which makes it a real held-out
test for this file even though it was a dead end for difficulty.py. Checked
2026-09-09: the literal tag "COD" does not appear; the word is "favourite", and
nominations name a clue three different ways (bare number, `14a`, or the answer
word), so harvesting them needs an answer-to-grid resolver, not a number regex.
Their robots.txt sets `Crawl-delay: 20`. Until that join exists, treat every
number here as relative to the collection.

Two things were measured on 2026-09-09 and both belong next to any use of this:

  IT IS NOT DIFFICULTY AGAIN.  Spearman between this index and difficulty.py's
  over the 359 scorable puzzles is -0.03. The two are independent, which is the
  claim that justifies the file existing at all. Re-run with --vs-difficulty; a
  drift toward correlation means a component has started measuring hardness.

  IT MAY REWARD REGULARITY.  Everyman — one setter, deliberately gentle and
  consistent — tops the series table while the Guardian daily sits below the
  mean. That is the shape you would expect if evenness scores well and a setter
  with a strong voice scores badly. Brendan, whose puzzles are themed on
  purpose, lands twice in the worst ten on filler share alone. Do not present
  this to readers as a verdict until the favourites join says otherwise.

So this measures four things that are genuinely in the annotations, reports each
one separately so a reader can disagree with the weighting, and ranks a puzzle
against the rest of the collection. "Better set than 80% of the puzzles here" is
a claim the data supports; "Craft 7/10" is not.

  DEVICE VARIETY      Normalised entropy over the atomic devices in
                      `annotation.type` (split on "+", so "charade + reversal"
                      counts as both). A grid that is 60% anagrams is a lazy
                      grid, and this is the number that says so.

  INDICATOR FRESHNESS Distinct indicator strings divided by indicator uses,
                      within the one puzzle. Reaching for "in" five times is
                      the single most visible sign of a setter on autopilot.

  DEFINITION BALANCE  Cryptic definitions sit at one end of the clue or the
                      other. A setter who always puts them at the front is
                      predictable; this peaks when the split is even and falls
                      to zero when every definition is on the same side.

  FILLER SHARE        The share of clues that are a bare cryptic definition or
                      a bare double definition. Both are legitimate and both
                      are cheap; a grid leaning on them is padding. This one
                      counts AGAINST the puzzle.

The weights are equal and that is a choice, not a fit. Nothing here is tuned to
make any puzzle come out well, because the moment a weight is fitted to an
outcome the score stops being evidence about the outcome. If the components
disagree with human judgement, the finding is about the components.

`tools/clue_quality.py` is deliberately NOT rolled in. Its checks were built to
catch the lifeless shapes OUR generated clues fall into, and its own calibration
shows them firing on 20-48% of published clues, so as a discriminator between
published puzzles it is mostly noise. Read it per clue; do not average it here.
"""

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from difficulty import load, moments  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PUZZLE_DIR = ROOT / "puzzles"

# A bare one of these is a cheap clue. The same device inside a compound
# ("double definition + reversal") is not, so this matches the whole type.
FILLER_TYPES = {"cryptic definition", "double definition"}

# Equal by choice — see the module docstring. Sign is the direction the
# component pushes the composite, not a magnitude.
COMPONENTS = {
    "device_variety": +1,
    "indicator_freshness": +1,
    "definition_balance": +1,
    "filler_share": -1,
}

BANDS = [(-0.90, "Perfunctory"), (-0.25, "Workmanlike"), (0.60, "Polished"),
         (float("inf"), "Exceptional")]


def puzzle_files():
    return sorted(p for p in PUZZLE_DIR.glob("*.js") if p.name != "index.js")


def annotated(puz):
    """Entries carrying a typed annotation. The rest are backlog, not evidence."""
    out = []
    for e in puz.get("entries", []):
        ann = e.get("annotation") or {}
        if (ann.get("type") or "").strip():
            out.append(e)
    return out


def devices(ann):
    """The atomic devices in a composite type string."""
    return [p.strip().lower() for p in (ann.get("type") or "").split("+") if p.strip()]


def device_variety(entries):
    """Normalised Shannon entropy of the atomic device mix, 0..1.

    Normalised by log(distinct), so a puzzle is measured on how evenly it uses
    the devices it reaches for, not punished for the corpus having rarer ones.
    """
    counts = Counter(d for e in entries for d in devices(e["annotation"]))
    total = sum(counts.values())
    if total == 0 or len(counts) < 2:
        return 0.0
    h = -sum((n / total) * math.log(n / total) for n in counts.values())
    return h / math.log(len(counts))


def indicator_freshness(entries):
    """Distinct indicators over indicator uses, 1.0 when none repeats."""
    uses = [i.strip().lower()
            for e in entries for i in (e["annotation"].get("indicators") or [])
            if i and i.strip()]
    return len(set(uses)) / len(uses) if uses else None


def definition_balance(entries):
    """1 when definitions are split evenly front/back, 0 when all one side.

    The definition is stored verbatim, so its side is recoverable by finding it
    in the clue: a definition that starts at character 0 is a front definition.
    Clues where it cannot be located are skipped rather than guessed at.
    """
    front = back = 0
    for e in entries:
        ann = e["annotation"]
        clue, defn = e.get("clue") or "", ann.get("definition") or ""
        if not clue or not defn:
            continue
        at = clue.lower().find(defn.lower())
        if at < 0:
            continue
        front += at == 0
        back += at > 0
    total = front + back
    return 1 - abs(2 * (front / total) - 1) if total else None


def filler_share(entries):
    """Share of clues that are a bare cryptic or double definition."""
    n = sum(1 for e in entries
            if (e["annotation"].get("type") or "").strip().lower() in FILLER_TYPES)
    return n / len(entries)


def components(puz):
    """The four raw components, or None if the puzzle is not annotated enough."""
    entries = annotated(puz)
    if len(entries) < 4:
        return None
    out = {
        "device_variety": device_variety(entries),
        "indicator_freshness": indicator_freshness(entries),
        "definition_balance": definition_balance(entries),
        "filler_share": filler_share(entries),
    }
    return None if any(v is None for v in out.values()) else out


def all_scores():
    """Every scorable puzzle, with each component z-scored against the corpus.

    The z-scores are computed over whatever is on disk right now, so this is a
    live comparison and the numbers move as puzzles arrive — which is the honest
    behaviour for a claim phrased "against the rest of the collection".
    """
    raw = {}
    for path in puzzle_files():
        puz = load(path)
        c = components(puz)
        if c:
            # Keyed by ID, not number: two papers reach the same number.
            raw[puz["id"]] = {"components": c, "series": puz.get("series"),
                              "setter": puz.get("setter")}

    stats = {k: moments([r["components"][k] for r in raw.values()])
             for k in COMPONENTS}

    for r in raw.values():
        zs = {}
        for k, sign in COMPONENTS.items():
            sd = stats[k]["sd"]
            zs[k] = sign * (r["components"][k] - stats[k]["mean"]) / sd if sd else 0.0
        r["z"] = zs
        r["index"] = sum(zs.values()) / len(zs)

    idx = sorted(r["index"] for r in raw.values())
    for r in raw.values():
        below = sum(1 for i in idx if i < r["index"])
        r["percentile"] = round(100 * below / max(len(idx) - 1, 1)) if len(idx) > 1 else None
        r["band"] = next(name for edge, name in BANDS if r["index"] < edge)
    return raw, stats


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0] * len(xs)
    for pos, i in enumerate(order):
        out[i] = pos
    return out


def vs_difficulty():
    """Craft against difficulty. A large correlation would mean this file is a
    second difficulty index wearing a different name, so the test is that the
    number stays near zero — not that it is high."""
    import difficulty

    craft, _ = all_scores()
    hard = difficulty.all_scores()
    common = sorted(set(craft) & set(hard))
    if len(common) < 3:
        print("not enough puzzles scored by both", file=sys.stderr)
        return 1
    a = _ranks([craft[p]["index"] for p in common])
    b = _ranks([hard[p]["index"] for p in common])
    n = len(common)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    rho = num / den if den else 0.0
    print(f"n={n}  spearman(craft, difficulty) = {rho:+.3f}")
    print("independent — this is not difficulty rebadged" if abs(rho) < 0.30
          else "TOO CORRELATED — a component has started measuring hardness")
    return 0 if abs(rho) < 0.30 else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="emit the full table as JSON")
    ap.add_argument("--top", type=int, default=10,
                    help="how many best and worst to show (default 10)")
    ap.add_argument("--by-series", action="store_true",
                    help="mean index per series instead of per puzzle")
    ap.add_argument("--vs-difficulty", action="store_true",
                    help="rank correlation against difficulty.py — near zero is the point")
    args = ap.parse_args()

    if args.vs_difficulty:
        return vs_difficulty()

    scores, stats = all_scores()
    if not scores:
        print("no puzzle is annotated enough to score", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"puzzles": scores, "components": stats}, indent=2))
        return 0

    if args.by_series:
        by = {}
        for pid, r in scores.items():
            by.setdefault(r["series"] or "unknown", []).append(r["index"])
        print(f"craft index by series — {len(scores)} puzzles")
        for series, xs in sorted(by.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
            print(f"  {series:<12} {sum(xs) / len(xs):+.3f}   n={len(xs)}")
        return 0

    ordered = sorted(scores.items(), key=lambda kv: -kv[1]["index"])
    print(f"craft index — {len(scores)} puzzles, equal weights, relative to this collection")
    for label, rows in (("best", ordered[:args.top]),
                        ("worst", ordered[-args.top:][::-1])):
        print(f"\n{label}")
        for pid, r in rows:
            c = r["components"]
            print(f"  {pid:<22} {r['index']:+.3f}  {r['band']:<12} p{r['percentile']:<3}"
                  f" variety {c['device_variety']:.2f}"
                  f" fresh {c['indicator_freshness']:.2f}"
                  f" defbal {c['definition_balance']:.2f}"
                  f" filler {c['filler_share']:.2f}"
                  f"  {r['setter'] or '?'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
