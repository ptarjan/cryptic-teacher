#!/usr/bin/env python3
"""Score how hard each puzzle is, from what the puzzle file actually says.

There is no ground truth for cryptic difficulty *here*. The Guardian publishes
no rating. The one community that does grade by real solve times — the SNITCH
(times.xwdsnitch.link), whose NITCH divides ~100 solvers' times by their own
six-month averages, 100 = a normal day — does publish, openly and without a
login, but it rates The Times, whose puzzles are subscription-only and cannot
be fetched. Real ratings for puzzles we can't have; puzzles we have with no
ratings. There is no join, so this deliberately does NOT pretend to be a
calibrated absolute.

Nor is there a SNITCH for our four series, and the gap is structural rather
than an oversight: the index needs a fixed cohort of timed solves, which only
the Times Club site records. Checked 2026-08-15 — Fifteensquared blogs all four
of ours (Guardian daily and prize, Independent, Everyman, Quick Cryptic) in
prose with no scale, and the one blog that does rate 1-5 for difficulty,
bigdave44, is Telegraph-only. Don't go looking again.

What the SNITCH does buy us is the shape of the thing. Over 136 weeks scraped
2026-08-15, the mean NITCH by publication day is Mon 72, Tue 83, Wed 92, Thu
101, Fri 128, Sat 97 (prize), Sun 105 (Sunday Times, a different puzzle) — a
strictly monotonic Mon-to-Fri climb, Friday 78% slower than Monday. So a
day-of-week term is a real effect in a graded paper, and worth looking for
here. It is NOT in this model, on purpose: the Guardian grades by setter
rotation rather than by editorial fiat, and our 21 scored Guardian cryptics
give 3-5 per weekday, rho = +0.18 against a +0.43 threshold. Underpowered, not
absent. Re-run the test at ~100 scored cryptics before adding a term; do not
fit one to the 21, and do not substitute the unannotated puzzles to pad n — see
the Quiptic control group in score() for why grid-only scores measure the grid. It measures three things that are
genuinely in the file, reports each one separately so a reader can disagree
with the weighting, and bands a puzzle by where it sits *against the rest of
the collection*: "tougher than 80% of the puzzles here" is a claim the data can
support, "Difficulty 7/10" is not.

Everything is scored RELATIVE, and that is the whole trick. The first version
of this file scored the raw numbers absolutely and rated all 35 puzzles
"Tough", which is worse than no rating at all: every Guardian 15x15 daily comes
off a similar grid library (checking sits in a 0.42-0.53 band across the whole
corpus) and every cryptic answer is rare next to "the" (raw obscurity saturates
around 0.9). The signal is entirely in the spread, so each component is
z-scored before it is combined. NITCH turns out to have been right about the
shape of the problem even though its data doesn't reach us.

The reference mean and spread live in tools/data/difficulty_baseline.json, a
frozen snapshot, NOT a running recomputation over whatever is in puzzles/
today. Rescoring against the live corpus every night would silently relabel
puzzles a solver had already seen — a puzzle remembered as Tough quietly
becoming Moderate because six easier ones arrived that week. Refreshing the
baseline is a deliberate act (--rebaseline) that shows the diff.

The three components, each 0-1, hardest = 1:

  checking   The share of an answer's letters that no other entry crosses.
             The oldest and least arguable measure there is: an unchecked
             letter is one you must get from the wordplay alone. A 15x15 daily
             with heavy bars can run over 50% unchecked and it is felt
             immediately.

  obscurity  How far down a frequency-ordered British cryptic word list the
             answers sit, worst word in each entry (a phrase is as hard as its
             rarest half). Needs tools/data/lexicon.tsv, which is gitignored
             and fetched — see the missing-lexicon note in score() for what
             happens when it isn't there.

  device     Which wordplay machinery the clues use, for annotated puzzles
             only, on two axes. RECOGNITION: hidden words give themselves up; a
             bare cryptic definition offers no second confirmation at all, so
             you can never be sure you are right. ASSEMBLY: how much work it is
             to build the answer once you know how — the number of pieces, and
             how many of those pieces are one- or two-letter conventions rather
             than words you could think of. Assembly is the heavier of the two,
             because recognition is the part that gets cheap with practice.

Weights are stated below as an editorial judgement, not a fit. Change them if
you disagree; the components are printed alongside so the change is arguable.

Usage:
  python3 tools/difficulty.py            # table of every puzzle, hardest first
  python3 tools/difficulty.py 30072      # one puzzle, with its components
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUZZLE_DIR = ROOT / "puzzles"
LEXICON = ROOT / "tools" / "data" / "lexicon.tsv"
BASELINE = ROOT / "tools" / "data" / "difficulty_baseline.json"
# What an answer scores when the lexicon has never heard of it. Deliberately the
# tail of the list rather than beyond it: unknown here almost always means a
# proper noun or a phrase build_lexicon.js dropped by design, not a hard word.
MISSING_RANK = 60000
JSON_START = "/*JSON-START*/"
JSON_END = "/*JSON-END*/"

# How much each component moves the overall index. Checking leads because it is
# the one component that is a fact rather than a judgement.
WEIGHTS = {"checking": 0.45, "obscurity": 0.30, "device": 0.25}

# Per-device hardness, 0 = gives itself away, 1 = you may never be certain.
# Ordered by how much confirmation the solver gets back ONCE THE ANSWER IS BUILT
# — this table is a confirmation cost only. The work of building it is a second,
# separate axis, handled by SEAM_COST and OPAQUE_PIECE_COST below. Note what that
# means for the charade at 0.45: a charade confirms itself well (every letter is
# accounted for), so it sits low here, and everything that makes a particular
# charade hard is priced on the other axis, per clue. That is deliberate — "not
# all charades are hard" (Paul, 2026-08-02), and a family-level bump would say
# they are.
DEVICE_COST = {
    "hidden word": 0.15,
    "anagram": 0.30,
    "charade": 0.45,
    "reversal": 0.50,
    "container": 0.50,
    "double definition": 0.55,     # no wordplay to check the definition against
    "first letter": 0.55, "first letters": 0.55,
    "last letter": 0.55, "last letters": 0.55,
    "middle letter": 0.55, "middle letters": 0.55,
    "outer letters": 0.55,
    "alternate letters": 0.55,
    "homophone": 0.60,             # accent-dependent, and rarely exact
    "deletion": 0.60,              # you must know what to remove before you can
    "&lit": 0.80,
    "cryptic definition": 0.85,    # a single unconfirmable leap
}
DEVICE_DEFAULT = 0.50
STACKING_COST = 0.12               # per device beyond the first

# --- the second axis: what the clue costs to WORK, not to recognise -----------
#
# Added 2026-08-02, then immediately re-aimed by Paul: "it isn't knowing it is a
# charade that is hard. It is doing the charade." The first cut priced spotting
# (an unindicated clue gives you nothing to notice) and that was the wrong
# target. Recognition is cheap and it is also learnable in an afternoon — by the
# time you have met thirty charades you assume charade by default. The work that
# does not get cheaper is the assembly: turning each fragment of the clue into
# the right few letters, then getting them in the right order.
#
# So the weight moved off recognition and onto assembly, and assembly is priced
# from what is actually in the annotation — `pieces`, the literal chunks the
# answer is built from. 273 of our clues record them: 26 ones, 105 twos, 92
# threes, 42 fours, 6 fives, 2 sixes.

# Per piece beyond the second, for the families that record `pieces`. Two parts
# is a joint; five is a chain, and every extra link is another sub-clue to solve
# AND another ordering decision to get right.
#
# These two are sized together, against saturation: the per-clue cost is capped
# at 1.0, and a ceiling that a tenth of all clues reach is a ceiling that has
# stopped measuring. At 0.09/0.06 it is 6%, i.e. only the genuinely extreme
# ones — A+T+L+ARGE, E+L+E+MENTAL — and the rest of the range stays live.
SEAM_COST = 0.09

# Per piece of one or two letters. This is the real charade tax and the reason
# the piece COUNT alone isn't enough. "US lawman perfects" -> EARP + HONES is a
# two-piece charade whose pieces are both things you can simply think of; the
# definition of each is a normal synonym problem. "Special ceremony" -> SP + RITE
# is the same shape and the same piece count, but SP is not a synonym for
# anything — it is a convention you either have memorised or you don't, and no
# amount of staring at "special" will produce it. Every one- and two-letter piece
# is a lookup of that kind (S/R/N/E for compass points and abbreviations, I for
# one, O for love/nothing, RE for about, and the rest of the list). Those are
# what make a charade feel like work rather than like thinking.
OPAQUE_PIECE_COST = 0.06
OPAQUE_LEN = 2

# Recognition, kept but demoted from 0.15 — a charade's joiners are invisible
# function words ("about", "after", "in", "before", "on", "by") and 54 of our 76
# bare charades record no indicator at all, so the effect is real. It is just not
# what makes them hard, so it is now a nudge rather than a component.
UNINDICATED_COST = 0.06
# ...except where the family is unindicated by definition. A double definition
# has no indicator because there is nothing to indicate, and its 0.55 already
# prices that; bumping it too would just re-level the whole class.
ALWAYS_UNINDICATED = {"double definition", "cryptic definition"}

# Cut points in standard deviations from the baseline mean, so the band names
# mean "…for a Guardian daily cryptic" — not "…for a crossword". A median
# Guardian cryptic is a hard puzzle by any general standard; saying so on every
# single one would tell a reader nothing about which to pick tonight.
BANDS = [(-0.90, "Gentle"), (-0.25, "Moderate"), (0.60, "Tough"), (float("inf"), "Brutal")]


def load(path):
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(JSON_START, 1)[1].rsplit(JSON_END, 1)[0])


def ranks():
    """word -> frequency rank (1 = "the"). Empty dict if the lexicon isn't fetched."""
    if not LEXICON.exists():
        return {}
    out = {}
    with LEXICON.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[1].isdigit():
                out[parts[0].upper()] = int(parts[1])
    return out


