# Findings triage

## Findings triage (2026-10-17)

Total: 125,790 backlog findings (`tools/annotation_backlog.json`). About 12,500
are fixable without a model: 3,508 firm and about 8,950 estimated.

Classes: **a** fixable by code, **b** needs a model re-parse, **c** a validator
false positive.

| Finding | Count | Class | What it is and what fixes it |
|---|---:|:---:|---|
| `wordplay.unchecked` | 47,580 | a ~17%, b the rest | New `tools/clear_unchecked.py` re-evaluates and drops the flag when the clue passes (~8,300). About 230 of 690 sampled crash the evaluator on wrong part counts. |
| `wordplay.noIndicator` | 12,943 | b | Mis-nested trees, mostly lone containers. About 15% are shared-indicator siblings. |
| `wordplay.delSingle` | 11,564 | b | Deletions that lost their removed part. |
| `features` | 10,406 | b | Surface judgements. |
| `indicators.note` | 9,119 | b | Reusing an existing note for the same indicator text is unmeasured. |
| `wordplay.indInLeaf` | 6,521 | b | |
| `explanation.surface` | 6,063 | b | |
| `wordplay.anagramCharade` | 5,729 | a ~11%, b the rest | Re-run `flatten_anagram_fodder.py` after unchecked is cleared (~650); the rest need a model. |
| `wordplay.arityOther` | 3,588 | b | |
| `spelling.unsaid` | 3,231 | a | `fill_spellings.py` does 2,979; 252 go to a model. |
| `wordplay.arityIns` | 2,796 | b | |
| `wordplay.anagramOfContainer` | 2,761 | b | |
| `wordplay.repeatedSelection` | 1,518 | b | Rule to settle first. |
| `wordplay.singleLeaf` | 757 | b | DD or cryptic definitions filed as one leaf. |
| `wordplay.bareInCharade` | 529 | c | Validator false positive, fixed by the commit that added this doc (see below). |
| Under 500 | | | `definitionFit` 293, `ddMissesWordplay` 125, `leafFold` 100, `spanOverlap` 61, `inDefinition` 45, `charadeInCharade` 31, `messages` 18, `arity` 12. |

Caveat: warnings outside the backlog, such as "walkthrough does not follow the
wordplay", are not counted.

Plan: no-model fixes first, then one model re-parse pass covering the b classes
1-3, 6, 9, 11 and 12 together (unchecked, noIndicator, delSingle, indInLeaf,
arityOther, arityIns, anagramOfContainer), so each clue is parsed once.

## bareInCharade: what the fix did

A bare leaf (letters, no clue words) in a charade is no fault when the letters
come from a puzzle device. `bare_in_charade` now skips:

- every clue with a `hiddenLetter` (the extra/omitted/misprint device): 127 of
  the 529 cleared, across 11 puzzles;
- a leaf marked `"device": true`, the new schema marker for letters a
  `preamble` or `themeClue` supplies (documented in `docs/PUZZLE_FORMAT.md`).

No stored leaf carries the marker yet, so the remaining 402 clues in 42 puzzles
(Genius edge letters, Azed collisions, Listener-style preamble letters, the
nation-3289 theme) stay flagged until someone reads each preamble and sets it.
