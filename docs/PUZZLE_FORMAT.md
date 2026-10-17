# Puzzle file format

`puzzles/<series>/<year>/<series>-<n>.json` holds one puzzle as plain JSON. It
is the committed source that every tool reads and writes. `<year>` is the
year of the puzzle's `date`, the calendar day the paper printed it, written
`YYYY-MM-DD`. A book puzzle holds its book's `year`, an integer, instead of a `date` and is
filed under that year. A puzzle with neither goes in `undated`. `tools/puzzle_paths.py` owns that
rule, and `python3 tools/puzzle_paths.py <id>` prints where a puzzle is.
Generated and not committed, `puzzles/<series>-<n>.js` stays flat, so no URL
depends on the year folder. It puts the puzzle in
`window.CRYPTIC_PUZZLES["<series>-<n>"]`: the browser's fields only, with each
entry packed into an array that the script itself unpacks
(`fetch_puzzle.write_shim`). That script is how the page loads a puzzle from
`file://`.

Shape (see "The wordplay tree" below):

```jsonc
{
  "id": "cryptic-30066", "number": 30066,
  "setter": "Tramp", "date": "2026-07-23", "dimensions": {"rows": 15, "cols": 15},
  "source": {"url": "https://www.theguardian.com/crosswords/cryptic/30066"},
  "entries": [
    {
      "number": 16, "direction": "across",
      "position": {"x": 0, "y": 8}, "length": 10,
      "clue": {"text": "Destroying climate, sun reaches highest point", "enumeration": "10"},
      "solution": "CULMINATES",
      "annotation": {
        "definitions": [{"text": "reaches highest point", "at": 24}],
        "wordplay": {"op": "anagram",
          "indicators": [{"text": "Destroying", "note": "destroying a thing breaks it apart, so its letters are rearranged"}],
          "parts": [{"words": "climate, sun", "note": "anagram fodder"}]},
        "explanation": {
          "surface": "…the picture the clue pretends to paint…",
          "walkthrough": "…1-2 sentences on what the blocks cannot show…",
          "definitionFit": "…why the answer means the definition…"
        }
      }
    }
  ]
}
```

A barred grid (the Mephisto, the Listener) also has `bars`, a string per row with a character per cell:
`r` for a bar on the cell's right, `b` for one below it, `+` for both, `.` for neither. A blocked grid
has no `bars`, and its black squares are the cells that no entry covers.

An entry has no stored id. Its id is `"<number>-<direction>"` ("16-across"),
derived where it is needed (`groups.entry_id`, `entryId` in `app.js`); `group`
and annotation files name entries by it. A puzzle file that stores an entry
`id` fails the schema, so the write refuses it.


## Design principles

- **The file stores facts and a checked parse, nothing derivable.** A field
  that can be computed from other fields is computed when the file is read,
  not stored. An annotation's `type`, display `answer`, `linkWords`,
  indicator `for`, `blocks` and `assembly` all follow from its wordplay tree
  and the entry's solution, separators and clue; `annotation.view()` derives
  them in one place, and a puzzle's `name` comes from `series.display_name()`.
