# Annotation task for Claude Code

You are annotating one cryptic crossword for the Cryptic Teacher app in this
repository. The caller names the puzzle and the file holding its clues and answers;
annotate that one and no other. The ID is series plus number (`cryptic-30089`,
`everyman-4165`): every series numbers from 1, so the number alone names nothing.

## What to produce

One file, `tools/_ann_<ID>.json`: one object with a key for every entry id, `null` for
a clue not done yet. A linked answer is annotated once, on its leader (the entry with a
`group`), with wordplay for the whole answer; every other light in the group ("See 21") is `null`.

```json
{"1-across": { ...annotation... }, "5-across": { ...annotation... }, "12-across": null}
```

- `annotateOnly` in the puzzle file: key only those entries (no `null` for the rest). Every other annotation is
  fixed and the check refuses a change to it (those in a group you write are shown in
  `existingAnnotations`, in your shape).
- An entry under `flagged` has a hint and the reason it is suspect: write a new
  annotation that fixes that (the old one stays until yours validates, so never answer
  it with null).
- An entry under `draftAnnotations` has a draft hidden word that a program checked
  against the answer (`def`, `wp`, `notes`). Write it with those three as they are, plus
  the `explanation` (`surface`, `definitionFit`) and `features` the draft lacks. Change
  the draft only when you can show it is wrong (definition is another part of the clue,
  fodder or indicator misread, a reversal missed), and say why in `explanation.walkthrough`.
- Write annotations only; no script. Each `"solution"` is ground truth: `wp` must
  produce exactly those letters, else rethink the parse rather than stretch it. A solution
  marked `(MODEL)` is a cold solve's guess: if no parse gives it and the clue plainly
  gives another word, set `"answer"` to that word (accepted only if it agrees with every
  crossing and printed answer; correct a crossing `(MODEL)` answer the same way). Never
  ship a hedged hint for one ("unconfirmed", "placeholder", "usually spelt" a near-twin):
  it is refused and solved again, so leave the clue null.
- When `source.retrievedFrom` is `newspaper` or `book`, clues are OCR and a letter can
  be misread ("judge" for "fudge"). If the answer and wordplay need a word a letter or
  two off, give `"printedClue": ["<clue as printed, no count>", "OCR misread: <what the wordplay needs>"]`
  (refused beyond 3 letters changed). A clue missing, or shown on two lights, is lost: `null`.
- A `scan` is the printed page. For a clue that looks cut short, garbled, blank or wrong
  for its answer, give `printedClue` as the page prints it, evidence
  `"Scan reads: <what the page shows>"`; any number of letters may differ.
- A clue shown exactly as printed whose anagram still cannot give the answer is the
  setter's slip: `"setterError": ["<fodder words as printed>", "<letters the anagram should give>", "<evidence>"]`,
  `wp` with the fodder as it should be, and what is wrong in `explanation.walkthrough`.
- When the wordplay plainly builds a real word a letter or two from a printed answer
  that is not one (MINUSCULE where the grid prints MINISCULE), annotate the real word
  and give `"answerTypo": ["<letters the wordplay builds>", "<evidence>"]` (refused if a crossing disagrees).
- The check compares your definition, clue type and pieces (from `wp`) with the puzzle
  blog's. A disagreement is a prompt to look, not an order: bloggers slip too. Fix yours
  if the blog is right; if yours stands, give
  `"blogDisagree": ["<definition|type|blocks>", "<one sentence: why yours is right>"]`.

## Order of work

Write a handful of clues at a time: only what is on disk survives the run ending. Run
the check once every clue is in. Solve in the order crossings unlock; skip a clue that
resists and return when its crossings are in (thinking longer adds no letters). There is
no word list: `/usr/share/dict/words` is out of reach and other puzzles are not a dictionary.

## Schema

Each clue is one object. `wp` is the parse as one line in the grammar of the Reference
below; the check works out its letters at every step, and from it the clue type, link
words, indicator operations and pieces, so you write none of those.

