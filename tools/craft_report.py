#!/usr/bin/env python3
"""Report what can honestly be said about how a puzzle is set. Not a score.

`tools/difficulty.py` asks how hard a puzzle is. This one used to answer "is it
any good?" with a single number. It no longer does, and the reason is the whole
point of the file, so it is written down here rather than left for somebody to
re-derive.

WHAT THE EVIDENCE SAID (2026-09-09)

Two things were read, not guessed. First, the held-out test: 186 puzzles that
are both scored here and blogged at fifteensquared, 5,398 annotated clues, 1,104
of them named somebody's favourite (tools/favourites_survey.py resolves the
nominations back to our own clue ids). The old composite index was unrelated to
the share of a puzzle's clues that got named — rho -0.116 raw, -0.007 once
thread size was held, and thread size alone carries rho +0.833. The raw number
WAS the thread size.

A rank bug was found while re-testing and is worth knowing about, because it
manufactures signal out of nothing: this file used to break ties by array
index, so a column that is constant or nearly so correlates with whatever order
the puzzles happen to be in. It produced a confident rho -0.379 for a quantity
that turned out to be 1 in all 359 puzzles. Ranks now come from
difficulty._rank_list, which averages ties, and there is no second
implementation here to drift from it.

Second, the prose around those votes: 551 comments naming favourites, and 68
whole blog threads judging whole puzzles. What solvers name when they say why:

  surface reading (~16% of comments)   not computable from a puzzle file
  bare "clever/brilliant" (12%)        not computable, and names no property
  humour (9%)                          not computable
  concision (7%)                       computable, and measured — see below
  misdirection (6%)                    not computable in general
  fairness: every word accounted for   computable, and ALREADY OWNED by
                                       validate_annotations.check_coverage
  loose definitions (~27 of 68 threads) not computable without a lexicon
  pitch against the slot (~50 of 68)   not a property of the puzzle at all

So the four things named most often cannot be computed from clue text, solution,
annotation spans and grid geometry. That is the finding, and no proxy for them
belongs here: a confident number about what nobody complained about is worse
than no number.

WHAT WAS DROPPED, AND WHY

Each of the four old components was tested per clue against the favourite flags,
shuffled inside each puzzle so a busy thread cannot inflate anything:

  FILLER SHARE        CONTRADICTED. Bare cryptic and double definitions, which
                      it counted AGAINST a puzzle, are named +1.8 points more
                      often than the rest, p = 0.032.
  DEFINITION BALANCE  MEASURES NOTHING. 1,092 of 1,104 praised clues have the
                      definition flush at one end; only 12 are interior. No
                      thread in 68 mentions which side a definition sits on.
  DEVICE VARIETY      RIGHT IDEA, WRONG STATISTIC. Entropy hides a 43% anagram
                      share behind a long tail. What solvers actually count is
                      the largest single share — one of them hand-counted "12
                      out of 28 clues involve anagrams". Replaced by DOMINANT
                      DEVICE below.
  INDICATOR FRESHNESS KEPT, but it now names the repeated strings, because the
                      ratio alone tells nobody which word to change.

Five more computable features were built from what the comments praise and
tested the same way. None discriminates: &lit (p = 0.46), single-word anagram
fodder (p = 1.00), clean wordplay tiling (0.887 either way, p = 1.00), a
mid-clue capitalised word consumed by the wordplay (p = 0.21), multi-word
definition (p = 0.55). What does move is clue length — named clues run 7.11
words against 6.78, p = 0.0003, and carry 2.22 blocks against 2.11, p = 0.0003.
Solvers admire ELABORATE clues. That is a fact about the corpus, not a lever:
padding a clue out does not make it good, so it is recorded and not scored.

WHAT IS LEFT, AND HOW TO READ IT

Four observations, reported separately, never averaged. Averaging them is what
produced the number that turned out to be thread size, and any composite would
be dominated by whatever happens to be measurable rather than by what matters.
Each is z-scored against the same setter's other puzzles and against the same
series, because essentially every verdict in 68 threads is comparative — "as
usual", "harder than usual", "one of his better ones" — and a z-score against a
setter's own history is the only referent the prose supports.

  DOMINANT DEVICE     The largest share held by any one atomic device, and its
                      name. "Overloaded with one particular clue type" is the
                      complaint; this is the number that says so.

  REPEATED INDICATORS 1 - distinct/uses, plus the strings that repeat. Reaching
                      for "in" five times is the visible sign of autopilot.

  DOUBLE DUTY         Clues where the definition text also does wordplay work.
                      The threads call this a virtue ("nicely doing double
                      duty") as often as a fault ("'sailor' used twice"), so the
                      sign is genuinely contested and this is REPORTED, never
                      scored.

  GRID MECHANICS      The count of entries of four letters or fewer. Pure
                      geometry, nothing to do with the clues, and the one thing
                      a solver can be flatly right about.

                      Two neighbours of it were tried and are deliberately not
                      observations. The share of lights under half checked is
                      difficulty.py's largest input already, and --vs-difficulty
                      caught it at rho +0.32; it is printed as context in the
                      per-puzzle report and never ranked. The longest run of
                      unchecked cells is 1 in all 359 puzzles — a blocked grid
                      cannot have two adjacent unchecked cells — so it is an
                      invariant, not a measurement, and it is now printed only
                      when it is violated.

NOT MEASURED HERE, ON PURPOSE: surface reading, humour, misdirection, whether a
definition is a stretch, obscurity, difficulty, theme, and whether the puzzle
suits its slot. Every one of those is argued about more than everything above
put together, and none of them is in the fields. Fairness in the strict sense —
every word of the clue accounted for — is real and computable, and it is already
a warning in tools/validate_annotations.py (check_coverage); it is not
duplicated here.

  python3 tools/craft_report.py                     # the corpus, per observation
  python3 tools/craft_report.py --puzzle cryptic-30098
  python3 tools/fetch_fifteensquared.py             # the cache, once
  python3 tools/favourites_survey.py --json votes.json
  python3 tools/craft_report.py --vs-favourites votes.json

`tools/clue_quality.py` is deliberately NOT rolled in. Its checks were built to
catch the lifeless shapes OUR generated clues fall into, and its own calibration
shows them firing on 20-48% of published clues, so as a discriminator between
published puzzles it is mostly noise. Read it per clue; do not average it here.

AS OF 2026-09-09 EVERY OBSERVATION HERE IS A NULL against the favourites, which
is the honest state and not a failure of the test: dominant device +0.18, repeat
indicators -0.02, double duty -0.03, short entries -0.07, all with thread size
held. They earn their place by being things solvers demonstrably argue about and
by being true, not by predicting admiration. Re-run --vs-favourites as the
corpus grows; a number that goes large is the first real evidence this project
has ever had, and it would deserve a paragraph of its own rather than a weight.

The device table --vs-favourites now prints is that evidence, and it is the only
thing in the fields that has ever moved: a bare cryptic definition is named
twice as often as its share of the grid (39 against 19.3 expected, z = +5.34),
and a reversal about a quarter less (83 against 109.1, z = -3.19). Both clear a
Bonferroni line over 15 devices. It is deliberately NOT an observation and never
becomes one, because "use more cryptic definitions" is advice about what to set
rather than about how well it was set, and 101 clues in 5,398 could not move a
puzzle-level number anyway. It says solvers reward the clue types that are pure
reading and punish the ones that are pure mechanism, which is the same sentence
the last paragraph ends on.

Nothing in this file may be shown to a reader as a verdict on how good a puzzle
is. It describes shape and mechanics. The thing solvers fall in love with is the
sentence the clue pretends to be, and that lives in the prose, not the fields.
"""

