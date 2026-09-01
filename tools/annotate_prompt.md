# Annotation task for Claude Code

You are annotating a broadsheet cryptic crossword for the Cryptic Teacher app in this
repository — a Guardian daily or Quiptic, the Observer's Everyman, or the Independent's
daily. The puzzle file's `series` and the tools/series.py table say which; the house
styles differ a little but the annotation schema below is identical for all of them.
The target puzzle file is `puzzles/<ID>.js`, where the ID is the series and the
number together — `cryptic-30089`, `everyman-4165`, `quiptic-1395`,
`independent-12438`, `indysunday-1903`. Every paper numbers from its own 1, so the number alone
does not name a puzzle. The caller names the file to annotate; that file is the
target and picking a different one is never right.

## What to produce

One JSON file, `tools/_ann_<ID>.json`, holding a single object keyed by entry id:

```json
{"1-across": { ...annotation... }, "5-across": { ...annotation... }, "12-across": null}
```

Then apply it:

```
python3 tools/apply_annotations.py <ID>
```

That reads the file, checks the ids against the puzzle, writes the annotations into
`puzzles/<ID>.js` and runs the validator. Every entry needs a key. A key set to `null`
says you could not solve that clue, which the rules below allow; leaving a key out is an
error, because forgetting a clue and giving up on one are not the same thing and the
file cannot tell them apart on its own.

Do not write a script to do this. Annotation runs used to hand-roll a throwaway Python
file per puzzle — five hundred lines of dict wrapped in forty of scaffolding, re-typed
every night, and the scaffolding is where the mistakes were: hand-copied JSON markers,
hardcoded paths, a provenance stamp naming a module the script never imported. The
annotations are the work. Write only those.

The published solution is already in each entry's `"solution"` field — use it as ground
truth, and make sure your parsing actually produces those letters.

Annotation schema (see `puzzles/cryptic-30066.js` for 28 worked examples):

```json
{
  "type": "anagram | charade | container | hidden word | homophone | reversal | deletion | double definition | &lit (combinations joined with ' + ')",
  "answer": "DISPLAY FORM (spaces/apostrophes/hyphens ok; letters must equal the solution)",
  "definition": "exact substring of the clue text",
  "definition2": "second definition, only for double definitions",
  "definitionNote": "only when the definition genuinely disagrees with the answer in number or part of speech: a sentence explaining why the setter is allowed it",
  "indicators": ["exact substring", "..."],
  "indicatorNotes": {"exact substring from indicators": "REQUIRED, one sentence: why THIS word means that instruction"},
  "linkWords": ["exact substring joining definition to wordplay, e.g. 'to locate'"],
  "blocks": [
    {"clueFragment": "exact words from the clue", "gives": "LETTERS", "note": "why"},
    {"clueFragment": "for homophones/spoonerisms", "soundsLike": "WHAT YOU SAY ALOUD", "gives": "HOW IT IS SPELT", "note": "why"}
  ],
  "walkthrough": "1-2 sentences, 45 words max: what the blocks CANNOT show. Friendly teaching tone.",
  "definitionFit": "REQUIRED. One sentence, 30 words max: why the ANSWER means the DEFINITION.",

  "pieces": ["CHUNKS", "THAT", "CONCATENATE", "TO", "THE", "ANSWER"],
  "anagram": {"fodder": "LETTERS WHOSE MULTISET EQUALS THE ANSWER"},
  "subAnagrams": [{"fodder": "SUIT", "gives": "TISU"}],
  "subReversals": [{"from": "MAC", "to": "CAM"}]
}
```

Rules:
- FIRST read `STYLE.md` at the repo root and follow every rule in it. It is the
  accumulated product feedback; it overrides habit. In particular, `type` must
  honestly name EVERY mechanism used, joined with " + " (e.g.
  `charade + alternate letters`), using only the controlled vocabulary in the
  Reference section at the end of this file. That section is generated from the
  code that enforces it, so it is current and you do not need to open `app.js` or
  the validator to check it. If a clue truly needs a new type part, add it to
  `TYPE_PARTS` in the validator, to STYLE.md, and to `TYPE_BLURBS` and a family in
  `FAMILIES` in `app.js` together, then rerun
  `python3 tools/build_annotate_prompt.py` — the smoke test fails a part with no
  family.
