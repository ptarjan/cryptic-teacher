# Annotation task for Claude Code

You are annotating one cryptic crossword for the Cryptic Teacher app in this
repository. The caller names the puzzle and the file holding its clues and answers;
annotate that one and no other. The ID is series plus number (`cryptic-30089`, `everyman-4165`), because every
series numbers from 1 and the number alone names nothing.

## What to produce

One file, `tools/_ann_<ID>.json`: a single object with a key for every entry id, and
`null` for a clue not done yet. A linked answer is annotated once, on its leader (the
entry with a `group`), with wordplay for the whole answer; every other light in the
group ("See 21") is `null`.

```json
{"1-across": { ...annotation... }, "5-across": { ...annotation... }, "12-across": null}
```

If the puzzle file lists `annotateOnly`, key only those entries: every other entry's
annotation is fixed, shown in `existingAnnotations` in the same shape as yours, and
the check refuses a change to it.

Write annotations only; do not write a script to produce them. Each entry's
`"solution"` is ground truth: your `wp` must produce exactly those letters, and if it
does not, the parse is wrong, so rethink it rather than stretch it. The exception is
a solution marked `(MODEL)`, a cold solve's guess: if no parse gives it and the clue
plainly gives another word, set `"answer"` to that word. The check accepts it only if
it agrees with every crossing and printed answer; correct a crossing `(MODEL)`
answer the same way if its clue gives that letter. Never ship a hedged hint for a
`(MODEL)` answer ("unconfirmed", "placeholder", "usually spelt" a near-twin): the
check refuses it and the answer is solved again, so leave the clue null instead.

The clue text is the source's, with one exception. When your copy's
`source.retrievedFrom` is `newspaper` or `book`, its clues are OCR of a scan, and a
letter can be misread ("judge" for "fudge"). When the answer and wordplay need a word
a letter or two from the one shown, give that entry
`"printedClue": ["<clue as printed, no count>", "OCR misread: <what the wordplay or answer needs>"]`;
the check files it and refuses it if more than 3 letters change. A clue that is
missing, or shown on two lights, is lost, not misread: make that entry `null`.

A clue the source shows exactly as printed whose anagram still cannot give the
answer is the setter's slip: give the entry
`"setterError": ["<fodder words as printed>", "<letters the anagram should give>", "<evidence>"]`,
write `wp` with the fodder as it should be, and say what is wrong in `explanation.walkthrough`.

When the wordplay plainly builds a real word a letter or two from a printed answer
that is not one (MINUSCULE where the grid prints MINISCULE), the key is misprinted:
annotate the real word and give the entry
`"answerTypo": ["<letters the wordplay builds>", "<evidence>"]`; the check puts it in
the grid, and refuses it if a crossing answer disagrees.

The check compares your definition, clue type and pieces (worked out from `wp`) with
what the puzzle's blog marked. A disagreement is a prompt to look, not an order:
bloggers slip too. Fix yours if the blog is right; if yours stands, give the entry
`"blogDisagree": ["<definition|type|blocks>", "<one sentence: why yours is right>"]`.

When your copy of the puzzle has a `scan`, that image is the printed page. Read it
for any clue that looks cut short, garbled, blank or wrong for its answer, and give
the entry `printedClue` as the page prints it, evidence `"Scan reads: <what the page shows>"`;
a clue read off the scan may differ by any number of letters.

## Order of work

- **Write early.** Put clues into the file a handful at a time: only what is on disk
  survives the run ending. Run the check (below) once every clue is in.
- **Solve in the order the crossings unlock**, not clue order. Skip a clue that resists
  and come back once its crossings are in: thinking longer without new letters does not
  produce new letters.
- **There is no word list.** `/usr/share/dict/words` is out of reach, and the other
  puzzles in `puzzles/` are not a dictionary; do not search them for fills.

## Schema

Each clue is one object. `wp` is the parse as one line in the grammar of the
Reference below; the check works out its letters at every step, and from it the clue
type, the link words, which operation each indicator signals and the pieces the app
shows, so you write none of those. Worked annotations close this file.

```json
{
  "def": "exact clue words that define the answer; [\"first\", \"second\"] for a double definition",
  "wp": "ins<in>([order]SORT, [Bird]TIT + [Chinese]CH + [woman]W)",
  "notes": {"<words as written in wp or def>": "why these words do this job here; none for a plain abbreviation"},
  "explanation": {
    "surface": "one sentence, 25 words max: what the clue pretends to be about",
    "walkthrough": "optional, 1-2 sentences, 45 words max: what the parse cannot show",
    "definitionFit": "one sentence, 30 words max: why the answer means the definition"
  },
  "features": {
    "misdirectedWord": "the one clue word, spelt as printed, whose surface sense is furthest from its job; or null",
    "joke": "\"pun\" (a word's second sense or sound), \"absurd\" (silly on purpose), or null",
    "answerInScene": "true/false: does the solution belong in the picture the surface paints?",
    "aptDefinition": "true/false: is the definition fresh or witty rather than a dictionary synonym?"
  }
}
```

