#!/usr/bin/env python3
"""Score how hard each puzzle is, from what the puzzle file actually says.

There is no ground truth for cryptic difficulty in most of the collection.
The Guardian publishes no rating, and nor does anyone else for our Guardian,
Independent, Observer or Telegraph puzzles: the community rating by real solve
times needs a fixed cohort of timed solves, which only the Times Club site
records. Checked 2026-08-15 — Fifteensquared blogs all four of ours in prose
with no scale, bigdave44's 1-5 stars are the blogger's own, and the comment
threads are long and entirely qualitative ("a fraction easier than the average
Paul"). Checked again 2026-09-05, post body and comments. Don't go looking again.

The Times is the exception. The SNITCH (times.xwdsnitch.link) rates every Times
daily since 2015 and every Sunday Times since 2024 by its NITCH — about a
hundred reference solvers' times divided by their own six-month averages, 100 =
a normal day — and tools/fetch_snitch.py keeps those ratings in
tools/data/snitch.json, keyed by our puzzle id, every night. That is a real
external rating joined to puzzles we hold, and --validate prints the agreement.

It is weak, and it did not move the weights. Tuned 2026-09-26 against 197
rated, annotated Times puzzles, split by date and scored only on the later part
(scratch/snitch_weights.py, scratch/snitch_device.py): every refit of WEIGHTS,
and of the device costs below, beat today's values on the puzzles it was
fitted to and lost to them on the held-out ones (Times daily held-out rho
+0.24/+0.32/+0.22 at three cuts, against +0.09/+0.23/+0.23 for the refits).
What agreement there is comes mostly from the device term; obscurity changes
sign between the halves. So the index is still NOT a calibrated absolute, and
the SNITCH is used for two things only: the --validate check, and the
"typically SNITCH X-Y" range a Times badge quotes for its band
(snitch_ranges()).

So this measures three things that are genuinely in the file, reports each one
separately so a reader can disagree with the weighting, and bands a puzzle by
where it sits *against the rest of the collection*: "tougher than 80% of the
puzzles here" is a claim the data can support, "Difficulty 7/10" is not.

`--validate` tests the index against the difficulty facts we did not invent,
and it is a command rather than a paragraph because a number pasted into prose
is true on the day it is pasted:

  SNITCH        The Times puzzles the SNITCH rates: the rank correlation of
                the index with the NITCH per series, and each band's NITCH
                quartiles.

  SERIES ORDER  The Quiptic is the Guardian's beginner crossword and the
                Everyman the Observer's gentlest, both by their own papers'
                editorial fiat. If the index puts them below the dailies it is
                separating puzzles somebody ELSE graded easy, which is the
                strongest external agreement available here. Run it for the
                margin and the p.

  WEEKDAY       The Guardian has no graded weekday, so no day-of-week term is
                in this model — decided 2026-09-09 at 139 scored cryptics,
                against a bar of 100 set while the count was 22 and the
                correlation a null. What the correlation was picking up is a
                Mon/Tue step: those two days sit 0.345 sd below the rest
                (p = 0.0004) and Wed to Sat are flat behind it (rho = -0.06,
                p = 0.59). That is not the SNITCH's shape at all — theirs
                climbs from Monday to Friday without a break (snitch_by_day(),
                printed beside ours), and our Friday, their hardest day, is dead average. Hold each
                setter's own mean constant and the step falls to 0.124 sd,
                p = 0.14: Monday is gentle because Monday is Vulcan, and the
                rotation is already in the score through the clues those
                setters write. --validate prints the step both ways, so a
                Guardian that started grading by day would show up there as a
                step that survives its setters.

That null is a finding about the Guardian, not a failure of the index: it
grades by setter rotation rather than by editorial fiat, and the rotation is
what the measurement found. Do not reopen it by padding n with the unannotated
puzzles: see the Quiptic control group in score() for why grid-only scores
measure the grid.

Everything is scored RELATIVE, and that is the whole trick. The first version
of this file scored the raw numbers absolutely and rated all 35 puzzles
"Tough", which is worse than no rating at all: every Guardian 15x15 daily comes
off a similar grid library (checking sits in a 0.42-0.53 band across the whole
corpus) and every cryptic answer is rare next to "the" (raw obscurity saturates
around 0.9). The signal is entirely in the spread, so each component is
z-scored before it is combined. NITCH is built on the same idea: a time only means something against
the solver's own average.

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
             rarest half). Needs tools/data/lexicon.tsv, which is committed —
             see the missing-lexicon note in score() for what happens in a
             checkout that somehow lacks it.

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
  python3 tools/difficulty.py --validate # does it agree with anything external?
"""