- `cryptic definition` is capped at TWO per puzzle and the validator ERRORS above that
  (`MAX_CRYPTIC_DEFINITIONS`). It is the only type with no checkable wordplay, so a third
  one almost always means you gave up on a clue: go back and find the charade, hidden word
  or container it is hiding. Treat the SECOND one the same way — the validator now warns
  at exactly two, because it is the type you can reach for without solving anything, which
  makes reaching for it twice a measure of how much you gave up rather than a property of
  the puzzle. Before you type a clue `cryptic definition`, spend one more pass hunting for
  a container: "Periods on horseback where British king into himself?" looks like a whole-
  clue definition of CHUKKAS and is really CHAS (the king himself) around UK + K. Writing
  the whole clue into `definition` and the whole answer into one block is not an
  annotation, it is a note saying you could not do it — and it is invisible to every other
  check, since a cryptic definition claims no letters and so can contradict nothing. If
  you truly cannot solve the clue, leave it `null` and say so. That is honest and someone
  will finish it; a cryptic definition that isn't one is a wrong answer nobody can find.
  Before you settle for `null`, though, look it up — you have `WebSearch` and `WebFetch`,
  and Guardian and Independent puzzles are blogged clue by clue at fifteensquared.net
  (search `fifteensquared <paper> <number>`; the comments often carry the parsing the
  blogger missed). Two rules bound this. Reach for it only once a clue has actually beaten
  you, because reading the blog first turns annotating into transcription and you will
  stop seeing the mechanisms. And take only the mechanism: the blocks, walkthrough and
  definitionFit are written from scratch, in this file's voice, teaching in rungs — the
  blog's prose is someone else's and it explains to a solver who already knows the answer. If you are WRITING clues rather than annotating them (see
  `tools/AUTHORING.md`), the same cap is the rule that keeps a funny sentence from
  replacing the mechanism — a clue needs both, and a funny sentence is much easier to find
  than a funny mechanism. Related: an indicator that reads as a visible instruction
  (`a bit of`, `in front`, `turned`, `rebuilt`) is a mechanism narrated, not hidden.
- When a clue genuinely IS a cryptic definition, its `blocks` still have to teach something,
  and the validator now ERRORS if they do not. **No block may carry `gives`** — a cryptic
  definition yields no letters from any fragment, so a `gives` is always the whole answer
  wearing a block's clothes, and the blocks rung is shown before the walkthrough. **At least
  two blocks** — one block spanning the whole clue only restates the clue. What a cryptic
  definition splits into is not letters but readings: one block for the sense the surface
  pushes you towards, one for the sense the setter meant. 1392 22A "Might this keep you to
  time?" (WATCHSTRAP) had a single block reading the whole clue → WATCHSTRAP, so hint 3 of 4
  charged a learner a hint and handed them the answer, one rung after hint 2 had told them
  there was no wordplay to find (Paul, 2026-08-10). Written properly it is "keep you to time"
  = not "make you punctual" but holding something against you, plus "Might this" = the answer
  is the object itself. Same shape as the good ones already in the corpus: 1389 26A NUDISM,
  30039 10A VANITY, 30039 21A NINETEENTH.
- `definition`, `definition2` and every string in `indicators` MUST occur verbatim in the
  clue (match the exact characters — Guardian clues use curly apostrophes `’` and en
  dashes `–`, Independent clues use straight `'` and hyphens, so copy from the file
  rather than retyping). Independent clues may also contain `<i>` tags around a title
  or a foreign word; that markup is part of the clue string, so a definition that
  spans it has to include it.
