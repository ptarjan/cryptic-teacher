# Solving a puzzle that has no published answers

Prize crosswords appear without solutions, which follow about a week later.
You solve the puzzle cold, then annotate your grid in this same turn, so it
has hints in the meantime. The paper's key grades your answers when it
arrives: a wrong entry has its annotation rewritten.

## Input

    python3 tools/solve_packet.py <number>

This prints every clue with its length, plus a crossing map: which letters
each entry shares with which other entry. It is the only thing that can tell you an answer is wrong.
An entry marked `printed answer` is the paper's own: your fill must agree with it.

A grid search runs only as `python3 tools/reconstruct_grid.py --lights … [--words …]`
; never write your own search script or use multiprocessing.

## Output

Create a JSON file with the Write tool (not a heredoc), at the path your task gives you, mapping every entry id to
its answer and definition, copied verbatim from the clue:

    {"1-across": {"answer": "POPULAR FRONT", "definition": "Left-wing alliance"}, ...}

Spaces, hyphens and apostrophes are stripped. Then run the check:

    python3 tools/apply_solution.py <number> --fill <path> --check-only

It lists missing entries, wrong lengths, crossings that disagree and
definitions not at an end of their clue, and it writes nothing. Fix what it reports and run it again until it passes. The
caller reruns it and ships nothing, hints included, unless it passes.

## Then annotate

Once the check passes, write the fill in and make the copy you annotate:

    python3 tools/apply_solution.py <number> --fill <path> --no-reindex
    python3 tools/annotate_check.py --view <number>

Then do your annotation task from that copy, annotating each `(MODEL)` answer
from the wordplay you derived it by.

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

A half-parse counts as unparsed: each half of a double definition must define
the answer alone. Doubt matters most on unchecked cells, where nothing else
will catch it.

## Confidence

End your final message with every entry listed as one of:

* **CONFIDENT**: the wordplay accounts for every letter.
* **LIKELY**: the definition and crossings fit, but the wordplay is only partly
  parsed.
* **GUESS**: it fits the letters and nothing more.

Never invent wordplay to promote a GUESS: your annotation states it with
full authority. If you cannot get the check to pass
honestly, stop, annotate nothing, and name the entries that beat you. Waiting for the paper's key
is a fine outcome.