def checking(puz):
    """Mean share of unchecked letters per entry."""
    used = {}
    for e in puz["entries"]:
        x, y = e["position"]["x"], e["position"]["y"]
        dx, dy = (1, 0) if e["direction"] == "across" else (0, 1)
        for i in range(e["length"]):
            used[(x + dx * i, y + dy * i)] = used.get((x + dx * i, y + dy * i), 0) + 1
    fracs = []
    for e in puz["entries"]:
        x, y = e["position"]["x"], e["position"]["y"]
        dx, dy = (1, 0) if e["direction"] == "across" else (0, 1)
        cells = [used[(x + dx * i, y + dy * i)] for i in range(e["length"])]
        fracs.append(sum(1 for c in cells if c < 2) / len(cells))
    return sum(fracs) / len(fracs) if fracs else 0.0


def obscurity(puz, rank):
    """Mean rarity of the answers, judged by the rarest word in each.

    Returned as a raw mean log10 rank, not squashed into 0-1: z-scoring in
    score() supplies the scale, and squashing first only threw away the spread
    that the whole rating depends on.

    log10 because the gap between the 100th and 1000th commonest word is felt
    about as much as the gap between the 1000th and 10000th. A word the list
    has never heard of scores as rare as the tail of the list rather than off
    the scale — usually it is a proper noun or a phrase the lexicon dropped,
    not something genuinely exotic, and letting those run away would make any
    puzzle with a place name in it look brutal.
    """
    if not rank:
        return None
    scores = []
    for e in puz["entries"]:
        ann = e.get("annotation") or {}
        words = (ann.get("answer") or e.get("solution") or "").upper().split()
        if not words:
            continue
        worst = max(rank.get(w.strip("'-"), MISSING_RANK) for w in words)
        scores.append(math.log10(max(worst, 10)))
    return sum(scores) / len(scores) if scores else None


