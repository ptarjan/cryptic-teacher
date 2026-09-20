# Annotation task for Claude Code

You are annotating a broadsheet cryptic crossword for the Cryptic Teacher app in this
repository — a Guardian daily or Quiptic, the Observer's Everyman, the Independent's
daily or Sunday, Private Eye's Cyclops, Metro's daily, the Globe and Mail's, or a
Guardian reprint out of a Penguin book. The target file is `puzzles/<ID>.js`, where the
ID is the series and the number together (`cryptic-30089`, `everyman-4165`,
`quiptic-1395`, `independent-12438`, `indysunday-1903`, `book-3003`); every paper
numbers from its own 1, and every scanned book is the one `book` series with the
book folded into the number — `book-3003` is Penguin book 5's No 3 — so the
number alone names nothing. The caller names the file to annotate; that file is the target and picking a
different one is never right.

## What to produce

One JSON file, `tools/_ann_<ID>.json`, holding a single object keyed by entry id:

```json
{"1-across": { ...annotation... }, "5-across": { ...annotation... }, "12-across": null}
```

Every entry needs a key. `null` means you could not solve that clue, which is allowed;
a MISSING key is an error, because the file cannot tell a forgotten clue from an
abandoned one.

Do not write a script to do this. The annotations are the work; write only those.

Each entry's `"solution"` field is ground truth: your parsing must produce exactly
those letters. If it does not, the parse is wrong — rethink it, do not stretch it.

**Except where the puzzle says otherwise.** A puzzle carrying a top-level
`"solutionSource"` was not solved by its paper; the answers are a model's, filled
cold and checked only for grid consistency. Where that object also says
`"officialKey": "never"` — the Penguin book reprints — no key is coming to correct
them either, so the file in front of you is the only account of that puzzle there
will ever be.

In those puzzles an entry may carry `"solutionConfidence": "LIKELY"`. That means the
letters were forced by the definition and the crossings and **the wordplay does not
fully parse**. Its absence means CONFIDENT, which is the normal case.

A `LIKELY` entry is the one place on this site where inventing a parse does real
damage: the answer is probably right, the site would present your explanation as
authoritative, and nothing downstream will ever catch it. So do not manufacture
wordplay to cover the gap. Either you can derive the whole answer from the clue
yourself — in which case annotate it normally, because you have solved what the
solver could not — or you cannot, in which case write `null` for that entry. `null`
is already the allowed answer for a clue you could not parse, and it is the right
answer here. A hedged walkthrough is not a third option; the validator rejects
hedges, and it should.

Then apply and check with one command, and repeat until it reports `clean`:

```
python3 tools/annotate_check.py <ID>
```

## Order of work

- **Write early, and keep writing.** Put what you have into `tools/_ann_<ID>.json` as
  soon as a handful of clues are done and add to it as you go. Only what is on disk
  survives the run ending.
- **Solve in the order the crossings unlock**, not clue order.
- **A clue that resists is a clue for later, not a clue to grind.** Leave it `null`,
  move on, and come back once its crossings are filled. Thinking longer without new
  letters does not produce new letters.
- **There is no word list.** `/usr/share/dict/words` is outside the working directory
  and this run cannot read it, and the other puzzles in `puzzles/` are not a
  dictionary. Do not search the corpus for candidate fills.
- **Look it up before you settle for `null`**, but only once a clue has beaten you.
  Guardian and Independent puzzles are blogged clue by clue at fifteensquared.net
  (`WebSearch` for `fifteensquared <paper> <number>`; the comments often carry what the
  blogger missed). Take only the mechanism: the blocks, walkthrough and definitionFit
  are written from scratch, in this file's voice.

## Schema

`puzzles/cryptic-30066.js` is a fully worked example.

