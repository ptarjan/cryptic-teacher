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

The SNITCH chooses components and never sets weights. A component joins the
index, or replaces one, only when the index with it beats the index without
it held out, on two sets: the annotated Times dailies under the full index,
and the rated Times dailies with no annotation under the components that
need none (PORTABLE). Each set splits into its own date thirds,
each third scored against the NITCH minus the weekday mean of the rated
puzzles outside it, and the candidate must win in at least two of the three and on the mean
in both, with the Sunday Times not falling and --validate's SERIES ORDER
passing at a margin of at least MARGIN_FLOOR (tools/difficulty_check.py
measures the shipped index this way nightly; scratch/snitch_stage4.py screens
candidates with the same functions). A candidate's sign is fixed before it is measured. The weights are fixed,
not fitted: held-out refits of them
(scratch/snitch_weights.py) came out unstable and never beat fixed ones. The
index is NOT a calibrated absolute, and the SNITCH is used for three things:
the --validate check, the "typically SNITCH X-Y" range a Times badge quotes
for its band (snitch_ranges()), and choosing components. tools/snitch_report.py measures the index and each component
against the NITCH minus its weekday mean, by date third, and is rerun
nightly into tools/data/snitch_report.txt.

So this measures nine things that are genuinely in the file, reports each one
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

  CTC           Per clue: Cracking the Cryptic's solve videos time the wait
                from reading each clue to solving it. The per-clue forms of
                the components against that wait, within each video. A check,
                not part of the adoption rule above.

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

The nine components, higher = harder:

  checking   The share of an answer's letters that no other entry crosses.
             The oldest and least arguable measure there is: an unchecked
             letter is one you must get from the wordplay alone. A 15x15 daily
             with heavy bars can run over 50% unchecked and it is felt
             immediately. A barred grid (Listener, Mephisto) has none: it is
             checked almost everywhere by convention, 9-19 sd off the blocked
             grids' spread, and its difficulty lives in the clues and the
             theme. Its checking is left out, not scored as Gentle.

  rarity     How far down a frequency-ordered British cryptic word list the
             puzzle's three rarest answers sit, each looked up whole (a phrase
             the list lacks is as rare as its rarest word). Needs
             tools/data/lexicon.tsv, which is committed.

  device     Which wordplay machinery the clues use, for annotated puzzles
             only, on two axes. RECOGNITION: hidden words give themselves up; a
             bare cryptic definition offers no second confirmation at all, so
             you can never be sure you are right. ASSEMBLY: how much work it is
             to build the answer once you know how — the number of pieces, and
             how many of those pieces are one- or two-letter conventions rather
             than words you could think of. Assembly is the heavier of the two,
             because recognition is the part that gets cheap with practice.

  machinery  How many operations the clues ask for, annotated puzzles only:
             indicators per clue, plus one for a clue stacking three or more
             devices. `device` asks which tools a clue uses; this asks how
             many times you have to use one. It is the feature that tracks
             the part of the SNITCH its weekly ramp does not explain.

  answer_novelty   How seldom the answers appeared in earlier puzzles, of
             any series. A solver who has met an answer before reaches it
             sooner, whatever the clue does.

  pairing_novelty  How seldom each answer was clued by a definition with this
             same head word in earlier puzzles: the definition the blog
             underlines where a blog writes the puzzle up, else our
             annotation's, reduced to its head (definition_head()). A stock
             pairing is recognised on sight. Counted on the whole string, a
             long definition almost never recurs and so reads as novel, which
             charges a series for writing long definitions.

             Both count ONLY puzzles dated before this one, so a rating never
             moves because a later puzzle arrived, and both are shares or
             scaled counts rather than raw counts, so an old puzzle with a
             short history behind it is not read as unfamiliar. history()
             states the arithmetic.

  question_marks  The share of clues ending in a question mark. The mark
             flags a definition by example, a pun or a cryptic definition:
             the definition is not a plain synonym, which is the part of a
             clue the wordplay components do not see. Commenters flag such
             clues hard, and name them as their last one in, more often than
             the rest. A clue whose answer is the first letters of its own
             consecutive words is not counted (acrostic()): there the mark
             flags an all-in-one acrostic, which gives itself up, and the
             Everyman closes most of its puzzles with one, so counting it
             charges the Everyman for a house style. It needs only the clue
             text, so it is there for every series, annotated or not.

  definition_unrelated  The share of clues whose definition WordNet does not
             tie to the answer: no content word of it is the answer's synset,
             a near hypernym, hyponym, look-alike or derived form of it, a
             sibling under the same hypernym, or a word of either one's gloss.
             An unrelated definition is an indirect one, which the solver
             cannot reach by synonym lookup. Each word is judged alone, so a
             long definition is not unrelated for its length. It needs the
             blog's or our annotation's definition, not our wordplay, so
             unannotated Times puzzles have it. WordNet is read from
             tools/data/wordnet.json.gz, committed and written by
             tools/build_wordnet.py, so no rating depends on nltk being
             installed; a word the file lacks counts as one WordNet lacks.

  clue_count  How many clues the puzzle sets, a cross-reference ("See 5")
             not counted. Every clue is one more thing to solve, so the
             count is felt in the time whatever each clue is like. It puts a
             Times Jumbo well above a daily, which is right for time taken.

