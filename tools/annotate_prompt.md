# Annotation task for Claude Code

You are annotating one cryptic crossword for the Cryptic Teacher app in this
repository. The caller names the puzzle and the file holding its clues and answers;
annotate that one and no other. The ID is series plus number (`cryptic-30089`, `everyman-4165`), because every
series numbers from 1 and the number alone names nothing.

## What to produce

One file, `tools/_ann_<ID>.json`: a single object with a key for every entry id, and
`null` for a clue not done yet.

```json
{"1-across": { ...annotation... }, "5-across": { ...annotation... }, "12-across": null}
```

Write annotations only; do not write a script to produce them. Each entry's
`"solution"` is ground truth: your parse must produce exactly those letters, and if it
does not, the parse is wrong, so rethink it rather than stretch it.

## Order of work

- **Write early.** Put clues into the file a handful at a time and run the check (below)
  as you go. Only what is on disk survives the run ending.
- **Solve in the order the crossings unlock**, not clue order. Skip a clue that resists
  and come back once its crossings are in: thinking longer without new letters does not
  produce new letters.
- **There is no word list.** `/usr/share/dict/words` is out of reach, and the other
  puzzles in `puzzles/` are not a dictionary; do not search them for fills.

## Schema

`puzzles/cryptic-30066.json` is a fully worked example.

```json
{
  "type": "every mechanism, joined with ' + ', from the Reference below",
  "answer": "DISPLAY FORM: the solution's letters, spaced only where the enumeration is",
  "definition": "exact substring of the clue",
  "definition2": "second definition, double definitions only",
  "definitionNote": "only if the definition disagrees with the answer in number or part of speech",
  "indicators": ["exact substring", "..."],
  "indicatorNotes": {"<each indicator string>": "why THIS word gives that instruction"},
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

Blocks are listed in the order the answer reads, not the clue; with a container,
reversal or rotation, in the order the pieces are assembled before that step.

## Taste

The check below enforces the mechanics and explains each rule when it is broken. These
it cannot see. `STYLE.md` holds the product feedback behind them; where the two
disagree, it wins.

- The definition must substitute for the answer in a sentence: same part of speech,
  same inflection. Say the swap out loud. This is the most common mistake.
- A link word joins and says nothing else. Don't borrow another mechanism's signal
  words in any prose field: "aloud" means homophone, "shuffle" anagram, "hidden"
  extraction, "reversed" turnaround.
- `surface` is the picture, not a paraphrase and no mechanics: `Behaved antisocially
  and gave birth` is one person's bad week. Omit it only when the clue paints no picture
  apart from its mechanism (`Flat (4)`).
- `walkthrough` says only what the blocks cannot: why the surface misleads, a convention
  the solver may not know (`ER` = Queen), why a definition is fair. Naming a chunk is
  fine when the sentence teaches (`OCT is the calendar abbreviation`); narrating
  fragment to letters is not.
- Where there is one false path a competent solver really takes first, name it and what
  kills it: `"Flowers" wants to be the definition; it is the river.` Most clues have
  none, and an invented one is worse than none. Every "the X" must be an X the reader
  can see in the clue.
- Many readers are not British. Where a clue turns on everyday British knowledge (a
  county, a soap, a cricket position, an old coin, rhyming slang, a word like banger or
  jumper), say what the thing is in one clause where it is needed: `THE OVAL is a London
  cricket ground`, `a banger is a sausage`. Brevity never drops this clause. Not for
  crossword conventions, which the app teaches.
- `features` is data for analysis, never shown to a solver. Honest nulls and falses are
  a usable row; a guessed `joke` poisons it. `joke` asks whether a joke is present, not
  whether it is funny.

## Check

```
python3 tools/annotate_check.py <ID>
```

It applies the file, validates it, audits it, and prints everything wrong in one report,
each line saying what to do. Fix everything it lists in one edit, run it again, and stop
when it says `clean`. What it prints under "worth knowing now" is advice, not a failure.

- Run it as a single command: no `&&`, `;`, pipes or `rm`. A compound command needs an
  approval this run cannot give, and aborts having run nothing.
- Don't open `validate_annotations.py`. For a line you cannot act on,
  `python3 tools/validate_annotations.py --explain <check-name>` prints that check.

<!-- REFERENCE-START — generated by tools/build_annotate_prompt.py -->

## Reference

Generated from the code that enforces it; do not read app.js or the validator
to check it.

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

<!-- REFERENCE-END -->