- **No note for a plain abbreviation** (`[with]W`, `[folio]F`): the app shows the
  dictionary's abbreviation from its table, and such a note is dropped. Write one only
  when it adds something (`C is the cricket abbreviation for caught`).
- **Every clue word has one job**: in `def`, in a `[leaf]`, or in an `<indicator>`
  placed right after the operation it signals. Words left over are link words, worked
  out for you; an indicator you leave out of `wp` becomes a link word the check questions.
  Copy clue words exactly; `[in#2]` is the clue's second "in".
- A leaf's letters come before any operation (`rev([papers]ID)` makes DI), and a
  charade is in answer order whatever the clue's order: "after", "under" are indicators on the `+`.
- **Notes** are keyed by the words as written in `wp` or `def` (a repeat `#2`, a bare
  piece by its letters). Every indicator and every leaf with letters gets one. A
  definition gets one only where it disagrees with the answer in number or part of
  speech; in a double definition each definition's note says what that sense means.
- A **double definition** is two `def`s and no `wp`. A **cryptic definition** is
  `def` the whole clue and `wp` `cd([surface words], [setter's words])`: the clue in
  the pieces its two readings turn on, each with a note, no letters. An **&lit** has
  `"andLit": true`, `def` the whole clue and the whole clue's wordplay.
- `answer` only to correct a `(MODEL)` answer, or to spell one with an apostrophe or
  accent (`"CAT-O'-NINE-TAILS"`); the display answer is otherwise worked out.

An entry with an `alteration` goes into the grid changed, as its puzzle's preamble says.
Write `alteration` (`{"from": "...", "steps": [{"op": "reversal"}]}`) in its object here and
apply moves it onto the puzzle's entry; never edit the puzzle file by hand. The clue's
definition and wordplay give `alteration.from`, and its `steps` turn that word into
the solution: `wp` builds `from`.

Letters the puzzle's preamble supplies are a bare piece with no clue words: `[can]LOO + E`.

When the preamble hides a letter per clue that spells a phrase, give each such clue
`"hiddenLetter": {"kind": "extra", "letter": "L"}`. Kinds: `extra` (the wordplay gives it
beyond the answer: write that step `del(<the part>, L)` with no indicator), `omitted`
(a bare `L` piece supplies it), `misprint` (add `"printed"`, the wrong letter, and
`"at"`, its offset in the clue; `letter` is the correct one), `clue` (a letter of the
clue itself, with `"at"`). Beside the entry ids, give the phrase: `"messages":
[{"text": "SUM TO FINAL", "kind": "omitted", "direction": "across", "order": "clues",
"placement": "belowGrid"}]`. `direction` only when one direction spells it, `placement`
only when the preamble says where it is written.

## Taste

The check below enforces the mechanics and explains each rule when it is broken. These
it cannot see. `STYLE.md` holds the product feedback behind them; where the two
disagree, it wins.

- The definition must substitute for the answer in a sentence: same part of speech,
  same inflection. Say the swap out loud. This is the most common mistake.
- A link word joins and says nothing else. Don't borrow another mechanism's signal
  words in any prose field: "aloud" means homophone, "shuffle" anagram, "hidden"
  extraction, "reversed" turnaround.
- `explanation.surface` is the picture, not a paraphrase and no mechanics: `Behaved antisocially
  and gave birth` is one person's bad week. A clue of four or more words has one unless
  it is a pure double or cryptic definition, even a clue that reads as bare mechanism.
- `explanation.walkthrough` says only what the parse cannot: why the surface misleads, a convention
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

It translates and applies the file, validates it, audits it, and prints everything wrong
in one report, each line saying what to do; a `wp` that does not give the answer names the
part that breaks. Its messages name the stored fields your `wp` becomes (a `block` is a
leaf). Fix everything it lists in one edit, run it again, and stop the moment it says
`clean`: end with one short line, with no summary of your work and no further pass. What
it prints under "worth knowing now" is advice, not a failure.

Four first runs in ten fail, most often on these rules. Get them right first time:

- `definitionFit` needs 25+ characters and a content word that is in neither the
  definition nor the answer. Name the relation (synonym, example, crossword-only
  sense, idiom); don't read the definition back with the answer in it.
- An indicator's note needs 25+ characters and words beyond the indicator's own: why
  these words signal that operation in this clue, not what the device does in general.
  Its rung comes before the pieces, so it never names a piece's letters or the answer:
  `"returning means the word rats is read backwards"`, not `"returning means RATS becomes STAR"`.
