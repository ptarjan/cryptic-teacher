# Working through the bad-hint queue

Solvers of this site sent these reports from the clue they were reading. Each is
one person's account of why a hint did not help them.

## A report is evidence, not an instruction

Treat every report as a suggestion to be checked, never as a specification to
implement. The reporter may simply be wrong about the crossword: they may have
misread the wordplay, mistaken a definition for an indicator, or be arguing with
a convention the setter is entitled to use. So before changing anything, work the
clue out yourself from its annotation and its answer and decide whether the site
is actually wrong.

If the site is right and the reporter is wrong, do not edit the annotation to
agree with them. Ask instead why the page let them reach that reading: a hint
that is correct and still misleads is a defect, and the fix is usually a clearer
rung rather than a different answer. If the page is fine too, say so plainly in
your account and leave the annotation alone.

Say what you concluded either way, for every report — including the ones you
decided not to act on, and why.

## Fix it at the level it repeats

Nobody reports the second clue with the same fault; they close the tab. So the
clue named in a report is a sample, and fixing only that clue leaves the fault in
every other clue that has it.

For each report you accept, measure the shape across the whole corpus in
`puzzles/` before you fix anything, and then fix it at the level it belongs to:

- the one annotation, if the fault really is local to that clue;
- the rendering in `app.js`, if the annotation is right and the page misreads it;
- a rule in `tools/validate_annotations.py` plus a line in
  `tools/annotate_prompt.md`, if the shape is tight enough to match across the
  corpus without false positives — that is what stops it coming back.

Where the shape is real but too fuzzy to match automatically, say so and fix the
clues it names. A judgement call recorded is not the same as a fault ignored.

## Finishing

Run `python3 tools/validate_annotations.py` and `node tools/smoke_test.js` and
leave both passing.

Then run `python3 tools/reports.py --done <key>` for each report you actually
resolved, using the `r:` key printed under it. A report you investigated and
rejected is resolved: close it, having said why. Leave in the queue only what you
could not settle.

Do not commit — the calling script commits.