The badges add one thing the clues cannot: where a Times for the Times post
has comments stating at least COMMENT_MIN_TIMES solve times, all_scores()
blends the clue index with them (blend()): the mean of the index's z and the
comment signal's z, the comment signal being the equal mean of the z of the
log median stated minutes and the z of the share of comments reporting a DNF,
every z against the puzzle's own series, restandardised onto that series' clue
index so its mean and spread stay put. The weights are fixed, not fitted, and
the per-series moments are frozen in the baseline beside the components'. A
puzzle re-rates as its post gains comments, which the nightly run fetches.
score() stays clue-only: the comments are solver times, as the NITCH is, so
everything that chooses components measures score(), never the blend. Fifteensquared's
comments state no times, so every other series is clue-only. Measured by
scratch/comment_blend.py.

Weights are fixed (above): checking leads at 0.45, rarity 0.30, and every
other component 0.25. The components are printed alongside the index so a
reader can argue with them.

Usage:
  python3 tools/difficulty.py            # table of every puzzle, hardest first
  python3 tools/difficulty.py 30072      # one puzzle, with its components
  python3 tools/difficulty.py --validate # does it agree with anything external?
"""

import bisect
import functools
import gzip
import json
import math
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (  # noqa: E402 — one glob, one reader for every tool
    puzzle_files, puzzle_is_annotated, read_puzzle_file)
import definitions
import parallel
import series as series_meta
from groups import entry_id
LEXICON = ROOT / "tools" / "data" / "lexicon.tsv"
BASELINE = ROOT / "tools" / "data" / "difficulty_baseline.json"
BLOG_FACTS = ROOT / "tools" / "data" / "blog_facts"
WORDNET = ROOT / "tools" / "data" / "wordnet.json.gz"
# What an answer scores when the lexicon has never heard of it. Deliberately the
# tail of the list rather than beyond it: unknown here almost always means a
# proper noun build_lexicon.js dropped by design, not a hard word.
MISSING_RANK = 60000
#: rarity() averages this many of a puzzle's rarest answers.
RAREST_ANSWERS = 3
#: Earlier puzzles a familiarity count needs behind it before it is scored.
HISTORY_FLOOR = 5000
#: pairing_novelty counts per this many earlier puzzles that carry a definition.
PAIRING_SCALE = 10000

# How much each component moves the overall index. Checking leads because it is
# the one component that is a fact rather than a judgement; rarity follows it,
# and the rest are equal. Fixed, never fitted: see the module docstring.
WEIGHTS = {"checking": 0.45, "rarity": 0.30, "device": 0.25, "machinery": 0.25,
           "answer_novelty": 0.25, "pairing_novelty": 0.25, "question_marks": 0.25,
           "definition_unrelated": 0.25, "clue_count": 0.25}
#: The components an unannotated puzzle has: the index the unannotated held-out
#: set is scored by (tools/difficulty_check.py).
PORTABLE = ("rarity", "answer_novelty", "pairing_novelty", "question_marks",
            "definition_unrelated", "clue_count")
#: The least the index may put the gentle series below the dailies, in its own sd.
MARGIN_FLOOR = 0.08

# The series their own papers declare gentle, an input to --validate that lives
# here rather than in the prose above so the test and the story it tells cannot
# drift apart.
SNITCH = ROOT / "tools" / "data" / "snitch.json"
#: Our series the SNITCH rates, whose badges quote their band's NITCH range.
SNITCH_SERIES = ("times", "sundaytimes")
#: Rated puzzles a band needs before its quartiles are quoted as a range.
SNITCH_RANGE_MIN = 10
#: Times for the Times comment signals, per puzzle (tools/blog_comment_difficulty.py).
COMMENTS = ROOT / "tools" / "data" / "blog_comment_difficulty.json"
#: Stated solve times a puzzle's comments need before they move its rating.
COMMENT_MIN_TIMES = 3
#: Puzzles with a comment signal a series needs before any of them is blended.
COMMENT_SERIES_MIN = 30
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
    "hidden_word": 0.15,
    "anagram": 0.30,
    "charade": 0.45,
    "reversal": 0.50,
    "container": 0.50,
    "double_definition": 0.55,     # no wordplay to check the definition against
    "letter_selection": 0.55,
    "homophone": 0.60,             # accent-dependent, and rarely exact
    "deletion": 0.60,              # you must know what to remove before you can
    "and_lit": 0.80,
    "cryptic_definition": 0.85,    # a single unconfirmable leap
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
ALWAYS_UNINDICATED = {"double_definition", "cryptic_definition"}

# --- how much machinery a clue carries: operations, counted -----------------
#
# `device` prices the families a clue uses; this counts the operations in it.
# Every indicator the annotation records is one instruction the solver has to
# spot and carry out, and a clue stacking three or more devices is one more
# thing again: the order they apply in, which no single indicator states.
# Against the SNITCH's NITCH minus its weekday mean, on the Times daily, this
# holds in each date third where `device` does not, and adding it at the same
# weight as `device` lifts the index in every third without costing it the raw
# NITCH (tools/snitch_report.py prints both).
STACKED_DEVICES = 3
STACKED_OPERATIONS = 1


def clue_machinery(e):
    """One clue's operation count, or None when it carries no type."""
    ann = e.get("annotation") or {}
    parts = ann.get("type") or []
    if not parts:
        return None
    return (len(ann.get("indicators") or [])
            + STACKED_OPERATIONS * (len(parts) >= STACKED_DEVICES))


