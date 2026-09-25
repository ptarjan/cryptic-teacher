# Solving a puzzle that has no published answers

Prize crosswords appear without solutions, which follow about a week later.
You solve the puzzle cold so it can have hints in the meantime.
`tools/annotate_prompt.md` then annotates your grid. The answers are published
as ours, and when the paper's key arrives it grades them. Any entry you got
wrong has its annotation thrown away and rewritten.

## Input

    python3 tools/solve_packet.py <number>

This prints every clue with its length, plus a crossing map. The map shows, for
each entry, which of its letters are shared with which letter of which other
entry. Use it. It is the only thing that can tell you an answer is wrong.

## Output

Write a JSON file, at the path your task gives you, mapping every entry id to
its answer:

    {"1-across": "POPULAR FRONT", "9-across": "AGAIN", ...}

Spaces, hyphens and apostrophes are stripped. Then run the check:

    python3 tools/apply_solution.py <number> --fill <path> --check-only

It lists missing entries, wrong lengths and crossings that disagree, and it
writes nothing. Fix what it reports and run it again until it passes. The
caller reruns it and refuses the whole fill unless it passes, so a partial or
conflicting fill publishes nothing.

## Method

1. **Cold pass.** Answer only the clues you are sure of. A wrong early answer
   costs more than a blank, because every crossing it touches then argues
   against the right answers.
2. **Crossing pass.** Work the entries with the most letters already crossed.
3. **Last few.** When the crossings refuse a parse, the parse is wrong.

The check cannot catch two errors: a pair of wrong answers that happen to share
their crossing letter, and an answer that fits the letters with no wordplay
behind it. Both show up as a clue you cannot parse, so treat an unparsed answer
as suspect.

## Confidence

When you finish, list each entry as one of:

* **CONFIDENT**: the wordplay accounts for every letter.
* **LIKELY**: the definition and crossings fit, but the wordplay is only partly
  parsed.
* **GUESS**: it fits the letters and nothing more.

Never invent wordplay to promote a GUESS. The annotation step will explain
whatever you claim with full authority. If you cannot get the check to pass
honestly, stop and name the entries that beat you. The puzzle then waits for
the paper's key, and that is a fine outcome.
