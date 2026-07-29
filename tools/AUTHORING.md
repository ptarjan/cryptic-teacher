# Setting a puzzle: filling the grid

`tools/grid_fill.py` is step one of setting a cryptic. It produces a legal
British grid and a set of answers; a human writes the clues afterwards. It does
not write clues, and it never will — that judgement is the whole point of the
site.

## Quick start

```bash
bash tools/fetch_lexicon.sh          # once: ~26 MB of word data, gitignored
python3 tools/grid_fill.py --size 11 --seed 1
python3 tools/grid_fill.py --size 11 --seed 3 --fills 60 --out my_fill.json
python3 tools/grid_fill.py --size 13 --check-only     # just validate a template
python3 tools/clueability.py --word CARPET            # why a word scores what it does
```

The worked example lives in `tools/data/sample_fill_11.json`, produced by:

```bash
python3 tools/grid_fill.py --size 11 --seed 3 --fills 60 \
    --min-familiarity 25 --min-clue 40 --out tools/data/sample_fill_11.json
```

## The grid conventions, and why each one

Every rule is a named `check_*` function in `tools/grid_fill.py`, and a template
that fails any of them is **refused, not filled**. That is not ceremony: the
first three 11x11 patterns written by hand for this tool were all illegal
(three-letter entries, orphan lights, a disconnected region), and the checker
caught all three.

| check | rule | source |
| --- | --- | --- |
| `check_shape` | square, odd side | universal in British blocked grids; an odd side gives a true centre for the symmetry |
| `check_symmetry` | 180-degree rotational symmetry | universal; a Guardian grid looks the same upside down |
| `check_min_entry_length` | every entry at least 4 letters | Exet. Nine of the twelve Guardian grids in `puzzles/` agree; three bottom out at 3, so `--min-entry 3` exists as an escape hatch |
| `check_every_light_is_used` | every light is in at least one entry | a light in no entry can never be filled. Note a light in exactly ONE entry is fine — that is an unchecked letter, which British grids have and American ones do not |
| `check_unchecked_runs` | no two adjacent unchecked letters | Exet's strict reading, and what all twelve measured Guardian grids actually do. `--relax-unches` allows the looser published convention (two mid-entry, never at an end) |
| `check_entry_checking` | no entry has more unchecked than checked letters; 9+ may have one more | Exet. Stricter than "at least half rounded down": a 5-letter entry needs 3 checked, not 2 |
| `check_connectivity` | all lights form one connected region | a detached corner is a second crossword |
| `check_checked_ratio` | 28-52% of all letters checked | measured: the twelve Guardian grids in `puzzles/` sit at 31-40% |
| `check_through_cut` | at least 3 lights bridge every cut line | Exet recommends 4 on a 15x15; scaled by side length. A solver stuck in one region needs several ways to carry letters into the next |