- Do not point at the surface picture with a definite noun phrase you never drew.
  "The impromptu band keeps both looking innocent" was the closing sentence of a
  walkthrough that had never mentioned a band, and "both" was two instructions a
  sentence and a half earlier ("this doesn't sound natural", 4096 14D IRRITANTS,
  2026-08-17). The reader is holding the clue, not your image of it: name the
  picture out of the clue's own words — "a sitar and a tin whistle sound like a
  band" — and say what it does. Every "the X" in a walkthrough must be an X the
  reader can already see.
- Every indicator needs an `indicatorNotes` entry, keyed by the identical string.
  The app already says what an anagram indicator DOES — that sentence is the same on
  every anagram in the corpus and it is not worth a hint. The note is the part that
  is only true here: which sense of the word carries the instruction. "'stable? No'
  means unstable, and something unstable will not stay in the order it is given"
  (4096 20A RENOVATOR), not "'stable? No' is the anagram indicator". A note made
  only of words already in the indicator is rejected, as is one under 25 characters.
  It renders on rung 3, before the answer, so it must not name the answer.
  Note every indicator or none: once all of them are noted the app drops its generic
  wording and the notes ARE rung 3, so a clue one note short keeps the filler.
- Provide `pieces` for charades/containers/deletions (the final letter chunks in answer
  order) or `anagram.fodder` for anagrams (including any extra letters joined in). Use
  `subAnagrams`/`subReversals` for embedded steps. Double definitions, homophones and
  hidden words need neither (hidden answers are checked against the clue letters).
- A homophone or spoonerism MUST name the word you say aloud, in a `soundsLike` field
  on the block that does the sounding. The validator errors without one, and errors if
  `soundsLike` has the same letters as `gives` (that is a spelling, not a sound). The
  sounded word is the entire mechanism, so a block that jumps a fragment straight to
  the answer has taught nothing: "Cockney mob loudly" → OARED is `soundsLike: "’ORDE",
  gives: "OARED"`, with the note carrying the step BEFORE the sound — a mob is a HORDE
  and a Cockney drops the aitch. Where another mechanism feeds the homophone, give it
  its own earlier block; do not smuggle two operations into one arrow.
- For linked entries (a `group` with several ids, e.g. "1-across"/"9-across" where one
  clue reads "See 1"), put the full annotation on the FIRST entry of the group with
  `"coversGroup": true`, and give the other entries `{"linkedTo": "<first-id>"}`.
- The `definition` must be SUBSTITUTABLE for the answer: same part of speech, same
  inflection. Say the swap out loud before you settle on it — a plural answer needs a
  plural definition, an `-ing` answer an `-ing` definition, a verb a verb. This is the
  single most common annotation mistake; the validator warns on the mechanical cases.
- Account for EVERY content word of the clue. Each one must sit inside the definition,
  inside an indicator, inside `linkWords`, or inside a block's `clueFragment`. A leftover
  word means you have missed a piece of wordplay (30067 13A dropped `state` = CAL and
  nobody noticed). It is always one of four things, so decide which: a **link word**
  ("indicating", "to locate" — no letters, put it in `linkWords`); an **indicator** you
  overlooked (anything saying where a piece goes, e.g. "facing"); a **letter you never
  named** (a deletion needs a block for the letter removed — "hard" = H — not just for the
  word it came out of); or **genuine surface padding**, which still gets a block with an
  empty `gives` and a note saying it is surface only. That fourth option exists only when
  you are ANNOTATING a published clue. If you are WRITING one (`tools/AUTHORING.md`), it
  is forbidden: "a good cryptic clue doesn't have anything superfluous which isn't
  directly part of the wordplay — it should be exactly two pieces, definition, optional
  joinery and wordplay". An empty `gives` in an authored puzzle is a validator ERROR
  (`check_two_pieces`), so rewrite the clue without the word, or work out which of the
  other three jobs it is really doing — a word can be an indicator hiding in plain
  description ("There's a mole in" = something is concealed inside) or joinery that only
  holds the sentence up ("There's").
