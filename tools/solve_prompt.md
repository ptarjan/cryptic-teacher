# Solving a puzzle that has no published answers

Prize puzzles appear without solutions for about a week. Solve cold, then
annotate in this same turn; when the key arrives, wrong entries are re-annotated.

## Input

    python3 tools/solve_packet.py <number>

This prints every clue with its length and a crossing map, the only thing
that can tell you an answer is wrong. A puzzle with no grid yet (clues alone, or a jigsaw) gets its
own packet: follow its fill shape and instructions instead of entry ids.

A grid search runs only as `python3 tools/reconstruct_grid.py --lights … [--words …]`;
never write your own search script or use multiprocessing.

## Output

With the Write tool (not a heredoc), write JSON to your task's path mapping
each entry id to its answer and its definition, verbatim from the clue:

    {"1-across": {"answer": "POPULAR FRONT", "definition": "Left-wing alliance"}, ...}

Spaces, hyphens and apostrophes are stripped. Write it after your cold pass
and rewrite it after every pass: a run ending without it is thrown away. Give every entry your best answer, adding
`"guess": true` where unsure; omit an entry only when you have no candidate.
Then run the check:

    python3 tools/apply_solution.py <number> --fill <path> --check-only

It writes nothing. Fix what it reports and rerun until it passes; the caller
ships nothing, hints included, unless it passes.

## Then annotate

Once the check passes, write the fill in and make the copy you annotate:

    python3 tools/apply_solution.py <number> --fill <path> --no-reindex
    python3 tools/annotate_check.py --view <number>

Annotate each `(MODEL)` answer there from the wordplay you derived it by. The moment `annotate_check.py` says `clean`,
you are done: end with the confidence line below and nothing else —
no summary, no further pass.

## Method

1. **Cold pass.** Answer only clues you are sure of. A wrong early answer
   costs more than a blank: its crossings argue against the right answers.
2. **Crossing pass.** Work the entries with the most letters crossed.
3. **Last few.** When the crossings refuse a parse, the parse is wrong.

The check misses two wrong answers sharing their crossing letter, and an
answer fitting the letters with no wordplay. Both show as a clue you cannot parse, so treat an unparsed answer as suspect. A half-parse
counts as unparsed: each half of a double definition must define the answer
alone. Doubt matters most on unchecked cells, where nothing else catches it.

## Confidence

Your final message is one line naming each entry not CONFIDENT with its grade (e.g. `LIKELY: 20D CHEAT; GUESS: 11D TOFFEES`), or `all
CONFIDENT`. The grades:

* **CONFIDENT**: the wordplay accounts for every letter.
* **LIKELY**: definition and crossings fit; wordplay only partly parsed.
* **GUESS**: it fits the letters and nothing more.

Never invent wordplay to promote a GUESS: your annotation states it with full
authority. If you cannot pass the check honestly, annotate nothing, stop, and
name the entries that beat you. The check has already written your annotations
into the puzzle file, so take them back with
`python3 tools/annotate_check.py <ID> --withdraw "<why>"`: the puzzle file is
put back for you when the run ends and nothing you wrote ships. Never use git
for this; this run cannot. Waiting for the paper's key is a fine outcome.
