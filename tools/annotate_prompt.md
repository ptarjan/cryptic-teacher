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
  "indicators": ["exact substring", "..."],
  "blocks": [
    {"clueFragment": "exact words from the clue", "gives": "LETTERS", "note": "why"}
  ],
  "walkthrough": "2-4 sentences assembling the answer step by step, friendly teaching tone.",

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
  inside an indicator, or inside a block's `clueFragment`. A leftover word means you have
  missed a piece of wordplay (30067 13A dropped `state` = CAL and nobody noticed).
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