- List the BLOCKS in the order the ANSWER reads, not the order the clue reads. The app
  renders them top to bottom, so they are the build a learner follows. A charade clued
  "Peas ... sweet" for SWEET PEAS gets blocks SWEET then PEAS, each `clueFragment` still
  pointing back at wherever its words sit in the clue. Same letters in the wrong order
  passes every multiset check and still makes the learner do the reassembly the
  annotation exists to show; `check_blocks_in_answer_order` now ERRORS on it. This
  applies to pure charades — where a container, reversal or rotation is in the mix, the
  blocks are assembled before the positional step and that order is the right one.
- The `walkthrough` is short, because the blocks already did the work: "when you
  basically give the whole answer in the building blocks you don't need to have the full
  walkthrough". Do not re-narrate fragment → letters. Write only what the blocks cannot
  show — why the surface misleads, the joke in one clause, a convention the solver may
  not know (`ER` = Queen, `worker` = ANT), or why a definition is fair. One or two
  sentences is normal; over 45 words the validator warns (authored puzzles). It must
  never be empty: the app always renders the walkthrough rung.
  Naming a letter chunk is not automatically re-narration — the test is what the
  sentence is FOR. `OCT is the calendar abbreviation and OPUS the composer's 'work'`
  teaches two conventions the solver keeps forever, and needs the capitals. `The
  official is a sports referee, tucked inside a stately walk: P(REF)ACE` draws, in
  words, the picture the blocks already drew an inch higher. Teach a convention, name a
  joke, explain why a definition is fair — but never spend the walkthrough narrating
  which piece goes inside which. `python3 tools/find_renarration.py` lists the current
  candidates, worst first; it deliberately does not gate, because no lexical rule
  separates those two sentences and every version that tried was wrong half the time.
- Every puzzle here is from a British paper and a large share of the readers are not
  British. When a clue turns on knowledge a British solver absorbs from the street and
  nobody else does — a county, a motorway, a bank holiday, a soap opera, a cricket
  position, a coin that stopped circulating, a supermarket, a public-school word, a
  regiment, a Cockney or rhyming-slang sense — say what the thing IS in the block `note`
  or `definitionFit` that needs it. One clause: `THE OVAL is a London cricket ground`,
  `a BOB was a shilling`. This is not the same as a crossword convention (`ER` = Queen,
  `worker` = ANT), which the app teaches in its own right; this is general knowledge that
  only looks general from inside Britain. Do not gloss what a dictionary reader anywhere
  already has — "London", "the Thames", "Shakespeare" need nothing.
- Show the trap, not just the exit. The obvious wrong reading is the thing the solver
  actually has in their head when they reach for a hint, and a walkthrough that goes
  straight to the right parse never meets them there. Where a clue has one dominant false
  path — a word that looks like an anagram indicator and isn't, a definition that looks
  like it ends three words earlier, a surface that reads as a container when it is a
  charade — name it and say what kills it: `"Flowers" wants to be the definition; it is
  the river.` Two conditions. It must be the reading a competent solver would genuinely
  take first, not a strawman. And it must be a settled sentence about the CLUE — never
  your own working-out about your own parse. `BACKTRACKS` in the validator ERRORS on
  "no wait", "actually:", "let me reconsider" and the rest, and that stands: the false
  start you show is the solver's, written down once and already resolved, not a
  transcript of yours. Only where such a path exists — most clues have none, and
  inventing one is worse than omitting it.
- `definitionFit` is REQUIRED on every clue: one sentence saying why the ANSWER means the
  DEFINITION. This is the half of a cryptic that isn't mechanical. The blocks spell the
  answer out of the wordplay and the definition rung points at the words, but nothing
  else ever joins the two ends, and that link is where the vocabulary of cryptics
  actually lives. Name the RELATION, don't just restate: a plain synonym, a definition by
  example ("Alsatian" defines a DOG only as an instance of one), a sense of the word that
  survives mainly in crosswords, a technical or regional use, a whole-phrase idiom. Good:
  `"a crawler → ARMY ANT: army ants move in a crawling column, and 'crawler' also carries
  the sense of a grovelling flatterer the surface is pointing at."` Bad: `"an army ant is
  a crawler"` — that is the definition read backwards, and teaches nothing. For a double
  definition, cover BOTH senses; for `&lit`, say why the whole clue reads straight. If the
  honest answer is "it's an everyday synonym", say which sense and why it isn't the first
  one that comes to mind. It is separate from `definitionNote`: the note justifies a
  definition that DISAGREES with the answer grammatically (number, part of speech);
  `definitionFit` explains the meaning, and every clue has one. Over 30 words the
  validator warns.
