# Cryptic Teacher style guide

This is the permanent home for product feedback. When Paul gives feedback on a
puzzle, a hint, or the app, the fix goes in TWO places: the instance that prompted
it, and a rule here (plus, where possible, a mechanical check in
`tools/validate_annotations.py` or an assertion in `tools/smoke_test.js`).
`tools/annotate_prompt.md` tells the daily annotation run to follow this file, so
rules added here apply to every future puzzle automatically.

### A new rule binds the next puzzle, not just the one that prompted it
A rule invented after 150 puzzles are annotated cannot fail the corpus on the day
it lands, and the old answer to that was a `REQUIRE_X = False` flag to be flipped
by hand once a backfill drained the backlog. That leaves the rule optional for
precisely the puzzles it exists for — the ones not written yet — and it stays
optional for as long as anyone forgets. So the allowance is per puzzle and
written down: `tools/annotation_backlog.json` records how many clues of each
existing puzzle predate each field, the validator ERRORs the moment a puzzle
exceeds its own number, and a puzzle absent from the file — every puzzle fetched
from now on — is allowed none. It only ever shrinks, so draining a puzzle
tightens the rule on it permanently, and `tools/prereset_backfill.sh` reads its
field list out of the same file rather than naming fields itself. Adding a
grandfathered field means adding it to `BACKLOG_MARKERS` and running
`python3 tools/validate_annotations.py --tighten` once (feedback 2026-08-17:
"Don't just fix the things I point out, make sure future puzzles get the fixes
too").

## Annotation rules

### Honest types (feedback 2026-07-26)
The `type` field must name EVERY mechanism the wordplay uses, joined with
`" + "`, in the order they occur. Never label a clue with just its dominant
mechanism: if a charade's second chunk comes from the alternate letters of a
word, the type is `charade + alternate letters`, not `charade`.

Controlled vocabulary (enforced by the validator — extend `TYPE_PARTS` there and
the list below together):

- Base types: `anagram`, `charade`, `container`, `hidden word`, `homophone`,
  `reversal`, `deletion`, `double definition`, `cryptic definition`, `&lit`,
  `spoonerism`
- Letter selection: `first letter(s)`, `last letter(s)`, `middle letter(s)`,
  `outer letters`, `alternate letters`, `regular letters` (letters taken at a
  fixed step other than every second one — 30077 17D takes every THIRD letter
  of "Hope to God" to spell POD), `second letter(s)` (a letter picked by its
  position — 12420 14D takes the second letter of "master" for the A of AGO,
  and 30065 6D takes the second letter of each of four words to spell EDAM)
- Letter movement: `cycling` (letters rotate from one end of the assembly to
  the other, keeping their order), `substitution` (one indicated letter or
  chunk stands in for another)

Worked examples: 30067 1A GARBAGE = `charade + alternate letters` (GARB +
alternate letters of bAgGiEr); 30066 5D ALLOCATE = `anagram + last letter`
(anagram of A COL TALE... + storE "ultimately"); 30079 7D TSUNAMIS =
`charade + cycling` (A + MIST + SUN, back half cycled to the front); 30079
15D LAUGH LINE = `charade + substitution` (TAUGHT + IN + E with student Ls
"covering" for the tense Ts).

When a new type part is needed, add it to `TYPE_PARTS` in the validator, this
list, and a level-1 blurb in `TYPE_BLURBS` in `app.js` — all three, in one commit.

**A sound type must name the sound.** `homophone` and `spoonerism` carry
`soundsLike` on the block that does the sounding: the word you say ALOUD, which
`gives` then spells differently. The validator errors when a sound clue has
none, and errors when the two are the same letters — that is a spelling, not a
homophone. This exists because 18 of the corpus's 48 sound clues had a block
reading “fragment” → ANSWER and nothing else, with the entire mechanism
unstated: 4096 24d rendered “Cockney mob” → OARED, never showing that a mob is
a HORDE, that a Cockney drops the aitch to leave ’ORDE, or that ’ORDE said
aloud is what you write ("doesn't explain that the original word is hoard but
it is a homophone and you drop the h to it", Paul, 2026-08-17). A note
mentioning the source in passing is not enough and was not enough — that clue
had one. It has to be a field, because prose cannot be checked. Where another
mechanism feeds the sound (a deletion, a charade), that mechanism gets its own
earlier block; one arrow does one operation.

`cryptic definition` is capped at **two per puzzle**, a validator ERROR above
that (`MAX_CRYPTIC_DEFINITIONS`). It is the only type with no checkable
mechanism, so reaching for a third means either the clue's wordplay has not been
found yet or — when we wrote the clue ourselves — a joke got written and a
mechanism did not. See `tools/AUTHORING.md`, "The sentence AND the wordplay".

The ones that survive that test still have to be annotated into something worth
paying a hint for. A cryptic definition's `blocks` may not carry `gives`, and
there must be at least two of them — both validator ERRORS
(`check_cryptic_definition_blocks`). There is exactly one block shape available
to an annotator who does not think about it, the whole clue giving the whole
answer, and it renders as hint 3 of 4 reading “Might this keep you to time?” →
WATCHSTRAP: the rung before it has just said there is no separable wordplay, and
this one sells the solve (Paul, 1392 22-across, 2026-08-10). A cryptic
definition does not split into letters, but it does split into readings — the
sense the surface pushes, and the sense the setter meant — and one block each is
the smallest annotation that shows the seam. `app.js` suppresses `gives` on this
type as well, so a stale annotation cannot leak while it waits to be rewritten.

### The definition must be substitutable (feedback 2026-07-29)
A definition has to be able to REPLACE the answer in a sentence — which means
matching its part of speech and its inflection. Paul's words: "the part of speech
needs to be right." A plural answer needs a plural definition, an `-ing` answer an
`-ing` definition, a verb a verb. Write the substitution out before you commit to a
definition: *"NAUTICAL matters" → "matters of the crew"* works, so the adjective
phrase `of the crew` is a fair definition; *"payment" → PEANUTS* would need the
noun to agree in number.

`check_part_of_speech()` in `tools/validate_annotations.py` catches the mechanical
half of this (plural / `-ing` disagreement) as warnings. The judgement half is
yours — the validator deliberately skips `-ly` and long descriptive phrases,
because a warning nobody reads is worse than no warning.

Agreement is about grammar, not spelling: `aircraft` genuinely is a plural and so
genuinely does define PLANES. Those nouns live in `INVARIANT_PLURALS` in the
validator; extend that set rather than papering over the warning with a
`definitionNote`, which would tell the learner a mismatch exists when it does not.

### Account for every word (feedback 2026-07-29)
Every content word of the clue must be claimed by the parse: it belongs to the
definition, to an indicator, or to a block's `clueFragment`. A word left over is
wordplay you have not explained. 30067 13A ("Called out indecent state of the
crew") was annotated as a homophone of NAUGHTY alone, and `state` = CAL
(California) was silently dropped; the walkthrough then papered over the gap with
"jokingly adjectived". `check_coverage()` flags leftover words as warnings, and
hedging words in a walkthrough (`jokingly`, `somehow`, `if you squint`, …) are a
hard ERROR — if a walkthrough needs a hedge, the parse is wrong, not the clue.
Extend `HEDGES` in the validator when a new fudge shows up.

The published text is the finished explanation, never the working-out. A
walkthrough, a `definitionFit` or a block `note` that is still arguing with
itself ("No wait—", "Still wrong.", "Actually:", "Correct parse:") is a hard
ERROR, as is any walkthrough over `WALKTHROUGH_HARD_MAX` words. Found
2026-08-05 benchmarking a cheaper annotation model: it passed every mechanical
check on 30073 and handed the reader a 177-word 1A walkthrough that backtracked
five times and never landed on a parse. Settle the parse first — think as long
as you like — then write the sentence. If you cannot settle it, the annotation
is not ready, and an unannotated clue is better than a published argument.

### What the leftover words turned out to be (feedback 2026-07-29)
Working through every warning `check_coverage()` raised produced four distinct
causes, and each one has a right answer. When a clue word is unaccounted for, it
is one of these — never "ignore it":

1. **A link word.** "Special symbol *indicating* ingredients of pudding batter",
   "Tar was here at sea *to locate* marine bird". These join definition to
   wordplay and contribute no letters. Declare them in `linkWords` (verbatim
   substrings, validated). They are then greyed and struck through in the clue
   and named on the definition rung — beginners hunt for a mechanism in these
   words precisely because nothing ever tells them there isn't one.
2. **An indicator you missed.** 30040 17D's "facing" is not padding: it is what
   puts CY in front of P + RIOT. If a word tells you where a piece goes, it is an
   indicator.
3. **A letter you never named.** 30041 26A ("Pressure, therefore, to dispose of
   hard cash") deleted an H without ever saying *hard* = H. A deletion must have
   a block for the thing deleted, not just for the thing it is deleted from.
4. **Genuine surface padding.** 30067 20D splits the phrase "from bad to worse"
   and uses only half. That is a real solving insight, so it gets a block with an
   empty `gives` and a note saying so — claimed and explained, not silently
   dropped.

### Exactly two pieces — in clues we WRITE (feedback 2026-07-29)
Paul's words: "A good cryptic clue doesn't have anything superfluous which isn't
directly part of the wordplay. It should be exactly two pieces. Definition,
optional joinery and wordplay." So every word of an authored clue is part of the
definition, part of the wordplay (fodder or indicator), or a link word joining
the two — and case 4 above, surface padding, is **not available**. A block with
`"gives": ""` is a validator ERROR in an authored puzzle (`check_two_pieces`).

This does not change annotation of PUBLISHED puzzles one bit. Real setters pad,
the annotator must be able to record it faithfully, and the check is scoped by
`is_authored()` (`series == "authored"`) for exactly that reason: unscoped it
fires eighteen times on 30039 alone. If it ever lights up a Guardian grid, the
scoping is broken — do not relax the rule.

When a word looks like padding, first ask whether it is really doing one of the
other jobs, because two of the nine A001 cases were mis-annotation: SIDE's
"There's a mole in" is the hidden-word *indicator* (a mole is a thing concealed
inside an organisation), and ARGUE's "There's" is *joinery*, the finite verb that
makes the clue an utterance — it belongs in `linkWords`. The deeper point, and
why this recurs: a funny sentence is easy if you are allowed filler, so banning
filler is what separates a clue from a joke that happens to contain the answer.
See `tools/AUTHORING.md`, "Exactly two pieces".

### The joints: link words, adjacency, direction (feedback 2026-07-30)
Three rules about how the pieces of a clue attach to each other, all three
ERRORs in `tools/validate_annotations.py`, all three scoped by `is_authored()`,
all three calibrated at **zero hits** across the eight annotated Guardian
puzzles before shipping (`--unscoped` runs them on published grids; the counts
and the reasoning are in `tools/AUTHORING.md`, "The joints").

1. **A link word stands in for an equals sign.** Paul's words: "link words have
   to stand in for an equals sign." It may assert equivalence (`is`, `'s`),
   derivation (`gives`, `makes`, `becomes`, `yields`, `means`, `leads to`,
   `indicating`, `to locate`) or plain prepositional joining (`for`, `from`,
   `of`, `in`, `with`, `after`), and it may be grammatical glue holding those
   together. Anything else is a content word doing surface work: `lives on`,
   `would be better spent`, `mistake it for`. Declaring padding in `linkWords`
   is the loophole in the two-pieces rule — the annotation looks sound while the
   clue is quietly in three pieces — so `EQUIVALENCE_LINKS` in the validator is
   a whitelist, not a blacklist. Widen it when a real setter's link word fails;
   never widen it for one of ours.
2. **An indicator operates on what it touches.** An anagram indicator must be
   adjacent to its fodder, with only grammatical glue between (`FODDER_GLUE`:
   `was`, `is`, `a`, `the`, `of`, `in`, `with`). `Naples was flattened by
   aircraft` is fine; `The oyster lives on the ground floor` is not, because
   `ground` cannot reach back over three words to shuffle `The oyster`.
   Measured from character offsets in the clue, so it is arithmetic, not taste.
3. **A reversal runs along the entry.** An across answer reversed reads right to
   left, so it wants `back` / `returning` / `retreating` / `west`; a down answer
   reads bottom to top, so it wants `up` / `rising` / `climbing` / `lifted` /
   `from below`. There is no backwards on a vertical axis. Neutral vocabulary
   (`turning`, `about`, `overturned`, `revolutionary`, `reversal`) is always
   safe and is the escape hatch when the surface wants a word the axis will not
   license. The eight Guardian puzzles observe this 19 times out of 19.

The post-mortem worth remembering: STOREY *felt* like the best clue in the set
because the padding is what made the surface smooth. Surface quality is not
evidence of soundness.

### The blocks already told them (feedback 2026-07-29)
Paul's words: "When you basically give the whole answer in the building blocks
you don't need to have the full walkthrough." The `blocks[]` rung already gives
the learner fragment → letters with a note on each, so a walkthrough that
re-narrates the same steps is padding in the teaching UI. Keep only what the
blocks CANNOT show: why the surface misleads, the joke in one clause, a
convention (`ER` = Queen, `worker` = ANT, `H` = husband), or why a definition is
fair. A001's twenty walkthroughs went from 44-63 words (median 54) to 19-42
(median 32), which is the published median.

`check_walkthrough_budget()` warns above `MAX_WALKTHROUGH_WORDS` (45; the
published 90th percentile is 42) when a blocks rung exists, and — like the rule
above — only on authored puzzles. It is a budget, not a redundancy detector: a
semantic version scoring recycled vocabulary was built, measured and rejected
because good walkthroughs scored worse than bad ones. The walkthrough may be
short but never absent: `ladderSteps()` always emits the rung, so an empty one is
a labelled hole in the ladder.

### A block's note must not name the answer (2026-08-25)
The building blocks are the rung before the walkthrough, so anything written
there is read by a learner who has deliberately not bought the solve yet. That
makes `blocks[].note` a leak the moment it says the word: "a run-in is a quarrel
or confrontation" for RUN-IN, "pulses are the crop family beans belong to" for
PULSE, "the letters run straight across the gap: n(O SLO)venian" for OSLO. Write
the note about the *fragment* instead — what "Beat" means, where the letters sit,
which convention is in play — and let the walkthrough be the first place the
answer is spelled. `app.js` refuses to render a `gives` that equals the answer,
so the letters can never leak; the prose is the annotator's to keep clean.

For a hidden word this is the whole lesson: pointing at the span and saying the
letters are consecutive inside it leaves the extraction as the solver's move,
which is the skill. Bracketing the answer out of the clue text does the move for
them.

### Anagram or insertion? Check the order before you label it (2026-08-25)
Every insertion is also a valid anagram of the same letters, so `anagram` is the
wrong call whenever the fodder can be assembled by putting one chunk inside
another with both chunks' letters left in their original order. GREAT APES is not
an anagram of GRAPES + EAT; it is GR + EAT + APES, and the setter's indicator
(bore = drill into) says so. Test the order-preserving reading first and only
reach for `anagram` when none exists — the mechanism the solver has to perform is
the thing being taught, and shuffling is not the mechanism here.

### An indicator that does its job loosely: say so (2026-08-25)
The mirror of the definition rule below. When an indicator is vague, stretched or
only conventionally understood, name the imprecision in `indicatorNotes` in those
words. A learner who cannot find a precise instruction needs to be told the
looseness is the setter's, not a failure of their solving. Silence reads as
significance, which is also why a signal that carries no wordplay at all —
capitalisation for surface effect, a quoted phrase, odd punctuation — is worth
retiring out loud rather than leaving to be hunted.

### When the definition really doesn't agree: say so (feedback 2026-07-29)
Sometimes the setter's definition genuinely does not match the answer's number or
part of speech — "Lousy payment" for PEANUTS, "hearing aid" for EARPHONES, "work"
for OPUSES. Do not paper over it and do not stretch the definition to fit. Add a
`definitionNote`: a sentence, shown to the learner under the definition rung,
saying what disagrees and why the setter is allowed it (mass-noun idiom, objects
that come in pairs, a plural naming one thing). It also silences
`check_part_of_speech()`, so the validator requires it to be a real explanation
(≥25 chars), never a rubber stamp. The unexplained mismatch is the bug; the
explained one is a lesson.

### Heuristics must know real words (feedback 2026-07-29)
The first cut of `check_part_of_speech()` warned on VIKING because it ends in
`-ING`, and on PICK UP THE PIECES because it ends in `-S`. Both were noise, and
noise is what makes a check ignorable. It now consults `/usr/share/dict/words`:
an answer is only treated as a gerund if the stem is a word (MARAUD yes, VIK no)
and only as a plural if the singular is (EARPHONE yes, CHAOS no), and multi-word
answers are skipped since their trailing `-S` belongs to an internal noun. If the
wordlist is missing, the check stands down rather than guessing. General rule for
any new validator check: prove the pattern is real before warning about it, and
test the check against every annotated puzzle before committing it.

### Fakes must not diverge from the real thing (feedback 2026-07-29)
`tools/smoke_test.js` uses a fake DOM. Setting `el.id` on a created element did
not publish it to `getElementById`, so the app and the test held two different
objects with the same id and assertions about dynamically-created elements were
quietly vacuous. When a test harness fakes an API, the fake has to keep that
API's contracts — a divergence does not fail loudly, it makes tests lie.

### Existing schema rules
See `tools/annotate_prompt.md`: verbatim definition/indicator substrings,
letter-perfect pieces/fodder, `linkedTo` stubs for grouped entries, validator
must pass before commit.

---

The rules for how the app *presents* those annotations — the hint ladder, the
reference corpus, deploy and cache-busting — live in `APP.md`. They are a
separate file because the nightly annotator is told to read this one whole, and
it holds one puzzle file: it can act on none of that, and paying to cache it on
every run bought nothing. Put a rule where the reader who must obey it will
look.
