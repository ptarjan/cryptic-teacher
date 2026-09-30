# Learning from a cold solve that got an answer wrong

We solved a crossword before its answers were published, following
`tools/solve_prompt.md`, and `tools/apply_solution.py` accepted the fill. The
paper's key has now arrived and one of our answers was wrong. The packet below
gives the clue, our answer, the published one, the crossings, and the solve's
own output if it was kept.

The job is to make the next solve better, not to explain this clue. The
answer is already corrected; nothing in `puzzles/` needs touching.

## Diagnose the mechanism

Parse the clue fully against the published answer first. Then name what let
the wrong answer through. It is usually one of these:

- **Misread wordplay**: a device read wrongly (a letter change taken as the
  answer itself, a container read backwards, an indicator missed).
- **Checker gap**: the wrong letters sat where `apply_solution.py` could not
  see them, such as unchecked cells, or a crossing that was also wrong.
- **Method gap**: `tools/solve_prompt.md` has no rule that would have caught
  it, e.g. an answer promoted with no wordplay behind it.
- **Unknown word or reference**: the solver did not know the answer.

## Fix the class

Fix what the diagnosis names, at the level where it will catch the next case
too:

- a rule in `tools/solve_prompt.md`, stated in general terms and not about this
  clue. Keep the file's plain style, and put the rule under the heading it
  belongs to. Only add a rule if one does not already say the same thing; if
  one does, sharpen it;
- a check in `tools/apply_solution.py`, if the class can be caught
  mechanically without refusing correct fills. Add a case to
  `tools/test_apply_refusal.sh` and run that test;
- nothing, if the honest diagnosis is an obscure word or reference that no
  rule would have produced. Saying so is a correct outcome. Do not invent a
  rule to have something to show.

One clue is a sample. Before adding a rule, satisfy yourself that it would not
have misled the solve on ordinary clues.

## Finishing

1. Record the verdict. Use `fixed` if you changed a file and
   `nothing-generalises` if you did not:

       python3 tools/solve_misses.py record <puzzle> <entry> --verdict <verdict> --note "<mechanism, then what you changed>"

   Write the note as one or two sentences a person can act on.
2. Do not edit `puzzles/`, `tools/data/blind_misses.json` or
   `tools/data/diagnosed_misses.json` by hand.
3. Do not commit. The calling script does that.