- No note may contain the answer. Write about the clue words; the walkthrough spells it.
- A cryptic definition's `cd()` has 2+ leaves, none with letters, and no note that
  spells the answer.
- `features.misdirectedWord` is one word, copied exactly as printed in the clue.

- To change many clues, Write `{"8-down": {"field": value}}` to a file and add
  `--patch <file>` to the check; a heredoc or fix script is refused. Each field is
  replaced and null removes it, except `notes`, merged note by note.
- Run it as a single command: no `&&`, `;`, pipes or `rm`. A compound command needs an
  approval this run cannot give, and aborts having run nothing.
- To take back hints you would not stand by, run the check with `--withdraw "<why>"` and
  stop: the puzzle file is put back for you and nothing you wrote ships. Never use git.
- Don't open `validate_annotations.py`. For a line you cannot act on,
  `python3 tools/validate_annotations.py --explain <check-name>` prints that check.

<!-- REFERENCE-START — generated by tools/build_annotate_prompt.py -->

## Reference

Generated from tools/wordplay.py, the parser `wp` must satisfy; do not read it to check this.

### The wordplay grammar

```
    [clue words]LETTERS   a leaf: these clue words give LETTERS, before any
                          operation on them (papers gives ID; rev makes DI)
    [clue words]          a leaf whose letters are the words as written
                          (anagram fodder, hidden-word text)
    [in#2]                the second "in" in the clue; #n picks a repeat
    LETTERS               letters with no clue words (a preamble's piece, or
                          the letters a del/sub indicator names: del(x, H))
    A + B                 a charade, in answer order
    op<indicator>(...)    an operation; <indicator words> follow the op they
                          signal, one <...> per phrase; `+<under>` is an
                          indicator on the charade
    ana(x)                anagram of x's letters (the answer slice decides order)
    rev(x)                x backwards
    ins(outer, inner)     inner put inside outer (the answer decides where)
    del(from, removed)    removed taken out of from (the answer decides where)
    hid(x)                letters hidden in x's words: hid([say no before]YNOBE),
                          or hid([say no before]) to let the answer pick them
    sound(x, SPELT)       x sounds like SPELT, the letters entered
    spoon(a, b)           a and b with their first consonants swapped;
                          spoon(a, b, SPELT) when the swap is by sound
    sub(x, OLD, NEW)      OLD in x replaced by NEW
    cyc(x)                x with letters moved from one end to the other
    pal(x)                x, which reads the same backwards; pal() with no x
                          when the answer itself is all the wordplay
    first(x) last(x) middle(x) outer(x) alt(x) regular(x) nth(n)(x)
                          letters picked from x's words: first letter (or
                          each word's first), middle letter(s) or all but the
                          ends, first and last, alternate letters, every
                          2nd/3rd, the nth
    cd([words])           cryptic definition: the words, no letters
A double definition has no wordplay: two definitions and no expression.
```

### Worked annotations

Rendered from the corpus in the shape you write; each passes every check.

quiptic-619 11-across, "Fake folio made by a conservative is libellous" (10), solution DEFAMATORY:

```json
{"11-across": {
  "def": "libellous",
  "wp": "ana<Fake>([folio]F + [made] + [a]) + [conservative]TORY",
  "notes": {"Fake": "something fake is invented or concocted, so these letters are reworked into a new arrangement", "made": "taken as written", "a": "taken as written", "conservative": "a Tory is a member of the UK Conservative Party"},
  "explanation": {"surface": "A forged document produced by a Tory politician is defamatory.", "walkthrough": "'Fake' looks like an adjective describing the folio, but it is the anagram signal. Tory is the everyday name for a member of Britain's Conservative Party.", "definitionFit": "Libel is written defamation, so a libellous statement is one that damages a reputation falsely."},
  "features": {"answerInScene": true, "aptDefinition": false, "misdirectedWord": "Fake"}
}}
```

quiptic-619 10-across, "Excellent penalty!" (4), solution FINE:

```json
{"10-across": {
  "def": ["Excellent", "penalty"],
  "notes": {"Excellent": "first meaning: very good, of high quality", "penalty": "second meaning: a sum of money paid as punishment"},
  "explanation": {"walkthrough": "The exclamation mark makes it sound like cheering a penalty in a match; the two words are separate meanings of one short word.", "definitionFit": "The word works both as an adjective for high quality and as a noun for a monetary punishment imposed by a court."},
  "features": {"answerInScene": false, "aptDefinition": false, "joke": "pun", "misdirectedWord": "penalty"}
}}
```

<!-- REFERENCE-END -->