```json
{
  "type": "anagram | charade | container | hidden word | homophone | reversal | deletion | double definition | &lit (combinations joined with ' + ')",
  "answer": "DISPLAY FORM (spaces/apostrophes/hyphens ok; letters must equal the solution)",
  "definition": "exact substring of the clue text",
  "definition2": "second definition, only for double definitions",
  "definitionNote": "only when the definition disagrees with the answer in number or part of speech: a sentence saying why the setter is allowed it",
  "indicators": ["exact substring", "..."],
  "indicatorNotes": {"exact substring from indicators": "REQUIRED, one sentence: why THIS word means that instruction"},
  "linkWords": ["exact substring joining definition to wordplay, e.g. 'to locate'"],
  "blocks": [
    {"clueFragment": "exact words from the clue", "gives": "LETTERS", "note": "why"},
    {"clueFragment": "for homophones/spoonerisms", "soundsLike": "WHAT YOU SAY ALOUD", "gives": "HOW IT IS SPELT", "note": "why"}
  ],
  "surface": "one sentence, 25 words max: what the clue PRETENDS to be about. Omit only when there is no surface apart from the mechanism.",
  "walkthrough": "1-2 sentences, 45 words max: what the blocks CANNOT show. Friendly teaching tone.",
  "definitionFit": "REQUIRED. One sentence, 30 words max: why the ANSWER means the DEFINITION.",
  "features": {
    "misdirectedWord": "REQUIRED. The one word of the clue whose surface sense is furthest from its real job, exactly as the setter spelt it — or null if nothing misleads.",
    "joke": "REQUIRED. \"pun\" if the humour is in a word's second sense or its sound, \"absurd\" if the surface is silly on purpose, null if there is no joke.",
    "answerInScene": "REQUIRED true/false. Does the SOLUTION belong in the picture the surface paints?",
    "aptDefinition": "REQUIRED true/false. Is the definition a fresh or witty way to say the answer, rather than a dictionary synonym?"
  },

  "pieces": ["CHUNKS", "THAT", "CONCATENATE", "TO", "THE", "ANSWER"],
  "anagram": {"fodder": "LETTERS WHOSE MULTISET EQUALS THE ANSWER"},
  "subAnagrams": [{"fodder": "SUIT", "gives": "TISU"}],
  "subReversals": [{"from": "MAC", "to": "CAM"}]
}
```

## Rules

`STYLE.md` at the repo root is the product feedback these rules distil; where the two
disagree, it wins.

- `type` names EVERY mechanism the wordplay uses, joined with ` + ` (`charade +
  alternate letters`), from the controlled vocabulary in the Reference at the end of
  this file. If a clue truly needs a new part, add it to `TYPE_PARTS` in the validator,
  to STYLE.md, and to `TYPE_BLURBS` plus a family in `FAMILIES` in `app.js`, then rerun
  `python3 tools/build_annotate_prompt.py`.
- `cryptic definition` is capped at two per puzzle, and the second already warns. It is
  the only type with no checkable wordplay, so reaching for it is usually giving up:
  spend one more pass hunting for the container or charade it hides ("Periods on
  horseback where British king into himself?" looks like a whole-clue definition of
  CHUKKAS and is CHAS around UK + K). If you cannot solve the clue, `null` is honest and
  someone will finish it; a cryptic definition that isn't one is a wrong answer nobody
  can find. When a clue genuinely is one, its blocks split the clue into READINGS, not
  letters — at least two, one for the sense the surface pushes and one for the sense
  the setter meant — and no block carries `gives`.
- `definition`, `definition2` and every string in `indicators` must occur verbatim in
  the clue. Copy from the file rather than retyping: Guardian clues use curly `’` and
  en dashes `–`, Independent clues use straight `'` and hyphens, and an Independent
  `<i>` tag is part of the clue string.
- The `definition` must be substitutable for the answer: same part of speech, same
  inflection. Say the swap out loud. This is the single most common mistake.
- If the definition genuinely does not agree with the answer ("Lousy payment" =
  PEANUTS), add a `definitionNote` — a real sentence — saying why the setter is allowed
  it. Do not stretch it and do not ignore it.
- `definitionFit` says why the ANSWER means the DEFINITION, the non-mechanical half of
  the clue. Name the relation — a plain synonym, a definition by example, a sense that
  survives mainly in crosswords, a regional use, an idiom — never the definition read
  backwards: `army ants move in a crawling column, and 'crawler' also carries the
  grovelling sense the surface points at`, not `an army ant is a crawler`. Cover both
  senses of a double definition; for `&lit`, say why the whole clue reads straight.
- Every indicator needs an `indicatorNotes` entry keyed by the identical string, saying
  which sense of THIS word carries the instruction: `'stable? No' means unstable, and
  something unstable will not stay in the order it is given`, not `'stable? No' is the
  anagram indicator`. It renders before the answer, so it must not name the answer.
  Note every indicator or none: one short keeps the app's generic wording.