- If the definition genuinely does NOT agree with the answer ("Lousy payment" = PEANUTS,
  "hearing aid" = EARPHONES), do not stretch it and do not ignore it: add a
  `definitionNote` explaining the mismatch to the learner. The validator requires a real
  sentence, and the note is shown in the app under the definition rung.
- Never hedge in a `walkthrough`. Words like "jokingly", "somehow", "if you squint" are a
  validator ERROR: if the explanation needs a fudge, the parse is wrong. Go back and
  find the parse that needs no excuse.
- Never leave your working-out in a `walkthrough`, `definitionFit` or block `note`. Those
  fields are what the learner reads; they are the finished explanation, not the thinking
  that produced it. "No wait—", "Still wrong.", "Actually:", "Correct parse:" and a
  walkthrough over `WALKTHROUGH_HARD_MAX` words are validator ERRORS. Work the clue out
  for as long as you need, then write the settled sentence. If you cannot settle it,
  leave the clue unannotated and say so — that is better than publishing an argument.
- Never borrow another mechanism's signal words to explain this one. "Aloud", "out loud",
  "sounds like", "reportedly", "spoken" mean homophone; "shuffle", "anagram", "jumbled"
  mean rearrangement; "hidden", "buried" mean extraction; "reversed", "backwards" mean
  turnaround. Used loosely — "found in says so out loud", meaning *announces itself* —
  they name a device this clue does not use, to the one reader who cannot yet tell the
  difference. The prose is fine English and wrong anyway. Say what the clue actually does.
- The BLOCKS are the parse, not a sketch of one. They are what the app renders, so three
  things are checked and all three are things a wrong parse gets wrong: their letters must
  add up to exactly the answer's letters (`check_blocks_account_for_answer` — deletions and
  substitutions excepted, since they name letters that go away); if `pieces` takes the
  answer apart into chunks, the blocks must take it apart the same way rather than handing
  the whole answer over in one lump (`check_blocks_decompose` — "Two types of earth" >
  SODDEN names the charade without doing it); and every block that claims letters needs a
  `note` saying why those words give those letters (`check_blocks_carry_notes`). That note
  is the teaching, and skipping it is how an invented block hides.
