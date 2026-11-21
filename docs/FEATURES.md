# What the site does

The hint ladder's rungs are listed, generated from `app.js`, in the
[README](../README.md). This page says how the ladder behaves and what else
the site offers.

## How the ladder behaves

- **A rung asks before it tells.** Every rung except the walkthrough asks its
  question first. The indicator, definition and building-blocks rungs ask
  "which words?", and you answer by tapping words in the clue. The type rung
  offers the seven clue families to pick from. Picks never confirm
  themselves. One button in the help bar under the panel does both jobs: with
  words picked it reads "Lock in" and is free; with nothing picked it reads
  "Show me", costs 1 hint and takes two taps (there is no "Check my answer" and
  no "Skip for now", picking another step is the skip). A right Lock in opens
  the step as worked out, with the green verdict. A wrong Lock in opens it
  exactly as Show me does and costs 1 hint: no verdict, no miss marks, no red,
  and a wrong clue family has no "Not X" line. A wrong piece followed by a
  right one keeps Pieces paid. A rung you worked out is scored separately from
  one you bought.
- **A piece with only one possible answer is handed over, not asked.** If the
  other rungs have already claimed every other word of the clue, tapping the
  rest would be a question with one answer.
- **The ladder is tiers, not a chain.** The three spotting rungs (indicators,
  definition, type) can be taken in any order. The building blocks and the
  walkthrough stay locked until the spotting rungs are up. The hint buttons are a step track of chips (Indicator, Definition, Clue type, Pieces, Solution): open, worked out (star), available or dim.
  Tapping a chip only chooses the step; the help bar button ("Show me") is what reveals it. In Pieces, the formula line is the question: tap a blank chip to make it current, tap clue words and Lock in, or Show me fills just that chip.
- **One letter wheel per clue.** A "Letters" toggle beside the answer boxes opens one wheel on any unsolved clue, whatever its type, and is never a hint. It opens empty from the toggle, or dealt with the fodder on its own when Pieces shows a whole-answer anagram (a part-anagram deals nothing), and it replaces the question at the end of the hint body. While it is open the clue's own words are its picker. Crossing off every tile of a dealt wheel finishes Pieces.
- **Solving the clue unlocks every rung for free.** The help bar then becomes one free
  "How it works" button (no red, no cost text) in place of the step buttons; one tap
  opens every step in order. Whatever was open stays open, nothing opens by itself,
  and the "Good clue?" vote sits under it.
- **The indicator and type rungs end on a rule chip.** Tapping the small "rule"
  chip at the end of the rung opens a line that says
  what that device's words usually mean in any clue, with other words that do
  the same job, and links to the device's section of the /learn/ lesson. The
  rest of the ladder explains this clue; the rule is what carries over to the
  next one.
- **Finishing a grid recaps what you used.** "What you used today" lists the
  clue types you needed hints for, with how many clues each, linked to /learn/.

## Other features

- **Reveal letter** is available at any time. It does not advance the
  ladder, but it costs one hint, like every paid button ("Tap again · 1 hint").
- **One help bar** under the panel holds "Lock in" / "Show me", Reveal letter, Letters and
  a "…" with Reveal answer, Report a bad hint and the blog link.
- **Report a bad hint** is on every clue: two taps and a sentence, with the
  puzzle and clue filled in for you.
- A **menu** ("…" on the puzzle's title row) holds the rarely used controls,
  off the solving path: paper mode, clear word and reset puzzle. Paper mode's
  own "Is it right?" shows under the grid only while it is on. The grid itself
  marks right, never wrong.
- A gentle score: clues solved with no hints, steps shown, steps worked out, and a single hint count (a revealed letter is a hint).
- A collapsible "How cryptic clues work" tutorial.
- A **glossary of standard abbreviations**. The building-blocks rung links into
  it word by word. Below the hand-built table, /abbreviations/ also lists the
  rarer conventions counted in solved clues.
- A list of **indicators** at /indicators/, by clue type and by how many clues
  use each one, from `tools/data/lexicons/indicators.json`.
- A puzzle picker.
- Progress is saved in localStorage, per puzzle.
