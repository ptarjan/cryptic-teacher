# Annotation task for Claude Code

You are annotating a Guardian cryptic crossword for the Cryptic Teacher app in this
repository. The target puzzle file is `puzzles/<NUMBER>.js` (the newest file whose
entries still have `"annotation": null` — `puzzles/index.json` lists which puzzles have
`"annotated": false`). Work on the OLDEST un-annotated puzzle first if several are
pending, so the backlog drains in order.

## What to produce

For EVERY entry in the puzzle file, replace `"annotation": null` with an annotation
object. The published solution is already in each entry's `"solution"` field — use it as
ground truth, and make sure your parsing actually produces those letters.

Annotation schema (see `puzzles/30066.js` for 28 worked examples):

```json
{
  "type": "anagram | charade | container | hidden word | homophone | reversal | deletion | double definition | &lit (combinations joined with ' + ')",
  "answer": "DISPLAY FORM (spaces/apostrophes/hyphens ok; letters must equal the solution)",
  "definition": "exact substring of the clue text",
  "definition2": "second definition, only for double definitions",
  "definitionNote": "only when the definition genuinely disagrees with the answer in number or part of speech: a sentence explaining why the setter is allowed it",
  "indicators": ["exact substring", "..."],
  "linkWords": ["exact substring joining definition to wordplay, e.g. 'to locate'"],
  "blocks": [
    {"clueFragment": "exact words from the clue", "gives": "LETTERS", "note": "why"}
  ],
  "walkthrough": "1-2 sentences, 45 words max: what the blocks CANNOT show. Friendly teaching tone.",

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
  `charade + alternate letters`), using only the controlled vocabulary in
  STYLE.md / `TYPE_PARTS` in the validator. If a clue truly needs a new type
  part, add it to `TYPE_PARTS`, STYLE.md, and `TYPE_BLURBS` in `app.js` together.
- `cryptic definition` is capped at TWO per puzzle and the validator ERRORS above that
  (`MAX_CRYPTIC_DEFINITIONS`). It is the only type with no checkable wordplay, so a third
  one almost always means you gave up on a clue: go back and find the charade, hidden word
  or container it is hiding. If you are WRITING clues rather than annotating them (see
  `tools/AUTHORING.md`), the same cap is the rule that keeps a funny sentence from
  replacing the mechanism — a clue needs both, and a funny sentence is much easier to find
  than a funny mechanism. Related: an indicator that reads as a visible instruction
  (`a bit of`, `in front`, `turned`, `rebuilt`) is a mechanism narrated, not hidden.
- `definition`, `definition2` and every string in `indicators` MUST occur verbatim in the
  clue (match the exact characters — Guardian clues use curly apostrophes `’` and en
  dashes `–`).
- Provide `pieces` for charades/containers/deletions (the final letter chunks in answer
  order) or `anagram.fodder` for anagrams (including any extra letters joined in). Use
  `subAnagrams`/`subReversals` for embedded steps. Double definitions, homophones and
  hidden words need neither (hidden answers are checked against the clue letters).
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
- The `walkthrough` is short, because the blocks already did the work: "when you
  basically give the whole answer in the building blocks you don't need to have the full
  walkthrough". Do not re-narrate fragment → letters. Write only what the blocks cannot
  show — why the surface misleads, the joke in one clause, a convention the solver may
  not know (`ER` = Queen, `worker` = ANT), or why a definition is fair. One or two
  sentences is normal; over 45 words the validator warns (authored puzzles). It must
  never be empty: the app always renders the walkthrough rung.
- If the definition genuinely does NOT agree with the answer ("Lousy payment" = PEANUTS,
  "hearing aid" = EARPHONES), do not stretch it and do not ignore it: add a
  `definitionNote` explaining the mismatch to the learner. The validator requires a real
  sentence, and the note is shown in the app under the definition rung.
- Never hedge in a `walkthrough`. Words like "jokingly", "somehow", "if you squint" are a
  validator ERROR: if the explanation needs a fudge, the parse is wrong. Go back and
  find the parse that needs no excuse.
- Do not guess: if a parsing doesn't produce the answer's letters exactly, it is wrong —
  rethink it. Consult the setter's usual tricks; check fifteensquared.net if reachable.

## Verify (mandatory)

```
python3 tools/validate_annotations.py <NUMBER>
```

Iterate until it reports `N/N annotated — OK` with no ERROR lines (warnings about block
fragments are acceptable but worth fixing). Then refresh the index:

```
python3 tools/fetch_puzzle.py --reindex
node --check puzzles/<NUMBER>.js
```

## Commit

Commit only the puzzle file + regenerated `puzzles/index.json`/`index.js` with message:

```
Annotate <NUMBER> (<Setter>): full 6-level hint data

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```