import argparse
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from difficulty import _rank_list, load, moments  # noqa: E402

# Below this a device's count is dominated by which puzzles happen to be
# blogged, not by whether solvers like it.
MIN_DEVICE_CLUES = 60

ROOT = Path(__file__).resolve().parent.parent
PUZZLE_DIR = ROOT / "puzzles"

WORD = re.compile(r"[A-Za-z’']+")

# The observations, and which direction is the one solvers complain about. None
# means the threads argue both ways, so it is printed and never ranked.
WORSE_WHEN_HIGH = {
    "dominant_device": True,
    "repeated_indicators": True,
    "double_duty": None,
    "short_entries": True,
}

# Counts rather than shares, so they print as integers.
COUNTS = {"short_entries"}


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


def words_of(s):
    return [w.lower().replace("’", "'") for w in WORD.findall(s or "")]


def dominant_device(entries):
    """Largest share of CLUES using one device, its name, and the anagram share.

    Not entropy: entropy normalises away exactly the thing being complained
    about, which is one device swamping the grid. Counted per clue rather than
    per atomic device token, because that is the arithmetic a solver does out
    loud — "12 out of 28 clues involve anagrams" counts a clue that is an
    anagram inside a container once, under anagram.
    """
    counts = Counter(d for e in entries for d in set(devices(e["annotation"])))
    if not counts:
        return None, None, None
    device, n = counts.most_common(1)[0]
    return n / len(entries), device, counts.get("anagram", 0) / len(entries)