def machinery(puz):
    """Mean operations per clue. None when the puzzle is not fully annotated,
    by the same rule as device()."""
    ops = [m for m in (clue_machinery(e) for e in puz["entries"]) if m is not None]
    if not ops or not puzzle_is_annotated(puz):
        return None
    return sum(ops) / len(ops)


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


def band_of(index, base):
    return next(n for hi, n in BANDS if banding(index, base) < hi)


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
    """{series: {band: {q1, q3, rated}}}: the NITCH a band's rated puzzles
    typically got, as the interquartile range q1 to q3 over `rated` puzzles. A band with fewer than SNITCH_RANGE_MIN
    rated puzzles is left out, and the badge says nothing for it."""
    snitch = load_snitch() if snitch is None else snitch
    out = {}
    for series, bands in snitch_bands(scores, snitch).items():
        for band, xs in bands.items():
            if len(xs) >= SNITCH_RANGE_MIN:
                q1, _, q3 = _quartiles(xs)
                out.setdefault(series, {})[band] = {"q1": round(q1), "q3": round(q3), "rated": len(xs)}
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
    for light in puz.get("unclued") or []:   # an unclued light checks the squares it shares
        for c in light["cells"]:
            used[(c["x"], c["y"])] = used.get((c["x"], c["y"]), 0) + 1
    fracs = []
    for e in puz["entries"]:
        x, y = e["position"]["x"], e["position"]["y"]
        dx, dy = (1, 0) if e["direction"] == "across" else (0, 1)
        cells = [used[(x + dx * i, y + dy * i)] for i in range(e["length"])]
        fracs.append(sum(1 for c in cells if c < 2) / len(cells))
    return sum(fracs) / len(fracs) if fracs else 0.0


