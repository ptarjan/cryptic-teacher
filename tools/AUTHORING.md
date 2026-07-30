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
- ~~**Do not stand the anagram indicator next to its fodder.**~~ **Withdrawn —
  this was wrong.** It was written from a judge's remark and never checked against
  practice. Measured over 38,830 published anagram clues with a structurally
  verified fodder, **88.9% put the indicator directly against it**; `Naples
  rebuilt` is the normal shape, not a tell. The half of the advice worth keeping
  is the second half: choose an indicator that reads as ordinary description in
  the surface. Where it sits matters far less than whether it sounds like an
  instruction. See the concealment section of `tools/clue_quality.py` for the
  measurement, including why the position effect that looked significant
  (p=0.03) does not survive being one of six cuts tried on thirteen clues.

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

## The standard is a pub joke, not a rubric score (feedback 2026-07-29)

Everything above was written from the blind-grading round, and the round-two
rewrites were judged against it and passed. Then a human read the five clues that
had beaten their entire human field and said: *those aren't very good, none of
those are real sentences.* He was right, and it invalidates the scoreboard rather
than the clues:

> `Newspaper: Morgan dropped a million (5)` is a colon-gloss. `Concerning hotel
> staff, the press (9)` is a verbless fragment opening on a naked RE marker.
> `Dwindles as time enters the Lords (6)` is a front definition welded to a
> narration of its own wordplay. `Pool turned into a circuit (4)` wears "turned"
> as a visible instruction. **They won a blind comparison because the judges were
> rewarding rubric-compliance.** Beating a field is not evidence of quality when
> the field and the judges share a rubric.

The target to write against is a named clue, not a table:

    Two girls, one on each knee (7)               = PATELLA
    Die of cold (3,4)                             = ICE CUBE
    Amundsen's forwarding address (4)             = MUSH
    A stiff examination (4-6)                     = POST-MORTEM
    Bergamot herbal extract for bodybuilder? (6)  = MOTHER

Short, complete, funny, and the definition is invisible because it is
load-bearing in the sentence. There is no crossword furniture anywhere in them —
and note that PATELLA is a plain charade, so "no furniture" does not mean "no
mechanism". It means `one on each knee` is simultaneously the assembly
instruction and the picture.

MOTHER (added 2026-07-30) is the same lesson for a hidden word, and it is the
sharpest example of Rule 1 below — **exactly two pieces, nothing superfluous**:

    Bergamot herbal   wordplay fodder — berga|MOT HER|bal
    extract           the hidden indicator, and also a real herbal product
    for               joinery
    bodybuilder?      definition

Five words, no waste, and every one of them is doing double duty. `extract` is
the crossword instruction *and* the thing a herbal shop sells, so the indicator
never surfaces as an instruction. `bodybuilder?` is the joke: the reader is
holding a gym, the answer is that mothers build bodies. The `?` is doing its
proper job — flagging a definition that is true but whimsical — not apologising
for a loose one. Contrast the hidden words in A001 (`Milan club buried in
winter`), which are sound but where the container word is visibly there to hide
letters.

Test a candidate against this one before shipping it: can you write the
four-line table above for your clue, with every word of the surface landing in
exactly one row?

The rules that follow, applied to all twenty A001 clues in the 2026-07-29 pass:

1. **A complete English utterance.** Subject and finite verb, or an idiom a
   person actually says. Imperatives are fine (`Die of cold`).
2. **Banned furniture:** definitions glossed off behind a colon or comma; clues
   opening `Concerning` / `About` / `Regarding`; `Sounds like`; any clue that is
   a bare noun phrase listing wordplay and then meaning.
3. **The pun must be nameable and cute.** The reader should smile. If the only
   pleasure is that the mechanism resolves, the clue fails, however sound it is.
4. **Shorter is better** — the target class runs 3-6 words.
5. **Mechanism is chosen last**, out of material the sentence already contains.
   If nothing fits, find a different sentence; never repair it by narrating the
   wordplay.

The honest cost, recorded so the trade is visible: pushing for the pun raised the
cryptic-definition count in A001 from one to six, because several answers (PACE,
THERE, ARMED, ORGAN, PETERS, REPORTERS) yielded a funny sentence and no funny
mechanism. A puzzle that is a third cryptic definitions is unbalanced by any
published standard. If a future pass can find Patella-class charades for those
six, it should — but a sound mechanism is not a reason to keep a clue nobody
enjoys reading. That pass happened; the next section is what it found.

