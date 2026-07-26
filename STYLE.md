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
  so it must never go stale while typing. See `patternHTML()` in `app.js`,
  `.pattern`/`.pat-box` in `style.css` (page-theme vars only — the strip is
  outside `#grid`, and dark mode must stay dim), and the pattern assertions in
  `tools/smoke_test.js`.
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
- Every asset URL carries a content hash (`style.css?v=…`, puzzle files use the
  `v` field in `puzzles/index.json`). GitHub Pages sends `max-age=14400`, so
  without this a phone shows four-hour-old CSS after a reload (feedback
  2026-07-26). After ANY edit to index.html's assets run
  `python3 tools/stamp_assets.py`; the smoke test fails on stale stamps and
  `tools/daily_update.sh` re-stamps automatically.
