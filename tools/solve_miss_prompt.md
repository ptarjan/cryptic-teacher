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
too. Prefer, in this order:

1. **A check in `tools/apply_solution.py`.** It costs nothing until it fires,
   while every solve pays for every word of the prompt. It may only use what
   the fill states (each answer and its definition) plus the puzzle and data
   already in the repo. Before keeping it, run it over the corpus's correct
   answers, using their annotations' definitions where it needs one, and count
   how often it fires: each firing on a correct fill costs the solver a fix
   turn, so keep it only if that rate is low, and give the numbers in your
   note. The refusal must say what to reparse. Add a case to
   `tools/test_apply_refusal.sh` and run that test. If the check replaces a
   rule in `tools/solve_prompt.md`, delete the rule.
2. **A rule in `tools/solve_prompt.md`**, only when no check is possible.
   State it in general terms, not about this clue, in the file's plain style,
   under the heading it belongs to. Sharpen an existing rule rather than add
   one that says the same thing. `tools/test_solve_misses.sh` caps the file at
   500 words, so a rule that does not fit must replace or merge with a weaker
   one.
3. **Nothing**, if the honest diagnosis is an obscure word or reference.
   Saying so is a correct outcome. Do not invent a rule to have something to
   show.

One clue is a sample. Before adding either, satisfy yourself that it would
not have misled the solve on ordinary clues.

## Finishing

1. Record the verdict. Use `fixed` if you changed a file and
   `nothing-generalises` if you did not:

       python3 tools/solve_misses.py record <puzzle> <entry> --verdict <verdict> --note "<mechanism, then what you changed>"

   Write the note as one or two sentences a person can act on.
2. Do not edit `puzzles/`, `tools/data/blind_misses.json` or
   `tools/data/diagnosed_misses.json` by hand.
3. Do not commit. The calling script does that.