## The sentence AND the wordplay (feedback 2026-07-29, same day)

The twenty rewritten clues were read back and the verdict was one sentence:

> **They are good for sentences now but they don't have wordplay anymore.**

He was right, and the arithmetic is in the section above: six of twenty had
become bare cryptic definitions. So the rule, in his terms and now permanent:

> A clue needs the sentence **and** the wordplay. Both, in the same handful of
> words. A funny sentence with no mechanism is a cryptic definition, and a
> cryptic definition is a treat, not a technique: **at most two in a twenty-clue
> puzzle**, enforced by `tools/validate_annotations.py` as an ERROR.

Two routes to the same answer is the entire deal. A joke with no mechanism is a
quiz question — the solver either shares your reference or is stuck with nothing
to work on, and no crossing letter helps them reason. That is why the cap is a
number and not a preference.

**Why this failure mode recurs, and will recur again.** A funny sentence is much
easier to find than a funny mechanism. Every minute spent chasing the pub-joke
standard is a minute of pressure to drop the mechanism, because the mechanism is
the part that will not bend. Each of those six clues was *individually*
defensible; the damage was only visible when you counted them, which nobody
does by eye. Hence a whole-puzzle check rather than a per-clue one. The ceiling
of 2 is measured, not invented: across the annotated puzzles in `puzzles/`, only
30039 carries any cryptic definitions at all, and it carries exactly two.

**The second half of the rule: a narrated mechanism is not a hidden one.** Two
A001 clues had a real mechanism and still failed, because the indicator was an
instruction wearing a sentence:

    There's a bit of the president in our team (4)   SIDE
    Every ship needs a leader in front (10)          LEADERSHIP

`a bit of` and `in front` are not description, they are the setter leaning over
the solver's shoulder saying *take part of this word* and *put that one first*.
Both were fixed by making the indicator carry ordinary meaning, or by removing
it entirely:

    There's a mole in the president's team (4)          in = the only signal, and
                                                        a mole really is buried
                                                        in pre-SIDE-nt
    Leaders get hip and mistake it for direction (10)   a charade needs no
                                                        indicator at all

The test to apply: **would this word be in the sentence if there were no
crossword?** `in` survives it. `a bit of` does not. Watch especially for
`a bit of`, `some of`, `in front`, `turned`, `rebuilt`, `back` and `about` doing
nothing but announcing the machinery.

What the pass actually produced, as a worked record of what "both" costs — four
cryptic definitions converted, two kept:

| answer | was (no mechanism) | now | mechanism |
| --- | --- | --- | --- |
| THERE | Where the grass is greener | Time here would be better spent yonder | charade, T + HERE |
| REPORTERS | These porters carry stories, not bags | The press are riddled with pet errors | anagram of PET ERRORS |
| ORGAN | The only instrument you can donate | The donor's dreadful groan comes from the instrument | anagram of GROAN |
| PETERS | What Peter does when Paul gets paid | With the Queen among the pets, interest dwindles | container, ER in PETS |
| PACE | Expectant fathers do it up and down | *kept* | — |
| ARMED | What the Venus de Milo isn't | *kept* | — |

PACE and ARMED are the two allowed cryptic definitions. They were kept because
their mechanisms are the weakest available, not because their jokes are the
best: PACE offers only an anagram of CAPE or the charade P + ACE, neither of
which supports a joke, and every synonym of ARMED is a phrase (`carrying a
weapon`, `under arms`), so no clue can define it tightly enough to be worth the
machinery. That is the honest test for spending one of your two: **not "is this
funny" but "is the mechanism I would swap it for actually worse than nothing".**

## Exactly two pieces (feedback 2026-07-29, same day again)

The twenty clues above were read back once more, and the verdict was about the
words that are not the clue:

> **A good cryptic clue doesn't have anything superfluous which isn't directly
> part of the wordplay. It should be exactly two pieces. Definition, optional
> joinery and wordplay.**

So every single word must be doing one of exactly three jobs: it is part of the
DEFINITION, part of the WORDPLAY (fodder or indicator), or a LINK WORD joining
the two. Nothing else. A word that exists only to make the surface read nicely
is a fault, **however good the resulting sentence** — and it has one signature in
this schema: a block with `"gives": ""`, the "surface only" padding STYLE.md's
leftover-words rule tells the annotator to record. Nine of the twenty A001 clues
carried one, which is what made this a rule instead of a note.