def device(puz):
    """Mean wordplay cost. None when the puzzle has no annotations yet.

    Two axes. RECOGNITION: how hard the machinery is to confirm once you see it
    (DEVICE_COST), plus a nudge when the clue names no indicator at all.
    ASSEMBLY: the work of actually building the answer — SEAM_COST per extra
    piece, OPAQUE_PIECE_COST per piece too short to be a synonym. Assembly
    carries the larger share, deliberately; see the note above SEAM_COST.
    """
    costs = []
    for e in puz["entries"]:
        ann = e.get("annotation") or {}
        kind = (ann.get("type") or "").strip()
        if not kind:
            continue
        parts = [p.strip().lower() for p in kind.split("+") if p.strip()]
        if not parts:
            continue
        cost = max(DEVICE_COST.get(p, DEVICE_DEFAULT) for p in parts)
        cost += STACKING_COST * (len(parts) - 1)
        if not (ann.get("indicators") or []) and not (set(parts) & ALWAYS_UNINDICATED):
            cost += UNINDICATED_COST
        # `pieces` is the answer broken into the chunks the wordplay builds it
        # from; annotate_prompt.md asks for it on charades, containers and
        # deletions. Two is the floor — every one of those families has at
        # least two parts by definition, so only the extra seams cost.
        pieces = [str(p) for p in (ann.get("pieces") or [])]
        cost += SEAM_COST * max(0, len(pieces) - 2)
        # Strip anything that isn't a letter first: pieces are written as the
        # letters they contribute, but a few carry a hyphen or an apostrophe
        # from the answer, and "A-" is a one-letter lookup, not a two.
        cost += OPAQUE_PIECE_COST * sum(
            1 for p in pieces
            if 0 < len([c for c in p if c.isalpha()]) <= OPAQUE_LEN)
        costs.append(min(1.0, cost))
    # A part-annotated puzzle would report whichever clues happened to be done
    # first, which is not a fact about the puzzle. Require most of it.
    if len(costs) < 0.8 * len(puz["entries"]):
        return None
    return sum(costs) / len(costs)


