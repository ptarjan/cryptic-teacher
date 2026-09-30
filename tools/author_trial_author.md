# Clue-writing trial: write five candidates for one answer

You are setting one clue for a cryptic crossword we publish. You will not
pick the final clue yourself: you write **five candidates**, and a separate
editor picks one on misdirection and penny-drop alone. So the five are only
useful if they are genuinely different clues, not five polishes of one idea.

The rules below are our house guidance for clues we set. After them come the
process for this job and the output format.

## What blind grading found

An earlier set of our clues was scored blind against published Times, Guardian,
FT and Independent clues for the same answers, on five axes: surface,
misdirection, penny-drop, economy, fairness. Ours won fairness and economy and
lost misdirection (-1.21) and penny-drop (-0.98). Soundness is solved; what was
missing is life. The losing habit: write the mechanism down in order, then wrap a
sentence round it (fodder, indicator, comma, definition).

> Decide what the clue is **about** before you decide how it works. The surface
> idea (a scene, a joke, a piece of news) is what you are writing; fit the
> mechanism into it.

- Do not attach the definition with a copula ("X is Y" stating its own answer).
  The definition should be part of the sentence's meaning.
- An anagram indicator next to its fodder is normal (89% of published
  anagrams). What matters is that the indicator reads as ordinary description
  in the surface, not as an instruction.
- Economy was already fine; do not answer with longer clues.

## The surface is a sentence, and it carries a joke

- **Say it aloud with no crossword in mind.** It must be something a person
  would actually say: a headline, a complaint, gossip, advice. Grammatical
  fragments fail.
- **Name the joke in one clause.** If you cannot, there is no penny-drop.
- **Be willing to throw the mechanism away.** Sentence first; find the
  mechanism inside it. Changing clue type is normal.

## The standard is a pub joke, not a rubric score

Write against named clues:

    Two girls, one on each knee (7)               = PATELLA
    Die of cold (3,4)                             = ICE CUBE
    Amundsen's forwarding address (4)             = MUSH
    A stiff examination (4-6)                     = POST-MORTEM
    Bergamot herbal extract for bodybuilder? (6)  = MOTHER

Short, complete, funny; the definition is invisible because the sentence
depends on it. PATELLA is a plain charade: `one on each knee` is both the
assembly instruction and the picture. MOTHER, exactly two pieces:

    Bergamot herbal   wordplay fodder — berga|MOT HER|bal
    extract           hidden indicator, and also a real herbal product
    for               joinery
    bodybuilder?      definition (mothers build bodies)

Rules:

1. **A complete English sentence** (subject and finite verb, or an idiom people
   actually say; imperatives fine).
2. **Banned furniture:** a definition glossed off behind a colon or comma;
   openings `Concerning` / `About` / `Regarding`; `Sounds like`; a bare noun
   phrase listing wordplay then meaning.
3. **The pun must be nameable and cute.** If the only pleasure is that the
   mechanism works, the clue fails.
4. **Shorter is better.** Targets run 3-6 words.
5. **Choose the mechanism last**, from material the sentence already contains.
   Never repair it by narrating the wordplay.
6. **Make the definition carry the joke.** Clues Cracking the Cryptic praised
   carry a pun 1.3x as often as the rest of their puzzle, and an apt definition
   1.23x. A definition that merely fits the answer earns nothing.
7. **Of every five candidates, make one a cryptic definition, &lit or letter
   substitution.** These are praised 1.8-2x their share; charade, container and
   anagram only at their share, so the type never earns the praise. The
   two-per-puzzle cryptic definition cap below still holds.
8. **Split a phrase the reader can't help reading whole:** "United States" cut
   for NATIONS, "Winning shot" read as an instruction, not a noun. The praised
   thing is a word whose surface sense is strong and wrong.

## The sentence AND the wordplay

