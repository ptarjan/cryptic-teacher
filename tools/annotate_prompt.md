# Annotation task for Claude Code

You are annotating one cryptic crossword for the Cryptic Teacher app in this
repository. The caller names the puzzle, `puzzles/<ID>.json`; annotate that one and no
other. The ID is series plus number (`cryptic-30089`, `everyman-4165`,
`independent-12438`, `book-3003`), because every series numbers from 1 and the number
alone names nothing.

## What to produce

One file, `tools/_ann_<ID>.json`: a single object with a key for every entry id.

```json
{"1-across": { ...annotation... }, "5-across": { ...annotation... }, "12-across": null}
```

Write annotations only. Do not write a script to produce them.

A missing key stops the file being applied at all. A `null` applies, but the validator
fails the whole puzzle on it and the night's work on that puzzle is thrown away. So
use `null` as a placeholder while you work, and finish with none, with one exception:
a clue you cannot parse without inventing wordplay stays `null`. A failed puzzle can
be retried. A confident wrong explanation cannot be caught.

Each entry's `"solution"` is ground truth. Your parse must produce exactly those
letters; if it does not, the parse is wrong, so rethink it rather than stretch it.

The exception is a puzzle with a top-level `"solutionSource"`: its answers were filled
by a model, not printed by the paper. With `"officialKey": "never"` (the Penguin book
reprints) no key will ever arrive to correct them. There, an entry marked
`"solutionConfidence": "LIKELY"` has letters forced by the definition and crossings
but wordplay that did not parse. Annotate it only if you can derive the whole answer
from the clue yourself. Otherwise it is the `null` exception above: the site would
present an invented parse as authoritative, and nothing downstream would catch it.
An unmarked entry is CONFIDENT and is annotated normally.

## Order of work

- **Write early.** Put clues into `tools/_ann_<ID>.json` a handful at a time. Only
  what is on disk survives the run ending.
- **Solve in the order the crossings unlock**, not clue order.
- **Skip a clue that resists** and come back once its crossings are in. Thinking
  longer without new letters does not produce new letters.
- **There is no word list.** `/usr/share/dict/words` is out of reach, and the other
  puzzles in `puzzles/` are not a dictionary; do not search them for fills.
- **Look it up once a clue has beaten you.** fifteensquared.net blogs these series
  clue by clue (`WebSearch` for `fifteensquared <paper> <number>`; the comments often
  have what the blogger missed). Take only the mechanism and write every field
  yourself, in this file's voice.

## Schema

`puzzles/cryptic-30066.json` is a fully worked example.

```json
{
  "type": "anagram | charade | container | ... — every mechanism, joined with ' + '",
  "answer": "DISPLAY FORM: the solution's letters, spaced only where the enumeration is",
  "definition": "exact substring of the clue",
  "definition2": "second definition, double definitions only",
  "definitionNote": "only if the definition disagrees with the answer in number or part of speech: why the setter is allowed it",
  "indicators": ["exact substring", "..."],
  "indicatorNotes": {"<each indicator string>": "one sentence: why THIS word gives that instruction"},
  "linkWords": ["exact substring joining definition to wordplay, e.g. 'to locate'"],
  "blocks": [
    {"clueFragment": "exact words from the clue", "gives": "LETTERS", "note": "why"},
    {"clueFragment": "for homophones/spoonerisms", "soundsLike": "WHAT YOU SAY ALOUD", "gives": "HOW IT IS SPELT", "note": "why"}
  ],
  "surface": "one sentence, 25 words max: what the clue pretends to be about",
  "walkthrough": "1-2 sentences, 45 words max: what the blocks cannot show",
  "definitionFit": "one sentence, 30 words max: why the answer means the definition",
  "features": {
    "misdirectedWord": "the one clue word, spelt as printed, whose surface sense is furthest from its job; or null",
    "joke": "\"pun\" (a word's second sense or sound), \"absurd\" (silly on purpose), or null",
    "answerInScene": "true/false: does the solution belong in the picture the surface paints?",
    "aptDefinition": "true/false: is the definition fresh or witty rather than a dictionary synonym?"
  },

  "pieces": ["CHUNKS", "THAT", "CONCATENATE", "TO", "THE", "ANSWER"],
  "anagram": {"fodder": "LETTERS WHOSE MULTISET EQUALS THE ANSWER"},
  "subAnagrams": [{"fodder": "SUIT", "gives": "TISU"}],
  "subReversals": [{"from": "MAC", "to": "CAM"}]
}
```

Every field above `pieces` is required, except that `definition2`, `definitionNote`,
`linkWords` and `surface` appear only where they apply, and `indicators` with
`indicatorNotes` only when the clue has indicators.

## Rules

`STYLE.md` holds the product feedback these rules come from; where the two disagree,
it wins.

### Type

- `type` names every mechanism the wordplay uses, joined with ` + ` (`charade +
  alternate letters`), from the closed vocabulary in the Reference below. If nothing
  fits, the parse is wrong. Adding a part is a code change, not part of this run.
