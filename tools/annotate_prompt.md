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