def raw(puz, rank):
    """The three measurements, in their natural units, before any scaling."""
    return {"checking": checking(puz), "obscurity": obscurity(puz, rank),
            "device": device(puz)}


def score(puz, rank, base):
    """Raw components, their z-scores, and a combined index in standard deviations.

    Missing components are dropped and their weight redistributed, rather than
    filled with an average. The two droppable ones — obscurity when the lexicon
    isn't fetched, device when the puzzle isn't annotated yet — are both absent
    for procedural reasons, not because the puzzle is unremarkable, and a
    substituted mean would quietly claim otherwise. Dropping is also cheap here
    because a z-score is already centred: an unannotated puzzle is scored on
    the two components it has, on the same scale as everything else.
    """
    parts = {k: v for k, v in raw(puz, rank).items() if v is not None}
    zs = {}
    for k, v in parts.items():
        ref = base.get(k)
        if not ref or not ref.get("sd"):
            continue
        zs[k] = (v - ref["mean"]) / ref["sd"]
    # Grid geometry on its own is not a difficulty rating. A prize puzzle whose
    # solutions haven't been published yet has nothing but `checking`, and 30068
    # duly came out "Brutal" on an empty grid. Two components or no rating.
    #
    # And `device` specifically, not just any two — the wordplay is the only
    # component that measures the CLUES. That used to be a hunch; adding the
    # Guardian Quiptic gave it a control group, because the Quiptic is the
    # Guardian's own beginner crossword and so is known-easier by editorial
    # fiat. Scored on checking + obscurity alone, our eight quiptics came out at
    # −0.07 against the cryptics' +0.09: a sixth of a standard deviation, i.e.
    # indistinguishable. Quiptic 1,393 was rated BRUTAL, harder than 86% of the
    # collection, on the strength of an open grid. A rating that can't separate
    # the beginner puzzle from the daily is not measuring difficulty, it is
    # measuring the grid — so an unannotated puzzle now gets no band at all,
    # which the index and the picker already handle by showing no badge. The
    # quiptic badge is a fact about the puzzle and stands on its own.
    if len(zs) < 2 or "device" not in zs:
        return None
    total = sum(WEIGHTS[k] for k in zs)
    index = sum(WEIGHTS[k] * z for k, z in zs.items()) / total
    return {"index": round(index, 3),
            "band": next(n for hi, n in BANDS if index < hi),
            "raw": {k: round(v, 4) for k, v in parts.items()},
            "z": {k: round(v, 2) for k, v in zs.items()},
            "basis": sorted(zs)}