`check_two_pieces()` in `tools/validate_annotations.py` makes it a hard ERROR,
scoped by `is_authored()` to puzzles whose id starts with a letter. That scoping
is load-bearing, not politeness: real setters pad, and the annotator has to be
able to say so faithfully. Unscoped, the check fires **eighteen times on 30039
alone** — mostly on double definitions, where a block legitimately carries no
letters. A check that lights up honest work is a broken check.

The flip side of that scoping is that the daily sweep globs `[0-9]*.js` and so
never sees an authored puzzle. After editing `tools/data/authored_*_clues.json`,
rebuild and validate **by id** — this is the mandatory step, not optional:

```bash
python3 tools/build_authored_puzzle.py --clues tools/data/authored_A001_clues.json \
    --id A001 --name "Cryptic Teacher No 1" --setter "Cryptic Teacher" --date 1785283200000
python3 tools/validate_annotations.py A001     # must say 20/20 annotated — OK
node --check puzzles/A001.js && node tools/smoke_test.js
```

**Why this recurs, and the deeper point.** A funny sentence is easy if you are
allowed filler: put `There's a…`, `Our…`, `she hopes he'll…` around any two
pieces and something readable falls out. Banning filler is what separates a clue
from a joke that happens to contain the answer. The rule makes the job harder,
not easier — you now need every word to serve the machinery *and* the sentence
to be funny, which is the actual craft. Expect to throw candidates away; the
rejects for this pass are logged with reasons in the commit's checkpoint.

Worked before and after, all nine:

| answer | was (padding in **bold**) | now | mechanism |
| --- | --- | --- | --- |
| ORGAN | **The donor's** dreadful groan comes from the instrument | The instrument makes a dreadful groan | anagram of GROAN |
| INTER | Milan club bury **the opposition** | Milan club buried in winter | hidden in w-INTER |
| PLEASE | Delight **mother** with the magic word | Delight in the magic word | double definition |
| PETERS | With the Queen among the pets, **interest** dwindles | Surrounded by pets, the Queen dwindles | container, ER in PETS |
| SIDE | **There's a mole** in the president's team | *clue unchanged, re-annotated* | hidden in pre-SIDE-nt |
| REPRESENTS | **Our** rep resents **the people** he speaks for | Rep resents what he stands for | charade, REP + RESENTS |
| STOREY | Ground floor, and **the world's your** oyster | The oyster lives on the ground floor | anagram of OYSTER |
| ARGUE | **There's** a row among the star guests | *clue unchanged, re-annotated* | hidden in st-ARGUE-sts |
| ALTER | At the altar **she hopes he'll** change | Husband slips out of the halter to change | deletion, HALTER less H |

Two of the nine were **mis-annotation, not filler**, and that is a legitimate
outcome the rule has to leave room for:

* SIDE's `There's a mole in` is not padding, it is the hidden-word **indicator**.
  A mole is a thing concealed inside an organisation; the phrase says *something
  is buried in here* without a single word of crossword instruction, which is
  exactly what an indicator is supposed to do. The previous annotation even said
  so ("it is also a fair description of what the clue is up to") and still filed
  it under surface.
* ARGUE's `There's` is **joinery**. It carries no letters and it is not
  definition, but it is the finite verb that makes the clue an utterance rather
  than a noun phrase. It belongs in `linkWords`, where the app already greys it
  and tells the learner there is no mechanism hiding in it.

The test for that call: does the word contribute letters, restrict the parse, or
hold the sentence together grammatically? Anything else is filler. Note the
asymmetry — an indicator or a link word is *claimed*, so it can be shown to the
solver; padding can only be apologised for.

**Is shorter usually the answer?** Mostly, and the numbers are honest about the
exception. The seven rewritten clues went 49 words to 43 (mean 7.0 to 6.1; all
twenty went 139 to 133); four got shorter, INTER and STOREY stayed the same
length, and ALTER got one word LONGER because the padding-free version needed a
real mechanism (HALTER less H) where the padded one had leaned on a homophone
plus a joke told in the padding. Padding is a *symptom* of a clue a word or two
too long, but the cure is finding the mechanism the sentence can pay for, not
cutting words until it fits.