- Account for EVERY content word of the clue: each sits in the definition, an
  indicator, `linkWords`, or a block's `clueFragment`. A leftover word is a missed piece
  of wordplay, and it is one of four things: a link word (`to locate` — no letters), an
  indicator you overlooked (`facing`), a letter you never named (a deletion needs a
  block for the letter removed, `hard` = H, not just the word it left), or genuine
  surface padding — a block with an empty `gives` and a note saying so. That fourth
  option is only for published clues; in a puzzle you are writing
  (`tools/AUTHORING.md`) it is an ERROR, so rewrite the clue without the word.
- A link word joins and says nothing else. `on`, `after`, `behind`, `below`, `under`
  and `following` also say WHICH WAY ROUND — in an across entry "A on B" is B then A —
  and where one of them is what puts the pieces in the answer's order it is an
  indicator, with an `indicatorNotes` entry, not a `linkWord`. The page tells solvers a
  link word "contributes no letters of its own", so filing the clue's only instruction
  there leaves nothing to explain why a piece moved.
- The definition's words are not wordplay. A block whose `clueFragment` repeats a word
  the `definition` claimed says the answer is the answer. If you cannot see the
  wordplay, the clue is unsolved — leave it `null`.
- The blocks are the parse. Their letters must add up to exactly the answer's
  (deletions and substitutions excepted); if `pieces` takes the answer apart, the blocks
  take it apart the same way rather than handing it over in one lump; and every block
  that claims letters carries a `note` saying why those words give those letters.
- List the blocks in the order the ANSWER reads, not the clue: "Peas ... sweet" for
  SWEET PEAS gets SWEET then PEAS, each `clueFragment` still pointing at its own words.
  Where a container, reversal or rotation is in the mix, the order the blocks are
  assembled before that step is the right one.
- Provide `pieces` for charades, containers and deletions (the final chunks in answer
  order) or `anagram.fodder` for anagrams (including any extra letters joined in), and
  `subAnagrams`/`subReversals` for embedded steps. Double definitions, homophones and
  hidden words need neither.
- A homophone or spoonerism names the word you say aloud in `soundsLike` on the block
  that does the sounding, and its letters must differ from `gives` or it is a spelling,
  not a sound. The note carries the step before the sound: "Cockney mob loudly" →
  OARED is `soundsLike: "’ORDE", gives: "OARED"`, the note saying a mob is a HORDE and
  a Cockney drops the aitch. A mechanism feeding the homophone gets its own earlier
  block.
- A block handing over one to three capitals for a word they abbreviate leans on a
  convention, and warns if `tools/data/abbreviations.json` has no row for it. If the
  letters came from an operation the clue asked for (a first letter, outer letters, a
  deletion, a sound), say so in the note and it is no longer a convention. If it is one
  the solver should own forever, run `python3 tools/add_abbreviation.py LETTERS sense`
  (never edit the JSON by hand — other sessions are writing it at the same time) and
  then `python3 tools/build_abbreviations.py`.
- Linked entries (a `group` of several ids, "See 1"): the full annotation goes on the
  FIRST entry with `"coversGroup": true`; each other entry is `{"linkedTo": "<first-id>"}`
  and nothing else. On the covering entry, `answer` is the group's solutions run
  together with no spaces, in group order, and the blocks account for all of it.
- `surface` is one sentence saying what the clue pretends to be about — the picture,
  not a paraphrase: `Behaved antisocially and gave birth` is one person's bad week. No
  mechanics in it. It is shown under **The joke**; omit it only when the clue paints no
  picture apart from its mechanism (`Flat (4)`). That is a question about the clue,
  not its type — the double definition above paints one.