- The definition's words are NOT available as wordplay. A block whose `clueFragment`
  repeats a word the `definition` already claimed is the annotation eating its own tail,
  and its worst form passes every other check: `definition: "Hard rock"` with a block
  `"Hard rock" > HORSE` says the answer is the answer. If you cannot see the wordplay,
  the clue is unsolved — leave it `null` and say so, which the instructions above already
  allow. Do not describe the clue and call it a parse. `check_definition_not_fodder`
  warns per clue (a setter occasionally reuses the word on purpose: "Nobody drunk now
  nobody drinks!") and ERRORS once several clues in one puzzle do it.
- Do not guess: if a parsing doesn't produce the answer's letters exactly, it is wrong —
  rethink it. Consult the setter's usual tricks; check fifteensquared.net if reachable.

## Verify (mandatory)

`apply_annotations.py` already ran this; run it again after any fix:

```
python3 tools/validate_annotations.py <ID>
```

Iterate until it reports `N/N annotated — OK` with no ERROR lines (warnings about block
fragments are acceptable but worth fixing). Fix by editing `tools/_ann_<ID>.json` and
re-running `apply_annotations.py` — that file stays put for exactly this. Then refresh
the index:

```
python3 tools/fetch_puzzle.py --reindex
node --check puzzles/<ID>.js
```

## Do not commit

The calling script commits, and composes its own message. `git` is not in the
tools this run is given, so trying is a wasted turn.

<!-- REFERENCE-START — generated by tools/build_annotate_prompt.py -->

## Reference

Generated from the code that enforces it — do not edit by hand, and do not go
and read app.js or the validator to check any of it. If a clue needs something
that is not here, add it to the source table and rerun
`python3 tools/build_annotate_prompt.py`.

### The controlled vocabulary for `type`

Join parts with ` + ` and name EVERY mechanism the wordplay uses. Each part
belongs to exactly one family; the family is what the app shows on rung 1, so a
compound type's family is decided by the FIRST row below that matches it.

**Definitions only** — No letter mechanics at all — nothing is anagrammed, hidden or spelled out. Either two plain definitions sit side by side, or one sly one describes the answer the long way round.

  `cryptic definition` `double definition`

**&lit** — The whole clue does double duty: read it once as a definition, then read the very same words again as wordplay.

  `&lit`

**Rearrangement** — Letters handed to you in the clue get shuffled into the answer. Find the fodder and count it against the enumeration.

  `anagram` `cycling`

**Sound** — The wordplay describes how the answer sounds rather than how it is spelled.

  `homophone` `spoonerism`

**Charade** — The answer is built from pieces laid end to end, each clued separately — read the wordplay left to right.

  `charade`

**Alteration** — A piece of the wordplay is changed rather than just joined on: put inside something, turned around, or trimmed.

  `container` `deletion` `palindrome` `reversal` `substitution`

**Extraction** — The answer's letters are already sitting in the clue in order — the job is working out which ones to pick out.

  `alternate letters` `first letter` `first letters` `hidden word` `last letter`
  `last letters` `middle letter` `middle letters` `outer letters` `regular letters`
  `second letter` `second letters`

### What the validator rejects

- More than **2** `cryptic definition` clues in one puzzle is an ERROR; the second one
  already warns.
- A `walkthrough` over **60** words is an ERROR, over **45** a warning (authored
  puzzles).
- More than **2** clues per puzzle whose type is one of `deletion`, `substitution`,
  `cryptic definition`, `double definition`, `homophone`, `spoonerism`, `&lit` — these
  are the types whose blocks need not add up to the answer, so they are the easy way
  out.
- More than **2** clues whose blocks hand over the whole answer in one lump instead of
  taking it apart the way `pieces` does.
- More than **0** clues whose blocks are not in answer order.
- The same word used as a definition in more than **3** clues in one puzzle (exempt:
  `&lit`, `double definition`, `cryptic definition`).

Words that are an ERROR anywhere a learner reads — `walkthrough`,
`definitionFit`, block `note`:

- hedges:
    `close enough` `don't ask` `for some reason` `hand-wave` `handwave`
    `if you squint` `jokingly` `somehow`
- working-out left in:
    `actually:` `correct parse` `hold on` `ignore that` `let me reconsider`
    `let me try` `no wait` `no, wait` `not it either` `on second thought` `re-examine`
    `scratch that` `still wrong` `that is not it` `that's not it` `wait --` `wait—`

Filler an `indicatorNotes` entry may not be made of on its own:

  `a` `about` `after` `all` `an` `and` `are` `as` `at` `be` `been` `before` `being`
  `but` `by` `can` `did` `do` `does` `for` `from` `get` `gets` `give` `gives` `go`
  `goes` `got` `had` `has` `have` `having` `he` `her` `him` `his` `i` `if` `in` `into`
  `is` `it` `its` `made` `make` `makes` `may` `me` `might` `must` `no` `not` `of`
  `off` `on` `one` `or` `out` `over` `s` `she` `so` `some` `that` `the` `their` `them`
  `they` `this` `to` `up` `us` `was` `we` `were` `when` `will` `with` `would` `you`

<!-- REFERENCE-END -->
