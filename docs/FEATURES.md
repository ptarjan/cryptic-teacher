# What the site does

The hint ladder's rungs are listed, generated from `app.js`, in the
[README](../README.md). This page says how the ladder behaves and what else
the site offers.

## How the ladder behaves

- **A rung asks before it tells.** Every rung except the walkthrough asks its
  question first. The indicator, definition and building-blocks rungs ask
  "which words?", and you answer by tapping words in the clue. The type rung
  offers the seven clue families to pick from. Answer correctly and you get the
  rung without spending a hint. "Just tell me" reveals it at the normal cost. A
  rung you worked out is scored separately from one you bought.
- **A piece with only one possible answer is handed over, not asked.** If the
  other rungs have already claimed every other word of the clue, tapping the
  rest would be a question with one answer.
- **The ladder is tiers, not a chain.** The three spotting rungs (indicators,
  definition, type) can be taken in any order. The building blocks and the
  walkthrough stay locked until the spotting rungs are up.
- **Solving the clue unlocks every rung for free.**
- **The indicator and type rungs end on a rule chip.** Tapping the small "rule"
  chip at the end of the rung opens a line that says
  what that device's words usually mean in any clue, with other words that do
  the same job, and links to the device's section of the /learn/ lesson. The
  rest of the ladder explains this clue; the rule is what carries over to the
  next one.
- **Finishing a grid recaps what you used.** "What you used today" lists the
  clue types you needed hints for, with how many clues each, linked to /learn/.

## Other features

- **Reveal one letter** is available at any time. It does not advance the
  ladder, but it counts against your score.
- **Report a bad hint** is on every clue: two taps and a sentence, with the
  puzzle and clue filled in for you.
- **Check** buttons (letter / entry / grid) mark wrong letters without
  revealing answers.
- A gentle score: clues solved with no hints, rungs shown, rungs worked out.
- A collapsible "How cryptic clues work" tutorial.
- A **glossary of standard abbreviations**. The building-blocks rung links into
  it word by word. Below the hand-built table, /abbreviations/ also lists the
  rarer conventions counted in solved clues.
- A list of **indicators** at /indicators/, by clue type and by how many clues
  use each one, from `tools/data/lexicons/indicators.json`.
- A puzzle picker.
- Progress is saved in localStorage, per puzzle.