def letters(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def answer_words(e):
    """The entry's answer split where its enumeration splits it."""
    sol = letters(e.get("solution"))
    cuts = sorted({sep["at"] for sep in e["clue"].get("separators", [])})
    words, prev = [], 0
    for c in cuts + [len(sol)]:
        words.append(sol[prev:c])
        prev = c
    return sol, [w for w in words if w]


def rarity(puz, rank):
    """Mean log10 frequency rank of the puzzle's RAREST_ANSWERS rarest answers.

    Each answer is looked up whole, and a phrase the lexicon lacks as a whole
    counts as its rarest word. The rarest few rather than the mean of all,
    because a puzzle is held up by the answers nobody knows, and thirty
    familiar ones do not dilute that.

    Raw log10, not squashed into 0-1: z-scoring in score() supplies the scale.
    log10 because the gap between the 100th and 1000th commonest word is felt
    about as much as the gap between the 1000th and 10000th. A word the list
    has never heard of scores MISSING_RANK, the tail of the list rather than
    off the scale, so a puzzle with a place name in it does not look brutal.
    """
    if not rank:
        return None
    scores = []
    for e in puz["entries"]:
        sol, words = answer_words(e)
        if not sol:
            continue
        r = rank[sol] if sol in rank else max(rank.get(w, MISSING_RANK) for w in words)
        scores.append(math.log10(max(r, 10)))
    worst = sorted(scores)[-RAREST_ANSWERS:]
    return sum(worst) / len(worst) if worst else None


def definition_key(d):
    """A definition as the lowercase words in it, the form pairings are counted in."""
    if isinstance(d, list):
        d = next((x for x in d if x), None)
    return " ".join(re.findall(r"[a-z]+", (d or "").lower()))


#: Words a definition's head is never: articles, example markers, the tails of
#: contractions ("that'll", "who's").
HEAD_SKIP = {"a", "an", "the", "and", "or", "is", "be", "it", "its", "his", "her",
             "their", "this", "not", "no", "some", "being", "perhaps", "say", "eg",
             "etc", "maybe", "possibly", "s", "ll", "m", "re", "ve", "d"}
#: A word that opens a definition's modifier: its head is the word before it.
HEAD_BREAK = {"of", "to", "for", "with", "in", "on", "from", "at", "by", "about",
              "who", "that", "which", "where"}


def definition_head(d):
    """The head word of a definition key: the last word before its first
    preposition or relative ("part of london" -> part, "one who is wise" ->
    one), else its last word ("hot african location" -> location), articles
    and example markers skipped. A pairing is counted on it, so a definition
    reads as familiar whatever length it is written at."""
    ws = d.split()
    for i, w in enumerate(ws):
        if w in HEAD_BREAK and i:
            before = [x for x in ws[:i] if x not in HEAD_SKIP]
            if before:
                return before[-1]
    kept = [x for x in ws if x not in HEAD_SKIP and x not in HEAD_BREAK]
    return kept[-1] if kept else d


#: Words a definition's relatedness is never judged on.
FUNCTION_WORDS = {"a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "is", "be",
                  "with", "by", "at", "as", "that", "this", "it", "one", "s", "from", "who",
                  "what", "may", "some", "being", "one's", "its", "his", "her", "their",
                  "not", "no"}
#: How far up the tree an answer's hypernyms still count as related to it...
HYPERNYM_DEPTH = 5
#: ...short of the generic top ("object", "person", "act"), which relates everything.
GENERIC_DEPTH = 3


@functools.lru_cache(maxsize=1)
def wordnet():
    """(word -> synset ids, synset rows) from tools/data/wordnet.json.gz
    (tools/build_wordnet.py), whose rows are (gloss words, hypernyms,
    instance hypernyms, neighbours, generic)."""
    data = json.loads(gzip.decompress(WORDNET.read_bytes()))
    rows = [(set(g.split()), h, ih, nb, bool(gen)) for g, h, ih, nb, gen in data["synsets"]]
    return {w: set(ids) for w, ids in data["words"].items()}, rows


@functools.lru_cache(maxsize=None)
def near_synsets(answer):
    """(synsets, gloss words) around an answer ("sea_dog" for a phrase): its
    own synsets, their hypernyms HYPERNYM_DEPTH deep short of the generic top,
    and their hyponyms, look-alikes, holonyms and derived forms."""
    words, rows = wordnet()
    own = words.get(answer, set())
    ss, gloss = set(own), set()
    level = set(own)
    for _ in range(HYPERNYM_DEPTH):
        level = {h for s in level for h in rows[s][1] + rows[s][2]}
        ss.update(h for h in level if not rows[h][4])
    for s in own:
        ss.update(rows[s][3])
        gloss |= rows[s][0]
    return ss, gloss - FUNCTION_WORDS


def definition_related(answer, definition):
    """Whether WordNet ties any content word of the definition to the answer:
    a synset near the answer's, one of the answer's gloss words, a synset
    whose hypernym (not instance hypernym) is near the answer's, or the answer named in the word's
    own gloss. Each word is judged alone, so a long definition is not read as
    unrelated for its length. None when WordNet lacks the answer."""
    ws = definition.split()
    ss, gloss = near_synsets(answer)
    if not ws or not ss:
        return None
    ans_words = set(answer.split("_"))
    for c in {x for x in ws if x not in FUNCTION_WORDS} or set(ws):
        ds, hyper, own_gloss = word_synsets(c)
        if c in gloss or not ds.isdisjoint(ss) or not hyper.isdisjoint(ss) \
                or not ans_words.isdisjoint(own_gloss):
            return True
    return False


@functools.lru_cache(maxsize=None)
def word_synsets(word):
    """(synsets, their hypernyms short of the generic top, their gloss words)
    of one definition word."""
    words, rows = wordnet()
    ds = words.get(word, set())
    return (ds, {h for d in ds for h in rows[d][1] if not rows[h][4]},
            set().union(*(rows[d][0] for d in ds)) if ds else set())


#: Judged clues a puzzle needs before definition_unrelated is scored.
UNRELATED_FLOOR = 5


def definition_unrelated(puz):
    """Share of the clues whose definition WordNet does not tie to the answer.
    The definition is the blog's underlined one, else our annotation's; a clue
    whose answer WordNet lacks is not judged. None below UNRELATED_FLOOR."""
    bd = blog_definitions().get(puz["id"], {})
    judged = []
    for e in puz["entries"]:
        d = bd.get(entry_id(e)) or definition_key(definitions.texts(e.get("annotation")))
        if not d or not e.get("solution"):
            continue
        clue = e["clue"].get("text", "").strip()
        if not clue or re.match(r"(?i)see\b", clue):
            continue
        _, ws = answer_words(e)
        r = definition_related("_".join(w.lower() for w in ws), d)
        if r is not None:
            judged.append(not r)
    return sum(judged) / len(judged) if len(judged) >= UNRELATED_FLOOR else None


@functools.lru_cache(maxsize=1)
def blog_definitions():
    """{puzzle id: {entry id: definition}}: the blogger's underlined definition,
    from tools/data/blog_facts/."""
    out = {}
    for part in parallel.pmap(blog_file_definitions, sorted(BLOG_FACTS.glob("*.json")),
                              chunksize=1):
        out.update(part)
    return out


def blog_file_definitions(f):
    """blog_definitions() for one tools/data/blog_facts/<series>.json."""
    out = {}
    for pid, v in json.loads(f.read_text(encoding="utf-8")).items():
        defs = {eid: definition_key(definitions.texts(b))
                for eid, b in (v.get("entries") or {}).items()}
        defs = {k: d for k, d in defs.items() if d}
        if defs:
            out[pid] = defs
    return out


def history_row(path):
    """(day, id, single-word answers, (answer, definition head) pairs) for
    one puzzle file, or None for an undated puzzle; history() counts these."""
    puz = read_puzzle_file(path)
    day = series_meta.puzzle_day(puz)
    if not day:
        return None
    bd = blog_definitions().get(puz["id"], {})
    sols, pairs = set(), set()
    for e in puz["entries"]:
        sol = letters(e.get("solution"))
        if not sol or e["clue"].get("separators"):
            continue
        sols.add(sol)
        d = bd.get(entry_id(e)) or definition_key(definitions.texts(e.get("annotation")))
        if d:
            pairs.add((sol, definition_head(d)))
    return day, puz["id"], sols, pairs


@functools.lru_cache(maxsize=1)
def history():
    """{puzzle id: {"answer_novelty", "pairing_novelty"}}, each counted over
    every puzzle of every series dated strictly before that one.

    answer_novelty   Mean over the answers of -ln((n + 1) / (N + 1)), where n
                     of the N earlier puzzles hold that answer: the log share
                     of the history it appeared in, so it does not drift as
                     the collection grows.
    pairing_novelty  Mean over the defined answers of -ln(1 + n *
                     PAIRING_SCALE / N), where n of the N earlier puzzles that
                     carry any definition paired this answer with a
                     definition of this head word (definition_head()). A
                     definition is the blog's underlined one, else our
                     annotation's. The pairs are sparse, so the count
                     is scaled to a fixed history rather than smoothed into a
                     share, which would drift with N through its zeros.

    Single-word answers only, in the counts and the means. Phrases are many
    and each recurs rarely however well a solver knows it, so a phrase's count
    measures how phrase-heavy a series is (the Everyman's most of all) rather
    than how familiar the answer is. rarity() judges phrases instead.

    Higher is less familiar. Each is None until HISTORY_FLOOR earlier puzzles
    (earlier defined puzzles, for the pairing) are behind it."""
    blog_definitions()      # loaded once, before the workers fork
    rows = [r for r in parallel.pmap(history_row, puzzle_files()) if r]
    rows.sort(key=lambda r: r[0])
    seen, paired = {}, {}
    n_all = n_defined = 0
    out, i = {}, 0
    while i < len(rows):
        j = i
        while j < len(rows) and rows[j][0] == rows[i][0]:
            j += 1
        day_rows = rows[i:j]
        for _, pid, sols, pairs in day_rows:
            a = [-math.log((seen.get(s, 0) + 1) / (n_all + 1)) for s in sols]
            p = [-math.log1p(paired.get(k, 0) * PAIRING_SCALE / n_defined) for k in pairs] \
                if n_defined else []
            out[pid] = {
                "answer_novelty": sum(a) / len(a) if a and n_all >= HISTORY_FLOOR else None,
                "pairing_novelty": sum(p) / len(p) if p and n_defined >= HISTORY_FLOOR else None}
        # A day's puzzles are added only after all of them are scored, so no
        # puzzle counts one printed the same day.
        for _, _, sols, pairs in day_rows:
            for s in sols:
                seen[s] = seen.get(s, 0) + 1
            for k in pairs:
                paired[k] = paired.get(k, 0) + 1
            n_all += 1
            n_defined += bool(pairs)
        i = j
    return out


def context(base=None):
    """Everything score() reads besides the puzzle: the lexicon, the frozen
    baseline, and the familiarity history."""
    return SimpleNamespace(rank=ranks(), base=load_baseline() if base is None else base,
                           history=history())


def clue_cost(e):
    """One clue's wordplay cost, 0-1, or None when it carries no type."""
    ann = e.get("annotation") or {}
    parts = ann.get("type") or []
    if not parts:
        return None
    cost = max(DEVICE_COST.get(p, DEVICE_DEFAULT) for p in parts)
    cost += STACKING_COST * (len(parts) - 1)
    if not (ann.get("indicators") or []) and not (set(parts) & ALWAYS_UNINDICATED):
        cost += UNINDICATED_COST
    # `assembly.pieces` is the answer broken into the chunks the wordplay builds it
    # from; annotate_prompt.md asks for it on charades, containers and
    # deletions. Two is the floor — every one of those families has at
    # least two parts by definition, so only the extra seams cost.
    pieces = [str(p) for p in ((ann.get("assembly") or {}).get("pieces") or [])]
    cost += SEAM_COST * max(0, len(pieces) - 2)
    # Strip anything that isn't a letter first: pieces are written as the
    # letters they contribute, but a few carry a hyphen or an apostrophe
    # from the answer, and "A-" is a one-letter lookup, not a two.
    cost += OPAQUE_PIECE_COST * sum(
        1 for p in pieces
        if 0 < len([c for c in p if c.isalpha()]) <= OPAQUE_LEN)
    return min(1.0, cost)


def device(puz):
    """Mean wordplay cost. None when the puzzle has no annotations yet.

    Two axes. RECOGNITION: how hard the machinery is to confirm once you see it
    (DEVICE_COST), plus a nudge when the clue names no indicator at all.
    ASSEMBLY: the work of actually building the answer — SEAM_COST per extra
    piece, OPAQUE_PIECE_COST per piece too short to be a synonym. Assembly
    carries the larger share, deliberately; see the note above SEAM_COST.
    """
    costs = [c for c in (clue_cost(e) for e in puz["entries"]) if c is not None]
    # A part-annotated puzzle would report whichever clues happened to be done
    # first, which is not a fact about the puzzle. Require all of it, using the
    # same test the index uses for its `annotated` flag: two definitions of
    # "annotated enough" that disagree ship a band on a puzzle the site calls
    # un-annotated, which is the one thing the band must never do.
    if not costs or not puzzle_is_annotated(puz):
        return None
    return sum(costs) / len(costs)


def acrostic(answer, clue):
    """Whether the answer is the first letters of consecutive clue words."""
    initials = "".join(w[0] for w in (letters(x) for x in clue.split()) if w)
    return bool(answer) and answer in initials


def question_marks(puz):
    """Share of the clues ending in a question mark, ignoring closing quotes,
    whose answer is not an acrostic of them (acrostic()): the mark on
    "Primarily, men attending godliest infant?" flags the all-in-one, not an
    indirect definition.

    None for a puzzle with no clue text. A cross-reference ("See 5") is not a
    clue and is left out."""
    ends = []
    for e in puz["entries"]:
        clue = e["clue"].get("text", "").strip().rstrip("\"'”’)")
        if clue and not re.match(r"(?i)see\b", clue):
            ends.append(clue.endswith("?") and not acrostic(letters(e.get("solution")), clue))
    return sum(ends) / len(ends) if ends else None


def clue_count(puz):
    """The number of clues with an answer, cross-references ("See 5") left
    out. None when the puzzle carries no answers."""
    n = sum(1 for e in puz["entries"] if e.get("solution")
            and (c := e["clue"].get("text", "").strip())
            and not re.match(r"(?i)see\b", c))
    return n or None


def raw(puz, ctx):
    """The measurements, in their natural units, before any scaling."""
    fam = ctx.history.get(puz["id"]) or {}
    return {"checking": None if puz.get("bars") else checking(puz), "rarity": rarity(puz, ctx.rank),
            "device": device(puz), "machinery": machinery(puz),
            "answer_novelty": fam.get("answer_novelty"),
            "pairing_novelty": fam.get("pairing_novelty"),
            "question_marks": question_marks(puz),
            "definition_unrelated": definition_unrelated(puz),
            "clue_count": clue_count(puz)}


def score(puz, ctx):
    """Raw components, their z-scores, and a combined index in standard deviations.

    Missing components are dropped and their weight redistributed, rather than
    filled with an average. The droppable ones — rarity when the lexicon isn't
    fetched, device and machinery when the puzzle isn't annotated yet, the
    novelty counts before HISTORY_FLOOR earlier puzzles exist — are all absent
    for procedural reasons, not because the puzzle is unremarkable, and a
    substituted mean would quietly claim otherwise. Dropping is also cheap here
    because a z-score is already centred: a puzzle is scored on the components
    it has, on the same scale as everything else.
    """
    base = ctx.base
    parts = {k: v for k, v in raw(puz, ctx).items() if v is not None}
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
    # fiat. Scored on the grid and word rarity alone, our eight quiptics came out at
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
            "band": band_of(index, base),
            "raw": {k: round(v, 4) for k, v in parts.items()},
            "z": {k: round(v, 2) for k, v in zs.items()},
            "basis": sorted(zs)}