def repeated_indicators(entries):
    """1 - distinct/uses, and the indicator strings that repeat."""
    uses = [i.strip().lower()
            for e in entries for i in (e["annotation"].get("indicators") or [])
            if i and i.strip()]
    if not uses:
        return None, []
    counts = Counter(uses)
    repeats = sorted(((n, w) for w, n in counts.items() if n > 1), reverse=True)
    return 1 - len(counts) / len(uses), [(w, n) for n, w in repeats]


def double_duty(entries):
    """Share of clues whose definition text also does wordplay work.

    Matched as whole-word containment either way round rather than by character
    span, because a word that appears twice in a clue makes spans ambiguous and
    the complaint ("'sailor' used twice") is about the word, not the position.
    """
    hits = []
    for e in entries:
        ann = e["annotation"]
        dwords = set(words_of(ann.get("definition")))
        if not dwords:
            continue
        others = set()
        for s in (ann.get("indicators") or []):
            others |= set(words_of(s))
        for b in (ann.get("blocks") or []):
            others |= set(words_of(b.get("clueFragment")))
        shared = dwords & others
        if shared:
            hits.append((e["id"], sorted(shared)))
    return (len(hits) / len(entries) if entries else None), hits


def grid_mechanics(puz):
    """Checking and short entries, from geometry alone.

    Returns the share of lights that are under half checked, the longest run of
    consecutive unchecked cells anywhere in the grid, and how many entries are
    four letters or fewer.
    """
    entries = puz.get("entries") or []
    used = Counter()
    for e in entries:
        x, y = e["position"]["x"], e["position"]["y"]
        dx, dy = (1, 0) if e["direction"] == "across" else (0, 1)
        for i in range(e["length"]):
            used[(x + dx * i, y + dy * i)] += 1

    weak = 0
    longest = 0
    for e in entries:
        x, y = e["position"]["x"], e["position"]["y"]
        dx, dy = (1, 0) if e["direction"] == "across" else (0, 1)
        cells = [used[(x + dx * i, y + dy * i)] < 2 for i in range(e["length"])]
        if sum(cells) / len(cells) > 0.5:
            weak += 1
        run = best = 0
        for unchecked in cells:
            run = run + 1 if unchecked else 0
            best = max(best, run)
        longest = max(longest, best)
    short = sum(1 for e in entries if e["length"] <= 4)
    if not entries:
        return None
    return {"weak_checking": weak / len(entries), "longest_unch": longest,
            "short_entries": short, "lights": len(entries)}


def observe(puz):
    """The four observations for one puzzle, or None if it is not annotated enough."""
    entries = annotated(puz)
    if len(entries) < 4:
        return None
    share, device, anagrams = dominant_device(entries)
    repeat, repeated = repeated_indicators(entries)
    dd, dd_hits = double_duty(entries)
    grid = grid_mechanics(puz)
    if share is None or repeat is None or dd is None or grid is None:
        return None
    return {
        "dominant_device": share, "dominant_device_name": device,
        "anagram_share": anagrams,
        "repeated_indicators": repeat, "repeated_strings": repeated,
        "double_duty": dd, "double_duty_clues": dd_hits,
        "weak_checking": grid["weak_checking"],
        "longest_unch": grid["longest_unch"],
        "short_entries": grid["short_entries"], "lights": grid["lights"],
        "clues": len(entries),
    }