import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (  # noqa: E402 — one glob, one reader for every tool
    puzzle_files, puzzle_is_annotated, read_puzzle_file)
LEXICON = ROOT / "tools" / "data" / "lexicon.tsv"
BASELINE = ROOT / "tools" / "data" / "difficulty_baseline.json"
# What an answer scores when the lexicon has never heard of it. Deliberately the
# tail of the list rather than beyond it: unknown here almost always means a
# proper noun or a phrase build_lexicon.js dropped by design, not a hard word.
MISSING_RANK = 60000

# How much each component moves the overall index. Checking leads because it is
# the one component that is a fact rather than a judgement.
WEIGHTS = {"checking": 0.45, "obscurity": 0.30, "device": 0.25}

# The series their own papers declare gentle, an input to --validate that lives
# here rather than in the prose above so the test and the story it tells cannot
# drift apart.
SNITCH = ROOT / "tools" / "data" / "snitch.json"
#: Our series the SNITCH rates, whose badges quote their band's NITCH range.
SNITCH_SERIES = ("times", "sundaytimes")
#: Rated puzzles a band needs before its quartiles are quoted as a range.
SNITCH_RANGE_MIN = 10
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
GENTLE_SERIES = {"quiptic", "everyman"}

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

# Cut points in standard deviations of the index, so the band names mean
# "…for a Guardian daily cryptic" — not "…for a crossword". A median Guardian
# cryptic is a hard puzzle by any general standard; saying so on every single
# one would tell a reader nothing about which to pick tonight.
#
# The index is a WEIGHTED MEAN of z-scores, so it does not itself have sd 1 —
# averaging partly-uncorrelated components shrinks the spread to about 0.6.
# Comparing these cut points against the raw index therefore reads every band
# a notch harder than it was written to: it put 5% of the corpus in Gentle and
# 67% in Tough-or-Brutal, and it could not call an Everyman gentle. The index
# is standardised against its own frozen mean and sd (banding(), below) before
# it meets these numbers.
BANDS = [(-0.90, "Gentle"), (-0.25, "Moderate"), (0.60, "Tough"), (float("inf"), "Brutal")]


def banding(index, base):
    """The index in units of its own spread, which is what BANDS is written in."""
    ref = base.get("index")
    return (index - ref["mean"]) / ref["sd"] if ref and ref.get("sd") else index


def load_snitch():
    """puzzle id -> {"nitch", "date", "snitch"}, from tools/fetch_snitch.py."""
    return json.loads(SNITCH.read_text(encoding="utf-8")) if SNITCH.exists() else {}


def snitch_by_day(snitch):
    """The Times daily's mean NITCH by weekday, Mon..Sat, over every rating held."""
    by = {}
    for pid, v in snitch.items():
        if pid.rpartition("-")[0] == "times":
            day = datetime.fromisoformat(v["date"]).weekday()
            by.setdefault(day, []).append(v["nitch"])
    return {d: round(sum(x) / len(x)) for d, x in sorted(by.items())}


def _quartiles(xs):
    xs = sorted(xs)
    def at(q):
        i = q * (len(xs) - 1)
        lo = math.floor(i)
        return xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (i - lo)
    return at(0.25), at(0.5), at(0.75)