**And the cryptic definitions.** Under a strict reading of "exactly two pieces",
PACE and ARMED fail outright: they have one piece, a definition, and no wordplay
at all. They were left in place deliberately. The rule as stated governs
*superfluous* words, and in a cryptic definition every word is part of the
definition, so nothing is superfluous; the count, not the anatomy, is what keeps
them honest, and `MAX_CRYPTIC_DEFINITIONS` already holds that at two. Recorded
for whoever revisits it: **ARMED is an anagram of DREAM**, and `Venus de Milo's
broken dream` is a real semi-&lit with `broken` doing double duty on a broken
statue. It was not applied because it is a bare noun phrase, which trades the
missing mechanism for a hard-rule-1 failure. If the two CDs ever have to go, that
is the clue to start from.

## When the blocks already told them (feedback 2026-07-29)

> **When you basically give the whole answer in the building blocks you don't
> need to have the full walkthrough.**

The `blocks[]` rung already lays the answer out fragment by fragment, letter by
letter, with a note on each. A walkthrough that then re-narrates the same steps
is padding in the teaching UI, and it arrives at exactly the moment the learner
has stopped needing it. All twenty A001 walkthroughs ran 44-63 words, median 54,
and every one of them restated its own blocks.

What earns its place is the thing the blocks **cannot show**:

* why the surface misleads you (`the corgis are the misdirection`),
* the joke, named in one clause (`the rep who resents is, letter for letter, the
  man who represents`),
* a convention the solver may not know (`ER = Queen`, `worker = ANT`,
  `H = husband`),
* why a definition is fair when it looks as though it is not.

Trimmed on that principle the same twenty run 19-42 words, median 32 — which is
the median of the 231 published-puzzle walkthroughs in `puzzles/`, arrived at
independently. `check_walkthrough_budget()` warns above 45 words (the published
90th percentile is 42) whenever there is a blocks rung above it.

Two things to know before touching this:

* **The walkthrough may be short but never absent.** `ladderSteps()` in `app.js`
  always pushes the "Full walkthrough" rung, and the validator requires the
  field, so an empty one renders as a labelled rung with a blank paragraph — a
  visual hole plus a missing home for the mechanism line on clues with no blocks.
* **The check is a budget, not a redundancy detector,** and the code says so. A
  semantic version was built and thrown away: scoring the fraction of
  walkthrough vocabulary already present in the clue and blocks gave 0.21 for
  the bad A001 set, 0.16 after the rewrite and 0.30 for published puzzles — the
  good walkthroughs scored *worse* than the bad ones, because naming the joke
  means reusing the clue's own words. Don't rebuild it without new evidence; the
  judgement half of this rule is procedure, not machinery.

## The joints: link words, adjacency, direction (feedback 2026-07-30)

The clue offered as the best of the pass was rejected, and the two objections
were both structural. Here is what was offered, with its annotation:

    The oyster lives on the ground floor (6)   = STOREY

    The oyster    fodder
    lives on      link
    ground        anagram indicator
    floor         definition

> **A link word has to stand in for an equals sign**, and **an anagram
> indicator has to be next to the fodder it operates on.**

Both faults are in that one clue. `lives on` asserts no equivalence between
wordplay and definition — it is surface padding wearing a link word's coat,
which makes the clue three pieces (wordplay, PADDING, definition) and a direct
breach of "Exactly two pieces" above. And `ground` cannot reach back over
`lives on the` to shuffle `The oyster`: an indicator only operates on what it
touches.

**The lesson underneath both, and the reason this one is worth a section: STOREY
felt like the best clue in the set precisely because of the fault.** The padding
is what made the surface smooth. `The oyster lives on the ground floor` scans
like a line from a nature programme, and it scans that way because three of its
words are free to serve the picture instead of the machinery. A sound clue has
to buy its surface with words that are already working. **Surface quality is
therefore not evidence of soundness — it is very often evidence against it,
because the easiest way to a smooth surface is to stop paying for it.**

A third fault of the same family turned up while auditing for the first two, and
it survived calibration:

> **A reversal indicator must point the way the entry runs.** `Back at the pool
> for another circuit (4)` = LOOP was **14-DOWN**. There is no backwards on a
> vertical axis.

### The three rules