Sources: [Exet](https://github.com/viresh-ratnakar/exet), Viresh Ratnakar's
British-grid editor, whose validator is the strict reading;
[georgeho.org/counting-cryptics](https://georgeho.org/counting-cryptics/), which
measured published grids and agrees on symmetry, odd side, connectivity and
half-checking, but permits two consecutive unches mid-entry. Where they differ,
the strict rule is the default and the loose one is a flag, so the choice is
visible rather than buried.

Worth internalising: **the global checked ratio and the per-entry rule are
different rules.** Folklore says "half the letters are checked"; real grids check
31-40% overall while keeping every individual entry at least half checked. Both
are "half checked"; only one is true.

The two shipped templates were found by searching symmetric block patterns and
keeping the ones that pass every check. Change them freely — they are plain text
blocks of `#` and `.` at the top of `grid_fill.py`, and `--template FILE` loads
one from disk.

## Why the fill is clueability-aware

**A grid that fills is not a grid that can be clued.** This is the failure mode
that separates a crossword-shaped constraint solver from a setting tool, and it
is not hypothetical — every example below came out of this tool's own runs:

* An early fill answered **KILOMETERS** in a Guardian-style grid. Legal, common,
  and an American spelling: a British solver would call it an error. Fixed
  systematically, not by hand — the Lufz lexicon's Britain region lists 5,212
  such spellings and the filler now drops all of them.
* Another produced **PARC** and **PROTO** in the corners. PARC is French; PROTO
  is a prefix, so there is no definition to write. Both are perfectly good
  *pieces* of wordplay and impossible *answers*.
* Another produced **AMINO**, which only ever appears in "amino acid". A setter
  cannot define it without lying.
* **ENTRUSTED** is the quieter case: a common word, no anagram, no reversal, no
  container, one dull charade. It is not wrong, it is just a clue nobody enjoys
  writing or solving. A filler blind to this fills a grid with them.

So `tools/clueability.py` scores every word once (cached) on the hooks a setter
actually uses — anagram, near-anagram (letters minus a standard abbreviation),
charade, container, homophone, reversal, deletion, hidden-ability, and a weak
double-definition proxy — plus a **fairness floor** from the lexicon's
importance ranking. The score is used twice:

1. **as an ordering**, so the backtracking search reaches for the best-hooked
   word first, and
2. **as a floor** (`--min-clue`, `--min-familiarity`), so a word below it is not
   a legal fill at all.

The reported distribution is how a human judges the result. Fills are ranked by
their **worst** entry before their mean, because one unclueable answer sinks a
grid however nice the other nineteen are.

### The outer loop: veto and blacklist

Scoring is a heuristic and will occasionally still hand over an unclueable word.
So `fill()` is a **generator with a veto hook**, not a one-shot:

```python
banned = {}
gen = grid_fill.fill(grid, by_len, veto=lambda w: banned.get(w), seed=1)
solution, _ = next(gen)
# ...try to clue it; if BANANA defeats you:
banned["BANANA"] = "no definition that isn't a giveaway"
solution, _ = next(gen)        # search RESUMES; BANANA is gone
```

Vetoing a word unwinds the search to the frame that chose it (see `Revoked`)
rather than restarting, so the next fill is nearly free. The first version of
this only filtered *new* candidates, which meant a resumed generator cheerfully
re-offered the banned word for the rest of the subtree — worth knowing if you
touch that code.

Rejections belong in `tools/data/unclueable.json`, **with a reason**, so the
knowledge accumulates instead of being rediscovered — the same principle
`STYLE.md` applies to product feedback. Most of the current entries exist because
Lufz folds proper nouns into lowercase entries (`isProperNoun` only inspects
capitalisation, so it cannot separate ERIC-the-name from a common noun). Until
there is a better signal, names get caught by the blacklist.

## Word data

`bash tools/fetch_lexicon.sh` fetches the [Lufz
lexicon](https://github.com/viresh-ratnakar/lufz) and
[exet-lexicon.js](https://github.com/viresh-ratnakar/exet) (both MIT) and runs
`tools/build_lexicon.js`, which loads them headless in a Node `vm` and writes
`tools/data/lexicon.tsv`. Lufz is UKACD18 — the classic British cryptic word
list — cleaned up and augmented with Wikipedia-derived importance ordering,
CMUdict pronunciations and Porter2 stems.

Those extras do real work here:

* **importance rank** is the fairness floor. `/usr/share/dict/words`, the
  fallback when the lexicon is missing, has no score column at all, so with it
  there is *no* fairness floor — the filler says so loudly and the fill will
  contain obscurities.
* **pronunciations** make the homophone hook a phonetic fact rather than a
  spelling guess.
* **stems** give each word a morphological family size (EARTH has forty
  relatives, ERIC has two), which is a better double-definition proxy than raw
  frequency.
* **the Britain region** is the British-spelling filter described above.

Licences and what is committed versus fetched: `tools/data/README.md`.
`tools/data/abbreviations.json` is hand-built (H = hard, R = river…) and is
*meant to grow*: add to it when a clue-writing pass wants an abbreviation it
lacks.

## What the clue-writing step gets

`--out FILE` writes JSON whose entries deliberately mirror the shape used in
`puzzles/*.js`, so a clued puzzle can be assembled without reshaping anything:

```json
{
  "id": "1-across", "number": 1, "direction": "across",
  "position": {"x": 0, "y": 0}, "length": 4,
  "solution": "PACE", "checkedPattern": "PaCe", "checkedIndices": [0, 2],
  "clueability": 73, "familiarity": 29, "hooks": "ANCXDH"
}
```

For each entry the clue writer therefore has: the answer, where it sits, which
letters are checked (uppercase in `checkedPattern`; those are the letters a
crossing clue will confirm, so an unchecked letter must be gettable from the
wordplay alone), and which mechanisms are available — `hooks` flags are
**A**nagram, **N**ear-anagram, **C**harade, **X** container, homophone (**P** for
phonetic), **R**eversal (lowercase `r` = contains a reversed word),
**D**eletion, **H**ideable. `python3 tools/clueability.py --word PACE` prints the
actual splits behind those flags.

Still to be written by a human, per entry: `clue`, and the `annotation` block
that `tools/validate_annotations.py` and `STYLE.md` govern — type, definition,
indicators, blocks, walkthrough. Note that the annotation rules bite here: a
definition must match the answer's part of speech, every content word of the clue
must be accounted for, and the type must name every mechanism used. Choosing an
answer with several hooks is what makes that possible.

## Performance notes

Filling is backtracking with minimum-remaining-values ordering over
letter-position bitmask indexes, forward-checking every crossing slot, a node and
time budget per restart, and random restarts with jittered candidate ordering. An
11x11 fills in well under a second; `--fills N` generates N distinct fills and
keeps the best. If a grid will not fill, the useful levers are (in order)
`--seed`, `--fills`, `--restarts`, then lowering `--min-clue` — and if you find
yourself lowering the floor a lot, the template is the problem, not the budget.

Concretely: the first 13x13 template shipped here was legal but nearly
unfillable, because it had full-width 13-letter entries and only ~200 clueable
13-letter words exist above the floor, two of which then had to interlock with
12s. The current 13x13 has a maximum entry of 7 and fills instantly. A grid full
of maximal entries is a grid you will fight.

## What blind grading found

Twenty original clues (A001) were scored against 60 published clues for the same
answers, drawn from the Times, Guardian, FT and Independent blogs. Three judges,
no provenance shown, five axes from `tools/data/grading_rubric.md`. Build the
packets with `tools/grade_clues.py`, score them with `tools/score_grading.py`.

                  ours   human    gap
    surface       3.10    3.73   -0.63
    misdirection  2.47    3.68   -1.21
    penny-drop    2.43    3.41   -0.98
    economy       4.17    4.02   +0.15
    fairness      4.72    4.00   +0.72
    OVERALL       3.38    3.77   -0.39

Beat the best human clue for the same answer on 1 of 20. Judges asked to pick the
machine-written clue were right 50% of the time against 25% chance.

Read that table as a diagnosis, not a scoreboard. **Soundness is solved and it is
not what is missing.** The +0.72 on fairness is real and it is earned by
`validate_annotations.py` — the human clues in the field included an anagram with
no anagram indicator, a hidden word with no hidden indicator, and one clue with no
derivation at all, and every judge found them. Our clues never fail that way.

The loss is entirely in **misdirection and penny-drop**, and both come from the
same habit: writing the mechanism down in order and putting a sentence around it
afterwards. `Later rewritten, to change` is fodder, indicator, definition, in that
order, fenced off with a comma. It is perfectly fair and it is not a clue anyone
would enjoy. Our worst six all have that shape.

So the rule that follows is about *sequence*, not vocabulary:

> Decide what the clue is going to be **about** before you decide how it works.
> A surface idea — a scene, a joke, a piece of news — is the thing being written;
> the mechanism has to be fitted into it. Assembling parts and then smoothing the
> result is what produced every clue we lost with.

Two habits to break specifically, both mechanically detectable and both flagged by
`tools/clue_quality.py`:

- **Do not weld the definition on with a copula.** `Cold heap is inexpensive`
  makes the clue assert its own answer. Real setters make the definition earn its
  place in the sentence's meaning.
- **Do not stand the anagram indicator next to its fodder.** `Naples rebuilt`
  points straight at the anagram. Separate them, or choose an indicator that reads
  as ordinary description in the surface.

And one thing not to over-correct: **economy was already fine** (+0.15), so the
answer is not "write longer clues". `terse` fires on ten of the twenty, including
the best ones. More words only help if they are buying a surface idea.

## The surface is a sentence, and it carries a joke

The six worst clues were rewritten under the rule above, and the rewrites were
read back as: *they still do not read as real sentences or have cute puns*.
`That Conservative lot, and mean with it (5)` is the shape to recognise — a
grammatical fragment with no finite verb, assembled out of two definitions and a
conjunction, and not a thing any human being has ever said. Two tests, both
applied before the clue counts as finished:

**Say it aloud with no crossword in mind.** If it is not something a person would
actually say — a headline, a complaint, a line of gossip, a piece of advice — it
is not finished. Not "is it grammatical"; grammatical fragments pass that and
still die on the page. The question is whether anyone would ever utter it.

**Name the joke in one clause.** *She hopes he'll change — at the altar.* *The
bully's name-calling turns out to be a list of stars.* If you cannot say what the
joke is in one clause, there is no penny-drop for the solver to have, and no
amount of polishing the wordplay will put one there.

And the honest note, because the rule in the previous section did not bind. Faced
with a mechanism that was already chosen, the author kept it and went hunting for
a surface that would accommodate it — mechanism-first with a coat of paint, which
is the thing the rule was written to stop. **The rule has teeth only if you are
willing to throw the mechanism away.** Four of the six rewrites that finally
worked changed clue type entirely; three of them are in A001 — CHEAP went from
charade to anagram, SIDE from container to hidden, ALTER from anagram to
homophone. The sentence came first and the mechanism had to be found inside it.

`tools/clue_quality.py` flags `not-a-sentence`, `imperative-opening` and
`unattested-phrasing` for this, but read its calibration table before you trust
them: the first fires on nearly half of all published Times clues, and the third
has never fired on one of ours. Verblessness is not the disease and strange
phrasing is not the disease. Both tests above are still judgements, made aloud.
