# Cryptic Teacher style guide

These are the standing rules for annotating puzzles. `tools/annotate_prompt.md`
is the nightly annotation run's condensed copy of them and points here, so a rule
added here must be carried into that prompt or into a validator check to reach
future puzzles. Where this file and `tools/annotate_prompt.md` disagree, this file
wins.

When Paul gives feedback on a puzzle, a hint or the app, fix it in two places:
the instance he pointed at, and a rule here. Where you can, also add a
mechanical check in `tools/validate_annotations.py` or an assertion in
`tools/smoke_test.js`.

Rules for how the app *presents* annotations (the hint ladder, the reference
corpus, deploy and cache-busting) live in `APP.md`, not here. The annotator
cannot act on them. Put each rule in the file that
its reader reads.

"The validator" below means `tools/validate_annotations.py`. ERROR means the
validator fails the puzzle; a warning is reported but does not fail it.

### A new rule binds the next puzzle, not just the one that prompted it
A new rule applies at once to every puzzle fetched from now on. Puzzles
annotated before it get a written, per-puzzle allowance, never an on/off flag:

- `tools/annotation_backlog.json` records, for each existing puzzle, how many of
  its clues predate each field.
- The validator ERRORs as soon as a puzzle has more such clues than its own
  number. A puzzle not listed in the file is allowed none.
- The numbers only go down. Draining a puzzle's backlog tightens the rule on it
  permanently.
- `tools/prereset_backfill.sh` reads its field list from the same file. It does
  not name fields itself.

To grandfather a new field, add it to `BACKLOG_MARKERS` in the validator and run
`python3 tools/validate_annotations.py --tighten` once. Do not add a
`REQUIRE_X = False` flag to flip later: it leaves the rule optional for the
puzzles it exists for, the ones not yet written, for as long as nobody flips it.

## Annotation rules

### Honest types
`type` names EVERY mechanism the wordplay uses, joined with `" + "`, in the
order they occur. Never give only the main mechanism. If a charade's second
chunk comes from the alternate letters of a word, the type is
`charade + alternate letters`, not `charade`.

The vocabulary is fixed. `TYPE_PARTS` in the validator is the complete list, and
the validator ERRORs on any other part. This list must match it. Where a part is
written `X letter(s)` below, both `X letter` and `X letters` are valid.

- Base types: `anagram`, `charade`, `container`, `hidden word`, `homophone`,
  `reversal`, `deletion`, `double definition`, `cryptic definition`, `&lit`,
  `spoonerism`.
- Letter selection: `first letter(s)`, `last letter(s)`, `middle letter(s)`,
  `outer letters`, `alternate letters`.
  - `regular letters`: letters taken at a fixed step other than every second.
    30077 17D takes every THIRD letter of "Hope to God" to spell POD.
  - `second letter(s)`: a letter picked by its position. 12420 14D takes the
    second letter of "master" for the A of AGO; 30065 6D takes the second letter
    of each of four words to spell EDAM.
  - `third letter(s)` through `twelfth letter(s)` (`third`, `fourth`, `fifth`,
    `sixth`, `seventh`, `eighth`, `ninth`, `tenth`, `eleventh`, `twelfth`): the
    same, counted further in. 30103 25D takes the fifth letter of "citizens" for
    the Z of UZBEK.
  - `prime letters`: positions picked by a rule, not a fixed step.
    indysunday-1871 12A keeps the 2nd, 3rd, 5th, 7th and 11th letters of a
    phrase to spell OASES.
- Letter movement:
  - `cycling`: letters move from one end of the assembly to the other and keep
    their order.
  - `substitution`: one indicated letter or chunk replaces another.
  - `palindrome`: the answer reads the same both ways, and that is the whole
    wordplay (30052 23D PULL-UP, "Stop going both ways?"). It is not a
    `reversal`: nothing is turned round to become something else, so no
    fragment hands over letters. Annotate it like a cryptic definition: blocks
    that split the clue into the definition and the mirror instruction, with
    `pieces` carrying the machine-checkable assembly.

Worked examples:
- 30067 1A GARBAGE = `charade + alternate letters` (GARB + alternate letters of
  bAgGiEr).