| rule | check | what it allows |
| --- | --- | --- |
| Link words are an equals sign | `check_link_words_are_equivalences` | equivalence (`is`, `'s`), derivation (`gives`, `makes`, `becomes`, `yields`, `means`, `leads to`, `indicating`, `to locate`), prepositional joining (`for`, `from`, `of`, `in`, `with`, `after`), and grammatical glue. Nothing else — `EQUIVALENCE_LINKS` is the whole rule |
| An indicator operates on what it touches | `check_indicator_adjacency` | only `FODDER_GLUE` between an anagram indicator and its fodder (`was`, `is`, `a`, `the`, `of`, `in`, `with`), plus the definition, which does sometimes sit in the gap |
| A reversal runs along the entry | `check_reversal_direction` | across: `back`, `returning`, `retreating`, `west`. Down: `up`, `rising`, `climbing`, `lifted`, `raised`, `from below`. Neutral (`turning`, `about`, `overturned`, `revolutionary`, `reversal`) is always safe |

All three are ERRORs, scoped by `is_authored()` like the two-pieces rule.

### Calibration, which is the part that matters

The standing discipline: **a check that flags Araucaria is a broken check.** Run
every authoring rule across the eight annotated Guardian puzzles before trusting
it, and keep the count:

```bash
python3 tools/validate_annotations.py --unscoped 30039 30040 30041 30042 30043 30044 30066 30067
```

`--unscoped` exists for exactly this and is not a mode to ship in. What it found:

| check | published sample | hits |
| --- | --- | --- |
| link words are equivalences | 2 declared link words, plus 105 unclaimed joinery-position words as a proxy | 0 (after adding `after` and `having`, the only two misses) |
| indicator adjacency | 42 anagram clues, 39 with a locatable fodder span | 0 |
| reversal direction | 19 reversal clues | 0 |

Two of those numbers are worth reading closely.

* **The link-word corpus is thin — two instances in 234 entries** — so the
  whitelist could not be calibrated directly, and a second measurement was
  built rather than shrugged at: every clue word the annotation claims for
  nothing is a word standing in the joinery position, and there are 105 of
  those. Four fell outside the whitelist, all of them grammatical (`after` x3,
  `having`), and the list was widened. When a corpus is too small to calibrate
  against, find the proxy with the bigger sample; do not ship on two points.
* **Reversal direction is not merely un-violated, it is actively observed.** Ten
  down entries use a vertical indicator, four across entries a horizontal one,
  five use neutral vocabulary, and there is no crossover in either direction.
  That is what a real convention looks like in data, as against a rule somebody
  wrote down.

Two published clues sit inside the adjacency check's allowances rather than
outside its scope, and both allowances were added because of them: 30043 1A
(`Bans recitals – where this is played?`) puts its definition between fodder and
anagrind, and 30067 20D (`Bertie develops from bad to worse`) puts annotated
padding there. Three more (30040 8A, 30040 11A, 30041 20A) build their fodder by
deleting letters, so no span of the clue holds it; those are skipped, with a
warning when the clue is ours.

Note the adjacency rule is *not* a reversal of the withdrawn advice at the top of
this file. That one said an anagrind next to its fodder is a *tell* and was
killed by measurement (88.9% of published anagrams do it). This says a separated
one is *unsound*. Different claims about different things, and the same
measurement supports both: adjacency is the norm because adjacency is how
indicators work. `tools/clue_quality.py` still carries the
`indicator-abuts-fodder` smell on its correlation with judge score alone, and it
now says so — the only legal response to it is a different indicator, never a
moved one.

### What the audit changed

| answer | was | now | fault |
| --- | --- | --- | --- |
| STOREY | The oyster lives on the ground floor | Ground oyster makes a floor | link word + adjacency |
| THERE | Time here would be better spent yonder | Time here leads to yonder | link word (four words of padding) |
| LEADERSHIP | Leaders get hip and mistake it for direction | Leaders get hip and find direction | link word (`mistake it`) |
| LOOP | Back at the pool for another circuit | Up the pool for another circuit | reversal direction (down entry) |

STOREY keeps the pun it was written for — floor-as-surface against
floor-as-storey — and pays for it honestly: crushed oyster shell really is laid
as flooring, so `Ground` describes the material and shuffles it in the same
breath, and `makes` is a true equals. Five words, four jobs, no passengers.
LOOP's walkthrough now teaches the direction convention instead of quietly
contradicting it: the old one already said "in a down clue the reversal runs
upwards" while using `Back` to do it.