def all_observations():
    """Every puzzle, each observation z-scored against its setter and its series.

    Deliberately no composite. The z-scores are live against whatever is on disk,
    so they move as puzzles arrive, which is honest for a comparative claim.
    """
    raw = {}
    for path in puzzle_files():
        puz = load(path)
        o = observe(puz)
        if o:
            o["series"] = puz.get("series")
            o["setter"] = puz.get("setter")
            raw[puz["id"]] = o

    keys = list(WORSE_WHEN_HIGH)
    stats = {k: moments([r[k] for r in raw.values()]) for k in keys}

    def group_z(field):
        by = {}
        for r in raw.values():
            by.setdefault(r.get(field), []).append(r)
        for name, rows in by.items():
            if name is None or len(rows) < 3:
                for r in rows:
                    r.setdefault(f"z_{field}", {})
                continue
            for k in keys:
                m = moments([r[k] for r in rows])
                for r in rows:
                    z = r.setdefault(f"z_{field}", {})
                    z[k] = (r[k] - m["mean"]) / m["sd"] if m["sd"] else 0.0

    group_z("setter")
    group_z("series")
    return raw, stats


def _rho(a, b):
    """Spearman, on the two lists as given."""
    x, y = _rank_list(a), _rank_list(b)
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    den = math.sqrt(sum((p - mx) ** 2 for p in x) * sum((q - my) ** 2 for q in y))
    return sum((p - mx) * (q - my) for p, q in zip(x, y)) / den if den else 0.0


def _resid(a, b):
    """`a`'s ranks with `b`'s ranks regressed out, for a partial correlation."""
    ra, rb = _rank_list(a), _rank_list(b)
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    var = sum((q - mb) ** 2 for q in rb)
    beta = sum((p - ma) * (q - mb) for p, q in zip(ra, rb)) / var if var else 0.0
    return [p - ma - beta * (q - mb) for p, q in zip(ra, rb)]


def vs_difficulty():
    """Each observation against difficulty. A large correlation would mean the
    observation is hardness wearing another name, so near zero is the pass."""
    import difficulty

    obs, _ = all_observations()
    hard = difficulty.all_scores()
    common = sorted(set(obs) & set(hard))
    if len(common) < 3:
        print("not enough puzzles scored by both", file=sys.stderr)
        return 1
    b = [hard[p]["index"] for p in common]
    print(f"n={len(common)}  each observation against difficulty.py")
    bad = 0
    for k in WORSE_WHEN_HIGH:
        rho = _rho([obs[p][k] for p in common], b)
        flag = "" if abs(rho) < 0.30 else "   TOO CORRELATED — this is measuring hardness"
        bad += abs(rho) >= 0.30
        print(f"  {k:<20} rho = {rho:+.3f}{flag}")
    return 1 if bad else 0


def device_vs_favourites(voted):
    """Which atomic devices get named more often than their share of the grid?

    Not one of the four observations: this is a property of a clue, not of how a
    puzzle is set, and there is no honest way to reward a setter for using more
    cryptic definitions. It is here because it is the only thing in the fields
    that has ever moved against the votes, and it must stay re-derivable.

    A clue's type is a sum ("charade + reversal"), so each atomic part is counted
    separately and the shares do not add to 1. The test is within-puzzle by
    construction: for a puzzle with n annotated clues of which k were named, a
    device appearing in m of them has a hypergeometric count under the null that
    the setter's choice of device tells you nothing. Summing mean and variance
    across puzzles holds thread size fixed the same way the shuffle does, without
    a shuffle.
    """
    tot, obs, exp, var = Counter(), Counter(), defaultdict(float), defaultdict(float)
    puzzles = clues = names = 0
    for path in puzzle_files():
        puz = load(path)
        ents = annotated(puz)
        pid = puz.get("id")
        if pid not in voted or not ents:
            continue
        n = len(ents)
        k = sum(1 for e in ents if e["id"] in voted[pid])
        if n < 2 or k == 0 or k == n:
            continue
        puzzles, clues, names = puzzles + 1, clues + n, names + k
        seen = defaultdict(list)
        for e in ents:
            kind = (e["annotation"].get("type") or "").lower()
            for atom in {a.strip() for a in kind.replace("&", "and ").split("+") if a.strip()}:
                seen[atom].append(e["id"] in voted[pid])
        for atom, flags in seen.items():
            m = len(flags)
            tot[atom] += m
            obs[atom] += sum(flags)
            exp[atom] += m * k / n
            var[atom] += m * (k / n) * ((n - k) / n) * ((n - m) / (n - 1))

    rows = []
    for atom, m in tot.items():
        if m < MIN_DEVICE_CLUES or var[atom] <= 0:
            continue
        z = (obs[atom] - exp[atom]) / math.sqrt(var[atom])
        rows.append((z, atom, m, obs[atom], exp[atom], math.erfc(abs(z) / math.sqrt(2))))
    rows.sort()

    print(f"\nper clue, by device — {puzzles} puzzles, {clues} annotated clues, "
          f"{names} named")
    print(f"  devices in fewer than {MIN_DEVICE_CLUES} clues are not shown; "
          f"{len(rows)} tests, so read p against {0.05 / max(len(rows), 1):.4f}")
    for z, atom, m, x, e, pv in rows:
        print(f"  {atom:22s} n={m:5d}  named {x:4d} vs {e:7.1f} expected"
              f"   z={z:+5.2f}  p={pv:.4f}")
    return rows