- `cryptic definition` is the only type with no checkable wordplay, so reaching for it
  is usually giving up. Hunt for the charade or container it hides first ("Periods on
  horseback where British king into himself?" looks like a whole-clue definition of
  CHUKKAS and is CHAS around UK + K). A cryptic definition that is not one is a wrong
  answer nobody can find. When a clue really is one, its blocks split the clue into at
  least two READINGS (the sense the surface pushes, the sense the setter meant), and no
  block carries `gives`.

### Definition

- `definition`, `definition2`, every indicator and every link word must occur verbatim
  in the clue. Copy them from the file: Guardian clues use curly `’` and en dashes `–`,
  Independent clues straight `'` and hyphens.
- The definition must be substitutable for the answer: same part of speech, same
  inflection. Say the swap out loud. This is the most common mistake.
- If it genuinely does not agree ("Lousy payment" = PEANUTS), add a `definitionNote`,
  a real sentence saying why the setter is allowed it. Do not stretch it or ignore it.
- `definitionFit` names the relation between answer and definition: a plain synonym, a
  definition by example, a crossword-only sense, a regional use, an idiom. Never read
  the definition back: `army ants move in a crawling column, and 'crawler' also carries
  the grovelling sense the surface points at`, not `an army ant is a crawler`. Cover
  both senses of a double definition; for `&lit`, say why the whole clue reads straight.
- The definition's words are not wordplay. A block reusing a word the definition
  claimed says the answer is the answer; if that is all you have, the clue is unsolved.

### Indicators and link words

- Every indicator gets an `indicatorNotes` entry keyed by the identical string, saying
  which sense of this word carries the instruction: `'stable? No' means unstable, and
  something unstable will not stay in the order it is given`, not `'stable? No' is the
  anagram indicator`.
- A link word joins and says nothing else. `on`, `after`, `behind`, `below`, `under`
  and `following` also say which way round ("A on B" in an across entry is B then A);
  where one of them sets the order of the pieces it is an indicator with a note, not a
  link word, because the page tells solvers a link word contributes no letters.
- Don't borrow another mechanism's signal words in any prose field. "Aloud", "sounds
  like" mean homophone; "shuffle", "jumbled" mean anagram; "hidden" means extraction;
  "reversed" means turnaround.

### Blocks

- Account for every content word of the clue: each sits in the definition, an
  indicator, `linkWords` or a block's `clueFragment`. A leftover word is a link word, an
  indicator you missed, a letter you never named (a deletion needs a block for the
  letter removed, `hard` = H), or surface padding: a block with an empty `gives` and a
  note saying so. Padding is allowed only in published clues; in a puzzle you are
  writing (`tools/AUTHORING.md`) rewrite the clue without the word.
- The blocks are the parse. Their letters add up to exactly the answer's (deletions and
  substitutions excepted). Where `pieces` splits the answer, the blocks split it the
  same way, never in one lump. Every block that gives letters has a `note` saying why.
- List blocks in the order the answer reads, not the clue: "Peas ... sweet" for SWEET
  PEAS gives SWEET then PEAS. With a container, reversal or rotation, use the order the
  pieces are assembled before that step.
- Give `pieces` for charades, containers and deletions (the final chunks in answer
  order), `anagram.fodder` for anagrams (including any letters added), and
  `subAnagrams`/`subReversals` for embedded steps. Double definitions, homophones and
  hidden words need none.
- A homophone or spoonerism names what you say aloud in `soundsLike` on the sounding
  block, and it must differ from `gives`. The note carries the step before the sound:
  "Cockney mob loudly" → OARED is `soundsLike: "’ORDE", gives: "OARED"`, the note saying
  a mob is a HORDE and a Cockney drops the aitch. A mechanism feeding the sound gets its
  own earlier block. A spoonerism swaps sounds, not letters.
- One to three capitals handed over for a word they abbreviate is a convention, and
  warns unless `tools/data/abbreviations.json` has it. If an operation produced the
  letters (a first letter, a deletion, a sound), say so in the note and it is not a
  convention. If it is one a solver should learn, run `python3 tools/add_abbreviation.py
  LETTERS sense` (never edit the JSON by hand), then `python3
  tools/build_abbreviations.py`.
- Linked entries (a `group`, "See 1"): the full annotation goes on the FIRST entry with
  `"coversGroup": true`, its `answer` the group's solutions run together in group order
  with no spaces. Each other entry is `{"linkedTo": "<first-id>"}` and nothing else.

### Prose

These fields are published, in the order the solver asks for help.

- Nothing shown before the walkthrough may spell the answer: not the definition,
  indicators, link words, indicator notes or block notes. Write a note about its
  fragment and let the walkthrough reveal.
- `surface` is the picture, not a paraphrase and no mechanics: `Behaved antisocially
  and gave birth` is one person's bad week. Omit it only when the clue paints no picture
  apart from its mechanism (`Flat (4)`); that depends on the clue, not its type. Do not
  repeat it in the walkthrough.
