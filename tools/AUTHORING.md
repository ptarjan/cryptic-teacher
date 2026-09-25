# Setting a puzzle: filling the grid

This file explains how we set an original puzzle. There are two steps:

1. `tools/grid_fill.py` fills a legal British grid with answers.
2. A human writes the clues and their annotations.

`tools/grid_fill.py` does not write clues, and never will. That judgement is the
point of the site.

The annotation rules themselves are in `STYLE.md`. This file records how the
clue-writing rules were found and measured, using our first authored puzzle,
A001 (twenty clues, built from `tools/data/sample_fill_11.json` and
`tools/data/authored_A001_clues.json`).

## Quick start

```bash
bash tools/fetch_lexicon.sh          # once: ~26 MB of word data, gitignored
python3 tools/grid_fill.py --size 11 --seed 1
python3 tools/grid_fill.py --size 11 --seed 3 --fills 60 --out my_fill.json
python3 tools/grid_fill.py --size 13 --check-only     # just validate a template
python3 tools/clueability.py --word CARPET            # why a word scores what it does
```

The worked example, `tools/data/sample_fill_11.json`, was made with:

```bash
python3 tools/grid_fill.py --size 11 --seed 3 --fills 60 \
    --min-familiarity 25 --min-clue 40 --out tools/data/sample_fill_11.json
```

## The grid conventions, and why each one

Each rule is a `check_*` function in `tools/grid_fill.py`. A template that fails
any of them is **refused, not filled**. This matters: the first three 11x11
patterns written by hand for this tool were all illegal (three-letter entries,
orphan lights, a disconnected region), and the checker caught all three.

| check | rule | source |
| --- | --- | --- |
| `check_shape` | square, odd side | universal in British blocked grids; an odd side gives a true centre for the symmetry |
| `check_symmetry` | 180-degree rotational symmetry | universal; a Guardian grid looks the same upside down |
| `check_min_entry_length` | every entry at least 4 letters | Exet. Nine of the twelve Guardian grids in `puzzles/` agree; three go down to 3, so `--min-entry 3` allows it |
| `check_every_light_is_used` | every light is in at least one entry | a light in no entry can never be filled. A light in exactly ONE entry is fine: that is an unchecked letter, which British grids have and American ones do not |
| `check_unchecked_runs` | no two adjacent unchecked letters | Exet's strict reading, and what all twelve measured Guardian grids do. `--relax-unches` allows the looser published convention (two in the middle of an entry, never at an end) |
| `check_entry_checking` | no entry has more unchecked than checked letters; entries of 9+ may have one more | Exet. Stricter than "at least half, rounded down": a 5-letter entry needs 3 checked, not 2 |
| `check_connectivity` | all lights form one connected region | a detached corner is a second crossword |
| `check_checked_ratio` | 28-52% of all letters checked | measured: the twelve Guardian grids in `puzzles/` sit at 31-40% |
| `check_through_cut` | at least 3 lights cross every cut line | Exet recommends 4 on a 15x15; scaled by side length. A solver stuck in one region needs several ways to carry letters into the next |