def snitch_bands(scores, snitch):
    """{series: {band: [NITCH of every rated puzzle in it]}} for SNITCH_SERIES."""
    out = {}
    for pid, s in scores.items():
        series = pid.rpartition("-")[0]
        if series in SNITCH_SERIES and pid in snitch:
            out.setdefault(series, {}).setdefault(s["band"], []).append(snitch[pid]["nitch"])
    return out


def snitch_ranges(scores, snitch=None):
    """{series: {band: [q1, q3, n]}}: the NITCH a band's rated puzzles typically
    got, as the interquartile range. A band with fewer than SNITCH_RANGE_MIN
    rated puzzles is left out, and the badge says nothing for it."""
    snitch = load_snitch() if snitch is None else snitch
    out = {}
    for series, bands in snitch_bands(scores, snitch).items():
        for band, xs in bands.items():
            if len(xs) >= SNITCH_RANGE_MIN:
                q1, _, q3 = _quartiles(xs)
                out.setdefault(series, {})[band] = [round(q1), round(q3), len(xs)]
    return out


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
    # first, which is not a fact about the puzzle. Require all of it, using the
    # same test the index uses for its `annotated` flag: two definitions of
    # "annotated enough" that disagree ship a band on a puzzle the site calls
    # un-annotated, which is the one thing the band must never do.
    if not costs or not puzzle_is_annotated(puz):
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
            "band": next(n for hi, n in BANDS if banding(index, base) < hi),
            "raw": {k: round(v, 4) for k, v in parts.items()},
            "z": {k: round(v, 2) for k, v in zs.items()},
            "basis": sorted(zs)}


def all_scores(base=None):
    rank = ranks()
    base = base if base is not None else load_baseline()
    out = {}
    for path in puzzle_files():
        puz = read_puzzle_file(path)
        s = score(puz, rank, base)
        if s:
            # Keyed by ID, not number: two papers can reach the same number
            # and the caller would then get whichever was scored last.
            out[puz["id"]] = s
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


def moments(vals):
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1)
    return {"mean": round(mean, 6), "sd": round(math.sqrt(var), 6), "n": len(vals)}


def rebaseline():
    """Freeze the current corpus as the reference distribution, showing the diff."""
    rank = ranks()
    before = all_scores()
    cols = {}
    for path in puzzle_files():
        for k, v in raw(read_puzzle_file(path), rank).items():
            if v is not None:
                cols.setdefault(k, []).append(v)
    comps = {}
    for k, vals in sorted(cols.items()):
        comps[k] = moments(vals)
    # Not a component: the composite's own mean and spread, frozen alongside
    # them so BANDS can be written in real standard deviations. It has to be a
    # second pass, because the index it describes is built out of the first.
    comps["index"] = moments([s["index"] for s in all_scores(comps).values()])
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