- `walkthrough` is short, because the blocks did the work. Never re-narrate fragment →
  letters; write only what the blocks cannot show — why the surface misleads, a
  convention the solver may not know (`ER` = Queen, `worker` = ANT), why a definition is
  fair. Naming a chunk is fine when the sentence teaches (`OCT is the calendar
  abbreviation and OPUS the composer's 'work'`) and re-narration when it redraws the
  blocks (`the referee tucked inside a stately walk: P(REF)ACE`). It is shown under
  **The trick** and must never be empty.
  **Open with the thing itself, never an appraisal of it**: no `A lovely/neat/classic
  ...`, no `Two instructions stacked: ...`, no `This is a ...`.
  **End on a fact, never a verdict on the sentence before**: `That switch is the whole
  difficulty` says nothing. If the second sentence has nothing new, write one.
  **Show the trap, not just the exit.** Where a clue has one dominant false path a
  competent solver genuinely takes first, name it and say what kills it: `"Flowers"
  wants to be the definition; it is the river.` A settled sentence about the clue,
  never your own working-out. Most clues have none; inventing one is worse than
  omitting it.
  **Name the picture out of the clue's own words.** Every "the X" in a walkthrough must
  be an X the reader can already see in the clue, not one that exists only in your
  image of it.
- Every puzzle is from a British paper and many readers are not British. Where a clue
  turns on knowledge absorbed from the street in Britain — a county, a motorway, a soap,
  a cricket position, a dead coin, a supermarket, a regiment, rhyming slang — say what
  the thing IS in the block `note` or `definitionFit` that needs it, in one clause:
  `THE OVAL is a London cricket ground`. Not for crossword conventions, which the app
  teaches itself, and not for what any dictionary reader already has ("the Thames").
- Never hedge, and never leave working-out in `walkthrough`, `definitionFit` or a block
  `note`. Those fields are the finished explanation. If it needs "somehow" or "no wait",
  the parse is wrong: find the one that needs no excuse, or leave the clue `null`.
- Never borrow another mechanism's signal words. "Aloud", "sounds like", "reportedly"
  mean homophone; "shuffle", "jumbled" mean anagram; "hidden" means extraction;
  "reversed" means turnaround. Used loosely they name a device this clue does not use,
  to the one reader who cannot yet tell the difference.
- `features` is data, not teaching; none of it is shown to a solver. Record what IS
  there: four honest nulls and falses are a usable row, one guessed `joke` is a poisoned
  one, and a `misdirectedWord` the setter never wrote is rejected. Report, never judge —
  `joke` asks whether a joke is present, not whether it is funny.

## Verify

`python3 tools/annotate_check.py <ID>` applies the file, validates it, audits it for
answer leaks and re-narrated walkthroughs, syntax-checks the puzzle and refreshes the
index, and prints everything wrong in one report. Repeat edit → run until `clean`.

- **One run, one edit pass.** Fix everything the report lists, then run again.
- **Run it on its own.** No `&&`, `;`, `rm` or piping — a compound command needs an
  approval this run cannot give and aborts having run nothing.
- **Never open `validate_annotations.py`.** For any line you cannot act on,
  `python3 tools/validate_annotations.py --explain <check-name>` prints that check's
  source and the comment above it; with no argument it lists the names. It answers for
  constants and helpers too.

## Do not commit

The calling script commits and composes its own message. `git` is not among the tools
this run is given.

<!-- REFERENCE-START — generated by tools/build_annotate_prompt.py -->

## Reference

Generated from the code that enforces it — do not edit by hand, and do not
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

- More than **2** `cryptic definition` clues in one puzzle; the second one already
  warns.
- A `walkthrough` over **60** words (over **45** warns).
- Blocks whose letters are not the answer's, blocks that hand the answer over in one
  lump where `pieces` takes it apart, and blocks out of answer order. Exempt from the
  letter count, because their blocks claim no letters: `deletion`, `substitution`,
  `cryptic definition`, `double definition`, `homophone`, `spoonerism`, `&lit` — which
  is what makes those types the easy way out of a clue you have not parsed.
- The same word used as a definition in more than **3** clues in one puzzle (exempt:
  `&lit`, `double definition`, `cryptic definition`).
- In `walkthrough`, `definitionFit` or a block `note` — hedges: `close enough` `don't
  ask` `for some reason` `hand-wave` `handwave` `if you squint` `jokingly` `somehow`;
  working-out left in: `actually:` `correct parse` `hold on` `ignore that` `let me
  reconsider` `let me try` `no wait` `no, wait` `not it either` `on second thought`
  `re-examine` `scratch that` `still wrong` `that is not it` `that's not it` `wait --`
  `wait—`.

<!-- REFERENCE-END -->
