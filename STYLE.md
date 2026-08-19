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
  `outer letters`, `alternate letters`
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
`is_authored()` (ids starting with a letter) for exactly that reason: unscoped it
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

## Hint-ladder / UX rules

- The ladder is built PER CLUE, not from a fixed template (feedback
  2026-07-26: a double definition showed "double definition", then a rung
  restating the same thing, then a rung saying "no indicator words"). Rules:
  a rung only exists if it carries new information — no indicators means no
  indicator rung; no rung may merely restate an earlier one. See `ladderSteps()`
  in `app.js`; the ladder length is per clue and shown as "x/N" in the meter.
- The BODY is per clue; the NAME is not. This rule used to read "rung wording is
  type-specific (a double definition asks 'where does the clue split?', an &lit
  asks 'how can the whole clue be the definition?')" and that was backwards: the
  names of the rungs you have not bought are on screen the whole time, because
  that is how you choose one. So a name that varies with the type is a free
  hint, and on a semi-&lit hidden word it is the whole solve — 4096 21d VSIGN
  ("What may you get from chavs, ignobly?") offered an unbought button reading
  "How can the whole clue be the definition?", which is the entire trick, told
  for nothing ("21d gives away the whole thing just by the name of the hint
  before I reveal it", Paul, 2026-08-17). Same for "Where does the clue split?",
  "What is the clue really describing?", "What each half means", and the
  singular/plural indicator label, which handed over the count. A label is now a
  function of the rung's key alone (`LABELS` in `app.js`), and the smoke test
  sweeps every annotated clue in the corpus and fails if any rung is named more
  than one way. A rung asks its question; the answer is what you are paying for.
- Never write a count into prose beside the list it counts. The compound
  indicator rung said "this clue does two things" and then listed three, on
  `container + charade + middle letters + reversal` (Paul, 4096 16d, 2026-08-17).
  Number words come off `.length`, always.
- Rung 3 says what the indicator DOES; `indicatorNotes` says why that word means
  it. The general sentence ("it tells you to shuffle the letters") is identical on
  every anagram in the corpus, which is what makes the rung feel content-free to
  pay for — the complaint has now been made twice ("these tell you what to do with
  the rest is terrible to pay for a hint for", 2026-08-02; "the indicator didn't
  explain why stable no was an indicator", 4096 20a, 2026-08-17). One sentence per
  indicator, keyed by the identical string, naming the sense of the word that
  carries the instruction: 'stable? No' means unstable, and unstable will not stay
  in the order it is given. It renders before the answer, so it is gated by
  `EARLY_RUNG_FIELDS`; the validator requires it of every puzzle except the ones
  `tools/annotation_backlog.json` grandfathers, so a new puzzle cannot ship
  without it while the old ones drain.
- Generic wording is not a frame to put around a real answer — it is what gets
  said when there is no real answer. So where every indicator has a note, the
  notes are the whole of rung 3: no "this clue does two things, and the
  indicators are what tell them apart", no list of the operations, no "which word
  calls for which is the step to work out here" ("this is just context free,
  never just put out text for the sake of filling space", Paul, 2026-08-17). The
  count was the tell — the operations come off the clue TYPE, so `container +
  charade + middle letters + reversal` promises four while only three of them
  have an indicator to point at. That sentence never described the indicators; it
  described the type, and the type is rung 1. The generic branch survives only
  for the puzzles that predate `indicatorNotes`, and `tools/smoke_test.js`
  enforces the rule structurally rather than by banned phrase: strip the notes
  list from a fully-noted rung and what is left must be empty, so new filler
  cannot pass by not being on a list.
- Do not point at the surface picture with a definite noun phrase you never drew —
  see `tools/annotate_prompt.md`. "The impromptu band keeps both looking innocent"
  on a walkthrough that never mentioned a band ("this doesn't sound natural", 4096
  14D, 2026-08-17). Name the picture in the clue's own words.
- A hint that has been bought never leaves the screen. Highlighting a fragment is
  a PLACEMENT, not a search: `indexOf` matched the indicator 'in' inside
  "Conclud(in)g", "island" and "confusion" on 18 clues, and on 15 more the mark it
  chose landed under the definition, where the old overlap rule deleted whichever
  came second — always the indicator, because indicators are pushed last. So
  buying the definition rung visibly removed a hint you had already paid for
  ("I think it might always be the indicator clue which is disappearing after
  click", Paul, 2026-08-17). Each fragment now takes the best occurrence still
  free, preferring whole words (an edge that is itself punctuation may abut a
  letter — "’s gone out of" in "Pound’s gone out of"), nothing is dropped, and
  where two marks genuinely overlap the SHORTER one wins the overlap so both stay
  visible. The smoke test buys every rung on every annotated clue in the corpus
  and reads the marks back off the rendered HTML.
- A tap must leave the soft keyboard exactly as it found it, unless the tap is
  going to type. On iOS the keyboard IS the viewport: it arriving and it leaving
  are the same size of reflow, and either one lands on the page in the same
  instant the new rung is drawn, which reads as the hint flashing open and shut.
  Both directions have now been reported, and each was caused by the fix for the
  other: dismissing one ("clicking hints sometimes triggers them quickly open
  then closed", iPhone, 2026-08-16), then summoning one for a solver who had none
  up ("I just clicked a hint once on my iPad and it opened then quickly closed",
  iPad, 2026-08-17). So the rule is not "focus the input on mousedown" — it is
  that controls which move the cursor (the grid, the letter strip) raise the
  keyboard, and controls which only reveal text (the hint buttons, the escape
  hatch) keep whatever state they were handed: `document.activeElement === $("kbd")`
  at mousedown, before the default focus transfer. Asserted in the smoke test in
  all three states, because a fix for one alone is what caused the other.
- The ladder is TIERED: free choice within a tier, no choice across tiers
  (`RUNG_TIER` in app.js). Tier 0 is what the clue asks you to SPOT — the family,
  the definition, the indicators — and any of them may be taken in any order.
  Tier 1 is the building blocks, which unlock only once every tier-0 rung this
  clue has is up. Tier 2 is the walkthrough, which unlocks after the blocks.
  Both halves of that are feedback and both have to hold:
  - Free within a tier (2026-08-01: "can I choose my hint instead of being
    forced to get the definition first?"). Finding the definition is most of the
    skill; wanting the indicators must not cost you it.
  - Gated across tiers (2026-08-01, correcting the first cut of the above: "the
    building blocks and walkthrough can be done first — the choice should be
    between just definition and indicator first, then building blocks, then
    walkthrough"). A later rung restates the earlier ones on its way to giving
    away the answer, so unrestricted choice put "skip to the walkthrough" one
    click from cold, which is not a ladder.
  Locked rungs are rendered disabled, not hidden — the solver should see the
  shape of what's coming. The recommended next rung leads and is labelled "Show
  hint N"; the rest of its tier are quiet ghost buttons. A rung keeps its ladder
  number wherever it is taken, so gaps in the numbering show what was skipped.
  This is a data-model rule as much as a UI one: revealed rungs are a SET
  (`hintsShown`, entryKey -> rung keys), not a high-water mark. An integer can
  only express "the first N", so any rung it granted dragged in every rung
  below it — which is precisely the forcing being complained about. Do not
  reintroduce a scalar here. A rung a clue does not HAVE must never gate one it
  does (many clues have no indicators rung and no blocks rung), which is why
  availability is computed against this clue's steps, not a fixed list.
- The full walkthrough must end by saying WHY the answer means the definition
  (feedback 2026-08-01: "in the full walkthrough explain why the answer matches
  the definition"). This is the `definitionFit` field, required on every
  annotation, rendered immediately before the answer. The blocks spell the answer
  out of the wordplay and the definition rung points at the words, but nothing
  used to join the two ends — and that link is the non-mechanical half of a
  cryptic, the half a solver is missing when they have the right letters and no
  confidence in them. Name the RELATION: plain synonym, definition by example,
  a sense that survives mainly in crosswords, a technical or regional use, a
  whole-phrase idiom. Restating the definition with the answer substituted in
  ("an army ant is a crawler") is a validator ERROR — it contains no content word
  that isn't already in the definition or the answer, which is exactly how
  `check_definition_fit` detects it. Distinct from `definitionNote`, which
  justifies a definition that DISAGREES with the answer grammatically; every clue
  has a fit, only a few need a note.
- Every rung marks up its OWN words in the clue text, independently of the other
  rungs, and the legend names exactly the marks that were drawn (feedback
  2026-08-01: "if I choose just the indicator clue now it doesn't highlight the
  parts of clue"). `clueHTML` used to gate ALL highlighting on the definition
  rung, and the legend with it. That was invisible while the ladder was strictly
  ordered and became a bug the moment tier 0 allowed any order: taking the
  indicators first — the legitimate route, since working out where the
  definition sits is most of the skill — spent a hint and lit nothing, so the
  one rung you paid for showed you nothing. The general rule, and the thing to
  check whenever a rung is added: **highlight exactly what has been revealed,
  and never anything that hasn't.** Link words ride with the definition rung
  (they betray where the definition ends), which is a deliberate pairing, not
  another gate. This is the second bug of this exact shape — a display keyed off
  one rung when it should be keyed off its own — so the smoke test now drives
  the indicators-alone route directly and asserts both directions: the indicator
  is marked, the definition is not.
- The puzzle picker lists only puzzles with `annotated: true`, plus the one
  currently open and any with saved progress (feedback 2026-08-01: "we only want
  to only show ones that have full annotations", alongside "hard to navigate as
  we get more puzzles"). The two are the same problem: fetching is nightly and
  annotating is one puzzle per run, so the un-taught puzzles are the majority and
  they grow faster than the taught ones. A row that cannot teach you anything is
  noise in the one dialog whose job is "what should I do next".
  Hidden must never mean unreachable, and that is what makes the filter
  load-bearing rather than decorative: **a query searches every puzzle**,
  annotated or not, so a number you know still finds its puzzle; the archive page
  lists them all and the picker footer links to it; `?p=<n>` opens anything. The
  box is focused on open and Enter takes the top row, so number-in/puzzle-open
  needs no mouse. Do not "simplify" this by filtering only the rendered rows —
  that would make the un-annotated puzzles unreachable from the app, and the
  smoke test asserts the search path specifically.
- Badge the exception, never the norm (feedback 2026-08-01: "since it only lists
  full hints we don't have to show it"). There is no "full hints" badge anywhere
  in the app — not on picker rows, not on the puzzle title. Once the picker
  listed annotated puzzles only, that badge asserted the same thing about every
  row, which communicates nothing while still taking a line of the row; being
  taught is simply what a puzzle here IS. The `auto hints` badge stays, because
  it is now the only thing the badge slot ever says, and it says it exactly when
  the puzzle in front of you is the odd one out. The generated archive page
  (`tools/build_seo_pages.py`) does badge both states, and should: it lists every
  puzzle, so there the distinction is real. Generalise this — a label that every
  item carries is decoration, not information.
- Rung 1 names the clue FAMILY, never the precise type (feedback 2026-07-26:
  "the type of clues seem a bit specific for a first hint"). Opening a clue with
  `charade + alternate letters` hands over the whole mechanism. The families,
  in match order (first match wins, so the dominant mechanism of a compound type
  decides): **Definitions only** (double/cryptic definition), **&lit**,
  **Rearrangement** (anagram), **Sound** (homophone, spoonerism), **Charade**,
  **Alteration** (container, reversal, deletion), **Extraction** (hidden word and
  all the letter-selection parts). Charade stays its own family — it is the most
  common build and reads nothing like a container or a reversal. The exact type
  appears later, on the building-blocks rung (or the walkthrough if there is no
  blocks rung), styled `.mechanism`; double and cryptic definitions skip it
  entirely, since the family label already said it. Every part in `TYPE_PARTS`
  must be claimed by exactly one family in `FAMILIES` in `app.js` — adding a type
  part means assigning it a family in the same commit.
- The ladder never offers information that is useless given what the user
  already knows. Concretely: after the level-5 walkthrough names the answer,
  the final rung is "Fill in answer" — never letter reveals (feedback
  2026-07-26).
- Every check must SAY what it found (feedback 2026-07-29: "I clicked it and
  didn't see anything change"). Checking used to mark wrong letters and nothing
  else, so checking a correct entry was indistinguishable from a dead button.
  A check now always writes a sentence into `#check-result` — wrong letters
  marked, all correct so far, or nothing typed yet — and pulses the squares it
  examined so its scope is visible too. General rule: no control may respond to a
  click with silence; if there is nothing to report, report that. See
  `checkCells()`/`announceCheck()` in `app.js` and the check assertions in
  `tools/smoke_test.js`.
- "Reveal one letter" is a standalone anytime escape hatch, hidden once the
  entry is solved; using it never advances the ladder but always counts in
  scoring (meter, scorebar, and no-hints tally).
- The grid stays light-cells/dark-letters in BOTH color schemes (feedback
  2026-07-26: a dark-on-dark grid was unreadable), BUT in dark mode the cells
  are a dimmed paper tone (`--cellbg: #c9c5bd`), never pure white — a white
  15x15 slab on a dark page is glare (feedback 2026-07-26). Grid colors live in
  `--cell*`/`--gridline`/`--blockfill` on `#grid`, with a dark-scheme override
  block; keep letter contrast at roughly 10:1 when re-tuning.
- Grid separator lines and blocked squares must never be near-identical darks.
  Lines are a quiet mid grey (`--gridline`), blocks are solid black
  (`--blockfill`) and bleed 1px over the gap so a run of blocks reads as one
  black mass (feedback 2026-07-26: grey blocks vs black lines were hard to tell
  apart and the lattice was noisy). Word-separator bars stay black so they
  stand out against the grey lines.
- The hint panel shows the selected entry's LIVE letter pattern under the clue
  (feedback 2026-07-26: "when looking at the clue can it show the missing and
  checking letters?"). One small box per cell — the typed letter or a blank —
  plus a muted "x of N letters in place · c checked, u unchecked" summary.
  Checked squares (crossed by another entry, so a second clue can confirm them)
  get a solid accent-underlined box; unchecked squares are dashed, because
  nothing will ever cross them. The strip re-renders on every `refreshAll()`,
  so it must never go stale while typing. The boxes are buttons: clicking one
  moves the cursor to that square (feedback 2026-07-26), so the strip steers as
  well as informs. See `patternHTML()` in `app.js`,
  `.pattern`/`.pat-box` in `style.css` (page-theme vars only — the strip is
  outside `#grid`, and dark mode must stay dim), and the pattern assertions in
  `tools/smoke_test.js`.
- Typing advances to the next square that still NEEDS a letter, skipping ones a
  crossing entry already filled in (feedback 2026-07-26 — every mainstream
  crossword app does this). If nothing ahead is empty it falls back to a plain
  one-square step, so overwriting a full entry still works. See `advanceToGap()`.
- On touch devices, a scroll gesture must never select a cell or clue — tap
  detection uses a movement threshold (feedback 2026-07-26).
- **A tap moves the page at most twice**, and that is a BUDGET, not a
  measurement. Every wiggle this app has had came from the same reasoning: the
  band moved, so the placement must be wrong, so place again. It is unfalsifiable
  on iOS, because our own smooth scroll pans the visual viewport and fires the
  same events a keyboard does — "scrolls down then up then down then up then
  down" (Paul, iPad, 2026-08-17, on a rule that let the late look re-arm itself,
  which walked `[1192, 1152, 1192, 1152, …]`). Nothing in a band measurement can
  say what moved it, so the cap does the job the measurement cannot: one
  placement on the best information available, one correction once the viewport
  goes quiet, and then the page belongs to the reader. Waiting longer is free;
  moving again is not. `tools/fake_dom.js` has `window.scrollPans`, which makes
  every scroll pan the stub viewport, so the loop is reproducible in the harness.
- **A row badge's colour names exactly one axis, and no two axes share a
  colour** (feedback 2026-08-06: "the colors for the pills conflate things").
  There are three axes on a puzzle row and they answer different questions:
  which crossword it is (`series`), what this site has for it (`full hints` /
  `answers only`), and how hard we judged it (`gentle`…`brutal`). `series` and
  `full hints` were both `--def-bg` green, so on the archive page an Independent
  puzzle looked annotated; and both borrowed the hint-rung palette, where green
  means *definition* and pink means *indicator* in the solving view the picker
  sits beside. Badges now have their own `--badge-*` variables — purple for
  which paper, blue for hinted, neutral for not, and difficulty stays outlined
  rather than filled because it is the only one of the three we made up. A new
  badge picks an existing axis's colour or brings its own; it never reuses
  another axis's.

## How Minute Cryptic writes a hint (the reference corpus)

Paul, 2026-08-01: *"our hints should be like theirs."* Minute Cryptic is one clue
a day with a progressive hint ladder — the same shape as our six rungs, and
better written. `node tools/fetch_minutecryptic.js` keeps a local copy of their
55 fully worked examples in `tools/data/minutecryptic/course.json`, refreshed by
the nightly job. It is GITIGNORED: their copyrighted teaching material, no
declared licence, kept to read and learn from. Never copy a sentence of it into
a puzzle file — write our own in the same manner.

Read the corpus before writing hints. What it actually shows, measured across
all 55:

- **Every single hint highlights a span of the clue — 156 of 156.** Not just the
  definition and the indicators: the *fodder* hint highlights the fodder too.
  This is the same rule as "every rung marks up its OWN words" above, carried
  further than we carry it: our `blocks` rung names `clueFragment` in prose but
  doesn't mark it in the clue. A hint that talks about words without pointing at
  them makes the solver do the search twice.
- **Two or three hints, never more** (46 clues have 3, 9 have 2). The ladder
  before the answer is short. Ours is longer because it also carries the type
  and the full walkthrough, but the *middle* of ours should stay this tight.
- **Their default order is indicators → fodder → definition** (41 of 55), not
  definition-first. They give you the machinery and make you find the definition
  yourself, because locating the definition is the skill. Double definitions are
  the exception: those go `definition 1` → `definition 2`.
- **~25 words a hint** (median), ~73 for the closing explanation. Short.
- **Written as an invitation, in the first person plural.** "Our anagram
  indicator is 'crazy'"; "we'll need a synonym for one, and just a single crucial
  letter from the other"; "Does it have a meaning that can correspond with
  'bolt'?" A hint asks the solver to do the next step — it does not perform the
  step for them. Compare our declarative register, which too often just states
  the finding.
- **A hint never leaks the answer.** The definition hint says "'produce' — that's
  the word we're trying to replace in our answer", naming the job of the word
  rather than what it resolves to. Only the closing explanation says the answer.
- **The closing explanation ends warmly** ("Nice one! Let's double down with
  another clue"). We don't have to copy the chirpiness, but note that it ends by
  looking forward, not by restating.

## Deploy rules

- Icons and the social card are GENERATED, never hand-edited. The 5x5 crossword
  motif lives in `tools/make_icons.py` (favicon.ico, favicon-16/32, icon-192/512,
  apple-touch-icon, and now `favicon.svg` too — the SVG used to be hand-kept "in
  sync" and drifted). The 1200x630 card is `tools/og_card.html` rendered by
  `tools/make_og.sh` (real type needs a browser, so headless Chrome draws it).
- **Every grid we draw must be a grid that could exist** (feedback 2026-08-06:
  "the social share icon isn't a valid cryptic grid"). Both the card and the
  icon were drawn by eye, symmetric and handsome, and both were impossible: their
  blocks left runs of two white squares, and no British cryptic has a two-letter
  entry. A solver spots that instantly, and the card is the one image people see
  before they have seen the site. So no grid is drawn and trusted: the rules live
  in `tools/grid_rules.py`, whose `check()` — 180-degree symmetry, no run of
  exactly two, every white square connected — the icon motif must pass before it
  is written, and which `mask()` demonstrates against a real published grid. A
  run of ONE is fine: that is an unchecked square inside the perpendicular light.
- **A card should show the work, not the wrapper** (feedback 2026-08-07: "can we
  make the image we use for social sharing show a good clue and the hints instead
  of the grid maybe?"). A grid is a picture of the thing people already believe
  they can't do; it says "crossword" and nothing else. The card is now one clue
  coming apart — definition and indicator marked in the app's own colours, the
  answer's letters underlined where they were hiding, three rungs of the real
  ladder, and the answer withheld as five empty boxes, so the reader gets the aha
  themselves. Hidden word on purpose: it is the one family whose mechanism is
  fully visible in a still image. Generated by `tools/make_og_card.py` from a
  published puzzle, and the underline is *computed* from the clue's letters — a
  card that quietly claimed the wrong span would be worse than a dull one.
- **Changing a file's bytes means changing its URL** (feedback 2026-08-06: "the
  image still isn't a valid cryptic" — a week after the impossible grid above was
  replaced with a real one). The new card was correct on disk and correct on the
  server; what people saw was Discord's unfurl, cached against `og.png`, a URL
  that had not moved. Browsers you can tell to hard-refresh; a chat app's link
  cache you cannot, so the only lever is a URL it has never seen. Every static
  file referenced by a page — `og.png` and the icons included, not just CSS and
  JS — carries `?v=<content hash>`: `asset()` in `tools/build_seo_pages.py` for
  generated pages, `tools/stamp_assets.py` for the hand-written homepage, and
  `stamp_assets.py --check` sweeps all 70 pages and fails the nightly run on a
  bare reference. Note what this does NOT fix: caches still holding the old URL.
  Re-share the link to force a refetch, and expect a day's lag.
- **Pushing is not deploying** (feedback 2026-08-16: "can you always hold off on
  telling me to reload until it is deployed"). GitHub Pages takes a minute or two
  to build, and "fixed and pushed — reload" is false for the whole of it: the
  person who reloads inside that window sees the old bug still there and
  reasonably concludes the fix did not work, so the next thing they report is a
  phantom. Nobody is told to reload until `python3 tools/wait_for_deploy.py`
  exits 0. It polls the live homepage for the local `?v=` stamps, which is the
  right check because the stamp is the thing a reload actually picks up — proof
  the new JavaScript is being *served*, not merely that a commit arrived. It is
  the last step of the pipeline, after the push, not a thing to remember.
- **A scheduled job never guesses a fact the API will tell it** ("fix the cron",
  2026-08-07). Two jobs spend inference here, and both were budgeting against
  numbers they had made up. `prereset_backfill.sh` deliberately runs with NO
  usage gate, which is only safe in the last hour before quota that cannot roll
  over evaporates — it identified that hour as "04:00 to 04:55" and was fired
  daily, so an ungated hour ran seven nights a week instead of one. The reset is
  a timestamp in `GET /api/oauth/usage`; the job now polls hourly and exits in a
  second unless `weekly_usage.py --resets-in` says the window really is closing.
  Meanwhile `daily_update.sh` checked the five-hour session window once, before
  spending any of it, when it necessarily reads near zero — so it approved three
  annotations and discovered the limit by crashing into it on the third. A
  budget is re-read between the things that spend it. Same rule as
  `series.py` being the only source of truth for what a series is: if something
  can be looked up, looking it up is not optional.
- **A gate that fails open must shout when it fails** (same day). The weekly
  usage check had read a keychain entry that a `/login` blanked on 2026-07-31,
  so it got HTTP 429 every night for a week and printed `WARNING: weekly usage
  unknown — annotating anyway` into `.update.log`. Failing open was the right
  call and the warning was accurate; it just went somewhere nobody looks, so a
  gate that had stopped existing kept being trusted. Anything that decides
  whether to spend money or quota routes its own failure through `alert()`.
  Correspondingly, alert on the OUTCOME, not on an exit code: a run that
  annotates two puzzles and then meets a rate limit has done its job, and the
  old code alerted "no puzzle got hints today" while two puzzles got hints.
- **A job that borrows a credential must survive that credential going stale**
  (2026-08-07, hours after the two rules above). `weekly_usage.py` reads the
  CLI's OAuth access token but nothing here refreshes it — only running `claude`
  does, as a side effect. The token lives about eight hours, so on a quiet
  afternoon every read returned HTTP 401, and the hourly poll would have gone
  blind at 3am on reset night, the single hour it exists for. Borrowing the
  credential is still right; assuming it is live is not. Cache the last good
  reading and say on stderr when you are using it — but only where staleness is
  harmless: `resets_at` is an absolute timestamp and stays true, a percentage
  goes off, so as a number it expires after six hours. As a floor it never does
  — see the next rule but one.
- **The same alert twice is the same silence** (same day). One lapsed token made
  an hourly job post four identical paragraphs to Discord, and a channel that
  cries wolf on the hour teaches its one reader to scroll past it — the silent
  failure again with the opposite mask. `alert()` now sends an identical message
  at most once per `ALERT_REPEAT_HOURS` (12). The log still records every one.
- **A spend gate fails closed, and a stale reading is still a floor** (2026-08-08).
  The gate could not reach the usage API, so it ran the annotator ungated at 82%
  of the week — while holding a ten-hour-old cached reading of 75% against a 50%
  limit. It had the answer and threw it away, because it was asking "what is the
  percentage" (which rots) instead of "am I over the line" (which doesn't):
  usage only rises inside a window, so any reading from the current window is a
  lower bound forever, and a floor above the limit is a decision. `gate()` returns
  `spend`/`skip`/`unknown`, never a bare number that an empty string can silently
  turn into "go". And `unknown` now skips — the old fail-open bet was that a
  stalled backlog is invisible while overspending isn't, which stopped being true
  the day skipping started raising an alert. Its four cases run offline as
  `--self-test` before any verdict is believed, because a broken gate says
  "spend" just as confidently as a working one.
- **A shared social card wastes the only view most pages get** (2026-08-08).
  Every puzzle page unfurled as the same picture of Quiptic 1,393, so a hundred
  different links previewed as somebody else's crossword. Each page now shows
  the best clue in its own puzzle, and "best" is a question about the PICTURE,
  not about the clue — these are published setters, soundness is a given, and
  what varies is whether the mechanism survives four seconds in a thumbnail. So
  `score()` ranks on visible mechanism (answer underlined where it hides >
  anagram fodder laid out > an indicator to point at), on length, and on whether
  the definition sits at one end. Two things are structural rather than
  reviewed: no card may print its answer — live, not theoretical, because the
  rungs are built from annotation prose that gives it away — and the family
  labels are diffed against app.js's FAMILIES on every build, so a card cannot
  describe a clue differently from the app that teaches it. A puzzle with no
  clue that qualifies keeps the site card; shipping a weak card is worse than
  shipping the generic one.
- **A word being shuffled cannot be the word that says to shuffle**
  (2026-08-08). Reviewing 30,079's card I called its indicator wrong — "School"
  looked odd and "to spin" looked like the obvious anagram indicator. It wasn't:
  `spin` is inside the fodder PAID TO SPIN, so its letters were already spoken
  for, and the annotation was right. The failure is text matching over structure
  — `spin`, `cooked`, `broken`, `wild` read as instructions wherever they sit, so
  eyes and bulk annotation alike will nominate one that is really material. Now
  `check_indicator_outside_fodder` decides it, because adjacency cannot: an
  indicator inside its fodder has no gap to measure and scores as perfectly
  placed. Zero violations across all 116 annotations carrying a fodder — a guard
  against a future one. The card was complicit too: it painted the indicator pink
  and never mentioned it, so rung 3 now reads "<ind> says to shuffle <fodder>"
  rather than "Shuffle <fodder>". A mark the prose never explains is a claim the
  reader has to take on trust, and this one didn't survive being taken on trust.
- **Explaining prose may not borrow another device's signal words**
  (2026-08-08). Rung 3 of every hidden-word card read "<ind> says so out loud"
  from the day the cards shipped. "Out loud" was meant as *announces itself*; in
  a cryptic it means one thing only, that the answer is a soundalike. So the card
  said Extraction on rung 1 and pointed at Sound on rung 3, about one clue, to a
  reader who is there precisely because they can't yet tell those apart — and it
  read so oddly that Paul took the rung for part of the clue. Ordinary writing
  advice doesn't catch this: the sentence is fine English and only wrong because
  the vocabulary is already spoken for. `check_prose_stays_in_family` now fails
  the build on it, scanning only the words the card contributes — never the marks
  and the fodder, which quote the clue, and an Extraction clue may perfectly well
  own an indicator that reads like a homophone. The list is short on purpose:
  only wording that can mean nothing but its own mechanism, so "says to shuffle"
  survives and "out loud" doesn't. It raises RuntimeError rather than SystemExit
  because `pick()` reads SystemExit as "this clue can't draw" and would quietly
  ship the bug on a different clue. Applies past the cards: a walkthrough that
  says "sounds like" about a charade is the same error with a wider audience.
- **Quote the explanation that already exists** (2026-08-08). The reworded rung
  3 was still the card talking about the family: "<ind> says it is hidden here",
  the same line on all sixteen hidden-word cards. The annotations had the better
  sentence all along, because a walkthrough almost always opens by glossing the
  indicator itself — "'Some' tells you to take only part of what follows", "'Put
  in' flags a hidden word". `indicator_gloss` lifts that opening clause when it
  leads with the indicator, fits a thumbnail line, and doesn't give the answer
  away; 8 of 16 qualify today, and the other 8 keep the generic line, because a
  card must never be blocked by prose. Writing a second explanation beside one
  that already exists is how the two drift apart.
- **A consistent parse is not a correct one** (2026-08-08). Benchmarking Haiku
  against Fable on 30073, Haiku returned `29/29 annotated — OK` in six and a half
  minutes and the validator had nothing to say. Seventeen of its twenty-seven
  non-exempt clues contained no wordplay at all: HORSE was `definition: "Hard
  rock"` with a block `"Hard rock" > HORSE`, TRIGGER was defined as "Bouncer"
  when "Bouncer" is the wordplay (TIGGER round R) and "cause" is the definition.
  Every check passed because every check tested CONSISTENCY — letters
  concatenate, substrings are verbatim — and a model that cannot solve the clue
  can still be perfectly consistent about a parse it invented. So consistency was
  never the bar. `check_definition_not_fodder` adds the missing one: the two
  halves of a cryptic sit side by side, and a block yielding letters out of words
  the definition already claimed is the annotation eating its own tail. It warns
  per clue, because a setter does occasionally reuse the word on purpose ("Nobody
  drunk now nobody drinks!"), and ERRORS past three in one puzzle, because that
  is no longer a device. Calibrated on all 671 annotated clues: 4 warnings in 4
  different puzzles, 0 errors; the Haiku run scores 17 in one. The general rule:
  when you add a model to a pipeline, the checks that passed for the old one are
  now a measurement of the new one, and they only measure what they test. Three
  more came out of the same run, all of them comparisons the annotation already
  contained and nothing was making: the blocks' letters against the answer
  (`check_blocks_account_for_answer` — Haiku's TRIGGER had immaculate `pieces`
  and blocks reading T + R + IG), the blocks against `pieces`
  (`check_blocks_decompose` — "Two types of earth" > SODDEN names a charade and
  then doesn't do it), and a note on every block that claims letters
  (`check_blocks_carry_notes`). Two of the three flag this repo's own work, five
  clues and one clue respectively, which is the point: a check worth adding
  usually finds something you did yourself.
  Worth knowing what this benchmark did NOT test. The published solution is in
  every puzzle file before annotation starts, so the model is never solving the
  crossword — it is explaining a clue whose answer it has been handed, and Haiku
  failed at that easier job. Nothing here says anything about solving.
  The Sonnet leg of the same benchmark clears every mechanical bar Haiku fails:
  2034s, zero flags on all four of the new checks (0/26 fodder, 0/19 accounting,
  0/14 decomposition, 0/53 missing notes), 29 parses correct on a hand read,
  committed as 30073. On that evidence alone Sonnet looks like a drop-in for
  Fable. It is not, and the reason is a lesson about benchmarks rather than about
  models: **30073 was in the backlog, so Fable had never annotated it, so there
  was nothing to compare against.** A clean validator run is an absence of
  detected faults, and the whole point of the entry above is that absence of
  detected faults is not quality. Only another annotator's work on the SAME clues
  can say whether a parse was the best available one.
  Re-run properly on 30078, which Fable had already done (2026-08-08, same
  prompt, same flags, Fable's annotation stripped to null in a worktree), the
  answer inverts:

  |        | time  | steps | input  | output | agrees w/ Fable   |
  |--------|-------|-------|--------|--------|-------------------|
  | Fable  | 990s  | 54    | 5.73M  | 480k   | —                 |
  | Sonnet | 1705s | 92    | 18.2M  | 300k   | 21/25 type, 20/25 def |

  Sonnet is 1.7x slower, costs 3.2x the input tokens, writes a third less, and is
  worse. The four disagreements are the whole story. Two are cosmetic (a trailing
  `?` inside the definition span). One is a real Sonnet win: 17A STREWTH, split as
  `’S` + TRUTH rather than lumped as one homophone. One is a real Sonnet loss: 5D
  COVERLET typed `anagram` with blocks `lever` > LEVER and `bed` > COT, which
  performs no anagram and hides the container — Fable's `COT` around `VERLE` is
  simply correct. And **two clues Sonnet could not solve at all**, 9A OPERA STAR
  and 19D CHUKKAS, it filed as `cryptic definition` with the entire clue as the
  definition — the same surrender Haiku made, in a model honest enough to label
  it. Fable had solved both, and 19D (`CHAS` around `UK` + `K`) is the best clue
  in the puzzle.
  Two things follow. First, `MAX_CRYPTIC_DEFINITIONS = 2` earns its keep as a
  model-quality tripwire and not just a style rule: Sonnet landed on exactly 2 in
  both benchmark puzzles, i.e. it passed by using its entire surrender budget,
  and a third punt would have ERRORed the run. When a model is at the cap, read
  the capped clues — that is where the giving-up is. Second, the failure mode
  that matters is not fabrication (Haiku) but *quiet under-solving*: a correct,
  well-formed, validator-clean annotation of the easy clues plus a shrug at the
  hard ones. No mechanical check can catch that, because a cryptic definition
  claims no letters and so cannot contradict anything. Only a diff against a
  better annotator finds it.
  Opus 5, run third on the same 30078 clues with the same prompt and flags,
  changes the conclusion. It is the only leg that reaches Fable's standard:

  |          | time  | steps | input | output | vs Fable            | cost   |
  |----------|-------|-------|-------|--------|---------------------|--------|
  | Fable 5  | 990s  | 54    | 5.73M | 480k   | —                   | $35.91 |
  | Opus 5   | 1038s | 45    | 7.30M | 215k   | 23/25 type, 22/25 def | $12.06 |
  | Sonnet 5 | 1705s | 92    | 18.2M | 300k   | 21/25 type, 20/25 def | $7.56  |

  Opus used **zero** cryptic definitions and solved both clues Sonnet punted —
  9A OPERA STAR as `O + PE(RASTA)R` and 19D CHUKKAS as `CHAS` round `UK + K`.
  All three definition differences are a trailing `?` inside or outside the
  span, which is cosmetic. Of the two type differences, Opus is right once (17A
  STREWTH as `charade + homophone`, since `’S` + TRUTH is a charade before it is
  a homophone — the same win Sonnet found) and Fable is right once (19D, where
  Opus dropped the `+ charade` that `UK + K` plainly is). That is parity, in the
  same wall time, at a third of the cost, and the saving is almost entirely
  output tokens: Fable writes 2.2x as many at 2x the rate, which is $24 of a $36
  puzzle. What the cheap legs got wrong was never cheapness, it was the model
  being unable to solve the two hardest clues, and Opus can.
  **Pinned to Opus on 2026-08-09** on this one puzzle. I argued for two or three
  more diffs first, on the grounds that a single clean run is not evidence — the
  exact lesson this entry exists to record. Paul overruled it and took the
  saving. So the pin rests on one puzzle: read the first few nightly runs, and
  if a run sits at `MAX_CRYPTIC_DEFINITIONS`, read the capped clues.

  A later read of the *prose* — the half a learner actually sees — splits the
  verdict the structural diff had called parity. Fable writes better: 18 words
  per walkthrough against Opus's 30, and the funnier line nearly every time
  (`Bacchus loses his CH — denied church — and what remains counts beads, not
  blessings`). Opus teaches better, which is what the prompt asks for. The rule
  above says a walkthrough carries what the blocks *cannot* show and never
  re-narrates fragment → letters; **Fable breaks it in 8 of 25 clues, Opus in
  3**. Fable on 9A is `RASTA bursts through the middle of PER, with O in front`,
  which is precisely what the app already renders underneath; Opus writes `the
  step that unlocks it is reading 'prayer' as a person rather than a thing
  said`. Opus also banks transferable convention (`EG for 'say' is a workhorse
  abbreviation`, `6-4 means hyphenated`) where Fable banks none. Opus's own vice
  is boilerplate — `so 'X' names it by what it does` recurs — and a definitionFit
  averaging 24 words against a 30-word cap, so it writes with no headroom.

  The number that reframes the cost table: Fable spent 2.2x the output tokens
  and produced 40% *less* finished prose. That $24 was iteration, not product.
- **Two renderings of one link must share one joiner** (Search Console,
  2026-08-07). Breadcrumb crumbs were `("Puzzles", "/puzzles/")`, and
  `breadcrumb_ld()` joined them to BASE while `masthead()` emitted them raw — so
  the structured data was right and the link a reader or a crawler could actually
  click was `paultarjan.com/puzzles/`, a 404 on all 71 puzzle pages, for as long
  as those pages have existed. Nothing shows in a browser: the page renders, the
  crumb looks like a crumb. The site is served from a subpath, so a root-relative
  href is never correct here; `site_url()` is the only joiner and
  `assert_no_root_relative()` fails the build on any `href="/…"` it did not make.
- **A URL that is not the canonical must say which page is** (same day). `?p=30054`
  shipped declaring the homepage canonical, so every share of a specific puzzle
  credited the front page and Search Console filed the puzzle as "alternate page
  with proper canonical tag". The static write-up at `/puzzles/30054/` is the page
  that deserves it. The app now rewrites the canonical at boot when `?p=` names a
  puzzle that has one — and only then, because an unannotated puzzle has no static
  page and the homepage is the honest answer.
- **A puzzle's id is its series and its number** (2026-08-19): `cryptic-30089`,
  `everyman-4165`. Every paper numbers from its own 1, so the number alone names a
  puzzle only by luck of which ranges happen to be far apart — and the luck runs
  out. `puzzles/<n>.js` WAS the whole namespace, so the second paper to reach a
  number would have shared the first one's file and merged one paper's annotations
  into the other's grid, silently. Spelled in exactly one place
  (`series.puzzle_id`), found in exactly one place (`fetch_puzzle.puzzle_files`),
  resolved in exactly one place (`fetch_puzzle.resolve_puzzle`, which takes a bare
  number too and refuses rather than guesses when one is ambiguous).
  **Numbers stay numbers everywhere a person reads one** — titles, picker rows,
  card art, prose — because "No 30,089" is what the paper calls it. The id is a
  key, not a name.
  Anything that has to keep working under an old id migrates rather than breaking:
  saved progress renames itself once on boot, `?p=30080` still opens the puzzle it
  named, incoming sync envelopes are mapped on the way in, and every retired
  `/puzzles/<n>/` URL keeps a page that says where its puzzle went. And the same
  spelling trick that hid a collision can hide a rule: `is_authored` read the first
  character of the id until every id began with a letter, at which point every
  Guardian puzzle was silently held to the authoring rules. It is a `series` field
  now. **Decide off a field, never off how an id is spelled.**
- **The address bar always names the puzzle on the screen** (2026-08-19). A link is
  copied out of it, so opening a puzzle rewrites it to `?p=<n>` and moves the
  canonical with it. Left alone the URL said whatever the page booted on: the bare
  site root, which drops the reader on last night's puzzle, or a stale `?p=` from
  the link they followed, which is worse because it looks deliberate.
  `replaceState`, never push — switching puzzles is choosing what to look at, not
  navigating, and a back button that walked the picker backwards would make leaving
  the site take one press per puzzle browsed. **But only when the reader chose.**
  Booting on the remembered puzzle is nobody's choice, and a bare
  `/cryptic-teacher/` that rewrote itself would leave the homepage declaring a
  puzzle as its canonical — the same de-indexing bug as above, pointed the other
  way. That is why `openPuzzle(id, chosen)` takes the flag rather than inferring it.
- **Copy about the whole site names every paper in it, or none of them**
  (feedback 2026-08-06: the archive page still said "Guardian cryptic crosswords,
  explained" over a list that included the Independent and Everyman). Naming one
  paper on a puzzle page is right — that page IS that paper's puzzle. Doing it in
  a site title, meta description or heading is a claim about the whole
  collection, and it went wrong the day a second series landed. The archive
  page's title and description are now DERIVED from the publishers actually
  present (`papers()` in `tools/build_seo_pages.py`), and the hand-written
  homepage `<head>` is checked against the same list by
  `assert_names_all_papers()`, which fails the build rather than shipping a
  half-true sentence. Prefer "broadsheet" where a stable phrase is wanted.
- The canonical URL is `https://paultarjan.com/cryptic-teacher/`. It appears in
  `<link rel=canonical>`, `og:url`, `og:image`, the JSON-LD, `sitemap.xml`,
  `robots.txt` and `tools/og_card.html` — if it ever moves, all seven change
  together. Note that crawlers only honour robots.txt at the DOMAIN root, so the
  sitemap must also be listed in the paultarjan.com repo's robots.txt.
- The Guardian publishes SIX cryptics a week, Monday to Saturday — there is no
  Sunday cryptic. Saturday's is the *Prize* crossword: same number sequence, but
  it lives at `/crosswords/prize/<n>`, not `/crosswords/cryptic/<n>`. Watching
  only the cryptic path loses one puzzle in six (feedback 2026-07-27: 30044,
  30050, 30056, 30062, 30068 were all silently missing). `SERIES_URLS` and
  `PUZZLE_URLS` in `tools/fetch_puzzle.py` must always list both. Prize solutions
  are withheld for about a week, so a fresh prize puzzle lands with
  `hasSolutions: false` and is not annotatable yet — `--refresh-unsolved` re-fetches
  those each day and the daily job runs it before annotating.
- The daily job annotates `ANNOTATE_MAX` puzzles per run (default 3), not one:
  at six new puzzles a week, one a day never drains a backlog. It stops early the
  first time a `claude -p` run fails, since that is nearly always a session limit
  and the remaining attempts would fail too.
- Every asset URL carries a content hash (`style.css?v=…`, puzzle files use the
  `v` field in `puzzles/index.json`). GitHub Pages sends `max-age=14400`, so
  without this a phone shows four-hour-old CSS after a reload (feedback
  2026-07-26). After ANY edit to index.html's assets run
  `python3 tools/stamp_assets.py`; the smoke test fails on stale stamps and
  `tools/daily_update.sh` re-stamps automatically.