- 30066 5D ALLOCATE = `anagram + last letter` (anagram of A COL TALE... + storE,
  "ultimately").
- 30079 7D TSUNAMIS = `charade + cycling` (A + MIST + SUN, back half cycled to
  the front).
- 30079 15D LAUGH LINE = `charade + substitution` (TAUGHT + IN + E, with student
  Ls "covering" for the tense Ts).

**`pieces` and blocks tell the same assembly.** Charades, containers and
deletions carry `pieces`: the final chunks of the answer, in answer order.
Anagrams carry `anagram.fodder` instead. Double definitions, homophones and
hidden words need neither. The blocks must take the answer apart the same way
`pieces` does, not hand it over in one lump, and are listed in the order the
answer reads. The full schema is in `tools/annotate_prompt.md`.

To add a new type part, change all of these in one commit: `TYPE_PARTS` in the
validator, this list, a level-1 blurb in `TYPE_BLURBS` in `app.js`, and a family
in `FAMILIES` in `app.js`. Then run `python3 tools/build_annotate_prompt.py`.

**A sound type must name the sound.** A `homophone` or `spoonerism` puts
`soundsLike` on the block that does the sounding. `soundsLike` is the word you
say aloud; `gives` is the different spelling that goes into the answer. The
validator ERRORs when a sound clue has no `soundsLike`, and when `soundsLike` and
`gives` are the same letters (that is a spelling, not a homophone). A single
block reading "fragment" → ANSWER, with the mechanism left unstated, is the
failure this rule exists to stop. A note that mentions the source word does not
count: it must be the field, because prose cannot be checked. Example: 4096 24D
"Cockney mob" → OARED must show that a mob is a HORDE, that a Cockney drops the
H to leave 'ORDE, and that 'ORDE said aloud is OARED. When another mechanism
feeds the sound (a deletion, a charade), give it its own earlier block. One
block does one operation.

**A spoonerism swaps sounds, so the annotation must show sounds.** On each half,
`soundsLike` is the word that half sounds like before the swap, and `gives` is
the letters it becomes after the swap: `"Money"` → DOUGH → NO, `"Nothing"` →
NOUGHT → DOUBT. Say the two words aloud, swap the sounds at their fronts, and
write the ordinary spelling of what you hear. That respelling is the lesson. If
the vowels shift a little on the way, spend a sentence on it in the walkthrough.
Never swap the two words' first letters and call the result a sound: "NOUGH
DOUGHT" (quiptic 1398 9A) is not a word and cannot be said.
`check_sound_is_not_a_letter_swap()` ERRORs when a `soundsLike` is just the
earlier blocks' letters rearranged. Copy the two-block exchange shape that the
other sound clues use.

**At most two cryptic definitions per puzzle** (`MAX_CRYPTIC_DEFINITIONS`).
`cryptic definition` is the only type with no checkable mechanism. Reaching for
a third means the clue's wordplay has not been found yet, or, in a clue we
wrote, that a joke was written without a mechanism. See `tools/AUTHORING.md`,
"The sentence AND the wordplay". On a puzzle we set, a third is an ERROR. On a
fetched puzzle, two or more is a warning that names each one, so a human can
check none of them hides wordplay. Never leave a clue unannotated to get under
the cap: `check_every_clue_is_annotated()` makes a blank annotation an error.

**A cryptic definition still needs useful blocks.** Its `blocks` may not carry
`gives`, and it needs at least two blocks; both are validator ERRORs
(`check_cryptic_definition_blocks`). Do not use one block that maps the whole
clue to the whole answer: on the hint ladder that gives away the solve one rung
early (for example "Might this keep you to time?" → WATCHSTRAP). A cryptic
definition does not split into letters, but it does split into two readings:
the sense the surface pushes, and the sense the setter meant. Give one block to
each. `app.js` also hides `gives` on this type, so an old annotation cannot leak
the answer while it waits to be rewritten.

### The definition must be substitutable
A definition must be able to REPLACE the answer in a sentence, so it must match
the answer's part of speech and inflection. Paul: "the part of speech needs to
be right." A plural answer needs a plural definition, an `-ing` answer an `-ing`
definition, a verb a verb. Write the swap out before you settle on a definition:
*"NAUTICAL matters" → "matters of the crew"* works, so the adjective phrase `of
the crew` is a fair definition. *"payment" → PEANUTS* fails, because the noun
must agree in number.