def vs_favourites(votes_path, trials=3000):
    """The held-out test: does any observation agree with the clues humans admired?

    Feed it what tools/favourites_survey.py --json writes. Two questions, kept
    apart because only DOUBLE DUTY has a per-clue meaning:

      per clue    Are double-duty clues named more or less often than the rest?
                  The flags are shuffled WITHIN each puzzle, never across, since
                  a puzzle with a busy thread has more of everything named.

      per puzzle  Does a puzzle scoring badly on an observation get fewer of its
                  clues named? Thread size has to be held: how many people
                  showed up moves the share far harder than anything here does.
    """
    votes = json.loads(Path(votes_path).read_text())
    voted, threads = {}, Counter()
    for v in votes:
        voted.setdefault(v["puzzle"], set()).add(v["entry"])
    for pid, _ in {(v["puzzle"], v["comment"]) for v in votes}:
        threads[pid] += 1

    device_vs_favourites(voted)

    obs, _ = all_observations()
    rows = []
    for path in puzzle_files():
        puz = load(path)
        pid = puz.get("id")
        ents = annotated(puz)
        if pid not in voted or pid not in obs or not ents:
            continue
        dd = {i for i, _ in obs[pid]["double_duty_clues"]}
        rows.append((pid, [int(e["id"] in dd) for e in ents],
                     [int(e["id"] in voted[pid]) for e in ents]))
    if len(rows) < 20:
        print(f"only {len(rows)} puzzles are both observed and voted on",
              file=sys.stderr)
        return 1

    def gap(rs):
        fa = fn = oa = on = 0
        for _, mark, fav in rs:
            for is_marked, is_fav in zip(mark, fav):
                if is_marked:
                    fa, fn = fa + is_fav, fn + 1
                else:
                    oa, on = oa + is_fav, on + 1
        return (fa / fn if fn else 0) - (oa / on if on else 0)

    clues = sum(len(r[1]) for r in rows)
    named = sum(sum(r[2]) for r in rows)
    print(f"{len(rows)} puzzles both observed and voted on, {clues} annotated "
          f"clues, {named} named a favourite ({named / clues:.1%})")

    o = gap(rows)
    rng = random.Random(20260909)
    hits = sum(1 for _ in range(trials)
               if abs(gap([(p, m, rng.sample(v, len(v))) for p, m, v in rows]))
               >= abs(o))
    print(f"\nper clue   double-duty clues are named {o:+.1%} against the rest, "
          f"p = {(hits + 1) / (trials + 1):.4f}")
    print("           reported, not scored: the threads call it a virtue as "
          "often as a fault")

    share = [sum(v) / len(v) for _, _, v in rows]
    size = [threads[p] for p, _, _ in rows]
    print(f"\nper puzzle thread size vs the share of a puzzle's clues named: "
          f"rho = {_rho(size, share):+.3f}  <- the confound, held below")
    for k in WORSE_WHEN_HIGH:
        xs = [obs[p][k] for p, _, _ in rows]
        print(f"  {k:<20} rho = {_rho(xs, share):+.3f} raw, "
              f"{_rho(_resid(xs, size), _resid(share, size)):+.3f} held")
    print("\nnone of these is expected to be large. A large one would be the "
          "first evidence\nthis file has ever had that a measurable property "
          "tracks what solvers admire.")
    return 0