def all_scores(base=None):
    rank = ranks()
    base = base if base is not None else load_baseline()
    out = {}
    for path in sorted(PUZZLE_DIR.glob("[0-9]*.js")):
        puz = load(path)
        s = score(puz, rank, base)
        if s:
            out[str(puz["number"])] = s
    # The percentile is a live comparison and says so — it is the answer to
    # "how does this rank against what's on the site", which genuinely does
    # change as puzzles arrive. The band above it stays put; only this moves.
    idx = sorted(s["index"] for s in out.values())
    for s in out.values():
        below = sum(1 for i in idx if i < s["index"])
        s["percentile"] = round(100 * below / max(len(idx) - 1, 1)) if len(idx) > 1 else None
    return out


def load_baseline():
    if BASELINE.exists():
        return json.loads(BASELINE.read_text(encoding="utf-8"))["components"]
    return {}


def rebaseline():
    """Freeze the current corpus as the reference distribution, showing the diff."""
    rank = ranks()
    before = all_scores()
    cols = {}
    for path in sorted(PUZZLE_DIR.glob("[0-9]*.js")):
        for k, v in raw(load(path), rank).items():
            if v is not None:
                cols.setdefault(k, []).append(v)
    comps = {}
    for k, vals in sorted(cols.items()):
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1)
        comps[k] = {"mean": round(mean, 6), "sd": round(math.sqrt(var), 6), "n": len(vals)}
    BASELINE.write_text(json.dumps(
        {"_comment": "Frozen reference distribution for tools/difficulty.py. "
                     "Regenerate deliberately with --rebaseline; every stored "
                     "rating shifts when you do.",
         "components": comps}, indent=2) + "\n", encoding="utf-8")
    after = all_scores(comps)
    moved = [(n, before[n]["band"], after[n]["band"]) for n in sorted(after)
             if n in before and before[n]["band"] != after[n]["band"]]
    for k, c in comps.items():
        print(f"baseline {k}: mean {c['mean']:.4f} sd {c['sd']:.4f} (n={c['n']})")
    print(f"{len(moved)} puzzle(s) changed band" + (":" if moved else ""))
    for n, was, now in moved:
        print(f"  {n}: {was} -> {now}")
    return 0


def main():
    if not LEXICON.exists():
        print("note: tools/data/lexicon.tsv not fetched — scoring without the "
              "obscurity component (bash tools/fetch_lexicon.sh)", file=sys.stderr)
    if "--rebaseline" in sys.argv:
        return rebaseline()
    if not BASELINE.exists():
        print("no tools/data/difficulty_baseline.json — run "
              "python3 tools/difficulty.py --rebaseline", file=sys.stderr)
        return 1
    scores = all_scores()
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")] or \
        sorted(scores, key=lambda n: -scores[n]["index"])
    print(f"{'puzzle':>7}  {'index':>6}  {'band':<10} {'pct':>4}  z-scores")
    for num in wanted:
        s = scores.get(str(num))
        if not s:
            print(f"{num:>7}  no such puzzle", file=sys.stderr)
            continue
        zs = "  ".join(f"{k} {v:+.2f}" for k, v in sorted(s["z"].items()))
        pct = "" if s["percentile"] is None else f"{s['percentile']}%"
        print(f"{num:>7}  {s['index']:+.3f}  {s['band']:<10} {pct:>4}  {zs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