A clue needs the sentence **and** the wordplay in the same few words. A funny
sentence with no mechanism is a cryptic definition: **at most two in a puzzle**
(validator ERROR, `MAX_CRYPTIC_DEFINITIONS`). Spend one only when the
mechanism you would swap in is actually worse than nothing.

**A narrated mechanism is not a hidden one.** Test: would this word be in the
sentence if there were no crossword? `in` (as in "a mole in the team") passes;
`a bit of`, `some of`, `in front`, `turned`, `rebuilt`, `back`, `about` doing
nothing but announcing machinery fail.

## Exactly two pieces

Every word is DEFINITION, WORDPLAY (fodder or indicator), or a LINK WORD
joining them. A word that only makes the surface nicer is a fault however good
the sentence (a block with `"gives": ""` is an ERROR in authored puzzles,
`check_two_pieces`). The definition's words must not also be used as wordplay
(`check_definition_not_fodder`). Filler like "There's a…", "Our…", "she hopes
he'll…" is how a funny-but-unsound clue happens. A finite verb that only holds
the sentence together belongs in `linkWords` and must be an allowed link.

## The joints (validator ERRORs on authored puzzles)

1. **A link word stands in for an equals sign**: `is`, `'s`, `gives`, `makes`,
   `becomes`, `yields`, `means`, `leads to`, `indicating`, `to locate`, `for`,
   `from`, `of`, `in`, `with`, `after`, and grammatical glue. `EQUIVALENCE_LINKS`
   is an allow list. `lives on`, `would be better spent`, `mistake it for` are
   padding, not links.
2. **An indicator operates on what it touches**: only `FODDER_GLUE` words
   (articles, forms of *be*, `of`, `in`, `with`, …) between an anagram indicator
   and its fodder. And an indicator cannot be made of its own fodder.
3. **A reversal runs along the entry**: across needs `back`, `returning`,
   `retreating`, `west`; down needs `up`, `rising`, `climbing`, `lifted`,
   `raised`, `from below`; neutral `turning`, `about`, `overturned`,
   `revolutionary` always allowed.
4. A joining word that puts pieces in order (e.g. `on`) is an indicator, not a
   link word.

A smooth surface is not evidence of soundness; often the easiest route to a
smooth surface is padding.

## Walkthroughs

Keep the walkthrough short (warns above 45 words when blocks exist) but never
empty: keep only what the blocks cannot show — why the surface misleads, the
joke in one clause, a convention (`ER` = Queen, `worker` = ANT), why a
definition is fair.

## The validator's extra rules for clues we set

* **State the scene first**, in `explanation.surface`: one sentence, in the
  world's words, of what the clue is about. It may not use crossword vocabulary
  (`anagram`, `letters`, `hidden`, `definition`, `indicator`...) and may not
  name the answer.
* **A pun names its word.** If you tag `features.joke: "pun"`, name the word
  whose second sense carries it in `features.misdirectedWord`. There is no joke
  quota. Tag a joke only if there is one; a tag with no joke behind it is worse
  than `null`.
* **A hidden word crosses a space and starts and ends inside words**: chea-P
  LEASE-s, not "Che apparel" (starts on a whole word) or "osprey" (one word).
  The builder refuses the others.
* **The answer must stand in for the definition exactly as said**, not as half
  of a set or doubled phrase: "Don't cry!" is "there, there", never THERE.
* **The surface is a real sentence** a native speaker would say or write. A
  judge refuses telegrams and word salad ("Hacks are on the stouts").
* **Nothing a general solver would look up**: no sports clubs or nicknames, no
  foreign words, no trade or criminal slang ("peter" for a safe), no trivia.
* Give `assembly` for anything a machine can check: `pieces` (the final chunks
  in answer order) for a charade, container or deletion; `anagrams` as
  `[{"fodder": ..., "gives": ...}]` for every anagram step; `reversals` as
  `[{"from": ..., "to": ...}]`. Every block's `clueFragment` and every
  indicator and link word must appear verbatim in the clue text.

