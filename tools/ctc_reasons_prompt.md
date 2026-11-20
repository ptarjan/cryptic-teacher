# Why did the solver react to this clue?

Each line of the packet is one clue from a Times (or other) cryptic, plus a
transcript of Cracking the Cryptic solving it aloud around the moment a
regex flagged a reaction (`triggers`). Auto captions: no punctuation you can
trust, homophone errors, and two voices run together.

For each line decide:

- `verdict`: `praise` if the solver is admiring THIS clue, `dislike` if they
  are complaining about THIS clue, `none` if the trigger word is about
  something else (another clue, the dictionary, "lovely" as filler, banter).
- `reasons`: only when the verdict is not `none`. One to three, from this list:
  - `misdirection`: the surface steers you to the wrong meaning of a word
  - `surface_story`: the clue reads as a natural, vivid sentence or scene
  - `unexpected_decomposition`: the answer splits into pieces you did not expect
  - `humour`: a pun, joke or absurd image that makes them laugh
  - `and_lit`: the whole clue is both definition and wordplay
  - `clever_definition`: a cryptic, oblique or witty definition
  - `lift_and_separate`: a phrase must be split against its natural reading
  - `neat_device`: an elegant indicator or mechanism (hidden, reversal, container...)
  - `economy`: short, nothing wasted
  - `penny_drop`: the "aha" when a long-resisted clue gives way
  - `obscure_vocab`: the answer or a piece is a word they did not know
  - `unfair_gk`: needs general knowledge a solver cannot derive
  - `loose_definition`: the definition does not quite mean the answer
  - `clunky_surface`: the sentence does not read naturally
  - `other`
- `quote`: the solver's own words that say why, at most 25 words, copied from
  the transcript. Empty if the verdict is `none`.

Write one JSON object: `{"<id>": {"verdict": ..., "reasons": [...], "quote": ...}, ...}`
covering every id in the packet, to the output path you were given. No prose.