def _rank_list(xs):
    """Ranks, ties averaged."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out, i = [0.0] * len(xs), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def _spearman(a, b):
    ra, rb = _rank_list(a), _rank_list(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")


def _perm_p(stat, a, b, trials=20000):
    """How often shuffling b alone beats the statistic we measured."""
    obs, b2, hits = abs(stat(a, b)), list(b), 0
    rng = random.Random(20260820)          # fixed: the answer must not wobble per run
    for _ in range(trials):
        rng.shuffle(b2)
        if abs(stat(a, b2)) >= obs:
            hits += 1
    return (hits + 1) / (trials + 1)


def scored_meta():
    """Every scored puzzle, paired with the puzzle file it was scored from."""
    scores = all_scores()
    meta = {}
    for path in puzzle_files():
        puz = read_puzzle_file(path)
        if puz["id"] in scores:
            meta[puz["id"]] = puz
    return scores, meta


def cryptic_weekdays(scores, meta):
    """(weekday, index, setter) for every scored Guardian cryptic."""
    return [(datetime.fromtimestamp(meta[p]["date"] / 1000, timezone.utc).weekday(),
             s["index"], meta[p].get("setter") or "")
            for p, s in scores.items()
            if meta[p].get("series", "cryptic") == "cryptic"]


def _step(ix, wd):
    """Mon+Tue against the rest of the week, in sd.

    The only weekday shape the Guardian actually has, so it is the statistic
    rather than a rank correlation across the six days: a rho reads a two-day
    step as a gradient and so reports a climb through the week that nobody
    publishes and the day means do not show.
    """
    a = [i for i, w in zip(ix, wd) if w < 2]
    b = [i for i, w in zip(ix, wd) if w >= 2]
    return sum(b) / len(b) - sum(a) / len(a) if a and b else 0.0


def hold_setter(rows, floor=3):
    """The same rows with each setter's own mean removed.

    Whatever survives that is the day rather than who sets that day, which is
    the difference between an editor grading Monday and a rotation that happens
    to put a gentle setter there. Setters below `floor` puzzles are dropped
    rather than centred: one seen once is centred onto exactly zero, which
    would report itself as perfect agreement.
    """
    by = {}
    for _, i, setter in rows:
        by.setdefault(setter, []).append(i)
    return [(w, i - sum(by[st]) / len(by[st]), st) for w, i, st in rows
            if st and len(by[st]) >= floor]


def validate():
    """Test the index against the difficulty facts we did not invent.

    Each test lives here rather than in a comment so it re-runs as the corpus
    grows — numbers written into prose are true on the day they are pasted and
    quietly stop being true afterwards.

      SNITCH        The one rating of the same puzzles by someone else: the
                    SNITCH's NITCH for the Times and Sunday Times, per series,
                    as a rank correlation with its permutation p, and the NITCH
                    quartiles of each band (the range the badges quote).

      SERIES ORDER  Two of our four series are declared easy by the papers that
                    print them: the Quiptic is the Guardian's beginner crossword
                    and the Everyman is the Observer's gentlest. If the index
                    cannot put those below the dailies it is not measuring
                    difficulty. This is the same argument the Quiptic control
                    group in score() makes, run as a test.

      WEEKDAY       The SNITCH's Mon-to-Fri climb is the shape of difficulty in a
                    graded paper. Whether the Guardian has one is an open
                    question, not a known fact — it grades by setter rotation
                    rather than editorial fiat — so a null here is a finding
                    about the Guardian, NOT a failure of the index.
    """
    scores, meta = scored_meta()
    print(f"{len(scores)} puzzle(s) scored (annotated) of {len(list(puzzle_files()))} fetched")
    if len(scores) < 20:
        print("too few to test anything; annotate more first")
        return 1
    snitch = load_snitch()

    print(f"\nSNITCH        {len(snitch)} Times puzzles rated in {SNITCH.name}")
    rated = snitch_bands(scores, snitch)
    for series in [s for s in SNITCH_SERIES if s in rated]:
        bands = rated[series]
        pairs = [(snitch[p]["nitch"], s["index"]) for p, s in scores.items()
                 if p in snitch and p.rpartition("-")[0] == series]
        a, b = [x for x, _ in pairs], [y for _, y in pairs]
        if len(pairs) >= 8:
            print(f"              {series:<12} n={len(pairs):>3}  rho = {_spearman(a, b):+.3f}, "
                  f"p = {_perm_p(_spearman, a, b):.4f}")
        for band in [n for _, n in BANDS]:
            xs = bands.get(band, [])
            if xs:
                q1, med, q3 = _quartiles(xs)
                quoted = "" if len(xs) >= SNITCH_RANGE_MIN else "  (too few to quote)"
                print(f"                {band:<9} n={len(xs):>3}  NITCH {q1:.0f}-{q3:.0f}, "
                      f"median {med:.0f}{quoted}")

    def idx(pred):
        return [s["index"] for p, s in scores.items() if pred(meta[p].get("series", "cryptic"))]

    print("\nseries          n   mean index")
    groups = {}
    for p, s in scores.items():
        groups.setdefault(meta[p].get("series", "cryptic"), []).append(s["index"])
    for k, v in sorted(groups.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        print(f"  {k:<12} {len(v):>3}   {sum(v) / len(v):+.3f}")

    gentle, hard = idx(lambda s: s in GENTLE_SERIES), idx(lambda s: s not in GENTLE_SERIES)
    ok = len(gentle) >= 8 and len(hard) >= 8
    if ok:
        labels = [0] * len(gentle) + [1] * len(hard)
        def gap(lab, vals):
            g = [v for l, v in zip(lab, vals) if not l]
            h = [v for l, v in zip(lab, vals) if l]
            return sum(h) / len(h) - sum(g) / len(g)
        d = gap(labels, gentle + hard)
        p = _perm_p(gap, labels, gentle + hard)
        print(f"\nSERIES ORDER  the papers' own beginner puzzles sit {d:+.3f} sd "
              f"below the dailies, p = {p:.4f}")
        print(f"              {'PASS' if d > 0 and p < 0.05 else 'FAIL'} — "
              "the index separates puzzles graded easy by someone other than us")
    else:
        print(f"\nSERIES ORDER  skipped: {len(gentle)} gentle / {len(hard)} daily scored")

    by_day = snitch_by_day(snitch)
    rows = cryptic_weekdays(scores, meta)
    days = sorted({d for d, _, _ in rows})
    if len(rows) >= 20 and len(days) > 1:
        wd, ix = [r[0] for r in rows], [r[1] for r in rows]
        print(f"\nWEEKDAY       Guardian cryptic n={len(rows)}")
        print("              day   n   mean index   SNITCH")
        means = {}
        for d in days:
            vals = [i for w, i, _ in rows if w == d]
            means[d] = sum(vals) / len(vals)
            print(f"              {DAY_NAMES[d]}  {len(vals):>3}   {means[d]:+.3f}"
                  f"       {by_day.get(d, '-')}")
        paired = [d for d in days if d in by_day]
        if len(paired) >= 4:
            r = _spearman([means[d] for d in paired], [by_day[d] for d in paired])
            print(f"              our weekday means vs the SNITCH's, over "
                  f"{len(paired)} days: rho = {r:+.3f}")
        # These two numbers are the whole of the weekday decision, so they are
        # printed rather than remembered. The held one is the one that matters:
        # a Guardian that started grading by day would keep its step with every
        # setter centred on themselves.
        print(f"              Mon+Tue below the rest: {_step(ix, wd):+.3f} sd, "
              f"p = {_perm_p(_step, ix, wd):.4f}")
        held = hold_setter(rows)
        if held:
            h_wd, h_ix = [r[0] for r in held], [r[1] for r in held]
            print(f"              the same step with each setter's own mean held: "
                  f"{_step(h_ix, h_wd):+.3f} sd, p = {_perm_p(_step, h_ix, h_wd):.4f} "
                  f"(n={len(held)} over {len({r[2] for r in held})} setters)")
        print("              decided 2026-09-09: the day is the setter, so the "
              "model has no day-of-week term")
    return 0


def main():
    if "--validate" in sys.argv:
        if not BASELINE.exists():
            print("no baseline — run --rebaseline first", file=sys.stderr)
            return 1
        return validate()
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
        # Bare numbers still work from the command line, the way every other
        # tool takes them, while one names a single puzzle.
        key = str(num) if str(num) in scores else next(
            (k for k in scores if k.rpartition("-")[2] == str(num)), None)
        s = scores.get(key)
        if not s:
            print(f"{num:>7}  no such puzzle", file=sys.stderr)
            continue
        zs = "  ".join(f"{k} {v:+.2f}" for k, v in sorted(s["z"].items()))
        pct = "" if s["percentile"] is None else f"{s['percentile']}%"
        print(f"{num:>7}  {s['index']:+.3f}  {s['band']:<10} {pct:>4}  {zs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
