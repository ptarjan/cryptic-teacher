# Cryptic Teacher app rules

This file covers how the app presents annotations and how the site is built and
deployed. The rules for *writing* annotations are in `STYLE.md`, which the
nightly annotator reads whole. Nothing here can be acted on by a run that holds
a single puzzle file, which is why the two files are separate.

Terms used below:

- **rung**: one step of a clue's hint ladder (indicators, definition, type,
  blocks, walkthrough).
- **family**: the coarse clue category the type rung names (for example
  *Rearrangement*). **type**: the precise annotation `type` (for example
  `charade + alternate letters`).
- **the smoke test**: `tools/smoke_test.js`, which runs the real `app.js`
  against a fake DOM (`tools/fake_dom.js`) and every puzzle file.
- **the validator**: `tools/validate_annotations.py`.

## Hint ladder

### Structure

- **Rungs are built per clue.** A rung exists only if it carries new
  information. No indicators means no indicator rung. No rung may restate an
  earlier one. See `ladderSteps()` in `app.js`. The ladder length varies by
  clue and shows as "x/N" in the meter.
- **The order has one source: the key order of `LABELS` in `app.js`.**
  `RUNG_ORDER` is `Object.keys(LABELS)`. `tools/build_readme.py` numbers the
  README's rung list from the same map. The smoke test parses it out of
  `app.js` and asserts every clue numbers its rungs in that order. Never write
  the order down anywhere else. The current order is indicators, definition,
  type, blocks, walkthrough:
  - the indicator rung is the cheapest (it names the mechanism and leaves the
    definition to find);
  - naming the definition hands over half the clue;
  - the family is usually already given away once you have both (`spentBy`).
- **The ladder is tiered** (`RUNG_TIER` in `app.js`). Within a tier you choose
  freely; across tiers you cannot.
  - Tier 0 is what the clue asks you to spot: indicators, definition, type. Take
    them in any order. Finding the definition is most of the skill, so wanting
    the indicators must not cost you it.
  - Tier 1 is the building blocks. They unlock only once every tier-0 rung this
    clue has is up.
  - Tier 2 is the walkthrough. It unlocks after the blocks.
  - Later rungs restate earlier ones on the way to the answer, so letting
    someone skip straight to the walkthrough would not be a ladder.
- **Locked rungs are shown disabled, not hidden**, so the solver sees what is
  coming. The recommended next rung leads and is labelled "Show hint N". The
  rest of its tier are quiet ghost buttons. A rung keeps its ladder number
  whichever order it is taken in, so gaps in the numbering show what was
  skipped.
- **Revealed rungs are a set, not a count.** `hintsShown` maps entryKey to rung
  keys. An integer can only say "the first N", which would force every lower
  rung open with any higher one. Do not reintroduce a scalar.
- **A rung a clue does not have must never gate one it does.** Many clues have
  no indicator rung and no blocks rung. Availability is computed from this
  clue's steps, not a fixed list.
- **Rung names do not vary by clue.** A rung's label is a function of its key
  alone (`LABELS` in `app.js`). The names of unbought rungs are on screen the
  whole time, so a name that varied by type would be a free hint. On a
  semi-&lit hidden word, a button reading "How can the whole clue be the
  definition?" gives away the whole trick. The same goes for "Where does the
  clue split?", "What is the clue really describing?", "What each half means",
  and a singular/plural indicator label, which reveals the count. A rung asks
  its question; the answer is what you pay for. The smoke test fails if any
  rung is named more than one way anywhere in the corpus.

### What each rung says

- **Never write a count into prose next to the list it counts.** Number words
  come from `.length`, always.