#: (context, comments, comment_blend) for scored_row(), set by all_scores()
#: before its workers fork.
_SCORING = None


def scored_row(path):
    """(id, rating) for one puzzle file as all_scores() reports it, before the
    percentile, or None for a puzzle score() cannot rate."""
    ctx, comments, cm = _SCORING
    puz = read_puzzle_file(path)
    s = score(puz, ctx)
    if not s:
        return None
    b = blend(puz["id"], s["index"], comments, cm)
    if b is not None:
        s["clue_index"] = s["index"]
        s["index"] = round(b, 3)
        s["band"] = band_of(b, ctx.base)
        s["basis"] = s["basis"] + ["blog comments"]
    return puz["id"], s


def all_scores(base=None):
    """Every puzzle's rating as the badges show it: score()'s clue index, and
    where a Times for the Times post has enough comments stating solve times,
    that index blended with them (blend()). score() itself stays clue-only,
    because the harnesses that choose components measure it against the
    SNITCH, and the comments are solver times too."""
    global _SCORING
    ctx = context(base)
    wordnet()               # loaded once, before the workers fork
    _SCORING = ctx, load_comments(), ctx.base.get("comment_blend") or {}
    # Keyed by ID, not number: two papers can reach the same number and the
    # caller would then get whichever was scored last.
    out = dict(r for r in parallel.pmap(scored_row, puzzle_files()) if r)
    # The percentile is a live comparison and says so — it is the answer to
    # "how does this rank against what's on the site", which genuinely does
    # change as puzzles arrive. The band above it stays put; only this moves.
    idx = sorted(s["index"] for s in out.values())
    for s in out.values():
        below = bisect.bisect_left(idx, s["index"])
        s["percentile"] = round(100 * below / max(len(idx) - 1, 1)) if len(idx) > 1 else None
    return out