```json
{
  "def": "exact clue words that define the answer; [\"first\", \"second\"] for a double definition",
  "wp": "ins<in>([order]SORT, [Bird]TIT + [Chinese]CH + [woman]W)",
  "notes": {"<words as written in wp or def>": "why these words do this job here; every indicator and every leaf with letters"},
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

**Parsing.**
- Every clue word has one job: in `def`, in a `[leaf]`, or in an `<indicator>` right
  after the operation it signals. Leftover words are link words, worked out for you; an
  indicator you leave out becomes a link word the check questions. Copy clue words
  exactly; `[in#2]` is the second "in". Each `[leaf]`, `<indicator>`, `def` and note key
  is one unbroken run of the clue as printed, neighbouring words with nothing between:
  words that are in order but have other words between them ("takes" ... "for" in
  "Relative takes a bit of tweed for top of pillbox hat") are two pieces, never one
  quote, or the check refuses it as "not in the clue".
- A leaf's letters come before any operation (`rev([papers]ID)` makes DI). A charade
  is in answer order whatever the clue's order: "after", "under" are indicators on the `+`.
- Every clue piece that gives letters is a term of the wordplay: leave none out, even a
  short query phrase ("look up where?" supplying part of AUSTRIA). Pieces side by side
  are a charade (`+`), not `ins`; `ins` only where one piece is cut open by another.
- Selection ops (first, last, middle, outer, alt, hid...) take the words picked FROM,
  never the pick. Over several words use a comma list, one indicator:
  `first<heads of>([a], [b], [c])`, not `first([a] + [b] + [c])`.
- `answer` only to correct a `(MODEL)` answer, or to spell one with an apostrophe or
  accent (`"CAT-O'-NINE-TAILS"`).

**Notes** are keyed by the words as written in `wp` or `def` (a repeat `#2`, a bare
piece by its letters). Every indicator and every leaf with letters gets one, in the
FIRST write: synonyms (`[depressed]SAD`: "depressed means sad"), abbreviations
(`[small road]RD`, even if the dictionary table holds the pair: you cannot see it; add the
domain when it helps, `C is the cricket abbreviation for caught`), names. A missing leaf
note is the commonest first-check failure. Only a leaf that is its own letters (`[a]A`)
goes without, and a pick under first/last/alt/hid needs a note on its indicator only. A
definition gets one only where it disagrees with the answer in number or part of speech;
in a double definition each definition's note says what that sense means.

**Special clue kinds.**
- **Double definition**: two `def`s and no `wp`.
- **Cryptic definition**: `def` the whole clue, `wp` `cd([the clue's words])`: ONE leaf
  holding the clue words once (never `cd([a], [b])`), with a note, no letters. Two
  readings in two stretches is a double definition instead.
- **Rebus**, **composite anagram**, **move** and **reverse clue** have their own
  forms in the grammar (`rebus`, `comp`, `move`, `reverse`): use them, never a
  fodder-plus-deleted-letter or `ana(del(...))` stand-in, which says a letter was added.
  A reverse clue keeps its `def`; its leaf's note says how the pieces make the clue words.
- **Trimmed synonym** ("jumps without limits" = BOUNCES less its ends, OUNCE): a
  deletion, `del<without limits>([jumps]BOUNCES, B, S)`, never `middle`/`first`/`last`
  (those say the letters are printed in the clue). A halving stays `first<half of>`.
- **&lit**: `"andLit": true`, `def` the whole clue and the whole clue's wordplay.
- **Homophone** (`sound`): the first check fails ("no block says what is said aloud",
  the commonest first failure) unless the word said aloud is on ONE leaf.
- **Spoonerism**: `spoon`, never `sound()` round it; no one-leaf rule applies. Written
  letters swapped: `spoon(a, b)`; swapped by sound: `spoon(a, b, SPELT)`.

An entry with an `alteration` goes into the grid changed, as its puzzle's preamble says.
Write `alteration` (`{"from": "...", "steps": [{"op": "reversal"}]}`) in its object; apply
moves it onto the puzzle's entry (never edit the puzzle file by hand). The clue's
definition and wordplay give `alteration.from`, `steps` turn that word into the
solution, and `wp` builds `from`.

Letters the puzzle's preamble supplies are a bare piece with no clue words: `[can]LOO + E`.
A puzzle's `themeClue` names the clue that states its theme; treat it as a preamble.

When the preamble hides a letter per clue that spells a phrase, give each such clue
`"hiddenLetter": {"kind": "extra", "letter": "L"}`. Kinds: `extra` (the wordplay gives it
beyond the answer: write that step `del(<the part>, L)` with no indicator), `omitted`
(a bare `L` piece supplies it), `misprint` (add `"printed"`, the wrong letter, and
`"at"`, its offset in the clue; `letter` is the correct one), `clue` (a letter of the
clue itself, with `"at"`). Beside the entry ids, give the phrase: `"messages":
[{"text": "SUM TO FINAL", "kind": "omitted", "direction": "across", "order": "clues",
"placement": "belowGrid"}]` (`direction` only when one direction spells it, `placement`
only when the preamble says where).

## Taste

The check enforces the mechanics and explains each rule when broken. It cannot see
these. `STYLE.md` holds the product feedback behind them and wins any disagreement.

- The definition must substitute for the answer in a sentence: same part of speech,
  same inflection. Say the swap out loud. This is the most common mistake.
- A link word joins and says nothing else. Don't borrow another mechanism's signal
  words in any prose field: "aloud" means homophone, "shuffle" anagram, "hidden"
  extraction, "reversed" turnaround.
- `explanation.surface` is the picture, not a paraphrase and no mechanics: `Behaved antisocially
  and gave birth` is one person's bad week. A clue of four or more words has one unless
  it is a pure double or cryptic definition, even a clue that reads as bare mechanism.
- `explanation.walkthrough` says only what the parse cannot: why the surface misleads, a
  convention the solver may not know (`ER` = Queen), why a definition is fair; not
  fragment-to-letters narration. It names every indicator by its words and any letters an
  anagram, reversal or deletion makes that the parse does not state: `'getting into' puts
  INAT (the anagram of ANTI, from 'Wildly') inside DOME`. Skipping one is a fault, like a wrong note; stay within the word cap by dropping everything else.
- Where one false path is a competent solver's real first move, name it and what kills
  it: `"Flowers" wants to be the definition; it is the river.` Most clues have none; an
  invented one is worse than none. Every "the X" must be visible in the clue.
- Many readers are not British. Where a clue turns on everyday British knowledge (a
  county, soap, cricket position, old coin, rhyming slang, banger, jumper), say what it is
  in one clause, never dropped for brevity: `THE OVAL is a London cricket ground`. Not for
  crossword conventions, which the app teaches.
- `features` is data, never shown. Honest nulls and falses are a usable row; a guessed
  `joke` poisons it. `joke` asks whether one is present, not whether it is funny.

## Check

```
python3 tools/annotate_check.py <ID>
```

It applies, validates and audits the file and prints everything wrong in one report, each
line saying what to do (it names the part of a `wp` that breaks; a `block` is a leaf).
Fix everything in one edit, run again, and stop the moment it says `clean` or `done`
(warns alone are advisory: never re-run to chase them): end with one short line, and
no summary, no further pass. "Worth knowing now" is advice, not failure.

Four first runs in ten fail, mostly on these:

- `definitionFit` needs 25+ characters and a content word in neither the definition nor
  the answer. Name the relation (synonym, example, crossword-only sense, idiom); don't
  read the definition back with the answer in it. Start with the relation itself: the page
  already prints "definition → ANSWER:" before your sentence, so never begin with
  "definition -> ANSWER:" yourself.
- An indicator's note needs 25+ characters and words beyond the indicator's own: why
  these words signal that operation in this clue, not what the device does in general.
  It comes before the pieces, so it never names a piece's letters or the answer:
  `"returning means the word rats is read backwards"`, not `"returning means RATS becomes STAR"`.
- No note may contain the answer, nor the solution of a linked light, as a word or as a run
  of words (the validator reads "under-taker", "S and Y", "get set" as the answer).
  Write about the clue words, never about the answer. This is the commonest first-check
  failure, in three shapes:
  - a definition's sense note that opens on the answer ("a tattoo is a display of troops"):
    say what the clue words mean, with a synonym or example, not the answer's own word;
  - "read the answer as ..." or "the answer read as a phrase says ...": describe the
    clue's fragment ("the outside letters are S and Y"), never the assembled answer;
  - a note on one fragment that mentions another light's solution: leave it out.
- A `cd()` has exactly one leaf, no letters, and no note that spells the answer.
- `features.misdirectedWord` is one word, copied exactly as printed in the clue.

Working here:

- To change many clues, Write `{"8-down": {"field": value}}` under `tools/`
  (`tools/_patch_<ID>.json`, never `/tmp`) and add `--patch <file>` to the check. Each
  field is replaced and null removes it, except `notes`, merged note by note.
- Run the check as a single command: no `&&`, `;`, pipes or `rm`; a compound command
  needs an approval this run cannot give and runs nothing.
- **Your tools are Read, Write, Edit, `python3` and `node`, nothing else.** `grep`,
  `sed`, `cat`, `ls`, `awk`, `mkdir`, `rm`, `cd`, heredocs and any `>` redirect are
  refused and cost a turn. The puzzle file's `entries` are strings
  (`id | group | SOLUTION | clue`), not objects: Read it rather than `python3 -c` it.
  Another puzzle's file is a different shape; you do not need one. WebFetch is refused
  for theguardian.com.
- To take back hints you would not stand by, run the check with `--withdraw "<why>"` and
  stop: the puzzle file is put back and nothing you wrote ships. Never use git.
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
    A + B                 a charade, in answer order, pieces side by side (ins
                          only where one piece is cut open by another). Every
                          clue piece that gives letters is a term: none is left
                          out (inside ana() they are the fodder's parts)
    op<indicator>(...)    an operation; <indicator words> follow the op they
                          signal, one <...> per phrase; `+<under>` is an
                          indicator on the charade. Every op but + needs its
                          indicator: no clue word signals it, the op is not there
    ana(x)                anagram of x's letters; ana(x + y + z) shuffles several
                          of the clue's own pieces as one pool. A single letter, a
                          pick at the answer's end, an abbreviation or a synonym
                          is spelt beside it, ana(x) + N, never scrambled in
    rev(x)                x backwards; an indicator naming a stretch (last pair
                          of, first three, half) turns only that stretch, 2+
                          letters: rev<last pair of>([mini vehicles]KARTS) for KARST
    rep(x)                x twice (leaf gives one copy): rep<twice>([boy]AL) for ALAL
    ins(outer, inner)     inner put inside outer (the answer decides where)
    del(from, removed)    removed taken out of from (the answer decides where):
                          one run, or scattered in the same order
                          (del([Equably], [by]BY) for EQUAL)
    hid(x)                letters hidden in x's words: hid([say no before]YNOBE),
                          or hid([say no before]) to let the answer pick them
    sound(x, SPELT)       x sounds like SPELT, the letters entered. x is ONE leaf
                          naming the word said aloud: sound<ind>([clue words]HEARD,
                          SPELT). Side-by-side leaves are merged for you; over a
                          step (first, del, hid) the leaf holds the step's letters
    spoon(a, b)           a and b with their first consonants swapped (written
                          letters); spoon(a, b, SPELT) when the swap is by sound,
                          SPELT the letters entered. Never put sound() round a
                          Spoonerism: spoon<Spooner's>([marry]MARRY, [fan]FAN, FERRYMAN)
    sub(x, OLD, NEW)      OLD in x replaced by NEW
    cyc(x)                x with letters moved from one end to the other
    move(x, MOVED)        MOVED, one run of x's letters, taken out and put back
                          elsewhere in x (the answer decides where), one step:
                          move<dropping>([England]ALBION, [ball]O) for ALBINO,
                          never ALBION + O with the first O deleted
    pal(x)                x, which reads the same backwards; pal() with no x
                          when the answer itself is all the wordplay
    first(x) last(x) middle(x) outer(x) alt(x) regular(x) nth(n)(x)
                          letters picked from x's words: first letter (or
                          each word's), middle letter(s) or all but the
                          ends, first and last, alternate, every 2nd/3rd, the nth.
                          x is the words picked FROM, never the pick:
                          alt<regularly>([most]) for MS, not ([most]MS). Over
                          several words it takes a comma list, never +:
                          outer<fringes of>([Argive], [Greece], [Anatolian]).
                          The indicator needs a note; the pick needs none
    cd([words])           cryptic definition: the words, no letters (a wp that
                          is one leaf is refused; no mechanism means a cd or a
                          double definition)
    comp(x, y)            composite anagram: x's letters are the answer plus y's
                          (never ana(del(...))): comp<sadly>([thirsted], [it's])
                          for DERTH
    reverse([words], "reading")
                          a reverse clue: the words read as wordplay that would
                          build the answer; "reading" spells it in the pieces,
                          capitals joined by spaces or +: reverse([What makes
                          pets], "OUT + STEP") for OUTSTEP. The whole wordplay;
                          the definition stays a `def`. Only when the reading
                          names the clue's own last words rearranged (pets ->
                          STEP); a phrase of 3+ words with no such word is
                          refused (reversePhrase): write what the words do
                          (ana, hid, charade), or cd([words]) if nothing builds
                          the answer
    rebus([words], "reading")
                          a picture of letters or figures, "reading" saying what
                          it shows: rebus([HIJKLMNO], "H to O") for WATER. The
                          whole wordplay; with no `def` it is the whole clue
A double definition has no wordplay: two definitions and no expression.
```

### Worked annotations

Rendered from the corpus in the shape you write; each passes every check.

quiptic-619 11-across, "Fake folio made by a conservative is libellous" (10), solution DEFAMATORY:

```json
{"11-across": {
  "def": "libellous",
  "wp": "ana<Fake>([folio]F + [made]) + [a] + [conservative]TORY",
  "notes": {"Fake": "something fake is invented or concocted, so these letters are reworked into a new arrangement", "made": "taken as written", "a": "taken as written", "conservative": "a Tory is a member of the UK Conservative Party"},
  "explanation": {"surface": "A forged document produced by a Tory politician is defamatory.", "walkthrough": "'Fake' looks like an adjective describing the folio, but it is the anagram signal. Take F (folio) and MADE to get FMADE, and rearrange those letters to make DEFAM. Then add A, which the clue gives as it is, and TORY, the everyday name for a member of Britain's Conservative Party.", "definitionFit": "Libel is written defamation, so a libellous statement is one that damages a reputation falsely."},
  "features": {"answerInScene": true, "aptDefinition": false, "misdirectedWord": "Fake"}
}}
```

<!-- REFERENCE-END -->