- **The indicator rung says what each indicator does, and `indicatorNotes` says
  why that word means it.** A general sentence ("it tells you to shuffle the
  letters") is the same on every anagram, so it feels empty to pay for. Write
  one sentence per indicator, keyed by the exact indicator string, naming the
  sense of the word that carries the instruction. Example: "'stable? No' means
  unstable, and unstable will not stay in the order it is given."
  - The notes render before the answer, so the validator checks them for answer
    leaks (`EARLY_RUNG_FIELDS` in `tools/validate_annotations.py`).
  - The validator requires `indicatorNotes` on every puzzle except those
    grandfathered in `tools/annotation_backlog.json`.
- **No filler around real content.** When every indicator has a note, the notes
  are the whole indicator rung. No "this clue does two things", no list of
  operations, no "which word calls for which is the step to work out here".
  Operations come from the clue *type*, which is a different rung. The generic
  sentence survives only for puzzles that predate `indicatorNotes`. The smoke
  test enforces this structurally, not by banned phrases: remove the notes from
  a fully-noted rung, and what is left must be empty.
- **Do not refer to the surface picture with a definite noun phrase you never
  introduced** (for example "the impromptu band" in a walkthrough that never
  mentioned a band). Name the picture in the clue's own words. See
  `tools/annotate_prompt.md`.
- **The walkthrough ends by saying why the answer means the definition.** This
  is `definitionFit`. It is required on every annotation and rendered just
  before the answer. Name the relation: plain synonym, definition by example, a
  sense mostly found in crosswords, a technical or regional use, a whole-phrase
  idiom. Restating the definition with the answer substituted in ("an army ant
  is a crawler") is a validator error. `check_definition_fit` catches it: the
  fit has no content word that is not already in the definition or the answer.
  `definitionNote` is different: it justifies a definition that disagrees with
  the answer grammatically. Every clue has a fit; only a few need a note.
- **The type rung names the family, never the precise type.** Saying
  `charade + alternate letters` hands over the whole mechanism. Families, in
  match order (first match wins, so the dominant mechanism of a compound type
  decides):
  1. **Definitions only**: double or cryptic definition
  2. **&lit**
  3. **Rearrangement**: anagram
  4. **Sound**: homophone, spoonerism
  5. **Charade**: the most common build; it reads nothing like a container or
     reversal, so it keeps its own family
  6. **Alteration**: container, reversal, deletion
  7. **Extraction**: hidden word and all the letter-selection parts

  Every part in `TYPE_PARTS` (in `tools/validate_annotations.py`) must be
  claimed by exactly one family in `FAMILIES` in `app.js`. Adding a type part
  means assigning it a family in the same commit. The smoke test checks this.
- **Every clue shows its exact type**, styled `.mechanism`, on the
  building-blocks rung, or on the walkthrough if there is no blocks rung. The
  smoke test checks every clue. This includes double and cryptic definitions:
  the *Definitions only* blurb covers both, so without the type name the solver
  cannot tell which one this clue is. Those two get the type name but not its
  `TYPE_BLURBS` sentence, because that sentence would restate the definition
  rung. General rule: drop a rung only because it is redundant. Never drop it
  because you assume another rung covered it; read what that rung actually
  says.
- **A double definition has no building blocks of its own.** Its halves are its
  two definitions, which the definition rung already asks for. A block that is
  one of the definitions and carries only a note renders that note on the
  definition rung, beside the split (`senseBlock` in `app.js`). Anything the
  split does not name is still a block: a third definition, a wordplay half, a
  sounded form.
- **A question with one answer is not asked.** If a piece of the blocks rung is
  made of all the words the clue has left (after the definition, indicators,
  link words and earlier pieces are lit), it is handed over together with the
  piece before it. This removes the fodder question from a pure anagram whose
  fodder is the rest of the clue, and the last question from a charade whose
  every word is claimed. It does not apply to the definition rung: nothing is
  settled yet there, and spotting that the whole clue defines is the skill
  being tested.
- **Never offer information that is useless given what the solver already
  knows.** Once the walkthrough names the answer, the final option is "Fill in
  answer", never letter reveals.

### Highlighting

- **Highlight exactly what has been revealed, and nothing that has not.** Every
  rung marks up its own words in the clue, independently of other rungs, and
  the legend names exactly the marks drawn. `clueHTML` must not tie one rung's
  highlighting to another rung. Link words go with the definition rung, because
  they show where the definition ends; that pairing is deliberate. The smoke
  test takes the indicator rung alone and asserts the indicator is marked and
  the definition is not. Check this whenever a rung is added.
- **A bought hint never leaves the screen.** Placing a highlight is a placement,
  not a text search. `indexOf` would match the indicator "in" inside
  "Conclud(in)g". The rules:
  - Each fragment takes the best occurrence still free, preferring whole words.
    An edge that is itself punctuation may touch a letter ("’s gone out of" in
    "Pound’s gone out of").
  - No mark is ever dropped.
  - Where two marks really overlap, the *shorter* one wins the overlap, so both
    stay visible.
  - The smoke test buys every rung on every annotated clue and reads the marks
    back from the rendered HTML.

### Hints read off a blog

- **A clue we have not annotated gets the rungs a blog's write-up can state,
  in our words, and never the blog's prose.** `tools/blog_facts.py` reads the
  timesforthetimes, fifteensquared and bigdave44 caches and keeps three facts
  per clue: the definition the blogger underlined (only as an exact run of
  whole words of our clue), the clue type where the write-up names it
  unambiguously, and indicators where the blog's own key marks them. Anything
  hedged ("almost a DD", "cd/dd"), anything that cuts into a word, and any
  multi-span underline that is not a double definition is dropped.
- **Where it lives.** `tools/data/blog_facts/<series>.json`, a sidecar, because a
  re-fetch rewrites the puzzle file and these facts come from somewhere else.
  `fetch_puzzle.write_shim` merges them into the puzzle's shim for entries with
  no annotation, and drops any fact whose words are no longer in the clue. The
  index carries nothing, so `index.js` does not grow.
- **Our annotation always wins.** `annOf` falls back to `blogAnn`, which shapes
  the facts as a partial annotation, so highlighting, questions and scoring
  read it like ours. A blog ladder has only the rungs it has facts for: no
  blocks, no walkthrough. Its indicator rung does not pair words with jobs,
  because the blog does not say which does what.
- **It says whose marks they are.** The title reads "hints via <blog>" in place
  of "answers only", the meter badges the clue, and the escape row links to the
  post ("Full explanation on <blog> →") on every clue we have not annotated.
- **The nightly refreshes it** (`tools/daily_update.sh`, step 1d) with
  `--if-changed`, which skips the ~5-minute parse when the digest in
  `tools/data/blog_facts/inputs.sha256` still matches the cached posts, the
  clues and the parser. By hand, `python3 tools/blog_facts.py --measure`
  rewrites the sidecar and prints coverage per blog and series.
- **The validator compares our definition with the blog's** when a run
  annotates (`check_definition_against_blog`), not in the corpus sweep: where
  the two share no word, the blogger's underline is the slip about three times
  in four, so it is a second opinion, not a verdict.

## Solving screen

- **Every check says what it found.** A check always writes a sentence into
  `#check-result` (wrong letters marked, all correct so far, or nothing typed
  yet) and pulses the squares it examined, so its scope is visible. No control
  may respond to a click with silence; if there is nothing to report, say so.
  See `checkCells()` and `announceCheck()` in `app.js`, and the check
  assertions in the smoke test.
- **"Reveal one letter"** is available at any time and hidden once the entry is
  solved. It never advances the ladder but always counts in scoring (the meter,
  the scorebar and the no-hints tally).
- **Live letter pattern.** The hint panel shows the selected entry's letters
  under the clue: one small box per cell (the typed letter or a blank), plus a
  muted "x of N letters in place · c checked, u unchecked" summary.
  - Checked squares (crossed by another entry) get a solid accent-underlined
    box. Unchecked squares are dashed.
  - The strip re-renders on every `refreshAll()`, so it never goes stale while
    typing.
  - The boxes are buttons: clicking one moves the cursor to that square.
  - See `patternHTML()` in `app.js` and `.pattern`/`.pat-box` in `style.css`.
    The strip is outside `#grid`, so it uses page-theme variables only, and
    must stay dim in dark mode.
- **Typing skips filled squares.** The cursor advances to the next square that
  still needs a letter, skipping ones a crossing entry already filled. If
  nothing ahead is empty, it steps one square, so overwriting a full entry
  still works. See `advanceToGap()`.
- **A scroll gesture never selects a cell or clue** on touch devices. Tap
  detection uses a movement threshold.
- **A tap moves the page at most twice.** This is a budget, not a measurement:
  one placement using the best information available, one correction once the
  viewport is quiet, then the page belongs to the reader. On iOS our own smooth
  scroll fires the same viewport events as the keyboard, so measurements cannot
  tell what moved the page, and re-placing on every movement loops. Waiting
  longer is free; moving again is not. `window.scrollPans` in
  `tools/fake_dom.js` makes every scroll pan the stub viewport, so the loop can
  be reproduced in the harness.
- **A tap leaves the soft keyboard as it found it, unless the tap is going to
  type.** On iOS the keyboard appearing or disappearing reflows the page, which
  looks like the hint flashing open and shut.
  - Controls that move the cursor (the grid, the letter strip) raise the
    keyboard.
  - Controls that only reveal text (hint buttons, reveal letter) keep whatever
    state they found. "Found" is read at mousedown, before the default focus
    transfer, and is two questions: `document.activeElement === $("kbd")` **and**
    `keyboardUp()`. On an iPad the chevron hides the keys but leaves the input
    focused. Re-focusing a focused input inside a touch gesture brings the
    keyboard back, and the keyboard arriving triggers extra scrolling.
  - Losing focus costs no typing. The document-level `keydown` handler feeds
    `onKey` whatever a hardware keyboard sends, focused or not. `#kbd` only
    takes input from a soft keyboard.
  - The smoke test asserts all three states. `activeElement` looks the same
    before and after a re-focus, so `tools/fake_dom.js` counts `focus()` calls
    and the test asserts zero.
- **Clue line spacing and tap-target size are one number.** Every clue word is
  an inline-block chip in every state (see `pickableClueHTML`), and an
  inline-block's margin box sets the minimum line height. A line-height smaller
  than the chip is silently ignored. So a bigger chip adds white space to the
  roughly 75% of clues that wrap on a 390px phone, in every state, including
  plain reading. `--gw-box` and `--gw-line` in `style.css` are declared as one
  sum, and the smoke test checks that arithmetic against `.gw`'s own box. To
  grow the target, grow the sum, knowing you are paying in line spacing. Never
  give `.gw` its own box on some devices.
- **Grid colours.** The grid stays light cells with dark letters in both colour
  schemes. In dark mode the cells are a dimmed paper tone
  (`--cellbg: #c9c5bd`), never pure white. Grid colours live in the `--cell*`,
  `--gridline` and `--blockfill` variables on `#grid`, with a dark-scheme
  override block. Keep letter contrast around 10:1 when re-tuning.
- **Grid lines and blocked squares must never be near-identical darks.** Lines
  are a quiet mid grey (`--gridline`). Blocks are solid black (`--blockfill`)
  and bleed 1px over the gap, so a run of blocks reads as one black mass.
  Word-separator bars stay black so they stand out against the grey lines.

## Picker and badges

- **The puzzle picker lists only puzzles with `annotated: true`**, plus the one
  currently open and any with saved progress. Un-annotated puzzles are the
  majority and grow faster than annotated ones, and a row that cannot teach
  anything is noise.
- **Hidden must never mean unreachable.**
  - A search query searches every puzzle, annotated or not.
  - The archive page lists every puzzle, and the picker footer links to it.
  - `?p=<id>` opens any puzzle.
  - The search box is focused when the picker opens, and Enter opens the top
    row, so typing a number and opening it needs no mouse.
  - Do not "simplify" this by filtering only the rendered rows. That would make
    un-annotated puzzles unreachable. The smoke test asserts the search path.
- **Papers and bands are menus, not words in the box.** Two native selects sit
  under the search. The paper menu groups series by their `group` in
  `tools/series.py` (the publisher unless set; the Sunday Times says "Times",
  Everyman "Guardian"), read from `groups` in `puzzles/index.json`. A group
  with two or more series gets an "All" option, and the single-series papers
  share one "Other papers" group. An option's value is the series keys it
  covers, so the filter matches keys and never a paper's name: "times" is
  inside "times quick" and "sunday times". Adding a series needs nothing in
  the picker. Only `SERIES_BADGE` needs its label.
- **Badge the exception, never the norm.** There is no "full hints" badge
  anywhere in the app, neither on picker rows nor on the puzzle title. Every
  listed puzzle is annotated, so that badge would say nothing. The
  `answers only` badge stays, because it appears exactly when a puzzle is the
  odd one out. The generated archive page (`tools/build_seo_pages.py`) does
  badge both states, correctly, because it lists every puzzle. In general: a
  label that every item carries is decoration, not information.
- **Each badge colour names exactly one axis, and no two axes share a colour.**
  A puzzle row has three axes:
  - which crossword it is (`series`): purple;
  - what the site has for it (`full hints` / `answers only`): blue for hinted,
    neutral for not;
  - how hard we judged it (`gentle`…`brutal`): outlined rather than filled,
    because it is the only one of the three we made up.

  Badges use their own `--badge-*` variables. They never borrow the hint-rung
  palette, where green means *definition* and pink means *indicator*. A new
  badge uses an existing axis's colour or brings its own; it never reuses
  another axis's.

## How Minute Cryptic writes a hint (the reference corpus)

Minute Cryptic publishes one clue a day with a progressive hint ladder. It has
the same shape as ours and is better written, so our hints should be written
like theirs. `node tools/fetch_minutecryptic.js` keeps a local copy of their 55
fully worked examples in `tools/data/minutecryptic/course.json`, refreshed by
the nightly job.

**That directory is gitignored.** It is their copyrighted teaching material,
with no declared licence, kept only to read and learn from. Never copy a
sentence of it into a puzzle file. Write our own in the same manner.

Read the corpus before writing hints. Measured across all 55
(`tools/compare_mc.py` re-derives these numbers):

- **Every hint highlights a span of the clue: 156 of 156.** That includes the
  fodder hint, not just the definition and indicators. Our `blocks` rung names
  `clueFragment` in prose but does not mark it in the clue. A hint that talks
  about words without pointing at them makes the solver search twice.
- **Two or three hints, never more.** 46 clues have 3, 9 have 2. Our ladder is
  longer because it also carries the type and the full walkthrough, but the
  middle of ours should stay this tight.
- **Their default order is indicators, then fodder, then definition** (41 of
  55). They give you the machinery and make you find the definition yourself,
  because locating the definition is the skill. Double definitions are the
  exception: `definition 1`, then `definition 2`.
- **About 25 words per hint** (median), and about 73 for the closing
  explanation.
- **Written as an invitation, in the first person plural.** "Our anagram
  indicator is 'crazy'"; "we'll need a synonym for one, and just a single
  crucial letter from the other"; "Does it have a meaning that can correspond
  with 'bolt'?" A hint asks the solver to do the next step. It does not do the
  step for them. Our register is too often a flat statement of the finding.
- **A hint never leaks the answer.** The definition hint says "'produce' —
  that's the word we're trying to replace in our answer": it names the job of
  the word, not what it resolves to. Only the closing explanation gives the
  answer.
- **The closing explanation ends warmly** ("Nice one! Let's double down with
  another clue"). We need not copy the chirpiness, but note that it ends by
  looking forward, not by restating.

## Annotation checks and the annotator model

### Consistency is not correctness

The validator's older checks test *consistency*: letters concatenate,
substrings appear verbatim. A model that cannot solve a clue can still be
perfectly consistent about a parse it invented. So these checks compare parts
of the annotation against each other. All are in
`tools/validate_annotations.py`:

- `check_definition_not_fodder`: a block may not take its letters from words
  the definition already claimed. It warns per clue, because setters sometimes
  reuse a word on purpose ("Nobody drunk now nobody drinks!"). It errors past
  three in one puzzle.
- `check_blocks_account_for_answer`: the blocks' letters must match the answer.
- `check_blocks_decompose`: the blocks must match `pieces`.
- `check_blocks_carry_notes`: every block that claims letters has a note.
- `check_indicator_outside_fodder`: an indicator cannot sit inside its own
  fodder. A word being shuffled cannot also be the word that says to shuffle.
  Words like `spin`, `cooked`, `broken` and `wild` look like instructions
  wherever they sit, so this is decided by structure, not by eye.
  Adjacency-based scoring cannot catch it, because an indicator inside its
  fodder has no gap to measure.
- `MAX_CRYPTIC_DEFINITIONS = 2`: at most two clues per puzzle may be typed
  `cryptic definition`. This is also a model-quality tripwire. A cryptic
  definition claims no letters, so it contradicts nothing, and a model that
  cannot solve a clue tends to file it as one. **When a run sits at the cap,
  read the capped clues.** That is where the giving up is.

When you add a model to the pipeline, the existing checks measure only what
they test. A clean validator run means no *detected* faults, not quality. Only
another annotator's work on the same clues shows whether a parse was the best
one. Note also that the published solution is in every puzzle file before
annotation starts, so annotation benchmarks test explaining a clue with a known
answer, not solving it.

### The annotator model

The nightly jobs annotate with Opus (`ANNOTATE_MODEL`, default `opus`, in
`tools/daily_update.sh` and `tools/prereset_backfill.sh`).
That is an alias, so each run records the exact model id it resolved to in the
puzzle's `provenance.annotatedBy`, and the commit trailer is read back from
there by `python3 tools/provenance.py trailer`. The choice rests
on one benchmark puzzle, 30078. Each model annotated it from scratch with the
same prompt and flags, and was compared with Fable's existing annotation:

| Model    | time  | steps | input | output | vs Fable              | cost   |
|----------|-------|-------|-------|--------|-----------------------|--------|
| Fable 5  | 990s  | 54    | 5.73M | 480k   | —                     | $35.91 |
| Opus 5   | 1038s | 45    | 7.30M | 215k   | 23/25 type, 22/25 def | $12.06 |
| Sonnet 5 | 1705s | 92    | 18.2M | 300k   | 21/25 type, 20/25 def | $7.56  |

- **Opus matches Fable in structure at a third of the cost.** It used no
  cryptic definitions and solved the two hardest clues. Its differences from
  Fable split one each way, plus cosmetic trailing-`?` spans.
- **Sonnet under-solves quietly.** It filed the two clues it could not solve
  (9A, 19D) as `cryptic definition`, landing exactly on the cap in both
  benchmark puzzles, and made one real parse error. Its output is
  validator-clean. Only a diff against a better annotator finds this.
- **Haiku fabricates.** On 30073 it returned "29/29 annotated — OK" with 17 of
  27 non-exempt clues containing no wordplay at all. The comparison checks
  above were added in response.
- **Prose.** Fable writes tighter and funnier (18 words per walkthrough against
  Opus's 30). Opus teaches better. A walkthrough must carry what the blocks
  cannot show and never re-narrate fragment-to-letters. Fable broke that rule
  in 8 of 25 clues, Opus in 3. Opus also records transferable conventions
  (`EG for 'say' is a workhorse abbreviation`, `6-4 means hyphenated`). Its
  weaknesses are boilerplate (`so 'X' names it by what it does` recurs) and a
  `definitionFit` averaging 24 words against a 30-word cap. Fable's extra output
  tokens were iteration, not finished prose.
- The pin rests on a single puzzle. Read the first few nightly runs, and read
  the capped clues of any run at `MAX_CRYPTIC_DEFINITIONS`.

## Social cards and icons

- **Icons and the social card are generated, never hand-edited.** The 5x5
  crossword motif is in `tools/make_icons.py`. It writes `favicon.ico`,
  `favicon-16.png`, `favicon-32.png`, `icon-192.png`, `icon-512.png`,
  `apple-touch-icon.png` and `favicon.svg`. The site-wide 1200x630 card
  (`og.png`) is `tools/og_card.html` rendered by `tools/make_og.sh` in headless
  Chrome, because real type needs a browser.
- **Every grid we draw must be a grid that could exist.** No grid is drawn by
  eye and trusted. The rules are in `tools/grid_rules.py`: its `check()`
  requires 180-degree symmetry, no run of exactly two white squares (no
  British cryptic has a two-letter entry), and every white square connected.
  The icon motif must pass `check()` before it is written. `mask()`
  demonstrates the rules against a real published grid. A run of one is fine:
  it is an unchecked square inside the crossing light.
- **The site card shows one clue coming apart, not a grid.** The definition and
  indicator are marked in the app's colours, the answer's letters are
  underlined where they hide, three rungs of the real ladder are shown, and the
  answer is withheld as empty boxes so the reader gets the aha. It uses a hidden
  word on purpose: that is the one family whose mechanism is fully visible in a
  still image. It is generated by `tools/make_og_card.py` from a published
  puzzle, and the underline is *computed* from the clue's letters.
- **Each puzzle page gets its own card.** A shared card would make every
  puzzle's link preview as somebody else's crossword. The card shows the best
  clue in that puzzle, and "best" means the best *picture*: whether the
  mechanism survives four seconds in a thumbnail. `score()` in
  `tools/make_og_card.py` ranks by visible mechanism (answer underlined where it
  hides, then anagram fodder laid out, then an indicator to point at), by
  length, and by whether the definition sits at one end. A puzzle with no
  qualifying clue keeps the site card; a weak card is worse than the generic
  one.
- **Card checks that fail the build** (all in `tools/make_og_card.py`):
  - No card may print its answer. The rungs are built from annotation prose,
    which can give it away.
  - Card family labels are diffed against `FAMILIES` in `app.js` on every build,
    so a card cannot describe a clue differently from the app.
  - `check_prose_stays_in_family`: card wording may not borrow another device's
    signal words. For example, "out loud" means a homophone, so it must not
    appear on a hidden-word card. It scans only the words the card adds, never
    the marks or fodder quoted from the clue. The word list is short on
    purpose: only wording that can mean nothing but its own mechanism, so
    "says to shuffle" passes and "out loud" does not. It raises `RuntimeError`,
    not `SystemExit`, because `pick()` reads `SystemExit` as "this clue can't be
    drawn" and would ship the bug on a different clue. The same rule applies to
    walkthroughs: "sounds like" about a charade is the same error.
- **A mark the prose never explains is a claim the reader must take on trust.**
  On an anagram card, rung 3 reads "<ind> says to shuffle <fodder>", not
  "Shuffle <fodder>".
- **Quote the explanation that already exists.** A walkthrough usually opens by
  glossing the indicator ("'Some' tells you to take only part of what
  follows"). `indicator_gloss` lifts that opening clause for the card when it
  leads with the indicator, fits a thumbnail line and does not give the answer
  away. Otherwise the card uses its generic line. A card is never blocked by
  prose. Writing a second explanation beside one that already exists is how
  the two drift apart.

## URLs, ids and search engines

- **The canonical URL is `https://cryptic.paultarjan.com/`.** It appears in
  `<link rel=canonical>`, `og:url`, `og:image`, the JSON-LD, `sitemap.xml`,
  `robots.txt` and `tools/og_card.html`. If it ever moves, all seven change
  together. In `tools/build_seo_pages.py` it is `BASE`.
- **A puzzle's id is its series and its number**: `cryptic-30089`,
  `everyman-4165`. Every paper numbers from its own 1, so a number alone would
  eventually collide across papers.
  - Spelled in one place: `series.puzzle_id` (`tools/series.py`).
  - Found in one place: `fetch_puzzle.puzzle_files`.
  - Resolved in one place: `fetch_puzzle.resolve_puzzle`. It also accepts a
    bare number, and refuses rather than guesses when the number is ambiguous.
- **Numbers stay numbers wherever a person reads one**: titles, picker rows,
  card art, prose. "No 30,089" is what the paper calls it. The id is a key, not
  a name.
- **Old ids keep working.** Saved progress renames itself once on boot,
  `?p=30080` still opens the puzzle it named, incoming sync envelopes are
  mapped on the way in, and every retired `/puzzles/<n>/` URL keeps a page
  that says where its puzzle went.
- **Decide from a field, never from how an id is spelled.** `is_authored` in the
  validator reads the puzzle's `series` field.
- **A series key is one lowercase word** (`indysunday`, not
  `independent-sunday`). The last hyphen splits key from number, and ids must
  match `^[a-z]+-\d+$`. That shape is asserted on filenames and on progress
  keys, and `series.puzzle_id` refuses a hyphenated key. A key is storage, not
  English: anything a solver reads comes from `series.badge`.
- **The address bar always names the puzzle on screen**, because links are
  copied from it. When the reader opens a puzzle, the app rewrites the URL with
  `replaceState` (never push; switching puzzles is not navigation, and Back
  should leave the site, not walk the picker). See `pointUrlAtPuzzle` and
  `shareUrl` in `app.js`.
  - A puzzle with a static page (`hasSolutions`) gets `/puzzles/<id>/`, which
    carries its own card. Otherwise it gets `?p=<id>`.
  - The canonical link moves with it: to `/puzzles/<id>/` when that page exists,
    otherwise the homepage.
  - A reload of `/puzzles/<id>/` in a tab that was solving goes back into the
    app. The app sets a `sessionStorage` flag, and the page's `<head>`
    (`app_return` in `tools/build_seo_pages.py`) redirects a flagged load to
    `?p=<id>&c=<ref>`. Crawlers and fresh visitors have no flag and get the
    static page.
  - **Only when the reader chose.** Booting on the remembered puzzle is not a
    choice, and a site root that rewrote itself would declare a puzzle as the
    homepage's canonical. That is why `openPuzzle(id, chosen)` takes the flag
    rather than inferring it.
  - Every URL the app builds is resolved against the canonical homepage
    (`at()` in `app.js`), never against the address bar, because the address
    bar may be `/puzzles/<id>/`.
- **Generated links have one joiner.** In `tools/build_seo_pages.py`,
  `site_url()` is the only function that joins a path to `BASE`, and both
  `breadcrumb_ld()` and `masthead()` go through it. `assert_no_root_relative()`
  fails the build on any `href="/…"` or `src="/…"`. Links are absolute
  (`BASE` + path) or relative to the page, which keeps generated pages openable
  from disk and makes a host move a one-line change to `BASE`.
- **Copy about the whole site names every paper in it, or none.** Naming one
  paper on a puzzle page is right. Doing it in a site title, meta description
  or heading is a claim about the whole collection. The archive page's title and
  description are derived from the publishers present (`papers()` in
  `tools/build_seo_pages.py`). `assert_names_all_papers()` checks the
  hand-written homepage `<head>` against the same list and fails the build.
  Where a stable phrase is wanted, prefer "broadsheet".
- **The Guardian publishes six cryptics a week, Monday to Saturday.** There is
  no Sunday cryptic. Saturday's is the *Prize* crossword: same number sequence,
  but at `/crosswords/prize/<n>`, not `/crosswords/cryptic/<n>`. The `cryptic`
  entry of `GUARDIAN_SERIES` and the `PUZZLE_URLS` list in
  `tools/fetch_puzzle.py` must always include both paths, or one puzzle in six
  goes missing. A fresh Prize puzzle lands with `hasSolutions` false and cannot
  be annotated yet. `--refresh-unsolved` re-fetches those each day, and the
  daily job runs it before annotating.

## Deploying

### Cache busting

GitHub Pages sends `max-age=14400`, so without a changing URL a phone shows
four-hour-old CSS after a reload. Chat apps (Discord, Slack, iMessage) cache
link previews against the image URL and cannot be told to refresh. **So
changing a file's bytes means changing its URL.**

- Every static file a page references carries `?v=<content hash>`: CSS, JS,
  `og.png` and the icons.
  - `asset()` in `tools/build_seo_pages.py` stamps generated pages.
  - `tools/stamp_assets.py` stamps the hand-written homepage.
  - Puzzle files use the `v` field in `puzzles/index.json`.
  - `python3 tools/stamp_assets.py --check` sweeps every page and fails the
    nightly run on a bare reference.
- **Stamping is a build step, not a stored value.** The committed `index.html`
  has bare references. `.github/workflows/pages.yml` runs
  `python3 tools/stamp_assets.py` on its own checkout, so what ships is stamped
  and what is stored is not. A hash in a tracked file would change on every
  asset commit, which is churn and a source of nightly rebase conflicts.
- **Do not commit a stamped `index.html`.** If you ran the stamper, or
  `tools/fetch_puzzle.py --reindex` (which also restamps), run
  `python3 tools/stamp_assets.py --unstamp` to put the tree back.
- The smoke test checks that each reference exists, never the stamp itself.
- Stamping does not fix caches still holding the old URL. Re-share a link to
  force a refetch, and expect a day's lag.

### Pushing is not deploying

GitHub Pages takes a minute or two to build after a push. **Nobody is told to
reload until `python3 tools/wait_for_deploy.py` exits 0.** It polls the live
homepage for the local `?v=` stamps, which proves the new code is being served,
not just that a commit arrived. It is the last step of the pipeline, after the
push.

## Scheduled jobs: quota, gates and alerts

The two jobs are `tools/daily_update.sh` and `tools/prereset_backfill.sh` (see
"Nightly jobs" in `README.md`).

- **A scheduled job never guesses a fact it can look up.**
  - `prereset_backfill.sh` runs with *no* usage gate. That is safe only in the
    last hour before unspent weekly quota expires. The reset time is a
    timestamp from `GET /api/oauth/usage`. The job runs hourly and exits within
    a second unless `weekly_usage.py --resets-in` says the window really is
    about to close.
  - `daily_update.sh` re-reads the five-hour session window between puzzles,
    not once at the start (when it always reads near zero). A budget is re-read
    between the things that spend it.
- **The spend gate fails closed.** `gate()` in `tools/weekly_usage.py` returns
  `spend`, `skip` or `unknown`, never a bare number that an empty string could
  turn into "go". `unknown` skips. A stale reading is still used as a floor:
  usage only rises within a window, so any reading from the current window is a
  lower bound, and a floor above the limit is a decision. `--self-test` runs the
  gate's four cases offline before any verdict is trusted, because a broken gate
  says "spend" just as confidently as a working one.
- **A job that borrows a credential must survive it going stale.**
  `weekly_usage.py` reads the CLI's OAuth access token, but nothing here
  refreshes it; only running `claude` does. The token lasts about eight hours.
  So cache the last good reading and say on stderr when you use it:
  - `resets_at` is an absolute timestamp and stays true indefinitely;
  - a usage percentage expires as a number after six hours, but never as a
    floor (see the rule above).
- **A gate that fails must alert.** Anything that decides whether to spend
  money or quota routes its own failure through `tools/alert.sh`, not a log
  line nobody reads.
- **Alert on the outcome, not the exit code.** A run that annotates two puzzles
  and then hits a rate limit did its job.
- **The same alert twice is noise.** `tools/alert.sh` sends an identical message
  at most once per `ALERT_REPEAT_HOURS` (default 12). The log still records every
  one.
- **`ANNOTATE_MAX`** (default 3) caps the backlog puzzles annotated per run. The
  daily job stops early the first time a `claude -p` run fails, because that is
  nearly always a session limit and the remaining attempts would fail too.
- The same "look it up" rule applies to data: `tools/series.py` is the only
  source of truth for what a series is.