Sources: [Exet](https://github.com/viresh-ratnakar/exet), Viresh Ratnakar's
British-grid editor, whose validator is the strict reading; and
[georgeho.org/counting-cryptics](https://georgeho.org/counting-cryptics/), which
measured published grids. It agrees on symmetry, odd side, connectivity and
half-checking, but allows two consecutive unchecked letters in the middle of an
entry. Where the two sources differ, the strict rule is the default and the
loose one is a flag, so the choice is visible.

**The overall checked ratio and the per-entry rule are different rules.**
Folklore says "half the letters are checked". Real grids check 31-40% of letters
overall, while every individual entry is at least half checked.

The two built-in templates were found by searching symmetric block patterns and
keeping the ones that pass every check. Change them freely: they are plain text
blocks of `#` and `.` at the top of `tools/grid_fill.py`. `--template FILE`
loads one from disk.

## Why the fill is clueability-aware

**A grid that fills is not necessarily a grid that can be clued.** Every example
below came from this tool's own runs:

* **KILOMETERS**: legal and common, but an American spelling that a British
  solver would call an error. The Lufz lexicon's Britain region lists 5,212 such
  spellings, and the filler now drops all of them.
* **PARC** and **PROTO**: PARC is French, and PROTO is a prefix with no
  definition. Both are good *pieces* of wordplay and impossible *answers*.
* **AMINO**: only ever appears in "amino acid", so it cannot be defined
  honestly.
* **ENTRUSTED**: a common word with no anagram, reversal or container, only one
  dull charade. It is not wrong, just a clue nobody enjoys. A filler that cannot
  see this fills a grid with them.

So `tools/clueability.py` scores every word once (cached) on the hooks a setter
uses: anagram, near-anagram (letters minus a standard abbreviation), charade,
container, homophone, reversal, deletion, hidden-ability, and a weak
double-definition proxy. It adds a **fairness floor** from the lexicon's
importance ranking. The score is used twice:

1. **as an ordering**, so the backtracking search tries the best-hooked word
   first, and
2. **as a floor** (`--min-clue`, `--min-familiarity`), so a word below it is not
   a legal fill at all.

A human judges the result from the reported score distribution. Fills are
ranked by their **worst** entry first, then their mean, because one unclueable
answer sinks a grid however good the other nineteen are.

### The outer loop: veto and blacklist

Scoring is a heuristic and will sometimes still produce an unclueable word. So
`fill()` is a **generator with a veto hook**:

```python
banned = {}
gen = grid_fill.fill(grid, by_len, veto=lambda w: banned.get(w), seed=1)
solution, _ = next(gen)
# ...try to clue it; if BANANA defeats you:
banned["BANANA"] = "no definition that isn't a giveaway"
solution, _ = next(gen)        # search RESUMES; BANANA is gone
```

Vetoing a word unwinds the search to the frame that chose it (see `Revoked`)
instead of restarting, so the next fill is nearly free. If you change that code:
a veto must also remove the word from the subtree already being searched, not
only from new candidates, or the resumed generator offers the banned word
again.

Record each rejection in `tools/data/unclueable.json` **with a reason**, so the
knowledge is kept instead of rediscovered. (`STYLE.md` applies the same
principle to product feedback.) Most current entries are proper nouns: Lufz
folds them into lowercase entries, and its `isProperNoun` only looks at
capitalisation, so it cannot tell ERIC the name from a common noun. Until there
is a better signal, the blacklist catches names.

## Word data

`bash tools/fetch_lexicon.sh` fetches the
[Lufz lexicon](https://github.com/viresh-ratnakar/lufz) and
[exet-lexicon.js](https://github.com/viresh-ratnakar/exet) (both MIT). It then
runs `tools/build_lexicon.js`, which loads them headless in a Node `vm` and
writes `tools/data/lexicon.tsv`. Lufz is UKACD18, the classic British cryptic
word list, cleaned up and extended with a Wikipedia-derived importance ranking,
CMUdict pronunciations and Porter2 stems.

What each extra is used for:

* **importance rank** is the fairness floor. The fallback when the lexicon is
  missing, `/usr/share/dict/words`, has no score column, so with it there is *no*
  fairness floor. The filler says so loudly, and the fill will contain obscure
  words.
* **pronunciations** make the homophone hook a phonetic fact, not a spelling
  guess.
* **stems** give each word a family size (EARTH has forty relatives, ERIC has
  two), which is a better double-definition proxy than raw frequency.
* **the Britain region** is the British-spelling filter described above.

Licences, and what is committed versus fetched: `tools/data/README.md`.

`tools/data/abbreviations.json` is hand-built (H = hard, R = river, ...) and is
*meant to grow*. Add to it when a clue needs an abbreviation it lacks. Solvers
read it too: `tools/build_abbreviations.py` publishes it as `abbreviations.js`,
and the building-blocks rung names the conventions a clue used ("sailor = AB").
So an entry added here is something the site then teaches.

## What the clue-writing step gets

`--out FILE` writes JSON whose entries use the same shape as `puzzles/*.json`,
so a clued puzzle can be assembled without reshaping anything:

```json
{
  "id": "1-across", "number": 1, "direction": "across",
  "position": {"x": 0, "y": 0}, "length": 4,
  "solution": "PACE", "checkedPattern": "PaCe", "checkedIndices": [0, 2],
  "clueability": 73, "familiarity": 29, "hooks": "ANCXDH"
}
```

For each entry the clue writer gets:

* the answer and where it sits;
* which letters are checked: uppercase in `checkedPattern`. A crossing clue
  confirms those, so an unchecked letter must be gettable from the wordplay
  alone;
* which mechanisms are available, as `hooks` flags: **A**nagram,
  **N**ear-anagram, **C**harade, **X** container, **P** homophone (phonetic),
  **R**eversal (lowercase `r` = contains a reversed word), **D**eletion,
  **H**ideable. `python3 tools/clueability.py --word PACE` prints the splits
  behind the flags.

A human still writes, per entry, the `clue` and the `annotation` (type,
definition, indicators, blocks, walkthrough), which `tools/validate_annotations.py`
and `STYLE.md` govern. The annotation rules apply here: the definition must
match the answer's part of speech, every content word must be accounted for,
and the type must name every mechanism. An answer with several hooks makes that
easier.

## Performance notes

Filling is backtracking search. It uses minimum-remaining-values ordering over
letter-position bitmask indexes, forward-checks every crossing slot, has a node
and time budget per restart, and restarts randomly with jittered candidate
order. An 11x11 fills in well under a second. `--fills N` generates N distinct
fills and keeps the best.

If a grid will not fill, try these in order: `--seed`, `--fills`, `--restarts`,
then a lower `--min-clue`. If you keep lowering the floor, the template is the
problem, not the budget. A grid full of maximum-length entries is hard to fill:
the first 13x13 template had full-width 13-letter entries, and only ~200
clueable 13-letter words exist above the floor, two of which then had to
interlock with 12s. The current 13x13 has a longest entry of 7 and fills
instantly.

## What blind grading found

A001's twenty clues were scored against 60 published clues for the same
answers, taken from the Times, Guardian, FT and Independent blogs. Three judges
scored them on five axes from `tools/data/grading_rubric.md`, without being told
which clues were ours. Build the packets with `tools/grade_clues.py`; score them
with `tools/score_grading.py`.

                  ours   human    gap
    surface       3.10    3.73   -0.63
    misdirection  2.47    3.68   -1.21
    penny-drop    2.43    3.41   -0.98
    economy       4.17    4.02   +0.15
    fairness      4.72    4.00   +0.72
    OVERALL       3.38    3.77   -0.39

Our clue beat the best human clue for the same answer on 1 of 20. Judges asked
to spot the machine-written clue were right 50% of the time, against 25% chance.

Read the table as a diagnosis. **Soundness is solved; it is not what is
missing.** The +0.72 on fairness comes from `tools/validate_annotations.py`. The
human field included an anagram with no anagram indicator, a hidden word with
no hidden indicator, and one clue with no derivation at all, and every judge
noticed. Our clues never fail that way.

The loss is in **misdirection and penny-drop**. Both come from one habit:
writing the mechanism down in order and then putting a sentence around it.
`Later rewritten, to change` is fodder, indicator, definition, in that order,
with a comma fencing off the definition. It is fair, and nobody would enjoy it.
Our worst six all have that shape.

So the rule is about *order of work*:

> Decide what the clue is **about** before you decide how it works. The surface
> idea (a scene, a joke, a piece of news) is what you are writing; fit the
> mechanism into it. Assembling parts and then smoothing the result produced
> every clue we lost with.

Two habits to break. `tools/clue_quality.py` flags both.

- **Do not attach the definition with a copula.** `Cold heap is inexpensive`
  makes the clue state its own answer. Real setters make the definition part of
  the sentence's meaning.
- ~~**Do not stand the anagram indicator next to its fodder.**~~ **Withdrawn:
  this was wrong.** It came from one judge's remark and was never checked.
  Across 38,830 published anagram clues with a verified fodder, **88.9% put the
  indicator directly against it**. `Naples rebuilt` is the normal shape, not a
  giveaway. The part worth keeping: choose an indicator that reads as ordinary
  description in the surface. Whether it sounds like an instruction matters far
  more than where it sits. The concealment section of `tools/clue_quality.py`
  has the measurement, including why an apparently significant position effect
  (p=0.03) does not survive being one of six cuts tried on thirteen clues.

Do not over-correct: **economy was already fine** (+0.15), so the answer is not
longer clues. The `terse` flag fires on ten of the twenty, including the best
ones. Extra words help only if they buy a surface idea.

## The surface is a sentence, and it carries a joke

The six worst clues were rewritten under the rule above, and the feedback was:
*they still do not read as real sentences or have cute puns*. For example,
`That Conservative lot, and mean with it (5)` is a grammatical fragment with no
finite verb, built from two definitions and a conjunction. Nobody has ever said
it. Apply two tests before a clue counts as finished:

**Say it aloud with no crossword in mind.** It must be something a person would
actually say: a headline, a complaint, gossip, advice. Being grammatical is not
enough; grammatical fragments pass that test and still fail.

**Name the joke in one clause.** *She hopes he'll change — at the altar.* *The
bully's name-calling turns out to be a list of stars.* If you cannot, there is no
penny-drop for the solver, and polishing the wordplay will not add one.

**Be willing to throw the mechanism away.** In the rewrite, the author kept each
already-chosen mechanism and hunted for a surface to fit it: mechanism first
with a coat of paint, which the previous rule forbids. Four of the six rewrites
that finally worked changed clue type entirely. Three are in A001: CHEAP went
from charade to anagram, SIDE from container to hidden word, ALTER from anagram
to homophone. The sentence came first, and the mechanism was found inside it.

`tools/clue_quality.py` flags `not-a-sentence`, `imperative-opening` and
`unattested-phrasing` for this, but read its calibration table before trusting
them. The first fires on nearly half of all published Times clues, and the third
has never fired on one of ours. Lacking a verb is not the problem, and odd
phrasing is not the problem. Both tests above remain judgements, made aloud.

## The standard is a pub joke, not a rubric score

The round-two rewrites passed the rubric. Then a human read the five clues that
had beaten their whole human field and said: *those aren't very good, none of
those are real sentences.* He was right, and it means the scoreboard was wrong,
not the reader:

> `Newspaper: Morgan dropped a million (5)` is a definition glossed with a
> colon. `Concerning hotel staff, the press (9)` is a verbless fragment opening
> on a bare RE marker. `Dwindles as time enters the Lords (6)` is a front
> definition attached to a narration of its own wordplay. `Pool turned into a
> circuit (4)` shows "turned" as a visible instruction. **They won because the
> judges were rewarding rubric-compliance.** Beating a field is not evidence of
> quality when the field and the judges share a rubric.

Write against named clues, not a table:

    Two girls, one on each knee (7)               = PATELLA
    Die of cold (3,4)                             = ICE CUBE
    Amundsen's forwarding address (4)             = MUSH
    A stiff examination (4-6)                     = POST-MORTEM
    Bergamot herbal extract for bodybuilder? (6)  = MOTHER

They are short, complete and funny, and the definition is invisible because the
sentence depends on it. None has any crossword furniture. PATELLA is a plain
charade, so "no furniture" does not mean "no mechanism": `one on each knee` is
both the assembly instruction and the picture.

MOTHER shows the same for a hidden word, and is the clearest example of
**exactly two pieces, nothing superfluous**:

    Bergamot herbal   wordplay fodder — berga|MOT HER|bal
    extract           the hidden indicator, and also a real herbal product
    for               joinery
    bodybuilder?      definition

Five words, and each does two jobs. `extract` is the crossword instruction *and*
something a herbal shop sells, so it never reads as an instruction.
`bodybuilder?` is the joke: the reader pictures a gym, and the answer is that
mothers build bodies. The `?` does its proper job, flagging a definition that is
true but whimsical, not apologising for a loose one. Compare A001's hidden words
(`Milan club buried in winter`): sound, but the container word is visibly there
only to hide letters.

Test each candidate against MOTHER: can you write the four-line table for your
clue, with every word of the surface in exactly one row?

The rules applied to all twenty A001 clues in that pass:

1. **A complete English sentence.** Subject and finite verb, or an idiom people
   actually say. Imperatives are fine (`Die of cold`).
2. **Banned furniture:** a definition glossed off behind a colon or comma; clues
   opening `Concerning` / `About` / `Regarding`; `Sounds like`; any clue that is
   a bare noun phrase listing wordplay and then meaning.
3. **The pun must be nameable and cute.** The reader should smile. If the only
   pleasure is that the mechanism works, the clue fails, however sound it is.
4. **Shorter is better.** The target clues run 3-6 words.
5. **Choose the mechanism last**, from material the sentence already contains.
   If nothing fits, find a different sentence. Never repair it by narrating the
   wordplay.

The cost: pushing for the pun raised A001's cryptic-definition count from one to
six, because several answers (PACE, THERE, ARMED, ORGAN, PETERS, REPORTERS) gave
a funny sentence and no funny mechanism. A puzzle that is a third cryptic
definitions is unbalanced by any published standard. The next section is the
pass that fixed it.

## The sentence AND the wordplay

The twenty rewritten clues were read back, and the verdict was:

> **They are good for sentences now but they don't have wordplay anymore.**

Six of twenty had become bare cryptic definitions. So the rule:

> A clue needs the sentence **and** the wordplay, both in the same few words. A
> funny sentence with no mechanism is a cryptic definition, and a cryptic
> definition is a treat, not a technique: **at most two in a puzzle we set**,
> enforced by `tools/validate_annotations.py` as an ERROR
> (`MAX_CRYPTIC_DEFINITIONS`).

A clue gives two routes to the same answer. A joke with no mechanism is a quiz
question: the solver shares your reference or has nothing to work on, and no
crossing letter helps them reason. That is why the cap is a number, not a
preference.

**Why this keeps happening.** A funny sentence is much easier to find than a
funny mechanism, and the mechanism is the part that will not bend. So chasing
the pub-joke standard constantly pushes you to drop the mechanism. Each of those
six clues was defensible on its own; the damage only showed when they were
counted. Hence a whole-puzzle check, not a per-clue one. The limit of 2 is
measured: when it was set, 30039 was the only annotated puzzle in `puzzles/`
with any cryptic definitions, and it had exactly two.

**A narrated mechanism is not a hidden one.** Two A001 clues had a real
mechanism and still failed, because the indicator was an instruction dressed as
a sentence:

    There's a bit of the president in our team (4)   SIDE
    Every ship needs a leader in front (10)          LEADERSHIP

`a bit of` and `in front` are not description. They are the setter telling the
solver *take part of this word* and *put that one first*. Both were fixed by
giving the indicator ordinary meaning, or by removing it:

    There's a mole in the president's team (4)          in = the only signal, and
                                                        a mole really is buried
                                                        in pre-SIDE-nt
    Leaders get hip and mistake it for direction (10)   a charade needs no
                                                        indicator at all

The test: **would this word be in the sentence if there were no crossword?**
`in` passes. `a bit of` fails. Watch for `a bit of`, `some of`, `in front`,
`turned`, `rebuilt`, `back` and `about` doing nothing but announcing the
machinery.

What the pass produced: four cryptic definitions converted, two kept.

| answer | was (no mechanism) | now | mechanism |
| --- | --- | --- | --- |
| THERE | Where the grass is greener | Time here would be better spent yonder | charade, T + HERE |
| REPORTERS | These porters carry stories, not bags | The press are riddled with pet errors | anagram of PET ERRORS |
| ORGAN | The only instrument you can donate | The donor's dreadful groan comes from the instrument | anagram of GROAN |
| PETERS | What Peter does when Paul gets paid | With the Queen among the pets, interest dwindles | container, ER in PETS |
| PACE | Expectant fathers do it up and down | *kept* | — |
| ARMED | What the Venus de Milo isn't | *kept* | — |

PACE and ARMED are the two allowed cryptic definitions. They were kept because
their available mechanisms are the weakest, not because their jokes are the
best. PACE offers only an anagram of CAPE or the charade P + ACE, and neither
supports a joke. Every synonym of ARMED is a phrase (`carrying a weapon`, `under
arms`), so no clue can define it tightly enough to be worth the machinery. The
test for spending one of your two: **not "is this funny" but "is the mechanism I
would swap in actually worse than nothing".**

## Exactly two pieces

The next read-back was about the words that are not part of the clue:

> **A good cryptic clue doesn't have anything superfluous which isn't directly
> part of the wordplay. It should be exactly two pieces. Definition, optional
> joinery and wordplay.**

So every word does exactly one of three jobs: part of the DEFINITION, part of the
WORDPLAY (fodder or indicator), or a LINK WORD joining the two. A word that only
makes the surface read nicely is a fault, **however good the sentence**. In the
schema it has one signature: a block with `"gives": ""`, the "surface only"
padding that `STYLE.md`'s leftover-words rule tells the annotator to record.
Nine of A001's twenty clues had one.

`check_two_pieces()` in `tools/validate_annotations.py` makes it an ERROR, scoped
by `is_authored()` to puzzles whose `series` is `"authored"`. The scoping is
required: real setters pad, and the annotator must be able to say so. Unscoped,
the check fires **eighteen times on 30039 alone**, mostly on double definitions,
where a block legitimately carries no letters. A check that fires on honest work
is a broken check.

The opposite fault needs no scoping, because it is wrong in a published grid
too: the DEFINITION's own words used again as wordplay.
`check_definition_not_fodder()` catches it. A block taking letters from words
the definition already claimed means the two halves overlap. Its worst form is
invisible to every other check: `definition: "Hard rock"` beside a block
`"Hard rock" > HORSE` concatenates perfectly and explains nothing. It warns per
clue, since a setter occasionally reuses a word on purpose, and ERRORs past
`MAX_DEFINITION_REUSE` in one puzzle, since that means the annotator described
the clues instead of solving them.

### The fault no check catches

A `cryptic definition` claims no letters, so it contradicts nothing and no
consistency check can reach it. That makes it the one type an annotator can use
without solving anything. Four candidate checks were measured against the corpus:

| candidate | hits on honest work | outcome |
| --- | --- | --- |
| a block hands over the whole answer | 4 of the 9 existing cryptic definitions | rejected |
| the `definition` spans the whole clue | 8 of 9 | rejected |
| a known indicator word appears in the clue | 3 of 9 | rejected |
| blocks give the right letters in the wrong order, with no mechanism named | 11 of 175 charades | kept, as `check_blocks_in_answer_order` |

The fourth was first rejected as noise, because the letters in all eleven were
correct (for example PEAS + SWEET for SWEET PEAS). That was a mistake: the ORDER
is what is being taught, and PEAS before SWEET makes the learner reassemble what
the annotation should show. What made it look like noise was scope. Limited to
`type == "charade"` exactly, it has 10 hits in 127 and no false positives. Every
hit outside that scope is a container or a rotation, whose blocks are
*supposed* to come before the positional step. The backlog was fixed in the same
commit, so the check started at zero.

The general lesson: before shelving a check for firing on honest work, ask
whether the rule is wrong or only its scope, and whether "honest work" is a
judgement you made or a default you gave the existing corpus.

For the remaining case, the defence is a human:
`check_cryptic_definition_cap()` warns from the cap upwards and names every
cryptic definition in the puzzle, and a human reads them. This is deliberate. A
check that catches the remaining case does not exist, because every version
tried was wrong more often than right.

The cap went through the same scoping lesson in the other direction. It was
once an ERROR on every puzzle. Then quiptic-1372 (Harpo) turned out to have five
real cryptic definitions, so the annotator solved all five and shipped three of
them with `annotation: null` to get under the limit. The rule was right and its
scope was wrong: our own count is ours to change, but a published setter's count
is a fact about their grid. It now ERRORs on authored puzzles and warns on
fetched ones. The second repair matters more: a rule that can be satisfied with
blanks turns a loud failure into a silent one. So `check_every_clue_is_annotated()`
makes a blank annotation an error, exempting only an entry the setter printed
with no clue text.

### Rebuilding and validating an authored puzzle

The daily sweep globs `*-[0-9]*.json`, the shape of a fetched puzzle's id
(`<series>-<number>`). An authored id such as A001 has no hyphen before its
digits, so the sweep never sees it. After editing a
`tools/data/authored_*_clues.json` file, you MUST rebuild and validate the
puzzle **by id**:

```bash
python3 tools/build_authored_puzzle.py --clues tools/data/authored_A001_clues.json \
    --id A001 --name "Cryptic Teacher No 1" --setter "Cryptic Teacher" --date 1785283200000
python3 tools/validate_annotations.py A001
rm puzzles/A001.json
```

`tools/build_authored_puzzle.py` writes `puzzles/A001.json` (it uses the grid in
`tools/data/sample_fill_11.json` unless `--fill` says otherwise). Delete it when
you are done. It is never committed: A001 is served to no one, and the clues
JSON is the source. While it exists, `tools/smoke_test.js` fails, because every
puzzle file must be named `<series>-<number>.json`.

A clean validate ends with no ERROR lines. A001 itself does not pass today. Among its ERRORs: it
predates the required `definitionFit` and `indicatorNotes` fields, and its 18A
block note names the answer. Fix those in the clues JSON before relying on it.

### Why filler is banned, and the nine fixes

A funny sentence is easy if filler is allowed. Put `There's a…`, `Our…`, `she
hopes he'll…` around any two pieces and something readable falls out. Banning
filler is what separates a clue from a joke that happens to contain the answer.
The rule makes the job harder: every word must serve the machinery *and* the
sentence must be funny, which is the actual craft. Expect to throw candidates
away; the rejects for this pass are logged with reasons in the commit's
checkpoint.

All nine, before and after:

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

Two of the nine were **mis-annotation, not filler**. The rule has to allow for
that:

* SIDE's `There's a mole in` is not padding; it is the hidden-word
  **indicator**. A mole is something concealed inside an organisation, so the
  phrase says *something is buried in here* without any crossword instruction,
  which is exactly what an indicator should do.
* ARGUE's `There's` is **joinery**. It carries no letters and is not definition,
  but it is the finite verb that makes the clue a sentence instead of a noun
  phrase. It belongs in `linkWords`, where the app greys it and tells the learner
  there is no mechanism in it.

The test: does the word contribute letters, restrict the parse, or hold the
sentence together grammatically? If none of these, it is filler. An indicator or
a link word is *claimed*, so it can be shown to the solver; padding can only be
apologised for.

**Is shorter usually the answer?** Mostly. The seven rewritten clues went from 49
words to 43 (mean 7.0 to 6.1; all twenty went from 139 to 133). Four got
shorter; INTER and STOREY stayed the same length; ALTER got one word LONGER,
because the padding-free version needed a real mechanism (HALTER less H) where
the padded one leaned on a homophone plus a joke told in the padding. Padding is
a *symptom* of a clue a word or two too long, but the cure is finding a mechanism
the sentence can pay for, not cutting words until it fits.

**The two cryptic definitions.** Read strictly, PACE and ARMED fail "exactly two
pieces": they have one piece, a definition, and no wordplay. They were kept on
purpose. The rule governs *superfluous* words, and in a cryptic definition every
word is part of the definition, so nothing is superfluous. The count keeps them
honest, and `MAX_CRYPTIC_DEFINITIONS` holds it at two. For whoever revisits
this: **ARMED is an anagram of DREAM**, and `Venus de Milo's broken dream` is a
real semi-&lit, with `broken` doing double duty on a broken statue. It was not
used because it is a bare noun phrase, which breaks rule 1 of "The standard is a
pub joke" in exchange for the mechanism. If the two cryptic definitions ever
have to go, start from that clue.

## When the blocks already told them

> **When you basically give the whole answer in the building blocks you don't
> need to have the full walkthrough.**

The rule, what a walkthrough should keep, and `check_walkthrough_budget()` are in
`STYLE.md`, "The blocks already told them". The evidence behind it: all twenty
A001 walkthroughs ran 44-63 words (median 54), and every one restated its own
blocks, just when the learner no longer needed it. Trimmed to what the blocks
cannot show, they run 19-42 words, median 32. That is also the median of the 231
published-puzzle walkthroughs in `puzzles/` at the time, and their 90th
percentile, 42, is why the budget warns above 45.

Before changing this, know two things:

* **The walkthrough may be short but never empty.** `ladderSteps()` in `app.js`
  always adds the "Full walkthrough" rung, and the validator requires the field.
  An empty one shows as a labelled rung with a blank paragraph: a visible hole,
  and no place for the mechanism line on clues with no blocks.
* **The check is a word budget, not a redundancy detector**, and the code says
  so. A semantic version was built and thrown away. It scored the fraction of
  walkthrough vocabulary already in the clue and blocks: 0.21 for the bad A001
  set, 0.16 after the rewrite, and 0.30 for published puzzles. The good
  walkthroughs scored *worse* than the bad ones, because naming the joke reuses
  the clue's own words. Do not rebuild it without new evidence.

## The joints: link words, adjacency, direction

The clue offered as the best of the pass was rejected, for two structural
reasons. Here it is with its annotation:

    The oyster lives on the ground floor (6)   = STOREY

    The oyster    fodder
    lives on      link
    ground        anagram indicator
    floor         definition

> **A link word has to stand in for an equals sign**, and **an anagram
> indicator has to be next to the fodder it operates on.**

This clue breaks both. `lives on` states no equivalence between wordplay and
definition; it is surface padding filed as a link word. That makes the clue
three pieces (wordplay, PADDING, definition), a direct breach of "Exactly two
pieces" above. And `ground` cannot reach back over `lives on the` to shuffle
`The oyster`: an indicator only operates on what it touches.

**STOREY felt like the best clue in the set because of those faults.** The
padding made the surface smooth. `The oyster lives on the ground floor` reads
like a line from a nature programme because three of its words serve the
picture instead of the machinery. A sound clue must buy its surface with words
that are already working. **So a smooth surface is not evidence of soundness;
often it is evidence against it**, because the easiest route to a smooth surface
is to stop paying for it.

A third fault of the same kind turned up while auditing for the first two, and
it survived calibration:

> **A reversal indicator must point the way the entry runs.** `Back at the pool
> for another circuit (4)` = LOOP was **14-DOWN**. There is no "backwards" on a
> vertical axis.

### The rules

| rule | check | what it allows |
| --- | --- | --- |
| Link words are an equals sign | `check_link_words_are_equivalences` | equivalence (`is`, `'s`), derivation (`gives`, `makes`, `becomes`, `yields`, `means`, `leads to`, `indicating`, `to locate`), prepositional joining (`for`, `from`, `of`, `in`, `with`, `after`), and grammatical glue. Nothing else: `EQUIVALENCE_LINKS` is the whole rule |
| An indicator operates on what it touches | `check_indicator_adjacency` | only `FODDER_GLUE` words (for example `was`, `is`, `a`, `the`, `of`, `in`, `with`) between an anagram indicator and its fodder, plus the definition, which sometimes sits in the gap |
| An indicator is not its own fodder | `check_indicator_outside_fodder` | nothing: a word whose letters are being shuffled cannot also be the instruction to shuffle them, so the indicator must sit outside every locatable reading of the fodder. The adjacency check cannot see this, because an indicator inside the fodder has no gap to measure and scores as perfectly placed |
| A reversal runs along the entry | `check_reversal_direction` | across: `back`, `returning`, `retreating`, `west`. Down: `up`, `rising`, `climbing`, `lifted`, `raised`, `from below`. Neutral words (`turning`, `about`, `overturned`, `revolutionary`, `reversal`) are always allowed |

All four are ERRORs, scoped by `is_authored()` like the two-pieces rule.

### Calibration

The standing rule: **a check that flags Araucaria is a broken check.** Before
trusting any authoring rule, run it across the eight annotated Guardian puzzles
and record the count:

```bash
python3 tools/validate_annotations.py --unscoped 30039 30040 30041 30042 30043 30044 30066 30067
```

`--unscoped` exists only for this; never ship in that mode. Results:

| check | published sample | hits |
| --- | --- | --- |
| link words are equivalences | 2 declared link words, plus 105 unclaimed joinery-position words as a proxy | 0 (after adding `after` and `having`, the only misses) |
| indicator adjacency | 42 anagram clues, 39 with a locatable fodder span | 0 |
| reversal direction | 19 reversal clues | 0 |

Two of these numbers deserve a closer look.

* **The link-word sample is thin: two declared link words in 234 entries.** So
  the allow list could not be calibrated directly, and a second measurement was
  built. Every clue word the annotation claims for nothing is a word in the
  joinery position, and there are 105 of those. Four fell outside the allow
  list, all grammatical (`after` x3, `having`), and the list was widened. When a
  sample is too small to calibrate against, find a proxy with a bigger sample;
  do not ship on two data points.
* **Reversal direction is not just unviolated; it is actively followed.** Ten
  down entries use a vertical indicator, four across entries a horizontal one,
  and five use neutral words. None crosses over. That is what a real convention
  looks like in data.

Two published clues fall inside the adjacency check's allowances, and those
allowances were added because of them: 30043 1A (`Bans recitals – where this is
played?`) puts its definition between fodder and indicator, and 30067 20D
(`Bertie develops from bad to worse`) puts annotated padding there. Three more
(30040 8A, 30040 11A, 30041 20A) build their fodder by deleting letters, so no
span of the clue contains it. The check skips those, with a warning when the
clue is ours.

The adjacency rule does *not* contradict the withdrawn advice in "What blind
grading found". That advice said an indicator next to its fodder is a
*giveaway*, and measurement killed it (88.9% of published anagrams do it). This
rule says a separated indicator is *unsound*. They are different claims, and the
same measurement supports both: adjacency is the norm because adjacency is how
indicators work. `tools/clue_quality.py` still has the `indicator-abuts-fodder`
smell, based only on its correlation with judge score, and says so. The only
valid response to that smell is a different indicator, never a moved one.

### What the audit changed

| answer | was | now | fault |
| --- | --- | --- | --- |
| STOREY | The oyster lives on the ground floor | Ground oyster makes a floor | link word + adjacency |
| THERE | Time here would be better spent yonder | Time here leads to yonder | link word (four words of padding) |
| LEADERSHIP | Leaders get hip and mistake it for direction | Leaders get hip and find direction | link word (`mistake it`) |
| LOOP | Back at the pool for another circuit | Up the pool for another circuit | reversal direction (down entry) |

STOREY keeps its pun (floor as surface, floor as storey) and pays for it
honestly. Crushed oyster shell really is laid as flooring, so `Ground` both
describes the material and shuffles it, and `makes` is a true equals sign. Five
words, four jobs, nothing spare. LOOP's walkthrough now teaches the direction
convention; the old one said "in a down clue the reversal runs upwards" while
using `Back` to do it.