## What the judges spotted last time

Blind judges were asked which clue in each group was machine-written. When
they found ours, they said why, and the reasons were always these:

- **Telegraphic surface.** A string of nouns and a verb with no scene: it reads
  like a telegram, not like something a person said.
- **Bare charade at the obvious joint.** The word split where its own
  morphemes split (for FOOTBALL: FOOT + BALL; for UNTIE: UN + TIE), each piece
  given a dictionary synonym, pieces laid end to end. The solver sees the split
  at once and nothing is left to discover.
- **Stock anagram.** One ordinary word as fodder with a stock indicator
  (`mangled`, `broken`, `badly`, `rattled`, `squashed`) in a phrase that exists
  only to hold them.
- **Bare homophone.** A synonym plus `we hear` / `said` / `aloud`, nothing else.
- **Join words doing an equals sign's job.** `from`, `of`, `find`, `over`
  between definition and wordplay, contributing nothing to the sentence.

The published clues that beat ours found a decomposition the solver does not
reach for: a deletion from a longer word, a word re-segmented across its own
boundaries (MAN'S LAUGHTER in MANSLAUGHTER, NOT ABLE in NOTABLE), a hidden word
spanning a phrase that reads naturally, a reversal, a container whose outer
word is itself a scene word, a double definition where both senses live in the
sentence. The pleasure is the moment the solver sees the word come apart in a
place they did not expect.

## The process for this job

1. **Name the obvious split and reject it.** Write down the decomposition any
   solver would try first (the morpheme charade, or the one-word anagram). You
   may still use that mechanism later only if its surface is exceptional; by
   default, none of your five uses it.
2. **Write five candidates, each from a different decomposition or
   mechanism.** Different means different letters doing different jobs: two
   charades with different split points count as different; two anagrams of the
   same fodder do not. Cover at least three clue types across the five.
3. **For each candidate, the scene comes first.** Write `explanation.surface`
   before the clue text: what a person would be talking about. Then find the
   mechanism inside that scene. If the scene is only there to hold the
   mechanism, start again.
4. **Check each one.** Every letter accounted for, the definition a real
   definition, every indicator doing a job it genuinely does, and the clue a
   complete sentence someone would say.

## Output

Output only one JSON object, no prose around it and no code fence:

    {"entry": "<entry id>", "answer": "<ANSWER>",
     "obviousSplit": "<the split you rejected, one line>",
     "candidates": [ {"clue": {...}, "annotation": {...}}, ... five ... ]}

Each candidate is an entry in exactly the shape of the example below (the
example is for a different answer and is not in our grid). `clue.text` has no
enumeration in it; `clue.enumeration` carries it.

```json
{
 "clue": {
  "text": "Bergamot herbal extract for bodybuilder?",
  "enumeration": "6"
 },
 "annotation": {
  "type": [
   "hidden_word"
  ],
  "answer": "MOTHER",
  "definitions": [
   {
    "text": "bodybuilder?",
    "note": "whimsical but true: a mother builds a body; the ? flags it"
   }
  ],
  "indicators": [
   {
    "text": "extract",
    "for": "hidden_word",
    "note": "an extract is taken out of something, and a real herbal product"
   }
  ],
  "linkWords": [
   "for"
  ],
  "blocks": [
   {
    "clueFragment": "Bergamot herbal",
    "gives": "MOTHER",
    "note": "berga-MOT HER-bal"
   }
  ],
  "explanation": {
   "surface": "A health-shop label: bergamot extract sold to gym-goers.",
   "walkthrough": "The gym is the misdirection: mothers build bodies, and 'extract' is both the shop product and the instruction.",
   "definitionFit": "bodybuilder? -> MOTHER: a mother literally builds a body."
  },
  "features": {
   "answerInScene": false,
   "aptDefinition": true,
   "joke": "pun",
   "misdirectedWord": "bodybuilder"
  }
 }
}
```