- **The model writes a model-friendly form, and a program translates it.**
  The annotator writes each clue's wordplay as a one-line expression close to
  a solving blog's parse line (`ins<in>([burn]STING, [tree]PINE) +<under>
  [fish]LING`). `tools/wordplay.py` parses it, works out the letters at every
  step, refuses a parse that does not give the answer (naming the step that
  broke), and turns it into the stored tree.
- **Lessons become checks, not prompt text.** The validator refuses a
  derivable field rather than a prompt asking the model to keep it consistent,
  so a mistake that has been fixed once cannot be written again.
- **Why.** Stored copies of the same fact drifted apart: answers spaced
  against their enumeration, a `type` list disagreeing with the blocks, link
  words that overlap a block, and containers and deletions that no check could
  reach, because only their final pieces were stored. A tree checks every
  step, and a derived field cannot disagree with its source.

### The wordplay tree

An annotation filed before trees were checked may hold an `"unchecked": true`
node where its step could not be rebuilt as an op: its `gives` is taken as
filed, and the expression cannot write one. The tree, in brief:

- A node is an op `{op, indicators?, parts, spelt?, reading?, n?}` or a leaf
  `{words, at?, gives?, note?}`. A leaf without `gives` is its own letters.
  `gives` on a checked op is refused, because the evaluator works it out.
- **An absent key means empty** (`puzzle_schema.prune` runs on every write), so
  no file stores `[]` or `""`. `pal()` over the answer alone has no `parts`,
  and every reader goes through `wordplay.parts_of`. An unchecked leaf without
  `gives` gives no letters (a block that was only a note).
- **An anagram's parts are its fodder**, one pool of letters: one part, or
  several in clue order, verbatim leaves and, for a compound anagram, any
  other piece (an abbreviation, a synonym, a selection). The expression
  writes them `ana<Dreadfully>([slay] + [a] + [cut])`, and `parse` stores
  slay, a and cut as the anagram's own parts (sundaytel-2671 1A, CASUALTY).
  Nothing under an anagram is joined in sequence, so a charade directly under
  one is refused: `parse` cannot write one, and `validate_annotations.py`
  counts them (`wordplay.anagramCharade` in `tools/annotation_backlog.json`)
  so a puzzle keeps only those `tools/flatten_anagram_fodder.py` left as
  filed (a join with an indicator of its own, or one under an unchecked step).
  view() reads the fodder's letters off the parts in clue order (the tiles the
  ring deals), and the blocks follow the parts.
- **Shape rules.** A tree that parses and evaluates can still say something the
  clue does not. `validate_annotations.py` counts these per clue, each under its
  own `tools/annotation_backlog.json` field, so a puzzle keeps the ones it has
  and a new annotation adds none: `wordplay.charadeInCharade` (an indicator-less
  charade directly in a charade: join the pieces in one), `wordplay.noIndicator`
  (an anagram, container, deletion, reversal, homophone, hidden word or letter
  selection with no indicator), `wordplay.cdefRepeat` (a cryptic definition is
  one `cd([clue words])`, not several leaves), `wordplay.arity` (a stored op with
  a part count its op cannot take, or a charade of fewer than two),
  `wordplay.spanOverlap` (two leaves or indicators sharing clue words),
  `wordplay.inDefinition` (wordplay words inside the definition of a clue that is
  not `andLit`), `wordplay.leafFold` (a leaf with no note whose `gives` is a
  stretch of its own words: write the selection, deletion or hidden word as an
  op), `wordplay.repeatedSelection` (the same first/last/middle pick on each
  word of a phrase: one op over one multi-word leaf), `wordplay.singleLeaf`
  (wordplay that is one leaf), `wordplay.bareInCharade` (a charade piece with no
  clue words, unless the clue has a `hiddenLetter` or the leaf carries
  `"device": true`) and `wordplay.anagramOfContainer` (`ana(ins(..))`: the anagram
  goes inside, `ins(outer, ana(x))`). Four more count what the checked rules skip,
  in an `unchecked` step (the `tools/shape_suspects.py` detectors measured precise):
  `wordplay.arityIns` (a container not of two parts), `wordplay.arityOther` (a
  deletion of 3+, substitution not of 3, homophone of 3+, or a reversal, hidden
  word, cycling or letter selection not of 1), `wordplay.delSingle` (a deletion
  with one part: what it removes is not stated) and `wordplay.indInLeaf` (an
  indicator word also inside a longer leaf). `tools/tidy_wordplay_shapes.py` joined the
  charades in charades whose `view()` is unchanged and recorded the rest.
  Two more ratchets (`tools/lesson_checks.py`) have no rewrite: `wordplay.ddMissesWordplay`
  (two definitions and no wordplay, in a clue that hides the answer across words or holds
  its letters in a run of whole words: parse it) and `spelling.unsaid` (an answer with an
  apostrophe or accent and no `spelling`; the known ones are in
  `tools/data/lexicons/spellings.json`, which `tools/build_spellings.py` extends).
  A run's own `annotate_check` reports every one as an error. Until
  `SHAPE_GRACE_UNTIL` in `validate_annotations.py` the push hook and CI let through
  findings that have no allowance yet (a pusher still on code from before the
  rules cannot see them); `tidy_wordplay_shapes.py --write` then records them.
- **A rebus** (a picture of letters: `HIJKLMNO` for WATER, `P?` for APPLE CORE)
  is `{"op": "rebus", "reading": "H to O", "parts": [{"words": "HIJKLMNO"}]}`,
  written `rebus([HIJKLMNO], "H to O")`: the clue words are the picture and
  `reading` says what it shows, the phrase that means the answer. It is the
  whole wordplay and gives no letters of its own, so `evaluate` checks the
  reading instead: it names some of the picture's capitals or figures, each
  shown in the picture in that order (`IOU` in `IO2U?`), and is not the answer
  itself. A picture of the whole clue needs no `definitions`; its type is
  `rebus` (family "Rebus"), its block is the picture with
  the reading as its note, and validate_annotations refuses a note that names
  the answer there as on any block.
- **A composite anagram** (the fodder holds the answer plus letters the clue names:
  "thirsted" is DERTH and ITS) is `{"op": "composite", "indicators": [...], "parts":
  [fodder, taken out]}`, written `comp<Sadly>([thirsted], [it's])`, never an
  `anagram` over a `deletion`, which reads the steps in the wrong order. `evaluate`
  checks that the fodder's sorted letters are the answer's plus the taken-out
  letters'; its indicator's `for` and the clue type are `composite_anagram` (family
  Anagram), its blocks (the fodder, the letters taken out) add up to more than
  the answer, which that type is let off, and there is no ring: the fodder is
  longer than the answer.
- **A reverse clue** (the clue words are what the answer's own wordplay would
  produce: "What makes pets" for OUT + STEP, out anagramming STEP) is
  `{"op": "reverse", "reading": "OUT + STEP", "parts": [{"words": "What makes pets"}]}`,
  written `reverse([What makes pets], "OUT + STEP")`. The clue words are the
  wordplay-like stretch and the leaf's note says how the pieces make them; the
  reading is the answer in two or more pieces, capitals joined by spaces or `+`,
  and `evaluate` checks that they spell the answer; the reading is the walkthrough's to
  say, so the block carries only the leaf's note. It gives no letters of its own
  and is the whole wordplay, but the definition stays a `definitions` entry. Type
  `reverse_clue`, family "Reverse clue".
- **A double definition** has two `definitions` and no `wordplay` (or a
  partless palindrome when the answer reads both ways). A definition's
  `meaning` is the note on its block, on the blocks rung. Its `note` belongs to
  the definitions rung, which comes later, so view() never promotes it to the
  block: it may say what a block may not.
- **A setter's slip** (`tools/data/setter_error.json`: printed fodder that
  cannot give the answer) is one unchecked anagram over the fodder leaves as
  printed, `gives` the letters it should give. view() lists it in
  `assembly.anagrams`, and the validator holds it to the row. A block may not
  respell its words to hide the slip.
- **Spacing**: the display answer is the solution spaced by the light's
  separators or enumeration. `spelling` holds what that cannot give (an
  apostrophe, an accent, or a hyphen in a series whose enumeration counts
  letters only, Azed and the Listener, when the light has no separators). A
  separator at the light's own end means the answer runs on into another
  light, and it is no gap inside this one.

Which whole-clue tree shapes the corpus holds, how common each is, and which
of them make sense as a cryptic mechanism (and which are redundant, mislabelled
or unverified) is in [CLUE_SHAPES.md](CLUE_SHAPES.md). `tools/clue_shapes.py`
generates the numbers and examples from the puzzle files; the judgements live
in `tools/data/clue_shape_verdicts.json`, which a regeneration keeps and which
the generated page's top section says is missing for any new common shape.

The schema refuses every derived field, each with the reason:

- top-level `name` and `series` (the file stores `prize`, `title` or `label`
  where `display_name()` needs one; `fetch_puzzle.write_puzzle_file` turns a
  fetcher's `name` into them, `series.name_facts`);
- annotation `type`, `answer`, `indicators`, `linkWords`, `blocks` and
  `assembly`;
- an indicator's `for` (it signals the op it sits on), `gives` on a checked op
  (the evaluator works it out), and `select` or `soundsLike` on a checked leaf;
- a `spelling` equal to the solution spaced by its enumeration.

The tree is `$defs/wordplayNode` in `tools/data/puzzle.schema.json`.
`validate_annotations.py` checks a file through `annotation.view_puzzle()`:
a tree that does not give the answer is an error, and every other check reads
the fields `view()` derives. An `unchecked` node warns, and the ratchet
(`wordplay.unchecked` in `tools/annotation_backlog.json`) lets a puzzle keep
only the ones it already has, so a new annotation can add none. The site's
build reads `view_puzzle()` too (`fetch_puzzle.browser_puzzle`), so app.js
sees the derived fields. `tools/test_puzzle_format.py`,
`tools/test_shim_format.py` and `tools/smoke_test.js` hold this.

**What the annotate run writes** (`tools/annotate_prompt.md`'s Schema) is a
shape of its own, the model's, which is never stored: per clue `def` (the
definition's clue words, or a list of two for a double definition), `wp` (the
expression; none for a double definition), `notes` keyed by the words of any
span as written (`#2` for a repeat), and `explanation`, `features`, `andLit`,
`hiddenLetter`, `alteration` as stored; `answer` only to correct a `(MODEL)`
answer or to spell one with an apostrophe or accent (stored as `spelling`).
`annotation.from_model()` translates it to the stored annotation, evaluating the
tree, and raises a message naming the step that broke; `annotation.to_model()`
renders a stored annotation back (the prompt's worked examples, generated by
`tools/build_annotate_prompt.py`, and the run's `existingAnnotations`).
`apply_annotations.normalize` writes each clue as its tree; a clue carrying a
derived key (`type`, `blocks`, ...) is refused by `from_model`, which names the
key and asks for `def`, `wp` and `notes`.
`tools/test_annotate_model_shape.py` holds all of this.

The rules below are written against the derived fields (`type`, `answer`,
`indicators` with `for`, `blocks`, `assembly`, `linkWords`). They are never
stored: they are read off `annotation.view()`, which derives them from the
tree.


## Annotation rules

`tools/validate_annotations.py` enforces these:

- Each definition's and each indicator's `text` must appear **verbatim** in
  the clue text. Guardian clues use `’` and `–`.
- `definitions` holds one object per definition, two for a double definition,
  in clue order: `text`, `at` (its offset in the clue, in Unicode code points)
  and an optional `note`. Writers give `text` and `tools/definitions.py` fills
  `at`; where the text occurs twice it takes the whole-word occurrence clear
  of the other definition, at the clue's start or end, and refuses to guess
  past that.
- `indicators` holds one object per indicator phrase: `text`, `for` (the one
  type from the annotation's own `type` that the words signal) and `note` (why
  they signal it in this clue). New annotations need `for` and `note`; older
  puzzles may lack them up to their allowance in
  `tools/annotation_backlog.json`.
- The letters of `answer` must equal the grid solution. For linked clues, that
  is the whole group.
- An annotation has three layers. `blocks` are the wordplay as the app shows
  it, one per clue fragment. `assembly` restates the answer for a program to
  check, and may cut it differently from the blocks. `explanation` is the
  prose the last hint rung prints: `walkthrough` (always), `surface` (the
  picture the clue pretends to paint) and `definitionFit` (why the answer
  means the definition). New annotations need `definitionFit`, and `surface`
  on a clue of four or more words that is not a pure double or cryptic
  definition; `tools/annotation_backlog.json` lists older puzzles' allowance
  under each key's dotted path (`explanation.surface`, `indicators.note`).
- Letter mechanics must be machine-checkable, through `assembly`:
  - `pieces` must concatenate to the answer.
  - Each of `anagrams` is `{fodder, gives}` with `fodder` a rearrangement of
    `gives`; when the whole answer is an anagram, one item's `gives` is the
    answer.
  - Each of `reversals` is `{from, to}` with `to` equal to `from` backwards.
  - A hidden answer must appear inside the clue's letters.
- Linked answers (one answer over several lights, "See 21"): the leader, the
  light that prints the clue, carries `group`, the answer's entry ids in
  word order, and the one annotation, whose `answer` is the whole answer.
  The leader is the light the answer starts on, and so first in its group,
  unless the paper printed the clue on a later light: cryptic-21673 clues
  VESTED INTEREST at 26-across and prints nothing at 25-across, so 26-across
  holds `["25-across", "26-across"]`. A light before such a leader prints no
  clue of its own, or is named in the leader's `selfClued` (cryptic-23821's
  23-down RIGHT, clued as RIGHT NOTE, also starts 22-across's RIGHT AS RAIN);
  `fetch_puzzle.GROUP_ORDER` pins the order so a re-fetch keeps it. The other
  lights carry neither a group nor an annotation, so a light's leader is the
  entry whose `group` names it. A light whose clue continues two answers
  ("See 19, 22") is in both leaders' groups.

  ```jsonc
  {"number": 21, "direction": "across",
   "clue": {"text": "‘Army-stopper’ inventor exploded, making a big noise (4,9,6)",
            "separators": [{"at": 4, "mark": ","}]},
   "group": ["21-across", "25-across"], "solution": "VERY",
   "annotation": {"answer": "VERY IMPORTANT PERSON", …}},
  {"number": 25, "direction": "across", "clue": {"text": "See 21", "separators": [{"at": 9, "mark": ","}]},
   "solution": "IMPORTANTPERSON"}
  ```
- `preamble` (puzzle level) is the paper's note above the clues: a themed
  puzzle's special instructions ("Seven solutions, not defined, are linked"),
  or an erratum. The Guardian fetcher takes it from the page's `instructions`,
  the Independent's from `<metadata><description>`. A puzzle filed from a
  blog carries the write-up's account of the instructions, set by hand.
- `"device": true` (on a wordplay leaf with no clue words) says its letters come
  from a puzzle-level device that `preamble` or `themeClue` declares, not from a
  clue word: a Genius edge letter, the shared letters of an Azed collision, a
  missing Pope the theme clue names. Such a bare leaf in a charade is exempt
  from `wordplay.bareInCharade`. A clue with a `hiddenLetter` needs no marker:
  its bare letter is exempt as a whole. The marker is a claim about the
  preamble, so set it only after reading the preamble; the expression cannot
  write it, so it is added to the stored tree.
- `"definedByPreamble": true` replaces `definitions` on an answer the preamble
  defines and the clue does not. It is valid only when the puzzle has a
  `preamble`, and never beside `definitions`.
- `themeClue` (puzzle level) is the id of the entry whose clue states the
  theme, `"30-across"`, on a themed puzzle that puts its gimmick in a clue
  and prints no preamble (nation-3337's 30-across: five Across answers start
  with a fish their wordplay omits). Someone sets it by hand at filing or
  review, after reading the puzzle. The annotator sees it and may not set,
  change or drop it: apply_annotations refuses the key and
  `check_theme_clue_unchanged` refuses a file whose value differs from HEAD's.
  It counts as a preamble in one rule only. A block with no `clueFragment`,
  letters the theme supplies, is allowed, and that clue is their source.
  `puzzle_integrity.check_theme_clue` requires an entry of the puzzle with
  clue words. A clues-only record may carry it under the id its printed
  number will take, and `clues_only.promote` copies it onto the grid puzzle.
  Filing it changes the puzzle's failed-inputs hash, so a withdrawn annotate
  run is due again.
- Hidden-letter devices (`tools/hidden_messages.py`). An annotation's
  `hiddenLetter` is the letter its clue gives to a device the preamble
  describes: `{"kind": "extra" | "omitted" | "misprint" | "clue", "letter"}`,
  plus `printed` and `at` for a misprint (the wrong letter the clue prints and
  its code-point offset in `clue.text`; `letter` is the correct one) and `at`
  for a letter read off the clue. An extra letter is in the blocks and not the
  answer; an omitted one is in the answer and not the blocks, or supplied by a
  block with no `clueFragment`. The puzzle's `messages` lists each phrase the
  letters spell: `{"text": "SUM TO FINAL", "kind": "omitted", "direction":
  "across", "order": "clues", "placement": "belowGrid"}`. `order` is `clues`
  (across by number, then down) or `unordered`; `direction` is absent when both
  directions spell it; `printed: true` reads a misprint's wrong letters;
  `placement` is absent when the preamble only asks that it be read. The
  validator checks every letter against its clue and, once every clue a message
  reads is annotated, that they spell `text`. A preamble that names such a
  device on an annotated puzzle with no `messages` is counted by the ratchet
  under `messages`.
- `clue` is the clue as printed, in one object:
  - `text`: the printed words, without the enumeration ("Moscow politician
    revolting in style", "See 21"). Offsets into it (`italics`, a definition's
    `at`) count Unicode code points.
  - `enumeration`: the printed letter counts without the brackets, "4,9,6",
    "2-3", "1'5", "6 and 5"; absent when the clue prints none (about 9,500,
    mostly "See 21" continuations). `text + " (" + enumeration + ")"` is the
    printed line. It is stored rather than rebuilt from `separators`: a linked
    answer's leader prints the whole group's count, and some prints say what
    separators cannot. A count the paper itself printed wrong stays as
    printed ("0,11" over RHODE ISLAND); `fetch_puzzle.PRINTED_COUNT_WRONG`
    names it with the count the answer reads by, every write lays the
    `separators` out from that one, and `puzzle_integrity` holds the file to
    the row.
  - `separators`: the marks inside this light's answer, in order, as
    `{"at", "mark"}`. `at` counts this light's answer letters before the mark,
    not clue characters. Each light of a linked answer carries the marks inside
    it, and a mark at `length` falls between it and the group's next light:
    (4,9,6) above gives VERY `at` 4 and IMPORTANTPERSON `at` 9. The mark is
    `","` for a word break or `"-"` for a hyphen, rarely `"'"`, `"."`, `"/"`,
    `":"`, `";"` or `"and"`.
  - `italics`: spans of `text` printed in italics, `{"at", "length"}`.
  - `missing: true`: the paper printed no words (no `text`; an `enumeration`
    may still be there), with an optional `missingNote`. A blank clue is kept as
    printed, never filled in: it can be the setter's joke (cryptic-30098
    12-across is `{"missing": true, …}` because the answer is NOONDAY and the
    clue number is 12).
- **An absent key means empty.** An un-annotated entry has no `annotation` key
  at all. The app then badges the puzzle `hints via <blog>` and builds a short
  ladder from what a solving blog's write-up marks on that clue
  (`tools/data/blog_facts/`), or, where no blog marked anything, badges it
  `answers only` and shows no ladder.
  `clue.separators` works the same way: it is present only when the paper
  marks a break inside the answer, and so does every other key: no value in a
  puzzle file is `null`, `""`, `[]` or `{}`, and a flag is written only when
  true. Every entry has a `clue`; a blank one is `{"missing": true}`. A
  puzzle whose paper names no setter
  (the Times, the Telegraph, Metro) has no `setter` key.
- **The shape is a schema.** `tools/data/puzzle.schema.json` (JSON Schema
  2020-12) lists every key, its type and the closed lists it draws from.
  Every write prunes empty values and refuses what breaks the schema, the
  validator reports it, and CI checks every puzzle with
  `python3 tools/puzzle_schema.py`.
- **The entries are the grid, plus two optional keys.** A square is white when
  an entry covers it or an `unclued` light lists it. An unclued light, such as a
  shaded quotation running round a ring, lists its `cells` in reading order with
  its `solution` (and optionally an `enumeration` and a `note`); the app shows it
  shaded and lists it under Unclued. `printed` holds the letters the setter
  printed in the grid as `{x, y, letter}`; the app fills them in and locks them.
  Both must agree with the crossing entries' solutions
  (`tools/puzzle_integrity.py` `check_extra_cells`).

## Provenance: where the puzzle, its grid and its answers each came from

Every puzzle has a `source` block and a `solutions` block. `source` records how
the file got here — which paper, which page, which channel the bytes were
actually read through. `solutions` records, most importantly, **whose answers
these are**.

```jsonc
"source": {
  "publisher": "Observer",          // from tools/series.py, by the id's series
  "url": "https://www.theguardian.com/crosswords/everyman/3716",
  "acquiredBy": "tools/fetch_wayback.py",   // the command that actually ran
  "acquiredOn": "2026-09-17",       // when the file first appeared in git
  "retrievedFrom": "wayback",       // publisher | wayback | blog | book | authored
  "gridOrigin": "published"         // published | reconstructed | authored | unknown
},
"solutions": {
  "origin": "published"             // published | writeup | model | authored | unsolved
},
"annotatedBy": ["claude-opus-5"]    // who wrote the hints: exact model ids, or human | published | unknown
```

**The clues, the grid and the answers can each come from a different place.**
That is why these are separate blocks. Two examples:

- A Cyclops puzzle comes from Private Eye's own `.puz` download. Private Eye
  blanks the solution grid, so the answers come from a fifteensquared write-up:
  `retrievedFrom: publisher`, `solutions.origin: writeup`.
- A scanned-book puzzle has three origins. The clues come from a book scan, the
  grid is reconstructed here from those clues, and the answers are solved here
  by a model.

**Read `solutions.origin` before trusting a grid:**

| Value | Meaning |
|-------|---------|
| `published` | The setter's own answer key. Ground truth. |
| `writeup` | A human solver's published answers, not the setter's. |
| `model` | We solved it from the clues. Self-consistent and crossing-checked, but still a guess. |
| `authored` | We wrote the puzzle. |
| `unsolved` | The grid is empty. This is a known fact, not missing data. |

A grid we guessed must never look the same as one the paper answered. This
field keeps them apart.

Other fields:

- `solutions.previousOrigin` appears when the answers in the file replaced
  answers of a different origin. Example: a grid was cold-solved, then the
  paper published the same answers.
- `annotatedBy` is on every puzzle with hints and says who wrote them: exact
  model ids such as `claude-opus-5`, never an alias like `opus`, because an alias
  points at a different model from one month to the next. One entry per run, in
  the order they ran; a run that was cut off and resumed by the same model
  counts once. `tools/apply_annotations.py` writes it from the running
  session's transcript. Hints no model wrote say `human` or `published`.
- `solutions` also carries the detail behind a non-published `origin`: `blog`
  and `url` for a write-up, `model` for a model solve, and `date` and `check`
  for both — which write-up, which model, whether an official key can ever
  exist. The validator rejects a file where the two disagree.
  `tools/provenance.solution_detail(puzzle)` reads these keys back out.
- `source.url` is the page to cite; `solutions.url` is the write-up the
  answers came from. They coincide on a puzzle read off its blog write-up.

Every allowed value is listed in `tools/provenance.py` and nowhere else.
`tools/puzzle_integrity.py` validates against those same dicts.
`tools/test_provenance.py` proves it: it deletes a value and checks that the
corpus is then rejected. `tools/backfill_provenance.py` writes the blocks. It is
idempotent and safe to re-run. New puzzles get the blocks automatically, because
`write_puzzle_file` stamps them on every write.