- `walkthrough` is never empty and says only what the blocks cannot: why the surface
  misleads, a convention the solver may not know (`ER` = Queen), why a definition is
  fair. Don't re-narrate fragment → letters (`the referee tucked inside a stately walk:
  P(REF)ACE`); naming a chunk is fine when the sentence teaches (`OCT is the calendar
  abbreviation and OPUS the composer's 'work'`).
  - Open with the thing itself, not an appraisal: no `A lovely/neat/classic ...`, `Two
    instructions stacked: ...`, `This is a ...`.
  - End on a fact, not a verdict: `That switch is the whole difficulty` says nothing.
    If a second sentence has nothing new, write one sentence.
  - Where there is one false path a competent solver really takes first, name it and
    what kills it: `"Flowers" wants to be the definition; it is the river.` Most clues
    have none, and an invented one is worse than none.
  - Every "the X" must be an X the reader can see in the clue.
- Many readers are not British. Where a clue turns on everyday British knowledge (a
  county, a motorway, a soap, a cricket position, an old coin, a regiment, rhyming
  slang), say what the thing is in one clause, in the note or `definitionFit` that
  needs it: `THE OVAL is a London cricket ground`. Not for crossword conventions, which
  the app teaches, or what any dictionary reader knows.
- No hedging and no working-out in any published field. If it needs "somehow" or "no
  wait", the parse is wrong: find the one that needs no excuse.

### Features

`features` is data for analysis and is never shown to a solver. Record what is there:
honest nulls and falses are a usable row, a guessed `joke` poisons it, and a
`misdirectedWord` the clue does not contain is rejected. `joke` asks whether a joke is
present, not whether it is funny.

## Check

```
python3 tools/annotate_check.py <ID>
```

It applies the file, validates it, audits for answer leaks and re-narrated
walkthroughs, syntax-checks the puzzle, refreshes the index, and prints everything
wrong in one report. Fix everything it lists in one edit, run it again, and stop when
it says `clean`.

- Run it as a single command: no `&&`, `;`, pipes or `rm`. A compound command needs an
  approval this run cannot give, and aborts having run nothing.
- Don't open `validate_annotations.py`. For a line you cannot act on,
  `python3 tools/validate_annotations.py --explain <check-name>` prints that check's
  source; with no argument it lists them.
- Don't commit. The calling script does, and `git` is not among your tools.

<!-- REFERENCE-START — generated by tools/build_annotate_prompt.py -->

## Reference

Generated from the code that enforces it. Do not edit it by hand, and do not
read app.js or the validator to check it.

### The controlled vocabulary for `type`

Join parts with ` + `. Each part belongs to one family, shown on the
"What kind of clue is this?" rung; a compound type's family is the
FIRST row below that matches it.

**Double or cryptic definition**

  `cryptic definition` `double definition`

**&lit**

  `&lit`

**Anagram**

  `anagram` `cycling`

**Homophone**

  `homophone` `spoonerism`

**Charade**

  `charade`

**Container, reversal or deletion**

  `container` `deletion` `palindrome` `reversal` `substitution`

**Hidden**

  `alternate letters` `eighth letter` `eighth letters` `eleventh letter`
  `eleventh letters` `fifth letter` `fifth letters` `first letter` `first letters`
  `fourth letter` `fourth letters` `hidden word` `last letter` `last letters`
  `middle letter` `middle letters` `ninth letter` `ninth letters` `outer letters`
  `prime letters` `regular letters` `second letter` `second letters` `seventh letter`
  `seventh letters` `sixth letter` `sixth letters` `tenth letter` `tenth letters`
  `third letter` `third letters` `twelfth letter` `twelfth letters`

### What the validator rejects

- A `walkthrough` over **60** words.
- Blocks whose letters are not the answer's, blocks that hand the answer over in one
  lump where `pieces` takes it apart, and blocks out of answer order. Exempt from the
  letter count, because their blocks claim no letters: `deletion`, `substitution`,
  `cryptic definition`, `double definition`, `homophone`, `spoonerism`, `&lit`. That
  exemption is what makes those types the easy way out of a clue you have not parsed.
- More than **3** clues in one puzzle whose blocks take their letters from their own
  definition (exempt: `&lit`, `double definition`, `cryptic definition`).
- In `walkthrough`, `surface`, `definitionFit` or a block `note`, working-out:
  `actually:` `correct parse` `hold on` `ignore that` `let me reconsider` `let me try`
  `no wait` `no, wait` `not it either` `on second thought` `re-examine` `scratch that`
  `still wrong` `that is not it` `that's not it` `wait --` `wait—`. In `walkthrough`,
  hedges: `close enough` `don't ask` `for some reason` `hand-wave` `handwave` `if you
  squint` `jokingly` `somehow`.
- Over **2** `cryptic definition` clues, in a puzzle we set ourselves. In a published
  puzzle, 2 or more only warns, naming each one for a human to check.

<!-- REFERENCE-END -->