def report(pid, r):
    print(f"{pid} — {r['setter'] or '?'} ({r['series'] or '?'}), "
          f"{r['clues']} annotated clues, {r['lights']} lights")
    zs = r.get("z_setter") or {}
    zr = r.get("z_series") or {}

    def z(k):
        parts = []
        if k in zs:
            parts.append(f"{zs[k]:+.1f} vs setter")
        if k in zr:
            parts.append(f"{zr[k]:+.1f} vs series")
        return f"   ({', '.join(parts)})" if parts else ""

    print(f"  dominant device      {r['dominant_device']:.0%} of clues use "
          f"{r['dominant_device_name']}{z('dominant_device')}")
    print(f"  anagram share        {r['anagram_share']:.0%} of clues"
          f"   (the one device solvers count for themselves)")
    print(f"  repeated indicators  {r['repeated_indicators']:.0%} of uses"
          f"{z('repeated_indicators')}")
    for w, n in r["repeated_strings"][:5]:
        print(f"      {w!r} x{n}")
    print(f"  double duty          {r['double_duty']:.0%} of clues"
          f"{z('double_duty')}   (reported, not scored)")
    for cid, shared in r["double_duty_clues"][:5]:
        print(f"      {cid}: {', '.join(shared)}")
    print(f"  grid                 {r['short_entries']} entries of 4 or fewer"
          f"{z('short_entries')}")
    if r["longest_unch"] > 1:
        print(f"                       longest unchecked run {r['longest_unch']} "
              f"— two adjacent unchecked cells, which a blocked grid should not "
              f"have")
    print(f"                       ({r['weak_checking']:.0%} of lights under half "
          f"checked — difficulty.py already weights this, so it is context here, "
          f"not\n                       an observation of its own)")
    print("\nnot measured: surface, humour, misdirection, stretchy definitions,"
          "\nobscurity, difficulty, theme, slot fit. See the module docstring.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="emit the full table as JSON")
    ap.add_argument("--puzzle", metavar="ID", help="the full report for one puzzle")
    ap.add_argument("--top", type=int, default=8,
                    help="how many extremes to show per observation (default 8)")
    ap.add_argument("--vs-difficulty", action="store_true",
                    help="each observation against difficulty.py — near zero is the point")
    ap.add_argument("--vs-favourites", metavar="VOTES.json",
                    help="test against the clues humans named: the JSON "
                         "tools/favourites_survey.py --json writes")
    args = ap.parse_args()

    if args.vs_difficulty:
        return vs_difficulty()
    if args.vs_favourites:
        return vs_favourites(args.vs_favourites)

    obs, stats = all_observations()
    if not obs:
        print("no puzzle is annotated enough to observe", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"puzzles": obs, "observations": stats}, indent=2))
        return 0

    if args.puzzle:
        if args.puzzle not in obs:
            print(f"{args.puzzle} is not observable — try one of "
                  f"{', '.join(sorted(obs)[:3])}", file=sys.stderr)
            return 1
        report(args.puzzle, obs[args.puzzle])
        return 0

    print(f"{len(obs)} puzzles, four observations, reported separately — there "
          f"is no composite\nand no ranking of puzzles overall. See the module "
          f"docstring for why.\n")
    for k, worse_high in WORSE_WHEN_HIGH.items():
        m = stats[k]
        print(f"{k}  mean {m['mean']:.2f}, sd {m['sd']:.2f}")
        if worse_high is None:
            print("  sign contested in the threads — printed, never ranked\n")
            continue
        ordered = sorted(obs.items(), key=lambda kv: -kv[1][k])
        for pid, r in ordered[:args.top]:
            extra = f" {r['dominant_device_name']}" if k == "dominant_device" else ""
            val = f"{r[k]}" if k in COUNTS else f"{r[k]:.0%}"
            print(f"  {pid:<22} {val:<5}{extra:<18} {r['setter'] or '?'}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