`check_part_of_speech()` in the validator warns on the mechanical part (plural
or `-ing` mismatch). The judgement part is yours. The validator deliberately
skips `-ly` and long descriptive phrases, because a warning nobody reads is
worse than no warning.

Agreement is about grammar, not spelling. `aircraft` really is plural, so it
really does define PLANES. Such nouns live in `INVARIANT_PLURALS` in the
validator. Add to that set instead of silencing the warning with a
`definitionNote`, which would tell the learner there is a mismatch when there
is none.

### Account for every word
Every content word of the clue must be claimed by the parse: it belongs to the
definition, to an indicator, or to a block's `clueFragment`. A word left over is
wordplay you have not explained. For example, 30067 13A ("Called out indecent
state of the crew") is not just a homophone of NAUGHTY: `state` = CAL
(California) must also be claimed. `check_coverage()` warns on leftover words.

Hedging words in a walkthrough (`jokingly`, `somehow`, `if you squint`, ...) are
an ERROR. If a walkthrough needs a hedge, the parse is wrong, not the clue.
Add new hedges to `HEDGES` in the validator when they appear.

Publish the finished explanation, never the working-out. A walkthrough,
`definitionFit` or block `note` that argues with itself ("No wait—", "Still
wrong.", "Actually:", "Correct parse:") is an ERROR. So is a walkthrough longer
than `WALKTHROUGH_HARD_MAX` words. Settle the parse first, taking as long as you
need, then write the sentence. If you cannot settle it, the annotation is not
ready: an unannotated clue is better than a published argument.

### What the leftover words turned out to be
A clue word the parse does not account for is always one of these four. Never
ignore it.

1. **A link word.** "Special symbol *indicating* ingredients of pudding batter",
   "Tar was here at sea *to locate* marine bird". It joins definition to
   wordplay and gives no letters. Declare it in `linkWords` (verbatim
   substrings, validated). The app then greys it and strikes it through in the
   clue, and names it on the definition rung. Beginners hunt for a mechanism in
   such words unless told there is none.
2. **An indicator you missed.** In 30040 17D, "facing" is not padding: it puts
   CY in front of P + RIOT. A word that tells you where a piece goes is an
   indicator.
3. **A letter you never named.** A deletion needs a block for the thing
   deleted, not just for the word it is deleted from. 30041 26A ("Pressure,
   therefore, to dispose of hard cash") deletes an H, so it needs a block saying
   *hard* = H.
4. **Real surface padding.** 30067 20D splits the phrase "from bad to worse" and
   uses only half. Give the padding a block with an empty `gives` and a note
   saying so. It is claimed and explained, not dropped. This case exists only in
   published puzzles; see the next rule.

### Exactly two pieces — in clues we WRITE
Paul: "A good cryptic clue doesn't have anything superfluous which isn't
directly part of the wordplay. It should be exactly two pieces. Definition,
optional joinery and wordplay." So in an authored clue every word is part of
the definition, part of the wordplay (fodder or indicator), or a link word
joining the two. Case 4 above, surface padding, is **not allowed**. A block with
`"gives": ""` is a validator ERROR in an authored puzzle (`check_two_pieces`).

This does not change how PUBLISHED puzzles are annotated. Real setters pad, and
the annotator must record that faithfully. So the check is scoped by
`is_authored()` (`series == "authored"`); unscoped, it fires eighteen times on
30039 alone. If it ever fires on a Guardian grid, the scoping is broken. Fix the
scoping; do not relax the rule.

When a word looks like padding, first check whether it is really doing another
job. In A001, two of the nine apparent cases were mis-annotations:

- SIDE's "There's a mole in" is the hidden-word *indicator* (a mole is something
  hidden inside an organisation).
- ARGUE's "There's" is *joinery*: the finite verb that makes the clue a sentence.
  It belongs in `linkWords`.

Why this matters: a funny sentence is easy if filler is allowed. Banning filler
is what separates a clue from a joke that happens to contain the answer. See
`tools/AUTHORING.md`, "Exactly two pieces".

### The joints: link words, adjacency, direction
Three rules about how the pieces of a clue attach to each other. All three are
ERRORs in the validator, all three are scoped by `is_authored()`, and all three
had **zero hits** across the eight annotated Guardian puzzles before they
shipped. `--unscoped` runs them on published grids. The counts and reasoning are
in `tools/AUTHORING.md`, "The joints".

1. **A link word stands in for an equals sign.** Paul: "link words have to stand
   in for an equals sign." A link word may state equivalence (`is`, `'s`),
   derivation (`gives`, `makes`, `becomes`, `yields`, `means`, `leads to`,
   `indicating`, `to locate`) or plain prepositional joining (`for`, `from`,
   `of`, `in`, `with`, `after`), plus the grammatical glue that holds those
   together. Anything else is a content word doing surface work: `lives on`,
   `would be better spent`, `mistake it for`. Putting padding in `linkWords` is
   how a clue dodges the two-pieces rule: the annotation looks sound while the
   clue is in three pieces. So `EQUIVALENCE_LINKS` in the validator is an allow
   list, not a block list. Widen it when a real setter's link word fails; never
   widen it for one of ours.
2. **An indicator operates on what it touches.** An anagram indicator must be
   next to its fodder, with only grammatical glue between them (`FODDER_GLUE`
   in the validator: articles, forms of *be*, and short joining words such as
   `of`, `in`, `with`). `Naples was flattened by aircraft` is fine. `The oyster
   lives on the ground floor` is not: `ground` cannot reach back over three
   words to shuffle `The oyster`. The check measures character offsets in the
   clue, so it is arithmetic, not taste.
3. **A reversal runs along the entry.** A reversed across answer reads right to
   left, so it needs `back`, `returning`, `retreating` or `west`. A reversed
   down answer reads bottom to top, so it needs `up`, `rising`, `climbing`,
   `lifted` or `from below`. There is no "backwards" on a vertical axis. Neutral
   words (`turning`, `about`, `overturned`, `revolutionary`, `reversal`) are
   always safe; use them when the surface wants a word the direction does not
   allow. The eight Guardian puzzles follow this in 19 of 19 reversals.

A smooth surface is not evidence that a clue is sound. STOREY felt like the best
clue in its set because the padding made the surface smooth.

### A link word that orders the pieces is an indicator
If a joining word is what puts the pieces in the answer's order, it is an
indicator, not a link word. The app tells the solver a link word "contributes no
letters of its own", so a word that orders the pieces must not be filed there.
Example: in "Post on half of wage" (30099 25A), `on` is the only thing that says
the post goes at the BACK of the answer. In an across entry, "A on B" puts B
first, then A; in a down entry, A sits above B.

The test is mechanical, and it is the check: if the blocks either side of the
joiner come out in the opposite order to the clue, and no indicator between them
could have done it, the joiner did. Move the word to `indicators` and give it an
`indicatorNotes` line saying which piece it sends second.
`check_link_word_is_not_an_order()` warns, on every puzzle including published
ones, because the parse is ours even when the clue is the Guardian's. `on` and
`after` stay in `EQUIVALENCE_LINKS`, because usually they only join: of 65
corpus entries that declared a positional joiner as a link word, only three were
ordering anything.

### The blocks already told them
Paul: "When you basically give the whole answer in the building blocks you don't
need to have the full walkthrough." The `blocks[]` rung already shows the
learner fragment → letters, with a note on each. A walkthrough that repeats
those steps is padding. Keep only what the blocks CANNOT show:

- why the surface misleads,
- the joke, in one clause,
- a convention (`ER` = Queen, `worker` = ANT, `H` = husband),
- why a definition is fair.

Trimmed this way, A001's twenty walkthroughs went from 44-63 words (median 54)
to 19-42 (median 32), which matches the median of published walkthroughs.

`check_walkthrough_budget()` warns above `MAX_WALKTHROUGH_WORDS` (45; the
published 90th percentile is 42) when a blocks rung exists, and only on authored
puzzles. It is a word budget, not a redundancy detector. A semantic version that
scored recycled vocabulary was built, measured and rejected, because good
walkthroughs scored worse than bad ones. Keep the walkthrough short but never
empty: `ladderSteps()` always shows the walkthrough rung, so an empty one is a
labelled hole in the ladder.

### A block's note must not name the answer
The blocks rung comes before the walkthrough, so its reader has chosen not to
see the solution yet. A `blocks[].note` that says the answer word leaks it. Bad:
"a run-in is a quarrel or confrontation" for RUN-IN; "pulses are the crop family
beans belong to" for PULSE; "the letters run straight across the gap:
n(O SLO)venian" for OSLO. Write the note about the *fragment*: what "Beat"
means, where the letters sit, which convention applies. The walkthrough is the
first place the answer is spelled out. `check_block_notes_dont_name_the_answer()`
ERRORs when a block note names the answer, and `app.js` refuses to show a
`gives` that equals the answer.

For a hidden word this is the whole lesson. Point at the span and say the
letters run consecutively inside it, and leave the extraction to the solver,
because that is the skill. Bracketing the answer out of the clue text does it
for them.

### Anagram or insertion? Check the order before you label it
Every insertion is also a valid anagram of the same letters. So `anagram` is
wrong whenever the answer can be built by putting one chunk inside another with
each chunk's letters kept in order. GREAT APES is not an anagram of GRAPES + EAT;
it is GR + EAT + APES, and the indicator (bore = drill into) says so. Test the
order-keeping reading first, and use `anagram` only when there is none. The
mechanism the solver must perform is what is being taught.

### An indicator that does its job loosely: say so
This mirrors the definition rule below. When an indicator is vague, stretched or
understood only by convention, say so plainly in `indicatorNotes`. Saying it is
loose does not mean leaving the choice to the grid. The crossing letters settle
only what the clue really leaves open (which article, which colour, which of two
spellings), never what the other pieces settle. "Half of wage" does not say which
half, but only one half joins the rest to make a word, so "the clue leaves it to
the crossing letters" is wrong: parse it (30099 25A). A learner who cannot find
a precise instruction needs to hear that the looseness is the setter's, not a
failure of their solving.

Silence reads as significance. So when a feature of the clue carries no wordplay
at all (capitals used for surface effect, a quoted phrase, odd punctuation), say
so explicitly instead of leaving the solver to hunt for a meaning.

### When the definition really doesn't agree: say so
Sometimes the setter's definition really does not match the answer's number or
part of speech: "Lousy payment" for PEANUTS, "hearing aid" for EARPHONES, "work"
for OPUSES. Do not hide it and do not stretch the definition to fit. Add a
`definitionNote`: a sentence, shown to the learner on the definition rung,
saying what disagrees and why the setter is allowed it (a mass-noun idiom,
objects that come in pairs, a plural naming one thing). A `definitionNote` also
silences `check_part_of_speech()`, so the validator requires it to be a real
explanation of at least 25 characters, not a rubber stamp. An unexplained
mismatch is a bug; an explained one is a lesson.

## Rules for validator checks

### Heuristics must know real words
Prove a pattern is real before warning about it, and run a new check against
every annotated puzzle before committing it. Noise makes a check ignorable. For
example, `check_part_of_speech()` consults `/usr/share/dict/words`: it treats an
answer as a gerund only if the stem is a word (MARAUD yes, VIK from VIKING no),
and as a plural only if the singular is a word (EARPHONE yes, CHAOS no). It skips
multi-word answers, whose final `-S` belongs to an inner noun (PICK UP THE
PIECES). If the word list is missing, the check stands down instead of guessing.

### Fakes must not diverge from the real thing
When a test harness fakes an API, the fake must keep that API's contracts. A
divergence does not fail loudly; it makes tests pass when they should not.
Example: `tools/smoke_test.js` uses a fake DOM. When setting `el.id` on a created
element did not register it with `getElementById`, the app and the test held two
different objects with the same id, and assertions about dynamically created
elements checked nothing.

## Existing schema rules
See `tools/annotate_prompt.md`: definition and indicator strings are verbatim
substrings of the clue, pieces and fodder are letter-perfect, grouped entries
get `linkedTo` stubs, and the validator must pass before commit.