def load_comments():
    """puzzle id -> its Times for the Times comment row, from
    tools/blog_comment_difficulty.py. Empty when the table is absent."""
    return json.loads(COMMENTS.read_text(encoding="utf-8")) if COMMENTS.exists() else {}


def comment_raw(row):
    """(log of the commenters' median stated minutes, the share of comments
    saying they did not finish), or None below COMMENT_MIN_TIMES stated times."""
    if not row or row.get("stated_times", 0) < COMMENT_MIN_TIMES or not row.get("median_minutes"):
        return None
    return math.log(row["median_minutes"]), row["dnf"] / row["comments"]


def _blend_z(index, c, m):
    """The mean of the clue index's z and the comment signal's z, the comment
    signal being the mean of the minutes' z and the DNF share's z, each
    against its own series."""
    def z(x, k):
        return (x - m[k]["mean"]) / m[k]["sd"]
    return (z(index, "index") + (z(c[0], "log_minutes") + z(c[1], "dnf")) / 2) / 2


def comment_moments(values, comments):
    """{series: moments of the clue index, log minutes, DNF share and the raw
    blend}, over the puzzles of each series that have both an index (`values`,
    puzzle id -> index) and a comment signal. A series needs
    COMMENT_SERIES_MIN such puzzles, or it has no blend."""
    by = {}
    for pid, x in values.items():
        c = comment_raw(comments.get(pid))
        if c is not None and x is not None:
            by.setdefault(pid.rpartition("-")[0], []).append((x, c))
    out = {}
    for series, rows in sorted(by.items()):
        if len(rows) < COMMENT_SERIES_MIN:
            continue
        m = {"index": moments([x for x, _ in rows]),
             "log_minutes": moments([c[0] for _, c in rows]),
             "dnf": moments([c[1] for _, c in rows])}
        if not all(v["sd"] for v in m.values()):
            continue
        m["blend"] = moments([_blend_z(x, c, m) for x, c in rows])
        out[series] = m
    return out


