# Working through the bad-hint queue

Each report below came from a solver who was reading that clue. It is their
account of why the hint did not help.

## Check the report before acting on it

Treat a report as evidence, not an instruction. The reporter may be wrong. They
may have misread the wordplay, taken the definition for an indicator, or be
objecting to a convention the setter is allowed to use. Work the clue out from
its answer and annotation, then decide whether the site is wrong.

- **The site is wrong:** fix it (see below).
- **The site is right but the page led them astray:** that is still a defect.
  Make the misleading rung clearer. Do not change the annotation to match their
  reading.
- **The site and page are both fine:** change nothing.

For every report, state which of these you concluded and why.

## Fix the fault everywhere it occurs

The reported clue is a sample. Other clues with the same fault go unreported,
because their readers just leave. For each report you accept, search `puzzles/`
for the same fault before fixing it. Then fix it at the right level:

- the one annotation, if the fault is only in that clue;
- the renderer in `app.js`, if the annotation is right and the page shows it
  wrongly;
- a rule in `tools/validate_annotations.py` and a line in
  `tools/annotate_prompt.md`, if the fault can be matched across the corpus
  without false positives. This is what stops it coming back.

If the fault is real but too fuzzy to match automatically, say so and fix the
clues your search found.

## Finishing

1. Leave `python3 tools/validate_annotations.py` and `node tools/smoke_test.js`
   both passing.
2. For each report you settled, run `python3 tools/reports.py --done <key>`
   with the `r:` key printed under it. A report you checked and rejected counts
   as settled. Leave only the ones you could not decide.
3. Do not commit. The calling script does that.
