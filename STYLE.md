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

- The ladder never offers information that is useless given what the user
  already knows. Concretely: after the level-5 walkthrough names the answer,
  the final rung is "Fill in answer" — never letter reveals (feedback
  2026-07-26).
- "Reveal one letter" is a standalone anytime escape hatch, hidden once the
  entry is solved; using it never advances the ladder but always counts in
  scoring (meter, scorebar, and no-hints tally).
- The grid stays light-on-dark-letters in BOTH color schemes; grid cell colors
  are fixed, not theme variables (feedback 2026-07-26: dark-on-dark grid was
  unreadable).
- On touch devices, a scroll gesture must never select a cell or clue — tap
  detection uses a movement threshold (feedback 2026-07-26).
