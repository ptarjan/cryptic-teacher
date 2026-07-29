# Cryptic Teacher style guide

This is the permanent home for product feedback. When Paul gives feedback on a
puzzle, a hint, or the app, the fix goes in TWO places: the instance that prompted
it, and a rule here (plus, where possible, a mechanical check in
`tools/validate_annotations.py` or an assertion in `tools/smoke_test.js`).
`tools/annotate_prompt.md` tells the daily annotation run to follow this file, so
rules added here apply to every future puzzle automatically.

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

Worked examples: 30067 1A GARBAGE = `charade + alternate letters` (GARB +
alternate letters of bAgGiEr); 30066 5D ALLOCATE = `anagram + last letter`
(anagram of A COL TALE... + storE "ultimately").

When a new type part is needed, add it to `TYPE_PARTS` in the validator, this
list, and a level-1 blurb in `TYPE_BLURBS` in `app.js` — all three, in one commit.

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
  indicator rung; rung wording is type-specific (a double definition asks
  "where does the clue split?", an &lit asks "how can the whole clue be the
  definition?"); no rung may merely restate an earlier one. See `ladderSteps()`
  in `app.js`; the ladder length is per clue and shown as "x/N" in the meter.
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

## Deploy rules

- Icons and the social card are GENERATED, never hand-edited. The 5x5 crossword
  motif lives in `tools/make_icons.py` (favicon.ico, favicon-16/32, icon-192/512,
  apple-touch-icon) and is duplicated by hand in `favicon.svg` — change one, change
  both. The 1200x630 card is `tools/og_card.html` rendered by `tools/make_og.sh`
  (real type needs a browser, so headless Chrome draws it).
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