def blend(pid, index, comments, cm):
    """The index moved halfway toward what the commenters reported, in the
    series' own units: the blend restandardised and put back on the scale of
    the clue index of the same puzzles, so a series' mean and spread do not
    move. None when the puzzle or its series has no comment signal."""
    m = cm.get(pid.rpartition("-")[0])
    c = comment_raw(comments.get(pid))
    if m is None or c is None:
        return None
    b = (_blend_z(index, c, m) - m["blend"]["mean"]) / m["blend"]["sd"]
    return m["index"]["mean"] + m["index"]["sd"] * b


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
    ctx = context()
    before = all_scores()
    cols = {}
    for path in puzzle_files():
        for k, v in raw(read_puzzle_file(path), ctx).items():
            if v is not None:
                cols.setdefault(k, []).append(v)
    comps = {}
    for k, vals in sorted(cols.items()):
        comps[k] = moments(vals)
    # Not a component: the composite's own mean and spread, frozen alongside
    # them so BANDS can be written in real standard deviations. It has to be a
    # second pass, because the index it describes is built out of the first.
    clue = {p: s["index"] for p, s in all_scores(comps).items()}
    comps["index"] = moments(list(clue.values()))
    # The comment blend's per-series moments, over the clue index alone: comps
    # has no comment_blend yet, so all_scores() above did not blend.
    comps["comment_blend"] = comment_moments(clue, load_comments())
    BASELINE.write_text(json.dumps(
        {"_comment": "Frozen reference distribution for tools/difficulty.py. "
                     "Regenerate deliberately with --rebaseline; every stored "
                     "rating shifts when you do.",
         "components": comps}, indent=2) + "\n", encoding="utf-8")
    after = all_scores(comps)
    moved = [(n, before[n]["band"], after[n]["band"]) for n in sorted(after)
             if n in before and before[n]["band"] != after[n]["band"]]
    for k, c in comps.items():
        if k == "comment_blend":
            for series, m in c.items():
                print(f"baseline comment_blend {series}: n={m['index']['n']}")
            continue
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
    return [(series_meta.puzzle_day(meta[p]).weekday(),
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

      CTC           Per clue, the one place a human's difficulty is timed:
                    Cracking the Cryptic's solve videos give each clue the
                    wait from first reading it to solving it
                    (tools/ctc_transcripts.py solves). The per-clue forms of
                    the components, weighted as WEIGHTS weights them, against
                    that wait within each video; and the wait against the
                    Times for the Times comments' hard flags on the same clues,
                    which shows the wait measures difficulty at all.
                    `ctc_transcripts.py solvecheck` prints every component.
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
            # The badges blend in blog comments, which are solver times like
            # the NITCH; the clue index alone is what the components answer for.
            c = [s.get("clue_index", s["index"]) for p, s in scores.items()
                 if p in snitch and p.rpartition("-")[0] == series]
            n_bl = sum("clue_index" in s for p, s in scores.items()
                       if p in snitch and p.rpartition("-")[0] == series)
            print(f"              {'':<12} clue index alone rho = {_spearman(a, c):+.3f} "
                  f"({n_bl} blended with blog comments)")
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

    import ctc_transcripts
    if ctc_transcripts.SOLVES.exists():
        t = ctc_transcripts.solve_table()
        wait = 1 + ctc_transcripts.CTC_MEASURES.index("ctc_wait")
        pairs = t.cols["all"]["composite"]
        r, n, p = ctc_transcripts._rho_p([x[0] for x in pairs], [x[wait] for x in pairs])
        rs = [x for v in t.per_video.values() for x in v]
        hr, hn, hp = ctc_transcripts._rho_p(*zip(*t.human[("ctc_wait", "hard")]))
        print(f"\nCTC           {t.clues} clues timed in {t.videos} solve videos")
        print(f"              per-clue index vs wait to solve, within video: rho = {r:+.3f} "
              f"(n={n}, p = {p:.2g}), positive in {sum(x > 0 for x in rs)}/{len(rs)} videos")
        print(f"              wait vs Times for the Times hard flags: rho = {hr:+.3f} (n={hn}, p = {hp:.2g})")
    return 0


def main():
    if "--validate" in sys.argv:
        if not BASELINE.exists():
            print("no baseline — run --rebaseline first", file=sys.stderr)
            return 1
        return validate()
    if not LEXICON.exists():
        print("note: tools/data/lexicon.tsv not fetched — scoring without the "
              "rarity component (bash tools/fetch_lexicon.sh)", file=sys.stderr)
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
